# `se download`

Pull Plane project pages to local markdown files. Read-only; never writes back to Plane.

## Synopsis

```
se download <project_id>
            [--page-id <UUID> | --page-name "<name>"]
            [--output-root <DIR>]
            [--include-private]
            [--dry-run]
            [--plane-profile <NAME> | --plane-config <PATH>]
```

## What it does

1. Resolves `<project_id>` to a Plane project UUID + short identifier (e.g. `CAPP`).
2. Lists pages in that project via the Plane REST API.
3. Filters to **public pages only** by default (skip with `--include-private`).
4. For each surviving page, fetches `description_html`, converts to markdown, and writes:

   ```
   <output-root>/<workspace>/<project-code>/<page-slug>.md
   ```

5. Each file ships a YAML frontmatter block (`plane_page_id`, `plane_workspace`, `plane_project_id`, `downloaded_at`) so the round-trip uploader (`upload_project_pages.py`) can match files to pages.

When `--page-id` or `--page-name` is set, the listing is skipped and only that one page is downloaded.

## Arguments

| Arg | Purpose | Notes |
|---|---|---|
| `<project_id>` | Required positional | Plane project UUID **or** short identifier (`CAPP`, `STELL`, …). Codes resolve via the workspace's projects listing (case-insensitive). |

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--output-root <DIR>` | `systems` | Root directory under which `<workspace>/<project-code>/` is created. |
| `--page-id <UUID>` | — | Download only this page. Mutually exclusive with `--page-name`. The explicit UUID path bypasses the public-only filter — operator knows exactly what they want. |
| `--page-name "<name>"` | — | Download the page whose name **exactly** matches (case-sensitive). Mutually exclusive with `--page-id`. Honours the public-only default unless `--include-private` is also set. Exits **2** if two or more pages share the name; use `--page-id` then. |
| `--include-private` | off | Widens the candidate pool to private (`access=1`) pages. Affects both listing mode and `--page-name` resolution. Single-page `--page-id` is unaffected (always downloads). |
| `--dry-run` | off | List what would be written; touch nothing on disk. |
| `--plane-profile <NAME>` | — | Load creds from `~/.config/plane/<NAME>.json` instead of the default `config.json`. |
| `--plane-config <PATH>` | — | Load creds from an explicit JSON file path. Overrides `--plane-profile`. |

### Credential resolution order (highest → lowest)

1. Direct env vars (`PLANE_API_TOKEN`, `PLANE_WORKSPACE`, `PLANE_HOST`) — each takes precedence individually.
2. `--plane-config <PATH>` flag.
3. `PLANE_CONFIG` env var (absolute path to a JSON file).
4. `--plane-profile <NAME>` flag.
5. `PLANE_PROFILE` env var → `~/.config/plane/<NAME>.json`.
6. Default `~/.config/plane/config.json`.

## Output layout

```
<output-root>/
└── <workspace>/
    └── <PROJECT_CODE>/             ← uses the short identifier (CAPP), not the UUID
        ├── architecture.md
        ├── roadmap.md
        └── foo-service.md
```

Slugging rules (from `slugify` in `download_project_pages.py`):

- Lowercase
- Replace whitespace with `-`
- Strip everything that isn't `[a-z0-9-]`
- If two pages slugify to the same name, the second one gets the first 8 chars of its UUID appended (e.g. `foo-service-5e964772.md`)

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | resolver / not-found failure (unknown project code, `--page-name` matched no public page) |
| 2 | usage / argparse error, fetch failure, **or** `--page-name` matched multiple pages |

## Recipes

### Pull every public page in a project

```bash
se download CAPP
# → systems/<workspace>/CAPP/*.md
```

Output ends with a summary line:

```
Pages to process: 7 of 10 total (public only; skipped 3 private page(s) — pass --include-private to include them)
```

### Download one page by UUID

Best when you have the exact UUID from the Plane web UI (URL bar):

```bash
se download CAPP --page-id 5e964772-ca74-4023-8fd0-b1282112381f
# → systems/<workspace>/CAPP/<page-slug>.md
```

The `--page-id` path is the disambiguating fallback — never filters, never errors on duplicates (there can only be one UUID).

### Download one page by name

Best when you can read the page title off the web UI but don't want to copy the UUID:

```bash
se download CAPP --page-name "Architecture"
# → systems/<workspace>/CAPP/architecture.md
```

If two pages share the name, the command stops with:

```
ERROR: 2 pages named 'Architecture' in project CAPP. Use --page-id <uuid> to disambiguate.
```

If a private page matches the name but the public-only default hid it, the error hints at the opt-out:

```
ERROR: no page named 'Architecture' in project CAPP (case-sensitive match) (1 private page with this name exists — pass --include-private to include it)
```

### Include private pages

```bash
se download CAPP --include-private
se download CAPP --page-name "Internal Plan" --include-private
```

`--include-private` only changes which pages enter the candidate pool. The output layout, slug rules, and frontmatter are unchanged.

### Switch workspace via profile

```bash
# One-shot, no env vars:
se download STELL --plane-profile stellar-sandbox

# Or set the env var for the session:
PLANE_PROFILE=stellar-sandbox se download STELL
```

### Preview without writing

```bash
se download CAPP --dry-run
se download CAPP --page-name "Architecture" --dry-run
```

Prints the `WRITE`/`OVERWRITE` plan with `[DRY RUN]` prefixed lines. No filesystem touch.

### Custom output root

```bash
se download CAPP --output-root /tmp/plane-snapshot
# → /tmp/plane-snapshot/<workspace>/CAPP/*.md
```

## What's **not** auto-resolved

The command does several lookups for you (project code → UUID, page name → UUID, workspace → cred file). It does **not** do:

- **Cross-project name search.** `--page-name "Foo"` looks only inside the named project. To find a page when you don't remember the project, list workspace projects first (`curl … /projects/`).
- **Fuzzy or case-insensitive name match.** Exact, case-sensitive. `architecture` won't match `Architecture`.
- **Recursive page hierarchies.** Plane's child-page nesting isn't traversed; each page is downloaded flat.
- **Auto-create destination directories outside `<output-root>`.** The script creates `<output-root>/<workspace>/<project-code>/` but assumes `<output-root>` is reachable (`mkdir -p` is used for the inner layers).

## Round-trip with `upload_project_pages.py`

`se download`'s frontmatter convention is matched by [`upload_project_pages.py`](../../upload_project_pages.py):

```bash
se download CAPP                            # pull
$EDITOR systems/<ws>/CAPP/architecture.md   # edit locally
python3 upload_project_pages.py …           # push the edit back
```

The uploader reads `plane_page_id` from the frontmatter and PATCHes the matching page on Plane.

## Related commands

- `se pages <project>` — list every page in a project as a table (id / name / access). Use this to discover what `--page-name` or `--page-id` values you can pass. Run `se pages -h` for the flag surface.
- `se generate --plane-project CAPP --plane-page <uuid>` — chains `se download` with the generator pipeline. The downloaded file feeds straight into `extract.json` / `render`.
- `se taskgen <project> <page>` — different intent: turns a single Plane spec page into Plane work items + Grava issues. Doesn't write to disk.

## See also

- [`scripts/install.sh --from-source`](../install.md) — install the latest version (with the most recent flags) without waiting for a tag.
- [`download_project_pages.py`](../../download_project_pages.py) — the underlying script that `se download` dispatches into.
