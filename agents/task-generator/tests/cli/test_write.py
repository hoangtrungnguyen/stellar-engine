"""Tests for cli/write.py."""

import json
import sys
from pathlib import Path

import write as write_cli  # noqa: E402
import plane_writer  # noqa: E402


PROJECT_ID = "proj-uuid-1"
PAGE_ID = "page-uuid-1"


def _seed_workdir(tmp_path: Path, *, missing_types=False, completed=None) -> Path:
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

    type_uuids = {} if missing_types else {
        "epic": "t-epic", "story": "t-story", "task": "t-task",
    }
    (work_dir / "preflight.json").write_text(json.dumps({
        "project_id": PROJECT_ID,
        "page_id": PAGE_ID,
        "type_uuids": type_uuids,
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

    if completed is not None:
        from datetime import datetime, timezone
        from ir import RunState
        from dataclasses import asdict

        state = RunState(
            run_id=work_dir.name,
            project_id=PROJECT_ID,
            page_id=PAGE_ID,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ops_total=3,
            completed_op_indices=completed,
            ref_to_uuid={"epic:0": "wi-pre-0"} if 0 in completed else {},
        )
        (work_dir / "run_state.json").write_text(json.dumps(asdict(state), indent=2))

    return work_dir


class _FakeClient:
    """Counts calls; succeeds unconditionally."""

    def __init__(self):
        self.created = 0

    def create_work_item(self, project_id, payload):
        self.created += 1
        return {"id": f"wi-{self.created}", "sequence_id": 100 + self.created}

    def add_comment(self, project_id, issue_id, comment_html):
        return {"id": "c-1"}

    def get_work_item(self, project_id, issue_id):
        return {"description_html": ""}

    def update_work_item(self, project_id, issue_id, payload):
        return {"id": issue_id}

    def delete_work_item(self, project_id, issue_id):
        pass


_fake_singleton = None


def _fake_factory():
    global _fake_singleton
    _fake_singleton = _FakeClient()
    return _fake_singleton


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["write.py", *argv])
    rc = write_cli.main()
    out, err = capsys.readouterr()
    return rc, out, err


def test_write_blocks_on_missing_types_exit_4(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path, missing_types=True)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
    ])
    assert rc == 4
    assert "missing" in err
    assert "epic" in err


def test_write_confirmation_required_on_first_run(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _msg: "n")
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert "Aborted" in err


def test_write_succeeds_with_yes(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert "report:" in out
    assert "summary:" in out
    report_path = tmp_path / "runs" / "reports" / "20260510-090000.json"
    assert report_path.exists()
    saved = json.loads(report_path.read_text())
    # 1 epic + 1 story + 1 task = 3 creates, no comments/updates
    assert len(saved["plane_created"]) == 3


def test_write_resume_path_skips_confirmation(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path, completed=[0])
    # No `--yes`; resume must NOT prompt because state already exists.
    monkeypatch.setattr("builtins.input", lambda _msg: (_ for _ in ()).throw(
        AssertionError("input() should not be called on resume")
    ))
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert "Resuming run" in err


def test_write_partial_failure_exits_5(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)

    class FailingClient(_FakeClient):
        def create_work_item(self, project_id, payload):
            self.created += 1
            if self.created == 2:
                raise RuntimeError("503 boom")
            return {"id": f"wi-{self.created}", "sequence_id": 100 + self.created}

    monkeypatch.setattr(write_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(write_cli, "PlaneClient", lambda **kw: FailingClient())

    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--yes", "--on-failure", "abort",
    ])
    assert rc == 5
    assert "report:" in out
    saved = json.loads((tmp_path / "runs" / "reports" / "20260510-090000.json").read_text())
    assert saved["failed_op"] is not None
    assert saved["rolled_back"] is False


def test_write_rollback_exits_6(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)

    class FailingClient(_FakeClient):
        def create_work_item(self, project_id, payload):
            self.created += 1
            if self.created == 3:
                raise RuntimeError("boom")
            return {"id": f"wi-{self.created}", "sequence_id": 100 + self.created}

    monkeypatch.setattr(write_cli, "load_credentials", lambda: ("t", "https://h", "ws"))
    monkeypatch.setattr(write_cli, "PlaneClient", lambda **kw: FailingClient())

    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path),
        "--yes", "--on-failure", "rollback",
    ])
    assert rc == 6
    saved = json.loads((tmp_path / "runs" / "reports" / "20260510-090000.json").read_text())
    assert saved["rolled_back"] is True


def test_write_missing_workdir_files_exit_1(monkeypatch, tmp_path, capsys):
    bare = tmp_path / "empty"
    bare.mkdir()
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(bare), "--target-repo", str(tmp_path), "--yes",
    ])
    assert rc == 1
    assert "missing required file" in err


# ── Phase 6: dep_graph.json wiring ──

def _stage_dep_graph(work_dir: Path, edges: list[dict]) -> None:
    """Drop a dep_graph.json shaped like cli/run.py writes it."""
    payload = {
        "edges": [],
        "resolved_edges": edges,
        "unresolved_refs": [],
        "cycles": [],
        "topo_order": [],
        "original_order": [],
        "reordered": True,
        "epic_titles": [],
    }
    (work_dir / "dep_graph.json").write_text(json.dumps(payload, indent=2))


def test_write_loads_dep_graph_and_forwards_relations(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    edges = [
        {"src_ref_key": "epic:0", "dst_ref_key": "epic:1",
         "source": "depends_on", "raw_ref": "E0"},
        {"src_ref_key": "epic:0", "dst_ref_key": "epic:2",
         "source": "depends_on", "raw_ref": "E0"},
    ]
    _stage_dep_graph(work_dir, edges)

    captured: dict = {}
    real_execute = plane_writer.execute

    def spy_execute(*args, **kwargs):
        captured["dep_edges"] = kwargs.get("dep_edges")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(plane_writer, "execute", spy_execute)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert captured["dep_edges"] == edges


def test_write_no_plane_relations_flag_passes_empty_list(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    _stage_dep_graph(work_dir, [
        {"src_ref_key": "epic:0", "dst_ref_key": "epic:1",
         "source": "depends_on", "raw_ref": "E0"},
    ])

    captured: dict = {}
    real_execute = plane_writer.execute

    def spy_execute(*args, **kwargs):
        captured["dep_edges"] = kwargs.get("dep_edges")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(plane_writer, "execute", spy_execute)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--no-plane-relations",
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert captured["dep_edges"] == []


def test_write_summary_shows_relation_counts(monkeypatch, tmp_path, capsys):
    work_dir = _seed_workdir(tmp_path)
    rc, out, err = _run(monkeypatch, capsys, [
        "--work-dir", str(work_dir), "--target-repo", str(tmp_path), "--yes",
        "--client-factory", "tests.cli.test_write._fake_factory",
    ])
    assert rc == 0
    assert "relations_created=" in out
    assert "relations_skipped=" in out
