# 53 - Event Bus

## Scope

`utils/event_bus.py` is a lightweight, **per-process** topic bus for asynchronous order side effects. It is not the cross-process market-data bus; ZeroMQ owns that job.

The single production Flask worker owns the singleton subscriber registry. A service publishes in the process handling the request, and that process dispatches its local subscribers. Ordinary callbacks use a shared 10-worker executor with at most 1,000 queued-or-running callbacks. `critical=True` subscriptions use a separate four-worker executor with a 10,000-callback cap so slow notification delivery does not consume the strategy/order-update lane.

## Flow

```text
order/sandbox service
  -> typed event with topic
  -> EventBus.publish()
  -> shared per-process thread pool
     -> log subscriber
     -> Socket.IO subscriber
     -> alert subscriber (raise_alert)
          -> alert.raised, only when a channel receives the event group
               -> alert subscriber (deliver_alert)
                    -> each routed channel: Telegram, WhatsApp, Slack, Discord
```

Callbacks are copied under a lock and submitted without waiting for subscribers. At capacity, the ordinary lane drops callbacks and logs sampled warnings; the critical lane is also bounded and logs every overflow as an error. Neither lane guarantees durable delivery. Callback failures are isolated, and every callback releases the SQLAlchemy scoped sessions it opened. `bus.stats()` reports pending/capacity/drop counters for both lanes.

## Topics

| Topic | Event |
|---|---|
| `order.placed` | Successful single order |
| `order.failed` | Failed order |
| `order.update` | Broker postback/order-WebSocket and sandbox execution transitions |
| `gtt.placed`, `gtt.failed` | GTT placement outcomes |
| `gtt.modified`, `gtt.modify_failed` | GTT modification outcomes |
| `gtt.cancelled`, `gtt.cancel_failed` | GTT cancellation outcomes |
| `gtt.triggered`, `gtt.expired` | GTT lifecycle transitions |
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

`subscribers/__init__.py:register_all()` wires log and Socket.IO callbacks for order topics, and `alert_subscriber.register()` adds one callback per alertable topic plus one delivery callback for `alert.raised`. An order event therefore costs two alert callbacks whatever the number of channels; each channel's `deliver` only queues on its own pool, so a slow provider does not hold a bus worker. Sandbox engine-internal topics go only to Socket.IO because they are UI refresh signals rather than user API calls; they are not duplicated into analyzer logs or chat alerts.

`order.update` also feeds the ZMQ relay and registered critical strategy-book, Strategy Module and Flow order monitors; these are distinct from best-effort chat alerts.

Failure and analyzer-error events have no alert group, so they raise no alert on any channel. The log and Socket.IO consumers still record/emit the applicable state.

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
| `subscribers/alert_subscriber.py` | Raises one `alert.raised` event per alertable order event, and subscribes every alert channel to it |
| `services/alerts/` | Alert groups, routing, settings and the Telegram, WhatsApp, Slack and Discord channels |
