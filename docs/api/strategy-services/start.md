# Strategy Start

Start a run of a batch strategy in the mode the caller asks for. Every leg's entry order is placed.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/start
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/start
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/start
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "mode": "sandbox"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/strategy/start \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "mode": "sandbox"
}'
```

## Sample API Response

```json
{
  "status": "success",
  "run_id": 42,
  "mode": "sandbox",
  "legs": [
    {
      "leg_id": 1,
      "ok": true,
      "acknowledged": true,
      "symbol": "NIFTY04SEP2624500CE",
      "broker_order_id": "26083004118201",
      "error": null
    },
    {
      "leg_id": 2,
      "ok": true,
      "acknowledged": true,
      "symbol": "NIFTY04SEP2624500PE",
      "broker_order_id": "26083004118244",
      "error": null
    }
  ]
}
```

## Sample API Response (Broker Accepted, Acknowledgement Not Recorded)

```json
{
  "status": "success",
  "run_id": 42,
  "mode": "live",
  "legs": [
    {
      "leg_id": 1,
      "ok": true,
      "acknowledged": false,
      "symbol": "NIFTY04SEP2624500CE",
      "broker_order_id": "26083004118201",
      "error": null
    }
  ]
}
```

This is a real broker order, not a rejection. The durable pending intent still
exists and structured `order_ack_unrecorded` metadata carries the exact broker,
row, run and leg linkage. The dispatch call immediately binds only that pending
row. A bounded shared open-run sweep retries the repair and broker-polls a
still-working acknowledgement when no held frame remains; a missing or
conflicting link remains open and reserved instead of retrying the entry or
claiming flatness.

## Sample API Request (Live)

A live start is refused unless the operator has enabled live trading on this strategy.

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "mode": "live"
}
```

## Sample API Response (Live Not Enabled)

```json
{
  "status": "error",
  "message": "This strategy is not enabled for live trading. Enable it on the strategy page, or start it with mode 'sandbox'."
}
```

HTTP 409.

## Sample API Response (Mode Omitted)

```json
{
  "status": "error",
  "message": {
    "mode": ["Missing data for required field."]
  }
}
```

HTTP 400. Nothing was started and no order was placed.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |
| mode | `live` or `sandbox`. Exact and case-sensitive | Mandatory | **None. There is no default** |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| run_id | integer | The run that was opened |
| mode | string | The mode the run was started in, echoed back |
| legs | array | Per-leg placement outcome |

Each object in `legs`:

| Field | Type | Description |
|-------|------|-------------|
| leg_id | integer | The leg's id within the strategy |
| ok | boolean | Whether the entry order was accepted |
| acknowledged | boolean, optional | Present after dispatch. Whether the broker id and status were durably written back. `false` with `ok: true` leaves structured exact-row metadata for automatic reconciliation; it is not a rejection. Absent when the durable intent itself could not be written and no broker call was made |
| symbol | string | The contract the leg resolved to |
| broker_order_id | string or null | Order reference: the broker's id on a live run, the sandbox engine's id on a sandbox run, `null` when the order was not accepted |
| error | string or null | Rejection reason when `ok` is false |

## Status Codes

| Code | Cause |
|---|---|
| 200 | A run was opened and at least one entry order was accepted |
| 400 | Schema validation failed, including a missing or invalid `mode`. Also returned when the engine refused the start as badly configured, for example a leg that could not be resolved |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found` |
| 409 | The strategy is already running, or `mode` is `live` on a strategy that has not opted into live trading |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **`mode` is required and is never defaulted.** A caller that omits it is refused with a 400 and the engine is never reached. The default a hurried reader would reach for is the one that places real orders, so there is no default at all.
- **The value is matched exactly.** `LIVE`, `Sandbox`, `paper` and `real` are all 400s. A near miss is never quietly read as sandbox.
- **Live is opt-in per strategy.** A strategy is created sandbox-only. Enable live trading on the strategy page at `/strategy` before asking for `mode: "live"`. This endpoint cannot enable it.
- **Starting is idempotent by conflict, not by silence.** A second start against a running strategy answers 409, so two triggers firing at the same instant cannot both place a full set of entries.
- A start through this API records `trigger_source: "manual"` on the run.
- A run whose entry orders were **all** rejected is closed immediately and the call answers 400: a running strategy holding nothing would be worse than none. The message carries the venue's own words, so `Every entry order was rejected: MIS orders cannot be placed after square-off time (15:15 IST). Trading resumes at 09:00 AM IST.` rather than the bare sentence. When the legs were refused for different reasons each is listed against the leg it belongs to.
- Partial success is a 200. Check `legs[].ok` rather than assuming every leg is in the market.
- **`ok: true, acknowledged: false` is a real broker order with incomplete
  database attribution.** The intent row was durable before dispatch and the
  acknowledgement write was retried, but its broker id/status still could not
  be saved. A structured critical `order_ack_unrecorded` event carries exact
  row/run/leg and broker facts for immediate and bounded periodic
  reconciliation. Conflicts remain managed and reserved rather than retrying
  the entry or asserting flatness.
- Long legs are placed before short legs. On a spread, a short leg alone can be refused for margin the account would have had once the long leg existed.
- This endpoint is for `batch` strategies, and enforces it. A `signal` strategy has no start: its first inbound signal after the platform session boundary opens the run, so a start against one answers 400 with `A signal strategy has no start. Its run opens on the first long_entry or short_entry signal after the session boundary.` and nothing is claimed or resolved. See the [webhook page](./webhook.md).

## Use Cases

- **Scheduled activation** from an external scheduler that does not use the built-in one
- **Paper testing**: run the same strategy in `sandbox` before enabling live
- **Manual override** from a script, an SDK or an MCP client without opening the browser

---

**Back to**: [API Documentation](../README.md)
