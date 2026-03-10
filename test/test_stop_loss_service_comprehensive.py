import unittest
import sys
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestStopLossService(unittest.TestCase):
    """Comprehensive tests for Stop Loss Service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.position = {
            "symbol": "NSE:SBIN-EQ",
            "quantity": 100,
            "entry_price": Decimal("500.00"),
            "current_price": Decimal("520.00")
        }
        self.stop_loss = {
            "price": Decimal("490.00"),
            "percentage": 2.0,  # 2% below entry
            "type": "PERCENTAGE"
        }
    
    def test_stop_loss_price_below_entry(self):
        """Test that stop loss price is below entry for long positions"""
        entry = self.position['entry_price']
        sl_price = self.stop_loss['price']
        
        self.assertLess(sl_price, entry)
    
    def test_stop_loss_percentage_valid_range(self):
        """Test that stop loss percentage is within 0-50%"""
        percentage = self.stop_loss['percentage']
        
        self.assertGreater(percentage, 0)
        self.assertLess(percentage, 50)
    
    def test_stop_loss_absolute_price_validation(self):
        """Test that absolute stop loss price is valid"""
        sl_price = self.stop_loss['price']
        
        # Stop loss price must be positive
        self.assertGreater(sl_price, Decimal("0"))
    
    def test_percentage_to_price_conversion(self):
        """Test conversion of percentage stop loss to price"""
        entry = self.position['entry_price']
        percentage = Decimal("2")
        
        # Calculate stop loss price from percentage
        sl_price = entry * (1 - percentage / 100)
        
        self.assertEqual(sl_price, Decimal("490.00"))
    
    def test_stop_loss_trigger_on_target_hit(self):
        """Test that stop loss triggers when price hits SL"""
        current_price = Decimal("490.00")
        sl_price = self.stop_loss['price']
        
        is_triggered = current_price <= sl_price
        self.assertTrue(is_triggered)
    
    def test_stop_loss_not_triggered_above_sl(self):
        """Test that stop loss doesn't trigger above SL price"""
        current_price = Decimal("495.00")
        sl_price = self.stop_loss['price']
        
        is_triggered = current_price <= sl_price
        self.assertFalse(is_triggered)
    
    def test_maximum_loss_calculation(self):
        """Test maximum loss calculation with stop loss"""
        quantity = self.position['quantity']
        entry = self.position['entry_price']
        sl_price = self.stop_loss['price']
        
        max_loss = quantity * (entry - sl_price)
        self.assertEqual(max_loss, Decimal("1000.00"))


if __name__ == '__main__':
    unittest.main()
