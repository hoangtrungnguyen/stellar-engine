#!/usr/bin/env bash
# Stellar Engine installer (macOS + Linux).
#
# Single-command install (latest tagged release):
#   curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh | bash
#
# Latest HEAD of main (built from source, no GH release required):
#   curl -sL https://raw.githubusercontent.com/hoangtrungnguyen/stellar-engine/main/scripts/install.sh | bash -s -- --from-source
#
# Specific branch (also from source):
#   curl -sL .../install.sh | bash -s -- --from-source --branch claude/se-pages-cmd
#
# Default: installs to $HOME/.local/bin (no sudo). Override with flags:
#   curl -sL .../install.sh | bash -s -- --prefix /usr/local        (will use sudo)
#   curl -sL .../install.sh | bash -s -- --version v0.1.0
#   curl -sL .../install.sh | bash -s -- --bin-dir /opt/homebrew/bin
#
# Behaviour (release mode — the default):
#   • Detects darwin × arm64|x64 / linux × arm64|x64.
#   • Fetches se-<os>-<arch>.tar.gz from the matching GitHub release.
#   • Verifies the published sha256.
#   • Installs `se` into <bin-dir> (default $HOME/.local/bin).
#   • Prints PATH instructions if the bin dir isn't on PATH.
#
# Behaviour (--from-source mode):
#   • git clone --depth 1 [--branch <name>] the repo into a temp dir.
#   • Runs `bash scripts/build.sh` (auto-installs PyInstaller into a venv).
#   • Installs the built binary into <bin-dir>.
#   • Requires python3 (3.10+), pip, git on the host. Slower (~1–2 min).
#   • Useful for unreleased changes / forks / corporate firewalls that
#     can't reach api.github.com but can reach the raw repo.

set -euo pipefail

REPO="${SE_REPO:-hoangtrungnguyen/stellar-engine}"
VERSION="${SE_VERSION:-latest}"
PREFIX=""
BIN_DIR=""
FROM_SOURCE=0
BRANCH="${SE_BRANCH:-main}"

while [ $# -gt 0 ]; do
    case "$1" in
        --version)      VERSION="$2"; shift 2 ;;
        --prefix)       PREFIX="$2";  shift 2 ;;
        --bin-dir)      BIN_DIR="$2"; shift 2 ;;
        --repo)         REPO="$2";    shift 2 ;;
        --from-source)  FROM_SOURCE=1; shift ;;
        --branch)       BRANCH="$2";  shift 2 ;;
        -h|--help)      sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# `--branch` only makes sense in --from-source mode. Reject the combo
# early rather than silently ignoring it.
if [ "$FROM_SOURCE" -eq 0 ] && [ "$BRANCH" != "main" ]; then
    echo "✗ --branch only valid with --from-source" >&2
    exit 1
fi

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

# ── --from-source: build from a git checkout, skip release machinery ─────────
#
# We branch here so the release-mode code below stays unchanged for the
# common path. The from-source branch clones, builds, and ends with the
# binary at `$TMP/se` — the same shape the release path produces after
# extracting the tarball — so the install + PATH-hint code at the bottom
# of the script reuses verbatim.

if [ "$FROM_SOURCE" -eq 1 ]; then
    # Sanity-check the host has what build.sh needs.
    for tool in git python3; do
        if ! command -v "$tool" >/dev/null; then
            echo "✗ --from-source requires '$tool' on PATH" >&2
            exit 1
        fi
    done

    echo "▸ stellar-engine installer (--from-source)"
    echo "  repo:     $REPO"
    echo "  branch:   $BRANCH"
    echo "  platform: $OS_TAG-$ARCH_TAG"
    echo "  bin-dir:  $BIN_DIR"
    echo ""

    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT

    CLONE_DIR="$TMP/repo"
    echo "▸ cloning $REPO @ $BRANCH (shallow)"
    if ! git clone --depth 1 --branch "$BRANCH" \
            "https://github.com/${REPO}.git" "$CLONE_DIR" 2>&1 \
            | tail -3; then
        echo "✗ git clone failed" >&2
        exit 1
    fi

    echo "▸ building (will take ~1–2 min)"
    cd "$CLONE_DIR"
    # Stamp the binary with the resolved commit so `se --version`
    # surfaces what actually got built. build.sh also accepts a
    # version flag — passing it here makes `se --version` show e.g.
    # `v0.0.6+8-from-source-9c25b7e`.
    HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    SRC_VERSION="${SE_VERSION:-from-source-${BRANCH}-${HEAD_SHA}}"
    if ! bash scripts/build.sh --version "$SRC_VERSION" 2>&1 | tail -5; then
        echo "✗ build.sh failed" >&2
        exit 1
    fi

    BUILT="$CLONE_DIR/dist/se-${OS_TAG}-${ARCH_TAG}/se"
    if [ ! -x "$BUILT" ]; then
        echo "✗ expected binary missing at $BUILT" >&2
        exit 1
    fi
    cp "$BUILT" "$TMP/se"
    chmod 0755 "$TMP/se"
    echo "✓ build complete: $($TMP/se --version 2>/dev/null || echo '<unknown>')"

    # Fall through to the shared install step (mkdir / sudo / install).
    # The release branch below depends on $TMP/$TARBALL existing for
    # checksum verification; from-source skips that — point the rest
    # of the script at the already-extracted binary.
    BASE_URL=""
    LABEL="$SRC_VERSION"
    SKIP_DOWNLOAD=1
else
    SKIP_DOWNLOAD=0
fi

# ── resolve release ───────────────────────────────────────────────────────────
# SE_BASE_URL env override is useful for forks + local testing (e.g. point
# at a `python3 -m http.server` serving a dist/ dir). Skipped entirely in
# --from-source mode — the binary already exists at $TMP/se.

if [ "$SKIP_DOWNLOAD" -eq 0 ]; then
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

    # ── download ─────────────────────────────────────────────────────────
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT

    echo "▸ downloading $TARBALL"
    if ! curl -fsSL "$URL" -o "$TMP/$TARBALL"; then
        echo "" >&2
        echo "✗ download failed: $URL" >&2
        echo "  No release named '$LABEL' for $REPO yet?" >&2
        echo "  Browse releases: https://github.com/$REPO/releases" >&2
        echo "  Or fall back to --from-source to build HEAD directly:" >&2
        echo "    curl -sL .../install.sh | bash -s -- --from-source" >&2
        exit 1
    fi

    curl -fsSL "$SHA_URL" -o "$TMP/$TARBALL.sha256" 2>/dev/null || true

    # ── verify checksum ──────────────────────────────────────────────────
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

    # ── extract ──────────────────────────────────────────────────────────
    tar -xzf "$TMP/$TARBALL" -C "$TMP"

    if [ ! -f "$TMP/se" ]; then
        echo "✗ tarball did not contain 'se'" >&2
        exit 1
    fi
fi

# At this point $TMP/se exists and is executable, whether we got it
# from a release tarball or built it from source. The rest of the
# script doesn't care which path produced it.

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
