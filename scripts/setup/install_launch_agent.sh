#!/bin/bash
#
# install_launch_agent.sh — install the AI Music Studio LaunchAgent so
# the Gradio server starts automatically at login and respawns on
# crash. Idempotent: re-running it cleanly replaces the existing
# install.
#
# Reads AI_MUSIC_AUTH_TOKEN, AI_MUSIC_HOST, AI_MUSIC_PORT from .env if
# present. Prompts for AUTH_TOKEN when missing (you can press Enter to
# leave it empty, but Tailscale-reachable installs really should set
# one).
#
# Run:
#     ./scripts/setup/install_launch_agent.sh
#
# Verify afterwards:
#     launchctl list | grep aimusic
#     curl http://127.0.0.1:7860/healthz

set -euo pipefail

LABEL="com.stephencjuliano.aimusic"

# Resolve the project root from this script's location so the plist
# embeds absolute paths regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${SCRIPT_DIR}/com.stephencjuliano.aimusic.plist.template"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [ ! -x "${PYTHON}" ]; then
    echo "ERROR: ${PYTHON} not found." >&2
    echo "Create the venv first: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

if [ ! -f "${TEMPLATE}" ]; then
    echo "ERROR: plist template missing at ${TEMPLATE}" >&2
    exit 1
fi

# Load .env if present so we can pick up the user's existing settings.
if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "${PROJECT_ROOT}/.env"
    set +a
fi

HOST="${AI_MUSIC_HOST:-0.0.0.0}"
PORT="${AI_MUSIC_PORT:-7860}"
TOKEN="${AI_MUSIC_AUTH_TOKEN:-}"

if [ -z "${TOKEN}" ]; then
    echo ""
    echo "AI_MUSIC_AUTH_TOKEN is not set in .env. The server will run"
    echo "without authentication — fine for trusted home Wi-Fi, but"
    echo "anyone on your Tailscale tailnet will be able to reach it."
    echo ""
    printf "Enter a token now (or press Enter to skip): "
    read -r TOKEN || TOKEN=""
fi

# Substitute placeholders into the plist body.
mkdir -p "${HOME}/Library/LaunchAgents"
sed \
    -e "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" \
    -e "s|@PYTHON@|${PYTHON}|g" \
    -e "s|@HOST@|${HOST}|g" \
    -e "s|@PORT@|${PORT}|g" \
    -e "s|@AUTH_TOKEN@|${TOKEN}|g" \
    "${TEMPLATE}" > "${TARGET}"

# Restart any prior instance so the new plist takes effect. ``bootout``
# fails with status 36 (No such process) when the agent isn't loaded —
# that's fine, we ignore it and proceed to bootstrap.
#
# launchd occasionally still has the label cached when bootstrap runs
# right after bootout — it returns "5: Input/output error". Retry a
# few times with a short sleep; usually one extra attempt is enough.
DOMAIN="gui/$(id -u)"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "${DOMAIN}" "${TARGET}" 2>/tmp/aimusic-bootstrap.err; then
        break
    fi
    if [ "${attempt}" -eq 5 ]; then
        echo "ERROR: launchctl bootstrap kept failing." >&2
        cat /tmp/aimusic-bootstrap.err >&2
        exit 1
    fi
    sleep 1
done
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}"

# Give launchd a beat to spawn, then check.
sleep 1
if launchctl list | grep -q "${LABEL}"; then
    echo "Installed ${LABEL} → ${TARGET}"
    echo ""
    launchctl list | grep "${LABEL}"
    echo ""
    echo "Probing http://127.0.0.1:${PORT}/healthz ..."
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS "http://127.0.0.1:${PORT}/healthz" \
                ${TOKEN:+-H "X-AI-Music-Token: ${TOKEN}"} > /dev/null; then
            echo "Server is up."
            exit 0
        fi
        sleep 1
    done
    echo "WARNING: server not responding after 10s." >&2
    echo "Check ${PROJECT_ROOT}/logs/launchd.err for the failure." >&2
    exit 1
else
    echo "ERROR: launchctl list does not show ${LABEL}" >&2
    exit 1
fi
