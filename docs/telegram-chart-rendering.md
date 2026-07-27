# Telegram `/chart` rendering — architecture & operational notes

This document explains how the Telegram bot's `/chart` command renders Plotly
candlestick charts to PNG, why the implementation is more involved than a
one-line `fig.to_image()` call, and what operators need to know when running
openalgo on Docker, Ubuntu, Debian, RHEL/CentOS, Fedora, or Arch.

It also covers the non-obvious interaction between **Plotly's Kaleido 1.x
renderer**, **PTB's asyncio event loop**, and **gunicorn's eventlet worker** —
the triangular trap that caused `/chart` to fail in Docker and would fail
identically on a fresh bare-metal install without the workarounds described
below.

---

## 1. What the `/chart` command actually does

Defined in `services/telegram_bot_service.py` (`cmd_chart` at the bottom of the
file; helpers `_generate_intraday_chart` and `_generate_daily_chart` above it),
the command runs this pipeline:

1. Parse `symbol`, `exchange`, `chart_type`, `interval`, and `days` from the
   user's message.
2. Fetch OHLCV history via the OpenAlgo Python SDK
   (`client.history(symbol=..., exchange=..., interval=..., start_date=..., end_date=...)`).
3. Build a candlestick + volume figure with `plotly.graph_objects` and
   `plotly.subplots.make_subplots`.
4. **Convert the Plotly figure to PNG bytes** — `fig.to_image(format="png", engine="kaleido")`.
5. Send the PNG to Telegram via `reply_photo` (single chart) or `reply_media_group`
   (when `type=both` returns intraday + daily together).

Steps 1–3 are pure Python and work anywhere. **Step 4 is where everything
interesting happens**, and the rest of this document is about that step.

---

## 2. Why Chromium must be installed on the host (or in the container)

openalgo pins `kaleido==1.2.0` in `pyproject.toml`. Kaleido had a major
architectural change between v0.2.x and v1.x, and the switchover is the
single most common reason new openalgo installs see `/chart` silently fail:

| Kaleido version      | Chromium binary ships inside the wheel? | Runtime requirement |
| -------------------- | --------------------------------------- | ------------------- |
| `kaleido==0.2.1` (legacy) | **Yes** — static Chromium bundled, ~60 MB wheel | Nothing. Worked in any Docker image out of the box. |
| `kaleido==1.x` (current)  | **No** — pure Python bridge | A real Chromium/Chrome must be installed *separately* on the system, discoverable by `choreographer`. |

Under the hood, Kaleido 1.x uses the
[`choreographer`](https://pypi.org/project/choreographer/) library to drive a
headless Chromium over the Chrome DevTools Protocol. When you call
`fig.to_image(...)`, Kaleido:

1. Serializes the Plotly figure to JSON + HTML.
2. Spawns `/usr/bin/chromium` (or whatever browser `choreographer` finds) as a
   subprocess with `--headless --disable-gpu` and friends.
3. Loads the HTML, waits for Plotly.js to render, calls `Page.captureScreenshot`
   over CDP, and returns the PNG bytes.
4. Kills the subprocess.

**Every chart render launches a real headless Chromium for ~1–3 seconds.**
If Chromium isn't on the system, the subprocess spawn fails and
`fig.to_image()` raises — the generator catches it, logs
`Error generating intraday chart: ...`, and the bot replies with
`❌ Failed to generate charts for <symbol>`.

### Confirming Chromium is present

On Docker:

```bash
docker exec openalgo-web /usr/bin/chromium --version
# -> Chromium 120.0.6099.224 built on Debian 11.8, running on Debian 11.11
```

On bare metal:

```bash
which chromium || which chromium-browser
/usr/bin/chromium --version   # or /usr/bin/chromium-browser --version
```

You can also verify Kaleido's end-to-end path without touching Telegram at all:

```bash
# Docker
docker exec openalgo-web /app/.venv/bin/python -c '
import plotly.graph_objects as go
img = go.Figure(data=[go.Candlestick(
    x=[1,2], open=[100,102], high=[105,106], low=[99,101], close=[104,103]
)]).to_image(format="png", engine="kaleido")
print("PNG bytes:", len(img))
'
# -> PNG bytes: ~16000

# Bare metal
cd /path/to/openalgo
uv run python -c '... same snippet ...'
```

If that prints a byte count, Kaleido + Chromium + choreographer are healthy
and the `/chart` pipeline will work end-to-end. If it raises, the traceback
tells you exactly what's missing.

### Disk space cost

- Docker image grows by **~280 MB** when `chromium` + its runtime libs
  (`libnss3`, `libatk-bridge2.0-0`, `libcups2`, `libgbm1`, `libxkbcommon0`,
  `libgtk-3-0`, …) are installed via apt in the production stage of
  `Dockerfile`.
- Bare-metal installs see a similar ~280 MB increase depending on what's
  already on the host.

---

## 3. How each install path gets Chromium

### 3.1 Docker (`Dockerfile`)

The production stage's apt install block includes `chromium` and
`fonts-liberation`. Because `apt-get install -y --no-install-recommends
chromium` pulls every hard-dependency library automatically, you do **not**
need to list the shared libs individually — apt does the right thing. Two env
vars are also set for determinism:

```
BROWSER_PATH=/usr/bin/chromium
CHROME_BIN=/usr/bin/chromium
```

choreographer auto-discovers `/usr/bin/chromium` on `PATH` anyway, but being
explicit protects against future choreographer releases changing their
discovery logic.

Nothing in `start.sh` (the container entrypoint) needs Chromium-specific
configuration. It just runs migrations, starts the WebSocket proxy, then
execs gunicorn — all three pick up the already-installed Chromium via PATH
when the bot thread later calls `fig.to_image()`.

### 3.2 Bare-metal installers

Each of these scripts installs Chromium non-fatally — if the install fails
(e.g. the distro doesn't package it, network flake, snap not ready), the
rest of openalgo still installs and everything except `/chart` works:

| Script | Target | Block |
| --- | --- | --- |
| `install/install.sh` | General-purpose Ubuntu / Debian / Raspbian / RHEL / CentOS / Fedora / Amazon Linux / Arch | Per-distro `case` branch after main `apt-get install`/`dnf`/`pacman` |
| `install/install-multi.sh` | Multi-tenant bare metal (Ubuntu) | After the main `apt-get install` block |

Both try `chromium` first (real Debian package / Fedora main / Arch), then
fall back to `chromium-browser` on Ubuntu (which 19.10+ rewires to the snap).
Headless snap Chromium works — choreographer auto-detects `/snap/bin/chromium`.

### 3.3 Docker installers (`install/install-docker.sh`, `install/install-docker-multi-custom-ssl.sh`)

These scripts install **Docker tooling on the host** (Docker Engine, nginx,
certbot, UFW, git, …). They do **not** install Chromium on the host — the
openalgo container itself is what runs Chromium, and the container gets it
from the Dockerfile change described in §3.1. Do not add Chromium to the
host from these scripts; it would be wasted space.

### 3.4 `update.sh`

`install/update.sh` only updates Python packages inside the venv (`uv pip
install ...`), pulls new code, and restarts the systemd service. It does
**not** run `apt-get install` for system packages, so **an existing
bare-metal install that was set up before this fix will not automatically
get Chromium on `update.sh`**. Operators in that situation need one of:

```bash
# Debian / Raspbian
sudo apt-get install -y chromium fonts-liberation

# Ubuntu 19.10+ (snap)
sudo apt-get install -y chromium-browser fonts-liberation
# or:
sudo snap install chromium

# RHEL / CentOS / Fedora
sudo dnf install -y chromium liberation-fonts

# Arch
sudo pacman -S --needed chromium ttf-liberation
```

followed by:

```bash
sudo systemctl restart openalgo   # or whichever unit name install.sh created
```

The restart is only required so the existing gunicorn worker reloads
`services/telegram_bot_service.py` — the Python helper described in §5 is
already shipped with the code.

---

## 4. The real trap: `gunicorn --worker-class eventlet` + PTB + Kaleido 1.x

This is the subtle part that bit the first implementation, and the part that
every future contributor needs to understand before changing anything in
`services/telegram_bot_service.py`.

### 4.1 The error you'll see if you get this wrong

```
Error generating intraday chart: asyncio.run() cannot be called from a running event loop
  File "services/telegram_bot_service.py", line 275, in _generate_intraday_chart
    img_bytes = fig.to_image(format="png", engine="kaleido")
  File ".../plotly/io/_kaleido.py", line 398, in to_image
    img_bytes = kaleido.calc_fig_sync(...)
  File ".../kaleido/_sync_server.py", line 122, in run
    q.put(asyncio.run(func(*args, **kwargs)))
RuntimeError: asyncio.run() cannot be called from a running event loop
```

It happens **every time** `/chart` is invoked, 100% reproducible.

### 4.2 Why it happens

Three independent facts stack up to make this inevitable:

1. **Kaleido 1.x's `fig.to_image()` is a sync façade over an async core.**
   Internally it does `asyncio.run(calc_fig(fig, ...))` to launch Chromium via
   `choreographer`. Python 3.12 tightened `asyncio.run()` — it now refuses to
   start a new event loop on any thread that already has one running, and
   raises the error above.

2. **PTB (`python-telegram-bot`) command handlers run inside a real asyncio
   event loop.** In `telegram_bot_service.py`, that loop is created in the
   bot-start path:

   ```python
   loop = asyncio.new_event_loop()            # line ~583
   self.bot_loop = loop
   # ... application.run_polling() on this loop ...
   ```

   and runs on a thread the file explicitly creates with `original_threading`:

   ```python
   self.bot_thread = original_threading.Thread(target=..., daemon=True)
   self.bot_thread.start()                    # line ~773
   ```

   So every time `cmd_chart` executes, we're inside a live asyncio loop on
   `self.bot_thread`. If we call `fig.to_image()` from this thread, Kaleido's
   inner `asyncio.run()` blows up per (1).

3. **`loop.run_in_executor(None, ...)` does not save you under eventlet.**
   This is the non-obvious part, and where the original fix attempt failed.
   openalgo runs gunicorn with `--worker-class eventlet -w 1` — both in Docker
   (`start.sh`) and bare metal (`install.sh` systemd unit at line 1013–1019).
   eventlet monkey-patches `socket`, `time`, `select`, and — crucially —
   `threading.Thread`. Any thread spawned via stdlib `threading.Thread(...)`
   after the monkey-patch becomes a **greenlet on eventlet's hub**, not a real
   OS thread.

   The default executor of an asyncio loop is a
   `concurrent.futures.ThreadPoolExecutor`, which spawns its workers via
   `threading.Thread`. Under eventlet, those "workers" are greenlets. Greenlets
   are cooperatively scheduled on a single OS thread, and for our purposes they
   **share the asyncio loop's thread context** — so Kaleido's internal
   `asyncio.run()` still sees the PTB loop as "already running" and raises the
   same `RuntimeError`.

   Result: you can wrap `fig.to_image()` in
   `await asyncio.get_running_loop().run_in_executor(None, lambda: fig.to_image(...))`
   and it will fail with the *same* traceback as calling it directly. The
   "offload to another thread" trick that works on vanilla CPython is a no-op
   under eventlet+PTB in this codebase.

TL;DR: **`run_in_executor` is not a valid escape hatch here.** Don't reach for it.

### 4.3 Why the bot itself already solves a harder version of this problem

Look at the very top of `services/telegram_bot_service.py`:

```python
if "eventlet" in sys.modules:
    import eventlet
    original_threading = eventlet.patcher.original("threading")
else:
    import threading as original_threading
```

`eventlet.patcher.original("threading")` returns the **un-monkey-patched**
`threading` module — the real one, before eventlet touched it. `Thread`
objects created from this module spawn **genuine POSIX OS threads** that
eventlet's hub never schedules.

That's exactly how the file already isolates the PTB bot from eventlet:
`self.bot_thread` at line ~773 is `original_threading.Thread(...)`, so PTB
runs on a real OS thread with its own real asyncio loop, completely separate
from the eventlet hub that gunicorn uses for HTTP workers. The pattern is
already here — we just reuse it one layer deeper.

### 4.4 The fix: `_render_plotly_png`

Full implementation lives at `services/telegram_bot_service.py:112`. Shape:

```python
def _render_plotly_png(self, fig) -> bytes:
    """Render a Plotly figure to PNG bytes using Kaleido on a real OS thread."""
    import queue as _queue

    result_q = _queue.Queue()

    def _worker():
        try:
            result_q.put(("ok", fig.to_image(format="png", engine="kaleido")))
        except BaseException as exc:
            result_q.put(("err", exc))

    t = original_threading.Thread(
        target=_worker, daemon=True, name="openalgo-kaleido-render"
    )
    t.start()
    t.join()

    status, payload = result_q.get_nowait()
    if status == "err":
        raise payload
    return payload
```

What each piece is doing:

- **`original_threading.Thread`** — not stdlib `threading.Thread`. This
  guarantees we get a real OS thread, not an eventlet greenlet. The new
  thread has **no asyncio event loop running on it** (we never called
  `asyncio.new_event_loop()` for it), so Kaleido's inner `asyncio.run()`
  is free to create a fresh loop and use it.
- **`queue.Queue`** — thread-safe result passing. We wrap success and
  failure in a `(status, payload)` tuple so exceptions propagate back to
  the caller instead of getting lost in the worker thread.
- **`t.join()`** — the caller **blocks** until the render thread finishes.
  Yes, this briefly pauses the PTB event loop (for the duration of the
  Chromium render, typically 1–3 seconds). For a personal trading bot this
  is fine; no other Telegram commands are queued behind it in practice.
  The alternative (a proper async bridge via `asyncio.wrap_future`) would
  work but re-introduces asyncio primitives that we were explicitly trying
  to keep out of this path.
- **No `async` anywhere in the helper.** The method is a plain `def`. It's
  called from inside the `async def _generate_intraday_chart` /
  `_generate_daily_chart` functions, which is perfectly legal — Python
  doesn't complain about sync calls inside async functions, the event loop
  just pauses during them.

Both chart generators call this helper the same way:

```python
img_bytes = self._render_plotly_png(fig)
return img_bytes
```

Call sites: `services/telegram_bot_service.py:323` (intraday) and
`services/telegram_bot_service.py:499` (daily).

### 4.5 Rule of thumb for future contributors

Any code path in `services/telegram_bot_service.py` that wants to call a
synchronous library which itself uses `asyncio.run()` internally (Kaleido
1.x, some PDF libs, some browser-driver libs, …) **must** go through a
`original_threading.Thread` hop. The shortcut is:

- If it's I/O-bound (HTTP, DB, network) and the library uses
  `requests`/`httpx`/etc., `await self.bot_loop.run_in_executor(None, ...)`
  is **fine** — eventlet greenlets are perfectly happy doing I/O, and
  there's no nested `asyncio.run()` to worry about. This is what
  `client.history(...)` calls use throughout the file.
- If the library internally spawns its own asyncio loop (Kaleido 1.x,
  notably), `run_in_executor` is **not enough**. Reuse the
  `_render_plotly_png` pattern: `original_threading.Thread` + `queue.Queue`
  + `t.join()`.

If you find yourself writing `loop.run_in_executor(...)` for a non-I/O-bound
task in this file, stop and reconsider. The eventlet hub will eat your
abstraction.

---

## 5. Legacy files: `telegram_bot_service_fixed.py`, `telegram_bot_service_v2.py`

Both of these exist in `services/` and both contain the **unfixed** pattern:

```python
img_bytes = fig.to_image(format="png", engine="kaleido")
```

at what used to be call sites in their own copies of the intraday and daily
generators. They are **not imported anywhere in the runtime code path** —
`app.py`, `blueprints/telegram.py`, and `restx_api/telegram_bot.py` all
import `from services.telegram_bot_service import telegram_bot_service`,
the non-suffixed module. The backup files are dead code from earlier
refactors.

Recommended cleanup (not done automatically — operator's call):

```bash
git rm services/telegram_bot_service_fixed.py services/telegram_bot_service_v2.py
```

If you keep them around as reference, be aware that **they will not work
with Kaleido 1.x under eventlet** — do not switch imports back to them
without applying the same `_render_plotly_png` pattern.

---

## 6. Operator troubleshooting checklist

When `/chart RELIANCE` returns `❌ Failed to generate charts for RELIANCE`:

1. **Container/host logs first.**
   ```bash
   # Docker
   docker logs openalgo-web --since 5m | grep -E "telegram_bot_service|chart|kaleido|chromium"

   # Bare metal
   sudo journalctl -u openalgo --since "5 minutes ago" | grep -E "telegram_bot_service|chart|kaleido|chromium"
   ```
   The exact traceback will tell you which layer broke.

2. **Is Chromium installed?**
   ```bash
   # Docker
   docker exec openalgo-web /usr/bin/chromium --version

   # Bare metal
   chromium --version || chromium-browser --version || /snap/bin/chromium --version
   ```
   Missing binary → follow the relevant install command in §3.4.

3. **Is the asyncio helper in place?**
   ```bash
   grep -n "_render_plotly_png" services/telegram_bot_service.py
   ```
   You should see the helper definition (~line 112) **and** two call sites
   (~line 323 and ~line 499). If only the call sites are present, you're
   running a stale copy of the file — `git pull` and restart the service.

4. **Does the standalone Kaleido smoke test pass?**
   ```bash
   docker exec openalgo-web /app/.venv/bin/python -c '
   import plotly.graph_objects as go
   img = go.Figure(data=[go.Candlestick(
       x=[1,2], open=[100,102], high=[105,106], low=[99,101], close=[104,103]
   )]).to_image(format="png", engine="kaleido")
   print("PNG bytes:", len(img))
   '
   ```
   - Prints bytes → Kaleido + Chromium are fine; something is wrong in the
     telegram pipeline (symbol, broker API, history fetch).
   - `RuntimeError: asyncio.run() cannot be called from a running event loop`
     → you're running the test from inside an already-live asyncio loop (not
     the standard `-c` invocation; this should never happen from plain
     `python -c`, so something is seriously wrong — file a bug).
   - `Could not find ... chromium` / `FileNotFoundError` → Chromium install
     missing; see §3.
   - Hangs for 60+ seconds then times out → Chromium is present but cannot
     launch (sandbox issues, missing shared libs, GPU errors). Re-run with
     `CHROMIUM_FLAGS="--no-sandbox --disable-dev-shm-usage" ...` to narrow
     down.

5. **Check Kaleido and Plotly versions match what's in `pyproject.toml`.**
   ```bash
   docker exec openalgo-web /app/.venv/bin/python -c '
   import importlib.metadata as m
   print("plotly:", m.version("plotly"))
   print("kaleido:", m.version("kaleido"))
   print("choreographer:", m.version("choreographer"))
   '
   ```
   Expected: `plotly==6.6.0`, `kaleido==1.2.0`, `choreographer>=1.x`.

---

## 7. Reference: file paths touched by this subsystem

| Path | Role |
| --- | --- |
| `services/telegram_bot_service.py` | Bot implementation; `_render_plotly_png` helper at ~line 112; call sites at ~323 and ~499 |
| `Dockerfile` | Installs `chromium` + `fonts-liberation` in the production stage; sets `BROWSER_PATH` / `CHROME_BIN` env vars |
| `install/install.sh` | Bare-metal installer; Chromium install block in each distro `case` branch |
| `install/install-multi.sh` | Multi-tenant bare-metal installer; Chromium install block after main `apt-get install` |
| `install/update.sh` | In-place updater; does **not** touch system packages — operators must install Chromium manually when upgrading an old install |
| `pyproject.toml` | Pins `kaleido==1.2.0` and `plotly==6.6.0` |
| `services/telegram_bot_service_fixed.py` | Legacy backup — unused, contains unfixed pattern |
| `services/telegram_bot_service_v2.py` | Legacy backup — unused, contains unfixed pattern |

---

## 8. Future-proofing notes

- **`engine="kaleido"` is deprecated.** Kaleido prints:
  > Support for the 'engine' argument is deprecated and will be removed after
  > September 2025. Kaleido will be the only supported engine at that time.

  The argument is still honoured and required-free today. When Plotly drops
  it, drop the `engine=` keyword from the two `fig.to_image(...)` calls
  inside `_render_plotly_png` and the chart generators — Kaleido will be
  auto-selected. No other changes needed.

- **Moving off eventlet.** The gunicorn maintainers have deprecated the
  eventlet worker class (`install.sh` and `start.sh` both still use it for
  backward compatibility with how openalgo integrates Flask-SocketIO). If
  openalgo ever migrates to `gthread`, `gevent`, or `uvicorn`, the
  `original_threading` dance becomes unnecessary and the `_render_plotly_png`
  helper can be replaced with a plain
  `await asyncio.get_running_loop().run_in_executor(None, ...)`. Do **not**
  make that simplification while eventlet is still the worker class — it
  will reintroduce the `asyncio.run()` error documented in §4.2.

- **Replacing Kaleido with a different renderer.** If someone wants to swap
  Kaleido for `playwright`, `pyppeteer`, `matplotlib`, or a server-side
  rendering microservice, the contract for the new implementation is:
  1. Input: a Plotly `Figure`.
  2. Output: PNG bytes.
  3. Must be safe to call from inside a running asyncio loop on
     `self.bot_thread` under an eventlet-patched process.

  If (3) is hard to guarantee, wrap the new renderer in the same
  `original_threading.Thread` hop — the `_render_plotly_png` helper is a
  generic escape hatch, not Kaleido-specific.
