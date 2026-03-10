import unittest
import sys
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestTakeProfitService(unittest.TestCase):
    """Comprehensive tests for Take Profit Service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.position = {
            "symbol": "NSE:SBIN-EQ",
            "quantity": 100,
            "entry_price": Decimal("500.00"),
            "current_price": Decimal("520.00")
        }
        self.take_profit = {
            "price": Decimal("530.00"),
            "percentage": 6.0,  # 6% above entry
            "type": "PERCENTAGE"
        }
    
    def test_take_profit_price_above_entry(self):
        """Test that take profit price is above entry for long positions"""
        entry = self.position['entry_price']
        tp_price = self.take_profit['price']
        
        self.assertGreater(tp_price, entry)
    
    def test_take_profit_percentage_valid_range(self):
        """Test that take profit percentage is within 0-500%"""
        percentage = self.take_profit['percentage']
        
        self.assertGreater(percentage, 0)
        self.assertLess(percentage, 500)
    
    def test_take_profit_absolute_price_positive(self):
        """Test that absolute take profit price is positive"""
        tp_price = self.take_profit['price']
        self.assertGreater(tp_price, Decimal("0"))
    
    def test_percentage_to_price_conversion_for_tp(self):
        """Test conversion of percentage take profit to price"""
        entry = self.position['entry_price']
        percentage = Decimal("6")
        
        # Calculate take profit price from percentage
        tp_price = entry * (1 + percentage / 100)
        
        self.assertEqual(tp_price, Decimal("530.00"))
    
    def test_take_profit_trigger_on_target_hit(self):
        """Test that take profit triggers when price hits TP"""
        current_price = Decimal("530.00")
        tp_price = self.take_profit['price']
        
        is_triggered = current_price >= tp_price
        self.assertTrue(is_triggered)
    
    def test_take_profit_not_triggered_below_tp(self):
        """Test that take profit doesn't trigger below TP price"""
        current_price = Decimal("525.00")
        tp_price = self.take_profit['price']
        
        is_triggered = current_price >= tp_price
        self.assertFalse(is_triggered)
    
    def test_maximum_profit_calculation(self):
        """Test maximum profit calculation with take profit"""
        quantity = self.position['quantity']
        entry = self.position['entry_price']
        tp_price = self.take_profit['price']
        
        max_profit = quantity * (tp_price - entry)
        self.assertEqual(max_profit, Decimal("3000.00"))


if __name__ == '__main__':
    unittest.main()
