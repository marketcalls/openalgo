# Windows Desktop Installation

For the TinyCompute team installing and supporting FastAlgo on a client's
Windows PC. The design and its reasons are in
[2026-11-05-desktop-panel-and-reset-plan.md](../../plans/2026-11-05-desktop-panel-and-reset-plan.md).

## Build a release

On a development machine, with the frontend built and the work committed:

```sh
uv run python scripts/build_release.py
```

This writes `release/FastAlgo-<version>.zip` and a `.sha256` file beside it.
`release/` is gitignored; upload the zip wherever clients download from.

- The zip holds the source exactly as Git tracks it, plus the built
  `frontend/dist`. It never contains `.git`, `.env`, databases or logs.
- `app/RELEASE_FILES` lists every shipped file. The reset uses it to tell the
  client's data apart from the program, so never hand-edit a release.
- The build runs `scripts/brand-check.mjs` when Node.js is present and stops if
  it fails.
- `--allow-dirty` builds from uncommitted work. Use it for test builds only.

## Install on a client PC

1. Download the zip, right-click it, and choose **Extract All**.
2. Double-click **Install FastAlgo.cmd**. Allow 3 to 10 minutes, mostly for the
   download. Windows asks "Yes" once, to allow the server through the firewall on
   Private networks.
3. The control panel opens and shows **Not set up yet**. Click **Set up your
   broker**, choose the broker, and enter its API key and secret. XTS brokers
   also need the market data pair.
4. In the broker's developer portal, set the redirect URL the panel shows.
5. Start FastAlgo from the panel, create the login, and log in to the broker.

If the internet drops during step 2, double-click the installer again. It
continues where it stopped and reuses everything already downloaded.

## What goes where

| Path | What it is |
| --- | --- |
| `C:\FastAlgo\app` | The source code. Inspect it freely. |
| `C:\FastAlgo\app\.venv` | Dependencies. Rebuilt by **Repair dependencies**. |
| `C:\FastAlgo\python` | A private Python 3.12, installed by uv. |
| `C:\FastAlgo\cache` | Download cache. Makes re-runs and repairs fast. Safe to delete. |
| `C:\FastAlgo\run` | Keeper state: `status.json`, `keeper.log`, `server.json`, locks. |
| `C:\FastAlgo\backups` | A zip from every reset (the last 5 are kept). |
| `C:\FastAlgo\panel.json` | Panel options (auto-restart, keep awake, start at sign-in). |
| `C:\FastAlgo\install.log` | Every installer run, for support. |
| `C:\FastAlgo\install.ok` | Written when the install finishes. Without it the panel offers **Finish installation**. |

## Where to look when something is wrong

1. **The panel.** Its status line gives the cause and the next step. The log
   pane shows the newest server log.
2. **`C:\FastAlgo\run\keeper.log`.** Every start, stop, crash, restart and missed
   health check, one line each, in plain words.
3. **`C:\FastAlgo\app\log\server-<date>.log`.** The server's own output (the last
   10 are kept).
4. **`C:\FastAlgo\app\log\errors.jsonl`.** Every error with its traceback.

The same controls work from a prompt, which helps on a remote session:

```bat
cd C:\FastAlgo\app
..\python\cpython-3.12*\python.exe -m launcher.control --home C:\FastAlgo status
..\python\cpython-3.12*\python.exe -m launcher.control --home C:\FastAlgo stop
..\python\cpython-3.12*\python.exe -m launcher.eject --dry-run
```

## How it stays up

- **The panel owns nothing.** Closing it never stops trading.
- **The keeper runs the server, with no window.**
  - It restarts the server after a crash. It waits 2, 5, 10, 30, then 60 seconds
    between tries, and gives up after 5 crashes in 10 minutes.
  - It restarts the server if `/health/status` misses four checks in a row.
  - It keeps the PC from idle sleep. A closed laptop lid still sleeps, so a client
    who needs guaranteed auto square-off belongs on a server, not a laptop.
- **Stop ends the server and every strategy process it started**, using a
  Windows job object.
- **A keeper that dies leaves the server running.** The panel then shows
  **Running without supervision**, and **Start** takes the server over.

## Switching broker (reset)

**Switch broker** in the panel (or `python -m launcher.eject --broker <name>`)
returns the install to a fresh state for a new broker:

- **Removed, after a backup zip:** the login, settings, orders, logs, keys and
  Flow workflows.
- **Kept:** the program and its dependencies.
- **Kept by default, removable with a checkbox:** scripts and chart indicators,
  and downloaded historical data.

Stop FastAlgo first. The reset refuses while it runs, and rolls everything back
if any file is still in use.

## Other devices on the network

Allowed by default. The panel shows the address to type on a phone, for example
`http://192.168.1.20:5000`. Turn it off with **Allow phones and other computers on
my network**.

- It works on networks Windows marks as Private, not Public ones such as a
  cafe or hotel.
- The broker login must be done on the PC itself, because the broker sends the
  login back to `127.0.0.1`.
