# OpenAlgo Desktop - Tauri Commands API Reference

**Version:** 1.0.0
**Date:** December 2024

---

## 1. Command Overview

All Tauri commands are invoked from the frontend using the `@tauri-apps/api` package:

```typescript
import { invoke } from '@tauri-apps/api/core';

// Example invocation
const result = await invoke('place_order', {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  action: 'BUY',
  quantity: 100,
  product: 'MIS',
  priceType: 'MARKET'
});
```

---

## 2. Authentication Commands

### 2.1 `login`

Authenticate user with username and password.

```typescript
invoke('login', {
  username: string,
  password: string
}) -> Promise<LoginResponse>
```

**Response:**
```typescript
interface LoginResponse {
  success: boolean;
  user: {
    id: number;
    username: string;
    email: string;
    isAdmin: boolean;
  };
  sessionToken: string;
  expiresAt: string;
}
```

### 2.2 `logout`

End current session.

```typescript
invoke('logout') -> Promise<void>
```

### 2.3 `get_session`

Get current session information.

```typescript
invoke('get_session') -> Promise<Session | null>
```

**Response:**
```typescript
interface Session {
  userId: number;
  username: string;
  broker: string | null;
  brokerConnected: boolean;
  expiresAt: string;
}
```

### 2.4 `broker_login`

Initiate broker OAuth login.

```typescript
invoke('broker_login', {
  broker: string  // 'angel', 'zerodha', 'dhan', etc.
}) -> Promise<BrokerLoginResponse>
```

**Response:**
```typescript
interface BrokerLoginResponse {
  loginUrl: string;      // OAuth URL to open in browser
  callbackPort: number;  // Local port for callback
}
```

### 2.5 `broker_callback`

Handle OAuth callback from broker.

```typescript
invoke('broker_callback', {
  broker: string,
  requestToken: string,
  additionalParams?: Record<string, string>
}) -> Promise<BrokerSession>
```

**Response:**
```typescript
interface BrokerSession {
  broker: string;
  clientId: string;
  isConnected: boolean;
  expiresAt: string;
}
```

### 2.6 `get_broker_status`

Get current broker connection status.

```typescript
invoke('get_broker_status') -> Promise<BrokerStatus>
```

**Response:**
```typescript
interface BrokerStatus {
  broker: string | null;
  clientId: string | null;
  isConnected: boolean;
  lastConnected: string | null;
}
```

---

## 3. Order Commands

### 3.1 `place_order`

Place a new order.

```typescript
invoke('place_order', {
  symbol: string,
  exchange: string,       // NSE, NFO, BSE, BFO, CDS, MCX
  action: string,         // BUY, SELL
  quantity: number,
  product: string,        // CNC, MIS, NRML
  priceType: string,      // MARKET, LIMIT, SL, SL-M
  price?: number,         // Required for LIMIT, SL
  triggerPrice?: number,  // Required for SL, SL-M
  disclosedQty?: number,
  strategy?: string
}) -> Promise<OrderResponse>
```

**Response:**
```typescript
interface OrderResponse {
  status: 'success' | 'error';
  orderId: string;
  brokerOrderId: string;
  message: string;
}
```

### 3.2 `place_smart_order`

Place order with position sizing.

```typescript
invoke('place_smart_order', {
  symbol: string,
  exchange: string,
  action: string,
  positionSize: number,   // Target position size
  product: string,
  priceType: string,
  price?: number,
  triggerPrice?: number,
  strategy?: string
}) -> Promise<OrderResponse>
```

### 3.3 `modify_order`

Modify an existing order.

```typescript
invoke('modify_order', {
  orderId: string,
  quantity?: number,
  price?: number,
  triggerPrice?: number,
  priceType?: string
}) -> Promise<OrderResponse>
```

### 3.4 `cancel_order`

Cancel a pending order.

```typescript
invoke('cancel_order', {
  orderId: string
}) -> Promise<CancelResponse>
```

**Response:**
```typescript
interface CancelResponse {
  status: 'success' | 'error';
  orderId: string;
  message: string;
}
```

### 3.5 `cancel_all_orders`

Cancel all pending orders.

```typescript
invoke('cancel_all_orders', {
  strategy?: string  // Optional: only cancel orders from this strategy
}) -> Promise<BulkCancelResponse>
```

**Response:**
```typescript
interface BulkCancelResponse {
  status: 'success' | 'partial' | 'error';
  totalOrders: number;
  cancelledOrders: number;
  failedOrders: number;
  errors: Array<{ orderId: string; error: string }>;
}
```

### 3.6 `close_position`

Close an open position.

```typescript
invoke('close_position', {
  symbol: string,
  exchange: string,
  product: string
}) -> Promise<ClosePositionResponse>
```

**Response:**
```typescript
interface ClosePositionResponse {
  status: 'success' | 'error';
  orderId: string;
  quantity: number;
  message: string;
}
```

### 3.7 `close_all_positions`

Close all open positions.

```typescript
invoke('close_all_positions', {
  product?: string  // Optional: only close specific product type
}) -> Promise<BulkCloseResponse>
```

---

## 4. Portfolio Commands

### 4.1 `get_orderbook`

Get all orders for the day.

```typescript
invoke('get_orderbook') -> Promise<Order[]>
```

**Response:**
```typescript
interface Order {
  orderId: string;
  brokerOrderId: string;
  exchange: string;
  symbol: string;
  action: 'BUY' | 'SELL';
  quantity: number;
  filledQuantity: number;
  pendingQuantity: number;
  product: string;
  priceType: string;
  price: number;
  triggerPrice: number;
  averagePrice: number;
  status: OrderStatus;
  statusMessage: string | null;
  strategy: string | null;
  placedAt: string;
  updatedAt: string;
}

type OrderStatus =
  | 'PENDING'
  | 'OPEN'
  | 'COMPLETE'
  | 'CANCELLED'
  | 'REJECTED'
  | 'TRIGGER_PENDING';
```

### 4.2 `get_tradebook`

Get executed trades for the day.

```typescript
invoke('get_tradebook') -> Promise<Trade[]>
```

**Response:**
```typescript
interface Trade {
  tradeId: string;
  orderId: string;
  exchange: string;
  symbol: string;
  action: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  product: string;
  tradeTime: string;
}
```

### 4.3 `get_positions`

Get current open positions.

```typescript
invoke('get_positions') -> Promise<Position[]>
```

**Response:**
```typescript
interface Position {
  exchange: string;
  symbol: string;
  product: string;
  quantity: number;       // Net quantity (+ve long, -ve short)
  averagePrice: number;
  ltp: number;
  pnl: number;
  pnlPercent: number;
  dayBuyQty: number;
  daySellQty: number;
  dayBuyAvg: number;
  daySellAvg: number;
}
```

### 4.4 `get_holdings`

Get demat holdings.

```typescript
invoke('get_holdings') -> Promise<Holding[]>
```

**Response:**
```typescript
interface Holding {
  exchange: string;
  symbol: string;
  isin: string;
  quantity: number;
  t1Quantity: number;     // T+1 unsettled
  averagePrice: number;
  ltp: number;
  currentValue: number;
  pnl: number;
  pnlPercent: number;
}
```

### 4.5 `get_funds`

Get account funds and margins.

```typescript
invoke('get_funds') -> Promise<Funds>
```

**Response:**
```typescript
interface Funds {
  availableBalance: number;
  usedMargin: number;
  totalBalance: number;
  availableMargin: number;
  collateral: number;
  payin: number;
  payout: number;
}
```

---

## 5. Market Data Commands

### 5.1 `get_quotes`

Get real-time quote for a symbol.

```typescript
invoke('get_quotes', {
  symbol: string,
  exchange: string
}) -> Promise<Quote>
```

**Response:**
```typescript
interface Quote {
  symbol: string;
  exchange: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  bid: number;
  ask: number;
  bidQty: number;
  askQty: number;
  oi?: number;           // Open interest (F&O)
  change: number;
  changePercent: number;
  timestamp: string;
}
```

### 5.2 `get_depth`

Get market depth (order book).

```typescript
invoke('get_depth', {
  symbol: string,
  exchange: string
}) -> Promise<Depth>
```

**Response:**
```typescript
interface Depth {
  symbol: string;
  exchange: string;
  bids: DepthLevel[];    // Array of 5 levels
  asks: DepthLevel[];    // Array of 5 levels
  totalBidQty: number;
  totalAskQty: number;
  timestamp: string;
}

interface DepthLevel {
  price: number;
  quantity: number;
  orders: number;
}
```

### 5.3 `get_history`

Get historical OHLC data.

```typescript
invoke('get_history', {
  symbol: string,
  exchange: string,
  interval: string,      // 1m, 5m, 15m, 30m, 1h, 1d
  startDate: string,     // YYYY-MM-DD
  endDate: string        // YYYY-MM-DD
}) -> Promise<Candle[]>
```

**Response:**
```typescript
interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  oi?: number;
}
```

### 5.4 `search_symbols`

Search for symbols.

```typescript
invoke('search_symbols', {
  query: string,
  exchange?: string,     // Optional filter
  limit?: number         // Default 20
}) -> Promise<SymbolInfo[]>
```

**Response:**
```typescript
interface SymbolInfo {
  symbol: string;
  exchange: string;
  token: string;
  name: string;
  instrumentType: string;  // EQ, FUT, CE, PE
  lotSize: number;
  tickSize: number;
  expiry?: string;
  strike?: number;
}
```

### 5.5 `subscribe_quotes`

Subscribe to real-time quote updates.

```typescript
invoke('subscribe_quotes', {
  symbols: Array<{
    symbol: string;
    exchange: string;
    mode: 'LTP' | 'QUOTE' | 'DEPTH'
  }>
}) -> Promise<void>
```

**Events emitted:**
```typescript
// Listen for quote updates
import { listen } from '@tauri-apps/api/event';

await listen('quote:NSE:RELIANCE', (event) => {
  const quote: Quote = event.payload;
  console.log('Quote update:', quote);
});
```

### 5.6 `unsubscribe_quotes`

Unsubscribe from quote updates.

```typescript
invoke('unsubscribe_quotes', {
  symbols: Array<{ symbol: string; exchange: string }>
}) -> Promise<void>
```

---

## 6. Options Commands

### 6.1 `get_option_chain`

Get options chain data.

```typescript
invoke('get_option_chain', {
  symbol: string,        // Underlying: NIFTY, BANKNIFTY, RELIANCE
  expiry: string         // YYYY-MM-DD
}) -> Promise<OptionChain>
```

**Response:**
```typescript
interface OptionChain {
  underlying: string;
  spotPrice: number;
  expiry: string;
  strikes: OptionStrike[];
}

interface OptionStrike {
  strikePrice: number;
  call: OptionData | null;
  put: OptionData | null;
}

interface OptionData {
  symbol: string;
  token: string;
  ltp: number;
  bid: number;
  ask: number;
  volume: number;
  oi: number;
  oiChange: number;
  iv: number;            // Implied Volatility
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}
```

### 6.2 `get_option_greeks`

Calculate option Greeks for a specific option.

```typescript
invoke('get_option_greeks', {
  symbol: string,
  exchange: string,
  spotPrice?: number,    // Optional: auto-fetch if not provided
  interestRate?: number  // Default: 0.1 (10%)
}) -> Promise<OptionGreeks>
```

**Response:**
```typescript
interface OptionGreeks {
  symbol: string;
  optionType: 'CE' | 'PE';
  strikePrice: number;
  spotPrice: number;
  ltp: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
  timeToExpiry: number;  // Days
  intrinsicValue: number;
  timeValue: number;
}
```

### 6.3 `get_expiries`

Get available expiry dates.

```typescript
invoke('get_expiries', {
  symbol: string,
  exchange: string
}) -> Promise<string[]>   // Array of YYYY-MM-DD dates
```

---

## 7. Strategy Commands

### 7.1 `get_strategies`

List all strategies.

```typescript
invoke('get_strategies') -> Promise<Strategy[]>
```

**Response:**
```typescript
interface Strategy {
  id: number;
  name: string;
  description: string;
  webhookId: string;
  isActive: boolean;
  symbols: StrategySymbol[];
  createdAt: string;
  updatedAt: string;
}

interface StrategySymbol {
  symbol: string;
  exchange: string;
  quantity: number;
  product: string;
}
```

### 7.2 `create_strategy`

Create a new strategy.

```typescript
invoke('create_strategy', {
  name: string,
  description?: string,
  symbols: Array<{
    symbol: string;
    exchange: string;
    quantity: number;
    product: string;
  }>
}) -> Promise<Strategy>
```

### 7.3 `update_strategy`

Update an existing strategy.

```typescript
invoke('update_strategy', {
  id: number,
  name?: string,
  description?: string,
  isActive?: boolean,
  symbols?: Array<{
    symbol: string;
    exchange: string;
    quantity: number;
    product: string;
  }>
}) -> Promise<Strategy>
```

### 7.4 `delete_strategy`

Delete a strategy.

```typescript
invoke('delete_strategy', {
  id: number
}) -> Promise<void>
```

### 7.5 `get_webhook_url`

Get webhook URL for external integrations.

```typescript
invoke('get_webhook_url', {
  strategyId: number
}) -> Promise<string>
```

---

## 8. Settings Commands

### 8.1 `get_settings`

Get all application settings.

```typescript
invoke('get_settings') -> Promise<Record<string, any>>
```

### 8.2 `update_settings`

Update settings.

```typescript
invoke('update_settings', {
  settings: Record<string, any>
}) -> Promise<void>
```

### 8.3 `get_api_key`

Get/generate API key.

```typescript
invoke('get_api_key') -> Promise<{ apiKey: string; createdAt: string }>
```

### 8.4 `regenerate_api_key`

Generate new API key (invalidates old one).

```typescript
invoke('regenerate_api_key') -> Promise<{ apiKey: string; createdAt: string }>
```

### 8.5 `get_order_mode`

Get current order mode.

```typescript
invoke('get_order_mode') -> Promise<'auto' | 'semi_auto'>
```

### 8.6 `set_order_mode`

Set order execution mode.

```typescript
invoke('set_order_mode', {
  mode: 'auto' | 'semi_auto'
}) -> Promise<void>
```

---

## 9. Action Center Commands (Semi-Auto Mode)

### 9.1 `get_pending_orders`

Get orders awaiting approval.

```typescript
invoke('get_pending_orders') -> Promise<PendingOrder[]>
```

**Response:**
```typescript
interface PendingOrder {
  id: number;
  strategy: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  product: string;
  priceType: string;
  price: number;
  triggerPrice: number;
  positionSize?: number;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  expiresAt: string;
  createdAt: string;
}
```

### 9.2 `approve_order`

Approve a pending order.

```typescript
invoke('approve_order', {
  pendingOrderId: number
}) -> Promise<OrderResponse>
```

### 9.3 `reject_order`

Reject a pending order.

```typescript
invoke('reject_order', {
  pendingOrderId: number,
  reason?: string
}) -> Promise<void>
```

### 9.4 `approve_all_orders`

Approve all pending orders.

```typescript
invoke('approve_all_orders') -> Promise<BulkApprovalResponse>
```

---

## 10. Event Reference

### 10.1 Event Types

```typescript
// Order events
'order:placed'     -> { orderId, symbol, action, quantity, status }
'order:updated'    -> { orderId, status, filledQty, avgPrice }
'order:cancelled'  -> { orderId }
'order:rejected'   -> { orderId, reason }

// Position events
'position:updated' -> { symbol, exchange, quantity, pnl }
'position:closed'  -> { symbol, exchange }

// Quote events
'quote:{exchange}:{symbol}' -> Quote

// Connection events
'broker:connected'    -> { broker, clientId }
'broker:disconnected' -> { broker, reason }
'broker:error'        -> { broker, error }

// WebSocket events
'ws:connected'     -> { }
'ws:disconnected'  -> { reason }
'ws:reconnecting'  -> { attempt }

// System events
'error:global'     -> { code, message }
'notification'     -> { type, title, message }
```

### 10.2 Listening to Events

```typescript
import { listen } from '@tauri-apps/api/event';

// Listen to order updates
const unlisten = await listen('order:updated', (event) => {
  console.log('Order updated:', event.payload);
});

// Clean up listener
unlisten();
```

---

## 11. Error Codes

| Code | Description |
|------|-------------|
| `NOT_AUTHENTICATED` | User not logged in |
| `SESSION_EXPIRED` | Session has expired |
| `BROKER_NOT_CONNECTED` | No broker connected |
| `BROKER_API_ERROR` | Error from broker API |
| `VALIDATION_ERROR` | Invalid request parameters |
| `ORDER_ERROR` | Order placement failed |
| `SYMBOL_NOT_FOUND` | Invalid symbol |
| `MARKET_CLOSED` | Market is closed |
| `INSUFFICIENT_FUNDS` | Not enough margin |
| `RATE_LIMITED` | Too many requests |
| `NETWORK_ERROR` | Network connectivity issue |
| `INTERNAL_ERROR` | Internal server error |

---

## Document References

- [00-PRODUCT-DESIGN.md](./00-PRODUCT-DESIGN.md) - Product overview
- [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) - System architecture
- [02-DATABASE.md](./02-DATABASE.md) - Database schema
- [04-FRONTEND.md](./04-FRONTEND.md) - Frontend design
- [05-BROKER-INTEGRATION.md](./05-BROKER-INTEGRATION.md) - Broker patterns
- [06-ROADMAP.md](./06-ROADMAP.md) - Implementation plan

---

*Last updated: December 2024*
