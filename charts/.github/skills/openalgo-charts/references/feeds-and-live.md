# Feeds and live data

*When to read this: you are connecting the chart to a broker or backend, REST history, a WebSocket tick stream, live candle assembly, or a custom `DataFeed`.*

## The DataFeed contract

`src/feed/types.ts`. The chart core never imports a broker SDK; it depends only on this.

```ts
interface DataFeed {
  getBars(req: BarsRequest): Promise<Bar[]>;
  getBarsPage?(req: BarsPageRequest): Promise<BarsPage>;
  getCachedBars?(req: BarsRequest): Promise<Bar[] | undefined>;
  subscribeBars?(req: BarsRequest, onBar: (bar: Bar) => void, opts?: BarSubscriptionOptions): UnsubscribeFn;
  subscribeDepth?(req: BarsRequest, onDepth: (depth: MarketDepth) => void, opts?: { depthLevel?: number }): UnsubscribeFn;
  searchSymbols?(request: SymbolSearchRequest): Promise<SymbolMatch[]>;
}

interface SymbolSearchRequest { query: string; signal?: AbortSignal }
interface SymbolMatch {
  symbol: string; exchange?: string; name?: string; assetClass?: string; iconUrl?: string;
  contractGroup?: { label?: string; contracts: readonly SymbolMatch[] };
}

interface BarsRequest {
  symbol: string;
  exchange: string;
  interval: string;   // '1m' | '5m' | '1h' | 'D' | ...
  signal?: AbortSignal;
  timeoutMs?: number;
  countBack?: number;
  from?: UTCSeconds;
  to?: UTCSeconds;
  noCache?: boolean;  // request authoritative history, bypassing cached results
}

interface BarSubscriptionOptions {
  seedFrom?: Bar;
  cumDayVolumeSoFar?: number;
  onResync?: () => void;
}
```

**`subscribeBars` and `subscribeDepth` are optional.** A history-only feed omits them so callers can feature-detect (`if (feed.subscribeBars)`). `OpenAlgoDataFeed` deliberately does not implement `subscribeBars`; `OpenAlgoLiveDataFeed` implements both.

**`searchSymbols` is optional too**. A feed that has it serves the widget's symbol search with no host code: `createWidget` uses it wherever the host passes no `symbolSearch`, and a host callback still wins. Answer closest first, and honour `signal`, which aborts once a newer query replaces this one. `SymbolMatch` and `SymbolSearchRequest` are exported from the base package; the widget re-exports `SymbolMatch`. Both OpenAlgo feeds implement it.

`BarSubscriptionOptions` is exported from the base package. Its optional third argument keeps existing two-argument feed implementations compatible. `seedFrom` continues the last time-bucketed history bar; `cumDayVolumeSoFar` is the cumulative day total at that snapshot for day-delta volume accounting. A feed calls `onResync` when a recovered stream may have missed data. A host should pause display updates, buffer incoming bars while loading the current window with `noCache: true`, merge the observations before `setData`, then seed the replacement subscription from the merged last bar. Keep resync monitoring active so a repeated reconnect can supersede the pending request. Preserve the viewport, guard against stale requests, and keep a visible error plus retry path if recovery fails. Older gap-fill bars do not belong in the tail-only `onBar` / `series.update` path.

Install the newly seeded subscription before releasing the previous one, so a shared feed keeps its underlying stream active through the handoff.

Supporting types: `MarketDepth { bids: DepthLevel[]; asks: DepthLevel[]; ltp: number; ltq?: number; timeSec?: UTCSeconds }`, `DepthLevel { price, qty, orders? }`, variable depth, whatever the broker streams. `UnsubscribeFn = () => void`.

`TradeFeed` (`placeOrder` / `modifyOrder` / `cancelOrder` / `subscribeOrders` / `subscribePositions`, taking `PlaceOrder`) is deprecated, removed in 3.0.0 (both types): nothing in the library takes or implements it. The trade tier's `OrderEngine` uses the smaller `OrderFeed` (`place` / `modify` / `cancel`, taking `PlaceRequest`) from `openalgo-charts/trade`, which is what `OpenAlgoTradeFeed` implements, and the chart draws the book a host hands it with `chart.trading.syncState`. `OrderSide` and `OrderType` are one type each: the trade tier's are the base's, re-exported. See [trading](trading.md).

**Verify every OpenAlgo wire field against your running OpenAlgo build.** The adapters below encode the documented REST paths and WS message shapes, and the parsers are deliberately tolerant, but field names have moved between OpenAlgo releases. Pin them for your deployment before production.

## OpenAlgoDataFeed: REST history

```ts
import { OpenAlgoDataFeed } from 'openalgo-charts';

const feed = new OpenAlgoDataFeed({
  baseUrl: 'http://127.0.0.1:5000',
  apiKey: 'YOUR_KEY',
  fetchImpl: undefined,   // optional; defaults to a bound global fetch
});

const bars = await feed.getBars({
  symbol: 'RELIANCE', exchange: 'NSE', interval: '1m',
  from: nowSec - 7 * 86400, to: nowSec,
});
```

- `POST ${baseUrl}/api/v1/history` with `{ apikey, symbol, exchange, interval, start_date, end_date }`.
- Exact interval translations: `1d` / `1D` to `D`, `1w` / `1W` to `W`, and `1M` / `MN` to `M`. Other codes pass through, including `D`, `W`, `M` and minute code `1m`.
- **`from` and `to` are mandatory.** `getBars` throws without them: OpenAlgo history requires a date range. They are UTC seconds; the adapter converts to IST `YYYY-MM-DD` via `utcSecondsToIstDateString`. That is the OpenAlgo server's own convention, not the chart's display zone: `chart.setTimezone(...)` does not change what date this adapter asks for, so widen the range by a day rather than assuming the two agree.
- A non-OK HTTP response throws `history request failed (<status>)`. JSON `status: 'error'` also throws, using its `message` or `OpenAlgo history request failed`, even for HTTP 200.
- `fetchImpl` is injectable so the adapter is unit-testable offline. The default binds global `fetch` to `globalThis` (an unbound `window.fetch` throws "Illegal invocation").

Symbol search:

```ts
const hits = await feed.searchSymbols({ query: 'NIFTY', signal });
// [{ symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY', assetClass: 'Index' },
//  { symbol: 'NIFTY28OCT26FUT', exchange: 'NFO', name: 'NIFTY', assetClass: 'Futures' },
//  { symbol: 'NIFTY 28-OCT-26', exchange: 'NFO', assetClass: 'Options',
//    contractGroup: { label: 'NIFTY 28-OCT-26', contracts: [/* one hit per strike and side */] } }, ...]
```

- `POST ${baseUrl}/api/v1/search` with `{ apikey, query }` across every exchange, under the same deadline and cancellation as history. A blank query answers `[]` without a request.
- The platform's ranking is kept, capped at 50 rows. `assetClass` is `Index` on an `*_INDEX` exchange, `Equity` without an expiry, `Options` for a contract whose symbol ends in `CE` or `PE`, else `Futures`.
- The options of one underlying and expiry on one exchange share a row whose `contractGroup` holds them, so an index search lists expiries rather than hundreds of strikes. An expiry with a single option lists that option itself.
- A non-OK response throws `symbol search failed (<status>)`; a JSON `status: 'error'` throws its string `message`. Neither carries the key.
- `OpenAlgoLiveDataFeed.searchSymbols` delegates to its REST adapter.

Two pure helpers are exported for reuse and testing:

- `mapHistoryResponse(json)`: reads `json.data[]`, accepts either `timestamp` or `time` on each row, skips rows with neither, returns bars sorted ascending.
- `rowTimeToUtcSeconds(value)`: tolerant timestamp coercion:

| Input | Result |
|---|---|
| `number > 1e12` | treated as epoch **ms** |
| other `number` | `Math.floor(value)` (epoch seconds) |
| numeric-looking string with no `-`, `T`, `:` or space | same numeric rules |
| parseable string ending in `Z`, `+HH:MM`, `-HH:MM`, `+HHMM` or `-HHMM` | UTC seconds using the explicit offset |
| anything else | `istStringToUtcSeconds(value)`, IST wall-clock parse |

## OpenAlgoWsFeed: realtime

```ts
import { OpenAlgoWsFeed } from 'openalgo-charts';

const ws = new OpenAlgoWsFeed({
  url: 'ws://127.0.0.1:8765',
  apiKey: 'YOUR_KEY',
  reconnect: { enabled: true, baseDelayMs: 1000, maxDelayMs: 30000, maxAttempts: Infinity },
  socketFactory: undefined,   // optional
});

ws.connect();
const off = ws.onLtp((e) => { /* e: { symbol, exchange, ltp, ltq?, volume?, timeSec } */ });
ws.subscribe('LTP', 'RELIANCE', 'NSE');
```

Modes: `WsMode = 'LTP' | 'Quote' | 'Depth'`, sent as numeric `1 | 2 | 3`.

Wire format (pure formatters, exported where noted):

| Step | Frame |
|---|---|
| auth (sent automatically on open, before anything else) | `{ action: 'authenticate', api_key }` |
| subscribe (`formatSubscribe`) | `{ action: 'subscribe', symbol, exchange, mode }`, plus `depth` (and `depth_level`, the 1.x name) for `Depth` |
| unsubscribe (`formatUnsubscribe`) | `{ action: 'unsubscribe', symbol, exchange, mode }` |
| order stream | `{ action: 'subscribe_orders' }` / `{ action: 'unsubscribe_orders' }` |
| heartbeat | inbound `'ping'` or `{ type: 'ping' }` -> replies `{ action: 'pong' }` |
| inbound data | `{ type: 'market_data', symbol, exchange, mode, data: { ... } }`; legacy `topic` is also accepted |

`parseMessage(raw)` (exported) normalizes inbound frames. It reads payload fields from `data` but tolerates a flat shape, accepts `ltp` or `last_price`, `ltq` or `last_trade_quantity`, and maps `depth.buy`/`depth.sell` (`{ price, quantity, orders? }`) into `MarketDepth.bids`/`asks`. Anything it cannot classify returns `null` and is surfaced to `onControl` instead.

Market time uses the first valid positive value in `last_trade_time`, `ltt`, `exchange_timestamp`, then `timestamp`. This keeps a cached quote's later proxy delivery time from replacing its known market event time. Epoch seconds, milliseconds, numeric strings and ISO-8601 strings are accepted. An unknown time remains `0` for LTP or absent for depth; hosts still own unknown-time and trading-session policies. Parsing a timestamp alone does not prove that the event occurred inside a trading session.

Symbol and exchange resolve independently from non-empty `data` fields, then top-level envelope fields, then the legacy `topic`. Empty nested identity fields do not hide usable top-level identity. This applies to LTP, Quote and Depth frames.

Callbacks, each returning its own unsubscribe: `onLtp`, `onDepth((symbol, exchange, depth) => {})`, `onState((s: WsState) => {})` with `'connecting' | 'open' | 'closed' | 'error' | 'reconnecting'`, `onControl` for auth/subscribe acks and server errors, `onOrderUpdate` for the account-level order stream. A callback that throws stops neither the other callbacks nor the feed's own state change (since 2.6.0): its error goes to `reportError` where the platform has one, as on the chart bus. Before, a throw during an auth refusal left the socket open, and a throwing tick listener starved the ones after it.

Reconnect and resubscribe:

- Enabled by default. On an unexpected close the feed backs off `min(maxDelayMs, baseDelayMs * 2^attempt)`, reconnects, re-authenticates, then replays **every** active subscription plus the order stream if it was on.
- A successful open resets the attempt counter.
- `close()` sets an intentional-close flag and never reconnects; it also clears the pending send queue.
- Sends before the socket is open are queued and flushed after authentication, so `subscribe()` immediately after `connect()` is safe.
- `socketFactory: (url) => SocketLike` injects a socket for tests, React Native, or any non-browser runtime. `SocketLike` needs `send`, `close`, `onopen`, `onclose`, `onmessage`, optionally `onerror` and `readyState` (`1` means open; a factory that connects synchronously is handled).

## OpenAlgoLiveDataFeed: REST + WS + CandleBuilder

The composed feed that actually satisfies the full `DataFeed` contract.

```ts
import { OpenAlgoLiveDataFeed } from 'openalgo-charts';

const live = new OpenAlgoLiveDataFeed({
  baseUrl: 'http://127.0.0.1:5000',
  wsUrl: 'ws://127.0.0.1:8765',
  apiKey: 'YOUR_KEY',
  volumeMode: 'ltq-sum',      // default
  timezone: 'Asia/Kolkata',   // default; the zone a calendar interval buckets in
});

const req = { symbol: 'RELIANCE', exchange: 'NSE', interval: '1m', from, to };
const bars = await live.getBars(req);
series.setData(bars);

const off = live.subscribeBars(req, (bar) => series.update(bar), {
  seedFrom: bars[bars.length - 1],
  cumDayVolumeSoFar: undefined,   // only meaningful for volumeMode: 'day-delta'
});
// later: off(); live.close();
```

- The constructor connects the socket immediately.
- `subscribeBars` resolves the interval code **once, up front** through `resolveInterval`, then creates a **per-subscription** aggregator: a `CandleBuilder` for a fixed-length interval, a `TickBarAggregator` for a calendar, tick-count or volume one. It filters WS ticks by symbol **and** exchange and forwards the bar to `onBar`. Unsubscribing detaches the callback and sends the WS unsubscribe.
- Resolving up front is deliberate: a bad interval code throws at subscribe time, where the mistake is, instead of silently on every tick for the life of the subscription.
- `opts.seedFrom` seeds the aggregator with the last history bar so the first tick continues that bucket. It applies to **time-bucketed intervals only**: a count-driven bar cannot resume one whose trades were never counted here. `opts.cumDayVolumeSoFar` gives a `day-delta` builder the right baseline.
- `opts.onResync` is called without arguments when the socket emits `client_warning` with code `STREAM_RESYNC` after reconnect. Replayed subscriptions resume delivery but do not repair missed history. Handle this callback with the history replacement sequence above; unsubscribing also removes this control listener.
- A tick with no usable timestamp (`timeSec` absent or `<= 0`) is bucketed at `Date.now()`, never at the epoch.
- `subscribeDepth` subscribes `Depth` and filters the same way.

`createWidget` handles seeding and `onResync` automatically: it requests fresh history with `noCache: true`, merges buffered live bars, replaces the series while preserving the visible logical range, and resubscribes. At matching timestamps it preserves the history open, combines high/low extrema, uses the latest buffered close, and takes the maximum volume to avoid counting overlapping snapshots twice. It does not reconstruct unseen trades. An automatic refresh failure or empty response leaves the existing chart visible with stale-history status and a `data` error; display updates pause while buffering and reconnect monitoring continue. `widget.reload()` retries and keeps the cache bypass until a load succeeds; same-context manual reload preserves the current time anchor and viewport. See [widget](widget.md#live-history-and-reconnect-recovery).

Only buffered timestamps are merged; other bars retain authoritative history. Whole-bar buffers can carry seed extrema that history corrected, so overlapping bars use conservative reconciliation rather than exact snapshot/tick ordering.

`intervalToSeconds(interval)` returns the seconds per bar for a **fixed-length** code: `D` and `1D` give `86400`, `W`/`1W` give `604800`, `1s`->1, `5m`->300, `4h`->14400.

**It throws rather than guessing.** `UnknownIntervalError` for a code nothing recognises, and a plain error for a calendar or count-driven code, which has no fixed length to report. Before 1.4.0 it answered 60 for both, so a monthly chart wired through this feed quietly bucketed live ticks into one-minute bars under a label saying otherwise. For anything outside `s/m/h/d/w`, register the code and use `resolveInterval` + `bucketStartOf` instead of asking for seconds.

## CandleBuilder

`src/feed/candle-builder.ts`. Pure and deterministic (no `Date`, no rAF), so it unit-tests exactly.

| Option | Default | Meaning |
|---|---|---|
| `intervalSec` | `60` | Bucket size. |
| `volumeMode` | `'ltq-sum'` | `'ltq-sum'` accumulates `tick.ltq`; `'day-delta'` diffs `tick.cumDayVolume`. |
| `lateTickPolicy` | `'foldIntoBar'` | `'foldIntoBar'` merges a tick older than the current bar into it; `'dropOlderThanPrevBar'` returns `null`. |
| `sessionAnchorSec` | `0` | Bucket alignment origin, in UTC seconds. |

`onTick(tick)` returns `{ bar, isNew, provisional? } | null`, `null` only under `'dropOlderThanPrevBar'`. `isNew` is true on the first tick of a bucket, so a host can append rather than replace. `provisional` is true while the bar's open, high, low and volume cover only the ticks this builder saw (2.3.2, below). `bucketStart(t) = anchor + floor((t - anchor) / intervalSec) * intervalSec`. `current()` returns a copy of the forming bar.

`'day-delta'` handles the daily reset: when the incoming cumulative drops below the last one, the new bar starts from 0; otherwise it carries from the previous bar's closing cumulative.

**Seed the builder from the last history bar, and seed it again after every reconnect.** History normally ends *inside* the forming bucket. An unseeded builder opens a fresh bar for that same bucket at whatever tick arrived first, wrong open, volume restarted at zero, and (if you also keep your own array) a duplicate entry for that time. `seed(lastBar, cumDayVolumeSoFar?)` is the fix; the optional second argument sets the `day-delta` baseline to `cumDayVolumeSoFar - (lastBar.volume ?? 0)`.

**Set `sessionAnchorSec` for any interval that does not divide the trading day evenly.** The default anchors buckets to the epoch, so 5-minute bars start at :00/:05 rather than at the session open: 09:15 in Mumbai, 09:30 in New York. The anchor is UTC seconds and knows nothing about the chart's `timezone`, so compute it from the session open you actually want. `zonedWallClockToUtcSeconds(y, m, d, 9, 30, 0, 'America/New_York')` resolves one on a changeover day without an offset table.

```ts
import { CandleBuilder } from 'openalgo-charts';

const builder = new CandleBuilder({ intervalSec: 300, volumeMode: 'ltq-sum', sessionAnchorSec: sessionOpenUtc });
builder.seed(bars[bars.length - 1]);

ws.onLtp((e) => {
  const u = builder.onTick({ time: e.timeSec, price: e.ltp, ltq: e.ltq, cumDayVolume: e.volume });
  if (u !== null) series.update(u.bar);
});
ws.subscribe('LTP', 'RELIANCE', 'NSE');
```

## Stream-driven repair and provisional bars (2.3.2)

Base exports added: `LiveBarMeta`. Existing exports gained members:
`DataLoadingOptions.refreshOnBarClose`, `.refreshOnGap`, `.refreshWindowBars`;
`DataLoadingController.pushBar(bar, meta?)`; `CandleUpdate.provisional`;
`CandleBuilder.reconcile(bar)` and `.isProvisional()`; `DataFeed.subscribeBars`
callbacks receive `(bar, meta?)`.

**Repair follows the stream, not a clock.** All three options are off by default,
and a controller built without them makes exactly the requests it always did.

| Option | Meaning |
|---|---|
| `refreshOnBarClose` | `true` or `{ delayMs?, retries?, retryDelayMs? }` (defaults 2500 ms, 2, 5000 ms). A pushed bar that opens a new bucket means the bar before it closed: one refresh runs `delayMs` later, retried up to `retries` times while the reply still stops short of that bar. Fires on any rollover, fixed-length interval or not. Nothing fires while the stream is quiet. |
| `refreshOnGap` | Refresh at once when a pushed bar skips one or more whole buckets. Needs a fixed-length interval; the window reaches back to the last bar the stream delivered. |
| `refreshWindowBars` | A refresh re-fetches only this many bars back from the tail instead of the whole load window. Needs a fixed-length interval; other intervals keep the whole window. A gap repair widens it to cover the gap. |

A repair requested while a refresh is in flight queues behind it rather than
aborting it. Hiding the tab cancels pending repairs; returning refreshes once,
as before. `pollIntervalMs` still works and is the right backstop for silent
drift, at a slow cadence. `examples/live` uses `refreshOnBarClose: true,
refreshOnGap: true, refreshWindowBars: 5, pollIntervalMs: 120_000`.

**A provisional bar is one the builder opened without having streamed the bar
before it**: a cold builder, or a seed from an older bucket. Either way the
trades between the bucket's true open and the first tick seen were missed, so
its open, high, low and volume are only what the builder saw; the close is
still the latest price. `CandleUpdate.provisional` says so per update and
`isProvisional()` on demand. The bucket after a provisional bar is not
provisional: the builder streamed to its end. Reseeding with `seed()` marks the
lineage unstreamed again, which is the right thing after a socket resync:
`builder.seed(builder.current())`, then refresh.

`reconcile(authoritative)` adopts history's bar for the current bucket: the open
when provisional, the union of the extremes and the larger volume always, the
close kept with the ticks. Returns the merged bar, or `null` for a different
bucket (then `seed` instead). Call it on `reason: 'refresh'` snapshots with the
bar history holds for `builder.current().time`.

`pushBar(bar, { provisional: true })` onto a bar the controller already holds for
that bucket keeps that bar's open and widens the extremes instead of replacing
it, so history's true open survives the next tick. A plain `pushBar(bar)` still
replaces the bar, as it always did. `OpenAlgoLiveDataFeed.subscribeBars` passes
the flag through, and so does the controller's own subscription.

```ts
const data = new DataLoadingController(feed, {
  refreshOnBarClose: true, refreshOnGap: true, refreshWindowBars: 5, pollIntervalMs: 120_000,
});
data.subscribe((s) => {
  if (s.reason === 'state') return;
  if (s.reason === 'refresh') {
    const current = builder.current();
    const held = current && s.bars.find((b) => b.time === current.time);
    if (held) builder.reconcile(held);
  }
  paint(s.bars);
});
ws.onLtp((e) => {
  const u = builder.onTick({ time: e.timeSec, price: e.ltp, ltq: e.ltq });
  if (u) data.pushBar(u.bar, u.provisional ? { provisional: true } : undefined);
});
```

## The interval registry

`src/feed/intervals.ts`, base bundle. An interval code resolves to a **bucketing rule, not a duration**, because three of the four kinds have no duration to state.

```ts
import { registerInterval, resolveInterval, bucketStartOf, isKnownInterval } from 'openalgo-charts';

registerInterval({ code: '1MO', bucketing: { mode: 'calendar', unit: 'month', count: 1 } });
registerInterval({ code: 'T500', bucketing: { mode: 'ticks', count: 500 } });

const { bucketing } = resolveInterval('1MO');
const open = bucketStartOf(bucketing, tickTimeSec, chart.timezone());
```

| `Bucketing` case | Shape | Bar closes when |
|---|---|---|
| `interval` | `{ mode: 'interval', seconds, anchorSec? }` | `seconds` elapse from `anchorSec` (default epoch). |
| `calendar` | `{ mode: 'calendar', unit: 'month' \| 'quarter' \| 'year', count?, timezone? }` | The period ends, at local midnight on the first, in that zone. |
| `ticks` | `{ mode: 'ticks', count }` | `count` trades have printed. |
| `volume` | `{ mode: 'volume', perBar }` | `perBar` quantity has traded. |

This is the vocabulary `TickTimeframe` already used, widened by one case, not a second system. `TickTimeframe` still names exactly the three time-agnostic modes (`interval`, `ticks`, `volume`) and is still re-exported from the tick aggregator; `TickBarAggregator` now takes the wider `Bucketing` plus an optional `{ timezone }`.

| Function | Notes |
|---|---|
| `registerInterval(descriptor)` | Returns a disposer. A registered code **shadows** a built-in token of the same name. |
| `unregisterInterval(code)` | `false` if nothing was registered under it. |
| `registeredIntervals()` | Registration order. Built-in tokens are not listed. |
| `resolveInterval(code)` | Throws `UnknownIntervalError` (which carries `.code`) when nothing recognises it. |
| `tryResolveInterval(code)` | The same, returning `null` instead of throwing. |
| `isKnownInterval(code)` | Boolean probe, for validating an interval picker's input. |
| `bucketStartOf(b, timeSec, zone?)` | UTC seconds the containing bar opened at. Count-driven bars return `timeSec`. |
| `nextBucketStart(b, timeSec, zone?)` | UTC seconds the next bar opens at, or `null` for count-driven bars. |
| `isTimeBucketed(b)` | True for `interval` and `calendar`. |

Codes are matched case-insensitively (`D` and `d` are one interval), because the built-in tokens always were. The built-ins are the old grammar byte for byte: an optional count followed by `s`, `m`, `h`, `d` or `w`.

**A calendar bar is not a fixed number of seconds, and you must not pretend it is.** Buckets are computed as absolute month indices floored to the step, converted back through `zonedWallClockToUtcSeconds`, so a month runs first to first at local midnight in the entry's zone (or the caller's, defaulting to IST). February 2024 is 29 days; March 2024 in `America/New_York` is 31 days minus an hour; quarters land on January, April, July and October. `30 * 86400` is wrong for every one of those.

**An unknown code throws.** That is the deliberate change in 1.4.0, and it is load-bearing: the old silent fall back to 60 seconds drew minute bars under whatever label the caller had chosen. Validate a picker with `isKnownInterval`, and let `resolveInterval` throw on the paths where a wrong timeframe would be a wrong trade.

## Warm-load bar cache

`src/feed/cache.ts`, base bundle. `withBarCache` is a `DataFeed` to `DataFeed` wrapper, so **any** feed gets warm loading, not just `OpenAlgoDataFeed`. A hit ends at the last closed bar and a live subscription supplies the forming one; a host with no subscription asks again with `noCache: true` when a hit ends before a bar it has already shown.

```ts
import { withBarCache, OpenAlgoDataFeed } from 'openalgo-charts';

const feed = withBarCache(new OpenAlgoDataFeed(cfg), { ttlMs: 60_000, max: 24 });

const bars = await feed.getBars({ symbol, exchange, interval, from, to });
await feed.getBars({ symbol, exchange, interval, from, to, noCache: true });  // force a fetch
feed.stats();          // { entries, bars, hits, misses, evictions }
```

| Option | Default | Notes |
|---|---|---|
| `ttlMs` | `300_000` | Absolute age bound. |
| `max` | `24` | Entries before LRU eviction. |
| `maxBars` | `250_000` | Total cached bars before LRU eviction. |
| `storage` | in-memory `Map` | A `BarCacheStore` (`get`/`set`/`delete`, sync **or** async). |
| `now` | `Date.now` | Injectable clock. |
| `intervalSeconds` | `intervalToCacheSeconds` | For tokens this does not know. Return `0` to disable caching for that interval. |

**The key is `symbol|exchange|interval`, and the range is deliberately not in it.** One entry per series holds the widest set fetched so far, and a narrower request is served by slicing it. Keying on the range would miss on every pan and on every "same chart, one bar later" reload, which is exactly the traffic warm loading is meant to remove.

**Freshness is two gates that must both pass.** `ttlMs` bounds absolute age, and a hit past the entry's coverage is allowed only while the bar after the last closed bar is still forming (`nowSec < entry.to + 1 + intervalSec`). The second gate is measured on the feed's own bar grid, not against UTC midnight, so a daily Indian bar opening at 03:45 UTC is judged against its own session. A request reaching further back than the entry's `from` is a real gap at the left edge and always refetches.

**The forming bar is never stored.** This is the rule to carry into any cache you write yourself, not a detail of this one:

> A closed bar is immutable and can be cached freely. **The last bar is alive until its interval ends.** A cache that serves a stale forming bar is worse than no cache at all: the wrong close reaches the last-price line, the axis tag, the header LTP and every indicator computed off it (RSI, VWAP, a Supertrend flip), instantly and with no spinner to warn anyone. This library draws Buy and Sell buttons on the chart; a fast wrong price is a worse failure than a slow right one.

So trailing unclosed bars are dropped on store and coverage ends at the last closed bar. A hit is therefore short by at most that one bar, which a live subscription re-supplies immediately, and is never wrong about a bar it does return.

Other behaviour worth knowing:

- `getBars` passes straight through, uncached, when `from` or `to` is absent (coverage cannot be reasoned about) or the resolved interval is `<= 0` (the caller opting out).
- `BarsRequest.noCache: true` bypasses the cached result and refreshes the entry from the source. Honor or forward it in custom wrappers so reconnect recovery cannot reuse history from before the interruption. `CachedBarsRequest` remains available for existing callers.
- A rejected fetch propagates untouched and leaves the previous entry alone. Nothing is written unless bars arrive.
- Bars are cloned in and out, because live builders mutate bar objects in place.
- `searchSymbols` is forwarded the same way, only when the wrapped feed has it.
- `subscribeBars` and `subscribeDepth` are forwarded **only when the wrapped feed has them**, with every argument, so feature detection still tells a history-only feed from a live one and `OpenAlgoLiveDataFeed`'s third `opts` argument survives the hop. `cache.source` is the wrapped feed.
- Bounds are LRU on entries **and** on total bars, because one intraday series can be 100k bars and an entry count alone does not bound memory. A single series larger than `maxBars` is simply not cached.
- `invalidate({ symbol, exchange, interval })` drops one series; `invalidate()` and `clear()` drop everything this instance knows of. With an injected persistent store, keys written by an earlier session are dropped when next read and found expired, not by `clear()`.
- **Out of hours every load is cold** unless the host helps. The cache cannot know a market is closed, so a request whose `to` is "now" is always past the coverage of an entry that ends at the last session's close. If the host has a session table, cap `to` at the newest bar it expects to exist and the reload goes warm.

## OpenAlgoTradeFeed

`src/feed/openalgo-trade.ts` implements the trade tier's `OrderFeed` over OpenAlgo REST.

```ts
import { OpenAlgoTradeFeed } from 'openalgo-charts';

const trade = new OpenAlgoTradeFeed({
  baseUrl: 'http://127.0.0.1:5000',
  apiKey: 'YOUR_KEY',
  strategy: 'openalgo-charts',   // default
  defaultProduct: 'MIS',         // default; 'CNC' | 'NRML' | 'MIS'
});
```

| Method | Endpoint |
|---|---|
| `place(req)` | `POST /api/v1/placeorder` -> `{ orderId }` (reads `orderid` or `order_id`) |
| `modify(orderId, patch)` | `POST /api/v1/modifyorder` |
| `cancel(orderId)` | `POST /api/v1/cancelorder` |
| `getOrders()` | `POST /api/v1/orderbook` -> `Order[]` |
| `getPositions()` | `POST /api/v1/positionbook` -> `Position[]` |

Every request sends `apikey` in the body. Non-OK responses surface OpenAlgo's own `message` text (RMS rules, square-off windows) rather than a bare status code.

**`modify` requires the full order context, so it throws for an order this feed has never seen.** OpenAlgo's `modifyorder` needs symbol/action/exchange/pricetype/product/quantity, not just the delta. The feed caches that context on `place` and on `getOrders`; modifying an order placed elsewhere means calling `getOrders()` first.

`decodeOrder` / `mapPosition` (exported) coerce OpenAlgo's string-or-number fields and map `order_status` into the chart's vocabulary (`open`/`trigger pending` -> `working`, `pending` -> `pending`, `complete` -> `filled`, `cancelled`, `rejected`; anything else is `'unknown'` with the broker's text in `rawStatus`). `decodeOrder` returns `{ ok: true, order }` or `{ ok: false, issue }` instead of guessing a side or a number. A `trigger_price` of 0 is normalized to `undefined` so an order line does not render at zero. `mapOrder` is deprecated (removed in 3.0.0): it hands back a placeholder row marked `status: 'unknown'` where `decodeOrder` reports the issue, so new code should not call it.

## Writing a custom DataFeed

Complete and sufficient, history plus live bars, no library internals:

```ts
import type { Bar, BarsRequest, DataFeed, UnsubscribeFn } from 'openalgo-charts';

export class MyFeed implements DataFeed {
  async getBars(req: BarsRequest): Promise<Bar[]> {
    const rows = await myApi.candles(req.symbol, req.interval, req.from, req.to);
    return rows
      .map((r) => ({ time: Math.floor(r.epochMs / 1000), open: r.o, high: r.h, low: r.l, close: r.c, volume: r.v }))
      .sort((a, b) => a.time - b.time);
  }

  subscribeBars(req: BarsRequest, onBar: (bar: Bar) => void): UnsubscribeFn {
    const sub = myApi.stream(req.symbol, (msg) => {
      onBar({ time: Math.floor(msg.bucketMs / 1000), open: msg.o, high: msg.h, low: msg.l, close: msg.c, volume: msg.v });
    });
    return () => sub.cancel();
  }
}
```

Rules for any adapter: convert to UTC seconds at the edge, sort ascending, keep one bar per time, and omit `subscribeBars` entirely rather than shipping a no-op, callers feature-detect it. If your source pushes ticks rather than bars, compose a `CandleBuilder` inside `subscribeBars` the way `OpenAlgoLiveDataFeed` does.

## FakeDataFeed and generateBars

Deterministic, network-free, seeded xorshift32, safe for pixel-diff tests.

```ts
import { FakeDataFeed, generateBars } from 'openalgo-charts';

const bars = generateBars(1700000000, 500, 3600);   // startTime, count, intervalSec
series.setData(bars);

const feed = new FakeDataFeed(60);                  // intervalSec, optional scheduler
const off = feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m' }, onBar, { tickMs: 500 });
```

- `getBars` returns 500 bars from `req.from ?? 1_700_000_000`.
- `subscribeBars` genuinely streams (default a 1s `setInterval`), so feature detection stays honest. Pass a `FeedScheduler` `(cb, ms) => UnsubscribeFn` to drive it by hand in tests.
- `generateBars` uses no global randomness and no `Date.now()`, so output is identical across runs.

## Related

- [data-and-time](data-and-time.md): `Bar`, UTC seconds, `update` vs `prependData`, tick bars, the chart timezone and the time helpers.
- [chart-linking](chart-linking.md): a grid of charts on one instrument, and the per-member `onSymbol` that loads its bars.
- [events-and-state](events-and-state.md), `lazy-load` and the rest of the event bus.
- [trading](trading.md) / [trade-tier](trade-tier.md), `OrderFeed`, `OrderEngine`, on-chart order lines.
- [pitfalls](pitfalls.md).

## Managed requests and cache snapshots (2.1.6)

Base exports: `DataLoadingController`, `DataLoadingOptions`, `DataLoadingSnapshot`,
`DataLoadingStatus`, `HistoryLoadingStatus`, `DataUpdateReason`,
`HistoryRequestPool`, `HistoryRequestPoolOptions`, `sharedHistoryRequests`,
`BarsPage`, `BarsPageRequest`, and `BAR_CACHE_VERSION`.

`new DataLoadingController(feed, options)` uses a per-feed shared pool unless
`requestPool` is supplied. Defaults: `pageSize: 500`, `maxEmptyPages: 4`,
`maxBars: 100_000`, `pollIntervalMs: 0`; `timeoutMs` defaults to the pool's 15 s.
`pageWindowSec` defaults to the initial range width; `now` returns UTC seconds.
`loadMore(until?)` pages older history; `until` (UTC seconds) widens a date
feed's window so a far date costs one request instead of one per default window.
The widened window stops at `maxBars` bars of a fixed interval, what retention
could keep; a `getBarsPage` feed keeps its ordinary window, since it pages by count.
Primary states: idle/loading/ready/empty/refreshing/stale/error. History states:
idle/loading/error/exhausted/limited. `hasMore: null` means unknown; never turn
an empty weekend window into permanent exhaustion. `limited` is local retention.

`HistoryRequestPool` defaults to 4 concurrent requests and 15 s per consumer,
including queue time. `getBars(req, priority?)` and `getBarsPage(req, priority?)`
share identical payloads within one feed object. Higher priority runs first.
Cancellation/deadlines are independent; the final consumer aborts the transport.
The REST adapter bounds fetch and JSON body reads. Feeds ignoring AbortSignal
cannot publish obsolete results through the controller, but may continue network work.

`BarsPageRequest` adds required exclusive `before` and `countBack`; `BarsPage`
returns `{ bars, hasMore?, nextBefore? }`. Custom cursor values must move backward.
`getCachedBars(req)` returns an optional closed-bar snapshot without fetching.
The controller paints it as refreshing and fetches authoritative history; cache
peek time is bounded to 500 ms. Never treat a warm snapshot as a live forming bar.

The cache validates entries and writes `CachedBars.version = BAR_CACHE_VERSION`
(currently 1), accepting valid unversioned legacy entries. Storage failures fall
back to bounded memory. A failed durable delete is suppressed per instance and
may remain visible to another process. Direct cache calls are not coalesced;
use the pool/controller. `MarketDepth.timeSec` preserves valid exchange timestamps;
Depth frames with only book quantities do not supply executed-trade volume.

## Quote and news contracts (2.5.5)

Optional provider contracts, types only in the base entry (no runtime bytes), for the
widget's watchlist and news panels or a host's own. They are separate from `DataFeed`:
a quote comes only from a `QuoteFeed`, never from a bar's close, and a host without one
shows no price.

- `InstrumentKey`: `{ symbol, exchange }`, both opaque and compared exactly.
- `QuoteSnapshot extends InstrumentKey`: `last`, optional `previousClose` (the reference
  for change figures), `bid`, `ask`, `volume`, `time` (exchange UTC seconds) and
  `delayed`. An absent field is unknown, never zero.
- `QuoteFeed.getQuotes({ instruments, signal })` returns snapshots; an instrument left
  out of the answer is unknown. Optional `subscribeQuotes(instruments, { onQuote,
  onStatus })` returns an `UnsubscribeFn`. `QuoteStreamStatus` is `'connecting' | 'live'
  | 'reconnecting' | 'disconnected'`; quotes held while a stream is not live are stale,
  and a consumer refetches snapshots when it becomes live again. The first quote a
  stream delivers counts as evidence it is live when the provider reports no status.
  The widget subscribes one instrument per call so it can release exactly the rows that
  scroll away; a provider multiplexes them over its own connection.
- `NewsFeed.getNews({ symbol, exchange, cursor?, limit, signal })` returns a `NewsPage`
  `{ items, nextCursor? }`, newest first; `nextCursor` absent or null means no older page.
  `NewsItem`: `id` (stable, used to drop repeats across pages), `headline`, `source?`,
  `time` (UTC seconds), `summary?`, `url?`. Every text field is plain text; a consumer
  never renders it as markup and opens only http and https links.

Types: `InstrumentKey`, `QuoteSnapshot`, `QuoteRequest`, `QuoteStreamStatus`,
`QuoteStreamHandlers`, `QuoteFeed`, `NewsRequest`, `NewsItem`, `NewsPage`, `NewsFeed`.

## Data variants: session, adjustment, currency, unit (2.5.6)

Base exports: `normalizeDataVariant`, `dataVariantKey`, `unsupportedDataVariant`,
`dataVariantError`, `publishDataContext`, and the types `DataVariant`, `DataSession`,
`DataAdjustment`, `DataVariantDimension`, `DataVariantCapabilities`, `DataVariantQuery`,
`DataContextTarget`. Indicators tier: `inheritedDataVariant`.

Regular and extended hours, adjusted and raw prices, and a quote currency or unit are
each a **different series from the provider**, not a view of one series. Extended hours
add bars the regular series does not have; an adjusted history rewrites every price
before a corporate action. So a variant is identity, like the symbol:

```ts
interface DataVariant {
  session?: 'regular' | 'extended';
  adjustment?: 'adjusted' | 'raw';
  currency?: string;   // the provider's own name, compared exactly
  unit?: string;       // the provider's own name, compared exactly
}
// BarsRequest.variant?: DataVariant        absent is the provider's default series
// DataFeed.dataVariants?(query): DataVariantCapabilities | Promise<...>
interface DataVariantCapabilities { sessions?; adjustments?; currencies?; units? }
```

- **Never convert or adjust locally.** A variant is served by a provider that declares
  it, or it is unsupported. There is no fallback that derives extended hours, raw prices
  or another currency from the default series: it would look exactly like the provider's
  own and be wrong in ways nobody could see.
- **Declaring.** `dataVariants({ symbol, exchange, interval, signal })` lists what the
  provider serves for that instrument and interval. A dimension absent or empty serves
  only the default. A feed without the method serves only its default series.
  `unsupportedDataVariant(capabilities, variant)` returns the first undeclared field
  (`'session'`, `'adjustment'`, `'currency'`, `'unit'`) or null.
- **The default is its own identity.** `{}` and no variant are the provider's default;
  `{ session: 'regular' }` asks for regular hours by name, whatever the default is.
  `normalizeDataVariant` returns a frozen copy in a fixed field order, undefined for the
  default, and throws a `TypeError` for an unknown value or field.
- **Keys.** `dataVariantKey(variant)` is `''` for the default, so `barCacheKey` and
  every other key that appends it stays byte-identical for a request with no variant:
  entries persisted before variants existed still match. `withBarCache` keys each
  variant separately (`invalidate({ symbol, exchange, interval, variant })` drops one),
  forwards `dataVariants`, and `HistoryRequestPool` never shares a request between two
  variants.
- **`DataLoadingController`.** `load(req)` normalises the variant (a request naming `{}`
  carries no `variant` field at all), asks the feed's declaration before the cache or the
  network, and publishes status `'unsupported'` with `snapshot.unsupported` (the
  dimension) and a `DataVariantUnsupportedError` when it is not declared: nothing is
  fetched, streamed, refreshed or paged. A declaration that rejects or times out is
  status `'error'`, and until the provider answers nothing fetches or pages the variant
  either: `loadMore` does nothing and `refresh` (the widget's Retry) asks the
  declaration again through a new load. A new `load` with another variant is a new
  source: the previous request is aborted, the stream released and the bars cleared.
  Hosts that switch exhaustively on `DataLoadingStatus` gain the `'unsupported'` case.
- **OpenAlgo adapters.** `OpenAlgoDataFeed.getBars` and `OpenAlgoLiveDataFeed.subscribeBars`
  refuse any non-default variant with `dataVariantError` (name
  `DataVariantUnsupportedError`): the history API has one series per instrument.
  `FakeDataFeed.getBars` and `subscribeBars` refuse the same way, since the synthetic
  feed has one series too, whether it is called directly or through `withBarCache`.
- **Chart data context.** `ChartDataContext.variant` carries the variant to studies and
  hosts. Set it with `publishDataContext(chart, context)`, which normalizes the variant.
  Since 2.6.0 `chart.setDataContext` compares the variant too, so a change of variant
  alone is a new source (requested bars aborted, source revisions restarted, studies told
  `'context'`) without changing the instrument, so event markers, linked drawings and news
  stay, and `data:context` fires once. `Instrument.applyTo` keeps the context variant.
  Before 2.6.0 the chart ignored a variant-only change, and the helper passed through an
  interval-less context first, marked so the library's own listeners skip it; a host saw
  two events. The helper still takes that detour for a target that keeps the old variant.
- **Alerts.** `AlertScope.variant` records a non-default variant (the default adds no
  field); an alert evaluates only on its own variant, and a fixed price is not drawn in
  another currency or unit. See [alerts](alerts.md).
- **Requested contexts.** `IndicatorBarsRequest.variant` names the series another
  instrument is asked in. `createRequestedIndicator` and `createTier2Indicator`'s
  `requestBars` inherit `inheritedDataVariant(chart variant)`, the session and the
  adjustment (how bars are observed) but not the currency or unit (what the other
  instrument is quoted in), unless the request names a variant itself (`{}` included).
  A change of the chart's variant alone restarts both kinds of study.
- Widget, grid and workspace carry it too: see [widget](widget.md) and
  [workspaces](workspaces.md).
