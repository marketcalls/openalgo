"""Shared pytest fixtures for OpenAlgo test suite.

Provides reusable test infrastructure including environment setup,
order data factories, mock broker modules, and security edge-case
fixtures.  All test files in the ``test/`` directory automatically
have access to these fixtures via pytest's conftest discovery.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so that ``import database``,
# ``import utils``, etc. resolve correctly when running ``pytest`` from
# the repository root.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── Environment Variables ─────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment variables for testing.

    This fixture runs automatically for every test so that modules
    which read ``os.getenv(...)`` at import time always find a value.
    All values are safe, non-production test defaults.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("BROKER_API_KEY", "test_api_key")
    monkeypatch.setenv("BROKER_API_SECRET", "test_api_secret")
    monkeypatch.setenv("API_KEY_PEPPER", "a" * 64)
    monkeypatch.setenv("APP_KEY", "test_app_key_for_session_security")
    monkeypatch.setenv("HOST_SERVER", "http://127.0.0.1:5000")
    monkeypatch.setenv("REDIRECT_URL", "http://127.0.0.1:5000/callback")
    monkeypatch.setenv("FLASK_ENV", "testing")


# ── Order Data Factories ─────────────────────────────────────────────────
@pytest.fixture
def valid_order_data() -> dict[str, str]:
    """Return a valid order payload with all mandatory fields.

    Returns a fresh copy each time so tests can mutate the dict
    without affecting other tests.

    Returns:
        Dictionary containing all required order fields with valid
        values suitable for unit testing.
    """
    return {
        "apikey": "test_api_key",
        "strategy": "TestStrategy",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "action": "BUY",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "10",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    }


@pytest.fixture
def valid_smart_order_data(valid_order_data: dict[str, str]) -> dict[str, str]:
    """Return a valid smart order payload including ``position_size``.

    Extends ``valid_order_data`` with the extra field required by the
    smart order endpoint.

    Returns:
        Dictionary containing all required smart order fields.
    """
    return {**valid_order_data, "position_size": "10"}


@pytest.fixture
def valid_cancel_order_data() -> dict[str, str]:
    """Return a valid cancel order payload.

    Returns:
        Dictionary containing all required cancel order fields.
    """
    return {
        "apikey": "test_api_key",
        "strategy": "TestStrategy",
        "orderid": "123456789",
    }


# ── Mock Broker Module ────────────────────────────────────────────────────
@pytest.fixture
def mock_broker_module() -> MagicMock:
    """Return a mock broker API module with sensible default return values.

    The mock pre-configures return values for the standard broker API
    functions (``place_order_api``, ``get_order_book``, ``cancel_order``,
    etc.) so that service-layer tests can run without a real broker
    connection.

    Returns:
        A ``MagicMock`` instance simulating a broker order API module.
    """
    module = MagicMock()
    module.place_order_api.return_value = (
        MagicMock(status=200),
        {"status": "success", "data": {"order_id": "12345"}},
        "12345",
    )
    module.get_order_book.return_value = {"status": "success", "data": []}
    module.get_trade_book.return_value = {"status": "success", "data": []}
    module.get_positions.return_value = {"status": True, "data": []}
    module.get_holdings.return_value = {"status": True, "data": []}
    module.cancel_order.return_value = (
        {"status": "success", "orderid": "12345"},
        200,
    )
    module.modify_order.return_value = (
        {"status": "success", "orderid": "12345"},
        200,
    )
    module.close_all_positions.return_value = (
        {"status": "success", "message": "All positions closed"},
        200,
    )
    module.cancel_all_orders_api.return_value = (
        {"status": "success", "message": "All orders cancelled"},
        200,
    )
    return module


# ── Security Edge-Case Fixtures ───────────────────────────────────────────
@pytest.fixture
def malicious_order_data() -> dict[str, str]:
    """Return order data with SQL injection and XSS payloads.

    Used to verify that input handling is safe against common
    injection attacks.  Tests consuming this fixture should assert
    that the application rejects or sanitises the data rather than
    processing it.

    Returns:
        Dictionary with attack payloads in key fields.
    """
    return {
        "apikey": "test_api_key",
        "strategy": "Test",
        "symbol": "'; DROP TABLE orders;--",
        "exchange": "<script>alert('xss')</script>",
        "action": "BUY",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "10",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    }


@pytest.fixture
def empty_auth_data() -> dict[str, str]:
    """Return order data with empty/blank authentication fields.

    Used to verify that empty API keys and missing strategy names
    are rejected before reaching the broker layer.

    Returns:
        Dictionary with empty strings for auth-sensitive fields.
    """
    return {
        "apikey": "",
        "strategy": "",
        "symbol": "",
        "exchange": "",
        "action": "",
        "quantity": "",
    }


@pytest.fixture
def oversized_order_data(valid_order_data: dict[str, str]) -> dict[str, str]:
    """Return order data with an absurdly large quantity.

    Used to verify that unreasonable order sizes are caught before
    being sent to the broker.

    Returns:
        Dictionary with a very large quantity value.
    """
    return {**valid_order_data, "quantity": "99999999999"}
