"""Quote and depth ticks carry the exchange's trade time, in epoch milliseconds.

Issue #2143. A client merging two brokers' feeds, or cutting candles on
exchange time, could not tell when a trade happened:

- Upstox Quote mode published the `ts` of the 1d OHLC bar as `timestamp`. That
  is the bar's start, the same value all day, so every quote tick also read as
  hours old to the stale-data check. `ltt` and `cp` were left out although the
  feed carries them. Depth published `currentTs` as the string protobuf's JSON
  form gives an int64, not as a number.
- Zerodha filled `ltt` from the server's clock whenever a packet carried no
  exchange time (every Quote packet), so it looked like an exchange time and
  was not one. The Full-mode exchange time was passed on in epoch seconds while
  every other time field is milliseconds.

`ltt` is now the broker's trade time or None, never a local time, and
`timestamp` stays the time the tick was published. Upstox packets are built
with the real protobuf schema and decoded the way the live client decodes them;
Zerodha packets are built byte for byte to the Kite layout. No broker account
or network is involved.
"""

import struct
import time

import pytest
from google.protobuf.json_format import MessageToDict

# websocket_proxy imports every broker adapter, so importing an adapter first
# leaves it half-built and the import fails. Pre-existing cycle, unrelated to
# what is tested here (the same workaround as test_flattrade_data_silence_watchdog).
import websocket_proxy  # noqa: F401  isort:skip

from broker.upstox.streaming import MarketDataFeedV3_pb2 as pb
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter
from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter
from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

# A trade at 10:15:30.250 IST on 1 Oct 2026, the packet sent 40 ms later, and
# the day's 1d bar starting at 00:00 IST. All epoch milliseconds.
TRADE_MS = 1_790_831_130_250
SENT_MS = TRADE_MS + 40
BAR_START_MS = 1_790_793_000_000
KEY = "NSE_FO|12345"


# --- Upstox ---------------------------------------------------------------


def upstox_message(*, ltt=TRADE_MS, current_ts=SENT_MS, cp=101.5):
    """A full-mode FeedResponse, decoded exactly as UpstoxWebSocketClient does."""
    response = pb.FeedResponse(type=pb.live_feed, currentTs=current_ts)
    ff = response.feeds[KEY].fullFeed.marketFF
    ff.ltpc.ltp = 102.25
    ff.ltpc.ltq = 75
    ff.ltpc.ltt = ltt
    ff.ltpc.cp = cp
    ff.marketOHLC.ohlc.add(
        interval="1d", open=100.0, high=103.0, low=99.5, close=102.25, vol=5000, ts=BAR_START_MS
    )
    level = ff.marketLevel.bidAskQuote.add()
    level.bidP, level.bidQ, level.askP, level.askQ = 102.2, 150, 102.3, 225
    decoded = pb.FeedResponse()
    decoded.ParseFromString(response.SerializeToString())
    return MessageToDict(decoded)


@pytest.fixture
def upstox():
    return UpstoxWebSocketAdapter.__new__(UpstoxWebSocketAdapter)


def quote_of(adapter, message):
    base = {"symbol": "NIFTY", "exchange": "NFO", "token": KEY}
    return adapter._extract_quote_data(message["feeds"][KEY], base, message.get("currentTs", 0))


def test_the_decoded_feed_really_carries_int64_as_strings():
    """What makes the fix necessary: the adapter never sees a Python int."""
    message = upstox_message()
    assert message["currentTs"] == str(SENT_MS)
    assert message["feeds"][KEY]["fullFeed"]["marketFF"]["ltpc"]["ltt"] == str(TRADE_MS)


def test_upstox_quote_carries_the_trade_time(upstox):
    quote = quote_of(upstox, upstox_message())
    assert quote["ltt"] == TRADE_MS
    assert isinstance(quote["ltt"], int)


def test_upstox_quote_timestamp_is_when_the_feed_sent_it_not_the_bar_start(upstox):
    quote = quote_of(upstox, upstox_message())
    assert quote["timestamp"] == SENT_MS, "timestamp is the 1d bar's start, same all day"
    assert isinstance(quote["timestamp"], int)


def test_upstox_quote_carries_the_previous_close(upstox):
    assert quote_of(upstox, upstox_message())["cp"] == 101.5


def test_upstox_quote_without_a_trade_time_says_so(upstox):
    quote = quote_of(upstox, upstox_message(ltt=0))
    assert quote["ltt"] is None


def test_upstox_quote_without_current_ts_falls_back_to_the_local_clock(upstox):
    before = int(time.time() * 1000)
    quote = quote_of(upstox, upstox_message(current_ts=0))
    assert before <= quote["timestamp"] <= int(time.time() * 1000)


def test_upstox_depth_timestamp_is_a_number_and_carries_the_trade_time(upstox):
    message = upstox_message()
    depth = upstox._extract_depth_data(message["feeds"][KEY], message["currentTs"])
    assert depth["timestamp"] == SENT_MS
    assert isinstance(depth["timestamp"], int), "published the protobuf string as-is"
    assert depth["ltt"] == TRADE_MS


def test_upstox_depth_tick_without_a_full_feed_still_carries_the_trade_time(upstox):
    """An LTPC-only update on a depth subscription has the same keys as a full one."""
    response = pb.FeedResponse(type=pb.live_feed, currentTs=SENT_MS)
    response.feeds[KEY].ltpc.ltp = 102.25
    response.feeds[KEY].ltpc.ltt = TRADE_MS
    message = MessageToDict(response)
    depth = upstox._extract_depth_data(message["feeds"][KEY], message["currentTs"])
    assert depth["ltt"] == TRADE_MS
    assert depth["timestamp"] == SENT_MS


def test_upstox_depth_tick_with_neither_feed_says_so(upstox):
    depth = upstox._extract_depth_data({}, str(SENT_MS))
    assert depth["ltt"] is None


# --- Zerodha --------------------------------------------------------------

QUOTE_FIELDS = (
    256265,  # instrument token
    2_455_000,  # last price, paise
    50,  # last traded quantity
    2_450_000,  # average price, paise
    120_000,  # volume
    9_000,  # total buy quantity
    8_000,  # total sell quantity
    2_440_000,  # open
    2_460_000,  # high
    2_430_000,  # low
    2_445_000,  # close
)
EXCHANGE_TS_S = TRADE_MS // 1000


def quote_packet():
    """A 44-byte Kite Quote packet, which carries no exchange time at all."""
    return struct.pack(">11i", *QUOTE_FIELDS)


def full_packet(exchange_ts_s=EXCHANGE_TS_S):
    """A 184-byte Kite Full packet with the exchange time, in seconds, at bytes 60-64."""
    head = quote_packet()
    middle = struct.pack(">IIIII", EXCHANGE_TS_S, 0, 0, 0, exchange_ts_s)
    depth = b"".join(struct.pack(">IIHxx", 10, 2_455_000, 1) for _ in range(10))
    packet = head + middle + depth
    assert len(packet) == 184
    return packet


@pytest.fixture
def kite():
    ws = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
    ws.logger = __import__("logging").getLogger("test.zerodha")
    ws.lock = __import__("threading").Lock()
    ws.mode_map = {}
    ws.token_exchange_map = {}
    return ws


@pytest.fixture
def zerodha():
    return ZerodhaWebSocketAdapter.__new__(ZerodhaWebSocketAdapter)


def test_zerodha_full_packet_exchange_time_is_in_milliseconds(kite):
    tick = kite._parse_packet(full_packet())
    assert tick["exchange_timestamp"] == EXCHANGE_TS_S * 1000, "passed on in epoch seconds"


def test_zerodha_full_packet_without_an_exchange_time_leaves_it_out(kite):
    assert "exchange_timestamp" not in kite._parse_packet(full_packet(exchange_ts_s=0))


@pytest.mark.parametrize("mode", ["quote", "full"])
def test_zerodha_full_tick_ltt_is_the_exchange_time(kite, zerodha, mode):
    tick = kite._parse_packet(full_packet())
    out = zerodha._transform_regular_tick(tick, "NIFTY", "NFO", mode)
    assert out["ltt"] == EXCHANGE_TS_S * 1000


@pytest.mark.parametrize("mode", ["ltp", "quote", "unknown"])
def test_zerodha_quote_packet_ltt_is_not_the_servers_clock(kite, zerodha, mode):
    """A Quote packet has no exchange time; ltt used to be filled with local time."""
    tick = kite._parse_packet(quote_packet())
    out = zerodha._transform_regular_tick(tick, "NIFTY", "NFO", mode)
    assert out["ltt"] is None


def test_zerodha_quote_packet_still_has_its_receive_timestamp(kite, zerodha):
    before = int(time.time() * 1000)
    tick = kite._parse_packet(quote_packet())
    out = zerodha._transform_regular_tick(tick, "NIFTY", "NFO", "quote")
    assert before <= out["timestamp"] <= int(time.time() * 1000)


@pytest.mark.parametrize("mode", ["ltp", "quote", "unknown"])
def test_zerodha_index_tick_ltt_is_not_the_servers_clock(zerodha, mode):
    tick = {"last_price": 24550.0, "timestamp": int(time.time() * 1000)}
    out = zerodha._transform_index_tick(tick, "NIFTY", "NSE_INDEX", mode)
    assert out["ltt"] is None


def test_zerodha_index_tick_ltt_is_the_exchange_time_when_sent(zerodha):
    tick = {"last_price": 24550.0, "timestamp": 1, "exchange_timestamp": TRADE_MS}
    out = zerodha._transform_index_tick(tick, "NIFTY", "NSE_INDEX", "quote")
    assert out["ltt"] == TRADE_MS
    assert out["exchange_timestamp"] == TRADE_MS
