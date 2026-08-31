# Flow Editor - Import JSON Reference

This document is the source of truth for hand-writing or generating workflow
JSON that can be imported into the OpenAlgo Flow Editor. It covers the
top-level workflow shape, every node type, every edge variant, the variable
interpolation grammar, and the source-handle vocabulary that drives condition
branching.

If you are writing a tool that produces flow JSON (an LLM agent, a script,
another editor), feed this file in as a system prompt - it is written in a
flat declarative style suitable for that purpose.

---

## 0. Output contract - read before generating anything

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
  If a requirement has no matching node, say so in prose - do not fabricate
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
| Structured trade logs, backtesting, general date arithmetic | Not Flow. Order Book / Trade Book / P&L Tracker hold the trade record; `variable.append` only provides simple text concatenation. |
| `crossover` / `crossunder` / `correlation` / `beta` as an `indicator` | Two `indicator` nodes plus an `andGate` - see §8.14. |

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
below is a *shape diagram*, not import-ready - see §8 for runnable examples):

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

### Value validation

Presence is not the only check. On import, save and activation the validator
also rejects:

- an `exchange`, `action`, `product` or `priceType` outside
  [§11 Order constants](#11-order-constants) - case-insensitive. Several broker
  mappers substitute a default for an unrecognised value rather than refusing
  it, so `"LIMT"` would have become a MARKET order.
- a `quantity` or `splitSize` that is not a positive number, except that
  `smartOrder.quantity` may be zero when `positionSize` drives the target
  position or square-off.
- `httpRequest` `headers` that are not a JSON object written as a string, and a
  `timeout` outside 1000..60000 milliseconds.

A value containing `{{...}}` is skipped here, because it is only knowable at
run time - order nodes check those separately, immediately before the broker
call. See
[Unresolved references on order nodes](#unresolved-references-on-order-nodes).

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
**"Invalid JSON format. Please check the workflow data."** - that always
indicates a syntax problem with the JSON text itself, not a missing field.

### Persisted vs minimal node

The DB stores additional UI-only fields per node (`measured`, `dragging`,
`selected`). They are not required for import - the executor reads only `id`,
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

### Every order field takes a reference

There is no field on an order node that must be a literal. The editor shows a
picker by default and a `{ }` toggle swaps it for a text box, but the stored
value is the same either way: a dropdown field holding `{{webhook.exchange}}` is
just a string, and the executor interpolates it like any other.

That includes the ones a form makes look fixed:

| Field | Reference must resolve to |
|---|---|
| `exchange` | `NSE`, `BSE`, `NFO`, `BFO`, `CDS`, `BCD`, `MCX`, `NCDEX`, `NCO` |
| `action` | `BUY` or `SELL` |
| `quantity`, `splitSize`, `positionSize` | a whole number |
| `product` | `CNC`, `NRML`, `MIS` |
| `priceType` | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| `price`, `triggerPrice` | a number, and only read for the price types that use them |
| `optionType` | `CE` or `PE` |
| `offset` | `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50` |
| `expiryType` | a relative type or a `DDMMMYY` date |

Matching is case-insensitive on every field in that list except the numeric ones,
so a payload carrying `"action": "buy"` is accepted.

A field holding **exactly one whole token** keeps its type, so
`"quantity": "{{webhook.quantity}}"` against a payload of `{"quantity": 10}`
arrives as the number `10`, not the string `"10"`. A field mixing a token with
other text always resolves to a string.

### Unresolved references on order nodes

Order-defining fields are checked before the node runs, and a `{{reference}}`
that does not resolve fails the node instead of falling back to a default.

This applies to `placeOrder`, `smartOrder`, `optionsOrder`, `optionsMultiOrder`,
`basketOrder`, `splitOrder`, `modifyOrder`, `cancelOrder` and `closePositions`,
on these fields:

`symbol` `exchange` `action` `quantity` `product` `priceType` `price`
`triggerPrice` `splitSize` `positionSize` `underlying` `strike` `optionType`
`expiryDate` `orderId` `newQuantity` `newPrice` `newTriggerPrice` `orders`
`legs`, plus the legacy lowercase spelling `pricetype`.

Why it matters: a numeric field cannot parse `{{webhook.qty}}`, so it used to
take the field default of `1`, and an unresolved `priceType` fell through the
broker mapping to `MARKET`. A webhook that simply omitted a key therefore placed
a **successful order for the wrong size at the wrong price type**, with nothing
in the run to say so. Now the node fails, the run is marked `failed`, and
nothing downstream of it executes.

Label fields are deliberately exempt -- `strategy`, `strategyTag` and
`outputVariable` still pass an unresolved reference through as text.

When a webhook may legitimately omit a value, give the node a literal instead of
a variable, or branch on a condition node first.

### Schedules run on the clock, and inside market hours

**An `interval` schedule is anchored to the clock, not to activation.** "Every
minute" fires at HH:MM:05 and "every 5 minutes" at :00, :05, :10, whenever the
workflow happened to be switched on. It used to count from activation time, so
the phase changed on every restart, which decides by luck whether a bar-reading
strategy sees the candle that just closed. A small offset (`FLOW_INTERVAL_ALIGN_OFFSET`,
default 2 seconds) puts the run just inside the new bar rather than racing the
one that is closing. Sub-minute intervals are left unaligned; there is no
meaningful boundary.

**A schedule is only as fresh as the history cache.** The indicator and history
nodes reuse a fetch for `FLOW_HISTORY_CACHE_TTL` seconds, 30 by default. That is
well under a 5-minute candle and half of a 1-minute one, so lower it for a
1-minute strategy or it can act on the previous bar.

**The window narrows the exchange's session, it never reopens it.** A holiday
or a weekend stays shut whatever `marketHoursStart` and `marketHoursEnd` say,
because the day is resolved through the platform's own market calendar. Set
`marketHoursExchange` to what you trade so MCX and CRYPTO inherit their real
hours instead of equity ones.

### What a node does when something fails

A node that cannot get a trustworthy answer returns an error rather than a
value. That matters most on the condition nodes, because a wrong answer there
routes a branch and can place a trade.

| Situation | What happens |
|---|---|
| `priceCondition`, `positionCheck` or `fundCheck` gets a failed broker read | the node errors and takes **neither** branch. It does not read the missing data as `0` |
| A condition cannot be evaluated | it takes neither branch, and a gate wired to it stays **pending** rather than treating the failure as `False` |
| A gate has fewer edges wired than its `inputCount` | it errors instead of evaluating on part of the condition |
| An order field holds an unresolved `{{reference}}` | the node fails before the broker call |
| Any node returns an error | the branch below it stops, and the run is marked `failed` |

The failure message is the broker's or the service's own text - "insufficient
funds", "RMS blocked", "symbol not found" - in the run record and in the webhook
response.

**A window that crosses midnight is expressed directly.** `timeWindow` with
`startTime` after `endTime`, such as `22:00` to `02:00`, is treated as spanning
midnight rather than as an empty window.

**`unsubscribe` needs a symbol** unless `streamType` is `all`. A specific mode
with no symbol is refused, because the underlying call clears every
subscription on the instance, including the ones the Sandbox engine uses to
trigger pending SL and LIMIT orders.

**Subscriptions are released with the workflow.** A subscribe node opens a
broker-side subscription against a process-wide client, so one left behind is
held for the life of the worker and counts against the per-broker symbol
ceiling that `/trading` and the Sandbox engine share. Deactivating or deleting
a workflow now gives back everything it opened. You still do not need an
`unsubscribe` node for cleanup; use one only to drop a stream mid-run.

**A condition evaluates once per run.** A condition reachable by two paths used
to evaluate once per path and follow its branch each time, so a diamond placed
two orders from one trigger. Gates already behaved this way; conditions now
match.

**`waitUntil` is bounded.** The wait holds the workflow's lock and the request
that triggered the run, so a target more than 30 minutes away is refused with a
message pointing at a schedule trigger instead. Use `start` for a square-off
hours later.

### Path grammar

- **Dotted keys** for dict access: `{{order.data.orderid}}`
- **Bracket index** for list/tuple access: `{{expiries.data[0]}}`
- **Combined**: `{{chain.data.results[0].ce.ltp}}`
- **Negative indices are not supported.** Use a positive index.

If any segment of the path is missing or the variable does not exist, the
entire `{{...}}` placeholder is left **literally** in the rendered string -
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

Data nodes ship with a default `outputVariable` (`orders`, `trades`,
`positions`, `holdings`, `funds`, `quotes`, `holidays`, `timings`,
`marginResult`, `response`, `ind`, ...), and the editor persists it. Set your
own when two nodes of the same type would otherwise collide.

An unresolved `{{name.path}}` interpolates to its own literal text rather than
raising. On most fields that is harmless -- an alert message simply contains the
literal `{{...}}`. On an **order node it is a failure**: see below.

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

When the trigger is a `webhookTrigger`, the inbound body is exposed as
`{{webhook.<key>}}`. A TradingView alert sending
`{"symbol": "RELIANCE", "action": "BUY", "qty": 10}` exposes
`{{webhook.symbol}}`, `{{webhook.action}}`, `{{webhook.qty}}`.

**The body is parsed as JSON whatever the sender declared.** External platforms
are the callers least able to set a `Content-Type`, so the header is treated as
a hint rather than the truth. A body that is not JSON falls through to form
fields, then to raw text:

| Body | Becomes |
|---|---|
| JSON object, any declared type | its own keys |
| Form-encoded | its own fields |
| JSON that is not an object (a list, a bare number) | `{{webhook.message}}` plus `{{webhook.payload}}` |
| Anything else | `{{webhook.message}}` holding the raw text |

**A secret in the payload requires JSON.** With `payload` auth the secret is a
field, and plain text has nowhere to put one, so such a request is refused with
401 rather than reaching the workflow. Send JSON, or switch the webhook to URL
auth and pass `?secret=...`. A body carrying no secret is refused the same way,
so plain text only reaches a workflow that requires none.

**Casing.** `action`, `product`, `priceType`, `exchange` and `optionType` are
upper-cased before validation, so `"buy"` and `"BUY"` both work. `symbol` on the
order nodes is upper-cased too, because the symbol lookup is exact and an alert
does not control its own casing. The data nodes (`getQuote`, `history`, ...) do
**not** normalise it yet, so send an upper-case symbol to those.

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

The executor accepts both vocabularies as synonyms - `{yes, true}` is the
truthy branch, `{no, false}` is the falsy branch - but it is good practice
to use the vocabulary native to each node so saved workflows match the UI.

Edges that source from a condition node and **do not** specify a `sourceHandle`
are followed unconditionally on every run (use this for "fire-and-forget" log
or telegram nodes that want to see every result).

**Gates read values, not branches.** An edge whose target is a gate is followed
whatever its `sourceHandle` says and whatever the condition returned, because
the executor checks for a gate target before it checks the handle. So a gate fed
through `sourceHandle: "true"` edges still receives the `False` result and its
false branch works.

This page used to say the opposite. Pass-through wiring (only `targetHandle`, no
`sourceHandle`) is still the clearer way to express it, because the edge is not
claiming a branch it does not act on:

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

> **Strict import and activation validation reject a second trigger.** A
> workflow must have exactly one trigger so every node has one unambiguous
> execution root. If a strategy needs two schedules (say entries each minute
> and a square-off at 14:00), either express the second as a
> `timeWindow`-gated branch on the same trigger, or split it into a second
> workflow.
>
> Note that splitting costs broker calls: branches sharing one trigger also
> share their data nodes, whereas separate workflows each re-fetch. Quotes and
> the order book are **not** de-duplicated by the history cache.

#### start - Schedule Trigger

Fires on a clock schedule.

| Field | Type | Default | Notes |
|---|---|---|---|
| `scheduleType` | `"once"` \| `"daily"` \| `"weekly"` \| `"interval"` | `"daily"` | |
| `time` | `"HH:MM"` | `"09:15"` | Required for `once` / `daily` / `weekly`. |
| `days` | `number[]` | `[0,1,2,3,4]` | **`weekly` only.** 0=Mon, 1=Tue, ..., 6=Sun. The `daily` branch builds a cron trigger from `time` alone and never reads `days`, so `scheduleType: "daily"` with `days: [0,1,2,3,4]` still fires on Saturday and Sunday. Use `weekly` for a weekday-only schedule, and set `marketHoursOnly` as well: an imported JSON that omits it is not gated. |
| `executeAt` | `"YYYY-MM-DD"` | - | Required when `scheduleType="once"`. |
| `intervalValue` | number | `1` | For `interval` mode. |
| `intervalUnit` | `"seconds"` \| `"minutes"` \| `"hours"` | `"minutes"` | For `interval` mode. |
| `marketHoursOnly` | boolean | **`false` when the key is absent** | Skip runs outside the trading window. The editor writes `true` into every new schedule node, so a workflow built there is gated. A hand-written or imported JSON that omits the key **runs around the clock**: set it explicitly. |
| `marketHoursStart` | `"HH:MM"` | `"09:15"` | Start of the window. |
| `marketHoursEnd` | `"HH:MM"` | `"15:15"` | End of the window. |
| `marketHoursExchange` | exchange code | `"NSE"` | Which calendar to read. MCX runs to 23:55 and CRYPTO never closes, so this matters for anything but equity. |
| `marketHoursOnly` | boolean | **`false` when the key is absent** | Skip runs outside the trading window. The editor writes `true` into every new schedule node, so a workflow built there is gated. A hand-written or imported JSON that omits the key **runs around the clock**: set it explicitly. |
| `marketHoursExchange` | string | `"NSE"` | Which exchange calendar sets the window. `MCX` runs to 23:55, `CRYPTO` never closes. |
| `marketHoursStart` | `"HH:MM"` | exchange open | Narrows or widens the start. Omit to use the exchange's own open. |
| `marketHoursEnd` | `"HH:MM"` | exchange close | Narrows or widens the end. Omit to use the exchange's own close. |

The window is resolved from the market calendar, not from fixed times, so
weekends, trading holidays and special sessions (muhurat) are handled for you
and each exchange gets its own hours. `marketHoursStart` / `marketHoursEnd`
override the clock only - **they cannot reopen a day the exchange is shut**,
so a workflow cannot configure its way into trading on Diwali.

Both are read from the graph on every run, so editing them applies from the
next run without deactivating and reactivating the workflow.

```json
{
  "id": "node_1",
  "type": "start",
  "position": { "x": 100, "y": 100 },
  "data": {
    "scheduleType": "daily",
    "time": "09:20",
    "days": [0, 1, 2, 3, 4],
    "marketHoursOnly": true,
    "marketHoursExchange": "NSE",
    "marketHoursStart": "09:15",
    "marketHoursEnd": "15:40"
  }
}
```

#### priceAlert - Price Alert Trigger

Fires when an LTP condition is met. The price-monitor service polls the
configured symbol on a 1-second tick.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | - | OpenAlgo symbol format. |
| `exchange` | string | `"NSE"` | See [§9 Exchange codes](#9-exchanges). |
| `condition` | `"above"` \| `"below"` \| `"crosses_above"` \| `"crosses_below"` | `"above"` | |
| `price` | number | - | Target price. For channel modes, see `priceLower`/`priceUpper`. |
| `priceLower` | number | - | Used by `entering_channel` / `inside_channel` / etc. (advanced). |
| `priceUpper` | number | - | |
| `trigger` | `"once"` \| `"every_time"` | `"once"` | Whether to re-fire after first match. |
| `expiration` | `"none"` \| `"1h"` \| `"4h"` \| `"1d"` \| `"1w"` | `"none"` | Auto-disable after this duration. |
| `playSound` | boolean | `true` | UI-only. |
| `message` | string | - | Optional custom message. |

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

#### webhookTrigger - Webhook Trigger

Fires when an external system POSTs to the workflow's webhook URL. The URL and
secret are minted by the server when the workflow is saved; you cannot
hand-write them.

| Field | Type | Default | Notes |
|---|---|---|---|
| `label` | string | - | Display name (e.g. `"TradingView Alert"`). |

**The trigger carries no instrument.** It used to accept `symbol` and
`exchange`, and this document described `symbol` as a filter. It never was one:
the executor read neither field, so they only ever labelled the node on the
canvas. Both are gone. Everything the workflow acts on arrives in the request
and is read downstream as `{{webhook.<field>}}`.

The body is exposed as `{{webhook.<key>}}` to every downstream node, so
`{"symbol": "RELIANCE", "action": "BUY", "qty": 10}` gives
`{{webhook.symbol}}`, `{{webhook.action}}` and `{{webhook.qty}}`.

```json
{
  "id": "node_1",
  "type": "webhookTrigger",
  "position": { "x": 100, "y": 100 },
  "data": { "label": "TradingView Long Entry" }
}
```

#### orderUpdateTrigger - Order Update Trigger

Fires when an order changes status (fill, rejection, cancellation), pushed
from the account order-update stream - no polling.

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | - | Literal broker order id. **`{{variable}}` references are rejected** - a trigger has no upstream node to resolve them. |
| `symbol` | string | - | OpenAlgo symbol. |
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

The six priced order nodes (`placeOrder`, `smartOrder`, `optionsOrder`,
`optionsMultiOrder`, `basketOrder`, and `splitOrder`) use the same static price
rules: `LIMIT` and `SL` require a positive `price`; `SL` and `SL-M` require a
positive `triggerPrice`. A missing, blank, zero, or negative required price is
rejected. A `{{variable}}` price passes import validation and is checked after
interpolation before the broker call.

#### Product defaults

`product` is optional on every order and position node. **Omit it and the
node's `exchange` decides**: a derivative segment - `NFO`, `BFO`, `CDS`, `BCD`,
`MCX`, `NCDEX`, `NCO` - defaults to `NRML`, and everything else to `MIS`.

Write `product` only to override that. It is used exactly as given, so `MIS` on
an `NFO` order really is an intraday order that the broker squares off at the
close. An index pseudo-exchange (`NSE_INDEX`, ...) is not a segment orders are
placed on and defaults to `MIS`.

Two nodes do not follow their `exchange`, because on them that field names
where the *underlying* is quoted rather than where the contract trades:
`optionsOrder` and `optionsMultiOrder` default to `NRML` outright.

`basketOrder` decides per row: with no `product` on the node, each row follows
its own `exchange`, so one basket can mix an `MIS` cash row and an `NRML`
commodity row. A `product` on the node covers every row that does not set its
own. Present-but-blank is still an error - that is a `{{variable}}` that failed
to resolve, and the node refuses rather than guessing.

#### placeOrder - Place Order

Single-leg order on any segment.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | - | OpenAlgo symbol format. |
| `exchange` | string | `"NSE"` | |
| `action` | `"BUY"` \| `"SELL"` | `"BUY"` | |
| `quantity` | int | `1` | In shares (not lots). |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | by `exchange` | See **Product defaults**. |
| `price` | number | `0` | Required for `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Required for `SL`/`SL-M`. |
| `outputVariable` | string | - | If set, exposes `{{name.orderid}}`, `{{name.status}}`. |

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

#### smartOrder - Smart Order

Position-aware order. The broker computes the delta between current position
and `positionSize` and places the appropriate order to reach it.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `action`, `priceType`, `product` | (as `placeOrder`) | | |
| `quantity` | int | `1` | Non-negative. Zero is valid when `positionSize` drives target-position reconciliation. |
| `positionSize` | int | `0` | Target net position. Positive=long, negative=short, 0=use `quantity`. |
| `price` | number | `0` | Common order price. Must be positive for `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Common trigger price. Must be positive for `SL`/`SL-M`. |
| `outputVariable` | string | - | |

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
    "price": 0,
    "triggerPrice": 0,
    "outputVariable": "smartResult"
  }
}
```

#### optionsOrder - Options Order

Single-leg options order resolved from underlying + offset + option type.

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | NSE: `"NIFTY"` \| `"BANKNIFTY"` \| `"FINNIFTY"` \| `"MIDCPNIFTY"` \| `"NIFTYNXT50"`; BSE: `"SENSEX"` \| `"BANKEX"` \| `"SENSEX50"`; MCX: `"GOLD"` \| `"GOLDM"` \| `"SILVER"` \| `"SILVERM"` \| `"CRUDEOIL"` \| `"CRUDEOILM"` \| `"NATURALGAS"` \| `"NATGASMINI"` \| `"COPPER"` \| `"ZINC"` \| `"MCXBULLDEX"` | `"NIFTY"` | Decides the exchange on its own - see **Underlying and exchange** below. |
| `exchange` | `"NSE_INDEX"` \| `"NFO"` \| `"BSE_INDEX"` \| `"BFO"` \| `"MCX"` \| `"CDS"` \| `"BCD"` \| `"NCDEX"` \| `"NCO"` | `"NSE_INDEX"` | **Only consulted for an `underlying` not listed above.** |
| `expiryType` | relative type, **or** a `DDMMMYY` date, or a reference | `"current_week"` | A relative type (`"current_week"`, `"next_week"`, `"current_month"`, `"next_month"`) is resolved by the Symbol service. A `DDMMMYY` value such as `"28OCT25"` is used as given, which is how a far contract the four choices cannot reach is named. MCX contracts are monthly, so use `"current_month"`/`"next_month"` there. |
| `expiryDate` | `"DDMMMYY"` or a reference | - | Optional. The same explicit date under its own key, for callers that prefer to send the two apart. Wins over `expiryType` when both are set. |
| `offset` | `"ATM"` \| `"ITM1"`-`"ITM50"` \| `"OTM1"`-`"OTM50"` | `"ATM"` | Checked against `OPTION_OFFSET_PATTERN`. Counted in strikes the contract actually lists, walking out from ATM, so an offset further than the chain reaches resolves to nothing and the leg is refused at run time rather than at import. |
| `optionType` | `"CE"` \| `"PE"` | `"CE"` | |
| `action` | `"BUY"` \| `"SELL"` | `"BUY"` | |
| `quantity` | int | `1` | **In lots** (executor multiplies by lot size). |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | |
| `product` | `"MIS"` \| `"NRML"` | `"NRML"` | Always a derivative; does not follow `exchange`. |
| `price` | number | `0` | For `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | For `SL`/`SL-M`. |
| `splitSize` | int | `0` | If >0, splits into chunks. |
| `outputVariable` | string | - | |

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

**Underlying and exchange.** The two options nodes resolve *two* exchanges: the
one whose price sets the ATM reference, and the one the option contract trades
on. Every underlying in the table above decides both by name:

| Underlying | ATM reference quoted from | Option trades on |
|---|---|---|
| NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 | `NSE_INDEX` (the index level) | `NFO` |
| SENSEX, BANKEX, SENSEX50 | `BSE_INDEX` (the index level) | `BFO` |
| GOLD, GOLDM, SILVER, SILVERM, CRUDEOIL, CRUDEOILM, NATURALGAS, NATGASMINI, COPPER, ZINC, MCXBULLDEX | `MCX` (the **near-month future**) | `MCX` |

MCX differs from the equity segments in two ways that matter when writing a
workflow by hand:

- **There is no separate derivatives exchange.** NFO is to NSE what nothing is
  to MCX - the future, the option and the quote all live on `MCX`.
- **There is no spot instrument.** `CRUDEOIL` on its own is not a tradable
  symbol, so the ATM strike is priced off the nearest unexpired future
  (`CRUDEOIL21SEP26FUT`), resolved automatically. If no unexpired future exists
  the node fails rather than guessing a reference price.

The `exchange` field is a **fallback, not an override**: it is read only when
`underlying` is not one of the names above, which is how you reach a stock
option (`"underlying": "SBIN", "exchange": "NFO"`) or a commodity the editor
does not list (`"underlying": "MENTHAOIL", "exchange": "MCX"`). A named
underlying always wins, so a workflow whose `exchange` still holds the node
default cannot misroute a SENSEX or CRUDEOIL order.

`quantity` is in **lots** for every underlying. The lot size comes from the
master contract, and most MCX option contracts carry a lot size of 1, so one lot
is one contract there.

#### optionsMultiOrder - Multi-Leg Options Strategy

Pre-defined or custom multi-leg strategies (straddle / strangle / iron condor /
spreads / custom).

| Field | Type | Default | Notes |
|---|---|---|---|
| `strategy` | `"straddle"` \| `"strangle"` \| `"iron_condor"` \| `"bull_call_spread"` \| `"bear_put_spread"` \| `"custom"` | `"custom"` | Absent means `custom`, which then requires `legs`. |
| `underlying` | (as `optionsOrder`) | `"NIFTY"` | |
| `expiryType` | (as `optionsOrder`) | `"current_week"` | One common expiry for every generated or custom leg. Takes a relative type or a `DDMMMYY` date. |
| `expiryDate` | `"DDMMMYY"` or a reference | - | Optional explicit date under its own key. Wins over `expiryType`. A leg may still override both. |
| `action` | `"BUY"` \| `"SELL"` | - | Direction for the strategy (BUY=long volatility, SELL=short volatility). |
| `quantity` | int | `1` | Lots per leg. |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | Common price type; generated legs do not support `SL`/`SL-M`, while custom legs may inherit all four types. |
| `product` | `"MIS"` \| `"NRML"` | `"NRML"` | Always a derivative; does not follow `exchange`. |
| `price` | number | `0` | Common leg price. Must be positive when the effective price type is `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Common custom-leg trigger. Must be positive when the effective price type is `SL`/`SL-M`. |
| `legs` | `Leg[]` | `[]` | **Required for `strategy="custom"`.** See **Custom legs** below. |
| `outputVariable` | string | - | Result includes `{{name.results}}` array per leg. |

**Custom legs.** A readymade strategy positions every leg at an offset from the
money and gives them all one expiry. `strategy: "custom"` lifts both limits: a
leg names its own strike, its own expiry and its own side, which is what makes a
calendar spread, a diagonal, a ratio, or a basket pinned to chosen strikes
expressible. The editor builds these leg by leg, and can load a readymade
strategy's legs as a starting point to edit.

In the editor the strike and expiry are chosen from the contracts the exchange
actually lists - strikes carry their moneyness (`ATM`, `ITM3`, `OTM2`) and the
symbol they resolve to, and expiry is a plain list of listed dates. A field can
still be typed instead, which is how a `{{variable}}` strike or expiry is
entered, and typing is the fallback whenever the contract lookup is unavailable.
What gets stored is the same either way: a number and a `DDMMMYY` string.

A leg with **no** `expiry` or `expiryType` follows the node's expiry, so a
scheduled workflow rolls forward to the next contract on its own. Giving a leg
its own `expiry` pins it to that one contract - correct for a calendar or
diagonal spread, and a basket that stops working once that date passes for
anything else. The editor leaves an untouched leg following the node and shows
the date it currently resolves to; picking a date pins it. `expiryType` is
accepted on import for a leg that should roll on a different schedule than the
node, though the editor does not offer it.

| Leg field | Type | Default | Notes |
|---|---|---|---|
| `strikeMode` | `"OFFSET"` \| `"STRIKE"` | `"OFFSET"` | Absent is `OFFSET`. A leg carrying `strike` and no mode is read as `STRIKE`. |
| `offset` | `"ATM"` \| `"ITM1"`-`"ITM50"` \| `"OTM1"`-`"OTM50"` | - | **Required unless `strike` is given.** Re-resolved against the live underlying on every run, counted in strikes the contract lists. |
| `strike` | number | - | **Required when `strikeMode` is `STRIKE`.** An absolute strike, used exactly as given; must be positive and must be listed for that expiry. |
| `expiry` | string | - | Overrides the node expiry with an exact date in `DDMMMYY`, e.g. `28OCT25`. |
| `expiryType` | `"current_week"` \| `"next_week"` \| `"current_month"` \| `"next_month"` | - | Overrides the node expiry with a relative one. Ignored when `expiry` is set. |
| `optionType` | `"CE"` \| `"PE"` | - | Required. |
| `action` | `"BUY"` \| `"SELL"` | - | Required. The leg's own side, independent of the node `action`. |
| `quantity` | int | - | Required. **In lots**, multiplied by the lot size like the node-level quantity. |
| `product` | `"MIS"` \| `"NRML"` | node `product` | |
| `priceType` (or `pricetype`) | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | node `priceType` | Unlike a generated strategy, a custom leg may use `SL`/`SL-M`, because it can carry its own trigger. |
| `price` | number | node `price` | Must be positive when the effective price type is `LIMIT`/`SL`. |
| `triggerPrice` | number | node `triggerPrice` | Must be positive when the effective price type is `SL`/`SL-M`. |
| `splitSize` | int | `0` | If >0, splits that leg into chunks. |

An **omitted** optional field is what tells the executor to inherit the node's
value, so write no key at all rather than an empty string. A leg naming neither
`offset` nor `strike` cannot execute and is refused.

The editor shows every inherited field as the value it currently resolves to -
its expiry, product and price type read as `25AUG26`, `NRML`, `MARKET` rather
than naming the inheritance - and writes nothing until the field is changed. So
a leg left alone keeps following the node, and adjusting the node still carries
to it.

Every leg is placed against the node's `underlying`; only the strike, expiry,
side and pricing vary per leg. A basket is capped at 10 legs in the editor.

Legs are placed in order and **a multi-leg basket fails leg by leg** - if leg
three is rejected, legs one and two are already filled. That is why a malformed
strike or expiry is refused at save time rather than at run time.

```json
{
  "id": "node_2",
  "type": "optionsMultiOrder",
  "position": { "x": 100, "y": 200 },
  "data": {
    "strategy": "custom",
    "underlying": "NIFTY",
    "expiryType": "current_week",
    "quantity": 1,
    "action": "SELL",
    "priceType": "MARKET",
    "product": "NRML",
    "legs": [
      {
        "strikeMode": "STRIKE",
        "strike": 24500,
        "expiry": "28OCT25",
        "optionType": "CE",
        "action": "SELL",
        "quantity": 1
      },
      {
        "strikeMode": "STRIKE",
        "strike": 24500,
        "expiry": "25NOV25",
        "optionType": "CE",
        "action": "BUY",
        "quantity": 1
      }
    ],
    "outputVariable": "calendar"
  }
}
```

That is a calendar spread: one strike, two expiries, opposite sides.

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

#### basketOrder - Basket Order

Place multiple orders in a single API call.

| Field | Type | Default | Notes |
|---|---|---|---|
| `basketName` | string | `"flow_basket"` | |
| `orders` | string \| `Order[]` | - | The editor writes multi-line `SYMBOL,EXCHANGE,ACTION,QTY` CSV. Imported arrays may set per-row `product`, `pricetype`, `price`, and `triggerprice`; common node values fill only omitted row fields. |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | by `exchange` | See **Product defaults**. |
| `priceType` | `"MARKET"` \| `"LIMIT"` \| `"SL"` \| `"SL-M"` | `"MARKET"` | Common to every CSV row. |
| `price` | number | `0` | Common row price. Must be positive for `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Common row trigger price. Must be positive for `SL`/`SL-M`. |
| `outputVariable` | string | - | `{{name.results}}` is the per-order result array. |

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
    "price": 0,
    "triggerPrice": 0,
    "outputVariable": "basket"
  }
}
```

#### splitOrder - Split Order

Splits a large order into chunks.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `action`, `priceType`, `product` | (as `placeOrder`) | | |
| `quantity` | int | `100` | Total to fill. |
| `splitSize` | int | `50` | Chunk size. Last chunk may be smaller. |
| `price` | number | `0` | Common chunk price. Must be positive for `LIMIT`/`SL`. |
| `triggerPrice` | number | `0` | Common chunk trigger price. Must be positive for `SL`/`SL-M`. |
| `outputVariable` | string | - | `{{name.results}}` is the per-chunk result. |

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
    "price": 0,
    "triggerPrice": 0,
    "outputVariable": "splitOut"
  }
}
```

#### modifyOrder - Modify Order

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | - | Required. Usually `{{prevOrder.orderid}}`. |
| `newQuantity` | int | - | Empty = keep existing. |
| `newPrice` | number | - | Empty = keep existing. |
| `newTriggerPrice` | number | - | Empty = keep existing. |
| `symbol`, `exchange`, `action`, `priceType`, `product` | as `placeOrder` | from the live order | **Omit these.** Any value present is treated as a deliberate override. |

The executor reads the order back from the order book and changes only the
fields you supply, so "empty = keep existing" is literal - an omitted quantity
keeps the order's quantity, not `1`.

Do not set `action` or `product` unless you mean to change them. Several brokers
carry these on a modify: an `action` of `BUY` on a live SELL order converts the
order, and a `product` of `MIS` on an NRML position makes it intraday and
subject to auto square-off. If the order cannot be read, the node fails rather
than sending a guessed value.

The executor cannot distinguish a value you meant from one a generator filled
in, so a `modifyOrder` node should carry **only** `orderId` plus whichever of
`newPrice` / `newQuantity` / `newTriggerPrice` you are changing.

```json
{
  "id": "node_3",
  "type": "modifyOrder",
  "position": { "x": 100, "y": 300 },
  "data": {
    "orderId": "{{buyOrder.orderid}}",
    "newPrice": 1455,
    "product": "CNC"
  }
}
```

#### cancelOrder - Cancel Order

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | - | Usually `{{prevOrder.orderid}}`. |

```json
{ "id": "node_3", "type": "cancelOrder", "position": { "x": 100, "y": 300 }, "data": { "orderId": "{{buyOrder.orderid}}" } }
```

#### cancelAllOrders - Cancel All Orders

Accepts `outputVariable` like every other action node; the broker's response is
stored under it.

Cancels every open order. No fields.

```json
{ "id": "node_3", "type": "cancelAllOrders", "position": { "x": 100, "y": 300 }, "data": {} }
```

#### closePositions - Close Positions

With no `symbol`, squares off every open position across all exchanges and
products. With a `symbol`, closes only that position.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | `""` | Blank closes everything. Set it to scope the close. |
| `exchange` | string | `NSE` | Only meaningful alongside `symbol`. |
| `product` | string | by `exchange` | Only meaningful alongside `symbol`. See **Product defaults**. |

`exchange` and `product` do not filter on their own - without a `symbol` this is
an unconditional square-off however they are set.

```json
{ "id": "node_3", "type": "closePositions", "position": { "x": 100, "y": 300 }, "data": {} }
```

```json
{
  "id": "node_4",
  "type": "closePositions",
  "position": { "x": 100, "y": 300 },
  "data": { "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS" }
}
```

---

### 7.3 Logic / condition nodes

These nodes set a `condition` boolean that the executor uses to route edges
via `sourceHandle` - see [§5](#5-condition-source-handles).

**A condition node that cannot evaluate fails the node; it does not answer
`false`.** An unrecognised `field`, `operator` or `condition`, or a threshold
that is not a number, returns `status: "error"` and takes *neither* branch.
This matters because `false` is a real answer that routes the graph down the
false path - an exit gate reading `false` would not fire. Previously these
cases silently produced `false`, so a typo looked like a condition that simply
did not hold.

Such a run is recorded as `failed` and the trigger response carries the error,
the same as any other failing node. A condition that evaluates cleanly to
`false` is **not** an error and the run still completes.

#### positionCheck - Position Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | required | |
| `exchange` | string | required | |
| `product` | `"MIS"` \| `"CNC"` \| `"NRML"` | by `exchange` | See **Product defaults**. |
| `condition` | `"exists"` \| `"not_exists"` \| `"quantity_above"` \| `"quantity_below"` \| `"pnl_above"` \| `"pnl_below"` | required | |
| `threshold` | number | `0` | Only used by the `quantity_*` and `pnl_*` modes. |

Result: `condition=True` if the rule matches the live position.

`symbol` is required and validated at import and activation. A blank symbol
reads back a zero-quantity position, which makes `not_exists` unconditionally
true, so the node fails instead of opening the gate it is supposed to guard.

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

#### fundCheck - Fund Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `minAvailable` | number | required | Triggers True when `availablecash >= minAvailable`. |

Required, and validated at import and activation. A node without it cannot guard
anything - the comparison would be `availablecash >= 0`, true on any balance -
so the node fails instead of letting the order behind it through.

```json
{ "id": "node_2", "type": "fundCheck", "position": { "x": 100, "y": 100 }, "data": { "minAvailable": 10000 } }
```

#### priceCondition - Price Check

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | - | |
| `exchange` | string | `"NSE"` | |
| `field` | `"ltp"` \| `"open"` \| `"high"` \| `"low"` \| `"prev_close"` \| `"change_percent"` | `"ltp"` | Validated. `change_percent` is computed from `(ltp - prev_close) / prev_close * 100`. |
| `operator` | `">"` \| `"<"` \| `"=="` \| `">="` \| `"<="` \| `"!="` | `">"` | Validated. |
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

#### varCondition - Compare Any Two Values

Generic counterpart to `priceCondition`. Compares two **interpolated** values
- an indicator output, a prior-period level, a workflow variable, or a
literal - instead of always re-fetching a live quote field.

| Field | Type | Default | Notes |
|---|---|---|---|
| `leftValue` | string | `""` | Supports `{{vars}}`. |
| `operator` | `">"` \| `"<"` \| `"=="` \| `">="` \| `"<="` \| `"!="` | `">"` | |
| `rightValue` | string | `"0"` | Supports `{{vars}}`. |

Uses `"true"`/`"false"` handles. **If either operand does not resolve to a
number the node errors and takes neither branch** - an unresolved variable
cannot silently route the else-path into a trade.

```json
{
  "id": "node_3",
  "type": "varCondition",
  "position": { "x": 100, "y": 200 },
  "data": { "leftValue": "{{rsi.latest.value}}", "operator": "<", "rightValue": "30" }
}
```

#### timeWindow - Time Window

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

#### timeCondition - Time Condition (uses `yes`/`no` handles)

| Field | Type | Default | Notes |
|---|---|---|---|
| `conditionType` | `"entry"` \| `"exit"` \| `"custom"` | - | UI-only categorization. |
| `operator` | `"=="` \| `">="` \| `"<="` \| `">"` \| `"<"` | `">="` | |
| `targetTime` | `"HH:MM"` or `"HH:MM:SS"` | `"09:30"` | Seconds are honoured when given. |
| `label` | string | - | Optional. |

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

#### andGate - AND Gate

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

#### orGate - OR Gate

True if any input is True. Same `inputCount` and `targetHandle` mechanics as
`andGate`.

```json
{ "id": "node_3", "type": "orGate", "position": { "x": 200, "y": 100 }, "data": { "inputCount": 2 } }
```

#### notGate - NOT Gate (uses `yes`/`no` handles)

Inverts the single incoming `condition`.

```json
{ "id": "node_3", "type": "notGate", "position": { "x": 200, "y": 100 }, "data": {} }
```

---

### 7.4 Data nodes

Each data node takes its inputs and stores its result under `outputVariable`
(if set). The shape returned by each maps onto the OpenAlgo REST API's
response - see `docs/prompt/services_documentation.md` for full response
schemas.

#### getQuote - Get Quote

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

#### getDepth - Market Depth

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | |

`{{depth.data.bids[0].price}}`, `{{depth.data.asks[0].quantity}}`, `{{depth.data.totalbuyqty}}`.

#### history - Historical OHLCV

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | | | |
| `interval` | `"1m"` \| `"5m"` \| `"15m"` \| `"1h"` \| `"1d"` (or any interval the broker supports - call `intervals` first) | `"5m"` | |
| `days` | int | `30` | When positive, derives a range from now back this many calendar days. |
| `startDate` | `"YYYY-MM-DD"` | - | Optional explicit range start; supply together with `endDate`. |
| `endDate` | `"YYYY-MM-DD"` | - | Optional explicit range end; supply together with `startDate`. |
| `outputVariable` | string | - | |

When both `startDate` and `endDate` are non-empty, that explicit range takes
precedence over `days`. Otherwise a positive `days` value derives both dates.

```json
{
  "id": "node_2",
  "type": "history",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "interval": "5m",
    "days": 30,
    "startDate": "2026-04-22",
    "endDate": "2026-04-29",
    "outputVariable": "ohlcv"
  }
}
```

#### indicator - Technical Indicator

Runs any of 116 `openalgo.ta` indicators over a symbol's history, or over
another indicator's output series.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | - | Not needed in nested mode. |
| `interval` | string | `"D"` | **Free text**, not an enum - any interval the broker supports. Use the `intervals` node to discover them. |
| `source` | `"api"` \| `"db"` | `"api"` | `"db"` reads Historify and resamples locally (2m/3m/25m/2h from stored 1m; W/M/Q/Y from D). |
| `indicatorName` | string | `"sma"` | Lowercase function name. |
| `params` | string | `"{}"` | JSON object of the indicator's own args, e.g. `"{\"period\": 14}"`. |
| `lookbackBars` | int | `100` | Capped at 200. |
| `tailBars` | int | `5` | Length of the returned `series` array. |
| `offsetBars` | int | `0` | Which bar `at_offset` reads. 0 = latest closed. |
| `sourceSeries` | string | - | Nest over another series, e.g. `{{rsi.series}}` or a raw `{{h.data}}`. |
| `sourceField` | string | `""` | Field to read per `sourceSeries` row. Blank = auto (`value`, `out0`, `close`). |
| `outputVariable` | string | - | |

Exposes `{{name.latest.*}}`, `{{name.previous.*}}`, `{{name.at_offset.*}}`,
`{{name.series}}`, `{{name.outputs}}`, `{{name.bars_used}}`. Single-output
indicators use `value`; multi-output use `out0`, `out1`, … (macd: line/signal/
histogram; supertrend: level/direction; bbands: upper/middle/lower).

`crossover`, `crossunder`, `cross`, `correlation`, `beta` are **not
available** - they need two independent series. Build a crossover from two
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

#### priorPeriodOhlc - Previous Period OHLC

Last fully-closed hour/day/week/month candle. Never returns a still-forming
candle; raises if history is too short.

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | - | |
| `period` | `"previous_hour"` \| `"previous_day"` \| `"previous_week"` \| `"previous_month"` | `"previous_day"` | |
| `source` | `"api"` \| `"db"` | `"api"` | |
| `outputVariable` | string | - | |

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

#### calendar - Calendar

Trading-day facts for a date, and the stateless answer to "has a new day,
week, month, quarter or year started". Flow keeps no state between runs, so a
workflow cannot remember the last run's date - it does not need to, because
"a new month started" is the same statement as "today is the first trading day
of this month", which the exchange calendar answers on its own.

| Field | Type | Default | Notes |
|---|---|---|---|
| `date` | `"YYYY-MM-DD"` | current trading session date | Blank uses the session date, which differs from the calendar date between midnight and the 03:00 IST rollover. |
| `outputVariable` | string | - | |

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

#### strategyPnl - Strategy P&L

Realized / unrealized / total P&L for **one strategy**, not the whole account.
The broker nets positions per `(symbol, exchange, product)` and carries no
strategy label, so this is the only way a workflow can exit on its own
performance while another strategy holds the same contract.

| Field | Type | Default | Notes |
|---|---|---|---|
| `strategy` | string | the workflow's own name | Matches the tag this workflow's order nodes apply. Leave blank in almost every case. |
| `outputVariable` | string | - | |

Exposes `{{name.realized}}`, `{{name.today_realized}}`, `{{name.unrealized}}`,
`{{name.total}}`, `{{name.today_total}}`, `{{name.open_quantity}}`,
`{{name.unpriced_legs}}` and a per-leg `{{name.legs[0].*}}` breakdown.

`legs` lists **open legs first**, so whenever `open_quantity` is non-zero,
`{{name.legs[0]}}` is an open leg. The book keeps a strategy's flat legs
indefinitely and resets their `average_price` to 0 when they close, so without
that ordering a positional read would eventually land on a stale closed leg and
a percentage calculation would divide by zero. Guard on `open_quantity` before
reading a leg.

The book is fed from orders placed **through OpenAlgo carrying a strategy
tag**; a position opened by hand in the broker terminal is invisible to it.
`unpriced_legs` counts open legs with no live price, which are excluded from
`unrealized` - a non-zero value means `total` is understated. If the position
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

#### barOffset - OHLCV N Bars Back

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange` | string | - | |
| `interval` | string | `"D"` | Free text. |
| `source` | `"api"` \| `"db"` | `"api"` | |
| `offsetBars` | int | `0` | 0 = most recent **closed** bar; today's forming candle is excluded. Counts bars, not calendar days. |
| `outputVariable` | string | - | |

Exposes `{{name.open/high/low/close/volume/timestamp}}`.

```json
{
  "id": "node_2",
  "type": "barOffset",
  "position": { "x": 100, "y": 100 },
  "data": { "symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "D", "source": "api", "offsetBars": 5, "outputVariable": "bar5" }
}
```

#### openPosition - Open Position For Symbol

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `product`, `outputVariable` | | | |

`{{position.quantity}}` and `{{position.pnl}}` are exposed.

#### getOrderStatus - Order Status

| Field | Type | Default | Notes |
|---|---|---|---|
| `orderId` | string | - | Usually `{{prevOrder.orderid}}`. |
| `outputVariable` | string | - | |

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

#### symbol - Symbol Info

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Returns `{ data: { lotsize, tick_size, expiry, ... } }`. |

#### optionSymbol - Resolve Option Symbol

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | string | `"NIFTY"` | |
| `exchange` | `"NSE_INDEX"` \| `"BSE_INDEX"` | `"NSE_INDEX"` | |
| `expiryDate` | string | - | Format `"30DEC25"`. Can be `{{expiries.data[0]}}` after a normalization step. |
| `offset` | `"ATM"` \| `"ITM1"`-`"ITM50"` \| `"OTM1"`-`"OTM50"` | `"ATM"` | |
| `optionType` | `"CE"` \| `"PE"` | `"CE"` | |
| `outputVariable` | string | - | |

#### expiry - Get Expiry Dates

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | string | `"NIFTY"` | |
| `exchange` | `"NFO"` \| `"BFO"` \| `"MCX"` \| `"CDS"` | `"NFO"` | |
| `instrumenttype` | `"options"` \| `"futures"` | `"options"` | **Lowercase.** Different calendars per type. |
| `outputVariable` | string | - | List sorted ascending. `{{expiries.data[0]}}` = nearest. |

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

#### intervals - Available Time Intervals

| Field | Type | Default | Notes |
|---|---|---|---|
| `outputVariable` | string | - | |

```json
{ "id": "node_2", "type": "intervals", "position": { "x": 100, "y": 100 }, "data": { "outputVariable": "ivs" } }
```

#### multiQuotes - Quotes For Many Symbols

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbols` | string | - | Comma-separated, e.g. `"RELIANCE,INFY,TCS"`. |
| `exchange` | string | `"NSE"` | Applied to each symbol. |
| `outputVariable` | string | - | `{{quotes.results[0].data.ltp}}`. |

#### optionChain - Option Chain

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying` | string | `"NIFTY"` | |
| `exchange` | `"NSE_INDEX"` \| `"BSE_INDEX"` | `"NSE_INDEX"` | |
| `expiryDate` | string | - | Format `"30DEC25"`. |
| `strikeCount` | int | `10` | Number of strikes above and below ATM. |
| `outputVariable` | string | - | `{{chain.atm_strike}}`, `{{chain.chain[0].ce.ltp}}`. |

#### syntheticFuture - Synthetic Future Price

| Field | Type | Default | Notes |
|---|---|---|---|
| `underlying`, `exchange`, `expiryDate`, `outputVariable` | (as `optionChain`) | | `{{synthFuture.synthetic_future_price}}`. |

#### holidays - Market Holidays

| Field | Type | Default | Notes |
|---|---|---|---|
| `year` | int | current year | Optional year whose holiday list is requested. |
| `outputVariable` | string | - | |

#### timings - Market Timings

| Field | Type | Default | Notes |
|---|---|---|---|
| `date` | `"YYYY-MM-DD"` | today | Optional date whose market timings are requested. |
| `outputVariable` | string | - | |

#### margin - Margin Calculator

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `quantity`, `price`, `product`, `action`, `priceType` | | | (Same shape as `placeOrder`.) |
| `outputVariable` | string | - | |

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

#### log - Log Message

| Field | Type | Default | Notes |
|---|---|---|---|
| `message` | string | - | Supports `{{vars}}`. |
| `level` | `"info"` \| `"warn"` \| `"error"` | `"info"` | |

```json
{ "id": "node_3", "type": "log", "position": { "x": 100, "y": 300 }, "data": { "message": "First expiry: {{expiries.data[0]}}", "level": "info" } }
```

#### telegramAlert - Telegram Alert

Sends a Telegram message via the per-user Telegram bot configured in OpenAlgo
settings. Delivery is owned by the workflow API key: the message goes to the
Telegram account paired for that API-key owner. A workflow cannot supply a
recipient override to target another OpenAlgo user.

| Field | Type | Default | Notes |
|---|---|---|---|
| `message` | string | - | Supports `{{vars}}`. |

```json
{
  "id": "node_3",
  "type": "telegramAlert",
  "position": { "x": 100, "y": 300 },
  "data": {
    "message": "Order placed: {{buyOrder.orderid}} for {{buyOrder.symbol}}"
  }
}
```

#### whatsappAlert - WhatsApp Alert

Sends a WhatsApp message via the paired bot device. Requires pairing from the
`/whatsapp` page first.

| Field | Type | Default | Notes |
|---|---|---|---|
| `to` | string | `""` | Phone digits, e.g. `919876543210`. Blank sends to the paired device itself. |
| `message` | string | - | Supports `{{vars}}`. |

```json
{
  "id": "node_3",
  "type": "whatsappAlert",
  "position": { "x": 100, "y": 300 },
  "data": { "to": "", "message": "Order placed: {{ord.orderid}}" }
}
```

#### variable - Set / Update Variable

All eleven editor operations are implemented. Each successful operation stores
its result under `variableName`; a missing source, invalid conversion, invalid
JSON, or division by zero returns an error and leaves the target unchanged.

| Operation | Behaviour |
|---|---|
| `"set"` | Stores `value` under `variableName`. JSON-shaped strings (starting with `{` or `[`) are auto-parsed via `json.loads`, so you can carry structured data. |
| `"get"` | Copies the raw value from `sourceVariable`. Optional `jsonPath` traverses dotted object keys and bracketed list indexes. |
| `"add"` | `current + value` (numeric coercion). Initialises to 0 if unset. |
| `"subtract"` | `current - value` (numeric coercion). Initialises to 0 if unset. |
| `"multiply"` | `current * value` (numeric coercion). Initialises to 0 if unset. |
| `"divide"` | `current / value` (numeric coercion). Division by zero is an error. |
| `"increment"` | `current + 1`. Initialises to 0 if unset. |
| `"decrement"` | `current - 1`. Initialises to 0 if unset. |
| `"parse_json"` | Parses the interpolated, non-empty `value` as JSON and stores the raw JSON value. Invalid JSON is an error. |
| `"stringify"` | JSON-serializes the raw `sourceVariable` and stores the resulting string. Missing or non-serializable sources are errors. |
| `"append"` | Appends `value` to the target as text; an unset target starts as an empty string. |

| Field | Type | Default | Notes |
|---|---|---|---|
| `variableName` | string | - | The name to set in workflow context. |
| `operation` | `"set"` \| `"get"` \| `"add"` \| `"subtract"` \| `"multiply"` \| `"divide"` \| `"increment"` \| `"decrement"` \| `"parse_json"` \| `"stringify"` \| `"append"` | `"set"` | Must be one of these eleven values. |
| `value` | any | - | Strings accept `{{vars}}`. Required for `add`, `subtract`, `multiply`, and `divide`; `parse_json` requires a non-empty value. Optional for `set` and `append`. |
| `sourceVariable` | string | - | Required for `get` and `stringify`; names a raw workflow-context variable. |
| `jsonPath` | string | - | Optional for `get`; dotted keys and bracketed indexes such as `data.items[0].price`. |

```json
{ "id": "node_3", "type": "variable", "position": { "x": 100, "y": 300 }, "data": { "variableName": "qty", "operation": "set", "value": "10" } }
```

For richer arithmetic, use `mathExpression`:

```json
{ "id": "node_3", "type": "mathExpression", "position": { "x": 100, "y": 300 }, "data": { "expression": "{{quote.data.ltp}} * 0.99", "outputVariable": "stopPrice" } }
```

#### mathExpression - Evaluate Math Expression

| Field | Type | Default | Notes |
|---|---|---|---|
| `expression` | string | - | Supports `+`, `-`, `*`, `/`, `%`, `**`, parentheses, and the sole allowed function `floor(expression)`. Variables via `{{name}}`. Other calls, attribute access, keyword arguments, and wrong argument counts are rejected. |
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

#### httpRequest - HTTP Request

| Field | Type | Default | Notes |
|---|---|---|---|
| `method` | `"GET"` \| `"POST"` \| `"PUT"` \| `"DELETE"` \| `"PATCH"` | `"GET"` | |
| `url` | string | - | Supports `{{vars}}`. |
| `headers` | JSON-string | `""` | e.g. `"{\"Authorization\": \"Bearer {{token}}\"}"`. A JSON object is also accepted. |
| `body` | string | - | JSON string, only used for POST/PUT/PATCH. Supports `{{vars}}`. |
| `timeout` | int | `30000` | Milliseconds; must be between 1000 and 60000. |
| `outputVariable` | string | `"response"` | `{{response.data}}`, `{{response.statusCode}}`. |

Only `http` and `https` are allowed, and the destination must resolve to a
public address. Loopback, private, link-local and reserved ranges are rejected,
so a workflow cannot be pointed at this server, at a host on the LAN, or at
cloud metadata on `169.254.169.254`. This matters because `url` interpolates
from workflow variables, and a webhook trigger puts its caller's JSON body into
that context. Redirects are not followed. Logged URLs have their query string
redacted, so a token in a query parameter is not written to the execution log.

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
    "timeout": 30000,
    "outputVariable": "notifyResp"
  }
}
```

#### delay - Delay

| Field | Type | Default | Notes |
|---|---|---|---|
| `delayValue` | int | `1` | |
| `delayUnit` | `"seconds"` \| `"minutes"` \| `"hours"` | `"seconds"` | |

Capped at 300 seconds. The delay blocks the workflow's lock and, for a webhook
trigger, the request that fired it, so longer waits belong in a schedule or a
`waitUntil` node. A longer value waits the maximum and logs a warning.

```json
{ "id": "node_3", "type": "delay", "position": { "x": 100, "y": 300 }, "data": { "delayValue": 30, "delayUnit": "seconds" } }
```

#### waitUntil - Wait Until Time

| Field | Type | Default | Notes |
|---|---|---|---|
| `targetTime` | `"HH:MM"` or `"HH:MM:SS"` | `"09:30"` | Seconds are honoured. If already past, the node returns immediately. |
| `label` | string | - | UI-only. |

```json
{ "id": "node_3", "type": "waitUntil", "position": { "x": 100, "y": 300 }, "data": { "targetTime": "15:25", "label": "Square-off entry" } }
```

#### group - Group / Visual Container

UI-only grouping. Has no executor behavior - the group's children execute on
their own edges. The Group node itself is a no-op when traversed.

| Field | Type | Default | Notes |
|---|---|---|---|
| `label` | string | - | |
| `color` | `"default"` \| `"blue"` \| `"green"` \| `"red"` \| `"purple"` \| `"orange"` | `"default"` | |

---

### 7.6 Stream nodes

These maintain a WebSocket subscription and either pass the latest tick to
their `outputVariable` (one-shot, used inside scheduled flows) or keep the
subscription alive across runs of the same workflow.

If WebSocket is unavailable for any reason, every stream node falls back to a
single REST call. Behaviour is identical from the workflow's point of view.

#### subscribeLtp - Subscribe LTP

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | `outputVariable` defaults to `"ltp"`. | The variable receives the float LTP directly. |

```json
{ "id": "node_2", "type": "subscribeLtp", "position": { "x": 100, "y": 100 }, "data": { "symbol": "RELIANCE", "exchange": "NSE", "outputVariable": "rltp" } }
```

#### subscribeQuote - Subscribe Quote

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Variable receives `{ ltp, open, high, low, close, volume, ... }`. |

#### subscribeDepth - Subscribe Depth

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol`, `exchange`, `outputVariable` | | | Variable receives `{ bids: [...], asks: [...], totalbuyqty, totalsellqty, ltp }`. |

#### unsubscribe - Unsubscribe

| Field | Type | Default | Notes |
|---|---|---|---|
| `streamType` | `"ltp"` \| `"quote"` \| `"depth"` \| `"all"` | `"all"` | |
| `symbol` | string | - | Empty = all symbols for this user. |
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

`mode` is `"analyze"` in Analyzer mode and `"live"` otherwise - useful for a
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
      "data": { "message": "Bought ATM CE: {{ceLong.orderid}} (expiry {{expiries.data[0]}})" }
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
    { "id": "node_3", "type": "telegramAlert", "position": { "x": 100, "y": 340 }, "data": { "message": "Realized: Rs {{funds.data.m2mrealized}} | Unrealized: Rs {{funds.data.m2munrealized}} | Cash: Rs {{funds.data.availablecash}} | At {{time}} IST" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2" },
    { "id": "e2", "source": "node_2", "target": "node_3" }
  ]
}
```

Note `m2mrealized` and `m2munrealized` are returned as **strings** (e.g.
`"1234.50"`). They interpolate into the Telegram message correctly. To compare
their computed result, normalize it with `mathExpression` and feed that output
to a `varCondition`.

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
    { "id": "node_4", "type": "varCondition",   "position": { "x": 100, "y": 420 }, "data": { "leftValue": "{{totalPnL}}", "operator": "<", "rightValue": "-2000" } },
    { "id": "node_5", "type": "closePositions","position": { "x":   0, "y": 540 }, "data": {} },
    { "id": "node_6", "type": "telegramAlert",  "position": { "x": 240, "y": 540 }, "data": { "message": "PnL stop-loss tripped at {{totalPnL}}, all positions squared off" } }
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

The `varCondition` compares the computed `{{totalPnL}}` directly; use
`priceCondition` only when the node itself should fetch and compare an
instrument quote field such as LTP or open.

### 8.6 Iron condor with custom legs

`optionsMultiOrder` accepts a `legs` array when `strategy="custom"` - useful
for structures the preset enums do not cover, such as ratios and butterflies.
Each leg is `{ offset, optionType, action, quantity }` plus optional pricing
fields. Every leg uses the one expiry resolved from the node's `expiryType`.

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
      "timeout": 10000,
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
    { "id": "node_5", "type": "telegramAlert",  "position": { "x": 100, "y": 540 }, "data": { "message": "[OpenAlgo] Daily square-off done at {{time}} IST on {{date}}" } }
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
    { "id": "node_4", "type": "mathExpression", "position": { "x": 100, "y": 420 }, "data": { "expression": "floor((0.05 * {{f.data.availablecash}}) / {{q.data.ltp}})", "outputVariable": "sizedQty" } },
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

> `floor(expression)` is the only supported function call and returns an
> integer-valued number. Other function names, attributes, keyword arguments, or calls with
> anything other than one positional expression are rejected.

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

Place an order only when (a) it is between 09:30-14:30 **and** (b) the symbol's
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

`crossover` is **not** available as an `indicator` node - it needs two
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
    { "id": "buy", "type": "optionsOrder", "position": {"x":120,"y":500}, "data": { "underlying": "NIFTY", "expiryType": "current_week", "offset": "ATM", "optionType": "CE", "action": "BUY", "quantity": 1, "priceType": "MARKET", "product": "NRML", "outputVariable": "ord" } }
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
distinct fetches - the request cache only collapses *identical* requests.

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

`positionCheck` with `not_exists` is what enforces one trade per breakout -
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
| `MCX` | Commodity, futures and options. Also the underlying exchange for a commodity `optionsOrder`/`optionsMultiOrder` - MCX has no separate F&O segment. |
| `NCDEX` | Commodity |
| `NCO` | NSE Commodities, futures and options (Zerodha only) |
| `NSE_INDEX` | NSE Indices (for `optionsOrder`/`optionChain`/`optionSymbol`/`syntheticFuture`) |
| `BSE_INDEX` | BSE Indices (same usage as above) |
| `MCX_INDEX` | MCX sectoral index feeds - MCXBULLDEX, MCXMETLDEX, MCXAGRI (quote only). The tradable MCXBULLDEX futures and options live on `MCX`, not here. |
| `GLOBAL_INDEX` | Global indices - US30, JAPAN225, HANGSENG, GIFTNIFTY (quote only, Zerodha) |
| `CRYPTO` | Crypto derivatives (Delta Exchange only) |

The index and crypto codes are quote-only or broker-specific; an order node
using one is accepted by the validator but will be refused by a broker that
does not serve that segment. See `docs/prompt/order-constants.md`, which is the
source this list is checked against.

---

## 10. Symbol format

OpenAlgo standardizes broker-specific symbols to the following format. See
`docs/prompt/symbol-format.md` for the complete spec; the short form:

- **Equity:** `INFY`, `RELIANCE`, `TATAMOTORS`
- **Futures:** `<base><DDMMMYY>FUT` - `BANKNIFTY24APR24FUT`, `CRUDEOILM20MAY24FUT`
- **Options:** `<base><DDMMMYY><strike><CE|PE>` - `NIFTY28MAR2420800CE`, `VEDL25APR24292.5CE`
- **Indices:** `NIFTY`, `SENSEX`, `BANKNIFTY` etc. on `NSE_INDEX` / `BSE_INDEX`

---

## 11. Order constants

For convenience in one place:

- **Action:** `BUY`, `SELL`
- **Product:** `CNC` (cash & carry / delivery), `NRML` (futures & options carry), `MIS` (intraday). Omit it and the node's `exchange` decides - see **Product defaults** in 7.2.
- **Price type:** `MARKET`, `LIMIT`, `SL` (stop-loss limit), `SL-M` (stop-loss market)
- **Option type:** `CE`, `PE`
- **Strike offset:** `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50`
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
funds (outputVariable=f)
  → mathExpression (expression={{f.data.m2mrealized}} + {{f.data.m2munrealized}}, outputVariable=totalPnl)
  → varCondition (leftValue={{totalPnl}}, operator="<", rightValue=-5000)
      └── true  → closePositions
```

---

## 13. Pitfalls

- **Missing top-level `name` on import.** The Flow Editor's import dialog
  rejects any JSON missing a `name` field with *"Invalid workflow format.
  Must have name, nodes, and edges."* The executor itself never reads it -
  only the importer does. See §1.
- **`JSON.parse` failures during paste.** *"Invalid JSON format. Please
  check the workflow data."* always means the text isn't valid JSON. Common
  causes: smart-quote conversion (`"` → `"` `"`) by Slack/Discord/word
  processors, BOM/zero-width characters from doc editors, real newlines
  injected inside a string value (use `\n` if you need a newline, never a
  literal line break inside `"..."`). The fix-of-last-resort is to save the
  JSON to a `.json` file and use the **file upload** button in the import
  dialog - that path goes through `FileReader` and bypasses clipboard
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
  month). The `expiry` node returns `"30-DEC-25"` (with hyphens) - pass that
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
  refuses to evaluate so a typo cannot route a trade. Order nodes refuse for the
  same reason -- see [Unresolved references on order nodes](#unresolved-references-on-order-nodes).
- **Execution history is pruned.** Each run stores its full node trace, so the
  newest `FLOW_EXECUTION_RETENTION_COUNT` runs per workflow (default 500) and
  anything newer than `FLOW_EXECUTION_RETENTION_DAYS` (default 30) are kept;
  older rows are deleted as new ones are written. Set either to `0` to disable
  that limit. Export anything you need to keep.
- **A failed node stops its branch and fails the run.** When a node returns
  an error - a broker rejection, an unreachable URL, a guard that cannot be
  evaluated - nothing downstream of it executes, the run is recorded as
  `failed`, and the trigger response carries the error. Do not rely on a later
  node running "anyway"; put independent work on its own branch from the
  trigger.
- **One-shot triggers deactivate the workflow when they fire.** A `priceAlert`
  or `orderUpdateTrigger` with `trigger: "once"` clears `is_active` after its
  run, so it is not re-armed by a later restart. Use `trigger: "every_time"`
  for a standing watch. The trigger is spent only by a run that actually
  reached the graph: if the workflow was already running, or the run could not
  be queued, the trigger stays armed for the next event rather than being
  silently consumed. A run the broker rejected still counts as spent - it ran.
- **Editing a trigger on an active workflow re-arms it during the save.** The
  scheduler and monitors snapshot the trigger node, so a save that changes it
  tears the old registration down and installs the new one. If that fails the
  workflow is **deactivated** rather than left running a stale registration,
  and the response carries `needs_reactivate: true`. Node bodies outside the
  trigger apply immediately either way, because the graph is re-read on every
  run.
- **Lot size handling differs per node.** `optionsOrder` and
  `optionsMultiOrder` accept `quantity` **in lots** (multiplied by lot size
  internally). `placeOrder` / `smartOrder` / `splitOrder` / `basketOrder`
  accept `quantity` **in shares**. Check this when generating from a single
  source. The lot size is read from the master contract, never guessed: an
  underlying with no usable lot size fails the node rather than sizing an order
  on an assumption. Most MCX option contracts carry a lot size of 1.

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
- Required fields, checked at import, save and activation:
  `services/flow_workflow_validator.py` (`REQUIRED_NODE_FIELDS`,
  `CONDITIONAL_REQUIRED_FIELDS`, `EITHER_REQUIRED_FIELDS`).
- Trigger registration and its lifecycle: `blueprints/flow.py` (activate,
  deactivate), `services/flow_scheduler_service.py`,
  `services/flow_price_monitor_service.py`,
  `services/flow_order_update_monitor_service.py`.
- HTTP destination rules: `NodeExecutor._check_http_destination` in
  `services/flow_executor_service.py`.
- Unresolved-reference checks on order nodes: `ORDER_NODE_TYPES`,
  `ORDER_CRITICAL_FIELDS` and `NodeExecutor.unresolved_order_fields` in
  `services/flow_executor_service.py`.
- Execution-history retention: `prune_workflow_executions` in
  `database/flow_db.py`.

If this doc and the code disagree, the code wins. Open a PR.
