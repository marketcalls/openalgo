import math
import pandas as pd
import pytest
from ai.chart_data_builder import build_chart_overlays


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n=10, columns=None, start_ts=1700000000, step=60):
    """Create a simple DataFrame with integer-timestamp index and optional indicator columns."""
    timestamps = [start_ts + i * step for i in range(n)]
    data = {
        "open": [100.0 + i for i in range(n)],
        "high": [102.0 + i for i in range(n)],
        "low": [99.0 + i for i in range(n)],
        "close": [101.0 + i for i in range(n)],
        "volume": [1000] * n,
    }
    if columns:
        for col, values in columns.items():
            data[col] = values
    df = pd.DataFrame(data, index=timestamps)
    return df


# ---------------------------------------------------------------------------
# Tests: empty DataFrame
# ---------------------------------------------------------------------------

def test_empty_dataframe_returns_empty_overlays():
    df = pd.DataFrame()
    result = build_chart_overlays(df, indicators={})
    assert result == {"lines": [], "bands": [], "markers": [], "levels": []}


# ---------------------------------------------------------------------------
# Tests: line generation (EMA, SMA, Supertrend)
# ---------------------------------------------------------------------------

def test_line_generation_ema_9():
    values = [100.5 + i * 0.1 for i in range(5)]
    df = _make_df(n=5, columns={"ema_9": values})
    result = build_chart_overlays(df, indicators={"ema_9": {}})

    assert len(result["lines"]) == 1
    line = result["lines"][0]
    assert line["id"] == "ema_9"
    assert line["label"] == "EMA 9"
    assert line["color"] == "#f59e0b"
    assert len(line["data"]) == 5
    assert line["data"][0]["value"] == round(values[0], 2)


def test_line_generation_multiple_columns():
    n = 5
    df = _make_df(n=n, columns={
        "ema_9": [100.0] * n,
        "ema_21": [200.0] * n,
        "sma_50": [300.0] * n,
        "supertrend": [400.0] * n,
    })
    result = build_chart_overlays(df, indicators={})

    assert len(result["lines"]) == 4
    ids = [line["id"] for line in result["lines"]]
    assert ids == ["ema_9", "ema_21", "sma_50", "supertrend"]


def test_line_time_is_integer_timestamp():
    df = _make_df(n=3, columns={"ema_9": [100.0, 101.0, 102.0]}, start_ts=1700000000, step=60)
    result = build_chart_overlays(df, indicators={})
    times = [pt["time"] for pt in result["lines"][0]["data"]]
    assert times == [1700000000, 1700000060, 1700000120]


# ---------------------------------------------------------------------------
# Tests: NaN exclusion
# ---------------------------------------------------------------------------

def test_nan_values_excluded_from_lines():
    df = _make_df(n=5, columns={"ema_9": [float("nan"), float("nan"), 100.0, 101.0, 102.0]})
    result = build_chart_overlays(df, indicators={})

    assert len(result["lines"]) == 1
    assert len(result["lines"][0]["data"]) == 3  # only non-NaN values


def test_all_nan_column_produces_no_line():
    df = _make_df(n=3, columns={"ema_9": [float("nan")] * 3})
    result = build_chart_overlays(df, indicators={})
    assert len(result["lines"]) == 0


# ---------------------------------------------------------------------------
# Tests: Bollinger bands
# ---------------------------------------------------------------------------

def test_bollinger_band_generation():
    n = 5
    df = _make_df(n=n, columns={
        "bb_high": [110.0 + i for i in range(n)],
        "bb_low": [90.0 + i for i in range(n)],
    })
    result = build_chart_overlays(df, indicators={})

    assert len(result["bands"]) == 1
    band = result["bands"][0]
    assert band["id"] == "bb"
    assert band["label"] == "Bollinger Bands"
    assert len(band["data"]) == n
    assert band["data"][0]["upper"] == 110.0
    assert band["data"][0]["lower"] == 90.0


def test_bollinger_nan_excluded():
    df = _make_df(n=4, columns={
        "bb_high": [float("nan"), 110.0, 111.0, float("nan")],
        "bb_low": [float("nan"), 90.0, 91.0, float("nan")],
    })
    result = build_chart_overlays(df, indicators={})

    assert len(result["bands"]) == 1
    assert len(result["bands"][0]["data"]) == 2


def test_bollinger_missing_one_column():
    df = _make_df(n=3, columns={"bb_high": [110.0, 111.0, 112.0]})
    result = build_chart_overlays(df, indicators={})
    assert len(result["bands"]) == 0  # need both bb_high and bb_low


# ---------------------------------------------------------------------------
# Tests: CPR levels
# ---------------------------------------------------------------------------

def test_cpr_levels_generation():
    cpr = {
        "r3": 1050.0, "r2": 1040.0, "r1": 1030.0,
        "tc": 1020.0, "pivot": 1010.0, "bc": 1000.0,
        "s1": 990.0, "s2": 980.0, "s3": 970.0,
    }
    df = _make_df(n=3)
    result = build_chart_overlays(df, indicators={}, cpr=cpr)

    assert len(result["levels"]) == 9
    labels = [lev["label"] for lev in result["levels"]]
    assert "R3" in labels
    assert "PIVOT" in labels
    assert "S3" in labels
    # Check price rounding
    pivot_level = next(lev for lev in result["levels"] if lev["label"] == "PIVOT")
    assert pivot_level["price"] == 1010.0


def test_cpr_skips_zero_and_missing_keys():
    cpr = {"pivot": 1010.0, "r1": 0, "s1": None}
    df = _make_df(n=3)
    result = build_chart_overlays(df, indicators={}, cpr=cpr)

    labels = [lev["label"] for lev in result["levels"]]
    assert "PIVOT" in labels
    assert "R1" not in labels  # val == 0
    assert "S1" not in labels  # val is None


# ---------------------------------------------------------------------------
# Tests: trade setup levels
# ---------------------------------------------------------------------------

def test_trade_setup_levels():
    setup = {"entry": 500.0, "stop_loss": 490.0, "target_1": 510.0, "target_2": 520.0}
    df = _make_df(n=3)
    result = build_chart_overlays(df, indicators={}, trade_setup=setup)

    assert len(result["levels"]) == 4
    labels = [lev["label"] for lev in result["levels"]]
    assert labels == ["Entry", "SL", "T1", "T2"]


def test_trade_setup_partial():
    setup = {"entry": 500.0, "stop_loss": 490.0}
    df = _make_df(n=3)
    result = build_chart_overlays(df, indicators={}, trade_setup=setup)

    labels = [lev["label"] for lev in result["levels"]]
    assert "Entry" in labels
    assert "SL" in labels
    assert "T1" not in labels
    assert "T2" not in labels


# ---------------------------------------------------------------------------
# Tests: None for cpr / trade_setup
# ---------------------------------------------------------------------------

def test_no_cpr_or_trade_setup():
    df = _make_df(n=3, columns={"ema_9": [100.0, 101.0, 102.0]})
    result = build_chart_overlays(df, indicators={}, cpr=None, trade_setup=None)

    assert len(result["levels"]) == 0
    assert len(result["lines"]) == 1  # ema_9 still present


# ---------------------------------------------------------------------------
# Tests: tail(200) limiting
# ---------------------------------------------------------------------------

def test_tail_200_limits_data():
    n = 300
    df = _make_df(n=n, columns={"ema_9": [100.0 + i for i in range(n)]})
    result = build_chart_overlays(df, indicators={})

    assert len(result["lines"]) == 1
    assert len(result["lines"][0]["data"]) == 200

    # The first data point should correspond to row 100 (tail 200 of 300)
    expected_first_ts = 1700000000 + 100 * 60
    assert result["lines"][0]["data"][0]["time"] == expected_first_ts


def test_fewer_than_200_rows_uses_all():
    n = 50
    df = _make_df(n=n, columns={"ema_9": [100.0] * n})
    result = build_chart_overlays(df, indicators={})

    assert len(result["lines"][0]["data"]) == 50
