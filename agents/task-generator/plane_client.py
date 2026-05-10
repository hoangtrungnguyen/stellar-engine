"""Read-only Plane REST client for the task-generator agent (Phase 1)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

CONFIG_PATH = Path.home() / ".config" / "plane" / "config.json"
DEFAULT_TIMEOUT_SECONDS = 30


class PlaneClientError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"Plane API {status} on {url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = url


def load_credentials() -> tuple[str, str, str]:
    token = os.environ.get("PLANE_API_TOKEN")
    host = os.environ.get("PLANE_HOST")
    workspace = os.environ.get("PLANE_WORKSPACE")

    if not all([token, host, workspace]) and CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        token = token or cfg.get("token")
        host = host or cfg.get("host", "https://api.plane.so")
        workspace = workspace or cfg.get("workspace")

    host = host or "https://api.plane.so"

    if not token or not workspace:
        raise RuntimeError(
            f"Missing Plane credentials. Set PLANE_API_TOKEN + PLANE_WORKSPACE env vars, "
            f"or populate {CONFIG_PATH}."
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
