# OpenAlgo LIVE demo: history + WebSocket

Streams a real OpenAlgo instance into the chart: historical candles over REST
(`/api/v1/history`) plus live updates over the OpenAlgo WebSocket proxy
(each LTP runs through `CandleBuilder` into the forming candle, plus a live LTP line).

It uses the library's real adapters unchanged: `OpenAlgoDataFeed` (history),
`OpenAlgoWsFeed` (live), and `CandleBuilder` (ticks into interval bars).

## Run

1. Have OpenAlgo running locally: REST on `http://127.0.0.1:5000`, WS proxy on
   `ws://127.0.0.1:8765` (the defaults).
2. Start this demo's server (it serves the package + proxies REST so the browser
   isn't blocked by CORS, since OpenAlgo sends no `Access-Control-Allow-*` headers):

   ```bash
   python examples/live/server.py            # http://127.0.0.1:8001
   # custom OpenAlgo host:
   OPENALGO_HOST=http://127.0.0.1:5000 python examples/live/server.py
   ```

3. Open `http://127.0.0.1:8001/examples/live/index.html`, paste your **API key**,
   pick symbol / exchange / interval, and click **Connect**.

The toolbar shows `WS live`, a running tick count, and the live LTP; intraday
intervals (1m/5m/15m/1h) aggregate LTP ticks into the forming candle, while `D`
shows the daily history with a moving LTP line.

History and its repair belong to one `DataLoadingController`. Repairs are
driven by the stream rather than a clock: one refresh a moment after each bar
closes (`refreshOnBarClose`), an immediate one when the stream skips a bucket
(`refreshOnGap`), and a slow poll every two minutes as the backstop for silent
drift. Each repair asks history for the last few bars only
(`refreshWindowBars`). Completed bars snap to the broker's official OHLC and
volume. The forming bar keeps its live close, takes the union of the extremes
and, when the builder opened it mid-bucket, the open history reports. Live OHLC
uses **LTP** mode (reliable across brokers); the forming bar's volume fills in
from history. (Quote-mode live volume exists in the adapter but is
broker-dependent, some brokers return `subscribe partial`.)

## Chart trading (real orders)

Right-click the chart to place an order **at the cursor price**, Buy/Sell
**Market / Limit / Stop (SL)**, via OpenAlgo's `placeorder` API. Working orders
appear as draggable lines (drag and release to **modify**, click its close box to
**cancel**); the net position shows as a line with **live P&L marked to the LTP**
and its own close box to **exit** (square off to flat via `placesmartorder position_size 0`).
Orders/positions are polled from `/orderbook` + `/positionbook` every 3s.

Safety:
- **Live trading** is off by default; nothing places until you turn it on.
- The **mode** pill reflects OpenAlgo's routing, read from the book response:
  `ANALYZE (sandbox)` or `LIVE - real orders`. In **LIVE** mode every order asks
  for an explicit confirm first.
- Set OpenAlgo to **Analyzer** mode (`/analyzer`) to test against the ₹1 Cr
  sandbox with no real fills. Validated end-to-end in sandbox: place, modify and
  cancel through the proxy.

## Notes

- **Your API key is never stored in this repo.** It is entered in the page, saved
  only to the browser's `localStorage`, and forwarded in the request body by the
  local proxy. The WebSocket authenticates with it directly from the browser.
- **Live ticks only flow during market hours**; outside them the history loads
  and the WS subscribes, but no `market_data` arrives.
- REST is proxied (same origin); the WebSocket connects straight to OpenAlgo
  (WS upgrades aren't subject to the CORS preflight that blocks REST).
- Validated against a live instance: history returns real bars and the WS streams
  `{type:'market_data', data:{ltp, timestamp}}` ticks that the adapter maps directly.
