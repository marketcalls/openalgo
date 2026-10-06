# P&L Attribution

Split live positions or holdings by the strategy that owns them, and optionally return today's M2M for each position.

A broker nets positions per symbol and carries no strategy label, so two strategies trading one contract are indistinguishable in `/positionbook`. OpenAlgo's strategy book keeps a per-strategy leg for every order placed with a `strategy` name. This endpoint joins the two: each broker row is divided into per-strategy slices, and whatever the strategy book does not explain is returned as an `Unattributed` slice. The `/positionbook` and `/holdings` responses are not changed.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/pnl/attribution
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/pnl/attribution
Custom Domain:  POST https://<your-custom-domain>/api/v1/pnl/attribution
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "kind": "positions",
  "m2m": true
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/pnl/attribution \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "kind": "positions",
  "m2m": true
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "kind": "positions",
    "strategies": ["TrendFade"],
    "m2m_error": null,
    "rows": [
      {
        "symbol": "NIFTY06OCT2622550PE",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": -195.0,
        "average_price": 80.3,
        "slices": [
          {
            "strategy": "TrendFade",
            "quantity": -150.0,
            "average_price": 80.3,
            "today_realized_pnl": 0.0,
            "attributed": true
          },
          {
            "strategy": "Unattributed",
            "quantity": -45.0,
            "average_price": 80.3,
            "today_realized_pnl": 0.0,
            "attributed": false
          }
        ],
        "mismatch": false,
        "mismatch_reason": null,
        "leftover_owner": null,
        "m2m_available": true,
        "m2m_reason": null,
        "m2m_fixed": 15473.25,
        "m2m": 15336.75,
        "overnight_quantity": -195.0,
        "prev_close": 79.35,
        "pnl_equals_m2m": false
      }
    ]
  }
}
```

The example is a short of 195 carried from the previous day, still open at an LTP of 0.7: `m2m_fixed` is 195 x 79.35 (the carried quantity valued at the previous close) and `m2m` adds 195 x -0.7 for the live mark.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| kind | `positions` or `holdings` | Mandatory | - |
| m2m | Also return today's M2M for each position (positions only) | Optional | false |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data.kind | string | Echo of the request |
| data.strategies | array | Strategy names that own part of any row, sorted (excludes `Unattributed`) |
| data.m2m_error | string or null | Set when M2M was requested but today's trades or the previous closes could not be fetched |
| data.rows | array | One entry per broker row, in the broker's order |

### Row Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol, exchange, product | string | The broker row. For holdings, `quantity` also includes T1 and pledged quantity where the broker reports them |
| quantity | number | The broker's net quantity |
| average_price | number | The broker's average price |
| slices | array | Per-strategy shares of the row (see below). Their quantities never add up to more than the broker holds |
| mismatch | boolean | The strategy book disagrees with the broker: a leg on the opposite side, legs larger than the broker quantity, or a row the broker shows flat while the book still shows an open leg |
| mismatch_reason | string or null | Why `mismatch` is set |
| leftover_owner | string or null | For a row the broker shows flat: the one strategy with activity on the contract, which owns whatever realized P&L the slices do not explain. Null when none, or when more than one strategy is involved |
| m2m_available | boolean | With `m2m`: whether M2M could be worked out for this row |
| m2m_reason | string or null | Why not |
| m2m_fixed | number or null | M2M excluding the live price: `m2m = m2m_fixed + quantity x LTP`. Null whenever `m2m_available` is false, including when `m2m_error` is set |
| m2m | number or null | Today's M2M at the row's LTP. Null when `m2m_available` is false |
| overnight_quantity | number or null | Quantity carried in from a previous day. Null when M2M could not be computed because today's trades or the previous closes could not be fetched |
| prev_close | number or null | The previous close used |
| pnl_equals_m2m | boolean | The broker's own P&L on this carried row is already the day's M2M (Kotak values a carried leg at the previous settlement) |

### Slice Fields

| Field | Type | Description |
|-------|------|-------------|
| strategy | string | Strategy name, or `Unattributed` |
| quantity | number | This strategy's quantity. Zero for a strategy that closed out today and only carries its realized P&L |
| average_price | number | This strategy's average price. For `Unattributed`, backed out so the slices add up to the broker's cost |
| today_realized_pnl | number | P&L this strategy realized today on the contract |
| attributed | boolean | False for `Unattributed` |

## M2M

M2M is today's move only. A position opened today is measured from its fills; a position carried from a previous day is measured from the previous close:

```
m2m = (sell value - buy value, today's fills)
      + end quantity x LTP
      - overnight quantity x previous close
```

It is computed from today's tradebook and the quote's `prev_close`, so it works for any broker that provides both. It is returned only for NSE, BSE, NFO and BFO rows. `m2m_available` is false, with a reason in `m2m_reason`, rather than the figure being guessed, when: the exchange is not one of those; a carried position has no previous close; an open position has no live price; or one of the row's fills has no usable price or quantity, or a fill names no symbol, exchange or product and so cannot be placed. When today's trades or the previous closes cannot be fetched at all, every row is unavailable, `data.m2m_error` says why, and the M2M fields are null.

## Errors

| Status | Meaning |
|--------|---------|
| 400 | Invalid request body |
| 403 | Invalid API key |
| 503 | The strategy book could not be read. This is never reported as "everything unattributed" |

## Notes

- Matching: positions match on symbol, exchange and product; holdings match on symbol and exchange with legs in the CNC product.
- Strategies hedging each other on one contract keep their gross quantities when their signed sum reconciles with the broker's net.
- Only orders placed with a `strategy` name are in the strategy book. Orders placed elsewhere (for example in the broker's own app) are not, and show as `Unattributed`.

---

**Back to**: [API Documentation](../README.md)
