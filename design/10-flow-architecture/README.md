# 10 - Flow Architecture

## Overview

Flow is OpenAlgo's visual workflow automation system built with React Flow. It enables users to create complex trading workflows using a node-based drag-and-drop interface, connecting triggers, conditions, and actions.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Flow Architecture                                      │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      React Flow Canvas (Frontend)                            │
│                                                                              │
│  ┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐   │
│  │  Trigger   │────▶│  Condition │────▶│   Action   │────▶│   Output   │   │
│  │   Nodes    │     │   Nodes    │     │   Nodes    │     │   Nodes    │   │
│  │            │     │            │     │            │     │            │   │
│  │ • Webhook  │     │ • Price >  │     │ • Buy      │     │ • Telegram │   │
│  │ • Schedule │     │ • Time     │     │ • Sell     │     │ • Log      │   │
│  │ • Manual   │     │ • Position │     │ • Close    │     │ • Email    │   │
│  └────────────┘     └────────────┘     └────────────┘     └────────────┘   │
│         │                 │                  │                  │           │
│         └─────────────────┴──────────────────┴──────────────────┘           │
│                                    │                                         │
│                           Edges (Connections)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ Save/Execute
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Flow Blueprint (/flow)                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Workflow CRUD                                                       │   │
│  │  • GET/POST/PUT/DELETE /api/workflows                               │   │
│  │                                                                      │   │
│  │  Execution                                                           │   │
│  │  • POST /api/workflows/{id}/execute                                 │   │
│  │  • POST /trigger/{token}                                            │   │
│  │                                                                      │   │
│  │  Scheduling                                                          │   │
│  │  • POST /api/workflows/{id}/schedule                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Flow Execution Engine                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  1. Parse workflow graph (nodes + edges)                              │  │
│  │  2. Topological sort for execution order                             │  │
│  │  3. Execute nodes sequentially                                        │  │
│  │  4. Pass data between connected nodes                                 │  │
│  │  5. Log execution results                                             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         flow.db (SQLite)                                     │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                │
│  │   workflows    │  │  executions    │  │   variables    │                │
│  │                │  │                │  │                │                │
│  │ - id           │  │ - id           │  │ - id           │                │
│  │ - name         │  │ - workflow_id  │  │ - workflow_id  │                │
│  │ - nodes (JSON) │  │ - status       │  │ - key          │                │
│  │ - edges (JSON) │  │ - started_at   │  │ - value        │                │
│  │ - is_active    │  │ - completed_at │  │                │                │
│  │ - webhook_token│  │ - logs (JSON)  │  │                │                │
│  └────────────────┘  └────────────────┘  └────────────────┘                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Node Types

### Trigger Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **Webhook** | External HTTP trigger | Token, auth type |
| **Schedule** | Time-based trigger | Cron expression |
| **Manual** | Manual execution | Button click |
| **Market Open** | Market timing trigger | Exchange |
| **Market Close** | Market timing trigger | Exchange |

### Condition Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **Price Condition** | Check symbol price | Symbol, operator, value |
| **Time Condition** | Check current time | Start time, end time |
| **Position Check** | Check position exists | Symbol, exchange |
| **Day Filter** | Filter by weekday | Selected days |

### Action Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **Place Order** | Execute trade | Symbol, action, qty, product |
| **Smart Order** | Position-based order | Symbol, position_size |
| **Close Position** | Close existing position | Symbol, exchange |
| **Cancel Orders** | Cancel pending orders | Symbol or all |

### Output Nodes

| Node | Description | Configuration |
|------|-------------|---------------|
| **Telegram** | Send notification | Message template |
| **Log** | Write to log | Log level, message |
| **Variable** | Store value | Variable name |

## Database Schema

**Location:** `database/flow_db.py`

```python
class Workflow(Base):
    __tablename__ = 'workflows'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    nodes = Column(JSON, default=[])           # React Flow nodes
    edges = Column(JSON, default=[])           # React Flow edges
    is_active = Column(Boolean, default=True)
    schedule_job_id = Column(String(50))       # APScheduler job ID
    webhook_token = Column(String(64))         # Unique webhook token
    webhook_secret = Column(String(64))        # For HMAC validation
    webhook_enabled = Column(Boolean, default=False)
    webhook_auth_type = Column(String(20))     # 'none', 'token', 'hmac'
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class WorkflowExecution(Base):
    __tablename__ = 'workflow_executions'

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id'))
    status = Column(String(20))                # 'running', 'completed', 'failed'
    trigger_type = Column(String(20))          # 'manual', 'webhook', 'schedule'
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    logs = Column(JSON, default=[])            # Execution logs
    error_message = Column(Text)

class WorkflowVariable(Base):
    __tablename__ = 'workflow_variables'

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id'))
    key = Column(String(100), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=func.now())
```

## API Endpoints

### Workflow Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows` | GET | List all workflows |
| `/flow/api/workflows` | POST | Create workflow |
| `/flow/api/workflows/{id}` | GET | Get workflow |
| `/flow/api/workflows/{id}` | PUT | Update workflow |
| `/flow/api/workflows/{id}` | DELETE | Delete workflow |

### Execution

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows/{id}/execute` | POST | Manual execute |
| `/flow/api/workflows/{id}/executions` | GET | Get execution history |
| `/flow/trigger/{token}` | POST | Webhook trigger |
| `/flow/trigger/{token}/{symbol}` | POST | Webhook with symbol |

### Scheduling

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows/{id}/schedule` | POST | Set schedule |
| `/flow/api/workflows/{id}/schedule` | DELETE | Remove schedule |

## Webhook Integration

### Webhook URL Format

```
POST /flow/trigger/{webhook_token}
POST /flow/trigger/{webhook_token}/{symbol}
```

### Authentication Types

| Type | Description | Header |
|------|-------------|--------|
| `none` | No authentication | - |
| `token` | Bearer token | `Authorization: Bearer {secret}` |
| `hmac` | HMAC-SHA256 signature | `X-Signature: {hmac}` |

### TradingView Alert Example

```json
// Webhook URL: http://your-domain/flow/trigger/abc123/{{ticker}}

// Alert message (optional body)
{
    "action": "{{strategy.order.action}}",
    "price": "{{close}}"
}
```

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Execution Flow                       │
└─────────────────────────────────────────────────────────────────┘

Trigger (Webhook/Schedule/Manual)
              │
              ▼
┌─────────────────────────┐
│  1. Load Workflow       │
│     - Get nodes/edges   │
│     - Validate active   │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  2. Create Execution    │
│     - Status: running   │
│     - Log trigger type  │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  3. Topological Sort    │
│     - Order by deps     │
│     - Find start nodes  │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│  4. Execute Nodes Sequentially          │
│                                         │
│  For each node:                         │
│    ├─ Get input from connected nodes   │
│    ├─ Execute node logic               │
│    ├─ Store output                     │
│    └─ Log result                       │
└───────────┬─────────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│  5. Complete Execution  │
│     - Status: completed │
│     - Save logs         │
└─────────────────────────┘
```

## Scheduling with APScheduler

```python
from services.flow_scheduler_service import schedule_workflow

# Schedule workflow to run at specific times
schedule_workflow(
    workflow_id=1,
    cron_expression="0 9 * * 1-5"  # 9 AM on weekdays
)
```

### Cron Expression Format

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6, Mon=0)
│ │ │ │ │
* * * * *
```

## React Flow Integration

### Node Data Structure

```javascript
{
  id: "node_1",
  type: "placeOrder",
  position: { x: 100, y: 200 },
  data: {
    label: "Buy SBIN",
    symbol: "SBIN",
    exchange: "NSE",
    action: "BUY",
    quantity: 10,
    product: "MIS",
    pricetype: "MARKET"
  }
}
```

### Edge Data Structure

```javascript
{
  id: "edge_1",
  source: "node_1",
  target: "node_2",
  sourceHandle: "output",
  targetHandle: "input"
}
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/flow.py` | Flow API endpoints |
| `database/flow_db.py` | Database models |
| `services/flow_execution_service.py` | Execution engine |
| `services/flow_scheduler_service.py` | APScheduler integration |
| `frontend/src/pages/Flow.tsx` | React Flow canvas |
| `frontend/src/components/flow/` | Custom node components |
