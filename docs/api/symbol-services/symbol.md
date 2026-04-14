# Symbol

Get detailed information about a specific trading symbol including broker-specific symbol mapping.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/symbol
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/symbol
Custom Domain:  POST https://<your-custom-domain>/api/v1/symbol
```

## Sample API Request (Equity)

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

## Sample API Response (Equity)

```json
{
  "status": "success",
  "data": {
    "id": 979,
    "name": "RELIANCE",
    "symbol": "RELIANCE",
    "brsymbol": "RELIANCE-EQ",
    "exchange": "NSE",
    "brexchange": "NSE",
    "instrumenttype": "",
    "expiry": "",
    "strike": -0.01,
    "lotsize": 1,
    "tick_size": 0.05,
    "token": "2885"
  }
}
```

## Sample API Request (Futures)

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTY30DEC25FUT",
  "exchange": "NFO"
}
```

## Sample API Response (Futures)

```json
{
  "status": "success",
  "data": {
    "brexchange": "NSE_FO",
    "brsymbol": "NIFTY FUT 30 DEC 25",
    "exchange": "NFO",
    "expiry": "30-DEC-25",
    "freeze_qty": 1800,
    "id": 57900,
    "instrumenttype": "FUT",
    "lotsize": 65,
    "name": "NIFTY",
    "strike": 0,
    "symbol": "NIFTY30DEC25FUT",
    "tick_size": 10,
    "token": "NSE_FO|49543"
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Trading symbol in OpenAlgo format | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Symbol details object |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| id | number | Internal symbol ID |
| name | string | Symbol name/underlying |
| symbol | string | OpenAlgo standard symbol |
| brsymbol | string | Broker-specific symbol |
| exchange | string | OpenAlgo exchange code |
| brexchange | string | Broker-specific exchange code |
| instrumenttype | string | Instrument type (EQ, FUT, CE, PE) |
| expiry | string | Expiry date for F&O (DD-MMM-YY) |
| strike | number | Strike price for options (-0.01 for non-options) |
| lotsize | number | Lot size for F&O (1 for equity) |
| tick_size | number | Minimum price movement |
| freeze_qty | number | Maximum quantity per order (for F&O) |
| token | string | Broker-specific instrument token |

## Notes

- Use this endpoint to get the **broker-specific symbol** for order placement
- The **lotsize** field shows:
  - NIFTY: 65
  - BANKNIFTY: 30
  - SENSEX: 20
  - Equity: 1
- The **freeze_qty** field indicates the maximum quantity allowed per order
- The **token** is used by brokers for faster symbol lookup

---

**Back to**: [API Documentation](../README.md)
