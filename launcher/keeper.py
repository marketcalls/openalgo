"""The keeper: runs the FastAlgo server and keeps it running.

Started by the panel as a detached background process with no window:

    pythonw -m launcher.keeper --home C:\\FastAlgo

What it does (``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``, M3.3):

- Starts ``app.py`` in desktop mode (``utils/desktop.py``): no window, stdin
  from the null device, output to a dated file in ``app\\log``, never a pipe.
- Puts the server in a **named Windows job object**. Strategy processes the
  server starts land in the same job, so one call ends the whole tree. The job
  does not kill on close, so a keeper that dies leaves the server running, and
  a new keeper reopens the job by name and takes the server over.
- Restarts the server when it exits on its own, waiting 2, 5, 10, 30 and 60
  seconds between tries, and gives up after 5 crashes in 10 minutes: a server
  that cannot start (a port taken, a broken setting) only fills the log.
- Restarts it when it hangs: ``/health/status`` is polled every 15 seconds
  after a 90 second start-up grace, and four misses in a row count as a hang.
- Keeps the PC from idle sleep while the server runs.
- Reports everything in ``run\\status.json``, the panel's only input.

The panel talks to it through files in ``run\\`` (``launcher.control``), so a
person on a support call can read the same state by opening the folder.

Standard library only; see ``launcher/__init__.py``.
"""

import argparse
import contextlib
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # run as a file rather than with -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher import envfile
from launcher.branding import display_name

IS_WINDOWS = sys.platform == "win32"

#: How many server log files to keep in app\log.
KEEP_SERVER_LOGS = 10

#: Keeper's own log is rotated once it passes this size.
KEEPER_LOG_MAX = 1_000_000


# --- paths and settings ------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    """Where everything lives. ``home`` is C:\\FastAlgo; ``app`` is the source tree."""

    home: Path
    app: Path

    @property
    def run(self) -> Path:
        return self.home / "run"

    @property
    def status(self) -> Path:
        return self.run / "status.json"

    @property
    def command(self) -> Path:
        return self.run / "command"

    @property
    def stop_request(self) -> Path:
        return self.run / "stop.request"

    @property
    def server_pid(self) -> Path:
        return self.run / "server.json"

    @property
    def lock(self) -> Path:
        return self.run / "keeper.lock"

    @property
    def keeper_log(self) -> Path:
        return self.run / "keeper.log"

    @property
    def settings(self) -> Path:
        return self.home / "panel.json"

    @property
    def server_logs(self) -> Path:
        return self.app / "log"

    @property
    def python(self) -> Path:
        venv = self.app / ".venv"
        return venv / "Scripts" / "python.exe" if IS_WINDOWS else venv / "bin" / "python"

    @property
    def job_name(self) -> str:
        digest = hashlib.sha1(str(self.home.resolve()).lower().encode()).hexdigest()[:12]
        return f"Local\\FastAlgoServer-{digest}"


def paths_for(home: Path, app: Path | None = None) -> Paths:
    return Paths(home=home.resolve(), app=(app or home / "app").resolve())


DEFAULT_SETTINGS = {"auto_restart": True, "keep_awake": True, "start_at_login": False}


def read_settings(paths: Paths) -> dict:
    """``panel.json`` over the defaults. A missing or broken file means the defaults."""
    settings = dict(DEFAULT_SETTINGS)
    with contextlib.suppress(OSError, ValueError):
        loaded = json.loads(paths.settings.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            settings.update({k: v for k, v in loaded.items() if k in DEFAULT_SETTINGS})
    return settings


def server_ports(paths: Paths) -> dict[str, int]:
    """The ports the server will use, from app\\.env."""
    values = {}
    with contextlib.suppress(OSError):
        values = envfile.read_values(
            (paths.app / ".env").read_text(encoding="utf-8", errors="replace")
        )
    ports = {}
    for key, default in (("FLASK_PORT", 5000), ("WEBSOCKET_PORT", 8765), ("ZMQ_PORT", 5555)):
        try:
            ports[key] = int(values.get(key, default))
        except ValueError:
            ports[key] = default
    return ports


def write_json(path: Path, data: dict) -> None:
    """Write atomically, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- the single-instance lock -------------------------------------------------


class InstanceLock:
    """A lock on ``run\\keeper.lock`` that the OS releases when this process dies.

    No PID file to go stale: a keeper killed outright cannot leave it held.
    """

    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")  # noqa: SIM115 - held for the process lifetime
        try:
            if IS_WINDOWS:
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def release(self) -> None:
        if self._file is None:
            return
        with contextlib.suppress(OSError):
            if IS_WINDOWS:
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._file.close()
        self._file = None


def keeper_running(paths: Paths) -> bool:
    """True when a keeper holds the lock. Takes and drops the lock to find out."""
    lock = InstanceLock(paths.lock)
    if lock.acquire():
        lock.release()
        return False
    return True


# --- Windows process plumbing ------------------------------------------------

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.OpenJobObjectW.restype = wintypes.HANDLE
    _k32.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.SetThreadExecutionState.restype = wintypes.DWORD
    _k32.SetThreadExecutionState.argtypes = (wintypes.DWORD,)

    _JOB_ALL_ACCESS = 0x1F001F
    _SYNCHRONIZE = 0x00100000
    _QUERY_LIMITED = 0x1000
    _STILL_ACTIVE = 259
    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001


class Job:
    """The named job object the server and its children run in. Windows only; a no-op elsewhere."""

    def __init__(self, name: str):
        self.name = name
        self.handle = None
        if IS_WINDOWS:
            # Opens the existing job if a previous keeper left one behind.
            self.handle = _k32.CreateJobObjectW(None, name)

    def assign(self, process_handle) -> bool:
        if not self.handle:
            return False
        return bool(_k32.AssignProcessToJobObject(self.handle, int(process_handle)))

    def terminate(self) -> bool:
        if not self.handle:
            return False
        return bool(_k32.TerminateJobObject(self.handle, 1))

    def close(self) -> None:
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


def process_start_time(pid: int) -> int | None:
    """When ``pid`` started, as an opaque number; None if it is not running.

    Stored beside the PID so a new keeper never adopts an unrelated process that
    was given the same PID after the server exited.
    """
    if IS_WINDOWS:
        handle = _k32.OpenProcess(_QUERY_LIMITED, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if (
                not _k32.GetExitCodeProcess(handle, ctypes.byref(code))
                or code.value != _STILL_ACTIVE
            ):
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            _k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().split()[21])
    except (OSError, ValueError, IndexError):
        return 0


class Server:
    """The running server: one we started (Popen) or one we adopted (PID only)."""

    def __init__(self, pid: int, started: int | None, popen: subprocess.Popen | None = None):
        self.pid = pid
        self.started = started
        self.popen = popen

    def alive(self) -> bool:
        if self.popen is not None:
            return self.popen.poll() is None
        return self.started is not None and process_start_time(self.pid) == self.started

    def exit_code(self) -> int | None:
        return self.popen.returncode if self.popen is not None else None

    def kill(self) -> None:
        if self.popen is not None:
            with contextlib.suppress(OSError):
                self.popen.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.popen.wait(timeout=10)
        elif IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.pid)], capture_output=True, timeout=30
            )
        else:
            with contextlib.suppress(OSError):
                os.killpg(self.pid, 9)


def keep_awake(on: bool) -> None:
    """Stop the PC idle-sleeping while the server runs. A closed lid still sleeps."""
    if IS_WINDOWS:
        flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
        _k32.SetThreadExecutionState(flags)


def port_owner(port: int) -> int | None:
    """The PID listening on ``port``, if Windows will say."""
    if not IS_WINDOWS:
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            with contextlib.suppress(ValueError):
                return int(parts[4])
    return None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


# --- the keeper --------------------------------------------------------------


@dataclass
class Timing:
    """Every interval the keeper uses. Tests shorten them; production uses these."""

    tick: float = 1.0
    start_grace: float = 90.0
    #: A server that has never answered is still starting, not hung, until this
    #: long. The first start on a new install compiles every module and took
    #: about two minutes on a development PC; a slow client PC takes longer.
    start_timeout: float = 300.0
    health_interval: float = 15.0
    health_timeout: float = 5.0
    health_misses: int = 4
    stop_timeout: float = 20.0
    port_wait: float = 30.0
    backoff: tuple = (2.0, 5.0, 10.0, 30.0, 60.0)
    crash_limit: int = 5
    crash_window: float = 600.0


@dataclass
class _State:
    restarts: int = 0
    crashes: list = field(default_factory=list)
    log_file: str = ""
    started_at: float = 0.0
    healthy: bool = False


class Keeper:
    def __init__(
        self, paths: Paths, command: list[str] | None = None, timing: Timing | None = None
    ):
        self.paths = paths
        self.command = command or [str(paths.python), "app.py"]
        self.timing = timing or Timing()
        self.settings = read_settings(paths)
        self.name = display_name(paths.app)
        self.job = Job(paths.job_name)
        self.server: Server | None = None
        self.state = _State()
        self.status_extra: dict = {}

    # status -------------------------------------------------------------

    def log(self, message: str) -> None:
        path = self.paths.keeper_log
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > KEEPER_LOG_MAX:
                os.replace(path, path.with_name(path.name + ".1"))
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

    def report(self, state: str, message: str, **extra) -> None:
        port = server_ports(self.paths)["FLASK_PORT"]
        data = {
            "state": state,
            "message": message,
            "keeper_pid": os.getpid(),
            "server_pid": self.server.pid if self.server else None,
            "port": port,
            "started_at": self.state.started_at or None,
            "restarts": self.state.restarts,
            "log_file": self.state.log_file,
            "updated_at": time.time(),
        }
        data.update(extra)
        write_json(self.paths.status, data)
        self.log(f"{state}: {message}")

    # commands -----------------------------------------------------------

    def take_command(self) -> str | None:
        try:
            text = self.paths.command.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return None
        with contextlib.suppress(OSError):
            self.paths.command.unlink()
        return text or None

    def wait(self, seconds: float) -> str | None:
        """Sleep in ticks, returning early with any command that arrives."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            command = self.take_command()
            if command:
                return command
            time.sleep(min(self.timing.tick, max(0.0, deadline - time.monotonic())))
        return None

    # server lifecycle ---------------------------------------------------

    def adopt(self) -> bool:
        record = read_json(self.paths.server_pid)
        if not record:
            return False
        pid, started = record.get("pid"), record.get("started")
        if not isinstance(pid, int) or process_start_time(pid) != started:
            with contextlib.suppress(OSError):
                self.paths.server_pid.unlink()
            return False
        self.server = Server(pid, started)
        self.state.log_file = record.get("log_file", "")
        self.state.started_at = record.get("started_at", time.time())
        self.state.healthy = True  # it was running before this keeper started
        self.log(f"adopted running server pid {pid}")
        return True

    def _rotate_server_logs(self) -> Path:
        logs = self.paths.server_logs
        logs.mkdir(parents=True, exist_ok=True)
        old = sorted(logs.glob("server-*.log"))[: -(KEEP_SERVER_LOGS - 1) or None]
        for path in old:
            with contextlib.suppress(OSError):
                path.unlink()
        return logs / f"server-{time.strftime('%Y%m%d-%H%M%S')}.log"

    def start_server(self) -> bool:
        """Start the server. False, with the status already reported, when it cannot."""
        ports = server_ports(self.paths)
        deadline = time.monotonic() + self.timing.port_wait
        while True:
            busy = [p for p in ports.values() if port_in_use(p)]
            if not busy:
                break
            if time.monotonic() >= deadline:
                owner = port_owner(busy[0])
                who = f" (process {owner})" if owner else ""
                self.report(
                    "error",
                    f"Port {busy[0]} is used by another program{who}. Close it, or choose another "
                    f"port in the panel, then start {self.name} again.",
                )
                return False
            if self.wait(1.0) == "stop":
                self.report("stopped", f"{self.name} is stopped.")
                return False

        with contextlib.suppress(OSError):
            self.paths.stop_request.unlink()
        log_path = self._rotate_server_logs()
        env = dict(os.environ)
        env.update(
            FASTALGO_DESKTOP="1",
            FASTALGO_STOP_FILE=str(self.paths.stop_request),
            PYTHONUNBUFFERED="1",
            PYTHONIOENCODING="utf-8",
        )
        flags = 0
        if IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        with open(log_path, "ab") as log_file:
            try:
                popen = subprocess.Popen(
                    self.command,
                    cwd=self.paths.app,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=flags,
                    start_new_session=not IS_WINDOWS,
                )
            except OSError as e:
                self.log(f"could not start server: {e}")
                self.report(
                    "error",
                    f"{self.name} could not be started: its Python environment is missing or broken. "
                    "Use Repair dependencies in the panel.",
                )
                return False
        if IS_WINDOWS and not self.job.assign(popen._handle):
            self.log(f"could not assign server to job (error {ctypes.get_last_error()})")
        started = process_start_time(popen.pid)
        self.server = Server(popen.pid, started, popen)
        self.state.log_file = str(log_path)
        self.state.started_at = time.time()
        self.state.healthy = False
        write_json(
            self.paths.server_pid,
            {
                "pid": popen.pid,
                "started": started,
                "log_file": str(log_path),
                "started_at": self.state.started_at,
            },
        )
        if self.settings["keep_awake"]:
            keep_awake(True)
        self.report("starting", f"{self.name} is starting.")
        return True

    def stop_server(self) -> None:
        """Ask the server to stop, then end the whole job if it has not within the timeout."""
        server = self.server
        if server is None:
            return
        self.report("stopping", f"{self.name} is stopping.")
        with contextlib.suppress(OSError):
            self.paths.stop_request.write_text("", encoding="utf-8")
        deadline = time.monotonic() + self.timing.stop_timeout
        while server.alive() and time.monotonic() < deadline:
            time.sleep(min(0.25, self.timing.tick))
        # Graceful or not, end anything left in the job: strategy processes
        # the server started outlive it otherwise.
        terminated = self.job.terminate()
        if server.alive():
            self.log("server did not stop in time; ending it")
            if not terminated:
                server.kill()
            end = time.monotonic() + 10
            while server.alive() and time.monotonic() < end:
                time.sleep(0.1)
        if server.popen is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                server.popen.wait(timeout=5)
        self.server = None
        keep_awake(False)
        for path in (self.paths.stop_request, self.paths.server_pid):
            with contextlib.suppress(OSError):
                path.unlink()

    def healthy(self) -> bool:
        port = server_ports(self.paths)["FLASK_PORT"]
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health/status", timeout=self.timing.health_timeout
            ) as response:
                return response.status == 200
        except Exception:
            return False

    def last_error(self) -> str:
        """The newest message in errors.jsonl, for the panel's detail line."""
        path = self.paths.server_logs / "errors.jsonl"
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 16384))
                lines = f.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        for line in reversed(lines):
            with contextlib.suppress(ValueError):
                entry = json.loads(line)
                if isinstance(entry, dict) and entry.get("message"):
                    return str(entry["message"])[:500]
        return ""

    # the loop ---------------------------------------------------------

    def run(self) -> int:
        lock = InstanceLock(self.paths.lock)
        if not lock.acquire():
            return 3  # another keeper is already running
        try:
            return self._run()
        except Exception as e:  # noqa: BLE001 - the keeper must report, not vanish
            self.log(f"keeper failed: {e!r}")
            self.report(
                "error",
                f"The {self.name} keeper stopped unexpectedly. {self.name} may still be running; "
                "open the panel to take it over.",
            )
            return 2
        finally:
            keep_awake(False)
            self.job.close()
            lock.release()

    def _run(self) -> int:
        with contextlib.suppress(OSError):
            self.paths.command.unlink()  # a command left from before this keeper is stale
        if not self.adopt() and not self.start_server():
            return 1
        if self.state.healthy:
            self.report("running", f"{self.name} is running.")
        misses = 0
        next_check = time.monotonic() + (0 if self.state.healthy else self.timing.start_grace)
        next_probe = time.monotonic()

        while True:
            command = self.take_command()
            if command == "stop":
                self.stop_server()
                self.report("stopped", f"{self.name} is stopped.")
                return 0
            if command == "restart":
                self.stop_server()
                if not self.start_server():
                    return 1
                misses, next_check = 0, time.monotonic() + self.timing.start_grace
                continue

            if not self.server.alive():
                code = self.server.exit_code()
                self.log(f"server exited on its own (code {code})")
                outcome = self.after_crash(f"{self.name} stopped unexpectedly.")
                if outcome is not None:
                    return outcome
                misses, next_check = 0, time.monotonic() + self.timing.start_grace
                continue

            now = time.monotonic()
            # Until it first answers, probe often so "running" shows promptly.
            if not self.state.healthy and now >= next_probe:
                next_probe = now + min(2.0, self.timing.health_interval)
                if self.healthy():
                    self.state.healthy = True
                    self.report("running", f"{self.name} is running.")
                    next_check = now + self.timing.health_interval
            if now >= next_check:
                next_check = now + self.timing.health_interval
                if self.healthy():
                    misses = 0
                    if not self.state.healthy:
                        self.state.healthy = True
                        self.report("running", f"{self.name} is running.")
                elif (
                    not self.state.healthy
                    and time.time() - self.state.started_at < self.timing.start_timeout
                ):
                    # Still starting: a slow first start is not a hang.
                    pass
                else:
                    misses += 1
                    self.log(f"health check missed ({misses}/{self.timing.health_misses})")
                    if misses >= self.timing.health_misses:
                        self.log("server is not answering; restarting it")
                        self.stop_server()
                        outcome = self.after_crash(
                            f"{self.name} stopped answering and was restarted."
                        )
                        if outcome is not None:
                            return outcome
                        misses, next_check = 0, time.monotonic() + self.timing.start_grace
                        continue
            time.sleep(self.timing.tick)

    def after_crash(self, what: str) -> int | None:
        """Wait and restart after a crash. Returns an exit code when the keeper should stop."""
        self.server = None
        keep_awake(False)
        with contextlib.suppress(OSError):
            self.paths.server_pid.unlink()
        now = time.monotonic()
        self.state.crashes = [
            t for t in self.state.crashes if now - t < self.timing.crash_window
        ] + [now]
        detail = self.last_error()

        if not self.settings["auto_restart"]:
            self.report(
                "crashed",
                f"{what} Automatic restart is off; start it from the panel.",
                last_error=detail,
            )
            return 1
        if len(self.state.crashes) >= self.timing.crash_limit:
            self.report(
                "crashed",
                f"{self.name} kept stopping, so it was not restarted again. The log has the reason; "
                "contact support if it does not start after you press Start.",
                last_error=detail,
            )
            return 1

        delay = self.timing.backoff[min(len(self.state.crashes), len(self.timing.backoff)) - 1]
        self.report("restarting", f"{what} Restarting in {delay:.0f} seconds.", last_error=detail)
        command = self.wait(delay)
        if command == "stop":
            self.report("stopped", f"{self.name} is stopped.")
            return 0
        self.state.restarts += 1
        if not self.start_server():
            return 1
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m launcher.keeper", description="Run and supervise the trading server."
    )
    parser.add_argument(
        "--home", type=Path, required=True, help="the install folder, for example C:\\FastAlgo"
    )
    parser.add_argument("--app", type=Path, help="the source folder (default: <home>\\app)")
    # Tests run the keeper against a stand-in server; never used by the panel.
    parser.add_argument("--command-json", help=argparse.SUPPRESS)
    parser.add_argument("--timing-json", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    command = json.loads(args.command_json) if args.command_json else None
    timing = Timing(**json.loads(args.timing_json)) if args.timing_json else None
    return Keeper(paths_for(args.home, args.app), command=command, timing=timing).run()


if __name__ == "__main__":
    sys.exit(main())
