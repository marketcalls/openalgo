# Action Center & Order Mode System

## Overview

The Action Center is OpenAlgo's semi-automated order management system designed for SEBI Research Analyst compliance. It provides a manual approval workflow where orders are queued for user review before broker execution, enabling proper separation between advisory (RA) and execution authority (Client).

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Order Flow                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│    API Request                                                           │
│         │                                                                │
│         ▼                                                                │
│  ┌──────────────┐     ┌──────────────────┐                              │
│  │ Order Router │────►│ Check Order Mode │                              │
│  │   Service    │     │  (auto/semi_auto)│                              │
│  └──────────────┘     └────────┬─────────┘                              │
│                                │                                         │
│              ┌─────────────────┼─────────────────┐                      │
│              ▼                                   ▼                       │
│    ┌─────────────────┐              ┌─────────────────┐                 │
│    │   Auto Mode     │              │  Semi-Auto Mode │                 │
│    │ (Immediate Exec)│              │  (Queue Order)  │                 │
│    └────────┬────────┘              └────────┬────────┘                 │
│             │                                 │                          │
│             ▼                                 ▼                          │
│    ┌─────────────────┐              ┌─────────────────┐                 │
│    │  Broker API     │              │  Action Center  │                 │
│    │   Execution     │              │   (Pending DB)  │                 │
│    └─────────────────┘              └────────┬────────┘                 │
│                                              │                          │
│                          ┌───────────────────┼───────────────────┐      │
│                          ▼                                       ▼      │
│                 ┌─────────────────┐                 ┌─────────────────┐ │
│                 │ User Approves   │                 │ User Rejects    │ │
│                 │ via Web UI      │                 │ via Web UI      │ │
│                 └────────┬────────┘                 └────────┬────────┘ │
│                          │                                   │          │
│                          ▼                                   ▼          │
│                 ┌─────────────────┐                 ┌─────────────────┐ │
│                 │ Execute Order   │                 │  Mark Rejected  │ │
│                 │ via Broker API  │                 │  (No Execution) │ │
│                 └─────────────────┘                 └─────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Locations

| Component | File Location | Purpose |
|-----------|---------------|---------|
| Order Router | `services/order_router_service.py` | Routes orders to queue or immediate execution |
| Action Center DB | `database/action_center_db.py` | PendingOrder model and database operations |
| Execution Service | `services/pending_order_execution_service.py` | Executes approved orders |
| Order Mode Storage | `database/auth_db.py` (ApiKeys.order_mode) | Stores user's order mode preference |
| Web Interface | `blueprints/orders.py` | Action Center routes and UI handlers |
| Templates | `templates/action_center.html` | Web dashboard UI |

## Order Mode System

### Mode Types

**Auto Mode (Default)**
- Orders execute immediately via broker API
- No manual intervention required
- Suitable for fully automated strategies

**Semi-Auto Mode**
- Orders queued in Action Center
- Requires manual approval before broker execution
- Designed for SEBI RA compliance

### Order Mode Storage

```python
# database/auth_db.py - ApiKeys model
class ApiKeys(Base):
    __tablename__ = 'api_keys'

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    api_key = Column(String(255), unique=True, nullable=False)
    order_mode = Column(String(20), default='auto')  # 'auto' or 'semi_auto'
    # ... other fields
```

### Mode Retrieval

```python
# services/order_router_service.py
def should_route_to_pending(api_key: str, api_type: Optional[str] = None) -> bool:
    """
    Determine if order should be routed to Action Center

    Returns:
        True if semi_auto mode and not an immediate operation
        False if auto mode or operation should execute immediately
    """
    # Check for immediate execution operations
    if api_type and api_type.lower() in IMMEDIATE_EXECUTION_OPERATIONS:
        return False

    # Get user's order mode
    user_id = verify_api_key(api_key)
    order_mode = get_order_mode(user_id)

    return order_mode == 'semi_auto'
```

## Operation Categories

### Immediate Execution Operations

These operations always execute immediately, regardless of order mode:

```python
IMMEDIATE_EXECUTION_OPERATIONS = {
    'closeallpositions',  # Close all positions
    'closeposition',      # Close specific position
    'cancelorder',        # Cancel pending order
    'cancelallorder',     # Cancel all orders
    'modifyorder',        # Modify existing order
    'orderstatus',        # Get order status
    'orderbook',          # View orderbook
    'tradebook',          # View tradebook
    'positions',          # View positions
    'holdings',           # View holdings
    'funds',              # View funds
    'openposition'        # Get open position
}
```

### Queueable Operations

These operations are queued in semi-auto mode:

| Operation | API Type | Description |
|-----------|----------|-------------|
| Place Order | `placeorder` | Regular order placement |
| Smart Order | `smartorder` | Position-sized order |
| Basket Order | `basketorder` | Multiple orders batch |
| Split Order | `splitorder` | Large order splitting |
| Options Order | `optionsorder` | Options trading |

## SEBI Research Analyst Compliance

### Regulatory Framework

The Action Center implements SEBI RA regulations requiring:

1. **Separation of Duties**: RA provides signals, client approves execution
2. **Client Control**: Client retains final decision on all trades
3. **Audit Trail**: Complete logging of order lifecycle
4. **No Unilateral Actions**: RA cannot close positions or cancel orders

### Blocked Operations in Semi-Auto Mode

When in semi-auto mode + live trading, these operations return HTTP 403:

| Operation | Error Message |
|-----------|---------------|
| `closeposition` | "Operation closeposition is not allowed in Semi-Auto mode..." |
| `cancelorder` | "Operation cancelorder is not allowed in Semi-Auto mode..." |
| `cancelallorder` | "Operation cancelallorder is not allowed in Semi-Auto mode..." |
| `modifyorder` | "Operation modifyorder is not allowed in Semi-Auto mode..." |
| `analyzer/toggle` | "Operation analyzer/toggle is not allowed in Semi-Auto mode..." |

### Implementation Example

```python
# services/close_position_service.py
def close_position(position_data, api_key, auth_token=None, broker=None):
    # Check semi-auto mode restriction (for API calls only)
    if api_key and not (auth_token and broker):
        order_mode = get_order_mode(api_key)

        # Block if semi-auto AND live trading (not sandbox)
        if order_mode == 'semi_auto' and not get_analyze_mode():
            return False, {
                'status': 'error',
                'message': 'Operation closeposition is not allowed in Semi-Auto mode...'
            }, 403

    # Proceed with execution...
```

### Client Direct Access

Clients bypass all restrictions via UI buttons:

```python
# When auth_token and broker are passed directly (UI buttons)
if auth_token and broker:
    # Skip order mode check - client has direct control
    return execute_operation(...)
```

## Database Schema

### PendingOrder Model

```python
# database/action_center_db.py
class PendingOrder(Base):
    __tablename__ = 'pending_orders'

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    api_type = Column(String(50), nullable=False)        # placeorder, smartorder, etc.
    order_data = Column(Text, nullable=False)            # JSON serialized order data

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=func.now())
    created_at_ist = Column(String(50))                  # Human-readable IST

    # Status tracking
    status = Column(String(20), default='pending')       # pending, approved, rejected

    # Approval tracking
    approved_at = Column(DateTime(timezone=True))
    approved_at_ist = Column(String(50))
    approved_by = Column(String(255))

    # Rejection tracking
    rejected_at = Column(DateTime(timezone=True))
    rejected_at_ist = Column(String(50))
    rejected_by = Column(String(255))
    rejected_reason = Column(Text)

    # Broker execution tracking
    broker_order_id = Column(String(255))
    broker_status = Column(String(20))                   # open, complete, rejected, cancelled

    __table_args__ = (
        Index('idx_user_status', 'user_id', 'status'),
        Index('idx_created_at', 'created_at'),
    )
```

### Status Lifecycle

```
┌────────────────────────────────────────────────────────────┐
│                    Status Lifecycle                         │
├────────────────────────────────────────────────────────────┤
│                                                             │
│                       ┌─────────┐                          │
│                       │ pending │                          │
│                       └────┬────┘                          │
│                            │                                │
│            ┌───────────────┼───────────────┐               │
│            ▼                               ▼                │
│      ┌──────────┐                   ┌──────────┐           │
│      │ approved │                   │ rejected │           │
│      └────┬─────┘                   └──────────┘           │
│           │                                                 │
│           ▼                                                 │
│    ┌──────────────┐                                        │
│    │ broker_status│                                        │
│    │  (open/      │                                        │
│    │  complete/   │                                        │
│    │  rejected/   │                                        │
│    │  cancelled)  │                                        │
│    └──────────────┘                                        │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

## Order Router Service

### Routing Logic

```python
# services/order_router_service.py
def queue_order(api_key: str, order_data: Dict, api_type: str):
    """
    Queue an order to Action Center

    Steps:
    1. Verify API key and get user_id
    2. Clean order data (remove apikey)
    3. Create pending order record
    4. Emit Socket.IO notification
    5. Return success with pending_order_id
    """
    user_id = verify_api_key(api_key)

    # Clean sensitive data
    order_data_clean = order_data.copy()
    del order_data_clean['apikey']

    # Create pending order
    pending_order_id = create_pending_order(user_id, api_type, order_data_clean)

    # Real-time notification
    socketio.emit('pending_order_created', {
        'pending_order_id': pending_order_id,
        'user_id': user_id,
        'api_type': api_type
    })

    return True, {
        'status': 'success',
        'message': 'Order queued for approval in Action Center',
        'mode': 'semi_auto',
        'pending_order_id': pending_order_id
    }, 200
```

### Integration in Order Services

```python
# services/place_order_service.py
def place_order(order_data, api_key=None, auth_token=None, broker=None):
    # Check if should route to pending (semi-auto mode)
    if api_key and not (auth_token and broker):
        if should_route_to_pending(api_key, 'placeorder'):
            return queue_order(api_key, order_data, 'placeorder')

    # Proceed with immediate execution...
```

## Pending Order Execution

### Execution Flow

```python
# services/pending_order_execution_service.py
def execute_approved_order(pending_order_id: int):
    """
    Execute an approved pending order

    Steps:
    1. Get pending order from database
    2. Verify status is 'approved'
    3. Parse stored order data
    4. Get user's API credentials
    5. Route to appropriate service based on api_type
    6. Update broker_order_id and broker_status
    """
    pending_order = get_pending_order_by_id(pending_order_id)

    if pending_order.status != 'approved':
        return False, {'message': 'Order not approved'}, 400

    # Parse order data
    order_data = json.loads(pending_order.order_data)
    api_type = pending_order.api_type

    # Get credentials
    api_key = get_api_key_for_tradingview(pending_order.user_id)
    auth_token = get_auth_token(pending_order.user_id)
    broker = get_broker(pending_order.user_id)

    # Route to service
    if api_type == 'placeorder':
        success, response, code = place_order(order_data, api_key, auth_token, broker)
    elif api_type == 'smartorder':
        success, response, code = place_smart_order(order_data, api_key, auth_token, broker)
    # ... other types

    # Update broker status
    if success and 'orderid' in response:
        update_broker_status(pending_order_id, response['orderid'], 'open')

    return success, response, code
```

## Web Interface

### Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/action-center/` | GET | Action Center dashboard |
| `/action-center/orders` | GET | Get orders (filtered by status) |
| `/action-center/approve/<id>` | POST | Approve pending order |
| `/action-center/reject/<id>` | POST | Reject pending order |
| `/action-center/delete/<id>` | POST | Delete processed order |
| `/action-center/count` | GET | Get pending count (for badge) |

### Dashboard Features

1. **Statistics Cards**
   - Pending Approval count
   - Buy/Sell breakdown
   - Approved count
   - Rejected count

2. **Filter Tabs**
   - Pending (auto-refresh 30s)
   - Approved
   - Rejected
   - All Orders

3. **Order Details Display**
   - Created timestamp (IST with relative time)
   - Symbol, Exchange, Action
   - Quantity, Price, Order Type, Product
   - API Type
   - Queue Status + Broker Status
   - Order ID (if executed)

4. **Actions**
   - Approve button (pending orders)
   - Reject button with reason modal
   - Delete button (processed orders)

### Real-time Updates

```javascript
// static/js/socket-events.js
socket.on('pending_order_created', function(data) {
    // Update badge count
    updatePendingBadge(data.pending_order_id);

    // Show notification
    showNotification(`New ${data.api_type} order queued for approval`);

    // Refresh table if on Action Center page
    if (currentPage === 'action-center') {
        refreshOrdersTable();
    }
});
```

## Sandbox Mode Exception

### Behavior in Sandbox Mode

When analyzer mode is enabled (sandbox/paper trading):

1. **All operations work** - No SEBI restrictions apply
2. **Virtual execution** - Orders execute against sandbox engine
3. **Testing allowed** - RA can test strategies freely

```python
# Example check in services
def close_position(...):
    # Only block in semi-auto + LIVE mode
    if order_mode == 'semi_auto' and not get_analyze_mode():
        return blocked_response()

    # Allow in sandbox mode
    # ...
```

### Behavior Matrix

| Mode | Trading | New Orders | Position Mgmt | Mode Toggle |
|------|---------|------------|---------------|-------------|
| Auto | Live | Immediate | Allowed | Allowed |
| Auto | Sandbox | Immediate | Allowed | Allowed |
| Semi-Auto | Live | Queued | Blocked (API) | Blocked (API) |
| Semi-Auto | Sandbox | Queued | Allowed | N/A |

## API Response Formats

### Semi-Auto Mode Response

```json
{
    "status": "success",
    "message": "Order queued for approval in Action Center",
    "mode": "semi_auto",
    "pending_order_id": 123
}
```

### Auto Mode Response

```json
{
    "status": "success",
    "orderid": "240612000123456"
}
```

### Blocked Operation Response

```json
{
    "status": "error",
    "message": "Operation closeposition is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control."
}
```

## Migration

### Migration Script

```bash
# Run migration to add order_mode support
cd /path/to/openalgo
python upgrade/migrate_order_mode.py
```

### Migration Steps

1. Add `order_mode` column to `api_keys` table
2. Create `pending_orders` table
3. Set default mode to 'auto' for existing users

## Security Considerations

### Data Isolation

- Users can only view their own pending orders
- User_id validated on all operations
- API key verified before queuing

### Audit Trail

- Complete logging of order lifecycle
- Timestamps in IST for all actions
- Approver/rejector identification
- Rejection reason capture

### Sensitive Data Handling

- API key removed from stored order data
- Clean data stored in `order_data` JSON

## Best Practices

### For Research Analysts

1. Use Semi-Auto mode for all client accounts
2. Provide clear order rationale in strategy signals
3. Monitor Action Center for approval status
4. Never hardcode client credentials

### For Clients

1. Review orders before approval
2. Understand order parameters
3. Use UI for direct position management
4. Regular audit of rejected orders

### For Developers

1. Always check order mode before execution
2. Handle blocked operation responses gracefully
3. Implement proper error handling
4. Use Socket.IO for real-time updates

## Troubleshooting

### Common Issues

1. **Orders not appearing in Action Center**
   - Verify semi-auto mode is enabled
   - Check API key validity
   - Confirm order was sent with correct key

2. **Cannot approve orders**
   - Check broker authentication
   - Verify broker API credentials
   - Review execution logs

3. **Badge not updating**
   - Refresh page
   - Check Socket.IO connection
   - Verify `/action-center/count` endpoint

### Debug Logging

```python
# Enable debug logging for order routing
logger.debug(f"Order mode: {order_mode}")
logger.debug(f"Routing to pending: {should_route}")
logger.debug(f"Pending order created: {pending_order_id}")
```

## Future Enhancements

### Planned Features

1. **Bulk Approval** - Approve multiple orders at once
2. **Auto-Expire** - Automatic rejection after timeout
3. **Telegram Notifications** - Alert on new pending orders
4. **Mobile App** - Approve orders from mobile
5. **Risk Limits** - Auto-reject orders exceeding limits

### Technical Improvements

1. **WebSocket Streaming** - Real-time order updates
2. **Redis Queue** - High-performance order queuing
3. **Multi-user Approval** - Maker-checker workflow
4. **API Webhooks** - Notify external systems on approval

---

**Document Version**: 1.0.0
**Last Updated**: December 2025
**Status**: Production Ready
