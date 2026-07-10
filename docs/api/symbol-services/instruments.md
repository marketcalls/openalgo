# Instruments

Download the locally stored instrument master for every exchange or for one exchange. This is the only v1 market-data resource that returns CSV as an alternative to JSON.

## Endpoint

```http
GET /api/v1/instruments?apikey=<key>&exchange=NFO&format=json
```

## Query Parameters

| Parameter | Required | Values | Default |
|---|---:|---|---|
| `apikey` | Yes | OpenAlgo API key | - |
| `exchange` | No | Any exchange accepted by `VALID_EXCHANGES` | all exchanges |
| `format` | No | `json`, `csv` | `json` |

## JSON Example

```bash
curl --get 'http://127.0.0.1:5000/api/v1/instruments' \
  --data-urlencode 'apikey=<your_app_apikey>' \
  --data-urlencode 'exchange=NFO' \
  --data-urlencode 'format=json'
```

```json
{
  "status": "success",
  "message": "Found 1 instruments",
  "data": [
    {
      "symbol": "NIFTY30JUL2625000CE",
      "brsymbol": "NIFTY26JUL25000CE",
      "name": "NIFTY",
      "exchange": "NFO",
      "brexchange": "NFO",
      "token": "12345",
      "expiry": "30-JUL-26",
      "strike": 25000,
      "lotsize": 65,
      "instrumenttype": "CE",
      "tick_size": 0.05
    }
  ]
}
```

The exact symbols, broker symbols, token types, and row count depend on the active broker's downloaded master contract.

## CSV Example

```bash
curl --get 'http://127.0.0.1:5000/api/v1/instruments' \
  --data-urlencode 'apikey=<your_app_apikey>' \
  --data-urlencode 'exchange=NSE' \
  --data-urlencode 'format=csv' \
  --output instruments_NSE.csv
```

CSV responses use `Content-Type: text/csv` and a download filename of `instruments_<exchange>.csv` (or `instruments_all.csv`).

## Errors

| Status | Condition |
|---:|---|
| 400 | Invalid query parameter |
| 401 | API key is missing |
| 403 | API key is invalid |
| 500 | Instrument database query failed |

**Back to**: [API documentation](../README.md)
