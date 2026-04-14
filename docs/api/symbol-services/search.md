# Search

Search for symbols by name, strike price, expiry, or other criteria.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/search
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/search
Custom Domain:  POST https://<your-custom-domain>/api/v1/search
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "query": "NIFTY 26000 DEC CE",
  "exchange": "NFO"
}
```

## Sample API Response

```json
{
  "status": "success",
  "message": "Found 7 matching symbols",
  "data": [
    {
      "brexchange": "NSE_FO",
      "brsymbol": "NIFTY 26000 CE 30 DEC 25",
      "exchange": "NFO",
      "expiry": "30-DEC-25",
      "freeze_qty": 1800,
      "instrumenttype": "CE",
      "lotsize": 65,
      "name": "NIFTY",
      "strike": 26000,
      "symbol": "NIFTY30DEC2526000CE",
      "tick_size": 5,
      "token": "NSE_FO|71399"
    },
    {
      "brexchange": "NSE_FO",
      "brsymbol": "NIFTY 26000 CE 29 DEC 26",
      "exchange": "NFO",
      "expiry": "29-DEC-26",
      "freeze_qty": 1800,
      "instrumenttype": "CE",
      "lotsize": 65,
      "name": "NIFTY",
      "strike": 26000,
      "symbol": "NIFTY29DEC2626000CE",
      "tick_size": 5,
      "token": "NSE_FO|71505"
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| query | Search query string | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| message | string | Number of matching symbols found |
| data | array | Array of matching symbol objects |

### Data Array Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | OpenAlgo standard symbol |
| brsymbol | string | Broker-specific symbol |
| name | string | Underlying/symbol name |
| exchange | string | OpenAlgo exchange code |
| brexchange | string | Broker-specific exchange code |
| instrumenttype | string | CE, PE, FUT, EQ |
| expiry | string | Expiry date (DD-MMM-YY) |
| strike | number | Strike price |
| lotsize | number | Lot size |
| tick_size | number | Tick size |
| freeze_qty | number | Maximum quantity per order |
| token | string | Broker-specific token |

## Search Tips

| Query Format | Example | Finds |
|--------------|---------|-------|
| Symbol only | `RELIANCE` | All RELIANCE instruments |
| Symbol + Strike | `NIFTY 26000` | NIFTY options at 26000 strike |
| Symbol + Strike + Type | `NIFTY 26000 CE` | NIFTY 26000 Call options |
| Symbol + Month + Type | `NIFTY DEC CE` | NIFTY December Call options |
| Symbol + Strike + Month + Type | `NIFTY 26000 DEC CE` | Specific option series |

## Notes

- Search is **case-insensitive**
- Results are limited to avoid overwhelming response
- Use more specific queries for better results
- The search covers all available expiries for the exchange

---

**Back to**: [API Documentation](../README.md)
