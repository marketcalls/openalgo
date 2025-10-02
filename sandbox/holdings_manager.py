# sandbox/holdings_manager.py
"""
Holdings Manager - Handles T+1 settlement and holdings tracking

Features:
- T+1 settlement for CNC positions
- Automatic position-to-holdings conversion
- Holdings P&L tracking with MTM
- Holdings retrieval with live prices
- Daily settlement processing
"""

import os
import sys
from decimal import Decimal
from datetime import datetime, date, timedelta
import pytz

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import (
    SandboxPositions, SandboxHoldings, db_session
)
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


class HoldingsManager:
    """Manages holdings and T+1 settlement"""

    def __init__(self, user_id):
        self.user_id = user_id

    def get_holdings(self, update_mtm=True):
        """
        Get all holdings for the user

        Args:
            update_mtm: bool - Whether to update MTM with live prices

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            holdings = SandboxHoldings.query.filter_by(user_id=self.user_id).all()

            if update_mtm:
                self._update_holdings_mtm(holdings)

            holdings_list = []
            total_pnl = Decimal('0.00')
            total_value = Decimal('0.00')
            total_investment = Decimal('0.00')

            for holding in holdings:
                pnl = Decimal(str(holding.pnl))
                total_pnl += pnl

                current_value = abs(holding.quantity) * holding.ltp if holding.ltp else Decimal('0.00')
                total_value += current_value

                investment_value = abs(holding.quantity) * holding.average_price
                total_investment += investment_value

                holdings_list.append({
                    'symbol': holding.symbol,
                    'exchange': holding.exchange,
                    'quantity': holding.quantity,
                    'average_price': float(holding.average_price),
                    'ltp': float(holding.ltp) if holding.ltp else 0.0,
                    'pnl': float(pnl),
                    'pnl_percent': float(holding.pnl_percent),
                    'current_value': float(current_value),
                    'settlement_date': holding.settlement_date.strftime('%Y-%m-%d')
                })

            # Calculate overall P&L percentage
            pnl_percent = (total_pnl / total_investment * 100) if total_investment > 0 else Decimal('0.00')

            return True, {
                'status': 'success',
                'data': {
                    'holdings': holdings_list,
                    'statistics': {
                        'totalholdingvalue': float(total_value),
                        'totalinvvalue': float(total_investment),
                        'totalprofitandloss': float(total_pnl),
                        'totalpnlpercentage': float(pnl_percent)
                    }
                },
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error getting holdings for user {self.user_id}: {e}")
            return False, {
                'status': 'error',
                'message': f'Error getting holdings: {str(e)}',
                'mode': 'analyze'
            }, 500

    def process_t1_settlement(self):
        """
        Process T+1 settlement - move CNC positions to holdings
        Should be called daily after market close
        """
        try:
            ist = pytz.timezone('Asia/Kolkata')
            today = datetime.now(ist).date()
            yesterday = today - timedelta(days=1)

            # Get all CNC positions from yesterday or earlier
            cnc_positions = SandboxPositions.query.filter_by(
                user_id=self.user_id,
                product='CNC'
            ).filter(
                SandboxPositions.created_at < datetime.combine(today, datetime.min.time()).replace(tzinfo=ist)
            ).all()

            if not cnc_positions:
                logger.debug(f"No CNC positions to settle for user {self.user_id}")
                return True, "No positions to settle"

            settled_count = 0

            for position in cnc_positions:
                # Check if holding already exists
                holding = SandboxHoldings.query.filter_by(
                    user_id=self.user_id,
                    symbol=position.symbol,
                    exchange=position.exchange
                ).first()

                if holding:
                    # Update existing holding
                    # Calculate new average price
                    total_value = (abs(holding.quantity) * holding.average_price) + \
                                  (abs(position.quantity) * position.average_price)
                    total_quantity = abs(holding.quantity) + abs(position.quantity)

                    if position.quantity > 0:
                        # Adding to holding
                        holding.quantity += position.quantity
                    else:
                        # Reducing holding (selling from holdings)
                        holding.quantity += position.quantity

                    # Only update average price if we're adding (not selling)
                    if position.quantity > 0:
                        holding.average_price = total_value / total_quantity if total_quantity > 0 else holding.average_price

                    holding.ltp = position.ltp
                    holding.updated_at = datetime.now(ist)

                    logger.info(f"Updated holding: {position.symbol}, New qty: {holding.quantity}")

                else:
                    # Create new holding
                    holding = SandboxHoldings(
                        user_id=self.user_id,
                        symbol=position.symbol,
                        exchange=position.exchange,
                        quantity=position.quantity,
                        average_price=position.average_price,
                        ltp=position.ltp or position.average_price,
                        pnl=Decimal('0.00'),
                        pnl_percent=Decimal('0.00'),
                        settlement_date=today,
                        created_at=datetime.now(ist)
                    )
                    db_session.add(holding)
                    logger.info(f"Created new holding: {position.symbol}, Qty: {position.quantity}")

                # Delete the position after settling
                db_session.delete(position)
                settled_count += 1

            db_session.commit()

            logger.info(f"Settled {settled_count} CNC positions for user {self.user_id}")
            return True, f"Settled {settled_count} positions"

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error processing T+1 settlement for user {self.user_id}: {e}")
            return False, f"Settlement error: {str(e)}"

    def _update_holdings_mtm(self, holdings):
        """Update MTM for all holdings with live quotes"""
        try:
            if not holdings:
                return

            # Get unique symbols
            symbols_to_fetch = set()
            for holding in holdings:
                symbols_to_fetch.add((holding.symbol, holding.exchange))

            # Fetch quotes for all symbols
            quote_cache = {}
            for symbol, exchange in symbols_to_fetch:
                quote = self._fetch_quote(symbol, exchange)
                if quote:
                    quote_cache[(symbol, exchange)] = quote

            # Update MTM for each holding
            for holding in holdings:
                quote = quote_cache.get((holding.symbol, holding.exchange))
                if quote:
                    ltp = Decimal(str(quote.get('ltp', 0)))
                    if ltp > 0:
                        holding.ltp = ltp
                        holding.pnl = self._calculate_holding_pnl(
                            holding.quantity,
                            holding.average_price,
                            ltp
                        )
                        holding.pnl_percent = self._calculate_pnl_percent(
                            holding.average_price,
                            ltp
                        )

            db_session.commit()

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating holdings MTM: {e}")

    def _calculate_holding_pnl(self, quantity, avg_price, ltp):
        """Calculate P&L for a holding"""
        try:
            quantity = Decimal(str(quantity))
            avg_price = Decimal(str(avg_price))
            ltp = Decimal(str(ltp))

            # Holdings are always long positions
            pnl = (ltp - avg_price) * abs(quantity)

            return pnl

        except Exception as e:
            logger.error(f"Error calculating holding P&L: {e}")
            return Decimal('0.00')

    def _calculate_pnl_percent(self, avg_price, ltp):
        """Calculate P&L percentage"""
        try:
            avg_price = Decimal(str(avg_price))
            ltp = Decimal(str(ltp))

            if avg_price <= 0:
                return Decimal('0.00')

            pnl_percent = ((ltp - avg_price) / avg_price) * Decimal('100')

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
                return None

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None


def process_all_t1_settlements():
    """Process T+1 settlement for all users"""
    try:
        # Get all unique users with CNC positions
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).date()

        positions = SandboxPositions.query.filter_by(product='CNC').filter(
            SandboxPositions.created_at < datetime.combine(today, datetime.min.time()).replace(tzinfo=ist)
        ).all()

        if not positions:
            logger.info("No CNC positions to settle")
            return

        users = set(p.user_id for p in positions)
        logger.info(f"Processing T+1 settlement for {len(users)} users")

        settled_users = 0
        for user_id in users:
            hm = HoldingsManager(user_id)
            success, message = hm.process_t1_settlement()
            if success:
                settled_users += 1

        logger.info(f"T+1 settlement completed for {settled_users} users")

    except Exception as e:
        logger.error(f"Error processing all T+1 settlements: {e}")


if __name__ == '__main__':
    """Run T+1 settlement processor"""
    logger.info("Starting T+1 Settlement Processor")

    from database.sandbox_db import init_db
    init_db()

    process_all_t1_settlements()
    logger.info("T+1 settlement processing completed")
