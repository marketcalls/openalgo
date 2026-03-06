import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sample.env")
load_dotenv(env_path)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

# Mock telegram service to avoid DB queries during module load
sys.modules["services.telegram_alert_service"] = MagicMock()

# Now import the modules
from services.cancel_order_service import cancel_order
from services.cancel_all_order_service import cancel_all_orders


@pytest.fixture(autouse=True)
def global_mocks():
    """Mock database calls globally to avoid OperationalError"""
    with patch("database.settings_db.get_analyze_mode") as mock_db_analyze, \
         patch("services.cancel_order_service.get_analyze_mode") as mock_svc_analyze, \
         patch("services.cancel_all_order_service.get_analyze_mode") as mock_all_analyze, \
         patch("database.auth_db.verify_api_key", return_value="user123") as mock_verify, \
         patch("database.auth_db.get_order_mode", return_value="auto") as mock_order_mode, \
         patch("services.cancel_order_service.executor") as mock_exec_cancel, \
         patch("services.cancel_order_service.async_log_order") as mock_log_cancel, \
         patch("services.cancel_all_order_service.executor") as mock_exec_all, \
         patch("services.cancel_all_order_service.async_log_order") as mock_log_all, \
         patch("services.cancel_order_service.socketio"), \
         patch("services.cancel_all_order_service.socketio"):
        mock_db_analyze.return_value = False
        mock_svc_analyze.return_value = False
        mock_all_analyze.return_value = False
        yield {
            "db_analyze": mock_db_analyze,
            "svc_analyze": mock_svc_analyze,
            "all_analyze": mock_all_analyze,
            "verify": mock_verify,
            "order_mode": mock_order_mode,
        }

@pytest.fixture
def mock_broker():
    return MagicMock()


@patch("services.cancel_order_service.get_auth_token_broker")
@patch("services.cancel_order_service.import_broker_module")
def test_cancel_order_valid_id(mock_import, mock_get_auth, mock_broker, global_mocks):
    """Test cancel_order with a valid order ID"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    mock_broker.cancel_order.return_value = ({"status": "success", "message": "Canceled"}, 200)
    mock_import.return_value = mock_broker

    success, response, status = cancel_order("ORD12345", api_key="testkey")

    assert success is True
    assert status == 200
    assert response["orderid"] == "ORD12345"
    mock_broker.cancel_order.assert_called_once_with("ORD12345", "fake_token")


def test_cancel_order_missing_id(global_mocks):
    """Test cancel_order with missing or empty order ID"""
    success, response, status = cancel_order("", api_key="testkey")

    assert success is False
    assert status == 400
    assert "Order ID is missing" in response["message"]


@patch("services.cancel_order_service.get_auth_token_broker")
@patch("services.cancel_order_service.import_broker_module")
def test_cancel_order_already_cancelled(mock_import, mock_get_auth, mock_broker, global_mocks):
    """Test cancel_order when order is already cancelled / invalid status"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    
    mock_broker.cancel_order.return_value = ({"status": "error", "message": "Order is already cancelled or executed"}, 400)
    mock_import.return_value = mock_broker

    success, response, status = cancel_order("ORD_ALREADY_DONE", api_key="testkey")

    assert success is False
    assert status == 400
    assert "already cancelled" in response["message"]


@patch("services.cancel_all_order_service.get_auth_token_broker")
@patch("services.cancel_all_order_service.import_broker_module")
def test_cancel_all_orders_success(mock_import, mock_get_auth, mock_broker, global_mocks):
    """Test cancel_all_orders successfully cancels multiple orders"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    
    mock_broker.cancel_all_orders_api.return_value = (["ORD1", "ORD2"], [])
    mock_import.return_value = mock_broker

    success, response, status = cancel_all_orders({}, api_key="testkey")

    assert success is True
    assert status == 200
    assert len(response["canceled_orders"]) == 2
    assert "ORD1" in response["canceled_orders"]
    mock_broker.cancel_all_orders_api.assert_called_once()


@patch("services.cancel_all_order_service.get_auth_token_broker")
@patch("services.cancel_all_order_service.import_broker_module")
def test_cancel_all_orders_partial_failure(mock_import, mock_get_auth, mock_broker, global_mocks):
    """Test cancel_all_orders where some orders fail to cancel"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    
    mock_broker.cancel_all_orders_api.return_value = (["ORD1"], ["ORD2"])
    mock_import.return_value = mock_broker

    success, response, status = cancel_all_orders({}, api_key="testkey")

    assert success is True
    assert status == 200
    assert len(response["canceled_orders"]) == 1
    assert len(response["failed_cancellations"]) == 1
    assert "Canceled 1 orders. Failed to cancel 1 orders." in response["message"]


def test_cancel_all_orders_semi_auto_restriction(global_mocks):
    """Test that cancel_all_orders is blocked if user is in semi-auto mode"""
    global_mocks["order_mode"].return_value = "semi_auto"
    success, response, status = cancel_all_orders({}, api_key="testkey")

    assert success is False
    assert status == 403
    assert "not allowed in Semi-Auto mode" in response["message"]


@patch("services.cancel_order_service.get_auth_token_broker")
def test_cancel_order_sandbox_route(mock_get_auth, global_mocks):
    """Test that sandbox mode correctly routes to sandbox service"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    global_mocks["db_analyze"].return_value = True
    global_mocks["svc_analyze"].return_value = True

    with patch("services.sandbox_service.sandbox_cancel_order") as mock_sandbox:
        mock_sandbox.return_value = (True, {"status": "success"}, 200)
        success, response, status = cancel_order("ORD_SANDBOX", api_key="testkey")

    assert success is True
    mock_sandbox.assert_called_once()
    assert mock_sandbox.call_args[0][0]["orderid"] == "ORD_SANDBOX"


@patch("services.cancel_all_order_service.get_auth_token_broker")
def test_cancel_all_order_sandbox_route(mock_get_auth, global_mocks):
    """Test that sandbox mode routes cancel all to sandbox service"""
    mock_get_auth.return_value = ("fake_token", "fake_broker")
    global_mocks["db_analyze"].return_value = True
    global_mocks["all_analyze"].return_value = True

    with patch("services.sandbox_service.sandbox_cancel_all_orders") as mock_sandbox:
        mock_sandbox.return_value = (True, {"status": "success"}, 200)
        success, response, status = cancel_all_orders({"some": "data"}, api_key="testkey")

    assert success is True
    mock_sandbox.assert_called_once()
