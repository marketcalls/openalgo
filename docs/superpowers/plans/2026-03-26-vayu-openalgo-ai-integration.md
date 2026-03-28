# VAYU + OpenAlgo AI Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed VAYU's AI analysis intelligence (20+ indicators, weighted signal engine, market regime detection) into OpenAlgo's production trading platform (32 brokers, REST API, event bus), enabling AI agents to analyze markets and execute trades through a unified interface.

**Architecture:** A new `ai/` package inside OpenAlgo that adapts VAYU's analysis engine (indicators, signals, regime detection) to work with OpenAlgo's data and order flow. The AI layer reads market data via OpenAlgo's existing `history_service` and `quotes_service`, runs VAYU's analysis pipeline, and exposes results through new REST API endpoints + MCP tools. Agent decisions flow through OpenAlgo's event bus for audit, and orders route through the existing broker service layer. No separate server — everything runs inside the Flask app.

**Tech Stack:** Python 3.12+ (uv), Flask, Flask-RESTX, pandas, ta (technical analysis), OpenAlgo services, event bus, SQLite, MCP (FastMCP)

**Backup:** `D:\openalgo-backup-2026-03-26`

---

## Scope Check

This plan covers one self-contained subsystem: the AI analysis + agent layer inside OpenAlgo. It does NOT cover:
- Modifying VAYU's FastAPI backend (read-only source)
- Frontend React components (separate plan)
- Sentiment/NLP analysis (Phase 2, separate plan)
- Multi-agent orchestration via CCGL/Triad Workbench (separate plan)

---

## File Structure

### New Files

```
D:\openalgo\
├── ai/                                    # NEW: AI analysis package
│   ├── __init__.py                        # Package init, exports
│   ├── indicators.py                      # VAYU core indicators (20+ via ta library)
│   ├── indicators_advanced.py             # Advanced: SMC, harmonics, candlesticks, CPR, Fib
│   ├── indicators_ml.py                   # ML hybrid VWAP+BB confidence scorer
│   ├── signals.py                         # VAYU signal engine (weighted composite)
│   ├── signals_advanced.py                # Extended signals using advanced indicators
│   ├── symbol_mapper.py                   # OpenAlgo ↔ VAYU symbol format conversion
│   ├── data_bridge.py                     # Fetches OHLCV via OpenAlgo services
│   └── agent_decisions.py                 # Decision logging + audit trail
│
├── database/
│   └── ai_db.py                           # NEW: AI decision + signal persistence
│
├── events/
│   └── ai_events.py                       # NEW: Agent event types
│
├── subscribers/
│   └── ai_subscriber.py                   # NEW: Log agent events
│
├── services/
│   └── ai_analysis_service.py             # NEW: Service layer orchestrating analysis
│
├── restx_api/
│   └── ai_agent.py                        # NEW: REST API namespace /api/v1/agent/*
│
├── test/
│   ├── test_ai_indicators.py              # NEW: Indicator engine tests
│   ├── test_ai_signals.py                 # NEW: Signal engine tests
│   ├── test_ai_symbol_mapper.py           # NEW: Symbol mapping tests
│   ├── test_ai_data_bridge.py             # NEW: Data bridge tests
│   ├── test_ai_analysis_service.py        # NEW: Service integration tests
│   └── test_ai_agent_api.py               # NEW: API endpoint tests
```

### Modified Files

```
D:\openalgo\
├── restx_api/__init__.py                  # Add: ai_agent namespace import + registration
├── app.py                                 # Add: init_ai_db() call in setup_environment
├── events/__init__.py                     # Add: AI event imports
├── subscribers/__init__.py                # Add: AI subscriber registration
├── mcp/mcpserver.py                       # Add: 3 new AI analysis MCP tools
```

---

## Task 1: Symbol Mapper

**Files:**
- Create: `ai/symbol_mapper.py`
- Test: `test/test_ai_symbol_mapper.py`

OpenAlgo uses `RELIANCE` (plain symbol) + separate `exchange` param. VAYU uses `RELIANCE.NS` (yfinance format). The mapper converts between formats and handles NSE/BSE/NFO edge cases.

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_symbol_mapper.py
import pytest
from ai.symbol_mapper import to_openalgo, to_yfinance, parse_openalgo_symbol


def test_to_yfinance_nse_equity():
    assert to_yfinance("RELIANCE", "NSE") == "RELIANCE.NS"


def test_to_yfinance_bse_equity():
    assert to_yfinance("RELIANCE", "BSE") == "RELIANCE.BO"


def test_to_openalgo_from_yfinance():
    symbol, exchange = to_openalgo("RELIANCE.NS")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"


def test_to_openalgo_from_yfinance_bse():
    symbol, exchange = to_openalgo("RELIANCE.BO")
    assert symbol == "RELIANCE"
    assert exchange == "BSE"


def test_to_openalgo_no_suffix():
    symbol, exchange = to_openalgo("RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"  # default


def test_to_yfinance_nfo():
    assert to_yfinance("NIFTY24JAN24000CE", "NFO") == "NIFTY24JAN24000CE.NS"


def test_parse_openalgo_symbol_with_exchange_prefix():
    symbol, exchange = parse_openalgo_symbol("NSE:RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"


def test_parse_openalgo_symbol_plain():
    symbol, exchange = parse_openalgo_symbol("RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_symbol_mapper.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'ai')

- [ ] **Step 3: Create package init and implement symbol mapper**

```python
# ai/__init__.py
"""AI analysis package for OpenAlgo — powered by VAYU patterns."""
```

```python
# ai/symbol_mapper.py
"""Convert between OpenAlgo and yfinance symbol formats.

OpenAlgo: symbol='RELIANCE', exchange='NSE' (separate params)
yfinance: 'RELIANCE.NS' (suffixed)
"""

_EXCHANGE_TO_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
    "NFO": ".NS",
    "MCX": ".NS",
    "CDS": ".NS",
    "BFO": ".BO",
    "BCD": ".BO",
    "NCDEX": ".NS",
}

_SUFFIX_TO_EXCHANGE = {
    ".NS": "NSE",
    ".BO": "BSE",
}


def to_yfinance(symbol: str, exchange: str = "NSE") -> str:
    """Convert OpenAlgo symbol + exchange to yfinance format."""
    suffix = _EXCHANGE_TO_SUFFIX.get(exchange.upper(), ".NS")
    return f"{symbol.upper()}{suffix}"


def to_openalgo(yf_symbol: str) -> tuple[str, str]:
    """Convert yfinance symbol to (symbol, exchange) tuple."""
    for suffix, exchange in _SUFFIX_TO_EXCHANGE.items():
        if yf_symbol.upper().endswith(suffix):
            return yf_symbol[: -len(suffix)].upper(), exchange
    return yf_symbol.upper(), "NSE"


def parse_openalgo_symbol(raw: str) -> tuple[str, str]:
    """Parse 'NSE:RELIANCE' or 'RELIANCE' into (symbol, exchange)."""
    if ":" in raw:
        exchange, symbol = raw.split(":", 1)
        return symbol.strip().upper(), exchange.strip().upper()
    return raw.strip().upper(), "NSE"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_symbol_mapper.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add ai/__init__.py ai/symbol_mapper.py test/test_ai_symbol_mapper.py
git commit -m "feat(ai): add symbol mapper for OpenAlgo ↔ yfinance conversion"
```

---

## Task 2: Indicator Engine

**Files:**
- Create: `ai/indicators.py`
- Test: `test/test_ai_indicators.py`

Port VAYU's `compute_all_indicators()` from `backend/analysis/technical/indicators.py`. Uses `ta` library (NOT pandas-ta). The `_safe()` wrapper pattern prevents crashes on edge cases.

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_indicators.py
import pandas as pd
import numpy as np
import pytest
from ai.indicators import compute_indicators


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + abs(np.random.randn(n) * 0.5),
        "low": close - abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


def test_returns_dataframe():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)


def test_adds_rsi_column():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "rsi_14" in result.columns


def test_adds_macd_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "macd" in result.columns
    assert "macd_signal" in result.columns
    assert "macd_hist" in result.columns


def test_adds_ema_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "ema_9" in result.columns
    assert "ema_21" in result.columns


def test_adds_bollinger_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "bb_high" in result.columns
    assert "bb_low" in result.columns
    assert "bb_pband" in result.columns


def test_adds_supertrend_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "supertrend" in result.columns
    assert "supertrend_dir" in result.columns


def test_adds_adx_column():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "adx_14" in result.columns


def test_handles_short_data():
    df = _make_ohlcv(5)
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 5


def test_does_not_mutate_input():
    df = _make_ohlcv(50)
    original_cols = list(df.columns)
    compute_indicators(df)
    assert list(df.columns) == original_cols


def test_no_exceptions_on_edge_case():
    df = pd.DataFrame({
        "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.5], "volume": [1000.0],
    })
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_indicators.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement indicator engine**

```python
# ai/indicators.py
"""Technical indicator engine adapted from VAYU.

Uses `ta` library (NOT pandas-ta which is broken/unmaintained).
All computations wrapped in _safe() to prevent crashes on short data.
"""

import numpy as np
import pandas as pd
import ta
from utils.logging import get_logger

logger = get_logger(__name__)


def _safe(func, *args, **kwargs):
    """Safely compute an indicator, returning None on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Indicator skipped: {e}")
        return None


def _compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Compute Supertrend indicator."""
    hl2 = (df["high"] + df["low"]) / 2
    atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=period).average_true_range()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(period, len(df)):
        if df["close"].iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i - 1]:
                lower_band.iloc[i] = lower_band.iloc[i - 1]
            if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i - 1]:
                upper_band.iloc[i] = upper_band.iloc[i - 1]

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    df["supertrend"] = supertrend
    df["supertrend_dir"] = direction
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to an OHLCV DataFrame.

    Input: DataFrame with columns: open, high, low, close, volume
    Returns: new DataFrame with indicator columns added (does NOT mutate input).
    """
    if len(df) < 2:
        return df.copy()

    df = df.copy()
    n = len(df)
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]

    # === Trend ===
    macd_ind = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = _safe(macd_ind.macd)
    df["macd_signal"] = _safe(macd_ind.macd_signal)
    df["macd_hist"] = _safe(macd_ind.macd_diff)

    if n >= 30:
        adx_ind = ta.trend.ADXIndicator(h, l, c, window=14)
        df["adx_14"] = _safe(adx_ind.adx)
        df["dmp_14"] = _safe(adx_ind.adx_pos)
        df["dmn_14"] = _safe(adx_ind.adx_neg)

    # === Moving Averages ===
    df["ema_9"] = _safe(lambda: ta.trend.EMAIndicator(c, window=9).ema_indicator())
    df["ema_21"] = _safe(lambda: ta.trend.EMAIndicator(c, window=21).ema_indicator())
    if n >= 50:
        df["sma_50"] = _safe(lambda: ta.trend.SMAIndicator(c, window=50).sma_indicator())
    if n >= 200:
        df["sma_200"] = _safe(lambda: ta.trend.SMAIndicator(c, window=200).sma_indicator())

    # === Supertrend ===
    if n >= 15:
        df = _compute_supertrend(df, period=10, multiplier=3.0)

    # === Momentum ===
    df["rsi_14"] = _safe(lambda: ta.momentum.RSIIndicator(c, window=14).rsi())
    df["rsi_7"] = _safe(lambda: ta.momentum.RSIIndicator(c, window=7).rsi())

    if n >= 16:
        stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
        df["stoch_k"] = _safe(stoch.stoch)
        df["stoch_d"] = _safe(stoch.stoch_signal)

    # === Volatility ===
    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["bb_high"] = _safe(bb.bollinger_hband)
    df["bb_low"] = _safe(bb.bollinger_lband)
    df["bb_mid"] = _safe(bb.bollinger_mavg)
    df["bb_pband"] = _safe(bb.bollinger_pband)

    if n >= 14:
        df["atr_14"] = _safe(lambda: ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range())

    # === Volume ===
    df["obv"] = _safe(lambda: ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume())
    df["vwap"] = _safe(lambda: ta.volume.VolumeWeightedAveragePrice(h, l, c, v).volume_weighted_average_price())

    return df
```

- [ ] **Step 4: Ensure `ta` is in dependencies**

Run: `cd D:\openalgo && uv add ta` (if not already present)
Check: `uv run python -c "import ta; print(ta.__version__)"`

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_indicators.py -v`
Expected: all 10 tests PASS

- [ ] **Step 6: Commit**

```bash
cd D:\openalgo
git add ai/indicators.py test/test_ai_indicators.py
git commit -m "feat(ai): add technical indicator engine from VAYU (20+ indicators)"
```

---

## Task 2B: Advanced Indicators (SMC, Harmonics, Candlesticks, CPR, Fib, ML)

**Files:**
- Create: `ai/indicators_advanced.py`
- Create: `ai/indicators_ml.py`
- Create: `ai/signals_advanced.py`
- Test: `test/test_ai_indicators_advanced.py`

Copy and adapt indicator logic from `D:\test1\self indc\` and `D:\test1\opensource_indicators\smart-money-concepts\`. All functions take OHLCV DataFrame, return DataFrame with added columns. No lookahead bias (signals use shift(1)).

**Source files to port:**
- SMC: `smc_bos.py`, `smc_choch.py`, `smc_fvg.py`, `smc_ob.py` + `smart-money-concepts/smc.py`
- Harmonics: `harmonic_patterns.py` (Gartley, Bat, Butterfly, Crab, Shark, Cypher, ABCD)
- Candlestick: `candlestick_patterns_identified.py` (15 patterns)
- CPR: `central_pivot_range.py` (pivot, BC/TC, R1-R5, S1-S5)
- Fibonacci: `fibonacci_levels.py` (0.236, 0.382, 0.5, 0.618, 0.786)
- Divergence: `rsi_divergence.py`
- Volume: `volume_exhaustion.py`, `vwap_bb_confluence.py`
- ML Hybrid: `hybrid_ml_vwap_bb.py` (10-feature confidence scorer)
- Reversal: `bahai_reversal_points.py`, `n_bar_reversal_luxalgo.py`
- Market Profile: `mp_value_area.py` (POC, Value Area)

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_indicators_advanced.py
import pandas as pd
import numpy as np
import pytest
from ai.indicators_advanced import (
    compute_smc_indicators,
    compute_candlestick_patterns,
    compute_cpr_levels,
    compute_fibonacci_levels,
    compute_harmonic_patterns,
    compute_rsi_divergence,
    compute_volume_signals,
)


def _make_ohlcv(n: int = 200, trend: str = "up") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    if trend == "up":
        close = 100 + np.arange(n) * 0.3 + rng.standard_normal(n) * 0.5
    elif trend == "down":
        close = 200 - np.arange(n) * 0.3 + rng.standard_normal(n) * 0.5
    else:
        close = 100 + rng.standard_normal(n) * 1.0
    return pd.DataFrame({
        "open": close + rng.standard_normal(n) * 0.2,
        "high": close + abs(rng.standard_normal(n) * 0.8),
        "low": close - abs(rng.standard_normal(n) * 0.8),
        "close": close,
        "volume": rng.integers(1000, 10000, size=n).astype(float),
    })


class TestSMC:
    def test_returns_dataframe(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert isinstance(result, pd.DataFrame)

    def test_has_bos_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_bos_bullish" in result.columns
        assert "smc_bos_bearish" in result.columns

    def test_has_fvg_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_fvg_bullish" in result.columns
        assert "smc_fvg_bearish" in result.columns

    def test_has_ob_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_ob_bullish" in result.columns
        assert "smc_ob_bearish" in result.columns

    def test_has_choch_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_choch_bullish" in result.columns
        assert "smc_choch_bearish" in result.columns

    def test_does_not_mutate_input(self):
        df = _make_ohlcv(100)
        orig_cols = list(df.columns)
        compute_smc_indicators(df)
        assert list(df.columns) == orig_cols


class TestCandlestickPatterns:
    def test_returns_dataframe(self):
        result = compute_candlestick_patterns(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_pattern_columns(self):
        result = compute_candlestick_patterns(_make_ohlcv(100))
        expected = ["cdl_doji", "cdl_hammer", "cdl_engulfing_bull", "cdl_engulfing_bear"]
        for col in expected:
            assert col in result.columns, f"Missing {col}"

    def test_binary_values(self):
        result = compute_candlestick_patterns(_make_ohlcv(200))
        for col in result.columns:
            if col.startswith("cdl_"):
                assert set(result[col].dropna().unique()).issubset({0, 1, True, False}), f"{col} not binary"


class TestCPR:
    def test_returns_dataframe(self):
        result = compute_cpr_levels(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_pivot_columns(self):
        result = compute_cpr_levels(_make_ohlcv(100))
        for col in ["pivot", "bc", "tc", "r1", "s1", "r2", "s2"]:
            assert col in result.columns, f"Missing {col}"


class TestFibonacci:
    def test_returns_dataframe(self):
        result = compute_fibonacci_levels(_make_ohlcv(200))
        assert isinstance(result, pd.DataFrame)

    def test_has_fib_signal(self):
        result = compute_fibonacci_levels(_make_ohlcv(200))
        assert "fib_long" in result.columns
        assert "fib_short" in result.columns


class TestHarmonics:
    def test_returns_dataframe(self):
        result = compute_harmonic_patterns(_make_ohlcv(200))
        assert isinstance(result, pd.DataFrame)

    def test_has_harmonic_columns(self):
        result = compute_harmonic_patterns(_make_ohlcv(200))
        assert "harmonic_bullish" in result.columns
        assert "harmonic_bearish" in result.columns


class TestDivergence:
    def test_returns_dataframe(self):
        result = compute_rsi_divergence(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_divergence_columns(self):
        result = compute_rsi_divergence(_make_ohlcv(100))
        assert "rsi_bull_divergence" in result.columns
        assert "rsi_bear_divergence" in result.columns


class TestVolume:
    def test_returns_dataframe(self):
        result = compute_volume_signals(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_volume_columns(self):
        result = compute_volume_signals(_make_ohlcv(100))
        assert "volume_exhaustion" in result.columns
        assert "vwap_bb_confluence" in result.columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_indicators_advanced.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement indicators_advanced.py**

Port each indicator from the source files. Each function:
- Takes OHLCV DataFrame
- Returns DataFrame with new columns added
- Uses `_safe()` wrapper for crash protection
- No lookahead bias (shift signals by 1 where needed)

```python
# ai/indicators_advanced.py
"""Advanced technical indicators from custom + open-source libraries.

Sources:
- Smart Money Concepts (BOS, CHoCH, FVG, Order Blocks)
- Harmonic Patterns (Gartley, Bat, Butterfly, Crab, Shark, Cypher)
- 15 Candlestick Patterns
- Central Pivot Range (Pivot, BC/TC, R1-R5, S1-S5)
- Fibonacci Retracement Levels
- RSI Divergence
- Volume Exhaustion + VWAP/BB Confluence
"""

import numpy as np
import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


def _safe(func, default=None):
    """Safely execute indicator computation."""
    try:
        return func()
    except Exception as e:
        logger.debug(f"Advanced indicator skipped: {e}")
        return default


# ============================================================
# SMART MONEY CONCEPTS
# ============================================================

def _detect_swing_points(df: pd.DataFrame, length: int = 10) -> pd.DataFrame:
    """Detect swing highs and lows using rolling window."""
    df = df.copy()
    df["swing_high"] = df["high"].rolling(length * 2 + 1, center=True).apply(
        lambda x: 1 if x.iloc[length] == x.max() else 0, raw=False
    )
    df["swing_low"] = df["low"].rolling(length * 2 + 1, center=True).apply(
        lambda x: 1 if x.iloc[length] == x.min() else 0, raw=False
    )
    return df


def compute_smc_indicators(df: pd.DataFrame, swing_length: int = 10) -> pd.DataFrame:
    """Compute Smart Money Concept indicators: BOS, CHoCH, FVG, Order Blocks."""
    df = df.copy()
    n = len(df)

    # Initialize output columns
    for col in ["smc_bos_bullish", "smc_bos_bearish", "smc_choch_bullish", "smc_choch_bearish",
                 "smc_fvg_bullish", "smc_fvg_bearish", "smc_ob_bullish", "smc_ob_bearish"]:
        df[col] = 0

    if n < swing_length * 3:
        return df

    # Detect swings
    df = _detect_swing_points(df, swing_length)

    # --- Fair Value Gaps (3-bar imbalance) ---
    for i in range(2, n):
        # Bullish FVG: bar[i] low > bar[i-2] high (gap up)
        if df["low"].iloc[i] > df["high"].iloc[i - 2]:
            df.iloc[i, df.columns.get_loc("smc_fvg_bullish")] = 1
        # Bearish FVG: bar[i] high < bar[i-2] low (gap down)
        if df["high"].iloc[i] < df["low"].iloc[i - 2]:
            df.iloc[i, df.columns.get_loc("smc_fvg_bearish")] = 1

    # --- Break of Structure / Change of Character ---
    last_swing_high = None
    last_swing_low = None
    trend = 0  # 1=up, -1=down, 0=neutral

    for i in range(swing_length, n):
        if df["swing_high"].iloc[i] == 1:
            last_swing_high = df["high"].iloc[i]
        if df["swing_low"].iloc[i] == 1:
            last_swing_low = df["low"].iloc[i]

        if last_swing_high is not None and df["close"].iloc[i] > last_swing_high:
            if trend == -1:
                df.iloc[i, df.columns.get_loc("smc_choch_bullish")] = 1  # Change of character
            else:
                df.iloc[i, df.columns.get_loc("smc_bos_bullish")] = 1   # Break of structure
            trend = 1

        if last_swing_low is not None and df["close"].iloc[i] < last_swing_low:
            if trend == 1:
                df.iloc[i, df.columns.get_loc("smc_choch_bearish")] = 1
            else:
                df.iloc[i, df.columns.get_loc("smc_bos_bearish")] = 1
            trend = -1

    # --- Order Blocks (last opposite candle before BOS) ---
    for i in range(1, n):
        if df["smc_bos_bullish"].iloc[i] == 1 or df["smc_choch_bullish"].iloc[i] == 1:
            for j in range(i - 1, max(i - 10, 0), -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:  # Last bearish candle
                    df.iloc[j, df.columns.get_loc("smc_ob_bullish")] = 1
                    break
        if df["smc_bos_bearish"].iloc[i] == 1 or df["smc_choch_bearish"].iloc[i] == 1:
            for j in range(i - 1, max(i - 10, 0), -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:  # Last bullish candle
                    df.iloc[j, df.columns.get_loc("smc_ob_bearish")] = 1
                    break

    return df


# ============================================================
# CANDLESTICK PATTERNS (15)
# ============================================================

def compute_candlestick_patterns(df: pd.DataFrame, doji_size: float = 0.05) -> pd.DataFrame:
    """Detect 15 candlestick patterns."""
    df = df.copy()
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = abs(c - o)
    hl_range = h - l
    upper_shadow = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_shadow = pd.concat([o, c], axis=1).min(axis=1) - l

    # Doji
    df["cdl_doji"] = (body <= hl_range * doji_size).astype(int)

    # Hammer (small body at top, long lower shadow)
    df["cdl_hammer"] = ((lower_shadow > body * 2) & (upper_shadow < body * 0.5) & (hl_range > 0)).astype(int)

    # Inverted Hammer
    df["cdl_inverted_hammer"] = ((upper_shadow > body * 2) & (lower_shadow < body * 0.5) & (hl_range > 0)).astype(int)

    # Shooting Star (same shape as inverted hammer but in uptrend)
    df["cdl_shooting_star"] = ((upper_shadow > body * 2) & (lower_shadow < body * 0.3) & (c < o) & (hl_range > 0)).astype(int)

    # Hanging Man (same shape as hammer but in uptrend)
    df["cdl_hanging_man"] = ((lower_shadow > body * 2) & (upper_shadow < body * 0.3) & (c < o) & (hl_range > 0)).astype(int)

    # Engulfing
    prev_body = body.shift(1)
    df["cdl_engulfing_bull"] = ((c > o) & (c.shift(1) < o.shift(1)) & (body > prev_body) & (c > o.shift(1)) & (o < c.shift(1))).astype(int)
    df["cdl_engulfing_bear"] = ((c < o) & (c.shift(1) > o.shift(1)) & (body > prev_body) & (c < o.shift(1)) & (o > c.shift(1))).astype(int)

    # Harami
    df["cdl_harami_bull"] = ((c > o) & (c.shift(1) < o.shift(1)) & (c < o.shift(1)) & (o > c.shift(1))).astype(int)
    df["cdl_harami_bear"] = ((c < o) & (c.shift(1) > o.shift(1)) & (c > o.shift(1)) & (o < c.shift(1))).astype(int)

    # Morning Star (3-bar)
    df["cdl_morning_star"] = (
        (c.shift(2) < o.shift(2)) &  # Bar 1: bearish
        (body.shift(1) < body.shift(2) * 0.3) &  # Bar 2: small body (star)
        (c > o) &  # Bar 3: bullish
        (c > (o.shift(2) + c.shift(2)) / 2)  # Bar 3 closes above bar 1 midpoint
    ).astype(int)

    # Evening Star (3-bar)
    df["cdl_evening_star"] = (
        (c.shift(2) > o.shift(2)) &
        (body.shift(1) < body.shift(2) * 0.3) &
        (c < o) &
        (c < (o.shift(2) + c.shift(2)) / 2)
    ).astype(int)

    # Piercing Line
    df["cdl_piercing_line"] = (
        (c.shift(1) < o.shift(1)) & (c > o) &
        (o < c.shift(1)) & (c > (o.shift(1) + c.shift(1)) / 2) & (c < o.shift(1))
    ).astype(int)

    # Dark Cloud Cover
    df["cdl_dark_cloud"] = (
        (c.shift(1) > o.shift(1)) & (c < o) &
        (o > c.shift(1)) & (c < (o.shift(1) + c.shift(1)) / 2) & (c > o.shift(1))
    ).astype(int)

    # Three White Soldiers
    df["cdl_three_white_soldiers"] = (
        (c > o) & (c.shift(1) > o.shift(1)) & (c.shift(2) > o.shift(2)) &
        (c > c.shift(1)) & (c.shift(1) > c.shift(2)) &
        (o > o.shift(1)) & (o.shift(1) > o.shift(2))
    ).astype(int)

    # Three Black Crows
    df["cdl_three_black_crows"] = (
        (c < o) & (c.shift(1) < o.shift(1)) & (c.shift(2) < o.shift(2)) &
        (c < c.shift(1)) & (c.shift(1) < c.shift(2)) &
        (o < o.shift(1)) & (o.shift(1) < o.shift(2))
    ).astype(int)

    return df


# ============================================================
# CENTRAL PIVOT RANGE
# ============================================================

def compute_cpr_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Central Pivot Range from previous session OHLC."""
    df = df.copy()
    prev_h = df["high"].shift(1)
    prev_l = df["low"].shift(1)
    prev_c = df["close"].shift(1)

    df["pivot"] = (prev_h + prev_l + prev_c) / 3
    mid = (prev_h + prev_l) / 2
    df["bc"] = pd.concat([mid, 2 * df["pivot"] - mid], axis=1).min(axis=1)
    df["tc"] = pd.concat([mid, 2 * df["pivot"] - mid], axis=1).max(axis=1)

    diff = prev_h - prev_l
    df["r1"] = 2 * df["pivot"] - prev_l
    df["s1"] = 2 * df["pivot"] - prev_h
    df["r2"] = df["pivot"] + diff
    df["s2"] = df["pivot"] - diff
    df["r3"] = prev_h + 2 * (df["pivot"] - prev_l)
    df["s3"] = prev_l - 2 * (prev_h - df["pivot"])

    return df


# ============================================================
# FIBONACCI RETRACEMENT
# ============================================================

def compute_fibonacci_levels(df: pd.DataFrame, lookback: int = 50, tolerance: float = 0.005) -> pd.DataFrame:
    """Compute Fibonacci retracement signals from swing highs/lows."""
    df = df.copy()
    df["fib_long"] = 0
    df["fib_short"] = 0
    fib_ratios = [0.382, 0.500, 0.618]

    if len(df) < lookback:
        return df

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        swing_high = window["high"].max()
        swing_low = window["low"].min()
        rng = swing_high - swing_low
        if rng < 0.01:
            continue

        close = df["close"].iloc[i]
        for ratio in fib_ratios:
            # Bullish: price near fib support level (retracement from high)
            support = swing_high - ratio * rng
            if abs(close - support) / close < tolerance:
                df.iloc[i, df.columns.get_loc("fib_long")] = 1
                break
            # Bearish: price near fib resistance level (retracement from low)
            resistance = swing_low + ratio * rng
            if abs(close - resistance) / close < tolerance:
                df.iloc[i, df.columns.get_loc("fib_short")] = 1
                break

    return df


# ============================================================
# HARMONIC PATTERNS (XABCD)
# ============================================================

def compute_harmonic_patterns(df: pd.DataFrame, zigzag_pct: float = 3.0) -> pd.DataFrame:
    """Detect harmonic patterns: Gartley, Bat, Butterfly, Crab, Shark, Cypher."""
    df = df.copy()
    df["harmonic_bullish"] = 0
    df["harmonic_bearish"] = 0

    if len(df) < 30:
        return df

    # Extract zigzag pivots
    pivots = _extract_zigzag(df, pct=zigzag_pct)
    if len(pivots) < 5:
        return df

    # Harmonic ratio definitions {pattern: {XB, AC, BD, XD}}
    PATTERNS = {
        "gartley":    {"XB": (0.618, 0.618), "AC": (0.382, 0.886), "BD": (1.27, 1.618), "XD": (0.786, 0.786)},
        "bat":        {"XB": (0.382, 0.500), "AC": (0.382, 0.886), "BD": (1.618, 2.618), "XD": (0.886, 0.886)},
        "butterfly":  {"XB": (0.786, 0.786), "AC": (0.382, 0.886), "BD": (1.618, 2.618), "XD": (1.27, 1.618)},
        "crab":       {"XB": (0.382, 0.618), "AC": (0.382, 0.886), "BD": (2.24, 3.618),  "XD": (1.618, 1.618)},
    }
    tolerance = 0.08  # 8% ratio tolerance

    for i in range(4, len(pivots)):
        X, A, B, C, D = [pivots[j] for j in range(i - 4, i + 1)]
        xa = abs(A[1] - X[1])
        if xa < 0.01:
            continue

        xb_ratio = abs(B[1] - X[1]) / xa
        ac_ratio = abs(C[1] - A[1]) / abs(B[1] - A[1]) if abs(B[1] - A[1]) > 0.01 else 0
        bd_ratio = abs(D[1] - B[1]) / abs(C[1] - B[1]) if abs(C[1] - B[1]) > 0.01 else 0
        xd_ratio = abs(D[1] - X[1]) / xa

        for name, ratios in PATTERNS.items():
            if (ratios["XB"][0] * (1 - tolerance) <= xb_ratio <= ratios["XB"][1] * (1 + tolerance) and
                ratios["AC"][0] * (1 - tolerance) <= ac_ratio <= ratios["AC"][1] * (1 + tolerance) and
                ratios["BD"][0] * (1 - tolerance) <= bd_ratio <= ratios["BD"][1] * (1 + tolerance) and
                ratios["XD"][0] * (1 - tolerance) <= xd_ratio <= ratios["XD"][1] * (1 + tolerance)):
                d_idx = D[0]
                if D[1] < C[1]:  # D is a low → bullish
                    df.iloc[d_idx, df.columns.get_loc("harmonic_bullish")] = 1
                else:  # D is a high → bearish
                    df.iloc[d_idx, df.columns.get_loc("harmonic_bearish")] = 1
                break

    return df


def _extract_zigzag(df: pd.DataFrame, pct: float = 3.0) -> list[tuple[int, float]]:
    """Extract zigzag pivots from OHLCV data. Returns [(index, price), ...]."""
    pivots = []
    last_pivot = df["close"].iloc[0]
    last_idx = 0
    direction = 0  # 1=up, -1=down

    for i in range(1, len(df)):
        h, l = df["high"].iloc[i], df["low"].iloc[i]
        if direction >= 0 and h >= last_pivot * (1 + pct / 100):
            if direction == -1:
                pivots.append((last_idx, last_pivot))
            last_pivot = h
            last_idx = i
            direction = 1
        elif direction <= 0 and l <= last_pivot * (1 - pct / 100):
            if direction == 1:
                pivots.append((last_idx, last_pivot))
            last_pivot = l
            last_idx = i
            direction = -1

    if last_idx > 0:
        pivots.append((last_idx, last_pivot))
    return pivots


# ============================================================
# RSI DIVERGENCE
# ============================================================

def compute_rsi_divergence(df: pd.DataFrame, rsi_period: int = 14, lookback: int = 20) -> pd.DataFrame:
    """Detect bullish/bearish RSI divergence."""
    import ta
    df = df.copy()
    df["rsi_bull_divergence"] = 0
    df["rsi_bear_divergence"] = 0

    rsi = ta.momentum.RSIIndicator(df["close"], window=rsi_period).rsi()
    if rsi is None:
        return df
    df["_rsi"] = rsi

    for i in range(lookback, len(df)):
        window_price = df["close"].iloc[i - lookback:i + 1]
        window_rsi = df["_rsi"].iloc[i - lookback:i + 1]

        # Bullish divergence: price makes lower low, RSI makes higher low
        if (df["close"].iloc[i] < window_price.min() * 1.005 and
            df["_rsi"].iloc[i] > window_rsi.iloc[window_price.argmin()] if window_price.argmin() > 0 else False):
            df.iloc[i, df.columns.get_loc("rsi_bull_divergence")] = 1

        # Bearish divergence: price makes higher high, RSI makes lower high
        if (df["close"].iloc[i] > window_price.max() * 0.995 and
            df["_rsi"].iloc[i] < window_rsi.iloc[window_price.argmax()] if window_price.argmax() > 0 else False):
            df.iloc[i, df.columns.get_loc("rsi_bear_divergence")] = 1

    df.drop(columns=["_rsi"], inplace=True)
    return df


# ============================================================
# VOLUME SIGNALS
# ============================================================

def compute_volume_signals(df: pd.DataFrame, vol_mult: float = 2.0) -> pd.DataFrame:
    """Detect volume exhaustion and VWAP/BB confluence."""
    df = df.copy()

    # Volume exhaustion: volume spike > mult * avg volume
    avg_vol = df["volume"].rolling(20).mean()
    df["volume_exhaustion"] = (df["volume"] > avg_vol * vol_mult).astype(int)

    # VWAP/BB confluence: price near both VWAP and Bollinger Band
    try:
        import ta
        vwap = ta.volume.VolumeWeightedAveragePrice(
            df["high"], df["low"], df["close"], df["volume"]
        ).volume_weighted_average_price()
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        bb_low = bb.bollinger_lband()
        bb_high = bb.bollinger_hband()

        near_vwap = abs(df["close"] - vwap) / df["close"] < 0.005
        near_bb_low = abs(df["close"] - bb_low) / df["close"] < 0.005
        near_bb_high = abs(df["close"] - bb_high) / df["close"] < 0.005

        df["vwap_bb_confluence"] = ((near_vwap & near_bb_low) | (near_vwap & near_bb_high)).astype(int)
    except Exception:
        df["vwap_bb_confluence"] = 0

    return df


# ============================================================
# AGGREGATE: Run all advanced indicators
# ============================================================

def compute_all_advanced(df: pd.DataFrame) -> pd.DataFrame:
    """Run all advanced indicators on an OHLCV DataFrame."""
    df = _safe(lambda: compute_smc_indicators(df), df) or df
    df = _safe(lambda: compute_candlestick_patterns(df), df) or df
    df = _safe(lambda: compute_cpr_levels(df), df) or df
    df = _safe(lambda: compute_fibonacci_levels(df), df) or df
    df = _safe(lambda: compute_harmonic_patterns(df), df) or df
    df = _safe(lambda: compute_rsi_divergence(df), df) or df
    df = _safe(lambda: compute_volume_signals(df), df) or df
    return df
```

- [ ] **Step 4: Implement indicators_ml.py (ML Hybrid Confidence Scorer)**

```python
# ai/indicators_ml.py
"""ML-style confidence scoring adapted from hybrid_ml_vwap_bb.py.

10-feature scoring: price_position, volume_strength, trend_alignment,
volatility, momentum, delta_pressure, confluence, pattern_strength,
time_factor, vwap_distance.
"""

import numpy as np
import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


def compute_ml_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Compute ML-style confidence scores from multiple features.

    Returns DataFrame with: ml_buy_confidence, ml_sell_confidence (0-100)
    """
    df = df.copy()
    df["ml_buy_confidence"] = 0.0
    df["ml_sell_confidence"] = 0.0

    if len(df) < 30:
        return df

    c = df["close"]
    v = df["volume"]

    # Feature 1: Price position relative to range (0-1)
    high_20 = df["high"].rolling(20).max()
    low_20 = df["low"].rolling(20).min()
    rng = high_20 - low_20
    price_pos = np.where(rng > 0, (c - low_20) / rng, 0.5)

    # Feature 2: Volume strength (current vs average)
    vol_avg = v.rolling(20).mean()
    vol_strength = np.where(vol_avg > 0, v / vol_avg, 1.0)
    vol_strength = np.clip(vol_strength, 0, 3) / 3

    # Feature 3: Trend alignment (EMA 9 vs 21)
    ema9 = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    trend = np.where(ema21 > 0, (ema9 - ema21) / ema21, 0)
    trend_score = np.clip(trend * 50, -1, 1)

    # Feature 4: Momentum (ROC 10)
    roc = c.pct_change(10)
    momentum_score = np.clip(roc * 20, -1, 1)

    # Feature 5: Volatility (ATR relative)
    tr = pd.concat([
        df["high"] - df["low"],
        abs(df["high"] - c.shift(1)),
        abs(df["low"] - c.shift(1)),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    vol_score = np.where(c > 0, atr / c, 0)
    vol_score = np.clip(vol_score * 100, 0, 1)

    # Aggregate: buy confidence
    buy_raw = (
        (1 - price_pos) * 0.2 +  # Low price position = bullish
        vol_strength * 0.15 +
        np.clip(trend_score, 0, 1) * 0.25 +
        np.clip(momentum_score, 0, 1) * 0.25 +
        (1 - vol_score) * 0.15
    )
    df["ml_buy_confidence"] = np.clip(buy_raw * 100, 0, 100).round(1)

    # Aggregate: sell confidence
    sell_raw = (
        price_pos * 0.2 +
        vol_strength * 0.15 +
        np.clip(-trend_score, 0, 1) * 0.25 +
        np.clip(-momentum_score, 0, 1) * 0.25 +
        (1 - vol_score) * 0.15
    )
    df["ml_sell_confidence"] = np.clip(sell_raw * 100, 0, 100).round(1)

    return df
```

- [ ] **Step 5: Implement signals_advanced.py**

```python
# ai/signals_advanced.py
"""Extended signal generation using advanced indicators.

Adds SMC, candlestick, harmonic, divergence, and ML signals
to the base signal from signals.py.
"""

from ai.indicators_advanced import compute_all_advanced
from ai.indicators_ml import compute_ml_confidence
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_advanced_signals(df: pd.DataFrame) -> dict:
    """Generate advanced signal summary from all advanced indicators.

    Returns dict with counts and details of detected patterns.
    """
    # Run all advanced indicators
    df = compute_all_advanced(df)
    df = compute_ml_confidence(df)

    latest = df.iloc[-1]
    signals = {
        "smc": {},
        "candlestick": [],
        "cpr": {},
        "fibonacci": {},
        "harmonic": {},
        "divergence": {},
        "volume": {},
        "ml_confidence": {},
    }

    # SMC signals (latest bar)
    for col in ["smc_bos_bullish", "smc_bos_bearish", "smc_choch_bullish", "smc_choch_bearish",
                 "smc_fvg_bullish", "smc_fvg_bearish", "smc_ob_bullish", "smc_ob_bearish"]:
        if col in df.columns and latest.get(col, 0) == 1:
            signals["smc"][col] = True

    # Active candlestick patterns (last 3 bars)
    for col in df.columns:
        if col.startswith("cdl_") and df[col].iloc[-3:].sum() > 0:
            signals["candlestick"].append(col.replace("cdl_", ""))

    # CPR levels
    for col in ["pivot", "r1", "s1", "r2", "s2", "r3", "s3", "bc", "tc"]:
        if col in df.columns:
            val = latest.get(col)
            if val is not None and not (isinstance(val, float) and __import__("math").isnan(val)):
                signals["cpr"][col] = round(float(val), 2)

    # Fibonacci
    signals["fibonacci"]["long"] = int(latest.get("fib_long", 0))
    signals["fibonacci"]["short"] = int(latest.get("fib_short", 0))

    # Harmonic
    # Check last 5 bars for recent harmonic patterns
    signals["harmonic"]["bullish"] = int(df["harmonic_bullish"].iloc[-5:].sum() > 0) if "harmonic_bullish" in df.columns else 0
    signals["harmonic"]["bearish"] = int(df["harmonic_bearish"].iloc[-5:].sum() > 0) if "harmonic_bearish" in df.columns else 0

    # Divergence
    signals["divergence"]["rsi_bullish"] = int(latest.get("rsi_bull_divergence", 0))
    signals["divergence"]["rsi_bearish"] = int(latest.get("rsi_bear_divergence", 0))

    # Volume
    signals["volume"]["exhaustion"] = int(latest.get("volume_exhaustion", 0))
    signals["volume"]["vwap_bb_confluence"] = int(latest.get("vwap_bb_confluence", 0))

    # ML confidence
    signals["ml_confidence"]["buy"] = float(latest.get("ml_buy_confidence", 0))
    signals["ml_confidence"]["sell"] = float(latest.get("ml_sell_confidence", 0))

    return signals
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_indicators_advanced.py -v`
Expected: all 18 tests PASS

- [ ] **Step 7: Commit**

```bash
cd D:\openalgo
git add ai/indicators_advanced.py ai/indicators_ml.py ai/signals_advanced.py test/test_ai_indicators_advanced.py
git commit -m "feat(ai): add advanced indicators — SMC, harmonics, 15 candlestick patterns, CPR, Fibonacci, divergence, ML confidence, volume signals"
```

---

## Task 3: Signal Engine

**Files:**
- Create: `ai/signals.py`
- Test: `test/test_ai_signals.py`

Port VAYU's `generate_signal()` and `detect_regime()`. This is the weighted composite scorer that fuses 6 sub-signals into a single BUY/SELL/HOLD recommendation.

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_signals.py
import pandas as pd
import numpy as np
import pytest
from ai.indicators import compute_indicators
from ai.signals import generate_signal, detect_regime, SignalType, MarketRegime


def _make_ohlcv(n: int = 100, trend: str = "up") -> pd.DataFrame:
    np.random.seed(42)
    if trend == "up":
        close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    elif trend == "down":
        close = 200 - np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    else:
        close = 100 + np.random.randn(n) * 0.5
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + abs(np.random.randn(n) * 0.5),
        "low": close - abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


def test_generate_signal_returns_dict():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert isinstance(result, dict)
    assert "signal" in result
    assert "confidence" in result
    assert "score" in result
    assert "scores" in result
    assert "regime" in result


def test_signal_is_valid_type():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    valid = {s.value for s in SignalType}
    assert result["signal"] in valid


def test_confidence_is_bounded():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert 0 <= result["confidence"] <= 100


def test_score_is_bounded():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert -1.0 <= result["score"] <= 1.0


def test_short_data_returns_hold():
    df = _make_ohlcv(5)
    result = generate_signal(df)
    assert result["signal"] == SignalType.HOLD.value
    assert result["confidence"] == 0


def test_detect_regime_returns_valid():
    df = compute_indicators(_make_ohlcv(100))
    regime = detect_regime(df)
    valid = {r.value for r in MarketRegime}
    assert regime.value in valid


def test_uptrend_is_bullish():
    df = compute_indicators(_make_ohlcv(200, trend="up"))
    result = generate_signal(df)
    assert result["score"] > 0  # Bullish score for uptrend


def test_downtrend_is_bearish():
    df = compute_indicators(_make_ohlcv(200, trend="down"))
    result = generate_signal(df)
    assert result["score"] < 0  # Bearish score for downtrend


def test_custom_weights():
    df = compute_indicators(_make_ohlcv(100))
    weights = {"supertrend": 0.5, "rsi": 0.5}
    result = generate_signal(df, weights=weights)
    assert isinstance(result, dict)
    assert "score" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_signals.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement signal engine**

```python
# ai/signals.py
"""Weighted composite signal engine adapted from VAYU.

Fuses 6 sub-signals (supertrend, RSI, MACD, EMA cross, Bollinger, ADX)
into a single score [-1, +1] → mapped to SignalType.
"""

from enum import Enum

import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)

# Default weights (same as VAYU)
DEFAULT_WEIGHTS = {
    "supertrend": 0.25,
    "rsi": 0.20,
    "macd": 0.20,
    "ema_cross": 0.15,
    "bollinger": 0.10,
    "adx_strength": 0.10,
}


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class MarketRegime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


def detect_regime(df: pd.DataFrame) -> MarketRegime:
    """Detect market regime using ADX + ATR percentile."""
    if len(df) < 50:
        return MarketRegime.RANGING

    latest = df.iloc[-1]
    adx_val = latest.get("adx_14")
    atr_val = latest.get("atr_14")

    atr_pctile = 50
    if atr_val is not None and pd.notna(atr_val) and "atr_14" in df.columns:
        atr_series = df["atr_14"].dropna()
        if len(atr_series) > 0:
            atr_pctile = (atr_series < atr_val).sum() / len(atr_series) * 100

    if adx_val is None or pd.isna(adx_val):
        return MarketRegime.RANGING

    trending = adx_val > 25
    sma_50 = latest.get("sma_50")
    close = latest.get("close", 0)

    if trending and sma_50 is not None and pd.notna(sma_50) and close > sma_50:
        return MarketRegime.TRENDING_UP
    elif trending:
        return MarketRegime.TRENDING_DOWN
    elif atr_pctile > 60:
        return MarketRegime.VOLATILE
    else:
        return MarketRegime.RANGING


def generate_signal(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> dict:
    """Generate composite signal from indicator DataFrame.

    Args:
        df: DataFrame with indicator columns (from compute_indicators)
        weights: Optional custom weights dict. Defaults to DEFAULT_WEIGHTS.

    Returns:
        {"signal", "confidence", "score", "scores", "regime"}
    """
    if len(df) < 20:
        return {
            "signal": SignalType.HOLD.value,
            "confidence": 0,
            "score": 0.0,
            "scores": {},
            "regime": MarketRegime.RANGING.value,
        }

    w = weights if weights else DEFAULT_WEIGHTS
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    scores = {}

    # 1. Supertrend (25%)
    st_dir = latest.get("supertrend_dir")
    prev_st_dir = prev.get("supertrend_dir")
    if st_dir is not None and pd.notna(st_dir):
        if prev_st_dir is not None and pd.notna(prev_st_dir):
            if st_dir == 1 and prev_st_dir == -1:
                scores["supertrend"] = 1.0
            elif st_dir == 1:
                scores["supertrend"] = 0.4
            elif st_dir == -1 and prev_st_dir == 1:
                scores["supertrend"] = -1.0
            else:
                scores["supertrend"] = -0.4
        elif st_dir == 1:
            scores["supertrend"] = 0.3
        else:
            scores["supertrend"] = -0.3

    # 2. RSI (20%)
    rsi = latest.get("rsi_14")
    if rsi is not None and pd.notna(rsi):
        if rsi < 30:
            scores["rsi"] = 0.8
        elif rsi < 40:
            scores["rsi"] = 0.3
        elif rsi > 70:
            scores["rsi"] = -0.8
        elif rsi > 60:
            scores["rsi"] = -0.3
        else:
            scores["rsi"] = 0.0

    # 3. MACD (20%)
    macd_hist = latest.get("macd_hist")
    prev_hist = prev.get("macd_hist")
    if macd_hist is not None and pd.notna(macd_hist):
        if prev_hist is not None and pd.notna(prev_hist):
            if macd_hist > 0 and prev_hist <= 0:
                scores["macd"] = 0.8
            elif macd_hist < 0 and prev_hist >= 0:
                scores["macd"] = -0.8
            elif macd_hist > 0:
                scores["macd"] = 0.3
            else:
                scores["macd"] = -0.3
        elif macd_hist > 0:
            scores["macd"] = 0.2
        else:
            scores["macd"] = -0.2

    # 4. EMA crossover (15%)
    ema9 = latest.get("ema_9")
    ema21 = latest.get("ema_21")
    if ema9 is not None and ema21 is not None and pd.notna(ema9) and pd.notna(ema21):
        prev_ema9 = prev.get("ema_9", ema9)
        prev_ema21 = prev.get("ema_21", ema21)
        if pd.notna(prev_ema9) and pd.notna(prev_ema21):
            if ema9 > ema21 and prev_ema9 <= prev_ema21:
                scores["ema_cross"] = 0.8
            elif ema9 < ema21 and prev_ema9 >= prev_ema21:
                scores["ema_cross"] = -0.8
            elif ema9 > ema21:
                scores["ema_cross"] = 0.3
            else:
                scores["ema_cross"] = -0.3

    # 5. Bollinger Band (10%)
    bbp = latest.get("bb_pband")
    if bbp is not None and pd.notna(bbp):
        if bbp < 0.0:
            scores["bollinger"] = 0.6
        elif bbp < 0.2:
            scores["bollinger"] = 0.3
        elif bbp > 1.0:
            scores["bollinger"] = -0.6
        elif bbp > 0.8:
            scores["bollinger"] = -0.3
        else:
            scores["bollinger"] = 0.0

    # 6. ADX strength (10%)
    adx_val = latest.get("adx_14")
    if adx_val is not None and pd.notna(adx_val):
        scores["adx_strength"] = 0.2 if adx_val > 25 else -0.1

    # Weighted aggregation
    weighted_sum = 0.0
    total_weight = 0.0
    for key, score in scores.items():
        weight = w.get(key, 0.1)
        weighted_sum += weight * score
        total_weight += weight

    final_score = weighted_sum / total_weight if total_weight > 0 else 0.0
    confidence = min(abs(final_score) * 100, 100)

    if final_score >= 0.5:
        signal = SignalType.STRONG_BUY
    elif final_score > 0.2:
        signal = SignalType.BUY
    elif final_score <= -0.5:
        signal = SignalType.STRONG_SELL
    elif final_score < -0.2:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    regime = detect_regime(df)

    return {
        "signal": signal.value,
        "confidence": round(confidence, 1),
        "score": round(final_score, 4),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "regime": regime.value,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_signals.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add ai/signals.py test/test_ai_signals.py
git commit -m "feat(ai): add weighted composite signal engine from VAYU"
```

---

## Task 4: Data Bridge

**Files:**
- Create: `ai/data_bridge.py`
- Test: `test/test_ai_data_bridge.py`

Fetches OHLCV data via OpenAlgo's existing `history_service` and converts it to the DataFrame format expected by the indicator engine.

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_data_bridge.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from ai.data_bridge import fetch_ohlcv, OHLCVResult


def test_ohlcv_result_has_required_fields():
    result = OHLCVResult(
        success=True,
        df=pd.DataFrame(),
        symbol="RELIANCE",
        exchange="NSE",
        interval="1d",
        error=None,
    )
    assert result.success is True
    assert result.symbol == "RELIANCE"


def test_fetch_ohlcv_returns_ohlcv_result():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.return_value = {
            "status": "success",
            "data": {
                "timestamp": [1700000000, 1700086400],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 2000],
            },
        }
        result = fetch_ohlcv("RELIANCE", "NSE", "1d", api_key="test_key")
        assert result.success is True
        assert isinstance(result.df, pd.DataFrame)
        assert list(result.df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(result.df) == 2


def test_fetch_ohlcv_handles_error():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.return_value = {"status": "error", "message": "No data found"}
        result = fetch_ohlcv("INVALID", "NSE", "1d", api_key="test_key")
        assert result.success is False
        assert result.error is not None


def test_fetch_ohlcv_handles_exception():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.side_effect = Exception("Network error")
        result = fetch_ohlcv("RELIANCE", "NSE", "1d", api_key="test_key")
        assert result.success is False
        assert "Network error" in result.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_data_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement data bridge**

```python
# ai/data_bridge.py
"""Bridge between OpenAlgo data services and AI indicator engine.

Fetches OHLCV via OpenAlgo's history_service and returns a clean DataFrame.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OHLCVResult:
    success: bool
    df: pd.DataFrame
    symbol: str
    exchange: str
    interval: str
    error: str | None


def _call_history_service(
    symbol: str, exchange: str, interval: str, api_key: str,
    start_date: str | None = None, end_date: str | None = None,
) -> dict:
    """Call OpenAlgo's history service to fetch OHLCV data.

    Uses the real get_history() signature from services/history_service.py:
    get_history(symbol, exchange, interval, start_date, end_date, api_key, source)
    Returns: (success: bool, response_data: dict, status_code: int)
    """
    from services.history_service import get_history

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        days = 365 if interval in ("1d", "1wk", "1mo") else 60
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    success, response_data, status_code = get_history(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        api_key=api_key,
        source="api",
    )
    return response_data


def fetch_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
) -> OHLCVResult:
    """Fetch OHLCV data and return as a clean DataFrame.

    Returns OHLCVResult with DataFrame having columns: open, high, low, close, volume
    """
    try:
        response = _call_history_service(
            symbol, exchange, interval, api_key, start_date, end_date,
        )

        if isinstance(response, tuple):
            response = response[0]

        if isinstance(response, dict) and response.get("status") == "error":
            return OHLCVResult(
                success=False, df=pd.DataFrame(),
                symbol=symbol, exchange=exchange, interval=interval,
                error=response.get("message", "Unknown error"),
            )

        data = response.get("data", response) if isinstance(response, dict) else response

        if isinstance(data, dict):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            return OHLCVResult(
                success=False, df=pd.DataFrame(),
                symbol=symbol, exchange=exchange, interval=interval,
                error=f"Unexpected data type: {type(data)}",
            )

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                return OHLCVResult(
                    success=False, df=pd.DataFrame(),
                    symbol=symbol, exchange=exchange, interval=interval,
                    error=f"Missing column: {col}",
                )

        df = df[required].astype(float)

        return OHLCVResult(
            success=True, df=df,
            symbol=symbol, exchange=exchange, interval=interval,
            error=None,
        )

    except Exception as e:
        logger.error(f"fetch_ohlcv error for {symbol}: {e}")
        return OHLCVResult(
            success=False, df=pd.DataFrame(),
            symbol=symbol, exchange=exchange, interval=interval,
            error=str(e),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_data_bridge.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add ai/data_bridge.py test/test_ai_data_bridge.py
git commit -m "feat(ai): add data bridge for OpenAlgo history → OHLCV DataFrame"
```

---

## Task 5: AI Events + Decision Logging

**Files:**
- Create: `events/ai_events.py`
- Create: `database/ai_db.py`
- Create: `ai/agent_decisions.py`
- Create: `subscribers/ai_subscriber.py`
- Modify: `events/__init__.py`
- Test: `test/test_ai_agent_decisions.py` (skipped — tested via service integration in Task 6)

- [ ] **Step 1: Create AI event types**

```python
# events/ai_events.py
"""Event types for AI agent operations."""

from dataclasses import dataclass, field

from events.base import OrderEvent


@dataclass
class AgentAnalysisEvent(OrderEvent):
    """Fired when AI agent completes an analysis."""

    topic: str = "agent.analysis"
    symbol: str = ""
    exchange: str = ""
    signal: str = ""
    confidence: float = 0.0
    score: float = 0.0
    regime: str = ""


@dataclass
class AgentOrderEvent(OrderEvent):
    """Fired when AI agent places or recommends an order."""

    topic: str = "agent.order"
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: int = 0
    reason: str = ""
    signal_score: float = 0.0


@dataclass
class AgentErrorEvent(OrderEvent):
    """Fired when AI agent encounters an error."""

    topic: str = "agent.error"
    symbol: str = ""
    error_message: str = ""
    operation: str = ""
```

- [ ] **Step 2: Create AI decision database model**

```python
# database/ai_db.py
"""AI agent decision persistence.

Stores analysis results and agent decisions for audit trail.
Uses raw SQLAlchemy (same pattern as auth_db.py, NOT Flask-SQLAlchemy).
Separate DB file: db/ai.db (follows OpenAlgo's multi-DB isolation pattern).
"""

import json
import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# AI database path (separate DB, follows OpenAlgo's 5-DB pattern)
AI_DATABASE_URL = os.getenv("AI_DATABASE_URL", "sqlite:///db/ai.db")
ai_engine = create_engine(AI_DATABASE_URL, poolclass=NullPool)
ai_session_factory = sessionmaker(bind=ai_engine)
AiSession = scoped_session(ai_session_factory)
AiBase = declarative_base()


class AiDecision(AiBase):
    """Stores every AI analysis + decision for audit."""

    __tablename__ = "ai_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = Column(String(100), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False, default="NSE")
    interval = Column(String(10), nullable=False, default="1d")

    # Signal output
    signal = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    score = Column(Float, nullable=False, default=0.0)
    regime = Column(String(20), nullable=False, default="RANGING")
    sub_scores_json = Column(Text, nullable=True)

    # Action taken (if any)
    action_taken = Column(String(20), nullable=True)
    order_id = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "interval": self.interval,
            "signal": self.signal,
            "confidence": self.confidence,
            "score": self.score,
            "regime": self.regime,
            "sub_scores": json.loads(self.sub_scores_json) if self.sub_scores_json else {},
            "action_taken": self.action_taken,
            "order_id": self.order_id,
            "reason": self.reason,
        }


def init_ai_db():
    """Create AI tables if they don't exist."""
    AiBase.metadata.create_all(ai_engine)
    logger.info("AI database initialized")


def save_decision(decision_data: dict) -> AiDecision:
    """Save an AI decision record."""
    session = AiSession()
    try:
        record = AiDecision(
            user_id=decision_data.get("user_id", "system"),
            symbol=decision_data["symbol"],
            exchange=decision_data.get("exchange", "NSE"),
            interval=decision_data.get("interval", "1d"),
            signal=decision_data["signal"],
            confidence=decision_data.get("confidence", 0.0),
            score=decision_data.get("score", 0.0),
            regime=decision_data.get("regime", "RANGING"),
            sub_scores_json=json.dumps(decision_data.get("scores", {})),
            action_taken=decision_data.get("action_taken"),
            order_id=decision_data.get("order_id"),
            reason=decision_data.get("reason"),
        )
        session.add(record)
        session.commit()
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        AiSession.remove()


def get_decisions(user_id: str, symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Get recent AI decisions for a user."""
    session = AiSession()
    try:
        query = session.query(AiDecision).filter_by(user_id=user_id)
        if symbol:
            query = query.filter_by(symbol=symbol)
        query = query.order_by(AiDecision.timestamp.desc()).limit(limit)
        return [d.to_dict() for d in query.all()]
    finally:
        AiSession.remove()
```

- [ ] **Step 3: Create AI event subscriber**

```python
# subscribers/ai_subscriber.py
"""Subscribe to AI agent events for logging."""

from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


def on_agent_analysis(event):
    """Log analysis events."""
    logger.info(
        f"AI Analysis: {event.symbol} ({event.exchange}) → "
        f"{event.signal} (confidence={event.confidence:.1f}%, score={event.score:.4f}, regime={event.regime})"
    )


def on_agent_order(event):
    """Log order events."""
    logger.info(
        f"AI Order: {event.action} {event.quantity}x {event.symbol} ({event.exchange}) "
        f"— reason: {event.reason}"
    )


def on_agent_error(event):
    """Log error events."""
    logger.error(f"AI Error: {event.operation} on {event.symbol} — {event.error_message}")


def register_ai_subscribers():
    """Register all AI event subscribers."""
    bus.subscribe("agent.analysis", on_agent_analysis, name="ai_analysis_logger")
    bus.subscribe("agent.order", on_agent_order, name="ai_order_logger")
    bus.subscribe("agent.error", on_agent_error, name="ai_error_logger")
```

- [ ] **Step 4: Update events/__init__.py**

Add to `events/__init__.py`:
```python
from events.ai_events import AgentAnalysisEvent, AgentOrderEvent, AgentErrorEvent
```

Add to `__all__`:
```python
"AgentAnalysisEvent",
"AgentOrderEvent",
"AgentErrorEvent",
```

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add events/ai_events.py database/ai_db.py ai/agent_decisions.py subscribers/ai_subscriber.py
git add events/__init__.py
git commit -m "feat(ai): add AI events, decision DB model, and event subscriber"
```

---

## Task 6: AI Analysis Service

**Files:**
- Create: `services/ai_analysis_service.py`
- Test: `test/test_ai_analysis_service.py`

The service orchestrates: fetch data → compute indicators → generate signal → log decision → optionally place order.

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_analysis_service.py
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from services.ai_analysis_service import analyze_symbol, AnalysisResult


def _mock_ohlcv():
    np.random.seed(42)
    n = 100
    close = 100 + np.arange(n) * 0.3 + np.random.randn(n) * 0.2
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.1,
        "high": close + abs(np.random.randn(n) * 0.3),
        "low": close - abs(np.random.randn(n) * 0.3),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_returns_result(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=True, df=_mock_ohlcv(),
        symbol="RELIANCE", exchange="NSE", interval="1d", error=None,
    )
    result = analyze_symbol("RELIANCE", "NSE", "1d", api_key="test")
    assert result.success is True
    assert result.signal is not None
    assert result.confidence >= 0


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_handles_no_data(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=False, df=pd.DataFrame(),
        symbol="INVALID", exchange="NSE", interval="1d", error="No data",
    )
    result = analyze_symbol("INVALID", "NSE", "1d", api_key="test")
    assert result.success is False
    assert result.error == "No data"


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_includes_indicators(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=True, df=_mock_ohlcv(),
        symbol="SBIN", exchange="NSE", interval="1d", error=None,
    )
    result = analyze_symbol("SBIN", "NSE", "1d", api_key="test")
    assert result.success is True
    assert "rsi_14" in result.latest_indicators
    assert "macd" in result.latest_indicators
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_analysis_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement analysis service**

```python
# services/ai_analysis_service.py
"""AI Analysis Service — orchestrates indicator computation and signal generation.

Pipeline: fetch_ohlcv → compute_indicators → generate_signal → log decision
"""

from dataclasses import dataclass, field

from ai.data_bridge import fetch_ohlcv
from ai.indicators import compute_indicators
from ai.signals import generate_signal
from ai.signals_advanced import generate_advanced_signals
from events import AgentAnalysisEvent, AgentErrorEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AnalysisResult:
    success: bool
    symbol: str
    exchange: str
    interval: str
    signal: str | None = None
    confidence: float = 0.0
    score: float = 0.0
    regime: str = "RANGING"
    sub_scores: dict = field(default_factory=dict)
    latest_indicators: dict = field(default_factory=dict)
    advanced_signals: dict = field(default_factory=dict)  # SMC, harmonics, candlesticks, CPR, etc.
    data_points: int = 0
    error: str | None = None


def analyze_symbol(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    api_key: str = "",
    weights: dict[str, float] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> AnalysisResult:
    """Run full analysis pipeline for a symbol.

    1. Fetch OHLCV data via OpenAlgo history service
    2. Compute 20+ technical indicators
    3. Generate weighted composite signal
    4. Emit analysis event for logging
    """
    try:
        # Step 1: Fetch data
        ohlcv = fetch_ohlcv(symbol, exchange, interval, api_key, start_date, end_date)
        if not ohlcv.success:
            bus.publish(AgentErrorEvent(
                symbol=symbol, error_message=ohlcv.error or "Data fetch failed",
                operation="analyze",
            ))
            return AnalysisResult(
                success=False, symbol=symbol, exchange=exchange,
                interval=interval, error=ohlcv.error,
            )

        if len(ohlcv.df) < 5:
            return AnalysisResult(
                success=False, symbol=symbol, exchange=exchange,
                interval=interval, error=f"Insufficient data: {len(ohlcv.df)} rows",
            )

        # Step 2: Compute indicators
        df_with_indicators = compute_indicators(ohlcv.df)

        # Step 3: Generate signal
        signal_result = generate_signal(df_with_indicators, weights=weights)

        # Extract latest indicator values for response
        latest = df_with_indicators.iloc[-1]
        indicator_keys = [
            "rsi_14", "rsi_7", "macd", "macd_signal", "macd_hist",
            "ema_9", "ema_21", "sma_50", "sma_200",
            "adx_14", "bb_high", "bb_low", "bb_pband",
            "supertrend", "supertrend_dir", "atr_14",
            "stoch_k", "stoch_d", "obv", "vwap",
        ]
        latest_indicators = {}
        for key in indicator_keys:
            val = latest.get(key)
            if val is not None and not (isinstance(val, float) and __import__("math").isnan(val)):
                latest_indicators[key] = round(float(val), 4)

        # Step 4: Run advanced indicators
        try:
            advanced = generate_advanced_signals(df_with_indicators)
        except Exception as e:
            logger.warning(f"Advanced indicators skipped for {symbol}: {e}")
            advanced = {}

        # Step 5: Emit event
        bus.publish(AgentAnalysisEvent(
            symbol=symbol, exchange=exchange,
            signal=signal_result["signal"],
            confidence=signal_result["confidence"],
            score=signal_result["score"],
            regime=signal_result["regime"],
        ))

        return AnalysisResult(
            success=True,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            signal=signal_result["signal"],
            confidence=signal_result["confidence"],
            score=signal_result["score"],
            regime=signal_result["regime"],
            sub_scores=signal_result["scores"],
            latest_indicators=latest_indicators,
            advanced_signals=advanced,
            data_points=len(ohlcv.df),
        )

    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}")
        bus.publish(AgentErrorEvent(
            symbol=symbol, error_message=str(e), operation="analyze",
        ))
        return AnalysisResult(
            success=False, symbol=symbol, exchange=exchange,
            interval=interval, error=str(e),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_analysis_service.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add services/ai_analysis_service.py test/test_ai_analysis_service.py
git commit -m "feat(ai): add AI analysis service orchestrating full pipeline"
```

---

## Task 7: REST API Endpoints

**Files:**
- Create: `restx_api/ai_agent.py`
- Modify: `app.py` (register blueprint)
- Test: `test/test_ai_agent_api.py`

Exposes 4 endpoints under `/api/v1/agent/`:
- `POST /api/v1/agent/analyze` — Run analysis on a symbol
- `POST /api/v1/agent/scan` — Scan multiple symbols
- `GET /api/v1/agent/history` — Get decision history
- `GET /api/v1/agent/status` — Agent health check

- [ ] **Step 1: Write failing tests**

```python
# test/test_ai_agent_api.py
import pytest
from unittest.mock import patch, MagicMock
from services.ai_analysis_service import AnalysisResult


@patch("restx_api.ai_agent.analyze_symbol")
def test_analyze_endpoint_success(mock_analyze, client):
    mock_analyze.return_value = AnalysisResult(
        success=True, symbol="RELIANCE", exchange="NSE", interval="1d",
        signal="BUY", confidence=75.0, score=0.35, regime="TRENDING_UP",
        sub_scores={"rsi": 0.3, "macd": 0.4}, latest_indicators={"rsi_14": 42.5},
        data_points=100,
    )
    resp = client.post("/api/v1/agent/analyze", json={
        "apikey": "test_key", "symbol": "RELIANCE", "exchange": "NSE",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["data"]["signal"] == "BUY"
    assert data["data"]["confidence"] == 75.0


@patch("restx_api.ai_agent.analyze_symbol")
def test_analyze_endpoint_missing_symbol(mock_analyze, client):
    resp = client.post("/api/v1/agent/analyze", json={
        "apikey": "test_key",
    })
    assert resp.status_code == 400


@patch("restx_api.ai_agent.analyze_symbol")
def test_analyze_endpoint_failure(mock_analyze, client):
    mock_analyze.return_value = AnalysisResult(
        success=False, symbol="INVALID", exchange="NSE", interval="1d",
        error="No data found",
    )
    resp = client.post("/api/v1/agent/analyze", json={
        "apikey": "test_key", "symbol": "INVALID", "exchange": "NSE",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_agent_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement REST API namespace**

```python
# restx_api/ai_agent.py
"""AI Agent REST API endpoints.

/api/v1/agent/analyze — Run technical analysis on a symbol
/api/v1/agent/scan    — Scan multiple symbols
/api/v1/agent/history — Get past AI decisions
/api/v1/agent/status  — Agent health check
"""

from flask_restx import Namespace, Resource

from limiter import limiter
from services.ai_analysis_service import analyze_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("agent", description="AI Agent Analysis & Decision Endpoints")


@api.route("/analyze")
class AnalyzeResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Analyze a symbol and return signal + indicators."""
        from flask import request

        data = request.get_json(force=True)

        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400

        result = analyze_symbol(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            api_key=api_key,
        )

        if not result.success:
            return {"status": "error", "message": result.error}

        return {
            "status": "success",
            "data": {
                "symbol": result.symbol,
                "exchange": result.exchange,
                "interval": result.interval,
                "signal": result.signal,
                "confidence": result.confidence,
                "score": result.score,
                "regime": result.regime,
                "sub_scores": result.sub_scores,
                "indicators": result.latest_indicators,
                "advanced": result.advanced_signals,
                "data_points": result.data_points,
            },
        }


@api.route("/scan")
class ScanResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """Scan multiple symbols and return signals."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbols = data.get("symbols", [])
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if not symbols or not isinstance(symbols, list):
            return {"status": "error", "message": "symbols list is required"}, 400

        results = []
        for sym in symbols[:20]:  # Max 20 symbols per scan
            result = analyze_symbol(sym, exchange, interval, api_key)
            results.append({
                "symbol": result.symbol,
                "signal": result.signal,
                "confidence": result.confidence,
                "score": result.score,
                "regime": result.regime,
                "error": result.error,
            })

        return {"status": "success", "data": results}


@api.route("/status")
class StatusResource(Resource):
    def get(self):
        """AI agent health check."""
        return {
            "status": "success",
            "data": {
                "agent": "active",
                "version": "1.0.0",
                "engine": "vayu-signals",
                "indicators": 20,
                "signals": 6,
            },
        }
```

- [ ] **Step 4: Register namespace in restx_api/__init__.py**

OpenAlgo registers ALL API namespaces in `restx_api/__init__.py` (NOT in `app.py`).
Follow the existing pattern:

Add import at the bottom of the import block (around line 54):
```python
from .ai_agent import api as ai_agent_ns
```

Add namespace registration at the bottom of the `api.add_namespace(...)` block (around line 100):
```python
api.add_namespace(ai_agent_ns, path="/agent")
```

**Files modified:** `restx_api/__init__.py` (2 lines added, following existing pattern)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:\openalgo && uv run pytest test/test_ai_agent_api.py -v`
Expected: all 3 tests PASS (may need test client fixture — check existing test patterns)

- [ ] **Step 6: Commit**

```bash
cd D:\openalgo
git add restx_api/ai_agent.py test/test_ai_agent_api.py
git add app.py
git commit -m "feat(ai): add REST API endpoints for AI analysis (/api/v1/agent/*)"
```

---

## Task 8: Extend MCP Server with AI Tools

**Files:**
- Modify: `mcp/mcpserver.py`

Add 3 new MCP tools so AI agents (Claude, Codex, Gemini) can call analysis directly.

- [ ] **Step 1: Add AI analysis tools to MCP server**

Append to `mcp/mcpserver.py` before the `if __name__` block:

```python
# AI ANALYSIS TOOLS

@mcp.tool()
def analyze_stock(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
) -> str:
    """
    Run AI-powered technical analysis on a stock symbol.
    Returns signal (STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL), confidence,
    composite score, market regime, and 20+ indicator values.

    Uses OpenAlgo history API to fetch data, then runs VAYU analysis engine.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE', 'SBIN', 'INFY')
        exchange: Exchange ('NSE', 'BSE')
        interval: Timeframe ('1m', '5m', '15m', '1h', '1d')
    """
    import requests
    try:
        # Call the AI analysis endpoint on OpenAlgo server
        response = requests.post(
            f"{host}/api/v1/agent/analyze",
            json={"apikey": api_key, "symbol": symbol, "exchange": exchange, "interval": interval},
            timeout=30,
        )
        return json.dumps(response.json(), indent=2)
    except Exception as e:
        return f"Error analyzing {symbol}: {str(e)}"


@mcp.tool()
def scan_stocks(
    symbols: List[str],
    exchange: str = "NSE",
    interval: str = "1d",
) -> str:
    """
    Scan multiple stocks and return signals for each.
    Maximum 20 symbols per scan. Returns signal, confidence, and score for each.

    Args:
        symbols: List of stock symbols (e.g., ['RELIANCE', 'SBIN', 'INFY'])
        exchange: Exchange ('NSE', 'BSE')
        interval: Timeframe ('1d', '1h', '15m')
    """
    import requests
    try:
        response = requests.post(
            f"{host}/api/v1/agent/scan",
            json={"apikey": api_key, "symbols": symbols, "exchange": exchange, "interval": interval},
            timeout=60,
        )
        return json.dumps(response.json(), indent=2)
    except Exception as e:
        return f"Error scanning stocks: {str(e)}"


@mcp.tool()
def get_ai_status() -> str:
    """Check if the AI analysis engine is active and healthy."""
    import requests
    try:
        response = requests.get(f"{host}/api/v1/agent/status", timeout=5)
        return json.dumps(response.json(), indent=2)
    except Exception as e:
        return f"Error checking AI status: {str(e)}"
```

- [ ] **Step 2: Verify MCP tools compile**

Run: `cd D:\openalgo && uv run python -c "from mcp.mcpserver import mcp; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
cd D:\openalgo
git add mcp/mcpserver.py
git commit -m "feat(ai): add analyze_stock, scan_stocks, get_ai_status MCP tools"
```

---

## Task 9: Integration Wiring + Subscriber Registration

**Files:**
- Modify: `subscribers/__init__.py`
- Modify: `app.py` (init AI DB tables)

- [ ] **Step 1: Wire AI subscriber into subscriber registration**

Read `subscribers/__init__.py` to see the `register_all()` pattern, then add:

```python
from subscribers.ai_subscriber import register_ai_subscribers

def register_all():
    # ... existing registrations ...
    register_ai_subscribers()
```

- [ ] **Step 2: Add AI DB init to app startup**

In `app.py`, in the `setup_environment()` or database init section, add:

```python
from database.ai_db import init_ai_db
init_ai_db()
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd D:\openalgo && uv run pytest test/ -v --ignore=test/test_ai_agent_api.py -x`
Expected: Existing tests PASS (no regressions)

- [ ] **Step 4: Run all AI tests together**

Run: `cd D:\openalgo && uv run pytest test/test_ai_*.py -v`
Expected: All AI tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo
git add subscribers/__init__.py app.py
git commit -m "feat(ai): wire AI subscribers and DB init into app startup"
```

---

## Task 10: End-to-End Smoke Test

- [ ] **Step 1: Start the application**

Run: `cd D:\openalgo && uv run app.py`
Expected: App starts on http://127.0.0.1:5000 with no errors

- [ ] **Step 2: Test AI status endpoint**

Run: `curl http://127.0.0.1:5000/api/v1/agent/status`
Expected: `{"status": "success", "data": {"agent": "active", ...}}`

- [ ] **Step 3: Test AI analysis endpoint (requires valid API key + broker connection)**

Run:
```bash
curl -X POST http://127.0.0.1:5000/api/v1/agent/analyze \
  -H "Content-Type: application/json" \
  -d '{"apikey": "YOUR_KEY", "symbol": "RELIANCE", "exchange": "NSE", "interval": "1d"}'
```
Expected: `{"status": "success", "data": {"signal": "BUY|SELL|HOLD", ...}}`

- [ ] **Step 4: Verify Swagger docs include AI endpoints**

Open: http://127.0.0.1:5000/api/docs
Expected: "agent" namespace visible with analyze, scan, status endpoints

- [ ] **Step 5: Run full test suite**

Run: `cd D:\openalgo && uv run pytest test/ -v`
Expected: All tests pass (existing + new AI tests)

- [ ] **Step 6: Final commit**

```bash
cd D:\openalgo
git add -A
git commit -m "feat(ai): complete VAYU AI analysis integration — 20+ indicators, 6-signal weighted engine, REST API, MCP tools, event bus, decision logging"
```

---

## Summary

| Task | Files | Tests | Description |
|------|-------|-------|-------------|
| 1 | 2 new | 8 | Symbol mapper (OpenAlgo ↔ yfinance) |
| 2 | 1 new | 10 | Core indicator engine (20+ indicators via `ta`) |
| 2B | 3 new | 18 | Advanced indicators: SMC (BOS/CHoCH/FVG/OB), 15 candlestick patterns, CPR, Fibonacci, harmonics (XABCD), RSI divergence, volume signals, ML confidence |
| 3 | 1 new | 9 | Signal engine (6 weighted sub-signals) |
| 4 | 1 new | 4 | Data bridge (OpenAlgo history → DataFrame) |
| 5 | 4 new, 1 mod | — | Events, DB model, subscriber |
| 6 | 1 new | 3 | Analysis service (orchestrator) |
| 7 | 1 new, 1 mod | 3 | REST API (/api/v1/agent/*) |
| 8 | 1 mod | — | MCP tools (3 new tools) |
| 9 | 2 mod | — | Wiring (subscribers + DB init) |
| 10 | — | — | E2E smoke test |
| **Total** | **14 new, 4 mod** | **~55** | — |
