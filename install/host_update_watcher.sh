#!/bin/bash
# OpenAlgo host-side update watcher (Docker deployments).
# Run every minute from cron (the user that owns the checkout and can run docker):
#   * * * * * flock -n /tmp/openalgo_host_update.lock /path/to/openalgo/install/host_update_watcher.sh >> /path/to/openalgo/log/host_watcher.log 2>&1
#
# Protocol with the container (shared volume /app/tmp):
#   container POST /api/update/run  -> writes /app/tmp/update_requested.json {force, branch, requested_at}
#   this script (host)              -> git pull + docker compose build + up -d,
#                                      writes /app/tmp/update_result.json {state, ...}
#                                      and deletes the request flag.
# Market-hours guard (IST 09:00-15:30) applies unless the request set force:true.
set -u
APP="${APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONTAINER="${CONTAINER:-openalgo-web}"
LOG="$APP/log/host_watcher.log"
mkdir -p "$APP/log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

have_flag() { docker exec "$CONTAINER" test -f /app/tmp/update_requested.json 2>/dev/null; }
read_flag()  { docker exec "$CONTAINER" cat /app/tmp/update_requested.json 2>/dev/null; }
write_result() { # $1 = json
  echo "$1" | docker exec -i "$CONTAINER" tee /app/tmp/update_result.json >/dev/null 2>&1 \
    || echo "$1" >> "$LOG"
}
clear_flag() { docker exec "$CONTAINER" rm -f /app/tmp/update_requested.json 2>/dev/null; }

if ! have_flag; then
  exit 0  # nothing requested — quiet exit, no log spam
fi

FLAG_JSON="$(read_flag)"
log "Update requested: $FLAG_JSON"
FORCE="$(echo "$FLAG_JSON" | grep -o '"force": *true' || true)"

# --- market-hours guard (authoritative) ---
if [ -z "$FORCE" ]; then
  IST_HM="$(TZ=Asia/Kolkata date +%H%M)"
  if [ "$IST_HM" -ge 0900 ] && [ "$IST_HM" -le 1530 ]; then
    log "Refusing: market hours ($IST_HM IST), no force flag."
    write_result "{\"state\": \"refused_market_hours\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"Blocked 09:00-15:30 IST. Retry with force checked.\"}"
    clear_flag
    exit 43
  fi
fi

clear_flag
START="$(date -u '+%FT%TZ')"
write_result "{\"state\": \"running\", \"started_at\": \"$START\", \"summary\": \"git pull + compose build + up -d in progress\"}"

cd "$APP" || { write_result '{"state": "error", "summary": "cannot cd to APP"}'; exit 1; }

# Host is authoritative for branch (container has no git; flag only hints).
# Pull via the branch's configured upstream — this checkout tracks the
# FORK (fork/<branch>), not origin, so `git pull origin <branch>` would fail.
BRANCH="$(git branch --show-current 2>/dev/null || echo main)"
log "Pulling $BRANCH (upstream: $(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo '?')) ..."
if ! git pull >>"$LOG" 2>&1; then
  log "git pull FAILED"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"git pull failed — see host log/host_watcher.log\"}"
  exit 1
fi
_UPSTREAM_REMOTE="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null | cut -d/ -f1)"
export GIT_SHA="$(git rev-parse --short HEAD)"
export GIT_BRANCH="$BRANCH"
export GIT_REMOTE="$(git remote get-url "$_UPSTREAM_REMOTE" 2>/dev/null || git remote get-url origin 2>/dev/null || echo unknown)"
log "Building $GIT_SHA ($GIT_BRANCH @ $GIT_REMOTE) ..."

log "Rebuilding container (plain build; code COPY layer invalidates) ..."
if ! docker compose build >>"$LOG" 2>&1; then
  log "docker compose build FAILED"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"compose build failed at $GIT_SHA\"}"
  exit 1
fi

log "Restarting container ..."
docker compose up -d >>"$LOG" 2>&1
sleep 8
if docker compose ps --format json 2>/dev/null | grep -q '"Health":"healthy"\|"State":"running"'; then
  : # container object exists; deeper health follows in OpenAlgo logs
fi

log "Update finished at $GIT_SHA"
write_result "{\"state\": \"done\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"Updated to $GIT_SHA ($GIT_BRANCH), container restarted.\"}"
