#!/bin/bash
# OpenAlgo web-triggered updater — called detached from the Flask UI.
# Same safe sequence as install/update.sh, plus:
#   * lock file /tmp/openalgo_update.lock (created by Flask, removed here on exit)
#   * refuses market hours 09:00–15:30 IST unless WEB_UPDATE_FORCE=1
#   * logs to log/update_web.log
# Run: sudo /bin/bash install/update_web.sh   (Flask launches it via setsid)
set -u
LOCK="/tmp/openalgo_update.lock"
trap 'rm -f "$LOCK"' EXIT

if [ -f /.dockerenv ]; then
  echo "Inside a container: code is baked into the image — this script cannot update it."
  echo "Use the web button (host watcher fulfils it) or run install/host_update_watcher.sh on the host."
  exit 44
fi

# resolve app root (this script lives in <app>/install/)
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP" || exit 1
mkdir -p log install/logs
LOG="$APP/log/update_web.log"
echo "===== web update started $(date -u '+%F %T UTC') =====" | tee -a "$LOG"

# --- market-hours guard (IST) ---
FORCE="${WEB_UPDATE_FORCE:-0}"
if [ "$FORCE" != "1" ]; then
  IST_HM="$(TZ=Asia/Kolkata date +%H%M)"
  if [ "$IST_HM" -ge 0900 ] && [ "$IST_HM" -le 1530 ]; then
    echo "Refusing: market hours ($IST_HM IST). Set WEB_UPDATE_FORCE=1 or re-POST with force:true." | tee -a "$LOG"
    exit 43
  fi
fi

# --- detect layout ---
if [ -d "/var/python/openalgo/.git" ]; then
  echo "Server install detected (/var/python/openalgo). Delegating to install/update.sh …" | tee -a "$LOG"
  sudo /bin/bash "$APP/install/update.sh" 2>&1 | tee -a "$LOG"
  exit ${PIPESTATUS[0]}
fi

# --- docker / local fallback: same steps, no service restart ---
echo "Non-server layout — running safe manual sequence…" | tee -a "$LOG"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "db/backup_$TS"
cp db/*.db db/*.duckdb "db/backup_$TS/" 2>/dev/null || true
echo "DB backup → db/backup_$TS" | tee -a "$LOG"

# `git pull` follows the branch's configured upstream. Forks that track a
# remote other than origin (the common case) would break on `pull origin`.
git pull 2>&1 | tee -a "$LOG"
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
  echo "git pull failed — aborting." | tee -a "$LOG"
  exit 1
fi
if command -v uv >/dev/null 2>&1; then
  uv sync 2>&1 | tee -a "$LOG"
else
  pip install -r requirements.txt 2>&1 | tee -a "$LOG"
fi

if [ -f upgrade/migrate_all.py ]; then
  if command -v uv >/dev/null 2>&1; then
    uv run upgrade/migrate_all.py 2>&1 | tee -a "$LOG" || exit 1
  else
    python3 upgrade/migrate_all.py 2>&1 | tee -a "$LOG" || exit 1
  fi
fi

# docker: rebuild and recreate in one step (named volumes survive)
if [ -f docker-compose.yaml ] && command -v docker >/dev/null 2>&1; then
  echo "Docker layout — rebuild & restart containers…" | tee -a "$LOG"
  sudo docker compose up -d --build 2>&1 | tee -a "$LOG"
fi

echo "===== web update finished $(date -u '+%F %T UTC') =====" | tee -a "$LOG"
