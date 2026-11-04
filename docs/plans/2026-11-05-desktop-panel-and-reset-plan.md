# Phase 3 Plan: Desktop Panel and Reset (Eject)

Date: 2026-11-05. Status: **built and tested, not yet committed** (M3.1 to M3.5; the owner
asked for one commit at the end of Phase 3). Where the zip is hosted is still open
(section 9); the zip is kept locally in `release/` for now. Operator guide:
[windows-desktop-installation.md](../installation-guidelines/getting-started/windows-desktop-installation.md).
Replaces the service-based recommendation in
[2026-11-04-desktop-packaging-research.md](2026-11-04-desktop-packaging-research.md)
(sections 3, 5 and 6). The crash analysis in that document (section 2) still holds
and is the basis of M3.1 below.

## 1. Decisions taken by the owner

- **Windows desktop first.** macOS is dropped. Linux comes later, as a server
  with no desktop app (a systemd unit or similar, decided then).
- **The source folder ships as-is.** We own and can read the actual code, logs
  and databases on every client machine. No freezing, no bundling into an exe.
- **No Windows service.** A light control panel in the style of XAMPP: start,
  stop, set the port, open the app, see the logs.
- **A reset ("eject") mode.** It returns the installation to the state of a fresh
  clone with dependencies installed, so a client can switch broker on a clean
  slate, and it never reinstalls dependencies. The client may keep their scripts
  and their historical data through it.
- **No Git on client machines.** Clients get a release zip with no `.git`
  folder and no repository details.
- **Other devices may connect.** Phones and other PCs on the same network can
  open FastAlgo, controlled by a panel checkbox that is on by default.
- **Install folder: `C:\FastAlgo`.**

## 2. The shape, in one picture

```
C:\FastAlgo\
  FastAlgo.lnk          shortcut: python\pythonw.exe app\launcher\panel.pyw
  uv.exe
  python\               CPython 3.12 installed by uv (includes tkinter)
  app\                  the source tree, exactly as released
    .venv\              dependencies, built once by `uv sync --frozen`
    launcher\           panel, keeper, reset, state manifest (new, in the repo)
    db\ log\ ...        runtime state, as today
  panel.json            panel settings: ports, auto-restart, keep-awake, autostart
  run\                  keeper.pid, server.pid, status.json, stop.request
  backups\              zip taken before every reset
```

Three processes, each with one job:

| Process | Runs as | Job | If it dies |
| --- | --- | --- | --- |
| **Panel** | `pythonw panel.pyw` (tkinter window) | Buttons and status. Owns nothing. | Nothing happens to the server. Reopen it and it reads `run\status.json`. |
| **Keeper** | `pythonw -m launcher.keeper`, detached, no window | Starts the server, restarts it on crash or hang, writes status and logs. | The server keeps running. The panel shows "running, unsupervised" and can start a new keeper that adopts it. |
| **Server** | `.venv\Scripts\python.exe app.py`, no window | FastAlgo itself, unchanged apart from M3.1. | The keeper restarts it. |

Why a keeper and not just the panel: closing a window must never stop trading,
and supervising from the window would make it stop. Why not a service: the owner
does not want one, and a detached per-user process gives the same restart
behaviour while the user is logged in, which is how a desktop is used.

**Panel and keeper use the standard library only** (tkinter, subprocess, ctypes,
urllib, json, zipfile, secrets) and run on the base Python, not the `.venv`. So
the panel still opens when the dependencies are broken, and can offer
"Repair dependencies" (runs `uv sync --frozen`).

## 3. M3.1: make the server safe to run without a terminal

Changes in the app, all behind `FASTALGO_DESKTOP=1`, which the keeper sets. The
production gunicorn path and the dev server are untouched.

| Cause (research doc, section 2) | Fix |
| --- | --- |
| A. Werkzeug refuses to start without a TTY | pass `allow_unsafe_werkzeug=True` to `socketio.run` (`app.py:1268`) |
| B. `input()` prompt on an old `.env` (`utils/env_check.py:211`) | do not prompt; log the warning and continue. The panel shows it from the log. |
| C. stdout pipe never drained | keeper writes stdout and stderr to a file, never a pipe; stdin is `DEVNULL` |
| E. debug reloader spawns a second process | force debug and the reloader off |
| Live prices fail from another device (section 6) | in desktop mode, answer the WebSocket config with the browser's own host instead of `127.0.0.1` |
| Graceful stop with no console to send Ctrl+Break to | a small thread polls `C:\FastAlgo\run\stop.request` once a second, calls the existing `utils.shutdown.shutdown_runtime()`, then exits 0 |

Done when: `app.py` started with stdin as a pipe and stdout to a file stays up,
serves `/health/status`, and exits cleanly within 20 s of `stop.request` appearing.
Tests run the server in a subprocess, as the eventlet tests already do.

Size: small. This alone fixes the crash you hit when wrapping `python app.py`.

**Done 2026-11-05.** `utils/desktop.py`, `test/test_desktop_mode.py`. Verified on the
real app: without desktop mode a piped stdin still crashes as before; with it the
server answers `/health/status` in about 8 s and stops on the stop file in about
2 s with all three ports released.

## 4. M3.2: the state manifest and the reset

**One file decides what is "state"**: `launcher/state.py`. Everything the
running app writes is listed there; everything else is the release. The reset
deletes state, and a future in-place update (M3.6) keeps it. One list serves both,
so they cannot disagree.

State, from the current tree:

| Path | What it holds | Reset |
| --- | --- | --- |
| `.env` | broker keys, `APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT`, ports | regenerated (below) |
| `db\*.db`, `*-wal`, `*-shm`, `*-journal` | user, auth tokens, orders, sandbox, Flow, strategies, settings, logs | deleted |
| `db\historify.duckdb` | downloaded historical candles | deleted, unless "Keep historical data" is ticked (default ticked) |
| `db\strategy_encryption.key`, `db\chatgpt_oauth\`, `db\backups\` | secrets tied to the old database | deleted |
| `keys\` | generated keys | deleted |
| `log\` (except `readme.md`) | logs, errors.jsonl, proxy stats | deleted |
| `strategies\scripts\`, `strategies\indicators\`, `strategies\strategy_configs.json` | the client's own scripts and chart indicators | anything not shipped in the release is deleted, unless "Keep my scripts and indicators" is ticked (default ticked) |
| `workspace\` (except shipped readmes) | notes, research, backtests | same rule |
| `tmp\`, `.numba_cache\`, `.llvm_tmp\` | caches | deleted |

Never touched: `.venv\`, `python\`, `uv.exe`, the source, `frontend\dist\`,
`custom_brand\` (the white-label belongs to the installation, not the client's
session), `panel.json`, `backups\`.

**"Shipped in the release"** is decided by `RELEASE_FILES`, a list of every file
in the release, written by the release build (M3.5). So a client's
`my_strategy.py` goes, the shipped `strategies\indicators\README.md` stays, with
no hand-kept exceptions.

**A guard test** walks the gitignore patterns and fails if any runtime path the
app can create is in neither list. That is what stops the next feature that adds
a database from surviving a reset unnoticed.

**The reset, step by step** (`launcher/eject.py`, also a CLI with `--dry-run`, so
it is usable by hand and on Linux later):

1. Refuse unless the server is stopped and ports 5000, 8765 and 5555 are free.
   SQLite files are locked on Windows while the app runs.
2. Show what will be removed, with sizes, and two checkboxes, both ticked by
   default: **Keep my scripts and indicators** (`strategies\scripts\`,
   `strategies\indicators\`) and **Keep historical data** (`db\historify.duckdb`).
   Switching broker does not need either gone, and losing them by accident is
   worse than clearing them by hand. Flow workflows and saved strategies live in
   the main database and always go; they are in the backup. The client types
   `RESET` to confirm.
3. Zip all state to `C:\FastAlgo\backups\before-reset-<timestamp>.zip`. Always,
   with no option to skip: the database holds the trade history a client may
   need for tax. Keep the last 5.
4. Delete the state paths.
5. Write a fresh `.env` from `.sample.env`, with new `APP_KEY` and
   `API_KEY_PEPPER` from `secrets.token_hex(32)` (as `install.sh` does), the
   network settings (ports, host, other-device access) carried over from the
   old `.env`, and **the new broker's name and keys**. `FERNET_SALT` is left as
   the placeholder, which the app already replaces on first start.
6. Start. The app creates empty databases on start as it does today. The client
   lands on `/setup`, creates the login, and logs in to the new broker, which
   downloads that broker's master contract.

**The reset asks for the new broker.** Found while testing M3.2 on a copy of a
real installation: the app refuses to start until `.env` names a broker
(`REDIRECT_URL` selects it, and the 5paisa, Flattrade and Dhan key formats are
checked at start-up). A reset that left no broker would leave an installation
that cannot start. So the reset dialog is really "Switch broker": choose the
broker, enter its API key and secret (and the market data pair for XTS
brokers). These are checked against the same rules as the start-up check
before anything is touched.

No dependency is reinstalled at any point, because `.venv` is never state.

**Why reset is in the panel and not in the web app:** it has to run while the
server is stopped, and a button in the app that deletes the app's own database
from under it is the wrong place for it.

Size: medium. The risk is in the list, so most of the work is the guard test and
testing against a copy of a real, used installation.

**Done 2026-11-05.** `launcher/state.py`, `launcher/envfile.py`,
`launcher/eject.py` (`python -m launcher.eject`), `test/test_launcher_reset.py`.
The state list was built from an inventory of every runtime writer, which also
found `logs/` (the Angel client), `~/` (LiteLLM tokens) and `agent_kill_switch`
outside the folders first listed. Rehearsed on a copy of a real development
installation: 93.5 MB of state removed and backed up, historical data kept,
the app started from the copy with no install step and came up with no users,
no broker session and no symbols. Paths outside the app folder that the app also
writes (system temp files for uploads and exports) are left to the OS.

## 5. M3.3: the keeper

- **Starts the server** with `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`,
  stdin `DEVNULL`, output to `app\log\server-<date>.log` (last 10 kept), env
  `FASTALGO_DESKTOP=1`.
- **Puts the server in a Windows job object, without kill-on-close.** Strategy
  subprocesses inherit it, so Stop can end the whole tree in one call
  (`TerminateJobObject`). And because the job does not kill on close, a crashed
  keeper does not take the server with it.
- **Stop:** write `stop.request`, wait up to 20 s for a clean exit, then
  terminate the job.
- **Restart on crash:** back off 2, 5, 10, 30, 60 s. After 5 crashes in 10
  minutes, stop trying and show "Stopped after repeated crashes, see log" with
  the last error from `log\errors.jsonl`. A crash loop on a taken port helps
  nobody.
- **Restart on hang:** poll `GET /health/status` every 15 s after a 90 s start-up
  grace. Four misses in a row means hung: terminate and restart.
- **Keep the PC awake** while the server runs (`SetThreadExecutionState`,
  default on). This stops idle sleep, not a closed lid; the panel says so.
- **Status** goes to `run\status.json` (state, PIDs, port, uptime, restarts,
  last error). That is the panel's only input, so it is debuggable by opening
  one file.
- **One keeper only:** a lock in `run\` with a PID check.

Size: medium.

**Done 2026-11-05.** `launcher/keeper.py`, `launcher/control.py`,
`test/test_launcher_keeper.py`. Verified with the real app: a server killed
outright was running again 13 s later, and Stop ended it in 3 s with the ports
released. Changed by testing: the first start on a new install took about two
minutes (every module compiled), past the hang limit, so a server that has never
answered now counts as starting until `start_timeout` (5 minutes), and as hung
only after that.

## 6. M3.4: the panel

One small window, no tray icon (a tray needs a third-party package):

- Status line: Stopped / Starting / Running on port 5000 / Restarting / Crashed.
- **Start, Stop, Restart. Open FastAlgo** (default browser on
  `http://127.0.0.1:<port>`).
- **Ports:** HTTP, WebSocket and ZMQ, editable only while stopped. Before saving,
  each is checked as free, and the owner of a taken port is named ("port 5000 is
  in use by python.exe, PID 1234"). Saving rewrites every `.env` key that
  carries a port: `FLASK_PORT`, `HOST_SERVER`, `REDIRECT_URL`,
  `CORS_ALLOWED_ORIGINS`, `WEBSOCKET_PORT`, `WEBSOCKET_URL`, `ZMQ_PORT`. Changing
  the HTTP port warns that the broker app's redirect URL must be changed at the
  broker too, or login breaks.
- **Logs:** the last 200 lines of the server log, refreshed, plus "Open log
  folder" and "Open install folder".
- **Options:** auto-restart (on), keep awake (on), start FastAlgo when I log in
  (a shortcut in the user's Startup folder that runs the keeper only).
- **Allow phones and other computers on my network** (on by default). Ticked, the
  server listens on all network cards (`FLASK_HOST_IP` and `WEBSOCKET_HOST` set
  to `0.0.0.0`), and the panel shows the address to type on the phone, for
  example `http://192.168.1.20:5000`. Unticked, only this PC (`127.0.0.1`).
  Changing it needs a restart, which the panel does. Details:
  - **A code fix is needed** (part of M3.1). The browser's live market data
    connection uses `WEBSOCKET_URL` from `.env` as is
    (`blueprints/websocket_example.py:199`, read by
    `frontend/src/lib/MarketDataManager.ts:388`). That says `127.0.0.1`, which on a
    phone means the phone. In desktop mode the server will answer with the host
    the browser actually used, so pages and live prices both work from another
    device. The SocketIO connection already uses the page's host.
  - **Windows Firewall:** the install script adds inbound rules for the HTTP and
    WebSocket ports on **Private** networks only. On a network Windows marks
    Public (cafe, hotel), other devices stay blocked even with the box ticked,
    and the panel says so.
  - **Broker login still happens on the PC.** The broker sends the login back to
    `REDIRECT_URL`, which is `127.0.0.1`. A phone can use everything else once
    the daily broker login is done on the PC.
  - **The connection is plain HTTP on the local network.** FastAlgo's own login
    still protects it. Encrypting it would need certificates and is not in this
    plan.
- **Reset to fresh install (switch broker)**, as in M3.2, behind its confirmation.
- **Repair dependencies:** runs `uv sync --frozen`, output into the log pane.

Every message is written for a trader, per `CLAUDE.md`: "Port 5000 is used by
another program", not an `OSError`.

Size: medium.

**Done 2026-11-05.** `launcher/panel.py`, `launcher/branding.py`,
`test/test_launcher_panel.py`, `test/test_launcher_network.py`. Driven against the
real app (Stopped, Running on port 5000, Stopped). Additions found while building:

- **First-run broker setup.** The installer leaves no `.env`, and the app will not
  start without a broker in it, so a new install opens on **Not set up yet** with a
  **Set up your broker** button: the switch-broker dialog without the reset.
- **Product name from the brand source.** Panel, keeper and reset messages read
  `PRODUCT_NAME` from `utils/brand.py` and the client's `custom_brand/brand.json`
  (`launcher/branding.py`), since the launcher cannot import the app.
- **DPI aware**, so the window is sharp at 125% and 150% display scaling.
- **tkinter needs the uv Python.** The project's development Python here has no
  Tk; the standalone 3.12 that uv installs does, and all launcher tests pass on it.

## 7. M3.5: install script and release zip

- **`scripts/build-release.ps1`** (ours, not the client's): `git archive` of the
  tag, plus the built `frontend\dist`, plus `RELEASE_FILES`, into
  `FastAlgo-<version>.zip`. No `.git`, no Git credentials on client machines.
- **`Install FastAlgo.cmd`** at the top of the zip, double-clicked by the client.
  It runs `install-desktop.ps1` past PowerShell's script policy (a `.ps1`
  double-clicked opens in Notepad). The script:
  1. Unblocks the files (Windows marks a downloaded zip and blocks its scripts).
  2. Downloads `uv.exe`.
  3. `uv python install 3.12` into `C:\FastAlgo\python`.
  4. Copies the source to `C:\FastAlgo\app`, then `uv sync --frozen`.
  5. Writes `.env` (the same function the reset uses) and `panel.json`.
  6. Adds the Private-network firewall rules. This is the one step that asks
     for admin rights (one Windows "Yes" prompt). Everything else is under
     `C:\FastAlgo` and needs none.
  7. Creates the desktop and Start menu shortcuts, opens the panel, starts the
     server and opens the browser.

Needs internet once, for `uv`, Python and the packages. Online install was
agreed on 2026-11-05.

### If the internet drops during install

The installer is built to be **run again**, not repaired. Double-clicking
`Install FastAlgo.cmd` a second time continues from where it stopped.

- **Every step checks before it acts.** If `uv.exe` is present and its checksum
  matches, the download is skipped. If Python 3.12 is already in `python\`, it
  is skipped. If `app\` is already copied, the copy is skipped.
- **Downloads land under a temporary name and are renamed only when complete.**
  A half-downloaded file is never mistaken for a whole one.
- **Packages are kept in our own cache,** `C:\FastAlgo\cache` (`UV_CACHE_DIR`).
  `uv sync` reuses every package already downloaded and fetches only the rest.
  A drop at 80% costs the last 20%, not the whole 300 to 500 MB. The one package
  that was mid-download starts over.
- **Short blips are absorbed.** The script sets `UV_HTTP_RETRIES=5` and a longer
  `UV_HTTP_TIMEOUT` for slow connections. Its own downloads (`uv.exe`) retry 3
  times, 10 s apart.
- **A longer drop stops the install with a sentence, not a stack trace:**
  "The internet connection dropped while downloading. Check your connection and
  double-click Install FastAlgo.cmd again. It will continue from where it
  stopped." The detail goes to `C:\FastAlgo\install.log`, which support can ask for.
- **Nothing half-installed ever starts.** The last step writes
  `C:\FastAlgo\install.ok`. Without it the shortcuts are not created, and if the
  panel is opened anyway it shows "Installation not finished" with a
  "Finish installation" button that runs the same script.
- **The same protection covers later use.** Repair dependencies in the panel,
  and updates (M3.6), go through the same `uv sync` and the same cache.

The cache stays after install (a few hundred MB) so repair and updates download
only what changed. The panel can offer "Clear download cache" if disk space is
ever a concern.

### What the client sees, from asking to dashboard

1. **We send a download link** to `FastAlgo-<version>.zip` (12.4 MB for 1.1.1).
   It holds the source and the built frontend, and nothing of Git. It is hosted
   wherever TinyCompute serves files from, behind a link only that client gets.
2. **The client downloads it,** right-clicks, Extract All.
3. **The client double-clicks `Install FastAlgo.cmd`.** A window shows progress
   for about 3 to 10 minutes, mostly the package download (about 300 to 500 MB).
   Windows asks "Yes" once, for the firewall.
4. **The panel opens by itself** and shows **Not set up yet**. A FastAlgo icon is
   now on the desktop for every later day.
5. **Set up your broker:** choose the broker and enter its API key and secret.
   The panel shows the redirect URL to put into the broker's developer portal, and
   offers to start.
6. **Open FastAlgo** in the default browser (Chrome, if it is the default), and
   create the FastAlgo login on the first-time setup page.
7. **Log in to the broker.** The dashboard opens, and the symbol list downloads
   in the background.

After a reset, the client repeats steps 6 and 7; the broker was chosen in the
reset dialog.

TinyCompute can do steps 2 to 7 on a remote-desktop call, which is likely how
most installs go.

Size: small to medium.

**Done 2026-11-05.** `install/desktop/install-desktop.ps1`, `install/desktop/Install.cmd`,
`scripts/build_release.py`. Rehearsed end to end from the built zip into a clean
folder: uv downloaded and checksum-verified, private Python 3.12.14, source copied,
dependencies installed, in 175 s; a second run took 2 s and skipped every finished
step; first-run broker setup, start, running and stop all worked from the
installed copy alone. Changed by testing:

- **`--no-dev`.** `uv sync` installs the `dev` group by default; clients get no
  test or audit tools. The panel's Repair uses the same command.
- **The firewall rule's program path comes from `.venv\pyvenv.cfg`.** The process
  that listens runs from uv's version folder (`cpython-3.12-...`), not the patch
  folder `uv python find` reports (`cpython-3.12.14-...`), and a rule matches the
  exact path. The shortcut uses the same path, which survives a patch upgrade.

**Not exercised in testing, to keep this PC unchanged:** the firewall rule itself
(it needs the Windows admin prompt), shortcuts on the real desktop, and a phone
on the network. These are the first things to check on a real client install.

## 8. Later

- **M3.6 Update in place:** unpack a new release over `app\`, keeping every path
  in the state manifest and `.venv`, then run `uv sync --frozen` (fast, since
  only changed packages download) and the database migrations
  (`upgrade/migrate_all.py`). Same manifest as the reset.
- **Restore from backup:** unzip a `before-reset` archive back. Cheap once M3.2
  exists.
- **Linux:** `launcher.keeper` and `launcher.eject` are plain Python CLIs with
  nothing Windows-only outside the job object and keep-awake calls, so a systemd
  unit can run the server, and the reset works from a shell.
- **Inno Setup installer**, only if clients ever install it themselves.

Order: M3.1, M3.2, M3.3, M3.4, M3.5. M3.1 and M3.2 can be used by hand before any
UI exists, which is how they get tested.

## 9. Questions

Answered on 2026-11-05: questions 1 and 2 (keep scripts and historical data, as
checkboxes), 3 (zip, no Git), 4 (external connections allowed, on by default) and
5 (`C:\FastAlgo`). They are folded into the sections above.

6. **Online install**, agreed. An offline zip can be added later if a client's
   network blocks the downloads; the installer would look for a `packages\`
   folder first.

Still open:

7. **Where is the zip hosted?** Any place that gives a private link works (S3 with
   an expiring link, Google Drive, our site). It does not change the plan.
