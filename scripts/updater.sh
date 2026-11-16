#!/bin/sh
set -u

# Argument 1 is the git branch to pull (default: main).
BRANCH="${1:-main}"

# Argument 2 is the Python executable that launched CraftBot. Reusing it keeps
# updates on the same interpreter and avoids python/python3 mismatches.
PYTHON_BIN="${2:-${PYTHON:-python3}}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LOG="$ROOT_DIR/updater.log"

log() {
    printf '%s\n' "$*" >> "$LOG"
}

# The user's runtime files. They used to be tracked, so an edited copy (API
# keys, memory) made `git pull` refuse to update. They are untracked now; this
# carries the user's copies across the pull that untracks them, and is a
# no-op on every pull after it.
RUNTIME_FILES="app/config/settings.json app/config/mcp_config.json app/config/scheduler_config.json app/config/skills_config.json agent_file_system/MEMORY.md agent_file_system/ENTITIES.md agent_file_system/PROACTIVE.md"
KEEP_DIR="$ROOT_DIR/.update-keep"

keep_runtime_files() {
    rm -rf "$KEEP_DIR"
    for f in $RUNTIME_FILES; do
        if [ -f "$f" ]; then
            mkdir -p "$KEEP_DIR/$(dirname "$f")"
            cp -p "$f" "$KEEP_DIR/$f" || return 1
        fi
        if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
            git checkout -- "$f" >> "$LOG" 2>&1
        fi
    done
}

restore_runtime_files() {
    for f in $RUNTIME_FILES; do
        if [ -f "$KEEP_DIR/$f" ]; then
            mkdir -p "$(dirname "$f")"
            cp -p "$KEEP_DIR/$f" "$f"
        fi
    done
    rm -rf "$KEEP_DIR"
}

fail() {
    restore_runtime_files
    log "$(date) - UPDATE FAILED: $*"
    exit 1
}

{
    printf '\n'
    printf '============================================\n'
    printf '%s - Updater start (branch=%s)\n' "$(date)" "$BRANCH"
    printf 'CWD=%s\n' "$ROOT_DIR"
    printf 'Python=%s\n' "$PYTHON_BIN"
} >> "$LOG"

cd "$ROOT_DIR" || fail "could not cd to $ROOT_DIR"

# Wait for current CraftBot to fully terminate.
sleep 3

log "--- git fetch ---"
git fetch origin "$BRANCH" >> "$LOG" 2>&1 || fail "git fetch failed"

log "--- keeping runtime files ---"
keep_runtime_files || fail "could not back up runtime files"

log "--- git checkout ---"
git checkout "$BRANCH" >> "$LOG" 2>&1 || fail "git checkout failed"

log "--- git pull ---"
git pull --ff-only origin "$BRANCH" >> "$LOG" 2>&1 || fail "git pull failed"
restore_runtime_files

if [ -f install.py ]; then
    log "--- install.py ---"
    "$PYTHON_BIN" install.py >> "$LOG" 2>&1 || fail "install.py failed"
fi

log "--- relaunching CraftBot ---"
nohup "$PYTHON_BIN" run.py --conda >> "$LOG" 2>&1 &
log "$(date) - Updater done, relaunched CraftBot"
exit 0
