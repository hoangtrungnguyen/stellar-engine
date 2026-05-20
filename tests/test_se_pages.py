"""Unit tests for `se pages` (cmd_pages in cli/se).

Loads `cli/se` as a Python module via `spec_from_file_location` — the
file has no `.py` suffix but argparse / typing are all stdlib so
nothing else is needed. Patches the `_load_module` boundary so the
tests never touch the real `download_project_pages.py` script (which
in turn never touches the Plane API).

Coverage:
- Missing project arg → exit 2 with usage hint
- Positional vs --project both work + are interchangeable
- Table output: header, columns, count line, sort by name
- JSON output (`--json`): array of {id, name, access}
- Public-only default filters out private pages
- `--include-private` widens the listing
- Access rendering: 0→public, 1→private, missing→unknown
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_se():
    """Load `cli/se` as a Python module so its functions are callable
    in-process.

    The file has no `.py` suffix, so `spec_from_file_location` can't
    auto-pick a loader — pass an explicit `SourceFileLoader`. Cached
    under a `_cli_se_module` sys.modules key so repeated calls in the
    same test session reuse the import."""
    import importlib.machinery
    se_path = _REPO_ROOT / "cli" / "se"
    spec = importlib.util.spec_from_file_location(
        "_cli_se_module",
        se_path,
        loader=importlib.machinery.SourceFileLoader("_cli_se_module", str(se_path)),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cli_se_module"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def se():
    return _import_se()


def _mk_pages(specs: list[tuple[str, str, int | None]]) -> list[dict]:
    """Build a list of {id, name, access} dicts. `access=None` simulates
    an older Plane schema that omitted the field entirely."""
    return [{"id": pid, "name": name, "access": access}
            for pid, name, access in specs]


def _patch_dpp(se, monkeypatch, *, pages, project_uuid="11111111-1111-1111-1111-111111111111",
               project_code="CAPP", workspace="demo-ws"):
    """Stub `_load_module('download_project_pages', …)` so cmd_pages
    pulls in a fake helper module instead of the real script.

    The stub mirrors the four functions cmd_pages depends on:
    `load_config`, `resolve_project`, `list_pages`, `is_public_page`.
    """
    fake = SimpleNamespace(
        load_config=lambda: {"workspace": workspace, "host": "https://api.example.com",
                              "token": "tok"},
        resolve_project=lambda _cfg, _ref: (project_uuid, project_code),
        list_pages=lambda _cfg, _proj: pages,
        is_public_page=lambda p: p.get("access") in (0, None),
    )
    monkeypatch.setattr(se, "_load_module", lambda _name, _path: fake)
    monkeypatch.setattr(se, "_repo_root", lambda: _REPO_ROOT)


def _ns(**overrides) -> argparse.Namespace:
    """argparse.Namespace builder with the defaults cmd_pages expects."""
    defaults = dict(
        project_id=None,
        project=None,
        include_private=False,
        json=False,
        plane_profile=None,
        plane_config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── argument validation ──────────────────────────────────────────────────────


def test_no_project_arg_exits_2_with_hint(se, capsys):
    with pytest.raises(SystemExit) as exc:
        se.cmd_pages(_ns())
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "pass a project" in err
    assert "se pages CAPP" in err


def test_positional_project_id_works(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Architecture", 0)]))
    with pytest.raises(SystemExit) as exc:
        se.cmd_pages(_ns(project_id="CAPP"))
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Architecture" in out


def test_flag_project_works(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Architecture", 0)]))
    with pytest.raises(SystemExit) as exc:
        se.cmd_pages(_ns(project="CAPP"))
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Architecture" in out


def test_positional_takes_precedence_over_flag(se, monkeypatch, capsys):
    """If both are passed (operator made a mistake), positional wins —
    matches what `args.project_id or args.project` evaluates."""
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Architecture", 0)]))
    with pytest.raises(SystemExit) as exc:
        se.cmd_pages(_ns(project_id="CAPP", project="STELL"))
    assert exc.value.code == 0


# ── table output ─────────────────────────────────────────────────────────────


def test_table_headers_and_columns(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("page-abc12345", "Architecture", 0),
        ("page-def67890", "Roadmap", 0),
    ]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "ID" in out and "NAME" in out and "ACCESS" in out
    assert "page-abc12345" in out and "Architecture" in out
    assert "page-def67890" in out and "Roadmap" in out
    # Header line + separator line + 2 rows + header lines
    assert out.count("\n") >= 5


def test_table_sorted_by_name_case_insensitive(se, monkeypatch, capsys):
    """Sort by name (case-insensitive) — gives operator a predictable
    scroll order regardless of how pages were created."""
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("p1", "zebra", 0),
        ("p2", "Apple", 0),
        ("p3", "mango", 0),
    ]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    apple_pos = out.find("Apple")
    mango_pos = out.find("mango")
    zebra_pos = out.find("zebra")
    assert 0 < apple_pos < mango_pos < zebra_pos


def test_table_header_metadata(se, monkeypatch, capsys):
    """Top-of-table lines surface project code + UUID + workspace +
    counts — useful when piping into a shared chat."""
    _patch_dpp(
        se, monkeypatch,
        pages=_mk_pages([("p1", "Architecture", 0)]),
        project_uuid="11111111-1111-1111-1111-111111111111",
        project_code="CAPP",
        workspace="demo-ws",
    )
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "Project: CAPP" in out
    assert "11111111-1111-1111-1111-111111111111" in out
    assert "workspace=demo-ws" in out
    assert "1 of 1 total" in out
    assert "(public only)" in out


# ── access rendering ─────────────────────────────────────────────────────────


def test_access_0_renders_public(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Foo", 0)]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "public" in out


def test_access_1_renders_private_when_included(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Foo", 1)]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP", include_private=True))
    out = capsys.readouterr().out
    assert "private" in out


def test_access_missing_renders_unknown(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Foo", None)]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "unknown" in out


# ── public-only default + --include-private ─────────────────────────────────


def test_public_only_default_hides_private(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("p1", "Public Page", 0),
        ("p2", "Secret Plan", 1),
    ]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "Public Page" in out
    assert "Secret Plan" not in out
    assert "1 of 2 total" in out
    assert "1 private hidden" in out


def test_include_private_widens(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("p1", "Public Page", 0),
        ("p2", "Secret Plan", 1),
    ]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP", include_private=True))
    out = capsys.readouterr().out
    assert "Public Page" in out
    assert "Secret Plan" in out
    assert "2 of 2 total" in out
    assert "--include-private" in out


# ── JSON output ──────────────────────────────────────────────────────────────


def test_json_output_emits_valid_array(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("p1", "Architecture", 0),
        ("p2", "Roadmap", 0),
    ]))
    with pytest.raises(SystemExit) as exc:
        se.cmd_pages(_ns(project_id="CAPP", json=True))
    assert exc.value.code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 2
    assert set(data[0].keys()) == {"id", "name", "access"}
    # Sorted by name → Architecture before Roadmap
    assert data[0]["name"] == "Architecture"
    assert data[0]["access"] == "public"
    assert data[1]["name"] == "Roadmap"


def test_json_output_includes_access_unknown(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([("p1", "Foo", None)]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP", json=True))
    data = json.loads(capsys.readouterr().out)
    assert data[0]["access"] == "unknown"


def test_json_empty_array_when_all_filtered(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, pages=_mk_pages([
        ("p1", "Private 1", 1),
        ("p2", "Private 2", 1),
    ]))
    with pytest.raises(SystemExit):
        se.cmd_pages(_ns(project_id="CAPP", json=True))
    data = json.loads(capsys.readouterr().out)
    assert data == []
