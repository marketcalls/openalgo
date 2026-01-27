"""
Unit tests for Action Center and Order Mode functionality

Run with: python -m pytest test/test_action_center.py -v
"""

import json

import pytest

from database.action_center_db import (
    approve_pending_order,
    create_pending_order,
    delete_pending_order,
    get_pending_count,
    get_pending_order_by_id,
    get_pending_orders,
    reject_pending_order,
    update_broker_status,
)
from database.auth_db import get_order_mode, update_order_mode
from services.action_center_service import get_action_center_data
from services.order_router_service import queue_order, should_route_to_pending


class TestOrderModeDatabase:
    """Test order mode database functions"""

    def test_get_order_mode_default(self):
        """Test default order mode is 'auto'"""
        mode = get_order_mode("test_user")
        assert mode == "auto", "Default order mode should be 'auto'"

    def test_update_order_mode_to_semi_auto(self):
        """Test updating order mode to semi_auto"""
        success = update_order_mode("test_user", "semi_auto")
        assert success is True, "Should successfully update to semi_auto"

        mode = get_order_mode("test_user")
        assert mode == "semi_auto", "Order mode should be updated to semi_auto"

    def test_update_order_mode_to_auto(self):
        """Test updating order mode back to auto"""
        update_order_mode("test_user", "semi_auto")
        success = update_order_mode("test_user", "auto")
        assert success is True, "Should successfully update to auto"

        mode = get_order_mode("test_user")
        assert mode == "auto", "Order mode should be updated to auto"

    def test_update_order_mode_invalid(self):
        """Test updating order mode with invalid value"""
        success = update_order_mode("test_user", "invalid_mode")
        assert success is False, "Should fail with invalid mode"


class TestPendingOrdersDatabase:
    """Test pending orders database functions"""

    def test_create_pending_order(self):
        """Test creating a pending order"""
        order_data = {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "price_type": "MARKET",
            "product_type": "MIS",
        }

        order_id = create_pending_order("test_user", "placeorder", order_data)
        assert order_id is not None, "Should create pending order and return ID"
        assert isinstance(order_id, int), "Order ID should be an integer"

    def test_get_pending_orders(self):
        """Test retrieving pending orders"""
        # Create test order
        order_data = {"symbol": "TCS", "action": "BUY"}
        create_pending_order("test_user", "placeorder", order_data)

        # Get pending orders
        orders = get_pending_orders("test_user", status="pending")
        assert len(orders) > 0, "Should retrieve at least one pending order"

    def test_get_pending_order_by_id(self):
        """Test retrieving a specific pending order"""
        order_data = {"symbol": "INFY", "action": "SELL"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        order = get_pending_order_by_id(order_id)
        assert order is not None, "Should retrieve the order"
        assert order.id == order_id, "Order ID should match"
        assert order.status == "pending", "Order status should be pending"

    def test_approve_pending_order(self):
        """Test approving a pending order"""
        order_data = {"symbol": "HDFC", "action": "BUY"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        success = approve_pending_order(order_id, approved_by="test_approver")
        assert success is True, "Should successfully approve order"

        order = get_pending_order_by_id(order_id)
        assert order.status == "approved", "Order status should be approved"
        assert order.approved_by == "test_approver", "Approved by should be set"
        assert order.approved_at_ist is not None, "IST timestamp should be set"

    def test_reject_pending_order(self):
        """Test rejecting a pending order"""
        order_data = {"symbol": "ICICI", "action": "SELL"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        reason = "Market conditions unfavorable"
        success = reject_pending_order(order_id, reason, rejected_by="test_rejector")
        assert success is True, "Should successfully reject order"

        order = get_pending_order_by_id(order_id)
        assert order.status == "rejected", "Order status should be rejected"
        assert order.rejected_by == "test_rejector", "Rejected by should be set"
        assert order.rejected_reason == reason, "Rejection reason should be set"
        assert order.rejected_at_ist is not None, "IST timestamp should be set"

    def test_delete_approved_order(self):
        """Test deleting an approved order"""
        order_data = {"symbol": "SBI", "action": "BUY"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        # Approve first
        approve_pending_order(order_id, approved_by="test_user")

        # Delete
        success = delete_pending_order(order_id)
        assert success is True, "Should successfully delete approved order"

        order = get_pending_order_by_id(order_id)
        assert order is None, "Order should be deleted"

    def test_delete_pending_order_fails(self):
        """Test that deleting a pending order fails"""
        order_data = {"symbol": "WIPRO", "action": "BUY"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        success = delete_pending_order(order_id)
        assert success is False, "Should not delete order in pending status"

    def test_update_broker_status(self):
        """Test updating broker status after execution"""
        order_data = {"symbol": "TCS", "action": "BUY"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        approve_pending_order(order_id, approved_by="test_user")

        success = update_broker_status(order_id, "BROKER123456", "open")
        assert success is True, "Should successfully update broker status"

        order = get_pending_order_by_id(order_id)
        assert order.broker_order_id == "BROKER123456", "Broker order ID should be set"
        assert order.broker_status == "open", "Broker status should be set"

    def test_get_pending_count(self):
        """Test getting count of pending orders"""
        # Create multiple pending orders
        for i in range(3):
            order_data = {"symbol": f"STOCK{i}", "action": "BUY"}
            create_pending_order("count_test_user", "placeorder", order_data)

        count = get_pending_count("count_test_user")
        assert count >= 3, "Should count at least 3 pending orders"


class TestOrderRouterService:
    """Test order routing service"""

    def test_should_route_to_pending_auto_mode(self):
        """Test routing check in auto mode"""
        # Assuming test user is in auto mode
        result = should_route_to_pending("test-api-key")
        assert result is False, "Should not route to pending in auto mode"

    def test_queue_order(self):
        """Test queuing an order"""
        order_data = {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "price_type": "MARKET",
            "product_type": "MIS",
            "apikey": "test-key",
        }

        # This will fail without valid API key, but tests the function structure
        success, response, status_code = queue_order("invalid-key", order_data, "placeorder")
        assert isinstance(success, bool), "Should return boolean success"
        assert isinstance(response, dict), "Should return response dict"
        assert isinstance(status_code, int), "Should return status code"

    def test_queue_options_order(self):
        """Test queuing an options order"""
        options_data = {
            "underlying": "NIFTY",
            "exchange": "NSE",
            "expiry_date": "2024-12-26",
            "strike_int": "50",
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": "50",
            "pricetype": "MARKET",
            "product": "MIS",
            "apikey": "test-key",
        }

        # This will fail without valid API key, but tests the function structure
        success, response, status_code = queue_order("invalid-key", options_data, "optionsorder")
        assert isinstance(success, bool), "Should return boolean success"
        assert isinstance(response, dict), "Should return response dict"
        assert isinstance(status_code, int), "Should return status code"


class TestActionCenterService:
    """Test action center service functions"""

    def test_get_action_center_data(self):
        """Test retrieving action center data"""
        # Create test order
        order_data = {"symbol": "TCS", "action": "BUY"}
        create_pending_order("ac_test_user", "placeorder", order_data)

        success, response, status_code = get_action_center_data(
            "ac_test_user", status_filter="pending"
        )

        assert success is True, "Should successfully retrieve data"
        assert status_code == 200, "Status code should be 200"
        assert "data" in response, "Response should contain data"
        assert "orders" in response["data"], "Data should contain orders"
        assert "statistics" in response["data"], "Data should contain statistics"

    def test_action_center_statistics(self):
        """Test action center statistics calculation"""
        # Create test orders with different statuses
        create_pending_order("stats_user", "placeorder", {"symbol": "A", "action": "BUY"})
        create_pending_order("stats_user", "placeorder", {"symbol": "B", "action": "SELL"})

        success, response, status_code = get_action_center_data("stats_user")
        stats = response["data"]["statistics"]

        assert "total_pending" in stats, "Should have pending count"
        assert "total_buy_orders" in stats, "Should have buy orders count"
        assert "total_sell_orders" in stats, "Should have sell orders count"


class TestISTTimestamps:
    """Test IST timestamp functionality"""

    def test_created_at_ist_format(self):
        """Test that created_at_ist is in correct format"""
        order_data = {"symbol": "TCS", "action": "BUY"}
        order_id = create_pending_order("test_user", "placeorder", order_data)

        order = get_pending_order_by_id(order_id)
        assert order.created_at_ist is not None, "IST timestamp should be set"
        assert "IST" in order.created_at_ist, "Timestamp should contain 'IST'"
        assert len(order.created_at_ist) > 10, "Timestamp should be formatted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
