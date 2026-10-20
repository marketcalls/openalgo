# 31 - Tools (Options & Strategy Analytics Suite)

## Introduction

OpenAlgo ships with **thirteen built-in analytical tools** for options trading and market analysis. They live under the `/tools` page and use the active broker's REST and WebSocket market data where each tool requires it.

Availability depends on the plugin's supported exchanges, broker response fields, account market-data entitlement, and the symbols or expiries requested. A plugin being installed does not guarantee that every analytical page has the data it needs.

## Accessing the Tools Page

Navigate to **Tools** in the sidebar, or go directly to `http://127.0.0.1:5000/tools`.

You will see a grid of tool cards. Click any card to open that tool.

## Tools Reference

### 1. Strategy Builder (`/strategybuilder`)

Build and analyze multi-leg option strategies end-to-end.

- Drag-and-drop legs with live Greeks (Delta, Gamma, Theta, Vega, Rho)
- Interactive **payoff diagram** with breakeven, max profit, and max loss
- **What-if simulator** to test price, time-to-expiry, and IV changes
- **Strategy Chart** tab for live strategy-level price and P&L curves
- **Multi Strike OI** tab for OI comparison across strikes in a single view
- **Basket order execution dialog** — review every leg and send them as a single basket order to the broker in one click

### 2. Strategy Portfolio (`/strategybuilder/portfolio`)

Your saved strategies at a glance.

- **MyTrades** watchlist — live strategies you are tracking with real positions
- **Simulation** watchlist — strategies saved for backtesting/simulation
- Quick reopen into Strategy Builder for further analysis or execution

### 3. Option Chain (`/optionchain`)

Real-time option chain with full order capability.

- Live Greeks per strike (Delta, Gamma, Theta, Vega, IV)
- OI, OI change, Volume, LTP, bid/ask — all streaming
- Quick order placement inline from the chain (click-to-trade)
- Supports the option expiries returned for the selected underlying and broker

### 4. Option Greeks (`/ivchart`)

Historical Greeks charts for ATM options.

- Time-series charts for IV, Delta, Theta, Vega, and Gamma
- ATM strike auto-rolls as spot moves
- Useful for IV regime analysis and decay studies

### 5. OI Tracker (`/oitracker`)

Open Interest analysis built for intraday decision-making.

- Side-by-side **CE/PE OI bars** across strikes
- **PCR (Put-Call Ratio)** overlay
- **ATM strike marker** that follows spot in real time
- Identify OI walls and shifts in positioning

### 6. Max Pain (`/maxpain`)

Max Pain strike calculation with visual distribution.

- Live computed Max Pain strike for the current expiry
- Pain distribution chart across all strikes
- Useful for expiry-day positioning and pinning analysis

### 7. Straddle Chart (`/straddle`)

Dynamic ATM Straddle chart with rolling strike logic.

- ATM CE + ATM PE combined straddle price
- Strike rolls automatically as spot moves
- **Spot** and **Synthetic Futures** overlays for context
- Essential for directional-neutral volatility trades

### 8. Straddle PnL (`/straddlepnl`)

Simulated intraday ATM straddle P&L with automation.

- Backtest-style intraday P&L simulation
- **Automated N-point adjustments** for delta management
- Complete **trade log** of every leg and adjustment
- Compare simulated performance vs. static straddle

### 9. Vol Surface (`/volsurface`)

3D Implied Volatility surface across strikes and expiries.

- Live-built surface from your broker's option chain data
- Rotate, zoom, and inspect IV across the entire surface
- Quickly spot skew, term structure, and volatility arbitrage zones

### 10. GEX Dashboard (`/gex`)

Gamma Exposure (GEX) analysis for market-maker positioning.

- **OI Walls** — strikes with the largest gamma exposure
- **Net GEX per strike** chart
- **Top Gamma Strikes** ranking
- Useful for identifying expected support/resistance zones

### 11. Strike Profile (`/strikeprofile`)

Gamma exposure (GEX) and delta exposure (DEX) for every strike of several expiries at once, as a strike by expiry heatmap.

- Values are in rupees crore. **GEX** is what hedgers would trade for a 1% move in the underlying (calls positive, puts negative). **DEX** is the delta-weighted open interest (call delta x OI + put delta x OI, times spot).
- One column per expiry, labelled with days to expiry, so a near expiry and a far one sit side by side.
- **Peaks** marks each expiry's own largest positive and negative strike (All), only the larger of the two (Max), or none (Off). A near expiry always carries far more gamma than a far one, so the peaks are what make a level on a far expiry visible.
- **Shade** colours cells against the whole grid (Global) or against each expiry's own largest value (Per expiry).
- **Flip** is the underlying price at which total GEX across the selected expiries changes sign, found by re-pricing every option's gamma at nearby prices. **C wall** and **P wall** are the strikes with the most call and put GEX.
- Range buttons (2%, 5%, 10%, All) choose the strikes shown around spot; Chart shows the net per strike summed across expiries; two panes show GEX and DEX together.
- Each selected expiry is one option chain request, so the nearest six are selected by default. Select more from the expiry list when your broker answers quickly.

### 12. IV Smile (`/ivsmile`)

Implied Volatility smile curve with skew analysis.

- Separate **Call IV** and **Put IV** curves
- **ATM IV** marker
- Skew measurement between OTM puts and OTM calls
- Per-expiry toggle

### 13. OI Profile (`/oiprofile`)

Futures candlestick with OI profile overlay.

- Futures candles as the primary price chart
- **OI butterfly** showing CE vs PE OI distribution
- **Daily OI change** across strikes
- Combines price action with positioning data in one view

## Tips

- Tools subscribe to live ticks, so **keep the connected broker's WebSocket active** and stay logged in.
- If a tool shows no data, verify the underlying index/symbol is tradeable in the current session and that your broker adapter is streaming (check the WebSocket status indicator in the dashboard).
- Use the **Strategy Builder** + **Strategy Portfolio** pair as your end-to-end workflow: design a strategy, save it to a watchlist, then execute the full basket with one click when conditions align.
- All tools respect your theme and accent color preferences.

## Related Guides

- [Module 11 - Order Types](../11-order-types/README.md) — understand the order types used by Strategy Builder basket orders
- [Module 13 - Basket Orders](../13-basket-orders/README.md) — how multi-leg baskets are routed to the broker
- [Module 21 - Flow Visual Builder](../21-flow-visual-builder/README.md) — for automating tool-driven strategies
- [Module 24 - PnL Tracker](../24-pnl-tracker/README.md) — track realized P&L after execution
