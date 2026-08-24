# Quotes

Get real-time market quotes for a single symbol including OHLC, LTP, bid/ask, and volume.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/quotes
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/quotes
Custom Domain:  POST https://<your-custom-domain>/api/v1/quotes
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/quotes \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "ltp": 1187.75,
    "ask": 1188.0,
    "bid": 1187.85,
    "prev_close": 1165.7,
    "volume": 14414545
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Trading symbol | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Quote data object |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| open | number | Day's open price |
| high | number | Day's high price |
| low | number | Day's low price |
| ltp | number | Last traded price |
| ask | number | Best ask price |
| bid | number | Best bid price |
| prev_close | number | Previous day's close price |
| volume | number | Total traded volume |

## Notes

- Quotes are **real-time** and refresh with each trade
- For **F&O symbols**, use the OpenAlgo standard format (e.g., NIFTY25AUG26FUT)
- For **multiple symbols**, use the [MultiQuotes](./multiquotes.md) endpoint
- The **bid/ask** spread indicates liquidity

## Example: F&O Quote

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTY25AUG26FUT",
  "exchange": "NFO"
}
```

## Related Endpoints

- [MultiQuotes](./multiquotes.md) - Get quotes for multiple symbols
- [Depth](./depth.md) - Get market depth (Level 2)

## Error Responses

| HTTP | code | Meaning | What to do |
|------|------|---------|------------|
| 403 | (none) | `Invalid openalgo apikey` - the key is unknown or has been regenerated | Re-issue the key at `/apikey` |
| 401 | `BROKER_SESSION_EXPIRED` | The API key is valid, but the broker session ended at the daily rollover (`SESSION_EXPIRY_TIME`, default 03:00 IST) | Log in and reconnect the broker. Retrying with the same key will not help |

```json
{
  "status": "error",
  "code": "BROKER_SESSION_EXPIRED",
  "message": "Broker session expired - please reconnect your broker"
}
```

Indian broker tokens are invalidated broker-side every morning, and only a
fresh broker login mints a new one. Crypto instances
(`DISABLE_SESSION_EXPIRY=true`) have no rollover and never return this code.

---

**Back to**: [API Documentation](../README.md)
