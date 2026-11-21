"""
Zerodha full-mode (184-byte) ticks must take open interest from bytes 48-52.

Issue #2319: the parser read OI from the last 4 bytes of the packet, which are
the fifth offer depth entry's order count and padding, so every Zerodha OI
value published by OpenAlgo was wrong.
"""

import logging
import struct
import threading

import pytest

import websocket_proxy  # noqa: F401
from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

TOKEN = 12345602
OI = 4_567_800
OI_HIGH = 4_600_000
OI_LOW = 4_400_000
LAST_TRADE_TS = 1762156790
EXCHANGE_TS = 1762156800


def full_packet():
    # token, ltp, ltq, atp, volume, buy qty, sell qty, open, high, low, close
    head = struct.pack(">11i", TOKEN, 150000, 75, 149950, 5000, 900, 1100, 149000, 151000, 148000, 149500)
    head += struct.pack(">IIIII", LAST_TRADE_TS, OI, OI_HIGH, OI_LOW, EXCHANGE_TS)
    depth = b""
    for i in range(10):
        # quantity, price, orders, padding; the last offer gets 7 orders
        depth += struct.pack(">IIHH", 100 + i, 150000 + i * 5, 7 if i == 9 else 3, 0)
    packet = head + depth
    assert len(packet) == 184
    return packet


@pytest.fixture
def ws():
    client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
    client.lock = threading.Lock()
    client.token_exchange_map = {TOKEN: "NFO"}
    client.mode_map = {}
    client.logger = logging.getLogger(__name__)
    return client


def test_full_packet_open_interest_read_from_bytes_48_to_52(ws):
    tick = ws._parse_packet(full_packet())

    assert tick["mode"] == ws.MODE_FULL
    assert tick["open_interest"] == OI
    assert tick["exchange_timestamp"] == EXCHANGE_TS
    assert tick["depth"]["sell"][4]["orders"] == 7
