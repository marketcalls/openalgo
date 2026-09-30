# The gthread web server (optional)

OpenAlgo runs inside a web server called gunicorn, and gunicorn can run it in
two ways. **eventlet** is the default and stays the default. **gthread** is
opt-in: select it in `.env` and start through the supplied launcher. An older
systemd service also needs the one-time switch command below; editing `.env`
alone does not change a service that still hardcodes eventlet.
This page explains what gthread is, who should try it, how to switch on
Ubuntu and on Docker, how to check that it works, and how to switch back.

Nothing on this page happens to your server by itself. An update does not
switch anything unless you have asked for gthread in `.env`.

## What gthread is, and why you might want it

- **eventlet** schedules request greenlets cooperatively: a request waiting
  on cooperative I/O lets other requests run. Blocking code that does not
  cooperate can stall the worker. It is OpenAlgo's existing default. Gunicorn
  has announced that it will drop eventlet in its next major version, and several past problems
  ("the first order works, the next one hangs the app") came from eventlet
  and ordinary threads meeting inside OpenAlgo.
- **gthread** gives every request its own thread from a fixed pool of 64. It
  lets other threads serve requests while one waits on a broker. Shared locks,
  CPU-heavy work and exhaustion of all 64 slots can still delay requests.

Both run the same OpenAlgo. Orders, strategies, Flow, the charting and
scalping terminals, Telegram and WhatsApp alerts work the same way on either.

## Installing with gthread

Gthread is built into Gunicorn; there is no separate gthread package to install.
Keep the project's pinned dependencies, including eventlet for rollback.
Use a source checkout or container image that includes this implementation;
an older published image cannot gain support just by setting the variable.

| Installation path | How to select gthread |
|---|---|
| Fresh Linux systemd install using `install/install.sh` | Finish the normal eventlet installation, then run the switch commands below. The installer currently has no worker-selection prompt. |
| Fresh multi-instance install using `install/install-multi.sh` | Finish installation, then switch the chosen service with `--service openalgo1 --to gthread`, or use `--all`. |
| Existing installer-managed systemd installation | Update to a release containing the launcher, then use `install/switch-worker.sh --to gthread`. |
| Docker Compose, including `install/install-docker.sh` | Set `OPENALGO_WORKER_CLASS = 'gthread'` in the mounted `.env`, set `stop_grace_period: 45s`, then recreate the container. |
| Windows/macOS/Linux Docker runner | Use a compatible image, set the same `.env` key, then restart with the updated `install/docker-run.bat` or `install/docker-run.sh`. These runners allow 45 seconds for container shutdown. |
| Native `uv run app.py` | This is the development server and ignores the Gunicorn worker setting. Use the supported Ubuntu or container path to run gthread. |

The single-instance installer detects Ubuntu, Debian, Raspbian, Arch and several
RPM-based distributions; the same switch applies to the systemd service it
generates. The multi-instance installer uses apt and targets Ubuntu/Debian.
The examples below use Ubuntu and the default installation paths.

After the single-instance installer completes:

```bash
cd /var/python/openalgo
sudo bash install/switch-worker.sh --to gthread --dry-run
sudo bash install/switch-worker.sh --to gthread
```

The same trading-hours guard applies to new installations. On an empty instance
with no trading activity, `--force` explicitly allows the switch during that
window. See [When to switch](#when-to-switch) before using it on an active instance.

For a fresh Docker Compose deployment, complete configuration, add the worker
setting and shutdown grace below, then run `docker compose up -d --build` when
building the repository's image locally. An existing local image must also be
rebuilt when it predates this implementation; `--force-recreate` alone reuses it.

After starting, [check the system report](#check-that-it-works): it must show
**gthread**, **64 request threads**, and **Started by launcher: True**. The
launcher enforces one worker process and configures the runtime and shutdown
hooks; use it instead of replacing only `--worker-class` in an old service file.

## Who should try it now

Try it if you:

- are comfortable running a few commands over SSH and reading a log;
- can pick a quiet time after 23:30 IST to switch (see below);
- use a broker from the verified list at the end of this page, or are happy
  to be the first to verify yours and tell us how it went.

Wait for now if you run strategies that must never pause, or if you run many
OpenAlgo instances on a small server (each gthread instance uses 64 request
threads, see [Known limits](#known-limits)).

## Before you start

### Platforms

| Host | Runtime and deployment |
|---|---|
| Ubuntu desktop or server | The supplied systemd installer and worker switch script, or Linux containers |
| Other Linux desktops and servers | Linux containers or a managed Gunicorn process using the launcher. The installer detects several Linux distributions; validate the generated systemd service and dependencies on your distribution. Automated Linux checks use Ubuntu runners. |
| Windows | `uv run app.py` uses native threads and ignores the worker setting. Use a Linux container or Ubuntu in WSL2 for the Gunicorn eventlet/gthread deployment |
| macOS | `uv run app.py` uses native threads. Linux containers provide the production deployment; the Ubuntu systemd scripts do not apply to macOS |
| Raspberry Pi | Use a 64-bit Linux OS and ARM64 dependencies. Native Linux ARM64 CI checks compatibility; it does not measure a Pi's memory, thermal limits, or trading-day capacity |

Gunicorn is a Unix server; setting `OPENALGO_WORKER_CLASS` does not turn the
native Windows development server into Gunicorn. A desktop running a server
must stay awake and keep its network connection available.

### Running continuously

Use a service manager or the documented container restart policy so OpenAlgo
starts after a reboot or process failure. Keep one Gunicorn worker per
instance, allow the shutdown window described below, and monitor disk space
for databases, strategy output and logs. On a small ARM64 host, check memory
and thread usage with the actual number of tabs, strategies and subscriptions
you intend to run; the 64-thread request budget is per instance.

Before relying on a new runtime for live trading, run it through a complete
trading day and the overnight broker-session expiry. Check that reconnects
and resubscriptions recover, scheduled jobs resume, and memory, file handles
and thread counts settle after repeated connect/disconnect cycles. Automated
lifecycle and platform tests cover regressions but do not establish a
multi-day uptime guarantee or certify every broker. See the verification
status at the end of this page.

### Switch checklist

- **Update OpenAlgo first.** The files `install/openalgo-gunicorn.sh` and
  `install/switch-worker.sh` must be present in your OpenAlgo folder.
- **Ubuntu:** your service must be the one `install.sh` or `install-multi.sh`
  created. If you changed its `ExecStart` line by hand, the switch script
  leaves it alone and tells you why.
- **Have your OpenAlgo API key ready** for the check at the end (generate one
  at `/apikey`).
- **Download the system report** before you switch, so you can compare:
  `/admin/api/system/report` while logged in.

## When to switch

**After 23:30 IST and before 09:00 IST, never during the trading day.** The
trading day runs from 09:00 to 23:30 IST, because MCX's evening session ends
at 23:30. Switching restarts OpenAlgo: orders already at your broker are not
touched, but strategies, the market data feed and open browser pages pause
for up to a minute while it restarts.

The switch script refuses to restart OpenAlgo between 09:00 and 23:30 IST and
tells you to run it again later. It only goes ahead in that window if you add
`--force`, which you should do only when you are sure nothing is trading.

## Switch on Ubuntu (one install, made by install.sh)

1. Go to your OpenAlgo folder:

   ```bash
   cd /var/python/openalgo
   ```

2. See what would change, without changing anything:

   ```bash
   sudo bash install/switch-worker.sh --to gthread --dry-run
   ```

3. Switch:

   ```bash
   sudo bash install/switch-worker.sh --to gthread
   ```

The script writes `OPENALGO_WORKER_CLASS = 'gthread'` into `.env`, saves a
copy of your service file next to it (as
`/etc/systemd/system/openalgo.service.pre-launcher-<date>`), points the
service at the launcher, restarts OpenAlgo and checks that:

- the service is running,
- the OpenAlgo page answers,
- the live update channel the browser uses answers, and
- OpenAlgo is running on the web server `.env` asks for.

If any check fails, it attempts to restore the previous service file and worker,
checks the restarted service, and shows the last lines of the log. If that
restart also fails, it reports the failure and the manual recovery command;
check its result before resuming trading.

You can also edit `.env` yourself: add (or uncomment) the line
`OPENALGO_WORKER_CLASS = 'gthread'`, then run
`sudo bash install/switch-worker.sh` without `--to`.

**Updating later.** Keep using the updater as before. If `.env` asks for
gthread and the service does not use the launcher yet, the updater switches
it at the end, with the same checks and the same automatic restore. If you
update during the trading day, it tells you to run the switch again after
23:30 IST.

## Switch on a server with several instances (install-multi.sh)

Each instance has its own folder (`/var/python/openalgo-flask/openalgo1`,
`openalgo2`, ...), its own service (`openalgo1`, `openalgo2`, ...) and its own
`.env`, so each chooses its own web server.

- One instance:

  ```bash
  cd /var/python/openalgo-flask/openalgo1
  sudo bash install/switch-worker.sh --service openalgo1 --to gthread
  ```

- Every instance, one at a time (it stops at the first one that fails, after
  putting that one back):

  ```bash
  sudo bash install/switch-worker.sh --all --to gthread
  ```

At the end it tells you how many request threads the gthread instances use
together (64 each). If your server limits processes or tasks, the launcher
writes a warning into each instance's log when the limit is too low.

**Updating later.** Run the updater from inside the instance you want to
update, once per instance, one after another:

```bash
cd /var/python/openalgo-flask/openalgo1
sudo bash install/update.sh
```

It updates that instance and restarts its service. If that instance's `.env`
asks for gthread and its service does not use the launcher yet, it switches it
at the end, exactly as on a single install. Run from anywhere else, it updates
the only instance if there is one, and otherwise asks which.

One exception: on a server that also has a single install at
`/var/python/openalgo` (or an older multi-deploy layout under
`/var/python/openalgo-flask/<name>/openalgo`), the updater updates that one,
wherever you run it from, as it always has. Update the instances on such a
server as you do today, then run the switch script for each one.

## Switch on Docker

1. Add this line to the `.env` file next to your `docker-compose.yaml` (the
   one mounted into the container as `/app/.env`):

   ```
   OPENALGO_WORKER_CLASS = 'gthread'
   ```

2. In the same `docker-compose.yaml`, give the OpenAlgo service 45 seconds to
   stop by adding `stop_grace_period` under it (keep your other lines as they
   are):

   ```yaml
   services:
     openalgo:
       stop_grace_period: 45s
   ```

   This step is required. See **Stopping** below for why.

3. After 23:30 IST, restart the container:

   ```bash
   docker compose up -d --force-recreate
   ```

4. The container log says
   `Starting application on port 5000 with gthread...`.

On Railway or another platform that sets environment variables for you, set
`OPENALGO_WORKER_CLASS=gthread` there instead, and set the platform's stop or
shutdown timeout to 45 seconds if it has one.

**Stopping.** On gthread, a stop gives open requests up to 30 seconds to
finish, and your running Python strategies and OpenScript runs are told to
stop at the same moment, side by side, so a strategy that handles the stop
signal gets its chance to clean up. Once OpenAlgo has finished, the market
data service is stopped too, within 5 seconds. Docker, though, forces a container to stop
10 seconds after asking it to, unless `stop_grace_period` says otherwise.
Without step 2 a stop cuts that cleanup short. Setting it to 45 seconds does
not make a normal stop slower: the container still stops as soon as OpenAlgo
has finished. On eventlet you can leave the line in place; it does no harm.

## Check that it works

1. **The system report.** Download `/admin/api/system/report` while logged
   in. Under *Runtime* it should say:
   - *Web server:* gthread
   - *Request threads:* 64
   - *Started by launcher:* True

   Any *Note:* lines there are written for you: for example that `.env` asks
   for a web server this server has not switched to yet, or that almost every
   request slot is busy.

2. **The log.** `sudo journalctl -u openalgo -n 50` (Docker:
   `docker compose logs --tail 50`) shows
   `Starting the gthread web server with 64 request threads`.

3. **Your broker.** Run the broker check against your own OpenAlgo address. It
   only reads (funds, positions, order book, trade book, holdings, quotes,
   depth, history) and prints a table of what passed and how long it took:

   ```bash
   cd /var/python/openalgo
   .venv/bin/python scripts/gthread_broker_smoke.py --url https://your-openalgo-domain --repeat 3 --parallel 4
   ```

   It asks for your API key rather than taking it on the command line. Log
   in to OpenAlgo and your broker first: after about 03:00 IST the broker
   session has expired and every call fails. Add `--order-check` only if
   OpenAlgo is in analyzer (sandbox) mode: it then places one small LIMIT buy
   far below the market in the sandbox (CNC on NSE and BSE, NRML elsewhere, so
   it works at any hour) and cancels it. In live mode it refuses.

4. **The next trading day.** Keep an eye on the system report and on
   `log/errors.jsonl`. If the report says almost every request slot is busy,
   see [Known limits](#known-limits).

## Switch back to eventlet

- **Ubuntu, service already on the launcher:** after 23:30 IST,

  ```bash
  sudo bash install/switch-worker.sh --to eventlet
  ```

  or set `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` and run
  `sudo systemctl restart openalgo`.
- **Put the original service file back entirely:**
  `sudo bash install/switch-worker.sh --restore`. It also sets
  `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` if it asked for gthread, so
  the next update does not switch the service over again.
- **Going back to an older OpenAlgo release.** A switched service starts
  OpenAlgo through `install/openalgo-gunicorn.sh`, which older releases do not
  have. Before you check out a release older than this one, run
  `sudo bash install/switch-worker.sh --restore` first, while the script is
  still there. Otherwise the service cannot start after the rollback. If that
  has already happened, copy back the saved file named in the comment just
  above the service file's `ExecStart` line (`<file>.pre-launcher-<date>`),
  then run `sudo systemctl daemon-reload` and restart the service.
- **Docker:** set `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` (or delete
  the line) and recreate the container.

## Known limits

- **A fixed budget of 64 request threads per instance.** It is not a
  setting. Most requests take a thread for a moment, but some hold one for as
  long as they are open: each browser tab keeps one live update connection
  waiting, shared by every page in it, and each open Python strategy log view,
  agent chat and remote MCP connection holds one while it is open. Five
  devices with two tabs each use about 10, plus one for each of those. If the
  system report says almost every request slot is busy, close tabs you are not
  using; if it keeps happening during trading, switch back to eventlet.
- **Stopping takes a little longer.** gthread lets open requests finish before
  it stops, for up to 30 seconds. On Docker this needs `stop_grace_period: 45s`
  (see [Switch on Docker](#switch-on-docker)).
- **Where the market data service runs** is shown in the system report as
  *Market data proxy*. On Ubuntu it runs as a separate process started by the
  web server, on gthread as on eventlet; if it stops, gthread starts it again
  after a short wait. On Docker the container starts it on its own and, on
  gthread, starts it again if it stops (after 1 second, then longer if it
  keeps stopping, up to 30 seconds); the container log says when it does.
- **The development server is not affected.** `uv run app.py` (including on
  Windows) ignores this setting; it only applies to gunicorn installs.

## What gthread refuses that eventlet waits for

Under eventlet a cooperative wait releases the worker to serve other greenlets.
Gthread has a fixed number of request threads, and waiting occupies a slot,
so a few kinds of waiting are cut short instead. The request is answered
with a sentence saying what happened and when to try
again. None of these is a setting, and none of them happens on eventlet.

- **A busy broker.** When a broker's rate limit would keep a request waiting
  more than about 10 seconds, the request is refused (HTTP 429) and nothing is
  sent to the broker. A smart order refused this way places nothing. This
  applies to a local refusal before sending. A broker response received
  after sending is not proof that nothing was placed; check the broker order
  book before repeating an order. An Action Center order whose status becomes
  unclear may still be sending, especially a split or basket order.
- **Two orders for the same symbol at once.** A smart order, or a sandbox
  order, that waits more than 30 seconds for another one on the same symbol to
  finish is refused with a sentence asking you to try again. Check your
  positions first.
- **Changing between live and sandbox mode.** A change that waits more than 30
  seconds for another change still in progress is refused (HTTP 409), and so is
  a sandbox reset behind one. A sandbox reset also stops the sandbox engines for
  the moment it takes and starts them again.
- **Reloading or clearing the symbol cache** while the master contract is still
  downloading is refused (HTTP 409) until the download finishes.
- **Flow workflows that wait.** A workflow whose Delay and Wait Until steps add
  up to more than 10 seconds runs in the background and answers at once (HTTP
  202); a shorter wait runs as before and answers with the result. Up to 16
  workflows waiting on a Delay, and separately up to 4 waiting on a Wait Until,
  can be running at the same time. The next one is refused (HTTP 429) without
  placing any order, and the refusal is shown in that workflow's execution
  history. Run Now on such a workflow shows it as running in the background.
- **Python strategy live log views.** At most eight windows stream at once;
  the next is told to wait (HTTP 503). An open view reconnects by itself every
  ten minutes.
- **Remote MCP and the agent.** At most four remote MCP streams stay open, each
  for up to five minutes, and at most eight MCP tool calls run at once. At most
  six agent chats stream at once, and one turn ends after 15 minutes.
- **OI Profile** spends at most 60 seconds fetching the day's open interest
  changes; if it runs out of time, the page says how many contracts it covered.
- **Email.** A mail server that does not answer within 20 seconds is reported
  as unreachable.
- **Sandbox square-off.** A square-off sweep that is still busy after 120
  seconds is picked up again by the next minute's check.

## Automated checks and remaining validation

The implementation and resource-cleanup follow-up passed
[CI on commit `38dbdcb0f`](https://github.com/marketcalls/openalgo/actions/runs/36626204203):
1,410 migration tests passed (three documentation skips), along with Windows,
macOS and Linux ARM64 platform checks, eventlet and gthread launcher boots,
frontend tests/builds, and AMD64/ARM64 container builds. These results apply to
that commit; check the PR's latest CI result for subsequent changes.

The resource regressions cover bounded authentication-error fingerprints and
pending strategy updates, Pocketful reconnect threads, retryable Flow
subscription cleanup, and browser socket/polling teardown. Flow delete and
deactivate now return 409 while a run is executing and 503 while a subscription
release needs retry. This cleanup behavior applies to both worker modes.

Still outstanding: a full trading-day broker run, overnight session expiry and
recovery, a deployment rollback drill, and Raspberry Pi hardware/resource
qualification. The 64-thread budget remains a limit; automated tests do not
certify unlimited concurrent streams or absence of every possible memory leak.

## Brokers verified on gthread

None yet. A broker moves to *Verified* once somebody has run a full trading
day on gthread with it, and the broker check above passed.

| Broker | Status |
|---|---|
| aliceblue | Not yet verified |
| angel | Not yet verified |
| arrow | Not yet verified |
| compositedge | Not yet verified |
| definedge | Not yet verified |
| deltaexchange | Not yet verified |
| dhan | Not yet verified |
| dhan_sandbox | Not yet verified |
| firstock | Not yet verified |
| fivepaisa | Not yet verified |
| fivepaisaxts | Not yet verified |
| flattrade | Not yet verified |
| fyers | Not yet verified |
| groww | Not yet verified |
| hdfcsecurities | Not yet verified |
| hdfcsky | Not yet verified |
| ibulls | Not yet verified |
| iifl | Not yet verified |
| iiflcapital | Not yet verified |
| indmoney | Not yet verified |
| jainamxts | Not yet verified |
| kotak | Not yet verified |
| motilal | Not yet verified |
| mstock | Not yet verified |
| nubra | Not yet verified |
| paytm | Not yet verified |
| pocketful | Not yet verified |
| rmoney | Not yet verified |
| samco | Not yet verified |
| shoonya | Not yet verified |
| tradejini | Not yet verified |
| tradesmart | Not yet verified |
| upstox | Not yet verified |
| wisdom | Not yet verified |
| zebu | Not yet verified |
| zerodha | Not yet verified |

**How to report a result.** Open an issue at
https://github.com/marketcalls/openalgo/issues titled
`gthread verified: <broker>` (or `gthread problem: <broker>`), and include:

- the table printed by `scripts/gthread_broker_smoke.py --repeat 3 --parallel 4`;
- the *Runtime* section of the system report;
- whether you ran a full trading day, and with what (strategies, Flow,
  TradingView alerts, the scalping terminal);
- anything unusual from `log/errors.jsonl` (remove anything private first).

Never post your API key, broker credentials or `.env`.
