# PR-10 — Add tests that boot the real container

**Status:** Done · **Tracker items:** GT-P-01 … GT-P-07, GT-P-12, GT-P-13 · **Runs on:** the current eventlet setup

This is the **last gate before the switch itself**, and it ships first on
purpose: these are the checks that would catch a bad switch.

## What was broken

### The Docker test never started the application

CI builds the container image on both Intel and ARM, which is good. But its only
test of that image ran:

```
docker run --entrypoint /app/.venv/bin/python ...
```

That `--entrypoint` **replaces** the container's normal startup. So the test
never ran the startup script, never started the web server, never started
Flask, never started Socket.IO, and never started the market-data proxy. It
imported a charting library and drew a picture.

That is a genuinely useful check for the thing it tests. But it means CI could
not detect:

- the wrong worker running,
- the market-data proxy failing to start,
- the shutdown handler being lost (exactly the bug PR-2 fixed),
- a container reporting itself healthy with market data dead.

### CI only ever tested Linux

The project requires code to work both on a developer's machine and in
production. CI ran Linux only, so a change that breaks Windows or macOS was
invisible until someone hit it.

### And the migration's own tests were not running

Found while writing this step: the test job ran **five named files**. None of
the ~120 checks written across PR-1 to PR-9 were among them. All that work was
sitting in the repository unprotected — a guarantee nobody re-checks quietly
stops being a guarantee.

## What we changed

**A real boot test.** `scripts/gthread_container_smoke.sh` starts the container
**through its normal entrypoint** and then asks it what it is actually running:

- Which worker, how many workers, how many threads.
- Whether the old library is still active.
- Where the market-data proxy is running.
- That Flask answers, that Socket.IO connects both ways, and that port 8765
  is listening.
- That stopping the container shuts down **both** processes cleanly, within the
  grace period, with the shutdown handler actually running.

It runs on Intel and ARM.

Crucially it is **parameterised, not hard-coded**: it asserts the worker matches
what we *expect*, and today that expectation is the current worker. So it is
meaningful now, and the switch changes one variable rather than rewriting the
test.

**Windows and macOS coverage.** A new job boots the app on all three operating
systems and asserts which runtime it got.

**The migration suites now run on every change** — all ~120 checks, both shell
suites, and both gate scripts. A newly introduced unlocked counter, or a drifted
inventory, now fails the build.

## How we know it works

`test/test_gthread_ci_gates.py` — **18 checks, all passing.**

They verify the workflow itself: that a boot step exists, that it does **not**
override the entrypoint, that it runs on both architectures, that the expected
worker is a single switchable variable, that the boot script probes each
surface and exits non-zero on any failure, that all three operating systems are
covered, and that the migration suites and gates are genuinely wired in.

The boot script cannot be executed here — Docker is installed but not running on
this machine — so it is syntax-checked and asserted against, and will execute
for real on the next pull request. That limit is worth stating plainly rather
than implying it has been run.

## Status

PR-1 through PR-10 are complete: **123 checks passing**, both gates green.

The next step is the switch itself, which is deliberately not started. Two
things need deciding first: the acceptance numbers (seven values in the plan are
still provisional), and the starting thread count — the corrected arithmetic
points to 64, because the long-lived connections alone account for 32 before a
single ordinary request is served.
