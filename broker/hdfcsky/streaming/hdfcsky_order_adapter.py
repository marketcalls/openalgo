"""
HDFC Sky order-update adapter - ORDER packets on the feed socket.

Docs: broker-api-docs/hdfcsky-api-docs/17-websocket.md ("Packet Types and
their meanings") and the GenericDTO proto it links (vendored here as
hdfcsky_market.proto). The feed socket wss://<host>/wsapi/v1/session carries
two packet types besides market data:

    ORDER (8) -> GenericDTO.order   (message Order)
    TRADE (9) -> GenericDTO.trade   (message Trade)

The docs give no subscribe message for them: the only documented subscription
takes a scripId with type LTP, ALL or GREEK. They are taken to be pushed for the
session's own account on any open socket, so this adapter opens one, sends the
documented heartbeat, and publishes packet type 8. Every other packet type
is ignored; the first packet of each type is logged, so a live session shows
whether the gateway delivers order packets at all.

TRADE packets are logged but not published. An order's fills already arrive as
ORDER packets (Status PARTIAL_TRADE / COMPLETE, with the cumulative fill and the
average price), so a TRADE packet would publish the same fill a second time with
fewer fields. Trade also has no presence for RemainingVolume (proto3 int64), so
"nothing remains" and "field not sent" read alike, and its Price is the order
price, not the fill price.

Why a separate socket instead of the market-data one: that adapter runs in the
websocket_proxy subprocess under gunicorn, so an event published there would
land on the wrong process's event bus. HDFC Sky allows three WebSocket
connections per API key (17-websocket.md), so a second socket does not evict
the market-data feed.

Authentication is the market feed's: the access token as ``token`` and the app
``api_key`` in the query string (baseurl.get_ws_url), plus the token in the
Authorization header as hdfcsky_websocket.py sends it. A rejected token fails
the upgrade with 401, which the base class treats as "stand down until the next
login".

Packets flagged isOrderDownload are a replay of the day's book, not a change,
so they are not published (the polling adapter seeds its first poll silently
for the same reason).
"""

import json
from collections import OrderedDict

from broker.hdfcsky.api.baseurl import USER_AGENT, get_ws_url
from broker.hdfcsky.streaming import hdfcsky_market_pb2 as pb
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

PACKET_ORDER = 8
HEARTBEAT_SECONDS = 10  # what hdfcsky_websocket.py uses on the same gateway
_DEDUPE_LIMIT = 2000  # orders remembered for duplicate suppression

# Proto Status enum -> OpenAlgo order_status. A rejected modify or cancel leaves
# the order itself working, so those read "open", not "rejected".
_STATUS_MAP = {
    "COMPLETE": "complete",
    "BRACKET_ORDER_COMPLETE_TRADE": "complete",
    "REJECTED": "rejected",
    "BRACKET_ORDER_REJECTED": "rejected",
    "CANCEL_CONFIRMED": "cancelled",
    "BATCH_CANCEL_CONFIRMED": "cancelled",
    "AMO_CANCEL_CONFIRMED": "cancelled",
    "BRACKET_ORDER_CANCELLED": "cancelled",
    "SL_TRIGGER_CONFIRMED": "trigger pending",
}

_PRICETYPE_MAP = {"LIMIT": "LIMIT", "MARKET": "MARKET", "SL": "SL", "SLM": "SL-M"}
_OA_PRODUCTS = ("CNC", "NRML", "MIS")

# (Exchange, Segment) enum names -> OpenAlgo exchange.
_EXCHANGE_MAP = {
    ("NSE", "Capital"): "NSE",
    ("NSE", "FutOpt"): "NFO",
    ("NSE", "Currency"): "CDS",
    ("BSE", "Capital"): "BSE",
    ("BSE", "FutOpt"): "BFO",
    ("BSE", "Currency"): "BCD",
    ("MCX", "Commodities"): "MCX",
    ("MCX", "FutOpt"): "MCX",
    ("NCDEX", "Commodities"): "NCDEX",
    ("NCDEX", "FutOpt"): "NCDEX",
}


def _enum_name(enum_type, value) -> str:
    try:
        return enum_type.Name(value)
    except ValueError:
        return str(value)


def map_stream_status(status_name: str) -> str:
    """Proto Status name -> OpenAlgo status; anything still working is open."""
    return _STATUS_MAP.get(status_name, "open")


def map_product(prod_name: str) -> str:
    """ProdType name -> CNC/NRML/MIS. AMO_, BO_, CO_ and OCO_ variants keep their
    base product; a name with no OpenAlgo equivalent (BTST, MTF) is passed on."""
    base = prod_name.split("_", 1)[1] if "_" in prod_name else prod_name
    return base if base in _OA_PRODUCTS else prod_name


def filled_quantity(order) -> int:
    """The order's total fill. Order carries two fill counts, fillQuantity (12)
    and volFilledToday (14), and the docs define neither; lastTradedQty (42)
    holds the latest fill's size, so both read as running totals. Taking the
    larger keeps the total right if one of them turns out to be per-fill."""
    return max(int(order.fillQuantity), int(order.volFilledToday))


def map_exchange(exchange_name: str, segment_name: str) -> str:
    return _EXCHANGE_MAP.get((exchange_name, segment_name), exchange_name)


def decode_frame(payload: bytes) -> list:
    """GenericDTO packets in one binary frame (GenericDTOList, or a bare
    GenericDTO as some deployments send - see hdfcsky_websocket._parse_frame)."""
    envelope = pb.GenericDTOList()
    envelope.ParseFromString(payload)
    packets = list(envelope.genericDTOList)
    if packets:
        return packets
    single = pb.GenericDTO()
    single.ParseFromString(payload)
    return [single]


class HDFCSkyOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for HDFC Sky (feed socket, ORDER packets)."""

    broker = "hdfcsky"

    def __init__(self, user_id: str, access_token: str):
        super().__init__(broker_name=self.broker, user_id=user_id)
        self.access_token = access_token
        self._seen_packet_types: set[int] = set()
        # orderid -> last published fields, so a repeat of the same state
        # (ACCEPTED then CONFIRMED both read "open") is not published twice.
        self._last_published: OrderedDict[str, dict] = OrderedDict()

    # -- connection ------------------------------------------------------------

    def _fresh_token(self) -> str:
        """The token rides in the URL and rolls over daily, so it is re-read on
        every (re)connect; the last known one is kept if the read fails."""
        try:
            fresh = get_auth_token(self.user_id, bypass_cache=True)
        except Exception:
            self.logger.debug("Re-reading the HDFC Sky token failed", exc_info=True)
            fresh = None
        if fresh:
            self.access_token = fresh
        return self.access_token

    def get_ws_url(self) -> str:
        return get_ws_url(self._fresh_token())

    def get_headers(self) -> dict:
        return {"Authorization": self.access_token, "User-Agent": USER_AGENT}

    def on_open_extra(self, ws) -> None:
        self.logger.info(f"HDFC Sky order socket open ({self.user_id}); waiting for ORDER packets")

    def heartbeat_interval(self) -> int:
        return HEARTBEAT_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"heart_beat": True}))

    # -- decoding --------------------------------------------------------------

    def _note_packet_type(self, packet_type: int) -> None:
        if packet_type in self._seen_packet_types:
            return
        self._seen_packet_types.add(packet_type)
        self.logger.info(
            f"HDFC Sky order socket: first packet of type "
            f"{_enum_name(pb.PacketType, packet_type)} ({packet_type})"
        )

    def normalize_frame(self, raw_message) -> list[dict]:
        """Every order update in one frame, normalized."""
        if isinstance(raw_message, str):
            self.logger.debug(f"HDFC Sky order socket text frame: {raw_message[:300]}")
            return []
        try:
            packets = decode_frame(bytes(raw_message))
        except Exception as e:
            self.logger.debug(f"Undecodable HDFC Sky frame ({len(raw_message)}B): {e}")
            return []
        out = []
        for packet in packets:
            packet_type = int(packet.packetType)
            self._note_packet_type(packet_type)
            try:
                if packet_type != PACKET_ORDER:
                    continue
                fields = self.normalize_order(packet.order)
            except Exception as e:
                # One bad packet must not cost the rest of the frame.
                self.logger.debug(f"Skipping undecodable HDFC Sky order packet: {e}")
                continue
            if fields:
                out.append(fields)
        return out

    def normalize(self, raw_message):
        normalized = self.normalize_frame(raw_message)
        return normalized[0] if normalized else None

    def _handle_message(self, raw_message) -> None:
        try:
            normalized = self.normalize_frame(raw_message)
        except Exception as e:
            self.logger.debug(f"Failed to normalize HDFC Sky order frame: {e}")
            return
        for fields in normalized:
            if self._is_repeat(fields):
                continue
            self._publish_event_fields(fields)

    def _is_repeat(self, fields: dict) -> bool:
        orderid = fields.get("orderid")
        if not orderid:
            return False
        if self._last_published.get(orderid) == fields:
            return True
        self._last_published[orderid] = dict(fields)
        self._last_published.move_to_end(orderid)
        while len(self._last_published) > _DEDUPE_LIMIT:
            self._last_published.popitem(last=False)
        return False

    @staticmethod
    def _symbol(trading_symbol: str, exchange: str, token) -> str:
        token = str(token) if token else None
        mapped = to_openalgo_symbol(trading_symbol, exchange, token=token)
        return mapped or trading_symbol or (token or "")

    def normalize_order(self, order) -> dict | None:
        if order.isOrderDownload or not order.orderID:
            return None
        status_name = _enum_name(pb.Status, order.status)
        order_status = map_stream_status(status_name)
        exchange = map_exchange(
            _enum_name(pb.Exchange, order.exchange), _enum_name(pb.Segment, order.segment)
        )
        type_name = _enum_name(pb.OrderType, order.type)
        fields = {
            "orderid": str(order.orderID),
            "symbol": self._symbol(order.description.tradingSymbol, exchange, order.tokenID),
            "exchange": exchange,
            "action": _enum_name(pb.OrderSide, order.side),
            "quantity": int(order.quantity),
            "price": float(order.price),
            "trigger_price": float(order.triggerPrice),
            "pricetype": _PRICETYPE_MAP.get(type_name, type_name),
            "product": map_product(_enum_name(pb.ProdType, order.prodType)),
            "order_status": order_status,
            "filled_quantity": filled_quantity(order),
            "pending_quantity": int(order.remainingQuantity),
            "average_price": float(order.avgPrice),
        }
        if order_status == "rejected":
            message = order.error.Message.strip()
            if not message and order.error.Code:
                message = _enum_name(pb.ErrorCode, order.error.Code)
            fields["rejection_reason"] = message
        return fields


def create_hdfcsky_order_adapter(user_id: str) -> "HDFCSkyOrderUpdateAdapter | None":
    """Factory: an HDFCSkyOrderUpdateAdapter for user_id, or None with no session."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No HDFC Sky access token for user {user_id}; order-update adapter not started"
        )
        return None
    return HDFCSkyOrderUpdateAdapter(user_id=user_id, access_token=access_token)
