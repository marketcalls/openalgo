"""HDFC Sky streaming: ports of the HDFC Securities fixes.

- *_CIRC and *_OI packets are partial refreshes (only the band or OI is set);
  they are tagged and merged into the last full snapshot instead of being
  published as a quote with ltp/OHLC/volume 0.
- Subscription state is keyed (exchange, token): the instrumentId is unique
  only within an exchange, and the exchange comes from the packet type.
- Every subscribed mode is tracked; the broker stays subscribed at the
  highest mode any subscriber still needs, and unsubscribing one mode does
  not drop the others.
"""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)

adapter_mod = pytest.importorskip("broker.hdfcsky.streaming.hdfcsky_adapter")
ws_mod = pytest.importorskip("broker.hdfcsky.streaming.hdfcsky_websocket")
pb = pytest.importorskip("broker.hdfcsky.streaming.hdfcsky_market_pb2")


def _ws():
    ws = ws_mod.HDFCSkyWebSocket.__new__(ws_mod.HDFCSkyWebSocket)
    ws.logger = MagicMock()
    return ws


def _adapter():
    adapter = adapter_mod.HDFCSkyWebSocketAdapter.__new__(adapter_mod.HDFCSkyWebSocketAdapter)
    adapter.logger = MagicMock()
    adapter.token_info = {}
    adapter.last_snapshot = {}
    adapter._state_lock = threading.Lock()
    adapter._subscription_seq = 0
    adapter._feed_epoch = 0
    adapter.ws_client = MagicMock()
    adapter.publish_market_data = MagicMock()
    return adapter


def _packet(packet_type, token=2885, **mbp):
    packet = pb.GenericDTO()
    packet.packetType = packet_type
    packet.instrumentId = token
    packet.packetTimestamp = 1700000000000
    for key, value in mbp.items():
        setattr(packet.mbpData, key, value)
    return packet


FULL = {
    "lastTradedPrice": 1500.5,
    "openPrice": 1490.0,
    "highPrice": 1510.0,
    "lowPrice": 1480.0,
    "closingPrice": 1495.0,
    "volumeTradedToday": 12345,
    "lastTradeQuantity": 3,
    "averageTradePrice": 1499.0,
    "lastTradeTime": 1700000000,
}


def test_circuit_and_oi_packets_are_tagged_partial():
    ws = _ws()
    circ = ws._parse_packet(
        _packet(pb.NSE_FO_CIRC, lowerCircuitLimit=1350.0, upperCircuitLimit=1650.0)
    )
    assert circ["kind"] == "circuit"
    assert "ltp" not in circ
    oi = ws._parse_packet(_packet(pb.NSE_FO_OI, oi=777))
    assert oi["kind"] == "oi"
    assert "ltp" not in oi
    assert oi["exchange"] == "NFO"


def test_partial_packets_merge_into_snapshot_instead_of_blanking():
    ws = _ws()
    adapter = _adapter()
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("NIFTYFUT", "NFO", 3)

    adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_FO_ALL, **FULL))])
    adapter._on_ticks(
        [
            ws._parse_packet(
                _packet(pb.NSE_FO_CIRC, lowerCircuitLimit=1350.0, upperCircuitLimit=1650.0)
            ),
            ws._parse_packet(_packet(pb.NSE_FO_OI, oi=777)),
        ]
    )
    last = adapter.publish_market_data.call_args.args[1]
    assert last["ltp"] == 1500.5
    assert last["volume"] == 12345
    assert last["open"] == 1490.0
    assert last["oi"] == 777
    assert last["upper_circuit"] == 1650.0


def test_partial_packet_without_snapshot_is_not_published():
    adapter = _adapter()
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("NIFTYFUT", "NFO", 2)
    adapter._on_ticks([_ws()._parse_packet(_packet(pb.NSE_FO_OI, oi=777))])
    adapter.publish_market_data.assert_not_called()


def test_same_token_on_two_exchanges_routes_by_packet_type():
    ws = _ws()
    adapter = _adapter()
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("EQ", "NSE", 2)
        adapter.subscribe("CUR", "CDS", 2)
    adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_CD_ALL, **FULL))])
    topics = [c.args[0] for c in adapter.publish_market_data.call_args_list]
    assert topics == ["CDS_CUR_QUOTE"]


def test_modes_tracked_and_highest_kept_at_broker():
    adapter = _adapter()
    reg = adapter_mod.HDFCSkyCapabilityRegistry
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("EQ", "NSE", 3)
        adapter.subscribe("EQ", "NSE", 1)
        # A later LTP subscribe must not downgrade the broker subscription.
        assert adapter.ws_client.subscribe_scrips.call_args.args[1] == (
            reg.get_subscription_type_for_numeric(3)
        )
        adapter.unsubscribe("EQ", "NSE", 3)
        adapter.ws_client.unsubscribe.assert_not_called()
        assert adapter.ws_client.subscribe_scrips.call_args.args[1] == (
            reg.get_subscription_type_for_numeric(1)
        )
        adapter.unsubscribe("EQ", "NSE", 1)
    adapter.ws_client.unsubscribe.assert_called_once()
    assert adapter.token_info == {}


# --- races and lifecycle (cubic review of PR #2396) -------------------------


def _live_ws():
    """A client that is running and connected, with the transport mocked."""
    ws = _ws()
    ws.lock = threading.Lock()
    ws.desired = {}
    ws.subscribed = {}
    ws.pending_subscriptions = ws_mod.deque()
    ws.running = True
    ws.connected = True
    ws._stop_event = threading.Event()
    ws.SUBSCRIPTION_DELAY = 0
    ws.ws = MagicMock()
    return ws


def _send_with_competitor(ws, competitor):
    """Make the transport run `competitor` on its own thread at the first
    subscribe frame, then record the frame. Returns (frames, competing thread
    holder). The competitor gets 0.3s to finish before the frame is recorded;
    if the code holds the lock across the send it is still blocked, which is
    the point."""
    frames = []
    started = []

    def send(payload):
        frame = json.loads(payload)
        if "subscribe" in frame and not started:
            thread = threading.Thread(target=competitor, daemon=True)
            started.append(thread)
            thread.start()
            thread.join(0.3)
        frames.append(frame)

    ws.ws.send.side_effect = send
    return frames, started


def _last_frame_for(frames, scrip_id):
    last = None
    for frame in frames:
        for key in ("subscribe", "unSubscribe"):
            if any(entry["scripId"] == scrip_id for entry in frame.get(key, [])):
                last = key
    return last


def test_unsubscribe_at_the_subscribe_send_is_not_undone():
    ws = _live_ws()
    ws.desired["NSE_2885"] = "ALL"
    frames, started = _send_with_competitor(ws, lambda: ws.unsubscribe(["NSE_2885"]))

    ws._send_subscribe(["NSE_2885"], "ALL")
    started[0].join(2)

    assert not started[0].is_alive()
    assert _last_frame_for(frames, "NSE_2885") == "unSubscribe"
    assert "NSE_2885" not in ws.subscribed
    assert "NSE_2885" not in ws.desired


def test_unsubscribe_at_the_replay_send_is_not_undone():
    ws = _live_ws()
    ws.desired["NSE_2885"] = "ALL"
    frames, started = _send_with_competitor(ws, lambda: ws.unsubscribe(["NSE_2885"]))

    ws._resubscribe_all()
    started[0].join(2)

    assert not started[0].is_alive()
    assert _last_frame_for(frames, "NSE_2885") == "unSubscribe"
    assert "NSE_2885" not in ws.subscribed


def test_mode_change_at_the_instrument_limit_is_accepted():
    ws = _live_ws()
    ws._subscription_thread = MagicMock()
    ws._subscription_thread.is_alive.return_value = True
    held = [f"NSE_{n}" for n in range(1, ws.MAX_INSTRUMENTS_PER_CONNECTION + 1)]
    for scrip_id in held:
        ws.desired[scrip_id] = "ALL"
        ws.subscribed[scrip_id] = "ALL"

    # A held scrip at another type adds no instrument.
    assert ws.subscribe_scrips([held[0]], "LTP") is not False
    assert ws.desired[held[0]] == "LTP"
    assert (held[0], "LTP") in ws.pending_subscriptions
    # A new scrip is still refused.
    assert ws.subscribe_scrips(["NSE_999999"], "ALL") is False
    assert "NSE_999999" not in ws.desired


def test_refused_subscription_is_reported_and_rolled_back():
    adapter = _adapter()
    adapter.ws_client.subscribe_scrips.return_value = False
    with patch.object(adapter, "_resolve_token", return_value=2885):
        result = adapter.subscribe("EQ", "NSE", 2)
    assert result["status"] == "error"
    assert adapter.token_info == {}


class _StageAtWrite(dict):
    """last_snapshot whose first write runs `competitor` on its own thread
    first, giving it 0.3s, then performs the write."""

    def __init__(self, competitor):
        super().__init__()
        self.competitor = competitor
        self.thread = None

    def __setitem__(self, key, value):
        if self.thread is None:
            self.thread = threading.Thread(target=self.competitor, daemon=True)
            self.thread.start()
            self.thread.join(0.3)
        super().__setitem__(key, value)


def test_unsubscribe_at_the_snapshot_write_leaves_no_stale_baseline():
    ws = _ws()
    adapter = _adapter()
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("NIFTYFUT", "NFO", 2)
        staged = _StageAtWrite(lambda: adapter.unsubscribe("NIFTYFUT", "NFO", 2))
        adapter.last_snapshot = staged

        adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_FO_ALL, **FULL))])
        staged.thread.join(2)
        assert not staged.thread.is_alive()

        # Subscribed again: an OI packet before the first full quote must not
        # publish the price from the previous subscription.
        adapter.subscribe("NIFTYFUT", "NFO", 2)
        adapter.publish_market_data.reset_mock()
        adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_FO_OI, oi=777))])

    adapter.publish_market_data.assert_not_called()


def test_reconnect_drops_snapshots_before_partial_packets():
    ws = _ws()
    adapter = _adapter()
    with patch.object(adapter, "_resolve_token", return_value=2885):
        adapter.subscribe("NIFTYFUT", "NFO", 2)
    adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_FO_ALL, **FULL))])

    # The client's own reconnect: close, then open again.
    adapter._on_ws_disconnect()
    adapter._on_ws_connect()
    adapter.publish_market_data.reset_mock()
    adapter._on_ticks([ws._parse_packet(_packet(pb.NSE_FO_OI, oi=777))])

    adapter.publish_market_data.assert_not_called()


# --- PR 2397 review follow-ups -------------------------------------------------


def test_unsubscribe_during_the_handshake_is_not_replayed_on_open():
    """No socket yet: the unsubscribe must still retract `desired`, or the
    replay on open subscribes the instrument again."""
    ws = _live_ws()
    ws.ws = None
    ws.connected = False
    ws.desired["NSE_2885"] = "ALL"
    ws.pending_subscriptions.append(("NSE_2885", "ALL"))

    ws.unsubscribe(["NSE_2885"])
    assert "NSE_2885" not in ws.desired
    assert list(ws.pending_subscriptions) == []

    ws.ws = MagicMock()
    ws.connected = True
    ws._resubscribe_all()
    ws.ws.send.assert_not_called()


def test_reconnect_replay_does_not_leave_its_frames_queued():
    ws = _live_ws()
    ws.desired = {"NSE_2885": "ALL", "NSE_1594": "LTP"}
    ws.pending_subscriptions.extend([("NSE_2885", "ALL"), ("NSE_1594", "LTP")])

    ws._resubscribe_all()

    assert list(ws.pending_subscriptions) == [], "the drain would send them a second time"
    sent = sorted(
        (entry["scripId"], entry["type"])
        for call in ws.ws.send.call_args_list
        for entry in json.loads(call.args[0]).get("subscribe", [])
    )
    assert sent == [("NSE_1594", "LTP"), ("NSE_2885", "ALL")], "each at its wanted mode"


def test_a_frame_queued_for_a_scrip_not_in_the_replay_stays_queued():
    ws = _live_ws()
    ws.desired = {"NSE_2885": "ALL"}
    # Queued at a type the replay does not cover (a mode change in flight)
    ws.pending_subscriptions.append(("NSE_2885", "LTP"))
    ws._resubscribe_all()
    assert list(ws.pending_subscriptions) == [("NSE_2885", "LTP")]


def test_a_failed_replay_send_is_queued_again(monkeypatch):
    """The replay took the frame off the queue; if its send raises, the frame
    must go back, or nothing retries it before the next reconnect."""
    ws = _live_ws()
    ws._subscription_thread = None
    ws.desired = {"NSE_2885": "ALL"}
    ws.pending_subscriptions.append(("NSE_2885", "ALL"))
    ws.ws.send.side_effect = OSError("socket closed")
    started = []
    monkeypatch.setattr(ws, "_ensure_drain_thread", lambda: started.append(True))

    ws._resubscribe_all()

    assert list(ws.pending_subscriptions) == [("NSE_2885", "ALL")]
    assert started, "the drain must run to retry it"
    assert "NSE_2885" not in ws.subscribed
