# Event Bus PRD

## Purpose

OpenAlgo uses an in-process event bus to separate order and sandbox state changes from logging, live UI updates, and notification delivery. It is not a durable message broker and does not replace the ZeroMQ market-data channel.

## Runtime Contract

- `utils/event_bus.py` owns a process-local singleton.
- Publishers route typed events by topic without waiting for subscriber completion.
- Ordinary callbacks execute in a shared 10-worker executor with at most 1,000 queued-or-running callbacks.
- `critical=True` callbacks use a separate four-worker executor with a 10,000-callback cap. Ordinary saturation drops callbacks with sampled warnings; critical overflow logs every dropped callback as an error.
- Every callback releases the scoped SQLAlchemy sessions it opened; pool threads outlive individual events.
- `bus.stats()` exposes pending, capacity and dropped counters for both lanes.
- Subscription mutation and callback-list snapshots are protected by a lock.
- One subscriber failure is logged and isolated from other subscribers.
- Events are not persisted, replayed, or delivered across processes.

## Registered Topics

Application startup registers handlers for:

- Order placed, failed, no-action, modified, modify-failed, cancelled, and cancel-failed events.
- All-orders-cancelled and position-closed events.
- Broker/sandbox order-update events and GTT placed, failed, modified, cancelled, triggered and expired events.
- Basket, split, options, and multi-order completion events.
- Analyzer error events.
- Sandbox order-filled, auto-square-off, and T+1 settlement events.

## Subscribers

| Subscriber | Responsibility |
|---|---|
| Log | Persist normalized order/analyzer outcomes |
| Socket.IO | Emit live order, analyzer, and sandbox UI updates |
| Telegram | Deliver eligible successful order notifications when the automatic-alert gate is active |
| WhatsApp | Deliver eligible successful order notifications |
| ZMQ order relay | Forward private order updates for authenticated installation clients |
| Strategy book / Strategy Module / Flow order monitors | Consume critical execution/tagging and order-update events |

Sandbox engine-internal events are intentionally wired only to Socket.IO. They are not user API calls and are not duplicated into analyzer logs or chat notifications.

## Requirements

- Persisted request logs and notification payloads must omit API keys. An event may carry an API key in memory for internal username resolution; do not persist that field or add broker secrets.
- Batch services must publish their intended summary event without creating duplicate user notifications.
- Analyzer events must retain analyzer/live mode context.
- Notification subscribers may skip failed and analyzer-error events according to their delivery policy.
- Telegram automatic events must honor persisted bot activation state; explicit notify operations remain separate commands.

## Ownership And Coverage

| Area | Source |
|---|---|
| Bus implementation | `utils/event_bus.py` |
| Event types | `events/` |
| Startup wiring | `subscribers/__init__.py`, `app.py` |
| Side effects | `subscribers/` |

See `docs/design/53-event-bus/README.md` and `docs/bdd/notifications_observability.feature`.
