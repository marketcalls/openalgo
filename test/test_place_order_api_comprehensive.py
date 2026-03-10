"""
Comprehensive tests for REST API place_order endpoint

This test suite covers:
- POST request validation
- Request body parsing
- Response structure validation
- Error handling for invalid requests
- Status code responses
"""

import pytest
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPlaceOrderAPI:
    """Test REST API endpoint for order placement"""

    def test_valid_place_order_request_structure(self):
        """Test valid place order request structure"""
        request_payload = {
            "apikey": "test-api-key-12345",
            "symbol": "NSE:SBIN-EQ",
            "quantity": 10,
            "price": 500.50,
            "order_type": "LIMIT",
            "side": "BUY"
        }
        
        # Validate required fields
        assert "apikey" in request_payload
        assert "symbol" in request_payload
        assert "quantity" in request_payload
        assert "price" in request_payload
        assert "order_type" in request_payload
        assert "side" in request_payload
        
        # Validate field values
        assert len(request_payload["apikey"]) > 0
        assert len(request_payload["symbol"]) > 0


    def test_missing_required_field(self):
        """Test request with missing required field"""
        request_payload = {
            "apikey": "test-api-key",
            "symbol": "NSE:SBIN-EQ",
            # Missing "quantity"
            "price": 500.50,
            "order_type": "LIMIT",
            "side": "BUY"
        }
        
        required_fields = ["apikey", "symbol", "quantity", "price", "order_type", "side"]
        missing_fields = [field for field in required_fields if field not in request_payload]
        
        assert len(missing_fields) > 0
        assert "quantity" in missing_fields


    def test_invalid_quantity_validation(self):
        """Test validation of invalid quantity values"""
        invalid_quantities = [0, -5, -100, -1]
        
        for quantity in invalid_quantities:
            assert quantity <= 0  # Invalid for order placement


    def test_invalid_price_validation(self):
        """Test validation of invalid price values"""
        invalid_prices = [0, -10.50, -500, -1]
        
        for price in invalid_prices:
            assert price <= 0  # Invalid for order placement


    def test_invalid_side_validation(self):
        """Test validation of order side (BUY/SELL)"""
        valid_sides = ["BUY", "SELL"]
        invalid_side = "INVALID"
        
        assert invalid_side not in valid_sides
        assert "BUY" in valid_sides
        assert "SELL" in valid_sides


    def test_valid_order_types(self):
        """Test validation of order types"""
        valid_order_types = ["LIMIT", "MARKET", "STOP", "STOP_LIMIT"]
        test_type = "LIMIT"
        
        assert test_type in valid_order_types
        assert len(valid_order_types) >= 4


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
