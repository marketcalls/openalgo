from types import SimpleNamespace

import services.intervals_service as intervals_service


def broker_module_with_timeframes(timeframe_map):
    return SimpleNamespace(
        BrokerData=lambda auth_token: SimpleNamespace(timeframe_map=timeframe_map)
    )


def test_intervals_group_and_sort_canonical_timeframes(monkeypatch):
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
    requested_brokers = []
    monkeypatch.setattr(
        intervals_service,
        "get_auth_token_broker",
        lambda api_key: ("test-auth-token", "test-broker"),
    )
    monkeypatch.setattr(
        intervals_service,
        "import_broker_module",
        lambda broker: (
            requested_brokers.append(broker)
            or broker_module_with_timeframes({"1m": "provider-1-minute"})
        ),
    )

    success, response, status_code = intervals_service.get_intervals(api_key="test-api-key")

    assert success is True
    assert status_code == 200
    assert response["data"]["minutes"] == ["1m"]
    assert requested_brokers == ["test-broker"]


def test_intervals_return_404_when_broker_module_is_missing(monkeypatch):
    monkeypatch.setattr(intervals_service, "import_broker_module", lambda broker: None)

    success, response, status_code = intervals_service.get_intervals_with_auth(
        "test-auth-token", "unknown-broker"
    )

    assert success is False
    assert status_code == 404
    assert response == {"status": "error", "message": "Broker-specific module not found"}


def test_intervals_return_500_when_broker_plugin_fails(monkeypatch):
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
