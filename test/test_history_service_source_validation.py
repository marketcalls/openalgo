import pytest

from services import history_service


def _history_request() -> dict:
    return {
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "interval": "1m",
        "start_date": "2026-08-01",
        "end_date": "2026-08-22",
        "auth_token": "test-token",
        "feed_token": "test-feed-token",
        "broker": "test-broker",
    }


def test_api_source_calls_api_provider(monkeypatch):
    provider_calls = []
    monkeypatch.setattr(history_service, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr(
        history_service,
        "get_history_with_auth",
        lambda *args: provider_calls.append(args) or (True, {"provider": "api"}, 200),
    )

    result = history_service.get_history(**_history_request(), source="api")

    assert result == (True, {"provider": "api"}, 200)
    assert provider_calls == [
        (
            "test-token",
            "test-feed-token",
            "test-broker",
            "NIFTY",
            "NSE_INDEX",
            "1m",
            "2026-08-01",
            "2026-08-22",
        )
    ]


def test_default_source_calls_api_provider(monkeypatch):
    monkeypatch.setattr(history_service, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr(
        history_service,
        "get_history_with_auth",
        lambda *args: (True, {"provider": "api"}, 200),
    )

    assert history_service.get_history(**_history_request()) == (
        True,
        {"provider": "api"},
        200,
    )


def test_db_source_calls_database_provider(monkeypatch):
    provider_calls = []

    def fake_database_provider(**kwargs):
        provider_calls.append(kwargs)
        return True, {"provider": "db"}, 200

    monkeypatch.setattr(
        history_service,
        "get_history_from_db",
        fake_database_provider,
    )

    result = history_service.get_history(**_history_request(), source="db")

    assert result == (True, {"provider": "db"}, 200)
    assert provider_calls == [
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "interval": "1m",
            "start_date": "2026-08-01",
            "end_date": "2026-08-22",
        }
    ]


@pytest.mark.parametrize("source", ["cache", "", None, 123, [], {}])
def test_invalid_sources_call_neither_provider(monkeypatch, source):
    monkeypatch.setattr(
        history_service,
        "get_history_from_db",
        lambda *args, **kwargs: pytest.fail("database provider should not be called"),
    )
    monkeypatch.setattr(
        history_service,
        "get_history_with_auth",
        lambda *args, **kwargs: pytest.fail("API provider should not be called"),
    )
    monkeypatch.setattr(
        history_service,
        "_enforce_rate_limit",
        lambda: pytest.fail("rate limiting should not run for an invalid source"),
    )

    success, response, status_code = history_service.get_history(
        **_history_request(), source=source
    )

    assert success is False
    assert status_code == 400
    assert response == {
        "status": "error",
        "message": "Source must be either 'api' or 'db'.",
    }
