# Version 2.0.2.8 Released

**Date: 15th October 2026**

**Maintenance Release: moves the NSE index freeze limits to the values in force from 5 October 2026, so large index orders are split into fewer slices and NIFTYFPI stops borrowing NIFTY's limit; turns `/trading` into a full-screen terminal on openalgo-charts 2.6.4 with a slimmer toolbar, a foldable drawing rail, smooth wheel zoom and Renko and Point & Figure settings; makes the agent's tool calls work the first time on questions about several instruments and lets the `/trading` assistant place orders behind the same approval card as `/agent`; stops a cancelled sandbox closing order from crediting margin it never blocked; and brings master contract, history and order fixes for Groww, Flattrade, 5 Paisa, Firstock and Tradejini**

13 commits since v2.0.2.7, excluding the automated frontend build commits.
**This release requires a database migration** - run
`cd upgrade && uv run migrate_all.py` after pulling (the Ubuntu and Windows
updaters and a Docker restart run it for you). No `update.sh` run is needed for
anything else. The platform version moves from 2.0.2.7 to 2.0.2.8; the pinned
`openalgo` SDK stays at 2.0.5.

The change most traders will feel is the freeze limits. NSE circular
NSE/FAOP/76693 roughly doubled the quantity freeze limits for index futures and
options from 5 October 2026. OpenAlgo splits an order above the freeze limit
into several orders, and until this release every install kept splitting at
the old limits: more orders than needed, slower to complete, and more room for
the price to move between slices. The migration updates only a limit that
still holds a value OpenAlgo shipped or NSE published before, so a limit an
admin set by hand is left alone.

The second is the charting terminal, which now takes the whole screen. The
app's navigation bar is gone from `/trading` only; the Dashboard link, the
Live or Analyze badge, the mode switch, the theme toggle and the profile menu
sit in the terminal's own toolbar at every width.

The rest is the broker plugins, most of it from a QA audit of each broker's
master contract and history against OpenAlgo's documented formats, and two
master contract refreshes that could leave the symbol table empty after a
failed download.

---

**Upgrade notes**

* **Database migration.** `upgrade/migrate_qty_freeze_oct_2026.py` moves the
  index freeze limits to the 5 October 2026 values (`4dac2455f`, #2218). It is
  idempotent and supports `--status`. A limit set to something else on the
  Freeze Quantities page is reported and not changed, so check those against
  the table below. Run `cd upgrade && uv run migrate_all.py`, then restart.
* **`/trading` has no app navbar.** Use the Dashboard button at the left of the
  terminal's toolbar to go back. Nothing else about navigation changes.
* **The `/trading` assistant can now place orders** when **Allow the agent to
  place, modify and cancel orders** is on in `/agent/config`, with the same
  approval card as `/agent`. With it off, the assistant has no order tools, as
  before.
* **Agent: closing a flat position now says there was nothing to close**
  instead of reporting success, and an order on NSE_INDEX or BSE_INDEX is
  refused with the exchange its future or option trades on.

| Index | Old limit | New limit | New limit in lots |
| --- | --- | --- | --- |
| NIFTY | 1,800 | 3,510 | 54 |
| BANKNIFTY | 600 | 1,440 | 48 |
| FINNIFTY | 1,800 | 3,240 | 54 |
| MIDCPNIFTY | 2,800 | 5,760 | 48 |
| NIFTYNXT50 | 600 | 1,125 | 45 |
| NIFTYFPI | 8,500 | 53,900 | 49 |

---

**Highlights**

*Orders*

* **NSE index freeze limits from 5 October 2026 (`4dac2455f`, #2218)** - the six index limits above, in `data/qtyfreeze.csv` for new installs and through the migration for existing ones. NIFTYFPI gets a row of its own: its contract symbols start with NIFTY, so its orders were split at NIFTY's limit. The API reference examples show NIFTY's new limit.

*Charting terminal*

* **Full-screen terminal on openalgo-charts 2.6.4 (`c8ca0420c`, #2216)** - one slim toolbar band with borderless controls, a chevron on every control that opens a list, and a tint in the mode's colour on whatever is switched on. The drawing rail gains group carets, held-tool and magnet dots and a fold with a tab at the chart's lower left that is remembered. Every icon in the toolbar, rails, style bar and right-click menu is drawn at one fine line weight. Wheel and trackpad zoom move in one smooth motion and keep the latest bar at the right edge (Ctrl or Cmd zooms about the pointer), a logarithmic scale fills the chart again, and the chart colours are refreshed in Live dark, Live light and Analyze. With several charts open, the chart the toolbar drives is chosen from the layout menu.
* **Renko and Point & Figure settings on openalgo-charts 2.6.2 (`f2d28cd54`, #2215)** - a settings button beside the chart type for colours, box size and how it is measured (price, percent, ATR multiple or percent of ATR), the ATR length, the reversal, and close-only or high-low building. Settings are kept per instrument and chart type. The range buttons and Go to no longer report history as cut short when the only gap is a weekend, a holiday or the pre-open hours.
* **Generated glyph modules restored (`cfc5892ff`, #2217)** - the two icon files generated from the chart package had been reformatted, which failed the chart-indicator skill check in CI. They are regenerated and excluded from the formatter.

*Agent*

* **Reliable tool calls on `/agent` and `/trading` (`1dcfff58a`)** - questions about several instruments at once (history for TCS and INFY, expiries for crude, gold and silver) failed every tool call on the ChatGPT subscription models, because LiteLLM 1.104.0 dropped the details of parallel calls; the agent now recovers them. The `/trading` assistant can place orders behind the approval card, an approval card whose details did not arrive cannot be approved, and far more ways of writing dates, intervals, expiries, symbols and products are accepted. Weekly and monthly candles are built from daily ones on brokers that serve only daily, and the agent says so. The agent can write an OpenScript study or strategy and a Flow workflow from the skills in `.claude/skills/`, which it reads live.

*Sandbox*

* **Cancelling a closing order no longer credits margin it never blocked (`f07c112e9`, #2207)** - a sandbox order that reserved no margin, such as one closing an open position, used to fall back to recalculating a margin to release when it was cancelled, which raised available funds by an amount that was never taken. A zero reservation is now recorded as such and releases nothing; orders saved before this release are recognised by their position.

*Brokers*

* **Groww aligned with Groww's API documentation (`a0ae95bee`, #2194)** - SL and SL-M orders are sent with the order types Groww documents and SL orders carry their limit price; cancel and modify report success only when Groww confirms, and otherwise show Groww's own message; cancel finds the order's segment from the order book. The order book and trade book read every page, map the exchange from Groww's exchange and segment (stocks with a C or P in their name, such as ICICIBANK, were shown as NFO), cover every status Groww publishes, and no longer invent trades when Groww's trades call fails. In the master contract, indices are EQ rows on NSE_INDEX and BSE_INDEX, BSE F&O and NSE commodity symbols use the OpenAlgo format, bonds sharing a trading symbol are told apart, and SENSEX and BANKEX quotes and depth return data.
* **Flattrade (`0ca17af49`, #2196; `12e111465`, #2198; `76fb805be`, #2206)** - SENSEX and BANKEX daily charts load again; index rows are typed EQ; about 116 stale BSE rows with no exchange, which Flattrade rejects as invalid scrips, are dropped; history skips candles with missing or invalid prices, drops the 09:14 pre-open bar and floors the negative volume Flattrade reports in the closing session, any of which used to make the chart reject the whole history; an empty order book is no longer logged at info level. A failed master contract refresh now keeps the existing symbols instead of leaving a segment or the whole table empty.
* **Firstock and Tradejini (`12e111465`, #2198)** - a failed master contract refresh keeps the existing symbols and is reported as failed, where it used to empty the table and report success (the class of #2099).
* **5 Paisa (`0555c83cc`, #2195)** - 164 duplicate symbol and exchange pairs from repeated scrip codes are reduced to one, about 600 trade-for-trade (BE series) stocks are typed EQ so they appear in every equity filter, and a history request with no sessions in range returns nothing instead of today's candle.
* **Option symbols with special underlyings (`76fb805be`, #2206)** - the option Greeks parser accepts underlyings containing digits, ampersands and hyphens, such as M&M and BAJAJ-AUTO, and rejects a symbol with trailing text instead of silently reading part of it.

*Tests*

* **Two flaky gthread-migration tests fixed (`7bdd70e87`, `f34fd9006`)** - a shutdown marker cut off by a SIGKILL is read as not reached, a thread-leak check counts only the pools its own code builds, and a patched `time.sleep` stays inside the module under test instead of reaching every thread in the interpreter. The full gthread suite passes on Linux (1447 passed, 3 skipped).

---

**Still not modelled**

* On CompositEdge, 5 Paisa (XTS), IIFL, Wisdom Capital and Groww the smart order reads every position as flat even when the read works, so do not rely on it to adjust or close a position you already hold on those brokers.
* The agent's order risk check still charges a buy its full value, so a margin order on NFO, BFO, MCX or an intraday equity order can be refused when funds are short of the full notional.
* External data over MCP is built in the agent but no server is registered, so that section stays hidden on `/agent/config`.
* `braces`, used only by the frontend test tools, has an open advisory (GHSA-vfj7-8cjw-p6xm) with no patched release yet.

---

**Dependencies**

* `openalgo-charts`: **2.6.0** to **2.6.4**. No built-in chart id was added or removed, so custom chart indicators are unaffected.
* No Python dependencies changed. The pinned `openalgo` SDK stays at **2.0.5**.

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; NSE index freeze limits and their migration (#2218); the full-screen `/trading` terminal on openalgo-charts 2.6.4 (#2216), Renko and Point & Figure settings on 2.6.2 (#2215) and the restored glyph modules (#2217); reliable agent tool calls and chart orders on `/agent` and `/trading`; the two flaky gthread-migration test fixes.
* **@Kalaiviswa** - Groww alignment with Groww's API documentation (#2194); 5 Paisa master contract and history fixes (#2195); Flattrade BSE index daily charts (#2196), master contract, history hardening and refresh safety, with Firstock and Tradejini refresh safety (#2198); Flattrade order book log noise and option symbols with special underlyings (#2206); sandbox cancellation of zero-margin orders (#2207).

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull
request this cycle. The broker fixes in this release came out of a QA audit
that checked each broker's symbols, quotes and history against the formats
OpenAlgo documents, one finding at a time.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
