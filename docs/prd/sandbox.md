# PRD: Sandbox - Paper Trading Environment

> **Status:** ✅ Stable - Fully implemented, production-ready

## Overview

Sandbox (Analyzer Mode) is an isolated paper trading environment with simulated capital for testing strategies without risking real money.

## Problem Statement

Traders need to:
- Test new strategies before live deployment
- Validate webhook/API integrations safely
- Learn the platform without financial risk
- Debug issues without affecting real account

## Solution

A complete paper trading environment that:
- Uses real-time market prices from broker
- Simulates order execution with realistic fills
- Maintains separate position/order books
- Applies exchange-specific margin rules
- Auto square-off at market close

## Target Users

| User | Use Case |
|------|----------|
| New User | Learn OpenAlgo safely |
| Strategy Developer | Test before live |
| Educator | Demonstrate without risk |
| Debugger | Isolate integration issues |

## Functional Requirements

### FR1: Capital Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Start with configurable capital (default ₹1 Cr) | P0 |
| FR1.2 | Track available/used margin | P0 |
| FR1.3 | Block margin on order placement | P0 |
| FR1.4 | Release margin on position close | P0 |
| FR1.5 | Daily margin reconciliation | P1 |

### FR2: Order Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Place market orders (instant fill at LTP) | P0 |
| FR2.2 | Place limit orders (fill when price reached) | P0 |
| FR2.3 | Place SL/SL-M orders | P1 |
| FR2.4 | Modify pending orders | P1 |
| FR2.5 | Cancel orders | P0 |
| FR2.6 | Order validation (qty, symbol, margin) | P0 |

### FR3: Position Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Track open positions | P0 |
| FR3.2 | Calculate MTM P&L in real-time | P0 |
| FR3.3 | Position netting (same direction, opposite) | P0 |
| FR3.4 | Support MIS/CNC/NRML products | P0 |

### FR4: Holdings (CNC)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | T+1 settlement for delivery trades | P1 |
| FR4.2 | Track buy avg, quantity, P&L | P0 |
| FR4.3 | Sell from holdings | P0 |

### FR5: Auto Square-Off
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | Square-off MIS at exchange timings | P0 |
| FR5.2 | Exchange-specific timings (NSE 15:15, MCX 23:30) | P0 |
| FR5.3 | Mark expired F&O contracts | P1 |

### FR6: Execution Engine
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | Poll pending orders every 2 seconds | P0 |
| FR6.2 | Match limit orders against LTP | P0 |
| FR6.3 | Trigger SL orders when price breached | P1 |
| FR6.4 | WebSocket price updates (optional) | P2 |

### FR7: Reporting
| ID | Requirement | Priority |
|----|-------------|----------|
| FR7.1 | Order book with all orders | P0 |
| FR7.2 | Trade book with executions | P0 |
| FR7.3 | Position book with MTM | P0 |
| FR7.4 | P&L summary | P0 |
| FR7.5 | Export to CSV | P2 |

### FR8: Session Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR8.1 | Session boundary at 03:00 IST | P0 |
| FR8.2 | Carry forward NRML/CNC positions | P0 |
| FR8.3 | Reset day's trades at session start | P0 |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Order execution latency | < 500ms |
| Price staleness | < 5 seconds |
| Concurrent orders | 1000+ |
| Database isolation | 100% separate from live |

## Margin Calculation

```
┌──────────────────────────────────────────────────────────┐
│                    Margin Rules                           │
├──────────────────────────────────────────────────────────┤
│ Product │ Leverage │ Margin Required                     │
├─────────┼──────────┼─────────────────────────────────────┤
│ CNC     │ 1x       │ Full value (qty × price)           │
│ MIS     │ 5x       │ 20% of value                       │
│ NRML    │ 1x       │ Full value (F&O overnight)         │
└──────────┴──────────┴─────────────────────────────────────┘
```

## Position Netting Logic

```
Current: +100 shares (LONG)
New Order: SELL 150

Result:
  1. Close existing: SELL 100 (close long)
  2. Open new: SELL 50 (new short position)
  Net: -50 shares (SHORT)
```

## Database Schema

```
sandbox.db (separate from main)
├── sandbox_orders      - All orders
├── sandbox_trades      - Executed trades
├── sandbox_positions   - Open positions
├── sandbox_holdings    - CNC holdings
├── sandbox_funds       - Capital tracking
├── sandbox_margins     - Margin blocks
└── sandbox_logs        - Audit trail
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      API Request                             │
│                 (Analyzer Mode = ON)                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Order Manager                             │
│  Validate → Check Margin → Create Order → Queue for Exec    │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Execution Engine                            │
│  Poll Orders → Fetch LTP → Match Price → Execute Trade      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Position Manager                            │
│  Net Position → Update MTM → Block/Release Margin           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Square-Off Manager                          │
│  Check Time → Close MIS → Mark Expired → Settle Holdings    │
└─────────────────────────────────────────────────────────────┘
```

## UI Wireframe

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠️ SANDBOX MODE ACTIVE                                      │
│  Capital: ₹1,00,00,000  │  Used: ₹5,00,000  │  P&L: +₹2,500 │
├─────────────────────────────────────────────────────────────┤
│  Open Positions (3)                                          │
│  ┌─────────┬─────┬───────┬─────────┬──────────┬──────────┐ │
│  │ Symbol  │ Qty │ Avg   │ LTP     │ P&L      │ Actions  │ │
│  ├─────────┼─────┼───────┼─────────┼──────────┼──────────┤ │
│  │ SBIN    │ +100│ 620.00│ 625.50  │ +₹550    │ [Close]  │ │
│  │ RELIANCE│ -50 │ 2450  │ 2445.00 │ +₹250    │ [Close]  │ │
│  └─────────┴─────┴───────┴─────────┴──────────┴──────────┘ │
│                                                              │
│  Today's Orders (5)                                          │
│  ┌─────────┬────────┬─────┬────────┬──────────┐            │
│  │ Symbol  │ Action │ Qty │ Status │ Time     │            │
│  ├─────────┼────────┼─────┼────────┼──────────┤            │
│  │ SBIN    │ BUY    │ 100 │ ✓ Done │ 09:15:32 │            │
│  │ INFY    │ BUY    │ 50  │ Pending│ 09:20:15 │            │
│  └─────────┴────────┴─────┴────────┴──────────┘            │
└─────────────────────────────────────────────────────────────┘
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Sandbox Architecture](./sandbox-architecture.md) | Detailed system architecture |
| [Execution Engine](./sandbox-execution-engine.md) | Order matching engine details |
| [Margin System](./sandbox-margin-system.md) | Margin calculation and fund management |

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/sandbox_db.py` | SQLAlchemy models for sandbox tables |
| `blueprints/analyzer.py` | Web routes and API endpoints |
| `services/sandbox_service.py` | Business logic and execution engine |
| `frontend/src/pages/Analyzer.tsx` | React UI component |

## Success Metrics

| Metric | Target |
|--------|--------|
| Price accuracy | Real-time from broker |
| Order fill simulation | Realistic (limit at LTP match) |
| Margin calculation | Match exchange rules |
| Isolation | 0 impact on live account |
