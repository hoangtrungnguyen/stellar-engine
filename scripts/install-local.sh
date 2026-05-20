#!/usr/bin/env bash
# Stellar Engine LOCAL installer.
#
# Companion to `scripts/build.sh` for installing the binary you just built
# without touching GitHub releases. No download, no checksum verification
# against a remote — just copies <repo>/dist/se-<os>-<arch>/se onto your
# PATH.
#
# Use this when:
#   • You built from a feature branch and want to test the binary on PATH
#     before opening a PR.
#   • You're iterating on cli/se locally and need fast feedback.
#   • You're behind a corporate firewall and can't reach api.github.com.
#
# For the published install flow (curl | bash from a tagged release) use
# scripts/install.sh instead.
#
# Usage:
#   bash scripts/build.sh                              # produce the binary first
#   bash scripts/install-local.sh                      # install to $HOME/.local/bin
#   bash scripts/install-local.sh --bin-dir /opt/homebrew/bin
#   bash scripts/install-local.sh --dry-run            # preview without copying
#   bash scripts/install-local.sh --force              # overwrite existing se
#
# Exit codes:
#   0 — installed (or would install, with --dry-run)
#   1 — usage / arg error
#   2 — build artifact missing (run scripts/build.sh first)
#   3 — refused to overwrite (existing se present; pass --force)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BIN_DIR=""
DRY_RUN=0
FORCE=0
ARTIFACT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --bin-dir)
            BIN_DIR="$2"; shift 2 ;;
        --artifact)
            # Explicit path to the freshly-built binary. Useful if you
            # built with --arch into a non-default dist/se-<os>-<arch>/
            # layout.
            ARTIFACT="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        --force)
            FORCE=1; shift ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *)
            echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ── detect host platform (so we can guess the artifact path) ────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Darwin)  OS_TAG="darwin" ;;
    Linux)   OS_TAG="linux" ;;
    *)       echo "unsupported OS: $OS" >&2; exit 1 ;;
esac
case "$ARCH" in
    arm64|aarch64)  ARCH_TAG="arm64" ;;
    x86_64|amd64)   ARCH_TAG="x64" ;;
    *)              echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

if [ -z "$ARTIFACT" ]; then
    ARTIFACT="$REPO_ROOT/dist/se-${OS_TAG}-${ARCH_TAG}/se"
fi

if [ ! -x "$ARTIFACT" ]; then
    echo "ERROR: build artifact not found at: $ARTIFACT" >&2
    echo "       Run 'bash scripts/build.sh' first, or pass --artifact <path>." >&2
    exit 2
fi

# ── default install destination ─────────────────────────────────────────────
if [ -z "$BIN_DIR" ]; then
    BIN_DIR="$HOME/.local/bin"
fi

DEST="$BIN_DIR/se"

# ── safety: don't silently overwrite ────────────────────────────────────────
if [ -e "$DEST" ] && [ "$FORCE" -eq 0 ]; then
    EXISTING_VERSION="$("$DEST" --version 2>/dev/null || echo '<unrunnable>')"
    echo "ERROR: $DEST already exists ($EXISTING_VERSION)." >&2
    echo "       Pass --force to overwrite, or --bin-dir <other-path> to install" >&2
    echo "       alongside the existing binary." >&2
    exit 3
fi

# ── report what we're about to do ───────────────────────────────────────────
NEW_VERSION="$("$ARTIFACT" --version 2>/dev/null || echo '<unknown>')"
SIZE="$(ls -l "$ARTIFACT" | awk '{print $5}')"

echo "  artifact : $ARTIFACT"
echo "  version  : $NEW_VERSION"
echo "  size     : $SIZE bytes"
echo "  dest     : $DEST"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] no files written."
    exit 0
fi

# ── install ─────────────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
install -m 0755 "$ARTIFACT" "$DEST"

# Mirror the published installer's PATH guidance so the user gets a hint
# when ~/.local/bin isn't on PATH yet.
case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "  installed."
        echo "  test: se --version" ;;
    *)
        echo "  installed, but $BIN_DIR is not on \$PATH."
        echo ""
        echo "  Add this to your shell rc (~/.zshrc, ~/.bashrc):"
        echo "      export PATH=\"$BIN_DIR:\$PATH\""
        echo ""
        echo "  Then reopen the terminal (or 'source ~/.zshrc')." ;;
esac
