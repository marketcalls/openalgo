# WhatsApp

### Overview

The OpenAlgo WhatsApp Bot connects your OpenAlgo install to a WhatsApp account that you control. It does two things:

1. **Outbound** — fires real-time order alerts to you (and optionally to a small list of recipients) via the same event bus that already drives Telegram, so a `/api/v1/placeorder` call lands as a WhatsApp message on your phone moments later.
2. **Inbound** — accepts slash-command queries (`/orderbook`, `/positions`, `/quote`, …) that you type from your **own phone** in the "Message yourself" chat. The bot replies in the same chat. Commands are gated by WhatsApp's own multi-device protocol — random contacts who message your number cannot drive the bot.

Unlike Telegram, WhatsApp has no separate "bot account" concept. The OpenAlgo server runs as a **linked device** on your personal WhatsApp account — the same way WhatsApp Web does. You pair once with a QR scan and the encrypted session lives in `openalgo.db`.

### Features

* **One-time pairing** — Scan a QR code from the admin web UI. The session blob is Fernet-encrypted at rest and auto-reconnects on every server boot. No bot token, no third-party service registration.
* **Event-driven alerts** — Every order topic the event bus already publishes (`order.placed`, `order.modified`, `order.cancelled`, `orders.all_cancelled`, `position.closed`, `basket.completed`, `split.completed`, `options.completed`, `multiorder.completed`) fires a WhatsApp message in parallel with Telegram.
* **Unified send API** — One `client.whatsapp(...)` call in the Python SDK and one `POST /api/v1/whatsapp/notify` endpoint over REST handle text, image, document, self-send, single recipient, and small broadcast (up to 5) cases.
* **Real-time trading queries** — Slash-commands from the operator's own phone trigger SDK calls and reply with the result in the same chat.
* **Single-user security model** — The paired device IS the operator. The bot only responds to messages where WhatsApp marks `is_from_me=True` (mirrored from the operator's primary phone). Random contacts who message the operator's number arrive with `is_from_me=False` and are silently ignored.
* **Admin-only pairing** — Pair, unpair, start, stop, config, broadcast, stats, and preferences live behind the session-authed `/whatsapp` admin page. The REST API surface is deliberately narrowed to send-only so a leaked API key cannot re-pair the device or enumerate recipients.

### Setup

#### 1. Pair Your WhatsApp Device in OpenAlgo

1. Log in to OpenAlgo.
2. From the profile dropdown (top-right) click **WhatsApp Bot**, or navigate to `/whatsapp`.
3. Click **Start pairing**. A QR code renders inline on the page.
4. On your phone: open WhatsApp → **Settings** → **Linked devices** → **Link a device** → scan the QR.
5. The QR refreshes automatically every ~30 seconds. Each refresh streams a fresh `whatsapp_qr` SocketIO event to your browser, so the UI swaps the image without polling.
6. On successful scan, the status flips to **Connected** and the bot is ready.

That's the entire setup. No bot token, no developer account, no external service.

> **Note:** WhatsApp permits a maximum of four (currently) linked devices per account. If you're already at the cap, remove an unused linked device on your phone before pairing OpenAlgo.

#### 2. (Optional) Generate an OpenAlgo API Key

Slash-command queries (`/orderbook`, `/positions`, etc.) execute against the OpenAlgo SDK using **your own** OpenAlgo API key, looked up server-side. If you haven't generated one yet:

1. Navigate to **API Key** in the profile dropdown.
2. Generate a key.

The bot pulls this key automatically from `auth_db` — you don't paste it anywhere on WhatsApp, and the key never leaves the server.

#### 3. (Optional) Configure Attachment Allowlist

If you plan to send images or documents via the API, set `WHATSAPP_ATTACHMENT_ROOTS` in `.env` to a comma-separated list of absolute directories from which the server may read media:

```
WHATSAPP_ATTACHMENT_ROOTS=/srv/charts,/srv/reports
```

When unset, the default allowlist is `<openalgo>/db/attachments/` only. Paths containing `..`, paths under sensitive system trees (`/etc`, `/proc`, `/sys`, `/root`, `/var/log`, `C:\Windows`, `C:\Users\Default`), and paths that resolve outside the allowlist are always rejected with `400 image_path is not allowed`.

### How to Send Commands

Commands work differently from Telegram. WhatsApp has no separate bot identity — the bot **is** your own WhatsApp account, running as a linked device on the OpenAlgo server.

1. Open WhatsApp on your phone.
2. Scroll to the top of your chat list — there's a chat titled **"You"** or your own name (the "Message yourself" chat that WhatsApp creates automatically).
3. Type a command starting with `/`, e.g. `/orderbook`.
4. The linked device on the OpenAlgo server sees the message as `is_from_me=True`, dispatches it, runs the matching SDK call, and replies in the same chat.
5. The reply arrives back on your phone within a second or two.

### Available Commands

#### Connection Status

* `/start`, `/help`, `/menu` — Show the full command list
* `/status` — Bot connection state, paired status, owner username

#### Trading Data

* `/orderbook` — Today's orders
* `/tradebook` — Today's executed trades
* `/positions` — Open positions
* `/holdings` — Portfolio holdings
* `/funds` — Available cash + margin utilisation
* `/pnl` — Net realised + unrealised P&L

#### Market Data

* `/quote <symbol> [exchange]` — Last traded price
  * Example: `/quote RELIANCE`
  * Example: `/quote NIFTY NSE_INDEX`
  * Defaults to `NSE` if exchange omitted

#### Trade Actions

* `/closeall` — Square off all open positions

#### Mode

* `/mode` — Show whether the OpenAlgo instance is in `live` or `analyze` (sandbox) mode

Each reply is a plain-text WhatsApp message (no Markdown rendering — WhatsApp's `*bold*`, `_italic_`, ``` ```mono``` ``` markers are preserved). Long responses are auto-truncated at 3,500 characters.

### Order Alerts (Automatic Notifications)

#### Overview

The bot automatically sends a WhatsApp message to the paired device's own number for every order-related API activity. No additional commands are needed — alerts are sent automatically when orders flow through the OpenAlgo API.

#### Supported Order Events

| Topic | Trigger |
| --- | --- |
| `order.placed` | `/api/v1/placeorder` succeeded |
| `order.no_action` | Smart order found nothing to do |
| `order.modified` | `/api/v1/modifyorder` succeeded |
| `order.cancelled` | `/api/v1/cancelorder` succeeded |
| `orders.all_cancelled` | `/api/v1/cancelallorder` succeeded |
| `position.closed` | `/api/v1/closeposition` succeeded |
| `basket.completed` | All legs of a `/basketorder` completed |
| `split.completed` | All sub-orders of a `/splitorder` completed |
| `options.completed` | All legs of an `/optionsorder` (split path) completed |
| `multiorder.completed` | All legs of an `/optionsmultiorder` completed |

Failure events (`order.failed`, `order.modify_failed`, `order.cancel_failed`, `analyzer.error`) deliberately do **not** fire WhatsApp messages — matching the existing Telegram convention so a flood of validation rejections doesn't spam the operator's phone.

#### Alert Format

Each alert includes:

* **Mode Indicator**:
  * `*LIVE MODE - Real Order*` — order executed with the broker
  * `*ANALYZE MODE - No Real Order*` — sandbox / simulated order
* **Order Details**: Symbol, action, quantity, price type, exchange, product
* **Status**: Success or failure with error messages if applicable
* **Order ID**: Broker order identifier for tracking
* **Timestamp**: Time of execution
* **Strategy Name**: If provided in the API call

#### Example Notifications

**Live Order Placed:**

```
*Order Placed*
Strategy: MyStrategy
*LIVE MODE - Real Order*
---------------------
Symbol: RELIANCE
Action: BUY
Quantity: 10
Price Type: MARKET
Exchange: NSE
Product: MIS
Order ID: 250408000989443
Time: 14:23:45
```

**Analyze (Sandbox) Mode Order:**

```
*Order Placed*
Strategy: TestStrategy
*ANALYZE MODE - No Real Order*
---------------------
Symbol: RELIANCE
Action: BUY
Quantity: 10
Price Type: MARKET
Exchange: NSE
Product: MIS
Order ID: ANALYZE123456
Time: 14:23:45
```

#### Configuration

* Alerts are **enabled by default** for the paired owner — no toggle needed for the single-user case.
* On disconnect / not-paired state, alerts are **silently dropped** (not queued). Pair from `/whatsapp` first; once the bot is connected, new order events flow normally.
* Zero impact on order execution speed — every alert goes through the event bus's thread pool, never on the order-placement critical path.

#### Requirements for Receiving Alerts

1. WhatsApp device must be paired in OpenAlgo (`/whatsapp` page in the web UI).
2. The OpenAlgo server must have rebooted at least once since pairing OR the bot must be currently connected (auto-reconnects on every boot from the encrypted session blob).
3. Orders must be placed through the OpenAlgo API (REST `/api/v1/*`, the Python SDK, or any tool that ultimately hits the API).

### Sending Messages via API

In addition to the automatic order alerts, you can send arbitrary WhatsApp messages from your own code through the OpenAlgo REST API or the Python SDK.

#### Python SDK (1.0.50+)

```python
from openalgo import api

client = api(api_key="your_api_key", host="http://127.0.0.1:5000")

# Send to yourself
client.whatsapp("Build #482 deployed. P&L: +1.2%")

# Send to a single number
client.whatsapp("Order placed: BUY RELIANCE x 10", to="919876543210")

# Small broadcast (max 5 recipients)
client.whatsapp(
    "Server maintenance in 10 minutes",
    to=["919876543210", "919812345678", "919900112233"],
)

# Image with caption
client.whatsapp(
    "NIFTY end-of-day chart",
    to="919876543210",
    image="/srv/charts/nifty_eod.png",
)

# Document attachment
client.whatsapp(
    "Daily P&L report attached",
    document="/srv/reports/eod.pdf",
    filename="DailyPnL.pdf",
)
```

#### REST API

```bash
curl -X POST http://127.0.0.1:5000/api/v1/whatsapp/notify \
  -H 'Content-Type: application/json' \
  -d '{
    "apikey": "your_api_key",
    "self": true,
    "message": "Order placed: BUY RELIANCE x 10"
  }'
```

**Sample success response:**

```json
{
  "status": "success",
  "message": "Delivered to 1, failed 0",
  "data": {
    "sent":    ["<self>"],
    "failed":  [],
    "skipped": 0
  }
}
```

**Sample not-paired response (HTTP 409):**

```json
{
  "status": "error",
  "message": "WhatsApp is not paired or not connected. Pair the device first from the /whatsapp page in OpenAlgo before sending."
}
```

The API refuses with HTTP 409 rather than silently queueing — a trader expects an alert to either deliver or fail loudly, not appear later out of nowhere.

#### Recipient Forms

Exactly one of the following must be specified (defaults to `self` if all are omitted):

| Field | Type | Description |
| --- | --- | --- |
| `self` | bool | `true` → send to the paired device's own number (the operator) |
| `username` | string | OpenAlgo username — resolves via the linked-users table |
| `phone` | string | Single E.164 digit string, e.g. `"919876543210"` |
| `phones` | array | Up to 5 E.164 digit strings (small broadcast). Anything beyond 5 is dropped server-side |

#### Payload Fields

| Field | Type | Description |
| --- | --- | --- |
| `message` | string | Text body, max 4096 characters |
| `image_path` | string | Server-local path to an image (must be inside `WHATSAPP_ATTACHMENT_ROOTS`) |
| `document_path` | string | Server-local path to a document |
| `caption` | string | Caption for image, or follow-up text for document |
| `filename` | string | Override the document's display name on the recipient device |
| `wait_for_delivery` | bool | Default `true`. When `true`, block until WhatsApp confirms and return the per-recipient delivery report |

### Security

#### Pairing Stays Inside the Web UI

The QR-scan / pair-code flow lives behind `POST /whatsapp/pair`, which is protected by the Flask **session cookie** (`@check_session_validity`). It is deliberately **not** exposed in the public REST API. An OpenAlgo API key alone cannot:

* Create a new paired device session
* Wipe the existing session
* Read or rotate `whatsapp_config`
* List linked recipients
* Fan out a `/broadcast` to all linked users
* Read command stats

A leaked API key can only send messages via `POST /api/v1/whatsapp/notify` — the narrowest possible surface for the trader's automation use case.

#### Encryption at Rest

The paired-device session blob (~300 KB of Signal Protocol private keys, identity material, and registration info from wars/whatsapp-rust) is **Fernet-encrypted** before writing to `openalgo.db`:

* Fernet key derived via PBKDF2-SHA256 from `API_KEY_PEPPER` and `FERNET_SALT + b":whatsapp-session"` (100,000 iterations, 32-byte output)
* The `:whatsapp-session` suffix is a domain separator — the same `(PEPPER, FERNET_SALT)` pair derives **different** Fernet keys for broker auth tokens (`database/auth_db.py`), Telegram bot tokens (`database/telegram_db.py`), and the WhatsApp session blob (`database/whatsapp_db.py`). Compromising one channel's ciphertext gives no leverage against the others.

Compromise model:

| Attacker has | Outcome |
| --- | --- |
| `openalgo.db` only | Useless — ciphertext without key |
| `.env` only | Useless — no ciphertext to decrypt |
| `openalgo.db` + `.env` | Full impersonation of the linked WhatsApp device |

Keep both off public hosts, off public git, and off any backup destination that mixes the two.

#### Owner-Only Bot Commands

Slash-commands are gated by WhatsApp's own multi-device cryptography. When the operator types `/orderbook` from their primary phone, WhatsApp marks the message as `is_from_me=True` when mirroring it to the linked OpenAlgo device. Random contacts who message the operator's number arrive with `is_from_me=False`. The bot's handler unconditionally drops the latter — there is no allowlist to maintain or `/link` flow to manage.

#### Attachment Path Allowlist

Image and document paths are validated server-side against:

1. **Path-traversal rejection** — paths containing `..` are refused before any filesystem call
2. **Absolute-path requirement** — relative paths are refused
3. **Deny-list** — `/etc`, `/proc`, `/sys`, `/root`, `/var/log`, `C:\Windows`, `C:\Users\Default` are rejected outright
4. **`WHATSAPP_ATTACHMENT_ROOTS` allowlist** — the resolved real path (one symlink hop followed) must live under one of the configured roots

Rejected paths return `400 image_path is not allowed` without echoing the path back, so misuse doesn't leak the operator's filesystem layout.

#### Sensitive Args Scrubbed from Audit Logs

The `whatsapp_command_logs` table records every slash-command for auditability, but command args carrying credentials are replaced with `<redacted>` before write.

### Database Schema

The bot uses SQLAlchemy ORM with the following tables in `openalgo.db`:

#### whatsapp_config

Singleton row (id=1) holding:

* `session_blob` — Fernet-encrypted wars session bytes
* `own_jid`, `own_phone`, `bot_username` — captured lazily after the first `is_from_me=True` message
* `owner_user_id`, `owner_username` — captured at pair time from the Flask session
* `is_paired`, `is_active`, `paired_at` — lifecycle state
* `max_message_length`, `rate_limit_per_minute`, `broadcast_enabled` — operational tunables

#### whatsapp_users (optional, multi-recipient)

Linked recipient phone numbers and their OpenAlgo username/api_key mapping. Unused in the standard single-user deployment.

#### whatsapp_command_logs

Audit trail of every slash-command — JID, command name, scrubbed parameters, timestamp.

#### whatsapp_notification_queue

Reserved for failed-delivery retry. Single-user mode does not queue (refuses with HTTP 409 if not paired); kept for future multi-recipient deployments.

#### whatsapp_user_preferences

Per-user notification toggles (`order_notifications`, `trade_notifications`, `pnl_notifications`, `daily_summary`, `summary_time`, `language`, `timezone`).

### Technical Architecture

#### Components

1. **`services/whatsapp_bot_service.py`** — `WhatsAppBotService` singleton

   * Owns the wars (PyO3 over whatsapp-rust) instance via a dedicated `WhatsAppBotThread`. wars's `WhatsApp` class is marked `#[pyclass(unsendable)]` and panics if touched from any thread other than its creator, so all `wars.send()` calls funnel through a `queue.Queue` and are dispatched by the worker thread.
   * Re-entrant: command handlers (which wars dispatches on the bot thread itself via `on_message`) bypass the queue via a `threading.get_ident() == self._bot_thread_id` check so they don't deadlock on themselves.
   * Handles pair flow (temp wars instance + `wait_until_ready` as the authoritative "paired" signal), connection lifecycle, slash-command dispatch, and SDK-backed query handlers (`/orderbook`, `/positions`, …).

2. **`services/whatsapp_alert_service.py`** — `WhatsAppAlertService`

   * Outbound notifier. Formats order/position/batch events into plain-text WhatsApp messages with LIVE / ANALYZE mode prefix.
   * Single-user owner resolution: matches the event's `api_key` → username via `auth_db.get_username_by_apikey`, then checks against `whatsapp_config.owner_username` captured at pair time. If matched, fires a self-send through wars's single-arg `send("text")` form (no need to know own JID — wars knows its own identity internally).

3. **`subscribers/whatsapp_subscriber.py`** — Event-bus subscriber

   * Registered alongside `telegram_subscriber` in `subscribers/__init__.register_all()` on all 13 order/position/batch topics.
   * Mirrors the Telegram convention: failure events (`order.failed`, `order.modify_failed`, `order.cancel_failed`, `analyzer.error`) are silently dropped.

4. **`database/whatsapp_db.py`** — SQLAlchemy models

   * 5 tables + Fernet encryption helpers + idempotent `PRAGMA table_info` migration for the `owner_user_id` / `owner_username` columns

5. **`restx_api/whatsapp_bot.py`** — `POST /api/v1/whatsapp/notify`

   * The only public REST endpoint. Validates recipient + payload + attachment paths, dispatches synchronously by default (`wait_for_delivery=true`) so the response carries the real delivery report.

6. **`blueprints/whatsapp.py`** — Session-authed admin routes

   * `/whatsapp/pair`, `/whatsapp/pair/status`, `/whatsapp/unlink`, `/whatsapp/bot/start`, `/whatsapp/bot/stop`, `/whatsapp/bot/status`, `/whatsapp/config`, `/whatsapp/users`, `/whatsapp/broadcast`, `/whatsapp/send`, `/whatsapp/test-message`, `/whatsapp/stats`
   * All gated by `@check_session_validity`; consumed by the React `/whatsapp` page.

7. **`frontend/src/pages/whatsapp/WhatsAppIndex.tsx`** — React admin page

   * Pair flow with auto-rotating QR (SocketIO `whatsapp_qr` event), Disconnect button, send-to-phone composer.

8. **Auto-reconnect on app boot** — `app.py:_autostart_whatsapp_bot`

   * Background thread spawned in `_init_databases_and_schedulers` after DB init completes
   * If `whatsapp_config.is_paired` is true, loads the encrypted blob and starts the worker thread without operator intervention

#### Event Flow

```
POST /api/v1/placeorder
        │
        ▼
services/place_order_service.place_order(...)
        │
        ▼
bus.publish(OrderPlacedEvent(api_key, ...))
        │
        ├──> log_subscriber          (writes to log/orders.jsonl)
        ├──> socketio_subscriber     (emits order_event for the dashboard)
        ├──> telegram_subscriber     (queues telegram_alert)
        └──> whatsapp_subscriber     (queues whatsapp_alert)
                  │
                  ▼
        whatsapp_alert_service.send_order_alert
                  │
                  ▼ alert_executor (5-worker thread pool)
                  │
                  ▼
        whatsapp_bot_service.send_sync(to=None, text=msg)
                  │
                  ▼ enqueue on _cmd_queue
                  │
                  ▼
        WhatsAppBotThread picks up the command
                  │
                  ▼
        self._wa.send(msg)   (wars's single-arg form → owner)
                  │
                  ▼
        WhatsApp servers → operator's phone
```

#### Threading Model

* The Flask app runs under Gunicorn + eventlet (production) or threaded dev server (development).
* The WhatsApp bot runs on a **dedicated OS thread** (`WhatsAppBotThread`), spawned via `threading.Thread`. wars's internal Rust runtime spawns its own worker threads but routes Python callbacks back to the creator thread, satisfying PyO3's unsendable contract.
* Outbound sends from request threads cross to the bot thread via `queue.Queue` + `threading.Event`.

### Troubleshooting

#### Bot Not Sending Alerts

1. Open `/whatsapp` — verify status badge shows **Connected**. If it shows **Not paired**, scan the QR.
2. Check that you have an OpenAlgo API key generated at `/apikey` (slash-commands need it for SDK calls).
3. Confirm the order actually flowed through `/api/v1/placeorder` (or the SDK / a strategy / any other API path). Orders placed directly via a broker website do NOT trigger event-bus events.
4. Check the server logs for lines like `WhatsApp alert queued for owner user=<username> type=placeorder`. If present, the alert was dispatched.

#### "WhatsApp is not paired or not connected" (HTTP 409)

The bot lost its connection — typically after a long offline period, a WhatsApp protocol upgrade, or your phone being offline for many days.

1. Open `/whatsapp` and re-pair if the badge says **Not paired**.
2. If the badge says **Connected** but sends still fail, restart the OpenAlgo server. Auto-reconnect rebuilds the session from the encrypted blob.

#### Slash Commands Don't Reply

1. Make sure you typed the command in the **"Message yourself"** chat (your own contact at the top of the chat list).
2. Commands must start with `/` and use one of the supported names — check `/help` for the list.
3. Verify the OpenAlgo owner has an API key on file (`/apikey` page).
4. Check `whatsapp_command_logs` table for the command — if it's logged, the bot received and processed it.

#### Attachment Path Rejected

`400 image_path is not allowed` means the path is outside the `WHATSAPP_ATTACHMENT_ROOTS` allowlist or contains a traversal token.

1. Move the file to `<openalgo>/db/attachments/` (the default allowlist), or
2. Add the file's directory to `WHATSAPP_ATTACHMENT_ROOTS` in `.env` and restart OpenAlgo.

Symlinks resolving outside the allowlist are also rejected.

#### "WhatsApp Web is full" / Pairing Fails

WhatsApp allows up to 4 simultaneously linked devices per account. On your phone: **Settings → Linked devices** → remove an unused one (often "WhatsApp Web on Chrome" left over from months ago).

### Environment Variables

The bot respects the following environment variables:

* `DATABASE_URL` — Main OpenAlgo database (WhatsApp tables live here)
* `API_KEY_PEPPER` — Encryption pepper, feeds the Fernet KDF
* `FERNET_SALT` — Per-install random salt (auto-rotated on first boot by `utils/env_check.py`); the `:whatsapp-session` domain suffix is applied internally
* `HOST_SERVER` — OpenAlgo server URL the bot uses for SDK loopback calls (defaults to `http://127.0.0.1:5000`)
* `WHATSAPP_ATTACHMENT_ROOTS` — Optional comma-separated allowlist for media paths. Defaults to `<openalgo>/db/attachments/` only.
* `WHATSAPP_RATE_LIMIT` — Optional REST rate limit override. Defaults to `30 per minute`.
* `WHATSAPP_MESSAGE_RATE_LIMIT` — Optional blueprint rate limit override. Defaults to `10 per minute`.
* `RUST_LOG` — Optional log-level filter for wars / whatsapp-rust. Default silences three known-noisy modules while keeping genuine errors visible.

### API Endpoints

#### Public REST API (API-key auth)

* `POST /api/v1/whatsapp/notify` — Send a message. The only public endpoint.

#### Session-Authed Admin (web UI only)

* `GET /whatsapp/config` — Read bot config + pair state
* `POST /whatsapp/config` — Update operational settings (broadcast toggle, rate limit, max message length)
* `POST /whatsapp/pair` — Start pairing flow
* `GET /whatsapp/pair/status` — Poll pair state (alternative to SocketIO)
* `POST /whatsapp/unlink` — Wipe the encrypted session blob
* `POST /whatsapp/bot/start` — Connect bot using stored session
* `POST /whatsapp/bot/stop` — Disconnect (session retained)
* `GET /whatsapp/bot/status` — Bot lifecycle state
* `GET /whatsapp/users` — List linked recipients (multi-recipient mode)
* `POST /whatsapp/user/<jid>/unlink` — Unlink a recipient
* `POST /whatsapp/broadcast` — Send to all linked users (filtered)
* `POST /whatsapp/send` — One-off send to any number
* `POST /whatsapp/test-message` — Send a test message to the operator
* `GET /whatsapp/stats` — Command usage statistics

#### SocketIO Events (server → frontend)

* `whatsapp_qr` — Fresh QR data URL each time wars rotates the code
* `whatsapp_pair_code` — Pair-code alternative to QR
* `whatsapp_paired` — Pair completed successfully
* `whatsapp_pair_status` — Full pair-state snapshot
* `whatsapp_status` — Bot connection state changes

### Error Handling

* The bot never blocks order placement — alerts fail-soft. If wars isn't ready or the worker queue times out, the send returns a failure report but the order itself is unaffected.
* Failed sends are logged with the exception type and a redacted recipient identifier; raw paths and message bodies are never logged.
* Slash-command handlers that raise an exception return a generic "An error occurred handling that command" reply to the operator and log the full traceback server-side.
* HTTP 409 responses to `/api/v1/whatsapp/notify` indicate the bot isn't paired/connected — the API refuses rather than queueing so the caller sees a clear failure.

### Performance Considerations

* **Worker thread isolation** — wars runs on a dedicated OS thread. Slow `wars.send` calls (e.g. WhatsApp servers throttling, slow network) do not block Flask request threads.
* **Connection pooling** — wars maintains a single persistent WebSocket to WhatsApp servers per process.
* **Alert pool** — Outbound notifications dispatch through a 5-worker `ThreadPoolExecutor` so a burst of order placements can fire alerts in parallel.
* **Event bus** — In-process pub/sub with a 10-worker thread pool. WhatsApp subscriber returns to the bus worker within microseconds (real work happens in the alert pool, then the bot thread).
* **No polling** — wars uses WhatsApp's binary protocol over WebSocket. No HTTP polling, no rate-limit consumption on idle.
* **Idempotent migrations** — Schema changes apply additively on every boot via `PRAGMA table_info`, so the upgrade procedure is just `git pull && uv sync && uv run app.py`.

### WhatsApp Terms of Service — Practical Risk Note

OpenAlgo's WhatsApp integration uses `wars`, an unofficial WhatsApp client. Unofficial clients can get the linked device unlinked, or in rare cases the entire account banned, by Meta's automation. The dominant trigger is send volume and pattern, not the client itself:

* **Low risk (typical OpenAlgo usage)** — A handful of self-send order alerts per day, occasional `/status` replies, sending charts/reports to a small circle of subscribers. Indistinguishable from a person using WhatsApp normally; well under Meta's automated thresholds.
* **Medium risk** — Sending to dozens of distinct contacts who haven't messaged you first, frequent broadcasts, sending the same body to many recipients in a short window.
* **High risk (don't)** — Bulk marketing, cold outreach to scraped numbers, evading rate limits. This is what triggers bans. Use the official WhatsApp Business / Cloud API for those use cases.

The 5-recipient cap on `phones[]` broadcasts is a deliberate ToS-safety guardrail. Treat your paired session as sensitive — it contains the private keys for your linked device.

### Future Enhancements

* [ ] Chart generation (intraday / daily / both) — matching the Telegram bot's `/chart` command
* [ ] Per-recipient notification preferences (currently single-user)
* [ ] Inline reply buttons (WhatsApp Business-only feature; would require a separate Business API path)
* [ ] Voice-note replies via Whisper transcription
* [ ] Daily P&L auto-summary scheduler

### Support

For issues or questions:

1. Check the server logs (`log/openalgo_YYYY-MM-DD.log` + `log/errors.jsonl`)
2. Open `/whatsapp` and inspect the status badge + pair-state JSON via `GET /whatsapp/pair/status`
3. Verify wars is installed: `uv run python -c "import wars; print(wars.__version__)"` — should print `0.1.3` or later
4. Review this documentation
5. Contact OpenAlgo support

---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/whatsapp.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
