"""Regression tests for interval service response contracts."""

from types import SimpleNamespace

import services.intervals_service as intervals_service


def broker_module_with_timeframes(timeframe_map):
    return SimpleNamespace(
        BrokerData=lambda auth_token: SimpleNamespace(timeframe_map=timeframe_map)
    )


def test_intervals_group_and_sort_canonical_timeframes(monkeypatch):
    """Sort canonical intervals within their response categories."""
    timeframe_map = {
        "15m": "provider-15-minute",
        "1h": "provider-60-minute",
        "60m": "provider-60-minute",
        "5m": "provider-5-minute",
        "4h": "provider-4-hour",
        "D": "provider-day",
        "1m": "provider-1-minute",
        "W": "provider-week",
        "M": "provider-month",
        "30s": "provider-30-second",
        "5s": "provider-5-second",
    }
    monkeypatch.setattr(
        intervals_service,
        "import_broker_module",
        lambda broker: broker_module_with_timeframes(timeframe_map),
    )

    success, response, status_code = intervals_service.get_intervals_with_auth(
        "test-auth-token", "test-broker"
    )

    assert success is True
    assert status_code == 200
    assert response == {
        "status": "success",
        "data": {
            "seconds": ["5s", "30s"],
            "minutes": ["1m", "5m", "15m", "60m"],
            "hours": ["1h", "4h"],
            "days": ["D"],
            "weeks": ["W"],
            "months": ["M"],
        },
    }


def test_intervals_look_up_broker_from_api_key(monkeypatch):
    """Resolve the broker name before loading its interval plugin."""
    requested_brokers = []
    monkeypatch.setattr(
        intervals_service,
        "get_auth_token_broker",
        lambda api_key: ("test-auth-token", "test-broker"),
    )

    def import_broker_module(broker):
        requested_brokers.append(broker)
        return broker_module_with_timeframes({"1m": "provider-1-minute"})

    monkeypatch.setattr(intervals_service, "import_broker_module", import_broker_module)

    success, response, status_code = intervals_service.get_intervals(api_key="test-api-key")

    assert success is True
    assert status_code == 200
    assert response["data"]["minutes"] == ["1m"]
    assert requested_brokers == ["test-broker"]


def test_intervals_return_404_when_broker_module_is_missing(monkeypatch):
    """Return the documented error when a broker plugin is unavailable."""
    monkeypatch.setattr(intervals_service, "import_broker_module", lambda broker: None)

    success, response, status_code = intervals_service.get_intervals_with_auth(
        "test-auth-token", "unknown-broker"
    )

    assert success is False
    assert status_code == 404
    assert response == {"status": "error", "message": "Broker-specific module not found"}


def test_intervals_return_500_when_broker_plugin_fails(monkeypatch):
    """Return the documented error when plugin setup raises an exception."""

    def raise_plugin_error(auth_token):
        raise RuntimeError("plugin initialization failed")

    monkeypatch.setattr(
        intervals_service,
        "import_broker_module",
        lambda broker: SimpleNamespace(BrokerData=raise_plugin_error),
    )

    success, response, status_code = intervals_service.get_intervals_with_auth(
        "test-auth-token", "failing-broker"
    )

    assert success is False
    assert status_code == 500
    assert response == {"status": "error", "message": "plugin initialization failed"}


def test_intervals_reject_invalid_api_key(monkeypatch):
    """Reject an API key that cannot be resolved to a broker token."""
    monkeypatch.setattr(intervals_service, "get_auth_token_broker", lambda api_key: (None, None))

    success, response, status_code = intervals_service.get_intervals(api_key="bad-key")

    assert success is False
    assert status_code == 403
    assert response == {"status": "error", "message": "Invalid openalgo apikey"}


def test_intervals_reject_missing_parameters():
    """Require an API key or a complete direct-authentication pair."""
    success, response, status_code = intervals_service.get_intervals()

    assert success is False
    assert status_code == 400
    assert response["message"] == "Either api_key or both auth_token and broker must be provided"
