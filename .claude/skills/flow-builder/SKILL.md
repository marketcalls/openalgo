---
name: flow-builder
description: Build, edit or debug an OpenAlgo Flow workflow - the no-code node graph at /flow. Use when asked to create a workflow, wire a webhook or TradingView alert to an order, add a node, port a strategy into Flow, or work out why a workflow imported but did nothing. Produces a workflow JSON that is validated against the real importer before it is handed over.
---

# Building an OpenAlgo Flow workflow

A workflow is a JSON graph: `nodes` (what happens) plus `edges` (in what order).
It is imported at `/flow`, or written straight into `flow_workflows`.

## The one rule

**Validate before you hand anything over.**

```bash
uv run python .claude/skills/flow-builder/validate.py <workflow.json>
```

It calls the importer's own `validate_workflow`, so it cannot disagree with what
the server accepts, and then adds the checks the importer deliberately skips.
Those matter more than they sound: **Flow ignores a `data` key nothing reads.**
Write `strikeOffset` when the field is `offset` and the workflow imports
cleanly, runs successfully, and silently uses ATM. Nothing in the run says so.

Exit 0 means it imports. Warnings mean it imports and then misbehaves - treat
them as errors unless you know why.

## Workflow

1. **Read `reference/nodes.md`.** All 61 node types, their required fields, and
   every `data` key each one actually reads. Generated from the validator and
   the executor, so it cannot drift.
2. **Pick the trigger.** Exactly one, and it is the execution root:
   `start` (schedule), `webhookTrigger` (external POST), `priceAlert`,
   `orderUpdateTrigger`. A second trigger is rejected at import.
3. **Wire the graph.** Every edge names `source` and `target` node ids. An edge
   leaving a condition node must also set `sourceHandle` to pick the TRUE or
   FALSE branch.
4. **Validate. Fix. Re-validate.**
5. **Import** at `/flow`, or `POST /flow/api/workflows/import`.

For the full field-by-field contract, `docs/prompt/flow-import-format.md` is the
long form. This skill is the short path plus the check.

## The shape

```json
{
  "name": "Webhook long entry",
  "nodes": [
    { "id": "node_1", "type": "webhookTrigger",
      "position": { "x": 0, "y": 0 }, "data": { "label": "TV alert" } },
    { "id": "node_2", "type": "placeOrder",
      "position": { "x": 0, "y": 120 },
      "data": { "symbol": "{{webhook.symbol}}", "exchange": "NSE",
                "action": "{{webhook.action}}", "quantity": "{{webhook.quantity}}",
                "product": "MIS", "priceType": "MARKET",
                "outputVariable": "orderResult" } }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2", "type": "default" }
  ]
}
```

## Values from outside: `{{webhook.*}}`

The webhook body is exposed as `{{webhook.<key>}}`. Nested paths and array
indexing both work: `{{webhook.legs[0].qty}}`.

**Every field on an order node takes a reference** - not only `symbol`. The
editor shows a dropdown for `exchange` and a BUY/SELL pair for `action`, but the
stored value is a string either way, so `"exchange": "{{webhook.exchange}}"` is
valid. The same is true of `quantity`, `product`, `priceType`, `price`,
`triggerPrice`, `offset`, `optionType` and `expiryType`.

A field holding **exactly one whole token** keeps its type, so
`"quantity": "{{webhook.quantity}}"` against `{"quantity": 10}` arrives as the
number `10`.

Enumerated fields are case-insensitive, which matters because TradingView sends
whatever the chart carries: `"action": "buy"` is accepted. `symbol` is
upper-cased on order nodes for the same reason.

**An unresolved reference on an order field fails the node.** It does not fall
back to a default. That is deliberate: a webhook omitting `quantity` used to
place a real order for 1 unit. If a value is genuinely optional, use a literal or
branch on a condition node first.

## Traps

**A key nothing reads is ignored, not rejected.** The single most common way a
workflow "works" and does the wrong thing. `validate.py` catches it.

**`source` is not the price field.** On `indicator`, `barOffset` and
`priorPeriodOhlc`, `source` selects the data source (`api` or `db`). The price
field is `sourceField`. Passing `close` to `source` fails with a history error
naming neither.

**Options expiry has two forms.** `expiryType` takes a relative type
(`current_week`, `next_week`, `current_month`, `next_month`) **or** a `DDMMMYY`
date such as `28OCT25`, used as given. `expiryDate` is the same explicit date
under its own key and wins when both are set.

**The `webhookTrigger` carries no instrument.** It has only a `label`. Symbol and
exchange come from the request.

**A failed read is not a `False`.** `priceCondition`, `positionCheck` and
`fundCheck` error rather than answering when the broker call fails, so they take
neither branch. Do not write a graph that relies on the FALSE branch firing when
data is unavailable - it will not.

**A gate waits for `inputCount`, not for the wires.** Configure three inputs and
wire two and the gate errors rather than evaluating on part of the condition.

**`timeWindow` may cross midnight.** `22:00` to `02:00` spans midnight rather
than being empty, so an overnight MCX or crypto guard works as written.

**`unsubscribe` needs a symbol** unless `streamType` is `all`, because the
underlying call clears every subscription on the instance - including the ones
the Sandbox engine uses to trigger pending SL and LIMIT orders.

**Subscriptions end with the workflow.** Deactivating or deleting it releases
everything its subscribe nodes opened, so no cleanup node is needed for that.

**A condition evaluates once per run**, like a gate. A diamond that reaches one
condition by two paths fires its branch once, not twice.

**`waitUntil` is capped at 30 minutes.** It sleeps inside the triggering request,
so anything longer belongs on a `start` schedule trigger.

**A schedule is clock-aligned and market-hours gated.** `interval` fires on the
clock (HH:MM:02, not activation time + 60s), and the `start` node carries
`marketHoursOnly` (the editor writes `true`, but an imported JSON that omits
the key defaults to **false** and runs around the clock, so set it explicitly),
`marketHoursStart` (09:15), `marketHoursEnd`
(15:15) and `marketHoursExchange` (NSE). The window narrows the exchange's
session; it never reopens a holiday.

**A 1-minute strategy needs a shorter history cache.** The indicator node
reuses a fetch for `FLOW_HISTORY_CACHE_TTL` seconds, 30 by default, which is
half a one-minute candle. Set it to 2-3 for 1m work.

**Read a closed bar, not a forming one.** `{{ind.latest.*}}` is the bar still
being built and repaints within the period. `{{ind.previous.*}}` is the last
closed bar. With `offsetBars: 2`, `{{ind.at_offset.*}}` is the bar before that,
so one node gives both bars a flip test needs.

**A tuple indicator returns `out0`, `out1`, ...** not `value`. Supertrend gives
`out0` (the line) and `out1` (direction), and its direction is inverted from the
usual convention: **-1 is the uptrend**, +1 the downtrend. Verify an
indicator's encoding before trading it.

**Conditions need `sourceHandle`.** An edge leaving `priceCondition`,
`timeCondition`, `timeWindow`, `positionCheck`, `fundCheck` or `varCondition`
must say which branch it is.

**Gates wait for every input.** `andGate` and `orGate` fire once, after all wired
inputs have been evaluated.

## Testing a workflow without the editor

Trigger it over HTTP, exactly as an alert would, and read the run back:

```bash
curl -X POST http://127.0.0.1:5000/flow/webhook/<token> \
  -H "Content-Type: application/json" \
  -d '{"secret":"<secret>","symbol":"RELIANCE","action":"BUY","quantity":1}'
```

```sql
SELECT id, status, logs FROM flow_workflow_executions ORDER BY id DESC LIMIT 1;
```

The log lines are the evidence: they name the values each node actually used, so
a field that silently kept its default shows up as a mismatch against the
payload you sent. **Check `settings.analyze_mode` first** - `1` routes orders to
the Sandbox engine, `0` sends them to a live broker.

## Files

| Path | |
|---|---|
| `validate.py` | the gate; wraps the importer's own validator |
| `reference/nodes.md` | all 61 node types, generated |
| `generate_reference.py` | regenerate it after a node's fields change |
| `coverage.py` | fails if a node type is undocumented |
| `docs/prompt/flow-import-format.md` | the long-form contract |
