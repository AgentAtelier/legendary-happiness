#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# DevForge Integration Test Launcher
#
# Starts the full chain and runs tests:
#   llama.cpp → DevForge MCP Server → godot-ai → Godot
#
# Usage:
#   ./scripts/run_integration_test.sh              # smoke test
#   ./scripts/run_integration_test.sh forgeborn    # game build
#   ./scripts/run_integration_test.sh forgeborn --dry-run
#   ./scripts/run_integration_test.sh forgeborn --start-at 3
# ────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
DEVFORGE_DIR="$PROJECT_ROOT/devforge"
MCP_PORT="${DEVFORGE_MCP_PORT:-8001}"
GODOT_AI_MCP_URL="${DEVFORGE_GODOT_AI_MCP_URL:-http://localhost:8000/mcp}"
LLAMA_ENDPOINT="${DEVFORGE_LLAMA_ENDPOINT:-http://localhost:8080}"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[devforge]${NC} $*"; }
ok()   { echo -e "${GREEN}[  ok  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ warn ]${NC} $*"; }
err()  { echo -e "${RED}[ FAIL ]${NC} $*"; }

# ── Preflight ──────────────────────────────────────────────────

preflight() {
    log "Running preflight checks..."

    # Check llama.cpp
    if curl -s "$LLAMA_ENDPOINT/health" > /dev/null 2>&1; then
        ok "llama.cpp is up ($LLAMA_ENDPOINT)"
    else
        warn "llama.cpp not responding at $LLAMA_ENDPOINT"
        warn "Pipeline will fail without LLM backend."
    fi

    # Check godot-ai MCP
    if curl -s "$GODOT_AI_MCP_URL" > /dev/null 2>&1; then
        ok "godot-ai MCP is up ($GODOT_AI_MCP_URL)"
    else
        err "godot-ai MCP not responding at $GODOT_AI_MCP_URL"
        echo "   Start godot-ai first: cd godot-ai && python -m godot_ai --mcp"
        exit 1
    fi

    # Check Python venv
    if [ -f "$VENV_PYTHON" ]; then
        ok "Python venv found"
    else
        err "Python venv not found at $VENV_PYTHON"
        echo "   Create it: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
        exit 1
    fi

    # Check Python deps
    if $VENV_PYTHON -c "import mcp" 2>/dev/null; then
        ok "MCP Python package installed"
    else
        err "MCP Python package not installed"
        echo "   Install: $VENV_PYTHON -m pip install mcp"
        exit 1
    fi

    echo ""
}

# ── Start MCP Server ──────────────────────────────────────────

start_mcp_server() {
    log "Starting DevForge MCP server on port $MCP_PORT..."

    export DEVFORGE_EXECUTOR_BACKEND=godot_ai_mcp
    export DEVFORGE_GODOT_AI_MCP_URL="$GODOT_AI_MCP_URL"
    export DEVFORGE_LLAMA_ENDPOINT="$LLAMA_ENDPOINT"

    # Kill any existing MCP server on this port
    lsof -ti:$MCP_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true

    # Start MCP server in background
    # FastMCP uses uvicorn internally; pass host/port via env
    cd "$PROJECT_ROOT"
    MCP_HOST=0.0.0.0 MCP_PORT=$MCP_PORT \
        $VENV_PYTHON -c "
import os, sys
sys.path.insert(0, '.')
# FastMCP reads MCP_HOST/MCP_PORT from environment
os.environ.setdefault('MCP_HOST', '0.0.0.0')
os.environ.setdefault('MCP_PORT', str($MCP_PORT))
from devforge.platform.mcp_server import mcp
mcp.run(transport='sse')
" &
    MCP_PID=$!

    # Wait for it to be ready
    sleep 2
    for i in $(seq 1 10); do
        # SSE endpoint returns a long-lived stream — use --max-time to not hang
        if curl -s --max-time 2 -H "Accept: text/event-stream" \
                "http://localhost:$MCP_PORT/sse" \
                2>&1 | grep -q 'event'; then
            ok "DevForge MCP server ready (PID $MCP_PID)"
            return 0
        fi
        # Also check if process is still alive
        if ! kill -0 "$MCP_PID" 2>/dev/null; then
            err "DevForge MCP server died during startup"
            return 1
        fi
        sleep 1
    done

    err "DevForge MCP server failed to start"
    return 1
}

# ── Run Tests ──────────────────────────────────────────────────

run_smoke_test() {
    log "Running smoke test..."
    echo ""

    cd "$PROJECT_ROOT"
    $VENV_PYTHON tests/integration/test_smoke.py \
        --mcp-url "http://localhost:$MCP_PORT/sse"

    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        ok "Smoke test passed!"
    else
        err "Smoke test failed (exit code $exit_code)"
    fi
    return $exit_code
}

run_forgeborn_build() {
    local extra_args="${*:-}"
    log "Running Forgeborn game build..."
    echo ""

    cd "$PROJECT_ROOT"
    $VENV_PYTHON tests/integration/test_forgeborn.py \
        --mcp-url "http://localhost:$MCP_PORT/sse" \
        $extra_args

    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        ok "Forgeborn build complete!"
    else
        err "Forgeborn build had failures (exit code $exit_code)"
    fi
    return $exit_code
}

# ── Cleanup ────────────────────────────────────────────────────

cleanup() {
    if [ -n "${MCP_PID:-}" ]; then
        log "Stopping DevForge MCP server (PID $MCP_PID)..."
        kill "$MCP_PID" 2>/dev/null || true
        wait "$MCP_PID" 2>/dev/null || true
        ok "MCP server stopped"
    fi
}

trap cleanup EXIT

# ── Main ───────────────────────────────────────────────────────

main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║        DevForge Integration Test Launcher               ║"
    echo "║        Chain: MCP → Pipeline → godot-ai → Godot        ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""

    preflight
    start_mcp_server || exit 1

    local mode="${1:-smoke}"
    shift || true

    case "$mode" in
        smoke)
            run_smoke_test
            ;;
        forgeborn)
            run_forgeborn_build "$@"
            ;;
        both)
            run_smoke_test || true
            echo ""
            run_forgeborn_build "$@"
            ;;
        *)
            echo "Usage: $0 {smoke|forgeborn|both} [--dry-run] [--start-at N]"
            exit 1
            ;;
    esac
}

main "$@"
