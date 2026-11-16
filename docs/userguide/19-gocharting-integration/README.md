# 19 - GoCharting Integration

## Generate a Webhook Configuration

Open **Platforms > GoCharting** or `/gocharting`. This page generates a regular MARKET-order webhook payload using the active broker's exchange capabilities and your OpenAlgo API key.

1. Search for the OpenAlgo symbol and choose its exact exchange.
2. Choose the product where shown, action (BUY/SELL) and quantity.
3. Inspect **Generated JSON** and use **Copy**. Generate JSON refreshes the output; it does not send an order.
4. Copy the **Webhook URL**, formed from the installation's `HOST_SERVER` and `/api/v1/placeorder`.
5. Configure the URL and JSON message in a GoCharting alert capable of sending webhooks.

If `HOST_SERVER` is localhost, the page warns that GoCharting cannot reach it. Use a reachable address for the installation and update `HOST_SERVER`; follow your deployment's reverse-proxy/TLS setup. Plan eligibility and alert setup are controlled by GoCharting and can change, so check them in that service.

## Payload

A generated request has this shape:

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "GoCharting Alert",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "product": "MIS",
  "pricetype": "MARKET",
  "quantity": "1"
}
```

Use the exact [OpenAlgo symbol format](../symbol-format/README.md). A chart provider's display name is not necessarily a tradeable OpenAlgo contract. For derivatives, search the current contract and use its current lot size when converting lots to units.

The current generator produces fixed symbol/action/quantity fields. It does not implement a Pine Script runtime or guarantee substitution of TradingView placeholders such as `{{ticker}}` or `{{strategy.position_size}}` by GoCharting. Use only values or placeholders your sender actually emits and inspect a test payload.

For limit/stop orders or position targets, follow the [PlaceOrder](../../api/order-management/placeorder.md) or [PlaceSmartOrder](../../api/order-management/placesmartorder.md) contract and choose the matching endpoint. Editing JSON does not cause OpenAlgo to reinterpret a regular placement URL as a smart order.

## Test and Verify

1. Switch the instance to **Analyze** and verify the badge.
2. Configure one alert with a small quantity and an unambiguous symbol/action.
3. Trigger it and check the sender's delivery result and OpenAlgo logs.
4. Verify the sandbox order book, trades and position. A success/order ID confirms acceptance, not a fill.
5. Exercise the intended exit and repeated-alert behavior before changing to Live.

A repeated alert is a new request and can place another order. A timeout or lost broker response leaves the outcome unclear: reconcile orders, trades and positions before resending. In Semi-Auto, eligible live placements wait in [Action Center](../22-action-center/README.md).

The payload includes your trading API key. Keep alerts and screenshots private, and update every stored alert after regenerating that key.

---

**Previous**: [18 - Chartink Integration](../18-chartink-integration/README.md)

**Next**: [20 - Python Strategies](../20-python-strategies/README.md)
