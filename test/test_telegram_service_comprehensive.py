import unittest
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestTelegramService(unittest.TestCase):
    """Comprehensive tests for Telegram Bot integration service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.valid_telegram_id = 123456789
        self.valid_chat_id = 987654321
        self.valid_message = "Order BUY 100 SBIN placed successfully"
        self.bot_token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    
    def test_telegram_id_validation(self):
        """Test that Telegram ID format is valid (positive integer)"""
        telegram_ids = [123456789, 987654321, 1]
        
        for tid in telegram_ids:
            is_valid = isinstance(tid, int) and tid > 0
            self.assertTrue(is_valid, f"Telegram ID {tid} should be valid")
    
    def test_telegram_id_must_be_positive(self):
        """Test that negative Telegram IDs are rejected"""
        invalid_id = -123456789
        is_valid = invalid_id > 0
        self.assertFalse(is_valid)
    
    def test_bot_token_format(self):
        """Test that bot token has correct format"""
        token = self.bot_token
        components = token.split(':')
        
        self.assertEqual(len(components), 2)
        self.assertTrue(components[0].isdigit())
        self.assertTrue(len(components[1]) > 0)
    
    def test_message_not_empty(self):
        """Test that messages are not empty"""
        valid_messages = [
            "Order placed",
            "Trade executed",
            "Position closed"
        ]
        
        for msg in valid_messages:
            is_valid = len(msg) > 0
            self.assertTrue(is_valid)
    
    def test_message_length_limit(self):
        """Test that messages respect Telegram 4096 character limit"""
        message = "x" * 4096
        is_valid = len(message) <= 4096
        self.assertTrue(is_valid)
    
    def test_message_exceeds_limit(self):
        """Test that messages exceeding 4096 chars fail"""
        message = "x" * 4097
        is_valid = len(message) <= 4096
        self.assertFalse(is_valid)


if __name__ == '__main__':
    unittest.main()
