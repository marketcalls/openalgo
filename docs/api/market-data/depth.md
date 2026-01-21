# Depth

Get market depth (Level 2 data) for a symbol showing top 5 bid and ask prices with quantities.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/depth
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/depth
Custom Domain:  POST https://<your-custom-domain>/api/v1/depth
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "SBIN",
  "exchange": "NSE"
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "open": 760.0,
    "high": 774.0,
    "low": 758.15,
    "ltp": 769.6,
    "ltq": 205,
    "prev_close": 746.9,
    "volume": 9362799,
    "oi": 161265750,
    "totalbuyqty": 591351,
    "totalsellqty": 835701,
    "asks": [
      {"price": 769.6, "quantity": 767},
      {"price": 769.65, "quantity": 115},
      {"price": 769.7, "quantity": 162},
      {"price": 769.75, "quantity": 1121},
      {"price": 769.8, "quantity": 430}
    ],
    "bids": [
      {"price": 769.4, "quantity": 886},
      {"price": 769.35, "quantity": 212},
      {"price": 769.3, "quantity": 351},
      {"price": 769.25, "quantity": 343},
      {"price": 769.2, "quantity": 399}
    ]
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
| data | object | Market depth data object |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| open | number | Day's open price |
| high | number | Day's high price |
| low | number | Day's low price |
| ltp | number | Last traded price |
| ltq | number | Last traded quantity |
| prev_close | number | Previous day's close |
| volume | number | Total traded volume |
| oi | number | Open interest (for F&O) |
| totalbuyqty | number | Total buy quantity in order book |
| totalsellqty | number | Total sell quantity in order book |
| asks | array | Top 5 ask (sell) prices |
| bids | array | Top 5 bid (buy) prices |

### Ask/Bid Array Fields

| Field | Type | Description |
|-------|------|-------------|
| price | number | Price level |
| quantity | number | Quantity at this price |

## Understanding Market Depth

```
        BIDS (Buyers)                 ASKS (Sellers)
        --------------               ----------------
Qty     Price                        Price     Qty
886     769.40 ←── Best Bid    Best Ask ──→ 769.60    767
212     769.35                              769.65    115
351     769.30                              769.70    162
343     769.25                              769.75    1121
399     769.20                              769.80    430
```

## Notes

- Depth shows the **order book** structure for a symbol
- **Bid-Ask spread** indicates liquidity (tighter = more liquid)
- **totalbuyqty vs totalsellqty** shows demand-supply balance
- For F&O, **oi** (open interest) is available
- Depth data updates in real-time with each order book change

## Use Cases

- **Scalping strategies**: Identify immediate support/resistance
- **Order placement**: Decide limit price based on depth
- **Liquidity analysis**: Assess ease of entry/exit

## Related Endpoints

- [Quotes](./quotes.md) - Basic quote data
- [WebSocket Depth](../websocket-streaming/depth.md) - Real-time depth streaming

---

**Back to**: [API Documentation](../README.md)
