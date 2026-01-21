# 07 - Sandbox Architecture (Analyzer Mode)

## Overview

OpenAlgo's Sandbox/Analyzer mode provides a production-grade walkforward testing environment with ₹1 Crore sandbox capital, realistic margin calculations, leverage-based trading, auto square-off, and T+1 settlement simulation. It runs completely isolated from live trading with its own database (`db/sandbox.db`).

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Sandbox Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

                              API Request
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Mode Router (is_sandbox_mode())                       │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  if is_sandbox_mode():                                                   │ │
│  │      → Route to Sandbox Services (OrderManager, FundManager, etc.)       │ │
│  │  else:                                                                   │ │
│  │      → Route to Live Broker Services (broker/*/api/*)                    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                    │                               │
           Analyzer Mode ON                    Live Mode
                    │                               │
                    ▼                               ▼
┌───────────────────────────────────┐    ┌───────────────────────────────┐
│      Sandbox Services              │    │      Live Broker Services      │
│                                   │    │                               │
│  ┌─────────────────────────────┐  │    │  ┌─────────────────────────┐  │
│  │    Order Manager            │  │    │  │   Broker Order API      │  │
│  │    - Validation             │  │    │  │   (Real Orders)         │  │
│  │    - Margin Check/Block     │  │    │  └─────────────────────────┘  │
│  │    - Order CRUD             │  │    │                               │
│  └─────────────────────────────┘  │    └───────────────────────────────┘
│                                   │
│  ┌─────────────────────────────┐  │
│  │    Fund Manager             │  │    ┌───────────────────────────────┐
│  │    - ₹1 Cr Sandbox Capital  │  │    │     Background Workers        │
│  │    - Margin Block/Release   │  │    │                               │
│  │    - P&L Tracking           │  │    │  ┌─────────────────────────┐  │
│  │    - Auto Reset             │  │    │  │  Execution Engine       │  │
│  └─────────────────────────────┘  │    │  │  (5 sec polling)        │  │
│                                   │    │  │  - Fetch live quotes    │  │
│  ┌─────────────────────────────┐  │    │  │  - Execute pending      │  │
│  │    Execution Engine         │  │    │  │  - Update positions     │  │
│  │    - Quote Fetching         │  │    │  └─────────────────────────┘  │
│  │    - Price Condition Check  │  │    │                               │
│  │    - Trade Execution        │  │    │  ┌─────────────────────────┐  │
│  │    - Position Netting       │  │    │  │  SquareOff Scheduler    │  │
│  └─────────────────────────────┘  │    │  │  (APScheduler)          │  │
│                                   │    │  │  - MIS auto square-off  │  │
│  ┌─────────────────────────────┐  │    │  │  - T+1 settlement       │  │
│  │    Position Manager         │  │    │  │  - Weekly reset         │  │
│  │    - MTM Updates            │  │    │  └─────────────────────────┘  │
│  │    - P&L Calculation        │  │    │                               │
│  │    - Session Filtering      │  │    │  ┌─────────────────────────┐  │
│  │    - Expiry Handling        │  │    │  │  MTM Update Worker      │  │
│  └─────────────────────────────┘  │    │  │  (5 sec interval)       │  │
│                                   │    │  │  - WebSocket data       │  │
│  ┌─────────────────────────────┐  │    │  │  - REST API fallback    │  │
│  │    Holdings Manager         │  │    │  └─────────────────────────┘  │
│  │    - T+1 Settlement         │  │    │                               │
│  │    - CNC → Holdings         │  │    └───────────────────────────────┘
│  │    - Holdings MTM           │  │
│  └─────────────────────────────┘  │
│                                   │
│  ┌─────────────────────────────┐  │
│  │    Squareoff Manager        │  │
│  │    - Exchange-wise timing   │  │
│  │    - MIS position close     │  │
│  │    - Open order cancel      │  │
│  └─────────────────────────────┘  │
└───────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│       sandbox.db (Isolated)       │
│                                   │
│  • sandbox_orders                 │
│  • sandbox_trades                 │
│  • sandbox_positions              │
│  • sandbox_holdings               │
│  • sandbox_funds                  │
│  • sandbox_daily_pnl              │
│  • sandbox_config                 │
└───────────────────────────────────┘
```

## Core Components

### 1. Database Models

**Location:** `database/sandbox_db.py`

#### SandboxOrders Table

Stores all sandbox orders with complete state tracking.

```python
class SandboxOrders(Base):
    __tablename__ = 'sandbox_orders'

    id = Column(Integer, primary_key=True)
    orderid = Column(String, unique=True, nullable=False)  # ORDER-YYYYMMDD-HHMMSS-uuid
    user_id = Column(String, nullable=False)
    strategy = Column(String)

    # Symbol details
    symbol = Column(String, nullable=False)      # SBIN, NIFTY30JAN25FUT
    exchange = Column(String, nullable=False)    # NSE, NFO, MCX

    # Order details
    action = Column(String, nullable=False)      # BUY, SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2))               # NULL for MARKET orders
    trigger_price = Column(Numeric(10, 2))       # For SL/SL-M orders
    price_type = Column(String, nullable=False)  # MARKET, LIMIT, SL, SL-M
    product = Column(String, nullable=False)     # CNC, NRML, MIS

    # Execution state
    order_status = Column(String, default='open')  # open, complete, cancelled, rejected
    average_price = Column(Numeric(10, 2))         # Fill price
    filled_quantity = Column(Integer, default=0)
    pending_quantity = Column(Integer, nullable=False)

    # Margin tracking (CRITICAL: stores exact margin at order time)
    margin_blocked = Column(Numeric(15, 2))

    # Timestamps
    order_timestamp = Column(DateTime, default=datetime.now)
    update_timestamp = Column(DateTime, onupdate=datetime.now)
```

**Why `margin_blocked` is critical:**
- Stores exact margin calculated at order placement
- Prevents over/under-release when execution price ≠ order price
- Ensures margin consistency across async execution

#### SandboxTrades Table

Records executed trades linked to orders.

```python
class SandboxTrades(Base):
    __tablename__ = 'sandbox_trades'

    id = Column(Integer, primary_key=True)
    tradeid = Column(String, unique=True)      # TRADE-YYYYMMDD-HHMMSS-uuid
    orderid = Column(String, nullable=False)   # Links to SandboxOrders
    user_id = Column(String, nullable=False)

    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    action = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)  # Actual execution price
    product = Column(String, nullable=False)
    strategy = Column(String)

    trade_timestamp = Column(DateTime, default=datetime.now)
```

#### SandboxPositions Table

Tracks open positions with comprehensive P&L tracking.

```python
class SandboxPositions(Base):
    __tablename__ = 'sandbox_positions'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    product = Column(String, nullable=False)

    # Position state
    quantity = Column(Integer, nullable=False)        # Positive=Long, Negative=Short
    average_price = Column(Numeric(10, 2), nullable=False)
    ltp = Column(Numeric(10, 2))                      # Last traded price (MTM)

    # P&L tracking (three separate fields)
    pnl = Column(Numeric(15, 2), default=0)           # Current unrealized P&L
    accumulated_realized_pnl = Column(Numeric(15, 2), default=0)  # All-time realized
    today_realized_pnl = Column(Numeric(15, 2), default=0)        # Today only (resets daily)
    pnl_percent = Column(Numeric(10, 4), default=0)

    # Margin tracking (CRITICAL: exact margin for this position)
    margin_blocked = Column(Numeric(15, 2), default=0)

    # Session tracking
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', 'exchange', 'product'),
    )
```

**P&L Field Semantics:**
- `pnl`: Display field for unrealized P&L (varies by context)
- `accumulated_realized_pnl`: All-time realized, never decrements
- `today_realized_pnl`: Daily realized, resets at session boundary (03:00 IST)

#### SandboxHoldings Table

T+1 settled CNC positions (delivery holdings).

```python
class SandboxHoldings(Base):
    __tablename__ = 'sandbox_holdings'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)

    quantity = Column(Integer, nullable=False)
    average_price = Column(Numeric(10, 2), nullable=False)
    ltp = Column(Numeric(10, 2))
    pnl = Column(Numeric(15, 2), default=0)
    pnl_percent = Column(Numeric(10, 4), default=0)

    settlement_date = Column(DateTime)  # When moved from position to holding

    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', 'exchange'),
    )
```

#### SandboxFunds Table

Sandbox capital management per user.

```python
class SandboxFunds(Base):
    __tablename__ = 'sandbox_funds'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)

    # Capital tracking
    total_capital = Column(Numeric(15, 2))        # Starting capital (₹1 Cr default)
    available_balance = Column(Numeric(15, 2))    # Cash available for trading
    used_margin = Column(Numeric(15, 2))          # Blocked in positions

    # P&L tracking
    realized_pnl = Column(Numeric(15, 2))         # All-time realized
    unrealized_pnl = Column(Numeric(15, 2))       # Current MTM
    total_pnl = Column(Numeric(15, 2))            # realized + unrealized

    # Reset tracking
    last_reset_date = Column(DateTime)
    reset_count = Column(Integer, default=0)
```

**Fund Balance Equation:**
```
total_capital = available_balance + used_margin + realized_pnl
```

#### SandboxDailyPnL Table

EOD snapshots for historical P&L reporting.

```python
class SandboxDailyPnL(Base):
    __tablename__ = 'sandbox_daily_pnl'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)

    realized_pnl = Column(Numeric(15, 2))
    unrealized_pnl = Column(Numeric(15, 2))
    total_pnl = Column(Numeric(15, 2))
    portfolio_value = Column(Numeric(15, 2))

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint('user_id', 'date'),
    )
```

#### SandboxConfig Table

Global configuration for all sandbox settings.

```python
class SandboxConfig(Base):
    __tablename__ = 'sandbox_config'

    id = Column(Integer, primary_key=True)
    config_key = Column(String, unique=True, nullable=False)
    config_value = Column(String, nullable=False)
    description = Column(String)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

**Default Configuration Values:**

| Key | Default | Description |
|-----|---------|-------------|
| `starting_capital` | 10000000 | ₹1 Crore sandbox capital |
| `reset_day` | Never | Weekly reset day (Never/Monday-Sunday) |
| `reset_time` | 00:00 | Reset time in IST |
| `equity_mis_leverage` | 5 | 5x leverage for equity intraday |
| `equity_cnc_leverage` | 1 | 1x for equity delivery |
| `futures_leverage` | 10 | 10x for futures |
| `option_buy_leverage` | 1 | Full premium for option buy |
| `option_sell_leverage` | 1 | Full premium for option sell |
| `nse_bse_square_off_time` | 15:15 | NSE/BSE MIS square-off |
| `cds_bcd_square_off_time` | 16:45 | Currency MIS square-off |
| `mcx_square_off_time` | 23:30 | MCX MIS square-off |
| `ncdex_square_off_time` | 17:00 | NCDEX MIS square-off |
| `order_check_interval` | 5 | Execution engine polling (seconds) |
| `mtm_update_interval` | 5 | Position MTM update (seconds) |

---

### 2. Fund Manager

**Location:** `sandbox/fund_manager.py`

Manages sandbox capital with thread-safe operations and realistic margin calculations.

```python
class FundManager:
    """Thread-safe fund management for sandbox mode"""

    _lock = threading.Lock()  # Prevents race conditions

    def __init__(self, user_id):
        self.user_id = user_id
        self.starting_capital = Decimal(get_config('starting_capital', '10000000.00'))
```

#### Margin Calculation

```python
def calculate_margin_required(self, symbol, exchange, price, quantity, product, action):
    """
    Calculate margin based on instrument type and product.

    Formula: Margin = (Quantity × Price) / Leverage

    Leverage by product/instrument:
    - Equity CNC: 1x (full payment)
    - Equity MIS: 5x (20% margin)
    - Futures: 10x (10% margin)
    - Options Buy: 1x (full premium)
    - Options Sell: 1x (full premium)
    """
    trade_value = Decimal(str(price)) * Decimal(str(quantity))

    # Determine instrument type
    is_option = self._is_option(symbol, exchange)
    is_future = self._is_future(symbol, exchange)

    # Get leverage from config
    if is_option:
        leverage = Decimal(get_config('option_buy_leverage' if action == 'BUY'
                                       else 'option_sell_leverage', '1'))
    elif is_future:
        leverage = Decimal(get_config('futures_leverage', '10'))
    elif product == 'MIS':
        leverage = Decimal(get_config('equity_mis_leverage', '5'))
    else:  # CNC
        leverage = Decimal(get_config('equity_cnc_leverage', '1'))

    margin_required = trade_value / leverage
    return margin_required.quantize(Decimal('0.01'))
```

#### Margin Block/Release Flow

```python
def block_margin(self, amount, description="Order placement"):
    """
    Block margin from available balance.
    Thread-safe with lock.
    """
    with self._lock:
        funds = self._get_or_create_funds()

        if funds.available_balance < amount:
            raise InsufficientMarginError(
                f"Required: ₹{amount}, Available: ₹{funds.available_balance}"
            )

        funds.available_balance -= amount
        funds.used_margin += amount

        db_session.commit()
        logger.info(f"Blocked ₹{amount} for {description}")

def release_margin(self, amount, realized_pnl=Decimal('0'), description="Position close"):
    """
    Release margin back to available balance.
    Also updates P&L fields.
    """
    with self._lock:
        funds = self._get_or_create_funds()

        # Release margin
        funds.used_margin -= amount
        funds.available_balance += amount

        # Update P&L
        funds.realized_pnl += realized_pnl
        funds.total_pnl = funds.realized_pnl + funds.unrealized_pnl

        db_session.commit()
        logger.info(f"Released ₹{amount}, P&L: ₹{realized_pnl}")
```

#### Margin Reconciliation

Detects and fixes margin inconsistencies.

```python
def validate_margin_consistency(self):
    """
    Verify: used_margin == sum(position.margin_blocked)
    Called after every position update.
    """
    funds = self._get_funds()

    # Sum all position margins
    position_margin_sum = db_session.query(
        func.sum(SandboxPositions.margin_blocked)
    ).filter(
        SandboxPositions.user_id == self.user_id,
        SandboxPositions.quantity != 0
    ).scalar() or Decimal('0')

    if abs(funds.used_margin - position_margin_sum) > Decimal('0.01'):
        logger.warning(
            f"Margin inconsistency detected! "
            f"Funds: ₹{funds.used_margin}, Positions: ₹{position_margin_sum}"
        )
        return False
    return True

def reconcile_margin(self, auto_fix=False):
    """
    Fix margin discrepancies by releasing stuck margin.
    """
    funds = self._get_funds()
    position_margin_sum = self._calculate_position_margin_sum()

    discrepancy = funds.used_margin - position_margin_sum

    if discrepancy > Decimal('0.01') and auto_fix:
        # Release stuck margin
        funds.used_margin = position_margin_sum
        funds.available_balance += discrepancy
        db_session.commit()
        logger.info(f"Reconciled: Released ₹{discrepancy} stuck margin")
```

#### Auto-Reset Feature

```python
def _check_and_reset_funds(self):
    """
    Check if funds need auto-reset based on config.
    Called on every get_funds() call.
    """
    reset_day = get_config('reset_day', 'Never')
    if reset_day == 'Never':
        return

    reset_time = get_config('reset_time', '00:00')
    now = datetime.now(IST)

    # Check if today is reset day and time has passed
    if now.strftime('%A') == reset_day:
        reset_hour, reset_min = map(int, reset_time.split(':'))
        reset_datetime = now.replace(hour=reset_hour, minute=reset_min, second=0)

        funds = self._get_funds()
        if funds.last_reset_date is None or funds.last_reset_date < reset_datetime:
            self._reset_funds()

def _reset_funds(self):
    """Reset to starting capital and clear all positions."""
    with self._lock:
        funds = self._get_funds()

        # Reset capital
        funds.total_capital = self.starting_capital
        funds.available_balance = self.starting_capital
        funds.used_margin = Decimal('0')
        funds.realized_pnl = Decimal('0')
        funds.unrealized_pnl = Decimal('0')
        funds.total_pnl = Decimal('0')
        funds.last_reset_date = datetime.now(IST)
        funds.reset_count += 1

        # Clear positions and holdings
        SandboxPositions.query.filter_by(user_id=self.user_id).delete()
        SandboxHoldings.query.filter_by(user_id=self.user_id).delete()

        db_session.commit()
        logger.info(f"Reset funds for user {self.user_id}, count: {funds.reset_count}")
```

---

### 3. Execution Engine

**Location:** `sandbox/execution_engine.py`

Background worker that monitors pending orders and executes them based on live market data.

```python
class ExecutionEngine:
    """
    Executes pending sandbox orders based on real market prices.
    Runs as background thread polling every 5 seconds.
    """

    def __init__(self):
        self.order_rate_limit = 10    # Max 10 orders per second
        self.api_rate_limit = 50      # Max 50 API calls per second
        self.batch_delay = 1.0        # 1 second between batches
        self.running = False
        self._thread = None
```

#### Main Execution Loop

```python
def check_and_execute_pending_orders(self):
    """
    Main execution loop - runs every 5 seconds (configurable).

    Flow:
    1. Fetch all pending orders (status='open')
    2. Group by (symbol, exchange) for efficient quote fetching
    3. Batch fetch quotes via multiquotes API
    4. Process each order respecting rate limits
    5. Execute if price conditions met
    """
    # 1. Get all pending orders
    pending_orders = SandboxOrders.query.filter_by(order_status='open').all()

    if not pending_orders:
        return

    # 2. Group by symbol for efficient API calls
    orders_by_symbol = defaultdict(list)
    for order in pending_orders:
        key = (order.symbol, order.exchange)
        orders_by_symbol[key].append(order)

    # 3. Batch fetch quotes
    symbols_list = [
        {"symbol": sym, "exchange": exch}
        for sym, exch in orders_by_symbol.keys()
    ]

    try:
        # Primary: Use multiquotes (batch API)
        quote_response = get_multiquotes(symbols_list)
        quote_cache = self._parse_multiquotes(quote_response)
    except Exception as e:
        # Fallback: Individual quotes
        logger.warning(f"Multiquotes failed: {e}, using individual quotes")
        quote_cache = self._fetch_individual_quotes(symbols_list)

    # 4. Process orders in batches (rate limiting)
    batch = []
    for order in pending_orders:
        quote = quote_cache.get((order.symbol, order.exchange))
        if quote:
            batch.append((order, quote))

        if len(batch) >= self.order_rate_limit:
            self._process_batch(batch)
            batch = []
            time.sleep(self.batch_delay)

    # Process remaining
    if batch:
        self._process_batch(batch)
```

#### Order Execution Logic by Price Type

```python
def _process_order(self, order, quote):
    """
    Determine if order should execute and at what price.

    Price types:
    - MARKET: Execute immediately at bid/ask
    - LIMIT: Execute if LTP meets limit
    - SL: Trigger at trigger_price, execute at limit
    - SL-M: Trigger at trigger_price, execute at market
    """
    ltp = Decimal(str(quote.get('ltp', 0)))
    bid = Decimal(str(quote.get('bid', ltp)))
    ask = Decimal(str(quote.get('ask', ltp)))

    should_execute = False
    execution_price = None

    if order.price_type == 'MARKET':
        # BUY at ASK, SELL at BID
        should_execute = True
        execution_price = ask if order.action == 'BUY' else bid

    elif order.price_type == 'LIMIT':
        limit_price = Decimal(str(order.price))
        if order.action == 'BUY' and ltp <= limit_price:
            should_execute = True
            execution_price = ltp  # Better than limit
        elif order.action == 'SELL' and ltp >= limit_price:
            should_execute = True
            execution_price = ltp

    elif order.price_type == 'SL':
        trigger = Decimal(str(order.trigger_price))
        limit_price = Decimal(str(order.price))

        if order.action == 'BUY' and ltp >= trigger and ltp <= limit_price:
            should_execute = True
            execution_price = ltp
        elif order.action == 'SELL' and ltp <= trigger and ltp >= limit_price:
            should_execute = True
            execution_price = ltp

    elif order.price_type == 'SL-M':
        trigger = Decimal(str(order.trigger_price))

        if order.action == 'BUY' and ltp >= trigger:
            should_execute = True
            execution_price = ask
        elif order.action == 'SELL' and ltp <= trigger:
            should_execute = True
            execution_price = bid

    if should_execute and execution_price:
        self._execute_order(order, execution_price)
```

#### Trade Execution and Position Update

```python
def _execute_order(self, order, execution_price):
    """
    Execute order: Create trade, update position, manage margin.
    """
    # Race condition protection: Check if already executed
    existing_trade = SandboxTrades.query.filter_by(orderid=order.orderid).first()
    if existing_trade:
        logger.warning(f"Order {order.orderid} already executed, skipping")
        return

    # Generate unique trade ID
    tradeid = f"TRADE-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

    # Create trade record
    trade = SandboxTrades(
        tradeid=tradeid,
        orderid=order.orderid,
        user_id=order.user_id,
        symbol=order.symbol,
        exchange=order.exchange,
        action=order.action,
        quantity=order.quantity,
        price=execution_price,
        product=order.product,
        strategy=order.strategy,
        trade_timestamp=datetime.now()
    )
    db_session.add(trade)

    # Update order status
    order.order_status = 'complete'
    order.average_price = execution_price
    order.filled_quantity = order.quantity
    order.pending_quantity = 0
    order.update_timestamp = datetime.now()

    db_session.commit()

    # Update position with netting logic
    self._update_position(order, execution_price)

    logger.info(f"Executed: {order.action} {order.quantity} {order.symbol} @ {execution_price}")

def _update_position(self, order, execution_price):
    """
    Apply position netting logic.

    Cases:
    1. NEW: No existing position → Create new
    2. SAME DIRECTION: Add to position → Average price, accumulate margin
    3. OPPOSITE DIRECTION (reduce): Partial close → Release proportional margin
    4. OPPOSITE DIRECTION (full close): Close position → Release all margin
    5. OPPOSITE DIRECTION (reversal): Close and flip → Full margin swap
    """
    fund_manager = FundManager(order.user_id)

    # Get existing position
    position = SandboxPositions.query.filter_by(
        user_id=order.user_id,
        symbol=order.symbol,
        exchange=order.exchange,
        product=order.product
    ).first()

    trade_qty = order.quantity if order.action == 'BUY' else -order.quantity
    order_margin = order.margin_blocked or Decimal('0')

    if not position or position.quantity == 0:
        # Case 1: NEW POSITION
        position = SandboxPositions(
            user_id=order.user_id,
            symbol=order.symbol,
            exchange=order.exchange,
            product=order.product,
            quantity=trade_qty,
            average_price=execution_price,
            ltp=execution_price,
            margin_blocked=order_margin,
            pnl=Decimal('0'),
            accumulated_realized_pnl=Decimal('0'),
            today_realized_pnl=Decimal('0')
        )
        db_session.add(position)

    elif (position.quantity > 0 and trade_qty > 0) or \
         (position.quantity < 0 and trade_qty < 0):
        # Case 2: SAME DIRECTION (add to position)
        old_qty = abs(position.quantity)
        new_qty = old_qty + abs(trade_qty)

        # Weighted average price
        position.average_price = (
            position.average_price * old_qty + execution_price * abs(trade_qty)
        ) / new_qty

        position.quantity += trade_qty
        position.margin_blocked += order_margin

    else:
        # Cases 3-5: OPPOSITE DIRECTION
        old_qty = abs(position.quantity)
        close_qty = min(old_qty, abs(trade_qty))

        # Calculate realized P&L
        if position.quantity > 0:  # Was long, now selling
            realized_pnl = (execution_price - position.average_price) * close_qty
        else:  # Was short, now buying
            realized_pnl = (position.average_price - execution_price) * close_qty

        # Release proportional margin
        margin_release = position.margin_blocked * (close_qty / old_qty)
        fund_manager.release_margin(margin_release, realized_pnl)

        # Update position
        position.quantity += trade_qty
        position.accumulated_realized_pnl += realized_pnl
        position.today_realized_pnl += realized_pnl
        position.margin_blocked -= margin_release

        # Case 5: REVERSAL (position flipped)
        if abs(trade_qty) > old_qty:
            remaining_qty = abs(trade_qty) - old_qty
            position.quantity = remaining_qty if trade_qty > 0 else -remaining_qty
            position.average_price = execution_price
            position.margin_blocked = order_margin * (remaining_qty / abs(trade_qty))

    position.ltp = execution_price
    position.updated_at = datetime.now()

    db_session.commit()

    # Validate margin consistency
    fund_manager.validate_margin_consistency()
```

#### Execution Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Order Execution Flow                          │
└─────────────────────────────────────────────────────────────────┘

                    Pending Order (status='open')
                              │
                              ▼
                ┌───────────────────────────┐
                │   Fetch Live Quote        │
                │   (Multiquotes API)       │
                │   Fallback: Individual    │
                └─────────────┬─────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
           ▼                  ▼                  ▼
    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │   MARKET    │   │    LIMIT    │   │   SL/SL-M   │
    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
           │                 │                  │
           │ BUY @ ASK       │ Check:           │ Check:
           │ SELL @ BID      │ BUY: LTP ≤ Px    │ Trigger hit?
           │                 │ SELL: LTP ≥ Px   │
           │                 │                  │
           ▼                 ▼                  ▼
    ┌─────────────────────────────────────────────────┐
    │              Should Execute?                     │
    │                                                  │
    │  Yes ─────────────────────────────────────────► │
    │                                                  │
    │  No ──► Keep as pending, check next cycle        │
    └──────────────────────────┬──────────────────────┘
                               │
                               ▼
                ┌───────────────────────────┐
                │   Race Condition Check    │
                │   (Trade already exists?) │
                └─────────────┬─────────────┘
                              │ No
                              ▼
                ┌───────────────────────────┐
                │   Create SandboxTrade     │
                │   Update Order status     │
                └─────────────┬─────────────┘
                              │
                              ▼
                ┌───────────────────────────┐
                │   Position Netting        │
                │                           │
                │   NEW    │ SAME  │ CLOSE  │
                │   Create │ Add   │ P&L    │
                │   margin │ avg   │ release│
                └─────────────┬─────────────┘
                              │
                              ▼
                ┌───────────────────────────┐
                │   Validate Margin         │
                │   Consistency             │
                └───────────────────────────┘
```

---

### 4. Position Manager

**Location:** `sandbox/position_manager.py`

Handles position tracking, MTM updates, session filtering, and expired contract handling.

#### MTM (Mark-to-Market) Updates

```python
def _update_positions_mtm(self):
    """
    Update all positions with live prices.
    Priority: WebSocket > Multiquotes API > Individual Quotes
    """
    positions = SandboxPositions.query.filter(
        SandboxPositions.quantity != 0
    ).all()

    if not positions:
        return

    # Build symbol list
    symbols = [{"symbol": p.symbol, "exchange": p.exchange} for p in positions]

    # Try WebSocket first (MarketDataService)
    ws_data = self._get_websocket_data(symbols)

    # Build quote cache
    quote_cache = {}
    missing_symbols = []

    for sym_info in symbols:
        key = (sym_info['symbol'], sym_info['exchange'])
        ws_quote = ws_data.get(key)

        if ws_quote and self._is_fresh(ws_quote, max_age_seconds=5):
            quote_cache[key] = ws_quote
        else:
            missing_symbols.append(sym_info)

    # Fetch missing via REST API
    if missing_symbols:
        try:
            api_quotes = get_multiquotes(missing_symbols)
            quote_cache.update(self._parse_quotes(api_quotes))
        except Exception as e:
            logger.warning(f"Multiquotes failed: {e}")
            # Individual fallback
            for sym_info in missing_symbols:
                try:
                    quote = get_quotes(sym_info['symbol'], sym_info['exchange'])
                    quote_cache[(sym_info['symbol'], sym_info['exchange'])] = quote
                except:
                    pass

    # Update positions
    for position in positions:
        quote = quote_cache.get((position.symbol, position.exchange))
        if quote:
            ltp = Decimal(str(quote.get('ltp', position.ltp)))
            position.ltp = ltp

            # Calculate unrealized P&L
            if position.quantity > 0:  # Long
                position.pnl = (ltp - position.average_price) * position.quantity
            else:  # Short
                position.pnl = (position.average_price - ltp) * abs(position.quantity)

            # P&L percentage
            if position.average_price > 0:
                position.pnl_percent = (position.pnl / (position.average_price * abs(position.quantity))) * 100

    db_session.commit()
```

#### Session Filtering

```python
def get_open_positions(self, user_id):
    """
    Get positions visible in current session.

    Session boundary: 03:00 IST (configurable via SESSION_EXPIRY_TIME)

    Filtering logic:
    - NRML: Carry forward across sessions
    - MIS: Only show if updated after last session boundary
    - CNC: Only show if not yet settled (T+1)
    """
    session_expiry = self._get_last_session_boundary()

    positions = SandboxPositions.query.filter(
        SandboxPositions.user_id == user_id,
        or_(
            SandboxPositions.quantity != 0,
            and_(
                SandboxPositions.quantity == 0,
                SandboxPositions.updated_at >= session_expiry
            )
        )
    ).all()

    # Reset today_realized_pnl if position from previous session
    for position in positions:
        if position.today_realized_pnl != 0 and position.updated_at < session_expiry:
            self._reset_today_pnl(position)

    return positions

def _get_last_session_boundary(self):
    """
    Calculate last session boundary.
    Session expires at 03:00 IST daily.
    """
    now = datetime.now(IST)
    session_hour = int(os.getenv('SESSION_EXPIRY_TIME', '03').split(':')[0])

    today_boundary = now.replace(hour=session_hour, minute=0, second=0, microsecond=0)

    if now < today_boundary:
        # Before today's boundary, use yesterday's
        return today_boundary - timedelta(days=1)
    return today_boundary

def _reset_today_pnl(self, position):
    """
    Reset today_realized_pnl without updating updated_at.
    Uses raw SQL to preserve timestamp.
    """
    db_session.execute(
        text("""
            UPDATE sandbox_positions
            SET today_realized_pnl = 0
            WHERE id = :id
        """),
        {"id": position.id}
    )
    db_session.commit()
```

#### Expired Contract Handling

```python
def _check_and_close_expired_positions(self):
    """
    Auto-close expired F&O positions.

    Settlement:
    - Options: Settle at 0 (expire worthless - conservative)
    - Futures: Settle at last LTP or average price
    """
    positions = SandboxPositions.query.filter(
        SandboxPositions.quantity != 0
    ).all()

    today = datetime.now(IST).date()

    for position in positions:
        expiry_date = self._parse_expiry_from_symbol(position.symbol)

        if expiry_date and expiry_date < today:
            self._settle_expired_position(position, expiry_date)

def _parse_expiry_from_symbol(self, symbol):
    """
    Parse expiry date from F&O symbol.

    Examples:
    - NIFTY30JAN25FUT → 30-Jan-2025
    - BANKNIFTY27FEB2548000CE → 27-Feb-2025
    """
    import re

    # Pattern: ...DDMMMYY... (e.g., 30JAN25)
    pattern = r'(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})'
    match = re.search(pattern, symbol.upper())

    if match:
        day, month, year = match.groups()
        month_num = ['JAN','FEB','MAR','APR','MAY','JUN',
                     'JUL','AUG','SEP','OCT','NOV','DEC'].index(month) + 1
        return date(2000 + int(year), month_num, int(day))

    # Fallback: Check SymToken database
    return self._get_expiry_from_symtoken(symbol)

def _settle_expired_position(self, position, expiry_date):
    """Settle expired position and release margin."""
    fund_manager = FundManager(position.user_id)

    # Settlement price
    if self._is_option(position.symbol):
        settlement_price = Decimal('0')  # Options expire worthless
    else:
        settlement_price = position.ltp or position.average_price

    # Calculate final P&L
    if position.quantity > 0:
        realized_pnl = (settlement_price - position.average_price) * position.quantity
    else:
        realized_pnl = (position.average_price - settlement_price) * abs(position.quantity)

    # Release margin and update P&L
    fund_manager.release_margin(position.margin_blocked, realized_pnl)

    # Update position
    position.accumulated_realized_pnl += realized_pnl
    position.quantity = 0
    position.margin_blocked = Decimal('0')

    # Hide position by setting updated_at to expiry date (raw SQL)
    db_session.execute(
        text("""
            UPDATE sandbox_positions
            SET updated_at = :expiry_date
            WHERE id = :id
        """),
        {"expiry_date": expiry_date, "id": position.id}
    )

    db_session.commit()
    logger.info(f"Settled expired {position.symbol}, P&L: ₹{realized_pnl}")
```

---

### 5. Square-Off Manager

**Location:** `sandbox/squareoff_manager.py`

Automatically closes MIS positions at exchange-specific timings.

```python
class SquareoffManager:
    """Auto square-off MIS positions at EOD."""

    def __init__(self):
        self.ist = pytz.timezone('Asia/Kolkata')
        self._load_square_off_times()

    def _load_square_off_times(self):
        """Load square-off times from config."""
        self.square_off_times = {
            'NSE': self._parse_time(get_config('nse_bse_square_off_time', '15:15')),
            'BSE': self._parse_time(get_config('nse_bse_square_off_time', '15:15')),
            'NFO': self._parse_time(get_config('nse_bse_square_off_time', '15:15')),
            'BFO': self._parse_time(get_config('nse_bse_square_off_time', '15:15')),
            'CDS': self._parse_time(get_config('cds_bcd_square_off_time', '16:45')),
            'BCD': self._parse_time(get_config('cds_bcd_square_off_time', '16:45')),
            'MCX': self._parse_time(get_config('mcx_square_off_time', '23:30')),
            'NCDEX': self._parse_time(get_config('ncdex_square_off_time', '17:00')),
        }
```

#### Main Square-Off Logic

```python
def check_and_square_off(self):
    """
    Main square-off check - runs every minute via APScheduler.

    Flow:
    1. Get current time (IST)
    2. Cancel all open MIS orders past square-off time
    3. Square off all MIS positions past square-off time
    """
    current_time = datetime.now(self.ist).time()

    # 1. Cancel open MIS orders
    self._cancel_open_mis_orders(current_time)

    # 2. Get all MIS positions
    mis_positions = SandboxPositions.query.filter(
        SandboxPositions.product == 'MIS',
        SandboxPositions.quantity != 0
    ).all()

    # 3. Check each position against its exchange's square-off time
    positions_to_close = []
    for position in mis_positions:
        square_off_time = self.square_off_times.get(position.exchange)

        if square_off_time and current_time >= square_off_time:
            positions_to_close.append(position)

    # 4. Execute square-off
    if positions_to_close:
        self._square_off_positions(positions_to_close)

def _cancel_open_mis_orders(self, current_time):
    """Cancel all open MIS orders past square-off time."""
    open_orders = SandboxOrders.query.filter(
        SandboxOrders.order_status == 'open',
        SandboxOrders.product == 'MIS'
    ).all()

    for order in open_orders:
        square_off_time = self.square_off_times.get(order.exchange)

        if square_off_time and current_time >= square_off_time:
            order.order_status = 'cancelled'
            order.update_timestamp = datetime.now()

            # Release blocked margin
            if order.margin_blocked:
                fund_manager = FundManager(order.user_id)
                fund_manager.release_margin(order.margin_blocked)

            logger.info(f"Cancelled MIS order {order.orderid} - past square-off time")

    db_session.commit()

def _square_off_positions(self, positions):
    """Create reverse market orders to close positions."""
    for position in positions:
        # Reverse action
        action = 'SELL' if position.quantity > 0 else 'BUY'
        quantity = abs(position.quantity)

        # Create square-off order
        order_manager = OrderManager(position.user_id)
        order_data = {
            'symbol': position.symbol,
            'exchange': position.exchange,
            'action': action,
            'quantity': quantity,
            'pricetype': 'MARKET',
            'product': 'MIS',
            'strategy': 'AUTO_SQUARE_OFF'
        }

        success, response, _ = order_manager.place_order(order_data)

        if success:
            logger.info(f"Square-off: {action} {quantity} {position.symbol}")
        else:
            logger.error(f"Square-off failed for {position.symbol}: {response}")
```

#### APScheduler Jobs

```python
def start_squareoff_scheduler(self):
    """
    Start APScheduler with multiple cron jobs.

    Jobs:
    1. Exchange-specific square-offs (4 jobs)
    2. Backup check every minute (safety net)
    3. T+1 Settlement at midnight
    4. Auto-reset (if configured)
    """
    scheduler = BackgroundScheduler(timezone=self.ist)

    # Exchange-specific square-offs
    for exchange, time_obj in self.square_off_times.items():
        scheduler.add_job(
            self._square_off_exchange,
            'cron',
            hour=time_obj.hour,
            minute=time_obj.minute,
            args=[exchange],
            id=f'squareoff_{exchange}'
        )

    # Backup check (every minute)
    scheduler.add_job(
        self.check_and_square_off,
        'interval',
        minutes=1,
        id='squareoff_backup'
    )

    # T+1 Settlement (midnight)
    scheduler.add_job(
        self._run_t1_settlement,
        'cron',
        hour=0,
        minute=0,
        id='t1_settlement'
    )

    # Auto-reset (if configured)
    reset_day = get_config('reset_day', 'Never')
    if reset_day != 'Never':
        reset_time = get_config('reset_time', '00:00')
        hour, minute = map(int, reset_time.split(':'))

        scheduler.add_job(
            self._run_auto_reset,
            'cron',
            day_of_week=self._get_day_num(reset_day),
            hour=hour,
            minute=minute,
            id='auto_reset'
        )

    scheduler.start()
    self.scheduler = scheduler
```

---

### 6. Holdings Manager

**Location:** `sandbox/holdings_manager.py`

Handles T+1 settlement and holdings MTM.

#### T+1 Settlement Process

```python
def process_t1_settlement(self):
    """
    Move settled CNC positions to holdings.
    Runs daily at midnight.

    Flow:
    1. Get all CNC positions created before today
    2. For BUY: Move to holdings, transfer margin
    3. For SELL: Credit proceeds, reduce holdings
    4. Delete settled positions
    """
    today = datetime.now(IST).date()

    # Get all CNC positions needing settlement
    cnc_positions = SandboxPositions.query.filter(
        SandboxPositions.product == 'CNC',
        SandboxPositions.quantity != 0,
        func.date(SandboxPositions.updated_at) < today
    ).all()

    for position in cnc_positions:
        fund_manager = FundManager(position.user_id)

        if position.quantity > 0:
            # BUY → Move to Holdings
            self._settle_buy_to_holdings(position, fund_manager)
        else:
            # SELL → Credit Proceeds
            self._settle_sell_proceeds(position, fund_manager)

    # Cleanup
    self._cleanup_zero_holdings()
    db_session.commit()

    logger.info(f"T+1 settlement complete: {len(cnc_positions)} positions processed")

def _settle_buy_to_holdings(self, position, fund_manager):
    """
    Move CNC BUY position to holdings.

    Margin treatment:
    - Transfer margin (don't credit to available_balance)
    - Money now represented in holdings value
    """
    # Get or create holding
    holding = SandboxHoldings.query.filter_by(
        user_id=position.user_id,
        symbol=position.symbol,
        exchange=position.exchange
    ).first()

    if holding:
        # Average existing holding
        total_qty = holding.quantity + position.quantity
        holding.average_price = (
            holding.average_price * holding.quantity +
            position.average_price * position.quantity
        ) / total_qty
        holding.quantity = total_qty
    else:
        # Create new holding
        holding = SandboxHoldings(
            user_id=position.user_id,
            symbol=position.symbol,
            exchange=position.exchange,
            quantity=position.quantity,
            average_price=position.average_price,
            ltp=position.ltp,
            settlement_date=datetime.now(IST)
        )
        db_session.add(holding)

    # Transfer margin (reduce used_margin without crediting available)
    transfer_amount = position.quantity * position.average_price
    fund_manager.transfer_margin_to_holdings(transfer_amount)

    # Delete position
    db_session.delete(position)

def _settle_sell_proceeds(self, position, fund_manager):
    """
    Process CNC SELL: Credit sale proceeds.
    """
    sell_qty = abs(position.quantity)

    # Find corresponding holding
    holding = SandboxHoldings.query.filter_by(
        user_id=position.user_id,
        symbol=position.symbol,
        exchange=position.exchange
    ).first()

    if holding:
        # Reduce holding
        holding.quantity -= sell_qty

        # Calculate realized P&L
        realized_pnl = (position.average_price - holding.average_price) * sell_qty

        # Credit sale proceeds
        sale_proceeds = position.average_price * sell_qty
        fund_manager.credit_sale_proceeds(sale_proceeds, realized_pnl)

    # Delete position
    db_session.delete(position)
```

---

### 7. Order Manager

**Location:** `sandbox/order_manager.py`

Handles order placement, modification, and cancellation.

#### Order Placement

```python
class OrderManager:
    def __init__(self, user_id):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    def place_order(self, order_data):
        """
        Place a new sandbox order.

        Flow:
        1. Validate order parameters
        2. Calculate required margin
        3. Check available balance
        4. Block margin
        5. Create order record
        6. Return orderid
        """
        # 1. Validate
        validation_result = self._validate_order(order_data)
        if not validation_result['valid']:
            return False, {'error': validation_result['error']}, 400

        # 2. Calculate margin
        price = self._get_order_price(order_data)
        margin_required = self.fund_manager.calculate_margin_required(
            symbol=order_data['symbol'],
            exchange=order_data['exchange'],
            price=price,
            quantity=int(order_data['quantity']),
            product=order_data['product'],
            action=order_data['action']
        )

        # 3. Check balance
        funds = self.fund_manager.get_funds()
        if funds['available_balance'] < margin_required:
            return False, {
                'error': f"Insufficient margin. Required: ₹{margin_required}, "
                         f"Available: ₹{funds['available_balance']}"
            }, 400

        # 4. Block margin
        self.fund_manager.block_margin(margin_required, f"Order: {order_data['symbol']}")

        # 5. Create order
        orderid = f"ORDER-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

        order = SandboxOrders(
            orderid=orderid,
            user_id=self.user_id,
            strategy=order_data.get('strategy'),
            symbol=order_data['symbol'],
            exchange=order_data['exchange'],
            action=order_data['action'],
            quantity=int(order_data['quantity']),
            price=order_data.get('price'),
            trigger_price=order_data.get('trigger_price'),
            price_type=order_data['pricetype'],
            product=order_data['product'],
            order_status='open',
            pending_quantity=int(order_data['quantity']),
            margin_blocked=margin_required,
            order_timestamp=datetime.now()
        )

        db_session.add(order)
        db_session.commit()

        logger.info(f"Order placed: {orderid}, margin blocked: ₹{margin_required}")

        return True, {'orderid': orderid, 'status': 'success'}, 200

    def _validate_order(self, order_data):
        """
        Comprehensive order validation.

        Checks:
        - Symbol exists in token database
        - Exchange is valid
        - Quantity > 0 and matches lot size
        - Price > 0 (for LIMIT/SL)
        - Trigger price > 0 (for SL)
        - Action is BUY/SELL
        - Product is valid (CNC/NRML/MIS)
        - For CNC SELL: Position must exist
        """
        errors = []

        # Required fields
        required = ['symbol', 'exchange', 'action', 'quantity', 'pricetype', 'product']
        for field in required:
            if field not in order_data or not order_data[field]:
                errors.append(f"Missing required field: {field}")

        if errors:
            return {'valid': False, 'error': ', '.join(errors)}

        # Symbol validation
        if not self._symbol_exists(order_data['symbol'], order_data['exchange']):
            return {'valid': False, 'error': f"Symbol not found: {order_data['symbol']}"}

        # Quantity validation
        qty = int(order_data['quantity'])
        if qty <= 0:
            return {'valid': False, 'error': "Quantity must be positive"}

        lot_size = self._get_lot_size(order_data['symbol'], order_data['exchange'])
        if qty % lot_size != 0:
            return {'valid': False, 'error': f"Quantity must be multiple of lot size ({lot_size})"}

        # Price validation for LIMIT/SL
        if order_data['pricetype'] in ['LIMIT', 'SL']:
            if not order_data.get('price') or float(order_data['price']) <= 0:
                return {'valid': False, 'error': "Price required for LIMIT/SL orders"}

        # Trigger price for SL
        if order_data['pricetype'] in ['SL', 'SL-M']:
            if not order_data.get('trigger_price') or float(order_data['trigger_price']) <= 0:
                return {'valid': False, 'error': "Trigger price required for SL orders"}

        # CNC SELL validation
        if order_data['product'] == 'CNC' and order_data['action'] == 'SELL':
            holding = self._get_holding(order_data['symbol'], order_data['exchange'])
            if not holding or holding.quantity < qty:
                available = holding.quantity if holding else 0
                return {'valid': False, 'error': f"Insufficient holdings. Available: {available}"}

        return {'valid': True}
```

#### Order Modification

```python
def modify_order(self, orderid, new_data):
    """
    Modify pending order.
    Only quantity, price, trigger_price can be modified.
    """
    order = SandboxOrders.query.filter_by(
        orderid=orderid,
        user_id=self.user_id,
        order_status='open'
    ).first()

    if not order:
        return False, {'error': 'Order not found or not modifiable'}, 404

    # Check what changed
    old_qty = order.quantity
    new_qty = int(new_data.get('quantity', old_qty))

    if new_qty != old_qty:
        # Recalculate margin
        price = new_data.get('price', order.price) or self._get_current_price(order)
        new_margin = self.fund_manager.calculate_margin_required(
            order.symbol, order.exchange, price, new_qty, order.product, order.action
        )

        margin_diff = new_margin - order.margin_blocked

        if margin_diff > 0:
            # Need more margin
            funds = self.fund_manager.get_funds()
            if funds['available_balance'] < margin_diff:
                return False, {'error': 'Insufficient margin for modification'}, 400
            self.fund_manager.block_margin(margin_diff)
        elif margin_diff < 0:
            # Release excess margin
            self.fund_manager.release_margin(abs(margin_diff))

        order.quantity = new_qty
        order.pending_quantity = new_qty
        order.margin_blocked = new_margin

    # Update other fields
    if 'price' in new_data:
        order.price = Decimal(str(new_data['price']))
    if 'trigger_price' in new_data:
        order.trigger_price = Decimal(str(new_data['trigger_price']))

    order.update_timestamp = datetime.now()
    db_session.commit()

    return True, {'orderid': orderid, 'status': 'modified'}, 200
```

#### Order Cancellation

```python
def cancel_order(self, orderid):
    """Cancel pending order and release margin."""
    order = SandboxOrders.query.filter_by(
        orderid=orderid,
        user_id=self.user_id,
        order_status='open'
    ).first()

    if not order:
        return False, {'error': 'Order not found or not cancellable'}, 404

    # Release blocked margin
    if order.margin_blocked:
        self.fund_manager.release_margin(order.margin_blocked)

    # Update order status
    order.order_status = 'cancelled'
    order.update_timestamp = datetime.now()

    db_session.commit()

    logger.info(f"Order cancelled: {orderid}, margin released: ₹{order.margin_blocked}")

    return True, {'orderid': orderid, 'status': 'cancelled'}, 200
```

---

### 8. API Integration

**Location:** `restx_api/analyzer.py`, `services/sandbox_service.py`

All major API endpoints check sandbox mode and route accordingly.

```python
# In restx_api endpoints
def placeorder():
    if is_sandbox_mode():
        return sandbox_place_order(order_data, api_key, original_data)
    else:
        return live_place_order(order_data, api_key)

def openposition():
    if is_sandbox_mode():
        return position_manager.get_open_positions(user_id)
    else:
        return broker_api.get_positions()

def getfunds():
    if is_sandbox_mode():
        return fund_manager.get_funds()
    else:
        return broker_api.get_funds()
```

#### Analyzer Toggle Endpoint

```python
# POST /api/v1/analyzer/toggle
def toggle_analyzer_mode(mode: bool):
    """
    Enable/disable analyzer mode.

    On Enable:
    1. Set mode in settings_db
    2. Start execution engine thread
    3. Start squareoff scheduler
    4. Run catch-up for missed settlements

    On Disable:
    1. Set mode in settings_db
    2. Stop execution engine
    3. Stop squareoff scheduler
    """
    if mode:
        set_analyze_mode(True)
        start_execution_engine()
        start_squareoff_scheduler()
        catchup_missed_settlements()
        logger.info("Analyzer mode enabled")
    else:
        set_analyze_mode(False)
        stop_execution_engine()
        stop_squareoff_scheduler()
        logger.info("Analyzer mode disabled")

    return {'status': 'success', 'mode': 'analyze' if mode else 'live'}
```

---

## Complete Order Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Complete Sandbox Order Flow                           │
└─────────────────────────────────────────────────────────────────────────────┘

User places order via API
         │
         ▼
POST /api/v1/placeorder
         │
         ▼
┌─────────────────────┐
│ is_sandbox_mode()?  │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │ True        │ False
    ▼             ▼
Sandbox       Live Broker
Service       API
    │
    ▼
┌─────────────────────┐
│ OrderManager        │
│ .place_order()      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 1. Validate order   │
│    - Symbol exists  │
│    - Qty > 0        │
│    - Lot size check │
│    - Price check    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. Calculate margin │
│    margin = value   │
│            ÷        │
│            leverage │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 3. Check balance    │
│    available >=     │
│    margin_required  │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │ Yes         │ No
    ▼             ▼
┌─────────┐   ┌─────────┐
│ Block   │   │ Reject  │
│ margin  │   │ order   │
└────┬────┘   └─────────┘
     │
     ▼
┌─────────────────────┐
│ 4. Create order     │
│    status='open'    │
│    margin_blocked=X │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Return orderid      │
└──────────┬──────────┘
           │
           ▼
┌───────────────────────────────────────────────────────────────────┐
│                  Background: Execution Engine                      │
│                                                                    │
│  Every 5 seconds:                                                  │
│  ┌─────────────────┐                                              │
│  │ 1. Get pending  │                                              │
│  │    orders       │                                              │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────┐                                              │
│  │ 2. Fetch quotes │ ← Multiquotes API (batch)                    │
│  │    (batched)    │   or individual quotes                       │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────┐                                              │
│  │ 3. Check price  │ MARKET: Execute immediately                  │
│  │    conditions   │ LIMIT: LTP vs limit                          │
│  │                 │ SL: Trigger check                            │
│  └────────┬────────┘                                              │
│           │                                                        │
│      Condition met?                                                │
│           │                                                        │
│    ┌──────┴──────┐                                                │
│    │ Yes         │ No                                             │
│    ▼             ▼                                                │
│  Execute     Keep pending                                         │
│    │                                                               │
│    ▼                                                               │
│  ┌─────────────────┐                                              │
│  │ 4. Create trade │                                              │
│  │    Update order │                                              │
│  │    status       │                                              │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────┐                                              │
│  │ 5. Update       │ NEW: Create position                         │
│  │    position     │ SAME: Average entry                          │
│  │    (netting)    │ OPPOSITE: Close/reverse                      │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────┐                                              │
│  │ 6. Margin       │ Release proportional margin                  │
│  │    adjustment   │ Update P&L                                   │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────┐                                              │
│  │ 7. Validate     │ used_margin == sum(position.margin_blocked)  │
│  │    consistency  │                                              │
│  └─────────────────┘                                              │
│                                                                    │
└───────────────────────────────────────────────────────────────────┘
```

---

## Session and Settlement Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Daily Session & Settlement Flow                           │
└─────────────────────────────────────────────────────────────────────────────┘

09:00 AM ─── Market Opens ───
         │
         │  User trades throughout day
         │  - Creates NRML, MIS, CNC positions
         │  - ExecutionEngine processes orders
         │  - MTM updates every 5 seconds
         │
         ▼
15:15 IST ─── NSE/BSE MIS Square-Off ───
         │
         │  SquareoffManager runs:
         │  1. Cancel all open MIS orders
         │  2. Create reverse MARKET orders
         │  3. Execute via ExecutionEngine
         │  4. Release margin, update P&L
         │
         ▼
16:45 IST ─── CDS/BCD MIS Square-Off ───
         │
         ▼
23:30 IST ─── MCX MIS Square-Off ───
         │
         ▼
00:00 IST ─── Midnight: T+1 Settlement ───
         │
         │  HoldingsManager runs:
         │  1. Find CNC positions from yesterday
         │  2. BUY → Move to holdings
         │  3. SELL → Credit proceeds
         │  4. Transfer margin appropriately
         │
         ▼
03:00 IST ─── Session Boundary ───
         │
         │  Session reset:
         │  1. Reset today_realized_pnl to 0
         │  2. NRML positions carry forward
         │  3. New session begins
         │
         ▼
─── Next Trading Day ───
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/sandbox_db.py` | All database models and initialization |
| `sandbox/fund_manager.py` | Capital and margin management |
| `sandbox/execution_engine.py` | Order execution background worker |
| `sandbox/position_manager.py` | Position tracking and MTM |
| `sandbox/squareoff_manager.py` | Auto square-off scheduling |
| `sandbox/holdings_manager.py` | T+1 settlement logic |
| `sandbox/order_manager.py` | Order CRUD operations |
| `sandbox/catch_up_processor.py` | Startup catch-up for missed events |
| `sandbox/execution_thread.py` | Execution engine thread management |
| `sandbox/squareoff_thread.py` | APScheduler management |
| `services/sandbox_service.py` | API integration layer |
| `services/analyzer_service.py` | Analyzer mode toggle |
| `restx_api/analyzer.py` | REST API endpoints |
| `blueprints/analyzer.py` | Web UI routes |
| `blueprints/sandbox.py` | Configuration UI routes |

---

## Configuration Blueprint

**Location:** `/sandbox` web routes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sandbox/` | GET | Configuration page |
| `/sandbox/api/configs` | GET | Get all config values |
| `/sandbox/update` | POST | Update config value |
| `/sandbox/reset` | POST | Reset all sandbox data |
| `/sandbox/reload-squareoff` | POST | Reload square-off schedule |
| `/sandbox/squareoff-status` | GET | Current square-off status |
| `/sandbox/mypnl` | GET | P&L history page |
| `/sandbox/mypnl/api/data` | GET | P&L history data (JSON) |
