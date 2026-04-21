# Sentiment

Get optional Adanos market sentiment snapshots for stock tickers.

This endpoint is designed as an external context module for research and strategy gating. It does not depend on broker market-data support and does not require OpenAlgo exchange codes.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/market/sentiment
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/market/sentiment
Custom Domain:  POST https://<your-custom-domain>/api/v1/market/sentiment
```

## Optional Setup

Add the following variables to your `.env` file to enable the module:

```bash
ADANOS_API_KEY=your_adanos_key
ADANOS_API_BASE_URL=https://api.adanos.org
ADANOS_SENTIMENT_DEFAULT_DAYS=7
ADANOS_API_TIMEOUT_MS=10000
```

If `ADANOS_API_KEY` is not configured, the endpoint stays available and returns `enabled=false`.

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "tickers": ["AAPL", "TSLA", "NVDA"],
  "source": "all",
  "days": 7
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "enabled": true,
    "provider": "adanos",
    "tickers": ["AAPL", "TSLA", "NVDA"],
    "source": "all",
    "days": 7,
    "summary": "- reddit: TSLA (Tesla, Inc.): sentiment=0.31, buzz=71.2, mentions=140, trend=rising",
    "docs_url": "https://api.adanos.org/docs/",
    "snapshots": [
      {
        "source": "reddit",
        "endpoint": "https://api.adanos.org/reddit/stocks/v1/compare",
        "success": true,
        "stocks": [
          {
            "ticker": "TSLA",
            "company_name": "Tesla, Inc.",
            "source": "reddit",
            "sentiment_score": 0.31,
            "buzz_score": 71.2,
            "bullish_pct": 62,
            "bearish_pct": 18,
            "mentions": 140,
            "subreddit_count": 11,
            "source_count": null,
            "unique_tweets": null,
            "trade_count": null,
            "market_count": null,
            "total_liquidity": null,
            "trend": "rising",
            "trend_history": [52.3, 63.4, 71.2]
          }
        ]
      }
    ]
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| tickers | Raw stock tickers such as `AAPL`, `TSLA`, `NVDA` | Mandatory | - |
| source | `all`, `reddit`, `x`, `news`, or `polymarket` | Optional | `all` |
| days | Lookback window in days | Optional | `ADANOS_SENTIMENT_DEFAULT_DAYS` or `7` |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `success` or `error` |
| data.enabled | boolean | Whether Adanos enrichment is configured on this OpenAlgo instance |
| data.provider | string | External provider name |
| data.tickers | array | Normalized tickers used for the request |
| data.source | string | Requested source or `all` |
| data.days | integer | Effective lookback window |
| data.summary | string | Compact human-readable summary across sources |
| data.docs_url | string | Adanos API docs URL |
| data.snapshots | array | Source-by-source compare results |

## Notes

- This is an **optional external data module**. It is not tied to broker quotes, master contracts, or exchange codes.
- Use this endpoint for **research, filtering, ranking, or gating** before order execution.
- `tickers` are validated as raw stock ticker strings. Do not send OpenAlgo `exchange:symbol` pairs here.
- If Adanos is disabled locally, OpenAlgo returns `enabled=false` instead of failing the request.

## Use Cases

- Gate webhook or Python strategies with cross-source stock sentiment
- Rank watchlists by current retail/news/prediction-market activity
- Add a second opinion layer before smart-order execution
- Build dashboards that combine OpenAlgo execution data with external market context

---

**Back to**: [API Documentation](../README.md)
