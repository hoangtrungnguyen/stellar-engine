"""Tests for the generator-related checks in `cli/se doctor` (Phase G).

`cli/se` is a script (no `.py` suffix), so we load it as a module via
`importlib.util.spec_from_file_location`. The tests then exercise the
private check helpers directly — fast and hermetic, no subprocess.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SE_PATH = _REPO_ROOT / "cli" / "se"
_MOD_NAME = "_se_doctor"


@pytest.fixture(scope="module")
def se():
    """Load `cli/se` as a Python module. The file has no .py suffix so we
    pass an explicit SourceFileLoader; we also register the module in
    sys.modules before exec so @dataclass can resolve its own module."""
    loader = SourceFileLoader(_MOD_NAME, str(_SE_PATH))
    spec = importlib.util.spec_from_loader(_MOD_NAME, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    try:
        loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(_MOD_NAME, None)


# ── _check_python_module ──────────────────────────────────────────────────────


def test_check_python_module_present(se):
    c = se._check_python_module("json")
    assert c.status == "ok"
    assert c.name == "python: json"


def test_check_python_module_missing_required_is_error(se):
    c = se._check_python_module("definitely_not_a_module_xyz_42")
    assert c.status == "error"


def test_check_python_module_missing_optional_is_warn(se):
    c = se._check_python_module(
        "definitely_not_a_module_xyz_42",
        required=False,
        note="deferred",
    )
    assert c.status == "warn"
    assert "deferred" in c.detail


# ── _check_env_file ───────────────────────────────────────────────────────────


def test_check_env_file_present(tmp_path, se):
    (tmp_path / ".env").write_text("X=1")
    c = se._check_env_file(tmp_path)
    assert c.status == "ok"


def test_check_env_file_missing_warns_with_example_hint(tmp_path, se):
    (tmp_path / ".env.example").write_text("X=1")
    c = se._check_env_file(tmp_path)
    assert c.status == "warn"
    assert ".env.example" in c.detail and ".env" in c.detail


def test_check_env_file_missing_without_example(tmp_path, se):
    c = se._check_env_file(tmp_path)
    assert c.status == "warn"
    assert "create from .env.example" in c.detail


# ── _check_generator ──────────────────────────────────────────────────────────


def _scaffold_generator_pkg(base: Path) -> None:
    pkg = base / "agents" / "generator"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")


def test_check_generator_missing_package_errors(tmp_path, se):
    checks = se._check_generator(tmp_path)
    assert len(checks) == 1
    assert checks[0].status == "error"
    assert "not found" in checks[0].detail


def test_check_generator_full_stack(tmp_path, se):
    _scaffold_generator_pkg(tmp_path)
    checks = se._check_generator(tmp_path)
    by_name = {c.name: c for c in checks}

    # Package check is OK.
    assert by_name["generator: package"].status == "ok"

    # Required deps surface as ok (real modules) or error (if absent at
    # the test runner). Both are valid — the test asserts the *check
    # ran*, not what the host machine has.
    assert by_name["python: markdown"].status in {"ok", "error"}
    assert by_name["python: markdownify"].status in {"ok", "error"}

    # Deferred deps: warn if absent, ok if present (operator may have
    # installed them anyway). Never error.
    assert by_name["python: anthropic"].status in {"ok", "warn"}
    if by_name["python: anthropic"].status == "warn":
        assert "Phase D" in by_name["python: anthropic"].detail
    assert by_name["python: pymupdf"].status in {"ok", "warn"}

    # drafts/ absent → warn, with helpful hint pointing at the generator
    # entry script (the old `se generate` wrapper was removed).
    drafts_check = by_name["generator: drafts/"]
    assert drafts_check.status == "warn"
    assert "agents/generator/cli/run.py" in drafts_check.detail


def test_check_generator_with_drafts_dir(tmp_path, se):
    _scaffold_generator_pkg(tmp_path)
    drafts = tmp_path / "drafts"
    (drafts / "demo" / "runs" / "RID-1").mkdir(parents=True)
    (drafts / "demo" / "runs" / "RID-2").mkdir(parents=True)

    checks = se._check_generator(tmp_path)
    by_name = {c.name: c for c in checks}
    dc = by_name["generator: drafts/"]
    assert dc.status == "ok"
    assert "2 run(s)" in dc.detail
