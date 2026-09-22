# Changelog

All notable changes to OpenAlgo will be documented in this file.

Each release adds a stanza here summarising what changed and who contributed.
The full notes for a release, with commit SHAs and the reasoning behind each
fix, live in [docs/releases](releases/).

## [Unreleased]

- Run OpenScript strategies on engine 0.5.0. The compiler in the browser had been at 0.5.0 while the engine that runs the result was pinned to 0.4.0, because 0.4.0 was the only release on the index. Nothing was broken by that: the two agreed on the compiled program format, which is what actually has to match and is 1.1 in both. What was wrong was the note beside the pin claiming the halves were one release while they were not, and they now are. Both strategies on this install load unchanged in the new engine.

- Upgrade `/trading` to the published openalgo-charts 2.4.5 package, with 105 built-in studies, open interest readouts and chart alerts. Open interest is a level: aggregation keeps the last reading rather than summing values. Missing live readings remain absent.
- Add saved chart workspaces, study templates, comparison symbols with price or percentage scales, and CSV downloads of the displayed bars, studies and comparisons.
- Share one toolbar across the selected chart and one replay transport across the workspace. Replay can follow the selected chart or all charts on a shared clock; order actions and workspace autosave pause until replay ends.
- Preserve drawings, study settings, comparison scale preferences and alert lifecycle state when restoring a workspace. Alerts default to completed-bar evaluation and do not fire from restored history; delivery remains the host's responsibility.
- Move the alert list out of its modal and onto the right rail, with a Log tab of what has fired.
- Make an alert by right-clicking the chart at the price to be watched: it is created there and then, with no form, armed to fire once on a confirmed bar. The toolbar's Alerts button opens the form for one that needs a condition, a trigger or an expiry the defaults do not give it. Both seed from the same place, so the gesture produces exactly the alert the form would have proposed.
- Move the alert list out of its modal and onto the right rail, with a Log tab of what has fired this session.
- Make an alert by right-clicking the chart at the price to be watched: it is created there and then, with no form, armed to fire once. The toolbar's Alerts button opens the form for one that needs a condition, a trigger or an expiry the defaults do not give it. Both seed from the same place, so the gesture produces exactly the alert the form would have proposed.
- Choose per alert how to be told when it fires: a sound and a desktop notification, both on by default and neither leaving the machine, and Telegram or WhatsApp through the services order notifications already use, both off unless asked for. A channel that refuses names itself and the others still go.
- A chart with an armed alert keeps fetching while its tab is hidden. A chart with nothing armed still stops, which is the saving a background tab is for.
- Fill values into an alert's message from the bar that fired it: `{{ticker}}`, `{{price}}`, `{{close}}`, `{{interval}}` and seven more. A placeholder spelled wrong is left as typed rather than blanked.
- Upgrade `/trading` to openalgo-charts 2.4.8: press and hold the plot to pan, on both axes. The chart no longer pins mouse panning to the time axis, so dragging moves through price as well, and the choice is the trader's under Mouse drag in the Axes tab.
- Find an instrument whose name contains an operator character. The symbol search split its box on `-` to look up the second leg of an expression, so `BAJAJ-AUTO` searched for `AUTO` and typing the hyphen emptied the list. Both the whole box and the leg are searched now.
- Round a dragged alert to the instrument's tick, and rename it after the price its line landed on when the name was one we wrote. An alert dropped where the axis read 1,260.55 used to store 1260.5486842105263.
- Say "on" rather than "armed" on the One-Click toggle and the alert form.
- Upgrade `/trading` to openalgo-charts 2.5.0. An alert set on one timeframe is now visible on the others for the same instrument, labelled with the interval it was made on, and evaluated only there; the rail says why a visible alert is not watching rather than leaving it reading Active on a chart where nothing will fire. A dragged alert snaps to the source scale's own tick, including a left or independent scale. Chart tables measure each column from its widest cell, and every cell clips its text, so a long reading no longer covers the column beside it.
- Point at a drawing or an alert and press Delete or Backspace to remove it. The key removes one thing in a fixed order: a placement in progress is cancelled, then selected drawings, then the drawing under the pointer, and an alert last, because an alert's line spans the pane and would otherwise be deleted while you meant to delete a shape. A field or a dialog always keeps the key.
- Keep the alert log after the tab is closed. A firing is written to the database as it happens and read back when `/trading` next opens, so a browser closed at four o'clock no longer takes the afternoon's firings with it and an alert that fired on an unwatched screen still leaves a row. Each row names the channels that accepted the message, so a firing that reached nobody reads differently from one that never happened. Firings are kept for 90 days and Clear empties the log. Alerts are still evaluated by the chart that is open: this stores what happened, it does not make anything fire. **Requires a database migration.**
- Upgrade `/trading` to openalgo-charts 2.5.1 and stop drawing the line of an alert that has fired or expired. The row, the state and the record all stay: a once-only alert that has fired is still fired after a reload, so it cannot fire again on a price it already reported. Only the line goes, because a level nothing is watching is a level in the way. Deleting such an alert was never the answer, since this terminal restores an alert's definition and its runtime from separate places and a removed record comes back armed.
- Fire a new alert the moment its price is reached, rather than when the candle closes. A level touched at 13:15 on an hourly chart was reported at 14:15, and on a daily chart the next session, which reads as an alert that does not work. Bar close remains a field on the form for a level that only counts if it held, and an alert that already exists keeps the setting it was made with.
- Chart an instrument whose name contains a hyphen. `BAJAJ-AUTO` reads as a subtraction to the chart's grammar, so the chart asked the history API for `BAJAJ` and for `AUTO` and was told, correctly, that neither exists. An exchange now settles what the name cannot: a computed chart carries none and one instrument always does, so a named instrument is never taken apart. In the symbol box the same question is settled by whether an instrument of that name exists, so a box naming one is never treated as arithmetic and never has a symbol appended to it, and an exact match now outranks an index that merely contains the word. A hyphenated symbol put into a real expression is quoted, the chart grammar's own escape, so `'NSE:BAJAJ-AUTO'/NIFTY` resolves as written.

## [2.0.2.5] - 2026-09-14

### Voice Agent Release

29 commits since 2.0.2.4, excluding automated frontend build commits. Full
notes: [version-2.0.2.5-released.md](releases/version-2.0.2.5-released.md).

**This release requires a database migration.** Run
`cd upgrade && uv run migrate_all.py` after pulling.

### Highlights

- The agent at `/agent` gains a third surface beside chat and chart: a spoken
  one. The speech model hears and speaks and decides nothing; every answer it
  reads out comes from the model configured at `/agent/config`, through the same
  toolkits, the same risk guard and the same audit rows a typed question goes
  through. No audio passes through the server.
- Order placement by the agent is now opt-in. It shipped on, so a fresh install
  could reach an order tool by typing a sentence with nobody having chosen that
  (#2036).
- The charting terminal moves from openalgo-charts 2.1.7 to 2.2.0, exposing all
  85 drawing tools.
- The 5paisa XTS, Tradejini and 5paisa feeds survive a full symbol book, and
  Kotak depth payloads stop the trading chart polling REST (#2038, #2042, #2044).

### Added

- Voice surface on `/agent` and `/agent/config`, configured per installation
  with the provider credential stored in the database. `Permissions-Policy`
  relaxes `microphone` to `self` only while voice is enabled; an operator who
  sets `PERMISSIONS_POLICY` explicitly still owns the whole string.
- Every finalised spoken line is recorded under a `transcript` phase and
  rendered in the thread beside the messages a delegated turn produces. The
  first line of a session opens the thread, so a spoken-only exchange is no
  longer unreachable once it ends.
- A voice session with nobody speaking for three minutes hangs up, since an open
  microphone is billed for as long as it is open. The interval is a setting.
- The agent's spoken name defaults to Vega, chosen to sit far from an order
  instruction phonetically. An operator's own name is left alone.
- `upgrade/migrate_agent_voice.py` and
  `upgrade/migrate_agent_voice_phrase_removal.py`, both idempotent and both
  supporting `--status`.

### Changed

- Upgrade `/trading` to openalgo-charts 2.2.0 and expose all 85 drawing tools,
  including advanced channels, pitchforks, Fibonacci and Gann geometry,
  wavefronts and manual patterns. Saved drawing IDs and version 2 documents
  remain compatible.
- Drawing menu labels and glyphs follow the installed package through generated
  metadata, keeping the drawing renderer lazy. Registry checks catch omitted
  tools and stale metadata during future upgrades.
- Notes, balloons, comments, signposts, price notes and tables use the existing
  content editor. Tables explain column separators and multiline row entry.
  Font colours reach the rendered letters; content edits preserve table grids
  and theme defaults. Editors show only controls supported by each tool.
- The TPO chart display defaults to letters rather than letters and blocks. A
  stored choice is kept.
- The Objects button on the `/trading` right rail is a glyph in the same 32px
  box as every other panel, instead of its label spelled down the rail.
- The spoken approval phrase is removed. An order is approved by answering a
  full read-back, decided server-side, rather than by a configured secret word
  that had to be remembered, was read aloud by the speech model, and was written
  to the audit trail in plaintext.
- Every message the voice surface can put in front of someone names the cause
  and the next action in plain words, on the browser half too. No status codes,
  no protocol terms. The rule is recorded in `CLAUDE.md` under Conventions.
- Refresh the custom chart indicator skill and generated API index for 2.2.0.

### Fixed

- Restore **Time Price Opportunity** and **Session Volume Profile** in the
  `/trading` chart-type menu. Both can be selected again, with their existing
  settings, saved layouts, live updates and intraday interval handling.
- A spoken order request resolved the contract and then announced the order
  without calling the tool, so no pause, no approval prompt and no order, while
  the trader had just been told one was on its way.
- The voice surface could not draw. A spoken turn renders on screen exactly as a
  typed one does, so withholding `render_ui` removed the half of the answer the
  surface was designed around. `render_ui` also draws figures the operator
  supplied in their own message, titled so they cannot be mistaken for an
  account.
- The thread sidebar only ever listed chat threads, making every past voice
  conversation unreachable, and a spoken thread rendered typed turns above
  earlier speech.
- 5paisa XTS sent one blocking HTTP POST per symbol, so a 1000-symbol startup
  was 1000 sequential round-trips and every reconnect replayed the book the same
  way. Subscriptions are batched into one request per mode; every LTP and depth
  unsubscribe had been targeting the quote feed, and the tick filter compared an
  int against a string so it dropped every depth tick (#2042).
- 5paisa XTS `unsubscribe()` called `disconnect()` on every invocation, so
  dropping one symbol killed the feed for every other subscribed symbol, with
  nothing able to bring it back (#2042).
- Kotak dropped `ltp` from quote and depth payloads when the price was zero, and
  suppressed the mode 2 publish entirely. The trading chart subscribes depth
  alone for tradeable symbols, so a payload without the key read as "keep
  polling" and nothing could ever clear the REST fallback (#2038).
- Tradejini re-sent the complete symbol list once per symbol change, since a
  subscribe replaces the server-side list rather than appending to it. Feed
  syncs are coalesced into one request per feed (part of #1350, #2044).
- The 5paisa `last_snapshot` cache was never pruned, so it grew for the life of
  the Gunicorn worker and resurfaced stale prices on re-subscribe and across the
  3 AM token rollover (#2044).
- Ctrl+C on the development server printed a scheduler traceback every five
  seconds and needed several presses. Six APScheduler instances were never
  stopped, the websocket proxy thread was non-daemon with its cleanup registered
  through `atexit`, and the health collector slept its whole sampling interval
  in one call.
- The LiteLLM pydantic serializer warning no longer prints on every `chatgpt/`
  plan turn.
- Replace the retired YouTube subscriber badge in the README, and sync SDK pin
  references to 2.0.5 across the API and MCP architecture documentation (#2050).

### Contributors

- **@marketcalls (Rajandran R)** - the voice surface and everything that
  followed it, including order placement made opt-in (#2036), the removal of the
  spoken approval phrase and its audit-trail leak, spoken orders that place
  rather than being announced, drawing from the voice surface, transcripts
  captured and threaded, the idle hangup, the plain-language voice errors and
  the two migrations; openalgo-charts 2.1.8, 2.1.9 and 2.2.0 with the generated
  drawing metadata; TPO and session volume profile restored, the TPO letters
  default and the Objects rail icon; the Ctrl+C shutdown fix; the LiteLLM
  warning filter.
- **@Kalaiviswa** - 5paisa XTS subscription batching and the unsubscribe
  teardown, Kotak `ltp` in quote and depth payloads (#2038), Tradejini feed sync
  coalescing (part of #1350) and the bounded 5paisa `last_snapshot` cache
  (#2042, #2044).
- **@Ayush7614** - SDK pin references synced to 2.0.5 in the documentation
  (#2050).

## [2.0.2.4] - 2026-09-11

### Charting Profiles and Broker Correctness Release

37 commits since 2.0.2.3, excluding automated frontend build commits. Full
notes: [version-2.0.2.4-released.md](releases/version-2.0.2.4-released.md).

### Highlights

- The charting terminal moves from openalgo-charts 2.0.2 to 2.1.7 across four
  engine upgrades, adding TPO and session volume profiles, a per-pane Objects
  panel and the engine's data loading controller.
- The Upstox V3 migration is complete, with CAS data, shared rate limiting and
  WebSocket leak fixes (#2028).
- Kotak market data now streams over SFeed with per-data-centre routing (#2016).
- GTT history appears in the order book, and sandbox GTT no longer reports 501.

### Changed

- `/trading` drawings extend into empty chart space: a trend line, rectangle or
  freehand stroke that reaches past the latest candle or before the first loaded
  bar keeps its preview and commits where it was drawn, instead of disappearing
  mid-gesture. Magnet snapping still requires an actual candle, and saved
  drawings load unchanged.
- Mouse and pen plot drags pan time and price by default. Horizontal-only
  panning remains optional and preserves price autoscale; existing saved
  preferences stay intact. Dragging the time axis left expands candle spacing
  and dragging right compresses it. The bottom controls include Reset view, and
  Axes settings retain the default visible-bar preference.
- The profile entries were removed from the chart type menu, where they did not
  belong, now that profiles are their own studies.

### Fixed

- Upstox reported tick size in paise rather than rupees, so every tick-derived
  value was off by a factor of a hundred (#2026).
- The Upstox synthetic daily candle was stamped in host local time rather than
  IST, placing it on the wrong day for anyone not running in IST (#2030).
- Upstox multiquotes never populated `prev_close`, breaking percentage-change
  reporting wherever it was displayed (#1725).
- Kotak holdings did not report `average_price` (#2001), and tradebook fills
  were keyed on `order_timestamp` instead of `fill_timestamp`, losing per-fill
  `trade_id` (#2007).
- Samco kept reconnecting after a rejected session token (#2035), and a
  Flattrade WebSocket close stalled the reconnect (#1965).
- Groww tradebook prices are reported in the rupees Groww actually sends (#1995).
- Holiday checks now apply the requested date range (#1938).
- The central CORS policy is applied to blueprint decorators, which were
  bypassing it (#1927).
- Ctrl+C on the development server stops the health collector and releases its
  sessions before exit, so a stopped instance no longer keeps writing to
  `health.db` (#2031).
- `/trading` keeps price and volume isolated during replay when a periodic
  history refresh or an older history page completes. Leaving replay restores
  the updated live session. A refresh from an earlier symbol, interval or load
  is discarded, and a destroyed terminal cannot restart its refresh timer.
- Symbol loads that finish after switching instruments or closing a pane no
  longer overwrite the active history or rebuild a destroyed chart.
- Older history pages discard obsolete symbol, interval and chart responses
  without exhausting the new session or releasing another page's loading state.
- Closing a pane during interval lookup no longer starts its WebSocket and
  polling timer after teardown.
- Custom indicators wait for concurrent registration to finish before they are
  added or restored, preventing missing indicators during pane startup.
- Negative Net GEX values are abbreviated with K/L/Cr suffixes (#1911); SIP
  inputs are validated before prices load (#1884); backtester controls are
  labelled for assistive technology (#1877); the Docker installer no longer
  starts a container from a failed build (#2005).

### Security

- Cleared every open Dependabot advisory on the lockfiles. `npm audit` and the
  Python resolve both report no known vulnerabilities.
- GitPython raised to 3.1.62 (advisories through 3.1.58 cover config-injection
  RCE, arbitrary file read and git-directory creation). It arrives transitively
  through streamlit in the opt-in `analysis` group, so it never reaches a
  production install; the floor in `pyproject.toml` keeps the lockfile clear.
- maplibre-gl forced to 6.9.0 for the `DOM.sanitize()` XSS bypass. It is pulled
  in only to satisfy the `plotly.js` peer dependency of `react-plotly.js`; the
  app renders through `plotly.js-dist-min`, so the vulnerable code was never in
  the shipped bundle and is still absent from it.
- svgo raised to 4.1.0 (`removeScripts` sanitizer bypasses), vitest and
  `@vitest/mocker` to 4.1.11 (path traversal via the mocker redirect), and
  colord to 2.10.0 (slow rejection of malformed colour strings). All four are
  build and test tooling, not runtime code.

### Dependencies

- `openalgo-charts`: 2.0.2 to 2.1.7
- The pinned `openalgo` SDK: 2.0.3 to 2.0.5, with `requirements-nginx.txt`
  realigned after it was left a version behind
- `docker/login-action`: 3 to 4.5.2 (#1719)

### Contributors

- **@marketcalls (Rajandran R)** - release management; the charting terminal
  through four engine upgrades, TPO and session volume profiles, the pane
  Objects panel, the data loading controller and replay isolation; GTT history
  in the order book; ordered shutdown on Ctrl+C (#2031); clearing every open
  Dependabot advisory; the `chart-indicator` skill regeneration and its CI gate.
- **@Kalaiviswa** - the Upstox V3 migration and the Flattrade reconnect stall
  (#2028, #1965); Kotak SFeed market data (#2016); the Upstox daily candle
  stamped in IST (#2030); the Samco reconnect loop (#2035).
- **@arsalanansari17** - tradebook fills keyed on `fill_timestamp` with per-fill
  `trade_id` preserved (#2007); Kotak average price on holdings (#2001).
- **@anishkun (Anish kunda)** - Upstox tick size normalized from paise to rupees
  (#2026), and the root-cause analysis on #2029.
- **@linuxsmiths** - Upstox multiquotes never populating `prev_close` (#1725).
- **@nightcityblade** - holiday checks applying the requested date range (#1938).
- **@WilliamK112 (Ching Wei Kang)** - central CORS policy applied to blueprint
  decorators (#1927).
- **@vibecoding-skills (Harsh Dattani)** - Groww tradebook prices in rupees
  (#1995).
- **@srajbr (Samiran Raj Boro)** - negative Net GEX abbreviations (#1911).
- **@siddharthg2309 (Siddharth Gouthaman)** - SIP input validation (#1884).
- **@hafzism (Hafeez)** - backtester control labelling (#1877).
- **@aravindgandavadi (Aravind Gandavadi)** - the Docker installer no longer
  starting a container from a failed build (#2005).
- **@Mr-Neutr0n (hari)** - frontend test coverage for the Footer (#1964).
- **@Pragitics (Pragit R V)** - the strategy-builder Greeks tab awaited rather
  than queried synchronously (#1903).
- **@santhiprakash (Santhi Prakash)** - README quick-contribution example
  aligned with Conventional Commits (#1935).

## [2.0.2.3] - 2026-09-06

### Strategy Module, Agent and Charting Release

217 commits since 2.0.2.2. Full notes: [version-2.0.2.3-released.md](releases/version-2.0.2.3-released.md).

---

### Highlights

- **Strategy Module and RMS at `/strategy`** - multi-leg options strategies with stop loss, target and trailing stop per leg and in aggregate, driven by the live tick feed. Two kinds share one engine: `batch` enters and exits every leg together, `signal` moves one leg per alert, so a TradingView alert can trade a single leg. Kill switch flattens, crash recovery and checkpointing survive a restart mid-run, and the books are served from the broker rather than from stored rows
- **A broker-agnostic risk core in `services/risk/`** - decides stops, targets, trailing and aggregate limits, and performs no I/O of any kind, so it is exercised by golden vectors rather than a running platform. The four defects in the evaluator it replaced are each pinned by a test marked `PORTED DEFECT`
- **Order-path safety** - a claim is written under the same lock that checks it and before dispatch, a fill is matched to its order rather than to its leg, and a caller that has already resolved the pipe says so, so an analyzer toggle mid-run cannot send live exits to the sandbox. A stop whose exits were refused leaves the run open and managed
- **The OpenAlgo Agent at `/agent`** - an LLM assistant wired to OpenAlgo's service layer, reading order book, positions, holdings, funds, quotes, history, indicators, Greeks and payoff diagrams, and placing orders only when the operator turns trading on. Runs on any LiteLLM provider, or on a ChatGPT Plus or Pro subscription by OAuth device flow (#1997)
- **Charting terminal on openalgo-charts 2.0.2** - a bottom dock for orders, positions, trades and GTT across every symbol; one-click trading as an explicit armed mode, off by default; watchlist and option chain side panels; and a chart-side agent panel
- **Kotak Neo historical data** - the plugin previously served none. Now 1m to 30m, 1h, D and W across NSE, BSE, NFO, BFO, NSE_INDEX and BSE_INDEX, as a direct REST integration. MCX and CDS are refused by the broker and error clearly rather than returning an empty series (#2008, #2010)
- **Broker fixes** - Fyers HSM authentication timeout (#1950), Shoonya socket and thread leak (#1988), mstock subscribe recovery (#1983, #1974), Upstox order-type price fields (#1966), Flattrade order socket evicting the feed (#1961)

---

### Charting Terminal

- **One-click trading is now an explicit armed mode, and it is off by default.**
  A click on the chart used to send a live market order with no confirmation and
  no way to switch that off. Disarmed, the same click opens an order ticket
  prefilled with what the chart would have sent. Arming gates new risk only:
  closing a position, cancelling an order and dragging one to a new price work
  either way.
- **A bottom dock shows orders, positions, trades and GTT across every symbol.**
  Working orders and the open position previously existed only as lines on the
  charted symbol. Rows update live from the account order stream and reconcile
  against the broker book. Cancel, modify and per-position close act on one row;
  cancel all and close all sit behind a confirmation. Every write refuses while a
  pane is replaying.
- **A drawing tool can stay armed.** A padlock beside the magnet keeps the tool
  after a drawing instead of returning to the cursor.
- **The Delete key removes the selected drawing**, and brings duplicate and
  arrow-key nudge with it. The host never asked the drawing tier what a key
  meant, so only the rail button worked.
- **Alt+V and Alt+H arm the vertical and horizontal line tools only.** Both were
  bound twice, so one press moved a grid line and armed a tool. The grid stays on
  the toolbar button and the right-click menu.
- **A double-click on the chart no longer resets the view.** Reset fits every
  loaded bar, which lands on the oldest one and woke the history loader, so the
  gesture quietly fetched another page. It now maximizes the pane under the
  pointer, and a second press puts the stack back. Reset stays on the toolbar
  button, the right-click menu and Home. Double-clicking a text drawing still
  opens its editor.
- **Upgraded to openalgo-charts 2.0.2** from 1.9.2. Drawings saved by the old
  version are upgraded on load, with their text, styling and Fibonacci ratios
  intact.
- **CRYPTO is treated as a derivative segment**, so a Delta Exchange contract is
  offered NRML rather than CNC and takes quantity in lots.
- **The user guide gains a chapter for the terminal**, covering one-click, the
  dock, drawing tools and every keyboard shortcut:
  [32 - Charting Terminal](userguide/32-charting-terminal/README.md).

### WebSocket Proxy

- **A depth subscription is read under either key.** The proxy read the requested
  book depth from `depth` only, while the chart library sent `depth_level`, so a
  client asking for 20, 30 or 50 levels was served 5 with no error.

### Brokers

- **Kotak Neo serves historical data.** `get_history` was a placeholder returning
  an empty frame and the interval lists were empty. Now 1m, 3m, 5m, 10m, 15m,
  30m, 1h, D and W across NSE, BSE, NFO, BFO, NSE_INDEX and BSE_INDEX, as a
  direct REST integration on the shared pooled client rather than an SDK wrapper.
  Paced at four requests per second against a measured ceiling of five, with an
  empty range recognised as a 400 fault rather than treated as a failure
  (#2008, #2010).
- **MCX and CDS have no Kotak historical data.** The broker refuses both segments
  outright, so the request errors clearly instead of returning an empty series
  that would read as a market holiday. Quotes, depth, orders and streaming are
  unaffected.
- **Kotak account data** - positions backfill LTP via batched multiquotes
  (#1973), realized P&L is reported for fully-closed positions (#1971),
  `availablecash` reports cash only (#1955), and the scripmaster fallback check
  uses a ranged GET instead of HEAD (#1730).
- **Fyers** HSM WebSocket authentication timeout resolved (#1950).
- **Shoonya** abandoned WebSocket clients no longer leak sockets and threads
  (#1988), and `get_history` raises on session errors instead of returning an
  empty success (#1952).
- **mstock** recovers dropped subscribes and stands down on dead tokens (#1983),
  with corrected order handling and the one-off quote socket closed on every exit
  path (#1974).
- **Upstox** sends price and trigger price only where the order type allows
  (#1966).
- **Flattrade** order socket no longer evicts the market-data feed (#1961).

### Dependencies

- **New**: `litellm==1.99.0`, `agno==3.0.5`, `ddgs>=9.16.0`, all for the Agent
- `openalgo-charts`: **1.8.2** to **2.0.2**
- Docker base images moved from EOL bullseye to trixie (#2004)
- npm and pip advisories flagged by Dependabot patched (#1968)
- The pinned `openalgo` SDK stays at **2.0.3**

### Contributors

- **@marketcalls (Rajandran R)** - release management; the Strategy Module and RMS including the risk core, signal mode, webhook, scheduler, crash recovery and order-path safety (#1976); the OpenAlgo Agent with ChatGPT subscription support (#1997); the charting terminal upgrade to openalgo-charts 2.0.2 with the bottom dock, armed one-click trading and side panels; Kotak Neo historical data (#2008, #2010); retirement of the legacy `/strategy` module
- **@Kalaiviswa** - Fyers HSM authentication timeout (#1950); Shoonya socket and thread leak (#1988) and `get_history` session errors (#1952); mstock subscribe recovery (#1983) and quote socket cleanup (#1974); Upstox order-type price fields (#1966); Flattrade order socket and Kotak multiquote batching (#1961); Flow strike offsets and QA fixture cleanup (#1953); underlying picker on cash exchanges (#1989); Kotak follow-ups (#1985); Dependabot advisory patches (#1968)
- **@arsalanansari17** - Kotak LTP backfill via batched multiquotes (#1973), realized P&L for closed positions (#1971), `availablecash` as cash only (#1955), ranged GET for the scripmaster check (#1730)
- **@aravindgandavadi (Aravind Gandavadi)** - Docker base images from EOL bullseye to trixie (#2004)

## [2.0.2.2] - 2026-08-29

### Stability and Security Release

143 commits since 2.0.2.1. Full notes: [version-2.0.2.2-released.md](releases/version-2.0.2.2-released.md).

---

### Highlights

- **The eventlet boundary closed** - the "first order works, next one hangs the app" reports (#1402, #1473, #1569) were four defects: a real thread contending on a green lock, a green logging handler lock, `PRAGMA busy_timeout` waiting inside C while holding the hub, and `run_coroutine_threadsafe` never waking its caller
- **Broker credentials swept out of the logs** - 73 bare `logging.getLogger()` call sites bypassing redaction across 30 plugins, credentials interpolated into messages in 12 plugins, 35 sites leaking a secret inside a URL, payload, headers dict or exception message, and a defect in the `Bearer` pattern itself
- **Dhan symbol mapping routed orders to the wrong instrument** - 8,642 security ids resolved to two contracts each, and equity symbols ignored `SEM_SERIES` so an order could reach a warrant (#1929, #1930)
- **User chart indicators, loaded at runtime** - drop a `.js` file in `strategies/indicators/` and it appears in the `/trading` picker. No build step, no Node.js, no restart (#1923)
- **Motilal Oswal repaired and modernised** - every endpoint on its documented version, smart orders that can see a position, and four WebSocket leaks closed (#1912)
- **GTT extended to Angel One, Fyers and Upstox** (#1922)
- **Flow nodes stop acting on data they do not have** - conditions answered on failed broker reads, an errored condition settled a gate into a real order, and `httpRequest` had two injection paths
- **A fresh install clones 20 MB instead of 276 MB** - 165 MB of committed compression artifacts removed and all clone paths made partial (#1896, #1897, #1898)

---

### New Features

- User chart indicators in `strategies/indicators/*.js`, served by `blueprints/custom_indicators.py` and loaded after the built-in tier, with in-browser validation (#1923)
- Charting terminal: market replay, a settings dialog rendered from the engine schema, chart sync groups, a warm-load history cache, drawing undo and redo, and an indicator browser with categories, favourites and recents
- GTT order support for Angel One, Fyers and Upstox, each registering itself by shipping `api/gtt_api.py` plus `mapping/gtt_data.py` (#1922)
- Every Flow order field accepts a `{{reference}}`, not just `symbol`
- Flow schedule trigger exposes its market-hours window and calendar exchange; interval schedules anchor to the clock with `FLOW_INTERVAL_ALIGN_OFFSET`
- Flow supports MCX commodity options and leg-by-leg multi-leg baskets (#1904)
- Flow defaults to NRML on NFO, BFO, CDS, BCD, MCX, NCDEX and NCO rather than storing MIS on every node (#1909)
- TradeSmart tags placed orders as `openalgo` and gives quotes their own 100/sec budget (#1928)
- Motilal Oswal order-update WebSocket adapter, bringing `_BROKER_FACTORIES` to 17 (#1912)
- `chart-indicator`, `flow-builder` and `verify` skills

### Stability Fixes

- Four eventlet boundary crossings fixed via `utils/real_threading`, `Handler.createLock` patching, a green-thread callback drain and a Python-side SQLite lock retry (#1402, #1473, #1569)
- Subscribe acks resolve immediately instead of waiting out a 12-second timeout; proxy error replies now echo `request_id`
- Motilal Oswal: market-data socket pooled per session, cold-start registration race, duplicate poll threads and unbounded tick caches (#1912)
- Dhan `unsubscribe()` reaches the broker instead of only clearing local tracking; `dhan_sandbox` stops sending the invalid `RequestCode: 0` (#1924)
- A silent feed logs at debug rather than warning every two minutes outside market hours
- Test suite database isolation no longer depends on module import order

### Security Fixes

- Broker loggers routed through `get_logger` so `SensitiveDataFilter` applies: 73 call sites in 60 files across 30 plugins
- Credential values removed from log messages in 12 plugins, and from URLs, payloads, headers dicts and exception messages at 35 sites in 15 plugins (#1854, #1855)
- `SensitiveDataFilter` Bearer pattern extended to composite credentials, `cookie` added to the key alternation, and `utils/logging.py` given its first tests
- `CORS_ENABLED=FALSE` disables CORS instead of falling through to the flask-cors `origins="*"` default; the enabled-but-unconfigured case fails closed (#1848)
- Client error reports no longer persist a reset-password token or broker OAuth code into `log/errors.jsonl`, sanitized on both boundaries (#1851)
- The frontend fails a mutating request rather than sending it with no CSRF token
- Password login clears the session before writing any authenticated value

### Platform Fixes

- Option resolver validates the strike interval and option type, so a `strike_int` of 0 or an option type of "CALL" is refused rather than returning the put strike (#1829)
- Sandbox position book, MIS square-off and T+1 settlement boundaries resolved in the database clock rather than naive local time (#1789, #1801)
- Sandbox serializes concurrent same-symbol position updates (#1808)
- An out-of-range `SESSION_EXPIRY_TIME` falls back rather than silently disabling the MIS square-off
- `get_history()` rejects an unsupported source at the entry point (#1826); market calendar helpers return 400 for a non-string date (#1824)
- Multi-option Greeks batch state keyed by leg index (#1819)
- Frontend rate limiter expires calls at the window boundary (#1830)
- Navigation links declare `aria-current="page"` (#1833)
- Frontend compression artifacts generated at startup rather than committed, and all install paths use `--filter=blob:none` (#1896, #1897, #1898)
- Ten routine startup log lines moved from INFO to debug
- CI runs `backend-test` on Python 3.12, 3.13 and 3.14 and the frontend jobs on Node 20, 22 and 24 (#1894)

### Flow Fixes

- `priceCondition`, `positionCheck` and `fundCheck` check the broker response status, so a 401 no longer reads as LTP 0.0 with `status: success`
- An errored condition leaves its gate pending instead of settling it to `False` and driving a real order
- A condition reachable by two paths runs once; gates honour `inputCount`
- `timeWindow` crosses midnight; `waitUntil` over 30 minutes points at a schedule trigger
- Websocket subscriptions are tracked per workflow and released on deactivate or delete; a specific-mode `unsubscribe` no longer falls through to `unsubscribe_all`
- `httpRequest` resolves its URL once and after parsing, closing two injection paths
- Broker rejections surface their real reason instead of "node failed"
- Import format docs corrected on gate wiring, `marketHoursOnly`, `days`, strike offset ranges and `optionsMultiOrder.strategy`

### Broker Fixes

- Dhan: master contract gated on `SEM_SEGMENT`, NSE segment M mapped to NCO, symbols built from `SEM_SERIES` and `SEM_STRIKE_PRICE`, `securityId`-first position matching, and the inverted INTRADAY reverse mapping. **Breaking: 7,190 NSE equity symbols gain a series suffix** (#1929, #1930, #1932)
- Shoonya: `GetQuotes` refuses a quote echoing a different instrument, measured at 9% of replies on the live API (#1904)
- Angel and Zerodha: holdings return LTP and average price, and one null row no longer fails the whole call (#1917, #1919)
- Flattrade: pledged holdings reported as collateral from the `collateral` field rather than `brkcollamt` (#1936)
- Motilal Oswal: endpoints on their documented versions, correct API key and secret convention, client code persisted from the TOTP page, smart orders matching on `symboltoken` (#1912)

### Documentation

- Broker plugin counts synchronised to 36 across 17 files, the FAQ, the devsprint guide and the design docs (#1844, #1906, #1910)
- Documentation-only contribution workflow (#1846), completed CONTRIBUTING table of contents (#1883), contributor test commands aligned with CI (#1841), corrected frontend build and Node guidance (#1842), obsolete `/react` routes replaced (#1840)
- The eventlet boundary rules recorded in CLAUDE.md, both directions, with the threads that are genuinely real named
- Sandbox margin PRD states that short options are not SPAN margined (#1795)

### Dependencies

- `openalgo-charts`: **1.6.0** to **1.8.2**, pinned exactly rather than with a caret
- `zmq==0.0.0` removed from all three dependency lists: a placeholder package shipping no code, with `pyzmq` already pinned (#1895)
- No other Python dependencies changed; the pinned `openalgo` SDK stays at 2.0.3

### Contributors

- **@marketcalls (Rajandran)** - release management; eventlet boundary sweep and regression suites (#1402, #1473, #1569); broker credential redaction across 30 plugins; Dhan master contract, symbol construction, NCO and unsubscribe (#1929, #1930, #1932, #1934); runtime-loaded chart indicators (#1923); charting terminal 1.6.0 to 1.8.2 with replay, settings, sync, history cache and the indicator browser; Flow node-contract audit, payload-driven order fields and clock-anchored schedules; sandbox clock boundaries; Flattrade collateral (#1936); repository size work (#1896, #1897, #1898); Motilal Oswal WebSocket pooling; CI version matrix (#1894); test isolation; three new skills
- **@Kalaiviswa** - Motilal Oswal plugin repair (#1912); GTT for Angel One, Fyers and Upstox (#1922); Angel and Zerodha holdings (#1917, #1919); Dhan PRs (#1932, #1934); TradeSmart tagging and quote budget (#1928); Flow MCX options, multi-leg baskets and NRML defaults (#1904, #1909); Shoonya wrong-instrument quote guard
- **@santhiprakash (Santhi Prakash)** - sandbox position-book session boundary (#1789), MIS square-off boundary (#1801), concurrent position updates (#1808), Historify index cleanup (#1803)
- **@siddharthg2309 (Siddharth Gouthaman)** - history source allowlist (#1875), client error URL sanitization (#1886), `aria-current` navigation (#1880), option chain view mode coverage (#1876)
- **@solstxce** - API key redaction in core service logs (#1914), credential removal from broker logs (#1916)
- **@nightcityblade** - client errors for invalid calendar dates (#1861), CONTRIBUTING table of contents (#1883)
- **@WilliamK112 (Ching Wei Kang)** - documentation-only contribution workflow (#1907), rate limiter window boundary (#1868)
- **@ANONYMOUSZED-beep (Arun)** - `CORS_ENABLED=FALSE` honoured (#1860)
- **@Narasimha722 (NarasimhaReddy)** - option resolver strike interval and option type validation (#1829)
- **@Pragitics (Pragit R V)** - multi-option Greeks batch state by leg index (#1885)
- **@Meraj-08 (Md Meraj Alam)** - contradictory broker plugin counts eliminated (#1906)
- **@K-PRAGALATHAN (PRAGALATHAN K)** - history format script converted to pytest coverage (#1887)
- **@NavadeepDj (NavadeepDJ)** - type hints for the data schema validators (#1864)
- **@suhaslord (Suhas)** - contributor test commands aligned with CI (#1889)
- **@thaildhe172591 (Luu Thai)** - frontend build-artifact and Node guidance (#1863)
- **@yiheng-kkk** - obsolete frontend routes replaced (#1867)
- **@PadmaBalajiL (Padma Balaji Leelavinodhan)** - devsprint participants (#1814)
- **@cracker314** - devsprint participants (#1817)

---

## [2.0.2.1] - 2026-08-21

### Flow Release

25 commits since 2.0.2.0. Full notes: [version-2.0.2.1-released.md](releases/version-2.0.2.1-released.md).

---

### Highlights

- **Flow QA audit remediation** - one production QA audit and three re-audits validated finding by finding against source, then closed across triggers, the scheduler lifecycle, execution reporting, node contracts, the editor, the import format and the generated documentation
- **Logic gates repaired** - a `False` input never reached an AND/OR/NOT gate, so OR behaved like AND, NOT could never fire, and the result depended on traversal order
- **The editor stopped losing work** - a failed fetch rendered a blank canvas that the next save wrote over the real graph, clicking Activate discarded unsaved edits, and a save race let Run Now execute a revision the user was no longer looking at
- **Typed fields replace hand-written JSON** on the Indicator and Margin Calculator nodes, with Margin gaining a leg editor and lot-based quantity
- **Order nodes fail on unresolved variables** instead of placing a successful order for the wrong size at the wrong price type
- **Charting terminal: 20 to 91 built-in indicators** across `openalgo-charts` 1.1.0 and 1.2.0, with search in the indicator menu
- **The endless "Loading new version" reload loop** ended, along with the unsafe `Vary`-less asset representations behind it
- **Migrations got the app's 15-second SQLite lock timeout**, which they had never had

---

### New Features

- Flow Indicator node renders each indicator's real parameters as typed fields, generated from the `openalgo.ta` signatures
- Flow Margin Calculator gains a repeatable leg editor with lot-based quantity for NFO and BFO, backed by a batched `POST /flow/api/symbol-lotsizes`
- Flow execution history is bounded by `FLOW_EXECUTION_RETENTION_COUNT` (500) and `FLOW_EXECUTION_RETENTION_DAYS` (30)
- `reconcile_scheduler_jobs()` and `restore_price_alerts()` run at startup, so Flow triggers survive a restart and stale jobs are cleared
- Charting terminal indicator menu has a search box, filtering on display name and id
- `GET /python/api/exchanges` serves session windows from the market calendar DB
- Home page "One platform, many desks" section, with counts read from the code
- Devsprint contributor prep guide (#1804)

### Flow Fixes

- Price Alert node evaluates the editor's own condition vocabulary; a monitor-fired run carries the trigger price rather than re-fetching a quote
- Condition results are delivered into logic gates instead of being filtered by the branch taken
- Condition nodes return an error rather than a substituted `false`; `timeCondition` keeps its seconds
- Order-defining fields are checked for unresolved `{{references}}` before the broker call
- Modify Order reads the live order and changes only what was supplied; its editor default no longer ships exchange and action
- Close Positions honours its symbol/exchange/product filter; HTTP Request parses headers, supports PATCH, reads a millisecond timeout capped at 60s and refuses non-http(s), loopback, private, link-local and reserved destinations
- Fund Check and Position Check fail closed; Delay is capped at 300s
- One-shot triggers are spent only when the workflow actually ran, and clear `is_active` when consumed
- Duplicate-run guard is an atomic try-acquire; a node returning error stops its branch and marks the run failed
- Activation persists before registering and rolls back on failure; the API key is no longer pickled into the jobstore
- Output variable names on nine node types are persisted rather than shown as a fallback
- Basket Order and Margin node subtitles count the fields the editor actually writes
- `flow_workflows.api_key` migration ships for existing installations; `create_execution` stamps `started_at` and history orders by id
- Both Flow monitors release their pools, threads and bus subscription at exit
- Webhook lookups cache the workflow id rather than a detached ORM instance; secret rotation evicts the cache

### Platform Fixes

- Endless "Loading new version" reload loop, and `/assets/<file>` serving three representations of one URL with no `Vary` header (#1807)
- Forced upgrade header removed from `change-domain.sh` and the Ubuntu server design doc sample (#1807)
- Migrations use the same `PRAGMA busy_timeout=15000` as the app, via `upgrade/_pragmas.py` (#1726)
- `/api/v1/telegram` write endpoints repaired and `/notify` gated (#1577)
- MCP loopback health probe honours `MCP_LOOPBACK_URL` (#1441)
- Order latency recorded for routes outside the RESTX API (#1805)
- `/python` schedule prefill no longer cuts NFO and BFO strategies off ten minutes early

### Broker Fixes

- TradeSmart: WebSocket lifecycle aligned with its Noren siblings, interruptible heartbeat, close frames told from faults, rate limits corrected to 10/sec and 120/min, bulk quotes served from the WebSocket feed (#1805, #1802)
- Delta Exchange: the pooled feed stays alive after the last unsubscribe, so an option chain keeps delivering ticks across an expiry or strike change (#1799)

### Dependencies

- `openalgo-charts`: **1.0.29** to **1.2.0** (20 to 91 built-in indicators, VWAP and CPR session anchoring, frontend only)
- No Python dependencies changed

---

## [2.0.2.0] - 2026-08-14

### Brokers and Options Release

58 commits since 2.0.1.9. Full notes: [version-2.0.2.0-released.md](releases/version-2.0.2.0-released.md).

---

### Highlights

- **HDFC Securities InvestRight** - new broker plugin covering auth, funds, master contract, orders, quotes, depth, WebSocket streaming and the option tools
- **AliceBlue rebuild** - order-update feed repaired, market-data reconnect storm ended, session-long socket reuse, documented rate limits enforced, index symbology and daily history boundaries corrected
- **Option Chain live Greeks** - client-side Black-76 recomputed on every tick, with a Price/Greeks view mode (shortcut G) and `with_greeks` on `POST /api/v1/optionchain`
- **Strategy Builder repair** - valuation aligned with Black-76, exact listed-contract resolution, live-market freshness, and a run of payoff and forward-curve corrections
- **MCP hardening** - tool annotations, a single structured error shape, a trust envelope, and toolset/read-only filtering on both transports
- **Samco Trade API v3.2**, **Tradejini CubePlus v2**, and **Delta Exchange** market data moved to the public WebSocket endpoint
- **Derivative underlying normalized once** on the shared master-contract path, fixing options orders, expiry lists and the underlying dropdown for every broker

---

### New Features

- HDFC Securities InvestRight broker integration (#1784)
- Option Chain streams live Greeks with a Price/Greeks column-preset toggle
- `POST /api/v1/optionchain` accepts `with_greeks` and `interest_rate`, and returns `expiry_ts` and `server_ts`
- HalfTrend added to the charting terminal as the 20th built-in indicator
- MCP tool annotations, structured errors, trust envelope, and `OPENALGO_MCP_TOOLSETS` / `OPENALGO_MCP_READ_ONLY` filtering
- AliceBlue EC error codes expand into readable messages
- PnL Tracker splits PnL and drawdown into 3:1 panes

### Broker Fixes

- AliceBlue: order-update WebSocket token host, market-data reconnect storm, session-long socket reuse, 1800 req / 15 min rate limit, bounded symbol-lock registry, integer master-contract tokens, BSE historical data, daily history day boundary at midnight IST, index symbology and `::index` history routing
- Samco: migrated to Trade API v3.2; a stalled streaming worker is now always replaced on reconnect (#1783)
- Tradejini: realigned to the refreshed CubePlus v2 API docs (#1787)
- Delta Exchange: market data moved to the public WebSocket endpoint with batched subscriptions; expiry dropdown fixed - requires a master contract re-download (#1790)
- Definedge: no longer loses a full trading day at each history chunk boundary (#1790)
- All brokers: the derivative underlying root is normalized once on the shared master-contract path, fixing Fyers and any broker that ships a contract description in `name`

### Platform Fixes

- 23 unregistered React routes were feeding `Error404Tracker` and pushing logged-out users toward an automatic IP ban; Flask rules added
- Strategy Builder: Black-76 scenario valuation, aggregate horizons, exact listed-contract resolution, stale margin invalidation, WebSocket-bound freshness, closed-leg exclusion, and exact tick rounding (#1786)
- Strategy Builder payoff charts: one carry curve per strategy, forward converging to spot at expiry, no breakeven at an underlying of zero, x-axis no longer collapsing, and zoom preserved
- Flow: option lot size resolved without trusting `SymToken.name`; open strategy legs sort ahead of flat ones
- Greeks: parsed option expiry kept naive
- Charting terminal: screenshots include the readout and exclude the order buttons
- Option Chain: a hidden column now hides on both sides in one toggle

### Documentation

- WebSocket client connection limits clarified (#1764, #1788)
- Option Chain `with_greeks` documented, examples moved to 25AUG26

### Dependencies

- `openalgo-charts`: **1.0.28** to **1.0.29** (HalfTrend indicator, frontend only)
- No Python dependencies changed

---

## [2.0.0.0] - 2026-01-22

### Major Release: Complete Frontend Rewrite & Feature Expansion

This is a major release featuring a complete rewrite of the frontend from Flask/Jinja2 templates to a modern React 19 Single Page Application (SPA). This release includes **212 commits** representing months of development work, introducing new features like Flow Visual Builder, Historify, and enhanced real-time capabilities.

---

## Highlights

- **React 19 Frontend** - Complete migration of 77 templates to modern React with TypeScript
- **Flow Visual Builder** - Node-based visual workflow builder for trading automation
- **Historify** - Historical market data management with DuckDB storage
- **Real-Time WebSocket** - Native WebSocket integration for live market data
- **Sandbox Mode** - Enhanced sandbox testing environment with sandbox capital
- **API Playground** - Bruno-style API testing with WebSocket support
- **Python Strategies** - Enhanced scheduler with real-time status and resource limits
- **Telegram Bot** - Fixed callbacks and improved status display
- **Enhanced Security** - Multiple security improvements and vulnerability fixes

---

## New Features

### React 19 Frontend Migration (77 Templates)

**Phase 1 - Foundation**
- Initialized React frontend with Vite, TypeScript, TanStack Query
- Added Flask blueprint to serve React frontend
- Pre-built frontend dist included for community use

**Phase 2 - Core Authentication & Trading**
- Login, Dashboard, Profile pages
- Orders, Positions, Holdings pages
- Order placement and management

**Phase 3 - Search & Symbol Management**
- FNO Discovery with performance optimization
- Symbol search and watchlist
- Bulk watchlist operations

**Phase 4 - Charts, WebSocket & Sandbox**
- TradingView charts integration
- WebSocket Test Console
- Sandbox/Analyzer mode interface

**Phase 5 - Platform Integrations**
- TradingView webhook page
- GoCharting integration
- Amibroker integration
- ChartInk integration

**Phase 6 - Strategy & Automation**
- Python Strategies management
- Strategy scheduler with SSE
- Strategy logs viewer

**Phase 7 - Monitoring & Administration**
- Logs, Latency Monitor, Traffic Logs
- Profile & Security settings
- Action Center for order approval
- Admin & Telegram modules

**Frontend Tech Stack**
- React 19 with TypeScript
- Vite 6 build system with code splitting
- TanStack Query v5 for server state
- shadcn/ui + Tailwind CSS 4 + DaisyUI
- Biome.js (replaced ESLint)
- Vitest unit tests + Playwright E2E tests
- Responsive mobile bottom navigation
- Accessibility testing (jest-axe)

---

### Flow Visual Builder

- **Node-based visual workflow builder** for trading strategies
- **Order Nodes**: Market Order, Limit Order, Smart Order, Basket Order
- **Options Order Node**: ATM/ITM/OTM offset resolution for F&O
- **Modify Order Node**: Live order management within workflows
- **Cancel Order Node**: Cancel single or all orders
- **Close Position Node**: Square off positions
- **WebSocket Streaming Nodes**: Real-time data within workflows
- **Telegram Alert Node**: Send notifications from workflows
- **Webhook Integration**: Trigger flows from external systems
- **Multi-leg Options Strategy**: Execute complex option strategies
- **Keyboard Shortcuts**: Efficient workflow creation
- Service integration for order execution

---

### Historify - Historical Data Management

- **DuckDB-powered storage** for historical market data
- **Multi-timeframe support**: 1m, 5m, 15m, 30m, 1h, Daily
- **Computed timeframes**: Weekly (W), Monthly (MO), Quarterly (Q), Yearly (Y)
- **Aggregation from daily data** for higher timeframes
- **Bulk export** with inline symbol selection
- **Multi-timeframe export** in single operation
- **Parquet import support** for external data sources
- **TradingView-style charts** with IST timezone
- **Styled crosshair tooltips** with IST timestamps
- **Job management**: Pause, resume, cancel operations
- **Broker badge display** and theme toggle
- **Date selector improvements** with Calendar component
- **Exchange market open time alignment** for candle boundaries

---

### Real-Time WebSocket Integration

- **Native WebSocket** for Holdings and Positions pages
- **Unified WebSocket proxy server** on port 8765
- **ZeroMQ message bus** for high-performance data distribution (port 5555)
- **Connection pooling**: MAX_SYMBOLS_PER_WEBSOCKET (1000) x MAX_WEBSOCKET_CONNECTIONS (3)
- **MultiQuotes API fallback** when WebSocket unavailable
- **Market timing awareness** for automatic data source switching
- **Real-time P&L calculation** using live LTP data
- **WebSocket templates** in Playground with Bruno-style collections
- **Multi-client subscribe/unsubscribe** support
- **Callback-based data retrieval** for Flow nodes
- **Pong message display** for manual ping testing

---

### Sandbox Mode (Sandbox Testing)

- **Isolated sandbox trading** with Rs. 1 Crore sandbox capital
- **Realistic margin system** with leverage
- **Auto square-off** at exchange timings for F&O contracts
- **Complete isolation** from live trading
- **Separate database** (sandbox.db) for sandbox trades
- **Real-time P&L** using WebSocket data
- **Session-based position filtering** for expired contracts
- **Expired F&O contract cleanup** on app startup
- **Sandbox logs** with date filter and Calendar icons
- **Wide dialog display** (98vw) for better visibility

---

### API Playground

- **Bruno-style API collection browser**
- **WebSocket testing console** with comprehensive controls
- **CodeMirror JSON editor** with syntax highlighting
- **Theme support** matching application theme
- **Manual ping/pong testing** for WebSocket connections
- **Multiple tabs** for endpoints with same path but different names
- **Nested braces handling** in body:json parsing
- **Source parameter** for History API collections

---

### Python Strategies

- **Enhanced scheduler** with mandatory scheduling
- **Real-time status updates** via SSE (Server-Sent Events)
- **Resource limits** to prevent runaway strategies
- **Python Strategy Guide page** with comprehensive help
- **FAQ for installing libraries** (TA-Lib, pandas-ta, etc.)
- **Log management** with configurable retention
- **Reverse chronological logs** with auto-scroll
- **Schedule box theme** with opacity-based dark mode colors
- **Holiday enforcement** for market-aware scheduling
- **Environment Variables feature removed** (security)

---

### Telegram Bot

- **Fixed /menu callbacks** for command navigation
- **Fixed /status display** for current position status
- **Flow Telegram alert integration** using existing send_alert_sync
- **Admin & Telegram modules** migrated to React

---

### Email & SMTP

- **Fixed SMTP email delivery**
- **Updated email templates**
- **Email icon centering** using table-based layout

---

### Action Center

- **Order approval workflow** for managed accounts
- **Semi-Auto mode** for manual approval
- **Auto mode** for direct execution
- **Complete migration** to React interface
- **Documentation** added (Module 42)

---

## Improvements

### User Interface
- Profile menu with mode controls on all pages
- Theme consistency across broker and public pages
- Theme sensitivity for dark/light mode switching
- Broker badge display across pages
- Chart icons in watchlist for smart navigation
- Responsive dialogs with optimized widths
- Mobile bottom navigation
- Accessible icon buttons with aria-labels

### Performance
- FNO Discovery performance optimization
- Historify storage optimization
- Code splitting and lazy loading
- Bulk watchlist add optimization
- Connection pooling for WebSocket

### Order Management
- P&L % calculation for flat positions using implied investment
- Show dash for P&L % on closed positions
- Preserved realized P&L for closed positions
- Position filtering for session boundaries
- Show closed positions that were traded today
- Expired F&O contract cleanup on startup
- Order field names aligned with OpenAlgo schema

### Broker Integrations
- AliceBlue holdings symbol field fix
- OAuth broker redirect improvements (AJAX vs browser detection)
- Broker login migrated to React JSON responses
- Updated lot sizes and expiry dates in Bruno collections
- Broker credentials GUI for easy configuration

### Charts
- TradingView-style x-axis labels for daily+ timeframes
- IST timezone correction for W/MO/Q/Y timeframes
- Dates instead of time for daily+ timeframes
- CodeMirror JSON editor on TradingView and GoCharting pages

---

## Security

- Fixed critical frontend vulnerabilities
- Removed environment variables feature from Python strategies
- Added resource limits for strategy execution
- Enhanced CSRF protection
- Security audit documentation added
- Dependency updates for known vulnerabilities

---

## Documentation

### User Guide (30 Modules)
- What is OpenAlgo, Key Concepts, System Requirements
- Installation Guide, First-Time Setup
- Broker Connection, Dashboard Overview
- Understanding Interface, API Key Management
- Order Types, Smart Orders, Basket Orders
- Positions & Holdings, Analyzer Mode
- Symbol Format Guide
- TradingView, Amibroker, ChartInk, GoCharting Integration
- Python Strategies, Flow Visual Builder
- Action Center, Telegram Bot
- PnL Tracker, Latency Monitor, Traffic Logs
- Security Settings, Two-Factor Authentication
- Troubleshooting, FAQs

### Architecture Documentation
- Frontend and Backend Architecture
- Login and Broker Login Flow (Module 03)
- Cache Architecture (Module 04)
- Security Architecture (Module 05)
- WebSockets Architecture (Module 06)
- Sandbox Architecture (Module 07)
- REST API Documentation (Module 09)
- Flow Architecture (Module 10)
- MCP Architecture (Module 41)
- Action Center (Module 42)

### API Documentation
- All REST endpoints documented
- OpenAlgo symbol format reference
- Manual testing guide
- Bruno collections for all APIs

### PRD Documents
- Sandbox PRD
- Python Strategies PRD
- Historify PRD
- Broker Factory Design
- WebSocket Guide
- Latency Audit

### Other Documentation
- Why Build with OpenAlgo guide
- Ubuntu Server deployment
- Docker deployment guide
- Security Policy
- Contributor guidelines for /frontend/dist

---

## Infrastructure

### Database Architecture (5 Databases)
- `db/openalgo.db` - Main database (users, orders, settings)
- `db/logs.db` - Traffic and API logs
- `db/latency.db` - Latency monitoring data
- `db/sandbox.db` - Analyzer/sandbox mode (isolated)
- `db/historify.duckdb` - Historical market data (DuckDB)

### Server Configuration
- React frontend served via Flask blueprint
- Pre-built frontend dist for community use
- System permissions monitoring for db directories
- Ngrok ERR_NGROK_108 fix in debug mode
- Prevented duplicate startup messages
- Password reset fixed for React migration
- Startup log noise reduced (DEBUG level)

### Docker
- Updated .dockerignore for React frontend
- Added db directory to permission commands
- Frontend documentation included

---

## Dependencies

### Python
- DuckDB 1.4.3
- PyArrow 22.0.0
- FastParquet 2025.12.0
- simple-websocket 1.1.0
- Python 3.12+ required

### Frontend
- React 19
- TypeScript 5.6
- Vite 6
- TanStack Query v5
- shadcn/ui components
- Tailwind CSS 4 + DaisyUI
- Biome.js
- Vitest + Playwright
- CodeMirror 6
- Socket.IO Client

---

## Breaking Changes

- Frontend routes served from React SPA
- Old Jinja2 templates removed completely
- Static folder cleaned up (React has all assets)
- API responses updated for React JSON format
- Broker login returns JSON instead of HTML redirects
- Environment variables feature removed from Python strategies

---

## Migration Guide

For users upgrading from v1.0.0.41:

1. **Backup your data**
   - Export databases before upgrading
   - Backup .env configuration

2. **Update environment**
   - Python 3.12+ required
   - Node.js 20+ for frontend development

3. **Install dependencies**
   ```bash
   uv sync                    # Python dependencies
   cd frontend && npm install # Frontend (for development only)
   ```

4. **Database migration**
   - Existing databases are compatible
   - New sandbox.db created automatically
   - New historify.duckdb created automatically

5. **Clear browser cache**
   - React frontend requires fresh load
   - Clear all cookies and cache for the domain

6. **Review breaking changes**
   - Update any custom integrations using old template routes
   - Update broker login handling if using custom flows

---

## Contributors

Special thanks to all contributors who made this release possible:
- @Kalaiviswa - Flow Visual Builder, React migration
- @akhandhediya - WebSocket Playground
- Community contributors and testers

---

## Previous Releases

### [1.0.0.41] and earlier

See [GitHub Releases](https://github.com/marketcalls/openalgo/releases) for previous version history.

---

## Links

- **Repository**: https://github.com/marketcalls/openalgo
- **Documentation**: https://docs.openalgo.in
- **Discord**: https://www.openalgo.in/discord
- **YouTube**: https://www.youtube.com/@openalgo
