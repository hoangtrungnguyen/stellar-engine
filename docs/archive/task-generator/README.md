# task-generator Detailed Plan

Implementation companion to [`../task-generator-strategy-bullets.md`](../task-generator-strategy-bullets.md). The strategy doc resolves *what* and *why*; the docs in this folder cover *how* — file layout, function shapes, request payloads, parser rules, test cases.

## Index

1. [data-model.md](data-model.md) — IR dataclasses (`EpicNode` / `StoryNode` / `TaskNode`), `RunPlan`, `RunReport`, and the `repo-map.yaml` shape.
2. [plane-client.md](plane-client.md) — REST client method signatures, auth, retry, error handling.
3. [parser.md](parser.md) — HTML → Markdown → IR pipeline; mapping rules; warning behaviour.
4. [planner.md](planner.md) — planner ordering, op shapes, "Related:" deferral, reconciler / idempotency.
5. [writers.md](writers.md) — `plane_writer` (Phase 2) and `grava_writer` (Phase 3); rollback semantics.
6. [runner.md](runner.md) — CLI flags and 12-step phase order.
7. [testing-and-phases.md](testing-and-phases.md) — test plan, phase mapping, open implementation questions.

## File Layout

```
stellar-engine/
├── agents/
│   └── task-generator/
│       ├── AGENT.md              # System prompt for the sub-agent
│       ├── README.md             # Operator guide (env vars, invocation, troubleshooting)
│       ├── plane_client.py       # REST client (work items, pages, comments, types, labels)
│       ├── parser.py             # HTML → Markdown → IR (epic/story/task tree)
│       ├── ir.py                 # Dataclasses for the parsed tree and run report
│       ├── planner.py            # IR → ordered list of write ops + preview Markdown
│       ├── plane_writer.py       # Phase 2: executes Plane ops; tracks IDs for rollback
│       ├── grava_writer.py       # Phase 3: mirrors hierarchy in target repo
│       ├── reconciler.py         # Phase 4: diff existing items against planned writes
│       ├── repo_map.py           # Plane project UUID → target repo path lookup
│       ├── runner.py             # CLI entry point; orchestrates phases
│       └── tests/
│           ├── fixtures/         # Sample spec pages and expected IRs
│           └── test_parser.py
├── docs/
│   ├── task-generator-strategy-bullets.md
│   └── task-generator/           # This folder
└── repo-map.yaml                 # Plane project UUID → repo path mapping
```

## Deliverables

- `agents/task-generator/AGENT.md` — sub-agent system prompt.
- `agents/task-generator/README.md` — operator guide.
- `docs/task-generator-smoke-test.md` — transcript from Phase 4 validation.

## Next Step

Begin Phase 1 implementation. Start with `parser.py` plus its fixtures, since the parser is the riskiest component to validate and unblocks everything downstream.
