"""Unit tests for grava_writer.execute."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grava_writer  # noqa: E402
from ir import (  # noqa: E402
    CreateWorkItem,
    GravaState,
    RunPlan,
    RunState,
)


WORKSPACE = "ws"
PROJECT_ID = "proj"
PROJECT_IDENT = "PROJ"
SPEC_URL = "https://app.plane.so/ws/projects/proj/pages/page-A/"


def _make_grava_state(tmp_path: Path, ops_total: int) -> GravaState:
    return GravaState(
        run_id="run01",
        target_repo=str(tmp_path),
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ops_total=ops_total,
    )


def _make_plane_state(refs: dict[str, tuple[str, int]]) -> RunState:
    """`refs` is {ref_key: (uuid, sequence_id)}."""
    s = RunState(
        run_id="run01", project_id=PROJECT_ID, page_id="page-A",
        started_at="2026-05-09T12:00:00Z", ops_total=len(refs),
    )
    s.completed_op_indices = list(range(len(refs)))
    s.ref_to_uuid = {k: v[0] for k, v in refs.items()}
    s.ref_to_sequence_id = {k: v[1] for k, v in refs.items()}
    return s


def _hierarchy_ops():
    """1 epic, 1 story under it, 1 task under the story. ref_keys per planner."""
    return [
        CreateWorkItem(
            node_kind="epic", title="Epic A", description_html="<p>e</p>",
            type_id_key="epic", parent_ref=None, ref_key="epic:0",
        ),
        CreateWorkItem(
            node_kind="story", title="Story A.0", description_html="<p>s</p>",
            type_id_key="story", parent_ref="epic:0", ref_key="story:0.0",
        ),
        CreateWorkItem(
            node_kind="task", title="Task A.0.0", description_html="<p>t</p>",
            type_id_key="task", parent_ref="story:0.0", ref_key="task:0.0.0",
        ),
    ]


def _make_plan(ops):
    return RunPlan(plane_ops=ops, grava_ops=[], preview_path=Path("/tmp/x.md"), warnings=[])


def _init_grava_dir(tmp_path: Path) -> Path:
    """Make `tmp_path` look like a grava-initialised repo."""
    (tmp_path / ".grava.yaml").write_text("dummy: true\n")
    return tmp_path


class FakePlaneClient:
    def __init__(self, items: dict[str, dict] | None = None):
        # items keyed by uuid -> dict with name/description_html/priority
        self._items = items or {}
        self.added_comments = []

    def get_work_item(self, project_id, uuid):
        return self._items.get(uuid, {
            "name": "Default", "description_html": "", "priority": "none",
        })

    def add_comment(self, project_id, uuid, comment_html):
        self.added_comments.append({"uuid": uuid, "html": comment_html})
        return {"id": f"c-{len(self.added_comments)}"}


class FakeRunner:
    """Records every subprocess.run call. Returns scripted responses by command-key."""

    def __init__(self, responses: dict[tuple, dict] | None = None,
                 default_create_id_seq: list[str] | None = None):
        self.calls = []  # list of {cmd, cwd, env, ...}
        self._responses = responses or {}
        self._default_creates = default_create_id_seq or []

    def __call__(self, cmd, cwd=None, env=None, capture_output=False,
                 text=False, check=False, **kwargs):
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "env": env})
        # cmd = ["grava", "<sub>", ...positional..., "--json"]
        sub = cmd[1] if len(cmd) > 1 else ""
        # Strip --json off the end for matching
        positional = [c for c in cmd[2:] if c != "--json"]
        # Find a matching scripted response, otherwise default behaviour.
        key = (sub, tuple(positional[:1]))  # match by (sub, first positional)
        for k, v in self._responses.items():
            ksub, kargs = k
            if ksub == sub and (not kargs or all(a in cmd for a in kargs)):
                return self._make_completed(v)

        # Defaults
        if sub in ("create", "subtask"):
            new_id = self._default_creates.pop(0) if self._default_creates else f"grava-{len(self.calls):04d}"
            return self._make_completed({"id": new_id, "title": "x", "status": "open"})
        if sub == "label":
            return self._make_completed({"id": cmd[2], "labels_added": [], "current_labels": []})
        if sub == "list":
            return self._make_completed([])
        if sub == "update":
            return self._make_completed({"id": cmd[2]})
        if sub == "drop":
            return self._make_completed({"id": cmd[2], "archived": True})
        if sub == "commit":
            return self._make_completed({"hash": "deadbeef"})
        return self._make_completed({})

    @staticmethod
    def _make_completed(payload, returncode=0, stderr=""):
        return SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps(payload) if not isinstance(payload, str) else payload,
            stderr=stderr,
        )


def _exec(plan, plane_state, target_repo, *, client=None, runner=None,
          state=None, on_failure="abort", input_fn=None,
          report_path=None, state_path=None):
    if client is None:
        client = FakePlaneClient()
    if runner is None:
        runner = FakeRunner()
    if state is None:
        state = _make_grava_state(target_repo, len(plan.plane_ops))
    return grava_writer.execute(
        plan, plane_state, target_repo, client, PROJECT_ID,
        SPEC_URL, WORKSPACE,
        state=state,
        state_path=state_path or (target_repo / "grava_state.json"),
        report_path=report_path or (target_repo / "report.json"),
        project_identifier=PROJECT_IDENT,
        on_failure=on_failure,
        input_fn=input_fn or (lambda _msg: ""),
        run_subprocess=runner,
    )


# ── Pre-flight ────────────────────────────────────────────────────────────────


def test_grava_init_missing_raises(tmp_path):
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({"epic:0": ("u0", 1)})
    with pytest.raises(RuntimeError, match="not initialised"):
        _exec(plan, plane_state, tmp_path)


# ── Create path ───────────────────────────────────────────────────────────────


def test_execute_creates_in_order(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })
    runner = FakeRunner(default_create_id_seq=["grava-0001", "grava-0001.1", "grava-0001.1.1"])
    report = _exec(plan, plane_state, target, runner=runner)

    # Subprocess sequence: list, create, label, list, subtask, label, list, subtask, label, [comments via Plane], commit
    subs = [c["cmd"][1] for c in runner.calls]
    create_subs = [s for s in subs if s in ("create", "subtask")]
    assert create_subs == ["create", "subtask", "subtask"]

    create_call = next(c for c in runner.calls if c["cmd"][1] == "create")
    assert "-t" in create_call["cmd"]
    t_idx = create_call["cmd"].index("-t")
    assert create_call["cmd"][t_idx + 1] == "Default"
    assert "--type" in create_call["cmd"]
    type_idx = create_call["cmd"].index("--type")
    assert create_call["cmd"][type_idx + 1] == "epic"
    assert create_call["cwd"] == str(target)

    subtask_calls = [c for c in runner.calls if c["cmd"][1] == "subtask"]
    # First subtask uses epic's grava id as parent
    assert subtask_calls[0]["cmd"][2] == "grava-0001"
    # Second subtask uses story's grava id (NOT epic's) as parent
    assert subtask_calls[1]["cmd"][2] == "grava-0001.1"

    assert report.failed_op is None
    assert len(report.grava_created) == 3
    assert report.grava_commit_hash == "deadbeef"


def test_subtask_passes_grava_parent(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 10),
        "story:0.0": ("uS", 20),
        "task:0.0.0": ("uT", 30),
    })
    runner = FakeRunner(default_create_id_seq=["g-E", "g-S", "g-T"])
    _exec(plan, plane_state, target, runner=runner)
    sub_calls = [c for c in runner.calls if c["cmd"][1] == "subtask"]
    assert sub_calls[0]["cmd"][2] == "g-E"
    assert sub_calls[1]["cmd"][2] == "g-S"


def test_labels_applied_per_level(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 100),
        "story:0.0": ("uS", 101),
        "task:0.0.0": ("uT", 102),
    })
    runner = FakeRunner(default_create_id_seq=["g-E", "g-S", "g-T"])
    _exec(plan, plane_state, target, runner=runner)

    label_calls = [c for c in runner.calls if c["cmd"][1] == "label"]
    # 3 label calls (one per create)
    assert len(label_calls) == 3

    epic_label = label_calls[0]["cmd"]
    assert epic_label[2] == "g-E"
    assert "plane:100" in epic_label
    assert "plane-epic:100" not in epic_label
    assert "plane-story:100" not in epic_label

    story_label = label_calls[1]["cmd"]
    assert story_label[2] == "g-S"
    assert "plane:101" in story_label
    assert "plane-epic:100" in story_label
    assert "plane-story:101" not in story_label

    task_label = label_calls[2]["cmd"]
    assert task_label[2] == "g-T"
    assert "plane:102" in task_label
    assert "plane-epic:100" in task_label
    assert "plane-story:101" in task_label


def test_priority_propagated_from_plane(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 1)})
    client = FakePlaneClient(items={
        "uE": {"name": "E", "description_html": "<p>x</p>", "priority": "high"},
    })
    runner = FakeRunner(default_create_id_seq=["g-E"])
    _exec(plan, plane_state, target, client=client, runner=runner)
    create_call = next(c for c in runner.calls if c["cmd"][1] == "create")
    assert "-p" in create_call["cmd"]
    p_idx = create_call["cmd"].index("-p")
    assert create_call["cmd"][p_idx + 1] == "high"


def test_priority_mapping_table(tmp_path):
    cases = [
        ("urgent", "critical"),
        ("high", "high"),
        ("medium", "medium"),
        ("low", "low"),
        ("none", "medium"),
        (None, "medium"),
        ("", "medium"),
    ]
    for plane_p, expected in cases:
        assert grava_writer._map_priority(plane_p) == expected, f"failed: {plane_p}"


def test_description_embeds_plane_urls(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })
    runner = FakeRunner(default_create_id_seq=["g-E", "g-S", "g-T"])
    _exec(plan, plane_state, target, runner=runner)

    task_call = next(c for c in runner.calls if c["cmd"][1] == "subtask"
                     and "Default" in c["cmd"] and "task" in c["cmd"])
    d_idx = task_call["cmd"].index("-d")
    desc = task_call["cmd"][d_idx + 1]
    assert "Plane:" in desc
    # New format: /browse/{IDENTIFIER}-{SEQ}/
    assert f"/browse/{PROJECT_IDENT}-3/" in desc        # task seq=3
    assert "Plane epic:" in desc
    assert f"/browse/{PROJECT_IDENT}-1/" in desc        # epic seq=1
    assert "Plane story:" in desc
    assert f"/browse/{PROJECT_IDENT}-2/" in desc        # story seq=2
    assert f"Spec: {SPEC_URL}" in desc

    # Epic description must NOT include parent links (it's the root).
    epic_call = next(c for c in runner.calls if c["cmd"][1] == "create")
    e_idx = epic_call["cmd"].index("-d")
    edesc = epic_call["cmd"][e_idx + 1]
    assert "Plane epic:" not in edesc
    assert "Plane story:" not in edesc


def test_comment_back_after_all_creates(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })
    client = FakePlaneClient()
    runner = FakeRunner(default_create_id_seq=["g-E", "g-S", "g-T"])
    _exec(plan, plane_state, target, client=client, runner=runner)
    assert len(client.added_comments) == 3
    assert {c["uuid"] for c in client.added_comments} == {"uE", "uS", "uT"}
    assert all("Mirrored to Grava" in c["html"] for c in client.added_comments)


# ── Update path (idempotency) ─────────────────────────────────────────────────


def test_update_path_when_label_match_found(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])  # epic only
    plane_state = _make_plane_state({"epic:0": ("uE", 42)})
    client = FakePlaneClient(items={
        "uE": {"name": "Epic A new title", "description_html": "<p>new</p>", "priority": "high"},
    })
    runner = FakeRunner(responses={
        ("list", ("--label",)): [{
            "id": "grava-EXIST",
            "title": "Epic A old title",
            "description": "Plane: old\n\nold body",
            "priority": 2,
        }],
    })
    report = _exec(plan, plane_state, target, client=client, runner=runner)

    update_calls = [c for c in runner.calls if c["cmd"][1] == "update"]
    assert len(update_calls) == 1
    assert update_calls[0]["cmd"][2] == "grava-EXIST"

    create_calls = [c for c in runner.calls if c["cmd"][1] == "create"]
    assert create_calls == []  # no create, only update

    assert len(report.grava_updated) == 1
    assert report.grava_updated[0]["grava_id"] == "grava-EXIST"
    assert "title" in report.grava_updated[0]["fields_changed"]

    assert client.added_comments == []  # update path skips comment-back


def test_update_path_skips_no_op_when_unchanged(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 7)})
    # Same title, desc body, priority that the writer would compute.
    client = FakePlaneClient(items={
        "uE": {"name": "EpicX", "description_html": "<p>body</p>", "priority": "high"},
    })
    expected_desc = f"Plane: https://app.plane.so/ws/browse/{PROJECT_IDENT}-7/\n\nbody"
    runner = FakeRunner(responses={
        ("list", ("--label",)): [{
            "id": "grava-NO-OP",
            "title": "EpicX",
            "description": expected_desc,
            "priority": 1,
        }],
    })
    _exec(plan, plane_state, target, client=client, runner=runner)
    update_calls = [c for c in runner.calls if c["cmd"][1] == "update"]
    assert update_calls == []


def test_create_path_when_no_label_match(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 1)})
    runner = FakeRunner(
        default_create_id_seq=["g-NEW"],
        responses={("list", ("--label",)): []},
    )
    report = _exec(plan, plane_state, target, runner=runner)
    assert len(report.grava_created) == 1
    assert report.grava_updated == []


def test_anomaly_when_multiple_label_matches(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 99)})
    runner = FakeRunner(responses={
        ("list", ("--label",)): [
            {"id": "grava-A", "title": "X"},
            {"id": "grava-B", "title": "Y"},
        ],
    })
    report = _exec(plan, plane_state, target, runner=runner)
    assert len(report.grava_anomalies) == 1
    assert report.grava_anomalies[0]["matched_grava_ids"] == ["grava-A", "grava-B"]
    create_calls = [c for c in runner.calls if c["cmd"][1] == "create"]
    update_calls = [c for c in runner.calls if c["cmd"][1] == "update"]
    assert create_calls == []
    assert update_calls == []


# ── Resume / checkpoint ───────────────────────────────────────────────────────


def test_resume_skips_completed_ops(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })
    state = _make_grava_state(target, 3)
    state.completed_op_indices = [0, 1]
    state.ref_to_grava_id = {"epic:0": "g-pre-E", "story:0.0": "g-pre-S"}
    runner = FakeRunner(default_create_id_seq=["g-pre-T"])
    _exec(plan, plane_state, target, state=state, runner=runner)
    create_subs = [c for c in runner.calls if c["cmd"][1] in ("create", "subtask")]
    assert len(create_subs) == 1
    # Only the task — and it should use story's pre-existing grava id as parent
    assert create_subs[0]["cmd"][1] == "subtask"
    assert create_subs[0]["cmd"][2] == "g-pre-S"


def test_checkpoint_after_each_op(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:2])  # epic + story
    plane_state = _make_plane_state({"epic:0": ("uE", 1), "story:0.0": ("uS", 2)})
    runner = FakeRunner(default_create_id_seq=["g-E", "g-S"])
    state_path = target / "grava_state.json"
    _exec(plan, plane_state, target, runner=runner, state_path=state_path)
    saved = json.loads(state_path.read_text())
    assert saved["completed_op_indices"] == [0, 1]
    assert saved["ref_to_grava_id"]["epic:0"] == "g-E"


# ── Failure paths ─────────────────────────────────────────────────────────────


def test_rollback_drops_in_reverse(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })
    # Fail on the task subtask call (the 2nd subtask).
    sub_count = {"n": 0}
    create_ids = ["g-E", "g-S"]

    class FailingRunner(FakeRunner):
        def __call__(self, cmd, **kw):
            self.calls.append({"cmd": list(cmd), "cwd": kw.get("cwd"), "env": kw.get("env")})
            sub = cmd[1]
            if sub == "subtask":
                sub_count["n"] += 1
                if sub_count["n"] == 2:
                    return self._make_completed({"error": {"message": "boom"}}, returncode=1)
                new_id = create_ids.pop(0)
                return self._make_completed({"id": new_id})
            if sub == "create":
                return self._make_completed({"id": create_ids.pop(0)})
            if sub == "label":
                return self._make_completed({"id": cmd[2]})
            if sub == "list":
                return self._make_completed([])
            if sub == "drop":
                return self._make_completed({"id": cmd[2]})
            if sub == "commit":
                return self._make_completed({"hash": "x"})
            return self._make_completed({})

    runner = FailingRunner()
    report = _exec(plan, plane_state, target, runner=runner, on_failure="rollback")
    drop_calls = [c for c in runner.calls if c["cmd"][1] == "drop"]
    # 2 successful creates -> 2 drops in reverse: story then epic
    assert [c["cmd"][2] for c in drop_calls] == ["g-S", "g-E"]
    assert report.rolled_back is True
    assert report.failed_op is not None


def test_abort_persists_failure(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops())
    plane_state = _make_plane_state({
        "epic:0": ("uE", 1),
        "story:0.0": ("uS", 2),
        "task:0.0.0": ("uT", 3),
    })

    class FailingRunner(FakeRunner):
        def __call__(self, cmd, **kw):
            self.calls.append({"cmd": list(cmd), "cwd": kw.get("cwd"), "env": kw.get("env")})
            if cmd[1] == "create":
                return self._make_completed({"error": {"message": "down"}}, returncode=1)
            if cmd[1] == "list":
                return self._make_completed([])
            return self._make_completed({})

    runner = FailingRunner()
    state_path = target / "grava_state.json"
    report = _exec(plan, plane_state, target, runner=runner,
                   on_failure="abort", state_path=state_path)
    drop_calls = [c for c in runner.calls if c["cmd"][1] == "drop"]
    assert drop_calls == []
    saved = json.loads(state_path.read_text())
    assert saved["failed_op_index"] == 0
    assert "down" in saved["failure_detail"]


def test_final_commit_invoked(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 1)})
    runner = FakeRunner(default_create_id_seq=["g-E"])
    report = _exec(plan, plane_state, target, runner=runner)
    commit_calls = [c for c in runner.calls if c["cmd"][1] == "commit"]
    assert len(commit_calls) == 1
    assert "-m" in commit_calls[0]["cmd"]
    assert report.grava_commit_hash == "deadbeef"


def test_grava_create_failure_surfaces_error_message(tmp_path):
    target = _init_grava_dir(tmp_path)
    plan = _make_plan(_hierarchy_ops()[:1])
    plane_state = _make_plane_state({"epic:0": ("uE", 1)})

    class FailingRunner(FakeRunner):
        def __call__(self, cmd, **kw):
            self.calls.append({"cmd": list(cmd), "cwd": kw.get("cwd"), "env": kw.get("env")})
            if cmd[1] == "list":
                return self._make_completed([])
            if cmd[1] == "create":
                return self._make_completed({"error": {"message": "title required"}}, returncode=1)
            return self._make_completed({})

    runner = FailingRunner()
    report = _exec(plan, plane_state, target, runner=runner, on_failure="abort")
    assert report.failed_op is not None
    assert "title required" in report.failed_op["detail"]


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_plane_url_uses_browse_format():
    url = grava_writer._plane_url("sportbuddies", "WEBINTRO", 166)
    assert url == "https://app.plane.so/sportbuddies/browse/WEBINTRO-166/"


def test_resolve_ancestors():
    assert grava_writer._resolve_ancestors("epic:0") == (None, None)
    assert grava_writer._resolve_ancestors("story:1.2") == ("epic:1", None)
    assert grava_writer._resolve_ancestors("task:1.2.3") == ("epic:1", "story:1.2")


def test_strip_html():
    assert grava_writer._strip_html("<p>hello <em>world</em></p>") == "hello world"
    assert grava_writer._strip_html("") == ""
    assert grava_writer._strip_html(None) == ""


def test_load_state_round_trip(tmp_path):
    state = _make_grava_state(tmp_path, 3)
    state.ref_to_grava_id = {"epic:0": "g-1"}
    state.plane_comments_posted = ["epic:0"]
    state_path = tmp_path / "g.json"
    grava_writer._atomic_write_state(state, state_path)
    loaded = grava_writer.load_state(state_path)
    assert loaded.ref_to_grava_id == {"epic:0": "g-1"}
    assert loaded.plane_comments_posted == ["epic:0"]
