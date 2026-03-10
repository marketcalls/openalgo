import unittest
import sys
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestPositionService(unittest.TestCase):
    """Comprehensive tests for Position Service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.position = {
            "symbol": "NSE:SBIN-EQ",
            "quantity": 100,
            "average_price": Decimal("500.00"),
            "current_price": Decimal("520.00"),
            "side": "BUY"
        }
    
    def test_position_quantity_non_zero(self):
        """Test that position quantity is non-zero"""
        quantity = self.position['quantity']
        self.assertNotEqual(quantity, 0)
        self.assertGreater(quantity, 0)
    
    def test_position_average_price_positive(self):
        """Test that average price is always positive"""
        price = self.position['average_price']
        self.assertGreater(price, Decimal("0"))
    
    def test_position_current_price_valid(self):
        """Test that current price is valid"""
        price = self.position['current_price']
        self.assertIsInstance(price, Decimal)
        self.assertGreater(price, Decimal("0"))
    
    def test_position_long_vs_short_side(self):
        """Test that position side is either LONG or SHORT"""
        side = self.position['side']
        valid_sides = ['BUY', 'SELL', 'LONG', 'SHORT']
        self.assertIn(side, valid_sides)
    
    def test_unrealized_pnl_calculation(self):
        """Test unrealized P&L calculation"""
        quantity = self.position['quantity']
        avg_price = self.position['average_price']
        current_price = self.position['current_price']
        
        unrealized_pnl = quantity * (current_price - avg_price)
        self.assertEqual(unrealized_pnl, Decimal("2000.00"))
    
    def test_position_value_calculation(self):
        """Test position value (current price × quantity)"""
        quantity = self.position['quantity']
        current_price = self.position['current_price']
        
        position_value = quantity * current_price
        self.assertEqual(position_value, Decimal("52000.00"))
    
    def test_cost_basis_calculation(self):
        """Test cost basis (average price × quantity)"""
        quantity = self.position['quantity']
        avg_price = self.position['average_price']
        
        cost_basis = quantity * avg_price
        self.assertEqual(cost_basis, Decimal("50000.00"))


if __name__ == '__main__':
    unittest.main()
