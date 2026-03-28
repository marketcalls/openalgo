# VAYU Dashboard Port to OpenAlgo — Full Design Spec

## Context

The VAYU project (`C:\Users\sakth\Desktop\vayu\`) has a rich trading analysis dashboard with 6 sub-tabs: Technical, Strategies, Decision, Fundamental, Why Not, Multi-TF. OpenAlgo (`D:\openalgo\`) already has a simpler AIAnalyzer page with some overlapping features. This spec defines how to port VAYU's full dashboard into OpenAlgo — merging where features overlap, porting where they don't.

**Source of truth:** VAYU codebase for feature parity
**Integration target:** OpenAlgo frontend (React 19, TailwindCSS v4, shadcn/ui, lightweight-charts v5)
**Quality bar:** Better than VAYU — cleaner UX, better explanations, less clutter, OpenAlgo-native

---

## 1. Page Architecture

### Current AIAnalyzer Structure (3 tabs)
```
[Analysis] [Scanner] [History]
```

### New Structure (6 analysis tabs + 2 utility tabs)
```
Primary:   [Technical] [Strategies] [Decision] [Fundamental] [Why Not] [Multi-TF]
Secondary: [Scanner] [History]
```

### Shared Header (all tabs)
- Symbol input + Exchange selector + Interval selector + Analyze button
- LivePriceHeader (existing component)
- All tabs share the same symbol/exchange/interval/analysis data context

### Data Flow
```
User selects symbol → useAIAnalysis hook fetches data → all tabs consume same result
                    → useStrategies hooks fetch strategy-specific data (lazy, per-tab)
                    → useMultiTimeframe fetches multi-TF data (lazy, when Multi-TF tab active)
```

### File: `pages/AIAnalyzer.tsx`
- **Modify** existing file
- Replace current 3-tab Tabs component with 8-tab layout (6 primary + 2 secondary)
- Keep all existing imports, add new ones
- Each tab content is a separate component for maintainability

---

## 2. Tab 1: Technical

**Purpose:** Signal overview + chart + indicators + patterns (matches VAYU's Technical sub-tab)

### Layout
```
┌─ Chart (2/3 width) ──────────────┐ ┌─ Signal Panel (1/3) ──────────┐
│ ChartWithIndicators               │ │ SignalBadge (STRONG_BUY etc)   │
│ [EMA] [SMA] [BB] [ST] [Levels]   │ │ SignalGauge (semicircular) NEW │
│ + Candlestick overlays            │ │ ConfidenceGauge (circular)     │
│                                   │ │ SubScoresChart (6 bars)        │
│                                   │ │ MLConfidenceBar                │
│                                   │ │ Market Regime badge            │
└───────────────────────────────────┘ └────────────────────────────────┘

┌─ Candlestick Patterns (1/3) ─────┐ ┌─ S/R Levels (1/3) ──┐ ┌─ Indicators (1/3) ──┐
│ CandlestickPatternsPanel NEW      │ │ SupportResistance NEW│ │ IndicatorTable       │
│ Pattern name, direction, strength │ │ R1/R2/R3, Pivot,     │ │ (existing)           │
│                                   │ │ S1/S2/S3             │ │                      │
└───────────────────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

### Components to Create
| Component | Source | Action |
|-----------|--------|--------|
| `SignalGauge.tsx` | VAYU `Prediction/SignalGauge.tsx` | Port — semicircular gauge (-1 to +1) |
| `CandlestickPatternsPanel.tsx` | VAYU `Prediction/CandlestickPatterns.tsx` | Port — pattern list with direction badges |
| `SupportResistancePanel.tsx` | VAYU `Prediction/SupportResistanceLevels.tsx` | Port — R/S level display |

### Components to Reuse (existing OpenAlgo)
- ChartWithIndicators, SignalBadge, ConfidenceGauge, SubScoresChart, MLConfidenceBar, IndicatorTable

### Container Component
- **Create:** `components/ai-analysis/tabs/TechnicalTab.tsx`

---

## 3. Tab 2: Strategies

**Purpose:** Deep strategy analysis with 5 sub-strategies (matches VAYU's Strategies sub-tab)

### Layout
```
┌─ Chart (1/2 width) ──────────────┐ ┌─ Strategy Panel (1/2) ─────────────┐
│ ChartWithIndicators               │ │ [Fibonacci] [Harmonic] [Elliott]    │
│ + strategy-specific overlays      │ │ [Smart Money] [Hedge Fund]          │
│                                   │ │                                     │
│                                   │ │ (Active strategy panel renders here)│
│                                   │ │ + TradeSetupCard per strategy       │
│                                   │ │                                     │
└───────────────────────────────────┘ └─────────────────────────────────────┘
```

### Components to Create
| Component | Source | Action |
|-----------|--------|--------|
| `StrategySelector.tsx` | VAYU `Strategy/StrategySelector.tsx` | Port — 5-tab strategy switcher |
| `FibonacciPanel.tsx` | VAYU `Strategy/FibonacciPanel.tsx` | Port — Fib levels, retracements, extensions |
| `HarmonicPanel.tsx` | VAYU `Strategy/HarmonicPanel.tsx` | Port — Gartley, Butterfly, Bat, Crab patterns |
| `ElliottWavePanel.tsx` | VAYU `Strategy/ElliottWavePanel.tsx` | Port — 5-wave impulse, ABC correction |
| `SmartMoneyPanel.tsx` | VAYU `Strategy/SmartMoneyPanel.tsx` | Port — OBs, FVGs, sweeps, structure breaks |
| `HedgeFundPanel.tsx` | VAYU `Strategy/HedgeStrategyPanel.tsx` | Port — mean reversion, momentum, vol regime |

### Container Component
- **Create:** `components/ai-analysis/tabs/StrategiesTab.tsx`

### Backend API Endpoints Needed
| Endpoint | Backend Module | Status |
|----------|---------------|--------|
| `POST /api/v1/agent/fibonacci` | `ai/indicators_lib/custom/fibonacci_levels.py` | Wire existing |
| `POST /api/v1/agent/harmonic` | `ai/indicators_lib/custom/harmonic_patterns.py` | Wire existing |
| `POST /api/v1/agent/elliott-wave` | New — port from VAYU backend | Create |
| `POST /api/v1/agent/smart-money` | `ai/indicators_lib/custom/smc_*.py` | Wire existing |
| `POST /api/v1/agent/hedge-strategy` | New — port from VAYU backend | Create |

### Data Hooks to Create
| Hook | Endpoint | Cache |
|------|----------|-------|
| `useFibonacci(symbol, exchange, interval)` | `/api/v1/agent/fibonacci` | 60s |
| `useHarmonic(symbol, exchange, interval)` | `/api/v1/agent/harmonic` | 60s |
| `useElliottWave(symbol, exchange, interval)` | `/api/v1/agent/elliott-wave` | 60s |
| `useSmartMoney(symbol, exchange, interval)` | `/api/v1/agent/smart-money` | 60s |
| `useHedgeStrategy(symbol, exchange, interval)` | `/api/v1/agent/hedge-strategy` | 60s |

---

## 4. Tab 3: Decision

**Purpose:** Single unified "what to do" recommendation with full evidence chain (VAYU StrategyDecisionPanel enhanced)

### Layout
```
┌─ Decision Header ─────────────────────────────────────────────────────────┐
│ 🟢 BUY NOW — High Conviction (72/100)                                    │
│ "Bullish continuation with multi-strategy confirmation"                   │
└───────────────────────────────────────────────────────────────────────────┘

┌─ Trade Levels (1/3) ──────────┐ ┌─ Confluence (1/3) ───────┐ ┌─ Position (1/3) ──────┐
│ Entry: ₹1,413.60              │ │ Confluence: 78%           │ │ Qty: 63 shares        │
│ SL: ₹1,397.80 (-1.1%)        │ │ ○ Circular ring           │ │ Risk: ₹1,000 (1%)     │
│ T1: ₹1,429.40 (1:1.0)        │ │ Bullish: 7 | Bearish: 2  │ │ Position: ₹89,057     │
│ T2: ₹1,445.20 (1:2.0)        │ │ Neutral: 1               │ │ R:R = 1:1.0           │
│ T3: ₹1,461.00 (1:3.0)        │ │                           │ │                       │
└───────────────────────────────┘ └───────────────────────────┘ └───────────────────────┘

┌─ Voting Breakdown ──────────────────────────────────────────────────────┐
│ Signal ✓ | SMC ✓ | Fibonacci ✓ | Harmonic ✗ | Elliott ✓ | Momentum ✓  │
│ Patterns ✓ | Mean Rev ✗ | S/R ✓                                        │
└─────────────────────────────────────────────────────────────────────────┘

┌─ Signal Overview (1/2) ───────────┐ ┌─ Smart Money Context (1/2) ────────┐
│ Signal: BUY (72% confidence)      │ │ Bias: Bullish                       │
│ Regime: TRENDING_UP               │ │ Active OBs: 2 (1380-1390)          │
│ Score: +0.68                      │ │ Unfilled FVGs: 1                    │
│ Momentum: Bullish                 │ │ Last Break: BOS at 1405             │
└───────────────────────────────────┘ └─────────────────────────────────────┘

┌─ Risk Metrics ────────────────────┐ ┌─ AI Commentary ─────────────────────┐
│ Vol Regime: Normal                │ │ 🤖 RELIANCE shows bullish setup...  │
│ HV: 18.2%                        │ │ supported by multiple strategies... │
│ VaR 95%: -2.3%                   │ │ [Refresh]                          │
│ Max DD: -5.1%                    │ │                                     │
└───────────────────────────────────┘ └─────────────────────────────────────┘

┌─ Evidence Chain (full width) ─────────────────────────────────────────────┐
│ • Supertrend confirmed bullish at ₹1,402                                  │
│ • EMA 9 crossed above EMA 21 (Golden cross)                             │
│ • RSI at 58 — bullish but not overbought                                │
│ • SMC: Price reclaimed order block at ₹1,400                            │
│ • Fibonacci: Bounced off 61.8% retracement                              │
│ • Candlestick: Bullish engulfing on daily                               │
└───────────────────────────────────────────────────────────────────────────┘
```

### Components to Create
| Component | Source | Action |
|-----------|--------|--------|
| `StrategyDecisionPanel.tsx` | VAYU `Strategy/StrategyDecisionPanel.tsx` | Port + merge with existing DecisionCard |
| `ConfluenceMeter.tsx` | VAYU (part of StrategyDecisionPanel) | Extract as reusable component |
| `VotingBreakdown.tsx` | VAYU (part of StrategyDecisionPanel) | Extract as reusable component |
| `EvidenceChain.tsx` | VAYU (part of StrategyDecisionPanel) | Extract — list of reasoning bullets |

### Components to Reuse
- DecisionCard (header portion), TradeSetupCard, RiskCalculator, LLMCommentary

### Container Component
- **Create:** `components/ai-analysis/tabs/DecisionTab.tsx`

### Backend Endpoint
| Endpoint | What |
|----------|------|
| `POST /api/v1/agent/strategy-decision` | Combine all strategy results + generate confluence + evidence chain |

---

## 5. Tab 4: Fundamental

**Purpose:** Fundamental data (P/E, P/B, ROCE, debt, revenue, EPS) — Phase 3 placeholder

### Layout
```
┌─ Coming Soon ─────────────────────────────────────────────────────────────┐
│ 📊 Fundamental Analysis                                                    │
│                                                                            │
│ This tab will include:                                                     │
│ • P/E Ratio, P/B Ratio, ROCE                                             │
│ • Debt-to-Equity, Current Ratio                                           │
│ • Revenue Growth (3Y, 5Y)                                                 │
│ • EPS Trend and Forecast                                                  │
│ • Sector Comparison                                                        │
│ • Quarterly Results Summary                                                │
│                                                                            │
│ [Coming in Phase 3]                                                       │
└───────────────────────────────────────────────────────────────────────────┘
```

### Component
- **Create:** `components/ai-analysis/tabs/FundamentalTab.tsx` (placeholder with roadmap)

---

## 6. Tab 5: Why Not

**Purpose:** Counter-thesis, risk factors, thesis invalidators — Phase 2 placeholder with basic implementation

### Layout
```
┌─ Why NOT to take this trade ──────────────────────────────────────────────┐
│                                                                            │
│ ⚠️ Risk Factors                                                           │
│ • [From opposing_signals in DecisionCard]                                 │
│ • [From risk_warning in DecisionCard]                                     │
│                                                                            │
│ 🔴 Thesis Invalidators                                                    │
│ • Price closes below ₹1,397.80 (SL level)                               │
│ • RSI drops below 40 (momentum loss)                                     │
│ • Volume dries up below 20-day average                                   │
│                                                                            │
│ 📉 Worst Case Scenario                                                    │
│ • Max loss: ₹1,000 (1% of account)                                      │
│ • If SL hits: -1.1% per share                                            │
│ • If gap down: Could exceed SL                                           │
│                                                                            │
│ 💡 What Would Change My Mind                                              │
│ • Trend reversal on daily (Supertrend flips bearish)                     │
│ • Break below support at ₹1,380                                         │
│ • Negative earnings surprise                                              │
└───────────────────────────────────────────────────────────────────────────┘
```

### Component
- **Create:** `components/ai-analysis/tabs/WhyNotTab.tsx`
- Uses existing `decision.opposing_signals`, `decision.risk_warning`, `trade_setup.stop_loss`
- Generates invalidator conditions from indicator thresholds
- No new backend endpoint needed — derived from existing analysis data

---

## 7. Tab 6: Multi-TF

**Purpose:** Multi-timeframe confluence analysis (port from VAYU MultiTimeframePanel)

### Layout
```
┌─ Multi-Timeframe Confluence ──────────────────────────────────────────────┐
│ Overall: 🟢 BULLISH (Agreement: 75%)    Score: +0.5432                   │
│ Aligned: 1H, 1D, 1W    Conflicting: 5m, 15m                            │
│ ██████████████████████░░░░░░░░ 75% Agreement                             │
└───────────────────────────────────────────────────────────────────────────┘

┌─ Per-Timeframe Breakdown ─────────────────────────────────────────────────┐
│ TF     │ Signal     │ Score  │ Confidence │ Regime       │                │
│ 5m     │ 🔴 SELL    │ -0.23  │ ██░░ 38%   │ Volatile     │                │
│ 15m    │ 🟡 HOLD    │ +0.05  │ ██░░ 42%   │ Ranging      │                │
│ 1H     │ 🟢 BUY     │ +0.48  │ ████ 65%   │ Trending Up  │                │
│ 1D     │ 🟢 BUY     │ +0.68  │ █████ 72%  │ Trending Up  │                │
│ 1W     │ 🟢 BUY     │ +0.55  │ ████ 61%   │ Trending Up  │                │
│ 1M     │ 🟢 BUY     │ +0.72  │ █████ 78%  │ Trending Up  │                │
└───────────────────────────────────────────────────────────────────────────┘
```

### Component
- **Create:** `components/ai-analysis/tabs/MultiTFTab.tsx`
- **Create:** `components/ai-analysis/MultiTimeframePanel.tsx` (port from VAYU)

### Backend Endpoint
| Endpoint | What |
|----------|------|
| `POST /api/v1/agent/multi-timeframe` | Run analysis on 5m, 15m, 1H, 1D, 1W, 1M and compute confluence |

### Data Hook
- `useMultiTimeframe(symbol, exchange)` → calls `/api/v1/agent/multi-timeframe`

---

## 8. Backend API Changes

### New Endpoints (in `restx_api/ai_agent.py`)

| # | Endpoint | Method | Backend Logic |
|---|----------|--------|---------------|
| 1 | `/api/v1/agent/fibonacci` | POST | Call `indicators_lib/custom/fibonacci_levels.py` on OHLCV |
| 2 | `/api/v1/agent/harmonic` | POST | Call `indicators_lib/custom/harmonic_patterns.py` on OHLCV |
| 3 | `/api/v1/agent/smart-money-detail` | POST | Call `smc_bos.py`, `smc_choch.py`, `smc_fvg.py`, `smc_ob.py` |
| 4 | `/api/v1/agent/elliott-wave` | POST | New module — port from VAYU backend |
| 5 | `/api/v1/agent/hedge-strategy` | POST | New module — mean reversion, momentum, vol regime |
| 6 | `/api/v1/agent/strategy-decision` | POST | Combine all strategies → confluence → evidence chain |
| 7 | `/api/v1/agent/multi-timeframe` | POST | Run `analyze_symbol()` across 6 intervals → compute confluence |
| 8 | `/api/v1/agent/patterns` | POST | Candlestick pattern detection (existing `indicators_advanced.py`) |
| 9 | `/api/v1/agent/support-resistance` | POST | S/R levels from pivots + Fibonacci |

### New Backend Service
- **Create:** `services/strategy_analysis_service.py` — orchestrates all strategy computations

### Existing Backend to Reuse
| Module | Already Has |
|--------|-------------|
| `ai/indicators_lib/custom/fibonacci_levels.py` | Fibonacci retracement/extension levels |
| `ai/indicators_lib/custom/harmonic_patterns.py` | Gartley, Butterfly, Bat, Crab detection |
| `ai/indicators_lib/custom/smc_bos.py` | Break of Structure |
| `ai/indicators_lib/custom/smc_choch.py` | Change of Character |
| `ai/indicators_lib/custom/smc_fvg.py` | Fair Value Gaps |
| `ai/indicators_lib/custom/smc_ob.py` | Order Blocks |
| `ai/indicators_lib/custom/swing_structure.py` | Swing high/low detection |
| `ai/indicators_advanced.py` | Candlestick patterns, harmonics, divergence |
| `ai/trend_analysis.py` | Trend direction + strength |
| `ai/momentum_analysis.py` | Momentum bias |
| `ai/oi_analysis.py` | OI-based bias (PCR, Max Pain) |

---

## 9. New Frontend Files Summary

### Tab Container Components (6 files)
```
frontend/src/components/ai-analysis/tabs/
├── TechnicalTab.tsx        # Technical analysis (chart + signals + patterns)
├── StrategiesTab.tsx       # 5 strategy panels
├── DecisionTab.tsx         # Full decision with confluence + evidence
├── FundamentalTab.tsx      # Placeholder (Phase 3)
├── WhyNotTab.tsx           # Risk factors + invalidators
└── MultiTFTab.tsx          # Multi-timeframe confluence
```

### New Components (14 files)
```
frontend/src/components/ai-analysis/
├── SignalGauge.tsx              # Semicircular buy/sell gauge
├── CandlestickPatternsPanel.tsx # Detected patterns with direction
├── SupportResistancePanel.tsx   # R1/R2/R3, Pivot, S1/S2/S3
├── StrategySelector.tsx (rename from IndicatorSelector) # 5-strategy tab switcher
├── FibonacciPanel.tsx           # Fib levels, retracements, extensions
├── HarmonicPanel.tsx            # Gartley, Butterfly, Bat, Crab
├── ElliottWavePanel.tsx         # 5-wave impulse, ABC correction
├── SmartMoneyDetailPanel.tsx    # OBs, FVGs, sweeps, structure breaks
├── HedgeFundPanel.tsx           # Mean reversion, momentum, vol regime
├── StrategyDecisionPanel.tsx    # Full decision (replaces simple DecisionCard usage)
├── ConfluenceMeter.tsx          # Circular confluence ring
├── VotingBreakdown.tsx          # Strategy voting badges
├── EvidenceChain.tsx            # Reasoning bullets
└── MultiTimeframePanel.tsx      # Multi-TF table + agreement bar
```

### New Hooks (6 files)
```
frontend/src/hooks/
├── useFibonacci.ts
├── useHarmonic.ts
├── useElliottWave.ts
├── useSmartMoneyDetail.ts
├── useHedgeStrategy.ts
└── useMultiTimeframe.ts
```

### New Types
```
frontend/src/types/
└── strategy-analysis.ts   # Fibonacci, Harmonic, Elliott, SMC, Hedge, Decision, MultiTF types
```

### Modified Files
```
frontend/src/pages/AIAnalyzer.tsx          # Restructure to 8 tabs
frontend/src/components/ai-analysis/index.ts # Add new exports
frontend/src/types/ai-analysis.ts          # Add strategy-related types (or separate file)
```

---

## 10. Feature Merge Strategy

| OpenAlgo Feature | VAYU Equivalent | Resolution |
|---|---|---|
| DecisionCard | StrategyDecisionPanel | **Enhance** — DecisionCard becomes header of DecisionTab; StrategyDecisionPanel adds confluence, voting, evidence |
| AdvancedSignalsPanel | SmartMoneyPanel + CandlestickPatterns | **Split** — SMC gets own detailed panel; patterns get own panel; AdvancedSignalsPanel stays as summary |
| ChartWithIndicators | CandlestickChart + IndicatorOverlay | **Keep** — already equivalent. Add strategy-specific overlays later |
| SubScoresChart | SubSignalBars | **Keep** — already equivalent |
| ConfidenceGauge | ConfidenceMeter | **Keep** — already equivalent |
| LLMCommentary | (not in VAYU) | **Keep** — unique to OpenAlgo, add to Decision tab |
| RiskCalculator | (part of StrategyDecisionPanel) | **Keep** — reuse in Decision tab |

---

## 11. Implementation Order

### Phase A: Shell + Technical Tab (Session 1)
1. Restructure AIAnalyzer.tsx with 8 tabs
2. Create TechnicalTab.tsx (reuse existing components)
3. Port SignalGauge, CandlestickPatternsPanel, SupportResistancePanel
4. Create backend endpoints: `/agent/patterns`, `/agent/support-resistance`

### Phase B: Strategies Tab (Session 2)
1. Create StrategySelector + 5 strategy panels
2. Create backend endpoints: `/agent/fibonacci`, `/agent/harmonic`, `/agent/smart-money-detail`
3. Create backend modules for Elliott Wave, Hedge Strategy
4. Create all strategy hooks

### Phase C: Decision + Multi-TF (Session 3)
1. Create StrategyDecisionPanel, ConfluenceMeter, VotingBreakdown, EvidenceChain
2. Create MultiTimeframePanel
3. Create backend endpoints: `/agent/strategy-decision`, `/agent/multi-timeframe`
4. Create WhyNotTab (derived from existing data)
5. Create FundamentalTab placeholder

### Phase D: Polish (Session 4)
1. UX improvements (spacing, typography, loading states)
2. Responsive layout refinements
3. Error state handling
4. Integration testing

---

## 12. Verification Plan

1. `npx tsc --noEmit` — zero TypeScript errors
2. `npx vite build` — production build succeeds
3. `python -m pytest test/test_ai_*.py` — all backend tests pass
4. Navigate to `/ai-analyzer` → all 8 tabs render without errors
5. Technical tab shows chart + signals + patterns
6. Strategies tab shows 5 strategy panels with data
7. Decision tab shows full decision + confluence + evidence
8. Multi-TF tab shows per-timeframe breakdown
9. Scanner and History tabs still work as before
10. No duplicate/conflicting analysis sections
