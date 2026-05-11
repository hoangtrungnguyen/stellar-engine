"""Grava writer (Phase 3 + Phase 5 deps): mirror the Plane hierarchy into Grava.

Walks the same plane_ops produced by planner.plan_from_cached, dispatching
only `CreateWorkItem` ops. For each op:

  1. Read the current Plane state (title, description, priority) via
     PlaneClient.get_work_item — Plane is the source of truth between runs.
  2. Search Grava for an existing issue with label `plane:<seq>`.
       0 matches → CREATE: `grava create` (epic) or `grava subtask <parent>` (story/task).
                   Apply labels: `plane:<own>` plus parent labels by level.
       1 match  → UPDATE if (title, desc, priority) differ, else no-op.
       2+ match → skip; record anomaly. Operator resolves manually.
  3. Atomic checkpoint after each op.

After all creates/updates land, post a Plane comment on each freshly-created
work item (UPDATE path skips comment-back — that comment exists from the
prior mirror run).

Phase 5: if `dep_edges` is passed (from cli/run.py's dep_graph.json), walk
the resolved edge list and post `grava dep <src> <dst> --type blocks` for
each. Idempotent: a duplicate-primary-key error is treated as success and
checkpointed in `state.dep_edges_posted` so resume runs skip it.

Final step: `grava commit -m ...` to persist Dolt history. Hash captured in
the report.

Failure modes mirror plane_writer: prompt | abort | rollback. Rollback runs
`grava drop <id> --force` in reverse order. Plane state is not touched.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from ir import (
    CreateWorkItem,
    GravaState,
    RunPlan,
    RunReport,
    RunState,
)


_PRIORITY_MAP = {
    "urgent": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "medium",
    "": "medium",
    None: "medium",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_state(state: GravaState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")


def load_state(path: Path) -> GravaState | None:
    if not path.exists():
        return None
    return GravaState(**json.loads(path.read_text(encoding="utf-8")))


def _map_priority(plane_priority: str | None) -> str:
    if plane_priority is None:
        return "medium"
    return _PRIORITY_MAP.get(plane_priority.lower(), "medium")


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub("", html)
    return text.strip()


def _plane_url(workspace: str, project_identifier: str, sequence_id) -> str:
    """Build the human-readable Plane work-item URL.

    Format: https://app.plane.so/{workspace}/browse/{IDENTIFIER}-{SEQ}/
    e.g.    https://app.plane.so/sportbuddies/browse/WEBINTRO-166/
    """
    return f"https://app.plane.so/{workspace}/browse/{project_identifier}-{sequence_id}/"


def _compose_grava_desc(
    *,
    own_url: str,
    epic_url: str | None,
    story_url: str | None,
    spec_url: str | None,
    body: str,
) -> str:
    lines: list[str] = [f"Plane: {own_url}"]
    if epic_url:
        lines.append(f"Plane epic: {epic_url}")
    if story_url:
        lines.append(f"Plane story: {story_url}")
    if spec_url:
        lines.append(f"Spec: {spec_url}")
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines)


def _comment_html(grava_id: str) -> str:
    return f"<p>Mirrored to Grava: <code>{grava_id}</code></p>"


def _run_grava(
    args: list[str],
    *,
    cwd: Path,
    actor: str,
    runner: Callable,
) -> dict | list:
    """Invoke `grava ...` with --json; parse stdout as JSON; raise on failure."""
    cmd = ["grava", *args, "--json"]
    env = {**os.environ, "GRAVA_ACTOR": actor}
    result = runner(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode != 0:
        try:
            err = json.loads(stdout)
        except json.JSONDecodeError:
            err = {"error": {"message": stderr.strip() or stdout.strip() or "grava failed"}}
        msg = err.get("error", {}).get("message", "grava failed")
        raise RuntimeError(f"grava {' '.join(args[:2])}: {msg}")
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"grava {args[0]}: non-JSON stdout: {stdout[:200]!r}")


def _grava_search_by_label(
    label: str,
    *,
    cwd: Path,
    actor: str,
    runner: Callable,
) -> list[dict]:
    """Return all Grava issues carrying the given label (live + archived)."""
    out = _run_grava(
        ["list", "--label", label, "--include-archived"],
        cwd=cwd, actor=actor, runner=runner,
    )
    if isinstance(out, list):
        return out
    if isinstance(out, dict) and "issues" in out:
        return out["issues"]
    return []


def execute(
    plan: RunPlan,
    plane_state: RunState,
    target_repo: Path,
    client,
    project_id: str,
    spec_page_url: str,
    workspace: str,
    *,
    state: GravaState,
    state_path: Path,
    report_path: Path,
    project_identifier: str = "",
    on_failure: Literal["prompt", "rollback", "abort"] = "prompt",
    actor: str = "task-generator",
    input_fn=input,
    run_subprocess: Callable = subprocess.run,
    dep_edges: list[dict] | None = None,
) -> RunReport:
    """Mirror the Plane hierarchy into Grava. See module docstring for the algorithm."""
    if not (target_repo / ".grava.yaml").exists():
        raise RuntimeError(
            f"Grava is not initialised in {target_repo}. "
            f"Run 'grava init' from inside the repo, then re-run."
        )

    if report_path.exists():
        existing = json.loads(report_path.read_text(encoding="utf-8"))
        report = _report_from_dict(existing)
    else:
        report = RunReport(
            run_id=state.run_id,
            spec_page_id=plane_state.page_id,
            started_at=plane_state.started_at,
        )

    completed = set(state.completed_op_indices)
    create_order: list[tuple[int, str, str]] = []  # (idx, ref_key, grava_id) — for rollback

    # Reseed report.grava_created from state so resume runs don't lose prior
    # creates. The previous run may have crashed before writing the report.
    if state.ref_to_grava_id and not report.grava_created:
        for idx in sorted(completed):
            if idx >= len(plan.plane_ops):
                continue
            op = plan.plane_ops[idx]
            if not isinstance(op, CreateWorkItem):
                continue
            grava_id = state.ref_to_grava_id.get(op.ref_key)
            if not grava_id:
                continue
            seq = plane_state.ref_to_sequence_id.get(op.ref_key)
            plane_uuid = plane_state.ref_to_uuid.get(op.ref_key)
            report.grava_created.append({
                "op_index": idx,
                "ref_key": op.ref_key,
                "grava_id": grava_id,
                "node_kind": op.node_kind,
                "plane_uuid": plane_uuid,
                "plane_seq_id": seq,
                "priority": None,
                "from_state": True,
            })

    for idx in sorted(completed):
        if idx >= len(plan.plane_ops):
            continue
        op = plan.plane_ops[idx]
        if isinstance(op, CreateWorkItem) and op.ref_key in state.ref_to_grava_id:
            create_order.append((idx, op.ref_key, state.ref_to_grava_id[op.ref_key]))

    try:
        for idx, op in enumerate(plan.plane_ops):
            if idx in completed:
                continue
            if not isinstance(op, CreateWorkItem):
                # Phase 3 only mirrors creates. Plane comments + description
                # updates from Phase 2 stay on the Plane side.
                completed.add(idx)
                state.completed_op_indices = sorted(completed)
                _atomic_write_state(state, state_path)
                continue

            _dispatch_create_or_update(
                op, idx, plane_state, state, plan,
                client, project_id, project_identifier, workspace, spec_page_url,
                target_repo, actor, run_subprocess,
                report, create_order,
            )
            completed.add(idx)
            state.completed_op_indices = sorted(completed)
            _atomic_write_state(state, state_path)

        # Comment-back to Plane for newly-created issues only.
        commented = set(state.plane_comments_posted)
        for idx, ref_key, grava_id in create_order:
            if ref_key in commented:
                continue
            plane_uuid = plane_state.ref_to_uuid.get(ref_key)
            if not plane_uuid:
                continue
            resp = client.add_comment(project_id, plane_uuid, _comment_html(grava_id))
            commented.add(ref_key)
            state.plane_comments_posted = sorted(commented)
            report.plane_comments.append({
                "ref_key": ref_key,
                "target_uuid": plane_uuid,
                "comment_id": resp.get("id"),
                "source": "grava_mirror",
            })
            _atomic_write_state(state, state_path)

        # Apply Grava dep edges (mirrors the analyzer's epic dependency graph).
        # Edge semantics: `src blocks dst`, so `dst` cannot start until `src`
        # is done. Run after creates+comments so all Grava IDs are resolved.
        if dep_edges:
            _apply_dep_edges(
                dep_edges, plan, state, report, target_repo,
                actor, run_subprocess, state_path,
            )

        commit_msg = (
            f"task-generator: mirror Plane page {plane_state.page_id} "
            f"(run {state.run_id})"
        )
        try:
            commit_resp = _run_grava(
                ["commit", "-m", commit_msg],
                cwd=target_repo, actor=actor, runner=run_subprocess,
            )
            commit_hash = commit_resp.get("hash") if isinstance(commit_resp, dict) else None
        except RuntimeError as exc:
            commit_hash = None
            # Grava auto-commits per command, so the trailing commit is often a
            # no-op ("nothing to commit"). Treat that as success.
            if "nothing to commit" in str(exc).lower():
                print("[grava_writer] commit: nothing to commit (Grava auto-commits per op).", file=sys.stderr)
            else:
                print(f"[grava_writer] commit failed (non-fatal): {exc}", file=sys.stderr)

        state.grava_commit_hash = commit_hash
        report.grava_commit_hash = commit_hash
        state.failed_op_index = None
        state.failure_detail = None
        _atomic_write_state(state, state_path)
        report.finished_at = _now_iso()
        _write_report(report, report_path)
        return report

    except Exception as exc:  # noqa: BLE001
        return _handle_failure(
            exc, plan, target_repo, state, report,
            create_order, state_path, report_path,
            on_failure, input_fn, actor, run_subprocess,
        )


def _dispatch_create_or_update(
    op: CreateWorkItem,
    idx: int,
    plane_state: RunState,
    state: GravaState,
    plan: RunPlan,
    client,
    project_id: str,
    project_identifier: str,
    workspace: str,
    spec_page_url: str,
    target_repo: Path,
    actor: str,
    run_subprocess: Callable,
    report: RunReport,
    create_order: list[tuple[int, str, str]],
) -> None:
    seq = plane_state.ref_to_sequence_id.get(op.ref_key)
    plane_uuid = plane_state.ref_to_uuid.get(op.ref_key)
    if not seq or not plane_uuid:
        raise RuntimeError(
            f"Op {idx} ({op.ref_key}): missing Plane sequence_id or uuid in state."
        )

    wi = client.get_work_item(project_id, plane_uuid)
    title = wi.get("name") or op.title
    desc_body = _strip_html(wi.get("description_html") or op.description_html)
    priority = _map_priority(wi.get("priority"))

    own_url = _plane_url(workspace, project_identifier, seq)
    epic_ref, story_ref = _resolve_ancestors(op.ref_key)
    epic_seq = plane_state.ref_to_sequence_id.get(epic_ref) if epic_ref else None
    story_seq = plane_state.ref_to_sequence_id.get(story_ref) if story_ref else None
    epic_url = (
        _plane_url(workspace, project_identifier, epic_seq)
        if epic_seq is not None
        else None
    )
    story_url = (
        _plane_url(workspace, project_identifier, story_seq)
        if story_seq is not None
        else None
    )

    description = _compose_grava_desc(
        own_url=own_url,
        epic_url=epic_url if op.node_kind != "epic" else None,
        story_url=story_url if op.node_kind == "task" else None,
        spec_url=spec_page_url if op.node_kind == "task" else None,
        body=desc_body,
    )

    label = f"plane:{seq}"
    existing = _grava_search_by_label(label, cwd=target_repo, actor=actor, runner=run_subprocess)

    if len(existing) >= 2:
        report.grava_anomalies.append({
            "op_index": idx,
            "ref_key": op.ref_key,
            "plane_seq": seq,
            "matched_grava_ids": [e.get("id") for e in existing],
            "reason": f"Multiple Grava issues carry the same {label} label; skipping.",
        })
        print(
            f"[grava_writer] anomaly: {len(existing)} matches for label '{label}' "
            f"(ref_key={op.ref_key}); skipping.",
            file=sys.stderr,
        )
        return

    if len(existing) == 1:
        grava_id = existing[0]["id"]
        existing_title = existing[0].get("title") or ""
        existing_desc = existing[0].get("description") or existing[0].get("desc") or ""
        existing_priority_str = _grava_priority_to_str(existing[0].get("priority"))

        fields_changed: list[str] = []
        update_args = ["update", grava_id]
        if title != existing_title:
            update_args += ["-t", title]
            fields_changed.append("title")
        if description != existing_desc:
            update_args += ["-d", description]
            fields_changed.append("desc")
        if priority != existing_priority_str:
            update_args += ["-p", priority]
            fields_changed.append("priority")

        if fields_changed:
            _run_grava(update_args, cwd=target_repo, actor=actor, runner=run_subprocess)
        state.ref_to_grava_id[op.ref_key] = grava_id
        report.grava_updated.append({
            "op_index": idx,
            "ref_key": op.ref_key,
            "grava_id": grava_id,
            "fields_changed": fields_changed,
        })
        return

    if op.node_kind == "epic":
        create_args = ["create", "-t", title, "-d", description, "--type", "epic", "-p", priority]
    else:
        parent_grava_id = state.ref_to_grava_id.get(op.parent_ref or "")
        if not parent_grava_id:
            raise RuntimeError(
                f"Op {idx} ({op.ref_key}): parent_ref {op.parent_ref!r} unresolved in Grava."
            )
        grava_type = "story" if op.node_kind == "story" else "task"
        create_args = [
            "subtask", parent_grava_id,
            "-t", title, "-d", description,
            "--type", grava_type, "-p", priority,
        ]

    resp = _run_grava(create_args, cwd=target_repo, actor=actor, runner=run_subprocess)
    if not isinstance(resp, dict):
        raise RuntimeError(f"Op {idx} grava create: unexpected response shape {resp!r}")
    grava_id = resp.get("id")
    if not grava_id:
        raise RuntimeError(f"Op {idx} grava create response missing 'id': {resp!r}")
    state.ref_to_grava_id[op.ref_key] = grava_id
    create_order.append((idx, op.ref_key, grava_id))

    label_args = ["label", grava_id, "--add", f"plane:{seq}"]
    if op.node_kind in ("story", "task") and epic_seq is not None:
        label_args += ["--add", f"plane-epic:{epic_seq}"]
    if op.node_kind == "task" and story_seq is not None:
        label_args += ["--add", f"plane-story:{story_seq}"]
    _run_grava(label_args, cwd=target_repo, actor=actor, runner=run_subprocess)

    report.grava_created.append({
        "op_index": idx,
        "ref_key": op.ref_key,
        "grava_id": grava_id,
        "node_kind": op.node_kind,
        "plane_uuid": plane_uuid,
        "plane_seq_id": seq,
        "priority": priority,
    })


_DUPLICATE_DEP_RE = re.compile(r"duplicate primary key", re.IGNORECASE)


def _edge_key(src_ref: str, dst_ref: str, kind: str) -> str:
    return f"{src_ref}->{dst_ref}:{kind}"


def _apply_dep_edges(
    dep_edges: list[dict],
    plan: RunPlan,
    state: GravaState,
    report: RunReport,
    target_repo: Path,
    actor: str,
    run_subprocess: Callable,
    state_path: Path,
) -> None:
    """Walk dep_edges, post `grava dep <src> <dst> --type blocks` for each.

    Idempotent: a duplicate-primary-key error from Grava is treated as
    success and recorded in `state.dep_edges_posted` so resume runs skip it.
    Skips edges whose src or dst grava_id is unknown (e.g. anomaly skip on
    the create side) and surfaces the reason in `report.grava_deps_skipped`.
    """
    posted = set(state.dep_edges_posted)
    for edge in dep_edges:
        src_ref = edge.get("src_ref_key", "")
        dst_ref = edge.get("dst_ref_key", "")
        kind = edge.get("type", "blocks")
        key = _edge_key(src_ref, dst_ref, kind)
        if key in posted:
            continue
        src_id = state.ref_to_grava_id.get(src_ref)
        dst_id = state.ref_to_grava_id.get(dst_ref)
        if not src_id or not dst_id:
            report.grava_deps_skipped.append({
                "src_ref_key": src_ref,
                "dst_ref_key": dst_ref,
                "type": kind,
                "reason": (
                    f"unresolved grava id (src={src_id or 'missing'} "
                    f"dst={dst_id or 'missing'}); likely anomaly on create side."
                ),
            })
            continue

        try:
            resp = _run_grava(
                ["dep", src_id, dst_id, "--type", kind],
                cwd=target_repo, actor=actor, runner=run_subprocess,
            )
            created = True
        except RuntimeError as exc:
            if _DUPLICATE_DEP_RE.search(str(exc)):
                # Already-existing edge — treat as no-op success.
                resp = {"status": "exists", "from_id": src_id, "to_id": dst_id, "type": kind}
                created = False
            else:
                raise

        posted.add(key)
        state.dep_edges_posted = sorted(posted)
        report.grava_deps_created.append({
            "src_ref_key": src_ref,
            "dst_ref_key": dst_ref,
            "src_grava_id": src_id,
            "dst_grava_id": dst_id,
            "type": kind,
            "raw_ref": edge.get("raw_ref"),
            "source": edge.get("source"),
            "created": created,
        })
        _atomic_write_state(state, state_path)


def _resolve_ancestors(ref_key: str) -> tuple[str | None, str | None]:
    """Given a ref_key like 'task:1.2.3', return (epic_ref, story_ref).

    For 'epic:N': (None, None).
    For 'story:N.M': ('epic:N', None).
    For 'task:N.M.K': ('epic:N', 'story:N.M').
    """
    if ref_key.startswith("epic:"):
        return None, None
    if ref_key.startswith("story:"):
        rest = ref_key[len("story:"):]
        epic_idx = rest.split(".", 1)[0]
        return f"epic:{epic_idx}", None
    if ref_key.startswith("task:"):
        rest = ref_key[len("task:"):]
        parts = rest.split(".")
        if len(parts) >= 2:
            return f"epic:{parts[0]}", f"story:{parts[0]}.{parts[1]}"
    return None, None


def _grava_priority_to_str(value: Any) -> str:
    if value is None:
        return "medium"
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, int):
        return {0: "critical", 1: "high", 2: "medium", 3: "low", 4: "backlog"}.get(value, "medium")
    return "medium"


def _report_from_dict(d: dict) -> RunReport:
    valid = {f.name for f in dataclasses.fields(RunReport)}
    return RunReport(**{k: v for k, v in d.items() if k in valid})


def _handle_failure(
    exc: Exception,
    plan: RunPlan,
    target_repo: Path,
    state: GravaState,
    report: RunReport,
    create_order: list[tuple[int, str, str]],
    state_path: Path,
    report_path: Path,
    on_failure: str,
    input_fn,
    actor: str,
    run_subprocess: Callable,
) -> RunReport:
    failed_idx = next(
        (i for i in range(len(plan.plane_ops)) if i not in state.completed_op_indices),
        None,
    )
    state.failed_op_index = failed_idx
    state.failure_detail = str(exc)
    _atomic_write_state(state, state_path)

    report.failed_op = {
        "index": failed_idx,
        "detail": str(exc),
        "exc_type": type(exc).__name__,
        "phase": "grava",
    }
    print(
        f"[grava_writer] FAILED at op {failed_idx}: {exc}",
        file=sys.stderr,
    )

    decision = on_failure
    if on_failure == "prompt":
        n_creates = len(create_order)
        msg = (
            f"\nFailed at op {failed_idx}. {n_creates} Grava issue(s) already created.\n"
            f"Rollback (drop in reverse)? [y/N]: "
        )
        try:
            answer = input_fn(msg).strip().lower()
        except EOFError:
            answer = ""
        decision = "rollback" if answer == "y" else "abort"

    if decision == "rollback":
        _rollback(target_repo, create_order, report, actor, run_subprocess)
        state.rolled_back = True
        _atomic_write_state(state, state_path)

    report.finished_at = _now_iso()
    _write_report(report, report_path)
    return report


def _rollback(
    target_repo: Path,
    create_order: list[tuple[int, str, str]],
    report: RunReport,
    actor: str,
    run_subprocess: Callable,
) -> None:
    deleted = 0
    failed_drops = []
    for idx, ref_key, grava_id in reversed(create_order):
        try:
            _run_grava(
                ["drop", grava_id, "--force"],
                cwd=target_repo, actor=actor, runner=run_subprocess,
            )
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            failed_drops.append({"ref_key": ref_key, "grava_id": grava_id, "detail": str(exc)})
            print(
                f"[grava_writer] rollback: drop failed for {ref_key} ({grava_id}): {exc}",
                file=sys.stderr,
            )
    report.rolled_back = not failed_drops
    if failed_drops and report.failed_op is not None:
        report.failed_op["rollback_failures"] = failed_drops
    print(
        f"[grava_writer] rollback complete: dropped {deleted}/{len(create_order)} items",
        file=sys.stderr,
    )
