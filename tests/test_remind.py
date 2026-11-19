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
    with pytest.raises(ValueError, match="past"):
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
    assert again == loop
