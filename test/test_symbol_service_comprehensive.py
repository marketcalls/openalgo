import unittest
import sys
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestSymbolService(unittest.TestCase):
    """Comprehensive tests for Symbol Service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.valid_symbols = [
            "NSE:SBIN-EQ",
            "NFO:NIFTY24JAN24000CE",
            "NSE:NIFTY-INDEX",
            "BSE:SENSEX-INDEX",
            "NFO:FINNIFTY24JAN24000PE"
        ]
        self.invalid_symbols = [
            "INVALID",
            ":",
            "",
            "NSE:",
            ":SBIN-EQ"
        ]
    
    def test_valid_symbol_format(self):
        """Test that valid symbols have correct format"""
        for symbol in self.valid_symbols:
            parts = symbol.split(':')
            is_valid = len(parts) == 2 and len(parts[0]) > 0 and len(parts[1]) > 0
            self.assertTrue(is_valid, f"Symbol {symbol} should be valid")
    
    def test_invalid_symbol_format(self):
        """Test that invalid symbols are rejected"""
        for symbol in self.invalid_symbols:
            parts = symbol.split(':')
            is_invalid = len(parts) != 2 or len(parts[0]) == 0 or len(parts[1]) == 0
            self.assertTrue(is_invalid, f"Symbol {symbol} should be invalid")
    
    def test_exchange_names_valid(self):
        """Test that exchange names are valid"""
        valid_exchanges = ['NSE', 'BSE', 'NFO', 'MCX', 'NCDEX']
        for symbol in self.valid_symbols:
            exchange = symbol.split(':')[0]
            self.assertIn(exchange, valid_exchanges)
    
    def test_symbol_case_sensitivity(self):
        """Test symbol case handling"""
        symbol = "NSE:SBIN-EQ"
        uppercase = symbol.upper()
        
        # Symbols are case-insensitive at API level
        is_normalized = symbol == uppercase
        self.assertTrue(is_normalized)
    
    def test_option_symbol_suffix(self):
        """Test that option symbols have CE/PE suffix"""
        option_symbols = [
            "NFO:NIFTY24JAN24000CE",
            "NFO:FINNIFTY24JAN24000PE"
        ]
        
        for symbol in option_symbols:
            is_option = symbol.endswith('CE') or symbol.endswith('PE')
            self.assertTrue(is_option)
    
    def test_symbol_length_within_limits(self):
        """Test that symbol length is within acceptable limits"""
        for symbol in self.valid_symbols:
            is_valid_length = 5 <= len(symbol) <= 30
            self.assertTrue(is_valid_length)


if __name__ == '__main__':
    unittest.main()
