# Sandbox Margin System - Complete Guide

## Overview

The Sandbox Mode margin system accurately simulates real-world margin blocking and release mechanics. This document provides a comprehensive understanding of how margins are calculated, blocked, released, and managed throughout the order lifecycle.

## Core Concepts

### What is Margin?

Margin is the amount of funds that must be blocked (reserved) when placing an order or holding a position. It acts as collateral to cover potential losses.

**Key Principles**:
- Margin is **blocked** when order is placed
- Margin is **released** when order is cancelled or position is closed
- Margin is **adjusted** when position size changes
- Different instruments and products have different margin requirements

### Margin vs Trade Value

```python
Trade Value = Price × Quantity
Margin Required = Trade Value ÷ Leverage

Example:
- Buy 100 RELIANCE @ ₹1,200
- Trade Value = 100 × ₹1,200 = ₹120,000
- Leverage (MIS) = 5x
- Margin Required = ₹120,000 ÷ 5 = ₹24,000
```

## Margin Blocking Decision Logic

### When is Margin Blocked?

**File**: `sandbox/order_manager.py` (lines 225-262)

```python
def should_block_margin(action, product, symbol, exchange):
    """
    Decision tree for whether margin should be blocked
    """

    # Rule 1: ALL BUY orders require margin
    if action == 'BUY':
        return True

    # Rule 2: SELL orders - depends on instrument type
    if action == 'SELL':
        # Check if it's an option
        if is_option(symbol, exchange):
            # Selling options (writing) requires margin
            return True

        # Check if it's a future
        if is_future(symbol, exchange):
            # Selling futures (shorting) requires margin
            return True

        # For equity, check product type
        if product in ['MIS', 'NRML']:
            # Short selling in MIS/NRML requires margin
            return True

        # CNC SELL of existing holdings doesn't need margin
        # (but this is checked separately)
        return False

    return False
```

### Margin Blocking Matrix

| Order Type | Instrument | Action | Product | Margin Blocked? | Reason |
|------------|------------|--------|---------|-----------------|---------|
| **Buy Orders** |
| BUY | Any | BUY | Any | ✅ Yes | Buying requires capital |
| **Sell Orders** |
| SELL | Option (CE/PE) | SELL | Any | ✅ Yes | Option writing requires margin |
| SELL | Future (FUT) | SELL | Any | ✅ Yes | Future shorting requires margin |
| SELL | Equity | SELL | MIS/NRML | ✅ Yes | Short selling requires margin |
| SELL | Equity | SELL | CNC | ❌ No* | Selling holdings, no margin needed |

*Note: CNC SELL without holdings will be rejected during validation

## Instrument Type Detection

**File**: `sandbox/order_manager.py` (lines 33-44)

### Helper Functions

```python
def is_option(symbol, exchange):
    """
    Detect if symbol is an option based on exchange and suffix

    Logic:
    - Must be derivative exchange: NFO, BFO, MCX, CDS, BCD, NCDEX
    - Symbol must end with 'CE' (Call) or 'PE' (Put)

    Examples:
    ✅ NIFTY25JAN25000CE - NFO, ends with CE → Option
    ✅ BANKNIFTY25JAN50000PE - NFO, ends with PE → Option
    ❌ NIFTY25JAN25000FUT - NFO, ends with FUT → Not Option
    ❌ RELIANCE - NSE, no suffix → Not Option
    """
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('CE') or symbol.endswith('PE')
    return False

def is_future(symbol, exchange):
    """
    Detect if symbol is a future based on exchange and suffix

    Logic:
    - Must be derivative exchange: NFO, BFO, MCX, CDS, BCD, NCDEX
    - Symbol must end with 'FUT'

    Examples:
    ✅ NIFTY25JAN25000FUT - NFO, ends with FUT → Future
    ✅ CRUDEOIL25JANFUT - MCX, ends with FUT → Future
    ❌ NIFTY25JAN25000CE - NFO, ends with CE → Not Future
    ❌ SBIN - NSE, no suffix → Not Future
    """
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('FUT')
    return False
```

**Why Suffix-Based Detection?**
- Avoids hardcoded instrument type arrays
- Works across all brokers and contract naming conventions
- Automatically handles new contracts
- More maintainable and flexible

## Price Selection for Margin Calculation

**File**: `sandbox/order_manager.py` (lines 153-207)

### Key Principle

Different order types use different prices for margin calculation to provide realistic margin requirements:

```python
def _get_margin_calculation_price(order_data, ltp):
    """
    Select appropriate price for margin calculation

    Principle: Use the price at which margin is most likely
    to be blocked in real trading
    """
    price_type = order_data['price_type']

    if price_type == 'MARKET':
        # MARKET orders execute immediately at LTP
        return ltp

    elif price_type == 'LIMIT':
        # LIMIT orders will execute at limit price (or better)
        # Use limit price for margin calculation
        return order_data['price']

    elif price_type in ['SL', 'SL-M']:
        # SL orders trigger at trigger_price
        # Use trigger_price for margin calculation
        return order_data['trigger_price']

    else:
        # Fallback to LTP
        return ltp
```

### Examples

#### Example 1: MARKET Order

```python
Order Data:
- Symbol: RELIANCE
- Action: BUY
- Quantity: 100
- Price Type: MARKET
- Product: MIS
- Current LTP: ₹1,187.50

Margin Calculation:
- Price Used: ₹1,187.50 (LTP)
- Trade Value: 100 × ₹1,187.50 = ₹118,750
- Leverage: 5x (MIS)
- Margin Required: ₹118,750 ÷ 5 = ₹23,750

✅ Margin Blocked: ₹23,750
```

#### Example 2: LIMIT Order

```python
Order Data:
- Symbol: YESBANK
- Action: BUY
- Quantity: 1000
- Price Type: LIMIT
- Limit Price: ₹22.00
- Product: MIS
- Current LTP: ₹21.40

Margin Calculation:
- Price Used: ₹22.00 (Limit Price, NOT LTP)
- Trade Value: 1000 × ₹22.00 = ₹22,000
- Leverage: 5x (MIS)
- Margin Required: ₹22,000 ÷ 5 = ₹4,400

✅ Margin Blocked: ₹4,400

Why Limit Price?
- Order will execute at ₹22 or better
- Must ensure sufficient margin for worst-case (limit price)
- Even if LTP is ₹21.40, margin is based on ₹22
```

#### Example 3: SL Order

```python
Order Data:
- Symbol: SBIN
- Action: SELL
- Quantity: 500
- Price Type: SL
- Trigger Price: ₹770.00
- Limit Price: ₹769.00
- Product: MIS
- Current LTP: ₹775.00

Margin Calculation:
- Price Used: ₹770.00 (Trigger Price)
- Trade Value: 500 × ₹770.00 = ₹385,000
- Leverage: 5x (MIS)
- Margin Required: ₹385,000 ÷ 5 = ₹77,000

✅ Margin Blocked: ₹77,000

Why Trigger Price?
- Order will trigger at ₹770 and execute around that level
- Trigger price is most realistic for margin calculation
- Ensures adequate margin when order becomes active
```

#### Example 4: SL-M Order

```python
Order Data:
- Symbol: TATAMOTORS
- Action: BUY
- Quantity: 300
- Price Type: SL-M
- Trigger Price: ₹950.00
- Product: MIS
- Current LTP: ₹945.00

Margin Calculation:
- Price Used: ₹950.00 (Trigger Price)
- Trade Value: 300 × ₹950.00 = ₹285,000
- Leverage: 5x (MIS)
- Margin Required: ₹285,000 ÷ 5 = ₹57,000

✅ Margin Blocked: ₹57,000

Why Trigger Price?
- SL-M executes at market when trigger price is hit
- Trigger price gives realistic estimate of execution price
- Better than using current LTP which might be far from trigger
```

## Leverage Rules

**File**: `sandbox/fund_manager.py` (lines 299-349)

### Leverage by Exchange and Product

```python
def _get_leverage(symbol, exchange, product, action):
    """
    Get leverage multiplier based on:
    - Exchange type
    - Instrument type
    - Product type
    - Action (for options)
    """

    # 1. EQUITY EXCHANGES (NSE, BSE)
    if exchange in ['NSE', 'BSE']:
        if product == 'MIS':
            # Intraday: Higher leverage
            return float(get_config('equity_mis_leverage', 5))
        elif product == 'CNC':
            # Delivery: No leverage
            return float(get_config('equity_cnc_leverage', 1))
        else:  # NRML
            # Equity NRML typically same as CNC
            return float(get_config('equity_cnc_leverage', 1))

    # 2. DERIVATIVES EXCHANGES (NFO, BFO, CDS, BCD, MCX, NCDEX)
    if exchange in ['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCDEX']:

        # Check if it's an option
        if is_option(symbol, exchange):
            if action == 'BUY':
                # Buying options: Full premium required (no leverage)
                return float(get_config('option_buy_leverage', 1))
            else:  # SELL
                # Selling options: Uses futures-equivalent margin
                return float(get_config('option_sell_leverage', 10))

        # Check if it's a future
        if is_future(symbol, exchange):
            # Futures: Standard leverage
            return float(get_config('futures_leverage', 10))

    # 3. DEFAULT
    return 1.0  # No leverage if unsure
```

### Leverage Configuration Table

| Exchange | Instrument | Product | Action | Leverage | Config Key | Default Value |
|----------|------------|---------|--------|----------|-----------|---------------|
| **NSE/BSE** | | | | | | |
| NSE/BSE | Equity | MIS | BUY/SELL | 5x | equity_mis_leverage | 5 |
| NSE/BSE | Equity | CNC | BUY | 1x | equity_cnc_leverage | 1 |
| NSE/BSE | Equity | NRML | BUY/SELL | 1x | equity_cnc_leverage | 1 |
| **Derivatives** | | | | | | |
| NFO/BFO/etc | Option | Any | BUY | 1x | option_buy_leverage | 1 |
| NFO/BFO/etc | Option | Any | SELL | 1x | option_sell_leverage | 1 |
| NFO/BFO/etc | Future | MIS | BUY/SELL | 10x | futures_leverage | 10 |
| NFO/BFO/etc | Future | NRML | BUY/SELL | 10x | futures_leverage | 10 |

**Configurable via**: `/sandbox` settings page or `sandbox_config` table

**Note**: Option selling leverage is set to 1x (full premium) by default for simplicity. Both option buying and selling require full premium amount, avoiding the complexity of futures-based margin calculations.

## Margin Calculation Methods

**File**: `sandbox/fund_manager.py` (lines 150-250)

### Method 1: Option Buying (Full Premium)

```python
def calculate_option_buy_margin(order_data, ltp):
    """
    Option buying requires full premium amount

    Formula: Margin = Premium × Lot Size × Quantity

    No leverage applied - full premium must be paid
    """
    symbol = order_data['symbol']
    exchange = order_data['exchange']
    quantity = order_data['quantity']

    # Get margin calculation price (option premium)
    premium = _get_margin_calculation_price(order_data, ltp)

    # Get lot size
    lot_size = get_lot_size(symbol, exchange)

    # Calculate margin (full premium)
    margin = premium * lot_size * quantity

    return round(margin, 2)
```

**Example**:
```python
Order:
- Symbol: NIFTY25JAN25000CE
- Action: BUY
- Quantity: 1 lot
- Premium: ₹150
- Lot Size: 50

Calculation:
Margin = 150 × 50 × 1 = ₹7,500

✅ No leverage - full premium required
```

### Method 2: Option Selling (Futures Margin)

```python
def calculate_option_sell_margin(order_data, underlying_ltp):
    """
    Option selling uses futures-equivalent margin

    Formula: Margin = (Underlying LTP × Lot Size × Qty) ÷ Leverage

    Uses underlying futures price, not option premium
    """
    symbol = order_data['symbol']
    exchange = order_data['exchange']
    quantity = order_data['quantity']

    # Get underlying futures LTP
    # For NIFTY25JAN25000CE, get NIFTY25JAN FUT price
    underlying_ltp = get_underlying_ltp(symbol, exchange)

    # Get lot size
    lot_size = get_lot_size(symbol, exchange)

    # Get leverage
    leverage = get_config('option_sell_leverage', 10)

    # Calculate margin
    contract_value = underlying_ltp * lot_size * quantity
    margin = contract_value / leverage

    return round(margin, 2)
```

**Example**:
```python
Order:
- Symbol: NIFTY25JAN25000CE
- Action: SELL
- Quantity: 1 lot
- Premium: ₹150 (not used for margin)
- Lot Size: 50
- Underlying (NIFTY) LTP: ₹25,150
- Leverage: 10x

Calculation:
Contract Value = 25,150 × 50 × 1 = ₹1,257,500
Margin = ₹1,257,500 ÷ 10 = ₹125,750

✅ Uses underlying futures price, NOT premium
✅ Similar margin as selling equivalent future
```

### Method 3: Futures

```python
def calculate_futures_margin(order_data, ltp):
    """
    Futures margin based on contract value

    Formula: Margin = (LTP × Lot Size × Qty) ÷ Leverage
    """
    symbol = order_data['symbol']
    exchange = order_data['exchange']
    quantity = order_data['quantity']

    # Get margin calculation price
    futures_price = _get_margin_calculation_price(order_data, ltp)

    # Get lot size
    lot_size = get_lot_size(symbol, exchange)

    # Get leverage
    leverage = get_config('futures_leverage', 10)

    # Calculate margin
    contract_value = futures_price * lot_size * quantity
    margin = contract_value / leverage

    return round(margin, 2)
```

**Example**:
```python
Order:
- Symbol: NIFTY25JAN25000FUT
- Action: BUY
- Quantity: 1 lot
- LTP: ₹25,150
- Lot Size: 50
- Leverage: 10x

Calculation:
Contract Value = 25,150 × 50 × 1 = ₹1,257,500
Margin = ₹1,257,500 ÷ 10 = ₹125,750

✅ 10% of contract value required as margin
```

### Method 4: Equity

```python
def calculate_equity_margin(order_data, ltp):
    """
    Equity margin based on trade value

    Formula: Margin = (Price × Qty) ÷ Leverage
    """
    quantity = order_data['quantity']
    product = order_data['product']
    exchange = order_data['exchange']

    # Get margin calculation price
    price = _get_margin_calculation_price(order_data, ltp)

    # Get leverage based on product
    if product == 'MIS':
        leverage = get_config('equity_mis_leverage', 5)
    else:  # CNC or NRML
        leverage = get_config('equity_cnc_leverage', 1)

    # Calculate margin
    trade_value = price * quantity
    margin = trade_value / leverage

    return round(margin, 2)
```

**Example - MIS**:
```python
Order:
- Symbol: RELIANCE
- Exchange: NSE
- Action: BUY
- Quantity: 100
- Price Type: LIMIT
- Limit Price: ₹1,200
- Product: MIS
- Leverage: 5x

Calculation:
Trade Value = 1,200 × 100 = ₹120,000
Margin = ₹120,000 ÷ 5 = ₹24,000

✅ 20% margin required for MIS
```

**Example - CNC**:
```python
Order:
- Symbol: RELIANCE
- Exchange: NSE
- Action: BUY
- Quantity: 100
- Price Type: MARKET
- LTP: ₹1,200
- Product: CNC
- Leverage: 1x

Calculation:
Trade Value = 1,200 × 100 = ₹120,000
Margin = ₹120,000 ÷ 1 = ₹120,000

✅ Full payment required for delivery
```

## Margin Blocking Flow

**File**: `sandbox/order_manager.py` (lines 100-300)

### Step-by-Step Order Placement

```python
def place_order(order_data, user_id):
    """
    Complete order placement flow with margin blocking
    """

    # STEP 1: Validate Order Data
    if not validate_order_data(order_data):
        return False, {'message': 'Invalid order data'}, 400

    # STEP 2: Get Current LTP
    try:
        ltp = get_quotes(order_data['symbol'], order_data['exchange'])['ltp']
    except Exception as e:
        return False, {'message': f'Failed to get LTP: {e}'}, 500

    # STEP 3: Calculate Margin Required
    margin_required = calculate_margin(order_data, ltp)

    # STEP 4: Check if Margin Should Be Blocked
    if not should_block_margin(
        order_data['action'],
        order_data['product'],
        order_data['symbol'],
        order_data['exchange']
    ):
        margin_required = 0  # No margin needed

    # STEP 5: Check Available Funds
    fund = SandboxFunds.query.filter_by(user_id=user_id).first()

    if not fund:
        # Create new fund record
        fund = SandboxFunds(
            user_id=user_id,
            total_capital=Decimal('10000000.00'),
            available_balance=Decimal('10000000.00'),
            used_margin=Decimal('0.00')
        )
        db_session.add(fund)
        db_session.commit()

    if fund.available_balance < margin_required:
        return False, {
            'status': 'error',
            'message': f'Insufficient funds. Required: ₹{margin_required:,.2f}, '
                      f'Available: ₹{fund.available_balance:,.2f}'
        }, 400

    # STEP 6: Block Margin
    fund.available_balance -= Decimal(str(margin_required))
    fund.used_margin += Decimal(str(margin_required))
    fund.updated_at = datetime.now(IST)

    # STEP 7: Create Order Record
    orderid = generate_orderid()

    order = SandboxOrders(
        orderid=orderid,
        user_id=user_id,
        symbol=order_data['symbol'],
        exchange=order_data['exchange'],
        action=order_data['action'],
        quantity=order_data['quantity'],
        price=order_data.get('price'),
        trigger_price=order_data.get('trigger_price'),
        price_type=order_data['price_type'],
        product=order_data['product'],
        order_status='open',  # Will be updated if MARKET
        pending_quantity=order_data['quantity'],
        filled_quantity=0,
        margin_blocked=Decimal(str(margin_required)),  # Store blocked margin
        order_timestamp=datetime.now(IST),
        update_timestamp=datetime.now(IST)
    )

    db_session.add(order)

    # STEP 8: Execute if MARKET Order
    if order_data['price_type'] == 'MARKET':
        # Execute immediately
        execute_order(order, ltp)
        order.order_status = 'complete'
        order.filled_quantity = order.quantity
        order.pending_quantity = 0
        order.average_price = Decimal(str(ltp))

        # Create trade entry
        create_trade(order, ltp)

        # Update position
        update_position(order, ltp, user_id)

    # STEP 9: Commit All Changes
    try:
        db_session.commit()
        logger.info(f"Order {orderid} placed, margin blocked: ₹{margin_required}")

        return True, {
            'status': 'success',
            'orderid': orderid,
            'margin_blocked': margin_required
        }, 200

    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to place order: {e}")
        return False, {'status': 'error', 'message': str(e)}, 500
```

### Margin Blocking Diagram

```
Order Placed
     ↓
Calculate Margin Required
     ↓
Check: Should Block Margin?
     ├─ Yes → Check Available Funds
     │        ├─ Sufficient → Block Margin
     │        │               ↓
     │        │          Update Funds:
     │        │          - available_balance -= margin
     │        │          - used_margin += margin
     │        │               ↓
     │        │          Store in order.margin_blocked
     │        │               ↓
     │        │          Create Order (status='open')
     │        │               ↓
     │        │          Execute if MARKET
     │        │               ↓
     │        │          Success ✅
     │        │
     │        └─ Insufficient → Reject Order ❌
     │
     └─ No → Create Order without blocking ✅
```

## Margin Release Flow

### Scenario 1: Order Cancellation

**File**: `sandbox/order_manager.py` (lines 477-537)

```python
def cancel_order(orderid, user_id):
    """
    Cancel order and release blocked margin
    """

    # STEP 1: Find Order
    order = SandboxOrders.query.filter_by(
        orderid=orderid,
        user_id=user_id
    ).first()

    if not order:
        return False, "Order not found"

    # STEP 2: Validate Order Can Be Cancelled
    if order.order_status != 'open':
        return False, f"Cannot cancel {order.order_status} order"

    try:
        # STEP 3: Release Blocked Margin
        if order.margin_blocked and order.margin_blocked > 0:
            fund = SandboxFunds.query.filter_by(user_id=user_id).first()

            if fund:
                # Add back to available balance
                fund.available_balance += order.margin_blocked

                # Reduce used margin
                fund.used_margin -= order.margin_blocked

                # Update timestamp
                fund.updated_at = datetime.now(IST)

                logger.info(f"Released margin: ₹{order.margin_blocked} for order {orderid}")

        # STEP 4: Update Order Status
        order.order_status = 'cancelled'
        order.update_timestamp = datetime.now(IST)

        # STEP 5: Commit Changes
        db_session.commit()

        return True, "Order cancelled successfully, margin released"

    except Exception as e:
        db_session.rollback()
        logger.error(f"Error cancelling order {orderid}: {e}")
        return False, str(e)
```

**Margin Release on Cancellation**:
```
Cancelled Order
     ↓
Get order.margin_blocked amount
     ↓
Update Funds:
- available_balance += margin_blocked
- used_margin -= margin_blocked
     ↓
Set order.status = 'cancelled'
     ↓
Margin Released ✅
```

### Scenario 2: Position Closure

**File**: `sandbox/position_manager.py` (lines 200-300)

```python
def close_position(user_id, symbol, exchange, product):
    """
    Close position and release margin
    """

    # STEP 1: Find Position
    position = SandboxPositions.query.filter_by(
        user_id=user_id,
        symbol=symbol,
        exchange=exchange,
        product=product
    ).first()

    if not position or position.quantity == 0:
        return False, "No position to close"

    try:
        # STEP 2: Get Current LTP
        ltp = get_quotes(symbol, exchange)['ltp']

        # STEP 3: Calculate Realized P&L
        realized_pnl = calculate_realized_pnl(position, ltp)

        # STEP 4: Calculate Margin to Release
        margin_to_release = calculate_position_margin(position)

        # STEP 5: Place Reverse Order to Close Position
        reverse_action = 'SELL' if position.quantity > 0 else 'BUY'
        reverse_qty = abs(position.quantity)

        close_order_data = {
            'symbol': symbol,
            'exchange': exchange,
            'action': reverse_action,
            'quantity': reverse_qty,
            'price_type': 'MARKET',
            'product': product
        }

        # This will execute at LTP and update position to qty=0
        success, response, code = place_order(close_order_data, user_id)

        if not success:
            return False, "Failed to place closing order"

        # STEP 6: Update Funds with Realized P&L
        fund = SandboxFunds.query.filter_by(user_id=user_id).first()

        if fund:
            # Release margin
            fund.available_balance += Decimal(str(margin_to_release))
            fund.used_margin -= Decimal(str(margin_to_release))

            # Update realized P&L
            fund.realized_pnl += Decimal(str(realized_pnl))

            # Total P&L
            fund.total_pnl = fund.realized_pnl + fund.unrealized_pnl

            fund.updated_at = datetime.now(IST)

        # STEP 7: Update Position
        position.quantity = 0
        position.pnl = Decimal('0.00')
        position.updated_at = datetime.now(IST)

        db_session.commit()

        logger.info(f"Position closed, margin released: ₹{margin_to_release}, "
                   f"realized P&L: ₹{realized_pnl}")

        return True, f"Position closed successfully. P&L: ₹{realized_pnl:,.2f}"

    except Exception as e:
        db_session.rollback()
        logger.error(f"Error closing position: {e}")
        return False, str(e)
```

**Margin Release on Position Closure**:
```
Close Position Request
     ↓
Get Current LTP
     ↓
Calculate Realized P&L
     ↓
Calculate Margin to Release
     ↓
Place Reverse MARKET Order
     ↓
Update Funds:
- available_balance += margin_released
- used_margin -= margin_released
- realized_pnl += position_pnl
     ↓
Update Position:
- quantity = 0
- pnl = 0
     ↓
Margin Released ✅
```

### Scenario 3: Auto Square-Off

**File**: `sandbox/squareoff_manager.py` (lines 145-200)

```python
def _close_mis_positions(exchanges):
    """
    Close all MIS positions at square-off time and release margin
    """

    for exchange in exchanges:
        # Get all MIS positions with non-zero quantity
        positions = SandboxPositions.query.filter_by(
            product='MIS',
            exchange=exchange
        ).filter(
            SandboxPositions.quantity != 0
        ).all()

        for position in positions:
            try:
                # STEP 1: Get Current LTP
                ltp = get_quotes(position.symbol, position.exchange)['ltp']

                # STEP 2: Calculate Realized P&L
                if position.quantity > 0:  # Long
                    realized_pnl = (ltp - position.average_price) * position.quantity
                else:  # Short
                    realized_pnl = (position.average_price - ltp) * abs(position.quantity)

                # STEP 3: Calculate Margin to Release
                margin_to_release = calculate_position_margin(position)

                # STEP 4: Create Reverse Order
                reverse_action = 'SELL' if position.quantity > 0 else 'BUY'
                reverse_qty = abs(position.quantity)

                # Execute at MARKET (LTP)
                squareoff_order = {
                    'symbol': position.symbol,
                    'exchange': position.exchange,
                    'action': reverse_action,
                    'quantity': reverse_qty,
                    'price_type': 'MARKET',
                    'product': 'MIS',
                    'price': ltp
                }

                # Execute immediately (no order record needed for squareoff)
                execute_squareoff_order(squareoff_order, position.user_id, ltp)

                # STEP 5: Update Funds
                fund = SandboxFunds.query.filter_by(
                    user_id=position.user_id
                ).first()

                if fund:
                    # Release margin
                    fund.available_balance += Decimal(str(margin_to_release))
                    fund.used_margin -= Decimal(str(margin_to_release))

                    # Update realized P&L
                    fund.realized_pnl += Decimal(str(realized_pnl))
                    fund.total_pnl = fund.realized_pnl + fund.unrealized_pnl

                    fund.updated_at = datetime.now(IST)

                # STEP 6: Update Position
                position.quantity = 0
                position.pnl = Decimal('0.00')
                position.updated_at = datetime.now(IST)

                logger.info(f"Squared off {position.symbol}, "
                           f"margin released: ₹{margin_to_release}, "
                           f"P&L: ₹{realized_pnl}")

            except Exception as e:
                logger.error(f"Error squaring off {position.symbol}: {e}")

        db_session.commit()
```

**Auto Square-Off Margin Release**:
```
Square-Off Time Triggered (e.g., 3:15 PM for NSE)
     ↓
Get All MIS Positions for Exchange
     ↓
For Each Position:
  ├─ Get Current LTP
  ├─ Calculate Realized P&L
  ├─ Calculate Margin to Release
  ├─ Execute Reverse MARKET Order
  ├─ Release Margin:
  │  - available_balance += margin
  │  - used_margin -= margin
  │  - realized_pnl += pnl
  └─ Set position.quantity = 0
     ↓
All MIS Margins Released ✅
```

### Scenario 4: Partial Position Reduction

**File**: `sandbox/position_manager.py` (lines 100-150)

```python
def update_position_on_trade(trade_data, user_id):
    """
    Update position and adjust margin when position is partially reduced
    """

    position = SandboxPositions.query.filter_by(
        user_id=user_id,
        symbol=trade_data['symbol'],
        exchange=trade_data['exchange'],
        product=trade_data['product']
    ).first()

    if not position:
        # New position - margin already blocked at order level
        create_new_position(trade_data, user_id)
        return

    # Calculate old and new quantities
    old_qty = position.quantity
    trade_qty = trade_data['quantity']
    trade_action = trade_data['action']

    if trade_action == 'BUY':
        new_qty = old_qty + trade_qty
    else:  # SELL
        new_qty = old_qty - trade_qty

    # CASE 1: Position Increasing
    if abs(new_qty) > abs(old_qty):
        # Margin already blocked at order level
        # Just update position quantity and average price
        update_position_details(position, trade_data)

    # CASE 2: Position Decreasing but not closed
    elif new_qty != 0 and abs(new_qty) < abs(old_qty):
        # Calculate margin to release (for reduced quantity)
        qty_reduced = abs(old_qty) - abs(new_qty)
        margin_per_unit = calculate_margin_per_unit(position)
        margin_to_release = margin_per_unit * qty_reduced

        # Calculate partial realized P&L
        if old_qty > 0:  # Was long
            partial_pnl = (trade_data['price'] - position.average_price) * qty_reduced
        else:  # Was short
            partial_pnl = (position.average_price - trade_data['price']) * qty_reduced

        # Release margin
        fund = SandboxFunds.query.filter_by(user_id=user_id).first()
        if fund:
            fund.available_balance += Decimal(str(margin_to_release))
            fund.used_margin -= Decimal(str(margin_to_release))
            fund.realized_pnl += Decimal(str(partial_pnl))
            fund.updated_at = datetime.now(IST)

        # Update position
        position.quantity = new_qty
        position.updated_at = datetime.now(IST)

        logger.info(f"Position reduced, margin released: ₹{margin_to_release}, "
                   f"partial P&L: ₹{partial_pnl}")

    # CASE 3: Position Closed (new_qty = 0)
    elif new_qty == 0:
        # Full margin release (handled in close_position flow)
        pass

    # CASE 4: Position Reversed
    elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
        # Close old position, open new opposite position
        # Margin adjustments handled accordingly
        reverse_position(position, trade_data, user_id)

    db_session.commit()
```

**Partial Reduction Example**:
```python
Initial Position:
- Symbol: RELIANCE
- Quantity: 100 (long)
- Average Price: ₹1,200
- Margin Blocked: ₹24,000 (₹240 per share @ 5x leverage)

SELL 50 shares @ ₹1,250:
     ↓
New Quantity: 100 - 50 = 50
     ↓
Margin to Release:
- Old margin: ₹24,000
- New required: ₹12,000 (50 shares × ₹240)
- Release: ₹12,000
     ↓
Partial Realized P&L:
- (₹1,250 - ₹1,200) × 50 = ₹2,500
     ↓
Update Funds:
- available_balance += ₹12,000
- used_margin -= ₹12,000
- realized_pnl += ₹2,500
     ↓
Final Position:
- Quantity: 50 (long)
- Average Price: ₹1,200 (unchanged)
- Margin Blocked: ₹12,000
```

## Fund Tracking

**File**: `database/sandbox_db.py`

### SandboxFunds Model

```python
class SandboxFunds(Base):
    __tablename__ = 'sandbox_funds'

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False)

    # Capital and Balance
    total_capital = Column(DECIMAL(15, 2), default=10000000.00)
    available_balance = Column(DECIMAL(15, 2), default=10000000.00)
    used_margin = Column(DECIMAL(15, 2), default=0.00)

    # P&L Tracking
    realized_pnl = Column(DECIMAL(15, 2), default=0.00)
    unrealized_pnl = Column(DECIMAL(15, 2), default=0.00)
    total_pnl = Column(DECIMAL(15, 2), default=0.00)

    # Reset Tracking
    last_reset_date = Column(DateTime, default=datetime.now)
    reset_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)
```

### Fund Balance Calculation

```python
def calculate_fund_balance(user_id):
    """
    Calculate comprehensive fund details
    """
    fund = SandboxFunds.query.filter_by(user_id=user_id).first()

    if not fund:
        return None

    # Available Balance
    # = Starting Capital + Realized P&L - Used Margin
    available_balance = (
        fund.total_capital +
        fund.realized_pnl -
        fund.used_margin
    )

    # Unrealized P&L (from open positions)
    positions = SandboxPositions.query.filter_by(
        user_id=user_id
    ).filter(SandboxPositions.quantity != 0).all()

    unrealized_pnl = Decimal('0.00')
    for position in positions:
        ltp = get_quotes(position.symbol, position.exchange)['ltp']
        pnl, _ = calculate_pnl(position, ltp)
        unrealized_pnl += Decimal(str(pnl))

    # Total P&L
    total_pnl = fund.realized_pnl + unrealized_pnl

    # Update fund record
    fund.available_balance = available_balance
    fund.unrealized_pnl = unrealized_pnl
    fund.total_pnl = total_pnl
    fund.updated_at = datetime.now(IST)

    db_session.commit()

    return {
        'total_capital': float(fund.total_capital),
        'available_balance': float(available_balance),
        'used_margin': float(fund.used_margin),
        'realized_pnl': float(fund.realized_pnl),
        'unrealized_pnl': float(unrealized_pnl),
        'total_pnl': float(total_pnl)
    }
```

### Fund Balance Relationships

```
┌─────────────────────────────────────────────────────┐
│                  FUND COMPONENTS                     │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Total Capital:        ₹10,000,000                   │
│  (Starting Balance)                                  │
│                                                      │
│  Realized P&L:         +₹50,000                      │
│  (From Closed Positions)                             │
│                                                      │
│  Used Margin:          -₹200,000                     │
│  (Blocked for Open Positions)                        │
│                                                      │
│  ───────────────────────────────────────────         │
│                                                      │
│  Available Balance:    ₹9,850,000                    │
│  (For New Orders)                                    │
│                                                      │
│  ───────────────────────────────────────────         │
│                                                      │
│  Unrealized P&L:       +₹15,000                      │
│  (From Open Positions)                               │
│                                                      │
│  ───────────────────────────────────────────         │
│                                                      │
│  Total P&L:            +₹65,000                      │
│  (Realized + Unrealized)                             │
│                                                      │
└─────────────────────────────────────────────────────┘

Formulas:
─────────
available_balance = total_capital + realized_pnl - used_margin
                  = 10,000,000 + 50,000 - 200,000
                  = 9,850,000

total_pnl = realized_pnl + unrealized_pnl
          = 50,000 + 15,000
          = 65,000
```

### Scenario 5: Exact Margin Tracking (Position-Based)

**File**: `sandbox/execution_engine.py` (lines 280-446)
**Database**: `sandbox_positions.margin_blocked` column

#### The Problem: Margin Over-Release Bug

**Root Cause**: Previously, margin was recalculated at position close time using execution price instead of using the exact margin blocked at order placement time.

**Example of the Bug**:
```python
Order Placement:
- BUY 150 RELIANCE @ ₹90.60 (order placement price)
- Margin Blocked: ₹90.60 × 150 ÷ 5 = ₹2,718

Order Execution:
- Order executes at ₹91.0 (LTP/bid/ask)
- Trade created at: ₹91.0

Position Close:
- OLD CODE: Recalculates margin using execution price
- Margin Released: ₹91.0 × 150 ÷ 5 = ₹2,730
- Over-released: ₹12 ❌

Result: used_margin becomes negative
```

#### The Solution: Store Exact Margin in Position

**Database Schema Addition** (`database/sandbox_db.py` lines 122-124):
```python
class SandboxPositions(Base):
    # ... other fields ...

    # Margin tracking - stores exact margin blocked for this position
    # This prevents margin release bugs when execution price differs from order placement price
    margin_blocked = Column(DECIMAL(15, 2), default=0.00)  # Total margin blocked for this position
```

#### How It Works

**Principle**: Store the exact margin amount blocked at order placement time in the position record. When releasing margin, use this stored value instead of recalculating.

##### Case 1: New Position Created

```python
def _update_position(order, execution_price):
    if not position:
        # Store exact margin from order
        order_margin = order.margin_blocked  # Margin blocked at placement
        position = SandboxPositions(
            quantity=order.quantity,
            average_price=execution_price,
            margin_blocked=order_margin,  # Store in position ✅
            # ... other fields ...
        )
```

**Example**:
```python
Order: BUY 100 RELIANCE @ MARKET
- Order placed when LTP = ₹1,200
- Margin blocked at placement: ₹24,000
- Order executes at ₹1,205 (ask price)

Position Created:
- quantity: 100
- average_price: ₹1,205 (execution price)
- margin_blocked: ₹24,000 (from order, not recalculated) ✅
```

##### Case 2: Complete Position Close

```python
def _update_position(order, execution_price):
    if final_quantity == 0:
        # Use STORED margin, not recalculated
        margin_to_release = position.margin_blocked  # ✅ Exact amount

        fund_manager.release_margin(margin_to_release, realized_pnl)

        # Reset margin to 0
        position.margin_blocked = Decimal('0.00')
        position.quantity = 0
```

**Example (The Bug Fix)**:
```python
Position:
- quantity: 150
- average_price: ₹91.0 (execution price)
- margin_blocked: ₹2,718 (stored from order placement @ ₹90.60)

Close Order: SELL 150 @ ₹90.7
- Calculates P&L using position.average_price (₹91.0)
- Realized P&L: (₹90.7 - ₹91.0) × 150 = -₹45

Margin Release:
- OLD CODE: Recalculates: ₹91.0 × 150 ÷ 5 = ₹2,730 ❌
- NEW CODE: Uses stored: ₹2,718 ✅
- Difference: ₹12 (no over-release!)

Result:
- available_balance += ₹2,718
- used_margin -= ₹2,718
- used_margin = ₹0 (correct!) ✅
```

##### Case 3: Adding to Position

```python
def _update_position(order, execution_price):
    if position_size_increasing:
        # Accumulate margin from new order
        order_margin = order.margin_blocked
        position.margin_blocked += order_margin  # Add to existing ✅

        # Update average price
        position.average_price = calculate_new_average(...)
```

**Example**:
```python
Initial Position:
- quantity: 100
- average_price: ₹1,200
- margin_blocked: ₹24,000

Add Order: BUY 50 @ ₹1,210
- Order margin: ₹12,100

Updated Position:
- quantity: 150
- average_price: ₹1,203.33
- margin_blocked: ₹24,000 + ₹12,100 = ₹36,100 ✅
```

##### Case 4: Partial Position Close

```python
def _update_position(order, execution_price):
    if position_reducing:
        # Calculate proportion being closed
        reduction_proportion = reduced_qty / abs(old_quantity)

        # Release proportional margin
        margin_to_release = position.margin_blocked × reduction_proportion  # ✅

        fund_manager.release_margin(margin_to_release, realized_pnl)

        # Update remaining margin
        position.margin_blocked -= margin_to_release
```

**Example**:
```python
Position:
- quantity: 100
- average_price: ₹1,200
- margin_blocked: ₹24,000

Partial Close: SELL 40 @ ₹1,250
- Reduction proportion: 40 / 100 = 40%
- Margin to release: ₹24,000 × 0.40 = ₹9,600 ✅
- Partial P&L: (₹1,250 - ₹1,200) × 40 = ₹2,000

Updated Position:
- quantity: 60
- average_price: ₹1,200 (unchanged)
- margin_blocked: ₹24,000 - ₹9,600 = ₹14,400 ✅

Funds Updated:
- available_balance += ₹9,600
- used_margin -= ₹9,600
- realized_pnl += ₹2,000
```

##### Case 5: Position Reversal

```python
def _update_position(order, execution_price):
    if position_reversed:
        # Release margin proportionally for closed portion
        margin_to_release = position.margin_blocked × (old_qty / new_order_qty)

        # Calculate new position margin from excess quantity
        excess_proportion = remaining_qty / new_order_qty
        new_position_margin = order.margin_blocked × excess_proportion  # ✅

        position.margin_blocked = new_position_margin
        position.quantity = remaining_qty  # opposite direction
```

**Example**:
```python
Initial Position (Long):
- quantity: +100
- average_price: ₹1,200
- margin_blocked: ₹24,000

Reverse Order: SELL 150 @ ₹1,250
- Order margin: ₹30,000 (blocked at order placement)

Position Reversal:
- Close 100 (release ₹24,000)
- Open new -50 SHORT position

Calculation:
- Closed portion: 100 shares → release ₹24,000
- New position: -50 shares (SHORT)
- Excess proportion: 50 / 150 = 33.33%
- New margin: ₹30,000 × 0.3333 = ₹10,000

Updated Position (Short):
- quantity: -50
- average_price: ₹1,250
- margin_blocked: ₹10,000 ✅

Funds:
- Margin released from old: ₹24,000
- Margin blocked for new: ₹10,000 (already blocked at order time)
- Net used_margin change: -₹24,000
- Realized P&L: (₹1,250 - ₹1,200) × 100 = ₹5,000
```

#### Benefits of Position-Based Margin Tracking

**1. Prevents Over-Release**
```python
# OLD: Margin recalculated → ₹60 over-release
# NEW: Exact margin used → ₹0 over-release ✅
```

**2. Handles Price Differences**
```python
Order Price:     ₹90.60  (margin calculated here)
Execution Price: ₹91.00  (trade happens here)
Close Price:     ₹90.70  (P&L calculated here)

Result: Each price serves its purpose, no conflicts ✅
```

**3. Supports Partial Closes**
```python
# Proportional release based on stored margin
Close 40%: Release 40% of stored margin
Close 60%: Release 60% of remaining margin
Total: 100% of original margin released ✅
```

**4. Tracks Multiple Orders**
```python
Order 1: BUY 100 @ ₹1,200 → Margin: ₹24,000
Order 2: BUY 50 @ ₹1,210  → Margin: ₹12,100
Position margin: ₹36,100 (accumulated) ✅

Close all: Release exact ₹36,100 ✅
```

#### Migration

**Script**: `upgrade/migrate_sandbox.py`

**What It Does**:
- Adds `margin_blocked` column to `sandbox_positions` table
- Sets default value to ₹0.00 for existing positions
- New positions will store exact margin going forward

**Run Migration**:
```bash
cd upgrade
uv run migrate_sandbox.py

# Check status
uv run migrate_sandbox.py --status
```

**Result**:
```
✅ Added margin_blocked column to sandbox_positions
✅ Migration sandbox_complete_setup completed successfully
```

#### Verification

**Check Schema**:
```python
from database.sandbox_db import SandboxPositions

# Verify column exists
position = SandboxPositions.query.first()
print(position.margin_blocked)  # Should return Decimal value
```

**Check Margin Release**:
```python
# Before fix:
1. BUY 150 @ market
2. SELL 150 @ market
3. Check used_margin → might be -₹60 ❌

# After fix:
1. BUY 150 @ market
2. SELL 150 @ market
3. Check used_margin → exactly ₹0 ✅
```

#### Summary: Exact Margin Flow

```
Order Placement
     ↓
Calculate Margin (using order price)
     ↓
Block Margin in Funds
     ↓
Store in order.margin_blocked
     ↓
─────────────────────────────────
     ↓
Order Executes (at different price)
     ↓
Position Created/Updated
     ↓
Store order.margin_blocked → position.margin_blocked ✅
     ↓
─────────────────────────────────
     ↓
Position Closed
     ↓
Use position.margin_blocked (NOT recalculated) ✅
     ↓
Release Exact Amount
     ↓
used_margin = ₹0 (perfect balance) ✅
```

**Key Principle**: "Block at order price, store in position, release exact amount" - This ensures perfect margin accounting regardless of price movements between order placement and execution.

## Common Scenarios

### Scenario A: Simple BUY and SELL

```python
Step 1: BUY 100 RELIANCE @ ₹1,200 (MIS)
─────────────────────────────────────────
Margin Required: ₹24,000
Available Before: ₹10,000,000
Available After: ₹9,976,000
Used Margin: ₹24,000

Position Created:
- Quantity: +100
- Avg Price: ₹1,200
- Margin: ₹24,000

═══════════════════════════════════════════

Step 2: SELL 100 RELIANCE @ ₹1,250 (MIS)
─────────────────────────────────────────
Position Closed

Realized P&L:
(₹1,250 - ₹1,200) × 100 = ₹5,000 profit

Margin Released: ₹24,000

Funds Updated:
- Available: ₹10,000,000 + ₹5,000 = ₹10,005,000
- Used Margin: ₹0
- Realized P&L: ₹5,000

Final: ₹5,000 profit, all margin released ✅
```

### Scenario B: Multiple Orders, Partial Closure

```python
Step 1: BUY 100 RELIANCE @ ₹1,200 (MIS)
─────────────────────────────────────────
Margin Blocked: ₹24,000
Position: +100 @ ₹1,200

Step 2: BUY 50 RELIANCE @ ₹1,210 (MIS)
─────────────────────────────────────────
Margin Blocked: ₹12,100
Total Margin Used: ₹36,100

Position Updated:
- Quantity: +150
- Avg Price: (100×1200 + 50×1210)/150 = ₹1,203.33

Step 3: SELL 50 RELIANCE @ ₹1,250 (MIS)
─────────────────────────────────────────
Margin Released: ₹12,017 (₹1,203.33 × 50 ÷ 5)
Partial Realized P&L: (₹1,250 - ₹1,203.33) × 50 = ₹2,333.50

Position Updated:
- Quantity: +100
- Avg Price: ₹1,203.33 (unchanged)
- Margin: ₹24,083

Step 4: SELL 100 RELIANCE @ ₹1,260 (MIS)
─────────────────────────────────────────
Position Closed
Margin Released: ₹24,083
Realized P&L: (₹1,260 - ₹1,203.33) × 100 = ₹5,667

Total Realized P&L: ₹2,333.50 + ₹5,667 = ₹8,000.50 ✅
All margin released ✅
```

### Scenario C: Option Buying vs Selling

```python
Scenario C1: BUY OPTION
─────────────────────────────────────────
Order: BUY 1 lot NIFTY25JAN25000CE @ ₹150
Lot Size: 50

Margin Calculation:
- Premium: ₹150
- Lot Size: 50
- Margin: 150 × 50 = ₹7,500

✅ Full premium required, no leverage

Funds Update:
- Used Margin: ₹7,500
- Available: ₹9,992,500

═══════════════════════════════════════════

Scenario C2: SELL OPTION
─────────────────────────────────────────
Order: SELL 1 lot NIFTY25JAN25000CE @ ₹150
Lot Size: 50
Underlying NIFTY LTP: ₹25,150
Leverage: 10x

Margin Calculation:
- Underlying: ₹25,150
- Lot Size: 50
- Contract Value: 25,150 × 50 = ₹1,257,500
- Margin: ₹1,257,500 ÷ 10 = ₹125,750

✅ Uses futures margin, NOT premium

Funds Update:
- Used Margin: ₹125,750
- Available: ₹9,874,250

Note: Option SELL requires 16.7x more margin than BUY!
      (₹125,750 vs ₹7,500)
```

## Edge Cases and Error Handling

### Case 1: Insufficient Funds

```python
Scenario:
- Available Balance: ₹50,000
- Order: BUY 100 RELIANCE @ ₹1,200 (MIS)
- Margin Required: ₹24,000 ✅
- But also have open position using ₹30,000
- Actual Available: ₹50,000 - ₹30,000 = ₹20,000 ❌

Result:
❌ Order Rejected
Message: "Insufficient funds. Required: ₹24,000, Available: ₹20,000"
```

### Case 2: Negative Available Balance Prevention

```python
def validate_funds_before_blocking(user_id, margin_required):
    """
    Prevent orders that would result in negative balance
    """
    fund = SandboxFunds.query.filter_by(user_id=user_id).first()

    # Calculate true available balance
    true_available = fund.total_capital + fund.realized_pnl - fund.used_margin

    if true_available < margin_required:
        return False, f"Insufficient funds. Required: ₹{margin_required:,.2f}, " \
                     f"Available: ₹{true_available:,.2f}"

    return True, "Sufficient funds"
```

### Case 3: Margin Mismatch on Release

```python
def safe_margin_release(user_id, margin_to_release):
    """
    Safely release margin with validation
    """
    fund = SandboxFunds.query.filter_by(user_id=user_id).first()

    if fund.used_margin < margin_to_release:
        # Edge case: Trying to release more than used
        logger.warning(
            f"Margin mismatch: Trying to release ₹{margin_to_release}, "
            f"but only ₹{fund.used_margin} is used"
        )

        # Release only what's actually used
        margin_to_release = fund.used_margin

    fund.available_balance += Decimal(str(margin_to_release))
    fund.used_margin -= Decimal(str(margin_to_release))

    # Ensure used_margin doesn't go negative
    if fund.used_margin < 0:
        fund.used_margin = Decimal('0.00')

    db_session.commit()
```

## Configuration and Customization

### Leverage Customization

Users can customize leverage values from `/sandbox` settings page:

```python
# Default Values (sandbox_config table)
{
    'equity_mis_leverage': '5',      # NSE/BSE MIS
    'equity_cnc_leverage': '1',      # NSE/BSE CNC
    'futures_leverage': '10',        # All futures
    'option_buy_leverage': '1',      # Full premium
    'option_sell_leverage': '10'     # Futures margin
}

# Customize via UI or API
set_config('equity_mis_leverage', '8')  # Increase MIS leverage to 8x
```

**Effect**:
```python
Before (5x leverage):
- Order: BUY 100 RELIANCE @ ₹1,200 (MIS)
- Margin: ₹120,000 ÷ 5 = ₹24,000

After (8x leverage):
- Order: BUY 100 RELIANCE @ ₹1,200 (MIS)
- Margin: ₹120,000 ÷ 8 = ₹15,000

Margin Reduced: ₹9,000 saved per order ✅
```

## Monitoring and Debugging

### Check Margin Status

```python
def get_margin_status(user_id):
    """
    Get detailed margin breakdown
    """
    fund = SandboxFunds.query.filter_by(user_id=user_id).first()
    positions = SandboxPositions.query.filter_by(user_id=user_id) \
        .filter(SandboxPositions.quantity != 0).all()

    margin_breakdown = []
    total_calculated_margin = Decimal('0.00')

    for position in positions:
        margin = calculate_position_margin(position)
        total_calculated_margin += Decimal(str(margin))

        margin_breakdown.append({
            'symbol': position.symbol,
            'quantity': position.quantity,
            'product': position.product,
            'margin': margin
        })

    return {
        'user_id': user_id,
        'total_capital': float(fund.total_capital),
        'available_balance': float(fund.available_balance),
        'used_margin': float(fund.used_margin),
        'calculated_margin': float(total_calculated_margin),
        'margin_mismatch': float(fund.used_margin - total_calculated_margin),
        'positions': margin_breakdown
    }
```

### Log Margin Operations

```python
# Order Placement
logger.info(f"Order {orderid} placed: Margin blocked ₹{margin_blocked:,.2f}")

# Order Cancellation
logger.info(f"Order {orderid} cancelled: Margin released ₹{margin_released:,.2f}")

# Position Closure
logger.info(f"Position {symbol} closed: Margin released ₹{margin_released:,.2f}, "
           f"Realized P&L: ₹{realized_pnl:,.2f}")

# Partial Reduction
logger.info(f"Position {symbol} reduced: Qty {old_qty} → {new_qty}, "
           f"Margin released ₹{margin_released:,.2f}")
```

## Recent Enhancements

### 1. Market Order Bid/Ask Execution

**Feature**: Market orders now execute at realistic bid/ask prices instead of LTP

**File**: `sandbox/execution_engine.py` (lines 156-165)

```python
if order.price_type == 'MARKET':
    # BUY: Execute at ask price (pay seller's asking price)
    # SELL: Execute at bid price (receive buyer's bid price)
    # If bid/ask is 0, fall back to LTP
    if order.action == 'BUY':
        execution_price = ask if ask > 0 else ltp
    else:  # SELL
        execution_price = bid if bid > 0 else ltp
```

**Example**:
```python
Quote Response:
- LTP: 106.3
- Bid: 109.4
- Ask: 109.9

BUY Market Order:
- Executes at: 109.9 (ask) ✅
- Not at: 106.3 (LTP) ❌

SELL Market Order:
- Executes at: 109.4 (bid) ✅
- Not at: 106.3 (LTP) ❌

Impact: More realistic slippage simulation
```

### 2. Intraday P&L Accumulation

**Feature**: Position book shows accumulated P&L for multiple trades on same symbol during the day

**Files**:
- `database/sandbox_db.py` (line 109): Added `accumulated_realized_pnl` column
- `sandbox/execution_engine.py` (lines 358-364, 307-315)
- `sandbox/position_manager.py` (lines 217-218)

**Database Schema Addition**:
```python
class SandboxPositions(Base):
    # Existing fields...
    pnl = Column(DECIMAL(10, 2), default=0.00)
    accumulated_realized_pnl = Column(DECIMAL(10, 2), default=0.00)  # NEW
```

**Behavior**:
```python
Trade 1: SELL @ 109.4, BUY @ 109.9
- Realized P&L: -37.50
- Position Closed (qty=0)
- accumulated_realized_pnl: -37.50
- Display P&L: -37.50

Trade 2: SELL @ 109.4, BUY @ 109.9 (same symbol)
- Realized P&L: -37.50
- Position Closed (qty=0)
- accumulated_realized_pnl: -37.50 + (-37.50) = -75.00
- Display P&L: -75.00 ✅

Open Position (after trades above):
- SELL @ 109.4 (still open)
- Current unrealized P&L: -10.00
- Display P&L: -75.00 (accumulated) + (-10.00) (unrealized) = -85.00 ✅
```

**Key Functions**:

Position Closure (accumulation):
```python
# When closing position
position.accumulated_realized_pnl += realized_pnl
position.pnl = position.accumulated_realized_pnl  # Display total
```

Position Reopening (preserve accumulation):
```python
# When reopening closed position
position.quantity = new_quantity
position.pnl = Decimal('0.00')  # Reset current P&L
# accumulated_realized_pnl preserved from previous trades
```

MTM Update (open positions):
```python
# Calculate display P&L for open positions
current_unrealized_pnl = calculate_position_pnl(qty, avg_price, ltp)
accumulated_realized = position.accumulated_realized_pnl or Decimal('0.00')
position.pnl = accumulated_realized + current_unrealized_pnl
```

**Benefits**:
- Track total intraday P&L per symbol
- See cumulative performance across multiple trades
- Matches real broker position book behavior
- Funds show separate realized P&L (cumulative for all symbols)

### 3. Dynamic Starting Capital Updates

**Feature**: Changing starting capital in `/sandbox` settings now updates user funds immediately

**File**: `blueprints/sandbox.py` (lines 105-126)

```python
# If starting_capital was updated, update all user funds immediately
if config_key == 'starting_capital':
    new_capital = Decimal(str(config_value))

    # Update all user funds with new starting capital
    funds = SandboxFunds.query.all()
    for fund in funds:
        # Calculate new available balance
        # New available = new_capital - used_margin + total_pnl
        fund.total_capital = new_capital
        fund.available_balance = new_capital - fund.used_margin + fund.total_pnl

    db_session.commit()
```

**Example**:
```python
Before:
- Starting Capital: ₹10,000,000
- Used Margin: ₹200,000
- Total P&L: -₹5,000
- Available Balance: ₹9,795,000

Change Starting Capital to: ₹5,000,000

After (Immediate Update):
- Starting Capital: ₹5,000,000
- Used Margin: ₹200,000 (preserved)
- Total P&L: -₹5,000 (preserved)
- Available Balance: ₹4,795,000 (recalculated) ✅

Formula: available = new_capital - used_margin + total_pnl
         = 5,000,000 - 200,000 + (-5,000)
         = 4,795,000
```

**Benefits**:
- No need to wait for weekly reset
- Preserves current positions and P&L
- Instant capital adjustment for testing different scenarios
- Realistic capital management simulation

### 4. Configurable Option Leverage

**Feature**: Option selling leverage now reads from config (not hardcoded)

**File**: `sandbox/fund_manager.py` (lines 326-331)

**Before (Hardcoded)**:
```python
elif is_option(symbol, exchange):
    return Decimal(get_config('option_buy_leverage', '1'))  # Always used this
```

**After (Configurable)**:
```python
elif is_option(symbol, exchange):
    if action == 'BUY':
        return Decimal(get_config('option_buy_leverage', '1'))
    else:  # SELL
        return Decimal(get_config('option_sell_leverage', '1'))
```

**Benefits**:
- Can adjust option selling leverage from `/sandbox` settings
- Defaults to 1x for simplicity (full premium required)
- Can be increased if you want futures-based margin simulation
- No code changes needed for leverage adjustments

## Summary

The Sandbox Margin System provides:

1. **Accurate Margin Blocking**:
   - Instrument-specific calculations
   - Leverage-based margin requirements
   - Order-type specific price selection
   - Bid/ask price execution for market orders

2. **Complete Margin Release**:
   - On order cancellation
   - On position closure
   - On auto square-off
   - On partial position reduction

3. **Fund Tracking**:
   - Real-time available balance
   - Separate realized and unrealized P&L
   - Margin utilization monitoring
   - Intraday P&L accumulation per symbol

4. **Realistic Behavior**:
   - Matches real broker margin mechanics
   - Bid/ask spread crossing on market orders
   - Prevents negative balances
   - Proper margin adjustments on partial closures
   - Accumulated intraday P&L tracking

5. **Configurability**:
   - Customizable leverage values
   - Per-exchange and per-product settings
   - Dynamic starting capital updates
   - Easy updates without code changes
   - All leverage settings read from database config

This comprehensive margin system ensures traders understand real-world margin requirements and fund management before deploying strategies with real capital.

---

**Version**: 1.2.0
**Last Updated**: October 2025
**File References**:
- `sandbox/order_manager.py` (lines 33-44, 153-262, 477-537)
- `sandbox/fund_manager.py` (lines 274-337)
- `sandbox/execution_engine.py` (lines 280-446) - **Updated with exact margin tracking**
- `sandbox/position_manager.py` (lines 178-224)
- `sandbox/squareoff_manager.py` (lines 101-200)
- `blueprints/sandbox.py` (lines 78-143)
- `database/sandbox_db.py` (lines 122-124) - **Added margin_blocked column**
- `upgrade/migrate_sandbox.py` - **Migration for margin_blocked column**
