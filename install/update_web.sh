#!/bin/bash
# OpenAlgo web-triggered updater — launched detached by the Flask UI
# (blueprints/system_update.py). Same core sequence as install/update.sh:
# stop service → back up db/* → git pull → sync deps → migrate → restart.
#
# Usage:
#   sudo /bin/bash /usr/local/sbin/openalgo-update /var/python/openalgo
#
# The sudoers rule must grant NOPASSWD on a ROOT-OWNED copy of this script
# installed OUTSIDE the checkout, with the app path pinned as the argument
# (see docs/system-update.md). The checkout is owned by the web user, so a
# rule pointing at install/update_web.sh would be a web-user-to-root hole.
#
# When run as root, every step that touches the checkout is executed as the
# checkout's owner; root is used only for systemctl. Local checkouts can run
# this script directly with no sudo at all.
#
# Extras over update.sh:
#   * lock file /tmp/openalgo_update.lock (created by Flask, removed here)
#   * refuses market hours 09:00–15:30 IST unless WEB_UPDATE_FORCE=1
#     (the web route sets it only when the user confirmed "force")
#   * logs to log/update_web.log
#   * any failed step aborts the update (set -euo pipefail) — the old
#     behaviour of reporting success after a hidden failure is gone
set -euo pipefail
shopt -s nullglob

LOCK="/tmp/openalgo_update.lock"
trap 'rm -f "$LOCK"' EXIT

# App root: pinned $1 > APP env > the directory above this script.
APP="${1:-${APP:-}}"
if [ -z "$APP" ]; then
  APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$APP"

if [ -f /.dockerenv ]; then
  echo "Inside a container: code is baked into the image — this script cannot update it."
  echo "Use the web button (the host watcher fulfils it) or install/host_update_watcher.sh on the host."
  exit 44
fi

# --- privilege model -------------------------------------------------------
# Root (via the sudoers wrapper) only ever calls systemctl; everything that
# writes into the checkout runs as the checkout's owner so the files stay
# owned by the web user and no web-writable script runs as root.
OWNER="$(stat -c %U "$APP" 2>/dev/null || echo root)"
RUN_AS=()
if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ]; then
  RUN_AS=(sudo -u "$OWNER")
fi
DOCKER=(docker)
if [ "$(id -u)" -ne 0 ]; then
  DOCKER=(sudo docker)
fi
UV_BIN="$(command -v uv || true)"

"${RUN_AS[@]}" mkdir -p log install/logs
LOG="$APP/log/update_web.log"
log() { echo "$*" | tee -a "$LOG"; }

log "===== web update started $(date -u '+%F %T UTC') as $(id -un) (app root: $APP) ====="

# --- market-hours guard (IST 09:00–15:30) ----------------------------------
FORCE="${WEB_UPDATE_FORCE:-0}"
if [ "$FORCE" != "1" ]; then
  IST_HM="$(TZ=Asia/Kolkata date +%H%M)"
  if [ "$IST_HM" -ge 0900 ] && [ "$IST_HM" -le 1530 ]; then
    log "Refusing: market hours ($IST_HM IST). The web route must send force:true (WEB_UPDATE_FORCE=1)."
    exit 43
  fi
fi

# --- service? (server installs have a systemd unit `openalgo`) -------------
SERVICE=""
if [ "$(id -u)" -eq 0 ] && command -v systemctl >/dev/null 2>&1 \
   && systemctl list-unit-files 2>/dev/null | grep -q '^openalgo\.service'; then
  SERVICE="openalgo"
fi
if [ -n "$SERVICE" ]; then
  log "Stopping service $SERVICE …"
  sudo systemctl stop "$SERVICE" || log "WARN: systemctl stop failed (continuing)"
fi

# --- back up databases FIRST; a failed backup aborts the update ------------
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="db/backup_$TS"
DBS=(db/*.db db/*.duckdb)
if [ "${#DBS[@]}" -gt 0 ]; then
  "${RUN_AS[@]}" mkdir -p "$BACKUP_DIR"
  # No `|| true`: if the databases exist but cannot be copied, stop here.
  "${RUN_AS[@]}" cp "${DBS[@]}" "$BACKUP_DIR/"
  log "DB backup → $BACKUP_DIR (${#DBS[@]} files)"
else
  log "No databases found to back up (fresh install)"
fi

# --- pull (follows the branch's configured upstream — forks are fine) ------
# Stash local modifications first so a dirty tree cannot fail the pull.
LOCAL_CHANGES="$("${RUN_AS[@]}" git status --porcelain 2>/dev/null | grep -v '^??' || true)"
if [ -n "$LOCAL_CHANGES" ]; then
  log "Local modifications detected — stashing before pull"
  "${RUN_AS[@]}" git stash push -m "auto-stash before web update $TS" 2>&1 | tee -a "$LOG"
fi
log "git pull …"
"${RUN_AS[@]}" git pull 2>&1 | tee -a "$LOG"

# --- dependencies -----------------------------------------------------------
if [ -n "$UV_BIN" ]; then
  log "uv sync …"
  "${RUN_AS[@]}" "$UV_BIN" sync 2>&1 | tee -a "$LOG"
elif [ -x "$APP/.venv/bin/python" ]; then
  log "uv not found — installing dependencies with the venv's pip …"
  "${RUN_AS[@]}" "$APP/.venv/bin/python" -m pip install . 2>&1 | tee -a "$LOG"
else
  log "ERROR: neither uv nor $APP/.venv/bin/python is available — cannot sync dependencies."
  exit 1
fi

# --- migrations -------------------------------------------------------------
if [ -f upgrade/migrate_all.py ]; then
  log "upgrade/migrate_all.py …"
  if [ -n "$UV_BIN" ]; then
    "${RUN_AS[@]}" "$UV_BIN" run upgrade/migrate_all.py 2>&1 | tee -a "$LOG"
  else
    "${RUN_AS[@]}" python3 upgrade/migrate_all.py 2>&1 | tee -a "$LOG"
  fi
fi

# --- docker layout: rebuild and recreate in one step (named volumes survive)
# Only when this checkout actually has compose services running — a plain
# local checkout that merely contains a docker-compose.yaml must not restart
# someone's containers as a side effect.
if [ -f docker-compose.yaml ] && command -v docker >/dev/null 2>&1 \
   && [ -n "$("${DOCKER[@]}" compose ps -q 2>/dev/null)" ]; then
  log "Docker layout — compose up -d --build …"
  "${DOCKER[@]}" compose up -d --build 2>&1 | tee -a "$LOG"
fi

# --- restart the service ----------------------------------------------------
if [ -n "$SERVICE" ]; then
  log "Starting service $SERVICE …"
  sudo systemctl start "$SERVICE"
fi

log "===== web update finished $(date -u '+%F %T UTC') ====="
