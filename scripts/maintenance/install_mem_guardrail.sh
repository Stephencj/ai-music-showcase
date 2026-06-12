#!/bin/bash
#
# install_mem_guardrail.sh — install the AI Music Studio memory-watchdog
# LaunchAgent. Idempotent: re-running cleanly replaces the install.
#
# Override the cap (MB) by exporting AI_MUSIC_MEM_CAP_MB before running:
#     AI_MUSIC_MEM_CAP_MB=10240 ./scripts/maintenance/install_mem_guardrail.sh
#
# Verify afterwards:
#     launchctl list | grep memguard
#     tail -f logs/mem_guardrail.log

set -euo pipefail

LABEL="com.stephencjuliano.aimusic-memguard"
CAP_MB="${AI_MUSIC_MEM_CAP_MB:-8192}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${SCRIPT_DIR}/${LABEL}.plist.template"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [ ! -f "${TEMPLATE}" ]; then
    echo "ERROR: plist template missing at ${TEMPLATE}" >&2
    exit 1
fi

# macOS TCC forbids a launchd agent from executing a script that lives
# inside ~/Documents. Copy the runtime script to a non-protected dir and
# point the plist there. The repo copy stays the source of truth.
RUNTIME_DIR="${HOME}/Library/Application Support/${LABEL}"
RUNTIME_SCRIPT="${RUNTIME_DIR}/mem_guardrail.sh"
mkdir -p "${RUNTIME_DIR}" "${HOME}/Library/LaunchAgents" "${PROJECT_ROOT}/logs"
cp "${SCRIPT_DIR}/mem_guardrail.sh" "${RUNTIME_SCRIPT}"
chmod +x "${RUNTIME_SCRIPT}"

sed \
    -e "s|@RUNTIME_SCRIPT@|${RUNTIME_SCRIPT}|g" \
    -e "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" \
    -e "s|@CAP_MB@|${CAP_MB}|g" \
    "${TEMPLATE}" > "${TARGET}"

DOMAIN="gui/$(id -u)"

# Reload cleanly. bootout returns non-zero when not loaded — ignore.
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "${DOMAIN}" "${TARGET}"
launchctl enable "${DOMAIN}/${LABEL}"

echo "Installed ${LABEL} (cap=${CAP_MB}MB)."
echo "  Status:  launchctl list | grep memguard"
echo "  Log:     tail -f '${RUNTIME_SCRIPT%/*}/mem_guardrail.log'"
echo "  Uninstall: launchctl bootout ${DOMAIN}/${LABEL}"
