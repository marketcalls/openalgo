from breeze_connect import BreezeConnect
from broker.icici.api.auth_api import login_breeze
import logging
import os

logger = logging.getLogger(__name__)

class ICICIBrokerData:
    def __init__(self, api_key: str, api_secret: str, totp: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.totp = totp
        self.breeze = BreezeConnect(api_key=api_key)

        # Login and create session
        session = self.breeze.generate_session(api_secret=api_secret)
        if totp:
            self.breeze.set_totp(totp)

        self.breeze.get_master_contract('NSE')

    def get_quotes(self, symbol: str, exchange: str = "NSE") -> dict:
        """
        Get real-time quote for a symbol from Breeze
        """
        try:
            response = self.breeze.get_quotes(stock_code=symbol, exchange_code=exchange, product_type="cash")
            quote = response.get("Success", {})
            return {
                "ltp": float(quote.get("last_traded_price", 0)),
                "open": float(quote.get("open", 0)),
                "high": float(quote.get("high", 0)),
                "low": float(quote.get("low", 0)),
                "close": float(quote.get("close", 0)),
                "volume": int(quote.get("volume", 0)),
                "bid": float(quote.get("best_bid_price", 0)),
                "ask": float(quote.get("best_offer_price", 0))
            }
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {str(e)}")
            return {
                "ltp": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 0,
                "volume": 0,
                "bid": 0,
                "ask": 0,
                "error": str(e)
            }

    def get_depth(self, symbol: str, exchange: str = "NSE") -> dict:
        """
        ICICI Breeze API currently does not support full market depth.
        We'll mimic 1-level bid/ask for compatibility.
        """
        quote = self.get_quotes(symbol, exchange)
        return {
            "bids": [{"price": quote["bid"], "quantity": 0}],
            "asks": [{"price": quote["ask"], "quantity": 0}],
            "ltp": quote["ltp"],
            "volume": quote["volume"],
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "prev_close": quote.get("close", 0),
            "error": quote.get("error")
        }

    # Optional: Add historical data method if Breeze API supports it
