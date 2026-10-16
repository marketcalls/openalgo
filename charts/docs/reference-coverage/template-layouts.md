# Indicator template layouts

Legacy templates retain study settings and dependency references but discard pane weights and scale configuration. Main-pane copies can also bind to an unrelated destination scale with the same ID. Rich templates now preserve those relationships through the native workspace tier and the example host.

## Public contracts

- `IndicatorTemplatePlotBinding` contains `instanceId`, exact `plotKey`, `paneIndex` and `scaleId`.
- `IndicatorTemplateLayout` contains `panes: PaneState[]`, `plots: IndicatorTemplatePlotBinding[]` and optional `primaryScaleId` for the source's primary series in pane zero.
- `IndicatorTemplatePayload` contains `indicators: IndicatorState[]` and optional `layout`. `IndicatorTemplateInput` accepts this payload or the existing study array.
- `IndicatorTemplateDocument` extends the payload and existing document metadata. Version remains 1 because omitted layout retains legacy behavior.
- `parseIndicatorTemplatePayload(input)` validates and detaches either input form. Rich payloads retain stable identities for every study; legacy independent arrays retain their existing anonymous-copy behavior. Dependency validation remains closed and acyclic.
- `captureIndicatorTemplate(chart: Chart): IndicatorTemplatePayload` captures all studies, effective plot bindings, pane/scale settings and the actual primary scale identity. It captures no market data or runtime formatter functions.
- `IndicatorTemplateApplyOptions` has `scalePolicy?: 'copy' | 'share'` and `rangePolicy?: 'auto' | 'preserve'`. Defaults are copy and auto.
- `planIndicatorTemplateState(chart: Chart, incoming: IndicatorTemplateInput, mode: IndicatorTemplateMode, options?: IndicatorTemplateApplyOptions): IndicatorTemplatePlan` reads the destination and returns a detached `{ indicators, panes?, restoreOptions? }` plan. It validates descriptors and metadata before the host calls `restoreState`. It does not apply the patch or reload a source.
- `ChartRestoreOptions.preserveScaleFormats` selects existing `{ paneIndex, scaleId }` targets whose runtime formatter callback or default formatter should survive automatic study-series recreation. Numeric saved scale settings still apply. The planner selects retained destination scales and omits replaced study-only slots. Hosts pass `plan.restoreOptions` as the second argument of `restoreState`; runtime callbacks never enter portable documents.
- Repository create/save methods accept `IndicatorTemplateInput`. Updating with a legacy array removes any old layout metadata.

The existing `planIndicatorTemplate` array API remains compatible.

## Copy and sharing rules

1. Map scale relationships by source pane plus scale ID. Equal IDs on different panes are independent. Effective plot bindings are captured explicitly, including price-pane overlays from other panes. Validate all plot keys and pane relationships against loaded descriptors before applying.
2. Every rich copy receives fresh study identities, including independent studies. Remap declared dependency references and retained `indicatorRange.instanceId` ownership through the same map. Opaque settings remain untouched.
3. A source primary-scale binding maps to the destination's actual primary scale when one exists. Retain the destination scale configuration and view. Moving the source primary axis to the left must not change this relationship.
4. Copy is the default for other pane-zero scales. Allocate fresh named IDs, preserve sharing within the copied group, and append copied visible columns after existing columns on their respective sides while retaining source relative order. Repeated copies remain independent.
5. Share deliberately reuses non-primary pane-zero IDs. Existing destination configuration wins; copy source settings only when the destination has no such scale. New positive pane groups remain separate in either policy.
6. Append places incoming positive pane groups after current panes. Replace reuses study-only pane slots where possible while reserving panes carrying host-owned series. Preserve unrelated destination series, their scales and the main pane weight. Retain source pane weight relative to its primary pane and scale it against the destination primary weight.
   Chart snapshots include indicator plot series as well as host series. Identify host-bearing panes using actual live plot handles and total pane series counts; descriptor plot counts alone are insufficient after a handle has been removed.
7. Copy only relevant main-pane scale state. New/reused study panes receive the source pane configuration. Incoming plot overrides encode the captured effective bindings after remapping; explicit price overlays retain pane-zero attachments. Primitive-only fallback assignments remain representable through the whole-study override.
8. Auto drops copied manual ranges and ratio locks. It retains explicit host fixed bands and lets owned indicator defaults be recomputed from the destination data. Preserve copies saved ranges and ratio references. Source primary/shared existing destination views are never overwritten by copied settings. Clear orphaned outgoing study ownership from retained destination scale state while preserving genuine manual-view intent.
9. Legacy documents with no layout keep existing behavior. Empty append is a no-op. Malformed metadata, missing descriptors, external dependencies, identity conflicts and pane/study limits fail before chart mutation.

## Ownership and host behavior

The example host saves, updates, imports, exports and applies the complete payload. Preserve its loading, settings, replay-selection and captured-target guards. Retain drawings, alerts, source handles and data. Recovery restores the prior state only while the same operation still owns the chart; a nested newer restore must not be overwritten. Refresh the primary mirror only for its current owner. No asynchronous source reload is introduced.

## Implementation plan

1. Extend workspace document types, bounded parsing and repository persistence. Add failing round-trip, malformed metadata, arbitrary plot-key, legacy and dependency tests before implementation.
2. Add native capture and detached layout planning in a focused workspace module. Reuse the legacy dependency-copy identity logic where practical. Cover primary-axis relocation, repeated copies, grouped panes, host-series preservation, explicit overlays, primitive-only studies, range ownership, manual-range policies and visible-column order with actual chart fixtures.
3. Integrate the example host and add explicit copy/share and range policy controls. Cover stale owners, nested restores, rollback failures and replay behavior.
4. Add public API documentation, skills and an executable website example. Exercise the built package and host in three browser engines, inspect screenshots, and preserve the autofit regression.
5. Run full package verification, unchanged script-engine integration, documentation generation without warnings, skills coverage and the website build. Measure bundle changes before adjusting budgets, review the final diff and commit the verified batch.

Comparative research remains outside the repository. No additional feed adapter or language runtime is introduced. This batch does not complete the remaining native capability or release scope.

## Validation

Full package verification passed with 7,266 unit tests, 455 example-host tests and
seven endurance checks. Documentation generation passed with warnings treated as
errors; skills coverage names all 978 exports and registry entries. These are
measured test and inventory counts, not a percentage of functional coverage.

The final build passed 33 browser cases across three engines, including native
template rendering, primitive-only panes, destination formatters, host controls
and the original price-autofit regression. The built website passed 30 states
across desktop and narrow layouts, including every template control. Screenshots
from the native engine, example host and website were inspected.

Eighteen compiled-program integration checks pass against the unchanged pinned
engine, including template copies with independent scales and same-time updates.
This verifies the adapter boundary; the complete cross-language numerical audit
remains separate work. Independent review findings for recreated hidden scales
and accessor-bearing formatter selectors are covered by failing-then-passing
regressions and closed.

Measured Brotli sizes are 109.13 kB for base, 8.61 kB for workspace and 289.23 kB
for all tiers. Chart-only imports measure 68.37 KiB. The measured limits and
optional-tier removal checks pass.
