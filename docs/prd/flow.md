# PRD: Flow - Visual Workflow Automation

> **Status:** ✅ Stable - Fully implemented with 53 node types

## Overview

Flow is a no-code visual workflow builder that enables traders to create automated trading strategies using drag-and-drop nodes. Built with React Flow for the visual canvas and a Python-based execution engine.

## Problem Statement

Many traders have trading ideas but:
- Cannot write code (Python/Pine Script)
- Find webhook setup complex
- Need conditional logic (if price > X, then buy)
- Want to combine multiple signals

## Solution

A visual canvas where users:
- Drag nodes (triggers, conditions, actions)
- Connect them with edges
- Configure parameters via forms
- Activate to run automatically

## Target Users

| User | Use Case |
|------|----------|
| Non-coder Trader | Automate simple strategies |
| Signal Follower | Route TradingView alerts with conditions |
| Multi-strategy Trader | Manage multiple workflows visually |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        React Frontend                                │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    @xyflow/react Canvas                          ││
│  │  [Start] ──▶ [Price Check] ──▶ [Place Order] ──▶ [Telegram]     ││
│  └─────────────────────────────────────────────────────────────────┘│
│        │                    │                    │                   │
│  ┌─────▼─────┐      ┌──────▼──────┐      ┌─────▼─────┐             │
│  │Node Palette│      │Config Panel │      │ Log Panel │             │
│  └───────────┘      └─────────────┘      └───────────┘             │
└─────────────────────────────────────────────────────────────────────┘
                              │ REST API
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Flask Backend                                 │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                   Execution Engine                               ││
│  │  WorkflowContext │ NodeExecutor │ FlowOpenAlgoClient            ││
│  └─────────────────────────────────────────────────────────────────┘│
│        │                    │                    │                   │
│  ┌─────▼─────┐      ┌──────▼──────┐      ┌─────▼─────┐             │
│  │APScheduler│      │Price Monitor│      │  Webhook  │             │
│  │  (IST)    │      │             │      │  Handler  │             │
│  └───────────┘      └─────────────┘      └───────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

## Node Categories (53 nodes verified)

| Category | Count | Examples |
|----------|-------|----------|
| Triggers | 5 | Start, Webhook, PriceAlert, HttpRequest, WaitUntil |
| Actions | 12 | PlaceOrder, SmartOrder, OptionsOrder, BasketOrder, SplitOrder, ModifyOrder, CancelOrder |
| Conditions | 9 | PriceCondition, TimeWindow, TimeCondition, PositionCheck, FundCheck, AndGate, OrGate, NotGate |
| Data | 17 | GetQuote, MultiQuotes, GetDepth, PositionBook, OrderBook, TradeBook, Holdings, Funds, Margin, OptionChain, OptionSymbol, History |
| Streaming | 4 | SubscribeLTP, SubscribeQuote, SubscribeDepth, Unsubscribe |
| Utility | 6 | Variable, Delay, Log, TelegramAlert, MathExpression, Symbol |

## Functional Requirements

### FR1: Workflow Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Create/edit/delete workflows | P0 |
| FR1.2 | Activate/deactivate workflows | P0 |
| FR1.3 | Duplicate workflow | P2 |
| FR1.4 | Import/export as JSON | P1 |

### FR2: Trigger Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Scheduled trigger (daily, weekly, interval) | P0 |
| FR2.2 | Webhook trigger (external HTTP) | P0 |
| FR2.3 | Price alert trigger (LTP crosses X) | P1 |
| FR2.4 | Manual trigger (button click) | P0 |

### FR3: Condition Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Price condition (>, <, ==) | P0 |
| FR3.2 | Time window (9:15-15:30) | P0 |
| FR3.3 | Position check (has open position?) | P1 |
| FR3.4 | Fund check (available margin > X) | P1 |
| FR3.5 | Logic gates (AND, OR, NOT) | P1 |

### FR4: Action Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Place order | P0 |
| FR4.2 | Smart order (position-aware) | P0 |
| FR4.3 | Options order (single leg) | P1 |
| FR4.4 | Options multi-order (strategies) | P1 |
| FR4.5 | Basket order | P2 |
| FR4.6 | Cancel/modify orders | P1 |
| FR4.7 | Close positions | P1 |

### FR5: Data Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Get quote (LTP, OHLC) | P0 |
| FR5.2 | Get market depth | P1 |
| FR5.3 | Get positions/holdings | P1 |
| FR5.4 | Get option chain | P1 |
| FR5.5 | Get historical data | P1 |

### FR6: Utility Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | Variable (set/get/math operations) | P0 |
| FR6.2 | Delay (wait N seconds) | P1 |
| FR6.3 | HTTP request (external API) | P1 |
| FR6.4 | Telegram alert | P1 |
| FR6.5 | Log message | P0 |
| FR6.6 | Math expression | P1 |

### FR7: Webhook System
| ID | Requirement | Priority |
|----|-------------|----------|
| FR7.1 | Unique webhook URL per workflow | P0 |
| FR7.2 | Secret-based authentication | P0 |
| FR7.3 | Symbol injection from payload | P1 |
| FR7.4 | Regenerate token/secret | P1 |

### FR8: Scheduling
| ID | Requirement | Priority |
|----|-------------|----------|
| FR8.1 | Daily at specific time (IST) | P0 |
| FR8.2 | Weekly on specific days | P1 |
| FR8.3 | Interval (every N minutes) | P1 |
| FR8.4 | One-time at datetime | P2 |
| FR8.5 | Persist jobs across restarts | P0 |

### FR9: Execution
| ID | Requirement | Priority |
|----|-------------|----------|
| FR9.1 | Execute nodes sequentially | P0 |
| FR9.2 | Conditional branching (yes/no paths) | P0 |
| FR9.3 | Variable interpolation ({{var}}) | P0 |
| FR9.4 | Execution logging | P0 |
| FR9.5 | Prevent concurrent execution | P0 |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Node execution time | < 100ms per node |
| Max nodes per workflow | 100 |
| Max concurrent workflows | 50 |
| Webhook response time | < 1 second |

## Database Schema

```sql
flow_workflows (
  id INTEGER PRIMARY KEY,
  name VARCHAR,
  description TEXT,
  nodes JSON,           -- ReactFlow node array
  edges JSON,           -- ReactFlow edge array
  is_active BOOLEAN,
  webhook_token VARCHAR UNIQUE,
  webhook_secret VARCHAR,
  webhook_enabled BOOLEAN,
  webhook_auth_type VARCHAR,  -- "payload" or "url"
  schedule_job_id VARCHAR,
  api_key VARCHAR,
  created_at DATETIME,
  updated_at DATETIME
)

flow_workflow_executions (
  id INTEGER PRIMARY KEY,
  workflow_id INTEGER FK,
  status VARCHAR,       -- pending, running, completed, failed
  started_at DATETIME,
  completed_at DATETIME,
  logs JSON,            -- [{time, message, level}]
  error TEXT
)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/flow/api/workflows` | GET | List all workflows |
| `/flow/api/workflows` | POST | Create workflow |
| `/flow/api/workflows/<id>` | GET | Get workflow |
| `/flow/api/workflows/<id>` | PUT | Update workflow |
| `/flow/api/workflows/<id>` | DELETE | Delete workflow |
| `/flow/api/workflows/<id>/execute` | POST | Manual execution |
| `/flow/api/workflows/<id>/activate` | POST | Activate (schedule) |
| `/flow/api/workflows/<id>/deactivate` | POST | Deactivate |
| `/flow/api/workflows/<id>/executions` | GET | Execution history |
| `/flow/api/workflows/<id>/webhook` | GET | Webhook info |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Node Reference](./flow-node-reference.md) | Complete list of 50+ nodes |
| [Node Creation Guide](./flow-node-creation.md) | How to create new nodes |
| [UI Components](./flow-ui-components.md) | React components guide |
| [Execution Engine](./flow-execution.md) | Backend execution details |

## Key Files Reference

| File | Purpose | Lines |
|------|---------|-------|
| `blueprints/flow.py` | Web routes and workflow API | - |
| `services/flow_executor_service.py` | Main execution engine | ~1940 |
| `services/flow_openalgo_client.py` | OpenAlgo API wrapper for nodes | - |
| `services/flow_scheduler_service.py` | APScheduler integration | - |
| `services/flow_price_monitor_service.py` | Price alert monitoring | - |
| `database/flow_db.py` | SQLAlchemy models (workflows, executions) | - |
| `frontend/src/pages/flow/FlowEditor.tsx` | React Flow canvas | - |
| `frontend/src/pages/flow/FlowIndex.tsx` | Workflow list page | - |
| `frontend/src/components/flow/nodes/*.tsx` | 53 node implementations | - |
| `frontend/src/components/flow/panels/*.tsx` | ConfigPanel, NodePalette, ExecutionLog | - |

## Success Metrics

| Metric | Target |
|--------|--------|
| Workflows created | 100+ |
| Execution success rate | > 99% |
| Avg nodes per workflow | 5-10 |
