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
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


class PositionManager:
    """Manages positions and MTM calculations"""

    def __init__(self, user_id):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    def get_open_positions(self, update_mtm=True):
        """
        Get all open positions for the user

        Args:
            update_mtm: bool - Whether to update MTM with live prices

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            positions = SandboxPositions.query.filter_by(user_id=self.user_id).all()

            if update_mtm:
                self._update_positions_mtm(positions)

            positions_list = []
            total_pnl = Decimal('0.00')

            for position in positions:
                pnl = Decimal(str(position.pnl))
                total_pnl += pnl

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

            # Update fund unrealized P&L
            if update_mtm:
                self.fund_manager.update_unrealized_pnl(total_pnl)

            return True, {
                'status': 'success',
                'data': positions_list,
                'total_pnl': float(total_pnl),
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

            # Fetch quotes for all symbols
            quote_cache = {}
            for symbol, exchange in symbols_to_fetch:
                quote = self._fetch_quote(symbol, exchange)
                if quote:
                    quote_cache[(symbol, exchange)] = quote

            # Update MTM for each position
            for position in positions:
                quote = quote_cache.get((position.symbol, position.exchange))
                if quote:
                    ltp = Decimal(str(quote.get('ltp', 0)))
                    if ltp > 0:
                        position.ltp = ltp
                        position.pnl = self._calculate_position_pnl(
                            position.quantity,
                            position.average_price,
                            ltp
                        )
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
            quote = self._fetch_quote(position.symbol, position.exchange)
            if quote:
                ltp = Decimal(str(quote.get('ltp', 0)))
                if ltp > 0:
                    position.ltp = ltp
                    position.pnl = self._calculate_position_pnl(
                        position.quantity,
                        position.average_price,
                        ltp
                    )
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
        """Get all executed trades for the user"""
        try:
            trades = SandboxTrades.query.filter_by(user_id=self.user_id).order_by(
                SandboxTrades.trade_timestamp.desc()
            ).all()

            tradebook = []
            for trade in trades:
                price = float(trade.price)
                quantity = abs(trade.quantity)  # Use absolute value for trade_value calculation
                trade_value = price * quantity

                tradebook.append({
                    'tradeid': trade.tradeid,
                    'orderid': trade.orderid,
                    'symbol': trade.symbol,
                    'exchange': trade.exchange,
                    'action': trade.action,
                    'quantity': trade.quantity,
                    'average_price': price,  # Field name expected by frontend
                    'price': price,  # Keep for backward compatibility
                    'trade_value': trade_value,  # Calculate trade value
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
