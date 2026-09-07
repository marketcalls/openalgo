# Strategy Webhook

Trigger a strategy from an external alert. The URL token identifies the strategy, so this endpoint takes no API key.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/strategy/webhook/<your_webhook_token>
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/strategy/webhook/<your_webhook_token>
Custom Domain:  POST https://<your-custom-domain>/strategy/webhook/<your_webhook_token>
```

This endpoint is **not** under `/api/v1`, and it does **not** accept an `apikey` field. The token in the path is the whole of the credential.

## The Token

- It is generated when the strategy is created and looks like `oaws_` followed by 43 URL-safe characters.
- **It is shown exactly once**, in the browser, when the strategy is created or when the token is rotated. Copy it then.
- Only its SHA-256 digest is stored. **No endpoint returns it**, and no response on this surface or the [API-key surface](./README.md) carries it. If you lose it, rotate it on the strategy page at `/strategy` and copy the new one.
- Treat it as a credential. Anyone who can post to the URL can start or stop the strategy, subject to the strategy's own kill switch, IP allowlist and live opt-in.
- Rotating invalidates the old token immediately.

Within OpenAlgo's enforceable boundary, the token is redacted from standard and JSON application logs, the traffic database and every shipped nginx access log. An application line carries only the first twelve characters of the stored digest, which is enough to correlate two events and useless to anyone who reads it. The inbound payload is redacted before it is stored, so a webhook URL pasted into an alert message does not end up in the database in plaintext. External senders and proxies are outside that boundary and must protect the URL as a credential.

## Batch Strategies

A batch strategy is a multi-leg spread entered and exited as a unit. It accepts `start` and `stop`, and nothing else.

### Sample API Request (Start)

```json
{
  "action": "start",
  "mode": "sandbox"
}
```

### Sample cURL Request (Start)

```bash
curl -X POST http://127.0.0.1:5000/strategy/webhook/oaws_your_webhook_token_here \
  -H 'Content-Type: application/json' \
  -d '{
  "action": "start",
  "mode": "sandbox"
}'
```

### Sample API Response (Start)

```json
{
  "status": "success",
  "result": "ok",
  "message": "Strategy start accepted",
  "strategy_id": 7,
  "run_id": 42
}
```

### Sample API Request (Stop)

```json
{
  "action": "stop"
}
```

### Sample cURL Request (Stop)

```bash
curl -X POST http://127.0.0.1:5000/strategy/webhook/oaws_your_webhook_token_here \
  -H 'Content-Type: application/json' \
  -d '{
  "action": "stop"
}'
```

### Sample API Response (Stop)

```json
{
  "status": "success",
  "result": "ok",
  "message": "Strategy stop accepted",
  "strategy_id": 7,
  "run_id": 42,
  "stop_pending": true,
  "exits": [
    {
      "leg_id": 1,
      "ok": true,
      "position_ref": "969bc536b1c14d15992f730c2c136d7a",
      "exit_owner": "live",
      "error": null
    }
  ]
}
```

`mode` is required on `start` and ignored on `stop`. A stop that carries a stray `mode` is not refused for it: the sender's extra field is not a reason to leave a position open.

`Strategy stop accepted` means the durable request was handed to the engine; it
does not mean the broker is flat. `stop_pending: true` keeps the run current,
subscribed and managed until exact exit fills confirm every owner is flat.

## Signal Strategies

A signal strategy moves one leg at a time. It accepts `long_entry`, `long_exit`, `short_entry` and `short_exit`, and nothing else. There is no `start` and no `mode`: the first signal after the platform session boundary opens the run, and the mode comes from the strategy's own live opt-in.

The leg is named either by `leg_id` or by `symbol`, optionally narrowed by `exchange`. `leg_id` wins when both are given.

### Sample API Request (By Leg Id)

```json
{
  "action": "long_entry",
  "leg_id": 1
}
```

### Sample API Request (By Symbol)

```json
{
  "action": "short_exit",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

### Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/strategy/webhook/oaws_your_webhook_token_here \
  -H 'Content-Type: application/json' \
  -d '{
  "action": "short_exit",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}'
```

### Sample API Response (Order Placed)

```json
{
  "status": "success",
  "result": "ok",
  "message": "Signal accepted",
  "strategy_id": 4,
  "run_id": 91
}
```

### Sample API Response (No-op)

```json
{
  "status": "success",
  "result": "ok",
  "message": "Signal accepted (already_long)",
  "strategy_id": 4,
  "run_id": 91
}
```

HTTP 200. The signal was understood and correctly did nothing.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| action | Batch: `start` or `stop`. Signal: `long_entry`, `long_exit`, `short_entry` or `short_exit`. Trimmed and lower-cased before matching | Mandatory | - |
| mode | `live` or `sandbox`. Batch `start` only. Trimmed and lower-cased before matching | Mandatory on `start`, ignored elsewhere | **None. There is no default** |
| leg_id | Which leg the signal targets. Signal strategies only | Optional | null |
| symbol | Leg symbol, used when `leg_id` is absent. Signal strategies only | Optional | null |
| exchange | Exchange for `symbol`. Signal strategies only | Optional | null |

The body must be a JSON object. A JSON array, a bare string and a number are all refused. Extra fields are ignored, and are redacted before the audit row is written if they look like a credential.

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `success` or `error` |
| result | string | The outcome label, always a member of the webhook result vocabulary. Absent on the declared-size 413 route preflight response |
| message | string | What happened, in words |
| strategy_id | integer | The strategy the token resolved to. Absent when the token resolved to nothing |
| run_id | integer | The run the signal opened or affected. Absent when there is none |
| stop_pending | boolean | Stop responses only. `true` means the durable stop still has exposure to fill, retry or reconcile; `false` means the stop confirmed flatness |
| exits | array | Stop responses only, present with `stop_pending`; per-owner exit outcomes including `position_ref`, `exit_owner`, `ok` and rejection context |

`status` and `result` answer different questions. A deduplicated retry has `status: "success"` because the caller's intent was already satisfied, and `result: "rejected_dedupe"` because the audit trail has to show that this particular delivery did nothing.

## Result Labels And Status Codes

| Result | HTTP | Cause |
|---|---|---|
| `ok` | 200 | The signal was accepted and handed to the engine. For a signal strategy this includes a no-op |
| `rejected_token` | 404 | The token is malformed, unknown, or has been rotated |
| `rejected_locked` | 403 | The strategy's webhook kill switch is engaged |
| `rejected_ip` | 403 | The caller's address is outside the strategy's IP allowlist |
| `rejected_payload` | 400 | The body is empty, is not valid UTF-8, is not valid JSON, is not a JSON object, or is larger than 16384 bytes |
| `rejected_invalid_action` | 400 | The action is not one this strategy's kind accepts, a `start` named no valid `mode`, or the signal engine refused the signal as a configuration mismatch |
| `rejected_live_disabled` | 403 | `mode: "live"` on a strategy that has not opted into live trading |
| `rejected_dedupe` | 200 | An identical signal was already handled within the last 60 seconds. Reported as a success |
| `rejected_cooling_off` | 409 | The strategy stopped within the last 30 seconds, so a `start` is held off |
| `rejected_engine_error` | 500 | The engine refused a batch `start` or `stop`, or raised anywhere. A signal-mode engine refusal is reported as `rejected_invalid_action` (400) instead; only a raised exception on the signal path answers 500 |
| `rate_limited` | 429 | The route's rate limiter refused the request |

Only requests admitted to the validation pipeline are audited. Every terminal
outcome inside that pipeline, accepted or rejected, writes a row to the webhook
audit table. The route's rate limiter and declared-size 413 run before durable
webhook-event audit, so those preflight refusals do not create an audit row.
The declared-size 413 response contains `status` and `message` but no `result`;
the limiter's 429 response contains `result: "rate_limited"`, a `retry_after` field and a `Retry-After` header.
The session endpoint can read admitted events, but the `/strategy` page does
not currently expose them. The page also does not provide an IP-allowlist
editor; creation currently stores no allowlist. Configure/read these through
the session API until those operator surfaces are built.

## Validation Order

The order is part of the contract. Before this list, the route applies its
caller/token rate limits and refuses a declared oversized body with 413 before
reading it. Those route preflight guards do not enter the pipeline and do not
write webhook audit rows. Once admitted, each terminal pipeline stage writes
its own audit row and stops the request.

1. The token resolves to a strategy, or `rejected_token`
2. The strategy is not locked, or `rejected_locked`
3. The caller is inside the IP allowlist, or `rejected_ip`
4. The body is a JSON object within the size cap, or `rejected_payload`
5. The action is one this strategy's kind accepts, or `rejected_invalid_action`
6. A batch `start` names a valid mode, or `rejected_invalid_action`
7. A live start is enabled for live, or `rejected_live_disabled`
8. It is not a retry of the last identical signal, or `rejected_dedupe`
9. The strategy is not cooling off, or `rejected_cooling_off`
10. The engine accepts it, or `rejected_engine_error`

The kill switch outranks the allowlist, and the allowlist outranks the payload, so a body from a blocked address is never even parsed. The live gate sits behind both action checks, so a malformed alert can never be the thing that reaches a broker. Signal-mode strategies branch out after stage 5: they have no mode to validate, no separate live gate, and no dedupe or cooling-off window.

## Notes

- **`mode` is required on a batch `start` and is never defaulted.** A start with no mode, or with `paper`, `real` or an empty string, is refused with `rejected_invalid_action` and never reaches the engine. Case and surrounding whitespace do not matter here: `"LIVE"` and `" Sandbox "` are read as `live` and `sandbox`. This is the one place the webhook is more forgiving than [`/start`](./start.md), where `LIVE` is a 400.
- **Live is opt-in per strategy.** A strategy is created sandbox-only. `mode: "live"` is refused with `rejected_live_disabled` until the operator enables live trading on the strategy page.
- **An unknown token and a malformed one are indistinguishable.** Same result label, same message, same status, so the endpoint is not an oracle for which tokens exist. A malformed token is refused on its shape before any database lookup, so the two are not separable by timing either.
- **A 404 here does not count towards an IP ban.** The endpoint answers with a controlled 404 rather than falling through to the application's handler, so a scanner walking the token space cannot get the address a real alert arrives from banned.
- **A signal that does nothing answers 200 with a note.** A repeat `long_entry` on a leg already long, or an exit for a position that is not held, is a no-op, not a failure. This is deliberate: reporting it as a failure invites a retry, and a retry on an order path is how one alert becomes two positions. The notes are `already_long`, `already_short`, `flip_pending`, `no_matching_position`, `outside_entry_window` and `outside_trading_window`, and they appear in the message as `Signal accepted (already_long)`. One further note, `run_stopping`, is not a no-op: a signal arriving while a durable stop is in flight is refused with `rejected_invalid_action` and the generic message `The signal was refused`.
- **Being refused is different from being a no-op.** A signal blocked by the strategy's `direction`, or by the leg's own accepted side, or naming a leg that does not exist, is a configuration mismatch the operator should see. So is a `short_entry` on a cash leg when the strategy's product is not `MIS`: cash cannot be carried short, so anything else would reach the venue as a naked short delivery. All of these answer `rejected_invalid_action` with the engine's own message, for example `This strategy is long_only; a short signal is not accepted`, `No leg matches this signal`, or `Leg 1: cash cannot be held short overnight, and product CNC carries the position. Use MIS for an intraday short.`
- **A signal leg names its instrument outright, and it is checked.** A signal leg is not resolved from an underlying and an expiry rank, so the symbol on the leg is the symbol sent to the broker. It is checked against the master contract on every venue, cash included: `NIFTY` on `NFO` is a base symbol rather than a contract, and a misspelled equity such as `RELAINCE` on `NSE` is refused the same way, both with `rejected_invalid_action`. If the master contract holds no rows at all for that exchange there is nothing to check against and the leg passes, so a fresh install is not blocked.
- **Each kind refuses the other's vocabulary.** `long_entry` against a batch strategy and `start` against a signal strategy are both `rejected_invalid_action`, and the message names the actions that strategy does accept.
- **Duplicate suppression, batch only.** Two identical `(strategy, action, mode)` deliveries inside 60 seconds are one signal. This exists because senders retry a delivery they believe failed. A delivery whose engine call then failed releases its claim, so a genuine retry is not swallowed as a duplicate of something that never happened.
- **Cooling off, batch `start` only.** A strategy that stopped within the last 30 seconds refuses a `start`, so a misconfigured pair of alerts firing against each other cannot oscillate and pay the spread each time. A stop is never blocked by the window. A stop against an already-stopped strategy does not arm it, and neither does a stop that is still pending.
- **The IP allowlist is a closed set when it is non-empty.** An empty or absent allowlist allows every address, which is how a strategy is created. Entries are CIDR ranges, and a bare address is read as its own `/32` or `/128`. A request that arrives with no address at all fails a non-empty allowlist. One malformed entry is skipped rather than failing the whole list closed.
- **Body size cap: 16384 bytes.** An oversized `Content-Length` is refused with a 413 **before the body is read or audited**, so an unauthenticated caller does not get to decide how much the worker reads. The admitted pipeline then applies its own byte cap to what actually arrived and audits that `rejected_payload` outcome. A TradingView alert is a few hundred bytes.
- **The caller is identified by the real client address.** The proxy headers are honoured through `get_real_ip()`, so the IP allowlist and the audit trail name the sender rather than the reverse proxy most installs run behind.
- **`action` and `mode` are trimmed and lower-cased** before matching, so `" START "` and `"Sandbox"` are accepted. Nothing else about the payload is normalised.
- **Audit rows for an unrecognised token are capped at the newest 1000.** They name no strategy, so nothing displays them and nothing deleted them: anyone who could reach the URL could otherwise grow the database without limit, invisibly. They are kept rather than dropped, because a run of them is the first sign of somebody walking the token space.
- The endpoint never raises. An unexpected failure anywhere is logged with a traceback and reported as `rejected_engine_error`.

## Rate Limits

The validation pipeline applies no rate limit of its own. The route in front of
it does, and `rate_limited` is the result label that outcome carries, answering
429 before the pipeline and therefore before durable webhook-event audit. The
platform's webhook budget is `WEBHOOK_RATE_LIMIT` in `.env`, which `.sample.env`
ships as `100 per minute` and which the other public webhook surfaces draw on.
See [rate limiting](../rate-limiting.md).

Two limits share that budget, because neither subsumes the other. **By caller address** is the only key that can stop someone walking the token space: every guess carries a different token, so a token-keyed limit would score each against an empty bucket and never fire. **By token** bounds what one leaked token can do to the broker account however many addresses replay it, which matters because the token is the whole credential.

The token-keyed limit is keyed on the token's SHA-256 digest, not the token. The limiter's in-memory storage empties the event list of an expired window but never removes the key, so a raw token there would sit in process memory for the life of the worker, one entry per token ever presented including every guess.

## Where The Token Must Not Appear

The URL token is the entire credential, so anywhere it is written down is a second copy of it.

- **It is masked in the traffic log.** `/traffic` keeps 30 days of requests and shows the path; the credential segment of `/strategy/webhook/`, `/flow/webhook/` and `/chartink/webhook/` paths is replaced with `<redacted>` before the row is written. Anyone who could read that log could otherwise replay the webhook and place orders.
- **It is masked in application logs.** The same path redactor runs over standard log messages and the request-path field in `log/errors.jsonl`.
- **It is suppressed in shipped nginx access logs.** Direct, Docker, multi-instance, update and change-domain installers conditionally disable access logging for all three URL-secret webhook prefixes, including the HTTP-to-HTTPS redirect server.
- **It never appears in an audit payload.** The stored `payload` is the body with anything token-shaped stripped, so a sender that echoes its own URL into the alert body does not persist it.
- **No API response carries it.** Only the SHA-256 digest is stored; the plaintext is shown once, at creation and at rotation, in the browser.

It will still be in your sender's own configuration and may be present in an external or previously installed/custom proxy that does not apply this guard. If credentials may previously have reached any access log or support bundle, rotate them from the strategy page (the session endpoint is `/strategy/api/strategies/<id>/webhook/rotate`); the old token stops working immediately. Apply equivalent redaction or access-log suppression at every external TLS terminator.

## Use Cases

- **TradingView alerts**: paste the webhook URL into an alert and send `{"action": "start", "mode": "sandbox"}` as the message
- **Signal-driven equity trading**: one alert per side per symbol, with the strategy holding several unrelated instruments
- **External schedulers**: start in the morning and stop at square-off from cron or any HTTP client
- **Paper validation**: run the same alerts against `mode: "sandbox"` until the strategy is enabled for live

---

**Back to**: [API Documentation](../README.md)
