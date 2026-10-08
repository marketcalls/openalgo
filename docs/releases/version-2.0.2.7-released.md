# Version 2.0.2.7 Released

**Date: 8th October 2026**

**Feature Release: adds gunicorn's gthread worker as an opt-in web server beside the default eventlet, one `.env` line that gives every request its own thread from a fixed pool of 64, with a switch script that backs up, checks and rolls back by itself; carries `/trading` to openalgo-charts 2.6.0 and OpenScript 0.8.1 with a bottom bar, trading-hours axis, data window, chart-wide undo, right-click position actions and a backtest equity view; stops a smart order from doubling or reversing a position when the broker does not answer the position check; and closes four install defects that left Ubuntu servers with world-readable secrets, missing packages, a WhatsApp that logged out on restart and a Telegram /chart that never drew**

247 commits since v2.0.2.6, excluding the automated frontend build commits, 169
of them through the gthread branch (#2117). **This release requires a database
migration** - run `cd upgrade && uv run migrate_all.py` after pulling. **Ubuntu
servers should run `update.sh` once**, which installs packages earlier releases
missed and puts file permissions right. The platform version moves from 2.0.2.6
to 2.0.2.7; the pinned `openalgo` SDK stays at 2.0.5.

The headline is gthread. Since its first release OpenAlgo has run as one
gunicorn worker on eventlet, which makes the standard library cooperative by
patching it at start. That has served about 4,75,000 installs, and it stays the
default: an install that does nothing keeps its service file, nginx
configuration and dependencies exactly as they are, and an update never
switches it. gthread is the opt-in alternative. Every request gets a real thread
from a pool of 64, so a slow broker call, a SQLite write or a long stream holds
one thread rather than the whole worker, and the class of hang reported in
#1402, #1473 and #1569 (the first order working and the next one freezing the
app) cannot occur. Getting there meant auditing every module for code that was
only safe because eventlet never preempted it: sandbox fills, settlements,
alerts, Historify IDs, the Action Center, broker pacing and the strategy hosts
were each given a claim under the lock that checks, and the races were proved
with tests that fail on the old code. Where gthread has to refuse something
eventlet would have waited on, it answers with a sentence a trader can act on.

The second thread is the charting terminal, which moves to openalgo-charts
2.6.0 and gains most of what a trader expects from a desktop terminal: a bottom
bar with ranges and market status, a time axis that follows trading hours and
holidays, a data window, drawings that stay with their symbol, a price scale
menu, right-click position actions, undo for the whole chart, and backtest
equity and drawdown that show the whole run.

The third is safety. A smart order used to read a failed position check as "no
position" and size itself as if flat; it now sends nothing. Updates no longer
leave `.env` and the databases readable by every account on the server.

---

**Upgrade notes**

* **Database migration.** `upgrade/migrate_historify_sequences.py` gives
  Historify's watchlist, download and schedule IDs counters kept in its
  database, so two requests at once cannot take the same ID (`c15a6f178`). It
  is idempotent, supports `--status`, and the same check runs on every start.
  Run `cd upgrade && uv run migrate_all.py`.
* **Ubuntu: run `update.sh` once after pulling.** It installs `openscript`
  0.8.1, and `litellm`, `agno` and `ddgs`, which `requirements-nginx.txt` was
  missing on 2.0.2.6, so OpenScript strategies and the agent work on the server
  (`d86438a7e`, #2115). It installs a browser Telegram /chart can start
  (`d0d356f4b`, #2144) and sets `.env` and `db/` back to owner-only
  (`316e245b7`, #2165). Docker and the development server need none of this.
* **gthread is opt-in and nothing changes unless you ask.** To switch, add
  `OPENALGO_WORKER_CLASS = 'gthread'` to `.env`, then on Ubuntu run
  `sudo bash install/switch-worker.sh --to gthread` after 23:30 IST, or on Docker
  add `stop_grace_period: 45s` and recreate the container. The guide:
  <https://github.com/marketcalls/openalgo/blob/main/docs/gthread/README.md>.
* **Going back to an older release from gthread.** Run
  `sudo bash install/switch-worker.sh --restore` before checking out an older
  revision; it puts the saved service file back and sets `.env` to eventlet.
* **Smart orders now refuse when the position read fails.**
  `/api/v1/placesmartorder` answers an error and sends nothing when the broker
  does not answer the position check, where it used to place the full quantity.
  A caller that retried on failure keeps working; one that assumed every call
  sent an order should check the status.
* **OpenScript strategies that write a request's mode positionally** (the third
  argument of `req.timeframe`) should be opened and saved again in `/trading`,
  since the server runs the program saved with the script.

---

**Highlights**

*Optional gthread web server*

* **gthread beside eventlet (`58b86fcee`, #2117, 169 commits)** - `OPENALGO_WORKER_CLASS = 'gthread'` starts gunicorn through `install/openalgo-gunicorn.sh` with 64 threads, still one worker so Socket.IO state stays in process. `install/switch-worker.sh` backs up the service file, checks that OpenAlgo comes up, restores the old one if it does not, and refuses to restart during the trading day without `--force`. A service switched from now on starts on eventlet, as before the switch, if the launcher is ever missing (`a75065f7e`, #2166).
* **Races closed for every install (`4ae0fdc70`, `67d0f7693`, `729b3a913`, `1f9ac397f`)** - check-then-act sequences that only eventlet's lack of preemption made safe now claim under the lock that checks: sandbox fills and settlements, alerts, Historify IDs, Action Center approvals and broker pacing. When requests do not overlap the outcome is exactly as before.
* **A sentence instead of a hang** - under gthread, a broker rate limit that would hold a request past about 10 seconds answers 429 with nothing sent, a second order on a symbol still waiting after 30 seconds is refused, long-lived streams are capped, and a Flow workflow with long Delay or Wait Until steps runs in the background (`24a5d62c1`). None of this happens on eventlet.
* **Restarts bring things back** - running Python strategies restart after a gthread restart as after an eventlet one (`7eba2393a`), Chartink square-offs are restored (`ce4ae8e41`), the Docker market data proxy is restarted if it stops (`6ecc5e907`), and a gthread stop gives open requests 30 seconds with a 45 second Docker grace (`cdb3ac996`).
* **The admin Diagnostics page and system report** show which web server is running, the request threads free, and where the market data proxy runs.

*Charting terminal*

* **openalgo-charts 2.6.0 and OpenScript 0.8.1 (`07365e215`, #2162)** - Heikin Ashi, Renko, Range Bars and Line Break formed live from the time bars, Point & Figure and Kagi, a Timeframe row on 29 studies, seven new studies (112 built-ins), Anchored VWAP and Fixed Range Volume Profile, and side panels that load when first opened. OpenScript strategies reading a minute or hour timeframe now run on the server.
* **Bottom bar and trading hours (`49d6b2bd5`)** - ranges from 1D to All, Go to a date, Auto-fit, Log and Percent, market status and an IST clock; the time axis follows the admin's market timings and the holiday calendar, MCX evening session included.
* **Drawings (`49325de50`)** - drawings stay with the symbol they were drawn on, copy and paste across charts and tabs, an eraser, magnets and a properties bar beside the selected drawing.
* **Data window, price scale and undo (`349f5c9d0`, `94428f659`, `27f3cd25d`)** - bar and study values at the crosshair, a price scale menu with previous close, day high and low, bid and ask lines, and Ctrl+Z for drawings, studies, panes, scale, chart type and interval. Orders are never undone.
* **Right-click position actions (`27f3cd25d`)** - Cancel orders, Close position, Close half and Reverse from the chart, each confirming the symbol, side, quantity and product and saying whether it goes to the broker or the sandbox.
* **Quicker everyday work (`30cd188f7`)** - type a symbol or an interval straight onto the chart, four comparison scales, resizable grids, and clearer button labels.
* **Backtest equity and drawdown (`2128437c0`, `da4862762`, `5696cc13e`)** - results first, Equity, Drawdown and Trades tabs, the whole run on one screen however long, rupees grouped the Indian way, and one mark for a reversal.

*Safety*

* **A smart order no longer doubles or reverses a position when the broker does not answer (`e0a71720d`, `c27fe9cbf`)** - a failed position read now sends no order and says so, with the broker named. An empty book is still flat, and a read that works places exactly what it placed before. This covers `/api/v1/placesmartorder`, TradingView alerts, Flow, Python strategies and the Positions close button.
* **Secrets stay owner-only after an update (`316e245b7`, #2165)** - `update.sh` opened the install with `chmod -R 755` and never closed `.env` or `db/` again.
* **WhatsApp stays paired across restarts (`8a1461a0c`, #2167)** - the session is saved after each login, every 5 minutes and on stop; a real logout is reported in words and not retried on every start.
* **OpenScript Stop reports a close only when it is confirmed (`23b82be1f`, `ad6e6c2a5`)** - Stop cancels the run's working orders and counts their fills first, and says when it cannot confirm.

*Agent*

* **Reasoning on GPT-5.4 and newer works under eventlet (`0c9c46841`, #2081)**, the `/trading` assistant gets the same model picker as `/agent` (`cf161962c`), provider failures read as plain sentences (`0911830c2`), and LiteLLM 1.104.0 brings four new providers and the newest models (`ee26e4e24`).

*Brokers*

* **Angel One** - an empty or unreadable order response is recovered from the order book by its order tag instead of being reported as a rejection, and never resent; history requests use IST windows (#2176).
* **Kotak** - order tag support for the September 2026 API (#2145), then a unique tag per order, since a fixed one rejected every order after the first (#2178, #2177).
* **Zerodha** - in-flight statuses such as `OPEN PENDING`, `VALIDATION PENDING` and `TRIGGER PENDING` read as open, where they used to inherit the previous order's final status (#2185), and blank master contract names are filled from the trading symbol (#2123).
* **Fyers** - the TBT 50-level depth indexed by level number (#2122), `appId:accessToken` on the TBT socket and the published index names on subscriptions and in the master contract (#2139, #2140), index and government bond rows typed as EQ (#2124), and the existing symbols kept when a download fails (#2108).
* **Shoonya** - NSE stocks appear in symbol search again (#2164), and invalid history candles are repaired so intraday charts load (#2154).
* **Flattrade** - basket margin reported after hedging (#2156), with protected prices kept on the tick.
* **Groww** - position prices reported in the rupees Groww sent (#2173).
* **Feeds** - Firstock, Pocketful and RMoney subscriptions batched, a Pocketful watchdog (#2176), a data-stall watchdog for 5 Paisa XTS (#2155), and HDFC Securities publishing every subscribed mode (#2124).
* **Dhan sandbox** - well-formed candles so the chart loads, and an empty history instead of a crash (#2114, #2057).

---

**Still not modelled**

* On CompositEdge, 5 Paisa (XTS), IIFL, Wisdom Capital and Groww the smart order reads every position as flat even when the read works, so do not rely on it to adjust or close a position you already hold on those brokers.
* `/api/v1/openposition` and Flow's Open Position and Position Check nodes still read a failed read as no position on most brokers.
* The sandbox margin reconcile does not count margin held by open and trigger-pending orders.
* `braces`, used only by the frontend test tools, has an open advisory (GHSA-vfj7-8cjw-p6xm) with no patched release yet.

---

**Dependencies**

* `openalgo-charts`: **2.5.1** to **2.6.0**
* `openalgo-script` (npm) and `openscript` (PyPI): **0.5.0** to **0.8.1**
* `litellm`: **1.99.0** to **1.104.0**
* Security updates: `PyJWT` 2.15.1, `tornado` 6.5.10, `urllib3` 2.8.0, `Werkzeug` 3.1.9, `multidict` 6.9.1 (now pinned in the requirements files); frontend `axios` 1.20.0, `probe-image-size` 7.4.0, `source-map-js` 1.2.2, `postcss-selector-parser` 7.1.6, `katex` 0.18
* CodeMirror editor packages: `@uiw/react-codemirror` **4.25.4** to **4.25.12** with the CodeMirror 6 core
* The pinned `openalgo` SDK: unchanged at **2.0.5**

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; the gthread web server (#2117): the launcher and switch script, the audit and race fixes across core, sandbox, strategy, hosts, messaging, brokers and deploy, the trader-facing refusals and the guide; the charting terminal on openalgo-charts 2.6.0 and OpenScript 0.8.1 (#2162), the bottom bar, drawings, data window, price scale, right-click actions, undo and backtest equity; the smart order position read fix; OpenScript Stop confirmation; the install fixes for permissions (#2165), requirements (#2115), Telegram /chart (#2144) and the launcher fallback (#2166); WhatsApp session persistence (#2167); the agent fixes (#2081) and LiteLLM 1.104.0; the dependency security updates.
* **@Kalaiviswa** - Angel One ambiguous responses and IST history, Firstock, Pocketful and RMoney subscription batching (#2176); Zerodha transient order status (#2185) and master contract names with QA tool fixes (#2123); Kotak order tags (#2145) and the 5 Paisa XTS watchdog (#2155); Shoonya symbol search (#2164) and history candles (#2154); Flattrade basket margin (#2156); Fyers index names (#2139, #2140) and HDFC Securities modes (#2124); the Historify gthread audit (#2142); Dhan sandbox candles (#2114).
* **@vibecoding-skills (Harsh Dattani)** - Groww position prices in rupees (#2173); Fyers keeping its symbols when a download fails (#2108).
* **@arsalanansari17** - a unique Kotak order tag per order (#2178), which made every order after the first go through again.
* **@Azhagesan-dev (Azhagesan)** - the Fyers TBT 50-level depth indexed by level (#2122).
* **@samadarsh (Adarsh)** - the navbar no longer overflowing between the xl and 2xl breakpoints (#2119).

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull
request this cycle. The Kotak tag regression (#2177) came with the broker's own
error text and the change that caused it named, and arrived with its own fix
and test, and the gthread work rests on the hang reports in #1402, #1473 and #1569, each
of which described the symptom precisely enough to find.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
