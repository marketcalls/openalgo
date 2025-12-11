# sandbox/position_manager.py
"""
Position Manager - Handles position tracking and MTM calculations

Features:
- Real-time position tracking
- Mark-to-Market (MTM) P&L calculations
- Position netting (same symbol/exchange/product)
- Open position retrieval with live P&L
- Background MTM updates (configurable interval)
"""

import os
import sys
from decimal import Decimal
from datetime import datetime
import pytz
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import (
    SandboxPositions, SandboxTrades, db_session, get_config
)
from sandbox.fund_manager import FundManager
from sandbox.holdings_manager import HoldingsManager
from services.quotes_service import get_quotes, get_multiquotes
from utils.logging import get_logger

logger = get_logger(__name__)


def parse_expiry_from_symbol(symbol, exchange):
    """
    Parse expiry date from F&O symbol name.

    Supports formats like:
    - NIFTY09DEC2526000CE -> 09-Dec-2025
    - BANKNIFTY31JUL25FUT -> 31-Jul-2025
    - RELIANCE25DEC24FUT -> 25-Dec-2024

    Args:
        symbol: Trading symbol (e.g., NIFTY09DEC2526000CE)
        exchange: Exchange (NFO, BFO, MCX, CDS, etc.)

    Returns:
        datetime.date or None if not an F&O instrument or parsing fails
    """
    import re

    # Only process F&O exchanges
    fo_exchanges = ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']
    if exchange not in fo_exchanges:
        return None

    # Pattern to extract date from symbol: DDMMMYY (e.g., 09DEC25, 31JUL25)
    # This pattern looks for 2 digits + 3 letters (month) + 2 digits (year)
    pattern = r'(\d{2})([A-Z]{3})(\d{2})'

    match = re.search(pattern, symbol)
    if not match:
        return None

    try:
        day = int(match.group(1))
        month_str = match.group(2)
        year_short = int(match.group(3))

        # Convert 2-digit year to 4-digit (assuming 20xx)
        year = 2000 + year_short

        # Parse month
        month_map = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
            'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
            'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }

        month = month_map.get(month_str)
        if not month:
            return None

        # Create date object
        from datetime import date
        expiry_date = date(year, month, day)

        return expiry_date

    except (ValueError, KeyError) as e:
        logger.debug(f"Could not parse expiry from symbol {symbol}: {e}")
        return None


def get_expiry_from_database(symbol, exchange):
    """
    Get expiry date from SymToken database as fallback.

    Args:
        symbol: Trading symbol
        exchange: Exchange

    Returns:
        datetime.date or None
    """
    try:
        from database.symbol import SymToken
        from datetime import datetime

        sym_token = SymToken.query.filter_by(
            symbol=symbol,
            exchange=exchange
        ).first()

        if sym_token and sym_token.expiry:
            # Expiry format in DB is typically "DD-MMM-YY" (e.g., "09-DEC-25")
            try:
                expiry_date = datetime.strptime(sym_token.expiry, "%d-%b-%y").date()
                return expiry_date
            except ValueError:
                try:
                    # Try alternative format "DD-MMM-YYYY"
                    expiry_date = datetime.strptime(sym_token.expiry, "%d-%b-%Y").date()
                    return expiry_date
                except ValueError:
                    logger.debug(f"Could not parse expiry '{sym_token.expiry}' for {symbol}")
                    return None

        return None

    except Exception as e:
        logger.debug(f"Error fetching expiry from DB for {symbol}: {e}")
        return None


def get_contract_expiry(symbol, exchange):
    """
    Get contract expiry date for a symbol.
    First tries to parse from symbol name, then falls back to database lookup.

    Args:
        symbol: Trading symbol
        exchange: Exchange

    Returns:
        datetime.date or None if not an F&O instrument
    """
    # First try parsing from symbol name (faster, no DB query)
    expiry = parse_expiry_from_symbol(symbol, exchange)

    if expiry:
        return expiry

    # Fallback to database lookup
    return get_expiry_from_database(symbol, exchange)


class PositionManager:
    """Manages positions and MTM calculations"""

    def __init__(self, user_id):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    def _check_and_close_expired_positions(self, positions):
        """
        Check for expired F&O contracts and auto-close them.

        For expired contracts:
        - Options expire worthless (value = 0) if not ITM
        - Uses last available P&L for settlement
        - Releases blocked margin back to available balance
        - Marks position as closed (quantity = 0)

        Args:
            positions: List of SandboxPositions objects to check

        Returns:
            list: Positions that are still valid (not expired)
        """
        from datetime import date

        today = date.today()
        valid_positions = []
        expired_count = 0

        for position in positions:
            # Skip already closed positions
            if position.quantity == 0:
                valid_positions.append(position)
                continue

            # Get contract expiry date
            expiry_date = get_contract_expiry(position.symbol, position.exchange)

            # If no expiry found (equity or couldn't parse), keep the position
            if expiry_date is None:
                valid_positions.append(position)
                continue

            # Check if contract has expired (day after expiry)
            # We don't close on expiry day itself - traders want to see P&L that day
            # Auto-close happens on the next day after expiry
            if today > expiry_date:
                # Contract has expired - auto-close it
                logger.info(
                    f"Expired contract detected: {position.symbol} "
                    f"(expiry: {expiry_date}, today: {today}, user: {position.user_id})"
                )

                try:
                    self._settle_expired_position(position)
                    expired_count += 1
                except Exception as e:
                    logger.error(f"Error settling expired position {position.symbol}: {e}")
                    # Keep the position in list if settlement fails
                    valid_positions.append(position)
            else:
                # Contract is still valid
                valid_positions.append(position)

        if expired_count > 0:
            logger.info(f"Auto-closed {expired_count} expired contract(s) for user {self.user_id}")

        return valid_positions

    def _settle_expired_position(self, position):
        """
        Settle an expired position.

        - Uses last available LTP for settlement (frozen at last traded price)
        - If no LTP available, falls back to average price
        - Releases margin and updates realized P&L

        Args:
            position: SandboxPositions object to settle
        """
        from decimal import Decimal

        symbol = position.symbol
        quantity = position.quantity
        avg_price = Decimal(str(position.average_price))
        margin_blocked = Decimal(str(position.margin_blocked or 0))

        # Use last available LTP for settlement
        # This freezes the P&L at the last traded price before expiry
        # Falls back to average price if LTP is not available
        if position.ltp and Decimal(str(position.ltp)) > 0:
            settlement_price = Decimal(str(position.ltp))
            logger.info(f"Expired contract {symbol} settling at last LTP: {settlement_price}")
        else:
            # Fallback to average price if no LTP available
            settlement_price = avg_price
            logger.info(f"Expired contract {symbol} settling at avg price (no LTP): {settlement_price}")

        # Calculate realized P&L for this closure
        if quantity > 0:
            # Long position: P&L = (settlement - avg) * qty
            close_pnl = (settlement_price - avg_price) * Decimal(str(quantity))
        else:
            # Short position: P&L = (avg - settlement) * abs(qty)
            close_pnl = (avg_price - settlement_price) * Decimal(str(abs(quantity)))

        # Get accumulated realized P&L from position
        accumulated_realized = Decimal(str(position.accumulated_realized_pnl or 0))

        # Total realized P&L for this position
        total_realized_pnl = accumulated_realized + close_pnl

        logger.info(
            f"Settling expired {symbol}: qty={quantity}, avg={avg_price}, "
            f"settlement={settlement_price}, close_pnl={close_pnl}, "
            f"total_realized={total_realized_pnl}, margin_to_release={margin_blocked}"
        )

        # Release margin and update funds
        self.fund_manager.release_margin(
            amount=margin_blocked,
            realized_pnl=close_pnl,
            description=f"Expired contract settlement: {symbol}"
        )

        # Update position to closed state
        position.quantity = 0
        position.ltp = settlement_price
        position.pnl = total_realized_pnl
        position.accumulated_realized_pnl = total_realized_pnl
        position.margin_blocked = Decimal('0')

        db_session.commit()

        logger.info(f"Expired position {symbol} settled successfully for user {position.user_id}")

    def get_open_positions(self, update_mtm=True):
        """
        Get all open positions for the user
        - After session expiry, only NRML positions carry forward
        - MIS and CNC positions are settled at session expiry

        Args:
            update_mtm: bool - Whether to update MTM with live prices

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            from datetime import datetime, time, timedelta
            import os

            # Get session expiry time from config (e.g., '03:00')
            session_expiry_str = os.getenv('SESSION_EXPIRY_TIME', '03:00')
            expiry_hour, expiry_minute = map(int, session_expiry_str.split(':'))

            # Get current time
            now = datetime.now()
            today = now.date()

            # Calculate if we're in a new session
            session_expiry_time = time(expiry_hour, expiry_minute)

            # Determine last session expiry
            if now.time() < session_expiry_time:
                # We're before today's session expiry (e.g., before 3 AM)
                # Last session expired yesterday at 3 AM
                last_session_expiry = datetime.combine(today - timedelta(days=1), session_expiry_time)
            else:
                # We're after today's session expiry (e.g., after 3 AM)
                # Last session expired today at 3 AM
                last_session_expiry = datetime.combine(today, session_expiry_time)

            # Get all positions (including zero quantity ones from current session)
            positions_query = SandboxPositions.query.filter(
                SandboxPositions.user_id == self.user_id
            )

            # Check if we need to filter positions based on product type
            # If position was created before last session expiry and it's not NRML,
            # it should have been settled
            all_positions = positions_query.all()
            positions = []

            for position in all_positions:
                # If position was updated after last session expiry, include it
                # This includes positions that went to zero during current session (closed positions)
                if position.updated_at >= last_session_expiry:
                    positions.append(position)
                # If position was updated before last session expiry, only include NRML with non-zero quantity
                elif position.product == 'NRML' and position.quantity != 0:
                    positions.append(position)
                # Skip MIS and CNC positions from previous session

            # Check for and auto-close expired F&O contracts
            # This handles NRML positions where the contract has expired
            positions = self._check_and_close_expired_positions(positions)

            if update_mtm:
                self._update_positions_mtm(positions)

            positions_list = []
            total_unrealized_pnl = Decimal('0.00')  # Only from open positions
            total_display_pnl = Decimal('0.00')     # For display (includes closed positions)

            for position in positions:
                pnl = Decimal(str(position.pnl))

                # Add to display total (includes all positions)
                total_display_pnl += pnl

                # Only add to unrealized P&L if position is open (not closed)
                # Closed positions (qty=0) have their P&L already in realized_pnl in funds
                if position.quantity != 0:
                    total_unrealized_pnl += pnl

                positions_list.append({
                    'symbol': position.symbol,
                    'exchange': position.exchange,
                    'product': position.product,
                    'quantity': position.quantity,
                    'average_price': float(position.average_price),
                    'ltp': float(position.ltp) if position.ltp else 0.0,
                    'pnl': float(pnl),
                    'pnl_percent': float(position.pnl_percent),
                })

            # Update fund unrealized P&L (only from open positions)
            # Closed position P&L is already in realized_pnl, so don't include it here
            if update_mtm:
                self.fund_manager.update_unrealized_pnl(total_unrealized_pnl)

            return True, {
                'status': 'success',
                'data': positions_list,
                'total_pnl': float(total_display_pnl),  # Display total includes all positions
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error getting positions for user {self.user_id}: {e}")
            return False, {
                'status': 'error',
                'message': f'Error getting positions: {str(e)}',
                'mode': 'analyze'
            }, 500

    def get_position_for_symbol(self, symbol, exchange, product):
        """Get position for a specific symbol"""
        try:
            position = SandboxPositions.query.filter_by(
                user_id=self.user_id,
                symbol=symbol,
                exchange=exchange,
                product=product
            ).first()

            if not position:
                return None

            # Update MTM
            self._update_single_position_mtm(position)

            return {
                'symbol': position.symbol,
                'exchange': position.exchange,
                'product': position.product,
                'quantity': position.quantity,
                'average_price': float(position.average_price),
                'ltp': float(position.ltp) if position.ltp else 0.0,
                'pnl': float(position.pnl),
                'pnl_percent': float(position.pnl_percent),
            }

        except Exception as e:
            logger.error(f"Error getting position for {symbol}: {e}")
            return None

    def _update_positions_mtm(self, positions):
        """Update MTM for all positions with live quotes"""
        try:
            if not positions:
                return

            # Get unique symbols
            symbols_to_fetch = set()
            for position in positions:
                symbols_to_fetch.add((position.symbol, position.exchange))

            symbols_list = list(symbols_to_fetch)

            # Fetch quotes using multiquotes (single API call)
            quote_cache = self._fetch_quotes_batch(symbols_list)

            # Fallback: For any symbols that failed in batch, try individual fetch
            failed_symbols = [s for s in symbols_list if s not in quote_cache or quote_cache[s] is None]
            if failed_symbols:
                logger.debug(f"Fetching {len(failed_symbols)} symbols individually (multiquotes fallback)")
                for symbol, exchange in failed_symbols:
                    quote = self._fetch_quote(symbol, exchange)
                    if quote:
                        quote_cache[(symbol, exchange)] = quote

            # Update MTM for each position
            for position in positions:
                # Skip MTM update for closed positions (quantity = 0)
                # They already have accumulated realized P&L stored in position.pnl
                if position.quantity == 0:
                    continue

                quote = quote_cache.get((position.symbol, position.exchange))
                if quote:
                    ltp = Decimal(str(quote.get('ltp', 0)))
                    if ltp > 0:
                        position.ltp = ltp

                        # Calculate current unrealized P&L for open position
                        current_unrealized_pnl = self._calculate_position_pnl(
                            position.quantity,
                            position.average_price,
                            ltp
                        )

                        # Display = accumulated realized P&L + current unrealized P&L
                        accumulated_realized = position.accumulated_realized_pnl if position.accumulated_realized_pnl else Decimal('0.00')
                        position.pnl = accumulated_realized + current_unrealized_pnl

                        position.pnl_percent = self._calculate_pnl_percent(
                            position.average_price,
                            ltp,
                            position.quantity
                        )

            db_session.commit()

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating positions MTM: {e}")

    def _update_single_position_mtm(self, position):
        """Update MTM for a single position"""
        try:
            # Skip MTM update for closed positions (quantity = 0)
            # They already have realized P&L stored from when position was closed
            if position.quantity == 0:
                return

            quote = self._fetch_quote(position.symbol, position.exchange)
            if quote:
                ltp = Decimal(str(quote.get('ltp', 0)))
                if ltp > 0:
                    position.ltp = ltp

                    # Calculate current unrealized P&L for open position
                    current_unrealized_pnl = self._calculate_position_pnl(
                        position.quantity,
                        position.average_price,
                        ltp
                    )

                    # Display = accumulated realized P&L + current unrealized P&L
                    accumulated_realized = position.accumulated_realized_pnl if position.accumulated_realized_pnl else Decimal('0.00')
                    position.pnl = accumulated_realized + current_unrealized_pnl

                    position.pnl_percent = self._calculate_pnl_percent(
                        position.average_price,
                        ltp,
                        position.quantity
                    )
                    db_session.commit()

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating position MTM for {position.symbol}: {e}")

    def _calculate_position_pnl(self, quantity, avg_price, ltp):
        """Calculate P&L for a position"""
        try:
            quantity = Decimal(str(quantity))
            avg_price = Decimal(str(avg_price))
            ltp = Decimal(str(ltp))

            if quantity > 0:
                # Long position
                pnl = (ltp - avg_price) * quantity
            else:
                # Short position
                pnl = (avg_price - ltp) * abs(quantity)

            return pnl

        except Exception as e:
            logger.error(f"Error calculating position P&L: {e}")
            return Decimal('0.00')

    def _calculate_pnl_percent(self, avg_price, ltp, quantity):
        """Calculate P&L percentage"""
        try:
            avg_price = Decimal(str(avg_price))
            ltp = Decimal(str(ltp))

            if avg_price <= 0:
                return Decimal('0.00')

            if quantity > 0:
                # Long position
                pnl_percent = ((ltp - avg_price) / avg_price) * Decimal('100')
            else:
                # Short position
                pnl_percent = ((avg_price - ltp) / avg_price) * Decimal('100')

            return pnl_percent

        except Exception as e:
            logger.error(f"Error calculating P&L percent: {e}")
            return Decimal('0.00')

    def _fetch_quote(self, symbol, exchange):
        """Fetch real-time quote for a symbol using API key"""
        try:
            # Get any user's API key for fetching quotes
            from database.auth_db import ApiKeys, decrypt_token
            api_key_obj = ApiKeys.query.first()

            if not api_key_obj:
                logger.warning("No API keys found for fetching quotes")
                return None

            # Decrypt the API key
            api_key = decrypt_token(api_key_obj.api_key_encrypted)

            # Use quotes service with API key authentication
            success, response, status_code = get_quotes(
                symbol=symbol,
                exchange=exchange,
                api_key=api_key
            )

            if success and 'data' in response:
                return response['data']
            else:
                logger.warning(f"Failed to fetch quote for {symbol}: {response.get('message', 'Unknown error')}")
                return None

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None

    def _fetch_quotes_batch(self, symbols_list):
        """
        Fetch quotes for multiple symbols in a single API call using multiquotes.
        Returns dict mapping (symbol, exchange) to quote data.
        Returns empty dict if multiquotes fails completely.
        """
        quote_cache = {}

        if not symbols_list:
            return quote_cache

        try:
            # Get any user's API key for fetching quotes
            from database.auth_db import ApiKeys, decrypt_token
            api_key_obj = ApiKeys.query.first()

            if not api_key_obj:
                logger.debug("No API keys found for fetching multiquotes")
                return quote_cache

            # Decrypt the API key
            api_key = decrypt_token(api_key_obj.api_key_encrypted)

            # Prepare symbols list for multiquotes API
            symbols_payload = [
                {"symbol": symbol, "exchange": exchange}
                for symbol, exchange in symbols_list
            ]

            # Use multiquotes service
            success, response, status_code = get_multiquotes(
                symbols=symbols_payload,
                api_key=api_key
            )

            if success and 'results' in response:
                results = response['results']
                successful_count = 0

                for result in results:
                    symbol = result.get('symbol')
                    exchange = result.get('exchange')

                    # Check if this result has data or error
                    if 'data' in result and result['data']:
                        quote_data = result['data']
                        quote_cache[(symbol, exchange)] = quote_data
                        logger.debug(f"Multiquotes: {symbol} LTP={quote_data.get('ltp', 0)}")
                        successful_count += 1
                    elif 'error' in result:
                        logger.debug(f"Multiquotes error for {symbol}: {result['error']}")

                logger.info(f"Positions MTM: Multiquotes fetched {successful_count}/{len(symbols_list)} symbols")
            else:
                logger.debug(f"Multiquotes failed: {response.get('message', 'Unknown error')}")

        except Exception as e:
            logger.debug(f"Exception in multiquotes fetch: {str(e)}")

        return quote_cache

    def close_position(self, symbol, exchange, product):
        """
        Close a position (square-off)
        Creates a reverse order to close the position
        """
        try:
            position = SandboxPositions.query.filter_by(
                user_id=self.user_id,
                symbol=symbol,
                exchange=exchange,
                product=product
            ).first()

            if not position:
                return False, {
                    'status': 'error',
                    'message': f'No open position found for {symbol}',
                    'mode': 'analyze'
                }, 404

            # Determine action (opposite of current position)
            action = 'SELL' if position.quantity > 0 else 'BUY'
            quantity = abs(position.quantity)

            # Create market order to close position
            from sandbox.order_manager import OrderManager
            order_manager = OrderManager(self.user_id)

            order_data = {
                'symbol': symbol,
                'exchange': exchange,
                'action': action,
                'quantity': quantity,
                'price_type': 'MARKET',
                'product': product,
                'strategy': 'AUTO_SQUARE_OFF'
            }

            success, response, status_code = order_manager.place_order(order_data)

            if success:
                logger.info(f"Position close order placed: {symbol} {action} {quantity}")
                return True, {
                    'status': 'success',
                    'message': f'Position close order placed for {symbol}',
                    'orderid': response.get('orderid'),
                    'mode': 'analyze'
                }, 200
            else:
                return False, response, status_code

        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
            return False, {
                'status': 'error',
                'message': f'Error closing position: {str(e)}',
                'mode': 'analyze'
            }, 500

    def get_tradebook(self):
        """Get all executed trades for the user for current session only"""
        try:
            from datetime import datetime, time, timedelta
            import os

            # Get session expiry time from config (e.g., '03:00')
            session_expiry_str = os.getenv('SESSION_EXPIRY_TIME', '03:00')
            expiry_hour, expiry_minute = map(int, session_expiry_str.split(':'))

            # Get current time
            now = datetime.now()
            today = now.date()

            # Calculate session start time
            # If current time is before session expiry (e.g., before 3 AM),
            # session started yesterday at expiry time
            session_expiry_time = time(expiry_hour, expiry_minute)

            if now.time() < session_expiry_time:
                # We're in the early morning before session expiry
                # Session started yesterday at expiry time
                session_start = datetime.combine(today - timedelta(days=1), session_expiry_time)
            else:
                # We're after session expiry time
                # Session started today at expiry time
                session_start = datetime.combine(today, session_expiry_time)

            trades = SandboxTrades.query.filter(
                SandboxTrades.user_id == self.user_id,
                SandboxTrades.trade_timestamp >= session_start
            ).order_by(
                SandboxTrades.trade_timestamp.desc()
            ).all()

            tradebook = []
            for trade in trades:
                price = float(trade.price)
                quantity = abs(trade.quantity)  # Use absolute value for trade_value calculation
                trade_value = round(price * quantity, 2)  # Round to 2 decimal places

                tradebook.append({
                    'tradeid': trade.tradeid,
                    'orderid': trade.orderid,
                    'symbol': trade.symbol,
                    'exchange': trade.exchange,
                    'action': trade.action,
                    'quantity': trade.quantity,
                    'average_price': round(price, 2),  # Round to 2 decimal places
                    'price': round(price, 2),  # Round to 2 decimal places
                    'trade_value': trade_value,  # Trade value already rounded above
                    'product': trade.product,
                    'strategy': trade.strategy or '',
                    'timestamp': trade.trade_timestamp.strftime('%Y-%m-%d %H:%M:%S')
                })

            return True, {
                'status': 'success',
                'data': tradebook,
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error getting tradebook: {e}")
            return False, {
                'status': 'error',
                'message': f'Error getting tradebook: {str(e)}',
                'mode': 'analyze'
            }, 500

    def process_session_settlement(self):
        """
        Process session expiry settlement (at SESSION_EXPIRY_TIME):
        1. Auto square-off MIS positions
        2. Move CNC positions to holdings (T+1 settlement)
        3. Keep NRML positions as carry forward

        This should be called at session expiry time (e.g., 3:00 AM IST)
        """
        try:
            from datetime import datetime, date
            from database.sandbox_db import SandboxHoldings
            from database import db
            import os

            # Get session expiry time from config
            session_expiry_str = os.getenv('SESSION_EXPIRY_TIME', '03:00')
            logger.info(f"Processing session settlement at {session_expiry_str}")

            # Get all open positions
            positions = SandboxPositions.query.filter_by(user_id=self.user_id).all()

            for position in positions:
                if position.quantity == 0:
                    continue  # Skip closed positions

                if position.product == 'MIS':
                    # Auto square-off MIS positions at market close
                    # Create a reverse order to square off
                    action = 'SELL' if position.quantity > 0 else 'BUY'
                    quantity = abs(position.quantity)

                    # Use last traded price or average price for square-off
                    price = float(position.average_price) if position.average_price else 0

                    # Update position to closed
                    position.quantity = 0
                    position.pnl = float(position.realized_pnl)
                    db.session.commit()

                    logger.info(f"Auto squared-off MIS position: {position.symbol} qty: {quantity}")

                elif position.product == 'CNC' and position.quantity > 0:
                    # Move CNC buy positions to holdings (T+1 settlement)
                    # CNC sell positions are already closed (no short delivery allowed)

                    # Check if holdings exist
                    holdings = SandboxHoldings.query.filter_by(
                        user_id=self.user_id,
                        symbol=position.symbol,
                        exchange=position.exchange
                    ).first()

                    if holdings:
                        # Update existing holdings
                        holdings.quantity += position.quantity
                        holdings.average_price = (
                            (holdings.average_price * holdings.quantity +
                             position.average_price * position.quantity) /
                            (holdings.quantity + position.quantity)
                        )
                    else:
                        # Create new holdings
                        holdings = SandboxHoldings(
                            user_id=self.user_id,
                            symbol=position.symbol,
                            exchange=position.exchange,
                            quantity=position.quantity,
                            average_price=position.average_price,
                            settlement_date=date.today()
                        )
                        db.session.add(holdings)

                    # Clear the CNC position
                    position.quantity = 0
                    position.pnl = float(position.realized_pnl)
                    db.session.commit()

                    logger.info(f"Moved CNC position to holdings: {position.symbol} qty: {position.quantity}")

                # NRML positions remain as-is (carry forward)

            return True, {
                'status': 'success',
                'message': 'Session settlement completed',
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error in EOD settlement: {e}")
            db.session.rollback()
            return False, {
                'status': 'error',
                'message': f'Error in EOD settlement: {str(e)}',
                'mode': 'analyze'
            }, 500


def update_all_positions_mtm():
    """Background task to update MTM for all positions"""
    try:
        # Get all unique users with positions
        positions = SandboxPositions.query.all()

        if not positions:
            logger.debug("No positions to update")
            return

        users = set(p.user_id for p in positions)
        logger.info(f"Updating MTM for {len(positions)} positions across {len(users)} users")

        for user_id in users:
            pm = PositionManager(user_id)
            pm.get_open_positions(update_mtm=True)

        logger.info("MTM update completed")

    except Exception as e:
        logger.error(f"Error updating MTM for all positions: {e}")


def process_all_users_settlement():
    """
    Process T+1 settlement for all users at midnight (00:00 IST)
    - Moves CNC positions to holdings
    - Auto squares-off any remaining MIS positions
    - NRML positions carry forward
    """
    try:
        # Get all unique users with positions
        positions = SandboxPositions.query.all()

        if not positions:
            logger.info("No positions to settle")
            return

        users = set(p.user_id for p in positions)
        logger.info(f"Processing T+1 settlement for {len(users)} users at midnight")

        for user_id in users:
            try:
                holdings_manager = HoldingsManager(user_id)
                success, message = holdings_manager.process_t1_settlement()

                if success:
                    logger.info(f"Settlement completed for user {user_id}")
                else:
                    logger.error(f"Settlement failed for user {user_id}: {message}")

            except Exception as e:
                logger.error(f"Error in settlement for user {user_id}: {e}")
                continue

        logger.info("T+1 settlement completed for all users")

    except Exception as e:
        logger.error(f"Error in T+1 settlement process: {e}")


def catchup_missed_settlements():
    """
    Catch-up settlement for positions that should have been settled while app was stopped.
    Runs on startup when analyzer mode is enabled.

    Checks for CNC positions older than 1 day and settles them to holdings.
    """
    try:
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).date()
        cutoff_time = datetime.combine(today, datetime.min.time())

        cnc_positions = SandboxPositions.query.filter_by(product='CNC').filter(
            SandboxPositions.quantity != 0,
            SandboxPositions.created_at < cutoff_time
        ).all()

        if not cnc_positions:
            logger.debug("No CNC positions for catch-up settlement")
            return

        logger.info(f"Found {len(cnc_positions)} CNC positions that need catch-up settlement")

        users = set(p.user_id for p in cnc_positions)

        for user_id in users:
            try:
                holdings_manager = HoldingsManager(user_id)
                success, message = holdings_manager.process_t1_settlement()

                if success:
                    logger.info(f"Catch-up settlement completed for user {user_id}")
                else:
                    logger.error(f"Catch-up settlement failed for user {user_id}: {message}")

            except Exception as e:
                logger.error(f"Error in catch-up settlement for user {user_id}: {e}")
                continue

        logger.info("Catch-up settlement process completed")

    except Exception as e:
        logger.error(f"Error in catch-up settlement: {e}")


if __name__ == '__main__':
    """Run MTM updater in standalone mode"""
    logger.info("Starting Sandbox MTM Updater")

    from database.sandbox_db import init_db
    init_db()

    mtm_interval = int(get_config('mtm_update_interval', '5'))

    if mtm_interval == 0:
        logger.info("Automatic MTM updates disabled (interval = 0)")
        exit(0)

    logger.info(f"MTM update interval: {mtm_interval} seconds")

    try:
        while True:
            update_all_positions_mtm()
            time.sleep(mtm_interval)
    except KeyboardInterrupt:
        logger.info("MTM updater stopped by user")
    except Exception as e:
        logger.error(f"MTM updater error: {e}")
