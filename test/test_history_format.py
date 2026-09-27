"""The history service always returns records shaped the same way, whatever the broker sends.

Every broker's BrokerData.get_history returns its own DataFrame, so
get_history_with_auth is the single place that normalises the result: it rejects
anything that is not a DataFrame, stamps in an 'oi' column when the broker omits
one, and serialises to a list of records. These tests pin that contract down with
a stub broker module, so no server, network or credentials are involved.
"""

import pandas as pd
import pytest

from services import history_service

CANDLE = {
    "timestamp": 1_700_000_000,
    "open": 100.0,
    "high": 101.5,
    "low": 99.5,
    "close": 101.0,
    "volume": 1_000,
}


def stub_broker(df):
    """Build a stand-in for a broker's api.data module whose get_history returns df."""

    class BrokerData:
        def __init__(self, auth_token, feed_token=None):
            self.auth_token = auth_token
            self.feed_token = feed_token

        def get_history(self, symbol, exchange, interval, start_date, end_date):
            return df

    return type("StubBrokerModule", (), {"BrokerData": BrokerData})


@pytest.fixture
def broker(monkeypatch):
    """Install a stub broker module and a resolvable symbol; return a caller for the service."""

    def call(df):
        monkeypatch.setattr(history_service, "get_token", lambda _symbol, _exchange: "12345")
        monkeypatch.setattr(
            history_service, "import_broker_module", lambda _broker: stub_broker(df)
        )
        return history_service.get_history_with_auth(
            auth_token="token",
            feed_token="feed",
            broker="stub",
            symbol="RELIANCE",
            exchange="NSE",
            interval="5m",
            start_date="2026-01-01",
            end_date="2026-01-05",
        )

    return call


def test_history_is_returned_as_success_records(broker):
    success, response, status = broker(pd.DataFrame([CANDLE]))

    assert success is True
    assert status == 200
    assert response["status"] == "success"
    assert response["data"] == [{**CANDLE, "oi": 0}]


def test_missing_oi_column_defaults_to_zero(broker):
    success, response, status = broker(pd.DataFrame([CANDLE, CANDLE]))

    assert (success, status) == (True, 200)
    assert [record["oi"] for record in response["data"]] == [0, 0]


def test_broker_supplied_oi_is_preserved(broker):
    success, response, status = broker(pd.DataFrame([{**CANDLE, "oi": 4_200}]))

    assert (success, status) == (True, 200)
    assert response["data"][0]["oi"] == 4_200


@pytest.mark.parametrize("malformed", [None, {"data": [CANDLE]}, [CANDLE], "not a dataframe"])
def test_non_dataframe_from_broker_is_reported_as_an_error(broker, malformed):
    success, response, status = broker(malformed)

    assert success is False
    assert status == 500
    assert response == {
        "status": "error",
        "message": "Invalid data format returned from broker",
    }
