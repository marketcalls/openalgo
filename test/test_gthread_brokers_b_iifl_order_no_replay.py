"""IIFL Capital never sends an order write twice on a "try again" reply.

``order_api._request`` retried every method whenever the reply looked like a
rate limit, and the fallback test for one is a message containing "try after
some time". IIFL's generic EC003 error reads "Something went wrong, please try
after some time", and neither it nor an HTTP 429 proves the order did not
reach IIFL. So a place, modify or cancel could go out up to four times.

Reads are still retried. Under the gthread worker order writes are answered
once, with a message telling the trader to check the order book before sending
again. The eventlet worker and the development server keep the old behaviour,
because gthread is opt-in and an install that has not chosen it sees no change;
the last cases pin that.
"""

from __future__ import annotations

import os

import pytest

from broker.iiflcapital.api import order_api
from utils import runtime

EC003 = {"status": "EC003", "message": "Something went wrong, please try after some time"}


class Reply:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.headers = {}
        self.text = str(body)

    def json(self):
        return self._body


class Client:
    """Answers each method from a queue of replies and counts the requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[str] = []

    def _answer(self, method):
        self.calls.append(method)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def get(self, url, **kwargs):
        return self._answer("GET")

    def post(self, url, **kwargs):
        return self._answer("POST")

    def put(self, url, **kwargs):
        return self._answer("PUT")

    def delete(self, url, **kwargs):
        return self._answer("DELETE")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        runtime, "_registered", {"worker_class": "gthread", "threads": 64, "pid": os.getpid()}
    )
    holder = {}

    def install(*replies):
        holder["client"] = Client(replies)
        monkeypatch.setattr(order_api, "get_httpx_client", lambda: holder["client"])
        return holder["client"]

    monkeypatch.setattr(order_api, "apply_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(order_api.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "2885")
    return install


ORDER = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": "1",
    "pricetype": "MARKET",
    "product": "MIS",
}


def _assert_unconfirmed(message: str):
    assert "order book" in message
    assert "429" not in message and "EC003" not in message


@pytest.mark.parametrize(
    "reply", [Reply(200, EC003), Reply(429, {"message": "Too many requests"})], ids=["ec003", "429"]
)
def test_a_placement_is_sent_once(client, reply):
    fake = client(reply)
    res, data, orderid = order_api.place_order_api(dict(ORDER), "tok")

    assert fake.calls == ["POST"]
    assert orderid is None and res.status != 200
    assert data["status"] == "error"
    _assert_unconfirmed(data["message"])


def test_a_modification_is_sent_once(client, monkeypatch):
    monkeypatch.setattr(order_api, "transform_modify_order_data", lambda data: {"x": 1})
    fake = client(Reply(200, EC003))

    data, status = order_api.modify_order({"orderid": "ABC123"}, "tok")

    assert fake.calls == ["PUT"]
    assert data["status"] == "error" and status != 200
    _assert_unconfirmed(data["message"])


def test_a_cancellation_is_sent_once(client):
    fake = client(Reply(429, {"message": "Too many requests"}))

    data, status = order_api.cancel_order("ABC123", "tok")

    assert fake.calls == ["DELETE"]
    assert data["status"] == "error" and status == 429
    _assert_unconfirmed(data["message"])


def test_a_read_is_still_retried(client):
    fake = client(
        Reply(429, {"message": "Too many requests"}),
        Reply(200, {"status": "SUCCESS", "result": [{"orderStatus": "OPEN"}]}),
    )

    book = order_api.get_order_book("tok")

    assert fake.calls == ["GET", "GET"]
    assert book["status"] == "SUCCESS"


def test_an_ordinary_rejection_passes_through_unchanged(client):
    """Only a throttle or retry reply is reworded; a real rejection is not."""
    fake = client(Reply(400, {"status": "error", "message": "Insufficient funds"}))

    res, data, orderid = order_api.place_order_api(dict(ORDER), "tok")

    assert fake.calls == ["POST"]
    assert data["message"] == "Insufficient funds"


@pytest.fixture
def dev_client(client, monkeypatch):
    monkeypatch.setattr(runtime, "_registered", None)
    assert not runtime.gthread_active()
    return client


def test_outside_gthread_a_throttled_write_is_retried_as_before(dev_client):
    fake = dev_client(
        Reply(429, {"message": "Too many requests"}),
        Reply(200, {"status": "SUCCESS", "result": {"brokerOrderId": "X1"}}),
    )

    order_api.place_order_api(dict(ORDER), "tok")

    assert fake.calls == ["POST", "POST"]


def test_outside_gthread_a_failed_cancel_keeps_the_broker_status(dev_client):
    dev_client(Reply(200, {"status": "error", "message": "Order already cancelled"}))

    data, status = order_api.cancel_order("ABC123", "tok")

    assert data["status"] == "error" and status == 200


def test_under_gthread_a_failed_cancel_answered_200_is_a_failure(client):
    client(Reply(200, {"status": "error", "message": "Order already cancelled"}))

    data, status = order_api.cancel_order("ABC123", "tok")

    assert data["status"] == "error" and status == 400
