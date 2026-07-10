# Telegram REST API

The Telegram namespace exposes configuration, lifecycle, user, notification, statistics, and preference resources. Most calls accept the OpenAlgo key in `X-API-KEY`, the `apikey` query parameter for GET, or the JSON body for POST.

## Endpoint Inventory

| Method | Path | Authentication | Current behavior |
|---|---|---|---|
| GET | `/api/v1/telegram/config` | API key | Returns configuration with the bot token masked |
| POST | `/api/v1/telegram/config` | API key | Updates accepted configuration fields |
| POST | `/api/v1/telegram/start` | API key | Initializes polling or webhook mode from stored config |
| POST | `/api/v1/telegram/stop` | API key | Stops the bot service |
| POST | `/api/v1/telegram/webhook` | Telegram secret header | Validates and acknowledges updates; dispatch is not implemented |
| GET | `/api/v1/telegram/users` | API key | Lists linked users, optionally filtered |
| POST | `/api/v1/telegram/broadcast` | API key | Validates request but currently reports zero deliveries |
| POST | `/api/v1/telegram/notify` | API key | Queues or synchronously sends one linked user's message |
| GET | `/api/v1/telegram/stats` | API key | Returns command statistics for 1 to 365 days |
| GET | `/api/v1/telegram/preferences` | API key | Reads preferences for a `telegram_id` |
| POST | `/api/v1/telegram/preferences` | API key | Updates supported preferences for a `telegram_id` |

## Direct Notification

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/telegram/notify' \
  -H 'Content-Type: application/json' \
  -d '{
    "apikey": "<your_app_apikey>",
    "username": "openalgo-user",
    "message": "Strategy alert",
    "wait_for_delivery": false
  }'
```

`username` must already be linked to a Telegram ID. With the default asynchronous path, HTTP 200 means queued, not confirmed delivered. `wait_for_delivery: true` waits for an immediate attempt; a failed attempt is queued for retry and still returns a queued success message.

## Webhook Authentication

Telegram sends `X-Telegram-Bot-Api-Secret-Token`. OpenAlgo compares it with `TELEGRAM_WEBHOOK_SECRET`, or with a token-derived fallback when the explicit secret is absent. Missing and incorrect headers return 401 and 403 respectively. Structurally valid updates are acknowledged with an empty HTTP 200 response, but `process_webhook_update` is not implemented in this RESTX handler.

## Automatic Alert Gate

Order-event and Flow alerts check the persisted bot `is_active` state. Stopping the bot suppresses those automatic alerts. Explicit admin sends and `/telegram/notify` intentionally bypass that gate.

## Rate Limits

Most Telegram resources use `TELEGRAM_RATE_LIMIT` (default `30 per minute`). Broadcast is independently limited to `5 per minute`.

**Back to**: [API documentation](../README.md)
