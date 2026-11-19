"""Reminders: a loop is armed on the channel within the horizon, cancelled when done, re-armed when snoozed, delivered late (and said so) when it was never armed, and never pushed when it is a proposal or has no time."""

from datetime import datetime, timedelta, timezone

import pytest

from openloops import loops as L
from openloops import remind as R

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
SETTINGS = R.RemindSettings(tz="UTC")


class FakeDelivery:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def _record(self, *call):
        if self.fail:
            raise R.DeliveryError("offline")
        self.calls.append(call)

    def schedule(self, loop, *, at, title, text):
        self._record("schedule", loop.id, at, title, text)

    def now(self, loop, *, title, text):
        self._record("now", loop.id, title, text)

    def cancel(self, loop):
        self._record("cancel", loop.id)


def _kit(**kw):
    return dict(store={}, deliver=FakeDelivery(**kw), settings=SETTINGS)


def test_a_reminder_within_three_days_is_scheduled_on_the_channel_at_once():
    kit = _kit()
    made = R.remind("Send the signed draft", in_="3h", now=NOW, **kit)
    (call,) = kit["deliver"].calls
    assert call[0] == "schedule" and call[2] == NOW + timedelta(hours=3)
    assert made["armed"] and made["state"] == "submitted"
    assert (
        made["echo"].startswith("Thu 19 Nov 15:00") and "push via ntfy:" in made["echo"]
    )


def test_the_title_stays_off_the_public_relay_unless_revealed():
    kit = _kit()
    R.remind("Call the lawyer about Acme", in_="1h", now=NOW, **kit)
    R.remind("Stretch", in_="1h", reveal=True, now=NOW, **kit)
    hidden, shown = kit["deliver"].calls
    assert "Acme" not in hidden[3] + hidden[4]
    assert shown[3] == "Stretch" and shown[4] == "Stretch"


def test_done_before_the_time_cancels_the_scheduled_push():
    kit = _kit()
    made = R.remind("t2", in_="5m", now=NOW, **kit)
    closed = R.done(made["id"], now=NOW + timedelta(minutes=1), **kit)
    assert closed["state"] == "completed" and not closed["armed"]
    assert [c[0] for c in kit["deliver"].calls] == ["schedule", "cancel"]
    # ntfy.sh delivers a cancelled scheduled push anyway: the owner is told, not misled.
    assert "may arrive at Thu 19 Nov 12:05" in closed["warning"]
    with pytest.raises(ValueError, match="already completed"):
        R.done(made["id"], now=NOW, **kit)


def test_snooze_rearms_under_the_same_id():
    kit = _kit()
    made = R.remind("x", in_="10m", now=NOW, **kit)
    later = R.snooze(made["id"], for_="1h", now=NOW + timedelta(minutes=10), **kit)
    first, second = kit["deliver"].calls
    assert first[1] == second[1] == made["id"]
    assert second[2] == NOW + timedelta(minutes=70) and later["snoozes"] == 1
    # Snoozed after it fired: nothing scheduled was left behind, so no warning.
    assert "warning" not in later


def test_far_reminders_wait_for_the_tick_then_fire_records_and_late_ones_say_so():
    kit = _kit()
    far = R.remind("far", in_="5d", now=NOW, **kit)
    assert not far["armed"] and not kit["deliver"].calls
    assert "hourly tick arms it" in far["echo"]
    # Three days later the tick arms it; after its time the tick records it as fired.
    report = R.tick(now=NOW + timedelta(days=3), **kit)
    assert report["actions"] == {"arm": 1}
    report = R.tick(now=NOW + timedelta(days=5, minutes=1), **kit)
    assert report["actions"] == {"woke": 1}
    assert kit["store"][far["id"]].state == "input-required"
    # A loop never armed (the machine slept past it) is delivered late, saying how late.
    kit["store"]["late"] = L.new_loop(
        "late", remind_at=NOW + timedelta(days=4), now=NOW, id="late"
    )
    R.tick(now=NOW + timedelta(days=4, minutes=30), **kit)
    last = kit["deliver"].calls[-1]
    assert last[0] == "now" and "late by 30 min" in last[3]


def test_a_failed_channel_is_logged_and_retried_by_the_next_tick():
    kit = _kit(fail=True)
    made = R.remind("x", in_="2h", now=NOW, **kit)
    assert not made["armed"] and "NOT scheduled" in made["echo"]
    kit["deliver"].fail = False
    report = R.tick(now=NOW + timedelta(minutes=5), **kit)
    assert report["actions"] == {"arm": 1} and not report["failed"]


def test_proposals_and_untimed_loops_never_push():
    kit = _kit()
    kit["store"]["p"] = L.new_loop(
        "maybe",
        remind_at=NOW + timedelta(hours=1),
        proposed_by="agent",
        now=NOW,
        id="p",
    )
    R.remind("someday", now=NOW, **kit)
    R.tick(now=NOW + timedelta(hours=2), **kit)
    assert not kit["deliver"].calls


def test_times_and_durations():
    assert R.parse_in("1h30m") == timedelta(minutes=90)
    for bad in ("soon", "3x", "1h 3"):
        with pytest.raises(ValueError):
            R.parse_in(bad)
    assert R.parse_at("09:30", now=NOW, zone=timezone.utc) == datetime(
        2026, 11, 20, 9, 30, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError, match="not in the future"):
        R.remind("x", at="2020-01-01T00:00", now=NOW, **_kit())
    with pytest.raises(ValueError, match="not both"):
        R.remind("x", at="10:00", in_="1h", now=NOW, **_kit())


def test_the_file_store_round_trips_and_lists(tmp_path):
    store = R.loops_store(tmp_path)
    kit = dict(store=store, deliver=FakeDelivery(), settings=SETTINGS)
    made = R.remind("persisted", in_="1h", now=NOW, **kit)
    assert (tmp_path / f"{made['id']}.json").exists()
    assert [r["id"] for r in R.list_loops(store=store)] == [made["id"]]
    R.done(made["id"][:12], now=NOW, **kit)  # a unique prefix finds it
    assert R.list_loops(store=store) == []
    assert R.list_loops(state="closed", store=store)[0]["state"] == "completed"


def test_the_ntfy_delivery_uses_one_sequence_id_per_loop_and_cancels_by_it():
    sent, cancelled = [], []

    class Result:
        ok, error = True, None

    class Channel:
        def parse_ref(self, topic):
            return topic

        def cancel(self, ref, sequence_id):
            cancelled.append((ref, sequence_id))

    delivery = R.NtfyDelivery(
        "ntfy:",
        send=lambda ref, text, **kw: sent.append((ref, text, kw)) or Result(),
        get_channel=lambda name: Channel(),
    )
    loop = L.new_loop("x", now=NOW, id="loop-1")
    delivery.schedule(loop, at=NOW, title="Reminder", text="due")
    delivery.cancel(loop)
    assert sent[0][2]["native"] == {"sequence_id": "loop-1", "at": int(NOW.timestamp())}
    assert cancelled == [("", "loop-1")]


def test_a_loop_is_validated_and_survives_unknown_keys():
    with pytest.raises(ValueError):
        L.new_loop("x", state="done")
    loop = L.new_loop("x", now=NOW, id="a")
    again = L.Loop.from_dict({**loop.to_dict(), "a_future_field": 1})
    assert again.extra == {"a_future_field": 1}
    # Written back, a newer writer's field survives an older reader.
    assert L.Loop.from_dict(again.to_dict()).to_dict()["a_future_field"] == 1


def test_snoozing_an_armed_loop_beyond_the_horizon_cancels_its_old_push():
    kit = _kit()
    made = R.remind("x", in_="1h", now=NOW, **kit)
    later = R.snooze(made["id"], for_="5d", now=NOW + timedelta(minutes=5), **kit)
    assert [c[0] for c in kit["deliver"].calls] == ["schedule", "cancel"]
    assert not later["armed"] and "hourly tick arms it" in later["echo"]


def test_one_unreadable_file_does_not_stop_the_others(tmp_path):
    store = R.loops_store(tmp_path)
    kit = dict(store=store, deliver=FakeDelivery(), settings=SETTINGS)
    good = R.remind("good", in_="5d", now=NOW, **kit)
    (tmp_path / "broken.json").write_text("{not json")
    report = R.tick(now=NOW + timedelta(days=3), **kit)
    assert report["actions"] == {"arm": 1} and report["skipped"] == [
        "broken: JSONDecodeError"
    ]
    assert [r["id"] for r in R.list_loops(store=store)] == [good["id"]]


def test_a_done_that_lands_while_the_tick_runs_is_not_undone():
    kit = _kit()
    made = R.remind("x", in_="5d", now=NOW, **kit)

    class DoneMidway(dict):
        """Hands the tick the open loop first, then the version an `ol done` wrote."""

        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            loop = super().__getitem__(key)
            if self.reads == 2:  # the tick's re-read just before applying
                closed = L.complete(loop, NOW + timedelta(days=3))
                super().__setitem__(key, closed)
                return closed
            return loop

    store = DoneMidway(kit["store"])
    R.tick(
        store=store,
        deliver=kit["deliver"],
        settings=SETTINGS,
        now=NOW + timedelta(days=3),
    )
    assert store[made["id"]].state == "completed"
    assert not kit["deliver"].calls  # it was never armed, so nothing to cancel either


def test_a_named_zone_applies_its_own_daylight_saving():
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        paris = ZoneInfo("Europe/Paris")
    except ZoneInfoNotFoundError:  # Windows without the tzdata package
        pytest.skip("no IANA time zone database here")
    summer = R.parse_at("2027-07-01", now=NOW, zone=paris)
    winter = R.parse_at("2027-01-04", now=NOW, zone=paris)
    assert summer.utcoffset() == timedelta(hours=2) and winter.utcoffset() == timedelta(
        hours=1
    )
    assert (
        R.attach(datetime(2027, 7, 1, 9), None).utcoffset()
        == datetime(2027, 7, 1, 9).astimezone().utcoffset()
    )


def test_bad_references_and_times_are_refused_plainly():
    kit = _kit()
    made = R.remind("x", in_="1h", now=NOW, **kit)
    with pytest.raises(KeyError):
        R.done("", now=NOW, **kit)
    assert R.find(kit["store"], made["id"].rsplit("-", 1)[1]).id == made["id"]
    for bad in ("24:00", "20261120", "tomorrow", "10"):
        with pytest.raises(ValueError, match="not a time"):
            R.parse_at(bad, now=NOW, zone=None)


def test_the_topic_never_appears_in_the_echo():
    settings = R.RemindSettings(channel="ntfy:secret-topic-123", tz="UTC")
    made = R.remind(
        "x", in_="1h", now=NOW, store={}, deliver=FakeDelivery(), settings=settings
    )
    assert "secret-topic-123" not in made["echo"] + str(made["last_note"])


def test_a_failing_channel_is_counted_not_logged_every_hour():
    kit = _kit(fail=True)
    made = R.remind("x", in_="2h", now=NOW, **kit)
    for minutes in (60, 61, 62):
        R.tick(now=NOW + timedelta(minutes=minutes - 59), **kit)
    log = kit["store"][made["id"]].log
    assert [e["event"] for e in log] == ["created", "delivery-failed"]
    assert log[-1]["count"] == 4


def test_the_cli_lists_times_in_the_owners_zone(monkeypatch):
    from openloops.__main__ import _loop_line

    monkeypatch.setenv("OPENLOOPS_TZ", "UTC")
    row = {
        "id": "a",
        "state": "submitted",
        "remind_at": "2026-11-20T08:00:00Z",
        "title": "t",
        "armed": True,
        "reveal": True,
    }
    assert "2026-11-20 08:00" in _loop_line(row)
