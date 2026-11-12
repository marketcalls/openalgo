# 17 - Amibroker Integration

## Integration Boundary

Amibroker sends order decisions from AFL or an HTTP-capable integration to OpenAlgo's REST API. OpenAlgo does not install an AFL interpreter or expose an `/amibroker` configuration page. The REST contract is the same one used by other external clients.

If Amibroker and OpenAlgo run on the same computer, use `http://127.0.0.1:5000`. For separate computers, use the reachable OpenAlgo host URL. A locally running Amibroker client does not need a public webhook URL merely to reach a server on the same machine.

## Configure the Client

1. Connect the intended broker in OpenAlgo and verify funds and symbol-master readiness.
2. Generate the [OpenAlgo API key](../09-api-key-management/README.md); keep it out of shared AFL files and logs.
3. Set the host URL and send JSON with `Content-Type: application/json` using an HTTP POST implementation supported by your Amibroker version or integration.
4. Translate Amibroker symbols to OpenAlgo's [symbol format](../symbol-format/README.md), including the exchange, expiry and contract quantity.
5. Enable **Analyze** before testing the first signal.

Do not treat an HTTP-open/read helper as a POST function unless its actual API supports a request body and method. Use a maintained integration implementation for that client; the platform's contract below is independent of the chosen HTTP helper.

## Order Request

Send one placement to `POST /api/v1/placeorder`:

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Amibroker",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 1,
  "pricetype": "MARKET",
  "product": "MIS"
}
```

Use [PlaceOrder](../../api/order-management/placeorder.md) for all fields. For position-target behavior, use [Smart Orders](../12-smart-orders/README.md); `position_size=0` is not an idempotent close-only flag when already flat. [Basket Orders](../13-basket-orders/README.md) submit independent legs rather than an atomic transaction.

## Signal and Position Safety

AFL evaluation can happen repeatedly while a bar is forming. Design the sender so one intended signal emits one placement, including after refreshing a chart, restarting the client or running an exploration over several symbols.

A client-local flag or timer records what the script believes happened; it is not the broker's position or a confirmed fill. Reconcile order book, trades and positions on startup and after any unclear response. Coordinate other scripts/manual trades that share the same symbol, exchange and product.

Do not retry placement automatically after a timeout or failed read. The broker may already have accepted it. A response containing `orderid` is an acceptance, not proof of a fill. Semi-Auto success with `pending_order_id` means approval is still needed in [Action Center](../22-action-center/README.md).

## Verify End to End

1. In Analyze, emit one small test signal.
2. Inspect the request and returned JSON, sandbox order/trade/position books, and the client log.
3. Check that repeated evaluations do not create repeated requests.
4. Exercise exits, rejected orders, a lost response and restart recovery before live use.
5. Before switching to Live, reconcile positions and verify account, product, quantity and current contract details.

The client's clock/schedule and the exchange calendar are separate from OpenAlgo's hosted Python scheduler. Do not assume a local scheduler follows Indian holidays or special sessions unless you implemented that behavior.

---

**Previous**: [16 - TradingView Integration](../16-tradingview-integration/README.md)

**Next**: [18 - ChartInk Integration](../18-chartink-integration/README.md)
