"""Pocketful's market-data feed protocol: its address, its messages and its packets.

The streaming adapter imports from here, and this module imports nothing of
it, so reading the protocol never pulls in the websocket proxy package.

Address
-------
``wss://algo.pocketful.in/ws/v1/feeds?login_id=<client id>&access_token=<token>``
from both SDKs (Python SDK 0.1.2 pocketfulwebsocket.py base_url and wsclient.py
socket_connect; JavaScript SDK pocketfulwebsocket.js and wsclient.js
socketConnect, whose commit 894e597c "updated websocket base url" moved the
host from trade.pocketful.in to algo.pocketful.in). The docs page
connecting-websockets.md names ``wss://algo.pocketful.in/api/v1/ws`` instead,
but says only that the token goes "in the connection handshake or subsequent
authentication message", with no parameter, header or message to do it with.
The SDKs' form is the only one specified in full. It carries the token in the
URL, so the URL is never logged.

Messages (SDK wsclient.py send_message, unsubscribe_update, heartbeat_thread)
-------------------------------------------------------------------------------
``{"a": "subscribe" | "unsubscribe", "v": [[exchange_code, token], ...], "m":
channel}`` with channel ``marketdata``, ``compact_marketdata`` or
``full_snapquote``; the heartbeat ``{"a": "h", "v": [], "m": ""}`` every 8
seconds.

Packets
-------
Every layout here is copied from Pocketful's own SDKs, and each field name and
example value matches the documentation's response samples:

* Python SDK ``pocketful`` 0.1.2, ``packetDecoder.py`` (decodeDetailedMarketData,
  decodeCompactMarketData, decodeSnapquoteData, decodeOrderUpdate,
  decodeTradeUpdate);
* JavaScript SDK pocketfulapi-javascript, ``PocketfulAPI/packetDecoder.js``,
  the same offsets read with readInt8, readUInt32BE and readBigUInt64BE;
* docs pages detailed-marketdata.md, compact-marketdata.md and
  snapquote-data.md ("Response" samples and "Response Parameter" tables).

All integers are big-endian. Byte 0 is the packet mode (a signed byte), byte 1
the exchange code (a signed byte), bytes 2 to 6 the instrument token (unsigned
32 bit). One WebSocket binary message carries one packet: both SDKs read the
mode from byte 0 of each message and decode the message whole.

Prices are integers in paise as the feed sends them (the docs' sample for NSE
token 1333 has last_traded_price 144895 for a price of 1448.95). Converting
them is the caller's job, so this module returns exactly what the SDK returns.

The ``change`` field of the compact packet is decoded unsigned, as both SDKs
do. The docs' sample shows 4294966816 there, which is -480 read as a signed
32 bit value; the adapter does not use the field.

Each layout is one precompiled ``struct.Struct`` read with a single
``unpack_from``. A packet shorter than its layout decodes to ``{}``; bytes past
the layout are ignored, as the SDK's fixed slices ignore them.
"""

import json
import struct
import urllib.parse

from broker.pocketful.api.baseurl import BASE_URL
from utils.logging import get_logger

logger = get_logger(__name__)

# Packet modes: byte 0 of each message (SDK wsclient.py on_message, the docs'
# "mode" in each response sample).
DETAILED_MODE = 1
COMPACT_MODE = 2
SNAPQUOTE_MODE = 4
ORDER_UPDATE_MODE = 50
TRADE_UPDATE_MODE = 51

FEED_PATH = "/ws/v1/feeds"

# The channel each packet mode is subscribed on (SDK wsclient.py send_message).
CHANNEL_NAMES = {
    DETAILED_MODE: "marketdata",
    COMPACT_MODE: "compact_marketdata",
    SNAPQUOTE_MODE: "full_snapquote",
}

HEARTBEAT_MESSAGE = json.dumps({"a": "h", "v": [], "m": ""})
HEARTBEAT_SECONDS = 8


def feed_url(client_id, access_token):
    """The feed's address for one session. It carries the token: never log it."""
    host = BASE_URL.split("://", 1)[-1].rstrip("/")
    query = urllib.parse.urlencode({"login_id": client_id, "access_token": access_token})
    return f"wss://{host}{FEED_PATH}?{query}"


def feed_message(action, instruments, mode):
    """A subscribe or unsubscribe message for ``[[exchange_code, token], ...]``."""
    return json.dumps({"a": action, "v": instruments, "m": CHANNEL_NAMES[mode]})


# Detailed market data, 102 bytes (packetDecoder.py decodeDetailedMarketData):
#   0 b mode, 1 b exchange_code, 2 I instrument_token,
#   6 I last_traded_price, 10 I last_traded_time, 14 I last_traded_quantity,
#   18 I trade_volume, 22 I best_bid_price, 26 I best_bid_quantity,
#   30 I best_ask_price, 34 I best_ask_quantity,
#   38 Q total_buy_quantity, 46 Q total_sell_quantity,
#   54 I average_trade_price, 58 I exchange_timestamp, 62 I open_price,
#   66 I high_price, 70 I low_price, 74 I close_price, 78 I yearly_high_price,
#   82 I yearly_low_price, 86 I lowDPR, 90 I highDPR,
#   94 I currentOpenInterest, 98 I initialOpenInterest.
_DETAILED = struct.Struct(">bbI8I2Q12I")
_DETAILED_FIELDS = (
    "mode",
    "exchange_code",
    "instrument_token",
    "last_traded_price",
    "last_traded_time",
    "last_traded_quantity",
    "trade_volume",
    "best_bid_price",
    "best_bid_quantity",
    "best_ask_price",
    "best_ask_quantity",
    "total_buy_quantity",
    "total_sell_quantity",
    "average_trade_price",
    "exchange_timestamp",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "yearly_high_price",
    "yearly_low_price",
    "lowDPR",
    "highDPR",
    "currentOpenInterest",
    "initialOpenInterest",
)

# Compact market data, 42 bytes (packetDecoder.py decodeCompactMarketData):
#   0 b mode, 1 b exchange_code, 2 I instrument_token,
#   6 I last_traded_price, 10 I change, 14 I last_traded_time, 18 I lowDPR,
#   22 I highDPR, 26 I currentOpenInterest, 30 I initialOpenInterest,
#   34 I bidPrice, 38 I askPrice.
_COMPACT = struct.Struct(">bbI9I")
_COMPACT_FIELDS = (
    "mode",
    "exchange_code",
    "instrument_token",
    "last_traded_price",
    "change",
    "last_traded_time",
    "lowDPR",
    "highDPR",
    "currentOpenInterest",
    "initialOpenInterest",
    "bidPrice",
    "askPrice",
)

# Snapquote, 166 bytes (packetDecoder.py decodeSnapquoteData):
#   0 b mode, 1 b exchange_code, 2 I instrument_token,
#   6 5I buyers, 26 5I bidPrices, 46 5I bidQtys,
#   66 5I sellers, 86 5I askPrices, 106 5I askQtys,
#   126 I averageTradePrice, 130 I open, 134 I high, 138 I low, 142 I close,
#   146 Q totalBuyQty, 154 Q totalSellQty, 162 I volume.
_SNAPQUOTE = struct.Struct(">bbI35I2QI")
_SNAPQUOTE_LEVELS = 5

DETAILED_PACKET_SIZE = _DETAILED.size
COMPACT_PACKET_SIZE = _COMPACT.size
SNAPQUOTE_PACKET_SIZE = _SNAPQUOTE.size


def packet_mode(packet):
    """The mode byte of a binary packet, or None for an empty or text message."""
    if not isinstance(packet, (bytes, bytearray, memoryview)) or len(packet) < 1:
        return None
    return struct.unpack_from(">b", packet, 0)[0]


def _fits(packet, layout, name):
    if isinstance(packet, (bytes, bytearray, memoryview)) and len(packet) >= layout.size:
        return True
    size = len(packet) if isinstance(packet, (bytes, bytearray, memoryview)) else 0
    logger.warning(f"Pocketful {name} packet too short: {size} of {layout.size} bytes")
    return False


def decodeDetailedMarketData(packet):
    """Decode a detailed market-data packet (mode 1), or {} if it is too short."""
    if not _fits(packet, _DETAILED, "detailed market data"):
        return {}
    return dict(zip(_DETAILED_FIELDS, _DETAILED.unpack_from(packet), strict=True))


def decodeCompactMarketData(packet):
    """Decode a compact market-data packet (mode 2), or {} if it is too short."""
    if not _fits(packet, _COMPACT, "compact market data"):
        return {}
    return dict(zip(_COMPACT_FIELDS, _COMPACT.unpack_from(packet), strict=True))


def decodeSnapquoteData(packet):
    """Decode a snapquote packet (mode 4) with its five depth levels, or {}."""
    if not _fits(packet, _SNAPQUOTE, "snapquote"):
        return {}
    values = _SNAPQUOTE.unpack_from(packet)
    levels = [list(values[3 + 5 * i : 8 + 5 * i]) for i in range(6)]
    tail = values[33:]
    return {
        "mode": values[0],
        "exchange_code": values[1],
        "instrument_token": values[2],
        "buyers": levels[0],
        "bidPrices": levels[1],
        "bidQtys": levels[2],
        "sellers": levels[3],
        "askPrices": levels[4],
        "askQtys": levels[5],
        "averageTradePrice": tail[0],
        "open": tail[1],
        "high": tail[2],
        "low": tail[3],
        "close": tail[4],
        "totalBuyQty": tail[5],
        "totalSellQty": tail[6],
        "volume": tail[7],
    }


def decodeOrderUpdate(packet):
    """An order update (mode 50): JSON after a five byte header, as the SDK reads it."""
    try:
        return json.loads(bytes(packet).decode("utf-8")[5:])
    except Exception:
        logger.exception("Could not decode a Pocketful order update")
        return {}


def decodeTradeUpdate(packet):
    """A trade update (mode 51): JSON after a five byte header, as the SDK reads it."""
    try:
        return json.loads(bytes(packet).decode("utf-8")[5:])
    except Exception:
        logger.exception("Could not decode a Pocketful trade update")
        return {}
