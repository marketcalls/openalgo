"""
Zerodha full-mode ticks must read open interest from bytes 48-52.

Issue #2491: Kite's 184-byte full packet (`zerodha-api-docs/10-websocket.md`)
carries last traded time at 44-48, OI at 48-52, OI day high at 52-56, OI day
low at 56-60 and the exchange timestamp at 60-64, then ten 12-byte depth
levels. `_parse_packet` read OI from 180-184, the fifth ask level's order count
and padding, so one order there published OI 65536. It also published bytes
44-48 (the last traded time) divided by 100 as `price_change`, a field Kite
does not send.

Every field gets a distinct value, and the fifth ask level gets one order, so a
parser reading the old offsets puts a recognisably wrong number in the key.
"""

import logging
import struct
import threading

import pytest

# The streaming package's __init__ imports the adapter, which imports
# websocket_proxy, which imports the adapter back. Loading the proxy first is
# the order the application uses.
import websocket_proxy  # noqa: F401
from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

NIFTY_FUT_TOKEN = 9485826
LAST_TRADE_TIME = 1795425800
EXCHANGE_TS = 1795425819
OI = 4932265
OI_DAY_HIGH = 5100000
OI_DAY_LOW = 4800000

# token, ltp, ltq, atp, volume, buy qty, sell qty, open, high, low, close
QUOTE_PART = struct.pack(
    ">11i",
    NIFTY_FUT_TOKEN,
    2539500,
    65,
    2559263,
    4688645,
    83395,
    107575,
    2596900,
    2600000,
    2537750,
    2577530,
)
EXTENDED = struct.pack(">5I", LAST_TRADE_TIME, OI, OI_DAY_HIGH, OI_DAY_LOW, EXCHANGE_TS)


def _level(qty, price, orders):
    return struct.pack(">IIHH", qty, price, orders, 0)


BIDS = b"".join(_level(130 * (i + 1), 2539300 - i * 100, i + 1) for i in range(5))
ASKS = b"".join(_level(260 + i * 65, 2539890 + i * 10, 4 - i if i < 4 else 1) for i in range(5))
FULL = QUOTE_PART + EXTENDED + BIDS + ASKS


@pytest.fixture
def ws():
    """A parser with no connection: _parse_packet reads only these attributes."""
    client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
    client.lock = threading.Lock()
    client.token_exchange_map = {NIFTY_FUT_TOKEN: "NFO"}
    client.mode_map = {}
    client.logger = logging.getLogger(__name__)
    return client


def test_fixture_is_a_full_packet():
    assert len(FULL) == 184
    # The bytes the old parser took for OI: one order at ask level 5, then padding.
    assert struct.unpack(">I", FULL[180:184])[0] == 65536


def test_full_packet_reads_oi_block_from_documented_offsets(ws):
    tick = ws._parse_packet(FULL)

    assert tick["mode"] == ws.MODE_FULL
    assert tick["open_interest"] == OI
    assert tick["oi_day_high"] == OI_DAY_HIGH
    assert tick["oi_day_low"] == OI_DAY_LOW
    assert tick["last_trade_time"] == LAST_TRADE_TIME
    assert tick["exchange_timestamp"] == EXCHANGE_TS


def test_full_packet_publishes_no_price_change(ws):
    tick = ws._parse_packet(FULL)

    # Kite's full packet has no change field; the quote packet sets none either.
    assert "price_change" not in tick


def test_full_packet_keeps_quote_fields_and_depth(ws):
    tick = ws._parse_packet(FULL)

    assert tick["last_price"] == 25395.0
    assert tick["volume"] == 4688645
    assert tick["ohlc"] == {"open": 25969.0, "high": 26000.0, "low": 25377.5, "close": 25775.3}
    assert tick["depth"]["buy"][0] == {"quantity": 130, "price": 25393.0, "orders": 1}
    assert tick["depth"]["sell"][4] == {"quantity": 520, "price": 25399.3, "orders": 1}
    assert len(tick["depth"]["buy"]) == 5
    assert len(tick["depth"]["sell"]) == 5
