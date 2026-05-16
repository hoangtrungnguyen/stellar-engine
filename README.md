# Stellar Engine

Operator toolkit on top of [grava](https://github.com/) + [Plane.so](https://plane.so/). Three sub-agents (generator, task-generator, orchestrator) plus a v0 grava→Plane state sync, all driven by the single `se` CLI.

## Install (macOS)

Linux support is not yet built — macOS only for now.

```bash
curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh | bash
```

Installs `se` into `$HOME/.local/bin` — no sudo required. If that directory is not on your `PATH`, the installer prints the exact line to add to your shell rc.

### System-wide install (with sudo)

```bash
curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh \
  | sudo bash -s -- --prefix /usr/local
```

### Pin to a specific release

```bash
curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh \
  | bash -s -- --version v0.1.0
```

### Pick your own bin dir

```bash
curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh \
  | bash -s -- --bin-dir /opt/homebrew/bin
```

### Manual download

Grab the tarball for your platform from [Releases](https://github.com/hoangtrungnguyen/stellar-engine/releases/latest):

| Platform | Asset |
|---|---|
| macOS Apple Silicon | `se-darwin-arm64.tar.gz` |
| macOS Intel | `se-darwin-x64.tar.gz` |

```bash
tar -xzf se-darwin-arm64.tar.gz
sudo install -m 0755 se /usr/local/bin/se
se --help
```

Each tarball ships with a `.sha256` companion file.

### Build from source

Requires Python 3.10+.

```bash
git clone https://github.com/hoangtrungnguyen/stellar-engine.git
cd stellar-engine
bash scripts/build.sh           # produces dist/se-<os>-<arch>/se
```

## Quick start

```bash
se --version                               # report which build you have
se --help
se doctor --dir .                          # validate environment
se generate path/to/spec.md --project DEMO # turn markdown into spec drafts
se download <plane-project-uuid>           # pull Plane pages → systems/
```

See [`CLAUDE.md`](CLAUDE.md) for the full architecture and [`docs/install.md`](docs/install.md) for build/release details.

## What's in the binary

The single `se` executable bundles:

- The `se` operator CLI (`init`, `repos`, `doctor`, `download`, `generate`).
- The generator agent (markdown → reviewable spec drafts).
- The Plane I/O scripts (`upload_project_pages.py`, `download_project_pages.py`).
- Python deps (`pyyaml`, `markdown`, `markdownify`, `requests`).

The task-generator and orchestrator agents still ship as separate scripts under `agents/` — they're invoked from inside a Claude Code session, not directly from the binary.

## License

See [LICENSE](LICENSE) (TBD).
