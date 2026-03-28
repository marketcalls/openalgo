# Phase 3: Port VAYU Dashboard to OpenAlgo

## Date: 2026-03-27
## Status: PENDING (Spec written, implementation not started)
## Spec: `D:\openalgo\docs\superpowers\specs\2026-03-27-vayu-dashboard-port-design.md`

---

## Prompt (paste this into a new Claude session)

You are working on TWO local projects:
1. VAYU project source: C:\Users\sakth\Desktop\vayu\
2. OpenAlgo project source: D:\openalgo\

Your job is to READ the VAYU codebase, identify the full implementation of:
- the chart dashboard like the screenshot/reference
- the analysis dashboard from the same VAYU project
- all sub-tabs and related logic:
  - Technical Strategy
  - Indicator
  - Decision
  - Fundamental
  - Why Not
  - Multi-TF

Then PORT those features into the OpenAlgo frontend as a production-quality implementation.

This is not a mockup task.
This is not a planning-only task.
You should do the actual coding work end-to-end in OpenAlgo.

Core goal:
Make OpenAlgo frontend include the VAYU chart dashboard and analysis dashboard features as closely as possible, but with:
- higher UI quality
- clearer explanations
- easier readability for traders
- better structured code
- integration with existing OpenAlgo features if similar features already exist

IMPORTANT RULES
1. First read and understand both codebases before editing.
2. Use VAYU as the source of truth for feature parity.
3. Reuse existing OpenAlgo features where possible instead of duplicating them.
4. If OpenAlgo already has similar features such as:
   - indicators
   - explanations
   - findings
   - technical analysis outputs
   - AI reasoning
   then integrate/merge them into the new dashboard instead of creating parallel redundant systems.
5. Preserve OpenAlgo's existing architecture, component patterns, API flow, styling conventions, routing, and state management where practical.
6. Do not remove unrelated user changes.
7. Do not stop after analysis. Implement the changes.
8. After implementation, run build/tests relevant to the frontend and fix issues you introduced.

WHAT TO DO

PHASE 1: DISCOVERY
A. In the VAYU project, find and fully inspect:
- chart dashboard components
- chart widgets
- analysis dashboard components
- all tab/sub-tab components
- API/service calls
- stores/state
- types/interfaces
- styling/theme logic
- charting libraries
- any data transformation utilities
- any reasoning/explanation components

B. In the OpenAlgo project, find and inspect:
- existing frontend dashboard/chart pages
- indicator pages/components
- analysis/explanation/findings related UI
- API clients
- React routes
- page layout system
- shared UI components
- state management
- charting setup
- relevant backend endpoints already consumed by frontend

C. Make a feature mapping:
- VAYU feature
- where it should live in OpenAlgo
- whether it should be copied, adapted, or merged with an existing OpenAlgo feature

Do this mapping internally and then start implementation.

PHASE 2: IMPLEMENTATION GOAL
Create in OpenAlgo frontend a VAYU-style trading/chart dashboard with:
1. Main chart dashboard copied from VAYU
2. Analysis dashboard copied from VAYU
3. All sub-tabs copied/adapted:
   - Technical Strategy
   - Indicator
   - Decision
   - Fundamental
   - Why Not
   - Multi-TF

The final OpenAlgo implementation should:
- feel like a refined VAYU dashboard inside OpenAlgo
- preserve important VAYU logic and workflows
- improve readability and explanation quality
- support existing OpenAlgo insights if available

FEATURE EXPECTATIONS

1. Chart Dashboard
Implement the VAYU chart dashboard experience in OpenAlgo:
- same major information blocks and behavior
- same chart-driven workflow
- same or better usability
- preserve signal/analysis context around the chart
- preserve timeframe interactions and chart-linked panels if present
- preserve indicator overlays and reasoning panels if present
- preserve decision support if present

Improve quality by:
- better spacing
- better typography hierarchy
- less clutter
- more trader-friendly labels
- fewer confusing abbreviations unless already standard
- better empty/loading/error states
- responsive behavior without breaking desktop-first layout

2. Analysis Dashboard
Implement the VAYU analysis dashboard in OpenAlgo with all tabs and logic:
- Technical Strategy
- Indicator
- Decision
- Fundamental
- Why Not
- Multi-TF

Each tab should include:
- the VAYU feature set
- the VAYU logic and data relationships
- improved UX and explanation clarity
- support for OpenAlgo-native features where relevant

3. OpenAlgo Feature Merge
If OpenAlgo already has similar features, merge them intelligently.
Examples:
- if OpenAlgo already has indicator explanations, include them in Indicator tab
- if OpenAlgo has findings/reasoning, expose them in Decision / Why Not / Explanation areas
- if OpenAlgo has technical outputs already available from backend, prefer reusing those
- if OpenAlgo has AI analysis panels, reconcile them with the VAYU structure instead of duplicating

4. Better Explainability
The final UI should be easier for traders to understand than raw VAYU copy.
Improve:
- explanation text
- reason grouping
- confidence display
- decision clarity
- "why not" risks/invalidations
- multi-timeframe interpretation
- indicator summaries
- strategy summary in plain language

Add readable labels such as:
- Bullish continuation
- Reversal risk
- Weak setup
- Confirmation missing
- Institutional support present
- Multi-timeframe alignment strong/weak
only where appropriate and supported by data.

PHASE 3: CODE REQUIREMENTS
Implement real code in OpenAlgo:
- components
- hooks
- types
- API integrations
- routes/pages
- state wiring
- styles
- reusable shared UI pieces if needed

Preferred approach:
- extract reusable subcomponents if VAYU code is messy
- keep files maintainable
- avoid giant monolithic files unless the repo already uses that pattern

When porting, preserve:
- data flow correctness
- calculations
- UI behavior
- interactions
- state transitions
- conditional rendering
- tab logic
- chart integrations
- tooltips / helper text / explanation surfaces

When improving, focus on:
- naming clarity
- composability
- readability
- fewer duplicated transforms
- stronger typing
- fewer fragile assumptions

PHASE 4: UX IMPROVEMENTS REQUIRED
Do not make only a literal copy.
Make it a better-than-VAYU version while preserving feature parity.

Required UX upgrades:
- reduce cognitive overload
- improve panel hierarchy
- improve tab discoverability
- make important conclusions visible faster
- improve color semantics
- improve contrast/readability
- improve loading and skeleton states
- improve responsiveness for common desktop widths
- make "Why Not" especially clear and actionable
- make "Decision" tab easier to scan
- make "Multi-TF" easier to interpret visually
- make indicator summaries less dense and more understandable

PHASE 5: BACKEND/FRONTEND CONNECTIONS
If OpenAlgo backend already exposes similar data, use it.
If a frontend feature cannot work because OpenAlgo lacks required data endpoints:
- first look for existing equivalent endpoints
- then look for nearby reusable sources
- only if necessary, add minimal backend support needed to make the frontend work properly

Do not invent fake UI-only data when real data exists or can be wired.

For every missing dependency, decide:
- reuse existing OpenAlgo source
- adapt VAYU data contract
- add minimal API shape needed

PHASE 6: VALIDATION
After coding:
1. Build the frontend
2. Fix compile/type/lint issues caused by your changes
3. Verify routes/pages render
4. Verify tabs work
5. Verify chart dashboard interactions work
6. Verify data loading states and error states
7. Verify no obvious duplication/conflict with current OpenAlgo features
8. Summarize:
   - what was ported from VAYU
   - what was merged with existing OpenAlgo features
   - what was improved
   - what remains blocked, if anything

DELIVERABLE EXPECTATIONS
I want actual code changes in OpenAlgo, not only a report.

At the end provide:
1. A short summary of what you implemented
2. List of files created/changed
3. Any backend dependencies added or reused
4. Any places where VAYU and OpenAlgo differed and how you resolved it
5. Any remaining gaps

QUALITY BAR
The final result should feel like:
- VAYU feature parity
- OpenAlgo-native integration
- cleaner architecture
- better trader UX
- more explanation clarity
- less clutter
- no duplicate/conflicting analysis sections if OpenAlgo already has equivalent ones

IMPLEMENTATION PRIORITY
Priority 1:
- chart dashboard port
- analysis dashboard shell
- all sub-tabs present and working

Priority 2:
- merge with existing OpenAlgo indicators/explanations/findings
- improve readability and trader friendliness

Priority 3:
- polish interactions, loading states, visual hierarchy

VERY IMPORTANT
Do not just recreate the UI visually.
Trace the actual VAYU code paths and port the real functionality.
Do not just copy blindly either.
Where OpenAlgo already has equivalent functionality, merge or enhance instead of duplicating.

If there are multiple possible integration paths, choose the one that:
- minimizes duplication
- preserves feature completeness
- keeps the code maintainable

Start by exploring both codebases thoroughly, then implement the full port.

---

## Reference: VAYU Screenshot Details (from 2026-03-27)

### Technical Tab (Screenshot 1)
- Dark theme, SBIN symbol, 1d timeframe
- Top nav: Dashboard | Analysis | Options(P3) | Screener(P2) | Backtest(P3) | News(P2) | Journal | Settings
- Sub-tabs: Technical | Strategies | Decision | Fundamental(P3) | Why NOT(P2) | Multi-TF
- LEFT (75%): Full chart with toggle buttons:
  - EMA 9, EMA 21, SMA 50, SMA 200, BB Upper, BB Mid, BB Lower, VWAP, Supertrend, Trade Levels
  - Candlestick chart with all overlays
  - Trade levels: SL 1295.46, Entry 1190.65, TP(S1) 1047.23, TP(S2) 1033.87, TP(S3) 1024.73
  - Volume bars, TradingView watermark
- RIGHT (25%): Signal Summary panel:
  - HOLD badge with 10% circular confidence gauge
  - Semicircular signal gauge (-0.10, yellow/orange needle)
  - MARKET REGIME: "Trending Down" (red)
  - SIGNAL BREAKDOWN: Supertrend -0.40, RSI +0.30, MACD -0.30, EMA Cross -0.30, Bollinger +0.30, ADX +0.20
  - KEY INDICATORS: RSI(14) 34.53, MACD -27.64, ADX 39.63, ATR 32.29
- Status bar: System GREEN | Latency 31ms | Source: yfinance | Autonomy: Manual

### Strategies Tab (Screenshot 2)
- Sub-tabs on right: Elliott Wave | Smart Money (active) | Hedge Fund
- Left: Chart (failed to load)
- Right: "Strategy Analysis" → "Analyzing Smart Money flow..."

### Dashboard Tab (Screenshot 3)
- Left: "SBIN Chart" (failed)
- Right: "Signal & Analysis" → "Analysis failed"
- Bottom: News Feed (Phase 2) | AI Chatbot (Phase 2)

---

## Pre-existing OpenAlgo Features (merge, don't duplicate)

| OpenAlgo Component | Status | Merge Into |
|---|---|---|
| ChartWithIndicators | EXISTS | Technical tab chart |
| SignalBadge | EXISTS | Signal Summary panel |
| ConfidenceGauge | EXISTS | Signal Summary panel |
| SubScoresChart | EXISTS | Signal Breakdown |
| MLConfidenceBar | EXISTS | Signal Summary |
| IndicatorTable | EXISTS | Key Indicators section |
| DecisionCard | EXISTS | Decision tab header |
| TradeSetupCard | EXISTS | Decision tab |
| RiskCalculator | EXISTS | Decision tab |
| LLMCommentary | EXISTS (unique) | Decision tab |
| AdvancedSignalsPanel | EXISTS | Technical + Strategies tabs |
| LevelsPanel | EXISTS | Technical tab |
| LivePriceHeader | EXISTS | Shared header |

## New Components Needed

| Component | Tab | Backend |
|---|---|---|
| SignalGauge (semicircular) | Technical | No (derived from score) |
| CandlestickPatternsPanel | Technical | Wire existing indicators_advanced |
| SupportResistancePanel | Technical | Wire existing pivot/fib |
| FibonacciPanel | Strategies | Wire indicators_lib/fibonacci_levels.py |
| HarmonicPanel | Strategies | Wire indicators_lib/harmonic_patterns.py |
| ElliottWavePanel | Strategies | Port from VAYU backend |
| SmartMoneyDetailPanel | Strategies | Wire indicators_lib/smc_*.py |
| HedgeFundPanel | Strategies | Create new backend module |
| StrategyDecisionPanel | Decision | Create strategy-decision endpoint |
| ConfluenceMeter | Decision | Derived from strategies |
| VotingBreakdown | Decision | Derived from strategies |
| EvidenceChain | Decision | Derived from all analysis |
| MultiTimeframePanel | Multi-TF | Create multi-timeframe endpoint |
| WhyNotTab | Why Not | Derived from existing analysis |
| FundamentalTab | Fundamental | Placeholder (Phase 3) |

## Backend Endpoints to Create

| # | Endpoint | Source Module |
|---|----------|--------------|
| 1 | POST /api/v1/agent/fibonacci | indicators_lib/custom/fibonacci_levels.py |
| 2 | POST /api/v1/agent/harmonic | indicators_lib/custom/harmonic_patterns.py |
| 3 | POST /api/v1/agent/smart-money-detail | indicators_lib/custom/smc_*.py |
| 4 | POST /api/v1/agent/elliott-wave | New (port from VAYU) |
| 5 | POST /api/v1/agent/hedge-strategy | New |
| 6 | POST /api/v1/agent/strategy-decision | Combine all strategies |
| 7 | POST /api/v1/agent/multi-timeframe | Run analyze across 6 intervals |
| 8 | POST /api/v1/agent/patterns | Wire existing indicators_advanced |
| 9 | POST /api/v1/agent/support-resistance | Wire existing pivot/fib |

## Implementation Sessions

| Session | What | Est. Components |
|---------|------|-----------------|
| Session 1 | 6-tab shell + Technical tab | 5 components |
| Session 2 | Strategies tab (5 panels) + backend APIs | 8 components + 5 endpoints |
| Session 3 | Decision + Multi-TF + Why Not tabs | 6 components + 2 endpoints |
| Session 4 | Polish + Fundamental placeholder + integration test | UX fixes |

## Key Files

| File | Purpose |
|------|---------|
| D:\openalgo\docs\superpowers\specs\2026-03-27-vayu-dashboard-port-design.md | Full design spec |
| D:\openalgo\docs\superpowers\plans\2026-03-27-phase3-vayu-dashboard-port.md | This file (plan + prompt) |
| D:\openalgo\docs\superpowers\plans\2026-03-27-phase2-spoon-feed-trader.md | Phase 2 plan (DONE) |
| D:\openalgo\docs\superpowers\plans\2026-03-26-vayu-openalgo-ai-integration.md | Phase 1 plan (DONE) |
| C:\Users\sakth\Desktop\vayu\ | VAYU source (read-only reference) |
