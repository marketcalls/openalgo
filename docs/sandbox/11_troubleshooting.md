# Troubleshooting - Sandbox Mode

## Overview

This guide covers common issues, errors, and solutions for OpenAlgo Sandbox Mode.

## Table of Contents

1. [General Issues](#general-issues)
2. [Order Execution Issues](#order-execution-issues)
3. [Position Management Issues](#position-management-issues)
4. [Margin and Fund Issues](#margin-and-fund-issues)
5. [Square-Off Issues](#square-off-issues)
6. [Thread and Performance Issues](#thread-and-performance-issues)
7. [Database Issues](#database-issues)
8. [Configuration Issues](#configuration-issues)

---

## General Issues

### Issue: Analyzer Mode Not Enabling

**Symptoms**:
- Toggle switch doesn't stay enabled
- No green confirmation message
- Orders still routing to live broker

**Solutions**:

1. **Check Broker Configuration**:
```python
# Ensure broker credentials are configured
# Navigate to: http://127.0.0.1:5000/settings
```

2. **Check Database**:
```bash
# Verify sandbox database exists
ls -lh db/sandbox.db

# If missing, run migration
python upgrade/migrate_sandbox.py
```

3. **Check Logs**:
```bash
# Check application logs
tail -f log/openalgo.log | grep -i sandbox
```

4. **Restart Application**:
```bash
# Stop and restart OpenAlgo
# Analyzer state persists in database
```

### Issue: UI Theme Not Changing

**Symptoms**:
- Analyzer mode enabled but theme stays default
- No Garden theme colors

**Solutions**:

1. **Clear Browser Cache**:
```
- Press Ctrl+Shift+Delete (Windows/Linux)
- Press Cmd+Shift+Delete (Mac)
- Clear cache and reload
```

2. **Hard Reload Page**:
```
- Press Ctrl+F5 (Windows/Linux)
- Press Cmd+Shift+R (Mac)
```

3. **Check CSS Build**:
```bash
# Rebuild Tailwind CSS
npm run build:css
```

### Issue: Orders Not Showing in Orderbook

**Symptoms**:
- Orders placed successfully but not visible
- Empty orderbook response

**Solutions**:

1. **Check API Key**:
```python
# Ensure same API key is used
payload = {"apikey": "correct_api_key"}
```

2. **Check Order Status Filter**:
```python
# Orders might be filtered by status
# Check all statuses: open, complete, cancelled, rejected
```

3. **Direct Database Query**:
```python
from database.sandbox_db import SandboxOrders

orders = SandboxOrders.query.filter_by(user_id=user_id).all()
for order in orders:
    print(f"{order.orderid}: {order.order_status}")
```

---

## Order Execution Issues

### Issue: MARKET Orders Not Executing

**Symptoms**:
- MARKET orders stay in "open" status
- No trades created
- Position not updated

**Solutions**:

1. **Check Execution Engine**:
```python
# Verify execution thread is running
import requests

response = requests.get("http://127.0.0.1:5000/sandbox/execution-status")
print(response.json())

# If not running, restart analyzer mode
```

2. **Check Symbol Quotes**:
```python
# Verify broker API can fetch quotes
from broker.api import get_quotes

try:
    quotes = get_quotes("RELIANCE", "NSE")
    print(f"LTP: {quotes['ltp']}")
except Exception as e:
    print(f"Quote fetch failed: {e}")
```

3. **Check Order Check Interval**:
```python
from database.sandbox_db import get_config

interval = get_config('order_check_interval')
print(f"Checking orders every {interval} seconds")

# Wait at least this long for execution
```

4. **Check Logs**:
```bash
# Look for execution errors
grep "execution_engine" log/openalgo.log
```

### Issue: LIMIT Orders Not Executing

**Symptoms**:
- LIMIT orders stuck in "open" status
- LTP has crossed limit price but no execution

**Solutions**:

1. **Verify Price Logic**:
```python
# BUY LIMIT: Executes when LTP <= limit_price
# SELL LIMIT: Executes when LTP >= limit_price

# Example:
# BUY 10 RELIANCE @ ₹1,200 LIMIT
# Will execute when LTP drops to ₹1,200 or below
```

2. **Check Current LTP**:
```python
from broker.api import get_quotes

quotes = get_quotes("RELIANCE", "NSE")
print(f"Current LTP: {quotes['ltp']}")
print(f"Your Limit: {order.price}")
```

3. **Adjust Limit Price**:
```python
# Modify order with more realistic limit
import requests

payload = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-151030-abc123",
    "price": 1190.00  # Closer to current LTP
}

requests.post("http://127.0.0.1:5000/api/v1/modifyorder", json=payload)
```

### Issue: SL/SL-M Orders Not Triggering

**Symptoms**:
- SL orders not executing even though trigger price hit
- Stuck in "open" status

**Solutions**:

1. **Verify Trigger Logic**:
```python
# BUY SL: Triggers when LTP >= trigger_price
# SELL SL: Triggers when LTP <= trigger_price

# Example:
# BUY 10 RELIANCE @ ₹1,250 SL (trigger ₹1,245)
# Triggers when LTP rises to ₹1,245 or above
```

2. **Check Trigger Price Direction**:
```python
# Common mistake: Wrong trigger direction
# BUY SL trigger should be ABOVE current price
# SELL SL trigger should be BELOW current price
```

3. **Monitor LTP Movement**:
```python
import time
from broker.api import get_quotes

for i in range(10):
    quotes = get_quotes("RELIANCE", "NSE")
    print(f"LTP: {quotes['ltp']}, Trigger: {order.trigger_price}")
    time.sleep(5)
```

### Issue: Order Rejected with "Insufficient Funds"

**Symptoms**:
- Order rejected immediately
- Error: "Insufficient funds. Required: ₹X, Available: ₹Y"

**Solutions**:

1. **Check Available Balance**:
```python
import requests

response = requests.post("http://127.0.0.1:5000/api/v1/funds", json={
    "apikey": "your_api_key"
})
funds = response.json()["data"]
print(f"Available: ₹{funds['availablecash']:,.2f}")
print(f"Used Margin: ₹{funds['utiliseddebits']:,.2f}")
```

2. **Calculate Required Margin**:
```python
# Formula:
# Margin = (Price × Quantity) ÷ Leverage

# Example:
# BUY 100 RELIANCE @ ₹1,200 (MIS, 5x leverage)
# Margin = (1200 × 100) ÷ 5 = ₹24,000
```

3. **Close Unused Positions**:
```python
# Free up margin by closing positions
response = requests.post("http://127.0.0.1:5000/api/v1/closeposition", json={
    "apikey": "your_api_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS"
})
```

4. **Increase Starting Capital**:
```python
# Navigate to: http://127.0.0.1:5000/sandbox
# Change "Starting Capital" to higher amount
```

---

## Position Management Issues

### Issue: Position Not Updating After Trade

**Symptoms**:
- Trade executed but position quantity unchanged
- Average price not recalculated

**Solutions**:

1. **Check MTM Update**:
```python
# Wait for MTM update interval
from database.sandbox_db import get_config

interval = get_config('mtm_update_interval')
print(f"MTM updates every {interval} seconds")
```

2. **Force Position Refresh**:
```python
# Manually trigger position update
response = requests.post("http://127.0.0.1:5000/api/v1/positionbook", json={
    "apikey": "your_api_key"
})
```

3. **Check Database Directly**:
```python
from database.sandbox_db import SandboxPositions

position = SandboxPositions.query.filter_by(
    user_id=user_id,
    symbol="RELIANCE",
    exchange="NSE",
    product="MIS"
).first()

if position:
    print(f"Quantity: {position.quantity}")
    print(f"Avg Price: {position.average_price}")
```

### Issue: Position P&L Not Updating

**Symptoms**:
- LTP changing but P&L stays same
- MTM not reflecting current market

**Solutions**:

1. **Check MTM Interval**:
```python
from database.sandbox_db import get_config

interval = int(get_config('mtm_update_interval', '5'))

if interval == 0:
    print("MTM auto-update is DISABLED (interval = 0)")
    print("Enable it in sandbox settings")
else:
    print(f"MTM updates every {interval} seconds")
```

2. **Enable MTM Updates**:
```python
from database.sandbox_db import set_config

# Enable 5-second MTM updates
set_config('mtm_update_interval', '5')
```

3. **Check Execution Thread**:
```python
import requests

response = requests.get("http://127.0.0.1:5000/sandbox/execution-status")
status = response.json()["data"]

if not status["is_running"]:
    print("Execution thread not running - restart analyzer mode")
```

### Issue: Closed Position Still Showing

**Symptoms**:
- Position closed but still appears in positionbook
- Quantity shows 0 but position exists

**Solutions**:

1. **This is Normal Behavior**:
```python
# Positions with quantity=0 are "closed" but retained
# They show accumulated intraday P&L

# To filter out closed positions:
open_positions = [
    p for p in positions
    if p["quantity"] != 0
]
```

2. **Check Accumulated P&L**:
```python
# Closed positions display total realized P&L for the day
# This includes all trades on that symbol
```

---

## Margin and Fund Issues

### Issue: Margin Not Released After Order Cancel

**Symptoms**:
- Cancelled order but margin still blocked
- Available balance unchanged

**Solutions**:

1. **Verify Cancellation**:
```python
# Check order status
response = requests.post("http://127.0.0.1:5000/api/v1/orderstatus", json={
    "apikey": "your_api_key",
    "orderid": "SB-20251002-151030-abc123"
})

if response.json()["data"]["status"] != "cancelled":
    print("Order not actually cancelled")
```

2. **Check Margin Blocked Field**:
```python
from database.sandbox_db import SandboxOrders

order = SandboxOrders.query.filter_by(orderid=orderid).first()
print(f"Margin Blocked: ₹{order.margin_blocked}")
print(f"Status: {order.order_status}")
```

3. **Manual Fund Update**:
```python
from database.sandbox_db import SandboxFunds, db_session

fund = SandboxFunds.query.filter_by(user_id=user_id).first()
fund.available_balance += order.margin_blocked
fund.used_margin -= order.margin_blocked
db_session.commit()
```

### Issue: Incorrect Margin Calculation

**Symptoms**:
- Margin seems too high/low
- Doesn't match expected calculation

**Solutions**:

1. **Verify Leverage Settings**:
```python
from database.sandbox_db import get_config

# Check leverage for your instrument type
equity_mis = get_config('equity_mis_leverage')
equity_cnc = get_config('equity_cnc_leverage')
futures = get_config('futures_leverage')
option_buy = get_config('option_buy_leverage')
option_sell = get_config('option_sell_leverage')

print(f"Equity MIS Leverage: {equity_mis}x")
```

2. **Manual Margin Calculation**:
```python
# Equity MIS
price = 1200
quantity = 100
leverage = 5
margin = (price * quantity) / leverage
print(f"Expected Margin: ₹{margin:,.2f}")

# Futures
futures_price = 25150
lot_size = 50
quantity = 1
leverage = 10
contract_value = futures_price * lot_size * quantity
margin = contract_value / leverage
print(f"Expected Margin: ₹{margin:,.2f}")
```

3. **Check Price Used for Calculation**:
```python
# MARKET: Uses LTP
# LIMIT: Uses limit price
# SL/SL-M: Uses trigger price

# Example:
# LIMIT order at ₹1,250 (LTP = ₹1,200)
# Margin calculated on ₹1,250, NOT ₹1,200
```

---

## Square-Off Issues

### Issue: MIS Positions Not Auto-Squaring Off

**Symptoms**:
- MIS positions still open after square-off time
- No automatic closure

**Solutions**:

1. **Check Square-Off Scheduler**:
```python
import requests

response = requests.get("http://127.0.0.1:5000/sandbox/squareoff-status")
status = response.json()["data"]

print(f"Scheduler Running: {status['is_running']}")
print("Scheduled Jobs:")
for job in status["scheduled_jobs"]:
    print(f"  {job['exchange']}: {job['square_off_time']} (Next: {job['next_run']})")
```

2. **Verify Square-Off Time**:
```python
from database.sandbox_db import get_config

nse_time = get_config('nse_bse_square_off_time')
print(f"NSE/BSE Square-Off: {nse_time} IST")

# Check if current time has passed this
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
now = datetime.now(IST)
print(f"Current Time: {now.strftime('%H:%M')} IST")
```

3. **Reload Schedule**:
```python
# After changing square-off time
import requests

response = requests.post("http://127.0.0.1:5000/sandbox/reload-squareoff")
print(response.json())
```

4. **Check Logs**:
```bash
# Look for square-off execution logs
grep "square.off\|squareoff" log/openalgo.log
```

### Issue: MIS Orders Rejected After Square-Off

**Symptoms**:
- Error: "MIS orders not allowed after square-off time"
- Cannot place new MIS orders

**Solutions**:

1. **This is Expected Behavior**:
```python
# MIS orders blocked from square-off time until 9:00 AM next day
# Example: After 3:15 PM, no new MIS orders until 9:00 AM

# Use NRML or CNC instead
payload = {
    "apikey": "your_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "NRML"  # Use NRML instead of MIS
}
```

2. **Exception: Closing Existing Position**:
```python
# Orders that reduce/close existing positions are allowed
# E.g., If you have long 100, you can SELL 50 or 100
```

3. **Wait Until Next Day**:
```
# Wait until 9:00 AM IST next trading day
# Or change square-off time in settings (for testing)
```

---

## Thread and Performance Issues

### Issue: High CPU Usage

**Symptoms**:
- CPU usage consistently high
- System slowdown

**Solutions**:

1. **Increase Check Intervals**:
```python
from database.sandbox_db import set_config

# Reduce frequency of checks
set_config('order_check_interval', '10')  # Was 5, now 10 seconds
set_config('mtm_update_interval', '10')   # Was 5, now 10 seconds
```

2. **Disable Unused Features**:
```python
# Disable auto-MTM if not needed
set_config('mtm_update_interval', '0')  # Manual only
```

3. **Check Number of Active Positions**:
```python
from database.sandbox_db import SandboxPositions

positions = SandboxPositions.query.filter(
    SandboxPositions.quantity != 0
).all()

print(f"Active Positions: {len(positions)}")
# If too many, close unused ones
```

### Issue: Threads Not Starting

**Symptoms**:
- Analyzer enabled but threads not running
- No order execution

**Solutions**:

1. **Check Thread Status**:
```python
import requests

# Execution thread
exec_status = requests.get("http://127.0.0.1:5000/sandbox/execution-status")
print("Execution:", exec_status.json())

# Square-off thread
sq_status = requests.get("http://127.0.0.1:5000/sandbox/squareoff-status")
print("Square-Off:", sq_status.json())
```

2. **Restart Analyzer Mode**:
```python
import requests

# Disable
requests.post("http://127.0.0.1:5000/api/v1/analyzer", json={
    "apikey": "your_api_key",
    "mode": False
})

# Wait 2 seconds
import time
time.sleep(2)

# Enable
requests.post("http://127.0.0.1:5000/api/v1/analyzer", json={
    "apikey": "your_api_key",
    "mode": True
})
```

3. **Check Application Logs**:
```bash
# Look for thread start messages
grep -i "thread\|scheduler" log/openalgo.log
```

---

## Database Issues

### Issue: Database Locked Error

**Symptoms**:
- Error: "database is locked"
- Operations timing out

**Solutions**:

1. **Close Duplicate Connections**:
```bash
# Check if database is being accessed elsewhere
lsof db/sandbox.db  # Linux/Mac
# Close any duplicate processes
```

2. **Restart Application**:
```bash
# Stop OpenAlgo completely
# Wait 5 seconds
# Start again
```

3. **Check Database Integrity**:
```bash
sqlite3 db/sandbox.db "PRAGMA integrity_check;"
```

### Issue: Migration Fails

**Symptoms**:
- Migration script errors
- Tables not created

**Solutions**:

1. **Check Database Exists**:
```bash
ls -lh db/
# If sandbox.db missing, directory might not exist
mkdir -p db
```

2. **Run Migration with Details**:
```bash
python upgrade/migrate_sandbox.py
# Review output for specific errors
```

3. **Backup and Reset**:
```bash
# Backup existing database
cp db/sandbox.db db/sandbox_backup_$(date +%Y%m%d).db

# Remove and recreate
rm db/sandbox.db
python upgrade/migrate_sandbox.py
```

### Issue: Old Data Not Clearing

**Symptoms**:
- Data from previous sessions persists
- Reset not working

**Solutions**:

1. **Manual Fund Reset**:
```python
import requests

response = requests.post("http://127.0.0.1:5000/api/v1/resetfunds", json={
    "apikey": "your_api_key"
})
print(response.json())
```

2. **Delete All Data**:
```python
from database.sandbox_db import (
    db_session, SandboxOrders, SandboxTrades,
    SandboxPositions, SandboxHoldings, SandboxFunds
)

# Clear all tables (keeps config)
db_session.query(SandboxOrders).delete()
db_session.query(SandboxTrades).delete()
db_session.query(SandboxPositions).delete()
db_session.query(SandboxHoldings).delete()
db_session.query(SandboxFunds).delete()
db_session.commit()

print("All sandbox data cleared")
```

---

## Configuration Issues

### Issue: Config Changes Not Applying

**Symptoms**:
- Updated config but behavior unchanged
- Settings reverting

**Solutions**:

1. **Verify Config Update**:
```python
from database.sandbox_db import get_config

leverage = get_config('equity_mis_leverage')
print(f"Current Leverage: {leverage}x")
```

2. **Reload Threads**:
```python
# Some configs require thread reload
import requests

# Reload square-off scheduler
requests.post("http://127.0.0.1:5000/sandbox/reload-squareoff")

# Restart analyzer mode for execution engine
```

3. **Check Validation Errors**:
```python
# Config values have validation ranges
# Example: leverage must be 1-50

from database.sandbox_db import set_config

# This will fail (>50)
result = set_config('equity_mis_leverage', '60')
# Use valid range
result = set_config('equity_mis_leverage', '10')
```

---

## Debugging Tools

### Enable Debug Logging

```python
# In your code
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('sandbox')
logger.setLevel(logging.DEBUG)
```

### Check Database Contents

```python
from database.sandbox_db import (
    SandboxOrders, SandboxTrades, SandboxPositions,
    SandboxHoldings, SandboxFunds, SandboxConfig
)

# Orders
print(f"Total Orders: {SandboxOrders.query.count()}")
print(f"Open Orders: {SandboxOrders.query.filter_by(order_status='open').count()}")

# Positions
print(f"Total Positions: {SandboxPositions.query.count()}")
print(f"Open Positions: {SandboxPositions.query.filter(SandboxPositions.quantity != 0).count()}")

# Funds
funds = SandboxFunds.query.all()
for fund in funds:
    print(f"User {fund.user_id}: ₹{fund.available_balance:,.2f} available")
```

### Monitor Threads

```bash
# Watch execution engine logs
tail -f log/openalgo.log | grep "execution_engine"

# Watch square-off logs
tail -f log/openalgo.log | grep "square.off"
```

---

## Getting Help

If issues persist:

1. **Check Logs**: `log/openalgo.log`
2. **GitHub Issues**: Report at [OpenAlgo Repository](https://github.com/marketcalls/openalgo/issues)
3. **Documentation**: Review [Sandbox Documentation](README.md)
4. **Community**: Ask in community forums

---

**Previous**: [API Reference](10_api_reference.md) | **Next**: [Regulatory Compliance](12_regulatory_compliance.md)
