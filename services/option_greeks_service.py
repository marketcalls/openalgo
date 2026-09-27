"""
Option Greeks Service
Calculates option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility
for options across all supported exchanges (NFO, BFO, CDS, MCX)

Uses Black-76 model (opengreeks) - appropriate for options on futures/forwards
which is the correct model for Indian F&O markets (NFO, BFO, MCX, CDS).
opengreeks is a Rust reimplementation with byte-identical signatures to py_vollib.
"""

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from utils.constants import CRYPTO_EXCHANGES
from utils.logging import get_logger

# opengreeks is lazy-loaded inside calculate_greeks() and check_opengreeks_availability().

logger = get_logger(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")

# Exchange-specific symbol mappings
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

CURRENCY_SYMBOLS = {"USDINR", "EURINR", "GBPINR", "JPYINR"}

COMMODITY_SYMBOLS = {
    "GOLD",
    "GOLDM",
    "GOLDPETAL",
    "SILVER",
    "SILVERM",
    "SILVERMIC",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "LEAD",
    "ALUMINIUM",
    "NICKEL",
    "COTTONCANDY",
    "MENTHAOIL",
}

# Default interest rates by exchange (annualized %)
# Set to 0 - users should explicitly define interest rate if needed
DEFAULT_INTEREST_RATES = {
    "NFO": 0,  # NSE F&O
    "BFO": 0,  # BSE F&O
    "CDS": 0,  # Currency derivatives
    "MCX": 0,  # Commodities
}

MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# Expiry cut-off time (IST wall clock) per exchange. MCX is a default; the real
# cut-off varies by commodity, which is why callers can override it.
EXCHANGE_EXPIRY_TIMES = {
    "MCX": (23, 30),
    "CDS": (12, 30),
}

# NFO and BFO, and anything else that follows the equity-derivatives session.
DEFAULT_EXPIRY_TIME = (15, 30)


def get_exchange_expiry_time(
    exchange: str, custom_expiry_time: str | None = None
) -> tuple[int, int]:
    """
    Resolve the expiry cut-off time for an exchange.

    This is the single source of truth for how far into the expiry day an option
    still has time value. Both the greeks path and the option chain read it, so
    the two agree on time to expiry.

    Args:
        exchange: Exchange code (NFO, BFO, CDS, MCX, ...)
        custom_expiry_time: Optional override in "HH:MM" format

    Returns:
        Tuple of (hour, minute) in IST

    Raises:
        ValueError: If custom_expiry_time is malformed or out of range
    """
    if not custom_expiry_time:
        return EXCHANGE_EXPIRY_TIMES.get(exchange, DEFAULT_EXPIRY_TIME)

    time_parts = custom_expiry_time.split(":")
    if len(time_parts) != 2:
        raise ValueError(
            f"Invalid expiry_time format: {custom_expiry_time}. Use HH:MM format (e.g., '15:30', '19:00')"
        )

    try:
        expiry_hour = int(time_parts[0])
        expiry_minute = int(time_parts[1])
    except ValueError as e:
        raise ValueError(f"Failed to parse expiry_time '{custom_expiry_time}': {str(e)}") from e

    if not (0 <= expiry_hour <= 23) or not (0 <= expiry_minute <= 59):
        raise ValueError(
            f"Invalid expiry_time values: {custom_expiry_time}. Hour must be 0-23, minute must be 0-59"
        )

    return expiry_hour, expiry_minute


def get_expiry_datetime(
    expiry_date: str, exchange: str, custom_expiry_time: str | None = None
) -> datetime:
    """
    Build the IST-localized expiry datetime from a DDMMMYY expiry code.

    Args:
        expiry_date: Expiry in DDMMMYY format (e.g. "28NOV25")
        exchange: Exchange code, used to pick the cut-off time
        custom_expiry_time: Optional override in "HH:MM" format

    Returns:
        Timezone-aware datetime in IST

    Raises:
        ValueError: If the expiry code cannot be parsed
    """
    code = expiry_date.strip().upper()
    match = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2})", code)
    if not match:
        raise ValueError(f"Invalid expiry format: {expiry_date}. Expected DDMMMYY (e.g. 28NOV25)")

    day, month_str, year = match.groups()
    if month_str not in MONTH_MAP:
        raise ValueError(f"Invalid month in expiry: {expiry_date}")

    expiry_hour, expiry_minute = get_exchange_expiry_time(exchange, custom_expiry_time)

    return datetime(
        int("20" + year),
        MONTH_MAP[month_str],
        int(day),
        expiry_hour,
        expiry_minute,
        tzinfo=INDIA_TZ,
    )


def check_opengreeks_availability():
    """Check if opengreeks library is available"""
    try:
        from opengreeks.black76 import implied_volatility as black_iv  # noqa: F401

        return True, None, None
    except ImportError:
        logger.error("opengreeks library not installed. Install with: pip install opengreeks")
        return (
            False,
            {
                "status": "error",
                "message": "Option Greeks calculation requires opengreeks library. Install with: pip install opengreeks",
            },
            500,
        )


def parse_option_symbol(
    symbol: str, exchange: str, custom_expiry_time: str | None = None
) -> tuple[str, datetime, float, str]:
    """
    Parse option symbol to extract underlying, expiry, strike, and option type

    Format: SYMBOL[DD][MMM][YY][STRIKE][CE/PE]
    Examples:
        NFO: NIFTY28NOV2424000CE, RELIANCE28NOV241500PE
        BFO: SENSEX28NOV24100000CE
        CDS: USDINR28NOV2483.50CE
        MCX: GOLD28NOV2472000CE

    Args:
        symbol: Option symbol
        exchange: Exchange code
        custom_expiry_time: Optional custom expiry time in "HH:MM" format

    Returns:
        base_symbol: Underlying symbol
        expiry: Expiry datetime, naive and to be read as IST
        strike: Strike price (float, in same units as spot)
        opt_type: CE or PE
    """
    try:
        # CRYPTO canonical format (BTC28FEB2580000CE) uses the same
        # Indian F&O-style symbology as NFO/MCX — the regex below handles both.

        # Pattern: SYMBOL + DD + MMM + YY + STRIKE + CE/PE
        # Strike can have decimal point for currencies
        match = re.match(r"([A-Z]+)(\d{2})([A-Z]{3})(\d{2})([\d.]+)(CE|PE)", symbol.upper())

        if not match:
            raise ValueError(f"Invalid option symbol format: {symbol}")

        base_symbol, day, month_str, year, strike_str, opt_type = match.groups()

        if month_str not in MONTH_MAP:
            raise ValueError(f"Invalid month in option symbol: {symbol}")

        expiry_hour, expiry_minute = get_exchange_expiry_time(exchange, custom_expiry_time)
        if custom_expiry_time:
            logger.info(f"Using custom expiry time: {custom_expiry_time}")

        # Deliberately naive, and treated as IST by every caller. Callers compare
        # this against naive timestamps of their own — historical candle times in
        # iv_chart_service, datetime.now() in vol_surface_service — and Python
        # refuses to compare naive against aware. calculate_time_to_expiry()
        # localizes it when it needs a real instant. Use get_expiry_datetime()
        # instead when you want a timezone-aware expiry.
        expiry = datetime(
            int("20" + year),
            MONTH_MAP[month_str],
            int(day),
            expiry_hour,
            expiry_minute,
        )

        # Convert strike to proper format
        # Strike must be in same units as futures price for Black-76
        strike = float(strike_str)

        logger.info(
            f"Parsed symbol {symbol}: base={base_symbol}, expiry={expiry}, strike={strike}, type={opt_type}"
        )

        return base_symbol, expiry, strike, opt_type.upper()

    except Exception as e:
        logger.exception(f"Error parsing option symbol {symbol}: {e}")
        raise ValueError(f"Failed to parse option symbol {symbol}: {str(e)}") from e


def get_underlying_exchange(base_symbol: str, options_exchange: str) -> str:
    """
    Determine the underlying exchange based on symbol and options exchange

    Returns:
        Exchange code for fetching underlying price
    """
    # NSE Index options
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"

    # BSE Index options
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"

    # Currency options
    if base_symbol in CURRENCY_SYMBOLS or options_exchange == "CDS":
        return "CDS"

    # Commodity options
    if base_symbol in COMMODITY_SYMBOLS or options_exchange == "MCX":
        return "MCX"

    # Crypto options — underlying is on the same exchange
    if options_exchange.upper() in CRYPTO_EXCHANGES:
        return options_exchange.upper()

    # Default to NSE for equity options
    return "NSE"


def _resolve_forward_price(
    base_symbol: str,
    options_exchange: str,
    underlying_exchange: str,
    expiry: datetime,
    api_key: str | None,
    synth_cache: dict | None = None,
) -> float | None:
    """
    Black-76 forward for an option's Greeks: the per-expiry SYNTHETIC FUTURE
    (ATM_strike + ATM_CE - ATM_PE, put-call parity) for every F&O underlying and
    expiry — index, stocks, MCX, CDS. Returns None to mean "fall back to spot"
    (e.g. the synthetic cannot be computed because ATM CE/PE quotes are missing).

    Single source of truth for the forward rule. Cached per
    (underlying, underlying_exchange, expiry) via synth_cache.
    """
    if synth_cache is None:
        synth_cache = {}
    expiry_code = expiry.strftime("%d%b%y").upper()  # DDMMMYY, e.g. 26JUN25
    key = (base_symbol, underlying_exchange, expiry_code)
    if key in synth_cache:
        return synth_cache[key]

    price = None
    try:
        from services.synthetic_future_service import calculate_synthetic_future

        ok, resp, _ = calculate_synthetic_future(
            base_symbol, underlying_exchange, expiry_code, api_key
        )
        if ok:
            price = resp.get("synthetic_future_price")
    except Exception as e:
        logger.warning(f"Synthetic future calc failed for {base_symbol} {expiry_code}: {e}")
    synth_cache[key] = price
    return price


def calculate_time_to_expiry(expiry: datetime) -> tuple[float, float]:
    """
    Calculate time to expiry in years (for the Black-76 model).

    The math library (opengreeks) expects time to expiry in YEARS.
    Also returns days for display purposes.

    Returns:
        Tuple of (time_in_years, time_in_days)
    """
    if expiry.tzinfo is None:
        expiry_for_calc = expiry.replace(tzinfo=INDIA_TZ)
        current_time = datetime.now(INDIA_TZ)
    else:
        expiry_for_calc = expiry
        current_time = datetime.now(expiry.tzinfo)

    if expiry_for_calc < current_time:
        logger.warning(f"Option has already expired: {expiry_for_calc}")
        return 0.0, 0.0

    # Calculate time to expiry
    time_delta = expiry_for_calc - current_time
    days_to_expiry = time_delta.total_seconds() / (60 * 60 * 24)
    years_to_expiry = days_to_expiry / 365.0

    # Ensure minimum value to avoid numerical issues
    if years_to_expiry < 0.0001:  # Less than ~1 hour
        years_to_expiry = 0.0001
        days_to_expiry = years_to_expiry * 365.0
        logger.info("Very close to expiry - using minimum 0.0001 years")

    logger.info(f"Time to expiry: {days_to_expiry:.4f} days ({years_to_expiry:.6f} years)")

    return years_to_expiry, days_to_expiry


def _expired_option_greeks_response(
    option_symbol: str,
    exchange: str,
    base_symbol: str,
    expiry: datetime,
    strike: float,
    opt_type: str,
    spot_price: float,
    option_price: float,
    interest_rate: float | None,
) -> dict[str, Any]:
    """Return a stable batch response for expired option legs."""
    if opt_type == "CE":
        intrinsic_value = max(spot_price - strike, 0)
    else:
        intrinsic_value = max(strike - spot_price, 0)

    return {
        "status": "success",
        "symbol": option_symbol,
        "exchange": exchange,
        "underlying": base_symbol,
        "strike": round(strike, 2),
        "option_type": opt_type,
        "expiry_date": expiry.strftime("%d-%b-%Y"),
        "days_to_expiry": 0,
        "spot_price": round(spot_price, 2),
        "option_price": round(option_price, 2),
        "intrinsic_value": round(intrinsic_value, 2),
        "time_value": round(max(option_price - intrinsic_value, 0), 2),
        "interest_rate": round(interest_rate or 0, 2),
        "implied_volatility": 0,
        "greeks": {
            "delta": 0,
            "gamma": 0,
            "theta": 0,
            "vega": 0,
            "rho": 0,
        },
        "note": "Option has expired - Greeks are no longer applicable",
    }


def _is_expired_option_response(response: dict[str, Any]) -> bool:
    message = str(response.get("message", "")).lower()
    return "option has expired" in message


def calculate_chain_greeks(
    strikes: list[float],
    ce_prices: list[float | None],
    pe_prices: list[float | None],
    forward_price: float,
    time_to_expiry_years: float,
    interest_rate: float | None = None,
) -> tuple[list[dict[str, float] | None], list[dict[str, float] | None]]:
    """
    Compute IV and Greeks for an entire option chain in one vectorized pass.

    Uses the opengreeks Black-76 ``*_array`` batch functions, which solve the
    whole strike ladder inside a single Rust call rather than one Python call
    per leg. A 40-strike chain (80 legs) costs roughly 70 microseconds, which is
    cheap enough to attach to every option-chain response.

    Legs with no time value, and legs whose IV does not converge, fall back to
    theoretical Greeks (IV 0, delta +/-1, everything else 0) so the numbers
    agree with calculate_greeks().

    Args:
        strikes: Strike ladder
        ce_prices: Call prices aligned to strikes; 0 or None where unavailable
        pe_prices: Put prices aligned to strikes; 0 or None where unavailable
        forward_price: Underlying forward or futures price
        time_to_expiry_years: Time to expiry in years
        interest_rate: Risk-free rate as an annualized percentage

    Returns:
        Tuple of (ce_greeks, pe_greeks). Each is aligned to strikes and holds a
        dict per leg, or None where Greeks are not computable at all.
    """
    count = len(strikes)
    if count == 0:
        return [], []

    empty: list[dict[str, float] | None] = [None] * count

    try:
        import numpy as np
        from opengreeks import black76
    except ImportError:
        logger.error("opengreeks not installed; option chain Greeks unavailable")
        return list(empty), list(empty)

    if forward_price <= 0 or time_to_expiry_years <= 0:
        logger.warning(
            f"Cannot compute chain Greeks: forward={forward_price}, t={time_to_expiry_years}"
        )
        return list(empty), list(empty)

    rate_decimal = (interest_rate or 0) / 100.0
    strike_arr = np.asarray(strikes, dtype=float)
    forward_arr = np.full(count, float(forward_price))
    tenor_arr = np.full(count, float(time_to_expiry_years))

    def _side(prices: list[float | None], flag: str) -> list[dict[str, float] | None]:
        price_arr = np.asarray([float(p) if p else 0.0 for p in prices], dtype=float)

        intrinsic = (
            np.maximum(forward_arr - strike_arr, 0.0)
            if flag == "c"
            else np.maximum(strike_arr - forward_arr, 0.0)
        )
        time_value = price_arr - intrinsic

        priced = (price_arr > 0) & (strike_arr > 0)
        # Same rule as calculate_greeks(): with no time value there is nothing to invert.
        no_time_value = priced & ((time_value <= 0) | ((intrinsic > 0) & (time_value < 0.01)))
        solvable = priced & ~no_time_value

        sigma = np.full(count, np.nan)
        solvable_idx = np.flatnonzero(solvable)
        if solvable_idx.size:
            try:
                sigma[solvable_idx] = black76.implied_volatility_array(
                    price_arr[solvable_idx],
                    forward_arr[solvable_idx],
                    strike_arr[solvable_idx],
                    rate_decimal,
                    tenor_arr[solvable_idx],
                    flag,
                )
            except Exception:
                # A whole-array failure is unexpected; per-leg misses come back as NaN.
                logger.exception("Vectorized IV solve failed for the chain")

        # Non-convergent legs come back NaN and join the theoretical bucket.
        converged = solvable & np.isfinite(sigma) & (sigma > 0)
        theoretical = priced & ~converged

        delta = np.zeros(count)
        gamma = np.zeros(count)
        theta = np.zeros(count)
        vega = np.zeros(count)

        converged_idx = np.flatnonzero(converged)
        if converged_idx.size:
            args = (
                flag,
                forward_arr[converged_idx],
                strike_arr[converged_idx],
                tenor_arr[converged_idx],
                rate_decimal,
                sigma[converged_idx],
            )
            # opengreeks already returns trader units: theta per day, vega per 1% vol.
            delta[converged_idx] = black76.delta_array(*args)
            gamma[converged_idx] = black76.gamma_array(*args)
            theta[converged_idx] = black76.theta_array(*args)
            vega[converged_idx] = black76.vega_array(*args)

        # Only an in-the-money leg collapses to +/-1 delta. An out-of-the-money
        # leg whose IV will not converge is worth ~0 and has ~0 delta, so keying
        # the fallback off the flag alone would invert its sign.
        signed_delta = 1.0 if flag == "c" else -1.0
        fallback_delta = np.where(intrinsic > 0, signed_delta, 0.0)

        out: list[dict[str, float] | None] = [None] * count

        for i in range(count):
            if converged[i]:
                out[i] = {
                    "iv": round(float(sigma[i]) * 100.0, 2),
                    "delta": round(float(delta[i]), 4),
                    "gamma": round(float(gamma[i]), 6),
                    "theta": round(float(theta[i]), 4),
                    "vega": round(float(vega[i]), 4),
                }
            elif theoretical[i]:
                out[i] = {
                    "iv": 0,
                    "delta": float(fallback_delta[i]),
                    "gamma": 0,
                    "theta": 0,
                    "vega": 0,
                }

        return out

    return _side(ce_prices, "c"), _side(pe_prices, "p")


def calculate_greeks(
    option_symbol: str,
    exchange: str,
    spot_price: float,
    option_price: float,
    interest_rate: float = None,
    expiry_time: str = None,
    api_key: str = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate Option Greeks using Black-76 model (opengreeks)

    Black-76 is the appropriate model for options on futures/forwards,
    which includes Indian F&O markets (NFO, BFO, MCX, CDS).

    Args:
        option_symbol: Option symbol (e.g., NIFTY28NOV2424000CE)
        exchange: Exchange code (NFO, BFO, CDS, MCX)
        spot_price: Underlying futures/forward price
        option_price: Current option price
        interest_rate: Risk-free interest rate (annualized %)
        expiry_time: Optional custom expiry time in "HH:MM" format
        api_key: API key for logging/tracking

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    try:
        # opengreeks is lazy-loaded to keep startup snappy (Rust core, NumPy-only deps).
        try:
            from opengreeks import black76

            black_delta = black76.delta
            black_gamma = black76.gamma
            black_iv = black76.implied_volatility
            black_rho = black76.rho
            black_theta = black76.theta
            black_vega = black76.vega
        except ImportError:
            logger.error("opengreeks library not installed.")
            return (
                False,
                {
                    "status": "error",
                    "message": "Option Greeks calculation requires opengreeks library. Install with: pip install opengreeks",
                },
                500,
            )

        # Parse option symbol with custom expiry time if provided
        base_symbol, expiry, strike, opt_type = parse_option_symbol(
            option_symbol, exchange, expiry_time
        )

        # Calculate time to expiry (returns years and days)
        time_to_expiry_years, time_to_expiry_days = calculate_time_to_expiry(expiry)

        if time_to_expiry_years <= 0:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Option has expired on {expiry.strftime('%d-%b-%Y')}",
                },
                400,
            )

        # Use default interest rate if not provided
        if interest_rate is None:
            interest_rate = DEFAULT_INTEREST_RATES.get(exchange, 0)

        # Convert interest rate from percentage to decimal
        # opengreeks expects decimal (0.065 for 6.5%)
        interest_rate_decimal = interest_rate / 100.0

        # Validate inputs
        if spot_price <= 0 or option_price <= 0:
            return (
                False,
                {"status": "error", "message": "Spot price and option price must be positive"},
                400,
            )

        if strike <= 0:
            return False, {"status": "error", "message": "Strike price must be positive"}, 400

        # Set option flag for opengreeks ('c' for call, 'p' for put)
        flag = "c" if opt_type == "CE" else "p"

        # Calculate intrinsic value to validate option price
        if opt_type == "CE":
            intrinsic_value = max(spot_price - strike, 0)
        else:  # PE
            intrinsic_value = max(strike - spot_price, 0)

        # Check if option price is at or below intrinsic value (deep ITM with no time value)
        # In this case, return theoretical deep ITM Greeks instead of error (like Opstra does)
        time_value = option_price - intrinsic_value
        if time_value <= 0 or (intrinsic_value > 0 and time_value < 0.01):
            # Deep ITM option with no/negligible time value
            # Return theoretical Greeks: IV=0, Delta=+/-1, Gamma=0, Theta=0, Vega=0
            logger.info("Deep ITM option with no time value - returning theoretical Greeks")

            response = {
                "status": "success",
                "symbol": option_symbol,
                "exchange": exchange,
                "underlying": base_symbol,
                "strike": round(strike, 2),
                "option_type": opt_type,
                "expiry_date": expiry.strftime("%d-%b-%Y"),
                "days_to_expiry": round(time_to_expiry_days, 4),
                "spot_price": round(spot_price, 2),
                "option_price": round(option_price, 2),
                "intrinsic_value": round(intrinsic_value, 2),
                "time_value": round(max(time_value, 0), 2),
                "interest_rate": round(interest_rate, 2),
                "implied_volatility": 0,  # No IV for deep ITM
                "greeks": {
                    "delta": 1.0 if opt_type == "CE" else -1.0,  # Deep ITM delta
                    "gamma": 0,
                    "theta": 0,
                    "vega": 0,
                    "rho": 0,
                },
                "note": "Deep ITM option with no time value - theoretical Greeks returned",
            }
            return True, response, 200

        # Calculate Implied Volatility using Black-76 model
        try:
            # black_iv(price, F, K, r, t, flag)
            # Returns IV as decimal (e.g., 0.15 for 15%)
            implied_volatility_decimal = black_iv(
                option_price, spot_price, strike, interest_rate_decimal, time_to_expiry_years, flag
            )
            # Convert to percentage for display
            implied_volatility = implied_volatility_decimal * 100.0

        except Exception as e:
            logger.exception(f"Error calculating IV: {e}")
            error_msg = str(e)
            # If IV calculation fails due to numerical issues, return theoretical deep ITM Greeks
            if (
                "intrinsic" in error_msg.lower()
                or "below" in error_msg.lower()
                or "convergence" in error_msg.lower()
            ):
                logger.info(
                    "IV calculation failed - returning theoretical Greeks for deep ITM option"
                )
                response = {
                    "status": "success",
                    "symbol": option_symbol,
                    "exchange": exchange,
                    "underlying": base_symbol,
                    "strike": round(strike, 2),
                    "option_type": opt_type,
                    "expiry_date": expiry.strftime("%d-%b-%Y"),
                    "days_to_expiry": round(time_to_expiry_days, 4),
                    "spot_price": round(spot_price, 2),
                    "option_price": round(option_price, 2),
                    "intrinsic_value": round(intrinsic_value, 2),
                    "time_value": round(max(time_value, 0), 2),
                    "interest_rate": round(interest_rate, 2),
                    "implied_volatility": 0,  # No IV calculable
                    "greeks": {
                        "delta": 1.0 if opt_type == "CE" else -1.0,
                        "gamma": 0,
                        "theta": 0,
                        "vega": 0,
                        "rho": 0,
                    },
                    "note": "IV calculation not possible - theoretical deep ITM Greeks returned",
                }
                return True, response, 200
            return (
                False,
                {
                    "status": "error",
                    "message": f"Failed to calculate Implied Volatility: {error_msg}",
                },
                500,
            )

        # Calculate Greeks using Black-76 model
        try:
            # All Greek functions: func(flag, F, K, t, r, sigma)
            # sigma is IV as decimal
            delta = black_delta(
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            gamma = black_gamma(
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            theta = black_theta(
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            vega = black_vega(
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            rho = black_rho(
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )

            # Note: opengreeks Black-76 returns Greeks in trader-friendly units:
            # - theta: already daily theta (no conversion needed)
            # - vega: already per 1% vol change (no conversion needed)

        except Exception as e:
            logger.exception(f"Error calculating Greeks: {e}")
            return (
                False,
                {"status": "error", "message": f"Failed to calculate Greeks: {str(e)}"},
                500,
            )

        # Build response
        response = {
            "status": "success",
            "symbol": option_symbol,
            "exchange": exchange,
            "underlying": base_symbol,
            "strike": round(strike, 2),
            "option_type": opt_type,
            "expiry_date": expiry.strftime("%d-%b-%Y"),
            "days_to_expiry": round(time_to_expiry_days, 4),
            "spot_price": round(spot_price, 2),
            "option_price": round(option_price, 2),
            "interest_rate": round(interest_rate, 2),
            "implied_volatility": round(implied_volatility, 2),
            "greeks": {
                "delta": round(delta, 4),
                "gamma": round(gamma, 6),
                "theta": round(theta, 4),
                "vega": round(vega, 4),
                "rho": round(rho, 6),
            },
        }

        logger.info(f"Greeks calculated successfully for {option_symbol} using Black-76 model")
        return True, response, 200

    except ValueError as e:
        logger.error(f"Validation error in calculate_greeks: {e}")
        return False, {"status": "error", "message": str(e)}, 400

    except Exception as e:
        logger.exception(f"Unexpected error in calculate_greeks: {e}")
        return (
            False,
            {"status": "error", "message": f"Failed to calculate option Greeks: {str(e)}"},
            500,
        )


def get_option_greeks(
    option_symbol: str,
    exchange: str,
    interest_rate: float | None = None,
    forward_price: float | None = None,
    underlying_symbol: str | None = None,
    underlying_exchange: str | None = None,
    expiry_time: str | None = None,
    api_key: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get option Greeks by fetching current market prices and calculating

    Args:
        option_symbol: Option symbol
        exchange: Exchange code (NFO, BFO, CDS, MCX)
        interest_rate: Optional interest rate (default from exchange mapping)
        forward_price: Optional custom forward/synthetic futures price. If provided, skips underlying fetch.
        underlying_symbol: Optional underlying symbol to use for spot price (e.g., NIFTY or NIFTY28NOV24FUT)
        underlying_exchange: Optional underlying exchange (e.g., NSE_INDEX or NFO)
        expiry_time: Optional custom expiry time in "HH:MM" format (e.g., "19:00" for MCX)
        api_key: API key for authentication

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    try:
        # Import here to avoid circular dependency
        from services.quotes_service import get_quotes

        # Parse symbol to get underlying (if not provided)
        base_symbol, expiry, strike, opt_type = parse_option_symbol(
            option_symbol, exchange, expiry_time
        )

        # Determine the forward/futures price to use
        if forward_price:
            # User provided custom forward price (e.g., synthetic future)
            spot_price = forward_price
            logger.info(f"Using custom forward price: {forward_price}")
        else:
            # Fetch underlying price from broker
            # Use provided underlying symbol/exchange or derive from option symbol
            if underlying_symbol:
                spot_symbol = underlying_symbol
                logger.info(f"Using custom underlying symbol: {underlying_symbol}")
            else:
                spot_symbol = base_symbol

            if underlying_exchange:
                spot_exchange = underlying_exchange
                logger.info(f"Using custom underlying exchange: {underlying_exchange}")
            else:
                spot_exchange = get_underlying_exchange(base_symbol, exchange)

            # Black-76 forward = per-expiry synthetic future for all F&O; spot
            # fallback. Skipped when the caller supplied a custom underlying
            # (e.g. a FUT symbol).
            resolved_forward = None
            if not underlying_symbol or underlying_symbol == base_symbol:
                resolved_forward = _resolve_forward_price(
                    base_symbol, exchange, spot_exchange, expiry, api_key
                )

            if resolved_forward:
                spot_price = resolved_forward
                logger.info(
                    f"Using forward {resolved_forward} for {option_symbol}"
                )
                success = True
            else:
                # Fetch underlying spot price
                logger.info(f"Fetching spot price for {spot_symbol} from {spot_exchange}")
                success, spot_response, status_code = get_quotes(spot_symbol, spot_exchange, api_key)

                if not success:
                    return (
                        False,
                        {
                            "status": "error",
                            "message": f"Failed to fetch underlying price: {spot_response.get('message', 'Unknown error')}",
                        },
                        status_code,
                    )

                spot_price = spot_response.get("data", {}).get("ltp")
            if not spot_price:
                return False, {"status": "error", "message": "Underlying LTP not available"}, 404

        # Fetch option price
        logger.info(f"Fetching option price for {option_symbol} from {exchange}")
        success, option_response, status_code = get_quotes(option_symbol, exchange, api_key)

        if not success:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Failed to fetch option price: {option_response.get('message', 'Unknown error')}",
                },
                status_code,
            )

        option_price = option_response.get("data", {}).get("ltp")
        if not option_price:
            return False, {"status": "error", "message": "Option LTP not available"}, 404

        # Calculate Greeks
        return calculate_greeks(
            option_symbol=option_symbol,
            exchange=exchange,
            spot_price=spot_price,
            option_price=option_price,
            interest_rate=interest_rate,
            expiry_time=expiry_time,
            api_key=api_key,
        )

    except Exception as e:
        logger.exception(f"Error in get_option_greeks: {e}")
        return False, {"status": "error", "message": f"Failed to get option Greeks: {str(e)}"}, 500


def get_multi_option_greeks(
    symbols: list,
    interest_rate: float | None = None,
    expiry_time: str | None = None,
    api_key: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get option Greeks for multiple symbols in a single call.
    Optimized to fetch spot prices once per underlying and batch option prices
    via get_multiquotes(), minimizing broker API calls.

    Args:
        symbols: List of dicts with 'symbol', 'exchange', optional 'underlying_symbol', 'underlying_exchange'
        interest_rate: Optional common interest rate for all symbols
        expiry_time: Optional common expiry time for all symbols
        api_key: API key for authentication

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    from services.quotes_service import get_multiquotes, get_quotes

    # Early return for empty symbols list
    if not symbols:
        return (
            True,
            {"status": "success", "data": [], "summary": {"total": 0, "success": 0, "failed": 0}},
            200,
        )

    results = [None] * len(symbols)
    success_count = 0
    failed_count = 0

    # Step 1: Parse all symbols and group by underlying for spot price fetch
    parsed_symbols = {}  # leg index -> (base_symbol, expiry, strike, opt_type)
    spot_keys = {}  # (spot_symbol, spot_exchange) -> spot_price
    symbol_to_spot_key = {}  # leg index -> (spot_symbol, spot_exchange)
    symbol_forward = {}  # leg index -> Black-76 forward (synthetic future)
    synth_cache = {}  # (base, underlying_exchange, expiry_code) -> synthetic future

    for idx, sym_req in enumerate(symbols):
        symbol = sym_req.get("symbol")
        exchange = sym_req.get("exchange")
        try:
            batch_key = idx
            base_symbol, expiry, strike, opt_type = parse_option_symbol(symbol, exchange, expiry_time)
            parsed_symbols[batch_key] = (base_symbol, expiry, strike, opt_type)

            # Determine spot symbol/exchange for this option (also the fallback
            # if the synthetic future cannot be computed for an index weekly)
            passed_underlying = sym_req.get("underlying_symbol")
            spot_symbol = passed_underlying or base_symbol
            spot_exchange = sym_req.get("underlying_exchange") or get_underlying_exchange(base_symbol, exchange)
            spot_key = (spot_symbol, spot_exchange)
            spot_keys[spot_key] = None  # will be filled with price
            symbol_to_spot_key[batch_key] = spot_key

            # Black-76 forward = per-expiry synthetic future for all F&O; spot
            # fallback. Skipped if the caller passed a custom underlying
            # (e.g. an explicit FUT symbol).
            if not passed_underlying or passed_underlying == base_symbol:
                forward = _resolve_forward_price(
                    base_symbol, exchange, spot_exchange, expiry, api_key, synth_cache
                )
                if forward:
                    symbol_forward[batch_key] = forward
        except Exception as e:
            logger.warning(f"Failed to parse symbol {symbol}: {e}")
            failed_count += 1
            results[idx] = {
                "status": "error",
                "symbol": symbol,
                "exchange": exchange,
                "message": f"Failed to parse option symbol: {str(e)}",
            }

    # Step 2: Fetch spot prices — one API call per unique underlying
    for spot_key in spot_keys:
        spot_symbol, spot_exchange = spot_key
        try:
            logger.info(f"Fetching spot price for {spot_symbol} from {spot_exchange}")
            success, spot_response, status_code = get_quotes(spot_symbol, spot_exchange, api_key)
            if success:
                spot_price = spot_response.get("data", {}).get("ltp")
                if spot_price:
                    spot_keys[spot_key] = spot_price
                else:
                    logger.warning(f"No LTP in spot response for {spot_symbol}")
            else:
                logger.warning(f"Failed to fetch spot for {spot_symbol}: {spot_response.get('message')}")
        except Exception as e:
            logger.warning(f"Error fetching spot for {spot_symbol}: {e}")

    # Step 3: Batch fetch all option prices via get_multiquotes()
    option_symbols_to_fetch = []
    seen_quotes = set()
    for idx, sym_req in enumerate(symbols):
        symbol = sym_req.get("symbol")
        exchange = sym_req.get("exchange")
        if idx in parsed_symbols and (symbol, exchange) not in seen_quotes:
            seen_quotes.add((symbol, exchange))
            option_symbols_to_fetch.append({
                "symbol": symbol,
                "exchange": exchange,
            })

    # Fallback exchange per requested symbol. Every broker adapter echoes the
    # requested exchange today, but a result that omitted it would key every
    # price under (symbol, None) and fail the whole batch rather than one leg.
    # A symbol requested on two exchanges maps to None: guessing either one
    # would reintroduce the collision, so only those legs go unpriced.
    requested_exchange = {}
    for item in option_symbols_to_fetch:
        sym_name = item["symbol"]
        requested_exchange[sym_name] = None if sym_name in requested_exchange else item["exchange"]

    option_prices = {}  # (symbol, exchange) -> ltp
    if option_symbols_to_fetch:
        logger.info(f"Batch fetching {len(option_symbols_to_fetch)} option prices via multiquotes")
        try:
            mq_success, mq_response, mq_status = get_multiquotes(
                symbols=option_symbols_to_fetch, api_key=api_key
            )
            if mq_success and "results" in mq_response:
                for result in mq_response["results"]:
                    sym = result.get("symbol")
                    exch = result.get("exchange") or requested_exchange.get(sym)
                    if sym and "data" in result:
                        ltp = result["data"].get("ltp")
                        if ltp:
                            option_prices[(sym, exch)] = ltp
        except Exception as e:
            logger.warning(f"Multiquotes fetch failed: {e}")

    # Step 4: Calculate Greeks for each symbol using fetched prices
    for idx, sym_req in enumerate(symbols):
        symbol = sym_req.get("symbol")
        exchange = sym_req.get("exchange")
        batch_key = idx

        # Skip if already failed during parsing
        if batch_key not in parsed_symbols:
            continue

        # Forward price: synthetic future for index weeklies, else spot.
        # Falls back to spot if the synthetic future could not be computed.
        spot_key = symbol_to_spot_key.get(batch_key)
        spot_price = symbol_forward.get(batch_key) or (
            spot_keys.get(spot_key) if spot_key else None
        )
        if not spot_price:
            failed_count += 1
            results[idx] = {
                "status": "error",
                "symbol": symbol,
                "exchange": exchange,
                "message": f"Failed to fetch underlying price for {spot_key[0] if spot_key else 'unknown'}",
            }
            continue

        # Get option price
        option_price = option_prices.get((symbol, exchange))
        if not option_price:
            failed_count += 1
            results[idx] = {
                "status": "error",
                "symbol": symbol,
                "exchange": exchange,
                "message": "Option LTP not available",
            }
            continue

        # Calculate Greeks (pure math, no API calls)
        try:
            calc_success, calc_response, calc_status = calculate_greeks(
                option_symbol=symbol,
                exchange=exchange,
                spot_price=spot_price,
                option_price=option_price,
                interest_rate=interest_rate,
                expiry_time=expiry_time,
                api_key=api_key,
            )
            if calc_success:
                success_count += 1
            else:
                if _is_expired_option_response(calc_response):
                    base_symbol, expiry, strike, opt_type = parsed_symbols[batch_key]
                    calc_response = _expired_option_greeks_response(
                        option_symbol=symbol,
                        exchange=exchange,
                        base_symbol=base_symbol,
                        expiry=expiry,
                        strike=strike,
                        opt_type=opt_type,
                        spot_price=spot_price,
                        option_price=option_price,
                        interest_rate=interest_rate,
                    )
                    success_count += 1
                else:
                    failed_count += 1
                    calc_response.setdefault("symbol", symbol)
                    calc_response.setdefault("exchange", exchange)
            results[idx] = calc_response
        except Exception as e:
            logger.exception(f"Error calculating Greeks for {symbol}: {e}")
            failed_count += 1
            results[idx] = {
                "status": "error",
                "symbol": symbol,
                "exchange": exchange,
                "message": str(e),
            }


    response = {
        "status": "success" if failed_count == 0 else "partial" if success_count > 0 else "error",
        "data": results,
        "summary": {"total": len(symbols), "success": success_count, "failed": failed_count},
    }
    if failed_count > 0:
        messages = []
        for result in results:
            if result.get("status") == "error" and result.get("message"):
                message = result["message"]
                if message not in messages:
                    messages.append(message)
        if messages:
            if response["status"] == "error":
                response["message"] = (
                    f"All option Greeks calculations failed: {'; '.join(messages[:3])}"
                )
            else:
                response["message"] = (
                    f"{failed_count} option Greeks calculation(s) failed: "
                    f"{'; '.join(messages[:3])}"
                )

    logger.info(f"Multi Greeks completed: {success_count}/{len(symbols)} successful")

    # Return False only when ALL operations fail (status='error')
    # Return True for 'success' or 'partial' (at least some succeeded)
    is_success = response["status"] != "error"
    return is_success, response, 200
