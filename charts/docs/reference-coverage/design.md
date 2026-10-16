# Native capability design

Implement missing indicator and chart functionality through the existing native APIs. Preserve the companion script engine's public descriptor contract, calculations and saved settings. Do not introduce a second scripting runtime, a drop-in API facade or an additional feed compatibility adapter.

Issue #22, exposing higher-timeframe inputs on built-in indicators, is deferred at the user's request. Existing native requested-context capabilities remain supported. The remaining listed fixes and gaps are in scope, including price-only autoscaling and a collapsible indicator list.

Native feeds and custom broker feeds continue using the current data interface. New provider contracts are justified only by a missing capability, such as authoritative bar-close events or a dataset that cannot be represented as ordinary bars. Provider-dependent functionality must be verified against supplied data; an interface declaration alone is not implementation evidence.

## Ownership

The chart owns rendering, lifecycle context, chart interactions, data access and persistence. The script engine owns compilation, execution, rollback and strategy arithmetic. Extend their existing boundary when a demonstrated capability requires it. Keep comparative research and raw reference inventories outside the repository. Use generic descriptions in source, tests, comments, documentation and commit messages. Implementation and tests must be independently authored from documented behavior.

Numerical changes require common input/output fixtures for equivalent chart,
JavaScript-engine and Python-engine calculations. Adapter compatibility alone does
not establish numerical agreement. Patch an engine only where the same contract
has a demonstrated defect; keep documented seed and missing-value differences
explicit and preserve existing program defaults. New language-level calculation
contracts require matching support and checks in both engines.

## Required capabilities

| Area | Required behavior |
| --- | --- |
| Lifecycle | Correct interval and calendar confirmation; historical, live and replay provenance; explicit provider confirmation for count-driven bars. |
| Calculations | Defined missing-value, warmup, varying-length and statistical contracts with independent fixtures. Preserve existing numerical defaults. |
| Requested contexts | Evaluate expressions in requested symbol/timeframe contexts before alignment; define confirmation, gaps, lookahead, intrabar arrays, cancellation and replay boundaries. |
| Study sources | Select another study's output with stable references, dependency ordering, cycle rejection, propagation, removal and persistence. |
| Inputs | Typed symbol, session, multiline text, price and absolute-time inputs; interactive selection, constraints and settings migration. |
| Visuals | Dynamic and gradient fills, multiple tables, text and marker styling, drawing variants, placement, updates and disposal. |
| Alerts | Every-update, once-per-bar, close and once-only policies with deduplication and historical/replay suppression. |
| Chart and widget | Navigation, scales, series, studies, drawings, layouts, persistence, events and consistent desktop/mobile bar density. |
| Trading and providers | Missing order, position, account and data-context capabilities through real host contracts and fixtures. |
| Script integration | Public descriptor assignability and execution of compiled programs through the actual chart, including requests, alerts and visuals. |

An inventory or passing existing tests does not establish full coverage. Unmapped, partial and provider-dependent behaviors remain incomplete until verified.

## Current implementation

The confirmation fix reuses the native interval registry and calendar boundary logic. Fixed bars close at their recorded opening plus their duration. Calendar bars close at the next calendar boundary in their configured timezone. Count-driven and unrecognized intervals cannot be confirmed by the clock. Hosts without an interval retain their legacy fallback.

The integration runner uses a separately built, caller-specified script engine and its public adapter. It adds no runtime dependency. Recheck newer engine revisions before claiming compatibility with ongoing development.

The user has authorized version 2.5.4 publication after the native work and validation are complete. Follow the release sequence in the plan.
