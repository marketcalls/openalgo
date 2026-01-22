# PRD: Flow - Visual Workflow Automation

## Overview

Flow is a no-code visual workflow builder that enables traders to create automated trading strategies using drag-and-drop nodes.

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
| FR4.3 | Cancel order | P1 |
| FR4.4 | Close position | P1 |
| FR4.5 | Basket order | P2 |

### FR5: Data Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Get quote (LTP, OHLC) | P0 |
| FR5.2 | Get market depth | P1 |
| FR5.3 | Get positions/holdings | P1 |
| FR5.4 | Subscribe to real-time data | P1 |

### FR6: Utility Nodes
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | Variable (set/get/math operations) | P0 |
| FR6.2 | Delay (wait N seconds) | P1 |
| FR6.3 | HTTP request (external API) | P1 |
| FR6.4 | Telegram alert | P1 |
| FR6.5 | Log message | P0 |

### FR7: Webhook System
| ID | Requirement | Priority |
|----|-------------|----------|
| FR7.1 | Unique webhook URL per workflow | P0 |
| FR7.2 | Secret-based authentication | P0 |
| FR7.3 | Symbol injection from URL path | P1 |
| FR7.4 | Regenerate token/secret | P1 |

### FR8: Scheduling
| ID | Requirement | Priority |
|----|-------------|----------|
| FR8.1 | Daily at specific time | P0 |
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

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React Flow Canvas                        │
│  [Start] ──▶ [Price Check] ──▶ [Place Order] ──▶ [Telegram] │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Execution Engine                           │
│  WorkflowContext │ NodeExecutor │ FlowOpenAlgoClient        │
└─────────────────────────────────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
      APScheduler   Price Monitor   Webhook Handler
```

## Node Categories (60+ nodes)

| Category | Count | Examples |
|----------|-------|----------|
| Triggers | 3 | Start, Webhook, PriceAlert |
| Orders | 8 | PlaceOrder, SmartOrder, CancelOrder |
| Data | 10 | GetQuote, GetDepth, PositionBook |
| Conditions | 8 | PriceCondition, TimeWindow, AndGate |
| Streaming | 4 | SubscribeLTP, SubscribeQuote |
| Utility | 6 | Variable, Delay, HttpRequest |

## Database Schema

```sql
flow_workflows (
  id, name, nodes JSON, edges JSON,
  is_active, webhook_token, webhook_secret,
  schedule_job_id, api_key
)

flow_workflow_executions (
  id, workflow_id, status, logs JSON,
  started_at, completed_at, error
)
```

## UI Wireframe

```
┌─────────────────────────────────────────────────────────────────────┐
│  Flow Editor - "Morning Breakout Strategy"         [Save] [Activate]│
├───────────────┬─────────────────────────────────────┬───────────────┤
│  Node Palette │           Canvas                    │  Config Panel │
│               │                                     │               │
│  ▸ Triggers   │   ┌───────┐      ┌───────────┐    │  Start Node   │
│    • Start    │   │ Start │─────▶│ Price > X │    │               │
│    • Webhook  │   └───────┘      └─────┬─────┘    │  Schedule:    │
│               │                    yes │ no       │  [Daily ▼]    │
│  ▸ Conditions │                        ▼          │  Time: [09:20]│
│    • Price    │                  ┌──────────┐     │               │
│    • Time     │                  │ Buy SBIN │     │               │
│               │                  └────┬─────┘     │               │
│  ▸ Actions    │                       ▼          │               │
│    • Order    │                  ┌──────────┐     │               │
│    • Close    │                  │ Telegram │     │               │
│               │                  └──────────┘     │               │
└───────────────┴─────────────────────────────────────┴───────────────┘
│  Execution Logs                                                      │
│  [09:20:01] Workflow started                                        │
│  [09:20:02] Price check: SBIN = 625.50 > 620 ✓                     │
│  [09:20:03] Order placed: SBIN BUY 10 @ MARKET                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Success Metrics

| Metric | Target |
|--------|--------|
| Workflows created | 100+ |
| Execution success rate | > 99% |
| Avg nodes per workflow | 5-10 |
