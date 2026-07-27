# WhatsApp Services

WhatsApp delivery via the unofficial multi-device protocol, powered by the
[`wars`](https://pypi.org/project/wars/) library (Rust core via PyO3).

OpenAlgo runs one paired WhatsApp Web session per install. Once paired
from the `/whatsapp` admin page, the bot stays connected in the same
Flask process that serves orders, so notifications fire from the same
event bus that drives Telegram alerts. Linked users can also run slash
commands against the bot (`/orderbook`, `/positions`, `/quote`, etc.)
once they send `/link <api_key>` from their phone.

## Security model — minimal REST surface

The REST API at `/api/v1/whatsapp/` exposes **exactly one** endpoint:
`POST /notify` (send a message). Everything else — pairing, unpairing,
starting / stopping the bot, reading or mutating config, listing linked
recipients, broadcasting to all of them, viewing stats, editing
preferences — is **admin-only** and lives behind the Flask session cookie
at `/whatsapp/...` (consumed by the React `/whatsapp` admin page).

Why this stance:

- The paired-device session blob is functionally a credential to the
  operator's WhatsApp account. A leaked API key must never be enough to
  re-pair the bot or wipe an existing session.
- A leaked API key must never let an attacker enumerate the operator's
  linked contact list, change rate limits, or fan out to every linked
  user via `/broadcast`.
- The paired session blob (~300 KB of Signal Protocol private keys) is
  encrypted at rest with a Fernet key derived from
  `API_KEY_PEPPER + FERNET_SALT + ":whatsapp-session"`. Anyone with the
  `openalgo.db` file **and** the `.env` secrets can impersonate the
  device — keep both secret.

## REST endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| [Notify](./notify.md) | POST | Send text / image / document to self, one user, or up to 5 recipients. |

That is the entire public surface.

## Admin operations (web UI only)

Performed on the logged-in `/whatsapp` page. Not exposed via API key:

- **Pair** a new device (QR or pair-code).
- **Unlink** the paired device (wipes the encrypted session blob).
- **Start / Stop** the bot's WhatsApp connection.
- **Config**: toggle broadcast, adjust rate limits, message length cap.
- **Users**: list and revoke linked recipients.
- **Broadcast**: send to every linked user matching filters.
- **Stats**: command usage analytics.
- **Preferences**: per-user notification toggles.

These are all routed through `blueprints/whatsapp.py` with
`@check_session_validity`, so only the logged-in OpenAlgo admin can
invoke them.

## Quick example: trade alert to yourself

```bash
curl -X POST http://127.0.0.1:5000/api/v1/whatsapp/notify \
  -H 'Content-Type: application/json' \
  -d '{
    "apikey": "<your_app_apikey>",
    "self": true,
    "message": "Build #482 deployed. P&L: +1.2%"
  }'
```

## Quick example: chart to client + yourself

```bash
curl -X POST http://127.0.0.1:5000/api/v1/whatsapp/notify \
  -H 'Content-Type: application/json' \
  -d '{
    "apikey": "<your_app_apikey>",
    "phones": ["919876543210", "919812345678"],
    "image_path": "/srv/charts/nifty_eod.png",
    "caption": "NIFTY end-of-day chart"
  }'
```

Up to 5 recipients per call — anything beyond that is dropped. This is a
ToS-safety guardrail; bulk-messaging patterns can get the paired device
unlinked by Meta.

## Receiving messages (bot commands)

Once paired, any WhatsApp user can message the bot and run queries:

```
/link <YOUR_API_KEY>        # one-time, links this WhatsApp number to your OpenAlgo user
/orderbook                  # today's orders
/positions                  # open positions
/funds                      # available cash
/pnl                        # net P&L
/quote RELIANCE NSE         # last traded price
/closeall                   # square off all positions
/help                       # full command list
```

Each command runs against the OpenAlgo SDK using the linked user's API
key, so results are identical to what you would get from the REST API.

## Event-driven order alerts

When you place an order via `/api/v1/placeorder` (or any of the other
order endpoints), the order service publishes an `order.placed` event to
the in-process event bus. The WhatsApp subscriber listens on every order
topic — `order.placed`, `order.modified`, `order.cancelled`,
`orders.all_cancelled`, `position.closed`, `basket.completed`,
`split.completed`, `options.completed`, `multiorder.completed` — and
sends the linked user a formatted alert automatically. No explicit
`/notify` call needed.

The Telegram subscriber sits on the same topics, so both channels fire
in parallel from a single order placement.

## Rate limits

| Endpoint | Limit |
|----------|-------|
| `/notify` | 30 / minute |
| Bot commands (inbound) | 10 / second per linked user |
