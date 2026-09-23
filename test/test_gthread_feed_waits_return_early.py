"""Quote and depth waits on a broker feed end when the data is complete.

Motilal, Pocketful, Tradejini and Nubra answer a quote or depth request by
subscribing on a WebSocket and waiting for the data. They used to wait a fixed
time (Motilal three seconds for a book, Nubra two), or look once a second
(Pocketful, Tradejini), or once every half second (a Nubra book), whatever had
arrived. Each wait holds the request's thread, which under gthread is one of a
fixed pool.

They now look every few hundredths of a second and stop as soon as what they
read is complete. The rule each test pins is the same: the answer is the one
the fixed wait gave for the same packets, only sooner; and when the data is
not complete the wait lasts exactly as long as before. "Complete" is decided
per feed, because one packet is not always the whole answer:

* Pocketful and a Tradejini book: one packet is the whole quote or book.
* Motilal: one packet per field group, so every group the read uses.
* Tradejini L1: a snapshot plus changes, so every field the answer reads.
* Nubra: a book needs five priced levels a side and the greeks' open
  interest; an index quote keeps the full wait.

No network: every socket is a fake that delivers packets on a timer.
"""

from __future__ import annotations

import struct
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from broker.motilal.api import data as motilal
from broker.motilal.api.motilal_websocket import MotilalWebSocket
from broker.nubra.api import data as nubra
from broker.pocketful.api import data as pocketful
from broker.tradejini.api import data as tradejini
from utils import runtime


@pytest.fixture(autouse=True)
def not_gthread(monkeypatch):
    """The feed gate is not what is under test here."""
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


def later(seconds, action):
    """Run ``action`` on a timer thread, as a feed delivers a packet."""
    timer = threading.Timer(seconds, action)
    timer.daemon = True
    timer.start()
    return timer


def timed(call):
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


# ---------------------------------------------------------------- Motilal


def _mo_packet(scrip: int, kind: str, body: bytes, wire: bytes = b"N") -> bytes:
    return (
        wire
        + struct.pack("<i", scrip)
        + struct.pack("<i", 0)
        + kind.encode()
        + body.ljust(20, b"\0")
    )


def _mo_ltp(scrip, ltp=500.5, oi=0):
    return _mo_packet(scrip, "A", struct.pack("<fiifi", ltp, 7, 90000, ltp, oi))


def _mo_ohlc(scrip):
    return _mo_packet(scrip, "G", struct.pack("<ffff", 495.0, 502.5, 494.25, 498.0))


def _mo_level(scrip, level, bid=500.25, ask=500.75):
    kind = "BCDEF"[level - 1]
    return _mo_packet(
        scrip,
        kind,
        struct.pack("<fihfih", bid - level, 10 * level, level, ask + level, 20 * level, level),
    )


def _mo_oi(scrip, oi=123400):
    return _mo_packet(scrip, "m", struct.pack("<iii", oi, oi + 100, oi - 100))


class _MotilalWire:
    """The socket under a real MotilalWebSocket: a register starts the feed."""

    def __init__(self, client: MotilalWebSocket, packets_for, delay: float):
        self.client = client
        self.packets_for = packets_for
        self.delay = delay

    def send(self, packet, opcode=None):
        # register_scrip's frame is "=cHcciB", ending 1 to register, 0 to leave.
        if isinstance(packet, bytes) and packet[:1] == b"D" and packet[-1:] == b"\x01":
            scrip = struct.unpack("=i", packet[5:9])[0]
            packets = self.packets_for(scrip)
            later(self.delay, lambda: self.client._parse_binary_market_data(b"".join(packets)))


def _motilal(monkeypatch, packets_for, delay=0.1, token="2885"):
    client = MotilalWebSocket("AA0", "tok", "key")
    client.is_connected = True
    client.ws = _MotilalWire(client, packets_for, delay)
    broker = motilal.BrokerData.__new__(motilal.BrokerData)
    broker.auth_token = "tok"
    broker._websocket = client
    monkeypatch.setattr(broker, "get_websocket", lambda force_new=False: client, raising=False)
    monkeypatch.setattr(motilal, "get_token", lambda symbol, exchange: token)
    monkeypatch.setattr(motilal, "get_br_symbol", lambda symbol, exchange: symbol)
    return broker, client


def _whole_book(scrip, oi=False):
    packets = [_mo_ltp(scrip), _mo_ohlc(scrip)] + [_mo_level(scrip, n) for n in range(1, 6)]
    return packets + ([_mo_oi(scrip)] if oi else [])


def test_motilal_depth_answers_as_soon_as_the_snapshot_is_complete(monkeypatch):
    broker, _ = _motilal(monkeypatch, lambda scrip: _whole_book(scrip))
    early, elapsed = timed(lambda: broker.get_depth("SBIN", "NSE"))
    assert elapsed < 1.5, f"waited {elapsed:.2f}s for data that arrived at 0.1s"

    # The same packets, read after the whole fixed wait, give the same answer.
    monkeypatch.setattr(MotilalWebSocket, "has_snapshot", lambda *a, **k: False)
    monkeypatch.setattr(motilal, "_DEPTH_WAIT_SECONDS", 0.5)
    broker, _ = _motilal(monkeypatch, lambda scrip: _whole_book(scrip))
    full, _ = timed(lambda: broker.get_depth("SBIN", "NSE"))
    assert early == full
    assert early["bids"][4] == {"price": 495.25, "quantity": 50}
    assert early["open"] == 495.0 and early["ltp"] == 500.5


def test_motilal_depth_keeps_the_full_wait_when_a_level_never_arrives(monkeypatch):
    monkeypatch.setattr(motilal, "_DEPTH_WAIT_SECONDS", 0.6)
    only_level_one = lambda scrip: [_mo_ltp(scrip), _mo_ohlc(scrip), _mo_level(scrip, 1)]  # noqa: E731
    broker, _ = _motilal(monkeypatch, only_level_one)
    result, elapsed = timed(lambda: broker.get_depth("SBIN", "NSE"))
    assert elapsed >= 0.6
    assert result["bids"][0]["price"] == 499.25
    assert result["bids"][1] == {"price": 0, "quantity": 0}


def test_motilal_derivative_depth_waits_for_its_open_interest(monkeypatch):
    monkeypatch.setattr(motilal, "_DEPTH_WAIT_SECONDS", 0.6)
    broker, _ = _motilal(monkeypatch, lambda scrip: _whole_book(scrip, oi=False))
    _, elapsed = timed(lambda: broker.get_depth("NIFTY26SEP25000CE", "NFO"))
    assert elapsed >= 0.6, "answered a derivative without its open interest packet"

    broker, _ = _motilal(monkeypatch, lambda scrip: _whole_book(scrip, oi=True))
    result, elapsed = timed(lambda: broker.get_depth("NIFTY26SEP25000CE", "NFO"))
    assert elapsed < 0.5
    assert result["oi"] == 123400


def test_motilal_quotes_answer_on_level_one_when_it_is_priced(monkeypatch):
    first_level = lambda scrip: [_mo_ltp(scrip), _mo_ohlc(scrip), _mo_level(scrip, 1)]  # noqa: E731
    broker, _ = _motilal(monkeypatch, first_level)
    quotes, elapsed = timed(lambda: broker.get_multiquotes([{"symbol": "SBIN", "exchange": "NSE"}]))
    assert elapsed < 1.5, f"waited {elapsed:.2f}s"
    assert quotes[0]["data"]["bid"] == 499.25 and quotes[0]["data"]["ask"] == 501.75


def test_motilal_quotes_with_an_empty_side_wait_for_the_whole_book(monkeypatch):
    """A quote reads the first level with a price, so an unpriced level one is not enough."""
    empty_bid = lambda scrip: [  # noqa: E731
        _mo_ltp(scrip),
        _mo_ohlc(scrip),
        _mo_packet(scrip, "B", struct.pack("<fihfih", 0.0, 0, 0, 501.0, 5, 1)),
    ]
    broker, _ = _motilal(monkeypatch, empty_bid)
    _, elapsed = timed(lambda: broker.get_multiquotes([{"symbol": "SBIN", "exchange": "NSE"}]))
    assert elapsed >= 2.0


def test_motilal_quotes_with_an_index_keep_the_full_wait(monkeypatch):
    """Index data outlives its registration, so what is there may be from before."""
    broker, client = _motilal(monkeypatch, lambda scrip: _whole_book(scrip))
    client.register_index = lambda exchange: True
    client.unregister_index = lambda exchange: True
    monkeypatch.setattr(
        motilal, "get_token", lambda symbol, exchange: "26000" if "INDEX" in exchange else "2885"
    )
    _, elapsed = timed(
        lambda: broker.get_multiquotes(
            [{"symbol": "SBIN", "exchange": "NSE"}, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
        )
    )
    assert elapsed >= 2.0


def test_has_snapshot_needs_every_packet_group():
    client = MotilalWebSocket("AA0", "tok", "key")
    assert client.has_snapshot("NSE", 1) is False
    client._parse_binary_market_data(b"".join(_whole_book(1)))
    assert client.has_snapshot("NSE", 1) is True
    assert client.has_snapshot("NSE", 1, need_oi=True) is False


# ---------------------------------------------------------------- Pocketful


class _PocketfulFeed:
    """The one module-level Pocketful socket: the latest packet, and nothing else."""

    def __init__(self, packets, delay):
        self.packets = packets
        self.delay = delay
        self.latest_detailed = {}
        self.latest_snap = {}

    def subscribe_detailed_marketdata(self, payload):
        for i, packet in enumerate(self.packets):
            later(self.delay * (i + 1), lambda p=packet: setattr(self, "latest_detailed", p))
        return True

    def subscribe_snapquote_data(self, payload):
        for i, packet in enumerate(self.packets):
            later(self.delay * (i + 1), lambda p=packet: setattr(self, "latest_snap", p))
        return True

    def read_detailed_marketdata(self):
        return self.latest_detailed

    def read_snapquote_data(self):
        return self.latest_snap

    def unsubscribe_detailed_marketdata(self, payload):
        return True

    def unsubscribe_snapquote_data(self, payload):
        return True


@contextmanager
def _one_row_session():
    row = SimpleNamespace(token="2885")
    query = SimpleNamespace(filter=lambda *a, **k: SimpleNamespace(first=lambda: row))
    yield SimpleNamespace(query=lambda *a, **k: query)


def _pocketful(monkeypatch, packets, delay=0.1):
    broker = pocketful.BrokerData("tok")
    broker.ws_connection = _PocketfulFeed(packets, delay)
    broker.ws_connected = True
    monkeypatch.setattr(pocketful, "db_session", _one_row_session)
    monkeypatch.setattr(pocketful, "get_br_symbol", lambda symbol, exchange: symbol)
    return broker


def _pf_detailed(token=2885, ltp=50050):
    return {
        "instrument_token": token,
        "exchange_code": 1,
        "last_traded_price": ltp,
        "best_bid_price": 50025,
        "best_ask_price": 50075,
        "high_price": 50250,
        "low_price": 49425,
        "open_price": 49500,
        "close_price": 49800,
        "trade_volume": 90000,
        "currentOpenInterest": 0,
    }


def test_pocketful_quote_takes_its_packet_as_soon_as_it_arrives(monkeypatch):
    broker = _pocketful(monkeypatch, [_pf_detailed()])
    quote, elapsed = timed(lambda: broker._get_quotes_compact("SBIN", "NSE"))
    assert elapsed < 0.8, f"waited {elapsed:.2f}s for a packet that arrived at 0.1s"
    assert quote["ltp"] == 500.5 and quote["bid"] == 500.25 and quote["prev_close"] == 498.0


def test_pocketful_quote_skips_another_instruments_packet(monkeypatch):
    broker = _pocketful(monkeypatch, [_pf_detailed(token=11, ltp=10), _pf_detailed()], delay=0.1)
    quote, elapsed = timed(lambda: broker._get_quotes_compact("SBIN", "NSE"))
    assert elapsed < 0.8
    assert quote["ltp"] == 500.5


def test_pocketful_quote_keeps_the_full_wait_without_its_packet(monkeypatch):
    monkeypatch.setattr(pocketful, "_QUOTE_WAIT_SECONDS", 0.4)
    broker = _pocketful(monkeypatch, [])
    started = time.monotonic()
    with pytest.raises(pocketful.PocketfulAPIError):
        broker._get_quotes_compact("SBIN", "NSE")
    assert time.monotonic() - started >= 0.4


def test_pocketful_depth_takes_its_book_as_soon_as_it_arrives(monkeypatch):
    book = {
        "instrument_token": 2885,
        "exchange_code": 1,
        "bidPrices": [50025, 50000, 49975, 49950, 49925],
        "bidQtys": [10, 20, 30, 40, 50],
        "buyers": [1, 2, 3, 4, 5],
        "askPrices": [50075, 50100, 50125, 50150, 50175],
        "askQtys": [15, 25, 35, 45, 55],
        "sellers": [1, 2, 3, 4, 5],
        "averageTradePrice": 50050,
        "open": 49500,
        "high": 50250,
        "low": 49425,
        "close": 49800,
        "totalBuyQty": 1500,
        "totalSellQty": 1750,
        "volume": 90000,
    }
    broker = _pocketful(monkeypatch, [book])
    depth, elapsed = timed(lambda: broker._get_market_depth_websocket("SBIN", "NSE"))
    assert elapsed < 0.8
    assert depth["bids"][4] == {"price": 499.25, "quantity": 50, "orders": 5}
    assert depth["totalsellqty"] == 1750


# ---------------------------------------------------------------- Tradejini


def _l1(symbol_key, **overrides):
    quote = {
        "symbol": symbol_key,
        "msgType": "L1",
        "ltp": 500.5,
        "open": 495.0,
        "high": 502.5,
        "low": 494.25,
        "close": 498.0,
        "vol": 90000,
        "bidPrice": 500.25,
        "askPrice": 500.75,
    }
    quote.update(overrides)
    return quote


class _TradejiniStream:
    """TradejiniWebSocket, connected, with a feed that answers a subscribe on a timer."""

    def __init__(self, l1_packets=(), l5_packets=(), delay=0.1):
        self.ws = tradejini.TradejiniWebSocket()
        self.ws.connected = True
        self.ws.nx_stream = SimpleNamespace(disconnect=lambda: None)
        self.subscribed_at = None
        self.l1_packets = list(l1_packets)
        self.l5_packets = list(l5_packets)
        self.delay = delay
        self.ws.subscribe_quotes = self._subscribe_quotes
        self.ws.subscribe_depth = self._subscribe_depth

    def _deliver(self, packets):
        for i, packet in enumerate(packets):
            later(self.delay * (i + 1), lambda p=packet: self.ws._on_data(None, dict(p)))

    def _subscribe_quotes(self, tokens):
        self.subscribed_at = time.monotonic()
        self._deliver(self.l1_packets)
        return True

    def _subscribe_depth(self, symbol, exchange, token):
        self.subscribed_at = time.monotonic()
        self._deliver(self.l5_packets)
        return True


def _tradejini(monkeypatch, stream):
    broker = tradejini.BrokerData("key:tok")
    broker.ws = stream.ws
    monkeypatch.setattr(tradejini, "get_token", lambda symbol, exchange: "2885")
    return broker


def test_tradejini_quote_answers_as_soon_as_the_quote_is_complete(monkeypatch):
    stream = _TradejiniStream(l1_packets=[_l1("2885_NSE")])
    broker = _tradejini(monkeypatch, stream)
    quote = broker.get_quotes("SBIN", "NSE")
    since_subscribe = time.monotonic() - stream.subscribed_at
    assert since_subscribe < 0.8, f"answered {since_subscribe:.2f}s after subscribing"
    assert quote["ltp"] == 500.5 and quote["ask"] == 500.75


def test_tradejini_quote_missing_a_field_is_read_on_the_second_as_before(monkeypatch):
    stream = _TradejiniStream(l1_packets=[_l1("2885_NSE", askPrice=None)])
    del stream.l1_packets[0]["askPrice"]
    broker = _tradejini(monkeypatch, stream)
    quote = broker.get_quotes("SBIN", "NSE")
    since_subscribe = time.monotonic() - stream.subscribed_at
    assert since_subscribe >= 1.0
    assert quote["ask"] == 0.0 and quote["ltp"] == 500.5


def test_tradejini_depth_takes_the_first_book(monkeypatch):
    book = {
        "symbol": "2885_NSE",
        "msgType": "L5",
        "bid": [{"price": 500.25 - i, "qty": 10 * (i + 1)} for i in range(5)],
        "ask": [{"price": 500.75 + i, "qty": 20 * (i + 1)} for i in range(5)],
    }
    stream = _TradejiniStream(l5_packets=[book])
    broker = _tradejini(monkeypatch, stream)
    depth, elapsed = timed(lambda: broker.get_depth("SBIN", "NSE"))
    assert elapsed < 0.8
    assert depth["bids"][4] == {"price": 496.25, "quantity": 50}
    assert depth["totalbuyqty"] == 150


def test_tradejini_batch_ends_when_every_quote_is_complete(monkeypatch):
    stream = _TradejiniStream(l1_packets=[_l1("2885_NFO", OI=4500), _l1("11_NSE")])
    broker = _tradejini(monkeypatch, stream)
    tokens = {"NIFTYFUT": "2885", "INFY": "11"}
    monkeypatch.setattr(tradejini, "get_token", lambda symbol, exchange: tokens[symbol])
    quotes = broker._process_multiquotes_batch(
        [{"symbol": "NIFTYFUT", "exchange": "NFO"}, {"symbol": "INFY", "exchange": "NSE"}]
    )
    since_subscribe = time.monotonic() - stream.subscribed_at
    assert since_subscribe < 1.0, f"answered {since_subscribe:.2f}s after subscribing"
    by_symbol = {q["symbol"]: q["data"] for q in quotes}
    assert by_symbol["NIFTYFUT"]["oi"] == 4500 and by_symbol["INFY"]["ltp"] == 500.5


def test_tradejini_batch_waits_for_open_interest_on_a_derivative(monkeypatch):
    stream = _TradejiniStream(l1_packets=[_l1("2885_NFO")])
    broker = _tradejini(monkeypatch, stream)
    broker._process_multiquotes_batch([{"symbol": "NIFTYFUT", "exchange": "NFO"}])
    since_subscribe = time.monotonic() - stream.subscribed_at
    assert since_subscribe >= 2.0


# ---------------------------------------------------------------- Nubra


class _NubraSocket:
    """NubraWebSocket's caches and subscribe calls, with a timed feed."""

    def __init__(self, delay=0.1):
        self.is_connected = True
        self.last_quotes = {}
        self.last_depth = {}
        self.delay = delay
        self.depth_packets = {}
        self.quote_packets = {}

    def _deliver(self, store, key, packets):
        def put(packet):
            store.setdefault(key, {}).update(packet)

        for i, packet in enumerate(packets):
            later(self.delay * (i + 1), lambda p=packet: put(p))

    def subscribe_orderbook(self, ref_ids):
        for ref in ref_ids:
            self._deliver(self.last_depth, ref, self.depth_packets.get(ref, []))
        return True

    def subscribe_index(self, symbols, exchange="NSE"):
        for sym in symbols:
            key = (exchange, sym.upper())
            self._deliver(self.last_quotes, key, self.quote_packets.get(key, []))
        return True

    def subscribe_ohlcv(self, symbols, interval, exchange="NSE"):
        return self.subscribe_index(symbols, exchange)

    def change_orderbook_depth(self, depth=5):
        return True

    def subscribe_greeks(self, ref_ids):
        return True

    def unsubscribe_orderbook(self, ref_ids):
        return True

    def unsubscribe_greeks(self, ref_ids):
        return True

    def unsubscribe_index(self, symbols, exchange="NSE"):
        return True

    def unsubscribe_ohlcv(self, symbols, interval, exchange="NSE"):
        return True

    def get_quote(self, exchange, symbol):
        return self.last_quotes.get((exchange, symbol.upper()))

    def get_market_depth(self, ref_id):
        return self.last_depth.get(ref_id)


def _nubra_book(levels=5, ltp=500.5):
    return {
        "ltp": ltp,
        "ltq": 7,
        "volume": 90000,
        "bids": [{"price": 500.25 - i, "quantity": 10} for i in range(levels)]
        + [{"price": 0, "quantity": 0}] * (5 - levels),
        "asks": [{"price": 500.75 + i, "quantity": 20} for i in range(levels)]
        + [{"price": 0, "quantity": 0}] * (5 - levels),
        "totalbuyqty": 10 * levels,
        "totalsellqty": 20 * levels,
    }


def _nubra(monkeypatch, socket):
    broker = nubra.BrokerData("tok")
    monkeypatch.setattr(broker, "get_websocket", lambda force_new=False: socket, raising=False)
    monkeypatch.setattr(nubra, "get_token", lambda symbol, exchange: "2885")
    monkeypatch.setattr(nubra, "get_br_symbol", lambda symbol, exchange: symbol)
    return broker


def test_nubra_depth_answers_once_the_book_and_open_interest_are_in(monkeypatch):
    socket = _NubraSocket(delay=0.05)
    socket.depth_packets[2885] = [_nubra_book(), {"oi": 4500}]
    broker = _nubra(monkeypatch, socket)
    depth, elapsed = timed(lambda: broker._get_depth_via_websocket("NIFTY26SEP25000CE", "NFO"))
    assert elapsed < 0.4, f"waited {elapsed:.2f}s"
    assert depth["oi"] == 4500 and depth["bids"][4]["price"] == 496.25


def test_nubra_depth_without_open_interest_is_read_on_the_half_second(monkeypatch):
    socket = _NubraSocket(delay=0.05)
    socket.depth_packets[2885] = [_nubra_book()]
    broker = _nubra(monkeypatch, socket)
    depth, elapsed = timed(lambda: broker._get_depth_via_websocket("SBIN", "NSE"))
    assert elapsed >= 0.5
    assert depth["oi"] == 0 and depth["ltp"] == 500.5


def test_nubra_depth_does_not_stop_on_a_shallow_first_book(monkeypatch):
    """The request turns five levels on; a book from before that is not the answer."""
    socket = _NubraSocket(delay=0.05)
    socket.depth_packets[2885] = [_nubra_book(levels=1), {"oi": 4500}]
    broker = _nubra(monkeypatch, socket)
    _, elapsed = timed(lambda: broker._get_depth_via_websocket("NIFTY26SEP25000CE", "NFO"))
    assert elapsed >= 0.5


def test_nubra_instrument_quote_answers_from_the_index_channel_at_once(monkeypatch):
    socket = _NubraSocket()
    socket.quote_packets[("NSE", "SBIN")] = [
        {"ltp": 500.5, "high": 502.5, "low": 494.25, "volume": 90000, "prev_close": 498.0}
    ]
    broker = _nubra(monkeypatch, socket)
    quote, elapsed = timed(lambda: broker._get_quotes_via_websocket("SBIN", "NSE"))
    assert elapsed < 1.0
    assert quote["ltp"] == 500.5 and quote["prev_close"] == 498.0


def test_nubra_index_quote_keeps_the_full_wait(monkeypatch):
    monkeypatch.setattr(nubra, "_QUOTE_WAIT_SECONDS", 0.5)
    socket = _NubraSocket()
    socket.quote_packets[("NSE", "NIFTY")] = [{"ltp": 25000.0, "open": 24900.0}]
    broker = _nubra(monkeypatch, socket)
    quote, elapsed = timed(lambda: broker._get_quotes_via_websocket("NIFTY", "NSE_INDEX"))
    assert elapsed >= 0.5
    assert quote["ltp"] == 25000.0


def test_nubra_batch_of_options_ends_when_every_book_is_complete(monkeypatch):
    socket = _NubraSocket(delay=0.05)
    tokens = {"CE": 101, "PE": 102}
    for token in tokens.values():
        socket.depth_packets[token] = [_nubra_book(), {"oi": token}]
    broker = _nubra(monkeypatch, socket)
    monkeypatch.setattr(nubra, "get_token", lambda symbol, exchange: str(tokens[symbol]))
    quotes, elapsed = timed(
        lambda: broker.get_multiquotes(
            [{"symbol": "CE", "exchange": "NFO"}, {"symbol": "PE", "exchange": "NFO"}]
        )
    )
    assert elapsed < 1.0, f"waited {elapsed:.2f}s"
    assert sorted(q["data"]["oi"] for q in quotes) == [101, 102]
