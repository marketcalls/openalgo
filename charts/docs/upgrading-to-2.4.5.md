# Upgrading to 2.4.5

Existing chart creation and feed contracts keep their defaults. Upgrade the
package and lockfile, run your host's tests and validate its rendered charts.
The optional APIs below require explicit host wiring. Installing a newer package
alone does not add a workspace toolbar or migrate a trading terminal.

## Data and instruments

`Bar.oi` is optional. Open interest is a level, not a flow: when folding bars,
take the latest defined reading in the bucket and never sum readings. Zero is a
real reading; absence is missing data. A live tick without OI leaves its forming
bar without OI, rather than silently carrying a historical value forward.

Declare `ChartDataContext.hasOpenInterest` when instrument metadata establishes
support. `true` with a missing bar value, `false` for an unsupported instrument
and omitted for unknown support remain distinct. Do not infer support from a
provider's placeholder zero. Open Interest and Open Interest Change use separate
panes; Open Interest Buildup colors candles from adjacent price/OI observations.

The optional [Instrument contract](instruments.md) supplies validated metadata,
calendar exceptions, formatting and exact supported interval tokens. Clear old
source bars before applying different metadata, cancel stale requests and retain
host ownership of loading. The trade helper keeps quantity units unchanged.

## Workspaces and replay

Import portable documents and `WorkspaceRepository` from
`openalgo-charts/workspace`. Implement the asynchronous store at your existing
account boundary and choose a namespace that changes when the account changes.
Treat save failures and revision conflicts as visible states. Never serialize
credentials, armed state, live orders, positions or account balances.

The reference host demonstrates named layouts, indicator templates, selected
chart controls and shared replay. Install complete saved drawing/study identities
before restoring their alerts. Hosts retain responsibility for requesting each
source, resolving symbols, cancelling stale loads and applying a workspace as
one coherent transition.

`isReplaying(chart)` includes paused replay. Lock order entry while choosing a
replay start, loading replay data and replaying any relevant chart. Those host
transition locks are additional to the chart's active-replay flag. Coordinate
charts by UTC time rather than copying logical bar indexes.

## Alerts, localization and trading

Alert evaluation defaults to bar close. Intrabar touch is an explicit choice:
a forming candle can touch a level and later retract before close. Subscribe
to alert events for delivery through your existing host path. The library does
not send notifications or orders. Persist the alert document if fired-once state
and anchors should survive reloads; restoration itself evaluates no history.

Widget `translate` is optional and falls back to the English catalog. Translate
named message keys, preserve required parameters and keep user/provider content
literal. See [widget localization](widget-localization.md).

Trading capability sources are optional. Omitting one retains legacy behavior;
when one is configured, unavailable, unknown or unsupported operations are
blocked with a reason. Supply current account/source permissions and continue to
enforce them on your server. Capability checks do not replace authentication or
broker authority. See [trading capabilities](trading-capabilities.md).

## Verification and support

Run your host's source-switch, reconnect, persistence, replay and trading guard
tests against the packed or installed release. Use simulated order transport for
automated validation. Confirm venue-specific timestamp and quantity conventions
at the adapter boundary, especially for fractional crypto quantities.

The [adapter conformance suite](adapter-conformance.md) and
[browser endurance harness](browser-endurance.md) are reproducible starting
points. Their deterministic traffic does not certify your live account or venue.
See [compatibility and support policy](../COMPATIBILITY.md) for release boundaries.
