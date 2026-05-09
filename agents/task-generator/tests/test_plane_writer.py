"""Unit tests for plane_writer.execute."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_writer  # noqa: E402
from ir import (  # noqa: E402
    AddComment,
    CreateWorkItem,
    RunPlan,
    RunState,
    UpdateWorkItem,
)


def _make_state(tmp_path: Path, ops_total: int) -> RunState:
    return RunState(
        run_id="run01",
        project_id="proj",
        page_id="page",
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ops_total=ops_total,
    )


def _make_plan(ops):
    return RunPlan(plane_ops=ops, grava_ops=[], preview_path=Path("/tmp/x.md"), warnings=[])


TYPE_MAP = {"epic": "type-epic", "story": "type-story", "task": "type-task"}


class FakeClient:
    """Records calls; returns scripted responses."""

    def __init__(self, *, fail_on=None):
        self.calls = []  # list of (method, args, kwargs)
        self._fail_on = fail_on or {}  # {(method_name, occurrence_index): exc_to_raise}
        self._counts = {}
        self.created = []  # list of {payload, returned_id}

    def _maybe_fail(self, name):
        i = self._counts.get(name, 0)
        self._counts[name] = i + 1
        if (name, i) in self._fail_on:
            raise self._fail_on[(name, i)]

    def create_work_item(self, project_id, payload):
        self._maybe_fail("create_work_item")
        i = len(self.created)
        new_id = f"wi-{i}"
        self.calls.append(("create", project_id, payload))
        self.created.append({"payload": payload, "id": new_id})
        return {"id": new_id, "sequence_id": 100 + i}

    def add_comment(self, project_id, issue_id, comment_html):
        self._maybe_fail("add_comment")
        self.calls.append(("comment", project_id, issue_id, comment_html))
        return {"id": f"c-{len(self.calls)}"}

    def get_work_item(self, project_id, issue_id):
        self.calls.append(("get", project_id, issue_id))
        return {"description_html": "<p>existing</p>"}

    def update_work_item(self, project_id, issue_id, payload):
        self._maybe_fail("update_work_item")
        self.calls.append(("update", project_id, issue_id, payload))
        return {"id": issue_id}

    def delete_work_item(self, project_id, issue_id):
        self._maybe_fail("delete_work_item")
        self.calls.append(("delete", project_id, issue_id))


def _hierarchy_ops():
    """1 epic, 2 stories, 1 task under story 0, 1 comment, 1 update."""
    return [
        CreateWorkItem(
            node_kind="epic", title="E", description_html="",
            type_id_key="epic", parent_ref=None, ref_key="epic:0",
        ),
        CreateWorkItem(
            node_kind="story", title="S0", description_html="",
            type_id_key="story", parent_ref="epic:0", ref_key="story:0.0",
        ),
        CreateWorkItem(
            node_kind="story", title="S1", description_html="",
            type_id_key="story", parent_ref="epic:0", ref_key="story:0.1",
        ),
        CreateWorkItem(
            node_kind="task", title="T0", description_html="",
            type_id_key="task", parent_ref="story:0.0", ref_key="task:0.0.0",
        ),
        AddComment(target_ref_key="epic:0", comment_html="<p>open q</p>"),
        UpdateWorkItem(
            target_ref_key="epic:0",
            patch={"description_html_append": "\nRelated: STELLAR-1"},
        ),
    ]


def test_execute_creates_in_order(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient()
    report = plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    create_calls = [c for c in client.calls if c[0] == "create"]
    assert [c[2]["name"] for c in create_calls] == ["E", "S0", "S1", "T0"]
    # parent UUIDs resolve from prior creates
    assert create_calls[1][2]["parent"] == "wi-0"
    assert create_calls[2][2]["parent"] == "wi-0"
    assert create_calls[3][2]["parent"] == "wi-1"
    assert report.failed_op is None
    assert len(report.plane_created) == 4
    assert len(report.plane_comments) == 1
    assert len(report.plane_updated) == 1


def test_execute_resolves_comment_target(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient()
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    comment_calls = [c for c in client.calls if c[0] == "comment"]
    assert len(comment_calls) == 1
    # epic:0 was the first create, got wi-0
    assert comment_calls[0][2] == "wi-0"


def test_update_append_merges_existing_description(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient()
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    update_calls = [c for c in client.calls if c[0] == "update"]
    assert len(update_calls) == 1
    body = update_calls[0][3]
    assert body["description_html"].startswith("<p>existing</p>")
    assert "Related: STELLAR-1" in body["description_html"]
    assert "description_html_append" not in body


def test_execute_resume_skips_completed_ops(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    state.completed_op_indices = [0, 1, 2]
    state.ref_to_uuid = {"epic:0": "wi-pre-0", "story:0.0": "wi-pre-1", "story:0.1": "wi-pre-2"}
    client = FakeClient()
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    create_calls = [c for c in client.calls if c[0] == "create"]
    # Only the task (op 3) gets created
    assert len(create_calls) == 1
    assert create_calls[0][2]["name"] == "T0"
    # Task's parent UUID came from the pre-populated state
    assert create_calls[0][2]["parent"] == "wi-pre-1"


def test_execute_checkpoint_after_each_op(tmp_path):
    plan = _make_plan(_hierarchy_ops()[:2])  # 1 epic + 1 story
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient()
    state_path = tmp_path / "state.json"
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=state_path,
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    saved = json.loads(state_path.read_text())
    assert saved["completed_op_indices"] == [0, 1]
    assert saved["ref_to_uuid"]["epic:0"] == "wi-0"
    assert saved["ref_to_uuid"]["story:0.0"] == "wi-1"


def test_execute_rollback_deletes_in_reverse(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    # Fail on op index 4 (the comment) — first 4 creates already succeed
    client = FakeClient(fail_on={("add_comment", 0): RuntimeError("API down")})
    state_path = tmp_path / "state.json"
    report_path = tmp_path / "report.json"
    report = plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=state_path,
        report_path=report_path,
        on_failure="rollback",
    )
    delete_calls = [c for c in client.calls if c[0] == "delete"]
    # 4 creates -> 4 deletes in reverse order (task, story1, story0, epic)
    assert [c[2] for c in delete_calls] == ["wi-3", "wi-2", "wi-1", "wi-0"]
    assert report.rolled_back is True
    assert report.failed_op is not None
    assert report.failed_op["index"] == 4
    saved = json.loads(state_path.read_text())
    assert saved["rolled_back"] is True


def test_execute_abort_persists_failure(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient(fail_on={("create_work_item", 2): RuntimeError("503")})
    state_path = tmp_path / "state.json"
    report_path = tmp_path / "report.json"
    report = plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=state_path,
        report_path=report_path,
        on_failure="abort",
    )
    delete_calls = [c for c in client.calls if c[0] == "delete"]
    assert delete_calls == []
    assert report.failed_op["index"] == 2
    saved = json.loads(state_path.read_text())
    assert saved["failed_op_index"] == 2
    assert "503" in saved["failure_detail"]
    assert saved["completed_op_indices"] == [0, 1]


def test_execute_writes_report_on_success(tmp_path):
    plan = _make_plan(_hierarchy_ops()[:1])  # epic only
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient()
    report_path = tmp_path / "report.json"
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=report_path,
        on_failure="abort",
    )
    assert report_path.exists()
    saved = json.loads(report_path.read_text())
    assert saved["spec_page_id"] == "page"
    assert len(saved["plane_created"]) == 1
    assert saved["finished_at"]


def test_execute_writes_report_on_failure(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient(fail_on={("create_work_item", 0): RuntimeError("oops")})
    report_path = tmp_path / "report.json"
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=report_path,
        on_failure="abort",
    )
    assert report_path.exists()
    saved = json.loads(report_path.read_text())
    assert saved["failed_op"]["index"] == 0


def test_execute_prompt_yes_triggers_rollback(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient(fail_on={("add_comment", 0): RuntimeError("boom")})
    report = plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="prompt",
        input_fn=lambda _msg: "y",
    )
    delete_calls = [c for c in client.calls if c[0] == "delete"]
    assert len(delete_calls) == 4
    assert report.rolled_back is True


def test_execute_prompt_no_aborts(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    state = _make_state(tmp_path, len(plan.plane_ops))
    client = FakeClient(fail_on={("add_comment", 0): RuntimeError("boom")})
    report = plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="prompt",
        input_fn=lambda _msg: "",
    )
    delete_calls = [c for c in client.calls if c[0] == "delete"]
    assert delete_calls == []
    assert report.rolled_back is False


def test_execute_missing_type_raises_helpful_error(tmp_path):
    plan = _make_plan(_hierarchy_ops()[:1])
    state = _make_state(tmp_path, 1)
    client = FakeClient()
    report = plane_writer.execute(
        plan, client, state, "proj", {"story": "s", "task": "t"},  # epic missing
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    assert report.failed_op is not None
    assert "epic" in report.failed_op["detail"]


def test_create_omits_empty_description_html(tmp_path):
    """Plane rejects description_html='' with 'Invalid HTML passed' — omit it instead."""
    op = CreateWorkItem(
        node_kind="task", title="t", description_html="",
        type_id_key="task", parent_ref=None, ref_key="task:0",
    )
    plan = _make_plan([op])
    state = _make_state(tmp_path, 1)
    client = FakeClient()
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    create_call = next(c for c in client.calls if c[0] == "create")
    assert "description_html" not in create_call[2]


def test_create_includes_description_html_when_present(tmp_path):
    op = CreateWorkItem(
        node_kind="task", title="t", description_html="<p>hello</p>",
        type_id_key="task", parent_ref=None, ref_key="task:0",
    )
    plan = _make_plan([op])
    state = _make_state(tmp_path, 1)
    client = FakeClient()
    plane_writer.execute(
        plan, client, state, "proj", TYPE_MAP,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        on_failure="abort",
    )
    create_call = next(c for c in client.calls if c[0] == "create")
    assert create_call[2]["description_html"] == "<p>hello</p>"


def test_load_state_returns_none_when_missing(tmp_path):
    assert plane_writer.load_state(tmp_path / "absent.json") is None


def test_load_state_round_trip(tmp_path):
    state = _make_state(tmp_path, 5)
    state.completed_op_indices = [0, 1]
    state.ref_to_uuid = {"epic:0": "wi-0"}
    state_path = tmp_path / "state.json"
    plane_writer._atomic_write_state(state, state_path)
    loaded = plane_writer.load_state(state_path)
    assert loaded.completed_op_indices == [0, 1]
    assert loaded.ref_to_uuid == {"epic:0": "wi-0"}
    assert loaded.run_id == "run01"
