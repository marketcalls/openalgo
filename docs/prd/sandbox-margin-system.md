# Sandbox Margin System

Complete documentation for margin calculation, blocking, and fund management in Sandbox mode.

## Overview

The Sandbox margin system replicates real exchange margin requirements with configurable leverage for paper trading.

## Fund Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                     Virtual Account                              │
├─────────────────────────────────────────────────────────────────┤
│  Starting Capital      │  ₹1,00,00,000 (1 Crore)               │
├─────────────────────────────────────────────────────────────────┤
│  Available Balance     │  Capital - Used Margin + Realized P&L │
│  Used Margin           │  Blocked for open positions           │
│  Realized P&L          │  Booked profit/loss from closed trades│
└─────────────────────────────────────────────────────────────────┘
```

## Margin Rules by Product

### Product Types

| Product | Full Form | Leverage | Use Case |
|---------|-----------|----------|----------|
| CNC | Cash and Carry | 1x | Delivery trades (T+1 settlement) |
| MIS | Margin Intraday Square-off | 5x | Intraday trades (auto square-off) |
| NRML | Normal | 1x | F&O overnight positions |

### Margin Calculation

```python
def calculate_margin(symbol, exchange, action, quantity, product, price):
    """Calculate required margin for order"""
    total_value = quantity * price

    if product == 'CNC':
        # Full value required for delivery
        margin = total_value

    elif product == 'MIS':
        # 20% margin (5x leverage) for intraday
        margin = total_value * 0.20

    elif product == 'NRML':
        # Full margin for F&O overnight
        if exchange in ['NFO', 'MCX', 'CDS', 'BFO']:
            margin = total_value
        else:
            margin = total_value

    return margin
```

## Margin Operations

### 1. Block Margin (Order Placement)

```python
def block_margin(amount, description=""):
    """Block margin when placing order"""
    with db_session() as session:
        funds = get_or_create_funds(user_id)

        if funds.available_balance < amount:
            raise InsufficientMarginError(
                f"Required: ₹{amount}, Available: ₹{funds.available_balance}"
            )

        funds.available_balance -= amount
        funds.used_margin += amount

        session.commit()
        return True
```

### 2. Release Margin (Order Cancel/Position Close)

```python
def release_margin(amount, description=""):
    """Release margin when closing position or canceling order"""
    with db_session() as session:
        funds = get_or_create_funds(user_id)

        funds.available_balance += amount
        funds.used_margin -= amount

        # Ensure used_margin doesn't go negative
        if funds.used_margin < 0:
            funds.used_margin = Decimal('0')

        session.commit()
        return True
```

### 3. Book P&L (Position Close)

```python
def book_pnl(pnl_amount, description=""):
    """Book realized P&L when closing position"""
    with db_session() as session:
        funds = get_or_create_funds(user_id)

        # P&L affects both available balance and realized P&L
        funds.available_balance += pnl_amount
        funds.realized_pnl += pnl_amount

        session.commit()
        return True
```

## Order Flow with Margin

### BUY Order Flow

```
┌─────────────────────────────────────────────────────────────┐
│  BUY 100 SBIN @ ₹620 (CNC)                                  │
│  Order Value: ₹62,000                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Calculate Margin                                         │
│     Product: CNC → 100% margin                               │
│     Required: ₹62,000                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Check Available Balance                                  │
│     Available: ₹1,00,00,000                                  │
│     Required: ₹62,000                                        │
│     ✓ Sufficient                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Block Margin                                             │
│     Available: ₹99,38,000 (↓62,000)                         │
│     Used: ₹62,000 (↑62,000)                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Create Order (PENDING)                                   │
│     Wait for execution...                                    │
└─────────────────────────────────────────────────────────────┘
```

### SELL Order Flow (Close Long Position)

```
┌─────────────────────────────────────────────────────────────┐
│  Current Position: LONG 100 SBIN @ ₹620                     │
│  Current LTP: ₹625                                           │
│  SELL 100 SBIN @ MARKET                                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Execute SELL at ₹625                                     │
│     Trade Value: ₹62,500                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Calculate P&L                                            │
│     Buy Avg: ₹620 × 100 = ₹62,000                           │
│     Sell: ₹625 × 100 = ₹62,500                              │
│     Profit: ₹500                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Release Margin + Book P&L                                │
│     Release margin: ₹62,000                                  │
│     Book profit: ₹500                                        │
│     Available: ₹99,38,000 + ₹62,000 + ₹500 = ₹1,00,00,500   │
│     Used: ₹62,000 - ₹62,000 = ₹0                            │
│     Realized P&L: ₹500                                       │
└─────────────────────────────────────────────────────────────┘
```

## MIS Leverage Example

```
┌─────────────────────────────────────────────────────────────┐
│  BUY 100 SBIN @ ₹620 (MIS - 5x leverage)                    │
│  Order Value: ₹62,000                                        │
│  Margin Required: ₹62,000 × 20% = ₹12,400                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Funds After Order:                                          │
│  Available: ₹1,00,00,000 - ₹12,400 = ₹99,87,600            │
│  Used Margin: ₹12,400                                        │
│                                                              │
│  Buying Power with 5x leverage: ₹99,87,600 × 5 = ₹4.99 Cr  │
└─────────────────────────────────────────────────────────────┘
```

## Holdings Settlement

When CNC positions convert to holdings (T+1):

```python
def transfer_margin_to_holdings(amount, description=""):
    """
    Transfer margin from used_margin to holdings.
    Money is now "locked" in shares, not available for trading.
    """
    with db_session() as session:
        funds = get_or_create_funds(user_id)

        # Release from used_margin (position closed)
        funds.used_margin -= amount

        # Do NOT credit to available_balance
        # Money is now in holdings

        session.commit()
```

### Selling from Holdings

```python
def credit_sale_proceeds(amount, description=""):
    """Credit proceeds from selling holdings back to available balance"""
    with db_session() as session:
        funds = get_or_create_funds(user_id)

        # Sale proceeds go to available balance
        funds.available_balance += amount

        session.commit()
```

## Margin Validation

### Pre-Order Checks

```python
def validate_margin_for_order(order):
    """Comprehensive margin validation before order placement"""

    # 1. Calculate required margin
    margin = calculate_margin(
        order.symbol, order.exchange, order.action,
        order.quantity, order.product, order.price or get_ltp(order.symbol)
    )

    # 2. Check for sell orders
    if order.action == 'SELL':
        if order.product == 'CNC':
            # Check holdings + position
            holdings = get_holdings(order.symbol)
            position = get_position(order.symbol)
            available_qty = (holdings.quantity if holdings else 0) + \
                           (position.quantity if position else 0)

            if order.quantity > available_qty:
                raise InsufficientQuantityError(
                    f"Available: {available_qty}, Requested: {order.quantity}"
                )

            # No margin needed for selling own holdings
            return True

        # For MIS/NRML short selling, margin is needed

    # 3. Check available balance
    funds = get_funds()
    if funds.available_balance < margin:
        raise InsufficientMarginError(
            f"Required: ₹{margin}, Available: ₹{funds.available_balance}"
        )

    return True
```

## API Endpoints

### Get Funds

```
GET /api/v1/funds

Response:
{
    "status": "success",
    "data": {
        "availablecash": 9938000.00,
        "collateral": 0.00,
        "m2mrealized": 500.00,
        "m2munrealized": 250.00,
        "utiliseddebits": 62000.00
    }
}
```

### Reset Funds (Sandbox Only)

```
POST /analyzer/reset-funds

Response:
{
    "status": "success",
    "message": "Funds reset to ₹1,00,00,000"
}
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SANDBOX_INITIAL_CAPITAL` | `10000000` | Starting capital (₹1 Cr) |
| `SANDBOX_MIS_LEVERAGE` | `5` | MIS leverage multiplier |
| `SANDBOX_CNC_LEVERAGE` | `1` | CNC leverage (no leverage) |
| `SANDBOX_NRML_LEVERAGE` | `1` | NRML leverage (no leverage) |

## Error Codes

| Code | Message | Resolution |
|------|---------|------------|
| `INSUFFICIENT_MARGIN` | Insufficient margin for order | Reduce quantity or add funds |
| `INSUFFICIENT_HOLDINGS` | Cannot sell more than holdings | Check available quantity |
| `MARGIN_BLOCKED` | Margin already blocked | Wait for previous order |
| `INVALID_PRODUCT` | Unknown product type | Use CNC, MIS, or NRML |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Sandbox Architecture](./sandbox-architecture.md) | System overview |
| [Execution Engine](./sandbox-execution-engine.md) | Order execution |
| [Sandbox PRD](./sandbox.md) | Product requirements |
