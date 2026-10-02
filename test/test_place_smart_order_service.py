import os
import sys

# Insert parent directory to path at index 0 to override test/sandbox
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sample.env")
load_dotenv(env_path)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest

import pytest
from unittest.mock import patch, MagicMock
import sys

# Mock telegram service to avoid DB queries during module load
sys.modules["services.telegram_alert_service"] = MagicMock()

from services.place_smart_order_service import validate_smart_order, place_smart_order
from services.sandbox_service import sandbox_place_smart_order
from utils.constants import REQUIRED_SMART_ORDER_FIELDS


@pytest.fixture
def valid_smart_order_data():
    return {
        "apikey": "testkey",
        "strategy": "test_strat",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "100",
        "position_size": "100",
    }


def test_validate_smart_order_valid(valid_smart_order_data):
    """Test validation with perfectly valid data"""
    is_valid, msg = validate_smart_order(valid_smart_order_data)
    assert is_valid is True
    assert msg is None


def test_validate_smart_order_missing_fields(valid_smart_order_data):
    """Test validation error when mandatory fields are missing"""
    del valid_smart_order_data["position_size"]
    is_valid, msg = validate_smart_order(valid_smart_order_data)
    assert is_valid is False
    assert "Missing mandatory field(s): position_size" in msg


def test_validate_smart_order_invalid_fields(valid_smart_order_data):
    """Test validation with invalid exchange and action"""
    valid_smart_order_data["exchange"] = "INVALID"
    is_valid, msg = validate_smart_order(valid_smart_order_data)
    assert is_valid is False
    assert "Invalid exchange" in msg

    valid_smart_order_data["exchange"] = "NSE"
    valid_smart_order_data["action"] = "INVALID"
    is_valid, msg = validate_smart_order(valid_smart_order_data)
    assert is_valid is False
    assert "Invalid action" in msg


@patch("services.sandbox_service.get_user_id_from_apikey")
@patch("services.sandbox_service.PositionManager")
@patch("services.sandbox_service.OrderManager")
def test_sandbox_smart_order_flat_to_long(mock_order_mgr, mock_pos_mgr, mock_get_user, valid_smart_order_data):
    """Test action mapping: Flat -> Long (target = 100, current = 0)"""
    mock_get_user.return_value = "user123"
    
    # Mock current position to be FLAT (0)
    pos_mgr_instance = mock_pos_mgr.return_value
    pos_mgr_instance.get_open_positions.return_value = (True, {"data": []}, 200)
    
    # Mock order placement success
    order_mgr_instance = mock_order_mgr.return_value
    order_mgr_instance.place_order.return_value = (True, {"status": "success"}, 200)

    success, response, status_code = sandbox_place_smart_order(valid_smart_order_data, "testkey", {})
    
    assert success is True
    order_mgr_instance.place_order.assert_called_once()
    called_args = order_mgr_instance.place_order.call_args[0][0]
    
    assert called_args["action"] == "BUY"
    assert called_args["quantity"] == 100


@patch("services.sandbox_service.get_user_id_from_apikey")
@patch("services.sandbox_service.PositionManager")
@patch("services.sandbox_service.OrderManager")
def test_sandbox_smart_order_reduce_long(mock_order_mgr, mock_pos_mgr, mock_get_user, valid_smart_order_data):
    """Test action mapping: Long 100 -> Long 50 (Expected: SELL 50)"""
    mock_get_user.return_value = "user123"
    valid_smart_order_data["position_size"] = "50"
    
    # Mock current position to be 100
    pos_mgr_instance = mock_pos_mgr.return_value
    pos_mgr_instance.get_open_positions.return_value = (True, {"data": [
        {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "quantity": 100}
    ]}, 200)
    
    order_mgr_instance = mock_order_mgr.return_value
    order_mgr_instance.place_order.return_value = (True, {"status": "success"}, 200)

    success, response, status_code = sandbox_place_smart_order(valid_smart_order_data, "testkey", {})
    
    assert success is True
    order_mgr_instance.place_order.assert_called_once()
    called_args = order_mgr_instance.place_order.call_args[0][0]
    
    assert called_args["action"] == "SELL"
    assert called_args["quantity"] == 50


@patch("services.sandbox_service.get_user_id_from_apikey")
@patch("services.sandbox_service.PositionManager")
@patch("services.sandbox_service.OrderManager")
def test_sandbox_smart_order_position_zero(mock_order_mgr, mock_pos_mgr, mock_get_user, valid_smart_order_data):
    """Test smart order with position_size=0 (Expected: SELL 100 to close position)"""
    mock_get_user.return_value = "user123"
    valid_smart_order_data["position_size"] = "0"
    
    # Mock current position to be 100
    pos_mgr_instance = mock_pos_mgr.return_value
    pos_mgr_instance.get_open_positions.return_value = (True, {"data": [
        {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "quantity": 100}
    ]}, 200)
    
    order_mgr_instance = mock_order_mgr.return_value
    order_mgr_instance.place_order.return_value = (True, {"status": "success"}, 200)

    success, response, status_code = sandbox_place_smart_order(valid_smart_order_data, "testkey", {})
    
    assert success is True
    order_mgr_instance.place_order.assert_called_once()
    called_args = order_mgr_instance.place_order.call_args[0][0]
    
    assert called_args["action"] == "SELL"
    assert called_args["quantity"] == 100


@patch("services.sandbox_service.get_user_id_from_apikey")
@patch("services.sandbox_service.PositionManager")
@patch("services.sandbox_service.OrderManager")
def test_sandbox_smart_order_no_action_needed(mock_order_mgr, mock_pos_mgr, mock_get_user, valid_smart_order_data):
    """Test when current position matches position_size (Expected: No action)"""
    mock_get_user.return_value = "user123"
    valid_smart_order_data["position_size"] = "100"
    
    pos_mgr_instance = mock_pos_mgr.return_value
    pos_mgr_instance.get_open_positions.return_value = (True, {"data": [
        {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "quantity": 100}
    ]}, 200)
    
    success, response, status_code = sandbox_place_smart_order(valid_smart_order_data, "testkey", {})
    
    assert success is True
    assert "Already Matched" in response["message"]
    mock_order_mgr.return_value.place_order.assert_not_called()


@patch("services.place_smart_order_service.get_analyze_mode")
@patch("services.place_smart_order_service.get_auth_token_broker")
@patch("services.place_smart_order_service.import_broker_module")
@patch("services.place_smart_order_service.async_log_order")
@patch("services.place_smart_order_service.executor")
def test_place_smart_order_mock_broker(mock_exec, mock_log_order, mock_import, mock_get_auth, mock_analyze, valid_smart_order_data):
    """Test place_smart_order routing to live broker properly handles broker responses"""
    mock_analyze.return_value = False
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    
    mock_broker = MagicMock()
    mock_res = MagicMock()
    mock_res.status = 200
    mock_broker.place_smartorder_api.return_value = (mock_res, {"status": "success"}, "12345")
    mock_import.return_value = mock_broker
    
    # We also have to mock telegram and socketio so it doesn't try linking
    with patch("services.place_smart_order_service.socketio"), patch("services.place_smart_order_service.telegram_alert_service"):
        # Temporarily mock SMART_ORDER_DELAY since it sleeps
        with patch("services.place_smart_order_service.SMART_ORDER_DELAY", "0"):
            success, response, status = place_smart_order(valid_smart_order_data, api_key="testkey", smart_order_delay="0")
            
    assert success is True
    assert status == 200
    mock_broker.place_smartorder_api.assert_called_once()
