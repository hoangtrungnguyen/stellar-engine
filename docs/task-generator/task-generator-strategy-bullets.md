# Strategy: Building the task-generator Agent

## 1. Goal

- A stellar-engine sub-agent that turns a Plane spec page into a complete work hierarchy on both Plane and Grava.
- Creates an epic, stories, and tasks in Plane, then mirrors the same hierarchy in Grava inside the target repository.
- Planner only — never claims work, never runs the ship pipeline, never writes source code.

## 2. Scope

**In scope**
- Reading one Plane spec page per invocation. Sub-page expansion is deferred until Plane ships a public sub-pages listing endpoint (tracked in #7319 / #8598).
- Creating the epic, stories, and tasks in Plane via the Plane REST API.
- Creating the same hierarchy in Grava using the create command for the epic and the subtask command for descendants, preserving native parent-child structure on both sides.
- Idempotency, dry-run mode, and rollback on failure.

**Out of scope**
- Multi-repo fan-out (orchestrator's job).
- Syncing state changes from Grava back to Plane (separate sync agent).
- Claiming or implementing work.
- Editing the spec page itself.

## 3. Architecture Decisions

**Plane API surface**
- Plane REST API is the primary interface for issue CRUD (create, read, update, delete) and for everything the agent needs to write to Plane: work items, comments, labels, parent links, and issue-type lookup.
- Endpoints (all under `https://api.plane.so/api/v1/workspaces/{workspace}/...`, auth `X-API-Key`):
  - Work items — `POST/GET/PATCH/DELETE /projects/{p}/work-items/{id}/`. Payload supports `name`, `description_html`, `type_id`, `parent` / `parent_issue_id`, `labels: [uuid,...]`, `priority`, `assignees`, `state`.
  - Issue types — `GET /projects/{p}/work-item-types/` for the per-run UUID lookup.
  - Comments — `POST/GET/PATCH/DELETE /projects/{p}/issues/{id}/comments/{comment_id}/` with `comment_html`.
  - Labels — `GET /projects/{p}/labels/` and `POST /projects/{p}/labels/`.
- Use the new `/work-items/` path, not the deprecated `/issues/` path (end of support 2026-03-31).
- Credentials: `~/.config/plane/config.json` (`token`, `host`, `workspace`) or env vars `PLANE_API_TOKEN`, `PLANE_HOST`, `PLANE_WORKSPACE` — same loader pattern as `upload_project_pages.py`.
- plane-mcp is optional. If connected, the agent may use it opportunistically for convenience tools (e.g. sub-issue conversion helpers, paginated work-item search), but it is never required.
- No plane-cli — `@aaronshaf/plane`'s surface (`projects list / issues list / issue create`) cannot satisfy types, parents, comments, or pages, so it is not in the picture.

**Page content format**
- Plane's public REST API returns page content as `description_html`; there is no markdown-export endpoint (markdown export is a UI-only feature).
- The agent fetches HTML via `GET /projects/{p}/pages/{page_id}/`, then converts to Markdown locally (e.g. `html2text` or `markdownify`) for parsing.
- Markdown is the internal pivot format because it parses headings and bullets without surprises; HTML is just the wire format.
- Page UPDATE / DELETE on Plane Cloud is also not in the public REST API yet (tracked in #7319 / #8598). The agent never writes back to the spec page anyway, so this only matters if tooling around the agent ever needs to.

**Hierarchy mapping**
- H2 headings become epics.
- H3 headings become stories.
- Bullet points under a story become tasks.
- Authors can override the type with inline markers like a Bug or P0 prefix.
- Sections titled "Out of scope" are skipped entirely.
- Sections titled "Open questions" or "Risks" are captured as comments on the epic.

**Grava hierarchy**
- Use the standard create command for the epic to obtain a base ID.
- Use the subtask command for stories under the epic, producing dotted IDs.
- Tasks are created as subtasks of their parent story via the subtask command (Grava supports unlimited nesting depth). They carry labels (`plane:`, `plane-story:`, `plane-epic:`) and the parent story's URL in their description for navigation.

**Cross-linking — two channels**
- Labels: every Grava issue carries three labels (own Plane sequence ID, parent story ID, parent epic ID); queryable for rollups.
- Description: every Grava issue embeds the URL of its corresponding Plane work item, plus its Plane parent's URL, plus (for tasks) the original spec page URL.
- Metadata: the Plane URL is also stored in the Grava issue's metadata field, giving structured (non-prose) access for tooling that doesn't want to parse description text.
- Labels are queryable, descriptions give one-click navigation, metadata gives programmatic access.

**Write order**
- Strictly top-down on each side: epic before stories before tasks.
- Plane is fully written before any Grava write begins (Grava labels need Plane sequence IDs).

**Repo-aware CLI usage**
- Read the target repo's agent-instructions guide and CLI reference at runtime.
- Never hardcode Grava flag spelling — it drifts across repos and versions.

**Plane typed issues (paid tier)**
- Use Plane's native epic, story, and task issue types via the type field on creation.
- The agent must look up each type's UUID once per project and cache it for the run.

**Plane related-issue links — deferred**
- Issue relations (`blocks` / `blocked_by` / `relates_to` / `duplicate`) are not exposed in plane-mcp or in Plane's public REST API as of mid-2026. The internal `/api/workspaces/.../issue-relation/` endpoint exists but is not under `/api/v1/`. Tracked in #5079 and #6236.
- Phase 2 does NOT create native relation objects in Plane.
- Cross-reference signal from the spec is preserved as plain text in the issue description: a "Related:" line listing the referenced Plane sequence IDs (e.g. `Related: STELLAR-12, STELLAR-15`). This keeps the information traceable and grep-able even without native relation links.
- When Plane ships a public relations endpoint, native linking is added in a follow-up phase; the description-text format is forward-compatible (the agent can read its own past output to upgrade existing issues).

## 4. Build Phases

**Phase 1 — Skeleton + dry-run (1 session)**
- Agent file lands in stellar-engine with full system prompt and parsing logic.
- Preview shows both Plane targets and Grava targets.
- No writes. Usable for human review against real spec pages.

**Phase 2 — Plane writes (1 session)**
- Create epic, stories, and tasks in correct top-down order via Plane REST.
- Attach provenance footers (spec-page URL on epic, parent URLs on descendants).
- Record open questions and risks as epic comments.
- Capture cross-reference signal from the spec as plain text in issue descriptions (a "Related:" line listing referenced sequence IDs); native relation links are deferred until Plane ships the public API.
- Track every created ID for rollback.

**Phase 3 — Grava mirror (1 session)**
- Read the target repo's agent guide and CLI reference first.
- Create the epic via the create command. Capture its Grava ID.
- Create each story via the subtask command under the epic. Capture each story's Grava ID.
- Create each task via the subtask command under its parent story. Carry the parent story's Grava ID in the description for traceability.
- Apply the three Plane labels to every Grava issue.
- Embed the Plane URL in every Grava description; tasks additionally embed their parent story's Plane URL and the spec page URL.
- Comment the Grava ID back on the matching Plane work item.
- Commit Grava state and emit a structured JSON report.

**Phase 4 — Hardening (1 session)**
- Idempotency check: search Plane and Grava for existing items referencing the spec page; on match, compute a field-by-field diff, show it in the preview, and require user confirmation before applying updates.
- Orphan detection: items present on Plane or Grava but missing from the latest spec are flagged as "orphaned" — never auto-deleted.
- Wire failure-mode table to real recovery flows.
- End-to-end smoke test on a real spec page and a scratch repo.

**Effort:** ~4 focused sessions. Phase 1 is independently useful even before writes are enabled.

## 5. Decisions (all resolved)

- **Plane tier — Paid.** Use Plane's typed issues (epic/story/task) via the type field. Agent caches type UUIDs once per project per run.
- **Workspace conventions — None.** Use Plane workspace defaults for prefix, initial state, cycle, and module.
- **Plane access — REST primary, plane-mcp optional.** The agent talks to Plane through the REST API (`X-API-Key` against `https://api.plane.so/api/v1/...`) for all issue CRUD, types, comments, and labels. Credentials are read from `~/.config/plane/config.json` or the `PLANE_API_TOKEN` / `PLANE_HOST` / `PLANE_WORKSPACE` env vars. plane-mcp is not required; if it is connected the agent may use it for convenience helpers, but the agent must function with REST alone.
- **Target repo selection — Agent picks.** The orchestrator does not pass a repo path; the agent looks up the target repo from a stellar-engine Plane-project-to-repo mapping (location TBD — likely a config file in the stellar-engine root).
- **Idempotency policy — Update.** On a second run against the same spec page, reconcile existing Plane and Grava items field-by-field instead of aborting. Show the diff in the preview and require user confirmation before applying. Never delete items that exist on Plane or Grava but not in the latest spec page (flag them as "orphaned" instead).
- **Grava subtasks — Top level only.** Subtasks exist only at the folder (top) level in the target repo. The agent can create stories as subtasks of an epic, but tasks cannot be subtasks of a story. Tasks are created as flat issues with cross-link labels (`plane:`, `plane-story:`, `plane-epic:`) and the parent story's URL embedded in the description.
- **Dry-run output — Markdown file.** When run with dry-run enabled, write the preview to a `.md` file in the target repo (or stellar-engine workspace) and print its path. Console output stays as a short summary so the orchestrator can still parse it.

## 6. Risks and Mitigations

- **Half-created hierarchy on mid-flight failure** — track every ID as it lands; on unrecoverable failure ask before rolling back, then delete reverse-order: Grava tasks, Grava stories, Grava epic, Plane tasks, Plane stories, Plane epic.
- **Plane platform gaps** — issue relations and page update/delete are not in the public REST API yet (#5079, #6236, #7319, #8598). Mitigation: relations preserved as text in descriptions; the agent never writes back to spec pages. Re-evaluate when the endpoints ship.
- **Update-policy drift** — repeated runs against an evolving spec page can quietly desync field values. Mitigation: always show the field-by-field diff in the preview and require explicit confirmation; log every update to the run report.
- **Orphaned items pile up** — items removed from the spec are flagged but never auto-deleted, so cruft accumulates. Mitigation: surface the orphan count prominently in the run report; recommend a periodic human cleanup pass.
- **Spec-page format ambiguity** — ignore fenced code blocks, cap depth at H3, surface unparseable sections as preview warnings rather than silently dropping them.
- **Plane API rate limits** — sequential writes with backoff on 429 responses.
- **Grava CLI flag drift** — re-read the target repo's docs at runtime; never hardcode flags in the agent prompt.
- **Duplicate runs creating duplicates** — blocked by the Phase 4 idempotency check.
- **Token leakage through logs** — reference env vars by name only; never echo the Plane API token.

## 7. Success Criteria

The finished agent must be able to:

- Produce a correct preview tree without writing anything in dry-run mode; write the full preview to a Markdown file and print its path.
- Create the full Plane hierarchy (typed epic/story/task) in correct parent order, with provenance footers on every item.
- Create a matching Grava structure: epic via the create command, stories as subtasks of the epic, tasks as subtasks of their parent story.
- Capture spec cross-references as a "Related:" line in each issue description (native relation links are deferred until Plane ships the public API).
- Apply the three Plane labels and embed the corresponding Plane URL in the description on every Grava issue.
- Comment the matching Grava ID back on each Plane work item.
- Commit Grava state and emit a JSON report listing every ID created and every update applied on both sides.
- On a second run against the same spec page, show a field-by-field diff and require confirmation before updating; flag any orphaned items without deleting them.
- Roll back cleanly if interrupted between the Plane and Grava phases.

## 8. Deliverables

- The agent file inside stellar-engine.
- A short operator guide covering invocation, environment variables, and troubleshooting.
- A smoke-test transcript against a throwaway Plane page and a scratch repo.

## 9. Next Step

- All open decisions are resolved. Build Phase 1.
- Validate parsing on two or three real spec pages before moving to Phase 2.
