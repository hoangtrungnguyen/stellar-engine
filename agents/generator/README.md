# Generator Agent

Turn a markdown source document into reviewable spec drafts under `drafts/<project>/runs/<RID>/`. The agent never writes to Plane or grava — promotion into `systems/<Name>/business/` is a manual operator step after review.

**Status:** Phases A + B + E + F + G shipped. Phase D (LLM outline) is deferred — the outline step today runs manually via a Claude Code session.

See also:
- [AGENT.md](AGENT.md) — agent prompt + hard limits + failure-modes table (Claude reads this when invoked as a sub-agent).
- [../../docs/generator/plan.md](../../docs/generator/plan.md) — phase-by-phase implementation plan + status.
- [../../docs/generator/usage.md](../../docs/generator/usage.md) — full operator walkthrough (markdown → Plane → grava).

## Quick start

```bash
# 1. Extract — produce extract.json under drafts/<project>/runs/<RID>/
se generate path/to/spec.md --project DEMO --no-llm

# 2. Outline — manual today (Phase D deferred). In a Claude Code session,
#    paste the contents of extract.json and ask Claude to produce an
#    outline.json matching the D2 schema (docs/generator/plan.md §Phase D).
#    Save the result into drafts/DEMO/runs/<RID>/outline.json.

# 3. Render — emit one *.md per epic under drafts/DEMO/runs/<RID>/drafts/
se generate path/to/spec.md --project DEMO --step render --system-name "Demo"
```

## Operator entry

```bash
se generate <source.md> --project <name>                       # default: offline, stops after extract
se generate <source.md> --project <name> --dry-run             # same as default; extract only
se generate <source.md> --project <name> --no-llm              # explicit offline; extract only
se generate <source.md> --project <name> --llm                 # Phase D — currently refused with pointer
se generate <source.md> --project <name> --step extract        # single-step: extract only
se generate <source.md> --project <name> --step outline        # no-op today (Phase D deferred)
se generate <source.md> --project <name> --step render         # render only (needs outline.json)
se generate <source.md> --project <name> --system-name "Foo"   # override H1 (default: --project value)
se generate <source.md> --project <name> --run-id RID-1        # override timestamp run id
```

`cli/run.py` is the internal implementation; `se generate` wraps it. Both accept the same flags.

## Output structure

Every run lands under `drafts/<project>/runs/<RID>/`:

```
drafts/DEMO/runs/20260516T120937Z/
├── run.json           # run metadata (project, source, started_at)
├── extract.json       # Section IR from the markdown parser
├── outline.json       # epic/story/task hierarchy (hand-written or LLM)
├── drafts/            # one *.md per epic
│   ├── 2026-05-16-court-booking.md
│   └── 2026-05-16-cancellations.md
├── manifest.json      # list of emitted drafts + confidence
└── diff.json          # structured diff vs latest prior run (only when one exists)
```

`drafts/` is `.gitignore`d — runs are operator-local.

## Output format

Each rendered draft has YAML frontmatter and a body shaped by [docs/generator/plan.md §E1](../../docs/generator/plan.md) and consumed by [docs/task-generator/parser.md](../../docs/task-generator/parser.md):

```markdown
---
generator_source: path/to/spec.md
generator_run_id: 20260516T120937Z
generator_confidence: 0.78
generator_model: manual-claude-code
generator_model_version: n/a
---
# <system name>

## <Epic title>

<epic summary>

**UI/UX Design:**            ← rendered iff epic.design_links non-empty
- [Label](https://figma.com/x)
- design/mock.png

### <Story title>
> Depends on: <ref>          ← rendered iff story.depends_on non-empty

**Acceptance Criteria:**     ← rendered iff story.acceptance_criteria non-empty
- AC bullet 1
- AC bullet 2

#### <Task title>            ← optional, when stories sub-divide
- task AC bullet
```

## Diff on re-run

When a prior run for the same source exists under `drafts/<project>/runs/`, the chain computes a structured diff (epics/stories/tasks added/removed/renamed) before writing new drafts. The diff is printed to stdout and persisted as `diff.json`. The walk-back skips runs that stopped before producing an `outline.json` (e.g. `--dry-run` leftovers), so it always compares against the most recent fully-rendered sibling.

## Doctor

`se doctor` reports generator health:

```bash
python3 cli/se doctor --dir .
# ✓ generator: package  <path>/agents/generator
# ✓ python: markdown    ...
# ✓ python: markdownify ...
# ⚠ python: anthropic   Phase D (LLM outline) deferred
# ⚠ python: pymupdf     PDF frontend deferred
# ⚠ generator: drafts/  not present — created on first `se generate` run
# ✓ .env                <path>/.env
```

## Hard limits

- NEVER call Plane API (use `upload_project_pages.py` after promotion).
- NEVER call grava (use `task-generator` after promotion).
- NEVER auto-promote a draft into `systems/<Name>/business/`.
- NEVER bypass the `--llm` gate (default mode is offline).
- NEVER commit `drafts/` — it stays operator-local.

Full limits + failure-modes table: [AGENT.md](AGENT.md).
