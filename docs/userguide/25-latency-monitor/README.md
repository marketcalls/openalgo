# 25 - Latency Monitor

## Open the Monitor

Open **Logs > Latency** or visit `/logs/latency`. The dashboard reads recorded order timing data, refreshes every 30 seconds and offers **Refresh** and **Export to CSV**.

## What Is Measured

The monitor measures OpenAlgo's recorded order request/confirmation path. It does not measure the time until an exchange fill or your TradingView alert's entire journey to the server. A fast confirmation can still describe a rejected or pending order.

The page shows total orders tracked, success/failure statistics, average confirmation time, the proportion within 150 ms, latency distribution, broker comparison and recent orders. The broker table includes average, median (P50), worst 1% (P99), the 150 ms percentage and sample count. These describe this instance's recorded samples, not a broker speed guarantee or a controlled benchmark between brokers.

Select a recent order to inspect its timing breakdown, including the **Broker API Call** and OpenAlgo's validation/response overhead. The broker API duration combines network round-trip and broker processing; this measurement cannot independently separate those components.

The dashboard's performance labels use these thresholds:

| Total time | Label |
|---|---|
| Under 150 ms | Excellent |
| 150 to under 250 ms | Good |
| 250 to under 400 ms | Acceptable |
| 400 ms and above | Slow |

These are UI classifications, not trading SLAs. Compare like-for-like operations with enough samples and account for network location, time of day, broker throttling and errors.

## Investigate Slow or Failed Requests

1. Inspect the row's status/error and the per-order breakdown.
2. Compare the Broker API Call with application overhead to decide which area to investigate.
3. Cross-check [Traffic Logs](../26-traffic-logs/README.md), live logs and broker order state.
4. If an order response was lost or delayed, reconcile order book, trades and positions before submitting again.

A basket submits independent legs in batches and can take longer than a single order. It does not guarantee a fixed total latency or simultaneous fills. See [Basket Orders](../13-basket-orders/README.md).

Export downloads recorded timing data from the authenticated `/latency/export` route. The supporting browser routes are `/latency/api/logs` and `/latency/api/stats`; they are separate from the public `/api/v1` trading API.

---

**Previous**: [24 - PnL Tracker](../24-pnl-tracker/README.md)

**Next**: [26 - Traffic Logs](../26-traffic-logs/README.md)
