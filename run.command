#!/bin/bash
# Double-clickable launcher for the AI Music Studio (Gradio UI).
# Opens the Compose tab in your default browser at http://localhost:7860.
#
# Both the Terminal output AND any pre-Python errors (missing venv,
# import-time tracebacks) are tee'd to logs/app.log. The Python app
# itself ALSO writes structured runtime errors to the same file via
# the logger configured in app.py.

cd "$(dirname "$0")" || exit 1
mkdir -p logs

LOG_FILE="logs/app.log"

{
    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') Starting AI Music Studio ==="

    if [ ! -x ".venv/bin/python" ]; then
        echo "ERROR: .venv/bin/python not found at $(pwd)/.venv"
        echo "Run setup first, then try again."
        read -n 1 -s -r -p "Press any key to close..."
        exit 1
    fi

    .venv/bin/python app.py
    EXIT_CODE=$?
    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') Exited with code $EXIT_CODE ==="
    if [ "$EXIT_CODE" -ne 0 ]; then
        echo "App exited with an error. Full log: $(pwd)/$LOG_FILE"
        read -n 1 -s -r -p "Press any key to close..."
    fi
} 2>&1 | tee -a "$LOG_FILE"
