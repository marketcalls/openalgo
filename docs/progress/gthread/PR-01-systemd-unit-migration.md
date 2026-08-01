# PR-1 — Make server upgrades able to change the worker safely

**Status:** Done · **Tracker items:** GT-C2-01, GT-R-02 · **Runs on:** the current eventlet setup

## What was broken

On a normal Ubuntu server install, OpenAlgo runs as a system service. The
service has a config file that says exactly how to start the app, including
which "worker" to use.

The upgrade script (`install/update.sh`) installed new Python packages and then
told the system to "reload the service config". But **it never actually changed
that config file.** It reloaded a file nobody had edited.

That did not matter until now. But the new Gunicorn version has deleted
eventlet entirely. So an upgrade would have:

1. Installed the new Gunicorn,
2. Restarted the service,
3. The service config still said "use eventlet",
4. Eventlet no longer exists → **the app fails to start**,
5. And there was no automatic way back.

The user would be left with a dead trading server after a routine update.

## What we changed

`install/update.sh` now knows how to migrate that config file properly:

- **Take a backup first**, with a timestamp, so the old file is never lost.
- **Edit the worker setting** and the thread count.
- **Check the edit worked** before removing anything — if the file came out
  malformed, put the backup straight back.
- **If the service still won't start**, restore the old config, start the app
  again on the old settings, and stop with a clear message rather than leaving
  the server down.

## Nothing changes yet — on purpose

The target worker is still set to `eventlet`. So on today's servers the script
looks at the config, sees it is already correct, and does nothing.

This is deliberate. PR-1 installs the *machinery*; PR-11 flips the switch.
That way the upgrade path gets rehearsed on every single update for weeks
before it is ever asked to actually change something.

## How we know it works

`test/test_gthread_unit_migration.sh` — **10 checks, all passing.**

The test pulls the real functions out of `update.sh` and runs them, so it is
testing the shipped code, not a copy of it. It checks:

- A server with no service file is left alone without erroring.
- A config file that doesn't mention a worker is not touched.
- A config already set correctly is not rewritten.
- Changing eventlet → gthread leaves no trace of eventlet behind.
- The thread count is added when missing, updated when present, and never
  added twice.
- A backup is written before any edit.
- Restoring the backup gives back the original file exactly, character for
  character.

## Two things worth knowing

**My first version of this test was worthless.** It copied the edit commands
into the test instead of calling the real functions — so it would have passed
while testing nothing at all. That is why the function now accepts a test-only
override for the file path: so the test can drive the actual code.

**A Mac/Linux difference nearly hid a bug.** The text-editing tool behaves
differently on macOS than on Linux servers. The shipped script is correct
because it only ever runs on Linux, but the test now installs the Linux version
locally so those checks genuinely run on a developer's machine instead of
quietly skipping.
