import json

from broker.angel.api import order_api


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.payload = None

    def post(self, _url, **kwargs):
        self.payload = json.loads(kwargs["content"])
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _run(monkeypatch, response, orders):
    client = FakeClient(response)
    monkeypatch.setenv("BROKER_API_KEY", "test-key")
    monkeypatch.setattr(order_api, "get_token", lambda *_args: "token")
    monkeypatch.setattr(
        order_api,
        "transform_data",
        lambda *_args: {
            "apikey": "test-key",
            "tradingsymbol": "SBIN-EQ",
            "symboltoken": "3045",
            "transactiontype": "BUY",
            "exchange": "NSE",
            "quantity": "1",
            "variety": "NORMAL",
            "ordertype": "LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": "800",
            "triggerprice": "0",
        },
    )
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api, "get_order_book", lambda _auth: {"data": orders(client)})
    result = order_api.place_order_api({"symbol": "SBIN", "exchange": "NSE"}, "auth")
    return client, result


def test_partial_success_payload_recovers_only_matching_unique_tag(monkeypatch):
    response = FakeResponse(502, {"status": True})

    def matching_orders(client):
        return [
            {
                "ordertag": client.payload["ordertag"],
                "tradingsymbol": "SBIN-EQ",
                "symboltoken": "3045",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": 1,
                "orderid": "fresh-order",
            }
        ]

    client, (result, body, order_id) = _run(monkeypatch, response, matching_orders)

    assert len(client.payload["ordertag"]) < 20
    assert client.payload["ordertag"].startswith("oa")
    assert order_id == "fresh-order"
    assert result.status == 200
    assert body["status"] is True


def test_unmatched_ambiguous_response_is_not_reported_as_success(monkeypatch):
    response = FakeResponse(200, {"status": True})
    _client, (result, body, order_id) = _run(
        monkeypatch,
        response,
        lambda client: [
            {
                "ordertag": "openalgo",
                "tradingsymbol": "SBIN-EQ",
                "symboltoken": "3045",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": 1,
                "orderid": "older-order",
            }
        ],
    )

    assert order_id is None
    assert body["status"] == "unknown"
    assert result.status != 200


def test_explicit_rejection_does_not_run_reconciliation(monkeypatch):
    response = FakeResponse(200, {"status": False, "message": "rejected"})

    def fail_if_reconciled(_client):
        raise AssertionError("explicit rejection must not query the order book")

    _client, (_result, body, order_id) = _run(
        monkeypatch, response, fail_if_reconciled
    )

    assert body["status"] is False
    assert order_id is None
    assert _result.status == 500


def test_empty_response_recovers_order_by_unique_tag(monkeypatch):
    response = FakeResponse(502, None)

    def matching_orders(client):
        return [{
            "ordertag": client.payload["ordertag"],
            "tradingsymbol": "SBIN-EQ",
            "symboltoken": "3045",
            "exchange": "NSE",
            "transactiontype": "BUY",
            "quantity": "1",
            "orderid": "recovered-order",
        }]

    _client, (result, body, order_id) = _run(monkeypatch, response, matching_orders)

    assert result.status == 200
    assert body["status"] is True
    assert order_id == "recovered-order"


def test_reconciliation_rejects_field_mismatch_and_duplicate_tags(monkeypatch):
    for orders in (
        lambda client: [{
            "ordertag": client.payload["ordertag"],
            "tradingsymbol": "OTHER-EQ",
            "symboltoken": "3045",
            "exchange": "NSE",
            "transactiontype": "BUY",
            "quantity": "1",
            "orderid": "wrong-symbol",
        }],
        lambda client: [
            {
                "ordertag": client.payload["ordertag"],
                "tradingsymbol": "SBIN-EQ",
                "symboltoken": "3045",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": "1",
                "orderid": f"duplicate-{index}",
            }
            for index in range(2)
        ],
    ):
        _client, (result, body, order_id) = _run(
            monkeypatch, FakeResponse(502, None), orders
        )
        assert result.status != 200
        assert body["status"] == "unknown"
        assert order_id is None


def test_transport_error_reconciles_without_retry(monkeypatch):
    transport_error = order_api.httpx.TimeoutException("request timed out")

    def matching_orders(client):
        return [{
            "ordertag": client.payload["ordertag"],
            "tradingsymbol": "SBIN-EQ",
            "symboltoken": "3045",
            "exchange": "NSE",
            "transactiontype": "BUY",
            "quantity": 1,
            "orderid": "accepted-before-timeout",
        }]

    client, (result, body, order_id) = _run(
        monkeypatch, transport_error, matching_orders
    )

    assert len(client.payload["ordertag"]) < 20
    assert result.status == 200
    assert body["status"] is True
    assert order_id == "accepted-before-timeout"
