# Generator Agent

Turns a source document (markdown today) into reviewable spec drafts under `drafts/<system>/`. Never writes to Plane or grava; the operator promotes a draft into `systems/<Name>/business/` by hand.

**Status:** Phase A — scaffold only. CLI commands return "phase A scaffold" until real implementation lands.

## Pipeline

```
source.md ──extract──> extract.json ──outline──> outline.json ──render──> drafts/<sys>/*.md
                                       (Phase D                   (Phase E)
                                        deferred —
                                        manual via
                                        Claude Code session)
```

## Operator entry point (Phase E onwards)

```bash
se generate <source.md> --project <name> [--llm | --no-llm | --dry-run | --step extract|outline|render]
```

Defaults are offline — `--llm` is required to call Anthropic. Phase D (LLM) is deferred until API budget exists; the interim outline path is manual via a Claude Code session.

## Hard limits

- NEVER call Plane API (use `upload_project_pages.py`).
- NEVER call grava (use `task-generator`).
- NEVER auto-promote a draft into `systems/`.
- NEVER bypass the `--llm` gate — default mode produces `extract.json` only.

## See also

- [docs/generator/plan.md](../../docs/generator/plan.md) — phase-by-phase implementation plan.
- [docs/task-generator/parser.md](../../docs/task-generator/parser.md) — downstream parser; render output must match its hierarchy rules.
