"""
GitHubAdapter — thin subprocess wrapper around the `gh` CLI.

Builds `PRView` instances from GitHub's current view of one or more
PRs. The watcher composition (`runtime.pr_watcher`) gives this adapter
a list of (pr_url, last_seen_comment_id) pairs; it returns a dict
`{pr_number → PRView}` for the pure state machine to consume.

D6 ships per-PR `gh pr view` + `gh api .../comments` calls — the same
N+1 pattern the bash watcher uses today. The composition is structured
so that the adapter can swap to a single `gh api graphql` bulk fetch
without changing any caller; that optimisation is deferred until the
rest of the watcher is in production and the API-call cost is the
provable bottleneck.

All adapter methods return what they observed — they NEVER raise — so
a flaky `gh` (rate-limit, transient 502, missing auth) surfaces as a
`PRView(state="UNKNOWN", …)`, which the state machine handles by
preserving the snapshot's previous state.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

from ..pr_state import PRView

log = logging.getLogger("stellar.orchestrator.adapters.github")


# Match canonical PR URLs: https://github.com/<owner>/<name>/pull/<num>
# Tolerates trailing slashes and missing scheme; rejects anything else
# so we don't pass garbage to `gh api`.
_PR_URL_RE = re.compile(
    r"(?:https?://)?github\.com/(?P<owner>[^/]+)/(?P<name>[^/]+)/pull/(?P<num>\d+)/?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PRRequest:
    """One thing to fetch this tick. `last_seen_comment_id` lets the
    adapter filter the comment delta down to genuinely new comments."""
    pr_url: str
    last_seen_comment_id: int = 0


def parse_pr_url(url: str) -> tuple[str, str, int] | None:
    """Return (owner, name, pr_number) or None if `url` isn't a PR URL.

    Exposed as a module function so callers can validate URLs before
    constructing a PRRequest; saves an `if` ladder inside the adapter.
    """
    m = _PR_URL_RE.search(url or "")
    if not m:
        return None
    try:
        return m["owner"], m["name"], int(m["num"])
    except ValueError:
        return None


class GitHubAdapter:
    """One adapter per daemon process. Stateless."""

    def __init__(self, gh_bin: str = "gh") -> None:
        self._bin = gh_bin

    def fetch_view(self, request: PRRequest) -> PRView | None:
        """Build a PRView for one PR.

        Returns None when the URL isn't parseable. Returns a PRView with
        `state="UNKNOWN"` when `gh` fails — the state machine guarantees
        the snapshot's prior state survives that case.
        """
        parsed = parse_pr_url(request.pr_url)
        if parsed is None:
            log.warning("not a GitHub PR URL: %r", request.pr_url)
            return None
        owner, name, pr_number = parsed

        state, review_decision = self._fetch_state(pr_number, owner, name)
        if state == "UNKNOWN":
            return PRView(
                pr_number=pr_number,
                state="UNKNOWN",
                review_decision=None,
                new_comment_ids=(),
                highest_comment_id=request.last_seen_comment_id,
            )

        new_ids, highest_id = self._fetch_comment_delta(
            owner, name, pr_number, request.last_seen_comment_id,
        )

        return PRView(
            pr_number=pr_number,
            state=state,
            review_decision=review_decision,
            new_comment_ids=new_ids,
            highest_comment_id=highest_id,
        )

    def fetch_views(self, requests: list[PRRequest]) -> dict[int, PRView]:
        """Bulk wrapper. Today calls `fetch_view` per request — same
        N+1 as the bash watcher. The interface is shaped so a future
        GraphQL implementation slots in without touching callers."""
        out: dict[int, PRView] = {}
        for req in requests:
            view = self.fetch_view(req)
            if view is not None:
                out[view.pr_number] = view
        return out

    # ── internals ──

    def _fetch_state(self, pr_number: int,
                     owner: str, name: str) -> tuple[str, str | None]:
        """Return (state, review_decision). state="UNKNOWN" on gh failure.

        `gh pr view` resolves owner/name from the current repo by default,
        so we pass them explicitly to make the call work outside a clone
        (the daemon runs in its own cwd, not the target repo)."""
        r = subprocess.run(
            [self._bin, "pr", "view", str(pr_number),
             "-R", f"{owner}/{name}",
             "--json", "state,reviewDecision"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            log.warning("gh pr view %s/%s#%d failed: %s",
                        owner, name, pr_number, (r.stderr or "").strip())
            return "UNKNOWN", None
        try:
            data = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            log.warning("gh pr view returned non-JSON for %s/%s#%d",
                        owner, name, pr_number)
            return "UNKNOWN", None
        state = (data.get("state") or "").upper() or "UNKNOWN"
        review = data.get("reviewDecision") or None
        return state, review

    def _fetch_comment_delta(self, owner: str, name: str, pr_number: int,
                             last_seen: int) -> tuple[tuple[int, ...], int]:
        """Return ((new top-level comment ids), highest seen id).

        Uses `gh api repos/{owner}/{name}/pulls/{num}/comments` for
        review-thread comments (matches what the bash watcher polled).
        Top-level only — replies are filtered out via `in_reply_to_id`.
        """
        r = subprocess.run(
            [self._bin, "api",
             f"repos/{owner}/{name}/pulls/{pr_number}/comments"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            # Comment fetch failures are non-fatal — we'd rather report
            # OPEN with no comment delta than refuse the whole tick.
            log.warning("gh api comments %s/%s#%d failed: %s",
                        owner, name, pr_number, (r.stderr or "").strip())
            return (), last_seen
        try:
            comments = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            return (), last_seen
        if not isinstance(comments, list):
            return (), last_seen

        new_ids: list[int] = []
        highest = last_seen
        for c in comments:
            if not isinstance(c, dict):
                continue
            if c.get("in_reply_to_id") is not None:
                continue                    # skip replies; we want roots
            cid = c.get("id")
            if not isinstance(cid, int):
                continue
            if cid > last_seen:
                new_ids.append(cid)
            if cid > highest:
                highest = cid
        return tuple(sorted(new_ids)), highest
