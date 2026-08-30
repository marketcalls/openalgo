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
      "symbol": "NIFTY04SEP2624500CE",
      "broker_order_id": "26083004118201",
      "error": null
    },
    {
      "leg_id": 2,
      "ok": true,
      "symbol": "NIFTY04SEP2624500PE",
      "broker_order_id": "26083004118244",
      "error": null
    }
  ]
}
```

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
- A run whose entry orders were **all** rejected is closed immediately and the call answers 400 with `Every entry order was rejected`: a running strategy holding nothing would be worse than none.
- Partial success is a 200. Check `legs[].ok` rather than assuming every leg is in the market.
- Long legs are placed before short legs. On a spread, a short leg alone can be refused for margin the account would have had once the long leg existed.
- This endpoint is for `batch` strategies. A `signal` strategy has no start: its first inbound signal of the day opens the run. See the [webhook page](./webhook.md).

## Use Cases

- **Scheduled activation** from an external scheduler that does not use the built-in one
- **Paper testing**: run the same strategy in `sandbox` before enabling live
- **Manual override** from a script, an SDK or an MCP client without opening the browser

---

**Back to**: [API Documentation](../README.md)
