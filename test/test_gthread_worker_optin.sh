#!/bin/bash
# Tests for install/lib/gunicorn_runtime.sh -- the opt-in switch (PR-11a).
#
# The property that matters most here is the DEFAULT. ~290,000 installs pull
# this code without asking for a runtime change; if resolution ever returns
# anything but eventlet when nothing is set, every one of them switches worker
# on their next restart. That is the first thing checked and the last.
#
# The second property is that opting in cannot produce a hung server: gthread
# with Gunicorn's default of 1 thread deadlocks on the first SSE stream.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$REPO/install/lib/gunicorn_runtime.sh"

PASS=0; FAIL=0
ok() { echo "  PASS - $1"; PASS=$((PASS+1)); }
no() { echo "  FAIL - $1"; FAIL=$((FAIL+1)); }

[ -f "$LIB" ] || { echo "FAIL - $LIB does not exist"; exit 1; }
# shellcheck source=/dev/null
. "$LIB"

# Resolve in a clean environment so a stray exported value in the developer's
# shell cannot make a failing case look like it passes.
resolve() {
    local env_file="${1:-}"
    GUNICORN_WORKER_CLASS=""; GUNICORN_THREADS=""; GUNICORN_WORKER_ARGS=""
    resolve_gunicorn_runtime "$env_file" 2>/dev/null
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== the default is eventlet =="

unset OPENALGO_WORKER_CLASS OPENALGO_GUNICORN_THREADS
resolve
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "nothing set resolves to eventlet" \
    || no "nothing set resolved to '$GUNICORN_WORKER_CLASS', not eventlet"

[ "$GUNICORN_WORKER_ARGS" = "--worker-class eventlet" ] \
    && ok "eventlet emits no --threads" \
    || no "eventlet emitted '$GUNICORN_WORKER_ARGS'"

# An empty .env, and a .env that mentions nothing relevant, must both behave
# exactly like no .env at all.
: > "$TMP/empty.env"
resolve "$TMP/empty.env"
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "empty .env resolves to eventlet" \
    || no "empty .env resolved to '$GUNICORN_WORKER_CLASS'"

printf "BROKER_API_KEY = 'x'\nAPP_KEY = 'y'\n" > "$TMP/unrelated.env"
resolve "$TMP/unrelated.env"
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "unrelated .env resolves to eventlet" \
    || no "unrelated .env resolved to '$GUNICORN_WORKER_CLASS'"

resolve "$TMP/does-not-exist.env"
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "missing .env resolves to eventlet" \
    || no "missing .env resolved to '$GUNICORN_WORKER_CLASS'"

echo "== opting in =="

OPENALGO_WORKER_CLASS="gthread"
unset OPENALGO_GUNICORN_THREADS
resolve
[ "$GUNICORN_WORKER_CLASS" = "gthread" ] \
    && ok "OPENALGO_WORKER_CLASS=gthread opts in" \
    || no "opt-in resolved to '$GUNICORN_WORKER_CLASS'"

# The single most important check in this file: gthread alone must never
# produce Gunicorn's 1-thread default.
[ "$GUNICORN_THREADS" = "64" ] \
    && ok "gthread alone defaults to 64 threads, not 1" \
    || no "gthread alone gave threads='$GUNICORN_THREADS', expected 64"

[ "$GUNICORN_WORKER_ARGS" = "--worker-class gthread --threads 64" ] \
    && ok "assembled args carry both worker and threads" \
    || no "assembled args were '$GUNICORN_WORKER_ARGS'"

OPENALGO_WORKER_CLASS="GThread"
resolve
[ "$GUNICORN_WORKER_CLASS" = "gthread" ] \
    && ok "worker class is case-insensitive" \
    || no "'GThread' resolved to '$GUNICORN_WORKER_CLASS'"

OPENALGO_WORKER_CLASS="gthread"
OPENALGO_GUNICORN_THREADS="96"
resolve
[ "$GUNICORN_THREADS" = "96" ] \
    && ok "an explicit thread count is honoured" \
    || no "explicit 96 became '$GUNICORN_THREADS'"

echo "== opting in via .env, which is what Docker users edit =="

unset OPENALGO_WORKER_CLASS OPENALGO_GUNICORN_THREADS
printf "OPENALGO_WORKER_CLASS = 'gthread'\n" > "$TMP/optin.env"
resolve "$TMP/optin.env"
[ "$GUNICORN_WORKER_CLASS" = "gthread" ] && [ "$GUNICORN_THREADS" = "64" ] \
    && ok ".env opt-in works and still implies a thread count" \
    || no ".env opt-in gave '$GUNICORN_WORKER_CLASS'/'$GUNICORN_THREADS'"

# The three quoting styles that appear in a real OpenAlgo .env.
for style in "OPENALGO_WORKER_CLASS = 'gthread'" \
             "OPENALGO_WORKER_CLASS='gthread'" \
             "OPENALGO_WORKER_CLASS=gthread" \
             "OPENALGO_WORKER_CLASS = \"gthread\""; do
    printf '%s\n' "$style" > "$TMP/style.env"
    resolve "$TMP/style.env"
    [ "$GUNICORN_WORKER_CLASS" = "gthread" ] \
        && ok "parses: $style" \
        || no "failed to parse: $style (got '$GUNICORN_WORKER_CLASS')"
done

printf "OPENALGO_WORKER_CLASS = 'gthread'\nOPENALGO_GUNICORN_THREADS = '48'\n" > "$TMP/both.env"
resolve "$TMP/both.env"
[ "$GUNICORN_THREADS" = "48" ] \
    && ok "thread count is read from .env too" \
    || no ".env thread count gave '$GUNICORN_THREADS'"

# Railway and `docker run -e` set real environment variables; those must win
# over the file, matching python-dotenv's non-overriding behaviour.
OPENALGO_WORKER_CLASS="eventlet"
resolve "$TMP/both.env"
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "process environment overrides .env" \
    || no "process env lost to .env: got '$GUNICORN_WORKER_CLASS'"
unset OPENALGO_WORKER_CLASS

echo "== bad input must degrade safely, never fail to start =="

OPENALGO_WORKER_CLASS="gevent"
unset OPENALGO_GUNICORN_THREADS
resolve
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "an unsupported worker falls back to eventlet" \
    || no "'gevent' resolved to '$GUNICORN_WORKER_CLASS'"

OPENALGO_WORKER_CLASS="gthred"   # typo
resolve
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] \
    && ok "a typo falls back to eventlet rather than failing" \
    || no "typo resolved to '$GUNICORN_WORKER_CLASS'"

# The warning must actually reach the operator, or a typo silently keeps them
# on eventlet while they believe they are testing gthread.
OPENALGO_WORKER_CLASS="gthred"
warn_output="$(resolve_gunicorn_runtime "" 2>&1 >/dev/null)"
printf '%s' "$warn_output" | grep -q "gthred" \
    && ok "the typo is named in a warning on stderr" \
    || no "no warning mentioned the bad value"

OPENALGO_WORKER_CLASS="gthread"
OPENALGO_GUNICORN_THREADS="not-a-number"
resolve
[ "$GUNICORN_THREADS" = "64" ] \
    && ok "a non-numeric thread count falls back to the default" \
    || no "non-numeric gave '$GUNICORN_THREADS'"

OPENALGO_GUNICORN_THREADS="1"
resolve
[ "$GUNICORN_THREADS" = "16" ] \
    && ok "threads=1 is raised to the floor instead of deadlocking" \
    || no "threads=1 gave '$GUNICORN_THREADS', expected the floor of 16"

OPENALGO_GUNICORN_THREADS="4"
resolve
[ "$GUNICORN_THREADS" = "16" ] \
    && ok "a below-floor value is raised to 16" \
    || no "threads=4 gave '$GUNICORN_THREADS'"

OPENALGO_GUNICORN_THREADS="2000"
resolve
[ "$GUNICORN_THREADS" = "2000" ] \
    && ok "a very high value is warned about but honoured" \
    || no "threads=2000 gave '$GUNICORN_THREADS'"

# A thread count set while staying on eventlet must not silently arm gthread.
unset OPENALGO_WORKER_CLASS
OPENALGO_GUNICORN_THREADS="64"
resolve
[ "$GUNICORN_WORKER_CLASS" = "eventlet" ] && [ "$GUNICORN_WORKER_ARGS" = "--worker-class eventlet" ] \
    && ok "a thread count alone does not opt in" \
    || no "threads alone produced '$GUNICORN_WORKER_ARGS'"

echo "== every launch surface actually uses the resolver =="

unset OPENALGO_WORKER_CLASS OPENALGO_GUNICORN_THREADS

# start.sh -- the Docker runtime path, which is where most installs live.
START="$REPO/start.sh"
grep -q "install/lib/gunicorn_runtime.sh" "$START" \
    && ok "start.sh sources the resolver" \
    || no "start.sh does not source the resolver"

grep -q 'resolve_gunicorn_runtime "\$ENV_FILE"' "$START" \
    && ok "start.sh resolves against the bind-mounted .env" \
    || no "start.sh does not pass .env to the resolver"

grep -q '\$GUNICORN_WORKER_ARGS' "$START" \
    && ok "start.sh launches with the resolved args" \
    || no "start.sh does not use GUNICORN_WORKER_ARGS"

grep -qE '^\s+--worker-class eventlet' "$START" \
    && no "start.sh still hard-codes --worker-class eventlet" \
    || ok "start.sh no longer hard-codes a worker class"

# The systemd generators must bake the resolved args into ExecStart.
for f in install/install.sh install/install-multi.sh; do
    grep -q 'GUNICORN_WORKER_ARGS' "$REPO/$f" \
        && ok "$f uses the resolved args in ExecStart" \
        || no "$f does not use GUNICORN_WORKER_ARGS"

    grep -qE '^\s+--worker-class eventlet' "$REPO/$f" \
        && no "$f still hard-codes --worker-class eventlet" \
        || ok "$f no longer hard-codes a worker class"

    # A user who installs from a checkout predating the resolver must still get
    # a working unit rather than an empty ExecStart argument.
    grep -q 'GUNICORN_WORKER_ARGS="--worker-class eventlet"' "$REPO/$f" \
        && ok "$f falls back to eventlet when the resolver is absent" \
        || no "$f has no fallback when the resolver is missing"
done

echo "== update.sh couples the worker class to a thread count =="

# This is the bug this change fixes: update.sh used to default the thread count
# to empty, so opting in would rewrite the unit to gthread with no --threads --
# Gunicorn's 1-thread default, which deadlocks on the first SSE stream.
UPDATE="$REPO/install/update.sh"

grep -q 'TARGET_GUNICORN_THREADS="\${OPENALGO_GUNICORN_THREADS:-}"' "$UPDATE" \
    && no "update.sh still defaults the thread count to empty" \
    || ok "update.sh no longer reads the thread count independently"

grep -q "resolve_target_worker" "$UPDATE" \
    && ok "update.sh resolves through the shared library" \
    || no "update.sh does not call resolve_target_worker"

# Exercise the real function rather than describing it.
RESOLVER_FRAGMENT="$TMP/resolve_target.sh"
sed -n '/^resolve_target_worker() {/,/^}/p' "$UPDATE" > "$RESOLVER_FRAGMENT"
[ -s "$RESOLVER_FRAGMENT" ] \
    && ok "resolve_target_worker is extractable for testing" \
    || no "could not extract resolve_target_worker"

(
    # shellcheck source=/dev/null
    . "$LIB"
    # shellcheck source=/dev/null
    . "$RESOLVER_FRAGMENT"
    TARGET_WORKER_CLASS="eventlet"; TARGET_GUNICORN_THREADS=""
    OPENALGO_PATH="$TMP/instance"
    mkdir -p "$OPENALGO_PATH"
    printf "OPENALGO_WORKER_CLASS = 'gthread'\n" > "$OPENALGO_PATH/.env"
    resolve_target_worker 2>/dev/null
    [ "$TARGET_WORKER_CLASS" = "gthread" ] && [ "$TARGET_GUNICORN_THREADS" = "64" ]
) && ok "update.sh opt-in yields gthread WITH a thread count, not a 1-thread unit" \
  || no "update.sh opt-in did not produce a thread count"

(
    # shellcheck source=/dev/null
    . "$LIB"
    # shellcheck source=/dev/null
    . "$RESOLVER_FRAGMENT"
    TARGET_WORKER_CLASS="sentinel"; TARGET_GUNICORN_THREADS="sentinel"
    OPENALGO_PATH="$TMP/plain"
    mkdir -p "$OPENALGO_PATH"
    : > "$OPENALGO_PATH/.env"
    resolve_target_worker 2>/dev/null
    [ "$TARGET_WORKER_CLASS" = "eventlet" ] && [ -z "$TARGET_GUNICORN_THREADS" ]
) && ok "update.sh leaves an ordinary install on eventlet with no --threads" \
  || no "update.sh changed the worker on an ordinary install"

echo "== the opt-in is documented and covered in CI =="

SAMPLE="$REPO/.sample.env"
grep -q "OPENALGO_WORKER_CLASS" "$SAMPLE" \
    && ok ".sample.env documents the opt-in variable" \
    || no ".sample.env does not mention OPENALGO_WORKER_CLASS"

# It must be documented as commented-out, or every fresh install silently
# switches worker the moment someone copies .sample.env to .env.
grep -qE "^[[:space:]]*OPENALGO_WORKER_CLASS[[:space:]]*=" "$SAMPLE" \
    && no ".sample.env has OPENALGO_WORKER_CLASS ACTIVE, not commented out" \
    || ok ".sample.env leaves the opt-in commented out"

grep -q "EXPERIMENTAL" "$SAMPLE" \
    && ok ".sample.env marks the opt-in experimental" \
    || no ".sample.env does not mark the opt-in experimental"

CI="$REPO/.github/workflows/ci.yml"
grep -q "gthread_container_smoke.sh .* gthread 64" "$CI" \
    && ok "CI boots a container with the gthread opt-in" \
    || no "CI has no gthread opt-in container boot"

grep -q "EXPECTED_WORKER_CLASS: eventlet" "$CI" \
    && ok "the DEFAULT container boot is still asserted to be eventlet" \
    || no "CI no longer asserts eventlet as the default worker"

# The smoke script must actually inject the opt-in, or the gthread CI leg
# would boot an eventlet container and pass for the wrong reason.
grep -q "OPENALGO_WORKER_CLASS=" "$REPO/scripts/gthread_container_smoke.sh" \
    && ok "the smoke script opts in the way a user would" \
    || no "the smoke script never sets OPENALGO_WORKER_CLASS"

echo "== the shipped default is unchanged for existing installs =="

# The single most consequential property of this change. Nothing that runs on
# an untouched install may name gthread as its default.
DEFAULT_LEAK=0
for f in start.sh install/install.sh install/install-multi.sh install/update.sh; do
    # Strip comments first: these files explain gthread at length, and matching
    # prose would make this check fail for the one reason that does not matter.
    if sed -E 's/(^|[[:space:]])#.*$//' "$REPO/$f" \
        | grep -qE '(OPENALGO_WORKER_CLASS:-gthread|WORKER_CLASS="gthread"|--worker-class gthread)'; then
        echo "    $f defaults to gthread"
        DEFAULT_LEAK=1
    fi
done
[ "$DEFAULT_LEAK" -eq 0 ] \
    && ok "no launch surface defaults to gthread" \
    || no "a launch surface defaults to gthread"

grep -q 'requested:-eventlet' "$LIB" \
    && ok "the resolver's built-in default is literally eventlet" \
    || no "the resolver's default is no longer eventlet"

echo
echo "Passed: $PASS  Failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
