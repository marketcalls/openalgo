"""
Straddle Chart Service
Computes Dynamic ATM Straddle time series from historical candle data.

For each candle timestamp, determines the ATM strike from the underlying close,
then looks up the corresponding CE and PE option prices to compute:
- Straddle value = CE + PE
- Synthetic Future = Strike + CE - PE
"""

from datetime import datetime, timedelta

import pandas as pd
import pytz

from services.history_service import get_history
from services.option_greeks_service import parse_option_symbol
from services.option_symbol_service import (
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
)
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)

# Index symbols that need NSE_INDEX/BSE_INDEX for quotes
NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYPHARMA",
    "NIFTYBANK",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def _get_quote_exchange(base_symbol, underlying_exchange):
    """Determine the exchange to use for fetching underlying quotes."""
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if underlying_exchange.upper() in ("NFO", "BFO"):
        return "NSE" if underlying_exchange.upper() == "NFO" else "BSE"
    return underlying_exchange.upper()


def _convert_timestamp_to_ist(df):
    """
    Convert timestamp column in a history DataFrame to IST datetime index.
    Returns the dataframe with 'datetime' index in IST, or None on failure.
    """
    ist = pytz.timezone("Asia/Kolkata")

    try:
        if "timestamp" not in df.columns:
            logger.warning("No timestamp field found in history data")
            return None

        # Try as Unix timestamp (seconds)
        try:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            df["datetime"] = df["datetime"].dt.tz_convert(ist)
        except Exception:
            # Try as milliseconds
            try:
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df["datetime"] = df["datetime"].dt.tz_convert(ist)
            except Exception:
                # Try as string datetime
                df["datetime"] = pd.to_datetime(df["timestamp"])
                if df["datetime"].dt.tz is None:
                    df["datetime"] = df["datetime"].dt.tz_localize("UTC").dt.tz_convert(ist)
                else:
                    df["datetime"] = df["datetime"].dt.tz_convert(ist)

        df.set_index("datetime", inplace=True)
        df = df.sort_index()
        return df
    except Exception as e:
        logger.warning(f"Error converting timestamps: {e}")
        return None


def get_straddle_chart_data(
    underlying,
    exchange,
    expiry_date,
    interval,
    api_key,
    days=5,
):
    """
    Compute Dynamic ATM Straddle time series.

    For each candle, the ATM strike is recomputed from the underlying close price.
    Option CE/PE prices are fetched for all unique ATM strikes that appear, then
    merged per-timestamp.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
        exchange: Underlying exchange (e.g., "NSE_INDEX", "BSE_INDEX")
        expiry_date: Expiry in DDMMMYY format (e.g., "06FEB26")
        interval: Candle interval (e.g., "1m", "5m")
        api_key: OpenAlgo API key
        days: Number of days of history (default 5)

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        today = datetime.now(ist).date()
        # Skip weekends
        weekday = today.weekday()
        if weekday == 5:  # Saturday
            today = today - timedelta(days=1)
        elif weekday == 6:  # Sunday
            today = today - timedelta(days=2)
        end_date_str = today.strftime("%Y-%m-%d")
        start_date_str = (today - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")

        # Step 1: Determine exchanges
        base_symbol = underlying.upper()
        quote_exchange = _get_quote_exchange(base_symbol, exchange)
        options_exchange = get_option_exchange(quote_exchange)

        # Step 2: Get available strikes for the expiry
        available_strikes = get_available_strikes(
            base_symbol, expiry_date.upper(), "CE", options_exchange
        )
        if not available_strikes:
            return (
                False,
                {
                    "status": "error",
                    "message": f"No strikes found for {base_symbol} {expiry_date} on {options_exchange}",
                },
                404,
            )

        # Step 3: Fetch underlying history
        success_u, resp_u, _ = get_history(
            symbol=base_symbol,
            exchange=quote_exchange,
            interval=interval,
            start_date=start_date_str,
            end_date=end_date_str,
            api_key=api_key,
        )
        if not success_u:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Failed to fetch underlying history: {resp_u.get('message', 'Unknown error')}",
                },
                400,
            )

        df_underlying = pd.DataFrame(resp_u.get("data", []))
        if df_underlying.empty:
            return False, {"status": "error", "message": "No underlying history data available"}, 404

        df_underlying = _convert_timestamp_to_ist(df_underlying)
        if df_underlying is None:
            return False, {"status": "error", "message": "Failed to parse underlying timestamps"}, 500

        # Step 4: For each candle, compute ATM strike
        atm_per_row = []
        for ts, row in df_underlying.iterrows():
            close_price = float(row["close"])
            atm = find_atm_strike_from_actual(close_price, available_strikes)
            atm_per_row.append(atm)

        df_underlying["atm_strike"] = atm_per_row

        # Step 5: Collect unique ATM strikes
        unique_strikes = set(s for s in atm_per_row if s is not None)
        if not unique_strikes:
            return False, {"status": "error", "message": "Could not determine any ATM strikes"}, 400

        logger.debug(f"Straddle chart: {len(unique_strikes)} unique ATM strikes for {base_symbol}: {sorted(unique_strikes)}")

        # Step 6: For each unique strike, fetch CE and PE history
        # Build lookup: {strike: {timestamp: {ce_close, pe_close}}}
        strike_data = {}

        for strike in sorted(unique_strikes):
            ce_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), strike, "CE")
            pe_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), strike, "PE")

            # Fetch CE history
            success_ce, resp_ce, _ = get_history(
                symbol=ce_symbol,
                exchange=options_exchange,
                interval=interval,
                start_date=start_date_str,
                end_date=end_date_str,
                api_key=api_key,
            )

            # Fetch PE history
            success_pe, resp_pe, _ = get_history(
                symbol=pe_symbol,
                exchange=options_exchange,
                interval=interval,
                start_date=start_date_str,
                end_date=end_date_str,
                api_key=api_key,
            )

            ce_lookup = {}
            pe_lookup = {}

            if success_ce:
                df_ce = pd.DataFrame(resp_ce.get("data", []))
                if not df_ce.empty:
                    df_ce = _convert_timestamp_to_ist(df_ce)
                    if df_ce is not None:
                        for ts, row in df_ce.iterrows():
                            ce_lookup[ts] = float(row["close"])

            if success_pe:
                df_pe = pd.DataFrame(resp_pe.get("data", []))
                if not df_pe.empty:
                    df_pe = _convert_timestamp_to_ist(df_pe)
                    if df_pe is not None:
                        for ts, row in df_pe.iterrows():
                            pe_lookup[ts] = float(row["close"])

            strike_data[strike] = {"ce": ce_lookup, "pe": pe_lookup}

        # Step 7: Merge — walk underlying candles, pick CE/PE from the correct strike
        series = []
        for ts, row in df_underlying.iterrows():
            spot = float(row["close"])
            atm_strike = row["atm_strike"]

            if atm_strike is None or atm_strike not in strike_data:
                continue

            sd = strike_data[atm_strike]
            ce_price = sd["ce"].get(ts)
            pe_price = sd["pe"].get(ts)

            if ce_price is None or pe_price is None:
                continue

            straddle = round(ce_price + pe_price, 2)
            synthetic_future = round(atm_strike + ce_price - pe_price, 2)

            # Convert timestamp to Unix seconds (UTC) for lightweight-charts
            unix_seconds = int(ts.timestamp())

            series.append(
                {
                    "time": unix_seconds,
                    "spot": round(spot, 2),
                    "atm_strike": atm_strike,
                    "ce_price": round(ce_price, 2),
                    "pe_price": round(pe_price, 2),
                    "straddle": straddle,
                    "synthetic_future": synthetic_future,
                }
            )

        if not series:
            return (
                False,
                {"status": "error", "message": "No straddle data available (option history may be missing)"},
                404,
            )

        # Get current LTP for display
        success_q, quote_resp, _ = get_quotes(
            symbol=base_symbol,
            exchange=quote_exchange,
            api_key=api_key,
        )
        underlying_ltp = quote_resp.get("data", {}).get("ltp", 0) if success_q else 0

        # Calculate days to expiry from the expiry date
        days_to_expiry = _calculate_days_to_expiry(expiry_date)

        return (
            True,
            {
                "status": "success",
                "data": {
                    "underlying": base_symbol,
                    "underlying_ltp": underlying_ltp,
                    "expiry_date": expiry_date.upper(),
                    "interval": interval,
                    "days_to_expiry": days_to_expiry,
                    "series": series,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error calculating straddle chart data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def _calculate_days_to_expiry(expiry_date_str):
    """
    Calculate days to expiry from DDMMMYY format string.

    Args:
        expiry_date_str: Expiry in DDMMMYY format (e.g., "06FEB26")

    Returns:
        Number of calendar days to expiry, or 0 if expired/parse error
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.now(ist)
        expiry_dt = datetime.strptime(expiry_date_str.upper(), "%d%b%y")
        # Set expiry to 15:30 IST (market close)
        expiry_dt = expiry_dt.replace(hour=15, minute=30)
        expiry_dt = ist.localize(expiry_dt)
        delta = expiry_dt - now
        return max(0, delta.days)
    except Exception:
        return 0
