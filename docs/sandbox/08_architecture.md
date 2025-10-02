# Sandbox Mode Architecture

## System Overview

The OpenAlgo Sandbox Mode is built as a modular, thread-safe system that runs parallel to the live trading infrastructure while maintaining complete isolation. This document details the architectural design and implementation.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         OpenAlgo Core                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Flask Application                       │  │
│  │                         (app.py)                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              │               │               │                   │
│              ▼               ▼               ▼                   │
│     ┌────────────┐   ┌────────────┐  ┌────────────┐           │
│     │   Live     │   │  Analyzer  │  │  Sandbox   │           │
│     │  Trading   │   │  Service   │  │  Blueprint │           │
│     └────────────┘   └────────────┘  └────────────┘           │
│                              │                                   │
└──────────────────────────────┼───────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox Mode Components                       │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                  Analyzer Service Layer                 │    │
│  │              (services/analyzer_service.py)             │    │
│  │  - Toggle analyzer mode on/off                          │    │
│  │  - Get analyzer status                                  │    │
│  │  - Start/stop execution engine                          │    │
│  │  - Start/stop squareoff scheduler                       │    │
│  └────────────────────────────────────────────────────────┘    │
│                               │                                  │
│               ┌───────────────┴───────────────┐                 │
│               ▼                               ▼                  │
│  ┌───────────────────────┐      ┌───────────────────────┐      │
│  │   Sandbox Service     │      │  Sandbox Blueprint    │      │
│  │  (sandbox_service.py) │      │  (sandbox.py)         │      │
│  │                       │      │                       │      │
│  │  - Order operations   │      │  - Web UI routes      │      │
│  │  - Position ops       │      │  - Configuration UI   │      │
│  │  - Fund management    │      │  - Settings updates   │      │
│  │  - Squareoff ops      │      │  - Status endpoints   │      │
│  └───────────────────────┘      └───────────────────────┘      │
│                               │                                  │
└───────────────────────────────┼──────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Execution       │  │   Squareoff      │  │   Order          │
│  Thread          │  │   Thread         │  │   Manager        │
│                  │  │                  │  │                  │
│  - Background    │  │  - APScheduler   │  │  - Place orders  │
│  - Check pending │  │  - Cron jobs     │  │  - Validate      │
│  - Execute when  │  │  - IST timezone  │  │  - Block margin  │
│  - conditions    │  │  - T+1 settle    │  │  - Release margin│
│    met           │  │  - Status check  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
        │                      │                      │
        └──────────────────────┴──────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Sandbox Core Modules                        │
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ Order Manager  │  │ Position Mgr   │  │  Fund Manager  │   │
│  │                │  │                │  │                │   │
│  │ - Create order │  │ - Update pos   │  │ - Calculate    │   │
│  │ - Validate     │  │ - Calculate    │  │   margin       │   │
│  │ - Block margin │  │   P&L          │  │ - Available    │   │
│  │ - Execute      │  │ - MTM update   │  │   funds        │   │
│  │ - Cancel       │  │ - Close pos    │  │ - Reset funds  │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ Execution Eng  │  │ Squareoff Mgr  │  │ Trade Manager  │   │
│  │                │  │                │  │                │   │
│  │ - Check orders │  │ - Cancel MIS   │  │ - Create trade │   │
│  │ - Get LTP      │  │   orders       │  │ - Tradebook    │   │
│  │ - Trigger exec │  │ - Close MIS    │  │ - Statistics   │   │
│  │ - Update pos   │  │   positions    │  │                │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Sandbox Database (db/sandbox.db)             │  │
│  │                                                            │  │
│  │  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐ │  │
│  │  │sandbox_orders │  │sandbox_trades │  │sandbox_      │ │  │
│  │  │               │  │               │  │positions     │ │  │
│  │  └───────────────┘  └───────────────┘  └──────────────┘ │  │
│  │                                                            │  │
│  │  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐ │  │
│  │  │sandbox_       │  │sandbox_funds  │  │sandbox_      │ │  │
│  │  │holdings       │  │               │  │config        │ │  │
│  │  └───────────────┘  └───────────────┘  └──────────────┘ │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Database Models (database/sandbox_db.py)       │  │
│  │  - SandboxOrders                                          │  │
│  │  - SandboxTrades                                          │  │
│  │  - SandboxPositions                                       │  │
│  │  - SandboxHoldings                                        │  │
│  │  - SandboxFunds                                           │  │
│  │  - SandboxConfig                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   External Integrations                          │
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ Quotes Service │  │ Symbol Service │  │ Market Data    │   │
│  │                │  │                │  │                │   │
│  │ - Get LTP      │  │ - Lot size     │  │ - Historical   │   │
│  │ - Real-time    │  │ - Tick size    │  │ - OHLCV        │   │
│  │   quotes       │  │ - Instrument   │  │                │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Analyzer Service Layer

**File**: `services/analyzer_service.py`
**Lines**: 244 lines

**Purpose**: Central service for toggling and managing analyzer/sandbox mode.

**Key Functions**:
- `toggle_analyzer_mode()`: Enable/disable sandbox mode
- `get_analyzer_status()`: Check current mode status
- Thread lifecycle management (start/stop execution and squareoff)

**Implementation**:
```python
def toggle_analyzer_mode_with_auth(
    analyzer_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Toggle analyzer mode on/off"""
    new_mode = analyzer_data.get('mode', False)
    set_analyze_mode(new_mode)

    if new_mode:
        # Start both threads when analyzer mode enabled
        start_execution_engine()
        start_squareoff_scheduler()
    else:
        # Stop both threads when analyzer mode disabled
        stop_execution_engine()
        stop_squareoff_scheduler()
```

### 2. Sandbox Service Layer

**File**: `services/sandbox_service.py`
**Lines**: ~716 lines

**Purpose**: Main service layer for all sandbox operations.

**Key Sections**:

#### Order Operations (lines 1-250)
- `sandbox_place_order()`: Place sandbox orders
- `sandbox_modify_order()`: Modify pending orders
- `sandbox_cancel_order()`: Cancel specific order
- `sandbox_cancel_all_orders()`: Cancel all pending orders

#### Position Operations (lines 251-450)
- `sandbox_get_positions()`: Retrieve all positions
- `sandbox_close_position()`: Close specific position
- `sandbox_update_mtm()`: Update mark-to-market

#### Fund Operations (lines 451-550)
- `sandbox_get_funds()`: Get fund details
- `sandbox_reset_funds()`: Reset to starting capital

#### Squareoff Operations (lines 551-650)
- `sandbox_reload_squareoff_schedule()`: Reload schedule
- `sandbox_get_squareoff_status()`: Get scheduler status

#### Smart Order Operations (lines 651-716)
- `sandbox_place_smartorder()`: Place position-sizing orders

**Error Handling Pattern**:
```python
try:
    # Operation logic
    result = perform_operation()
    return True, result, 200
except Exception as e:
    logger.error(f"Error: {e}", exc_info=True)
    return False, {'status': 'error', 'message': str(e)}, 500
```

### 3. Execution Thread

**File**: `sandbox/execution_thread.py`
**Lines**: ~200 lines

**Purpose**: Background thread that checks and executes pending orders.

**Architecture**:
```python
# Global state
_execution_thread = None
_execution_running = False
_execution_lock = threading.Lock()

def start_execution_engine():
    """Start background execution thread"""
    global _execution_thread, _execution_running

    with _execution_lock:
        if _execution_running:
            return

        _execution_running = True
        _execution_thread = threading.Thread(
            target=_execution_loop,
            daemon=True,
            name="SandboxExecutionThread"
        )
        _execution_thread.start()

def _execution_loop():
    """Main execution loop"""
    while _execution_running:
        try:
            # Check interval from config (default 5 seconds)
            check_interval = get_config('order_check_interval', 5)

            # Process pending orders
            _check_and_execute_pending_orders()

            # Sleep until next check
            time.sleep(check_interval)

        except Exception as e:
            logger.error(f"Execution loop error: {e}")
            time.sleep(5)  # Wait before retry
```

**Order Processing**:
```python
def _check_and_execute_pending_orders():
    """Check all pending orders and execute if conditions met"""
    pending_orders = SandboxOrders.query.filter_by(
        order_status='open'
    ).all()

    for order in pending_orders:
        try:
            # Get current LTP
            ltp = get_quotes(order.symbol, order.exchange)['ltp']

            # Check execution conditions
            if should_execute(order, ltp):
                execute_order(order, ltp)

        except Exception as e:
            logger.error(f"Error checking order {order.orderid}: {e}")
```

### 4. Squareoff Thread

**File**: `sandbox/squareoff_thread.py`
**Lines**: 218 lines

**Purpose**: Separate thread using APScheduler for time-based MIS square-off and T+1 settlement.

**Architecture**:
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Global scheduler state
_scheduler = None
_scheduler_running = False
_scheduler_lock = threading.Lock()

def start_squareoff_scheduler():
    """Start APScheduler with cron jobs for each exchange"""
    global _scheduler, _scheduler_running

    with _scheduler_lock:
        if _scheduler_running:
            return True

        try:
            # Create scheduler
            _scheduler = BackgroundScheduler(
                timezone=IST,
                daemon=True,
                job_defaults={
                    'coalesce': True,  # Combine missed runs
                    'max_instances': 1,  # One job at a time
                }
            )

            # Load square-off times from config
            _load_squareoff_jobs()

            # Start scheduler
            _scheduler.start()
            _scheduler_running = True

            return True

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            return False
```

**Dynamic Job Loading**:
```python
def _load_squareoff_jobs():
    """Load square-off jobs from config"""
    # Exchange time mappings
    exchanges_config = {
        'NSE_BSE': 'nse_bse_square_off_time',
        'CDS_BCD': 'cds_bcd_square_off_time',
        'MCX': 'mcx_square_off_time',
        'NCDEX': 'ncdex_square_off_time'
    }

    for exchange_group, config_key in exchanges_config.items():
        # Get time from config (e.g., "15:15")
        time_str = get_config(config_key, "15:15")
        hour, minute = map(int, time_str.split(':'))

        # Create cron trigger in IST
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=IST
        )

        # Add job
        _scheduler.add_job(
            func=_squareoff_exchange_group,
            trigger=trigger,
            args=[exchange_group],
            id=f'squareoff_{exchange_group}',
            replace_existing=True,
            misfire_grace_time=300  # 5 minutes grace
        )
```

**T+1 Settlement Job** (lines 99-122):
```python
# Schedule T+1 settlement at midnight (00:00 IST)
from sandbox.position_manager import process_all_users_settlement

settlement_trigger = CronTrigger(
    hour=0,
    minute=0,
    timezone=IST
)

settlement_job = scheduler.add_job(
    func=process_all_users_settlement,
    trigger=settlement_trigger,
    id='t1_settlement',
    name='T+1 Settlement (CNC to Holdings)',
    replace_existing=True,
    misfire_grace_time=300
)

# This job:
# - Runs at midnight (00:00 IST) daily
# - Moves CNC positions to holdings
# - Auto squares-off any remaining MIS positions
# - NRML positions carry forward
```

**Auto-Reset Job** (lines 124-158):
```python
# Schedule auto-reset based on configured reset day and time
from sandbox.fund_manager import reset_all_user_funds

reset_day = get_config('reset_day', 'Sunday')
reset_time_str = get_config('reset_time', '00:00')
reset_hour, reset_minute = map(int, reset_time_str.split(':'))

# Map day names to APScheduler day_of_week values
day_mapping = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6
}

reset_trigger = CronTrigger(
    day_of_week=day_mapping.get(reset_day, 6),  # Default to Sunday
    hour=reset_hour,
    minute=reset_minute,
    timezone=IST
)

reset_job = scheduler.add_job(
    func=reset_all_user_funds,
    trigger=reset_trigger,
    id='auto_reset',
    name=f'Auto-Reset Funds ({reset_day} {reset_time_str})',
    replace_existing=True,
    misfire_grace_time=300
)

# This job:
# - Runs at configured day/time (default: Sunday 00:00 IST)
# - Resets all user funds to starting capital
# - Clears all positions, holdings, orders, and trades
# - Automatically reloads when reset_day or reset_time config changes
# - Works even if app was stopped during reset time (misfire_grace_time)
```

**Reload Without Restart**:
```python
def reload_squareoff_schedule():
    """Reload schedule from config without restart"""
    global _scheduler

    with _scheduler_lock:
        if not _scheduler_running or not _scheduler:
            return False, "Scheduler not running"

        try:
            # Remove all existing jobs
            _scheduler.remove_all_jobs()

            # Reload from config
            _load_squareoff_jobs()

            return True, "Schedule reloaded successfully"

        except Exception as e:
            return False, f"Failed to reload: {e}"
```

### 5. Order Manager

**File**: `sandbox/order_manager.py`
**Lines**: ~600 lines

**Purpose**: Core logic for order validation, margin blocking, and order lifecycle.

**Key Sections**:

#### Helper Functions (lines 33-44)
```python
def is_option(symbol, exchange):
    """Check if symbol is an option based on exchange and suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('CE') or symbol.endswith('PE')
    return False

def is_future(symbol, exchange):
    """Check if symbol is a future based on exchange and suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('FUT')
    return False
```

#### Price Selection for Margin (lines 153-207)
```python
def _get_margin_calculation_price(order_data, ltp):
    """Get appropriate price for margin calculation"""
    price_type = order_data['price_type']

    if price_type == 'MARKET':
        # Use current LTP
        return ltp
    elif price_type == 'LIMIT':
        # Use order's limit price
        return order_data['price']
    elif price_type in ['SL', 'SL-M']:
        # Use trigger price
        return order_data['trigger_price']
    else:
        # Fallback to LTP
        return ltp
```

#### Margin Blocking Logic (lines 225-262)
```python
def should_block_margin(action, product, symbol, exchange):
    """Determine if margin should be blocked for this order"""

    # BUY orders always block margin
    if action == 'BUY':
        return True

    # SELL orders: depends on instrument type
    if action == 'SELL':
        # Options: Selling options requires margin
        if is_option(symbol, exchange):
            return True

        # Futures: Selling futures requires margin
        if is_future(symbol, exchange):
            return True

        # Equity MIS/NRML: Shorting requires margin
        if product in ['MIS', 'NRML']:
            return True

    return False
```

#### Order Cancellation (lines 477-537)
```python
def cancel_order(orderid, user_id):
    """Cancel order and release margin"""
    order = SandboxOrders.query.filter_by(
        orderid=orderid,
        user_id=user_id
    ).first()

    if not order:
        return False, "Order not found"

    if order.order_status != 'open':
        return False, "Only pending orders can be cancelled"

    try:
        # Release margin if it was blocked
        if order.margin_blocked and order.margin_blocked > 0:
            fund = SandboxFunds.query.filter_by(user_id=user_id).first()
            if fund:
                fund.available_balance += order.margin_blocked
                fund.used_margin -= order.margin_blocked
                fund.updated_at = datetime.now(IST)

        # Update order status
        order.order_status = 'cancelled'
        order.update_timestamp = datetime.now(IST)

        db_session.commit()
        return True, "Order cancelled successfully"

    except Exception as e:
        db_session.rollback()
        logger.error(f"Error cancelling order: {e}")
        return False, str(e)
```

### 6. Position Manager

**File**: `sandbox/position_manager.py`
**Lines**: ~680 lines

**Purpose**: Manage position updates, P&L calculations, position closure, and T+1 settlement.

**Key Functions**:

#### Position Update (lines 50-180)
```python
def update_position(trade_data, user_id):
    """Update position based on trade"""
    position = SandboxPositions.query.filter_by(
        user_id=user_id,
        symbol=trade_data['symbol'],
        exchange=trade_data['exchange'],
        product=trade_data['product']
    ).first()

    if not position:
        # Create new position
        position = SandboxPositions(
            user_id=user_id,
            symbol=trade_data['symbol'],
            exchange=trade_data['exchange'],
            product=trade_data['product'],
            quantity=0,
            average_price=0.00,
            created_at=datetime.now(IST)
        )
        db_session.add(position)

    # Calculate new quantity and average price
    old_qty = position.quantity
    old_avg = position.average_price
    trade_qty = trade_data['quantity']
    trade_price = trade_data['price']

    if trade_data['action'] == 'BUY':
        new_qty = old_qty + trade_qty
    else:  # SELL
        new_qty = old_qty - trade_qty

    # Update average price
    if new_qty != 0:
        if (old_qty >= 0 and new_qty > old_qty) or \
           (old_qty <= 0 and new_qty < old_qty):
            # Increasing position
            total_value = (old_qty * old_avg) + (trade_qty * trade_price)
            position.average_price = abs(total_value / new_qty)

    position.quantity = new_qty
    position.updated_at = datetime.now(IST)

    db_session.commit()
```

#### P&L Calculation (lines 250-320)
```python
def calculate_pnl(position, ltp):
    """Calculate P&L for position"""
    if position.quantity == 0:
        return 0.00, 0.00

    if position.quantity > 0:
        # Long position
        pnl = (ltp - position.average_price) * position.quantity
    else:
        # Short position
        pnl = (position.average_price - ltp) * abs(position.quantity)

    # Calculate percentage
    investment = position.average_price * abs(position.quantity)
    pnl_percent = (pnl / investment * 100) if investment > 0 else 0.00

    return round(pnl, 2), round(pnl_percent, 4)
```

#### Tradebook Formatting (lines 402-421)
```python
def format_tradebook(trades):
    """Format trades for display"""
    formatted_trades = []

    for trade in trades:
        price = round(trade.price, 2)
        trade_value = round(price * trade.quantity, 2)  # Round to 2 decimals

        formatted_trades.append({
            'symbol': trade.symbol,
            'exchange': trade.exchange,
            'action': trade.action,
            'quantity': trade.quantity,
            'average_price': round(price, 2),
            'price': round(price, 2),
            'trade_value': trade_value,
            'product': trade.product,
            'trade_timestamp': trade.trade_timestamp.strftime('%d-%b-%Y %H:%M:%S')
        })
```

#### T+1 Settlement (lines 584-619)
```python
def process_all_users_settlement():
    """
    Process T+1 settlement for all users at midnight (00:00 IST)
    - Moves CNC positions to holdings
    - Auto squares-off any remaining MIS positions
    - NRML positions carry forward
    """
    positions = SandboxPositions.query.all()
    users = set(p.user_id for p in positions)

    for user_id in users:
        pm = PositionManager(user_id)
        pm.process_session_settlement()

    # Called by APScheduler at midnight
    # File: sandbox/squareoff_thread.py (lines 99-122)
```

#### Catch-up Settlement (lines 622-674)
```python
def catchup_missed_settlements():
    """
    Catch-up settlement for positions that should have been settled
    while app was stopped. Runs on startup when analyzer mode is enabled.
    """
    # Find CNC positions older than 1 day
    cutoff_time = datetime.now() - timedelta(days=1)

    cnc_positions = SandboxPositions.query.filter_by(product='CNC').all()
    positions_to_settle = [
        p for p in cnc_positions
        if p.quantity != 0 and p.created_at < cutoff_time
    ]

    if positions_to_settle:
        logger.info(f"Found {len(positions_to_settle)} CNC positions for catch-up")

        users = set(p.user_id for p in positions_to_settle)
        for user_id in users:
            pm = PositionManager(user_id)
            pm.process_session_settlement()

    # Called on app startup (app.py:347-353)
    # Called when toggling analyzer mode (analyzer_service.py:107-113)
```

**Settlement Layers**:
1. **Scheduled Settlement**: Midnight (00:00 IST) via APScheduler
2. **Startup Catch-up**: When app starts with analyzer mode ON
3. **Toggle Catch-up**: When user enables analyzer mode

### 7. Fund Manager

**File**: `sandbox/fund_manager.py`
**Lines**: ~400 lines

**Purpose**: Handle margin calculations, fund updates, and leverage rules.

**Key Sections**:

#### Leverage Calculation (lines 299-349)
```python
def _get_leverage(symbol, exchange, product):
    """Get leverage based on instrument type and product"""

    # Equity (NSE, BSE)
    if exchange in ['NSE', 'BSE']:
        if product == 'MIS':
            return get_config('equity_mis_leverage', 5)
        elif product == 'CNC':
            return get_config('equity_cnc_leverage', 1)
        else:  # NRML
            return get_config('equity_cnc_leverage', 1)

    # Derivatives
    if exchange in ['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCDEX']:
        # Options buying
        if is_option(symbol, exchange):
            if action == 'BUY':
                return 1  # Full premium required
            else:  # SELL
                return get_config('option_sell_leverage', 10)

        # Futures
        if is_future(symbol, exchange):
            return get_config('futures_leverage', 10)

    # Default
    return 1
```

#### Margin Calculation (lines 150-250)
```python
def calculate_margin(order_data, ltp):
    """Calculate margin required for order"""
    symbol = order_data['symbol']
    exchange = order_data['exchange']
    action = order_data['action']
    product = order_data['product']
    quantity = order_data['quantity']

    # Get price for margin calculation
    margin_price = _get_margin_calculation_price(order_data, ltp)

    # Get leverage
    leverage = _get_leverage(symbol, exchange, product)

    # Calculate base value
    if is_option(symbol, exchange) and action == 'BUY':
        # Option buying: Full premium
        lot_size = get_lot_size(symbol, exchange)
        margin = margin_price * lot_size * quantity
    elif is_future(symbol, exchange):
        # Futures: Contract value / leverage
        lot_size = get_lot_size(symbol, exchange)
        contract_value = margin_price * lot_size * quantity
        margin = contract_value / leverage
    else:
        # Equity: Trade value / leverage
        trade_value = margin_price * quantity
        margin = trade_value / leverage

    return round(margin, 2)
```

#### Auto-Reset Functions (lines 353-385)
```python
def reset_all_user_funds():
    """
    Reset funds for all users (called by APScheduler)
    This runs at configured reset day/time (default: Sunday 00:00 IST)
    """
    logger.info("=== AUTO-RESET: Starting scheduled fund reset for all users ===")

    # Get all unique user IDs from funds table
    all_funds = SandboxFunds.query.all()

    if not all_funds:
        logger.info("No user funds to reset")
        return

    reset_count = 0
    for fund in all_funds:
        try:
            # Create FundManager for this user
            fm = FundManager(fund.user_id)

            # Call the internal reset function
            fm._reset_funds(fund)
            reset_count += 1

        except Exception as e:
            logger.error(f"Error resetting funds for user {fund.user_id}: {e}")
            continue

    logger.info(f"=== AUTO-RESET: Successfully reset {reset_count} user fund accounts ===")

# This function:
# - Runs automatically via APScheduler at configured day/time
# - Resets all user funds to starting capital
# - Clears all positions and holdings for each user
# - Increments reset_count for tracking
# - Works even if app was stopped during reset time (misfire_grace_time=300s)
```

### 8. Execution Engine

**File**: `sandbox/execution_engine.py`
**Lines**: ~450 lines

**Purpose**: Execute orders when trigger conditions are met.

**Order Execution Logic** (lines 150-200):
```python
def check_and_execute(order):
    """Check if order should execute and execute it"""
    try:
        # Get current LTP
        ltp = get_quotes(order.symbol, order.exchange)['ltp']

        should_execute = False
        execution_price = ltp

        # Check execution conditions based on order type
        if order.price_type == 'MARKET':
            # Already executed at placement
            return

        elif order.price_type == 'LIMIT':
            # Execute at LTP when it crosses limit price
            if order.action == 'BUY' and ltp <= order.price:
                should_execute = True
                execution_price = ltp  # Execute at LTP, not limit price
            elif order.action == 'SELL' and ltp >= order.price:
                should_execute = True
                execution_price = ltp

        elif order.price_type == 'SL':
            # Trigger at trigger_price, then execute at LTP
            if order.action == 'BUY' and ltp >= order.trigger_price:
                should_execute = True
                execution_price = ltp
            elif order.action == 'SELL' and ltp <= order.trigger_price:
                should_execute = True
                execution_price = ltp

        elif order.price_type == 'SL-M':
            # Same as SL for execution
            if order.action == 'BUY' and ltp >= order.trigger_price:
                should_execute = True
                execution_price = ltp
            elif order.action == 'SELL' and ltp <= order.trigger_price:
                should_execute = True
                execution_price = ltp

        if should_execute:
            execute_order(order, execution_price)

    except Exception as e:
        logger.error(f"Error checking order {order.orderid}: {e}")
```

### 9. Squareoff Manager

**File**: `sandbox/squareoff_manager.py`
**Lines**: ~250 lines

**Purpose**: Handle auto square-off of MIS positions.

**Square-off Process** (lines 50-150):
```python
def check_and_square_off(exchange_group):
    """Square off all MIS positions for exchange group"""
    logger.info(f"Starting square-off for {exchange_group}")

    # Map exchange group to actual exchanges
    exchange_map = {
        'NSE_BSE': ['NSE', 'BSE', 'NFO', 'BFO'],
        'CDS_BCD': ['CDS', 'BCD'],
        'MCX': ['MCX'],
        'NCDEX': ['NCDEX']
    }

    exchanges = exchange_map.get(exchange_group, [])

    try:
        # Step 1: Cancel all pending MIS orders
        _cancel_open_mis_orders(exchanges)

        # Step 2: Close all MIS positions
        _close_mis_positions(exchanges)

        logger.info(f"Square-off completed for {exchange_group}")

    except Exception as e:
        logger.error(f"Error in square-off for {exchange_group}: {e}")
```

**Cancel Pending Orders** (lines 101-144):
```python
def _cancel_open_mis_orders(exchanges):
    """Cancel all open MIS orders for exchanges"""
    for exchange in exchanges:
        orders = SandboxOrders.query.filter_by(
            order_status='open',
            product='MIS',
            exchange=exchange
        ).all()

        for order in orders:
            try:
                # Release margin
                if order.margin_blocked and order.margin_blocked > 0:
                    fund = SandboxFunds.query.filter_by(
                        user_id=order.user_id
                    ).first()

                    if fund:
                        fund.available_balance += order.margin_blocked
                        fund.used_margin -= order.margin_blocked
                        fund.updated_at = datetime.now(IST)

                # Cancel order
                order.order_status = 'cancelled'
                order.rejection_reason = 'Auto-cancelled at square-off time'
                order.update_timestamp = datetime.now(IST)

                logger.info(f"Cancelled MIS order {order.orderid}")

            except Exception as e:
                logger.error(f"Error cancelling order {order.orderid}: {e}")

        db_session.commit()
```

**Close Positions** (lines 145-200):
```python
def _close_mis_positions(exchanges):
    """Close all MIS positions for exchanges"""
    for exchange in exchanges:
        positions = SandboxPositions.query.filter_by(
            product='MIS',
            exchange=exchange
        ).filter(
            SandboxPositions.quantity != 0
        ).all()

        for position in positions:
            try:
                # Get current LTP
                ltp = get_quotes(position.symbol, position.exchange)['ltp']

                # Create reverse order
                reverse_action = 'SELL' if position.quantity > 0 else 'BUY'
                reverse_qty = abs(position.quantity)

                # Execute at MARKET (LTP)
                order_data = {
                    'symbol': position.symbol,
                    'exchange': position.exchange,
                    'action': reverse_action,
                    'quantity': reverse_qty,
                    'price_type': 'MARKET',
                    'product': 'MIS',
                    'price': ltp
                }

                # Execute immediately
                execute_squareoff_order(order_data, position.user_id, ltp)

                logger.info(f"Squared off MIS position {position.symbol}")

            except Exception as e:
                logger.error(f"Error squaring off {position.symbol}: {e}")
```

## Thread Management

### Thread Lifecycle

```python
# Application Startup (app.py lines 325-355)
if get_analyze_mode():
    logger.info("Analyzer mode is ON - starting background threads")
    from sandbox.execution_thread import start_execution_engine
    from sandbox.squareoff_thread import start_squareoff_scheduler
    from sandbox.position_manager import catchup_missed_settlements

    # Start execution engine for order processing
    start_execution_engine()

    # Start squareoff scheduler for MIS auto-squareoff and T+1 settlement
    start_squareoff_scheduler()

    # Run catch-up settlement for any CNC positions that missed settlement
    # while app was stopped (e.g., stopped for days/weeks)
    catchup_missed_settlements()
    logger.info("Catch-up settlement check completed on startup")

# Catch-up Settlement Logic:
# - Finds CNC positions older than 1 day
# - Automatically settles them to holdings
# - Ensures holdings are accurate even after extended downtime
```

### Thread Safety

All sandbox components use thread-safe patterns:

1. **Thread Locks**: Prevent concurrent modification
```python
_execution_lock = threading.Lock()

with _execution_lock:
    if _execution_running:
        return
    _execution_running = True
```

2. **Database Session Management**: Each thread uses scoped sessions
```python
from database.sandbox_db import db_session

try:
    # Database operations
    db_session.commit()
except:
    db_session.rollback()
finally:
    db_session.close()
```

3. **APScheduler Configuration**: Prevents job overlap
```python
job_defaults = {
    'coalesce': True,  # Combine missed runs
    'max_instances': 1,  # Only one instance at a time
    'misfire_grace_time': 300  # 5 minutes tolerance
}
```

## Database Architecture

### Connection Management

```python
# database/sandbox_db.py
import os
from dotenv import load_dotenv

load_dotenv()
SANDBOX_DATABASE_URL = os.getenv(
    'SANDBOX_DATABASE_URL',
    'sqlite:///db/sandbox.db'
)

engine = create_engine(SANDBOX_DATABASE_URL)
Session = scoped_session(sessionmaker(bind=engine))
db_session = Session()
```

### Table Relationships

```
sandbox_orders (1) -----> (N) sandbox_trades
      │
      │ (orderid)
      │
      └──> Creates trade entries when executed

sandbox_trades (N) -----> (1) sandbox_positions
      │
      │ (user_id, symbol, exchange, product)
      │
      └──> Updates position on each trade

sandbox_positions (1) -----> (1) sandbox_holdings
      │
      │ (CNC positions after T+1)
      │
      └──> Moves to holdings after settlement

sandbox_orders/positions (N) -----> (1) sandbox_funds
      │
      │ (user_id)
      │
      └──> Updates funds on order/position changes
```

## Integration Points

### 1. Quotes Service Integration

```python
from services.quotes_service import get_quotes

# Get real-time LTP
success, response, status_code = get_quotes(
    symbol="RELIANCE",
    exchange="NSE",
    auth_token=auth_token,
    broker=broker
)

ltp = response['data']['ltp']
```

### 2. Symbol Service Integration

```python
from services.symbol_service import get_symbol_info

# Get lot size and instrument details
success, response, status_code = get_symbol_info(
    symbol="NIFTY25JAN25000FUT",
    exchange="NFO",
    auth_token=auth_token,
    broker=broker
)

lot_size = response['data']['lotsize']
```

### 3. Web UI Integration

```python
# blueprints/sandbox.py
@sandbox_bp.route('/update', methods=['POST'])
@check_session_validity
def update_config():
    """Update sandbox configuration"""
    data = request.get_json()

    # Update config
    success = set_config(
        data['config_key'],
        data['config_value']
    )

    # Auto-reload square-off if time changed
    if data['config_key'].endswith('square_off_time'):
        from services.sandbox_service import sandbox_reload_squareoff_schedule
        sandbox_reload_squareoff_schedule()

    return jsonify({'status': 'success'})
```

## Configuration Management

### Config Storage

```python
# database/sandbox_db.py
class SandboxConfig(Base):
    __tablename__ = 'sandbox_config'

    id = Column(Integer, primary_key=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime, default=datetime.now)
```

### Config Access

```python
def get_config(key, default=None):
    """Get configuration value"""
    config = SandboxConfig.query.filter_by(config_key=key).first()
    if config:
        return config.config_value
    return default

def set_config(key, value):
    """Set configuration value"""
    config = SandboxConfig.query.filter_by(config_key=key).first()
    if config:
        config.config_value = value
        config.updated_at = datetime.now(IST)
    else:
        config = SandboxConfig(
            config_key=key,
            config_value=value,
            updated_at=datetime.now(IST)
        )
        db_session.add(config)

    db_session.commit()
```

## Performance Considerations

### 1. Query Optimization

```python
# Use indexes for frequent queries
# database/sandbox_db.py

# Order queries
Index('idx_orderid', SandboxOrders.orderid)
Index('idx_user_status', SandboxOrders.user_id, SandboxOrders.order_status)
Index('idx_symbol_exchange', SandboxOrders.symbol, SandboxOrders.exchange)

# Position queries
Index('idx_position_user', SandboxPositions.user_id)
Index('idx_user_symbol', SandboxPositions.user_id, SandboxPositions.symbol)
```

### 2. Batch Processing

```python
# Process orders in batches to respect rate limits
MAX_ORDERS_PER_BATCH = 10  # ORDER_RATE_LIMIT
BATCH_DELAY = 1.0  # 1 second between batches

for i in range(0, len(pending_orders), MAX_ORDERS_PER_BATCH):
    batch = pending_orders[i:i + MAX_ORDERS_PER_BATCH]

    # Process batch
    for order in batch:
        check_and_execute_order(order)

    # Wait before next batch
    if i + MAX_ORDERS_PER_BATCH < len(pending_orders):
        time.sleep(BATCH_DELAY)
```

### 3. Connection Pooling

```python
# database/sandbox_db.py
engine = create_engine(
    SANDBOX_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600  # Recycle connections after 1 hour
)
```

## Error Handling Patterns

### 1. Try-Except with Rollback

```python
try:
    # Database operations
    order.order_status = 'complete'
    db_session.commit()
except Exception as e:
    db_session.rollback()
    logger.error(f"Error: {e}", exc_info=True)
    raise
```

### 2. Graceful Degradation

```python
def get_quotes_with_fallback(symbol, exchange):
    """Get quotes with fallback to last known price"""
    try:
        response = get_quotes(symbol, exchange)
        return response['data']['ltp']
    except Exception as e:
        logger.warning(f"Failed to get live quote, using last known: {e}")
        # Return last known LTP from position/order
        return get_last_known_price(symbol, exchange)
```

### 3. Retry Logic

```python
def execute_with_retry(func, max_retries=3, delay=1):
    """Execute function with retry logic"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
            time.sleep(delay)
```

## Logging Strategy

### 1. Log Levels

```python
# DEBUG: Detailed information for debugging
logger.debug(f"Checking order {orderid} with LTP {ltp}")

# INFO: General operational messages
logger.info(f"Order {orderid} executed at {execution_price}")

# WARNING: Warning messages for recoverable issues
logger.warning(f"Failed to get quote for {symbol}, using last known price")

# ERROR: Error messages for failures
logger.error(f"Failed to execute order {orderid}: {e}", exc_info=True)
```

### 2. Log Format

```python
# utils/logging.py
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.FileHandler('logs/sandbox.log'),
        logging.StreamHandler()
    ]
)
```

## Deployment Considerations

### 1. Environment Variables

```bash
# .env
VERSION=1.0.4
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db
API_RATE_LIMIT=50 per second
ORDER_RATE_LIMIT=10 per second
SMART_ORDER_RATE_LIMIT=2 per second
SMART_ORDER_DELAY=0.5
```

### 2. Database Migrations

```bash
# Run sandbox migration
cd openalgo
uv run upgrade/migrate_sandbox.py

# Or using Python directly
python upgrade/migrate_sandbox.py
```

### 3. Monitoring

```python
# Monitor thread health
def check_thread_health():
    """Check if threads are running properly"""
    execution_healthy = is_execution_thread_running()
    squareoff_healthy = is_squareoff_scheduler_running()

    if not execution_healthy:
        logger.error("Execution thread not running!")
        # Alert or restart

    if not squareoff_healthy:
        logger.error("Squareoff scheduler not running!")
        # Alert or restart
```

## Summary

The Sandbox Mode architecture is designed with the following principles:

1. **Isolation**: Complete separation from live trading
2. **Modularity**: Each component has a single responsibility
3. **Thread Safety**: Proper locking and session management
4. **Scalability**: Efficient batch processing and connection pooling
5. **Maintainability**: Clear code structure and comprehensive logging
6. **Reliability**: Error handling, retry logic, and graceful degradation

This architecture supports the core mission of providing a realistic, safe environment for testing trading strategies before deploying them with real capital.
