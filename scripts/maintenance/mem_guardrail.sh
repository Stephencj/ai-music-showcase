#!/bin/bash
#
# mem_guardrail.sh — memory watchdog for the AI Music Studio daemon.
#
# Background: a stuck Gradio client (reconnect/poll loop) can keep
# resubmitting heavy renders. Each render is memory-hungry; under a
# tight respawn loop the process eventually exhausts RAM + swap and the
# whole Mac hangs hard (watchdog-timeout kernel panic). See the night
# of 2026-06-08, when app.py crash-looped ~10× and the machine froze.
#
# This watchdog runs as its own LaunchAgent and does ONE job: if the
# aimusic process's resident memory crosses CAP_MB, it SIGTERMs it (and
# SIGKILLs if it won't die) so launchd respawns a clean instance. The
# app survives the kill; the *machine* survives the runaway. It never
# touches Fooocus or anything else.
#
# Tunables (all overridable via the LaunchAgent's EnvironmentVariables):
#   AI_MUSIC_MEM_CAP_MB    resident-memory ceiling per process (default 8192)
#   AI_MUSIC_MEM_INTERVAL  seconds between checks            (default 20)
#   AI_MUSIC_MEM_GRACE     seconds to wait for graceful exit (default 10)
#   AI_MUSIC_MEM_LOG       log file (default <project>/logs/mem_guardrail.log)
#
# It matches the daemon by command line (".venv/bin/python app.py"), so
# it only ever targets the AI Music Studio server, never this script or
# an interactive python.

set -u

CAP_MB="${AI_MUSIC_MEM_CAP_MB:-8192}"
INTERVAL="${AI_MUSIC_MEM_INTERVAL:-20}"
GRACE="${AI_MUSIC_MEM_GRACE:-10}"

# PROJECT_ROOT is normally injected by the installer (via the plist's
# EnvironmentVariables) because the running copy of this script lives
# outside the repo — macOS TCC forbids a launchd agent from executing a
# script inside ~/Documents. Fall back to deriving it from our own
# location when run by hand from the repo.
if [ -n "${AI_MUSIC_PROJECT_ROOT:-}" ]; then
    PROJECT_ROOT="${AI_MUSIC_PROJECT_ROOT}"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi
# Default the log next to the running script (a non-protected dir), not
# into ~/Documents which the agent may not be allowed to write.
LOG="${AI_MUSIC_MEM_LOG:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mem_guardrail.log}"

# Match the daemon precisely: the venv python running app.py from this
# project. Anchoring on the project path avoids ever matching unrelated
# python processes.
MATCH="${PROJECT_ROOT}/.venv/bin/python app.py"

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "${LOG}"
}

mkdir -p "$(dirname "${LOG}")"
log "mem_guardrail started — cap=${CAP_MB}MB interval=${INTERVAL}s match='${MATCH}'"

while true; do
    # pgrep -f matches against the full argv; -- guards a leading dash.
    while IFS= read -r pid; do
        [ -z "${pid}" ] && continue
        # RSS is reported in KB by ps.
        rss_kb="$(ps -o rss= -p "${pid}" 2>/dev/null | tr -d ' ')"
        [ -z "${rss_kb}" ] && continue
        rss_mb=$(( rss_kb / 1024 ))
        if [ "${rss_mb}" -ge "${CAP_MB}" ]; then
            log "pid ${pid} RSS ${rss_mb}MB >= cap ${CAP_MB}MB — sending SIGTERM (launchd will respawn)"
            kill -TERM "${pid}" 2>/dev/null
            # Give it a chance to flush/exit cleanly, then force.
            waited=0
            while [ "${waited}" -lt "${GRACE}" ] && kill -0 "${pid}" 2>/dev/null; do
                sleep 1
                waited=$(( waited + 1 ))
            done
            if kill -0 "${pid}" 2>/dev/null; then
                log "pid ${pid} still alive after ${GRACE}s — sending SIGKILL"
                kill -KILL "${pid}" 2>/dev/null
            fi
        fi
    done < <(pgrep -f -- "${MATCH}")
    sleep "${INTERVAL}"
done
