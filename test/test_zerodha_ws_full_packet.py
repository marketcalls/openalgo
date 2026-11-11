"""
Zerodha full-mode ticks must carry the open interest Kite sent, not depth bytes.

Issue #2319: `ZerodhaWebSocket._parse_packet` read `open_interest` from bytes
180:184 of the 184-byte full-mode packet. Those bytes are the fifth sell
level's `orders` (180:182) and its padding (182:184), so a `>I` read of them is
`orders << 16`: the feed reported 655360 for RELIANCE (10 << 16) and 65536 for
a BANKNIFTY future (1 << 16). It also read bytes 44:48 as `price_change`; in
Kite's layout those bytes are the last trade time.

Kite's layout, as pykiteconnect 5.2.2 `KiteTicker._parse_binary` reads it
(all big-endian unsigned 32-bit unless noted):
    0:4 token, 4:8 last price, 8:12 last quantity, 12:16 average price,
    16:20 volume, 20:24 total buy quantity, 24:28 total sell quantity,
    28:32 open, 32:36 high, 36:40 low, 40:44 close,
    44:48 last trade time (epoch s), 48:52 oi, 52:56 oi day high,
    56:60 oi day low, 60:64 exchange timestamp (epoch s),
    then ten 12-byte depth entries from 64 (quantity, price, orders as `>H`,
    two bytes padding): five buy, then five sell.

The fixture is synthetic, because no recorded Kite packet is public and
capturing one needs a second Kite session. It is built field by field on that
layout, with distinct values, and the depth `orders` are chosen so that
`orders << 16` of the fifth sell level is not the open interest.

Fixture assumptions (the generator writes the expected file to match):
- `fixtures/zerodha_full_packet_synthetic.bin` is the 184-byte packet alone,
  with no frame header.
- `fixtures/zerodha_full_packet_synthetic_expected.json` is pykiteconnect
  5.2.2's tick for that packet, used as the reference parser. Its keys are
  pykiteconnect's own: `instrument_token`, `last_price`,
  `last_traded_quantity`, `average_traded_price`, `volume_traded`,
  `total_buy_quantity`, `total_sell_quantity`, `ohlc`, `oi`, `oi_day_high`,
  `oi_day_low` and `depth`. Its two datetimes are written as integer epoch
  seconds under `last_trade_time_epoch` and `exchange_timestamp_epoch`.
- The token's low byte is Kite's NFO segment, so prices are in paise and the
  reference divides them by 100, as this parser does.
"""

import json
import struct
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PACKET_FILE = FIXTURES / "zerodha_full_packet_synthetic.bin"
EXPECTED_FILE = FIXTURES / "zerodha_full_packet_synthetic_expected.json"
FULL_PACKET_LENGTH = 184
DEPTH_LEVELS_PER_SIDE = 5
SYMBOL = "NIFTY03NOV2624150CE"  # any NFO symbol; the adapter only looks it up by token
MODE_FULL = "full"  # ZerodhaWebSocket.MODE_FULL, the mode the adapter's full transform keys on


@pytest.fixture(scope="module")
def adapter_class():
    """`ZerodhaWebSocketAdapter`, imported the way the other adapter tests do.

    Importing `broker.zerodha.streaming.zerodha_adapter` first is circular
    (`websocket_proxy/__init__.py` imports every adapter), and an import
    sorter may put `broker` before `websocket_proxy` at module level, so the
    imports live in fixtures and their order is explicit.
    """
    from websocket_proxy import ZerodhaWebSocketAdapter

    return ZerodhaWebSocketAdapter


@pytest.fixture(scope="module")
def parser_class(adapter_class):
    """`ZerodhaWebSocket`, imported after the proxy package."""
    from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

    assert ZerodhaWebSocket.MODE_FULL == MODE_FULL
    return ZerodhaWebSocket


@pytest.fixture(scope="module")
def packet():
    """The synthetic 184-byte full-mode packet."""
    data = PACKET_FILE.read_bytes()
    assert len(data) == FULL_PACKET_LENGTH
    return data


@pytest.fixture(scope="module")
def expected():
    """pykiteconnect 5.2.2's parse of the same packet."""
    return json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client(parser_class):
    """A parser instance that never connects.

    `ZerodhaWebSocket.__init__` only stores its arguments and builds locks and
    queues; nothing opens a socket until `start()`.
    """
    return parser_class(api_key="test", access_token="test")


@pytest.fixture(scope="module")
def tick(client, packet):
    """The packet parsed the way the feed parses it: one frame, one packet.

    A Kite binary frame is a `>H` packet count, then per packet a `>H` length
    and the packet bytes.
    """
    frame = struct.pack(">HH", 1, len(packet)) + packet
    ticks = client._parse_binary_message(frame)
    assert len(ticks) == 1
    return ticks[0]


class TestFullPacketParse:
    """The parser against the reference, field by field."""

    def test_the_frame_path_and_the_packet_path_agree(self, client, packet, tick):
        """`_parse_binary_message` adds nothing but the framing.

        `timestamp` is the local receive time in ms, so it is excluded.
        """
        direct = client._parse_packet(packet)
        assert {k: v for k, v in direct.items() if k != "timestamp"} == {
            k: v for k, v in tick.items() if k != "timestamp"
        }

    def test_mode_is_full_for_a_184_byte_packet(self, tick):
        assert tick["mode"] == MODE_FULL

    def test_open_interest_is_read_from_bytes_48_to_52(self, tick, expected):
        assert tick["open_interest"] == expected["oi"]

    def test_open_interest_is_not_the_fifth_sell_level_orders_shifted(self, tick, expected):
        """The fixture must be able to tell the old misread from the real OI."""
        misread = expected["depth"]["sell"][4]["orders"] << 16
        assert misread != expected["oi"]
        assert tick["open_interest"] != misread

    def test_oi_day_high_and_low_are_read_from_bytes_52_to_60(self, tick, expected):
        assert tick["oi_day_high"] == expected["oi_day_high"]
        assert tick["oi_day_low"] == expected["oi_day_low"]

    def test_last_trade_time_is_epoch_seconds_from_bytes_44_to_48(self, tick, expected):
        assert type(tick["last_trade_time"]) is int
        assert tick["last_trade_time"] == expected["last_trade_time_epoch"]

    def test_exchange_timestamp_is_epoch_seconds_from_bytes_60_to_64(self, tick, expected):
        assert type(tick["exchange_timestamp"]) is int
        assert tick["exchange_timestamp"] == expected["exchange_timestamp_epoch"]

    def test_last_trade_time_and_exchange_timestamp_are_different_fields(self, tick):
        """The fixture gives them different values, so a swap cannot pass."""
        assert tick["last_trade_time"] != tick["exchange_timestamp"]

    def test_bytes_44_to_48_are_no_longer_reported_as_price_change(self, tick):
        assert "price_change" not in tick

    @pytest.mark.parametrize("side", ["buy", "sell"])
    @pytest.mark.parametrize("level", range(DEPTH_LEVELS_PER_SIDE))
    def test_every_depth_level_matches_the_reference(self, tick, expected, side, level):
        got = tick["depth"][side][level]
        want = expected["depth"][side][level]
        assert got["quantity"] == want["quantity"]
        assert got["price"] == want["price"]
        assert got["orders"] == want["orders"]

    def test_depth_has_five_levels_per_side(self, tick):
        assert len(tick["depth"]["buy"]) == DEPTH_LEVELS_PER_SIDE
        assert len(tick["depth"]["sell"]) == DEPTH_LEVELS_PER_SIDE

    def test_header_fields_still_match_the_reference(self, tick, expected):
        """Bytes 0:44 were already right; the fix must not move them."""
        for key in (
            "instrument_token",
            "last_price",
            "last_traded_quantity",
            "average_traded_price",
            "volume_traded",
            "total_buy_quantity",
            "total_sell_quantity",
        ):
            assert tick[key] == expected[key], key
        assert tick["ohlc"] == expected["ohlc"]


class TestAdapterFullMode:
    """What the WebSocket proxy publishes for the parsed tick."""

    @pytest.fixture(scope="class")
    def adapter(self, adapter_class, client, tick):
        """An adapter that knows the token and nothing else.

        `__init__` connects a ZeroMQ publisher to the proxy bus, which this
        test does not need, so the instance is built without it. The state
        `cleanup()` reads on garbage collection is set so it finds nothing to
        release; `_zmq_cleaned_up` because no ZeroMQ resource was created.
        """
        instance = adapter_class.__new__(adapter_class)
        instance.logger = client.logger
        instance.lock = threading.Lock()
        instance.batch_timer = None
        instance.ws_client = None
        instance.subscribed_symbols = {}
        instance._zmq_cleaned_up = True
        instance.token_to_symbol = {tick["instrument_token"]: (SYMBOL, "NFO")}
        return instance

    @pytest.fixture(scope="class")
    def message(self, adapter, tick):
        transformed = adapter._transform_tick(tick)
        assert transformed is not None
        return transformed

    def test_message_is_full_mode_for_the_mapped_symbol(self, message):
        assert message["mode"] == MODE_FULL
        assert (message["symbol"], message["exchange"]) == (SYMBOL, "NFO")

    def test_last_trade_time_is_published_as_a_new_field(self, message, tick):
        assert message["last_trade_time"] == tick["last_trade_time"]

    def test_oi_is_the_parsed_open_interest(self, message, tick, expected):
        assert message["oi"] == tick["open_interest"] == expected["oi"]
        assert message["open_interest"] == tick["open_interest"]

    def test_ltt_stays_the_exchange_timestamp(self, message, tick):
        """Consumers bucket ticks by `ltt`; its meaning does not change."""
        assert message["ltt"] == tick["exchange_timestamp"]
