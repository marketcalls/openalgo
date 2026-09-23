"""Boot smoke for OpenAlgo started through ``install/openalgo-gunicorn.sh``.

CI starts the real launcher with a throwaway ``.env`` and runs this against it,
once per web server (gthread and eventlet), so a change that stops either one
from booting, serving Socket.IO, streaming or stopping cleanly fails the build.
It is also safe to run by hand against a local test instance. It never logs
in to a broker and never places an order.

Checks, in order:

1. The app answers ``/auth/check-setup`` (waits up to ``--ready-timeout``).
2. ``/`` answers 200.
3. The Socket.IO polling handshake returns a session id.
4. A Socket.IO client connects over polling (the frontend's transport), and
   another over websocket and reports the websocket transport.
5. An SSE stream (``/python/api/events``) sends its first event within 5 s,
   using a session cookie signed with the instance's ``APP_KEY``.
6. While several streams and polling clients are held open, an ordinary
   request still answers within 2 s.
7. ``/admin/api/system`` reports the expected web server, thread budget and
   launcher.
8. The market data proxy listens on ``--proxy-port`` with the expected
   topology: ``child`` (a child process of the worker), ``thread`` (inside the
   worker), ``external`` (not under gunicorn at all) or ``any``.
9. With ``--pid`` and ``--stop-within``: SIGTERM to the gunicorn arbiter while
   a polling client, a stream and an idle keep-alive connection are open ends
   the process within that many seconds, and the proxy port is released.
10. With ``--log``: the gunicorn log has no traceback and no greenlet error.

Usage:
    .venv/bin/python scripts/gthread_smoke.py --base-url http://127.0.0.1:5099 \\
        --worker gthread --env-file .env --proxy-port 8799 --proxy child \\
        --pid "$GUNICORN_PID" --stop-within 45 --log gunicorn.log

Exit status 0 when every check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import sys
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

CONNECTED_EVENT = 'data: {"type": "connected"}'


class Smoke:
    """Collects check results and prints them as a table."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, float, str]] = []

    def check(self, name: str, fn: Callable[[], str]) -> bool:
        """Run one check. ``fn`` returns a detail string or raises."""
        started = time.monotonic()
        try:
            detail = fn() or ""
            ok = True
        except Exception as error:  # a failed check, reported, never fatal here
            detail = f"{type(error).__name__}: {error}"
            ok = False
        self.results.append((name, ok, time.monotonic() - started, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})", flush=True)
        return ok

    def report(self) -> int:
        failed = [r for r in self.results if not r[1]]
        print()
        print(f"{'check':<34}{'result':<8}{'seconds':>8}  detail")
        for name, ok, seconds, detail in self.results:
            print(f"{name:<34}{'PASS' if ok else 'FAIL':<8}{seconds:>8.2f}  {detail[:100]}")
        print()
        print(f"{len(self.results) - len(failed)} passed, {len(failed)} failed")
        return 1 if failed else 0


def read_env(path: str | None) -> dict:
    """Read the instance's .env with the app's own parser."""
    if not path or not os.path.isfile(path):
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def session_cookie(env: dict) -> tuple[str, str]:
    """Return (cookie name, value) for a logged-in session signed with APP_KEY."""
    import pytz
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface

    app_key = env.get("APP_KEY") or os.environ.get("APP_KEY")
    if not app_key:
        raise RuntimeError("APP_KEY is not in the .env given with --env-file")
    app = Flask("gthread-smoke")
    app.secret_key = app_key
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))
    value = serializer.dumps(
        {"logged_in": True, "login_time": now_ist.isoformat(), "user": "gthread-smoke"}
    )
    name = env.get("SESSION_COOKIE_NAME") or "session"
    return name, value


def wait_ready(base: str, timeout: float) -> str:
    import requests

    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base}/auth/check-setup", timeout=5)
            if response.status_code == 200:
                return f"ready after {timeout - (deadline - time.monotonic()):.1f}s"
            last = f"status {response.status_code}"
        except Exception as error:
            last = type(error).__name__
        time.sleep(1)
    raise RuntimeError(f"not ready within {timeout:.0f}s ({last})")


def open_sse(base: str, cookie: tuple[str, str], first_event_within: float = 5.0):
    """Open /python/api/events and return (response, first line)."""
    import requests

    response = requests.get(
        f"{base}/python/api/events",
        cookies={cookie[0]: cookie[1]},
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=(5, first_event_within),
    )
    if response.status_code != 200:
        response.close()
        raise RuntimeError(f"status {response.status_code}")
    lines = response.iter_lines(decode_unicode=True)
    deadline = time.monotonic() + first_event_within
    while time.monotonic() < deadline:
        line = next(lines)
        if line:
            return response, line
    response.close()
    raise RuntimeError("no event received")


def socketio_client(base: str, transports: list[str]):
    import socketio

    client = socketio.Client(reconnection=False)
    client.connect(base, transports=transports, wait_timeout=10)
    return client


def listener_pids(port: int) -> list[int]:
    import psutil

    pids = []
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
            if conn.pid is not None:
                pids.append(conn.pid)
    return sorted(set(pids))


def proxy_topology(port: int, arbiter_pid: int | None) -> str:
    """Name where the proxy listening on ``port`` runs relative to gunicorn."""
    import psutil

    pids = listener_pids(port)
    if not pids:
        raise RuntimeError(f"nothing listens on port {port}")
    if len(pids) > 1:
        raise RuntimeError(f"more than one process listens on port {port}: {pids}")
    proc = psutil.Process(pids[0])
    if arbiter_pid is None:
        return f"listening (pid {proc.pid})"
    workers = [child.pid for child in psutil.Process(arbiter_pid).children()]
    if proc.pid in workers:
        return "thread"
    if proc.ppid() in workers:
        return "child"
    return "external"


def idle_keepalive_connection(base: str) -> http.client.HTTPConnection:
    """Make one request on a connection and leave it open and idle."""
    parts = urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=10)
    conn.request("GET", "/auth/check-setup")
    response = conn.getresponse()
    response.read()
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAlgo gunicorn boot smoke")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--worker", choices=("gthread", "eventlet"), required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--hold", type=int, default=6, help="streams and polling clients to hold")
    parser.add_argument("--threads", type=int, default=64, help="expected gthread threads")
    parser.add_argument("--proxy-port", type=int)
    parser.add_argument("--proxy", choices=("child", "thread", "external", "any"), default="any")
    parser.add_argument("--pid", type=int, help="gunicorn arbiter pid, for the stop check")
    parser.add_argument("--stop-within", type=float, help="seconds a SIGTERM stop may take")
    parser.add_argument("--log", help="gunicorn log file to scan after the stop")
    args = parser.parse_args(argv)

    import requests

    base = args.base_url.rstrip("/")
    env = read_env(args.env_file)
    smoke = Smoke()
    print(f"OpenAlgo boot smoke: {base} ({args.worker})")

    if not smoke.check("app ready", lambda: wait_ready(base, args.ready_timeout)):
        return smoke.report()

    def home() -> str:
        response = requests.get(f"{base}/", timeout=10)
        if response.status_code != 200:
            raise RuntimeError(f"status {response.status_code}")
        return "200"

    smoke.check("GET /", home)

    def handshake() -> str:
        response = requests.get(f"{base}/socket.io/?EIO=4&transport=polling", timeout=10)
        if response.status_code != 200 or '"sid"' not in response.text:
            raise RuntimeError(f"status {response.status_code}: {response.text[:80]}")
        return "sid returned"

    smoke.check("socket.io polling handshake", handshake)

    def polling_client() -> str:
        client = socketio_client(base, ["polling"])
        try:
            return f"connected over {client.transport()}"
        finally:
            client.disconnect()

    smoke.check("socket.io client (polling)", polling_client)

    def websocket_client() -> str:
        client = socketio_client(base, ["websocket"])
        try:
            transport = client.transport()
            if transport != "websocket":
                raise RuntimeError(f"transport is {transport}")
            return "connected over websocket"
        finally:
            client.disconnect()

    smoke.check("socket.io client (websocket)", websocket_client)

    cookie = None

    def make_cookie() -> str:
        nonlocal cookie
        cookie = session_cookie(env)
        return f"cookie {cookie[0]}"

    smoke.check("signed session cookie", make_cookie)

    def sse() -> str:
        response, line = open_sse(base, cookie)
        response.close()
        if line.strip() != CONNECTED_EVENT:
            raise RuntimeError(f"first line was {line!r}")
        return "connected event received"

    if cookie:
        smoke.check("SSE stream", sse)

    held: list = []

    def hold_and_probe() -> str:
        for _ in range(args.hold):
            held.append(open_sse(base, cookie)[0])
            held.append(socketio_client(base, ["polling"]))
        started = time.monotonic()
        response = requests.get(f"{base}/auth/check-setup", timeout=10)
        elapsed = time.monotonic() - started
        if response.status_code != 200 or elapsed > 2.0:
            raise RuntimeError(f"status {response.status_code} after {elapsed:.2f}s")
        return (
            f"{args.hold} streams and {args.hold} polling clients open, answered in {elapsed:.2f}s"
        )

    if cookie:
        smoke.check("request while streams are open", hold_and_probe)
    for item in held:
        try:
            if hasattr(item, "disconnect"):
                item.disconnect()
            else:
                item.close()
        except Exception:
            pass

    def runtime_report() -> str:
        response = requests.get(
            f"{base}/admin/api/system", cookies={cookie[0]: cookie[1]}, timeout=15
        )
        runtime = response.json()["data"]["runtime"]
        problems = []
        if runtime.get("worker_class") != args.worker:
            problems.append(f"worker_class {runtime.get('worker_class')}")
        expected_threads = args.threads if args.worker == "gthread" else None
        if runtime.get("configured_threads") != expected_threads:
            problems.append(f"configured_threads {runtime.get('configured_threads')}")
        if runtime.get("configured_workers") != 1:
            problems.append(f"configured_workers {runtime.get('configured_workers')}")
        if bool(runtime.get("eventlet_active")) != (args.worker == "eventlet"):
            problems.append(f"eventlet_active {runtime.get('eventlet_active')}")
        launcher = runtime.get("launcher") or {}
        if str(launcher.get("version")) != "1":
            problems.append(f"launcher {launcher}")
        if runtime.get("wsgi_hint") != f"gunicorn-{args.worker}":
            problems.append(f"wsgi_hint {runtime.get('wsgi_hint')}")
        if problems:
            raise RuntimeError(", ".join(problems))
        return f"{runtime.get('wsgi_hint')}, threads {runtime.get('configured_threads')}"

    if cookie:
        smoke.check("runtime report", runtime_report)

    if args.proxy_port:

        def proxy() -> str:
            deadline = time.monotonic() + 30
            while True:
                try:
                    topology = proxy_topology(args.proxy_port, args.pid)
                    break
                except RuntimeError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(1)
            if args.proxy != "any" and topology != args.proxy:
                raise RuntimeError(f"proxy runs as {topology}, expected {args.proxy}")
            return f"proxy on {args.proxy_port} runs as {topology}"

        smoke.check("market data proxy", proxy)

    if args.pid and args.stop_within:

        def stop() -> str:
            import psutil

            open_items: list = []
            try:
                open_items.append(socketio_client(base, ["polling"]))
            except Exception:
                pass
            if cookie:
                try:
                    open_items.append(open_sse(base, cookie)[0])
                except Exception:
                    pass
            try:
                open_items.append(idle_keepalive_connection(base))
            except Exception:
                pass
            arbiter = psutil.Process(args.pid)
            started = time.monotonic()
            os.kill(args.pid, signal.SIGTERM)
            # Polled rather than Process.wait(): the arbiter is usually not our
            # child, and an exited process whose parent has not reaped it yet
            # is a zombie, which counts as stopped.
            while True:
                try:
                    if arbiter.status() == psutil.STATUS_ZOMBIE:
                        break
                except psutil.NoSuchProcess:
                    break
                if time.monotonic() - started > args.stop_within:
                    raise RuntimeError(f"still running {args.stop_within:.0f}s after SIGTERM")
                time.sleep(0.1)
            elapsed = time.monotonic() - started
            for item in open_items:
                try:
                    (getattr(item, "disconnect", None) or item.close)()
                except Exception:
                    pass
            if args.proxy_port and args.proxy in ("child", "thread"):
                deadline = time.monotonic() + 10
                while listener_pids(args.proxy_port) and time.monotonic() < deadline:
                    time.sleep(0.5)
                if listener_pids(args.proxy_port):
                    raise RuntimeError(f"port {args.proxy_port} still in use after the stop")
            return f"stopped {elapsed:.1f}s after SIGTERM with {len(open_items)} connections open"

        smoke.check("SIGTERM stop", stop)

    if args.log:

        def log_clean() -> str:
            with open(args.log, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            problems = [
                marker
                for marker in ("Traceback (most recent call last)", "greenlet.error")
                if marker in text
            ]
            if problems:
                raise RuntimeError(f"log contains {', '.join(problems)}")
            return f"{len(text.splitlines())} lines, no traceback"

        smoke.check("gunicorn log", log_clean)

    status = smoke.report()
    print(json.dumps({"worker": args.worker, "failed": status != 0}))
    return status


if __name__ == "__main__":
    sys.exit(main())
