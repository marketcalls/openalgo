# MASTER RESEARCH PROMPT
## RELIANCE Swing Bundle — Probabilistic Signal Discovery System
### For: AI Research Agent | Style: Out-of-box probabilistic thinking
### Context: Continuing an active ML research session on NSE India equities

---

## HOW TO READ THIS DOCUMENT

This is not a documentation file. This is a **research brief**.

You are being handed a partially explored probabilistic trading signal system. Your job is not to execute what was done before — it is to look at the results with fresh eyes, identify what has NOT been explored, spot the hidden patterns in the numbers, form hypotheses, test them, and find signal combinations that a human researcher would miss by thinking linearly.

Think of each strategy signal as a **vote in a probabilistic jury**. Each independent vote that agrees with the others raises the posterior probability of a correct trade. Your job is to find which jurors are reliable, which are correlated (so their votes cancel out), which are only reliable in certain market conditions, and which ones, when combined, achieve statistical independence — which is where real edge lives.

---

## PART 1: WHAT THIS SYSTEM IS

### The Core Idea
A Python-based ML framework that:
1. Loads OHLCV market data for RELIANCE (NSE India) at multiple timeframes
2. Runs 25 Pine Script strategies (converted to Python) as signal generators
3. Labels each signal as success/fail based on 8-bar forward price movement
4. Trains models to rank and combine signals
5. Generates trade recommendations with entry, stop, and target levels

### The Physical Setup
```
Market Data (CSVs):   D:\TV_proj\output\reliance_timeframes\
  RELIANCE_1m_5250bars.csv
  RELIANCE_3m_5500bars.csv
  RELIANCE_5m_5025bars.csv
  RELIANCE_15m_5029bars.csv     ← PRIMARY TRAINING FRAME
  RELIANCE_30m_7151bars.csv
  RELIANCE_1hr_5568bars.csv     ← CONFIRMATION TF 1
  RELIANCE_2hr_5160bars.csv
  RELIANCE_4hr_5051bars.csv
  RELIANCE_1day_7772bars.csv    ← CONFIRMATION TF 2
  RELIANCE_1month_377bars.csv

Strategy Files:       D:\test1\  (25 Python files, converted from Pine Script v5)
Project Code:         D:\ml\stock_advisor_starter_pack\local_project\src\
Python Env:           C:\Users\sakth\Desktop\vayu\.venv\  (Python 3.11.9)
Activate:             cd C:\Users\sakth\Desktop\vayu && source .venv/Scripts/activate
Run with:             PYTHONPATH=D:\ml\stock_advisor_starter_pack\local_project\src

Training output:      D:\ml\stock_advisor_starter_pack\artifacts_template\
Reports:              D:\ml\stock_advisor_starter_pack\artifacts_template\reports\
```

### Data Range
```
15m bars:  June 2025 – March 2026 (5,029 bars = ~9 months)
           India market hours only: 09:15–15:30 IST
           25 bars per trading day × ~201 trading days
```

---

## PART 2: THE FULL CODEBASE — EVERY MODULE

### Data Pipeline
```
src/data/load_symbol_timeframes.py
  discover_timeframe_csvs(root, symbol)    → finds all SYMBOL_TF_NNNNbars.csv files
  load_timeframe_csv(path, symbol, tf)     → reads CSV, adds columns, filters session hours
  load_symbol_timeframes(root, symbol)     → returns dict[timeframe → TimeframeDataset]
  TimeframeDataset: {symbol, timeframe, path, frame:DataFrame}

src/data/session_filter.py
  filter_indian_market_hours(df, tf)       → keeps only 09:15–15:30 IST bars
  ensure_datetime_index(df)               → converts timestamp/datetime to DatetimeIndex

src/data/timeframe_alignment.py
  align_higher_timeframes(primary_df, [(tf, df), ...])
  → pd.merge_asof(direction="backward") for each higher TF
  → every 15m bar gets the most recent 1hr and 1day columns appended
  → result columns: open_1hr, high_1hr, low_1hr, close_1hr, volume_1hr,
                    open_1day, high_1day, low_1day, close_1day, volume_1day

src/data/prepare_market_data.py
  normalize_market_data(df, symbol, tf)   → enforces canonical schema
  Canonical schema: symbol, timeframe, timestamp(unix_sec), datetime(ISO8601),
                    open, high, low, close, volume
```

### Feature Engineering
```
src/features/build_regime_features.py
  build_regime_features(df) adds 7 columns:
    return_1         = close.pct_change(1)
    return_5         = close.pct_change(5)
    volatility_10    = return_1.rolling(10).std()
    volume_zscore_10 = (vol - vol.rolling(10).mean()) / vol.rolling(10).std()
    close_ma_5       = close.rolling(5).mean()
    close_ma_20      = close.rolling(20).mean()
    ma_spread        = close_ma_5 - close_ma_20

src/features/build_swing_training_data.py
  build_swing_training_artifacts(primary, confirmations, wrappers)
  → runs each strategy on primary + each confirmation TF
  → confirmation agreement: usable_signal = primary_signal * confirm_agreement
    confirm_agreement = 1 if ALL higher TF trends agree with primary direction
    confirm_agreement = 0 if ANY higher TF conflicts

src/features/feature_schema.py
  infer_feature_columns(df, excluded)     → all numeric columns not in exclusion set
  save/load feature_schema.json           → list of 43 column names used for model input
```

### Labeling
```
src/labels/build_regime_labels.py
  build_regime_labels(df, lookahead_bars=5, threshold=0.002)
    forward_return = close.shift(-5) / close - 1
    "bull" if forward_return > +0.002 (price rises >0.2% in next 5 bars = 75 min)
    "bear" if forward_return < -0.002
    "flat" otherwise
  Distribution: bull=1,403  bear=1,441  flat=2,185  (43% flat)

src/labels/build_setup_labels.py
  build_setup_labels(df, signal_column, lookahead_bars=8)
    pnl = (close.shift(-8) - close) * signal_direction
    setup_success = 1 if pnl > 0 else 0
    (lookahead_bars=8 → 2 hours forward on 15m bars)
```

### Models
```
src/models/train_regime_model.py
  CentroidRegimeModel (Nearest Centroid Classifier):
    train: centroid[label][feature] = mean(feature) for all bars with that label
    predict: L1 distance to each centroid, return nearest label
    predict_proba: confidence[L] = 1/distance(L), normalized

src/models/train_setup_ranker.py
  HeuristicSetupRanker (NOT a real ML model — a lookup table):
    strategy_scores[name] = mean(setup_success) per strategy
    score(row) = strategy_scores[strategy_name] + signal_strength * 0.25
    CRITICAL BUG: signal_strength = 1.0 for ALL rows (constant)
    so score = strategy_win_rate + 0.25 (constant — carries no information)

src/models/calibrate_confidence.py
  MinMaxConfidenceCalibrator:
    calibrate(score) = clip((score - min) / (max - min), 0, 1)

src/models/evaluate_walk_forward.py
  chronological_split(df, train_ratio=0.7)  → train=first70%, test=last30%
  evaluate_simple_walk_forward(df, target, prediction)
    robustness = test_accuracy / train_accuracy
    (single split, NOT rolling walk-forward)
```

### Strategy System
```
src/strategies/loader.py
  discover_strategy_paths(D:\test1\)  → all *.py files
  extract_default_constants(path)     → AST parses DEFAULT_* constants
  load_module(path)                   → importlib dynamic import
  get_calculate_signature_defaults()  → inspect.signature defaults

src/strategies/param_space.py
  build_param_space(defaults):
    numeric: ±30% grid, 7 values (low=0.7x, high=1.3x, steps=6)
    bool: [True, False]
    other: [value]  (not searchable)

src/strategies/registry.py
  ModuleStrategyWrapper:
    .run(df, params) → StrategyRunResult
    .param_defaults  → dict of DEFAULT_* values
    .param_space     → auto-generated ±30% search space
    .role_tags       → ("trend","entry") etc.
    .unsupported_reason → None or string

src/strategies/signal_adapter.py
  normalize_strategy_output(name, raw_frame):
    looks for columns containing: "buy"/"bull"/"long" → +1
                                   "sell"/"bear"/"short" → -1
                                   "dir" → directional
    special case: central_pivot_range → +1 if close > tp, -1 if close < bp
    KNOWN BUG: vwap_bb_super_confluence_2 uses "upper_reversal"/"lower_reversal"
               columns — adapter finds NO matching names → returns 0 for all bars
```

### Backtest Engine
```
src/backtest/engine.py
  run_backtest(df, signal_column, stop_loss_pct=0.02, take_profit_pct=0.04):
    Entry: next bar's open
    Long exit: stop = entry*(1-0.02), target = entry*(1+0.04)
    Short exit: stop = entry*(1+0.02), target = entry*(1-0.04)
    Stops/targets checked within same bar (high/low check)

src/backtest/cost_model.py
  IndiaCashCostModel:
    brokerage = 2 bps/leg
    slippage  = 3 bps/leg
    taxes     = 1.5 bps/leg (STT + exchange)
    round_trip = 0.13% total

src/backtest/metrics.py
  Sharpe = sqrt(252) * mean(returns) / std(returns)
  KNOWN BUG: uses 252 (daily) annualization on per-trade returns
```

### Inference Pipeline
```
src/inference/recommend.py
  recommend_latest(feature_frame, candidate_frame, regime_model, ranker, calibrator):
    1. regime = regime_model.predict(feature_frame.tail(1))
    2. score all candidates with setup_ranker
    3. pick highest-confidence candidate
    4. build_trade_plan(close, side, confidence, atr)

src/inference/trade_plan.py
  entry     = last close
  stop_loss = entry ± 1.5 * ATR
  target_1  = entry ± 1.0 * ATR  (R:R = 0.67)
  target_2  = entry ± 2.0 * ATR  (R:R = 1.33)
```

### Feedback Loop
```
src/feedback/ingest_paper_trade_log.py
  append_feedback_log(source, target)  → merges new paper trades into store CSV

src/feedback/daily_retrain.py
  run_daily_retrain(market_data, feedback_source, feedback_store):
    appends feedback, retrains regime model + setup ranker
    CRITICAL GAP: feedback records are appended but never read back
    into model training — the loop is structurally incomplete

src/feedback/promotion_report.py
  build_promotion_report(candidate_metrics, active_metrics, output_path)
  → side-by-side comparison to decide if candidate should replace active model
```

---

## PART 3: THE 25 AVAILABLE STRATEGIES

```
Name                              Role Tags              Notes
─────────────────────────────────────────────────────────────────────
twin_range_filter                 trend, entry           ATR range bands
trend_signals_tp_sl_ualgo         trend, entry           ATR bands + TP/SL levels  ← BEST
central_pivot_range               levels, filter         Daily pivot (CPR)
reversal_radar_v2                 reversal, entry        Block-pattern reversal
bahai_reversal_points             reversal, entry        Point-in-polygon reversal
vwap_bb_super_confluence_2        mean_reversion, filter VWAP+BB zone detection  ← ADAPTER BROKEN
bollinger_band_breakout           breakout, entry        Price breaks BB           ← NOT TESTED
candlestick_patterns_identified   pattern, filter        Multiple patterns         ← NOT TESTED
cm_hourly_pivots                  levels, filter         Hourly pivot levels       ← NOT TESTED
dark_cloud_piercing_line          pattern, entry         Candlestick pattern       ← NOT TESTED
double_top_bottom_ultimate        pattern, entry         Classic chart patterns    ← NOT TESTED
flowscope_hapharmonic             unsupported            SKIP (placeholder only)
harmonic_strategy                 pattern, entry         Harmonic patterns         ← NOT TESTED
hybrid_ml_vwap_bb                 hybrid, entry          ML + VWAP/BB              ← NOT TESTED
impulse_trend_boswaves            trend, entry           Impulse wave analysis     ← NOT TESTED
n_bar_reversal_luxalgo            pattern, entry         N-bar reversal            ← NOT TESTED
n_bar_reversal_luxalgo_strategy   pattern, entry         Strategy version          ← NOT TESTED
outside_reversal                  pattern, entry         Outside bar reversal      ← NOT TESTED
previous_candle_inside_outside    pattern, filter        Inside/outside bars       ← NOT TESTED
sfp_candelacharts                 pattern, entry         Swing failure pattern     ← NOT TESTED
three_inside_tradingfinder        pattern, entry         Three inside up/down      ← NOT TESTED
vedhaviyash4_daily_cpr            levels, filter         Alternate CPR             ← NOT TESTED
sbs_swing_areas_trades            structure, entry       Swing structure areas     ← NOT TESTED
outside_reversal                  pattern, entry         Outside bar reversal      ← NOT TESTED
harmonic_strategy                 pattern, entry         Harmonic patterns         ← NOT TESTED

19 of 25 strategies have NEVER been tested. Their signal quality is UNKNOWN.
```

---

## PART 4: ALL RESULTS SO FAR — EXACT NUMBERS

### Initial Training (default params, 5 strategies + broken vwap_bb)
```
Data range:   June 2025 – March 2026, RELIANCE 15m
Primary TF:   15m  |  Confirmation TFs: 1hr + 1day
5,029 bars total training set

Strategy win rates (with 1hr+1day confirmation filter):
  bahai_reversal_points         10 signals   70.0% win
  trend_signals_tp_sl_ualgo    104 signals   60.6% win
  central_pivot_range        3,590 signals   52.9% win
  reversal_radar_v2            296 signals   52.0% win
  twin_range_filter          1,618 signals   50.0% win
  vwap_bb_super_confluence_2     0 signals   BROKEN

Regime distribution:
  flat: 2,185 bars (43.5%)
  bear: 1,441 bars (28.7%)
  bull: 1,403 bars (27.9%)

Signal direction distribution (candidate_frame):
  LONG:  2,898 signals (51.6%)
  SHORT: 2,720 signals (48.4%)
```

### CRITICAL DISCOVERY 1: Regime-Conditional Win Rates
```
Win rate by regime (ALL strategies combined):
  BULL regime:  55.6% win  (1,566 signals)
  BEAR regime:  54.6% win  (1,587 signals)
  FLAT regime:  48.5% win  (2,465 signals) ← BELOW RANDOM

Per strategy × regime breakdown:
  trend_signals_tp_sl_ualgo:
    BULL regime:  79.6% win  (49 signals)   ← OUTSTANDING
    BEAR regime:  57.9% win  (19 signals)
    FLAT regime:  36.1% win  (36 signals)   ← ACTIVELY LOSES MONEY
  bahai_reversal_points:
    BEAR regime: 100.0% win  (4 signals)   ← perfect (tiny sample)
    BULL regime:  66.7% win  (3 signals)
    FLAT regime:  33.3% win  (3 signals)   ← terrible in flat
  central_pivot_range:
    BULL regime:  55.7% win  (982 signals)
    BEAR regime:  56.0% win  (1,023 signals)
    FLAT regime:  49.2% win  (1,585 signals)
  reversal_radar_v2:
    FLAT regime:  54.4% win  (114 signals) ← reversal works best in flat!
    BULL regime:  53.9% win  (89 signals)
    BEAR regime:  47.3% win  (93 signals)  ← worst in trending bear
  twin_range_filter:
    BULL regime:  52.8% win  (443 signals)
    BEAR regime:  52.5% win  (448 signals)
    FLAT regime:  46.8% win  (727 signals)
```

### CRITICAL DISCOVERY 2: Time of Day Effects
```
Win rate by hour (IST), ALL strategies:
  09:xx IST:  62.7% win  (667 signals)   ← BEST HOUR
  10:xx IST:  54.3% win  (891 signals)
  11:xx IST:  51.2% win  (866 signals)
  12:xx IST:  52.0% win  (868 signals)
  13:xx IST:  50.3% win  (891 signals)
  14:xx IST:  50.3% win  (922 signals)
  15:xx IST:  43.9% win  (513 signals)   ← WORST HOUR

trend_signals_tp_sl_ualgo by hour:
  09:xx:  64.3% win  (28 signals)
  10:xx:  42.9% win  (14 signals)  ← BAD
  11:xx: 100.0% win   (8 signals)  ← tiny but perfect
  12:xx:  20.0% win  (10 signals)  ← TERRIBLE — loses 4 out of 5
  13:xx:  50.0% win  (14 signals)
  14:xx:  80.0% win  (15 signals)  ← second best hour
  15:xx:  66.7% win  (15 signals)
```

### CRITICAL DISCOVERY 3: Direction Asymmetry
```
trend_signals_tp_sl_ualgo:
  LONG  signals:  66.7% win  (78 signals)  ← much stronger
  SHORT signals:  42.3% win  (26 signals)  ← worse than random

reversal_radar_v2:
  LONG  signals:  52.9% win  (157 signals)
  SHORT signals:  51.1% win  (139 signals)  ← symmetrical

central_pivot_range:
  LONG  signals:  52.4% win  (1,788 signals)
  SHORT signals:  53.4% win  (1,802 signals)  ← slightly better short

bahai_reversal_points:
  LONG  signals: 100.0% win  (2 signals)   ← meaningless sample
  SHORT signals:  62.5% win  (8 signals)
```

### CRITICAL DISCOVERY 4: Monthly Stability
```
Monthly win rate (all strategies):
  2025-06:  52.4%  (578 signals)
  2025-07:  52.3%  (646 signals)
  2025-08:  58.8%  (582 signals)  ← strong month
  2025-09:  48.3%  (631 signals)  ← weak month
  2025-10:  50.1%  (593 signals)
  2025-11:  45.8%  (452 signals)  ← worst month (Nov sideways chop?)
  2025-12:  47.2%  (534 signals)
  2026-01:  58.5%  (643 signals)  ← strong month
  2026-02:  58.2%  (557 signals)  ← strong month
  2026-03:  47.0%  (402 signals)  ← current month, weak so far

Pattern: Aug, Jan, Feb are high-win months. Sep, Nov, Dec, Mar are low-win.
Hypothesis: market regime cycles exist on monthly timeframe.
```

### Parameter Optimization Results
```
Method: one-at-a-time sweep, ±30% grid, 7 values per parameter

WINNER: trend_signals_tp_sl_ualgo
  DEFAULT_MULTIPLIER = 2.6  →  60.9% win rate, 184 signals
  DEFAULT_ATR_PERIOD = 10   →  53.4% win rate
  DEFAULT_CLOUD_VAL  = 7    →  51.5% win rate
  Combined best params: 183 signals, 60.1% win (+8.6%pts vs default 51.5%)

  Mechanism: MULTIPLIER=2.6 creates wider ATR bands.
  Only fires when price breaks 2.6× ATR from its average.
  This filters weak breakouts and keeps only high-momentum moves.

twin_range_filter:
  Best combined: 3,708 signals, 48.3% (SLIGHTLY WORSE than default)
  Conclusion: insensitive to parameter tuning on this data

reversal_radar_v2:
  Best combined: 556 signals, 53.1% (+0.3%pts — marginal)

bahai_reversal_points:
  Best individual: DEFAULT_LOOKBACK_LENGTH=6 → 64.0% (25 signals)
  Combined: only 8 signals — statistically useless
```

### VWAP BB Analysis (adapter bypass, direct signal extraction)
```
Signal columns produced by vwap_bb_super_confluence_2:
  Upper_Confluence, Lower_Confluence
  touch_upper_vw, touch_upper_bb, touch_upper
  touch_lower_vw, touch_lower_bb, touch_lower
  upper_reversal, lower_reversal
  (+ 4 line level columns)

Interpretation:
  lower_reversal = True  →  buy signal  (price reversed up from lower VWAP+BB zone)
  upper_reversal = True  →  sell signal (price reversed down from upper VWAP+BB zone)
  Upper/Lower Confluence = zone detection only, NOT confirmed reversal

Default parameter results:
  upper_reversal (sell):     225 events   52.9% win   avg_fwd_return +0.017%
  lower_reversal (buy):      240 events   49.6% win   avg_fwd_return -0.005%
  upper_confluence (zone):   375 events   44.8% win   ← BELOW RANDOM
  lower_confluence (zone):   430 events   44.7% win   ← BELOW RANDOM

KEY INSIGHT: The zone itself has no edge. Only confirmed reversal bars have edge.
Zones are false positives 55% of the time. Reversed bars are correct 53% of the time.
The ADDITION of vwap_bb as a 3rd filter to 2-strategy combos = +11.7%pts improvement.

Best parameters for vwap_bb:
  bb_len1=30, bb_k1a=1.5, require_double_touch=False, vwap_k1=0.5, vwap_k2=3.0
```

### Confluence Optimizer — All 24 Valid Combinations
```
Method: rebuilt signal matrix with OPTIMIZED params + vwap_bb reversal
        tested all 2^6=64 subsets, 24 had >= 8 signals

Signal counts with optimized params:
  central_pivot_range:       4,333  (86.1% of bars)
  twin_range_filter:         3,708  (73.7%)
  vwap_bb_reversal:            630  (12.5%)
  reversal_radar_v2:           556  (11.1%)
  trend_signals_tp_sl_ualgo:   183  ( 3.6%)
  bahai_reversal_points:         8  ( 0.16%)

All 24 combinations (sorted by win rate):
Rank  Combo                                       Sigs  WinRate  LongWR  ShortWR
1     trend_signals + reversal_radar_v2              8   75.0%   66.7%   80.0%
2     trend_signals + vwap_bb_reversal              19   73.7%   66.7%   85.7%
3     twin_range + trend_signals + vwap_bb          19   73.7%   66.7%   85.7%
4     trend_signals + CPR + vwap_bb                 14   71.4%   66.7%   80.0%
5     twin_range + trend_signals + CPR + vwap_bb    14   71.4%   66.7%   80.0%
6     trend_signals + CPR                          136   64.0%   65.9%   60.4%
7     twin_range + trend_signals + CPR             100   62.0%   63.0%   60.9%
8     trend_signals (alone)                        182   60.4%   63.9%   55.4%
9     twin_range + trend_signals                   145   57.9%   60.3%   55.6%
10    twin_range + reversal_radar                  195   54.4%   49.5%   59.2%
11    reversal_radar + vwap_bb                      84   53.6%   53.8%   53.3%
12    reversal_radar (alone)                       556   53.1%   50.7%   55.2%
13    reversal_radar + CPR                         160   52.5%   45.7%   59.5%
14    twin_range + reversal_radar + CPR             99   51.5%   43.1%   60.4%
15    vwap_bb (alone)                              628   51.4%   50.8%   52.1%
16    bahai (alone)                                  8   50.0%   40.0%   66.7%
17    reversal_radar + CPR + vwap_bb                 8   50.0%   50.0%   50.0%
18    twin_range (alone)                          3,702  48.4%   47.8%   49.1%
19    twin_range + vwap_bb                         147   47.6%   52.0%   42.9%
20    twin_range + CPR                           2,563   47.6%   47.1%   48.0%
21    CPR (alone)                                4,325   47.2%   46.7%   47.8%
22    twin_range + reversal_radar + vwap_bb         28   46.4%   50.0%   43.8%
23    twin_range + CPR + vwap_bb                    63   46.0%   50.0%   39.1%
24    CPR + vwap_bb                                105   42.9%   46.2%   37.5%

False signal reduction proof:
  1 strategy average:  51.8% win rate
  2 strategies agree:  56.9% avg, 75.0% best
  3 strategies agree:  57.3% avg, 73.7% best
  4 strategies agree:  71.4% avg, 71.4% best

VWAP BB contribution:
  As 1st signal: 51.4% (barely above random)
  As 2nd filter with existing pair: -1.3%pts (neutral to slightly negative)
  As 3rd filter on 2-strategy combo: +11.7%pts (powerful)
```

---

## PART 5: KNOWN BUGS AND STRUCTURAL PROBLEMS

### Bug 1 — signal_strength = 1.0 for ALL rows (HIGH IMPACT)
```
WHAT HAPPENS: normalize_strategy_output() computes signal_strength = signal.abs() / max(signal.abs())
              When signal is always +1 or -1 (binary), max = 1, so ALL strengths = 1.0
IMPACT: setup_ranker.score() = win_rate + 1.0 * 0.25 (constant for every row)
        Signal strength carries ZERO information about trade quality
        The 0.25 bonus is cosmetic — it shifts all scores up equally
FIX NEEDED: Compute strength from the raw_frame output (e.g., how far price is from ATR band)
```

### Bug 2 — vwap_bb_super_confluence_2 gives 0 signals (HIGH IMPACT)
```
WHAT HAPPENS: signal_adapter searches for column names containing "buy/sell/bull/bear/long/short"
              vwap_bb outputs "upper_reversal" and "lower_reversal" — no match
IMPACT: This strategy appears to produce nothing. It has 630 actual signals being hidden.
FIX: In signal_adapter.py, add detection for upper_reversal/lower_reversal columns
     upper_reversal = True → signal = -1 (bearish)
     lower_reversal = True → signal = +1 (bullish)
```

### Bug 3 — Sharpe ratio incorrectly annualized (MEDIUM IMPACT)
```
CODE: sqrt(252) * mean(returns) / std(returns)
PROBLEM: 252 assumes 252 daily returns per year. Our system has ~100-200 trades/year.
FIX: sqrt(trades_per_year) or report raw mean/std without annualization
```

### Bug 4 — Feedback loop not connected (MEDIUM IMPACT)
```
daily_retrain.py appends paper trade records to feedback_store.csv
BUT: the retrain function builds candidates from build_sample_candidates() which
     generates toy samples — it never reads feedback_store.csv back into training
IMPACT: paper trade results have zero influence on model updates
FIX: read actual paper trade records, filter by current model_version,
     use real PnL outcomes to update strategy_scores in setup_ranker
```

### Bug 5 — Regime labeling threshold too small (MEDIUM IMPACT)
```
CODE: label = "bull" if forward_return > 0.002 (0.2%)
PROBLEM: RELIANCE 15m bars often move 0.3-0.5% randomly. 0.2% threshold creates noise labels.
         43% of bars are labeled "flat" — may be genuine or may be threshold too tight.
FIX: Use ATR-relative threshold: label = "bull" if forward_return > 0.5 * (ATR/close)
     This makes the threshold proportional to current volatility
```

### Bug 6 — backtest ATR uses simplified formula
```
CODE: atr_proxy = (high - low).rolling(14).mean()
CORRECT: ATR = max(high-low, |high-prev_close|, |low-prev_close|).rolling(14).mean()
IMPACT: ATR is underestimated on gap days (e.g., post-earnings bars)
```

### Structural Gap 7 — No out-of-sample validation anywhere
```
All win rates reported are IN-SAMPLE (parameters tuned on same data used to evaluate them)
This means: reported win rates are optimistic. True out-of-sample performance is unknown.
Required: 70/30 chronological split — optimize on first 70%, report ONLY on held-out 30%
```

### Structural Gap 8 — 19 of 25 strategies never tested
```
bollinger_band_breakout, candlestick_patterns_identified, cm_hourly_pivots,
dark_cloud_piercing_line, double_top_bottom_ultimate, harmonic_strategy,
hybrid_ml_vwap_bb, impulse_trend_boswaves, n_bar_reversal_luxalgo,
n_bar_reversal_luxalgo_strategy, outside_reversal, previous_candle_inside_outside,
sfp_candelacharts, three_inside_tradingfinder, vedhaviyash4_daily_cpr,
sbs_swing_areas_trades (and others)

These may contain hidden high-win-rate signals or powerful combination partners.
```

---

## PART 6: THE PROBABILISTIC FRAMEWORK — HOW TO THINK ABOUT THIS

### Each Signal as a Bayesian Vote
```
Prior probability of a profitable trade: 50% (random entry)

Each strategy signal is a vote that updates this probability.
The quality of the vote depends on:
  1. Base rate: what is this strategy's unconditional win rate?
  2. Conditional rate: what is its win rate given current regime + time + direction?
  3. Independence: how correlated is this signal with the other signals?

Bayesian update (simplified):
  P(win | signals S1, S2, S3) = P(win | S1) * P(win | S2) * P(win | S3) / normalizer
  (valid ONLY if S1, S2, S3 are independent — which they may NOT be)
```

### The Independence Question (most important unsolved problem)
```
When trend_signals + vwap_bb gives 73.7% win rate, is this because:
  A) They are independent signals capturing genuinely different information
     (momentum breakout + mean-reversion zone = real 2D edge)
  OR
  B) They are correlated — both fire at the same price extreme, so they're
     both measuring the same thing twice (pseudo-independence)

If A: adding more independent signals should keep improving win rate
If B: adding more signals gives diminishing returns and the apparent 73.7% is inflated

TO TEST THIS: compute signal correlation matrix
  Pearson correlation between all strategy signal columns
  Highly correlated pairs (>0.5) are redundant — no new information
  Low-correlation pairs (<0.2) are genuinely independent — true edge multipliers
```

### What the Regime-Direction Matrix Reveals
```
The most important finding so far (discovered but not fully exploited):

trend_signals_tp_sl_ualgo:
  In BULL regime  +  LONG direction: likely ~85%+ win rate
  In FLAT regime  +  LONG direction: likely ~25% win rate (LOSES MONEY)
  In FLAT regime  + SHORT direction: likely ~40% win rate

This means: THE SAME STRATEGY in different contexts has wildly different edge.
A flat-regime filter alone could transform a 60% strategy into an 80% strategy
by simply refusing to trade when the regime model says "flat".

The regime model currently IS BEING USED, but its predictions are fed into
recommend_latest() which picks the highest-confidence candidate regardless of
whether that candidate's strategy works well in the current regime.

MISSING: regime-conditional filtering in the recommendation system
```

### The Kelly Criterion for Strategy Selection
```
Kelly fraction = (win_rate * reward - loss_rate * risk) / reward
For a 2:1 reward:risk trade (target_2 vs stop_loss):
  reward = 2, risk = 1
  At 60% win rate: Kelly = (0.6*2 - 0.4*1)/2 = 0.5 (bet 50% of capital)
  At 50% win rate: Kelly = (0.5*2 - 0.5*1)/2 = 0.25 (bet 25%)
  At 45% win rate: Kelly = (0.45*2 - 0.55*1)/2 = 0.175 (still positive — trade!)
  At 33% win rate: Kelly = 0 (do NOT trade — expected value is zero)

For trend_signals in FLAT regime (36% win rate) with 2:1 R:R:
  Kelly = (0.36*2 - 0.64*1)/2 = 0.04 (barely above zero — NOT worth trading)

For trend_signals in BULL regime (79.6% win rate) with 2:1 R:R:
  Kelly = (0.796*2 - 0.204*1)/2 = 0.694 (bet 69% of capital — extremely high edge)

This single calculation proves why regime-conditional filtering is the most
important near-term improvement: it turns a marginal strategy into an exceptional one.
```

### Information Theory View (Mutual Information)
```
Each strategy provides I(strategy; outcome) bits of information about whether a trade wins.
If two strategies are perfectly correlated, combining them gives 0 additional bits.
If two strategies are perfectly independent, combining them roughly doubles the information.

The surprising finding (rank 1 vs rank 24):
  trend_signals + reversal_radar = 75% win (8 signals)
  CPR + vwap_bb = 42.9% win (105 signals) ← WORSE than either alone

This tells us:
  - CPR and vwap_bb are NEGATIVELY correlated as a pair
  - trend_signals and reversal_radar capture genuinely different information
  - The quality of information, not just the quantity of signals, determines the outcome

CPR fires at pivot crossings (trend continuation)
vwap_bb fires at band reversals (mean reversion)
These two are conceptually OPPOSITE — hence combining them creates confusion.
```

---

## PART 7: HYPOTHESES TO TEST NEXT

### Hypothesis 1: Regime-Filtered Confluence Will Approach 85%+ Win Rate
```
Current best: trend_signals + reversal_radar = 75% (8 signals, all regimes)
Expected result if filtered to BULL+BEAR regimes only:
  Removes flat-regime signals (where trend_signals = 36% win)
  Should push win rate toward 80-85%

TEST:
  matrix = existing signal matrix from confluence_optimizer
  regime_frame = regime labels per bar
  for each combo, evaluate win rate ONLY on bars where regime_label != "flat"
  Compare vs full-regime win rates
```

### Hypothesis 2: Morning Session Filter Adds 5-8%pts to Every Strategy
```
09:xx IST has 62.7% win rate vs 15:xx IST has 43.9% win rate.
If morning session is filtered (only take signals in 09:15-10:30 IST window):
  - Signal count drops by ~80% (only ~120 min of 375 min session)
  - But win rate should rise significantly for all strategies

TEST: Add hour filter to confluence_optimizer.py
  morning_mask = ist_hour.isin([9, 10])
  Compare win rates for morning-only vs all-day signals
```

### Hypothesis 3: The 19 Untested Strategies Contain at Least 2 Hidden Gems
```
Among the 19 untested strategies, based on role tags:
  Most likely to be independent signals (not correlated with trend_signals):
    sfp_candelacharts (swing failure pattern — pure price action, no ATR)
    candlestick_patterns_identified (pattern recognition — different mechanism)
    outside_reversal (price action reversal — not ATR-based)

  Most likely to conflict (correlated with existing signals):
    impulse_trend_boswaves (trend-following, likely correlated with twin_range)
    bollinger_band_breakout (breakout, likely correlated with trend_signals)

TEST: Run all 19 through confluence_optimizer.py individually, then check
      correlations with the top 6 existing strategies.
      Any strategy with:
        - Base win rate > 53%
        - Signal correlation < 0.3 with trend_signals
        = Candidate for inclusion in new combo search
```

### Hypothesis 4: Combining Regime Filter + Time Filter + Best Combo Exceeds 85% Win Rate
```
This is the compound hypothesis:
  trend_signals + reversal_radar  →  75.0% (8 signals, no filters)
  + BULL/BEAR regime only          →  ~80%  (maybe 6 signals)
  + Morning session only           →  ~85%  (maybe 4 signals)
  + LONG direction only            →  ~88%  (maybe 3 signals)

The problem: only 3-4 signals over 9 months = 4-6 trades per year.
Too rare for reliable paper trading or statistical proof.

TRADE-OFF ANALYSIS:
  Each filter adds win rate but removes signals.
  The OPTIMAL filter is the one that maximizes EXPECTED VALUE:
    EV = win_rate * avg_win_pct - loss_rate * avg_loss_pct * n_trades
  Not just maximum win rate.
```

### Hypothesis 5: vwap_bb Reversal Quality Differs by Market Phase
```
vwap_bb is a mean-reversion indicator. It should work:
  BEST in: range-bound (flat) markets where price bounces between bands
  WORST in: strong trending markets where price breaks bands and keeps going

We know from the regime data:
  reversal_radar ALSO works best in flat regime (54.4% flat vs 47.3% bear)
  Both are reversal-type indicators

TEST: For vwap_bb signals, compute win rate split by regime_label
      Expected: flat regime vwap_bb win rate > bear/bull
      If true: use vwap_bb ONLY in flat regime, use trend_signals in bull/bear
      This creates a regime-switching strategy: different tools for different markets
```

### Hypothesis 6: The 15m Primary Signal With 1hr Regime Filter Is Underused
```
Current setup: 1hr and 1day are used as CONFIRMATION (trend agreement)
Alternative:   Use 1hr regime to FILTER 15m trade direction
  Step 1: Classify 1hr bars as bull/bear/flat using regime model
  Step 2: On 15m, only take LONG entries when 1hr regime = bull
  Step 3: On 15m, only take SHORT entries when 1hr regime = bear
  Step 4: Skip all trades when 1hr regime = flat

This is the classic multi-timeframe trading technique.
The data exists. The 1hr CSV is already loaded.
The regime model can run on 1hr data.
This experiment has NOT been run.
```

---

## PART 8: THREE CURRENT WORKING CONFIGS

### Config A — Best Balance (use for paper trading)
```json
{
  "name": "active_trader",
  "strategies": ["trend_signals_tp_sl_ualgo", "central_pivot_range"],
  "params": {
    "trend_signals_tp_sl_ualgo": {
      "DEFAULT_MULTIPLIER": 2.6,
      "DEFAULT_ATR_PERIOD": 10,
      "DEFAULT_CLOUD_VAL": 7,
      "DEFAULT_STOP_LOSS_PCT": 1.4
    }
  },
  "win_rate": "64.0%",
  "signals_per_dataset": 136,
  "signal_frequency": "~1 per 2 trading days",
  "long_win_rate": "65.9%",
  "short_win_rate": "60.4%",
  "statistical_reliability": "HIGH — 136 samples, CI: 55%-72%"
}
```

### Config B — Recommended (best win rate with reasonable sample)
```json
{
  "name": "balanced_swing",
  "strategies": ["twin_range_filter", "trend_signals_tp_sl_ualgo", "vwap_bb_reversal"],
  "params": {
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10},
    "vwap_bb_super_confluence_2": {
      "bb_len1": 30, "bb_k1a": 1.5,
      "require_double_touch": false,
      "vwap_k1": 0.5, "vwap_k2": 3.0
    }
  },
  "win_rate": "73.7%",
  "signals_per_dataset": 19,
  "signal_frequency": "~1 per 16 trading days",
  "long_win_rate": "66.7%",
  "short_win_rate": "85.7%",
  "warning": "Only 19 signals — CI: 51%-91%. Needs more data."
}
```

### Config C — High Conviction (research use only)
```json
{
  "name": "ultra_selective",
  "strategies": ["trend_signals_tp_sl_ualgo", "reversal_radar_v2"],
  "params": {
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6},
    "reversal_radar_v2": {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7}
  },
  "win_rate": "75.0%",
  "signals_per_dataset": 8,
  "signal_frequency": "~1 per month",
  "short_win_rate": "80.0%",
  "warning": "8 signals — CI: 37%-100%. STATISTICALLY UNRELIABLE. Do not trade live."
}
```

---

## PART 9: WHAT TO BUILD NEXT — PRIORITY ORDER

### Immediate (1-2 sessions, highest impact)

**Task A — Regime-conditional win rate analysis**
Run the confluence_optimizer but add a regime filter:
```python
# In confluence_optimizer.py, after building matrix:
regime = pd.read_csv('artifacts_template/reports/reliance_swing_15m_20260321T174222Z/regime_frame.csv')
matrix = matrix.merge(regime[['datetime','regime_label']], on='datetime', how='left')

# Evaluate each combo 4 ways:
# 1. All regimes (current)
# 2. Non-flat only (regime_label != 'flat')
# 3. Bull regime only
# 4. Bear regime only
```
Expected: win rates jump 5-15%pts when flat regime is excluded.

**Task B — Fix signal adapter for vwap_bb**
Add to strategies/signal_adapter.py, inside normalize_strategy_output():
```python
if not signal_parts:
    if "lower_reversal" in frame.columns or "upper_reversal" in frame.columns:
        sig = pd.Series(0, index=frame.index, dtype=int)
        if "lower_reversal" in frame.columns:
            sig[frame["lower_reversal"].astype(bool)] = 1
        if "upper_reversal" in frame.columns:
            sig[frame["upper_reversal"].astype(bool)] = -1
        signal_parts.append(sig)
        notes.append("vwap_bb: extracted from upper_reversal/lower_reversal")
```

**Task C — Morning session filter analysis**
```python
# In confluence_optimizer.py, add IST hour to matrix:
import pandas as pd
matrix['datetime_dt'] = pd.to_datetime(matrix['datetime'], utc=True)
matrix['ist_hour'] = matrix['datetime_dt'].apply(lambda x: x.tz_convert('Asia/Kolkata').hour)
morning_mask = matrix['ist_hour'].isin([9, 10])

# Re-run all evaluations on morning_mask only
# Expected: all win rates increase by ~5%pts
```

### Medium Term (3-5 sessions)

**Task D — Test all 19 untested strategies**
Load ALL strategies from D:\test1\, run each individually on RELIANCE 15m.
For each strategy:
  - Record base win rate and signal count
  - Compute signal correlation with top 6 existing strategies
  - If win_rate > 53% AND correlation < 0.3 with trend_signals → add to candidate list
  - Run extended confluence optimizer with new candidates

**Task E — Build proper signal_strength from raw output**
For each strategy's raw_frame, compute a real quality measure:
```python
# Example for trend_signals: distance from ATR band = strength
# Example for central_pivot_range: distance from CPR level = strength
# Example for reversal_radar: reversal bar size / ATR = strength
```
Replace the broken signal_strength=1.0 constant with real values.
Then the setup_ranker's 0.25 weight becomes meaningful.

**Task F — Replace centroid model with LightGBM or XGBoost**
```python
# In train_regime_model.py, replace CentroidRegimeModel with:
from lightgbm import LGBMClassifier
model = LGBMClassifier(n_estimators=100, max_depth=4, learning_rate=0.05)
model.fit(X_train, y_train)
# Expected: regime prediction accuracy improves from ~55% to 65-70%
# This is the highest-leverage model improvement available
```

**Task G — Implement rolling walk-forward validation**
```python
def rolling_walk_forward(df, train_bars=2500, test_bars=500, step_bars=250):
    results = []
    for start in range(0, len(df) - train_bars - test_bars, step_bars):
        train = df.iloc[start : start + train_bars]
        test  = df.iloc[start + train_bars : start + train_bars + test_bars]
        # train model on train, evaluate on test
        # collect test metrics only
    return pd.DataFrame(results)
```
This will reveal which win rates hold out-of-sample and which are overfitted.

### Longer Term (5-10 sessions)

**Task H — Multi-symbol expansion**
Run the same pipeline on NIFTY, BANKNIFTY, TCS, INFY, HDFC.
Compare which strategies and combinations generalize across symbols.
A combination that works on 4+ symbols is much more trustworthy than
one that only works on RELIANCE.

**Task I — Higher timeframe as primary signal**
Instead of 15m primary with 1hr confirmation, try:
  - 1hr primary, 1day confirmation (fewer, higher-quality swing trades)
  - 4hr primary, 1day confirmation (multi-day swing)
The same strategy code works unchanged. Just change the config.

**Task J — Implement paper trading feedback loop**
Fix daily_retrain.py to:
  1. Read paper trade outcomes from feedback_store.csv
  2. For each paper trade: find the matching signal in candidate_frame
  3. Update strategy_scores in setup_ranker based on recent actual PnL
  4. Weight recent trades more heavily than historical (decay factor)
  5. Track model performance over time

---

## PART 10: STATISTICAL RULES — WHEN TO TRUST A WIN RATE

```
Sample Size → 95% Wilson Confidence Interval half-width:
  n=8   signals at 75% win:  actual range is 37% – 100%  (DO NOT TRUST)
  n=19  signals at 74% win:  actual range is 51% – 91%   (WEAK)
  n=50  signals at 65% win:  actual range is 51% – 77%   (MODERATE)
  n=100 signals at 64% win:  actual range is 54% – 73%   (GOOD)
  n=200 signals at 60% win:  actual range is 53% – 67%   (SOLID)

Rule of thumb: NEVER trust a win rate based on fewer than 50 signals.
For live trading decisions: require at least 100 signals.

For our current best configs:
  Config C (8 signals, 75%): DO NOT USE FOR LIVE TRADING
  Config B (19 signals, 74%): PAPER TRADE ONLY, need 3x more data
  Config A (136 signals, 64%): ACCEPTABLE for paper trading
```

---

## PART 11: THE CORE INSIGHT (SUMMARIZED)

The fundamental question this system is trying to answer is:
**"Given that multiple independent mechanisms agree a move is likely, how much does probability increase?"**

What we found:
1. Each additional independent strategy agreement raises win probability by ~2-3%
2. The biggest gains come from regime-conditional filtering (not adding more strategies)
3. The time of day matters enormously — morning session is 18%pts better than afternoon
4. Strategy direction asymmetry exists: trend_signals is a good LONG indicator but unreliable SHORT
5. Some pairs conflict (CPR + vwap_bb = 43% = actively bad)
6. The strategy type matters: trend + reversal is more complementary than trend + trend

The next frontier is not more strategies — it is conditional probability:
**"What is the win rate of strategy X specifically when regime=Y, hour=Z, direction=D?"**

This 4-dimensional conditional probability matrix has not been computed.
When it is, we will know exactly when to trade, what to trade, and in which direction.
That is the target.

---

## APPENDIX: COMMAND REFERENCE

```bash
# Activate environment (always run first)
cd C:\Users\sakth\Desktop\vayu && source .venv/Scripts/activate

# PYTHONPATH (always set)
export PYTHONPATH=D:/ml/stock_advisor_starter_pack/local_project/src

# Train bundle (full run, ~30 seconds)
cd D:/ml/stock_advisor_starter_pack/local_project
python -m models.train_reliance_swing_bundle

# Run parameter optimizer (~5 minutes)
python scripts/param_optimizer.py

# Run vwap_bb analysis (~2 minutes)
python scripts/vwap_bb_reversal_analysis.py

# Run confluence optimizer (~3 minutes)
python scripts/confluence_optimizer.py

# Run tests
python -m pytest tests/ -v

# Key output files to read after any run:
#   artifacts_template/reports/<bundle>/strategy_success_summary.csv
#   artifacts_template/reports/confluence_optimizer/all_combos.csv
#   artifacts_template/reports/param_optimization/optimization_summary.csv
```
