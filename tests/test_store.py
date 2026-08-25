import pytest

from openloops.store import (
    data_dir,
    default_source,
    digest_key,
    digests_store,
    load_sync_state,
    other_state,
    parse_digest_key,
    save_sync_state,
    state_dir,
    sync_state_path,
)


def test_keys_round_trip():
    key = digest_key("mac", "open", "abc-123")
    assert key == "mac/open/abc-123.md"
    assert parse_digest_key(key) == ("mac", "open", "abc-123")


def test_a_bad_state_is_refused_rather_than_written():
    with pytest.raises(ValueError):
        digest_key("mac", "running", "abc")
    with pytest.raises(ValueError):
        parse_digest_key("mac/open/abc")


def test_other_state_has_exactly_two_answers():
    assert other_state("open") == "archive"
    assert other_state("archive") == "open"


def test_the_store_creates_its_nested_directories(isolated_dirs):
    store = digests_store()
    store["mac/open/s1.md"] = "# hi"
    assert store["mac/open/s1.md"] == "# hi"
    assert list(store) == ["mac/open/s1.md"]
    del store["mac/open/s1.md"]
    assert list(store) == []


def test_data_and_state_are_different_places(isolated_dirs):
    """A cache purge must not be able to reach the digests."""
    assert data_dir() != state_dir()
    assert state_dir() not in data_dir().parents
    assert data_dir() not in state_dir().parents


def test_the_environment_overrides_every_location(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENLOOPS_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("OPENLOOPS_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("OPENLOOPS_SOURCE", "Some Host.local")
    assert data_dir() == tmp_path / "d"
    assert state_dir() == tmp_path / "s"
    assert default_source() == "some-host.local"


def test_the_source_name_is_always_filename_safe(monkeypatch):
    monkeypatch.setenv("OPENLOOPS_SOURCE", "a/b c!")
    assert default_source() == "a-b-c"
    monkeypatch.setenv("OPENLOOPS_SOURCE", "///")
    assert default_source() == "local"


def test_sync_state_survives_a_round_trip_and_tolerates_corruption(isolated_dirs):
    assert load_sync_state() == {}
    save_sync_state({"a": "1"})
    assert load_sync_state() == {"a": "1"}

    sync_state_path().write_text("not json at all")
    assert load_sync_state() == {}, "a corrupt cache reads as an absent one"


def test_the_default_store_reads_and_writes_utf8_whatever_the_locale(tmp_path):
    """A digest contains em dashes; the locale encoding is not a safe default."""
    store = digests_store(rootdir=tmp_path)
    store["m/open/s1.md"] = "an em dash — and a non-breaking space ."
    assert "—" in store["m/open/s1.md"]
    raw = (tmp_path / "m" / "open" / "s1.md").read_bytes()
    assert raw.decode("utf-8").startswith("an em dash")


def test_deleting_a_digest_deletes_it(tmp_path):
    """Not "moves it to Trash" — that is a second copy of the content, outside the store."""
    store = digests_store(rootdir=tmp_path)
    store["m/open/s1.md"] = "body"
    path = tmp_path / "m" / "open" / "s1.md"
    assert path.exists()
    del store["m/open/s1.md"]
    assert not path.exists()


def test_the_store_refuses_a_key_that_would_escape_its_root(tmp_path):
    from openloops.store import DigestFiles

    store = DigestFiles(tmp_path)
    for key in ("../escaped.md", "a/../../escaped.md", "", "."):
        with pytest.raises(KeyError):
            store[key] = "x"


def test_store_keys_are_posix_on_every_platform(tmp_path):
    store = digests_store(rootdir=tmp_path)
    store["m/archive/s1.md"] = "body"
    assert list(store) == ["m/archive/s1.md"]
    assert "m/archive/s1.md" in store
    assert len(store) == 1
