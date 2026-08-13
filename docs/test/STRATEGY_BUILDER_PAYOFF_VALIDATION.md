# Strategy Builder Payoff Fix Validation

Date: 28 July 2026  
Route: `/strategybuilder`  
Status: Automated validation passed; interactive browser validation was not available in this session.

## Scope

This change is limited to the Strategy Builder payoff path:

- payoff curve sampling, breakevens, extrema, Probability of Profit inputs, and display range
- profit/loss fill geometry and volatility-band rendering
- template strike and expiry resolution
- contract and implied-volatility inputs that directly feed payoff pricing
- regression coverage for every strategy template

No backend service, database, broker capability, Strategy Chart, order execution, commit, or push change is included. The existing files under the repository-root `audit/` directory were not edited.

## Corrections implemented

| Audit area | Resolution |
| --- | --- |
| PB-H1 / PB-M2: stale IV and leg-count-only refresh | Contract-changing edits clear the old leg IV. Greeks/IV refresh is keyed by contract symbol and active state, so strike, option type, expiry, and reactivation changes refetch market data. Expiry edits cannot reuse a symbol from a different loaded expiry. |
| PB-H2 / PB-L2: fixed price window and missing wide breakevens/PoP | Terminal breakevens are solved structurally across strike intervals and asymptotic tails. Multi-expiry roots use numerical scanning with adaptive tail expansion, including zero-slope calendar tails. Exact roots are injected into the displayed samples. |
| PB-H3: volatility markers outside the payoff domain | The page range contains all active strikes and the full two-standard-deviation range. Plotly is pinned to the sampled curve domain. Bands are clipped to that domain, and physically invalid negative markers are omitted. |
| PB-H4 / PB-H6: global-minimum strike-step template distortion | Template offsets now walk actual ordered strikes outward from ATM. They no longer multiply every offset by one global minimum gap. Out-of-range offsets are rejected instead of clamped or pulled toward ATM. |
| PB-H5 / PB-M5: fill wedges and beveled strike kinks | Every active strike and every exact breakeven is an explicit chart vertex. Profit and loss fills both contain the same zero-valued root, eliminating the pre-sample fill boundary mismatch. |
| PB-M1: multi-expiry extrema | Calendars, diagonals, and arbitrary multi-expiry combinations use a dense numerical analysis plus local extremum refinement. Unlimited right tails are still reported as positive or negative infinity. |
| PB-M4: wall-clock staleness | Days-to-expiry values that feed payoff pricing refresh once per minute. |
| PB-L1: exact-zero duplication | Roots are normalized, sorted, and tolerance-deduplicated. An empty strategy does not invent a zero-price breakeven. |
| Template contract integrity | A template is blocked when a required CE/PE contract is absent. Far-expiry calendar and diagonal contracts are fetched with the same exchange mapping and request queue as the primary chain, then validated before legs are added. |

## Iron Condor and shared wedge exposure

The screenshot showed two distinct shared rendering risks:

1. a fill boundary switching at a nearby sample instead of the interpolated breakeven
2. a strike kink falling between uniform samples and rendering as a short beveled shoulder

The corrected sample set for the regression Iron Condor contains the exact values:

```text
long put strike, left breakeven, short put strike,
short call strike, right breakeven, long call strike
```

Both profit and loss fill traces equal zero at each breakeven. The same rule is applied to custom strategies and all templates, so the correction is not Iron-Condor-specific.

## All-template validation

The suite iterates all 38 entries in `STRATEGY_TEMPLATES` on an intentionally irregular 41-strike chain.

For every template it verifies:

- each offset resolves by actual strike position
- equal offsets resolve to the same strike
- distinct offsets remain distinct and ordered
- every required strike is an exact payoff sample
- expiry and T+0 samples are finite
- max profit and max loss are not `NaN`
- breakevens are unique and sorted

This includes butterflies, condors, iron flies, Iron Condors, Double Condor, Batman Strategy, Double Fly, Call Calendar, Put Calendar, and Diagonal Calendar.

Additional focused cases cover:

- the Iron Condor strike and breakeven geometry
- wide strangle roots and Probability of Profit
- exact-grid zero deduplication
- smooth multi-expiry extrema
- positive-slope and zero-slope distant tail roots
- truncated strike chains
- missing later expiries
- missing CE/PE contracts
- stale IV after strike, option-type, or expiry edits
- high-IV negative volatility markers

## Verification evidence

### Regression tests

Command:

```bash
npx -y -p node@24 sh -c 'cd frontend && npm run test:run'
```

Result:

```text
Test Files  12 passed (12)
Tests       170 passed (170)
```

The new regressions were exercised red-first. Observed pre-fix failures included:

- no structural wide root outside the supplied chart window
- finite max profit for an unlimited multi-expiry tail
- no distant zero-slope calendar root
- duplicate or invented exact-zero behavior
- enabled invalid Batman/calendar templates
- missing contract-side acceptance
- stale-IV invalidation helper absent
- negative sigma shapes outside the physical price domain

### Production build

Command:

```bash
npx -y -p node@24 sh -c 'cd frontend && npm run build'
```

Result: TypeScript project build and Vite production build completed with exit code 0. Generated `frontend/dist` output was removed after validation and is not part of this working change.

### Lint and formatting

Command:

```bash
npx -y -p node@24 sh -c 'cd frontend && npm run lint'
```

Result: exit code 0, no lint errors. Four pre-existing optional-chain warnings remain in unrelated/existing lines; they were not changed to preserve the payoff-only scope.

### Independent code review

An independent read-only review found no Critical issues. Its four Important findings were fixed and re-reviewed:

- expiry edits reusing a different-expiry chain symbol
- missing zero-slope calendar tail expansion
- negative sigma markers
- missing near/far CE/PE contract validation

Final reviewer assessment: ready to merge.

### Interactive browser validation

Not executed. No controllable browser was available in this session. The automated chart test inspects the Plotly trace vertices, fill values, axis range, shapes, and annotations directly, but this is not represented as a substitute for a live visual sign-off.

Before release, perform one manual render of the original Iron Condor configuration and confirm:

- no colored wedge at either breakeven
- one sharp vertex at each strike
- no call-side shoulder between the plateau and wing
- all valid volatility markers remain visible
- Batman, Double Fly, and Double Condor either resolve every real contract or show a blocking validation message

## Explicitly out of scope

The following items from the broader audit were not changed because the approved implementation scope was payoff-only frontend behavior:

- PB-M3: the adjacent Strategy Chart backend excludes futures
- PB-L3: frontend/backend near-expiry epsilon alignment
- backend Black-76 services, database state, broker capabilities, and execution behavior

## Repository state

No commit or push was performed.
