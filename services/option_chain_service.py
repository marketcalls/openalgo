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

from typing import Tuple, Dict, Any, List, Optional
from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from services.quotes_service import get_quotes, get_multiquotes
from services.option_symbol_service import (
    parse_underlying_symbol,
    get_option_exchange,
    get_available_strikes,
    find_atm_strike_from_actual,
    construct_option_symbol
)
from utils.logging import get_logger

logger = get_logger(__name__)


def get_strikes_with_labels(
    available_strikes: List[float],
    atm_strike: float,
    strike_count: Optional[int] = None
) -> List[Dict[str, Any]]:
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
        return [{'strike': s, 'ce_label': '', 'pe_label': ''} for s in available_strikes]

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
            ce_label = 'ATM'
            pe_label = 'ATM'
        elif strike < atm_strike:
            # Strikes below ATM: CE is ITM, PE is OTM
            position = atm_index - available_strikes.index(strike)
            ce_label = f'ITM{position}'
            pe_label = f'OTM{position}'
        else:
            # Strikes above ATM: CE is OTM, PE is ITM
            position = available_strikes.index(strike) - atm_index
            ce_label = f'OTM{position}'
            pe_label = f'ITM{position}'

        result.append({'strike': strike, 'ce_label': ce_label, 'pe_label': pe_label})

    return result


def get_option_symbols_for_chain(
    base_symbol: str,
    expiry_date: str,
    strikes_with_labels: List[Dict[str, Any]],
    exchange: str
) -> List[Dict[str, Any]]:
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
    expiry_formatted = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}".upper()

    for strike_info in strikes_with_labels:
        strike = strike_info['strike']
        ce_label = strike_info['ce_label']
        pe_label = strike_info['pe_label']

        # Construct symbol names
        ce_symbol = construct_option_symbol(base_symbol, expiry_date, strike, "CE")
        pe_symbol = construct_option_symbol(base_symbol, expiry_date, strike, "PE")

        # Query database for both CE and PE
        ce_record = db_session.query(SymToken).filter(
            SymToken.symbol == ce_symbol,
            SymToken.exchange == exchange
        ).first()

        pe_record = db_session.query(SymToken).filter(
            SymToken.symbol == pe_symbol,
            SymToken.exchange == exchange
        ).first()

        chain_symbols.append({
            'strike': strike,
            'ce': {
                'symbol': ce_symbol,
                'label': ce_label,
                'exists': ce_record is not None,
                'lotsize': ce_record.lotsize if ce_record else None,
                'tick_size': ce_record.tick_size if ce_record else None
            },
            'pe': {
                'symbol': pe_symbol,
                'label': pe_label,
                'exists': pe_record is not None,
                'lotsize': pe_record.lotsize if pe_record else None,
                'tick_size': pe_record.tick_size if pe_record else None
            }
        })

    return chain_symbols


def get_option_chain(
    underlying: str,
    exchange: str,
    expiry_date: str,
    strike_count: int,
    api_key: str
) -> Tuple[bool, Dict[str, Any], int]:
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
            return False, {
                'status': 'error',
                'message': 'Expiry date is required.'
            }, 400

        # Step 2: Determine quote exchange for underlying LTP
        quote_exchange = exchange
        if exchange.upper() in ['NFO', 'BFO']:
            if base_symbol in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'INDIAVIX']:
                quote_exchange = 'NSE_INDEX'
            elif base_symbol in ['SENSEX', 'BANKEX', 'SENSEX50']:
                quote_exchange = 'BSE_INDEX'
            else:
                quote_exchange = 'NSE' if exchange.upper() == 'NFO' else 'BSE'

        # Use base symbol for index quotes
        quote_symbol = base_symbol if embedded_expiry else underlying

        # Step 3: Fetch underlying LTP
        logger.info(f"Fetching LTP for {quote_symbol} on {quote_exchange}")
        success, quote_response, status_code = get_quotes(
            symbol=quote_symbol,
            exchange=quote_exchange,
            api_key=api_key
        )

        if not success:
            return False, {
                'status': 'error',
                'message': f"Failed to fetch LTP for {quote_symbol}: {quote_response.get('message', 'Unknown error')}"
            }, status_code

        underlying_ltp = quote_response.get('data', {}).get('ltp')
        if underlying_ltp is None:
            return False, {
                'status': 'error',
                'message': f'Could not determine LTP for {quote_symbol}'
            }, 500

        logger.info(f"Underlying LTP: {underlying_ltp}")

        # Step 4: Get options exchange and available strikes
        options_exchange = get_option_exchange(quote_exchange)

        # Get strikes for CE (same strikes will work for PE)
        available_strikes = get_available_strikes(base_symbol, final_expiry, "CE", options_exchange)

        if not available_strikes:
            return False, {
                'status': 'error',
                'message': f'No strikes found for {base_symbol} expiring {final_expiry}. Please check expiry date or update master contract.'
            }, 404

        # Step 5: Find ATM and get strikes around it
        atm_strike = find_atm_strike_from_actual(underlying_ltp, available_strikes)
        if atm_strike is None:
            return False, {
                'status': 'error',
                'message': 'Failed to determine ATM strike'
            }, 500

        strikes_with_labels = get_strikes_with_labels(available_strikes, atm_strike, strike_count)
        logger.info(f"Selected {len(strikes_with_labels)} strikes (strike_count={'all' if strike_count is None else strike_count})")

        # Step 6: Get symbol details for all strikes
        chain_symbols = get_option_symbols_for_chain(
            base_symbol, final_expiry, strikes_with_labels, options_exchange
        )

        # Step 7: Build list of symbols for multiquotes
        symbols_to_fetch = []
        for item in chain_symbols:
            if item['ce']['exists']:
                symbols_to_fetch.append({
                    'symbol': item['ce']['symbol'],
                    'exchange': options_exchange
                })
            if item['pe']['exists']:
                symbols_to_fetch.append({
                    'symbol': item['pe']['symbol'],
                    'exchange': options_exchange
                })

        if not symbols_to_fetch:
            return False, {
                'status': 'error',
                'message': 'No valid option symbols found for the given parameters'
            }, 404

        # Step 8: Fetch quotes for all options using multiquotes
        logger.info(f"Fetching quotes for {len(symbols_to_fetch)} option symbols")
        success, quotes_response, status_code = get_multiquotes(
            symbols=symbols_to_fetch,
            api_key=api_key
        )

        # Build quote lookup map
        quotes_map = {}
        if success and 'results' in quotes_response:
            for result in quotes_response['results']:
                symbol = result.get('symbol')
                if symbol:
                    # Handle both formats: direct data or nested data
                    if 'data' in result:
                        quotes_map[symbol] = result['data']
                    elif 'error' not in result:
                        quotes_map[symbol] = result

        # Step 9: Build final chain response
        chain = []
        for item in chain_symbols:
            strike_data = {
                'strike': item['strike']
            }

            # CE data (label inside CE object)
            ce_symbol = item['ce']['symbol']
            if item['ce']['exists']:
                ce_quote = quotes_map.get(ce_symbol, {})
                strike_data['ce'] = {
                    'symbol': ce_symbol,
                    'label': item['ce']['label'],
                    'ltp': ce_quote.get('ltp', 0),
                    'bid': ce_quote.get('bid', 0),
                    'ask': ce_quote.get('ask', 0),
                    'open': ce_quote.get('open', 0),
                    'high': ce_quote.get('high', 0),
                    'low': ce_quote.get('low', 0),
                    'prev_close': ce_quote.get('prev_close', 0),
                    'volume': ce_quote.get('volume', 0),
                    'oi': ce_quote.get('oi', 0),
                    'lotsize': item['ce']['lotsize'],
                    'tick_size': item['ce']['tick_size']
                }
            else:
                strike_data['ce'] = None

            # PE data (label inside PE object)
            pe_symbol = item['pe']['symbol']
            if item['pe']['exists']:
                pe_quote = quotes_map.get(pe_symbol, {})
                strike_data['pe'] = {
                    'symbol': pe_symbol,
                    'label': item['pe']['label'],
                    'ltp': pe_quote.get('ltp', 0),
                    'bid': pe_quote.get('bid', 0),
                    'ask': pe_quote.get('ask', 0),
                    'open': pe_quote.get('open', 0),
                    'high': pe_quote.get('high', 0),
                    'low': pe_quote.get('low', 0),
                    'prev_close': pe_quote.get('prev_close', 0),
                    'volume': pe_quote.get('volume', 0),
                    'oi': pe_quote.get('oi', 0),
                    'lotsize': item['pe']['lotsize'],
                    'tick_size': item['pe']['tick_size']
                }
            else:
                strike_data['pe'] = None

            chain.append(strike_data)

        return True, {
            'status': 'success',
            'underlying': base_symbol,
            'underlying_ltp': underlying_ltp,
            'expiry_date': final_expiry,
            'atm_strike': atm_strike,
            'chain': chain
        }, 200

    except Exception as e:
        logger.exception(f"Error in get_option_chain: {e}")
        return False, {
            'status': 'error',
            'message': f'An error occurred while fetching option chain: {str(e)}'
        }, 500
