# Version 1.2.0 Released

**Date: 5th November 2026**

**Desktop release: FastAlgo installs on a Windows PC with a double-click, stays up on its own, and can switch broker on a clean slate.**

7 commits since 1.1.1. This release adds a complete Windows desktop
distribution next to the Ubuntu server install:

- **Server start-up:** the server now starts safely without a terminal.
- **The keeper:** a background program runs the server and restarts it after a
  crash or hang.
- **The control panel:** a small window for starting, stopping and setting up the
  server.
- **Switch broker:** a reset that clears the client's data while keeping the
  installed dependencies.
- **The installer:** a release zip with an installer that resumes after a dropped
  connection.

It also fixes a strategy delete that could target the wrong file.

No database migration, no new required setting and no change to the API, the
SDK or webhooks. The source stays a plain folder on disk, so the code and logs
can be read by hand on every client machine.

**Highlights**

- **Desktop-safe start-up (`c25aad6b7`)** - with `FASTALGO_DESKTOP=1`, set by the
  keeper:
  - the server no longer refuses to start without a terminal ("The Werkzeug web
    server is not designed to run in production"), which is the crash seen when
    wrapping `python app.py`;
  - an outdated `.env` logs a warning instead of waiting at a prompt;
  - the debug reloader stays off;
  - the server stops cleanly when the keeper asks.

  A phone on the same network now gets a WebSocket address it can reach, so live
  prices work there too. A terminal start, and production under gunicorn, are
  unchanged.
- **The keeper (`a8687e78c`)** - runs the server with no window and keeps it up.
  - **Crashes:** it restarts the server after a crash, with growing waits, and
    stops trying after 5 crashes in 10 minutes.
  - **Hangs:** it restarts a server that stops answering its health check. A first
    start is given 5 minutes before it counts as hung.
  - **Stopping:** Stop ends the server and every strategy process it started.
  - **Keeper failure:** if the keeper itself dies, the server keeps running and a
    new keeper takes it over.
  - **Sleep:** it keeps the PC from idle sleep while the server runs.
  - **Records:** it writes every event to `run\keeper.log` in plain words.
- **The control panel (`320a6959f`)** - one window that owns nothing, so closing
  it never stops trading.
  - **Server controls:** Start, Stop, Restart and Open FastAlgo, with the live
    status and the newest server log.
  - **Network:** port settings, and "Allow phones and other computers on my
    network" (on by default).
  - **Options:** restart automatically, keep the PC awake, and start at sign-in.
  - **Maintenance:** Switch broker and Repair dependencies.
  - **New installs:** a new install opens on "Set up your broker".
- **Switch broker, a reset to a fresh install (`30f42d0bd`)** - removes the login,
  settings, orders, logs and keys after zipping them to a backup.
  - **Kept:** the dependencies, so nothing is downloaded again.
  - **Kept by default, removable with a checkbox:** scripts, chart indicators and
    historical data.
  - **Safety:** it refuses while FastAlgo runs, and rolls everything back if any
    file is in use.
  - **The new broker:** it asks for the new broker and checks its keys against the
    same rules as start-up before touching anything.
  - **From a prompt:** also available as `python -m launcher.eject`.
- **Installer and release zip (`4b431e8d7`)** - `scripts/build_release.py` builds
  the release zip (12.4 MB). `Install FastAlgo.cmd` does the rest:
  - downloads uv and checks its checksum;
  - installs a private Python 3.12;
  - copies the source and installs the dependencies;
  - allows the server through Windows Firewall on Private networks;
  - creates the shortcuts.

  Running it again after a dropped connection continues where it stopped. A clean
  install took 175 seconds, and a second run 2 seconds.
- **Strategy delete fix (`1314c8a38`)** - deleting a `/python` strategy whose
  config had no script path tried to delete the app's own folder ("Access is
  denied: '.'"). A damaged config could have deleted any file it named. Delete now
  removes only a script inside `strategies/scripts`. The entry that exposed this
  had been written into the real config by two test fixtures, which now use a
  temporary folder.
- **Plan and research (`3c12dc016`)** - why the server died when wrapped, and the
  agreed desktop design.

**Upgrading**

- **Servers:** `git pull` on `main`. No migration is needed.
- **Windows desktop clients:** see the new
  [operator guide](../installation-guidelines/getting-started/windows-desktop-installation.md).

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - Phase 3 direction and decisions: the desktop panel over a
  Windows service, the broker reset and its keep options, access from other
  devices, and the online install. Also reported the strategy delete error
  (`3c12dc016`, `c25aad6b7`, `30f42d0bd`, `1314c8a38`, `a8687e78c`, `320a6959f`,
  `4b431e8d7`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
