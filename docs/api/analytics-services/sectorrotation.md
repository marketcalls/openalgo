# Sector Rotation

Build a relative rotation map from historical closing prices. This is an analysis API and does not place orders. Paths are relative to `/api/v1`.

| Method | Path | Authentication |
|---|---|---|
| GET | `/sectorrotation/options` | No API key required |
| POST | `/sectorrotation` | OpenAlgo `apikey` in JSON |

`GET /sectorrotation/options` returns `status: "success"` and `data` containing `benchmarks`, `timeframes`, `exchanges`, `max_instruments`, `sectors`, `optional_sectors`, and `max_tail`. Use these lists to populate a client rather than assuming all brokers supply all indices.

## Request

```json
{
  "apikey": "<your_app_apikey>",
  "benchmark": "NIFTY",
  "timeframe": "daily",
  "source": "db",
  "instruments": [
    {"symbol": "NIFTYIT", "exchange": "NSE_INDEX", "label": "IT"},
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ]
}
```

| Field | Required/default | Accepted values |
|---|---|---|
| `apikey` | Required | OpenAlgo API key |
| `benchmark` | `NIFTY` | `NIFTY`, `NIFTY500`, `BANKNIFTY`, `SENSEX`, `NIFTYNXT50`, `MIDCPNIFTY`, `FINNIFTY` |
| `timeframe` | `daily` | `daily`, `weekly` (resampled from daily closes) |
| `source` | `db` | `db` (Historify) or `api` (broker history) |
| `instruments` | `[]` | Up to 40; omitted/empty means the default NSE sector set |
| `instruments[].symbol` | Required per item | OpenAlgo symbol, 1–64 characters |
| `instruments[].exchange` | Required per item | `NSE`, `BSE`, `NSE_INDEX`, `BSE_INDEX`, `MCX_INDEX`, `GLOBAL_INDEX` |
| `instruments[].label` | `null` | Optional display label, at most 64 characters |

The benchmark determines its exchange; there is no `benchmark_exchange` request field. Derivatives are excluded. Every map request verifies the API key; `source="api"` additionally needs an active broker session. Local Historify data must cover the selected symbols and benchmark.

## Response and interpretation

Success returns `{"status":"success","data":{...}}`. `data` includes `benchmark`, `benchmark_exchange`, `benchmark_label`, `timeframe`, `source`, `as_of`, `max_tail`, `instruments`, and `unavailable`.

Each placed instrument includes its relative-strength ratio, momentum, quadrant, run length and trail. Both axes are centered on 100. These positions use OpenAlgo's weighted-average calculations; they are comparative trend measures, not forecasts or broker trade signals. Trails contain up to 30 points. Daily calculations use a 365-calendar-day lookback; weekly calculations use 730 days. Broker closes are cached for five minutes.

A missing sector does not invalidate the whole map: inspect `unavailable` and each reason even on a `200` response. If no instrument can be placed, the service returns `422`. A missing benchmark prevents calculation.

## Status codes and limits

`200` result/options; `400` invalid settings; `403` invalid key or missing required broker login; `422` insufficient history or no usable instruments; `429` rate limit; `500` unexpected error.

Both routes use `SECTOR_ROTATION_API_RATE_LIMIT`, default `30 per minute`.

Source contracts: `restx_api/sector_rotation.py` and `services/sector_rotation_service.py`.

**Back to**: [API Documentation](../README.md)
