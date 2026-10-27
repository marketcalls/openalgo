"""Sector rotation map: the calculation, weekly resampling and the service.

The calculation is checked against a deliberately plain loop written here,
independently of the vectorised code, and against values worked by hand.
"""

import zlib

import numpy as np
import pandas as pd
import pytest

import services.sector_rotation_service as srs
from portfolio.data import MissingHistory, PriceMatrix


def _plain_rotation(sector, benchmark, fast, slow, momentum):
    """The same positions, one bar at a time, with no pandas rolling machinery."""
    rs = [100 * s / b for s, b in zip(sector, benchmark, strict=True)]

    def weighted(values, length, end):
        window = values[end - length + 1 : end + 1]
        return sum(w * v for w, v in enumerate(window, start=1)) / sum(range(1, length + 1))

    ratio = [None] * len(rs)
    for i in range(slow - 1, len(rs)):
        ratio[i] = 100 * weighted(rs, fast, i) / weighted(rs, slow, i)
    out = []
    for i in range(len(rs)):
        if ratio[i] is not None and i - momentum >= 0 and ratio[i - momentum] is not None:
            out.append((round(ratio[i], 2), round(100 * ratio[i] / ratio[i - momentum], 2)))
    return out


def _walk(seed: int, n: int = 400, start: float = 100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=index)


def test_wma_weights_the_newest_bar_most():
    series = pd.Series([1.0, 2.0, 3.0, 9.0])
    out = srs.wma(series, 3)
    assert out.isna().tolist() == [True, True, False, False]
    assert out.iloc[2] == pytest.approx((1 * 1 + 2 * 2 + 3 * 3) / 6)
    assert out.iloc[3] == pytest.approx((1 * 2 + 2 * 3 + 3 * 9) / 6)


@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
def test_matches_a_plain_loop(timeframe):
    params = srs.PARAMS[timeframe]
    sector, bench = _walk(1), _walk(2)
    expected = _plain_rotation(
        sector.tolist(), bench.tolist(), params.fast, params.slow, params.momentum
    )
    points = srs.rotation_series(sector, bench, timeframe)
    got = [
        (round(r, 2), round(m, 2))
        for r, m in zip(points["rs_ratio"], points["rs_momentum"], strict=True)
    ]
    assert len(got) > 300
    assert got == expected


def test_lengths_per_timeframe():
    daily, weekly = srs.PARAMS["daily"], srs.PARAMS["weekly"]
    assert (daily.fast, daily.slow, daily.momentum) == (14, 36, 8)
    assert (weekly.fast, weekly.slow, weekly.momentum) == (5, 15, 5)


@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
def test_first_point_needs_exactly_min_bars(timeframe):
    need = srs.PARAMS[timeframe].min_bars
    sector, bench = _walk(3, n=need), _walk(4, n=need)
    assert len(srs.rotation_series(sector.iloc[:-1], bench.iloc[:-1], timeframe)) == 0
    assert len(srs.rotation_series(sector, bench, timeframe)) == 1


def test_a_symbol_moving_with_the_benchmark_sits_at_the_centre():
    bench = _walk(5)
    points = srs.rotation_series(bench * 3, bench)
    assert points["rs_ratio"].round(9).eq(100).all()
    assert points["rs_momentum"].round(9).eq(100).all()


def test_steady_outperformance_reads_strong():
    bench = _walk(6)
    drift = pd.Series(np.exp(np.linspace(0, 0.3, len(bench))), index=bench.index)
    last = srs.rotation_series(bench * drift, bench).iloc[-1]
    assert last["rs_ratio"] > 100


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


def test_uses_only_sessions_both_traded():
    sector = _walk(5)
    bench = _walk(6).drop(_walk(6).index[100:110])
    points = srs.rotation_series(sector, bench)
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
    monkeypatch.setattr(srs, "load_prices", _fake_loader({"NIFTYMEDIA"}))
    ok, payload, status = srs.compute_sector_rotation("NIFTY", "daily", "db")
    assert ok and status == 200
    placed = {s["symbol"] for s in payload["data"]["instruments"]}
    missing = {u["symbol"] for u in payload["data"]["unavailable"]}
    assert "NIFTYMEDIA" in missing
    assert "NIFTYMEDIA" not in placed
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


def test_default_map_leaves_off_indices_brokers_rarely_publish():
    defaults = {s.symbol for s in srs.SECTORS}
    optional = {s.symbol for s in srs.OPTIONAL_SECTORS}
    assert optional == {"NIFTYCONSRDURBL", "NIFTYHEALTHCARE", "NIFTYINDDEFENCE", "NIFTYOILANDGAS"}
    assert not defaults & optional


def test_an_optional_sector_added_by_hand_keeps_its_name(monkeypatch):
    monkeypatch.setattr(srs, "load_prices", _fake_loader(set()))
    ok, payload, _ = srs.compute_sector_rotation(
        "NIFTY", "daily", "db", instruments=[{"symbol": "NIFTYHEALTHCARE", "exchange": "NSE_INDEX"}]
    )
    assert ok
    assert payload["data"]["instruments"][0]["label"] == "Healthcare"
