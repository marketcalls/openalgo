# Alerts

OpenAlgo can tell you what your orders did on Telegram, WhatsApp, Slack and
Discord. The **Alerts** page (`/alerts`, in the profile menu) shows every
channel in one place:

- a card per channel with how it stands, an on/off switch, a test button and a
  link to the channel's own setup page;
- a grid choosing which orders each channel hears about.

## Event groups

| Group | Covers |
|-------|--------|
| Orders placed | New orders, and smart orders that found nothing to change |
| Orders modified | A change to the price or quantity of an open order |
| Orders cancelled | One order, or every open order at once |
| Positions closed | One position, or every open position |
| Basket, split and options orders | Orders sent together, with how many went through |
| GTT orders | GTT orders placed, modified, cancelled, triggered or expired |

An order that fails on its own is never sent as an alert, on any channel: a
script retrying a bad order would otherwise fill every chat with rejections.
A basket, split or options alert does list any of its orders that were
rejected, since that is part of what the batch did.

A GTT alert names the symbol, the trigger prices and the trigger id, and when
a GTT fires, the order it placed. (Telegram's GTT alerts still show only the
title and the time; WhatsApp, Slack and Discord show the details.)

Alerts in analyze (sandbox) mode are sent too, marked
`ANALYZE MODE - No Real Order`.

## Channels

| Channel | Set up on | How it sends | On by default |
|---------|-----------|--------------|---------------|
| Telegram | `/telegram` | The OpenAlgo Telegram bot, to linked accounts with notifications on, while the bot is running | Yes |
| WhatsApp | `/whatsapp` | The paired WhatsApp device, to its own number | Yes |
| Slack | `/slack` | A Slack incoming webhook | When its webhook is saved |
| Discord | `/discord` | A Discord channel webhook | When its webhook is saved |

An install that has never opened `/alerts` keeps exactly the Telegram and
WhatsApp alerts it had: both start on, with every event group.

### Slack

1. Open api.slack.com/apps and create an app for your workspace ("From scratch").
2. Open **Incoming Webhooks**, switch them on, and choose **Add New Webhook to Workspace**.
3. Pick the channel, allow it, and copy the webhook URL.
4. Paste it on the `/slack` page and save. Slack alerts switch on.

### Discord

1. Open the settings of the channel the alerts should go to (**Edit Channel**).
2. Open **Integrations**, then **Webhooks**, and choose **New Webhook**. You need the Manage Webhooks permission.
3. Choose **Copy Webhook URL**.
4. Paste it on the `/discord` page and save. Discord alerts switch on.

### Keeping a webhook safe

Anybody holding a webhook URL can post into that channel. OpenAlgo:

- accepts only the provider's own webhook URLs (`https://hooks.slack.com/services/...`,
  `https://discord.com/api/webhooks/...`), so a send can only ever reach Slack or Discord;
- stores the URL encrypted and never shows it again, on the page or through the API;
- keeps it out of its logs;
- never lets an alert ping a whole channel: Slack's `<!channel>` and Discord's
  `@everyone`, `@here`, user and role mentions are shown as text.

If you think a webhook URL has leaked, delete the webhook in Slack or Discord,
create a new one and save it on the channel's page.

## Sending from your own code

Each channel has one REST endpoint that posts a message. It needs your OpenAlgo
API key and the channel switched on at `/alerts`:

| Channel | Endpoint | Docs |
|---------|----------|------|
| Telegram | `POST /api/v1/telegram/notify` | [Telegram](api/telegram-services/README.md) |
| WhatsApp | `POST /api/v1/whatsapp/notify` | [WhatsApp](api/whatsapp-services/notify.md) |
| Slack | `POST /api/v1/slack/notify` | [Slack](api/slack-services/notify.md) |
| Discord | `POST /api/v1/discord/notify` | [Discord](api/discord-services/notify.md) |

All four are listed in the API Playground (`/playground`) for stock brokers.
The crypto broker collection does not list the messaging endpoints yet, but
they work the same way from any broker.

## Chart alerts on /trading

A price or indicator alert on the chart can also be sent to Telegram,
WhatsApp, Slack or Discord, chosen per alert under **When it fires**. These
are separate from the order alerts above: the chart posts to the channel's
notify endpoint itself, so the `/alerts` grid does not route them, but a
channel switched off on `/alerts` refuses them too. Every outward option is
off for a new alert, and alerts saved before Slack and Discord existed read
them as off.

## How it works (for maintainers)

Alerts are event driven end to end:

1. An order service publishes an order event on the event bus (`order.placed` and so on).
2. `subscribers/alert_subscriber.py` maps it to an event group
   (`services/alerts/categories.py`) and, when at least one channel receives
   that group, publishes one `alert.raised` event (`events/alert_events.py`).
3. One delivery callback on `alert.raised` asks `services/alerts/router.py`
   which channels in `services/alerts/registry.py` are on and receive the
   group (`services/alerts/settings.py`, stored in the `alert_channels`
   table), and hands the alert to each in its own `try`, so a failing channel
   never stops another. An order event costs the bus two alert callbacks,
   however many channels there are.
4. The channel queues the send and returns at once, so a slow provider never
   holds a bus worker. Telegram and WhatsApp go through their existing alert
   services and pools, whose own rules (bot running, device paired) still
   apply. Slack and Discord each post on their own bounded lane
   (`services/alerts/channels/webhook.py`), so one provider that stops
   answering never delays or drops the other's alerts. A queued post reads
   the saved webhook when it runs, so a webhook removed meanwhile is never
   posted to.

WhatsApp, Slack and Discord share one formatter (`services/alerts/formatting.py`);
Telegram keeps its own, so the messages its users receive are unchanged.

Settings changes to one channel are serialised, and each reads the stored row
rather than the cache, so two changes made at once both land and a failed
read never resets a channel to its defaults.

**Adding a channel** is a subclass of `AlertChannel` (or `WebhookChannel` for
one that posts to a URL) under `services/alerts/channels/`, plus one line in
`services/alerts/registry.py`. The subscriber, the `/alerts` API and the page
all read the registry. A webhook channel's encrypted column is already in the
key rotation lists (`utils/env_check._migrate_fernet_db`, `upgrade/rotate_pepper.py`).
