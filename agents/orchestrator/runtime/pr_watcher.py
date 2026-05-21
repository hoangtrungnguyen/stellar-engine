"""
PRWatcher — composition layer that runs one pr-lifecycle tick against
a single repo (Phase D6).

Flow per tick:
  1. Acquire `.grava/pr-watcher.lock` via fcntl.flock(LOCK_EX|LOCK_NB).
     If held by another process, return immediately with zero events.
     This replaces the bash watcher's pidfile dance — no PID recycling
     bugs, OS releases the lock on process death.
  2. List all `pr-created` issues via GravaAdapter.
  3. For each issue:
        a. GravaAdapter.load_snapshot → PRSnapshot (or skip if no
           pr_number wisp).
        b. GitHubAdapter.fetch_view  → PRView.
        c. pr_state.next_state(snapshot, view, now)  → (new_state, events).
        d. Apply events through adapters (signals, labels, close, commit).
        e. Persist the new snapshot back to grava wisps.
  4. Release the lock, return the accumulated events for caller logging.

The watcher is intentionally a class (not a function) so the daemon can
inject mock adapters in tests and real ones in production. Same shape
will let D2 (heartbeat) share the lock + tick pattern when its time
comes.
"""
from __future__ import annotations

import fcntl
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .adapters.grava import (
    GravaAdapter,
    IssueRef,
    WISP_PR_LAST_SEEN_COMMENT,
)
from .adapters.github import GitHubAdapter, PRRequest
from .pr_state import (
    Event,
    PRSnapshot,
    PRState,
    PRView,
    WatcherPolicy,
    next_state,
)

log = logging.getLogger("stellar.orchestrator.pr_watcher")


# ── per-team re-entry hints (printed when a PR is rejected) ───────────────────
# Plain dict instead of a switch so adding a team is a single line and
# tests can monkey-patch without touching production logic.
TEAM_REENTRY_HINTS: dict[str, str] = {
    "fix-bug":        "/deploy {issue} --retry",
    "epic-task":      "/ship {issue} --retry",
    "qa":             "/qa {issue} --rerun",
    # task-generator: no auto-retry; manual intervention.
}


@dataclass
class TickReport:
    """What one tick did, for the daemon's tick log + state file."""
    repo: Path
    events: list[Event] = field(default_factory=list)
    issues_scanned: int = 0
    skipped_no_pr_number: int = 0
    skipped_bad_url: int = 0
    errors: list[str] = field(default_factory=list)


# ── lock ──────────────────────────────────────────────────────────────────────


@contextmanager
def _flock(lockfile: Path) -> Iterator[bool]:
    """Yield True iff we acquired the lock. False ⇒ another tick is
    running (caller skips the tick — singleton-per-repo, not a queue).

    LOCK_NB so we never block the daemon's main loop. The lock file
    survives process death; the OS releases the lock itself.
    """
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    try:
        fd = open(lockfile, "w")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield True
        except BlockingIOError:
            yield False
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fd.close()


# ── the composition class ────────────────────────────────────────────────────


class PRWatcher:
    """Runs one repo's pr-lifecycle tick. Adapters are injectable for tests."""

    def __init__(
        self,
        grava: GravaAdapter | None = None,
        github: GitHubAdapter | None = None,
        policy: WatcherPolicy | None = None,
    ) -> None:
        self.grava = grava or GravaAdapter()
        self.github = github or GitHubAdapter()
        self.policy = policy or WatcherPolicy()

    # ── public entry ──

    def tick(self, repo: Path, *, now: int | None = None) -> TickReport:
        """One full pass over `repo`'s pr-created issues. Idempotent."""
        if now is None:
            now = int(time.time())
        report = TickReport(repo=repo)

        lockfile = repo / ".grava" / "pr-watcher.lock"
        with _flock(lockfile) as acquired:
            if not acquired:
                log.info("%s: another pr-watcher tick is running; skipping",
                         repo.name)
                return report

            issues = self.grava.list_pr_created(repo)
            if not issues:
                return report
            log.debug("%s: %d pr-created issue(s) to scan",
                      repo.name, len(issues))

            for ref in issues:
                report.issues_scanned += 1
                self._tick_one_issue(repo, ref, now, report)

        return report

    # ── per-issue ──

    def _tick_one_issue(self, repo: Path, ref: IssueRef,
                        now: int, report: TickReport) -> None:
        snapshot = self.grava.load_snapshot(repo, ref.id)
        if snapshot is None:
            log.info("%s: no pr_number wisp; skipping", ref.id)
            report.skipped_no_pr_number += 1
            return
        # If awaiting_since was never recorded (legacy data with no
        # migration source), seed it to `now`. Without this the stale
        # threshold would be tripped on the very first tick.
        if snapshot.awaiting_since == 0:
            snapshot = self._with_awaiting_since(snapshot, now)

        request = PRRequest(
            pr_url=snapshot.pr_url,
            last_seen_comment_id=snapshot.last_seen_comment_id,
        )
        view = self.github.fetch_view(request)
        if view is None:
            log.warning("%s: bad pr_url %r — skipping", ref.id, snapshot.pr_url)
            report.skipped_bad_url += 1
            return

        new_state, events = next_state(snapshot, view, now, self.policy)
        report.events.extend(events)

        # Apply side effects in order: a TRANSITION carries the heavy
        # lifting (signals, label removes, close); auxiliary events
        # come after.
        self._apply_events(repo, snapshot, view, events, now)

        # Persist the new state — even when events is empty, this is a
        # cheap no-op (writing the same value twice) that ensures the
        # canonical wisp keys exist after first migration.
        updated = self._new_snapshot(snapshot, view, new_state, now)
        self.grava.persist_snapshot(repo, updated, now)

    @staticmethod
    def _with_awaiting_since(s: PRSnapshot, now: int) -> PRSnapshot:
        # Frozen dataclass → can't mutate; build a fresh one.
        return PRSnapshot(
            issue_id=s.issue_id,
            pr_number=s.pr_number,
            pr_url=s.pr_url,
            team=s.team,
            state=s.state,
            state_changed_at=s.state_changed_at,
            awaiting_since=now,
            last_seen_comment_id=s.last_seen_comment_id,
        )

    @staticmethod
    def _new_snapshot(s: PRSnapshot, view: PRView,
                      new_state: PRState, now: int) -> PRSnapshot:
        # Update state + state_changed_at + last_seen_comment_id.
        state_changed_at = now if new_state != s.state else s.state_changed_at
        last_seen = max(s.last_seen_comment_id, view.highest_comment_id)
        return PRSnapshot(
            issue_id=s.issue_id,
            pr_number=s.pr_number,
            pr_url=s.pr_url,
            team=s.team,
            state=new_state,
            state_changed_at=state_changed_at,
            awaiting_since=s.awaiting_since,
            last_seen_comment_id=last_seen,
        )

    # ── side effects (event → adapter calls) ──

    def _apply_events(self, repo: Path, snapshot: PRSnapshot,
                      view: PRView, events: list[Event],
                      now: int) -> None:
        for ev in events:
            if ev.kind == Event.TRANSITION:
                self._apply_transition(repo, snapshot, ev, now)
            elif ev.kind == Event.STALE_FIRST_SEEN:
                self._apply_stale(repo, snapshot, ev)
            elif ev.kind == Event.NEW_COMMENTS:
                self._apply_new_comments(repo, snapshot, view, ev)
            elif ev.kind == Event.REVIEW_REQUESTED:
                log.info("%s: review CHANGES_REQUESTED (PR #%d)",
                         snapshot.issue_id, snapshot.pr_number)
            elif ev.kind == Event.UNKNOWN:
                log.warning("%s: PR #%d gh view returned %r — preserving state %s",
                            snapshot.issue_id, snapshot.pr_number,
                            ev.payload.get("raw_state"), snapshot.state.value)

    def _apply_transition(self, repo: Path, snapshot: PRSnapshot,
                          ev: Event, now: int) -> None:
        before, after = ev.before, ev.after
        log.info("%s: %s → %s (PR #%d)",
                 snapshot.issue_id,
                 before.value if before else "?",
                 after.value if after else "?",
                 snapshot.pr_number)

        if after == PRState.MERGED:
            self.grava.write_wisp(repo, snapshot.issue_id,
                                  "pr_merged_at", str(now))
            self.grava.signal(repo, snapshot.issue_id, "PR_MERGED")
            self.grava.label(repo, snapshot.issue_id,
                             remove=["pr-created"])
            self.grava.close(repo, snapshot.issue_id)
            self.grava.signal(repo, snapshot.issue_id, "PIPELINE_COMPLETE",
                              payload=snapshot.issue_id)
            self.grava.commit(repo,
                              f"watcher: {snapshot.issue_id} merged + closed "
                              f"(team={snapshot.team or 'unknown'})")
            return

        if after == PRState.CLOSED:
            reason = ev.payload.get("reason", "closed_without_merge")
            self.grava.signal(repo, snapshot.issue_id, "PR_CLOSED",
                              payload=reason)
            self.grava.write_wisp(repo, snapshot.issue_id,
                                  "pr_rejection_reason", reason)
            self.grava.label(repo, snapshot.issue_id,
                             add=["pr-rejected"], remove=["pr-created"])
            self.grava.commit(repo,
                              f"watcher: {snapshot.issue_id} PR closed "
                              f"without merge (team={snapshot.team or 'unknown'})")
            hint = TEAM_REENTRY_HINTS.get(snapshot.team or "")
            if hint:
                log.info("%s (%s): re-entry hint → %s",
                         snapshot.issue_id, snapshot.team,
                         hint.format(issue=snapshot.issue_id))
            else:
                log.info("%s (%s): PR rejected — manual intervention needed",
                         snapshot.issue_id, snapshot.team or "unknown")
            return

        # AWAITING_MERGE / UNDER_REVIEW / STALE transitions: no signal
        # to send (the state change itself is the signal, persisted via
        # persist_snapshot). The grava-side audit log captures it via
        # the wisp write.

    def _apply_stale(self, repo: Path, snapshot: PRSnapshot,
                     ev: Event) -> None:
        log.info("%s: PR #%d stale at %dh (threshold %dh) → needs-human",
                 snapshot.issue_id, snapshot.pr_number,
                 ev.payload.get("age_hours", 0),
                 ev.payload.get("threshold_hours", 0))
        self.grava.label(repo, snapshot.issue_id, add=["needs-human"])
        self.grava.commit(repo,
                          f"watcher: {snapshot.issue_id} PR stale")

    def _apply_new_comments(self, repo: Path, snapshot: PRSnapshot,
                            view: PRView, ev: Event) -> None:
        ids = ev.payload.get("new_comment_ids") or []
        if not ids:
            return
        log.info("%s: %d new PR comment(s) on #%d",
                 snapshot.issue_id, len(ids), snapshot.pr_number)
        # We do NOT write a `pr_new_comments` wisp (the bash watcher
        # wrote a JSON blob there — useless for diff detection, just
        # noise). The advance of `last_seen_comment_id` happens in
        # _new_snapshot → persist_snapshot.
