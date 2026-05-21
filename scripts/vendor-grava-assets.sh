#!/usr/bin/env bash
# Fetch grava's .claude/{agents,skills}/ into vendored/grava/ for PyInstaller
# to bundle into the `se` binary.
#
# Called from scripts/build.sh BEFORE PyInstaller runs. The vendored dir is
# git-ignored — it's a build artefact, regenerated on every release.
#
# Source: https://github.com/hoangtrungnguyen/grava (main branch tip).
# To pin a specific grava ref: GRAVA_REF=v0.1.2 bash scripts/vendor-grava-assets.sh
#
# Usage:
#   bash scripts/vendor-grava-assets.sh              # vendors latest main
#   GRAVA_REF=v0.1.2 bash scripts/vendor-grava-assets.sh  # pinned ref
#   GRAVA_SRC=/path/to/clone bash scripts/vendor-grava-assets.sh  # use existing clone

set -euo pipefail

OWNER="${GRAVA_OWNER:-hoangtrungnguyen}"
REPO="${GRAVA_REPO_NAME:-grava}"
REF="${GRAVA_REF:-main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendored/grava"

# Source override: if GRAVA_SRC points at a usable clone, skip the network fetch.
if [ -n "${GRAVA_SRC:-}" ] && [ -d "$GRAVA_SRC/.claude/agents" ]; then
    echo "▸ vendoring from existing clone: $GRAVA_SRC"
    SRC="$GRAVA_SRC"
    USE_TMP=0
else
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    SRC="$TMP/grava"
    USE_TMP=1
    echo "▸ cloning $OWNER/$REPO @ $REF (shallow) into $SRC"
    if ! git clone --depth 1 --branch "$REF" \
            "https://github.com/${OWNER}/${REPO}.git" "$SRC" 2>&1 | tail -2; then
        echo "✗ git clone failed; vendoring aborted" >&2
        exit 1
    fi
fi

# Clean previous vendoring — match-source-exactly semantics.
rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR/.claude"

# Copy ONLY the dirs stellar-engine consumes. Keeping the scope tight means
# unrelated changes in grava (docs, tests, source code) don't bloat the
# stellar-engine binary or trigger spurious rebuilds.
for sub in agents skills; do
    if [ ! -d "$SRC/.claude/$sub" ]; then
        echo "✗ $SRC/.claude/$sub missing in grava clone; aborting" >&2
        exit 1
    fi
    cp -R "$SRC/.claude/$sub" "$VENDOR_DIR/.claude/"
done

# Also vendor scripts/ship/ — /ship's dep-check.sh lives outside .claude/
# but is part of the ship workflow contract.
if [ -d "$SRC/scripts/ship" ]; then
    mkdir -p "$VENDOR_DIR/scripts"
    cp -R "$SRC/scripts/ship" "$VENDOR_DIR/scripts/"
fi

# Stamp the vendored commit so `se` can surface it via `se doctor`.
( cd "$SRC" && git rev-parse HEAD 2>/dev/null || echo unknown ) > "$VENDOR_DIR/VENDORED_COMMIT"

echo "✓ vendored $(find "$VENDOR_DIR" -type f | wc -l | tr -d ' ') file(s) into $VENDOR_DIR"
echo "  grava commit: $(cat "$VENDOR_DIR/VENDORED_COMMIT")"
