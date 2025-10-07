# Configuration - Sandbox Mode

## Overview

All sandbox settings are stored in the `sandbox_config` table and can be configured through the web interface or programmatically. Settings control capital, leverage, square-off times, and update intervals.

**Settings Page**: `http://127.0.0.1:5000/sandbox`

## Configuration Categories

### 1. Capital Settings
### 2. Leverage Settings
### 3. Square-Off Times
### 4. Update Intervals

---

## 1. Capital Settings

### Starting Capital

**Config Key**: `starting_capital`
**Default**: ₹10,000,000 (1 Crore)
**Available Options**:
- ₹1,00,000 (1 Lakh)
- ₹5,00,000 (5 Lakhs)
- ₹10,00,000 (10 Lakhs)
- ₹25,00,000 (25 Lakhs)
- ₹50,00,000 (50 Lakhs)
- ₹1,00,00,000 (1 Crore) ← Default

**Description**: Initial sandbox capital for all users. Changing this value updates all user funds immediately.

**Via Web UI**:
1. Navigate to `http://127.0.0.1:5000/sandbox`
2. Select desired capital from dropdown
3. Click "Update Starting Capital"

**Via Code**:
```python
from database.sandbox_db import set_config

set_config('starting_capital', '5000000')  # ₹50 Lakhs
```

**Effect on Existing Users**:
When starting capital is changed, all user funds are updated:
```python
# Formula:
available_balance = new_capital - used_margin + total_pnl
```

**Example**:
```python
Before:
- Starting Capital: ₹10,000,000
- Used Margin: ₹200,000
- Total P&L: -₹5,000
- Available: ₹9,795,000

Change to: ₹5,000,000

After:
- Starting Capital: ₹5,000,000
- Used Margin: ₹200,000 (preserved)
- Total P&L: -₹5,000 (preserved)
- Available: ₹4,795,000 (recalculated)
```

### Auto-Reset Day

**Config Key**: `reset_day`
**Default**: `Sunday`
**Options**: `Monday`, `Tuesday`, `Wednesday`, `Thursday`, `Friday`, `Saturday`, `Sunday`

**Description**: Day of the week when funds automatically reset to starting capital.

**Via Web UI**:
Select day from dropdown in Sandbox Settings.

**Via Code**:
```python
set_config('reset_day', 'Monday')
```

**Behavior**:
- Resets at configured time (default: 00:00 IST)
- Uses APScheduler (works even if app was stopped)
- Resets all user funds to starting capital
- Clears all positions, orders, trades
- Increments reset counter

### Auto-Reset Time

**Config Key**: `reset_time`
**Default**: `00:00` (midnight IST)
**Format**: `HH:MM` (24-hour format)
**Range**: `00:00` to `23:59`

**Description**: Time of day when auto-reset occurs (in IST timezone).

**Via Web UI**:
Use time picker in Sandbox Settings.

**Via Code**:
```python
set_config('reset_time', '09:00')  # 9:00 AM IST
```

**APScheduler Integration**:
```python
# Automatically creates cron job
reset_trigger = CronTrigger(
    day_of_week=day_mapping[reset_day],
    hour=reset_hour,
    minute=reset_minute,
    timezone=IST
)
```

---

## 2. Leverage Settings

All leverage settings accept values from **1 to 50x**.

### Equity MIS Leverage

**Config Key**: `equity_mis_leverage`
**Default**: `5` (5x leverage)
**Range**: 1-50x
**Input Type**: Number with step 0.1

**Description**: Leverage for equity intraday (MIS) trades on NSE/BSE.

**Example**:
```python
# With 5x leverage (default)
Order: BUY 100 RELIANCE @ ₹1,200 (MIS)
Margin: ₹120,000 ÷ 5 = ₹24,000

# With 8x leverage
Order: BUY 100 RELIANCE @ ₹1,200 (MIS)
Margin: ₹120,000 ÷ 8 = ₹15,000
```

### Equity CNC Leverage

**Config Key**: `equity_cnc_leverage`
**Default**: `1` (no leverage)
**Range**: 1-50x

**Description**: Leverage for equity delivery (CNC) trades on NSE/BSE.

**Typical Use**: Keep at 1x (full payment required for delivery).

### Futures Leverage

**Config Key**: `futures_leverage`
**Default**: `10` (10x leverage)
**Range**: 1-50x

**Description**: Leverage for all futures contracts (NFO, BFO, CDS, BCD, MCX, NCDEX).

**Example**:
```python
# With 10x leverage
Symbol: NIFTY25JAN25000FUT
LTP: ₹25,150
Lot Size: 50
Contract Value: ₹25,150 × 50 = ₹1,257,500
Margin: ₹1,257,500 ÷ 10 = ₹125,750
```

### Option Buy Leverage

**Config Key**: `option_buy_leverage`
**Default**: `1` (full premium)
**Range**: 1-50x

**Description**: Leverage for buying options. Default requires full premium payment.

**Example**:
```python
# With 1x leverage (default)
Symbol: NIFTY25JAN25000CE
Premium: ₹150
Lot Size: 50
Margin: 150 × 50 = ₹7,500 (full premium)
```

### Option Sell Leverage

**Config Key**: `option_sell_leverage`
**Default**: `1` (full premium)
**Range**: 1-50x

**Description**: Leverage for selling options. Default requires full premium (simplified approach).

**Note**: Can be increased for futures-based margin calculation, but default 1x keeps it simple.

**Configuration**:
```python
# Via UI
Navigate to Sandbox Settings → Leverage Settings → Option Sell Leverage

# Via Code
set_config('option_sell_leverage', '10')  # Use 10x leverage for option selling
```

---

## 3. Square-Off Times

All times are in **IST** (Indian Standard Time) and use **HH:MM** format (24-hour).

### NSE/BSE Square-Off Time

**Config Key**: `nse_bse_square_off_time`
**Default**: `15:15` (3:15 PM IST)
**Input Type**: Time picker

**Description**: Auto square-off time for MIS positions on NSE/BSE exchanges.

**Behavior**:
- Cancels all pending MIS orders at this time
- Closes all open MIS positions at LTP
- Blocks new MIS orders until 09:00 AM next day

### CDS/BCD Square-Off Time

**Config Key**: `cds_bcd_square_off_time`
**Default**: `16:45` (4:45 PM IST)

**Description**: Auto square-off time for MIS positions on CDS/BCD currency exchanges.

### MCX Square-Off Time

**Config Key**: `mcx_square_off_time`
**Default**: `23:30` (11:30 PM IST)

**Description**: Auto square-off time for MIS positions on MCX commodity exchange.

### NCDEX Square-Off Time

**Config Key**: `ncdex_square_off_time`
**Default**: `17:00` (5:00 PM IST)

**Description**: Auto square-off time for MIS positions on NCDEX commodity exchange.

**Auto-Reload**:
Changing square-off time automatically reloads the scheduler:

```python
# blueprints/sandbox.py
if config_key.endswith('square_off_time'):
    from services.sandbox_service import sandbox_reload_squareoff_schedule
    reload_success, reload_response, reload_status = sandbox_reload_squareoff_schedule()
```

---

## 4. Update Intervals

### Order Check Interval

**Config Key**: `order_check_interval`
**Default**: `5` seconds
**Range**: 1-30 seconds
**Input Type**: Number (integer)

**Description**: How often the execution engine checks pending orders.

**Lower Value**: Faster order execution, more CPU usage
**Higher Value**: Slower order execution, less CPU usage

**Recommendation**: 5 seconds provides good balance.

### MTM Update Interval

**Config Key**: `mtm_update_interval`
**Default**: `5` seconds
**Range**: 0-60 seconds
**Input Type**: Number (integer)

**Description**: How often position mark-to-market is updated.

**Special Value**: `0` = Manual MTM only (no automatic updates)

**Configuration Examples**:
```python
# Real-time MTM (every second)
set_config('mtm_update_interval', '1')

# Normal MTM (every 5 seconds)
set_config('mtm_update_interval', '5')

# Manual MTM only (no auto-updates)
set_config('mtm_update_interval', '0')
```

---

**Note**: Rate limiting for API endpoints is controlled by `.env` file settings (`ORDER_RATE_LIMIT`, `API_RATE_LIMIT`, `SMART_ORDER_RATE_LIMIT`), not sandbox configuration. These apply to all API requests regardless of sandbox mode.

---

## Configuration via Web Interface

### Access Settings Page

Navigate to: `http://127.0.0.1:5000/sandbox`

### Update Settings

1. **Capital Settings**:
   - Select starting capital from dropdown
   - Choose auto-reset day from dropdown
   - Pick auto-reset time using time picker
   - Click "Update Starting Capital"

2. **Leverage Settings**:
   - Enter values between 1-50 for each leverage type
   - Use decimal values if needed (e.g., 5.5x)
   - Click "Update Leverage Settings"

3. **Square-Off Times**:
   - Use time pickers for each exchange
   - Time format: HH:MM (24-hour)
   - Click "Update Square-Off Times"

4. **Update Intervals**:
   - Adjust order check interval (1-30 seconds)
   - Set MTM update interval (0-60 seconds)
   - Click "Update Intervals"

---

## Configuration via Code

### Get Configuration

```python
from database.sandbox_db import get_config

# Get single config
leverage = get_config('equity_mis_leverage', default='5')

# Get all configs
from database.sandbox_db import get_all_configs
all_configs = get_all_configs()
# Returns: {config_key: {'value': ..., 'description': ...}}
```

### Set Configuration

```python
from database.sandbox_db import set_config

# Update single config
set_config('equity_mis_leverage', '8')

# With description
set_config(
    config_key='equity_mis_leverage',
    config_value='8',
    description='Updated leverage to 8x for testing'
)
```

### Batch Update

```python
from database.sandbox_db import set_config

configs = {
    'equity_mis_leverage': '8',
    'equity_cnc_leverage': '2',
    'futures_leverage': '15'
}

for key, value in configs.items():
    set_config(key, value)
```

---

## Configuration Best Practices

### 1. Testing Different Capital Levels

Test your strategies with various capital levels:

```python
# Conservative testing
set_config('starting_capital', '100000')  # ₹1 Lakh

# Moderate testing
set_config('starting_capital', '1000000')  # ₹10 Lakhs

# Realistic testing
set_config('starting_capital', '10000000')  # ₹1 Crore
```

### 2. Adjusting Leverage for Risk Testing

```python
# Conservative (lower leverage, higher margin)
set_config('equity_mis_leverage', '3')  # 33% margin required

# Moderate (default)
set_config('equity_mis_leverage', '5')  # 20% margin required

# Aggressive (higher leverage, lower margin)
set_config('equity_mis_leverage', '10')  # 10% margin required
```

### 3. Performance Tuning

```python
# For heavy testing (more orders/positions)
set_config('order_check_interval', '3')  # Check more frequently
set_config('mtm_update_interval', '3')   # Update MTM more frequently

# For light testing (fewer resources)
set_config('order_check_interval', '10')  # Check less frequently
set_config('mtm_update_interval', '10')   # Update MTM less frequently
```

### 4. Square-Off Testing

```python
# Test square-off earlier in the day
set_config('nse_bse_square_off_time', '14:00')  # 2:00 PM

# Normal square-off
set_config('nse_bse_square_off_time', '15:15')  # 3:15 PM
```

---

## Configuration Validation

The system validates all configuration changes:

### Starting Capital Validation
```python
# Only fixed values allowed
valid_capitals = [100000, 500000, 1000000, 2500000, 5000000, 10000000]
if value not in valid_capitals:
    return 'Starting capital must be one of: ₹1L, ₹5L, ₹10L, ₹25L, ₹50L, or ₹1Cr'
```

### Leverage Validation
```python
# Range: 1-50x
if value < 1:
    return 'Leverage must be at least 1x'
if value > 50:
    return 'Leverage cannot exceed 50x'
```

### Interval Validation
```python
# Order check: 1-30 seconds
if value < 1 or value > 30:
    return 'Order check interval must be between 1-30 seconds'

# MTM update: 0-60 seconds (0 = manual)
if value < 0 or value > 60:
    return 'MTM update interval must be between 0-60 seconds'
```

### Rate Limit Validation
```python
# Order rate: 1-100 orders/sec
if value < 1 or value > 100:
    return 'Order rate limit must be between 1-100 orders/second'

# API rate: 1-1000 calls/sec
if value < 1 or value > 1000:
    return 'API rate limit must be between 1-1000 calls/second'
```

---

## Default Configuration

When sandbox database is initialized, these defaults are set:

```python
{
    'starting_capital': '10000000.00',      # ₹1 Crore
    'reset_day': 'Sunday',
    'reset_time': '00:00',
    'order_check_interval': '5',
    'mtm_update_interval': '5',
    'nse_bse_square_off_time': '15:15',
    'cds_bcd_square_off_time': '16:45',
    'mcx_square_off_time': '23:30',
    'ncdex_square_off_time': '17:00',
    'equity_mis_leverage': '5',
    'equity_cnc_leverage': '1',
    'futures_leverage': '10',
    'option_buy_leverage': '1',
    'option_sell_leverage': '1'
}
```

**Note**: Rate limits (`ORDER_RATE_LIMIT`, `API_RATE_LIMIT`, `SMART_ORDER_RATE_LIMIT`, `SMART_ORDER_DELAY`) are configured in `.env` file and apply globally to all API endpoints.

---

## Troubleshooting Configuration

### Issue: Configuration Changes Not Taking Effect

**Solution**: Check if sandbox threads are running and restart if needed.

```python
# Via API
import requests
response = requests.post("http://127.0.0.1:5000/sandbox/reload-squareoff")
```

### Issue: Can't Update Starting Capital

**Solution**: Ensure value is one of the fixed options.

```python
# Valid
set_config('starting_capital', '5000000')  # ✅

# Invalid
set_config('starting_capital', '3000000')  # ❌ Not in fixed list
```

### Issue: Square-Off Not Working at Configured Time

**Solution**: Reload the square-off scheduler after changing time.

```python
from services.sandbox_service import sandbox_reload_squareoff_schedule
success, response, status = sandbox_reload_squareoff_schedule()
```

---

**Previous**: [Architecture](08_architecture.md) | **Next**: [API Reference](10_api_reference.md)
