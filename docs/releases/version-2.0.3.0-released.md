# Version 2.0.3.0 Released

**Date: 29th October 2026**

**One charting engine for every chart, two new analysis tools and a new broker: every chart in OpenAlgo now draws with openalgo-charts 2.6.9, Sector Rotation and Strike Profile join the tools, and Sahi joins the brokers. This release also stops a sent order from being reported as failed when the broker's reply is lost, fixes sandbox order ids and margin, and carries a round of broker and security fixes.**

36 commits since v2.0.2.9, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.2.9 to 2.0.3.0.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds no database
migration.

**Highlights**

- **Every chart uses one engine (`936a7ef62`, `f618b6953`, `3c773e72a`,
  `ab94ce707`, `0a35b00ac`, `965628d88`, `45e8b0d60`, `66582498d`; #2297 to
  #2304).** The Scalping Terminal, Option Greeks (`/ivchart`), PnL Tracker,
  Straddle Chart, Straddle PnL Simulator, Health Monitor and the chart test
  page now draw with the same engine as `/trading`. They follow the light,
  dark and analyzer looks, read times in IST, and keep your zoom when you
  switch theme or toggle a series. The scalper charts gain the `/trading`
  legend, a countdown to the candle close, and a hovered candle that stays put
  while ticks arrive; the arrow keys and F6/F7 still trade, and the charting
  engine is only downloaded when you turn charts on. The separate
  lightweight-charts library is removed.
- **openalgo-charts 2.6.9 (`583852ba4`).** Volume studies such as On-Balance
  Volume and VWAP now work on Renko, range bar, line break and point and
  figure charts. A higher-timeframe study no longer shows "Insufficient
  confirmed history" when the loaded history starts just after a weekend or a
  holiday. OHLC and high-low bars thicken as you zoom in. Existing custom
  indicators keep working.
- **Sector Rotation (`b7cdc028e`, `3e37288e0`, `91e35d9fb`).** A new tool at
  `/sector-rotation` places every NSE sector index, or any stocks and indices
  you add, on four quadrants (Leading, Weakening, Lagging, Improving) against
  a benchmark, with a trail of daily or weekly bars. Prices come from Historify
  or from your broker. Positions use weighted averages of relative strength. A
  symbol needs 44 daily sessions or 20 weeks of shared history to appear. Four
  sector indices that many brokers do not publish (Consumer Durables,
  Healthcare, India Defence, Oil & Gas) are off the default map and can be
  added from search. Also available as `POST /api/v1/sectorrotation`.
- **Strike Profile (`2b2d73b5c`).** A new tool at `/strikeprofile` shows gamma
  exposure (GEX) and delta exposure (DEX) in rupees crore for every strike of
  up to twenty expiries at once, as a strike by expiry heatmap, with each
  expiry's peaks marked, the gamma flip level, and the call and put walls.
  Each expiry costs one option chain request.
- **Sahi broker (`a1adec367`, #2320).** Sign in with the API key and secret
  from Sahi; there is no redirect or TOTP, but the key must be approved once
  per trading day in Sahi's API Dashboard. Orders, smart orders, books,
  funds, margin, quotes, depth, history and live streaming are supported on
  NSE, BSE, NFO and BFO. MCX is listed by Sahi but not yet tradable there, so
  it is not loaded.
- **A sent order is never reported as failed when the reply is lost
  (`34ce7ca33`, #2305; reported in #2067 and #2293).** On Windows the
  connection to a broker could drop after the broker had accepted an order,
  and OpenAlgo reported a plain failure, so a caller that retried placed the
  order twice. Place order, smart order, basket order and split order now
  answer: "The connection to the broker dropped after the order was sent, so
  it may have been placed. Check the order book before placing it again."
  Order sends are never repeated automatically; only reads are retried once.
- **Sandbox order ids and margin (`103df9fbb`, `0e18e8a7b`).** Two sandbox
  orders on the same day could be given the same order id, which made the
  second fail and left its margin blocked with no order behind it. Every order
  now gets a unique id in the same format, and the margin is taken in the same
  save as the order, so a failed order never reduces your funds.
- **Broker fixes.**
  - Angel: modifying an SL or SL-M order now changes its trigger at the broker
    (`df1073cc2`, #2279); before, the modify answered success and the trigger
    stayed where it was. Daily candles are dated on their own session, quotes
    carry the bid and ask quantities, and non-tradable CDS bond and NCDEX
    index rows are dropped from the master (`79fe4cf18`, #2290).
  - RMoney: smart exits on F&O positions find the open position again
    (`dbb608e06`, #2292); before, every smart exit was refused with "No
    OpenPosition Found" while the position stayed open.
  - Groww: the live feed no longer falls into an endless reconnect loop, and
    reconnects no longer leak threads or memory (`979d35cb5`, #2312).
  - Dhan: index charts no longer break on 30 minutes after the close, because
    the extra bar Dhan appends to index history after the close is dropped
    (`2c4f35d84`, #2308). Every index symbol now uses the standard OpenAlgo
    name, and equity and index rows carry no expiry (`ab018044f`, #2306).
  - Fyers: NSE debt, warrant and InvIT series now load into the symbol master
    (`79fe4cf18`, #2290, fixes #2280).
  - Flattrade: an empty order, trade or position book no longer prints a
    warning every five seconds (`930bf89d3`, #2249).
- **Credentials kept out of logs (`de03682a9`, #2313; `b06c14d29`; #1853).**
  Seven XTS brokers and Samco no longer write any part of a session token to
  the log, and a test now refuses any new log line that would.
- **CI and dependency hygiene (`61243a093`, `24d81412b`).** The browser tests
  run on Ubuntu 24.04, and Dependabot waits seven days before proposing a new
  version, while security fixes still arrive at once.

**What to check after upgrading**

- **Fyers sovereign gold bonds are renamed** to match Zerodha: `SGBAPR28I`
  becomes `SGBAPR28I-GB`, for all 44 bonds. Update any strategy, alert or
  watchlist that uses the old name.
- **Dhan index symbols use the standard names.** An NSE or BSE index that was
  listed under Dhan's own name (for example "Nifty100 Alpha 30") is now
  `NIFTY100ALPHA30`. Headline indices such as NIFTY and SENSEX are unchanged.
  Update anything that used Dhan's raw name.
- **Index rows in the Dhan and Angel masters are typed `EQ`**, as Zerodha
  types them; the `NSE_INDEX` or `BSE_INDEX` exchange is what marks an index.
  A script that looked for an `INDEX` or `AMXIDX` type should check the
  exchange instead.
- **A new reply to watch for.** An external platform or script that places
  orders can now receive the "may have been placed" message above, with HTTP
  status 502. Do not retry it automatically: check the order book first.
- **Install your operating system's certificate update** when it is
  published (on Ubuntu: `sudo apt update && sudo apt upgrade`). Broker
  live-data feeds use the system certificate store, so the certifi update in
  this release does not cover them.
- **Building the frontend yourself needs a patched Node.js:** 22.23.4 or later
  on 22, 24.22.1 or later on 24, or 26.12.1 or later. Node 20 is no longer
  supported. Installed servers do not need Node.js; the frontend arrives
  prebuilt.

**Dependencies**

- `openalgo-charts` 2.6.7 to 2.6.9. `lightweight-charts` is removed.
- Security updates, no behaviour change expected: `certifi` 2026.7.22 to
  2026.10.19 (GHSA-6q48-6c7w-9gw2, critical), `Pillow` 12.3.0 to 13.0.0 (28
  advisories), `aiohttp` 3.14.3 to 3.14.5 (now pinned in the requirements
  files), `dnspython` 2.8.0 to 2.9.0, `msgpack` 1.2.2 to 1.2.3, `setuptools`
  83.0.0 to 84.1.0, and `filelock` to 4.2.4 through a uv override, since
  LiteLLM still caps it below 4.
- Optional `analysis` group: `streamlit` 1.66.1 (the first to accept Pillow
  13) and `GitPython` 3.2.1 (GHSA-83vg-56qc-22m7).
- Frontend: `zod` 4.6.7, `follow-redirects` 1.16.1, `vite` 8.1.6 and `vitest`
  4.1.12. The Node.js engines requirement is raised as above.
- Not fixed: `braces`, used only by the frontend test tools, has no patched
  release for GHSA-vfj7-8cjw-p6xm. It never reaches a browser or the server.
- The pinned `openalgo` Python SDK remains 2.0.5.

**Contributors**

- **@marketcalls** - every chart moved to openalgo-charts (#2297 to #2304) and
  the 2.6.9 upgrade, Sector Rotation, Strike Profile, sandbox order id and
  margin fixes, credential logging follow-up, Flattrade log noise (#2249),
  security dependency updates, CI and the release.
- **@Kalaiviswa** - Sahi broker integration (#2320), lost-reply order safety
  (#2305), Groww feed reconnects (#2312), Dhan index history and master
  (#2306, #2308), Fyers and Angel master, history and quote fixes (#2290),
  and Dependabot fixes (#2294, #2315).
- **@dmchandru (Chandru Dhanasekar)** - Angel SL order modify trigger (#2279).
- **@SatriaBagusNurhadianto (Chavaaa)** - XTS token values kept out of logs
  (#2313).
- **@dvygo (Deshik Narasimha)** - RMoney smart exit position lookup (#2292).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
