# Portfolio Analysis

Portfolio analysis runs historical simulations; these endpoints do not place orders. Paths below are relative to `/api/v1`.

| Method | Path | Authentication | Result |
|---|---|---|---|
| GET | `/portfolio/benchmarks` | `apikey` query parameter | Available index benchmarks from the instrument master |
| POST | `/portfolio/backtest` | `apikey` in JSON | Weighted portfolio simulation and analysis |
| POST | `/portfolio/tearsheet` | `apikey` in JSON | Downloadable self-contained HTML report |
| POST | `/portfolio/holdings` | `apikey` in JSON and active broker session | Analysis of current broker holdings |

Every endpoint verifies the OpenAlgo API key. Backtest and tearsheet requests with `source="db"` read local Historify data without requiring a broker login; `source="api"` additionally requires an active broker session. Holdings analysis always needs a broker session to read what is held, even when its historical prices come from Historify.

## Backtest and tearsheet request

```json
{
  "apikey": "<your_app_apikey>",
  "holdings": [
    {"symbol": "RELIANCE", "exchange": "NSE", "weight": 60},
    {"symbol": "INFY", "exchange": "NSE", "weight": 40}
  ],
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "benchmark": "NIFTY",
  "source": "db",
  "rebalance": "monthly"
}
```

| Field | Required/default | Accepted values |
|---|---|---|
| `apikey` | Required | OpenAlgo API key |
| `holdings` | Required | 1–50 holdings; unique symbols |
| `holdings[].symbol` | Required | OpenAlgo cash-equity or ETF symbol, 1–64 characters |
| `holdings[].exchange` | `NSE` | `NSE`, `BSE` |
| `holdings[].weight` | Required | Nonnegative relative weight; total must be positive. Fractions and percentages both work |
| `start_date`, `end_date` | Required | `YYYY-MM-DD` |
| `benchmark` | `null` | Optional index symbol from `/portfolio/benchmarks` |
| `benchmark_exchange` | `NSE_INDEX` | `NSE_INDEX`, `BSE_INDEX`, `GLOBAL_INDEX` |
| `rebalance` | `never` | `never`, `monthly`, `quarterly`, `yearly` |
| `drift_band` | `0` | Fraction from 0 to 0.99; 0 disables drift rebalancing |
| `initial_capital` | `100000` | At least 1 |
| `risk_free_rate` | `0` | Annual fraction from 0 to 0.5 |
| `source` | `db` | `db` (Historify) or `api` (broker history) |
| `cost_model` | `indian_equity` | `indian_equity` or `flat_bps` |
| `cost_exchange` | `NSE` | `NSE` or `BSE` charge schedule |
| `brokerage_pct` | `0` | Fraction from 0 to 0.05 |
| `charges` | `{}` | Per-charge nested overrides; see below |
| `gst_rate` | `null` | Optional fraction from 0 to 1 |
| `cost_bps` | `0` | Flat costs, 0–1000 basis points |
| `slippage` | `0` | Fraction from 0 to 0.1 |

`charges` overrides the Indian-equity schedule by charge name: `brokerage`, `stt`, `exchange_txn`, `sebi`, and `stamp_duty`. For example, `{"brokerage":{"flat":10,"cap":20},"stt":{"rate":0.001}}`. Nested `rate` values are fractions of the charge basis; `flat` and `cap` are rupee amounts per order where applicable. Omitted values retain model defaults; unknown charge keys are ignored. Check the applicable rates for the market and period being modelled.

A successful backtest returns `status: "success"` with analysis at the **top level**, including `meta`, `equity`, `benchmark_equity`, `metrics`, `items`, `correlation`, `diversification`, `series`, and robustness analyses. It does not wrap these under `data`. `meta.total_return_basis` is `"price"`; dividends are not included. Read `meta.data_warnings` and benchmark availability before interpreting comparisons.

A successful tearsheet returns `text/html; charset=utf-8`, with `Content-Disposition: attachment; filename="portfolio-tearsheet.html"`. Errors remain JSON; check the status/content type before saving the response as HTML.

## Holdings analysis request

```json
{
  "apikey": "<your_app_apikey>",
  "lookback_days": 365,
  "benchmark": "NIFTY",
  "benchmark_exchange": "NSE_INDEX",
  "risk_free_rate": 0,
  "source": "db"
}
```

`lookback_days` accepts 60–3650, default 365. The remaining optional fields use the benchmark, rate and source rules above; holdings analysis defaults `benchmark` to `NIFTY`. Results include `summary` and historical portfolio analysis; unsupported holdings or missing price history can limit that analysis. This is a historical analysis of the current holdings, not a reconstruction of all past purchases and sales.

## Status codes and limits

- `200`: JSON analysis/list, or HTML tearsheet.
- `400`: Invalid request/schema or simulation inputs.
- `403`: Invalid API key, or missing broker session where required.
- `422`: Required historical data cannot support the analysis.
- `429`: Rate limit exceeded; `500`: unexpected analysis/rendering error.

Backtest and holdings default to `PORTFOLIO_API_RATE_LIMIT="10 per minute"`; tearsheet uses `PORTFOLIO_TEARSHEET_RATE_LIMIT="5 per minute"`. Benchmarks uses `API_RATE_LIMIT` (its route fallback is `10 per second`).

Source contracts: `restx_api/portfolio.py`, `services/portfolio_service.py`, `portfolio/costs.py`, and `portfolio/data.py`.

**Back to**: [API Documentation](../README.md)
