# ModifyGTTOrder

Modify an active GTT trigger. The body is a **full replacement** of the trigger spec — same shape as `PlaceGTTOrder` plus `trigger_id`. The broker's underlying PUT replaces trigger prices, leg limits, and order params atomically.

> **Send everything you want to keep.** Modify is not a patch — fields you omit are not preserved.

## SINGLE vs OCO — Same Trigger Type as Original

You can modify any of the price levels, the quantity, or the pricetype, but you **cannot switch a SINGLE into an OCO** (or vice versa). If you need that, cancel and re-place.

| Type | Use when… | Triggers | Orders fired |
|------|-----------|----------|--------------|
| **SINGLE** | You set up one entry/exit at a level. | 1 | 1 |
| **OCO** (One-Cancels-Other) | You set up a stoploss + target bracket. | 2 | 1 of 2 (the other is auto-cancelled) |

> In SINGLE there is no second leg and no automatic cancel — once your one trigger fires and the order is placed, the GTT is finished.

## How to Choose `triggerprice_sl` vs `triggerprice_tg` (SINGLE only)

For SINGLE, exactly **one** of these two fields is your trigger price; set the other to `0`. Pick based on **where your trigger sits relative to LTP**:

| Field | Trigger sits… | Typical intent |
|-------|---------------|----------------|
| `triggerprice_sl` | **below** current LTP | SELL stop-loss · BUY-on-dip · BUY-the-fall |
| `triggerprice_tg` | **above** current LTP | BUY breakout · SELL-at-target · SELL-the-rise |

For OCO, you always send **both**: `triggerprice_sl` (the lower trigger, your stoploss) **and** `triggerprice_tg` (the higher trigger, your target).

> **Note on naming.** In **SINGLE**, `triggerprice_sl` / `triggerprice_tg` are just *the trigger price* — the generic "price at which the order is triggered". The `_sl` / `_tg` suffix is only a directional hint (sits below / above LTP); SINGLE has no stoploss leg.
> In **OCO**, the suffix becomes a real role: `triggerprice_sl` is the **stoploss-leg trigger** and `triggerprice_tg` is the **target-leg trigger**.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/modifygttorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/modifygttorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/modifygttorder
```

## Sample API Request — SINGLE: "Move my IDEA dip-buy from 9.55 → 9.65, raise limit to 9.60"

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_id": "23132604291205",
  "trigger_type": "SINGLE",
  "exchange": "NSE",
  "symbol": "IDEA",
  "action": "BUY",
  "product": "CNC",
  "quantity": 1,
  "pricetype": "LIMIT",
  "price": 9.60,
  "triggerprice_sl": 9.65,
  "triggerprice_tg": 0,
  "stoploss": null,
  "target": null
}
```

LTP is currently above 9.65 → trigger sits **below** LTP → use `triggerprice_sl`.

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/modifygttorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_id": "23132604291205",
  "trigger_type": "SINGLE",
  "exchange": "NSE",
  "symbol": "IDEA",
  "action": "BUY",
  "product": "CNC",
  "quantity": 1,
  "pricetype": "LIMIT",
  "price": 9.60,
  "triggerprice_sl": 9.65,
  "triggerprice_tg": 0,
  "stoploss": null,
  "target": null
}'
```

## Sample API Response

```json
{
  "status": "success",
  "trigger_id": "23132604291205"
}
```

## Sample API Request — OCO: "Tighten my INFY bracket — stop 1480→1485, target 1620→1625"

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Bracket OCO",
  "trigger_id": "23132604291213",
  "trigger_type": "OCO",
  "exchange": "NSE",
  "symbol": "INFY",
  "action": "SELL",
  "product": "CNC",
  "quantity": 5,
  "pricetype": "LIMIT",
  "price": 0,
  "triggerprice_sl": 1485,
  "stoploss": 1483,
  "triggerprice_tg": 1625,
  "target": 1627
}
```

`price=0` because OCO uses per-leg limit prices: `stoploss` (the SL leg's limit) and `target` (the target leg's limit).

## Parameters Description

| Parameters | Description | Mandatory/Optional | Default Value |
|------------|-------------|--------------------|---------------|
| apikey | OpenAlgo API key (string) | Mandatory | - |
| strategy | Strategy identifier (string) | Mandatory | - |
| trigger_id | The trigger ID returned by `PlaceGTTOrder` — identifies which active GTT to modify (string) | Mandatory | - |
| trigger_type | `SINGLE` or `OCO` — must match the original trigger's type (string) | Mandatory | - |
| exchange | NSE, BSE, NFO, BFO, CDS, BCD, MCX (string) | Mandatory | - |
| symbol | Trading symbol in OpenAlgo format (string) | Mandatory | - |
| action | `BUY` or `SELL` (string). For OCO, applies to both legs. | Mandatory | - |
| product | `CNC` (equity delivery) or `NRML` (F&O overnight). MIS is **not** supported for GTT. (string) | Mandatory | - |
| quantity | New order quantity. Integer for equity/F&O; fractional float allowed for crypto (number). | Mandatory | - |
| pricetype | `LIMIT` or `MARKET` (string) | Optional | `LIMIT` |
| price | **SINGLE only** — new limit price of the child order. Send `0` when `pricetype=MARKET`. Ignored for OCO. (float) | Mandatory | - |
| triggerprice_sl | New trigger price below LTP. **SINGLE**: use this OR `triggerprice_tg`. **OCO**: required (the stoploss-leg trigger). (float) | Conditional | `0` |
| triggerprice_tg | New trigger price above LTP. **SINGLE**: use this OR `triggerprice_sl`. **OCO**: required (the target-leg trigger). (float) | Conditional | `0` |
| stoploss | **OCO only** — new limit price for the stoploss leg's child order. Ignored for SINGLE. (float, `null`, or `""`) | Conditional | `null` |
| target | **OCO only** — new limit price for the target leg's child order. Ignored for SINGLE. (float, `null`, or `""`) | Conditional | `null` |

### Trigger Field Rules

| trigger_type | What you must send | Constraint |
|--------------|--------------------|------------|
| `SINGLE` | exactly one of `triggerprice_sl` / `triggerprice_tg` (>0); the other = `0` | `price` is the child order's limit; send `0` for MARKET. |
| `OCO` | all four: `triggerprice_sl`, `stoploss`, `triggerprice_tg`, `target` (all >0) | `triggerprice_sl < triggerprice_tg`. Both legs share `action`, `quantity`, `product`. |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `"success"` or `"error"` |
| trigger_id | string | Modified trigger ID (same value you sent) |
| message | string | Error message (on failure) |

## What Can Be Modified?

| Parameter | Modifiable | Notes |
|-----------|------------|-------|
| Trigger prices (`triggerprice_sl` / `triggerprice_tg`) | Yes | For OCO, both legs swap atomically. |
| Limit prices (`price` / `stoploss` / `target`) | Yes | |
| `quantity` | Yes | Must be a valid lot size for F&O. |
| `pricetype` | Yes | `LIMIT` ↔ `MARKET` (see broker-specific notes below). |
| `trigger_type` | No | Cannot switch SINGLE ↔ OCO — cancel and re-place. |
| `symbol` / `exchange` | No | Cannot change instrument. |
| `action` | No | Cannot change BUY ↔ SELL. |

## Notes

- Numeric fields (`quantity`, `price`, `triggerprice_sl`, `triggerprice_tg`, `stoploss`, `target`) are JSON floats. Empty strings (`""`) for `stoploss`/`target`/`triggerprice_sl`/`triggerprice_tg` are also accepted and coerced to `null`/`0`.
- **Modify is a full replacement** — every field on the trigger is replaced. Always send all fields you want to keep, not just the diff.
- **Only active GTTs can be modified.** Triggered, cancelled, or expired GTTs are immutable.
- **`last_price` is fetched server-side** from the broker's quotes endpoint. You don't need to send it.
- **OCO modify atomicity**: OpenAlgo aims to update both legs of an OCO atomically; some brokers expose a per-leg modify under the hood and may, in rare failure cases, leave the OCO in a half-modified state — re-issue the modify or cancel and re-place if the response indicates partial failure.
- **MARKET handling**: same auto-conversion behaviour as [PlaceGTTOrder](./placegttorder.md#notes) — broker-specific quirks are absorbed in the broker layer.
- **Semi-auto mode** blocks GTT modify (parity with `ModifyOrder`) — switch to Auto mode if you see a 403.

## Error Scenarios

| Error | Cause |
|-------|-------|
| `trigger_id is required` (400) | Missing `trigger_id` |
| `Modify GTT order is not allowed in Semi-Auto mode` (403) | User in Semi-Auto mode |
| `triggerprice_sl: Stoploss trigger must be less than target trigger` | OCO with `triggerprice_sl >= triggerprice_tg` |
| `GTT supports only CNC (delivery) or NRML (overnight F&O); MIS is intraday-only.` | `product=MIS` submitted |
| `Failed to fetch last_price from broker quotes` (502) | Broker quotes endpoint unavailable |
| `Sandbox GTT support not yet implemented` (501) | Analyzer mode is enabled |
| `GTT orders are not supported for broker 'X' yet` (501) | Broker capability gate |

---

**Back to**: [API Documentation](../README.md)
