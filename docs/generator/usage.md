# Generator agent — operator walkthrough

End-to-end recipe for turning a markdown source document into Plane work items + a grava mirror, using only what ships in stellar-engine today (no Anthropic API key required).

The chain has five operator-visible steps:

```
spec.md   ── 1 extract ──>  extract.json
                         ── 2 outline ──>  outline.json     (manual via Claude Code session)
                                        ── 3 render ──>     drafts/<proj>/runs/<RID>/drafts/*.md
                                                         ── 4 promote ──>  systems/<Name>/business/spec.md
                                                                        ── 5 task-generator ──>  Plane + grava
```

Steps 1–3 are the **Generator agent** (this doc). Step 4 is a manual file copy + git commit. Step 5 is the **task-generator agent** (see [`agents/task-generator/AGENT.md`](../../agents/task-generator/AGENT.md)).

---

## Prerequisites

- `bash setup.sh` has been run at least once (installs `markdown`, `markdownify`, `requests`, `pyyaml`).
- `.env` is populated. Copy from [.env.example](../../.env.example) and fill in:
  ```
  PLANE_WORKSPACE=<workspace-slug>
  PLANE_HOST=https://api.plane.so
  PLANE_API_TOKEN=<plane personal access token — never commit>
  PLANE_PROJECT_ID=<short identifier, e.g. STELL>
  SANDBOX_REPO=<absolute path to target repo>
  STELLAR_ENGINE_HOME=<absolute path to stellar-engine>
  ```
  Then `set -a; source .env; set +a` to load into the current shell.
- The target repo (where the spec eventually lands) lives as a sibling of `stellar-engine/` and has been `grava init`'d.
- `repo-map.yaml` has an entry mapping the Plane project UUID to the target repo (use `python3 agents/task-generator/cli/resolve_repo.py <project_uuid>` to verify).
- `python3 cli/se doctor --dir .` is green (or has only the expected warnings: `anthropic`, `pymupdf`, `drafts/`).

---

## Step 1 — Extract: markdown → IR

```bash
se generate path/to/spec.md --project STELL --no-llm
```

This step:
- Creates `drafts/STELL/runs/<RID>/` where `<RID>` is a UTC timestamp (override with `--run-id`).
- Parses the source markdown into a `Section` tree (H1/H2/H3/H4 + paragraphs / lists / code / tables).
- Writes `extract.json` to the run directory.
- Stops there. With `--no-llm`, no further steps run.

**Output:**
```
drafts/STELL/runs/20260516T120937Z/
├── run.json
└── extract.json
```

If you want a one-shot extract without creating an outline yet, this is the command. Use `--dry-run` for the same behaviour with slightly different intent semantics; either way the chain halts after extract.

---

## Step 2 — Outline: IR → epic/story/task hierarchy (manual today)

Phase D (automated LLM call via the Anthropic SDK) is deferred until API key budget exists. Until then, the outline step runs **manually inside a Claude Code session** — your Claude Code subscription covers it.

1. Open the file produced by Step 1 in your editor or copy its contents:
   ```bash
   cat drafts/STELL/runs/20260516T120937Z/extract.json
   ```
2. Open a Claude Code session. Paste the JSON. Ask Claude to produce an `outline.json` matching this schema (also documented in [`docs/generator/plan.md` §D2](plan.md)):
   ```json
   {
     "epics": [
       {
         "title": "...",
         "summary": "...",
         "source_anchors": ["..."],
         "depends_on": ["<other epic title or EPIC-N slug>"],
         "stories": [
           {
             "title": "...",
             "description_md": "As a stakeholder, I want…, so that…",
             "depends_on": [],
             "source_anchors": ["..."],
             "tasks": ["Task 1 title", "Task 2 title"],
             "acceptance_criteria": ["Criterion 1", "Criterion 2"],
             "design_links": [
               {"label": "Figma — Booking flow", "url": "https://figma.com/..."},
               {"label": null, "url": "design/mockup.png"}
             ]
           }
         ]
       }
     ],
     "confidence": 0.78
   }
   ```
   - `tasks` is a list of strings (titles only). Each becomes a `TaskNode` + a Plane task work item downstream.
   - `acceptance_criteria` is a list of strings — story-level criteria.
   - `design_links` is optional. Each entry is `{label, url}`; `label: null` renders as a bare URL/path.
   - Both `acceptance_criteria` and `design_links` are **story-level** (not epic-level).
   - `epics[].depends_on` is optional (default `[]`) and carries **epic-level** dependency refs (another epic's title or `EPIC-N` slug). Render emits a `> Depends on: …` blockquote under the H2; task-generator turns it into Plane `blocking` relations after epics exist.
3. **If the source has a `## Epic dependencies` Mermaid block**, `extract.json` carries the parsed edges under `epic_dependencies`. See [`epic-dependencies.md`](epic-dependencies.md) for the full authoring guide — grammar, label normalisation, fan-out examples, and a copy-paste template. Quick recap:
   ```markdown
   ## Epic dependencies

   ```mermaid
   graph TD
     A[Authentication] --> B[Court Booking]
     B --> C[Cancellations]
   ```
   ```
   yields
   ```json
   "epic_dependencies": [
     {"from": "Authentication", "to": "Court Booking"},
     {"from": "Court Booking",  "to": "Cancellations"}
   ]
   ```
   Mermaid `A --> B` means "A leads to B" → **B depends on A**. Fold each edge `{from: A, to: B}` into `Epic(title=B).depends_on += [A]` when authoring `outline.json`. Use bracket labels (`A[Court Booking]`) for multi-word epics so the labels match epic titles directly.
4. Save the JSON to the run directory:
   ```bash
   $EDITOR drafts/STELL/runs/20260516T120937Z/outline.json
   # paste the JSON Claude produced, save
   ```

---

## Step 3 — Render: outline → markdown drafts

```bash
se generate path/to/spec.md --project STELL --step render --system-name "Stellar Sandbox Demo"
```

This step:
- Reads `<run-dir>/outline.json`.
- Emits one markdown file per epic into `<run-dir>/drafts/`, filename `YYYY-MM-DD-<slug>.md`.
- Writes `manifest.json` listing what landed.
- If a prior run exists for the same source, prints a structured diff (epics/stories/tasks added/removed/renamed) and persists it as `diff.json`.

**Output:**
```
drafts/STELL/runs/20260516T120937Z/
├── run.json
├── extract.json
├── outline.json
├── drafts/
│   ├── 2026-05-16-court-booking.md
│   └── 2026-05-16-cancellations.md
└── manifest.json
```

Each draft has frontmatter with `generator_source`, `generator_run_id`, `generator_confidence`, `generator_model`, `generator_model_version`, plus the body shaped per [`docs/task-generator/parser.md`](../task-generator/parser.md) hierarchy rules.

Inspect one before promoting:
```bash
less drafts/STELL/runs/<RID>/drafts/2026-05-16-court-booking.md
```

---

## Step 4 — Promote a draft to the target repo

The operator chooses which draft (often one epic at a time) to promote. There is no auto-promotion.

```bash
# Pick one draft and copy it as the new spec.
mkdir -p $SANDBOX_REPO/systems/STELL/business
cp drafts/STELL/runs/<RID>/drafts/2026-05-16-court-booking.md \
   $SANDBOX_REPO/systems/STELL/business/spec.md

# Commit + push (manual).
cd $SANDBOX_REPO
git add systems/STELL/business/spec.md
git commit -m "docs(STELL): promote Court Booking spec draft"
git push
```

The frontmatter rides along on disk. It's harmless for downstream parsers (task-generator's parser starts from the H2 and ignores everything above it), but **does** show up as a `<hr>`-bounded paragraph on the Plane page in Step 5. See [Known limitations](#known-limitations).

---

## Step 5 — Upload to Plane + run task-generator

```bash
# Upload the promoted spec to a Plane page.
python3 upload_project_pages.py $PLANE_PROJECT_UUID \
    $SANDBOX_REPO/systems/STELL/business/spec.md
# → CREATE  <path>  →  '<H1 title>'
# → Mapping saved to .plane-pages.json
```

The new page UUID is recorded in `.plane-pages.json` (gitignored). Grab it for the next command, or read it from the Plane URL after opening the page.

```bash
# Dry-run task-generator first.
python3 agents/task-generator/cli/run.py $PLANE_PROJECT_UUID <page_uuid> \
    --dry-run --target-repo $SANDBOX_REPO

# Review the preview at $SANDBOX_REPO/runs/preview/<RID>/...master.preview.md
# Confirm op count, no warnings, no unexpected duplicates / orphans.

# Real write (creates Plane work items + mirrors to grava).
python3 agents/task-generator/cli/run.py $PLANE_PROJECT_UUID <page_uuid> \
    --target-repo $SANDBOX_REPO --yes --on-failure abort
```

The report at `$SANDBOX_REPO/runs/reports/<RID>.json` lists every Plane work item created, every grava ID assigned, and the "Mirrored to Grava" comment IDs posted back.

---

## Re-running on a changed source

Just run the chain again with a fresh `--run-id` (or omit `--run-id` to get a new UTC timestamp). The chain:

1. Extracts the new spec into a new run directory.
2. You hand-write a new `outline.json` (or copy the previous one and edit).
3. On render, it locates the most recent prior run for the same source that has an `outline.json`, computes the diff, prints it, and writes `diff.json`. Runs that stopped before producing an outline (dry-run leftovers) are skipped silently.

Use the diff to decide whether to promote. The new drafts are written either way — there is no hard failure.

For Step 5: re-upload the same promoted file. `upload_project_pages.py` uses the path → page-UUID mapping in `.plane-pages.json` to update the existing page instead of creating a new one. task-generator's reconciliation (`reconcile.py`) then compares the spec against existing Plane items via the `tg:src:<page-uuid>` sentinel label and decides what to create / update.

---

## Common flag combinations

| Intent | Command |
|---|---|
| Just look at the IR | `se generate spec.md --project FOO --dry-run` |
| Run only extract | `se generate spec.md --project FOO --step extract` |
| Render against a pre-placed outline | `se generate spec.md --project FOO --step render` |
| Use a stable run id | `se generate spec.md --project FOO --run-id RID-1` |
| Override the H1 system name | `se generate spec.md --project FOO --system-name "My System"` |
| Write to a custom drafts root | `se generate spec.md --project FOO --drafts-root /tmp/work` |

`--llm` is reserved for Phase D and currently exits 1 with a Phase D pointer.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: source not found` | Path mistyped | Check the path; spec must be a real file with `.md` suffix. |
| `ERROR: only .md sources supported (got .pdf)` | Non-markdown source | PDF / URL / transcript / codebase frontends are deferred. Convert to markdown. |
| `ERROR: no outline.json present and --llm not passed` | Default chain ran without a hand-placed outline | Do Step 2 (manual outline via Claude Code session), save into the run dir, re-run with `--step render`. |
| `ERROR: Phase D (LLM outline) is deferred` | `--llm` requested | Use `--no-llm` and the manual outline workflow. |
| `ERROR: outline.json not found` (render step) | Run dir is empty | Same as above. |
| `ERROR: invalid outline shape` | Hand-written outline missing required keys | Open `outline.json`, ensure `epics[].title`, `epics[].stories[].title`, and `confidence` are present. Compare against the schema in [plan.md §D2](plan.md). |
| Frontmatter appears as a visible block on the Plane page | Known limitation — see below | Strip frontmatter manually before upload, or open a PR to add `--strip-frontmatter` to `upload_project_pages.py`. |
| `se doctor` shows `python: markdown ✗` or similar | Missing pip deps | `bash setup.sh` to install. |

---

## Known limitations

1. **Plane page frontmatter.** `upload_project_pages.py` does not strip the generator's YAML frontmatter before HTML conversion. It appears at the top of the Plane page as an `<hr>`-bounded paragraph block. task-generator's parser ignores it (parses from H2), but it's visible to humans. Tracked as a deferred item in [`docs/generator/plan.md` §1](plan.md).

2. **Phase D deferred.** No automated LLM outline today. Use the manual Claude Code session workflow in Step 2.

3. **Single source per run.** No multi-document synthesis. One markdown file in, one or more spec drafts out.

4. **No auto-promotion.** The operator copies a chosen draft into `systems/<Name>/business/` by hand (Step 4). This is by design — the human in the loop is the review gate.

---

## See also

- [agents/generator/AGENT.md](../../agents/generator/AGENT.md) — agent prompt (used when Claude is invoked as a sub-agent on this pipeline).
- [agents/generator/README.md](../../agents/generator/README.md) — quick reference.
- [docs/generator/plan.md](plan.md) — implementation plan with status.
- [docs/task-generator/parser.md](../task-generator/parser.md) — downstream parser rules; the generator output must match.
- [agents/task-generator/AGENT.md](../../agents/task-generator/AGENT.md) — Step 5 details.
