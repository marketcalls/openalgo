# T+1 Settlement and Holdings - Complete Guide

## Overview

The T+1 Settlement system handles the conversion of CNC (Cash and Carry / Delivery) positions to holdings after the settlement period. This document provides a comprehensive understanding of the complete lifecycle of CNC trades, fund flow mechanics, and holdings management.

**Key Concept**: In Indian markets, when you buy shares for delivery (CNC product), they are settled to your demat account on T+1 (Trade day + 1 business day). At midnight (00:00 IST), your CNC positions automatically convert to holdings.

## Complete CNC Lifecycle

### Day 0: CNC BUY Order Placement

```python
Order: BUY 75 ZEEL @ Rs.114.21 (CNC)
Trade Value: 75 × Rs.114.21 = Rs.8,565.75
```

**What Happens:**

1. **Margin Calculation**
   ```python
   Product: CNC
   Leverage: 1x (no leverage for delivery)
   Margin Required: Rs.8,565.75 × 1 = Rs.8,565.75
   ```

2. **Fund Deduction**
   ```
   BEFORE ORDER:
   - Total Capital:      Rs.5,000,000.00
   - Available Balance:  Rs.5,000,000.00
   - Used Margin:        Rs.0.00

   MARGIN BLOCKED:
   - available_balance -= Rs.8,565.75
   - used_margin += Rs.8,565.75

   AFTER ORDER:
   - Total Capital:      Rs.5,000,000.00
   - Available Balance:  Rs.4,991,434.25 ✓
   - Used Margin:        Rs.8,565.75 ✓
   ```

3. **Position Created**
   ```python
   SandboxPositions:
   - symbol: ZEEL
   - exchange: NSE
   - product: CNC
   - quantity: +75
   - average_price: Rs.114.21
   - created_at: 2025-10-03 10:00:00 IST
   ```

**File**: `sandbox/order_manager.py` (lines 100-300)

---

### Day 1 00:00: T+1 Settlement (Position → Holdings)

At midnight (00:00 IST), the APScheduler job runs to process T+1 settlement.

**What Happens:**

1. **Scheduler Triggers Settlement**
   ```python
   # APScheduler Job (runs daily at 00:00 IST)
   from sandbox.holdings_manager import process_all_t1_settlements

   # File: sandbox/squareoff_thread.py (lines 99-122)
   settlement_trigger = CronTrigger(
       hour=0,
       minute=0,
       timezone=IST
   )

   scheduler.add_job(
       func=process_all_t1_settlements,
       trigger=settlement_trigger,
       id='t1_settlement'
   )
   ```

2. **Position Retrieved**
   ```python
   # Get all CNC positions from yesterday or earlier
   ist = pytz.timezone('Asia/Kolkata')
   today = datetime.now(ist).date()

   cnc_positions = SandboxPositions.query.filter_by(
       user_id=user_id,
       product='CNC'
   ).filter(
       SandboxPositions.created_at < datetime.combine(today, datetime.min.time())
   ).all()
   ```

3. **Holding Created**
   ```python
   holding = SandboxHoldings(
       user_id=user_id,
       symbol='ZEEL',
       exchange='NSE',
       quantity=75,
       average_price=Rs.114.21,
       ltp=Rs.114.21,
       pnl=Decimal('0.00'),
       pnl_percent=Decimal('0.00'),
       settlement_date=today,
       created_at=datetime.now(ist)
   )
   db_session.add(holding)
   ```

4. **✨ CRITICAL: Margin Transfer to Holdings**
   ```python
   # This is the KEY difference from standard margin release
   from sandbox.fund_manager import FundManager
   fund_manager = FundManager(user_id)

   margin_amount = abs(position.quantity) * position.average_price
   # = 75 × Rs.114.21 = Rs.8,565.75

   # Transfer margin from used_margin to holdings
   # (does NOT credit available_balance!)
   fund_manager.transfer_margin_to_holdings(
       margin_amount,
       f"T+1 settlement: {position.symbol} → Holdings"
   )
   ```

5. **Fund Update**
   ```python
   # Inside transfer_margin_to_holdings():

   BEFORE TRANSFER:
   - available_balance: Rs.4,991,434.25
   - used_margin: Rs.8,565.75

   TRANSFER OPERATION:
   - used_margin -= Rs.8,565.75  # Release from margin
   - available_balance += Rs.0.00  # Do NOT credit!

   AFTER TRANSFER:
   - available_balance: Rs.4,991,434.25 (STAYS SAME ✓)
   - used_margin: Rs.0.00 (RELEASED ✓)
   - holdings_value: Rs.8,565.75 (NEW)

   BALANCE CHECK:
   available_balance + holdings_value = Rs.5,000,000.00 ✓
   ```

   **Why not credit available_balance?**
   - The money is now **invested in shares**
   - Holdings value represents your investment
   - Money is not available as cash until you sell
   - This maintains: `Total Capital = Available Balance + Holdings Value`

6. **Position Deleted**
   ```python
   db_session.delete(position)
   db_session.commit()
   ```

**Files**:
- `sandbox/holdings_manager.py` (lines 106-224)
- `sandbox/fund_manager.py` (lines 258-284)

---

### Day 2-365: Holdings Period

Your shares now appear in `/holdings` API:

```json
{
  "status": "success",
  "data": {
    "holdings": [
      {
        "symbol": "ZEEL",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 75,
        "average_price": 114.21,
        "ltp": 120.00,
        "pnl": 434.25,
        "pnlpercent": 3.80,
        "current_value": 9000.00,
        "settlement_date": "2025-10-04"
      }
    ],
    "statistics": {
      "totalholdingvalue": 9000.00,
      "totalinvvalue": 8565.75,
      "totalprofitandloss": 434.25,
      "totalpnlpercentage": 3.80
    }
  },
  "mode": "analyze"
}
```

**MTM Updates:**
```python
# Holdings P&L updated with live prices every 5 seconds
def _update_holdings_mtm(holdings):
    for holding in holdings:
        ltp = get_live_quote(holding.symbol, holding.exchange)

        holding.ltp = ltp
        holding.pnl = (ltp - holding.average_price) × abs(holding.quantity)
        holding.pnl_percent = ((ltp - holding.average_price) / holding.average_price) × 100

    db_session.commit()
```

**File**: `sandbox/holdings_manager.py` (lines 203-242)

---

### Day X: CNC SELL Order (Selling Holdings)

```python
Order: SELL 75 ZEEL @ Rs.120.00 (CNC)
Sale Value: 75 × Rs.120.00 = Rs.9,000.00
```

**What Happens:**

1. **CNC SELL Position Created**
   ```python
   # When you sell holdings, a SELL position is created
   position = SandboxPositions(
       user_id=user_id,
       symbol='ZEEL',
       exchange='NSE',
       product='CNC',
       quantity=-75,  # Negative for SELL
       average_price=Rs.120.00,
       created_at=datetime.now(ist)
   )
   db_session.add(position)
   ```

2. **No Margin Blocked**
   ```python
   # CNC SELL of existing holdings doesn't block margin
   # You're selling what you already own

   Funds Update: NONE
   - available_balance: Rs.4,991,434.25 (unchanged)
   - used_margin: Rs.0.00 (unchanged)
   ```

**File**: `sandbox/order_manager.py` (lines 225-262)

---

### Day X+1 00:00: T+1 Settlement (Process SELL)

At midnight, the APScheduler job processes the SELL position.

**What Happens:**

1. **Position Retrieved**
   ```python
   cnc_positions = SandboxPositions.query.filter_by(
       user_id=user_id,
       product='CNC'
   ).filter(
       SandboxPositions.created_at < today
   ).all()

   # Found: SELL position with quantity=-75
   ```

2. **Holding Updated**
   ```python
   holding = SandboxHoldings.query.filter_by(
       user_id=user_id,
       symbol='ZEEL',
       exchange='NSE'
   ).first()

   # position.quantity = -75 (SELL)
   # holding.quantity = 75 (current holding)

   # Update holding quantity
   holding.quantity += position.quantity
   # = 75 + (-75) = 0
   ```

3. **✨ CRITICAL: Credit Sale Proceeds**
   ```python
   # Calculate sale proceeds
   sale_proceeds = abs(position.quantity) × position.average_price
   # = 75 × Rs.120.00 = Rs.9,000.00

   # Credit to available balance
   fund_manager.credit_sale_proceeds(
       sale_proceeds,
       f"T+1 settlement: {position.symbol} SELL from Holdings"
   )
   ```

4. **Fund Update**
   ```python
   # Inside credit_sale_proceeds():

   BEFORE CREDIT:
   - available_balance: Rs.4,991,434.25
   - used_margin: Rs.0.00
   - holdings_value: Rs.8,565.75

   CREDIT OPERATION:
   - available_balance += Rs.9,000.00  # Credit sale proceeds

   AFTER CREDIT:
   - available_balance: Rs.5,000,434.25 ✓
   - used_margin: Rs.0.00
   - holdings_value: Rs.0.00 (holding deleted)

   PROFIT CALCULATION:
   Sale Proceeds: Rs.9,000.00
   Original Cost: Rs.8,565.75
   Profit: Rs.434.25 ✓
   ```

5. **Holding Deleted (Zero Quantity)**
   ```python
   # If holding quantity becomes 0, delete the holding
   if holding.quantity == 0:
       db_session.delete(holding)
       logger.info(f"Deleted zero-quantity holding: {position.symbol}")
   ```

6. **Position Deleted**
   ```python
   db_session.delete(position)
   db_session.commit()
   ```

**Files**:
- `sandbox/holdings_manager.py` (lines 173-192)
- `sandbox/fund_manager.py` (lines 286-310)

---

## Fund Flow Summary

### Complete CNC Cycle Fund Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   CNC TRADE FUND FLOW                        │
└─────────────────────────────────────────────────────────────┘

INITIAL STATE:
├─ Total Capital:      Rs.5,000,000.00
├─ Available Balance:  Rs.5,000,000.00
├─ Used Margin:        Rs.0.00
└─ Holdings Value:     Rs.0.00

▼ DAY 0: BUY 75 ZEEL @ Rs.114.21 (CNC)
│
├─ Trade Value: Rs.8,565.75
├─ Margin Blocked: Rs.8,565.75 (1x leverage)
│
├─ AFTER BUY:
│  ├─ Available Balance:  Rs.4,991,434.25 (-Rs.8,565.75)
│  ├─ Used Margin:        Rs.8,565.75
│  └─ Holdings Value:     Rs.0.00 (still in positions)

▼ DAY 1 00:00: T+1 SETTLEMENT (Position → Holdings)
│
├─ Margin Transfer: Rs.8,565.75
├─ Operation: transfer_margin_to_holdings()
│  ├─ used_margin -= Rs.8,565.75  (release)
│  └─ available_balance += Rs.0    (NO credit!)
│
├─ AFTER SETTLEMENT:
│  ├─ Available Balance:  Rs.4,991,434.25 (STAYS SAME ✓)
│  ├─ Used Margin:        Rs.0.00 (released)
│  └─ Holdings Value:     Rs.8,565.75 (now in holdings)
│
└─ BALANCE CHECK: Rs.4,991,434.25 + Rs.8,565.75 = Rs.5,000,000 ✓

▼ DAY X: SELL 75 ZEEL @ Rs.120.00 (CNC)
│
├─ Sale Value: Rs.9,000.00
├─ No Margin Blocked (selling existing holdings)
│
├─ AFTER SELL ORDER:
│  ├─ Available Balance:  Rs.4,991,434.25 (unchanged)
│  ├─ Used Margin:        Rs.0.00
│  └─ Holdings Value:     Rs.8,565.75 (still in holdings)

▼ DAY X+1 00:00: T+1 SETTLEMENT (Process SELL)
│
├─ Sale Proceeds: Rs.9,000.00
├─ Operation: credit_sale_proceeds()
│  └─ available_balance += Rs.9,000.00
│
├─ AFTER SETTLEMENT:
│  ├─ Available Balance:  Rs.5,000,434.25 ✓
│  ├─ Used Margin:        Rs.0.00
│  └─ Holdings Value:     Rs.0.00 (holding deleted)
│
└─ PROFIT: Rs.5,000,434.25 - Rs.5,000,000.00 = Rs.434.25 ✓
```

---

## Key Functions

### 1. process_t1_settlement()

**File**: `sandbox/holdings_manager.py` (lines 106-224)

```python
def process_t1_settlement(self):
    """
    Process T+1 settlement - move CNC positions to holdings
    Should be called daily at midnight by APScheduler
    """

    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist).date()

    # Get all CNC positions from yesterday or earlier
    cnc_positions = SandboxPositions.query.filter_by(
        user_id=self.user_id,
        product='CNC'
    ).filter(
        SandboxPositions.created_at < datetime.combine(today, datetime.min.time())
    ).all()

    for position in cnc_positions:
        # Skip zero-quantity positions
        if position.quantity == 0:
            db_session.delete(position)
            continue

        # Initialize fund manager
        fund_manager = FundManager(self.user_id)

        # Check if holding already exists
        holding = SandboxHoldings.query.filter_by(
            user_id=self.user_id,
            symbol=position.symbol,
            exchange=position.exchange
        ).first()

        if holding:
            # UPDATE EXISTING HOLDING

            if position.quantity > 0:
                # BUY: Add to holding
                total_value = (abs(holding.quantity) * holding.average_price) + \
                              (abs(position.quantity) * position.average_price)
                total_quantity = abs(holding.quantity) + abs(position.quantity)

                holding.quantity += position.quantity
                holding.average_price = total_value / total_quantity

                # Transfer margin to holdings (don't credit available_balance)
                margin_amount = abs(position.quantity) * position.average_price
                fund_manager.transfer_margin_to_holdings(margin_amount, ...)

            else:
                # SELL: Reduce holding
                holding.quantity += position.quantity  # position.quantity is negative

                # Credit sale proceeds to available balance
                sale_proceeds = abs(position.quantity) * position.average_price
                fund_manager.credit_sale_proceeds(sale_proceeds, ...)

            # Delete holding if quantity becomes 0
            if holding.quantity == 0:
                db_session.delete(holding)

        else:
            # CREATE NEW HOLDING (BUY only)
            holding = SandboxHoldings(
                user_id=self.user_id,
                symbol=position.symbol,
                exchange=position.exchange,
                quantity=position.quantity,
                average_price=position.average_price,
                ltp=position.ltp or position.average_price,
                pnl=Decimal('0.00'),
                pnl_percent=Decimal('0.00'),
                settlement_date=today
            )
            db_session.add(holding)

            # Transfer margin to holdings
            margin_amount = abs(position.quantity) * position.average_price
            fund_manager.transfer_margin_to_holdings(margin_amount, ...)

        # Delete position after settling
        db_session.delete(position)

    db_session.commit()
```

---

### 2. transfer_margin_to_holdings()

**File**: `sandbox/fund_manager.py` (lines 258-284)

```python
def transfer_margin_to_holdings(self, amount, description=""):
    """
    Transfer margin to holdings during T+1 settlement
    Reduces used_margin without crediting available_balance
    (the money is now represented in holdings value, not available cash)
    """

    funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

    amount = Decimal(str(amount))

    # Reduce used margin (release from used_margin)
    # But do NOT credit available_balance - money is now in holdings
    funds.used_margin -= amount

    db_session.commit()

    logger.info(f"Transferred ₹{amount} margin to holdings for user {self.user_id}")
```

**Key Point**: This function is **different** from `release_margin()`:
- `release_margin()`: used_margin -= amount, available_balance += amount (for MIS/NRML closures)
- `transfer_margin_to_holdings()`: used_margin -= amount, available_balance += 0 (for T+1 settlement)

---

### 3. credit_sale_proceeds()

**File**: `sandbox/fund_manager.py` (lines 286-310)

```python
def credit_sale_proceeds(self, amount, description=""):
    """
    Credit sale proceeds from selling CNC holdings
    Increases available_balance when holdings are sold
    """

    funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

    amount = Decimal(str(amount))

    # Credit sale proceeds to available balance
    funds.available_balance += amount

    db_session.commit()

    logger.info(f"Credited ₹{amount} sale proceeds for user {self.user_id}")
```

---

### 4. get_holdings()

**File**: `sandbox/holdings_manager.py` (lines 37-104)

```python
def get_holdings(self, update_mtm=True):
    """
    Get all holdings for the user
    Excludes zero-quantity holdings
    """

    # Get all holdings, excluding zero-quantity holdings
    holdings = SandboxHoldings.query.filter_by(user_id=self.user_id).filter(
        SandboxHoldings.quantity != 0
    ).all()

    if update_mtm:
        self._update_holdings_mtm(holdings)

    holdings_list = []
    total_pnl = Decimal('0.00')
    total_value = Decimal('0.00')
    total_investment = Decimal('0.00')

    for holding in holdings:
        pnl = Decimal(str(holding.pnl))
        total_pnl += pnl

        current_value = abs(holding.quantity) * holding.ltp
        total_value += current_value

        investment_value = abs(holding.quantity) * holding.average_price
        total_investment += investment_value

        holdings_list.append({
            'symbol': holding.symbol,
            'exchange': holding.exchange,
            'product': 'CNC',
            'quantity': holding.quantity,
            'average_price': float(holding.average_price),
            'ltp': float(holding.ltp),
            'pnl': float(pnl),
            'pnlpercent': float(holding.pnl_percent),
            'current_value': float(current_value),
            'settlement_date': holding.settlement_date.strftime('%Y-%m-%d')
        })

    pnl_percent = (total_pnl / total_investment * 100) if total_investment > 0 else 0

    return True, {
        'status': 'success',
        'data': {
            'holdings': holdings_list,
            'statistics': {
                'totalholdingvalue': float(total_value),
                'totalinvvalue': float(total_investment),
                'totalprofitandloss': float(total_pnl),
                'totalpnlpercentage': float(pnl_percent)
            }
        },
        'mode': 'analyze'
    }, 200
```

**Important**: Zero-quantity holdings are filtered out and NOT displayed.

---

## Edge Cases

### Case 1: Multiple Buys, Single Sell

```python
# Day 1: BUY 50 ZEEL @ Rs.100
# Day 2: T+1 Settlement → Holdings (50 @ Rs.100)

# Day 5: BUY 30 ZEEL @ Rs.110
# Day 6: T+1 Settlement → Holdings updated

Holding Update:
- Old: 50 @ Rs.100
- New: 30 @ Rs.110

Total Value = (50 × 100) + (30 × 110) = Rs.8,300
Total Qty = 50 + 30 = 80
New Avg = Rs.8,300 / 80 = Rs.103.75

Result: 80 shares @ Rs.103.75 average price ✓
```

### Case 2: Partial Sell

```python
# Holdings: 100 ZEEL @ Rs.100

# Day 10: SELL 40 ZEEL @ Rs.120
# Day 11: T+1 Settlement

Holding Update:
- Old Qty: 100
- Sell: -40
- New Qty: 100 + (-40) = 60

Average Price: Rs.100 (unchanged)

Sale Proceeds: 40 × Rs.120 = Rs.4,800 (credited)
Holding: 60 @ Rs.100 (remains)
```

### Case 3: Complete Sell (Zero Quantity)

```python
# Holdings: 75 ZEEL @ Rs.114.21

# Day 15: SELL 75 ZEEL @ Rs.120
# Day 16: T+1 Settlement

Holding Update:
- Old Qty: 75
- Sell: -75
- New Qty: 75 + (-75) = 0

Result:
- Holding DELETED from database ✓
- Sale proceeds: 75 × Rs.120 = Rs.9,000 credited ✓
- NOT shown in /holdings API ✓
```

### Case 4: Zero-Quantity Position (Already Squared Off)

```python
# Day 1: BUY 100 ZEEL @ Rs.100 (CNC)
# Day 1: SELL 100 ZEEL @ Rs.110 (CNC, same day)

# Position: qty=0 (closed same day)

# Day 2: T+1 Settlement
Result:
- Position deleted (qty=0, skipped)
- No holding created
- Realized P&L: Rs.1,000 already credited
```

---

## Scheduler Configuration

### APScheduler Job Setup

**File**: `sandbox/squareoff_thread.py` (lines 99-122)

```python
from sandbox.holdings_manager import process_all_t1_settlements

# Schedule T+1 settlement job at midnight (00:00 IST)
settlement_trigger = CronTrigger(
    hour=0,
    minute=0,
    timezone=IST
)

settlement_job = scheduler.add_job(
    func=process_all_t1_settlements,
    trigger=settlement_trigger,
    id='t1_settlement',
    name='T+1 Settlement (CNC to Holdings)',
    replace_existing=True,
    misfire_grace_time=300  # 5 minutes grace time
)

logger.info(f"T+1 Settlement: 00:00 IST (Job ID: {settlement_job.id})")
```

### Manual Trigger (For Testing)

```python
# Run T+1 settlement manually
from sandbox.holdings_manager import process_all_t1_settlements

process_all_t1_settlements()
```

Or via command line:
```bash
cd openalgo
python -c "from sandbox.holdings_manager import process_all_t1_settlements; from database.sandbox_db import init_db; init_db(); process_all_t1_settlements()"
```

---

## API Reference

### Get Holdings

**Endpoint**: `POST /api/v1/holdings`

**Request**:
```python
import requests

payload = {"apikey": "your_api_key"}
response = requests.post(
    "http://127.0.0.1:5000/api/v1/holdings",
    json=payload
)
print(response.json())
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "holdings": [
      {
        "symbol": "ZEEL",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 75,
        "average_price": 114.21,
        "ltp": 120.00,
        "pnl": 434.25,
        "pnlpercent": 3.80,
        "current_value": 9000.00,
        "settlement_date": "2025-10-04"
      }
    ],
    "statistics": {
      "totalholdingvalue": 9000.00,
      "totalinvvalue": 8565.75,
      "totalprofitandloss": 434.25,
      "totalpnlpercentage": 3.80
    }
  },
  "mode": "analyze"
}
```

**Service Function**: `sandbox_service.py` (lines 298-323)

---

## Database Schema

### SandboxHoldings Table

```python
class SandboxHoldings(Base):
    __tablename__ = 'sandbox_holdings'

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), nullable=False)

    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)

    quantity = Column(Integer, nullable=False)  # Can be 0 temporarily
    average_price = Column(DECIMAL(10, 2), nullable=False)
    ltp = Column(DECIMAL(10, 2), default=0.00)

    pnl = Column(DECIMAL(10, 2), default=0.00)
    pnl_percent = Column(DECIMAL(10, 4), default=0.00)

    settlement_date = Column(Date, nullable=False)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_holdings_user_symbol', 'user_id', 'symbol', 'exchange'),
    )
```

**File**: `database/sandbox_db.py`

---

## Troubleshooting

### Issue 1: Holdings Not Appearing

**Symptom**: Bought CNC stock yesterday, but not showing in /holdings

**Diagnosis**:
```python
# Check if T+1 settlement ran
from sandbox.holdings_manager import HoldingsManager
hm = HoldingsManager(user_id)
success, msg = hm.process_t1_settlement()
print(msg)
```

**Solutions**:
1. Wait for midnight (00:00 IST) for automatic settlement
2. Manually trigger settlement (for testing)
3. Check scheduler status: `/sandbox` settings page
4. Check logs for settlement errors

---

### Issue 2: Zero-Quantity Holdings Showing

**Symptom**: Holdings showing with 0 quantity

**This should NOT happen** - zero-quantity holdings are:
1. Filtered from `get_holdings()` response (line 49-51)
2. Deleted during T+1 settlement (line 189-191)

**If this occurs**, it indicates a bug. Report with:
- User ID
- Symbol
- Holding quantity
- Settlement date

---

### Issue 3: Fund Balance Mismatch

**Symptom**: `available_balance + holdings_value ≠ total_capital`

**Diagnosis**:
```python
from sandbox.fund_manager import FundManager
from sandbox.holdings_manager import HoldingsManager

fm = FundManager(user_id)
hm = HoldingsManager(user_id)

# Get funds
funds = fm.get_funds()

# Get holdings
success, holdings_response, _ = hm.get_holdings()
holdings_value = holdings_response['data']['statistics']['totalholdingvalue']

# Check balance
total = funds['availablecash'] + holdings_value
print(f"Available: {funds['availablecash']}")
print(f"Holdings: {holdings_value}")
print(f"Total: {total}")
print(f"Should be: {funds['total_capital']}")
```

**Common Causes**:
1. Unsettled CNC positions (still in used_margin)
2. Missed T+1 settlement
3. Manual fund manipulation

**Solution**: Trigger settlement and verify again.

---

### Issue 4: Margin Not Released After T+1

**Symptom**: `used_margin` still showing amount after T+1 settlement

**Check**:
```python
# View positions
from database.sandbox_db import SandboxPositions
positions = SandboxPositions.query.filter_by(user_id=user_id, product='CNC').all()
for p in positions:
    print(f"{p.symbol}: qty={p.quantity}, created={p.created_at}")
```

**If positions exist with old dates**: Settlement did not run properly.

**Solution**: Manually trigger settlement.

---

## Summary

### CNC Fund Flow Rules

1. **CNC BUY**:
   - Margin blocked (used_margin ↑, available_balance ↓)
   - Full trade value required (1x leverage)

2. **T+1 Settlement (BUY → Holdings)**:
   - Margin transferred to holdings
   - `used_margin ↓`, `available_balance UNCHANGED`
   - Money now in holdings, not available as cash

3. **CNC SELL**:
   - No margin blocked (selling existing holdings)
   - Creates negative quantity position

4. **T+1 Settlement (Process SELL)**:
   - Sale proceeds credited
   - `available_balance ↑`
   - Holding reduced/deleted

5. **Balance Equation**:
   ```
   Total Capital = Available Balance + Used Margin + Holdings Value
   ```

### Key Differences from MIS/NRML

| Aspect | MIS/NRML | CNC |
|--------|----------|-----|
| **Margin** | Blocked, released on close | Blocked, transferred to holdings |
| **Settlement** | Same day (auto square-off) | T+1 (midnight) |
| **Fund Flow** | Margin ↔ Available Balance | Margin → Holdings → Available Balance |
| **Leverage** | 5-10x | 1x (no leverage) |
| **Product** | Intraday/Positional | Delivery |

---

**Version**: 1.0
**Last Updated**: October 2025
**File References**:
- `sandbox/holdings_manager.py` (lines 37-347)
- `sandbox/fund_manager.py` (lines 258-310)
- `sandbox/squareoff_thread.py` (lines 99-122)
- `services/sandbox_service.py` (lines 298-323)
- `database/sandbox_db.py` (SandboxHoldings model)

---

**Previous**: [Position Management](05_position_management.md) | **Next**: [Auto Square-Off](06_auto_squareoff.md)
