"""
Option Chain Service

This service fetches option chain data for a given underlying and expiry.
It returns strikes around ATM with real-time quotes for both CE and PE options.
Each CE and PE option includes its own label (ATM, ITM1, ITM2, OTM1, OTM2, etc.).

Example Usage:
    Input:
        underlying: "NIFTY"
        exchange: "NSE_INDEX"
        expiry_date: "30DEC25"
        strike_count: 10

    Output:
        {
            "status": "success",
            "underlying": "NIFTY",
            "underlying_ltp": 24250.50,
            "expiry_date": "30DEC25",
            "atm_strike": 24250.0,
            "chain": [
                {
                    "strike": 24000.0,
                    "ce": { "symbol": "...", "label": "ITM5", "ltp": ..., ... },
                    "pe": { "symbol": "...", "label": "OTM5", "ltp": ..., ... }
                },
                {
                    "strike": 24250.0,
                    "ce": { "symbol": "...", "label": "ATM", ... },
                    "pe": { "symbol": "...", "label": "ATM", ... }
                },
                {
                    "strike": 24500.0,
                    "ce": { "symbol": "...", "label": "OTM5", ... },
                    "pe": { "symbol": "...", "label": "ITM5", ... }
                },
                ...
            ]
        }

Strike Labels (different for CE and PE):
    - ATM: At-The-Money strike (same for both CE and PE)
    - Strike BELOW ATM: CE is ITM, PE is OTM
    - Strike ABOVE ATM: CE is OTM, PE is ITM
"""

from typing import Any, Dict, List, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from services.option_symbol_service import (
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
    parse_underlying_symbol,
)
from services.quotes_service import get_multiquotes, get_quotes, import_broker_module
from utils.constants import CRYPTO_EXCHANGES, CRYPTO_QUOTE_CURRENCY
from utils.logging import get_logger

logger = get_logger(__name__)


def get_strikes_with_labels(
    available_strikes: list[float], atm_strike: float, strike_count: int | None = None
) -> list[dict[str, Any]]:
    """
    Get strikes with labels for CE and PE.

    Args:
        available_strikes: Sorted list of all available strikes
        atm_strike: ATM strike price
        strike_count: Number of strikes above and below ATM. If None, returns all strikes.

    Returns:
        List of dicts with strike, ce_label, and pe_label

    Label Logic:
        - Strike BELOW ATM: CE is ITM, PE is OTM
        - Strike ABOVE ATM: CE is OTM, PE is ITM
        - ATM strike: Both are ATM
    """
    if atm_strike not in available_strikes:
        logger.warning(f"ATM strike {atm_strike} not in available strikes")
        # Return all strikes without proper labels if ATM not found
        return [{"strike": s, "ce_label": "", "pe_label": ""} for s in available_strikes]

    atm_index = available_strikes.index(atm_strike)

    # If strike_count is None, use all strikes; otherwise limit around ATM
    if strike_count is None:
        selected_strikes = available_strikes
    else:
        start_index = max(0, atm_index - strike_count)
        end_index = min(len(available_strikes), atm_index + strike_count + 1)
        selected_strikes = available_strikes[start_index:end_index]

    # Build strikes with labels for both CE and PE
    result = []
    for strike in selected_strikes:
        if strike == atm_strike:
            ce_label = "ATM"
            pe_label = "ATM"
        elif strike < atm_strike:
            # Strikes below ATM: CE is ITM, PE is OTM
            position = atm_index - available_strikes.index(strike)
            ce_label = f"ITM{position}"
            pe_label = f"OTM{position}"
        else:
            # Strikes above ATM: CE is OTM, PE is ITM
            position = available_strikes.index(strike) - atm_index
            ce_label = f"OTM{position}"
            pe_label = f"ITM{position}"

        result.append({"strike": strike, "ce_label": ce_label, "pe_label": pe_label})

    return result


def get_option_symbols_for_chain(
    base_symbol: str, expiry_date: str, strikes_with_labels: list[dict[str, Any]], exchange: str
) -> list[dict[str, Any]]:
    """
    Get CE and PE symbols for each strike from database.

    Args:
        base_symbol: Base symbol (e.g., NIFTY)
        expiry_date: Expiry in DDMMMYY format
        strikes_with_labels: List of dicts with 'strike', 'ce_label', 'pe_label' keys
        exchange: Options exchange (NFO, BFO, etc.)

    Returns:
        List of dicts with strike, ce (with label), pe (with label), and metadata
    """
    chain_symbols = []

    # Convert expiry format for database lookup (DDMMMYY -> DD-MMM-YY)
    # e.g., "28FEB25" -> "28-FEB-25"
    expiry_db_fmt = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}".upper()

    for strike_info in strikes_with_labels:
        strike = strike_info["strike"]
        ce_label = strike_info["ce_label"]
        pe_label = strike_info["pe_label"]

        if exchange.upper() in CRYPTO_EXCHANGES:
            # CRYPTO canonical format: BTC28FEB2580000CE / BTC28FEB2580000PE
            # (Indian F&O-style, no dashes — prefix-match on base symbol)
            underlying_pattern = f"{base_symbol.upper()}%"
            ce_record = (
                db_session.query(SymToken)
                .filter(
                    SymToken.symbol.like(underlying_pattern),
                    SymToken.expiry == expiry_db_fmt,
                    SymToken.strike == strike,
                    SymToken.instrumenttype == "CE",
                    SymToken.exchange.in_(CRYPTO_EXCHANGES),
                )
                .first()
            )
            pe_record = (
                db_session.query(SymToken)
                .filter(
                    SymToken.symbol.like(underlying_pattern),
                    SymToken.expiry == expiry_db_fmt,
                    SymToken.strike == strike,
                    SymToken.instrumenttype == "PE",
                    SymToken.exchange.in_(CRYPTO_EXCHANGES),
                )
                .first()
            )
            strike_int = int(strike) if strike == int(strike) else strike
            ce_symbol = ce_record.symbol if ce_record else f"{base_symbol}-UNKNOWN-{strike_int}-CE"
            pe_symbol = pe_record.symbol if pe_record else f"{base_symbol}-UNKNOWN-{strike_int}-PE"
        else:
            # Construct symbol names (Indian FNO format)
            ce_symbol = construct_option_symbol(base_symbol, expiry_date, strike, "CE")
            pe_symbol = construct_option_symbol(base_symbol, expiry_date, strike, "PE")

            # Query database for both CE and PE
            ce_record = (
                db_session.query(SymToken)
                .filter(SymToken.symbol == ce_symbol, SymToken.exchange == exchange)
                .first()
            )

            pe_record = (
                db_session.query(SymToken)
                .filter(SymToken.symbol == pe_symbol, SymToken.exchange == exchange)
                .first()
            )

        chain_symbols.append(
            {
                "strike": strike,
                "ce": {
                    "symbol": ce_symbol,
                    "label": ce_label,
                    "exists": ce_record is not None,
                    "lotsize": ce_record.lotsize if ce_record else None,
                    "tick_size": ce_record.tick_size if ce_record else None,
                },
                "pe": {
                    "symbol": pe_symbol,
                    "label": pe_label,
                    "exists": pe_record is not None,
                    "lotsize": pe_record.lotsize if pe_record else None,
                    "tick_size": pe_record.tick_size if pe_record else None,
                },
            }
        )

    return chain_symbols


def get_option_chain(
    underlying: str, exchange: str, expiry_date: str, strike_count: int, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Main function to get option chain data.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
        exchange: Exchange (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO, MCX, CDS)
        expiry_date: Expiry date in DDMMMYY format (e.g., 28NOV25)
        strike_count: Number of strikes above and below ATM
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Step 1: Parse underlying symbol
        base_symbol, embedded_expiry = parse_underlying_symbol(underlying)
        final_expiry = embedded_expiry or expiry_date

        if not final_expiry:
            return False, {"status": "error", "message": "Expiry date is required."}, 400

        # Step 2: Determine quote exchange for underlying LTP
        quote_exchange = exchange
        if exchange.upper() in ["NFO", "BFO"]:
            if base_symbol in [
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "NIFTYNXT50",
                "INDIAVIX",
            ]:
                quote_exchange = "NSE_INDEX"
            elif base_symbol in ["SENSEX", "BANKEX", "SENSEX50"]:
                quote_exchange = "BSE_INDEX"
            else:
                quote_exchange = "NSE" if exchange.upper() == "NFO" else "BSE"
        elif exchange.upper() in CRYPTO_EXCHANGES:
            # CRYPTO: underlying perpetual canonical symbol (e.g. BTC -> BTCUSDT)
            quote_exchange = exchange.upper()
            quote_symbol = f"{base_symbol}{CRYPTO_QUOTE_CURRENCY}"

        if exchange.upper() not in CRYPTO_EXCHANGES:
            # Use base symbol for index quotes (non-Delta)
            quote_symbol = base_symbol if embedded_expiry else underlying

        # Step 3: Fetch underlying LTP
        logger.info(f"Fetching LTP for {quote_symbol} on {quote_exchange}")
        if exchange.upper() in CRYPTO_EXCHANGES:
            # Initialise broker auth/module once here and reuse in Step 8 for the
            # option multiquote fetch.  Doing it once avoids a duplicate DB query
            # and module import inside the same request.
            _auth, _feed, _broker = get_auth_token_broker(api_key, include_feed_token=True)
            if _auth is None:
                return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
            _bmod = import_broker_module(_broker)
            if _bmod is None:
                return False, {"status": "error", "message": "Broker module not found"}, 404
            _dh = _bmod.BrokerData(_auth)
            try:
                _q = _dh.get_quotes(quote_symbol, quote_exchange)
                quote_response = {"data": _q}
                success = True
                status_code = 200
            except Exception as _e:
                return (
                    False,
                    {"status": "error", "message": f"Failed to fetch LTP for {quote_symbol}: {_e}"},
                    500,
                )
        else:
            success, quote_response, status_code = get_quotes(
                symbol=quote_symbol, exchange=quote_exchange, api_key=api_key
            )

        if not success:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Failed to fetch LTP for {quote_symbol}: {quote_response.get('message', 'Unknown error')}",
                },
                status_code,
            )

        underlying_data = quote_response.get("data", {})
        underlying_ltp = underlying_data.get("ltp")
        underlying_prev_close = underlying_data.get("prev_close", 0)
        if underlying_ltp is None:
            return (
                False,
                {"status": "error", "message": f"Could not determine LTP for {quote_symbol}"},
                500,
            )

        logger.info(f"Underlying LTP: {underlying_ltp}, Prev Close: {underlying_prev_close}")

        # Step 4: Get options exchange and available strikes
        options_exchange = get_option_exchange(quote_exchange)

        # Get strikes for CE (same strikes will work for PE)
        available_strikes = get_available_strikes(base_symbol, final_expiry, "CE", options_exchange)

        if not available_strikes:
            return (
                False,
                {
                    "status": "error",
                    "message": f"No strikes found for {base_symbol} expiring {final_expiry}. Please check expiry date or update master contract.",
                },
                404,
            )

        # Step 5: Find ATM and get strikes around it
        atm_strike = find_atm_strike_from_actual(underlying_ltp, available_strikes)
        if atm_strike is None:
            return False, {"status": "error", "message": "Failed to determine ATM strike"}, 500

        strikes_with_labels = get_strikes_with_labels(available_strikes, atm_strike, strike_count)
        logger.info(
            f"Selected {len(strikes_with_labels)} strikes (strike_count={'all' if strike_count is None else strike_count})"
        )

        # Step 6: Get symbol details for all strikes
        chain_symbols = get_option_symbols_for_chain(
            base_symbol, final_expiry, strikes_with_labels, options_exchange
        )

        # Step 7: Build list of symbols for multiquotes
        symbols_to_fetch = []
        for item in chain_symbols:
            if item["ce"]["exists"]:
                symbols_to_fetch.append(
                    {"symbol": item["ce"]["symbol"], "exchange": options_exchange}
                )
            if item["pe"]["exists"]:
                symbols_to_fetch.append(
                    {"symbol": item["pe"]["symbol"], "exchange": options_exchange}
                )

        if not symbols_to_fetch:
            return (
                False,
                {
                    "status": "error",
                    "message": "No valid option symbols found for the given parameters",
                },
                404,
            )

        # Step 8: Fetch quotes for all options using multiquotes
        logger.info(f"Fetching quotes for {len(symbols_to_fetch)} option symbols")
        if exchange.upper() in CRYPTO_EXCHANGES:
            # Reuse _auth, _bmod, _dh already initialised in Step 3 — no second
            # DB query or module import needed.
            try:
                _results = []
                for _item in symbols_to_fetch:
                    try:
                        _oq = _dh.get_quotes(_item["symbol"], _item["exchange"])
                        _results.append(
                            {"symbol": _item["symbol"], "exchange": _item["exchange"], "data": _oq}
                        )
                    except Exception as _qe:
                        logger.warning(f"[CRYPTO] Quote error for {_item['symbol']}: {_qe}")
                        _results.append(
                            {"symbol": _item["symbol"], "exchange": _item["exchange"], "error": str(_qe)}
                        )
                quotes_response = {"status": "success", "results": _results}
                success = True
                status_code = 200
            except Exception as _e:
                return (
                    False,
                    {"status": "error", "message": f"Failed to fetch option quotes: {_e}"},
                    500,
                )
        else:
            success, quotes_response, status_code = get_multiquotes(
                symbols=symbols_to_fetch, api_key=api_key
            )

        # Build quote lookup map
        quotes_map = {}
        if success and "results" in quotes_response:
            for result in quotes_response["results"]:
                symbol = result.get("symbol")
                if symbol:
                    # Handle both formats: direct data or nested data
                    if "data" in result:
                        quotes_map[symbol] = result["data"]
                    elif "error" not in result:
                        quotes_map[symbol] = result

        # Step 9: Build final chain response
        chain = []
        for item in chain_symbols:
            strike_data = {"strike": item["strike"]}

            # CE data (label inside CE object)
            ce_symbol = item["ce"]["symbol"]
            if item["ce"]["exists"]:
                ce_quote = quotes_map.get(ce_symbol, {})
                strike_data["ce"] = {
                    "symbol": ce_symbol,
                    "label": item["ce"]["label"],
                    "ltp": ce_quote.get("ltp", 0),
                    "bid": ce_quote.get("bid", 0),
                    "ask": ce_quote.get("ask", 0),
                    "open": ce_quote.get("open", 0),
                    "high": ce_quote.get("high", 0),
                    "low": ce_quote.get("low", 0),
                    "prev_close": ce_quote.get("prev_close", 0),
                    "volume": ce_quote.get("volume", 0),
                    "oi": ce_quote.get("oi", 0),
                    "lotsize": item["ce"]["lotsize"],
                    "tick_size": item["ce"]["tick_size"],
                }
            else:
                strike_data["ce"] = None

            # PE data (label inside PE object)
            pe_symbol = item["pe"]["symbol"]
            if item["pe"]["exists"]:
                pe_quote = quotes_map.get(pe_symbol, {})
                strike_data["pe"] = {
                    "symbol": pe_symbol,
                    "label": item["pe"]["label"],
                    "ltp": pe_quote.get("ltp", 0),
                    "bid": pe_quote.get("bid", 0),
                    "ask": pe_quote.get("ask", 0),
                    "open": pe_quote.get("open", 0),
                    "high": pe_quote.get("high", 0),
                    "low": pe_quote.get("low", 0),
                    "prev_close": pe_quote.get("prev_close", 0),
                    "volume": pe_quote.get("volume", 0),
                    "oi": pe_quote.get("oi", 0),
                    "lotsize": item["pe"]["lotsize"],
                    "tick_size": item["pe"]["tick_size"],
                }
            else:
                strike_data["pe"] = None

            chain.append(strike_data)

        return (
            True,
            {
                "status": "success",
                "underlying": base_symbol,
                "underlying_ltp": underlying_ltp,
                "underlying_prev_close": underlying_prev_close,
                "expiry_date": final_expiry,
                "atm_strike": atm_strike,
                "chain": chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_option_chain: {e}")
        return (
            False,
            {
                "status": "error",
                "message": f"An error occurred while fetching option chain: {str(e)}",
            },
            500,
        )
