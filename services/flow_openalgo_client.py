# services/flow_openalgo_client.py
"""
OpenAlgo Client Wrapper for Flow
Provides SDK-like interface using internal OpenAlgo services
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

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

    def _handle_response(
        self, success: bool, response: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
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
            # Return all response fields, ensuring status is set
            result = {"status": "success"}
            for key, value in response.items():
                if key != "status":
                    result[key] = value
            return result
        else:
            return {
                "status": "error",
                "error": response.get("message", "Unknown error"),
                "code": status_code,
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
        strategy: str = "flow_workflow",
    ) -> dict[str, Any]:
        """Place a regular order"""
        from services.place_order_service import place_order

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": quantity,
            "pricetype": price_type,  # Schema expects 'pricetype' (no underscore)
            "product": product_type,  # Schema expects 'product' not 'product_type'
            "price": price,
            "trigger_price": trigger_price,
            "disclosed_quantity": disclosed_quantity,
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
        strategy: str = "flow_workflow",
    ) -> dict[str, Any]:
        """Place a smart order with position management"""
        from services.place_smart_order_service import place_smart_order

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": quantity,
            "position_size": position_size,
            "pricetype": price_type,  # Schema expects 'pricetype' (no underscore)
            "product": product_type,  # Schema expects 'product' not 'product_type'
            "price": price,
            "trigger_price": trigger_price,
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
        strategy: str = "flow_workflow",
    ) -> dict[str, Any]:
        """Modify an existing order"""
        from services.modify_order_service import modify_order

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "orderid": order_id,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": quantity,
            "pricetype": price_type,  # Schema expects 'pricetype' (no underscore)
            "product": product_type,  # Schema expects 'product' not 'product_type'
            "price": price,
            "trigger_price": trigger_price,
            "disclosed_quantity": disclosed_quantity,
        }

        success, response, status_code = modify_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def cancel_order(self, order_id: str, strategy: str = "flow_workflow") -> dict[str, Any]:
        """Cancel an order by order ID"""
        from services.cancel_order_service import cancel_order

        # cancel_order service expects orderid as first param (string), not a dict
        success, response, status_code = cancel_order(order_id, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel all open orders"""
        from services.cancel_all_order_service import cancel_all_orders

        success, response, status_code = cancel_all_orders(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def close_all_positions(self) -> dict[str, Any]:
        """Close all open positions (square off all)"""
        from services.close_position_service import close_position

        # close_position service closes ALL positions when called with just api_key
        success, response, status_code = close_position(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def close_position(
        self, symbol: str, exchange: str, product_type: str = "MIS", strategy: str = "flow_workflow"
    ) -> dict[str, Any]:
        """Close a position"""
        from services.close_position_service import close_position

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "product": product_type,  # Service expects 'product' not 'product_type'
        }

        success, response, status_code = close_position(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def basket_order(
        self, orders: list[dict[str, Any]], strategy: str = "flow_workflow"
    ) -> dict[str, Any]:
        """
        Place basket of orders.

        Args:
            orders: List of order dicts with symbol, exchange, action, quantity, etc.
            strategy: Strategy name for tracking
        """
        from services.basket_order_service import place_basket_order

        basket_data = {"strategy": strategy, "orders": orders}

        success, response, status_code = place_basket_order(basket_data, api_key=self.api_key)
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
        strategy: str = "flow_workflow",
    ) -> dict[str, Any]:
        """Place a split order"""
        from services.split_order_service import split_order

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": quantity,
            "splitsize": split_size,
            "pricetype": price_type,  # Schema expects 'pricetype' (no underscore)
            "product": product_type,  # Schema expects 'product' not 'product_type'
            "price": price,
            "trigger_price": trigger_price,
        }

        success, response, status_code = split_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Market Data Operations ---

    def get_quotes(self, symbol: str, exchange: str) -> dict[str, Any]:
        """Get real-time quotes for a symbol"""
        from services.quotes_service import get_quotes

        success, response, status_code = get_quotes(symbol, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_depth(self, symbol: str, exchange: str) -> dict[str, Any]:
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
        end_date: str = None,
    ) -> dict[str, Any]:
        """Get historical data for a symbol"""
        from services.history_service import get_history

        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=self.api_key,
        )
        return self._handle_response(success, response, status_code)

    # --- Account Operations ---

    def orderbook(self) -> dict[str, Any]:
        """Get order book"""
        from services.orderbook_service import get_orderbook

        success, response, status_code = get_orderbook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def tradebook(self) -> dict[str, Any]:
        """Get trade book"""
        from services.tradebook_service import get_tradebook

        success, response, status_code = get_tradebook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def positionbook(self) -> dict[str, Any]:
        """Get position book"""
        from services.positionbook_service import get_positionbook

        success, response, status_code = get_positionbook(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def holdings(self) -> dict[str, Any]:
        """Get holdings"""
        from services.holdings_service import get_holdings

        success, response, status_code = get_holdings(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def funds(self) -> dict[str, Any]:
        """Get account funds"""
        from services.funds_service import get_funds

        success, response, status_code = get_funds(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_open_position(
        self, symbol: str, exchange: str, product_type: str = None
    ) -> dict[str, Any]:
        """Get open position for a specific symbol.
        Returns quantity matching standard OpenAlgo API response.
        """
        result = self.positionbook()
        if result.get("status") != "success":
            return result

        positions = result.get("data", [])
        if not positions:
            return {"status": "success", "quantity": 0}

        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("exchange") == exchange:
                # Check both 'product' and 'product_type' for compatibility
                pos_product = pos.get("product") or pos.get("product_type")
                if product_type and pos_product != product_type:
                    continue
                return {"status": "success", "quantity": pos.get("quantity", 0)}

        return {"status": "success", "quantity": 0}

    # --- Options Operations ---

    def optionchain(
        self, underlying: str, exchange: str, expiry_date: str = "", strike_count: int = 10
    ) -> dict[str, Any]:
        """Get option chain data"""
        from services.option_chain_service import get_option_chain

        success, response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
            api_key=self.api_key,
        )
        return self._handle_response(success, response, status_code)

    def optionsymbol(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str,
        offset: str = "ATM",
        option_type: str = "CE",
    ) -> dict[str, Any]:
        """Get option symbol resolved from underlying/expiry/offset"""
        from services.option_symbol_service import get_option_symbol

        success, response, status_code = get_option_symbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_int=None,
            offset=offset,
            option_type=option_type,
            api_key=self.api_key,
        )
        return self._handle_response(success, response, status_code)

    # --- Options Orders ---

    def options_order(
        self,
        underlying: str,
        exchange: str,
        action: str,
        quantity: int,
        expiry_date: str,
        offset: str,
        option_type: str,
        price_type: str = "MARKET",
        product: str = "NRML",
        price: float = 0,
        splitsize: int = 0,
        strategy: str = "flow_workflow",
    ) -> dict[str, Any]:
        """Place an options order with ATM/ITM/OTM offset resolution

        Args:
            underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            exchange: Exchange for underlying (NSE_INDEX, BSE_INDEX)
            action: BUY or SELL
            quantity: Total quantity
            expiry_date: Expiry date (e.g., 27JAN26)
            offset: Strike offset (ATM, ITM1-ITM50, OTM1-OTM50)
            option_type: CE or PE
            price_type: MARKET, LIMIT, SL, SL-M
            product: NRML, MIS
            price: Price for limit orders
            splitsize: Split large orders into smaller chunks (0 = no split)
            strategy: Strategy name for tracking
        """
        from services.place_options_order_service import place_options_order

        order_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "underlying": underlying,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": quantity,
            "expiry_date": expiry_date,
            "offset": offset,
            "option_type": option_type.upper(),
            "pricetype": price_type,
            "product": product,
            "price": price,
            "splitsize": splitsize,
        }

        success, response, status_code = place_options_order(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def options_multi_order(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str,
        legs: list[dict[str, Any]],
        strategy: str = "flow_workflow",
        strike_int: int = None,
    ) -> dict[str, Any]:
        """
        Place multiple option legs with common underlying.
        BUY legs are executed first for margin efficiency.

        Args:
            underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            exchange: Exchange for underlying (NSE_INDEX, BSE_INDEX)
            expiry_date: Expiry date (e.g., 27JAN26)
            legs: List of leg dicts with offset, option_type, action, quantity, etc.
            strategy: Strategy name for tracking
            strike_int: Optional specific strike price (overrides offset)
        """
        from services.options_multiorder_service import place_options_multiorder

        multiorder_data = {
            "apikey": self.api_key,
            "strategy": strategy,
            "underlying": underlying,
            "exchange": exchange,
            "expiry_date": expiry_date,
            "strike_int": strike_int,
            "legs": legs,
        }

        success, response, status_code = place_options_multiorder(
            multiorder_data, api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    # --- Market Calendar ---

    def holidays(self, exchange: str = "NSE") -> dict[str, Any]:
        """Get market holidays"""
        from services.market_calendar_service import get_holidays

        success, response, status_code = get_holidays(exchange=exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def timings(self, exchange: str = "NSE") -> dict[str, Any]:
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
        price_type: str = "MARKET",
    ) -> dict[str, Any]:
        """Get margin required for an order"""
        from services.margin_service import get_margin

        order_data = {
            "symbol": symbol,
            "exchange": exchange,
            "quantity": str(quantity),  # Schema expects string
            "price": str(price),  # Schema expects string
            "product": product_type,  # Schema expects 'product' not 'product_type'
            "pricetype": price_type,  # Schema expects 'pricetype' (no underscore)
            "action": action.upper(),
        }

        success, response, status_code = get_margin(order_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    # --- Alerts ---

    def telegram(self, message: str) -> dict[str, Any]:
        """Send a Telegram alert using existing telegram_alert_service"""
        from datetime import datetime

        from database.telegram_db import get_telegram_user_by_username
        from services.telegram_alert_service import telegram_alert_service

        try:
            # Get username from API key
            from database.auth_db import verify_api_key

            username = verify_api_key(self.api_key)
            if not username:
                return {"status": "error", "error": "Invalid API key"}

            # Get telegram user by username
            telegram_user = get_telegram_user_by_username(username)
            if not telegram_user:
                logger.info(f"No telegram user linked for username: {username}")
                return {
                    "status": "error",
                    "error": f"No Telegram account linked for user: {username}",
                }

            if not telegram_user.get("notifications_enabled"):
                logger.info(f"Notifications disabled for telegram user: {username}")
                return {"status": "error", "error": "Telegram notifications are disabled"}

            telegram_id = telegram_user["telegram_id"]

            # Format the message with timestamp
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_message = (
                f"📢 *Flow Alert*\n─────────────────────\n{message}\n\n⏰ Time: {timestamp}"
            )

            # Send alert using existing send_alert_sync method
            from concurrent.futures import ThreadPoolExecutor

            alert_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow_telegram")
            alert_executor.submit(
                telegram_alert_service.send_alert_sync, telegram_id, formatted_message
            )

            return {"status": "success", "data": {"message": "Alert queued successfully"}}

        except Exception as e:
            logger.exception(f"Error sending Telegram alert: {e}")
            return {"status": "error", "error": str(e)}

    # --- Additional Data Services ---

    def get_multi_quotes(self, symbols: list[dict[str, str]]) -> dict[str, Any]:
        """Get quotes for multiple symbols"""
        from services.quotes_service import get_multiquotes

        success, response, status_code = get_multiquotes(symbols, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Get status of a specific order"""
        from services.orderstatus_service import get_order_status

        status_data = {"orderid": order_id}
        success, response, status_code = get_order_status(status_data, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def symbol(self, symbol: str, exchange: str) -> dict[str, Any]:
        """Get symbol info (lotsize, tick_size, expiry, etc.)"""
        from services.symbol_service import get_symbol_info

        success, response, status_code = get_symbol_info(symbol, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_intervals(self) -> dict[str, Any]:
        """Get supported intervals for the broker"""
        from services.intervals_service import get_intervals

        success, response, status_code = get_intervals(api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def search_symbols(self, query: str, exchange: str = None) -> dict[str, Any]:
        """Search for symbols"""
        from services.search_service import search_symbols

        success, response, status_code = search_symbols(query, exchange, api_key=self.api_key)
        return self._handle_response(success, response, status_code)

    def get_expiry(
        self, symbol: str, exchange: str, instrumenttype: str = "options"
    ) -> dict[str, Any]:
        """Get expiry dates for F&O symbols"""
        from services.expiry_service import get_expiry_dates

        success, response, status_code = get_expiry_dates(
            symbol, exchange, instrumenttype, api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    def syntheticfuture(self, underlying: str, exchange: str, expiry_date: str) -> dict[str, Any]:
        """Calculate synthetic future price using ATM options"""
        from services.synthetic_future_service import calculate_synthetic_future

        success, response, status_code = calculate_synthetic_future(
            underlying=underlying, exchange=exchange, expiry_date=expiry_date, api_key=self.api_key
        )
        return self._handle_response(success, response, status_code)

    def get_option_greeks(
        self,
        symbol: str,
        exchange: str,
        underlying_symbol: str = None,
        underlying_exchange: str = None,
        interest_rate: float = 0.0,
    ) -> dict[str, Any]:
        """Get option greeks (Delta, Gamma, Theta, Vega, Rho) and IV"""
        from services.option_greeks_service import get_option_greeks

        success, response, status_code = get_option_greeks(
            option_symbol=symbol,
            exchange=exchange,
            interest_rate=interest_rate,
            underlying_symbol=underlying_symbol,
            underlying_exchange=underlying_exchange,
            api_key=self.api_key,
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
