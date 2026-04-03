# Event Bus PRD

## Problem

Order side-effects (logging, SocketIO notifications, Telegram alerts) were hardcoded across 10+ service files with 50+ dispatch points. This caused:

- **Inconsistent behavior**: 3 different ownership patterns for side-effects (sandbox fires, caller fires, nobody fires)
- **Silent bugs**: `closeposition` in analyze mode fired zero side-effects (dead `if False:` block); `modify`/`cancel` in analyze mode had no Telegram alerts
- **Duplicate alerts**: Basket/split orders fired N per-order alerts + 1 summary
- **Tight coupling**: Adding a new consumer required editing 4-5 service files
- **Security gap**: API key leaked into log database on validation failure paths
- **Code duplication**: Identical `emit_analyzer_error()` helper copied into 8 files

## Solution

In-process Event Bus — a lightweight pub/sub system using Python stdlib (`threading.Lock` + `ThreadPoolExecutor`).

### Core Concept

Services publish typed events. Subscribers handle side-effects independently.

```
Service: bus.publish(OrderPlacedEvent(...))
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    Log to DB    SocketIO    Telegram
   (subscriber) (subscriber) (subscriber)
```

## Requirements

### Functional

| Requirement | Status |
|-------------|--------|
| All 10 order services publish events via bus | Complete |
| Log subscriber handles both live and analyze mode | Complete |
| SocketIO subscriber emits correct event names per type | Complete |
| Telegram subscriber sends alerts for all order types | Complete |
| Batch operations fire ONE summary event, not N+1 | Complete |
| Analyze mode events set `mode="analyze"` | Complete |
| API keys stripped from event `request_data` before publish | Complete |
| Subscriber failures isolated (one crash doesn't affect others) | Complete |
| New subscribers can be added without modifying services | Complete |

### Non-Functional

| Requirement | Status |
|-------------|--------|
| Zero new dependencies (stdlib only) | Complete |
| Zero infrastructure (no Redis, no ZeroMQ) | Complete |
| Non-blocking publish (ThreadPoolExecutor) | Complete |
| Thread-safe subscribe/unsubscribe | Complete |
| < 1ms publish overhead | Complete |

## Scope

### In Scope

- All order execution services (place, smart, basket, split, options, multi-order, modify, cancel, cancel-all, close-position)
- Sandbox service side-effect removal
- REST API validation error logging migration
- Blueprint `close_position` logging gap fix
- Telegram alert templates for `optionsorder` and `optionsmultiorder`

### Out of Scope (Future)

- Strategy-level position tracking (Phase 2 — new subscriber)
- Strategy-level risk management (Phase 2 — new subscriber)
- Event persistence/replay (SQLite event log table)
- Query services (`orderstatus`, `openposition`, `margin`)

## Bugs Fixed

| Bug | Impact |
|-----|--------|
| `closeposition` analyze mode: dead `if False:` block, zero side-effects | Position closes silently in analyzer |
| `modify`/`cancel` analyze mode: missing Telegram alerts | No notification for sandbox operations |
| `options_order`/`options_multiorder`: `order_event` fired in analyze mode | Wrong SocketIO event in analyzer |
| Basket/split: N+1 `analyzer_update` events and log entries | 21 log entries for 20-order basket |
| `blueprints/orders.py` `close_position`: no API logging | Orders placed but not logged |
| API key in `request_data` on validation failure | Raw key persisted to log DB |
| `emit_event=False` didn't suppress Telegram | Per-sub-order Telegram still fired |

## Architecture

See [Design Doc: 53-event-bus](../design/53-event-bus/README.md) for full technical details.

## Files Changed

### New Files (11)

| File | Lines | Purpose |
|------|-------|---------|
| `utils/event_bus.py` | ~70 | EventBus class |
| `events/__init__.py` | ~40 | Event type exports |
| `events/base.py` | ~25 | Base event dataclass |
| `events/order_events.py` | ~70 | Order event types |
| `events/batch_events.py` | ~60 | Batch event types |
| `events/position_events.py` | ~30 | Position event types |
| `events/analyzer_events.py` | ~15 | Analyzer error event |
| `subscribers/__init__.py` | ~90 | Subscriber registration |
| `subscribers/log_subscriber.py` | ~40 | DB logging |
| `subscribers/socketio_subscriber.py` | ~200 | SocketIO events |
| `subscribers/telegram_subscriber.py` | ~70 | Telegram alerts |

### Modified Files (19)

- 10 service files: hardcoded side-effects replaced with `bus.publish()`
- 7 restx_api files: validation error logging migrated
- 1 blueprint: `orders.py` close_position logging gap fixed
- 1 startup: `app.py` subscriber registration added
