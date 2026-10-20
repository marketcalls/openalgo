# Version 2.0.2.3 Released

**Date: 6th September 2026**

**Feature Release: adds the Strategy Module and RMS at `/strategy`, a multi-leg options engine with end-to-end risk management built on a broker-agnostic risk core; ships the OpenAlgo Agent at `/agent`, an LLM assistant that reads live account and market data and can place orders at the operator's direction, usable on a ChatGPT subscription instead of an API key; rebuilds the charting terminal on openalgo-charts 2.0.2 with a bottom dock, armed one-click trading and a chart-side agent panel; and implements Kotak Neo historical data, which the plugin previously did not serve at all**

This release spans 217 commits since 2.0.2.2 and is dominated by two new modules rather than by fixes to existing ones.

The larger is the **Strategy Module and RMS**. The legacy `/strategy` module was retired and replaced by a multi-leg options engine in which risk is the point rather than an afterthought. Two kinds of strategy share one engine: a `batch` strategy enters and exits every leg together, a `signal` strategy moves one leg per alert, which is what makes per-alert TradingView trading work without a second code path. Underneath both sits `services/risk/`, a core that performs no I/O of any kind - no database, no broker, no market data, no clock, no logging. Every input arrives as an argument and every decision leaves as a return value, which is what makes it testable without a running platform, identical across the scalping terminal, Flow and the REST surface, and safe to call from a green thread and a real one alike.

That design was not chosen for elegance. The module this was ported from had its own evaluator, and four defects lived in it undetected: a leg with no recorded side evaluated as a short, so its stop fired on a favourable move; an exit derived from configuration doubled a short instead of covering it; an aggregate summed from a stale per-leg field; and a peak and trough persisted as zero on most stop paths. Each is now pinned by a test marked `PORTED DEFECT`, and `test/risk/vectors.json` is the contract between the Python core and its TypeScript counterpart so the two cannot drift.

A large share of this release's 44 strategy fixes are order-path safety work, and they converge on three rules, each learned from a defect that reversed a real position. **Claim under the same lock that checks**: the duplicate check and the marker write happen in one hold, and the marker is written before dispatch rather than after the order returns, because testing the order id let two rules firing on one leg send a covering order each. **Match a fill to the order it belongs to, not to the leg**: a signal flip squares one side and opens the other immediately, so one leg id names two positions until the closing order fills, and applying an exit fill by leg alone closed the position that had just been opened. **A caller that has already decided the pipe says so**: `place_order_with_auth` reads the platform-wide analyzer toggle first, so an operator switching to analyze mode mid-run sent every exit to the sandbox, which reports success.

The second module is the **Agent**. It is an LLM assistant with access to OpenAlgo's own service layer rather than a chat window bolted on: it can read the order book, positions, holdings, funds, quotes and history, compute Greeks and payoff diagrams, and place orders when the operator turns trading on. It runs on any LiteLLM-supported provider, and notably on a ChatGPT Plus or Pro subscription through OAuth device flow, which reaches Codex rather than the ChatGPT web app. It appears both as a full page at `/agent` and as a right-rail panel inside the charting terminal.

Outside those, the charting terminal moved from openalgo-charts 1.8.2 to 2.0.2 and gained a bottom dock, an explicit armed mode for one-click trading, watchlist and option chain side panels, and a user guide chapter. Kotak Neo gained historical data. Several broker plugins were repaired.

---

**Highlights**

* **Strategy Module and RMS at `/strategy` (`db57bf9ca` through `e62d6cc7f`, 71 commits)** - multi-leg options strategies with stop loss, target and trailing stop evaluated per leg and in aggregate, driven by the live tick feed with a REST fallback. Legs are measured in points or percent and counted in lots or units. The kill switch flattens rather than merely stopping. Crash recovery and periodic checkpointing mean a restart mid-run does not lose the position, and the books are served from the broker rather than from stored rows, so what the screen shows is what the broker holds. The module is exposed over the API-key surface at `/api/v1/strategy` and over a webhook, so a TradingView alert can move a single leg. Scheduling runs on IST times with cron jobs synced on every write.

  The safety work is the bulk of it. A stop whose exit orders were refused leaves the run **open and managed**, because the position is still there - reporting success and clearing the state is how a position ends up with nothing watching it. A refused dispatch releases its claim, or that leg is skipped by its stop loss, its target and every square-off for the rest of the session while the broker still holds it. Stale position marks are rejected, nullable broker positions are preserved rather than read as flat, and terminal partial fills are reconciled instead of assumed complete.

  Full reference: [`docs/prompt/strategy_rms_documentation.md`](../prompt/strategy_rms_documentation.md).

* **The broker-agnostic risk core (`55984920d`)** - `services/risk/` decides whether a position has hit its stop, taken its target, earned a tighter trailing stop, or whether a set of positions has run past its combined limits. It does no I/O, so it is exercised directly by golden vectors rather than through a running platform. Consumers translate, they do not decide: `services/strategy_module/risk_adapter.py` maps a leg onto `PositionRisk`, calls the core and writes the decision back. Adding a rule means changing the core, not adding a second evaluator beside it.

* **The OpenAlgo Agent at `/agent` (`72a5edea6` through `a62931aea`, #1997)** - an LLM agent wired to OpenAlgo's service layer. It answers from live data: order book, positions, holdings, funds, quotes, history, 127 indicators, streaming instrument cards, option Greeks, payoff diagrams and combined premium charts, with three renderers for charts in chat. Conversation threads persist, questions can be edited in place, and answers can be copied or retried. Trading is off until the operator switches it on, and reasoning effort is selectable per turn.

  **It runs on a ChatGPT subscription (`835ca8bd5`)**, authenticating by OAuth device flow instead of an API key, which reaches Codex rather than the ChatGPT web app. The provider catalogue is read live from LiteLLM so a package bump brings new models with it; the `chatgpt/*` entries are the one exception and are maintained by hand in `services/agent/chatgpt_models.py`, because a model absent from LiteLLM's registry has no `mode` and gets routed through the chat-completions bridge, landing on a Cloudflare interstitial that returns `403 Enable JavaScript and cookies to continue` rather than reaching the API. Web search falls back to Tavily rather than DuckDuckGo (`14833f2f4`).

* **Charting terminal: openalgo-charts 1.8.2 to 2.0.2 (`962310609`, `19c5d7089`)** - drawings saved by the old version are upgraded on load with their text, styling and Fibonacci ratios intact.

  **A bottom dock (`7d61076ea`)** shows orders, positions, trades and GTT across every symbol, not just the charted one, updating live from the account order stream and reconciling against the broker book. Cancel, modify and per-position close act on one row; cancel all and close all sit behind a confirmation; every write refuses while a pane is replaying.

  **One-click trading is now an explicit armed mode, off by default (`71d293e91`)**. A click on the chart used to send a live market order with no confirmation and no way to switch that off. Disarmed, the same click opens an order ticket prefilled with what the chart would have sent. Arming gates new risk only: closing a position, cancelling an order and dragging one to a new price work either way.

  Also: watchlist and option chain side panels (`f132e41f2`), a watchlist that chooses its own columns and symbol display (`7de2819d7`), replay start-bar selection that live ticks cannot corrupt (`c6afaf6f0`), copy as well as save from the camera (`dba8b659c`), a drawing tool that can stay armed, Delete removing the selected drawing, and a double-click that maximizes the pane instead of resetting the view and quietly fetching another page of history (`be23baa89`). The user guide gains a chapter: [32 - Charting Terminal](../userguide/32-charting-terminal/README.md).

* **Kotak Neo historical data (`44c488c25`, #2008, #2010)** - the plugin previously served no historical data at all: `get_history` was a placeholder returning an empty frame and the interval lists were empty. It now serves 1m, 3m, 5m, 10m, 15m, 30m, 1h, D and W across NSE, BSE, NFO, BFO, NSE_INDEX and BSE_INDEX, as a direct REST integration on the shared pooled HTTP/2 client rather than a wrapper around the vendor SDK.

  Three behaviours were measured against the live API rather than taken from the specification. Kotak publishes no historical rate limit, but the endpoint returns HTTP 429 after roughly five requests in a second, so requests are paced at four per second by a module-level limiter - module-level because `history_service` builds a fresh `BrokerData` per request and Historify runs concurrent workers that would otherwise burst - with a 429 retrying the same request rather than falling through to another candidate. An empty range arrives as a **400 fault**, not an empty success, under two different messages, so a pull whose last chunk landed on a weekend or on today before the open used to abort entirely. And index names are matched case-sensitively here and disagree with the quotes endpoint: INDIAVIX answers to `INDIA VIX`, not `India VIX`.

  **MCX and CDS have no historical data on Kotak.** The API refuses every contract in those segments with `Historical data is not supported for this exchange`, confirmed across four commodities and three segment spellings, so OpenAlgo rejects the request with a clear error before sending it rather than returning an empty series that would read as a market holiday. Both segments continue to work for quotes, depth, orders and streaming. Open interest is not populated in Kotak's current phase, so the `oi` column reads 0.

  Verified against a live session: a two year 1-minute pull returns 184,595 candles across 497 trading sessions with no duplicates and no gaps at the chunk seams.

* **Kotak Neo account data (`41fc1e52e`, `45fb2d7bc`, `05a137423`, `1bedf5ab5`, `4152451bf`, #1971, #1973, #1955, #1730, #1961)** - positions backfill their LTP through batched multiquotes, realized P&L is reported for fully-closed positions, `availablecash` reports cash only rather than including collateral, the scripmaster fallback accessibility check uses a ranged GET instead of HEAD, and multiquotes are batched at 25 with failed sub-batches isolated so one bad symbol cannot empty the response.

* **Broker fixes** - Fyers HSM WebSocket authentication timeout (`41f9e4f12`, #1950); Shoonya abandoned WebSocket clients leaking sockets and threads (`4ec984cec`, #1988) and `get_history` raising on session errors instead of returning an empty success (`5806b8a16`, #1952); mstock dropped subscribes recovered and dead tokens stood down on (`fb58d0615`, #1983), plus order handling, batched WebSocket subscribes and the one-off quote socket closed on every exit path (`9c129feb6`, #1974); Upstox sending price and trigger price only where the order type allows (`5390dcd89`, #1966); Flattrade's order socket no longer evicting the market-data feed (`4152451bf`, #1961); and the underlying picker no longer showing company names on cash exchanges (`a0e372acc`, #1989).

* **Docker base images move off EOL bullseye to trixie (`a7fc508a9`, #2004)**.

---

**Dependencies**

* **New**: `litellm==1.99.0`, `agno==3.0.5` and `ddgs>=9.16.0`, all for the Agent module
* `openalgo-charts`: **1.8.2** to **2.0.2**
* npm and pip advisories flagged by Dependabot patched (#1968)
* Routine patch bumps across the pinned Python set (`cryptography`, `SQLAlchemy`, `APScheduler`, `pyzmq`, `python-socketio` and others)
* The pinned `openalgo` SDK stays at **2.0.3**

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; the Strategy Module and RMS in full, including the risk core, signal mode, webhook, scheduler, crash recovery and the order-path safety work (#1976); the OpenAlgo Agent, including ChatGPT subscription support (#1997); the charting terminal upgrade to openalgo-charts 2.0.2 with the bottom dock, armed one-click trading, side panels and the user guide chapter; Kotak Neo historical data (#2008, #2010); retirement of the legacy `/strategy` module.
* **@Kalaiviswa** - Fyers HSM WebSocket authentication timeout (#1950); Shoonya socket and thread leak (#1988) and `get_history` session errors (#1952); mstock dropped subscribes and dead tokens (#1983), order handling and quote socket cleanup (#1974); Upstox order-type price fields (#1966); Flattrade order socket evicting the market-data feed and Kotak multiquote batching (#1961); Flow strike offsets and QA fixture cleanup (#1953); the underlying picker on cash exchanges (#1989); Kotak follow-ups (#1985); Dependabot advisory patches (#1968).
* **@arsalanansari17** - Kotak LTP backfill for positions via batched multiquotes (#1973); realized P&L for fully-closed positions (#1971); `availablecash` reporting cash only (#1955); ranged GET for the scripmaster fallback check (#1730).
* **@aravindgandavadi (Aravind Gandavadi)** - Docker base images moved from EOL bullseye to trixie (#2004).

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull request this cycle. The Kotak historical data work in particular came directly from #2008 and #2010, and the market-feed deprecation raised in #2010 is next.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
