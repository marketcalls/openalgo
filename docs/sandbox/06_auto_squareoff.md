# Auto Square-Off System

## Overview

The sandbox auto square-off system automatically closes MIS (Margin Intraday Square-off) positions at configured times for each exchange using APScheduler for precise timing.

## Key Features

- **Exchange-Specific Timings**: Different square-off times for NSE, MCX, NCDEX, etc.
- **Dual Action**: Cancels pending MIS orders + Closes open MIS positions
- **APScheduler Based**: Uses cron jobs for precise IST timing
- **Dynamic Reload**: Configuration changes apply without restart
- **Backup Safety**: Every-minute backup check catches missed executions
- **Post-Squareoff Blocking**: Prevents new MIS orders until 09:00 AM next day

## Square-Off Times (IST)

### Default Configuration

| Exchange Group | Time  | Exchanges Covered |
|---------------|-------|-------------------|
| NSE/BSE       | 15:15 | NSE, BSE, NFO, BFO |
| CDS/BCD       | 16:45 | CDS, BCD |
| MCX           | 23:30 | MCX |
| NCDEX         | 17:00 | NCDEX |

**Config Keys**:
- `nse_bse_square_off_time`
- `cds_bcd_square_off_time`
- `mcx_square_off_time`
- `ncdex_square_off_time`

## Architecture

### Thread Implementation

**File**: `sandbox/squareoff_thread.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

IST = pytz.timezone('Asia/Kolkata')

def start_squareoff_scheduler():
    scheduler = BackgroundScheduler(
        timezone=IST,
        daemon=True,
        job_defaults={
            'coalesce': True,  # Combine missed runs
            'max_instances': 1,  # One job at a time
        }
    )

    # Schedule jobs for each exchange
    schedule_square_off_jobs(scheduler)

    scheduler.start()
```

### Job Scheduling

**File**: `sandbox/squareoff_thread.py` (lines 37-98)

```python
def _schedule_square_off_jobs(scheduler):
    configs = {
        'NSE_BSE': get_config('nse_bse_square_off_time', '15:15'),
        'CDS_BCD': get_config('cds_bcd_square_off_time', '16:45'),
        'MCX': get_config('mcx_square_off_time', '23:30'),
        'NCDEX': get_config('ncdex_square_off_time', '17:00'),
    }

    for group, time_str in configs.items():
        hour, minute = map(int, time_str.split(':'))

        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=IST
        )

        scheduler.add_job(
            func=som.check_and_square_off,
            trigger=trigger,
            id=f'squareoff_{group}',
            replace_existing=True,
            misfire_grace_time=300  # 5 min grace
        )

    # Backup job runs every minute
    scheduler.add_job(
        func=som.check_and_square_off,
        trigger='interval',
        minutes=1,
        id='squareoff_backup'
    )
```

## Square-Off Process

### Step 1: Cancel Pending MIS Orders

**File**: `sandbox/squareoff_manager.py` (lines 102-145)

```python
def _cancel_open_mis_orders(current_time):
    # Get all open MIS orders
    open_orders = SandboxOrders.query.filter_by(
        product='MIS',
        order_status='open'
    ).all()

    for order in open_orders:
        square_off_time = get_square_off_time(order.exchange)

        # Check if past square-off time
        if current_time >= square_off_time:
            # Release margin
            if order.margin_blocked > 0:
                release_margin(order.margin_blocked)

            # Cancel order
            order.order_status = 'cancelled'
            order.rejection_reason = 'Auto-cancelled at square-off time'
```

### Step 2: Close Open MIS Positions

**File**: `sandbox/squareoff_manager.py` (lines 147-178)

```python
def _square_off_positions(positions):
    for position in positions:
        # Create reverse MARKET order
        if position.quantity > 0:
            action = 'SELL'
        else:
            action = 'BUY'

        order_manager = OrderManager(position.user_id)
        success, response, status = order_manager.place_order({
            'symbol': position.symbol,
            'exchange': position.exchange,
            'action': action,
            'quantity': abs(position.quantity),
            'price_type': 'MARKET',
            'product': 'MIS'
        })
```

**Important**: Only processes positions with `quantity != 0`

### Execution Flow

```
15:15 IST (NSE/BSE Square-off Time)
    ↓
Cron Job Triggered
    ↓
Step 1: Cancel all pending NSE/BSE/NFO/BFO MIS orders
    ├─> Release blocked margin
    └─> Mark orders as cancelled
    ↓
Step 2: Close all open NSE/BSE/NFO/BFO MIS positions (qty != 0)
    ├─> Create reverse MARKET order
    ├─> Execute at current LTP
    ├─> Calculate realized P&L
    ├─> Add to accumulated_realized_pnl
    └─> Release margin
    ↓
Log completion
```

## Post Square-Off Order Blocking

**New in v1.1.0**: MIS orders are blocked after square-off time until 09:00 AM next day.

### Blocking Logic

**File**: `sandbox/order_manager.py` (lines 115-167)

```python
if product == 'MIS':
    square_off_time = get_square_off_time(exchange)
    market_open_time = time(9, 0)
    current_time = datetime.now(IST).time()

    # Check if in blocked period
    is_blocked = False
    if current_time >= square_off_time:
        is_blocked = True  # After square-off today
    elif current_time < market_open_time:
        is_blocked = True  # Before market open (yesterday's block continues)

    if is_blocked:
        # Exception: Allow closing existing positions
        existing_position = get_open_position(symbol, exchange, 'MIS')

        is_reducing = False
        if existing_position:
            if action == 'BUY' and existing_position.quantity < 0:
                is_reducing = True  # Covering short
            elif action == 'SELL' and existing_position.quantity > 0:
                is_reducing = True  # Closing long

        if not is_reducing:
            return error(
                f"MIS orders cannot be placed after square-off time "
                f"({square_off_time}). Trading resumes at 09:00 AM IST."
            )
```

### Blocking Scenarios

**Scenario 1: After 15:15, Before Midnight**
```python
Time: 16:30 IST
Order: BUY 100 RELIANCE MIS
Result: BLOCKED ❌
Message: "MIS orders cannot be placed after square-off time (15:15 IST)"
```

**Scenario 2: After Midnight, Before 09:00**
```python
Time: 07:00 IST
Order: BUY 100 SBIN MIS
Result: BLOCKED ❌
Message: "MIS orders cannot be placed after square-off time (15:15 IST)"
```

**Scenario 3: After 09:00**
```python
Time: 09:15 IST
Order: BUY 100 INFY MIS
Result: ALLOWED ✅
```

**Scenario 4: Closing Existing Position (Exception)**
```python
Time: 16:30 IST
Existing Position: +100 RELIANCE MIS
Order: SELL 100 RELIANCE MIS
Result: ALLOWED ✅ (closing existing position)
```

## Configuration Management

### View Square-Off Status

**Endpoint**: `/sandbox/squareoff-status`

```python
import requests

response = requests.get("http://127.0.0.1:5000/sandbox/squareoff-status")
print(response.json())
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "running": true,
        "timezone": "Asia/Kolkata",
        "jobs": [
            {
                "id": "squareoff_NSE_BSE",
                "name": "MIS Square-off NSE_BSE",
                "next_run": "2025-10-02 15:15:00 IST"
            },
            {
                "id": "squareoff_backup",
                "name": "MIS Square-off Backup Check",
                "next_run": "2025-10-02 10:54:00 IST"
            }
        ]
    }
}
```

### Reload Square-Off Schedule

**Endpoint**: `/sandbox/reload-squareoff`

```python
# After changing square-off time in settings
response = requests.post("http://127.0.0.1:5000/sandbox/reload-squareoff")
```

**Auto-Reload**: Schedule automatically reloads when square-off time is updated via `/sandbox/update` endpoint.

**File**: `blueprints/sandbox.py` (lines 129-138)

```python
if config_key.endswith('square_off_time'):
    from services.sandbox_service import sandbox_reload_squareoff_schedule
    reload_success, reload_response, reload_status = sandbox_reload_squareoff_schedule()
    if reload_success:
        logger.info(f"Square-off schedule reloaded after {config_key} update")
```

## Backup Safety Mechanism

### Every-Minute Backup Check

**Purpose**: Catch any missed square-off executions

**Implementation**:
```python
# Runs every 1 minute
scheduler.add_job(
    func=som.check_and_square_off,
    trigger='interval',
    minutes=1,
    id='squareoff_backup'
)
```

**Smart Logic**:
```python
def check_and_square_off():
    current_time = datetime.now(IST).time()

    # Get all MIS positions (qty != 0)
    mis_positions = get_open_mis_positions()

    for position in mis_positions:
        square_off_time = get_square_off_time(position.exchange)

        # Only square-off if past square-off time
        if current_time >= square_off_time:
            square_off_position(position)
```

**Scenarios Covered**:
- System was down during exact square-off time
- Primary cron job failed to execute
- Late market hours trading (MCX at 23:30)
- System restart after square-off time

## Force Square-Off

### Manual Force Square-Off

```python
from sandbox.squareoff_manager import SquareOffManager

som = SquareOffManager()
success, message = som.force_square_off_all_mis()
```

**Use Cases**:
- Emergency position closure
- End of day cleanup
- Testing square-off functionality

## Logging

### Square-Off Logs

```
[INFO] Scheduling MIS square-off jobs (IST timezone):
[INFO]   NSE_BSE: 15:15 IST (Job ID: squareoff_NSE_BSE)
[INFO]   CDS_BCD: 16:45 IST (Job ID: squareoff_CDS_BCD)
[INFO]   MCX: 23:30 IST (Job ID: squareoff_MCX)
[INFO]   NCDEX: 17:00 IST (Job ID: squareoff_NCDEX)
[INFO]   Backup check: Every 1 minute (Job ID: squareoff_backup)

[INFO] Starting square-off check
[INFO] Found 5 MIS positions to square-off
[INFO] Auto-cancelled MIS order SB-123 for RELIANCE past square-off time
[INFO] Auto square-off: SBIN for user rajandran - OrderID: SB-456
[INFO] Square-off completed: 5 successful, 0 failed
```

## Summary

The auto square-off system provides:

1. **Precise Timing**: APScheduler cron jobs in IST timezone
2. **Dual Action**: Cancels orders + Closes positions
3. **Exchange-Specific**: Different times for different exchanges
4. **Post-Squareoff Control**: Blocks new MIS orders until next session
5. **Safety Net**: Backup every-minute check
6. **Dynamic Updates**: Config changes apply without restart
7. **Smart Filtering**: Only processes positions with quantity != 0

---

**Previous**: [Position Management](05_position_management.md) | **Next**: [Database Schema](07_database_schema.md)
