# Testing, Phase Mapping, Open Questions

## Test Plan

### Unit — parser.py

- Empty H2 (no H3 children) → epic with zero stories, no warning.
- Stray H3 before any H2 → `ParseWarning("orphan story 'Foo'")`.
- "Out of scope" section under an H2 → entirely skipped.
- "Open questions" H3 with three bullets → `epic.open_questions` has three entries.
- Cross-reference regex matches `STELLAR-12`, `(STELLAR-12)`, and `STELLAR-12, STELLAR-15` (both as separate matches).
- Fenced code block containing `## Fake epic` → does not produce a phantom epic.
- Inline marker `Bug: payment hangs` → title `payment hangs`, `type_marker="Bug"`.

### Unit — planner.py

- Missing required type (e.g. `epic`) in `list_work_item_types` → planner raises a clear error before any writes.
- A label referenced by IR but not in `list_labels` → planner queues a `CreateLabel` op ahead of any `CreateWorkItem`.
- "Related:" line ops are queued only for issues with non-empty `related_refs`.

### Integration — Phase 2 smoke

- Throwaway Plane project + a hand-crafted spec page with one epic, two stories, three tasks, one "Open questions" section, one "Out of scope" section.
- Run end-to-end, assert: 1 epic + 2 stories + 3 tasks created; 1 epic comment; "Out of scope" content absent from any issue.

### Integration — Phase 4 idempotency

- Re-run the same command against the same spec page → zero new issues, zero patches (everything matches), exit 0.
- Edit one task title in the spec, re-run → preview shows a single `UpdateWorkItem` diff; user confirms; one PATCH applied.
- Remove a task from the spec, re-run → preview shows one orphan; no DELETE issued.

## Phase Mapping

Matches strategy §4.

### Phase 1 — Skeleton + dry-run

- **Build:** `plane_client.py` (read-only methods only), `parser.py`, `ir.py`, `planner.py`, `runner.py` with `--dry-run` working end-to-end.
- **Stub:** `plane_writer.py` and `grava_writer.py` raise `NotImplementedError`.
- **Validate:** hand-review preview Markdown against 2–3 real spec pages.

### Phase 2 — Plane writes

- **Implement:** write methods in `plane_client.py`; `plane_writer.py`.
- **Validate:** throwaway Plane project + smoke spec → assert hierarchy matches.

### Phase 3 — Grava mirror

- **Implement:** `grava_writer.py`.
- **Validate:** end-to-end against a scratch repo.

### Phase 4 — Hardening

- **Implement:** `reconciler.py`; backoff in `plane_client.py`; orphan reporting in `runner.py`.
- **Validate:** idempotency runs; orphan flagging without deletion; rollback rehearsal.

## Open Implementation Questions

- **`repo-map.yaml` location** — proposing `stellar-engine/repo-map.yaml` (sibling to `CLAUDE.md`). Confirm before committing.
- **Comment granularity** — single bulk comment per epic section ("Open questions: …"), or one comment per bullet? Proposing one bulk comment per section to keep epic comments scannable.
- **"Related:" line format inside descriptions** — proposing a fenced block at the bottom: `<!-- task-generator:related -->\nRelated: STELLAR-12, STELLAR-15\n<!-- /task-generator:related -->`. Sentinels make idempotency diffs trivial when Plane ships native relations.
- **Preview filename** — proposing `<spec-slug>-<YYYYMMDD-HHMMSS>.preview.md` so re-runs don't overwrite history.
- **HTML→Markdown converter pin** — `markdownify==0.13.x`; document in `agents/task-generator/requirements.txt`.

## See Also

- [README.md](README.md) — index, file layout, deliverables.
- [planner.md](planner.md) — reconciler details for the idempotency tests.
- [writers.md](writers.md) — rollback semantics for the failure-path tests.
