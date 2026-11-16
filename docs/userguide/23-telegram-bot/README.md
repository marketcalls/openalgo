# 23 - Telegram Bot

## Configure and Start

1. Create a Telegram bot with BotFather and keep its token private.
2. Open **Telegram Bot** from the profile menu (`/telegram`), then **Bot Configuration** (`/telegram/config`).
3. Save the token, Broadcast Messages preference and per-user message rate limit. Leave the token field empty when changing settings without replacing a saved token.
4. Return to the Telegram dashboard and start the bot. Check its running status.
5. Open a private chat with your bot and send `/start`, then link your OpenAlgo account:

```text
/link <OpenAlgo_API_key> <OpenAlgo_host_URL>
```

The host URL must be reachable by the bot service. On a normal local installation the bot runs on the OpenAlgo server, so a loopback URL can work without exposing the server publicly. Linking validates the key with a funds request. A broker/session error can therefore prevent linking.

The token in Bot Configuration is the Telegram bot token; `/link` uses your OpenAlgo API key. The UI registers users through the bot rather than asking for a comma-separated Chat ID list. Use `/telegram/users` to inspect registered users and notification preferences, and `/telegram/analytics` for command/message activity.

## Commands

Send `/help` to the running bot for its current syntax.

| Command | Purpose |
|---|---|
| `/start` | Register with the bot |
| `/link <api_key> <host_url>` | Link an OpenAlgo account |
| `/unlink` | Remove that account link |
| `/status` | Check the account link/connection |
| `/orderbook`, `/tradebook` | Read orders and trades |
| `/positions`, `/holdings`, `/funds`, `/pnl` | Read account data and P&L |
| `/quote <symbol> [exchange]` | Read a quote |
| `/chart <symbol> [exchange] [type] [interval] [days]` | Request an intraday/daily chart |
| `/closeall` | Ask to close open positions, with confirmation |
| `/stoppython` | Ask to stop running Python strategies, with confirmation |
| `/mode` | View or toggle Live/Analyze mode |
| `/menu` | Open the interactive menu |

`/orders` is not the order-book command; use `/orderbook`. Symbols and exchanges use OpenAlgo's [symbol format](../symbol-format/README.md).

A remote action uses the same OpenAlgo services as the UI. Verify the mode and read the returned result. Stopping Python processes is not a guarantee that their positions were closed. Mode changes affect the whole instance; reconcile running strategies and their positions before changing mode.

## Alerts and Custom Messages

Use the Telegram dashboard to send a test/broadcast message and manage registered recipients. Incoming order/event alerts depend on the linked account, recipient preferences and the event emitted; a Telegram message is not the authoritative order or fill record.

From Python, use the SDK's `telegram` method rather than an extra field on a placement request:

```python
response = client.telegram(message='Strategy check completed')
print(response)
```

See the [Telegram API reference](../../api/telegram-services/README.md) for message routing and [Python SDK reference](<../../prompt/openalgo python sdk.md>) for the client call. Flow offers a Telegram Alert node.

Charts are generated on the server. See [Telegram chart rendering](../../telegram-chart-rendering.md) for supported layouts, data requirements and renderer troubleshooting.

## Troubleshooting

| Symptom | Check |
|---|---|
| Bot does not answer | Saved token, bot running state, outbound network access, application logs |
| Account commands refuse | `/status`, valid OpenAlgo key/host, broker session; relink after replacing the key |
| No notifications | `/start` registration, linked account, active user and notification preferences |
| Rate-limit message | Wait for the configured window; avoid repeatedly sending the same command |
| Chart fails | Symbol/exchange, history availability and renderer logs |
| Close outcome unclear | Broker order book, trades and positions before any replacement order |

---

**Previous**: [22 - Action Center](../22-action-center/README.md)

**Next**: [24 - PnL Tracker](../24-pnl-tracker/README.md)
