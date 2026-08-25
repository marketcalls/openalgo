from types import SimpleNamespace

from flask import Flask

from restx_api import ticker


def test_ticker_rejects_an_interval_unsupported_by_the_selected_broker(monkeypatch):
    calls = []

    class BrokerData:
        def __init__(self, auth_token):
            self.timeframe_map = {"D": "day"}

        def get_history(self, *args):
            calls.append(args)

    monkeypatch.setattr(ticker, "get_auth_token_broker", lambda _: ("auth-token", "groww"))
    monkeypatch.setattr(
        ticker,
        "import_broker_module",
        lambda _: SimpleNamespace(BrokerData=BrokerData),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/v1/ticker/NSE:RELIANCE?apikey=test-api-key&interval=60m&from=2026-08-01&to=2026-08-22"
    ):
        get = getattr(ticker.Ticker.get, "__wrapped__", ticker.Ticker.get)
        response = get(ticker.Ticker(), "NSE:RELIANCE")

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "Unsupported interval '60m' for broker 'groww'. Supported intervals: D.",
    }
    assert calls == []
