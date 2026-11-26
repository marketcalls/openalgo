# Slack Notify

Post a message to the Slack channel whose incoming webhook is saved on the
`/slack` page.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/slack/notify
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/slack/notify
Custom Domain:  POST https://<your-custom-domain>/api/v1/slack/notify
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "message": "*NIFTY breakout* above 24,200",
  "wait_for_delivery": false
}
```

The API key may also be sent in the `X-API-KEY` header. It is not accepted in
the query string, where proxies and access logs keep it.

## Request Fields

| Field | Required | Description |
|-------|----------|-------------|
| `apikey` | Yes | OpenAlgo API key (or the `X-API-KEY` header). |
| `message` | Yes | The text to post, at most 4000 characters. Slack bold (`*text*`) works; `&`, `<` and `>` are escaped, so mentions and link markup are shown as text. |
| `wait_for_delivery` | No | `false` (default) queues the message and returns at once. `true` posts it first and reports whether Slack accepted it. |

## Sample API Responses

Queued (default):

```json
{
  "status": "success",
  "message": "Notification queued."
}
```

Delivered (`"wait_for_delivery": true`):

```json
{
  "status": "success",
  "message": "Message sent to Slack."
}
```

## Errors

| HTTP | When | Message |
|------|------|---------|
| 400 | Missing or empty `message`, `message` too long, `wait_for_delivery` not true or false, or the body is not a JSON object. | Names the field. |
| 401 | Missing or invalid API key. | `Invalid or missing API key` |
| 409 | Slack alerts are switched off on `/alerts`. | `Slack alerts are turned off. Turn them on from the Alerts page in OpenAlgo.` |
| 409 | No Slack webhook is saved. | `No Slack webhook is saved. Add one on the Slack page in OpenAlgo.` |
| 502 | With `wait_for_delivery`, Slack refused the message or could not be reached. | Says why and what to do, for example that the webhook was deleted and a new one should be saved. |
| 503 | Too many messages are already waiting to be sent. | `Too many Slack messages are waiting to be sent. Try again shortly.` |

## Rate Limit

30 requests per minute, which is about what Slack itself accepts on one
webhook. A failed post is not retried.

## Notes

- Only the channel switch at `/alerts` applies to this endpoint. The event
  groups chosen there apply to automatic order alerts, not to messages sent
  here.
- To change the channel, create a new webhook in Slack and save it on the
  `/slack` page. The old URL is replaced.
