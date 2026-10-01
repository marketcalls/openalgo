# The gthread web server (optional)

OpenAlgo runs inside a web server called Gunicorn, and Gunicorn can run it in
two ways. **eventlet** is the default and stays the default. **gthread** is
opt-in: you choose it per installation, and nothing changes on your server
until you do. An update does not switch anything unless you have asked for
gthread in `.env`.

This page explains what gthread is, who should try it, how to switch on
Ubuntu and on Docker, how to check that it works, and how to switch back.

## What gthread is, and why it matters

- **eventlet** lets one request wait while others run, but some kinds of
  waiting can hold everything up. Several past problems, such as "the first
  order works, the next one hangs the app", came from eventlet and ordinary
  threads meeting inside OpenAlgo. Gunicorn has also announced that it will
  drop eventlet in its next major version.
- **gthread** gives every request its own thread from a fixed pool of 64, so
  one request waiting on a broker does not stop the others. It is not
  unlimited: a request that holds a thread for a long time still uses up one
  of the 64 (see [Known limits](#known-limits)).

Both run the same OpenAlgo. Orders, strategies, Flow, the charting and
scalping terminals, Telegram and WhatsApp alerts work the same way on either.

## Current status

- **Automated checks pass on every change**: tests on several Python
  versions, the web server starting on both eventlet and gthread, container
  builds for AMD64 and ARM64, and the frontend tests. They catch regressions;
  they do not certify every broker or promise days of uptime.
- **Verified on a live instance with Upstox**: a full trading day on 29
  September 2026 with no errors after login, the overnight login expiry and
  recovery after the next login, read-only broker calls passing under
  parallel load, and restarts completing in about 10 seconds.
- **Still wanted**: other brokers, more trading days, Docker and multi-instance
  installations running a full day, a rollback drill on a live instance, and
  Raspberry Pi hardware running a trading day.

## Installing with gthread

gthread is built into Gunicorn; there is no separate package to install. Keep
the project's pinned dependencies, including eventlet, so you can switch back.
Use a source checkout or container image that includes this page's version of
OpenAlgo; an older image cannot gain gthread just by setting the variable.

| Installation | How to select gthread |
|---|---|
| Fresh Ubuntu install with `install/install.sh` | Finish the normal installation (it installs on eventlet), then run the switch commands below. The installer has no worker question. |
| Fresh multi-instance install with `install/install-multi.sh` | Finish installation, then switch the instance you want with `--service openalgo1 --to gthread`, or every instance with `--all`. |
| Existing Ubuntu install made by either installer | Update OpenAlgo, then run `install/switch-worker.sh --to gthread`. |
| Docker Compose, including `install/install-docker.sh` | Set `OPENALGO_WORKER_CLASS = 'gthread'` in the mounted `.env`, set `stop_grace_period: 45s`, then rebuild and recreate the container. |
| Docker runners `install/docker-run.sh` and `install/docker-run.bat` | Use an image that includes this version, set the same `.env` line, then restart with the runner. The runners already allow 45 seconds to stop. |
| `uv run app.py` | This is the development server. It ignores the setting; use Ubuntu or Docker to run gthread. |

The single-instance installer also detects Debian, Raspbian, Arch and several
RPM-based distributions, and the same switch applies to the service it
creates. The multi-instance installer targets Ubuntu and Debian. The examples
below use Ubuntu and the default folders.

## Who should try it now

Try it if you:

- are comfortable running a few commands over SSH and reading a log;
- can switch at a quiet time, after 23:30 IST (see [When to switch](#when-to-switch));
- use a broker already verified on gthread (see the end of this page), or are
  happy to be the first to verify yours and report how it went.

Wait for now if you run strategies that must never pause, or if you run many
OpenAlgo instances on a small server: each gthread instance uses 64 request
threads.

## Before you start

### Platforms

| Computer | How to run OpenAlgo on gthread |
|---|---|
| Ubuntu desktop or server | The supplied installer and switch script, or Docker |
| Other Linux | Docker, or the installer's service on a distribution it detects. Check the service it creates; the automated checks run on Ubuntu. |
| Windows | `uv run app.py` ignores the setting. Use Docker, or Ubuntu inside WSL2. |
| macOS | `uv run app.py` ignores the setting. Use Docker; the Ubuntu scripts do not apply. |
| Raspberry Pi | A 64-bit Linux and ARM64 packages. The automated checks confirm it runs on ARM64; they do not measure a Pi's memory, heat or a full trading day. |

A computer running OpenAlgo must stay awake and keep its network connection.

### Running continuously

Use the service the installer created, or Docker's restart policy, so
OpenAlgo starts again after a reboot or a crash. Keep an eye on disk space for
databases, strategy output and logs. On a small computer, check memory with
the number of tabs, strategies and subscriptions you really intend to run.

Before relying on gthread for live trading, run it through a complete trading
day and the overnight broker login expiry. Check that market data reconnects
after the next login, scheduled jobs run, and memory stays level.

### Switch checklist

- **Update OpenAlgo first.** The files `install/openalgo-gunicorn.sh` and
  `install/switch-worker.sh` must be in your OpenAlgo folder.
- **Ubuntu:** the script only switches a service that `install.sh` or
  `install-multi.sh` created. If you edited the service's `ExecStart` line by
  hand, it leaves the service alone and tells you why.
- **Have your OpenAlgo API key ready** for the broker check at the end
  (generate one at `/apikey`).
- **Download the system report** before you switch, so you can compare: open
  **Admin**, then **Diagnostics**, and choose **Download .md**.

## When to switch

**After 23:30 IST and before 09:00 IST, never during the trading day.** The
trading day runs until 23:30 IST because of MCX's evening session. Switching
restarts OpenAlgo: orders already at your broker are not touched, but
strategies, the market data feed and open browser pages pause for up to a
minute.

The switch script refuses to restart OpenAlgo between 09:00 and 23:30 IST.
It goes by the clock, so it refuses on weekends and holidays too. Add
`--force` only when you are sure nothing is trading, for example on a new
installation with no strategies yet.

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

The script:

- writes `OPENALGO_WORKER_CLASS = 'gthread'` into `.env`;
- saves a copy of your service file next to it, as
  `/etc/systemd/system/openalgo.service.pre-launcher-<date>`;
- points the service at the launcher `install/openalgo-gunicorn.sh` and
  restarts OpenAlgo;
- checks that the service is running, the OpenAlgo page answers, the live
  update channel the browser uses answers, and OpenAlgo is running on the web
  server `.env` asks for.

If any check fails, it puts back the previous service file, restarts, checks
again and shows the last lines of the log. If that restart also fails, it says
so and prints the command to recover by hand; check it before you trade.

You can also edit `.env` yourself: add (or uncomment) the line
`OPENALGO_WORKER_CLASS = 'gthread'`, then run
`sudo bash install/switch-worker.sh` without `--to`.

**Updating later.** Keep using `sudo bash install/update.sh`. If `.env` asks
for gthread and the service does not use the launcher yet, the updater
switches it at the end, with the same checks and the same automatic restore.
If you update during the trading day, it tells you to run the switch again
after 23:30 IST.

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
together, 64 each. If your server limits how many processes or threads a
service may start, the launcher writes a warning into each instance's log when
the limit is too low for 64.

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
`/var/python/openalgo` (or an older layout under
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

3. After 23:30 IST, rebuild and restart:

   ```bash
   docker compose up -d --build --force-recreate
   ```

   `--build` matters. Without it Docker reuses the old image, which quietly
   keeps running on eventlet.

4. The container log shows
   `Starting application on port 5000 with gthread...`.

On Railway or another platform that sets environment variables for you, set
`OPENALGO_WORKER_CLASS=gthread` there instead, and set the platform's stop
timeout to 45 seconds if it has one.

**Stopping.** On gthread, a stop gives open requests up to 30 seconds to
finish, and running Python strategies and OpenScript runs are told to stop at
the same moment, so a strategy that handles the stop signal gets its chance to
clean up. Once OpenAlgo has finished, the market data service is stopped too,
within 5 seconds. Docker forces a container to stop 10 seconds after asking
it to, unless `stop_grace_period` says otherwise, so without step 2 a stop
cuts that cleanup short. Setting 45 seconds does not make a normal stop
slower: the container still stops as soon as OpenAlgo has finished. On
eventlet you can leave the line in place; it does no harm.

## Check that it works

1. **The system report.** Open **Admin**, then **Diagnostics**, and choose
   **Download .md**. Under *Runtime* it should say:
   - *Web server:* gthread
   - *Request threads:* 64
   - *Started by launcher:* True

   Any *Note* lines there are written for you, for example that `.env` asks
   for a web server this server has not switched to yet, or that almost every
   request slot is busy.

2. **The log.** `sudo journalctl -u openalgo -n 50` shows
   `Starting the gthread web server with 64 request threads`. On several
   instances use the instance's service name, for example `-u openalgo1`. On
   Docker use `docker compose logs --tail 50`.

3. **Your broker.** The broker check only reads (funds, positions, order
   book, trade book, holdings, quotes, multiquotes, depth, history and
   intervals) and prints a table of what passed and how long each call took.
   It needs nothing beyond the Python that comes with the server. Log in to
   OpenAlgo and your broker first: after about 03:00 IST the broker login has
   expired and every call fails.

   On Docker, run it on the server against the local address:

   ```bash
   cd /opt/openalgo
   python3 scripts/gthread_broker_smoke.py --url http://127.0.0.1:5000 --repeat 3 --parallel 4
   ```

   On Ubuntu OpenAlgo has no local address of its own, so run it on the
   server against your domain:

   ```bash
   cd /var/python/openalgo
   python3 scripts/gthread_broker_smoke.py --url https://your-openalgo-domain --repeat 3 --parallel 4
   ```

   It asks for your API key when you leave out `--apikey`, which keeps the key
   out of your shell history.

   **If every row says "answered 403"**, the check was stopped before it
   reached OpenAlgo, usually by Cloudflare, which turns away scripts that are
   not browsers. OpenAlgo has not failed. On the server, point your domain at
   the server itself for the run by adding a line
   `127.0.0.1 your-openalgo-domain` to `/etc/hosts`, run the check, then
   remove the line.

   Add `--order-check` only while OpenAlgo is in analyzer (sandbox) mode. It
   then places one small LIMIT buy far below the market in the sandbox (CNC on
   NSE and BSE, NRML elsewhere, so it works at any hour) and cancels it
   straight away. In live mode it refuses.

4. **The next trading day.** Keep an eye on the Diagnostics page and on the
   error log, `log/errors.jsonl` in your OpenAlgo folder. On Docker it lives
   inside the container:

   ```bash
   docker compose exec openalgo tail -n 50 /app/log/errors.jsonl
   ```

   If the report says almost every request slot is busy, see
   [Known limits](#known-limits).

## Switch back to eventlet

- **Ubuntu, after 23:30 IST:**

  ```bash
  sudo bash install/switch-worker.sh --to eventlet
  ```

  On several instances add `--service openalgo1`, or `--all`. You can also set
  `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` and restart the service
  (`sudo systemctl restart openalgo`, or the instance's name).
- **Put the original service file back entirely:**
  `sudo bash install/switch-worker.sh --restore` (again with `--service` or
  `--all` on several instances). It also sets `.env` back to eventlet, so the
  next update does not switch the service over again.
- **Going back to an older OpenAlgo release.** A switched service starts
  OpenAlgo through `install/openalgo-gunicorn.sh`, which older releases do not
  have. Run `sudo bash install/switch-worker.sh --restore` **first**, while
  the script is still there. A service switched with this release or later
  still starts if you forget: when the launcher is missing it starts OpenAlgo
  on eventlet exactly as before the switch, and says so in
  `journalctl -u openalgo`. A service switched with an earlier copy of the
  script cannot start after the rollback (systemd keeps restarting it); to
  give it the same safety net, run `--restore` and then switch again, outside
  market hours. If the service is already failing: in `/etc/systemd/system`, copy back
  the file named in the comment just above the service's `ExecStart` line (it
  ends in `.pre-launcher-<date>`), set `OPENALGO_WORKER_CLASS = 'eventlet'` in
  `.env`, then run `sudo systemctl daemon-reload` and restart the service.
- **Docker:** set `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` (or delete
  the line) and recreate the container.

Coming back to this version after an older one is safe for Historify: it
checks its internal ID counters every time it starts, and the database upgrade
does the same, so new watchlist symbols and downloads carry on where the older
version left off.

## Known limits

- **A fixed budget of 64 request threads per instance.** It is not a
  setting. Most requests take a thread for a moment, but some hold one for as
  long as they are open: each browser tab keeps one live update connection,
  shared by every page in it, and each open Python Strategies page, agent chat
  and remote MCP connection holds one while it is open. Five devices with two
  tabs each use about 10, plus one for each of those. If the system report
  says almost every request slot is busy, close tabs you are not using; if it
  keeps happening during trading, switch back to eventlet.
- **Stopping takes a little longer.** gthread lets open requests finish before
  it stops, for up to 30 seconds. On Docker this needs
  `stop_grace_period: 45s` (see [Switch on Docker](#switch-on-docker)).
- **The market data service** is shown in the system report as *Market data
  proxy*. On Ubuntu it runs as a separate process started by the web server,
  on gthread as on eventlet, and gthread starts it again if it stops. On
  Docker the container starts it and, on gthread, starts it again if it stops,
  after 1 second and then longer, up to 30 seconds, if it keeps stopping. The
  container log says when it does.
- **The development server is not affected.** `uv run app.py`, including on
  Windows, ignores this setting.

## What gthread refuses that eventlet waits for

Under eventlet some kinds of waiting simply take as long as they take.
gthread has a fixed number of request threads and waiting occupies one, so a
few waits are cut short instead, with a message saying what happened and what
to do. None of these is a setting, and none happens on eventlet.

- **A busy broker.** When a broker's rate limit would keep a request waiting
  more than about 10 seconds, the request is refused and nothing is sent to
  the broker. A smart order refused this way places nothing. An order that
  did reach the broker and then timed out is different: check your broker's
  order book before repeating it. In the Action Center, an order whose status
  is unclear may still be sending, especially a split or basket order.
- **Two orders for the same symbol at once.** A smart order or a sandbox
  order that waits more than 30 seconds for another one on the same symbol to
  finish is refused with a message asking you to try again. Check your
  positions first.
- **Switching between live and sandbox mode.** A switch that waits more than
  30 seconds for another switch still in progress is refused, and so is a
  sandbox reset behind one. A sandbox reset also stops the sandbox engines
  for the moment it takes and starts them again.
- **Reloading or clearing the symbol cache** while the master contract is
  still downloading is refused until the download finishes.
- **Flow workflows that wait.** A workflow whose Delay and Wait Until steps
  add up to more than 10 seconds runs in the background and answers at once;
  a shorter wait runs as before and answers with the result. Up to 16
  workflows waiting on a Delay, and separately up to 4 waiting on a Wait
  Until, can run at the same time; the next one is refused without placing any
  order, and the refusal appears in that workflow's execution history. Run Now
  on such a workflow shows it as running in the background.
- **Python Strategies page live status.** At most eight windows get live
  status at once. The next one shows "Too many windows are showing live
  strategy status" and still works, without live updates. An open page
  reconnects by itself every ten minutes.
- **Remote MCP and the agent.** At most four remote MCP streams stay open,
  each for up to five minutes, and at most eight MCP tool calls run at once.
  At most six agent chats stream at once, and one reply ends after 15 minutes.
- **OI Profile** spends at most 60 seconds loading the previous day's open
  interest for the daily change. If it runs out of time, the page says how
  many contracts it covered.
- **Email.** A mail server that does not answer within 20 seconds is
  reported as unreachable.
- **Sandbox square-off.** A square-off check that waits more than 120 seconds
  for one already running is skipped, and the next minute's check runs it.

**For API and webhook callers.** These refusals reach programs as HTTP status
codes: 429 for a busy broker, the Flow caps and the other limits above, 409
for a mode switch, sandbox reset or symbol cache reload that has to wait, 503
for the Python Strategies live status cap, and 202 when a waiting Flow
workflow has been accepted to run in the background. A caller that retries on
429 should wait before it does.

## Brokers verified on gthread

A broker moves to *Verified* once somebody has run a full trading day on
gthread with it and the broker check above passed.

| Broker | Status |
|---|---|
| upstox | Verified on 29 September 2026: a full trading day on a live instance, the overnight login expiry and recovery, and read-only broker calls passing under parallel load |

All other brokers are not yet verified: aliceblue, angel, arrow,
compositedge, definedge, deltaexchange, dhan, dhan_sandbox, firstock,
fivepaisa, fivepaisaxts, flattrade, fyers, groww, hdfcsecurities, hdfcsky,
ibulls, iifl, iiflcapital, indmoney, jainamxts, kotak, motilal, mstock, nubra,
paytm, pocketful, rmoney, samco, shoonya, tradejini, tradesmart, wisdom, zebu
and zerodha.

**How to report a result.** Open an issue at
https://github.com/marketcalls/openalgo/issues titled
`gthread verified: <broker>` (or `gthread problem: <broker>`), and include:

- the table printed by the broker check (`--repeat 3 --parallel 4`);
- the *Runtime* section of the system report;
- whether you ran a full trading day, and with what (strategies, Flow,
  TradingView alerts, the scalping terminal);
- anything unusual from `log/errors.jsonl`, with anything private removed.

**Never post your API key, broker credentials or `.env`.**
