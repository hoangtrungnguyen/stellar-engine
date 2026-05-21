"""
GravaAdapter — thin subprocess wrapper around the `grava` CLI for the
PR-lifecycle watcher (Phase D6).

The adapter is the ONLY place that knows the canonical wisp keys for
the watcher. The pure state machine (`runtime.pr_state`) sees clean
`PRSnapshot` instances; the watcher composition (`runtime.pr_watcher`)
calls `load_snapshot` / `persist_snapshot` and trusts they round-trip.

Migration from the bash watcher's scattered booleans
(`pr_stale`, `pr_rejection_recorded`, `pr_merged_at`,
`pr_rejection_reason`) happens in `load_snapshot`: on first read after
upgrade, the old keys are folded into the new `pr_state` +
`pr_state_changed_at` and the snapshot is persisted on the way back
out. Old keys are NOT deleted — they linger until a future cleanup
sweep, so a downgrade to the bash watcher is still survivable.

All methods are no-ops on missing data and best-effort on errors:
the daemon loop must not crash because one issue's wisp read returned
a transient grava error. Adapter methods that mutate (`signal`,
`label`, `close`, `commit`, `write_wisp`) return a bool so the caller
can log / surface failures without an exception path.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..pr_state import PRSnapshot, PRState

log = logging.getLogger("stellar.orchestrator.adapters.grava")


# ── canonical wisp keys (single source of truth) ─────────────────────────────

# New schema (PR #__ — Phase D6). Centralized here so the pure state
# machine never has to know wire names.
WISP_PR_NUMBER             = "pr_number"
WISP_PR_URL                = "pr_url"
WISP_TEAM                  = "team"
WISP_PR_STATE              = "pr_state"
WISP_PR_STATE_CHANGED_AT   = "pr_state_changed_at"
WISP_PR_AWAITING_SINCE     = "pr_awaiting_since"
WISP_PR_LAST_SEEN_COMMENT  = "pr_last_seen_comment_id"

# Legacy keys read once for migration. NOT written.
LEGACY_PR_AWAITING_SINCE   = "pr_awaiting_merge_since"
LEGACY_PR_STALE            = "pr_stale"
LEGACY_PR_MERGED_AT        = "pr_merged_at"
LEGACY_PR_REJECTION_FLAG   = "pr_rejection_recorded"


# ── data containers for adapter return values ────────────────────────────────


@dataclass(frozen=True)
class IssueRef:
    """Minimal projection of a grava issue used by the watcher."""
    id: str
    title: str = ""


# ── adapter ──────────────────────────────────────────────────────────────────


class GravaAdapter:
    """One adapter instance per daemon process; cheap (no state)."""

    def __init__(self, grava_bin: str = "grava") -> None:
        self._bin = grava_bin

    # ── primitives ──

    def _run(self, args: list[str], repo: Path,
             *, capture: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
        """Invoke `grava <args>` inside `repo`. Returns the CompletedProcess.

        We never raise — callers decide how to react to non-zero returns.
        """
        return subprocess.run(
            [self._bin, *args],
            cwd=str(repo),
            capture_output=capture, text=True, timeout=timeout,
        )

    # ── reads ──

    def list_pr_created(self, repo: Path) -> list[IssueRef]:
        """Return all issues labelled `pr-created` in this repo."""
        r = self._run(["list", "-L", "pr-created", "--json"], repo)
        if r.returncode != 0:
            log.warning("list -L pr-created failed in %s: %s",
                        repo, (r.stderr or "").strip())
            return []
        try:
            data = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            log.warning("list returned non-JSON in %s", repo)
            return []
        if isinstance(data, dict):
            data = data.get("issues") or data.get("Issues") or []
        out: list[IssueRef] = []
        for it in data if isinstance(data, list) else []:
            iid = it.get("id") or it.get("ID") or ""
            if iid:
                out.append(IssueRef(id=iid, title=it.get("title", "")))
        return out

    def read_wisp(self, repo: Path, issue_id: str, key: str) -> str:
        """Return the wisp value or "" if missing / unreadable."""
        r = self._run(["wisp", "read", issue_id, key], repo)
        if r.returncode != 0:
            return ""
        return (r.stdout or "").strip()

    def load_snapshot(self, repo: Path, issue_id: str) -> PRSnapshot | None:
        """Build a PRSnapshot from this issue's wisps.

        Returns None when the issue has no `pr_number` wisp — the watcher
        skips it with a "no pr_number; skipping" log line, matching the
        bash watcher's behaviour.

        Performs schema migration when the new keys aren't set yet but
        legacy keys are. The migrated snapshot is NOT persisted from
        here (load is read-only) — the watcher's tick loop will call
        `persist_snapshot` after the state machine runs, which writes
        the canonical keys.
        """
        pr_number_raw = self.read_wisp(repo, issue_id, WISP_PR_NUMBER)
        if not pr_number_raw:
            return None
        try:
            pr_number = int(pr_number_raw)
        except ValueError:
            log.warning("%s: %s wisp non-integer (%r)",
                        issue_id, WISP_PR_NUMBER, pr_number_raw)
            return None

        pr_url = self.read_wisp(repo, issue_id, WISP_PR_URL)
        team = self.read_wisp(repo, issue_id, WISP_TEAM) or ""

        # New schema first; fall back to legacy if absent.
        state_str = self.read_wisp(repo, issue_id, WISP_PR_STATE)
        state = self._parse_state(state_str) or self._migrate_state(repo, issue_id)

        state_changed_at = self._read_int(repo, issue_id, WISP_PR_STATE_CHANGED_AT)
        awaiting_since = self._read_int(repo, issue_id, WISP_PR_AWAITING_SINCE)
        if awaiting_since == 0:
            # Migration: bash watcher wrote pr_awaiting_merge_since.
            awaiting_since = self._read_int(repo, issue_id, LEGACY_PR_AWAITING_SINCE)
        last_seen = self._read_int(repo, issue_id, WISP_PR_LAST_SEEN_COMMENT)

        return PRSnapshot(
            issue_id=issue_id,
            pr_number=pr_number,
            pr_url=pr_url,
            team=team,
            state=state,
            state_changed_at=state_changed_at,
            awaiting_since=awaiting_since,
            last_seen_comment_id=last_seen,
        )

    def _read_int(self, repo: Path, issue_id: str, key: str) -> int:
        raw = self.read_wisp(repo, issue_id, key)
        if not raw:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    @staticmethod
    def _parse_state(value: str) -> PRState | None:
        """Convert a wisp string to PRState; None if blank or unknown."""
        if not value:
            return None
        try:
            return PRState(value)
        except ValueError:
            log.warning("unrecognised pr_state wisp value %r — ignoring", value)
            return None

    def _migrate_state(self, repo: Path, issue_id: str) -> PRState:
        """Derive PRState from the bash watcher's legacy boolean wisps.

        Order matters: MERGED beats CLOSED beats STALE; a PR that's
        merged but also flagged stale is still merged. AWAITING_MERGE
        is the default — matches the bash watcher's implicit baseline.
        """
        if self.read_wisp(repo, issue_id, LEGACY_PR_MERGED_AT):
            return PRState.MERGED
        if self.read_wisp(repo, issue_id, LEGACY_PR_REJECTION_FLAG) == "1":
            return PRState.CLOSED
        if self.read_wisp(repo, issue_id, LEGACY_PR_STALE) == "true":
            return PRState.STALE
        return PRState.AWAITING_MERGE

    # ── writes ──

    def write_wisp(self, repo: Path, issue_id: str,
                   key: str, value: str) -> bool:
        r = self._run(["wisp", "write", issue_id, key, value], repo)
        if r.returncode != 0:
            log.warning("wisp write %s.%s failed: %s",
                        issue_id, key, (r.stderr or "").strip())
            return False
        return True

    def persist_snapshot(self, repo: Path, snapshot: PRSnapshot,
                         now: int) -> bool:
        """Write the canonical wisp keys for one snapshot.

        Idempotent: writing the same value twice is harmless. Does NOT
        delete legacy keys — see file-level doc.
        """
        ok = True
        ok &= self.write_wisp(repo, snapshot.issue_id,
                              WISP_PR_STATE, snapshot.state.value)
        ok &= self.write_wisp(repo, snapshot.issue_id,
                              WISP_PR_STATE_CHANGED_AT,
                              str(snapshot.state_changed_at or now))
        if snapshot.awaiting_since:
            ok &= self.write_wisp(repo, snapshot.issue_id,
                                  WISP_PR_AWAITING_SINCE,
                                  str(snapshot.awaiting_since))
        if snapshot.last_seen_comment_id:
            ok &= self.write_wisp(repo, snapshot.issue_id,
                                  WISP_PR_LAST_SEEN_COMMENT,
                                  str(snapshot.last_seen_comment_id))
        return ok

    def signal(self, repo: Path, issue_id: str, name: str,
               payload: str | None = None,
               actor: str = "watcher") -> bool:
        argv: list[str] = ["signal", name, "--issue", issue_id,
                           "--actor", actor]
        if payload is not None:
            argv += ["--payload", payload]
        r = self._run(argv, repo)
        if r.returncode != 0:
            log.warning("signal %s failed for %s: %s",
                        name, issue_id, (r.stderr or "").strip())
            return False
        return True

    def label(self, repo: Path, issue_id: str,
              add: Iterable[str] = (), remove: Iterable[str] = ()) -> bool:
        ok = True
        for label in add:
            r = self._run(["label", issue_id, "--add", label], repo)
            if r.returncode != 0:
                ok = False
                log.warning("label --add %s failed for %s: %s",
                            label, issue_id, (r.stderr or "").strip())
        for label in remove:
            r = self._run(["label", issue_id, "--remove", label], repo)
            if r.returncode != 0:
                ok = False
                log.warning("label --remove %s failed for %s: %s",
                            label, issue_id, (r.stderr or "").strip())
        return ok

    def close(self, repo: Path, issue_id: str,
              actor: str = "watcher") -> bool:
        r = self._run(["close", issue_id, "--actor", actor], repo)
        if r.returncode != 0:
            log.warning("close %s failed: %s",
                        issue_id, (r.stderr or "").strip())
            return False
        return True

    def commit(self, repo: Path, message: str) -> bool:
        r = self._run(["commit", "-m", message], repo)
        if r.returncode != 0:
            log.warning("grava commit failed in %s: %s",
                        repo, (r.stderr or "").strip())
            return False
        return True
