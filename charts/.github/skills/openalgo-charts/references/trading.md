# Trading visualization (`chart.trading`)

*When to read this: rendering positions, resting orders, brackets and fill markers on a chart, and turning user gestures on those lines into broker calls.*

Source of truth: `src/core/trading-controller.ts`, `src/core/chart.ts` (`get trading`, `tradeHost`, `subscribeClick`, `subscribeDrag`), `src/primitives/price-line.ts`, `src/primitives/buy-sell-buttons.ts`. Tests: `tests/trading-controller.test.ts`, `tests/trade-ui.test.ts`, `tests/buy-sell-buttons.test.ts`.

Ships in the **base** bundle (`openalgo-charts`). No extra entry point, no broker dependency. For the transactional order engine, state machine and DOM ladder, see [trade-tier](trade-tier.md).

## Mental model: a two-way loop

**This layer never talks to a broker.** It is a renderer for state you own plus an event source for gestures. Getting this wrong is the single most common failure: dragging a line does *not* move the order, it only tells you the user wants it moved.

```
your app  ---- chart.trading.syncState({ positions, orders, trades }) ---->  chart draws
                                                                                 |
                                          user drags a line / hits cancel        |
your app  <------------ 'trading:order_modify' | 'trading:order_cancel' ---------'
    |
    '-> broker REST/WS -> (broker confirms) -> chart.trading.syncState(fresh state)
```

The chart applies one optimistic write on drag end (`order.price` is updated locally so the line does not snap back mid-frame). Everything else is yours. If the broker rejects, push the previous state back with `setOrders(...)` and the line reverts.

## Accessor

`chart.trading` is a **getter**, not a method. The `TradingController` is constructed on first access and cached.

```ts
import { createChart } from 'openalgo-charts';
const chart = createChart(el);
chart.addSeries('candlestick').setData(bars);
chart.trading.syncState({ positions, orders, trades });
```

- Its `PriceLine`s and marker primitive always land on **the price pane** (`new TradingController(this)` routes through `chart.addPrimitive`, whose pane defaults to the price pane). That is pane 0, unless the chart was built with `movablePrimaryPane` and the price pane was moved below its studies; the lines follow it there.
- `chart.tradeHost(paneIndex)` is the *other* host shape (`addPrimitive`/`removePrimitive` only) and is for the trade tier's `TradeController`, not for `chart.trading`.

**`chart.trading` subscribes to `chart.subscribeClick` and `chart.subscribeDrag` beside the host.** Since 2.6.0 both take several subscribers and return an unsubscribe, so a host callback registered before or after `chart.trading` leaves cancel and modify working, and the host hears the same ids. Before 2.6.0 they were single slots and the last registration silenced the other. Building the layer also makes every `ns-resize` price line on the chart draggable, which is why inspecting code asks `chart.hasTrading()` first.

## Worked example: full round trip

```ts
import { createChart } from 'openalgo-charts';
import type { TradingOrder, TradingPosition } from 'openalgo-charts';

const chart = createChart(el);
chart.addSeries('candlestick').setData(bars);

let positions: TradingPosition[] = [
  { id: 'p1', side: 'long', entryPrice: 2900, size: 10, pnlText: '+500.00', pnlPercent: '+1.72%' },
];
let orders: TradingOrder[] = [
  { id: 'o1', type: 'limit', side: 'buy', price: 2850, size: 5 },
  { id: 'tp1', type: 'limit', side: 'sell', price: 3000, size: 10, parentId: 'p1', bracketRole: 'tp' },
  { id: 'sl1', type: 'stop', side: 'sell', price: 2840, size: 10, parentId: 'p1', bracketRole: 'sl' },
];

chart.trading.syncState({
  positions,
  orders,
  trades: [{ id: 'f1', side: 'buy', price: 2900, size: 10, timestamp: Date.now() }],
});

// Gestures out -> broker -> confirmed state back in.
chart.trading.on('trading:order_modify', async ({ orderId, newPrice, previousPrice }) => {
  const ok = await broker.amend(orderId, newPrice);
  orders = orders.map((o) => (o.id === orderId ? { ...o, price: ok ? newPrice : previousPrice } : o));
  chart.trading.setOrders(orders);          // authoritative repaint either way
});

chart.trading.on('trading:order_cancel', async ({ orderId }) => {
  await broker.cancel(orderId);
  orders = orders.filter((o) => o.id !== orderId);
  chart.trading.setOrders(orders);
});

chart.trading.on('trading:position_close', async ({ positionId }) => {
  await broker.squareOff(positionId);
});
```

On `chart.on` the payload is typed by the name (`TradingOrderModifyEvent`, `TradingBracketModifyEvent`, or `ChartEventMap['trading:order_cancel']` and so on), so destructure it directly. `chart.trading.on` still types it `unknown`; cast there, or subscribe on the chart.

## `TradingPosition`

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `string` | yes | Hit-test id is `pos:<id>`, close button `pos:<id>::close` |
| `side` | `'long' \| 'short'` | yes | Badge text is `LONG` / `SHORT`; picks `colors.long` / `colors.short` |
| `entryPrice` | `number` | yes | Line price |
| `size` | `number` | yes | Rendered in the qty segment |
| `pnlText` | `string` | no | Pre-formatted; omit and the info segment is empty |
| `pnlPercent` | `string` | no | Appended as `pnlText (pnlPercent)`; ignored without `pnlText` |
| `color` | `string` | no | Overrides the side colour |
| `readOnly` | `boolean` | no | `true` hides the cancel button (`closeButton: false`) |
| `variant` | `'standard' \| 'line-only'` | no | `line-only` drops badge, qty, info and the cancel button |

Positions are drawn with a hard-coded `lineWidth: 2`, `dashed: false`, `extentFromRight: 0.3`. **Position lines are never draggable**: `_positionOpts` sets no `cursor`, so there is no `trading:position_modify` event.

## `TradingOrder`

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `string` | yes | Hit-test id `ord:<id>`, close `ord:<id>::close` |
| `type` | `'limit' \| 'stop' \| 'stop_limit'` | yes | Info segment text: `LIMIT` / `STOP` / `STOP LIMIT` |
| `side` | `'buy' \| 'sell'` | yes | Badge when there is no `bracketRole` |
| `price` | `number` | yes | Line price |
| `size` | `number` | yes | Qty segment |
| `parentId` | `string` | no | Owning position/entry id; echoed in `trading:bracket_modify` |
| `bracketRole` | `'tp' \| 'sl'` | no | Overrides the badge with `TP`/`SL`, picks `colors.tp`/`colors.sl`, and suppresses the info segment |
| `color` | `string` | no | Overrides badge/line colour |
| `lineStyle` | `'solid' \| 'dashed' \| 'dotted'` | no | Default `'solid'` |
| `lineWidth` | `number` | no | Default `1` |
| `readOnly` | `boolean` | no | Hides the cancel button and (unless `draggable` is set) disables drag |
| `draggable` | `boolean` | no | Defaults to `readOnly !== true`; forced off by `variant: 'line-only'` |
| `variant` | `'standard' \| 'line-only'` | no | Line + axis tag only |

**`lineStyle: 'dotted'` renders identically to `'dashed'`.** The controller collapses it to `dashed: (lineStyle ?? 'solid') !== 'solid'`; `PriceLine` has no dotted dash pattern.

## `TradingTrade`

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `string` | yes | Map key; re-adding the same id replaces the fill |
| `side` | `'buy' \| 'sell'` | yes | Picks `colors.buy` / `colors.sell` |
| `price` | `number` | yes | Marker Y |
| `size` | `number` | yes | Only used as the VWAP weight for `variant: 'count'` |
| `timestamp` | `number` | yes | **Milliseconds** |
| `variant` | `'chevron' \| 'bubble' \| 'count'` | no | Default `'chevron'` |
| `color` | `string` | no | Overrides the side colour |
| `label` | `string` | no | `bubble` text; defaults to `'B'` / `'S'`. Ignored by `chevron` and `count` |

**`TradingTrade.timestamp` is in milliseconds while every other time in this library is UTC seconds.** `TradeMarkersPrimitive.draw` does `snapToIndex(rc.dataLayer, Math.floor(t.timestamp / 1000))`. Passing `bar.time` directly puts every marker at the first bar. Convert with `bar.time * 1000`, or use `Date.now()`.

Markers snap to the **nearest bar index**, not an exact time; sub-bar fill precision is lost. `variant: 'count'` groups fills sharing an `(index, side)` key and draws the count at the size-weighted VWAP of the group.

## Methods

| Method | Effect |
|---|---|
| `setPositions(positions)` | Full replace; unlisted ids are removed |
| `setOrders(orders)` | Full replace |
| `setTrades(trades)` | Full replace; creates the marker primitive on first call |
| `syncState({ positions?, orders?, trades? })` | Applies only the keys present |
| `upsertOrder(order)` | Filters by id then re-runs `setOrders` |
| `removeOrder(id)` | Removes the order **and every order whose `parentId === id`** |
| `addTrade(trade)` | One fill, keyed by `id` |
| `updatePositionPnl(id, pnlText?, pnlPercent?)` | Rewrites the info segment in place |
| `getPositions()` / `getOrders()` / `getTrades()` | Current entities |
| `clear()` | Removes every line and the marker primitive |
| `setSettings(settings)` / `getSettings()` | Colours; see below |
| `setTickSchedule(schedule \| null)` | Snap dragged order and bracket lines, and the `newPrice` their events carry, to a `TickSchedule`; anything else throws a `TypeError`; `chart.setTickSchedule` sets it too; see below |
| `on(event, cb)` | Returns an unsubscribe function |
| `off(event, cb)` | `cb` is required here (unlike `chart.off`) |

**`updatePositionPnl` takes texts, not a number.** Only `pnlText` and `pnlPercent` reach the pill, so format the number yourself. The 2.x form with the number first, `updatePositionPnl(id, pnl, pnlText?, pnlPercent?)`, still works and ignores the number; it is deprecated, removed in 3.0.0. The method tells the forms apart by the second argument: a string is a text, anything else (a number, or the undefined or null a script host passes before it has one) is the ignored number.

Diffing: `_sync` recreates a line whenever `color | dashed | closeButton | cursor | hasLeftLabel | badge | qty` changes and otherwise patches `price` + `leftLabel` in place. Changing `size` therefore rebuilds the primitive; changing only `price` does not.

## Event catalogue

Six events, all emitted from `src/core/trading-controller.ts`. Names carry the `trading:` prefix on **both** buses, `chart.trading.on('trading:order_modify', cb)` and `chart.on('trading:order_modify', cb)` are the two valid forms; a bare `'order_modify'` matches nothing.

| Event | Payload | Fired by |
|---|---|---|
| `trading:order_modify` | `{ orderId: string; newPrice: number; previousPrice: number }` | Drag end on a non-bracket order line |
| `trading:bracket_modify` | `{ parentId: string \| undefined; bracketRole: 'tp' \| 'sl'; newPrice: number }` | Drag end on an order with a `bracketRole`. Carries no `orderId` |
| `trading:order_cancel` | `{ orderId: string }` | Click on `ord:<id>::close` |
| `trading:position_close` | `{ positionId: string }` | Click on `pos:<id>::close` |
| `trading:order_click` | `{ order: TradingOrder }` | Click on an order pill body |
| `trading:position_click` | `{ position: TradingPosition }` | Click on a position pill body |

`_emit` fans out to the controller's own listeners and then mirrors through `host.emit?.(...)`, which is `Chart.emit`. A `chart.on` listener that throws is swallowed; a `chart.trading.on` listener that throws propagates.

**A plain click on a *draggable* order pill emits `trading:order_modify` as well as `trading:order_click`.** A press on an `ns-resize` primitive arms the drag, so pointer-up runs `_dragEndCb` (emitting `order_modify` with `newPrice` = the price under the cursor, a few pixels off the line) before `_clickCb`. Guard the handler: `if (Math.abs(newPrice - previousPrice) < tickSize) return;`. Position pills and cancel segments are unaffected, neither arms a drag.

**Drag prices are raw pointer prices unless a schedule is set.** `chart.setTickSchedule(new TickSchedule(bands))` rounds the dragged line's preview and the `newPrice` of `trading:order_modify` and `trading:bracket_modify` to the band the release lands in: 0.01 below 100 and 0.05 from 100 turns a release at 100.33 into 100.35 and one at 99.874 into 99.87. The chart passes the schedule on to `chart.trading` (a layer that exists or one built later) and rounds dragged price alerts and `chart.snapPrice` on the price pane with it too; `chart.trading.setTickSchedule` sets the trading layer alone, so a host without instrument metadata calls the chart's. `Instrument.applyTo` sets it from `instrument.tickSchedule`, and a constant-tick instrument clears it, so a symbol switch never leaves the previous bands on a drag; call `chart.setTickSchedule` after `applyTo` to override. A one-band schedule snaps a constant tick; give `validatePrice` the same schedule, or its `roundToTick` result (`100.05000000000001`) will not equal the dragged `100.05`. `null`, the default, keeps the raw price. Validate with `validatePrice` before sending either way; price limits are not checked here.

`trading:bracket_modify` gives you `parentId`, not the child order id. Keep your own `parentId + bracketRole -> orderId` map if the broker amends by order id.

## Colours

```ts
export const DEFAULT_TRADING_COLORS: TradingColors = {
  long: '#2f6df6', short: '#ef5350', order: '#3b82f6',
  tp: '#26a69a', sl: '#ef5350', buy: '#26a69a', sell: '#ef5350',
};
```

`setSettings(settings: TradingSettings)` takes the optional keys `longColor`, `shortColor`, `orderColor`, `tpColor`, `slColor`, `buyColor`, `sellColor`, merges only the defined ones, then re-runs `setPositions`/`setOrders` and pushes the new palette into the markers. `getSettings()` returns a copy of the resolved `TradingColors` (long/short/order/tp/sl/buy/sell keys, note the different key names from the setter).

Resolution order per object: explicit `color` -> `bracketRole` colour (`tp`/`sl`) -> role default (`long`/`short`/`order`/`buy`/`sell`). Pill badge text auto-contrasts against its fill via `contrastText`, so custom colours stay legible on either theme.

## Brackets

A bracket child is any `TradingOrder` with `bracketRole` set. `parentId` links it to a position or entry order. The controller uses `bracketRole` for the badge, colour and event routing, and `parentId` only as event payload and as the `removeOrder` cascade key. **There is no OCO logic here**: filling the TP does not cancel the SL. That lives in the trade tier's `OrderEngine.linkOco`.

## `BuySellButtons`

An in-plot trade panel (base export). Draws on the overlay canvas, so it survives pan/zoom and lands in screenshots.

```ts
import { BuySellButtons } from 'openalgo-charts';

const panel = new BuySellButtons({ id: 'trade', position: 'top-left', qty: 1, scale: 0.75 });
chart.addPrimitive(panel);
panel.setMark(ltp);            // or setPrices(bid, ask)

chart.on('click', ({ id }) => {
  if (id === 'trade:buy') placeMarket('BUY');
  if (id === 'trade:sell') placeMarket('SELL');
  if (id === 'trade:qty') focusQtyInput();
});
```

Options: `id` (default `'trade'`), `position` (`WatermarkPosition`, default `'top-left'`), `margin` (`number | {x,y}`, default `12`), `qty`, `buyColor`/`sellColor` (default to `theme.buy`/`theme.sell`), `buyLabel`/`sellLabel` (default `'BUY'`/`'SELL'`), `showPrices` (default `true`), `scale` (default `1`, clamped `0.6..1.5`). Runtime setters: `setPrices(bid, ask)`, `setMark(price)`, `setQty(qty)`, `setColors(buy?, sell?)`. Hit ids: `${id}:buy`, `${id}:sell`, `${id}:qty`, all `cursor: 'pointer'`, `zOrder: 'top'`.

Base size is 190x42 media px before `scale`. Use `margin` plus `legendOffset` to keep it clear of pane legends.

## Right-click order menu

The chart installs its own `contextmenu` handler that composites the base canvas under the overlay so the browser's "Save image as…" captures the visible chart, and freezes overlay repaints until the next input. **Calling `e.preventDefault()` in your own listener disables that path entirely**: which is exactly what an app-owned order menu wants (`if (e.defaultPrevented) return;` guards it).

Pattern from `examples/live/index.html` and `examples/yfinance/index.html`:

```ts
chartEl.addEventListener('contextmenu', (e) => {
  // No pane named: the price pane, wherever it sits. An explicit 0 is the top
  // pane, which is a study's on a chart whose price pane was moved below it.
  const price = chart.coordinateToPrice(e.clientY - chartEl.getBoundingClientRect().top);
  if (price == null) return;
  e.preventDefault();                       // suppress the chart's snapshot path + native menu
  ctxPrice = round(price);
  // Grey out wrong-side entries: BUY stop above the market, BUY limit below, etc.
  showMenuAt(e.clientX, e.clientY);
});
window.addEventListener('click', () => hideMenu());
```

`chart.coordinateToPrice(y, paneIndex)` takes a **container-relative** Y in media px and returns `null` for a missing pane or one collapsed to its header strip; `chart.priceToCoordinate(price, paneIndex)` is the inverse for positioning DOM panels over a line. Both default to the price pane. Offer order rows only when the right-click landed on it (`event.paneIndex === chart.primaryPaneIndex()` on the chart's `contextmenu` event): a price read off a study pane is in the study's units.

## Foot-guns

**Trades are keyed by `id` in a `Map`; `setTrades` clears first, `addTrade` does not.** Streaming fills with a repeated id silently overwrite.

**`clear()` detaches the markers primitive.** The next `setTrades`/`addTrade` builds a fresh one, so any reference you held is dead.

**Everything renders on the price pane**, pane 0 unless `movablePrimaryPane` let it move. There is no `paneIndex` on `chart.trading`. Drive `PriceLine` yourself via `chart.addPriceLine(opts, paneIndex)` for other panes; `addPriceLine(opts)` with no pane follows the price pane.

**`chart.trading.off(event, cb)` needs the exact callback.** There is no remove-all form; keep the unsubscribe returned by `on`.

## Deeper

- Line rendering, pill segments, hover/drag/ghost visuals: [primitives-and-plugins](primitives-and-plugins.md), `src/primitives/price-line.ts`.
- Event bus, `click`/`drag`/`drag:end`/`hover` payloads: [events-and-state](events-and-state.md).
- Pushing live LTP into the pill: [feeds-and-live](feeds-and-live.md).
- Order engine, validation, OCO, DOM ladder: [trade-tier](trade-tier.md).
- Bundle entry points: [bundling-and-tiers](bundling-and-tiers.md).

## Which layer enforces what (1.6.0)

`OrderEngine` owns the arm/confirm gate, the client state machine, intent-versus-broker
state, and OCO bookkeeping. Use it when you need to remember what the user is doing.

`OpenAlgoTradeFeed` owns the checks that must not be bypassable, because a host can call
`feed.place()` directly and never construct an engine:

- quantity: non-finite, zero, negative and fractional are refused with no configuration;
  pass `constraints(symbol, exchange)` to add freeze and lot limits, including on MARKET;
- idempotency: a repeated `clientToken` is refused pre-flight; a failure after the request
  leaves is marked `'ambiguous'` and NOT released. Read it with `tokenState(token)`, clear
  it with `releaseToken(token)` once you have established the truth from the order book;
- decoding: `getOrderBook()` returns `{ orders, quarantined }`, and an unknown broker status
  stays `'unknown'` rather than becoming `working`.

Everything the client checks is advisory. The broker RMS is authoritative.
