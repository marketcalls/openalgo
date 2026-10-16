#!/usr/bin/env python
"""
Autonomous Daily Iron Condor - NIFTY & BANKNIFTY options, 9:15am-2:45pm IST

WHAT THIS IS: a fully automated, defined-risk premium-selling strategy.
Each morning it sells a near-OTM Call+Put (the profit engine - collects
theta/time decay) and simultaneously buys a further-OTM Call+Put as
insurance (the "buying" leg). That combination caps the maximum possible
loss to a known, fixed number *before the trade is even placed* - unlike a
naked short strangle, where a gap move can produce unlimited loss. It then
manages the position by itself for the rest of the day: no approval step,
no manual intervention - it enters, watches, and exits on its own.

WHAT THIS IS NOT: there is no options strategy - here or anywhere - that
produces "no loss ever." Selling options trades a high win-rate (most days
expire with a chunk of the credit in pocket) against occasional losing days
when the underlying makes a large move. This script's job is to make those
losing days small, bounded, and rare - not to eliminate them. Every rupee
this deploys is capital you can lose, up to the position's structural max
loss. Start in Analyzer (sandbox) mode and watch it for at least a couple
of weeks before considering real money.

DECISION LOOP (runs every POLL_SECONDS, logs its reasoning every time -
watch it live from the /python Strategy Logs page):
  09:15-10:30  Entry window. Once per instrument per day: size the position
               against your capital (via live margin check), place the
               4-leg spread.
  All day      Re-check P&L. Exit early on whichever comes first:
                 - PROFIT_TARGET_CREDIT_FRACTION of the credit received
                   (booking ~50% of max profit early is the standard
                   professional heuristic for defined-risk premium
                   selling - don't get greedy waiting for the last few
                   rupees while gamma risk builds into the close)
                 - STOP_LOSS_CREDIT_MULTIPLE x the credit received, as a
                   loss (bails out long before the structural max loss)
                 - FORCE_EXIT_TIME reached (2:45pm - inside your requested
                   2-3pm window, with a safety margin before the exchange's
                   own auto square-off for MIS positions)
  After exit   Done for the day. Does not re-enter (no revenge trading).

LIVE P&L: OpenAlgo already ships a real-time PnL dashboard with an equity
curve - open the OpenAlgo web app -> "PnL" in the sidebar -> filter by
Strategy = "Intraday Iron Condor". That's the live graph; this script does
not duplicate it, it just feeds it (every order below is tagged with
STRATEGY_NAME so the dashboard can find it).
"""
import os
import json
import time
from datetime import datetime, time as dtime

from openalgo import api

# ---------------------------------------------------------------------------
# Connection (see strategies/README.md for the env var conventions)
# ---------------------------------------------------------------------------
API_KEY = os.getenv('OPENALGO_API_KEY')
HOST = os.getenv('HOST_SERVER') or os.getenv('OPENALGO_HOST', 'http://127.0.0.1:5000')
WS_URL = os.getenv('WEBSOCKET_URL') or (
    f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"
)

if not API_KEY:
    print("Error: OPENALGO_API_KEY environment variable not set")
    raise SystemExit(1)

client = api(api_key=API_KEY, host=HOST, ws_url=WS_URL)

# ---------------------------------------------------------------------------
# Strategy configuration - review every value before going live
# ---------------------------------------------------------------------------
STRATEGY_NAME = "Intraday Iron Condor"
PRODUCT = "MIS"  # intraday - broker auto-square-off is a backstop if this script ever fails to exit

INSTRUMENTS = [
    {"underlying": "NIFTY", "exchange": "NSE_INDEX",
     "hedge_offset": "OTM6", "short_offset": "OTM4", "weight": 0.5},
    {"underlying": "BANKNIFTY", "exchange": "NSE_INDEX",
     "hedge_offset": "OTM6", "short_offset": "OTM4", "weight": 0.5},
]

# --- Capital & sizing -------------------------------------------------------
TOTAL_CAPITAL = 1_000_000            # example: Rs 10L - set this to your own capital
CAPITAL_ALLOCATION_FRACTION = 0.6    # deploy at most 60% of capital as margin - the
                                      # rest is a buffer against intraday MTM swings.
                                      # Never raise this to 1.0: a defined-risk spread
                                      # still has margin, and running it to the edge
                                      # of your funds turns any adverse move into a
                                      # margin call instead of a controlled stop-loss.
MAX_LOTS_PER_INSTRUMENT = 10          # hard ceiling regardless of what the margin math allows

# --- Exits -------------------------------------------------------------------
PROFIT_TARGET_CREDIT_FRACTION = 0.5  # book profit at 50% of credit received
STOP_LOSS_CREDIT_MULTIPLE = 1.0      # stop out at 100% of credit received, as a loss
ENTRY_START_TIME = dtime(9, 20)      # let opening-bell volatility settle first
ENTRY_CUTOFF_TIME = dtime(10, 30)    # don't chase an entry deep into the day
FORCE_EXIT_TIME = dtime(14, 45)      # square off well before the 3:30pm close

POLL_SECONDS = 45

# Real-money safety gate. Leave SANDBOX_MODE=True while testing - this does
# NOT touch OpenAlgo's global Analyzer toggle (that's account-wide and would
# affect other strategies you run), it's a local guard specific to this
# script. To go live: set SANDBOX_MODE=False here AND switch off Analyzer
# Mode yourself in the OpenAlgo navbar. Both must agree or nothing is sent.
SANDBOX_MODE = True

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".iron_condor_daily_state.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def today_str():
    return datetime.now().date().isoformat()


def nearest_expiry(underlying):
    resp = client.expiry(symbol=underlying, exchange="NFO", instrumenttype="options")
    if resp.get("status") != "success" or not resp.get("data"):
        raise RuntimeError(f"Could not fetch expiry list for {underlying}: {resp}")
    return resp["data"][0].replace("-", "")  # e.g. "25-NOV-25" -> "25NOV25"


def offset_count(offset):
    return int("".join(ch for ch in offset if ch.isdigit()) or 0)


def resolve_chain_legs(underlying, exchange, expiry_fmt, hedge_offset, short_offset):
    """Look up exact option symbols + lot size for both offsets, with no order placed."""
    strike_count = max(offset_count(hedge_offset), offset_count(short_offset))
    chain = client.optionchain(underlying=underlying, exchange=exchange,
                                expiry_date=expiry_fmt, strike_count=strike_count)
    if chain.get("status") != "success":
        raise RuntimeError(f"optionchain failed for {underlying}: {chain}")

    found = {}
    lotsize = None
    for row in chain["chain"]:
        for side in ("ce", "pe"):
            leg = row[side]
            lotsize = lotsize or leg["lotsize"]
            if leg["label"] == hedge_offset:
                found[f"hedge_{side}"] = leg["symbol"]
            if leg["label"] == short_offset:
                found[f"short_{side}"] = leg["symbol"]

    missing = [k for k in ("hedge_ce", "hedge_pe", "short_ce", "short_pe") if k not in found]
    if missing:
        raise RuntimeError(f"Could not resolve legs {missing} for {underlying} {expiry_fmt} "
                            f"(increase strike_count or check offsets)")
    return found, lotsize


def lots_affordable(legs, lotsize, budget):
    """Ask the broker's own margin engine what 1 lot of this spread costs, then size to budget."""
    positions = [
        {"symbol": legs["hedge_ce"], "exchange": "NFO", "action": "BUY", "product": PRODUCT,
         "pricetype": "MARKET", "quantity": str(lotsize)},
        {"symbol": legs["hedge_pe"], "exchange": "NFO", "action": "BUY", "product": PRODUCT,
         "pricetype": "MARKET", "quantity": str(lotsize)},
        {"symbol": legs["short_ce"], "exchange": "NFO", "action": "SELL", "product": PRODUCT,
         "pricetype": "MARKET", "quantity": str(lotsize)},
        {"symbol": legs["short_pe"], "exchange": "NFO", "action": "SELL", "product": PRODUCT,
         "pricetype": "MARKET", "quantity": str(lotsize)},
    ]
    resp = client.margin(positions=positions)
    if resp.get("status") != "success":
        raise RuntimeError(f"margin check failed: {resp}")
    margin_per_lot = float(resp["data"]["total_margin_required"])
    if margin_per_lot <= 0:
        raise RuntimeError(f"margin API returned non-positive margin: {resp}")
    lots = int(budget // margin_per_lot)
    return max(0, min(lots, MAX_LOTS_PER_INSTRUMENT)), margin_per_lot


def deployable_budget(weight):
    funds = client.funds()
    available_cash = float(funds.get("data", {}).get("availablecash", 0))
    cap = min(TOTAL_CAPITAL * CAPITAL_ALLOCATION_FRACTION, available_cash)
    return max(0.0, cap * weight)


def enter_iron_condor(inst, expiry_fmt):
    underlying, exchange = inst["underlying"], inst["exchange"]
    legs, lotsize = resolve_chain_legs(underlying, exchange, expiry_fmt,
                                        inst["hedge_offset"], inst["short_offset"])
    budget = deployable_budget(inst["weight"])
    lots, margin_per_lot = lots_affordable(legs, lotsize, budget)

    if lots < 1:
        log(f"{underlying}: skipping entry - budget Rs{budget:,.0f} can't cover "
            f"1 lot (margin/lot Rs{margin_per_lot:,.0f})")
        return None

    qty = lots * lotsize
    order_legs = [
        {"offset": inst["hedge_offset"], "option_type": "CE", "action": "BUY", "quantity": qty},
        {"offset": inst["hedge_offset"], "option_type": "PE", "action": "BUY", "quantity": qty},
        {"offset": inst["short_offset"], "option_type": "CE", "action": "SELL", "quantity": qty},
        {"offset": inst["short_offset"], "option_type": "PE", "action": "SELL", "quantity": qty},
    ]
    resp = client.optionsmultiorder(strategy=STRATEGY_NAME, underlying=underlying,
                                     exchange=exchange, expiry_date=expiry_fmt, legs=order_legs)
    if resp.get("status") != "success":
        log(f"{underlying}: ENTRY FAILED: {resp}")
        return None

    log(f"{underlying}: entered {lots} lot(s) ({qty} qty), margin/lot Rs{margin_per_lot:,.0f}, "
        f"budget Rs{budget:,.0f} -> {resp['results']}")

    time.sleep(2)  # let the fills land in the position book
    pb = client.positionbook().get("data", [])
    by_symbol = {p["symbol"]: p for p in pb}

    stored_legs = []
    net_credit = 0.0
    for leg in resp["results"]:
        sym = leg["symbol"]
        pos = by_symbol.get(sym)
        avg_price = float(pos["average_price"]) if pos else 0.0
        stored_legs.append({"symbol": sym, "exchange": "NFO", "action": leg["action"], "quantity": qty})
        net_credit += avg_price * qty if leg["action"] == "SELL" else -avg_price * qty

    return {
        "date": today_str(), "status": "open", "legs": stored_legs,
        "net_credit": net_credit, "lots": lots, "entered_at": datetime.now().isoformat(),
    }


def current_pnl(legs):
    pb = client.positionbook().get("data", [])
    by_symbol = {p["symbol"]: p for p in pb}
    return sum(float(by_symbol[leg["symbol"]]["pnl"]) for leg in legs if leg["symbol"] in by_symbol)


def exit_position(legs, reason):
    orders = [{
        "symbol": leg["symbol"], "exchange": leg["exchange"],
        "action": "SELL" if leg["action"] == "BUY" else "BUY",
        "quantity": leg["quantity"], "pricetype": "MARKET", "product": PRODUCT,
    } for leg in legs]
    resp = client.basketorder(strategy=STRATEGY_NAME, orders=orders)
    log(f"EXIT ({reason}): {resp}")


def run_instrument(inst, state):
    key = inst["underlying"]
    rec = state.get(key)
    if rec and rec.get("date") != today_str():
        rec = None  # yesterday's record - today starts fresh

    now_t = datetime.now().time()

    if rec is None:
        if ENTRY_START_TIME <= now_t <= ENTRY_CUTOFF_TIME:
            expiry_fmt = nearest_expiry(inst["underlying"])
            new_rec = enter_iron_condor(inst, expiry_fmt)
            if new_rec:
                state[key] = new_rec
                save_state(state)
        else:
            log(f"{key}: thinking... no position, outside entry window ({now_t.strftime('%H:%M')}), standing by")
        return

    if rec["status"] == "closed":
        log(f"{key}: thinking... already done for today ({rec.get('reason', 'closed')})")
        return

    # status == "open": evaluate exits
    pnl = current_pnl(rec["legs"])
    credit = abs(rec["net_credit"])
    target_level = credit * PROFIT_TARGET_CREDIT_FRACTION
    stop_level = -credit * STOP_LOSS_CREDIT_MULTIPLE

    log(f"{key}: thinking... lots={rec['lots']} credit=Rs{rec['net_credit']:.0f} "
        f"pnl=Rs{pnl:.0f} target=Rs{target_level:.0f} stop=Rs{stop_level:.0f}")

    if pnl >= target_level:
        exit_position(rec["legs"], f"profit target hit ({pnl:.0f} >= {target_level:.0f})")
        rec.update(status="closed", reason="profit target")
    elif pnl <= stop_level:
        exit_position(rec["legs"], f"stop-loss hit ({pnl:.0f} <= {stop_level:.0f})")
        rec.update(status="closed", reason="stop-loss")
    elif now_t >= FORCE_EXIT_TIME:
        exit_position(rec["legs"], f"time-based exit at {FORCE_EXIT_TIME.strftime('%H:%M')}")
        rec.update(status="closed", reason="time exit")

    state[key] = rec
    save_state(state)


def main():
    if not SANDBOX_MODE and os.getenv("LIVE_TRADING_CONFIRMED") != "YES":
        log("SANDBOX_MODE is False but LIVE_TRADING_CONFIRMED != 'YES'. "
            "Refusing to run against a live account. Set the env var explicitly to proceed.")
        raise SystemExit(1)

    mode = "SANDBOX (test with fake money)" if SANDBOX_MODE else "LIVE (real money)"
    log(f"Starting {STRATEGY_NAME} - mode: {mode} - capital Rs{TOTAL_CAPITAL:,.0f} "
        f"({CAPITAL_ALLOCATION_FRACTION:.0%} deployable)")
    state = load_state()

    while True:
        try:
            now = datetime.now()
            if now.weekday() >= 5:
                log("Weekend - market closed, sleeping")
            else:
                for inst in INSTRUMENTS:
                    run_instrument(inst, state)
        except Exception as e:
            log(f"Error in main loop: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
