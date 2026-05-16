# Generator Agent — Implementation Plan

**Status:** Phase A ✅ · Phase B ✅ · Phase E ✅ · Phase F ✅ · Phase G ✅ (D deferred) · **Last updated:** 2026-05-16

This plan covers the **CLI scaffold + minimal markdown extract/render MVP** for the Generator agent — enough to take one markdown source file and emit one spec draft, end-to-end. The agent translates a document into reviewable spec markdown files under `drafts/<system>/`; it never writes to Plane or grava directly.

---

## 1. Context

`docs/stellar-engine/plan.md` §4 Phase F (Generator) was deferred without detail. This sub-plan turns that into concrete sequencing.

Scope cuts:
- **Input:** one markdown file. PDF / URLs / codebases / transcripts all deferred.
- **Output:** one or more spec markdown files under `drafts/<system-name>/`. No Plane writes, no grava writes.
- **LLM:** Anthropic SDK direct, single Sonnet call per outline, temperature 0.
- **Promotion:** operator copies a draft into `systems/<Name>/business/` by hand. Not automated.

What this plan does NOT cover (deferred):
- PDF frontend (was Phase C; revisit when a real PDF source-doc workflow is needed).
- URL / transcript / codebase frontends.
- Draft staleness doctor checks.
- task-generator extension to strip `generator_*` frontmatter (operator strips manually for now).
- Multi-document synthesis (one source doc per run).
- Bidirectional sync between draft and source (source changes → re-run).
- Auto-promotion of drafts to `systems/`.

---

## 2. Inventory

### 2.1 Existing (no Generator code yet)

| Path | Relevance |
|:---|:---|
| `agents/task-generator/` | Layout template; mirror naming conventions, CLI structure, tests style |
| `agents/task-generator/parser.py` | Downstream consumer of Generator output; must parse rendered drafts cleanly |
| `agents/task-generator/cli/resolve_repo.py` | Pattern for resolving system → directory |
| `agents/orchestrator/tests/conftest.py` | Test-fixture style to reuse |
| `setup.sh` | Will need `anthropic` added to pip install line when Phase D lands |
| `docs/stellar-engine/plan.md` §4 Phase F | Notes Generator is unbuilt; will mark this sub-plan as the owner |

### 2.2 To be built

| Path | Function |
|:---|:---|
| `agents/generator/__init__.py` | Package marker |
| `agents/generator/AGENT.md` | Agent prompt: invocation pattern, hard limits, approval gates |
| `agents/generator/requirements.txt` | `anthropic>=0.40` (deferred until Phase D) |
| `agents/generator/llm_client.py` | Thin Anthropic SDK wrapper (deferred) |
| `agents/generator/ir.py` | Intermediate representation dataclasses |
| `agents/generator/parser/__init__.py` | Markdown dispatcher (PDF deferred) |
| `agents/generator/parser/markdown.py` | `*.md` → IR |
| `agents/generator/outline.py` | IR → hierarchy via LLM |
| `agents/generator/render.py` | Hierarchy → markdown draft files |
| `agents/generator/cli/__init__.py` | Package marker |
| `agents/generator/cli/init_run.py` | Provision `drafts/<sys>/runs/<run_id>/` |
| `agents/generator/cli/extract.py` | Run parser, write `extract.json` |
| `agents/generator/cli/outline.py` | Run outline, write `outline.json` |
| `agents/generator/cli/render.py` | Run render, write `*.md` + `manifest.json` |
| `agents/generator/cli/run.py` | One-shot orchestrator chaining the three |
| `agents/generator/tests/__init__.py` | Test package marker |
| `agents/generator/tests/conftest.py` | sys.path + fixtures (mirror orchestrator tests) |
| `agents/generator/tests/test_*.py` | Unit tests per module |
| `agents/generator/tests/fixtures/sample.md` | Fixture input for parser + render tests |
| `agents/generator/tests/fixtures/sample_outline.json` | Fixed outline fixture for render tests (no LLM needed) |
| `setup.sh` edit | Add new deps to install line |
| `docs/stellar-engine/plan.md` edit | Reference this sub-plan from Phase F |

---

## 3. Gaps

### G_Gen_1. No agent directory exists
`agents/generator/` is empty. Every file in §2.2 is new.

### G_Gen_2. No LLM credential plumbing
`agents/task-generator/` uses Plane creds; nothing in the repo loads `ANTHROPIC_API_KEY`. New `llm_client.py` must handle this.

### G_Gen_4. No `drafts/` convention
The directory does not exist yet; `.gitignore` does not exclude it. Drafts should be operator-local, not committed by default.

### G_Gen_5. No structured diff on re-run
Source docs change over time. Byte-identical comparison against a static golden file breaks on every legitimate edit. The gap is the absence of snapshot storage + diff surfacing: when the same source is re-run, the operator needs to see what changed (sections added/removed/renamed) before deciding whether to promote the new draft.

---

## 4. Plan

### Phase A — Scaffold (no LLM, no PDF yet) — ✅ DONE (2026-05-16)

> Landed: `agents/generator/` directory tree, IR dataclasses, llm_client stub, markdown-parser stub, 5 CLI argparse skeletons, 20 scaffold tests (8 IR round-trip + 12 CLI smoke). All green: `pytest agents/generator/tests/` → 20 passed.

**A1. Create the directory tree.** ✅
- `agents/generator/{__init__.py, AGENT.md, ir.py, llm_client.py, requirements.txt}`
- `agents/generator/parser/{__init__.py, markdown.py}` (PDF deferred)
- `agents/generator/cli/{__init__.py, init_run.py, extract.py, outline.py, render.py, run.py}`
- `agents/generator/tests/{__init__.py, conftest.py}`

**A2. Define IR dataclasses (`ir.py`).** ✅ Source IR (`Heading`/`Block`/`Section`) + Outline IR (`Epic`/`Story`/`Task`/`DesignLink`/`Outline`) with `section_from_dict` / `outline_from_dict` round-trip helpers.
```python
@dataclass
class Heading:
    level: int          # 1..6
    text: str
    anchor: str         # source-doc anchor (line number or PDF page+y)

@dataclass
class Block:
    kind: str           # "paragraph" | "list" | "code" | "table"
    text: str
    anchor: str

@dataclass
class Section:
    heading: Heading
    blocks: list[Block]
    children: list["Section"]
```

**A3. CLI argparse skeletons.** ✅ All 5 scripts (`init_run`, `extract`, `outline`, `render`, `run`) expose `build_parser()` + `main(argv)`, document exit codes, and return 0 after printing `"phase A scaffold"`.

**A4. Tests for A1–A3.** ✅
- `tests/test_ir.py` — 8 round-trip tests including parametrised `confidence`.
- `tests/test_cli_smoke.py` — 12 tests: `--help` exit 0, happy-path scaffold output, mutually-exclusive `--llm`/`--no-llm`/`--dry-run`, `--step` choices.

**Verify:** ✅ `pytest agents/generator/tests/` → **20 passed in 0.03s**; each `python3 agents/generator/cli/*.py --help` prints usage and exits 0.

### Phase B — Markdown frontend (no LLM yet) — ✅ DONE (2026-05-16)

> Landed: hand-rolled line walker (no external markdown lib needed — Python-Markdown was HTML-only; markdown-it / mistletoe not installed). Real `extract.py` CLI with full exit-code coverage. 24 new tests (16 parser + 8 CLI). Total generator suite: 43 passed.

**B1. `parser/markdown.py` → IR.** ✅ Line walker (no external dep). Handles ATX H1–H6, fenced code (` ``` ` and `~~~`), bulleted + numbered lists, pipe tables, paragraphs. Root Section is synthetic level-0; H1+ hang off `root.children`. Anchors = 1-indexed line numbers (`"L<n>"`).

**B2. `cli/extract.py` runs markdown parser on the source.** ✅ Rejects non-`.md` with exit 1. Exit codes: 0 OK / 1 bad source or work-dir / 2 parse or write failure. Payload: `{source, source_label, root: asdict(Section)}`. `--stdout` flag echoes JSON.

**B3. Tests.** ✅
- `tests/test_markdown_parser.py` — 16 tests: heading tree, paragraph/list/code/table capture, anchors, edge cases (empty, orphan, H4 nesting, both fence styles, numbered lists).
- `tests/test_cli_extract.py` — 8 tests: happy path, `--stdout`, missing source (exit 1), wrong extension (exit 1), unwritable work-dir (exit 1), write failure (exit 2), parse failure (exit 2), `--help` (exit 0).

**Verify:** ✅ `python3 agents/generator/cli/extract.py docs/grava-plane-status-sync-plan.md --work-dir /tmp/gen-test` writes a 1-child-root extract with the H1 `Plan — Grava coding team → Plane status sync` and its H2 children (`Goal`, `Inventory…`, `Trigger model…`).

### Phase D — LLM outline (DEFERRED — develop in later phase)

> **Status: deferred.** Direct Anthropic SDK calls require a paid `ANTHROPIC_API_KEY`, which is not in budget today. Claude Code subscription covers the interactive `claude` CLI only, not SDK calls. Phase D is parked until billing is sorted.
>
> **Interim workflow (works today, no API key needed):**
>
> 1. `se generate <source> --project <name> --no-llm` → produces `extract.json` only.
> 2. Operator opens Claude Code in a session, pastes `extract.json`, asks Claude to produce an `outline.json` matching the D2 schema below.
> 3. Operator saves the produced `outline.json` into `drafts/<sys>/runs/<run_id>/outline.json`.
> 4. `se generate <source> --project <name> --step render` → render reads the manual outline, emits drafts.
>
> This keeps Phases A–C + E + F unblocked. Phase D below is preserved as the future automation target.

**D1. `llm_client.py`** *(future)*.
- Read `ANTHROPIC_API_KEY` from env. Error if missing.
- `outline(ir_root, *, model="claude-sonnet-4.5", max_tokens=4096)` → hierarchy JSON.
- Single non-streaming call. Temperature 0. System prompt loaded from `agents/generator/prompts/outline.md`.

**D2. Prompt + schema** *(active — used by the interim manual workflow)*.
- Input: IR sections (compressed: heading + first 300 chars per block).
- Output schema:
  ```json
  {
    "epics": [
      {"title": "...", "summary": "...", "source_anchors": ["..."],
       "design_links": [
         {"label": "Figma — Booking flow", "url": "https://figma.com/file/XXX/booking"},
         {"label": null, "url": "design/booking-mockup.png"}
       ],
       "stories": [
         {"title": "...", "depends_on": [], "source_anchors": ["..."],
          "acceptance_criteria": ["...", "..."],
          "tasks": [{"title": "...", "ac": ["..."]}]}
       ]}
    ],
    "confidence": 0.78
  }
  ```
  `design_links` is optional; empty list / omitted = no UI/UX section rendered. Each entry: `{label, url}`. `label` null → render as bare URL or path.
- Operator paste the IR sections + the schema above into a Claude Code session and asks for matching JSON.

**D3. `cli/outline.py`** *(future)*.
- Will read `extract.json`, call `llm_client.outline()`, write `outline.json`.
- Exit codes: 0 OK / 1 missing API key / 2 LLM call failed / 3 invalid output shape.

**D4. Tests** *(future)*.
- Mock `llm_client.outline()` (do not call real API in tests).
- `tests/test_outline_cli.py` — happy path, missing creds, bad shape.

### Phase E — Render — ✅ DONE (2026-05-16)

> Landed: top-level `render.py` (one .md per epic, full frontmatter, AC + UI/UX blocks); `cli/render.py` with manifest.json + envelope-payload support; `cli/init_run.py` for run-dir provisioning; `agents/generator/diff.py` (added/removed/renamed with Levenshtein-style rename detection at epic/story/task levels); `cli/run.py` chaining init→extract→outline→render with `--dry-run`/`--no-llm`/`--llm`/`--step` + diff persistence as `diff.json`; `cli/se generate` subcommand wired. 50 new tests (17 render + 12 diff + 5 init_run + 7 render-CLI + 12 run-CLI minus 3 already-counted). Total generator suite: **93 passed in 0.07s**.
>
> End-to-end verified: `se generate fixtures/sample.md --project demo --run-id RID-1 --system-name "Demo System"` with pre-seeded `outline.json` emits two drafts under `drafts/demo/runs/RID-1/drafts/`. Manual integration check: `task-generator/parser.py` parses the rendered Court Booking draft into 1 epic + 2 stories with no warnings (note: task-generator parser does not yet implement the `**Acceptance Criteria:**` marker rule — AC bullets currently become TaskNodes; format spec is correct, downstream wiring is a follow-up).

**E1. `render.py`.** ✅
- Given `outline.json` + run metadata: emit one `*.md` per epic.
- Filename: `YYYY-MM-DD-<slug>.md` from `epic.title`.
- Frontmatter: `generator_source`, `generator_run_id`, `generator_confidence`, `generator_model`, `generator_model_version`.
- Body structure:
  - H1 = system name.
  - H2 per epic.
  - Under each H2, before stories: a **`**UI/UX Design:**`** line listing one or more links (Figma, design-doc URL, image path). Omitted when `epic.design_links` is empty.
  - H3 per story (with `> Depends on:` blockquote when set).
  - Under each H3, after the story description: an **`**Acceptance Criteria:**`** marker line followed by a bullet list. Each bullet is one criterion. The downstream task-generator parser ([docs/task-generator/parser.md](../task-generator/parser.md)) treats bullets after this marker as `story.acceptance_criteria` — not tasks.
  - H4 per task with AC bullets *(optional, used only when stories sub-divide into work items)*.
- Example epic block:
  ```markdown
  ## Epic 1: Court Booking

  **UI/UX Design:**
  - [Figma — Booking flow](https://figma.com/file/XXX/booking)
  - `design/booking-mockup.png`

  ### US-01 — Pick a court
  **As a** customer,
  **I want to** browse available courts on a map,
  **so that** I can pick one near me.

  **Acceptance Criteria:**
  - Map shows courts within a 5 km radius of current location
  - Pin colour reflects availability (green = open, red = booked)
  - Tapping a pin opens the court detail sheet
  ```

**E2. `cli/render.py`.** ✅ Reads `<work-dir>/outline.json` (or envelope `{run_id, source, outline}`), writes `<work-dir>/drafts/*.md` plus `<work-dir>/manifest.json`. Exit codes: 0 / 1 (missing or invalid outline) / 2 (write error).

**E3. `se generate` subcommand + `cli/run.py` (one-shot).** ✅
- `cli/run.py` is the internal implementation; `se generate` is the operator-facing entry point added to `cli/se`.
- Operator interface:
  ```
  se generate <source> --project <name> --llm        # full chain
  se generate <source> --project <name> --dry-run    # extract only, no LLM
  se generate <source> --project <name> --no-llm     # extract only, render skipped
  se generate <source> --project <name> --step extract|outline|render  # single step
  ```
- Chains extract → outline → render internally.
- `--llm`: required to call Anthropic; default offline mode produces `extract.json` only.
- On each run, saves `extract.json` + `outline.json` + rendered `*.md` into `drafts/<sys>/runs/<run_id>/`.
- If a previous run exists for the same source file: compute structured diff (epics/stories/tasks added, removed, renamed) and print it before writing new drafts. Operator sees delta; no hard failure.
- Diff stored as `drafts/<sys>/runs/<run_id>/diff.json` for audit.

**E4. Tests.** ✅
- `tests/test_render.py` — 17 tests on the render module (frontmatter keys, H1/H2/H3/H4 structure, AC block, UI/UX block omission, depends-on blockquote, slugify, filename format).
- `tests/test_cli_render.py` — 7 tests on the render CLI (happy path, envelope payload, missing/malformed/invalid outline, write failure, --help).
- `tests/test_cli_init_run.py` — 5 tests (creates dir, run.json contents, default UTC run-id, mkdir failure, --help).
- `tests/test_diff.py` — 12 tests covering empty diff, epic add/remove/rename, story drill-down (including under renamed epics), task add/remove, render_diff_text.
- `tests/test_cli_run.py` — 12 tests (missing source, --dry-run/--no-llm/--step extract stop after extract; --step outline no-op; --llm refused with helpful Phase D pointer; full chain with hand-placed outline.json; --step render; diff emitted on second run + persisted as diff.json; no diff when no previous run).

**Verify:** ✅ `pytest agents/generator/tests/` → **93 passed**. End-to-end: `python3 cli/se generate agents/generator/tests/fixtures/sample.md --project demo --drafts-root /tmp/se-gen-e2e/drafts --run-id RID-1 --system-name "Demo System"` (with `outline.json` pre-seeded) emits two valid drafts. task-generator parser accepts the result with zero warnings.

### Phase F — Operator polish — ✅ DONE (2026-05-16)

> Landed: `drafts/` in `.gitignore`; `setup.sh` installs `markdownify` + prints `.env` setup hint + adds `se generate` / `se download` to the quick-reference footer; `agents/generator/AGENT.md` fleshed out with the three-step pipeline, output format example, Phase D interim workflow, hard limits, allowed tools, and a failure-modes table mirroring `task-generator/AGENT.md`; `docs/stellar-engine/plan.md` G6 marked CLOSED (MVP) and the Phase F summary table flipped A/B/E/F to ✅ done.

**F1. Add `drafts/` to `.gitignore`.** ✅ `drafts/` excluded; `.env*` lines were already present from earlier work.

**F2. Update `setup.sh`.** ✅
- Python deps now install `markdown markdownify requests pyyaml` (notes call out that `anthropic` and `pymupdf` stay out until their phases land).
- New "Sandbox .env" section prompts `cp .env.example .env`, `set -a; source .env; set +a`, and reminds the operator that `ANTHROPIC_API_KEY` can stay as a placeholder under the Phase D interim workflow.
- Quick-reference footer adds `python3 cli/se generate <source.md> --project <name>` and `python3 cli/se download <project-uuid>`.

**F3. `agents/generator/AGENT.md`.** ✅ Replaced the Phase A stub with the full agent prompt: invocation patterns (all flags), three-step pipeline diagram, output format example, Phase D interim workflow, hard limits (NEVER Plane / grava / auto-promote / bypass `--llm` gate / commit `drafts/` / auto-resolve diffs), allowed tools, failure-modes table for every documented exit code, cross-links to plan + downstream parser.

**F4. Update `docs/stellar-engine/plan.md`.** ✅ Phase F summary table now shows A/B/E/F as `✅ done`; G6 row marked CLOSED (MVP) with the manual-outline caveat preserved.

### Phase G — Doctor integration — ✅ DONE (2026-05-16)

> Landed: generator checks live in `cli/se doctor` (engine-level), not in `agents/orchestrator/cli/doctor.py` (which targets a single repo — wrong scope for an engine-wide agent). Five new check helpers (`_check_python_module`, `_check_env_file`, `_check_generator`) wired into `cmd_doctor`. 9 new tests load `cli/se` as a module via `SourceFileLoader` and exercise the helpers directly. Total generator suite: **102 passed in 0.11s**.

**G1. Extend `cli/se doctor`.** ✅
- `_check_generator(base)` — `agents/generator/` package present (error if missing), `markdown` + `markdownify` importable (required), `anthropic` + `pymupdf` importable (warn-only — Phase D + PDF deferred), `drafts/` directory status (ok with run count, warn if missing with `se generate` hint).
- `_check_env_file(base)` — `.env` present (ok) or missing (warn with hint to copy `.env.example`).
- `_check_python_module(name, *, required, note)` — generic importability probe; deferred modules report as warn with a phase pointer.

Note: the original plan named `agents/orchestrator/cli/doctor.py` as the target. That doctor is target-repo-scoped (checks `.grava`, `/ship` skill, etc.); the generator is engine-level, so `cli/se doctor` is the right home. The orchestrator doctor remains unchanged.

---

## 5. Critical files to create or modify

| Phase | Path | Action | Status |
|:---|:---|:---|:---|
| A1 | `agents/generator/__init__.py`, `AGENT.md`, `requirements.txt`, `llm_client.py`, `ir.py` | Create (AGENT.md stub) | ✅ |
| A1 | `agents/generator/parser/*.py` | Create | ✅ |
| A1 | `agents/generator/cli/*.py` | Create (5 scripts, skeletons) | ✅ |
| A1 | `agents/generator/tests/{__init__,conftest}.py` | Create | ✅ |
| A4 | `agents/generator/tests/test_ir.py`, `test_cli_smoke.py` | Create | ✅ |
| B1 | `agents/generator/parser/markdown.py` | Implement | ✅ |
| B2 | `agents/generator/cli/extract.py` | Implement | ✅ |
| B3 | `agents/generator/tests/test_markdown_parser.py`, `test_cli_extract.py` | Create | ✅ |
| D1 | `agents/generator/llm_client.py` | Implement | 🚫 deferred |
| D2 | `agents/generator/prompts/outline.md` | Create | 🚫 deferred |
| D3 | `agents/generator/cli/outline.py` | Implement | 🚫 deferred |
| D4 | `agents/generator/tests/test_outline_cli.py` | Create | 🚫 deferred |
| E1 | `agents/generator/render.py` | Implement | ✅ |
| E2 | `agents/generator/cli/render.py` | Implement | ✅ |
| E3 | `agents/generator/cli/init_run.py` | Implement | ✅ |
| E3 | `agents/generator/cli/run.py` | Implement | ✅ |
| E3 | `agents/generator/diff.py` | Implement | ✅ |
| E3 | `cli/se` (add `generate` subcommand) | Edit | ✅ |
| E4 | `agents/generator/tests/test_render.py`, `test_cli_render.py`, `test_cli_init_run.py`, `test_cli_run.py`, `test_diff.py`, fixtures | Create | ✅ |
| F1 | `.gitignore` | Add `drafts/` | ✅ |
| F2 | `setup.sh` | Add deps + ANTHROPIC_API_KEY hint | ✅ |
| F3 | `agents/generator/AGENT.md` | Flesh out | ✅ |
| F4 | `docs/stellar-engine/plan.md` | Cross-link | ✅ |
| G1 | `cli/se` (add `_check_generator` + `_check_env_file` + `_check_python_module`) | Edit | ✅ |
| G1 | `agents/generator/tests/test_doctor_checks.py` | Create | ✅ |

---

## 6. Verification

### Sandbox configuration

End-to-end verification runs against a dedicated sandbox to keep production Plane workspaces clean. Secrets live in a local `.env` file at the stellar-engine repo root (gitignored).

| Setting | `.env` key | Notes |
|:---|:---|:---|
| Plane workspace | `PLANE_WORKSPACE` | `stellar-sandbox` |
| Plane host | `PLANE_HOST` | `https://api.plane.so` |
| Plane project ID | `PLANE_PROJECT_ID` | `STELL` |
| Plane API key | `PLANE_API_TOKEN` | **never commit** |
| Anthropic API key | `ANTHROPIC_API_KEY` | **never commit** |
| Sandbox repo | `SANDBOX_REPO` | `/Users/trungnguyenhoang/IdeaProjects/stellar-sand-box` |

Setup (one time):
```bash
cp .env.example .env       # template at repo root
$EDITOR .env               # paste real keys
set -a; source .env; set +a    # load into current shell
```

The `.env` file is gitignored. `.env.example` is the committed template — safe to share, contains no real keys.

### Per-phase verification

**After Phase A:** `pytest agents/generator/tests/` green; CLI `--help` works for all five scripts.

**After Phase B:**
```bash
python3 agents/generator/cli/extract.py docs/grava-plane-status-sync-plan.md --work-dir /tmp/gen-test
```
→ `extract.json` with H2/H3/H4 hierarchy intact.

**After Phase D (deferred):** N/A today. Interim check: paste a Phase B `extract.json` into a Claude Code session with the D2 schema; Claude returns an `outline.json` that validates against the schema. Save it to `runs/<run_id>/outline.json` for Phase E to consume.

**After Phase E:**
```bash
# Full chain — emits drafts to sandbox folder
se generate /path/to/sample.md --project STELL --llm

# Re-run after editing the source — see diff
se generate /path/to/sample.md --project STELL --llm
# → prints "Diff vs run <prev>:" with added/removed/renamed epics/stories/tasks
```

End-to-end integration (manual; assumes `.env` loaded):
```bash
# Promote one draft into the sandbox repo
cp drafts/$PLANE_PROJECT_ID/2026-05-16-<slug>.md \
   $SANDBOX_REPO/systems/$PLANE_PROJECT_ID/business/spec.md

# Upload to Plane sandbox workspace
python3 upload_project_pages.py $PLANE_PROJECT_ID \
   $SANDBOX_REPO/systems/$PLANE_PROJECT_ID/business/

# Trigger task-generator dry-run against the uploaded page
python3 agents/task-generator/cli/run.py $PLANE_PROJECT_ID <page_id> --dry-run \
   --target-repo $SANDBOX_REPO
```
→ parser accepts the draft, planner builds epic/story/task hierarchy, no errors.

**After Phase F:** `bash setup.sh` on a clean machine installs `pymupdf` and `anthropic`; prints `ANTHROPIC_API_KEY` hint.

**Continuous:** `pytest agents/generator/tests/` after every Phase. Add tests with each implementation.

---

## 7. Sequencing and parallelism

```
A1 ──> A2 ──> A3 ──> A4 ─────────────────────┐
                                              │
B1 ──> B2 ──> B3 ────────────────────────────┤
                                              │
[D1 ──> D2 ──> D3 ──> D4]  DEFERRED          │ (manual outline via Claude Code)
                                              │
E1 ──> E2 ──> E3 ──> E4 (needs B; uses ──────┤
                         manual outline.json) │
                                              │
F1 ─ F2 ─ F3 ─ F4 (after E) ─────────────────┤
                                              │
G1 (after F, optional) ───────────────────────┘
```

**Hard rules:**

- **A blocks everything.** No B/D/E before scaffold lands.
- **D is deferred.** Manual outline via Claude Code session covers it until API key budget exists. The D2 schema is the contract — `outline.json` shape must match whether produced manually or by automation.
- **E depends on B only** (needs a markdown parser + an `outline.json`; outline can be manual today).
- **F (operator polish) waits on E.** No point updating `setup.sh` before the chain runs.
- **G (doctor integration) is optional.** Can land in a follow-up PR after the rest is stable.

**Recommended PR boundaries:**

1. **PR 1: Phase A** — scaffold + smoke tests. Small, easy to review.
2. **PR 2: Phase B** — markdown parser.
3. **PR 3: Phase E + F** — render (consumes manual `outline.json`) + operator polish.
4. **PR 4: Phase G** — doctor integration (optional).
5. **PR 5 (future): Phase D** — automated LLM outline once API key budget exists.
6. **Future: PDF frontend** — when a real PDF source workflow is needed; revives the old Phase C.

---

## 8. Out of scope for this plan

- PDF / URL / transcript / codebase frontends.
- task-generator extension to strip `generator_*` frontmatter (operator strips manually for now).
- Cost ceiling per run / token caps.
- Multi-document synthesis (one source per run).
- Real-time / streaming generation (one-shot batch only).
- Auto-promotion of drafts into `systems/`.
- Direct Plane / grava writes (use `task-generator` + `upload_project_pages.py`).
