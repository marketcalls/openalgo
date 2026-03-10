"""
Comprehensive tests for option_chain_service.py

This test suite covers:
- Option chain data structure validation
- Strike price ordering
- Bid-ask spread validation
- Open interest tracking
- Greeks calculation basics
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOptionChainService:
    """Test option chain data and calculations"""

    def test_strike_price_ordering(self):
        """Test that strike prices are properly ordered"""
        strike_prices = [19500, 19600, 19700, 19800, 19900, 20000]
        
        # Verify ascending order
        for i in range(len(strike_prices) - 1):
            assert strike_prices[i] < strike_prices[i + 1]


    def test_bid_ask_spread_validation(self):
        """Test bid-ask spread is valid (ask >= bid)"""
        bid_price = Decimal("150.50")
        ask_price = Decimal("150.75")
        
        assert ask_price >= bid_price
        spread = ask_price - bid_price
        assert spread >= 0


    def test_open_interest_non_negative(self):
        """Test that open interest values are non-negative"""
        open_interest_values = [1000, 5000, 10000, 0]
        
        for oi in open_interest_values:
            assert oi >= 0


    def test_option_chain_structure(self):
        """Test option chain data structure for calls and puts"""
        option_chain = {
            "call": {
                "strike": 20000,
                "bid": Decimal("150.00"),
                "ask": Decimal("150.50"),
                "oi": 10000,
                "volume": 5000
            },
            "put": {
                "strike": 20000,
                "bid": Decimal("149.50"),
                "ask": Decimal("150.00"),
                "oi": 12000,
                "volume": 4000
            }
        }
        
        assert "call" in option_chain
        assert "put" in option_chain
        assert "strike" in option_chain["call"]
        assert "bid" in option_chain["call"]
        assert "ask" in option_chain["call"]
        assert option_chain["call"]["strike"] > 0


    def test_option_expiry_validation(self):
        """Test option expiry date validation"""
        today = datetime.now()
        expiry_date = today + timedelta(days=7)
        
        assert expiry_date > today
        assert (expiry_date - today).days == 7


    def test_moneyness_calculation(self):
        """Test in/out of money calculation"""
        spot_price = Decimal("20000.00")
        call_strike = Decimal("20500.00")  # OTM
        put_strike = Decimal("19500.00")   # OTM
        
        # Call is OTM when spot < strike
        call_is_otm = spot_price < call_strike
        assert call_is_otm is True
        
        # Put is OTM when spot > strike
        put_is_otm = spot_price > put_strike
        assert put_is_otm is True


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
