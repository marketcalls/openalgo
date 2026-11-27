"""Opening Marubozu breakout strategy for the OpenAlgo /python strategy host.

Flow (one trading day):
    09:05  start, load universe, build 10-day first-5-minute volume baseline
    09:20  read the 09:15-09:20 opening candle for every symbol
           -> data valid? -> bullish Marubozu + volume? -> rank by relative volume
    until  ENTRY_CUTOFF: wait for price to break above the opening-candle high
           -> breakout valid and not too extended? -> size the trade
           -> risk and capital checks -> MARKET BUY (MIS) through OpenAlgo
           -> confirm fill -> place SL-M SELL at the opening-candle low (at the broker)
    manage: the script watches price; at +TARGET_PCT it cancels the SL-M and sells
            at MARKET. If the SL-M fills first, the trade is closed by the broker.
    15:10  square off anything still open (cancel SL-M, sell at MARKET)

The stop-loss lives at the broker, so a crashed script still leaves every position
protected. State is saved to a JSON file so a restart resumes managing open trades.

Every setting below can be overridden by a parameter of the same name in the
/python upload form (they arrive as environment variables).

Test in Analyzer (sandbox) mode before running live.
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


STRATEGY_NAME = _env("STRATEGY_TAG", "MarubozuBreakout")
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
MIN_REL_VOLUME = _env("MIN_REL_VOLUME", 2.0, float)  # opening vol >= 2x baseline
BASELINE_DAYS = _env("BASELINE_DAYS", 10, int)  # days for the volume baseline
TOP_N = _env("TOP_N", 5, int)  # candidates kept after ranking
MAX_EXTENSION_PCT = _env("MAX_EXTENSION_PCT", 0.5, float)  # skip if > 0.5% above high

# Trade rules
TARGET_PCT = _env("TARGET_PCT", 1.0, float)  # +1% from fill price
RISK_PER_TRADE = _env("RISK_PER_TRADE", 1000.0, float)  # rupees risked per trade
MAX_CAPITAL_PER_TRADE = _env("MAX_CAPITAL_PER_TRADE", 100000.0, float)
MARGIN_FACTOR = _env("MARGIN_FACTOR", 1.0, float)  # cash needed = value * factor
MAX_TRADES_PER_DAY = _env("MAX_TRADES_PER_DAY", 3, int)
MAX_DAILY_LOSS = _env("MAX_DAILY_LOSS", 3000.0, float)

# Times (IST)
CANDLE_READY = _hhmm(_env("CANDLE_READY", "09:20"))
ENTRY_CUTOFF = _hhmm(_env("ENTRY_CUTOFF", "11:00"))
SQUARE_OFF = _hhmm(_env("SQUARE_OFF", "15:10"))

POLL_SECONDS = _env("POLL_SECONDS", 2.0, float)
FILL_TIMEOUT_SECONDS = _env("FILL_TIMEOUT_SECONDS", 30, int)
QUOTE_BATCH = _env("QUOTE_BATCH", 50, int)
TICK = 0.05

API_KEY = os.getenv("OPENALGO_API_KEY") or os.getenv("API_KEY", "")
API_HOST = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, f"marubozu_state_{date.today():%Y%m%d}.json")
TRADES_CSV = os.path.join(HERE, "marubozu_trades.csv")

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
        "qty",
        "entry",
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
        writer.writerow({k: trade.get(k, "") for k in fields} | {"date": f"{date.today()}"})


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
    """Average 09:15 5-minute candle volume over the last BASELINE_DAYS sessions."""
    baseline = {}
    today = now_ist().date()
    start = today - timedelta(days=BASELINE_DAYS * 2 + 5)
    end = today - timedelta(days=1)
    for symbol in symbols:
        if _stop_requested:
            break
        df = client.history(
            symbol=symbol,
            exchange=EXCHANGE,
            interval="5m",
            start_date=f"{start}",
            end_date=f"{end}",
        )
        if not hasattr(df, "empty") or df.empty:
            log("BASELINE", f"{symbol}: no history ({df if isinstance(df, dict) else 'empty'})")
            continue
        firsts = df[df.index.time == dtime(9, 15)]["volume"].tail(BASELINE_DAYS)
        if len(firsts) >= max(3, BASELINE_DAYS // 2) and firsts.mean() > 0:
            baseline[symbol] = float(firsts.mean())
        else:
            log("BASELINE", f"{symbol}: only {len(firsts)} opening candles, skipped")
    log("BASELINE", f"Volume baseline ready for {len(baseline)}/{len(symbols)} symbols")
    return baseline


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


def select_candidates(client, state, baseline):
    today = now_ist().date()
    quotes = get_quotes(client, list(baseline))
    scored = []
    for symbol, avg_vol in baseline.items():
        q = quotes.get(symbol)
        if not q:
            reject(state, symbol, "no opening quote")
            continue
        # Pre-filter on the quote (day OHLC at 09:20 == opening candle), then
        # confirm with the exact 09:15 candle from history.
        pre = {
            "open": to_float(q.get("open")),
            "high": to_float(q.get("high")),
            "low": to_float(q.get("low")),
            "close": to_float(q.get("ltp")),
        }
        if min(pre.values()) <= 0 or to_float(q.get("volume")) <= 0:
            reject(state, symbol, "incomplete opening data")
            continue
        passed, _ = is_bullish_marubozu(pre)
        if not passed:
            reject(state, symbol, "not a Marubozu (quote pre-filter)")
            continue
        candle = first_candle_from_history(client, symbol, today)
        if not candle or min(candle.values()) <= 0:
            reject(state, symbol, "opening candle unavailable or invalid")
            continue
        passed, why = is_bullish_marubozu(candle)
        if not passed:
            reject(state, symbol, f"not a Marubozu ({why})")
            continue
        rel_vol = candle["volume"] / avg_vol
        if rel_vol < MIN_REL_VOLUME:
            reject(state, symbol, f"relative volume {rel_vol:.2f} < {MIN_REL_VOLUME}")
            continue
        range_pct = (candle["high"] - candle["low"]) / candle["low"] * 100
        scored.append((rel_vol, range_pct, symbol, candle))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for rel_vol, range_pct, symbol, candle in scored[:TOP_N]:
        state["candidates"][symbol] = candle | {
            "rel_vol": round(rel_vol, 2),
            "range_pct": round(range_pct, 2),
        }
        log(
            "CANDIDATE",
            f"{symbol}: high {candle['high']} low {candle['low']} "
            f"relvol {rel_vol:.2f} range {range_pct:.2f}%",
        )
    for _, _, symbol, _ in scored[TOP_N:]:
        reject(state, symbol, "ranked below TOP_N")
    if not state["candidates"]:
        log("SELECT", "No candidates today")
    save_state(state)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def order_status(client, order_id):
    resp = client.orderstatus(order_id=order_id, strategy=STRATEGY_NAME)
    if not ok(resp):
        return None, resp
    return resp.get("data", {}), resp


def wait_for_terminal(client, order_id, timeout):
    """Poll an order until complete/rejected/cancelled or timeout. Returns its data."""
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data, _ = order_status(client, order_id)
        status = (data or {}).get("order_status", "").lower()
        if status in ("complete", "rejected", "cancelled"):
            return data
        time.sleep(1)
    return data


def net_position(client, symbol):
    resp = client.openposition(
        strategy=STRATEGY_NAME, symbol=symbol, exchange=EXCHANGE, product=PRODUCT
    )
    if not ok(resp):
        return None
    return int(to_float(resp.get("quantity"), 0))


def place_stop(client, symbol, qty, stop_price):
    resp = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=symbol,
        action="SELL",
        exchange=EXCHANGE,
        price_type="SL-M",
        product=PRODUCT,
        quantity=qty,
        price=0,
        trigger_price=round_down_tick(stop_price),
    )
    return resp.get("orderid") if ok(resp) else None, resp


def market_sell(client, symbol, qty):
    resp = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=symbol,
        action="SELL",
        exchange=EXCHANGE,
        price_type="MARKET",
        product=PRODUCT,
        quantity=qty,
    )
    return resp.get("orderid") if ok(resp) else None, resp


def enter_trade(client, state, symbol, candle, ltp):
    """Risk checks, MARKET BUY, fill reconciliation, then broker-side SL-M."""
    stop = candle["low"]
    risk_per_share = ltp - stop
    if risk_per_share <= 0:
        reject(state, symbol, "price at or below stop")
        return
    qty = int(RISK_PER_TRADE // risk_per_share)
    qty = min(qty, int(MAX_CAPITAL_PER_TRADE // ltp))
    if qty < 1:
        reject(state, symbol, "quantity below 1 after risk/capital sizing")
        return

    funds = client.funds()
    cash = to_float(funds.get("data", {}).get("availablecash")) if ok(funds) else 0.0
    needed = qty * ltp * MARGIN_FACTOR
    if cash < needed:
        reject(state, symbol, f"insufficient funds ({cash:.0f} < {needed:.0f})")
        return
    existing = net_position(client, symbol)
    if existing is None:
        reject(state, symbol, "could not read existing position")
        return
    if existing != 0:
        reject(state, symbol, f"already holding {existing}")
        return

    resp = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=symbol,
        action="BUY",
        exchange=EXCHANGE,
        price_type="MARKET",
        product=PRODUCT,
        quantity=qty,
    )
    if not ok(resp):
        reject(state, symbol, f"entry refused: {resp.get('message', resp)}")
        return
    entry_id = resp.get("orderid")
    state["trades_taken"] += 1
    log("ENTRY", f"{symbol}: BUY {qty} MARKET sent, order {entry_id}")

    data = wait_for_terminal(client, entry_id, FILL_TIMEOUT_SECONDS) or {}
    status = data.get("order_status", "").lower()
    if status != "complete":
        if status not in ("rejected", "cancelled"):
            client.cancelorder(order_id=entry_id, strategy=STRATEGY_NAME)
        filled = net_position(client, symbol) or 0
        if filled <= 0:
            reject(
                state,
                symbol,
                f"entry {status or 'unknown'}: "
                f"{data.get('rejection_reason', data.get('message', ''))}",
            )
            save_state(state)
            return
        log("ENTRY", f"{symbol}: partial fill {filled}, protecting what was filled")
        qty = filled

    fill_price = to_float(data.get("average_price")) or ltp
    held = net_position(client, symbol)
    if held is not None and held > 0:
        qty = held  # reconcile against the broker's position
    target = fill_price * (1 + TARGET_PCT / 100)

    sl_id, sl_resp = place_stop(client, symbol, qty, stop)
    trade = {
        "symbol": symbol,
        "qty": qty,
        "entry": round(fill_price, 2),
        "stop": stop,
        "target": round(target, 2),
        "entry_order": entry_id,
        "sl_order": sl_id,
        "status": "open",
    }
    state["trades"][symbol] = trade
    save_state(state)
    if not sl_id:
        log("RISK", f"{symbol}: SL-M refused ({sl_resp}); exiting immediately")
        close_trade(client, state, trade, "sl_order_failed")
        return
    log(
        "PROTECT",
        f"{symbol}: filled {qty} @ {fill_price:.2f}, SL-M {stop} (order {sl_id}), "
        f"target {target:.2f}",
    )


def close_trade(client, state, trade, reason, exit_price=None, exit_order=None):
    """Cancel the SL-M (if any) and sell whatever is still held at MARKET."""
    symbol = trade["symbol"]
    if trade.get("sl_order") and exit_order is None:
        sl_data, _ = order_status(client, trade["sl_order"])
        if (sl_data or {}).get("order_status", "").lower() == "complete":
            # The stop already filled at the broker: nothing left to sell.
            exit_price = to_float(sl_data.get("average_price")) or trade["stop"]
            exit_order = trade["sl_order"]
            reason = "stop_loss"
        else:
            client.cancelorder(order_id=trade["sl_order"], strategy=STRATEGY_NAME)
            after = wait_for_terminal(client, trade["sl_order"], 10) or {}
            if after.get("order_status", "").lower() == "complete":
                # The stop filled before the cancel landed: record it as the exit.
                exit_price = to_float(after.get("average_price")) or trade["stop"]
                exit_order = trade["sl_order"]
                reason = "stop_loss"

    if exit_order is None:
        held = net_position(client, symbol)
        if held is None:
            log("EXIT", f"{symbol}: cannot read position; will retry")
            return False
        if held > 0:
            exit_order, resp = market_sell(client, symbol, held)
            if not exit_order:
                log("EXIT", f"{symbol}: exit refused ({resp}); will retry")
                return False
            data = wait_for_terminal(client, exit_order, FILL_TIMEOUT_SECONDS) or {}
            exit_price = to_float(data.get("average_price")) or exit_price

    exit_price = exit_price or trade["entry"]
    pnl = (exit_price - trade["entry"]) * trade["qty"]
    trade.update(
        {
            "status": "closed",
            "exit": round(exit_price, 2),
            "exit_reason": reason,
            "exit_order": exit_order,
            "pnl": round(pnl, 2),
        }
    )
    state["realized_pnl"] = round(state["realized_pnl"] + pnl, 2)
    save_state(state)
    record_trade(trade)
    log(
        "EXIT",
        f"{symbol}: {reason} @ {exit_price:.2f}, P&L {pnl:.2f}, "
        f"day P&L {state['realized_pnl']:.2f}",
    )
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def manage(client, state):
    while not _stop_requested:
        now_t = now_ist().time()
        open_trades = [t for t in state["trades"].values() if t["status"] == "open"]

        if now_t >= SQUARE_OFF:
            for trade in open_trades:
                close_trade(client, state, trade, "square_off")
            if all(t["status"] == "closed" for t in state["trades"].values()):
                log("DONE", f"Square-off complete. Day P&L {state['realized_pnl']:.2f}")
                return
            time.sleep(5)
            continue

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

        # Manage open trades: stop filled at broker? target reached?
        for trade in open_trades:
            sl_data, _ = order_status(client, trade["sl_order"])
            sl_status = (sl_data or {}).get("order_status", "").lower()
            if sl_status == "complete":
                close_trade(
                    client,
                    state,
                    trade,
                    "stop_loss",
                    exit_price=to_float(sl_data.get("average_price")) or trade["stop"],
                    exit_order=trade["sl_order"],
                )
                continue
            if sl_status in ("rejected", "cancelled"):
                log("RISK", f"{trade['symbol']}: SL-M is {sl_status}; exiting at market")
                close_trade(client, state, trade, f"sl_{sl_status}")
                continue
            ltp = to_float(quotes.get(trade["symbol"], {}).get("ltp"))
            if ltp >= trade["target"]:
                log("TARGET", f"{trade['symbol']}: LTP {ltp} >= target {trade['target']}")
                close_trade(client, state, trade, "target")

        # Look for breakouts
        for symbol in waiting:
            if state["trades_taken"] >= MAX_TRADES_PER_DAY:
                break
            candle = state["candidates"][symbol]
            ltp = to_float(quotes.get(symbol, {}).get("ltp"))
            if ltp <= candle["high"]:
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
            log("BREAKOUT", f"{symbol}: LTP {ltp} > opening high {candle['high']}")
            enter_trade(client, state, symbol, candle, ltp)

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
        baseline = build_volume_baseline(client, SYMBOLS)
        if not sleep_until(CANDLE_READY):
            return
        time.sleep(5)  # let the 09:15 candle close at the broker
        select_candidates(client, state, baseline)

    manage(client, state)


if __name__ == "__main__":
    main()
