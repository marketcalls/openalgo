"""Opening Marubozu breakout, comparison version, for the OpenAlgo /python strategy host.

Runs next to marubozu_breakout for a side-by-side test. It differs in two ways:

1. Selection. Instead of opening volume >= 2x the 10-day baseline, a candidate
   needs BOTH:
     - opening-candle traded value (volume x close) >= MIN_CANDLE_VALUE (Rs 1 crore)
     - opening volume >= MIN_REL_VOLUME (1.5x) the 10-day baseline
   The candle shape, minimum size, MAX_ADR_FRACTION limit, ranking, entries,
   stops, targets and daily limits are the same as marubozu_breakout.

2. No orders are sent. Both strategies share one account, so if both bought the
   same stock each would see the other's shares in the position and could sell
   them. This script only tracks its trades from live prices: entry, TP1, stop
   and exit happen at the LTP the moment a level is crossed (polled every
   POLL_SECONDS), the way the sandbox fills an order. Every trade is written to
   marubozu_my_trades.csv, in the same format as marubozu_trades.csv.

The baseline is read from the file marubozu_breakout writes each morning
(marubozu_baseline_YYYYMMDD.json). If it has not appeared by BASELINE_WAIT, this
script builds its own.
"""

import csv
import json
import math
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from openalgo import api

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Settings (override any of these with a /python parameter of the same name)
# ---------------------------------------------------------------------------


def _env(name, default, cast=str):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return cast(value)
    except ValueError:
        print(f"[CONFIG] Invalid value for {name}={value!r}, using default {default!r}", flush=True)
        return default


def _hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


STRATEGY_NAME = "marubozu_with_my_strategy"
EXCHANGE = "NSE"
PRODUCT = "MIS"

# Universe: comma-separated symbols. Default is a liquid large-cap list; replace it
# with your NIFTY 200 (or any) list through the SYMBOLS parameter.
DEFAULT_SYMBOLS = (
    "RELIANCE,HDFCBANK,ICICIBANK,INFY,TCS,SBIN,BHARTIARTL,ITC,LT,KOTAKBANK,"
    "AXISBANK,HINDUNILVR,BAJFINANCE,MARUTI,SUNPHARMA,M&M,TITAN,ULTRACEMCO,"
    "NTPC,POWERGRID,TATASTEEL,ONGC,HCLTECH,WIPRO,TECHM,ADANIENT,ADANIPORTS,"
    "JSWSTEEL,HINDALCO,COALINDIA,BAJAJFINSV,NESTLEIND,ASIANPAINT,GRASIM,CIPLA,"
    "DRREDDY,EICHERMOT,HEROMOTOCO,BPCL,BRITANNIA,TATACONSUM,APOLLOHOSP,"
    "SBILIFE,HDFCLIFE,INDUSINDBK,SHRIRAMFIN,TRENT,BEL,BAJAJ-AUTO,DLF"
)
SYMBOLS = [s.strip().upper() for s in _env("SYMBOLS", DEFAULT_SYMBOLS).split(",") if s.strip()]

# Candle and filter rules
MIN_BODY_PCT = _env("MIN_BODY_PCT", 80.0, float)  # body >= 80% of candle range
MAX_WICK_PCT = _env("MAX_WICK_PCT", 10.0, float)  # each wick <= 10% of range
MIN_REL_VOLUME = _env("MY_MIN_REL_VOLUME", 1.5, float)  # opening vol >= 1.5x baseline
MIN_CANDLE_VALUE = _env("MY_MIN_CANDLE_VALUE", 1e7, float)  # opening value >= Rs 1 crore
BASELINE_DAYS = _env("BASELINE_DAYS", 10, int)  # days for the volume baseline
TOP_N = _env("TOP_N", 5, int)  # candidates kept after ranking
MAX_EXTENSION_PCT = _env("MAX_EXTENSION_PCT", 0.5, float)  # skip if > 0.5% above high
BREAKOUT_BUFFER_PCT = _env("BREAKOUT_BUFFER_PCT", 0.1, float)  # enter at high + 0.1%
MIN_RANGE_PCT = _env("MIN_RANGE_PCT", 0.3, float)  # skip opening candles smaller than this
# Skip opening candles larger than this share of the stock's average daily range
# (high-low % over BASELINE_DAYS). 0 turns the check off.
MAX_ADR_FRACTION = _env("MAX_ADR_FRACTION", 0.8, float)
BIG_CANDLE_PCT = _env("BIG_CANDLE_PCT", 1.5, float)  # above this: pullback entry
PULLBACK_BOUNCE_PCT = _env("PULLBACK_BOUNCE_PCT", 0.1, float)  # bounce off the dip to buy
PULLBACK_TP2_R = _env("PULLBACK_TP2_R", 0.5, float)  # TP2 = candle high + 0.5 x risk

# Trade rules (all percentages are from the fill price)
MAX_STOP_PCT = _env("MAX_STOP_PCT", 0.8, float)  # stop: candle low, or -0.8% if closer
TP1_PCT = _env("TP1_PCT", 0.6, float)  # first target
TP1_FRACTION = _env("TP1_FRACTION", 0.5, float)  # share of the quantity sold at TP1
RUNNER_STOP_PCT = _env("RUNNER_STOP_PCT", 0.4, float)  # stop for the rest after TP1
RUNNER_TARGET_PCT = _env("RUNNER_TARGET_PCT", 0.8, float)  # target for the rest
RISK_PER_TRADE = _env("RISK_PER_TRADE", 1000.0, float)  # rupees risked per trade
MAX_CAPITAL_PER_TRADE = _env("MAX_CAPITAL_PER_TRADE", 100000.0, float)
MARGIN_FACTOR = _env("MARGIN_FACTOR", 1.0, float)  # cash needed = value * factor
MAX_TRADES_PER_DAY = _env("MAX_TRADES_PER_DAY", 3, int)
MAX_DAILY_LOSS = _env("MAX_DAILY_LOSS", 3000.0, float)

# Times (IST)
CANDLE_READY = _hhmm(_env("CANDLE_READY", "09:20"))
ENTRY_CUTOFF = _hhmm(_env("ENTRY_CUTOFF", "11:00"))
SQUARE_OFF = _hhmm(_env("SQUARE_OFF", "15:10"))
# Wait this long for marubozu_breakout's baseline file before building our own.
BASELINE_WAIT = _hhmm(_env("BASELINE_WAIT", "09:17"))

POLL_SECONDS = _env("POLL_SECONDS", 2.0, float)
FILL_TIMEOUT_SECONDS = _env("FILL_TIMEOUT_SECONDS", 30, int)
QUOTE_BATCH = _env("QUOTE_BATCH", 50, int)
HISTORY_RETRIES = _env("HISTORY_RETRIES", 3, int)  # attempts per baseline history call
TICK = 0.05

API_KEY = os.getenv("OPENALGO_API_KEY") or os.getenv("API_KEY", "")
API_HOST = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, f"marubozu_my_state_{date.today():%Y%m%d}.json")
TRADES_CSV = os.path.join(HERE, "marubozu_my_trades.csv")
# Written by marubozu_breakout each morning; read here.
BASELINE_FILE = os.path.join(HERE, f"marubozu_baseline_{date.today():%Y%m%d}.json")

_stop_requested = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_ist():
    return datetime.now(IST)


def log(tag, message):
    print(f"{now_ist():%H:%M:%S} [{tag}] {message}", flush=True)


def round_down_tick(price):
    return math.floor(price / TICK + 1e-9) * TICK


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ok(response):
    return isinstance(response, dict) and response.get("status") == "success"


def sleep_until(target_time):
    while not _stop_requested:
        current = now_ist()
        if current.time() >= target_time:
            return True
        time.sleep(
            min(
                30.0,
                max(
                    1.0,
                    (datetime.combine(current.date(), target_time, IST) - current).total_seconds(),
                ),
            )
        )
    return False


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as fh:
            state = json.load(fh)
        log("STATE", f"Resumed state from {os.path.basename(STATE_FILE)}")
        return state
    return {"candidates": {}, "trades": {}, "rejected": {}, "trades_taken": 0, "realized_pnl": 0.0}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


def record_trade(trade):
    new_file = not os.path.exists(TRADES_CSV)
    fields = [
        "date",
        "symbol",
        "mode",
        "qty",
        "entry",
        "initial_stop",
        "tp1_qty",
        "tp1_exit",
        "stop",
        "target",
        "exit",
        "exit_reason",
        "pnl",
        "entry_order",
        "exit_order",
    ]
    with open(TRADES_CSV, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {k: trade.get(k, "") for k in fields}
            | {"date": f"{date.today()}", "qty": trade.get("initial_qty", trade.get("qty"))}
        )


def reject(state, symbol, reason):
    state["rejected"][symbol] = reason
    log("REJECT", f"{symbol}: {reason}")


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


def get_quotes(client, symbols):
    """Return {symbol: data} for the given symbols using batched multiquotes."""
    out = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        batch = [{"symbol": s, "exchange": EXCHANGE} for s in symbols[i : i + QUOTE_BATCH]]
        resp = client.multiquotes(symbols=batch)
        if not ok(resp):
            log("DATA", f"multiquotes failed: {resp}")
            continue
        for row in resp.get("results", []):
            if isinstance(row.get("data"), dict):
                out[row.get("symbol")] = row["data"]
    return out


def first_candle_from_history(client, symbol, day):
    """Return the 09:15 5-minute candle for `day` from broker history, or None."""
    df = client.history(
        symbol=symbol, exchange=EXCHANGE, interval="5m", start_date=f"{day}", end_date=f"{day}"
    )
    if not hasattr(df, "empty") or df.empty:
        return None
    df = df[df.index.time == dtime(9, 15)]
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


def build_volume_baseline(client, symbols):
    """Average 09:15 5-minute candle volume and average daily range (high-low %)
    over the last BASELINE_DAYS sessions. Returns ({symbol: volume}, {symbol: range %})."""
    baseline = {}
    adr = {}
    today = now_ist().date()
    start = today - timedelta(days=BASELINE_DAYS * 2 + 5)
    end = today - timedelta(days=1)
    for symbol in symbols:
        if _stop_requested:
            break
        # Broker history calls occasionally time out; retry before dropping the
        # symbol, otherwise it is silently left out of the day's selection.
        for attempt in range(1, HISTORY_RETRIES + 1):
            df = client.history(
                symbol=symbol,
                exchange=EXCHANGE,
                interval="5m",
                start_date=f"{start}",
                end_date=f"{end}",
            )
            if hasattr(df, "empty") or attempt == HISTORY_RETRIES or _stop_requested:
                break
            log("BASELINE", f"{symbol}: history attempt {attempt} failed, retrying")
            time.sleep(2)
        if not hasattr(df, "empty") or df.empty:
            log("BASELINE", f"{symbol}: no history ({df if isinstance(df, dict) else 'empty'})")
            continue
        firsts = df[df.index.time == dtime(9, 15)]["volume"].tail(BASELINE_DAYS)
        if len(firsts) >= max(3, BASELINE_DAYS // 2) and firsts.mean() > 0:
            baseline[symbol] = float(firsts.mean())
            days = df.groupby(df.index.date).agg({"high": "max", "low": "min"}).tail(BASELINE_DAYS)
            days = days[days["low"] > 0]
            if not days.empty:
                adr[symbol] = float(((days["high"] - days["low"]) / days["low"] * 100).mean())
        else:
            log("BASELINE", f"{symbol}: only {len(firsts)} opening candles, skipped")
    log("BASELINE", f"Volume baseline ready for {len(baseline)}/{len(symbols)} symbols")
    return baseline, adr


def load_shared_baseline():
    """Wait for marubozu_breakout's baseline file until BASELINE_WAIT. None if absent.

    A file that is already there is used even after BASELINE_WAIT (a late start).
    """
    while not _stop_requested:
        if os.path.exists(BASELINE_FILE):
            try:
                with open(BASELINE_FILE) as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = None
            if data is not None:
                wanted = set(SYMBOLS)
                baseline = {s: v for s, v in data.get("volume", {}).items() if s in wanted}
                adr = {s: v for s, v in data.get("adr", {}).items() if s in wanted}
                log("BASELINE", f"Using marubozu_breakout's baseline for {len(baseline)} symbols")
                return baseline, adr
        if now_ist().time() >= BASELINE_WAIT:
            return None
        time.sleep(5)
    return None


# ---------------------------------------------------------------------------
# Selection: data valid -> Marubozu + volume -> rank
# ---------------------------------------------------------------------------


def is_bullish_marubozu(c):
    rng = c["high"] - c["low"]
    if rng <= 0 or c["close"] <= c["open"]:
        return False, "not a bullish candle"
    body_pct = (c["close"] - c["open"]) / rng * 100
    upper_pct = (c["high"] - c["close"]) / rng * 100
    lower_pct = (c["open"] - c["low"]) / rng * 100
    if body_pct < MIN_BODY_PCT:
        return False, f"body {body_pct:.0f}% < {MIN_BODY_PCT:.0f}%"
    if upper_pct > MAX_WICK_PCT or lower_pct > MAX_WICK_PCT:
        return False, f"wicks {upper_pct:.0f}%/{lower_pct:.0f}% > {MAX_WICK_PCT:.0f}%"
    return True, f"body {body_pct:.0f}%"


def select_candidates(client, state, baseline, adr):
    today = now_ist().date()
    quotes = get_quotes(client, list(baseline))
    scored = []
    for symbol, avg_vol in baseline.items():
        q = quotes.get(symbol)
        if not q:
            reject(state, symbol, "no opening quote")
            continue
        # Pre-filter on the quote, then confirm with the exact 09:15 candle from
        # history. The quote arrives after 09:20, so LTP is not the candle close
        # and the day low may already be below the candle low. Only use values
        # that can only move one way: open is fixed, day high and day volume only
        # grow. A true candidate can therefore never fail these checks.
        day_open = to_float(q.get("open"))
        day_high = to_float(q.get("high"))
        day_volume = to_float(q.get("volume"))
        if day_open <= 0 or day_high <= 0 or day_volume <= 0:
            reject(state, symbol, "incomplete opening data")
            continue
        min_move_pct = MIN_RANGE_PCT * MIN_BODY_PCT / 100
        if (day_high - day_open) / day_open * 100 < min_move_pct:
            reject(state, symbol, f"no {min_move_pct:.2f}% move above open (quote pre-filter)")
            continue
        if day_volume < MIN_REL_VOLUME * avg_vol:
            reject(state, symbol, "day volume below relative-volume threshold (quote pre-filter)")
            continue
        if day_volume * day_high < MIN_CANDLE_VALUE:
            reject(state, symbol, "day traded value below Rs 1 crore (quote pre-filter)")
            continue
        candle = first_candle_from_history(client, symbol, today)
        if not candle or min(candle.values()) <= 0:
            reject(state, symbol, "opening candle unavailable or invalid")
            continue
        passed, why = is_bullish_marubozu(candle)
        if not passed:
            reject(state, symbol, f"not a Marubozu ({why})")
            continue
        value = candle["volume"] * candle["close"]
        if value < MIN_CANDLE_VALUE:
            reject(state, symbol, f"opening value Rs {value / 1e5:.1f} lakh < Rs 1 crore")
            continue
        rel_vol = candle["volume"] / avg_vol
        if rel_vol < MIN_REL_VOLUME:
            reject(state, symbol, f"relative volume {rel_vol:.2f} < {MIN_REL_VOLUME}")
            continue
        range_pct = (candle["high"] - candle["low"]) / candle["low"] * 100
        if range_pct < MIN_RANGE_PCT:
            reject(state, symbol, f"first candle too small ({range_pct:.2f}% < {MIN_RANGE_PCT}%)")
            continue
        daily_range = adr.get(symbol)
        if MAX_ADR_FRACTION > 0 and daily_range and range_pct > MAX_ADR_FRACTION * daily_range:
            reject(
                state,
                symbol,
                f"first candle too big ({range_pct:.2f}% > {MAX_ADR_FRACTION} x "
                f"average daily range {daily_range:.2f}%)",
            )
            continue
        scored.append((rel_vol, range_pct, symbol, candle))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for rel_vol, range_pct, symbol, candle in scored[:TOP_N]:
        mode = "pullback" if range_pct > BIG_CANDLE_PCT else "breakout"
        state["candidates"][symbol] = candle | {
            "rel_vol": round(rel_vol, 2),
            "range_pct": round(range_pct, 2),
            "mode": mode,
        }
        log(
            "CANDIDATE",
            f"{symbol}: high {candle['high']} low {candle['low']} "
            f"relvol {rel_vol:.2f} range {range_pct:.2f}% -> {mode} entry",
        )
    for _, _, symbol, _ in scored[TOP_N:]:
        reject(state, symbol, "ranked below TOP_N")
    if not state["candidates"]:
        log("SELECT", "No candidates today")
    save_state(state)


# ---------------------------------------------------------------------------
# Tracked trades (no orders are sent)
# ---------------------------------------------------------------------------


def initial_stop(candle, price):
    """Breakout: candle low, or MAX_STOP_PCT below `price` if closer. Pullback: candle low."""
    if candle.get("mode") == "pullback":
        return candle["low"]
    return max(candle["low"], price * (1 - MAX_STOP_PCT / 100))


def exit_levels(candle, entry, stop):
    """Return (tp1, runner_stop, runner_target) for a trade filled at `entry`."""
    if candle.get("mode") == "pullback":
        tp1 = candle["high"]
        if tp1 <= entry:  # cannot happen from a midpoint entry; keep TP1 above the fill
            tp1 = entry * (1 + TP1_PCT / 100)
        return tp1, entry, candle["high"] + PULLBACK_TP2_R * (entry - stop)
    return (
        entry * (1 + TP1_PCT / 100),
        entry * (1 + RUNNER_STOP_PCT / 100),
        entry * (1 + RUNNER_TARGET_PCT / 100),
    )


def enter_trade(state, symbol, candle, ltp):
    """Size the trade like marubozu_breakout and record a buy at the LTP."""
    risk_per_share = ltp - initial_stop(candle, ltp)
    if risk_per_share <= 0:
        reject(state, symbol, "price at or below stop")
        return
    qty = int(RISK_PER_TRADE // risk_per_share)
    qty = min(qty, int(MAX_CAPITAL_PER_TRADE // ltp))
    if qty < 1:
        reject(state, symbol, "quantity below 1 after risk/capital sizing")
        return

    stop = round_down_tick(initial_stop(candle, ltp))
    tp1, runner_stop, runner_target = exit_levels(candle, ltp, stop)
    state["trades_taken"] += 1
    state["trades"][symbol] = {
        "symbol": symbol,
        "mode": candle.get("mode", "breakout"),
        "qty": qty,
        "initial_qty": qty,
        "entry": round(ltp, 2),
        "stop": stop,
        "initial_stop": stop,
        "target": round(tp1, 2),
        "runner_stop": round_down_tick(runner_stop),
        "runner_target": round(runner_target, 2),
        "phase": "full",
        "partial_pnl": 0.0,
        "status": "open",
    }
    save_state(state)
    log(
        "ENTRY",
        f"{symbol}: tracked BUY {qty} @ {ltp:.2f} (no order sent), stop {stop}, TP1 {tp1:.2f}",
    )


def take_tp1(state, trade, price):
    """Book TP1_FRACTION of the shares at `price`, then move to the runner levels."""
    if trade["qty"] < 2:
        return close_trade(state, trade, "target", price)
    sold = max(1, min(trade["qty"] - 1, math.ceil(trade["qty"] * TP1_FRACTION)))
    leg_pnl = (price - trade["entry"]) * sold
    state["realized_pnl"] = round(state["realized_pnl"] + leg_pnl, 2)
    trade.update(
        {
            "phase": "runner",
            "qty": trade["qty"] - sold,
            "tp1_qty": sold,
            "tp1_exit": round(price, 2),
            "partial_pnl": round(leg_pnl, 2),
            "stop": trade["runner_stop"],
            "target": trade["runner_target"],
        }
    )
    save_state(state)
    log(
        "TP1",
        f"{trade['symbol']}: sold {sold} @ {price:.2f}, P&L {leg_pnl:.2f}; "
        f"{trade['qty']} left, stop {trade['stop']}, TP2 {trade['target']:.2f}",
    )
    return True


def close_trade(state, trade, reason, price):
    """Book the remaining shares at `price`."""
    leg_pnl = (price - trade["entry"]) * trade["qty"]
    pnl = leg_pnl + trade.get("partial_pnl", 0.0)  # TP1 leg was booked at TP1
    trade.update(
        {"status": "closed", "exit": round(price, 2), "exit_reason": reason, "pnl": round(pnl, 2)}
    )
    state["realized_pnl"] = round(state["realized_pnl"] + leg_pnl, 2)
    save_state(state)
    record_trade(trade)
    log(
        "EXIT",
        f"{trade['symbol']}: {reason} @ {price:.2f}, trade P&L {pnl:.2f}, "
        f"day P&L {state['realized_pnl']:.2f}",
    )
    return True


def pullback_ready(state, symbol, candle, ltp):
    """Big-candle entry: touch the midpoint, then bounce PULLBACK_BOUNCE_PCT off the dip.

    The touch and the lowest price since it are kept on the candidate, so a restart
    resumes the same setup. A fall to the candle low means the setup failed.
    """
    mid = (candle["high"] + candle["low"]) / 2
    if ltp <= candle["low"]:
        reject(state, symbol, f"pullback reached the candle low {candle['low']} before entry")
        save_state(state)
        return False
    if not candle.get("touched_mid"):
        if ltp <= mid:
            candle["touched_mid"] = True
            candle["dip_low"] = ltp
            log("PULLBACK", f"{symbol}: LTP {ltp} touched midpoint {mid:.2f}")
            save_state(state)
        return False
    if ltp < candle["dip_low"]:
        candle["dip_low"] = ltp
        save_state(state)
        return False
    if ltp < candle["dip_low"] * (1 + PULLBACK_BOUNCE_PCT / 100):
        return False
    if ltp > mid * (1 + MAX_EXTENSION_PCT / 100):
        # Bounced too far between polls: wait for another touch of the midpoint.
        log("PULLBACK", f"{symbol}: LTP {ltp} ran too far above midpoint {mid:.2f}; re-waiting")
        candle["touched_mid"] = False
        save_state(state)
        return False
    log("PULLBACK", f"{symbol}: LTP {ltp} bounced off {candle['dip_low']} (midpoint {mid:.2f})")
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def manage(client, state):
    while not _stop_requested:
        now_t = now_ist().time()
        open_trades = [t for t in state["trades"].values() if t["status"] == "open"]

        if now_t >= SQUARE_OFF:
            quotes = get_quotes(client, [t["symbol"] for t in open_trades]) if open_trades else {}
            for trade in open_trades:
                ltp = to_float(quotes.get(trade["symbol"], {}).get("ltp"))
                close_trade(state, trade, "square_off", ltp or trade["entry"])
            log("DONE", f"Square-off complete. Day P&L {state['realized_pnl']:.2f}")
            return

        can_enter = (
            now_t < ENTRY_CUTOFF
            and state["trades_taken"] < MAX_TRADES_PER_DAY
            and state["realized_pnl"] > -MAX_DAILY_LOSS
        )
        waiting = (
            [
                s
                for s in state["candidates"]
                if s not in state["trades"] and s not in state["rejected"]
            ]
            if can_enter
            else []
        )

        watch = waiting + [t["symbol"] for t in open_trades]
        if not watch:
            if not open_trades and not can_enter:
                log("IDLE", "No open trades and no new entries allowed; waiting for square-off")
                sleep_until(SQUARE_OFF)
            else:
                time.sleep(POLL_SECONDS)
            continue

        quotes = get_quotes(client, watch)

        # Manage open trades: stop crossed? target reached?
        for trade in open_trades:
            ltp = to_float(quotes.get(trade["symbol"], {}).get("ltp"))
            if ltp <= 0:
                continue
            if ltp <= trade["stop"]:
                close_trade(state, trade, "stop_loss", ltp)
            elif ltp >= trade["target"]:
                if trade.get("phase", "full") == "full":
                    log("TP1", f"{trade['symbol']}: LTP {ltp} >= TP1 {trade['target']}")
                    take_tp1(state, trade, ltp)
                else:
                    log("TARGET", f"{trade['symbol']}: LTP {ltp} >= TP2 {trade['target']}")
                    close_trade(state, trade, "target", ltp)

        # Look for entries
        for symbol in waiting:
            if state["trades_taken"] >= MAX_TRADES_PER_DAY:
                break
            candle = state["candidates"][symbol]
            ltp = to_float(quotes.get(symbol, {}).get("ltp"))
            if ltp <= 0:
                continue
            if candle.get("mode") == "pullback":
                if pullback_ready(state, symbol, candle, ltp):
                    enter_trade(state, symbol, candle, ltp)
                continue
            if ltp < candle["high"] * (1 + BREAKOUT_BUFFER_PCT / 100):
                continue
            extension = (ltp - candle["high"]) / candle["high"] * 100
            if extension > MAX_EXTENSION_PCT:
                reject(
                    state,
                    symbol,
                    f"breakout too extended ({extension:.2f}% > {MAX_EXTENSION_PCT}%)",
                )
                save_state(state)
                continue
            log(
                "BREAKOUT",
                f"{symbol}: LTP {ltp} >= opening high {candle['high']} + {BREAKOUT_BUFFER_PCT}%",
            )
            enter_trade(state, symbol, candle, ltp)

        time.sleep(POLL_SECONDS)


def _handle_stop(signum, _frame):
    global _stop_requested
    _stop_requested = True
    log(
        "STOP",
        f"Signal {signum} received. Open positions stay protected by their broker SL-M orders.",
    )


def main():
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    if not API_KEY:
        log("CONFIG", "OPENALGO_API_KEY is not set; run this from the /python host")
        sys.exit(1)
    client = api(api_key=API_KEY, host=API_HOST)
    log("START", f"{STRATEGY_NAME}: {len(SYMBOLS)} symbols, host {API_HOST}")

    state = load_state()

    if now_ist().time() >= SQUARE_OFF:
        log("START", "Past square-off time; nothing to do today")
        return

    if not state["candidates"] and now_ist().time() < ENTRY_CUTOFF:
        shared = load_shared_baseline()
        if shared is None:
            log("BASELINE", "marubozu_breakout's baseline not found; building our own")
            shared = build_volume_baseline(client, SYMBOLS)
        baseline, adr = shared
        if not sleep_until(CANDLE_READY):
            return
        time.sleep(5)  # let the 09:15 candle close at the broker
        select_candidates(client, state, baseline, adr)

    manage(client, state)


if __name__ == "__main__":
    main()
