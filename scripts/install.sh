#!/usr/bin/env bash
# Stellar Engine installer (macOS + Linux).
#
# Single-command install:
#   curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh | bash
#
# Default: installs to $HOME/.local/bin (no sudo). Override with flags:
#   curl -sL .../install.sh | bash -s -- --prefix /usr/local        (will use sudo)
#   curl -sL .../install.sh | bash -s -- --version v0.1.0
#   curl -sL .../install.sh | bash -s -- --bin-dir /opt/homebrew/bin
#
# Behaviour:
#   • Detects darwin × arm64|x64.
#   • Fetches se-<os>-<arch>.tar.gz from the matching GitHub release.
#   • Verifies the published sha256.
#   • Installs `se` into <bin-dir> (default $HOME/.local/bin).
#   • Prints PATH instructions if the bin dir isn't on PATH.

set -euo pipefail

REPO="${SE_REPO:-hoangtrungnguyen/stellar-engine}"
VERSION="${SE_VERSION:-latest}"
PREFIX=""
BIN_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --version)  VERSION="$2"; shift 2 ;;
        --prefix)   PREFIX="$2";  shift 2 ;;
        --bin-dir)  BIN_DIR="$2"; shift 2 ;;
        --repo)     REPO="$2";    shift 2 ;;
        -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ── pick install location ─────────────────────────────────────────────────────
# Resolution order: --bin-dir > --prefix/bin > $HOME/.local/bin
if [ -z "$BIN_DIR" ]; then
    if [ -n "$PREFIX" ]; then
        BIN_DIR="$PREFIX/bin"
    else
        BIN_DIR="$HOME/.local/bin"
    fi
fi

# ── platform ──────────────────────────────────────────────────────────────────
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$OS" in
    darwin) OS_TAG="darwin" ;;
    linux)  OS_TAG="linux" ;;
    *) echo "✗ unsupported OS: $OS" >&2; exit 1 ;;
esac

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)   ARCH_TAG="x64" ;;
    arm64|aarch64)  ARCH_TAG="arm64" ;;
    *) echo "✗ unsupported arch: $ARCH" >&2; exit 1 ;;
esac

NAME="se-${OS_TAG}-${ARCH_TAG}"

# ── resolve release ───────────────────────────────────────────────────────────
# SE_BASE_URL env override is useful for forks + local testing (e.g. point
# at a `python3 -m http.server` serving a dist/ dir).
if [ -n "${SE_BASE_URL:-}" ]; then
    BASE_URL="$SE_BASE_URL"
    LABEL="$VERSION ($SE_BASE_URL)"
elif [ "$VERSION" = "latest" ]; then
    BASE_URL="https://github.com/$REPO/releases/latest/download"
    LABEL="latest"
else
    BASE_URL="https://github.com/$REPO/releases/download/$VERSION"
    LABEL="$VERSION"
fi

TARBALL="$NAME.tar.gz"
URL="$BASE_URL/$TARBALL"
SHA_URL="$URL.sha256"

echo "▸ stellar-engine installer"
echo "  repo:     $REPO"
echo "  release:  $LABEL"
echo "  platform: $OS_TAG-$ARCH_TAG"
echo "  bin-dir:  $BIN_DIR"
echo ""

# ── download ──────────────────────────────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "▸ downloading $TARBALL"
if ! curl -fsSL "$URL" -o "$TMP/$TARBALL"; then
    echo "" >&2
    echo "✗ download failed: $URL" >&2
    echo "  No release named '$LABEL' for $REPO yet?" >&2
    echo "  Browse releases: https://github.com/$REPO/releases" >&2
    exit 1
fi

curl -fsSL "$SHA_URL" -o "$TMP/$TARBALL.sha256" 2>/dev/null || true

# ── verify checksum ───────────────────────────────────────────────────────────
if [ -s "$TMP/$TARBALL.sha256" ]; then
    EXPECTED="$(awk '{print $1}' "$TMP/$TARBALL.sha256")"
    if command -v shasum >/dev/null; then
        ACTUAL="$(shasum -a 256 "$TMP/$TARBALL" | awk '{print $1}')"
    else
        ACTUAL="$(sha256sum "$TMP/$TARBALL" | awk '{print $1}')"
    fi
    if [ "$EXPECTED" != "$ACTUAL" ]; then
        echo "✗ checksum mismatch" >&2
        echo "  expected: $EXPECTED" >&2
        echo "  got:      $ACTUAL"   >&2
        exit 1
    fi
    echo "✓ sha256 verified"
else
    echo "⚠ no .sha256 published — skipping verify"
fi

# ── extract + install ─────────────────────────────────────────────────────────
tar -xzf "$TMP/$TARBALL" -C "$TMP"

if [ ! -f "$TMP/se" ]; then
    echo "✗ tarball did not contain 'se'" >&2
    exit 1
fi

# Need sudo? Only if the target dir is system-owned and we're not root.
needs_sudo=false
if ! mkdir -p "$BIN_DIR" 2>/dev/null; then
    needs_sudo=true
elif [ ! -w "$BIN_DIR" ]; then
    needs_sudo=true
fi

if $needs_sudo; then
    if [ "$(id -u)" = "0" ]; then
        needs_sudo=false
    elif ! command -v sudo >/dev/null; then
        echo "✗ $BIN_DIR is not writable and sudo is unavailable" >&2
        echo "  retry with --prefix \$HOME/.local (no sudo)" >&2
        exit 1
    fi
fi

if $needs_sudo; then
    if [ ! -t 0 ]; then
        echo "⚠ $BIN_DIR requires sudo, but stdin is piped (curl | bash)." >&2
        echo "  Re-run with sudo, or pick a user-owned target:" >&2
        echo "" >&2
        echo "    # user install (no sudo, default):" >&2
        echo "    curl -sL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | bash" >&2
        echo "" >&2
        echo "    # system install (with sudo):" >&2
        echo "    curl -sL https://raw.githubusercontent.com/$REPO/main/scripts/install.sh | sudo bash -s -- --prefix /usr/local" >&2
        exit 1
    fi
    sudo mkdir -p "$BIN_DIR"
    sudo install -m 0755 "$TMP/se" "$BIN_DIR/se"
else
    mkdir -p "$BIN_DIR"
    install -m 0755 "$TMP/se" "$BIN_DIR/se"
fi

echo "✓ installed: $BIN_DIR/se"
echo ""

# ── PATH hint ─────────────────────────────────────────────────────────────────
on_path=false
case ":$PATH:" in
    *":$BIN_DIR:"*) on_path=true ;;
esac

if ! $on_path; then
    # detect login shell rc file
    rc=""
    case "${SHELL:-}" in
        */zsh)  rc="$HOME/.zshrc" ;;
        */bash) rc="$HOME/.bashrc" ;;
        */fish) rc="$HOME/.config/fish/config.fish" ;;
    esac

    echo "⚠ $BIN_DIR is not on your PATH. Add it:"
    echo ""
    if [ "${SHELL:-}" = "${SHELL%/fish}" ] || [ -z "${SHELL:-}" ]; then
        echo "    echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ${rc:-~/.bashrc}"
        echo "    source ${rc:-~/.bashrc}"
    else
        echo "    fish_add_path $BIN_DIR"
    fi
    echo ""
    echo "Until then, run with the full path:"
    echo "    $BIN_DIR/se --help"
else
    "$BIN_DIR/se" --help | head -3
    echo ""
    echo "Run \`se doctor --dir .\` to validate your environment."
fi
