# The gthread web server (optional)

OpenAlgo runs inside a web server called gunicorn, and gunicorn can run it in
two ways. **eventlet** is the default and stays the default: every install
uses it unless you change one line in `.env`. **gthread** is the other one.
This page explains what gthread is, who should try it, how to switch on
Ubuntu and on Docker, how to check that it works, and how to switch back.

Nothing on this page happens to your server by itself. An update does not
switch anything unless you have asked for gthread in `.env`.

## What gthread is, and why you might want it

- **eventlet** runs everything on one thread that takes turns between
  requests. It is what OpenAlgo has always used. gunicorn has announced that
  it will drop eventlet in its next major version, and several past problems
  ("the first order works, the next one hangs the app") came from eventlet
  and ordinary threads meeting inside OpenAlgo.
- **gthread** gives every request its own thread from a fixed pool of 64. It
  does not take turns, so one slow broker call cannot hold up everything
  else, and it avoids that whole family of problems.

Both run the same OpenAlgo. Orders, strategies, Flow, the charting and
scalping terminals, Telegram and WhatsApp alerts work the same way on either.

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

If any check fails, it puts the saved service file back, restarts OpenAlgo on
eventlet, checks it again, and shows you the last lines of the log. Your
server is then exactly as it was.

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

The updater does not find these instances by itself (it never has). Update
them as you do today, then run the switch script for each one.

## Switch on Docker

1. Add this line to the `.env` file next to your `docker-compose.yaml` (the
   one mounted into the container as `/app/.env`):

   ```
   OPENALGO_WORKER_CLASS = 'gthread'
   ```

2. After 23:30 IST, restart the container:

   ```bash
   docker compose up -d --force-recreate
   ```

3. The container log says
   `Starting application on port 5000 with gthread...`.

On Railway or another platform that sets environment variables for you, set
`OPENALGO_WORKER_CLASS=gthread` there instead.

**Stopping.** Docker gives a container 10 seconds to stop before it forces
it. On gthread OpenAlgo gives open requests 7 of those seconds to finish, so
a normal `docker compose down` or restart fits. Leave `stop_grace_period` at
its default or longer; do not shorten it below 10 seconds. A longer value is
harmless but does not give requests more time.

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

   It asks for your API key rather than taking it on the command line. Add
   `--order-check` only if OpenAlgo is in analyzer (sandbox) mode: it then
   places one small LIMIT buy far below the market in the sandbox and cancels
   it. In live mode it refuses.

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
  `sudo bash install/switch-worker.sh --restore`.
- **Docker:** set `OPENALGO_WORKER_CLASS = 'eventlet'` in `.env` (or delete
  the line) and recreate the container.

## Known limits

- **A fixed budget of 64 request threads per instance.** It is not a
  setting. Most requests take a thread for a moment, but some hold one for as
  long as they are open: each browser tab keeps two or three live update
  connections waiting, and each open Python strategy log view, agent chat and
  remote MCP connection holds one while it is open. Five devices with two
  tabs each use about 20 to 30. If the system report says almost every
  request slot is busy, close tabs you are not using; if it keeps happening
  during trading, switch back to eventlet.
- **Live update connections per tab.** Each tab currently opens two or three
  of them. A later release brings that down to one.
- **Stopping takes a little longer.** gthread lets open requests finish before
  it stops: up to 30 seconds on Ubuntu and 7 seconds on Docker.
- **Where the market data service runs** is shown in the system report as
  *Market data proxy*. On Ubuntu it runs as a separate process started by the
  web server, on gthread as on eventlet; if it stops, gthread starts it again
  after a short wait. On Docker the container starts it on its own.
- **The development server is not affected.** `uv run app.py` (including on
  Windows) ignores this setting; it only applies to gunicorn installs.

## What gthread refuses that eventlet waits for

Under eventlet a request that cannot go ahead yet simply waits, however long
that takes, while everything else waits behind it. gthread has a fixed number
of request threads, so a few kinds of waiting are cut short instead, and the
request is answered with a sentence saying what happened and when to try
again. None of these is a setting, and none of them happens on eventlet.

- **A busy broker.** When a broker's rate limit would keep a request waiting
  more than about 10 seconds, the request is refused (HTTP 429) and nothing is
  sent to the broker. A smart order refused this way places nothing.
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
