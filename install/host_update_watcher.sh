#!/bin/bash
# OpenAlgo host-side update watcher (Docker deployments).
# Run every minute from cron (the user that owns the checkout and can run docker):
#   * * * * * flock -n /tmp/openalgo_host_update.lock /path/to/openalgo/install/host_update_watcher.sh >> /path/to/openalgo/log/host_watcher.log 2>&1
#
# Protocol with the container (shared volume /app/tmp):
#   container POST /api/update/run  -> writes /app/tmp/update_requested.json
#   this script (host)              -> validates it, writes a "running" result,
#                                      deletes the flag, then git pull +
#                                      docker compose build + up -d, and finally
#                                      writes /app/tmp/update_result.json
# Market-hours guard (IST 09:00-15:30) applies unless the request set force:true.
set -euo pipefail
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

FLAG_JSON="$(read_flag || true)"
# A partially written flag is possible for a split second; re-read once before
# declaring the request malformed.
if ! printf '%s' "$FLAG_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d.get("force"), bool) else 1)' 2>/dev/null; then
  sleep 1
  FLAG_JSON="$(read_flag || true)"
fi
log "Update requested: $FLAG_JSON"

# Validate the request before acting on it — any existing file used to pass.
if ! printf '%s' "$FLAG_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d.get("force"), bool) else 1)' 2>/dev/null; then
  log "Invalid request payload — ignoring"
  write_result '{"state": "error", "finished_at": "'"$(date -u '+%FT%TZ')"'", "summary": "Malformed update request (not valid JSON with a boolean force field)."}'
  clear_flag
  exit 1
fi
FORCE="$(printf '%s' "$FLAG_JSON" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("force") else "0")' || echo 0)"

# --- market-hours guard (authoritative) ---
if [ "$FORCE" != "1" ]; then
  IST_HM="$(TZ=Asia/Kolkata date +%H%M)"
  if [ "$IST_HM" -ge 0900 ] && [ "$IST_HM" -le 1530 ]; then
    log "Refusing: market hours ($IST_HM IST), no force flag."
    write_result "{\"state\": \"refused_market_hours\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"Blocked 09:00-15:30 IST. Retry with force checked.\"}"
    clear_flag
    exit 43
  fi
fi

START="$(date -u '+%FT%TZ')"
# Publish the in-flight marker BEFORE removing the flag, so the web UI sees
# state=running (and answers 409) for the whole window, not just the gap
# between flag removal and the first build output.
write_result "{\"state\": \"running\", \"started_at\": \"$START\", \"summary\": \"git pull + compose build + up -d in progress\"}"
clear_flag

# A failed cd must not leave state=running forever, blocking future updates.
if ! cd "$APP"; then
  log "cannot cd to $APP"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"watcher cannot cd to $APP\"}"
  exit 1
fi

# Host is authoritative for branch (container has no git; flag only hints).
BRANCH="$(git branch --show-current 2>/dev/null || echo main)"
log "Pulling $BRANCH (upstream: $(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo '?')) …"
if ! git pull >>"$LOG" 2>&1; then
  log "git pull FAILED"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"git pull failed — see host log/host_watcher.log\"}"
  exit 1
fi
# @{u} fails when the branch tracks a raw URL remote (no remote-tracking ref
# is stored for those) — then use the configured remote URL itself, so the
# baked stamp still points at the repo the branch actually pulls from.
# Never let the lookup kill the script under set -e.
_UPSTREAM_REMOTE="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null | cut -d/ -f1 || true)"
if [ -n "$_UPSTREAM_REMOTE" ]; then
  GIT_REMOTE_RAW="$(git remote get-url "$_UPSTREAM_REMOTE" 2>/dev/null || echo unknown)"
else
  GIT_REMOTE_RAW="$(git config --get "branch.$BRANCH.remote" 2>/dev/null || echo unknown)"
fi
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
export GIT_BRANCH="$BRANCH"
# Strip any user:pass@ userinfo — a remote URL may embed credentials and must
# never be baked into the image or written to a log.
GIT_REMOTE_RAW="${GIT_REMOTE_RAW:-unknown}"
export GIT_REMOTE="$(printf '%s' "$GIT_REMOTE_RAW" | sed -E 's#(://)[^/@]+@#\1#')"
log "Building $GIT_SHA ($GIT_BRANCH @ $GIT_REMOTE) …"

log "Rebuilding container (code COPY layer invalidates) …"
if ! docker compose build >>"$LOG" 2>&1; then
  log "docker compose build FAILED"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"compose build failed at $GIT_SHA\"}"
  exit 1
fi

log "Restarting container …"
if ! docker compose up -d >>"$LOG" 2>&1; then
  log "docker compose up -d FAILED"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"compose up -d failed at $GIT_SHA — old image may still be running\"}"
  exit 1
fi

# Wait for the container to report running/healthy before declaring success.
# The compose healthcheck has start_period 40s + interval 30s, so "healthy"
# can legitimately take ~2 min after the recreate — poll for 3 minutes.
STATE="unknown"
for _ in $(seq 1 36); do
  STATE="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || echo unknown)"
  case "$STATE" in
    running|healthy) break ;;
  esac
  sleep 5
done
if [ "$STATE" != "running" ] && [ "$STATE" != "healthy" ]; then
  log "Container not healthy after recreate (state=$STATE)"
  write_result "{\"state\": \"error\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"updated to $GIT_SHA but container state is $STATE — check docker logs\"}"
  exit 1
fi

log "Update finished at $GIT_SHA (container state: $STATE)"
write_result "{\"state\": \"done\", \"started_at\": \"$START\", \"finished_at\": \"$(date -u '+%FT%TZ')\", \"summary\": \"Updated to $GIT_SHA ($GIT_BRANCH), container restarted ($STATE).\"}"
