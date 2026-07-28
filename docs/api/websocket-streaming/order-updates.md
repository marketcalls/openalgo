# Order Updates (WebSocket)

Subscribe to real-time order status updates via WebSocket — fills, partial
fills, rejections, and cancellations pushed by the broker (live mode) or the
sandbox engine (analyze mode). This is an **account-level** stream: no
symbols or modes are involved; one subscription covers every order in the
connected account, from any origin (OpenAlgo API, the broker's own app or
website, engine-internal square-offs).

## WebSocket URL

```
Local Host   :  ws://127.0.0.1:8765
Custom Host  :  ws://<your-host>:8765
```

## Subscribe to Order Updates

Authenticate first, then send:

### Subscribe Message

```json
{
  "action": "subscribe_orders",
  "request_id": "orders-1"
}
```

### Subscribe Acknowledgement

```json
{
  "type": "subscribe_orders",
  "status": "success",
  "message": "Subscribed to order updates",
  "request_id": "orders-1"
}
```

## Order Update Message

Every field uses OpenAlgo's common order constants: `symbol` in OpenAlgo
format (e.g. `NIFTY28JUL26FUT`, mapped from the broker's own symbology),
`action` `BUY`/`SELL`, `pricetype` `MARKET`/`LIMIT`/`SL`/`SL-M`, `product`
`CNC`/`NRML`/`MIS`, and lowercase `order_status`
(`open`/`trigger pending`/`complete`/`rejected`/`cancelled`, plus broker extras such as
`expired`). `mode` is `live` for broker-pushed events and `analyze` for
sandbox events.

```json
{
  "type": "order_update",
  "user_id": "rajandran",
  "mode": "analyze",
  "broker": "sandbox",
  "orderid": "26071590395364",
  "symbol": "NIFTY28JUL26FUT",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": 65,
  "price": 24077.8,
  "trigger_price": 0.0,
  "pricetype": "MARKET",
  "product": "NRML",
  "order_status": "complete",
  "filled_quantity": 65,
  "pending_quantity": 0,
  "average_price": 24077.8,
  "rejection_reason": ""
}
```

A live rejection example (pushed by the broker's own order feed):

```json
{
  "type": "order_update",
  "mode": "live",
  "broker": "upstox",
  "orderid": "260715000344871",
  "symbol": "NHPC",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 1,
  "pricetype": "LIMIT",
  "product": "CNC",
  "order_status": "rejected",
  "rejection_reason": "RMS:Rule: Check circuit limit including square off order exceeds : Circuit breach, Order Price :50.00, Low Price Range:70.90 High Price Range:86.64 ..."
}
```

## Unsubscribe

```json
{
  "action": "unsubscribe_orders"
}
```

### Unsubscribe Acknowledgement

```json
{
  "type": "unsubscribe_orders",
  "status": "success",
  "message": "Unsubscribed from order updates"
}
```

## Sources and Broker Coverage

- **Dedicated order feed / ticker postback**: Zerodha, Dhan, Fyers, Upstox,
  AliceBlue, Definedge, IndMoney, Angel One, Nubra, Arrow stream natively via
  each broker's push channel (`broker/*/streaming/*_order_adapter.py`).
- **REST polling fallback**: brokers with no push mechanism (e.g. Groww) are
  covered by server-side orderbook polling (`ORDER_POLL_INTERVAL`, default 5s).
- **HTTPS postbacks**: `/postback/<broker>` webhook receivers feed the same
  stream on production deployments (public HTTPS URL required by brokers).
  Postback coverage is broker-defined and can be narrower than the WebSocket
  source — e.g. Zerodha postbacks fire only for orders placed through your
  API key and omit intermediate states such as `open`, while the ticker
  WebSocket covers all order origins with the full lifecycle. The WS adapter
  is therefore the more complete source; postbacks are a parallel inlet, not
  a fallback.
- Sandbox (analyze mode) emits the same messages for order placements
  (open), engine fills, rejections, and cancellations — test end-to-end without a live broker.

If both a broker WebSocket and a postback are configured, the same transition
may be delivered twice — deduplicate on `orderid` + `order_status` +
`filled_quantity`. The adapter lifecycle is automatic: it starts on broker
login, restarts on real token changes (daily rollover), and stops on logout.
Disable globally with `ORDER_UPDATES_ENABLED=FALSE`.
