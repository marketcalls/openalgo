# Discord Services

OpenAlgo posts alerts to a Discord channel through a Discord **webhook**.
There is no bot to run and no token to keep alive: a trader creates the
webhook in the channel's settings, pastes its URL on the `/discord` page, and
OpenAlgo posts to it.

Order alerts reach Discord automatically once the webhook is saved. Which
orders are sent (orders placed, modified, cancelled, positions closed, batch
orders, GTT orders) is chosen per channel on the `/alerts` page, alongside
Telegram, WhatsApp and Slack. An order that fails on its own is never sent as an alert. A basket, split or
options alert does list any of its orders that were rejected, since that is
part of what the batch did.

## Security model

The REST API at `/api/v1/discord/` exposes **exactly one** endpoint,
`POST /notify`, and it can only post a message. Saving, replacing or removing
the webhook, switching the channel on or off and choosing its event groups are
done on the session-authenticated `/discord` and `/alerts` pages.

- **The webhook URL is a credential.** Anybody holding it can post into the
  channel. OpenAlgo stores it encrypted with the same key as broker tokens,
  never returns it to the browser or the API, and redacts it from logs.
- **Only Discord webhooks are accepted:** `https://discord.com/api/webhooks/...`
  (also `discordapp.com`, `ptb.discord.com` and `canary.discord.com`, with an
  optional `?thread_id=` for forum threads). The host is matched exactly, so a
  request can only ever reach Discord, never this server's own network. The
  saved URL is checked again before every post, and redirects are not
  followed.
- **Nothing pings anybody.** Every message is posted with mentions disabled,
  so `@everyone`, `@here`, users and roles are shown as text. In an order
  alert every value is also escaped, so a symbol or a broker's message shows
  exactly as it was sent.

## REST endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| [Notify](./notify.md) | POST | Post a message to the saved Discord webhook. |
