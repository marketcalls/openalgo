"""Sahi order-update adapter: frame normalization, handshake and factory.

The frames follow the sample under "WSS /v1/stream/orders -- Order updates"
in broker-api-docs/sahi-api-docs/02-api-reference.md: one JSON order object
shaped like an element of GET /v1/orders, prices in paise.
"""

import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# websocket_proxy and broker/*/streaming import each other; load the proxy
# package first, as services/order_update_service.py does.
importlib.import_module("websocket_proxy")
mod = importlib.import_module("broker.sahi.streaming.sahi_order_adapter")
order_data = importlib.import_module("broker.sahi.mapping.order_data")

DOC_FRAME = {
    "order_id": "26101900133912345678",
    "exchange_order_id": "1300000123456789",
    "exchange_segment": "NSE",
    "symbol": "RELIANCE",
    "txn_type": "B",
    "order_type": "LMT",
    "product": "I",
    "validity": "DAY",
    "qty": 10,
    "disclosed_qty": 0,
    "filled_qty": 10,
    "price": 250000,
    "trigger_price": 0,
    "avg_price": 249975,
    "status": "Completed",
    "rejection_reason": None,
    "created_at": 1747798201123,
    "placed_at": 1747798201456,
    "completed_at": 1747798205890,
    "cancelled_at": None,
    "rejected_at": None,
    "last_modified_at": 1747798205890,
}


def frame(**overrides):
    return json.dumps({**DOC_FRAME, **overrides})


@pytest.fixture(autouse=True)
def symbol_lookup():
    # The order book's mapping resolves (symbol, exchange_segment) through the
    # master contract; stand in for it so no database is needed.
    with patch.object(
        order_data, "get_oa_symbol", side_effect=lambda brsymbol, exchange: brsymbol
    ) as m:
        yield m


@pytest.fixture
def adapter():
    return mod.SahiOrderUpdateAdapter(user_id="trader", access_token="jwt-token")


def test_doc_sample_maps_to_openalgo_fields(adapter):
    assert adapter.normalize(frame()) == {
        "orderid": "26101900133912345678",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "price": 2500.0,
        "trigger_price": 0.0,
        "pricetype": "LIMIT",
        "product": "MIS",
        "order_status": "complete",
        "filled_quantity": 10,
        "pending_quantity": 0,
        "average_price": 2499.75,
        "rejection_reason": "",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Open", "open"),
        ("OpenPartial", "open"),
        ("AwaitingTrigger", "trigger pending"),
        ("PartialFilled", "cancelled"),
        ("Completed", "complete"),
        ("Cancelled", "cancelled"),
        ("Rejected", "rejected"),
    ],
)
def test_status_matches_the_order_book(adapter, status, expected):
    event = adapter.normalize(frame(status=status))
    assert event["order_status"] == expected
    assert event["order_status"] == order_data.map_order_status(status)


def test_working_order_reports_unfilled_quantity_as_pending(adapter):
    event = adapter.normalize(frame(status="OpenPartial", qty=10, filled_qty=4))
    assert event["filled_quantity"] == 4
    assert event["pending_quantity"] == 6


@pytest.mark.parametrize("status", ["PartialFilled", "Cancelled", "Rejected", "Completed"])
def test_finished_order_has_nothing_pending(adapter, status):
    assert adapter.normalize(frame(status=status, qty=10, filled_qty=4))["pending_quantity"] == 0


def test_rejection_reason_passes_through(adapter):
    event = adapter.normalize(
        frame(
            status="Rejected", filled_qty=0, avg_price=0, rejection_reason="RMS: margin shortfall"
        )
    )
    assert event["order_status"] == "rejected"
    assert event["rejection_reason"] == "RMS: margin shortfall"


@pytest.mark.parametrize(
    ("order_type", "product", "pricetype", "oa_product"),
    [
        ("MKT", "C", "MARKET", "CNC"),
        ("SL-LMT", "M", "SL", "NRML"),
        ("SL-MKT", "I", "SL-M", "MIS"),
    ],
)
def test_order_type_and_product_codes(adapter, order_type, product, pricetype, oa_product):
    event = adapter.normalize(frame(order_type=order_type, product=product, trigger_price=249000))
    assert event["pricetype"] == pricetype
    assert event["product"] == oa_product
    assert event["trigger_price"] == 2490.0


def test_sell_and_derivative_segment(adapter, symbol_lookup):
    symbol_lookup.side_effect = lambda brsymbol, exchange: "NIFTY25NOV2624000CE"
    event = adapter.normalize(frame(txn_type="S", exchange_segment="NFO", symbol="NIFTY 24000 CE"))
    assert event["action"] == "SELL"
    assert event["exchange"] == "NFO"
    assert event["symbol"] == "NIFTY25NOV2624000CE"


def test_bytes_frame_is_accepted(adapter):
    assert adapter.normalize(frame().encode())["orderid"] == "26101900133912345678"


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", json.dumps({"status": "Open"}), "null"])
def test_non_order_frames_are_ignored(adapter, raw):
    assert adapter.normalize(raw) is None


def test_handshake_targets_order_stream_with_bearer_and_user_agent(adapter):
    assert adapter.get_ws_url() == "wss://direct.sahi.com/v1/stream/orders"
    headers = adapter.get_headers()
    assert headers["Authorization"] == "Bearer jwt-token"
    assert headers["User-Agent"]
    # No login or subscribe frame and no app-level heartbeat: the server pushes
    # on connect and pings on its own.
    assert adapter.heartbeat_interval() is None


def test_message_publishes_order_update_event(adapter):
    with patch.object(adapter, "_publish_event_fields") as publish:
        adapter._handle_message(frame(status="Open", filled_qty=0))
    fields = publish.call_args.args[0]
    assert fields["orderid"] == "26101900133912345678"
    assert fields["order_status"] == "open"


def test_factory_without_session_returns_none():
    with patch.object(mod, "get_auth_token", return_value=None):
        assert mod.create_sahi_order_adapter("trader") is None


def test_factory_builds_adapter_from_stored_token():
    with patch.object(mod, "get_auth_token", return_value="jwt-token") as read:
        built = mod.create_sahi_order_adapter("trader")
    read.assert_called_once_with("trader", bypass_cache=True)
    assert isinstance(built, mod.SahiOrderUpdateAdapter)
    assert built.get_headers()["Authorization"] == "Bearer jwt-token"
