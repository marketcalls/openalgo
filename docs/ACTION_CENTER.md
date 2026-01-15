# OpenAlgo Action Center

## Overview

**OpenAlgo Action Center** is a centralized hub for managing semi-automated trading orders. It provides a manual approval workflow for orders before they are executed by the broker, giving traders full control over their trading decisions.

## Key Features

- **Manual Approval Workflow**: Review and approve orders before broker execution
- **Dual Mode Operation**: Switch between Auto and Semi-Auto modes
- **IST Timestamps**: All orders tracked in Indian Standard Time
- **Comprehensive Status Tracking**: Two-tier status system (Queue + Broker)
- **Real-time Badge Updates**: Pending order count displayed in navigation
- **Audit Trail**: Complete history of who approved/rejected orders and when

## Use Cases

### When to Use Auto Mode (Default)

- Fully automated trading strategies
- High-frequency trading
- Backtested strategies with proven performance
- When immediate execution is required

### When to Use Semi-Auto Mode

- New or unproven trading strategies
- High-risk trades requiring manual verification
- Learning and testing scenarios
- Compliance requirements for manual approval
- Preventing accidental or unauthorized trades

## SEBI Research Analyst (RA) Compliance

### Current Implementation - SEBI RA Compliant ✅

OpenAlgo Action Center's semi-auto mode is designed to comply with SEBI Research Analyst regulations, ensuring proper separation of duties between advisory (RA) and execution authority (Client).

### What Research Analyst CAN Do (in Semi-Auto Mode)

#### 1. Place New Orders (requires client approval via Action Center)

All new order placements are queued for client approval:

- ✅ **placeorder** - Regular order placement
- ✅ **placesmartorder** - Smart order placement with position sizing
- ✅ **basketorder** - Basket of multiple orders
- ✅ **splitorder** - Split large orders into smaller chunks
- ✅ **optionsorder** - Options order placement

**Flow**: RA places order → Goes to Action Center → Client approves/rejects

#### 2. View/Monitor Portfolio (read-only access)

Instant access to portfolio information without approval:

- ✅ **funds** - Check available funds
- ✅ **ping** - Check system connectivity
- ✅ **orderbook** - View all orders
- ✅ **tradebook** - View executed trades
- ✅ **positions** - View open positions
- ✅ **holdings** - View holdings
- ✅ **orderstatus** - Check order status

**Flow**: Instant access, no approval needed

### What Research Analyst CANNOT Do (blocked in Semi-Auto Mode)

#### Position & Order Management (Client-only decisions)

These operations are blocked with HTTP 403 error in semi-auto mode:

- ❌ **closeposition** - Close positions (blocked with error message)
- ❌ **cancelorder** - Cancel pending orders (blocked with error message)
- ❌ **cancelallorder** - Cancel all orders (blocked with error message)
- ❌ **modifyorder** - Modify existing orders (blocked with error message)
- ❌ **analyzer/toggle** - Switch between Analyze (Sandbox) and Live mode (blocked with error message)

**Reason**: These are portfolio management decisions that should be made by the client, not the RA. This ensures compliance with SEBI regulations where RAs provide advisory services but cannot unilaterally manage client positions or control trading environment settings.

**Error Response**:
```json
{
  "status": "error",
  "message": "Operation closeposition is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control."
}
```

### Client Direct Access (UI Buttons)

Clients retain full control through UI interfaces:

- ✅ Client can use UI buttons on `/positions`, `/orderbook` pages
- ✅ These bypass API key restrictions (use auth_token + broker)
- ✅ Client retains full control over their portfolio
- ✅ Works in any mode (Auto or Semi-Auto)

**Flow**: Client clicks button → Executes immediately (no RA involvement)

### Analyze/Sandbox Mode Exception

Testing in sandbox environment has different rules:

- ✅ All operations work in sandbox for testing (including closeposition, cancelorder, etc.)
- ✅ Allows RA to test strategies in virtual environment
- ✅ No real orders executed, so restrictions lifted
- ✅ Perfect for strategy development and validation

**Reason**: Sandbox mode uses virtual capital and simulated execution, so there's no regulatory concern about unauthorized portfolio management.

### Compliance Summary

This implementation ensures:

1. **Separation of Duties**: RA provides signals, client approves execution
2. **Client Control**: Client can always manage positions directly via UI
3. **Transparency**: All RA orders logged and visible in Action Center
4. **Audit Trail**: Complete logging of who approved/rejected orders and when
5. **SEBI Compliance**: RA cannot unilaterally exit positions or modify/cancel orders

The current implementation perfectly matches the SEBI Research Analyst regulatory framework where:
- **Advisory Role (RA)**: Can recommend trades but needs approval
- **Execution Authority (Client)**: Final decision on all portfolio actions

### Behavior Matrix

#### In Semi-Auto Mode + Live Trading

| Operation | Behavior | HTTP Status |
|-----------|----------|-------------|
| **New Orders** (placeorder, smartorder, basketorder, splitorder, optionsorder) | ✅ QUEUED for approval | 200 |
| **Position Management** (closeposition, cancelorder, cancelallorder, modifyorder) | ❌ BLOCKED | 403 |
| **Mode Control** (analyzer/toggle) | ❌ BLOCKED | 403 |
| **Read Operations** (orderstatus, orderbook, tradebook, positions, holdings, funds) | ✅ ALLOWED immediately | 200 |

#### In Semi-Auto Mode + Analyze/Sandbox Mode

| Operation | Behavior | HTTP Status |
|-----------|----------|-------------|
| **New Orders** (placeorder, smartorder, basketorder, splitorder, optionsorder) | ✅ QUEUED for approval (sandbox execution) | 200 |
| **Position Management** (closeposition, cancelorder, cancelallorder, modifyorder) | ✅ ALLOWED immediately (sandbox) | 200 |
| **Read Operations** (orderstatus, orderbook, tradebook, positions, holdings, funds) | ✅ ALLOWED immediately | 200 |

#### In Auto Mode (regardless of analyze mode)

| Operation | Behavior | HTTP Status |
|-----------|----------|-------------|
| **All Operations** | ✅ Execute immediately | 200 |

#### UI Buttons (auth_token + broker passed directly)

| Operation | Behavior | Notes |
|-----------|----------|-------|
| **All Operations** | ✅ Always work regardless of mode | Bypass all API key checks |

### Practical Example

**Scenario**: Research Analyst using Semi-Auto Mode in Live Trading

```python
# RA places a new order - Goes to Action Center ✅
response = api.placeorder({
    "apikey": "...",
    "symbol": "SBIN",
    "action": "BUY",
    "quantity": "100"
})
# Response: {"status": "success", "message": "Order queued for approval", "mode": "semi_auto"}

# RA tries to close a position - Blocked ❌
response = api.closeposition({
    "apikey": "...",
    "symbol": "SBIN"
})
# Response: {"status": "error", "message": "Operation closeposition is not allowed in Semi-Auto mode..."}

# RA can view positions - Allowed ✅
response = api.positions({"apikey": "..."})
# Response: {"status": "success", "data": [...]}

# RA tries to toggle analyzer mode - Blocked ❌
response = api.analyzer_toggle({
    "apikey": "...",
    "mode": True
})
# Response: {"status": "error", "message": "Operation analyzer/toggle is not allowed in Semi-Auto mode..."}

# Client approves order via Action Center UI - Executes ✅
# Client closes position via /positions page UI button - Executes immediately ✅
# Client toggles analyzer mode via UI button - Works immediately ✅
```

---

## Configuration

### Step 1: Navigate to API Key Settings

1. Go to **Profile** → **API Key** page
2. Scroll to **Order Execution Mode** section

### Step 2: Toggle Order Mode

- **Auto Mode (Default)**: Orders execute immediately
  - Toggle switch: OFF (unchecked)
  - Status: Green "Auto Mode"

- **Semi-Auto Mode**: Orders require approval
  - Toggle switch: ON (checked)
  - Status: Orange "Semi-Auto Mode"

### Step 3: Access Action Center

- Navigate to **Action Center** in main menu
- Pending orders appear in "Pending" tab
- Badge shows count of pending orders

## Order Flow

### Auto Mode Flow

```
Order Received → Validation → Broker Execution → Complete
```

### Semi-Auto Mode Flow

```
Order Received → Validation → Action Center Queue → Manual Approval → Broker Execution → Complete
                                                    ↓
                                              Manual Rejection → Rejected
```

## Status System

### Queue Status (Pre-Execution)

- **Pending**: Awaiting manual approval
- **Approved**: User approved, sent to broker
- **Rejected**: User rejected, never sent to broker

### Broker Status (Post-Execution)

- **Open**: Order placed with broker, awaiting fill
- **Complete**: Order fully executed
- **Rejected**: Broker rejected the order
- **Cancelled**: Order was cancelled

## Action Center Features

### Dashboard Statistics

- **Pending Approval**: Orders awaiting action
- **Buy/Sell Orders**: Breakdown by action type
- **Approved Orders**: Successfully executed
- **Rejected Orders**: Declined by user

### Filter Tabs

- **Pending**: Active orders requiring approval (auto-refresh every 30s)
- **Approved**: Orders that were approved and executed
- **Rejected**: Orders that were declined
- **All Orders**: Complete history

### Order Information Display

Each pending order shows:
- Created timestamp (IST) with relative time
- Symbol, Exchange, Action (BUY/SELL)
- Quantity, Price, Order Type, Product Type
- API Type (place/smart/basket/split)
- Queue Status with timestamps
- Broker Status (if applicable)
- Order ID (if executed)

### Actions Available

**For Pending Orders:**
- **Approve**: Execute order with broker
- **Reject**: Decline order with reason

**For Processed Orders:**
- **Delete**: Remove from history

## API Integration

### Order Response (Semi-Auto Mode)

When an order is sent in semi-auto mode:

```json
{
  "status": "success",
  "message": "Order queued for approval in Action Center",
  "mode": "semi_auto",
  "pending_order_id": 123
}
```

### Order Response (Auto Mode)

When an order is sent in auto mode:

```json
{
  "status": "success",
  "orderid": "240612000123456"
}
```

## Supported Order Types

All order types support semi-auto mode:

- **Place Order** (`/placeorder`)
- **Smart Order** (`/placesmartorder`)
- **Basket Order** (`/basketorder`)
- **Split Order** (`/splitorder`)
- **Options Order** (`/optionsorder`)

## Database Schema

### pending_orders Table

```sql
CREATE TABLE pending_orders (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    api_type VARCHAR(50) NOT NULL,
    order_data TEXT NOT NULL,
    created_at DATETIME,
    created_at_ist VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    approved_at DATETIME,
    approved_at_ist VARCHAR(50),
    approved_by VARCHAR(255),
    rejected_at DATETIME,
    rejected_at_ist VARCHAR(50),
    rejected_by VARCHAR(255),
    rejected_reason TEXT,
    broker_order_id VARCHAR(255),
    broker_status VARCHAR(20)
)
```

### api_keys Table (Updated)

Added column:
```sql
order_mode VARCHAR(20) DEFAULT 'auto'
```

## Security Considerations

- **Session Validation**: All actions require valid user session
- **User Isolation**: Users can only see their own pending orders
- **Audit Trail**: Complete history of approvals/rejections
- **No Parameter Changes**: Existing API endpoints unchanged
- **Cache Invalidation**: Automatic cache clearing on mode changes

## Troubleshooting

### Orders Not Appearing in Action Center

1. Verify Semi-Auto mode is enabled in API Key settings
2. Check that API key is valid and not expired
3. Confirm order was sent with correct API key
4. Check browser console for errors

### Badge Not Updating

1. Refresh the page manually
2. Check browser console for fetch errors
3. Verify `/action-center/count` endpoint is accessible
4. Clear browser cache

### Cannot Approve Orders

1. Ensure you have valid broker authentication
2. Check broker API credentials are not expired
3. Verify broker API is accessible
4. Check logs for execution errors

## Migration

To enable this feature on existing installations:

```bash
cd /path/to/openalgo
python upgrade/migrate_order_mode.py
```

This will:
1. Add `order_mode` column to `api_keys` table
2. Create `pending_orders` table
3. Set all existing users to Auto mode

## Best Practices

1. **Start with Auto Mode**: Test strategies in auto mode first
2. **Use Semi-Auto for High-Risk**: Enable semi-auto for unproven strategies
3. **Regular Review**: Check rejected orders to understand strategy behavior
4. **Monitor Pending Queue**: Don't let orders pile up in pending state
5. **Set Alerts**: Use telegram alerts to notify of pending orders

## Technical Architecture

### Components

- **Database Layer**: `database/action_center_db.py`
- **Services Layer**: `services/order_router_service.py`, `services/action_center_service.py`
- **Blueprint**: `blueprints/orders.py` (action-center routes)
- **Template**: `templates/action_center.html`

### Request Flow

```
API Request → Order Service → Router Check → Queue (if semi-auto) → Action Center
                                          ↓
                                    Execute (if auto) → Broker
```

## Support

For issues or questions:
- GitHub: https://github.com/marketcalls/openalgo/issues
- Documentation: https://docs.openalgo.in
