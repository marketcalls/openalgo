import json
import os
import sys
from pathlib import Path

os.environ.setdefault("API_KEY_PEPPER", "test-pepper-value-at-least-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import broker.dhan.api.margin_api as margin_api  # noqa: E402
import broker.dhan.mapping.margin_data as margin_data  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.status = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_calculate_margin_api_routes_single_position_to_single_api(monkeypatch):
    position = {
        "symbol": "NIFTY30JUN26FUT",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": "65",
        "product": "NRML",
        "pricetype": "MARKET",
    }
    transformed = {
        "dhanClientId": "client-1",
        "exchangeSegment": "NSE_FNO",
        "transactionType": "BUY",
        "quantity": 65,
        "productType": "MARGIN",
        "securityId": "71470",
        "price": 0.0,
    }
    captured = {}

    monkeypatch.setattr(margin_api, "get_client_id", lambda api_key=None: "client-1")
    monkeypatch.setattr(margin_api, "transform_margin_position", lambda pos, client_id: transformed)
    monkeypatch.setattr(
        margin_api,
        "calculate_single_margin",
        lambda pos, auth, client_id: captured.update(
            {"pos": pos, "auth": auth, "client_id": client_id}
        )
        or (
            FakeResponse(200, {}),
            {
                "status": "success",
                "data": {
                    "total_margin_required": 100.0,
                    "span_margin": 80.0,
                    "exposure_margin": 20.0,
                },
            },
        ),
    )
    monkeypatch.setattr(
        margin_api,
        "calculate_basket_margin",
        lambda *args: (_ for _ in ()).throw(AssertionError("basket should not run")),
    )

    response, payload = margin_api.calculate_margin_api([position], "auth-token")

    assert response.status_code == 200
    assert payload["status"] == "success"
    assert captured == {"pos": transformed, "auth": "auth-token", "client_id": "client-1"}


def test_calculate_margin_api_routes_multi_position_to_basket_api(monkeypatch):
    positions = [
        {
            "symbol": "NIFTY30JUN2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "quantity": "65",
            "product": "NRML",
            "pricetype": "MARKET",
        },
        {
            "symbol": "NIFTY30JUN2624000PE",
            "exchange": "NFO",
            "action": "SELL",
            "quantity": "65",
            "product": "NRML",
            "pricetype": "MARKET",
        },
    ]
    transformed_positions = [
        {"securityId": "71472", "transactionType": "SELL"},
        {"securityId": "71473", "transactionType": "SELL"},
    ]
    captured = {}

    monkeypatch.setattr(margin_api, "get_client_id", lambda api_key=None: "client-1")
    def fake_transform(pos, client_id):
        idx = len(captured.setdefault("seen", []))
        captured["seen"].append((pos["symbol"], client_id))
        return transformed_positions[idx]

    monkeypatch.setattr(margin_api, "transform_margin_position", fake_transform)
    monkeypatch.setattr(
        margin_api,
        "calculate_single_margin",
        lambda *args: (_ for _ in ()).throw(AssertionError("single should not run")),
    )
    monkeypatch.setattr(
        margin_api,
        "calculate_basket_margin",
        lambda pos, auth, client_id: captured.update(
            {"pos": pos, "auth": auth, "client_id": client_id}
        )
        or (
            FakeResponse(200, {}),
            {
                "status": "success",
                "data": {
                    "total_margin_required": 250.0,
                    "span_margin": 200.0,
                    "exposure_margin": 50.0,
                },
            },
        ),
    )

    response, payload = margin_api.calculate_margin_api(positions, "auth-token")

    assert response.status_code == 200
    assert payload["status"] == "success"
    assert captured["pos"] == transformed_positions
    assert captured["auth"] == "auth-token"
    assert captured["client_id"] == "client-1"


def test_calculate_basket_margin_uses_dhan_multi_payload(monkeypatch):
    calls = {}

    class FakeClient:
        def post(self, url, headers, content):
            calls["url"] = url
            calls["headers"] = headers
            calls["content"] = content
            return FakeResponse(
                200,
                {
                    "total_margin": "150000.00",
                    "span_margin": "50000.00",
                    "exposure_margin": "30000.00",
                    "hedge_benefit": "25000.00",
                    "currency": "INR",
                },
            )

    monkeypatch.setattr(margin_api, "get_url", lambda path: f"https://api.dhan.test{path}")
    monkeypatch.setattr(margin_api, "get_httpx_client", lambda: FakeClient())

    response, payload = margin_api.calculate_basket_margin(
        [{"securityId": "71472"}, {"securityId": "71473"}],
        "auth-token",
        "client-1",
    )

    assert response.status_code == 200
    assert calls["url"] == "https://api.dhan.test/v2/margincalculator/multi"
    assert calls["headers"]["access-token"] == "auth-token"
    body = json.loads(calls["content"])
    assert body["dhanClientId"] == "client-1"
    assert body["includePosition"] is True
    assert body["includeOrder"] is True
    assert body["scripList"] == [{"securityId": "71472"}, {"securityId": "71473"}]
    assert payload["status"] == "success"
    assert payload["data"] == {
        "total_margin_required": 150000.0,
        "span_margin": 50000.0,
        "exposure_margin": 30000.0,
    }


def test_basket_error_body_returns_non_200_response(monkeypatch):
    class FakeClient:
        def post(self, url, headers, content):
            return FakeResponse(
                200,
                {
                    "errorType": "Invalid_Authentication",
                    "errorMessage": "Client ID or access token is invalid or expired.",
                },
            )

    monkeypatch.setattr(margin_api, "get_url", lambda path: f"https://api.dhan.test{path}")
    monkeypatch.setattr(margin_api, "get_httpx_client", lambda: FakeClient())

    response, payload = margin_api.calculate_basket_margin(
        [{"securityId": "71472"}, {"securityId": "71473"}],
        "expired-token",
        "client-1",
    )

    assert response.status_code == 400
    assert payload["status"] == "error"
    assert "invalid or expired" in payload["message"]


def test_transform_margin_position_accepts_openalgo_option_and_future_symbols(monkeypatch):
    tokens = {
        ("NIFTY30JUN2624000CE", "NFO"): "71472",
        ("NIFTY30JUN2624000PE", "NFO"): "71473",
        ("NIFTY30JUN26FUT", "NFO"): "62329",
    }
    monkeypatch.setattr(
        margin_data,
        "get_token",
        lambda symbol, exchange: tokens.get((symbol, exchange)),
    )

    common = {
        "exchange": "NFO",
        "action": "SELL",
        "quantity": "65",
        "product": "NRML",
        "pricetype": "MARKET",
    }

    ce = margin_data.transform_margin_position(
        {"symbol": "NIFTY30JUN2624000CE", **common}, "client-1"
    )
    pe = margin_data.transform_margin_position(
        {"symbol": "NIFTY30JUN2624000PE", **common}, "client-1"
    )
    fut = margin_data.transform_margin_position(
        {"symbol": "NIFTY30JUN26FUT", **common, "action": "BUY"}, "client-1"
    )

    assert ce["exchangeSegment"] == "NSE_FNO"
    assert ce["securityId"] == "71472"
    assert pe["securityId"] == "71473"
    assert fut["securityId"] == "62329"
    assert fut["transactionType"] == "BUY"
