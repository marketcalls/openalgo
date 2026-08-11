# Task 6 report: Manual, edit, futures, and fallback safety

Date: 2026-08-11

Reviewed base: `3874a778a`

## Result

- Manual Add and Edit now receive one async listed-contract resolver. Both clear prior
  symbol/current price as soon as expiry, strike, or option type changes, reject missing
  contracts, and use a generation guard so only the latest request can update the UI.
- Same-expiry options reuse only the identity-matching active chain. Far-expiry options fetch
  the requested expiry with Greeks and accept only the canonical symbol and metadata returned by
  that response. No manual/edit option symbol is constructed locally.
- Futures use the existing master-contract-backed `/scalping/api/futures` list, match the exact
  selected expiry, then quote that exact `exchange:symbol`. The option-expiry parity forward is
  not used as the futures entry/current price.
- The existing futures endpoint now exposes the row's stored `tick_size` alongside canonical
  symbol, expiry, and lot size. `SymToken` has no authoritative expiry timestamp/cut-off field,
  so futures keep `expiryTs: null` rather than fabricating one.
- Entry and optional exit prices use Task 3 `parseFinitePrice`. Zero is preserved; empty entry,
  negative, and non-finite values render associated inline errors with `aria-invalid` and
  `aria-describedby`. Lot behavior is unchanged.
- `fallbackPricesByLeg` now matches only `exchange:symbol`; the strike/type lookup was removed.
  The separate symbol-keyed `/multiquotes` backfill remains. Resolved zero-price legs are not
  misclassified as missing prices.

## Independent `origin/main` validation

Validated against `origin/main` `74b53ae3949cdf3a303d9ebaa8c9dba13f1aa83e`.

- **SB-02:** origin Manual Add read whichever `chainData.chain` happened to be active and then
  fell back to `buildOptionSymbol` (`StrategyBuilder.tsx:863-867`). Selecting another expiry did
  not make the strike lookup expiry-specific.
- **SB-05 / SB-10:** origin Edit constructed cross-expiry option and futures symbols locally
  (`EditLegDialog.tsx:136,144`), then the page rebuilt them again on save
  (`StrategyBuilder.tsx:980-987`). Neither boundary required the listed response's canonical
  symbol.
- **SB-11:** origin manual futures used `buildFutureSymbol` and filled a missing entry price from
  the selected option chain's synthetic/parity future. The existing `/scalping/api/futures`
  endpoint already queried exact master-contract FUT rows, so it was reused rather than adding an
  endpoint.
- **SB-23:** origin Edit used `Number(entryPrice) || leg.price`
  (`EditLegDialog.tsx:181`), which silently restored stale price and rejected a valid zero.
  Lots were not widened into this fix.
- **SB-24:** origin `fallbackPricesByLeg` was derived from active-chain strike and option type
  (`StrategyBuilder.tsx:737+`), allowing a far-expiry leg to inherit a same-strike near-expiry
  quote. The correctly symbol-keyed multiquote effect was separate and remains intact.

The documented future symbol format (`BASE + expiry + FUT`) was reviewed, but it is not used to
synthesize a tradable contract; the canonical master-contract symbol is authoritative.

## TDD evidence

### RED

Focused component command before production changes:

```text
npm run test:run -- src/components/strategy-builder/ManualLegBuilder.test.tsx src/components/strategy-builder/EditLegDialog.test.tsx
Test Files 2 failed
Tests 9 failed | 5 passed
```

Expected failures showed the missing resolver prop/behavior, absent canonical symbols, no stale
response guard, inaccessible price fields, no inline validation, and zero falling back to the old
price. A Radix `scrollIntoView` harness gap was isolated and supplied with the same DOM shim used
by the page suite.

Backend metadata RED:

```text
uv run pytest -q test/test_scalping_futures_contracts.py
collection error: cannot import name '_serialize_futures_contract'
```

This proved the existing response dropped the master-contract row's available tick size.

### GREEN

```text
npm run test:run -- src/components/strategy-builder/ManualLegBuilder.test.tsx src/components/strategy-builder/EditLegDialog.test.tsx src/pages/StrategyBuilder.test.tsx src/lib/strategyContracts.test.ts
Test Files 4 passed
Tests 41 passed

uv run pytest -q test/test_scalping_futures_contracts.py
1 passed
```

Coverage includes far-expiry canonical manual/edit contracts, stale-response rejection,
missing-contract clearing/disabling, exact futures symbol/quote/lot/tick metadata, zero entry and
exit values, invalid entry/exit feedback, and the real page resolver calls.

## Final verification

```text
npm run test:run
Test Files 24 passed
Tests 374 passed

npm run lint
Checked 382 files. No fixes applied.

npx tsc -b --pretty false
Exit 0

npm run build
3013 modules transformed; built in 2.63s. Exit 0

uv run pytest -q test/test_scalping_futures_contracts.py
1 passed

git diff --check
Exit 0
```

Build-generated `frontend/dist` tracked changes were restored to `HEAD`.

## Concern

The master-contract schema stores an expiry date string but no authoritative futures cut-off
timestamp. This task deliberately reports `expiryTs: null` for futures. Adding an exchange-aware
future expiry instant requires a separate authoritative backend contract; local date/time
construction would violate the reviewed boundary.

## Fix Round 1

Reviewed head: `2ee0604ed`

### Blocking findings addressed

- `resolveLegContract` now has a stable callback identity. A ref carries the latest API key,
  underlying/exchange, active chain, and futures expiries; every invocation snapshots that state
  once before resolving. Live active-chain object replacement therefore no longer clears the
  manual selection or repeats far-option/futures contract requests.
- Edit no longer trusts a persisted leg as a listed contract. Opening the dialog clears the
  resolved contract, disables Modify, resolves the exact stored selection, and then canonicalizes
  symbol and market metadata. A missing/delisted current selection remains cleared with an inline
  error and cannot be saved. Live metadata updates for the same leg identity do not reset the
  in-progress form.
- `isLegClosed` now defines the shared boundary: `undefined` is open; any finite non-negative exit
  price, including zero, is closed. Payoff geometry/horizons, realised P&L, live subscriptions,
  margin and multiquote candidates, positions status, basket execution, and portfolio
  streaming/status/P&L all consume that predicate. Edit hydration preserves a literal zero.
- Futures forwarding assertions now cover canonical symbol, normalized expiry, lot size, tick
  size, quote, and the deliberately authoritative `expiryTs: null` value. Flask route tests use an
  in-memory master-contract table to verify session authentication, underlying/exchange/FUT
  filtering, chronological sorting, and the full response fields.

### RED evidence

Resolver/edit focused run before production fixes:

```text
npm run test:run -- src/components/strategy-builder/EditLegDialog.test.tsx
Test Files 1 failed
Tests 3 failed | 13 passed

Open validation: expected resolver call, received 0 calls.
Missing current contract: expected listed-contract error, none rendered.
Zero reopen: expected exit field "0", received empty string.
```

The page live-refresh regressions failed independently in the combined focused run:

```text
selected far option: expected getOptionChain 1 call, received 2
selected future: expected getFutures 1 call, received 2
```

Zero-exit cross-flow run before the shared predicate:

```text
npm run test:run -- src/lib/strategyMath.test.ts src/components/strategy-builder/PnLTab.test.tsx src/components/trading/ExecuteBasketDialog.test.tsx src/pages/StrategyBuilder.test.tsx
Test Files 4 failed
Tests 4 failed | 36 passed
```

The four failures proved that zero exit still responded to scenarios, remained live/open,
remained executable, and remained in the hydrated margin request.

### GREEN evidence

```text
npm run test:run -- src/components/strategy-builder/EditLegDialog.test.tsx src/components/strategy-builder/ManualLegBuilder.test.tsx src/components/strategy-builder/PnLTab.test.tsx src/components/trading/ExecuteBasketDialog.test.tsx src/pages/StrategyBuilder.test.tsx src/lib/strategyMath.test.ts
Test Files 6 passed
Tests 59 passed

uv run pytest -q test/test_scalping_futures_contracts.py
3 passed
```

### Final verification

```text
npm run test:run
Test Files 26 passed
Tests 383 passed

npm run lint
Checked 384 files. No fixes applied.

npx tsc -b --pretty false
Exit 0

npm run build
3013 modules transformed; built in 3.89s. Exit 0

git diff --check
Exit 0
```

Build-generated `frontend/dist` changes were restored to `HEAD`.

### Remaining concern

No new concern. Futures still use `expiryTs: null` because the master-contract schema has no
authoritative expiry cut-off timestamp; canonical date/symbol/lot/tick and the exact contract quote
remain authoritative.
