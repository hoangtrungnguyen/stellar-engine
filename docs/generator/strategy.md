# Generator Agent — Strategy

**Status:** Draft · **Last updated:** 2026-05-16

> Companion plan: [`plan.md`](plan.md). Upstream context: [`docs/stellar-engine/strategy.md`](../stellar-engine/strategy.md) §3.2 lists the Generator as a planned component; this doc fills in the design.

---

## 1. Problem

Today, every grava backlog starts from a hand-written Plane spec page. Operators must:

1. Read source material (a PRD, design doc, transcript, RFC, …).
2. Decide which sections become epics, which become stories, which become tasks.
3. Type the spec into Plane by hand, following the H1/H2/H3/H4 convention `task-generator` parses.
4. Re-read for missed scope, conflicting requirements, dependency ordering.

This is the slowest step in the entire pipeline. The Generator Agent automates the first three substeps and leaves the operator only the fourth (review).

The constraint: anything the Generator emits must remain **operator-reviewable on disk** before it reaches Plane or grava. Strategy principle 4: "Files before issues."

---

## 2. Thesis

The Generator is a **document → spec markdown** translator. Input: one source document (initially markdown or PDF). Output: one or more spec files under `drafts/<system-name>/`, each shaped to the task-generator H2/H3/H4 hierarchy.

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Source doc      │    │  Generator agent │    │  drafts/<sys>/   │
│  (md / PDF /     ├───>│  extract→outline ├───>│  *.md spec files │
│   future: URL)   │    │  →render         │    │  (reviewable)    │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                                          │
                                                          │ operator
                                                          │ reviews +
                                                          ▼ promotes
                                                ┌──────────────────┐
                                                │ systems/<Name>/  │
                                                │ business/spec.md │
                                                └────────┬─────────┘
                                                         │
                                              upload_project_pages.py
                                                         │
                                                         ▼
                                                ┌──────────────────┐
                                                │ Plane spec page  │
                                                └────────┬─────────┘
                                                         │
                                                /generate <page_id>
                                                         │
                                                         ▼
                                                ┌──────────────────┐
                                                │ task-generator   │
                                                │ → Plane + Grava  │
                                                └──────────────────┘
```

The Generator **never** writes to Plane or grava. The handoff is filesystem only. Strategy D6 protected.

---

## 3. Components

### 3.1 Generator agent (`agents/generator/`)

Mirrors the layout of `agents/task-generator/`:

| Path | Role |
|:---|:---|
| `agents/generator/AGENT.md` | Agent prompt: how Claude invokes the CLI, approval gates, hard limits |
| `agents/generator/cli/extract.py` | Source doc → intermediate JSON (sections, headings, paragraphs) |
| `agents/generator/cli/outline.py` | Intermediate JSON → epic/story/task hierarchy (LLM call) |
| `agents/generator/cli/render.py` | Hierarchy → one or more H2/H3/H4 markdown files under `drafts/` |
| `agents/generator/cli/run.py` | One-shot orchestrator chaining extract → outline → render |
| `agents/generator/cli/init_run.py` | Set up `<output>/runs/<run_id>/` working directory |
| `agents/generator/parser/markdown.py` | Markdown frontend (no LLM) |
| `agents/generator/parser/pdf.py` | PDF frontend (PyMuPDF) |
| `agents/generator/llm_client.py` | Thin wrapper around the Anthropic SDK (one model, low temp) |
| `agents/generator/requirements.txt` | `pymupdf`, `anthropic` (in addition to repo defaults) |
| `agents/generator/tests/` | Unit tests mirroring `task-generator/tests/` |

### 3.2 Output convention

Each emitted file has YAML frontmatter + H2/H3/H4 sections matching what `task-generator/parser.py` already parses:

```markdown
---
generator_source: /path/to/source.pdf
generator_run_id: 2026-05-16T08-03-14Z
generator_confidence: 0.78
---

# <Spec title>

## Epic 1: <Title>

Brief description.

### Story 1.1: <Title>

> Depends on: Epic 0

#### Task: <Title>

Acceptance criteria as bullet list.
```

Frontmatter `generator_*` keys are stripped by the operator before upload (or by a future `task-generator` extension that ignores them).

### 3.3 Drafts directory

```
drafts/
├── <system-name>/
│   ├── runs/<run_id>/
│   │   ├── extract.json       # raw extracted structure
│   │   ├── outline.json       # LLM-proposed hierarchy
│   │   └── manifest.json      # paths of rendered specs
│   ├── 2026-05-16-onboarding-flow.md
│   └── 2026-05-16-payments-v2.md
```

Operator promotes individual files into `systems/<Name>/business/` after review. Never auto-promoted.

---

## 4. Principles

1. **Files only.** Generator writes to disk. No Plane API calls, no grava commands. Strategy D6.
2. **One source doc → one outline → N spec files.** Multiple epics in one doc → multiple files; one epic → one file.
3. **LLM call is one-shot per outline.** Streaming, retries, and chain-of-thought stay inside the outline step. Render is deterministic markdown generation, no LLM.
4. **Confidence is surfaced, not hidden.** Frontmatter records a confidence score; operator decides whether to promote.
5. **Reproducible.** Same source + same model + same prompt + temperature 0 → same output. Run id captures inputs.
6. **No re-runs against the same draft.** Operator either accepts and promotes, or edits the source and re-runs from scratch. No incremental "diff and update."
7. **Knowledge-source scope is narrow at v0.** Markdown and PDF. URL/transcript/codebase deferred.

---

## 5. Success Criteria

| Dimension | Goal |
|:---|:---|
| Throughput | One ~10-page PRD → 3–5 epic-shaped drafts in ≤2 min |
| Operator review time | ≤15 min per draft before promotion |
| Promotion rate | ≥60% of drafts promoted without operator-side rewrites |
| task-generator compatibility | 100% of promoted files parse cleanly through `task-generator/parser.py` |
| Reproducibility | Same input + same model → byte-identical render output |

Operator experience target: drop a PDF, run `generator run`, read the drafts, promote 3 of 5, delete 2. Total: ~20 min from PDF to Plane page.

---

## 6. Non-Goals

- **Direct Plane / Grava writes.** Belongs to `task-generator` + `upload_project_pages.py`.
- **Multi-doc synthesis.** v0 takes one source. Merging two PDFs into one outline → operator's job today.
- **Spec editing UX.** Drafts are markdown files; editor of choice. No web UI, no in-place CLI.
- **Codebase scan.** Reading a repo and inferring epics from module structure is a separate, harder problem. Out of scope.
- **URL / transcript ingestion.** Deferred until markdown+PDF prove out.
- **Bidirectional sync** between draft and source. Source changes → re-run, do not merge.
- **Auto-promotion.** Files always require human eyes before upload.

---

## 7. Phased Rollout

| Phase | Outcome | Status |
|:---|:---|:---|
| 1 | CLI scaffold: `extract`, `outline`, `render`, `run` argparse + smoke tests | ⬜ — covered by [`plan.md`](plan.md) |
| 2 | Markdown frontend: parse `*.md` → IR | ⬜ |
| 3 | PDF frontend: parse `*.pdf` via PyMuPDF → IR | ⬜ |
| 4 | LLM outline step: IR → hierarchy JSON via Anthropic SDK | ⬜ |
| 5 | Render step: hierarchy → H2/H3/H4 markdown matching task-generator format | ⬜ |
| 6 | Tests + golden samples (input PDF + expected draft) | ⬜ |
| 7 | Operator setup doc + `setup.sh` adds `pymupdf`/`anthropic` to deps | ⬜ |
| 8 | URL / transcript frontends | ⬜ deferred |
| 9 | Codebase-as-source | ⬜ deferred |

**Rule:** Phase 4 (LLM call) is gated on Phases 2–3 producing clean IR. Don't pay the LLM cost until the upstream is deterministic.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|:---|:---|
| LLM hallucinates an epic that wasn't in the source | Render step echoes section anchors back to source paragraphs; operator reviews anchored excerpts; low-confidence outlines flagged in frontmatter |
| PDF parsing drops figures / tables silently | `extract.py` records dropped element counts in `extract.json`; operator sees the gap before promotion |
| Source contains sensitive content (NDA, PII) | Generator's LLM call is the only network egress; operator opts in per-run via `--llm` flag; default offline mode produces extract.json only |
| Drafts pile up uncurated | `agents/generator/cli/doctor.py` (future) reports drafts older than N days |
| Reproducibility breaks when model versions change | Frontmatter records `generator_model` + `generator_model_version`; operator can diff drafts across model upgrades |
| Markdown frontmatter confuses downstream `task-generator/parser.py` | Parser already strips YAML frontmatter (verified by Phase 2 testing in [plan.md](plan.md)) |
| Operator promotes a draft that doesn't match Plane workspace conventions | Promotion is manual; the operator owns the spec format check |

---

## 9. Decision Log

**D1: Document-first input, not codebase.** PDFs and design docs are the most common Generator input in practice. Walking a codebase to infer epics is a much harder problem and would delay shipping. Codebase-as-source is Phase 9.

**D2: PyMuPDF over pdfplumber/pdfminer.** PyMuPDF is one binary dep, handles 95% of PDFs, including reasonable table extraction. Heavier deps unjustified at v0.

**D3: Anthropic SDK directly, not via MCP.** Generator is a batch tool, not an interactive agent. Direct SDK call with temperature 0 is simpler, deterministic, and avoids MCP wiring for non-conversational work.

**D4: One LLM call per outline.** Splitting into "extract", "cluster", "label" multi-call chains adds latency and failure surface for marginal quality gain at v0. Revisit if outline quality is below 60% promotion rate.

**D5: Outputs in `drafts/<system>/`, not `systems/<system>/business/`.** Promotion is manual. Mixing drafts with promoted specs in the same directory loses the boundary the operator relies on for review state.

**D6: No incremental re-run.** Source changes → re-run from scratch. Incremental update of a draft would invite drift between draft and rendered output. Cheap to re-run; expensive to debug a half-merged draft.

**D7: Frontmatter, not sidecar file.** `generator_*` keys live in the markdown itself so the draft is self-contained. Sidecar JSON would be lost when the operator copies the file into `systems/`.

---

## 10. Open Questions

1. **Anthropic model choice.** Sonnet (cheaper, fast) or Opus (higher quality, slower)? Recommend Sonnet at v0; switch lever in `llm_client.py` env var.
2. **PDF tables.** PyMuPDF returns tables as text. Should tables become task lists, leave as inline tables, or be flagged for operator?
3. **Multi-language source docs.** Initially English only. When a non-English PDF lands, do we translate, error, or pass through?
4. **Cost ceiling per run.** A 50-page PDF could cost $1+ in tokens. Add a `--max-tokens` cap?
5. **Where does `--llm` API key come from?** `~/.config/anthropic/credentials` analogous to Plane creds, or env var `ANTHROPIC_API_KEY`? Recommend env var.
6. **Draft filename collisions.** If two runs against the same source produce the same outline, do we suffix `-2`, overwrite, or refuse?
7. **task-generator extension to ignore `generator_*` frontmatter** vs. operator manually stripping it — which?

---

## 11. Anti-Strategy

The Generator is **not**:

- A document summarizer (it produces structured backlog, not a digest).
- A Plane uploader (`upload_project_pages.py` exists for that).
- A grava issue creator (only `task-generator` writes to grava).
- A spec linter (it does not validate operator-written specs).
- A knowledge management system (it reads docs; it does not store, search, or version them).
- A real-time assistant (one-shot batch tool; no streaming, no chat).
- A codebase analyzer (Phase 9, separate effort).

Boundary: **one source doc → reviewable spec drafts on disk.** Past that line is the operator's call.
