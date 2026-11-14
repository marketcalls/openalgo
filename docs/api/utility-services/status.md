# Active Status

Show what is active in OpenAlgo right now and what is loading the broker: the
broker feed connections and subscribed symbols, open streams and threads, and
how many of each kind of broker data request were made in the last one and
five minutes.

## Endpoint

```http
POST /api/v1/status
```

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/status' \
  -H 'Content-Type: application/json' \
  -d '{"apikey":"<your_app_apikey>"}'
```

```json
{
  "status": "success",
  "data": {
    "broker_feed": {
      "connections": 1,
      "subscribed_symbols": 500,
      "pools": {
        "zerodha": {"broker": "zerodha", "count": 1, "symbols": 500}
      }
    },
    "streams": {
      "open": 1,
      "by_kind": {"python_strategy_sse": 1}
    },
    "threads": {
      "active": 42,
      "web_server_threads": null,
      "browser_connections": 2,
      "headroom": null
    },
    "requests": {
      "last_60s": {
        "quotes": 120, "multiquotes": 0, "depth": 0, "history": 2,
        "positionbook": 12, "orderbook": 6, "tradebook": 0, "holdings": 0, "funds": 6
      },
      "last_300s": {
        "quotes": 600, "multiquotes": 0, "depth": 0, "history": 9,
        "positionbook": 60, "orderbook": 30, "tradebook": 0, "holdings": 0, "funds": 30
      }
    }
  }
}
```

Here two charts poll quotes every second (120 a minute) and the positions page
refreshes every 5 seconds.

## Fields

| Field | Meaning |
|---|---|
| `broker_feed.connections` | Broker WebSocket connections the feed holds (the Health Monitor's WebSocket count) |
| `broker_feed.subscribed_symbols` | Symbols subscribed on the broker feed |
| `broker_feed.pools` | The same counts per broker pool |
| `streams.open` | Long-lived responses open now (live logs, MCP and agent streams), as on the System page |
| `streams.by_kind` | Open streams per kind |
| `threads.active` | Threads alive in the OpenAlgo process |
| `threads.web_server_threads` | Size of the web server's thread pool under the gthread worker; `null` under eventlet and the development server |
| `threads.browser_connections` | Browser (Socket.IO) connections held open |
| `threads.headroom` | Web server threads still free under gthread; `null` otherwise |
| `requests.last_60s`, `requests.last_300s` | Broker data requests per kind (`quotes`, `multiquotes`, `depth`, `history`, `positionbook`, `orderbook`, `tradebook`, `holdings`, `funds`) in the last 60 and 300 seconds |

## Notes

- Request counts are taken where a request leaves for the broker, so they
  include the React pages (charts, positions, order book), Flow, the strategy
  module and Python strategies, not only external calls to `/api/v1/`. A
  `multiquotes` call counts once however many symbols it carries. In analyzer
  mode, book and funds requests sent through the API are answered by the
  sandbox but are still counted.
- `history` counts requests sent to the broker; history served from Historify
  (`source="db"`) is not counted.
- Counts are kept in memory, start empty when OpenAlgo restarts, and cover one
  OpenAlgo process.
- The broker feed counts come from the WebSocket proxy's stats snapshot, which
  it refreshes about every 10 seconds.
- An invalid API key returns HTTP 403. No broker session is needed.

**Back to**: [API documentation](../README.md)
