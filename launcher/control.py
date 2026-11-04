"""What the panel calls to start, stop and read the keeper.

Kept apart from the panel so it can be tested without a window, and so a support
person can drive it from a prompt:

    python -m launcher.control --home C:\\FastAlgo status
    python -m launcher.control --home C:\\FastAlgo start | stop | restart

Standard library only; see ``launcher/__init__.py``.
"""

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher.branding import display_name
from launcher.keeper import (
    IS_WINDOWS,
    Paths,
    keeper_running,
    paths_for,
    process_start_time,
    read_json,
)


def _background_python() -> str:
    """``pythonw.exe`` beside the running interpreter, so the keeper has no window."""
    exe = Path(sys.executable)
    if IS_WINDOWS:
        windowless = exe.with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return str(exe)


def status(paths: Paths) -> dict:
    """The keeper's last report, corrected for what is actually running now.

    ``status.json`` is written by the keeper, so if the keeper has died its last
    word may be "running". The truth is worked out from the lock and the
    server's PID record instead:

    - keeper running: its report stands.
    - no keeper, server alive: "unsupervised", FastAlgo works but nothing will
      restart it. Start takes it over.
    - no keeper, no server: "stopped", unless the keeper's last report said why
      it stopped (crashed, error), which is kept so the panel can show it.
    """
    name = display_name(paths.app)
    report = read_json(paths.status) or {"state": "stopped", "message": f"{name} is stopped."}
    if keeper_running(paths):
        report["supervised"] = True
        return report
    report["supervised"] = False
    record = read_json(paths.server_pid) or {}
    pid = record.get("pid")
    if isinstance(pid, int) and process_start_time(pid) == record.get("started"):
        report.update(
            state="unsupervised",
            message=f"{name} is running, but nothing will restart it if it stops. Press Start to fix this.",
            server_pid=pid,
        )
    elif report.get("state") not in ("crashed", "error", "stopped"):
        report.update(state="stopped", message=f"{name} is stopped.", server_pid=None)
    return report


def start(paths: Paths, timeout: float = 10.0, extra_args: tuple[str, ...] = ()) -> bool:
    """Start the keeper unless one is running. True once a keeper holds the lock."""
    if keeper_running(paths):
        return True
    paths.run.mkdir(parents=True, exist_ok=True)
    # By file path rather than -m: the keeper is part of this launcher, which
    # need not be the copy inside paths.app (it is in tests).
    keeper_file = Path(__file__).with_name("keeper.py")
    args = [
        _background_python(),
        str(keeper_file),
        "--home",
        str(paths.home),
        "--app",
        str(paths.app),
    ]
    args += list(extra_args)
    kwargs = {
        "cwd": paths.app,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if IS_WINDOWS:
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # Break away from any job the panel runs in, so closing the panel, or
        # whatever launched it, cannot take the keeper with it. Not every job
        # allows breaking away; then start inside it rather than not at all.
        try:
            subprocess.Popen(
                args, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs
            )
        except OSError:
            subprocess.Popen(args, creationflags=base, **kwargs)
    else:
        subprocess.Popen(args, start_new_session=True, **kwargs)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if keeper_running(paths):
            return True
        time.sleep(0.2)
    return False


def _send(paths: Paths, command: str) -> None:
    paths.run.mkdir(parents=True, exist_ok=True)
    tmp = paths.command.with_name("command.tmp")
    tmp.write_text(command, encoding="utf-8")
    os.replace(tmp, paths.command)


def stop(paths: Paths, timeout: float = 60.0) -> bool:
    """Stop FastAlgo. True once neither the keeper nor the server is running.

    A server running without a keeper is taken over first, so it is stopped
    the same careful way.
    """
    current = status(paths)
    if current["state"] == "unsupervised":
        start(paths)
    elif not current["supervised"]:
        return True
    _send(paths, "stop")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not keeper_running(paths):
            return status(paths)["state"] != "unsupervised"
        time.sleep(0.25)
    return False


def restart(paths: Paths) -> bool:
    if not status(paths)["supervised"]:
        return start(paths)
    _send(paths, "restart")
    return True


def wait_for(paths: Paths, states: set[str], timeout: float) -> dict:
    """Poll the status until it reaches one of ``states`` or the time runs out."""
    deadline = time.monotonic() + timeout
    current = status(paths)
    while current["state"] not in states and time.monotonic() < deadline:
        time.sleep(0.25)
        current = status(paths)
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m launcher.control")
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--app", type=Path)
    parser.add_argument("action", choices=("status", "start", "stop", "restart"))
    args = parser.parse_args(argv)
    paths = paths_for(args.home, args.app)
    ok = True
    if args.action == "start":
        ok = start(paths)
    elif args.action == "stop":
        ok = stop(paths)
    elif args.action == "restart":
        ok = restart(paths)
    with contextlib.suppress(OSError):
        print(json.dumps(status(paths), indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
