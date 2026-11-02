"""The transcript index is built once per pass, not once per session key (issue #33)."""

import hashlib
from pathlib import Path

from fixtures import (
    asking_session,
    closed_session,
    interrupted_session,
    write_transcripts,
)

from openloops._sync import retained, sync
from openloops.transcripts import ClaudeCodeTranscripts

BUILDERS = (closed_session, asking_session, interrupted_session)


def synthetic_tree(root: Path, *, projects: int, per_project: int) -> int:
    """Fake transcripts spread over several project folders; returns the session count."""
    n = 0
    for p in range(projects):
        sessions = {}
        for _ in range(per_project):
            key = f"sess-{n:04d}"
            sessions[key] = BUILDERS[n % len(BUILDERS)](key)
            n += 1
        write_transcripts(root, sessions, project=f"-w-proj{p:03d}")
    return n


def count_walks(monkeypatch, root: Path) -> list[int]:
    """Count how many times the projects root is listed (one listing = one walk)."""
    calls = [0]
    real = Path.iterdir

    def counting_iterdir(self):
        if self == root:
            calls[0] += 1
        return real(self)

    monkeypatch.setattr(Path, "iterdir", counting_iterdir)
    return calls


def run_sync(src, tmp_path, name="a"):
    store: dict[str, str] = {}
    result = sync(
        transcript_source=src,
        digests_store=store,
        source="demo",
        state_dir=str(tmp_path / f"state-{name}"),
    )
    return result, store


def store_hash(store) -> str:
    h = hashlib.sha256()
    for key in sorted(store):
        h.update(f"{key}\0{store[key]}\0".encode())
    return h.hexdigest()


def test_a_sync_walks_the_projects_tree_a_constant_number_of_times(
    projects_dir, tmp_path, monkeypatch
):
    walks = {}
    for projects, per_project in ((2, 2), (6, 4)):
        root = tmp_path / f"tree-{projects}"
        root.mkdir()
        n = synthetic_tree(root, projects=projects, per_project=per_project)
        src = ClaudeCodeTranscripts(root=root)
        calls = count_walks(monkeypatch, root)
        result, _ = run_sync(src, tmp_path, name=str(projects))
        assert result["scanned"] == n
        walks[n] = calls[0]
    small, large = sorted(walks)
    assert walks[small] == walks[large], f"walks grow with sessions: {walks}"
    assert walks[large] <= 2


def test_retained_does_not_walk_per_digest(projects_dir, tmp_path, monkeypatch):
    n = synthetic_tree(projects_dir, projects=4, per_project=5)
    src = ClaudeCodeTranscripts()
    _, store = run_sync(src, tmp_path)
    assert len(store) == n
    calls = count_walks(monkeypatch, projects_dir)
    assert retained(store, src, source="demo") == []
    assert calls[0] <= 1


def test_refresh_picks_up_a_transcript_written_after_the_index_was_built(
    projects_dir,
):
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    src = ClaudeCodeTranscripts()
    assert "s1" in src and "s9" not in src
    write_transcripts(projects_dir, {"s9": closed_session("s9")})
    src.refresh()
    assert "s9" in src
    assert list(src) == ["s1", "s9"]


def test_iterating_starts_a_new_pass_and_sees_new_transcripts(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    src = ClaudeCodeTranscripts()
    assert list(src) == ["s1"]
    write_transcripts(projects_dir, {"s2": asking_session("s2")})
    assert list(src) == ["s1", "s2"]
    assert src["s2"].key == "s2"


def test_sync_output_is_unchanged_by_the_cached_index(projects_dir, tmp_path):
    """The cached index and a per-call rebuild produce byte-identical digests."""
    synthetic_tree(projects_dir, projects=5, per_project=4)

    class Uncached(ClaudeCodeTranscripts):
        """The pre-fix behaviour: rebuild the index on every access."""

        def __getitem__(self, key):
            self.refresh()
            return super().__getitem__(key)

        def revision(self, key=None):
            self.refresh()
            return super().revision(key)

        def __contains__(self, key):
            self.refresh()
            return super().__contains__(key)

    _, cached = run_sync(ClaudeCodeTranscripts(), tmp_path, name="cached")
    _, uncached = run_sync(Uncached(), tmp_path, name="uncached")
    assert len(cached) == 20
    assert store_hash(cached) == store_hash(uncached)


# Captured by running `sync` on this exact synthetic tree with the code as it was
# before the index was cached (the per-key rebuild).
PRE_FIX_STORE_HASH = "a38cf221ab22b4446a1a7cca47db0c013fa273462dd899301aa8100236076399"


def test_sync_output_matches_the_one_recorded_before_the_fix(projects_dir, tmp_path):
    synthetic_tree(projects_dir, projects=5, per_project=4)
    _, store = run_sync(ClaudeCodeTranscripts(), tmp_path)
    assert store_hash(store) == PRE_FIX_STORE_HASH
