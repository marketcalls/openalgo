# Instruments API

## Endpoint URL

Download all trading symbols and instruments with exchange-wise filtering in JSON or CSV format.

```http
GET http://127.0.0.1:5000/api/v1/instruments
```

## Parameters

| Parameter | Type   | Required | Description                                       | Default |
| --------- | ------ | -------- | ------------------------------------------------- | ------- |
| apikey    | string | Yes      | API Key for authentication                        | -       |
| exchange  | string | No       | Filter by exchange: NSE, BSE, NFO, BFO, BCD, CDS, MCX, NSE_INDEX, BSE_INDEX | All |
| format    | string | No       | Output format: json or csv                        | json    |

## Browser Examples

Replace `your_api_key_here` with your actual API key and paste in browser:

**Download All Exchanges - All Instruments (JSON)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here
```

**Download All Exchanges - All Instruments (CSV)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here&format=csv
```

**Download NSE Equities Only (CSV)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here&exchange=NSE&format=csv
```

**Download NFO Derivatives Only (CSV)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here&exchange=NFO&format=csv
```

**Download BSE Equities Only (CSV)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here&exchange=BSE&format=csv
```

**Download MCX Commodities Only (CSV)**
```
http://127.0.0.1:5000/api/v1/instruments?apikey=your_api_key_here&exchange=MCX&format=csv
```

## Response Fields

| Field          | Description                                      |
| -------------- | ------------------------------------------------ |
| symbol         | OpenAlgo standard symbol                         |
| brsymbol       | Broker-specific symbol                           |
| name           | Instrument name                                  |
| exchange       | Exchange code                                    |
| token          | Instrument identifier                            |
| expiry         | Expiry date (F&O only)                           |
| strike         | Strike price (options only)                      |
| lotsize        | Lot size                                         |
| instrumenttype | Instrument type (EQ, FUT, CE, PE, etc.)          |
| tick_size      | Minimum price movement                           |

## JSON Response

```json
{
    "status": "success",
    "message": "Found 5000 instruments",
    "data": [
        {
            "symbol": "RELIANCE",
            "name": "Reliance Industries Ltd",
            "exchange": "NSE",
            "token": "2885",
            "lotsize": 1,
            "instrumenttype": "EQ"
        }
    ]
}
```

## CSV Response

```csv
symbol,brsymbol,name,exchange,token,expiry,strike,lotsize,instrumenttype,tick_size
RELIANCE,RELIANCE-EQ,Reliance Industries Ltd,NSE,2885,,,1,EQ,0.05
```

## Error Codes

| Code | Message                     |
| ---- | --------------------------- |
| 401  | API key is required         |
| 403  | Invalid openalgo apikey     |
| 400  | Invalid exchange or format  |

## Notes

- **Without exchange parameter**: Downloads ALL exchanges in one shot (NSE, BSE, NFO, BFO, BCD, CDS, MCX, NSE_INDEX, BSE_INDEX)
- **With exchange parameter**: Downloads only specified exchange
- CSV format auto-downloads in browser
- Rate limit: 50 requests/second
- Data updates when master contracts are downloaded
