# Flow Editor — Import JSON Reference

This document is the source of truth for hand-writing or generating workflow
JSON that can be imported into the OpenAlgo Flow Editor. It covers the
top-level workflow shape, every node type, every edge variant, the variable
interpolation grammar, and the source-handle vocabulary that drives condition
branching.

If you are writing a tool that produces flow JSON (an LLM agent, a script,
another editor), feed this file in as a system prompt — it is written in a
flat declarative style suitable for that purpose.

---

## 0. Output contract — read before generating anything

**Emit exactly this shape. Nothing else imports.**

```jsonc
// shape only - see the runnable example below
{ "name": "...", "nodes": [ ... ], "edges": [ ... ] }
```

* `name` (string), `nodes` (array), `edges` (array) are **required at the top
  level**. Any other top-level shape is rejected with *"Invalid workflow
  format. Must have name, nodes, and edges."*
* Every node must be `{ "id", "type", "position": {"x","y"}, "data": {} }`.
* **`type` must be copied verbatim from the list below.** Do not invent node
  types, and do not translate a strategy description into your own schema.
  If a requirement has no matching node, say so in prose — do not fabricate
  one.
* Emit the JSON object alone: no ``` fences, no commentary, no comments, no
  trailing commas.

### The only valid `type` values

```
Triggers   start · priceAlert · webhookTrigger · orderUpdateTrigger
Actions    placeOrder · smartOrder · optionsOrder · optionsMultiOrder ·
           basketOrder · splitOrder · modifyOrder · cancelOrder ·
           cancelAllOrders · closePositions
Conditions positionCheck · fundCheck · priceCondition · varCondition ·
           timeWindow · timeCondition · andGate · orGate · notGate
Data       getQuote · multiQuotes · getDepth · history · indicator ·
           priorPeriodOhlc · barOffset · strategyPnl · openPosition ·
           getOrderStatus ·
           orderBook · tradeBook · positionBook · holdings · funds · margin ·
           symbol · optionSymbol · expiry · intervals · optionChain ·
           syntheticFuture · holidays · timings · calendar
Streaming  subscribeLtp · subscribeQuote · subscribeDepth · unsubscribe
Utility    log · telegramAlert · whatsappAlert · variable · mathExpression ·
           httpRequest · delay · waitUntil · group
```

### Capabilities Flow does NOT have

Do not emit nodes for these; restructure the strategy instead.

| Not available | What to do instead |
|---|---|
| Variables that persist between runs (flags, counters, "already traded today") | Ask the broker, which is the real record of what you did: `positionCheck` for an open position, or `orderBook` statistics for orders already placed today (the order book resets daily). |
| Remembering that price *reached* a level earlier today ("the gap has filled", "it already tagged VWAP") | The quote's session `high`/`low` are the running extremes of today's session, so `day_low <= PDH` proves price traded down to PDH at some point today. This records where price has been, **not** what you have traded - do not use it to infer your own activity. |
| Loops / iteration / "monitor from 09:20 to 12:30" | Use `start` with `scheduleType: "interval"` plus a `timeWindow` condition. One run per tick. |
| Waiting inside a run for a target or stop | A separate workflow on its own schedule. Entry, exit and square-off are different workflows. |
| Iterating a list of symbols | One workflow per symbol, or drive it from `webhookTrigger` using `{{webhook.symbol}}`. |
| Structured trade logs, backtesting, string manipulation, date arithmetic | Not Flow. Order Book / Trade Book / P&L Tracker hold the trade record. |
| `crossover` / `crossunder` / `correlation` / `beta` as an `indicator` | Two `indicator` nodes plus an `andGate` — see §8.14. |

### Worked example of the required shape

```json
{
  "name": "Buy RELIANCE if RSI below 30",
  "nodes": [
    { "id": "n1", "type": "start", "position": { "x": 0, "y": 0 },
      "data": { "scheduleType": "interval", "intervalValue": 5, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "n2", "type": "indicator", "position": { "x": 0, "y": 100 },
      "data": { "symbol": "RELIANCE", "exchange": "NSE", "interval": "D", "source": "api",
                "indicatorName": "rsi", "params": "{\"period\": 14}", "outputVariable": "rsi" } },
    { "id": "n3", "type": "varCondition", "position": { "x": 0, "y": 200 },
      "data": { "leftValue": "{{rsi.latest.value}}", "operator": "<", "rightValue": "30" } },
    { "id": "n4", "type": "placeOrder", "position": { "x": 0, "y": 300 },
      "data": { "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1,
                "priceType": "MARKET", "product": "MIS", "outputVariable": "ord" } }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "n2" },
    { "id": "e2", "source": "n2", "target": "n3" },
    { "id": "e3", "source": "n3", "sourceHandle": "true", "target": "n4" }
  ]
}
```

### Shapes that are rejected

```jsonc
{ "strategy": {...}, "settings": {...}, "flow": [...] }   // no name/nodes/edges
{ "workflow": { "name": "...", "nodes": [], "edges": [] } } // nested one level too deep
{ "name": "x", "nodes": [ { "type": "Decision" } ] }        // invented type, and no id/position/data
{ "name": "x", "nodes": [], "edges": [], }                  // trailing comma
```

---

## 0.1 Updating a workflow that already exists

Importing always creates a **new** workflow, so iterating on a strategy as JSON
leaves a trail of copies and a new webhook URL each time.

To replace an existing workflow's graph in place, keeping its id, webhook token
and active state:

* **In the editor** - the workflow menu, **Replace from JSON**. Paste or pick a
  file.
* **From a terminal** - `uv run python scripts/update_flow_workflow.py --id <id> --file strategy.json`
  (add `--dry-run` to see what would change first).
* **Over HTTP** - `POST /flow/api/workflows/<id>/replace` with the same body an
  import takes.

All three apply the rules in this document, so a graph that would be rejected at
import is not written through a side door. If the **trigger** configuration
changes on an active workflow, deactivate and reactivate it: the schedule and any
price or order watch are registered at activation, not read per run. Node changes
apply from the next run without any action.

---

## 1. Workflow shape

A workflow is a JSON object with the following top-level keys (the snippet
below is a *shape diagram*, not import-ready — see §8 for runnable examples):

```jsonc
{
  "name": "My Workflow",
  "description": "Optional one-line summary",
  "nodes": [ /* array of nodes */ ],
  "edges": [ /* array of edges */ ],
  "viewport": { "x": 0, "y": 0, "zoom": 1 }
}
```

| Key | Required for import | Required for execution | Notes |
|---|---|---|---|
| `name` | **yes** | no | Importer rejects without it. The UI suffixes `(imported)` to whatever you supply. |
| `description` | no | no | Free-text. Defaults to empty. |
| `nodes` | **yes** (array, can be empty) | yes | See §2 + §7. |
| `edges` | **yes** (array, can be empty) | yes | See §3. |
| `viewport` | no | no | Restores canvas position only. Importers may omit. |

### Importer validation

The importer (`POST /api/workflows/import`, called from the Flow Editor's
**Import** dialog) runs this check on the parsed JSON before saving:

```js
if (!parsed.name || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
  // -> "Invalid workflow format. Must have name, nodes, and edges."
}
```

If `JSON.parse` itself throws (smart quotes, missing comma, real newline
inside a string, BOM at the start), the message is the more generic
**"Invalid JSON format. Please check the workflow data."** — that always
indicates a syntax problem with the JSON text itself, not a missing field.

### Persisted vs minimal node

The DB stores additional UI-only fields per node (`measured`, `dragging`,
`selected`). They are not required for import — the executor reads only `id`,
`type`, `position`, and `data`. A minimal valid node:

```json
{ "id": "node_1", "type": "start", "position": { "x": 0, "y": 0 }, "data": { "scheduleType": "daily", "time": "09:15" } }
```

---

## 2. Node common structure

Every node has the same outer shape:

| Key | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Must be unique within the workflow. Convention: `node_1`, `node_2`, ... |
| `type` | string | yes | One of the values listed in [§7](#7-node-reference). Case-sensitive. |
| `position` | `{ x: number, y: number }` | yes | Canvas coordinates. Anything works; group nodes ~200px apart. |
| `data` | object | yes | Per-node configuration. Each node type defines its own keys. |

Every node's `data` object also accepts an optional `label` (string) used
purely as a UI display override. The executor ignores it.

---

## 3. Edge common structure

Edges connect nodes. Each edge:

| Key | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Any unique string. Convention: `edge-<timestamp>`. |
| `source` | string | yes | The upstream node's `id`. |
| `target` | string | yes | The downstream node's `id`. |
| `sourceHandle` | string \| null | conditional | See [§5](#5-condition-source-handles). Required when fanning out from a condition or gate node. |
| `targetHandle` | string \| null | no | Almost always `null`. Only AND/OR gates use it (see `andGate`/`orGate`). |
| `type` | string | no | UI styling hint. `"insertable"` is the default the editor saves; importers can omit it. |
| `animated` | boolean | no | UI-only flag. Importers can omit. |

Minimal edge:

```json
{ "id": "edge-1", "source": "node_1", "target": "node_2" }
```

---

## 4. Variable interpolation

Inside any string field of any node's `data`, you can reference variables that
upstream nodes have produced or that the executor exposes as built-ins. The
syntax is `{{path}}`.

### Path grammar

- **Dotted keys** for dict access: `{{order.data.orderid}}`
- **Bracket index** for list/tuple access: `{{expiries.data[0]}}`
- **Combined**: `{{chain.data.results[0].ce.ltp}}`
- **Negative indices are not supported.** Use a positive index.

If any segment of the path is missing or the variable does not exist, the
entire `{{...}}` placeholder is left **literally** in the rendered string —
the workflow does **not** error out. Useful for spotting typos in logs.

### Built-in variables

These resolve to the runtime value of the executor process clock at the moment
the node fires:

| Token | Example value |
|---|---|
| `{{timestamp}}` | `2026-04-29 09:15:42` |
| `{{date}}` | `2026-04-29` |
| `{{time}}` | `09:15:42` |
| `{{year}}` | `2026` |
| `{{month}}` | `04` |
| `{{day}}` | `29` |
| `{{hour}}` | `09` |
| `{{minute}}` | `15` |
| `{{second}}` | `42` |
| `{{weekday}}` | `Wednesday` |
| `{{iso_timestamp}}` | `2026-04-29T09:15:42.123456` |

Calendar built-ins: `{{weekday_num}}` (1 = Monday, for numeric comparison -
`{{weekday}}` is a name like `"Thursday"`), `{{quarter}}`, `{{week_of_year}}`,
`{{day_of_year}}`, and `{{session_date}}` (the trading session date, which
differs from `{{date}}` between midnight and the 03:00 IST rollover).

For "has a new period started", use the `calendar` node rather than comparing
these - see 7.4.
### Output variables

Most data and action nodes accept an `outputVariable` field in their `data`
object. When set, the result of that node is stored in the workflow context
under that name and can be read by every downstream node.

```json
{ "type": "getQuote", "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "quote" } }
```

Then a downstream node can use `{{quote.data.ltp}}` in any string field.

If `outputVariable` is empty or unset, the node still runs but its result is
not exposed.

### Webhook payload

When the trigger is a `webhookTrigger`, the inbound JSON body is exposed as
`{{webhook.<key>}}`. For example, a TradingView alert sending
`{"symbol": "RELIANCE", "action": "BUY", "qty": 10}` exposes
`{{webhook.symbol}}`, `{{webhook.action}}`, `{{webhook.qty}}`.

---

## 5. Condition source handles

Six node types fan out into a TRUE branch and a FALSE branch:

| Node | Handle vocabulary used in `sourceHandle` |
|---|---|
| `positionCheck` | `"true"` / `"false"` |
| `fundCheck` | `"true"` / `"false"` |
| `priceCondition` | `"true"` / `"false"` |
| `varCondition` | `"true"` / `"false"` |
| `timeWindow` | `"true"` / `"false"` |
| `timeCondition` | `"yes"` / `"no"` |
| `notGate` | `"yes"` / `"no"` |

The executor accepts both vocabularies as synonyms — `{yes, true}` is the
truthy branch, `{no, false}` is the falsy branch — but it is good practice
to use the vocabulary native to each node so saved workflows match the UI.

Edges that source from a condition node and **do not** specify a `sourceHandle`
are followed unconditionally on every run (use this for "fire-and-forget" log
or telegram nodes that want to see every result).

**Gate wiring matters.** Feeding a gate through `sourceHandle: "true"` edges
means the gate is only reached when that condition is true, so the gate can
never evaluate to false and **its `false` branch is unreachable**. Use
pass-through wiring (only `targetHandle`, no `sourceHandle`) whenever the
gate needs a working else-branch:

```json
{ "id": "e3", "source": "c1", "target": "gate", "targetHandle": "input-0" }
{ "id": "e4", "source": "c2", "target": "gate", "targetHandle": "input-1" }
```

Gates wait until every wired input has been evaluated, then fire exactly
once per run.

`andGate` / `orGate` **do** branch: both render `true` and `false` source
handles, and the executor routes their result through the same truthy/falsy
edge filter as a condition node. Set `sourceHandle: "true"` or `"false"` on a
gate's outgoing edges exactly as you would for a condition. An edge with no
`sourceHandle` is followed unconditionally, which is rarely what you want from
a gate.

Their **incoming** edges use `targetHandle` to pin a specific input slot:
`targetHandle: "input-0"`, `"input-1"`, ... up to `inputCount - 1`.

`notGate` emits `yes` / `no` handles, which the executor treats as synonyms of
`true` / `false`.

---

## 6. ID generation

`id` strings only need to be unique within the workflow. The UI uses the
pattern `node_<N>` for nodes and `edge-<unix-millis>` for edges, but any
non-empty string works.

Snake/camel case in `data` keys: **camelCase** (e.g. `expiryType`,
`triggerPrice`, `outputVariable`). The one exception is the Expiry node's
`instrumenttype` field which is lowercase to match the OpenAlgo REST API.

---

## 7. Node reference

Every node type the executor recognizes is documented below. Examples show
the full node JSON; in workflow JSON, paste the example as one element of
the `nodes` array.

### 7.1 Trigger nodes

A workflow must contain exactly one trigger node, and that node must be one
of: `start`, `priceAlert`, `webhookTrigger`, `orderUpdateTrigger`. Every
other path of execution flows from there.

> **A second trigger is silently ignored.** The executor takes the *first*
> trigger node it finds and walks the graph from there, so any additional
> trigger - and every node downstream of it - never runs, with no error. If a
> strategy needs two schedules (say entries each minute and a square-off at
> 14:00), either express the second as a `timeWindow`-gated branch on the
> same trigger, or split it into a second workflow.
>
> Note that splitting costs broker calls: branches sharing one trigger also
> share their data nodes, whereas separate workflows each re-fetch. Quotes and
> the order book are **not** de-duplicated by the history cache.

#### start — Schedule Trigger

Fires on a clock schedule.

| Field | Type | Default | Notes |
|---|---|---|---|
| `scheduleType` | `"once"` \| `"daily"` \| `"weekly"` \| `"interval"` | `"daily"` | |
| `time` | `"HH:MM"` | `"09:15"` | Required for `once` / `daily` / `weekly`. |
| `days` | `number[]` | `[0,1,2,3,4]` | For `daily`/`weekly`. 0=Mon, 1=Tue, ..., 6=Sun. |
| `executeAt` | `"YYYY-MM-DD"` | — | Required when `scheduleType="once"`. |
| `intervalValue` | number | `1` | For `interval` mode. |
| `intervalUnit` | `"seconds"` \| `"minutes"` \| `"hours"` | `"minutes"` | For `interval` mode. |
| `marketHoursOnly` | boolean | `true` | If true, the schedule pauses outside 09:15–15:30 IST on weekdays. |

```json
{
  "id": "node_1",
  "type": "start",
  "position": { "x": 100, "y": 100 },
  "data": {
    "scheduleType": "daily",
    "time": "09:20",
    "days": [0, 1, 2, 3, 4],
    "marketHoursOnly": true
  }
}
```

#### priceAlert — Price Alert Trigger

Fires when an LTP condition is met. The price-monitor service polls the
configured symbol on a 1-second tick.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | — | OpenAlgo symbol format. |
| `exchange` | string | `"NSE"` | See [§9 Exchange codes](#9-exchanges). |
| `condition` | `"above"` \| `"below"` \| `"crosses_above"` \| `"crosses_below"` | `"above"` | |
| `price` | number | — | Target price. For channel modes, see `priceLower`/`priceUpper`. |
| `priceLower` | number | — | Used by `entering_channel` / `inside_channel` / etc. (advanced). |
| `priceUpper` | number | — | |
| `trigger` | `"once"` \| `"every_time"` | `"once"` | Whether to re-fire after first match. |
| `expiration` | `"none"` \| `"1h"` \| `"4h"` \| `"1d"` \| `"1w"` | `"none"` | Auto-disable after this duration. |
| `playSound` | boolean | `true` | UI-only. |
| `message` | string | — | Optional custom message. |

```json
{
  "id": "node_1",
  "type": "priceAlert",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "condition": "crosses_above",
    "price": 1500,
    "trigger": "once",
    "expiration": "1d"
  }
}
```

#### webhookTrigger — Webhook Trigger

Fires when an external system POSTs JSON to the workflow's webhook URL. The
URL and secret are minted by the server when the workflow is saved (you cannot
hand-write them; you can only configure the symbol/exchange filter).

| Field | Type | Default | Notes |
|---|---|---|---|
| `label` | string | — | Display name (e.g. `"TradingView Alert"`). |
| `symbol` | string | — | Optional. If set, only requests whose URL ends in `/{symbol}` or whose body has matching `symbol` are accepted. |
| `exchange` | `"NSE"` \| `"BSE"` \| `"NFO"` \| `"CDS"` \| `"MCX"` | `"NSE"` | Default exchange to assume in the payload. |

The inbound JSON body is exposed as `{{webhook.<key>}}` to all downstream
nodes (e.g. `{{webhook.action}}`, `{{webhook.qty}}`, `{{webhook.strike}}`).

```json
{
  "id": "node_1",
  "type": "webhookTrigger",
  "position": { "x": 100, "y": 100 },
  "data": {
    "label": "TradingView Long Entry",
    "symbol": "NIFTY",
    "exchange": "NFO"
  }
}
```

#### orderUpdateTrigger — Order Update Trigger

Fires when an order changes status (fill, rejection, cancellation), pushed
from the account order-update stream — no polling.

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | — | Literal broker order id. **`{{variable}}` references are rejected** — a trigger has no upstream node to resolve them. |
| `symbol` | string | — | OpenAlgo symbol. |
| `exchange` | string | `""` | Empty = any exchange. An explicit value must match. |
| `status` | `"any"` \| `"open"` \| `"trigger pending"` \| `"complete"` \| `"rejected"` \| `"cancelled"` | `"complete"` | |
| `trigger` | `"once"` \| `"every_time"` | `"once"` | |

At least one of `orderId` / `symbol` is required; an unfiltered watch would
fire on every order in the account. The event is exposed to downstream nodes
as `{{webhook.orderid}}`, `{{webhook.symbol}}`, `{{webhook.order_status}}`,
`{{webhook.filled_quantity}}`, `{{webhook.average_price}}`,
`{{webhook.rejection_reason}}`.

```json
{
  "id": "node_1",
  "type": "orderUpdateTrigger",
  "position": { "x": 100, "y": 100 },
  "data": { "symbol": "NIFTY04AUG2624250CE", "exchange": "NFO", "status": "complete", "trigger": "once" }
}
```

---

### 7.2 Action nodes

#### placeOrder — Place Order

Single-leg order on any segment.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | — | OpenAlgo symbol format. |
| `exchange` | string | `"NSE"` | |
| `action` | `"BUY"` \| `"SELL"` | `"BUY"` | |
| `quantity` | int | `1` | In shares (not lots). |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | `"MIS"` | |
| `price` | number | `0` | Required for `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Required for `SL`/`SL-M`. |
| `outputVariable` | string | — | If set, exposes `{{name.orderid}}`, `{{name.status}}`. |

```json
{
  "id": "node_2",
  "type": "placeOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "priceType": "LIMIT",
    "product": "CNC",
    "price": 1450.50,
    "outputVariable": "buyOrder"
  }
}
```

#### smartOrder — Smart Order

Position-aware order. The broker computes the delta between current position
and `positionSize` and places the appropriate order to reach it.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `action`, `priceType`, `product` | (as `placeOrder`) | | |
| `quantity` | int | `1` | Used only when `positionSize=0`. |
| `positionSize` | int | `0` | Target net position. Positive=long, negative=short, 0=use `quantity`. |
| `outputVariable` | string | — | |

```json
{
  "id": "node_2",
  "type": "smartOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "symbol": "TATAMOTORS",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 0,
    "positionSize": -5,
    "priceType": "MARKET",
    "product": "MIS",
    "outputVariable": "smartResult"
  }
}
```

#### optionsOrder — Options Order

Single-leg options order resolved from underlying + offset + option type.

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | `"NIFTY"` \| `"BANKNIFTY"` \| `"FINNIFTY"` \| `"MIDCPNIFTY"` \| `"NIFTYNXT50"` \| `"SENSEX"` \| `"BANKEX"` \| `"SENSEX50"` | `"NIFTY"` | |
| `expiryType` | `"current_week"` \| `"next_week"` \| `"current_month"` \| `"next_month"` | `"current_week"` | The Symbol service resolves to actual date. |
| `offset` | `"ATM"` \| `"ITM1"`–`"ITM5"` \| `"OTM1"`–`"OTM10"` | `"ATM"` | |
| `optionType` | `"CE"` \| `"PE"` | `"CE"` | |
| `action` | `"BUY"` \| `"SELL"` | `"BUY"` | |
| `quantity` | int | `1` | **In lots** (executor multiplies by lot size). |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | |
| `product` | `"MIS"` \| `"NRML"` | `"NRML"` | |
| `price` | number | `0` | For `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | For `SL`/`SL-M`. |
| `splitSize` | int | `0` | If >0, splits into chunks. |
| `outputVariable` | string | — | |

```json
{
  "id": "node_2",
  "type": "optionsOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "underlying": "NIFTY",
    "expiryType": "current_week",
    "offset": "ATM",
    "optionType": "CE",
    "action": "BUY",
    "quantity": 1,
    "priceType": "MARKET",
    "product": "NRML",
    "outputVariable": "ceLong"
  }
}
```

#### optionsMultiOrder — Multi-Leg Options Strategy

Pre-defined or custom multi-leg strategies (straddle / strangle / iron condor /
spreads / custom).

| Field | Type | Default | Notes |
|---|---|---|---|
| `strategy` | `"straddle"` \| `"strangle"` \| `"iron_condor"` \| `"bull_call_spread"` \| `"bear_put_spread"` \| `"custom"` | `"straddle"` | |
| `underlying` | (as `optionsOrder`) | `"NIFTY"` | |
| `expiryType` | (as `optionsOrder`) | `"current_week"` | |
| `action` | `"BUY"` \| `"SELL"` | — | Direction for the strategy (BUY=long volatility, SELL=short volatility). |
| `quantity` | int | `1` | Lots per leg. |
| `priceType` | `"MARKET"` \| `"LIMIT"` | `"MARKET"` | |
| `product` | `"MIS"` \| `"NRML"` | `"NRML"` | |
| `legs` | `Leg[]` | `[]` | **Only for `strategy="custom"`.** Each leg: `{ offset, optionType, action, quantity, expiryDate? }`. |
| `outputVariable` | string | — | Result includes `{{name.results}}` array per leg. |

```json
{
  "id": "node_2",
  "type": "optionsMultiOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "strategy": "iron_condor",
    "underlying": "NIFTY",
    "expiryType": "current_week",
    "action": "SELL",
    "quantity": 1,
    "product": "NRML",
    "outputVariable": "ironCondor"
  }
}
```

#### basketOrder — Basket Order

Place multiple orders in a single API call.

| Field | Type | Default | Notes |
|---|---|---|---|
| `basketName` | string | `"flow_basket"` | |
| `orders` | string | — | Multi-line, comma-separated `SYMBOL,EXCHANGE,ACTION,QTY` per line. |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | `"MIS"` | |
| `priceType` | `"MARKET"` \| `"LIMIT"` | `"MARKET"` | |
| `outputVariable` | string | — | `{{name.results}}` is the per-order result array. |

```json
{
  "id": "node_2",
  "type": "basketOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "basketName": "Morning Long Book",
    "orders": "RELIANCE,NSE,BUY,10\nINFY,NSE,BUY,5\nSBIN,NSE,SELL,20",
    "product": "MIS",
    "priceType": "MARKET",
    "outputVariable": "basket"
  }
}
```

#### splitOrder — Split Order

Splits a large order into chunks.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `action`, `priceType`, `product` | (as `placeOrder`) | | |
| `quantity` | int | `100` | Total to fill. |
| `splitSize` | int | `50` | Chunk size. Last chunk may be smaller. |
| `outputVariable` | string | — | `{{name.results}}` is the per-chunk result. |

```json
{
  "id": "node_2",
  "type": "splitOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "symbol": "YESBANK",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 105,
    "splitSize": 20,
    "priceType": "MARKET",
    "product": "MIS",
    "outputVariable": "splitOut"
  }
}
```

#### modifyOrder — Modify Order

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | — | Usually `{{prevOrder.orderid}}`. |
| `symbol`, `exchange`, `action`, `priceType`, `product` | as `placeOrder` | | Required if the broker expects them on modify. |
| `newQuantity` | int | — | Empty = keep existing. |
| `newPrice` | number | — | Empty = keep existing. |
| `newTriggerPrice` | number | — | Empty = keep existing. |

```json
{
  "id": "node_3",
  "type": "modifyOrder",
  "position": { "x": 100, "y": 300 },
  "data": {
    "orderId": "{{buyOrder.orderid}}",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "newPrice": 1455,
    "priceType": "LIMIT",
    "product": "CNC"
  }
}
```

#### cancelOrder — Cancel Order

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | — | Usually `{{prevOrder.orderid}}`. |

```json
{ "id": "node_3", "type": "cancelOrder", "position": { "x": 100, "y": 300 }, "data": { "orderId": "{{buyOrder.orderid}}" } }
```

#### cancelAllOrders — Cancel All Orders

Cancels every open order. No fields.

```json
{ "id": "node_3", "type": "cancelAllOrders", "position": { "x": 100, "y": 300 }, "data": {} }
```

#### closePositions — Close All Positions

Squares off every open position. No fields.

```json
{ "id": "node_3", "type": "closePositions", "position": { "x": 100, "y": 300 }, "data": {} }
```

---

### 7.3 Logic / condition nodes

These nodes set a `condition` boolean that the executor uses to route edges
via `sourceHandle` — see [§5](#5-condition-source-handles).

#### positionCheck — Position Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | — | |
| `exchange` | string | `"NSE"` | |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | `"MIS"` | |
| `condition` | `"exists"` \| `"not_exists"` \| `"quantity_above"` \| `"quantity_below"` \| `"pnl_above"` \| `"pnl_below"` | `"exists"` | |
| `threshold` | number | `0` | Only used by the `quantity_*` and `pnl_*` modes. |

Result: `condition=True` if the rule matches the live position.

```json
{
  "id": "node_2",
  "type": "positionCheck",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS",
    "condition": "not_exists"
  }
}
```

#### fundCheck — Fund Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `minAvailable` | number | `0` | Triggers True when `availablecash >= minAvailable`. |

```json
{ "id": "node_2", "type": "fundCheck", "position": { "x": 100, "y": 100 }, "data": { "minAvailable": 10000 } }
```

#### priceCondition — Price Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | — | |
| `exchange` | string | `"NSE"` | |
| `field` | `"ltp"` \| `"open"` \| `"high"` \| `"low"` \| `"prev_close"` \| `"change_percent"` | `"ltp"` | `change_percent` is computed from `(ltp - prev_close) / prev_close * 100`. |
| `operator` | `">"` \| `"<"` \| `"=="` \| `">="` \| `"<="` \| `"!="` | `">"` | |
| `value` | number | `0` | The threshold to compare against. |

```json
{
  "id": "node_2",
  "type": "priceCondition",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "field": "ltp",
    "operator": ">",
    "value": 1500
  }
}
```

#### varCondition — Compare Any Two Values

Generic counterpart to `priceCondition`. Compares two **interpolated** values
— an indicator output, a prior-period level, a workflow variable, or a
literal — instead of always re-fetching a live quote field.

| Field | Type | Default | Notes |
|---|---|---|---|
| `leftValue` | string | `""` | Supports `{{vars}}`. |
| `operator` | `">"` \| `"<"` \| `"=="` \| `">="` \| `"<="` \| `"!="` | `">"` | |
| `rightValue` | string | `"0"` | Supports `{{vars}}`. |

Uses `"true"`/`"false"` handles. **If either operand does not resolve to a
number the node errors and takes neither branch** — an unresolved variable
cannot silently route the else-path into a trade.

```json
{
  "id": "node_3",
  "type": "varCondition",
  "position": { "x": 100, "y": 200 },
  "data": { "leftValue": "{{rsi.latest.value}}", "operator": "<", "rightValue": "30" }
}
```

#### timeWindow — Time Window

| Field | Type | Default | Notes |
|---|---|---|---|
| `startTime` | `"HH:MM"` | `"09:15"` | |
| `endTime` | `"HH:MM"` | `"15:30"` | |
| `invertCondition` | boolean | `false` | If true, fires when **outside** the window. |

```json
{
  "id": "node_2",
  "type": "timeWindow",
  "position": { "x": 100, "y": 100 },
  "data": { "startTime": "09:30", "endTime": "15:15", "invertCondition": false }
}
```

#### timeCondition — Time Condition (uses `yes`/`no` handles)

| Field | Type | Default | Notes |
|---|---|---|---|
| `conditionType` | `"entry"` \| `"exit"` \| `"custom"` | — | UI-only categorization. |
| `operator` | `"=="` \| `">="` \| `"<="` \| `">"` \| `"<"` | `">="` | |
| `targetTime` | `"HH:MM"` | `"09:30"` | |
| `label` | string | — | Optional. |

```json
{
  "id": "node_2",
  "type": "timeCondition",
  "position": { "x": 100, "y": 100 },
  "data": {
    "conditionType": "entry",
    "operator": ">=",
    "targetTime": "09:30",
    "label": "Market Open Entry"
  }
}
```

#### andGate — AND Gate

True only if every input is True.

| Field | Type | Default | Notes |
|---|---|---|---|
| `inputCount` | 2..5 | `2` | Number of input slots. Incoming edges should set `targetHandle` to `"input-0"`, `"input-1"`, ... |

Edges feeding it:
```json
{ "id": "edge-x", "source": "cond1", "sourceHandle": "true", "target": "and1", "targetHandle": "input-0" }
{ "id": "edge-y", "source": "cond2", "sourceHandle": "true", "target": "and1", "targetHandle": "input-1" }
```

```json
{ "id": "node_3", "type": "andGate", "position": { "x": 200, "y": 100 }, "data": { "inputCount": 2 } }
```

#### orGate — OR Gate

True if any input is True. Same `inputCount` and `targetHandle` mechanics as
`andGate`.

```json
{ "id": "node_3", "type": "orGate", "position": { "x": 200, "y": 100 }, "data": { "inputCount": 2 } }
```

#### notGate — NOT Gate (uses `yes`/`no` handles)

Inverts the single incoming `condition`.

```json
{ "id": "node_3", "type": "notGate", "position": { "x": 200, "y": 100 }, "data": {} }
```

---

### 7.4 Data nodes

Each data node takes its inputs and stores its result under `outputVariable`
(if set). The shape returned by each maps onto the OpenAlgo REST API's
response — see `docs/prompt/services_documentation.md` for full response
schemas.

#### getQuote — Get Quote

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | |

`{{quote.data.ltp}}`, `{{quote.data.bid}}`, `{{quote.data.ask}}`, `{{quote.data.open}}`, ...

```json
{
  "id": "node_2",
  "type": "getQuote",
  "position": { "x": 100, "y": 100 },
  "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "quote" }
}
```

#### getDepth — Market Depth

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | |

`{{depth.data.bids[0].price}}`, `{{depth.data.asks[0].quantity}}`, `{{depth.data.totalbuyqty}}`.

#### history — Historical OHLCV

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | | | |
| `interval` | `"1m"` \| `"5m"` \| `"15m"` \| `"1h"` \| `"1d"` (or any interval the broker supports — call `intervals` first) | `"5m"` | |
| `startDate` | `"YYYY-MM-DD"` | — | **Required.** Note: the Config Panel currently writes a `days` integer instead — the executor does not consume it, so for import JSON write explicit `startDate`/`endDate` strings. |
| `endDate` | `"YYYY-MM-DD"` | — | **Required.** See note above. |
| `outputVariable` | string | — | |

```json
{
  "id": "node_2",
  "type": "history",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "interval": "5m",
    "startDate": "2026-04-22",
    "endDate": "2026-04-29",
    "outputVariable": "ohlcv"
  }
}
```

#### indicator — Technical Indicator

Runs any of 116 `openalgo.ta` indicators over a symbol's history, or over
another indicator's output series.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | — | Not needed in nested mode. |
| `interval` | string | `"D"` | **Free text**, not an enum — any interval the broker supports. Use the `intervals` node to discover them. |
| `source` | `"api"` \| `"db"` | `"api"` | `"db"` reads Historify and resamples locally (2m/3m/25m/2h from stored 1m; W/M/Q/Y from D). |
| `indicatorName` | string | `"sma"` | Lowercase function name. |
| `params` | string | `"{}"` | JSON object of the indicator's own args, e.g. `"{\"period\": 14}"`. |
| `lookbackBars` | int | `100` | Capped at 200. |
| `tailBars` | int | `5` | Length of the returned `series` array. |
| `offsetBars` | int | `0` | Which bar `at_offset` reads. 0 = latest closed. |
| `sourceSeries` | string | — | Nest over another series, e.g. `{{rsi.series}}` or a raw `{{h.data}}`. |
| `sourceField` | string | `""` | Field to read per `sourceSeries` row. Blank = auto (`value`, `out0`, `close`). |
| `outputVariable` | string | — | |

Exposes `{{name.latest.*}}`, `{{name.previous.*}}`, `{{name.at_offset.*}}`,
`{{name.series}}`, `{{name.outputs}}`, `{{name.bars_used}}`. Single-output
indicators use `value`; multi-output use `out0`, `out1`, … (macd: line/signal/
histogram; supertrend: level/direction; bbands: upper/middle/lower).

`crossover`, `crossunder`, `cross`, `correlation`, `beta` are **not
available** — they need two independent series. Build a crossover from two
`indicator` nodes plus an `andGate`. Only single-series indicators (sma, ema,
rsi, wma, stdev, highest, lowest, …) can be nested via `sourceSeries`.

```json
{
  "id": "node_2",
  "type": "indicator",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE", "exchange": "NSE", "interval": "D", "source": "api",
    "indicatorName": "rsi", "params": "{\"period\": 14}",
    "lookbackBars": 100, "tailBars": 5, "offsetBars": 0,
    "outputVariable": "rsi"
  }
}
```

#### priorPeriodOhlc — Previous Period OHLC

Last fully-closed hour/day/week/month candle. Never returns a still-forming
candle; raises if history is too short.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | — | |
| `period` | `"previous_hour"` \| `"previous_day"` \| `"previous_week"` \| `"previous_month"` | `"previous_day"` | |
| `source` | `"api"` \| `"db"` | `"api"` | |
| `outputVariable` | string | — | |

Exposes `{{name.open/high/low/close/volume}}` plus aliases `{{name.pdh}}`,
`{{name.pdl}}`, `{{name.pdc}}` and `{{name.date}}`.

```json
{
  "id": "node_2",
  "type": "priorPeriodOhlc",
  "position": { "x": 100, "y": 100 },
  "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "period": "previous_day", "source": "api", "outputVariable": "pd" }
}
```

#### calendar — Calendar

Trading-day facts for a date, and the stateless answer to "has a new day,
week, month, quarter or year started". Flow keeps no state between runs, so a
workflow cannot remember the last run's date - it does not need to, because
"a new month started" is the same statement as "today is the first trading day
of this month", which the exchange calendar answers on its own.

| Field | Type | Default | Notes |
|---|---|---|---|
| `date` | `"YYYY-MM-DD"` | current trading session date | Blank uses the session date, which differs from the calendar date between midnight and the 03:00 IST rollover. |
| `outputVariable` | string | — | |

Not exchange-aware: a date is a trading holiday if the exchange calendar lists
one. MCX differs from NSE on a few days a year.

Use `{{cal.is_new_month}}` rather than `{{month}}`-based arithmetic or
`{{day}} == 1`. The 1st can fall on a Sunday, and a week's Monday can be a
holiday; the flags handle both, those tests do not.

```json
{
  "id": "node_2",
  "type": "calendar",
  "position": { "x": 100, "y": 100 },
  "data": { "outputVariable": "cal" }
}
```

#### strategyPnl — Strategy P&L

Realized / unrealized / total P&L for **one strategy**, not the whole account.
The broker nets positions per `(symbol, exchange, product)` and carries no
strategy label, so this is the only way a workflow can exit on its own
performance while another strategy holds the same contract.

| Field | Type | Default | Notes |
|---|---|---|---|
| `strategy` | string | the workflow's own name | Matches the tag this workflow's order nodes apply. Leave blank in almost every case. |
| `outputVariable` | string | — | |

Exposes `{{name.realized}}`, `{{name.today_realized}}`, `{{name.unrealized}}`,
`{{name.total}}`, `{{name.today_total}}`, `{{name.open_quantity}}`,
`{{name.unpriced_legs}}` and a per-leg `{{name.legs[0].*}}` breakdown.

The book is fed from orders placed **through OpenAlgo carrying a strategy
tag**; a position opened by hand in the broker terminal is invisible to it.
`unpriced_legs` counts open legs with no live price, which are excluded from
`unrealized` — a non-zero value means `total` is understated. If the position
book or the strategy book cannot be read, the node returns `status: "error"`
rather than a zero, because a zero is indistinguishable from a flat strategy.

Guard on `open_quantity` before acting, or an exit re-fires every run once the
position is already flat and realized P&L still exceeds the target.

```json
{
  "id": "node_2",
  "type": "strategyPnl",
  "position": { "x": 100, "y": 100 },
  "data": { "outputVariable": "pnl" }
}
```

#### barOffset — OHLCV N Bars Back

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | — | |
| `interval` | string | `"D"` | Free text. |
| `source` | `"api"` \| `"db"` | `"api"` | |
| `offsetBars` | int | `0` | 0 = most recent **closed** bar; today's forming candle is excluded. Counts bars, not calendar days. |
| `outputVariable` | string | — | |

Exposes `{{name.open/high/low/close/volume/timestamp}}`.

```json
{
  "id": "node_2",
  "type": "barOffset",
  "position": { "x": 100, "y": 100 },
  "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "D", "source": "api", "offsetBars": 5, "outputVariable": "bar5" }
}
```

#### openPosition — Open Position For Symbol

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `product`, `outputVariable` | | | |

`{{position.quantity}}` and `{{position.pnl}}` are exposed.

#### getOrderStatus — Order Status

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | — | Usually `{{prevOrder.orderid}}`. |
| `outputVariable` | string | — | |

`{{orderStatus.data.order_status}}` is `"complete" / "open" / "rejected" / ...`.

#### orderBook / tradeBook / positionBook / holdings / funds

All five take only `outputVariable`. Common patterns:

```json
{ "id": "node_2", "type": "orderBook",    "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "orders" } }
{ "id": "node_2", "type": "tradeBook",    "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "trades" } }
{ "id": "node_2", "type": "positionBook", "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "positions" } }
{ "id": "node_2", "type": "holdings",     "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "holdings" } }
{ "id": "node_2", "type": "funds",        "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "funds" } }
```

Useful interpolations: `{{orders.data.orders[0].orderid}}`,
`{{positions.data[0].quantity}}`, `{{holdings.data.holdings[0].symbol}}`,
`{{funds.data.availablecash}}`.

> Note the asymmetry, which is a common source of unresolvable paths:
> `positionBook` and `tradeBook` put their rows directly in `data` (a list),
> while `orderBook` nests them under `data.orders` and `holdings` under
> `data.holdings`. See [§7.7 Node output shapes](#77-node-output-shapes).

#### symbol — Symbol Info

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Returns `{ data: { lotsize, tick_size, expiry, ... } }`. |

#### optionSymbol — Resolve Option Symbol

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | string | `"NIFTY"` | |
| `exchange` | `"NSE_INDEX"` \| `"BSE_INDEX"` | `"NSE_INDEX"` | |
| `expiryDate` | string | — | Format `"30DEC25"`. Can be `{{expiries.data[0]}}` after a normalization step. |
| `offset` | `"ATM"` \| `"ITM1"`–`"ITM2"` \| `"OTM1"`–`"OTM3"` | `"ATM"` | |
| `optionType` | `"CE"` \| `"PE"` | `"CE"` | |
| `outputVariable` | string | — | |

#### expiry — Get Expiry Dates

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | `"NIFTY"` | |
| `exchange` | `"NFO"` \| `"BFO"` \| `"MCX"` \| `"CDS"` | `"NFO"` | |
| `instrumenttype` | `"options"` \| `"futures"` | `"options"` | **Lowercase.** Different calendars per type. |
| `outputVariable` | string | — | List sorted ascending. `{{expiries.data[0]}}` = nearest. |

```json
{
  "id": "node_2",
  "type": "expiry",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "NIFTY",
    "exchange": "NFO",
    "instrumenttype": "options",
    "outputVariable": "expiries"
  }
}
```

#### intervals — Available Time Intervals

| Field | Type | Default | Notes |
|---|---|---|---|
| `outputVariable` | string | — | |

```json
{ "id": "node_2", "type": "intervals", "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "ivs" } }
```

#### multiQuotes — Quotes For Many Symbols

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbols` | string | — | Comma-separated, e.g. `"RELIANCE,INFY,TCS"`. |
| `exchange` | string | `"NSE"` | Applied to each symbol. |
| `outputVariable` | string | — | `{{quotes.results[0].data.ltp}}`. |

#### optionChain — Option Chain

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | string | `"NIFTY"` | |
| `exchange` | `"NSE_INDEX"` \| `"BSE_INDEX"` | `"NSE_INDEX"` | |
| `expiryDate` | string | — | Format `"30DEC25"`. |
| `strikeCount` | int | `10` | Number of strikes above and below ATM. |
| `outputVariable` | string | — | `{{chain.atm_strike}}`, `{{chain.chain[0].ce.ltp}}`. |

#### syntheticFuture — Synthetic Future Price

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying`, `exchange`, `expiryDate`, `outputVariable` | (as `optionChain`) | | `{{synthFuture.synthetic_future_price}}`. |

#### holidays — Market Holidays

| Field | Type | Default | Notes |
|---|---|---|---|
| `exchange` | string | `"NSE"` | |
| `outputVariable` | string | — | |

#### timings — Market Timings

| Field | Type | Default | Notes |
|---|---|---|---|
| `exchange` | string | `"NSE"` | |
| `outputVariable` | string | — | |

#### margin — Margin Calculator

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `quantity`, `price`, `product`, `action`, `priceType` | | | (Same shape as `placeOrder`.) |
| `outputVariable` | string | — | |

```json
{
  "id": "node_2",
  "type": "margin",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "NIFTY30DEC25FUT",
    "exchange": "NFO",
    "quantity": 75,
    "price": 0,
    "product": "NRML",
    "action": "BUY",
    "priceType": "MARKET",
    "outputVariable": "marginCalc"
  }
}
```

---

### 7.5 Utility nodes

#### log — Log Message

| Field | Type | Default | Notes |
|---|---|---|---|
| `message` | string | — | Supports `{{vars}}`. |
| `level` | `"info"` \| `"warn"` \| `"error"` | `"info"` | |

```json
{ "id": "node_3", "type": "log", "position": { "x": 100, "y": 300 }, "data": { "message": "First expiry: {{expiries.data[0]}}", "level": "info" } }
```

#### telegramAlert — Telegram Alert

Sends a Telegram message via the per-user Telegram bot configured in OpenAlgo
settings.

| Field | Type | Default | Notes |
|---|---|---|---|
| `username` | string | — | OpenAlgo login ID linked to a Telegram user. |
| `message` | string | — | Supports `{{vars}}`. |

```json
{
  "id": "node_3",
  "type": "telegramAlert",
  "position": { "x": 100, "y": 300 },
  "data": {
    "username": "rajandran",
    "message": "Order placed: {{buyOrder.orderid}} for {{buyOrder.symbol}}"
  }
}
```

#### whatsappAlert — WhatsApp Alert

Sends a WhatsApp message via the paired bot device. Requires pairing from the
`/whatsapp` page first.

| Field | Type | Default | Notes |
|---|---|---|---|
| `to` | string | `""` | Phone digits, e.g. `919876543210`. Blank sends to the paired device itself. |
| `message` | string | — | Supports `{{vars}}`. |

```json
{
  "id": "node_3",
  "type": "whatsappAlert",
  "position": { "x": 100, "y": 300 },
  "data": { "to": "", "message": "Order placed: {{ord.orderid}}" }
}
```

#### variable — Set / Update Variable

The UI dropdown offers eleven operations but only four are implemented by
the executor today; pick from those when authoring import JSON:

| Operation | Behaviour |
|---|---|
| `"set"` | Stores `value` under `variableName`. JSON-shaped strings (starting with `{` or `[`) are auto-parsed via `json.loads`, so you can carry structured data. |
| `"add"` | `current + value` (numeric coercion). Initialises to 0 if unset. |
| `"increment"` | `current + 1`. Initialises to 0 if unset. |
| `"decrement"` | `current - 1`. Initialises to 0 if unset. |

| Field | Type | Default | Notes |
|---|---|---|---|
| `variableName` | string | — | The name to set in workflow context. |
| `operation` | `"set"` \| `"add"` \| `"increment"` \| `"decrement"` | `"set"` | Other UI options (`subtract`, `multiply`, `divide`, `append`, `parse_json`, `stringify`, `get`) are **no-ops** on the executor side as of this writing — use `mathExpression` for arithmetic and `set` with a JSON-shaped string for structured assignment. |
| `value` | any | — | Strings accept `{{vars}}`. |

```json
{ "id": "node_3", "type": "variable", "position": { "x": 100, "y": 300 }, "data": { "variableName": "qty", "operation": "set", "value": "10" } }
```

For richer arithmetic, use `mathExpression`:

```json
{ "id": "node_3", "type": "mathExpression", "position": { "x": 100, "y": 300 }, "data": { "expression": "{{quote.data.ltp}} * 0.99", "outputVariable": "stopPrice" } }
```

#### mathExpression — Evaluate Math Expression

| Field | Type | Default | Notes |
|---|---|---|---|
| `expression` | string | — | Supports `+`, `-`, `*`, `/`, `%`, `**`, parentheses. Variables via `{{name}}`. |
| `outputVariable` | string | `"result"` | |

```json
{
  "id": "node_3",
  "type": "mathExpression",
  "position": { "x": 100, "y": 300 },
  "data": {
    "expression": "({{quote.data.ltp}} * {{lotSize}}) + {{brokerage}}",
    "outputVariable": "totalCost"
  }
}
```

#### httpRequest — HTTP Request

| Field | Type | Default | Notes |
|---|---|---|---|
| `method` | `"GET"` \| `"POST"` \| `"PUT"` \| `"DELETE"` \| `"PATCH"` | `"GET"` | |
| `url` | string | — | Supports `{{vars}}`. |
| `headers` | object \| JSON-string | `{}` | e.g. `{"Authorization": "Bearer {{token}}"}`. |
| `body` | string | — | JSON string, only used for POST/PUT/PATCH. Supports `{{vars}}`. |
| `timeout` | int | `30` | Seconds. |
| `outputVariable` | string | — | `{{apiResponse.data}}`, `{{apiResponse.status}}`. |

```json
{
  "id": "node_3",
  "type": "httpRequest",
  "position": { "x": 100, "y": 300 },
  "data": {
    "method": "POST",
    "url": "https://hooks.example.com/notify",
    "headers": "{\"Authorization\": \"Bearer {{secret}}\"}",
    "body": "{\"symbol\": \"{{webhook.symbol}}\", \"action\": \"{{webhook.action}}\"}",
    "timeout": 30,
    "outputVariable": "notifyResp"
  }
}
```

#### delay — Delay

| Field | Type | Default | Notes |
|---|---|---|---|
| `delayValue` | int | `1` | |
| `delayUnit` | `"seconds"` \| `"minutes"` \| `"hours"` | `"seconds"` | |

```json
{ "id": "node_3", "type": "delay", "position": { "x": 100, "y": 300 }, "data": { "delayValue": 30, "delayUnit": "seconds" } }
```

#### waitUntil — Wait Until Time

| Field | Type | Default | Notes |
|---|---|---|---|
| `targetTime` | `"HH:MM"` | `"09:30"` | If already past, the node returns immediately. |
| `label` | string | — | UI-only. |

```json
{ "id": "node_3", "type": "waitUntil", "position": { "x": 100, "y": 300 }, "data": { "targetTime": "15:25", "label": "Square-off entry" } }
```

#### group — Group / Visual Container

UI-only grouping. Has no executor behavior — the group's children execute on
their own edges. The Group node itself is a no-op when traversed.

| Field | Type | Default | Notes |
|---|---|---|---|
| `label` | string | — | |
| `color` | `"default"` \| `"blue"` \| `"green"` \| `"red"` \| `"purple"` \| `"orange"` | `"default"` | |

---

### 7.6 Stream nodes

These maintain a WebSocket subscription and either pass the latest tick to
their `outputVariable` (one-shot, used inside scheduled flows) or keep the
subscription alive across runs of the same workflow.

If WebSocket is unavailable for any reason, every stream node falls back to a
single REST call. Behaviour is identical from the workflow's point of view.

#### subscribeLtp — Subscribe LTP

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | `outputVariable` defaults to `"ltp"`. | The variable receives the float LTP directly. |

```json
{ "id": "node_2", "type": "subscribeLtp", "position": { "x": 100, "y": 100 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "rltp" } }
```

#### subscribeQuote — Subscribe Quote

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Variable receives `{ ltp, open, high, low, close, volume, ... }`. |

#### subscribeDepth — Subscribe Depth

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Variable receives `{ bids: [...], asks: [...], totalbuyqty, totalsellqty, ltp }`. |

#### unsubscribe — Unsubscribe

| Field | Type | Default | Notes |
|---|---|---|---|
| `streamType` | `"ltp"` \| `"quote"` \| `"depth"` \| `"all"` | `"all"` | |
| `symbol` | string | — | Empty = all symbols for this user. |
| `exchange` | string | `"NSE"` | |

---

### 7.7 Node output shapes

What each node stores in its `outputVariable`, so downstream `{{...}}` paths
resolve. Shapes below were captured from live responses, not inferred.

**Market data**

| Node | Shape | Example paths |
|---|---|---|
| `getQuote` | `{status, data: {ltp, open, high, low, prev_close, volume, oi, bid, ask}}` | `{{q.data.ltp}}`, `{{q.data.prev_close}}` |
| `multiQuotes` | `{status, results: [{symbol, exchange, data: {...}}]}` | `{{qs.results[0].data.ltp}}` |
| `getDepth` | `{status, data: {bids: [{price, quantity}], asks: [...], ltp, totalbuyqty, totalsellqty, ...}}` | `{{d.data.bids[0].price}}` |
| `history` | `{status, data: [{timestamp, open, high, low, close, volume, oi}]}` | `{{h.data[0].close}}` |
| `intervals` | `{status, data: {seconds, minutes, hours, days, weeks, months}}` | `{{iv.data.minutes[0]}}` |

`history` timestamps are **epoch seconds**, not ISO strings.

**New data nodes**

| Node | Shape | Example paths |
|---|---|---|
| `indicator` | `{status, indicator, nested, inputs, params, outputs, latest, previous, at_offset, series, offset_bars, bars_used}` | `{{r.latest.value}}`, `{{r.previous.value}}`, `{{r.at_offset.out0}}`, `{{r.series[0].value}}` |
| `priorPeriodOhlc` | `{status, symbol, exchange, period, date, open, high, low, close, volume, pdh, pdl, pdc}` | `{{pd.pdh}}`, `{{pd.pdl}}`, `{{pd.close}}` |
| `barOffset` | `{status, symbol, exchange, offsetBars, timestamp, open, high, low, close, volume}` | `{{b.close}}`, `{{b.high}}` |
| `calendar` | `{status, date, is_trading_day, is_trading_holiday, is_weekend, weekday, weekday_num, day, month, quarter, year, week_of_year, day_of_year, is_new_day, is_new_week, is_new_month, is_new_quarter, is_new_year, is_last_day_of_week, is_last_day_of_month, is_last_day_of_quarter, is_last_day_of_year, prev_trading_day, next_trading_day, first_trading_day_of_week, first_trading_day_of_month, first_trading_day_of_quarter, last_trading_day_of_week, last_trading_day_of_month, last_trading_day_of_quarter}` | `{{cal.is_new_month}}`, `{{cal.is_trading_day}}`, `{{cal.prev_trading_day}}` |
| `strategyPnl` | `{status, strategy, realized, today_realized, unrealized, total, today_total, open_quantity, unpriced_legs, legs: [{symbol, exchange, product, quantity, average_price, ltp, realized, today_realized, unrealized}]}` | `{{pnl.total}}`, `{{pnl.today_total}}`, `{{pnl.today_realized}}`, `{{pnl.open_quantity}}` |

`strategyPnl` reports **only this strategy's** legs, not the account's. It
defaults to the workflow's own name, which is the same tag its order nodes
apply, so the usual case needs no configuration. `unpriced_legs` counts open
legs with no live price - those are excluded from `unrealized`, so treat a
non-zero value as "this total is incomplete" before acting on it.

Single-output indicators expose `value`; multi-output expose `out0`, `out1`,
… (macd: line/signal/histogram, supertrend: level/direction, bbands:
upper/middle/lower, adx: +DI/-DI/ADX, stochastic: %K/%D).

**Account and orders**

| Node | Shape | Example paths |
|---|---|---|
| `funds` | `{status, data: {availablecash, collateral, m2mrealized, m2munrealized, utiliseddebits, ...}}` | `{{f.data.availablecash}}` |
| `orderBook` | `{status, data: {orders: [...], statistics: {...}}}` | `{{o.data.orders[0].orderid}}` |
| `tradeBook` | `{status, data: [{tradeid, orderid, symbol, average_price, ...}]}` | `{{t.data[0].average_price}}` |
| `positionBook` | `{status, data: [{symbol, quantity, average_price, ltp, pnl, ...}], total_pnl}` | `{{p.data[0].pnl}}`, `{{p.total_pnl}}` |
| `holdings` | `{status, data: {holdings: [...], statistics: {...}}}` | `{{hd.data.holdings[0].symbol}}` |
| `openPosition` | `{status, quantity}` | `{{op.quantity}}` |
| `getOrderStatus` | `{status, data: {order_status, average_price, quantity, ...}}` | `{{os.data.order_status}}` |

**Order placement** (all order nodes)

| Node | Shape | Example paths |
|---|---|---|
| `placeOrder`, `smartOrder` | `{status, orderid}` | `{{ord.orderid}}` |
| `optionsOrder` | `{status, orderid, symbol, exchange, underlying, underlying_ltp, offset, option_type, mode}` | `{{ce.orderid}}`, `{{ce.symbol}}` |
| `optionsMultiOrder`, `basketOrder`, `splitOrder` | `{status, results: [{...}]}` | `{{b.results[0].orderid}}` |

`mode` is `"analyze"` in Analyzer mode and `"live"` otherwise — useful for a
guard that refuses to run live.

**Symbols and options**

| Node | Shape | Example paths |
|---|---|---|
| `symbol` | `{status, data: {symbol, brsymbol, lotsize, tick_size, expiry, strike, token, ...}}` | `{{s.data.lotsize}}` |
| `expiry` | `{status, message, data: ["04-AUG-26", ...]}` | `{{e.data[0]}}` |
| `optionSymbol` | `{status, symbol, exchange, lotsize, tick_size, freeze_qty, underlying_ltp}` (**flat, not under `data`**) | `{{os.symbol}}`, `{{os.lotsize}}` |
| `optionChain` | `{status, underlying, underlying_ltp, expiry_date, atm_strike, chain: [{strike, ce: {...}, pe: {...}}]}` | `{{ch.atm_strike}}`, `{{ch.chain[0].ce.ltp}}` |
| `syntheticFuture` | `{status, underlying, expiry, atm_strike, synthetic_future_price, underlying_ltp}` | `{{sf.synthetic_future_price}}` |

**Condition nodes** do not produce an `outputVariable`; they emit a
`condition` boolean consumed by edge routing. Reference a condition's *inputs*
instead of its result.

For full REST response schemas see [`docs/api`](../api/README.md); the Flow
client returns those payloads unchanged apart from adding `status`.

---

## 8. End-to-end examples

### 8.1 Simple scheduled workflow

Run every weekday at 09:20 IST: place a 10-share BUY of RELIANCE if a
position does not already exist.

```json
{
  "name": "Daily RELIANCE Buy",
  "description": "Place a 10-share intraday BUY of RELIANCE at 09:20 if no existing position",
  "nodes": [
    {
      "id": "node_1",
      "type": "start",
      "position": { "x": 100, "y": 100 },
      "data": { "scheduleType": "daily", "time": "09:20", "days": [0,1,2,3,4], "marketHoursOnly": true }
    },
    {
      "id": "node_2",
      "type": "positionCheck",
      "position": { "x": 100, "y": 200 },
      "data": { "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "condition": "not_exists" }
    },
    {
      "id": "node_3",
      "type": "placeOrder",
      "position": { "x": 100, "y": 300 },
      "data": {
        "symbol": "RELIANCE", "exchange": "NSE",
        "action": "BUY", "quantity": 10,
        "priceType": "MARKET", "product": "MIS",
        "outputVariable": "buyOrder"
      }
    },
    {
      "id": "node_4",
      "type": "log",
      "position": { "x": 300, "y": 300 },
      "data": { "message": "Skipped: position exists ({{buyOrder.orderid}} not placed)", "level": "info" }
    }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "sourceHandle": "true",  "target": "node_3" },
    { "id": "e3", "source": "node_2", "sourceHandle": "false", "target": "node_4" }
  ]
}
```

### 8.2 Webhook-triggered options buy with expiry resolution

TradingView posts `{ "symbol": "NIFTY", "action": "BUY" }` to the webhook.
The workflow fetches the nearest weekly expiry, resolves the ATM CE symbol,
and places a 1-lot BUY.

```json
{
  "name": "TV NIFTY Long ATM CE",
  "description": "Webhook -> ATM weekly CE long entry on NIFTY",
  "nodes": [
    {
      "id": "node_1",
      "type": "webhookTrigger",
      "position": { "x": 100, "y": 100 },
      "data": { "label": "TV NIFTY Long", "symbol": "NIFTY", "exchange": "NFO" }
    },
    {
      "id": "node_2",
      "type": "expiry",
      "position": { "x": 100, "y": 200 },
      "data": { "symbol": "NIFTY", "exchange": "NFO", "instrumenttype": "options", "outputVariable": "expiries" }
    },
    {
      "id": "node_3",
      "type": "optionsOrder",
      "position": { "x": 100, "y": 300 },
      "data": {
        "underlying": "NIFTY",
        "expiryType": "current_week",
        "offset": "ATM",
        "optionType": "CE",
        "action": "BUY",
        "quantity": 1,
        "priceType": "MARKET",
        "product": "NRML",
        "outputVariable": "ceLong"
      }
    },
    {
      "id": "node_4",
      "type": "telegramAlert",
      "position": { "x": 300, "y": 300 },
      "data": { "username": "rajandran", "message": "Bought ATM CE: {{ceLong.orderid}} (expiry {{expiries.data[0]}})" }
    }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" }
  ]
}
```

### 8.3 Funds-aware split entry

Every weekday at 09:30, fetch funds. If available cash >= ₹50k, split a 100-qty
SBIN buy into 5 chunks of 20; otherwise log the skip.

```json
{
  "name": "SBIN Funds-Gated Split Buy",
  "description": "Conditional split entry on SBIN with available-cash guard",
  "nodes": [
    { "id": "node_1", "type": "start",      "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "daily", "time": "09:30", "days": [0,1,2,3,4], "marketHoursOnly": true } },
    { "id": "node_2", "type": "fundCheck",  "position": { "x": 100, "y": 180 }, "data": { "minAvailable": 50000 } },
    { "id": "node_3", "type": "splitOrder", "position": { "x":   0, "y": 300 }, "data": { "symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 100, "splitSize": 20, "priceType": "MARKET", "product": "MIS", "outputVariable": "splitOut" } },
    { "id": "node_4", "type": "log",        "position": { "x": 240, "y": 300 }, "data": { "message": "Skipped SBIN entry: available cash below 50k", "level": "warn" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "sourceHandle": "true",  "target": "node_3" },
    { "id": "e3", "source": "node_2", "sourceHandle": "false", "target": "node_4" }
  ]
}
```

### 8.4 Realized P&L Telegram every minute

Pings the configured Telegram user with realized + unrealized P&L every minute
during market hours. Useful for "watchdog" supervision.

```json
{
  "name": "Realized PnL Telegram Watchdog",
  "description": "Funds snapshot to Telegram every 1 min during market hours",
  "nodes": [
    { "id": "node_1", "type": "start",         "position": { "x": 100, "y": 100 }, "data": { "scheduleType": "interval", "intervalValue": 1, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "node_2", "type": "funds",         "position": { "x": 100, "y": 220 }, "data": { "outputVariable": "funds" } },
    { "id": "node_3", "type": "telegramAlert", "position": { "x": 100, "y": 340 }, "data": { "username": "rajandran", "message": "Realized: Rs {{funds.data.m2mrealized}} | Unrealized: Rs {{funds.data.m2munrealized}} | Cash: Rs {{funds.data.availablecash}} | At {{time}} IST" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" }
  ]
}
```

Note `m2mrealized` and `m2munrealized` are returned as **strings** (e.g.
`"1234.50"`). They interpolate into the Telegram message correctly; if you
want to use them in a `priceCondition`, wrap them via `mathExpression` first.

### 8.5 P&L stop-loss circuit breaker

Polls the position book every 30 seconds. If aggregate P&L drops below
₹-2000, square off everything and notify Telegram.

```json
{
  "name": "Aggregate PnL Stop-Loss",
  "description": "Square off when total open-position pnl falls below -2000",
  "nodes": [
    { "id": "node_1", "type": "start",          "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "interval", "intervalValue": 30, "intervalUnit": "seconds", "marketHoursOnly": true } },
    { "id": "node_2", "type": "funds",          "position": { "x": 100, "y": 180 }, "data": { "outputVariable": "f" } },
    { "id": "node_3", "type": "mathExpression", "position": { "x": 100, "y": 300 }, "data": { "expression": "{{f.data.m2mrealized}} + {{f.data.m2munrealized}}", "outputVariable": "totalPnL" } },
    { "id": "node_4", "type": "priceCondition", "position": { "x": 100, "y": 420 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "field": "ltp", "operator": "<", "value": -2000 } },
    { "id": "node_5", "type": "closePositions","position": { "x":   0, "y": 540 }, "data": {} },
    { "id": "node_6", "type": "telegramAlert",  "position": { "x": 240, "y": 540 }, "data": { "username": "rajandran", "message": "PnL stop-loss tripped at {{totalPnL}}, all positions squared off" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" },
    { "id": "e4", "source": "node_4", "sourceHandle": "true", "target": "node_5" },
    { "id": "e5", "source": "node_5", "target": "node_6" }
  ]
}
```

> Note: today the `priceCondition` node compares against a quote-fetched
> field (`ltp`/`open`/etc.). If you want to compare a workflow variable like
> `{{totalPnL}}` directly, you currently need to write the value into a quote
> via the broker — or wait for a `varCondition` node. For now the example
> above is illustrative; in practice, square off via a `priceCondition` on
> the actual symbol's LTP, or use a `mathExpression` -> negative-result
> heuristic gate built from `andGate`.

### 8.6 Iron condor with custom legs

`optionsMultiOrder` accepts a `legs` array when `strategy="custom"` —
useful for any structure the preset enums don't cover (calendars, ratios,
butterflies). Each leg is `{ offset, optionType, action, quantity }` and
optionally a leg-specific `expiryDate` for diagonals.

```json
{
  "name": "NIFTY Custom Iron Fly",
  "description": "ATM straddle hedged with OTM3 wings, current-week expiry",
  "nodes": [
    { "id": "node_1", "type": "start",             "position": { "x": 100, "y": 100 }, "data": { "scheduleType": "daily", "time": "09:25", "days": [0,1,2,3,4], "marketHoursOnly": true } },
    { "id": "node_2", "type": "optionsMultiOrder", "position": { "x": 100, "y": 240 }, "data": {
      "strategy": "custom",
      "underlying": "NIFTY",
      "expiryType": "current_week",
      "action": "SELL",
      "quantity": 1,
      "priceType": "MARKET",
      "product": "NRML",
      "legs": [
        { "offset": "ATM",  "optionType": "CE", "action": "SELL", "quantity": 1 },
        { "offset": "ATM",  "optionType": "PE", "action": "SELL", "quantity": 1 },
        { "offset": "OTM3", "optionType": "CE", "action": "BUY",  "quantity": 1 },
        { "offset": "OTM3", "optionType": "PE", "action": "BUY",  "quantity": 1 }
      ],
      "outputVariable": "ironFly"
    } }
  ],
  "edges": [ { "id": "e1", "source": "node_1", "target": "node_2" } ]
}
```

### 8.7 Webhook → external HTTP forward

Receive a webhook, then fan out: place an OpenAlgo order **and** post a
copy of the payload to an external system (e.g. a Discord bot or a
spreadsheet endpoint) for audit.

```json
{
  "name": "Webhook to Order + External Audit",
  "description": "Place order from webhook payload and POST to external audit URL",
  "nodes": [
    { "id": "node_1", "type": "webhookTrigger", "position": { "x": 100, "y":  80 }, "data": { "label": "TV Webhook", "exchange": "NSE" } },
    { "id": "node_2", "type": "placeOrder",     "position": { "x":   0, "y": 220 }, "data": {
      "symbol": "{{webhook.symbol}}",
      "exchange": "{{webhook.exchange}}",
      "action": "{{webhook.action}}",
      "quantity": "{{webhook.qty}}",
      "priceType": "MARKET",
      "product": "MIS",
      "outputVariable": "ord"
    } },
    { "id": "node_3", "type": "httpRequest",    "position": { "x": 240, "y": 220 }, "data": {
      "method": "POST",
      "url": "https://audit.example.com/orders",
      "headers": "{\"Content-Type\": \"application/json\"}",
      "body": "{\"symbol\": \"{{webhook.symbol}}\", \"action\": \"{{webhook.action}}\", \"orderid\": \"{{ord.orderid}}\", \"ts\": \"{{iso_timestamp}}\"}",
      "timeout": 10,
      "outputVariable": "auditResp"
    } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_1", "target": "node_3" }
  ]
}
```

### 8.8 Three-condition AND gate

Time-window AND price-above AND no-existing-position. Demonstrates
`inputCount: 3` and `targetHandle: "input-N"`.

```json
{
  "name": "Triple-Condition Long Entry",
  "description": "Long RELIANCE only inside trading window, above 1500, with no existing long",
  "nodes": [
    { "id": "node_1", "type": "start",          "position": { "x": 200, "y":  20 }, "data": { "scheduleType": "interval", "intervalValue": 1, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "node_2", "type": "timeWindow",     "position": { "x":   0, "y": 140 }, "data": { "startTime": "09:30", "endTime": "14:30" } },
    { "id": "node_3", "type": "priceCondition", "position": { "x": 200, "y": 140 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "field": "ltp", "operator": ">", "value": 1500 } },
    { "id": "node_4", "type": "positionCheck",  "position": { "x": 400, "y": 140 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "condition": "not_exists" } },
    { "id": "node_5", "type": "andGate",        "position": { "x": 200, "y": 280 }, "data": { "inputCount": 3 } },
    { "id": "node_6", "type": "placeOrder",     "position": { "x": 200, "y": 400 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "MIS", "outputVariable": "ord" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_1", "target": "node_3" },
    { "id": "e3", "source": "node_1", "target": "node_4" },
    { "id": "e4", "source": "node_2", "sourceHandle": "true", "target": "node_5", "targetHandle": "input-0" },
    { "id": "e5", "source": "node_3", "sourceHandle": "true", "target": "node_5", "targetHandle": "input-1" },
    { "id": "e6", "source": "node_4", "sourceHandle": "true", "target": "node_5", "targetHandle": "input-2" },
    { "id": "e7", "source": "node_5", "sourceHandle": "true", "target": "node_6" }
  ]
}
```

### 8.9 Place order, wait, then auto-cancel

Demonstrates `delay` + variable interpolation of an upstream order id. Places a
LIMIT BUY at LTP - 0.5%, waits 90s, and cancels if it hasn't filled yet. The
broker will silently no-op the cancel if the order already completed, so this
is safe.

```json
{
  "name": "RELIANCE LIMIT with 90s Auto-Cancel",
  "description": "Place a sub-LTP limit and cancel if unfilled after 90 seconds",
  "nodes": [
    { "id": "node_1", "type": "start",         "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "daily", "time": "09:30", "days": [0,1,2,3,4], "marketHoursOnly": true } },
    { "id": "node_2", "type": "getQuote",      "position": { "x": 100, "y": 180 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "q" } },
    { "id": "node_3", "type": "mathExpression","position": { "x": 100, "y": 300 }, "data": { "expression": "{{q.data.ltp}} * 0.995", "outputVariable": "limitPx" } },
    { "id": "node_4", "type": "placeOrder",    "position": { "x": 100, "y": 420 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 5, "priceType": "LIMIT", "product": "MIS", "price": "{{limitPx}}", "outputVariable": "ord" } },
    { "id": "node_5", "type": "delay",         "position": { "x": 100, "y": 540 }, "data": { "delayValue": 90, "delayUnit": "seconds" } },
    { "id": "node_6", "type": "cancelOrder",   "position": { "x": 100, "y": 660 }, "data": { "orderId": "{{ord.orderid}}" } },
    { "id": "node_7", "type": "log",           "position": { "x": 100, "y": 780 }, "data": { "message": "Auto-cancel sent for {{ord.orderid}} at {{time}} IST", "level": "info" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" },
    { "id": "e4", "source": "node_4", "target": "node_5" },
    { "id": "e5", "source": "node_5", "target": "node_6" },
    { "id": "e6", "source": "node_6", "target": "node_7" }
  ]
}
```

### 8.10 Wait until square-off, then close + log

Use `waitUntil` to pause execution until 15:15 IST, then close all open
positions and log the action. Useful as a tail-end of any intraday flow.

```json
{
  "name": "Intraday Square-Off at 15:15",
  "description": "Wait until 15:15 IST, close all open positions, log the squareoff",
  "nodes": [
    { "id": "node_1", "type": "start",          "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "daily", "time": "09:25", "days": [0,1,2,3,4], "marketHoursOnly": true } },
    { "id": "node_2", "type": "waitUntil",      "position": { "x": 100, "y": 180 }, "data": { "targetTime": "15:15", "label": "Square-off window" } },
    { "id": "node_3", "type": "closePositions", "position": { "x": 100, "y": 300 }, "data": {} },
    { "id": "node_4", "type": "log",            "position": { "x": 100, "y": 420 }, "data": { "message": "Daily square-off completed at {{time}} IST", "level": "info" } },
    { "id": "node_5", "type": "telegramAlert",  "position": { "x": 100, "y": 540 }, "data": { "username": "rajandran", "message": "[OpenAlgo] Daily square-off done at {{time}} IST on {{date}}" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" },
    { "id": "e4", "source": "node_4", "target": "node_5" }
  ]
}
```

### 8.11 Quantity from a math expression

Sizes a position based on a fraction of available cash divided by LTP. Shows
`getQuote` → `funds` → `mathExpression` → `variable` (set with computed value)
→ `placeOrder` referencing the computed quantity.

```json
{
  "name": "RELIANCE 5%-of-Cash Sizing",
  "description": "Size BUY quantity at floor(0.05 * available_cash / ltp)",
  "nodes": [
    { "id": "node_1", "type": "start",          "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "daily", "time": "09:30", "days": [0,1,2,3,4], "marketHoursOnly": true } },
    { "id": "node_2", "type": "funds",          "position": { "x": 100, "y": 180 }, "data": { "outputVariable": "f" } },
    { "id": "node_3", "type": "getQuote",       "position": { "x": 100, "y": 300 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "q" } },
    { "id": "node_4", "type": "mathExpression", "position": { "x": 100, "y": 420 }, "data": { "expression": "(0.05 * {{f.data.availablecash}}) / {{q.data.ltp}}", "outputVariable": "sizedQty" } },
    { "id": "node_5", "type": "placeOrder",     "position": { "x": 100, "y": 540 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "{{sizedQty}}", "priceType": "MARKET", "product": "CNC", "outputVariable": "ord" } },
    { "id": "node_6", "type": "log",            "position": { "x": 100, "y": 660 }, "data": { "message": "Sized BUY {{sizedQty}} units at LTP {{q.data.ltp}} (cash={{f.data.availablecash}}) -> orderid {{ord.orderid}}", "level": "info" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" },
    { "id": "e4", "source": "node_4", "target": "node_5" },
    { "id": "e5", "source": "node_5", "target": "node_6" }
  ]
}
```

> The `mathExpression` result will be a float (e.g. `1.234`). The
> placeOrder node coerces the `quantity` field via `int(...)` so a float
> truncates toward zero as in Python. Wrap with `floor()` in your math if
> you want explicit rounding logic.

### 8.12 Per-day order counter (variable increment)

Keep an in-context counter of how many orders have been placed today. The
`variable` node's `increment` operation initialises to 0 if unset, so no
explicit reset is needed at the workflow's first run.

```json
{
  "name": "Hourly Buy with Daily Counter",
  "description": "Place 1 order per hour and track count via variable.increment",
  "nodes": [
    { "id": "node_1", "type": "start",       "position": { "x": 100, "y":  60 }, "data": { "scheduleType": "interval", "intervalValue": 1, "intervalUnit": "hours", "marketHoursOnly": true } },
    { "id": "node_2", "type": "placeOrder",  "position": { "x": 100, "y": 180 }, "data": { "symbol": "TATAMOTORS", "exchange": "NSE", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "MIS", "outputVariable": "ord" } },
    { "id": "node_3", "type": "variable",    "position": { "x": 100, "y": 300 }, "data": { "variableName": "todayCount", "operation": "increment" } },
    { "id": "node_4", "type": "log",         "position": { "x": 100, "y": 420 }, "data": { "message": "Order #{{todayCount}} placed: {{ord.orderid}}", "level": "info" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" },
    { "id": "e3", "source": "node_3", "target": "node_4" }
  ]
}
```

> **Counter scope.** `variable` storage is per-workflow-run today. Across
> separate scheduled runs the counter resets to 0 each time. For a true
> daily-persistent counter, write to the DB via an `httpRequest` to your
> own endpoint, or use the broker's order-book and count the orders.

### 8.13 Compound condition (AND gate, two inputs)

Place an order only when (a) it is between 09:30–14:30 **and** (b) the symbol's
LTP is above 1500.

```json
{
  "name": "RELIANCE Long Above 1500 in Window",
  "description": "Buy 1 share of RELIANCE only when LTP > 1500 between 09:30 and 14:30",
  "nodes": [
    { "id": "node_1", "type": "start",          "position": {"x":100,"y": 50}, "data": { "scheduleType": "interval", "intervalValue": 1, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "node_2", "type": "timeWindow",     "position": {"x":100,"y":150}, "data": { "startTime": "09:30", "endTime": "14:30" } },
    { "id": "node_3", "type": "priceCondition", "position": {"x":300,"y":150}, "data": { "symbol": "RELIANCE", "exchange": "NSE", "field": "ltp", "operator": ">", "value": 1500 } },
    { "id": "node_4", "type": "andGate",        "position": {"x":200,"y":250}, "data": { "inputCount": 2 } },
    { "id": "node_5", "type": "placeOrder",     "position": {"x":200,"y":350}, "data": { "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "MIS", "outputVariable": "ord" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_1", "target": "node_3" },
    { "id": "e3", "source": "node_2", "sourceHandle": "true", "target": "node_4", "targetHandle": "input-0" },
    { "id": "e4", "source": "node_3", "sourceHandle": "true", "target": "node_4", "targetHandle": "input-1" },
    { "id": "e5", "source": "node_4", "sourceHandle": "true", "target": "node_5" }
  ]
}
```

### 8.14 Indicator crossover (two indicators + AND gate)

`crossover` is **not** available as an `indicator` node — it needs two
independent series. Build it from two indicator nodes: fast above slow *now*,
and fast at-or-below slow on the *previous* bar.

Note the gate inputs use pass-through wiring (`targetHandle` only, no
`sourceHandle`) so the gate receives both results and can also evaluate false.

```json
{
  "name": "EMA golden cross",
  "nodes": [
    { "id": "n1", "type": "start", "position": {"x":0,"y":0}, "data": { "scheduleType": "interval", "intervalValue": 5, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "f", "type": "indicator", "position": {"x":0,"y":100}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "D", "source": "api", "indicatorName": "ema", "params": "{\"period\":9}", "lookbackBars": 120, "tailBars": 3, "outputVariable": "fast" } },
    { "id": "s", "type": "indicator", "position": {"x":0,"y":200}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "D", "source": "api", "indicatorName": "ema", "params": "{\"period\":21}", "lookbackBars": 120, "tailBars": 3, "outputVariable": "slow" } },
    { "id": "c1", "type": "varCondition", "position": {"x":0,"y":300}, "data": { "leftValue": "{{fast.latest.value}}", "operator": ">", "rightValue": "{{slow.latest.value}}" } },
    { "id": "c2", "type": "varCondition", "position": {"x":250,"y":300}, "data": { "leftValue": "{{fast.previous.value}}", "operator": "<=", "rightValue": "{{slow.previous.value}}" } },
    { "id": "and", "type": "andGate", "position": {"x":120,"y":400}, "data": { "inputCount": 2 } },
    { "id": "buy", "type": "placeOrder", "position": {"x":120,"y":500}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "MIS", "outputVariable": "ord" } }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "f" },
    { "id": "e2", "source": "f",  "target": "s" },
    { "id": "e3", "source": "s",  "target": "c1" },
    { "id": "e4", "source": "s",  "target": "c2" },
    { "id": "e5", "source": "c1", "target": "and", "targetHandle": "input-0" },
    { "id": "e6", "source": "c2", "target": "and", "targetHandle": "input-1" },
    { "id": "e7", "source": "and", "sourceHandle": "true", "target": "buy" }
  ]
}
```

For a death cross flip both operators (`<` on latest, `>=` on previous). To
test a cross on an earlier bar, set `offsetBars` on both indicators and
compare `{{fast.at_offset.value}}` with `{{slow.at_offset.value}}`.

### 8.15 Multi-timeframe filter

Two indicator nodes on the same symbol at different intervals. These are two
distinct fetches — the request cache only collapses *identical* requests.

```json
{
  "name": "Daily trend + intraday momentum",
  "nodes": [
    { "id": "n1", "type": "start", "position": {"x":0,"y":0}, "data": { "scheduleType": "interval", "intervalValue": 15, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "d", "type": "indicator", "position": {"x":0,"y":100}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "D", "source": "api", "indicatorName": "ema", "params": "{\"period\":20}", "lookbackBars": 100, "tailBars": 3, "outputVariable": "emaD" } },
    { "id": "i", "type": "indicator", "position": {"x":0,"y":200}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "15m", "source": "api", "indicatorName": "rsi", "params": "{\"period\":14}", "lookbackBars": 100, "tailBars": 3, "outputVariable": "rsi15" } },
    { "id": "q", "type": "getQuote", "position": {"x":0,"y":300}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "outputVariable": "q" } },
    { "id": "c1", "type": "varCondition", "position": {"x":0,"y":400}, "data": { "leftValue": "{{q.data.ltp}}", "operator": ">", "rightValue": "{{emaD.latest.value}}" } },
    { "id": "c2", "type": "varCondition", "position": {"x":250,"y":400}, "data": { "leftValue": "{{rsi15.latest.value}}", "operator": ">", "rightValue": "50" } },
    { "id": "g", "type": "andGate", "position": {"x":120,"y":500}, "data": { "inputCount": 2 } },
    { "id": "log", "type": "log", "position": {"x":120,"y":600}, "data": { "message": "Aligned: ltp={{q.data.ltp}} emaD={{emaD.latest.value}} rsi15={{rsi15.latest.value}}", "level": "info" } }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "d" },
    { "id": "e2", "source": "d", "target": "i" },
    { "id": "e3", "source": "i", "target": "q" },
    { "id": "e4", "source": "q", "target": "c1" },
    { "id": "e5", "source": "q", "target": "c2" },
    { "id": "e6", "source": "c1", "target": "g", "targetHandle": "input-0" },
    { "id": "e7", "source": "c2", "target": "g", "targetHandle": "input-1" },
    { "id": "e8", "source": "g", "sourceHandle": "true", "target": "log" }
  ]
}
```

### 8.16 Stateless "price retested a level today"

Flow keeps no state between runs, so "price came back to PDH earlier today"
cannot be a stored flag. Read **today's session low** from the quote instead:
if `data.low <= PDH`, price has already visited that level today. Combined
with a re-entry guard, this expresses a gap-aware breakout with no memory.

```json
{
  "name": "PDH breakout with gap-up retest filter",
  "nodes": [
    { "id": "n1", "type": "start", "position": {"x":0,"y":0}, "data": { "scheduleType": "interval", "intervalValue": 1, "intervalUnit": "minutes", "marketHoursOnly": true } },
    { "id": "pd", "type": "priorPeriodOhlc", "position": {"x":0,"y":100}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "period": "previous_day", "source": "api", "outputVariable": "pd" } },
    { "id": "q", "type": "getQuote", "position": {"x":0,"y":200}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "outputVariable": "q" } },
    { "id": "win", "type": "timeWindow", "position": {"x":0,"y":300}, "data": { "startTime": "09:20", "endTime": "15:00" } },
    { "id": "brk", "type": "varCondition", "position": {"x":0,"y":400}, "data": { "leftValue": "{{q.data.ltp}}", "operator": ">", "rightValue": "{{pd.pdh}}" } },
    { "id": "retest", "type": "varCondition", "position": {"x":250,"y":400}, "data": { "leftValue": "{{q.data.low}}", "operator": "<=", "rightValue": "{{pd.pdh}}" } },
    { "id": "pos", "type": "positionCheck", "position": {"x":500,"y":400}, "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "product": "NRML", "condition": "not_exists" } },
    { "id": "g", "type": "andGate", "position": {"x":250,"y":500}, "data": { "inputCount": 4 } },
    { "id": "ce", "type": "optionsOrder", "position": {"x":250,"y":600}, "data": { "underlying": "NIFTY", "expiryType": "current_week", "offset": "ATM", "optionType": "CE", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "NRML", "outputVariable": "ce" } }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "pd" },
    { "id": "e2", "source": "pd", "target": "q" },
    { "id": "e3", "source": "q", "target": "win" },
    { "id": "e4", "source": "win", "target": "brk" },
    { "id": "e5", "source": "win", "target": "retest" },
    { "id": "e6", "source": "win", "target": "pos" },
    { "id": "e7",  "source": "win",    "target": "g", "targetHandle": "input-0" },
    { "id": "e8",  "source": "brk",    "target": "g", "targetHandle": "input-1" },
    { "id": "e9",  "source": "retest", "target": "g", "targetHandle": "input-2" },
    { "id": "e10", "source": "pos",    "target": "g", "targetHandle": "input-3" },
    { "id": "e11", "source": "g", "sourceHandle": "true", "target": "ce" }
  ]
}
```

Mirror it for the short side: `{{q.data.ltp}} < {{pd.pdl}}` and
`{{q.data.high}} >= {{pd.pdl}}`.

`positionCheck` with `not_exists` is what enforces one trade per breakout —
it asks the broker, so unlike a counter variable it survives restarts.

---

## 9. Exchanges

Valid `exchange` values across all nodes:

| Code | Segment |
|---|---|
| `NSE` | NSE Equity |
| `BSE` | BSE Equity |
| `NFO` | NSE F&O |
| `BFO` | BSE F&O |
| `CDS` | NSE Currency |
| `BCD` | BSE Currency |
| `MCX` | Commodity |
| `NCDEX` | Commodity |
| `NSE_INDEX` | NSE Indices (for `optionsOrder`/`optionChain`/`optionSymbol`/`syntheticFuture`) |
| `BSE_INDEX` | BSE Indices (same usage as above) |

---

## 10. Symbol format

OpenAlgo standardizes broker-specific symbols to the following format. See
`docs/prompt/symbol-format.md` for the complete spec; the short form:

- **Equity:** `INFY`, `RELIANCE`, `TATAMOTORS`
- **Futures:** `<base><DDMMMYY>FUT` — `BANKNIFTY24APR24FUT`, `CRUDEOILM20MAY24FUT`
- **Options:** `<base><DDMMMYY><strike><CE|PE>` — `NIFTY28MAR2420800CE`, `VEDL25APR24292.5CE`
- **Indices:** `NIFTY`, `SENSEX`, `BANKNIFTY` etc. on `NSE_INDEX` / `BSE_INDEX`

---

## 11. Order constants

For convenience in one place:

- **Action:** `BUY`, `SELL`
- **Product:** `CNC` (cash & carry / delivery), `NRML` (futures & options carry), `MIS` (intraday)
- **Price type:** `MARKET`, `LIMIT`, `SL` (stop-loss limit), `SL-M` (stop-loss market)
- **Option type:** `CE`, `PE`
- **Strike offset:** `ATM`, `ITM1`–`ITM5`, `OTM1`–`OTM10`
- **Expiry type (preset):** `current_week`, `next_week`, `current_month`, `next_month`

---

## 12. Common patterns

### Use the first expiry from the dynamic list

```
expiry node (outputVariable=expiries)  →  symbol-using node ({{expiries.data[0]}})
```

### Place an order conditional on free margin

```
fundCheck (minAvailable=50000)
   ├── true  → placeOrder ...
   └── false → log "Insufficient funds"
```

### Cancel an order after a fixed delay

```
placeOrder (outputVariable=ord)  →  delay (60s)  →  cancelOrder (orderId={{ord.orderid}})
```

### Square off everything if MTM crosses a P&L threshold

```
positionBook (outputVariable=positions)
  → mathExpression (expression=sum of {{positions.data[i].pnl}})
  → priceCondition (operator="<", value=-5000) on the computed MTM
      └── true  → closePositions
```

---

## 13. Pitfalls

- **Missing top-level `name` on import.** The Flow Editor's import dialog
  rejects any JSON missing a `name` field with *"Invalid workflow format.
  Must have name, nodes, and edges."* The executor itself never reads it —
  only the importer does. See §1.
- **`JSON.parse` failures during paste.** *"Invalid JSON format. Please
  check the workflow data."* always means the text isn't valid JSON. Common
  causes: smart-quote conversion (`"` → `"` `"`) by Slack/Discord/word
  processors, BOM/zero-width characters from doc editors, real newlines
  injected inside a string value (use `\n` if you need a newline, never a
  literal line break inside `"..."`). The fix-of-last-resort is to save the
  JSON to a `.json` file and use the **file upload** button in the import
  dialog — that path goes through `FileReader` and bypasses clipboard
  munging entirely.
- **Output variable not set.** If a downstream node references `{{name.field}}`
  but the upstream producer doesn't have `outputVariable: "name"` set, the
  literal `{{name.field}}` string is passed through. The workflow runs but
  the value is wrong. The Execution Log will show the placeholder verbatim.
- **`sourceHandle` mismatch.** PositionCheck/FundCheck/PriceCondition/TimeWindow
  fork on `"true"`/`"false"`, while NotGate/TimeCondition fork on `"yes"`/`"no"`.
  Both vocabularies are accepted, but be consistent within a workflow.
- **AND/OR gate target slots.** Without `targetHandle: "input-N"`, multiple
  edges into a gate are treated ambiguously. Always pin them.
- **Webhook trigger without saved workflow.** The webhook URL is minted on
  save. Importing a workflow with a `webhookTrigger` node and trying to use
  the URL before saving will fail. Save first, then copy the URL from the
  ConfigPanel.
- **`expiryDate` format.** Strings like `"30DEC25"` (no separator, uppercase
  month). The `expiry` node returns `"30-DEC-25"` (with hyphens) — pass that
  through `_format_expiry_for_api` if hand-converting, or use `expiryType`
  presets which the executor resolves automatically.
- **History is capped at 200 bars.** Every history-reading node
  (`history`, `indicator`, `barOffset`, `priorPeriodOhlc`) requests at most
  the latest 200 bars for the chosen interval, and the cap is applied when
  sizing the request window - a 10-year 1-minute range (~900k rows) never
  reaches the broker. Tunable via `FLOW_MAX_HISTORY_BARS`.
- **Identical history requests are cached** for a short TTL and collapse to
  one broker call, so several indicators on the same symbol/interval do not
  multiply rate-limit pressure. Distinct requests still cost a call each.
- **`interval` is free text, not an enum.** Broker support varies; use the
  `intervals` node to discover it, or `source: "db"` to resample locally
  from Historify regardless of broker capability.
- **Unresolved operands in `varCondition` take neither branch.** Unlike other
  interpolation (which passes `{{...}}` through as literal text), this node
  refuses to evaluate so a typo cannot route a trade.
- **Lot size handling differs per node.** `optionsOrder` and
  `optionsMultiOrder` accept `quantity` **in lots** (multiplied by lot size
  internally). `placeOrder` / `smartOrder` / `splitOrder` / `basketOrder`
  accept `quantity` **in shares**. Check this when generating from a single
  source.

---

## 14. Where this is enforced

- Node type strings: `services/flow_executor_service.py` (top-level
  `execute_node_chain` dispatch).
- Per-node field reads: each `execute_*` method in
  `services/flow_executor_service.py`.
- UI defaults: `frontend/src/lib/flow/constants.ts` (`DEFAULT_NODE_DATA`).
- UI ↔ field mapping: `frontend/src/components/flow/panels/ConfigPanel.tsx`.
- Edge filtering: `services/flow_executor_service.py:execute_node_chain`
  → the `if result and "condition" in result:` block.

If this doc and the code disagree, the code wins. Open a PR.
