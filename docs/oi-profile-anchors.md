# OI Profile: where Change in OI is anchored

The OI Profile (`/oiprofile`, and the `oi_profile_live` chart overlay) draws two
things per strike: the open interest each option carries now, and how much of it
was built today. The second needs an **anchor** — the open interest the contract
closed the previous session on:

```
Change in OI = current OI - previous session's closing OI
```

Current OI is cheap: one multiquote over the chain, well under a second. The
anchor is the expensive half, and how it is sourced decides whether switching
symbols is instant or unusable. This document records the two sources, why the
order between them matters, and what each one is verified against.

Code: `services/nse_oi_bhavcopy.py`, `services/oi_profile_service.py`.

## The anchor is the previous session's close, not today's open

Settled by measurement, not preference. On 16-Sep-2026, NIFTY22SEP2623200PE
closed 15-Sep at 4,552,925 — exactly NSE's 70,045 contracts at a lot size of 65
— while its 16-Sep opening bar read 6,614,400. Anchoring on the opening bar
showed a 85% build where NSE and Sensibull both showed 170%. The overnight step
is real open interest and the day's change owns it.

Pinned by `test_anchor_is_the_previous_session_close`. Do not re-derive it from
the opening bar; that has been tried.

## Source 1: NSE's F&O bhavcopy (preferred)

NSE publishes every derivatives contract's closing open interest after each
session, as one zipped CSV — the bhavcopy. One file answers the whole market.

| | |
|---|---|
| Size | ~1.1 MB zipped |
| Rows | 35,657 contracts (35,010 options, the rest futures) |
| Underlyings | 216 |
| Download + parse | 0.58–1.02 s |
| Frequency | once per day |

`TckrSymb` + `XpryDt` + `StrkPric` + `OptnTp` maps onto the OpenAlgo symbol
(`NIFTY22SEP2623200PE`), strikes written the way the symbol master writes them —
whole numbers bare, fractions kept (`VEDL29SEP26292.5CE`).

**What it was verified against.** For the 16-Sep-2026 file:

- All **216** NFO option underlyings in `symtoken` are present, and the file
  carries no underlying `symtoken` does not know.
- All **35,010** option rows map onto a symbol already in `symtoken`. No
  spelling mismatches.
- Anchor-for-anchor against the broker's per-leg history, 134 live legs
  (NIFTY 82, TVSMOTOR 52): **zero disagreements**. Every leg both sources
  answer returns the identical figure.
- The asymmetry runs one way only: 7 TVSMOTOR legs carry a figure the broker's
  daily history returned nothing for. No leg went the other way.

**Absence is evidence, with one guard.** The file lists contracts that held no
open interest explicitly, as `OpnIntrst = 0` (about 16,800 of the 35,010). A
contract missing from it altogether, *whose underlying the file does cover*, is
therefore anchored at zero — all of today's open interest is a fresh build. An
underlying the file does not cover at all (an F&O name listed today) falls
through to the broker instead, because zeroing its whole chain would report
every strike as built today.

This is the opposite of how a *failed broker read* is treated, deliberately.
See "unknown is not zero" below.

**Coverage.** NSE only. BSE publishes its own file in a different format and
crypto has none; both use source 2.

## Source 2: one broker history call per leg (fallback)

Ask the broker for each option's daily candles and read the row before the
latest. Correct, and ~80 HTTP round trips per chain. Behind the process-wide
350 ms gate in `services/history_service.py` that every history caller shares,
that is 25–30 s for one underlying.

It remains the fallback for BFO, crypto, and any leg the bhavcopy cannot speak
for.

## Nothing fetches an anchor inside a request

The per-leg pass used to run inline. An underlying nobody had opened that day
had no anchor for any of its legs, so a symbol switch became a 30–90 s request
(117 s observed, multi-expiry). Two consequences, both seen in production:

- `openalgo-charts` gives its own history request a **15 s** timeout, so the
  chart's request for the newly selected symbol expired behind the anchor pass:
  *"History error: History request timed out"*, and the symbol never drew.
- Switching twice in a minute put two chains' worth of broker calls in flight
  together. Thread count reached 50 and the Upstox feed dropped on ping/pong.

So the request never fetches. `_fetch_prev_session_oi` answers with the anchors
already cached, reports `oi_change_pending` when some are missing, and hands the
rest to a single module-level worker:

- **One worker** (`max_workers=1`), so the broker never sees two chains warming
  at once.
- **Newest selection wins.** A later request supersedes the running job by
  generation check rather than queueing behind it; anchors it had already cached
  are kept, so nothing is refetched.
- **The worker is the only place that may download the bhavcopy.** A request
  reads it only if it is already in hand (`cached_previous_session_oi`), which is
  why every symbol switch after the first is instant *and* complete.
- A pending payload is **not** written to the shared profile cache, or the
  client polling for the rest would be handed the same gaps for the whole TTL.

Clients shorten their beat while pending — 10 s on the page, 15 s on the chart
overlay — instead of waiting out the normal three minutes.

### Warmed at startup

`app.py` calls `previous_session_oi("NFO")` from the existing
`_restore_caches_background` daemon thread. That thread already waits for the
database and holds an app context, which the market calendar needs to resolve
which session to anchor on. Cost is one sub-second download during boot, off
the critical path, and it means `oi_change_pending` is never seen in normal
operation.

### Which session the file is for

The anchor belongs to the session *before* the one on screen:

| When | On screen | Anchor file |
|---|---|---|
| Trading day, any time including after close | today | previous trading day |
| Weekend or holiday | last session that traded | the session before that |

`_displayed_session()` reads `is_market_holiday()` for the first column and
`_newest_before()` walks back day by day for the second — an unpublished date
404s, so weekends and holidays are skipped without a calendar lookup. Verified
to agree with the per-leg path on a trading day; the holiday branch follows the
same shape.

## Unknown is not zero

A zero anchor subtracted from a live number reports the leg's entire open
interest as today's build, so one unreadable leg paints a strike as a huge fresh
write. Rules:

- A **failed or empty broker read** caches `_NO_ANCHOR` (-1.0) and is read back
  as unknown. It draws no change. It is cached rather than retried so a chain of
  unreadable legs cannot re-storm the broker on every beat — the trade-off is
  that a transient failure keeps that leg blank for the session.
- An **explicit zero from NSE**, or absence from a file that covers the
  underlying, is a real anchor of 0. The whole of today's open interest is a
  genuine build. This is a behaviour change from the per-leg-only era, where
  the two cases were indistinguishable and both drew nothing.

## Measured

Live, market open, same legs through both paths:

| | before | after |
|---|---|---|
| NIFTY 22SEP26, 82 legs — anchor pass | 28.82 s | 0.0003 s |
| TVSMOTOR 29SEP26, 52 legs — anchor pass | 24.35 s | 0.0003 s |
| Full request, cold symbol | 34–40 s | 0.16–0.28 s |
| Chart overlay, `include_change: false` | 0.5 s | 0.5 s |
| Whole NSE F&O market | ~17,700 calls, ~1 h 38 m | one file, under 1 s |

## Not covered by the file

- **BFO** (SENSEX, BANKEX) — BSE publishes an equivalent in a different format.
  Not implemented; BFO uses the per-leg fallback.
- **Crypto** — no such file exists.
- **The drag-selected window.** Dragging a range on the OI Profile candles sends
  `window_start`/`window_end` and measures the build across that intraday window
  (`_fetch_windowed_oi_changes`). A daily settlement file cannot answer it —
  it needs intraday bars, still one broker call per leg, still inline. It is
  explicitly user-initiated and one-off, so it was left alone. Historify's
  `market_data` table already holds one-minute bars with an `oi` column for
  5,970 NFO symbols, which is the obvious local source if this path starts to
  hurt.

## Tests

| File | Covers |
|---|---|
| `test/test_nse_oi_bhavcopy.py` | Symbol mapping including fractional strikes, the 4,552,925 arithmetic, both absence rules, NSE-only gating, the failure cool-off. Builds a file in memory — no network. |
| `test/test_oi_profile_multi_expiry.py` | The anchor definition, unknown-is-not-zero, multi-expiry sums, and that a cold underlying answers at once, that a newer selection abandons the chain being warmed, and that a failed warm pass cannot wedge the pending state. |
| `test/test_oi_profile_windowed.py` | That the windowed and previous-close paths are selected on the right condition. |

The NSE path is switched off by default in `test_oi_profile_multi_expiry.py`, so
those tests keep exercising the per-leg fallback.

## Tuning

| Variable | Default | Effect |
|---|---|---|
| `OI_PROFILE_CACHE_TTL` | 60 s | How long one profile answer is shared |
| `OI_PROFILE_CACHE_MAXSIZE` | 64 | Bound on shared answers |
| `OI_PROFILE_PREV_OI_TTL` | 43200 s (12 h) | Anchor lifetime; must outlast a session |
| `OI_PROFILE_PREV_OI_MAXSIZE` | 4096 | Bound on cached anchors |
