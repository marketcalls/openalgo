# Holdings

Get portfolio holdings (delivery positions) with P&L information.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/holdings
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/holdings
Custom Domain:  POST https://<your-custom-domain>/api/v1/holdings
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "holdings": [
      {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 1,
        "pnl": -149.0,
        "pnlpercent": -11.1
      },
      {
        "symbol": "TATASTEEL",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 1,
        "pnl": -15.0,
        "pnlpercent": -10.41
      },
      {
        "symbol": "CANBK",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 5,
        "pnl": -69.0,
        "pnlpercent": -13.43
      }
    ],
    "statistics": {
      "totalholdingvalue": 1768.0,
      "totalinvvalue": 2001.0,
      "totalprofitandloss": -233.15,
      "totalpnlpercentage": -11.65
    }
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Holdings data |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| holdings | array | Array of holding objects |
| statistics | object | Portfolio statistics |

### Holding Object Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Stock symbol |
| exchange | string | Exchange (NSE/BSE) |
| product | string | Product type (CNC) |
| quantity | number | Number of shares held |
| pnl | number | Profit/Loss in currency |
| pnlpercent | number | Profit/Loss percentage |

### Statistics Object Fields

| Field | Type | Description |
|-------|------|-------------|
| totalholdingvalue | number | Current market value of holdings |
| totalinvvalue | number | Total investment value (cost) |
| totalprofitandloss | number | Total P&L in currency |
| totalpnlpercentage | number | Total P&L percentage |

## Notes

- Holdings are **delivery positions** (CNC product type)
- Different from [PositionBook](./positionbook.md) which shows intraday positions
- **pnl** is calculated as: (Current Price - Average Buy Price) × Quantity
- **totalholdingvalue** is the current market value of entire portfolio
- Holdings persist across trading days (unlike MIS positions)

## Use Cases

- **Portfolio tracking**: View all delivery holdings
- **Wealth monitoring**: Track total portfolio value
- **Performance analysis**: Monitor overall P&L

---

**Back to**: [API Documentation](../README.md)
