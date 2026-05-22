# Runner / CLI

`agents/task-generator/runner.py` is the CLI entry point that orchestrates phases.

## Invocation

```
task-generator <project_id> <page_id> [options]

Options:
  --dry-run             Preview only; write Markdown preview and exit.
  --target-repo PATH    Override the repo-map lookup.
  --no-grava            Skip Phase 3.
  --json-report PATH    Override default report path (default: runs/<ts>.json).
  --yes                 Skip interactive confirmation (CI mode).
```

## Phase Order

1. **Load credentials** — `~/.config/plane/config.json`, with env-var override (`PLANE_API_TOKEN`, `PLANE_HOST`, `PLANE_WORKSPACE`).
2. **Resolve target repo** — via [`repo-map.yaml`](data-model.md#repo-mapyaml) lookup, or `--target-repo` override.
3. **Fetch page** — `client.get_page()` → HTML → Markdown via `markdownify`.
4. **Parse** — `parser.parse()` → IR (see [parser.md](parser.md)).
5. **Plan** — `planner.plan()` → preview, warnings, ordered ops (see [planner.md](planner.md)).
6. **Reconcile** — only if existing items reference this spec page (Phase 4).
7. **Surface** — print preview path + warning count + orphan count.
8. **Dry-run exit** — if `--dry-run`, exit 0.
9. **Confirm** — interactive prompt, skipped when `--yes`.
10. **Plane writes** — `plane_writer.execute()`.
11. **Grava writes** — `grava_writer.execute()` unless `--no-grava`.
12. **Report** — write JSON report to `runs/<timestamp>.json` (or `--json-report` path).

## See Also

- [data-model.md](data-model.md) — `RunReport` shape, repo-map.yaml.
- [planner.md](planner.md) — preview rendering, reconciler trigger.
- [writers.md](writers.md) — Plane and Grava execution.
- [testing-and-phases.md](testing-and-phases.md) — what each phase delivers.
