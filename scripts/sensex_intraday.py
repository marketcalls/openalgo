import os
from datetime import datetime
import pytz
import pandas as pd

from openalgo import api, ta
from fyers_apiv3 import fyersModel

# =========================
# CONFIG
# =========================

LOTS = 5
SENSEX_LOT_SIZE = 20
QTY = LOTS * SENSEX_LOT_SIZE

MAX_TRADES_PER_DAY = 3

TARGET_MTM = 1500
STOPLOSS_MTM = 2000

ENTRY_START = "09:30"
ENTRY_END = "11:30"
SQUAREOFF_TIME = "15:15"

IST = pytz.timezone("Asia/Kolkata")

# =========================
# GLOBALS
# =========================

trades_today = 0
active_position = False
last_trade_time = None

# =========================
# OPENALGO CLIENT
# =========================

def get_openalgo_client():

    api_key = 'cf0715cb983ddec8529e08ed813c27a091d8284be258769105a7341494cf0409'#os.getenv("OPENALGO_API_KEY")

    host = (
        os.getenv("HOST_SERVER")
        or os.getenv("OPENALGO_HOST")
        or "http://127.0.0.1:5000"
    )

    return api(
        api_key=api_key,
        host=host
    )

# =========================
# FYERS CLIENT
# =========================

def get_fyers_client():

    client_id = os.getenv("FYERS_CLIENT_ID")
    access_token = os.getenv("FYERS_ACCESS_TOKEN")

    return fyersModel.FyersModel(
        client_id=client_id,
        token=access_token,
        is_async=False
    )

# =========================
# VALIDATE DATA
# =========================

def validate_ohlcv_dataframe(df):

    if df is None:
        return False

    if df.empty:
        return False

    required_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    for col in required_cols:
        if col not in df.columns:
            return False

    return True

# =========================
# ADX FILTER
# =========================

def get_adx(client):

    end_date = datetime.now().strftime("%Y-%m-%d")

    df = client.history(
        symbol="SENSEX",
        exchange="BSE_INDEX",
        interval="5m",
        start_date=end_date,
        end_date=end_date
    )

    if not validate_ohlcv_dataframe(df):
        return None

    df = df.sort_index()

    di_plus, di_minus, adx = ta.adx(
        df["high"],
        df["low"],
        df["close"],
        period=14
    )

    df["ADX"] = adx
    df.dropna(inplace=True)

    if len(df) == 0:
        return None

    return float(df["ADX"].iloc[-1])

# =========================
# FYERS OPTION CHAIN
# =========================

def get_option_chain(fyers):
    """
    Replace this with your FYERS v3
    option chain endpoint call.

    Must return dataframe containing:

    symbol
    strike
    option_type
    delta
    ltp
    iv
    """

    raise NotImplementedError

# =========================
# STRIKE SELECTION
# =========================

def select_short_strikes(option_chain):

    calls = option_chain[
        option_chain["option_type"] == "CE"
    ].copy()

    puts = option_chain[
        option_chain["option_type"] == "PE"
    ].copy()

    calls["distance"] = abs(
        calls["delta"] - 0.20
    )

    puts["distance"] = abs(
        puts["delta"] + 0.20
    )

    ce = calls.sort_values(
        "distance"
    ).iloc[0]

    pe = puts.sort_values(
        "distance"
    ).iloc[0]

    return ce, pe

# =========================
# PAPER ORDERS
# =========================

paper_positions = []

def place_paper_order(symbol,
                      action,
                      qty,
                      price):

    paper_positions.append(
        {
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "entry_price": price,
            "entry_time": datetime.now(IST)
        }
    )

    print(
        f"{action} {symbol} "
        f"QTY={qty} "
        f"PRICE={price}"
    )

# =========================
# ENTRY LOGIC
# =========================

def entry_conditions_met(adx_value):

    if adx_value is None:
        return False

    if adx_value >= 20:
        return False

    return True

# =========================
# RUN STRATEGY
# =========================

def run_strategy():

    global trades_today
    global active_position
    global last_trade_time

    client = get_openalgo_client()
    fyers = get_fyers_client()

    adx_value = get_adx(client)

    print(f"ADX = {adx_value}")

    if not entry_conditions_met(adx_value):
        return

    if active_position:
        return

    if trades_today >= MAX_TRADES_PER_DAY:
        return

    option_chain = get_option_chain(fyers)

    ce, pe = select_short_strikes(
        option_chain
    )

    place_paper_order(
        ce["symbol"],
        "SELL",
        QTY,
        ce["ltp"]
    )

    place_paper_order(
        pe["symbol"],
        "SELL",
        QTY,
        pe["ltp"]
    )

    active_position = True
    trades_today += 1
    last_trade_time = datetime.now(IST)

    print(
        f"Trade #{trades_today} entered."
    )

# =========================
# MAIN
# =========================

def main():

    print("🔁 OpenAlgo Python Bot is running.")

    run_strategy()

if __name__ == "__main__":
    main()