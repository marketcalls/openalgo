# OpenAlgo Order Placement Test

Throwaway live Lean strategy for testing `Lean.Brokerages.OpenAlgo` order placement.

It submits this sequence when explicitly enabled:

- Buy 1 SBIN share, then sell it after 5 minutes.
- Buy 1 current-month NIFTY future, then sell it after 5 minutes.
- Buy bull call spreads on NIFTY, BANKNIFTY, and SENSEX using the configured strikes, then close the legs after 5 minutes.

Orders are disabled by default. Copy `.env.example` to `.env`, set your OpenAlgo connection values, configure strikes, then enable both order-confirmation flags:

```bash
cp strategies/python/openalgo_order_placement_test/.env.example strategies/python/openalgo_order_placement_test/.env
```

```bash
OPENALGO_PLACE_TEST_ORDERS=true
LIVE_CONFIRM_OPENALGO_ORDER=true
```

Run:

```bash
strategies/python/openalgo_order_placement_test/run-live.sh
```

Dashboard:

```text
http://127.0.0.1:3001/d/openalgo-order-placement-test/openalgo-order-placement-test?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s
```

The strategy-local `.env` overrides repository `.env` values unless you already exported a variable in the shell. Use `OPENALGO_FO_EXPIRY=YYYY-MM-DD` when you need to force the exchange expiry.

Note: the current OpenAlgo symbol mapper routes `Market.India` options/futures to `NFO`. If SENSEX orders require `BFO` in your OpenAlgo server, the brokerage mapper may need a SENSEX-to-BFO routing update.
