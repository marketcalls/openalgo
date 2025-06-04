# SmartAPI - WebSocket Streaming 2.0 Documentation

## Web Socket URL

```
wss://smartapisocket.angelone.in/smart-stream
```

## Features

- Simplified JSON request and binary response structure
- Heartbeat support
- No need to reconnect for subscribe/unsubscribe
- Up to 3 concurrent WebSocket connections per client code
- Supports up to 1000 token subscriptions per session
- Duplicate subscriptions are ignored
- One tick per token_mode combination recommended

## Authentication Headers

| Header         | Mandatory | Description                                      |
|----------------|-----------|--------------------------------------------------|
| Authorization  | Yes       | JWT auth token from Login API                   |
| x-api-key      | Yes       | API Key                                          |
| x-client-code  | Yes       | Angel One trading account id                    |
| x-feed-token   | Yes       | Feed token from Login API                        |

## Error Authentication Headers

| Header           | Description                                 |
|------------------|---------------------------------------------|
| x-error-message  | Text explaining why auth failed (401 error) |

Examples:
- Invalid Auth token
- Invalid Client Code
- Invalid API Key
- Invalid Feed Token

## For Browser-Based Clients

URL Format:
```
wss://smartapisocket.angelone.in/smart-stream?clientCode=&feedToken=&apiKey=
```

## Heartbeat

- **Request**: `ping`
- **Response**: `pong`

## JSON Request Format

```json
{
  "correlationID": "abcde12345",
  "action": 1,
  "params": {
    "mode": 1,
    "tokenList": [
      {
        "exchangeType": 1,
        "tokens": ["10626", "5290"]
      },
      {
        "exchangeType": 5,
        "tokens": ["234230", "234235", "234219"]
      }
    ]
  }
}
```

## Request Field Description

| Field         | Type       | Mandatory | Description                                 | Valid Values       |
|---------------|------------|-----------|---------------------------------------------|---------------------|
| correlationID | String     | Optional  | Used for tracking error responses           |                     |
| action        | Integer    | Yes       | 1 (Subscribe), 0 (Unsubscribe)              | 0, 1                |
| mode          | Integer    | Yes       | Subscription type                           | 1 (LTP), 2 (Quote), 3 (Snap Quote) |
| exchangeType  | Integer    | Yes       | Type of exchange                            | 1–nse_cm, 2–nse_fo, 3–bse_cm, 5–mcx_fo etc. |
| tokens        | List       | Yes       | Token codes from master script              |                     |

## Binary Response Structure

### Section-1: Payload

(Details for each field in byte array, Little Endian format)

| Field                | DataType | Size | Index | Description                            |
|----------------------|----------|------|--------|----------------------------------------|
| Subscription Mode    | byte     | 1    | 0      | 1 (LTP), 2 (Quote), 3 (Snap Quote)     |
| Exchange Type        | byte     | 1    | 1      | 1–nse_cm, 5–mcx_fo etc.                |
| Token                | byte[]   | 25   | 2      | UTF-8 encoded string                    |
| Sequence Number      | int64    | 8    | 27     |                                          |
| Exchange Timestamp   | int64    | 8    | 35     | epoch ms                                |
| LTP                  | int32    | 8    | 43     | Prices in paise                         |
| Last Traded Qty      | int64    | 8    | 51     |                                          |
| Average Traded Price | int64    | 8    | 59     |                                          |
| Volume               | int64    | 8    | 67     |                                          |
| Total Buy Qty        | double   | 8    | 75     |                                          |
| Total Sell Qty       | double   | 8    | 83     |                                          |
| Open Price           | int64    | 8    | 91     |                                          |
| High Price           | int64    | 8    | 99     |                                          |
| Low Price            | int64    | 8    | 107    |                                          |
| Close Price          | int64    | 8    | 115    | Ends for Quote                          |
| Last Trade Timestamp | int64    | 8    | 123    |                                          |
| Open Interest        | int64    | 8    | 131    |                                          |
| OI Change %          | double   | 8    | 139    | Dummy field                             |
| Best Five Data       | bytes[]  | 200  | 147    | See Section-2                           |
| Upper Circuit Limit  | int64    | 8    | 347    |                                          |
| Lower Circuit Limit  | int64    | 8    | 355    |                                          |
| 52W High             | int64    | 8    | 363    |                                          |
| 52W Low              | int64    | 8    | 371    | Ends for SnapQuote                      |

### Section-2: Best Five Data

Each packet = 20 bytes (10 packets total = 200 bytes)

| Field           | DataType | Size | Index | Description       |
|------------------|----------|------|--------|--------------------|
| Buy/Sell Flag     | int16    | 2    | 0      | 1 (buy), 0 (sell)  |
| Quantity          | int64    | 8    | 2      |                    |
| Price             | int64    | 8    | 10     |                    |
| Number of Orders  | int16    | 2    | 18     |                    |

## Error Response Format

```json
{
  "correlationID": "abcde12345",
  "errorCode": "E1002",
  "errorMessage": "Invalid Request. Subscription Limit Exceeded"
}
```

### Error Codes

| Code   | Message                                      |
|--------|----------------------------------------------|
| E1001  | Invalid Request Payload                      |
| E1002  | Subscription Limit Exceeded                  |

*Note: Sequence number for index feed is not available.*