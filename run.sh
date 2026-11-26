#!/usr/bin/env bash
# run.sh — Launch AI Interview Copilot (Linux)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use venv python if available
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "🚀 Starting AI Interview Copilot..."
"$PYTHON" "$SCRIPT_DIR/run.py" "$@"
