"""A broker postback is accepted only when its payload proves who sent it.

``POST /postback/<broker>`` is public: a broker cannot hold an OpenAlgo
session. An accepted postback is published as a live ``OrderUpdateEvent``,
which the strategy engine applies to its orders by broker order id and which
can fire an order-placing Flow workflow. The only gate used to be that the
broker in the URL was the one logged in, and only Zerodha's payload carries a
signature. For Dhan, Fyers, Upstox, Angel and AliceBlue anybody who could
reach the server could post a fill that never happened.

Those five are refused now, before anything is read; their updates come
through the order WebSocket adapters. Every test asserts what reached the
event bus, since that is where a forged update does its damage.
"""

from __future__ import annotations

import hashlib
import types

import pytest
from flask import Flask

API_SECRET = "the-zerodha-api-secret"
UNSIGNED = ["dhan", "fyers", "upstox", "angel", "aliceblue"]

#: A filled order as each broker's postback names its fields: the shapes the
#: normalizers accept, so the unpatched route publishes every one of them. A
#: forger sends an order id learned elsewhere and a status of complete.
FORGED = {
    "dhan": {
        "orderId": "2",
        "orderStatus": "TRADED",
        "tradingSymbol": "SBIN",
        "exchangeSegment": "NSE_EQ",
        "transactionType": "BUY",
        "quantity": 1,
        "filled_qty": 1,
        "orderType": "MARKET",
        "productType": "CNC",
    },
    "fyers": {
        "id": "3",
        "status": 2,
        "symbol": "NSE:SBIN-EQ",
        "qty": 1,
        "filledQty": 1,
        "side": 1,
        "type": 2,
        "productType": "CNC",
        "exchange": 10,
        "segment": 10,
    },
    "upstox": {
        "update_type": "order",
        "order_id": "4",
        "status": "complete",
        "trading_symbol": "SBIN-EQ",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": 1,
        "filled_quantity": 1,
        "order_type": "MARKET",
        "product": "D",
    },
    "angel": {
        "orderid": "5",
        "orderstatus": "complete",
        "tradingsymbol": "SBIN-EQ",
        "exchange": "NSE",
        "transactiontype": "BUY",
        "quantity": "1",
        "filledshares": "1",
        "unfilledshares": "0",
        "ordertype": "MARKET",
        "producttype": "DELIVERY",
    },
    "aliceblue": {
        "norenordno": "6",
        "status": "Complete",
        "tsym": "SBIN-EQ",
        "exch": "NSE",
        "trantype": "B",
        "qty": 1,
        "fillshares": 1,
        "prctyp": "MKT",
        "pcode": "CNC",
    },
}


@pytest.fixture
def postbacks(monkeypatch):
    """The postback blueprint on an app of its own, with the bus recorded.

    ``active`` names the broker that is logged in; a test changes it to ask
    the same question of an instance on another broker.
    """
    import blueprints.postback as pb

    published: list = []
    active = {"broker": "dhan"}
    monkeypatch.setattr(pb.bus, "publish", lambda event: published.append(event))
    monkeypatch.setattr(
        pb,
        "_get_active_session",
        lambda: (
            types.SimpleNamespace(broker=active["broker"], name="trader")
            if active["broker"]
            else None
        ),
    )
    monkeypatch.setenv("BROKER_API_SECRET", API_SECRET)

    app = Flask(__name__)
    app.register_blueprint(pb.postback_bp)
    return types.SimpleNamespace(
        client=app.test_client(), published=published, active=active, module=pb
    )


def _zerodha_payload(secret: str = API_SECRET) -> dict:
    order_id, stamp = "240101000001", "2026-01-01 09:15:00"
    return {
        "order_id": order_id,
        "order_timestamp": stamp,
        "checksum": hashlib.sha256(f"{order_id}{stamp}{secret}".encode()).hexdigest(),
        "status": "COMPLETE",
        "tradingsymbol": "SBIN",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": 10,
        "filled_quantity": 10,
        "average_price": 800.5,
    }


def test_a_forged_fill_for_the_logged_in_broker_publishes_nothing(postbacks):
    """The defect itself: no credential, the right broker name, a live event."""
    postbacks.active["broker"] = "dhan"

    response = postbacks.client.post("/postback/dhan", json=FORGED["dhan"])

    assert postbacks.published == []
    assert response.status_code == 403


@pytest.mark.parametrize("broker", UNSIGNED)
def test_every_broker_without_a_signature_is_refused(postbacks, broker):
    postbacks.active["broker"] = broker

    response = postbacks.client.post(f"/postback/{broker}", json=FORGED[broker])

    assert postbacks.published == []
    assert response.status_code == 403


@pytest.mark.parametrize("broker", UNSIGNED + ["zerodha"])
def test_the_answer_does_not_tell_which_broker_is_logged_in(postbacks, broker):
    """Six requests used to reveal it: 403 for five brokers, 400 for the one."""
    answers = set()
    for logged_in in ("dhan", "zerodha", "upstox", None):
        postbacks.active["broker"] = logged_in
        payload = FORGED.get(broker) or _zerodha_payload("a-guess")
        response = postbacks.client.post(f"/postback/{broker}", json=payload)
        answers.add((response.status_code, response.get_data()))

    assert len(answers) == 1
    assert postbacks.published == []


def test_a_signed_zerodha_postback_is_published_as_before(postbacks):
    postbacks.active["broker"] = "zerodha"

    response = postbacks.client.post("/postback/zerodha", json=_zerodha_payload())

    assert response.status_code == 200
    assert len(postbacks.published) == 1
    event = postbacks.published[0]
    assert event.orderid == "240101000001"
    assert event.order_status == "complete"
    assert event.mode == "live"
    assert event.request_data == {"user_id": "trader"}


def test_a_zerodha_postback_signed_with_another_secret_is_refused(postbacks):
    postbacks.active["broker"] = "zerodha"

    response = postbacks.client.post("/postback/zerodha", json=_zerodha_payload("a-guess"))

    assert postbacks.published == []
    assert response.status_code == 403


def test_a_signed_zerodha_postback_changed_after_signing_is_still_bound_to_its_order(postbacks):
    """The checksum covers the order id and timestamp; another id fails it."""
    postbacks.active["broker"] = "zerodha"
    payload = _zerodha_payload()
    payload["order_id"] = "999999999999"

    response = postbacks.client.post("/postback/zerodha", json=payload)

    assert postbacks.published == []
    assert response.status_code == 403


def test_a_signed_zerodha_postback_while_another_broker_is_logged_in_is_refused(postbacks):
    postbacks.active["broker"] = "dhan"

    response = postbacks.client.post("/postback/zerodha", json=_zerodha_payload())

    assert postbacks.published == []
    assert response.status_code == 403


def test_a_zerodha_postback_with_no_secret_configured_is_refused(postbacks, monkeypatch):
    postbacks.active["broker"] = "zerodha"
    monkeypatch.delenv("BROKER_API_SECRET")

    response = postbacks.client.post("/postback/zerodha", json=_zerodha_payload(""))

    assert postbacks.published == []
    assert response.status_code == 403


def test_a_broker_is_verified_only_if_the_route_checks_its_signature():
    """Adding a name to VERIFIED_BROKERS without a check would reopen this."""
    import inspect

    import blueprints.postback as pb

    route = inspect.getsource(pb.broker_postback)
    for broker in pb.VERIFIED_BROKERS:
        assert f'broker == "{broker}" and not _validate_{broker}_checksum' in route
    assert pb.VERIFIED_BROKERS <= pb.SUPPORTED_BROKERS
