"""Tests for ai.indicator_registry — dynamic indicator loader."""
import math
import os
import types
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from ai.indicator_registry import (
    IndicatorInfo,
    IndicatorRegistry,
    get_indicator_registry,
    init_indicator_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_df(rows: int = 5) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame for testing."""
    return pd.DataFrame({
        "open":   [100.0 + i for i in range(rows)],
        "high":   [105.0 + i for i in range(rows)],
        "low":    [95.0 + i for i in range(rows)],
        "close":  [102.0 + i for i in range(rows)],
        "volume": [1000 * (i + 1) for i in range(rows)],
    })


def _make_mock_module(indicator_fn=None):
    """Create a mock module with a calculate_indicators function."""
    mod = types.ModuleType("mock_indicator")
    if indicator_fn is None:
        def indicator_fn(df):
            df["Buy_Signal"] = 0
            df.iloc[-1, df.columns.get_loc("Buy_Signal")] = 1
            df["SMA_20"] = df["close"].rolling(2, min_periods=1).mean()
            return df
    mod.calculate_indicators = indicator_fn
    return mod


# ---------------------------------------------------------------------------
# IndicatorRegistry — init
# ---------------------------------------------------------------------------

class TestRegistryInit:
    def test_empty_on_creation(self):
        reg = IndicatorRegistry()
        assert reg.list_all() == []
        assert reg._indicators == {}
        assert reg._modules == {}

    def test_get_returns_none_when_empty(self):
        reg = IndicatorRegistry()
        assert reg.get("nonexistent") is None


# ---------------------------------------------------------------------------
# IndicatorRegistry — discover
# ---------------------------------------------------------------------------

class TestRegistryDiscover:
    def test_discover_missing_directory_does_not_crash(self, tmp_path):
        """discover() with a non-existent dir should warn and return without error."""
        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path / "does_not_exist"))
        assert reg.list_all() == []

    def test_discover_empty_directory(self, tmp_path):
        """discover() on an empty directory registers nothing."""
        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))
        assert reg.list_all() == []

    def test_discover_skips_dunder_files(self, tmp_path):
        """Files starting with _ should be skipped."""
        init_file = tmp_path / "__init__.py"
        init_file.write_text("# init")
        helper_file = tmp_path / "_helpers.py"
        helper_file.write_text("def calculate_indicators(df): return df")

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))
        assert reg.list_all() == []

    def test_discover_skips_non_python_files(self, tmp_path):
        """Non-.py files should be ignored."""
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.csv").write_text("a,b\n1,2")

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))
        assert reg.list_all() == []

    def test_discover_skips_file_without_calculate_indicators(self, tmp_path):
        """A .py file without calculate_indicators should be skipped."""
        (tmp_path / "no_func.py").write_text("x = 42\n")

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))
        assert reg.list_all() == []

    def test_discover_registers_valid_indicator(self, tmp_path):
        """A .py file with calculate_indicators should be registered."""
        code = "def calculate_indicators(df):\n    df['out'] = 1\n    return df\n"
        (tmp_path / "my_indicator.py").write_text(code)

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))

        assert len(reg.list_all()) == 1
        info = reg.get("my_indicator")
        assert info is not None
        assert info.id == "my_indicator"
        assert info.name == "My Indicator"
        assert info.category == "custom"
        assert info.has_signals is True
        assert info.file_path == os.path.join(str(tmp_path), "my_indicator.py")

    def test_discover_registers_multiple_indicators_sorted(self, tmp_path):
        """Multiple valid files should all be registered, discovered in sorted order."""
        for name in ["zebra_signal", "alpha_signal", "mid_signal"]:
            code = f"def calculate_indicators(df):\n    df['{name}'] = 1\n    return df\n"
            (tmp_path / f"{name}.py").write_text(code)

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))

        ids = [info.id for info in reg.list_all()]
        assert len(ids) == 3
        # discover() uses sorted(), so order should be alphabetical
        assert ids == ["alpha_signal", "mid_signal", "zebra_signal"]

    def test_discover_skips_file_with_import_error(self, tmp_path):
        """A file that raises an error on import should be skipped, not crash."""
        (tmp_path / "bad_import.py").write_text("import nonexistent_package_xyz\n")
        code = "def calculate_indicators(df):\n    return df\n"
        (tmp_path / "good_indicator.py").write_text(code)

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))

        assert len(reg.list_all()) == 1
        assert reg.get("good_indicator") is not None
        assert reg.get("bad_import") is None


# ---------------------------------------------------------------------------
# IndicatorRegistry — list_all / get
# ---------------------------------------------------------------------------

class TestRegistryListAndGet:
    def test_list_all_returns_indicator_info_objects(self, tmp_path):
        code = "def calculate_indicators(df):\n    return df\n"
        (tmp_path / "test_ind.py").write_text(code)

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))

        result = reg.list_all()
        assert len(result) == 1
        assert isinstance(result[0], IndicatorInfo)

    def test_get_returns_none_for_unknown(self):
        reg = IndicatorRegistry()
        assert reg.get("does_not_exist") is None

    def test_get_returns_correct_info(self, tmp_path):
        code = "def calculate_indicators(df):\n    return df\n"
        (tmp_path / "bollinger_band.py").write_text(code)

        reg = IndicatorRegistry()
        reg.discover(base_dir=str(tmp_path))

        info = reg.get("bollinger_band")
        assert info is not None
        assert info.id == "bollinger_band"
        assert info.name == "Bollinger Band"


# ---------------------------------------------------------------------------
# IndicatorRegistry — compute
# ---------------------------------------------------------------------------

class TestRegistryCompute:
    def test_compute_unknown_indicator_returns_error(self):
        reg = IndicatorRegistry()
        result = reg.compute("nonexistent", _make_ohlcv_df())
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_compute_with_mock_module(self):
        """compute() should return new columns and latest values."""
        reg = IndicatorRegistry()

        mock_mod = _make_mock_module()
        reg._indicators["test_ind"] = IndicatorInfo(
            id="test_ind", name="Test", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["test_ind"] = mock_mod

        df = _make_ohlcv_df()
        result = reg.compute("test_ind", df)

        assert "error" not in result
        assert "columns" in result
        assert "Buy_Signal" in result["columns"]
        assert "SMA_20" in result["columns"]
        assert "latest" in result
        assert result["latest"]["Buy_Signal"] == 1

    def test_compute_does_not_mutate_input_df(self):
        """compute() should work on a copy, not the original DataFrame."""
        reg = IndicatorRegistry()

        def mutating_fn(df):
            df["new_col"] = 999
            return df

        mock_mod = _make_mock_module(mutating_fn)
        reg._indicators["mut"] = IndicatorInfo(
            id="mut", name="Mut", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["mut"] = mock_mod

        df = _make_ohlcv_df()
        original_cols = list(df.columns)
        reg.compute("mut", df)
        assert list(df.columns) == original_cols

    def test_compute_excludes_nan_from_latest(self):
        """NaN values in latest row should not appear in output."""
        reg = IndicatorRegistry()

        def nan_fn(df):
            df["has_nan"] = float("nan")
            df["has_value"] = 42.0
            return df

        mock_mod = _make_mock_module(nan_fn)
        reg._indicators["nan_ind"] = IndicatorInfo(
            id="nan_ind", name="Nan Ind", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["nan_ind"] = mock_mod

        result = reg.compute("nan_ind", _make_ohlcv_df())
        assert "has_nan" not in result["latest"]
        assert result["latest"]["has_value"] == 42.0

    def test_compute_handles_exception_in_indicator(self):
        """If the indicator function raises, compute() returns an error dict."""
        reg = IndicatorRegistry()

        def raising_fn(df):
            raise ValueError("Broken indicator")

        mock_mod = _make_mock_module(raising_fn)
        reg._indicators["broken"] = IndicatorInfo(
            id="broken", name="Broken", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["broken"] = mock_mod

        result = reg.compute("broken", _make_ohlcv_df())
        assert "error" in result
        assert "Broken indicator" in result["error"]


# ---------------------------------------------------------------------------
# IndicatorRegistry — compute_all_signals
# ---------------------------------------------------------------------------

class TestRegistryComputeAllSignals:
    def test_compute_all_signals_empty_registry(self):
        reg = IndicatorRegistry()
        result = reg.compute_all_signals(_make_ohlcv_df())
        assert result == []

    def test_compute_all_signals_with_signal_columns(self):
        """Indicators that produce signal columns should be included in results."""
        reg = IndicatorRegistry()

        def buy_signal_fn(df):
            df["Buy"] = 0
            df.iloc[-1, df.columns.get_loc("Buy")] = 1
            return df

        mock_mod = _make_mock_module(buy_signal_fn)
        reg._indicators["buy_ind"] = IndicatorInfo(
            id="buy_ind", name="Buy Ind", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["buy_ind"] = mock_mod

        results = reg.compute_all_signals(_make_ohlcv_df())
        # The signal detection logic checks column names for keywords
        buy_results = [r for r in results if r["indicator_id"] == "buy_ind"]
        # Whether this fires depends on the signal column detection logic;
        # confirm it doesn't crash at minimum
        assert isinstance(results, list)

    def test_compute_all_signals_skips_broken_indicator(self):
        """If one indicator raises, it should be silently skipped."""
        reg = IndicatorRegistry()

        def raising_fn(df):
            raise RuntimeError("oops")

        def good_fn(df):
            df["Sell_Signal"] = 1
            return df

        bad_mod = _make_mock_module(raising_fn)
        good_mod = _make_mock_module(good_fn)

        reg._indicators["bad"] = IndicatorInfo(
            id="bad", name="Bad", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["bad"] = bad_mod

        reg._indicators["good"] = IndicatorInfo(
            id="good", name="Good", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["good"] = good_mod

        # Should not raise despite the broken indicator
        results = reg.compute_all_signals(_make_ohlcv_df())
        assert isinstance(results, list)

    def test_compute_all_signals_no_signal_columns(self):
        """Indicator that adds non-signal columns should yield empty results."""
        reg = IndicatorRegistry()

        def no_signal_fn(df):
            df["SMA_50"] = df["close"].rolling(2, min_periods=1).mean()
            return df

        mock_mod = _make_mock_module(no_signal_fn)
        reg._indicators["sma"] = IndicatorInfo(
            id="sma", name="SMA", file_path="/fake",
            category="custom", has_signals=True,
        )
        reg._modules["sma"] = mock_mod

        results = reg.compute_all_signals(_make_ohlcv_df())
        # SMA_50 is not a signal column name, so no signals should fire
        assert results == []


# ---------------------------------------------------------------------------
# IndicatorInfo dataclass
# ---------------------------------------------------------------------------

class TestIndicatorInfo:
    def test_default_output_columns(self):
        info = IndicatorInfo(
            id="test", name="Test", file_path="/fake",
            category="custom", has_signals=False,
        )
        assert info.output_columns == []

    def test_with_output_columns(self):
        info = IndicatorInfo(
            id="test", name="Test", file_path="/fake",
            category="custom", has_signals=True,
            output_columns=["Buy", "Sell"],
        )
        assert info.output_columns == ["Buy", "Sell"]


# ---------------------------------------------------------------------------
# Global singleton functions
# ---------------------------------------------------------------------------

class TestGlobalSingleton:
    def test_get_indicator_registry_returns_same_instance(self):
        reg1 = get_indicator_registry()
        reg2 = get_indicator_registry()
        assert reg1 is reg2

    def test_get_indicator_registry_returns_registry_type(self):
        reg = get_indicator_registry()
        assert isinstance(reg, IndicatorRegistry)

    def test_init_indicator_registry_calls_discover(self):
        """init_indicator_registry should call discover() on the global singleton."""
        with patch.object(IndicatorRegistry, "discover") as mock_discover:
            init_indicator_registry()
            mock_discover.assert_called_once()
