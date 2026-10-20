# Strategy Orders

Every order the engine placed across a strategy's runs, optionally narrowed to one run.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/orders
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/orders
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/orders
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/strategy/orders \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "run_id": 42
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "id": 318,
      "run_id": 42,
      "leg_id": 1,
      "kind": "entry",
      "position_ref": "969bc536b1c14d15992f730c2c136d7a",
      "broker_order_id": "26083004118201",
      "symbol": "NIFTY04SEP2624500CE",
      "exchange": "NFO",
      "action": "SELL",
      "qty": 75,
      "product": "NRML",
      "pricetype": "MARKET",
      "price": 0.0,
      "trigger_price": 0.0,
      "status": "complete",
      "placed_at": "2026-08-30T03:50:11.610224+00:00",
      "filled_at": "2026-08-30T03:50:12.004881+00:00",
      "avg_fill_price": 142.35,
      "filled_qty": 75,
      "reject_reason": null
    },
    {
      "id": 322,
      "run_id": 42,
      "leg_id": 1,
      "kind": "exit_sl",
      "position_ref": "969bc536b1c14d15992f730c2c136d7a",
      "broker_order_id": "26083006214088",
      "symbol": "NIFTY04SEP2624500CE",
      "exchange": "NFO",
      "action": "BUY",
      "qty": 75,
      "product": "NRML",
      "pricetype": "MARKET",
      "price": 0.0,
      "trigger_price": 0.0,
      "status": "complete",
      "placed_at": "2026-08-30T06:21:40.118409+00:00",
      "filled_at": "2026-08-30T06:21:40.552117+00:00",
      "avg_fill_price": 172.80,
      "filled_qty": 75,
      "reject_reason": null
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |
| run_id | Narrow the result to one run, a positive integer | Optional | null (every run) |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Order objects, oldest first by placement time |

Each object in `data`:

| Field | Type | Description |
|-------|------|-------------|
| id | integer | The strategy order row's id |
| run_id | integer | Run the order belongs to |
| leg_id | integer | Leg within the strategy |
| kind | string | Why the order was placed |
| position_ref | string or null | Durable owner identity. A signal flip can keep an outgoing owner under `superseded` while the replacement owner is live; fills and exits settle the exact reference they name |
| broker_order_id | string or null | Order reference: the broker's id on a live run, the sandbox engine's id on a sandbox run, `null` before the order path answered |
| symbol | string | OpenAlgo symbol |
| exchange | string | Exchange code |
| action | string | `BUY` or `SELL` |
| qty | integer | Quantity sent |
| product | string or null | The product actually sent, which is not always the one the strategy carries: it is translated to the venue, so a CNC strategy sends NRML for an option leg. Null on orders placed before the column existed |
| pricetype | string | `MARKET`. Neither the strategy nor a leg carries a price, so a LIMIT, SL or SL-M order would go out priced at zero; exits are MARKET on every path regardless |
| price | number | Order price, `0` for a market order |
| trigger_price | number | Trigger price, `0` when unused |
| status | string | `pending`, `open`, `complete`, `cancelled` or `rejected` |
| placed_at | string | ISO 8601 UTC, written before the broker answered |
| filled_at | string or null | ISO 8601 UTC, set when the status first becomes `complete` |
| avg_fill_price | number or null | Average fill price reported by the broker |
| filled_qty | integer or null | Quantity actually filled |
| reject_reason | string or null | Broker or engine rejection text |

### Order kinds

`entry`, `exit_sl`, `exit_target`, `exit_trail`, `exit_overall_sl`, `exit_overall_target`, `exit_lock_profit`, `exit_eod`, `exit_expiry`, `exit_daily_loss_limit`, `exit_close_all`, `exit_leg_manual`, `exit_recovery`, `exit_signal`

## Notes

- Rows are ordered by placement time, **oldest first**, so an entry always precedes its exit in the list. This is the opposite ordering to [`/runs`](./runs.md) and [`/events`](./events.md).
- **A `run_id` belonging to another strategy matches nothing** rather than leaking its orders. The store joins through this strategy's runs, so the filter cannot be used to read across strategies.
- The row is written **before** the broker answers, so an order can appear here with `status: "pending"` and a `null` `broker_order_id`. That is deliberate: an order that reached the broker but was never recorded would be invisible to crash recovery.
- A positive `filled_qty` proves exposure in every status, including `open`,
  `cancelled` and `rejected`; a working order may partially fill before its
  terminal update. Only `complete` may fall back to the requested `qty` when a
  broker omitted `filled_qty`. Missing or unusable `avg_fill_price` means the
  exposure is real but its valuation is unavailable, not zero.
- `position_ref` is the ownership key for entry, exits, fills and recovery. At
  most a live and one outgoing `superseded` owner can be represented by a leg.
  Proven additional owners leave the run database-open and reserved for manual
  reconciliation rather than being declared flat.
- These rows are the engine's record of what it **asked for**. For money, the broker is the authority. The `/strategy` Detail page in the browser reads the broker's own orderbook and uses these rows only to decide which of the broker's rows belong to this strategy.
- There is no `limit` on this endpoint. Narrow with `run_id` when a strategy has a long history.
- Sandbox orders are placed against the sandbox engine and never reach a broker. Their `broker_order_id` is the sandbox engine's own reference, so it is not resolvable at the broker.

## Use Cases

- **Audit**: reconstruct exactly what a run sent and when
- **Fill analysis**: compare `avg_fill_price` against the intended entry
- **Failure triage**: filter for `status: "rejected"` and read `reject_reason`

---

**Back to**: [API Documentation](../README.md)
