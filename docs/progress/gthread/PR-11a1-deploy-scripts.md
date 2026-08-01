# PR-11a.1 — Confirming two scripts need no change

**Status:** Done · **Tracker items:** GT-C3-11, GT-C3-12 (resolved), GT-C3-13 (part) · **Runs on:** both

Two deployment scripts were flagged as migration risks. Neither turned out to
need changing. This page records **why**, and the checks that keep the reasoning
from going stale.

"No change needed" is the easiest conclusion to get wrong later. Someone extends
a script six months from now, the original reason silently stops holding, and
nobody revisits a row already marked resolved.

## 1. Changing your domain must not undo the worker migration

`install/change-domain.sh` restarts the service and rewrites the nginx config.
The worry was concrete: once `update.sh` has rewritten the systemd unit to use a
different worker, a script that also writes that unit could quietly put the old
one back — and the symptom would appear days later, after an unrelated domain
change.

It does not. The script reads the unit path **only to print it** in its summary
(`:256-258`). It never parses `ExecStart` and never writes the file. It stops and
starts the service by name, so it picks up whatever the unit currently says.

So a domain change is safe before or after the migration, in either order.

The second half of that row matters more than it first appears. Because the
script **regenerates the nginx config**, it owns the `/socket.io/` block. Drop an
upgrade header there and the WebSocket transport breaks for every client after a
domain change — and it would look like an application bug, not an nginx one. The
block is now pinned: HTTP/1.1, both upgrade headers, buffering off, and an
extended read timeout so long-lived sessions are not cut at nginx's default.

## 2. The Windows updater has no service to migrate

`install/update.bat` was flagged to confirm it needed no unit handling. It does
not, and the reason is more interesting than the answer.

Windows does not run Gunicorn or systemd. The updater backs up databases, pulls,
checks `.env`, runs `uv sync`, and applies migrations. There is no worker class
anywhere in its 320 lines.

**Windows and macOS users have never run eventlet at all.** `uv run app.py` uses
standard threading. That reframes the work in PR-1 through PR-10: those races
were not hypothetical, and they were not only about a future switch. Every one of
them — the double margin release, the cache going blank mid-refresh, the sandbox
sweeps running twice — has been **reachable on Windows and macOS the whole time**.
The migration did not create those bugs. It found them.

## 3. The documentation item is only half done, deliberately

`GT-C3-13` asks for documentation with "no stale eventlet runtime claims".

**That half cannot honestly be done yet, because eventlet is not stale.** It is
still what runs by default. Every eventlet reference in the Docker and Ubuntu
server documents is currently *correct*, and rewriting them now would make the
docs describe a runtime nobody is using.

What was done instead is the half that applies today: both documents now explain
how to opt into gthread, that it is experimental, and how to go back. The
Docker page covers the `.env` line and that it survives `docker pull`; the Ubuntu
page covers re-running the updater and the automatic unit restore. Both explain
why the thread count is not a separate choice.

The row stays **open**, with the split recorded, and the eventlet rewrite waits
for the cutover that makes it true.

## How we know it works

`test/test_gthread_deploy_scripts.sh` — **15 checks**, all passing.

Each one pins a property the conclusion depends on rather than restating the
conclusion. Verified by mutation:

| Change | Result |
| --- | --- |
| `change-domain.sh` given a line that rewrites the unit | **caught** |
| an upgrade header removed from the Socket.IO block | **caught** |
| `update.bat` given a gunicorn reference | **caught** — names the row to reopen |

The Windows check is written so that if `update.bat` ever gains service
handling, the failure message says to reopen `GT-C3-12` rather than just
reporting a mismatch.

## Status

23 items remain: 5 belong to the switch itself, and 18 need a real server, a
Docker daemon, a multi-instance host, a soak, a browser session, or a rollback
rehearsal.

There is no further code that can be honestly justified from a developer machine.
What is needed now is the manual testing pass — all features, live WebSockets,
a real broker session — on the current default runtime.
