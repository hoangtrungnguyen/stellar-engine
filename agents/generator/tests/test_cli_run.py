"""Tests for `agents/generator/cli/run.py` (Phase E3 orchestrator)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator.cli import run as run_cli


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_SAMPLE_MD = _FIXTURE_DIR / "sample.md"
_SAMPLE_OUTLINE = _FIXTURE_DIR / "sample_outline.json"


# ── helpers ───────────────────────────────────────────────────────────────────


def _drop_outline(work_dir: Path) -> None:
    """Simulate the operator hand-placing outline.json from a Claude session."""
    (work_dir / "outline.json").write_text(_SAMPLE_OUTLINE.read_text())


def _common_args(drafts_root: Path, *extra: str, run_id: str = "RID-1") -> list[str]:
    return [
        str(_SAMPLE_MD),
        "--project", "demo",
        "--drafts-root", str(drafts_root),
        "--run-id", run_id,
        *extra,
    ]


# ── argument / source validation ──────────────────────────────────────────────


def test_missing_source_exits_1(tmp_path, capsys):
    rc = run_cli.main([
        str(tmp_path / "nope.md"),
        "--project", "demo",
        "--drafts-root", str(tmp_path),
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "source not found" in captured.err


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        run_cli.build_parser().parse_args(["--help"])
    assert exc.value.code == 0


# ── early-stop modes (--dry-run / --no-llm / --step extract) ──────────────────


def test_dry_run_stops_after_extract(tmp_path, capsys):
    rc = run_cli.main(_common_args(tmp_path, "--dry-run"))
    assert rc == 0
    work = tmp_path / "demo" / "runs" / "RID-1"
    assert (work / "extract.json").exists()
    assert not (work / "drafts").exists()
    assert "stopped after extract" in capsys.readouterr().out


def test_no_llm_stops_after_extract(tmp_path, capsys):
    rc = run_cli.main(_common_args(tmp_path, "--no-llm"))
    assert rc == 0
    work = tmp_path / "demo" / "runs" / "RID-1"
    assert (work / "extract.json").exists()
    assert not (work / "drafts").exists()


def test_step_extract_only(tmp_path, capsys):
    rc = run_cli.main(_common_args(tmp_path, "--step", "extract"))
    assert rc == 0
    work = tmp_path / "demo" / "runs" / "RID-1"
    assert (work / "extract.json").exists()
    assert not (work / "drafts").exists()


def test_step_outline_no_op(tmp_path, capsys):
    rc = run_cli.main(_common_args(tmp_path, "--step", "outline"))
    captured = capsys.readouterr()
    assert rc == 0
    assert "no-op" in captured.out


# ── --llm currently refuses (Phase D deferred) ────────────────────────────────


def test_llm_flag_refused_with_helpful_message(tmp_path, capsys):
    rc = run_cli.main(_common_args(tmp_path, "--llm"))
    captured = capsys.readouterr()
    assert rc == 1
    assert "Phase D" in captured.err
    assert "deferred" in captured.err.lower()


# ── full chain with hand-placed outline.json (Phase D interim workflow) ───────


def test_chain_without_outline_exits_1(tmp_path, capsys):
    """Default offline chain stops with helpful message if outline.json missing."""
    rc = run_cli.main(_common_args(tmp_path))
    captured = capsys.readouterr()
    assert rc == 1
    assert "no outline.json present" in captured.err
    work = tmp_path / "demo" / "runs" / "RID-1"
    assert (work / "extract.json").exists()  # extract ran


def test_chain_full_render_when_outline_present(tmp_path, monkeypatch):
    """Operator-supplied outline.json → render runs."""
    work = tmp_path / "demo" / "runs" / "RID-1"
    work.mkdir(parents=True, exist_ok=True)
    # Pre-seed run.json + outline (init_run will see existing dir).
    _drop_outline(work)
    rc = run_cli.main(_common_args(tmp_path, "--system-name", "Demo"))
    assert rc == 0
    drafts = list((work / "drafts").glob("*.md"))
    assert len(drafts) == 2
    assert (work / "manifest.json").exists()


def test_step_render_only(tmp_path):
    """`--step render` skips extract — outline.json must already be present."""
    work = tmp_path / "demo" / "runs" / "RID-1"
    work.mkdir(parents=True, exist_ok=True)
    _drop_outline(work)
    rc = run_cli.main(_common_args(tmp_path, "--step", "render"))
    assert rc == 0
    assert list((work / "drafts").glob("*.md"))


# ── diff vs previous run ──────────────────────────────────────────────────────


def test_diff_emitted_on_second_run(tmp_path, capsys):
    # First run: pre-create RID-1 with extract + hand-placed outline.
    work1 = tmp_path / "demo" / "runs" / "RID-1"
    work1.mkdir(parents=True, exist_ok=True)
    (work1 / "run.json").write_text(json.dumps({
        "run_id": "RID-1", "project": "demo",
        "source": str(_SAMPLE_MD), "started_at": "x",
    }))
    _drop_outline(work1)

    # Modify outline for run 2: drop one epic, rename the other.
    modified = json.loads(_SAMPLE_OUTLINE.read_text())
    modified["epics"] = modified["epics"][:1]   # drop "Cancellations"
    modified["epics"][0]["title"] = "Court Bookings"   # rename Court Booking → Court Bookings
    work2 = tmp_path / "demo" / "runs" / "RID-2"
    work2.mkdir(parents=True, exist_ok=True)
    (work2 / "outline.json").write_text(json.dumps(modified))

    rc = run_cli.main([
        str(_SAMPLE_MD),
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID-2",
        "--system-name", "Demo",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Diff vs run RID-1" in out
    # Rename or removal must surface in the printed diff text.
    diff_file = work2 / "diff.json"
    assert diff_file.exists()
    diff_data = json.loads(diff_file.read_text())
    # Either renamed-pair or added/removed-pair is acceptable; both signal change.
    assert (diff_data["epics_renamed"]
            or (diff_data["epics_added"] and diff_data["epics_removed"]))


def test_no_diff_when_no_previous_run(tmp_path, capsys):
    work = tmp_path / "demo" / "runs" / "RID-1"
    work.mkdir(parents=True, exist_ok=True)
    _drop_outline(work)

    rc = run_cli.main(_common_args(tmp_path, "--system-name", "Demo"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Diff vs run" not in out
    assert not (work / "diff.json").exists()


def test_previous_run_without_outline_is_skipped(tmp_path, capsys):
    """A prior `--dry-run` / `--no-llm` run leaves a run.json but no
    outline.json. The diff lookup must skip it silently — no WARN — and
    fall back to "no previous run" rather than tripping over the missing
    outline.json."""
    # RID-prev: a dry-run leftover — run.json present, outline.json absent.
    prev = tmp_path / "demo" / "runs" / "RID-prev"
    prev.mkdir(parents=True, exist_ok=True)
    (prev / "run.json").write_text(json.dumps({
        "run_id": "RID-prev", "project": "demo",
        "source": str(_SAMPLE_MD), "started_at": "x",
    }))

    # Current run: outline.json hand-placed; render should proceed without
    # any diff line and without warning about the prev run.
    work = tmp_path / "demo" / "runs" / "RID-curr"
    work.mkdir(parents=True, exist_ok=True)
    _drop_outline(work)

    rc = run_cli.main([
        str(_SAMPLE_MD),
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID-curr",
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" not in captured.err
    assert "Diff vs run" not in captured.out
    assert not (work / "diff.json").exists()


def test_diff_walks_back_past_dry_run_to_rendered_run(tmp_path, capsys):
    """When a dry-run sits between two fully-rendered runs, the diff
    must compare against the older rendered run, not the dry-run."""
    # RID-1: fully rendered.
    work1 = tmp_path / "demo" / "runs" / "RID-1"
    work1.mkdir(parents=True, exist_ok=True)
    (work1 / "run.json").write_text(json.dumps({
        "run_id": "RID-1", "project": "demo",
        "source": str(_SAMPLE_MD), "started_at": "x",
    }))
    _drop_outline(work1)

    # RID-2: dry-run leftover (run.json only).
    work2 = tmp_path / "demo" / "runs" / "RID-2"
    work2.mkdir(parents=True, exist_ok=True)
    (work2 / "run.json").write_text(json.dumps({
        "run_id": "RID-2", "project": "demo",
        "source": str(_SAMPLE_MD), "started_at": "x",
    }))

    # RID-3: current run with a modified outline.
    modified = json.loads(_SAMPLE_OUTLINE.read_text())
    modified["epics"] = modified["epics"][:1]   # drop one epic
    work3 = tmp_path / "demo" / "runs" / "RID-3"
    work3.mkdir(parents=True, exist_ok=True)
    (work3 / "outline.json").write_text(json.dumps(modified))

    rc = run_cli.main([
        str(_SAMPLE_MD),
        "--project", "demo",
        "--drafts-root", str(tmp_path),
        "--run-id", "RID-3",
        "--system-name", "Demo",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Diff vs run RID-1" in captured.out   # not RID-2
    assert "WARN" not in captured.err
