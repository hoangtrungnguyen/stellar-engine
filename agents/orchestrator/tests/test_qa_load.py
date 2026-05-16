"""Tests for cli/qa_load.py — Phase 0 QA checklist resolution."""
from __future__ import annotations

import json
import os
import sys

import pytest

import qa_load
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["qa_load.py", *argv])
    try:
        rc = qa_load.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _no_stellar_root(_):
    raise FileNotFoundError("no root")


# ── happy-path resolution ─────────────────────────────────────────────────────


def test_explicit_checklist(recorder, wisps, monkeypatch, capsys, tmp_path):
    """--checklist <existing file> → source=explicit, exit 0."""
    checklist = tmp_path / "check.md"
    checklist.write_text("# Checklist\n- [ ] item\n")
    out_path = tmp_path / ".grava" / "qa-T1-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T1", "--target-repo", str(tmp_path),
        "--checklist", str(checklist),
        "--out", str(out_path),
    ])
    assert rc == 0
    payload = json.loads(out)
    assert payload["source"] == "explicit"
    assert payload["id"] == "T1"
    assert out_path.exists()


def test_type_template_cli(recorder, wisps, monkeypatch, capsys, tmp_path):
    """--type cli resolves bundled cli-checklist.md → source=type:cli, exit 0."""
    out_path = tmp_path / ".grava" / "qa-T2-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T2", "--target-repo", str(tmp_path),
        "--type", "cli",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out)["source"] == "type:cli"


def test_type_template_mobile(recorder, wisps, monkeypatch, capsys, tmp_path):
    """--type mobile resolves bundled mobile-checklist.md → source=type:mobile, exit 0."""
    out_path = tmp_path / ".grava" / "qa-T3-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T3", "--target-repo", str(tmp_path),
        "--type", "mobile",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out)["source"] == "type:mobile"


def test_wisp_fallback(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Wisp qa_checklist points to existing file → source=wisp, exit 0."""
    checklist = tmp_path / "wisp-check.md"
    checklist.write_text("# Wisp Checklist\n")
    wisps.write("T4", "qa_checklist", str(checklist))
    monkeypatch.setattr(qa_load, "find_stellar_root", _no_stellar_root)
    out_path = tmp_path / ".grava" / "qa-T4-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T4", "--target-repo", str(tmp_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out)["source"] == "wisp"


def test_repo_default_fallback(recorder, wisps, monkeypatch, capsys, tmp_path):
    """docs/qa/default-checklist.md in target-repo → source=repo-default, exit 0."""
    repo_default = tmp_path / "docs" / "qa" / "default-checklist.md"
    repo_default.parent.mkdir(parents=True)
    repo_default.write_text("# Repo Default\n")
    monkeypatch.setattr(qa_load, "find_stellar_root", _no_stellar_root)
    out_path = tmp_path / ".grava" / "qa-T5-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T5", "--target-repo", str(tmp_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out)["source"] == "repo-default"


def test_bundled_default_fallback(recorder, wisps, monkeypatch, capsys, tmp_path):
    """No other source → bundled default-checklist.md → source=bundled-default, exit 0."""
    out_path = tmp_path / ".grava" / "qa-T6-checklist.md"
    rc, out, _ = _run(monkeypatch, capsys, [
        "T6", "--target-repo", str(tmp_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert json.loads(out)["source"] == "bundled-default"


# ── failure paths ─────────────────────────────────────────────────────────────


def test_no_checklist_found(recorder, wisps, monkeypatch, capsys, tmp_path):
    """All 5 resolution paths fail → exit 1."""
    monkeypatch.setattr(qa_load, "find_stellar_root", _no_stellar_root)
    out_path = tmp_path / ".grava" / "qa-T7-checklist.md"
    rc, _, err = _run(monkeypatch, capsys, [
        "T7", "--target-repo", str(tmp_path),
        "--out", str(out_path),
    ])
    assert rc == 1
    assert "no checklist" in err.lower()


def test_write_error(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Checklist resolved but atomic write fails (os.replace raises) → exit 2."""
    checklist = tmp_path / "check.md"
    checklist.write_text("# Checklist\n")
    out_path = tmp_path / ".grava" / "qa-T8-checklist.md"

    def fake_replace(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fake_replace)
    rc, _, err = _run(monkeypatch, capsys, [
        "T8", "--target-repo", str(tmp_path),
        "--checklist", str(checklist),
        "--out", str(out_path),
    ])
    assert rc == 2
    assert "cannot write" in err.lower()


# ── side-effects ──────────────────────────────────────────────────────────────


def test_wisp_write_called(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Happy path writes qa_checklist wisp with resolved path."""
    checklist = tmp_path / "check.md"
    checklist.write_text("# Checklist\n")
    out_path = tmp_path / ".grava" / "qa-T9-checklist.md"
    rc, _, _ = _run(monkeypatch, capsys, [
        "T9", "--target-repo", str(tmp_path),
        "--checklist", str(checklist),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert wisps.read("T9", "qa_checklist") == str(checklist)


def test_out_default_path(recorder, wisps, monkeypatch, capsys, tmp_path):
    """No --out → output file placed at <target-repo>/.grava/qa-<id>-checklist.md."""
    checklist = tmp_path / "check.md"
    checklist.write_text("# Checklist\n")
    rc, out, _ = _run(monkeypatch, capsys, [
        "T10", "--target-repo", str(tmp_path),
        "--checklist", str(checklist),
    ])
    assert rc == 0
    payload = json.loads(out)
    expected = os.path.join(str(tmp_path), ".grava", "qa-T10-checklist.md")
    assert payload["out"] == expected
