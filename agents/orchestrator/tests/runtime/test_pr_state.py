"""Unit tests for the pure pr_state transition function (Phase D6).

These tests deliberately do NOT touch grava, gh, the filesystem, or
subprocess. The state machine is meant to be testable in milliseconds
on any host, regardless of grava-DB availability — that's the whole
point of the three-layer split documented in
docs/orchestrator/daemon-plan.md#Phase-D6.

Add new tests when:
  * A new transition path is added (e.g. AUTO_RETRY) — assert both the
    happy path and the idempotency contract (same view twice = no
    duplicate events).
  * A new `view.state` value comes from GraphQL — extend the UNKNOWN
    suite to verify the orchestrator stays put.
  * Policy tunables grow — pass a WatcherPolicy with non-default values
    and assert the threshold is respected.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agents/orchestrator/runtime/` importable without packaging.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "agents" / "orchestrator"))

import pytest                                                          # noqa: E402
from runtime.pr_state import (                                         # noqa: E402
    Event,
    PRSnapshot,
    PRState,
    PRView,
    WatcherPolicy,
    next_state,
)

NOW = 1_700_000_000   # arbitrary stable timestamp for assertions
HOUR = 3600


def _snap(state: PRState = PRState.AWAITING_MERGE,
          awaiting_since: int = NOW,
          last_seen_comment_id: int = 0) -> PRSnapshot:
    return PRSnapshot(
        issue_id="grava-abc",
        pr_number=123,
        pr_url="https://github.com/o/r/pull/123",
        team="fix-bug",
        state=state,
        state_changed_at=NOW,
        awaiting_since=awaiting_since,
        last_seen_comment_id=last_seen_comment_id,
    )


def _view(state: str = "OPEN",
          review_decision: str | None = None,
          new_comment_ids: tuple[int, ...] = (),
          highest_comment_id: int = 0) -> PRView:
    return PRView(
        pr_number=123,
        state=state,
        review_decision=review_decision,
        new_comment_ids=new_comment_ids,
        highest_comment_id=highest_comment_id,
    )


# ── MERGED ────────────────────────────────────────────────────────────────────


def test_merged_first_sight_emits_transition():
    new, events = next_state(_snap(), _view(state="MERGED"), NOW)
    assert new == PRState.MERGED
    assert len(events) == 1
    assert events[0].kind == Event.TRANSITION
    assert events[0].before == PRState.AWAITING_MERGE
    assert events[0].after == PRState.MERGED
    assert events[0].payload["pr_number"] == 123


def test_merged_idempotent_second_tick():
    """Bash watcher fired PR_MERGED + PIPELINE_COMPLETE every tick a
    merged PR was still labelled `pr-created`. The new state machine
    only fires once — verified by feeding the same MERGED view twice."""
    snap = _snap(state=PRState.MERGED)
    new, events = next_state(snap, _view(state="MERGED"), NOW)
    assert new == PRState.MERGED
    assert events == []


def test_merged_from_stale_emits_transition():
    snap = _snap(state=PRState.STALE)
    new, events = next_state(snap, _view(state="MERGED"), NOW)
    assert new == PRState.MERGED
    assert events[0].before == PRState.STALE


# ── CLOSED ────────────────────────────────────────────────────────────────────


def test_closed_first_sight_carries_review_decision():
    new, events = next_state(
        _snap(),
        _view(state="CLOSED", review_decision="CHANGES_REQUESTED"),
        NOW,
    )
    assert new == PRState.CLOSED
    assert events[0].payload["reason"] == "CHANGES_REQUESTED"


def test_closed_without_review_decision_falls_back_to_default_reason():
    new, events = next_state(_snap(), _view(state="CLOSED"), NOW)
    assert new == PRState.CLOSED
    assert events[0].payload["reason"] == "closed_without_merge"


def test_closed_idempotent_second_tick():
    snap = _snap(state=PRState.CLOSED)
    new, events = next_state(snap, _view(state="CLOSED"), NOW)
    assert new == PRState.CLOSED
    assert events == []


# ── AWAITING_MERGE (the open / quiet path) ───────────────────────────────────


def test_awaiting_stays_awaiting_when_nothing_changes():
    new, events = next_state(_snap(), _view(state="OPEN"), NOW)
    assert new == PRState.AWAITING_MERGE
    assert events == []


# ── UNDER_REVIEW transitions ──────────────────────────────────────────────────


def test_first_new_comment_transitions_to_under_review():
    new, events = next_state(
        _snap(),
        _view(state="OPEN", new_comment_ids=(101,), highest_comment_id=101),
        NOW,
    )
    assert new == PRState.UNDER_REVIEW
    kinds = {e.kind for e in events}
    assert Event.TRANSITION in kinds
    assert Event.NEW_COMMENTS in kinds


def test_changes_requested_without_new_comments_emits_review_event():
    new, events = next_state(
        _snap(),
        _view(state="OPEN", review_decision="CHANGES_REQUESTED"),
        NOW,
    )
    assert new == PRState.UNDER_REVIEW
    kinds = {e.kind for e in events}
    assert Event.REVIEW_REQUESTED in kinds
    assert Event.NEW_COMMENTS not in kinds


def test_new_comments_while_already_under_review_emits_comments_only():
    """Don't re-emit TRANSITION when state is unchanged — but DO surface
    the new comments so the operator can see the latest delta."""
    snap = _snap(state=PRState.UNDER_REVIEW)
    new, events = next_state(
        snap,
        _view(state="OPEN", new_comment_ids=(202,), highest_comment_id=202,
              review_decision="CHANGES_REQUESTED"),
        NOW,
    )
    assert new == PRState.UNDER_REVIEW
    kinds = [e.kind for e in events]
    assert Event.TRANSITION not in kinds
    assert Event.NEW_COMMENTS in kinds


# ── STALE behaviour + latch ──────────────────────────────────────────────────


def test_stale_first_sighting_emits_dedicated_event():
    snap = _snap(awaiting_since=NOW - 73 * HOUR)
    new, events = next_state(snap, _view(state="OPEN"), NOW)
    assert new == PRState.STALE
    kinds = {e.kind for e in events}
    assert Event.STALE_FIRST_SEEN in kinds
    assert Event.TRANSITION in kinds


def test_stale_below_threshold_stays_awaiting():
    snap = _snap(awaiting_since=NOW - 71 * HOUR)
    new, events = next_state(snap, _view(state="OPEN"), NOW)
    assert new == PRState.AWAITING_MERGE
    assert events == []


def test_stale_latches_even_when_new_comments_arrive():
    """Once STALE, comment activity does NOT reset the latch — the
    only way out is MERGED / CLOSED or operator-driven re-claim."""
    snap = _snap(state=PRState.STALE,
                 awaiting_since=NOW - 100 * HOUR)
    new, events = next_state(
        snap,
        _view(state="OPEN", new_comment_ids=(303,), highest_comment_id=303),
        NOW,
    )
    assert new == PRState.STALE
    # Comments still surface, but no transition is reported.
    kinds = [e.kind for e in events]
    assert Event.NEW_COMMENTS in kinds
    assert Event.TRANSITION not in kinds


def test_stale_idempotent_second_tick():
    snap = _snap(state=PRState.STALE,
                 awaiting_since=NOW - 100 * HOUR)
    new, events = next_state(snap, _view(state="OPEN"), NOW)
    assert new == PRState.STALE
    assert events == []      # STALE_FIRST_SEEN already fired earlier


def test_stale_threshold_respects_custom_policy():
    snap = _snap(awaiting_since=NOW - 10 * HOUR)
    policy = WatcherPolicy(stale_threshold_hours=8)
    new, _ = next_state(snap, _view(state="OPEN"), NOW, policy=policy)
    assert new == PRState.STALE


# ── UNKNOWN: gh blip protection ──────────────────────────────────────────────


def test_unknown_view_does_not_reset_known_state():
    """A flaky `gh pr view` returning an unrecognised state must not
    flip an already-MERGED issue back to AWAITING_MERGE."""
    snap = _snap(state=PRState.MERGED)
    new, events = next_state(snap, _view(state="GRAPHQL_TIMEOUT"), NOW)
    assert new == PRState.MERGED
    assert len(events) == 1
    assert events[0].kind == Event.UNKNOWN
    assert events[0].before == PRState.MERGED
    assert events[0].after == PRState.MERGED


def test_unknown_view_from_first_sight_is_also_safe():
    new, events = next_state(_snap(), _view(state=""), NOW)
    assert new == PRState.AWAITING_MERGE   # snapshot's state is preserved
    assert events[0].kind == Event.UNKNOWN


# ── invariants & misc ────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", list(PRState))
def test_terminal_states_are_idempotent_under_same_view(state: PRState):
    """For every state, feeding a view that re-describes the same
    underlying GitHub state should produce no events. `awaiting_since`
    is tuned per-state so OPEN snapshots aren't accidentally stale."""
    snap_extras = {
        PRState.STALE: {"awaiting_since": NOW - 100 * HOUR},
    }
    snap = _snap(state=state, **snap_extras.get(state, {}))
    view_map = {
        PRState.MERGED: _view(state="MERGED"),
        PRState.CLOSED: _view(state="CLOSED"),
        PRState.AWAITING_MERGE: _view(state="OPEN"),
        PRState.UNDER_REVIEW: _view(state="OPEN",
                                    review_decision="CHANGES_REQUESTED"),
        PRState.STALE: _view(state="OPEN"),
        PRState.UNKNOWN: _view(state="GRAPHQL_TIMEOUT"),
    }
    _, events = next_state(snap, view_map[state], NOW)
    if state == PRState.UNKNOWN:
        assert any(e.kind == Event.UNKNOWN for e in events)
    else:
        # UNDER_REVIEW under "OPEN + CHANGES_REQUESTED" without a fresh
        # comment delta should not re-emit the REVIEW_REQUESTED event;
        # the bash watcher's bug was reporting the same review_decision
        # every tick.
        assert events == [], f"{state} unexpectedly emitted {events}"
