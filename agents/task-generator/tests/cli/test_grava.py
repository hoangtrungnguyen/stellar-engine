"""Tests for cli/grava.py."""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import grava as grava_cli  # noqa: E402

PROJECT_ID = "proj-uuid-1"
PAGE_ID = "page-uuid-1"


def _seed_workdir(tmp_path: Path, *, plane_failed=False, completed=None) -> Path:
    work_dir = tmp_path / "runs" / "work" / "20260510-090000"
    work_dir.mkdir(parents=True)

    (work_dir / "page.json").write_text(json.dumps({
        "project_id": PROJECT_ID,
        "page_id": PAGE_ID,
        "title": "Spec",
        "description_html": "",
        "spec_page_url": "https://x",
        "fetched_at": "2026-05-10T09:00:00Z",
    }))

    (work_dir / "preflight.json").write_text(json.dumps({
        "project_id": PROJECT_ID,
        "page_id": PAGE_ID,
        "type_uuids": {"epic": "t-epic", "story": "t-story", "task": "t-task"},
        "label_uuids": {},
        "duplicates": [],
        "duplicates_bypassed": False,
    }))

    (work_dir / "ir.json").write_text(json.dumps({
        "epics": [{
            "title": "E0",
            "description_md": "",
            "spec_page_url": "https://x",
            "spec_page_id": PAGE_ID,
            "open_questions": [],
            "risks": [],
            "related_refs": [],
            "stories": [
                {
                    "title": "S0",
                    "description_md": "",
                    "type_marker": None,
                    "related_refs": [],
                    "tasks": [
                        {"title": "T0", "description_md": "", "type_marker": None, "related_refs": []},
                    ],
                },
            ],
        }],
        "warnings": [],
        "page_title": "Spec",
    }))

    # Plane state — simulate Phase 2 completed (or failed if requested)
    from ir import RunState
    plane_state = RunState(
        run_id=work_dir.name,
        project_id=PROJECT_ID,
        page_id=PAGE_ID,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ops_total=3,
    )
    plane_state.completed_op_indices = [0, 1, 2]
    plane_state.ref_to_uuid = {"epic:0": "uE", "story:0.0": "uS", "task:0.0.0": "uT"}
    plane_state.ref_to_sequence_id = {"epic:0": 1, "story:0.0": 2, "task:0.0.0": 3}
    if plane_failed:
        plane_state.failed_op_index = 1
        plane_state.failure_detail = "synthetic"
    (work_dir / "run_state.json").write_text(json.dumps(asdict(plane_state), indent=2))

    if completed is not None:
        from ir import GravaState
        g = GravaState(
            run_id=work_dir.name,
            target_repo=str(tmp_path),
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ops_total=3,
            completed_op_indices=completed,
            ref_to_grava_id={"epic:0": "g-pre"} if 0 in completed else {},
        )
        (work_dir / "grava_state.json").write_text(json.dumps(asdict(g), indent=2))

    return work_dir


class _FakeClient:
    def __init__(self):
        self.added = []

    def get_work_item(self, project_id, uuid):
        return {"name": f"item-{uuid}", "description_html": "", "priority": "none"}

    def add_comment(self, project_id, uuid, html):
        self.added.append({"uuid": uuid, "html": html})
        return {"id": "c-1"}


_singleton = None


def _fake_factory():
    global _singleton
    _singleton = _FakeClient()
    return _singleton


def _patch_grava_subprocess(monkeypatch, fail_at=None):
    """Wrap grava_writer.execute so it injects a fake subprocess.run."""
    from types import SimpleNamespace
    counter = {"n": 0}
    create_ids = ["g-E", "g-S", "g-T"]

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False, **kw):
        counter["n"] += 1
        if fail_at is not None and counter["n"] == fail_at:
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps({"error": {"message": "synthetic boom"}}),
                stderr="",
            )
        sub = cmd[1] if len(cmd) > 1 else ""
        if sub == "list":
            return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")
        if sub in ("create", "subtask"):
            return SimpleNamespace(returncode=0, stdout=json.dumps({"id": create_ids.pop(0)}), stderr="")
        if sub == "label":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"id": cmd[2]}), stderr="")
        if sub == "drop":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"id": cmd[2]}), stderr="")
        if sub == "commit":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"hash": "deadbeef"}), stderr="")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    import grava_writer as gw
    original = gw.execute

    def patched_execute(*args, **kwargs):
        kwargs.setdefault("run_subprocess", fake_run)
        return original(*args, **kwargs)

    monkeypatch.setattr(gw, "execute", patched_execute)


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["grava.py", *argv])
    rc = grava_cli.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_grava_blocks_when_plane_phase_incomplete(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path, plane_failed=True)
    (tmp_path / ".grava.yaml").write_text("dummy: 1")
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 1
    assert "Plane writes incomplete" in err


def test_grava_blocks_on_missing_grava_init(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    # Do NOT create .grava.yaml
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 4
    assert "not initialised" in err


def test_grava_succeeds_with_yes(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    (tmp_path / ".grava.yaml").write_text("dummy: 1")
    _patch_grava_subprocess(monkeypatch)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 0
    assert "report:" in out
    assert "grava_created=3" in out
    report_path = tmp_path / "runs" / "reports" / "20260510-090000.json"
    assert report_path.exists()


def test_grava_resume_skips_confirmation(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path, completed=[0])
    (tmp_path / ".grava.yaml").write_text("dummy: 1")
    _patch_grava_subprocess(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _msg: (_ for _ in ()).throw(
        AssertionError("input() should not be called on resume")
    ))
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 0
    assert "Resuming run" in err


def test_grava_confirmation_required_on_first_run(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    (tmp_path / ".grava.yaml").write_text("dummy: 1")
    _patch_grava_subprocess(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _msg: "n")
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 0
    assert "Aborted" in err


def test_grava_partial_failure_exits_5(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    (tmp_path / ".grava.yaml").write_text("dummy: 1")
    # First call is `list`; second is `create`. Fail on 2nd.
    _patch_grava_subprocess(monkeypatch, fail_at=2)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--on-failure", "abort",
        "--client-factory", "tests.cli.test_grava._fake_factory",
    ])
    assert rc == 5
    saved = json.loads((tmp_path / "runs" / "reports" / "20260510-090000.json").read_text())
    assert saved["failed_op"] is not None


def test_grava_missing_workdir_files_exit_1(monkeypatch, tmp_path, capsys):
    bare = tmp_path / "empty"
    bare.mkdir()
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(bare), "--target-repo", str(tmp_path), "--yes",
    ])
    assert rc == 1
    assert "missing required file" in err
