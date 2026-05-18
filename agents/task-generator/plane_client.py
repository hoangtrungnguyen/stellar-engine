"""Read-only Plane REST client for the task-generator agent (Phase 1)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

CONFIG_DIR = Path.home() / ".config" / "plane"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_TIMEOUT_SECONDS = 30


class PlaneClientError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"Plane API {status} on {url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = url


def resolve_plane_config_path() -> Path:
    """Resolve which Plane config JSON file to load.

    Priority order (first match wins):
      1. PLANE_CONFIG env var — explicit absolute path to a config JSON file
      2. PLANE_PROFILE env var — short name → ~/.config/plane/<name>.json
      3. Default ~/.config/plane/config.json

    The function does NOT verify the file exists — callers handle that
    so they can fall back to env-var-only credentials.
    """
    explicit = os.environ.get("PLANE_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    profile = os.environ.get("PLANE_PROFILE", "").strip()
    if profile:
        return CONFIG_DIR / f"{profile}.json"
    return CONFIG_PATH


def load_credentials() -> tuple[str, str, str]:
    """Return (token, host, workspace) from env vars + config file.

    Precedence (highest → lowest):
      1. Direct env vars: PLANE_API_TOKEN, PLANE_HOST, PLANE_WORKSPACE
         — each takes precedence individually (partial override works)
      2. Config JSON file resolved by `resolve_plane_config_path()`
         (PLANE_CONFIG > PLANE_PROFILE > default config.json)
      3. host default: https://api.plane.so

    Raises RuntimeError with a hint pointing at the resolved config path
    if either token or workspace remain unset.
    """
    token = os.environ.get("PLANE_API_TOKEN")
    host = os.environ.get("PLANE_HOST")
    workspace = os.environ.get("PLANE_WORKSPACE")

    config_path = resolve_plane_config_path()
    if not all([token, host, workspace]) and config_path.exists():
        cfg = json.loads(config_path.read_text())
        token = token or cfg.get("token")
        host = host or cfg.get("host", "https://api.plane.so")
        workspace = workspace or cfg.get("workspace")

    host = host or "https://api.plane.so"

    if not token or not workspace:
        raise RuntimeError(
            f"Missing Plane credentials. Set PLANE_API_TOKEN + PLANE_WORKSPACE env vars, "
            f"or populate {config_path} "
            f"(override location via PLANE_CONFIG or PLANE_PROFILE env vars)."
        )

    return token, host.rstrip("/"), workspace


class PlaneClient:
    def __init__(self, host: str, workspace: str, token: str):
        self._host = host.rstrip("/")
        self._workspace = workspace
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": token,
            "Content-Type": "application/json",
        })

    def __repr__(self) -> str:
        return f"PlaneClient(host={self._host!r}, workspace={self._workspace!r}, token=<redacted>)"

    def _url(self, path: str) -> str:
        return f"{self._host}/api/v1/workspaces/{self._workspace}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        url = self._url(path)
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
        for attempt in range(5):
            resp = self._session.request(method, url, **kwargs)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", "5"))
                time.sleep(min(wait, 30))
                continue
            if 500 <= resp.status_code < 600 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise PlaneClientError(resp.status_code, resp.text, url)
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        raise PlaneClientError(429, "Too many retries", url)

    # ── Project ──────────────────────────────────────
    def get_project(self, project_id: str) -> dict:
        return self._request("GET", f"projects/{project_id}/")

    # ── Pages ────────────────────────────────────────
    def get_page(self, project_id: str, page_id: str) -> dict:
        return self._request("GET", f"projects/{project_id}/pages/{page_id}/")

    def list_pages(self, project_id: str) -> list[dict]:
        data = self._request("GET", f"projects/{project_id}/pages/")
        if isinstance(data, list):
            return data
        return data.get("results", [])

    # ── Work-item types ──────────────────────────────
    def list_work_item_types(self, project_id: str) -> list[dict]:
        data = self._request("GET", f"projects/{project_id}/work-item-types/")
        if isinstance(data, list):
            return data
        return data.get("results", [])

    # ── Work items ───────────────────────────────────
    def get_work_item(self, project_id: str, issue_id: str) -> dict:
        return self._request("GET", f"projects/{project_id}/work-items/{issue_id}/")

    def search_work_items(self, project_id: str, **filters) -> list[dict]:
        """List work items, following cursor pagination until exhausted.

        Plane returns up to ~100 items per page in a wrapper:
        `{results: [...], next_cursor, next_page_results, ...}`.
        """
        params = dict(filters)
        params.setdefault("per_page", 100)
        out: list[dict] = []
        seen_cursors: set[str] = set()
        while True:
            data = self._request("GET", f"projects/{project_id}/work-items/", params=params)
            if isinstance(data, list):
                out.extend(data)
                return out
            out.extend(data.get("results", []))
            if not data.get("next_page_results"):
                return out
            cursor = data.get("next_cursor")
            if not cursor or cursor in seen_cursors:
                return out
            seen_cursors.add(cursor)
            params["cursor"] = cursor

    def create_work_item(self, project_id: str, payload: dict) -> dict:
        return self._request(
            "POST",
            f"projects/{project_id}/work-items/",
            json=payload,
        )

    def update_work_item(self, project_id: str, issue_id: str, payload: dict) -> dict:
        return self._request(
            "PATCH",
            f"projects/{project_id}/work-items/{issue_id}/",
            json=payload,
        )

    def delete_work_item(self, project_id: str, issue_id: str) -> None:
        self._request("DELETE", f"projects/{project_id}/work-items/{issue_id}/")

    # ── Comments ─────────────────────────────────────
    def add_comment(self, project_id: str, issue_id: str, comment_html: str) -> dict:
        return self._request(
            "POST",
            f"projects/{project_id}/work-items/{issue_id}/comments/",
            json={"comment_html": comment_html},
        )

    # ── Relations (Phase 6 — `blocking` mirror of analyzer dep edges) ──
    def list_relations(self, project_id: str, issue_id: str) -> dict:
        """GET /issues/{id}/relations/

        Returns dict with relation-type buckets:
        ``{"blocking": [...], "blocked_by": [...], "start_after": [...],
        "start_before": [...], "finish_after": [...], "finish_before": [...],
        "relates_to": [...], "duplicate": [...]}``. Each list contains
        target issue UUIDs (strings).
        """
        data = self._request(
            "GET", f"projects/{project_id}/issues/{issue_id}/relations/"
        )
        return data if isinstance(data, dict) else {}

    def add_relation(
        self,
        project_id: str,
        src_issue_id: str,
        relation_type: str,
        dst_issue_ids: list[str],
    ) -> list[dict]:
        """POST /issues/{src}/relations/ — server returns list of relation rows.

        Plane auto-creates the bidirectional inverse (e.g. POSTing
        ``blocking`` from src to dst also adds ``blocked_by`` from dst's view).
        """
        resp = self._request(
            "POST",
            f"projects/{project_id}/issues/{src_issue_id}/relations/",
            json={"relation_type": relation_type, "issues": dst_issue_ids},
        )
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            return [resp]
        return []

    # ── Labels ───────────────────────────────────────
    def list_labels(self, project_id: str) -> list[dict]:
        data = self._request("GET", f"projects/{project_id}/labels/")
        if isinstance(data, list):
            return data
        return data.get("results", [])

    def create_label(self, project_id: str, name: str, color: str = "#888") -> dict:
        return self._request(
            "POST",
            f"projects/{project_id}/labels/",
            json={"name": name, "color": color},
        )

    # ── States ───────────────────────────────────────
    def list_states(self, project_id: str) -> list[dict]:
        """GET /workspaces/{ws}/projects/{id}/states/

        Returns list of dicts: ``[{id, name, group, color, sequence, ...}, ...]``.
        ``group`` is one of: ``backlog | unstarted | started | completed | cancelled``.
        """
        data = self._request("GET", f"projects/{project_id}/states/")
        if isinstance(data, list):
            return data
        return data.get("results", [])

    # ── Members ──────────────────────────────────────
    def list_members(self) -> list[dict]:
        """GET /workspaces/{ws}/members/

        Returns workspace member rows. Shape (Plane-version dependent):
        ``[{member: {id, display_name, email, ...}, role, ...}, ...]`` or flat
        ``[{id, display_name, email, ...}, ...]``. Callers handle both.
        """
        data = self._request("GET", "members/")
        if isinstance(data, list):
            return data
        return data.get("results", [])
