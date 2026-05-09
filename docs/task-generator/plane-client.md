# Plane REST Client

Lives in `agents/task-generator/plane_client.py`. Wraps the Plane public REST API at `https://api.plane.so/api/v1/...`.

## Method Surface

```python
class PlaneClient:
    def __init__(self, host: str, workspace: str, token: str): ...

    # ── Pages ────────────────────────────────────────
    def get_page(self, project_id: str, page_id: str) -> dict
        # GET /projects/{p}/pages/{page_id}/
        # Returns description_html.

    # ── Work-item types ──────────────────────────────
    def list_work_item_types(self, project_id: str) -> list[dict]
        # GET /projects/{p}/work-item-types/
        # Returns [{id, name, ...}]; cached for the run.

    # ── Work items ───────────────────────────────────
    def create_work_item(self, project_id: str, payload: dict) -> dict
        # POST /projects/{p}/work-items/
        # Payload: name, description_html, type_id, parent (UUID),
        #          labels [uuid,...], priority, assignees, state

    def get_work_item(self, project_id: str, issue_id: str) -> dict
    def update_work_item(self, project_id: str, issue_id: str, payload: dict) -> dict
    def delete_work_item(self, project_id: str, issue_id: str) -> None
    def search_work_items(self, project_id: str, **filters) -> list[dict]
        # Use label or text-search filters for idempotency lookups.

    # ── Comments ─────────────────────────────────────
    def add_comment(self, project_id: str, issue_id: str, comment_html: str) -> dict
        # POST /projects/{p}/issues/{id}/comments/

    # ── Labels ───────────────────────────────────────
    def list_labels(self, project_id: str) -> list[dict]
    def create_label(self, project_id: str, name: str, color: str = "#888") -> dict
```

## Conventions

- **Auth header:** `X-API-Key: <token>`.
- **Base URL builder:** `f"{host}/api/v1/workspaces/{workspace}/{path}"`.
- **Endpoint path:** use the new `/work-items/` path, never the deprecated `/issues/` path (end of support 2026-03-31).
- **Backoff:** retry on `429` honouring `Retry-After` (default 5s, max 5 attempts). Exponential backoff on `5xx` (1s, 2s, 4s; max 3 attempts).
- **Token never logged.** Load via env (`PLANE_API_TOKEN`) or `~/.config/plane/config.json` and reference by name only — no echoing in error messages or run reports.
- **Error mapping.** `4xx` other than `429` raise `PlaneClientError` with status, response body, and the failed request URL. Callers decide whether to retry or roll back.

## Capability Gaps (handled upstream of the client)

These Plane operations are not in the public REST API as of mid-2026 and are deliberately *not* exposed by this client:

- Issue relations (`blocks` / `relates_to` / `duplicate`) — preserved as text in descriptions instead. Tracked in [makeplane/plane#5079](https://github.com/makeplane/plane/issues/5079) and [#6236](https://github.com/makeplane/plane/issues/6236).
- Page UPDATE / DELETE — tracked in [#7319](https://github.com/makeplane/plane/issues/7319) and [#8598](https://github.com/makeplane/plane/issues/8598). The agent never writes back to spec pages.
- Sub-pages listing endpoint.
- Markdown-export endpoint (UI-only feature) — the agent fetches HTML and converts locally.

## See Also

- [parser.md](parser.md) — calls `get_page`.
- [planner.md](planner.md) — calls `list_work_item_types`, `list_labels` in pre-flight.
- [writers.md](writers.md) — calls every write method.
