# Intraday Position Calculator — Feature Documentation

## Problem Statement

You have 1,579 NSE stocks, each with a different intraday leverage multiplier (1x, 2x, 4x, or 5x). When placing an intraday trade, you need to know how many shares you can buy/sell based on your available capital and the stock's leverage. Currently this requires an external Excel sheet (`fyers_intraday_calculator.xlsx`).

**Core Formula:**

```
Max Quantity = FLOOR((Capital x Intraday Multiplier) / Current Price)
```

Example: Capital = 1,00,000, Leverage = 5x, Price = 842.50
Max Quantity = FLOOR((1,00,000 x 5) / 842.50) = FLOOR(593.47) = **593 shares**

---

## Solution Overview

A calculator popup that appears when the user clicks Buy/Sell on any order surface. It auto-reads:

- **Stock Symbol** from the current chart / option chain row / holding
- **Current Price (LTP)** from the live WebSocket feed
- **Available Capital** from the broker funds API
- **Leverage Multiplier** from a per-symbol lookup table (1,579 NSE stocks)

The user can review, adjust quantity, and confirm — then the order is placed.

---

## User Flow

### Chart (`/trading`)

```
User clicks Buy/Sell on chart
  → PositionCalculator dialog opens
  → Auto-filled: Symbol, LTP, Capital, Leverage (Nx)
  → Max Quantity computed: FLOOR((Capital x Leverage) / LTP)
  → User adjusts quantity (optional)
  → Clicks "Place BUY/SELL Order"
  → Order placed via terminal
```

### OptionChain (`/optionchain`) and OptionChainPanel

```
User clicks B/S pill on an option leg
  → PositionCalculator dialog opens
  → Auto-filled: Symbol (option), LTP, Capital, Leverage
  → User confirms quantity
  → PlaceOrderDialog opens with calculated quantity pre-filled
  → User reviews and submits
```

### Holdings (`/holdings`)

```
User clicks Exit/Add on a holding
  → PositionCalculator dialog opens
  → Auto-filled: Symbol, LTP, Capital, Leverage
  → User confirms quantity
  → PlaceOrderDialog opens with calculated quantity pre-filled
  → User reviews and submits
```

---

## Architecture

### Backend Components

#### 1. Intraday Leverage Lookup Table

**File:** `database/intraday_leverage_db.py`

A new SQLite table storing per-symbol intraday leverage multipliers.

**Schema:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `symbol` | String | OpenAlgo symbol (e.g. "SBIN") |
| `exchange` | String | Exchange code (default "NSE") |
| `multiplier` | Float | Intraday multiplier (1, 2, 4, or 5) |
| `updated_at` | DateTime | Last update timestamp |

**Unique constraint:** `(symbol, exchange)`

**Functions:**

- `init_db()` — Creates table, seeds 1,579 NSE stocks from hardcoded data if empty
- `get_multiplier(symbol, exchange="NSE")` — Single lookup with TTLCache (1 hour TTL)
- `get_multipliers_bulk(symbols, exchange="NSE")` — Batch lookup for multiple symbols

**Multiplier Distribution (from Excel):**

| Multiplier | Stock Count | Examples |
|-----------|-------------|----------|
| 5x | 1,005 | SBIN, RELIANCE, TCS, INFY, HDFCBANK |
| 4x | 392 | ABBOTINDIA, ACC, ADANIENT, AMBUJACEM |
| 1x | 179 | AARON, low-liquidity / illiquid stocks |
| 2x | 3 | Rare cases |

#### 2. REST API

**File:** `blueprints/intraday_leverage.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/intraday-leverage/api/<symbol>` | Single symbol lookup |
| POST | `/intraday-leverage/api/batch` | Bulk lookup `{ symbols: [...] }` |

**Response (single):**

```json
{
  "status": "success",
  "data": {
    "symbol": "SBIN",
    "exchange": "NSE",
    "multiplier": 5
  }
}
```

**Response (batch):**

```json
{
  "status": "success",
  "data": [
    { "symbol": "SBIN", "exchange": "NSE", "multiplier": 5 },
    { "symbol": "RELIANCE", "exchange": "NSE", "multiplier": 5 }
  ]
}
```

Protected by `@check_session_validity` (session auth).

#### 3. Migration Script

**File:** `upgrade/migrate_intraday_leverage.py`

- Creates `intraday_leverage` table (idempotent)
- Seeds 1,579 NSE stock multipliers (INSERT OR IGNORE)
- Supports `--status` flag to report table state
- Registered in `upgrade/migrate_all.py` MIGRATIONS list

---

### Frontend Components

#### 1. API Client

**File:** `frontend/src/api/intradayLeverage.ts`

```typescript
export interface IntradayLeverage {
  symbol: string
  exchange: string
  multiplier: number
}

export const intradayLeverageApi = {
  getMultiplier: (symbol: string, exchange?: string) =>
    fetch(`/intraday-leverage/api/${symbol}?exchange=${exchange || 'NSE'}`),

  getBulk: (symbols: string[]) =>
    fetch('/intraday-leverage/api/batch', {
      method: 'POST',
      body: JSON.stringify({ symbols }),
    }),
}
```

#### 2. PositionCalculator Component

**File:** `frontend/src/components/trading/PositionCalculator.tsx`

A shadcn/ui Dialog that shows before every order placement.

**Props:**

```typescript
interface PositionCalculatorProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  symbol: string           // from chart / option chain / holdings
  exchange: string         // exchange code
  side: 'BUY' | 'SELL'    // initial action (default toggleable in-dialog)
  ltp: number | null       // current LTP (from terminal or live quote)
  lotSize?: number         // for derivatives (default: 1)
  tradeType?: TradeType    // INTRADAY | OVERNIGHT | GTT (default INTRADAY)
  onConfirm: (outcome: PositionCalculatorOutcome) => void
}
```

**Confirmed outcome (what `onConfirm` receives):**

```typescript
type TradeType = 'INTRADAY' | 'OVERNIGHT' | 'GTT'
type OrderKind = 'MARKET' | 'LIMIT'

interface PositionCalculatorOutcome {
  quantity: number
  action: 'BUY' | 'SELL'
  product: 'MIS' | 'NRML' | 'CNC'        // derived from tradeType + exchange
  tradeType: TradeType
  orderType: OrderKind                    // MARKET executes now; LIMIT schedules
  price?: number                          // limit price when orderType === 'LIMIT'
  gtt?: boolean                           // true when GTT selected
  stoploss?: number                       // trigger price for the stop
  target?: number                         // target price
  trailingStoploss?: number               // trailing stop in points
}
```

**Auto-filled data sources:**

| Field | Source |
|-------|--------|
| Symbol | Props (from chart/option chain/holdings) |
| LTP | `useLiveQuote(symbol, exchange)` — WebSocket + REST fallback |
| Capital | `tradingApi.getFunds(apiKey)` → `availablecash` |
| Leverage | `intradayLeverageApi.getMultiplier(symbol, exchange)` → `multiplier` |

> **Leverage applies only to INTRADAY.**
> The intraday multiplier is used for sizing only when the trade type is
> `INTRADAY`. For `OVERNIGHT` and `GTT` the effective multiplier is `1x` (cash
> only): with Rs 100 capital and a Rs 100 share, max quantity is exactly 1.
> The UI labels the row "Leverage (not applicable)" in those modes and the Max
> Quantity card shows an explanatory note when the API returned a real
> multiplier that is being ignored.

**Trade type -> product mapping** (`defaultProductFor(exchange, tradeType)`):

| TradeType | F&O exchange (NFO/BFO/NSE/BSE futures+options) | Equity/other |
|-----------|------------------------------------------------|--------------|
| INTRADAY  | MIS                                            | MIS          |
| OVERNIGHT | NRML                                           | CNC          |
| GTT       | NRML (+ `gtt: true`)                          | CNC (+ `gtt: true`) |

**Order type:**

| OrderKind | Meaning | Sizing basis |
|-----------|---------|--------------|
| MARKET    | Execute immediately at the current market price. | Live LTP |
| LIMIT     | Scheduled: fills only when the market trades at the chosen price. | The limit price (cash reserved at limit) |

For a LIMIT buy the price must be below LTP (a buy limit above LTP fills
immediately — it is not a scheduled order); a LIMIT sell must be above LTP. An
invalid limit blocks confirm and explains why.

**Computed quantity:**

```typescript
const effectiveLeverage = tradeType === 'INTRADAY' ? leverage : 1
const priceBasis =
  orderType === 'LIMIT' && parseFloat(limitPrice) > 0
    ? parseFloat(limitPrice)
    : currentPrice
const maxQty = Math.floor((capital * effectiveLeverage) / priceBasis)
```

The user's quantity is clamped to `maxQty` whenever the trade type, order type
or limit price changes, so it can never oversize against the new basis.

**UI Layout (3D-style, dark glass):**

```
+------------------------------------------------------------------+
|  Position Calculator                                    [BUY][SELL] [X] |
|------------------------------------------------------------------|
|  Order Type                                            (3D tiles) |
|  [ Market ]  [ Limit ]                              current/your px |
|  Executes immediately ... / Scheduled order fills at your price   |
|------------------------------------------------------------------|
|  Trade Type                                           (3D tiles) |
|  [ Intraday ]  [ Overnight ]  [ GTT ]                            |
|------------------------------------------------------------------|
|  SBIN (NSE)  [CNC]                                               |
|  LTP: 842.50  (+1.23%)                 [Live]                    |
|  (Limit only) Limit Price: [ ______ ]  LTP: 842.50                |
|------------------------------------------------------------------|
|  Intraday Leverage:  5x        (Overnight/GTT -> "1x" + note)    |
|  Available Capital:  1,00,000  (editable)                        |
|  Max Quantity:  593                    (glow card, formula hidden)|
|  [Quantity: [  593  ]]  [Max]                                    |
|------------------------------------------------------------------|
|  Risk Management                                                  |
|  Stop Loss:     [ ______ ]  Target Price: [ ______ ]              |
|  Trailing Stop: [ ______ ]  pts        [GTT switch]              |
|------------------------------------------------------------------|
|  [Cancel]              [BUY 593 · CNC · Market / · Limit]        |
+------------------------------------------------------------------+
```

Key points:

- **3D UI treatment**: raised/inset (pressed) tiles for Buy/Sell, order type
  and trade type; gradient depth cards with glows for Order Type, Max
  Quantity and Risk Management; gradient ctas with drop shadows. Pure CSS
  (Tailwind), no new dependencies; still a shadcn Dialog.
- **Buy/Sell toggle** sits top-right; the confirm button label follows it.
- The **order type** selector breaks confirmation into **Market** (now) vs
  **Limit** (scheduled at a price).
- A **Trade Type segmented control** (`Intraday` / `Overnight` / `GTT`)
  drives the derived product, the GTT flag and, via the leverage gate, the
  sizing multiplier.
- The **Max Quantity formula is hidden** — only the computed number is shown.
- **Risk Management** block adds optional Stop Loss (trigger price), Target
  Price, and Trailing Stop Loss (points). These are sent attached to the same
  single `placeorder` request; they are NOT separate risk orders. Brokers that
  do not consume them simply ignore them (graceful degradation).

---

### Integration Points

#### Terminal (Chart Trading)

**File:** `frontend/src/lib/trading/terminal.ts`

**Change:** Add `onOrderRequest` callback to `TerminalCallbacks` interface.

```typescript
export interface TerminalCallbacks {
  // ... existing callbacks ...
  onOrderRequest?(params: {
    side: OrderSide
    type: OrderType
    sym: SymbolView
    ltp: number | null
    product: string
  }): void
}
```

**Refactor:** Extract `placeFromMenu` body into `_executeOrder`. The original `placeFromMenu` checks for `onOrderRequest` callback and fires it instead of placing directly. A new public `confirmOrder()` method runs `_executeOrder` (called by the calculator after user confirms).

```
placeFromMenu(side, type)
  → if cb.onOrderRequest exists: fire callback, return
  → else: call _executeOrder(side, type)

confirmOrder(side, type, opts?)   // called by PositionCalculator
  opts: { product?, price?, stoploss?, target?, trailingStoploss?, gtt? }
  → _executeOrder(side, type, opts)
```

**Limit orders carry their own price.** `_executeOrder` prices a LIMIT order
from `opts.price` (the calculator's Limit Price field); every other type keeps
the chart context price (`snap(ctxPrice)`) and market orders send no price.
The price is forwarded as `price` on the REST risk path and the feed path, so
a LIMIT order fills only when the market trades at the chosen price.

**Risk params change `_executeOrder`'s transport.** `OpenAlgoTradeFeed.place`
carries a fixed `PlaceRequest` shape (symbol/exchange/side/type/qty/price/
triggerPrice/product/clientToken) that has no slot for risk fields, so when the
calculator provides `stoploss`, `target`, `trailing_stoploss` or `gtt`, the
terminal places the order through a **single** REST `POST /api/v1/placeorder`
(`this.api('placeorder', {...})`) instead of the SocketIO feed. The request
body carries the extra keys and the backend routes them by mode:

- **Live mode** → `place_order_with_auth(...)` →
  `place_order_api(order_data, auth_token)`. The risk keys
  (`stoploss`, `target`, `trailing_stoploss`, `gtt`) are **stripped** just
  before the broker call so generic brokers never reject unknown keys; they
  remain in `original_data` for the persisted/audit log.
- **Analyze mode** → `sandbox_place_order(...)`, which records the extras as
  order metadata.

When no risk params are present the original feed path (`trade.place`) is used
unchanged, preserving on-chart order lines and position markers.

#### ChartPane

**File:** `frontend/src/components/trading/ChartPane.tsx`

- Add `calcOpen` / `calcParams` state
- Add `onOrderRequest` callback to `TerminalCallbacks` — sets calcParams, opens calculator
- `handleCalcConfirm(outcome)` — updates terminal qty (lot-aware), sets terminal product from `outcome.product`, calls `terminal.confirmOrder(action, outcome.orderType, { product, price, stoploss, target, trailingStoploss, gtt })`
- Renders `<PositionCalculator>` when calcParams is set

#### OptionChain Page

**File:** `frontend/src/pages/OptionChain.tsx`

- Add `calcOpen` / `calcTarget` state
- `handlePlaceOrder` opens PositionCalculator instead of PlaceOrderDialog directly
- `handleCalcConfirm(outcome)` opens PlaceOrderDialog with `outcome.quantity` and `outcome.action`
- Renders `<PositionCalculator>` before `<PlaceOrderDialog>`

#### Holdings Page

**File:** `frontend/src/pages/Holdings.tsx`

- Same pattern as OptionChain
- Button click opens PositionCalculator
- `handleCalcConfirm(outcome)` opens PlaceOrderDialog with `outcome.quantity` and `outcome.action`

> The calculator's `onConfirm` contract changed from `(quantity, action)` to a
> single `PositionCalculatorOutcome` object so the trade type, product, GTT
> flag and risk fields travel with the confirmation. PlaceOrderDialog-based
> flows (option chain, holdings) consume `quantity`/`action` and ignore the
> rest.

---

### Backend: order schema and the risk-param strip

**Files:** `restx_api/schemas.py`, `services/place_order_service.py`

`OrderSchema` (marshmallow; unknown fields default to RAISE) was extended so
the calculator payload survives validation:

```
stoploss:        number  (float, optional)
target:          number  (float, optional)
trailing_stoploss: number (float, optional)
gtt:             boolean (default false)
```

`place_order_with_auth` passes the validated `order_data` through to the
sandbox verbatim (recorded as order metadata) and, in the **live** branch only,
pops the four risk keys just before `broker_module.place_order_api(...)`. This
keeps every current broker adapter safe: five adapters forward the whole data
dict to their API and would otherwise reject the unknown `gtt` key. The keys
stay in `original_data`, so the audit/log trail keeps them. A future broker
that consumes these on a plain order can opt back in per-broker.

---

### App Registration

**File:** `app.py`

```python
from database.intraday_leverage_db import init_db as ensure_intraday_leverage_tables_exists
from blueprints.intraday_leverage import intraday_leverage_bp

# Register blueprint
app.register_blueprint(intraday_leverage_bp)

# Add to db_init_functions list
("Intraday Leverage DB", ensure_intraday_leverage_tables_exists),
```

---

## File Change Summary

### New Files (6)

| File | Purpose |
|------|---------|
| `database/intraday_leverage_db.py` | Model, init_db, lookup functions |
| `blueprints/intraday_leverage.py` | REST API for leverage data |
| `upgrade/migrate_intraday_leverage.py` | Migration + seed from Excel |
| `frontend/src/api/intradayLeverage.ts` | Frontend API client |
| `frontend/src/components/trading/PositionCalculator.tsx` | Calculator dialog |
| `Documentation.md` | This file |

### Modified Files (5)

| File | Change |
|------|--------|
| `frontend/src/lib/trading/terminal.ts` | Add onOrderRequest callback, refactor placeFromMenu, risk-aware `_executeOrder` REST path, LIMIT price from `opts.price` |
| `frontend/src/components/trading/ChartPane.tsx` | Wire calculator to chart buy/sell, handle `PositionCalculatorOutcome`, pass outcome orderType+price |
| `frontend/src/pages/OptionChain.tsx` | Wire calculator to option chain buy/sell, outcome-based confirm |
| `frontend/src/pages/Holdings.tsx` | Wire calculator to holdings exit/add, outcome-based confirm |
| `app.py` | Register blueprint + init_db |
| `context.md` | AI-agent handover notes (per-task plan + history) |

### Latest change (this task): leverage gate + Market/Limit + 3D UI

- **Leverage gate**: the intraday multiplier sizes orders only for `INTRADAY`;
  `OVERNIGHT` and `GTT` size at cash value (`1x`). The UI labels the row
  "Leverage (not applicable)" and the Max Quantity card explains the ignored
  multiplier. User quantity is clamped whenever trade type / order type /
  limit price changes.
- **Order type selector**: `MARKET` executes now at LTP; `LIMIT` schedules at
  a user-chosen price (buy below LTP, sell above LTP), used as the sizing
  basis and sent as the order `price` (pricetype `LIMIT`).
- **3D UI redesign**: dark-glass depth styling — raised/inset 3D tiles for
  Buy/Sell, order type and trade type; gradient glow cards for Order Type,
  Max Quantity and Risk Management; gradient confirm CTA. Pure Tailwind/CSS,
  no new dependencies, existing prop/outcome contracts preserved.
| `restx_api/schemas.py` | `OrderSchema` + stoploss/target/trailing_stoploss/gtt fields |
| `services/place_order_service.py` | Strip risk keys before live broker call; pass through to sandbox |
| `upgrade/migrate_all.py` | Add migration to MIGRATIONS list |

### Latest change (this task): calculator redesign + brokerage fees

User redesign ask: bigger dialog; stock name beside the live trading price on
top (keep Buy/Sell toggle); trade types directly below; separate Capital and
Quantity sections with leverage shown as just the number; Market/Limit moved
down into a "Price" section; the old Risk Management section collapsed behind
an "Add Stop Loss / Target Price" expander; and a hidden "Brokerage" chip that
pops up an estimate — only for the brokers whose tariff sheet the platform
carries (Fyers, Zerodha, Dhan, Groww). The same brokerage estimator backs a
Charges column in the order book.

**Layout now (top to bottom):** Header (symbol + live price + exchange/product
badges + Buy/Sell toggle) → Trade Type tiles (Intraday/Overnight/GTT) → Price
section (Market/Limit tiles; limit price + validation hint when Limit) →
Capital → Quantity card (Leverage `Nx` inline, lot size, input + Max button,
max-qty readout, Brokerage chip) → Add Stop Loss / Target Price expander (Stop
Loss, Target Price, Trailing Stop Loss) → footer CTA. Bid/ask display removed
(the header price is the live LTP only). Dialog width upgraded to `sm:max-w-lg`
with an inner scroll so the longer form fits short viewports.

**Brokerage estimator (`services/brokerage_charges.py`):** pure module, no
I/O beyond reading `data/broker_charges_comparison.csv` once (lru_cache). CSV
is a committed copy of the user's tariff sheet with a Groww section appended
(the source file had Fyers/Zerodha/Dhan only). Resolves the trade segment from
exchange/product/symbol/instrumenttype (`Equity Delivery`, `Equity Intraday`,
`Futures`, `Options`; Dhan's "Futures (Equity F&O)" aliased), merges global
rows ("All Equity Segments" GST/SEBI/IPFT, "DP Charges"/"Demat Account" DP)
into every segment, and returns per-component amounts + total + notes. Three
parser defects pinned by tests: equities ending in "CE"/"PE" were resolved to
Options (RELIANCE, BAJFINANCE); STT "on buy and sell" parsed as sell-only;
GST/SEBI/DP rows under global segments were dropped. Returns 403 for brokers
outside the supported four.

**API:** `POST /brokerage-charges/api/estimate` (single) and
`POST /brokerage-charges/api/estimate/batch` (`{orders:[...]}`) under
`blueprints/brokerage_charges.py`, both `@check_session_validity`, broker read
from session. Frontend client `frontend/src/api/brokerage.ts`; `webClient`
handles CSRF automatically.

**Calculator:** Brokerage chip hidden unless `authStore.user.broker` is in the
supported set. Estimate debounced (400 ms), keyed on quantity / price basis /
product / action, priced at LTP for Market and the limit price for Limit.
Opened chip shows the component breakdown + estimated total + turnover.

**Order book:** new "Charges" column (header + cell) rendered only for
supported brokers and non-crypto; one batch call estimates every priced row
(`price>0`, `quantity>0`); cell shows the total with a hover tooltip
(segment + each component); market rows without a price stay blank.

**Backend verification:** `uv run pytest test/test_brokerage_charges.py` — 19
locked vectors, including Zerodha intraday BUY 100@500 = 21.07 and delivery SELL
= 67.21 (STT 50 + DP 15.34 included), Fyers options SELL 1 lot @200 lot75 =
54.00, Groww delivery SELL = 66.87 (DP 15 not clobbered by the zero buy row).

---

## Implementation Phases

### Phase 1: Backend

1. Create `database/intraday_leverage_db.py` — model + init + lookup
2. Create `blueprints/intraday_leverage.py` — REST API
3. Create `upgrade/migrate_intraday_leverage.py` — migration script
4. Update `upgrade/migrate_all.py` — register migration
5. Update `app.py` — register blueprint + init_db

### Phase 2: Frontend Foundation

6. Create `frontend/src/api/intradayLeverage.ts` — API client

### Phase 3: Calculator Component

7. Create `frontend/src/components/trading/PositionCalculator.tsx` — dialog UI

### Phase 4: Integration

8. Modify `terminal.ts` — add callback + refactor
9. Modify `ChartPane.tsx` — wire calculator
10. Modify `OptionChain.tsx` — wire calculator
11. Modify `Holdings.tsx` — wire calculator

---

## Testing

### Backend Tests

```bash
# Run leverage lookup tests
uv run pytest test/test_intraday_leverage.py -v

# Verify migration idempotency
uv run upgrade/migrate_intraday_leverage.py --status
uv run upgrade/migrate_intraday_leverage.py  # run once
uv run upgrade/migrate_intraday_leverage.py  # run again (should skip)
```

### Frontend Manual Tests

1. **Chart — Buy button:**
   - Open `/trading`, load SBIN
   - Click Buy → PositionCalculator appears
   - Verify: Symbol = SBIN, LTP = live price, Capital = account balance, Leverage = 5x
   - Verify: Max Qty = FLOOR((Capital x 5) / LTP)
   - Confirm → order placed

2. **Chart — Right-click:**
   - Right-click on chart → Buy Limit
   - PositionCalculator appears with same data
   - Confirm → order placed

3. **OptionChain:**
   - Open `/optionchain`, click B/S on a CE
   - PositionCalculator appears
   - Confirm → PlaceOrderDialog opens with calculated quantity

4. **Holdings:**
   - Open `/holdings`, click Exit
   - PositionCalculator appears
   - Confirm → PlaceOrderDialog opens with calculated quantity

### Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Symbol not in leverage table | Show "N/A" for leverage, default to 1x multiplier |
| Capital = 0 | Show 0 for max quantity |
| LTP = 0 or null | Show "Waiting for price..." |
| Network error fetching leverage | Show fallback message, allow manual entry |
| User overrides quantity above max | Show warning, allow (for limit orders where margin may differ) |

---

## Future Enhancements

### MTF (Margin Trading Facility)

Add a `product` toggle in the calculator (MIS = intraday, MTF = margin). The leverage table can have separate columns:
- `intraday_multiplier` (current)
- `mtf_multiplier` (to be added)

### Broker-Specific Multipliers

Different brokers offer different leverage for the same stock. Add a `broker` column to the table:
```sql
CREATE TABLE intraday_leverage (
  symbol TEXT,
  exchange TEXT,
  broker TEXT DEFAULT 'default',
  multiplier REAL,
  UNIQUE(symbol, exchange, broker)
);
```

### API-Based Leverage

Some brokers expose margin info per symbol via API. The calculator could fall back to the broker margin API (`/api/v1/margin/`) if no static multiplier exists.

### Tool Page

Register as a standalone tool in `frontend/src/lib/tools.ts` for manual use without the chart:
```typescript
{
  title: 'Position Calculator',
  description: 'Calculate max intraday quantity based on capital and leverage',
  href: '/position-calculator',
  color: 'bg-cyan-500',
}
```

---

## Multiplier Data Source

The 1,579 NSE stock multipliers come from the Excel file `fyers_intraday_calculator.xlsx`, sheet `NSE`, columns A-C:

| Column | Content |
|--------|---------|
| A | Symbol (OpenAlgo format, e.g. "SBIN") |
| B | Exchange ("NSE" for all rows) |
| C | Intraday multiplier (1, 2, 4, or 5) |

This data is embedded directly in the migration script as a Python dictionary. No runtime Excel file dependency.

---

*Built by traders, for traders — making algo trading accessible to everyone.*
