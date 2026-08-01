#!/usr/bin/env bash
# Tests for the start.sh process supervisor (gthread PR-2, gate A7a).
#
# Covers GT-A7-01 and GT-A7-03. The defect: start.sh backgrounded the proxy and
# installed a SIGTERM/SIGINT trap, then `exec`d gunicorn -- and exec replaces
# the shell, destroying the trap. The proxy was never gracefully stopped, an
# unexpected proxy exit was never noticed, and the health check probed only
# Flask, so a container could report healthy with market data dead.
#
# Run: bash test/test_gthread_start_supervisor.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START_SH="$REPO_ROOT/start.sh"

PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "  ok   - $1"; }
no() { FAIL=$((FAIL + 1)); echo "  FAIL - $1"; }

echo "== start.sh supervisor =="

bash -n "$START_SH" && ok "start.sh parses" || no "start.sh has a syntax error"

# 1. gunicorn must NOT be exec'd -- exec is what destroyed the trap.
if grep -qE '^\s*exec\s+.*gunicorn' "$START_SH"; then
    no "gunicorn is still exec'd, which destroys the signal trap"
else
    ok "gunicorn is not exec'd"
fi

# 2. gunicorn must be backgrounded with its PID captured.
grep -q 'GUNICORN_PID=\$!' "$START_SH" \
    && ok "gunicorn PID is captured for supervision" \
    || no "gunicorn PID is not captured"

# 3. The trap must still be installed, and reachable after gunicorn starts.
grep -qE '^trap cleanup SIGTERM SIGINT' "$START_SH" \
    && ok "signal trap is installed" || no "signal trap missing"

TRAP_LINE=$(grep -nE '^trap cleanup SIGTERM SIGINT' "$START_SH" | head -1 | cut -d: -f1)
GUNI_LINE=$(grep -nE 'GUNICORN_PID=\$!' "$START_SH" | head -1 | cut -d: -f1)
if [ -n "$TRAP_LINE" ] && [ -n "$GUNI_LINE" ] && [ "$TRAP_LINE" -lt "$GUNI_LINE" ]; then
    ok "trap is installed before gunicorn starts"
else
    no "trap is not installed before gunicorn starts"
fi

# 4. cleanup must signal BOTH children, not just the proxy.
CLEANUP=$(sed -n '/^cleanup() {/,/^}/p' "$START_SH")
echo "$CLEANUP" | grep -q 'GUNICORN_PID' \
    && ok "cleanup signals gunicorn" || no "cleanup does not signal gunicorn"
echo "$CLEANUP" | grep -q 'WEBSOCKET_PID' \
    && ok "cleanup signals the proxy" || no "cleanup does not signal the proxy"
echo "$CLEANUP" | grep -q 'kill -TERM' \
    && ok "cleanup sends SIGTERM before SIGKILL" || no "cleanup does not send SIGTERM"

# 5. A supervisor loop must exist that notices a dead proxy and bounds restarts.
grep -q 'WEBSOCKET_MAX_RESTARTS' "$START_SH" \
    && ok "proxy restarts are bounded" || no "proxy restarts are unbounded"
grep -q 'WebSocket proxy died, restarting' "$START_SH" \
    && ok "supervisor restarts a dead proxy" || no "supervisor does not restart the proxy"
grep -q 'Gunicorn exited with status' "$START_SH" \
    && ok "gunicorn exit is terminal and propagates status" \
    || no "gunicorn exit is not handled"

# --- behavioural: the trap survives because we no longer exec ---------------
# Model both shapes with a throwaway script and assert the trap fires.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/exec_shape.sh" <<'EOS'
CHILD_MARK="$1"
sleep 30 & CHILD=$!
cleanup() { echo "trap-fired" >> "$CHILD_MARK"; kill $CHILD 2>/dev/null; exit 0; }
trap cleanup SIGTERM
exec sleep 30
EOS

cat > "$WORK/supervisor_shape.sh" <<'EOS'
CHILD_MARK="$1"
sleep 30 & CHILD=$!
cleanup() { echo "trap-fired" >> "$CHILD_MARK"; kill $CHILD 2>/dev/null; exit 0; }
trap cleanup SIGTERM
sleep 30 & MAIN=$!
while kill -0 $MAIN 2>/dev/null; do sleep 0.2; done
EOS

for shape in exec_shape supervisor_shape; do
    MARK="$WORK/$shape.mark"; : > "$MARK"
    bash "$WORK/$shape.sh" "$MARK" &
    SPID=$!
    sleep 1
    kill -TERM "$SPID" 2>/dev/null
    sleep 1
    kill -KILL "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
    if [ "$shape" = "exec_shape" ]; then
        [ -s "$MARK" ] && no "exec shape should NOT run the trap (test is invalid)" \
                       || ok "exec shape loses the trap, as the defect described"
    else
        [ -s "$MARK" ] && ok "supervisor shape runs the trap on SIGTERM" \
                       || no "supervisor shape did not run the trap"
    fi
done

# --- health check must probe the proxy port, not just Flask ------------------
echo
echo "== health checks (GT-A7-03) =="
for f in install/install-docker.sh install/install-docker-multi-custom-ssl.sh; do
    HC=$(grep -A1 'healthcheck:' "$REPO_ROOT/$f" | grep 'test:')
    if echo "$HC" | grep -q '8765'; then
        ok "$f health check probes the proxy port"
    else
        no "$f health check does not probe 8765"
    fi
    echo "$HC" | grep -q 'check-setup' \
        && ok "$f health check still probes Flask" \
        || no "$f health check lost the Flask probe"
done

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
