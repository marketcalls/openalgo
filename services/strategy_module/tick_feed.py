"""Last-traded prices for the strategy module's risk engine, source-agnostic.

The risk engine needs one number per open leg: what is this contract trading at
right now. It must not care whether that number arrived on the websocket feed or
was fetched over REST, and it must be told when the number stopped being
trustworthy. That is the whole contract of this module::

    feed.add_run_subscriptions(run_id, [("NIFTY28MAY2624000CE", "NFO"), ...])
    ...
    price = feed.get_ltp("NIFTY28MAY2624000CE", "NFO")
    ...
    feed.remove_run_subscriptions(run_id)

Where the price came from is reported separately by :meth:`get_source`, and
every change of source is pushed to the engine's ``notify`` hook so it can
update the ``tick_source`` chip and halt a run whose prices have gone stale.

Sources
-------

Per symbol, the source moves ``WS_LIVE -> POLLING -> WS_LIVE``, with ``STALE``
as a terminal state:

* **WS_LIVE** on subscribe, and whenever a websocket tick arrives.
* **POLLING** once no websocket tick has arrived for
  ``STRATEGY_TICK_STALE_THRESHOLD_SEC``. REST multi-quote takes over. The
  websocket subscription is deliberately left in place: it costs nothing and it
  is how the symbol gets promoted back.
* **WS_LIVE** again the moment a tick arrives while polling, which also drops
  the symbol from the next poll cycle.
* **STALE** when *neither* source has produced a price for
  ``STRATEGY_TICK_STALE_FATAL_SEC``. Terminal on purpose: a risk engine that
  halted on stale prices must not silently resume on its own. Recovery is an
  explicit :meth:`clear_stale` call, or dropping and re-adding the symbol.

Threading
---------

This is the module in the strategy package that straddles the eventlet
boundary, so it is worth being explicit (see CLAUDE.md, "Nothing may block or
be blocked across the eventlet boundary").

**Producer side -** :meth:`on_tick`. It is registered as a ``market_data``
callback on ``services/websocket_client.py``. That client currently dispatches
callbacks from a *green* thread, but its ticks originate on the asyncio loop's
**real OS thread**, and one refactor of the dispatcher would put this callback
back on it. So :meth:`on_tick` is written as though it always runs on a real
thread and is allowed to do exactly two things:

* one lockless ``set`` membership test, and
* ``put_nowait`` on a **real** queue from :mod:`utils.real_threading`.

It takes no lock at all. Taking a green lock from a real thread raises
``greenlet.error: Cannot switch to a different thread`` inside the hub and
wedges that thread permanently, which is the failure behind issues #1402,
#1473 and #1569. The membership test needs no lock either: ``key in set`` is a
single GIL-held C operation for string keys, and losing a race against a
concurrent subscribe costs at most one tick, which the next one replaces.

**Consumer side -** :meth:`_run_drain_loop` and :meth:`_run_poll_loop`. Both
run on plain ``threading.Thread``, which eventlet monkey-patches into green
threads. That is the point: they touch the state dicts, call the quote service
over HTTP and invoke the engine's ``notify`` hook, and all of those belong to
the hub. They read the real queue with ``get_nowait()`` plus a short sleep,
never a blocking ``get()``, because a greenlet blocking on a real primitive
stops every other request on the worker.

Everything on the consumer side of the queue is therefore green, and the lock
guarding the state dicts is an ordinary green ``threading.Lock``. It is held
for in-memory bookkeeping only: the websocket subscribe, the REST fetch and the
``notify`` callback all happen after it is released.
"""

from __future__ import annotations

import atexit
import os
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from utils import real_threading as _real_threading
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "POLLING",
    "STALE",
    "WS_LIVE",
    "RiskTickFeed",
    "TickSourceEvent",
    "get_risk_tick_feed",
]

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

#: Prices are arriving on the websocket feed.
WS_LIVE = "ws_live"
#: The websocket has gone quiet for this symbol; REST multi-quote is covering it.
POLLING = "polling"
#: Neither source has produced a price for long enough that the engine must act.
STALE = "stale"

#: Subscription mode. LTP is the cheapest mode the proxy offers and the only
#: field the risk engine reads.
SUBSCRIBE_MODE = "LTP"


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        logger.warning("%s is not a number; using %s", name, default)
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(float(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        logger.warning("%s is not a number; using %s", name, default)
        return default
    return value if value > 0 else default


#: No websocket tick for this long and the symbol falls back to REST.
STALE_THRESHOLD_SEC = _env_float("STRATEGY_TICK_STALE_THRESHOLD_SEC", 10.0)
#: No price from *either* source for this long and the symbol goes STALE.
STALE_FATAL_SEC = _env_float("STRATEGY_TICK_STALE_FATAL_SEC", 60.0)
#: How often the REST fallback runs a cycle.
POLL_INTERVAL_SEC = _env_float("STRATEGY_TICK_POLL_INTERVAL_SEC", 2.0)
#: Most symbols in a single multi-quote call. More than this splits into
#: further calls in the same cycle, so every polling symbol is still covered.
POLL_BATCH_MAX = _env_int("STRATEGY_TICK_POLL_BATCH_MAX", 50)

#: Backoff after a broker rate limit. The feed is marked degraded rather than
#: stopping: the operator needs to know prices are thinning out, and giving up
#: would silently disarm every stop loss riding on this feed.
BACKOFF_SCHEDULE_SEC: tuple[float, ...] = (2.0, 5.0, 10.0, 30.0)

#: Bound on ticks queued for the hub. The producer never blocks, so an
#: unbounded queue would grow until the worker is OOM-killed if the drain loop
#: stalled. Shedding is right for market data: the next tick supersedes the one
#: dropped. Mirrors WebSocketClient.DISPATCH_QUEUE_MAX.
TICK_QUEUE_MAX = 10000

#: Ticks applied per drain pass before yielding, so a fast feed cannot starve
#: the rest of the worker.
DRAIN_BATCH_MAX = 500

#: Idle gap for the drain loop. It empties the queue before sleeping, so this
#: only bounds latency when there is nothing to do.
DRAIN_POLL_SEC = 0.005

#: Used only when nothing is subscribed, so no tick can arrive. Long enough
#: that an idle worker is not waking constantly, short enough that the first
#: subscription of the day is picked up without anyone noticing.
DRAIN_DORMANT_SEC = 0.25

#: Hard ceiling on tracked symbols. Subscriptions are bounded by the operator's
#: own runs, but a runaway caller must not be able to grow a module-level
#: registry without bound in a worker that never restarts.
MAX_TRACKED_SYMBOLS = 1000

#: Longest a loop sleeps before re-checking the stop flag, so stop() is prompt
#: even when the poll interval is long.
_STOP_CHECK_SEC = 0.1


@dataclass(frozen=True, slots=True)
class TickSourceEvent:
    """One source transition, handed to the engine's ``notify`` hook.

    ``symbol`` and ``exchange`` are ``None`` for a feed-wide health change (the
    rate-limit degradation flag flipping), which carries ``source`` ``None``.
    Always delivered on a green thread, after the state lock has been released,
    so the handler is free to emit over SocketIO or touch the database.
    """

    symbol: str | None
    exchange: str | None
    source: str | None
    previous: str | None
    degraded: bool
    at: float


@dataclass(slots=True)
class _SymbolState:
    """Everything tracked for one ``(symbol, exchange)``."""

    symbol: str
    exchange: str
    runs: set[int] = field(default_factory=set)
    source: str = WS_LIVE
    ltp: float | None = None
    #: Monotonic time of the last websocket tick. Seeded at subscribe so the
    #: fallback gets a grace period; it is not a claim that a tick arrived.
    last_ws_at: float = 0.0
    #: Monotonic time of the last price from *any* source. Drives STALE.
    last_price_at: float = 0.0


def _key(symbol: str, exchange: str) -> str:
    return f"{exchange}:{symbol}"


def _normalise(entry: Any) -> tuple[str, str] | None:
    """A ``(symbol, exchange)`` pair out of a tuple or a dict, or None."""
    if isinstance(entry, dict):
        symbol = entry.get("symbol")
        exchange = entry.get("exchange")
    elif isinstance(entry, Sequence) and not isinstance(entry, str) and len(entry) == 2:
        symbol, exchange = entry
    else:
        return None
    if not symbol or not exchange:
        return None
    return str(symbol), str(exchange).upper()


def _price_from(payload: Any) -> float | None:
    """The last traded price out of a tick or a quote row, or None.

    Accepts the websocket tick shape (``{"data": {"ltp": ...}}``) and the plain
    quote shape (``{"ltp": ...}``). Zero and negative are rejected: brokers use
    0 for "no trade yet", and marking a leg at 0 would fire every stop at once.
    """
    if not isinstance(payload, dict):
        return None
    inner = payload.get("data")
    source = inner if isinstance(inner, dict) else payload
    raw = source.get("ltp")
    if raw is None:
        raw = source.get("last_price")
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


class RiskTickFeed:
    """A last-traded price per ``(symbol, exchange)``, however it has to get one.

    One instance per process; use :func:`get_risk_tick_feed`. Every collaborator
    is injectable so the tests can drive it without a broker, a socket or a
    clock that moves on its own.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ws_provider: Callable[[str], Any] | None = None,
        quote_fetcher: Callable[[list[dict[str, str]], str], tuple[bool, dict, int]] | None = None,
        api_key_provider: Callable[[], str | None] | None = None,
        stale_threshold_sec: float = STALE_THRESHOLD_SEC,
        stale_fatal_sec: float = STALE_FATAL_SEC,
        poll_interval_sec: float = POLL_INTERVAL_SEC,
        poll_batch_max: int = POLL_BATCH_MAX,
        max_tracked_symbols: int = MAX_TRACKED_SYMBOLS,
    ) -> None:
        self._clock = clock
        self._ws_provider = ws_provider
        self._quote_fetcher = quote_fetcher
        self._api_key_provider = api_key_provider

        self.stale_threshold_sec = stale_threshold_sec
        self.stale_fatal_sec = stale_fatal_sec
        self.poll_interval_sec = poll_interval_sec
        self.poll_batch_max = max(1, poll_batch_max)
        self.max_tracked_symbols = max_tracked_symbols

        # Green. Guards the three registries below and nothing else; it is
        # never taken by on_tick, and never held across a subscribe, a REST
        # call or a notify.
        self._lock = threading.Lock()
        self._symbols: dict[str, _SymbolState] = {}
        self._runs: dict[int, set[str]] = {}
        #: Read by the producer without a lock. Kept as a separate set rather
        #: than testing against _symbols so the producer never touches a
        #: structure the consumer mutates in place.
        self._wanted: frozenset[str] = frozenset()

        # Green, and held across the yielding websocket subscribe/unsubscribe
        # so two runs starting at once cannot issue conflicting reconciles.
        # Never taken by the producer, by get_ltp or by the drain loop.
        self._ws_lock = threading.Lock()
        self._ws = None
        self._ws_callbacks_registered = False

        # REAL, because on_tick may run on the asyncio loop's OS thread.
        self._queue = _real_threading.Queue(maxsize=TICK_QUEUE_MAX)
        self._dropped = 0

        self._notify: Callable[[TickSourceEvent], None] | None = None
        self._on_price: Callable[[str, str, float], None] | None = None

        self._degraded = False
        self._backoff_index = -1
        self._backoff_until = 0.0

        self._api_key: str | None = None

        self._running = False
        self._drain_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

        atexit.register(self.stop)

    # ------------------------------------------------------------------ hooks

    def set_notify(self, callback: Callable[[TickSourceEvent], None] | None) -> None:
        """Register the engine's source-transition hook (or clear it with None).

        Deliberately a hook rather than a call into the engine: this module must
        not import the engine, and the engine must be replaceable without
        touching the feed. Exactly one hook, so re-registering replaces rather
        than accumulating handlers in a process that never restarts.
        """
        self._notify = callback

    def set_on_price(self, callback: Callable[[str, str, float], None] | None) -> None:
        """Register the per-price hook. One handler, replaced not accumulated.

        This is what drives risk evaluation. ``set_notify`` reports only source
        transitions, which is a display concern; this fires for every usable
        price from either source, which is what a stop is judged against.

        Both the websocket and the REST fallback go through it. A leg that has
        fallen back to polling has to be evaluated on polled prices too, or the
        fallback would keep the price fresh on screen while protecting nothing.
        """
        self._on_price = callback

    # ------------------------------------------------------------ subscriptions

    def add_run_subscriptions(self, run_id: int, symbols: Iterable[Any]) -> list[str]:
        """Hold a subscription for ``run_id`` on each symbol. Never raises.

        Symbols may be ``(symbol, exchange)`` pairs or dicts with those keys.
        Returns the keys that became newly tracked, which is empty when another
        run already held them.

        The bookkeeping happens first and cannot fail; the websocket subscribe
        happens after and is allowed to. A symbol whose subscribe fails is kept
        and pushed straight to POLLING, so REST covers it rather than the leg
        being left with no price at all.
        """
        wanted: list[tuple[str, str]] = []
        for entry in symbols or ():
            pair = _normalise(entry)
            if pair is None:
                logger.warning("Ignoring unusable strategy tick subscription: %r", entry)
                continue
            wanted.append(pair)
        if not wanted:
            return []

        now = self._clock()
        fresh: list[tuple[str, str]] = []
        with self._lock:
            held = self._runs.setdefault(run_id, set())
            for symbol, exchange in wanted:
                key = _key(symbol, exchange)
                state = self._symbols.get(key)
                if state is None:
                    if len(self._symbols) >= self.max_tracked_symbols:
                        logger.error(
                            "Strategy tick feed is tracking %d symbols; refusing %s",
                            len(self._symbols),
                            key,
                        )
                        continue
                    state = _SymbolState(
                        symbol=symbol,
                        exchange=exchange,
                        source=WS_LIVE,
                        last_ws_at=now,
                        last_price_at=now,
                    )
                    self._symbols[key] = state
                    fresh.append((symbol, exchange))
                state.runs.add(run_id)
                held.add(key)
            if not held:
                # Nothing was actually taken (every symbol refused); do not
                # leave an empty run entry behind.
                self._runs.pop(run_id, None)
            self._wanted = frozenset(self._symbols)

        self._ensure_started()
        if fresh:
            self._ws_subscribe(fresh)
        return [_key(s, e) for s, e in fresh]

    def remove_run_subscriptions(self, run_id: int) -> list[str]:
        """Release every subscription ``run_id`` holds. Never raises.

        Returns the keys dropped entirely, that is, the ones no other run was
        still holding. Safe to call for a run that holds nothing, and safe to
        call twice, which matters because it is what a run's error path calls.
        """
        with self._lock:
            keys = self._runs.pop(run_id, set())
            dropped: list[tuple[str, str]] = []
            for key in keys:
                state = self._symbols.get(key)
                if state is None:
                    continue
                state.runs.discard(run_id)
                if not state.runs:
                    del self._symbols[key]
                    dropped.append((state.symbol, state.exchange))
            self._wanted = frozenset(self._symbols)
            empty = not self._symbols

        if dropped:
            self._ws_unsubscribe(dropped)
        if empty:
            # Nothing left to watch. Drop the queued backlog so a run that ends
            # mid-burst does not leave ticks for symbols nobody holds sitting in
            # memory until the next run happens to drain them.
            self._flush_queue()
        return [_key(s, e) for s, e in dropped]

    # ------------------------------------------------------------------ reads

    def get_ltp(self, symbol: str, exchange: str) -> float | None:
        """The last traded price, or None if there has not been one yet.

        Lockless on purpose. This is the hottest call in the risk loop; taking
        the state lock here would make every price read queue behind a poll
        cycle's bookkeeping. The dict lookup and the attribute read are each a
        single atomic operation, and every caller is a greenlet, which cannot be
        preempted mid-statement anyway.
        """
        state = self._symbols.get(_key(symbol, exchange))
        return None if state is None else state.ltp

    def get_source(self, symbol: str, exchange: str) -> str | None:
        """Where this symbol's price is coming from, or None if untracked."""
        state = self._symbols.get(_key(symbol, exchange))
        return None if state is None else state.source

    def is_stale(self, symbol: str, exchange: str) -> bool:
        return self.get_source(symbol, exchange) == STALE

    @property
    def degraded(self) -> bool:
        """True while the REST fallback is backing off a broker rate limit."""
        return self._degraded

    def health(self) -> dict[str, Any]:
        """A snapshot for diagnostics and the ``tick_source`` chip."""
        with self._lock:
            by_source: dict[str, int] = {}
            for state in self._symbols.values():
                by_source[state.source] = by_source.get(state.source, 0) + 1
            tracked = len(self._symbols)
            runs = len(self._runs)
        return {
            "running": self._running,
            "degraded": self._degraded,
            "tracked_symbols": tracked,
            "runs": runs,
            "by_source": by_source,
            "queue_depth": self._queue.qsize(),
            "dropped_ticks": self._dropped,
        }

    def clear_stale(self, symbol: str, exchange: str) -> bool:
        """Take one symbol out of STALE and give it another chance.

        STALE is terminal by design, so getting out of it is an explicit act:
        the engine halted a run on it, and the operator, not a lucky tick, is
        who decides to resume. Returns True if the symbol was STALE.
        """
        now = self._clock()
        with self._lock:
            state = self._symbols.get(_key(symbol, exchange))
            if state is None or state.source != STALE:
                return False
            state.source = POLLING
            state.last_ws_at = now
            state.last_price_at = now
            event = TickSourceEvent(
                symbol=state.symbol,
                exchange=state.exchange,
                source=POLLING,
                previous=STALE,
                degraded=self._degraded,
                at=now,
            )
        self._emit([event])
        return True

    # --------------------------------------------------------------- producer

    def on_tick(self, payload: dict) -> None:
        """Take one websocket tick. **May run on a real OS thread.**

        Hands the tick to the green side and returns. No lock, no state write,
        no logging on the hot path: see this module's docstring for why a real
        thread touching a green primitive is fatal rather than merely slow.

        A tick for a symbol nobody holds costs one set membership test.
        """
        if not isinstance(payload, dict):
            return
        symbol = payload.get("symbol")
        exchange = payload.get("exchange")
        if not symbol or not exchange:
            return
        key = f"{exchange}:{symbol}"
        if key not in self._wanted:
            return
        try:
            self._queue.put_nowait((key, payload, self._clock()))
        except Exception:
            # Full, or the queue is being torn down. Dropping is correct; the
            # next tick carries a newer price than the one shed. The counter is
            # a diagnostic, so a lost increment across threads does not matter
            # and is not worth a lock on this path.
            self._dropped += 1

    # --------------------------------------------------------------- consumer

    def _drain_ticks_once(self, limit: int = DRAIN_BATCH_MAX) -> int:
        """Apply queued ticks. Green side. Returns how many were applied."""
        applied = 0
        events: list[TickSourceEvent] = []
        prices: list[tuple[str, str, float]] = []
        while applied < limit:
            try:
                key, payload, at = self._queue.get_nowait()
            except _real_threading.Empty:
                break
            except Exception:
                break
            applied += 1
            event = self._apply_tick(key, payload, at)
            if event is not None:
                events.append(event)
            price = _price_from(payload)
            if price is not None:
                prices.append((str(payload.get("symbol")), str(payload.get("exchange")), price))
        self._emit(events)
        self._emit_prices(prices)
        return applied

    def _apply_tick(self, key: str, payload: dict, at: float) -> TickSourceEvent | None:
        """Record one tick and say whether it changed the symbol's source."""
        price = _price_from(payload)
        if price is None:
            return None
        with self._lock:
            state = self._symbols.get(key)
            if state is None:
                # Unsubscribed between the enqueue and now. Nothing to do.
                return None
            state.ltp = price
            state.last_ws_at = at
            state.last_price_at = at
            if state.source == POLLING:
                # Promoted, and dropped from the next poll cycle by virtue of
                # no longer being POLLING when that cycle picks its batch.
                state.source = WS_LIVE
                return TickSourceEvent(
                    symbol=state.symbol,
                    exchange=state.exchange,
                    source=WS_LIVE,
                    previous=POLLING,
                    degraded=self._degraded,
                    at=at,
                )
            # STALE is terminal: the price is still recorded, because a real
            # number beats a missing one on the operator's screen, but the
            # source does not recover on its own. See clear_stale().
            return None

    # ------------------------------------------------------------------- poll

    def _poll_once(self) -> int:
        """One REST fallback cycle. Green side. Returns symbols priced.

        Re-evaluates every symbol's source first, so the WS -> POLLING and the
        -> STALE transitions fire on this cadence whether or not the REST call
        is possible, then fetches prices for whatever is POLLING.
        """
        now = self._clock()
        events: list[TickSourceEvent] = []
        with self._lock:
            for state in self._symbols.values():
                event = self._evaluate(state, now)
                if event is not None:
                    events.append(event)
            polling = [
                (s.symbol, s.exchange) for s in self._symbols.values() if s.source == POLLING
            ]
        self._emit(events)

        if not polling:
            return 0
        if now < self._backoff_until:
            # Still serving out a rate-limit backoff. The evaluation above
            # already ran, so symbols keep ageing towards STALE.
            return 0

        priced = 0
        for start in range(0, len(polling), self.poll_batch_max):
            batch = polling[start : start + self.poll_batch_max]
            outcome, rows = self._fetch_quotes(batch)
            if outcome == "rate_limited":
                # The endpoint, not this batch, is the problem. Stop the cycle.
                self._enter_backoff(now)
                break
            if outcome == "abort":
                # Nothing can be fetched at all this cycle (no API key yet).
                break
            if outcome == "error":
                # One batch failed. The others are independent calls and must
                # still be attempted: breaking here would mean a batch that
                # always fails permanently starves every batch behind it, and
                # those symbols would age to STALE on a feed that was working.
                continue
            self._reset_backoff()
            priced += self._apply_quotes(rows)
        return priced

    def _evaluate(self, state: _SymbolState, now: float) -> TickSourceEvent | None:
        """Age one symbol.

        Caller holds the state lock, so this does in-memory bookkeeping only:
        no logging either, because a log record is a file write and a greenlet
        holding this lock across one would stall every price read. The
        transition is logged from :meth:`_emit`, after the release.
        """
        if state.source == STALE:
            return None
        if now - state.last_price_at >= self.stale_fatal_sec:
            previous, state.source = state.source, STALE
            return TickSourceEvent(
                symbol=state.symbol,
                exchange=state.exchange,
                source=STALE,
                previous=previous,
                degraded=self._degraded,
                at=now,
            )
        if state.source == WS_LIVE and now - state.last_ws_at >= self.stale_threshold_sec:
            state.source = POLLING
            return TickSourceEvent(
                symbol=state.symbol,
                exchange=state.exchange,
                source=POLLING,
                previous=WS_LIVE,
                degraded=self._degraded,
                at=now,
            )
        return None

    def _fetch_quotes(self, batch: list[tuple[str, str]]) -> tuple[str, list[dict]]:
        """One multi-quote call. Returns ``(outcome, rows)``.

        ``outcome`` is ``"ok"``, ``"rate_limited"``, ``"error"`` for a failure
        of this batch alone, or ``"abort"`` when nothing can be fetched at all.
        Runs with no lock held: this is a network call, and holding the state
        lock across it would stall every price read for its duration.
        """
        api_key = self._resolve_api_key()
        if not api_key:
            logger.debug("Strategy tick feed: no API key yet; skipping the poll cycle")
            return "abort", []

        symbols = [{"symbol": s, "exchange": e} for s, e in batch]
        try:
            ok, response, status = self._quotes(symbols, api_key)
        except Exception as exc:
            if _looks_rate_limited(exc):
                return "rate_limited", []
            logger.exception("Strategy tick feed multi-quote failed")
            return "error", []

        if status == 429 or (not ok and _looks_rate_limited(response)):
            return "rate_limited", []
        if not ok or not isinstance(response, dict):
            message = response.get("message") if isinstance(response, dict) else response
            logger.warning("Strategy tick feed multi-quote error (%s): %s", status, message)
            if status == 403:
                # The key was rejected. Drop it so the next cycle re-resolves,
                # which is what a daily broker-token rollover needs.
                self._api_key = None
            return "error", []

        rows = response.get("results")
        return "ok", rows if isinstance(rows, list) else []

    def _apply_quotes(self, rows: list[dict]) -> int:
        """Write REST prices onto the symbols still polling. Returns how many."""
        if not rows:
            return 0
        now = self._clock()
        applied = 0
        prices: list[tuple[str, str, float]] = []
        with self._lock:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                exchange = row.get("exchange")
                if not symbol or not exchange:
                    continue
                state = self._symbols.get(_key(str(symbol), str(exchange).upper()))
                if state is None or state.source != POLLING:
                    # Either it was released, or a websocket tick promoted it
                    # while this call was in flight. The tick is newer.
                    continue
                price = _price_from(row)
                if price is None:
                    continue
                state.ltp = price
                state.last_price_at = now
                prices.append((state.symbol, state.exchange, price))
                applied += 1
        # Outside the lock: the hook evaluates risk and may place an order.
        self._emit_prices(prices)
        return applied

    def _enter_backoff(self, now: float) -> None:
        """Advance the rate-limit backoff and mark the feed degraded."""
        self._backoff_index = min(self._backoff_index + 1, len(BACKOFF_SCHEDULE_SEC) - 1)
        delay = BACKOFF_SCHEDULE_SEC[self._backoff_index]
        self._backoff_until = now + delay
        logger.warning("Strategy tick feed rate limited; backing off %.0fs", delay)
        self._set_degraded(True, now)

    def _reset_backoff(self) -> None:
        if self._backoff_index < 0 and not self._degraded:
            return
        self._backoff_index = -1
        self._backoff_until = 0.0
        self._set_degraded(False, self._clock())

    def _set_degraded(self, degraded: bool, now: float) -> None:
        if self._degraded == degraded:
            return
        self._degraded = degraded
        # A feed-wide event: no symbol, no source. The engine uses it for the
        # health chip; per-symbol transitions still arrive separately.
        self._emit(
            [
                TickSourceEvent(
                    symbol=None,
                    exchange=None,
                    source=None,
                    previous=None,
                    degraded=degraded,
                    at=now,
                )
            ]
        )

    # -------------------------------------------------------------- lifecycle

    def _ensure_started(self) -> None:
        """Start the two loops once. Shared for the life of the process."""
        with self._lifecycle_lock:
            if self._running:
                return
            self._running = True
            # Plain threading.Thread, so under eventlet these are GREEN. They
            # touch the state dicts, the quote service and the notify hook, all
            # of which belong to the hub.
            self._drain_thread = threading.Thread(
                target=self._run_drain_loop, name="strategy-tick-drain", daemon=True
            )
            self._drain_thread.start()
            self._poll_thread = threading.Thread(
                target=self._run_poll_loop, name="strategy-tick-poll", daemon=True
            )
            self._poll_thread.start()

    def _run_drain_loop(self) -> None:
        """Apply ticks on the hub. Never a blocking get() on the real queue.

        The idle wait depends on whether anything could arrive at all, not on
        how recently something did. While any symbol is subscribed the loop
        stays at the short interval, because this is the risk path and a tick
        waited on is a stop evaluated late. When nothing is subscribed no tick
        can arrive by definition, so the loop waits far longer.

        That distinction matters because these threads are never stopped when
        the last run ends: they are process-lifetime singletons, and a flat
        short sleep meant a worker that had run one strategy in the morning was
        still waking two hundred times a second at midnight, for a queue that
        could not receive anything.
        """
        while self._running:
            try:
                drained = self._drain_ticks_once()
            except Exception:
                logger.exception("Strategy tick drain loop error")
                time.sleep(DRAIN_POLL_SEC)
                continue
            if drained:
                # More may be waiting; come straight back for it.
                continue
            time.sleep(DRAIN_POLL_SEC if self._wanted else DRAIN_DORMANT_SEC)

    def _run_poll_loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("Strategy tick poll loop error")
            self._sleep(self.poll_interval_sec)

    def _sleep(self, seconds: float) -> None:
        """Sleep in slices so stop() does not wait out a whole poll interval."""
        remaining = seconds
        while self._running and remaining > 0:
            slice_ = min(_STOP_CHECK_SEC, remaining)
            time.sleep(slice_)
            remaining -= slice_

    def stop(self) -> None:
        """Tear everything down: threads, feed subscription, registries.

        Idempotent, and registered with atexit. Everything it releases is a
        file descriptor or a registry entry that would otherwise outlive the
        runs that created it.
        """
        with self._lifecycle_lock:
            self._running = False
            drain, poll = self._drain_thread, self._poll_thread
            self._drain_thread = self._poll_thread = None

        for thread in (drain, poll):
            if thread is not None and thread.is_alive():
                # Green under eventlet, so this join yields; the timeout is
                # there for the dev server, where it is a real thread.
                thread.join(timeout=5)

        with self._lock:
            pairs = [(s.symbol, s.exchange) for s in self._symbols.values()]
            self._symbols.clear()
            self._runs.clear()
            self._wanted = frozenset()
        if pairs:
            self._ws_unsubscribe(pairs)
        self._release_ws()
        self._flush_queue()
        # The handler is itself a registry entry, and an instance that has been
        # stopped must not keep the interpreter's exit list growing.
        try:
            atexit.unregister(self.stop)
        except Exception:
            pass

    def _release_ws(self) -> None:
        """Unregister the callbacks and drop the shared client reference.

        The client itself is a singleton shared with the rest of the platform,
        so this unsubscribes and unhooks rather than disconnecting it: another
        surface may still be streaming on it.
        """
        with self._ws_lock:
            ws, self._ws = self._ws, None
            self._ws_callbacks_registered = False
        if ws is None:
            return
        try:
            ws.unregister_callback("market_data", self.on_tick)
            ws.unregister_callback("auth", self._on_auth)
        except Exception:
            logger.debug("Strategy tick feed could not unregister its callbacks")

    def _flush_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Exception:
                return

    # ------------------------------------------------------------ ws plumbing

    def _ws_subscribe(self, pairs: list[tuple[str, str]]) -> None:
        """Subscribe LTP for newly tracked symbols; degrade to REST on failure.

        Called with no state lock held. The websocket ack can take seconds, and
        while a greenlet waiting on it yields to the hub, holding the state lock
        across it would block every price read.
        """
        symbols = [{"symbol": s, "exchange": e} for s, e in pairs]
        with self._ws_lock:
            client = self._ensure_ws()
            if client is None:
                self._force_polling(pairs, "the feed is not available")
                return
            try:
                result = client.subscribe(symbols, mode=SUBSCRIBE_MODE)
            except Exception:
                logger.exception("Strategy tick feed subscribe raised")
                self._force_polling(pairs, "the subscribe failed")
                return
        if isinstance(result, dict) and result.get("status") == "error":
            self._force_polling(pairs, result.get("message") or "the subscribe was refused")

    def _ws_unsubscribe(self, pairs: list[tuple[str, str]]) -> None:
        symbols = [{"symbol": s, "exchange": e} for s, e in pairs]
        with self._ws_lock:
            client = self._ws
            if client is None:
                return
            try:
                client.unsubscribe(symbols, mode=SUBSCRIBE_MODE)
            except Exception:
                logger.debug("Strategy tick feed unsubscribe failed for %d symbols", len(symbols))

    def _force_polling(self, pairs: list[tuple[str, str]], reason: str) -> None:
        """Send symbols straight to POLLING when the websocket cannot carry them.

        Better than leaving them nominally WS_LIVE for the stale threshold: the
        risk engine gets a price from REST immediately, and the chip tells the
        truth about where it came from.
        """
        now = self._clock()
        events: list[TickSourceEvent] = []
        with self._lock:
            for symbol, exchange in pairs:
                state = self._symbols.get(_key(symbol, exchange))
                if state is None or state.source != WS_LIVE:
                    continue
                state.source = POLLING
                events.append(
                    TickSourceEvent(
                        symbol=state.symbol,
                        exchange=state.exchange,
                        source=POLLING,
                        previous=WS_LIVE,
                        degraded=self._degraded,
                        at=now,
                    )
                )
        if events:
            logger.warning(
                "Strategy tick feed polling %d symbol(s) from the start: %s", len(events), reason
            )
        self._emit(events)

    def _ensure_ws(self):
        """The shared websocket client, or None. Caller holds ``_ws_lock``."""
        if self._ws is not None and getattr(self._ws, "connected", True):
            return self._ws
        api_key = self._resolve_api_key()
        if not api_key:
            return None
        try:
            if self._ws_provider is not None:
                client = self._ws_provider(api_key)
            else:
                from services.websocket_client import get_websocket_client

                client = get_websocket_client(api_key)
        except Exception as exc:
            logger.debug("Strategy tick feed: websocket not available yet: %s", exc)
            return None
        if client is None:
            return None
        self._ws = client
        if not self._ws_callbacks_registered:
            # on_tick is the ONLY thing registered on the feed's own thread, and
            # all it does is enqueue. _on_auth re-subscribes after a reconnect,
            # which the client does not do for us.
            client.register_callback("market_data", self.on_tick)
            client.register_callback("auth", self._on_auth)
            self._ws_callbacks_registered = True
        return self._ws

    def _on_auth(self, data: dict) -> None:
        """Re-subscribe after a reconnect. Runs wherever the client dispatches.

        Snapshot under the state lock, then subscribe outside it. The client
        re-authenticates on reconnect but does not restore subscriptions, so
        without this every symbol would quietly fall back to polling forever.
        """
        if not isinstance(data, dict) or data.get("status") != "success":
            return
        with self._lock:
            pairs = [(s.symbol, s.exchange) for s in self._symbols.values()]
        if pairs:
            self._ws_subscribe(pairs)

    # ---------------------------------------------------------------- helpers

    def _quotes(self, symbols: list[dict[str, str]], api_key: str):
        if self._quote_fetcher is not None:
            return self._quote_fetcher(symbols, api_key)
        from services.quotes_service import get_multiquotes

        return get_multiquotes(symbols=symbols, api_key=api_key)

    def _resolve_api_key(self) -> str | None:
        """The platform API key, cached because the poll cycle is every 2s.

        A single string, cleared on a 403 so the daily broker-token rollover is
        picked up without a restart. The session is removed explicitly: this
        runs on a background thread, where Flask's teardown never fires.
        """
        if self._api_key:
            return self._api_key
        if self._api_key_provider is not None:
            try:
                self._api_key = self._api_key_provider()
            except Exception:
                logger.exception("Strategy tick feed could not resolve an API key")
                self._api_key = None
            return self._api_key

        try:
            from database.auth_db import get_api_key_for_tradingview
            from database.user_db import db_session as user_session
            from database.user_db import find_user_by_username

            try:
                user = find_user_by_username()
                if not user:
                    return None
                self._api_key = get_api_key_for_tradingview(user.username)
            finally:
                user_session.remove()
        except Exception:
            logger.exception("Strategy tick feed could not resolve an API key")
            self._api_key = None
        return self._api_key

    def _emit_prices(self, prices: list[tuple[str, str, float]]) -> None:
        """Hand prices to the risk hook. Green side, always outside every lock.

        Outside the lock because the handler evaluates risk and can place an
        order. A greenlet cannot yield while holding a lock, so calling this
        from inside one would stall the worker for the length of a broker call.
        """
        if not prices:
            return
        callback = self._on_price
        if callback is None:
            return
        for symbol, exchange, price in prices:
            try:
                callback(symbol, exchange, price)
            except Exception:
                # One symbol's evaluation failing must not cost the rest of the
                # batch their prices.
                logger.exception("Strategy tick feed price hook raised for %s", symbol)

    def _emit(self, events: list[TickSourceEvent]) -> None:
        """Log and push transitions. Green side, always outside every lock.

        A handler that raises is logged and skipped: the engine's chip is not
        worth losing the drain loop over.
        """
        if not events:
            return
        callback = self._notify
        for event in events:
            _log_event(event)
            if callback is None:
                continue
            try:
                callback(event)
            except Exception:
                logger.exception("Strategy tick feed notify hook raised")


def _log_event(event: TickSourceEvent) -> None:
    """One line per transition, at the severity the transition deserves."""
    if event.symbol is None:
        logger.warning(
            "Strategy tick feed is %s", "degraded (rate limited)" if event.degraded else "healthy"
        )
        return
    where = f"{event.exchange}:{event.symbol}"
    if event.source == STALE:
        logger.error("Strategy tick feed: %s has no price from either source - STALE", where)
    elif event.source == POLLING:
        logger.warning("Strategy tick feed: %s fell back to REST polling", where)
    else:
        logger.info("Strategy tick feed: %s is back on the websocket feed", where)


def _looks_rate_limited(value: Any) -> bool:
    """Whether a response or an exception is the broker saying "too fast"."""
    if isinstance(value, dict):
        text = str(value.get("message") or "")
    else:
        text = str(value)
    lowered = text.lower()
    return "429" in lowered or "too many requests" in lowered or "rate limit" in lowered


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_feed: RiskTickFeed | None = None
_feed_lock = threading.Lock()


def get_risk_tick_feed() -> RiskTickFeed:
    """The process-wide feed.

    One instance means one pair of loop threads and one websocket subscription
    set for the whole worker, however many runs are open. Building one per run
    would leak a thread pair per run in a Gunicorn worker that never restarts.
    """
    global _feed
    with _feed_lock:
        if _feed is None:
            _feed = RiskTickFeed()
        return _feed
