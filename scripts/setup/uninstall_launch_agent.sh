#!/bin/bash
#
# uninstall_launch_agent.sh — stop and remove the AI Music Studio
# LaunchAgent. Symmetric to install_launch_agent.sh.

set -euo pipefail

LABEL="com.stephencjuliano.aimusic"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true

if [ -f "${TARGET}" ]; then
    rm -f "${TARGET}"
    echo "Removed ${TARGET}"
else
    echo "No plist at ${TARGET} — already uninstalled."
fi

if launchctl list | grep -q "${LABEL}"; then
    echo "WARNING: launchctl still lists ${LABEL}." >&2
    exit 1
fi
echo "Done."
