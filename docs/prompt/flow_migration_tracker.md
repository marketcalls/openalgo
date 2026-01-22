# OpenAlgo Flow Migration Tracker

## Overview

| Property | Value |
|----------|-------|
| **Start Date** | 2026-01-16 |
| **Target Completion** | TBD |
| **Current Status** | Phase 1, 2 & 3 Complete |
| **Source** | `openalgo-flow/` |
| **Target** | `openalgo/` |

---

## Progress Summary

| Phase | Description | Tasks | Done | Status |
|-------|-------------|-------|------|--------|
| 1 | Backend Infrastructure | 22 | 22 | ✅ Complete |
| 2 | Service Mapping | 32 | 32 | ✅ Complete |
| 3 | Frontend Infrastructure | 6 | 6 | ✅ Complete |
| 4 | Pages & Routes | 4 | 4 | ✅ Complete |
| 5 | Panels & Edges | 5 | 0 | ⬜ Not Started |
| 6 | Node Components | 54 | 0 | ⬜ Not Started |
| 7 | Testing | 23 | 0 | ⬜ Not Started |
| | **TOTAL** | **146** | **64** | **44%** |

---

## Phase 1: Backend Infrastructure ✅

### 1.1 Database Models

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Create flow_db.py | `database/flow_db.py` | ✅ |
| 2 | FlowWorkflow model | `database/flow_db.py` | ✅ |
| 3 | FlowWorkflowExecution model | `database/flow_db.py` | ✅ |
| 4 | init_db() function | `database/flow_db.py` | ✅ |
| 5 | CRUD functions | `database/flow_db.py` | ✅ |

### 1.2 Blueprint Routes

| # | Route | Method | File | Status |
|---|-------|--------|------|--------|
| 1 | `/flow/api/workflows` | GET | `blueprints/flow.py` | ✅ |
| 2 | `/flow/api/workflows` | POST | `blueprints/flow.py` | ✅ |
| 3 | `/flow/api/workflows/<id>` | GET | `blueprints/flow.py` | ✅ |
| 4 | `/flow/api/workflows/<id>` | PUT | `blueprints/flow.py` | ✅ |
| 5 | `/flow/api/workflows/<id>` | DELETE | `blueprints/flow.py` | ✅ |
| 6 | `/flow/api/workflows/<id>/activate` | POST | `blueprints/flow.py` | ✅ |
| 7 | `/flow/api/workflows/<id>/deactivate` | POST | `blueprints/flow.py` | ✅ |
| 8 | `/flow/api/workflows/<id>/execute` | POST | `blueprints/flow.py` | ✅ |
| 9 | `/flow/api/workflows/<id>/executions` | GET | `blueprints/flow.py` | ✅ |
| 10 | `/flow/webhook/<token>` | POST | `blueprints/flow.py` | ✅ |
| 11 | Register blueprint in app.py | - | `app.py` | ✅ |

### 1.3 Services

| # | Service | File | Status | Description |
|---|---------|------|--------|-------------|
| 1 | FlowOpenAlgoClient | `services/flow_openalgo_client.py` | ✅ | Direct service wrapper |
| 2 | FlowExecutor | `services/flow_executor_service.py` | ✅ | Workflow executor |
| 3 | FlowScheduler | `services/flow_scheduler_service.py` | ✅ | APScheduler |
| 4 | FlowPriceMonitor | `services/flow_price_monitor_service.py` | ✅ | Price alerts |

### 1.4 Database Migration

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Create migrate_flow.py | `upgrade/migrate_flow.py` | ✅ |
| 2 | Add to migrate_all.py | `upgrade/migrate_all.py` | ✅ |

---

## Phase 2: Service Mapping ✅

**Implementation:** `services/flow_openalgo_client.py`

### Order Services

| # | SDK Method | Internal Service | Status |
|---|------------|------------------|--------|
| 1 | `place_order()` | place_order_service.py | ✅ |
| 2 | `place_smart_order()` | place_smart_order_service.py | ✅ |
| 3 | `options_order()` | place_options_order_service.py | ✅ |
| 4 | `options_multi_order()` | options_multiorder_service.py | ✅ |
| 5 | `basket_order()` | basket_order_service.py | ✅ |
| 6 | `split_order()` | split_order_service.py | ✅ |
| 7 | `modify_order()` | modify_order_service.py | ✅ |
| 8 | `cancel_order()` | cancel_order_service.py | ✅ |
| 9 | `cancel_all_orders()` | cancel_all_order_service.py | ✅ |
| 10 | `close_position()` | close_position_service.py | ✅ |

### Data Services

| # | SDK Method | Internal Service | Status |
|---|------------|------------------|--------|
| 1 | `get_quotes()` | quotes_service.py | ✅ |
| 2 | `get_multi_quotes()` | quotes_service.py | ✅ |
| 3 | `get_depth()` | depth_service.py | ✅ |
| 4 | `get_history()` | history_service.py | ✅ |
| 5 | `get_intervals()` | intervals_service.py | ⏭️ N/A |
| 6 | `get_order_status()` | orderstatus_service.py | ✅ |
| 7 | `get_open_position()` | positionbook_service.py | ✅ |
| 8 | `symbol()` | symbol_service.py | ✅ |
| 9 | `search_symbols()` | search_service.py | ✅ |
| 10 | `get_expiry()` | expiry_service.py | ✅ |

> Note: `get_intervals()` not implemented in openalgo-flow backend executor

### Options & Account Services

| # | SDK Method | Internal Service | Status |
|---|------------|------------------|--------|
| 1 | `optionsymbol()` | option_symbol_service.py | ✅ |
| 2 | `optionchain()` | option_chain_service.py | ✅ |
| 3 | `syntheticfuture()` | synthetic_future_service.py | ✅ |
| 4 | `get_option_greeks()` | option_greeks_service.py | ✅ |
| 5 | `funds()` | funds_service.py | ✅ |
| 6 | `margin()` | margin_service.py | ✅ |
| 7 | `orderbook()` | orderbook_service.py | ✅ |
| 8 | `tradebook()` | tradebook_service.py | ✅ |
| 9 | `positionbook()` | positionbook_service.py | ✅ |
| 10 | `holdings()` | holdings_service.py | ✅ |
| 11 | `holidays()` | market_calendar_service.py | ✅ |
| 12 | `timings()` | market_calendar_service.py | ✅ |
| 13 | `telegram()` | telegram_alert_service.py | ✅ |

---

## Phase 3: Frontend Infrastructure ✅

| # | Task | Target File | Status |
|---|------|-------------|--------|
| 1 | Add @xyflow/react dependency | `frontend/package.json` | ✅ |
| 2 | Add Flow CSS variables | `frontend/src/index.css` | ✅ |
| 3 | Create flow directory structure | `frontend/src/lib/flow/` | ✅ |
| 4 | Create flow.ts API module | `frontend/src/api/flow.ts` | ✅ |
| 5 | Create flowWorkflowStore.ts | `frontend/src/stores/flowWorkflowStore.ts` | ✅ |
| 6 | Create constants.ts | `frontend/src/lib/flow/constants.ts` | ✅ |

---

## Phase 4: Pages & Routes ✅

### Pages

| # | Page | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | FlowIndex | `pages/Dashboard.tsx` | `pages/flow/FlowIndex.tsx` | ✅ |
| 2 | FlowEditor | `pages/Editor.tsx` | `pages/flow/FlowEditor.tsx` | ✅ |

### Routes

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Add Flow routes to App.tsx | `frontend/src/App.tsx` | ✅ |
| 2 | Add Flow routes to react_app.py | `blueprints/react_app.py` | ✅ |

---

## Phase 5: Panels & Edges ⬜

### Panels

| # | Component | Source | Target | Status |
|---|-----------|--------|--------|--------|
| 1 | NodePalette | `panels/NodePalette.tsx` | `flow/panels/NodePalette.tsx` | ⬜ |
| 2 | ConfigPanel | `panels/ConfigPanel.tsx` | `flow/panels/ConfigPanel.tsx` | ⬜ |
| 3 | ExecutionLogPanel | `panels/ExecutionLogPanel.tsx` | `flow/panels/ExecutionLogPanel.tsx` | ⬜ |

### Edges

| # | Component | Source | Target | Status |
|---|-----------|--------|--------|--------|
| 1 | InsertableEdge | `edges/InsertableEdge.tsx` | `flow/edges/InsertableEdge.tsx` | ⬜ |
| 2 | Edge index.ts | `edges/index.ts` | `flow/edges/index.ts` | ⬜ |

---

## Phase 6: Node Components ⬜

### Trigger Nodes (4)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | StartNode | `nodes/StartNode.tsx` | `flow/nodes/StartNode.tsx` | ⬜ |
| 2 | PriceAlertNode | `nodes/PriceAlertNode.tsx` | `flow/nodes/PriceAlertNode.tsx` | ⬜ |
| 3 | WebhookTriggerNode | `nodes/WebhookTriggerNode.tsx` | `flow/nodes/WebhookTriggerNode.tsx` | ⬜ |
| 4 | HttpRequestNode | `nodes/HttpRequestNode.tsx` | `flow/nodes/HttpRequestNode.tsx` | ⬜ |

### Order Nodes (10)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | PlaceOrderNode | `nodes/PlaceOrderNode.tsx` | `flow/nodes/PlaceOrderNode.tsx` | ⬜ |
| 2 | SmartOrderNode | `nodes/SmartOrderNode.tsx` | `flow/nodes/SmartOrderNode.tsx` | ⬜ |
| 3 | OptionsOrderNode | `nodes/OptionsOrderNode.tsx` | `flow/nodes/OptionsOrderNode.tsx` | ⬜ |
| 4 | OptionsMultiOrderNode | `nodes/OptionsMultiOrderNode.tsx` | `flow/nodes/OptionsMultiOrderNode.tsx` | ⬜ |
| 5 | BasketOrderNode | `nodes/BasketOrderNode.tsx` | `flow/nodes/BasketOrderNode.tsx` | ⬜ |
| 6 | SplitOrderNode | `nodes/SplitOrderNode.tsx` | `flow/nodes/SplitOrderNode.tsx` | ⬜ |
| 7 | ModifyOrderNode | `nodes/ModifyOrderNode.tsx` | `flow/nodes/ModifyOrderNode.tsx` | ⬜ |
| 8 | CancelOrderNode | `nodes/CancelOrderNode.tsx` | `flow/nodes/CancelOrderNode.tsx` | ⬜ |
| 9 | CancelAllOrdersNode | `nodes/CancelAllOrdersNode.tsx` | `flow/nodes/CancelAllOrdersNode.tsx` | ⬜ |
| 10 | ClosePositionsNode | `nodes/ClosePositionsNode.tsx` | `flow/nodes/ClosePositionsNode.tsx` | ⬜ |

### Condition Nodes (5)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | PositionCheckNode | `nodes/PositionCheckNode.tsx` | `flow/nodes/PositionCheckNode.tsx` | ⬜ |
| 2 | FundCheckNode | `nodes/FundCheckNode.tsx` | `flow/nodes/FundCheckNode.tsx` | ⬜ |
| 3 | TimeWindowNode | `nodes/TimeWindowNode.tsx` | `flow/nodes/TimeWindowNode.tsx` | ⬜ |
| 4 | TimeConditionNode | `nodes/TimeConditionNode.tsx` | `flow/nodes/TimeConditionNode.tsx` | ⬜ |
| 5 | PriceConditionNode | `nodes/PriceConditionNode.tsx` | `flow/nodes/PriceConditionNode.tsx` | ⬜ |

### Logic Gate Nodes (3)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | AndGateNode | `nodes/AndGateNode.tsx` | `flow/nodes/AndGateNode.tsx` | ⬜ |
| 2 | OrGateNode | `nodes/OrGateNode.tsx` | `flow/nodes/OrGateNode.tsx` | ⬜ |
| 3 | NotGateNode | `nodes/NotGateNode.tsx` | `flow/nodes/NotGateNode.tsx` | ⬜ |

### Market Data Nodes (8)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | GetQuoteNode | `nodes/GetQuoteNode.tsx` | `flow/nodes/GetQuoteNode.tsx` | ⬜ |
| 2 | GetDepthNode | `nodes/GetDepthNode.tsx` | `flow/nodes/GetDepthNode.tsx` | ⬜ |
| 3 | HistoryNode | `nodes/HistoryNode.tsx` | `flow/nodes/HistoryNode.tsx` | ⬜ |
| 4 | MultiQuotesNode | `nodes/MultiQuotesNode.tsx` | `flow/nodes/MultiQuotesNode.tsx` | ⬜ |
| 5 | SymbolNode | `nodes/SymbolNode.tsx` | `flow/nodes/SymbolNode.tsx` | ⬜ |
| 6 | ExpiryNode | `nodes/ExpiryNode.tsx` | `flow/nodes/ExpiryNode.tsx` | ⬜ |
| 7 | IntervalsNode | `nodes/IntervalsNode.tsx` | `flow/nodes/IntervalsNode.tsx` | ⬜ |
| 8 | SearchNode | `nodes/SearchNode.tsx` | `flow/nodes/SearchNode.tsx` | ⬜ |

### Options Nodes (4)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | OptionSymbolNode | `nodes/OptionSymbolNode.tsx` | `flow/nodes/OptionSymbolNode.tsx` | ⬜ |
| 2 | OptionChainNode | `nodes/OptionChainNode.tsx` | `flow/nodes/OptionChainNode.tsx` | ⬜ |
| 3 | SyntheticFutureNode | `nodes/SyntheticFutureNode.tsx` | `flow/nodes/SyntheticFutureNode.tsx` | ⬜ |
| 4 | OptionGreeksNode | `nodes/OptionGreeksNode.tsx` | `flow/nodes/OptionGreeksNode.tsx` | ⬜ |

### Order/Position Info Nodes (5)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | GetOrderStatusNode | `nodes/GetOrderStatusNode.tsx` | `flow/nodes/GetOrderStatusNode.tsx` | ⬜ |
| 2 | OpenPositionNode | `nodes/OpenPositionNode.tsx` | `flow/nodes/OpenPositionNode.tsx` | ⬜ |
| 3 | OrderBookNode | `nodes/OrderBookNode.tsx` | `flow/nodes/OrderBookNode.tsx` | ⬜ |
| 4 | TradeBookNode | `nodes/TradeBookNode.tsx` | `flow/nodes/TradeBookNode.tsx` | ⬜ |
| 5 | PositionBookNode | `nodes/PositionBookNode.tsx` | `flow/nodes/PositionBookNode.tsx` | ⬜ |

### WebSocket Streaming Nodes (4)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | SubscribeLTPNode | `nodes/SubscribeLTPNode.tsx` | `flow/nodes/SubscribeLTPNode.tsx` | ⬜ |
| 2 | SubscribeQuoteNode | `nodes/SubscribeQuoteNode.tsx` | `flow/nodes/SubscribeQuoteNode.tsx` | ⬜ |
| 3 | SubscribeDepthNode | `nodes/SubscribeDepthNode.tsx` | `flow/nodes/SubscribeDepthNode.tsx` | ⬜ |
| 4 | UnsubscribeNode | `nodes/UnsubscribeNode.tsx` | `flow/nodes/UnsubscribeNode.tsx` | ⬜ |

### Risk Management Nodes (3)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | HoldingsNode | `nodes/HoldingsNode.tsx` | `flow/nodes/HoldingsNode.tsx` | ⬜ |
| 2 | FundsNode | `nodes/FundsNode.tsx` | `flow/nodes/FundsNode.tsx` | ⬜ |
| 3 | MarginNode | `nodes/MarginNode.tsx` | `flow/nodes/MarginNode.tsx` | ⬜ |

### Calendar Nodes (2)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | HolidaysNode | `nodes/HolidaysNode.tsx` | `flow/nodes/HolidaysNode.tsx` | ⬜ |
| 2 | TimingsNode | `nodes/TimingsNode.tsx` | `flow/nodes/TimingsNode.tsx` | ⬜ |

### Utility Nodes (7)

| # | Node | Source | Target | Status |
|---|------|--------|--------|--------|
| 1 | TelegramAlertNode | `nodes/TelegramAlertNode.tsx` | `flow/nodes/TelegramAlertNode.tsx` | ⬜ |
| 2 | DelayNode | `nodes/DelayNode.tsx` | `flow/nodes/DelayNode.tsx` | ⬜ |
| 3 | WaitUntilNode | `nodes/WaitUntilNode.tsx` | `flow/nodes/WaitUntilNode.tsx` | ⬜ |
| 4 | GroupNode | `nodes/GroupNode.tsx` | `flow/nodes/GroupNode.tsx` | ⬜ |
| 5 | VariableNode | `nodes/VariableNode.tsx` | `flow/nodes/VariableNode.tsx` | ⬜ |
| 6 | MathExpressionNode | `nodes/MathExpressionNode.tsx` | `flow/nodes/MathExpressionNode.tsx` | ⬜ |
| 7 | LogNode | `nodes/LogNode.tsx` | `flow/nodes/LogNode.tsx` | ⬜ |

### Base Components (3)

| # | Component | Source | Target | Status |
|---|-----------|--------|--------|--------|
| 1 | BaseNode | `nodes/BaseNode.tsx` | `flow/nodes/BaseNode.tsx` | ⬜ |
| 2 | Node index.ts | `nodes/index.ts` | `flow/nodes/index.ts` | ⬜ |
| 3 | nodeTypes config | - | `flow/nodes/nodeTypes.ts` | ⬜ |

**Total Nodes: 54**

---

## Phase 7: Testing ⬜

### Backend Tests
| # | Test | Status |
|---|------|--------|
| 1 | Create workflow via API | ⬜ |
| 2 | List workflows | ⬜ |
| 3 | Get single workflow | ⬜ |
| 4 | Update workflow | ⬜ |
| 5 | Delete workflow | ⬜ |
| 6 | Activate workflow | ⬜ |
| 7 | Deactivate workflow | ⬜ |
| 8 | Execute workflow manually | ⬜ |
| 9 | Webhook trigger | ⬜ |
| 10 | Scheduled trigger | ⬜ |
| 11 | Price alert trigger | ⬜ |

### Frontend Tests

| # | Test | Status |
|---|------|--------|
| 1 | Navigate to /flow | ⬜ |
| 2 | View workflow list | ⬜ |
| 3 | Create new workflow | ⬜ |
| 4 | Open workflow editor | ⬜ |
| 5 | Drag and drop nodes | ⬜ |
| 6 | Connect nodes | ⬜ |
| 7 | Configure node properties | ⬜ |
| 8 | Save workflow | ⬜ |
| 9 | Activate workflow | ⬜ |
| 10 | View execution logs | ⬜ |

### Integration Tests

| # | Test | Status |
|---|------|--------|
| 1 | End-to-end workflow creation | ⬜ |
| 2 | Order placement (analyze mode) | ⬜ |

---

## Change Log

| Date | Phase | Changes |
|------|-------|---------|
| 2026-01-16 | 1 | Created all backend files: flow_db.py, flow.py blueprint, 4 services |
| 2026-01-16 | 1 | Created migrate_flow.py and added to migrate_all.py |
| 2026-01-16 | 1 | Registered blueprint in app.py with CSRF exemption |
| 2026-01-16 | 2 | Implemented initial service mappings in flow_openalgo_client.py |
| 2026-01-16 | 2 | Added remaining 7 methods: get_multi_quotes, get_order_status, symbol, search_symbols, get_expiry, syntheticfuture, get_option_greeks |
| 2026-01-19 | 2 | Fixed timing-vulnerable webhook secret comparison (hmac.compare_digest) |
| 2026-01-19 | 3 | Added @xyflow/react dependency to package.json |
| 2026-01-19 | 3 | Added Flow CSS variables and ReactFlow styles to index.css |
| 2026-01-19 | 3 | Created flow.ts API module with all workflow endpoints |
| 2026-01-19 | 3 | Created flowWorkflowStore.ts Zustand store |
| 2026-01-19 | 3 | Created lib/flow/constants.ts with all trading and node constants |
| 2026-01-19 | 4 | Created FlowIndex.tsx (workflow list page) |
| 2026-01-19 | 4 | Created FlowEditor.tsx (visual editor with ReactFlow canvas) |
| 2026-01-19 | 4 | Added Flow routes to App.tsx (/flow, /flow/editor/:id) |
| 2026-01-19 | 4 | Added Flow routes to react_app.py |

---

## Files Created

| Phase | File | Description |
|-------|------|-------------|
| 1 | `database/flow_db.py` | Database models and CRUD |
| 1 | `blueprints/flow.py` | Flask blueprint with routes |
| 1 | `services/flow_openalgo_client.py` | Direct service wrapper |
| 1 | `services/flow_executor_service.py` | Workflow executor |
| 1 | `services/flow_scheduler_service.py` | APScheduler integration |
| 1 | `services/flow_price_monitor_service.py` | Price alert monitoring |
| 1 | `upgrade/migrate_flow.py` | Database migration |
| 3 | `frontend/src/api/flow.ts` | Flow API module |
| 3 | `frontend/src/stores/flowWorkflowStore.ts` | Zustand store for workflow editor |
| 3 | `frontend/src/lib/flow/constants.ts` | Trading and node constants |
| 4 | `frontend/src/pages/flow/FlowIndex.tsx` | Workflow list page |
| 4 | `frontend/src/pages/flow/FlowEditor.tsx` | Visual workflow editor |

## Files Modified

| Phase | File | Changes |
|-------|------|---------|
| 1 | `app.py` | Blueprint registration, CSRF exemption, DB init, scheduler init |
| 1 | `upgrade/migrate_all.py` | Added migrate_flow.py to MIGRATIONS |
| 3 | `frontend/package.json` | Added @xyflow/react dependency |
| 3 | `frontend/src/index.css` | Added Flow CSS variables and ReactFlow styles |

---

## Notes

- **Do NOT port:** Settings page, Profile page, separate Auth system
- **Use:** OpenAlgo's existing auth, API key from /playground, DATABASE_URL from .env
- Source nodes path: `openalgo-flow/frontend/src/components/nodes/`
- Target nodes path: `openalgo/frontend/src/components/flow/nodes/`
