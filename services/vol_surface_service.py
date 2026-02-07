"""
Volatility Surface Service
Computes a 3D implied volatility surface across strikes and expiries
at the current instant using live option chain quotes + Black-76 IV calculation.

Uses OTM convention: CE IV for strikes >= ATM, PE IV for strikes < ATM.
"""

from typing import Any

from services.option_greeks_service import calculate_greeks, parse_option_symbol
from services.option_symbol_service import (
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
)
from services.quotes_service import get_multiquotes, get_quotes
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


def _get_quote_exchange(base_symbol: str, exchange: str) -> str:
    """Determine the exchange to use for fetching underlying quotes."""
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if exchange.upper() in ("NFO", "BFO"):
        return "NSE" if exchange.upper() == "NFO" else "BSE"
    return exchange.upper()


def get_vol_surface_data(
    underlying: str,
    exchange: str,
    expiry_dates: list[str],
    strike_count: int,
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Compute a volatility surface across multiple expiries at the current instant.

    Args:
        underlying: Base symbol (e.g., "NIFTY")
        exchange: Exchange for quotes (e.g., "NSE_INDEX")
        expiry_dates: List of expiry dates in DDMMMYY format
        strike_count: Number of strikes above and below ATM
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not expiry_dates:
            return False, {"status": "error", "message": "At least one expiry is required"}, 400

        base_symbol = underlying.upper()
        quote_exchange = _get_quote_exchange(base_symbol, exchange)
        options_exchange = get_option_exchange(quote_exchange)

        # Step 1: Fetch underlying LTP once
        success, quote_response, status_code = get_quotes(
            symbol=base_symbol, exchange=quote_exchange, api_key=api_key
        )
        if not success:
            return False, {
                "status": "error",
                "message": f"Failed to fetch LTP for {base_symbol}: {quote_response.get('message', '')}",
            }, status_code

        underlying_ltp = quote_response.get("data", {}).get("ltp")
        if not underlying_ltp:
            return False, {"status": "error", "message": f"No LTP for {base_symbol}"}, 500

        # Step 2: For each expiry, get strikes and find ATM
        expiry_strike_data = []
        for expiry in expiry_dates:
            strikes = get_available_strikes(base_symbol, expiry, "CE", options_exchange)
            if not strikes:
                logger.warning(f"No strikes found for {base_symbol} expiry {expiry}, skipping")
                continue

            atm = find_atm_strike_from_actual(underlying_ltp, strikes)
            if atm is None:
                continue

            atm_idx = strikes.index(atm)
            start = max(0, atm_idx - strike_count)
            end = min(len(strikes), atm_idx + strike_count + 1)
            selected = strikes[start:end]

            expiry_strike_data.append({
                "expiry": expiry,
                "strikes": selected,
                "atm": atm,
            })

        if not expiry_strike_data:
            return False, {"status": "error", "message": "No valid expiry data found"}, 404

        # Step 3: Use intersection of strikes for a rectangular grid
        strike_sets = [set(e["strikes"]) for e in expiry_strike_data]
        common_strikes = sorted(strike_sets[0].intersection(*strike_sets[1:]))

        if len(common_strikes) < 3:
            # Fallback: use first expiry's strikes (surface may have gaps)
            common_strikes = sorted(expiry_strike_data[0]["strikes"])

        atm_strike = expiry_strike_data[0]["atm"]

        # Step 4: For each expiry, fetch option LTPs and compute IV
        surface = []  # surface[expiry_idx][strike_idx] = IV
        expiry_info = []

        for ed in expiry_strike_data:
            expiry = ed["expiry"]

            # Build symbol list for multiquotes - OTM convention
            symbols_to_fetch = []
            symbol_map = {}  # symbol -> (strike, option_type)

            for strike in common_strikes:
                if strike >= atm_strike:
                    # Use CE for ATM and above
                    sym = construct_option_symbol(base_symbol, expiry, strike, "CE")
                    opt_type = "CE"
                else:
                    # Use PE below ATM
                    sym = construct_option_symbol(base_symbol, expiry, strike, "PE")
                    opt_type = "PE"

                symbols_to_fetch.append({"symbol": sym, "exchange": options_exchange})
                symbol_map[sym] = (strike, opt_type)

            # Batch fetch all LTPs
            success_q, quotes_resp, _ = get_multiquotes(
                symbols=symbols_to_fetch, api_key=api_key
            )

            quotes_map = {}
            if success_q and "results" in quotes_resp:
                for result in quotes_resp["results"]:
                    sym = result.get("symbol")
                    if sym:
                        data = result.get("data", result)
                        quotes_map[sym] = data.get("ltp", 0)

            # Compute IV for each strike
            iv_row = []
            for strike in common_strikes:
                if strike >= atm_strike:
                    sym = construct_option_symbol(base_symbol, expiry, strike, "CE")
                else:
                    sym = construct_option_symbol(base_symbol, expiry, strike, "PE")

                option_ltp = quotes_map.get(sym, 0)

                if not option_ltp or option_ltp <= 0:
                    iv_row.append(None)
                    continue

                try:
                    ok, greeks_resp, _ = calculate_greeks(
                        option_symbol=sym,
                        exchange=options_exchange,
                        spot_price=underlying_ltp,
                        option_price=option_ltp,
                    )
                    if ok and greeks_resp.get("status") == "success":
                        iv_val = greeks_resp.get("implied_volatility")
                        iv_row.append(round(iv_val, 2) if iv_val and iv_val > 0 else None)
                    else:
                        iv_row.append(None)
                except Exception:
                    iv_row.append(None)

            surface.append(iv_row)

            # Compute DTE from parsed symbol
            try:
                test_sym = construct_option_symbol(base_symbol, expiry, common_strikes[0], "CE")
                _, expiry_dt, _, _ = parse_option_symbol(test_sym, options_exchange)
                from datetime import datetime
                dte = max(0, (expiry_dt - datetime.now()).total_seconds() / 86400)
                expiry_info.append({"date": expiry, "dte": round(dte, 1)})
            except Exception:
                expiry_info.append({"date": expiry, "dte": 0})

        return True, {
            "status": "success",
            "data": {
                "underlying": base_symbol,
                "underlying_ltp": underlying_ltp,
                "atm_strike": atm_strike,
                "strikes": common_strikes,
                "expiries": expiry_info,
                "surface": surface,
            },
        }, 200

    except Exception as e:
        logger.exception(f"Error computing vol surface: {e}")
        return False, {"status": "error", "message": str(e)}, 500
