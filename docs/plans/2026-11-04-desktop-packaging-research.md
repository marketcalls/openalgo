# Phase 3 Research: Desktop Packaging

Date: 2026-11-04. Status: research, for the owner's decision. Nothing here is built yet.

Superseded in part: the owner chose a desktop panel over a Windows service and
dropped macOS. See [2026-11-05-desktop-panel-and-reset-plan.md](2026-11-05-desktop-panel-and-reset-plan.md).
Section 2 (why the process dies) still applies.

Question: how do we ship FastAlgo as a desktop application with the least effort,
so that the Python process and `localhost` stay up, while keeping the source
folders on disk so logs and code can be inspected by hand?

## 1. Short answer

1. **The crash you see when wrapping `python app.py` is a known, one-line cause,
   not a packaging problem** (section 2). Fix the code first.
2. **Never let the window own the server.** The OS service manager starts the
   server, restarts it when it dies, and keeps it running when every window is
   closed. The "desktop app" is a shortcut that opens the browser at
   `http://127.0.0.1:5000`.
3. **Do not freeze the app** (PyInstaller, Nuitka). Ship the source folder, a
   standalone Python installed by `uv`, and the locked environment. Logs, the
   database and the code stay in plain folders anyone can open.
4. **Start with an install script, not an installer.** The team installs every
   client, so a PowerShell script that does the five install steps is the
   minimum. A click-through installer can come later.

## 2. Why the process dies when wrapped

Verified on this machine unless marked otherwise.

| # | Cause | Evidence | Fix |
| --- | --- | --- | --- |
| A | **Werkzeug refuses to start when stdin is not a terminal.** `app.py:1268` calls `socketio.run(...)` in threading mode (`extensions.py:8`) without `allow_unsafe_werkzeug`. Flask-SocketIO 5.6.1 raises `RuntimeError: The Werkzeug web server is not designed to run in production` when `sys.stdin` is not a TTY (`flask_socketio/__init__.py:662-667`). Electron, Tauri, Node and most launchers give the child a pipe for stdin, so the app prints its banner and exits. | Reproduced: a minimal Flask-SocketIO app started with a piped stdin crashes with that error, and starts with `allow_unsafe_werkzeug=True`. | Pass `allow_unsafe_werkzeug=True`, gated on a desktop setting such as `FASTALGO_DESKTOP=1`. The threading server is what every dev run already uses; for one user on loopback it is the right server (see 5.3). |
| B | **An interactive prompt at startup.** When `.env` is older than `.sample.env`, `utils/env_check.py:211` calls `input("Continue anyway? (y/N)")`. With no terminal this reads EOF, returns False, and the app exits. | Code read. | Never prompt in desktop mode: log the warning and continue, or fail with a clear message in the log. |
| C | **A launcher that never reads the output pipe.** All logging goes to the console (`utils/logging.py:472`). If a wrapper captures stdout with a pipe and does not drain it, the server blocks once the pipe buffer fills: it looks alive but stops answering. | Code read; standard OS behaviour. | The supervisor writes stdout and stderr to a log file, never a pipe. |
| D | **The window kills the server.** Closing a console sends `CTRL_CLOSE_EVENT` to every process attached to it, and a child in its parent's kill-on-close job object dies with the parent. Tauri does not supervise or restart sidecars at all. | Sources below. | Do not make the server a child of any window. The service manager owns it. |
| E | **Debug mode tracks the wrong process.** With `FLASK_DEBUG` on, Werkzeug's reloader runs the real server in a child (`app.py:1149`), so a launcher watches a parent that does no work. | Code read. | Force `FLASK_DEBUG=False` in desktop mode. |
| F | **Leftovers from a previous run.** A hard kill runs no cleanup, strategy subprocesses are not in a job object, and the WebSocket proxy then fails with "port 8765 is already in use" (9 occurrences in `log/errors.jsonl`). | Log and code read. | Graceful stop (5.2), plus a start-up check that frees our own stale ports and strategy PIDs. |
| G | **A read-only program folder.** `log/`, `db/`, `strategies/`, `keys/` and `.env` are all written relative to the working directory or the repo (`utils/logging.py:500`, `app.py:21-26`, `utils/env_check.py:1009`). Installed under `C:\Program Files`, start-up fails. | Code read. | Install to a folder the client's user can write (section 4). |

A, B and E are why "it works in my terminal and dies in the wrapper". Fixing
them is a small code change and needs no new tooling.

## 3. Options compared

| Option | Effort | Survives a closed window | Restarts after a crash | Source and logs visible | Verdict |
| --- | --- | --- | --- | --- | --- |
| **OS service + browser shortcut** | Low | Yes, the window is just a browser tab | Yes, the service manager does it | Yes | **Recommended** |
| Tauri or Electron shell with a Python sidecar | High | Only if we write that logic | Only if we write that logic | Yes | Rejected: Tauri spawns sidecars but does not supervise them; crash detection, restart and kill-on-exit are all ours to build |
| pywebview window in the same process | Medium | No, closing the window ends the process | No | Yes | Rejected as the main design. A pywebview window that only displays the page, with the server still run as a service, is a possible later add-on |
| PyInstaller or Nuitka freeze | Medium, with ongoing breakage | Depends on the launcher | No | No | Rejected: the Python strategy host runs user scripts with `sys.executable` (`blueprints/python_strategy.py:516`), which a frozen app does not have; code is hidden inside the binary; frozen executables are often flagged by antivirus |

## 4. Recommended distribution layout

One folder per installation, writable by the client's Windows user, for example
`C:\FastAlgo` (not `C:\Program Files`):

```
C:\FastAlgo\
  app\            the repository as-is: source, .env, db\, log\, strategies\, keys\
  python\         standalone CPython 3.12, installed by uv (python-build-standalone)
  uv.exe          the uv binary, used to install and update
  service\        the service wrapper and its config, plus its own log
```

- **Keep the current relative layout for now.** The code expects `db/`, `log/`,
  `strategies/` and `.env` inside the app folder, and you want to open them by
  hand. Installing to a writable folder makes that work with no code change.
  Moving data out of the program folder (planned in the rebrand plan, section 6)
  can come later by pointing each `*_DATABASE_URL` and `LOG_DIR` at absolute
  paths. `.env` would still need a code change to move.
- **Python:** `uv python install 3.12` gives a standalone interpreter
  (python-build-standalone) that does not depend on anything installed on the
  machine. `uv sync --frozen` builds `.venv` from `uv.lock`, so every client gets
  identical dependency versions.
- **Updates:** stop the service, `git pull` (or copy a new release over `app\`),
  `uv sync --frozen`, run `upgrade\migrate_all.py`, start the service. That is the
  existing `install/update.bat` flow, minus the parts that assume a terminal.
- **Offline installs** (optional): `uv-pack` bundles the locked environment and a
  portable Python into one directory that installs without internet access.

## 5. The supervisor: keeping it alive

### 5.1 Per operating system

| OS | Supervisor | Key settings |
| --- | --- | --- |
| Windows | A Windows service, created with a service wrapper. Candidates: **WinSW** (one exe plus an XML file, widely used, scriptable), **Servy** (MIT, GUI and PowerShell, built-in health checks and pre/post hooks), NSSM (simplest, but reported unmaintained) | Restart on failure after a delay, stdout and stderr to rolling log files, working directory `C:\FastAlgo\app`, run as the client's own user account, start automatically at boot |
| macOS | A `launchd` LaunchAgent in `~/Library/LaunchAgents` | `KeepAlive` as a dictionary with `SuccessfulExit = false` (restart on crash, not on a deliberate stop), `ThrottleInterval` about 30 s against crash loops, program kept in the foreground |
| Linux | A `systemd` user service | `Restart=on-failure`, `RestartSec=5`, and `loginctl enable-linger` so it runs without anyone logged in |

Why a service rather than a "start at login" shortcut: it starts at boot without
a login, it has no console window to close, it restarts after a crash, and
Windows keeps it alive when the user signs out. Installing a service needs admin
rights, which the team has at install time.

### 5.2 Stopping cleanly

`utils/shutdown.py:233-263` already handles SIGINT, SIGTERM and, on Windows,
SIGBREAK: it stops the schedulers and the WebSocket proxy, and atexit stops
running strategies. The service wrapper must send one of those (Ctrl+C or
Ctrl+Break) and wait before force-killing; a force-kill skips all of it and
leaves orphaned strategies and port 8765 held (cause F). Confirm the chosen
wrapper's stop behaviour in M3.1.

### 5.3 The server itself

Stay on the threading Werkzeug server that `uv run app.py` uses today:

- gunicorn does not run on Windows, and eventlet is not installed in the desktop
  environment (it is only in `requirements-nginx.txt`).
- Waitress has no WebSocket support, which Flask-SocketIO needs here.
- For one user on `127.0.0.1` the threading server is adequate, and it is the
  mode the whole team already runs every day, so its behaviour is known.

### 5.4 Hangs, not just crashes

A service manager restarts a process that exits. It does not notice one that is
still running but no longer answers. Add a watchdog that polls
`GET /health/status` (no login needed, returns 503 on failure,
`blueprints/health.py:55-99`) every 30 s and restarts the service after three
failures in a row. Servy has this built in; with WinSW it is a small scheduled
script.

### 5.5 What a service cannot fix

- **Sleep.** A laptop that sleeps stops every scheduler. The sandbox square-off
  drops jobs missed by more than five minutes (`sandbox/squareoff_thread.py:344`).
  The install script should set the power plan so the machine never sleeps on
  mains power, and clients who need guaranteed square-off belong on a VPS.
- **Port conflicts.** macOS uses port 5000 for AirPlay Receiver. Pick a FastAlgo
  port per install and write it into `.env`.
- **Telegram chart images** need a Chrome or Chromium install for `kaleido`.

## 6. Proposed milestones

| ID | Milestone | Deliverable | Exit criteria |
| --- | --- | --- | --- |
| M3.1 | Desktop-safe start-up | `FASTALGO_DESKTOP=1` mode: `allow_unsafe_werkzeug=True`, no `input()` prompts, `FLASK_DEBUG` forced off, stale port and strategy-PID cleanup at start, hidden `reg query` window (`utils/logging.py:314-327`). Tests for each | `app.py` starts with stdin piped and with no console, and survives a pipe test like the one in section 2 |
| M3.2 | Windows service | Pick WinSW or Servy by testing both against M3.1. Service config with restart, log files, graceful stop and the health watchdog | Killing the process restarts it within 30 s; a hung process is restarted by the watchdog; stopping the service stops every strategy and frees port 8765 |
| M3.3 | Windows install script | `install-desktop.ps1`: install uv, Python 3.12, copy or clone the app, `uv sync --frozen`, write `.env`, register the service, set the power plan, add a desktop shortcut to `http://127.0.0.1:<port>`. Plus `update-desktop.ps1` | A clean Windows VM goes from nothing to a running FastAlgo with one command, and an update keeps data and settings |
| M3.4 | macOS and Linux | LaunchAgent and systemd user unit, with matching install scripts | Same exit criteria as M3.2 and M3.3 on each OS |
| M3.5 | Installer (optional) | An Inno Setup installer wrapping M3.3 | Only if clients will ever install without the team |

M3.1 is small and on its own fixes the crash you are seeing. M3.2 and M3.3 are
the minimum for a reliable Windows desktop install.

## 7. Decisions for the owner

1. **Service, or start at login?** Recommended: a Windows service. It starts at
   boot without a login and keeps running when the user signs out.
2. **Install folder:** `C:\FastAlgo` for every client, or under the user's
   profile (`%LOCALAPPDATA%\FastAlgo`)? `C:\FastAlgo` is easier to find when
   checking logs by hand.
3. **Which operating systems first?** Recommended: Windows only for M3.1 to M3.3,
   then macOS and Linux.
4. **Source delivery:** `git clone` from the private repository on each client
   (easy updates, needs a deploy key) or a copied release folder (no Git
   credentials on client machines)?

## Sources

- Tauri sidecar lifecycle (no supervision, restart with backoff, kill on exit): https://stuffbucket.github.io/skills/catalog/tauri-sidecar-lifecycle/
- Example Tauri v2 Python sidecar: https://github.com/dieharders/example-tauri-v2-python-server-sidecar/pull/8
- Servy, NSSM and WinSW compared (written by Servy's author): https://dev.to/aelassas/servy-vs-nssm-vs-winsw-2k46
- Servy repository: https://github.com/aelassas/servy
- python-build-standalone: https://gregoryszorc.com/docs/python-build-standalone/main/
- uv-pack (offline bundle of a locked uv environment): https://pypi.org/project/uv-pack/
- Console close and `DETACHED_PROCESS` on Windows: https://safe-exit.readthedocs.io/en/latest/_sources/recipes.rst.txt
- launchd `KeepAlive`, `SuccessfulExit` and `ThrottleInterval`: https://github.com/D0n9X1n/copilot-relay/wiki/EN-macOS-LaunchAgent and https://www.unix.com/man-page/osx/5/launchd.plist/
- Inno Setup per-user, no-admin installs: https://kinook.com/blog2/inno-setup.html
