"""Unit tests for download_project_pages.py — project resolution +
single-page download path.

End-to-end coverage of the network paths is intentionally avoided here;
those run against the Plane sandbox via the smoke tests documented in
docs/install.md. These tests pin the pure logic so future refactors
don't silently break the `CAPP → UUID` resolution that
`agents/generator/cli/run.py --plane-project CAPP` depends on.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_dpp():
    """Load download_project_pages.py as a module (the file lives at
    repo root, not inside a package)."""
    spec = importlib.util.spec_from_file_location(
        "download_project_pages",
        _REPO_ROOT / "download_project_pages.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["download_project_pages"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dpp():
    return _import_dpp()


@pytest.fixture
def cfg():
    return {
        "token": "tok",
        "host": "https://api.example.com",
        "workspace": "demo-ws",
    }


def _projects() -> list[dict]:
    return [
        {"id": "11111111-1111-1111-1111-111111111111", "identifier": "CAPP",
         "name": "Court Booking App"},
        {"id": "22222222-2222-2222-2222-222222222222", "identifier": "STELL",
         "name": "Stellar Sandbox"},
    ]


# ── resolve_project ───────────────────────────────────────────────────────────


def test_resolve_uuid_passthrough_returns_identifier_for_folder(monkeypatch, dpp, cfg):
    """Given a UUID, the resolver returns (uuid, identifier) so the
    output folder can use the short code instead of the UUID string."""
    monkeypatch.setattr(dpp, "list_projects", lambda c: _projects())
    uuid, code = dpp.resolve_project(cfg, "11111111-1111-1111-1111-111111111111")
    assert uuid == "11111111-1111-1111-1111-111111111111"
    assert code == "CAPP"


def test_resolve_uuid_not_in_workspace_passes_through(monkeypatch, dpp, cfg):
    """If the UUID isn't in the workspace listing we still let the
    caller try — the API will 404 if it's truly invalid, but the script
    should not block on a stale local listing."""
    monkeypatch.setattr(dpp, "list_projects", lambda c: _projects())
    uuid, code = dpp.resolve_project(cfg, "99999999-9999-9999-9999-999999999999")
    assert uuid == "99999999-9999-9999-9999-999999999999"
    assert code == "99999999-9999-9999-9999-999999999999"


def test_resolve_identifier_to_uuid(monkeypatch, dpp, cfg):
    monkeypatch.setattr(dpp, "list_projects", lambda c: _projects())
    uuid, code = dpp.resolve_project(cfg, "CAPP")
    assert uuid == "11111111-1111-1111-1111-111111111111"
    assert code == "CAPP"


def test_resolve_identifier_case_insensitive(monkeypatch, dpp, cfg):
    monkeypatch.setattr(dpp, "list_projects", lambda c: _projects())
    uuid, code = dpp.resolve_project(cfg, "capp")
    assert uuid == "11111111-1111-1111-1111-111111111111"
    # The canonical (upper-case) form is preserved on the way out so
    # the on-disk folder stays consistent regardless of how the user
    # typed the code.
    assert code == "CAPP"


def test_resolve_unknown_identifier_raises(monkeypatch, dpp, cfg):
    monkeypatch.setattr(dpp, "list_projects", lambda c: _projects())
    with pytest.raises(SystemExit) as exc:
        dpp.resolve_project(cfg, "NOPE")
    assert "NOPE" in str(exc.value)


def test_resolve_falls_back_when_listing_unreachable(monkeypatch, dpp, cfg):
    """If `list_projects` fails (HTTPError), the resolver returns the
    input verbatim for both fields so the caller can attempt the API
    call without the script crashing before it has a chance."""
    import requests

    class _Boom:
        def raise_for_status(self):
            raise requests.HTTPError("offline (test)")

    def _explode(_c):
        raise requests.HTTPError("offline (test)")

    monkeypatch.setattr(dpp, "list_projects", _explode)
    uuid, code = dpp.resolve_project(cfg, "CAPP")
    assert uuid == "CAPP"
    assert code == "CAPP"


# ── download_single_page (dry-run path) ───────────────────────────────────────


def test_download_single_page_dry_run_returns_path(tmp_path, dpp, cfg):
    """Dry-run does not call the API, does not write the file, but
    still returns a deterministic path so callers can chain it (the
    `agents/generator/cli/run.py` Plane-source flow relies on this
    contract)."""
    out = dpp.download_single_page(
        cfg,
        project_uuid="11111111-1111-1111-1111-111111111111",
        project_code="CAPP",
        page_id="abc-page",
        output_root=str(tmp_path),
        dry_run=True,
    )
    assert out == tmp_path / "demo-ws" / "CAPP" / "dry-run-page-abc-page.md"
    # No actual write happened.
    assert not out.exists()


def test_download_single_page_writes_to_short_code_folder(tmp_path, monkeypatch, dpp, cfg):
    """The output folder uses the project code (`CAPP`), not the
    UUID — confirming the human-readable layout we ship to operators."""
    monkeypatch.setattr(
        dpp, "fetch_page",
        lambda c, p, pid: {"id": pid, "name": "My Plan", "description_html": "<p>x</p>"},
    )
    out = dpp.download_single_page(
        cfg,
        project_uuid="11111111-1111-1111-1111-111111111111",
        project_code="CAPP",
        page_id="abc-page",
        output_root=str(tmp_path),
        dry_run=False,
    )
    assert out == tmp_path / "demo-ws" / "CAPP" / "my-plan.md"
    assert out.exists()
    content = out.read_text()
    assert "plane_page_id: abc-page" in content
    assert "# My Plan" in content


# ── resolve_page_by_name ──────────────────────────────────────────────────────


def _pages_for_name_tests() -> list[dict]:
    """Mixed public / private pages with one unique name, one duplicate
    name, and one private-only name — covers every branch of
    `resolve_page_by_name`."""
    return [
        # Unique public page
        {"id": "page-unique-pub", "name": "Architecture", "access": 0},
        # Duplicate name (twice, both public)
        {"id": "page-dup-1", "name": "Roadmap", "access": 0},
        {"id": "page-dup-2", "name": "Roadmap", "access": 0},
        # Private-only name — invisible by default, visible with include-private
        {"id": "page-private-secret", "name": "Internal Plan", "access": 1},
        # Public + private with same name — collide only when --include-private
        {"id": "page-mixed-pub", "name": "Backlog", "access": 0},
        {"id": "page-mixed-priv", "name": "Backlog", "access": 1},
    ]


def _patch_list_pages(monkeypatch, dpp, pages):
    monkeypatch.setattr(dpp, "list_pages", lambda c, p: pages)


def test_resolve_page_by_name_unique_match(monkeypatch, dpp, cfg):
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    pid = dpp.resolve_page_by_name(
        cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
        "Architecture", include_private=False,
    )
    assert pid == "page-unique-pub"


def test_resolve_page_by_name_no_match_raises_not_found(monkeypatch, dpp, cfg):
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    with pytest.raises(dpp.PageNameResolutionError) as exc:
        dpp.resolve_page_by_name(
            cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
            "Nonexistent", include_private=False,
        )
    assert exc.value.kind == dpp.PAGE_NAME_NOT_FOUND
    assert "no page named" in str(exc.value)
    assert "Nonexistent" in str(exc.value)


def test_resolve_page_by_name_case_sensitive(monkeypatch, dpp, cfg):
    """`architecture` (lowercase) must NOT match `Architecture` — the
    spec calls for exact, case-sensitive matching so duplicate detection
    stays predictable."""
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    with pytest.raises(dpp.PageNameResolutionError) as exc:
        dpp.resolve_page_by_name(
            cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
            "architecture", include_private=False,
        )
    assert exc.value.kind == dpp.PAGE_NAME_NOT_FOUND


def test_resolve_page_by_name_ambiguous(monkeypatch, dpp, cfg):
    """Duplicate name → stops with `PAGE_NAME_AMBIGUOUS` so the operator
    sees the count and is told to switch to --page-id."""
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    with pytest.raises(dpp.PageNameResolutionError) as exc:
        dpp.resolve_page_by_name(
            cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
            "Roadmap", include_private=False,
        )
    assert exc.value.kind == dpp.PAGE_NAME_AMBIGUOUS
    assert "2 pages named" in str(exc.value)
    assert "--page-id" in str(exc.value)


def test_resolve_page_by_name_private_hidden_by_default(monkeypatch, dpp, cfg):
    """A private-only name (`Internal Plan`) is invisible unless the
    operator passes --include-private. The not-found message hints at
    this so the operator knows why the match failed."""
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    with pytest.raises(dpp.PageNameResolutionError) as exc:
        dpp.resolve_page_by_name(
            cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
            "Internal Plan", include_private=False,
        )
    assert exc.value.kind == dpp.PAGE_NAME_NOT_FOUND
    assert "--include-private" in str(exc.value)


def test_resolve_page_by_name_private_included_returns_match(monkeypatch, dpp, cfg):
    """With --include-private, the private-only page resolves."""
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())
    pid = dpp.resolve_page_by_name(
        cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
        "Internal Plan", include_private=True,
    )
    assert pid == "page-private-secret"


def test_resolve_page_by_name_collision_only_when_private_included(
    monkeypatch, dpp, cfg,
):
    """`Backlog` has a public + private collision. The public-only
    default sees just one match (public) and resolves cleanly. With
    --include-private both are visible → ambiguous."""
    _patch_list_pages(monkeypatch, dpp, _pages_for_name_tests())

    pid = dpp.resolve_page_by_name(
        cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
        "Backlog", include_private=False,
    )
    assert pid == "page-mixed-pub"

    with pytest.raises(dpp.PageNameResolutionError) as exc:
        dpp.resolve_page_by_name(
            cfg, "11111111-1111-1111-1111-111111111111", "CAPP",
            "Backlog", include_private=True,
        )
    assert exc.value.kind == dpp.PAGE_NAME_AMBIGUOUS


# ── _UUID_RE sanity ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("s,expected", [
    ("11111111-1111-1111-1111-111111111111", True),
    ("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", True),   # uppercase hex
    ("CAPP", False),
    ("CAPP-2", False),
    ("11111111-1111-1111-1111-11111111111", False),    # one too few
    ("not-a-uuid-at-all", False),
])
def test_uuid_re(dpp, s, expected):
    assert bool(dpp._UUID_RE.match(s)) is expected
