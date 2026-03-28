# Phase 2: Spoon-Feed Trader — Complete Trading Assistant

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Use CCGL:** architecture-compare workflow for design, code-review-fix-verify for implementation.

**Goal:** Transform the AI Analyzer into a complete trading assistant that shows indicators on the chart, gives entry/SL/target for every signal, includes risk calculation, and integrates 47 custom + 600+ opensource indicators — all spoon-feeding the trader with exact actionable data.

**Architecture:** An indicator registry loads all 57 Python indicator files from `ai/indicators_lib/`. Each indicator's `calculate_indicators(df)` function is called dynamically. Results are returned as chart overlay data (price lines, bands, markers) and trade setups (entry/SL/target per pattern). The frontend renders overlays on the TradingView Lightweight Chart and shows a unified "What To Do" decision card.

**Tech Stack:** Python (pandas, ta, custom indicators), React 19, TradingView Lightweight Charts v5, TypeScript

**Indicator Library Location:** `D:\openalgo\ai\indicators_lib\`
- `custom/` — 47 files from `D:\test1\self indc\`
- `opensource/` — smart-money-concepts, finta, streaming_indicators

---

## File Structure

### New Backend Files
```
D:\openalgo\ai\
├── indicator_registry.py          # Dynamic loader for all indicators
├── chart_data_builder.py          # Builds chart overlay data (lines, bands, markers)
└── decision_engine.py             # "What To Do" — unified recommendation with entry/SL/target
```

### New Frontend Files
```
D:\openalgo\frontend\src\
├── components\ai-analysis\
│   ├── ChartWithIndicators.tsx    # Full chart with indicator overlays + entry/SL/target lines
│   ├── DecisionCard.tsx           # "WHAT TO DO" card — single clear recommendation
│   ├── RiskCalculator.tsx         # Account balance → position size → max loss
│   ├── IndicatorSelector.tsx      # Toggle which indicators to show on chart
│   ├── ScanResultRow.tsx          # Enhanced scanner row with mini entry/SL/target
│   └── PatternTradeSetup.tsx      # Per-pattern trade setup (if engulfing, buy at X)
├── types\
│   └── chart-data.ts              # Chart overlay types (line, band, marker)
```

### Modified Files
```
D:\openalgo\
├── services\ai_analysis_service.py   # Add chart overlays + decision to response
├── restx_api\ai_agent.py             # Add chart_overlays + decision to API
├── frontend\src\pages\AIAnalyzer.tsx  # Restructure with new components
├── frontend\src\types\ai-analysis.ts  # Add overlay + decision types
```

---

## Task 1: Indicator Registry — Dynamic Loader

**Files:**
- Create: `ai/indicator_registry.py`
- Test: `test/test_ai_indicator_registry.py`

The registry discovers all `calculate_indicators(df)` functions in `ai/indicators_lib/custom/*.py` and makes them callable by name.

```python
# ai/indicator_registry.py
"""Dynamic indicator registry — loads all custom indicators from indicators_lib/.

Each indicator file must have a calculate_indicators(df) function.
Returns DataFrame with added columns.
"""
import importlib
import importlib.util
import os
from pathlib import Path
from dataclasses import dataclass, field
from utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class IndicatorInfo:
    id: str              # "bahai_reversal_points"
    name: str            # "Bahai Reversal Points"
    file_path: str       # Full path to .py file
    category: str        # "custom" or "opensource"
    has_signals: bool    # True if output has Buy/Sell columns
    output_columns: list[str] = field(default_factory=list)

class IndicatorRegistry:
    def __init__(self):
        self._indicators: dict[str, IndicatorInfo] = {}
        self._modules: dict[str, object] = {}

    def discover(self, base_dir: str = None):
        """Scan indicators_lib/ and register all indicators."""
        if base_dir is None:
            base_dir = str(Path(__file__).parent / "indicators_lib" / "custom")

        if not os.path.exists(base_dir):
            logger.warning(f"Indicator dir not found: {base_dir}")
            return

        for fname in sorted(os.listdir(base_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(base_dir, fname)
            indicator_id = fname[:-3]  # Remove .py

            try:
                spec = importlib.util.spec_from_file_location(f"custom_ind.{indicator_id}", fpath)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, "calculate_indicators"):
                    name = indicator_id.replace("_", " ").title()
                    self._indicators[indicator_id] = IndicatorInfo(
                        id=indicator_id, name=name, file_path=fpath,
                        category="custom", has_signals=True,
                    )
                    self._modules[indicator_id] = mod
                    logger.debug(f"Registered indicator: {indicator_id}")
            except Exception as e:
                logger.debug(f"Skipped indicator {indicator_id}: {e}")

    def list_all(self) -> list[IndicatorInfo]:
        return list(self._indicators.values())

    def get(self, indicator_id: str) -> IndicatorInfo | None:
        return self._indicators.get(indicator_id)

    def compute(self, indicator_id: str, df) -> dict:
        """Run a specific indicator on OHLCV data.
        Returns dict with output columns and their values.
        """
        mod = self._modules.get(indicator_id)
        if not mod:
            return {"error": f"Indicator not found: {indicator_id}"}

        try:
            result_df = mod.calculate_indicators(df.copy())
            # Find new columns added by the indicator
            new_cols = [c for c in result_df.columns if c not in df.columns]
            latest = result_df.iloc[-1]
            output = {}
            for col in new_cols:
                val = latest[col]
                if val is not None and not (isinstance(val, float) and __import__("math").isnan(val)):
                    output[col] = val
            return {"columns": new_cols, "latest": output}
        except Exception as e:
            return {"error": str(e)}

    def compute_all_signals(self, df) -> list[dict]:
        """Run all registered indicators and collect signals.
        Returns list of {indicator_id, signals: {column: value}} for signals that fired.
        """
        results = []
        for ind_id, mod in self._modules.items():
            try:
                result_df = mod.calculate_indicators(df.copy())
                new_cols = [c for c in result_df.columns if c not in df.columns]
                latest = result_df.iloc[-1]

                # Check for signal columns (Buy, Sell, bullish, bearish)
                signals = {}
                for col in new_cols:
                    val = latest.get(col)
                    if val and val != 0 and str(col).lower() in [
                        c for c in [col.lower()]
                        if any(s in c for s in ["buy", "sell", "bullish", "bearish", "signal", "long", "short"])
                    ]:
                        signals[col] = val

                if signals:
                    results.append({
                        "indicator_id": ind_id,
                        "name": self._indicators[ind_id].name,
                        "signals": signals,
                    })
            except Exception:
                pass
        return results

# Global singleton
_registry = IndicatorRegistry()

def get_indicator_registry() -> IndicatorRegistry:
    return _registry

def init_indicator_registry():
    """Call at app startup to discover all indicators."""
    _registry.discover()
    logger.info(f"Indicator registry: {len(_registry._indicators)} custom indicators loaded")
```

---

## Task 2: Chart Data Builder

**Files:**
- Create: `ai/chart_data_builder.py`

Converts indicator values into chart overlay format for TradingView Lightweight Charts.

```python
# ai/chart_data_builder.py
"""Builds chart overlay data from indicator results.

Outputs:
- lines: [{time, value}] for EMA, SMA, Supertrend
- bands: [{time, upper, lower}] for Bollinger, Keltner
- markers: [{time, position, shape, color, text}] for signals
- levels: [{price, color, label}] for CPR, Fibonacci
"""

def build_chart_overlays(df, indicators: dict, cpr: dict = None, trade_setup: dict = None) -> dict:
    """Build all chart overlay data from an indicator-enriched DataFrame."""
    overlays = {"lines": [], "bands": [], "markers": [], "levels": []}

    n = min(len(df), 200)
    chart_df = df.tail(n)

    # --- Lines: EMA, SMA, Supertrend ---
    for col, color, label in [
        ("ema_9", "#f59e0b", "EMA 9"),
        ("ema_21", "#3b82f6", "EMA 21"),
        ("sma_50", "#8b5cf6", "SMA 50"),
        ("supertrend", "#10b981", "Supertrend"),
    ]:
        if col in chart_df.columns:
            line_data = []
            for i, row in chart_df.iterrows():
                val = row.get(col)
                if val and not (isinstance(val, float) and __import__("math").isnan(val)):
                    line_data.append({"time": int(i), "value": round(float(val), 2)})
            if line_data:
                overlays["lines"].append({"id": col, "label": label, "color": color, "data": line_data})

    # --- Bands: Bollinger ---
    if "bb_high" in chart_df.columns and "bb_low" in chart_df.columns:
        band_data = []
        for i, row in chart_df.iterrows():
            bh = row.get("bb_high")
            bl = row.get("bb_low")
            if bh and bl and not (__import__("math").isnan(bh) or __import__("math").isnan(bl)):
                band_data.append({"time": int(i), "upper": round(float(bh), 2), "lower": round(float(bl), 2)})
        if band_data:
            overlays["bands"].append({"id": "bb", "label": "Bollinger Bands", "color": "#94a3b8", "data": band_data})

    # --- Levels: CPR, Trade Setup ---
    if cpr:
        for key, color in [("r3", "#ef4444"), ("r2", "#f87171"), ("r1", "#fb923c"),
                           ("tc", "#a78bfa"), ("pivot", "#3b82f6"), ("bc", "#a78bfa"),
                           ("s1", "#22c55e"), ("s2", "#4ade80"), ("s3", "#86efac")]:
            val = cpr.get(key)
            if val and val > 0:
                overlays["levels"].append({"price": round(float(val), 2), "color": color, "label": key.upper()})

    if trade_setup:
        if trade_setup.get("entry"):
            overlays["levels"].append({"price": trade_setup["entry"], "color": "#3b82f6", "label": "Entry"})
        if trade_setup.get("stop_loss"):
            overlays["levels"].append({"price": trade_setup["stop_loss"], "color": "#dc2626", "label": "SL"})
        if trade_setup.get("target_1"):
            overlays["levels"].append({"price": trade_setup["target_1"], "color": "#16a34a", "label": "T1"})
        if trade_setup.get("target_2"):
            overlays["levels"].append({"price": trade_setup["target_2"], "color": "#22c55e", "label": "T2"})

    return overlays
```

---

## Task 3: Decision Engine — "What To Do"

**Files:**
- Create: `ai/decision_engine.py`

Single clear recommendation combining all signals.

```python
# ai/decision_engine.py
"""Decision Engine — produces one clear "What To Do" recommendation.

Combines: signal score + confidence + trend + momentum + OI + pattern alerts + ML confidence
into a single actionable recommendation with entry/SL/target.
"""

from dataclasses import dataclass

@dataclass
class TradingDecision:
    action: str          # "BUY NOW", "SELL NOW", "WAIT", "AVOID"
    confidence_label: str  # "High Conviction", "Medium", "Low", "No Setup"
    entry: float
    stop_loss: float
    target: float
    quantity: int
    risk_amount: float
    risk_reward: float
    reason: str          # 1-2 sentence explanation
    risk_warning: str    # Risk disclosure
    supporting_signals: list[str]  # Which indicators agree
    opposing_signals: list[str]    # Which indicators disagree
    score: float         # Overall decision score 0-100

def make_decision(
    signal: str, score: float, confidence: float,
    trend_direction: str, momentum_bias: str,
    trade_setup: dict, advanced_signals: dict,
    ml_buy: float, ml_sell: float,
    account_balance: float = 100000,
    risk_percent: float = 1.0,
) -> TradingDecision:
    """Make a single trading decision from all available data."""

    is_buy = signal in ("STRONG_BUY", "BUY")
    is_sell = signal in ("STRONG_SELL", "SELL")
    is_hold = signal == "HOLD"

    # Count supporting/opposing signals
    supporting = []
    opposing = []

    if trend_direction == "bullish" and is_buy: supporting.append("Trend: Bullish")
    elif trend_direction == "bearish" and is_sell: supporting.append("Trend: Bearish")
    elif trend_direction != "neutral": opposing.append(f"Trend: {trend_direction}")

    if momentum_bias == "bullish" and is_buy: supporting.append("Momentum: Bullish")
    elif momentum_bias == "bearish" and is_sell: supporting.append("Momentum: Bearish")
    elif momentum_bias != "neutral": opposing.append(f"Momentum: {momentum_bias}")

    if ml_buy > 60 and is_buy: supporting.append(f"ML: Buy {ml_buy:.0f}%")
    elif ml_sell > 60 and is_sell: supporting.append(f"ML: Sell {ml_sell:.0f}%")

    smc = advanced_signals.get("smc", {})
    if any("bullish" in k for k in smc): supporting.append("SMC: Bullish structure")
    if any("bearish" in k for k in smc):
        if is_sell: supporting.append("SMC: Bearish structure")
        else: opposing.append("SMC: Bearish structure")

    candlestick = advanced_signals.get("candlestick", [])
    if candlestick: supporting.append(f"Candlestick: {', '.join(candlestick[:2])}")

    diverg = advanced_signals.get("divergence", {})
    if diverg.get("rsi_bullish") and is_buy: supporting.append("RSI Bullish Divergence")
    if diverg.get("rsi_bearish") and is_sell: supporting.append("RSI Bearish Divergence")

    # Decision scoring
    agreement = len(supporting) / max(len(supporting) + len(opposing), 1)
    decision_score = confidence * 0.4 + agreement * 100 * 0.3 + abs(score) * 100 * 0.3
    decision_score = min(decision_score, 100)

    # Action
    if is_hold or decision_score < 30:
        action = "WAIT"
        conf_label = "No Setup"
    elif decision_score > 70:
        action = "BUY NOW" if is_buy else "SELL NOW"
        conf_label = "High Conviction"
    elif decision_score > 50:
        action = "BUY NOW" if is_buy else "SELL NOW"
        conf_label = "Medium Conviction"
    else:
        action = "BUY NOW" if is_buy else "SELL NOW"
        conf_label = "Low Conviction"

    # Trade params from setup
    entry = trade_setup.get("entry", 0)
    sl = trade_setup.get("stop_loss", 0)
    target = trade_setup.get("target_1", 0)
    rr = trade_setup.get("risk_reward_1", 0)
    qty = trade_setup.get("suggested_qty", 0)
    risk = trade_setup.get("risk_amount", 0)

    # Risk-based quantity from account balance
    if entry > 0 and sl > 0 and account_balance > 0:
        max_risk = account_balance * risk_percent / 100
        sl_distance = abs(entry - sl)
        if sl_distance > 0:
            qty = max(int(max_risk / sl_distance), 1)
            risk = qty * sl_distance

    # Reason
    if action == "WAIT":
        reason = f"No clear setup. Signal is {signal} with {confidence:.0f}% confidence. Wait for better entry."
    else:
        direction = "buying" if is_buy else "selling"
        reason = f"{conf_label} {direction} setup. {len(supporting)} signals agree, {len(opposing)} oppose. Score: {decision_score:.0f}/100."

    # Risk warning
    if rr < 1.5:
        risk_warning = "⚠️ Low R:R ratio — consider waiting for better entry"
    elif len(opposing) > len(supporting):
        risk_warning = "⚠️ More signals opposing than supporting — trade with caution"
    elif confidence < 40:
        risk_warning = "⚠️ Low confidence — use smaller position size"
    else:
        risk_warning = "✓ Setup looks reasonable — follow your risk management rules"

    return TradingDecision(
        action=action, confidence_label=conf_label,
        entry=round(entry, 2), stop_loss=round(sl, 2), target=round(target, 2),
        quantity=qty, risk_amount=round(risk, 2), risk_reward=round(rr, 2),
        reason=reason, risk_warning=risk_warning,
        supporting_signals=supporting, opposing_signals=opposing,
        score=round(decision_score, 1),
    )
```

---

## Task 4: Update API to Include Chart Overlays + Decision

Add `chart_overlays` and `decision` to the `/api/v1/agent/analyze` response.

**Modify:** `services/ai_analysis_service.py` — call `build_chart_overlays()` and `make_decision()`
**Modify:** `restx_api/ai_agent.py` — add fields to response

---

## Task 5: Frontend — ChartWithIndicators Component

Replace `MiniChart` with `ChartWithIndicators` that:
- Renders candlesticks
- Overlays EMA 9/21, SMA 50 as line series
- Overlays Bollinger Bands as area between upper/lower
- Shows Supertrend line (color changes on direction)
- Shows CPR pivot levels as horizontal price lines
- Shows Entry/SL/Target lines (colored, labeled)
- Has toggle buttons to show/hide each overlay

---

## Task 6: Frontend — DecisionCard Component

The "WHAT TO DO" card:
```
┌─────────────────────────────────────┐
│  🟢 BUY NOW — High Conviction      │
│  ──────────────────────────────────  │
│  Entry:  ₹1,413.60                  │
│  SL:     ₹1,397.80  (-1.1%)        │
│  Target: ₹1,429.40  (+1.1%)        │
│  ──────────────────────────────────  │
│  Qty: 63 shares | Risk: ₹1,000     │
│  R:R = 1:1.0                        │
│  ──────────────────────────────────  │
│  ✓ Trend Bullish  ✓ MACD Bullish   │
│  ✓ RSI Divergence  ✗ EMA Bearish   │
│  ──────────────────────────────────  │
│  ✓ Setup looks reasonable           │
│  ──────────────────────────────────  │
│  Score: 72/100                      │
│  [Place Order]                      │
└─────────────────────────────────────┘
```

---

## Task 7: Frontend — RiskCalculator Component

Inputs: Account balance, Risk % per trade
Shows: Max risk in ₹, suggested qty, position value, max loss scenario

---

## Task 8: Frontend — Enhanced Scanner

Each row shows: Symbol | Signal | Entry | SL | Target | R:R | Score
Click row → loads full analysis

---

## Task 9: Frontend — IndicatorSelector

Toggle panel listing all 47 custom indicators by name. Checked ones are computed and overlaid on chart.

---

## Task 10: Restructure AIAnalyzer Page

New layout:
```
┌─ AI Trading Intelligence ─── [RELIANCE] [NSE] [Daily] [🔍] ───────┐
│ 1413.10 +12.50 (+0.89%)  Bid:1413 Ask:1414 📶                    │
├── [Analysis] [Scanner] [History] ──────────────────────────────────┤
│                                                                     │
│ ┌─ WHAT TO DO ────────────────────────────────────────────────────┐│
│ │ 🟢 BUY NOW — High Conviction (72/100)                          ││
│ │ Entry: 1413.60 | SL: 1397.80 (-1.1%) | Target: 1429.40 (1:1) ││
│ │ Qty: 63 | Risk: ₹1,000 | [Place Order]                        ││
│ └──────────────────────────────────────────────────────────────────┘│
│                                                                     │
│ ┌─ Chart ─────────────────────────────┐ ┌─ Signals ──────────────┐│
│ │ [EMA✓] [SMA✓] [BB✓] [ST✓] [CPR✓]  │ │ ✓ Trend: Bullish      ││
│ │ ╔═══════════════════════════════╗   │ │ ✓ Momentum: Bullish   ││
│ │ ║  Candlestick chart with       ║   │ │ ✓ MACD: Bullish       ││
│ │ ║  EMA, BB, Supertrend overlays ║   │ │ ✗ EMA: Bearish cross  ││
│ │ ║  + Entry/SL/Target lines      ║   │ │ ✓ SMC: FVG Bullish    ││
│ │ ║  + CPR pivot levels           ║   │ │ ✓ RSI Divergence      ││
│ │ ╚═══════════════════════════════╝   │ │ ML: Buy 72% Sell 28%  ││
│ └─────────────────────────────────────┘ │ Risk: ₹1,000 (1%)     ││
│                                          └────────────────────────┘│
│ ┌─ Indicators ──────┐ ┌─ Patterns ──────┐ ┌─ AI Commentary ────┐ │
│ │ RSI(14): 51.28    │ │ FVG Bullish     │ │ 🤖 RELIANCE shows  │ │
│ │ MACD: 1.23        │ │ Doji detected   │ │ bullish setup...    │ │
│ │ ADX: 28.4         │ │ Fib at support  │ │ [Refresh]           │ │
│ └───────────────────┘ └─────────────────┘ └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Execution Plan via CCGL

### Workflow 1: Backend (Tasks 1-4)
```
Claude(code T1-T3) → Codex(review) → Claude(code T4) → Codex(verify tests)
```

### Workflow 2: Frontend (Tasks 5-10)
```
Gemini(design all components) → Claude(implement T5-T8) → Codex(review) → Claude(T9-T10) → Codex(build+test)
```

### Workflow 3: Integration + Polish
```
Claude(wire everything) → Codex(E2E test) → Gemini(UX review) → Codex(final)
```

---

## Summary

| Task | Files | Description |
|------|-------|-------------|
| 1 | 2 | Indicator Registry (dynamic loader for 47 custom indicators) |
| 2 | 1 | Chart Data Builder (overlay format for TradingView) |
| 3 | 1 | Decision Engine ("What To Do" recommendation) |
| 4 | 2 mod | API update (add overlays + decision to response) |
| 5 | 1 | ChartWithIndicators (full chart with overlays) |
| 6 | 1 | DecisionCard ("BUY NOW" with entry/SL/target) |
| 7 | 1 | RiskCalculator (account balance → qty → risk) |
| 8 | 1 | Enhanced Scanner (entry/SL/target per symbol) |
| 9 | 1 | IndicatorSelector (toggle custom indicators) |
| 10 | 1 mod | Restructured AIAnalyzer page |
| **Total** | **~12 files** | |
