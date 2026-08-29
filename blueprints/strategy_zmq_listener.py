"""OpenAlgo Strategy Hub — ZMQ listener and control service.

Discovers and monitors lean_trading_engine strategy instances (and any other
strategy runner speaking the same protocol) over ZeroMQ, and relays their
state to the browser via SocketIO. Runs entirely as background OS threads
inside the single Flask/gunicorn worker.

Protocol (matches lean_trading_engine/zmq_publisher.py):
  - Strategies PUSH frames to our PULL socket at STRATEGY_HUB_ZMQ_PORT
    (default 6099): ANNOUNCE (on start), HEARTBEAT (every 10s), METRICS
    (on fills), BYE (on clean shutdown). Each frame carries strategy_id,
    host, zmq_port, unit_name so we can control it later.
  - We also periodically PING a configured port range
    (STRATEGY_ZMQ_BASE_PORT..+STRATEGY_ZMQ_SCAN_RANGE) so a strategy that
    started before OpenAlgo (or whose ANNOUNCE was missed) is still found.
  - To stop/start a strategy: REQ STOP/START to its REP port first (2s
    timeout); if that fails, fall back to
    `systemctl --user stop/start <unit_name>`.

Threading model: gunicorn runs a single eventlet worker in production, and
libzmq's blocking recv() does not cooperate with eventlet's greenlet
scheduler the way monkey-patched stdlib sockets do. Both loops below
therefore run on REAL OS threads (via eventlet.patcher.original when
eventlet is active, matching blueprints/python_strategy_custom.py), not
monkey-patched green threads. socketio.emit() is safe to call from those
threads because extensions.py configures async_mode="threading".

Disable with STRATEGY_HUB_ENABLED=FALSE in .env.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading as _patched_threading
import time
from datetime import UTC, datetime, timezone
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# Real OS threads only — see module docstring. Under eventlet, `threading` is
# monkey-patched process-wide; grab the pre-patch module the same way
# blueprints/python_strategy_custom.py does for its schedule-install thread.
if "eventlet" in sys.modules:
    import eventlet

    _threading = eventlet.patcher.original("threading")
else:
    _threading = _patched_threading

STATUS_ONLINE = "online"
STATUS_STALE = "stale"
STATUS_OFFLINE = "offline"

_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = _threading.Lock()

_started = False
_start_lock = _threading.Lock()
_running = False
_pull_thread: _threading.Thread | None = None
_poll_thread: _threading.Thread | None = None


def _enabled() -> bool:
    return os.getenv("STRATEGY_HUB_ENABLED", "TRUE").upper() != "FALSE"


def _hub_port() -> int:
    return int(os.getenv("STRATEGY_HUB_ZMQ_PORT", "6099"))


def _scan_base_port() -> int:
    return int(os.getenv("STRATEGY_ZMQ_BASE_PORT", "6000"))


def _scan_range() -> int:
    return int(os.getenv("STRATEGY_ZMQ_SCAN_RANGE", "20"))


def _poll_interval_seconds() -> float:
    return float(os.getenv("STRATEGY_HUB_POLL_INTERVAL_SECONDS", "15"))


def _stale_after_seconds() -> float:
    return float(os.getenv("STRATEGY_HUB_STALE_SECONDS", "30"))


def _offline_after_seconds() -> float:
    # Offline is declared at 3x the stale window so a couple of missed
    # heartbeats/polls (network blip) don't immediately flip a card to red.
    return _stale_after_seconds() * 3


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _emit_update(strategy_id: str, entry: dict[str, Any]) -> None:
    """Push one strategy's current state to all connected browsers."""
    try:
        from extensions import socketio

        socketio.emit(
            "strategy_hub_update",
            {"strategy_id": strategy_id, "strategy": entry},
        )
    except Exception:
        logger.exception("Failed to emit strategy_hub_update for %s", strategy_id)


def get_registry_snapshot() -> dict[str, dict[str, Any]]:
    """Return a shallow copy of the full registry for the REST API."""
    with _REGISTRY_LOCK:
        return {sid: dict(entry) for sid, entry in _REGISTRY.items()}


def get_entry(strategy_id: str) -> dict[str, Any] | None:
    with _REGISTRY_LOCK:
        entry = _REGISTRY.get(strategy_id)
        return dict(entry) if entry is not None else None


def _upsert(strategy_id: str, **fields: Any) -> dict[str, Any]:
    """Merge fields into a strategy's registry entry and return the new snapshot."""
    with _REGISTRY_LOCK:
        entry = _REGISTRY.setdefault(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "status": STATUS_ONLINE,
                "host": "127.0.0.1",
                "zmq_port": None,
                "unit_name": None,
                "metrics": {},
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "last_command": None,
            },
        )
        entry.update({k: v for k, v in fields.items() if v is not None})
        return dict(entry)


def _handle_frame(msg: dict[str, Any]) -> None:
    strategy_id = msg.get("strategy_id")
    if not strategy_id:
        return
    frame_type = msg.get("type", "")

    if frame_type == "BYE":
        with _REGISTRY_LOCK:
            entry = _REGISTRY.get(strategy_id)
            if entry is not None:
                entry["status"] = STATUS_OFFLINE
                entry["last_seen"] = _now_iso()
                snapshot = dict(entry)
            else:
                snapshot = None
        if snapshot is not None:
            _emit_update(strategy_id, snapshot)
        return

    metrics = msg.get("metrics") if frame_type == "HEARTBEAT" else msg.get("data")
    snapshot = _upsert(
        strategy_id,
        status=STATUS_ONLINE,
        host=msg.get("host"),
        zmq_port=msg.get("zmq_port"),
        unit_name=msg.get("unit_name"),
        metrics=metrics if metrics is not None else None,
        last_seen=_now_iso(),
    )
    _emit_update(strategy_id, snapshot)


def _pull_loop() -> None:
    """Bind PULL on STRATEGY_HUB_ZMQ_PORT and process incoming push frames."""
    try:
        import zmq
    except ImportError:
        logger.warning("pyzmq not installed — Strategy Hub discovery disabled")
        return

    context = zmq.Context()
    socket = context.socket(zmq.PULL)
    try:
        socket.bind(f"tcp://0.0.0.0:{_hub_port()}")
    except Exception:
        logger.exception("Strategy Hub failed to bind PULL socket on port %s", _hub_port())
        context.term()
        return

    socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1s poll so _running is checked promptly
    logger.info("Strategy Hub ZMQ listener bound on tcp://0.0.0.0:%s", _hub_port())

    while _running:
        try:
            msg = socket.recv_json()
        except zmq.Again:
            continue
        except Exception:
            logger.exception("Strategy Hub PULL loop error")
            continue
        try:
            _handle_frame(msg)
        except Exception:
            logger.exception("Strategy Hub failed to process frame: %s", msg)

    socket.close()
    context.term()


def _ping_port(zmq, context, host: str, port: int, timeout_ms: int = 300) -> dict[str, Any] | None:
    """Send a single PING to host:port and return the reply, or None on timeout/error."""
    sock = context.socket(zmq.REQ)
    try:
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
        sock.connect(f"tcp://{host}:{port}")
        sock.send_json({"command": "PING"})
        return sock.recv_json()
    except Exception:
        return None
    finally:
        sock.close()


def _sweep_stale_entries() -> None:
    """Downgrade entries that have missed heartbeats/polls to stale or offline."""
    now = datetime.now(UTC)
    with _REGISTRY_LOCK:
        snapshot_items = list(_REGISTRY.items())

    for strategy_id, entry in snapshot_items:
        if entry["status"] == STATUS_OFFLINE:
            continue
        try:
            last_seen = datetime.fromisoformat(entry["last_seen"])
        except ValueError:
            continue
        age = (now - last_seen).total_seconds()
        new_status = entry["status"]
        if age >= _offline_after_seconds():
            new_status = STATUS_OFFLINE
        elif age >= _stale_after_seconds():
            new_status = STATUS_STALE
        else:
            new_status = STATUS_ONLINE

        if new_status != entry["status"]:
            snapshot = _upsert(strategy_id, status=new_status)
            _emit_update(strategy_id, snapshot)


def _poll_loop() -> None:
    """Periodically scan the configured port range for strategies we haven't
    heard from via PUSH (e.g. OpenAlgo restarted after the strategy's
    ANNOUNCE), and sweep the registry for stale/offline entries.
    """
    try:
        import zmq
    except ImportError:
        return  # already logged by _pull_loop

    context = zmq.Context()
    base = _scan_base_port()
    scan_range = _scan_range()

    while _running:
        for offset in range(scan_range):
            if not _running:
                break
            port = base + offset
            reply = _ping_port(zmq, context, "127.0.0.1", port)
            if reply and reply.get("reply") == "PONG" and reply.get("strategy_id"):
                snapshot = _upsert(
                    reply["strategy_id"],
                    status=STATUS_ONLINE,
                    host=reply.get("host", "127.0.0.1"),
                    zmq_port=reply.get("zmq_port", port),
                    unit_name=reply.get("unit_name"),
                    last_seen=_now_iso(),
                )
                _emit_update(reply["strategy_id"], snapshot)

        _sweep_stale_entries()

        # Sleep in small increments so shutdown is responsive.
        slept = 0.0
        interval = _poll_interval_seconds()
        while slept < interval and _running:
            time.sleep(1)
            slept += 1

    context.term()


def start_listener() -> None:
    """Start the PULL-receive and periodic-poll background threads (idempotent)."""
    global _started, _running, _pull_thread, _poll_thread

    if not _enabled():
        logger.debug("Strategy Hub disabled via STRATEGY_HUB_ENABLED")
        return

    with _start_lock:
        if _started:
            return
        _started = True
        _running = True

        _pull_thread = _threading.Thread(target=_pull_loop, daemon=True, name="strategy-hub-pull")
        _pull_thread.start()

        _poll_thread = _threading.Thread(target=_poll_loop, daemon=True, name="strategy-hub-poll")
        _poll_thread.start()

    logger.info("Strategy Hub ZMQ listener started")


def stop_listener() -> None:
    """Stop background threads. Not called on normal process exit (daemon
    threads die with the process); provided for tests and graceful reload.
    """
    global _running, _started
    _running = False
    if _pull_thread is not None:
        _pull_thread.join(timeout=5)
    if _poll_thread is not None:
        _poll_thread.join(timeout=5)
    _started = False


def send_command(strategy_id: str, command: str) -> tuple[bool, str]:
    """Send STOP/START to a strategy: ZMQ REQ first, systemctl fallback.

    Returns (success, message).
    """
    command = command.upper()
    if command not in ("STOP", "START"):
        return False, f"Unsupported command: {command}"

    entry = get_entry(strategy_id)
    if entry is None:
        return False, "Unknown strategy — it has not announced or been discovered yet"

    host = entry.get("host") or "127.0.0.1"
    port = entry.get("zmq_port")
    unit_name = entry.get("unit_name")

    zmq_message = "No ZMQ port known for this strategy"
    if port:
        try:
            import zmq

            context = zmq.Context.instance()
            sock = context.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, 2000)
            sock.setsockopt(zmq.SNDTIMEO, 2000)
            sock.connect(f"tcp://{host}:{port}")
            sock.send_json({"command": command})
            reply = sock.recv_json()
            sock.close()
            if reply.get("reply") == "ACK":
                message = f"ZMQ {command} acknowledged by {strategy_id}"
                _record_command_result(strategy_id, command, True, message)
                return True, message
            zmq_message = f"Unexpected ZMQ reply: {reply}"
        except ImportError:
            zmq_message = "pyzmq not installed"
        except Exception as exc:
            zmq_message = f"ZMQ {command} failed or timed out: {exc}"

    # Fall back to systemd unit control.
    if not unit_name:
        message = f"{zmq_message}; no systemd unit_name configured for fallback"
        _record_command_result(strategy_id, command, False, message)
        return False, message

    action = "stop" if command == "STOP" else "start"
    try:
        result = subprocess.run(
            ["systemctl", "--user", action, unit_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            message = f"{zmq_message}; systemctl --user {action} {unit_name} succeeded"
            _record_command_result(strategy_id, command, True, message)
            return True, message
        message = (
            f"{zmq_message}; systemctl --user {action} {unit_name} failed: {result.stderr.strip()}"
        )
        _record_command_result(strategy_id, command, False, message)
        return False, message
    except Exception as exc:
        message = f"{zmq_message}; systemctl fallback failed: {exc}"
        _record_command_result(strategy_id, command, False, message)
        return False, message


def _record_command_result(strategy_id: str, command: str, success: bool, message: str) -> None:
    snapshot = _upsert(
        strategy_id,
        last_command={
            "command": command,
            "success": success,
            "message": message,
            "at": _now_iso(),
        },
    )
    _emit_update(strategy_id, snapshot)
