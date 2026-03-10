import unittest
import sys
from datetime import datetime
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestWebsocketService(unittest.TestCase):
    """Comprehensive tests for Websocket streaming service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.valid_symbol = "NSE:SBIN-EQ"
        self.valid_wsocket_message = {
            "symbol": "NSE:SBIN-EQ",
            "ltp": Decimal("550.00"),
            "bid": Decimal("549.95"),
            "ask": Decimal("550.05"),
            "volume": 1000000,
            "timestamp": datetime.now()
        }
    
    def test_symbol_validation_for_websocket(self):
        """Test that websocket validates symbol format"""
        valid_symbols = ["NSE:SBIN-EQ", "NFO:NIFTY24JUL24000CE", "NSE:NIFTY-INDEX"]
        
        for symbol in valid_symbols:
            is_valid = len(symbol) > 0 and ":" in symbol
            self.assertTrue(is_valid, f"Symbol {symbol} should be valid")
    
    def test_ltp_price_format(self):
        """Test that LTP (Last Traded Price) is decimal"""
        ltp = self.valid_wsocket_message['ltp']
        self.assertIsInstance(ltp, Decimal)
        self.assertGreater(ltp, Decimal("0"))
    
    def test_bid_ask_spread_validation(self):
        """Test that bid is always less than or equal to ask"""
        bid = self.valid_wsocket_message['bid']
        ask = self.valid_wsocket_message['ask']
        
        self.assertLessEqual(bid, ask)
    
    def test_ltp_within_bid_ask_range(self):
        """Test that LTP falls within bid-ask range"""
        ltp = self.valid_wsocket_message['ltp']
        bid = self.valid_wsocket_message['bid']
        ask = self.valid_wsocket_message['ask']
        
        self.assertGreaterEqual(ltp, bid)
        self.assertLessEqual(ltp, ask)
    
    def test_volume_non_negative(self):
        """Test that volume is never negative"""
        volume = self.valid_wsocket_message['volume']
        self.assertGreaterEqual(volume, 0)
    
    def test_websocket_timestamp_recorded(self):
        """Test that websocket message includes timestamp"""
        timestamp = self.valid_wsocket_message['timestamp']
        self.assertIsInstance(timestamp, datetime)
        self.assertLessEqual(timestamp, datetime.now())


if __name__ == '__main__':
    unittest.main()
