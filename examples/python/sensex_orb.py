import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from openalgo import api, ta

print("🔁 OpenAlgo Python Bot is running.")

# ==========================================================
# CONFIGURATION
# ==========================================================

START_DATE = "2025-06-01"
END_DATE = "2026-06-01"

SPOT_SYMBOL = "SENSEX"
SPOT_EXCHANGE = "BSE_INDEX"

OPTION_EXCHANGE = "BFO"

INTERVAL = "5m"

ORB_START = "09:15"
ORB_END = "09:30"

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0

LOT_SIZE = 20

# ==========================================================
# OPENALGO CLIENT
# ==========================================================

def get_client():
    api_key = os.getenv("OPENALGO_API_KEY")
    host = (
        os.getenv("HOST_SERVER")
        or os.getenv("OPENALGO_HOST")
        or "http://127.0.0.1:5000"
    )
    return api(api_key=api_key, host=host)


# ==========================================================
# OPTION HELPERS
# ==========================================================

def get_atm_strike(spot):
    return int(round(spot / 100) * 100)


def get_monthly_expiry(trade_date):
    trade_date = pd.Timestamp(trade_date)
    month_dates = pd.date_range(
        start=trade_date.replace(day=1),
        end=trade_date + pd.offsets.MonthEnd(1),
        freq="D"
    )
    thursdays = [
        d for d in month_dates
        if d.weekday() == 3 and d.month == trade_date.month
    ]
    expiry = max(thursdays)
    return expiry.strftime("%d%b%y").upper()


def build_option_symbol(strike, expiry, option_type):
    return f"SENSEX{expiry}{strike}{option_type}"


# ==========================================================
# DATA HELPERS
# ==========================================================

def _to_df(result, label=""):
    """
    Validate that client.history() returned a usable DataFrame.
    The SDK returns a DataFrame on success and an error dict on failure.
    """
    if not isinstance(result, pd.DataFrame):
        msg = result.get("message", "unknown error") if isinstance(result, dict) else "no data"
        print(f"[WARNING] {label}: {msg}")
        return None
    if result.empty:
        print(f"[WARNING] {label}: empty DataFrame returned")
        return None
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(result.columns)
    if missing:
        print(f"[WARNING] {label}: missing columns {missing}")
        return None
    return result


# ==========================================================
# FETCH SENSEX DATA
# ==========================================================

def fetch_spot_history(client):
    result = client.history(
        symbol= os.getenv("SPOT_SYMBOL"),
        exchange= os.getenv("SPOT_EXCHANGE"),
        interval= os.getenv("INTERVAL"),
        start_date= os.getenv("START_DATE"),
        end_date= os.getenv("END_DATE"),
    )
    df = _to_df(result, f"{os.getenv('SPOT_SYMBOL')} spot history")
    if df is None:
        raise ValueError(f"Failed to fetch {os.getenv('SPOT_SYMBOL')} history")
    return df.sort_index()


# ==========================================================
# FETCH OPTION DATA
# ==========================================================

def fetch_option_data(client, symbol, trade_date):
    result = client.history(
        symbol=symbol,
        exchange=OPTION_EXCHANGE,
        interval=INTERVAL,
        start_date=trade_date.strftime("%Y-%m-%d"),
        end_date=trade_date.strftime("%Y-%m-%d"),
    )
    option_df = _to_df(result, symbol)
    if option_df is None:
        return None

    option_df = option_df.sort_index()

    option_df["ATR"] = ta.atr(
        option_df["high"],
        option_df["low"],
        option_df["close"],
        ATR_PERIOD,
    )
    option_df.dropna(inplace=True)
    return option_df


# ==========================================================
# BACKTEST
# ==========================================================

def run_backtest(client, spot_df):
    trades = []
    equity = 0
    equity_curve = []
    chart_entries = []
    chart_exits = []

    spot_df["date"] = spot_df.index.normalize() if hasattr(spot_df.index, "normalize") else spot_df.index.date

    for trade_date, day_df in spot_df.groupby("date"):
        orb_df = day_df.between_time(ORB_START, ORB_END)

        if len(orb_df) < 3:
            continue

        orb_high = orb_df["high"].max()
        orb_low = orb_df["low"].min()

        post_orb = day_df[day_df.index > orb_df.index[-1]]

        position = None

        for ts, row in post_orb.iterrows():
            close = row["close"]

            # ==================================================
            # ENTRY LOGIC
            # ==================================================

            if position is None:
                option_type = None
                if close > orb_high:
                    option_type = "CE"
                elif close < orb_low:
                    option_type = "PE"

                if option_type:
                    strike = get_atm_strike(close)
                    expiry = get_monthly_expiry(trade_date)
                    option_symbol = build_option_symbol(strike, expiry, option_type)

                    option_df = fetch_option_data(
                        client, option_symbol, pd.Timestamp(trade_date)
                    )

                    if option_df is None:
                        continue

                    option_df = option_df[option_df.index >= ts]

                    if len(option_df) == 0:
                        continue

                    entry_bar = option_df.iloc[0]
                    entry_time = option_df.index[0]

                    position = {
                        "symbol": option_symbol,
                        "type": option_type,
                        "strike": strike,
                        "entry_time": entry_time,
                        "entry_price": entry_bar["close"],
                    }

                    trail_stop = entry_bar["close"] - (entry_bar["ATR"] * ATR_MULTIPLIER)

                    chart_entries.append((ts, close))

                    # ==========================================
                    # OPTION MANAGEMENT
                    # ==========================================

                    for opt_ts, opt_row in option_df.iloc[1:].iterrows():
                        option_close = opt_row["close"]
                        atr = opt_row["ATR"]

                        trail_stop = max(
                            trail_stop,
                            option_close - (atr * ATR_MULTIPLIER),
                        )

                        eod_exit = opt_ts.time().strftime("%H:%M") >= "15:25"
                        stop_hit = option_close < trail_stop

                        if stop_hit or eod_exit:
                            pnl = (option_close - position["entry_price"]) * LOT_SIZE

                            trades.append({
                                "Date": trade_date,
                                "Option": position["symbol"],
                                "Type": position["type"],
                                "Strike": position["strike"],
                                "Entry Time": position["entry_time"],
                                "Exit Time": opt_ts,
                                "Entry": round(position["entry_price"], 2),
                                "Exit": round(option_close, 2),
                                "PnL": round(pnl, 2),
                            })

                            equity += pnl
                            equity_curve.append({"Date": opt_ts, "Equity": equity})
                            chart_exits.append((opt_ts, close))
                            position = None
                            break

                    break

    return (
        pd.DataFrame(trades),
        pd.DataFrame(equity_curve),
        chart_entries,
        chart_exits,
    )


# ==========================================================
# METRICS
# ==========================================================

def calculate_metrics(trades_df, equity_df):
    total_trades = len(trades_df)
    wins = (trades_df["PnL"] > 0).sum()
    losses = (trades_df["PnL"] <= 0).sum()
    win_rate = wins / total_trades * 100 if total_trades else 0
    net_pnl = trades_df["PnL"].sum() if total_trades else 0

    avg_win = trades_df[trades_df["PnL"] > 0]["PnL"].mean()
    avg_loss = trades_df[trades_df["PnL"] <= 0]["PnL"].mean()
    gross_profit = trades_df[trades_df["PnL"] > 0]["PnL"].sum()
    gross_loss = abs(trades_df[trades_df["PnL"] <= 0]["PnL"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.nan

    if len(equity_df):
        equity_df["Peak"] = equity_df["Equity"].cummax()
        equity_df["Drawdown"] = equity_df["Equity"] - equity_df["Peak"]
        max_dd = equity_df["Drawdown"].min()
    else:
        max_dd = 0

    print("\n========== RESULTS ==========")
    print(f"Total Trades : {total_trades}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(f"Win Rate     : {win_rate:.2f}%")
    print(f"Net PnL      : {net_pnl:.2f}")
    print(f"Avg Win      : {avg_win:.2f}")
    print(f"Avg Loss     : {avg_loss:.2f}")
    print(f"ProfitFactor : {profit_factor:.2f}")
    print(f"Max DD       : {max_dd:.2f}")


# ==========================================================
# PLOTLY CHART
# ==========================================================

def plot_strategy(spot_df, entries, exits, equity_df):
    plot_df = spot_df.tail(600).copy()
    formatted_index = plot_df.index.strftime("%d-%b<br>%H:%M")

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=formatted_index,
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        name="SENSEX",
    ))

    if entries:
        fig.add_trace(go.Scatter(
            x=[x[0].strftime("%d-%b<br>%H:%M") for x in entries],
            y=[x[1] for x in entries],
            mode="markers",
            name="BUY",
        ))

    if exits:
        fig.add_trace(go.Scatter(
            x=[x[0].strftime("%d-%b<br>%H:%M") for x in exits],
            y=[x[1] for x in exits],
            mode="markers",
            name="SELL",
        ))

    fig.update_layout(
        title="SENSEX ATM ORB Strategy",
        template="plotly_dark",
        height=800,
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(type="category")
    fig.show()

    if len(equity_df):
        equity_fig = go.Figure()
        equity_fig.add_trace(go.Scatter(
            x=equity_df["Date"],
            y=equity_df["Equity"],
            mode="lines",
            name="Equity Curve",
        ))
        equity_fig.update_layout(
            title="Equity Curve",
            template="plotly_dark",
            height=500,
        )
        equity_fig.show()


# ==========================================================
# MAIN
# ==========================================================

def main():
    client = get_client()

    spot_df = fetch_spot_history(client)

    trades_df, equity_df, entries, exits = run_backtest(client, spot_df)

    if len(trades_df) == 0:
        print("No trades generated.")
        return

    pd.set_option("display.max_columns", None)
    print("\n========== TRADE LOG ==========")
    print(trades_df)

    calculate_metrics(trades_df, equity_df)
    plot_strategy(spot_df, entries, exits, equity_df)


if __name__ == "__main__":
    main()
