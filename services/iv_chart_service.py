"""
IV Chart Service
Calculates intraday Implied Volatility time series for option symbols.

Uses historical OHLCV candle data and Black-76 model to compute IV at each
candle's close price. Returns IV time series suitable for charting.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytz

from services.history_service import get_history
from services.option_greeks_service import (
    DEFAULT_INTEREST_RATES,
    parse_option_symbol,
)
from services.option_symbol_service import (
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
)
from services.quotes_service import get_quotes
from utils.logging import get_logger

# Import py_vollib for Black-76 IV and Greeks calculation
try:
    from py_vollib.black.greeks.analytical import delta as black_delta
    from py_vollib.black.greeks.analytical import gamma as black_gamma
    from py_vollib.black.greeks.analytical import theta as black_theta
    from py_vollib.black.greeks.analytical import vega as black_vega
    from py_vollib.black.implied_volatility import implied_volatility as black_iv

    PYVOLLIB_AVAILABLE = True
except ImportError:
    PYVOLLIB_AVAILABLE = False

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


def calculate_time_to_expiry_at(candle_time, expiry):
    """
    Calculate time to expiry in years from a specific candle timestamp.

    Unlike calculate_time_to_expiry() which uses datetime.now(), this
    calculates relative to an arbitrary historical timestamp for IV
    computation on past candles.

    Args:
        candle_time: datetime of the candle (naive, treated as IST)
        expiry: datetime of option expiry (naive, IST)

    Returns:
        Tuple of (time_in_years, time_in_days)
    """
    if expiry <= candle_time:
        return 0.0, 0.0

    time_delta = expiry - candle_time
    days_to_expiry = time_delta.total_seconds() / (60 * 60 * 24)
    years_to_expiry = days_to_expiry / 365.0

    # Minimum threshold to avoid numerical issues
    if years_to_expiry < 0.0001:
        years_to_expiry = 0.0001
        days_to_expiry = years_to_expiry * 365.0

    return years_to_expiry, days_to_expiry


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


def get_iv_chart_data(
    underlying,
    exchange,
    expiry_date,
    interval,
    api_key,
    days=1,
):
    """
    Calculate intraday IV time series for ATM CE and PE options.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
        exchange: Underlying exchange (e.g., "NSE_INDEX", "BSE_INDEX")
        expiry_date: Expiry in DDMMMYY format (e.g., "06FEB26")
        interval: Candle interval (e.g., "5m", "1m", "15m")
        api_key: OpenAlgo API key
        days: Number of days of history to load (default 1)

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    if not PYVOLLIB_AVAILABLE:
        return (
            False,
            {
                "status": "error",
                "message": "py_vollib library required for IV calculation. Install with: pip install py_vollib",
            },
            500,
        )

    try:
        ist = pytz.timezone("Asia/Kolkata")
        today = datetime.now(ist).date()
        # If today is a weekend (Saturday=5, Sunday=6), use last Friday
        weekday = today.weekday()
        if weekday == 5:  # Saturday
            today = today - timedelta(days=1)
        elif weekday == 6:  # Sunday
            today = today - timedelta(days=2)
        end_date_str = today.strftime("%Y-%m-%d")
        start_date_str = (today - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")

        # Step 1: Determine quote exchange and options exchange
        base_symbol = underlying.upper()
        quote_exchange = _get_quote_exchange(base_symbol, exchange)
        options_exchange = get_option_exchange(quote_exchange)

        # Step 2: Get underlying LTP to resolve ATM strike
        success, quote_response, status_code = get_quotes(
            symbol=base_symbol,
            exchange=quote_exchange,
            api_key=api_key,
        )
        if not success:
            return (
                False,
                {"status": "error", "message": f"Failed to fetch underlying quote: {quote_response.get('message', 'Unknown error')}"},
                status_code,
            )

        underlying_ltp = quote_response.get("data", {}).get("ltp", 0)
        if not underlying_ltp:
            return False, {"status": "error", "message": "Could not get underlying LTP"}, 400

        # Step 3: Resolve ATM CE and PE symbols
        available_strikes = get_available_strikes(
            base_symbol, expiry_date.upper(), "CE", options_exchange
        )
        if not available_strikes:
            return (
                False,
                {"status": "error", "message": f"No strikes found for {base_symbol} {expiry_date} on {options_exchange}"},
                404,
            )

        atm_strike = find_atm_strike_from_actual(underlying_ltp, available_strikes)
        if atm_strike is None:
            return False, {"status": "error", "message": "Could not determine ATM strike"}, 400

        ce_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), atm_strike, "CE")
        pe_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), atm_strike, "PE")

        # Step 4: Parse option symbols to get expiry datetime
        _, expiry_dt, strike, _ = parse_option_symbol(ce_symbol, options_exchange)

        # Step 5: Get interest rate
        interest_rate_pct = DEFAULT_INTEREST_RATES.get(options_exchange, 0)
        interest_rate_decimal = interest_rate_pct / 100.0

        # Step 6: Fetch intraday history for underlying and both option symbols
        # Underlying history - use the underlying exchange for index symbols
        underlying_history_exchange = quote_exchange
        # For index symbols like NIFTY on NSE_INDEX, the history service needs the right exchange
        success_u, resp_u, _ = get_history(
            symbol=base_symbol,
            exchange=underlying_history_exchange,
            interval=interval,
            start_date=start_date_str,
            end_date=end_date_str,
            api_key=api_key,
        )

        success_ce, resp_ce, _ = get_history(
            symbol=ce_symbol,
            exchange=options_exchange,
            interval=interval,
            start_date=start_date_str,
            end_date=end_date_str,
            api_key=api_key,
        )

        success_pe, resp_pe, _ = get_history(
            symbol=pe_symbol,
            exchange=options_exchange,
            interval=interval,
            start_date=start_date_str,
            end_date=end_date_str,
            api_key=api_key,
        )

        if not success_u:
            return (
                False,
                {"status": "error", "message": f"Failed to fetch underlying history: {resp_u.get('message', 'Unknown error')}"},
                400,
            )

        # Step 7: Convert to DataFrames and align timestamps
        df_underlying = pd.DataFrame(resp_u.get("data", []))
        df_ce = pd.DataFrame(resp_ce.get("data", [])) if success_ce else pd.DataFrame()
        df_pe = pd.DataFrame(resp_pe.get("data", [])) if success_pe else pd.DataFrame()

        if df_underlying.empty:
            return False, {"status": "error", "message": "No underlying history data available for today"}, 404

        # Convert timestamps to IST
        df_underlying = _convert_timestamp_to_ist(df_underlying)
        if df_underlying is None:
            return False, {"status": "error", "message": "Failed to parse underlying timestamps"}, 500

        series_results = []

        # Step 8: Calculate IV for CE
        if not df_ce.empty:
            df_ce = _convert_timestamp_to_ist(df_ce)
            if df_ce is not None:
                ce_iv_data = _calculate_iv_series(
                    df_option=df_ce,
                    df_underlying=df_underlying,
                    strike=strike,
                    expiry_dt=expiry_dt,
                    flag="c",
                    interest_rate=interest_rate_decimal,
                )
                series_results.append({
                    "symbol": ce_symbol,
                    "option_type": "CE",
                    "strike": strike,
                    "iv_data": ce_iv_data,
                })

        # Step 9: Calculate IV for PE
        if not df_pe.empty:
            df_pe = _convert_timestamp_to_ist(df_pe)
            if df_pe is not None:
                pe_iv_data = _calculate_iv_series(
                    df_option=df_pe,
                    df_underlying=df_underlying,
                    strike=strike,
                    expiry_dt=expiry_dt,
                    flag="p",
                    interest_rate=interest_rate_decimal,
                )
                series_results.append({
                    "symbol": pe_symbol,
                    "option_type": "PE",
                    "strike": strike,
                    "iv_data": pe_iv_data,
                })

        if not series_results:
            return (
                False,
                {"status": "error", "message": "No option history data available for today"},
                404,
            )

        return (
            True,
            {
                "status": "success",
                "data": {
                    "underlying": base_symbol,
                    "underlying_ltp": underlying_ltp,
                    "atm_strike": atm_strike,
                    "ce_symbol": ce_symbol,
                    "pe_symbol": pe_symbol,
                    "interval": interval,
                    "series": series_results,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error calculating IV chart data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def _calculate_iv_series(df_option, df_underlying, strike, expiry_dt, flag, interest_rate):
    """
    Calculate IV at each candle timestamp by aligning option and underlying data.

    Args:
        df_option: DataFrame with option OHLCV (datetime index in IST)
        df_underlying: DataFrame with underlying OHLCV (datetime index in IST)
        strike: Option strike price
        expiry_dt: Expiry datetime (naive, IST)
        flag: "c" for call, "p" for put
        interest_rate: Decimal interest rate (e.g., 0.0 for 0%)

    Returns:
        List of dicts with time (unix seconds), iv, option_price, underlying_price
    """
    iv_data = []

    # Align on common timestamps using inner join
    common_index = df_option.index.intersection(df_underlying.index)

    for ts in common_index:
        option_close = float(df_option.loc[ts, "close"])
        underlying_close = float(df_underlying.loc[ts, "close"])

        # Calculate time to expiry from this candle's timestamp
        # Remove timezone info for comparison with naive expiry_dt
        candle_time_naive = ts.replace(tzinfo=None)
        years_to_expiry, _ = calculate_time_to_expiry_at(candle_time_naive, expiry_dt)

        iv_value = None
        delta_value = None
        gamma_value = None
        theta_value = None
        vega_value = None

        if years_to_expiry > 0 and option_close > 0 and underlying_close > 0:
            try:
                iv_decimal = black_iv(
                    option_close,
                    underlying_close,
                    strike,
                    interest_rate,
                    years_to_expiry,
                    flag,
                )
                iv_value = round(iv_decimal * 100.0, 2)

                # Calculate Greeks using the computed IV
                if iv_decimal > 0:
                    try:
                        delta_value = round(black_delta(flag, underlying_close, strike, years_to_expiry, interest_rate, iv_decimal), 4)
                        gamma_value = round(black_gamma(flag, underlying_close, strike, years_to_expiry, interest_rate, iv_decimal), 6)
                        theta_value = round(black_theta(flag, underlying_close, strike, years_to_expiry, interest_rate, iv_decimal), 4)
                        vega_value = round(black_vega(flag, underlying_close, strike, years_to_expiry, interest_rate, iv_decimal), 4)
                    except Exception:
                        pass
            except Exception:
                # IV calculation failed (deep ITM, no time value, etc.)
                iv_value = None

        # Convert timestamp to Unix seconds (UTC) for lightweight-charts
        unix_seconds = int(ts.timestamp())

        iv_data.append({
            "time": unix_seconds,
            "iv": iv_value,
            "delta": delta_value,
            "gamma": gamma_value,
            "theta": theta_value,
            "vega": vega_value,
            "option_price": option_close,
            "underlying_price": underlying_close,
        })

    return iv_data


def get_default_symbols(underlying, exchange, expiry_date, api_key):
    """
    Get ATM CE and PE symbol names for display.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY")
        exchange: Exchange (e.g., "NSE_INDEX")
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    try:
        base_symbol = underlying.upper()
        quote_exchange = _get_quote_exchange(base_symbol, exchange)
        options_exchange = get_option_exchange(quote_exchange)

        # Get underlying LTP
        success, quote_response, status_code = get_quotes(
            symbol=base_symbol,
            exchange=quote_exchange,
            api_key=api_key,
        )
        if not success:
            return False, {"status": "error", "message": "Failed to fetch underlying quote"}, status_code

        underlying_ltp = quote_response.get("data", {}).get("ltp", 0)
        if not underlying_ltp:
            return False, {"status": "error", "message": "Could not get underlying LTP"}, 400

        # Resolve ATM
        available_strikes = get_available_strikes(
            base_symbol, expiry_date.upper(), "CE", options_exchange
        )
        if not available_strikes:
            return False, {"status": "error", "message": f"No strikes found for {base_symbol} {expiry_date}"}, 404

        atm_strike = find_atm_strike_from_actual(underlying_ltp, available_strikes)
        if atm_strike is None:
            return False, {"status": "error", "message": "Could not determine ATM strike"}, 400

        ce_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), atm_strike, "CE")
        pe_symbol = construct_option_symbol(base_symbol, expiry_date.upper(), atm_strike, "PE")

        return (
            True,
            {
                "status": "success",
                "data": {
                    "ce_symbol": ce_symbol,
                    "pe_symbol": pe_symbol,
                    "atm_strike": atm_strike,
                    "exchange": options_exchange,
                    "underlying_ltp": underlying_ltp,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting default symbols: {e}")
        return False, {"status": "error", "message": str(e)}, 500
