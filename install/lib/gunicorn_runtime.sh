#!/bin/bash
# Resolves which Gunicorn worker OpenAlgo should run, and with how many threads.
#
# This is the single opt-in point for the gthread migration. The default is
# unchanged -- every existing install keeps running eventlet and sees nothing
# different. A user who wants to try gthread sets one variable:
#
#     OPENALGO_WORKER_CLASS = 'gthread'
#
# in .env (Docker), or in the environment before running the installer/updater
# (native systemd installs).
#
# WHY THE TWO SETTINGS ARE NOT INDEPENDENT
#
# Gunicorn's gthread worker defaults to --threads 1. OpenAlgo holds a request
# thread for the entire life of an SSE stream (python_strategy and mcp_http both
# stream indefinitely), and re-enters itself over HTTP for MCP, Telegram and
# WhatsApp. A single-threaded gthread worker therefore deadlocks as soon as one
# stream opens -- on boot, in practice.
#
# So selecting gthread MUST imply a thread count. Anyone who sets only the
# worker class gets a working default rather than a hung instance.
#
# Sourced by: start.sh (Docker runtime), install/install.sh and
# install/install-multi.sh (bake into the systemd unit at install time),
# install/update.sh (migrate an existing unit).

# Thread budget when gthread is selected without an explicit count.
# Derived in docs/plans/2026-08-01-eventlet-to-gthread-migration-plan.md section B1:
# Socket.IO clients x2, plus both infinite SSE endpoints, plus an internal
# loopback reserve, plus requests parked in broker rate limiters, plus ordinary
# HTTP concurrency and a failure reserve.
OPENALGO_DEFAULT_GTHREAD_THREADS=64

# Below this, the SSE and loopback reserve alone can deadlock the worker. A
# lower value is treated as a mistake and raised, loudly, rather than honoured.
OPENALGO_MIN_GTHREAD_THREADS=16

# Above this the thread stacks alone are a meaningful memory cost. Warn, but
# honour it -- this is a tuning choice, not a footgun.
OPENALGO_WARN_GTHREAD_THREADS=512

# Read a single key from a .env file, tolerating the quoting styles OpenAlgo's
# .env uses:  KEY = 'value'  |  KEY='value'  |  KEY=value
#
# Prints nothing when the file or key is absent, so callers can use the result
# directly as a fallback.
openalgo_env_file_value() {
    local file="$1" key="$2"
    [ -f "$file" ] && [ -r "$file" ] || return 0
    grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" 2>/dev/null \
        | head -n1 \
        | sed -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//; s/^['\"]//; s/['\"][[:space:]]*$//; s/[[:space:]]*$//"
}

# resolve_gunicorn_runtime [env_file]
#
# Precedence: the process environment wins over the .env file, matching
# python-dotenv's default (load_dotenv does not override an existing variable),
# so Railway-style `-e` injection keeps working.
#
# Sets, for the caller to use:
#   GUNICORN_WORKER_CLASS  - eventlet | gthread
#   GUNICORN_THREADS       - thread count, empty under eventlet
#   GUNICORN_WORKER_ARGS   - assembled arguments, e.g. "--worker-class gthread --threads 64"
resolve_gunicorn_runtime() {
    local env_file="${1:-}"
    local requested threads

    requested="${OPENALGO_WORKER_CLASS:-}"
    if [ -z "$requested" ] && [ -n "$env_file" ]; then
        requested="$(openalgo_env_file_value "$env_file" OPENALGO_WORKER_CLASS)"
    fi
    requested="$(printf '%s' "${requested:-eventlet}" | tr '[:upper:]' '[:lower:]')"

    threads="${OPENALGO_GUNICORN_THREADS:-}"
    if [ -z "$threads" ] && [ -n "$env_file" ]; then
        threads="$(openalgo_env_file_value "$env_file" OPENALGO_GUNICORN_THREADS)"
    fi

    case "$requested" in
        eventlet)
            GUNICORN_WORKER_CLASS="eventlet"
            ;;
        gthread)
            GUNICORN_WORKER_CLASS="gthread"
            ;;
        *)
            # An unrecognised value must never stop a user's server from
            # starting. Fall back to the shipped default and say so.
            echo "[OpenAlgo] WARNING: unknown OPENALGO_WORKER_CLASS '${requested}'." >&2
            echo "[OpenAlgo]          Supported: eventlet (default), gthread. Using eventlet." >&2
            GUNICORN_WORKER_CLASS="eventlet"
            ;;
    esac

    if [ "$GUNICORN_WORKER_CLASS" != "gthread" ]; then
        # The eventlet worker has no thread pool; --threads would be misleading.
        GUNICORN_THREADS=""
        GUNICORN_WORKER_ARGS="--worker-class ${GUNICORN_WORKER_CLASS}"
        return 0
    fi

    if [ -z "$threads" ]; then
        threads="$OPENALGO_DEFAULT_GTHREAD_THREADS"
    elif ! printf '%s' "$threads" | grep -qE '^[0-9]+$'; then
        echo "[OpenAlgo] WARNING: OPENALGO_GUNICORN_THREADS='${threads}' is not a number." >&2
        echo "[OpenAlgo]          Using ${OPENALGO_DEFAULT_GTHREAD_THREADS}." >&2
        threads="$OPENALGO_DEFAULT_GTHREAD_THREADS"
    fi

    if [ "$threads" -lt "$OPENALGO_MIN_GTHREAD_THREADS" ]; then
        echo "[OpenAlgo] WARNING: OPENALGO_GUNICORN_THREADS=${threads} is too low." >&2
        echo "[OpenAlgo]          Live strategy and MCP streams each hold a thread for" >&2
        echo "[OpenAlgo]          their whole life, so this can deadlock. Raising to" >&2
        echo "[OpenAlgo]          ${OPENALGO_MIN_GTHREAD_THREADS}." >&2
        threads="$OPENALGO_MIN_GTHREAD_THREADS"
    elif [ "$threads" -gt "$OPENALGO_WARN_GTHREAD_THREADS" ]; then
        echo "[OpenAlgo] WARNING: OPENALGO_GUNICORN_THREADS=${threads} is very high;" >&2
        echo "[OpenAlgo]          each thread costs stack memory. Proceeding." >&2
    fi

    GUNICORN_THREADS="$threads"
    GUNICORN_WORKER_ARGS="--worker-class gthread --threads ${threads}"
    return 0
}
