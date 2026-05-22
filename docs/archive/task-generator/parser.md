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
- Plain text / paragraphs between the H3 and the first bullet or H4 → folded into `story.description_md` (typical content: "As a stakeholder, I want… so that…").
- Bullet items directly under a story, **before** any H4 subsection → `TaskNode` (one per top-level bullet).
- **H4 subsections under a story** switch to a typed bucket — bullets that follow are captured into the corresponding `StoryNode` field, not as `TaskNode`s:
  - `#### Acceptance Criteria` (case-insensitive, trailing colon optional) → `story.acceptance_criteria: list[str]`. Each bullet becomes one criterion (bullet prefix stripped, inline markdown preserved).
  - `#### UI/UX Design` (also accepts `#### Design`, `#### UX`, `#### UI`) → `story.design_links: list[DesignLink]`. Each bullet becomes one `DesignLink`. Bullet `[Label](url)` → `{label, url}`; bare URL or plain text → `{label: null, url}`. Free-form notes that aren't links land in `url` with `label=null`.
  - Any other H4 text → fold the bullets into `story.description_md` and emit a `unknown_section` warning so the operator can rename the heading.
- A new H2, H3, or H4 resets the active bucket. So a story can have `Tasks → AC → UI/UX` in any order; each H4 terminates the previous bucket.
- Section titles **"Out of scope"** (case-insensitive, any heading level) → skip the entire section and its children.
- Section titles **"Open questions"** / **"Risks"** at H2 or H3 level under the epic → captured into `epic.open_questions` / `epic.risks` as a list of bullets.
- Inline type markers — title prefix `Bug:`, `P0:`, `P1:`, `Spike:` → strip the prefix from `title` and store in `type_marker`.
- Cross-references — regex `(?:[A-Z]{2,10})-\d+` (workspace-prefix configurable per run) → store in `related_refs`. Matches both bare IDs (`STELLAR-12`) and parenthesised IDs (`(STELLAR-12)`).

### Example

```markdown
## Epic 1: Court Booking

### US-01 — Pick a court
As a customer, I want to browse available courts, so that I can pick one.

- Render the map widget
- Wire location services
- Fetch courts within radius

#### Acceptance Criteria
- Map shows pins within 5 km of current location
- Pin colour reflects availability
- Tapping a pin opens the court detail sheet

#### UI/UX Design
- [Figma — Booking flow](https://figma.com/file/XXX/booking)
- `design/booking-mockup.png`
- Map pin shape: 32×40px teardrop, white 1.5px outline
```

Parses to:
- `EpicNode(title="Epic 1: Court Booking")`
  - `StoryNode(title="US-01 — Pick a court")`
    - `description_md`: "As a customer, I want to browse available courts, so that I can pick one."
    - `tasks`: 3 `TaskNode`s ("Render the map widget", …)
    - `acceptance_criteria`: 3 strings
    - `design_links`: 3 `DesignLink`s — first two with labels, the third with `label=null`

## Output

Returns:

- An `EpicNode` (root of the IR tree).
- A `list[ParseWarning]` for unparseable structures: heading-without-parent, unknown section title under the epic, multiple H2s, etc.

Warnings are surfaced in the preview rather than silently dropped — see [planner.md](planner.md).

## See Also

- [data-model.md](data-model.md) — IR shapes.
- [plane-client.md](plane-client.md) — `get_page` source.
- [planner.md](planner.md) — consumer of the IR + warnings.
