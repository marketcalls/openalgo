"""The shared alert formatter, and the WhatsApp text it must not change.

WhatsApp alerts were formatted in services/whatsapp_alert_service.py. That
code moved to services/alerts/formatting.py so Slack and Discord alerts share
it. ``fixtures/whatsapp_alert_golden.json`` holds the messages the old code
produced for 24 order events, recorded before the move with the clock pinned.
A trader on WhatsApp must receive exactly the same text.
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


@pytest.mark.parametrize("case", GOLDEN, ids=[f"{i}-{c['api_type']}" for i, c in enumerate(GOLDEN)])
def test_whatsapp_text_is_unchanged(case):
    message = build_message(case["api_type"], case["request"], case["response"], now=RECORDED_AT)

    assert WhatsAppAlertService.render(message) == case["message"]


def test_the_golden_corpus_covers_every_titled_order_type():
    covered = {case["api_type"] for case in GOLDEN}

    assert set(formatting.TITLES) <= covered


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
