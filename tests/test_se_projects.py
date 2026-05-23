"""Unit tests for `se projects {list,show,members,states}`.

Same import pattern as `test_se_pages.py`: load `cli/se` via
`SourceFileLoader` (file has no `.py` extension) and patch the
`_load_module` / `_plane_get_json` boundaries so tests never touch
the real Plane API.

Coverage:
- list: argparse defaults, public-only filter, --include-private widens,
        --json shape, table layout, sort by identifier
- show: positional resolved via dpp.resolve_project, JSON pass-through,
        key/value table renders network label + truncated description
- members: list/dict response shapes, --json, role-desc sort
- states: list/dict response shapes, --json, natural pipeline sort
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_se():
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


def _ns(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace with cmd_projects_* defaults."""
    defaults = dict(
        project_id=None,
        include_private=False,
        json=False,
        plane_profile=None,
        plane_config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _projects() -> list[dict]:
    """Workspace projects mix: 2 public + 1 secret."""
    return [
        {"id": "p-capp-uuid", "identifier": "CAPP",
         "name": "Court Booking App", "network": 2},
        {"id": "p-stell-uuid", "identifier": "STELL",
         "name": "Stellar Sandbox", "network": 2},
        {"id": "p-secret-uuid", "identifier": "SECRET",
         "name": "Top Secret Project", "network": 0},
    ]


def _patch_dpp(se, monkeypatch, *, projects=None,
               project_uuid="p-capp-uuid", project_code="CAPP",
               workspace="demo-ws"):
    """Patch `_projects_load_dpp` to return a stub with the helpers
    cmd_projects_* depends on, plus apply env shim no-op."""
    fake = SimpleNamespace(
        load_config=lambda: {
            "workspace": workspace,
            "host": "https://api.example.com",
            "token": "tok",
        },
        list_projects=lambda _cfg: projects if projects is not None else _projects(),
        resolve_project=lambda _cfg, _ref: (project_uuid, project_code),
    )
    monkeypatch.setattr(se, "_projects_load_dpp", lambda: fake)


def _patch_get(se, monkeypatch, response):
    """Patch _plane_get_json so show/members/states get a deterministic
    payload without hitting the network."""
    monkeypatch.setattr(se, "_plane_get_json",
                        lambda _cfg, _path: response)


# ── _is_public_project / _network_label ──────────────────────────────────────


def test_is_public_project_explicit_public(se):
    assert se._is_public_project({"network": 2}) is True


def test_is_public_project_secret(se):
    assert se._is_public_project({"network": 0}) is False


def test_is_public_project_missing_field_treats_as_public(se):
    """Default-safe: older Plane schemas don't expose `network`."""
    assert se._is_public_project({}) is True


def test_network_label_known_values(se):
    assert se._network_label(0) == "secret"
    assert se._network_label(2) == "public"
    assert se._network_label(None) == "unknown"
    assert "1" in se._network_label(1)  # private (network=1)


# ── cmd_projects_list ────────────────────────────────────────────────────────


def test_list_table_default_public_only(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        se.cmd_projects_list(_ns())
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Workspace: demo-ws" in out
    assert "2 of 3 total" in out
    assert "1 private hidden" in out
    assert "CAPP" in out and "STELL" in out
    # Secret project filtered out
    assert "SECRET" not in out


def test_list_include_private_widens(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    with pytest.raises(SystemExit):
        se.cmd_projects_list(_ns(include_private=True))
    out = capsys.readouterr().out
    assert "3 of 3 total" in out
    assert "CAPP" in out and "STELL" in out and "SECRET" in out
    assert "(public + private — --include-private)" in out


def test_list_sorted_by_identifier(se, monkeypatch, capsys):
    """Sort by identifier so the table order is stable across API runs."""
    _patch_dpp(se, monkeypatch, projects=[
        {"id": "p1", "identifier": "ZULU", "name": "Z", "network": 2},
        {"id": "p2", "identifier": "ALPHA", "name": "A", "network": 2},
        {"id": "p3", "identifier": "MIKE", "name": "M", "network": 2},
    ])
    with pytest.raises(SystemExit):
        se.cmd_projects_list(_ns())
    out = capsys.readouterr().out
    alpha = out.find("ALPHA")
    mike = out.find("MIKE")
    zulu = out.find("ZULU")
    assert 0 < alpha < mike < zulu


def test_list_json_emits_array(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    with pytest.raises(SystemExit):
        se.cmd_projects_list(_ns(json=True))
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 2  # public only
    assert {p["identifier"] for p in data} == {"CAPP", "STELL"}
    assert all("network" in p for p in data)


def test_list_json_include_private_includes_secret_label(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    with pytest.raises(SystemExit):
        se.cmd_projects_list(_ns(include_private=True, json=True))
    data = json.loads(capsys.readouterr().out)
    secret = next(p for p in data if p["identifier"] == "SECRET")
    assert secret["network"] == "secret"


def test_list_empty_workspace(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch, projects=[])
    with pytest.raises(SystemExit):
        se.cmd_projects_list(_ns())
    out = capsys.readouterr().out
    assert "0 of 0 total" in out


# ── cmd_projects_show ────────────────────────────────────────────────────────


def test_show_renders_key_value_table(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    _patch_get(se, monkeypatch, {
        "id": "p-capp-uuid",
        "identifier": "CAPP",
        "name": "Court Booking App",
        "network": 2,
        "total_members": 7,
        "project_lead": "u-jane",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-05-23T00:00:00Z",
        "description": "Reservations for sport courts.",
    })
    with pytest.raises(SystemExit) as exc:
        se.cmd_projects_show(_ns(project_id="CAPP"))
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Identifier" in out and "CAPP" in out
    assert "Name" in out and "Court Booking App" in out
    assert "Network" in out and "public" in out
    assert "Total members" in out and "7" in out
    assert "Description" in out and "Reservations" in out


def test_show_long_description_truncated(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    long_desc = "A" * 500
    _patch_get(se, monkeypatch, {
        "id": "p-capp-uuid",
        "identifier": "CAPP",
        "name": "X",
        "network": 2,
        "description": long_desc,
    })
    with pytest.raises(SystemExit):
        se.cmd_projects_show(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    # 197 + ellipsis (1 char) = 198 visible chars cap on the value
    assert "…" in out
    assert "A" * 500 not in out


def test_show_json_pass_through(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    payload = {"id": "x", "identifier": "CAPP", "name": "C", "network": 2}
    _patch_get(se, monkeypatch, payload)
    with pytest.raises(SystemExit):
        se.cmd_projects_show(_ns(project_id="CAPP", json=True))
    assert json.loads(capsys.readouterr().out) == payload


def test_show_unknown_project_resolves_then_exits_1(se, monkeypatch, capsys):
    """If resolve_project raises SystemExit (unknown code), surface it."""
    fake = SimpleNamespace(
        load_config=lambda: {"workspace": "ws", "host": "h", "token": "t"},
        resolve_project=lambda _c, _r: (_ for _ in ()).throw(
            SystemExit("ERROR: no project with identifier 'NOPE'")
        ),
    )
    monkeypatch.setattr(se, "_projects_load_dpp", lambda: fake)
    with pytest.raises(SystemExit) as exc:
        se.cmd_projects_show(_ns(project_id="NOPE"))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "NOPE" in err


# ── cmd_projects_members ─────────────────────────────────────────────────────


def test_members_table_list_response(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    _patch_get(se, monkeypatch, [
        {"id": "m1", "role": 20, "member__display_name": "Jane Admin",
         "member__email": "jane@example.com"},
        {"id": "m2", "role": 15, "member__display_name": "Bob Member",
         "member__email": "bob@example.com"},
    ])
    with pytest.raises(SystemExit):
        se.cmd_projects_members(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "Project: CAPP" in out
    assert "Members: 2" in out
    assert "Jane Admin" in out and "Bob Member" in out
    # Admin (role 20) sorted before member (role 15)
    assert out.find("Jane Admin") < out.find("Bob Member")


def test_members_handles_results_envelope(se, monkeypatch, capsys):
    """Plane sometimes returns {results: [...], count: N}; handle both."""
    _patch_dpp(se, monkeypatch)
    _patch_get(se, monkeypatch, {
        "results": [{"id": "m1", "role": 15, "display_name": "Alice", "email": "a@x.com"}],
        "count": 1,
    })
    with pytest.raises(SystemExit):
        se.cmd_projects_members(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert "Members: 1" in out
    assert "Alice" in out


def test_members_json_array(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    members = [{"id": "m1", "role": 20}]
    _patch_get(se, monkeypatch, members)
    with pytest.raises(SystemExit):
        se.cmd_projects_members(_ns(project_id="CAPP", json=True))
    assert json.loads(capsys.readouterr().out) == members


# ── cmd_projects_states ──────────────────────────────────────────────────────


def test_states_table_pipeline_order(se, monkeypatch, capsys):
    """States sort by natural pipeline order: backlog → cancelled."""
    _patch_dpp(se, monkeypatch)
    _patch_get(se, monkeypatch, [
        {"id": "s1", "name": "Done", "group": "completed", "sequence": 1, "color": "#0f0"},
        {"id": "s2", "name": "Backlog", "group": "backlog", "sequence": 1, "color": "#888"},
        {"id": "s3", "name": "In Progress", "group": "started", "sequence": 1, "color": "#00f"},
        {"id": "s4", "name": "Cancelled", "group": "cancelled", "sequence": 1, "color": "#f00"},
        {"id": "s5", "name": "Todo", "group": "unstarted", "sequence": 1, "color": "#fff"},
    ])
    with pytest.raises(SystemExit):
        se.cmd_projects_states(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    backlog = out.find("Backlog")
    todo = out.find("Todo")
    progress = out.find("In Progress")
    done = out.find("Done")
    cancelled = out.find("Cancelled")
    assert 0 < backlog < todo < progress < done < cancelled


def test_states_unknown_group_sorts_last(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    _patch_get(se, monkeypatch, [
        {"id": "s1", "name": "Weird", "group": "mystery", "sequence": 1, "color": ""},
        {"id": "s2", "name": "Backlog", "group": "backlog", "sequence": 1, "color": ""},
    ])
    with pytest.raises(SystemExit):
        se.cmd_projects_states(_ns(project_id="CAPP"))
    out = capsys.readouterr().out
    assert out.find("Backlog") < out.find("Weird")


def test_states_json_array(se, monkeypatch, capsys):
    _patch_dpp(se, monkeypatch)
    states = [{"id": "s1", "name": "Backlog", "group": "backlog"}]
    _patch_get(se, monkeypatch, states)
    with pytest.raises(SystemExit):
        se.cmd_projects_states(_ns(project_id="CAPP", json=True))
    assert json.loads(capsys.readouterr().out) == states
