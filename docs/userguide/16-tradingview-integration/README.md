# 16 - TradingView Integration

## Generate the Alert Configuration

Open **Platforms > TradingView** or `/tradingview`. Choose **Strategy Alert** or **Line Alert**, search for the exact OpenAlgo symbol, select its exchange and product, then review **Generated JSON** and the displayed **Webhook URL**.

| Generator mode | Endpoint | Inputs |
|---|---|---|
| Strategy Alert | `/api/v1/placesmartorder` | TradingView strategy order action/contracts and position size |
| Line Alert | `/api/v1/placeorder` | Fixed BUY/SELL and quantity selected in the form |

**Generate JSON** and **Copy** only prepare the configuration; they do not create a TradingView alert or place an order. The generated symbol and exchange are fixed to the instrument you selected, even if the TradingView chart uses a different display name.

## Connect the Alert

1. Connect the intended broker and generate an [OpenAlgo API key](../09-api-key-management/README.md).
2. Configure a reachable installation address in `HOST_SERVER`. TradingView cannot call `localhost` on your machine; use the public URL configured for your deployment.
3. Copy the Webhook URL and Generated JSON from the matching mode.
4. In TradingView, create the intended alert and paste that URL and message. Your account and alert type must support outbound webhooks; check current availability in TradingView.
5. Verify that the alert emits the intended event and that its substitutions resolve to actual values before relying on it.

Follow [Installation](../04-installation/README.md) for the server's domain/reverse-proxy/TLS setup. Tunneling changes reachability; it does not run OpenAlgo for you or automatically restrict access to webhook routes.

## Strategy Alert Payload

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "TradingView Strategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "{{strategy.order.action}}",
  "product": "MIS",
  "pricetype": "MARKET",
  "quantity": "{{strategy.order.contracts}}",
  "position_size": "{{strategy.position_size}}"
}
```

This goes to **placesmartorder**, not placeorder. Read [Smart Orders](../12-smart-orders/README.md): nonzero targets match a position, while zero is not a universal close-only flag when already flat. The broker's net symbol/exchange/product position can also include manual trades or other strategies.

For a Line Alert, the generator emits a regular placeorder request with fixed action/quantity and no position target. Every delivered line alert can submit another order; it is not automatically position-aware.

Use OpenAlgo's [symbol format](../symbol-format/README.md), especially for dated futures/options. Quantities for derivatives are units and must follow the current contract lot size. Do not assume a chart provider's ticker or a strategy's contract count is already correct for the broker instrument.

## Rehearse and Reconcile

1. Enable **Analyze** and verify the header badge.
2. Test one small signal and inspect the sender's delivery result plus OpenAlgo's live/sandbox logs.
3. Check the sandbox order book, trades and resulting position.
4. Test entry, reversal/exit and repeated-alert behavior, including client/server restarts, before Live.
5. Reconcile positions before changing execution mode and verify broker/account, symbol, product and quantity again.

A successful placement/order ID means acceptance, not a fill. Semi-Auto success with `pending_order_id` means approval is still needed in [Action Center](../22-action-center/README.md). A timeout or lost response can occur after broker acceptance; do not resend until orders, trades and positions establish what happened. Smart orders do not deduplicate two separate submissions.

Traffic Logs records request metadata, not payload bodies. Use [Traffic Logs](../26-traffic-logs/README.md) for delivery timing/status and the live or sandbox order logs for trading outcomes. Never publish the webhook JSON's API key in screenshots or logs.

## Managed Batch and Signal Strategies

The generator above sends direct API orders. For configured multi-leg options with RMS, or TradingView signals that start/stop mapped legs, use the separate **Strategies** module at `/strategy`. Its batch and signal webhook contracts are in the [Strategy Module & RMS guide](../../prompt/strategy_rms_documentation.md). Do not send one module's payload to another module's URL.

---

**Previous**: [15 - Analyzer Mode](../15-analyzer-mode/README.md)

**Next**: [17 - Amibroker Integration](../17-amibroker-integration/README.md)
