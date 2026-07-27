# 53 - Event Bus

## Overview

The Event Bus is a lightweight, in-process pub/sub system that decouples order side-effects (logging, SocketIO notifications, Telegram alerts) from the order execution pipeline. Services publish typed events; subscribers handle side-effects independently.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Event Bus Architecture                                │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  Publishers (Order Services)                                                 │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ place_order      │  │ basket_order    │  │ modify_order    │             │
│  │ place_smart_order│  │ split_order     │  │ cancel_order    │             │
│  │ options_order    │  │ multiorder      │  │ close_position  │             │
│  └────────┬─────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                     │                     │                      │
│           └─────────────────────┼─────────────────────┘                      │
│                                 │                                            │
│                    bus.publish(TypedEvent)                                   │
│                                 │                                            │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Event Bus (utils/event_bus.py)                                              │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  - Topic-based routing (e.g., "order.placed", "basket.completed")   │   │
│  │  - Thread-safe subscribe/unsubscribe/publish                        │   │
│  │  - ThreadPoolExecutor (10 workers) for async dispatch               │   │
│  │  - Error isolation: one subscriber failure doesn't affect others    │   │
│  │  - Global singleton instance                                        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Subscribers (subscribers/)                                                  │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ Log Subscriber   │  │ SocketIO        │  │ Telegram        │             │
│  │                  │  │ Subscriber      │  │ Subscriber      │             │
│  │ Live mode:       │  │                 │  │                 │             │
│  │  → order_logs    │  │ Live mode:      │  │ Calls           │             │
│  │    (openalgo.db) │  │  → order_event  │  │ send_order_alert│             │
│  │                  │  │  → cancel_event │  │ for all event   │             │
│  │ Analyze mode:    │  │  → modify_event │  │ types with      │             │
│  │  → analyzer_logs │  │                 │  │ mode awareness  │             │
│  │    (openalgo.db) │  │ Analyze mode:   │  │                 │             │
│  │                  │  │  → analyzer_    │  │ Future:         │             │
│  │ Future:          │  │    update       │  │ strategy_store  │             │
│  │ strategy_tracker │  │                 │  │ risk_manager    │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Event Types

### Base Event

All events inherit from `OrderEvent` which carries common fields:

| Field | Type | Description |
|-------|------|-------------|
| `topic` | str | Event routing key (e.g., `"order.placed"`) |
| `mode` | str | `"live"` or `"analyze"` — subscribers branch on this |
| `api_type` | str | Operation name (`"placeorder"`, `"cancelorder"`, etc.) |
| `request_data` | dict | Cleaned request data (apikey stripped) for logging |
| `response_data` | dict | Response data for logging |
| `api_key` | str | For Telegram username resolution (never persisted to logs) |

### Event Catalog

| Event | Topic | When Fired |
|-------|-------|------------|
| `OrderPlacedEvent` | `order.placed` | Single order successfully placed (live or analyze) |
| `OrderFailedEvent` | `order.failed` | Order fails (validation, broker rejection, module not found) |
| `SmartOrderNoActionEvent` | `order.no_action` | Smart order determines no action needed |
| `OrderModifiedEvent` | `order.modified` | Order successfully modified |
| `OrderModifyFailedEvent` | `order.modify_failed` | Order modification fails |
| `OrderCancelledEvent` | `order.cancelled` | Single order successfully cancelled |
| `OrderCancelFailedEvent` | `order.cancel_failed` | Order cancellation fails |
| `AllOrdersCancelledEvent` | `orders.all_cancelled` | Cancel-all-orders completes |
| `PositionClosedEvent` | `position.closed` | Position(s) closed |
| `BasketCompletedEvent` | `basket.completed` | All basket orders complete (one summary) |
| `SplitCompletedEvent` | `split.completed` | All split sub-orders complete (one summary) |
| `OptionsOrderCompletedEvent` | `options.completed` | Options split order completes |
| `MultiOrderCompletedEvent` | `multiorder.completed` | Multi-leg options order completes |
| `AnalyzerErrorEvent` | `analyzer.error` | Validation/unexpected errors |

### Batch Event Pattern

Batch operations (basket, split, options multi-order) publish ONE summary event after all sub-orders complete. Individual sub-orders do NOT publish events — this prevents N+1 notifications.

```
Basket with 20 orders:
  place_order(emit_event=False) × 20   → no events
  BasketCompletedEvent × 1              → log + socketio + telegram fire ONCE
```

## File Structure

```
utils/
  event_bus.py              ← EventBus class (~70 lines)

events/
  __init__.py               ← Re-exports all event types
  base.py                   ← OrderEvent base dataclass
  order_events.py           ← OrderPlaced, OrderFailed, SmartOrderNoAction, Modified, Cancelled
  batch_events.py           ← Basket, Split, Options, MultiOrder completed
  position_events.py        ← PositionClosed, AllOrdersCancelled
  analyzer_events.py        ← AnalyzerError

subscribers/
  __init__.py               ← register_all() wires all subscribers at startup
  log_subscriber.py         ← Logging (live → order_logs, analyze → analyzer_logs)
  socketio_subscriber.py    ← SocketIO events (8 distinct event names)
  telegram_subscriber.py    ← Telegram alerts via telegram_alert_service
```

## How It Works

### Publishing (Service Layer)

```python
from events import OrderPlacedEvent
from utils.event_bus import bus

# After successful broker call:
bus.publish(OrderPlacedEvent(
    mode="live",
    api_type="placeorder",
    strategy=order_data.get("strategy", ""),
    symbol=order_data.get("symbol", ""),
    orderid=str(order_id),
    request_data=cleaned_request,
    response_data={"status": "success", "orderid": order_id},
    api_key=api_key,
))
```

### Subscribing (Startup)

```python
# subscribers/__init__.py — called once from app.py
from utils.event_bus import bus

def register_all():
    bus.subscribe("order.placed", log_subscriber.on_order_placed)
    bus.subscribe("order.placed", socketio_subscriber.on_order_placed)
    bus.subscribe("order.placed", telegram_subscriber.on_order_placed)
    # ... 14 topics × 3 subscribers = 42+ registrations
```

### Mode-Aware Subscribers

```python
# subscribers/log_subscriber.py
def _log_event(event):
    if event.mode == "analyze":
        async_log_analyzer(event.request_data, event.response_data, event.api_type)
    else:
        async_log_order(event.api_type, event.request_data, event.response_data)
```

## SocketIO Event Mapping

| Bus Event | Live SocketIO Event | Analyze SocketIO Event |
|-----------|--------------------|-----------------------|
| `order.placed` | `order_event` | `analyzer_update` |
| `order.no_action` | `order_notification` | `analyzer_update` |
| `order.modified` | `modify_order_event` | `analyzer_update` |
| `order.cancelled` | `cancel_order_event` | `analyzer_update` |
| `orders.all_cancelled` | `cancel_order_event` (batch) | `analyzer_update` |
| `position.closed` | `close_position_event` | `analyzer_update` |
| `basket.completed` | `order_event` (batch) | `analyzer_update` |
| `split.completed` | `order_event` (batch) | `analyzer_update` |
| `options.completed` | `order_event` (batch) | `analyzer_update` |
| `multiorder.completed` | `order_event` (batch) | `analyzer_update` |
| `analyzer.error` | — | `analyzer_update` |

## Design Decisions

### Why In-Process (Not Redis/ZeroMQ)?

OpenAlgo is a single-user, single-process application using SQLite. External message brokers add infrastructure complexity for zero benefit at this scale. The EventBus is ~70 lines of Python using stdlib `threading` and `concurrent.futures`.

### Why ThreadPoolExecutor?

Subscribers must not block the order response. The thread pool (10 workers) dispatches all callbacks asynchronously. The `_safe_call` wrapper isolates failures — one subscriber crashing doesn't affect others.

### Why Typed Events (Dataclasses)?

Prevents silent bugs from dict key typos. Provides autocomplete in IDEs. The event schema is the contract between publishers and subscribers.

### Why Not Blinker/PyPubSub?

Blinker (Flask's signal library) dispatches callbacks synchronously in the caller's thread. PyPubSub adds a dependency for what's essentially a dict of lists. Neither provides async dispatch or error isolation.

## Adding a New Subscriber

To add a new consumer (e.g., strategy-level position tracking):

```python
# subscribers/strategy_store.py (new file)
def on_order_placed(event):
    # Update strategy position from fill
    ...

def on_basket_completed(event):
    # Update positions for all basket legs
    ...
```

```python
# subscribers/__init__.py — add registration
bus.subscribe("order.placed", strategy_store.on_order_placed)
bus.subscribe("basket.completed", strategy_store.on_basket_completed)
```

Zero changes to any order service. This is the primary architectural benefit.

## Security

- `api_key` is passed in events only for Telegram username resolution — never written to log databases
- `request_data` has `apikey` stripped before event publication
- Event bus is in-process only — no network exposure
- Thread pool provides isolation — subscriber exceptions are caught and logged

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/event_bus.py` | EventBus class (singleton) |
| `events/__init__.py` | All event type exports |
| `events/base.py` | OrderEvent base class |
| `subscribers/__init__.py` | register_all() startup wiring |
| `subscribers/log_subscriber.py` | DB logging (live + analyze) |
| `subscribers/socketio_subscriber.py` | Real-time UI events |
| `subscribers/telegram_subscriber.py` | Telegram alerts |
| `app.py` | Subscriber registration at startup |
