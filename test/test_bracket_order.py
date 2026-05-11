import pytest
from services.bracket_order_service import calculate_exit_prices
from restx_api.schemas import BracketOrderSchema
from marshmallow import ValidationError

def test_calculate_exit_prices_buy_points():
    target, sl = calculate_exit_prices(100.0, "BUY", "points", 10.0, "points", 5.0)
    assert target == 110.0
    assert sl == 95.0

def test_calculate_exit_prices_sell_points():
    target, sl = calculate_exit_prices(100.0, "SELL", "points", 10.0, "points", 5.0)
    assert target == 90.0
    assert sl == 105.0

def test_calculate_exit_prices_buy_percentage():
    target, sl = calculate_exit_prices(100.0, "BUY", "percentage", 10.0, "percentage", 5.0)
    assert target == 110.0
    assert sl == 95.0

def test_calculate_exit_prices_sell_percentage():
    target, sl = calculate_exit_prices(100.0, "SELL", "percentage", 10.0, "percentage", 5.0)
    assert target == 90.0
    assert sl == 105.0

def test_calculate_exit_prices_buy_absolute():
    target, sl = calculate_exit_prices(100.0, "BUY", "absolute", 120.0, "absolute", 80.0)
    assert target == 120.0
    assert sl == 80.0

def test_calculate_exit_prices_sell_absolute():
    target, sl = calculate_exit_prices(100.0, "SELL", "absolute", 80.0, "absolute", 120.0)
    assert target == 80.0
    assert sl == 120.0

def test_schema_valid_payload():
    schema = BracketOrderSchema()
    data = {
        "apikey": "test_key",
        "strategy": "test_strat",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "target_type": "points",
        "target_value": 5.0,
        "sl_type": "points",
        "sl_value": 3.0
    }
    result = schema.load(data)
    assert result["price_type"] == "MARKET"
    assert result["product"] == "MIS"
    assert result["price"] == 0.0

def test_schema_invalid_target_type():
    schema = BracketOrderSchema()
    data = {
        "apikey": "test_key",
        "strategy": "test_strat",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "target_type": "invalid",
        "target_value": 5.0,
        "sl_type": "points",
        "sl_value": 3.0
    }
    with pytest.raises(ValidationError) as exc:
        schema.load(data)
    assert "target_type" in exc.value.messages

def test_schema_missing_required():
    schema = BracketOrderSchema()
    data = {
        "apikey": "test_key",
        "strategy": "test_strat",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "target_type": "points",
        "target_value": 5.0
        # sl_type and sl_value missing
    }
    with pytest.raises(ValidationError) as exc:
        schema.load(data)
    assert "sl_type" in exc.value.messages
    assert "sl_value" in exc.value.messages
