# Version 2.0.3.4 Released

**Date: 17th November 2026**

**One Alerts page for Telegram, WhatsApp, Slack and Discord; the Nuvama broker; four security fixes for the live Socket.IO channel, Telegram linking, broker postbacks and password resets; scheduled Flow workflows that keep running when the database is busy; a Latency Monitor that reports orders apart from data calls; Elliott wave counts and openalgo-charts 2.7.3 on every chart; and fixes for nine brokers.**

32 commits since v2.0.3.3, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.3.3 to 2.0.3.4.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds two
migrations, `migrate_alert_channels.py` (the `alert_channels` table) and
`migrate_password_reset_grants.py` (the `password_reset_grants` table).
`migrate_all.py` runs both, and both are required: if either fails,
`migrate_all.py` reports the failure and exits with an error instead of a
warning. Neither writes a row, so nothing is backfilled.

**Highlights**

- **One Alerts page, with Slack and Discord (`a455b2997`, #2435;
  `fdda2c211`, #2440).** `/alerts` puts Telegram, WhatsApp, Slack and Discord
  on one page. Each channel has a card with its status, an on/off switch, a
  test button and a link to its setup page, and a grid chooses which orders
  each channel hears about: orders placed, modified, cancelled, positions
  closed, basket/split/options orders and GTT orders. Slack and Discord post
  through an incoming webhook set up on `/slack` and `/discord`, with nothing
  to host and no bot token. The webhook URL is stored encrypted, never shown
  again and kept out of the logs; only Slack's or Discord's own webhook
  addresses are accepted, and an alert can never ping a whole channel.
  `POST /api/v1/slack/notify` and `POST /api/v1/discord/notify` post a
  message, like the Telegram and WhatsApp notify endpoints. Flow gains Slack
  and Discord nodes under Utility, the local and remote MCP servers gain
  `send_slack_alert` and `send_discord_alert`, and chart alerts on `/trading`
  can go to either channel. Each channel queues its own sends, so a slow or
  failing one never delays another. Telegram and WhatsApp alerts are
  unchanged for an install that never opens `/alerts`, except that GTT alerts
  on WhatsApp now name the symbol, the trigger prices, the trigger id and,
  when a GTT fires, the order it placed. The profile menu's Telegram Bot and
  WhatsApp Bot entries are replaced by one Alerts entry.
- **The Nuvama broker (`ee123273b`, #2461).** Nuvama (API Connect) joins the
  brokers with login, funds, master contract, orders (place, modify, cancel,
  smart order, cancel all, close all), quotes and 5-level depth, history,
  live market data, and order status updates from Nuvama's order stream.
  MARKET orders are sent as LIMIT priced off the last price with OpenAlgo's
  market price protection, and SL-M as a stop-limit priced off its trigger,
  because Nuvama refuses the forms it does not take. History is placed on the
  exchange session grid, so `/trading` can build 45m, 2h, 3h and 4h charts
  from it. Nuvama's API has no margin calculator, so OpenAlgo's margin
  calculator does not cover Nuvama.
- **Security fixes.**
  - **The live Socket.IO channel needs a signed-in session (`471e1ddf7`).** A
    client with no login could connect to the default Socket.IO channel and
    receive live order events, analyzer updates, the signed-in device list,
    scalping levels and the WhatsApp pairing QR code. It now needs a
    signed-in user whose broker session is still valid. The web app opens its
    socket only after a broker login, so nothing you use changes.
  - **Telegram `/link` checks this instance's API key (`81fe8eb41`).** `/link`
    asked the server named in the command whether the key was good, so anyone
    who found the bot could name a server of their own and be linked, and
    could then switch the platform between Live and analyzer mode or stop
    every running Python strategy. The key is now checked against this
    instance's own API key, and the mode buttons, `/mode`, `/stoppython` and
    the strategy stops check the link at every use.
  - **Broker postbacks need proof of their sender (`76ebb8593`).**
    `POST /postback/<broker>` is public, and for Dhan, Fyers, Upstox, Angel
    One and AliceBlue anybody who could reach the server could post a fill
    that never happened. The strategy engine applied it, and it could fire an
    order-placing Flow workflow. Postbacks from those five brokers are now
    refused; their order updates arrive through the order feed OpenAlgo opens
    itself at login. Zerodha's signed postbacks are accepted as before, with
    the signature now compared in constant time.
  - **A password reset works once and then lapses (`d2b08fc59`).** The server
    now records an approved reset, uses it up in the same step that writes
    the password, and lets it lapse after 15 minutes for a TOTP approval or
    one hour for an emailed link. Before, a copy of the reset cookie could
    set the password a second time. A reset also stops the old password at
    once, where it kept working for up to 30 seconds.
- **Scheduled Flow workflows keep running (`ceb116807`, #2355, #2326).**
  Every scheduled workflow could stop at the same moment and stay stopped
  until OpenAlgo was restarted, while the Flow page still showed them Active.
  An exit workflow that should have closed an open position was among those
  that did not run. A workflow run kept the database locked for writing for
  as long as it ran, and the write that then failed, the scheduler saving a
  next run time, ended the scheduler. A run now holds nothing while it works,
  and the scheduler keeps its schedule in memory while the database is busy,
  runs each workflow on time and once, and saves when it can. The Historify
  download scheduler has the same protection.
- **The Latency Monitor reports orders apart from data calls (`c46a4b19a`,
  #2421, #2286).** `/logs/latency` put every API call into one set of figures
  and called them orders, so a chart's history requests decided the "order"
  average: an install that had never placed an order could read "2,607
  orders tracked". The page now shows one group at a time (Orders, Account
  and books, Market data, Options, Symbols and settings, Tools and alerts,
  All calls), opens on Orders, and adds a By Endpoint table. The Excellent to
  Slow ratings and the share under 150 ms are shown for orders only. Options
  orders and options multi-leg orders were recorded under a misspelt name and
  deleted after 7 days like data calls; they are now kept like every other
  order, and those still on record are counted as the orders they are.
- **Elliott waves and openalgo-charts 2.7.3 (`afc3e133f`, `169bf19d2`,
  `12bb3069b`, `c16c52799`).** Every chart moves from openalgo-charts 2.6.9 to
  2.7.3. The drawing rail's icons are redrawn with an open ring at every point
  you place, and its Patterns group gains Elliott waves with five counts:
  impulse, correction, triangle, double combination and triple combination.
  Click the origin first, then the end of each wave; the waves are numbered
  from the second point, as a count is read, in the Intermediate degree.
  2.7.3 is a correctness release. On `/trading`: the price axis labels only
  prices the instrument trades at; a chart alert judges the bars a history
  refresh adds, so a crossing that lands during a refresh fires; a failed
  order book read no longer clears the order lines, and cancelling from an
  order line checks the broker's answer; a study timeframe the chart's own
  bars cannot be folded to (5 minutes on a 3-minute chart) is refused with a
  message instead of drawn from buckets of the wrong length; CPR, KAMA,
  HalfTrend, Renko on decimal boxes, point and figure, Kagi and the TPO and
  volume profiles are corrected; and charts with many studies update faster.
  OpenAlgo follows one change in the library's contract: when a saved study
  fails while a chart is rebuilt, the chart reports it and your saved studies
  stay in place, as before, instead of an empty list being saved over them.
- **Broker fixes.**
  - **Market price protection for cash symbols ending in CE or PE
    (`be6c3bbe4`, #2388, #2446).** 91 NSE and BSE equities, among them
    RELIANCE, BAJFINANCE, PRINCEPIPE and REDTAPE, were given the options
    protection slab: a MARKET BUY on RELIANCE at 1339.7 was sent at 1353.1
    (1%) instead of 1346.4 (0.5%). A symbol is now treated as an option only
    with the full option shape, and NSE and BSE are always equity. This
    covers every broker that converts MARKET or SL-M orders this way.
  - **Paytm Money stop orders (`6d3159f14`, #2404).** SL and SL-M fell back
    to MARKET and the trigger price was never sent, so a protective stop
    executed at once. They now go as Paytm's SL and SLM with their trigger,
    and one without a valid trigger price is refused before it is sent.
  - **Paytm Money cancels (`fc9403372`, #2374).** Only an order whose status
    read exactly "Pending" could be cancelled, so an open, trigger pending or
    modified order was left working and the cancel returned nothing. Those
    orders are now cancelled, and an order that cannot be cancelled, an
    unknown order id or a failed order book read each return an error saying
    so.
  - **Tradejini (`bf05a70af`, #2385, #2444).** A refusal Tradejini sent with
    HTTP 200 was reported as "Order Placed ... Order ID: None". A refused
    order now returns Tradejini's reason, and an accepted reply without an
    order id asks you to check the order book before placing it again.
  - **Fyers history (`5cbd69d72`, #2422, #2438).** A period with no candles
    (a weekend, a holiday, dates before listing) cost about 13 seconds and
    four requests; it now moves on at once. A real error, such as a wrong
    symbol, is reported instead of coming back as an empty result.
  - **Flattrade and Kotak margins (`4195b084c`, #2436; `192d2a3f1`, #2439;
    #2156).** The margin calculator now reports the basket's own margin:
    Flattrade's figure included margin already blocked by open positions and
    orders, and Kotak's added the account's existing usage once per leg. A
    basket with a failed or unknown leg returns an error naming it instead of
    pricing the rest, and a broker's rejection comes back as an error rather
    than a success.
  - **Sahi TOTP keys (`eb7ecc3af`, #2441).** Login with Sahi opens a short
    form with one optional field: for a TOTP key, type the code your
    authenticator app shows; for a Regular key, leave it blank and approve
    the key in Sahi's API Dashboard as before. Nothing about the TOTP is
    stored. A product the segment does not take is refused before sending,
    with the product to use, and AwaitingTrigger reads as trigger pending.
  - **Samco, 5paisa and HDFC Sky live data (`a1b9e3250`, #2397).** Follow-ups
    to the 2.0.3.3 feed fixes. Samco keeps a total of zero and routes a bare
    scrip code only within one segment. 5paisa keeps snapshots only for
    subscribed instruments, so its memory no longer grows. HDFC Sky sends
    subscribe and unsubscribe in the order they happen, honours an
    unsubscribe made during the handshake, no longer sends frames twice after
    a reconnect, and counts only new scrips against its 300-instrument limit.
- **Order tickets work right after an in-app broker login (`9d83c5de1`,
  #2417, #2423).** After signing in to 5paisa, Angel One, mStock, Tradejini,
  INDmoney, Firstock, Nubra, Motilal Oswal, Kotak, Definedge or Samco on
  OpenAlgo's own login page, the Place Order button on every order ticket
  stayed disabled until the page was reloaded. The session now loads at once.
- **A faster `/api/v1/instruments` (`ea90e4ffc`, #2406).** It is served from
  the in-memory symbol cache: about 90,000 NFO rows in 0.07 s where they took
  1.26 s, holding up every other page meanwhile.
- **MCP index quotes and expiries (`f456b3216`).** `get_quote` for SENSEX or
  NIFTY without an exchange looked on NSE and failed, and `get_expiry_dates`
  found no SENSEX expiries. An index now uses its index exchange, and the BSE
  indices' expiries come from BFO.
- **`rotate_pepper.py` on installs with their own `FERNET_SALT`
  (`a455b2997`).** It could decrypt nothing on such an install and still
  wrote the new pepper to `.env`, leaving every broker token, API key, TOTP
  secret, broker key and webhook unreadable. It now uses the install's own
  salt. If you ran it on such an install, the backup it made
  (`db/backups/openalgo.db.before-rotate-pepper-<time>`) still holds the data
  under the old pepper; restoring it also needs the old `API_KEY_PEPPER`
  back in `.env`.
- **Broker Configuration in dark mode (`ca83d3062`).** The open broker list
  was white with near-white names. It now follows the theme.
- **Documentation (`5f54059dd`, `440dee38f`, `3fc6dd8ed`, #1921).** The
  `/python` resource limits guide is rewritten from measurements: the memory
  cap is on address space, 512 MB is the practical minimum for a strategy
  that imports the SDK, and a strategy that uses up its CPU budget is ended
  with nothing in its log. The Docker guides no longer say `.env` is mounted
  read-only.

**What to check after upgrading**

- **Run the migrations and restart.** The update scripts run
  `migrate_all.py`. If you upgrade by hand, run
  `cd upgrade && uv run migrate_all.py`, then restart OpenAlgo.
- **A postback URL registered at Dhan, Fyers, Upstox, Angel One or AliceBlue
  no longer delivers updates.** Nothing has to be registered at those
  brokers: order updates arrive through the order feed that starts at login,
  unless `ORDER_UPDATES_ENABLED` is `FALSE`.
- **Telegram: send `/link` again** if the chat was linked before you last
  regenerated your API key; `/mode` and `/stoppython` ask for it. A link a
  stranger made before this release can no longer act on the server, but
  stays listed until you remove it on the Telegram page.
- **A password reset started before the upgrade** and not finished has to be
  started again.
- **The Latency Monitor's Orders figures will read differently,** usually
  with a lower count. They were not order figures before.
- **A Socket.IO client of your own** that connects to OpenAlgo's default
  channel now needs a signed-in session.
- **The Python SDK has no Slack or Discord method yet.** Call
  `/api/v1/slack/notify` and `/api/v1/discord/notify` directly until it does.
- **Not yet confirmed.** Nuvama's order status updates were checked against
  packets captured from a live order, but had not yet been seen on
  `/websocket/order` when they were merged. If they do not arrive, report it
  on the issue tracker.

**Dependencies**

- `dnspython` 2.9.0 to 2.9.2 (GHSA-vvf4-9x63-8xvv, high), `tornado` 6.6 to
  6.6.1 (GHSA-5cjw-f85j-cv6r, low) and `soupsieve` 2.9.1 to 4.1
  (GHSA-mmhr-3c5m-f64f and GHSA-6655-6qjp-jx7x, high; GHSA-7g44-g9rc-x53w and
  GHSA-4j63-6c4x-wfg4, medium), from `4ed17bde0`. Nothing in OpenAlgo imports
  any of the three. `soupsieve` is now pinned in both requirements files, so
  an Ubuntu server updated with `update.sh` moves to 4.1 as well.
- `openalgo-charts` 2.6.9 to 2.7.3 in the frontend. It reaches you in the
  built frontend; no Node.js is needed on the server.
- The pinned `openalgo` Python SDK remains 2.0.5.

**Contributors**

- **@marketcalls** - the Alerts page with Slack and Discord (#2435, #2440),
  the four security fixes, scheduled Flow workflows that keep running
  (#2355, #2326), the Latency Monitor groups (#2421, #2286), openalgo-charts
  2.7.0 to 2.7.3 with the Elliott waves, the MCP index fix, the
  `rotate_pepper.py` fix, the dependency updates, the dark mode fix, the
  documentation and the release.
- **@Kalaiviswa** - the Nuvama broker (#2461), market price protection for
  cash symbols (#2388, #2446), Tradejini refusals (#2385, #2444), Sahi TOTP
  keys (#2441), Fyers history (#2422, #2438), Flattrade and Kotak margins
  (#2156, #2436, #2439), order tickets after an in-app login (#2417, #2423),
  and the Samco, 5paisa and HDFC Sky live data follow-ups (#2397).
- **@Mystery01092000 (Pranav Tomar)** - Paytm Money stop orders (#2404) and
  the faster instruments endpoint (#2406).
- **@raghav-iit (Raghav Verma)** - Paytm Money cancels (#2374).
- **@santhiprakash (Santhi Prakash)** - the Docker records without read-only
  `.env` mounts (#1921).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
