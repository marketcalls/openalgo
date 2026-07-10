# 53 - Event Bus

## Scope

`utils/event_bus.py` is a lightweight, **per-process** topic bus for asynchronous order side effects. It is not the cross-process market-data bus; ZeroMQ owns that job.

Each Flask worker that imports the global singleton has its own subscriber registry and 10-worker `ThreadPoolExecutor`. A service publishes in the process handling the request, and that process dispatches its local subscribers.

## Flow

```text
order/sandbox service
  -> typed event with topic
  -> EventBus.publish()
  -> shared per-process thread pool
     -> log subscriber
     -> Socket.IO subscriber
     -> Telegram subscriber
     -> WhatsApp subscriber
```

Callbacks are copied under a lock and submitted without blocking the publisher. `_safe_call` catches/logs subscriber exceptions so notification or logging failure cannot change the order response.

## Topics

| Topic | Event |
|---|---|
| `order.placed` | Successful single order |
| `order.failed` | Failed order |
| `order.no_action` | Smart order already at target |
| `order.modified`, `order.modify_failed` | Modify result |
| `order.cancelled`, `order.cancel_failed` | Cancel result |
| `orders.all_cancelled` | Cancel-all summary |
| `position.closed` | Close-position summary |
| `basket.completed` | Basket summary |
| `split.completed` | Split summary |
| `options.completed` | Options-order summary |
| `multiorder.completed` | Multi-leg summary |
| `analyzer.error` | Analyzer validation/runtime error |
| `sandbox.order_filled` | Engine-driven fill refresh |
| `sandbox.auto_squareoff` | Engine-driven square-off refresh |
| `sandbox.t1_settlement` | Engine-driven settlement refresh |

Batch services suppress child events and publish one summary, preventing duplicate logs/chat alerts.

## Subscribers

`subscribers/register_all()` wires log, Socket.IO, Telegram, and WhatsApp callbacks for order topics. Sandbox engine-internal topics go only to Socket.IO because they are UI refresh signals rather than user API calls; they are not duplicated into analyzer logs or chat alerts.

Telegram/WhatsApp subscribers skip failure and analyzer-error chat notifications. The log and Socket.IO consumers still record/emit the applicable state.

## Event Data

Order events carry mode, API type, strategy, request/response data, and fields needed for notification formatting. API keys may be passed in memory for username resolution but must be stripped from persisted request logs. Do not add broker tokens or other decrypted credentials to an event.

## Why Per-Process

The bus decouples side effects on a single request path with minimal dependencies. It makes no durability or cross-worker delivery guarantee. Features that require cross-process delivery, replay, or durable queues need a different transport; do not infer those properties from this bus.

## Adding An Event Or Subscriber

1. Add a typed event under `events/` with a stable topic.
2. Publish once at the service boundary, after the outcome is known.
3. Add callbacks and registrations in `subscribers/__init__.py`.
4. Keep callbacks idempotent where duplicate upstream requests are possible.
5. Test publisher response independence and subscriber failure isolation.

## Key Files

| File | Purpose |
|---|---|
| `utils/event_bus.py` | Bus and executor singleton |
| `events/` | Typed payloads |
| `subscribers/__init__.py` | Registration |
| `subscribers/log_subscriber.py` | Database logging |
| `subscribers/socketio_subscriber.py` | Browser refresh/events |
| `subscribers/telegram_subscriber.py` | Telegram alerts |
| `subscribers/whatsapp_subscriber.py` | WhatsApp alerts |
