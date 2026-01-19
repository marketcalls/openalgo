# services/flow_openalgo_client.py
"""
OpenAlgo Client Wrapper for Flow
Provides SDK-like interface using internal OpenAlgo services
"""

from typing import Dict, Any, Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


class FlowOpenAlgoClient:
    """
    Client wrapper that provides SDK-like interface to OpenAlgo services.
    Used by Flow workflow executor to interact with trading functionality.
    """

    def __init__(self, api_key: str):
        """
        Initialize the client with an API key.

        Args:
            api_key: The OpenAlgo API key for authentication
        """
        self.api_key = api_key

    def _handle_response(self, success: bool, response: Dict[str, Any], status_code: int) -> Dict[str, Any]:
        """
        Convert service response to SDK-like format.

        Args:
            success: Whether the operation succeeded
            response: Response data from the service
            status_code: HTTP status code

        Returns:
            Dictionary with 'status' and relevant data
        """
        if success:
            # Return the response directly - it already has the right format
            # Ensure status is set and orderid is at top level if present
            result = {
                'status': 'success',
                'orderid': response.get('orderid')
            }
            # Add any additional data fields (excluding status to avoid nesting)
            if 'data' in response:
                result['data'] = response['data']
            # Copy other useful fields like 'message', 'results', etc.
            for key in ['message', 'results', 'mode']:
                if key in response:
                    result[key] = response[key]
            return result
        else:
            return {
                'status': 'error',
                'error': response.get('message', 'Unknown error'),
                'code': status_code
            }

    # --- Order Operations ---

    def place_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0,
        trigger_price: float = 0,
        disclosed_quantity: int = 0,
        strategy: str = "flow_workflow"
    ) -> Dict[str, Any]:
        """Place a regular order"""
        from services.place_order_service import place_order

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'symbol': symbol,
            'exchange': exchange,
            'action': action.upper(),
            'quantity': quantity,
            'pricetype': price_type,  # Schema expects 'pricetype' (no underscore)
            'product': product_type,  # Schema expects 'product' not 'product_type'
            'price': price,
            'trigger_price': trigger_price,
            'disclosed_quantity': disclosed_quantity
        }

        success, response, status_code = place_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def place_smart_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        position_size: int = 0,
        price_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0,
        trigger_price: float = 0,
        strategy: str = "flow_workflow"
    ) -> Dict[str, Any]:
        """Place a smart order with position management"""
        from services.place_smart_order_service import place_smart_order

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'symbol': symbol,
            'exchange': exchange,
            'action': action.upper(),
            'quantity': quantity,
            'position_size': position_size,
            'pricetype': price_type,  # Schema expects 'pricetype' (no underscore)
            'product': product_type,  # Schema expects 'product' not 'product_type'
            'price': price,
            'trigger_price': trigger_price
        }

        success, response, status_code = place_smart_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def modify_order(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0,
        trigger_price: float = 0,
        disclosed_quantity: int = 0,
        strategy: str = "flow_workflow"
    ) -> Dict[str, Any]:
        """Modify an existing order"""
        from services.modify_order_service import modify_order

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'orderid': order_id,
            'symbol': symbol,
            'exchange': exchange,
            'action': action.upper(),
            'quantity': quantity,
            'pricetype': price_type,  # Schema expects 'pricetype' (no underscore)
            'product': product_type,  # Schema expects 'product' not 'product_type'
            'price': price,
            'trigger_price': trigger_price,
            'disclosed_quantity': disclosed_quantity
        }

        success, response, status_code = modify_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def cancel_order(self, order_id: str, strategy: str = "flow_workflow") -> Dict[str, Any]:
        """Cancel an order"""
        from services.cancel_order_service import cancel_order

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'orderid': order_id
        }
        success, response, status_code = cancel_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders"""
        from services.cancel_all_order_service import cancel_all_orders

        success, response, status_code = cancel_all_orders(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def close_position(
        self,
        symbol: str,
        exchange: str,
        product_type: str = "MIS",
        strategy: str = "flow_workflow"
    ) -> Dict[str, Any]:
        """Close a position"""
        from services.close_position_service import close_position

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'symbol': symbol,
            'exchange': exchange,
            'product': product_type  # Service expects 'product' not 'product_type'
        }

        success, response, status_code = close_position(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def basket_order(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Place basket of orders"""
        from services.basket_order_service import basket_order

        success, response, status_code = basket_order(orders, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def split_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        split_size: int,
        price_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0,
        trigger_price: float = 0,
        strategy: str = "flow_workflow"
    ) -> Dict[str, Any]:
        """Place a split order"""
        from services.split_order_service import split_order

        order_data = {
            'apikey': self.api_key,
            'strategy': strategy,
            'symbol': symbol,
            'exchange': exchange,
            'action': action.upper(),
            'quantity': quantity,
            'splitsize': split_size,
            'pricetype': price_type,  # Schema expects 'pricetype' (no underscore)
            'product': product_type,  # Schema expects 'product' not 'product_type'
            'price': price,
            'trigger_price': trigger_price
        }

        success, response, status_code = split_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Market Data Operations ---

    def get_quotes(self, symbol: str, exchange: str) -> Dict[str, Any]:
        """Get real-time quotes for a symbol"""
        from services.quotes_service import get_quotes

        success, response, status_code = get_quotes(symbol, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_depth(self, symbol: str, exchange: str) -> Dict[str, Any]:
        """Get market depth for a symbol"""
        from services.depth_service import get_depth

        success, response, status_code = get_depth(symbol, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, Any]:
        """Get historical data for a symbol"""
        from services.history_service import get_history

        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    # --- Account Operations ---

    def orderbook(self) -> Dict[str, Any]:
        """Get order book"""
        from services.orderbook_service import get_orderbook

        success, response, status_code = get_orderbook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def tradebook(self) -> Dict[str, Any]:
        """Get trade book"""
        from services.tradebook_service import get_tradebook

        success, response, status_code = get_tradebook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def positionbook(self) -> Dict[str, Any]:
        """Get position book"""
        from services.positionbook_service import get_positionbook

        success, response, status_code = get_positionbook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def holdings(self) -> Dict[str, Any]:
        """Get holdings"""
        from services.holdings_service import get_holdings

        success, response, status_code = get_holdings(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def funds(self) -> Dict[str, Any]:
        """Get account funds"""
        from services.funds_service import get_funds

        success, response, status_code = get_funds(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_open_position(self, symbol: str, exchange: str, product_type: str = None) -> Dict[str, Any]:
        """Get open position for a specific symbol"""
        result = self.positionbook()
        if result.get('status') != 'success':
            return result

        positions = result.get('data', [])
        if not positions:
            return {'status': 'success', 'data': None}

        for pos in positions:
            if pos.get('symbol') == symbol and pos.get('exchange') == exchange:
                # Check both 'product' and 'product_type' for compatibility
                pos_product = pos.get('product') or pos.get('product_type')
                if product_type and pos_product != product_type:
                    continue
                return {'status': 'success', 'data': pos}

        return {'status': 'success', 'data': None}

    # --- Options Operations ---

    def optionchain(
        self,
        symbol: str,
        exchange: str,
        expiry: str = None,
        strike_price: float = None
    ) -> Dict[str, Any]:
        """Get option chain data"""
        from services.option_chain_service import get_option_chain

        success, response, status_code = get_option_chain(
            symbol=symbol,
            exchange=exchange,
            expiry=expiry,
            strike_price=strike_price,
            api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    def optionsymbol(
        self,
        symbol: str,
        exchange: str,
        expiry: str,
        option_type: str,
        strike_price: float
    ) -> Dict[str, Any]:
        """Get option symbol"""
        from services.option_symbol_service import get_option_symbol

        success, response, status_code = get_option_symbol(
            symbol=symbol,
            exchange=exchange,
            expiry=expiry,
            option_type=option_type,
            strike_price=strike_price,
            api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    # --- Options Orders ---

    def options_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        expiry: str,
        option_type: str,
        strike_price: float,
        price_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0
    ) -> Dict[str, Any]:
        """Place an options order"""
        from services.place_options_order_service import place_options_order

        order_data = {
            'symbol': symbol,
            'exchange': exchange,
            'action': action.upper(),
            'quantity': quantity,
            'expiry': expiry,
            'option_type': option_type,
            'strike_price': strike_price,
            'pricetype': price_type,  # Service expects 'pricetype' (no underscore) for options
            'product': product_type,  # Service expects 'product' not 'product_type'
            'price': price
        }

        success, response, status_code = place_options_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def options_multi_order(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Place multiple options orders"""
        from services.options_multiorder_service import place_options_multi_order

        success, response, status_code = place_options_multi_order(orders, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Market Calendar ---

    def holidays(self, exchange: str = "NSE") -> Dict[str, Any]:
        """Get market holidays"""
        from services.market_calendar_service import get_holidays

        success, response, status_code = get_holidays(exchange=exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def timings(self, exchange: str = "NSE") -> Dict[str, Any]:
        """Get market timings"""
        from services.market_calendar_service import get_timings

        success, response, status_code = get_timings(exchange=exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Margin ---

    def margin(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: float = 0,
        product_type: str = "MIS",
        action: str = "BUY",
        price_type: str = "MARKET"
    ) -> Dict[str, Any]:
        """Get margin required for an order"""
        from services.margin_service import get_margin

        order_data = {
            'symbol': symbol,
            'exchange': exchange,
            'quantity': str(quantity),  # Schema expects string
            'price': str(price),  # Schema expects string
            'product': product_type,  # Schema expects 'product' not 'product_type'
            'pricetype': price_type,  # Schema expects 'pricetype' (no underscore)
            'action': action.upper()
        }

        success, response, status_code = get_margin(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Alerts ---

    def telegram(self, message: str) -> Dict[str, Any]:
        """Send a Telegram alert"""
        from services.telegram_alert_service import telegram_alert_service

        try:
            # Get username from API key
            from database.auth_db import verify_api_key
            username = verify_api_key(self.api_key)
            if not username:
                return {
                    'status': 'error',
                    'error': 'Invalid API key'
                }

            # Send custom alert
            result = telegram_alert_service.send_custom_alert(
                username=username,
                message=message
            )

            if result:
                return {
                    'status': 'success',
                    'data': {'message': 'Alert sent successfully'}
                }
            else:
                return {
                    'status': 'error',
                    'error': 'Failed to send Telegram alert'
                }
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    # --- Additional Data Services ---

    def get_multi_quotes(self, symbols: List[Dict[str, str]]) -> Dict[str, Any]:
        """Get quotes for multiple symbols"""
        from services.quotes_service import get_multiquotes

        success, response, status_code = get_multiquotes(symbols, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of a specific order"""
        from services.orderstatus_service import get_order_status

        status_data = {'orderid': order_id}
        success, response, status_code = get_order_status(status_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def symbol(self, symbol: str, exchange: str) -> Dict[str, Any]:
        """Get symbol info (lotsize, tick_size, expiry, etc.)"""
        from services.symbol_service import get_symbol_info

        success, response, status_code = get_symbol_info(symbol, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def search_symbols(self, query: str, exchange: str = None) -> Dict[str, Any]:
        """Search for symbols"""
        from services.search_service import search_symbols

        success, response, status_code = search_symbols(query, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_expiry(
        self,
        symbol: str,
        exchange: str,
        instrumenttype: str = "options"
    ) -> Dict[str, Any]:
        """Get expiry dates for F&O symbols"""
        from services.expiry_service import get_expiry_dates

        success, response, status_code = get_expiry_dates(symbol, exchange, instrumenttype, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def syntheticfuture(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str
    ) -> Dict[str, Any]:
        """Calculate synthetic future price using ATM options"""
        from services.synthetic_future_service import calculate_synthetic_future

        success, response, status_code = calculate_synthetic_future(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    def get_option_greeks(
        self,
        symbol: str,
        exchange: str,
        underlying_symbol: str = None,
        underlying_exchange: str = None,
        interest_rate: float = 0.0
    ) -> Dict[str, Any]:
        """Get option greeks (Delta, Gamma, Theta, Vega, Rho) and IV"""
        from services.option_greeks_service import get_option_greeks

        success, response, status_code = get_option_greeks(
            option_symbol=symbol,
            exchange=exchange,
            interest_rate=interest_rate,
            underlying_symbol=underlying_symbol,
            underlying_exchange=underlying_exchange,
            api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)


def get_flow_client(api_key: str) -> FlowOpenAlgoClient:
    """
    Factory function to create a Flow OpenAlgo client.

    Args:
        api_key: The OpenAlgo API key

    Returns:
        FlowOpenAlgoClient instance
    """
    return FlowOpenAlgoClient(api_key)
