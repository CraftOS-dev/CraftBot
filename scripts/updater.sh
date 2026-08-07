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

fail() {
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

log "--- git checkout ---"
git checkout "$BRANCH" >> "$LOG" 2>&1 || fail "git checkout failed"

log "--- git pull ---"
git pull --ff-only origin "$BRANCH" >> "$LOG" 2>&1 || fail "git pull failed"

if [ -f install.py ]; then
    log "--- install.py ---"
    "$PYTHON_BIN" install.py >> "$LOG" 2>&1 || fail "install.py failed"
fi

log "--- relaunching CraftBot ---"
nohup "$PYTHON_BIN" run.py --conda >> "$LOG" 2>&1 &
log "$(date) - Updater done, relaunched CraftBot"
exit 0
