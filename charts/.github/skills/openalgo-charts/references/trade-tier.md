# Trade tier (`openalgo-charts/trade`)

`orderConstraintsForInstrument(instrument)` maps a validated base `Instrument` to
the existing `OrderConstraints`: price tick, quantity grid and fractional quantity
support, plus `tickSchedule` when the metadata carries `tickBands` (a constant
tick returns the same three fields as before, and its `instrument.tickSchedule`
is null). Steps remain in the adapter's order
units, without multiplying lots.
Use `validateQuantity`/`validatePrice` for advisory checks and add host price-band
or freeze limits when available. See [instrument metadata](../../../../docs/instruments.md).

*When to read this: placing, modifying or cancelling real orders from the chart, the order engine, its state machine, pre-trade validation, OCO brackets and the depth ladder.*

Source of truth: every file in `src/trade/`, plus `src/feed/openalgo-trade.ts` (the `OrderFeed` adapter) and `src/feed/types.ts` (`MarketDepth`). Tests: `tests/trade.test.ts`, `tests/order-engine.test.ts`, `tests/dom-ladder.test.ts`. Demos: `examples/phase8-trade.html`, `examples/phase9-chart-trading.html`, `examples/phase10-dom.html`.

Separate bundle entry: `import { OrderEngine } from 'openalgo-charts/trade'` -> `dist/openalgo-charts.trade.mjs`. `OpenAlgoTradeFeed`, `decodeOrder`, `mapPosition` (and the deprecated `mapOrder`, removed in 3.0.0) are in the **base** package, not this one.

## Which tier

| Need | Use |
|---|---|
| Render broker state you already hold, get gestures back as events | [`chart.trading`](trading.md) (base) |
| Client-side order lifecycle, idempotency, validation, OCO, arm/confirm | `OrderEngine` (this tier) |
| Reconcile whole order/position book snapshots into primitives | `TradeController` (this tier) |
| Depth-of-market ladder | `DomLadder` (this tier) |

They are independent: `chart.trading` uses `TradingPosition`/`TradingOrder` and `PriceLine`; this tier uses `Order`/`Position` and its own primitives.

**`chart.trading` and this tier both route drag-modify and cancel through `chart.subscribeDrag` and `chart.subscribeClick`**: the `TradingController` subscribes on first access to `chart.trading`, and a host of this tier subscribes itself (below). Since 2.6.0 both methods take several subscribers, so neither silences the other. Before 2.6.0 they were single-slot setters: whoever registered last won and the other went silently dead, so on an older release keep the two off one chart.

## Data model (`src/trade/types.ts`)

```ts
type OrderSide = 'BUY' | 'SELL';
type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
type OrderStatus = 'pending' | 'working' | 'partial' | 'filled' | 'cancelled' | 'rejected';
type OrderRole = 'entry' | 'sl' | 'tp';

interface Order {
  id: string; symbol: string; side: OrderSide; type: OrderType;
  qty: number; filledQty: number; price: number;
  triggerPrice?: number; status: OrderStatus; parentId?: string; role?: OrderRole;
}
interface Position { symbol: string; netQty: number; avgPrice: number; accountId?: string }  // netQty signed
```

`isWorking(o)` is true for `pending | working | partial`, the canonical "still live in the book" filter. Note these are *broker* statuses, distinct from the engine's `ClientOrderState` below.

## `OrderEngine`

```ts
interface OrderEngineOptions {
  feed: OrderFeed;                 // required
  constraints: OrderConstraints;   // required
  mode?: TradeMode;                // default 'live'
  armed?: boolean;                 // default false
  gate?: GateFn;
  minModifyIntervalMs?: number;    // default 150
  now?: () => number;              // default performance.now()
  idGen?: () => string;            // default 'c1', 'c2', ...
  onValidationError?: (reason: string) => void;
}
type TradeMode = 'live' | 'analyzer';
type GateFn = (req: PlaceRequest) => boolean | Promise<boolean>;
```

The broker interface you implement:

```ts
interface OrderFeed {
  capabilities?: TradingCapabilitySource;   // place/modify/cancel restrictions
  features?: TradingFeatureSource;          // the newer operations below; omitted declares none
  place(req: PlaceRequest & { mode: TradeMode }): Promise<{ orderId: string }>;
  modify(orderId: string, patch: { price?: number; triggerPrice?: number; qty?: number }): Promise<void>;
  cancel(orderId: string): Promise<void>;
  previewOrder?(req): Promise<OrderPreview>;              // read-only
  closePosition?(req: ClosePositionRequest & { mode }): Promise<CommandReceipt>;
  reversePosition?(req: ReversePositionRequest & { mode }): Promise<CommandReceipt>;
  placeBracket?(req: BracketOrderRequest & { mode; legClientTokens: { stopLoss; takeProfit } }): Promise<BracketReceipt>;
}
interface PlaceRequest {
  symbol: string; exchange?: string; side: OrderSide; type: OrderType; qty: number;
  price?: number; triggerPrice?: number;
  product?: 'CNC' | 'NRML' | 'MIS';
  clientToken?: string;            // idempotency token
  account?: string;                // needs features.accounts
  duration?: OrderDuration;        // 'DAY' | 'IOC' | 'FOK' | 'GTC' | 'GTD', must be in features.durations
  expiresAt?: number;              // GTD only, UTC seconds, in the future
  leverage?: number;               // needs features.leverage
}
interface PlaceResult { ok: boolean; clientId?: string; state?: ClientOrderState; reason?: string }
```

`OrderFeed` is **not** the base package's `TradeFeed`, which is deprecated (removed in 3.0.0) and taken by nothing. Implement `OrderFeed` for the engine.

| Method | Behaviour |
|---|---|
| `placeOrder(req)` | validate -> idempotency -> gate -> `feed.place` -> `ack`/`reject`. Returns `PlaceResult` |
| `placeMarket(symbol, side, qty)` | `placeOrder({ symbol, side, type: 'MARKET', qty })` |
| `requestModify(clientId, price)` | Validates, coalesces, sends at most every `minModifyIntervalMs` |
| `commitModify(clientId)` | Force-flushes the pending modify. Call on drag end |
| `cancelOrder(clientId)` | `submitCancel` -> `feed.cancel` -> `cancelled`, then cancels the OCO peer |
| `linkOco(clientIdA, clientIdB)` | Mutual peer link |
| `onFill(brokerId, full)` | Broker fill in. `full: true` also cancels the peer |
| `onReconnect(presentBrokerIds: ReadonlySet<string>)` | Any non-terminal order absent from the set -> `stale` |
| `state(clientId)` | `ClientOrderState \| undefined` |
| `mode` (getter) | The configured `TradeMode` |

There is **no `placeLimit`** despite what `website/pages/docs/trading.mdx` shows in its DOM-ladder snippet. Use `placeOrder({ ..., type: 'LIMIT', price })`.

### Arming, the gate, and analyzer mode

`armed: false` (the default) routes every order through `gate`. With no `gate` supplied, the engine awaits `Promise.resolve(false)` and every order returns `{ ok: false, reason: 'not confirmed' }`.

**A default-constructed `OrderEngine` places nothing.** Either pass `armed: true` or pass a `gate`. Silent no-ops here look exactly like a broken network.

`mode` is *only* forwarded as `feed.place({ ...req, mode })`. **The engine does not gate anything on `mode`, and `OpenAlgoTradeFeed` drops the field before it reaches the wire**: its `place()` body is `{ strategy, symbol, action, exchange, pricetype, product, quantity, price, trigger_price, disclosed_quantity }`, with no `mode` key. Analyzer/sandbox is a server-side OpenAlgo toggle (`/auth/analyzer-mode`, response field `data.analyze_mode`), not something this field turns on. Treat `mode: 'analyzer'` as a label your own adapter must honour; verify the server is in analyzer mode before trusting it.

### Idempotency and modify throttling

`clientToken` (or a generated id) is recorded before the network call; a repeat returns `{ ok: false, reason: 'duplicate clientToken (idempotent skip)' }` with no second send. On a thrown `feed.place` the token is **released**, so the same request is retryable after a transient transport failure.

`requestModify` validates first: an invalid price is neither queued nor sent, and surfaces through `onValidationError(reason)` so the UI can snap the line back. Only the latest price survives coalescing, and the flush no-ops until `place` has acked (it needs the broker id).

## Order state machine (`src/trade/order-state-machine.ts`)

States: `pending_place`, `working`, `partial`, `filled`, `modify_pending`, `cancel_pending`, `rejected`, `cancelled`, `stale`.
Events: `ack`, `partialFill`, `fill`, `reject`, `submitModify`, `submitCancel`, `cancelled`, `reconnectAbsent`.

| From \ Event | `ack` | `partialFill` | `fill` | `reject` | `submitModify` | `submitCancel` | `cancelled` | `reconnectAbsent` |
|---|---|---|---|---|---|---|---|---|
| `pending_place` | `working` | `partial` | `filled` | `rejected` | none | none | none | `stale` |
| `working` | none | `partial` | `filled` | none | `modify_pending` | `cancel_pending` | `cancelled` | `stale` |
| `partial` | none | `partial` | `filled` | none | `modify_pending` | `cancel_pending` | `cancelled` | `stale` |
| `modify_pending` | `working` | `partial` | `filled` | `working` | none | none | `cancelled` | `stale` |
| `cancel_pending` | none | none | `filled` | `working` | none | none | `cancelled` | `stale` |
| `filled` / `cancelled` / `rejected` / `stale` | none | none | none | none | none | none | none | none |

`transition(state, event)` returns the **same state** for a disallowed event, it never throws, so spurious broker events are absorbed silently. Use `canTransition(state, event)` when you need to know. `isTerminal(state)` is true for `filled`, `cancelled`, `rejected`, `stale`.

Note the asymmetry: in `modify_pending`, `reject` means "the amend failed, the order is still working" and goes to `working`, not `rejected`.

## Validation (`src/trade/validation.ts`)

```ts
interface PriceBand { lower: number; upper: number }
interface OrderConstraints { tickSize: number; tickSchedule?: TickSchedule | null; priceBand?: PriceBand; freezeQty?: number; lotSize?: number; allowFractionalQty?: boolean }
interface ValidationResult { ok: boolean; reason?: string; code?: ValidationCode; price?: number }

withinPriceBand(price, band): boolean            // inclusive on both bounds
validateOrder(price, qty, c): ValidationResult
```

Check order: `qty <= 0` -> reject; `qty > freezeQty` -> reject; snap with `roundToTick(price, tickSize)`; band check runs on the **snapped** price. On success `price` holds the snapped value, always use `result.price`, not your input. `roundToTick` is `Math.round(value / step) * step` and returns raw floats (`100.05000000000001`), so format for display and never compare with `===`.

### Price-dependent ticks

`tickSchedule` replaces the constant snap: `validatePrice` rounds with `tickSchedule.round(price)`, which returns exact decimals (`===` is safe), the nearer valid price at any price-to-tick ratio, and rounds a written halfway price up. Null, like absent, keeps the constant `tickSize` snap. `tickSize` is then read only by older code; give it `tickSchedule.minMove`. The price band still runs on the snapped price, so a price inside the limits as typed can snap outside them and be refused. `OrderEngine.placeOrder` (typed prices, triggers included) and `requestModify` (drags, a stop-limit's carried trigger included) both go through it. A plain band list in place of a `TickSchedule` throws a `TypeError` naming `new TickSchedule(bands)`.

```ts
import { TickSchedule } from 'openalgo-charts';
const ticks = new TickSchedule([{ tick: 0.01 }, { from: 10, tick: 0.05 }, { from: 100, tick: 0.1 }]);
validatePrice(10.03, { tickSize: ticks.minMove, tickSchedule: ticks }); // { ok: true, price: 10.05 }
validatePrice(9.996, { tickSize: ticks.minMove, tickSchedule: ticks }); // { ok: true, price: 10 }
```

Band rules (`src/feed/tick-schedule.ts`): the first band has no `from` and covers every lower price, zero and negatives included; each later `from` is inclusive and strictly ascending; every `from` must be a multiple of the ticks on both sides of it; ticks are positive with at most 12 decimals; 1 to 64 bands. Anything else throws `Invalid tick schedule: ...` naming the band. An exact boundary takes the upper band's tick (`tickAt(10) === 0.05`); `step(price, n)` moves whole ticks across bands, down from a boundary on the band below. A floor such as "no negative prices" is a price band, not a tick rule. Real venue schedules come from the host; the library ships none.

`OrderEngine.placeOrder` skips the price path entirely when `req.price` is undefined and only checks `qty > 0`. **A `MARKET` order bypasses the freeze-quantity check.**

## P&L helpers (`src/trade/pnl.ts`): pure, LTP-hot-path safe

```ts
unrealizedPnl(position, ltp): number              // (ltp - avgPrice) * netQty
unrealizedPnlPercent(position, ltp): number       // signed % of entry notional; 0 if avgPrice or netQty is 0
breakeven(position, chargesPerUnit = 0): number   // avgPrice + dir * chargesPerUnit; avgPrice when flat
riskReward(entry, stop, target): number | null    // |target-entry| / |entry-stop|; null when risk is 0
bracketValid(side, entry, stop, target): boolean  // BUY: stop<entry && target>entry; SELL: inverted
```

## Primitives

| Class | Constructor | Draws | Hit ids | zOrder |
|---|---|---|---|---|
| `WorkingOrderLine` | `(order: Order, { extentFromRight? })` | Dashed line, `[SIDE][qty][TYPE price +/-dist][cancel]`, axis price tag | `order:<id>` (`ns-resize`), `order:<id>::close` (`pointer`) | `normal` |
| `PositionMarker` | `(position: Position, { extentFromRight? })` | Entry line, entry->LTP band tinted by P&L sign, `[LONG\|SHORT][qty][pnl (pct)][cancel]` | `position:<symbol>`, `position:<symbol>::close` (both `pointer`) | `normal` |
| `BracketGroup` | `(state: BracketState)` | Shaded risk/reward zones, SL/TP dashed lines with chips, an R:R chip | `bracket-sl:<symbol>`, `bracket-tp:<symbol>` (`ns-resize`) | `bottom` |

```ts
interface BracketState { symbol: string; side: OrderSide; entry: number; stop: number; target: number }
```

`extentFromRight` defaults to `0.5`, clamped `0.1..1`. All three take `update(...)`; the first two take `setLtp(ltp)`. `WorkingOrderLine` renders at `triggerPrice ?? price`, dims when `status === 'pending'`, and shows `filledQty/qty` once partially filled. `PositionMarker` draws nothing when `netQty === 0`.

**`BracketGroup` is purely visual, it carries no OCO logic.** One-cancels-other is `OrderEngine.linkOco(a, b)`, keyed on client ids.

## `TradeController` / `TradeHost`

```ts
interface TradeHost { addPrimitive(p: IPrimitive): void; removePrimitive(p: IPrimitive): void }

const tc = new TradeController(chart.tradeHost());  // the price pane; tradeHost(n) for another pane
tc.reconcile(orders, positions);   // full snapshot; idempotent, safe on every update and reconnect
tc.onLtp('RELIANCE', 2950);        // pushes into every bound primitive
```

`reconcile` diffs by `Order.id` and `Position.symbol`: new -> add, existing -> `update`, missing -> remove. Reconnect needs no special path, a fresh snapshot without a stale order removes its line. Rules: orders failing `isWorking` are skipped; orders with `role: 'sl' | 'tp'` are **excluded from standalone lines** and folded into a `BracketGroup`; a bracket only appears when a non-flat position exists for that symbol (SL uses `triggerPrice ?? price`, TP uses `price`). Introspection: `orderLineCount()`, `positionCount()`, `bracketCount()`.

## `DomLadder`

```ts
interface DomLadderOptions { tickSize: number; tickSchedule?: TickSchedule | null; width: number; groupBy: number; maxRows: number; rowHeight: number }
const DEFAULT_DOM_LADDER_OPTIONS = { tickSize: 0.05, width: 96, groupBy: 1, maxRows: 60, rowHeight: 14 };
```

A right-docked depth strip drawn on the overlay (`zOrder: 'top'`), price-aligned to the pane's price scale. With `tickSchedule` (an instrument whose tick changes with price) every row is a price its own band allows and `groupBy` counts whole ticks of that band (a fraction rounds down, so 2.5 groups by 2, where the constant path would make rows 2.5 ticks apart and off the tick grid), so a ladder across a boundary changes step there and `tickSize` is unused. A band list in its place throws a `TypeError` at construction. Input is one method: `setDepth(depth: MarketDepth)`, called on every book update. `tier()` returns the current `LadderTier`. Rows hit-test as `ladder-bid:<price>` / `ladder-ask:<price>` with a `pointer` cursor, route them to a place-order flow.

`MarketDepth` (from `src/feed/types.ts`) is `{ bids: DepthLevel[]; asks: DepthLevel[]; ltp: number; ltq?: number }` with `DepthLevel = { price: number; qty: number; orders?: number }`. Length is whatever the broker streams, **5 to 200 levels**.

Pure helpers, exported for custom rendering and tests:

| Function | Signature | Notes |
|---|---|---|
| `ladderCapability` | `(depth) => LadderTier` | `0` levels -> `'none'`; `<= 5` -> `'compact'`; else `'deep'` |
| `buildRows` | `(depth, tickSize: number \| TickSchedule, groupBy = 1) => LadderRow[]` | Merges bids+asks into `{ price, bidQty, askQty }`, bucketed to `tickSize * groupBy`, sorted high->low. Total qty is preserved across aggregation. With a `TickSchedule` (any non-null object takes this path; a number or numeric string keeps the constant one), each level lands on its band's nearest valid price and a group spans `groupBy` whole ticks of that band, a fraction rounding down, never labelled past a boundary |
| `visibleRows` | `(rows, priceToY, plotHeight, rowHeight, maxRows) => LadderRow[]` | Culls off-screen rows (±1 row), then keeps the `maxRows` nearest the vertical centre, re-sorted high->low |

Depth arrives through the feed's optional `subscribeDepth(req, onDepth)`, `OpenAlgoLiveDataFeed` implements it over WS mode `'Depth'`.

```ts
const ladder = new DomLadder({ tickSize: 0.05, width: 110, maxRows: 60, groupBy: 1 });
chart.tradeHost().addPrimitive(ladder);   // beside the candles, wherever the price pane sits
feed.subscribeDepth({ symbol, exchange, interval }, (d) => ladder.setDepth(d));
```

**`DomLadder` options are constructor-only.** There is no `setOptions`; changing `groupBy`, `width` or `maxRows` means building a new ladder and re-adding it.

**The strip overlays the plot, it does not reserve layout space.** Widen `priceAxisWidth` or accept that the rightmost `width` px of candles sit under the ladder.

## `FakeBroker`

Deterministic in-memory `OrderFeed` for tests and offline demos. Members: `onBook(cb)` / `setBook(orders, positions)` (copies its inputs), `onLtp(cb)` / `emitLtp(symbol, ltp)`, `onDepth(cb)` / `emitDepth(symbol, depth)`, `place`/`modify`/`cancel` (broker ids `B1`, `B2`, …), `fill(orderId)`, `orders()` / `positions()`, the test hook `rejectNextPlace = 'reason'` (next `place()` throws once, as an answer lost on its way back: the engine settles it as ambiguous and keeps the token; for a broker's refusal use `failNext('place', 'reject')` with `accounts`), and `static makeDepth(ltp, levels, tickSize = 0.05)`.

`new FakeBroker()` (no options) is the original book simulator and declares no `features`: `place()` marks `MARKET` orders `'filled'` and everything else `'working'`, appends to the order book and never updates `positions` (seed those with `setBook`). A request carrying `account`, `duration`, `expiresAt` or `leverage` is refused, and the engine refuses every newer operation against it.

`new FakeBroker({ accounts, features?, now?, latency? })` (`FakeBrokerOptions`, `FakeAccountSeed` = `{ id, name?, mode, currency?, balance, leverage?, maxLeverage? }`) also simulates a provider with account ledgers. It implements `AccountFeed` and every optional `OrderFeed` method, declares every feature and duration unless `features` narrows it, and:

- fills `MARKET` orders at the mark (`setMark(symbol, price)`, which `emitLtp` also sets), averages, realizes and flips positions per account (`accountPositions(id)`), records executions and order history with the echoed client token, duration and expiry;
- reports balance, equity, margin used and available (margin is `|netQty| x avgPrice / leverage`), pushing snapshots to `subscribeAccount` on every change and mark;
- cancels an unmarketable `IOC`/`FOK` limit at once, lapses a `GTD` order at its expiry, and links bracket legs itself (an entry fill starts them, a leg fill cancels its sibling), echoing on each leg the token in `legClientTokens`;
- refuses like a server, with an error marked `rejected: true` (`isBrokerRejection`): unknown account, the other ledger's account (`mode` mismatch), an undeclared feature, no mark, missing margin, leverage above `maxLeverage`, a close larger than the position, a cancel or modify of an order that has already filled or ended;
- test hooks: `latency(operation, accountId)` holds any answer, `failNext(operation, 'reject' | 'timeout' | 'lost-response', reason?)` (`FakeBrokerOperation`, `FakeBrokerFailure`), `disconnect()` / `reconnect()` (streams get `onError`; a call made while down fails pre-flight, `isPreflightFailure`, so the engine blocks it and frees its token, while one already out fails without applying, as a lost answer would), `onOrderUpdate(cb)` the order stream with `FakeOrderInfo` (`accountId`, `clientToken`, `command`), and `muteOrderUpdates(true)` for a silent stream.

## Accounts, preview, durations and position commands

Declared with `TradingFeatures` on `OrderFeed.features` / `AccountFeed.features` (a `TradingFeatureSource`: an object or a synchronous provider of one). **Unlike `TradingCapabilities`, an omitted feature is unsupported.** Flags: `accounts`, `executions`, `orderHistory`, `preview`, `leverage`, `close`, `partialClose`, `reverse`, `brackets` (each `boolean | 'unknown'`), and `durations: OrderDuration[]` (`ORDER_DURATIONS` lists all five). `checkTradingFeature(source, { feature, ... })` answers `{ supported } | { supported: false, reason }`; `tradingFeatureLabel(feature)` is the wording its reasons use. `OrderEngineOptions.features` and `AccountManagerOptions.features` add host restrictions (either side can refuse).

`AccountManager` (`new AccountManager({ feed, mode?, features?, initialAccount? })`) is read-only and implements `AccountStateSource` (`getState()`, `subscribe(listener)`, `select(id)`), which the widget's `account` option takes:

| Member | Behaviour |
|---|---|
| `getState()` | `AccountState`: `status` (`unsupported` with `reason`, `idle`, `loading`, `ready`, `stale`, `error`), `mode`, `accounts` (only this mode's), `selectedId`, `snapshot` (`AccountSnapshot`: `accountId`, `mode`, `asOf` UTC seconds, `currency?`, `balance?`, `equity?`, `marginUsed?`, `marginAvailable?`, `unrealizedPnl?`, `realizedPnl?`, `leverage?`), `generation` |
| `refresh()` / `reconnect()` | List accounts (other-mode accounts dropped), keep or choose the selection, load its snapshot, subscribe. Figures on screen stay until the answer |
| `select(id)` | Aborts the previous snapshot and history reads, unsubscribes the old stream, clears the old figures, loads the new. A late answer for the old account resolves `{ ok: false, cancelled: true }` and is never shown |
| `disconnected(reason?)` | Keeps the last figures as `stale` (or `error` when there were none) and abandons what is in flight. A stream's `onError` calls it |
| `positions()`, `executions(query?)`, `orderHistory(query?)` | `AccountReadResult`: `{ ok: true, accountId, rows, dropped }` or `{ ok: false, reason, cancelled?, unsupported? }`. Rows naming another account and unreadable rows are dropped and counted. Executions and history rows always name theirs; a position row names one only when the provider stamps `Position.accountId` (`FakeBroker` does), and one without it is taken as the selected account's, the account the provider was asked for. `AccountHistoryQuery` filters `symbol`, `from`, `to` (UTC seconds), `limit` |
| `selectedAccount()`, `destroy()` | |

Snapshots are validated: a non-finite figure is an unreadable snapshot (`error`), a snapshot naming another account or the other ledger is refused, and a pushed reading older than the one shown is ignored. `TradingAccount`, `Execution` and `OrderHistoryEntry` (`accountId`, `order`, `time`, `clientToken?`, `duration?`, `expiresAt?`, `command?`) are the row types.

`OrderEngine` additions:

- `selectedAccount: accounts` (the `AccountManager`, or any `{ getState() }` source; a `() => id` function also works) stamps the selected account on every order and command, refuses a selection from the other ledger (`The selected account X is in live mode, not analyzer`, checked on the view's mode and the account's own; a bare id function cannot be checked), refuses one naming a different account, refuses `No account is selected`, and after confirmation refuses `The account changed before the order was sent; nothing was sent` (token released). An order already sent stays with its account; `orderAccount(clientId)` reads it.
- `account`, `duration`, `expiresAt`, `leverage` are checked before confirmation and again after: an undeclared one is refused (`... is not declared by this provider`), never dropped. `GTD` needs a future `expiresAt` (`clock`, UTC seconds, default `Date.now() / 1000`); an expiry needs `GTD`.
- `previewOrder(req)`: `PreviewResult` = `{ ok: true, preview: OrderPreview, request }` or `{ ok: false, reason, unsupported?, stale? }`. Claims no token, never calls `place`, is `stale` when the account changed while it was out. `OrderPreview` carries `estimatedPrice`, `estimatedValue`, `marginRequired`, `marginAvailableAfter`, `fees`, `currency`, `warnings`, `rejectReason`, `asOf`.
- `closePosition({ symbol, qty? })` (`partialClose` feature when `qty` is set, validated against lot and freeze limits), `reversePosition({ symbol })` and `placeBracket({ ...PlaceRequest, stopLoss, takeProfit })` return `CommandResult` (`PlaceResult` plus `kind` and, for a bracket, `legs` client ids `<token>:stop` / `<token>:target`). Each has its own `clientToken`. They need the feature **and** the feed method; otherwise they are `BLOCKED` with a reason. **An opposite order is never sent instead.** `TradingCommand` is what `confirmCommand` approves when not `armed` (omitted declines, like the gate). The place flag and `modes` still apply (a host lock stops them); `orderTypes` does not apply to close or reverse.
- A close or reverse whose outcome is unknown (`SUBMITTING`, `SUBMITTED`, `AMBIGUOUS`, `RECONCILING`) blocks another on the same account and symbol: `A previous close or reverse for X is unresolved; reconcile it with the broker first`. An omitted exchange matches any exchange, since it is whatever default the provider applies; two different exchanges named outright are two positions.
- A feed error marked `rejected: true` (`BrokerRejection`, `isBrokerRejection`) is the broker's explicit refusal: the row settles `SETTLED` with `brokerStatus` `rejected`; the token stays claimed. Any other non-preflight error is `AMBIGUOUS`, as for orders.
- `onBrokerOrder({ id, clientToken?, status, parentId?, role? })` (`BrokerOrderUpdate`; an `Order` row spreads into it, `onBrokerOrder({ ...order, clientToken })`) applies an order-stream or book row by broker id, or binds an unknown id through the echoed client token: how an `AMBIGUOUS` write whose answer was lost gets its id and outcome. The broker's status replaces the terminal state the client guessed for an `AMBIGUOUS` row (`rejected` for a lost answer, `stale` for a row a snapshot missed), so one reported `pending` or `working` is a live order again: modifiable, cancellable, and never pruned as settled. A stream status that arrives before the transport answers outranks it. `releaseAmbiguous(clientId)` drops an `AMBIGUOUS` row after the host has established from the complete book that it never arrived. A provider bracket's legs are adopted on first sight: by the leg token the engine sent in `legClientTokens` (`<token>:stop`, `<token>:target`, claimed with the entry token and refused as duplicates like it), or by `parentId` (the entry's broker id) and `role` (`sl`, `tp`). A leg row naming an entry the engine has not bound yet (a history listed newest first, or a stream that reports the legs before the transport returns the entry's id) is held and applied when the entry binds, by its echoed token or by the receipt, so rows may arrive in any order. Rows are held only while a bracket the engine sent is still waiting for its entry's id, for at most 64 entries, and the latest row for a leg wins. So a bracket whose answer was lost still gets legs that can be cancelled, modified and filled, and `bracketLegs(clientId)` names them. `orderKind(clientId)` (`OrderKind`). After a dropped connection: `beginReconcile()`, read the order history of every account written to, pass each row to `onBrokerOrder({ ...row.order, clientToken: row.clientToken })`, `onReconnect(new Set(ids))`, then `releaseAmbiguous` each client id the complete history never mentions; otherwise a close left unresolved by the drop refuses every later close. Close and reverse rows cannot be modified or cancelled (`onValidationError`).

`OpenAlgoTradeFeed.place` refuses `account`, `duration`, `expiresAt` and `leverage` pre-flight: OpenAlgo's placeorder has no such fields and one key is one account.

```ts
import { AccountManager, FakeBroker, OrderEngine } from 'openalgo-charts/trade';
const broker = new FakeBroker({ accounts: [{ id: 'SBX-1', mode: 'analyzer', balance: 100000 }] });
const accounts = new AccountManager({ feed: broker, mode: 'analyzer' });
const engine = new OrderEngine({ feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05 },
  selectedAccount: accounts });
broker.onOrderUpdate((order, info) => engine.onBrokerOrder({ ...order, clientToken: info.clientToken }));
await accounts.refresh();
broker.setMark('SYN', 100);
await engine.placeOrder({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 10, duration: 'DAY' });
await engine.closePosition({ symbol: 'SYN', qty: 4 });     // native partial close
await engine.reversePosition({ symbol: 'SYN' });            // native reverse
```

Full guide: website `docs/trading-accounts`.

## Worked example: engine + OpenAlgo + chart gesture

```ts
import { createChart, OpenAlgoTradeFeed } from 'openalgo-charts';
import { OrderEngine, TradeController } from 'openalgo-charts/trade';

const chart = createChart(el);
chart.addSeries('candlestick').setData(bars);

const feed = new OpenAlgoTradeFeed({
  baseUrl: 'http://127.0.0.1:5000', apiKey, strategy: 'chart-trading', defaultProduct: 'MIS',
});
const engine = new OrderEngine({
  feed,
  constraints: { tickSize: 0.05, priceBand: { lower: ltp * 0.8, upper: ltp * 1.2 }, freezeQty },
  armed: false,
  gate: (req) => window.confirm(`${req.side} ${req.qty} ${req.symbol}?`),
  onValidationError: (reason) => setStatus(reason),
});
const controller = new TradeController(chart.tradeHost());

// Chart hit ids are 'order:<brokerId>'; the engine is addressed by clientId.
const clientOf = new Map<string, string>();
const knownBrokerIds = new Set<string>();

async function refreshBook() {
  const [orders, positions] = await Promise.all([feed.getOrders(), feed.getPositions()]);
  controller.reconcile(orders, positions);   // fills, cancels and stale orders all resolve here
}

async function placeFromChart(side: 'BUY' | 'SELL', type: 'LIMIT' | 'SL', price: number) {
  const r = await engine.placeOrder({ symbol, exchange, side, type, qty, product: 'MIS', price });
  if (!r.ok) return setStatus(`blocked: ${r.reason}`);
  const before = new Set(knownBrokerIds);
  const orders = await feed.getOrders();
  const fresh = orders.find((o) => !before.has(o.id));
  if (fresh) { clientOf.set(`order:${fresh.id}`, r.clientId!); knownBrokerIds.add(fresh.id); }
  await refreshBook();
}

// Drag a working-order line -> throttled modify; release -> commit.
chart.subscribeDrag(
  (id, price) => { const c = clientOf.get(id); if (c) engine.requestModify(c, price); },
  (id, price) => {
    const c = clientOf.get(id);
    if (c) { engine.requestModify(c, price); void engine.commitModify(c).then(refreshBook); }
  },
);

// The pill cancel button routes as `order:<id>::close`.
chart.subscribeClick((id) => {
  if (!id.endsWith('::close')) return;
  const c = clientOf.get(id.slice(0, -'::close'.length));
  if (c) void engine.cancelOrder(c).then(refreshBook);
});

setInterval(refreshBook, 8000);
```

Reconciling the fill back onto the chart *is* `refreshBook()`, the filled order drops out of `getOrders()`, `TradeController` removes its line, and the new `Position` grows a `PositionMarker`. Call `controller.onLtp(symbol, ltp)` on every tick so the P&L band and distance labels stay current.

`OpenAlgoTradeFeed.modify` needs the full order context, which it caches on `place()` and `getOrders()`. **Calling `modify()` for an order it has never seen throws** `cannot modify <id>, unknown order context`; call `getOrders()` after a page reload before allowing drags.

## Foot-guns

**`onFill` takes a broker id, `cancelOrder`/`requestModify`/`state` take a client id.** Mixing them is a silent no-op.

**`onReconnect` is destructive.** Any tracked non-terminal order whose broker id is missing from the set becomes `stale`, which is terminal, pass the *complete* fresh book, never a partial page.

**Terminal states swallow everything.** After `stale`, a late fill event cannot move the order back; rebuild from a snapshot instead.

**`OpenAlgoTradeFeed` sends `pricetype: req.type` verbatim.** Your `OrderType` strings must be the exact values OpenAlgo expects (`MARKET`, `LIMIT`, `SL`, `SL-M`). `exchange` defaults to `'NSE'`, `product` to `defaultProduct` (default `'MIS'`), on `place()` only: `modify()` never guesses either for an order the book does not describe, so pass `exchange` on every order for any other exchange.

## Deeper

Visualization layer and its events: [trading](trading.md). Entry points and tree-shaking: [bundling-and-tiers](bundling-and-tiers.md). `subscribeDepth` and WS modes: [feeds-and-live](feeds-and-live.md). `IPrimitive` and hit-testing: [primitives-and-plugins](primitives-and-plugins.md). `chart.on('drag' | 'drag:end' | 'click' | 'hover')` payloads: [events-and-state](events-and-state.md).

## Field validators

`validateOrder` runs the whole set. The two field-level checks are exported so a form
can validate as the user types instead of only on submit:

```ts
validatePrice(price: number, c: OrderConstraints): ValidationResult
validateQuantity(qty: number, c: OrderConstraints): ValidationResult
```

Both return a `ValidationResult` rather than throwing, so a failure is a value you
render, not an exception you catch.

`isPreflightFailure(err)` distinguishes an order rejected *before* it reached the
broker from one the broker rejected. The difference matters: a preflight failure is
the user's to fix and the order never existed, so retrying is safe and no reconcile
against the broker is needed.

`TRADE_TIER` is the tier's identity constant (`'trade'`).

## Trading capability contract

`TradingCapabilities`, `TradingCapabilitySource`, `TradingCapabilityRequest`,
`TradingCapabilityResult` and `TradingOperation` are available from both base
and trade entry points. The declaration has optional `place`, `modify` and
`cancel` fields (`boolean | 'unknown'`), plus `orderTypes` and `modes` lists
for new orders. Omitted declarations/fields preserve legacy behavior. False,
explicit unknown support and empty placement lists block the relevant action.
A configured synchronous provider returning undefined or throwing declares
unavailable support and blocks delivery.

Use `checkTradingCapability(source, request)` to hide or disable unsupported
controls. A request names `operation`, with optional `symbol`, `exchange`,
`orderId`, `type` and `mode`. A declared type/mode list requires that qualifier;
no broker mode is inferred. `assertTradingCapability(source, request)` raises
`TradingCapabilityError` with `preflight: true` and `operation` before delivery.
This refusal does not resolve a previous ambiguous order or release its token.

`OrderFeed.capabilities` advertises feed restrictions.
`OrderEngineOptions.capabilities` adds host restrictions; either source can
refuse. The engine rechecks after confirmation and before queued modify flush.
`OpenAlgoTradeConfig.capabilities` protects direct feed calls, including a
recheck after asynchronous mode verification. `OpenAlgoTradeFeed.capabilities`
exposes that source. Unsupported modify/cancel operations preserve the existing
order state; the engine reports them through `onValidationError`. Order-type
placement restrictions do not prevent cancellation of an existing order.

Use a dynamic provider to combine capability metadata with host-owned replay
selection and workspace locks. The base `isReplaying(chart)` query detects
active replay. The widget accepts `tradingCapabilities`, `tradingMode` and
`tradingLocked` and rechecks capability and replay state before calling
`onOrder`; the direct feed/engine must receive the same host restrictions.
Unknown book rows and ambiguous delivered intents remain unresolved until
broker reconciliation establishes their status. Capabilities never acknowledge
an order or change the broker's mode.

Full examples and verification boundaries: `docs/trading-capabilities.md`.

Placement requests are snapshotted before confirmation or asynchronous mode
checks. The confirmation callback receives a separate copy, so caller/callback
mutation cannot replace the validated request. Modify options and feed patches
are detached as well. New broker updates, reconciliation and later writes
supersede pending modify/cancel completions; late responses cannot overwrite
their intent or broker authority. This does not cancel an in-flight request or
establish its broker outcome.
