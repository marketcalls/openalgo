# services/symbol_exit_monitor_service.py
"""
Server-side exit watch for the charting terminal's position calculator.

The calculator can attach risk legs (``stoploss`` / ``target`` /
``trailing_stoploss``) to a ``placeorder`` request. For entry-orders those are
advisory on the wire — every broker gets a clean single-leg entry. This
service is what makes them real: it records each entry order as an "exit
watch" (``database/symbol_exit_db.py``), subscribes the symbol's LTP on the
WebSocket proxy, and squares the position off with a market order when the
level is reached. It works for intraday and overnight entries in both
sandbox (analyze) and live mode. GTT placement uses its dedicated API.

A broker accepts an entry before it fills it, so watches are born
``pending``: levels are only evaluated, and an entry price only seeded, once
the guarded entry order is confirmed filled (resolved against the broker's
own orderbook), so a resting LIMIT that is still working cannot false-trigger
a stop on a position that does not exist yet. A rejected or cancelled entry
drops its watch. Exits are capped to the watched entry's own quantity so one
watch never squares unrelated exposure sharing the same symbol/exchange/
product, and a positionbook failure keeps the watch open instead of reading
as a flat position.

Designed after ``services/scalping_risk_monitor_service.py``:
- the shared ``services/risk`` core decides (pure, no I/O) what a tick means;
- the feed comes from the WebSocket proxy client, whose dispatch loop runs
  callbacks on a green thread, so DB writes and order placement are safe there;
- exit placement follows the current analyzer toggle (scaled to the watch's
  own mode), and a watch never acts across modes.
"""

from __future__ import annotations

import atexit
import math
import time

from utils.logging import get_logger
from utils.real_threading import Lock, RLock, Thread

logger = get_logger(__name__)

SUBSCRIBE_MODE = "LTP"
PERSIST_THROTTLE_SEC = 1.5  # cap trailing-stop writes in a fast market
EXIT_RETRY_COOLDOWN_SEC = 3.0  # throttle retries when an exit keeps failing
PENDING_RESOLVE_COOLDOWN_SEC = 3.0  # throttle broker checks while an entry is unfilled


def _symkey(exchange: str, symbol: str) -> str:
    # (exchange, symbol) — proxy subscribe payload orders exchange first.
    return f"{exchange}:{symbol}"


def _is_usable_price(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0.0
    except (TypeError, ValueError):
        return False


def _classify_entry(order: dict) -> str:
    """Verdict for a guarded entry order: 'filled' | 'open' | 'dead'.

    The broker accepts an entry before it fills. Until a ``quantity`` exists
    in the position book the watch has nothing to protect, so the monitor
    resolves the entry and acts on this verdict: activate on fill, drop the
    watch on reject/cancel, keep waiting otherwise.
    """
    status = str(order.get("order_status") or order.get("status") or "").strip().lower()
    filled = order.get("filled_quantity")
    filled_qty = 0.0
    if filled is not None:
        try:
            filled_qty = float(filled)
        except (TypeError, ValueError):
            filled_qty = 0.0
    # A partial fill is still a position - protect the filled part.
    if filled_qty > 0:
        return "filled"
    if status in ("complete", "completed", "filled", "executed", "fully traded", "trade"):
        return "filled"
    if status in ("rejected", "cancelled", "expired", "cancelled/expired"):
        return "dead"
    return "open"


def _exit_sizing(state: dict, net_qty: int) -> tuple[str, int] | None:
    """Square-off sizing for a breached watch.

    The watch protects one entry order, so the exit is capped to that watch's
    ``quantity`` and never squares a whole aggregate position that shares the
    symbol/exchange/product (which could close unrelated exposure). Returns
    ``(action, qty)``; None when there is nothing to exit - the position is
    gone (``net_qty`` zero) or has flipped beyond the watched side.
    """
    watch_qty = int(state.get("quantity") or 0)
    side = (state.get("side") or "BUY").upper()
    if side == "BUY":
        if net_qty <= 0:
            return None
        return "SELL", min(net_qty, watch_qty)
    if net_qty >= 0:
        return None
    return "BUY", min(-net_qty, watch_qty)


class SymbolExitMonitor:
    """Singleton event-driven monitor for calculator exit watches."""

    _instance: SymbolExitMonitor | None = None
    _singleton_lock = Lock()

    def __new__(cls) -> SymbolExitMonitor:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once()
            return cls._instance

    def _init_once(self) -> None:
        # Real, not green: _on_tick() runs on the websocket client's dispatch
        # (green) thread while request threads also call request_sync() from
        # the order path. See utils/real_threading.
        self._lock = RLock()
        self._watches: dict[int, dict] = {}  # watch_id -> state
        self._subscribed: set[str] = set()  # symkey currently subscribed
        self._ws = None
        self._callbacks_registered = False
        self._exit_inflight: set[int] = set()
        self._last_exit_attempt: dict[int, float] = {}
        self._last_persist: dict[int, float] = {}
        self._last_activate: dict[int, float] = {}
        # Background sync coalescing — sync() blocks on WS subscribe acks, so it
        # must never run on a request thread. request_sync() schedules a single
        # daemon worker and coalesces bursts.
        self._sync_lock = Lock()
        self._sync_pending = False
        self._sync_thread: Thread | None = None
        atexit.register(self._atexit_stop)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Initial reconcile at boot (non-blocking). Idles when no watch is set."""
        self.request_sync()

    def request_sync(self) -> None:
        """Schedule a reconcile on the background worker (NEVER blocks the caller).

        Coalesces bursts: if a sync is already running, flag that another run is
        needed so it re-runs once. Safe to call from request threads.
        """
        with self._sync_lock:
            self._sync_pending = True
            if self._sync_thread is not None and self._sync_thread.is_alive():
                return
            self._sync_thread = Thread(
                target=self._sync_worker, name="symbol-exit-sync", daemon=True
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
                logger.exception("Symbol exit monitor sync error: %s", e)

    def _atexit_stop(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

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

    # ------------------------------------------------------------------ reconcile
    def sync(self) -> None:
        """Rebuild in-memory watches and subscribe the feed to exactly their symbols.

        Only watches for the CURRENT trading mode are loaded so sandbox watches
        never drive live exits (and vice-versa).
        """
        from database.symbol_exit_db import get_active_watches

        try:
            rows = get_active_watches(mode=self._mode())
        finally:
            self._remove_session("database.symbol_exit_db")

        with self._lock:
            self._watches = {int(r["id"]): self._build_state(r) for r in rows}
            wanted = {_symkey(r["exchange"], r["symbol"]) for r in rows}
            to_remove = self._subscribed - wanted

        if not wanted:
            if to_remove:
                self._unsubscribe(to_remove)
            return

        if not self._ensure_ws():
            return  # retried on the next sync

        with self._lock:
            to_add = wanted - self._subscribed
        if to_add:
            self._subscribe(to_add)
        if to_remove:
            self._unsubscribe(to_remove)

    def _build_state(self, row: dict) -> dict:
        """Translate a DB row into the loose dict ``services/risk`` accepts."""
        return {
            "id": int(row["id"]),
            "symbol": row["symbol"],
            "exchange": row["exchange"],
            "product": row["product"],
            "side": row["side"],
            "mode": row["mode"],
            "order_id": row["order_id"],
            "quantity": int(row["quantity"] or 0),
            "identifier": str(row["id"]),
            "status": row.get("status", "active"),
            "entry_price": row["entry_price"] or 0.0,
            "current_sl": row["current_stop"] or row["stop_loss"],
            "initial_sl": row["stop_loss"],
            "target": row["target"],
            "trailing_enabled": bool(_is_usable_price(row["trailing_step"])),
            "trailing_step": row["trailing_step"] or 0.0,
            "highest_price": row["highest_price"],
            "lowest_price": row["lowest_price"],
        }

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
            logger.debug("Symbol exit monitor: feed not available yet: %s", e)
            return False
        self._ws = ws
        if not self._callbacks_registered:
            ws.register_callback("market_data", self._on_tick)
            # Re-subscribe after a (re)connect — the client re-auths but does
            # not restore subscriptions itself.
            ws.register_callback("auth", self._on_auth)
            self._callbacks_registered = True
        return True

    def _subscribe(self, symkeys: set[str]) -> None:
        if not symkeys or self._ws is None:
            return
        symbols = [{"exchange": k.split(":", 1)[0], "symbol": k.split(":", 1)[1]} for k in symkeys]
        try:
            response = self._ws.subscribe(symbols, mode=SUBSCRIBE_MODE)
            accepted = (
                {
                    _symkey(item["exchange"], item["symbol"])
                    for item in (response.get("subscriptions") or [])
                    if isinstance(item, dict)
                    and item.get("status") == "success"
                    and item.get("exchange")
                    and item.get("symbol")
                }
                if isinstance(response, dict)
                else set()
            )
            with self._lock:
                self._subscribed |= accepted & symkeys
        except Exception as e:
            logger.warning("Symbol exit monitor subscribe failed: %s", e)

    def _unsubscribe(self, symkeys: set[str]) -> None:
        if not symkeys or self._ws is None:
            return
        symbols = [{"exchange": k.split(":", 1)[0], "symbol": k.split(":", 1)[1]} for k in symkeys]
        try:
            self._ws.unsubscribe(symbols, mode=SUBSCRIBE_MODE)
        except Exception as e:
            logger.debug("Symbol exit monitor unsubscribe failed: %s", e)
        with self._lock:
            self._subscribed -= symkeys

    def _on_auth(self, data: dict) -> None:
        if data.get("status") != "success":
            return
        with self._lock:
            self._subscribed.clear()
        self.request_sync()

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

        with self._lock:
            current_mode = self._mode()
            matches = [
                (watch_id, state)
                for watch_id, state in self._watches.items()
                if state.get("symbol") == symbol and state.get("exchange") == exchange
            ]
            pending = []
            for watch_id, state in matches:
                # A watch never acts across modes: if the user flipped
                # analyze/live since the watch was placed, skip until the mode
                # matches again (the exit worker repeats this guard).
                if current_mode and state.get("mode") and state.get("mode") != current_mode:
                    continue

                # Entry accepted but not yet filled: there is no position to
                # protect and no entry price to anchor a trail. Resolve the
                # entry against the broker instead of evaluating levels.
                if state.get("status") == "pending":
                    pending.append((watch_id, state))
                    continue

                # Market entries carry no fill price; seed the entry from the
                # first tick so trailing has an anchor to measure from.
                if not _is_usable_price(state.get("entry_price")):
                    state["entry_price"] = ltp
                    try:
                        from database.symbol_exit_db import set_watch_entry_price

                        set_watch_entry_price(watch_id, ltp)
                    finally:
                        self._remove_session("database.symbol_exit_db")

                from services.risk.position import evaluate_position_state

                decision = evaluate_position_state(state, ltp)
                if decision.breached:
                    self._dispatch_exit(watch_id, state, str(decision.reason or "sl"), ltp)
                    continue

                moved = (
                    decision.stop_price != state.get("current_sl")
                    or decision.highest_price != state.get("highest_price")
                    or decision.lowest_price != state.get("lowest_price")
                )
                if moved:
                    state["current_sl"] = decision.stop_price
                    state["highest_price"] = decision.highest_price
                    state["lowest_price"] = decision.lowest_price
                    self._maybe_persist(watch_id, state)

        # Activation resolution runs outside the in-memory lock - it calls the
        # broker, which must not happen while holding the state lock.
        for watch_id, state in pending:
            self._maybe_resolve_pending(watch_id, state)

    def _maybe_resolve_pending(self, watch_id: int, state: dict) -> None:
        """Throttled activation check for a pending (unfilled) entry watch."""
        now = time.monotonic()
        if now - self._last_activate.get(watch_id, 0.0) < PENDING_RESOLVE_COOLDOWN_SEC:
            return
        self._last_activate[watch_id] = now
        try:
            self._resolve_pending(watch_id, state)
        except Exception as e:
            logger.exception("Symbol exit activation check error: %s", e)

    def _resolve_pending(self, watch_id: int, state: dict) -> None:
        """Activate a pending watch once its entry order has filled.

        The authoritative signal is the entry order's own broker state: a
        filled (or partially filled) order activates the watch, a rejected or
        cancelled one without fills drops it. Trades matched to the entry
        resolve partial fills and entries missing from the orderbook.
        """
        watch_mode = state.get("mode")
        current_mode = self._mode()
        if watch_mode and current_mode and watch_mode != current_mode:
            return

        api_key = self._resolve_api_key()
        if not api_key:
            return

        entry = self._find_entry_order(state, api_key)
        verdict = _classify_entry(entry) if entry is not None else "open"
        if entry is not None and verdict == "filled":
            if not self._position_open(state, api_key):
                return  # Filled orders can precede the positionbook update.
            self._seed_fill_price(watch_id, state, entry.get("average_price"))
            self._set_active(watch_id, state)
            return
        # Normalized orderbooks often omit filled_quantity. Match trades
        # to THIS entry; aggregate positions may belong to another order.
        trades = self._entry_trades(state, api_key)
        if trades:
            if not self._position_open(state, api_key):
                return
            quantity = sum(float(t["quantity"]) for t in trades)
            price = sum(float(t["quantity"]) * float(t["average_price"]) for t in trades)
            self._seed_fill_price(watch_id, state, price / quantity)
            self._set_active(watch_id, state)
        elif verdict == "dead" and trades is not None:
            self._drop_cancelled(watch_id, state)

    def _entry_trades(self, state: dict, api_key: str) -> list[dict] | None:
        """Executed fills for the guarded order; None means lookup unavailable."""
        from services.tradebook_service import get_tradebook

        try:
            ok, response, _ = get_tradebook(api_key=api_key)
            rows = response.get("data") if isinstance(response, dict) else None
            if not ok or not isinstance(rows, list):
                return None
            fills = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("orderid") or row.get("order_id") or "") != str(state["order_id"]):
                    continue
                if (
                    row.get("symbol") != state["symbol"]
                    or row.get("exchange") != state["exchange"]
                    or row.get("action") != state["side"]
                    or row.get("product") != state["product"]
                ):
                    continue
                if _is_usable_price(row.get("quantity")) and _is_usable_price(
                    row.get("average_price")
                ):
                    fills.append(row)
            return fills
        except Exception as exc:
            logger.debug("Symbol exit tradebook fetch error: %s", exc)
            return None
        finally:
            self._remove_session("services.tradebook_service")

    def _seed_fill_price(self, watch_id: int, state: dict, price) -> None:
        if not _is_usable_price(price):
            return
        from database.symbol_exit_db import set_watch_entry_price

        try:
            set_watch_entry_price(watch_id, float(price))
            with self._lock:
                state["entry_price"] = float(price)
        finally:
            self._remove_session("database.symbol_exit_db")

    def _find_entry_order(self, state: dict, api_key: str) -> dict | None:
        """Locate the guarded entry order inside the broker orderbook."""
        from services.orderbook_service import get_orderbook

        try:
            ok, resp, _code = get_orderbook(api_key=api_key)
        except Exception as e:
            logger.debug("Symbol exit orderbook fetch error: %s", e)
            return None
        finally:
            self._remove_session("services.orderbook_service")
        if not ok or not isinstance(resp, dict):
            return None
        orders = (resp.get("data") or {}).get("orders")
        if not isinstance(orders, list):
            return None
        target = str(state.get("order_id") or "")
        for entry in orders:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("orderid") or entry.get("order_id") or "") == target:
                return entry
        return None

    def _position_open(self, state: dict, api_key: str) -> bool:
        net = self._net_qty(state, api_key)
        if net is None:
            return False
        side = (state.get("side") or "BUY").upper()
        return (net > 0 and side == "BUY") or (net < 0 and side == "SELL")

    def _set_active(self, watch_id: int, state: dict) -> None:
        with self._lock:
            state["status"] = "active"
        try:
            from database.symbol_exit_db import set_watch_active

            set_watch_active(watch_id)
        finally:
            self._remove_session("database.symbol_exit_db")
        logger.info(
            "Symbol exit watch %d activated - entry %s filled",
            watch_id,
            state.get("order_id"),
        )

    def _drop_cancelled(self, watch_id: int, state: dict) -> None:
        """Drop a watch whose entry was rejected/cancelled - nothing will fill."""
        self._drop_in_memory(watch_id)
        try:
            from database.symbol_exit_db import cancel_watch

            cancel_watch(state.get("order_id", ""), state.get("mode", "analyze"))
            self.request_sync()
        finally:
            self._remove_session("database.symbol_exit_db")
        logger.info(
            "Symbol exit watch %d dropped - entry %s rejected/cancelled",
            watch_id,
            state.get("order_id"),
        )

    def _maybe_persist(self, watch_id: int, state: dict) -> None:
        """Rate-limit trailing-stop writes so a fast market cannot storm SQLite."""
        now = time.monotonic()
        if now - self._last_persist.get(watch_id, 0.0) < PERSIST_THROTTLE_SEC:
            return
        self._last_persist[watch_id] = now
        try:
            from database.symbol_exit_db import update_watch_tick

            update_watch_tick(
                watch_id,
                state.get("current_sl"),
                state.get("highest_price"),
                state.get("lowest_price"),
            )
        finally:
            self._remove_session("database.symbol_exit_db")

    # ------------------------------------------------------------------ exit
    def _dispatch_exit(self, watch_id: int, state: dict, reason: str, ltp: float) -> None:
        now = time.monotonic()
        if watch_id in self._exit_inflight:
            return
        if now - self._last_exit_attempt.get(watch_id, 0.0) < EXIT_RETRY_COOLDOWN_SEC:
            return
        self._last_exit_attempt[watch_id] = now
        self._exit_inflight.add(watch_id)
        snapshot = dict(state)
        Thread(
            target=self._exit_worker,
            args=(watch_id, snapshot, reason, ltp),
            name=f"symbol-exit-{state.get('symbol')}",
            daemon=True,
        ).start()

    def _exit_worker(self, watch_id: int, state: dict, reason: str, ltp: float) -> None:
        symbol = state.get("symbol")
        try:
            # Detection->exit race: only act if the GLOBAL mode still matches
            # this watch's mode, so a watch never exits the other mode's
            # position. Exit routing follows get_analyze_mode().
            watch_mode = state.get("mode")
            current_mode = self._mode()
            if watch_mode and current_mode and watch_mode != current_mode:
                logger.info(
                    "Symbol exit for %s skipped - mode changed (watch=%s, current=%s)",
                    symbol,
                    watch_mode,
                    current_mode,
                )
                return

            api_key = self._resolve_api_key()
            if not api_key:
                logger.error("Symbol exit for %s: no api key - will retry", symbol)
                return

            if not self._cancel_entry_remainder(state, api_key):
                return  # Keep protection until the unfilled remainder stops working.
            net_qty = self._net_qty(state, api_key)
            if net_qty is None:
                logger.debug(
                    "Symbol exit for %s skipped - positionbook unavailable (kept open, will retry)",
                    symbol,
                )
                return

            sizing = _exit_sizing(state, net_qty)
            if sizing is None:
                self._closed(watch_id, "flat", ltp)
                logger.info("Symbol exit for %s already flat - cleared", symbol)
                return

            action, qty = sizing
            ok, resp, _code = self._place_exit(state, action, qty, api_key)
            if ok:
                self._closed(watch_id, reason, ltp)
                logger.info(
                    "Symbol exit (%s) %s %s %d @~%.2f",
                    reason,
                    action,
                    symbol,
                    qty,
                    ltp,
                )
            else:
                msg = resp.get("message") if isinstance(resp, dict) else resp
                logger.error("Symbol exit FAILED for %s - still OPEN, will retry: %s", symbol, msg)
        except Exception as e:
            logger.exception("Symbol exit error for %s: %s", symbol, e)
        finally:
            self._exit_inflight.discard(watch_id)
            self._remove_session("database.symbol_exit_db")
            self._remove_session("database.settings_db")
            self._remove_session("database.auth_db")
            self._remove_session("database.user_db")

    def _cancel_entry_remainder(self, state: dict, api_key: str) -> bool:
        """Do not leave a partially filled entry working after its risk exit."""
        entry = self._find_entry_order(state, api_key)
        if entry is None:
            return True  # Older filled entries may have aged out of the daily book.
        status_only = {k: v for k, v in entry.items() if k != "filled_quantity"}
        if _classify_entry(status_only) != "open":
            return True
        from database.auth_db import get_auth_token_broker
        from services.cancel_order_service import cancel_order

        try:
            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token or not broker:
                return False
            ok, _, _ = cancel_order(
                state["order_id"], api_key=api_key, auth_token=auth_token, broker=broker
            )
            if not ok:
                return False
            updated = self._find_entry_order(state, api_key)
            return (
                updated is not None
                and _classify_entry({k: v for k, v in updated.items() if k != "filled_quantity"})
                != "open"
            )
        finally:
            self._remove_session("services.cancel_order_service")

    def _place_exit(
        self, state: dict, action: str, qty: int, api_key: str
    ) -> tuple[bool, dict, int]:
        from database.auth_db import get_auth_token_broker
        from services.place_order_service import place_order

        try:
            order_data = {
                "strategy": "symbol-exit-watch",
                "exchange": state["exchange"],
                "symbol": state["symbol"],
                "action": action,
                "quantity": int(qty),
                "pricetype": "MARKET",
                "product": state["product"],
            }
            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token or not broker:
                return (
                    False,
                    {"status": "error", "message": "Broker authentication unavailable"},
                    403,
                )
            # Automatic protection bypasses the semi-auto entry queue. Keep
            # the API key so analyze mode still routes to the sandbox.
            return place_order(order_data, api_key=api_key, auth_token=auth_token, broker=broker)
        finally:
            self._remove_session("services.place_order_service")

    def _net_qty(self, state: dict, api_key: str) -> int | None:
        """Signed net position for the watch's symbol/exchange/product.

        Returns None when the position could not be determined (broker error,
        malformed or unsuccessful response) so the caller keeps the watch open
        and retries - a lookup failure is never the same as a flat position.
        """
        from services.positionbook_service import get_positionbook

        try:
            ok, resp, _code = get_positionbook(api_key=api_key)
        except Exception as e:
            logger.debug("Symbol exit positionbook fetch error: %s", e)
            return None
        finally:
            self._remove_session("services.positionbook_service")
        if not ok or not isinstance(resp, dict):
            logger.debug("Symbol exit positionbook response not usable")
            return None
        ex = (state.get("exchange") or "").upper()
        pr = (state.get("product") or "").upper()
        data = resp.get("data")
        if not isinstance(data, list):
            return None
        for p in data:
            if not isinstance(p, dict):
                continue
            if (
                p.get("symbol") == state.get("symbol")
                and (p.get("exchange") or "").upper() == ex
                and (p.get("product") or "").upper() == pr
            ):
                try:
                    return int(float(p.get("quantity") or 0))
                except (TypeError, ValueError):
                    return None
        return 0

    def _drop_in_memory(self, watch_id: int) -> None:
        """Remove a watch from evaluation, taking its bookkeeping with it."""
        with self._lock:
            self._watches.pop(watch_id, None)
            # Per-watch bookkeeping must leave with the watch, or a long-lived
            # worker accumulates one (cooldown, persist throttle) entry per
            # closed position forever.
            self._exit_inflight.discard(watch_id)
            self._last_exit_attempt.pop(watch_id, None)
            self._last_persist.pop(watch_id, None)
            self._last_activate.pop(watch_id, None)

    def _closed(self, watch_id: int, reason: str, ltp: float) -> None:
        """Mark the watch executed and drop it from evaluation."""
        self._drop_in_memory(watch_id)
        try:
            from database.symbol_exit_db import mark_watch_executed

            mark_watch_executed(watch_id, reason, ltp)
            self.request_sync()
        finally:
            self._remove_session("database.symbol_exit_db")

    # ------------------------------------------------------------------ helpers
    def _mode(self) -> str | None:
        """Current trading mode ('analyze'/'live'). Not cached (see scalping)."""
        try:
            from database.settings_db import get_analyze_mode

            return "analyze" if get_analyze_mode() else "live"
        except Exception:
            return None
        finally:
            self._remove_session("database.settings_db")

    def _resolve_api_key(self) -> str | None:
        """First usable api key for a background service (no session context)."""
        try:
            from database.auth_db import get_first_available_api_key

            return get_first_available_api_key()
        finally:
            self._remove_session("database.auth_db")

    def _remove_session(self, module_name: str) -> None:
        try:
            import importlib

            mod = importlib.import_module(module_name)
            sess = getattr(mod, "db_session", None)
            if sess is not None:
                sess.remove()
        except Exception:
            pass


# Module-level singleton + accessors.
symbol_exit_monitor = SymbolExitMonitor()


def get_symbol_exit_monitor() -> SymbolExitMonitor:
    return symbol_exit_monitor


def start_symbol_exit_monitor() -> None:
    """Start (initial sync) the singleton monitor. Safe to call multiple times."""
    get_symbol_exit_monitor().start()


def register_exit_watch(
    order_data: dict,
    risk_meta: dict,
    order_id: str,
    mode: str,
) -> dict | None:
    """Persist an exit watch for a placed entry order, if it carried risk legs.

    ``risk_meta`` holds the calculator's ``stoploss`` / ``target`` /
    ``trailing_stoploss`` as entered on the placeorder request. Returns the
    stored row; None when there is nothing to watch.
    """
    stop_loss = risk_meta.get("stoploss")
    target = risk_meta.get("target")
    trailing_step = risk_meta.get("trailing_stoploss")
    if not any(v for v in (stop_loss, target, trailing_step)):
        return None

    try:
        from database.symbol_exit_db import create_exit_watch

        watch = create_exit_watch(
            {
                "symbol": order_data.get("symbol"),
                "exchange": order_data.get("exchange"),
                "product": order_data.get("product"),
                "side": order_data.get("action"),
                "mode": mode,
                "order_id": str(order_id),
                "strategy": order_data.get("strategy", ""),
                "quantity": int(order_data.get("quantity") or 0),
                "stop_loss": stop_loss,
                "target": target,
                "trailing_step": trailing_step,
            }
        )
        # Reconcile the feed on the background worker so the order request
        # returns immediately (sync() blocks on WS subscribe acks).
        get_symbol_exit_monitor().request_sync()
        return watch
    except Exception as e:
        logger.exception("Failed to register symbol exit watch: %s", e)
        return None
    finally:
        try:
            get_symbol_exit_monitor()._remove_session("database.symbol_exit_db")
        except Exception:
            pass
