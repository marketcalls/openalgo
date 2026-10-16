# Production chart workspace

## Objective and authority

Implement the nine enhancements in openalgo/openalgo issue 2078 in the chart engine,
reference host, and the actual OpenAlgo `/trading` consumer. Preserve the broader
production-readiness work requested in the conversation: instrument metadata,
adapter conformance, browser endurance, persistence/localization, capability-aware
trading integration and documented maintenance. The user authorized continuous
implementation, validation, commits, push and publication of Charts 2.4.5. The
release order is Charts first, then the remaining `/trading` implementation and
final connected-broker/deployment validation. Those consumer tasks remain in
scope but do not gate the Charts publication. Live orders remain outside scope.

Source: https://github.com/marketcalls/openalgo/issues/2078

The supplied images clarify named indicator templates, focused/all-chart replay,
and a named workspace menu with save, autosave, duplicate, rename, recent layouts,
new/open layout and chart data download. Provide portable layout export/import for
sharing a workspace without publishing private information.

## Invariants

- No comparison product names in changes, commit messages or PR material.
- UTC seconds for engine data. OpenAlgo trade-fill timestamps remain milliseconds
  at their existing adapter boundary. Default Asia/Kolkata behaviour is preserved.
- Broker state remains authoritative for orders and positions. Workspace files
  never contain credentials, orders, positions, account balances or the armed flag.
- Replay and replay selection lock every order-entry route across the workspace.
- No future bars may be disclosed by synchronized replay or comparison overlays.
- Sync between charts uses time, never another chart's logical index.
- Existing library options retain their defaults. New APIs are additive.
- Every user-visible control has working behaviour, error feedback and teardown.
- Engine tiers remain free of host DOM. Keep the established bundle boundaries.
- Use the packed candidate in an isolated OpenAlgo worktree for integration tests.

## Acceptance matrix

| ID | Requirement | Completion evidence |
| --- | --- | --- |
| F1 | Named layouts include every pane's symbol, interval, chart type, settings, studies, drawings, comparison state and grid arrangement. Create, save, load, rename, duplicate, delete, recent list, autosave, export/import. | Round-trip and migration tests; browser reload and layout-switch tests; failed storage writes remain visible; no credentials or trading state serialized. |
| F2 | Named indicator templates capture parameters and plot styling and apply to the focused chart across symbols. | Multiple instances of one study, unsupported custom studies, replace/apply behaviour and empty templates tested; picker exercised in `/trading`. |
| F3 | Optional vertical crosshair snapping to nearest candle center, independent of horizontal OHLC magnet. | Real pointer/paint tests, empty and future space, settings/state round-trip, default behaviour unchanged. |
| F4 | Volume moving average with configurable period, styled on the volume scale. | Correct warmup and rolling values, live replacement/append, transforms, replay and visibility tests. |
| F5 | Independent interval sync in multi-chart layouts. | Late join, toggle, member removal, feedback protection, unsupported interval and rapid-change tests; `/trading` sync control works. |
| F6 | Volume bar direction follows its candle, including theme changes, live ticks and transforms. | Colour agreement assertions and browser pixels in dark/light mode and replay. |
| F7 | Multiple comparison symbols, independently removable, with common-baseline percentage comparison. | Mismatched calendars, missing data, source failures, interval changes, teardown, live updates, persistence and replay tests. |
| F8 | One replay control for a grid, with focused/all-chart scope and one shared clock. | Different symbols, histories and intervals align by time; no future disclosure; pause/seek/speed/exit and loading failure behave consistently; trading remains locked throughout transitions. |
| F9 | One workspace toolbar acts on the selected chart: symbol, interval, chart type, indicators, snapshot and replay. | Focus is apparent, keyboard accessible, survives layout changes, no duplicate toolbars in a grid, mobile usable. |
| P1 | Unified instrument metadata and calendar/format rules. | Typed validated contract and integration tests for session exceptions, 24-hour markets, precision, quantity steps and supported intervals. |
| P2 | Reusable adapter conformance tests and broker/crypto reference cases. | Recorded or deterministic input cases demonstrate duplicates, late updates, repairs, errors, cancellation and reconnect. Label synthetic and real-feed evidence separately. |
| P3 | Browser performance and endurance gates. | Declared device/workload measurements, real rendering and memory checks, repeatable artifact reports; prolonged run with an actual process handle and final report. |
| P4 | Async host persistence and translation contracts. | Adapter failures, migration, account namespace changes and translated widget controls covered; no backend credentials embedded. |
| P5 | Consistent trading capability contract. | Existing OpenAlgo path preserved, unsupported capabilities hidden/disabled, ambiguous order state retained, replay guards verified. |
| P6 | Maintenance and release documentation. | Compatibility/deprecation policy, support boundaries, measured package facts, API docs and consumer guide updated without inventing contractual guarantees. |

## Architecture

Use the existing Chart, DrawingController, ComparisonController, ReplayController
and LinkGroup. Add reusable behaviour at these boundaries and let the host retain
ownership of requests, authentication and execution. Do not create a second chart
engine or route trading through a new order authority.

The library supplies validated workspace/template document contracts, optional
asynchronous storage, instrument metadata, interval linking and reusable replay
coordination. The reference widget demonstrates the contracts. OpenAlgo provides
its host-specific persistence adapter, terminal snapshots, shared React controls,
symbol resolution and user feedback through existing components.

Build in phases: interaction/data primitives; workspace documents and storage;
consumer workspace controls; comparison and coordinated replay; instrument and
adapter contracts; localization/capabilities; endurance and release validation.
Each phase has its own detailed execution plan and regression gate. Phases are
sequencing, not reductions of the goal.

## Verification and completion

For each behaviour, write a regression first and observe failure against the
baseline. Run affected suites, then package lint/typecheck/unit/build/demo/dts/size/
tree-shaking checks. Run library Chromium, Firefox and WebKit coverage for changed
interactions. Install an npm-packed candidate into the isolated consumer, run
trading tests, typecheck/build and the real `/trading` browser harness with mocked
transport; inspect screenshots. Add real-feed evidence only when genuinely run.

A numeric quality score is an assessment, not a test or a deliverable that can be
manufactured. Completion requires the matrix above to be supported by current
evidence. Preserve incomplete items in the ledger and continue work. Record any
external evidence that cannot be produced locally without claiming it passed.
