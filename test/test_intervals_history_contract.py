import pytest
from marshmallow import ValidationError

from restx_api.data_schemas import HistorySchema
from services import intervals_service


class _BrokerData:
    """Credential-free broker fixture with canonical advertised intervals."""

    def __init__(self, auth_token: str):
        self.timeframe_map = {
            "30m": "30minute",
            "60m": "60minute",
            "4h": "4hour",
            "6h": "6hour",
            "D": "day",
        }


class _BrokerModule:
    BrokerData = _BrokerData


def _history_request(interval: str) -> dict:
    return {
        "apikey": "test-api-key",
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "interval": interval,
        "start_date": "2026-08-01",
        "end_date": "2026-08-22",
    }


@pytest.mark.parametrize(
    "interval",
    [
        "1s",
        "5s",
        "10s",
        "15s",
        "30s",
        "45s",
        "1m",
        "2m",
        "3m",
        "5m",
        "10m",
        "15m",
        "20m",
        "30m",
        "1h",
        "2h",
        "3h",
        "4h",
        "D",
        "W",
        "M",
        "Q",
        "Y",
    ],
)
def test_history_schema_keeps_existing_intervals_valid(interval: str):
    assert HistorySchema().load(_history_request(interval))["interval"] == interval


def test_broker_advertised_intervals_are_requestable(monkeypatch):
    monkeypatch.setattr(
        intervals_service, "import_broker_module", lambda broker_name: _BrokerModule
    )

    success, response, status_code = intervals_service.get_intervals_with_auth(
        auth_token="test-token", broker="test-broker"
    )

    assert success is True
    assert status_code == 200
    advertised_intervals = response["data"]["minutes"] + response["data"]["hours"]
    assert advertised_intervals == ["30m", "60m", "4h", "6h"]

    for interval in advertised_intervals:
        assert HistorySchema().load(_history_request(interval))["interval"] == interval


def test_history_schema_rejects_unsupported_intervals():
    with pytest.raises(ValidationError):
        HistorySchema().load(_history_request("7h"))
