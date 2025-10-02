# Order Management in Sandbox Mode

## Overview

The sandbox order management system simulates realistic order placement, execution, modification, and cancellation using real-time market data. All order types supported by live trading are available in sandbox mode.

## Order Types

### 1. MARKET Orders

**Description**: Execute immediately at the current market price

**Execution Logic**:
- **BUY**: Executes at ask price (or LTP if ask is 0)
- **SELL**: Executes at bid price (or LTP if bid is 0)
- Execution is immediate (not pending)

**Example**:
```python
order_data = {
    "apikey": "your_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
}
```

**Execution Flow**:
```
Place MARKET Order
    ↓
Validate Symbol & Quantity
    ↓
Calculate Margin (using current LTP)
    ↓
Check Available Funds
    ↓
Block Margin
    ↓
Create Order (status: open)
    ↓
IMMEDIATELY Execute at Bid/Ask
    ↓
Create Trade
    ↓
Update Position
    ↓
Order Status: complete
```

### 2. LIMIT Orders

**Description**: Execute only when market price reaches or crosses the limit price

**Execution Logic**:
- **BUY LIMIT**: Executes when LTP ≤ Limit Price
- **SELL LIMIT**: Executes when LTP ≥ Limit Price
- Execution happens at LTP (not limit price) for realism
- Order remains pending until triggered

**Example**:
```python
order_data = {
    "apikey": "your_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "price": 590.50,  # Limit price
    "pricetype": "LIMIT",
    "product": "MIS"
}
```

**Execution Flow**:
```
Place LIMIT Order
    ↓
Validate Symbol & Quantity
    ↓
Calculate Margin (using limit price)
    ↓
Check Available Funds
    ↓
Block Margin
    ↓
Create Order (status: open)
    ↓
Wait for Execution Engine
    ↓
Check every 5 seconds: Is LTP ≤ 590.50?
    ↓
YES → Execute at current LTP
    ↓
Create Trade & Update Position
```

### 3. SL (Stop-Loss) Orders

**Description**: Limit order that activates only when trigger price is hit

**Execution Logic**:
- **BUY SL**: Triggers when LTP ≥ Trigger Price, executes if LTP ≤ Limit Price
- **SELL SL**: Triggers when LTP ≤ Trigger Price, executes if LTP ≥ Limit Price
- Two-step process: trigger then limit check

**Example**:
```python
order_data = {
    "apikey": "your_api_key",
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 25,
    "price": 1450.00,        # Limit price
    "trigger_price": 1455.00, # Trigger price
    "pricetype": "SL",
    "product": "MIS"
}
```

**Execution Flow**:
```
Place SL Order
    ↓
Calculate Margin (using trigger price)
    ↓
Block Margin
    ↓
Create Order (status: open)
    ↓
Wait for Trigger: LTP ≤ 1455?
    ↓
TRIGGERED → Check Limit: LTP ≥ 1450?
    ↓
YES → Execute at current LTP
```

### 4. SL-M (Stop-Loss Market) Orders

**Description**: Market order that activates when trigger price is hit

**Execution Logic**:
- **BUY SL-M**: Triggers when LTP ≥ Trigger Price, executes at market
- **SELL SL-M**: Triggers when LTP ≤ Trigger Price, executes at market
- One-step: trigger then immediate market execution

**Example**:
```python
order_data = {
    "apikey": "your_api_key",
    "symbol": "TCS",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 15,
    "trigger_price": 3500.00,
    "pricetype": "SL-M",
    "product": "MIS"
}
```

**Execution Flow**:
```
Place SL-M Order
    ↓
Calculate Margin (using trigger price)
    ↓
Block Margin
    ↓
Create Order (status: open)
    ↓
Wait for Trigger: LTP ≥ 3500?
    ↓
TRIGGERED → Execute immediately at LTP
```

## Product Types

### MIS (Margin Intraday Square-off)

**Characteristics**:
- Higher leverage (5x for equity)
- Must be squared off same day
- Auto square-off at configured times
- Orders blocked after square-off time until 9 AM next day

**Square-off Times** (IST):
- NSE/BSE: 15:15
- CDS/BCD: 16:45
- MCX: 23:30
- NCDEX: 17:00

**Post Square-off Behavior**:
```python
# After 15:15, trying to place new MIS order:
{
    "status": "error",
    "message": "MIS orders cannot be placed after square-off time (15:15 IST). Trading resumes at 09:00 AM IST."
}

# Exception: Closing existing positions is allowed
```

### NRML (Normal)

**Characteristics**:
- Lower leverage (1x for equity)
- Can be held overnight
- No auto square-off
- Higher margin requirements

### CNC (Cash & Carry)

**Characteristics**:
- No leverage (1x)
- Delivery-based trading
- T+1 settlement to holdings (midnight 00:00 IST)
- SELL requires existing shares

## Order Lifecycle

### Order States

```
┌──────────┐
│   open   │ → Order placed, waiting for execution
└──────────┘
     │
     ├─→ ┌──────────┐
     │   │ complete │ → Order fully executed
     │   └──────────┘
     │
     ├─→ ┌───────────┐
     │   │ cancelled │ → User cancelled order
     │   └───────────┘
     │
     └─→ ┌──────────┐
         │ rejected │ → Order validation failed
         └──────────┘
```

### State Transitions

**Open → Complete**:
- Execution engine checks pending orders every 5 seconds
- Price conditions met
- Order executed at LTP
- Trade created
- Position updated

**Open → Cancelled**:
- User calls cancel order API
- Margin released
- Order marked cancelled
- No trade created

**Open → Rejected**:
- Execution error occurred
- Invalid conditions
- System error

## Margin Blocking

### When is Margin Blocked?

**At Order Placement Time**:
```python
# For ALL order types (MARKET, LIMIT, SL, SL-M)
margin_required = calculate_margin(order_data)
if available_balance >= margin_required:
    block_margin(margin_required)
    create_order(status='open')
else:
    reject_order("Insufficient funds")
```

### Price Used for Margin Calculation

**File**: `sandbox/order_manager.py` (lines 209-239)

```python
if price_type == 'MARKET':
    # Use current LTP from quote
    margin_price = quote['ltp']

elif price_type == 'LIMIT':
    # Use order's limit price
    margin_price = order['price']

elif price_type in ['SL', 'SL-M']:
    # Use trigger price
    margin_price = order['trigger_price']
```

### Margin Release

**On Order Cancellation**:
```python
# Full margin released
released_margin = order.margin_blocked
available_balance += released_margin
used_margin -= released_margin
```

**On Order Execution (Position Reduction)**:
```python
# If closing/reducing position, release proportional margin
if is_reducing_position:
    margin_to_release = calculate_position_margin(closed_quantity)
    available_balance += margin_to_release
    used_margin -= margin_to_release
```

## Order Validation

### Symbol Validation

```python
from database.symbol import SymToken

symbol_obj = SymToken.query.filter_by(
    symbol=symbol,
    exchange=exchange
).first()

if not symbol_obj:
    return reject_order("Symbol not found")
```

### Lot Size Validation

```python
# For F&O instruments
if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
    lot_size = symbol_obj.lotsize

    if quantity % lot_size != 0:
        return reject_order(
            f"Quantity must be in multiples of lot size {lot_size}"
        )
```

### CNC SELL Validation

```python
# CNC SELL requires existing shares
if product == 'CNC' and action == 'SELL':
    # Check position quantity
    position_qty = get_position_quantity(symbol, exchange, 'CNC')

    # Check holdings quantity
    holdings_qty = get_holdings_quantity(symbol, exchange)

    total_available = position_qty + holdings_qty

    if quantity > total_available:
        return reject_order(
            f"Cannot sell {quantity} shares. Only {total_available} available"
        )
```

### MIS Post-Squareoff Validation

**File**: `sandbox/order_manager.py` (lines 115-167)

```python
if product == 'MIS':
    square_off_time = get_square_off_time(exchange)
    market_open_time = time(9, 0)
    current_time = datetime.now(IST).time()

    # Block if after square-off OR before market open
    is_blocked = False
    if current_time >= square_off_time:
        is_blocked = True
    elif current_time < market_open_time:
        is_blocked = True

    if is_blocked:
        # Check if order reduces existing position
        existing_position = get_open_position(symbol, exchange, 'MIS')

        is_reducing = False
        if existing_position:
            if action == 'BUY' and existing_position.quantity < 0:
                is_reducing = True  # Covering short
            elif action == 'SELL' and existing_position.quantity > 0:
                is_reducing = True  # Closing long

        # Block only if opening/increasing position
        if not is_reducing:
            return reject_order(
                f"MIS orders cannot be placed after square-off time ({square_off_time}). "
                f"Trading resumes at 09:00 AM IST."
            )
```

## Order Modification

### Modifiable Fields

- **Quantity**: Can be increased or decreased
- **Price**: Can be changed for LIMIT orders
- **Trigger Price**: Can be changed for SL/SL-M orders

### Modification Example

```python
# Modify order quantity
modify_data = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-101530-abc123",
    "quantity": 20  # Changed from 10 to 20
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/modifyorder",
    json=modify_data
)
```

### Modification Logic

**File**: `sandbox/order_manager.py` (lines 540-618)

```python
def modify_order(orderid, new_data):
    # Get existing order
    order = get_order(orderid)

    if order.order_status != 'open':
        return error("Only pending orders can be modified")

    # Calculate margin adjustment
    old_margin = order.margin_blocked
    new_margin = calculate_margin(new_data)
    margin_diff = new_margin - old_margin

    if margin_diff > 0:
        # Additional margin needed
        if available_balance >= margin_diff:
            block_margin(margin_diff)
        else:
            return error("Insufficient funds for modification")
    else:
        # Margin released
        release_margin(abs(margin_diff))

    # Update order
    order.quantity = new_data.get('quantity', order.quantity)
    order.price = new_data.get('price', order.price)
    order.trigger_price = new_data.get('trigger_price', order.trigger_price)
    order.margin_blocked = new_margin

    return success("Order modified successfully")
```

## Order Cancellation

### Cancel Single Order

```python
cancel_data = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-101530-abc123"
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/cancelorder",
    json=cancel_data
)
```

### Cancel All Orders

```python
cancel_all_data = {
    "apikey": "your_api_key"
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/cancelallorder",
    json=cancel_all_data
)
```

### Cancellation Logic

**File**: `sandbox/order_manager.py` (lines 477-537)

```python
def cancel_order(orderid):
    order = get_order(orderid)

    if order.order_status != 'open':
        return error("Only pending orders can be cancelled")

    # Release blocked margin
    if order.margin_blocked > 0:
        release_margin(order.margin_blocked)
        logger.info(f"Released margin ₹{order.margin_blocked}")

    # Update order status
    order.order_status = 'cancelled'
    order.update_timestamp = datetime.now(IST)

    return success("Order cancelled successfully")
```

## Execution Engine

### Background Thread

**File**: `sandbox/execution_thread.py`

```python
class ExecutionEngineThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.check_interval = int(get_config('order_check_interval', '5'))

    def run(self):
        while not self.stop_event.is_set():
            try:
                engine = ExecutionEngine()
                engine.check_and_execute_pending_orders()
            except Exception as e:
                logger.error(f"Error in execution engine: {e}")

            time.sleep(self.check_interval)
```

### Order Checking Logic

**File**: `sandbox/execution_engine.py` (lines 45-100)

```python
def check_and_execute_pending_orders():
    # Get all pending orders
    pending_orders = SandboxOrders.query.filter_by(
        order_status='open'
    ).all()

    if not pending_orders:
        return

    # Group by symbol for efficient quote fetching
    orders_by_symbol = group_by_symbol(pending_orders)

    # Fetch quotes in batches (respect API rate limit)
    quote_cache = fetch_quotes_batch(orders_by_symbol.keys())

    # Process orders in batches (respect order rate limit)
    for order in pending_orders:
        quote = quote_cache.get((order.symbol, order.exchange))
        if quote:
            process_order(order, quote)
```

### Execution Decision Logic

**File**: `sandbox/execution_engine.py` (lines 138-203)

```python
def should_execute(order, quote):
    ltp = quote['ltp']
    bid = quote['bid']
    ask = quote['ask']

    if order.price_type == 'MARKET':
        # Already executed at placement
        return False

    elif order.price_type == 'LIMIT':
        if order.action == 'BUY' and ltp <= order.price:
            return True, ltp
        elif order.action == 'SELL' and ltp >= order.price:
            return True, ltp

    elif order.price_type == 'SL':
        # Check trigger first
        if order.action == 'BUY' and ltp >= order.trigger_price:
            # Check limit
            if ltp <= order.price:
                return True, ltp
        elif order.action == 'SELL' and ltp <= order.trigger_price:
            if ltp >= order.price:
                return True, ltp

    elif order.price_type == 'SL-M':
        if order.action == 'BUY' and ltp >= order.trigger_price:
            return True, ltp
        elif order.action == 'SELL' and ltp <= order.trigger_price:
            return True, ltp

    return False, None
```

## Rate Limiting

### Order Rate Limit

**Config**: `order_rate_limit` = 10 orders/second

```python
# Batch processing to respect rate limit
MAX_ORDERS_PER_BATCH = 10
BATCH_DELAY = 1.0  # 1 second

for i in range(0, len(pending_orders), MAX_ORDERS_PER_BATCH):
    batch = pending_orders[i:i + MAX_ORDERS_PER_BATCH]

    for order in batch:
        process_order(order)

    if more_orders_remaining:
        time.sleep(BATCH_DELAY)
```

### API Rate Limit

**Config**: `api_rate_limit` = 50 API calls/second

```python
# Quote fetching in batches
MAX_API_CALLS = 50
BATCH_DELAY = 1.0

for i in range(0, len(symbols), MAX_API_CALLS):
    batch = symbols[i:i + MAX_API_CALLS]

    for symbol in batch:
        fetch_quote(symbol)

    if more_symbols_remaining:
        time.sleep(BATCH_DELAY)
```

## Orderbook Format

### Get Orderbook

```python
payload = {"apikey": "your_api_key"}
response = requests.post(
    "http://127.0.0.1:5000/api/v1/orderbook",
    json=payload
)
```

### Response Format

```json
{
    "status": "success",
    "data": {
        "orders": [
            {
                "orderid": "SB-20251002-101530-abc123",
                "strategy": "Test Strategy",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 10,
                "filled_quantity": 10,
                "pending_quantity": 0,
                "price": null,
                "trigger_price": null,
                "price_type": "MARKET",
                "product": "MIS",
                "order_status": "complete",
                "average_price": 2892.50,
                "order_timestamp": "2025-10-02 10:15:30",
                "update_timestamp": "2025-10-02 10:15:30"
            }
        ]
    },
    "mode": "analyze"
}
```

## Order Status

### Get Order Status

```python
payload = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-101530-abc123"
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/orderstatus",
    json=payload
)
```

## Best Practices

### 1. Use Appropriate Order Types

- **MARKET**: When immediate execution is critical
- **LIMIT**: When you have a target entry/exit price
- **SL**: For stop-loss protection with price limit
- **SL-M**: For guaranteed stop-loss execution

### 2. Monitor Pending Orders

Check orderbook regularly for pending LIMIT/SL orders:
```python
# Get pending orders
orders = get_orderbook()
pending = [o for o in orders if o['order_status'] == 'open']
```

### 3. Cancel Unused Orders

Cancel orders that are no longer needed:
```python
# Cancel specific order
cancel_order(orderid)

# Or cancel all at end of day
cancel_all_orders()
```

### 4. Understand MIS Restrictions

- Orders blocked after square-off time
- Auto square-off at configured times
- Higher leverage but intraday only

## Summary

The sandbox order management system provides:

1. **Complete Order Types**: MARKET, LIMIT, SL, SL-M
2. **Realistic Execution**: Bid/ask pricing, LTP-based triggers
3. **Accurate Margin**: Calculated at placement, adjusted on modification
4. **Proper Validation**: Symbol, lot size, funds, CNC SELL checks
5. **Lifecycle Management**: Place, modify, cancel, execute
6. **Auto Square-off**: MIS position closure
7. **Rate Limiting**: Compliant with broker limits

---

**Previous**: [Getting Started](02_getting_started.md) | **Next**: [Margin System](04_margin_system.md)
