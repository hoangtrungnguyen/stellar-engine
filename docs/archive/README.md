# Archived docs

Historical design documents kept for reference. **Not authoritative.** The current state lives in the code and the active `docs/` tree.

## task-generator/

Pre-implementation design specs for `agents/task-generator/`, archived on 2026-05-22. Predate Phase 2 (May 18 originals); the agent is now at Phase 6 with three-phase preview/Plane/Grava flow, per-turn operator approval, epic dependencies via `dependency_analyzer.py`, and CLI entry via `se taskgen` / `agents/task-generator/cli/run.py` — none of which match these docs. Notable drifts:

- Docs reference `runner.py` at package root; actual entry is `agents/task-generator/cli/run.py`.
- Docs name `reconciler.py`; actual file is `reconcile.py`.
- Docs claim the parser "expects exactly one H2 per spec; warn if more than one"; `parser.py:103-105` returns a list of epics, one per H2, and warns only when **no** H2 is present.
- No mention of `dependency_analyzer.py` (Phase 6 epic-deps).
- Phase mapping covers Phases 1–4 only.

Authoritative replacements for the routing / format contract previously in `parser.md`:

- `agents/generator/AGENT.md` — "Output format" + "Routing rules" sections (story-level AC + UI/UX H4 routing rules, the rendered draft shape that `task-generator/parser.py` consumes).
- `agents/task-generator/parser.py` — the code itself.

## generator/

Implementation plan + operator walkthrough + epic-dependencies authoring guide for `agents/generator/`, archived on 2026-05-22. All phases (A, B, E, F, G) shipped; Phase D (LLM outline) remains deferred. Authoritative replacements:

- `agents/generator/README.md` — quick-start, operator entry, output format, hard limits.
- `agents/generator/AGENT.md` — agent prompt, failure-modes table, routing rules.
- `agents/generator/` code — ground truth for all CLI flags and exit codes.

## grava-plane-status-sync-plan.md

Original v0 planning artifact for the grava → Plane status sync feature, archived on 2026-05-23. The feature has shipped as `agents/task-generator/cli/grava_plane_sync.py` (not the proposed `sync_plane_status.py` name in the plan). Authoritative replacements:

- `docs/cli/se-plane-sync.md` — command reference (flags, modes, exit codes, examples).
- `docs/grava-plane-sync-setup.md` — operator setup (`STELLAR_ENGINE_HOME`, shell profile, hook verification).
- `agents/task-generator/cli/grava_plane_sync.py` — the shipped implementation.
