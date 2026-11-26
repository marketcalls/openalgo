"""AliceBlue tick and depth feeds: quote fields, per-level depth merge, OI and ltt.

Messages are the dk/df/tk/tf samples of aliceblue-api-docs/11-websocket.md,
sent through the adapter's own message handler with publish mocked.
"""

import json
import logging
import threading

import pytest

# websocket_proxy first: it imports the adapters in an order that avoids the
# broker package's import cycle.
import websocket_proxy  # noqa: F401
from broker.aliceblue.streaming.aliceblue_adapter import AliceblueWebSocketAdapter
from broker.aliceblue.streaming.aliceblue_mapping import (
    AliceBlueExchangeMapper,
    AliceBlueMessageMapper,
)

DK = {
    "t": "dk",
    "pp": "2",
    "ml": "1",
    "e": "NFO",
    "tk": "54957",
    "ts": "NIFTY28JUL22C16600",
    "ls": "50",
    "ti": "0.05",
    "c": "42.20",
    "lp": "76.40",
    "pc": "81.04",
    "uc": "469.90",
    "lc": "0.05",
    "ft": "1658910517",
    "oi": "7361100",
    "ltq": "50",
    "o": "37.65",
    "h": "98.00",
    "l": "22.00",
    "ap": "60.72",
    "v": "125888500",
    "ltt": "13:58:37",
    "tbq": "965400",
    "tsq": "980950",
    "bp1": "76.30",
    "sp1": "76.45",
    "bp2": "76.25",
    "sp2": "76.50",
    "bp3": "76.20",
    "sp3": "76.55",
    "bp4": "76.15",
    "sp4": "76.60",
    "bp5": "76.10",
    "sp5": "76.65",
    "bq1": "50",
    "sq1": "650",
    "bq2": "2000",
    "sq2": "1400",
    "bq3": "3800",
    "sq3": "2250",
    "bq4": "2000",
    "sq4": "3400",
    "bq5": "7350",
    "sq5": "2250",
    "bo1": "1",
    "so1": "2",
    "bo2": "9",
    "so2": "8",
    "bo3": "22",
    "so3": "12",
    "bo4": "12",
    "so4": "16",
    "bo5": "17",
    "so5": "7",
}


@pytest.fixture
def adapter():
    """Adapter without __init__: no broker session, no ZMQ socket, no websocket."""
    ad = AliceblueWebSocketAdapter.__new__(AliceblueWebSocketAdapter)
    ad.logger = logging.getLogger("test_aliceblue_quote_feed")
    ad.lock = threading.Lock()
    ad.subscriptions = {}
    ad.symbol_state = {}
    ad.market_snapshots = {}
    ad.exchange_mapper = AliceBlueExchangeMapper()
    ad.message_mapper = AliceBlueMessageMapper()
    ad.published = []
    ad.publish_market_data = lambda topic, data: ad.published.append((topic, data))
    return ad


def _subscribe(ad, modes, exchange="NFO", token="54957", symbol="NIFTY28JUL2216600CE"):
    ad.subscriptions[f"{exchange}|{token}"] = {
        "symbol": symbol,
        "exchange": exchange,
        "token": token,
        "mode": max(modes),
        "original_symbol": symbol,
        "original_exchange": exchange,
        "all_modes": set(modes),
    }


def _send(ad, msg):
    ad._handle_message(json.dumps(msg))
    return ad.published[-1]


def test_depth_ack_publishes_quote_fields_and_orders(adapter):
    _subscribe(adapter, {3})
    topic, data = _send(adapter, DK)

    assert topic == "NFO_NIFTY28JUL2216600CE_DEPTH"
    assert data["ltp"] == 76.40
    assert data["open"] == 37.65
    assert data["high"] == 98.00
    assert data["low"] == 22.00
    assert data["close"] == 42.20
    assert data["volume"] == 125888500
    assert data["average_price"] == 60.72
    assert data["total_buy_quantity"] == 965400
    assert data["total_sell_quantity"] == 980950
    assert data["last_quantity"] == 50
    assert data["percent_change"] == 81.04
    assert data["depth"]["buy"][0] == {"price": 76.30, "quantity": 50, "orders": 1}
    assert data["depth"]["sell"][4] == {"price": 76.65, "quantity": 2250, "orders": 7}


def test_depth_diff_merges_per_level_and_field(adapter):
    _subscribe(adapter, {3})
    _send(adapter, DK)
    # A df that changes the quantity of sell level 1 only, and ltp.
    topic, data = _send(
        adapter, {"t": "df", "e": "NFO", "tk": "54957", "lp": "76.55", "sq1": "900"}
    )

    sell = data["depth"]["sell"]
    buy = data["depth"]["buy"]
    assert len(sell) == 5 and len(buy) == 5
    assert sell[0] == {"price": 76.45, "quantity": 900, "orders": 2}
    assert sell[1] == {"price": 76.50, "quantity": 1400, "orders": 8}
    assert buy[0] == {"price": 76.30, "quantity": 50, "orders": 1}
    # Quote fields from the ack survive the diff.
    assert data["ltp"] == 76.55
    assert data["open"] == 37.65
    assert data["volume"] == 125888500


def test_open_interest_is_read_from_documented_oi_key(adapter):
    _subscribe(adapter, {2})
    tk = {
        "t": "tk",
        "e": "NFO",
        "tk": "54957",
        "ts": "NIFTY28JUL22C16600",
        "c": "42.20",
        "lp": "84.00",
        "pc": "99.05",
        "ft": "1658911102",
        "oi": "7606750",
        "o": "37.65",
        "h": "98.00",
        "l": "22.00",
        "ap": "61.35",
        "v": "129781850",
    }
    _, data = _send(adapter, tk)
    assert data["total_oi"] == 7606750
    assert data["oi"] == 7606750


def test_ltt_is_exchange_feed_time_and_omitted_when_absent(adapter):
    _subscribe(adapter, {1})
    _, data = _send(adapter, {"t": "tf", "e": "NFO", "tk": "54957", "lp": "84.20"})
    assert data == {"ltp": 84.20}  # no ft yet: no ltt, no wall-clock substitute

    _, data = _send(
        adapter, {"t": "tf", "e": "NFO", "tk": "54957", "lp": "84.35", "ft": "1658911103"}
    )
    assert data == {"ltp": 84.35, "ltt": 1658911103}

    _, data = _send(adapter, {"t": "tf", "e": "NFO", "tk": "54957", "lp": "84.40"})
    assert data["ltt"] == 1658911103


def test_quote_omits_fields_the_feed_never_sent(adapter):
    # The MCX tk sample carries no o/h/l/ap.
    _subscribe(adapter, {2}, exchange="MCX", token="239484", symbol="CRUDEOIL19SEP22FUT")
    tk = {
        "t": "tk",
        "e": "MCX",
        "tk": "239484",
        "ts": "CRUDEOIL19SEP22",
        "c": "7522.00",
        "ft": "1658911100",
        "v": "469",
        "oi": "429",
        "lp": "7568.00",
    }
    _, data = _send(adapter, tk)
    assert data["close"] == 7522.00
    assert data["volume"] == 469
    for key in ("open", "high", "low", "average_price"):
        assert key not in data
