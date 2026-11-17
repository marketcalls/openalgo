# Version 2.0.3.3 Released

**Date: 6th November 2026**

**Broker keys saved in OpenAlgo on the same screens as OpenAlgo Desktop, with one broker logged in at a time; broker logins that only OpenAlgo itself can start; live data fixes for fifteen broker feeds; corrected Shoonya and Historify history; an AI agent that works again on LiteLLM 1.106.6; and OpenAlgo Desktop, the Chrome Plugin and the Excel Add-in on the download page.**

20 commits since v2.0.3.2, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.3.2 to 2.0.3.3.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds one
migration, `migrate_broker_keys.py`, which creates the `broker_keys`,
`session_revocations` and `broker_login_states` tables, and extends
`migrate_strategy_module.py` to add `sm_strategy_run.broker_account`.
`migrate_all.py` runs both.

**Highlights**

- **Broker keys in OpenAlgo, on OpenAlgo Desktop's screens (`eec700046`,
  #2337).** You can save API keys for several brokers and log in to one at a
  time. Select Broker (`/broker`) shows a card for each broker, with search,
  its status (Active, Configured, Not Configured) and the buttons Login with,
  Configure, Edit keys and Open Dashboard. Broker Configuration
  (`/broker/config`) names each field the way that broker does, with a hint
  and a sentence on how its login works. Saved values are masked: an API key
  shows its first few characters and a secret shows none. Keys for any broker
  other than the one named in `.env` are stored encrypted in OpenAlgo and
  apply at once. **Installs that log in from `.env` need to do nothing.** The
  broker named in `.env` always logs in with the `.env` keys, and saving its
  keys on Broker Configuration writes them to `.env`.
- **One broker at a time (`eec700046`).** Login with another broker asks
  first ("End your <broker> session?"). The old session ends on every device
  only when the new login is stored, so a login that fails or that you
  abandon leaves the old broker connected and its keys unchanged. A switch is
  refused while the broker logged in now, or the one logged in last if you
  logged out, still runs Live automation: a Live strategy module run, a Live
  OpenScript run, or outside analyzer mode a Python strategy or scalping
  protection. Opening the dashboard from a second device (Open Dashboard)
  joins the session that is already open.
- **A Live strategy run trades only at the broker it started on
  (`eec700046`).** A Live run now records its broker, and its account where
  the broker names one, and every order, cancel and status check it makes goes
  there. Before, an exit could go to whichever broker was logged in when it
  fired: a short's cover sent to a new broker opened a position there and left
  the original one unmanaged. If you are logged in to another broker, the run
  stays open and managed and sends nothing until you log back in to its
  broker.
- **Broker logins only OpenAlgo can start (`eec700046`).** The login page
  now asks the server to start a broker login, and the broker's answer
  completes a login only if this OpenAlgo started it, once, and within ten
  minutes. Zerodha, Upstox and Paytm Money now send and require that check, as
  Fyers, Pocketful, CompositEdge, RMoney and IIFL Capital already did.
  Two defects are closed. Any broker request token that reached OpenAlgo
  while you were signed in completed a login. An answer posted to the
  CompositEdge or RMoney login page could sign the poster in to OpenAlgo with
  no password.
- **Account checks at login (`eec700046`).** OpenAlgo now takes the account
  only from the broker's own answer. A Dhan login is refused when the account
  is not the configured client ID, or when Dhan does not report the account.
  An RMoney or CompositEdge login is refused when the account is not the one
  your market data keys belong to.
- **Signing out reaches every copy of a sign-in (`eec700046`).** Logging
  out, changing or resetting your password, and switching broker now end the
  sign-in on your other devices too. OpenAlgo records each sign-out, so a copied login
  cookie stops working too. A sign-in that never reached a broker login ends
  at the daily 3 AM IST rollover. A page that opens before a broker login no
  longer signs you out.
- **A fresh download runs with `uv run app.py` alone (`eec700046`).** With
  no `.env`, the first start creates one from `.sample.env` with fresh
  security keys and no broker. It never does this when a database already
  exists. The server and Docker installers no longer ask for a broker, keys or
  redirect URL: add them on Broker Configuration. The installers also offer
  fail2ban for SSH (default No). Docker Compose now refuses to start when
  `.env` is missing, instead of creating a folder named `.env`.
- **Live data fixes for fifteen broker feeds.** Many broker feeds sent 0 for
  a field they never received, so a client computing the day's change against
  a previous close of 0 showed the whole price as the change. A field the feed
  does not carry is now left out instead. Each broker's fixes:
  - **Zerodha (`5372987aa`, #2347):** NSE_INDEX and BSE_INDEX quotes and depth
    now carry open, high, low, close and change. Before, they carried the last
    price only.
  - **Groww (`f5805220b`, `e2e31e91f`):** index subscriptions now receive
    ticks; before, they received none. MCX, NCDEX, NCO, CDS and BCD, which
    Groww's feed does not publish, are refused with a plain message.
  - **Dhan (`e2e31e91f`):** the previous close was 0 all session. It now comes
    from the previous-close packet Dhan sends on every subscribe.
  - **Angel One (`e2e31e91f`):** depth open, high, low and close were always
    0. Currency prices now use the divisor Angel's docs give (10,000,000, not
    100).
  - **Upstox (`e2e31e91f`):** the previous close was today's candle, which is
    close to the last price during the session. It is now the real previous
    close, and depth carries the full quote.
  - **Fyers (`abceace5e`):** a quote on a symbol that also had depth open
    showed a blank price, OHLC and volume. 50-level depth now carries the quote
    too. LTP and Quote on one symbol no longer replace each other, and a tick
    can no longer be delivered under another symbol.
  - **Kotak (`abceace5e`):** quotes and depth now carry average price, last
    quantity, total buy and sell quantity and OI, with the exchange's trade
    time instead of the server clock. Index ticks reach both NIFTY and
    NIFTY50.
  - **Sahi (`abceace5e`):** open, high, low, previous close and the other
    fields Sahi's stream does not carry are left out instead of 0.
  - **Definedge (`0faa9dbf3`):** with Depth subscribed first, a Quote
    subscriber on the same symbol received nothing. Every subscribed mode now
    gets each tick, and Quote carries OHLC.
  - **mStock (`0faa9dbf3`):** a token listed on two exchanges published one
    exchange's prices under both symbols.
  - **Tradejini (`0faa9dbf3`, `a92418967`, `f5805220b`):** total buy and sell
    quantity in quotes was always 0. Depth is sent only once both the quote
    and the book have arrived. The master contract download no longer fails
    on Tradejini's new ETF group. A subscription change that fails while
    connected is retried, and the feed no longer leaks sockets.
  - **Flattrade (`a92418967`, #2324):** after about seven minutes of network
    outage the feed gave up for the day, and only a restart brought it back.
    It now keeps retrying every 60 seconds until the broker is reachable.
  - **Samco (`8279621cd`):** the last trade time was the server clock. It is
    now the exchange's, and average price and total buy and sell quantity are
    published.
  - **5paisa (`8279621cd`):** depth frames published volume 0 to quote
    subscribers. Depth now carries OHLC, volume and average price.
  - **HDFC Sky (`8279621cd`):** partial packets were published as ticks with a
    last price of 0. Subscribing the same token on another exchange no longer
    takes over the first, and unsubscribing one mode keeps the others.
- **Shoonya intraday history (`0e4a488cc`, #2343).** When a 3m to 4h request
  spanned more than one trading day, the last candle of each day took the
  next morning's pre-open price as its high and close: NIFTY on 30 October
  closed at 23,222.30 instead of 23,053.10. OpenAlgo now rebuilds each day's
  last candle from 1-minute bars. 1m and daily bars were not affected.
- **Historify older history (`69ff02570`, #2310).** On 3m, 5m, 15m and 1h,
  scrolling the chart back past a session's opening candle failed with "Could
  not load older history". 1m was not affected.
- **Kotak holdings and margins (`eb4cce0a1`, #2365).** Holdings now show the
  OpenAlgo symbol: before, they were looked up by an id that is not in the
  master contract. A margin error now gives Kotak's reason instead of "Failed
  to calculate margin". The position average uses the precision Kotak gives.
  A delivery position carried overnight on NSE or BSE cash is valued at its
  holdings average price. Carried F&O is unchanged, because Kotak gives no
  cost for it (#2271).
- **The AI agent works again (`00314fb63`).** Since 2.0.3.2 moved to LiteLLM
  1.106.6, every agent turn failed on every model with "cannot import name
  'CacheableResult' from 'mcp.types'". The model test on `/agent/config` also
  failed for ChatGPT plan models. Both work again. A second, older fault is
  fixed too: opening `/agent/config` could leave every model test failing
  until a restart.
- **The download page lists all four OpenAlgo apps (`d629f3d57`,
  `b592e914f`).** These are OpenAlgo Desktop 1.0.5 (Windows, macOS and
  Linux), FastScalper Desktop 0.1.0, the Chrome Plugin 1.0 and the Excel
  Add-in 1.0.7 (Windows only). Each comes with what it does, what it needs and
  how to install it.
- **Documentation (`f34a121c3`, `da15d4641`, `a9370edf8`, `cf5a20132`).**
  The references now match recent platform changes, and new API references
  cover Portfolio, SIP and Sector Rotation. The `/tools` count is 20
  everywhere, and the README links the new explainer video. A new
  `python-strategy` skill lets Claude Code build, backtest and rehearse a
  strategy for `/python` with every order held back.

**What to check after upgrading**

- **Run the migrations and restart.** The update scripts run
  `migrate_all.py`. If you upgrade by hand, run
  `cd upgrade && uv run migrate_all.py`, then restart OpenAlgo.
- **Installs that log in from `.env` need no change.** Your broker keeps
  using the `.env` keys.
- **Live data clients may now find a field missing.** A quote or depth
  message from the WebSocket feed now leaves out a field the broker did not
  send, where it used to send 0. A script or tool that reads every field from
  every message should handle a missing one.
- **A broker login in progress during the upgrade will not complete.** Start
  it again from Select Broker.
- **Not yet confirmed against real accounts.** The RMoney and CompositEdge
  account checks, and the new login check for IIFL Capital, Upstox and Paytm
  Money, had not been tried against real accounts when they were merged. If a
  login to one of these brokers is refused after upgrading, report it on the
  issue tracker.
- **The broker switch check does not see everything yet.** It does not cover
  Flow workflows, queued Action Center orders or delayed external alerts.
  Finish or stop those before you log in to another broker.

**Dependencies**

- `joserfc` 1.7.4 to 1.7.7, used for remote MCP sign-in tokens
  (`eec700046`).
- `follow-redirects` 1.16.1 to 1.16.2 in the frontend, for advisory
  GHSA-mrwp-f3q8-3g9p (`89442ceec`). It reaches you in the built frontend; no
  Node.js is needed on the server.
- `litellm` stays at 1.106.6. A note beside its pin records why the agent
  keeps LiteLLM's MCP gateway out of its requests.
- The pinned `openalgo` Python SDK remains 2.0.5.

**Contributors**

- **@marketcalls** - broker keys, one broker at a time and the server-started
  broker login (#2337), the agent fix for LiteLLM 1.106.6, the download page,
  `follow-redirects` 1.16.2, the `python-strategy` skill, the documentation
  updates and the release.
- **@Kalaiviswa** - live data fixes for fifteen broker feeds (#2341, #2359,
  #2376, #2377, #2383, #2396), Flattrade's among them (#2324), Shoonya day-end candles (#2343, #2360), Zerodha index
  packets (#2347, #2361), Historify older history (#2310, #2358) and Kotak
  holdings and margins (#2365, #2367).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
