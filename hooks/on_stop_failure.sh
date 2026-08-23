#!/usr/bin/env bash
# Claude Code hook -> govee-signals
# Fires the "stop_failure" signal. Runs detached and always exits 0 so a slow or
# unreachable bulb can never delay or fail the turn.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${GOVEE_SIGNALS_PYTHON:-python3}"

# .env is loaded explicitly by config.py from $PROJECT_DIR/.env --
# nothing here relies on the shell environment already having the keys.
nohup "$PYTHON" "$PROJECT_DIR/signal.py" "stop_failure" >/dev/null 2>&1 &

exit 0
