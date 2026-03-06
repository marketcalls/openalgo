"""
Option Greeks Service
Calculates option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility
for options across all supported exchanges (NFO, BFO, CDS, MCX)

Uses Black-76 model - appropriate for options on futures/forwards
which is the correct model for Indian F&O markets (NFO, BFO, MCX, CDS)

Primary implementation uses py_vollib. If py_vollib is unavailable or broken
(e.g. numba incompatibility on Python 3.13+), a pure-scipy fallback is used
automatically. The fallback implements identical Black-76 formulae using only
math + scipy.stats.norm + scipy.optimize.brentq — no numba/llvmlite needed.
"""

import math
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from scipy.optimize import brentq
from scipy.stats import norm

from utils.constants import CRYPTO_EXCHANGES
from utils.logging import get_logger

logger = get_logger(__name__)

# ── Try to load py_vollib at module level (once) ────────────────────────
# If it fails we fall back to the pure-scipy implementation below.
_USE_PYVOLLIB = False
_pv_iv = _pv_delta = _pv_gamma = _pv_theta = _pv_vega = _pv_rho = None  # type: ignore
try:
    from py_vollib.black.greeks.analytical import delta as _pv_delta
    from py_vollib.black.greeks.analytical import gamma as _pv_gamma
    from py_vollib.black.greeks.analytical import rho as _pv_rho
    from py_vollib.black.greeks.analytical import theta as _pv_theta
    from py_vollib.black.greeks.analytical import vega as _pv_vega
    from py_vollib.black.implied_volatility import (
        implied_volatility as _pv_iv,
    )

    # Smoke-test: numba JIT may explode on first real call even though the
    # import itself succeeds.  Run a trivial calculation to flush that out.
    _pv_iv(1.0, 100.0, 100.0, 0.0, 0.25, "c")
    _USE_PYVOLLIB = True
    logger.info("py_vollib loaded successfully — using numba-accelerated Black-76")
except Exception as exc:
    logger.warning(
        "py_vollib unavailable or broken (%s). Using pure-scipy Black-76 fallback.", exc
    )


# ── Pure-scipy Black-76 implementation ──────────────────────────────────
def _black76_price(F: float, K: float, T: float, r: float, sigma: float, flag: str) -> float:
    """Black-76 option price.  flag = 'c' or 'p'."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    df = math.exp(-r * T)
    if flag == "c":
        return float(df * (F * norm.cdf(d1) - K * norm.cdf(d2)))
    return float(df * (K * norm.cdf(-d2) - F * norm.cdf(-d1)))


def _black76_iv(
    price: float, F: float, K: float, r: float, T: float, flag: str
) -> float:
    """Implied volatility via Brent's method.  Same arg order as py_vollib.

    Raises ValueError whose message lets the caller distinguish:
      - 'below intrinsic'  → price is below theoretical minimum (deep ITM)
      - 'exceeds theoretical maximum' → price above max Black-76 value (bad data)
      - 'convergence' → generic iteration / other failure
    """
    def _obj(sigma: float) -> float:
        return _black76_price(F, K, T, r, sigma, flag) - price

    try:
        # brentq returns scalar root when full_output=False (default)
        root: float = brentq(_obj, 1e-6, 50.0, xtol=1e-12, maxiter=200)  # type: ignore
        return float(root)
    except (ValueError, RuntimeError) as e:
        # Diagnose *why* brentq failed so the caller can react appropriately.
        try:
            low_residual = _obj(1e-6)
            high_residual = _obj(50.0)
        except Exception:
            # Pricing itself blew up (e.g. log of negative) — generic error
            raise ValueError(f"IV convergence failed: {e}") from e

        if low_residual > 0 and high_residual > 0:
            # Theoretical price > market price at all vols → price below intrinsic
            raise ValueError(
                "Option price is below intrinsic value — IV not calculable"
            ) from e
        if low_residual < 0 and high_residual < 0:
            # Theoretical price < market price at all vols → impossibly high price
            raise ValueError(
                "Option price exceeds theoretical maximum — IV not calculable"
            ) from e
        # Mixed signs but brentq still failed (maxiter, tolerance, etc.)
        raise ValueError(f"IV convergence failed: {e}") from e


def _d1d2(F: float, K: float, T: float, sigma: float):
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return d1, d2, sqrt_T


def _black76_delta(flag: str, F: float, K: float, T: float, r: float, sigma: float) -> float:
    d1, _, _ = _d1d2(F, K, T, sigma)
    df = math.exp(-r * T)
    if flag == "c":
        return float(df * norm.cdf(d1))
    return float(-df * norm.cdf(-d1))


def _black76_gamma(flag: str, F: float, K: float, T: float, r: float, sigma: float) -> float:
    d1, _, sqrt_T = _d1d2(F, K, T, sigma)
    df = math.exp(-r * T)
    return float(df * norm.pdf(d1) / (F * sigma * sqrt_T))


def _black76_theta(flag: str, F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Daily theta (matches py_vollib: annualized theta / 365)."""
    d1, d2, sqrt_T = _d1d2(F, K, T, sigma)
    df = math.exp(-r * T)
    first_term = float(-(F * df * norm.pdf(d1) * sigma) / (2.0 * sqrt_T))
    if flag == "c":
        return float((first_term - r * df * (F * norm.cdf(d1) - K * norm.cdf(d2))) / 365.0)
    return float((first_term + r * df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))) / 365.0)


def _black76_vega(flag: str, F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Vega per 1% IV change (matches py_vollib: raw vega * 0.01)."""
    d1, _, sqrt_T = _d1d2(F, K, T, sigma)
    df = math.exp(-r * T)
    return float(F * df * norm.pdf(d1) * sqrt_T * 0.01)


def _black76_rho(flag: str, F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Rho per 1% rate change (matches py_vollib: raw rho * 0.01)."""
    d1, d2, _ = _d1d2(F, K, T, sigma)
    df = math.exp(-r * T)
    if flag == "c":
        return float(-T * df * (F * norm.cdf(d1) - K * norm.cdf(d2)) * 0.01)
    return float(-T * df * (K * norm.cdf(-d2) - F * norm.cdf(-d1)) * 0.01)

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


def check_pyvollib_availability():
    """Check if Black-76 engine is available (py_vollib or scipy fallback)"""
    # Pure-scipy fallback is always available, so this always succeeds.
    return True, None, None


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
        expiry: Expiry datetime
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

        # Month mapping
        month_map = {
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

        # Determine expiry time
        if custom_expiry_time:
            # Parse custom expiry time (format: "HH:MM")
            try:
                time_parts = custom_expiry_time.split(":")
                if len(time_parts) != 2:
                    raise ValueError(
                        f"Invalid expiry_time format: {custom_expiry_time}. Use HH:MM format (e.g., '15:30', '19:00')"
                    )
                expiry_hour = int(time_parts[0])
                expiry_minute = int(time_parts[1])
                if not (0 <= expiry_hour <= 23) or not (0 <= expiry_minute <= 59):
                    raise ValueError(
                        f"Invalid expiry_time values: {custom_expiry_time}. Hour must be 0-23, minute must be 0-59"
                    )
                logger.info(f"Using custom expiry time: {custom_expiry_time}")
            except Exception as e:
                raise ValueError(f"Failed to parse expiry_time '{custom_expiry_time}': {str(e)}")
        else:
            # Use default expiry time based on exchange:
            # NFO/BFO: 15:30 (3:30 PM)
            # CDS: 12:30 (12:30 PM)
            # MCX: 23:30 (11:30 PM) - Default, but varies by commodity
            if exchange == "MCX":
                expiry_hour = 23
                expiry_minute = 30
            elif exchange == "CDS":
                expiry_hour = 12
                expiry_minute = 30
            else:  # NFO, BFO
                expiry_hour = 15
                expiry_minute = 30

        expiry = datetime(
            int("20" + year), month_map[month_str], int(day), expiry_hour, expiry_minute
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
        raise ValueError(f"Failed to parse option symbol {symbol}: {str(e)}")


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


def calculate_time_to_expiry(expiry: datetime) -> tuple[float, float]:
    """
    Calculate time to expiry in years (for py_vollib Black-76 model)

    py_vollib expects time to expiry in YEARS.
    Also returns days for display purposes.

    Returns:
        Tuple of (time_in_years, time_in_days)
    """
    current_time = datetime.now()

    if expiry < current_time:
        logger.warning(f"Option has already expired: {expiry}")
        return 0.0, 0.0

    # Calculate time to expiry
    time_delta = expiry - current_time
    days_to_expiry = time_delta.total_seconds() / (60 * 60 * 24)
    years_to_expiry = days_to_expiry / 365.0

    # Ensure minimum value to avoid numerical issues
    if years_to_expiry < 0.0001:  # Less than ~1 hour
        years_to_expiry = 0.0001
        days_to_expiry = years_to_expiry * 365.0
        logger.info("Very close to expiry - using minimum 0.0001 years")

    logger.info(f"Time to expiry: {days_to_expiry:.4f} days ({years_to_expiry:.6f} years)")

    return years_to_expiry, days_to_expiry


def calculate_greeks(
    option_symbol: str,
    exchange: str,
    spot_price: float,
    option_price: float,
    interest_rate: Optional[float] = None,
    expiry_time: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate Option Greeks using Black-76 model (py_vollib)

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
        # Select Black-76 engine: py_vollib (numba-accelerated) or scipy fallback
        if _USE_PYVOLLIB:
            # Type narrowing: when _USE_PYVOLLIB is True, all _pv_* are guaranteed loaded
            black_iv = _pv_iv  # type: ignore[assignment]
            black_delta = _pv_delta  # type: ignore[assignment]
            black_gamma = _pv_gamma  # type: ignore[assignment]
            black_theta = _pv_theta  # type: ignore[assignment]
            black_vega = _pv_vega  # type: ignore[assignment]
            black_rho = _pv_rho  # type: ignore[assignment]
        else:
            black_iv = _black76_iv
            black_delta = _black76_delta
            black_gamma = _black76_gamma
            black_theta = _black76_theta
            black_vega = _black76_vega
            black_rho = _black76_rho

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
        # py_vollib expects decimal (0.065 for 6.5%)
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

        # Set option flag for py_vollib ('c' for call, 'p' for put)
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
            implied_volatility_decimal = black_iv(  # type: ignore[misc]
                option_price, spot_price, strike, interest_rate_decimal, time_to_expiry_years, flag
            )
            # Convert to percentage for display
            implied_volatility = implied_volatility_decimal * 100.0

        except Exception as e:
            logger.exception(f"Error calculating IV: {e}")
            error_msg = str(e)
            # If IV calculation fails due to numerical issues, return theoretical deep ITM Greeks
            # Gracefully handle both py_vollib and scipy/brentq error patterns
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
            delta = black_delta(  # type: ignore[misc]
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            gamma = black_gamma(  # type: ignore[misc]
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            theta = black_theta(  # type: ignore[misc]
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            vega = black_vega(  # type: ignore[misc]
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )
            rho = black_rho(  # type: ignore[misc]
                flag,
                spot_price,
                strike,
                time_to_expiry_years,
                interest_rate_decimal,
                implied_volatility_decimal,
            )

            # Note: py_vollib Black model returns Greeks in trader-friendly units:
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

            # Fetch underlying price
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
    Uses concurrent execution for efficiency.

    Args:
        symbols: List of dicts with 'symbol', 'exchange', optional 'underlying_symbol', 'underlying_exchange'
        interest_rate: Optional common interest rate for all symbols
        expiry_time: Optional common expiry time for all symbols
        api_key: API key for authentication

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Early return for empty symbols list
    if not symbols:
        return (
            True,
            {"status": "success", "data": [], "summary": {"total": 0, "success": 0, "failed": 0}},
            200,
        )

    results = []
    success_count = 0
    failed_count = 0

    def fetch_single_greeks(symbol_request):
        """Fetch Greeks for a single symbol"""
        try:
            symbol = symbol_request.get("symbol")
            exchange = symbol_request.get("exchange")
            underlying_symbol = symbol_request.get("underlying_symbol")
            underlying_exchange = symbol_request.get("underlying_exchange")

            success, response, status_code = get_option_greeks(
                option_symbol=symbol,
                exchange=exchange,
                interest_rate=interest_rate,
                forward_price=None,  # Not supported in batch mode
                underlying_symbol=underlying_symbol,
                underlying_exchange=underlying_exchange,
                expiry_time=expiry_time,
                api_key=api_key,
            )

            return {
                "success": success,
                "response": response,
                "symbol": symbol,
                "exchange": exchange,
            }
        except Exception as e:
            logger.exception(f"Error fetching Greeks for {symbol_request.get('symbol')}: {e}")
            return {
                "success": False,
                "response": {
                    "status": "error",
                    "symbol": symbol_request.get("symbol"),
                    "exchange": symbol_request.get("exchange"),
                    "message": str(e),
                },
                "symbol": symbol_request.get("symbol"),
                "exchange": symbol_request.get("exchange"),
            }

    # Use ThreadPoolExecutor for parallel execution
    # Limit workers to avoid overwhelming the broker API
    max_workers = min(len(symbols), 10)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_symbol = {executor.submit(fetch_single_greeks, sym): sym for sym in symbols}

        # Collect results as they complete
        for future in as_completed(future_to_symbol):
            result = future.result()

            if result["success"]:
                success_count += 1
                results.append(result["response"])
            else:
                failed_count += 1
                results.append(result["response"])

    # Sort results to maintain original order
    symbol_order = {sym["symbol"]: idx for idx, sym in enumerate(symbols)}
    results.sort(key=lambda x: symbol_order.get(x.get("symbol"), 999))

    response = {
        "status": "success" if failed_count == 0 else "partial" if success_count > 0 else "error",
        "data": results,
        "summary": {"total": len(symbols), "success": success_count, "failed": failed_count},
    }

    logger.info(f"Multi Greeks completed: {success_count}/{len(symbols)} successful")

    # Return False only when ALL operations fail (status='error')
    # Return True for 'success' or 'partial' (at least some succeeded)
    is_success = response["status"] != "error"
    return is_success, response, 200
