"""Angel SmartAPI WebSocket 2.0 quote fields reaching QUOTE and DEPTH subscribers.

Packets are built byte for byte from the layout in the SmartAPI WebSocket 2.0
spec and parsed by the real SmartWebSocketV2 parser, so the adapter is tested
against the keys the parser actually produces.
"""

import struct
import threading

import pytest

# websocket_proxy first: it imports the adapters in an order that avoids the
# broker package's import cycle.
import websocket_proxy  # noqa: F401
from broker.angel.streaming.angel_adapter import AngelWebSocketAdapter
from broker.angel.streaming.smartWebSocketV2 import SmartWebSocketV2


def _packet(mode, exchange_type, token, *, ltp, ltq, atp, vol, tbq, tsq, o, h, lo, c, levels):
    """Build a Quote (mode 2) or Snap Quote (mode 3) binary packet."""
    buf = bytearray(379 if mode == 3 else 123)
    buf[0] = mode
    buf[1] = exchange_type
    tok = token.encode()
    buf[2 : 2 + len(tok)] = tok
    struct.pack_into("<q", buf, 27, 1)  # sequence
    struct.pack_into("<q", buf, 35, 1746171226000)  # exchange timestamp
    struct.pack_into("<q", buf, 43, ltp)
    struct.pack_into("<q", buf, 51, ltq)
    struct.pack_into("<q", buf, 59, atp)
    struct.pack_into("<q", buf, 67, vol)
    struct.pack_into("<d", buf, 75, tbq)
    struct.pack_into("<d", buf, 83, tsq)
    struct.pack_into("<q", buf, 91, o)
    struct.pack_into("<q", buf, 99, h)
    struct.pack_into("<q", buf, 107, lo)
    struct.pack_into("<q", buf, 115, c)
    if mode == 3:
        struct.pack_into("<q", buf, 123, 1746171225000)  # last traded timestamp
        struct.pack_into("<q", buf, 131, 5000)  # open interest
        for i, (flag, qty, price, orders) in enumerate(levels):
            struct.pack_into("<HqqH", buf, 147 + 20 * i, flag, qty, price, orders)
        struct.pack_into("<q", buf, 347, h * 2)  # upper circuit
        struct.pack_into("<q", buf, 355, lo // 2)  # lower circuit
    return bytes(buf)


def _parse(packet):
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    return ws._parse_binary_data(packet)


@pytest.fixture
def adapter():
    """Adapter without __init__: no broker session, no ZMQ socket, no websocket."""
    ad = AngelWebSocketAdapter.__new__(AngelWebSocketAdapter)
    ad.logger = __import__("logging").getLogger("test_angel_quote_feed")
    ad.lock = threading.Lock()
    ad.subscriptions = {}
    ad._token_index = {}
    # Read by cleanup() from __del__ when the adapter is collected.
    ad._reconnect_timer = None
    ad.ws_client = None
    ad._connect_thread = None
    ad.published = []
    ad.publish_market_data = lambda topic, data: ad.published.append((topic, data))
    return ad


def _subscribe(ad, symbol, exchange, token, exchange_type, mode):
    sub = {
        "symbol": symbol,
        "exchange": exchange,
        "brexchange": exchange,
        "token": token,
        "mode": mode,
    }
    ad.subscriptions[f"{symbol}_{exchange}_{mode}"] = sub
    ad._token_index[(token, exchange_type)] = sub


# Buy/Sell flag per the SmartAPI spec (10-websocket-streaming-2-0.md:152):
# 1 is buy, 0 is sell. Bids below asks, as a real book is.
NSE_LEVELS = [(1, 100 + i, 150000 - 5 * i, 3 + i) for i in range(5)] + [
    (0, 200 + i, 150010 + 5 * i, 4 + i) for i in range(5)
]


def test_snap_quote_publishes_ohlc_from_parser_keys(adapter):
    _subscribe(adapter, "RELIANCE", "NSE", "2885", 1, 3)
    msg = _parse(
        _packet(
            3,
            1,
            "2885",
            ltp=150005,
            ltq=25,
            atp=149876,
            vol=123456,
            tbq=1000.0,
            tsq=2000.0,
            o=149000,
            h=151000,
            lo=148500,
            c=148800,
            levels=NSE_LEVELS,
        )
    )
    adapter._on_data(None, msg)

    topic, data = adapter.published[-1]
    assert topic == "NSE_RELIANCE_DEPTH"
    assert data["open"] == 1490.0
    assert data["high"] == 1510.0
    assert data["low"] == 1485.0
    assert data["close"] == 1488.0  # previous close (closed_price)
    assert data["ltp"] == 1500.05


def test_snap_quote_keeps_quote_fields(adapter):
    _subscribe(adapter, "RELIANCE", "NSE", "2885", 1, 3)
    msg = _parse(
        _packet(
            3,
            1,
            "2885",
            ltp=150005,
            ltq=25,
            atp=149876,
            vol=123456,
            tbq=1000.0,
            tsq=2000.0,
            o=149000,
            h=151000,
            lo=148500,
            c=148800,
            levels=NSE_LEVELS,
        )
    )
    adapter._on_data(None, msg)

    data = adapter.published[-1][1]
    assert data["average_price"] == 1498.76
    assert data["total_buy_quantity"] == 1000.0
    assert data["total_sell_quantity"] == 2000.0
    assert data["volume"] == 123456
    assert data["last_quantity"] == 25
    assert data["last_trade_quantity"] == 25
    assert data["depth"]["buy"] == [
        {"price": (150000 - 5 * i) / 100, "quantity": 100 + i, "orders": 3 + i} for i in range(5)
    ]
    assert data["depth"]["sell"] == [
        {"price": (150010 + 5 * i) / 100, "quantity": 200 + i, "orders": 4 + i} for i in range(5)
    ]


def test_quote_publishes_last_quantity_next_to_last_trade_quantity(adapter):
    _subscribe(adapter, "RELIANCE", "NSE", "2885", 1, 2)
    msg = _parse(
        _packet(
            2,
            1,
            "2885",
            ltp=150005,
            ltq=25,
            atp=149876,
            vol=123456,
            tbq=1000.0,
            tsq=2000.0,
            o=149000,
            h=151000,
            lo=148500,
            c=148800,
            levels=[],
        )
    )
    adapter._on_data(None, msg)

    topic, data = adapter.published[-1]
    assert topic == "NSE_RELIANCE_QUOTE"
    assert data["last_quantity"] == 25
    assert data["last_trade_quantity"] == 25


def test_currency_prices_divide_by_1e7(adapter):
    # cde_fo (exchange type 13): "For currencies, the int 32 price values
    # should be divided by 10000000.0" (SmartAPI WebSocket 2.0).
    _subscribe(adapter, "USDINR28NOVFUT", "CDS", "1234", 13, 3)
    levels = [(0, 10, 834950000, 2)] * 5 + [(1, 12, 835050000, 3)] * 5
    msg = _parse(
        _packet(
            3,
            13,
            "1234",
            ltp=835000000,
            ltq=1,
            atp=834900000,
            vol=900,
            tbq=10.0,
            tsq=12.0,
            o=834000000,
            h=836000000,
            lo=833000000,
            c=833500000,
            levels=levels,
        )
    )
    adapter._on_data(None, msg)

    data = adapter.published[-1][1]
    assert data["ltp"] == pytest.approx(83.5)
    assert data["open"] == pytest.approx(83.4)
    assert data["close"] == pytest.approx(83.35)
    assert data["average_price"] == pytest.approx(83.49)
    for lvl in data["depth"]["buy"] + data["depth"]["sell"]:
        assert 83 < lvl["price"] < 84


def test_non_currency_prices_divide_by_100(adapter):
    assert adapter._price_divisor(1, "NSE") == 100.0
    assert adapter._price_divisor(5, "MCX") == 100.0
    assert adapter._price_divisor(13, "CDS") == 10000000.0
