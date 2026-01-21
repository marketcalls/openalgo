# 10 - Flow Architecture

## Overview

Flow is OpenAlgo's visual workflow automation system built with XYFlow (React Flow). It enables users to create trading strategies as visual node graphs without coding, supporting scheduled execution, webhook triggers, and price alerts.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Flow Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      React Flow Canvas (Frontend)                            │
│                                                                              │
│  ┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐   │
│  │  Trigger   │────▶│  Condition │────▶│   Action   │────▶│   Output   │   │
│  │   Nodes    │     │   Nodes    │     │   Nodes    │     │   Nodes    │   │
│  └────────────┘     └────────────┘     └────────────┘     └────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Save/Execute
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Flow Blueprint (/flow)                               │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │  Workflow CRUD   │  │  Webhook Handler │  │  Scheduler Jobs  │          │
│  │  /api/workflows  │  │  /webhook/{token}│  │  APScheduler     │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Flow Execution Engine                                   │
│                                                                              │
│  WorkflowContext ─── Variables, Conditions, Interpolation                   │
│  NodeExecutor ────── 60+ Node Type Handlers                                 │
│  FlowOpenAlgoClient ─ OpenAlgo API Wrapper                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Database (SQLite)                                    │
│                                                                              │
│  flow_workflows │ flow_workflow_executions │ flow_apscheduler_jobs          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Node Types

### Trigger Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **Start** | Scheduled trigger | scheduleType, time, days, intervalValue |
| **WebhookTrigger** | External HTTP trigger | symbol, exchange (optional) |
| **PriceAlert** | Price condition trigger | symbol, condition, price, percentage |

### Order Execution Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **PlaceOrder** | Single order | symbol, exchange, action, quantity, priceType, product |
| **SmartOrder** | Position-aware order | Same + positionSize |
| **ModifyOrder** | Modify existing | orderId, updated fields |
| **CancelOrder** | Cancel single order | orderId |
| **CancelAllOrders** | Cancel all open | - |
| **ClosePositions** | Close position | symbol, exchange, product |
| **BasketOrder** | Multiple orders | orders (CSV or array) |
| **SplitOrder** | Chunked order | symbol, quantity, splitSize |

### Market Data Nodes

| Node | Description | Returns |
|------|-------------|---------|
| **GetQuote** | Real-time quote | ltp, open, high, low, close, volume |
| **GetDepth** | Order book | bids, asks, totalbuyqty, totalsellqty |
| **History** | OHLCV data | Array of candles |
| **OpenPosition** | Position for symbol | quantity, avgprice, pnl |
| **OptionChain** | Options data | calls, puts, spot_price |
| **OrderBook** | All orders | Array of orders |
| **TradeBook** | All trades | Array of trades |
| **PositionBook** | All positions | Array of positions |
| **Holdings** | Delivery holdings | Array of holdings |
| **Funds** | Account balance | availablecash, marginused |

### Condition Nodes

| Node | Description | Output Handles |
|------|-------------|----------------|
| **PriceCondition** | Compare price | yes / no |
| **PositionCheck** | Check position qty | yes / no |
| **FundCheck** | Check available funds | yes / no |
| **TimeWindow** | Check time range | yes / no |
| **TimeCondition** | Compare with target time | yes / no |
| **AndGate** | Logical AND | single output |
| **OrGate** | Logical OR | single output |
| **NotGate** | Logical NOT | single output |

### Streaming Nodes

| Node | Description | Behavior |
|------|-------------|----------|
| **SubscribeLTP** | Real-time LTP | WebSocket → REST fallback |
| **SubscribeQuote** | Real-time quote | WebSocket mode 2 |
| **SubscribeDepth** | Real-time depth | WebSocket mode 3 |
| **Unsubscribe** | Stop streaming | Cleanup subscription |

### Utility Nodes

| Node | Description |
|------|-------------|
| **Variable** | Set/get/arithmetic operations |
| **Log** | Debug logging |
| **Delay** | Wait for duration |
| **WaitUntil** | Wait until time |
| **HttpRequest** | External API call |
| **TelegramAlert** | Send notification |

## Database Schema

**Location:** `database/flow_db.py`

### FlowWorkflow Table

```sql
CREATE TABLE flow_workflows (
    id                INTEGER PRIMARY KEY,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    nodes             JSON DEFAULT [],      -- React Flow nodes
    edges             JSON DEFAULT [],      -- React Flow edges
    is_active         BOOLEAN DEFAULT FALSE,
    schedule_job_id   VARCHAR(255),         -- APScheduler job ID
    webhook_token     VARCHAR(64) UNIQUE,   -- URL-safe token
    webhook_secret    VARCHAR(64),          -- For authentication
    webhook_enabled   BOOLEAN DEFAULT FALSE,
    webhook_auth_type VARCHAR(20),          -- 'payload' or 'url'
    api_key           VARCHAR(255),         -- Stored on activation
    created_at        DATETIME,
    updated_at        DATETIME
);
```

### FlowWorkflowExecution Table

```sql
CREATE TABLE flow_workflow_executions (
    id           INTEGER PRIMARY KEY,
    workflow_id  INTEGER FOREIGN KEY,
    status       VARCHAR(50),    -- pending, running, completed, failed
    started_at   DATETIME,
    completed_at DATETIME,
    logs         JSON DEFAULT [],
    error        TEXT
);
```

## Execution Engine

**Location:** `services/flow_executor_service.py`

### Execution Flow

```
1. Trigger received (webhook/schedule/manual)
           │
           ▼
2. Load workflow (nodes + edges)
           │
           ▼
3. Initialize context (variables, conditions)
           │
           ▼
4. Find trigger node in graph
           │
           ▼
5. Execute nodes sequentially
   ┌───────┴───────┐
   │ For each node │
   │   • Get input │
   │   • Execute   │
   │   • Store out │
   │   • Log result│
   └───────┬───────┘
           │
           ▼
6. Handle conditions (yes/no branching)
           │
           ▼
7. Complete execution, save logs
```

### Safety Limits

```python
MAX_NODE_DEPTH = 100      # Maximum nesting depth
MAX_NODE_VISITS = 500     # Maximum total node visits
WORKFLOW_LOCKS = {}       # Per-workflow mutex (prevent concurrent execution)
```

### WorkflowContext

Manages variables and interpolation during execution:

```python
class WorkflowContext:
    variables: Dict[str, Any]           # User variables
    condition_results: Dict[str, bool]  # Condition outcomes

    def interpolate(text: str) -> str:
        # Replace {{var}} patterns with values
```

### Built-in Variables

Available in any text field via `{{variable}}` syntax:

| Variable | Example Output |
|----------|----------------|
| `{{timestamp}}` | 2024-01-15 14:30:45 |
| `{{date}}` | 2024-01-15 |
| `{{time}}` | 14:30:45 |
| `{{weekday}}` | Monday |
| `{{webhook.field}}` | Webhook payload data |

## Webhook System

### Webhook URLs

```
POST /flow/webhook/{token}
POST /flow/webhook/{token}/{symbol}
```

### Authentication Methods

**Payload Authentication (default):**
```json
POST /flow/webhook/abc123
{
  "secret": "your_webhook_secret",
  "symbol": "NSE:SBIN-EQ",
  "price": 500.50
}
```

**URL Parameter Authentication:**
```
POST /flow/webhook/abc123?secret=your_webhook_secret
```

### TradingView Integration

```json
// Webhook URL: https://your-domain/flow/webhook/{token}
{
  "secret": "your_secret",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": "{{close}}"
}
```

## Scheduling System

**Location:** `services/flow_scheduler_service.py`

Uses APScheduler with SQLAlchemy job store for persistence.

### Schedule Types

| Type | Configuration | Trigger |
|------|---------------|---------|
| manual | - | Manual only |
| daily | time: "09:15" | Every day at time |
| weekly | time, days: [1,3,5] | Selected weekdays |
| interval | value: 5, unit: "minutes" | Every N units |
| once | executeAt: ISO datetime | One-time |

### Cron Examples

```python
# Daily at 09:15
CronTrigger(hour=9, minute=15)

# Mon-Fri at 14:30
CronTrigger(day_of_week="mon-fri", hour=14, minute=30)

# Every 5 minutes
IntervalTrigger(minutes=5)
```

## Price Monitoring

**Location:** `services/flow_price_monitor_service.py`

Polling-based monitor for price alert triggers.

### Alert Conditions

| Condition | Description |
|-----------|-------------|
| greater_than | LTP > target |
| less_than | LTP < target |
| crossing | Price crosses target (±0.1%) |
| crossing_up | Price crosses above |
| crossing_down | Price crosses below |
| entering_channel | Price enters [lower, upper] |
| exiting_channel | Price exits range |
| moving_up_percent | % increase |
| moving_down_percent | % decrease |

### Monitor Lifecycle

```
1. Workflow activated with priceAlert trigger
           │
           ▼
2. Add alert to monitor (symbol, condition, price)
           │
           ▼
3. Monitor polls every 5 seconds
           │
           ▼
4. Condition met → Execute workflow
           │
           ▼
5. Remove alert from monitor
```

## API Endpoints

### Workflow Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows` | GET | List all workflows |
| `/flow/api/workflows` | POST | Create workflow |
| `/flow/api/workflows/{id}` | GET/PUT/DELETE | CRUD operations |
| `/flow/api/workflows/{id}/activate` | POST | Activate workflow |
| `/flow/api/workflows/{id}/deactivate` | POST | Deactivate workflow |
| `/flow/api/workflows/{id}/execute` | POST | Manual execute |
| `/flow/api/workflows/{id}/executions` | GET | Execution history |

### Webhook Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows/{id}/webhook` | GET | Get webhook config |
| `/flow/api/workflows/{id}/webhook/enable` | POST | Enable webhook |
| `/flow/api/workflows/{id}/webhook/disable` | POST | Disable webhook |
| `/flow/api/workflows/{id}/webhook/regenerate` | POST | New token + secret |

### Public Webhook

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/webhook/{token}` | POST | Trigger workflow |
| `/flow/webhook/{token}/{symbol}` | POST | Trigger with symbol |

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/flow.py` | Flow API endpoints and webhook handler |
| `database/flow_db.py` | Database models (FlowWorkflow, FlowWorkflowExecution) |
| `services/flow_executor_service.py` | Execution engine (WorkflowContext, NodeExecutor) |
| `services/flow_scheduler_service.py` | APScheduler integration |
| `services/flow_price_monitor_service.py` | Price alert monitoring |
| `services/flow_openalgo_client.py` | OpenAlgo API client wrapper |
| `frontend/src/pages/FlowIndex.tsx` | Workflow list UI |
| `frontend/src/pages/FlowEditor.tsx` | Visual editor (XYFlow) |
| `frontend/src/components/flow/nodes/` | Custom node components |
| `frontend/src/components/flow/panels/` | ConfigPanel, ExecutionLogPanel |
