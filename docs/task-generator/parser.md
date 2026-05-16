# Parser

Lives in `agents/task-generator/parser.py`. Turns a Plane page (HTML) into the IR (`EpicNode` tree, see [data-model.md](data-model.md)).

## Pipeline

1. **Fetch HTML** — `client.get_page(project_id, page_id)["description_html"]`.
2. **Convert to Markdown** — `markdownify(html, heading_style="ATX")`. Prefer `markdownify` over `html2text` because it handles tables and fenced code more reliably.
3. **Strip fenced code blocks** before structural parsing (re-attach as raw text in the owning node's description so they don't get lost).
4. **Walk the token stream** and produce the IR.

## Mapping Rules

From strategy §3 "Hierarchy mapping":

- `H1` is treated as the page title; not part of the tree.
- `H2` → `EpicNode`. The agent currently expects exactly one H2 per spec; warn if more than one.
- `H3` → `StoryNode` under the most recent H2.
- Bullet items directly under a story → `TaskNode` (only bullets *before* an Acceptance Criteria marker).
- **Acceptance Criteria block** — bold marker `**Acceptance Criteria:**` (case-insensitive, trailing colon optional) on its own line under a story. Every bullet from the marker until the next H2/H3/marker terminates the block is appended to `story.acceptance_criteria` as a plain string (markdown preserved, bullet prefix stripped). Bullets in this block are **not** turned into `TaskNode`s.
- Headings `H4`+ are folded into the description of the nearest enclosing story or task.
- Section titles **"Out of scope"** (case-insensitive, any heading level) → skip the entire section and its children.
- Section titles **"Open questions"** / **"Risks"** at H2 or H3 level under the epic → captured into `epic.open_questions` / `epic.risks` as a list of bullets.
- Inline type markers — title prefix `Bug:`, `P0:`, `P1:`, `Spike:` → strip the prefix from `title` and store in `type_marker`.
- Cross-references — regex `(?:[A-Z]{2,10})-\d+` (workspace-prefix configurable per run) → store in `related_refs`. Matches both bare IDs (`STELLAR-12`) and parenthesised IDs (`(STELLAR-12)`).

## Output

Returns:

- An `EpicNode` (root of the IR tree).
- A `list[ParseWarning]` for unparseable structures: heading-without-parent, unknown section title under the epic, multiple H2s, etc.

Warnings are surfaced in the preview rather than silently dropped — see [planner.md](planner.md).

## See Also

- [data-model.md](data-model.md) — IR shapes.
- [plane-client.md](plane-client.md) — `get_page` source.
- [planner.md](planner.md) — consumer of the IR + warnings.
