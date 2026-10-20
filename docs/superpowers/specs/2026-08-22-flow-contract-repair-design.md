# Flow Node Contract Repair Design

## Purpose

Flow currently has several places where the editor, import validator, executor,
and prompt documentation disagree. Some valid workflows are rejected during
activation, some incomplete workflows activate and fail later, and some fields
or operations report success without affecting execution. This repair makes the
activation contract match the behavior users configure and the behavior the
executor can safely deliver.

The repair covers every mismatch confirmed in the August 22, 2026 Flow audit.
It preserves existing workflow JSON where that JSON has a well-defined meaning,
and it rejects incomplete or unsafe configurations before a workflow becomes
active.

## Goals

1. Allow valid nested Indicator and SmartOrder target-position workflows.
2. Reject incomplete trigger, expiry, margin, multi-leg, and priced-order
   configurations during strict activation validation.
3. Carry every configured order price and trigger price through to the broker
   service.
4. Implement every Variable operation exposed by the editor.
5. Support the documented `floor()` math operation without allowing arbitrary
   Python calls.
6. Remove the misleading Telegram recipient field while preserving account
   isolation.
7. Make the Flow import prompt and its examples describe the implemented
   contract.
8. Keep non-strict draft saves permissive; completeness checks continue to run
   only for import/activation with `strict=True`.

## Non-goals

- No new Flow node types are introduced.
- No broker API or order-constant vocabulary is changed.
- Telegram alerts cannot target another OpenAlgo user. The workflow API key
  remains the sole account identity.
- Options multi-order continues to use one common expiry. Per-leg expiries are
  not supported by the service and will no longer be advertised as diagonal or
  calendar-spread support.
- Basket rows configured in the editor continue to share product, price type,
  price, and trigger price. Different per-leg values remain available only to
  imported list-form basket payloads.

## Architecture

The existing layers remain in place:

1. `ConfigPanel.tsx` and `DEFAULT_NODE_DATA` define the editor contract.
2. `flow_workflow_validator.py` validates static values on save and completeness
   on import/activation.
3. `flow_executor_service.py` resolves variables and executes the node.
4. `flow_openalgo_client.py` translates executor arguments to service payloads.
5. `flow-import-format.md` documents the same JSON contract for generated and
   hand-authored imports.

The validator becomes the fail-fast boundary for every rule that can be decided
from stored JSON. Runtime interpolation remains the boundary for values such as
`{{webhook.price}}` that cannot be known until a run. Runtime handlers still
return explicit errors for bad resolved values so an old saved workflow cannot
silently place a different order.

## Validation Contract

### Nested Indicator

`indicatorName` is always required. `symbol` and `exchange` are required only
when `sourceSeries` is absent. When `sourceSeries` is present, strict validation
accepts blank symbol/exchange because the executor consumes the upstream array
without making a history request.

### SmartOrder quantity and target position

`quantity` remains present in SmartOrder JSON but is non-negative rather than
strictly positive, matching `SmartOrderSchema` and broker reconciliation logic.
A value of zero is valid for target-position and square-off semantics. Numeric
accessors must preserve an explicit zero instead of replacing it with the
default value `1`.

### Priced orders

The following node types share the same price rules:

- `placeOrder`
- `smartOrder`
- `optionsOrder`
- `optionsMultiOrder`
- `basketOrder`
- `splitOrder`

For static values, `LIMIT` and `SL` require a positive `price`; `SL` and `SL-M`
require a positive `triggerPrice`. A missing or blank field is an error, not a
reason to skip the range check. A `{{variable}}` value is accepted at activation
and checked after interpolation by the executor or service.

Generated Options Multi-Order strategies expose `MARKET` and `LIMIT` only.
Custom legs may use all four order types when each leg supplies the required
price fields.

### Order Update Trigger

Strict validation requires at least one literal `orderId` or a `symbol` filter.
An `orderId` containing `{{...}}` is rejected because trigger nodes have no
upstream context. `status` must normalize to one of the statuses accepted by
the order-update monitor. These checks mirror `add_watch()` so activation does
not fail after the graph validator has accepted the workflow.

### Expiry-dependent data nodes

- `optionSymbol` and `optionChain` require `expiryDate` unless the underlying
  embeds a `DDMMMYY` expiry in the exact format accepted by
  `parse_underlying_symbol()`.
- `syntheticFuture` always requires an explicit `expiryDate` because its price
  extraction logic consumes that field directly.

The editor continues to show Expiry Date as a normal required field for the
default `NIFTY` underlying.

### Margin

A Margin node must contain one of:

- a non-empty `positionsJson` basket,
- a non-empty legacy `positions` basket, or
- a legacy single-position `symbol`.

Static basket JSON must parse to a non-empty array of objects. Each static leg
must include symbol, exchange, action, quantity, product, and price type, with
the same constant and priced-order checks used by the margin editor. A whole
field or leg value containing `{{...}}` is deferred to runtime validation.

### Custom Options Multi-Order

When `strategy` is `custom`, `legs` must be a non-empty array. Static legs must
contain offset, optionType, action, and positive quantity. Their product, price
type, price, and trigger price are validated when present. Per-leg `expiryDate`
is removed from the TypeScript and prompt contract because the executor and
service use one common resolved expiry.

### Variable

`operation` is validated against all eleven editor choices. Conditional fields
are required as follows:

- `get` and `stringify`: `sourceVariable`
- `add`, `subtract`, `multiply`, and `divide`: `value`
- `parse_json`: a non-empty `value`
- `set`, `append`, `increment`, and `decrement`: no additional required field

Invalid operations never return success.

## Execution Contract

### Priced SmartOrder, SplitOrder, and BasketOrder

SmartOrder and SplitOrder read `price` and `triggerPrice` and pass them to their
existing client methods. BasketOrder adds common `price` and `triggerPrice`
fields to CSV-configured rows. List-form imported basket orders retain explicit
per-leg values; common node values fill only missing properties.

The editor exposes price type plus conditional price/trigger controls for all
three nodes and persists explicit zero defaults. Runtime price checks occur
before a broker call, including after variable interpolation.

### Variable operations

Variable operations have these exact semantics:

- `set`: store the interpolated value; JSON-looking strings retain the existing
  auto-parse behavior.
- `get`: copy the raw value from `sourceVariable`; optional `jsonPath` traverses
  dotted keys and bracketed list indexes.
- `add`, `subtract`, `multiply`, `divide`: coerce current and supplied values to
  floats and store the result. Division by zero returns an error without
  changing the target variable.
- `increment`, `decrement`: add or subtract one, preserving current behavior.
- `parse_json`: parse the interpolated string and store the resulting raw JSON
  value. Invalid JSON returns an error without mutation.
- `stringify`: JSON-serialize the raw source variable and store the string.
  Missing or non-serializable sources return an error.
- `append`: concatenate the supplied value to the target variable as text,
  treating an unset target as an empty string.

A missing source or invalid numeric conversion returns `status: "error"` and
stops the branch. Successful operations always store the result under
`variableName` and return that stored value.

### Safe `floor()`

The math evaluator accepts only a direct call to `floor()` with one positional
numeric expression and no keyword arguments. Other names, attributes, calls,
or argument counts remain rejected. This extends the AST whitelist without
introducing `eval()` or arbitrary function access.

### Telegram identity

Telegram alerts continue resolving their destination from the workflow API
key. The unused `username` input is removed from the editor, TypeScript type,
prompt tables, and examples. Old workflow JSON carrying the property remains
loadable; the extra field is ignored for backward compatibility.

## Documentation Corrections

`docs/prompt/flow-import-format.md` will be updated to:

- state that a second trigger is rejected by strict validation;
- document History `days` and the explicit-range precedence actually used by
  the executor;
- document Holidays `year` and Timings `date` instead of a nonexistent
  `exchange` field;
- document the implemented Variable operations;
- document `floor()` as the one supported math function;
- change the HTTP forwarding example timeout from `10` to `10000` milliseconds;
- replace computed-P&L `priceCondition` examples with `varCondition`;
- remove Telegram usernames and per-leg option expiries;
- describe common price fields on SmartOrder, BasketOrder, and SplitOrder;
- ensure order examples do not submit non-tradable index symbols to
  `placeOrder`.

Every parseable fenced JSON example will be checked with the strict workflow
validator while ignoring only the expected missing-trigger error on standalone
node snippets.

## Error Handling and Compatibility

- Draft saves remain possible because completeness checks stay behind
  `strict=True`.
- Imported or activated workflows receive precise JSON-pointer paths and error
  codes for missing conditional values.
- Dynamic `{{...}}` values are not rejected merely because their resolved value
  is unavailable during activation.
- Existing valid MARKET orders and the four already-implemented Variable
  operations retain their behavior.
- Existing Telegram workflows with `username` continue running for the API-key
  owner.
- Old workflows that previously activated with incomplete data are rejected the
  next time they are activated, before any broker call.

## Testing Strategy

Implementation follows red-green-refactor cycles.

Backend validator tests will cover:

- nested Indicator conditional requirements;
- SmartOrder zero quantity;
- missing and dynamic priced-order fields for all six order node types;
- Order Update alternative filters and invalid literal/status cases;
- conditional and explicit expiry requirements;
- empty, templated, valid, and malformed Margin baskets;
- custom Options Multi-Order leg requirements;
- Variable operation enum and conditional fields;
- every parseable prompt JSON example.

Executor tests will cover:

- explicit-zero numeric handling;
- SmartOrder, SplitOrder, and BasketOrder price propagation;
- each Variable operation, missing sources, invalid JSON, invalid numeric input,
  and division by zero;
- allowed `floor()` and rejected arbitrary calls;
- Telegram delivery remaining API-key scoped.

Frontend verification will cover default-data parity, TypeScript checking, the
Flow component tests, and a production build. Backend verification will run the
focused Flow suite plus Ruff on changed Python files. The repository-wide test
suite will also be attempted; known baseline collection failures will be
reported separately and will not be represented as regressions from this work.

## Delivery

Work is performed on `fix/flow-contract-repair`, forked from current
`origin/main`. After implementation and fresh verification, the reviewed
changes will be committed and pushed to `main` with a normal fast-forward push,
as approved. The original dirty checkout is not reset, cleaned, or overwritten.
