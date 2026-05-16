"""Tests for cli/qa_report.py — Phase 2 QA report generation."""
from __future__ import annotations

import json
import os
import sys

import pytest

import qa_report
from conftest import grava_show_payload


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["qa_report.py", *argv])
    try:
        rc = qa_report.main() or 0
    except SystemExit as exc:
        rc = int(exc.code or 0)
    out, err = capsys.readouterr()
    return rc, out, err


def _results_file(tmp_path, items: list[dict]) -> str:
    f = tmp_path / "results.json"
    f.write_text(json.dumps({"items": items}))
    return str(f)


_PASS = {"section": "Functional", "text": "Login works", "verdict": "PASS", "evidence": ""}
_FAIL = {"section": "Functional", "text": "Logout broken", "verdict": "FAIL", "evidence": "trace"}
_WARN = {"section": "Performance", "text": "Slow response", "verdict": "WARN", "evidence": "3s"}
_SKIP = {"section": "Security", "text": "SSL check", "verdict": "SKIP", "evidence": ""}


def _show(recorder, issue_id: str, title: str = "Feature") -> None:
    recorder.register("grava", "show", returncode=0,
                      stdout=grava_show_payload(issue_id=issue_id, title=title))


# ── verdict logic ─────────────────────────────────────────────────────────────


def test_pass_verdict(recorder, wisps, monkeypatch, capsys, tmp_path):
    """All PASS → verdict=pass, label qa-passed, exit 0."""
    _show(recorder, "QA-1", "Feature X")
    rc, out, _ = _run(monkeypatch, capsys, [
        "QA-1", "--results-file", _results_file(tmp_path, [_PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    payload = json.loads(out)
    assert payload["verdict"] == "pass"
    assert recorder.find_calls("grava", "label", "QA-1", "--add", "qa-passed")


def test_fail_verdict(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Any FAIL → verdict=fail, fail_count correct, label qa-failed, exit 0."""
    _show(recorder, "QA-2")
    rc, out, _ = _run(monkeypatch, capsys, [
        "QA-2", "--results-file", _results_file(tmp_path, [_FAIL, _PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    payload = json.loads(out)
    assert payload["verdict"] == "fail"
    assert payload["fail_count"] == 1
    assert recorder.find_calls("grava", "label", "QA-2", "--add", "qa-failed")


def test_warn_verdict(recorder, wisps, monkeypatch, capsys, tmp_path):
    """WARN but no FAIL → verdict=warn, label qa-failed, exit 0."""
    _show(recorder, "QA-3")
    rc, out, _ = _run(monkeypatch, capsys, [
        "QA-3", "--results-file", _results_file(tmp_path, [_WARN, _PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert json.loads(out)["verdict"] == "warn"
    assert recorder.find_calls("grava", "label", "QA-3", "--add", "qa-failed")


# ── input validation → exit 1 ─────────────────────────────────────────────────


def test_missing_results_file(recorder, wisps, monkeypatch, capsys, tmp_path):
    """--results-file path does not exist → exit 1."""
    rc, _, err = _run(monkeypatch, capsys, [
        "QA-4", "--results-file", str(tmp_path / "nonexistent.json"),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "cannot load" in err.lower()


def test_malformed_json(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Results file is invalid JSON → exit 1."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json{")
    rc, _, err = _run(monkeypatch, capsys, [
        "QA-5", "--results-file", str(bad), "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "cannot load" in err.lower()


def test_missing_items_key(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Results JSON has no 'items' key → exit 1."""
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"results": []}))
    rc, _, err = _run(monkeypatch, capsys, [
        "QA-6", "--results-file", str(f), "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "items" in err.lower()


def test_items_not_list(recorder, wisps, monkeypatch, capsys, tmp_path):
    """items is not a list → exit 1."""
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"items": "not-a-list"}))
    rc, _, err = _run(monkeypatch, capsys, [
        "QA-7", "--results-file", str(f), "--target-repo", str(tmp_path),
    ])
    assert rc == 1
    assert "items" in err.lower()


# ── write failure → exit 2 ────────────────────────────────────────────────────


def test_write_error(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Report file write fails (os.replace raises) → exit 2."""
    _show(recorder, "QA-8")

    def fake_replace(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fake_replace)
    rc, _, err = _run(monkeypatch, capsys, [
        "QA-8", "--results-file", _results_file(tmp_path, [_PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 2
    assert "cannot write" in err.lower()


# ── side-effects ──────────────────────────────────────────────────────────────


def test_grava_comment_failure_ignored(recorder, wisps, monkeypatch, capsys, tmp_path):
    """grava comment failure is best-effort and does not abort the pipeline → exit 0."""
    _show(recorder, "QA-9")
    recorder.register("grava", "comment", returncode=1, stderr="comment failed")
    rc, out, _ = _run(monkeypatch, capsys, [
        "QA-9", "--results-file", _results_file(tmp_path, [_PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert json.loads(out)["verdict"] == "pass"


def test_wisp_writes(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Happy path writes qa_verdict, qa_report_path, qa_fail_count, qa_blocking_items."""
    _show(recorder, "QA-10")
    rc, _, _ = _run(monkeypatch, capsys, [
        "QA-10", "--results-file", _results_file(tmp_path, [_FAIL, _PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    assert wisps.read("QA-10", "qa_verdict") == "fail"
    assert "qa/reports" in wisps.read("QA-10", "qa_report_path")
    assert wisps.read("QA-10", "qa_fail_count") == "1"
    blocking = json.loads(wisps.read("QA-10", "qa_blocking_items"))
    assert blocking == [_FAIL["text"]]


def test_grava_commit_called(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Happy path calls grava commit with issue ID in the message."""
    _show(recorder, "QA-11")
    rc, _, _ = _run(monkeypatch, capsys, [
        "QA-11", "--results-file", _results_file(tmp_path, [_PASS]),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    commit_calls = recorder.find_calls("grava", "commit")
    assert commit_calls
    assert "QA-11" in commit_calls[0][-1]


def test_truncation(recorder, wisps, monkeypatch, capsys, tmp_path):
    """Report larger than COMMENT_MAX chars → grava comment arg is truncated."""
    _show(recorder, "QA-12")
    many_items = [
        {
            "section": "Sec",
            "text": f"test item {i} " + "x" * 60,
            "verdict": "PASS",
            "evidence": "y" * 80,
        }
        for i in range(80)
    ]
    rc, _, _ = _run(monkeypatch, capsys, [
        "QA-12", "--results-file", _results_file(tmp_path, many_items),
        "--target-repo", str(tmp_path),
    ])
    assert rc == 0
    comment_calls = recorder.find_calls("grava", "comment", "QA-12")
    assert comment_calls
    # argv layout: ["grava", "comment", "QA-12", "-m", <text>]
    msg = comment_calls[0][4]
    assert "truncated" in msg
    assert len(msg) <= qa_report.COMMENT_MAX + 100
