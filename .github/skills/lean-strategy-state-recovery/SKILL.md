---
name: lean-strategy-state-recovery
description: "Use when creating, modifying, reviewing, or debugging state persistence and startup recovery in any Lean Python strategy in this repository."
---

# Lean Strategy State Recovery

All Lean Python strategies in this repository must use the shared state helper:

```python
from strategies.python.common.strategy_state import StrategyStateStore
```

`StrategyStateStore` wraps Lean's built-in `self.object_store`. Do not introduce a custom database, filesystem store, cloud store, or broker API client for strategy recovery.

## Initialize State

Create the store during `initialize()` before restoring state:

```python
self.state_store = StrategyStateStore(
    self.object_store,
    "my-strategy-id",
    self.get_parameter("strategy-state-scope") or "paper",
    1,
    self._default_state,
)
self.state_reconciliation_required = False
self.state = self._restore_state()
```

Requirements:

- Use a stable, unique strategy ID.
- Use separate scopes for paper and live deployments.
- Start schema versions at `1` and increment them for incompatible schemas.
- Keep the strategy-owned payload JSON-serializable.
- Include the repository root in `python-additional-paths` when Lean is not launched from the repository root.

## Handle Every Load Outcome

Handle every `StrategyStateStore.load()` result explicitly:

| Status | Required behavior |
| --- | --- |
| `missing` | Use the strategy's default payload. |
| `valid` | Restore the payload, reconstruct subscriptions, and reconcile against Lean state. |
| `corrupt` | Retain the record, log an actionable error, and block new entries. |
| `incompatible` | Retain the record and block new entries until migration or reconciliation succeeds. |

Never silently discard unsafe state or treat it as a clean start.

## Save Durable Transitions

Save immediately after:

- entry intent or submission
- order or brokerage execution ID capture
- partial and complete fills
- exit submission, cancellation, rejection, and completion
- risk-state changes
- migrations and reconciliation outcomes

Use the Lean algorithm timestamp:

```python
self.state_store.save(self.state, self.time.isoformat())
```

## Reconcile Through Lean

The brokerage integration is the account authority. Reconcile recovered state through Lean's imported portfolio, orders, and transactions after brokerage setup completes.

Startup sequence:

1. Load state through `StrategyStateStore`.
2. Recreate required securities and subscriptions.
3. Wait for usable market data when prices are required for reconciliation.
4. Compare recovered ownership with Lean portfolio quantities and tracked orders.
5. Block new entries until reconciliation completes.
6. Mark state flat or closed only after Lean confirms the relevant positions are flat.

Do not issue direct Python REST requests for broker positions when Lean already imports holdings. Never persist credentials, API keys, tokens, account secrets, or raw broker responses.

## Migrate Legacy State

Strategies own payload migrations; the helper owns envelope validation.

For a legacy Object Store key:

1. Load the shared state first.
2. Read the legacy key only when shared state is `missing`.
3. Validate the legacy payload.
4. Save it through `StrategyStateStore` using the current schema.
5. Retain the source record until the migration window is intentionally retired.

Never treat an incompatible payload as a clean start.

## Validate Changes

Add focused tests for missing, valid, corrupt, and incompatible state; supported migrations; restored open positions; and confirmed-flat reconciliation.

Run the shared tests:

```sh
cd /Users/arifkhan/github/lean-strategies
python3 -m unittest -v strategies/python/common/test_strategy_state.py
```

Also run syntax checks and the narrowest applicable tests for every modified strategy.

## Review Checklist

- `StrategyStateStore` is the normal persistence API.
- Strategy ID and deployment scope isolate the key.
- Unsafe restore outcomes fail closed.
- Startup restores subscriptions before reconciliation.
- Reconciliation uses Lean portfolio and order state.
- Material lifecycle transitions are persisted.
- State contains no credentials or raw broker responses.
- Migration and recovery tests cover the change.
