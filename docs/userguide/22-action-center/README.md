# 22 - Action Center

## Enable Semi-Auto Order Mode

Open **API Key** (`/apikey`) from the profile menu and switch **Order Mode** to **Semi-Auto**. Open **Action Center** from the same menu, or visit `/action-center`. Its **Toggle Order Mode** button returns to API Key settings.

Auto/Semi-Auto and Live/Analyze are separate settings. Supported placements in Semi-Auto are queued for approval. Analyzer execution branches can run directly in the sandbox before live-order approval routing; use [Analyzer Mode](../15-analyzer-mode/README.md) to rehearse and verify the response's mode.

Live regular, smart, basket, split, options, multi-options and GTT placements use the approval queue where their services support it. Read-only account and market-data requests are not queued. Modify, cancel and close-position operations do not become pending approvals; their live service paths can refuse them in Semi-Auto. Check the relevant [order-management API reference](../../api/README.md) before depending on an automated exit or cancellation.

A queued placement responds with `mode: "semi_auto"` and a `pending_order_id`. That ID identifies an approval record, not a broker order or a completed trade.

## Review Orders

The page has **Pending**, **Approved**, **Rejected** and **All Orders** tabs. Its cards show pending approvals, buy orders, sell orders, approved orders and rejected orders.

Each row shows the strategy/API type, symbol, exchange, side, quantity, price, order type, product and creation time. Expand the row to inspect the original order data and, for a basket, every leg. Review the instrument, size and whether the signal is still valid before approving.

The current page offers approval and rejection; it does not have a Modify or Save & Approve form. Reject a wrong request and have its source submit a corrected request after checking that it was never sent.

## Actions

| Action | What it does |
|---|---|
| Approve (check mark) | Claims the pending request and sends it through its order service |
| Reject (cross) | Rejects a still-pending request without sending it |
| Approve All | Approves pending requests in a batch; review all pending rows first |
| Refresh | Rereads the current list and statistics |
| Delete (trash) | Removes an approved or rejected approval record after confirmation |

Approval is distinct from a fill. A limit order can remain open, a broker can reject a submitted order, and a basket or split can have partial results. Check the broker order ID/status and the order book, trade book and positions.

Deleting a record does not cancel a broker order or close a position. Preserve records whose outcomes you are still investigating.

## Sending and Status Unclear

OpenAlgo claims each approved record for sending at most once. Two tabs approving the same record cannot intentionally send it twice. This does not deduplicate two separate requests that your integration submits.

An approved row whose send has begun but has no broker answer recorded shows **Sending** during the first two minutes. It then shows **Status unclear** and a notice that the order may still be sending. Split and basket requests can take longer than two minutes; elapsed time is not proof that sending stopped. An interruption can also leave this state behind.

When the status is unclear:

1. Check the broker's own order book, trades and positions for every affected leg.
2. Refresh Action Center and inspect the application logs.
3. Reconcile the actual outcome before submitting any replacement. Do not place the order again while its status is unclear.

**A lost broker response still needs reconciliation even if the recorded broker status says rejected or the approval response says execution failed.** Some execution error paths record a rejection after an ambiguous upstream response; that label alone does not prove the broker received nothing.

If OpenAlgo determines a request was never sent and returns it to Pending, read the refusal and correct its cause before approving again. An Approved label alone does not prove execution succeeded.

## Notifications and Monitoring

The page uses the shared Socket.IO connection to update new requests and decisions and plays a sound for a newly queued order. Notification preferences for Action Center are in Profile. Keep the page visible while relying on manual approval, and use Refresh after a connection problem.

There is no separate public SDK approval API in the Python client. The page's authenticated, CSRF-protected browser routes live under `/action-center`; they use your application session rather than the public `/api/v1` API key interface.

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing in Pending | API Key's order mode, the response's mode, and the selected status tab |
| Approval refused as already handled | Refresh; another tab may have approved or rejected it |
| Approved but no confirmed order | Expand the record and reconcile broker orders, trades and positions |
| Order parameters wrong | Reject while pending, then correct the source request |
| Cannot modify/cancel/close through API | Check Semi-Auto restrictions in that operation's reference |
| Updates stopped | Check the connection and Refresh before acting again |

OpenAlgo remains a single-user, one-broker deployment. Action Center does not add multi-account management or automatic quantity/value thresholds for choosing Auto versus Semi-Auto.

---

**Previous**: [21 - Flow Visual Builder](../21-flow-visual-builder/README.md)

**Next**: [23 - Telegram Bot](../23-telegram-bot/README.md)
