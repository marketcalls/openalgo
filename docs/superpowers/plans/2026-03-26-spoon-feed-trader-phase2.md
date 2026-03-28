# Phase 2: Spoon-Feed Trader — Complete Trading Assistant

## Vision
Transform the AI Analyzer from "data display" into a **decision-ready trading assistant** that tells the trader exactly what to do — buy/sell, at what price, with what stop loss, what target, how many shares, and what risk they're taking. Every piece of information should lead to action.

## What's Missing (from user feedback)

### 1. History Tab — Empty, needs real decision history
### 2. Scanner Tab — Needs actionable output (not just signals)
### 3. Indicators NOT showing on chart (Supertrend, EMA, BB should overlay)
### 4. Every section should show Entry/Target/SL — not just the Trade Setup card
### 5. Risk knowledge — show max loss, position sizing, risk % of capital
### 6. Auto-show indicators on chart when analysis runs
### 7. Python custom indicators from self indc/ should be selectable

## Detailed Requirements

### A. Chart Enhancements
- Overlay EMA 9/21, SMA 50/200 on candlestick chart
- Overlay Bollinger Bands (upper/lower)
- Overlay Supertrend line (green when bullish, red when bearish)
- Show CPR pivot levels as horizontal lines
- Show Entry/SL/Target lines (already done but need visibility)
- Volume bars below chart
- Toggle panel to show/hide each indicator

### B. Trade Setup Everywhere
- Every signal card should show: "Buy at X, SL at Y, Target at Z"
- Scanner results should show mini trade setup per symbol
- Pattern Alerts should show "if this pattern confirms, buy at X"
- CPR levels should show "buy near S1, sell near R1"

### C. Risk Calculator
- Input: Account balance, risk % per trade
- Output: Max shares, max loss in ₹, position value
- Show risk-reward ratio prominently (1:2, 1:3)
- Color-coded: green if R:R > 2, yellow if 1-2, red if < 1

### D. History Tab
- Show all past AI decisions with outcomes (if trade was taken)
- Win/loss tracking
- Average R:R achieved
- P&L summary

### E. Scanner Enhancements
- Show mini signal badge + entry/SL/target for each symbol
- Sortable by: confidence, score, R:R ratio
- Click on symbol → loads full analysis
- Highlight "strong" setups (confidence > 70%)

### F. Python Custom Indicators
- Load indicators from D:\test1\self indc\
- Show as toggleable overlays on chart
- Run calculate_indicators() on the OHLCV data

## Implementation via CCGL

Use Triad Workbench's architecture-compare workflow:
1. **Gemini (Designer)**: Design the complete UX — mockups for each section
2. **Claude (Architect)**: Plan the backend changes — new API fields, chart data format
3. **Codex (Implementer)**: Implement frontend components
4. **Ollama (Reviewer)**: Review for trading accuracy and risk logic

## Priority Order
1. Chart indicator overlays (highest visual impact)
2. Risk calculator (critical for trader safety)
3. Scanner with trade setup (actionable scanning)
4. History with outcomes (learning from past)
5. Custom indicator integration (power user feature)

## Estimated Scope
- Backend: ~5 new/modified files
- Frontend: ~8 new/modified components
- Tests: ~20 new tests
- CCGL workflows: 2 new custom workflows
