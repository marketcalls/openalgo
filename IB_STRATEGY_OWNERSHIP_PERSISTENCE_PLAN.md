# IB Strategy Ownership and Restart Persistence Plan

## Objective

Allow multiple LEAN strategies to trade the same underlying and option chain
without closing or reusing another strategy's positions after a restart.

The SPX 1:45 PM Sandwich strategy will maintain its own trade ledger using:

- A deterministic strategy identifier and trade identifier.
- LEAN order tags.
- Interactive Brokers native execution IDs (`ExecId`).
- LEAN Object Store persistence.
- Account-level IB holdings and open orders as reconciliation inputs.

IB remains the source of truth for actual account quantities and working orders.
Object Store records which account activity this strategy owns.

## Ownership identifiers

Every order created by this strategy will use a tag such as:

```text
SPX145|v1|trade=<trade-id>|role=ENTRY
SPX145|v1|trade=<trade-id>|role=EXIT
```

The trade ID must be unique and stable across restarts. A UUID or UTC timestamp
plus a sequence number is suitable. The Object Store key must be namespaced by
strategy, account, and environment so separate strategies cannot overwrite one
another's state:

```text
ib-ownership/v1/spx-1-45pm-sandwich/<account>/<environment>/ledger.json
```

No credentials or passwords will be stored in the ledger.

## Persisted ledger schema

```json
{
  "schema_version": 1,
  "strategy_id": "spx-1-45pm-sandwich",
  "account": "<account-id>",
  "environment": "paper",
  "updated_at": "<utc-time>",
  "trades": {
    "<trade-id>": {
      "status": "ENTRY_SUBMITTED",
      "entry_order_ids": [],
      "entry_brokerage_ids": [],
      "entry_execution_ids": [],
      "exit_order_ids": [],
      "exit_execution_ids": [],
      "legs": [
        {
          "symbol": "<canonical-contract-symbol>",
          "con_id": "<ib-con-id>",
          "quantity": 0,
          "average_price": 0
        }
      ],
      "created_at": "<utc-time>",
      "last_event_at": "<utc-time>"
    }
  },
  "seen_execution_ids": []
}
```

Trade states will be explicit:

```text
FLAT
ENTRY_SUBMITTED
PARTIALLY_FILLED
OPEN
EXIT_SUBMITTED
CLOSED
RECONCILIATION_REQUIRED
```

## Execution-ID integration

The current LEAN `OrderEvent` contains the LEAN order ID and fill details, but
not the IB native execution ID. The Interactive Brokers brokerage already
receives `Execution.ExecId` internally.

Implement a small cross-repository change:

1. Add an optional brokerage execution-ID field to LEAN `OrderEvent` and its
   serialization path.
2. Set that field in the Interactive Brokers brokerage when creating an order
   fill event from `Execution.ExecId`.
3. Expose the field to Python as `order_event.brokerage_execution_id`.
4. Persist every new execution ID immediately and ignore duplicate IDs during
   reconnect/replay.

Do not parse execution IDs from log messages. Logs are diagnostic and are not a
reliable persistence interface.

## Restart and reconciliation flow

During `Initialize`:

1. Load the namespaced ledger from Object Store.
2. Validate the schema, strategy ID, account, and environment.
3. If the ledger is missing or corrupt, start in a safe reconciliation state.

After brokerage synchronization and warm-up:

1. Read current IB/LEAN holdings and open orders.
2. Match working orders using the strategy tag and persisted brokerage order
   IDs.
3. Match filled activity using persisted execution IDs.
4. Recalculate each owned trade's leg quantities from fills.
5. Compare the owned net quantities with the account-level holdings.
6. Mark unmatched or conflicting quantities as foreign/unattributed.

If an account position cannot be attributed confidently to this strategy, the
strategy must not open another trade or liquidate that position. It should log
`RECONCILIATION_REQUIRED` and expose the condition to Grafana.

## Strategy behavior changes

Replace the account-wide entry guard:

```python
if self.portfolio.invested:
    return
```

with ownership-aware checks:

- Block if this strategy has an `OPEN`, `ENTRY_SUBMITTED`, or
  `RECONCILIATION_REQUIRED` trade.
- Ignore unrelated holdings belonging to another strategy.
- Block if the same option contracts are already claimed by another known
  strategy or if account-level quantities do not reconcile.
- Exit only legs recorded in this strategy's ledger.

Every state transition will save the ledger after order submission, order
status changes, fills, cancellations, and reconciliation.

## Object Store safety

- Use a schema version for forward-compatible migrations.
- Save compact JSON, not raw logs.
- Bound the retained execution-ID history and keep a closed-trade archive or
  rolling checksum to prevent unbounded growth.
- Use separate keys per strategy/account/environment.
- Never allow two instances of the same strategy to write the same ledger key.
- Treat Object Store as durable strategy metadata, not as a replacement for IB
  account reconciliation.

## Grafana additions

Export these strategy-level metrics:

- `lean_owned_trade_state`
- `lean_owned_position_quantity`
- `lean_owned_trade_count`
- `lean_reconciliation_required`
- `lean_last_execution_age_seconds`
- `lean_unattributed_account_quantity`

Add panels for owned trade state, reconciliation warnings, and the latest IB
execution ID. Account-level equity and holdings remain separate panels.

## Validation plan

Test in paper mode with these scenarios:

1. Submit an entry and restart before any fill.
2. Restart after one or more partial fills.
3. Restart after a complete four-leg condor fill.
4. Restart while an exit order is working.
5. Run a second strategy on the same SPX option chain.
6. Introduce unrelated account holdings and verify they do not get closed.
7. Duplicate an execution callback and verify it is ignored.
8. Corrupt or delete the ledger and verify the strategy refuses new orders.

Real-money order placement remains disabled during implementation and testing.
