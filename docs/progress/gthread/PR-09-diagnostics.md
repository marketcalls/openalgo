# PR-9 — Report the running configuration correctly

**Status:** Done · **Tracker items:** GT-C5-01, GT-C5-02, GT-C5-03 · **Runs on:** the current eventlet setup

This ships **before** the switch on purpose. Diagnostics are how a bad switch
gets noticed — turning them on afterwards would be like fitting a smoke alarm
after the fire.

## What was broken

The admin panel and the downloadable system report both describe what the
server is running. That description was worked out entirely from one question:
*is eventlet active?*

- Yes → "gunicorn-eventlet"
- No → **"flask-dev"**

There was no third answer. So the moment we switch workers, a production server
would confidently report itself as **a developer's laptop**.

That matters more than it sounds. The system report is what users paste into bug
reports — it is how we found the original database-locking issue. During a
migration, a report that cannot tell you which worker is running, how many
threads it has, or whether the market-data feed is in its own process is close
to useless.

## What we changed

The runtime section now reports what is **actually** running, rather than
inferring it from one library's presence:

| Field | Why it matters |
| --- | --- |
| WSGI server | Now `gunicorn-gthread`, `gunicorn-eventlet` or `flask-dev` |
| Gunicorn version | The old worker was removed in version 26 |
| Worker class | The single most important fact during this migration |
| Configured threads | The thread budget — the main capacity limit under the new worker |
| Configured workers | Must stay at 1 |
| Active OS threads | Compare against the budget to spot saturation |
| WebSocket proxy mode | Confirms the market-data feed did not silently move |

These are read from the server's live configuration, so a value set in a config
file or environment variable is reported as it is really in force — not as the
command line happens to read.

The same fields now appear in the downloadable report and in the frontend's
type definitions, so the admin UI can show them.

## Verified against a real server, not just in tests

We started an actual Gunicorn 26 gthread worker with 17 threads and asked it to
describe itself:

```json
{
  "wsgi_hint": "gunicorn-gthread",
  "gunicorn_version": "26.0.0",
  "worker_class": "gthread",
  "configured_threads": 17,
  "configured_workers": 1,
  "active_threads": 2,
  "websocket_proxy_mode": "subprocess"
}
```

Every field correct. As a bonus this independently confirmed PR-2's fix: under
Gunicorn the market-data proxy correctly resolves to its **own process**, with
no eventlet involved.

## A test that was protecting nothing

The Telegram start-up test began by importing eventlet and switching it on.
eventlet is not installed here any more, so that test had stopped running
entirely — **it failed before it could collect a single check**, and had been
doing so silently.

It now skips cleanly when eventlet is absent, and still runs when it is present.
Alongside it we added checks for the code path that becomes production after the
switch: the start-up branch used when eventlet is *not* active. That branch runs
on a worker thread, where asking for the current event loop raises an error
rather than creating one — so its error-handling fallback is load-bearing, and
is now covered.

## How we know it works

`test/test_gthread_diagnostics.py` — **16 checks, all passing.**

Including both directions: a simulated gthread worker must report
`gunicorn-gthread` with its thread count, **and** a simulated eventlet worker
must still report `gunicorn-eventlet`. Accuracy before the switch matters as
much as after — otherwise we could not trust a report taken during a rollback.
