# 42 - Action Center

## Overview

The Action Center is a centralized order approval system for semi-automated trading. When enabled, orders are queued for manual approval before execution, essential for managed accounts and regulatory compliance (RA - Relationship Advisor mode).

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Action Center Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

                           External Order Request
                           (TradingView, API, etc.)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Order Router Service                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  should_route_to_pending(api_key, api_type)                          │   │
│  │                                                                      │   │
│  │  Check 1: Is user in semi_auto mode?                                │   │
│  │  Check 2: Is this a restricted operation?                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│              ┌─────────────────────┴─────────────────────┐                  │
│              │                                           │                   │
│         Auto Mode                                   Semi-Auto Mode           │
│         or Restricted                               (Queue Order)            │
│              │                                           │                   │
│              ▼                                           ▼                   │
│      Execute Immediately                        Create Pending Order         │
│      with Broker                                in Action Center             │
└─────────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Action Center UI                                    │
│                          /action-center                                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  [Pending (3)]  [Approved]  [Rejected]  [All Orders]                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Statistics                                                          │   │
│  │  Pending: 3  │  Buy: 2  │  Sell: 1  │  Approved: 15  │  Rejected: 2 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Strategy │ Symbol │ Exchange │ Action │ Qty │ Price │ Actions      │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  MyStrat  │ SBIN   │ NSE      │ BUY    │ 100 │ MKT   │ ✓ Approve    │   │
│  │           │        │          │        │     │       │ ✗ Reject     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│                         [Approve All Pending]                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                          User clicks Approve
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Pending Order Execution Service                           │
│                                                                              │
│  1. Mark order status = 'approved'                                          │
│  2. Execute order with broker API                                           │
│  3. Get broker order status                                                 │
│  4. Update broker_order_id and broker_status                                │
│  5. Emit SocketIO event                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Order Mode Configuration

### Setting Order Mode

```python
# Via API Key settings page
order_mode = 'auto'       # Direct execution (default)
order_mode = 'semi_auto'  # Queue for approval
```

### Mode Toggle API

```
POST /apikey/mode
Content-Type: application/json

{"mode": "semi_auto"}
```

## Semi-Auto Workflow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Semi-Auto Order Flow                                 │
│                                                                             │
│  1. Order Received ────────────────────────────────────────────────────►   │
│           │                                                                 │
│           ▼                                                                 │
│  2. Check Order Mode ──────────────────────────────────────────────────►   │
│           │                                                                 │
│           │ semi_auto = True                                               │
│           ▼                                                                 │
│  3. Create Pending Order ──────────────────────────────────────────────►   │
│           │                                                                 │
│           ├──► Store in pending_orders table                               │
│           │                                                                 │
│           ├──► Emit 'pending_order_created' SocketIO event                 │
│           │                                                                 │
│           └──► Return pending_order_id to caller                           │
│                       │                                                     │
│                       ▼                                                     │
│  4. User Reviews in Action Center ─────────────────────────────────────►   │
│           │                                                                 │
│           ├──────────────────┬──────────────────┐                          │
│           │                  │                  │                           │
│        Approve            Reject             Ignore                         │
│           │                  │                  │                           │
│           ▼                  ▼                  ▼                           │
│  5a. Execute Order    5b. Mark Rejected    5c. Stays Pending               │
│      with Broker          Store reason                                      │
│           │                  │                                              │
│           ▼                  ▼                                              │
│  6. Update Broker      Emit SocketIO                                        │
│     Status                Event                                             │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### pending_orders Table

```
┌────────────────────────────────────────────────────────────────┐
│                    pending_orders table                         │
├──────────────────┬──────────────┬──────────────────────────────┤
│ Column           │ Type         │ Description                  │
├──────────────────┼──────────────┼──────────────────────────────┤
│ id               │ INTEGER PK   │ Unique order identifier      │
│ user_id          │ VARCHAR(255) │ User who placed order        │
│ api_type         │ VARCHAR(50)  │ Order type                   │
│ order_data       │ TEXT         │ JSON order details           │
│ created_at       │ DATETIME     │ Creation time (UTC)          │
│ created_at_ist   │ VARCHAR(50)  │ Creation time (IST)          │
│ status           │ VARCHAR(20)  │ pending/approved/rejected    │
│ approved_at      │ DATETIME     │ Approval time (UTC)          │
│ approved_at_ist  │ VARCHAR(50)  │ Approval time (IST)          │
│ approved_by      │ VARCHAR(255) │ Approver username            │
│ rejected_at      │ DATETIME     │ Rejection time (UTC)         │
│ rejected_at_ist  │ VARCHAR(50)  │ Rejection time (IST)         │
│ rejected_by      │ VARCHAR(255) │ Rejector username            │
│ rejected_reason  │ TEXT         │ Reason for rejection         │
│ broker_order_id  │ VARCHAR(255) │ Broker's order ID            │
│ broker_status    │ VARCHAR(20)  │ complete/open/rejected       │
└──────────────────┴──────────────┴──────────────────────────────┘
```

### Indexes

```sql
CREATE INDEX idx_user_status ON pending_orders(user_id, status);
CREATE INDEX idx_created_at ON pending_orders(created_at);
```

## Supported Order Types

| API Type | Description |
|----------|-------------|
| placeorder | Standard order |
| smartorder | Position-aware order |
| basketorder | Multiple orders |
| splitorder | Split large orders |
| optionsorder | Options contracts |

## Restricted Operations

These operations ALWAYS execute immediately, even in semi-auto mode:

| Operation | Reason |
|-----------|--------|
| closeposition | Prevent stuck positions |
| closeallpositions | Emergency close |
| cancelorder | Order management |
| cancelallorder | Bulk cancel |
| modifyorder | Order adjustment |
| orderstatus | Status query |
| orderbook | Data retrieval |
| tradebook | Data retrieval |
| positions | Data retrieval |
| holdings | Data retrieval |
| funds | Data retrieval |

## API Endpoints

### Get Orders

```
POST /action-center/api/data?status=pending
```

**Response:**
```json
{
    "status": "success",
    "orders": [
        {
            "id": 1,
            "strategy": "MyStrategy",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 100,
            "price": 0,
            "price_type": "MARKET",
            "product": "MIS",
            "order_type": "placeorder",
            "status": "pending",
            "created_at": "5 minutes ago"
        }
    ],
    "statistics": {
        "total_pending": 3,
        "total_approved": 15,
        "total_rejected": 2,
        "total_buy_orders": 10,
        "total_sell_orders": 10
    }
}
```

### Approve Order

```
POST /action-center/approve/{order_id}
```

**Response:**
```json
{
    "status": "success",
    "message": "Order approved and executed",
    "broker_order_id": "123456789"
}
```

### Reject Order

```
POST /action-center/reject/{order_id}
Content-Type: application/json

{"reason": "Invalid price level"}
```

### Approve All

```
POST /action-center/approve-all
```

**Response:**
```json
{
    "status": "success",
    "approved": 5,
    "executed": 5,
    "failed": 0
}
```

### Delete Order

```
DELETE /action-center/delete/{order_id}
```

Note: Only approved or rejected orders can be deleted.

### Get Pending Count

```
GET /action-center/count
```

**Response:**
```json
{
    "count": 3
}
```

## Real-Time Updates

### SocketIO Events

| Event | Trigger | Data |
|-------|---------|------|
| pending_order_created | New order queued | order_id, user_id |
| pending_order_updated | Approve/Reject | order_id, status |

### Frontend Handling

```typescript
// Listen for new orders
socket.on('pending_order_created', () => {
    playAlertSound();
    showToast('New order pending approval');
    refreshOrders();
});

// Listen for status changes
socket.on('pending_order_updated', () => {
    refreshOrders();
});
```

## React Component Features

### Tabbed Interface

```
[Pending (3)]  [Approved]  [Rejected]  [All Orders]
     ↓
  (pulse animation when pending > 0)
```

### Statistics Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  Pending: 3    │    Buy: 2    │    Sell: 1    │    Approved: 15 │
│  (yellow)           (green)        (red)            (green)     │
└─────────────────────────────────────────────────────────────────┘
```

### Order Table Columns

| Column | Content |
|--------|---------|
| Strategy | Strategy name |
| Symbol | Trading symbol |
| Exchange | NSE/NFO/MCX badge |
| Action | BUY (green) / SELL (red) |
| Quantity | Order quantity |
| Price | Price or "MARKET" |
| Order Type | placeorder/smartorder/etc |
| Product | CNC/MIS/NRML badge |
| Created | Relative time ("5 min ago") |
| Actions | Approve/Reject/Delete buttons |

### Expandable Details

Click chevron to view raw order data:

```
┌─────────────────────────────────────────────────────────────────┐
│  ▼ Order Details                                                │
│                                                                 │
│  apikey: ****                                                   │
│  strategy: MyStrategy                                           │
│  symbol: SBIN                                                   │
│  exchange: NSE                                                  │
│  action: BUY                                                    │
│  quantity: 100                                                  │
│  pricetype: MARKET                                              │
│  product: MIS                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Service Implementation

### Order Router

```python
def should_route_to_pending(api_key, api_type=None):
    """Check if order should be queued"""
    # Skip restricted operations
    if api_type in IMMEDIATE_EXECUTION_OPERATIONS:
        return False

    # Check user's order mode
    user_id = get_user_id_from_api_key(api_key)
    order_mode = get_order_mode(user_id)

    return order_mode == 'semi_auto'
```

### Queue Order

```python
def queue_order(api_key, order_data, api_type):
    """Queue order for approval"""
    user_id = get_user_id_from_api_key(api_key)

    pending_order_id = create_pending_order(
        user_id=user_id,
        api_type=api_type,
        order_data=order_data
    )

    # Emit real-time event
    socketio.emit('pending_order_created', {
        'order_id': pending_order_id,
        'user_id': user_id
    })

    return True, {
        'status': 'success',
        'message': 'Order queued for approval',
        'mode': 'semi_auto',
        'pending_order_id': pending_order_id
    }, 200
```

### Execute Approved Order

```python
def execute_approved_order(pending_order_id):
    """Execute approved order with broker"""
    order = get_pending_order_by_id(pending_order_id)

    # Route to appropriate service
    if order.api_type == 'placeorder':
        result = place_order(order.order_data, api_key)
    elif order.api_type == 'smartorder':
        result = place_smart_order(order.order_data, api_key)
    # ... other types

    # Update broker status
    update_broker_status(
        pending_order_id,
        result['orderid'],
        result['broker_status']
    )

    return result
```

## Security & Compliance

### Audit Trail

All actions are logged with:
- Timestamp (IST)
- Username
- Action taken
- Reason (for rejections)

### API Key Security

- API keys never stored in pending_orders
- Only user_id reference maintained
- Keys retrieved at execution time

### Analyzer Mode Restriction

When in semi_auto mode, analyzer toggle is blocked to ensure RA compliance.

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/action_center_db.py` | PendingOrder model |
| `services/action_center_service.py` | Order parsing, stats |
| `services/order_router_service.py` | Route decisions |
| `services/pending_order_execution_service.py` | Execute approved |
| `blueprints/orders.py` | Action center routes |
| `blueprints/apikey.py` | Mode toggle |
| `frontend/src/pages/ActionCenter.tsx` | React UI |
