# Version 2.0.2.6 Released

**Date: 23rd September 2026**

**Feature Release: brings OpenScript to the charting terminal, a language for writing studies and strategies that compiles in the browser, backtests beside the editor and runs on the server as one deployment per instrument; gives chart alerts a stored log, a choice of how to be told, and firing at the price rather than at the bar close; carries `/trading` from openalgo-charts 2.2.0 to 2.5.1 with chart arithmetic, workspaces and replay; and changes how Zerodha MCX quantity is counted, which every API caller trading MCX on Zerodha has to act on**

48 commits since v2.0.2.5, excluding the automated frontend build commits.
**This release requires a database migration** - run
`cd upgrade && uv run migrate_all.py` after pulling. **Zerodha users trading
MCX must re-download the master contract** and send MCX quantity in units (see
Upgrade notes below). The platform version moves from 2.0.2.5 to 2.0.2.6; the
pinned `openalgo` SDK stays at 2.0.5.

The release has three threads. The largest is OpenScript. Until now the chart
could run a study somebody had written as JavaScript, which is code the page
imports with the trader's session behind it. An OpenScript file is text a
compiler turns into a list of instructions an engine walks: a script can only
name what the language gives it, so there is no way to spell a network call or
a reach into the page. It is written in a panel on the chart, compiled on every
save with the diagnostic shown against the line, backtested in the browser
beside the editor, and run on the server as a deployment of one script on one
instrument and interval, so a closed tab does not stop a position.

The second thread is chart alerts, which gained everything they need to reach
somebody who is not looking at the chart: a sound, a desktop notification,
Telegram or WhatsApp chosen per alert, a log that survives the tab being
closed, and firing when the price is reached rather than when the candle
closes.

The third is the brokers. Zerodha now counts MCX quantity in units like every
other broker, an unconfigured freeze quantity no longer refuses every order on
MCX, BFO and CDS in the scalping terminal, and five Noren-based feeds that could
go silent while still answering heartbeats now notice and reconnect.

---

**Upgrade notes**

* **Database migration.** `upgrade/migrate_alert_log.py` adds the table behind
  the alert Log tab. It is idempotent and supports `--status`. Run
  `cd upgrade && uv run migrate_all.py`.
* **Zerodha MCX quantity is now in units (`cf27e5f98`, #1998).** Kite counts MCX
  orders in contracts, so one lot of crude was quantity 1 on Zerodha and 100 on
  every other broker. OpenAlgo now keeps one convention, units, and the Zerodha
  adapter converts at every Kite boundary. **A script sending MCX orders through
  `/api/v1/` on Zerodha must send 100 for one lot of CRUDEOIL, not 1.** Re-download
  the master contract after upgrading so the real lot sizes are stored. A
  quantity that is not a whole number of contracts is refused rather than
  rounded, since rounding down halves an order and rounding up doubles it. Until
  the master contract is rebuilt the stored lot size stays at Kite's 1, which
  sends one contract per lot exactly as before.
* **WhatsApp notify reports a send that reached nobody as an error
  (`1a7c785c7`, `e4b295f5a`).** `/api/v1/whatsapp/notify` used to answer
  `"status": "success"` with "Delivered to 0, failed 1". It now answers
  `"status": "error"` in that case. The HTTP code is still 200, and a send that
  reached at least one recipient is still a success, so only a caller that was
  trusting a failed send to have worked sees a difference.
* **Ubuntu server installs: install the OpenScript engine by hand.** The engine
  that runs an OpenScript strategy on the server is the `openscript` Python
  package, which is listed in `pyproject.toml` but not yet in
  `requirements-nginx.txt`, the file `install.sh` and `update.sh` install from.
  Docker and `uv run app.py` installs pick it up automatically. On an Ubuntu
  server, after `update.sh` finishes:

  ```sh
  sudo uv pip install --python /var/python/openalgo/.venv/bin/python "openscript==0.5.0"
  ```

  The package has no dependencies of its own. Writing, compiling and
  backtesting a script in the browser work without it; only starting a strategy
  on the server needs it.

---

**Highlights**

*OpenScript*

* **Write a study or strategy on the chart (`7444c57f6`, #2084)** - a Scripts panel on the `/trading` right rail. Every save compiles first and reports the whole diagnostic, its code, its line and its fix, with the gutter marking the line; a script that will not compile is still saved, because being halfway through a thought is not a reason to lose it. Syntax colours come from the language's own lexer, so a keyword added to the language is coloured the day it ships. A study written here gets its own section in the indicator picker, and the braces button on its legend row opens its source. Scripts live in `strategies/openscript/`, which is gitignored and inside the Docker volume, so an upgrade leaves them alone. They are served as plain text and never as JavaScript, and the security policy is unchanged.
* **Backtest a strategy beside the editor (`76c623724`, #2102)** - the engine that runs a compiled program is the same package that compiled it, so a backtest runs in the browser with no server call beyond fetching bars. The instrument and interval are the chart's, read at the moment Run is pressed. Equity and drawdown share one time axis. Tick and lot size are read from the platform, and when an instrument has no stored row the panel says which defaults the money figures rest on. A run past the bar ceiling is refused with the count rather than freezing the workspace.
* **Run a strategy on the server (`f11fcbea6`, #2100)** - a compiled strategy runs as its own process, so closing the tab does not stop a position. It places orders through the platform's own order path, so where they go is decided by the platform-wide analyzer setting exactly as for every hosted Python strategy; the runner has no switch of its own. If that setting changes while a run holds a position, the run stops at once and its log names what is open, rather than sending its exits somewhere its entries did not go. Starting one script twice at the same moment starts it once.
* **One strategy deployed on many instruments, with Pause, Stop and restart (`2aa4318ab`, #2103)** - a deployment is a script, an instrument and an interval, with its own order tag, book and position. Pause ends the process and leaves the position; Stop closes what the run holds and then ends it. A bar now closes on the tick stream rather than when history catches up, which was about thirty five seconds late on every fill. A strategy left running comes back after a restart and adopts a still-live process rather than starting a second beside it. Three defects were found on the way: every deployment showed the account's P&L as its own, switching between live and analyzer mode silently stopped every idle strategy, and running the test suite cleared the record of every live strategy.
* **A new deployment does not inherit a removed one's history (`6af9e2edb`, #2106)** - the id was derived from the script, instrument, exchange and interval alone, so a deployment made where another had been removed opened showing a day of trades it never made and a position it did not hold. Each deployment now carries a token of its own. Existing deployments keep the ids their orders already carry, and deploying the same script on the same instrument and interval twice is refused in words.
* **Engine 0.5.0 (`44e14593b`, #2107)** - the server engine now matches the browser compiler's release. Both already agreed on the compiled program format, so nothing was broken before; both existing strategies load unchanged.
* **A saved script appears in the indicator list without a reload (`2677f2ee8`)** - the picker built its catalogue on first open and never again, so a study saved from the panel was missing until the page was reloaded.
* **An `openscript` skill for Claude Code (`755947696`, `c5e22319c`)** - writes a `.oscript` file and installs it only after the pinned compiler accepts it, writing the source and the compiled program from one compile or neither. Ninety five of the language's 350 names are planned and not implemented, and the reference marks them. Three CI gates keep the skill in step with the compiler.

*Chart alerts*

* **The alert log survives the tab (`a2efe1cdf`, #2087)** - a firing is written to the database as it happens and read back when `/trading` next opens. Each row names the channels that accepted the message, so a firing that reached nobody reads differently from one that never happened. Kept for 90 days; Clear empties it. Alerts are still evaluated by the chart that is open: this stores what happened, it does not make anything fire.
* **Choose per alert how to be told (`7444c57f6`, #2084)** - a sound and a desktop notification, both on by default and neither leaving the machine; Telegram and WhatsApp through the services order notifications already use, both off unless asked for. Eleven placeholders such as `{{ticker}}` and `{{price}}` fill the message from the bar that fired it. A chart with an active alert keeps fetching while its tab is hidden.
* **Right-click the chart to make an alert (`7444c57f6`, #2084)** - created at the price under the pointer with no form, on the instrument's tick. The toolbar's Alerts button opens the form for an alert that needs a condition, a trigger or an expiry. The list moved from its modal to the right rail, with a Log tab.
* **An alert fires when the price is reached (`c61240645`, #2091)** - a level touched at 13:15 on an hourly chart used to be reported at 14:15, and on a daily chart the next session. Bar close is still one field away on the form. Existing alerts keep the setting they were made with.
* **A fired alert's line is no longer drawn (`402698272`, #2096)** - the row, its state and its record stay, so a once-only alert that has fired cannot fire again after a reload.
* **An alert refused by a channel says why, and channels send at once (`5a3dd6e3c`)** - every refusal used to arrive as one hardcoded guess about pairing; the server's own reason is now shown. Telegram no longer has to finish before WhatsApp starts.
* **The paired WhatsApp owner receives their own alerts (`1a7c785c7`, `5f2b5adfe`)** - an operator who had paired a device but never sent `/link` was told their own username was not linked. The owner recorded at pairing is now a recipient.

*Charting terminal*

* **openalgo-charts 2.2.0 to 2.5.1** - through 2.2.1 (`10bf61812`), 2.3.0 to 2.3.2 (`f31a7cd5a`, `3f74dcd9c`, `a7e6e1261`), 2.4.0 (`a0a684e28`), 2.4.5 (`621eaab62`), 2.4.6 to 2.4.8 (`7444c57f6`), 2.5.0 (`7e22dcbb9`, #2088) and 2.5.1 (`402698272`). The `chart-indicator` skill moved with every pin.
* **Chart arithmetic over instruments (`f31a7cd5a`, `50ca5004b`, `56983ed7b`)** - chart `NIFTY/RELIANCE`, `2*CE25000 - CE25200` or a straddle as one series, built from the symbol search with an operator keypad. A combined chart stays live with one LTP stream per leg. A computed chart is never tradeable: the order path refuses it by name.
* **The chart workspace (`621eaab62`, closes #2077)** - saved workspaces, study templates, comparison symbols on price or percentage scales, replay across one chart or all of them on a shared clock, CSV export of what is displayed, and open interest studies. Order actions pause during replay.
* **Candles repair from the stream (`a7e6e1261`, `3f74dcd9c`)** - a candle no longer vanishes for a few seconds after it closes, and each repair asks for the last five bars rather than the whole window.
* **An alert set on one timeframe is visible on the others (`7e22dcbb9`, #2088)** - labelled with the interval it was made on and evaluated only there, with the rail saying why it is not watching elsewhere. Delete or Backspace removes the drawing or alert under the pointer, in a fixed order that takes an alert last.
* **A hyphenated symbol charts (`c61240645`, #2091)** - `BAJAJ-AUTO` read as a subtraction, so the chart asked for `BAJAJ` and `AUTO`. An exchange now settles what the name cannot, and an exact match outranks an index that merely contains the word.
* **Pan through price as well as time (`7444c57f6`)** - the terminal had pinned mouse panning to the time axis; the choice is the trader's under Mouse drag in the Axes tab.
* **Historify charts rebuilt on openalgo-charts (`97fdeae16`)** - downloaded DuckDB data gets indicators, drawings, chart types and replay, with no order rows and no live feed. Monthly, quarterly and yearly intervals no longer crash the page, and a store whose newest candle is days old no longer opens empty.
* **Strategy Builder charts on the OpenAlgo engine (`9f4767d0d`, `ee0900e2e`)** - both chart tabs gain indicators, drawings and scroll-back history, and the strategy chart stays live. The history window is validated before any broker is called.
* **The agent draws a combined premium and studies it (`4dfe2568a`, `8986ba533`)** - "plot the combined premium of NIFTY current month straddles with a supertrend" now works, and "current month" resolves to the monthly contract.

*Brokers*

* **Zerodha MCX quantity in units (`cf27e5f98`, #1998)** - see Upgrade notes. Lot sizes come from the master contract row, so MCXBULLDEX's two live lot sizes are both right. Close-all now reports the symbols still held when an exit is refused, instead of always reporting success.
* **An unconfigured freeze quantity no longer blocks orders (`cf27e5f98`, #1998)** - a symbol with no freeze row returned a limit of 1, so the scalping terminal refused every order on MCX, BFO and CDS on every broker. It now returns 0, which every caller already reads as no limit.
* **The strategy wizard's underlying picker lists symbols (`cf27e5f98`, #1998)** - on cash and index exchanges it listed company names, and picking one stored a name that resolved to nothing.
* **Zerodha quotes carry best bid and ask size (`88c3a969e`, fixes #2045)** - they were absent rather than zero, so the option chain showed a confident 0 on every leg.
* **Kotak carried-forward positions (`d1dda9ca9`, `ac480e971`, #2061)** - valued at the uploaded price where Kotak sends one rather than the overnight settlement re-valuation. Where only the re-valuation exists, the row now says so in `average_price_basis`.
* **Kotak history (`efd516be8`, #2094, #2062)** - opening candles whose open fell outside their own range are widened, a market-wide negative volume on one closing candle is zeroed, a lookback at the five-year horizon no longer fails the whole pull, and requests are paced at the measured 1 per second.
* **Noren feeds that answer heartbeats but send no ticks now reconnect (`c0294d234`, #2089, #2075; `efd516be8`, #2094)** - Flattrade, Shoonya, Zebu, Tradesmart and Definedge. A heartbeat reply refreshed the liveness clock, so a feed could stay silently dead for the session with prices frozen and stop losses, sandbox triggers and Flow conditions not firing. Market data now has its own clock. The watchdog only starts once ticks have arrived across three separate 30-second windows, so the snapshot burst a feed sends outside market hours does not cause a reconnect every few minutes.
* **Delta Exchange history reads dates as IST (`a4cc86f9d`, #2074)** - a requested day ran 05:30 to 05:29 IST, and Delta filled the future half of it with flat synthetic bars.
* **A broker QA audit suite (`a4cc86f9d`, `c0294d234`)** - 364 checks run in sandbox and live modes, producing an xlsx report.

*Platform*

* **No Close button on a position already squared off (`3bc2f7251`, #2064)** - the frontend half of #2054. The row and its realised P&L stay; its zero quantity is no longer drawn in the short colour.
* **A spoken approval window closes when its run is decided or abandoned (`f579de58d`)** - an order read back and left alone stayed approvable for 30 seconds by a filler word said to something else.
* **Windows installers work without WMIC (`592507b0c`, #2080; `491deca07`; `2779fc7fc`)** - `update.bat` no longer misparses, stops if it cannot back up the databases instead of reporting a backup it did not make, and `docker-run.bat` sizes the container from the real RAM and core count rather than its lowest tier.
* **One word per state, wherever a trader reads (`8e0b869e4`, #2093; `c3762dba4`, #2097)** - the `/strategy` trailing-stop readout says trailing or pending, the One-Click toggle says ON, an alert is Active or Stopped, and a scheduled strategy is "scheduled to start". The platform's own words, and the ones it does not use, are now written down in `CLAUDE.md`.
* **Documentation** - Agno and LiteLLM credited in the open source acknowledgements (`c2a2ddf72`); a line-ending false failure in the OpenUI prompt test on Windows fixed (`9d031789a`).

---

**Migration**

This release adds one migration script, idempotent and supporting `--status`:

* `upgrade/migrate_alert_log.py` - creates the `alert_log` table behind the
  alert Log tab on `/trading`. A new table, so there is nothing to backfill.

Run it the usual way:

```sh
cd upgrade && uv run migrate_all.py
```

---

**Dependencies**

* `openalgo-charts`: **2.2.0** to **2.5.1**
* `openalgo-script` (npm, the OpenScript compiler): new, **0.5.0**
* `openscript` (PyPI, the OpenScript engine): new, **0.5.0**
* The pinned `openalgo` SDK: unchanged at **2.0.5**
* No other dependencies changed

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; OpenScript on `/trading`: the Scripts panel, the compiler integration and its colours, the backtest panel, the server-side runner and its destination guard, deployments with Pause, Stop and restart, deployment identity, engine 0.5.0 and the `openscript` skill; chart alerts: the stored log and its migration, per-alert channels and placeholders, right-click creation, firing at the price, the fired-line option, channel reasons and concurrent sends, and the WhatsApp owner fix; openalgo-charts 2.2.1 through 2.5.1 with the skill updated at each pin; chart arithmetic and live combined charts; the chart workspace (#2077); hyphenated symbols; Historify and Strategy Builder charts on the OpenAlgo engine; the agent's combined premium chart; Zerodha bid and ask size (#2045); Kotak carried-forward valuation (#2061); the spoken approval window; the WMIC-free installer fixes; the trader-facing wording sweep and the vocabulary rules.
* **@Kalaiviswa** - Zerodha MCX quantity in units, with the freeze quantity fix and the strategy wizard underlying picker fix (#1998); Kotak history repair and pacing (#2094, #2062); the heartbeat-without-ticks watchdog for Flattrade (#2089, #2075), Shoonya, Zebu, Tradesmart and Definedge (#2094); Delta Exchange IST history (#2074); the broker QA audit suite (#2074, #2089).
* **@anishkun (Anish kunda)** - no Close button on a position already squared off, and its quantity read as a number (#2064).
* **@nimchand87** - escaped parentheses in `update.bat` (#2080), which is what made the rest of that script reachable.

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull
request this cycle. Several fixes here exist only because somebody took the
trouble to report them with evidence: the Kotak carried-forward averages (#2061)
were settled by a raw payload attached to the issue, the silent Flattrade feed
(#2075) was found from a user's description of prices freezing while the
connection still read as live, and the freeze quantity defect was proved a
platform one by a user who switched broker to rule their own out.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
