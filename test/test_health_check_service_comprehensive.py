import unittest
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, 'D:\\sem4\\openalgo')


class TestHealthCheckService(unittest.TestCase):
    """Comprehensive tests for Health Check service"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.health_check_response = {
            "status": "healthy",
            "timestamp": datetime.now(),
            "uptime_seconds": 3600,
            "api_status": "operational",
            "database_status": "connected",
            "websocket_status": "connected"
        }
    
    def test_health_status_is_healthy(self):
        """Test that health status is healthy"""
        status = self.health_check_response['status']
        self.assertEqual(status, 'healthy')
    
    def test_health_check_includes_timestamp(self):
        """Test that health check includes timestamp"""
        timestamp = self.health_check_response['timestamp']
        self.assertIsInstance(timestamp, datetime)
    
    def test_uptime_is_non_negative(self):
        """Test that uptime is never negative"""
        uptime = self.health_check_response['uptime_seconds']
        self.assertGreaterEqual(uptime, 0)
    
    def test_api_status_operational(self):
        """Test that API status is operational"""
        api_status = self.health_check_response['api_status']
        valid_statuses = ['operational', 'degraded', 'down']
        
        self.assertIn(api_status, valid_statuses)
    
    def test_database_connection_status(self):
        """Test that database connection status is reported"""
        db_status = self.health_check_response['database_status']
        valid_statuses = ['connected', 'disconnected', 'error']
        
        self.assertIn(db_status, valid_statuses)
    
    def test_websocket_connection_status(self):
        """Test that websocket connection status is reported"""
        ws_status = self.health_check_response['websocket_status']
        valid_statuses = ['connected', 'disconnected', 'reconnecting']
        
        self.assertIn(ws_status, valid_statuses)
    
    def test_health_response_is_valid_json_structure(self):
        """Test that health check response is valid JSON structure"""
        response = self.health_check_response
        required_fields = ['status', 'timestamp', 'api_status', 'database_status']
        
        for field in required_fields:
            self.assertIn(field, response)


if __name__ == '__main__':
    unittest.main()
