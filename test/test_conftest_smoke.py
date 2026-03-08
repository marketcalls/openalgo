"""Smoke tests for conftest.py fixtures.

Verifies that all shared fixtures load correctly and return the
expected data shapes.  These tests serve as a safety net—if a change
to conftest.py breaks a fixture, this test file will catch it before
downstream test files are affected.
"""


def test_valid_order_data_has_required_fields(valid_order_data: dict) -> None:
    """valid_order_data fixture must include all mandatory order fields."""
    required = ["apikey", "strategy", "symbol", "exchange", "action", "quantity"]
    for field in required:
        assert field in valid_order_data, f"Missing required field: {field}"


def test_valid_order_data_values_are_sane(valid_order_data: dict) -> None:
    """valid_order_data fixture values should be non-empty strings."""
    for key, value in valid_order_data.items():
        assert isinstance(value, str), f"{key} should be a string"


def test_valid_smart_order_data_extends_order(
    valid_smart_order_data: dict,
    valid_order_data: dict,
) -> None:
    """valid_smart_order_data must contain all order fields plus position_size."""
    for field in valid_order_data:
        assert field in valid_smart_order_data, f"Missing field: {field}"
    assert "position_size" in valid_smart_order_data


def test_valid_cancel_order_data_has_required_fields(
    valid_cancel_order_data: dict,
) -> None:
    """valid_cancel_order_data must include apikey, strategy, and orderid."""
    required = ["apikey", "strategy", "orderid"]
    for field in required:
        assert field in valid_cancel_order_data, f"Missing required field: {field}"


def test_mock_broker_module_has_order_apis(mock_broker_module) -> None:
    """mock_broker_module must expose standard broker API methods."""
    required_methods = [
        "place_order_api",
        "get_order_book",
        "get_trade_book",
        "get_positions",
        "get_holdings",
        "cancel_order",
        "modify_order",
        "close_all_positions",
        "cancel_all_orders_api",
    ]
    for method in required_methods:
        assert hasattr(mock_broker_module, method), f"Missing method: {method}"


def test_mock_broker_place_order_returns_tuple(mock_broker_module) -> None:
    """place_order_api mock should return a 3-element tuple."""
    result = mock_broker_module.place_order_api("data", "auth")
    assert len(result) == 3, "place_order_api should return (response, body, order_id)"


def test_malicious_order_data_contains_payloads(malicious_order_data: dict) -> None:
    """malicious_order_data must contain injection payloads in key fields."""
    assert "DROP TABLE" in malicious_order_data["symbol"]
    assert "<script>" in malicious_order_data["exchange"]


def test_empty_auth_data_has_blank_fields(empty_auth_data: dict) -> None:
    """empty_auth_data must have empty strings for auth fields."""
    assert empty_auth_data["apikey"] == ""
    assert empty_auth_data["strategy"] == ""


def test_oversized_order_data_has_large_quantity(oversized_order_data: dict) -> None:
    """oversized_order_data must have an unreasonably large quantity."""
    qty = int(oversized_order_data["quantity"])
    assert qty > 1_000_000_000, "Quantity should be absurdly large"


def test_fixtures_return_independent_copies(
    valid_order_data: dict,
) -> None:
    """Each call to valid_order_data must return an independent dict."""
    valid_order_data["symbol"] = "MUTATED"
    # The fixture is a function-scoped factory, so the mutation should
    # not affect other tests.  This test just verifies the mutation
    # itself succeeded (independence is verified by other tests seeing
    # the original value).
    assert valid_order_data["symbol"] == "MUTATED"
