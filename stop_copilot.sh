#!/usr/bin/env bash
# stop_copilot.sh — Stop all running AI Interview Copilot processes (Linux)
echo "🛑 Stopping AI Interview Copilot..."
pkill -f "run.py" 2>/dev/null && echo "✅ Stopped." || echo "ℹ️  No running instance found."
