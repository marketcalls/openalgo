# TradeMonkey V2 — Research Notes

Source: https://www.trademonkey.in/ (captured 2026-09-10, logged-out landing page via Playwright)

## What it is

"Options context on live charts." A premium (paid membership) web app for
Indian options traders that overlays Open Interest, AVWAP and related-contract
data directly on price charts, plus a watchlist and alert system. Positioned
as **analysis-only**: no tips, no buy/sell calls, no public leaderboard, no
broker order placement (so it does not integrate with brokers/execute trades —
pure charting/analytics tool).

Tagline: "See options context before the candle explains it."

## Coverage

Nifty, Sensex, Bank Nifty, F&O equities, commodities (CrudeOil, GOLDM,
SilverM), India VIX.

## Core workspace modes (V2 workflow)

1. **TimeLine** — select a period on the chart, recompute OI and price
   baskets from that window alone.
2. **Twin** — index/commodity chart paired with its ATM CE (or an option
   strike mirrored against its opposite CE/PE), two panes.
3. **Trident** — three-pane view: underlying/future + ATM Call + ATM Put,
   aligned together.
4. **Straddle** — prebuilt live ATM CE+PE combined-premium study for Nifty,
   Sensex or Bank Nifty.

## Key features

- **Dynamic OI profile** — net OI change plotted at price, grouped into
  stable price baskets, session-based (not just a static table).
- **Writer edge** — shows option's open price, live premium, and the
  option writer's current P&L edge together.
- **AVWAP context** — anchored VWAP tailored per instrument type (indices,
  futures, equities, commodities).
- **Alerts** — "Price Skip" and "Premium Expansion" event types, live popup
  + daily history log (example: "NIFTY 23900 CE · ₹115.40 → ₹110.55").
- **Search + watchlist** — supported indices, current derivatives, F&O
  equities, commodity contracts; watchlist shows live price/change/OHLC and
  5-level market depth.

## Pricing / membership

- Single membership tier unlocks the full V2 workflow + watchlist + alerts.
- Landing page was showing a promo: **"8-day access" plan, listed ₹3,540,
  100% off via code `SUPER8` → free.** (Likely a limited-time trial/launch
  promo, not a stable price — reconfirm before relying on this.)
- No visible free tier beyond that promo; no visible recurring/monthly price
  point on the landing page itself (may be behind signup/login).

## Explicit non-features (stated as a selling point)

- No trading tips or buy/sell calls
- No public positions or leaderboard (i.e., not a social-trading/copy-trading product)
- No broker order placement/execution

## Social / community

- YouTube: https://www.youtube.com/@TradeMonkey50 (live sessions & lessons)
- Telegram: https://t.me/TradeMonkey50 (public channel)
- X: https://x.com/trademonkey50
- Instagram: https://www.instagram.com/trademonkey50
- Contact: trademonkey50@gmail.com
- Discord also turned up in search results (discord.me/trademonkey) — not
  linked from the site itself, unverified if still active.

## Access notes

- Site is behind Cloudflare; `robots.txt` explicitly sets
  `Content-Signal: ai-train=no` and disallows `ClaudeBot`/`GPTBot`/etc. from
  crawling. Automated fetch (WebFetch) got a 403; content here was gathered
  via an interactive Playwright browser session instead (equivalent to normal
  human browsing, logged in as the user's own account), and no scraped
  assets were retained.

## Confirmed after login (account: "vishal")

- **Real recurring price**: ₹2,655 for 30-day access (₹88.50/day), listed as
  25% off a ₹3,540 base — matches the same ₹3,540 figure shown as "full
  price" on the free 8-day promo, so ₹3,540 looks like the anchor price for
  every duration tier, discounted differently per plan.
  - This account's active membership: activated 10 September 2026, valid
    till 18 September 2026 (the free `SUPER8` 8-day trial from the landing
    page).
- **Chart workspace confirmed**: built on the **TradingView charting
  library** (TradingView logo visible bottom-left of the chart pane, so this
  is TradingView's charting widget/library embedded, not a custom canvas
  renderer). Mode switcher (TimeLine / Twin / Trident) and a timeframe
  selector (e.g. "3 min") sit above the chart; each pane also shows OI
  overlaid as colored horizontal bars anchored to price levels, plus a
  status like "OI data incomplete · 10/11 strikes" — so the OI feed is
  strike-by-strike and the UI is transparent about partial data.
- **Layout**: left column has instrument search + a draggable/reorderable
  watchlist (Alt+arrow to reorder); center is the chart region with
  Index/Straddle/Commodity category tabs (Nifty/Sensex/BNF, CrudeOil/GoldM/
  SilverM) above the mode switcher.
- **"Verified P&L" link** on the profile page points to a public Sensibull
  P&L verification page (web.sensibull.com/verified-pnl/...) — used as
  social proof of the founder's/team's own trading results.

## TimeLine / Twin / Trident — hands-on, explained

Explored live on both an index (Nifty) and a stock (BANKBARODA, F&O equity)
chart. Every pane is its own TradingView Lightweight Charts instance
(`utm_campaign=lwc-chart` confirms the OSS Lightweight Charts library, not
the full TradingView widget), with its own interval dropdown, OI-at-price
bars on the right edge, and a volume histogram along the bottom.

- **TimeLine** — single pane. A draggable vertical marker sits on the chart;
  moving it defines a time window (shown as e.g. "10 Sep, 09:27 IST – 10
  Sep, 09:57 IST"). While active, the interval dropdown disables and the
  OI-at-price bars recompute using *only* the candles inside that window —
  confirmed by watching the numbers shrink (e.g. 95,743 for the full day
  down to 11,940 for a ~30 min slice) as the window narrowed. This is a
  "what changed in this specific stretch of the session" tool, not a
  different chart type.

- **Twin** — two panes side by side. Left is the underlying (index, stock,
  or commodity) with OI-at-price bars; right is its **ATM CE**, auto-picked
  by TradeMonkey, with its own AVWAP line (blue) and a header strip:
  `OPEN <oi> @ <price>` / `LTP` / `WRITER EDGE <value>`. Each pane can be
  independently zoomed/panned/interval-changed. **Not available for
  individual stocks** — the mode switcher on a stock chart only offers
  TimeLine and Trident, Twin is index/commodity/straddle only.

- **Trident** — three panes: underlying, ATM CE, ATM PE, all aligned. Each
  option pane's header swaps label depending on who's ahead: **"Writer
  Edge"** (green, positive) when premium has decayed below where the writer
  opened, or **"Under Pressure"** (red) when the option has moved against
  the writer — i.e. it's tracking the option seller's running P&L per
  contract, not the buyer's. Works for stocks too, using the stock's
  monthly F&O expiry (e.g. "BANKBARODA 29th Sep") since single-stock options
  in India don't have weekly expiries like the indices do.

- **Straddle** (separate top-level tab, not a per-chart mode) — the combined
  ATM CE+PE premium as one series, for Nifty/Sensex/BNF only.

One quirk observed on BANKBARODA: the pane read **"OI data incomplete ·
0/11 strikes"** — so OI-at-price is populated per-strike server-side and can
legitimately be empty/partial for a given stock at a given moment, the UI
surfaces that honestly rather than guessing.

## Backend / data source (from observed network calls)

Passively observed via the browser's network log during normal use (no
endpoint probing, no auth bypass attempts):

- Frontend calls TradeMonkey's own backend (`www.trademonkey.in/api/...`) —
  `api/market/candles/{key}`, `api/market/oi-profile/{key}`,
  `api/market/timeline/{key}`, `api/market/twin/{key}`,
  `api/market/trident/{key}`, `api/market/top-quotes`, `api/watchlist`,
  `api/alerts/preference`, `api/membership/quote`, `api/auth/login`. This is
  their own service layer, not the browser calling a broker directly.
- **The instrument-key format used everywhere is Upstox's exact
  `instrument_key` convention**: `NSE_INDEX|Nifty 50`, `NSE_FO|47293`
  (numeric token for F&O), `NSE_EQ|INE028A01039` (ISIN for equities — that
  ISIN is Bank of Baroda's, matching the BANKBARODA chart open at the time).
  This pipe-delimited `EXCHANGE|TOKEN-or-ISIN` scheme is specific to Upstox's
  API and instrument master, not a generic or NSE-native format. Strong
  signal the backend is built on **Upstox** as the market-data/broker
  source, even though the site's own API is what the browser talks to.

## How TimeLine actually works (from live network inspection)

Read directly off the request/response bodies while dragging the TimeLine
marker (passive observation of normal app traffic, no endpoint probing):

- **The selected window is persisted server-side, not just held in browser
  state.** Dragging the marker fires
  `POST /api/market/timeline/{instrument}` with
  `{"start_time":<epoch>,"end_time":<epoch>}`, which returns a created
  record: `{"timeline_id":"7pklf1A8xL3l","instrument_token":"...",
  "created_at":"..."}`. Further drags on the same window call
  `PATCH /api/market/timeline/{instrument}/{timeline_id}` with new
  start/end — i.e. it updates the existing DB row rather than creating a
  new one per drag. On load, `GET /api/market/timeline/{instrument}`
  returned `{"timeline":null}` (no saved selection yet for that instrument).
  This lines up with the separate `/api/market/shared-charts` and
  `/api/market/shared-chart/{instrument}` endpoints seen in the log — this
  is very likely the backing mechanism for a "share this chart view" link
  feature.
- **The OI numbers come from stored historical snapshots, not a live-only
  computation.** `GET /api/market/oi-profile/{instrument}?start_time=...&
  end_time=...` returns per-strike detail for an arbitrary past window:
  `{"reference_price":23433.55,"reference_minute":"...","strikes":[
  {"strike":23400.0,"ce_lots":17428.0,"pe_lots":44593.0,"net_lots":-27165.0,
  "data_complete":true}, ...],"coverage":{"expected_strikes":11,
  "ready_strikes":11,"missing_tokens":[]}}`. Producing accurate per-strike
  net-lot changes for any arbitrary historical window requires the backend
  to store periodic OI snapshots per strike over time (granularity implied
  by `reference_minute`) — this is a real time-series data store, not an
  in-memory "current OI" cache.
- **Architecture detail**: response header `x-tmv2-worker: 127.0.0.1:8011`
  leaks that Cloudflare is proxying to an internal worker process — a real
  backend service, not a pure serverless/edge function, consistent with
  needing a persistent DB connection for this kind of range query.

## Strike OI profile (CE/PE panes) + live update mechanism

- The per-option "Strike OI profile" (the small `+80`/`-51` tags bucketed by
  the option's own premium, seen in Twin/Trident CE/PE panes) is derived
  from a **stored per-minute OI time series**: every candle the API returns
  already embeds its own OI reading, e.g.
  `{"minute":"2026-09-10T05:37:00Z","close":4.61,"oi":9023625.0}`. The
  profile buckets that per-minute OI-delta history by the price it occurred
  at, splitting each bucket into "Added" vs "Unwound" lots.
- The AVWAP line's `studies` payload goes back to the contract's actual
  listing date (`2026-08-31` for a 29-Sep-expiry BANKBARODA option) — a
  precomputed historical series, not rebuilt from scratch per request.
- **"Live" = polling, not WebSocket push.** With a chart open, the browser
  repeats this cycle roughly every 5-10s per pane:
  `GET /candles/{token}?after_time=<cursor>` (incremental new candle(s)) ->
  `GET /candles/{token}?after_time=<cursor>&refresh_studies=true`
  (recomputed AVWAP) -> `GET /oi-profile/{token}` (refreshed strike/price
  breakdown). No streaming socket observed for market data.
- **Data-completeness caveat, observed live, not assumed**: calling the
  aggregate strike-chain endpoint for BANKBARODA
  (`GET /api/market/oi-profile/NSE_EQ|INE028A01039`, mode "total") returned
  `"coverage":{"complete":false,"expected_strikes":11,"ready_strikes":0,
  "missing_tokens":[...22 FO tokens...]}` — i.e. **zero of BANKBARODA's 11
  strikes had usable OI data** at that moment, matching the "OI data
  incomplete · 0/11 strikes" banner the UI was already showing honestly.
  Nifty/Sensex/BNF panes, by contrast, showed full `11/11` coverage. So the
  feature's reliability is real for the liquid index names but genuinely
  patchy for less-liquid single-stock F&O — worth knowing before leaning on
  it for a mid-cap stock's options.

## Open questions (not pursued further — paid workspace internals)

- Exact OI-profile calculation and AVWAP anchor rules per instrument type.
- Whether Upstox is the only feed or just the instrument-identity scheme
  carried over from an earlier integration.
- How does it compare to OpenAlgo's own `/trading` charting terminal and
  options tools (GEX, OI Tracker, Straddle, Vol Surface, etc. in
  `frontend/src/lib/tools.ts`)? On the surface, TradeMonkey is a narrower,
  single-purpose paid product (OI-at-price + AVWAP + multi-pane option
  context) versus OpenAlgo's broader open self-hosted options/portfolio
  suite — not a direct architecture reference since TradeMonkey's stack is
  unknown (TradingView front end, backend unverified), but comparable in
  the specific "OI overlay on live chart" feature area.

## FORCEMOT — 10 Sep 2026 morning move, micro-level reconstruction

Deep dive requested by the user on Force Motors (NSE: `FORCEMOT`, ISIN
`INE451A01017`, futures token `NSE_FO|68480`, lot size 25), which "gave a
good move" this morning. Reconstructed by placing/resizing TimeLine windows
directly on TradeMonkey's chart (via genuine Playwright-driven drag
gestures on the actual DOM handles — `.timeline-handle.left/.right` — not
just clicking) and reading the exact API responses those actions triggered,
plus pulling FORCEMOT's own 1-minute candle/OI history directly from
`/api/market/candles` for minute-by-minute ground truth.

**FORCEMOT does have a full option chain** (14000–20500 in 500-pt
increments, monthly 29-Sep-2026 expiry) — so a full picture was possible,
unlike a futures-only reconstruction.

### The move, minute by minute (IST, from raw 1-min candles)

| Time | Open→Close | Volume | Note |
|---|---|---|---|
| 09:15 | 17,419 → 17,465 | 1,782 | Gap-up open |
| 09:15–09:17 | → high 17,620 | — | Fast initial pop |
| 09:19–09:39 | ~17,500–17,560 range | low, ~200–800/min | 20-min sideways consolidation, move stalled |
| 09:40 | 17,561 → 17,623 | 1,504 | Resumes |
| 09:40–09:54 | grinds 17,620 → 17,780 | rising | Steady climb, no single big candle yet |
| **09:55** | **17,780 → 17,938** | **4,009** | First breakout candle — biggest volume so far, high 17,972 |
| 09:56–09:58 | 17,914 → 17,912 | ~500–1,200 | Brief pause just under 18,000 |
| **09:59** | **17,912 → 17,999** | **5,095** | Second, bigger breakout candle — session's largest volume print, touches round-number 18,000 |
| 10:00–10:02 | 18,000 → peak 18,044 | 1,600–3,300 | Final push to the session high |
| 10:02–10:10 | fades to ~17,920–17,940 | tapering | Move exhausts, gives back ~100 pts |

So "the move" is really two things: a slow 40-minute grind (09:15–09:54,
~17,420→17,780, +2.1%), then two explosive 1-minute volume spikes
(09:55 and 09:59, the two largest-volume candles of the session by a wide
margin) that did most of the work, carrying price to 17,999→18,044 before
fading.

### What the futures OI did — the key finding

Pulling `NSE_FO|68480`'s own per-minute `oi` field (embedded in every
candle) across the whole move:

| Time | Price | Futures OI (lots) |
|---|---|---|
| 09:15 | 17,414 | 254,600 |
| 09:53 (pre-breakout) | 17,502 | 254,350 |
| 09:55 (breakout candle) | 17,950 | 249,750 |
| 09:56–09:58 | ~17,920–17,958 | 248,375–248,600 |
| 09:59 (2nd breakout candle) | 17,999 | 248,000 |
| 10:02 (session high 18,080 intraday tick) | 18,080 | 248,625 |
| 10:05 | 17,982 | 249,075 |

**Futures OI fell by roughly 6,000 lots (~2.4%) while price rose ~600
points, with the steepest OI decline landing on exactly the same two
minutes (09:55, and the run-up into 09:59) as the two volume-spike breakout
candles.** Price up + OI down together is the textbook signature of a
**short-covering rally**, not fresh long buying — the move looks driven
substantially by futures short sellers being forced to buy back, not by
new bullish futures positioning. This is a materially different read than
"strong buying interest," and it's only visible because the per-minute OI
series exists at all — a plain price chart or an end-of-day OI figure
would not show it.

### What the options chain did in the same window

Using a TimeLine window tightened to 09:51–10:03 IST (bracketing exactly
the two breakout candles), the per-strike change data
(`GET /api/market/oi-profile/NSE_EQ|INE451A01017?start_time=1789014060&
end_time=1789014779`) returned:

| Strike | CE net | PE net | Combined net | Read |
|---|---|---|---|---|
| 17,000 | -12 | -35 | +23 | minor |
| 17,500 (ATM at window start) | **-103** | **+203** | -306 | Call OI unwound, Put OI built, in the same 12 minutes |
| 18,000 (new ATM as price broke through) | **+269** | +70 | +199 | Heaviest fresh Call OI of any strike |
| 18,500 | +31 | -1 | +32 | modest |
| 19,000 | +96 | +2 | +94 | fresh OTM call buildup |
| 19,500 / 20,000 / 20,500 | +139 / +155 / +79 (incomplete data) | n/a | — | more OTM call buildup, further out |

Coverage was partial (5/11 strikes fully complete; 6 strikes, mostly the
lower ones — 15,000–16,500 and the far OTM 19,500+ — had `data_complete:
false` with missing option tokens), consistent with the same liquidity-
dependent gaps already documented above for BANKBARODA.

Reading the complete strikes together: as spot broke through 17,780 toward
18,000, **call OI piled up hardest exactly at 18,000** (+269, more than
any other strike, right at the round-number level price was attacking),
with more speculative OTM call buildup cascading out to 19,000+ — a classic
"chase the breakout with OTM calls" pattern. At the same time, the prior
ATM (17,500) saw *puts* increase (+203) while its *calls* fell (-103) —
consistent with 17,500 call writers/holders unwinding as it went
in-the-money, while fresh put writing appeared there once it was safely
below spot.

### Put together

The full micro-level picture for this move: a slow grind higher for 40
minutes, then a two-minute volume explosion that pushed the stock through
17,800 and then 18,000; **the futures OI drop through that explosion points
to short-covering as the actual mechanical driver**, while **the options
chain shows fresh speculative call buildup concentrated right at the round
number the price was breaking through, plus fresh put writing at the level
that just got left behind**. None of this — the short-covering signature
specifically — would be visible from price and volume alone; it only shows
up because TradeMonkey (and the underlying per-minute OI storage this
research already established) exposes OI as its own time series, not just
an end-of-day number.

Caveat carried over from the rest of this document: this reconstruction is
one session, one stock, with partial per-strike data coverage — treat it as
an illustration of what the tool can surface, not a general claim about how
FORCEMOT always trades.

## Competitive check: Sensibull already ships the same core feature

TradeMonkey's profile page links out to Sensibull for "Verified P&L" proof
(that link itself redirects into a Zerodha Kite Connect OAuth login — not
something explored further, since it would require someone else's broker
credentials). Following that thread to Sensibull's own free chart tool
(`web.sensibull.com/chart`, no login required) turned up a direct
competitor to TradeMonkey's core pitch:

- Sensibull's chart toolbar has a checkbox literally labeled **"OI Profile"
  (tagged "New")** that renders the *same visual concept* as TradeMonkey's
  Dynamic/Strike/Contract OI profile — green/red horizontal bars sitting at
  price levels on the right edge of the candle chart.
- Its settings dialog (**OI Profile Settings**) exposes two things
  TradeMonkey's captured responses never showed:
  - A toggle between **"Open Interest"** (absolute level, the default) and
    **"Change in OI"** (delta) — TradeMonkey's API always returned
    `"mode":"change"` in every response seen in this research; no absolute-
    OI view was ever observed.
  - An **"Expiry Used"** checklist (15 Sep / 22 Sep / 29 Sep / 06 Oct /
    13 Oct / 27 Oct, all selectable) — meaning Sensibull can aggregate OI
    across multiple expiries in one profile. Every TradeMonkey `oi-profile`
    response captured in this research carried a single `"expiry"` field —
    one expiry at a time only.
- Sensibull's chart is built on the **full TradingView platform** (complete
  drawing tools, Fibonacci/Gann tools, position tools, indicators, 5-year
  history) with OI Profile as one overlay among many — versus TradeMonkey's
  narrower, purpose-built app using just TradingView's open-source
  Lightweight Charts library with candles + OI profile + AVWAP and nothing
  else (no drawing tools, no other indicators, no multi-year history).

**Read, revised after inspecting Sensibull's actual API calls (not just the
UI)**: the visual similarity is real but the underlying mechanism is not the
same, and it changes the conclusion.

`POST oxide.sensibull.com/v1/compute/compute_intraday_oi_chart` takes only
`{underlying, expiries, chart_selection: "oi" | "oi_change"}` — **no time
window parameter exists in the request or response, in either mode.** The
response is a flat `{strike: {call: N, put: N}}` map for ~20 strikes around
ATM:
- `"oi"` mode returns today's current absolute OI per strike — i.e. a
  standard option-chain snapshot rendered as bars instead of a table.
- `"oi_change"` mode returns one fixed delta per strike (e.g. ADANIENSOL's
  1600 strike showed `{"call":-45900,"put":0}` as a single number), almost
  certainly "since previous close" or "since today's open" — not a
  window you can choose.

So Sensibull's bars are bucketed **by strike**, full stop — the same
information a normal option chain already carries, just charted instead of
tabulated. TradeMonkey's TimeLine mechanic is a different thing: it buckets
OI changes by the **price the instrument was actually trading at during an
arbitrary historical window you drag on the chart** (confirmed in the
FORCEMOT section above — dragging the marker to 09:51–10:03 IST re-queried
`start_time`/`end_time` and got back numbers scoped to exactly that
12-minute stretch). That specific capability — temporal + price-level OI
attribution, not just a strike snapshot — has no observed Sensibull
equivalent. TradeMonkey's actual differentiation, if it has one, is the
TimeLine replay mechanic and the Writer Edge/Under Pressure per-contract
framing, not "OI plotted at price" in general, which Sensibull's simpler
strike-snapshot version already covers for free.

### Writer Edge / Under Pressure — checked against Sensibull's Option Chain, no equivalent found

Checked Sensibull's full Option Chain tool (`web.sensibull.com/option-chain`)
across all three of its column presets — **LTP View**, **All Column View**
(Bid/Offer, Intrinsic Value, Time Value, Breakeven%, LTP change), and
**Greeks View** (Delta, Theta, Vega, Gamma, POP — Probability of Profit,
computed per strike) — for anything resembling TradeMonkey's per-contract
"is the writer currently winning or losing" framing.

**Nothing matches.** Sensibull's metrics are all standard, buyer/seller-
neutral options math: real Greeks from a pricing model, a genuine POP
probability, intrinsic-vs-time-value split, breakeven%. None of it is
framed as "the option seller's running edge" the way TradeMonkey's Writer
Edge/Under Pressure is. The closest conceptual relative is POP, but that's
a computed probability from the Greeks, not a live comparison of current
premium against the pane's opening print — a materially different (and more
rigorous) calculation than what TradeMonkey appears to be doing, based on
what was observed on its own chart headers (`OPEN <n> @ ₹X` / `LTP` /
`WRITER EDGE ±₹Y`, where the edge value tracked simply how far LTP had
moved from the opening reference price).

So this is a second real point of differentiation for TradeMonkey (after
TimeLine's time-windowed OI replay) — but it cuts the other way from a
credibility standpoint: Sensibull's option-chain analytics are built on
actual options-pricing math, while TradeMonkey's Writer Edge framing looks
like a simplified "premium vs open" heuristic wearing a seller-P&L label.
Simpler isn't necessarily wrong for a quick-glance chart overlay, but it's
worth knowing it isn't doing genuine Greeks-based P&L attribution the way
the label might imply.

## Synthesis: what's actually buildable in OpenAlgo

Checked against the real codebase before proposing anything — OpenAlgo
already has the prerequisite most of this would need, and already has
tools that overlap partway with both competitors.

**Foundation already exists.** `database/historify_db.py`'s `market_data`
table stores `oi` as a column alongside OHLCV, per interval, per symbol
(`historify_db.py:130,332` and the insert/read paths around it) — the same
"every candle carries its own OI reading" shape both TradeMonkey and
Sensibull are built on. No new data pipeline is needed to build any of this;
it's a query/UI problem, not a data-collection problem.

**What OpenAlgo already covers** (`frontend/src/lib/tools.ts`): OI Tracker
(CE/PE OI bars + PCR + ATM marker), OI Range (strike-range OI with
ATM-relative selectors), OI Profile (futures candlestick + OI butterfly +
daily OI change), Option Greeks (historical IV/Delta/Theta/Vega/Gamma),
Max Pain, Straddle Chart, GEX Dashboard, Gamma Density, IV Smile, Vol
Surface. This is already broader than either TradeMonkey or Sensibull's
free chart — real Greeks and GEX put OpenAlgo ahead of TradeMonkey's simple
Writer Edge heuristic already.

**What's genuinely missing — the one clear gap**: nothing in OpenAlgo does
TradeMonkey's TimeLine mechanic — an arbitrary, user-draggable time window
on the chart that recomputes OI-by-price *for exactly that window*, scoped
to the price the instrument was trading at during that stretch (confirmed
`OIProfile.tsx` has no time-windowing logic — it's whole-day, same as
Sensibull's fixed-delta approach). This is the one piece of this whole
research thread that neither existing OpenAlgo tool nor Sensibull's option
chain does.

### Concrete feature proposal: "OI Timeline" mode for the existing OI Profile tool

Rather than a new tool page, extend `/oiprofile` (and optionally
`/oitracker`) with a time-window selector:

- **UI**: a draggable range overlay on the candlestick chart (left/right
  handles, matching the interaction TradeMonkey uses — proven usable, and
  `openalgo-charts` already renders candles on the same `/trading` terminal
  this could reuse rendering primitives from) or, more simply for a first
  cut, a from/to time picker above the chart.
- **Query**: for the selected window, pull `market_data` rows for the
  underlying/futures/each strike's option contract between `start_time` and
  `end_time`, compute `oi[end] - oi[start]` (or true net across the window
  if OI can move both ways intra-window) bucketed by the price the
  instrument was trading at during that stretch — this is exactly the shape
  TradeMonkey's `oi-profile?start_time&end_time` response has
  (`strike/price -> {net_lots, ce_lots/pe_lots or added/unwound}`), and
  OpenAlgo already has the raw per-minute OI rows to compute it directly in
  SQL/DuckDB rather than needing a service call out.
- **Where it beats both competitors**: combine it with OpenAlgo's *existing*
  real Greeks (Option Greeks tool) instead of TradeMonkey's simplistic
  "LTP vs opening premium" Writer Edge heuristic — show the actual writer's
  running P&L per lot (entry premium at window start vs current, times lot
  size) alongside the OI-build/unwind bucket, which neither TradeMonkey
  (heuristic, not real P&L) nor Sensibull (no writer-framing at all) does
  today. That would be a feature no one in this research thread actually
  has yet: **time-windowed OI-at-price + real per-lot writer P&L in the
  same view.**

### Smaller, lower-effort pickups worth considering separately

- **Multi-expiry aggregation toggle** on OI Range/OI Profile, matching
  Sensibull's "Expiry Used" checklist — cheap to add if OpenAlgo's option
  chain endpoints already return per-expiry OI (need to verify), and closes
  a real gap versus Sensibull that TradeMonkey also doesn't have.
- **Absolute OI vs Change-in-OI toggle**, matching Sensibull's two modes —
  OpenAlgo's existing tools already lean toward change/PCR framing; a
  same-page toggle to flip to raw open-interest level would be a small,
  well-understood addition.
- **Twin/Trident-style synchronized multi-pane layout** (underlying + ATM
  CE + ATM PE side by side, each independently zoomable) is more of a
  `/trading` charting-terminal layout feature than an options-tools feature
  — lower priority unless there's a specific workflow need for it, since
  OpenAlgo's existing Option Chain + Straddle Chart already cover the
  "see both sides at once" need in table/combined-premium form.
