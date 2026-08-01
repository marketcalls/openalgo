"""Closes the remaining service-lifecycle investigations (gates A12, C4, A13).

Covers GT-A12-07, GT-S-04 (scalping risk monitor), GT-T-02 (Telegram bot
lifecycle), GT-H-03 (historify scheduler) and GT-A12-11 (Socket.IO rooms).

Each was carried as `INVESTIGATE:`. Most resolve with evidence; one was a real
defect and is fixed here.
"""

import inspect
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# GT-T-02: Telegram bot start (a real defect)
# --------------------------------------------------------------------------


def test_bot_start_is_serialized():
    """`is_running` is only set from inside the bot thread once polling is
    live, so it lags the call by up to five seconds. Two callers in that window
    -- the app.py auto-start and a user pressing Start -- both passed the guard
    and both spawned a polling thread. Two threads polling one token makes
    Telegram answer 409 Conflict and the bot stops responding."""
    from services.telegram_bot_service import TelegramBotService

    service = TelegramBotService()
    assert hasattr(service, "_start_lock")

    src = inspect.getsource(TelegramBotService.start_bot)
    assert "_start_lock" in src, "start_bot does not serialize"


def test_bot_start_also_rejects_a_thread_that_is_still_coming_up():
    """The flag alone is not enough -- the gap is exactly the problem."""
    from services.telegram_bot_service import TelegramBotService

    src = inspect.getsource(TelegramBotService._start_bot_locked)
    assert "is_alive()" in src, "a starting-but-not-yet-running thread is not rejected"


def test_only_one_of_many_concurrent_starts_wins():
    """Behavioural, against the real guard shape."""
    from services.telegram_bot_service import TelegramBotService

    service = TelegramBotService()
    service.is_running = False
    service.bot_thread = None

    started = []
    barrier = threading.Barrier(8)

    def fake_locked(_self=service):
        # Model the real body: check, then a slow spawn before the flag flips.
        if _self.is_running:
            return False, "already running"
        if _self.bot_thread is not None and _self.bot_thread.is_alive():
            return False, "already starting"
        started.append(1)
        _self.is_running = True
        return True, "started"

    def caller(_b=barrier):
        _b.wait()
        with service._start_lock:
            fake_locked()

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(started) == 1, f"{len(started)} bot threads would have been spawned"


# --------------------------------------------------------------------------
# GT-A12-07 / GT-S-04: scalping risk monitor (already correct)
# --------------------------------------------------------------------------


def test_scalping_monitor_is_a_locked_singleton():
    """Resolved with evidence. This module was written for real threads."""
    import services.scalping_risk_monitor_service as srm

    src = inspect.getsource(srm.ScalpingRiskMonitor.__new__)
    assert "_singleton_lock" in src, "singleton construction is not guarded"
    assert "if cls._instance is None" in src, "missing the double-check"


def test_scalping_exit_dispatch_is_atomic():
    """The money path: an SL/target breach must fire exactly once.

    _dispatch_exit does `if key in _exit_inflight: return` then `.add(key)`.
    That is a check-then-act, and it is safe only because every caller holds
    self._lock. This test pins that, since moving the call out of the lock
    would silently allow a double exit.
    """
    src = (
        REPO / "services" / "scalping_risk_monitor_service.py"
    ).read_text(encoding="utf-8")
    lines = src.splitlines()

    call_line = next(i for i, ln in enumerate(lines) if "self._dispatch_exit(" in ln)
    call_indent = len(lines[call_line]) - len(lines[call_line].lstrip())

    # Walk back to the nearest enclosing `with self._lock:` at a lower indent.
    enclosing = None
    for i in range(call_line - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        if indent < call_indent and stripped.startswith("with self._lock"):
            enclosing = i
            break
        if indent < call_indent and stripped.startswith("def "):
            break
    assert enclosing is not None, "_dispatch_exit is called outside self._lock"


def test_scalping_sync_coalesces_instead_of_stacking():
    import services.scalping_risk_monitor_service as srm

    src = inspect.getsource(srm.ScalpingRiskMonitor.request_sync)
    assert "_sync_lock" in src
    assert "is_alive()" in src, "a second sync would stack another thread"


# --------------------------------------------------------------------------
# GT-H-03: historify scheduler (already correct)
# --------------------------------------------------------------------------


def test_historify_scheduler_bounds_job_overlap():
    src = (
        REPO / "services" / "historify_scheduler_service.py"
    ).read_text(encoding="utf-8")
    block = src[src.index("BackgroundScheduler(") :][:600]
    for setting in ("max_instances", "coalesce", "misfire_grace_time"):
        assert setting in block, f"historify scheduler does not set {setting}"


# --------------------------------------------------------------------------
# GT-A12-11: Socket.IO rooms (safe today, conditionally)
# --------------------------------------------------------------------------


def test_no_emit_targets_a_room():
    """python-socketio's basic_enter_room is itself a check-then-act on nested
    dicts: two threads joining the same *new* room can each create a fresh
    mapping, and one membership is lost.

    That race is unreachable here because every emit in OpenAlgo is a
    broadcast -- room membership is written but never read for targeting. This
    test is the tripwire: adding the first room-targeted emit makes the library
    race reachable and this must be revisited.
    """
    offenders = []
    for sub in ("services", "blueprints", "subscribers"):
        for path in (REPO / sub).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "emit(" in line and "room=" in line and not line.strip().startswith("#"):
                    offenders.append(f"{path.relative_to(REPO)}: {line.strip()[:70]}")
    assert offenders == [], (
        "a room-targeted emit now exists, so the python-socketio room race is "
        f"reachable and GT-A12-11 must be reopened: {offenders}"
    )
