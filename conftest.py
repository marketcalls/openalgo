"""
Pytest configuration and fixtures for OpenAlgo test suite.
This file is automatically loaded by pytest.
"""

import os
import sys
from pathlib import Path

import pytest
from flask import Flask

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_env():
    """Set up test environment variables."""
    os.environ["TESTING"] = "true"
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["DATABASE_URL"] = "sqlite:///test_openalgo.db"
    os.environ["API_KEY_PEPPER"] = "test-pepper-for-testing-only"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["WTF_CSRF_ENABLED"] = "false"  # Disable CSRF for testing
    yield
    # Cleanup
    if os.path.exists("test_openalgo.db"):
        os.remove("test_openalgo.db")


@pytest.fixture(scope="session")
def app(test_env):
    """Create and configure a test Flask application instance."""
    from app import app as flask_app

    flask_app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": "localhost:5000",
        "PREFERRED_URL_SCHEME": "http",
    })

    yield flask_app


@pytest.fixture(scope="function")
def client(app):
    """Create a test client for the Flask application."""
    return app.test_client()


@pytest.fixture(scope="function")
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()


@pytest.fixture(scope="function")
def auth_headers():
    """Provide authentication headers for API testing."""
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-api-key",
    }


@pytest.fixture(scope="function")
def sample_order_data():
    """Sample order data for testing."""
    return {
        "apikey": "test-api-key",
        "strategy": "test_strategy",
        "symbol": "SBIN-EQ",
        "action": "BUY",
        "exchange": "NSE",
        "pricetype": "MARKET",
        "product": "MIS",
        "quantity": "1",
    }


@pytest.fixture(scope="function")
def mock_broker_response():
    """Mock broker API response."""
    return {
        "status": "success",
        "orderid": "123456789",
    }


# Pytest hooks
def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically."""
    for item in items:
        # Auto-mark tests based on directory
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Auto-mark broker tests
        if "broker" in str(item.fspath):
            item.add_marker(pytest.mark.broker)

        # Auto-mark API tests
        if "api" in item.name.lower() or "restx_api" in str(item.fspath):
            item.add_marker(pytest.mark.api)
