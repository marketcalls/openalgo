# Slack Services

OpenAlgo posts alerts to a Slack channel through a Slack **incoming webhook**.
There is no bot to run and no token to keep alive: a trader creates the webhook
in Slack, pastes its URL on the `/slack` page, and OpenAlgo posts to it.

Order alerts reach Slack automatically once the webhook is saved. Which orders
are sent (orders placed, modified, cancelled, positions closed, batch orders,
GTT orders) is chosen per channel on the `/alerts` page, alongside Telegram,
WhatsApp and Discord. An order that fails on its own is never sent as an alert. A basket, split or
options alert does list any of its orders that were rejected, since that is
part of what the batch did.

## Security model

The REST API at `/api/v1/slack/` exposes **exactly one** endpoint,
`POST /notify`, and it can only post a message. Saving, replacing or removing
the webhook, switching the channel on or off and choosing its event groups are
done on the session-authenticated `/slack` and `/alerts` pages.

- **The webhook URL is a credential.** Anybody holding it can post into the
  channel. OpenAlgo stores it encrypted with the same key as broker tokens,
  never returns it to the browser or the API, and redacts it from logs.
- **Only Slack webhooks are accepted:** `https://hooks.slack.com/services/...`,
  with the host matched exactly. A request can therefore only ever reach
  Slack, never this server's own network. The saved URL is checked again
  before every post, and redirects are not followed.
- **Nothing can ping a channel.** Slack's control characters `&`, `<` and `>`
  are escaped in every alert and every API message, so `<!channel>`,
  `<!here>` and link markup are shown as text.

## REST endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| [Notify](./notify.md) | POST | Post a message to the saved Slack webhook. |
