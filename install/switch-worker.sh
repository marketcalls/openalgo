#!/bin/bash
# OpenAlgo: move a systemd service onto the web server launcher.
#
# OpenAlgo can run on two web servers: eventlet (the default) and gthread.
# A service written by install.sh or install-multi.sh starts eventlet
# directly. This script points it at install/openalgo-gunicorn.sh instead,
# which reads OPENALGO_WORKER_CLASS from that install's .env at every start.
# After that, switching between the two is one line in .env plus a restart.
#
# For each service it:
#   1. finds the service file and checks that an OpenAlgo installer wrote it
#      (a customised file is left alone, with an explanation);
#   2. saves a copy next to it as <file>.pre-launcher-<date>;
#   3. points ExecStart at the launcher and gives systemd enough time to let
#      a stop finish;
#   4. restarts OpenAlgo and checks that the service is running, the page
#      answers, the live update channel answers, and the web server is the
#      one .env asks for;
#   5. if any check fails, puts the saved copy back, restarts and checks again.
#
# This is the only thing that rewrites an OpenAlgo service file for this
# purpose. It runs only when you run it, or when the updater runs it because
# .env asks for gthread. It refuses to restart OpenAlgo during the trading
# day (09:00 to 23:30 IST) unless you add --force.
#
# Usage:
#   sudo bash install/switch-worker.sh [options]
#
#   --to gthread|eventlet   also set OPENALGO_WORKER_CLASS in that install's .env
#   --service NAME          the systemd service (default: found automatically)
#   --path DIR              the OpenAlgo folder, to pick a service by folder
#   --all                   every OpenAlgo service on this server, one at a time
#   --restore               put back the service file saved before the switch
#   --dry-run               show what would change, change nothing
#   --force                 allow a restart between 09:00 and 23:30 IST
#   --yes                   do not ask for confirmation
#   --check                 print nothing; exit 0 only when .env asks for gthread
#                           and the service does not use the launcher yet
#
# Exit status: 0 done (or nothing to do), 1 the switch failed and the previous
# service file is back and running, 2 OpenAlgo is not running and needs a
# person, 3 refused (trading hours, customised file, missing pieces), 4 usage.

set -u

LAUNCHER_REL="install/openalgo-gunicorn.sh"
RESOLVER_REL="install/lib/resolve_runtime.py"
MARKER="# OPENALGO_LAUNCHER=1"
STOP_WINDOW=90
MIN_STOP_WINDOW=60

# Internal overrides used by the test suite only.
SYSTEMD_DIR="${OPENALGO_SWITCH_TEST_SYSTEMD_DIR:-/etc/systemd/system}"
PROC_ROOT="${OPENALGO_SWITCH_TEST_PROC:-/proc}"
HEALTH_TIMEOUT="${OPENALGO_SWITCH_TEST_HEALTH_TIMEOUT:-120}"
HEALTH_INTERVAL="${OPENALGO_SWITCH_TEST_HEALTH_INTERVAL:-2}"
HEALTH_SETTLE="${OPENALGO_SWITCH_TEST_HEALTH_SETTLE:-5}"
CLOCK_HHMM="${OPENALGO_SWITCH_TEST_CLOCK_HHMM:-}"

TO=""
SERVICE=""
APP_PATH=""
ALL=0
RESTORE=0
DRY_RUN=0
FORCE=0
YES=0
CHECK=0
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

say() {
    printf '%s\n' "$*"
}

warn() {
    printf '%s\n' "$*" >&2
}

usage() {
    sed -n '/^# Usage:/,/^# Exit status/p' "${BASH_SOURCE[0]}" | sed -e 's/^# \{0,1\}//' -e '$d'
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --to)
            [ $# -ge 2 ] || { warn "--to needs gthread or eventlet."; exit 4; }
            TO="$2"; shift 2 ;;
        --service)
            [ $# -ge 2 ] || { warn "--service needs a name."; exit 4; }
            SERVICE="${2%.service}"; shift 2 ;;
        --path)
            [ $# -ge 2 ] || { warn "--path needs a folder."; exit 4; }
            APP_PATH="${2%/}"; shift 2 ;;
        --all) ALL=1; shift ;;
        --restore) RESTORE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --force) FORCE=1; shift ;;
        --yes|-y) YES=1; shift ;;
        --check) CHECK=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) warn "Unknown option: $1"; usage >&2; exit 4 ;;
    esac
done

case "$TO" in
    ""|gthread|eventlet) ;;
    *) warn "--to must be gthread or eventlet, not '$TO'."; exit 4 ;;
esac

# ---------------------------------------------------------------- unit parsing

# Print the value of the last KEY= line in a unit file.
unit_value() {
    local file="$1" key="$2"
    tr -d '\r' < "$file" | grep -E "^[[:space:]]*${key}=" | tail -n 1 | sed -E "s/^[[:space:]]*${key}=//"
}

# Print the ExecStart command with its continuation lines joined.
exec_start_joined() {
    tr -d '\r' < "$1" | awk '
        !inblock && /^[[:space:]]*ExecStart=/ { inblock = 1; sub(/^[[:space:]]*ExecStart=/, "") }
        inblock {
            line = $0
            more = (line ~ /\\[[:space:]]*$/)
            sub(/\\[[:space:]]*$/, "", line)
            printf "%s ", line
            if (!more) { inblock = 0; exit }
        }
    '
}

count_exec_start() {
    tr -d '\r' < "$1" | grep -cE '^[[:space:]]*ExecStart='
}

uses_launcher() {
    exec_start_joined "$1" | grep -q "$LAUNCHER_REL"
}

# Parse an installer-written gunicorn command. Sets OLD_VENV, OLD_BIND,
# OLD_LOG_LEVEL, OLD_TIMEOUT, OLD_GRACEFUL, OLD_TMP_DIR, OLD_WORKER and
# PARSE_PROBLEM (empty when the command is one this script knows).
parse_gunicorn_command() {
    local cmd="$1" args token next value
    OLD_VENV=""; OLD_BIND=""; OLD_LOG_LEVEL="info"; OLD_TIMEOUT="30"; OLD_GRACEFUL=""
    OLD_TMP_DIR=""; OLD_WORKER=""; PARSE_PROBLEM=""

    case "$cmd" in
        *gunicorn*app:app*) ;;
        *) PARSE_PROBLEM="its ExecStart does not start gunicorn with app:app"; return ;;
    esac
    OLD_VENV="$(printf '%s' "$cmd" | grep -oE "[^[:space:]'\"]+/bin/gunicorn" | head -n 1)"
    OLD_VENV="${OLD_VENV%/bin/gunicorn}"
    if [ -z "$OLD_VENV" ]; then
        PARSE_PROBLEM="the Python environment in its ExecStart could not be read"
        return
    fi
    args="${cmd#*/bin/gunicorn}"
    args="${args%%\'*}"
    args="${args%%\"*}"

    set -f
    # shellcheck disable=SC2086
    set -- $args
    set +f
    while [ $# -gt 0 ]; do
        token="$1"; shift
        value=""
        case "$token" in
            --*=*) value="${token#*=}"; token="${token%%=*}" ;;
        esac
        case "$token" in
            app:app) continue ;;
            --no-control-socket) continue ;;
            --worker-class|-k|--workers|-w|--bind|-b|--timeout|-t|--log-level|--graceful-timeout|--worker-tmp-dir|--threads)
                if [ -z "$value" ]; then
                    [ $# -gt 0 ] || { PARSE_PROBLEM="the option $token has no value"; return; }
                    value="$1"; shift
                fi
                ;;
            *) PARSE_PROBLEM="it passes the gunicorn option '$token', which this script does not know"; return ;;
        esac
        case "$token" in
            --worker-class|-k) OLD_WORKER="$value" ;;
            --workers|-w)
                if [ "$value" != "1" ]; then
                    PARSE_PROBLEM="it runs $value workers; OpenAlgo needs exactly one"
                    return
                fi ;;
            --bind|-b) OLD_BIND="$value" ;;
            --timeout|-t) OLD_TIMEOUT="$value" ;;
            --log-level) OLD_LOG_LEVEL="$value" ;;
            --graceful-timeout) OLD_GRACEFUL="$value" ;;
            --worker-tmp-dir) OLD_TMP_DIR="$value" ;;
            --threads) ;;
        esac
    done
    [ -n "$OLD_BIND" ] || PARSE_PROBLEM="its ExecStart has no --bind"
    case "$OLD_TIMEOUT$OLD_GRACEFUL" in
        *[!0-9]*) PARSE_PROBLEM="its timeouts are not plain seconds" ;;
    esac
    case "$OLD_LOG_LEVEL" in
        debug|info|warning|error|critical) ;;
        *) PARSE_PROBLEM="its log level '$OLD_LOG_LEVEL' is not one the launcher accepts" ;;
    esac
}

# Seconds in a systemd time span such as 300, 90s, 5min or 1min 30s. Prints
# nothing for infinity or a span it cannot read.
span_seconds() {
    local span="$1" total=0 part number unit
    case "$span" in ''|infinity) return ;; esac
    for part in $span; do
        number="$(printf '%s' "$part" | sed -E 's/^([0-9]+).*/\1/')"
        unit="$(printf '%s' "$part" | sed -E 's/^[0-9]+//')"
        case "$number" in ''|*[!0-9]*) return ;; esac
        case "$unit" in
            ''|s|sec|second|seconds) total=$((total + number)) ;;
            m|min|minute|minutes) total=$((total + number * 60)) ;;
            h|hr|hour|hours) total=$((total + number * 3600)) ;;
            ms|msec) ;;
            *) return ;;
        esac
    done
    printf '%s' "$total"
}

# True when the unit already allows a stop long enough for the drain.
stop_window_ok() {
    local value seconds
    value="$(unit_value "$1" TimeoutStopSec)"
    [ -n "$value" ] || value="$(unit_value "$1" TimeoutSec)"
    [ -n "$value" ] || return 1
    [ "$value" = "infinity" ] && return 0
    seconds="$(span_seconds "$value")"
    [ -n "$seconds" ] && [ "$seconds" -ge "$MIN_STOP_WINDOW" ]
}

# Write the launcher version of UNIT to OUT: only the ExecStart block changes,
# plus TimeoutStopSec when the stop window is too short or unset.
render_unit() {
    local unit="$1" out="$2" execline="$3" backup_name="$4" add_timeout="$5"
    tr -d '\r' < "$unit" | awk -v marker="$MARKER" -v execline="$execline" \
        -v backup="$backup_name" -v timeout="$add_timeout" '
        !done && !inblock && /^[[:space:]]*ExecStart=/ {
            inblock = 1
            print marker " started through install/openalgo-gunicorn.sh, which reads"
            print "# OPENALGO_WORKER_CLASS from .env. Previous file: " backup
            print "ExecStart=" execline
            if (timeout != "") print "TimeoutStopSec=" timeout
        }
        inblock {
            if ($0 !~ /\\[[:space:]]*$/) { inblock = 0; done = 1 }
            next
        }
        { print }
    ' > "$out"
}

# ---------------------------------------------------------------- health check

base_for_bind() {
    case "$1" in
        unix:*) printf 'unix %s' "${1#unix:}" ;;
        *)
            local host="${1%:*}" port="${1##*:}"
            case "$host" in ''|0.0.0.0|'[::]'|'*') host="127.0.0.1" ;; esac
            printf 'tcp http://%s:%s' "$host" "$port" ;;
    esac
}

http_get() {
    local bind="$1" path="$2" kind target
    read -r kind target <<< "$(base_for_bind "$bind")"
    if [ "$kind" = "unix" ]; then
        curl -fsS --max-time 5 --unix-socket "$target" "http://localhost$path"
    else
        curl -fsS --max-time 5 "$target$path"
    fi
}

running_worker_class() {
    local service="$1" pid
    pid="$(systemctl show -p MainPID --value "$service" 2>/dev/null)"
    case "$pid" in ''|0|*[!0-9]*) return 1 ;; esac
    tr '\0' ' ' < "$PROC_ROOT/$pid/cmdline" 2>/dev/null
}

# All four checks at once: running, page answers, Socket.IO answers, and the
# web server is EXPECTED. Retried until HEALTH_TIMEOUT, then checked again
# after HEALTH_SETTLE seconds so a crash loop is not mistaken for a start.
health_check() {
    local service="$1" bind="$2" expected="$3" waited=0 round
    for round in first settled; do
        while :; do
            HEALTH_PROBLEM=""
            if ! systemctl is-active --quiet "$service"; then
                HEALTH_PROBLEM="the service is not running"
            elif ! http_get "$bind" /auth/check-setup > /dev/null 2>&1; then
                HEALTH_PROBLEM="the OpenAlgo page does not answer"
            elif ! http_get "$bind" "/socket.io/?EIO=4&transport=polling" 2>/dev/null | grep -q '"sid"'; then
                HEALTH_PROBLEM="the live update channel does not answer"
            elif [ -n "$expected" ] && ! running_worker_class "$service" | grep -q -- "--worker-class $expected"; then
                HEALTH_PROBLEM="it is not running the $expected web server"
            fi
            [ -z "$HEALTH_PROBLEM" ] && break
            if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
                return 1
            fi
            sleep "$HEALTH_INTERVAL"
            waited=$((waited + HEALTH_INTERVAL))
        done
        [ "$round" = "first" ] && sleep "$HEALTH_SETTLE"
    done
    return 0
}

journal_tail() {
    journalctl -u "$1" -n 60 --no-pager 2>/dev/null | sed 's/^/    /'
}

# ---------------------------------------------------------------- guards

inside_trading_day() {
    local now
    now="${CLOCK_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"
    now="$((10#$now))"
    [ "$now" -ge 900 ] && [ "$now" -lt 2330 ]
}

refuse_during_trading_day() {
    if [ "$FORCE" -eq 1 ] || ! inside_trading_day; then
        return 0
    fi
    local now="${CLOCK_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"
    warn "It is ${now:0:2}:${now:2:2} IST, inside the trading day (09:00 to 23:30 IST, which"
    warn "includes the MCX evening session). This restarts OpenAlgo, which pauses live"
    warn "orders, strategies and market data for up to a minute. Run it again after"
    warn "23:30 IST, or add --force if you are sure nothing is trading."
    return 1
}

confirm() {
    [ "$YES" -eq 1 ] && return 0
    [ -t 0 ] || return 0
    local answer
    read -r -p "$1 [y/N] " answer
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------- discovery

# Print the unit files of OpenAlgo services, one per line.
find_openalgo_units() {
    local file workdir
    for file in "$SYSTEMD_DIR"/*.service; do
        [ -f "$file" ] || continue
        if ! exec_start_joined "$file" | grep -qE "gunicorn.*app:app|$LAUNCHER_REL"; then
            continue
        fi
        workdir="$(unit_value "$file" WorkingDirectory)"
        [ -n "$workdir" ] && [ -f "$workdir/app.py" ] || continue
        if [ -n "$APP_PATH" ] && [ "${workdir%/}" != "$APP_PATH" ]; then
            continue
        fi
        printf '%s\n' "$file"
    done
}

# Resolve the web server .env asks for, with the install's own Python.
requested_worker() {
    local workdir="$1" venv="$2" python="$2/bin/python"
    if [ -x "$python" ] && [ -f "$workdir/$RESOLVER_REL" ]; then
        as_root "$python" "$workdir/$RESOLVER_REL" --env-file "$workdir/.env" --print worker 2>/dev/null
        return
    fi
    printf 'eventlet'
}

venv_of_unit() {
    local cmd venv
    cmd="$(exec_start_joined "$1")"
    venv="$(printf '%s' "$cmd" | grep -oE -- "--venv [^[:space:]]+" | head -n 1)"
    if [ -n "$venv" ]; then
        printf '%s' "${venv#--venv }"
        return
    fi
    venv="$(printf '%s' "$cmd" | grep -oE "[^[:space:]'\"]+/bin/gunicorn" | head -n 1)"
    printf '%s' "${venv%/bin/gunicorn}"
}

bind_of_unit() {
    local cmd bind
    cmd="$(exec_start_joined "$1")"
    bind="$(printf '%s' "$cmd" | grep -oE -- "(--bind|-b)[ =][^[:space:]']+" | head -n 1)"
    bind="${bind#--bind}"; bind="${bind#-b}"
    printf '%s' "${bind# }" | sed 's/^=//'
}

# ---------------------------------------------------------------- actions

# Set OPENALGO_WORKER_CLASS in the install's .env.
set_env_worker() {
    local workdir="$1" venv="$2" value="$3"
    if [ "$DRY_RUN" -eq 1 ]; then
        say "Would set OPENALGO_WORKER_CLASS = '$value' in $workdir/.env"
        return 0
    fi
    if ! as_root "$venv/bin/python" "$workdir/$RESOLVER_REL" --env-file "$workdir/.env" --set "$value"; then
        warn "Could not update $workdir/.env. Nothing was changed."
        return 1
    fi
    say "Set OPENALGO_WORKER_CLASS = '$value' in $workdir/.env"
}

restart_and_check() {
    local service="$1" bind="$2" expected="$3"
    as_root systemctl daemon-reload
    as_root systemctl restart "$service"
    health_check "$service" "$bind" "$expected"
}

# Switch one service. Returns the exit status described at the top.
switch_one() {
    local unit="$1" service workdir user execs cmd execline backup tmpdir rendered add_timeout
    local expected dry_output previous=""
    service="$(basename "$unit" .service)"
    workdir="$(unit_value "$unit" WorkingDirectory)"
    workdir="${workdir%/}"
    user="$(unit_value "$unit" User)"
    [ -n "$user" ] || user="root"

    say ""
    say "Service $service ($workdir)"

    if [ ! -f "$workdir/$LAUNCHER_REL" ] || [ ! -f "$workdir/$RESOLVER_REL" ]; then
        warn "  This install does not have the launcher yet. Update OpenAlgo first, then run this again."
        return 3
    fi

    if [ "$CHECK" -eq 1 ]; then
        uses_launcher "$unit" && return 3
        [ "$(requested_worker "$workdir" "$(venv_of_unit "$unit")")" = "gthread" ] && return 0
        return 3
    fi

    if uses_launcher "$unit"; then
        local venv bind
        venv="$(venv_of_unit "$unit")"
        bind="$(bind_of_unit "$unit")"
        if [ -z "$TO" ]; then
            say "  Already uses the launcher. It runs the web server set in $workdir/.env"
            say "  ($(requested_worker "$workdir" "$venv")). To change it, run this again with --to gthread or --to eventlet."
            return 0
        fi
        refuse_during_trading_day || return 3
        if [ "$DRY_RUN" -eq 1 ]; then
            set_env_worker "$workdir" "$venv" "$TO"
            say "  Would restart $service on the $TO web server."
            return 0
        fi
        confirm "  Restart $service on the $TO web server now?" || { say "  Nothing changed."; return 3; }
        previous="$(requested_worker "$workdir" "$venv")"
        set_env_worker "$workdir" "$venv" "$TO" || return 3
        if restart_and_check "$service" "$bind" "$TO"; then
            say "  OpenAlgo is running on the $TO web server."
            return 0
        fi
        warn "  OpenAlgo did not come back on the $TO web server ($HEALTH_PROBLEM)."
        journal_tail "$service" >&2
        set_env_worker "$workdir" "$venv" "$previous" > /dev/null || true
        if restart_and_check "$service" "$bind" "$previous"; then
            warn "  It has been put back on the $previous web server and is running."
            return 1
        fi
        warn "  OpenAlgo is not running. Check: sudo journalctl -u $service -n 100"
        return 2
    fi

    execs="$(count_exec_start "$unit")"
    if [ "$execs" != "1" ]; then
        warn "  Left unchanged: the service file has $execs ExecStart lines, so it was customised."
        return 3
    fi
    if tr -d '\r' < "$unit" | grep -qE '^[[:space:]]*ExecReload='; then
        warn "  Left unchanged: the service file has an ExecReload line. A reload would start"
        warn "  a second OpenAlgo worker, so remove that line first, then run this again."
        return 3
    fi
    cmd="$(exec_start_joined "$unit")"
    parse_gunicorn_command "$cmd"
    if [ -n "$PARSE_PROBLEM" ]; then
        warn "  Left unchanged: $PARSE_PROBLEM, so it looks customised. OpenAlgo keeps its"
        warn "  current web server. To switch, change ExecStart by hand to call"
        warn "  $workdir/$LAUNCHER_REL (see docs/gthread/README.md)."
        return 3
    fi
    if [ ! -x "$OLD_VENV/bin/gunicorn" ]; then
        warn "  Left unchanged: gunicorn is not installed in $OLD_VENV."
        return 3
    fi

    execline="/bin/bash $workdir/$LAUNCHER_REL --venv $OLD_VENV --bind $OLD_BIND --proxy-mode subprocess --log-level $OLD_LOG_LEVEL --timeout $OLD_TIMEOUT"
    [ -n "$OLD_GRACEFUL" ] && execline="$execline --graceful-timeout $OLD_GRACEFUL"
    [ -n "$OLD_TMP_DIR" ] && execline="$execline --worker-tmp-dir $OLD_TMP_DIR"
    add_timeout=""
    stop_window_ok "$unit" || add_timeout="$STOP_WINDOW"
    backup="$unit.pre-launcher-$TIMESTAMP"

    tmpdir="$(mktemp -d /tmp/openalgo-switch-XXXXXX)" || { warn "  Could not create a temporary folder."; return 3; }
    rendered="$tmpdir/$service.service"
    render_unit "$unit" "$rendered" "$execline" "$(basename "$backup")" "$add_timeout"

    if [ "$(count_exec_start "$rendered")" != "1" ] || ! grep -qF "$LAUNCHER_REL" "$rendered"; then
        warn "  Could not prepare the new service file. Nothing was changed."
        rm -rf "$tmpdir"
        return 3
    fi

    if command -v systemd-analyze > /dev/null 2>&1; then
        mkdir -p "$tmpdir/original"
        tr -d '\r' < "$unit" > "$tmpdir/original/$service.service"
        if systemd-analyze verify "$tmpdir/original/$service.service" > /dev/null 2>&1 \
            && ! systemd-analyze verify "$rendered" > "$tmpdir/verify.txt" 2>&1; then
            warn "  The new service file did not pass systemd's check. Nothing was changed:"
            sed 's/^/    /' "$tmpdir/verify.txt" >&2
            rm -rf "$tmpdir"
            return 3
        fi
    fi

    # The launcher must work as the service's own user before anything changes.
    if ! dry_output="$(cd "$workdir" && sudo -u "$user" /bin/bash "$workdir/$LAUNCHER_REL" \
            --venv "$OLD_VENV" --bind "$OLD_BIND" --proxy-mode subprocess \
            --log-level "$OLD_LOG_LEVEL" --timeout "$OLD_TIMEOUT" --dry-run 2>&1)"; then
        warn "  The launcher could not run as $user. Nothing was changed:"
        printf '%s\n' "$dry_output" | sed 's/^/    /' >&2
        rm -rf "$tmpdir"
        return 3
    fi
    expected="$(printf '%s\n' "$dry_output" | awk '/^ARG --worker-class$/ { getline; print $2; exit }')"
    [ -n "$expected" ] || expected="eventlet"
    if [ -n "$TO" ]; then
        expected="$TO"
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        say "  Would save the current file as $backup and change it like this:"
        diff -u "$unit" "$rendered" | sed 's/^/    /'
        [ -n "$TO" ] && set_env_worker "$workdir" "$OLD_VENV" "$TO"
        say "  OpenAlgo would then start on the $expected web server."
        rm -rf "$tmpdir"
        return 0
    fi

    refuse_during_trading_day || { rm -rf "$tmpdir"; return 3; }
    confirm "  Switch $service to the launcher and restart it on the $expected web server now?" \
        || { say "  Nothing changed."; rm -rf "$tmpdir"; return 3; }

    if [ -n "$TO" ]; then
        previous="$(requested_worker "$workdir" "$OLD_VENV")"
        set_env_worker "$workdir" "$OLD_VENV" "$TO" || { rm -rf "$tmpdir"; return 3; }
    fi

    if ! as_root cp -p "$unit" "$backup"; then
        warn "  Could not save a copy of the service file. Nothing was changed."
        rm -rf "$tmpdir"
        return 3
    fi
    if ! as_root cp "$rendered" "$unit"; then
        as_root cp -p "$backup" "$unit"
        warn "  Could not write the new service file. The previous one is in place."
        rm -rf "$tmpdir"
        return 3
    fi
    rm -rf "$tmpdir"
    say "  Saved the previous service file as $backup"

    if restart_and_check "$service" "$OLD_BIND" "$expected"; then
        say "  OpenAlgo is running on the $expected web server."
        say "  To switch later: set OPENALGO_WORKER_CLASS in $workdir/.env and restart $service."
        return 0
    fi

    warn "  OpenAlgo did not start correctly through the launcher ($HEALTH_PROBLEM)."
    warn "  Last lines of its log:"
    journal_tail "$service" >&2
    as_root cp -p "$backup" "$unit"
    if [ -n "$TO" ] && [ -n "${previous:-}" ]; then
        set_env_worker "$workdir" "$OLD_VENV" "$previous" > /dev/null || true
    fi
    if restart_and_check "$service" "$OLD_BIND" "$OLD_WORKER"; then
        warn "  OpenAlgo has been put back on its previous service file and is running"
        warn "  on the ${OLD_WORKER:-previous} web server. The launcher is not in use."
        return 1
    fi
    warn "  OpenAlgo is not running on the previous service file either."
    journal_tail "$service" >&2
    warn "  To put the previous file back by hand:"
    warn "    sudo cp $backup $unit && sudo systemctl daemon-reload && sudo systemctl restart $service"
    return 2
}

restore_one() {
    local unit="$1" service backup workdir old_cmd bind expected env_worker env_differs
    service="$(basename "$unit" .service)"
    backup="$(ls -1 "$unit".pre-launcher-* 2>/dev/null | sort | tail -n 1)"
    say ""
    say "Service $service"
    if [ -z "$backup" ]; then
        warn "  No saved service file was found next to $unit."
        return 3
    fi
    old_cmd="$(exec_start_joined "$backup")"
    parse_gunicorn_command "$old_cmd"
    bind="$OLD_BIND"
    expected="$OLD_WORKER"
    workdir="$(unit_value "$backup" WorkingDirectory)"
    workdir="${workdir%/}"
    # .env goes back too. Left asking for gthread, the next update.sh would
    # move this service straight back onto the launcher the operator has just
    # backed out of. Only a .env that asks for something else is touched.
    env_worker="eventlet"
    [ "$OLD_WORKER" = "gthread" ] && env_worker="gthread"
    env_differs=0
    if [ -n "$workdir" ] && [ -f "$workdir/.env" ] \
        && [ "$(requested_worker "$workdir" "$OLD_VENV")" != "$env_worker" ]; then
        env_differs=1
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        say "  Would put back $backup and restart on the ${expected:-previous} web server."
        [ "$env_differs" -eq 1 ] && say "  Would set OPENALGO_WORKER_CLASS = '$env_worker' in $workdir/.env"
        return 0
    fi
    refuse_during_trading_day || return 3
    confirm "  Put back $backup and restart $service now?" || { say "  Nothing changed."; return 3; }
    as_root cp -p "$unit" "$unit.launcher-$TIMESTAMP"
    as_root cp -p "$backup" "$unit"
    if [ "$env_differs" -eq 1 ] && ! set_env_worker "$workdir" "$OLD_VENV" "$env_worker"; then
        warn "  Set OPENALGO_WORKER_CLASS = '$env_worker' in $workdir/.env by hand, or the"
        warn "  next update will switch $service back to the gthread web server."
    fi
    if restart_and_check "$service" "$bind" "$expected"; then
        say "  Put back $backup. OpenAlgo is running on the ${expected:-previous} web server."
        return 0
    fi
    warn "  OpenAlgo is not running after putting back $backup ($HEALTH_PROBLEM)."
    journal_tail "$service" >&2
    return 2
}

# ---------------------------------------------------------------- main

if [ -n "$SERVICE" ]; then
    UNITS="$SYSTEMD_DIR/$SERVICE.service"
    if [ ! -f "$UNITS" ]; then
        [ "$CHECK" -eq 1 ] && exit 3
        warn "No service file at $UNITS."
        exit 3
    fi
else
    UNITS="$(find_openalgo_units)"
fi

if [ -z "$UNITS" ]; then
    [ "$CHECK" -eq 1 ] && exit 3
    warn "No OpenAlgo service was found in $SYSTEMD_DIR."
    warn "Use --service NAME (for example --service openalgo) to name it."
    exit 3
fi

COUNT="$(printf '%s\n' "$UNITS" | grep -c .)"
if [ "$COUNT" -gt 1 ] && [ "$ALL" -eq 0 ]; then
    [ "$CHECK" -eq 1 ] && exit 3
    warn "More than one OpenAlgo service is installed on this server:"
    printf '%s\n' "$UNITS" | while read -r unit; do warn "  $(basename "$unit" .service)"; done
    warn "Name one with --service NAME, or use --all to switch them one at a time."
    exit 3
fi

if [ "$CHECK" -eq 1 ]; then
    switch_one "$(printf '%s\n' "$UNITS" | head -n 1)" > /dev/null 2>&1
    exit $?
fi

STATUS=0
GTHREAD_COUNT=0
# An array, not a loop reading a here-string: the loop body may ask for
# confirmation, and that has to read the terminal, not the list.
mapfile -t UNIT_LIST <<< "$UNITS"
for unit in "${UNIT_LIST[@]}"; do
    [ -n "$unit" ] || continue
    if [ "$RESTORE" -eq 1 ]; then
        restore_one "$unit"
    else
        switch_one "$unit"
    fi
    result=$?
    if [ "$result" -ne 0 ]; then
        STATUS=$result
        if [ "$ALL" -eq 1 ] && [ "$COUNT" -gt 1 ]; then
            warn ""
            warn "Stopped after $(basename "$unit" .service). The services after it were not touched."
        fi
        break
    fi
    workdir="$(unit_value "$unit" WorkingDirectory)"
    if [ "$(requested_worker "${workdir%/}" "$(venv_of_unit "$unit")")" = "gthread" ]; then
        GTHREAD_COUNT=$((GTHREAD_COUNT + 1))
    fi
done

if [ "$ALL" -eq 1 ] && [ "$COUNT" -gt 1 ] && [ "$RESTORE" -eq 0 ] && [ "$GTHREAD_COUNT" -gt 0 ]; then
    say ""
    say "$GTHREAD_COUNT OpenAlgo service(s) on this server use gthread, 64 request threads each"
    say "($((GTHREAD_COUNT * 64)) in total)."
fi
exit "$STATUS"
