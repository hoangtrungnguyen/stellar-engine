"""
Pure state-machine for the PR lifecycle watcher (Phase D6).

This module is intentionally I/O-free: it computes the next observable
state for an issue given (a) the wisp snapshot the orchestrator currently
holds and (b) a fresh GitHub PR view. Side effects — writing wisps,
emitting signals, mutating labels, closing issues — live in the adapters
and `pr_watcher.py`. The split exists so the state machine is
unit-testable without a grava DB or a network.

Inputs: PRSnapshot (last-known wisps) + PRView (this-tick GitHub data)
Output: (new PRState, list[Event])

The caller is responsible for:
  * Persisting `new_state` + `last_seen_comment_id` back into wisps.
  * Acting on emitted events (sending signals, updating labels, closing).

State machine (matches the bash watcher's MERGED/CLOSED/OPEN branches
plus an explicit STALE / UNDER_REVIEW separation that was implicit
before):

         ┌─────────────── AWAITING_MERGE ───────────────┐
         │       (PR open, no review activity)           │
         │  ──new comments / CHANGES_REQUESTED──▶ UNDER_REVIEW ─┐
         │  ──age >= stale_threshold──▶ STALE                    │
         │  ──PR merged─────────────────▶ MERGED (terminal)      │
         │  ──PR closed unmerged────────▶ CLOSED (terminal)      │
         └──────────────────────────────────────────────────────┘
                                            ▲
                                            │
                                       (also possible
                                        from UNDER_REVIEW
                                        and STALE)

UNKNOWN is a transient sink the watcher enters when `gh pr view` fails
or returns a PR state we don't recognise; the caller logs + retries
next tick rather than corrupting the wisps with derived data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PRState(str, Enum):
    """Canonical states the watcher persists in the `pr_state` wisp.

    Subclassing `str` so a wisp read can compare directly against the
    enum value without an explicit cast — `PRState(value)` round-trips
    cleanly when the string matches a member.
    """
    AWAITING_MERGE = "awaiting_merge"
    UNDER_REVIEW   = "under_review"
    STALE          = "stale"
    MERGED         = "merged"
    CLOSED         = "closed"
    UNKNOWN        = "unknown"


TERMINAL_STATES = frozenset({PRState.MERGED, PRState.CLOSED})


# ── input: what the orchestrator currently knows ─────────────────────────────


@dataclass(frozen=True)
class PRSnapshot:
    """The last-known state for one issue, loaded from grava wisps.

    Fields map 1:1 to the new centralized wisp schema (see
    [[pr-watcher-redesign]] memory file). The migration from the bash
    watcher's scattered booleans (`pr_stale`, `pr_rejection_recorded`,
    …) is the GravaAdapter's job — by the time `next_state` sees a
    snapshot the schema is already canonical.
    """
    issue_id: str
    pr_number: int
    pr_url: str
    team: str
    state: PRState                  # last observed state; AWAITING_MERGE on first sight
    state_changed_at: int           # unix ts of most recent transition
    awaiting_since: int             # unix ts when this PR first became `pr-created`
    last_seen_comment_id: int       # 0 = no comments observed yet


# ── input: this tick's GitHub view ───────────────────────────────────────────


@dataclass(frozen=True)
class PRView:
    """One PR's GitHub-side facts at a moment in time.

    Built by GitHubAdapter from a single `gh api graphql` bulk fetch.
    `state` follows GitHub's enum literally (OPEN / CLOSED / MERGED);
    `review_decision` is the GraphQL `reviewDecision` (APPROVED /
    CHANGES_REQUESTED / REVIEW_REQUIRED / null).
    """
    pr_number: int
    state: str                      # "OPEN" | "CLOSED" | "MERGED" | "UNKNOWN"
    review_decision: Optional[str]  # None when there are no reviews yet
    new_comment_ids: tuple[int, ...] = ()
    highest_comment_id: int = 0     # for advancing last_seen_comment_id


# ── output: what the orchestrator does on transition ─────────────────────────


@dataclass(frozen=True)
class Event:
    """A single side-effect the orchestrator should apply this tick.

    Pure data — no methods, no callbacks. `pr_watcher.tick()` drains the
    event list and routes each one to the right adapter call. Lets us
    unit-test the state machine without mocking the entire stack."""
    issue_id: str
    kind: str                       # see Event.* constants below
    before: Optional[PRState] = None
    after: Optional[PRState] = None
    payload: dict = field(default_factory=dict)

    # ── Event kinds ──
    # Keep these as string constants (not yet another enum) so callers
    # can build a `dispatch_table[event.kind](event)` without an import.
    TRANSITION       = "transition"        # state changed; persist + signal
    NEW_COMMENTS     = "new_comments"      # OPEN PR has new top-level comments
    REVIEW_REQUESTED = "review_requested"  # OPEN PR moved to CHANGES_REQUESTED
    STALE_FIRST_SEEN = "stale_first_seen"  # crossed stale_threshold this tick
    UNKNOWN          = "unknown"           # gh view failed; transient


# ── policy (consumed by next_state) ──────────────────────────────────────────


@dataclass(frozen=True)
class WatcherPolicy:
    """Tunables from `policies/default.yaml#pr_watcher` (loaded by the
    caller). Defaults here match the bash watcher's behaviour."""
    stale_threshold_hours: int = 72
    on_terminal_state: str = "remove_label"  # "remove_label" | "keep_label"
    # Future: backoff config, max_batch, etc. lives here, not in adapters.


# ── the pure transition function ─────────────────────────────────────────────


def next_state(
    snapshot: PRSnapshot,
    view: PRView,
    now: int,
    policy: WatcherPolicy = WatcherPolicy(),
) -> tuple[PRState, list[Event]]:
    """Compute the next PRState + side-effect events for one issue.

    Idempotency contract: if `snapshot.state == returned_state` AND no
    new comments / review-decision change happened, the returned event
    list is empty. Same view at the same tick produces the same output;
    same view across ticks produces zero events after the first.
    """
    issue_id = snapshot.issue_id

    # ── UNKNOWN: gh fetch failed or surfaced an unrecognised state ──
    # We do NOT transition out of a known state on an UNKNOWN view.
    # Otherwise a transient gh outage would flip a MERGED issue back
    # to AWAITING_MERGE and re-emit signals on the next good tick.
    if view.state not in ("OPEN", "CLOSED", "MERGED"):
        return snapshot.state, [Event(
            issue_id=issue_id, kind=Event.UNKNOWN,
            before=snapshot.state, after=snapshot.state,
            payload={"raw_state": view.state, "pr_number": view.pr_number},
        )]

    # ── Terminal transitions: MERGED / CLOSED ──
    # Idempotent: once already in MERGED, a second MERGED view emits no
    # events. The bash watcher emitted PR_MERGED + PIPELINE_COMPLETE
    # every tick a merged PR was still labelled `pr-created`; relying
    # on the state diff fixes that.
    if view.state == "MERGED":
        if snapshot.state == PRState.MERGED:
            return PRState.MERGED, []
        return PRState.MERGED, [Event(
            issue_id=issue_id, kind=Event.TRANSITION,
            before=snapshot.state, after=PRState.MERGED,
            payload={"pr_number": view.pr_number, "at": now,
                     "on_terminal_state": policy.on_terminal_state},
        )]

    if view.state == "CLOSED":
        if snapshot.state == PRState.CLOSED:
            return PRState.CLOSED, []
        # Capture the review verdict at the moment of closure — drives
        # the rejection_reason wisp written by the adapter.
        reason = view.review_decision or "closed_without_merge"
        return PRState.CLOSED, [Event(
            issue_id=issue_id, kind=Event.TRANSITION,
            before=snapshot.state, after=PRState.CLOSED,
            payload={"pr_number": view.pr_number, "at": now,
                     "reason": reason,
                     "on_terminal_state": policy.on_terminal_state},
        )]

    # ── view.state == "OPEN" ──
    # Three sub-states differ only by signal: stale > review > awaiting.
    # Stale wins because it's the loudest operator signal (label
    # `needs-human`). UNDER_REVIEW supersedes AWAITING_MERGE once there
    # are review-side comments or a CHANGES_REQUESTED decision.
    events: list[Event] = []

    age_hours = max(0, (now - snapshot.awaiting_since) // 3600)
    is_stale = age_hours >= policy.stale_threshold_hours

    has_new_comments = bool(view.new_comment_ids)
    changes_requested = view.review_decision == "CHANGES_REQUESTED"

    # Determine target state. Stale dominates because it surfaces a
    # human-action requirement; review-decision is the next strongest.
    if is_stale:
        new_state = PRState.STALE
    elif has_new_comments or changes_requested:
        new_state = PRState.UNDER_REVIEW
    else:
        new_state = PRState.AWAITING_MERGE

    # Don't downgrade a STALE PR back to AWAITING/UNDER_REVIEW just
    # because the operator added a comment. Staleness is a one-way
    # latch within the current `pr-created` cycle; the only way out is
    # MERGED / CLOSED. (If the operator wants to clear staleness, they
    # remove the `needs-human` label and the next tick will re-evaluate
    # from a fresh `awaiting_since` after re-claim.)
    if snapshot.state == PRState.STALE and new_state != PRState.STALE:
        new_state = PRState.STALE

    # Emit transition event when the state diff is non-trivial.
    if new_state != snapshot.state:
        events.append(Event(
            issue_id=issue_id, kind=Event.TRANSITION,
            before=snapshot.state, after=new_state,
            payload={"pr_number": view.pr_number, "at": now,
                     "age_hours": age_hours},
        ))

    # First-sighting STALE: emit a dedicated event so the adapter can
    # add `needs-human` + post a one-time stale notice.
    if new_state == PRState.STALE and snapshot.state != PRState.STALE:
        events.append(Event(
            issue_id=issue_id, kind=Event.STALE_FIRST_SEEN,
            before=snapshot.state, after=PRState.STALE,
            payload={"pr_number": view.pr_number, "age_hours": age_hours,
                     "threshold_hours": policy.stale_threshold_hours},
        ))

    # New comments are reported regardless of state diff — operator
    # wants to see them even if the PR stays UNDER_REVIEW. The adapter
    # uses `highest_comment_id` to advance `last_seen_comment_id`.
    if has_new_comments:
        events.append(Event(
            issue_id=issue_id, kind=Event.NEW_COMMENTS,
            before=snapshot.state, after=new_state,
            payload={"pr_number": view.pr_number,
                     "new_comment_ids": list(view.new_comment_ids),
                     "highest_comment_id": view.highest_comment_id,
                     "review_decision": view.review_decision},
        ))

    # Edge case: first sight of CHANGES_REQUESTED with no new top-level
    # comment (e.g. a synthetic review with only inline annotations).
    # Fires alongside TRANSITION exactly once — only on the entry into
    # UNDER_REVIEW. Without this gate, a PR that sat in UNDER_REVIEW
    # with CHANGES_REQUESTED would re-emit the event every tick, which
    # was the bash watcher's bug.
    if (changes_requested
            and not has_new_comments
            and new_state != snapshot.state):
        events.append(Event(
            issue_id=issue_id, kind=Event.REVIEW_REQUESTED,
            before=snapshot.state, after=new_state,
            payload={"pr_number": view.pr_number,
                     "review_decision": view.review_decision},
        ))

    return new_state, events
