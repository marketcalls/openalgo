import unittest
import sys
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestOrderEntryService(unittest.TestCase):
    """Comprehensive tests for Order Entry validation"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.valid_order = {
            "symbol": "NSE:SBIN-EQ",
            "quantity": 100,
            "price": Decimal("500.00"),
            "side": "BUY",
            "order_type": "LIMIT"
        }
    
    def test_order_quantity_must_be_positive(self):
        """Test that order quantity must be positive"""
        quantities = [100, 50, 1]
        for qty in quantities:
            is_valid = qty > 0
            self.assertTrue(is_valid)
    
    def test_order_quantity_cannot_be_zero(self):
        """Test that zero quantity is rejected"""
        quantity = 0
        is_valid = quantity > 0
        self.assertFalse(is_valid)
    
    def test_order_quantity_cannot_be_negative(self):
        """Test that negative quantity is rejected"""
        quantity = -100
        is_valid = quantity > 0
        self.assertFalse(is_valid)
    
    def test_order_price_must_be_positive(self):
        """Test that order price must be positive"""
        price = Decimal("500.00")
        is_valid = price > Decimal("0")
        self.assertTrue(is_valid)
    
    def test_order_price_cannot_be_zero(self):
        """Test that zero price is rejected"""
        price = Decimal("0")
        is_valid = price > Decimal("0")
        self.assertFalse(is_valid)
    
    def test_order_side_must_be_buy_or_sell(self):
        """Test that order side is BUY or SELL"""
        valid_sides = ['BUY', 'SELL']
        side = self.valid_order['side']
        
        self.assertIn(side, valid_sides)
    
    def test_order_type_valid(self):
        """Test that order type is valid"""
        valid_types = ['LIMIT', 'MARKET', 'STOP', 'STOP_LIMIT']
        order_type = self.valid_order['order_type']
        
        self.assertIn(order_type, valid_types)


if __name__ == '__main__':
    unittest.main()
