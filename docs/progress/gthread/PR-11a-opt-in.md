# PR-11a — Making gthread available to try, without changing anything by default

**Status:** Done · **Tracker items:** GT-C1-01, GT-C3-01, GT-C3-02, GT-C3-03, GT-C3-06 · **Runs on:** both

This is **not** the switch. The default is unchanged: every existing install
keeps running eventlet and will not notice this release. What it adds is a way
for someone who *wants* to test gthread to do so by setting one variable.

## Why this step exists at all

The plan originally called for a canary: switch a small percentage first, watch,
then widen. That works for a service you operate. **It does not work here.**

OpenAlgo is self-hosted by around 290,000 people, roughly 80% of them on Docker
or an Ubuntu server. Each of them upgrades on their own schedule with `git pull`
or `docker pull`. There is no gradual rollout, no traffic shifting, and — the
part that matters — **no way to roll anything back centrally**. Once a change is
on `main`, it belongs to whoever pulls it, and it cannot be recalled.

So the safe order is the reverse of a canary: make the new runtime *available*,
let people opt in deliberately, collect evidence from real installs on real
hardware, and only then consider changing the default.

## The finding that made this cheap

The migration was expected to need a Gunicorn upgrade, because Gunicorn 26
removes eventlet. But the version already pinned everywhere — **25.3** — ships
**both** workers:

```
supported workers: asgi, eventlet, gevent, gevent_pywsgi, gevent_wsgi, gthread, sync, tornado
```

So making gthread available needs **no dependency change at all**. `Dockerfile`
and `requirements-nginx.txt` keep `gunicorn>=25.0,<26` exactly as they are. The
image everybody already runs can do this today. That removes the single riskiest
part of the step: nobody's dependency set changes.

## How someone opts in

**Docker** — add one line to `.env` and restart the container:

```
OPENALGO_WORKER_CLASS = 'gthread'
```

Every Docker install already bind-mounts `.env` into the container, so this
needs no compose regeneration, no re-running the installer, and it **survives
`docker pull`**.

**Ubuntu server** — set the same variable in the instance's `.env` and re-run
`install/update.sh`. The updater rewrites the systemd unit, backs up the
previous one, and puts it back automatically if the service does not come up.

Either way, going back is removing the line and restarting.

## The trap this closes

Gunicorn's gthread worker defaults to **one thread**. That default is fine for
an ordinary web app and actively dangerous for this one, because OpenAlgo holds
a request thread for the entire life of a stream — live strategy logs and MCP
both stream indefinitely.

Before this change, `install/update.sh` read the worker class and the thread
count as two independent settings, with the thread count defaulting to empty. So
anyone who set only the worker class would have had their unit rewritten to
`--worker-class gthread` with no `--threads`, and got a **one-thread server**.

That was measured rather than assumed. With one long-lived stream open:

| Threads | An ordinary request arriving while a stream is open |
| --- | --- |
| 1 | **Never served** — gave up after 6s |
| 64 | Served in under 0.1s |

A user opting in would have watched their server stop responding on boot and
reasonably concluded gthread is broken.

**So the two settings are no longer independent.** Choosing gthread always
produces a thread count: 64 by default, and anything below 16 is raised to 16
with a warning. Setting a thread count on its own does nothing, because that
alone should never change which worker runs.

## Everything else degrades toward eventlet

Bad input must never stop someone's trading server from starting. A misspelled
worker name (`gthred`), an unsupported one (`gevent`), or a non-numeric thread
count all fall back to a working configuration and print a warning naming the
bad value — so a typo cannot leave someone quietly on eventlet while they
believe they are testing gthread.

## One shared resolver, not eleven copies

All of this lives in a single file, `install/lib/gunicorn_runtime.sh`, sourced by
the container entrypoint, both installers, and the updater. The alternative —
repeating the defaulting rules across four shell scripts — is how the floor
ends up enforced in three places and forgotten in the fourth.

Where the file is missing (someone installing from an older checkout), the
installers fall back to plain eventlet, which is what they did before.

## How we know it works

`test/test_gthread_worker_optin.sh` — **48 checks**, all passing.

The first and last of them assert the same thing from different directions: that
nothing here changes the default. One checks the resolver returns eventlet when
nothing is set; the other greps every launch surface for a gthread default and
fails if it finds one. That check was verified to still catch a real default
after being taught to ignore comments.

The suite was also mutation-tested. Flipping the resolver's default to gthread
fails 5 checks; dropping the thread floor fails 2; changing the default thread
count from 64 to 1 fails 4.

Beyond the unit checks, the **real application was booted both ways** on this
machine:

| Configuration | Result |
| --- | --- |
| Nothing set | Boots on eventlet, serves, 1 OS thread |
| `OPENALGO_WORKER_CLASS=gthread` | Resolves to `--worker-class gthread --threads 64`, boots, serves |

CI now boots the container image **twice** on every pull request: once with the
default, asserting it is still eventlet, and once with the opt-in set, asserting
gthread comes up. The second is marked `continue-on-error` on purpose — the
experimental path must not be able to block a release of the default one.

Full suite: **215 Python checks** and **75 shell checks**, all passing.

## What this deliberately does not do

- It does not change the default worker for anyone.
- It does not change any pinned dependency.
- It does not touch the five Docker compose generators, because reading `.env`
  turned out to make that unnecessary.
- It does not resolve the thread count question. 64 is a starting point derived
  on paper, not a measurement. **Getting that measurement from real installs is
  the entire purpose of shipping this.**

## What would make the default flip defensible

Evidence from opt-in users, which the diagnostics added in earlier steps already
collect: the thread high-water mark, live stream counts, and whether any
multi-packet Socket.IO messages occur at all. Plus the platform coverage that
cannot be produced here — a real Ubuntu server, a multi-instance host, and a
24-hour soak through a full trading day.

Until then this stays experimental, and the default stays eventlet.
