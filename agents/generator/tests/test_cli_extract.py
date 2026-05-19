"""Tests for `agents/generator/cli/extract.py` (Phase B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator.cli import extract


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.md"
_FIXTURE_DEPS = Path(__file__).resolve().parent / "fixtures" / "sample_epic_deps.md"


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    rc = extract.main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_happy_path_writes_extract_json(tmp_path, monkeypatch, capsys):
    work = tmp_path / "run1"
    rc, out, err = _run(monkeypatch, capsys, [str(_FIXTURE), "--work-dir", str(work)])
    assert rc == 0, err
    out_file = work / "extract.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    assert payload["source"].endswith("sample.md")
    assert payload["source_label"] == "sample"
    assert payload["root"]["heading"]["level"] == 0
    assert payload["root"]["children"][0]["heading"]["text"] == "Court Booking Spec"


def test_stdout_flag_prints_payload(tmp_path, capsys):
    rc = extract.main([str(_FIXTURE), "--work-dir", str(tmp_path), "--stdout"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Court Booking Spec" in captured.out


def test_missing_source_exits_1(tmp_path, capsys):
    rc = extract.main([str(tmp_path / "nope.md"), "--work-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "source not found" in captured.err


def test_non_markdown_source_exits_1(tmp_path, capsys):
    bogus = tmp_path / "spec.pdf"
    bogus.write_bytes(b"%PDF-1.4")
    rc = extract.main([str(bogus), "--work-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "only .md sources supported" in captured.err


def test_unwritable_work_dir_exits_1(tmp_path, capsys, monkeypatch):
    """If we can't create the work-dir at all, exit 1 (bad input)."""
    # Force mkdir to fail.
    def _raise(*_a, **_kw):
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr(Path, "mkdir", _raise)
    rc = extract.main([str(_FIXTURE), "--work-dir", str(tmp_path / "x")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot create work-dir" in captured.err


def test_write_failure_exits_2(tmp_path, capsys, monkeypatch):
    """If parse succeeds but write fails, exit 2."""
    original_write_text = Path.write_text

    def _raise_on_extract(self, *args, **kwargs):
        if self.name == "extract.json":
            raise OSError("disk full (simulated)")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _raise_on_extract)
    rc = extract.main([str(_FIXTURE), "--work-dir", str(tmp_path / "w")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "cannot write" in captured.err


def test_parse_failure_exits_2(tmp_path, capsys, monkeypatch):
    """Simulate a parser blow-up — exit 2."""
    import generator.parser.markdown as md_mod

    def _boom(_path):
        raise RuntimeError("synthetic parser failure")

    monkeypatch.setattr(md_mod, "parse_markdown", _boom)
    # Also patch the binding seen via the extract CLI's lazy import path.
    import sys
    if "generator.parser.markdown" in sys.modules:
        sys.modules["generator.parser.markdown"].parse_markdown = _boom

    rc = extract.main([str(_FIXTURE), "--work-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "parse failure" in captured.err


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        extract.build_parser().parse_args(["--help"])
    assert exc.value.code == 0


# ── epic_dependencies (mermaid graph in `## Epic dependencies` section) ───────


def test_epic_dependencies_emitted(tmp_path, capsys):
    """Source with `## Epic dependencies` + mermaid graph → extract.json
    carries an `epic_dependencies` array with one entry per edge."""
    work = tmp_path / "run-deps"
    rc = extract.main([str(_FIXTURE_DEPS), "--work-dir", str(work)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads((work / "extract.json").read_text())
    assert payload["epic_dependencies"] == [
        {"from": "Authentication", "to": "Court Booking"},
        {"from": "Court Booking", "to": "Cancellations"},
    ]


def test_no_dep_section_omits_field(tmp_path, capsys):
    """The original `sample.md` fixture has no `## Epic dependencies`
    section — `epic_dependencies` must be absent from extract.json (not
    written as an empty list)."""
    work = tmp_path / "run-no-deps"
    rc = extract.main([str(_FIXTURE), "--work-dir", str(work)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads((work / "extract.json").read_text())
    assert "epic_dependencies" not in payload


def test_dep_section_without_mermaid_omits_field(tmp_path, capsys):
    """`## Epic dependencies` section exists but contains no mermaid
    block (e.g. just prose) → field omitted (parser has nothing to
    extract)."""
    src = tmp_path / "no_mermaid.md"
    src.write_text(
        "# Demo\n\n## Epic dependencies\n\nNo mermaid graph here, just prose.\n"
    )
    work = tmp_path / "run-prose"
    rc = extract.main([str(src), "--work-dir", str(work)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads((work / "extract.json").read_text())
    assert "epic_dependencies" not in payload
