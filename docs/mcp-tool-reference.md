# OpenAlgo MCP — Tool Reference & Prompt Examples

Companion reference to the main MCP setup guide. Once the MCP server is wired into Claude Desktop, Cursor, Windsurf, Antigravity, or any other MCP-capable client, you can ask for these operations in plain English — the client decides which tool to call.

All **40 tools** shipped by the server are listed below with:

- What the tool does
- Key parameters (required / optional)
- Example prompts you can paste directly into Claude / Cursor / Antigravity / Windsurf

## Conventions

- **Default strategy tag**: `python mcp` — every MCP-triggered order is tagged so you can filter MCP activity in OpenAlgo logs and the Analyzer. Override by saying *"use strategy 'my scalper'"* in the prompt.
- **Product type defaults**: `MIS` for equity. Use `NRML` for F&O carry; `CNC` for delivery.
- **Exchange codes**: `NSE`, `BSE`, `NFO`, `BFO`, `CDS`, `BCD`, `MCX` + `NSE_INDEX` / `BSE_INDEX` for index values.
- **Lot size**: never hardcoded. The model will call `get_option_symbol` / `get_option_chain` / `get_symbol_info` to read the live `lotsize` from the broker master contract, then compute `quantity = lots × lotsize` for you.

---

## 📦 Order Management

### `place_order`

Place a single market / limit / stop-loss order.

| Param | Required | Notes |
|---|---|---|
| `symbol`, `quantity`, `action` | Yes | — |
| `exchange` | No | Default `NSE` |
| `price_type` | No | `MARKET`, `LIMIT`, `SL`, `SL-M`. Default `MARKET` |
| `product` | No | `CNC`, `NRML`, `MIS`. Default `MIS` |
| `strategy` | No | Default `python mcp` |
| `price`, `trigger_price`, `disclosed_quantity` | No | Use as applicable |

**Prompts:**
- *"Place a market buy for 100 shares of RELIANCE on NSE, intraday"*
- *"Buy 50 INFY at limit 1550, delivery product"*
- *"Sell 25 SBIN with a stop-loss at 765 and trigger 766"*

---

### `place_smart_order`

Auto-calculates the delta between your current position and the target `position_size`, then sends only the incremental order.

| Param | Required | Notes |
|---|---|---|
| `symbol`, `quantity`, `action`, `position_size` | Yes | `position_size` = your target net qty |
| Rest | No | Same defaults as `place_order` |

**Prompts:**
- *"Square off my TATAMOTORS intraday position to zero"*
- *"Scale my YESBANK position to 100 shares long"*

---

### `place_basket_order`

Fire multiple orders in one call. Each basket entry carries its own `symbol`, `exchange`, `action`, `quantity`, `pricetype`, `product`.

**Prompts:**
- *"Place a basket: buy 1 BHEL and sell 1 ZOMATO, both market MIS on NSE"*
- *"Build a basket of SBIN, HDFCBANK and ICICIBANK buys, 10 shares each, CNC"*

---

### `place_split_order`

Break a large order into equal chunks (helpful for low-liquidity names or to avoid freeze limits).

**Prompts:**
- *"Sell 500 YESBANK in slices of 50, market orders"*
- *"Split 1200 NIFTY lots across 100-lot chunks"*

---

### `place_options_order`

Single-leg option order using offset-based strike selection (ATM / ITM1–ITM50 / OTM1–OTM50). The server resolves the strike against the live option chain.

| Param | Required | Notes |
|---|---|---|
| `underlying`, `exchange`, `offset`, `option_type`, `action`, `quantity` | Yes | — |
| `expiry_date` | No | Optional if underlying includes expiry (e.g., `NIFTY28OCT25FUT`) |
| `price_type`, `product`, `price`, `trigger_price` | No | Same as `place_order` |

> **Lot size note**: if you don't know it, just ask — the assistant will pull `lotsize` from `get_option_symbol` first, then size the quantity correctly.

**Prompts:**
- *"Buy 1 lot NIFTY ATM CE expiring 28NOV25"*
- *"Short 2 lots BANKNIFTY OTM3 PE for next weekly expiry"*

---

### `place_options_multi_order`

Multi-leg option strategies (up to 20 legs). BUY legs are fired first for margin efficiency, then SELL legs. Supports per-leg overrides for `expiry_date`, `pricetype`, `price`, `product`, etc. — perfect for calendar / diagonal spreads.

**Prompts:**
- *"Place an iron condor on NIFTY 28NOV25 at OTM5 and OTM10 strikes, 1 lot each, NRML"*
- *"Build a long straddle on BANKNIFTY ATM for 25NOV25 expiry with limit orders at 250"*
- *"Diagonal NIFTY spread: buy ITM2 CE 30DEC25, sell OTM2 CE 25NOV25, 1 lot"*

---

### `modify_order`

Change price / quantity / type / trigger on a working order.

| Param | Required | Notes |
|---|---|---|
| `order_id`, `symbol`, `action`, `exchange`, `product`, `quantity`, `price` | Yes | `price` is mandatory per the REST spec — use current price if unchanged |
| `price_type`, `trigger_price`, `disclosed_quantity` | No | Sensible defaults |

**Prompts:**
- *"Modify order 250408001002736 — change limit price to 16.5"*
- *"Increase quantity of my open NIFTY CE buy order to 2 lots"*

---

### `cancel_order`

**Prompt:** *"Cancel order 250408001002736"*

---

### `cancel_all_orders`

**Prompts:**
- *"Cancel every pending order I have"*
- *"Kill all open orders for strategy 'nifty scalper'"*

---

## 📊 Positions & Holdings

### `close_all_positions`

Square off everything for a strategy.

**Prompt:** *"Close all my open positions now"*

---

### `get_open_position`

Query the current net quantity for a specific instrument.

**Prompts:**
- *"What's my current position in NHPC NSE MIS?"*
- *"How many NIFTY futures am I long?"*

---

### `get_position_book`

Every open position across instruments.

**Prompt:** *"Show me all open positions with unrealized P&L"*

---

### `get_holdings`

Delivery/CNC holdings with today's P&L, % move, and aggregate statistics.

**Prompts:**
- *"Show my demat holdings sorted by today's % change"*
- *"What's the total unrealized P&L on my long-term portfolio?"*

---

### `get_funds`

Cash, collateral, realized/unrealized M2M, utilized margin.

**Prompt:** *"How much free cash do I have for trading today?"*

---

## 📋 Order Tracking

### `get_order_status`

**Prompt:** *"Check status of order 250828000185002 — did it fill?"*

---

### `get_order_book`

Every order today with statistics (open / complete / cancelled / rejected counts).

**Prompts:**
- *"Show today's order book"*
- *"How many of my orders got rejected today and why?"*

---

### `get_trade_book`

Only executed fills.

**Prompt:** *"List all my executed trades today with average price"*

---

## 📈 Market Data

### `get_quote`

LTP, bid, ask, OHLC, volume for one symbol.

**Prompts:**
- *"Get the latest quote for RELIANCE"*
- *"What's NIFTY trading at right now?"*

---

### `get_multi_quotes`

Quotes for many symbols in one round-trip.

**Prompt:** *"Get quotes for RELIANCE, TCS, INFY, HDFCBANK and ICICIBANK"*

---

### `get_market_depth`

Full 5-level bid/ask book plus total buy/sell qty and OI.

**Prompt:** *"Show the order book depth for SBIN"*

---

### `get_historical_data`

OHLCV history. Two sources:
- `source="api"` (default) → live fetch from broker API
- `source="db"` → local Historify DuckDB store (1m and D stored physically; other intervals, including custom ones like 2m/3m/W/M/Q/Y, computed on-the-fly via SQL)

**Prompts:**
- *"Get 5-minute SBIN candles from 1 Apr to 8 Apr 2025"*
- *"Pull NIFTY daily data for the last 6 months from the local Historify DB"*
- *"Give me weekly aggregates of BANKNIFTY for the past year using source=db"*

---

### `get_option_chain`

Real-time chain with CE/PE data per strike — LTP, bid/ask, OHLC, volume, OI, `lotsize`, moneyness labels. Use `strike_count=N` to limit to N strikes around ATM.

**Prompts:**
- *"Show me NIFTY option chain for 30DEC25, 10 strikes around ATM"*
- *"Full BANKNIFTY option chain for this week's expiry"*

---

## 🔍 Instrument Search & Symbols

### `search_instruments`

Fuzzy search across exchanges by name or symbol.

**Prompts:**
- *"Search for NIFTY 26000 Dec CE"*
- *"Find all TATA stocks on NSE"*

---

### `get_symbol_info`

Full metadata for one symbol: `brsymbol`, `lotsize`, `expiry`, `strike`, `tick_size`, `token`.

**Prompts:**
- *"Get symbol info for NIFTY30DEC25FUT on NFO"*
- *"What's the lot size for BANKNIFTY futures?"*

---

### `get_option_symbol`

Resolve ATM/ITM/OTM offset to the exact option symbol plus `lotsize`, `tick_size`, `underlying_ltp`. Expiry optional if the underlying includes one.

**Prompts:**
- *"Get the ATM CE symbol for NIFTY expiring 28OCT25"*
- *"What's the OTM4 PE for BANKNIFTY next weekly?"*

---

### `get_option_greeks`

Delta, Gamma, Theta, Vega, Rho + Implied Volatility using Black-76. Underlying is auto-detected — override with `underlying_symbol` / `underlying_exchange`, supply `forward_price` for custom / illiquid underlyings, and `expiry_time` for non-standard MCX contracts.

**Prompts:**
- *"Calculate greeks for NIFTY25NOV2526000CE with 6.5% interest rate"*
- *"What's the delta and IV of the ATM NIFTY CE for 28NOV25?"*

---

### `get_synthetic_future`

Put-call parity synthetic future price — useful for illiquid futures or weekly expiries that lack a traded future.

**Prompt:** *"What's the NIFTY synthetic future price for 25NOV25?"*

---

### `get_expiry_dates`

All tradeable expiries for an underlying.

**Prompt:** *"List all NIFTY options expiries available on NFO"*

---

### `get_available_intervals`

Supported timeframes for `get_historical_data`.

**Prompt:** *"What intraday intervals are supported?"*

---

### `get_instruments`

Bulk instrument master download for an exchange (or all exchanges when `exchange` is omitted). Output is paginated — default limit 500, with a `truncated` flag.

**Prompts:**
- *"Download the NFO instrument master, first 500 rows"*
- *"Get all MCX instruments available for trading"*

---

### `get_index_symbols`

Returns the full standardized OpenAlgo index symbol list (57 NSE + 40 BSE), rolled out uniformly across every supported broker.

**Prompts:**
- *"List all NSE index symbols I can subscribe to"*
- *"Show me the BSE index list — I want to stream SENSEX50"*

---

## 💰 Margin

### `calculate_margin`

SPAN + exposure margin for a hypothetical position set. Accepts an array of legs with `symbol`, `exchange`, `action`, `product`, `pricetype`, `quantity`.

**Prompts:**
- *"Calculate margin for 1 lot NIFTY 25000 CE buy + 1 lot 25500 CE sell, 25NOV25 expiry"*
- *"How much margin do I need for a BANKNIFTY short straddle at ATM for next week?"*

---

## 🧪 Analyzer

### `analyzer_status`

Am I in simulated (analyzer) or live mode?

**Prompt:** *"Am I in live or analyzer mode right now?"*

---

### `analyzer_toggle`

Flip between simulated and live trading. Analyzer mode returns `SB-xxx` pseudo-orderids without touching the broker — perfect for testing strategies end-to-end.

**Prompts:**
- *"Switch to analyzer mode before I test this strategy"*
- *"Turn off analyzer — I want to go live"*

---

## 📅 Market Calendar

### `get_holidays`

Full holiday list for a year (year optional → defaults to current year).

**Prompts:**
- *"What are the trading holidays in 2026?"*
- *"List this year's market holidays"*

---

### `get_timings`

Exchange open/close epoch timestamps for a given date (date optional → defaults to today).

**Prompt:** *"What are today's market timings across NSE, BFO and MCX?"*

---

### `check_holiday`

Quick pre-trade check: is a given date a holiday on a specific exchange?

**Prompts:**
- *"Is 26 Jan 2026 a holiday on NSE?"*
- *"Is tomorrow a trading day on MCX?"*

---

## 🛠️ Utilities

### `get_openalgo_version`

**Prompt:** *"What version of the openalgo library is running?"*

---

### `validate_order_constants`

Quick cheat-sheet of valid exchanges, product types, price types, actions, and intervals — useful when the model wants to double-check a parameter before sending an order.

**Prompt:** *"Remind me of the valid product types and price types"*

---

### `send_telegram_alert`

Push a Telegram notification via the OpenAlgo Telegram bot (must be configured in OpenAlgo settings first). Supports `priority` 1–10.

**Prompts:**
- *"Send me a Telegram alert: NIFTY crossed 26000, priority 8"*
- *"Ping me on Telegram if my NIFTY CE fills"*

---

## 🧠 Worked Multi-Tool Workflows

Real strength shows when the assistant chains tools on its own. Example prompts:

**1. End-to-end iron condor (analyzer mode):**

> *"Set up a NIFTY iron condor for next week's expiry. Find the expiry, pull the option chain, use OTM5 strikes on both sides, calculate the margin required, and — only if margin is under ₹1L — place it in analyzer mode using 1 lot per leg."*

The assistant will chain: `get_expiry_dates` → `get_option_chain` → `get_option_symbol` (for lot size) → `calculate_margin` → `analyzer_status` / `analyzer_toggle` → `place_options_multi_order`.

**2. Pre-market checklist:**

> *"Before I start trading: is the market open today on NSE and MCX, what's my free cash, what's my current position book, and what's NIFTY spot right now?"*

Chains: `check_holiday` → `get_timings` → `get_funds` → `get_position_book` → `get_quote`.

**3. Options greeks scan:**

> *"Pull the NIFTY option chain for 25NOV25 within 5 strikes of ATM, then compute greeks for the ATM CE and PE with 6.5% interest rate — tell me which has higher vega."*

Chains: `get_option_chain` → `get_option_symbol` (ATM) × 2 → `get_option_greeks` × 2.

**4. Square-off with Telegram confirmation:**

> *"Square off everything, cancel all pending orders, then send me a Telegram alert summarizing what got closed with the realized P&L."*

Chains: `cancel_all_orders` → `close_all_positions` → `get_trade_book` → `send_telegram_alert`.

---

## Quick Prompt Patterns

| Intent | Prompt pattern |
|---|---|
| Status check | *"What's my {thing}?"* |
| Single action | *"{Buy/Sell} {qty} {symbol} at {price}"* |
| Multi-leg | *"Build a {strategy} on {underlying} {expiry} with {offsets}"* |
| Safety-first | *"In analyzer mode, {do the thing}"* |
| Conditional | *"Only if {condition}, then {action}"* |
| Research | *"Show me {chain/greeks/history} and recommend {levels}"* |

---

## Safety Tips

- Start in **analyzer mode** (`analyzer_toggle True`) while you get comfortable — orders look real but never leave OpenAlgo.
- Use phrases like *"only if margin is under X"* or *"ask me to confirm before placing"* — the assistant will pause for your OK.
- Use a unique `strategy` name per use-case (e.g., *"use strategy 'nifty scalper'"*) so MCP-driven activity is cleanly separable from manual orders in logs.
- For live trading, set up the OpenAlgo Telegram bot and ask the assistant to *"send a Telegram alert after every order fill"* — you get a realtime feed without staring at the screen.

---

## Related

- [MCP Server Setup Guide](../mcp/README.md) — install, configure Claude / Cursor / Windsurf, broker prerequisites
- [OpenAlgo Symbol Format](./userguide/symbol-format/README.md) — how equity / future / option symbols are constructed
- [API Documentation](./api/README.md) — underlying REST endpoints each MCP tool wraps
