#!/usr/bin/env python3
"""grava_plane_sync: one-shot Grava → Plane sync, called by Grava agents
after each `grava signal` emission.

Reads the Grava Dolt DB (issues + issue_labels + issue_comments tables) for a
single issue (or all plane-labelled issues if no issue_id given), diffs the
current status/assignee/comments against a cached state file, and PATCHes
Plane to match.

Behaviour gates:
  * Plane not configured (no credentials)  → exit 0 silently.
  * No internet                            → exit 0 silently.
  * Grava issue has no `plane:<seq>` label → exit 2 silently.
  * Plane API failure                      → exit 3 (agents call with `|| true`).

This script is intentionally non-fatal — Plane sync should never break the
Grava agent pipeline. Failures retry naturally on the next agent signal.

CLI:
    python3 grava_plane_sync.py [<grava_issue_id>] \\
        --project-id <plane-project-uuid> \\
        --grava-repo /path/to/grava \\
        [--state-file PATH] \\
        [--system-yaml PATH] \\
        [--log-level INFO]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from plane_client import (  # noqa: E402
    CONFIG_PATH,
    PlaneClient,
    PlaneClientError,
    load_credentials,
    resolve_plane_config_path,
)

DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "grava-plane-sync"
DEFAULT_FAILURE_LOG = DEFAULT_STATE_DIR / "errors.jsonl"

log = logging.getLogger("grava_plane_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Failure log (G11)
# ─────────────────────────────────────────────────────────────────────────────


def log_failure(
    path: Path | None,
    *,
    project_id: str,
    issue_id: str | None,
    gate: str,
    exit_code: int,
    detail: str,
) -> None:
    """Append one JSONL line describing a non-success path. Best-effort.

    `gate` values: no_creds, no_internet, db_init, db_query, plane_creds,
    no_plane_label, plane_api, save_state.
    """
    if path is None:
        return
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_id": project_id,
        "issue_id": issue_id,
        "gate": gate,
        "exit_code": exit_code,
        "detail": detail[:500],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        # Logging the logger fails → stderr only; do not raise.
        log.debug("failure-log write failed (%s): %s", path, exc)


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WatcherState:
    # Per-issue snapshot of last-seen values.
    # {grava_id: {"status": str, "assignee": str|None, "seq_id": str}}
    issues: dict[str, dict] = field(default_factory=dict)
    # Comment cursor per issue (highest issue_comments.id already POSTed).
    last_comment_id_by_issue: dict[str, int] = field(default_factory=dict)
    # Plane sequence_id (str) → work-item UUID cache.
    seq_to_plane_uuid: dict[str, str] = field(default_factory=dict)
    # Plane state-name → state-UUID cache (warmed once per run).
    plane_states: dict[str, str] = field(default_factory=dict)
    # Plane state-name → group (for fallback resolution).
    plane_state_groups: dict[str, str] = field(default_factory=dict)
    # Plane state-name → sequence (for "lowest in group" tie-break).
    plane_state_sequences: dict[str, int] = field(default_factory=dict)
    # Grava assignee display string → Plane member UUID.
    plane_members: dict[str, str] = field(default_factory=dict)
    # Resolved grava_id custom-property UUIDs, keyed by work-item-type UUID.
    # Each Plane work-item type (epic, story, task, …) attaches the property
    # independently and gets its own property UUID, so we cache one entry per
    # type. Negative results are recorded as empty strings so we don't re-walk
    # the API on every run. See `resolve_grava_id_property_uuids` for the
    # auto-detection logic.
    grava_id_property_uuids: dict[str, str] = field(default_factory=dict)
    # Per-issue snapshot of the last grava_id value we POSTed to Plane.
    # Lets us skip the upsert when nothing changed (idempotency without a
    # GET round-trip). Keyed by grava issue id.
    grava_id_posted: dict[str, str] = field(default_factory=dict)


def load_state(path: Path) -> WatcherState:
    if not path.exists():
        return WatcherState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("state file corrupted at %s — starting fresh", path)
        return WatcherState()
    valid = {f for f in WatcherState.__dataclass_fields__}
    return WatcherState(**{k: v for k, v in data.items() if k in valid})


def save_state(state: WatcherState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ─────────────────────────────────────────────────────────────────────────────
# Gates
# ─────────────────────────────────────────────────────────────────────────────


def plane_configured() -> bool:
    """Return True if Plane credentials are reachable (env vars or config file).

    Honours PLANE_CONFIG / PLANE_PROFILE env vars so callers running with
    a non-default profile see the right file checked (and not just the
    static `~/.config/plane/config.json`).
    """
    env_token = os.environ.get("PLANE_API_TOKEN")
    env_ws = os.environ.get("PLANE_WORKSPACE")
    if env_token and env_ws:
        return True
    config_path = resolve_plane_config_path()
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return False
        return bool(cfg.get("token") and cfg.get("workspace"))
    return False


def internet_ok(host: str = "api.plane.so", port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Grava DB (dolt sql subprocess)
# ─────────────────────────────────────────────────────────────────────────────


class GravaDB:
    """Thin wrapper around `dolt sql` for the Grava Dolt database."""

    def __init__(self, grava_repo: Path):
        dolt_dir = grava_repo / ".grava" / "dolt"
        if not dolt_dir.exists():
            raise RuntimeError(f"Grava Dolt DB not found at {dolt_dir}")
        self._cwd = dolt_dir

    def _sql(self, query: str) -> list[dict]:
        result = subprocess.run(
            ["dolt", "sql", "-q", query, "--result-format", "json"],
            cwd=str(self._cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"dolt sql failed (exit {result.returncode}): "
                f"{result.stderr.strip()[:300]}"
            )
        raw = result.stdout.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"dolt sql non-JSON output: {raw[:200]!r}") from exc
        # dolt returns {} for zero rows, or {"rows": [...]}
        if isinstance(parsed, dict):
            return parsed.get("rows", [])
        if isinstance(parsed, list):
            return parsed
        return []

    @staticmethod
    def _escape(value: str) -> str:
        """Safe SQL string escape for identifiers we control (issue IDs).
        Grava issue IDs are restricted to [a-z0-9.-]; quoted with single quotes.
        """
        return value.replace("'", "''")

    def fetch_issue(self, issue_id: str) -> dict | None:
        """Return one plane-linked issue or None.

        Returns: {id, status, assignee, seq_id} or None if missing/not mirrored.
        """
        eid = self._escape(issue_id)
        rows = self._sql(
            f"""
            SELECT i.id, i.status, i.assignee, SUBSTRING(il.label, 7) AS seq_id
            FROM issues i
            JOIN issue_labels il ON i.id = il.issue_id
            WHERE i.id = '{eid}'
              AND il.label LIKE 'plane:%'
              AND il.label NOT LIKE 'plane-epic:%'
              AND il.label NOT LIKE 'plane-story:%'
            LIMIT 1
            """
        )
        return rows[0] if rows else None

    def fetch_all_plane_issues(self) -> list[dict]:
        """All plane-linked issues — one row per issue.

        Returns: [{id, status, assignee, seq_id}, ...]
        """
        return self._sql(
            """
            SELECT i.id, i.status, i.assignee, SUBSTRING(il.label, 7) AS seq_id
            FROM issues i
            JOIN issue_labels il ON i.id = il.issue_id
            WHERE il.label LIKE 'plane:%'
              AND il.label NOT LIKE 'plane-epic:%'
              AND il.label NOT LIKE 'plane-story:%'
            GROUP BY i.id, i.status, i.assignee, il.label
            """
        )

    def fetch_new_comments(self, issue_id: str, since_id: int) -> list[dict]:
        """Comments for one issue with id > since_id, ascending."""
        eid = self._escape(issue_id)
        return self._sql(
            f"""
            SELECT id, issue_id, message, actor, created_at
            FROM issue_comments
            WHERE issue_id = '{eid}' AND id > {int(since_id)}
            ORDER BY id ASC
            """
        )

    def fetch_max_comment_id(self, issue_id: str) -> int:
        """Highest issue_comments.id for an issue, or 0."""
        eid = self._escape(issue_id)
        rows = self._sql(
            f"SELECT MAX(id) AS max_id FROM issue_comments WHERE issue_id = '{eid}'"
        )
        if not rows:
            return 0
        value = rows[0].get("max_id")
        return int(value) if value is not None else 0


# ─────────────────────────────────────────────────────────────────────────────
# Plane state + member mapping
# ─────────────────────────────────────────────────────────────────────────────


_GROUP_FALLBACK = {
    "open": ["unstarted", "backlog"],
    "in_progress": ["started"],
    "closed": ["completed", "cancelled"],
}


class StateMapper:
    def __init__(
        self,
        client: PlaneClient,
        project_id: str,
        state: WatcherState,
        configured_map: dict[str, str],
    ):
        self._client = client
        self._project_id = project_id
        self._state = state
        self._configured = configured_map or {}

    def warm(self) -> None:
        """Populate state caches from list_states(). Safe to call repeatedly."""
        if self._state.plane_states:
            return
        try:
            states = self._client.list_states(self._project_id)
        except PlaneClientError as exc:
            log.warning("list_states failed: %s", exc)
            return
        for s in states:
            name = s.get("name")
            uuid = s.get("id")
            if not name or not uuid:
                continue
            self._state.plane_states[name] = uuid
            self._state.plane_state_groups[name] = s.get("group", "")
            self._state.plane_state_sequences[name] = int(s.get("sequence") or 0)

    def resolve(self, grava_status: str) -> str | None:
        """Return Plane state UUID for a Grava status, or None if unresolvable."""
        if not grava_status:
            return None
        # 1. Configured map
        configured_name = self._configured.get(grava_status)
        if configured_name and configured_name in self._state.plane_states:
            return self._state.plane_states[configured_name]
        # 2. Group fallback
        target_groups = _GROUP_FALLBACK.get(grava_status, [])
        candidates = []
        for name, uuid in self._state.plane_states.items():
            if self._state.plane_state_groups.get(name) in target_groups:
                seq = self._state.plane_state_sequences.get(name, 0)
                group_rank = target_groups.index(
                    self._state.plane_state_groups.get(name, "")
                )
                candidates.append((group_rank, seq, name, uuid))
        if candidates:
            candidates.sort()
            chosen = candidates[0]
            log.info(
                "state fallback: grava=%s → group=%s state=%s",
                grava_status,
                self._state.plane_state_groups.get(chosen[2]),
                chosen[2],
            )
            return chosen[3]
        return None


class GravaIDPropertyMirror:
    """Mirror the grava issue id into Plane as a custom property.

    Plane's custom-property system attaches the same property name (e.g.
    ``grava_id``) to one or more work-item types (epic, story, task, ...).
    Each type-binding gets its own property UUID. This class:

      1. Lists work-item types + their properties exactly once per run
         (via ``warm``), recording each type → property UUID mapping in
         the persisted state. Negative results (property not attached to
         a type) are stored as empty strings so we don't re-scan every
         tick.
      2. For each issue synced, ``mirror`` resolves the item's type
         binding → property UUID, compares the cached last-posted value
         (``state.grava_id_posted``) to the grava id, and POSTs an
         upsert only when the cached value differs. POST endpoint is
         documented as create-or-replace so we don't need a separate GET
         to disambiguate.

    The mirror is opt-in: if no Plane type has the property attached,
    ``warm`` records empty strings everywhere and ``mirror`` is a no-op
    (with a single info-level log line so operators know it's inactive).
    Operators enable mirroring by creating a TEXT custom property named
    ``grava_id`` on each work-item type they want tracked, via the Plane
    web UI (Settings → Work item types → <type> → Properties).
    """

    PROPERTY_NAME = "grava_id"

    def __init__(self, client: PlaneClient, project_id: str, state: WatcherState):
        self._client = client
        self._project_id = project_id
        self._state = state
        self._warmed = False
        # Cached `{plane_work_item_uuid: type_uuid}` lookup so repeat
        # mirror calls for the same issue don't re-GET the work item just
        # to discover its type.
        self._wi_to_type: dict[str, str] = {}

    def warm(self) -> bool:
        """Populate ``state.grava_id_property_uuids`` from Plane. Returns
        True when at least one type has the property attached (mirror is
        usable), False when the feature is dormant for this project.

        Idempotent — the resolved cache is persisted in state, so a warmed
        state carries forward across runs. Repeat calls re-use the cache
        without hitting the network unless it's empty.
        """
        if self._warmed:
            return any(self._state.grava_id_property_uuids.values())

        # Carry forward a populated cache without API calls. We only walk
        # the API on a cold cache; operators who want to force a refresh
        # can delete the `grava_id_property_uuids` block from the state
        # file.
        if self._state.grava_id_property_uuids:
            self._warmed = True
            return any(self._state.grava_id_property_uuids.values())

        try:
            types = self._client.list_work_item_types(self._project_id)
        except PlaneClientError as exc:
            log.warning(
                "grava_id mirror: list_work_item_types failed (%s) — mirror disabled this run",
                exc,
            )
            return False

        target = self.PROPERTY_NAME.lower()
        resolved: dict[str, str] = {}
        for t in types:
            type_uuid = t.get("id")
            if not type_uuid:
                continue
            try:
                props = self._client.list_type_properties(self._project_id, type_uuid)
            except PlaneClientError as exc:
                log.warning(
                    "grava_id mirror: list_type_properties(%s) failed: %s",
                    type_uuid,
                    exc,
                )
                # Treat as "unknown" — leave out of cache so we retry next run.
                continue
            prop_uuid = ""
            for p in props:
                name = (p.get("name") or "").strip().lower()
                display = (p.get("display_name") or "").strip().lower()
                if target in (name, display):
                    prop_uuid = p.get("id") or ""
                    break
            resolved[type_uuid] = prop_uuid

        self._state.grava_id_property_uuids = resolved
        self._warmed = True
        usable = any(resolved.values())
        if not usable:
            log.info(
                "grava_id mirror: no Plane work-item type in project %s has a "
                "'%s' custom property — mirror is a no-op. Create the property "
                "in Plane (Settings → Work item types → <type> → Properties) "
                "to enable.",
                self._project_id,
                self.PROPERTY_NAME,
            )
        else:
            log.info(
                "grava_id mirror: resolved %d/%d type bindings (%s)",
                sum(1 for v in resolved.values() if v),
                len(resolved),
                self.PROPERTY_NAME,
            )
        return usable

    def _lookup_type(self, plane_uuid: str) -> str | None:
        """Return the work-item-type UUID for a Plane item, GETting it once
        and caching for the remainder of the run.
        """
        if plane_uuid in self._wi_to_type:
            return self._wi_to_type[plane_uuid] or None
        try:
            wi = self._client.get_work_item(self._project_id, plane_uuid)
        except PlaneClientError as exc:
            log.warning(
                "grava_id mirror: get_work_item(%s) failed: %s — skip mirror",
                plane_uuid,
                exc,
            )
            return None
        type_uuid = wi.get("type") or wi.get("work_item_type") or ""
        # Normalise to string — Plane sometimes returns a dict here.
        if isinstance(type_uuid, dict):
            type_uuid = type_uuid.get("id", "")
        type_uuid = str(type_uuid or "")
        self._wi_to_type[plane_uuid] = type_uuid
        return type_uuid or None

    def mirror(self, plane_uuid: str, grava_id: str) -> bool:
        """Push ``grava_id`` to the Plane work item's custom property.

        Returns True on success or no-op, False on hard failure (the caller
        treats False as a non-fatal warning — Plane sync never blocks the
        Grava pipeline on property mirror).
        """
        if not self.warm():
            return True  # mirror dormant for this project; treat as success
        if not plane_uuid or not grava_id:
            return True
        cached = self._state.grava_id_posted.get(grava_id)
        if cached == grava_id:
            # Already posted this value — nothing to do.
            return True

        type_uuid = self._lookup_type(plane_uuid)
        if not type_uuid:
            return False
        prop_uuid = self._state.grava_id_property_uuids.get(type_uuid, "")
        if not prop_uuid:
            # Property not attached to this type — silently skip.
            log.debug(
                "grava_id mirror: type %s has no '%s' property; skip plane=%s grava=%s",
                type_uuid,
                self.PROPERTY_NAME,
                plane_uuid,
                grava_id,
            )
            return True

        try:
            self._client.upsert_property_value(
                self._project_id,
                plane_uuid,
                prop_uuid,
                grava_id,
                external_id=grava_id,
                external_source="grava",
            )
        except PlaneClientError as exc:
            log.warning(
                "grava_id mirror: upsert failed for plane=%s grava=%s: %s",
                plane_uuid,
                grava_id,
                exc,
            )
            return False

        self._state.grava_id_posted[grava_id] = grava_id
        log.info(
            "grava_id mirror: plane=%s ← grava=%s (prop=%s)",
            plane_uuid,
            grava_id,
            prop_uuid,
        )
        return True


class MemberMapper:
    def __init__(self, client: PlaneClient, state: WatcherState):
        self._client = client
        self._state = state

    def warm(self) -> None:
        if self._state.plane_members:
            return
        try:
            members = self._client.list_members()
        except PlaneClientError as exc:
            log.warning("list_members failed: %s — assignee sync disabled", exc)
            return
        for row in members:
            member = row.get("member") if isinstance(row.get("member"), dict) else row
            uuid = member.get("id")
            if not uuid:
                continue
            for key in ("display_name", "first_name", "email"):
                val = member.get(key)
                if val:
                    self._state.plane_members[str(val).lower()] = uuid
            email = member.get("email")
            if email and "@" in email:
                prefix = email.split("@", 1)[0]
                self._state.plane_members.setdefault(prefix.lower(), uuid)

    def resolve(self, assignee: str | None) -> str | None:
        if not assignee:
            return None
        return self._state.plane_members.get(assignee.lower())


# ─────────────────────────────────────────────────────────────────────────────
# Sync
# ─────────────────────────────────────────────────────────────────────────────


class PlaneSyncer:
    def __init__(
        self,
        client: PlaneClient,
        project_id: str,
        state: WatcherState,
        state_mapper: StateMapper,
        member_mapper: MemberMapper,
    ):
        self._client = client
        self._project_id = project_id
        self._state = state
        self._states = state_mapper
        self._members = member_mapper

    def resolve_plane_uuid(self, seq_id: str) -> str | None:
        if seq_id in self._state.seq_to_plane_uuid:
            return self._state.seq_to_plane_uuid[seq_id]
        try:
            results = self._client.search_work_items(
                self._project_id, sequence_id=int(seq_id)
            )
        except (PlaneClientError, ValueError) as exc:
            log.warning("search_work_items(seq=%s) failed: %s", seq_id, exc)
            return None
        for item in results:
            if str(item.get("sequence_id")) == str(seq_id):
                uuid = item.get("id")
                if uuid:
                    self._state.seq_to_plane_uuid[seq_id] = uuid
                    return uuid
        # Fallback — Plane may have ignored sequence_id filter; scan-search.
        try:
            all_items = self._client.search_work_items(self._project_id)
        except PlaneClientError as exc:
            log.warning("search_work_items(scan) failed: %s", exc)
            return None
        for item in all_items:
            if str(item.get("sequence_id")) == str(seq_id):
                uuid = item.get("id")
                if uuid:
                    self._state.seq_to_plane_uuid[seq_id] = uuid
                    return uuid
        log.warning("Plane work item not found for sequence_id=%s", seq_id)
        return None

    def sync_one_issue(self, row: dict) -> bool:
        """Diff one Grava issue vs cached state, PATCH Plane if needed.

        Returns True on success (incl. no-op), False on hard failure.
        """
        grava_id = row["id"]
        seq_id = str(row.get("seq_id") or "")
        if not seq_id:
            log.debug("issue %s has no seq_id — skip", grava_id)
            return True

        plane_uuid = self.resolve_plane_uuid(seq_id)
        if not plane_uuid:
            return False

        cached = self._state.issues.get(grava_id, {})
        new_status = row.get("status")
        new_assignee = row.get("assignee")
        old_status = cached.get("status")
        old_assignee = cached.get("assignee")

        patch: dict[str, Any] = {}

        if new_status != old_status:
            state_uuid = self._states.resolve(new_status)
            if state_uuid:
                patch["state"] = state_uuid
            else:
                log.info(
                    "issue %s: no Plane state for grava status=%r — skip state field",
                    grava_id,
                    new_status,
                )

        if new_assignee != old_assignee:
            if new_assignee is None:
                # Explicit unassign.
                patch["assignees"] = []
            else:
                member_uuid = self._members.resolve(new_assignee)
                if member_uuid:
                    patch["assignees"] = [member_uuid]
                else:
                    log.info(
                        "issue %s: no Plane member match for assignee=%r — skip",
                        grava_id,
                        new_assignee,
                    )

        # Idempotency: confirm current Plane values differ before PATCH.
        if patch:
            try:
                current = self._client.get_work_item(self._project_id, plane_uuid)
            except PlaneClientError as exc:
                log.warning("get_work_item(%s) failed: %s", plane_uuid, exc)
                return False
            effective = dict(patch)
            if "state" in effective and current.get("state") == effective["state"]:
                effective.pop("state")
            if "assignees" in effective:
                # Plane's GET response sometimes returns assignees as list of
                # member dicts ({id, display_name, ...}) and sometimes as a
                # flat list of UUIDs. Normalise to UUID set for comparison.
                raw = current.get("assignees") or []
                cur_assignees: set[str] = set()
                for a in raw:
                    if isinstance(a, dict):
                        uid = a.get("id")
                        if uid:
                            cur_assignees.add(uid)
                    elif isinstance(a, str):
                        cur_assignees.add(a)
                if cur_assignees == set(effective["assignees"]):
                    effective.pop("assignees")
            if effective:
                try:
                    self._client.update_work_item(
                        self._project_id, plane_uuid, effective
                    )
                    log.info("PATCH plane=%s grava=%s fields=%s",
                             plane_uuid, grava_id, list(effective.keys()))
                except PlaneClientError as exc:
                    log.warning("update_work_item failed for %s: %s", grava_id, exc)
                    return False
            else:
                log.debug("issue %s: Plane already matches, no PATCH", grava_id)

        # Update cached snapshot for this issue.
        self._state.issues[grava_id] = {
            "status": new_status,
            "assignee": new_assignee,
            "seq_id": seq_id,
        }
        return True

    def post_comment(self, comment_row: dict, plane_uuid: str) -> bool:
        actor = comment_row.get("actor") or "grava"
        message = comment_row.get("message") or ""
        # newlines → <br>, prefix actor.
        body = message.replace("\n", "<br>")
        html = f"<p><strong>[grava/{actor}]</strong> {body}</p>"
        try:
            self._client.add_comment(self._project_id, plane_uuid, html)
            return True
        except PlaneClientError as exc:
            log.warning(
                "add_comment failed for plane=%s grava-comment-id=%s: %s",
                plane_uuid,
                comment_row.get("id"),
                exc,
            )
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────


def _load_state_map(system_yaml: Path | None, project_id: str) -> dict[str, str]:
    if not system_yaml or not system_yaml.exists():
        return {}
    try:
        data = yaml.safe_load(system_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.warning("system.yaml parse failed: %s", exc)
        return {}
    block = data.get("plane_state_map") or {}
    return block.get(project_id) or {}


def sync_issue(
    db: GravaDB,
    syncer: PlaneSyncer,
    state: WatcherState,
    row: dict,
    is_first_seen: bool,
    grava_id_mirror: "GravaIDPropertyMirror | None" = None,
) -> None:
    """Sync status/assignee + new comments for one issue."""
    grava_id = row["id"]
    ok = syncer.sync_one_issue(row)
    if not ok:
        return

    seq_id = str(row.get("seq_id") or "")
    plane_uuid = state.seq_to_plane_uuid.get(seq_id)
    if not plane_uuid:
        return

    # Best-effort: push the grava id into Plane's custom property if one is
    # configured. Failures are non-fatal — `mirror` swallows API errors and
    # returns False; we surface them only as warnings so they never block
    # the surrounding sync.
    if grava_id_mirror is not None:
        grava_id_mirror.mirror(plane_uuid, grava_id)

    # First-time-seen issue: skip historical comments — set cursor to current max.
    if is_first_seen and grava_id not in state.last_comment_id_by_issue:
        try:
            max_id = db.fetch_max_comment_id(grava_id)
        except RuntimeError as exc:
            log.warning("fetch_max_comment_id(%s) failed: %s", grava_id, exc)
            max_id = 0
        state.last_comment_id_by_issue[grava_id] = max_id
        log.info(
            "issue %s first seen — comment cursor initialised to %d (skip historical)",
            grava_id,
            max_id,
        )
        return

    cursor = state.last_comment_id_by_issue.get(grava_id, 0)
    try:
        new_comments = db.fetch_new_comments(grava_id, cursor)
    except RuntimeError as exc:
        log.warning("fetch_new_comments(%s) failed: %s", grava_id, exc)
        return

    for comment in new_comments:
        if not syncer.post_comment(comment, plane_uuid):
            # Stop on first failure — cursor not advanced past the failed one.
            return
        cid = int(comment["id"])
        state.last_comment_id_by_issue[grava_id] = max(cursor, cid)
        cursor = state.last_comment_id_by_issue[grava_id]


# ─────────────────────────────────────────────────────────────────────────────
# Pull direction — bulk import Plane work items as new grava issues
# ─────────────────────────────────────────────────────────────────────────────


_PLANE_PRIORITY_TO_GRAVA = {
    "urgent": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "medium",
}

_PLANE_GROUP_TO_GRAVA_STATUS = {
    "backlog": "open",
    "unstarted": "open",
    "started": "in_progress",
    "completed": "closed",
    "cancelled": "closed",
}


def _run_grava_cli(
    args: list[str], cwd: Path, timeout: int = 30, want_json: bool = False
) -> tuple[int, str, str]:
    """Run a grava CLI command in `cwd`. Returns (rc, stdout, stderr)."""
    cmd = ["grava"] + (["--json"] if want_json else []) + args
    r = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, r.stdout, r.stderr


def _grava_create_issue(
    grava_repo: Path,
    title: str,
    description: str,
    issue_type: str = "task",
    priority: str = "medium",
) -> str:
    """Create a grava issue, return its id. Raises RuntimeError on failure."""
    rc, out, err = _run_grava_cli(
        [
            "create",
            "-t", title,
            "-d", description,
            "--type", issue_type,
            "-p", priority,
        ],
        cwd=grava_repo,
        want_json=True,
    )
    if rc != 0:
        raise RuntimeError(f"grava create failed (exit {rc}): {err.strip() or out.strip()}")
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"grava create returned non-JSON: {out[:200]!r}") from exc
    issue_id = parsed.get("id") if isinstance(parsed, dict) else None
    if not issue_id:
        raise RuntimeError(f"grava create response missing id: {parsed!r}")
    return issue_id


def _grava_add_label(grava_repo: Path, issue_id: str, label: str) -> None:
    rc, out, err = _run_grava_cli(
        ["label", issue_id, "--add", label], cwd=grava_repo
    )
    if rc != 0:
        raise RuntimeError(
            f"grava label {issue_id} --add {label} failed (exit {rc}): "
            f"{err.strip() or out.strip()}"
        )


def _grava_close_force(grava_repo: Path, issue_id: str) -> None:
    rc, out, err = _run_grava_cli(
        ["close", "--force", issue_id], cwd=grava_repo, timeout=60
    )
    if rc != 0:
        raise RuntimeError(
            f"grava close --force {issue_id} failed (exit {rc}): "
            f"{err.strip() or out.strip()}"
        )


def pull_from_plane(
    client: PlaneClient,
    project_id: str,
    grava_repo: Path,
    db: GravaDB,
) -> dict:
    """Create grava mirrors for all Plane work items not yet linked.

    Skips items that already have a grava issue with their `plane:<seq>` label.
    Returns a counts dict: {scanned, already_linked, created, skipped, failed}.
    """
    pull_log = logging.getLogger("grava_plane_sync.pull")

    # Already-mirrored seq ids (from local grava DB).
    try:
        mirrored_rows = db.fetch_all_plane_issues()
    except RuntimeError as exc:
        pull_log.error("Cannot read mirrored seq ids: %s", exc)
        raise
    mirrored_seqs = {str(r.get("seq_id")) for r in mirrored_rows if r.get("seq_id")}
    pull_log.info("Pull: %d already-mirrored seq ids", len(mirrored_seqs))

    # All Plane work items in the project.
    items = client.search_work_items(project_id)
    pull_log.info("Pull: %d Plane work items returned", len(items))

    # State UUID → group map for status decision.
    states_by_uuid = {s["id"]: s for s in client.list_states(project_id)}

    counts = {"scanned": 0, "already_linked": 0, "created": 0, "skipped": 0, "failed": 0}
    for item in items:
        counts["scanned"] += 1
        seq = item.get("sequence_id")
        if seq is None:
            pull_log.warning("Skip: work item %s has no sequence_id", item.get("id"))
            counts["skipped"] += 1
            continue
        seq_str = str(seq)
        if seq_str in mirrored_seqs:
            counts["already_linked"] += 1
            continue

        title = (item.get("name") or "").strip() or f"Plane item {seq_str}"
        body = (
            item.get("description_stripped")
            or item.get("description")
            or ""
        )
        if isinstance(body, dict):
            body = ""  # Plane sometimes returns a rich-text object; skip.
        body = str(body).strip()

        plane_priority = (item.get("priority") or "none").lower()
        grava_priority = _PLANE_PRIORITY_TO_GRAVA.get(plane_priority, "medium")

        state_uuid = item.get("state")
        state_obj = states_by_uuid.get(state_uuid) if state_uuid else None
        plane_group = (state_obj or {}).get("group", "unstarted")
        grava_target_status = _PLANE_GROUP_TO_GRAVA_STATUS.get(plane_group, "open")

        try:
            new_id = _grava_create_issue(
                grava_repo,
                title=title,
                description=body,
                issue_type="task",
                priority=grava_priority,
            )
            _grava_add_label(grava_repo, new_id, f"plane:{seq_str}")
            if grava_target_status == "closed":
                _grava_close_force(grava_repo, new_id)
            pull_log.info(
                "Created grava %s ← plane:%s [%s, %s]",
                new_id, seq_str, grava_target_status, grava_priority,
            )
            counts["created"] += 1
        except Exception as exc:  # noqa: BLE001
            pull_log.error("Failed to mirror plane:%s — %s", seq_str, exc)
            counts["failed"] += 1

    return counts


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Grava → Plane one-shot sync. "
            "Called by Grava agents after `grava signal` emits."
        )
    )
    ap.add_argument(
        "issue_id",
        nargs="?",
        default=None,
        help="Grava issue id (e.g. grava-0305). Omit to scan all plane-linked issues.",
    )
    ap.add_argument("--project-id", required=True, help="Plane project UUID.")
    ap.add_argument(
        "--grava-repo",
        type=Path,
        required=True,
        help="Path to Grava repo root (must contain .grava/dolt/).",
    )
    ap.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help=(
            "JSON state file path. "
            "Default: ~/.local/share/grava-plane-sync/<project_id>.json"
        ),
    )
    ap.add_argument(
        "--system-yaml",
        type=Path,
        default=None,
        help="Path to system.yaml containing plane_state_map. Optional.",
    )
    ap.add_argument(
        "--log-failures",
        type=Path,
        default=DEFAULT_FAILURE_LOG,
        help=(
            "Append-only JSONL log of non-success paths "
            f"(default: {DEFAULT_FAILURE_LOG}). "
            "Pass /dev/null to disable."
        ),
    )
    ap.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    ap.add_argument(
        "--direction",
        default="push",
        choices=["push", "pull", "both"],
        help=(
            "Sync direction. push (default): grava → Plane (existing behaviour). "
            "pull: import Plane work items as new grava issues "
            "(creates a grava issue with `plane:<seq>` label for every Plane "
            "item not yet mirrored). both: run pull then push."
        ),
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    failure_log: Path | None = args.log_failures
    # `--log-failures /dev/null` (or any non-regular path the user can't write
    # to) acts as a disable switch — log_failure() catches OSError silently.
    if failure_log and str(failure_log) == "/dev/null":
        failure_log = None

    project_id = args.project_id
    issue_id = args.issue_id

    # Gate 0: Plane configured?
    if not plane_configured():
        log.debug("Plane not configured — skip")
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="no_creds",
            exit_code=0,
            detail=(
                f"PLANE_API_TOKEN/PLANE_WORKSPACE env unset and "
                f"{resolve_plane_config_path()} missing "
                f"(set PLANE_CONFIG or PLANE_PROFILE to use a different profile)"
            ),
        )
        return 0

    state_path = args.state_file or (DEFAULT_STATE_DIR / f"{project_id}.json")
    state = load_state(state_path)

    # Gate 1: internet?
    if not internet_ok():
        log.info("internet check failed — skip Plane sync")
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="no_internet",
            exit_code=0,
            detail="TCP connect api.plane.so:443 failed",
        )
        return 0

    # Load DB.
    try:
        db = GravaDB(args.grava_repo)
    except RuntimeError as exc:
        log.error("%s", exc)
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="db_init",
            exit_code=1,
            detail=str(exc),
        )
        return 1

    # Plane client + credentials are needed by both directions.
    try:
        token, host, workspace = load_credentials()
    except RuntimeError as exc:
        log.error("Plane credentials: %s", exc)
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="plane_creds",
            exit_code=1,
            detail=str(exc),
        )
        return 1
    client = PlaneClient(host=host, workspace=workspace, token=token)

    direction = getattr(args, "direction", "push")
    plane_failure_detail: list[str] = []

    # ── Pull leg ────────────────────────────────────────────────────────────
    if direction in ("pull", "both"):
        try:
            counts = pull_from_plane(client, project_id, args.grava_repo, db)
            log.info(
                "Pull complete: scanned=%d already_linked=%d created=%d "
                "skipped=%d failed=%d",
                counts["scanned"],
                counts["already_linked"],
                counts["created"],
                counts["skipped"],
                counts["failed"],
            )
            if counts["failed"]:
                plane_failure_detail.append(
                    f"pull: {counts['failed']}/{counts['scanned']} create attempts failed"
                )
        except Exception as exc:  # noqa: BLE001
            log.error("pull_from_plane failed: %s", exc)
            log_failure(
                failure_log,
                project_id=project_id,
                issue_id=issue_id,
                gate="pull_plane",
                exit_code=3,
                detail=str(exc),
            )
            if direction == "pull":
                return 3
            # `both`: still attempt push leg
            plane_failure_detail.append(f"pull: {exc}")

        # Pull-only: skip push entirely.
        if direction == "pull":
            try:
                save_state(state, state_path)
            except OSError as exc:
                log.warning("save_state failed: %s", exc)
            if plane_failure_detail:
                log_failure(
                    failure_log,
                    project_id=project_id,
                    issue_id=issue_id,
                    gate="plane_api",
                    exit_code=3,
                    detail="; ".join(plane_failure_detail),
                )
                return 3
            return 0

    # ── Push leg (existing behaviour) ───────────────────────────────────────
    # Resolve issues to sync.
    try:
        if issue_id:
            row = db.fetch_issue(issue_id)
            if not row:
                log.debug("issue %s missing plane:* label — silent skip", issue_id)
                log_failure(
                    failure_log,
                    project_id=project_id,
                    issue_id=issue_id,
                    gate="no_plane_label",
                    exit_code=2,
                    detail="grava issue has no `plane:<seq>` label",
                )
                return 2
            rows = [row]
        else:
            rows = db.fetch_all_plane_issues()
            log.info("Full scan: %d plane-linked issues", len(rows))
            if not rows:
                return 0
    except RuntimeError as exc:
        log.error("Grava DB query failed: %s", exc)
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="db_query",
            exit_code=1,
            detail=str(exc),
        )
        return 1

    state_map = _load_state_map(args.system_yaml, project_id)
    state_mapper = StateMapper(client, project_id, state, state_map)
    member_mapper = MemberMapper(client, state)
    state_mapper.warm()
    member_mapper.warm()

    # Best-effort custom-property mirror. `warm` populates the cache in
    # `state.grava_id_property_uuids` (or records the no-op state) so it's
    # cheap on subsequent calls. The mirror itself is wired into sync_issue
    # below and silently no-ops when the property isn't configured in Plane.
    grava_id_mirror = GravaIDPropertyMirror(client, project_id, state)
    grava_id_mirror.warm()

    syncer = PlaneSyncer(client, project_id, state, state_mapper, member_mapper)

    for row in rows:
        grava_id = row["id"]
        is_first_seen = grava_id not in state.issues
        try:
            sync_issue(db, syncer, state, row, is_first_seen, grava_id_mirror)
        except Exception as exc:  # noqa: BLE001
            log.warning("sync_issue(%s) failed: %s", grava_id, exc)
            plane_failure_detail.append(f"{grava_id}: {exc}")

    # Always save state (caches + cursors + per-issue snapshot).
    try:
        save_state(state, state_path)
    except OSError as exc:
        log.warning("save_state failed: %s", exc)
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="save_state",
            exit_code=0,
            detail=f"{state_path}: {exc}",
        )

    if plane_failure_detail:
        log_failure(
            failure_log,
            project_id=project_id,
            issue_id=issue_id,
            gate="plane_api",
            exit_code=3,
            detail="; ".join(plane_failure_detail),
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
