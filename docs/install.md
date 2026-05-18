# Install + release flow

The `se` CLI ships as a self-contained binary per OS/arch. End-users `curl | bash` an installer that grabs the right tarball from GitHub Releases.

## Supported platforms

| OS | Arch | Tarball | Runner used in CI |
|---|---|---|---|
| macOS | arm64 (Apple Silicon) | `se-darwin-arm64.tar.gz` | `macos-14` |
| macOS | x64 (Intel) | `se-darwin-x64.tar.gz` | `macos-14` |
| Linux | x64 (x86_64) | `se-linux-x64.tar.gz` | `ubuntu-latest` |
| Linux | arm64 (ARM64) | `se-linux-arm64.tar.gz` | `ubuntu-latest` |

Windows is not supported. The matrix can be extended — see [`.github/workflows/release.yml`](../.github/workflows/release.yml).

## What's bundled

PyInstaller `--onefile` pulls the entry script ([`cli/se`](../cli/se)) plus every dispatched module into a single executable:

- Python interpreter + std-lib.
- Third-party deps: `pyyaml`, `markdown`, `markdownify`, `requests`.
- The whole [`agents/`](../agents) tree, the Plane sync scripts (`upload_project_pages.py`, `download_project_pages.py`, `upload_wiki_page.py`).

At runtime the entrypoint resolves data files via `sys._MEIPASS`, so subcommands like `se generate` import the generator agent directly — no subprocess shell-out.

## Local build

```bash
bash scripts/build.sh
# produces:
#   dist/se-<os>-<arch>/se                  ← runnable binary
#   dist/se-<os>-<arch>.tar.gz              ← distributable tarball
#   dist/se-<os>-<arch>.tar.gz.sha256       ← checksum
```

The script creates `.build-venv/`, installs PyInstaller + runtime deps into it, runs `pyinstaller --onefile`, and packages the result.

### Version stamping

Every build embeds a version, short commit, and UTC build date into the binary. Inspect with `se --version`:

```
$ se --version
se v0.1.0 (commit 82952fe, built 2026-05-16T13:48:26Z)
```

Resolution order for the version string:

1. `--version v0.1.0` flag passed to `build.sh`.
2. `SE_VERSION=v0.1.0` env (what the GH Actions workflow injects on tag push).
3. `git describe --tags --always --dirty` (e.g. `v0.1.0`, `v0.1.0-3-gabc1234`, `e34d9a0-dirty`).
4. Fallback: `0.0.0-dev`.

Dev installs (running `python3 cli/se` directly) always see `0.0.0-dev` — the committed [`cli/_version.py`](../cli/_version.py). `build.sh` overwrites that file for the PyInstaller run and restores it on exit (via `trap`), so dev state isn't disturbed.

Cleanup:

```bash
rm -rf .build-venv build dist
```

## CI release flow

[`.github/workflows/release.yml`](../.github/workflows/release.yml) drives every release.

Trigger:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow:

1. Spins up four runners (macOS arm64 + x64, Linux x64 + arm64).
2. Each runs `bash scripts/build.sh`.
3. Tarballs + sha256 files upload as artifacts.
4. A final `release` job downloads all artifacts and creates a GitHub Release tagged with the pushed tag, attaching all four `.tar.gz` + `.sha256` pairs.

You can also dispatch manually from the GitHub UI ("Run workflow") — that path produces artifacts but does NOT publish a release (the `release` job only runs on tag pushes).

## Installer

[`scripts/install.sh`](../scripts/install.sh) is the user-facing entry point:

```bash
curl -fsSL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh | bash
```

It:

1. Detects `darwin|linux` × `arm64|x64`.
2. Fetches `se-<os>-<arch>.tar.gz` from `releases/latest/download/` (or `--version <tag>`).
3. Verifies the published `.sha256`.
4. Extracts `se` and installs it to `<prefix>/bin` (default `/usr/local`, override with `--prefix`).
5. Warns if `<prefix>/bin` is not on the user's PATH.

The installer respects `SE_REPO=<owner/repo>` so a fork can host its own builds.

## Refactoring notes for binary friendliness

The original `cli/se` shelled out via `subprocess.call([sys.executable, str(script), …])`. That pattern is fine in dev but breaks under PyInstaller — `sys.executable` becomes the bundled binary, which only knows how to run its own entry script.

To make `se` ship as one executable, [`cli/se`](../cli/se) now uses `importlib.util.spec_from_file_location` to load `download_project_pages.py` and `agents/generator/cli/run.py` as modules and call their `main(argv)` functions directly. The data files still exist on disk (under `sys._MEIPASS` at runtime); only the dispatch is in-process.

Each dispatched script must expose `main(argv: list[str] | None = None) -> int`. If you add a new `se <subcommand>`, follow the same pattern in `cli/se`'s `cmd_*` handler:

```python
def cmd_foo(args: argparse.Namespace) -> None:
    script = _repo_root() / "path/to/foo.py"
    mod = _load_module("foo", script)
    sys.exit(mod.main(["--flag", args.value]))
```

## Verifying the bundle

```bash
bash scripts/build.sh
./dist/se-darwin-arm64/se --help
./dist/se-darwin-arm64/se doctor --dir .
./dist/se-darwin-arm64/se generate path/to/sample.md --project DEMO --no-llm
```

A green `doctor` (with the expected `anthropic`/`pymupdf` warnings) and a populated `drafts/DEMO/runs/<RID>/extract.json` confirm the bundle is wired correctly.
