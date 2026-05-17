"""Tests for cli/grava_plane_sync.py — one-shot Grava → Plane sync."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import grava_plane_sync as sync_mod
from grava_plane_sync import (
    GravaDB,
    MemberMapper,
    PlaneSyncer,
    StateMapper,
    WatcherState,
    _load_state_map,
    load_state,
    main,
    save_state,
)


# ─── FakePlaneClient ─────────────────────────────────────────────────────────


class FakePlaneClient:
    def __init__(
        self,
        *,
        states=None,
        members=None,
        work_items=None,
        get_responses=None,
    ):
        self._states = states or []
        self._members = members or []
        self._work_items = work_items or []
        self._get_responses = get_responses or {}
        self.patches: list[tuple[str, str, dict]] = []
        self.comments: list[tuple[str, str, str]] = []

    def list_states(self, project_id):
        return self._states

    def list_members(self):
        return self._members

    def search_work_items(self, project_id, **filters):
        if not filters:
            return self._work_items
        if "sequence_id" in filters:
            return [
                w for w in self._work_items
                if str(w.get("sequence_id")) == str(filters["sequence_id"])
            ]
        return self._work_items

    def get_work_item(self, project_id, issue_id):
        return self._get_responses.get(issue_id, {"id": issue_id})

    def update_work_item(self, project_id, issue_id, payload):
        self.patches.append((project_id, issue_id, payload))
        return {"id": issue_id, **payload}

    def add_comment(self, project_id, issue_id, comment_html):
        self.comments.append((project_id, issue_id, comment_html))
        return {"id": "c-1"}


# ─── WatcherState round-trip ─────────────────────────────────────────────────


def test_state_round_trip(tmp_path):
    state = WatcherState(
        issues={"grava-1": {"status": "open", "assignee": None, "seq_id": "10"}},
        last_comment_id_by_issue={"grava-1": 5},
        seq_to_plane_uuid={"10": "uuid-1"},
        plane_states={"In Progress": "state-uuid"},
        plane_members={"alice": "member-uuid"},
    )
    path = tmp_path / "state.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.issues == state.issues
    assert loaded.last_comment_id_by_issue == state.last_comment_id_by_issue


def test_load_state_missing_file_returns_default(tmp_path):
    loaded = load_state(tmp_path / "absent.json")
    assert loaded.issues == {}
    assert loaded.last_comment_id_by_issue == {}


def test_load_state_corrupted_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {")
    loaded = load_state(p)
    assert loaded.issues == {}


# ─── _load_state_map ─────────────────────────────────────────────────────────


def test_load_state_map_extracts_per_project(tmp_path):
    yml = tmp_path / "system.yaml"
    yml.write_text(
        "plane_state_map:\n"
        '  "proj-1":\n'
        '    open: "Todo"\n'
        '    closed: "Done"\n'
    )
    out = _load_state_map(yml, "proj-1")
    assert out == {"open": "Todo", "closed": "Done"}


def test_load_state_map_missing_project_returns_empty(tmp_path):
    yml = tmp_path / "system.yaml"
    yml.write_text('plane_state_map:\n  "other-proj":\n    open: "Todo"\n')
    assert _load_state_map(yml, "proj-1") == {}


def test_load_state_map_no_file_returns_empty():
    assert _load_state_map(None, "proj-1") == {}
    assert _load_state_map(Path("/no/such/file"), "proj-1") == {}


# ─── StateMapper ─────────────────────────────────────────────────────────────


def test_state_mapper_warm_populates_caches():
    state = WatcherState()
    client = FakePlaneClient(states=[
        {"id": "s1", "name": "Todo", "group": "unstarted", "sequence": 1},
        {"id": "s2", "name": "In Progress", "group": "started", "sequence": 2},
        {"id": "s3", "name": "Done", "group": "completed", "sequence": 3},
    ])
    mapper = StateMapper(client, "proj-1", state, configured_map={})
    mapper.warm()
    assert state.plane_states == {"Todo": "s1", "In Progress": "s2", "Done": "s3"}
    assert state.plane_state_groups["In Progress"] == "started"


def test_state_mapper_resolves_via_configured_map():
    state = WatcherState(
        plane_states={"Todo": "s1", "In Progress": "s2"},
        plane_state_groups={"Todo": "unstarted", "In Progress": "started"},
    )
    client = FakePlaneClient()
    mapper = StateMapper(client, "proj-1", state, configured_map={"open": "Todo"})
    assert mapper.resolve("open") == "s1"


def test_state_mapper_fallback_by_group():
    state = WatcherState(
        plane_states={"Backlog": "s0", "Todo": "s1", "In Progress": "s2"},
        plane_state_groups={
            "Backlog": "backlog",
            "Todo": "unstarted",
            "In Progress": "started",
        },
        plane_state_sequences={"Backlog": 0, "Todo": 1, "In Progress": 2},
    )
    client = FakePlaneClient()
    mapper = StateMapper(client, "proj-1", state, configured_map={})
    # open → prefer unstarted (Todo) over backlog (Backlog)
    assert mapper.resolve("open") == "s1"
    assert mapper.resolve("in_progress") == "s2"


def test_state_mapper_returns_none_when_unresolvable():
    state = WatcherState(plane_states={"Custom": "s9"},
                         plane_state_groups={"Custom": "unknown-group"})
    mapper = StateMapper(FakePlaneClient(), "proj-1", state, configured_map={})
    assert mapper.resolve("open") is None
    assert mapper.resolve("") is None


# ─── MemberMapper ────────────────────────────────────────────────────────────


def test_member_mapper_warm_indexes_keys():
    state = WatcherState()
    client = FakePlaneClient(members=[
        {"member": {"id": "m1", "display_name": "Alice", "email": "alice@x.io"}},
        {"member": {"id": "m2", "display_name": "Bob"}},
    ])
    MemberMapper(client, state).warm()
    assert state.plane_members["alice"] == "m1"
    assert state.plane_members["bob"] == "m2"
    assert state.plane_members["alice@x.io"] == "m1"


def test_member_mapper_resolves_case_insensitive():
    state = WatcherState(plane_members={"alice": "m1"})
    mapper = MemberMapper(FakePlaneClient(), state)
    assert mapper.resolve("Alice") == "m1"
    assert mapper.resolve("ALICE") == "m1"


def test_member_mapper_returns_none_on_no_match():
    mapper = MemberMapper(FakePlaneClient(), WatcherState())
    assert mapper.resolve("ghost") is None
    assert mapper.resolve(None) is None
    assert mapper.resolve("") is None


# ─── PlaneSyncer ─────────────────────────────────────────────────────────────


def _build_syncer(client, state=None, configured_map=None, project_id="proj-1"):
    state = state or WatcherState()
    sm = StateMapper(client, project_id, state, configured_map or {})
    mm = MemberMapper(client, state)
    return PlaneSyncer(client, project_id, state, sm, mm), state


def test_resolve_plane_uuid_uses_cache():
    state = WatcherState(seq_to_plane_uuid={"10": "u1"})
    client = FakePlaneClient()
    syncer, _ = _build_syncer(client, state)
    assert syncer.resolve_plane_uuid("10") == "u1"


def test_resolve_plane_uuid_searches_then_caches():
    client = FakePlaneClient(
        work_items=[{"id": "u1", "sequence_id": 10}, {"id": "u2", "sequence_id": 11}],
    )
    syncer, state = _build_syncer(client)
    assert syncer.resolve_plane_uuid("10") == "u1"
    assert state.seq_to_plane_uuid["10"] == "u1"


def test_resolve_plane_uuid_returns_none_when_not_found():
    client = FakePlaneClient(work_items=[{"id": "u1", "sequence_id": 99}])
    syncer, _ = _build_syncer(client)
    assert syncer.resolve_plane_uuid("10") is None


def test_sync_one_issue_patches_status_change():
    client = FakePlaneClient(
        states=[{"id": "s_done", "name": "Done", "group": "completed", "sequence": 3}],
        work_items=[{"id": "u1", "sequence_id": 10}],
        get_responses={"u1": {"state": "s_open", "assignees": []}},
    )
    state = WatcherState(
        issues={"grava-1": {"status": "open", "assignee": None, "seq_id": "10"}},
    )
    syncer, _ = _build_syncer(
        client, state, configured_map={"closed": "Done"},
    )
    StateMapper(client, "proj-1", state, {"closed": "Done"}).warm()
    row = {"id": "grava-1", "status": "closed", "assignee": None, "seq_id": "10"}
    assert syncer.sync_one_issue(row) is True
    assert client.patches == [("proj-1", "u1", {"state": "s_done"})]


def test_sync_one_issue_idempotent_when_plane_matches():
    client = FakePlaneClient(
        states=[{"id": "s_done", "name": "Done", "group": "completed", "sequence": 3}],
        work_items=[{"id": "u1", "sequence_id": 10}],
        get_responses={"u1": {"state": "s_done", "assignees": []}},  # already Done
    )
    state = WatcherState(
        issues={"grava-1": {"status": "open", "assignee": None, "seq_id": "10"}},
    )
    syncer, _ = _build_syncer(client, state, configured_map={"closed": "Done"})
    StateMapper(client, "proj-1", state, {"closed": "Done"}).warm()
    row = {"id": "grava-1", "status": "closed", "assignee": None, "seq_id": "10"}
    syncer.sync_one_issue(row)
    assert client.patches == []  # no PATCH issued


def test_sync_one_issue_assignee_unassign_when_grava_null():
    client = FakePlaneClient(
        work_items=[{"id": "u1", "sequence_id": 10}],
        get_responses={"u1": {"state": None, "assignees": ["m1"]}},
    )
    state = WatcherState(
        issues={"grava-1": {"status": "open", "assignee": "alice", "seq_id": "10"}},
    )
    syncer, _ = _build_syncer(client, state)
    row = {"id": "grava-1", "status": "open", "assignee": None, "seq_id": "10"}
    syncer.sync_one_issue(row)
    assert client.patches == [("proj-1", "u1", {"assignees": []})]


def test_sync_one_issue_skips_assignee_when_no_member_match():
    client = FakePlaneClient(
        work_items=[{"id": "u1", "sequence_id": 10}],
        get_responses={"u1": {"state": None, "assignees": []}},
    )
    state = WatcherState(
        issues={"grava-1": {"status": "open", "assignee": None, "seq_id": "10"}},
    )
    syncer, _ = _build_syncer(client, state)
    row = {"id": "grava-1", "status": "open", "assignee": "ghost", "seq_id": "10"}
    syncer.sync_one_issue(row)
    assert client.patches == []


def test_post_comment_formats_html():
    client = FakePlaneClient()
    syncer, _ = _build_syncer(client)
    ok = syncer.post_comment(
        {"id": 7, "issue_id": "grava-1", "message": "line1\nline2", "actor": "coder"},
        plane_uuid="u1",
    )
    assert ok is True
    assert client.comments == [
        ("proj-1", "u1", "<p><strong>[grava/coder]</strong> line1<br>line2</p>"),
    ]


# ─── GravaDB (with mocked subprocess) ────────────────────────────────────────


def _fake_sql_result(rows):
    return mock.Mock(returncode=0, stdout=json.dumps({"rows": rows}), stderr="")


def _fake_sql_empty():
    return mock.Mock(returncode=0, stdout="{}", stderr="")


def test_grava_db_requires_dolt_dir(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        GravaDB(tmp_path / "missing-grava-repo")


def test_grava_db_fetch_issue(tmp_path, monkeypatch):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    db = GravaDB(tmp_path)
    rows = [{"id": "grava-1", "status": "open", "assignee": None, "seq_id": "10"}]
    with mock.patch.object(sync_mod.subprocess, "run", return_value=_fake_sql_result(rows)):
        out = db.fetch_issue("grava-1")
    assert out == rows[0]


def test_grava_db_fetch_issue_empty(tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    db = GravaDB(tmp_path)
    with mock.patch.object(sync_mod.subprocess, "run", return_value=_fake_sql_empty()):
        assert db.fetch_issue("grava-x") is None


def test_grava_db_raises_on_nonzero(tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    db = GravaDB(tmp_path)
    with mock.patch.object(
        sync_mod.subprocess, "run",
        return_value=mock.Mock(returncode=1, stdout="", stderr="boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            db.fetch_issue("grava-1")


def test_grava_db_fetch_new_comments(tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    db = GravaDB(tmp_path)
    rows = [
        {"id": 5, "issue_id": "grava-1", "message": "hi", "actor": "coder",
         "created_at": "2026-05-13T00:00:00"},
        {"id": 6, "issue_id": "grava-1", "message": "two", "actor": "coder",
         "created_at": "2026-05-13T00:00:01"},
    ]
    with mock.patch.object(sync_mod.subprocess, "run", return_value=_fake_sql_result(rows)):
        out = db.fetch_new_comments("grava-1", since_id=4)
    assert [r["id"] for r in out] == [5, 6]


def test_grava_db_fetch_max_comment_id_handles_null(tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    db = GravaDB(tmp_path)
    with mock.patch.object(
        sync_mod.subprocess, "run",
        return_value=_fake_sql_result([{"max_id": None}]),
    ):
        assert db.fetch_max_comment_id("grava-x") == 0


# ─── main() integration ──────────────────────────────────────────────────────


def test_main_exits_0_when_plane_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_mod, "plane_configured", lambda: False)
    rc = main([
        "grava-1",
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
    ])
    assert rc == 0


def test_main_exits_0_when_no_internet(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_mod, "plane_configured", lambda: True)
    monkeypatch.setattr(sync_mod, "internet_ok", lambda **_: False)
    rc = main([
        "grava-1",
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
        "--state-file", str(tmp_path / "state.json"),
    ])
    assert rc == 0


def test_main_exits_2_when_issue_not_mirrored(monkeypatch, tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    monkeypatch.setattr(sync_mod, "plane_configured", lambda: True)
    monkeypatch.setattr(sync_mod, "internet_ok", lambda **_: True)
    # GravaDB.fetch_issue returns None.
    monkeypatch.setattr(GravaDB, "fetch_issue", lambda self, iid: None)
    rc = main([
        "grava-ghost",
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
        "--state-file", str(tmp_path / "state.json"),
    ])
    assert rc == 2


def test_main_first_seen_initialises_comment_cursor(monkeypatch, tmp_path):
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(sync_mod, "plane_configured", lambda: True)
    monkeypatch.setattr(sync_mod, "internet_ok", lambda **_: True)
    monkeypatch.setattr(sync_mod, "load_credentials", lambda: ("tok", "h", "ws"))
    fake_client = FakePlaneClient(
        states=[{"id": "s1", "name": "Todo", "group": "unstarted", "sequence": 1}],
        work_items=[{"id": "u1", "sequence_id": 10}],
        get_responses={"u1": {"state": "s1", "assignees": []}},
    )
    monkeypatch.setattr(sync_mod, "PlaneClient", lambda **kw: fake_client)

    monkeypatch.setattr(GravaDB, "fetch_issue", lambda self, iid: {
        "id": "grava-1", "status": "open", "assignee": None, "seq_id": "10",
    })
    monkeypatch.setattr(GravaDB, "fetch_max_comment_id", lambda self, iid: 42)
    fetched_comments = []
    monkeypatch.setattr(
        GravaDB, "fetch_new_comments",
        lambda self, iid, since_id: fetched_comments.append((iid, since_id)) or [],
    )

    rc = main([
        "grava-1",
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
        "--state-file", str(state_file),
    ])
    assert rc == 0
    # First-seen path means fetch_new_comments NOT called this run.
    assert fetched_comments == []
    state = load_state(state_file)
    assert state.last_comment_id_by_issue.get("grava-1") == 42


# ─── pull_from_plane ─────────────────────────────────────────────────────────


class _StubDB:
    """Quacks like GravaDB but lets us seed mirrored seq_ids."""

    def __init__(self, mirrored_seqs):
        self._rows = [{"id": f"g-{s}", "seq_id": s} for s in mirrored_seqs]

    def fetch_all_plane_issues(self):
        return list(self._rows)


def _patch_grava_helpers(monkeypatch):
    """Replace the three subprocess wrappers; return a call recorder."""
    calls = {"create": [], "label": [], "close": []}
    counter = {"n": 0}

    def fake_create(grava_repo, title, description, issue_type="task", priority="medium"):
        counter["n"] += 1
        new_id = f"grava-new-{counter['n']}"
        calls["create"].append({
            "title": title, "description": description,
            "type": issue_type, "priority": priority, "id": new_id,
        })
        return new_id

    def fake_label(grava_repo, issue_id, label):
        calls["label"].append({"issue_id": issue_id, "label": label})

    def fake_close(grava_repo, issue_id):
        calls["close"].append(issue_id)

    monkeypatch.setattr(sync_mod, "_grava_create_issue", fake_create)
    monkeypatch.setattr(sync_mod, "_grava_add_label", fake_label)
    monkeypatch.setattr(sync_mod, "_grava_close_force", fake_close)
    return calls


def test_pull_creates_missing_mirrors(tmp_path, monkeypatch):
    calls = _patch_grava_helpers(monkeypatch)
    client = FakePlaneClient(
        states=[
            {"id": "s-todo",  "name": "Todo",        "group": "unstarted"},
            {"id": "s-prog",  "name": "In Progress", "group": "started"},
            {"id": "s-done",  "name": "Done",        "group": "completed"},
        ],
        work_items=[
            {"id": "u-1", "sequence_id": 101, "name": "Backlog task",
             "description_stripped": "do x", "priority": "high", "state": "s-todo"},
            {"id": "u-2", "sequence_id": 102, "name": "Doing now",
             "description_stripped": "", "priority": "urgent", "state": "s-prog"},
            {"id": "u-3", "sequence_id": 103, "name": "Already done",
             "description_stripped": "", "priority": "low", "state": "s-done"},
        ],
    )
    db = _StubDB(mirrored_seqs=[])  # nothing mirrored locally yet

    counts = sync_mod.pull_from_plane(client, "proj-1", tmp_path, db)
    assert counts == {"scanned": 3, "already_linked": 0, "created": 3, "skipped": 0, "failed": 0}
    assert len(calls["create"]) == 3
    titles = [c["title"] for c in calls["create"]]
    assert titles == ["Backlog task", "Doing now", "Already done"]
    # Priority mapping: high→high, urgent→critical, low→low
    prios = [c["priority"] for c in calls["create"]]
    assert prios == ["high", "critical", "low"]
    # Labels applied with correct seq.
    labels = [l["label"] for l in calls["label"]]
    assert labels == ["plane:101", "plane:102", "plane:103"]
    # Only the completed-group item got closed.
    assert len(calls["close"]) == 1


def test_pull_skips_already_linked(tmp_path, monkeypatch):
    calls = _patch_grava_helpers(monkeypatch)
    client = FakePlaneClient(
        states=[{"id": "s-todo", "name": "Todo", "group": "unstarted"}],
        work_items=[
            {"id": "u-1", "sequence_id": 200, "name": "old", "state": "s-todo"},
            {"id": "u-2", "sequence_id": 201, "name": "new", "state": "s-todo"},
        ],
    )
    db = _StubDB(mirrored_seqs=["200"])

    counts = sync_mod.pull_from_plane(client, "proj-1", tmp_path, db)
    assert counts == {"scanned": 2, "already_linked": 1, "created": 1, "skipped": 0, "failed": 0}
    titles = [c["title"] for c in calls["create"]]
    assert titles == ["new"]


def test_pull_handles_missing_sequence_id(tmp_path, monkeypatch):
    calls = _patch_grava_helpers(monkeypatch)
    client = FakePlaneClient(
        states=[{"id": "s", "name": "X", "group": "unstarted"}],
        work_items=[{"id": "u-1", "name": "no-seq", "state": "s"}],
    )
    db = _StubDB(mirrored_seqs=[])

    counts = sync_mod.pull_from_plane(client, "proj-1", tmp_path, db)
    assert counts == {"scanned": 1, "already_linked": 0, "created": 0, "skipped": 1, "failed": 0}
    assert calls["create"] == []


def test_pull_counts_failed_creates(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("grava create exploded")

    monkeypatch.setattr(sync_mod, "_grava_create_issue", boom)
    monkeypatch.setattr(sync_mod, "_grava_add_label", lambda *a, **kw: None)
    monkeypatch.setattr(sync_mod, "_grava_close_force", lambda *a, **kw: None)

    client = FakePlaneClient(
        states=[{"id": "s", "name": "X", "group": "unstarted"}],
        work_items=[
            {"id": "u-1", "sequence_id": 300, "name": "x", "state": "s"},
        ],
    )
    db = _StubDB(mirrored_seqs=[])
    counts = sync_mod.pull_from_plane(client, "proj-1", tmp_path, db)
    assert counts["failed"] == 1
    assert counts["created"] == 0


# ─── main() --direction routing ──────────────────────────────────────────────


def test_main_direction_pull_skips_push(tmp_path, monkeypatch):
    """`--direction pull` runs pull_from_plane and does NOT run push (sync_issue)."""
    state_file = tmp_path / "s.json"
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)

    monkeypatch.setattr(sync_mod, "plane_configured", lambda: True)
    monkeypatch.setattr(sync_mod, "internet_ok", lambda: True)
    monkeypatch.setattr(
        sync_mod, "load_credentials",
        lambda: ("tok", "https://api.plane.so", "ws"),
    )
    # Stub PlaneClient → ignore constructor args, return a sentinel.
    monkeypatch.setattr(sync_mod, "PlaneClient", lambda **kw: object())

    pull_called = {"n": 0}
    sync_issue_called = {"n": 0}

    def fake_pull(client, project_id, grava_repo, db):
        pull_called["n"] += 1
        return {"scanned": 0, "already_linked": 0, "created": 0, "skipped": 0, "failed": 0}

    def fake_sync_issue(*a, **kw):
        sync_issue_called["n"] += 1

    monkeypatch.setattr(sync_mod, "pull_from_plane", fake_pull)
    monkeypatch.setattr(sync_mod, "sync_issue", fake_sync_issue)

    rc = main([
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
        "--state-file", str(state_file),
        "--direction", "pull",
    ])
    assert rc == 0
    assert pull_called["n"] == 1
    assert sync_issue_called["n"] == 0


def test_main_direction_push_skips_pull(tmp_path, monkeypatch):
    """Default `--direction push` does NOT call pull_from_plane."""
    state_file = tmp_path / "s.json"
    (tmp_path / ".grava" / "dolt").mkdir(parents=True)

    monkeypatch.setattr(sync_mod, "plane_configured", lambda: True)
    monkeypatch.setattr(sync_mod, "internet_ok", lambda: True)
    monkeypatch.setattr(
        sync_mod, "load_credentials",
        lambda: ("tok", "https://api.plane.so", "ws"),
    )
    monkeypatch.setattr(sync_mod, "PlaneClient", lambda **kw: object())

    monkeypatch.setattr(GravaDB, "fetch_all_plane_issues", lambda self: [])

    pull_called = {"n": 0}
    monkeypatch.setattr(
        sync_mod, "pull_from_plane",
        lambda *a, **kw: pull_called.__setitem__("n", pull_called["n"] + 1) or {},
    )

    rc = main([
        "--project-id", "proj-1",
        "--grava-repo", str(tmp_path),
        "--state-file", str(state_file),
        # no --direction → default push
    ])
    assert rc == 0
    assert pull_called["n"] == 0
