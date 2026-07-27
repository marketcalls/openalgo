# PlaceGTTOrder

Place a new GTT (Good Till Triggered) order — a price-trigger that sits with the broker until LTP crosses your level, then automatically places the underlying order. Useful for setting buy/sell levels without watching the screen.

## SINGLE vs OCO — Pick One

| Type | Use when… | Triggers | Orders fired |
|------|-----------|----------|--------------|
| **SINGLE** | You want **one** entry or exit at a level. Example: *"Buy IDEA if it dips to 9.55"* or *"Sell RELIANCE if it crosses 1450"*. | 1 | 1 |
| **OCO** (One-Cancels-Other) | You're already in a position and want **both a stoploss and a target**, whichever hits first. Example: *"I'm short INFY @ 1550. Stop me out at 1480, take profit at 1620."* | 2 | 1 of 2 (the other is auto-cancelled) |

> **In SINGLE there is no second leg and no automatic cancel** — once your one trigger fires and the order is placed, the GTT is finished.

## How to Choose `triggerprice_sl` vs `triggerprice_tg` (SINGLE only)

For SINGLE, exactly **one** of these two fields is your trigger price; set the other to `0`. Pick based on **where your trigger sits relative to LTP** — this also matches the leg name the broker assigns internally:

| Field | Trigger sits… | Typical intent |
|-------|---------------|----------------|
| `triggerprice_sl` | **below** current LTP | SELL stop-loss · BUY-on-dip · BUY-the-fall |
| `triggerprice_tg` | **above** current LTP | BUY breakout · SELL-at-target · SELL-the-rise |

For OCO, you always send **both**: `triggerprice_sl` (the lower trigger, your stoploss) **and** `triggerprice_tg` (the higher trigger, your target).

> **Note on naming.** In **SINGLE**, `triggerprice_sl` / `triggerprice_tg` are just *the trigger price* — the generic "price at which the order is triggered". The `_sl` / `_tg` suffix is only a directional hint (sits below / above LTP); SINGLE has no stoploss leg.
> In **OCO**, the suffix becomes a real role: `triggerprice_sl` is the **stoploss-leg trigger** and `triggerprice_tg` is the **target-leg trigger**.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/placegttorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/placegttorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/placegttorder
```

## Sample API Request — SINGLE: "Buy IDEA if it dips to 9.55, place a LIMIT order at 9.50"

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_type": "SINGLE",
  "exchange": "NSE",
  "symbol": "IDEA",
  "action": "BUY",
  "product": "CNC",
  "quantity": 1,
  "pricetype": "LIMIT",
  "price": 9.50,
  "triggerprice_sl": 9.55,
  "triggerprice_tg": 0,
  "stoploss": null,
  "target": null
}
```

LTP is currently above 9.55 → trigger sits **below** LTP → use `triggerprice_sl`.

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/placegttorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_type": "SINGLE",
  "exchange": "NSE",
  "symbol": "IDEA",
  "action": "BUY",
  "product": "CNC",
  "quantity": 1,
  "pricetype": "LIMIT",
  "price": 9.50,
  "triggerprice_sl": 9.55,
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

## Sample API Request — SINGLE: "Buy RELIANCE at MARKET if it breaks above 1450"

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_type": "SINGLE",
  "exchange": "NSE",
  "symbol": "RELIANCE",
  "action": "BUY",
  "product": "CNC",
  "quantity": 1,
  "pricetype": "MARKET",
  "price": 0,
  "triggerprice_sl": 0,
  "triggerprice_tg": 1450,
  "stoploss": null,
  "target": null
}
```

LTP is currently below 1450 → trigger sits **above** LTP → use `triggerprice_tg`. `price=0` because pricetype is MARKET.

## Sample API Request — OCO: "Bracket my INFY short — stop at 1480 / take profit at 1620"

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Bracket OCO",
  "trigger_type": "OCO",
  "exchange": "NSE",
  "symbol": "INFY",
  "action": "SELL",
  "product": "CNC",
  "quantity": 5,
  "pricetype": "LIMIT",
  "price": 0,
  "triggerprice_sl": 1480,
  "stoploss": 1478,
  "triggerprice_tg": 1620,
  "target": 1622
}
```

`price=0` because OCO uses per-leg limit prices: `stoploss` (the SL leg's limit) and `target` (the target leg's limit).

## Sample API Response (OCO)

```json
{
  "status": "success",
  "trigger_id": "23132604291213"
}
```

## Parameters Description

| Parameters | Description | Mandatory/Optional | Default Value |
|------------|-------------|--------------------|---------------|
| apikey | OpenAlgo API key (string) | Mandatory | - |
| strategy | Strategy identifier (string, used as broker correlation id where supported) | Mandatory | - |
| trigger_type | `SINGLE` or `OCO` (string) | Mandatory | - |
| exchange | NSE, BSE, NFO, BFO, CDS, BCD, MCX (string) | Mandatory | - |
| symbol | Trading symbol in OpenAlgo format (string) | Mandatory | - |
| action | `BUY` or `SELL` (string). For OCO, applies to both legs. | Mandatory | - |
| product | `CNC` (equity delivery) or `NRML` (F&O overnight). MIS is **not** supported — GTTs can sit for days. (string) | Mandatory | - |
| quantity | Order quantity. Integer for equity/F&O; fractional float allowed for crypto (number). | Mandatory | - |
| pricetype | `LIMIT` or `MARKET` (string) | Optional | `LIMIT` |
| price | **SINGLE only** — limit price of the child order. Send `0` when `pricetype=MARKET`. Ignored for OCO. (float) | Mandatory | - |
| triggerprice_sl | Trigger price below LTP. **SINGLE**: use this OR `triggerprice_tg`. **OCO**: required (the stoploss-leg trigger). (float) | Conditional | `0` |
| triggerprice_tg | Trigger price above LTP. **SINGLE**: use this OR `triggerprice_sl`. **OCO**: required (the target-leg trigger). (float) | Conditional | `0` |
| stoploss | **OCO only** — limit price for the stoploss leg's child order. Ignored for SINGLE. (float, `null`, or `""`) | Conditional | `null` |
| target | **OCO only** — limit price for the target leg's child order. Ignored for SINGLE. (float, `null`, or `""`) | Conditional | `null` |

### Trigger Field Rules

| trigger_type | What you must send | Constraint |
|--------------|--------------------|------------|
| `SINGLE` | exactly one of `triggerprice_sl` / `triggerprice_tg` (>0); the other = `0` | `price` is the child order's limit; send `0` for MARKET. |
| `OCO` | all four: `triggerprice_sl`, `stoploss`, `triggerprice_tg`, `target` (all >0) | `triggerprice_sl < triggerprice_tg`. Both legs share `action`, `quantity`, `product`. |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `"success"` or `"error"` |
| trigger_id | string | Unique trigger ID from broker (on success) — save this to modify or cancel later. |
| message | string | Error message (on error) |

## Notes

- Numeric fields (`quantity`, `price`, `triggerprice_sl`, `triggerprice_tg`, `stoploss`, `target`) are JSON floats. Empty strings (`""`) for `stoploss`/`target`/`triggerprice_sl`/`triggerprice_tg` are also accepted and coerced to `null`/`0`.
- **`last_price` is fetched server-side** from the broker's quotes endpoint. You don't need to send it.
- **MARKET handling**: some brokers' GTT APIs only accept LIMIT child orders. When that's the case, OpenAlgo automatically converts a MARKET request into a Market-Price-Protected LIMIT (a slab-based buffer around LTP for SINGLE, or around each leg's trigger for OCO) so the submitted `pricetype=MARKET` works uniformly across brokers.
- **OCO direction**: stoploss-leg trigger must be **below** target-leg trigger (`triggerprice_sl < triggerprice_tg`). The `action` (BUY or SELL) applies to both legs.
- **Symbol format**:
  - Equity: `RELIANCE`
  - Futures: `NIFTY30JAN25FUT`
  - Options: `NIFTY30JAN2525000CE`

## Error Scenarios

| Error | Cause |
|-------|-------|
| `triggerprice_sl: SINGLE GTT requires a positive triggerprice_sl or triggerprice_tg` | SINGLE without any trigger price |
| `triggerprice_sl: Stoploss trigger must be less than target trigger` | OCO with `triggerprice_sl >= triggerprice_tg` |
| `triggerprice_sl/stoploss/triggerprice_tg/target: Required for OCO` | OCO missing one of the four required fields |
| `Quantity must be a positive number` | quantity ≤ 0 |
| `GTT supports only CNC (delivery) or NRML (overnight F&O); MIS is intraday-only.` | `product=MIS` submitted |
| `Fractional quantity is not allowed for non-crypto exchanges` | Non-integer qty on equity/F&O |
| `GTT orders are not supported for broker 'X' yet` (501) | Broker doesn't ship a `gtt_api` module |
| `Sandbox GTT support not yet implemented` (501) | Analyzer mode is enabled |

---

**Back to**: [API Documentation](../README.md)
