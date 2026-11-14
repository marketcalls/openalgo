# 25 - Latency Monitor

## Open the Monitor

Open **Logs > Latency** or visit `/logs/latency`. The dashboard reads recorded timing data, refreshes every 30 seconds and offers **Refresh** and **Export to CSV**. The export holds the group that is on screen.

## What Is Measured

Every call to the OpenAlgo API is timed, not only orders. For an order the monitor measures OpenAlgo's recorded order request/confirmation path. It does not measure the time until an exchange fill or your TradingView alert's entire journey to the server. A fast confirmation can still describe a rejected or pending order.

## Choose a Group

The buttons at the top pick which calls the page describes, and each shows how many calls it holds. The page opens on **Orders**.

| Group | What it covers | Kept for |
|---|---|---|
| Orders | Placing, changing and cancelling orders, closing positions and GTT orders | All time |
| Account and books | Order status, positions, holdings, funds, margin, and the order, trade and GTT books | 7 days |
| Market data | Quotes, depth and price history | 7 days |
| Options | Option chain, Greeks and option symbol lookups | 7 days |
| Symbols and settings | Symbol search, expiry dates, the market calendar and settings, answered from OpenAlgo's own data | 7 days |
| Tools and alerts | Portfolio, SIP and sector analysis, the strategy module and alert messages | 7 days |
| All calls | Everything together | As above |

Every figure on the page is for the chosen group only. A chart or a scanner makes hundreds of history calls for each order, and a history call returns a large response, so one average across both would describe neither. Read **Orders** for order speed. **All calls** is there for the total, not for a figure to act on.

The **By Endpoint** table lists each endpoint of the group on its own: how many calls, how many failed, the average, the median (P50), the slowest 1% (P99), and how the average splits between the broker and OpenAlgo. The median and the slowest 1% cover the last 30 days.

For **Orders** the page shows orders tracked, success/failure statistics, average confirmation time, the proportion within 150 ms, the latency distribution across every recorded order, the endpoint table, broker comparison and recent orders. The broker table includes average, median (P50), slowest 1% (P99), the 150 ms percentage and sample count. The other groups show calls tracked, the success rate, the average and the median in place of the 150 ms figure, and leave out the performance levels: those describe an order confirmation, and a history download that takes a second is not a slow order. These describe this instance's recorded samples, not a broker speed guarantee or a controlled benchmark between brokers.

Select a recent order or call to inspect its timing breakdown, including the **Broker API Call** and OpenAlgo's validation/response overhead. The broker API duration combines network round-trip and broker processing; this measurement cannot independently separate those components.

The dashboard's performance labels use these thresholds:

| Total time | Label |
|---|---|
| Under 150 ms | Excellent |
| 150 to under 250 ms | Good |
| 250 to under 400 ms | Acceptable |
| 400 ms and above | Slow |

These labels apply to the Orders group only. They are UI classifications, not trading SLAs. Compare like-for-like operations with enough samples and account for network location, time of day, broker throttling and errors.

## Investigate Slow or Failed Requests

1. Inspect the row's status/error and the per-order breakdown.
2. Compare the Broker API Call with application overhead to decide which area to investigate.
3. Cross-check [Traffic Logs](../26-traffic-logs/README.md), live logs and broker order state.
4. If an order response was lost or delayed, reconcile order book, trades and positions before submitting again.

A basket submits independent legs in batches and can take longer than a single order. It does not guarantee a fixed total latency or simultaneous fills. See [Basket Orders](../13-basket-orders/README.md).

Export downloads recorded timing data from the authenticated `/latency/export` route. The supporting browser routes are `/latency/api/logs` and `/latency/api/stats`; they are separate from the public `/api/v1` trading API. Each takes a `group` in the query string.

---

**Previous**: [24 - PnL Tracker](../24-pnl-tracker/README.md)

**Next**: [26 - Traffic Logs](../26-traffic-logs/README.md)
