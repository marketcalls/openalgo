# Order Mode API Documentation

## Overview

The Order Mode API allows programmatic control over how orders are executed in OpenAlgo. Users can switch between Auto and Semi-Auto modes, affecting whether orders execute immediately or require manual approval in the Action Center.

## Endpoints

### 1. Get Order Mode

Retrieve the current order mode for a user.

**Endpoint**: `GET /apikey`

**Response**:
```json
{
  "has_api_key": true,
  "api_key": "your-api-key-here",
  "order_mode": "auto"  // or "semi_auto"
}
```

**Note**: This is part of the existing API Key management endpoint.

---

### 2. Update Order Mode

Change the order mode for a user.

**Endpoint**: `POST /apikey/mode`

**Headers**:
```
Content-Type: application/json
X-CSRFToken: <csrf-token>
```

**Request Body**:
```json
{
  "user_id": "username",
  "mode": "semi_auto"  // or "auto"
}
```

**Success Response** (200 OK):
```json
{
  "message": "Order mode updated to semi_auto",
  "mode": "semi_auto"
}
```

**Error Responses**:

400 Bad Request (Invalid mode):
```json
{
  "error": "Invalid mode. Must be 'auto' or 'semi_auto'"
}
```

500 Internal Server Error:
```json
{
  "error": "Failed to update order mode"
}
```

---

### 3. Get Action Center Data

Retrieve pending orders for the Action Center.

**Endpoint**: `GET /action-center?status={filter}`

**Query Parameters**:
- `status` (optional): Filter by status
  - `pending` - Orders awaiting approval (default)
  - `approved` - Orders that were approved
  - `rejected` - Orders that were rejected
  - `all` - All orders

**Success Response** (200 OK):

Returns rendered HTML page with order data.

---

### 4. Get Pending Order Count

Get count of pending orders for badge display.

**Endpoint**: `GET /action-center/count`

**Success Response** (200 OK):
```json
{
  "count": 5
}
```

---

### 5. Approve Pending Order

Approve and execute a pending order.

**Endpoint**: `POST /action-center/approve/{order_id}`

**Headers**:
```
Content-Type: application/json
X-CSRFToken: <csrf-token>
```

**Success Response** (200 OK):
```json
{
  "status": "success",
  "message": "Order approved and executed successfully",
  "broker_order_id": "240612000123456"
}
```

**Warning Response** (varies):
```json
{
  "status": "warning",
  "message": "Order approved but execution failed",
  "error": "Insufficient margin"
}
```

**Error Response** (400 Bad Request):
```json
{
  "status": "error",
  "message": "Failed to approve order"
}
```

---

### 6. Reject Pending Order

Reject a pending order with a reason.

**Endpoint**: `POST /action-center/reject/{order_id}`

**Headers**:
```
Content-Type: application/json
X-CSRFToken: <csrf-token>
```

**Request Body**:
```json
{
  "reason": "Risk too high for current market conditions"
}
```

**Success Response** (200 OK):
```json
{
  "status": "success",
  "message": "Order rejected successfully"
}
```

**Error Response** (400 Bad Request):
```json
{
  "status": "error",
  "message": "Failed to reject order"
}
```

---

### 7. Delete Pending Order

Delete a processed pending order (not in 'pending' status).

**Endpoint**: `DELETE /action-center/delete/{order_id}`

**Headers**:
```
Content-Type: application/json
X-CSRFToken: <csrf-token>
```

**Success Response** (200 OK):
```json
{
  "status": "success",
  "message": "Order deleted successfully"
}
```

**Error Response** (400 Bad Request):
```json
{
  "status": "error",
  "message": "Failed to delete order"
}
```

**Note**: Cannot delete orders in 'pending' status.

---

## Order API Behavior

### Auto Mode (Default)

When `order_mode = 'auto'`, all order endpoints behave as before:

**Request**:
```bash
POST /api/v1/placeorder
{
  "apikey": "your-api-key",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "1",
  "price_type": "MARKET",
  "product_type": "MIS"
}
```

**Response** (Immediate Execution):
```json
{
  "status": "success",
  "orderid": "240612000123456"
}
```

### Semi-Auto Mode

When `order_mode = 'semi_auto'`, orders are queued:

**Request** (Same as above):
```bash
POST /api/v1/placeorder
{
  "apikey": "your-api-key",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "1",
  "price_type": "MARKET",
  "product_type": "MIS"
}
```

**Response** (Queued for Approval):
```json
{
  "status": "success",
  "message": "Order queued for approval in Action Center",
  "mode": "semi_auto",
  "pending_order_id": 123
}
```

## SEBI Research Analyst Compliance

### Operation Restrictions in Semi-Auto Mode

When operating in **Semi-Auto Mode with Live Trading**, certain operations are **blocked** to comply with SEBI Research Analyst regulations:

#### Blocked Operations (HTTP 403)

The following operations return an error in semi-auto mode:

1. `/api/v1/closeposition` - Close positions
2. `/api/v1/cancelorder` - Cancel pending orders
3. `/api/v1/cancelallorder` - Cancel all orders
4. `/api/v1/modifyorder` - Modify existing orders
5. `/api/v1/analyzer/toggle` - Switch between Analyze (Sandbox) and Live mode

**Error Response**:
```json
{
  "status": "error",
  "message": "Operation closeposition is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control."
}
```

**Reason**: These are portfolio management and trading environment control decisions that must be made by the client, not the Research Analyst. This ensures proper separation of duties between advisory (RA) and execution authority (Client). Mode switching (Live/Analyze) is particularly sensitive as it affects whether real capital is at risk.

#### Allowed Operations in Semi-Auto Mode

**New Order Placement** (queued for approval):
1. `/api/v1/placeorder` - Place Order ✅
2. `/api/v1/placesmartorder` - Smart Order ✅
3. `/api/v1/basketorder` - Basket Order ✅
4. `/api/v1/splitorder` - Split Order ✅
5. `/api/v1/optionsorder` - Options Order ✅

**Read-Only Operations** (execute immediately):
1. `/api/v1/funds` - Check available funds ✅
2. `/api/v1/orderbook` - View all orders ✅
3. `/api/v1/tradebook` - View executed trades ✅
4. `/api/v1/positions` - View open positions ✅
5. `/api/v1/holdings` - View holdings ✅
6. `/api/v1/orderstatus` - Check order status ✅

### Sandbox Mode Exception

All operations (including closeposition, cancelorder, etc.) work normally in **Analyze/Sandbox Mode** regardless of order mode setting, since no real trades are executed.

**Example**: Blocked operation in semi-auto + live mode

```python
import requests

# Try to close a position in semi-auto mode
response = requests.post('http://localhost:5000/api/v1/closeposition', json={
    'apikey': 'your-api-key',
    'symbol': 'RELIANCE',
    'exchange': 'NSE',
    'product_type': 'MIS'
})

# Response (HTTP 403):
{
    "status": "error",
    "message": "Operation closeposition is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control."
}
```

### Client UI Access

Clients retain full control via UI buttons on `/positions` and `/orderbook` pages:
- UI buttons bypass API key restrictions
- Use `auth_token` + `broker` parameters
- Work in any mode (Auto or Semi-Auto)
- Execute immediately without approval

This ensures clients can always manage their own positions directly.

---

## Supported Order Endpoints

The following endpoints support order mode routing (queuing in semi-auto):

1. `/api/v1/placeorder` - Place Order
2. `/api/v1/placesmartorder` - Smart Order
3. `/api/v1/basketorder` - Basket Order
4. `/api/v1/splitorder` - Split Order
5. `/api/v1/optionsorder` - Options Order

## Rate Limiting

All Action Center endpoints follow the existing rate limiting configuration:

- Default: `50 requests per second`
- Configurable via `API_RATE_LIMIT` environment variable

## Authentication

### Web Interface

- **Required**: Valid session (cookie-based)
- **CSRF Protection**: Required for all POST/DELETE requests
- **Validation**: `@check_session_validity` decorator

### API Endpoints

- **Required**: Valid API key in request payload
- **Validation**: `verify_api_key()` function
- **Mode Check**: `get_order_mode()` determines routing

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 400 | Bad Request (invalid parameters) |
| 403 | Forbidden (invalid API key or session) |
| 404 | Not Found (order not found) |
| 500 | Internal Server Error |

## Database Structure

### api_keys Table

```sql
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    api_key_hash TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    order_mode VARCHAR(20) DEFAULT 'auto'  -- NEW COLUMN
);
```

### pending_orders Table

```sql
CREATE TABLE pending_orders (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    api_type VARCHAR(50) NOT NULL,
    order_data TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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
);
```

## WebSocket Integration

### Real-time Badge Updates

The Action Center badge updates automatically every 30 seconds:

```javascript
fetch('/action-center/count')
  .then(res => res.json())
  .then(data => {
    // Update badge with count
    badge.textContent = data.count;
  });
```

### Auto-refresh

Pending orders page auto-refreshes every 30 seconds when viewing pending orders.

## Examples

### Example 1: Enable Semi-Auto Mode

```javascript
fetch('/apikey/mode', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': getCSRFToken()
  },
  body: JSON.stringify({
    user_id: 'trader123',
    mode: 'semi_auto'
  })
})
.then(res => res.json())
.then(data => console.log(data));
```

### Example 2: Approve Order

```javascript
fetch('/action-center/approve/5', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': getCSRFToken()
  }
})
.then(res => res.json())
.then(data => console.log(data));
```

### Example 3: Send Order (Auto vs Semi-Auto)

```python
import requests

# Same request for both modes
response = requests.post('http://localhost:5000/api/v1/placeorder', json={
    'apikey': 'your-api-key',
    'symbol': 'RELIANCE',
    'exchange': 'NSE',
    'action': 'BUY',
    'quantity': '1',
    'price_type': 'MARKET',
    'product_type': 'MIS'
})

result = response.json()

# Auto mode response:
# {"status": "success", "orderid": "240612000123456"}

# Semi-auto mode response:
# {"status": "success", "message": "Order queued for approval in Action Center", "mode": "semi_auto", "pending_order_id": 123}
```

## Migration

Existing API integrations require **no changes**. The order mode feature:

- ✅ No parameter changes to existing endpoints
- ✅ Backward compatible responses (auto mode is default)
- ✅ Optional feature (users can stay in auto mode)
- ✅ Existing order logging and tracking unchanged

## Testing

### Test Auto Mode

1. Ensure order_mode is 'auto'
2. Send order via API
3. Verify immediate execution
4. Check orderbook for order

### Test Semi-Auto Mode

1. Set order_mode to 'semi_auto'
2. Send order via API
3. Verify queued response
4. Check Action Center for pending order
5. Approve order
6. Verify broker execution

## Support

For API support:
- Documentation: https://docs.openalgo.in
- GitHub Issues: https://github.com/marketcalls/openalgo/issues
