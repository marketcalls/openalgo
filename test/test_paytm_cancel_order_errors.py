import json

import pytest

from broker.paytm.api import order_api


def _order(status="Pending", order_no="OA123"):
    return {
        "order_no": order_no,
        "status": status,
        "txn_type": "BUY",
        "exchange": "NSE",
        "segment": "E",
        "product": "MIS",
        "security_id": "123",
        "quantity": "1",
        "validity": "DAY",
        "order_type": "LMT",
        "price": "100",
        "off_mkt_flag": "N",
        "mkt_type": "N",
        "serial_no": "1",
        "group_id": "1",
    }


@pytest.mark.parametrize("order_book", [None, {}, {"data": None}])
def test_cancel_order_returns_error_when_order_book_is_unavailable(monkeypatch, order_book):
    monkeypatch.setattr(order_api, "get_order_book", lambda _auth: order_book)

    response, status = order_api.cancel_order("OA123", "token")

    assert status == 500
    assert response == {"status": "error", "message": "Failed to fetch order book"}


@pytest.mark.parametrize("order_status", ["Pending", "OPEN", "TRIGGER PENDING", "MODIFIED"])
def test_cancel_order_accepts_supported_statuses(monkeypatch, order_status):
    monkeypatch.setattr(
        order_api, "get_order_book", lambda _auth: {"data": [_order(order_status)]}
    )
    monkeypatch.setattr(
        order_api,
        "get_api_response",
        lambda **_kwargs: {"status": "success", "data": [{"order_no": "OA123"}]},
    )

    response, status = order_api.cancel_order("OA123", "token")

    assert status == 200
    assert response == {"status": "success", "orderid": "OA123"}


def test_cancel_order_returns_400_for_non_cancellable_status(monkeypatch):
    monkeypatch.setattr(
        order_api, "get_order_book", lambda _auth: {"data": [_order("COMPLETE")]}
    )

    response, status = order_api.cancel_order("OA123", "token")

    assert status == 400
    assert "cannot be cancelled" in response["message"]


def test_cancel_order_returns_404_when_order_id_is_missing(monkeypatch):
    monkeypatch.setattr(
        order_api, "get_order_book", lambda _auth: {"data": [_order(order_no="OTHER")]}
    )

    response, status = order_api.cancel_order("OA123", "token")

    assert status == 404
    assert response["message"] == "Order OA123 not found"


def test_cancel_order_forwards_ext_info_unchanged(monkeypatch):
    ext_info = {"source": "mobile", "metadata": {"tag": "keep-me"}}
    order = _order()
    order["ext_info"] = ext_info
    captured = {}
    monkeypatch.setattr(order_api, "get_order_book", lambda _auth: {"data": [order]})

    def fake_cancel(**kwargs):
        captured.update(json.loads(kwargs["payload"]))
        return {"status": "success", "data": [{"order_no": "OA123"}]}

    monkeypatch.setattr(order_api, "get_api_response", fake_cancel)

    response, status = order_api.cancel_order("OA123", "token")

    assert status == 200
    assert response["orderid"] == "OA123"
    assert captured["ext_info"] == ext_info
