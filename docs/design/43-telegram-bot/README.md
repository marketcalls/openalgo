# 43 - Telegram Bot

## Components

| Component | Responsibility |
|---|---|
| `blueprints/telegram.py` | Session-authenticated React UI APIs for config, lifecycle, users, analytics, explicit sends |
| `restx_api/telegram_bot.py` | API-key REST management and direct notification resources |
| `services/telegram_bot_service.py` | Bot initialization, polling, commands, lifecycle |
| `services/telegram_alert_service.py` | Synchronous HTTP delivery, async executor, retry queue, formatting |
| `database/telegram_db.py` | Encrypted config, linked users, preferences, notifications/stats |
| `subscribers/telegram_subscriber.py` | EventBus-to-alert mapping |

The React pages live under `frontend/src/pages/telegram/` and use `frontend/src/api/telegram.ts`.

## Lifecycle

The bot configuration persists an encrypted token, polling/webhook settings, and `is_active`. Start initializes the bot and starts polling when configured. Stop updates the persisted active state and stops the service.

`is_active` is the source of truth for automatic-alert gating. Order-event alerts and Flow Telegram nodes skip delivery when the bot is stopped. Explicit UI test/send/broadcast actions and `/api/v1/telegram/notify` intentionally bypass this gate because they are direct human/API requests.

## EventBus Alerts

Successful order-related topics are mapped through `telegram_subscriber.py` to `send_order_alert()`. Failure events and analyzer errors are deliberately not sent to chat. Batch operations produce one summary event, avoiding one notification per child order.

Alerts resolve the local username from the API key, verify that a Telegram user is linked and notifications are enabled, then enqueue delivery on the shared five-worker alert executor.

## Explicit Delivery

`send_alert_sync()` calls Telegram's HTTP API through `httpx`. It supports Markdown formatting fallback to plain text and queues failed/timeout deliveries in the notification store. The REST notify endpoint can use fire-and-forget or wait for one immediate delivery attempt.

## RESTX Surface And Limitations

The `/api/v1/telegram` namespace registers config GET/POST, start, stop, webhook, users, broadcast, notify, stats, and preferences GET/POST.

Current limitations must remain explicit:

- The REST webhook validates `X-Telegram-Bot-Api-Secret-Token` and acknowledges valid updates, but its command dispatch call is not implemented.
- The REST broadcast handler validates input/config but currently returns zero successful and zero failed deliveries.
- These limitations do not apply to the session-authenticated blueprint broadcast path, which iterates linked users and attempts delivery.

## Webhook Security

The expected secret comes from `TELEGRAM_WEBHOOK_SECRET`; if absent, the handler derives a fallback from the stored bot token. Missing and incorrect headers return 401 and 403. Payloads must be objects containing `update_id`.

## Rate Limits

REST Telegram calls normally use `TELEGRAM_RATE_LIMIT` (default 30 per minute). REST broadcast uses 5 per minute. Telegram's upstream limits and transient errors are handled separately by delivery/retry behavior.

## Commands And Charts

Bot commands query normalized order/account data, control supported automation actions, and can render charts using Plotly/Kaleido. Chart rendering requires the Chromium/Kaleido runtime verified by Docker CI. The exact command registry belongs to `telegram_bot_service.py`, not a copied static list in this architecture page.

## Key Files

| File | Purpose |
|---|---|
| `blueprints/telegram.py` | Authenticated web management |
| `restx_api/telegram_bot.py` | External REST resources |
| `services/telegram_bot_service.py` | Command and bot lifecycle |
| `services/telegram_alert_service.py` | Delivery and gating |
| `database/telegram_db.py` | Persistent state |
| `frontend/src/pages/telegram/TelegramConfig.tsx` | React configuration page |
