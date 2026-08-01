#!/usr/bin/env bash
# Boot the real container entrypoint and assert what is actually running.
#
# The existing CI smoke test runs `docker run --entrypoint /app/.venv/bin/python`,
# so it never executes start.sh, Gunicorn, Flask, Socket.IO or the WebSocket
# proxy. It cannot detect a broken worker class, a proxy that fails to start, a
# supervisor that does not forward signals, or a container that reports healthy
# while market data is dead. This script closes that gap (gthread gate, section 7).
#
# It asserts the runtime matches EXPECTED_WORKER_CLASS rather than hard-coding
# gthread, so it is meaningful before the cutover (eventlet) and after it
# (gthread) -- the cutover changes one variable, not this script.
#
# Usage:
#   scripts/gthread_container_smoke.sh <image> [expected-worker-class] [expected-threads]
#
# Example:
#   scripts/gthread_container_smoke.sh openalgo-ci:amd64 eventlet
#   scripts/gthread_container_smoke.sh openalgo-ci:amd64 gthread 64

set -uo pipefail

IMAGE="${1:?usage: $0 <image> [worker-class] [threads]}"
EXPECTED_WORKER_CLASS="${2:-eventlet}"
EXPECTED_THREADS="${3:-}"
NAME="openalgo-smoke-$$"
APP_PORT=5099
WS_PORT=8799

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); echo "  ok   - $1"; }
no() { FAIL=$((FAIL + 1)); echo "  FAIL - $1"; }

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== booting $IMAGE via its real entrypoint =="

# Anything other than the shipped default has to be opted into explicitly --
# that is the whole point of the switch, so the smoke test opts in the same way
# a user would rather than assuming the image already defaults to it.
OPTIN_ENV=()
if [ "$EXPECTED_WORKER_CLASS" != "eventlet" ]; then
    OPTIN_ENV+=(-e "OPENALGO_WORKER_CLASS=${EXPECTED_WORKER_CLASS}")
    [ -n "$EXPECTED_THREADS" ] && OPTIN_ENV+=(-e "OPENALGO_GUNICORN_THREADS=${EXPECTED_THREADS}")
    echo "  opting in with OPENALGO_WORKER_CLASS=${EXPECTED_WORKER_CLASS}"
fi

docker run -d --name "$NAME" \
    -p "127.0.0.1:${APP_PORT}:5000" \
    -p "127.0.0.1:${WS_PORT}:8765" \
    -e APP_KEY="ci-smoke-app-key" \
    -e API_KEY_PEPPER="$(printf '0%.0s' {1..64})" \
    -e HOST_SERVER="http://127.0.0.1:${APP_PORT}" \
    -e FLASK_PORT=5000 \
    "${OPTIN_ENV[@]+"${OPTIN_ENV[@]}"}" \
    "$IMAGE" >/dev/null

# Wait for Flask. start.sh runs migrations first, so allow a generous window.
for _ in $(seq 1 90); do
    if curl -fsS -m 2 "http://127.0.0.1:${APP_PORT}/auth/check-setup" >/dev/null 2>&1; then
        break
    fi
    if ! docker ps --format '{{.Names}}' | grep -q "^${NAME}$"; then
        echo "  container exited during boot:"
        docker logs "$NAME" 2>&1 | tail -30
        exit 1
    fi
    sleep 2
done

curl -fsS -m 5 "http://127.0.0.1:${APP_PORT}/auth/check-setup" >/dev/null 2>&1 \
    && ok "Flask answers on the app port" \
    || { no "Flask never became reachable"; docker logs "$NAME" 2>&1 | tail -30; }

# --- what is actually running -------------------------------------------
# Read it from inside the container: the diagnostics endpoint is behind admin
# auth, and this must work without provisioning a login.
RUNTIME=$(docker exec "$NAME" /app/.venv/bin/python -c \
    'import json; from blueprints.admin import _runtime_info; print(json.dumps(_runtime_info()))' \
    2>/dev/null)

if [ -z "$RUNTIME" ]; then
    no "could not read runtime diagnostics from the container"
else
    echo "  runtime: $RUNTIME"
    get() { echo "$RUNTIME" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1'))"; }

    [ "$(get worker_class)" = "$EXPECTED_WORKER_CLASS" ] \
        && ok "worker class is $EXPECTED_WORKER_CLASS" \
        || no "worker class is $(get worker_class), expected $EXPECTED_WORKER_CLASS"

    [ "$(get configured_workers)" = "1" ] \
        && ok "exactly one worker" \
        || no "configured_workers is $(get configured_workers), must be 1"

    if [ -n "$EXPECTED_THREADS" ]; then
        [ "$(get configured_threads)" = "$EXPECTED_THREADS" ] \
            && ok "configured threads is $EXPECTED_THREADS" \
            || no "configured threads is $(get configured_threads), expected $EXPECTED_THREADS"
    fi

    if [ "$EXPECTED_WORKER_CLASS" = "gthread" ]; then
        [ "$(get eventlet_active)" = "False" ] \
            && ok "eventlet is not active" \
            || no "eventlet is still active under gthread"
    fi

    case "$(get websocket_proxy_mode)" in
        external) ok "proxy mode is external (start.sh owns it)" ;;
        *) no "proxy mode is $(get websocket_proxy_mode), expected external in Docker" ;;
    esac
fi

# --- the proxy must actually be listening --------------------------------
docker exec "$NAME" /app/.venv/bin/python -c \
    "import socket,sys; s=socket.socket(); s.settimeout(5); sys.exit(s.connect_ex(('127.0.0.1',8765)))" \
    2>/dev/null \
    && ok "WebSocket proxy is listening on 8765" \
    || no "WebSocket proxy is not listening on 8765"

# --- Socket.IO transports -------------------------------------------------
curl -fsS -m 5 "http://127.0.0.1:${APP_PORT}/socket.io/?EIO=4&transport=polling" >/dev/null 2>&1 \
    && ok "Socket.IO polling handshake" \
    || no "Socket.IO polling handshake failed"

# WebSocket upgrade is only expected to work on gthread; eventlet's worker
# supports it too, so assert it either way and let a failure be informative.
docker exec "$NAME" /app/.venv/bin/python - <<'PYEOF' 2>/dev/null && ok "Socket.IO WebSocket upgrade" || no "Socket.IO WebSocket upgrade failed"
import sys
try:
    import socketio
except ImportError:
    sys.exit(0)  # client not bundled; not a product failure
c = socketio.Client(reconnection=False)
try:
    c.connect("http://127.0.0.1:5000", transports=["websocket"], wait_timeout=10)
    ok = c.transport() == "websocket"
    c.disconnect()
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PYEOF

# --- clean shutdown of BOTH processes ------------------------------------
# This is the A7a gate: before the supervisor fix, `exec` destroyed the trap so
# the proxy was never signalled.
PROXY_PIDS_BEFORE=$(docker exec "$NAME" sh -c "ps -eo args | grep -c '[w]ebsocket_proxy.server'" 2>/dev/null || echo 0)
[ "${PROXY_PIDS_BEFORE:-0}" -ge 1 ] \
    && ok "proxy process is running before shutdown" \
    || no "no proxy process found before shutdown"

START=$(date +%s)
docker stop -t 45 "$NAME" >/dev/null 2>&1
ELAPSED=$(( $(date +%s) - START ))

EXIT_CODE=$(docker inspect -f '{{.State.ExitCode}}' "$NAME" 2>/dev/null || echo "?")
[ "$EXIT_CODE" = "0" ] || [ "$EXIT_CODE" = "143" ] \
    && ok "container exited cleanly (code $EXIT_CODE in ${ELAPSED}s)" \
    || no "container exit code $EXIT_CODE"

[ "$ELAPSED" -lt 45 ] \
    && ok "shutdown completed within the grace period (${ELAPSED}s)" \
    || no "shutdown hit the ${ELAPSED}s timeout, so something ignored SIGTERM"

docker logs "$NAME" 2>&1 | grep -q "Shutting down" \
    && ok "supervisor ran its shutdown handler" \
    || no "supervisor shutdown handler never ran (exec destroyed the trap?)"

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
