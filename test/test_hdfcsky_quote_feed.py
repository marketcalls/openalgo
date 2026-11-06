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
