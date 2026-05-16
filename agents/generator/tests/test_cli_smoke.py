"""Smoke tests for CLI argparse contracts.

Every CLI script must:
  - expose `build_parser()` (argparse) and `main(argv)` callable
  - accept `--help` and exit 0

Scripts still in scaffold state additionally print "phase A scaffold" on
happy-path invocation. Scripts that have a real implementation (Phase B+)
are excluded from the scaffold-happy-path parametrize set and tested in
their own `test_cli_<name>.py`.
"""

from __future__ import annotations

import pytest

from generator.cli import extract, init_run, outline, render, run


# All scripts (for --help contract).
ALL_SCRIPTS = [
    ("init_run", init_run, ["--project", "demo"]),
    ("extract", extract, ["src.md", "--work-dir", "/tmp/x"]),
    ("outline", outline, ["--work-dir", "/tmp/x"]),
    ("render", render, ["--work-dir", "/tmp/x", "--system-name", "Demo"]),
    ("run", run, ["src.md", "--project", "demo"]),
]

# Scripts still in scaffold state (Phase D outline is deferred).
SCAFFOLD_SCRIPTS = [s for s in ALL_SCRIPTS if s[0] == "outline"]


@pytest.mark.parametrize("name,mod,argv", ALL_SCRIPTS, ids=[s[0] for s in ALL_SCRIPTS])
def test_help_exits_zero(name, mod, argv, capsys):
    with pytest.raises(SystemExit) as exc:
        mod.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


@pytest.mark.parametrize("name,mod,argv", SCAFFOLD_SCRIPTS,
                         ids=[s[0] for s in SCAFFOLD_SCRIPTS])
def test_happy_path_prints_scaffold(name, mod, argv, capsys):
    rc = mod.main(argv)
    assert rc == 0
    out = capsys.readouterr().out
    assert "phase A scaffold" in out


def test_run_mutually_exclusive_modes():
    """--llm / --no-llm / --dry-run are mutually exclusive."""
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(
            ["src.md", "--project", "demo", "--llm", "--no-llm"]
        )


def test_run_step_choices():
    """--step accepts only extract|outline|render."""
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(
            ["src.md", "--project", "demo", "--step", "bogus"]
        )
    # valid choice parses
    args = run.build_parser().parse_args(
        ["src.md", "--project", "demo", "--step", "extract"]
    )
    assert args.step == "extract"
