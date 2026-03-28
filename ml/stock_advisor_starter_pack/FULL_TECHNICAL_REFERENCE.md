# RELIANCE Swing Bundle — Full Technical Reference
**Purpose:** Complete technical documentation for sharing with another AI agent to continue, audit, or improve this project.
**Date of experiment:** 2026-03-22
**Primary symbol:** RELIANCE (NSE India)
**Primary timeframe:** 15m bars

---

## TABLE OF CONTENTS
1. Project Architecture
2. Complete Data Flow (step by step)
3. Every Module Explained (with exact logic)
4. All Algorithms Used (with formulas)
5. The 25 Available Strategies and Their Role Tags
6. What We Ran and Exact Results
7. Parameter Optimization — Methodology and Results
8. VWAP BB Analysis — Why It Was Broken and How We Fixed It
9. Confluence Analysis — All 24 Combinations and Results
10. The 3 Recommended Configs
11. What the Backtest Engine Does (and does NOT do)
12. The Inference Pipeline (how a live recommendation is generated)
13. The Feedback Loop (daily retraining design)
14. Everything That Is Missing or Broken
15. Specific Improvements for Another AI to Implement
16. File Map — Every File and Its Purpose

---

## 1. PROJECT ARCHITECTURE

```
stock_advisor_starter_pack/
├── local_project/
│   ├── src/                  ← All Python implementation
│   │   ├── core/             ← Config, constants, interfaces
│   │   ├── data/             ← CSV loading, session filtering, timeframe alignment
│   │   ├── features/         ← Feature engineering, regime features, swing features
│   │   ├── labels/           ← Forward-return labeling (regime + setup)
│   │   ├── models/           ← Training: regime model, setup ranker, calibrator
│   │   ├── strategies/       ← Registry, loader, signal adapter, param space
│   │   ├── backtest/         ← Engine, metrics, cost model
│   │   ├── inference/        ← Load bundle, generate recommendation, trade plan
│   │   └── feedback/         ← Paper trade ingestion, daily retrain, promotion report
│   ├── configs/              ← YAML configs (reliance_swing.yaml etc.)
│   ├── scripts/              ← Runnable scripts (train, validate, optimize)
│   ├── tests/                ← pytest tests
│   └── examples/             ← Sample data and expected outputs
├── kaggle_kit/
│   ├── dataset_template/     ← Upload-ready folder structure for Kaggle
│   │   ├── market_data/      ← Parquet files go here (RELIANCE/15m.parquet etc.)
│   │   ├── strategies/       ← Strategy .py files go here
│   │   └── config/           ← YAML config files go here
│   ├── notebooks/            ← 5 skeleton notebooks (01-05) — STUBS ONLY, not implemented
│   └── exports/              ← Where downloaded Kaggle bundle goes
├── artifacts_template/
│   ├── models/
│   │   ├── candidate/        ← New trained bundle goes here first
│   │   └── active/           ← Promoted (validated) bundle lives here
│   └── reports/              ← All CSV/JSON outputs from training/analysis
└── docs/                     ← Operator guides
```

### External Dependencies
```
D:\TV_proj\output\reliance_timeframes\  ← Market data CSVs (source of truth)
D:\test1\                               ← Strategy .py files (read-only, never modified)
D:\test1\opensource_indicators\         ← Open-source indicator libraries (imported from source)
C:\Users\sakth\Desktop\vayu\.venv\     ← Python 3.11.9 virtual environment
```

### Python Dependencies Used
```
pandas       — all data manipulation
numpy        — array math in strategies
pickle       — model bundle serialization
json         — metadata/config files
pathlib      — cross-platform paths
dataclasses  — data structures
pytest       — test runner
requests     — vwap_bb fetches external VWAP data (blocked in training)
```

---

## 2. COMPLETE DATA FLOW

```
STEP 1: Load raw CSVs
  D:\TV_proj\output\reliance_timeframes\
    RELIANCE_15m_5029bars.csv   → primary frame (5,029 bars)
    RELIANCE_1hr_5568bars.csv   → confirmation frame 1
    RELIANCE_1day_7772bars.csv  → confirmation frame 2
  ↓
  load_symbol_timeframes() → dict[timeframe → TimeframeDataset]
  - Reads CSV, adds symbol/timeframe columns
  - Converts datetime to Asia/Kolkata timezone
  - Filters to Indian market hours 09:15–15:30
    (skipped for 1day, 1month — daily bars have no intraday time)
  - Converts timestamp to int (Unix seconds)

STEP 2: Align timeframes
  align_higher_timeframes(primary_15m, [1hr_frame, 1day_frame])
  - Uses pd.merge_asof(direction="backward") for each higher TF
  - Every 15m bar gets the most recent 1hr and 1day OHLCV appended as:
      open_1hr, high_1hr, low_1hr, close_1hr, volume_1hr
      open_1day, high_1day, low_1day, close_1day, volume_1day
  - Result: one wide DataFrame with all timeframe data per bar

STEP 3: Build regime features (for regime model input)
  build_regime_features(aligned_df) adds:
    return_1        = close.pct_change(1)
    return_5        = close.pct_change(5)
    volatility_10   = return_1.rolling(10).std()
    volume_zscore_10 = (volume - volume.rolling(10).mean()) / volume.rolling(10).std()
    close_ma_5      = close.rolling(5).mean()
    close_ma_20     = close.rolling(20).mean()
    ma_spread       = close_ma_5 - close_ma_20

STEP 4: Label regime (for training the regime model)
  build_regime_labels(feature_df, lookahead_bars=5, threshold=0.002)
    forward_return = close.shift(-5) / close - 1
    label = "bull"  if forward_return > 0.002
    label = "bear"  if forward_return < -0.002
    label = "flat"  otherwise

STEP 5: For each selected strategy — run on all 3 timeframes
  wrapper.run(primary_df, params={})    → StrategyRunResult
  wrapper.run(1hr_df, params={})        → StrategyRunResult (confirmation)
  wrapper.run(1day_df, params={})       → StrategyRunResult (confirmation)

  Each run calls module.calculate_indicators(df, **params)
  then normalize_strategy_output() reads the returned DataFrame columns
  and extracts signal (+1/-1/0), signal_strength (0-1), trend_state (+1/-1/0)

STEP 6: Confirmation agreement check
  _confirm_agreement(primary_signal, [aligned_1hr_trend, aligned_1day_trend])
  agreement = 1 if all higher TF trends agree direction with primary signal
  agreement = 0 if any higher TF conflicts
  usable_signal = primary_signal * agreement
  (only non-zero usable_signal rows become training candidates)

STEP 7: Label each setup
  build_setup_labels(candidate_df, signal_column="usable_signal", lookahead_bars=8)
    future_close = close.shift(-8)
    side = usable_signal (+1 or -1)
    pnl = (future_close - close) * side
    setup_success = 1 if pnl > 0 else 0

STEP 8: Train regime model
  train_regime_model(labeled_df) → CentroidRegimeModel
  For each regime label (bull/bear/flat):
    centroid[label][feature] = mean(feature values where regime_label == label)
  predict(bar): compute L1 distance to each centroid, predict nearest

STEP 9: Train setup ranker
  train_setup_ranker(candidate_df) → HeuristicSetupRanker
  For each strategy_name: strategy_score = mean(setup_success)
  score(row) = strategy_score[strategy_name] + signal_strength * 0.25

STEP 10: Fit confidence calibrator
  fit_confidence_calibrator(raw_scores) → MinMaxConfidenceCalibrator
  calibrate(score) = (score - min) / (max - min), clipped to [0, 1]

STEP 11: Save bundle
  Bundle written to artifacts_template/models/candidate/<bundle_name>/
    metadata.json   — version, features, symbols, notes
    objects.pkl     — pickle of {regime_model, setup_ranker, calibrator,
                                 selected_strategies, primary_tf, confirm_tfs,
                                 strategy_notes}
    feature_schema.json — list of 43 feature column names
  Reports written to artifacts_template/reports/<bundle_name>/
    regime_frame.csv          — 5,029 rows, all regime features + labels
    candidate_frame.csv       — 5,618 setup rows, all signals + success labels
    strategy_success_summary.csv — per-strategy win rate summary
    training_summary.json     — metadata + counts
```

---

## 3. EVERY MODULE EXPLAINED

### core/interfaces.py — Data Contracts
All data structures used across modules:

**StrategyRunResult** (returned by every wrapper.run() call):
```python
strategy_name: str
signal: pd.Series          # +1=buy, -1=sell, 0=hold, indexed by bar
signal_strength: pd.Series # 0.0-1.0 normalized magnitude
trend_state: pd.Series     # ffill of signal — persists last non-zero signal
raw_frame: pd.DataFrame    # full indicator output from calculate_indicators()
adapter_notes: list[str]   # warnings/notes from signal adapter
```

**Recommendation** (output of inference pipeline):
```python
recommendation_id: str     # UUID
symbol: str
horizon: str               # "swing"
regime: str                # "bull", "bear", "flat"
strategy_combo: list[str]  # which strategies triggered
parameters: dict           # params used per strategy
primary_tf: str            # "15m"
confirm_tfs: list[str]     # ["1hr", "1day"]
entry: float               # last close price
stop_loss: float           # entry ± 1.5 * ATR
target_1: float            # entry ± 1.0 * ATR
target_2: float            # entry ± 2.0 * ATR
confidence: float          # 0.0-1.0 calibrated
reason_codes: list[str]    # ["regime:bull", "strategy:twin_range_filter"]
model_version: str
```

**PaperTradeRecord** (feedback loop input):
```python
recommendation_id, symbol, horizon, model_version,
side, entry_time, exit_time, entry_price, exit_price, quantity,
gross_pnl, net_pnl, sl_hit, tp_hit, manual_reject, reject_reason
```

**ModelBundleMetadata**:
```python
model_version, horizon, created_at_utc, feature_columns,
training_symbols, notes, artifact_root
```

---

### strategies/loader.py — Strategy File Importer
```
discover_strategy_paths(root) → sorted list of all *.py in D:\test1\
extract_default_constants(path) → reads AST, finds all DEFAULT_* = <literal>
load_module(path) → importlib dynamic load, adds to sys.modules
get_calculate_signature_defaults(module) → inspect.signature of calculate_indicators()
```

Important: `extend_source_path()` adds D:\test1\ and ALL its subdirectories to sys.path so that open-source indicator libraries cloned under `D:\test1\opensource_indicators\` can be imported by name without pip install.

---

### strategies/registry.py — Strategy Wrapper Builder
```
build_strategy_registry(D:\test1\) → dict[name → ModuleStrategyWrapper]
For each .py file:
  1. extract_default_constants() → AST-parsed DEFAULT_* values
  2. load_module() → dynamic import
  3. get_calculate_signature_defaults() → function signature defaults
  4. merge both into param_defaults (AST values take precedence)
  5. build_param_space() → ±30% grid for each numeric param
  6. assign role_tags from ROLE_TAGS dict
  7. mark flowscope_hapharmonic as unsupported

wrapper.run(df, params=None):
  1. load_module() — reloads fresh (no caching)
  2. _build_call_params() — resolves DEFAULT_X names to function param names
  3. module.calculate_indicators(df, **call_params)
  4. normalize_strategy_output() → extract signal/strength/trend
```

**Special handling in _build_call_params():**
- `timeframe_minutes` parameter is auto-filled from df["timeframe"] column
- `symbol` parameter is auto-filled for vwap_bb_super_confluence_2 and reversal_radar_v2
- `allow_external_fetch=False` is forced for reversal_radar_v2 (blocks HTTP requests during training)
- DEFAULT_X naming: `DEFAULT_ATR_PERIOD` maps to function param `atr_period`

---

### strategies/signal_adapter.py — Signal Column Extractor
Searches the raw_frame returned by calculate_indicators() for columns containing:
```
"buy" or "bull" or "long" → treated as +1 signal direction
"sell" or "bear" or "short" → treated as -1 signal direction
"dir" → treated as directional (sign gives direction)
```

Special case for `central_pivot_range`:
```
If columns {bp, tp} or {daily_bc, daily_tc} exist:
  signal = +1 where close > tp (above pivot top)
  signal = -1 where close < bp (below pivot bottom)
```

If NO matching columns found → signal = 0 for all bars (adapter_notes says "No directional columns found")

**THE BUG:** `vwap_bb_super_confluence_2` returns columns named:
`Upper_Confluence, Lower_Confluence, upper_reversal, lower_reversal`
None contain "buy/sell/bull/bear/long/short" → adapter returns 0 for ALL bars.
Fix: read `upper_reversal` as -1 and `lower_reversal` as +1 directly.

---

### strategies/param_space.py — Parameter Grid Builder
```python
build_numeric_search_space(value):
  low  = value * 0.7
  high = value * 1.3
  steps = 6  (7 values total including endpoints)

  For int: {max(1, round(low + (high-low)*i/6)) for i in range(7)}
  For float: {round(low + (high-low)*i/6, 4) for i in range(7)}

build_param_space(defaults):
  bool   → [True, False]
  int/float → build_numeric_search_space(value)
  other  → [value]  (single-element, not searchable)
```

**Limitation:** The ±30% range is fixed and symmetric. For some parameters (e.g., a lookback period of 20 bars), the meaningful range might be 10–50, but the auto-grid only covers 14–26. A human or AI should manually define wider ranges for critical parameters.

---

### data/load_symbol_timeframes.py — CSV Loader
```
Filename pattern: SYMBOL_TIMEFRAME_NNNNbars.csv
  e.g. RELIANCE_15m_5029bars.csv → symbol=RELIANCE, timeframe=15m, bars=5029

load_timeframe_csv():
  1. pd.read_csv()
  2. Add symbol and timeframe columns
  3. Convert datetime to Asia/Kolkata via tz_convert()
  4. filter_indian_market_hours() → removes bars outside 09:15-15:30
  5. Convert datetime back to UTC
  6. Convert timestamp to int
```

**Note on session filtering:** For 1day and 1month timeframes, session filtering is skipped (daily bars have no intraday time component). For all intraday timeframes (1m, 3m, 5m, 15m, 30m, 1hr, 2hr, 4hr), bars outside 09:15–15:30 IST are dropped. This removes pre-market and post-market data from US-sourced feeds.

---

### data/timeframe_alignment.py — Multi-Timeframe Merger
```
align_higher_timeframes(primary_df, [(timeframe, df), ...]):
  Uses pd.merge_asof(direction="backward") for each higher TF

  merge_asof with direction="backward" means:
  - For each 15m bar at time T, find the most recent 1hr bar at time <= T
  - Copy all columns from that 1hr bar (suffixed with _1hr)

  This correctly handles the case where a 15m bar at 10:30 looks up the
  1hr bar that started at 10:00 (not the future bar at 11:00).
```

**Result:** The primary (15m) DataFrame gains extra columns:
`open_1hr, high_1hr, low_1hr, close_1hr, volume_1hr, open_1day, ...`

---

### features/build_regime_features.py — Regime Feature Engineering
Features computed on the primary 15m frame:
```
return_1         = pct_change(1)       — 1-bar momentum
return_5         = pct_change(5)       — 5-bar momentum (75 min)
volatility_10    = return_1.rolling(10).std()   — realized vol over 2.5 hrs
volume_zscore_10 = (vol - vol.rolling(10).mean()) / vol.rolling(10).std()
close_ma_5       = close.rolling(5).mean()      — 75-min moving average
close_ma_20      = close.rolling(20).mean()     — 5-hr moving average
ma_spread        = close_ma_5 - close_ma_20     — trend direction indicator
```

**Missing features that would improve this:**
- RSI (Relative Strength Index)
- ATR (Average True Range) — volatility-adjusted
- Higher-TF trend features (is close_1hr above/below its MA?)
- Volume profile features (VWAP deviation)
- Market breadth (India VIX level)
- Time-of-day features (morning vs afternoon session)

---

### labels/build_regime_labels.py — Regime Labeling
```python
forward_return = close.shift(-lookahead_bars) / close - 1
threshold = 0.002  (0.2%)

regime_label = "bull"  if forward_return > +0.002
regime_label = "bear"  if forward_return < -0.002
regime_label = "flat"  otherwise
```

**Problem with this labeling:**
- 0.2% threshold on 15m bars is very small (RELIANCE ticks ±0.3-0.5% per bar often)
- Many bars that are actually "flat" noise get labeled "bull" or "bear" by random fluctuation
- lookahead=5 bars = 75 minutes — not aligned with swing trade timeframe
- Should use ATR-relative threshold: e.g., label="bull" if forward_return > 0.5 * ATR/close

---

### labels/build_setup_labels.py — Setup Success Labeling
```python
future_close = close.shift(-lookahead_bars)  # lookahead_bars = 8 = 2 hours
side = usable_signal  # +1 or -1
pnl = (future_close - close) * side
setup_forward_pnl = pnl
setup_success = 1 if pnl > 0 else 0
```

**What this measures:** Did price move in the signal direction within 8 bars (2 hours)?

**Problems:**
1. Binary success/fail — ignores magnitude. A 0.01% move counts as "success" same as 2% move.
2. No cost model applied. Real trades have brokerage + slippage (approx 0.13% round trip on India cash equity).
3. All bars at lookahead boundary are labeled success=0 (because future_close is NaN, pnl=0).
4. No holding period optimization — maybe 12 bars is better than 8 for swing trades.

---

### models/train_regime_model.py — CentroidRegimeModel
```python
class CentroidRegimeModel:
  feature_columns: list[str]
  centroids: dict[str, dict[str, float]]  # {label: {feature: mean_value}}

  train():
    For each regime label (bull/bear/flat):
      centroid[label] = mean(feature values) for all training bars with that label

  predict(features):
    For each test bar:
      L1 distance to each centroid = sum(|bar[feature] - centroid[label][feature]|)
      Predict label with minimum distance

  predict_proba(features):
    confidence[label] = 1 / max(L1_distance, 1e-6)
    normalize to sum=1
```

**This is a Nearest Centroid Classifier.** It is the simplest possible ML model.

**What it does well:**
- Very fast to train (single pass, compute means)
- No hyperparameters to tune
- Interpretable: you can print the centroid values

**What it does poorly:**
- Assumes each regime has a single "center" in feature space (not true for non-convex distributions)
- Does not learn feature importance (all 43 features weighted equally)
- Does not handle multi-modal distributions within a regime
- L1 distance is sensitive to scale differences between features (should normalize features first)

**Better alternatives:** LightGBM, RandomForest, XGBoost — all would dramatically improve regime prediction accuracy. Even a simple logistic regression with feature scaling would beat this centroid model.

---

### models/train_setup_ranker.py — HeuristicSetupRanker
```python
class HeuristicSetupRanker:
  strategy_scores: dict[str, float]  # per-strategy historical win rate
  fallback_score: float              # overall win rate (for unknown strategies)

  train():
    strategy_scores[name] = mean(setup_success) for all rows of that strategy

  score(candidates):
    base_score = strategy_scores[strategy_name]  # e.g., 0.606 for trend_signals
    return base_score + signal_strength * 0.25   # small bonus for strong signals
```

**This is a simple lookup table + constant.** It is NOT a machine learning model.

**Problems:**
- Ignores ALL features except strategy_name and signal_strength
- No regime context: scores a "trend" setup the same in a bull regime vs bear regime
- No interaction between strategies: does not know that "trend_signals + CPR together" = 65%
- The 0.25 weight for signal_strength is completely arbitrary (not learned from data)

**Better approach:** Train a proper classifier (XGBoost or logistic regression) on all 43 features + strategy_name + regime_label → predict setup_success directly.

---

### models/calibrate_confidence.py — MinMaxConfidenceCalibrator
```python
class MinMaxConfidenceCalibrator:
  min_score: float  # minimum raw score seen during training
  max_score: float  # maximum raw score seen during training

  transform(raw_score):
    return clip((raw_score - min) / (max - min), 0, 1)
```

**This is min-max normalization.** It maps the training distribution to [0, 1].

**Problem:** If inference encounters a score outside [min, max], it clips to 0 or 1 — not informative. Isotonic regression or Platt scaling would be more robust calibration methods.

---

### models/evaluate_walk_forward.py — Walk Forward Validator
```python
chronological_split(df, train_ratio=0.7):
  train = df[:70%]
  test  = df[70%:]   (chronological — no future leakage)

evaluate_simple_walk_forward(df, target_col, prediction_col):
  train_metric = accuracy(train[target_col] == train[prediction_col])
  test_metric  = accuracy(test[target_col]  == test[prediction_col])
  robustness   = test_metric / train_metric  (>0.8 = good, <0.5 = overfit)
```

**This is a single train/test split, NOT a true walk-forward.** True walk-forward would use rolling or expanding windows. This implementation evaluates whether the model generalizes from first 70% of data to last 30%.

---

### backtest/engine.py — Backtest Simulator
```python
run_backtest(df, signal_column, stop_loss_pct=0.02, take_profit_pct=0.04):
  For each bar where signal != 0:
    Enter at next bar's open price

    If LONG (+1):
      stop  = entry * (1 - 0.02)   # 2% below entry
      target = entry * (1 + 0.04)  # 4% above entry (2:1 reward:risk)

      Exit if low <= stop  → exit = stop (stopped out)
      Exit if high >= target → exit = target (target hit)
      Else exit = bar close (EOD)

    If SHORT (-1): symmetric logic

    gross_return = (exit/entry) - 1  for long
    gross_return = (entry/exit) - 1  for short

    net_return = gross_return - cost_model.round_trip_cost_pct()
```

### backtest/cost_model.py — India Cash Equity Costs
```python
class IndiaCashCostModel:
  brokerage_bps = 2.0   # 0.02% per leg
  slippage_bps  = 3.0   # 0.03% per leg (market impact)
  taxes_bps     = 1.5   # 0.015% per leg (STT + exchange fees)

  round_trip_cost_pct = (2+3+1.5) * 2 / 10000 = 0.0013 = 0.13%
```

Round-trip cost is 0.13% per trade. On a 2-hour swing trade on RELIANCE with 0.3-0.5% expected move, this is a meaningful friction.

### backtest/metrics.py — Performance Metrics
```python
compute_equity_curve(returns, initial=100000):
  equity = (1 + return_i).cumprod() * 100000

compute_max_drawdown_pct(equity_curve):
  rolling_peak = equity_curve.cummax()
  drawdown = equity_curve / rolling_peak - 1
  return min(drawdown)

compute_sharpe_ratio(returns):
  return sqrt(252) * mean(returns) / std(returns)
  # 252 = trading days/year
  # NOTE: this assumes daily returns but our returns are per-trade
  # annualization factor should be trades/year not 252
```

**Bug:** Sharpe uses sqrt(252) daily annualization on per-trade returns. For intraday swing trades, the correct annualization depends on average trades per year. If there are 100 trades/year and sqrt(252) is used, Sharpe is systematically overstated.

---

### inference/recommend.py — Live Recommendation Generator
```python
recommend_latest(feature_frame, candidate_frame, regime_model, setup_ranker, calibrator, ...):
  1. latest = feature_frame.tail(1)  — most recent bar's features
  2. regime = regime_model.predict(latest)  — predict current market regime
  3. raw_scores = setup_ranker.score(candidate_frame)  — score all candidates
  4. winner = candidates.sort_values(["confidence", "raw_score"]).iloc[0]  — top candidate
  5. build_trade_plan(last_close, side, confidence, atr)
```

### inference/trade_plan.py — Stop/Target Calculator
```python
build_trade_plan(last_close, side, confidence, atr):
  entry     = last_close
  stop_loss = entry - 1.5 * ATR   (long) or entry + 1.5 * ATR (short)
  target_1  = entry + 1.0 * ATR   (long) or entry - 1.0 * ATR (short)
  target_2  = entry + 2.0 * ATR   (long) or entry - 2.0 * ATR (short)
```

Risk:Reward = stop is 1.5 ATR away, target_1 is 1.0 ATR away (R:R = 0.67:1 for T1) and target_2 is 2.0 ATR away (R:R = 1.33:1 for T2). This is a reasonable initial framework but the fixed 1.5/1.0/2.0 multipliers should ideally be dynamic based on regime or confidence.

---

### feedback/daily_retrain.py — Daily Retraining Pipeline
```
run_daily_retrain(market_data_path, feedback_source_path, feedback_store_path):
  1. append_feedback_log() — merge new paper trade results into feedback store
  2. Load fresh market data
  3. build_regime_features() + build_regime_labels()
  4. train_regime_model() — retrain centroid model on all data
  5. build_sample_candidates() — generate candidate rows from fresh data
  6. train_setup_ranker() — update per-strategy win rates
  7. fit_confidence_calibrator() — recalibrate score range
```

**NOTE:** The daily retrain does NOT use the feedback records to update model weights. The feedback store is appended but never read back. This is a placeholder — the actual feedback-to-model loop is NOT implemented.

---

## 4. ALL ALGORITHMS USED (FORMULAS)

### Centroid Regime Model (L1 distance)
```
For training bar i with label L:
  centroid[L][f] = mean(x_f) for all i where label == L

For prediction bar j:
  distance(j, L) = sum_f |x_j[f] - centroid[L][f]|
  predicted_label = argmin_L distance(j, L)
  confidence[L] = 1 / max(distance(j, L), 1e-6)
  normalize: confidence[L] = confidence[L] / sum_L confidence[L]
```

### Setup Ranker Score
```
score(row) = historical_win_rate[strategy_name] + signal_strength * 0.25
```

### Confidence Calibration (min-max)
```
calibrated = clip((raw_score - min_score) / (max_score - min_score), 0, 1)
```

### Regime Labeling Threshold
```
threshold = 0.2%
label = "bull" if (close_{t+5} / close_t - 1) > 0.002
label = "bear" if (close_{t+5} / close_t - 1) < -0.002
label = "flat" otherwise
```

### Setup Success Label
```
pnl = (close_{t+8} - close_t) * signal_direction
success = 1 if pnl > 0
```

### Walk Forward Robustness
```
robustness = test_accuracy / train_accuracy
  >0.9 = very robust
  0.8-0.9 = good
  0.6-0.8 = acceptable
  <0.6 = likely overfit
```

### Sharpe Ratio (per-trade, incorrectly annualized)
```
SR = sqrt(252) * mean(net_returns) / std(net_returns)
Correct formula: SR = sqrt(N_trades_per_year) * mean(net_returns) / std(net_returns)
```

### ATR Proxy (used in backtest)
```
atr_proxy = (high - low).rolling(14).mean()
  (simplified ATR — true ATR uses max(high-low, |high-prev_close|, |low-prev_close|))
```

### Backtest Win Rate (direction-aware)
```
long trades: win if exit_price > entry_price (before costs)
short trades: win if exit_price < entry_price (before costs)
win_rate = wins / total_trades
```

### Confluence Win Rate (used in our analysis)
```
For a set of strategies S = {s1, s2, s3}:
  long_bars  = bars where ALL s in S have signal == +1
  short_bars = bars where ALL s in S have signal == -1

  wins_long  = count(long_bars where close_{t+8} > close_t)
  wins_short = count(short_bars where close_{t+8} < close_t)

  win_rate = (wins_long + wins_short) / (|long_bars| + |short_bars|)
```

---

## 5. THE 25 AVAILABLE STRATEGIES

All Python files in D:\test1\ are auto-loaded. Each was originally a Pine Script v5 indicator converted to Python.

| Strategy Name | Role Tags | Status | Notes |
|---|---|---|---|
| twin_range_filter | trend, entry | OK | ATR-based dynamic range filter |
| trend_signals_tp_sl_ualgo | trend, entry | OK | ATR band trend + TP/SL levels |
| central_pivot_range | levels, filter | OK | Daily pivot levels CPR |
| reversal_radar_v2 | reversal, entry | OK | Block-based reversal detection |
| bahai_reversal_points | reversal, entry | OK | Point-in-polygon reversal |
| vwap_bb_super_confluence_2 | mean_reversion, filter | BROKEN ADAPTER | Outputs upper/lower_reversal not buy/sell |
| bollinger_band_breakout | breakout, entry | OK | Price breaks outside BB |
| candlestick_patterns_identified | pattern, filter | OK | Multiple candlestick patterns |
| cm_hourly_pivots | levels, filter | OK | Hourly CPR pivot levels |
| dark_cloud_piercing_line_tradingfinder | pattern, entry | OK | Japanese candlestick |
| double_top_bottom_ultimate | pattern, entry | OK | Classic chart patterns |
| flowscope_hapharmonic | unsupported | SKIP | Needs sub-bar data not available |
| harmonic_strategy | pattern, entry | OK | Harmonic pattern detection |
| hybrid_ml_vwap_bb | hybrid, entry | OK | Combines ML + VWAP/BB |
| impulse_trend_boswaves | trend, entry | OK | Impulse wave analysis |
| n_bar_reversal_luxalgo | pattern, entry | OK | N-bar reversal |
| n_bar_reversal_luxalgo_strategy | pattern, entry | OK | Strategy version of above |
| outside_reversal | pattern, entry | OK | Outside bar reversal |
| previous_candle_inside_outside_mk | pattern, filter | OK | Inside/outside bar filter |
| reversal_radar_v2 | reversal, entry | OK | see above |
| sfp_candelacharts | pattern, entry | OK | Swing failure pattern |
| three_inside_tradingfinder | pattern, entry | OK | Three inside up/down |
| vedhaviyash4_daily_cpr | levels, filter | OK | Alternate CPR implementation |
| outside_reversal | pattern, entry | OK | |
| sbs_swing_areas_trades | structure, entry | OK | Swing area structure |

**Strategies NOT included in our initial training (potential additions):**
bollinger_band_breakout, hybrid_ml_vwap_bb, impulse_trend_boswaves, harmonic_strategy, sfp_candelacharts, double_top_bottom_ultimate, outside_reversal, candlestick_patterns_identified, n_bar_reversal_luxalgo, three_inside_tradingfinder

These were excluded from the initial config (`reliance_swing.yaml`). They should be tested in the confluence optimizer.

---

## 6. WHAT WE RAN AND EXACT RESULTS

### Run 1 — Initial Training (default params, 6 strategies)
```
Command: PYTHONPATH=src python -m models.train_reliance_swing_bundle
Config:  configs/reliance_swing.yaml
Output:  artifacts_template/models/candidate/reliance_swing_15m_20260321T174222Z/
```

Results:
```
Bundle name:    reliance_swing_15m_20260321T174222Z
Candidate rows: 5,618
Regime rows:    5,029
Feature columns: 43

Strategy win rates (default params, with 1hr+1day confirmation):
  bahai_reversal_points      10 signals   70.0% win
  trend_signals_tp_sl_ualgo 104 signals   60.6% win
  central_pivot_range      3,590 signals  52.9% win
  reversal_radar_v2          296 signals  52.0% win
  twin_range_filter        1,618 signals  50.0% win
  vwap_bb_super_confluence_2  0 signals   N/A   (BROKEN — signal adapter failure)
```

### Run 2 — Confluence Analysis (using initial candidate_frame.csv)
```
Analysis: scripts/param_optimizer.py (inline confluence analysis section)
Input:    candidate_frame.csv from Run 1
```

Results:
```
Confluence count → win rate:
  1 strategy    2,440 bars   50.5%
  2 strategies  1,397 bars   53.3%
  3 strategies    124 bars   54.8%
  4 strategies      3 bars   66.7%

Best pairs:
  central_pivot_range + trend_signals_tp_sl_ualgo   82 bars  65.2%
  trend_signals_tp_sl_ualgo + twin_range_filter      48 bars  58.3%

Worst pair: reversal_radar_v2 + central_pivot_range  217 bars  49.7% (conflict)
```

### Run 3 — Parameter Optimization (scripts/param_optimizer.py)
```
Method: one-at-a-time sweep, ±30% grid, 7 values per parameter
Input:  RELIANCE 15m raw data, each strategy run fresh with each parameter value
Output: artifacts_template/reports/param_optimization/
```

Results by strategy:
```
twin_range_filter:
  DEFAULT_PER1:  default=? best=27   win_rate=48.6% (no real improvement)
  DEFAULT_MULT1: default=? best=1.28 win_rate=48.7%
  DEFAULT_PER2:  default=? best=55   win_rate=48.6%
  DEFAULT_MULT2: default=? best=1.60 win_rate=48.8%
  Combined: 3,708 signals, 48.3% (slightly WORSE than default)
  Conclusion: this strategy's win rate is parameter-insensitive on this data

trend_signals_tp_sl_ualgo:
  DEFAULT_MULTIPLIER:    default=? best=2.6   win_rate=60.9% ← KEY PARAMETER
  DEFAULT_ATR_PERIOD:    default=? best=10    win_rate=53.4%
  DEFAULT_CLOUD_VAL:     default=? best=7     win_rate=51.5%
  DEFAULT_STOP_LOSS_PCT: default=? best=1.4   win_rate=51.5%
  Combined: 183 signals, 60.1% (+8.6%pts vs baseline 51.5%)
  Conclusion: MULTIPLIER=2.6 is the critical change

bahai_reversal_points:
  DEFAULT_LENGTH:         default=? best=25   win_rate=60.0% (20 signals)
  DEFAULT_LOOKBACK_LENGTH: default=? best=6   win_rate=64.0% (25 signals)
  DEFAULT_THRESHOLD_LEVEL: default=? best=0.7 win_rate=52.2%
  Combined: 8 signals only — too few for statistical significance
  Conclusion: individually parameters look good but combined over-filters to 8 trades

reversal_radar_v2:
  DEFAULT_BLOCK_START: default=? best=16  win_rate=53.1%
  DEFAULT_BLOCK_END:   default=? best=7   win_rate=52.8%
  Combined: 556 signals, 53.1% (+0.3%pts — minimal improvement)

central_pivot_range:
  No numeric DEFAULT_* constants found in source file
  Baseline: 4,333 signals, 47.1%
```

### Run 4 — VWAP BB Reversal Analysis (scripts/vwap_bb_reversal_analysis.py)
```
Input: RELIANCE 15m data
Method: bypass signal adapter, read upper_reversal/lower_reversal/Upper_Confluence/Lower_Confluence directly
Output: artifacts_template/reports/vwap_bb_analysis/
```

Default parameter results:
```
upper_reversal (sell signal):   225 events  52.9% win  avg_fwd_return +0.017%
lower_reversal (buy signal):    240 events  49.6% win  avg_fwd_return -0.005%
Upper_Confluence (zone only):   375 events  44.8% win  ← BELOW RANDOM
Lower_Confluence (zone only):   430 events  44.7% win  ← BELOW RANDOM
```

Best parameters from sweep:
```
bb_len1=30:              reversal win_rate = 53.0%  (vs 51.2% default)
bb_k1a=1.5:             reversal win_rate = 52.1%
require_double_touch=False: 571 signals, 52.0%
vwap_k1=0.5:            502 signals, 52.0%
```

Combined best (all above): upper_reversal 52.1%, lower_reversal 50.8%

Key finding: Adding vwap_bb as 3rd filter to existing 2-strategy combos = +11.7%pts.

### Run 5 — Confluence Optimizer (scripts/confluence_optimizer.py)
```
Input: RELIANCE 15m data, all strategies with optimized params
Method: rebuild signal matrix from scratch using best params, test all 24 subsets
  (2^6 - 2 = 62 subsets total, but 24 met the MIN_BARS=8 threshold)
Output: artifacts_template/reports/confluence_optimizer/
```

Signal counts with optimized params:
```
central_pivot_range:      4,333 signals (86.1% of all bars)
twin_range_filter:        3,708 signals (73.7% of all bars)
vwap_bb_reversal:           630 signals (12.5% of all bars)
reversal_radar_v2:          556 signals (11.1% of all bars)
trend_signals_tp_sl_ualgo:  183 signals ( 3.6% of all bars)
bahai_reversal_points:        8 signals ( 0.16% of all bars)
```

All 24 valid combinations (sorted by win rate):
```
Rank  Combo                                              Signals  WinRate  LongWR  ShortWR
1     trend_signals + reversal_radar_v2                      8    75.0%    66.7%   80.0%
2     trend_signals + vwap_bb_reversal                      19    73.7%    66.7%   85.7%
3     twin_range + trend_signals + vwap_bb                  19    73.7%    66.7%   85.7%
4     trend_signals + CPR + vwap_bb                         14    71.4%    66.7%   80.0%
5     twin_range + trend_signals + CPR + vwap_bb            14    71.4%    66.7%   80.0%
6     trend_signals + CPR                                  136    64.0%    65.9%   60.4%
7     twin_range + trend_signals + CPR                     100    62.0%    63.0%   60.9%
8     trend_signals (alone)                                182    60.4%    63.9%   55.4%
9     twin_range + trend_signals                           145    57.9%    60.3%   55.6%
10    twin_range + reversal_radar_v2                       195    54.4%    49.5%   59.2%
11    reversal_radar_v2 + vwap_bb                           84    53.6%    53.8%   53.3%
12    reversal_radar_v2 (alone)                            556    53.1%    50.7%   55.2%
13    reversal_radar_v2 + CPR                              160    52.5%    45.7%   59.5%
14    twin_range + reversal_radar_v2 + CPR                  99    51.5%    43.1%   60.4%
15    vwap_bb (alone)                                      628    51.4%    50.8%   52.1%
16    bahai (alone)                                          8    50.0%    40.0%   66.7%
17    reversal_radar_v2 + CPR + vwap_bb                     8    50.0%    50.0%   50.0%
18    twin_range (alone)                                 3,702    48.4%    47.8%   49.1%
19    twin_range + vwap_bb                                 147    47.6%    52.0%   42.9%
20    twin_range + CPR                                   2,563    47.6%    47.1%   48.0%
21    CPR (alone)                                        4,325    47.2%    46.7%   47.8%
22    twin_range + reversal_radar_v2 + vwap_bb             28    46.4%    50.0%   43.8%
23    twin_range + CPR + vwap_bb                           63    46.0%    50.0%   39.1%
24    CPR + vwap_bb                                       105    42.9%    46.2%   37.5%
```

---

## 7. WHY CERTAIN COMBOS WORK — DEEP ANALYSIS

### Why `trend_signals + reversal_radar_v2` = 75% win rate

**trend_signals_tp_sl_ualgo** is a trend-following indicator:
- It draws ATR-based bands above and below price
- When price breaks above the upper band → bullish signal (+1)
- When price breaks below the lower band → bearish signal (-1)
- With MULTIPLIER=2.6 (wide bands): only very strong breakouts signal
- This means when it fires, price has moved 2.6 × ATR from its average — genuinely extreme momentum

**reversal_radar_v2** is a reversal detector:
- It identifies "block" patterns — specific sequences of bars that historically precede reversals
- When it fires, it says "a reversal is starting here"

**Why they combine well:**
A bar where trend_signals fires +1 (strong uptrend established) AND reversal_radar fires +1 (reversal upward beginning) represents a very specific setup: price was in a strong downtrend, hit an extreme, and is NOW beginning to reverse up. This is the classic "trend reversal" setup used in professional swing trading.

The SHORT trades (80%): strong downtrend + reversal-down detected = bearish momentum extremes. RELIANCE specifically tends to have sharp, clean down moves when institutional selling begins.

### Why `trend_signals + vwap_bb_reversal` = 73.7% win rate

**vwap_bb_reversal** upper_reversal fires when:
- Price touched the UPPER VWAP band + Bollinger Band confluence zone
- AND the bar closed lower (confirmed reversal bar, not just a wick touch)

The SHORT side (85.7%): when trend_signals also says "strong downtrend" AND vwap_bb says "price just confirmed reversal from upper extreme zone" = very high confluence for continued downside.

### Why `trend_signals + CPR` = 64% win rate (high signal count)
CPR (Central Pivot Range) fires whenever price crosses above/below the daily pivot levels. This happens frequently (4,333 bars = 86% of all bars). When filtered by trend_signals (only 183 bars), you get 136 bars where:
- Price just crossed a major pivot level (CPR says structural level broken)
- AND the trend is confirmed strong by the ATR band system

### Why `CPR + reversal_radar_v2` = 49.7% (WORSE than random)
These two strategies conflict. CPR fires on pivot crossings (trend continuation signal) while reversal_radar fires on reversal patterns (trend change signal). When both fire, they are contradicting each other: "trend continuing across pivot" + "reversal starting here" = mixed signal = noise. Combining conflicting strategy types destroys signal quality.

---

## 8. STATISTICAL VALIDITY ANALYSIS

### Sample Size Warning
| Combo | Signals | 95% Confidence Interval for Win Rate |
|---|---|---|
| trend_signals + reversal_radar_v2 | 8 | 37% – 100% |
| trend_signals + vwap_bb | 19 | 51% – 91% |
| trend_signals + CPR + vwap_bb | 14 | 46% – 92% |
| trend_signals + CPR | 136 | 55% – 72% |

8 signals: The Wilson interval for 75% with n=8 is enormous (37–100%). This is NOT statistically significant. We need at least 50 signals to trust a win rate within ±10%pts.

**Recommendation:** The top combos have too few signals to be trusted. For live trading:
- Use `trend_signals + CPR` (136 signals, 64% win rate, tighter CI: 55–72%)
- Or collect more data (add more symbols) before trusting the 8-signal combos

### Data Snooping Risk
We tested 24 combinations on the SAME dataset we used to discover the best parameters. This means:
- We optimized parameters on the full dataset (no holdout)
- We then tested combinations on the same full dataset
- The "best" combination is partly luck — it happened to work on this specific price history

**Required fix:** Use a proper out-of-sample test period (e.g., train on 2022-2024, test on 2025) to validate any combination before trusting it.

---

## 9. EVERYTHING THAT IS MISSING OR BROKEN

### Broken
1. **Signal adapter for vwap_bb** — `normalize_strategy_output()` in `signal_adapter.py` doesn't handle `upper_reversal`/`lower_reversal` column names. Fix: add detection for these columns in the adapter.
2. **Sharpe ratio annualization** — uses sqrt(252) but should use sqrt(trades_per_year). Current Sharpe is systematically inflated.
3. **Feedback loop not actually connected** — `daily_retrain.py` appends paper trade records but never reads them back to update model weights.
4. **DEFAULT_* param names not printed** — the optimizer showed "default=?" because the constants use names like DEFAULT_LENGTH not DEFAULT_ATR_PERIOD. The param space key and the actual param name mapping is inconsistent.

### Missing Features
1. **Out-of-sample validation** — no holdout period used anywhere. All metrics are in-sample.
2. **Cross-strategy parameter interaction search** — we did one-at-a-time sweep; didn't explore parameter combinations within a strategy.
3. **Regime-conditional win rates** — we never checked "what is the win rate of combo X specifically during bull/bear/flat regime?"
4. **Multi-symbol validation** — everything is RELIANCE-only. No evidence this generalizes.
5. **True ATR** — the backtest uses `(high-low).rolling(14).mean()` but true ATR = `max(high-low, |high-prev_close|, |low-prev_close|)`. Should fix.
6. **Proper ML model** — the centroid regime classifier and heuristic setup ranker are placeholders. Should replace with LightGBM or XGBoost.
7. **Feature importance** — we have 43 features but no analysis of which ones matter. PCA or feature importance from a tree model would help.
8. **Position sizing** — the backtest assumes constant position size. Kelly criterion or volatility-adjusted sizing would be more realistic.
9. **The other 19 strategies not tested** — only 5-6 of the 25 available strategies were used. The others (bollinger_band_breakout, hybrid_ml_vwap_bb, sfp_candelacharts, etc.) were never tested.
10. **Higher timeframe signal integration** — the 1hr/1day frames are used for confirmation but their signals are not used as primary entries. A 1hr or 1day signal could be the primary entry, confirmed by 15m.

### Kaggle Notebooks
All 5 notebooks (01-05) are empty stubs with TODO comments only. They reference `/kaggle/input/your-dataset/` which doesn't exist. Before using Kaggle, someone needs to:
1. Implement the notebooks (copy local_project/src code into them)
2. Convert CSV files to parquet
3. Upload the dataset

---

## 10. SPECIFIC IMPROVEMENTS FOR ANOTHER AI TO IMPLEMENT

### Priority 1 — Fix the adapter bug for vwap_bb (easy, high impact)
In `strategies/signal_adapter.py`, add to `normalize_strategy_output()`:
```python
# After existing SIGNAL_PRIORITY matching loop, before the "no signal found" check:
if not signal_parts:
    if "lower_reversal" in frame.columns or "upper_reversal" in frame.columns:
        sig = pd.Series(0, index=frame.index, dtype=int)
        if "lower_reversal" in frame.columns:
            sig[frame["lower_reversal"].astype(bool)] = 1
        if "upper_reversal" in frame.columns:
            sig[frame["upper_reversal"].astype(bool)] = -1
        signal_parts.append(sig)
        notes.append("vwap_bb: extracted from upper_reversal/lower_reversal columns")
```
Effect: vwap_bb_super_confluence_2 will now produce signals in the standard pipeline.

### Priority 2 — Replace centroid model with LightGBM (medium, high impact)
Replace `CentroidRegimeModel` with:
```python
import lightgbm as lgb

def train_regime_model_lgbm(df):
    features = infer_feature_columns(df, excluded={"regime_label", "forward_return", ...})
    X = df[features].fillna(0)
    y = df["regime_label"].map({"bull": 2, "flat": 1, "bear": 0})
    model = lgb.LGBMClassifier(n_estimators=100, num_leaves=15, random_state=42)
    model.fit(X, y)
    return model, features
```
Expected improvement: regime prediction accuracy likely improves from ~55% to ~65-70%.

### Priority 3 — Add regime-conditional win rate analysis (medium)
In `confluence_optimizer.py`, for each winning combo, add:
```python
for regime_label in ["bull", "flat", "bear"]:
    regime_bars = matrix[matrix["regime_label"] == regime_label]
    # evaluate combo on regime_bars only
```
This will show: "combo X has 75% win rate overall, but 85% in bear regime and 60% in bull regime"

### Priority 4 — Use chronological train/test split in parameter sweep (medium)
Current: parameter sweep tests on ALL 5,029 bars (same data used to find best params)
Fix: split data chronologically (train on first 3,500 bars, test on last 1,529 bars), sweep on train only, then validate on test. Any parameter that doesn't generalize to test will be rejected.

### Priority 5 — Expand to all 25 strategies (easy, potentially high impact)
Change `SELECTED_STRATEGIES` in `confluence_optimizer.py` to include all non-broken strategies. The 19 untested ones may contain hidden high-win-rate combinations.

### Priority 6 — Fix Sharpe ratio annualization
In `backtest/metrics.py`, change:
```python
# Wrong:
return float(math.sqrt(252) * clean.mean() / clean.std(ddof=0))

# Better:
trades_per_year = 252  # estimate based on signal frequency; should be passed as parameter
return float(math.sqrt(trades_per_year) * clean.mean() / clean.std(ddof=0))
```

### Priority 7 — Implement the Kaggle notebooks
Using `local_project/src` as reference, implement each notebook:
```
01_prepare_data.ipynb:
  - Read CSV from /kaggle/input/your-dataset/market_data/
  - normalize_market_data() for each timeframe
  - Save parquet to /kaggle/working/prepared_data/

02_build_features.ipynb:
  - align_higher_timeframes() using prepared parquet files
  - build_regime_features() on aligned frame
  - For each strategy: wrapper.run() → save signal columns
  - Save feature tables to /kaggle/working/features/

03_train_models.ipynb:
  - train_regime_model(), train_setup_ranker(), fit_confidence_calibrator()
  - Save bundle to /kaggle/working/models/

04_validate_backtest.ipynb:
  - chronological_split() → evaluate on test period
  - run_backtest() with IndiaCashCostModel
  - Save metrics to /kaggle/working/reports/

05_export_bundle.ipynb:
  - Copy bundle + reports to /kaggle/working/exports/
  - Download for local review
```

### Priority 8 — Implement rolling walk-forward (hard, essential for real trading)
Replace single-split evaluation with rolling walk-forward:
```python
def rolling_walk_forward(df, window_size=1000, step_size=250):
    results = []
    for start in range(0, len(df) - window_size, step_size):
        train = df.iloc[start : start + window_size]
        test  = df.iloc[start + window_size : start + window_size + step_size]
        model = train_regime_model(train)
        result = evaluate(model, test)
        results.append(result)
    return pd.DataFrame(results)
```

---

## 11. FILE MAP — EVERY FILE AND ITS PURPOSE

### Scripts Created During This Experiment
```
local_project/scripts/param_optimizer.py
  → Sweeps each strategy's parameters one-at-a-time to find best values
  → Input: D:\TV_proj\output\reliance_timeframes\, D:\test1\
  → Output: artifacts_template/reports/param_optimization/

local_project/scripts/vwap_bb_reversal_analysis.py
  → Runs vwap_bb_super_confluence_2 directly, bypasses signal adapter
  → Extracts upper_reversal/lower_reversal/Upper_Confluence/Lower_Confluence events
  → Checks forward return accuracy for each event type
  → Sweeps key parameters
  → Output: artifacts_template/reports/vwap_bb_analysis/

local_project/scripts/confluence_optimizer.py
  → Runs ALL strategies with OPTIMIZED params (hardcoded from BEST_PARAMS dict)
  → Also runs vwap_bb with best params, extracts reversal as signal
  → Tests every combination (single → quintuples) for win rate
  → Uses direction-aware win rate (all strategies must agree on direction)
  → Output: artifacts_template/reports/confluence_optimizer/
```

### Key Output Files
```
artifacts_template/models/candidate/reliance_swing_15m_20260321T174222Z/
  metadata.json       → bundle version, features, symbols
  objects.pkl         → regime_model, setup_ranker, calibrator, selected_strategies
  feature_schema.json → 43 feature column names

artifacts_template/reports/reliance_swing_15m_20260321T174222Z/
  candidate_frame.csv          → 5,618 setup rows with all signals + success labels
  regime_frame.csv             → 5,029 bars with regime features + labels
  strategy_success_summary.csv → per-strategy win rates
  training_summary.json        → counts + config

artifacts_template/reports/param_optimization/
  optimization_summary.csv     → per-strategy: baseline vs optimized win rate
  best_params.json             → best parameters per strategy (use as BEST_PARAMS input)
  <strategy>__<param>_sweep.csv → one file per parameter, all values tested

artifacts_template/reports/vwap_bb_analysis/
  events_default_params.csv    → all reversal/confluence events with success labels
  events_best_params.csv       → same with best params applied
  param_sweep.csv              → parameter sweep results
  vwap_bb_best_params.json     → best parameters for vwap_bb

artifacts_template/reports/confluence_optimizer/
  all_combos.csv               → all 24 valid combinations sorted by win rate
  top20_combos.csv             → top 20 combinations
  best_combo_config.json       → best combo + all optimized params as single JSON
```

---

## 12. HOW TO REPRODUCE EVERYTHING FROM SCRATCH

```bash
# 1. Activate environment
cd C:\Users\sakth\Desktop\vayu && source .venv/Scripts/activate

# 2. Set Python path
export PYTHONPATH=D:/ml/stock_advisor_starter_pack/local_project/src

# 3. Train the bundle (initial run, default params)
cd D:/ml/stock_advisor_starter_pack/local_project
python -m models.train_reliance_swing_bundle

# 4. Run parameter optimizer (~5 min)
python scripts/param_optimizer.py

# 5. Run vwap_bb reversal analysis (~2 min)
python scripts/vwap_bb_reversal_analysis.py

# 6. Run confluence optimizer with all best params (~3 min)
python scripts/confluence_optimizer.py

# 7. Run tests
python -m pytest tests/ -v
```

---

## 13. CURRENT RECOMMENDED CONFIGS (SUMMARY)

### Config A — Active Trading (best balance of frequency + quality)
```json
{
  "strategies": ["trend_signals_tp_sl_ualgo", "central_pivot_range"],
  "params": {
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10}
  },
  "win_rate": "64.0%",
  "signal_frequency": "136 signals per 5,029 bars (1 per ~37 bars = ~1 per 2 trading days)",
  "long_win_rate": "65.9%",
  "short_win_rate": "60.4%"
}
```

### Config B — Balanced (recommended for paper trading first)
```json
{
  "strategies": ["twin_range_filter", "trend_signals_tp_sl_ualgo", "vwap_bb_reversal"],
  "params": {
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10},
    "vwap_bb_super_confluence_2": {"bb_len1": 30, "bb_k1a": 1.5, "require_double_touch": false}
  },
  "win_rate": "73.7%",
  "signal_frequency": "19 signals per 5,029 bars (1 per 265 bars = ~1 per 16 trading days)",
  "long_win_rate": "66.7%",
  "short_win_rate": "85.7%",
  "warning": "Only 19 signals — CI is wide. Need more data to trust this fully."
}
```

### Config C — High Confidence (very selective)
```json
{
  "strategies": ["trend_signals_tp_sl_ualgo", "reversal_radar_v2"],
  "params": {
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10},
    "reversal_radar_v2": {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7}
  },
  "win_rate": "75.0%",
  "signal_frequency": "8 signals per 5,029 bars (1 per ~1 month)",
  "long_win_rate": "66.7%",
  "short_win_rate": "80.0%",
  "warning": "Only 8 signals — statistically unreliable. Use for learning, not live trading."
}
```
