"""Broker feed adapters forward a contract's open interest as `oi`.

The OI Profile overlays this on its polled numbers, so the contract is the same
for every broker: `oi` is the contract's own OI (never the underlying's total),
an integer, and absent rather than 0 when the packet does not carry it. Each
case below is built from the field names in that broker's own documentation.
"""

import atexit
import os
import struct
import sys
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
from broker.aliceblue.streaming.aliceblue_mapping import AliceBlueMessageMapper  # noqa: E402
from broker.flattrade.streaming import flattrade_adapter  # noqa: E402
from broker.groww.streaming.groww_protobuf import MiniProtobufParser  # noqa: E402
from broker.samco.streaming.samco_adapter import SamcoWebSocketAdapter  # noqa: E402
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


def test_samco_quote2_frame_without_oi_is_omitted():
    adapter = SamcoWebSocketAdapter.__new__(SamcoWebSocketAdapter)
    assert "oi" not in adapter._normalize_market_data({"open_interest": 0}, 2)


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
