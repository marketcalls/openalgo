# Version 2.0.3.6 Released

**Date: 26th November 2026**

**This release charges brokerage and statutory charges on every sandbox fill, lets OpenScript read any minute timeframe with candles counted from the session open, moves the pinned Python SDK to 2.4.1 and the charts to openalgo-charts 2.7.5, and fixes Flattrade, 5paisa XTS, Zerodha and SL-M stop orders.**

This is the first release after 2.0.3.5, with 22 commits since that bump, excluding automated frontend build commits and including this release. Run `cd upgrade && uv run migrate_all.py` as usual: it adds the charge columns to the sandbox database and the default brokerage plan. An install that only restarts gets the same columns at startup.

**Highlights**

- **Sandbox brokerage and statutory charges (`4bce67c35`, #2496)** - every sandbox fill now pays brokerage under your own plan, plus STT or CTT, exchange transaction charges, SEBI fees, stamp duty and GST at the published rates, taken from the available balance when the order fills. Set the plan per segment on `/sandbox/commissions`, which also has a transaction cost report with a CSV export. `/sandbox/calculator` shows every charge, the points to breakeven and the net P&L for a trade, and `POST /api/v1/charges` prices one order before it is placed (documented in `docs/api/account-services/charges.md`, examples priced in `702785ade`, #2497). `/sandbox/mypnl` shows today's and lifetime charges beside the P&L. Charges are on after the upgrade for new and existing installs; switch them off on `/sandbox/commissions` to keep the old behaviour. Trades made before the upgrade are not charged.
- **OpenScript reads any minute timeframe (`264b3c2a7`, `b7f750c62`)** - `openalgo-script` and the server engine `openscript` move to 0.9.0. A study or strategy on `/trading`, and a backtest, can read fifteen, twenty five or three minutes on a ten minute chart, where only whole multiples were allowed before; the finer bars are fetched for you. Intraday reads now start at the session open, so a 60 minute read on NSE runs 09:15 to 10:15 as the broker's candles do, and a saved study that reads 10, 20, 30 or 60 minutes redraws after the upgrade. A strategy deployed on the server still reads whole multiples of its interval only.
- **OpenScript backtests fetch a finer read that is its own base (`e44126d67`)** - a backtest of a `"15m"` read on an hourly chart, or `"1m"` on a 5 minute one, read as absent. On a chart the same read still draws nothing until the next `openalgo-script` release; write the minutes as a bare number (`"15"`) until then.
- **OpenScript skill (`7a92a704c`)** - a worked multi-timeframe example, `run.mjs` to run a draft on real bars before installing it, and new pitfalls from writing it.
- **Python SDK 2.4.1 (`c8b2896ca`, `348b7edf7`)** - several strategies on one account in one backtest or live session, including two on one symbol; optional daily limits; an audit record of every live order; custom tearsheets; and `client.charges(...)`, `client.discord(...)` and `client.slack(...)`. A backtest now charges the standard brokerage by default, the same plan the sandbox starts with, so equity backtest figures change. The AI agent's indicator and chart tools, skipped at startup since 2.0.3.5, load again.
- **Pivot Points Standard on every chart (`501198289`, `908764bb9`)** - openalgo-charts moves to 2.7.5, with the new pivot study (Traditional, Fibonacci, Woodie, Classic, DeMark or Camarilla, with an Auto period) taking the built-in indicators to 113. On Historify and the strategy charts, the settings forms can be dragged by their title bar.
- **Watchlist shows the price change by default (`39933fc6b`, #2276)** - four columns: Symbol, Last, Chg and Chg%. Prices and moves are shown to the paisa at every size, a flat instrument no longer reads as a green gain, and the timezone list grows from 14 zones to 30.
- **Weekly and monthly charts load for every broker (`6c9d35b61`, #2443, issue #2384)** - brokers without native weekly or monthly history timed out on `/trading`. A daily source now asks for up to 2000 days per call, so five years of weekly bars and ten years of monthly bars arrive inside the deadline.
- **Flattrade (`73599f37c`, #2507; `9f8ad8246`, #2482)** - order updates stream from the market data socket instead of polling; a non-JSON order book reply after the daily rollover now answers Not_Ok instead of raising (#2386); and pre-open history bars before the calendar's session open are dropped, which had broken older history on Muhurat day.
- **5paisa XTS (`5749d4126`, #2504, issue #2484; `19f993c92`, #2490)** - XTS answers are read as the XTS v2 docs describe them, so open positions and trade book fills are right and a smart-order exit no longer places a new order; the feed and history share one market data session, so history no longer fails with "Invalid Token"; and history requests no longer leave gaps between chunks.
- **Zerodha (`8128336df`, #2503; `cbeb1378a`, #2494, issue #2491)** - holdings count pledged and T1 shares, so a fully pledged holding no longer shows 0 shares and Rs 0; and full-mode ticks read open interest from its documented bytes instead of the fifth ask level.
- **SL-M stop orders on Shoonya, Flattrade and Firstock (`3f7fcd295`, #2495)** - these brokers take SL-M as a stop-limit, and its limit is now priced off the trigger rather than the last price, so a triggered stop no longer rests away from the market.
- **Broker skill and QA checklist (`7b253a907`, #2483)** - refreshed from the broker fixes of September to November 2026.

**Dependencies**

- `openalgo` (Python SDK) 2.3.0 to 2.4.1.
- `openscript` (OpenScript server engine) 0.8.1 to 0.9.0.
- Frontend: `openalgo-charts` 2.7.3 to 2.7.5, and `openalgo-script` 0.8.1 to 0.9.0.

**Contributors**

- **@marketcalls** - sandbox charges, the calculator and the charges API (#2496, #2497), OpenScript 0.9.0 on `/trading` and in backtests, the watchlist (#2276), openalgo-charts 2.7.4 and 2.7.5, the SDK 2.4.0 and 2.4.1 updates with the agent's indicator tools, and the release.
- **@Kalaiviswa** - Flattrade order updates and fixes (#2507, #2482), 5paisa XTS (#2504), Zerodha holdings and open interest (#2503, #2494), SL-M stop pricing (#2495), weekly and monthly charts (#2443) and the broker skill refresh (#2483).
- **@nikitabhagat2307-prog (Nikita Bhagat)** - 5paisa XTS history chunk gaps (#2490).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
