# Instruments

Get the complete list of instruments/symbols available for trading. Can be filtered by exchange.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/instruments
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/instruments
Custom Domain:  POST https://<your-custom-domain>/api/v1/instruments
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "exchange": "NSE"
}
```

## Sample API Response

```json
{
  "status": "success",
  "message": "Found 3046 instruments",
  "data": [
    {
      "symbol": "RELIANCE",
      "brsymbol": "RELIANCE-EQ",
      "name": "RELIANCE INDUSTRIES LTD",
      "exchange": "NSE",
      "brexchange": "NSE",
      "token": "2885",
      "expiry": null,
      "strike": -1.0,
      "lotsize": 1,
      "instrumenttype": "EQ",
      "tick_size": 0.05
    },
    {
      "symbol": "TCS",
      "brsymbol": "TCS-EQ",
      "name": "TATA CONSULTANCY SERVICES",
      "exchange": "NSE",
      "brexchange": "NSE",
      "token": "11536",
      "expiry": null,
      "strike": -1.0,
      "lotsize": 1,
      "instrumenttype": "EQ",
      "tick_size": 0.05
    }
  ]
}
```

## Sample API Request (All Exchanges)

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| exchange | Exchange filter: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Optional | All exchanges |
| format | Output format: "json" or "csv" | Optional | json |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| message | string | Number of instruments found |
| data | array | Array of instrument objects |

### Data Array Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | OpenAlgo standard symbol |
| brsymbol | string | Broker-specific symbol |
| name | string | Full company/instrument name |
| exchange | string | OpenAlgo exchange code |
| brexchange | string | Broker-specific exchange code |
| token | string | Broker-specific instrument token |
| expiry | string | Expiry date (null for equity) |
| strike | number | Strike price (-1 for non-options) |
| lotsize | number | Lot size (1 for equity) |
| instrumenttype | string | EQ, FUT, CE, PE |
| tick_size | number | Minimum price movement |

## CSV Export

Request with `format: "csv"` to get data as downloadable CSV:

```json
{
  "apikey": "<your_app_apikey>",
  "exchange": "NSE",
  "format": "csv"
}
```

The response will include `Content-Disposition` header for file download.

## Notes

- Without exchange filter, returns instruments from **all exchanges** (can be large)
- For NFO/BFO, includes all futures and options contracts
- Data is refreshed daily with master contract updates
- Use CSV format for importing into spreadsheets or databases
- Response can be large for F&O exchanges (50,000+ instruments)

## Exchange Instrument Counts (Approximate)

| Exchange | Instruments |
|----------|-------------|
| NSE | ~3,000 |
| BSE | ~5,000 |
| NFO | ~50,000+ |
| BFO | ~30,000+ |
| CDS | ~500 |
| MCX | ~200 |

---

**Back to**: [API Documentation](../README.md)
