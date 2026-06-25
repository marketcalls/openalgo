import pytest
import sys
import os
from dotenv import load_dotenv

# Set required environment variables before importing openalgo modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ANALYZER_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LOGS_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "fake-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load sample env variables
load_dotenv(os.path.join(sys.path[0], ".sample.env"))

from unittest.mock import patch, MagicMock
from services.basket_order_service import (
    validate_order,
    place_single_order,
    process_basket_order_with_auth,
    place_basket_order
)

@pytest.fixture
def global_mocks():
    """Fixture to provide common mocks for all tests to prevent OperationalError"""
    with patch("database.settings_db.get_analyze_mode", return_value=False) as db_analyze, \
         patch("services.basket_order_service.get_analyze_mode", return_value=False) as svc_analyze, \
         patch("database.apilog_db.async_log_order") as mock_log_order, \
         patch("services.basket_order_service.log_executor") as mock_log_exec, \
         patch("database.analyzer_db.async_log_analyzer") as mock_log_analyzer:
        yield {
            "db_analyze": db_analyze,
            "svc_analyze": svc_analyze,
            "log_order": mock_log_order,
            "log_analyzer": mock_log_analyzer,
            "log_exec": mock_log_exec
        }

def test_validate_order_valid():
    order = {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "10", "pricetype": "MARKET", "product": "MIS", "apikey": "key", "strategy": "strat"}
    is_valid, error = validate_order(order)
    assert is_valid is True
    assert error is None

def test_validate_order_invalid_missing_fields():
    order = {"exchange": "NSE", "action": "BUY"}
    is_valid, error = validate_order(order)
    assert is_valid is False
    assert "Missing mandatory field" in error

def test_validate_order_invalid_exchange():
    order = {"symbol": "RELIANCE", "exchange": "INVALID", "action": "BUY", "quantity": "10", "pricetype": "MARKET", "product": "MIS", "apikey": "key", "strategy": "strat"}
    is_valid, error = validate_order(order)
    assert is_valid is False
    assert "Invalid exchange" in error

def test_place_single_order_success():
    mock_broker = MagicMock()
    mock_res = MagicMock()
    mock_res.status = 200
    mock_broker.place_order_api.return_value = (mock_res, {"status": "success"}, "ORDER123")
    
    order_data = {"symbol": "RELIANCE"}
    result = place_single_order(order_data, mock_broker, "token123", 1, 0)
    
    assert result["status"] == "success"
    assert result["orderid"] == "ORDER123"

def test_place_single_order_failure():
    mock_broker = MagicMock()
    mock_res = MagicMock()
    mock_res.status = 400
    mock_broker.place_order_api.return_value = (mock_res, {"message": "Rejected"}, None)
    
    order_data = {"symbol": "RELIANCE"}
    result = place_single_order(order_data, mock_broker, "token123", 1, 0)
    
    assert result["status"] == "error"
    assert result["message"] == "Rejected"

@patch("services.basket_order_service.import_broker_module")
@patch("services.basket_order_service.socketio")
def test_process_basket_order_live_success(mock_socketio, mock_import, global_mocks):
    mock_broker = MagicMock()
    mock_import.return_value = mock_broker
    
    mock_res = MagicMock()
    mock_res.status = 200
    mock_broker.place_order_api.return_value = (mock_res, {"status": "success"}, "ORDER789")
    
    basket = {
        "strategy": "TestStrat",
        "orders": [
            {"symbol": "REL", "action": "BUY", "exchange": "NSE", "quantity": "10", "pricetype": "MARKET", "product": "MIS"},
            {"symbol": "TCS", "action": "SELL", "exchange": "NSE", "quantity": "10", "pricetype": "MARKET", "product": "MIS"}
        ]
    }
    
    success, response, status_code = process_basket_order_with_auth(basket, "token1", "fakebroker", basket)
    
    assert success is True
    assert status_code == 200
    assert response["status"] == "success"
    assert len(response["results"]) == 2
    assert mock_broker.place_order_api.call_count == 2

@patch("services.basket_order_service.import_broker_module")
@patch("services.basket_order_service.socketio")
def test_process_basket_order_partial_failure(mock_socketio, mock_import, global_mocks):
    mock_broker = MagicMock()
    mock_import.return_value = mock_broker
    
    def side_effect(order_data, auth_token):
        mock_res = MagicMock()
        if order_data["symbol"] == "GOOD":
            mock_res.status = 200
            return (mock_res, {"status": "success"}, "ORDER1")
        else:
            mock_res.status = 400
            return (mock_res, {"message": "Rejected"}, None)
            
    mock_broker.place_order_api.side_effect = side_effect
    
    basket = {
        "strategy": "TestStrat",
        "orders": [
            {"symbol": "GOOD", "action": "BUY", "exchange": "NSE", "quantity": "10", "pricetype": "MARKET", "product": "MIS"},
            {"symbol": "BAD", "action": "BUY", "exchange": "NSE", "quantity": "10", "pricetype": "MARKET", "product": "MIS"}
        ]
    }
    
    success, response, status_code = process_basket_order_with_auth(basket, "token1", "fakebroker", basket)
    
    assert success is True
    assert len(response["results"]) == 2
    
    statuses = [r["status"] for r in response["results"]]
    assert "success" in statuses
    assert "error" in statuses

@patch("services.sandbox_service.sandbox_place_order")
@patch("services.basket_order_service.socketio")
def test_process_basket_order_sandbox(mock_socketio, mock_sandbox, global_mocks):
    global_mocks["db_analyze"].return_value = True
    global_mocks["svc_analyze"].return_value = True
    
    # sandbox_place_order returns (success, response, status_code)
    mock_sandbox.return_value = (True, {"orderid": "SANDBOX123"}, 200)
    
    basket = {
        "strategy": "TestStrat",
        "orders": [
            {"symbol": "REL", "action": "BUY", "exchange": "NSE", "quantity": "10", "pricetype": "MARKET", "product": "MIS"}
        ]
    }
    
    success, response, status_code = process_basket_order_with_auth(basket, "token1", "fakebroker", basket)
    
    assert success is True
    assert status_code == 200
    assert response["mode"] == "analyze"
    assert mock_sandbox.call_count == 1

@patch("services.order_router_service.should_route_to_pending")
@patch("services.basket_order_service.get_auth_token_broker")
def test_place_basket_order_api_success(mock_get_auth, mock_should_route, global_mocks):
    mock_should_route.return_value = False
    mock_get_auth.return_value = ("token123", "fakebroker")
    
    with patch("services.basket_order_service.process_basket_order_with_auth") as mock_process:
        mock_process.return_value = (True, {"status": "success"}, 200)
        
        success, response, code = place_basket_order({"orders": []}, api_key="test_key")
        
        assert success is True
        assert mock_process.call_count == 1

@patch("services.order_router_service.should_route_to_pending")
@patch("services.order_router_service.queue_order")
def test_place_basket_order_semi_auto_route(mock_queue, mock_should_route, global_mocks):
    mock_should_route.return_value = True
    mock_queue.return_value = (True, {"status": "queued"}, 200)
    
    success, response, code = place_basket_order({"orders": []}, api_key="test_key")
    
    assert success is True
    assert response["status"] == "queued"
    assert mock_queue.call_count == 1

def test_place_basket_order_invalid_params():
    success, response, code = place_basket_order({"orders": []})
    assert success is False
    assert code == 400
    assert "must be provided" in response["message"]
