# task-generator Detailed Plan — moved

This single-file plan has been split for easier maintenance. See [`task-generator/`](task-generator/README.md) for the new structure:

- [README](task-generator/README.md) — index, file layout, deliverables, next step.
- [data-model](task-generator/data-model.md) — IR, `RunPlan`, `RunReport`, `repo-map.yaml`.
- [plane-client](task-generator/plane-client.md) — REST client surface and conventions.
- [parser](task-generator/parser.md) — HTML → Markdown → IR pipeline and mapping rules.
- [planner](task-generator/planner.md) — planner ordering plus the reconciler / idempotency path.
- [writers](task-generator/writers.md) — `plane_writer` (Phase 2) and `grava_writer` (Phase 3).
- [runner](task-generator/runner.md) — CLI flags and 12-step phase order.
- [testing-and-phases](task-generator/testing-and-phases.md) — test plan, Phase 1–4 mapping, open implementation questions.

The strategy doc remains at [`task-generator-strategy-bullets.md`](task-generator-strategy-bullets.md).
