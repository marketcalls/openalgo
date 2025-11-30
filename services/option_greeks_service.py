"""
Option Greeks Service
Calculates option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility
for options across all supported exchanges (NFO, BFO, CDS, MCX)

Uses Black-76 model (py_vollib) - appropriate for options on futures/forwards
which is the correct model for Indian F&O markets (NFO, BFO, MCX, CDS)
"""

import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from utils.logging import get_logger

# Import py_vollib for Black-76 calculations
try:
    from py_vollib.black.implied_volatility import implied_volatility as black_iv
    from py_vollib.black.greeks.analytical import delta as black_delta
    from py_vollib.black.greeks.analytical import gamma as black_gamma
    from py_vollib.black.greeks.analytical import theta as black_theta
    from py_vollib.black.greeks.analytical import vega as black_vega
    from py_vollib.black.greeks.analytical import rho as black_rho
    PYVOLLIB_AVAILABLE = True
except ImportError:
    PYVOLLIB_AVAILABLE = False

logger = get_logger(__name__)

# Exchange-specific symbol mappings
NSE_INDEX_SYMBOLS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "NIFTYNXT50", "NIFTYIT", "NIFTYPHARMA", "NIFTYBANK"
}

BSE_INDEX_SYMBOLS = {
    "SENSEX", "BANKEX", "SENSEX50"
}

CURRENCY_SYMBOLS = {
    "USDINR", "EURINR", "GBPINR", "JPYINR"
}

COMMODITY_SYMBOLS = {
    "GOLD", "GOLDM", "GOLDPETAL", "SILVER", "SILVERM", "SILVERMIC",
    "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "COPPER", "ZINC", "LEAD",
    "ALUMINIUM", "NICKEL", "COTTONCANDY", "MENTHAOIL"
}

# Default interest rates by exchange (annualized %)
# Set to 0 - users should explicitly define interest rate if needed
DEFAULT_INTEREST_RATES = {
    "NFO": 0,      # NSE F&O
    "BFO": 0,      # BSE F&O
    "CDS": 0,      # Currency derivatives
    "MCX": 0       # Commodities
}

def check_pyvollib_availability():
    """Check if py_vollib library is available"""
    if not PYVOLLIB_AVAILABLE:
        logger.error("py_vollib library not installed. Install with: pip install py_vollib")
        return False, {
            'status': 'error',
            'message': 'Option Greeks calculation requires py_vollib library. Install with: pip install py_vollib'
        }, 500
    return True, None, None


def parse_option_symbol(symbol: str, exchange: str, custom_expiry_time: Optional[str] = None) -> Tuple[str, datetime, float, str]:
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
        # Pattern: SYMBOL + DD + MMM + YY + STRIKE + CE/PE
        # Strike can have decimal point for currencies
        match = re.match(r"([A-Z]+)(\d{2})([A-Z]{3})(\d{2})([\d.]+)(CE|PE)", symbol.upper())

        if not match:
            raise ValueError(f"Invalid option symbol format: {symbol}")

        base_symbol, day, month_str, year, strike_str, opt_type = match.groups()

        # Month mapping
        month_map = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }

        # Determine expiry time
        if custom_expiry_time:
            # Parse custom expiry time (format: "HH:MM")
            try:
                time_parts = custom_expiry_time.split(':')
                if len(time_parts) != 2:
                    raise ValueError(f"Invalid expiry_time format: {custom_expiry_time}. Use HH:MM format (e.g., '15:30', '19:00')")
                expiry_hour = int(time_parts[0])
                expiry_minute = int(time_parts[1])
                if not (0 <= expiry_hour <= 23) or not (0 <= expiry_minute <= 59):
                    raise ValueError(f"Invalid expiry_time values: {custom_expiry_time}. Hour must be 0-23, minute must be 0-59")
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
            int('20' + year),
            month_map[month_str],
            int(day),
            expiry_hour,
            expiry_minute
        )

        # Convert strike to proper format
        # Strike must be in same units as futures price for Black-76
        strike = float(strike_str)

        logger.info(f"Parsed symbol {symbol}: base={base_symbol}, expiry={expiry}, strike={strike}, type={opt_type}")

        return base_symbol, expiry, strike, opt_type.upper()

    except Exception as e:
        logger.error(f"Error parsing option symbol {symbol}: {e}")
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

    # Default to NSE for equity options
    return "NSE"


def calculate_time_to_expiry(expiry: datetime) -> Tuple[float, float]:
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
        logger.info(f"Very close to expiry - using minimum 0.0001 years")

    logger.info(f"Time to expiry: {days_to_expiry:.4f} days ({years_to_expiry:.6f} years)")

    return years_to_expiry, days_to_expiry


def calculate_greeks(
    option_symbol: str,
    exchange: str,
    spot_price: float,
    option_price: float,
    interest_rate: float = None,
    expiry_time: str = None,
    api_key: str = None
) -> Tuple[bool, Dict[str, Any], int]:
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
        # Check if py_vollib is available
        available, error_response, status_code = check_pyvollib_availability()
        if not available:
            return False, error_response, status_code

        # Parse option symbol with custom expiry time if provided
        base_symbol, expiry, strike, opt_type = parse_option_symbol(option_symbol, exchange, expiry_time)

        # Calculate time to expiry (returns years and days)
        time_to_expiry_years, time_to_expiry_days = calculate_time_to_expiry(expiry)

        if time_to_expiry_years <= 0:
            return False, {
                'status': 'error',
                'message': f'Option has expired on {expiry.strftime("%d-%b-%Y")}'
            }, 400

        # Use default interest rate if not provided
        if interest_rate is None:
            interest_rate = DEFAULT_INTEREST_RATES.get(exchange, 0)

        # Convert interest rate from percentage to decimal
        # py_vollib expects decimal (0.065 for 6.5%)
        interest_rate_decimal = interest_rate / 100.0

        # Validate inputs
        if spot_price <= 0 or option_price <= 0:
            return False, {
                'status': 'error',
                'message': 'Spot price and option price must be positive'
            }, 400

        if strike <= 0:
            return False, {
                'status': 'error',
                'message': 'Strike price must be positive'
            }, 400

        # Set option flag for py_vollib ('c' for call, 'p' for put)
        flag = 'c' if opt_type == 'CE' else 'p'

        # Calculate Implied Volatility using Black-76 model
        try:
            # black_iv(price, F, K, r, t, flag)
            # Returns IV as decimal (e.g., 0.15 for 15%)
            implied_volatility_decimal = black_iv(
                option_price,
                spot_price,
                strike,
                interest_rate_decimal,
                time_to_expiry_years,
                flag
            )
            # Convert to percentage for display
            implied_volatility = implied_volatility_decimal * 100.0

        except Exception as e:
            logger.error(f"Error calculating IV: {e}")
            return False, {
                'status': 'error',
                'message': f'Failed to calculate Implied Volatility: {str(e)}'
            }, 500

        # Calculate Greeks using Black-76 model
        try:
            # All Greek functions: func(flag, F, K, t, r, sigma)
            # sigma is IV as decimal
            delta = black_delta(flag, spot_price, strike, time_to_expiry_years, interest_rate_decimal, implied_volatility_decimal)
            gamma = black_gamma(flag, spot_price, strike, time_to_expiry_years, interest_rate_decimal, implied_volatility_decimal)
            theta = black_theta(flag, spot_price, strike, time_to_expiry_years, interest_rate_decimal, implied_volatility_decimal)
            vega = black_vega(flag, spot_price, strike, time_to_expiry_years, interest_rate_decimal, implied_volatility_decimal)
            rho = black_rho(flag, spot_price, strike, time_to_expiry_years, interest_rate_decimal, implied_volatility_decimal)

            # Note: py_vollib Black model returns Greeks in trader-friendly units:
            # - theta: already daily theta (no conversion needed)
            # - vega: already per 1% vol change (no conversion needed)

        except Exception as e:
            logger.error(f"Error calculating Greeks: {e}")
            return False, {
                'status': 'error',
                'message': f'Failed to calculate Greeks: {str(e)}'
            }, 500

        # Build response
        response = {
            'status': 'success',
            'symbol': option_symbol,
            'exchange': exchange,
            'underlying': base_symbol,
            'strike': round(strike, 2),
            'option_type': opt_type,
            'expiry_date': expiry.strftime('%d-%b-%Y'),
            'days_to_expiry': round(time_to_expiry_days, 4),
            'spot_price': round(spot_price, 2),
            'option_price': round(option_price, 2),
            'interest_rate': round(interest_rate, 2),
            'implied_volatility': round(implied_volatility, 2),
            'greeks': {
                'delta': round(delta, 4),
                'gamma': round(gamma, 6),
                'theta': round(theta, 4),
                'vega': round(vega, 4),
                'rho': round(rho, 6)
            }
        }

        logger.info(f"Greeks calculated successfully for {option_symbol} using Black-76 model")
        return True, response, 200

    except ValueError as e:
        logger.error(f"Validation error in calculate_greeks: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 400

    except Exception as e:
        logger.exception(f"Unexpected error in calculate_greeks: {e}")
        return False, {
            'status': 'error',
            'message': f'Failed to calculate option Greeks: {str(e)}'
        }, 500


def get_option_greeks(
    option_symbol: str,
    exchange: str,
    interest_rate: Optional[float] = None,
    forward_price: Optional[float] = None,
    underlying_symbol: Optional[str] = None,
    underlying_exchange: Optional[str] = None,
    expiry_time: Optional[str] = None,
    api_key: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
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
        base_symbol, expiry, strike, opt_type = parse_option_symbol(option_symbol, exchange, expiry_time)

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
                return False, {
                    'status': 'error',
                    'message': f'Failed to fetch underlying price: {spot_response.get("message", "Unknown error")}'
                }, status_code

            spot_price = spot_response.get('data', {}).get('ltp')
            if not spot_price:
                return False, {
                    'status': 'error',
                    'message': 'Underlying LTP not available'
                }, 404

        # Fetch option price
        logger.info(f"Fetching option price for {option_symbol} from {exchange}")
        success, option_response, status_code = get_quotes(option_symbol, exchange, api_key)

        if not success:
            return False, {
                'status': 'error',
                'message': f'Failed to fetch option price: {option_response.get("message", "Unknown error")}'
            }, status_code

        option_price = option_response.get('data', {}).get('ltp')
        if not option_price:
            return False, {
                'status': 'error',
                'message': 'Option LTP not available'
            }, 404

        # Calculate Greeks
        return calculate_greeks(
            option_symbol=option_symbol,
            exchange=exchange,
            spot_price=spot_price,
            option_price=option_price,
            interest_rate=interest_rate,
            expiry_time=expiry_time,
            api_key=api_key
        )

    except Exception as e:
        logger.exception(f"Error in get_option_greeks: {e}")
        return False, {
            'status': 'error',
            'message': f'Failed to get option Greeks: {str(e)}'
        }, 500
