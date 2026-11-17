# =============================================================================
# openalgo-strategy-kit 1.0.0 BEGIN
#
# The engine that runs the settings and signals above. Every strategy the
# python-strategy skill builds carries this same block, so change the strategy
# above it, never in here. To take a newer kit, replace the whole block:
#     uv run python .claude/skills/python-strategy/kit_sync.py --write <this file>
#
# Stops, targets, trailing stops and the daily loss and profit limits are
# decided by OpenAlgo's own risk engine (services/risk), the same one behind
# the scalping terminal and the strategy module. The skill's backtest.py
# replays history through these same functions.
# =============================================================================

import logging
import math
import os
import signal as _os_signal
import sys
import threading
import time as _clock
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np  # noqa: F811 (a strategy may import it above too)
import pandas as pd  # noqa: F811 (a strategy may import it above too)
from openalgo import api as _OpenAlgoClient

KIT_VERSION = "1.0.0"
IST = ZoneInfo("Asia/Kolkata")
SIGNAL_COLUMNS = ("long_entry", "long_exit", "short_entry", "short_exit")
log = logging.getLogger("strategy")
STOP = threading.Event()
_S = globals()


def _load_risk_core():
    """Import services.risk from the OpenAlgo folder this file runs in."""
    here = Path(__file__).resolve()
    for root in (Path.cwd(), *here.parents):
        if (root / "services" / "risk" / "__init__.py").is_file():
            if str(root) not in sys.path:
                sys.path.append(str(root))
            break
    try:
        import services.risk as core
    except ImportError as exc:
        raise SystemExit(
            "This strategy uses OpenAlgo's own stop loss, target and trailing stop engine, "
            "so it must run from inside the OpenAlgo folder. It does when hosted at /python. "
            "To run it yourself, start it from the OpenAlgo folder with uv run."
        ) from exc
    return core


risk = _load_risk_core()


# ---------------------------------------------------------------------------
# Logging: one line per event, IST timestamps, stdout (the /python log file)
# ---------------------------------------------------------------------------


class _ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 (logging API name)
        return datetime.fromtimestamp(record.created, IST).strftime("%Y-%m-%d %H:%M:%S")


def _setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ISTFormatter("%(asctime)s IST | %(levelname)-7s | %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    for noisy in ("httpx", "httpcore", "websocket", "urllib3", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Stopping: /python's Stop button and schedule stop send SIGTERM, then kill
# the process 5 seconds later. Every wait goes through pause() so a stop is
# noticed at once instead of after a long sleep.
# ---------------------------------------------------------------------------


def _on_stop_signal(signum, _frame):
    if not STOP.is_set():
        log.info("Stop requested. Shutting down.")
    STOP.set()


def pause(seconds):
    """Wait up to `seconds`. Returns True when a stop was requested."""
    return STOP.wait(max(0.0, float(seconds)))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def setting(name, default=None):
    """A setting from the top of the file, or `default` when it is not there."""
    value = _S.get(name, default)
    return default if value is None and default is not None else value


def hhmm(text):
    """'09:30' -> time(9, 30). None and '' stay None."""
    if text in (None, ""):
        return None
    if isinstance(text, dtime):
        return text
    hours, minutes = str(text).strip().split(":")
    return dtime(int(hours), int(minutes))


_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "60m": 60}


def interval_step(interval):
    if interval == "D":
        return timedelta(days=1)
    if interval not in _MINUTES:
        raise SystemExit(
            f"INTERVAL {interval!r} is not supported. Use one of {', '.join([*_MINUTES, 'D'])}."
        )
    return timedelta(minutes=_MINUTES[interval])


@dataclass(frozen=True)
class Config:
    name: str
    symbol: str
    exchange: str
    product: str
    interval: str
    quantity: int
    sides: str
    stop_loss_pct: float | None
    stop_loss_points: float | None
    target_pct: float | None
    target_points: float | None
    trail_pct: float | None
    trail_points: float | None
    entry_start: dtime | None
    entry_end: dtime | None
    square_off: dtime | None
    decision_time: dtime | None
    max_trades_per_day: int | None
    max_loss_per_day: float | None
    max_profit_per_day: float | None
    close_on_stop: bool
    warmup_bars: int
    bar_delay_seconds: float


def strategy_name():
    """The name orders are tagged with: the one given at /python, else the
    STRATEGY_NAME setting, else the file name."""
    return str(
        os.getenv("STRATEGY_NAME")
        or setting("STRATEGY_NAME")
        or Path(sys.argv[0] if sys.argv and sys.argv[0] else __file__).stem
    )


def load_config():
    name = strategy_name()
    interval = str(setting("INTERVAL", "5m"))
    interval_step(interval)
    sides = str(setting("SIDES", "long")).lower()
    if sides not in ("long", "short", "both"):
        raise SystemExit(f'SIDES must be "long", "short" or "both", not {sides!r}.')
    cfg = Config(
        name=str(name),
        symbol=str(setting("SYMBOL", "")).upper(),
        exchange=str(setting("EXCHANGE", "NSE")).upper(),
        product=str(setting("PRODUCT", "MIS")).upper(),
        interval=interval,
        quantity=int(setting("QUANTITY", 1)),
        sides=sides,
        stop_loss_pct=setting("STOP_LOSS_PCT"),
        stop_loss_points=setting("STOP_LOSS_POINTS"),
        target_pct=setting("TARGET_PCT"),
        target_points=setting("TARGET_POINTS"),
        trail_pct=setting("TRAIL_PCT"),
        trail_points=setting("TRAIL_POINTS"),
        entry_start=hhmm(setting("ENTRY_START")),
        entry_end=hhmm(setting("ENTRY_END")),
        square_off=hhmm(setting("SQUARE_OFF")),
        decision_time=hhmm(setting("DECISION_TIME", "15:20")),
        max_trades_per_day=setting("MAX_TRADES_PER_DAY"),
        max_loss_per_day=setting("MAX_LOSS_PER_DAY"),
        max_profit_per_day=setting("MAX_PROFIT_PER_DAY"),
        close_on_stop=bool(setting("CLOSE_ON_STOP", False)),
        warmup_bars=int(setting("WARMUP_BARS", 200)),
        bar_delay_seconds=float(setting("BAR_DELAY_SECONDS", 2.0)),
    )
    if cfg.product not in ("MIS", "CNC", "NRML"):
        raise SystemExit(f"PRODUCT must be MIS, CNC or NRML, not {cfg.product!r}.")
    if cfg.quantity <= 0:
        raise SystemExit("QUANTITY must be a positive whole number.")
    return cfg


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def now_ist():
    return datetime.now(IST)


def _aware(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)


def calendar_exchange(exchange):
    """The exchange /python should gate this strategy's schedule on."""
    return {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)


def _session_close(exchange):
    return {"MCX": dtime(23, 30), "CDS": dtime(17, 0), "BCD": dtime(17, 0)}.get(
        calendar_exchange(exchange), dtime(15, 30)
    )


def closed_bars(df, interval, now, exchange="NSE"):
    """Only the bars that have finished. Brokers differ on whether the bar
    still forming is included, so this is decided from each bar's end time,
    never by assuming the last row is the forming one."""
    if df is None or len(df) == 0:
        return df
    if interval == "D":
        last = df.index[-1]
        if last.date() >= now.date() and now.time() < _session_close(exchange):
            return df.iloc[:-1]
        return df
    index = df.index
    index = index.tz_localize(IST) if index.tz is None else index.tz_convert(IST)
    return df[np.asarray(index + interval_step(interval) <= now)]


# ---------------------------------------------------------------------------
# OpenAlgo connection
# ---------------------------------------------------------------------------


def ok(response):
    return isinstance(response, dict) and response.get("status") == "success"


def why(response):
    if isinstance(response, dict):
        message = response.get("message") or response.get("error") or response
        return str(message)[:300]
    return str(response)[:300]


def connect():
    """An OpenAlgo client from the connection settings at the top of the file
    (API_KEY, HOST, WEBSOCKET_URL), falling back to what /python provides."""
    api_key = str(setting("API_KEY") or os.getenv("OPENALGO_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit(
            "No OpenAlgo API key. /python provides it once a key exists at /apikey. "
            "Anywhere else, copy the key from /apikey into API_KEY at the top of the file."
        )
    host = str(
        setting("HOST")
        or os.getenv("HOST_SERVER")
        or os.getenv("OPENALGO_HOST")
        or "http://127.0.0.1:5000"
    )
    ws_url = str(setting("WEBSOCKET_URL") or os.getenv("WEBSOCKET_URL") or "").strip() or (
        f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"
    )
    return _OpenAlgoClient(
        api_key=api_key, host=host.strip().rstrip("/"), ws_url=ws_url, timeout=10.0
    )


def check_connection(client):
    """Confirms OpenAlgo answers with this key and says where orders go."""
    status = client.analyzerstatus()
    if not ok(status):
        raise SystemExit(
            f"OpenAlgo did not accept the request ({why(status)}). Check that OpenAlgo is "
            "running, that you are logged in to your broker, and that the API key at "
            "/apikey is the current one."
        )
    if status.get("data", {}).get("analyze_mode"):
        log.info("Orders go to the Sandbox: analyzer mode is on. No real orders are placed.")
    else:
        log.warning("Orders go to your broker: live mode. These are real orders.")


def check_calendar(exchange):
    """Warn when /python gates this strategy on another exchange's calendar."""
    host_exchange = os.getenv("OPENALGO_STRATEGY_EXCHANGE")
    expected = calendar_exchange(exchange)
    if host_exchange and host_exchange.upper() != expected:
        log.warning(
            "This strategy trades on %s but /python schedules it on the %s calendar. "
            "Open the strategy's Schedule at /python and set the exchange to %s, or it "
            "may run while %s is closed or stay stopped while it is open.",
            exchange,
            host_exchange,
            expected,
            exchange,
        )


def instrument(client, symbol, exchange):
    """Lot size and tick size for a symbol, refusing an unknown symbol."""
    info = client.symbol(symbol=symbol, exchange=exchange)
    if not ok(info) or not info.get("data"):
        raise SystemExit(
            f"{symbol} was not found on {exchange} ({why(info)}). Check the spelling against "
            "OpenAlgo's symbol format (docs/prompt/symbol-format.md) and that today's master "
            "contract has downloaded."
        )
    data = info["data"]
    lot = int(float(data.get("lotsize") or 1)) or 1
    tick = float(data.get("tick_size") or 0.05) or 0.05
    return lot, tick


def expiry_dates(client, underlying, exchange, kind="options"):
    """Upcoming expiries, nearest first, as dates."""
    reply = client.expiry(symbol=underlying, exchange=exchange, instrumenttype=kind)
    if not ok(reply) or not reply.get("data"):
        raise SystemExit(f"No {kind} expiries found for {underlying} on {exchange}: {why(reply)}")
    today = now_ist().date()
    dates = sorted({datetime.strptime(text.upper(), "%d-%b-%y").date() for text in reply["data"]})
    return [d for d in dates if d >= today]


def pick_expiry(client, underlying, exchange, kind="options", which="nearest", roll_days=0):
    """'nearest', 'next', or an explicit DDMMMYY. Returns DDMMMYY ('25AUG26').

    roll_days skips an expiry that is that many days away or fewer, so a
    futures strategy does not open a contract about to expire."""
    if which not in ("nearest", "next"):
        return str(which).upper()
    today = now_ist().date()
    dates = [
        d
        for d in expiry_dates(client, underlying, exchange, kind)
        if (d - today).days > int(roll_days or 0) or not roll_days
    ]
    index = 0 if which == "nearest" else 1
    if len(dates) <= index:
        raise SystemExit(f"Not enough upcoming {kind} expiries for {underlying} on {exchange}.")
    return dates[index].strftime("%d%b%y").upper()


def futures_symbol(underlying, expiry_ddmmmyy):
    """OpenAlgo futures symbol: NIFTY + 25AUG26 + FUT."""
    return f"{underlying.upper()}{expiry_ddmmmyy.upper()}FUT"


# ---------------------------------------------------------------------------
# Prices: streamed over the WebSocket, with a quote request as the fallback
# when no tick has arrived recently (feed down, or a quiet instrument)
# ---------------------------------------------------------------------------


class Prices:
    def __init__(self, client, instruments, stale_after=10.0, poll_every=5.0):
        self.client = client
        self.instruments = [(e.upper(), s.upper()) for e, s in instruments]
        self.stale_after = stale_after
        self.poll_every = poll_every
        self.streaming = False
        self._lock = threading.Lock()
        self._last = {}
        self._polled = {}

    def start(self):
        try:
            if self.client.connect():
                self.streaming = bool(
                    self.client.subscribe_ltp(
                        [{"exchange": e, "symbol": s} for e, s in self.instruments],
                        on_data_received=self._on_tick,
                    )
                )
        except Exception:
            log.exception("The live price stream could not start")
        if self.streaming:
            log.info("Streaming live prices for %s", ", ".join(s for _, s in self.instruments))
        else:
            log.warning(
                "Live prices are not streaming, so prices are read by quote request every "
                "%.0f seconds instead. Check that the WebSocket server is running.",
                self.poll_every,
            )

    def add(self, exchange, symbol):
        key = (exchange.upper(), symbol.upper())
        if key in self.instruments:
            return
        self.instruments.append(key)
        if self.streaming:
            try:
                self.client.subscribe_ltp(
                    [{"exchange": key[0], "symbol": key[1]}], on_data_received=self._on_tick
                )
            except Exception:
                log.exception("Could not subscribe to %s", key[1])

    def _on_tick(self, message):
        # Runs on the SDK's WebSocket thread: store the price and return.
        try:
            key = (str(message["exchange"]).upper(), str(message["symbol"]).upper())
            price = float(message["data"]["ltp"])
        except (KeyError, TypeError, ValueError):
            return
        if price > 0:
            with self._lock:
                self._last[key] = (price, _clock.monotonic())

    def get(self, exchange, symbol):
        key = (exchange.upper(), symbol.upper())
        with self._lock:
            cached = self._last.get(key)
        now = _clock.monotonic()
        if cached and now - cached[1] <= self.stale_after:
            return cached[0]
        if now - self._polled.get(key, 0.0) >= self.poll_every:
            self._polled[key] = now
            quote = self.client.quotes(symbol=key[1], exchange=key[0])
            if ok(quote):
                price = float((quote.get("data") or {}).get("ltp") or 0)
                if price > 0:
                    with self._lock:
                        self._last[key] = (price, now)
                    return price
        return cached[0] if cached else None

    def stop(self):
        try:
            if self.streaming:
                self.client.unsubscribe_ltp(
                    [{"exchange": e, "symbol": s} for e, s in self.instruments]
                )
            self.client.disconnect()
        except Exception:
            log.debug("Price stream shutdown", exc_info=True)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    status: str  # complete, rejected, cancelled, unconfirmed, matched, refused, sent
    price: float | None = None
    order_id: str | None = None


def confirm(client, name, order_id, timeout=15.0):
    """Wait for an order to finish and return its fill."""
    deadline = _clock.monotonic() + timeout
    last_status = ""
    while _clock.monotonic() < deadline:
        reply = client.orderstatus(order_id=order_id, strategy=name)
        if ok(reply):
            data = reply.get("data") or {}
            last_status = str(data.get("order_status") or "").lower()
            if last_status == "complete":
                price = float(data.get("average_price") or data.get("price") or 0) or None
                return Fill("complete", price, order_id)
            if last_status in ("rejected", "cancelled"):
                log.error(
                    "Order %s was %s by the broker: %s",
                    order_id,
                    last_status,
                    data.get("rejection_reason") or data.get("message") or "no reason given",
                )
                return Fill(last_status, None, order_id)
        if pause(0.5):
            break
    log.warning(
        "Order %s was not confirmed within %.0f seconds (last status: %s)",
        order_id,
        timeout,
        last_status or "unknown",
    )
    return Fill("unconfirmed", None, order_id)


def smart_order(client, name, symbol, exchange, product, action, quantity, position_size, why_):
    """Move the broker position in this symbol to `position_size` (an entry).

    A smart order compares with what the broker holds, so repeating it never
    doubles a position. Exits go through flatten(), never through here."""
    reply = client.placesmartorder(
        strategy=name,
        symbol=symbol,
        exchange=exchange,
        action=action,
        price_type="MARKET",
        product=product,
        quantity=int(quantity),
        position_size=int(position_size),
    )
    if not ok(reply):
        log.error("%s order for %s was refused: %s", why_, symbol, why(reply))
        return Fill("refused")
    order_id = reply.get("orderid")
    if not order_id:
        log.info("%s for %s: the broker position already matches, nothing was sent.", why_, symbol)
        return Fill("matched")
    log.info("%s order sent: %s %s %s (order %s)", why_, action, quantity, symbol, order_id)
    return confirm(client, name, order_id)


def flatten(client, name, symbol, exchange, product, why_, held_side="BUY", wait=True):
    """Close whatever the broker holds in this symbol and product, and nothing more.

    quantity=0 with position_size=0 is the one smart order that closes any open
    position, long or short, of any size, and sends nothing when there is none.
    Sending the position's own quantity instead opens a fresh position whenever
    the position was already closed elsewhere (a manual exit, the broker's own
    square-off), because a smart order for size 0 on a flat account places the
    requested quantity as a new trade."""
    reply = client.placesmartorder(
        strategy=name,
        symbol=symbol,
        exchange=exchange,
        action="SELL" if held_side == "BUY" else "BUY",
        price_type="MARKET",
        product=product,
        quantity=0,
        position_size=0,
    )
    if not ok(reply):
        log.error("%s order for %s was refused: %s", why_, symbol, why(reply))
        return Fill("refused")
    order_id = reply.get("orderid")
    if not order_id:
        log.info("%s for %s: nothing is open at the broker, nothing was sent.", why_, symbol)
        return Fill("matched")
    log.info("%s order sent for %s (order %s)", why_, symbol, order_id)
    return confirm(client, name, order_id) if wait else Fill("sent", None, order_id)


def broker_position(client, name, symbol, exchange, product):
    """(net quantity, average price) the broker holds for this symbol and product."""
    reply = client.openposition(strategy=name, symbol=symbol, exchange=exchange, product=product)
    if not ok(reply):
        return None, None
    quantity = int(float(reply.get("quantity") or 0))
    average = None
    if quantity:
        book = client.positionbook()
        for row in (book.get("data") or []) if ok(book) else []:
            if (
                str(row.get("symbol")).upper() == symbol
                and str(row.get("exchange")).upper() == exchange
                and str(row.get("product")).upper() == product
            ):
                average = float(row.get("average_price") or 0) or None
                break
    return quantity, average


# ---------------------------------------------------------------------------
# Risk: translate settings into the risk engine's terms, then let it decide
# ---------------------------------------------------------------------------


def _distance(entry, pct, points):
    if points:
        return float(points)
    if pct:
        return entry * float(pct) / 100.0
    return None


def make_risk(
    identifier,
    side,
    entry,
    quantity,
    stop_pct=None,
    stop_points=None,
    target_pct=None,
    target_points=None,
    trail_pct=None,
    trail_points=None,
):
    """The risk engine's view of a new position. Percentages are of the entry
    price; points win over percentages. A trail starts once price has moved
    one trail distance in favour, then follows the best price at that distance."""
    stop_gap = _distance(entry, stop_pct, stop_points)
    target_gap = _distance(entry, target_pct, target_points)
    trail_gap = _distance(entry, trail_pct, trail_points)
    long_side = side == "BUY"
    stop = None if stop_gap is None else entry - stop_gap if long_side else entry + stop_gap
    target = None if target_gap is None else entry + target_gap if long_side else entry - target_gap
    return risk.PositionRisk(
        identifier=identifier,
        side=side,
        entry_price=entry,
        quantity=quantity,
        stop_price=stop,
        initial_stop_price=stop,
        target_price=target,
        trailing_enabled=bool(trail_gap),
        trail_step=float(trail_gap or 0.0),
        trail_trigger=float(trail_gap or risk.DEFAULT_TRAIL_TRIGGER),
    )


def position_risk(cfg, side, entry, quantity):
    """make_risk from the STOP_LOSS, TARGET and TRAIL settings."""
    return make_risk(
        cfg.symbol,
        side,
        entry,
        quantity,
        cfg.stop_loss_pct,
        cfg.stop_loss_points,
        cfg.target_pct,
        cfg.target_points,
        cfg.trail_pct,
        cfg.trail_points,
    )


def step_risk(state, price):
    """One price through the risk engine. Returns (new state, decision)."""
    decision = risk.evaluate_position(state, price)
    if decision.evaluated:
        state = replace(
            state,
            stop_price=decision.stop_price,
            highest_price=decision.highest_price,
            lowest_price=decision.lowest_price,
        )
    return state, decision


def day_limits(cfg):
    if cfg.max_loss_per_day is None and cfg.max_profit_per_day is None:
        return None
    return risk.AggregateRisk(
        combined_stoploss=cfg.max_loss_per_day, combined_target=cfg.max_profit_per_day
    )


def step_day_limits(state, realized, unrealized):
    decision = risk.evaluate_aggregate(state, realized, unrealized)
    state = replace(
        state,
        peak_pnl=decision.peak_pnl,
        trough_pnl=decision.trough_pnl,
        lock_armed=decision.lock_armed,
        lock_floor=decision.lock_floor,
    )
    return state, decision


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

_warned_columns = set()


def signal_frame(df):
    """signals(df) as four boolean columns aligned to df."""
    produced = _S["signals"](df)
    if isinstance(produced, dict):
        produced = dict(produced)
    elif isinstance(produced, pd.DataFrame):
        produced = {k: produced[k] for k in produced.columns}
    else:
        raise SystemExit("signals(df) must return a DataFrame or a dict of columns.")
    known = [k for k in SIGNAL_COLUMNS if k in produced]
    if not known:
        raise SystemExit(
            f"signals(df) returned {sorted(produced)}; it must return some of "
            f"{', '.join(SIGNAL_COLUMNS)}."
        )
    extra = sorted(set(produced) - set(SIGNAL_COLUMNS) - _warned_columns)
    if extra:
        _warned_columns.update(extra)
        log.warning(
            "signals(df) returned %s, which nothing reads. Only %s act.",
            ", ".join(extra),
            ", ".join(SIGNAL_COLUMNS),
        )
    frame = pd.DataFrame(index=df.index)
    for key in SIGNAL_COLUMNS:
        value = produced.get(key, False)
        if isinstance(value, pd.Series):
            series = value.reindex(df.index)
        elif np.isscalar(value):
            series = pd.Series(value, index=df.index)
        else:
            array = np.asarray(value)
            if len(array) != len(df):
                raise SystemExit(f"signals(df)['{key}'] has {len(array)} rows, df has {len(df)}.")
            series = pd.Series(array, index=df.index)
        frame[key] = series.astype("object").where(series.notna(), False).astype(bool)
    return frame


_said = {}


def say_now_and_then(level, key, message, *args, every=60.0):
    """Log a repeating problem once a minute instead of on every loop."""
    now = _clock.monotonic()
    if now - _said.get(key, -every) >= every:
        _said[key] = now
        log.log(level, message, *args)


def history(client, cfg, start, end, source="api"):
    df = client.history(
        symbol=cfg.symbol,
        exchange=cfg.exchange,
        interval=cfg.interval,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        source=source,
    )
    if not isinstance(df, pd.DataFrame):
        say_now_and_then(
            logging.ERROR,
            "history",
            "History for %s %s was not available: %s",
            cfg.symbol,
            cfg.interval,
            why(df),
        )
        return None
    return df


def with_today(client, cfg, bars, now):
    """Daily bars with today's bar, built from a quote when the broker has
    not published it yet, so a 15:20 decision reads today and not yesterday."""
    if bars is None or len(bars) == 0 or bars.index[-1].date() >= now.date():
        return bars
    quote = client.quotes(symbol=cfg.symbol, exchange=cfg.exchange)
    if not ok(quote):
        return bars
    q = quote.get("data") or {}
    row = {
        "open": q.get("open"),
        "high": q.get("high"),
        "low": q.get("low"),
        "close": q.get("ltp"),
        "volume": q.get("volume", 0),
    }
    if not all(row[k] for k in ("open", "high", "low", "close")):
        return bars
    stamp = pd.Timestamp(now.date())
    if bars.index.tz is not None:
        stamp = stamp.tz_localize(bars.index.tz)
    today = pd.DataFrame([{k: float(v or 0) for k, v in row.items()}], index=[stamp])
    return pd.concat([bars, today[[c for c in today.columns if c in bars.columns]]])


def _warmup_days(cfg):
    if cfg.interval == "D":
        return int(cfg.warmup_bars * 1.6) + 10
    per_day = max(1, 375 // _MINUTES[cfg.interval])
    return math.ceil(cfg.warmup_bars / per_day) + 6


# ---------------------------------------------------------------------------
# Live engine for bar strategies
# ---------------------------------------------------------------------------


@dataclass
class Holding:
    side: str | None = None  # "BUY" long, "SELL" short
    quantity: int = 0
    entry: float = 0.0
    risk: object = None
    retry_exit_at: float = 0.0


def _allowed(cfg, side):
    return cfg.sides == "both" or (cfg.sides == "long") == (side == "BUY")


def _in_entry_window(cfg, moment):
    clock = moment.time()
    if cfg.entry_start and clock < cfg.entry_start:
        return False
    if cfg.entry_end and clock > cfg.entry_end:
        return False
    return not (cfg.square_off and clock >= cfg.square_off)


def prepare(client, cfg):
    """Settle what can only be known from OpenAlgo: the symbol, when the
    strategy picks it at start (resolve_symbol, for futures), and the quantity
    in lots (LOTS) from the instrument's current lot size."""
    if callable(_S.get("resolve_symbol")):
        cfg = replace(cfg, symbol=str(_S["resolve_symbol"](client, cfg)).upper())
    if not cfg.symbol:
        raise SystemExit("SYMBOL is empty and the strategy has no resolve_symbol(client, cfg).")
    lot, _tick = instrument(client, cfg.symbol, cfg.exchange)
    if setting("LOTS") is not None:
        cfg = replace(cfg, quantity=int(setting("LOTS")) * lot)
    if cfg.quantity % lot:
        raise SystemExit(
            f"QUANTITY {cfg.quantity} is not a multiple of the lot size {lot} for "
            f"{cfg.symbol}. Use {lot * max(1, round(cfg.quantity / lot))}, or set LOTS instead."
        )
    return cfg


def run_bar_strategy():
    cfg = load_config()
    client = connect()
    check_connection(client)
    check_calendar(cfg.exchange)
    cfg = prepare(client, cfg)
    log.info(
        "Starting %s: trading %s on %s, %s bars, quantity %s, product %s, sides %s (kit %s)",
        cfg.name,
        cfg.symbol,
        cfg.exchange,
        cfg.interval,
        cfg.quantity,
        cfg.product,
        cfg.sides,
        KIT_VERSION,
    )
    prices = Prices(client, [(cfg.exchange, cfg.symbol)])
    prices.start()
    held = Holding()
    quantity, average = broker_position(client, cfg.name, cfg.symbol, cfg.exchange, cfg.product)
    if quantity:
        side = "BUY" if quantity > 0 else "SELL"
        entry = average or prices.get(cfg.exchange, cfg.symbol) or 0.0
        held = Holding(side, abs(quantity), entry, position_risk(cfg, side, entry, abs(quantity)))
        log.warning(
            "Found an open position of %+d %s at the broker (average %.2f). Managing it "
            "with this strategy's stop loss, target and square-off.",
            quantity,
            cfg.symbol,
            entry,
        )
    limits0 = day_limits(cfg)
    limits, day, realized, trades_today, halted = limits0, None, 0.0, 0, False
    last_bar, next_check, next_reconcile, expected_close = None, 0.0, 0.0, None
    step = interval_step(cfg.interval)

    def reconcile(price):
        """The broker is the record. Adopt a position that appeared (an entry
        confirmed late, a manual trade) and forget one that was closed elsewhere
        (a manual exit, the broker's own square-off)."""
        quantity_now, average_now = broker_position(
            client, cfg.name, cfg.symbol, cfg.exchange, cfg.product
        )
        if quantity_now is None:
            return
        signed = 0 if not held.side else held.quantity * (1 if held.side == "BUY" else -1)
        if quantity_now == signed:
            return
        if quantity_now == 0:
            log.warning(
                "The broker shows no %s position any more (closed outside this "
                "strategy). Stopped managing it.",
                cfg.symbol,
            )
            held.side, held.quantity, held.entry, held.risk = None, 0, 0.0, None
            return
        side_now = "BUY" if quantity_now > 0 else "SELL"
        entry_now = average_now or held.entry or price or 0.0
        log.warning(
            "The broker shows %+d %s, not %+d. Managing the broker's position.",
            quantity_now,
            cfg.symbol,
            signed,
        )
        held.side, held.quantity, held.entry = side_now, abs(quantity_now), entry_now
        held.risk = position_risk(cfg, side_now, entry_now, abs(quantity_now))

    def exit_now(reason, price):
        nonlocal realized
        if _clock.monotonic() < held.retry_exit_at:
            return False
        log.info("EXIT %s %s: %s", held.quantity, cfg.symbol, reason)
        fill = flatten(client, cfg.name, cfg.symbol, cfg.exchange, cfg.product, "Exit", held.side)
        if fill.status == "unconfirmed":
            left, _ = broker_position(client, cfg.name, cfg.symbol, cfg.exchange, cfg.product)
            fill = Fill("complete", price) if left == 0 else fill
        if fill.status not in ("complete", "matched"):
            held.retry_exit_at = _clock.monotonic() + 10.0
            log.error(
                "The exit did not go through, so the position is still open and still "
                "managed. Trying again in 10 seconds."
            )
            return False
        exit_price = fill.price or price or held.entry
        sign = 1 if held.side == "BUY" else -1
        pnl = sign * (exit_price - held.entry) * held.quantity
        realized += pnl
        log.info("Closed at %.2f, P&L %.2f (today %.2f)", exit_price, pnl, realized)
        held.side, held.quantity, held.entry, held.risk = None, 0, 0.0, None
        return True

    def enter_now(side, price):
        nonlocal trades_today
        target = cfg.quantity if side == "BUY" else -cfg.quantity
        log.info("ENTRY %s %s %s near %.2f", side, cfg.quantity, cfg.symbol, price or 0)
        fill = smart_order(
            client,
            cfg.name,
            cfg.symbol,
            cfg.exchange,
            cfg.product,
            side,
            cfg.quantity,
            target,
            "Entry",
        )
        if fill.status in ("unconfirmed", "matched"):
            held_now, average_now = broker_position(
                client, cfg.name, cfg.symbol, cfg.exchange, cfg.product
            )
            if held_now != target:
                log.error(
                    "The entry was not confirmed and the broker shows %s, so no position "
                    "is assumed.",
                    held_now,
                )
                return
            fill = Fill("complete", average_now or price)
        if fill.status != "complete":
            return
        entry = fill.price or price
        held.side, held.quantity, held.entry = side, cfg.quantity, entry
        held.risk = position_risk(cfg, side, entry, cfg.quantity)
        trades_today += 1
        log.info(
            "Entered at %.2f. Stop %s, target %s.",
            entry,
            _fmt(held.risk.stop_price),
            _fmt(held.risk.target_price),
        )

    try:
        while not STOP.is_set():
            now = now_ist()
            if day != now.date():
                day, realized, trades_today, halted, limits = now.date(), 0.0, 0, False, limits0
            price = prices.get(cfg.exchange, cfg.symbol)
            if price is None:
                say_now_and_then(logging.WARNING, "price", "No price for %s yet.", cfg.symbol)
            if _clock.monotonic() >= next_reconcile:
                next_reconcile = _clock.monotonic() + 30.0
                reconcile(price)

            if held.side and price:
                held.risk, decision = step_risk(held.risk, price)
                if decision.breached:
                    exit_now(decision.detail, price)
                elif decision.stop_moved:
                    log.info("Trailing stop moved to %.2f", decision.stop_price)

            if limits is not None and not halted and price:
                open_pnl = 0.0
                if held.side:
                    sign = 1 if held.side == "BUY" else -1
                    open_pnl = sign * (price - held.entry) * held.quantity
                limits, verdict = step_day_limits(limits, realized, open_pnl)
                if verdict.breached:
                    log.warning("Daily limit reached: %s. No more trades today.", verdict.detail)
                    halted = True
            if halted and held.side:
                exit_now("daily limit reached", price)

            if cfg.square_off and now.time() >= cfg.square_off and held.side:
                exit_now("square-off time", price)

            if _clock.monotonic() >= next_check:
                # Between bars, ask again every 3 seconds until the bar the clock
                # says has closed appears; long after the session, once a minute.
                late = expected_close is not None and now > expected_close + 2 * step
                next_check = _clock.monotonic() + (60.0 if late else 3.0)
                daily = cfg.interval == "D"
                if daily and (now.time() < cfg.decision_time or last_bar == now.date()):
                    next_check = _clock.monotonic() + 30.0
                else:
                    raw = history(client, cfg, now - timedelta(days=_warmup_days(cfg)), now)
                    bars = (
                        with_today(client, cfg, raw, now)
                        if daily
                        else closed_bars(raw, cfg.interval, now, cfg.exchange)
                    )
                    if bars is not None and len(bars) > 1:
                        stamp = now.date() if daily else bars.index[-1]
                        if last_bar is None and not daily:
                            log.info(
                                "Waiting for the next %s bar to close. Last closed bar started %s.",
                                cfg.interval,
                                bars.index[-1],
                            )
                        elif stamp != last_bar:
                            _act_on_bar(
                                cfg,
                                bars,
                                held,
                                price,
                                now,
                                trades_today,
                                halted,
                                exit_now,
                                enter_now,
                            )
                        if stamp != last_bar and not daily:
                            expected_close = _aware(bars.index[-1]) + 2 * step
                            wait = (expected_close - now_ist()).total_seconds()
                            next_check = _clock.monotonic() + max(2.0, wait + cfg.bar_delay_seconds)
                        last_bar = stamp
            pause(1.0)
    finally:
        if held.side and cfg.close_on_stop:
            # No waiting for the fill: /python kills the process 5 seconds after Stop.
            flatten(
                client,
                cfg.name,
                cfg.symbol,
                cfg.exchange,
                cfg.product,
                "Close on stop",
                held.side,
                wait=False,
            )
        elif held.side:
            log.warning(
                "Stopped with %s %s %s still open at the broker. It stays open; this "
                "strategy manages it again when started.",
                held.side,
                held.quantity,
                cfg.symbol,
            )
        prices.stop()
        client.close()
        log.info("Stopped. Realized P&L today: %.2f", realized)


def _act_on_bar(cfg, bars, held, price, now, trades_today, halted, exit_now, enter_now):
    row = signal_frame(bars).iloc[-1]
    stamp = bars.index[-1]
    reference = price or float(bars["close"].iloc[-1])
    if held.side == "BUY" and (row.long_exit or (row.short_entry and _allowed(cfg, "SELL"))):
        if not exit_now(f"exit signal on the {stamp} bar", reference):
            return
    elif held.side == "SELL" and (row.short_exit or (row.long_entry and _allowed(cfg, "BUY"))):
        if not exit_now(f"exit signal on the {stamp} bar", reference):
            return
    if held.side or halted or not _in_entry_window(cfg, now):
        return
    if cfg.max_trades_per_day and trades_today >= cfg.max_trades_per_day:
        return
    if row.long_entry and _allowed(cfg, "BUY"):
        enter_now("BUY", reference)
    elif row.short_entry and _allowed(cfg, "SELL"):
        enter_now("SELL", reference)


def _fmt(value):
    return "none" if value is None else f"{value:.2f}"


# ---------------------------------------------------------------------------
# Entry point. /python runs the file with no arguments, so this is the whole
# of how a hosted strategy starts. Backtests run from the skill's backtest.py,
# which imports this file and replays history through the same functions.
# ---------------------------------------------------------------------------


def main():
    _setup_logging()
    _os_signal.signal(_os_signal.SIGTERM, _on_stop_signal)
    _os_signal.signal(_os_signal.SIGINT, _on_stop_signal)
    try:
        (_S.get("run_live") or run_bar_strategy)()
    except SystemExit as stop:
        if stop.code not in (None, 0):
            log.error("%s", stop.code)
            raise SystemExit(1) from None
    except Exception:
        log.exception("The strategy stopped on an unexpected error")
        raise SystemExit(1) from None


# openalgo-strategy-kit 1.0.0 END
if __name__ == "__main__":
    main()
