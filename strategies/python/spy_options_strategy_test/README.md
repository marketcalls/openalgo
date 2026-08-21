# SPY Options Strategy Placement Test

Live-paper Lean strategy for checking whether SPY option strategy orders can be submitted through the configured brokerage.

Supported test modes:

- `covered_call`
- `iron_butterfly`
- `iron_butterfly_0dte`

The default mode is `iron_butterfly_0dte`. Order placement is disabled by default. Copy `.env.example` to `.env` in this folder and set `SPY_OPTIONS_PLACE_TEST_ORDER=true` when you want the strategy to place the paper test order.

When started after the market is already open, Lean may not emit the canonical SPY option universe immediately. The strategy therefore falls back to `OptionChainProvider`, manually subscribes the selected option legs, and places the test order only after the subscribed legs have live prices.

Run:

```bash
strategies/python/spy_options_strategy_test/run-live.sh
```

Dashboard:

```text
http://127.0.0.1:3001/d/spy-options-strategy-test/spy-options-strategy-test?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s
```

Strategy-local `.env` values override repository-level `.env` values, so this folder can use its own `IB_CLIENT_ID`, test mode, quantity, hold time, and exporter port without changing global settings.
