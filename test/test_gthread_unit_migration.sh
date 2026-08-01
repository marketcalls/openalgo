#!/usr/bin/env bash
# Tests for migrate_systemd_worker_class / restore_systemd_unit in
# install/update.sh (gthread migration, gate C2 / GT-C2-01).
#
# The real functions are extracted from update.sh and sourced, so this
# exercises the shipped code rather than a copy of it. sudo and systemctl are
# stubbed, and UNIT_PATH_OVERRIDE points the migration at a temp unit, so the
# test needs neither root nor systemd.
#
# update.sh targets Linux/systemd and uses GNU sed. On a machine with BSD sed
# (macOS) the rewrite cases are skipped rather than reported as failures.
#
# Run: bash test/test_gthread_unit_migration.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE_SH="$REPO_ROOT/install/update.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS + 1)); echo "  ok   - $1"; }
no()   { FAIL=$((FAIL + 1)); echo "  FAIL - $1"; }
skip() { SKIP=$((SKIP + 1)); echo "  skip - $1"; }

# GNU sed is required for the in-place -E rewrites update.sh performs.
# On macOS, `brew install gnu-sed` provides it as gsed; shim it onto PATH so
# the rewrite cases run locally instead of being skipped.
if sed --version >/dev/null 2>&1; then
    HAVE_GNU_SED=1
elif command -v gsed >/dev/null 2>&1; then
    mkdir -p "$WORK/bin"
    ln -sf "$(command -v gsed)" "$WORK/bin/sed"
    PATH="$WORK/bin:$PATH"
    export PATH
    HAVE_GNU_SED=1
else
    HAVE_GNU_SED=0
fi

# --- stubs -----------------------------------------------------------------
export RED="" GREEN="" YELLOW="" BLUE="" NC=""
log_message() { :; }
check_status() { :; }
DAEMON_RELOADS=0
sudo() { "$@"; }
systemctl() {
    [ "${1:-}" = "daemon-reload" ] && DAEMON_RELOADS=$((DAEMON_RELOADS + 1))
    return 0
}
export -f log_message check_status sudo systemctl 2>/dev/null || true

# --- extract the functions under test --------------------------------------
FUNCS="$WORK/funcs.sh"
sed -n '/^TARGET_WORKER_CLASS=/,/^# Start logging/p' "$UPDATE_SH" | sed '$d' > "$FUNCS"
grep -q "migrate_systemd_worker_class()" "$FUNCS" || {
    echo "FAIL - could not extract migration functions from $UPDATE_SH"; exit 1; }
grep -q "UNIT_PATH_OVERRIDE" "$FUNCS" || {
    echo "FAIL - migrate_systemd_worker_class is not test-injectable"; exit 1; }

write_unit() {
    cat > "$1" <<'UNIT'
[Service]
ExecStart=/bin/bash -c 'source /opt/venv/bin/activate && /opt/venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind unix:/tmp/openalgo.sock \
    app:app'
UNIT
}

# call_migrate <target-class> <threads> <unit-path>  -> echoes rc
call_migrate() {
    (
        SERVICE_NAME="openalgo"
        UNIT_PATH_OVERRIDE="$3"
        # shellcheck disable=SC1090
        source "$FUNCS"
        TARGET_WORKER_CLASS="$1"
        TARGET_GUNICORN_THREADS="$2"
        migrate_systemd_worker_class >/dev/null 2>&1
        echo $?
    )
}

UNIT="$WORK/openalgo.service"

echo "== migrate_systemd_worker_class =="

# 1. Missing unit is a no-op that succeeds.
[ "$(call_migrate gthread "" "$WORK/absent.service")" = "0" ] \
    && ok "missing unit is a no-op that succeeds" \
    || no "missing unit should return 0"

# 2. Unit with no --worker-class is left untouched.
printf '[Service]\nExecStart=/bin/true\n' > "$UNIT"
BEFORE="$(cat "$UNIT")"
rc="$(call_migrate gthread "" "$UNIT")"
[ "$rc" = "0" ] && [ "$(cat "$UNIT")" = "$BEFORE" ] \
    && ok "unit without --worker-class is untouched" \
    || no "unit without --worker-class was modified"

# 3. Already-correct worker class is a no-op (the default state until cutover).
write_unit "$UNIT"
BEFORE="$(cat "$UNIT")"
rc="$(call_migrate eventlet "" "$UNIT")"
[ "$rc" = "0" ] && [ "$(cat "$UNIT")" = "$BEFORE" ] \
    && ok "matching worker class is a no-op" \
    || no "matching worker class should not rewrite"

if [ "$HAVE_GNU_SED" -eq 0 ]; then
    skip "rewrite cases (GNU sed required; update.sh targets Linux/systemd)"
    skip "threads insert/update cases"
    skip "backup and restore round-trip"
else
    # 4. eventlet -> gthread rewrite, with no eventlet left behind.
    write_unit "$UNIT"
    rc="$(call_migrate gthread "" "$UNIT")"
    [ "$rc" = "0" ] && grep -qE -- "--worker-class[= ]+gthread" "$UNIT" \
        && ok "worker class rewritten eventlet -> gthread" \
        || no "worker class not rewritten"
    grep -q "eventlet" "$UNIT" \
        && no "eventlet reference survived the rewrite" \
        || ok "no eventlet reference remains"

    # 5. --threads inserted when absent, updated when present, never duplicated.
    write_unit "$UNIT"
    call_migrate gthread 64 "$UNIT" >/dev/null
    grep -qE -- "--threads[= ]+64" "$UNIT" \
        && ok "--threads inserted when absent" || no "--threads not inserted"
    call_migrate gthread 32 "$UNIT" >/dev/null
    grep -qE -- "--threads[= ]+32" "$UNIT" \
        && ok "--threads updated when present" || no "--threads not updated"
    [ "$(grep -cE -- '--threads' "$UNIT")" -eq 1 ] \
        && ok "--threads never duplicated" || no "--threads duplicated"

    # 6. A backup is written and restore round-trips the original exactly.
    write_unit "$UNIT"
    ORIGINAL="$(cat "$UNIT")"
    (
        SERVICE_NAME="openalgo"; UNIT_PATH_OVERRIDE="$UNIT"
        # shellcheck disable=SC1090
        source "$FUNCS"
        TARGET_WORKER_CLASS="gthread"; TARGET_GUNICORN_THREADS=""
        migrate_systemd_worker_class >/dev/null 2>&1
        [ -n "$UNIT_BACKUP_PATH" ] && [ -f "$UNIT_BACKUP_PATH" ] || exit 1
        restore_systemd_unit "$UNIT" >/dev/null 2>&1
    ) && ok "backup written before rewrite" || no "no backup written"
    [ "$(cat "$UNIT")" = "$ORIGINAL" ] \
        && ok "restore round-trips the original unit exactly" \
        || no "restore did not round-trip"
fi

echo
echo "passed: $PASS  failed: $FAIL  skipped: $SKIP"
[ "$FAIL" -eq 0 ]
