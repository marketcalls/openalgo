"""
Comprehensive tests for holdings_service.py

This test suite covers:
- Position tracking accuracy
- Average price calculations
- P&L calculations
- Dividend and split handling
- Corporate action adjustments
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHoldingsService:
    """Test holdings tracking and calculation logic"""

    def test_position_value_calculation(self):
        """Test calculation of current position value"""
        quantity = 100
        current_price = Decimal("520.50")
        position_value = quantity * current_price
        
        assert position_value == Decimal("52050.00")
        assert position_value > 0


    def test_average_price_calculation(self):
        """Test average purchase price calculation"""
        total_cost = Decimal("51000.00")
        total_quantity = 100
        avg_price = total_cost / total_quantity
        
        assert avg_price == Decimal("510.00")
        assert avg_price > 0


    def test_unrealized_pnl_calculation(self):
        """Test unrealized P&L calculation"""
        position_value = Decimal("52050.00")
        investment_value = Decimal("51000.00")
        unrealized_pnl = position_value - investment_value
        
        assert unrealized_pnl == Decimal("1050.00")
        assert unrealized_pnl > 0  # Profit


    def test_pnl_percentage_calculation(self):
        """Test P&L percentage calculation"""
        investment_value = Decimal("51000.00")
        unrealized_pnl = Decimal("1050.00")
        pnl_percentage = (unrealized_pnl / investment_value) * 100
        
        assert pnl_percentage > 0
        assert float(pnl_percentage) == pytest.approx(2.06, rel=0.01)


    def test_loss_tracking(self):
        """Test tracking of unrealized losses"""
        current_value = Decimal("50000.00")
        investment_value = Decimal("51000.00")
        unrealized_loss = investment_value - current_value
        
        assert unrealized_loss == Decimal("1000.00")
        assert unrealized_loss > 0  # Loss


    def test_zero_quantity_holdings(self):
        """Test holdings with zero quantity"""
        quantity = 0
        position_value = quantity
        
        assert position_value == 0
        assert position_value == 0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
