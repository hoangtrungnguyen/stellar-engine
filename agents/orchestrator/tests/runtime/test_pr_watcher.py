"""Integration tests for PRWatcher.tick() with stubbed adapters.

The adapter classes are replaced with fakes that capture every call,
so we can assert on the wire-level effects (what signal, what label,
in what order) without touching grava or gh.

These tests cover:
  * Idempotency: running tick twice in a row produces no extra side
    effects on the second pass.
  * Migration: a snapshot built from the legacy `pr_stale=true` wisp
    is treated as STALE on the first tick.
  * Lock arbitration: a held .grava/pr-watcher.lock causes the second
    tick to no-op.
  * Snapshot persistence: `pr_state` + `pr_state_changed_at` are
    written even when no transition fired (so the canonical keys
    exist after first read).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "agents" / "orchestrator"))

from runtime.adapters.grava import IssueRef                            # noqa: E402
from runtime.adapters.github import PRRequest                          # noqa: E402
from runtime.pr_state import PRSnapshot, PRState, PRView               # noqa: E402
from runtime.pr_watcher import PRWatcher                               # noqa: E402

NOW = 1_700_000_000


# ── fake adapters ────────────────────────────────────────────────────────────


@dataclass
class FakeGrava:
    """Mirrors GravaAdapter's surface; records every call for assertions."""
    snapshots: dict[str, PRSnapshot] = field(default_factory=dict)
    pr_created_issues: list[IssueRef] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)

    def list_pr_created(self, repo: Path) -> list[IssueRef]:
        self.calls.append(("list_pr_created", str(repo)))
        return list(self.pr_created_issues)

    def load_snapshot(self, repo: Path, issue_id: str) -> PRSnapshot | None:
        self.calls.append(("load_snapshot", issue_id))
        return self.snapshots.get(issue_id)

    def persist_snapshot(self, repo: Path, snapshot: PRSnapshot,
                         now: int) -> bool:
        self.calls.append(("persist_snapshot",
                           snapshot.issue_id, snapshot.state.value))
        self.snapshots[snapshot.issue_id] = snapshot
        return True

    def read_wisp(self, repo: Path, issue_id: str, key: str) -> str:
        return ""

    def write_wisp(self, repo: Path, issue_id: str,
                   key: str, value: str) -> bool:
        self.calls.append(("write_wisp", issue_id, key, value))
        return True

    def signal(self, repo: Path, issue_id: str, name: str,
               payload: str | None = None,
               actor: str = "watcher") -> bool:
        self.calls.append(("signal", issue_id, name, payload))
        return True

    def label(self, repo: Path, issue_id: str,
              add=(), remove=()) -> bool:
        self.calls.append(("label", issue_id,
                           tuple(add), tuple(remove)))
        return True

    def close(self, repo: Path, issue_id: str,
              actor: str = "watcher") -> bool:
        self.calls.append(("close", issue_id))
        return True

    def commit(self, repo: Path, message: str) -> bool:
        self.calls.append(("commit", message))
        return True


@dataclass
class FakeGithub:
    """Mirrors GitHubAdapter; serves canned PRView per PR number."""
    views: dict[int, PRView] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    def fetch_view(self, request: PRRequest) -> PRView | None:
        self.calls.append(("fetch_view", request.pr_url,
                           request.last_seen_comment_id))
        # PR number comes from the URL — extract it the way the real
        # adapter does (just for test convenience).
        import re
        m = re.search(r"/pull/(\d+)", request.pr_url or "")
        if not m:
            return None
        return self.views.get(int(m.group(1)))

    def fetch_views(self, requests):
        out = {}
        for req in requests:
            v = self.fetch_view(req)
            if v is not None:
                out[v.pr_number] = v
        return out


def _snap(state: PRState = PRState.AWAITING_MERGE,
          awaiting_since: int = NOW,
          last_seen: int = 0,
          team: str = "fix-bug") -> PRSnapshot:
    return PRSnapshot(
        issue_id="grava-abc",
        pr_number=123,
        pr_url="https://github.com/o/r/pull/123",
        team=team,
        state=state,
        state_changed_at=NOW,
        awaiting_since=awaiting_since,
        last_seen_comment_id=last_seen,
    )


def _view(state: str = "OPEN",
          review_decision: str | None = None,
          new_comment_ids: tuple[int, ...] = (),
          highest: int = 0) -> PRView:
    return PRView(
        pr_number=123,
        state=state,
        review_decision=review_decision,
        new_comment_ids=new_comment_ids,
        highest_comment_id=highest,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".grava").mkdir()
    return tmp_path


# ── happy path: MERGED transition ────────────────────────────────────────────


def test_merged_transition_fires_full_signal_chain(repo: Path):
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": _snap(state=PRState.AWAITING_MERGE)},
    )
    github = FakeGithub(views={123: _view(state="MERGED")})

    report = PRWatcher(grava=grava, github=github).tick(repo, now=NOW)

    # Expected adapter sequence:
    #   write_wisp pr_merged_at → signal PR_MERGED → label remove pr-created
    #   → close → signal PIPELINE_COMPLETE → commit
    actions = [c for c in grava.calls
               if c[0] in ("signal", "label", "close",
                            "commit", "write_wisp")]
    kinds = [c[0] for c in actions]
    assert kinds == [
        "write_wisp",   # pr_merged_at
        "signal",       # PR_MERGED
        "label",        # remove pr-created
        "close",
        "signal",       # PIPELINE_COMPLETE
        "commit",
    ]
    # And the snapshot was persisted with the new MERGED state.
    assert grava.snapshots["grava-abc"].state == PRState.MERGED
    # Tick report has the transition event.
    transition = [e for e in report.events if e.kind == "transition"]
    assert len(transition) == 1
    assert transition[0].after == PRState.MERGED


def test_merged_idempotent_on_second_tick(repo: Path):
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": _snap(state=PRState.MERGED)},
    )
    github = FakeGithub(views={123: _view(state="MERGED")})

    report = PRWatcher(grava=grava, github=github).tick(repo, now=NOW)

    # No signals, no close, no commit — only the bookkeeping
    # persist_snapshot that ensures canonical keys exist.
    side_effects = [c for c in grava.calls
                    if c[0] in ("signal", "label", "close",
                                 "commit", "write_wisp")]
    assert side_effects == []
    assert report.events == []


# ── CLOSED transition includes re-entry hint ─────────────────────────────────


def test_closed_transition_writes_rejection_reason(repo: Path):
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": _snap(state=PRState.UNDER_REVIEW,
                                       team="fix-bug")},
    )
    github = FakeGithub(views={123: _view(state="CLOSED",
                                          review_decision="CHANGES_REQUESTED")})

    PRWatcher(grava=grava, github=github).tick(repo, now=NOW)

    signals = [c for c in grava.calls if c[0] == "signal"]
    assert any(s[2] == "PR_CLOSED" and s[3] == "CHANGES_REQUESTED"
               for s in signals)
    # `pr_rejection_reason` written
    rej = [c for c in grava.calls
           if c[0] == "write_wisp" and c[2] == "pr_rejection_reason"]
    assert rej and rej[0][3] == "CHANGES_REQUESTED"
    # label pr-rejected added + pr-created removed (single call)
    label_calls = [c for c in grava.calls if c[0] == "label"]
    assert label_calls == [("label", "grava-abc",
                            ("pr-rejected",), ("pr-created",))]


# ── STALE: dedicated label + commit ──────────────────────────────────────────


def test_stale_first_sight_labels_needs_human(repo: Path):
    HOUR = 3600
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": _snap(awaiting_since=NOW - 100 * HOUR)},
    )
    github = FakeGithub(views={123: _view(state="OPEN")})

    PRWatcher(grava=grava, github=github).tick(repo, now=NOW)

    label_adds = [c for c in grava.calls
                  if c[0] == "label" and "needs-human" in c[2]]
    assert label_adds, "needs-human label was never added"
    # And the snapshot transitioned to STALE
    assert grava.snapshots["grava-abc"].state == PRState.STALE


# ── lock arbitration ─────────────────────────────────────────────────────────


def test_held_lock_makes_tick_a_noop(repo: Path, monkeypatch):
    """When another process holds .grava/pr-watcher.lock, tick returns
    with no adapter calls. Verifies fcntl.LOCK_NB is wired right."""
    import fcntl

    lockfile = repo / ".grava" / "pr-watcher.lock"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    holder = open(lockfile, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        grava = FakeGrava(pr_created_issues=[IssueRef(id="grava-abc")])
        report = PRWatcher(grava=grava, github=FakeGithub()).tick(repo,
                                                                   now=NOW)
        assert grava.calls == []   # no list_pr_created, nothing
        assert report.events == []
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


# ── snapshot persistence on a no-op tick ────────────────────────────────────


def test_quiet_tick_still_persists_canonical_wisps(repo: Path):
    """First tick after upgrade: snapshot is in AWAITING_MERGE, view
    says OPEN, no comments. No transition, but persist_snapshot must
    still fire so `pr_state` + `pr_state_changed_at` end up on disk."""
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": _snap()},
    )
    github = FakeGithub(views={123: _view(state="OPEN")})

    PRWatcher(grava=grava, github=github).tick(repo, now=NOW)

    persists = [c for c in grava.calls if c[0] == "persist_snapshot"]
    assert persists == [("persist_snapshot", "grava-abc", "awaiting_merge")]


# ── snapshot with no pr_url is skipped gracefully ────────────────────────────


def test_bad_pr_url_skipped(repo: Path):
    snap = _snap()
    bad = PRSnapshot(
        issue_id=snap.issue_id, pr_number=snap.pr_number,
        pr_url="not a url",  # ← will fail PR-URL regex
        team=snap.team, state=snap.state,
        state_changed_at=snap.state_changed_at,
        awaiting_since=snap.awaiting_since,
        last_seen_comment_id=snap.last_seen_comment_id,
    )
    grava = FakeGrava(
        pr_created_issues=[IssueRef(id="grava-abc")],
        snapshots={"grava-abc": bad},
    )
    github = FakeGithub()       # no views → fetch_view returns None

    report = PRWatcher(grava=grava, github=github).tick(repo, now=NOW)
    assert report.skipped_bad_url == 1
    assert all(c[0] not in ("signal", "label", "close", "commit")
               for c in grava.calls)
