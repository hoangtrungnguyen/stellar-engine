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
)

DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "grava-plane-sync"

log = logging.getLogger("grava_plane_sync")


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
    """Return True if Plane credentials are reachable (env vars or config file)."""
    env_token = os.environ.get("PLANE_API_TOKEN")
    env_ws = os.environ.get("PLANE_WORKSPACE")
    if env_token and env_ws:
        return True
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Gate 0: Plane configured?
    if not plane_configured():
        log.debug("Plane not configured — skip")
        return 0

    state_path = args.state_file or (DEFAULT_STATE_DIR / f"{args.project_id}.json")
    state = load_state(state_path)

    # Gate 1: internet?
    if not internet_ok():
        log.info("internet check failed — skip Plane sync")
        return 0

    # Load DB.
    try:
        db = GravaDB(args.grava_repo)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    # Resolve issues to sync.
    try:
        if args.issue_id:
            row = db.fetch_issue(args.issue_id)
            if not row:
                log.debug(
                    "issue %s missing plane:* label — silent skip",
                    args.issue_id,
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
        return 1

    # Plane client + caches.
    try:
        token, host, workspace = load_credentials()
    except RuntimeError as exc:
        log.error("Plane credentials: %s", exc)
        return 1
    client = PlaneClient(host=host, workspace=workspace, token=token)

    state_map = _load_state_map(args.system_yaml, args.project_id)
    state_mapper = StateMapper(client, args.project_id, state, state_map)
    member_mapper = MemberMapper(client, state)
    state_mapper.warm()
    member_mapper.warm()

    syncer = PlaneSyncer(client, args.project_id, state, state_mapper, member_mapper)

    plane_failure = False
    for row in rows:
        grava_id = row["id"]
        is_first_seen = grava_id not in state.issues
        try:
            sync_issue(db, syncer, state, row, is_first_seen)
        except Exception as exc:  # noqa: BLE001
            log.warning("sync_issue(%s) failed: %s", grava_id, exc)
            plane_failure = True

    # Always save state (caches + cursors + per-issue snapshot).
    try:
        save_state(state, state_path)
    except OSError as exc:
        log.warning("save_state failed: %s", exc)

    return 3 if plane_failure else 0


if __name__ == "__main__":
    sys.exit(main())
