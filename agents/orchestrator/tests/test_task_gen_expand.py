"""Tests for cli/task_gen_expand.py — bridge from grava epic to task-generator."""
from __future__ import annotations

import json
import sys

import pytest

import task_gen_expand
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["task_gen_expand.py", *argv])
    try:
        rc = task_gen_expand.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _epic_payload(issue_id: str = "epic-1", page_id: str = "page-abc") -> str:
    return grava_show_payload(
        issue_id=issue_id,
        issue_type="epic",
        labels=[f"tg:src:{page_id}"],
    )


def _register_taskgen(recorder, returncode: int = 0) -> None:
    recorder.register(sys.executable, returncode=returncode)


# ── dry-run (no approval gate) ───────────────────────────────────────────────


def test_dry_run_success(recorder, wisps, monkeypatch, capsys, tmp_path):
    """--dry-run skips approval and delegates to task-generator → exit 0."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload())
    wisps.write("epic-1", "plane_project_id", "uuid-123")
    _register_taskgen(recorder, returncode=0)
    rc, out, _ = _run(monkeypatch, capsys, [
        "epic-1", "--target-repo", str(tmp_path), "--dry-run",
    ])
    assert rc == 0
    payload = json.loads(out.splitlines()[-1])
    assert payload["epic_id"] == "epic-1"
    assert payload["page_id"] == "page-abc"
    assert payload["project_id"] == "uuid-123"
    assert payload["task_gen_exit_code"] == 0


# ── approval gate ─────────────────────────────────────────────────────────────


def test_approved_success(recorder, wisps, monkeypatch, capsys, tmp_path):
    """stdin 'yes' → approved, task-gen runs, exit 0."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-2"))
    wisps.write("epic-2", "plane_project_id", "uuid-456")
    _register_taskgen(recorder, returncode=0)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    rc, out, _ = _run(monkeypatch, capsys, [
        "epic-2", "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert json.loads(out.splitlines()[-1])["task_gen_exit_code"] == 0


def test_stdin_y_accepted(recorder, wisps, monkeypatch, capsys, tmp_path):
    """stdin 'y' also accepted → exit 0."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-3"))
    wisps.write("epic-3", "plane_project_id", "uuid-789")
    _register_taskgen(recorder, returncode=0)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    rc, _, _ = _run(monkeypatch, capsys, [
        "epic-3", "--target-repo", str(tmp_path),
    ])
    assert rc == 0


def test_declined_no(recorder, wisps, monkeypatch, capsys, tmp_path):
    """stdin 'no' → operator declined → exit 2."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-4"))
    wisps.write("epic-4", "plane_project_id", "uuid-dec")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    rc, _, err = _run(monkeypatch, capsys, [
        "epic-4", "--target-repo", str(tmp_path),
    ])
    assert rc == 2
    assert "declined" in err.lower()


def test_declined_n(recorder, wisps, monkeypatch, capsys, tmp_path):
    """stdin 'n' → operator declined → exit 2."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-5"))
    wisps.write("epic-5", "plane_project_id", "uuid-dec2")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    rc, _, _ = _run(monkeypatch, capsys, [
        "epic-5", "--target-repo", str(tmp_path),
    ])
    assert rc == 2


def test_eof_on_prompt(recorder, wisps, monkeypatch, capsys, tmp_path):
    """EOFError during approval prompt treated as decline → exit 2."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-6"))
    wisps.write("epic-6", "plane_project_id", "uuid-eof")

    def raise_eof(_prompt):
        raise EOFError()

    monkeypatch.setattr("builtins.input", raise_eof)
    rc, _, _ = _run(monkeypatch, capsys, [
        "epic-6", "--target-repo", str(tmp_path),
    ])
    assert rc == 2


# ── page_id / project_id resolution errors → exit 1 ──────────────────────────


def test_grava_show_failure(recorder, wisps, monkeypatch, capsys, tmp_path):
    """grava show returns non-zero → exit 1."""
    recorder.register("grava", "show", returncode=1, stderr="not found")
    rc, _, err = _run(monkeypatch, capsys, [
        "epic-missing", "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "not found" in err.lower()


def test_bad_json_from_grava(recorder, wisps, monkeypatch, capsys, tmp_path):
    """grava show returns invalid JSON → exit 1."""
    recorder.register("grava", "show", returncode=0, stdout="not-json{")
    rc, _, err = _run(monkeypatch, capsys, [
        "epic-bad", "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "bad json" in err.lower()


def test_no_tg_src_label(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Epic has no tg:src:<page_id> label → exit 1."""
    recorder.register("grava", "show", returncode=0, stdout=grava_show_payload(
        issue_id="epic-nolabel", issue_type="epic", labels=["some-other-label"],
    ))
    rc, _, err = _run(monkeypatch, capsys, [
        "epic-nolabel", "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "tg:src" in err


def test_no_project_id(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Wisp empty + repo-map lookup returns '' → exit 1."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-nopid"))
    monkeypatch.setattr(task_gen_expand, "resolve_project_id_from_map",
                        lambda _cwd, _root: "")
    rc, _, err = _run(monkeypatch, capsys, [
        "epic-nopid", "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "project_id" in err.lower()


# ── project_id resolution happy paths ────────────────────────────────────────


def test_project_id_from_wisp(recorder, wisps, monkeypatch, capsys, tmp_path):
    """project_id resolved from wisp → used in output, exit 0."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-wisp"))
    wisps.write("epic-wisp", "plane_project_id", "uuid-from-wisp")
    _register_taskgen(recorder, returncode=0)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    rc, out, _ = _run(monkeypatch, capsys, [
        "epic-wisp", "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert json.loads(out.splitlines()[-1])["project_id"] == "uuid-from-wisp"


def test_project_id_from_repo_map(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Wisp empty; project_id resolved via resolve_project_id_from_map → exit 0."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload("epic-map"))
    monkeypatch.setattr(task_gen_expand, "resolve_project_id_from_map",
                        lambda _cwd, _root: "uuid-from-map")
    _register_taskgen(recorder, returncode=0)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    rc, out, _ = _run(monkeypatch, capsys, [
        "epic-map", "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert json.loads(out.splitlines()[-1])["project_id"] == "uuid-from-map"


# ── task-generator exit code passthrough ─────────────────────────────────────


@pytest.mark.parametrize("tg_exit", [5, 6, 7])
def test_passthrough_exit(tg_exit, recorder, wisps, monkeypatch, capsys, tmp_path):
    """task-generator exit codes 5/6/7 pass through unchanged."""
    recorder.register("grava", "show", returncode=0, stdout=_epic_payload(f"epic-pt{tg_exit}"))
    wisps.write(f"epic-pt{tg_exit}", "plane_project_id", "uuid-pt")
    _register_taskgen(recorder, returncode=tg_exit)
    rc, _, _ = _run(monkeypatch, capsys, [
        f"epic-pt{tg_exit}", "--target-repo", str(tmp_path), "--dry-run",
    ])
    assert rc == tg_exit
