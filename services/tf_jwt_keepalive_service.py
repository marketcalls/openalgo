"""TF JWT keep-alive service.

The server-side TradeFinder JWT (strategies/tf_jwt.txt) is what the
tf_boost_snapshot_service and Python TF strategies authenticate with. Nothing
was keeping it fresh day-to-day — it only gets renewed if a strategy script
happens to be running, or someone manually pastes a token. Refreshing it via
strategies/tf_auth.py's browser automation is slow (up to ~60s, launches a
headless Chromium against a persisted, already-logged-in Google profile), so
it must never run inline in a request thread.

This service is designed to be pinged frequently and cheaply by an ACTIVE
openalgo-chart session (the user has the chart open regularly, per their own
usage — see useTradeFinderBoost.ts): a cheap expiry check gates the slow
refresh, which runs in a background thread so the HTTP response returns
immediately regardless of whether a refresh was kicked off.

Headless refresh only reloads an already-logged-in TradeFinder session — it
cannot complete a fresh Google login. When TradeFinder's own session has
actually logged out (independent of Google, which can still be fine), every
headless attempt fails identically. Once the headless retries are exhausted,
this service opens one real, visible browser window (same flow as
strategies/tf_login_setup.py) so the user can click through the Google login
whenever they next look at their screen, without having to remember to run
anything from a terminal.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from utils.logging import get_logger

logger = get_logger(__name__)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TF_AUTH_PATH = os.path.join(_REPO_ROOT, "strategies", "tf_auth.py")

_tf_auth = None
_lock = threading.Lock()
_refreshing = False

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()
_KEEPALIVE_JOB_ID = "tf_jwt_keepalive_tick"

# Headless can only reload an already-logged-in TF session (see refresh_tf_jwt's
# docstring) -- when TF's own session has actually logged out, every headless
# attempt fails identically, so retrying it more than once just burns the
# outage window before the headed fallback (which actually works, see below)
# kicks in. One attempt still absorbs a genuine cold-Chromium flake; the
# headed tier is what recovers a real logout now, not this retry loop.
_MAX_REFRESH_ATTEMPTS = 1
_RETRY_BACKOFF_SECONDS = 5

# Headless refresh can only reload an already-logged-in session; it cannot
# complete a fresh Google login (the OAuth popup click-through is unreliable
# under headless Chromium). When TradeFinder's own session has actually
# logged out, every headless attempt fails the same way, so as a last resort
# pop a REAL, visible browser window and give the user time to click through
# the Google login themselves — same flow as running tf_login_setup.py, just
# triggered automatically instead of requiring the user to remember it.
_HEADED_LOGIN_TIMEOUT_SECONDS = 240


def _load_tf_auth():
    """strategies/ has no __init__.py (its scripts run standalone via `uv run`
    from that directory), so this is loaded by file path rather than imported
    as a package — same reason services/tradefinder_service.py re-implements
    rather than imports its strategies/ counterpart."""
    global _tf_auth
    if _tf_auth is None:
        spec = importlib.util.spec_from_file_location("tf_auth_dynamic", _TF_AUTH_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _tf_auth = module
    return _tf_auth


def get_tf_jwt_status() -> dict:
    ta = _load_tf_auth()
    token = ta._read_file_jwt()
    return {
        "hasToken": bool(token),
        "expiresInSeconds": max(0, int(ta.jwt_expiry_seconds(token))) if token else 0,
        "refreshing": _refreshing,
    }


def trigger_refresh_if_needed(min_seconds: int = 1800, force: bool = False) -> dict:
    """Non-blocking. Cheap file read + expiry check; if the token is missing or
    expiring within `min_seconds`, kicks off the browser refresh in a
    background thread (deduped — a refresh already in flight is not
    re-launched) and returns immediately. Safe to call every few minutes.

    `force=True` skips the expiry check entirely -- for when a live request
    just got a 401 on a token the file still claims has time left (TF revoked
    the session server-side, independent of the JWT's own exp claim). Without
    this, that mismatch is invisible until the next scheduled tick, up to 20
    minutes of every TradeFinder call failing for no visible reason."""
    global _refreshing
    ta = _load_tf_auth()
    token = ta._read_file_jwt()
    needs_refresh = force or not token or ta.jwt_expiry_seconds(token) <= min_seconds

    if needs_refresh:
        with _lock:
            if not _refreshing:
                _refreshing = True

                def _run():
                    global _refreshing
                    try:
                        # refresh_tf_jwt reports its own failures on stdout and
                        # returns None rather than raising, so without this the
                        # service logged nothing and a dead refresh looked
                        # identical to a healthy one — the token simply expired
                        # with no trace in log/errors.jsonl.
                        #
                        # Retry rather than give up: a single miss (TF slow to
                        # mint, cold Chromium losing the race against the rest
                        # of app startup) used to leave the token dead until
                        # the next 20-min tick. Both the boot call and the
                        # scheduled tick land here, so one retry loop covers
                        # every caller.
                        for attempt in range(1, _MAX_REFRESH_ATTEMPTS + 1):
                            if ta.refresh_tf_jwt():
                                if attempt > 1:
                                    logger.info(
                                        f"tf_jwt_keepalive: refresh succeeded on attempt {attempt}"
                                    )
                                return
                            if attempt < _MAX_REFRESH_ATTEMPTS:
                                logger.warning(
                                    f"tf_jwt_keepalive: refresh attempt {attempt} produced no "
                                    f"token, retrying in {_RETRY_BACKOFF_SECONDS}s"
                                )
                                time.sleep(_RETRY_BACKOFF_SECONDS)

                        # Headless is exhausted. Open a visible window so the user can
                        # complete the Google login by hand whenever they notice it —
                        # refresh_tf_jwt keeps polling for the token for the whole
                        # timeout, so the window stays up long enough to click through.
                        logger.warning(
                            "tf_jwt_keepalive: headless refresh exhausted, opening a visible "
                            "browser window for manual Google login"
                        )
                        if ta.refresh_tf_jwt(headless=False, timeout_s=_HEADED_LOGIN_TIMEOUT_SECONDS):
                            logger.info("tf_jwt_keepalive: refresh succeeded via headed login window")
                            return
                        logger.error(
                            "tf_jwt_keepalive: refresh failed even after a headed login window "
                            "(no display, or login not completed in time). Run "
                            "uv run python strategies/tf_login_setup.py manually, or check "
                            "that the Playwright chromium build is installed "
                            "(uv run playwright install chromium)."
                        )
                    except Exception as e:
                        logger.warning(f"tf_jwt_keepalive: background refresh failed: {e}")
                    finally:
                        _refreshing = False

                threading.Thread(target=_run, daemon=True, name="tf-jwt-refresh").start()
                logger.info("tf_jwt_keepalive: token missing/expiring, background refresh started")

    return get_tf_jwt_status()


def init_tf_jwt_keepalive_scheduler(interval_minutes: int = 20) -> None:
    """Server-native keep-alive: runs independent of any chart tab, so the
    server-side TF JWT self-heals on its own cadence whenever OpenAlgo itself
    is running — including right after a restart, when the token may have
    gone stale while the machine was off. The chart's own /tfjwtkeepalive
    pings (useTradeFinderBoost.ts) and this scheduler both funnel through
    trigger_refresh_if_needed's single _refreshing guard, so they can never
    launch two overlapping browser refreshes.

    Idempotent; safe to call once at app startup."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            logger.debug("tf_jwt_keepalive: scheduler already initialized, skipping")
            return

        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            lambda: trigger_refresh_if_needed(min_seconds=1800),
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=_KEEPALIVE_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        _scheduler.start()

        # Fire once immediately at boot too, so a restart self-heals right
        # away instead of waiting a full interval — this is what covers the
        # "computer was off overnight, token went stale" case.
        threading.Thread(
            target=lambda: trigger_refresh_if_needed(min_seconds=1800),
            daemon=True,
            name="tf-jwt-keepalive-boot",
        ).start()

        logger.info(
            f"TF JWT keep-alive scheduler started (every {interval_minutes} min, "
            "independent of any client — self-heals on server restart)"
        )
