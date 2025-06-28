from breeze_connect import BreezeConnect
import logging

logger = logging.getLogger(__name__)


class ICICIOrderAPI:
    def __init__(self, api_key: str, api_secret: str, totp: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.totp = totp
        self.breeze = BreezeConnect(api_key=api_key)

        # Authenticate session
        self.breeze.generate_session(api_secret=api_secret)
        if totp:
            self.breeze.set_totp(totp)

    def place_order(self, symbol: str, exchange: str, action: str, quantity: int, order_type: str = "market",
                    product_type: str = "cash", price: float = 0.0) -> dict:
        """
        Place an order via Breeze API
        """
        try:
            logger.info(f"Placing order: {action} {quantity} {symbol} on {exchange}")
            order = self.breeze.place_order(
                stock_code=symbol,
                exchange_code=exchange,
                action=action.upper(),  # BUY or SELL
                order_type=order_type.lower(),  # market or limit
                quantity=quantity,
                price=price if order_type.lower() == "limit" else 0,
                product_type=product_type,
                validity="day"
            )
            return {"status": "success", "data": order}
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return {"status": "error", "error": str(e)}

    def get_order_book(self) -> dict:
        try:
            return self.breeze.get_order_list()
        except Exception as e:
            logger.error(f"Error fetching order book: {str(e)}")
            return {"error": str(e)}

    def get_trade_book(self) -> dict:
        try:
            return self.breeze.get_trade_list()
        except Exception as e:
            logger.error(f"Error fetching trade book: {str(e)}")
            return {"error": str(e)}

    def get_positions(self) -> dict:
        try:
            return self.breeze.get_positions()
        except Exception as e:
            logger.error(f"Error fetching positions: {str(e)}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        try:
            cancel_resp = self.breeze.cancel_order(order_id=order_id)
            return {"status": "success", "data": cancel_resp}
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            return {"status": "error", "error": str(e)}

    def close_all_positions(self) -> list:
        try:
            positions = self.get_positions()
            if isinstance(positions, dict) and "error" in positions:
                return positions

            closed = []
            for pos in positions:
                qty = int(pos.get("quantity", 0))
                if qty == 0:
                    continue
                symbol = pos.get("stock_code")
                exchange = pos.get("exchange_code")
                action = "SELL" if qty > 0 else "BUY"
                qty = abs(qty)

                result = self.place_order(symbol, exchange, action, qty)
                closed.append(result)
            return closed
        except Exception as e:
            logger.error(f"Error closing all positions: {str(e)}")
            return {"error": str(e)}
