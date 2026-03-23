# Broker-Exchange Separation Audit

**Date**: 2026-03-17
**Status**: Audit Complete - Implementation Pending
**Scope**: Frontend + Backend separation of stock broker and crypto exchange features

---

## 1. Problem Statement

OpenAlgo supports 30+ Indian stock brokers and 1 crypto exchange (Delta Exchange), with more crypto exchanges planned. The current frontend treats all brokers uniformly, presenting a mixed UI where:

- **Stock brokers** see crypto-related features (CRYPTO exchange in dropdowns, Leverage page)
- **Crypto brokers** see stock-specific features (NSE/BSE/NFO/MCX/CDS exchanges, CNC product type, Indian index options)
- **Limited-exchange brokers** (e.g., Firstock, Groww, Upstox) see MCX/CDS exchanges they don't support

This creates confusion and leads to failed orders when users select unsupported exchanges.

---

## 2. Current Architecture

### 2.1 Broker Classification

| Category | Brokers | Supported Exchanges |
|----------|---------|---------------------|
| **Full Stock** (20 brokers) | Zerodha, Angel, Dhan, Dhan Sandbox, Shoonya, Motilal, Samco, IIFL, Fyers, AliceBlue, CompositEdge, FivePaisa, FivePaisaXTS, JainamXTS, DefinEdge, Wisdom, MStock, Upstox, Flattrade, Kotak | NSE, BSE, NFO, BFO, MCX, CDS (+ BCD/INDEX varies) |
| **No MCX/CDS** (6 brokers) | Groww, Paytm, IndMoney, Nubra, Firstock, Pocketful | NSE, BSE, NFO, BFO (no MCX/CDS) |
| **Partial** (4 brokers) | IBulls, RMoney, Zebu, Tradejini | Mixed — some have MCX but not CDS, or vice versa |
| **Crypto Only** (1 broker) | Delta Exchange | CRYPTO only |

### 2.2 No Exchange Metadata in Plugin System

Current `plugin.json` files contain only basic metadata:
```json
{
    "Plugin Name": "zerodha",
    "Description": "Zerodha OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R"
}
```

There is **no `supported_exchanges` field** and **no `broker_type` field** (stock/crypto). Exchange capabilities are implicitly encoded in each broker's `mapping/` and `database/master_contract_db.py` files.

### 2.3 Backend Constants (`utils/constants.py`)

```python
CRYPTO_EXCHANGES = {"CRYPTO"}
CRYPTO_BROKERS = {"deltaexchange"}
VALID_EXCHANGES = ["NSE", "NFO", "CDS", "BSE", "BFO", "BCD", "MCX", "NCDEX", "NSE_INDEX", "BSE_INDEX", "CRYPTO"]
```

`CRYPTO_BROKERS` exists but is only used for currency formatting (INR vs USD) and session expiry logic. It is **not exposed to the frontend**.

### 2.4 Frontend Has No Broker Capability Awareness

The frontend gets `user.broker` (broker name string) from the auth store but has **no API endpoint** to query what exchanges that broker supports. All exchange lists are hardcoded per-page.

---

## 3. Affected Pages - Detailed Analysis

### 3.1 Pages That Need Stock/Crypto Separation

#### Leverage (`/frontend/src/pages/Leverage.tsx`)
- **Current**: Hardcoded for Delta Exchange crypto leverage only
- **Problem**: Visible to all brokers, but only functional for crypto
- **Fix**: Hide entirely for stock brokers. Show only when `broker_type === "crypto"`

#### TradingView (`/frontend/src/pages/TradingView.tsx`)
- **Current**: Hardcoded exchanges: `[NSE, NFO, BSE, BFO, CDS, MCX]` (stock only)
- **Current Products**: `[MIS, NRML, CNC]` (stock only)
- **Problem**: No CRYPTO exchange option; products don't apply to crypto
- **Done**:
  - Exchanges now from `tradingExchanges` via `useSupportedExchanges()` hook
  - Product dropdown hidden for crypto brokers (`isCrypto`)
  - Default symbol: `BTCUSDFUT` for crypto, `NHPC` for stock
  - Default exchange: from broker capabilities

#### GoCharting (`/frontend/src/pages/GoCharting.tsx`)
- **Current**: Hardcoded exchanges: `[NSE, NFO, BSE, BFO, CDS, MCX]` (stock only)
- **Current Products**: `[MIS, NRML, CNC]` (stock only)
- **Problem**: Same as TradingView - no crypto support, stock-specific products
- **Done**: Same approach as TradingView — `tradingExchanges` from hook, Product hidden for crypto, crypto defaults

#### Historify (`/frontend/src/pages/Historify.tsx`)
- **Current**: Hardcoded 10 exchanges including CRYPTO mixed with stock
- **Default Exchange**: `NSE` (wrong for crypto brokers)
- **Problem**: Crypto broker users see NSE/BSE/NFO which they can't use; stock users see CRYPTO
- **Fix** (pending):
  - Stock brokers: Show only their supported stock exchanges
  - Crypto brokers: Show only `CRYPTO`
  - Default exchange should match broker type

#### Search / Token Search (`/frontend/src/pages/Token.tsx`)
- **Current**: 9 hardcoded exchanges including CRYPTO
- **FNO Exchanges**: `[NFO, BFO, MCX, CDS, CRYPTO]` (mixed stock and crypto)
- **Problem**: Stock users see CRYPTO; crypto users see 8 irrelevant stock exchanges
- **Done**:
  - Exchanges now from `allExchanges` via hook (includes _INDEX for token lookup)
  - FNO check uses `fnoExchanges` from hook
  - Crypto-specific search tips (BTCUSDFUT, BTCINR, BTC options)
  - Stock-specific search tips (RELIANCE, INFY, nifty)
  - Dynamic placeholder text based on broker type

#### Playground (`/frontend/src/pages/Playground.tsx`)
- **Current**: Single set of API examples (stock-oriented symbol formats)
- **Problem**: Crypto users get stock examples (RELIANCE, NIFTY) that don't work
- **Done**:
  - Bruno collections split into `collections/openalgo/IN_stock/` and `collections/openalgo/crypto/`
  - `playground.py` loads from broker-type-specific subfolder based on session broker's `broker_type` from plugin.json capabilities
  - Crypto collection: 48 files with BTCUSDFUT, CRYPTO exchange, NRML product (no holdings.bru, Chartink.bru, syntheticfuture.bru)
  - Stock collection: original 62 files unchanged
  - WebSocket presets in `MessageComposer.tsx`: dynamic symbols based on `isCrypto` (BTCUSDFUT/CRYPTO for crypto, RELIANCE/NSE for stock)

#### Flow Editor (`/frontend/src/pages/flow/FlowIndex.tsx`)
- **Current**: Generic webhook automation, example payloads use stock symbols (RELIANCE, INFY)
- **Problem**: Examples don't help crypto users
- **Fix**: Conditional example payloads based on broker type

#### OptionChain (`/frontend/src/pages/OptionChain.tsx`)
- **Current**: `FNO_EXCHANGES = [NFO, BFO, CRYPTO]` with mixed underlyings
- **Default Underlyings**: `{NFO: [NIFTY, BANKNIFTY...], BFO: [SENSEX...], CRYPTO: [BTC, ETH...]}`
- **Problem**: Stock users see CRYPTO tab; crypto users see NFO/BFO tabs
- **Fix**:
  - Stock brokers: Show `[NFO, BFO]` only
  - Crypto brokers: Show `[CRYPTO]` only

#### CustomStraddle (`/frontend/src/pages/CustomStraddle.tsx`)
- **Current**: Stock F&O only `[NFO, BFO]` with Indian index defaults
- **Problem**: Not applicable to crypto - entirely stock-specific feature
- **Fix**: Hide for crypto brokers

### 3.2 Pages That Need Exchange Filtering (Not Full Separation)

| Page | File | Current Behavior | Fix Done |
|------|------|-----------------|----------|
| **PlaceOrderDialog** | `components/trading/PlaceOrderDialog.tsx` | Product types based on exchange (FNO vs equity) | Pending — add crypto product handling |
| **Positions** | `pages/Positions.tsx` | Dynamic exchange filter from data | Done — Product column hidden for crypto via `isCrypto` |
| **TradeBook** | `pages/TradeBook.tsx` | Dynamic exchange filter from data | Done — Product column hidden for crypto via `isCrypto` |
| **OrderBook** | `pages/OrderBook.tsx` | No exchange filter | Done — Product column hidden for crypto via `isCrypto` |
| **Holdings** | `pages/Holdings.tsx` | No exchange filter | Done — Page hidden for crypto (route guard + nav filter). Crypto has no equity holdings; wallet balances shown in Positions |
| **PnL Tracker** | `pages/PnLTracker.tsx` | Uses broker for currency formatting | Already handled |

### 3.3 Pages That Need No Changes

| Page | Reason |
|------|--------|
| **Dashboard** | Aggregated data, broker-agnostic |
| **API Key** | Generic |
| **Telegram** | Generic notification system |
| **Logs** | Generic |
| **Profile / Admin** | Generic |
| **Strategy (Python/Chartink)** | User-defined, broker-agnostic |
| **Action Center** | Generic order approval |
| **Analyzer / Sandbox** | Uses same order schemas |

### 3.4 Navigation & Menu Visibility

**File**: `/frontend/src/components/layout/Navbar.tsx`

Navigation menu items are now conditionally filtered in `Navbar.tsx` using `useBrokerStore` capabilities:

| Menu Item | Stock Brokers | Crypto Brokers | Implementation |
|-----------|:---:|:---:|---|
| Leverage | Hidden | Visible | `leverage_config === true` check + `LeverageRoute` guard |
| Holdings | Visible | Hidden | `broker_type !== 'crypto'` check + `HoldingsRoute` guard |
| CustomStraddle | Visible | Visible | Shown for both (crypto has options) |
| All Tools pages | Visible | Visible | Exchange dropdown filtered by broker capabilities |

---

## 4. Proposed Solution

### 4.1 Add `supported_exchanges` to `plugin.json`

Each broker's `plugin.json` declares its supported exchanges, broker type, and leverage config:

```json
{
    "Plugin Name": "zerodha",
    "Description": "Zerodha OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R",
    "supported_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX"],
    "broker_type": "IN_stock",
    "leverage_config": false
}
```

```json
{
    "Plugin Name": "deltaexchange",
    "Description": "Delta Exchange OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Bashab Bhattacharjee",
    "supported_exchanges": ["CRYPTO"],
    "broker_type": "crypto",
    "leverage_config": true
}
```

```json
{
    "Plugin Name": "Firstock",
    "Description": "Firstock OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R",
    "broker_type": "stock",
    "supported_exchanges": ["NSE", "BSE", "NFO", "BFO"]
}
```

```json
{
    "Plugin Name": "groww",
    "Description": "Groww OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R",
    "broker_type": "stock",
    "supported_exchanges": ["NSE", "BSE"]
}
```

### 4.2 New Backend API Endpoint

Create `GET /api/broker/capabilities` that returns broker metadata to the frontend:

```json
{
    "status": "success",
    "data": {
        "broker_name": "zerodha",
        "broker_type": "IN_stock",
        "supported_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX"],
        "leverage_config": false
    }
}
```

For crypto broker:
```json
{
    "status": "success",
    "data": {
        "broker_name": "deltaexchange",
        "broker_type": "crypto",
        "supported_exchanges": ["CRYPTO"],
        "leverage_config": true
    }
}
```

**Implementation**: `utils/plugin_loader.py` reads all `plugin.json` files at startup into an in-memory dict. `blueprints/broker_credentials.py` serves `GET /api/broker/capabilities` from this cache. Zero file I/O per request.

### 4.3 Frontend Broker Capabilities Store

Create a new store or extend `authStore` to cache broker capabilities:

```typescript
// frontend/src/stores/brokerStore.ts (new file)

interface BrokerCapabilities {
  broker_name: string
  broker_type: 'IN_stock' | 'crypto'
  supported_exchanges: string[]
  leverage_config: boolean
}
```

Fetch once on login via `AuthSync.tsx`, cache in Zustand `brokerStore.ts`. All pages consume from `useSupportedExchanges()` hook instead of hardcoding exchange lists.

### 4.4 Page-Level Changes Summary

| Page | Change Type | Description |
|------|------------|-------------|
| **Leverage** | Conditional Route | Only render route if `leverage_config === true` |
| **TradingView** | Exchange Filter | Load exchanges from `supported_exchanges`; swap product list for crypto |
| **GoCharting** | Exchange Filter | Same as TradingView |
| **Historify** | Exchange Filter | Load exchanges from `supported_exchanges`; default exchange matches broker type |
| **Search/Token** | Exchange Filter | Filter exchange list from `supported_exchanges`; separate FNO sublist |
| **Playground** | Collection Swap | Load `stock-examples.json` or `crypto-examples.json` based on `broker_type` |
| **Flow Editor** | Example Swap | Show stock or crypto webhook payload examples |
| **OptionChain** | Exchange Filter | Stock: `[NFO, BFO]`; Crypto: `[CRYPTO]` from `supported_exchanges` |
| **CustomStraddle** | Conditional Route | Only render if `features.custom_straddle === true` |
| **Navigation** | Conditional Items | Hide/show menu items based on `features` flags |
| **PlaceOrderDialog** | Product Logic | Add crypto product types alongside stock MIS/NRML/CNC |

### 4.5 Exchange Config per Broker Folder

Update each broker's `plugin.json` with `broker_type` and `supported_exchanges`:

Source of truth: `broker/*/database/master_contract_db.py` — the master contract download function defines exactly which exchanges each broker processes.

| Broker | `broker_type` | `supported_exchanges` (from master_contract_db.py) |
|--------|--------------|-----------------------------------------------------|
| zerodha | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX, MCX_INDEX, CDS_INDEX |
| angel | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX, MCX_INDEX |
| dhan | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| dhan_sandbox | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| fyers | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| kotak | stock | NSE, BSE, NFO, BFO, CDS, MCX |
| motilal | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| samco | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| shoonya | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| iifl | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| aliceblue | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| compositedge | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fivepaisa | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fivepaisaxts | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| jainamxts | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| indmoney | stock | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| nubra | stock | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| rmoney | stock | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| definedge | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX, MCX_INDEX |
| wisdom | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| mstock | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| paytm | stock | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| tradejini | stock | NSE, BSE, NFO, BFO, CDS, MCX |
| firstock | stock | NSE, BSE, NFO, BFO, NSE_INDEX |
| flattrade | stock | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX |
| pocketful | stock | NSE, BSE, NFO, BFO, MCX, NSE_INDEX |
| zebu | stock | NSE, BSE, NFO, BFO, CDS, MCX |
| ibulls | stock | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| groww | stock | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| upstox | stock | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| deltaexchange | crypto | CRYPTO |

**Key corrections from previous estimates:**
- **Groww**: Supports NFO, BFO (not equity-only as previously assumed)
- **Upstox**: Full exchange support including CDS, BCD, MCX (not limited)
- **Firstock**: Also supports NSE_INDEX
- **Flattrade**: Supports CDS, MCX (not limited to NSE/BSE/NFO/BFO)
- **Paytm**: Does NOT support MCX, CDS (equity + equity F&O only)
- **IndMoney**: Does NOT support MCX, CDS (equity + equity F&O only)
- **Nubra**: Does NOT support MCX, CDS (equity + equity F&O only)

---

## 5. Tools Section - Deep Analysis

The Tools landing page (`/tools`) provides 10 analytical subpages for options trading. Most tools already include CRYPTO in their exchange dropdowns alongside NFO/BFO, but they need proper separation so stock brokers don't see CRYPTO and crypto brokers don't see NFO/BFO.

### 5.1 Tools Exchange Configuration

All tool subpages (except Straddle PnL) share the same hardcoded exchange + underlying config:

```typescript
// Current: Mixed stock + crypto in one array
const FNO_EXCHANGES = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
  { value: 'CRYPTO', label: 'CRYPTO' },
]

const DEFAULT_UNDERLYINGS = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
  CRYPTO: ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'],
}
```

### 5.2 Per-Tool Analysis

| Tool | Route | File | Exchanges | Crypto? | Separation Needed |
|------|-------|------|-----------|---------|-------------------|
| **Option Chain** | `/optionchain` | `OptionChain.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **Option Greeks** | `/ivchart` | `IVChart.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **OI Tracker** | `/oitracker` | `OITracker.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **Max Pain** | `/maxpain` | `MaxPain.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **Straddle Chart** | `/straddle` | `StraddleChart.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **Straddle PnL** | `/straddlepnl` | `CustomStraddle.tsx` | **NFO, BFO only** | **No** | Hide for crypto brokers |
| **Vol Surface** | `/volsurface` | `VolSurface.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **GEX Dashboard** | `/gex` | `GEXDashboard.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **IV Smile** | `/ivsmile` | `IVSmile.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |
| **OI Profile** | `/oiprofile` | `OIProfile.tsx` | NFO, BFO, CRYPTO | Yes | Filter by broker_type |

### 5.3 Data Points per Tool

| Tool | Data | Stock-Specific Notes | Crypto-Specific Notes |
|------|------|---------------------|----------------------|
| **Option Chain** | OI, LTP, Bid/Ask, Volume, PCR | Lot sizes (NIFTY: 65, BANKNIFTY: 30) | Fractional quantities, 24/7 data |
| **Option Greeks** | IV, Delta, Theta, Vega, Gamma | IST market hours | UTC timestamps, 24/7 |
| **OI Tracker** | CE/PE OI, PCR, Futures price | Lot-based OI | Contract-based OI |
| **Max Pain** | Pain distribution in Crores | Currency: INR (Crs.) | Currency: USD |
| **Straddle Chart** | ATM straddle price, spot, synthetic | IST time labels | UTC time labels |
| **Straddle PnL** | Simulated P&L, trade log | Indian index lot sizes, adjustment points | **N/A - stock only** |
| **Vol Surface** | 3D IV matrix (strike x expiry) | Multiple monthly/weekly expiries | Different expiry structure |
| **GEX Dashboard** | Gamma exposure, OI walls | `gamma x OI x lotsize` | Same formula, different scale |
| **IV Smile** | Call/Put IV curves, skew | 25-delta skew reference | Same concept applies |
| **OI Profile** | Futures OHLC + OI butterfly | NSE/BSE futures | Crypto perpetual futures |

### 5.4 Tools Landing Page Changes

**File**: `/frontend/src/pages/Tools.tsx`

The Tools grid currently shows all 10 tools to all users. With broker_type awareness:

**Stock brokers see**: All 10 tools (with NFO/BFO exchanges only in dropdowns)

**Crypto brokers see**: 9 tools (Straddle PnL hidden), with CRYPTO exchange only in dropdowns

**Equity-only brokers** (Groww, Upstox with no FNO): Tools section should show a message that options tools require F&O-enabled broker, or hide the Tools menu entirely

### 5.5 Recommended Fix for Tools

Instead of duplicating exchange arrays in every tool file, create a shared hook:

```typescript
// frontend/src/hooks/useFnoExchanges.ts (new)
export function useFnoExchanges() {
  const capabilities = useBrokerCapabilities()
  const supported = capabilities.supported_exchanges

  if (capabilities.broker_type === 'crypto') {
    return {
      exchanges: [{ value: 'CRYPTO', label: 'CRYPTO' }],
      defaultExchange: 'CRYPTO',
      defaultUnderlyings: { CRYPTO: ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'] },
    }
  }

  // Stock broker: filter to only FNO exchanges they support
  const fnoExchanges = ['NFO', 'BFO'].filter(e => supported.includes(e))
  return {
    exchanges: fnoExchanges.map(e => ({ value: e, label: e })),
    defaultExchange: fnoExchanges[0] || 'NFO',
    defaultUnderlyings: {
      NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
      BFO: ['SENSEX', 'BANKEX'],
    },
  }
}
```

All 10 tool pages import `useSupportedExchanges()` (single combined hook at `frontend/src/hooks/useSupportedExchanges.ts`) instead of hardcoding their own arrays. This hook returns `fnoExchanges`, `tradingExchanges`, `allExchanges`, `defaultUnderlyings`, and `isCrypto`. This ensures:
- Stock brokers see only NFO/BFO
- Crypto brokers see only CRYPTO
- Future crypto exchanges automatically inherit this behavior
- Equity-only brokers (no FNO) get an empty exchange list (tools become unavailable)

### 5.6 Currency Formatting in Tools

**Max Pain** currently formats values in Crores (INR). For crypto brokers, this should be USD:

| Tool | Current Format | Stock Broker | Crypto Broker |
|------|---------------|-------------|--------------|
| Max Pain | `₹10.50 Crs.` | `₹10.50 Crs.` | `$10.50K` or `$10,500` |
| GEX Dashboard | Absolute values | INR-based display | USD-based display |

The `makeFormatCurrency()` utility in `/frontend/src/lib/utils.ts` already handles INR vs USD based on broker name. Tool pages should use this consistently.

---

## 6. Product Type Normalization (REST API Schemas)

### 6.1 The Problem

The REST API schemas in `restx_api/schemas.py` hardcode product validation to stock broker values:

```python
product = fields.Str(missing="MIS", validate=validate.OneOf(["MIS", "NRML", "CNC"]))
```

Crypto brokers like Delta Exchange **do not use MIS, NRML, or CNC**. These are Indian stock market concepts:
- **MIS** (Margin Intraday Square-off) — auto-squared off at EOD
- **NRML** (Normal) — carry-forward derivatives
- **CNC** (Cash and Carry) — delivery-based equity

Delta Exchange currently works around this by:
1. Accepting `NRML` or `MIS` from the API (schema passes validation)
2. Silently ignoring the value in `map_product_type()` (passthrough, not used)
3. Hardcoding `NRML` in `reverse_map_product_type()` for all positions/orders returned
4. Using `CNC` for spot wallet holdings and `NRML` for derivatives

This workaround is fragile and semantically incorrect. As more crypto exchanges are added, each would need the same silent-ignore hack.

### 6.2 Affected Schemas

All schemas with product validation in `restx_api/schemas.py`:

| Schema | Product Field | Current Validation |
|--------|--------------|-------------------|
| `OrderSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])`, default `MIS` |
| `SmartOrderSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])`, default `MIS` |
| `ModifyOrderSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])` (required) |
| `BasketOrderItemSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])`, default `MIS` |
| `SplitOrderSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])`, default `MIS` |
| `OptionsOrderSchema` | `product` | `OneOf(["MIS", "NRML"])`, default `MIS` |
| `OptionsMultiOrderLegSchema` | `product` | `OneOf(["MIS", "NRML"])`, default `MIS` |
| `MarginPositionSchema` | `product` | `OneOf(["MIS", "NRML", "CNC"])` (required) |

### 6.3 Proposed Solution

**Option A: Expand validation to include crypto product types (recommended)**

Add crypto-compatible product types that normalize in the broker mapping layer:

```python
VALID_PRODUCTS_ALL = ["MIS", "NRML", "CNC", "CROSS", "ISOLATED"]

product = fields.Str(
    missing="MIS",
    validate=validate.OneOf(VALID_PRODUCTS_ALL)
)
```

Where:
- `CROSS` — Cross-margin (crypto derivatives, shared margin pool)
- `ISOLATED` — Isolated margin (crypto derivatives, per-position margin)

Each crypto broker's `map_product_type()` would then translate:
- `CROSS` → broker-specific cross-margin parameter
- `ISOLATED` → broker-specific isolated-margin parameter
- `NRML`/`MIS` → fallback to default crypto margin mode (backward compatibility)

**Option B: Make product validation exchange-aware**

Validate product based on the `exchange` field in the same request:

```python
@post_load
def validate_product_for_exchange(self, data, **kwargs):
    exchange = data.get("exchange", "")
    product = data.get("product", "")
    if exchange == "CRYPTO" and product in ("MIS", "CNC"):
        data["product"] = "NRML"  # Normalize to NRML for crypto
    return data
```

**Option C: Accept any product for crypto exchanges (most flexible)**

Skip product validation when `exchange == "CRYPTO"` since the broker mapping layer handles normalization anyway. This is the least disruptive change but loses schema-level documentation of valid values.

### 6.4 Frontend Impact

The product type dropdowns on trading pages also need updating:

| Page | Current Products | Stock Broker | Crypto Broker |
|------|-----------------|-------------|--------------|
| **TradingView** | MIS, NRML, CNC | MIS, NRML, CNC | CROSS, ISOLATED (or hide product) |
| **GoCharting** | MIS, NRML, CNC | MIS, NRML, CNC | CROSS, ISOLATED (or hide product) |
| **PlaceOrderDialog** | MIS/NRML (F&O), CNC/MIS (equity) | No change | CROSS, ISOLATED |
| **Flow Editor** | Webhook payload examples | Stock products | Crypto products |

### 6.5 Backward Compatibility

Any change must maintain backward compatibility:
- Existing API users sending `product: "NRML"` to Delta Exchange must continue to work
- The broker mapping layer already ignores the product value for crypto
- New crypto product types (`CROSS`, `ISOLATED`) should be additive, not replacing

---

## 7. Implementation Priority

### Phase 1: Foundation (Backend)
1. Add `broker_type` and `supported_exchanges` to all 31 `plugin.json` files
2. Create `GET /api/v1/broker/capabilities` endpoint
3. Update `utils/plugin_loader.py` to parse new fields
4. Normalize product types in `restx_api/schemas.py` — expand `OneOf` validation to include crypto products (`CROSS`, `ISOLATED`) or make validation exchange-aware

### Phase 2: Frontend Store + Shared Hooks
4. Create `brokerStore.ts` with capabilities caching
5. Fetch capabilities on login, expose via hook `useBrokerCapabilities()`
6. Create `useFnoExchanges()` shared hook for all Tools subpages
7. Create `useExchanges()` shared hook for non-FNO pages (TradingView, GoCharting, etc.)

### Phase 3: Page Separation (High Priority)
8. **Leverage page**: Conditional route (crypto only)
9. **TradingView / GoCharting**: Exchange + product filtering
10. **Search/Token**: Exchange list filtering
11. **Navigation**: Conditional menu items (hide Leverage for stock, hide Straddle PnL for crypto)

### Phase 4: Tools Section
12. **Tools landing page**: Conditional tool cards based on broker_type
13. **9 tool subpages** (OptionChain, IVChart, OITracker, MaxPain, StraddleChart, VolSurface, GEX, IVSmile, OIProfile): Replace hardcoded `FNO_EXCHANGES` with `useFnoExchanges()` hook
14. **Straddle PnL (CustomStraddle)**: Conditional route (stock only, hide for crypto)
15. **Max Pain / GEX**: Currency formatting (INR Crores vs USD)

### Phase 5: Remaining Pages
16. **Historify**: Exchange filtering + default exchange based on broker_type
17. **Playground**: Separate stock vs crypto example collections
18. **Flow Editor**: Conditional example payloads (stock symbols vs crypto pairs)

### Phase 6: Future Crypto Exchanges
19. When adding new crypto exchanges, only need to:
    - Create `broker/new_crypto_exchange/` with standard structure
    - Add `plugin.json` with `broker_type: "crypto"` and `supported_exchanges: ["CRYPTO"]`
    - Frontend automatically adapts via capabilities API and shared hooks

---

## 8. Files to Modify

### Backend (8 files + 31 plugin.json)
| File | Change |
|------|--------|
| `broker/*/plugin.json` (x31) | Add `broker_type` and `supported_exchanges` |
| `utils/plugin_loader.py` | Parse new plugin.json fields |
| `restx_api/` (new endpoint) | `GET /api/v1/broker/capabilities` |
| `restx_api/schemas.py` | Expand product validation for crypto (`CROSS`, `ISOLATED`) |
| `utils/constants.py` | Add `STOCK_EXCHANGES`, `VALID_PRODUCTS_CRYPTO`, refine `CRYPTO_EXCHANGES` |
| `database/historify_db.py` | Make `SUPPORTED_EXCHANGES` dynamic per broker |
| `services/historify_service.py` | Filter exchanges by broker capabilities |
| `broker/deltaexchange/mapping/transform_data.py` | Map `CROSS`/`ISOLATED` to Delta Exchange margin modes |

### Frontend (22 files + 4 new)
| File | Change |
|------|--------|
| `stores/brokerStore.ts` | **New** - broker capabilities store |
| `api/broker.ts` | **New** - capabilities API client |
| `hooks/useFnoExchanges.ts` | **New** - shared FNO exchange hook for all Tools |
| `hooks/useExchanges.ts` | **New** - shared exchange hook for non-FNO pages |
| `config/navigation.ts` | Conditional menu items based on broker_type |
| `pages/Leverage.tsx` | Guard: crypto only |
| `pages/TradingView.tsx` | Dynamic exchanges + products |
| `pages/GoCharting.tsx` | Dynamic exchanges + products |
| `pages/Historify.tsx` | Dynamic exchanges + default |
| `pages/Search.tsx` | Dynamic exchanges + FNO filter |
| `pages/Playground.tsx` | Separate stock vs crypto example collections |
| `pages/flow/FlowIndex.tsx` | Conditional examples |
| `pages/Tools.tsx` | Conditional tool cards based on broker_type |
| `pages/OptionChain.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/IVChart.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/OITracker.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/MaxPain.tsx` | Replace FNO_EXCHANGES + currency formatting |
| `pages/StraddleChart.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/CustomStraddle.tsx` | Guard: stock only (hide route for crypto) |
| `pages/VolSurface.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/GEXDashboard.tsx` | Replace FNO_EXCHANGES + currency formatting |
| `pages/IVSmile.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/OIProfile.tsx` | Replace hardcoded FNO_EXCHANGES with useFnoExchanges() |
| `pages/Holdings.tsx` | Normalize product display for crypto (CROSS/ISOLATED instead of CNC/NRML) |
| `pages/OrderBook.tsx` | Normalize product column display; crypto orders show crypto product types |
| `pages/TradeBook.tsx` | Normalize product column display for crypto trades |
| `pages/Positions.tsx` | Normalize product display + currency formatting (USD vs INR) |
| `components/trading/PlaceOrderDialog.tsx` | Crypto product types in dropdown |
| `App.tsx` | Conditional routes (Leverage, Straddle PnL) |
| `lib/flow/constants.ts` | Split exchange constants |

---

## 9. Trading Pages Normalization (Holdings / OrderBook / TradeBook / Positions)

These four core pages display data returned by broker mapping layers. Currently they show stock-centric labels that are meaningless for crypto:

### 9.1 Current Behavior

| Page | Product Column Shows | Currency | Issue for Crypto |
|------|---------------------|----------|-----------------|
| **Holdings** | `CNC` (hardcoded in Delta mapping) | Already uses `makeFormatCurrency` (INR/USD) | `CNC` label makes no sense for crypto spot holdings |
| **OrderBook** | `NRML` (hardcoded in Delta mapping) | Already uses `makeFormatCurrency` | `NRML` label makes no sense for crypto orders |
| **TradeBook** | `NRML` (hardcoded in Delta mapping) | Already uses `makeFormatCurrency` | `NRML` label makes no sense for crypto trades |
| **Positions** | `NRML` or `CNC` (Delta mapping) | Already uses `makeFormatCurrency` | Labels don't convey margin mode |

### 9.2 Actual Findings from Delta Exchange API

Raw API response analysis (captured 2026-03-20) revealed:

**Orders (`GET /v2/orders`) contain `margin_mode` field:**
```json
{
  "margin_mode": "cross",
  "product_symbol": "BTCUSD",
  "product": {
    "contract_type": "perpetual_futures"
  }
}
```

**Key finding**: `margin_mode` (`"cross"` / `"isolated"`) IS available in order responses, but it serves a different purpose than MIS/NRML/CNC:
- MIS/NRML/CNC answers: **"how long do you hold?"** (intraday vs carry-forward vs delivery)
- Cross/Isolated answers: **"how is your margin protected?"** (shared pool vs per-position)

These concepts have no meaningful mapping between them. Crypto has no EOD square-off, no delivery concept.

**Wallet (`GET /v2/wallet/balances`)**: Single unified wallet — no separate spot vs derivatives wallet. Same BTC balance is used for spot trading and derivative margin. `blocked_margin` shows how much is locked for open positions.

### 9.3 Implementation Decision: Hide Product Column for Crypto

Instead of mapping to CROSS/ISOLATED (which adds complexity for no functional benefit), the Product column is **hidden entirely** for crypto brokers:

**Stock brokers**: Continue showing MIS, NRML, CNC (unchanged)
**Crypto brokers**: Product column hidden — table header, cell, CSV export, and filter chips all conditionally removed using `isCrypto` from `useSupportedExchanges()` hook

Pages updated:
- `OrderBook.tsx` — Product column, CSV export, modify dialog
- `TradeBook.tsx` — Product column, CSV export, filter dialog + chips
- `Positions.tsx` — Product column, CSV export, filter dialog + chips

### 9.4 Additional Display Differences

| Element | Stock Brokers | Crypto Brokers |
|---------|-------------|--------------|
| **Exchange badge** | NSE, BSE, NFO, BFO, etc. | CRYPTO |
| **Product column** | MIS, NRML, CNC (visible) | Hidden |
| **Quantity** | Integer (lots) | Fractional (0.001 BTC) |
| **Currency** | INR (already handled) | USD (already handled) |
| **Trading hours** | IST market hours | 24/7 |
| **Symbol format** | RELIANCE, NIFTY24JAN24000CE | BTCUSD.P, ETHUSD-25MAR25-2000-C |

The quantity formatting already handles fractional values since Delta Exchange uses `float` for sizes. Currency formatting is already handled by `makeFormatCurrency()`.

---

## 10. Sandbox / Analyzer Mode Normalization

### 10.1 The Problem

The sandbox (analyzer) mode has exchange-specific square-off timings hardcoded for Indian stock markets in `database/sandbox_db.py`:

```python
{"config_key": "nse_bse_square_off_time", "config_value": "15:15", "description": "Square-off time for NSE/BSE MIS positions (IST)"},
{"config_key": "cds_bcd_square_off_time", "config_value": "16:45", "description": "Square-off time for CDS/BCD MIS positions (IST)"},
{"config_key": "mcx_square_off_time",     "config_value": "23:30", "description": "Square-off time for MCX MIS positions (IST)"},
{"config_key": "ncdex_square_off_time",   "config_value": "17:00", "description": "Square-off time for NCDEX MIS positions (IST)"},
```

Crypto markets are **24x5** (or 24x7 depending on exchange). These IST-based square-off times are meaningless for crypto and would incorrectly auto-close crypto positions.

### 10.2 What Needs to Change

| Setting | Stock Broker | Crypto Broker |
|---------|-------------|--------------|
| MIS square-off times | NSE 15:15, MCX 23:30, etc. | **Disabled** — no auto-square-off (or configurable per-session) |
| Fund reset time | 00:00 IST | 00:00 UTC (or IST, configurable) |
| MIS leverage settings | Exchange-specific | Not applicable (leverage set at broker level) |
| Trading hours | Exchange-specific windows | 24x5 or 24x7 |
| Session expiry | 03:00 IST daily | Disabled (already handled in `authStore.ts`) |

### 10.3 Sandbox Frontend Pages

The sandbox settings UI (`/sandbox`) likely exposes these square-off time configurations. For crypto brokers:
- Hide MIS square-off time settings (MIS doesn't exist for crypto)
- Hide exchange-specific leverage settings
- Show crypto-relevant settings (if any)

### 10.4 Implementation

- Add a `crypto_square_off_time` config key with a sensible default (e.g., disabled or `"none"`)
- In the square-off scheduler service, skip scheduling for crypto exchanges
- Frontend sandbox settings page: conditionally show/hide settings based on `broker_type`

---

## 11. Backward Compatibility

- Existing brokers without updated `plugin.json` should fall back to showing all exchanges (current behavior)
- The `broker_type` field defaults to `"stock"` if not specified
- Existing API users sending `product: "NRML"` to crypto brokers must continue to work (broker mapping layer normalizes)
- New crypto product types (`CROSS`, `ISOLATED`, `SPOT`) are additive — they don't replace existing stock product types
- REST API `VALID_EXCHANGES` validation remains unchanged (accepts all exchanges; broker-level filtering is a UX concern)
- **Product labels on trading pages**: For crypto brokers, Holdings/OrderBook/TradeBook/Positions must NOT display `MIS`, `NRML`, or `CNC` — these are stock-specific terms. The backend mapping layer should return crypto-native labels (`SPOT`, `CROSS`, `ISOLATED`), and the frontend should render whatever the backend provides without stock-specific assumptions
