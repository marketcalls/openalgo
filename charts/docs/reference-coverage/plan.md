# Native capability implementation plan

The scope and ownership boundaries are in [design.md](design.md).

Scope update: defer issue #22 (higher-timeframe inputs on built-in indicators). Continue the remaining listed fixes and capability gaps, including issue #25 (price-only autoscaling) and issue #12 (collapsible indicator list), before the authorized release.

1. Retain the known-interval confirmation fix and compiled-program integration tests. Verify both after removing the excluded adapter work.
2. Map remaining native functionality to concrete behavior and test evidence. Keep comparative research outside the repository. Prioritize correctness defects and actual script-adapter refusals.
3. Complete lifecycle provenance and provider-driven confirmation, including historical loads, live updates, replay, cancellation and teardown.
4. Add requested-context and study-dependency contracts with full/tail execution and persistence checks.
5. Extend inputs, visual descriptors and alert policies with compatible defaults. Exercise outputs from compiled programs through the actual chart.
6. Complete missing calculation helpers, navigation, density, drawing, layout, persistence, trading and provider capabilities.
7. Update public documentation and executable examples for each added capability. Verify rendering changes in actual browsers as well as unit tests.
8. Run complete chart verification and integration against a pinned script engine, then recheck its latest development revision. Review all outstanding capability requirements before claiming completion.

For numerical work, verify equivalent calculations against shared fixtures in
both language engines as well as the chart helpers. Keep renderer/adapter checks
separate from arithmetic conformance; coordinated engine changes need evidence
that the existing contract is wrong or a deliberately added language contract.

## Evidence retained

- Chart baseline: `a1828e9ac948d2f9aebe0657f421987a85d6f2a7`.
- Pinned script-engine revision: `833ce15f7ec1bb0ab8ae203b800c8858ce3b4339`.
- Twelve confirmation regression cases, nine demonstrated failing before implementation.
- Fifteen compiled-program integration cases plus public descriptor typechecking.
- Measured chart-only build: baseline 55.58 KiB, confirmation fix 56.09 KiB, budget 56.25 KiB.

The drop-in facade and additional feed adapter are excluded. No percentage of full capability coverage has been certified.

The implemented whole-study transaction follows [scale ownership](scale-ownership.md), including primitive coordinates, range ownership and persistence. [Requested provider lifecycle](requested-providers.md) extends the native request path with explicit availability, cancellation and replay boundaries.

[Alert policies](alert-policies.md) now add live-update, first-match-per-bar, known-close and instance-lifetime delivery. Legacy omitted-frequency behavior and the existing script adapter remain compatible.

[Study dependencies](study-dependencies.md) now add opted-in scalar sources, ordered calculation, unavailable-state propagation, UI selection and graph persistence. The first built-in consumers are SMA, EMA and WMA. The existing script adapter can produce these sources without an upgrade; consuming them inside compiled programs requires explicit adapter support.

[Multiple price axes](multiple-price-axes.md) separates stable scale IDs from visible columns. It covers native placement, rendering, exact input routing, host menus and full-layout persistence. [Indicator template layouts](template-layouts.md) now preserves this metadata with explicit copy and sharing policies.

[Per-plot scale assignments](plot-scale-assignments.md) defines the prerequisite for copying mixed-scale studies and explicit price-pane plots without losing their bindings.

[Indicator template layouts](template-layouts.md) adds capture, portable pane and scale relationships, copy policies, dependency ownership and guarded host application.

The final numerical audit covers every shipped numerical indicator and the
equivalent calculations in both companion language packages. Compare shared
fixtures, fix confirmed deviations, and publish both companion packages as 0.7.0
after the complete audit and release checks. Inventory, arithmetic comparison and
chart integration can run in parallel with exclusive file ownership. Record
non-equivalent contracts explicitly; agreement between two implementations is not
proof that either follows the calculation specification.

## Authorized release sequence

[Numerical audit](numerical-audit.md) records independently derived chart
corrections and their compiled and browser evidence. It does not certify complete
agreement while remaining contract differences are still under investigation.

The reported right-axis autoscale issue is fixed and verified on the example host in three browser engines. Retain that regression check for the final candidate. After completing the native capability work, validate the package, bump it to 2.5.4, update the example host, website, API documentation and changelog, commit and push, publish the package and website, and create the matching release. Verify the published artifacts against the tested build. Publication is authorized by the user; incomplete capability work is not a release candidate.
