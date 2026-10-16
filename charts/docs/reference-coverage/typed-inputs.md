# Typed study inputs

Extend native descriptors with symbol, session, multiline, price and timestamp
inputs. Values remain plain strings and numbers in chart, template and workspace
documents. Existing `time` inputs retain their chart-zone wall-clock strings.
The current compiled adapter remains structurally compatible and keeps its own
language input validation.

New kinds validate their defaults, constraints and supplied values before
registration, instance mutation or chart restore. Missing settings use defaults;
malformed supplied values reject rather than being repaired. Existing input kinds
retain their current contracts. Accessor settings reject before they execute.

- `symbol` holds an opaque host identifier, including an empty chart-symbol
  selection. Optional `exchangeKey` names a separate string setting, defaulting
  to empty text if no input declares it. Search uses
  the host's existing provider and writes both fields atomically.
- `session` uses the existing session parser, including overnight and weekday
  rules. Accepted spelling is preserved in state.
- `multiline` preserves whitespace, newlines and literal text.
- `price` holds any finite number within optional bounds. Step is editor metadata;
  the core does not round prices. Optional `pick` enables chart selection, with
  explicit pane and scale targets available for mixed-scale studies.
- `timestamp` holds finite absolute UTC seconds, including fractional seconds.
  Raw-seconds editing avoids calendar-range and precision loss. Optional `pick`
  selects a bar time. Timezone changes never reinterpret the stored number.

`Chart.beginPick` keeps the existing price/time selection and adds optional pane
and price-scale targeting. Invalid targets reject before replacing a current
pick. Off-plot gestures and primitive controls cannot answer it. Panning stays
available; active drawing placement refuses a pick. Starting placement, replacing
context, changing pane order, restoring state or destroying the chart cancels
it. Its callable `PickHandle` reports whether that invocation remains active.
Lifecycle fences remain effective during start/end listeners and before value
delivery, so reentrant host actions cannot retain or deliver a stale capture.

Hosts suspend the settings overlay, scrim and focus trap while picking, then
restore the same draft and focus. Cancel, owner removal and context replacement
cannot apply stale results. Invalid text remains visible with an error. Missing
symbol search leaves manual entry available. Values selected for a study never
change the chart's primary instrument.

Verification covers core validation and capture tests, both hosts, state round
trips and the installed companion adapter. Actual browser tests exercise desktop
and narrow layouts in three engines, including a live website example. This
contract does not add a transport adapter or language runtime.
