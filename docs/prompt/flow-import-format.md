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

## 1. Workflow shape

A workflow is a JSON object with three top-level keys:

```json
{
  "nodes": [ /* array of nodes */ ],
  "edges": [ /* array of edges */ ],
  "viewport": { "x": 0, "y": 0, "zoom": 1 }
}
```

`viewport` is optional and is used only for restoring the canvas position in
the UI; importers may omit it.

### Persisted vs minimal

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
| `timeWindow` | `"true"` / `"false"` |
| `timeCondition` | `"yes"` / `"no"` |
| `notGate` | `"yes"` / `"no"` |

The executor accepts both vocabularies as synonyms — `{yes, true}` is the
truthy branch, `{no, false}` is the falsy branch — but it is good practice
to use the vocabulary native to each node so saved workflows match the UI.

Edges that source from a condition node and **do not** specify a `sourceHandle`
are followed unconditionally on every run (use this for "fire-and-forget" log
or telegram nodes that want to see every result).

`andGate` / `orGate` source handles are not bool branches — they emit a single
`condition` value to whatever connects to them downstream. Their **incoming**
edges do use `targetHandle` to pin a specific input slot:
`targetHandle: "input-0"`, `"input-1"`, ... up to `inputCount - 1`.

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
of: `start`, `priceAlert`, `webhookTrigger`. Every other path of execution
flows from there.

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
| `startDate` | `"YYYY-MM-DD"` | — | |
| `endDate` | `"YYYY-MM-DD"` | — | |
| `outputVariable` | string | — | |

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
`{{positions.data[0].quantity}}`, `{{holdings.data[0].symbol}}`,
`{{funds.data.availablecash}}`.

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

#### variable — Set / Update Variable

| Field | Type | Default | Notes |
|---|---|---|---|
| `variableName` | string | — | The name to set in workflow context. |
| `operation` | `"set"` \| `"add"` \| `"subtract"` \| `"multiply"` \| `"divide"` \| `"increment"` \| `"decrement"` \| `"append"` \| `"parse_json"` \| `"stringify"` \| `"get"` | `"set"` | |
| `value` | any | — | Used by `set`/`add`/`subtract`/`multiply`/`divide`/`append`/`parse_json`. Strings accept `{{vars}}`. JSON strings (starting with `{` or `[`) are auto-parsed under `set`. |
| `sourceVariable` | string | — | Used by `get`/`stringify`. |
| `jsonPath` | string | — | Used by `get`. e.g. `"data.ltp"`. |

```json
{ "id": "node_3", "type": "variable", "position": { "x": 100, "y": 300 }, "data": { "variableName": "qty", "operation": "set", "value": "10" } }
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

## 8. End-to-end examples

### 8.1 Simple scheduled workflow

Run every weekday at 09:20 IST: place a 10-share BUY of RELIANCE if a
position does not already exist.

```json
{
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

### 8.3 Compound condition (AND gate)

Place an order only when (a) it is between 09:30–14:30 **and** (b) the symbol's
LTP is above 1500.

```json
{
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
