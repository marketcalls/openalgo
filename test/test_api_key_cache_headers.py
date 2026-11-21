"""Test that API key endpoints return proper cache-control headers for security."""

import json
from unittest.mock import MagicMock, patch

import pytest

from blueprints.apikey import api_key_bp
from blueprints.playground import playground_bp
from blueprints.websocket_example import websocket_bp


@pytest.fixture
def client(app):
    """Create a test client with mocked session."""
    return app.test_client()


@pytest.fixture
def mock_session():
    """Mock session data."""
    return {"user": "test-user"}


class TestAPIKeyEndpointCacheHeaders:
    """Test cache headers on API key endpoints."""

    def test_apikey_get_has_cache_headers(self, client, mock_session):
        """GET /apikey should return no-store and no-cache headers."""
        with client.session_transaction() as sess:
            sess.update(mock_session)

        with patch("database.auth_db.get_api_key_for_tradingview") as mock_get_key:
            mock_get_key.return_value = "test-token-not-real"
            with patch("database.auth_db.get_order_mode") as mock_get_mode:
                mock_get_mode.return_value = "auto"

                response = client.get(
                    "/apikey",
                    headers={"Accept": "application/json"},
                )

                assert response.status_code == 200
                assert response.headers.get("Cache-Control") == "no-store, max-age=0"
                assert response.headers.get("Pragma") == "no-cache"

    def test_apikey_post_has_cache_headers(self, client, mock_session):
        """POST /apikey should return no-store and no-cache headers."""
        with client.session_transaction() as sess:
            sess.update(mock_session)

        with patch("database.auth_db.upsert_api_key") as mock_upsert:
            mock_upsert.return_value = 1  # key_id

            response = client.post(
                "/apikey",
                json={"user_id": "test-user"},
                content_type="application/json",
            )

            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "no-store, max-age=0"
            assert response.headers.get("Pragma") == "no-cache"
            data = json.loads(response.data)
            assert "api_key" in data
            # Verify test value is used
            assert data["api_key"].startswith("test-") or len(data["api_key"]) == 64

    def test_playground_api_key_has_cache_headers(self, client, mock_session):
        """GET /playground/api-key should return no-store and no-cache headers."""
        with client.session_transaction() as sess:
            sess.update(mock_session)

        with patch("database.auth_db.get_api_key_for_tradingview") as mock_get_key:
            mock_get_key.return_value = "test-token-not-real"

            response = client.get("/playground/api-key")

            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "no-store, max-age=0"
            assert response.headers.get("Pragma") == "no-cache"

    def test_websocket_apikey_has_cache_headers(self, client, mock_session):
        """GET /api/websocket/apikey should return no-store and no-cache headers."""
        with client.session_transaction() as sess:
            sess.update(mock_session)

        with patch("database.auth_db.get_api_key_for_tradingview") as mock_get_key:
            mock_get_key.return_value = "test-token-not-real"

            response = client.get("/api/websocket/apikey")

            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "no-store, max-age=0"
            assert response.headers.get("Pragma") == "no-cache"

    def test_apikey_no_credentials_in_test(self, client, mock_session):
        """Verify tests use only test values, never real credentials."""
        with client.session_transaction() as sess:
            sess.update(mock_session)

        with patch("database.auth_db.upsert_api_key") as mock_upsert:
            mock_upsert.return_value = 1

            response = client.post(
                "/apikey",
                json={"user_id": "test-user"},
                content_type="application/json",
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            # Ensure no real keys are exposed in error logs or test output
            assert "your-real-key" not in str(data)
            assert "production-key" not in str(data)
