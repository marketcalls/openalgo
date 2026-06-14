"""
Scalping Risk Monitor — server-side, EVENT-DRIVEN stop-loss / target / trailing-SL.

The /scalping terminal lets a trader attach an SL, a target (TP) and an optional
trailing stop to each leg. These used to be evaluated in the browser, so they
stopped the moment the user left /scalping or closed the tab. This service runs
the engine server-side and is fully event-driven — there is NO polling:

  * Prices arrive as live ticks from the unified WebSocket proxy
    (services/websocket_client.py), and each tick drives one evaluation.
  * The watched-symbol set changes only when an SL is saved/deleted — the
    /scalping SL endpoints call sync(), so the monitor never polls the DB either.
  * Trailing updates and auto-clears are pushed to the browser via a SocketIO
    'scalping_sl_update' event, so the UI is event-driven too (no interval polling).

On breach the monitor fires a freeze-safe, whole-lot risk-reducing exit
(blueprints.scalping._reducing_exit) sized to the CURRENT live position, then
clears the SL only on a confirmed exit.

FD / thread hygiene:
  * One shared WebSocket connection via the websocket_client singleton (subscribe
    LTP mode); re-subscribed automatically on reconnect via the auth callback.
  * Exit placement runs in a short-lived daemon worker so a slow broker call
    never blocks tick processing; the worker removes every scoped_session it
    touches (background threads have no Flask teardown).
  * stop() unsubscribes, disconnects the client and is registered with atexit.
"""

from __future__ import annotations

import atexit
import threading
import time

from utils.logging import get_logger

logger = get_logger(__name__)

MIN_TRAIL_PROFIT = 1.0  # don't trail until >= 1 in profit (matches the UI engine)
PERSIST_THROTTLE_SEC = 1.5  # rate-limit trailing-SL writes (latest value, bounds restart staleness)
EMIT_THROTTLE_SEC = 1.0  # debounce browser SL-update pushes
EXIT_RETRY_COOLDOWN_SEC = 3.0  # throttle retries for a leg whose exit keeps failing
SUBSCRIBE_MODE = "LTP"


def _slkey(symbol: str, exchange: str, product: str) -> str:
    return f"{exchange}:{symbol}:{product}"


def _symkey(symbol: str, exchange: str) -> str:
    return f"{exchange}:{symbol}"


def evaluate_trail(state: dict, ltp: float) -> dict:
    """Pure trail evaluation (mirrors the browser's evaluateTrail).

    Long (BUY): stop sits below price and only rises. Short (SELL): stop sits
    above price and only falls. Returns updated highest/lowest/current_sl and
    whether the stop or target was breached this tick.
    """
    side = (state.get("side") or "BUY").upper()
    entry = state.get("entry_price") or 0.0
    trailing = bool(state.get("trailing_enabled"))
    step = state.get("trailing_step") or 0.0
    target = state.get("target") or 0.0
    current_sl = state.get("current_sl")
    if current_sl is None:
        current_sl = state.get("initial_sl")
    if current_sl is None:
        current_sl = entry

    if side == "SELL":
        prev_low = state.get("lowest_price")
        lowest = min(prev_low if prev_low is not None else entry, ltp)
        if trailing and step > 0 and (entry - ltp) >= MIN_TRAIL_PROFIT:
            candidate = lowest + step
            if candidate < current_sl:
                current_sl = candidate
        sl_hit = ltp >= current_sl  # short: stop ABOVE price
        target_hit = target > 0 and ltp <= target  # short: target BELOW price
        return {
            "highest_price": state.get("highest_price"),
            "lowest_price": lowest,
            "current_sl": current_sl,
            "breached": sl_hit or target_hit,
            "reason": "sl" if sl_hit else ("target" if target_hit else None),
        }

    # Long leg (BUY)
    prev_high = state.get("highest_price")
    highest = max(prev_high if prev_high is not None else entry, ltp)
    if trailing and step > 0 and (ltp - entry) >= MIN_TRAIL_PROFIT:
        candidate = highest - step
        if candidate > current_sl:
            current_sl = candidate
    sl_hit = ltp <= current_sl  # long: stop BELOW price
    target_hit = target > 0 and ltp >= target  # long: target ABOVE price
    return {
        "highest_price": highest,
        "lowest_price": state.get("lowest_price"),
        "current_sl": current_sl,
        "breached": sl_hit or target_hit,
        "reason": "sl" if sl_hit else ("target" if target_hit else None),
    }


class ScalpingRiskMonitor:
    """Singleton event-driven monitor for scalping SL / target / trailing stops."""

    _instance: ScalpingRiskMonitor | None = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> ScalpingRiskMonitor:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once()
            return cls._instance

    def _init_once(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, dict] = {}  # slkey -> state (in-memory source of truth)
        self._subscribed: set[str] = set()  # symkey currently subscribed on the feed
        self._ws = None
        self._callbacks_registered = False
        self._exit_inflight: set[str] = set()
        self._last_exit_attempt: dict[str, float] = {}
        self._last_persist: dict[str, float] = {}
        self._last_emit: dict[str, float] = {}
        # Background sync coalescing — sync() does blocking WS subscribe calls (up to
        # ~12s for the proxy ack), so it must NEVER run on a request thread.
        # request_sync() schedules it on a single daemon worker and coalesces repeats.
        self._sync_lock = threading.Lock()
        self._sync_pending = False
        self._sync_thread: threading.Thread | None = None
        atexit.register(self.stop)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Initial reconcile at boot (non-blocking). Idles when nothing is set."""
        self.request_sync()

    def request_sync(self) -> None:
        """Schedule a reconcile on the background worker (NEVER blocks the caller).

        Coalesces bursts: if a sync is already running, just flag that another is
        needed so it re-runs once. Safe to call from request threads.
        """
        with self._sync_lock:
            self._sync_pending = True
            if self._sync_thread is not None and self._sync_thread.is_alive():
                return
            self._sync_thread = threading.Thread(
                target=self._sync_worker, name="scalping-sync", daemon=True
            )
            self._sync_thread.start()

    def _sync_worker(self) -> None:
        while True:
            with self._sync_lock:
                if not self._sync_pending:
                    self._sync_thread = None
                    return
                self._sync_pending = False
            try:
                self.sync()
            except Exception as e:
                logger.exception("Scalping risk monitor sync error: %s", e)

    def stop(self) -> None:
        """Tear down the feed subscription/connection (FD hygiene)."""
        ws = self._ws
        if ws is not None:
            try:
                ws.unsubscribe_all()
            except Exception:
                pass
            try:
                ws.disconnect()
            except Exception:
                pass
        with self._lock:
            self._ws = None
            self._subscribed.clear()
            self._callbacks_registered = False

    def is_running(self) -> bool:
        return self._ws is not None and getattr(self._ws, "connected", False)

    # ------------------------------------------------------------------ sync (event)
    def sync(self) -> None:
        """Reconcile watched symbols with the active SL states.

        Called at startup and by the SL save/delete endpoints — never on a timer.
        Rebuilds the in-memory state from the DB and subscribes/unsubscribes the
        feed to exactly the set of symbols that have an active SL.
        """
        from database.scalping_db import get_active_sl_states

        try:
            # Only watch SLs for the CURRENT trading mode so sandbox SLs never
            # drive live exits (and vice-versa).
            rows = get_active_sl_states(mode=self._mode())
        finally:
            self._remove_session("database.scalping_db")

        # Update in-memory state + compute the subscription diff under the lock; the
        # actual subscribe/unsubscribe (blocking WS calls) happen OUTSIDE the lock so
        # they never block tick processing (_on_tick).
        with self._lock:
            self._states = {
                _slkey(r["symbol"], r["exchange"], r["product"]): dict(r) for r in rows
            }
            wanted_syms = {_symkey(r["symbol"], r["exchange"]) for r in rows}
            to_remove = self._subscribed - wanted_syms

        if not wanted_syms:
            if to_remove:
                self._unsubscribe(to_remove)
            return

        if not self._ensure_ws():
            # Not logged in / proxy unavailable yet — retried on the next sync.
            return

        with self._lock:
            to_add = wanted_syms - self._subscribed
            to_remove = self._subscribed - wanted_syms
        if to_add:
            self._subscribe(to_add)
        if to_remove:
            self._unsubscribe(to_remove)

    # ------------------------------------------------------------------ ws plumbing
    def _ensure_ws(self) -> bool:
        if self._ws is not None and getattr(self._ws, "connected", False):
            return True
        api_key = self._resolve_api_key()
        if not api_key:
            return False
        try:
            from services.websocket_client import get_websocket_client

            ws = get_websocket_client(api_key)
        except Exception as e:
            logger.debug("Scalping risk monitor: feed not available yet: %s", e)
            return False
        self._ws = ws
        if not self._callbacks_registered:
            ws.register_callback("market_data", self._on_tick)
            # Re-subscribe after a (re)connect — the client re-auths but does not
            # restore subscriptions itself.
            ws.register_callback("auth", self._on_auth)
            self._callbacks_registered = True
        return True

    def _subscribe(self, symkeys: set[str]) -> None:
        if not symkeys or self._ws is None:
            return
        symbols = [{"exchange": k.split(":", 1)[0], "symbol": k.split(":", 1)[1]} for k in symkeys]
        try:
            self._ws.subscribe(symbols, mode=SUBSCRIBE_MODE)  # blocking (off-lock)
            with self._lock:
                self._subscribed |= symkeys
        except Exception as e:
            logger.warning("Scalping risk monitor subscribe failed: %s", e)

    def _unsubscribe(self, symkeys: set[str]) -> None:
        if not symkeys or self._ws is None:
            return
        symbols = [{"exchange": k.split(":", 1)[0], "symbol": k.split(":", 1)[1]} for k in symkeys]
        try:
            self._ws.unsubscribe(symbols, mode=SUBSCRIBE_MODE)  # blocking (off-lock)
        except Exception as e:
            logger.debug("Scalping risk monitor unsubscribe failed: %s", e)
        with self._lock:
            self._subscribed -= symkeys

    def _on_auth(self, data: dict) -> None:
        if data.get("status") != "success":
            return
        # Re-subscribe after a (re)connect. Snapshot + clear under the lock, then do
        # the blocking subscribe OUTSIDE the lock so ticks aren't blocked.
        with self._lock:
            syms = set(self._subscribed)
            self._subscribed.clear()
        if syms:
            self._subscribe(syms)

    # ------------------------------------------------------------------ tick handler
    def _on_tick(self, data: dict) -> None:
        try:
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            inner = data.get("data") or {}
            ltp = inner.get("ltp")
            if ltp is None:
                ltp = inner.get("last_price")
            if symbol is None or exchange is None or ltp is None:
                return
            ltp = float(ltp)
            if ltp <= 0:
                return
        except (TypeError, ValueError):
            return

        symkey = _symkey(symbol, exchange)
        with self._lock:
            # A symbol can carry both an MIS and an NRML leg.
            matches = [
                (k, s)
                for k, s in self._states.items()
                if s.get("symbol") == symbol and s.get("exchange") == exchange
            ]
            current_mode = self._mode()
            for key, state in matches:
                # Skip SLs whose mode no longer matches (user flipped mode without
                # a resync) — never act on a sandbox SL while live, or vice-versa.
                # If mode is unknown (current_mode None), don't skip; the exit
                # worker's live-position check is the backstop.
                if current_mode and state.get("mode") and state.get("mode") != current_mode:
                    continue
                has_sl = state.get("current_sl") is not None or state.get("initial_sl") is not None
                has_target = (state.get("target") or 0) > 0
                if not has_sl and not has_target:
                    continue
                result = evaluate_trail(state, ltp)
                if result["breached"]:
                    self._dispatch_exit(key, state, result["reason"], ltp)
                    continue
                moved = (
                    result["current_sl"] != state.get("current_sl")
                    or result["highest_price"] != state.get("highest_price")
                    or result["lowest_price"] != state.get("lowest_price")
                )
                if moved:
                    state["current_sl"] = result["current_sl"]
                    state["highest_price"] = result["highest_price"]
                    state["lowest_price"] = result["lowest_price"]
                    self._maybe_persist(key, state)
        # symkey kept for symmetry / future per-symbol bookkeeping
        del symkey

    def _maybe_persist(self, key: str, state: dict) -> None:
        # Persist the LATEST trailed stop, rate-limited so a fast market can't storm
        # SQLite writes (which would contend the shared DB and slow every request).
        # The write always uses the current in-memory state, so staleness on a
        # restart is bounded to <= PERSIST_THROTTLE_SEC (then it re-trails on the next
        # tick). MUST carry `mode` or the upsert would write the wrong row.
        now = time.monotonic()
        if now - self._last_persist.get(key, 0.0) < PERSIST_THROTTLE_SEC:
            return
        self._last_persist[key] = now
        try:
            from database.scalping_db import upsert_sl_state

            upsert_sl_state(
                {
                    "symbol": state["symbol"],
                    "exchange": state["exchange"],
                    "product": state["product"],
                    "mode": state.get("mode"),
                    "current_sl": state["current_sl"],
                    "highest_price": state.get("highest_price"),
                    "lowest_price": state.get("lowest_price"),
                }
            )
        except Exception as e:
            logger.debug("Trailing persist failed for %s: %s", key, e)
        finally:
            self._remove_session("database.scalping_db")
        self._emit_update(key, state, throttled=True)

    # ------------------------------------------------------------------ exit
    def _dispatch_exit(self, key: str, state: dict, reason: str | None, ltp: float) -> None:
        now = time.monotonic()
        if key in self._exit_inflight:
            return
        if now - self._last_exit_attempt.get(key, 0.0) < EXIT_RETRY_COOLDOWN_SEC:
            return
        self._last_exit_attempt[key] = now
        self._exit_inflight.add(key)
        snapshot = dict(state)
        worker = threading.Thread(
            target=self._exit_worker,
            args=(key, snapshot, reason, ltp),
            name=f"scalping-exit-{snapshot.get('symbol')}",
            daemon=True,
        )
        worker.start()

    def _exit_worker(self, key: str, state: dict, reason: str | None, ltp: float) -> None:
        symbol = state["symbol"]
        exchange = state["exchange"]
        product = state["product"]
        try:
            # Guard the detection->exit race: only act if the GLOBAL mode still matches
            # this SL's mode. Exit routing (place_order/positionbook) follows the live
            # get_analyze_mode(); if the user toggled analyze/live since detection, this
            # SL now belongs to the other mode — skip (don't clear) so we never act on,
            # or wrongly clear, the wrong mode's position. It'll be re-evaluated on a
            # tick once the mode matches again.
            sl_mode = state.get("mode")
            cur_mode = self._mode()
            if sl_mode and cur_mode is not None and sl_mode != cur_mode:
                logger.info(
                    "Scalping auto-exit for %s skipped — mode changed (SL=%s, current=%s)",
                    symbol,
                    sl_mode,
                    cur_mode,
                )
                return
            auth = self._resolve_auth()
            if auth is None:
                logger.error(
                    "Scalping auto-exit for %s: no auth (not logged in) — will retry", symbol
                )
                return
            exit_api_key, auth_token, broker = auth
            net_qty = self._live_net_qty(symbol, exchange, product, exit_api_key, auth_token, broker)
            mode = state.get("mode")
            if net_qty == 0:
                self._clear_state(key, symbol, exchange, product, mode)
                logger.info("Scalping SL for %s already flat — cleared", symbol)
                return

            action = "SELL" if net_qty > 0 else "BUY"
            qty = abs(net_qty)
            from blueprints.scalping import _reducing_exit

            ok, resp, _code = _reducing_exit(
                symbol, exchange, product, action, qty, auth_token, broker, exit_api_key
            )
            if ok:
                self._clear_state(key, symbol, exchange, product, mode)
                logger.info(
                    "Scalping auto-exit (%s) %s %s %d @~%.2f",
                    reason or "sl",
                    action,
                    symbol,
                    qty,
                    ltp,
                )
            else:
                msg = resp.get("message") if isinstance(resp, dict) else resp
                logger.error(
                    "Scalping auto-exit FAILED for %s — still OPEN, will retry: %s", symbol, msg
                )
        except Exception as e:
            logger.exception("Scalping auto-exit error for %s: %s", symbol, e)
        finally:
            self._exit_inflight.discard(key)
            self._remove_sessions()

    def _clear_state(
        self, key: str, symbol: str, exchange: str, product: str, mode: str | None = None
    ) -> None:
        from database.scalping_db import delete_sl_state

        try:
            delete_sl_state(symbol, exchange, product, mode=mode)
        finally:
            self._remove_session("database.scalping_db")
        with self._lock:
            self._states.pop(key, None)
            self._last_persist.pop(key, None)
            self._last_exit_attempt.pop(key, None)
            # Drop the feed subscription if no other leg needs this symbol.
            symkey = _symkey(symbol, exchange)
            if not any(_symkey(s["symbol"], s["exchange"]) == symkey for s in self._states.values()):
                self._unsubscribe({symkey})
        self._emit_update(key, None, cleared=True, symbol=symbol, exchange=exchange, product=product)

    # ------------------------------------------------------------------ emit
    def _emit_update(
        self,
        key: str,
        state: dict | None,
        throttled: bool = False,
        cleared: bool = False,
        symbol: str | None = None,
        exchange: str | None = None,
        product: str | None = None,
    ) -> None:
        if throttled:
            now = time.monotonic()
            if now - self._last_emit.get(key, 0.0) < EMIT_THROTTLE_SEC:
                return
            self._last_emit[key] = now
        try:
            from extensions import socketio

            payload = {
                "symbol": symbol or (state or {}).get("symbol"),
                "exchange": exchange or (state or {}).get("exchange"),
                "product": product or (state or {}).get("product"),
                "cleared": cleared,
            }
            if state is not None:
                payload["current_sl"] = state.get("current_sl")
                payload["target"] = state.get("target")
            socketio.emit("scalping_sl_update", payload)
        except Exception as e:
            logger.debug("scalping_sl_update emit failed: %s", e)

    # ------------------------------------------------------------------ helpers
    def _live_net_qty(self, symbol, exchange, product, api_key, auth_token, broker) -> int:
        from services.positionbook_service import get_positionbook

        try:
            ok, resp, _code = get_positionbook(
                api_key=api_key, auth_token=auth_token, broker=broker
            )
        except Exception as e:
            logger.debug("Positionbook fetch error: %s", e)
            return 0
        if not ok or not isinstance(resp, dict):
            return 0
        ex = (exchange or "").upper()
        pr = (product or "").upper()
        for p in resp.get("data") or []:
            if (
                p.get("symbol") == symbol
                and (p.get("exchange") or "").upper() == ex
                and (p.get("product") or "").upper() == pr
            ):
                try:
                    return int(float(p.get("quantity") or 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def _mode(self) -> str | None:
        """Current trading mode ('analyze'/'live') for segregating SLs.

        NOT cached here on purpose: get_analyze_mode() is already TTL-cached AND
        invalidated on toggle (set_analyze_mode), so it's both cheap and fresh. A
        local cache would create a window where breach detection (cached mode) and
        exit routing (live get_analyze_mode) disagree right after a toggle — which
        could clear/act on the wrong mode's SL and drop protection. Returns None if
        undeterminable; callers then degrade safely (the exit worker's live-position
        check + the per-exit mode guard still protect).
        """
        try:
            from database.settings_db import get_analyze_mode

            return "analyze" if get_analyze_mode() else "live"
        except Exception:
            return None
        finally:
            self._remove_session("database.settings_db")

    def _resolve_api_key(self) -> str | None:
        from database.auth_db import get_api_key_for_tradingview
        from database.user_db import find_user_by_username

        try:
            user = find_user_by_username()
            if not user:
                return None
            return get_api_key_for_tradingview(user.username)
        finally:
            self._remove_session("database.user_db")

    def _resolve_auth(self):
        """Resolve (api_key, auth_token, broker) for positionbook + exits.

        Pass the api_key ONLY (auth_token/broker None) and let the service layer
        route by mode — sandbox in analyze mode, live otherwise. Required because
        place_order validates a mandatory `apikey` regardless of auth path, and
        get_positionbook routes by param presence (auth_token+broker would force
        the live book and hide sandbox positions). Returns None if no api_key.
        """
        from database.auth_db import get_api_key_for_tradingview
        from database.user_db import find_user_by_username

        try:
            user = find_user_by_username()
            if not user:
                return None
            api_key = get_api_key_for_tradingview(user.username)
            if not api_key:
                return None
            return api_key, None, None
        finally:
            self._remove_session("database.user_db")

    def _remove_session(self, module_name: str) -> None:
        try:
            import importlib

            mod = importlib.import_module(module_name)
            sess = getattr(mod, "db_session", None)
            if sess is not None:
                sess.remove()
        except Exception:
            pass

    def _remove_sessions(self) -> None:
        for module_name in (
            "database.scalping_db",
            "database.symbol",
            "database.user_db",
            "database.auth_db",
            "database.settings_db",
        ):
            self._remove_session(module_name)


# Module-level singleton + accessors.
scalping_risk_monitor = ScalpingRiskMonitor()


def get_scalping_risk_monitor() -> ScalpingRiskMonitor:
    return scalping_risk_monitor


def start_scalping_risk_monitor() -> None:
    """Start (initial sync) the singleton monitor. Safe to call multiple times."""
    get_scalping_risk_monitor().start()


def notify_sl_changed() -> None:
    """Event hook: an SL was saved/deleted — reconcile the watched symbol set.

    Non-blocking: schedules the reconcile on the monitor's background worker so the
    HTTP request that triggered it returns immediately (sync() does blocking WS
    subscribe calls and must never run on a request thread).
    """
    try:
        get_scalping_risk_monitor().request_sync()
    except Exception as e:
        logger.debug("Scalping risk monitor sync skipped: %s", e)
