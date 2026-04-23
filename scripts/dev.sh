#!/usr/bin/env bash
# scripts/dev.sh — run from source with hot-restart on file changes
#
# Usage:
#   ./scripts/dev.sh          # run once (kill existing, start fresh)
#   ./scripts/dev.sh --watch  # restart automatically on any src/ change

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: .venv not found. Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

_kill_existing() {
    # Kill any running source or bundle instance
    pkill -f "claude_usage_bar" 2>/dev/null || true
    pkill -f "Claude Usage Bar" 2>/dev/null || true
    sleep 0.3
}

_run() {
    echo "==> Starting claude-usage-bar from source..."
    "$PYTHON" -m claude_usage_bar
}

if [[ "${1:-}" == "--watch" ]]; then
    # Requires: brew install fswatch
    if ! command -v fswatch &>/dev/null; then
        echo "ERROR: --watch requires fswatch. Install with: brew install fswatch" >&2
        exit 1
    fi
    echo "==> Watching src/ for changes — will auto-restart on save."
    _kill_existing
    _run &
    APP_PID=$!
    fswatch -o src/ | while read -r _; do
        echo "==> Change detected — restarting..."
        kill "$APP_PID" 2>/dev/null || true
        wait "$APP_PID" 2>/dev/null || true
        _run &
        APP_PID=$!
    done
else
    _kill_existing
    _run
fi
