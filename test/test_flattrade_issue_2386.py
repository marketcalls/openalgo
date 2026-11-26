"""Regression contracts for GitHub issue #2386 (Flattrade order updates).

With OpenAlgo left running overnight on Flattrade, the REST order-update poller
kept reading the order book with the previous day's token, and from about
05:00 IST Flattrade's non-JSON answer made order_api.py raise on every poll,
logging a traceback every 5 seconds.

Flattrade order updates are now event driven (flattrade_order_adapter.py):

  - order frames ride the market-data socket and reach the Flask process over
    a Flattrade-only relay (flattrade_order_relay.py), because PiConnect
    allows one session per uid (#1806);
  - with no market-data adapter running, a socket of our own carries them, and
    it steps aside on the market-data adapter's "claim";
  - nothing connects or reads after the session rollover without a new login,
    and a refused token stands the adapter down until the next login;
  - one order-book read after each new stream publishes what a handover
    missed.

Plus: order_api.get_api_response no longer raises on a non-JSON body.

Self-contained: no broker call. The relay round trip binds one local port.
"""

from __future__ import annotations

import importlib
import json
import logging
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# websocket_proxy must load before any broker.*.streaming module.
importlib.import_module("websocket_proxy")

from broker.flattrade.streaming import flattrade_order_adapter as foa  # noqa: E402
from broker.flattrade.streaming import flattrade_order_relay as relay_mod  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")

OM_FRAME = json.dumps(
    {
        "t": "om",
        "norenordno": "26111700000001",
        "tsym": "SBIN-EQ",
        "exch": "NSE",
        "trantype": "B",
        "qty": "10",
        "fillshares": "10",
        "prc": "0",
        "prctyp": "MKT",
        "pcode": "I",
        "status": "COMPLETE",
        "avgprc": "812.5",
    }
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class _FakeRelay:
    bound = True

    def __init__(self):
        self.handlers = {}

    def add_handler(self, handler):
        self.handlers[1] = handler
        return 1

    def remove_handler(self, handle):
        self.handlers.pop(handle, None)


class _FakeSocket:
    """Stands in for FlattradeOrderUpdateAdapter (the standalone socket)."""

    instances: list[_FakeSocket] = []

    def __init__(self, user_id, flattrade_uid, accesstoken):
        self.accesstoken = accesstoken
        self._running = False
        self._auth_rejected = False
        self.connects = 0
        self.disconnects = 0
        self.on_order = None
        self.on_subscribed = None
        _FakeSocket.instances.append(self)

    def connect(self):
        self.connects += 1
        self._running = True

    def disconnect(self):
        self.disconnects += 1
        self._running = False


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr(
        foa.FlattradeOrderUpdateAdapter,
        "_publish_event_fields",
        lambda self, fields: events.append(dict(fields)),
    )
    return events


@pytest.fixture
def event_adapter(monkeypatch, published):
    """Running adapter with no supervisor thread; ticks are driven by hand."""
    _FakeSocket.instances = []
    monkeypatch.setattr(foa, "FlattradeOrderUpdateAdapter", _FakeSocket)
    monkeypatch.setattr(foa, "get_auth_token", lambda *a, **k: "tok")
    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: True)

    relay = _FakeRelay()
    adapter = foa.FlattradeEventOrderAdapter("user", "FZ06120", relay)
    # Real publisher class captured before the monkeypatch above replaced it.
    adapter._publisher = _Publisher(published)
    _FakeSocket.instances = []  # the constructor built its publisher from the fake
    adapter._running = True
    adapter._generation = 1
    adapter._started_at = time.monotonic() - foa.STARTUP_GRACE_SECONDS - 1
    return adapter


class _Publisher:
    def __init__(self, sink):
        self.sink = sink

    def _publish_event_fields(self, fields):
        self.sink.append(dict(fields))


def _relay(adapter, kind, frame=None, user_id="user", actid="FZ06120"):
    message = {"kind": kind, "user_id": user_id, "actid": actid}
    if frame is not None:
        message["frame"] = frame
    adapter._on_relay_message(message)


# --------------------------------------------------------------------------
# 1. order_api no longer raises on a non-JSON answer
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _Client:
    def __init__(self, response):
        self.response = response

    def request(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize("body", ["", "<html>Session Expired</html>", "not json"])
def test_a_non_json_answer_is_a_not_ok_not_an_exception(monkeypatch, caplog, body):
    from broker.flattrade.api import order_api

    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")
    monkeypatch.setattr(order_api.DATA_LIMITER, "acquire", lambda *a, **k: None)
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: _Client(_Response(body, 502)))

    with caplog.at_level(logging.DEBUG):
        result = order_api.get_order_book("dead-token")

    assert result["stat"] == "Not_Ok"
    assert "log in to the broker again" in result["emsg"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("502" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)


# --------------------------------------------------------------------------
# 2. The market-data adapter carries and relays order updates
# --------------------------------------------------------------------------


class _RecordingRelay:
    def __init__(self):
        self.sent = []
        self.closed = False

    def publish(self, kind, frame=None):
        self.sent.append((kind, frame))

    def close(self):
        self.closed = True


class _WsClient:
    def __init__(self, events, connects=True):
        self.events = events
        self.messages = []
        self._connects = connects
        self.auth_failed = False
        self.auth_failure_message = ""

    def connect(self):
        self.events.append("ws.connect")
        return self._connects

    def stop(self):
        self.events.append("ws.stop")

    def _send_message(self, message, operation):
        self.messages.append(message)
        return True

    def subscribe_touchline(self, scrips):
        return True

    def subscribe_depth(self, scrips):
        return True


@pytest.fixture
def md_adapter(monkeypatch):
    pytest.importorskip("sqlalchemy")
    module = importlib.import_module("broker.flattrade.streaming.flattrade_adapter")
    instance = module.FlattradeWebSocketAdapter.__new__(module.FlattradeWebSocketAdapter)
    instance.logger = module.get_logger("flattrade_test_2386")
    instance._setup_adapter()
    instance._setup_market_cache()
    instance._setup_connection_management()
    instance.running = True
    instance.actid = "FZ06120"
    instance.user_id = "user"
    instance.accesstoken = "tok"
    events = []
    relay = _RecordingRelay()
    original_publish = relay.publish

    def publish(kind, frame=None):
        events.append(f"relay.{kind}")
        original_publish(kind, frame)

    relay.publish = publish
    instance._order_relay = relay
    instance.ws_client = _WsClient(events)
    instance.cleanup_zmq = lambda: None
    instance._events = events
    instance._relay_recorder = relay
    return instance


def test_an_order_frame_is_relayed_verbatim_and_not_parsed_as_market_data(md_adapter):
    called = []
    md_adapter._process_market_message = lambda data: called.append(data)

    md_adapter._on_message(None, OM_FRAME)

    assert md_adapter._relay_recorder.sent == [("om", OM_FRAME)]
    assert called == []


def test_the_open_session_subscribes_order_updates_and_says_ready(md_adapter):
    md_adapter._on_open(None)

    assert {"t": "o", "actid": "FZ06120"} in md_adapter.ws_client.messages
    assert ("ready", None) in md_adapter._relay_recorder.sent


def test_the_claim_goes_out_before_the_socket_connects(md_adapter):
    md_adapter.connect()

    events = md_adapter._events
    assert events.index("relay.claim") < events.index("ws.connect")


def test_a_failed_first_connect_releases_the_session(md_adapter):
    """The proxy drops an adapter whose connect raises without calling
    disconnect(); its "alive" beat must not keep the Flask side waiting."""
    relay = md_adapter._relay_recorder
    md_adapter.ws_client = _WsClient(md_adapter._events, connects=False)

    with pytest.raises(ConnectionError):
        md_adapter.connect()

    assert ("release", None) in relay.sent
    assert relay.closed
    assert md_adapter._order_relay is None
    beat = md_adapter._order_relay_thread
    if beat is not None:
        beat.join(timeout=2)
        assert not beat.is_alive(), "the alive beat outlived the released session"


def test_a_reconnect_claims_before_it_connects(md_adapter, monkeypatch):
    module = sys.modules[type(md_adapter).__module__]
    events = md_adapter._events
    monkeypatch.setattr(module, "get_auth_token", lambda *a, **k: "tok")
    monkeypatch.setattr(module, "FlattradeWebSocket", lambda **kw: _WsClient(events))

    md_adapter._attempt_reconnection()

    assert events.index("relay.claim") < events.index("ws.connect")


def test_disconnect_releases_the_session_after_the_socket_is_closed(md_adapter):
    relay = md_adapter._relay_recorder
    md_adapter.disconnect()

    events = md_adapter._events
    assert events.index("ws.stop") < events.index("relay.release")
    assert relay.closed
    assert md_adapter._order_relay is None


def test_giving_up_on_a_refused_token_releases_the_session(md_adapter):
    relay = md_adapter._relay_recorder
    md_adapter.auth_refresh_retries = md_adapter.max_auth_refresh_retries

    md_adapter._handle_auth_failure("Invalid Session")

    assert not md_adapter.running
    assert ("release", None) in relay.sent


# --------------------------------------------------------------------------
# 3. Relay mode: frames from the market-data socket become events
# --------------------------------------------------------------------------


def test_a_relayed_frame_is_published_as_an_order_update(event_adapter, published):
    _relay(event_adapter, "om", OM_FRAME)

    assert len(published) == 1
    event = published[0]
    assert event["orderid"] == "26111700000001"
    assert event["order_status"] == "complete"
    assert event["action"] == "BUY"
    assert event["product"] == "MIS"
    assert event["pricetype"] == "MARKET"
    assert event["filled_quantity"] == 10


def test_messages_for_another_account_are_ignored(event_adapter, published):
    _relay(event_adapter, "om", OM_FRAME, user_id="other", actid="FZ99999")
    _relay(event_adapter, "claim", user_id="other", actid="FZ99999")

    assert published == []
    assert event_adapter._owner_seen_at is None


def test_the_account_id_matches_when_the_user_name_differs(event_adapter, published):
    _relay(event_adapter, "om", OM_FRAME, user_id="someone-else")
    assert len(published) == 1


def test_a_stopped_adapter_publishes_nothing(event_adapter, published):
    event_adapter._running = False
    _relay(event_adapter, "om", OM_FRAME)
    assert published == []


# --------------------------------------------------------------------------
# 4. Standalone mode and the handover
# --------------------------------------------------------------------------


def test_with_no_market_data_adapter_a_socket_of_our_own_opens(event_adapter):
    event_adapter._tick(1)

    assert len(_FakeSocket.instances) == 1
    assert _FakeSocket.instances[0].connects == 1
    assert event_adapter._socket is _FakeSocket.instances[0]


def test_nothing_opens_during_the_startup_grace(event_adapter):
    event_adapter._started_at = time.monotonic()
    event_adapter._tick(1)
    assert _FakeSocket.instances == []


def test_nothing_opens_while_the_market_data_adapter_holds_the_session(event_adapter):
    _relay(event_adapter, "alive")
    event_adapter._tick(1)
    assert _FakeSocket.instances == []


def test_a_claim_closes_our_socket_at_once(event_adapter):
    event_adapter._tick(1)
    own = event_adapter._socket

    _relay(event_adapter, "claim")

    assert own.disconnects == 1
    assert event_adapter._socket is None
    event_adapter._tick(1)
    assert len(_FakeSocket.instances) == 1, "reopened while the market-data adapter holds it"


def test_a_claim_during_the_token_read_keeps_the_socket_from_opening(event_adapter, monkeypatch):
    """The race lands at the write: the claim arrives between the token read
    and publishing the new socket."""

    def token_then_claim(*args, **kwargs):
        _relay(event_adapter, "claim")
        return "tok"

    monkeypatch.setattr(foa, "get_auth_token", token_then_claim)
    event_adapter._tick(1)

    assert event_adapter._socket is None
    assert all(s.connects == 0 for s in _FakeSocket.instances)


def test_after_release_order_updates_take_their_own_socket(event_adapter):
    _relay(event_adapter, "alive")
    _relay(event_adapter, "release")
    event_adapter._tick(1)
    assert len(_FakeSocket.instances) == 1


def test_a_silent_market_data_adapter_is_given_up_after_the_timeout(event_adapter):
    event_adapter._owner_seen_at = time.monotonic() - foa.OWNER_TIMEOUT_SECONDS - 1
    event_adapter._tick(1)
    assert len(_FakeSocket.instances) == 1


def test_a_dropped_socket_is_retried_with_backoff(event_adapter):
    event_adapter._tick(1)
    _FakeSocket.instances[0]._running = False  # the single attempt ended

    event_adapter._tick(1)
    assert event_adapter._socket is None
    assert event_adapter._next_standalone_at > time.monotonic()
    event_adapter._tick(1)
    assert len(_FakeSocket.instances) == 1, "retried without waiting"

    event_adapter._next_standalone_at = 0
    event_adapter._tick(1)
    assert len(_FakeSocket.instances) == 2


# --------------------------------------------------------------------------
# 5. Rollover: no connect, no read, without a login this session
# --------------------------------------------------------------------------


def test_without_a_login_this_session_nothing_connects_or_reads(event_adapter, monkeypatch, caplog):
    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: False)
    reads = []
    import services.orderbook_service as obs

    monkeypatch.setattr(obs, "get_orderbook", lambda **kw: reads.append(kw))
    event_adapter._catch_up_pending = True

    with caplog.at_level(logging.INFO):
        for _ in range(3):
            event_adapter._session_ok = None  # defeat the cache: every tick asks
            event_adapter._tick(1)

    assert _FakeSocket.instances == []
    assert reads == []
    paused = [r for r in caplog.records if "paused" in r.getMessage()]
    assert len(paused) == 1


def test_a_socket_open_at_the_rollover_is_closed(event_adapter, monkeypatch):
    event_adapter._tick(1)
    own = event_adapter._socket

    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: False)
    event_adapter._session_ok = None
    event_adapter._tick(1)

    assert own.disconnects == 1
    assert event_adapter._socket is None


def test_a_refused_token_stands_the_adapter_down(event_adapter):
    event_adapter._tick(1)
    own = event_adapter._socket
    own._running = False
    own._auth_rejected = True

    event_adapter._tick(1)
    event_adapter._next_standalone_at = 0
    event_adapter._tick(1)

    assert event_adapter._auth_rejected
    assert len(_FakeSocket.instances) == 1


def _sessions(monkeypatch, login_time):
    import database.auth_db as auth_db

    monkeypatch.setattr(
        auth_db, "get_active_sessions", lambda user: [{"login_time": login_time.isoformat()}]
    )


@pytest.mark.parametrize(
    ("now", "login", "current"),
    [
        # 01:30 IST: an evening login still belongs to the running session.
        (datetime(2026, 11, 18, 1, 30), datetime(2026, 11, 17, 21, 0), True),
        # 05:00 IST: yesterday evening's login has rolled over.
        (datetime(2026, 11, 18, 5, 0), datetime(2026, 11, 17, 21, 0), False),
        # 05:00 IST with a login after 03:00.
        (datetime(2026, 11, 18, 5, 0), datetime(2026, 11, 18, 4, 0), True),
    ],
)
def test_the_session_check_measures_from_the_last_rollover(monkeypatch, now, login, current):
    import utils.session as session

    monkeypatch.setattr(session, "is_session_expiry_disabled", lambda: False)
    now_ist = IST.localize(now)
    real = session.last_rollover_boundary
    monkeypatch.setattr(session, "last_rollover_boundary", lambda now_ist_=None: real(now_ist))
    _sessions(monkeypatch, login)  # naive IST, as SQLite stores it

    assert foa._login_this_trading_session("user") is current


def test_disabled_session_expiry_is_always_current(monkeypatch):
    import utils.session as session

    monkeypatch.setattr(session, "is_session_expiry_disabled", lambda: True)
    assert foa._login_this_trading_session("user") is True


# --------------------------------------------------------------------------
# 6. Catch-up after a new stream
# --------------------------------------------------------------------------


def _book(*orders):
    return (
        True,
        {"status": "success", "data": {"orders": [dict(o) for o in orders]}},
        200,
    )


def _order(orderid, status, filled=0):
    return {
        "orderid": orderid,
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "price": 0,
        "trigger_price": 0,
        "pricetype": "MARKET",
        "product": "MIS",
        "order_status": status,
        "filled_quantity": filled,
        "pending_quantity": 10 - filled,
        "average_price": 0,
    }


def test_the_first_read_records_and_a_later_one_publishes_the_gap(
    event_adapter, published, monkeypatch
):
    import services.orderbook_service as obs

    books = [
        _book(_order("1", "open"), _order("2", "open")),
        _book(_order("1", "complete", 10), _order("2", "open"), _order("3", "rejected")),
    ]
    monkeypatch.setattr(obs, "get_orderbook", lambda **kw: books.pop(0))

    event_adapter._catch_up()
    assert published == [], "the first read must only record"

    event_adapter._catch_up()
    assert sorted(e["orderid"] for e in published) == ["1", "3"]
    assert {e["orderid"]: e["order_status"] for e in published} == {
        "1": "complete",
        "3": "rejected",
    }


def test_an_update_already_pushed_is_not_published_again(event_adapter, published, monkeypatch):
    import services.orderbook_service as obs

    books = [
        _book(_order("26111700000001", "open")),
        _book(_order("26111700000001", "complete", 10)),
    ]
    monkeypatch.setattr(obs, "get_orderbook", lambda **kw: books.pop(0))

    event_adapter._catch_up()
    _relay(event_adapter, "om", OM_FRAME)  # the fill arrives by push
    event_adapter._catch_up()

    assert [e["order_status"] for e in published] == ["complete"]


def test_trigger_pending_and_open_are_the_same_state_to_the_catch_up(
    event_adapter, published, monkeypatch
):
    import services.orderbook_service as obs

    frame = json.loads(OM_FRAME)
    frame.update(status="TRIGGER_PENDING", fillshares="0", prctyp="SL-LMT")
    books = [_book(), _book(_order("26111700000001", "open"))]
    monkeypatch.setattr(obs, "get_orderbook", lambda **kw: books.pop(0))

    event_adapter._catch_up()
    _relay(event_adapter, "om", json.dumps(frame))
    event_adapter._catch_up()

    assert [e["order_status"] for e in published] == ["trigger pending"]


def test_ready_from_the_market_data_adapter_schedules_a_catch_up(event_adapter):
    _relay(event_adapter, "ready")
    assert event_adapter._catch_up_pending


# --------------------------------------------------------------------------
# 7. The standalone socket itself
# --------------------------------------------------------------------------


class _Ws:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


def test_a_refused_connect_ack_closes_and_stands_down():
    from broker.flattrade.streaming.flattrade_order_adapter import FlattradeOrderUpdateAdapter

    socket_adapter = FlattradeOrderUpdateAdapter("user", "FZ06120", "tok")
    ws = _Ws()
    socket_adapter._ws = ws

    socket_adapter.normalize(json.dumps({"t": "ak", "s": "Not_Ok", "emsg": "Invalid Session"}))

    assert ws.closed
    assert socket_adapter._auth_rejected
    assert ws.sent == []


def test_an_accepted_ack_subscribes_and_reports_it():
    from broker.flattrade.streaming.flattrade_order_adapter import FlattradeOrderUpdateAdapter

    socket_adapter = FlattradeOrderUpdateAdapter("user", "FZ06120", "tok")
    ws = _Ws()
    socket_adapter._ws = ws
    seen = []
    socket_adapter.on_subscribed = lambda: seen.append(True)

    socket_adapter.normalize(json.dumps({"t": "ak", "s": "OK"}))

    assert ws.sent == [{"t": "o", "actid": "FZ06120"}]
    assert seen == [True]


def test_the_standalone_socket_makes_one_attempt_only(monkeypatch):
    from broker.flattrade.streaming.flattrade_order_adapter import FlattradeOrderUpdateAdapter

    socket_adapter = FlattradeOrderUpdateAdapter("user", "FZ06120", "tok")
    attempts = []
    monkeypatch.setattr(
        socket_adapter, "_connect_once", lambda generation=None: attempts.append(generation)
    )
    socket_adapter._running = True
    socket_adapter._generation = 3

    socket_adapter._run_forever(3)

    assert attempts == [3]
    assert not socket_adapter._running


# --------------------------------------------------------------------------
# 8. The relay itself
# --------------------------------------------------------------------------


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_relay_port_follows_zmq_port(monkeypatch):
    monkeypatch.delenv("FLATTRADE_ORDER_RELAY_PORT", raising=False)
    monkeypatch.setenv("ZMQ_PORT", "5557")
    assert relay_mod.relay_port() == 5657
    monkeypatch.setenv("FLATTRADE_ORDER_RELAY_PORT", "6001")
    assert relay_mod.relay_port() == 6001


def test_a_frame_crosses_the_relay(monkeypatch):
    monkeypatch.setenv("FLATTRADE_ORDER_RELAY_PORT", str(_free_port()))
    listener = relay_mod.OrderRelayListener()
    assert listener.bound
    received = []
    listener.add_handler(received.append)
    publisher = relay_mod.OrderRelayPublisher("user", "FZ06120")
    try:
        deadline = time.monotonic() + 5
        while not received and time.monotonic() < deadline:
            publisher.publish("om", frame=OM_FRAME)
            time.sleep(0.1)
    finally:
        publisher.close()
        listener.close()

    assert received, "nothing crossed the relay"
    assert received[0] == {"kind": "om", "user_id": "user", "actid": "FZ06120", "frame": OM_FRAME}


def test_a_second_binder_falls_back_instead_of_raising(monkeypatch, caplog):
    monkeypatch.setenv("FLATTRADE_ORDER_RELAY_PORT", str(_free_port()))
    first = relay_mod.OrderRelayListener()
    try:
        with caplog.at_level(logging.WARNING):
            second = relay_mod.OrderRelayListener()
        assert first.bound
        assert not second.bound
        assert any("falling back" in r.getMessage() for r in caplog.records)
    finally:
        first.close()


# --------------------------------------------------------------------------
# 9. Found by the overnight run of 2026-11-17/18
# --------------------------------------------------------------------------
#
# The app was restarted with the debug reloader. Startup ran in the reloader's
# watcher process first, which took the relay port; the serving process then
# fell back to the shared poller, and that poller read the order book with the
# expired token every 5 s from 06:04.


@pytest.mark.parametrize(
    ("debug", "run_main", "watcher"),
    [
        ("True", None, True),
        ("true", "true", False),
        ("False", None, False),
        (None, None, False),
    ],
)
def test_the_reloader_watcher_is_recognised(monkeypatch, debug, run_main, watcher):
    for name, value in (("FLASK_DEBUG", debug), ("WERKZEUG_RUN_MAIN", run_main)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert relay_mod.is_reloader_watcher() is watcher


def test_the_reloader_watcher_starts_no_order_updates(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "True")
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    bound = []
    monkeypatch.setattr(relay_mod, "listener", lambda: bound.append(1))

    assert foa.create_flattrade_order_adapter("user") is None
    assert bound == [], "the watcher must not take the relay port"


def test_a_failed_bind_is_retried_on_the_next_call(monkeypatch):
    attempts = []

    class _Listener:
        def __init__(self):
            attempts.append(1)
            self.bound = len(attempts) > 1

    monkeypatch.setattr(relay_mod, "OrderRelayListener", _Listener)
    monkeypatch.setattr(relay_mod, "_listener", None)

    assert not relay_mod.listener().bound
    assert relay_mod.listener().bound
    assert relay_mod.listener().bound
    assert len(attempts) == 2


class _Poller:
    def __init__(self):
        self.connects = 0
        self.disconnects = 0

    def connect(self):
        self.connects += 1

    def disconnect(self):
        self.disconnects += 1


def test_the_polling_fallback_stops_at_the_rollover(monkeypatch, caplog):
    poller = foa.FlattradeSessionPoller("user")
    poller._poller = inner = _Poller()

    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: True)
    poller._check()
    assert inner.connects == 1

    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: False)
    with caplog.at_level(logging.INFO):
        poller._check()
        poller._check()
    assert inner.disconnects == 2
    assert len([r for r in caplog.records if "paused" in r.getMessage()]) == 1

    monkeypatch.setattr(foa, "_login_this_trading_session", lambda user_id: True)
    poller._check()
    assert inner.connects == 2, "polling did not resume after a new login"


def test_a_stopped_fallback_stops_its_poller():
    poller = foa.FlattradeSessionPoller("user")
    poller._poller = inner = _Poller()
    poller._running = True

    poller.disconnect()

    assert inner.disconnects == 1
    assert not poller.connected
