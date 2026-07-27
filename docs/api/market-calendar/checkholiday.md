# CheckHoliday

Check if a specific date is a market holiday for an exchange.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/checkholiday
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/checkholiday
Custom Domain:  POST https://<your-custom-domain>/api/v1/checkholiday
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "date": "2025-01-26",
  "exchange": "NSE"
}
```

## Sample API Response (Holiday)

```json
{
  "status": "success",
  "data": {
    "date": "2025-01-26",
    "exchange": "NSE",
    "is_holiday": true
  }
}
```

## Sample API Response (Trading Day)

```json
{
  "status": "success",
  "data": {
    "date": "2025-01-27",
    "exchange": "NSE",
    "is_holiday": false
  }
}
```

## Sample API Request (Without Exchange)

```json
{
  "apikey": "<your_app_apikey>",
  "date": "2025-01-26"
}
```

## Sample API Response (Without Exchange)

```json
{
  "status": "success",
  "data": {
    "date": "2025-01-26",
    "is_holiday": true
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| date | Date in YYYY-MM-DD format | Mandatory | - |
| exchange | Exchange code to check | Optional | All exchanges |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Holiday check result |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| date | string | Date checked |
| exchange | string | Exchange checked (if specified) |
| is_holiday | boolean | true if holiday, false if trading day |

## Notes

- Returns **true** for:
  - Exchange-specific holidays
  - Weekends (Saturday, Sunday)
  - National holidays
- If **exchange** is not specified, returns true if it's a holiday for any major exchange
- Date must be between **2020-01-01 and 2050-12-31**
- Use this for quick **pre-trade checks**

## Use Cases

- **Pre-trade validation**: Check if market is open before placing orders
- **Scheduling**: Determine if automated systems should run
- **Calendar display**: Show market status in applications

---

**Back to**: [API Documentation](../README.md)
