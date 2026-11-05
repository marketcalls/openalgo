"""
Zerodha index ticks in quote and full mode must carry OHLC and change.

Issue #2347: Kite sends indices a packet of their own, 28 bytes in quote mode
and 32 in full mode (`zerodha-api-docs/10-websocket.md`, "Index Packet"):
token, ltp, high, low, open, close, change, then the exchange timestamp in
full mode. `_parse_packet` only knew the 8, 44 and 184-byte packets, so an
NSE_INDEX subscription in quote or full mode published the LTP alone.

The index field order is not the quote packet's (high, low, open, close
against open, high, low, close at other offsets), so the fixture gives every
field a distinct value: a parser that reads the wrong offset, or the regular
layout, puts a recognisably wrong number in the wrong key.
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

NIFTY_TOKEN = 256265
EXCHANGE_TS = 1762156800

# token, ltp, high, low, open, close, change (prices in paise)
INDEX_QUOTE = struct.pack(">7i", NIFTY_TOKEN, 2450010, 2460000, 2440000, 2445000, 2430000, 20010)
INDEX_FULL = INDEX_QUOTE + struct.pack(">I", EXCHANGE_TS)


@pytest.fixture
def ws():
    """A parser with no connection: _parse_packet reads only these attributes."""
    client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
    client.lock = threading.Lock()
    client.token_exchange_map = {NIFTY_TOKEN: "NSE_INDEX"}
    client.mode_map = {}
    client.logger = logging.getLogger(__name__)
    return client


def _assert_index_fields(tick):
    assert tick["instrument_token"] == NIFTY_TOKEN
    assert tick["last_price"] == 24500.10
    assert tick["ohlc"] == {"open": 24450.0, "high": 24600.0, "low": 24400.0, "close": 24300.0}
    assert tick["open_price"] == 24450.0
    assert tick["high_price"] == 24600.0
    assert tick["low_price"] == 24400.0
    assert tick["close_price"] == 24300.0
    assert tick["price_change"] == 200.10
    assert tick["source_exchange"] == "NSE_INDEX"
    # Kite sends no volume, depth or OI for an index; none is invented.
    for absent in ("volume", "depth", "open_interest", "total_buy_quantity"):
        assert absent not in tick


def test_index_quote_packet_carries_ohlc_and_change(ws):
    tick = ws._parse_packet(INDEX_QUOTE)

    assert tick["mode"] == ws.MODE_QUOTE
    _assert_index_fields(tick)
    assert "exchange_timestamp" not in tick


def test_index_full_packet_adds_exchange_timestamp(ws):
    tick = ws._parse_packet(INDEX_FULL)

    assert tick["mode"] == ws.MODE_FULL
    _assert_index_fields(tick)
    assert tick["exchange_timestamp"] == EXCHANGE_TS


def test_regular_quote_packet_still_uses_quote_layout(ws):
    # token, ltp, ltq, atp, volume, buy qty, sell qty, open, high, low, close
    packet = struct.pack(
        ">11i", 408065, 150000, 10, 149950, 5000, 1, 2, 149000, 151000, 148000, 149500
    )

    tick = ws._parse_packet(packet)

    assert tick["mode"] == ws.MODE_QUOTE
    assert tick["volume"] == 5000
    assert tick["ohlc"] == {"open": 1490.0, "high": 1510.0, "low": 1480.0, "close": 1495.0}
