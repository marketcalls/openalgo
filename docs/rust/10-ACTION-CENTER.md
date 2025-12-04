# OpenAlgo Desktop - Action Center (Semi-Auto Mode)

## Overview

The Action Center is OpenAlgo's semi-automated order management system designed for SEBI Research Analyst (RA) compliance. It provides a manual approval workflow where API orders are queued for user review before broker execution.

---

## SEBI RA Compliance

### Regulatory Requirements

1. **Separation of Duties**: RA provides signals, client approves execution
2. **Client Control**: Client retains final decision on all trades
3. **Audit Trail**: Complete logging of order lifecycle
4. **No Unilateral Actions**: RA cannot close positions via API in live mode

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Order Routing Flow                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                            API Request                                       │
│                                 │                                            │
│                                 ▼                                            │
│                    ┌────────────────────────┐                               │
│                    │   Check Order Mode     │                               │
│                    │  (get_order_mode)      │                               │
│                    └───────────┬────────────┘                               │
│                                │                                             │
│              ┌─────────────────┴─────────────────┐                          │
│              │                                   │                           │
│              ▼                                   ▼                           │
│     ┌─────────────────┐              ┌─────────────────────────┐            │
│     │   AUTO MODE     │              │   SEMI-AUTO MODE        │            │
│     │                 │              │                         │            │
│     │ Immediate       │              │ Queue to Action Center  │            │
│     │ Broker Exec     │              │                         │            │
│     └────────┬────────┘              └────────────┬────────────┘            │
│              │                                    │                          │
│              ▼                                    ▼                          │
│     ┌─────────────────┐              ┌─────────────────────────┐            │
│     │  Broker API     │              │    PendingOrder DB      │            │
│     └─────────────────┘              └────────────┬────────────┘            │
│                                                   │                          │
│                          ┌────────────────────────┼────────────────────────┐│
│                          │                                                 ││
│                          ▼                        ▼                        ▼│
│                 ┌────────────────┐      ┌────────────────┐      ┌──────────┤│
│                 │ User Approves  │      │ User Rejects   │      │ Expires  ││
│                 └───────┬────────┘      └───────┬────────┘      └────┬─────┤│
│                         │                       │                    │      │
│                         ▼                       ▼                    ▼      │
│                 ┌────────────────┐      ┌────────────────┐      ┌──────────┤│
│                 │ Execute via    │      │ Mark Rejected  │      │ Mark     ││
│                 │ Broker API     │      │ with Reason    │      │ Expired  ││
│                 └────────────────┘      └────────────────┘      └──────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### PendingOrder Table

```rust
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct PendingOrder {
    pub id: i64,
    pub user_id: String,
    pub api_type: String,           // placeorder, smartorder, basketorder, etc.
    pub order_data: String,         // JSON serialized order data
    pub status: String,             // pending, approved, rejected, expired

    // Timestamps
    pub created_at: DateTime<Utc>,
    pub created_at_ist: String,     // Human-readable IST

    // Approval tracking
    pub approved_at: Option<DateTime<Utc>>,
    pub approved_at_ist: Option<String>,
    pub approved_by: Option<String>,

    // Rejection tracking
    pub rejected_at: Option<DateTime<Utc>>,
    pub rejected_at_ist: Option<String>,
    pub rejected_by: Option<String>,
    pub rejected_reason: Option<String>,

    // Broker execution tracking
    pub broker_order_id: Option<String>,
    pub broker_status: Option<String>,  // open, complete, rejected, cancelled
}
```

### ApiKeys Order Mode

```rust
// Extension to ApiKeys table
pub struct ApiKeyOrderMode {
    pub api_key_id: i64,
    pub order_mode: String,     // "auto" or "semi_auto"
}
```

---

## Order Mode System

### Mode Types

| Mode | Behavior | Use Case |
|------|----------|----------|
| Auto | Orders execute immediately | Fully automated strategies |
| Semi-Auto | Orders queued for approval | SEBI RA compliance |

### Mode Storage

```rust
pub async fn get_order_mode(api_key: &str) -> Result<OrderMode, DbError> {
    let mode = sqlx::query_scalar!(
        r#"
        SELECT order_mode FROM api_keys
        WHERE api_key = $1
        "#,
        api_key
    )
    .fetch_one(&pool)
    .await?;

    match mode.as_str() {
        "auto" => Ok(OrderMode::Auto),
        "semi_auto" => Ok(OrderMode::SemiAuto),
        _ => Ok(OrderMode::Auto),
    }
}

pub async fn set_order_mode(api_key: &str, mode: OrderMode) -> Result<(), DbError> {
    sqlx::query!(
        r#"
        UPDATE api_keys
        SET order_mode = $1
        WHERE api_key = $2
        "#,
        mode.to_string(),
        api_key
    )
    .execute(&pool)
    .await?;

    Ok(())
}
```

---

## Operation Categories

### Immediate Execution Operations

These always execute immediately regardless of mode:

```rust
pub const IMMEDIATE_EXECUTION_OPERATIONS: &[&str] = &[
    "closeallpositions",    // Emergency position closure (UI only)
    "closeposition",        // Position closure (UI only)
    "cancelorder",          // Cancel pending order
    "cancelallorder",       // Cancel all orders
    "modifyorder",          // Modify existing order
    "orderstatus",          // Get order status
    "orderbook",            // View orderbook
    "tradebook",            // View tradebook
    "positions",            // View positions
    "holdings",             // View holdings
    "funds",                // View funds
    "openposition",         // Get open position
];
```

### Queueable Operations

These are queued in semi-auto mode:

| Operation | API Type | Description |
|-----------|----------|-------------|
| Place Order | `placeorder` | Regular order placement |
| Smart Order | `smartorder` | Position-sized order |
| Basket Order | `basketorder` | Multiple orders batch |
| Split Order | `splitorder` | Large order splitting |
| Options Order | `optionsorder` | Options trading |
| Multi-leg Options | `optionsmultiorder` | Options strategies |

### Blocked Operations (Semi-Auto + Live)

When in semi-auto mode AND live trading (not sandbox):

```rust
pub const BLOCKED_IN_SEMI_AUTO: &[&str] = &[
    "closeposition",        // Cannot close positions via API
    "cancelorder",          // Cannot cancel via API
    "cancelallorder",       // Cannot cancel all via API
    "modifyorder",          // Cannot modify via API
    "analyzer/toggle",      // Cannot toggle mode via API
];
```

---

## Core Components

### 1. Order Router Service

```rust
pub struct OrderRouterService {
    db: SqlitePool,
    pending_orders: Arc<PendingOrderDb>,
}

impl OrderRouterService {
    /// Check if order should route to Action Center
    pub async fn should_route_to_pending(
        &self,
        api_key: &str,
        api_type: &str,
    ) -> Result<bool, RouterError> {
        // Immediate operations bypass routing
        if IMMEDIATE_EXECUTION_OPERATIONS.contains(&api_type.to_lowercase().as_str()) {
            return Ok(false);
        }

        // Get user's order mode
        let order_mode = get_order_mode(api_key).await?;

        Ok(order_mode == OrderMode::SemiAuto)
    }

    /// Queue order to Action Center
    pub async fn queue_order(
        &self,
        api_key: &str,
        order_data: &serde_json::Value,
        api_type: &str,
    ) -> Result<QueueResponse, RouterError> {
        // Verify API key
        let user_id = verify_api_key(api_key).await?;

        // Clean order data (remove apikey)
        let mut clean_data = order_data.clone();
        if let Some(obj) = clean_data.as_object_mut() {
            obj.remove("apikey");
        }

        // Create pending order
        let pending_order_id = self.pending_orders.create(
            &user_id,
            api_type,
            &serde_json::to_string(&clean_data)?,
        ).await?;

        // Emit real-time notification
        self.emit_pending_order_created(pending_order_id, &user_id, api_type).await;

        Ok(QueueResponse {
            status: "success".to_string(),
            message: "Order queued for approval in Action Center".to_string(),
            mode: "semi_auto".to_string(),
            pending_order_id,
        })
    }
}
```

### 2. Pending Order Database

```rust
pub struct PendingOrderDb {
    db: SqlitePool,
}

impl PendingOrderDb {
    /// Create pending order
    pub async fn create(
        &self,
        user_id: &str,
        api_type: &str,
        order_data: &str,
    ) -> Result<i64, DbError> {
        let now = Utc::now();
        let ist = now.with_timezone(&chrono_tz::Asia::Kolkata);

        let id = sqlx::query_scalar!(
            r#"
            INSERT INTO pending_orders (user_id, api_type, order_data, status, created_at, created_at_ist)
            VALUES ($1, $2, $3, 'pending', $4, $5)
            RETURNING id
            "#,
            user_id,
            api_type,
            order_data,
            now,
            ist.format("%Y-%m-%d %H:%M:%S").to_string()
        )
        .fetch_one(&self.db)
        .await?;

        Ok(id)
    }

    /// Get pending orders for user
    pub async fn get_pending(
        &self,
        user_id: &str,
        status: Option<&str>,
    ) -> Result<Vec<PendingOrder>, DbError> {
        let orders = match status {
            Some(s) => {
                sqlx::query_as!(
                    PendingOrder,
                    r#"
                    SELECT * FROM pending_orders
                    WHERE user_id = $1 AND status = $2
                    ORDER BY created_at DESC
                    "#,
                    user_id,
                    s
                )
                .fetch_all(&self.db)
                .await?
            }
            None => {
                sqlx::query_as!(
                    PendingOrder,
                    r#"
                    SELECT * FROM pending_orders
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    "#,
                    user_id
                )
                .fetch_all(&self.db)
                .await?
            }
        };

        Ok(orders)
    }

    /// Approve order
    pub async fn approve(
        &self,
        id: i64,
        approved_by: &str,
    ) -> Result<PendingOrder, DbError> {
        let now = Utc::now();
        let ist = now.with_timezone(&chrono_tz::Asia::Kolkata);

        sqlx::query!(
            r#"
            UPDATE pending_orders
            SET status = 'approved',
                approved_at = $1,
                approved_at_ist = $2,
                approved_by = $3
            WHERE id = $4
            "#,
            now,
            ist.format("%Y-%m-%d %H:%M:%S").to_string(),
            approved_by,
            id
        )
        .execute(&self.db)
        .await?;

        self.get_by_id(id).await
    }

    /// Reject order
    pub async fn reject(
        &self,
        id: i64,
        rejected_by: &str,
        reason: &str,
    ) -> Result<PendingOrder, DbError> {
        let now = Utc::now();
        let ist = now.with_timezone(&chrono_tz::Asia::Kolkata);

        sqlx::query!(
            r#"
            UPDATE pending_orders
            SET status = 'rejected',
                rejected_at = $1,
                rejected_at_ist = $2,
                rejected_by = $3,
                rejected_reason = $4
            WHERE id = $5
            "#,
            now,
            ist.format("%Y-%m-%d %H:%M:%S").to_string(),
            rejected_by,
            reason,
            id
        )
        .execute(&self.db)
        .await?;

        self.get_by_id(id).await
    }

    /// Update broker status after execution
    pub async fn update_broker_status(
        &self,
        id: i64,
        broker_order_id: &str,
        broker_status: &str,
    ) -> Result<(), DbError> {
        sqlx::query!(
            r#"
            UPDATE pending_orders
            SET broker_order_id = $1, broker_status = $2
            WHERE id = $3
            "#,
            broker_order_id,
            broker_status,
            id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Get pending count for badge
    pub async fn get_pending_count(&self, user_id: &str) -> Result<i64, DbError> {
        let count = sqlx::query_scalar!(
            r#"
            SELECT COUNT(*) as count FROM pending_orders
            WHERE user_id = $1 AND status = 'pending'
            "#,
            user_id
        )
        .fetch_one(&self.db)
        .await?;

        Ok(count.unwrap_or(0))
    }
}
```

### 3. Execution Service

```rust
pub struct PendingOrderExecutionService {
    db: SqlitePool,
    pending_db: Arc<PendingOrderDb>,
    order_service: Arc<PlaceOrderService>,
}

impl PendingOrderExecutionService {
    /// Execute an approved pending order
    pub async fn execute_approved_order(
        &self,
        pending_order_id: i64,
    ) -> Result<ExecutionResponse, ExecutionError> {
        // 1. Get pending order
        let pending_order = self.pending_db.get_by_id(pending_order_id).await?;

        // 2. Verify status
        if pending_order.status != "approved" {
            return Err(ExecutionError::InvalidStatus {
                expected: "approved".to_string(),
                actual: pending_order.status,
            });
        }

        // 3. Parse order data
        let order_data: serde_json::Value = serde_json::from_str(&pending_order.order_data)?;

        // 4. Get credentials
        let (auth_token, broker) = get_auth_token_broker_for_user(&pending_order.user_id).await?;

        // 5. Route to appropriate service based on api_type
        let result = match pending_order.api_type.as_str() {
            "placeorder" => {
                self.order_service.place_order(
                    order_data.clone().into(),
                    None,           // No API key (direct call)
                    Some(&auth_token),
                    Some(&broker),
                ).await
            }
            "smartorder" => {
                self.smart_order_service.place_smart_order(
                    order_data.clone().into(),
                    None,
                    Some(&auth_token),
                    Some(&broker),
                ).await
            }
            "basketorder" => {
                self.basket_order_service.place_basket_order(
                    order_data.clone().into(),
                    None,
                    Some(&auth_token),
                    Some(&broker),
                ).await
            }
            _ => {
                return Err(ExecutionError::UnsupportedApiType(pending_order.api_type));
            }
        };

        // 6. Update broker status
        match &result {
            Ok(response) => {
                if let Some(order_id) = response.order_id.as_ref() {
                    self.pending_db.update_broker_status(
                        pending_order_id,
                        order_id,
                        "open",
                    ).await?;
                }
            }
            Err(e) => {
                self.pending_db.update_broker_status(
                    pending_order_id,
                    "",
                    &format!("failed: {}", e),
                ).await?;
            }
        }

        result.map_err(|e| ExecutionError::OrderPlacement(e.to_string()))
    }
}
```

### 4. Semi-Auto Mode Check Service

```rust
pub struct SemiAutoModeService {
    db: SqlitePool,
}

impl SemiAutoModeService {
    /// Check if operation is blocked in semi-auto mode
    pub async fn check_operation_allowed(
        &self,
        api_key: &str,
        api_type: &str,
        is_ui_call: bool,
    ) -> Result<(), OperationBlockedError> {
        // UI calls always allowed
        if is_ui_call {
            return Ok(());
        }

        // Get order mode
        let order_mode = get_order_mode(api_key).await?;

        // If not semi-auto, allowed
        if order_mode != OrderMode::SemiAuto {
            return Ok(());
        }

        // Check if in sandbox mode (allowed in sandbox)
        let analyze_mode = get_analyze_mode().await?;
        if analyze_mode {
            return Ok(());
        }

        // Check if operation is blocked
        if BLOCKED_IN_SEMI_AUTO.contains(&api_type.to_lowercase().as_str()) {
            return Err(OperationBlockedError {
                operation: api_type.to_string(),
                message: format!(
                    "Operation {} is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control.",
                    api_type
                ),
            });
        }

        Ok(())
    }
}
```

---

## API Responses

### Success - Order Queued

```json
{
    "status": "success",
    "message": "Order queued for approval in Action Center",
    "mode": "semi_auto",
    "pending_order_id": 123
}
```

### Error - Operation Blocked

```json
{
    "status": "error",
    "message": "Operation closeposition is not allowed in Semi-Auto mode. Please switch to Auto mode or use the UI for direct control."
}
```

HTTP Status: 403 Forbidden

---

## Tauri Commands

```rust
#[tauri::command]
pub async fn action_center_get_orders(
    state: State<'_, AppState>,
    status: Option<String>,
) -> Result<Vec<PendingOrderView>, String> {
    let user_id = state.get_current_user_id()?;
    let pending_db = &state.pending_db;

    pending_db.get_pending(&user_id, status.as_deref())
        .await
        .map(|orders| orders.into_iter().map(PendingOrderView::from).collect())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn action_center_approve(
    state: State<'_, AppState>,
    pending_order_id: i64,
) -> Result<ExecutionResponse, String> {
    let user_id = state.get_current_user_id()?;
    let pending_db = &state.pending_db;
    let execution_service = &state.execution_service;

    // Approve the order
    pending_db.approve(pending_order_id, &user_id).await
        .map_err(|e| e.to_string())?;

    // Execute the order
    execution_service.execute_approved_order(pending_order_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn action_center_reject(
    state: State<'_, AppState>,
    pending_order_id: i64,
    reason: String,
) -> Result<PendingOrderView, String> {
    let user_id = state.get_current_user_id()?;
    let pending_db = &state.pending_db;

    pending_db.reject(pending_order_id, &user_id, &reason)
        .await
        .map(PendingOrderView::from)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn action_center_delete(
    state: State<'_, AppState>,
    pending_order_id: i64,
) -> Result<(), String> {
    let pending_db = &state.pending_db;

    pending_db.delete(pending_order_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn action_center_count(
    state: State<'_, AppState>,
) -> Result<i64, String> {
    let user_id = state.get_current_user_id()?;
    let pending_db = &state.pending_db;

    pending_db.get_pending_count(&user_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_order_mode(
    state: State<'_, AppState>,
    mode: String,
) -> Result<(), String> {
    let api_key = state.get_current_api_key()?;

    let order_mode = match mode.as_str() {
        "auto" => OrderMode::Auto,
        "semi_auto" => OrderMode::SemiAuto,
        _ => return Err("Invalid mode. Must be 'auto' or 'semi_auto'".to_string()),
    };

    set_order_mode_db(&api_key, order_mode)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_order_mode(
    state: State<'_, AppState>,
) -> Result<String, String> {
    let api_key = state.get_current_api_key()?;

    get_order_mode_db(&api_key)
        .await
        .map(|m| m.to_string())
        .map_err(|e| e.to_string())
}
```

---

## Frontend Integration (Svelte)

### Action Center Store

```typescript
// src/lib/stores/actionCenter.ts
import { writable } from 'svelte/store';
import { invoke } from '@tauri-apps/api/tauri';

interface PendingOrder {
    id: number;
    api_type: string;
    order_data: object;
    status: string;
    created_at_ist: string;
    approved_at_ist?: string;
    rejected_at_ist?: string;
    rejected_reason?: string;
    broker_order_id?: string;
    broker_status?: string;
}

export const pendingOrders = writable<PendingOrder[]>([]);
export const pendingCount = writable<number>(0);

export async function loadOrders(status?: string) {
    const orders = await invoke<PendingOrder[]>('action_center_get_orders', { status });
    pendingOrders.set(orders);
    return orders;
}

export async function approveOrder(id: number) {
    const result = await invoke('action_center_approve', { pendingOrderId: id });
    await loadOrders('pending');
    await updatePendingCount();
    return result;
}

export async function rejectOrder(id: number, reason: string) {
    const result = await invoke('action_center_reject', { pendingOrderId: id, reason });
    await loadOrders('pending');
    await updatePendingCount();
    return result;
}

export async function deleteOrder(id: number) {
    await invoke('action_center_delete', { pendingOrderId: id });
    await loadOrders();
}

export async function updatePendingCount() {
    const count = await invoke<number>('action_center_count');
    pendingCount.set(count);
    return count;
}
```

---

## Status Lifecycle

```
         ┌─────────┐
         │ pending │
         └────┬────┘
              │
   ┌──────────┼──────────┐
   ▼          │          ▼
┌──────────┐  │   ┌──────────┐
│ approved │  │   │ rejected │
└────┬─────┘  │   └──────────┘
     │        │
     ▼        ▼
┌──────────────────┐
│  broker_status   │
│  (open/complete/ │
│  rejected/cancel)│
└──────────────────┘
```

---

## Conclusion

The Action Center provides:

1. **SEBI RA Compliance** - Proper separation between advisory and execution
2. **Client Control** - Manual approval before any trade execution
3. **Audit Trail** - Complete logging of all order lifecycle events
4. **Selective Blocking** - Position/order management blocked via API in semi-auto mode
5. **Real-time Updates** - WebSocket notifications for new pending orders
6. **Flexible Modes** - Easy switching between auto and semi-auto modes
