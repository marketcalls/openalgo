#!/bin/bash
# Deployment scripts that do NOT launch Gunicorn but could still break the
# migration (GT-C3-11, GT-C3-12).
#
# Both turned out to need no change. That is a fine outcome, but "no change
# needed" decays: someone can later teach change-domain.sh to rewrite the unit,
# or give update.bat service handling, and silently undo the reasoning. These
# checks pin the properties the conclusion rests on, so the decision fails loudly
# instead of quietly becoming wrong.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CHANGE_DOMAIN="$REPO/install/change-domain.sh"
UPDATE_BAT="$REPO/install/update.bat"

PASS=0; FAIL=0
ok() { echo "  PASS - $1"; PASS=$((PASS+1)); }
no() { echo "  FAIL - $1"; FAIL=$((FAIL+1)); }

echo "== GT-C3-11: change-domain.sh must not disturb a migrated unit =="

[ -f "$CHANGE_DOMAIN" ] || { echo "FAIL - $CHANGE_DOMAIN missing"; exit 1; }

# The whole reason this row was flagged: after update.sh migrates ExecStart, a
# script that rewrites the unit would silently revert the worker class. It reads
# the path only to display it, so there is nothing to revert.
if grep -nE '(tee|cat|sed -i|>>?)[^|]*\$SERVICE_FILE' "$CHANGE_DOMAIN" \
   | grep -vE '^\s*[0-9]+:\s*#' | grep -q .; then
    no "change-domain.sh writes to \$SERVICE_FILE"
else
    ok "change-domain.sh never writes the systemd unit"
fi

grep -q "ExecStart" "$CHANGE_DOMAIN" \
    && no "change-domain.sh references ExecStart" \
    || ok "change-domain.sh never touches ExecStart"

# It restarts the service, which is exactly what should happen -- the migrated
# unit is picked up unchanged.
grep -qE 'systemctl (stop|start|restart) "\$SERVICE_NAME"' "$CHANGE_DOMAIN" \
    && ok "change-domain.sh restarts the service by name" \
    || no "change-domain.sh no longer restarts the service"

echo "== GT-C3-11: the regenerated Socket.IO config must survive =="

# change-domain.sh rewrites the nginx config, so it owns the /socket.io/ block.
# Losing an upgrade header here breaks the WebSocket transport for every client
# after a domain change -- and it would look like an application bug.
socketio_block() {
    awk '/location \/socket.io\/ \{/,/^\s*\}/' "$CHANGE_DOMAIN"
}

BLOCK="$(socketio_block)"
[ -n "$BLOCK" ] \
    && ok "the /socket.io/ location block is present" \
    || no "the /socket.io/ location block is gone"

for directive in "proxy_http_version 1.1" \
                 "proxy_set_header Upgrade" \
                 'Connection "upgrade"' \
                 "proxy_buffering off"; do
    printf '%s' "$BLOCK" | grep -q "$directive" \
        && ok "Socket.IO block keeps: $directive" \
        || no "Socket.IO block lost: $directive"
done

# Long-lived Socket.IO sessions must not be cut by the default 60s read timeout.
printf '%s' "$BLOCK" | grep -qE "proxy_read_timeout [0-9]+s" \
    && ok "Socket.IO block sets an extended read timeout" \
    || no "Socket.IO block has no extended read timeout"

echo "== GT-C3-12: update.bat needs no unit handling =="

[ -f "$UPDATE_BAT" ] || { echo "FAIL - $UPDATE_BAT missing"; exit 1; }

# Windows has no systemd unit and does not run Gunicorn, so there is nothing to
# migrate. If any of this ever appears, the row must be reopened rather than
# left resolved on a stale reading.
if grep -qiE "gunicorn|systemd|--worker-class|eventlet|gthread" "$UPDATE_BAT"; then
    no "update.bat now references a worker or service manager - reopen GT-C3-12"
else
    ok "update.bat references no worker class or service manager"
fi

# Confirm what it *does* do, so the conclusion rests on the script's real shape
# rather than on the absence of keywords.
for step in "git pull" "uv" "migrat"; do
    grep -qi "$step" "$UPDATE_BAT" \
        && ok "update.bat still performs: $step" \
        || no "update.bat no longer performs: $step"
done

echo "== Windows and macOS already run on real threads =="

# This is why the PR-1..PR-10 concurrency fixes are bug fixes rather than
# migration scaffolding: the dev server has never used eventlet, so every race
# they close has been reachable on Windows and macOS all along.
grep -q "uses standard threading, not eventlet" "$REPO/CLAUDE.md" \
    && ok "CLAUDE.md records that the dev server uses threads, not eventlet" \
    || no "CLAUDE.md no longer records the dev-server threading model"

# The dev-server entrypoint must not quietly acquire an eventlet dependency.
if grep -nE "^\s*import eventlet|^\s*eventlet\.monkey_patch" "$REPO/app.py" | grep -q .; then
    no "app.py imports or monkey-patches eventlet"
else
    ok "app.py does not import eventlet"
fi

echo
echo "Passed: $PASS  Failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
