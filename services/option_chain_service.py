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

from datetime import UTC, datetime
from typing import Any

from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from database.token_db import get_br_symbol
from database.token_db_enhanced import fno_search_symbols
from services.option_greeks_service import (
    calculate_chain_greeks,
    calculate_time_to_expiry,
    get_expiry_datetime,
)
from services.option_symbol_service import (
    NO_SPOT_EXCHANGES,
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
    parse_underlying_symbol,
    resolve_underlying_quote,
)
from services.quotes_service import get_multiquotes, get_quotes, import_broker_module
from utils.constants import CRYPTO_EXCHANGES, INSTRUMENT_PERPFUT
from utils.logging import get_logger

logger = get_logger(__name__)


def _reference_metadata(symbol: str, exchange: str) -> dict[str, str]:
    """Expose the exact quote identity selected while resolving the chain."""
    return {
        "underlying_symbol": symbol,
        "underlying_exchange": exchange,
    }


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


def _forward_from_chain(
    chain: list[dict[str, Any]], atm_strike: float, underlying_ltp: float
) -> float:
    """
    Derive the forward price from the chain's own ATM legs via put-call parity.

    Black-76 prices off the forward, not spot. Indian index futures carry a
    premium over spot, so pricing an index chain off the spot LTP biases every
    delta. The ATM call and put are already in hand, so F = K + (C - P) costs
    nothing extra.

    Falls back to the underlying LTP when the ATM legs have no usable quotes.

    Args:
        chain: Assembled chain rows
        atm_strike: ATM strike
        underlying_ltp: Underlying spot or near-month future price

    Returns:
        Forward price to use for the whole chain
    """
    for row in chain:
        if row.get("strike") != atm_strike:
            continue
        ce = row.get("ce") or {}
        pe = row.get("pe") or {}
        ce_ltp = ce.get("ltp") or 0
        pe_ltp = pe.get("ltp") or 0
        if ce_ltp > 0 and pe_ltp > 0:
            return round(atm_strike + ce_ltp - pe_ltp, 4)
        break

    logger.info("ATM legs unpriced; falling back to underlying LTP as the forward")
    return underlying_ltp


def _attach_chain_greeks(
    chain: list[dict[str, Any]],
    expiry_dt: datetime | None,
    forward_price: float,
    interest_rate: float | None,
) -> None:
    """
    Attach implied_volatility and Greeks to every leg of an assembled chain, in place.

    One vectorized Black-76 pass over the whole ladder. Legs whose Greeks are not
    computable are left without the fields rather than filled with zeros, so a
    caller can tell "no data" from "genuinely zero".

    Args:
        chain: Assembled chain rows, mutated in place
        expiry_dt: Expiry instant, or None if it could not be derived
        forward_price: Forward price for the chain
        interest_rate: Annualized rate percentage, or None for the default
    """
    if expiry_dt is None:
        logger.warning("Skipping chain Greeks: expiry timestamp unavailable")
        return

    time_to_expiry_years, _ = calculate_time_to_expiry(expiry_dt)
    if time_to_expiry_years <= 0:
        logger.info("Skipping chain Greeks: option chain has expired")
        return

    strikes = [row["strike"] for row in chain]
    ce_prices = [(row.get("ce") or {}).get("ltp", 0) for row in chain]
    pe_prices = [(row.get("pe") or {}).get("ltp", 0) for row in chain]

    ce_greeks, pe_greeks = calculate_chain_greeks(
        strikes, ce_prices, pe_prices, forward_price, time_to_expiry_years, interest_rate
    )

    for row, ce_g, pe_g in zip(chain, ce_greeks, pe_greeks, strict=True):
        for leg_key, greeks in (("ce", ce_g), ("pe", pe_g)):
            leg = row.get(leg_key)
            if leg is None or greeks is None:
                continue
            leg["implied_volatility"] = greeks["iv"]
            leg["delta"] = greeks["delta"]
            leg["gamma"] = greeks["gamma"]
            leg["theta"] = greeks["theta"]
            leg["vega"] = greeks["vega"]


def get_option_chain(
    underlying: str,
    exchange: str,
    expiry_date: str,
    strike_count: int,
    api_key: str,
    with_quotes: bool = True,
    with_greeks: bool = False,
    interest_rate: float | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Main function to get option chain data.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
        exchange: Exchange (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO, MCX, CDS)
        expiry_date: Expiry date in DDMMMYY format (e.g., 28NOV25)
        strike_count: Number of strikes above and below ATM
        api_key: OpenAlgo API key
        with_quotes: When True (default) fetch live per-strike quotes via the broker.
            When False, build the strike ladder + ATM + symbols/lotsize/tick purely from
            cache/DB (one underlying LTP only) and leave price fields at 0 — used by the
            scalping ladder, which streams live prices over the WebSocket feed instead of
            paying for a slow per-strike broker multiquote.
        with_greeks: When True, attach implied_volatility plus delta/gamma/theta/vega to
            every leg. Computed from the quotes already fetched via one vectorized
            Black-76 pass, so it costs no extra broker calls. Ignored when
            with_quotes is False, since there are no prices to invert.
        interest_rate: Risk-free rate as an annualized percentage, used only for Greeks.
            Defaults to the exchange default (0).

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
            # CRYPTO: look up the canonical perpetual symbol from cache (e.g. BTC -> BTCUSDFUT)
            quote_exchange = exchange.upper()
            _perp = fno_search_symbols(
                query=f"{base_symbol}USDFUT", exchange=exchange, instrumenttype=INSTRUMENT_PERPFUT, limit=1
            )
            if not _perp:
                return (
                    False,
                    {"status": "error", "message": f"No perpetual futures found for {base_symbol} on {exchange}"},
                    404,
                )
            quote_symbol = _perp[0]["symbol"]

        elif exchange.upper() in NO_SPOT_EXCHANGES:
            # MCX and the currency segments list no spot instrument: there is a
            # CRUDEOIL19AUG26FUT but no plain CRUDEOIL, so a spot quote returns
            # nothing and the chain comes back with no underlying price at all.
            # The near-month future is the pricing reference instead.
            quote_exchange = exchange.upper()
            resolved = resolve_underlying_quote(base_symbol, quote_exchange)
            if resolved is None:
                return (
                    False,
                    {
                        "status": "error",
                        "message": (
                            f"No unexpired futures found for {base_symbol} on "
                            f"{quote_exchange}. {quote_exchange} options are priced "
                            "against the near-month future, which this product does "
                            "not currently have."
                        ),
                    },
                    404,
                )
            quote_symbol, quote_exchange = resolved
            logger.info(
                f"{exchange.upper()} has no spot; pricing {base_symbol} against "
                f"{quote_symbol}"
            )

        if exchange.upper() not in CRYPTO_EXCHANGES and exchange.upper() not in NO_SPOT_EXCHANGES:
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

        # Step 8: Fetch live quotes for all options via multiquotes. Skipped when
        # with_quotes=False (e.g. the scalping ladder) — the structure is built from
        # cache/DB and live prices stream over the WebSocket feed, avoiding a slow
        # per-strike broker multiquote (e.g. Flattrade throttles to 10 quotes/sec).
        quotes_map = {}
        quotes_response: dict = {}
        success = False
        if with_quotes:
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
                # Fyers fast path: its native /data/options-chain-v3 endpoint
                # returns every CE/PE strike (LTP, OI, bid/ask, volume) in ONE
                # call, instead of a bulk /data/quotes call plus one
                # /data/depth call PER symbol just to backfill OI (Fyers'
                # bulk quotes endpoint doesn't include OI at all). The
                # per-symbol depth fallback is what made large chains take
                # 10+ seconds. Only usable when a bounded strike_count was
                # requested -- Fyers caps strikecount at 50, so an
                # unbounded "entire chain" request (strike_count=None) still
                # needs the generic path.
                used_fast_path = False
                if strike_count is not None and strike_count <= 50:
                    _auth, _, _broker = get_auth_token_broker(api_key, include_feed_token=True)
                    if _broker == "fyers" and _auth:
                        _bmod = import_broker_module(_broker)
                        if _bmod is not None and hasattr(_bmod.BrokerData, "get_option_chain"):
                            try:
                                fyers_symbol = get_br_symbol(quote_symbol, quote_exchange)
                                _dh = _bmod.BrokerData(_auth)
                                # +2 buffer absorbs Fyers computing its own ATM a
                                # strike off from ours; harmless if unused, and
                                # still capped at Fyers' hard max of 50.
                                fyers_chain = _dh.get_option_chain(
                                    fyers_symbol, strikecount=min(strike_count + 2, 50)
                                )
                                for item in chain_symbols:
                                    strike = item["strike"]
                                    if item["ce"]["exists"]:
                                        data = fyers_chain.get((strike, "CE"))
                                        if data:
                                            quotes_map[item["ce"]["symbol"]] = data
                                    if item["pe"]["exists"]:
                                        data = fyers_chain.get((strike, "PE"))
                                        if data:
                                            quotes_map[item["pe"]["symbol"]] = data
                                used_fast_path = bool(fyers_chain)
                            except Exception as _fe:
                                logger.warning(
                                    f"Fyers fast-path option chain failed, falling back to "
                                    f"generic multiquotes: {_fe}"
                                )
                                quotes_map = {}

                if not used_fast_path:
                    success, quotes_response, status_code = get_multiquotes(
                        symbols=symbols_to_fetch, api_key=api_key
                    )

            # Build the quote lookup map from whichever branch produced results.
            # The Fyers fast path is the only one that fills quotes_map itself;
            # both the crypto per-symbol loop and the generic multiquotes call
            # hand back a results list that still has to be indexed here.
            if not quotes_map and success and "results" in quotes_response:
                for result in quotes_response["results"]:
                    symbol = result.get("symbol")
                    if symbol:
                        # Handle both formats: direct data or nested data
                        if "data" in result:
                            quotes_map[symbol] = result["data"]
                        elif "error" not in result:
                            quotes_map[symbol] = result
        else:
            logger.info(
                f"Structure-only option chain ({len(symbols_to_fetch)} symbols); skipping live quotes"
            )

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
                    "bid_qty": ce_quote.get("bid_qty", 0),
                    "ask_qty": ce_quote.get("ask_qty", 0),
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
                    "bid_qty": pe_quote.get("bid_qty", 0),
                    "ask_qty": pe_quote.get("ask_qty", 0),
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

        # The exact expiry instant, so callers computing time to expiry themselves
        # (the browser, for one) do not have to re-derive each exchange's cut-off.
        expiry_dt = None
        expiry_ts = None
        forward_price = None
        try:
            expiry_dt = get_expiry_datetime(final_expiry, options_exchange)
            expiry_ts = int(expiry_dt.timestamp())
        except ValueError:
            logger.warning(f"Could not derive expiry timestamp from {final_expiry}")

        if with_quotes and with_greeks:
            forward_price = _forward_from_chain(chain, atm_strike, underlying_ltp)
            _attach_chain_greeks(chain, expiry_dt, forward_price, interest_rate)

        return (
            True,
            {
                "status": "success",
                "underlying": base_symbol,
                **_reference_metadata(quote_symbol, quote_exchange),
                "underlying_ltp": underlying_ltp,
                "underlying_prev_close": underlying_prev_close,
                "expiry_date": final_expiry,
                "expiry_ts": expiry_ts,
                # Lets a client correct for its own clock skew before computing
                # time to expiry, which otherwise silently biases every Greek.
                "server_ts": int(datetime.now(UTC).timestamp()),
                "atm_strike": atm_strike,
                "quotes_included": with_quotes,
                "greeks_included": bool(with_quotes and with_greeks),
                "forward_price": forward_price,
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
