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

### `--from-source`: install from HEAD without a release

Two extra flags let the installer skip GitHub Releases entirely and build the binary from a git checkout on the host:

```bash
# Latest commit on main:
curl -fsSL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh \
  | bash -s -- --from-source

# Specific branch (unreleased PR, fork, etc.):
curl -fsSL .../install.sh | bash -s -- --from-source --branch claude/some-feature

# Combine with --bin-dir / --prefix as usual:
curl -fsSL .../install.sh | bash -s -- --from-source --bin-dir /opt/homebrew/bin
```

Flow:

1. `git clone --depth 1 --branch <name> https://github.com/<repo>.git` into a temp dir.
2. Runs `bash scripts/build.sh --version from-source-<branch>-<short-sha>` inside the clone (build.sh auto-installs PyInstaller into `.build-venv/`).
3. Copies the built `dist/se-<os>-<arch>/se` into the resolved bin dir.
4. Cleans up the temp clone via the script's `trap … EXIT`.

The version stamp embeds the resolved branch + short SHA so `se --version` shows exactly what landed:

```
$ se --version
se from-source-main-d2f60be (commit d2f60be, built 2026-05-20T14:03:45Z)
```

#### Trade-offs

| | Default (`install.sh`) | `--from-source` |
|---|---|---|
| Source | Latest tagged GitHub release | Latest commit on a branch (default `main`) |
| Network | GitHub Releases CDN | `git clone` over HTTPS |
| Host build chain | not needed | needs `python3` (3.10+), `pip`, `git` |
| Speed | ~1 second | ~1–2 minutes |
| `sha256` verify | yes (against published `.sha256`) | no (trust the git repo + host build chain) |
| Use case | production install from a tagged release | unreleased features, forks, firewalled hosts |

#### Constraints

- **Snapshot, not live.** The binary is frozen at clone time; subsequent commits on the branch don't reach you until you reinstall.
- **Shallow clone (`--depth 1`).** No history; `git describe` inside the binary's working dir won't see other tags. Doesn't affect the binary itself.
- **`--branch` only valid with `--from-source`.** Passing `--branch <name>` without `--from-source` exits with `✗ --branch only valid with --from-source` — silent ignore would mask a misconfigured install command.
- **Unsigned.** Release-mode installs verify a published `.sha256` from the release page. `--from-source` skips that — you trust the git repo + the host's build chain. Use `--version <tag>` (release mode) when you need cryptographic verification.

### `install-local.sh`: companion for in-checkout iteration

[`scripts/install-local.sh`](../scripts/install-local.sh) is the "I already ran `build.sh`, just install the artifact" helper. No network, no clone — copies `dist/se-<os>-<arch>/se` straight into the bin dir.

```bash
bash scripts/build.sh                    # produce dist/se-<os>-<arch>/se
bash scripts/install-local.sh            # copy to $HOME/.local/bin/se
bash scripts/install-local.sh --force    # overwrite existing se
bash scripts/install-local.sh --dry-run  # preview
bash scripts/install-local.sh --bin-dir /opt/homebrew/bin
bash scripts/install-local.sh --artifact /path/to/custom/se
```

Auto-detects OS+arch (darwin/linux × arm64/x64) to find the right `dist/` subdir. Exits:

- `0` — installed (or would install, with `--dry-run`)
- `1` — usage / arg error
- `2` — build artifact missing (run `scripts/build.sh` first)
- `3` — refused to overwrite an existing `se` (pass `--force`)

Use this in a tight iteration loop where you're hacking `cli/se` and want fast feedback. Use `install.sh --from-source` when you want a one-liner that works on someone else's machine.

### Choosing between the three paths

| You want… | Command |
|---|---|
| Production install from the latest tagged release | `curl … install.sh \| bash` |
| HEAD of `main` (latest unreleased code) | `curl … install.sh \| bash -s -- --from-source` |
| An unreleased PR branch | `curl … install.sh \| bash -s -- --from-source --branch <name>` |
| Already built locally, just put it on PATH | `bash scripts/install-local.sh` |
| Pin to a specific tag for reproducibility | `curl … install.sh \| bash -s -- --version v0.0.6+8` |

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
