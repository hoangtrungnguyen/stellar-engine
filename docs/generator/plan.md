# Generator Agent — Implementation Plan

**Status:** Draft · **Last updated:** 2026-05-16

Companion to [`strategy.md`](strategy.md). Strategy describes intent and components. This plan covers the **CLI scaffold + minimal extract/render MVP** — enough to take one markdown or PDF and emit one spec draft, end-to-end.

---

## 1. Context

`docs/stellar-engine/plan.md` §4 Phase F (Generator) was deferred without detail. This sub-plan turns that into concrete sequencing.

Scope cuts:
- **Input:** one markdown OR one PDF file. URLs / codebases / transcripts are Phase 8+ in `strategy.md`.
- **Output:** one or more spec markdown files under `drafts/<system-name>/`. No Plane writes, no grava writes.
- **LLM:** Anthropic SDK direct, single Sonnet call per outline, temperature 0.
- **Promotion:** operator copies a draft into `systems/<Name>/business/` by hand. Not automated.

What this plan does NOT cover (deferred):
- Codebase-as-source (`strategy.md` §3.1 not listed; Phase 9).
- URL / transcript frontends (strategy Phase 8).
- Draft staleness doctor checks.
- task-generator extension to strip `generator_*` frontmatter (open question 7).

---

## 2. Inventory

### 2.1 Existing (no Generator code yet)

| Path | Relevance |
|:---|:---|
| `agents/task-generator/` | Layout template; mirror naming conventions, CLI structure, tests style |
| `agents/task-generator/parser.py` | Downstream consumer of Generator output; must parse rendered drafts cleanly |
| `agents/task-generator/cli/resolve_repo.py` | Pattern for resolving system → directory |
| `agents/orchestrator/tests/conftest.py` | Test-fixture style to reuse |
| `setup.sh` | Will need `pymupdf` + `anthropic` added to pip install line |
| `docs/generator/strategy.md` | Design doc, written alongside this plan |
| `docs/stellar-engine/plan.md` §4 Phase F | Notes Generator is unbuilt; will mark this sub-plan as the owner |

### 2.2 To be built

| Path | Function |
|:---|:---|
| `agents/generator/__init__.py` | Package marker |
| `agents/generator/AGENT.md` | Agent prompt: invocation pattern, hard limits, approval gates |
| `agents/generator/requirements.txt` | `pymupdf>=1.24`, `anthropic>=0.40` |
| `agents/generator/llm_client.py` | Thin Anthropic SDK wrapper |
| `agents/generator/ir.py` | Intermediate representation dataclasses |
| `agents/generator/parser/__init__.py` | Markdown / PDF dispatcher |
| `agents/generator/parser/markdown.py` | `*.md` → IR |
| `agents/generator/parser/pdf.py` | `*.pdf` → IR (PyMuPDF) |
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
| `agents/generator/tests/fixtures/sample.md`, `sample.pdf` | Golden inputs |
| `agents/generator/tests/fixtures/expected_draft.md` | Golden output for regression |
| `setup.sh` edit | Add new deps to install line |
| `docs/stellar-engine/plan.md` edit | Reference this sub-plan from Phase F |

---

## 3. Gaps

### G_Gen_1. No agent directory exists
`agents/generator/` is empty. Every file in §2.2 is new.

### G_Gen_2. No LLM credential plumbing
`agents/task-generator/` uses Plane creds; nothing in the repo loads `ANTHROPIC_API_KEY`. New `llm_client.py` must handle this.

### G_Gen_3. PDF parsing dep absent
Repo does not depend on PyMuPDF today. `setup.sh` must be extended; clean-clone testing required.

### G_Gen_4. No `drafts/` convention
The directory does not exist yet; `.gitignore` does not exclude it. Drafts should be operator-local, not committed by default.

### G_Gen_5. No golden-output regression coverage
Without a canned input + expected output, the LLM step has no determinism guard. Same prompt + temperature 0 should produce byte-identical render output, but only if golden files exist.

---

## 4. Plan

### Phase A — Scaffold (no LLM, no PDF yet)

**A1. Create the directory tree.**
- `agents/generator/{__init__.py, AGENT.md, ir.py, llm_client.py, requirements.txt}`
- `agents/generator/parser/{__init__.py, markdown.py, pdf.py}` (markdown only; pdf stubbed)
- `agents/generator/cli/{__init__.py, init_run.py, extract.py, outline.py, render.py, run.py}`
- `agents/generator/tests/{__init__.py, conftest.py}`

**A2. Define IR dataclasses (`ir.py`).**
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

**A3. CLI argparse skeletons.**
Each CLI script: argparse, JSON-line output for chained invocation, exit codes documented in module docstring. No real work — just print "phase A scaffold" and exit 0. Verifies the chain runs end-to-end before logic lands.

**A4. Tests for A1–A3.**
- `tests/test_ir.py` — round-trip IR ↔ JSON.
- `tests/test_cli_smoke.py` — each CLI script accepts `--help`, exits 0.

**Verify:** `pytest agents/generator/tests/` green; `python3 agents/generator/cli/run.py --help` shows usage.

### Phase B — Markdown frontend (no LLM yet)

**B1. `parser/markdown.py` → IR.**
- Walk markdown via the existing `markdown` lib (already a dep).
- Build `Section` tree from H1/H2/H3/H4 nesting.
- Capture paragraphs, lists, code blocks, tables as `Block`.
- Anchor = line number.

**B2. `cli/extract.py` wires markdown parser when source ends in `.md`.**
- Writes `extract.json` (`asdict(root_section)`).
- Exit codes: 0 OK / 1 bad source / 2 parse failure.

**B3. Tests.**
- `tests/test_markdown_parser.py` — fixture `sample.md` → expected `Section` tree.
- `tests/test_cli_extract.py` — invokes `extract.main([…])`, asserts JSON shape.

**Verify:** `python3 agents/generator/cli/extract.py docs/grava-plane-status-sync-plan.md --work-dir /tmp/gen-test` produces a sane `extract.json`.

### Phase C — PDF frontend

**C1. Add `pymupdf` to `requirements.txt` and `setup.sh`.**

**C2. `parser/pdf.py` → IR.**
- `fitz.open(path)` → iterate pages → extract spans → reconstruct heading hierarchy from font size + bold.
- Anchor = `page=<N>;y=<float>` so render can echo source position back.

**C3. Dropped-element tracking.**
- Record counts of figures, dropped images, undecodable text. Surface in `extract.json` under `"warnings"`.

**C4. Tests.**
- Golden fixture: `tests/fixtures/sample.pdf` (one-page PDF with three sections).
- `tests/test_pdf_parser.py` — assert heading count, section text.

**Verify:** drop a real PRD PDF in `/tmp/`, run `extract.py`, inspect `extract.json` for completeness.

### Phase D — LLM outline

**D1. `llm_client.py`.**
- Read `ANTHROPIC_API_KEY` from env. Error if missing.
- `outline(ir_root, *, model="claude-sonnet-4.5", max_tokens=4096)` → hierarchy JSON.
- Single non-streaming call. Temperature 0. System prompt loaded from `agents/generator/prompts/outline.md`.

**D2. Prompt design.**
- Input: IR sections (compressed: heading + first 300 chars per block).
- Output schema (enforced via JSON mode):
  ```json
  {
    "epics": [
      {"title": "...", "summary": "...", "source_anchors": ["..."],
       "stories": [
         {"title": "...", "depends_on": [], "source_anchors": ["..."],
          "tasks": [{"title": "...", "ac": ["..."]}]}
       ]}
    ],
    "confidence": 0.78
  }
  ```

**D3. `cli/outline.py`.**
- Reads `extract.json`, calls `llm_client.outline()`, writes `outline.json`.
- Exit codes: 0 OK / 1 missing API key / 2 LLM call failed / 3 invalid output shape.

**D4. Tests.**
- Mock `llm_client.outline()` (do not call real API in tests).
- `tests/test_outline_cli.py` — happy path, missing creds, bad shape.

**Verify:** with real API key, run outline against the markdown extract from Phase B. Inspect `outline.json` quality.

### Phase E — Render

**E1. `render.py`.**
- Given `outline.json` + run metadata: emit one `*.md` per epic.
- Filename: `YYYY-MM-DD-<slug>.md` from `epic.title`.
- Frontmatter: `generator_source`, `generator_run_id`, `generator_confidence`, `generator_model`, `generator_model_version`.
- Body: H1 (system name), H2 per epic, H3 per story (with `> Depends on:` blockquote when set), H4 per task with AC bullets.

**E2. `cli/render.py`.**
- Reads `outline.json`, writes `*.md` files into `drafts/<system>/`.
- Writes `manifest.json` listing emitted paths + confidence.

**E3. `cli/run.py` (one-shot).**
- Chains extract → outline → render.
- `--dry-run`: stop after extract.
- `--no-llm`: stop after extract; render skipped.
- `--llm`: required to actually call Anthropic.

**E4. Tests.**
- Golden fixture: `outline.json` + expected `*.md`.
- `tests/test_render.py` — assert byte-identical output.
- `tests/test_cli_run.py` — full chain with mocked LLM.

**Verify:** end-to-end on a real PDF. Operator-readable drafts emitted. `task-generator/parser.py` parses one promoted draft cleanly (manual integration test).

### Phase F — Operator polish

**F1. Add `drafts/` to `.gitignore`.**

**F2. Update `setup.sh`.**
- Add `pymupdf`, `anthropic` to the pip install line.
- New section: print `ANTHROPIC_API_KEY` setup hint.

**F3. `agents/generator/AGENT.md`.**
- Document invocation patterns.
- Hard limit: NEVER call Plane or grava.
- Hard limit: NEVER auto-promote into `systems/`.
- Hard limit: NEVER bypass `--llm` gate (default offline mode produces extract.json only).
- Failure modes table mirroring `task-generator/AGENT.md`.

**F4. Update `docs/stellar-engine/plan.md`.**
- Phase F (Generator) → reference `docs/generator/plan.md` as owner.
- G6 status updated (in progress → done as phases land).

### Phase G — Doctor integration (optional, can defer)

**G1. Extend `agents/orchestrator/cli/doctor.py`.**
- Check `ANTHROPIC_API_KEY` present.
- Check `pymupdf` + `anthropic` importable.
- Check `drafts/` exists (informational).

---

## 5. Critical files to create or modify

| Phase | Path | Action |
|:---|:---|:---|
| A1 | `agents/generator/__init__.py`, `AGENT.md`, `requirements.txt`, `llm_client.py`, `ir.py` | Create (AGENT.md stub) |
| A1 | `agents/generator/parser/*.py` | Create |
| A1 | `agents/generator/cli/*.py` | Create (5 scripts, skeletons) |
| A1 | `agents/generator/tests/{__init__,conftest}.py` | Create |
| A4 | `agents/generator/tests/test_ir.py`, `test_cli_smoke.py` | Create |
| B1 | `agents/generator/parser/markdown.py` | Implement |
| B2 | `agents/generator/cli/extract.py` | Implement |
| B3 | `agents/generator/tests/test_markdown_parser.py`, `test_cli_extract.py` | Create |
| C1 | `agents/generator/requirements.txt`, `setup.sh` | Edit |
| C2 | `agents/generator/parser/pdf.py` | Implement |
| C4 | `agents/generator/tests/fixtures/sample.pdf` + `test_pdf_parser.py` | Create |
| D1 | `agents/generator/llm_client.py` | Implement |
| D2 | `agents/generator/prompts/outline.md` | Create |
| D3 | `agents/generator/cli/outline.py` | Implement |
| D4 | `agents/generator/tests/test_outline_cli.py` | Create |
| E1 | `agents/generator/render.py` | Implement |
| E2 | `agents/generator/cli/render.py` | Implement |
| E3 | `agents/generator/cli/run.py` | Implement |
| E4 | `agents/generator/tests/test_render.py`, `test_cli_run.py`, fixtures | Create |
| F1 | `.gitignore` | Add `drafts/` |
| F2 | `setup.sh` | Add deps + ANTHROPIC_API_KEY hint |
| F3 | `agents/generator/AGENT.md` | Flesh out |
| F4 | `docs/stellar-engine/plan.md` | Cross-link |

---

## 6. Verification

**After Phase A:** `pytest agents/generator/tests/` green (2 tests); CLI `--help` works for all five scripts.

**After Phase B:** `extract.py` on this very repo's `docs/grava-plane-status-sync-plan.md` produces a sane `extract.json` with the H2/H3/H4 hierarchy intact.

**After Phase C:** `extract.py` on a real-world PRD PDF emits an `extract.json` with most headings preserved; dropped-element count visible.

**After Phase D:** with `ANTHROPIC_API_KEY` set, `outline.py` on a Phase B `extract.json` produces a valid `outline.json` matching the schema in D2.

**After Phase E:**
- Full chain: `run.py path/to/sample.pdf --llm --output drafts/sample/` produces `*.md` files in `drafts/sample/`.
- One emitted draft is hand-copied into `systems/<Test>/business/spec.md`, uploaded via `upload_project_pages.py`, and then `agents/task-generator/cli/run.py <project> <page> --dry-run` parses it cleanly with no errors.

**After Phase F:** `bash setup.sh` on a clean machine installs `pymupdf` and `anthropic`; prints `ANTHROPIC_API_KEY` hint.

**Continuous:** `pytest agents/generator/tests/` after every Phase. Add tests with each implementation, not in a single batch.

---

## 7. Sequencing and parallelism

```
A1 ──> A2 ──> A3 ──> A4 ─────────────────────┐
                                              │
B1 ──> B2 ──> B3 ────────────────────────────┤
                                              │
C1 ──> C2 ──> C3 ──> C4 (independent of B) ──┤
                                              │
D1 ──> D2 ──> D3 ──> D4 ─────────────────────┤
                                              │
E1 ──> E2 ──> E3 ──> E4 (depends on B + D) ──┤
                                              │
F1 ─ F2 ─ F3 ─ F4 (after E) ─────────────────┤
                                              │
G1 (after F, optional) ───────────────────────┘
```

**Hard rules:**

- **A blocks everything.** No B/C/D/E before scaffold lands.
- **B and C are independent.** Two operators can split markdown/PDF.
- **D blocks E.** Outline schema must be stable before render.
- **E depends on B AND D** (needs both a parser and an outline).
- **F (operator polish) waits on E.** No point updating `setup.sh` before the chain runs.
- **G (doctor integration) is optional.** Can land in a follow-up PR after the rest is stable.

**Recommended PR boundaries:**

1. **PR 1: Phase A** — scaffold + smoke tests. Small, easy to review.
2. **PR 2: Phase B + C** — both parsers in one PR.
3. **PR 3: Phase D** — LLM outline.
4. **PR 4: Phase E + F** — render + operator polish.
5. **PR 5: Phase G** — doctor integration (optional).

---

## 8. Out of scope for this plan

- URL / transcript / codebase frontends — `strategy.md` Phases 8–9.
- task-generator extension to strip `generator_*` frontmatter — strategy §10 OQ 7.
- Cost ceiling per run / token caps — strategy §10 OQ 4.
- Multi-document synthesis — strategy §6 non-goal.
- Real-time/streaming Generator — strategy §11 anti-strategy.
