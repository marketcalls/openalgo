"""Sector rotation map: the calculation, weekly resampling and the service.

The parity test pins the calculation to the standalone sector-rotation-map
project, whose ``compute_single_rrg`` is copied verbatim below as the
reference. If the two ever disagree, the map in OpenAlgo has drifted from the
one traders already know.
"""

import zlib

import numpy as np
import pandas as pd
import pytest

import services.sector_rotation_service as srs
from portfolio.data import MissingHistory, PriceMatrix


def _reference_compute_single_rrg(sector_prices, benchmark_prices, tail_length=8):
    """compute_single_rrg from sector-rotation-map/api_server.py, unchanged."""
    raw_rs = (sector_prices / benchmark_prices) * 100
    rs_smoothed = raw_rs.ewm(span=10, adjust=False).mean()

    rolling_mean = rs_smoothed.rolling(window=52, min_periods=20).mean()
    rolling_std = rs_smoothed.rolling(window=52, min_periods=20).std()
    rolling_std = rolling_std.replace(0, np.nan)
    rs_ratio = 100 + ((rs_smoothed - rolling_mean) / rolling_std) * 2

    rs_momentum_raw = rs_ratio - rs_ratio.shift(1)
    mom_smoothed = rs_momentum_raw.ewm(span=5, adjust=False).mean()
    mom_mean = mom_smoothed.rolling(window=52, min_periods=20).mean()
    mom_std = mom_smoothed.rolling(window=52, min_periods=20).std()
    mom_std = mom_std.replace(0, np.nan)
    rs_momentum = 100 + ((mom_smoothed - mom_mean) / mom_std) * 2

    valid = rs_ratio.notna() & rs_momentum.notna()
    rs_r = rs_ratio[valid]
    rs_m = rs_momentum[valid]
    n = min(tail_length, len(rs_r))
    return [
        (
            rs_r.index[i].strftime("%Y-%m-%d"),
            round(float(rs_r.iloc[i]), 2),
            round(float(rs_m.iloc[i]), 2),
        )
        for i in range(-n, 0)
    ]


def _walk(seed: int, n: int = 400, start: float = 100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=index)


def test_matches_reference_calculation():
    sector, bench = _walk(1), _walk(2)
    expected = _reference_compute_single_rrg(sector, bench, tail_length=30)
    summary = srs.summarise(srs.rrg_series(sector, bench), tail=30)
    got = [(p["date"], p["rs_ratio"], p["rs_momentum"]) for p in summary["tail"]]
    assert got == expected


def test_matches_reference_on_weekly_bars():
    sector, bench = _walk(3, n=800), _walk(4, n=800)
    weekly_sector, weekly_bench = srs.to_weekly(sector), srs.to_weekly(bench)
    expected = _reference_compute_single_rrg(weekly_sector, weekly_bench, tail_length=12)
    summary = srs.summarise(srs.rrg_series(weekly_sector, weekly_bench), tail=12)
    got = [(p["date"], p["rs_ratio"], p["rs_momentum"]) for p in summary["tail"]]
    assert got == expected


@pytest.mark.parametrize(
    ("rs_ratio", "rs_momentum", "expected"),
    [
        (101, 101, "leading"),
        (101, 99, "weakening"),
        (99, 99, "lagging"),
        (99, 101, "improving"),
        (100, 100, "leading"),
    ],
)
def test_quadrant(rs_ratio, rs_momentum, expected):
    assert srs.quadrant(rs_ratio, rs_momentum) == expected


def test_bars_in_quadrant_counts_the_current_run_only():
    points = pd.DataFrame(
        {
            "rs_ratio": [101, 101, 99, 99, 99, 98],
            "rs_momentum": [101, 101, 101, 99, 98, 97],
        }
    )
    assert srs.bars_in_quadrant(points) == 3


def test_weekly_bar_is_dated_by_its_last_session():
    # Mon 2026-10-26 to Wed 2026-10-28: a week still in progress.
    index = pd.DatetimeIndex(["2026-10-19", "2026-10-23", "2026-10-26", "2026-10-28"])
    weekly = srs.to_weekly(pd.Series([1.0, 2.0, 3.0, 4.0], index=index))
    assert list(weekly.index.strftime("%Y-%m-%d")) == ["2026-10-23", "2026-10-28"]
    assert list(weekly) == [2.0, 4.0]


def test_rrg_uses_only_sessions_both_traded():
    sector = _walk(5)
    bench = _walk(6).drop(_walk(6).index[100:110])
    points = srs.rrg_series(sector, bench)
    assert not set(points.index) - set(bench.index)


def _fake_loader(missing: set[str], short: set[str] | None = None):
    short = short or set()

    def load(symbols, exchanges, start, end, *, source, allowed_exchanges, **creds):
        symbol = symbols[0]
        if symbol in missing:
            raise MissingHistory(f"{symbol}: no history")
        n = 10 if symbol in short else 300
        # crc32, not hash(): str hashing is randomised per process, and two
        # symbols sharing a seed would give a flat RS that cannot be placed.
        series = _walk(zlib.crc32(symbol.encode()), n=n)
        return PriceMatrix(
            closes=series.to_frame(symbol),
            source=source,
            start=series.index[0].date(),
            end=series.index[-1].date(),
        )

    return load


@pytest.fixture(autouse=True)
def _clear_cache():
    srs._CLOSES_CACHE.clear()
    yield
    srs._CLOSES_CACHE.clear()


def test_one_missing_index_does_not_cost_the_map(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader({"NIFTYINDDEFENCE"}))
    ok, payload, status = srs.compute_sector_rotation("NIFTY", "daily", "db")
    assert ok and status == 200
    placed = {s["symbol"] for s in payload["data"]["instruments"]}
    missing = {u["symbol"] for u in payload["data"]["unavailable"]}
    assert "NIFTYINDDEFENCE" in missing
    assert "NIFTYINDDEFENCE" not in placed
    assert len(placed) == len(srs.SECTORS) - 1


def test_short_history_is_reported_not_plotted(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader(set(), short={"NIFTYMEDIA"}))
    ok, payload, _ = srs.compute_sector_rotation("NIFTY", "daily", "db")
    assert ok
    reasons = {u["symbol"]: u["reason"] for u in payload["data"]["unavailable"]}
    assert "Not enough daily history" in reasons["NIFTYMEDIA"]


def test_sector_equal_to_benchmark_is_left_off(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader(set()))
    ok, payload, _ = srs.compute_sector_rotation("FINNIFTY", "weekly", "db")
    assert ok
    symbols = {s["symbol"] for s in payload["data"]["instruments"]}
    assert "FINNIFTY" not in symbols
    assert payload["data"]["timeframe"] == "weekly"
    reasons = {u["symbol"]: u["reason"] for u in payload["data"]["unavailable"]}
    assert "benchmark itself" in reasons["FINNIFTY"]


def test_weekly_keeps_a_week_one_side_ended_early():
    # The benchmark trades every weekday; the symbol misses every fourth
    # Friday (a holiday on its exchange only). Each such week must still pair.
    bench = _walk(7, n=600)
    fridays = bench.index[bench.index.dayofweek == 4]
    symbol = _walk(8, n=600).drop(fridays[::4])

    weekly_symbol, weekly_bench = srs.paired_bars(symbol, bench, "weekly")
    assert weekly_symbol.index.equals(weekly_bench.index)
    assert len(weekly_bench) == len(srs.to_weekly(bench))


def test_missing_benchmark_names_the_fix(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader({"NIFTY"}))
    ok, payload, status = srs.compute_sector_rotation("NIFTY", "daily", "db")
    assert not ok and status == 422
    assert "Historify" in payload["message"]


def test_rejects_unknown_inputs():
    assert srs.compute_sector_rotation("DOW", "daily", "db")[2] == 400
    assert srs.compute_sector_rotation("NIFTY", "monthly", "db")[2] == 400
    assert srs.compute_sector_rotation("NIFTY", "daily", "csv")[2] == 400


def test_custom_list_places_stocks_and_indices(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader(set()))
    ok, payload, _ = srs.compute_sector_rotation(
        "NIFTY",
        "daily",
        "db",
        instruments=[
            {"symbol": "reliance", "exchange": "nse"},
            {"symbol": "NIFTYIT", "exchange": "NSE_INDEX"},
            {"symbol": "RELIANCE", "exchange": "NSE"},
        ],
    )
    assert ok
    placed = [(i["symbol"], i["label"]) for i in payload["data"]["instruments"]]
    # Duplicates dropped; a known sector keeps its name, a stock its symbol.
    assert placed == [("RELIANCE", "RELIANCE"), ("NIFTYIT", "IT")]


def test_custom_list_refuses_derivatives_and_oversize():
    ok, payload, status = srs.compute_sector_rotation(
        "NIFTY", "daily", "db", instruments=[{"symbol": "NIFTY30OCT26FUT", "exchange": "NFO"}]
    )
    assert not ok and status == 400
    assert "NFO" in payload["message"]

    too_many = [{"symbol": f"S{i}", "exchange": "NSE"} for i in range(srs.MAX_INSTRUMENTS + 1)]
    assert srs.compute_sector_rotation("NIFTY", "daily", "db", instruments=too_many)[2] == 400


def test_closes_are_reused_across_maps(monkeypatch):
    calls: list[str] = []
    loader = _fake_loader(set())

    def counting(symbols, *args, **kwargs):
        calls.append(symbols[0])
        return loader(symbols, *args, **kwargs)

    monkeypatch.setattr(srs, "load_prices", counting)
    srs.compute_sector_rotation("NIFTY", "daily", "api")
    first = len(calls)
    srs.compute_sector_rotation(
        "NIFTY", "daily", "api", instruments=[{"symbol": "NIFTYIT", "exchange": "NSE_INDEX"}]
    )
    assert len(calls) == first


def test_trail_is_capped_at_max_tail(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader(set()))
    _, payload, _ = srs.compute_sector_rotation("NIFTY", "daily", "db")
    for sector in payload["data"]["instruments"]:
        assert len(sector["tail"]) == srs.MAX_TAIL
        assert sector["tail"][-1]["rs_ratio"] == sector["rs_ratio"]


def test_loader_cache_flag_reads_historify_fresh(monkeypatch):
    # The sector map keeps its own expiring cache, so it asks the loader not to
    # keep a matrix that would hide a Historify download for the rest of the day.
    import portfolio.data as pdata

    reads: list[int] = []

    def fake_read(symbols, exchanges, start, end, interval):
        reads.append(1)
        return {symbols[0]: _walk(9, n=50)}

    monkeypatch.setattr(pdata, "_closes_from_duckdb", fake_read)
    pdata.clear_price_cache()
    args = (["NIFTYIT"], ["NSE_INDEX"], "2024-01-01", "2024-06-01")
    kw = {"source": "db", "allowed_exchanges": srs.EXCHANGES, "cache": False}
    pdata.load_prices(*args, **kw)
    pdata.load_prices(*args, **kw)
    assert len(reads) == 2
    pdata.clear_price_cache()
