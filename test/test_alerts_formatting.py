"""The shared alert formatter, and the WhatsApp text it must not change.

WhatsApp alerts were formatted in services/whatsapp_alert_service.py. That
code moved to services/alerts/formatting.py so Slack and Discord alerts share
it. ``fixtures/whatsapp_alert_golden.json`` holds the messages the old code
produced for 24 order events, recorded before the move with the clock pinned.
A trader on WhatsApp must receive exactly the same text.

GTT orders are the one deliberate change: the old code had no template for
them and sent a bare "Order Update" with the mode and the time and nothing
else. They are checked separately below.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from services.alerts import formatting
from services.alerts.formatting import AlertMessage, build_message
from services.whatsapp_alert_service import WhatsAppAlertService

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "whatsapp_alert_golden.json").read_text(encoding="utf-8")
)
RECORDED_AT = datetime(2026, 11, 11, 9, 15, 30)
UNCHANGED = [case for case in GOLDEN if case["api_type"] not in formatting.GTT_TYPES]


@pytest.mark.parametrize(
    "case", UNCHANGED, ids=[f"{i}-{c['api_type']}" for i, c in enumerate(UNCHANGED)]
)
def test_whatsapp_text_is_unchanged(case):
    message = build_message(case["api_type"], case["request"], case["response"], now=RECORDED_AT)

    assert WhatsAppAlertService.render(message) == case["message"]


def test_the_golden_corpus_covers_every_titled_order_type():
    covered = {case["api_type"] for case in UNCHANGED}

    assert set(formatting.TITLES) - formatting.GTT_TYPES <= covered


def test_a_gtt_alert_used_to_say_nothing_and_now_says_what_it_is():
    (old,) = [case for case in GOLDEN if case["api_type"] == "placegttorder"]
    assert old["message"].startswith("*Order Update*")

    request = {
        "symbol": "SBIN",
        "action": "BUY",
        "quantity": 10,
        "exchange": "NSE",
        "trigger_type": "OCO",
        "triggerprice_sl": 790.0,
        "triggerprice_tg": 850.0,
    }
    response = {"status": "success", "trigger_id": "G1", "mode": "live"}
    message = build_message("placegttorder", request, response, now=RECORDED_AT)

    assert message.title == "GTT Order Placed"
    assert message.lines == (
        "Symbol: SBIN",
        "Action: BUY",
        "Quantity: 10",
        "Exchange: NSE",
        "Trigger Type: OCO",
        "Stop Loss Trigger: 790.0",
        "Target Trigger: 850.0",
        "Trigger ID: G1",
        "Time: 09:15:30",
    )


def test_a_single_gtt_shows_only_its_own_trigger():
    message = build_message(
        "placegttorder",
        {"symbol": "SBIN", "trigger_type": "SINGLE", "triggerprice_tg": 850.0},
        {"status": "error", "message": "Price out of range"},
    )

    assert "Target Trigger: 850.0" in message.lines
    assert not any(line.startswith("Stop Loss Trigger") for line in message.lines)
    assert "Error: Price out of range" in message.lines


@pytest.mark.parametrize(
    ("api_type", "request_data", "response", "expected"),
    [
        (
            "modifygttorder",
            {"trigger_id": "G1", "symbol": "SBIN", "triggerprice_sl": 780.0},
            {"status": "success"},
            ["Trigger ID: G1", "Stop Loss Trigger: 780.0", "Modification Successful"],
        ),
        (
            "cancelgttorder",
            {"trigger_id": "G1"},
            {"status": "success"},
            ["Trigger ID: G1", "Cancellation Successful"],
        ),
        (
            "gtttriggered",
            {"symbol": "SBIN", "exchange": "NSE", "trigger_id": "G1", "trigger_prices": [790.0]},
            {"status": "success", "orderid": "77"},
            ["Trigger ID: G1", "Trigger Prices: 790.0", "Order ID: 77"],
        ),
        (
            "gttexpired",
            {"symbol": "SBIN", "exchange": "NSE", "trigger_id": "G1"},
            {"status": "success", "message": "GTT expired without firing"},
            ["Trigger ID: G1", "GTT expired without firing"],
        ),
    ],
)
def test_every_gtt_event_has_its_title_and_fields(api_type, request_data, response, expected):
    message = build_message(api_type, request_data, response)

    assert message.title == formatting.TITLES[api_type]
    for line in expected:
        assert line in message.lines


def test_an_unreadable_event_still_raises_an_alert():
    """A malformed response costs the detail, never the alert."""
    message = build_message("basketorder", {}, {"status": "success", "results": [None]})

    assert message == AlertMessage(
        title="Basket Order Executed", lines=("Order Type: basketorder", "Status: success")
    )


def test_the_mode_banner_follows_the_response():
    live = build_message("placeorder", {}, {"status": "success", "mode": "live"})
    analyze = build_message("placeorder", {}, {"status": "success", "mode": "analyze"})
    unmarked = build_message("placeorder", {}, {"status": "success"})

    assert live.banner == formatting.LIVE_BANNER
    assert analyze.banner == formatting.ANALYZE_BANNER
    assert unmarked.banner == formatting.LIVE_BANNER


def test_the_time_is_the_last_line():
    message = build_message("cancelorder", {"orderid": "1"}, {"status": "success"}, now=RECORDED_AT)

    assert message.lines[-1] == "Time: 09:15:30"
