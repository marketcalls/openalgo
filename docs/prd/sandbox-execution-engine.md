# Sandbox Execution Engine

Complete documentation for the Sandbox order execution engine with WebSocket and polling modes.

## Overview

The execution engine matches pending orders against real-time market prices. Two execution modes are available:

| Mode | Performance | Requirement |
|------|-------------|-------------|
| WebSocket | Real-time (~50ms latency) | WebSocket proxy running |
| Polling | 2-second intervals | Broker API access |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Execution Thread Controller                           │
│                    sandbox/execution_thread.py                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  start_execution_engine(engine_type='websocket')                  │  │
│  │      │                                                             │  │
│  │      ├──▶ Check WebSocket proxy health                            │  │
│  │      │         │                                                   │  │
│  │      │         ├──▶ Healthy → Start WebSocket Engine              │  │
│  │      │         │                                                   │  │
│  │      │         └──▶ Unhealthy → Fallback to Polling Engine        │  │
│  │      │                                                             │  │
│  │      └──▶ engine_type='polling' → Start Polling Engine            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
┌───────────────────────────┐     ┌───────────────────────────┐
│   WebSocket Engine        │     │   Polling Engine          │
│   (Primary)               │     │   (Fallback)              │
│                           │     │                           │
│ • Subscribe to LTP stream │     │ • Poll every 2 seconds    │
│ • Instant order matching  │     │ • Fetch LTP from broker   │
│ • Event-driven execution  │     │ • Sequential matching     │
└───────────────────────────┘     └───────────────────────────┘
```

## WebSocket Execution Engine

Located in `sandbox/websocket_execution_engine.py`.

### Initialization

```python
def start_websocket_execution_engine():
    """Start WebSocket-based execution engine"""
    global _execution_engine

    if not _is_websocket_proxy_healthy():
        return False, "WebSocket proxy not available"

    _execution_engine = WebSocketExecutionEngine()
    _execution_engine.start()

    return True, "WebSocket execution engine started"
```

### Order Matching Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  WebSocket Message Handler                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Receive LTP Update: {symbol: "SBIN", ltp: 625.50}           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Find matching pending orders for symbol                      │
│     SELECT * FROM sandbox_orders                                 │
│     WHERE symbol = 'SBIN' AND status IN ('PENDING', 'TRIGGER')  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. For each order, check execution conditions                   │
│     • MARKET: Execute immediately at LTP                         │
│     • LIMIT BUY: Execute if LTP <= limit_price                  │
│     • LIMIT SELL: Execute if LTP >= limit_price                 │
│     • SL BUY: Trigger if LTP >= trigger_price                   │
│     • SL SELL: Trigger if LTP <= trigger_price                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Execute matched order                                        │
│     • Update order status to COMPLETE                            │
│     • Create trade record                                        │
│     • Update position (netting)                                  │
│     • Update funds (P&L booking)                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Symbol Subscription

```python
def _subscribe_pending_symbols(self):
    """Subscribe to WebSocket for all symbols with pending orders"""
    pending_symbols = self._get_pending_order_symbols()

    for symbol, exchange in pending_symbols:
        self._websocket_client.subscribe(
            symbol=symbol,
            exchange=exchange,
            mode='ltp'
        )
```

## Polling Execution Engine

Located in `sandbox/polling_execution_engine.py`.

### Poll Loop

```python
def _poll_loop(self):
    """Main polling loop - runs every 2 seconds"""
    while self._running:
        try:
            # Get all pending orders
            pending_orders = self._get_pending_orders()

            # Group by symbol for batch price fetch
            symbols = set((o.symbol, o.exchange) for o in pending_orders)

            # Fetch current prices
            prices = self._fetch_prices(symbols)

            # Match orders against prices
            for order in pending_orders:
                ltp = prices.get((order.symbol, order.exchange))
                if ltp:
                    self._try_execute_order(order, ltp)

        except Exception as e:
            logger.error(f"Polling error: {e}")

        time.sleep(2)  # Poll interval
```

## Order Execution Logic

### Price Type Matching

| Price Type | BUY Condition | SELL Condition |
|------------|---------------|----------------|
| MARKET | Execute at LTP | Execute at LTP |
| LIMIT | LTP <= limit_price | LTP >= limit_price |
| SL | LTP >= trigger_price → MARKET | LTP <= trigger_price → MARKET |
| SL-M | LTP >= trigger_price → MARKET | LTP <= trigger_price → MARKET |

### Execution Function

```python
def execute_order(order, execution_price):
    """Execute order at given price"""
    with db_lock:
        # Update order
        order.status = 'COMPLETE'
        order.filled_quantity = order.quantity
        order.average_price = execution_price
        order.exchange_timestamp = datetime.now()

        # Create trade record
        trade = SandboxTrades(
            order_id=order.order_id,
            trade_id=generate_trade_id(),
            symbol=order.symbol,
            exchange=order.exchange,
            action=order.action,
            quantity=order.quantity,
            price=execution_price,
            trade_timestamp=datetime.now()
        )

        # Update position
        position_manager.update_position(
            symbol=order.symbol,
            exchange=order.exchange,
            product=order.product,
            action=order.action,
            quantity=order.quantity,
            price=execution_price
        )

        db.session.add(trade)
        db.session.commit()
```

## Square-Off Manager

Handles automatic position closure at exchange timings.

### Exchange Timings

| Exchange | Product | Square-Off Time |
|----------|---------|-----------------|
| NSE | MIS | 15:15 IST |
| NFO | MIS | 15:15 IST |
| BSE | MIS | 15:15 IST |
| MCX | MIS | 23:30 IST |
| CDS | MIS | 17:00 IST |

### Square-Off Logic

```python
def auto_square_off():
    """Called by scheduler at exchange timings"""
    current_time = datetime.now(IST)

    # Determine which exchanges to square off
    exchanges_to_close = []

    if current_time.hour == 15 and current_time.minute >= 15:
        exchanges_to_close.extend(['NSE', 'NFO', 'BSE'])

    if current_time.hour == 23 and current_time.minute >= 30:
        exchanges_to_close.append('MCX')

    # Close all MIS positions for these exchanges
    for exchange in exchanges_to_close:
        positions = SandboxPositions.query.filter(
            SandboxPositions.exchange == exchange,
            SandboxPositions.product == 'MIS',
            SandboxPositions.quantity != 0
        ).all()

        for position in positions:
            close_position(position)
```

## Settlement Jobs

### T+1 Settlement (Midnight)

```python
@scheduler.scheduled_job('cron', hour=0, minute=1, timezone=IST)
def t1_settlement():
    """Convert CNC positions to holdings"""
    # Get all CNC positions from previous day
    positions = SandboxPositions.query.filter(
        SandboxPositions.product == 'CNC',
        SandboxPositions.quantity != 0
    ).all()

    for position in positions:
        # Create/update holding
        holding = SandboxHoldings.query.filter_by(
            symbol=position.symbol,
            exchange=position.exchange
        ).first()

        if holding:
            # Average down/up existing holding
            new_qty = holding.quantity + position.quantity
            new_avg = (holding.quantity * holding.average_price +
                       position.quantity * position.average_price) / new_qty
            holding.quantity = new_qty
            holding.average_price = new_avg
        else:
            # Create new holding
            holding = SandboxHoldings(
                symbol=position.symbol,
                exchange=position.exchange,
                quantity=position.quantity,
                average_price=position.average_price
            )
            db.session.add(holding)

        # Clear position
        position.quantity = 0
```

### Expired Contract Cleanup

```python
@scheduler.scheduled_job('cron', hour=0, minute=5, timezone=IST)
def cleanup_expired_contracts():
    """Remove expired F&O contracts"""
    today = date.today()

    # Find expired positions
    expired = SandboxPositions.query.filter(
        SandboxPositions.exchange.in_(['NFO', 'MCX', 'CDS']),
        SandboxPositions.quantity != 0
    ).all()

    for position in expired:
        expiry = get_contract_expiry(position.symbol)
        if expiry and today > expiry:
            # Auto-close at last traded price
            close_expired_position(position)
```

## Performance Metrics

| Metric | WebSocket Engine | Polling Engine |
|--------|-----------------|----------------|
| Order matching latency | ~50ms | ~2000ms |
| Price staleness | Real-time | Up to 2 seconds |
| CPU usage | Low (event-driven) | Higher (continuous polling) |
| Network requests | WebSocket subscription | 1 request/symbol/2sec |

## Error Handling

### Connection Loss

```python
def _on_websocket_disconnect(self):
    """Handle WebSocket disconnection"""
    logger.warning("WebSocket disconnected, attempting reconnect...")

    # Retry with backoff
    for attempt in range(5):
        time.sleep(2 ** attempt)
        if self._reconnect():
            logger.info("Reconnected successfully")
            return

    # Fallback to polling
    logger.warning("Falling back to polling engine")
    start_polling_execution_engine()
```

### Database Locks

```python
# Use threading lock for concurrent order updates
_db_lock = threading.Lock()

def execute_order(order, price):
    with _db_lock:
        # All database operations within lock
        ...
```

## Configuration

Environment variables for execution engine:

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_ENGINE_TYPE` | `websocket` | Engine type: `websocket` or `polling` |
| `SANDBOX_POLL_INTERVAL` | `2` | Polling interval in seconds |
| `SANDBOX_WS_RECONNECT_ATTEMPTS` | `5` | WebSocket reconnection attempts |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Sandbox Architecture](./sandbox-architecture.md) | System architecture |
| [Margin System](./sandbox-margin-system.md) | Margin calculations |
| [WebSocket Proxy](./websocket-proxy.md) | WebSocket server details |
