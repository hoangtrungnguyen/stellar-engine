#!/usr/bin/env bash
set -euo pipefail

PLANE_CONFIG="$HOME/.config/plane/config.json"
PLANE_HOST="https://api.plane.so"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠ $*${RESET}"; }
error()   { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }

# ── bun ───────────────────────────────────────────────────────────────────────
install_bun() {
    header "Installing bun"
    curl -fsSL https://bun.sh/install | bash
    export BUN_INSTALL="$HOME/.bun"
    export PATH="$BUN_INSTALL/bin:$PATH"
    success "bun installed"
}

header "━━━  Plane CLI Setup  ━━━"

if ! command -v bun &>/dev/null; then
    warn "bun not found"
    install_bun
else
    success "bun $(bun --version) found"
fi

# ── plane-cli ─────────────────────────────────────────────────────────────────
header "Installing plane-cli"

if bun pm ls -g 2>/dev/null | grep -q "@aaronshaf/plane"; then
    info "Upgrading @aaronshaf/plane"
    bun update -g @aaronshaf/plane
else
    info "Installing @aaronshaf/plane"
    bun install -g @aaronshaf/plane
fi

# ensure bun bin is on PATH for this session
export PATH="$HOME/.bun/bin:$PATH"

if ! command -v plane &>/dev/null; then
    error "plane binary not found after install — add $HOME/.bun/bin to your PATH"
fi
success "plane $(plane --version 2>/dev/null || echo 'installed')"

# ── python deps ───────────────────────────────────────────────────────────────
header "Installing Python dependencies"

PIP=$(command -v pip3 || command -v pip || true)
# Notes:
#  - `markdown` (>=3.6) is used by task-generator and the generator agent.
#  - `markdownify` parses Plane HTML pages.
#  - `anthropic` is intentionally NOT installed: generator Phase D (LLM
#    outline) is deferred; today the outline step runs manually via a
#    Claude Code session. Add `anthropic>=0.40` here when Phase D lands.
#  - `pymupdf` (PDF frontend) is also deferred — markdown is the only
#    supported source for now.
if [ -z "$PIP" ]; then
    warn "pip not found — skipping Python deps (install manually: pip install markdown markdownify requests pyyaml)"
else
    $PIP install -q markdown markdownify requests pyyaml --break-system-packages 2>/dev/null \
        || $PIP install -q markdown markdownify requests pyyaml 2>/dev/null \
        || warn "Could not install Python deps automatically — run: pip install markdown markdownify requests pyyaml"
    success "markdown, markdownify, requests, pyyaml installed"
fi

# ── credentials ───────────────────────────────────────────────────────────────
header "Configuring credentials"

# load existing values as defaults
EXISTING_WORKSPACE=""
EXISTING_TOKEN=""
if [ -f "$PLANE_CONFIG" ]; then
    EXISTING_WORKSPACE=$(python3 -c "import json,sys; d=json.load(open('$PLANE_CONFIG')); print(d.get('workspace',''))" 2>/dev/null || true)
    EXISTING_TOKEN=$(python3 -c "import json,sys; d=json.load(open('$PLANE_CONFIG')); print(d.get('token',''))" 2>/dev/null || true)
    info "Existing config found — press Enter to keep current values"
fi

prompt_value() {
    local label="$1" current="$2" result
    if [ -n "$current" ]; then
        read -rp "  $label [${current:0:6}...]: " result
        echo "${result:-$current}"
    else
        read -rp "  $label: " result
        echo "$result"
    fi
}

echo ""
WORKSPACE=$(prompt_value "Workspace slug (e.g. my-team)" "$EXISTING_WORKSPACE")
TOKEN=$(prompt_value "API token (Profile → Personal Access Tokens)" "$EXISTING_TOKEN")

[ -z "$WORKSPACE" ] && error "Workspace slug is required"
[ -z "$TOKEN" ]     && error "API token is required"

mkdir -p "$(dirname "$PLANE_CONFIG")"
cat > "$PLANE_CONFIG" <<JSON
{
  "host": "$PLANE_HOST",
  "workspace": "$WORKSPACE",
  "token": "$TOKEN"
}
JSON
chmod 600 "$PLANE_CONFIG"
success "Config saved to $PLANE_CONFIG"

# ── verify ────────────────────────────────────────────────────────────────────
header "Verifying connection"

OUTPUT=$(plane projects list 2>&1)
if [ $? -eq 0 ] && [ -n "$OUTPUT" ]; then
    success "Connected! Projects in workspace '$WORKSPACE':"
    echo ""
    echo "$OUTPUT"
else
    warn "Could not list projects — check your workspace slug and API token"
    echo "$OUTPUT"
fi

# ── STELLAR_ENGINE_HOME ───────────────────────────────────────────────────────
header "STELLAR_ENGINE_HOME"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${STELLAR_ENGINE_HOME:-}" ] && [ -d "$STELLAR_ENGINE_HOME" ]; then
    success "STELLAR_ENGINE_HOME=$STELLAR_ENGINE_HOME"
else
    warn "STELLAR_ENGINE_HOME unset — grava agent hooks will fall back to a hard-coded path."
    echo ""
    echo "  Add to your shell profile:"
    echo ""
    echo "    export STELLAR_ENGINE_HOME=\"$SCRIPT_DIR\""
    echo ""
    echo "  Then: source ~/.zshrc (or ~/.bashrc)"
fi

# ── sandbox .env ──────────────────────────────────────────────────────────────
header "Sandbox .env"

SCRIPT_DIR_PRE_CRON="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_EXAMPLE="$SCRIPT_DIR_PRE_CRON/.env.example"
ENV_FILE="$SCRIPT_DIR_PRE_CRON/.env"

if [ -f "$ENV_FILE" ]; then
    success ".env present at $ENV_FILE"
else
    warn ".env not found — generator + integration tests need this for sandbox runs."
    echo ""
    echo "  Create it from the template:"
    echo ""
    echo "    cp $ENV_EXAMPLE $ENV_FILE"
    echo "    \$EDITOR $ENV_FILE        # paste real PLANE_API_TOKEN, etc."
    echo "    set -a; source $ENV_FILE; set +a   # load into current shell"
    echo ""
    echo "  Generator note: ANTHROPIC_API_KEY can stay as the placeholder —"
    echo "  the outline step runs manually via Claude Code today (Phase D"
    echo "  is deferred). See docs/generator/plan.md §Phase D."
fi

# ── pr_merge_watcher cron ─────────────────────────────────────────────────────
header "PR merge watcher cron"

WATCHER_PATH="$SCRIPT_DIR/agents/orchestrator/scripts/pr_merge_watcher.sh"
echo ""
echo "  Install the watcher in each target repo so PR transitions feed back into grava."
echo "  Cron snippet (replace <target-repo>):"
echo ""
echo "    */5 * * * * cd /path/to/<target-repo> && bash $WATCHER_PATH"
echo ""
echo "  Add via: crontab -e"

# ── done ──────────────────────────────────────────────────────────────────────
header "━━━  Setup complete  ━━━"
echo ""
echo -e "  ${BOLD}Quick reference:${RESET}"
echo "  plane projects list"
echo "  plane issues list <PROJECT>"
echo "  plane issue create <PROJECT> \"Issue title\""
echo "  python3 upload_project_pages.py <project-uuid> <file.md>"
echo "  python3 agents/orchestrator/cli/doctor.py --target-repo <path>"
echo "  python3 cli/se generate <source.md> --project <name>           # generator"
echo "  python3 cli/se download <project-uuid>                         # Plane → systems/"
echo ""
echo -e "  Run the doctor against any target repo to verify your environment."
echo ""
