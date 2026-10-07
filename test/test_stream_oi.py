"""Broker feed adapters forward a contract's open interest as `oi`.

The OI Profile overlays this on its polled numbers, so the contract is the same
for every broker: `oi` is the contract's own OI (never the underlying's total),
an integer, and absent rather than 0 when the packet does not carry it. Each
case below is built from the field names in that broker's own documentation.
"""

import atexit
import logging
import os
import struct
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_stream_oi.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

# websocket_proxy must load before broker.*.streaming (the packages import each other).
import websocket_proxy  # noqa: E402, F401
from broker.aliceblue.streaming.aliceblue_adapter import AliceblueWebSocketAdapter  # noqa: E402
from broker.aliceblue.streaming.aliceblue_mapping import AliceBlueMessageMapper  # noqa: E402
from broker.flattrade.streaming import flattrade_adapter  # noqa: E402
from broker.groww.streaming.groww_adapter import _GrowwMarketCache  # noqa: E402
from broker.groww.streaming.groww_protobuf import MiniProtobufParser  # noqa: E402
from broker.samco.streaming.samco_adapter import SamcoWebSocketAdapter  # noqa: E402
from broker.samco.streaming.samcoWebSocket import SamcoWebSocket  # noqa: E402
from broker.shoonya.streaming import shoonya_adapter  # noqa: E402
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter as Adapter  # noqa: E402
from broker.zebu.streaming import zebu_adapter  # noqa: E402


def _adapter():
    return Adapter.__new__(Adapter)


def _feed(**extra):
    ff = {"ltpc": {"ltp": 101.5, "cp": 100.0}, "marketOHLC": {"ohlc": []}}
    ff.update(extra)
    return {"fullFeed": {"marketFF": ff}}


def test_upstox_quote_publishes_oi_when_present():
    out = _adapter()._extract_quote_data(_feed(oi=1234567.0), {}, 1)
    assert out["oi"] == 1234567


def test_upstox_quote_omits_oi_when_absent():
    # proto3 drops a zero scalar; absent must stay absent, never become 0
    assert "oi" not in _adapter()._extract_quote_data(_feed(), {}, 1)


def test_upstox_depth_publishes_oi():
    out = _adapter()._extract_depth_data(_feed(oi=500.0), 1)
    assert out["oi"] == 500


# --- Noren family (Flattrade, Zebu, Shoonya) ---------------------------------
# Noren touchline: `oi` is the contract's OI, `toi` the underlying's total.


@pytest.mark.parametrize("mod", [flattrade_adapter, zebu_adapter, shoonya_adapter])
def test_noren_uses_contract_oi_not_underlying_total(mod):
    tick = {"lp": "101.5", "oi": "4200", "toi": "99999999", "poi": "4000"}
    for normalizer in (mod.QuoteNormalizer, mod.DepthNormalizer):
        out = normalizer.normalize(tick, "tk")
        assert out["oi"] == 4200
        assert "open_interest" not in out


@pytest.mark.parametrize("mod", [flattrade_adapter, zebu_adapter, shoonya_adapter])
def test_noren_omits_oi_when_absent(mod):
    # Equity and index scrips carry no oi; a partial tf frame may omit it.
    assert "oi" not in mod.QuoteNormalizer.normalize({"lp": "101.5"}, "tf")


# --- Samco: only the `quote` stream carries `oI` ------------------------------


def test_samco_forwards_open_interest():
    msg = {"last_traded_price": 10.0, "open_interest": 750}
    adapter = SamcoWebSocketAdapter.__new__(SamcoWebSocketAdapter)
    assert adapter._normalize_market_data(msg, 2)["oi"] == 750
    assert adapter._normalize_market_data(msg, 3)["oi"] == 750


def test_samco_never_sent_is_omitted_and_a_real_zero_is_forwarded():
    adapter = SamcoWebSocketAdapter.__new__(SamcoWebSocketAdapter)
    # quote2 frames arrive as mode 3. Before any quote frame has carried oI,
    # the client reports None and the key stays absent.
    assert "oi" not in adapter._normalize_market_data({"open_interest": None}, 3)
    # A quote frame that carried oI = 0 is a real zero, not "not sent".
    assert adapter._normalize_market_data({"open_interest": 0}, 2)["oi"] == 0


def _samco_client():
    client = SamcoWebSocket.__new__(SamcoWebSocket)
    client._tick_state = {}
    client._tick_state_lock = threading.Lock()
    return client


def test_samco_quote2_frame_carries_the_last_quote_oi():
    client = _samco_client()
    before = client._normalize_market_data({"symbol": "X", "bidValues": []}, "quote2")
    assert before["open_interest"] is None, "no quote frame has carried oI yet"
    client._normalize_market_data({"symbol": "X", "ltp": "10", "oI": "750"}, "quote")
    after = client._normalize_market_data({"symbol": "X", "bidValues": []}, "quote2")
    assert after["subscription_mode"] == 3
    assert after["open_interest"] == 750


# --- Groww: StocksLivePriceProto.openInterest is field 14 (double) ----------


def _groww_live_price(ltp: float, oi: float) -> bytes:
    def fixed64(field, value):
        return bytes([(field << 3) | 1]) + struct.pack("<d", value)

    inner = fixed64(13, ltp) + fixed64(14, oi)
    return bytes([(4 << 3) | 2, len(inner)]) + inner


def test_groww_parser_reads_open_interest():
    parsed = MiniProtobufParser().parse_market_data(_groww_live_price(101.5, 61875.0))
    assert parsed["ltp_data"]["open_interest"] == 61875.0
    assert parsed["ltp_data"]["ltp"] == 101.5


# --- Aliceblue: contract `oi` is on depth frames only -----------------------


def test_aliceblue_depth_frame_carries_oi():
    out = AliceBlueMessageMapper.parse_depth_data({"t": "dk", "e": "NFO", "tk": "1", "oi": "1500"})
    assert out["oi"] == 1500


def test_aliceblue_depth_frame_without_oi():
    assert "oi" not in AliceBlueMessageMapper.parse_depth_data({"t": "df", "e": "NFO", "tk": "1"})


def test_aliceblue_depth_frame_forwards_a_real_zero():
    out = AliceBlueMessageMapper.parse_depth_data({"t": "df", "e": "NFO", "tk": "1", "oi": "0"})
    assert out["oi"] == 0


def test_aliceblue_snapshot_keeps_oi_for_publishing():
    # The adapter publishes the merged snapshot, not the parsed frame, so the
    # snapshot has to carry oi through, and keep it across a frame without it.
    adapter = AliceblueWebSocketAdapter.__new__(AliceblueWebSocketAdapter)
    adapter.market_snapshots = {}
    adapter.logger = logging.getLogger("test_aliceblue")
    first = adapter._update_market_snapshot("NFO:1", {"ltp": 10.0, "oi": 1500, "bids": []})
    assert first["oi"] == 1500
    second = adapter._update_market_snapshot("NFO:1", {"ltp": 10.5, "bids": []})
    assert second["oi"] == 1500


# --- Groww: Depth publishes send the merged cache entry ----------------------


def test_groww_depth_cache_keeps_oi():
    cache = _GrowwMarketCache()
    cache.update_from_ltp("NSE", "FNO", "1", {"ltp": 101.5, "oi": 61875})
    merged = cache.update_from_depth("NSE", "FNO", "1", {"depth": {"buy": [], "sell": []}})
    assert merged["oi"] == 61875


@pytest.mark.parametrize("mod", [flattrade_adapter, zebu_adapter, shoonya_adapter])
def test_noren_forwards_a_real_zero(mod):
    assert mod.QuoteNormalizer.normalize({"lp": "1", "oi": "0"}, "tf")["oi"] == 0


@pytest.mark.parametrize("mod", [flattrade_adapter, zebu_adapter, shoonya_adapter])
@pytest.mark.parametrize("junk", ["  ", "abc", "N/A"])
def test_noren_malformed_oi_is_not_sent_as_zero(mod, junk):
    assert "oi" not in mod.QuoteNormalizer.normalize({"lp": "1", "oi": junk}, "tf")
