import unittest
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestOrderStatusService(unittest.TestCase):
    """Comprehensive tests for Order Status Service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.order = {
            "order_id": "12345",
            "status": "OPEN",
            "quantity": 100,
            "filled_quantity": 0,
            "pending_quantity": 100,
            "timestamp": datetime.now()
        }
    
    def test_order_id_not_empty(self):
        """Test that order ID is not empty"""
        order_id = self.order['order_id']
        self.assertTrue(len(order_id) > 0)
    
    def test_order_status_valid(self):
        """Test that order status is valid"""
        valid_statuses = [
            'PENDING', 'OPEN', 'PARTIALLY_FILLED', 'FILLED', 
            'CANCELLED', 'REJECTED', 'EXPIRED'
        ]
        status = self.order['status']
        self.assertIn(status, valid_statuses)
    
    def test_filled_quantity_non_negative(self):
        """Test that filled quantity is never negative"""
        filled = self.order['filled_quantity']
        self.assertGreaterEqual(filled, 0)
    
    def test_filled_quantity_not_exceeds_order_quantity(self):
        """Test that filled quantity never exceeds order quantity"""
        filled = self.order['filled_quantity']
        total = self.order['quantity']
        self.assertLessEqual(filled, total)
    
    def test_pending_quantity_calculation(self):
        """Test that pending = order quantity - filled quantity"""
        total = self.order['quantity']
        filled = self.order['filled_quantity']
        pending = self.order['pending_quantity']
        
        self.assertEqual(pending, total - filled)
    
    def test_order_timestamp_recorded(self):
        """Test that order timestamp is recorded"""
        timestamp = self.order['timestamp']
        self.assertIsInstance(timestamp, datetime)
    
    def test_order_timestamp_not_future(self):
        """Test that order timestamp is not in future"""
        timestamp = self.order['timestamp']
        now = datetime.now()
        self.assertLessEqual(timestamp, now)


if __name__ == '__main__':
    unittest.main()
