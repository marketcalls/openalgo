#!/bin/bash
# OpenAlgo gunicorn launcher.
#
# Starts OpenAlgo under gunicorn on the web server chosen in .env with
# OPENALGO_WORKER_CLASS: eventlet (the default) or gthread. The setting is read
# at every start, so once a service uses this launcher, switching between the
# two is one line in .env plus a restart.
#
# Service files written by install/switch-worker.sh point at this exact path
# and keep pointing at it after every update. Never move or rename this file:
# every switched server would fail to start on its next restart.
#
# Usage:
#   /bin/bash install/openalgo-gunicorn.sh --venv DIR --bind ADDR [options]
#
#   --venv DIR              Python environment that holds gunicorn (required)
#   --bind ADDR             unix:/path/openalgo.sock or HOST:PORT (required)
#   --app-dir DIR           OpenAlgo folder (default: the folder above install/)
#   --env-file FILE         settings file (default: APP_DIR/.env)
#   --proxy-mode MODE       subprocess (systemd, the default) or external (Docker)
#   --log-level LEVEL       debug, info (default), warning, error or critical
#   --timeout SECONDS       request timeout (default 300)
#   --graceful-timeout S    seconds a stop may take to finish open requests (default 30)
#   --worker-tmp-dir DIR    where gunicorn keeps its heartbeat file
#   --dry-run               print the command and environment, then exit
#
# The gthread thread count is fixed here, not a setting. One worker only:
# Socket.IO state lives in that one process.

set -u

LAUNCHER_VERSION=1
GTHREAD_THREADS=64
# Longer than nginx's 60 second upstream keepalive, so nginx never reuses a
# connection gunicorn is closing (a webhook POST would otherwise fail).
KEEP_ALIVE=75

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
VENV=""
BIND=""
ENV_FILE=""
PROXY_MODE="subprocess"
LOG_LEVEL="info"
TIMEOUT=300
GRACEFUL=30
WORKER_TMP_DIR=""
DRY_RUN=0

say() {
    printf '[OpenAlgo] %s\n' "$*" >&2
}

fail() {
    say "$*"
    exit 2
}

usage() {
    cat <<'USAGE'
Usage: /bin/bash install/openalgo-gunicorn.sh --venv DIR --bind ADDR [options]

  --venv DIR              Python environment that holds gunicorn (required)
  --bind ADDR             unix:/path/openalgo.sock or HOST:PORT (required)
  --app-dir DIR           OpenAlgo folder (default: the folder above install/)
  --env-file FILE         settings file (default: APP_DIR/.env)
  --proxy-mode MODE       subprocess (systemd, the default) or external (Docker)
  --log-level LEVEL       debug, info (default), warning, error or critical
  --timeout SECONDS       request timeout (default 300)
  --graceful-timeout S    seconds a stop may take to finish open requests (default 30)
  --worker-tmp-dir DIR    where gunicorn keeps its heartbeat file
  --dry-run               print the command and environment, then exit

The web server comes from OPENALGO_WORKER_CLASS in .env: eventlet (default) or gthread.
USAGE
}

need_value() {
    if [ $# -lt 2 ] || [ -z "$2" ]; then
        fail "The option $1 needs a value."
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --venv) need_value "$@"; VENV="$2"; shift 2 ;;
        --bind) need_value "$@"; BIND="$2"; shift 2 ;;
        --app-dir) need_value "$@"; APP_DIR="$2"; shift 2 ;;
        --env-file) need_value "$@"; ENV_FILE="$2"; shift 2 ;;
        --proxy-mode) need_value "$@"; PROXY_MODE="$2"; shift 2 ;;
        --log-level) need_value "$@"; LOG_LEVEL="$2"; shift 2 ;;
        --timeout) need_value "$@"; TIMEOUT="$2"; shift 2 ;;
        --graceful-timeout) need_value "$@"; GRACEFUL="$2"; shift 2 ;;
        --worker-tmp-dir) need_value "$@"; WORKER_TMP_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done

[ -n "$VENV" ] || fail "Missing --venv: the Python environment that holds gunicorn."
[ -n "$BIND" ] || fail "Missing --bind: the socket or address OpenAlgo listens on."
case "$PROXY_MODE" in
    subprocess|external) ;;
    *) fail "--proxy-mode must be subprocess or external, not '$PROXY_MODE'." ;;
esac
case "$LOG_LEVEL" in
    debug|info|warning|error|critical) ;;
    *) fail "--log-level must be debug, info, warning, error or critical." ;;
esac
case "$TIMEOUT" in ''|*[!0-9]*) fail "--timeout must be a whole number of seconds." ;; esac
case "$GRACEFUL" in ''|*[!0-9]*) fail "--graceful-timeout must be a whole number of seconds." ;; esac

cd "$APP_DIR" 2>/dev/null || fail "The OpenAlgo folder $APP_DIR does not exist."
APP_DIR="$(pwd)"
[ -n "$ENV_FILE" ] || ENV_FILE="$APP_DIR/.env"
[ -f "$APP_DIR/app.py" ] || fail "$APP_DIR does not look like an OpenAlgo folder (app.py is missing)."
[ -x "$VENV/bin/gunicorn" ] || fail "gunicorn is not installed in $VENV. Run the updater to reinstall the dependencies."

# Read OPENALGO_WORKER_CLASS without Python, for when the helper cannot run.
# Follows python-dotenv's rules closely: the last assignment wins, and
# export, quotes, a trailing comment and a carriage return are removed.
fallback_worker() {
    local line="" value=""
    if [ -f "$ENV_FILE" ]; then
        line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?OPENALGO_WORKER_CLASS[[:space:]]*=' "$ENV_FILE" 2>/dev/null | tail -n 1)"
    fi
    if [ -n "$line" ]; then
        value="${line#*=}"
    else
        value="${OPENALGO_WORKER_CLASS:-}"
    fi
    value="$(printf '%s' "$value" | tr -d '\r' | sed -e 's/[[:space:]]#.*$//' | tr -d "'\" \t" | tr '[:upper:]' '[:lower:]')"
    REQUESTED="${value:-default}"
    case "$REQUESTED" in *[!a-z0-9_.-]*) REQUESTED="unrecognised" ;; esac
    if [ "$value" = "gthread" ]; then
        WORKER="gthread"
    else
        WORKER="eventlet"
    fi
}

WORKER=""
REQUESTED="default"
GUNICORN_VERSION="0"
RESOLVER="$APP_DIR/install/lib/resolve_runtime.py"
if [ -x "$VENV/bin/python" ] && [ -f "$RESOLVER" ]; then
    RESOLVED="$("$VENV/bin/python" "$RESOLVER" --env-file "$ENV_FILE" --shell --threads "$GTHREAD_THREADS")"
    while IFS='=' read -r key value; do
        case "$value" in ''|*[!a-z0-9_.-]*) continue ;; esac
        case "$key" in
            WORKER_CLASS) WORKER="$value" ;;
            REQUESTED) REQUESTED="$value" ;;
            GUNICORN_VERSION) GUNICORN_VERSION="$value" ;;
        esac
    done <<< "$RESOLVED"
fi
if [ "$WORKER" != "eventlet" ] && [ "$WORKER" != "gthread" ]; then
    fallback_worker
fi

# True when gunicorn is at least MAJOR.MINOR.
gunicorn_at_least() {
    local major minor rest
    major="${GUNICORN_VERSION%%.*}"
    rest="${GUNICORN_VERSION#*.}"
    minor="${rest%%.*}"
    case "$major" in ''|*[!0-9]*) return 1 ;; esac
    case "$minor" in ''|*[!0-9]*) minor=0 ;; esac
    [ "$major" -gt "$1" ] || { [ "$major" -eq "$1" ] && [ "$minor" -ge "$2" ]; }
}

# Settings gunicorn would otherwise pick up from outside this command line.
# GUNICORN_CMD_ARGS could add --preload or --max-requests, which would start
# the app's threads in the wrong process or recycle the only worker.
if [ -n "${GUNICORN_CMD_ARGS:-}" ]; then
    say "Ignoring GUNICORN_CMD_ARGS: this launcher sets every gunicorn option itself."
fi
unset GUNICORN_CMD_ARGS

# The same environment the old service file got from 'source bin/activate'.
export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"
unset PYTHONHOME

# Internal values for the app and its diagnostics page. Not settings.
export WEBSOCKET_PROXY_MODE="$PROXY_MODE"
export OPENALGO_LAUNCHER_VERSION="$LAUNCHER_VERSION"
export OPENALGO_REQUESTED_WORKER_CLASS="$REQUESTED"
export OPENALGO_EFFECTIVE_WORKER_CLASS="$WORKER"
if [ "$WORKER" = "gthread" ]; then
    export OPENALGO_EFFECTIVE_THREADS="$GTHREAD_THREADS"
else
    unset OPENALGO_EFFECTIVE_THREADS
fi

# -c names the hooks file, so a stray gunicorn.conf.py in the working folder is
# never loaded. Never add --preload, --max-requests or --reload.
ARGS=(-c "$APP_DIR/install/lib/gunicorn_hooks.py" --worker-class "$WORKER")
if [ "$WORKER" = "gthread" ]; then
    ARGS+=(--threads "$GTHREAD_THREADS")
fi
ARGS+=(--workers 1 --bind "$BIND" --timeout "$TIMEOUT" --graceful-timeout "$GRACEFUL")
ARGS+=(--keep-alive "$KEEP_ALIVE")
# The control socket (gunicorn 25.1 and later) can add workers at runtime,
# which would split Socket.IO state across processes.
if gunicorn_at_least 25 1; then
    ARGS+=(--no-control-socket)
fi
ARGS+=(--log-level "$LOG_LEVEL")
if [ -n "$WORKER_TMP_DIR" ]; then
    ARGS+=(--worker-tmp-dir "$WORKER_TMP_DIR")
fi
ARGS+=(app:app)

if [ "$WORKER" = "gthread" ]; then
    say "Starting the gthread web server with $GTHREAD_THREADS request threads. To go back, set OPENALGO_WORKER_CLASS = 'eventlet' in .env and restart OpenAlgo."
else
    say "Starting the eventlet web server."
fi

if [ "$DRY_RUN" -eq 1 ]; then
    printf 'EXEC %s\n' "$VENV/bin/gunicorn"
    for arg in "${ARGS[@]}"; do
        printf 'ARG %s\n' "$arg"
    done
    for name in WEBSOCKET_PROXY_MODE OPENALGO_LAUNCHER_VERSION OPENALGO_REQUESTED_WORKER_CLASS \
        OPENALGO_EFFECTIVE_WORKER_CLASS OPENALGO_EFFECTIVE_THREADS VIRTUAL_ENV; do
        if [ -n "${!name+x}" ]; then
            printf 'ENV %s=%s\n' "$name" "${!name}"
        fi
    done
    exit 0
fi

exec "$VENV/bin/gunicorn" "${ARGS[@]}"
