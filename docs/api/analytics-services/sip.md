# SIP Backtester

These endpoints simulate systematic investments in cash equities and ETFs. They do not create a live SIP or place orders. Paths are relative to `/api/v1`.

| Method | Path | Authentication |
|---|---|---|
| GET | `/sip/frequencies` | No API key required |
| POST | `/sip/backtest` | OpenAlgo `apikey` in JSON |

The frequency list returns `{"status":"success","data":[{"value":"monthly","label":"Monthly"}, ...]}`. Supported values are `monthly`, `fortnightly`, `weekly`, and `quarterly`.

## Backtest request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTYBEES",
  "exchange": "NSE",
  "start_date": "2024-01-01",
  "end_date": "2025-12-31",
  "amount": 10000,
  "frequency": "monthly",
  "day_of_month": 1,
  "source": "db",
  "include_grids": false
}
```

| Field | Required/default | Accepted values |
|---|---|---|
| `apikey` | Required | OpenAlgo API key |
| `symbol` | Required | OpenAlgo cash-equity or ETF symbol, 1–64 characters |
| `exchange` | `NSE` | `NSE`, `BSE` |
| `start_date`, `end_date` | Required | `YYYY-MM-DD`; maximum span 30 years |
| `amount` | Required | Investment per installment, 1–10,000,000 |
| `frequency` | `monthly` | `monthly`, `fortnightly`, `weekly`, `quarterly` |
| `day_of_month` | `1` | 1–28; used by monthly/quarterly schedules |
| `step_up_percent` | `0` | Annual percentage increase, 0–100 |
| `brokerage_percent` | `0` | Percentage points, 0–5 (unlike portfolio `brokerage_pct`, which is a fraction) |
| `brokerage_flat` | `0` | Flat brokerage per installment, 0–10,000 |
| `cost_model` | `indian_equity` | `indian_equity`, `flat_bps` |
| `cost_exchange` | `NSE` | `NSE`, `BSE` |
| `charges`, `gst_rate`, `cost_bps`, `slippage` | `null`, `null`, `0`, `0` | Charge overrides and units as on [portfolio analysis](portfolio.md); GST 0–1, costs 0–1000 bps, slippage 0–0.1 |
| `benchmark` | `null` | Optional index symbol |
| `benchmark_exchange` | `NSE_INDEX` | `NSE_INDEX`, `BSE_INDEX`, `GLOBAL_INDEX` |
| `source` | `db` | `db` (Historify) or `api` (broker history) |
| `include_grids` | `true` | Include rolling/start-date/crisis analyses and the applicable SIP-date grid |

Every backtest verifies the API key, including local-history runs. `source="api"` additionally needs an active broker login. Historify runs need local price coverage for the requested period. Requested installment dates move to the next available trading session; the response preserves both requested and executed dates.

## Response

A successful response has `status: "success"` and analysis fields at the **top level**: `request`, `headline`, `underwater`, `drawdown`, `yearly`, `monthly_heatmap`, `lumpsum`, `charges`, `frequency_comparison`, `curves`, `installments`, and `warnings`.

When `include_grids=true`, it also contains `rolling_xirr`, `start_date_heatmap`, `crisis`, and `sip_date_heatmap` (the latter is `null` for weekly/fortnightly schedules). A requested benchmark adds `benchmark`. Read warnings and the executed schedule alongside returns; results depend on available price history and the configured costs.

## Status codes and limits

`200` indicates a result; `400` invalid inputs/schema; `403` invalid API key or missing required broker session; `422` insufficient data or an unsupported simulation/schedule; `429` rate limit; `500` unexpected error.

Both routes use `SIP_API_RATE_LIMIT`, default `10 per minute`. `include_grids=false` skips the additional grids for a smaller run.

Source contracts: `restx_api/sip.py`, `services/sip_service.py`, and `sip/schedule.py`.

**Back to**: [API Documentation](../README.md)
