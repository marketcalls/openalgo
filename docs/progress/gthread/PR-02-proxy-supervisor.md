# PR-2 — Stop the market-data process from dying unnoticed

**Status:** Done · **Tracker items:** GT-A7-01, GT-A7-02, GT-A7-03 · **Runs on:** the current eventlet setup

## Background

OpenAlgo runs two things side by side in Docker:

- **The web app** (Gunicorn) — pages, orders, the API.
- **The market-data proxy** — the live price feed on port 8765.

They are separate processes. The startup script starts both.

## What was broken

### Problem 1: the shutdown handler was being deleted

`start.sh` started the price feed in the background, then set up a "when you
get a shutdown signal, stop both cleanly" handler. Then it launched Gunicorn
using a command called `exec`.

`exec` **replaces** the script with Gunicorn. The script stops existing — and
the shutdown handler goes with it.

So:

- Stopping the container never told the price feed to shut down cleanly.
- If the price feed crashed, **nobody noticed and nothing restarted it**.
- The container's health check only tested the web app, so Docker would happily
  report the container as *healthy* while **live market data was completely
  dead**.

That is the worst kind of failure: silent, and invisible to monitoring.

### Problem 2: the price feed could move house by accident

On a normal (non-Docker) server install, the app decided *where* to run the
price feed by asking "is eventlet turned on?" If yes, run it as its own
process. If no, run it inside the web app.

That question is about to change its answer. Switching the worker in PR-11
would have silently moved the price feed out of its own process and into the
web app — a real change to how production is laid out, arriving as a
side-effect of an unrelated setting. Nobody would have asked for it.

## What we changed

**The startup script is now a supervisor.** It no longer hands itself over to
Gunicorn. It stays alive and watches both processes:

- Passes shutdown signals to **both**, and gives Gunicorn its full 30 seconds
  to finish serving in-flight requests before forcing anything.
- **Restarts the price feed if it dies**, up to 5 times (configurable). A feed
  that cannot stay up is a real fault and should stop the container rather than
  spin forever.
- If Gunicorn exits, that is final — it stops the feed and exits with the same
  status, so Docker's restart policy behaves predictably.

**The health check now tests both.** It checks the web app *and* opens a
connection to port 8765. A container can no longer look healthy while the
market-data feed is dead.

**Where the price feed runs is now an explicit setting**, not a guess:

| `WEBSOCKET_PROXY_MODE` | Meaning |
| --- | --- |
| `external` | Something else runs it (Docker's startup script) |
| `subprocess` | Its own process — the default under Gunicorn |
| `thread` | Inside the app — development only |

If the setting is missing, the default is based on "are we running under
Gunicorn", not "is eventlet on". Changing the worker can no longer relocate
anything.

## How we know it works

**`test/test_gthread_proxy_mode.py` — 11 checks, all passing.**

Including the one that matters most: with the app running under Gunicorn, the
price feed stays in its own process **whether eventlet is on or off**. We also
ran the old logic to confirm it genuinely fails that check — it returned
"own process" with eventlet and "inside the app" without it, which is exactly
the accidental move we were guarding against.

**`test/test_gthread_start_supervisor.sh` — 17 checks, all passing.**

The interesting one is a live demonstration rather than a code inspection. We
build two tiny throwaway scripts — one using `exec` like the old code, one
supervising like the new code — send each a shutdown signal, and watch what
happens. The `exec` version loses its shutdown handler completely. The
supervisor version runs it. That is the bug, reproduced and then fixed.

The rest check that Gunicorn is no longer `exec`d, that the shutdown handler is
installed before Gunicorn starts, that shutdown signals **both** processes,
that restarts are capped, and that both health checks test port 8765 while
still testing the web app.

## Note

While testing, one command that temporarily shelved my changes timed out
half-way through, leaving the edit sitting in Git's stash instead of in the
files. Caught it by checking the working tree before committing, and restored
it. All tests were re-run afterwards and pass. Worth recording because a
half-restored working tree is an easy way to commit something that was never
actually tested.
