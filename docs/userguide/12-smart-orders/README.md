# 12 - Smart Orders

## Match a Position Target

`POST /api/v1/placesmartorder` reads the current position for a symbol, exchange and product and calculates an order to move it toward `position_size`.

For a **nonzero target**, positive means long and negative means short:

| Current position | Target | Order needed |
|---:|---:|---|
| 0 | +100 | BUY 100 |
| +100 | +100 | No action |
| +100 | +200 | BUY 100 |
| +100 | -100 | SELL 200 |
| -100 | +100 | BUY 200 |

These are required order quantities, not a guarantee of fills. A rejected, pending or partially filled order means the actual position may still differ from the target.

## Zero Is Not a Universal Close-Only Flag

`position_size=0` can close an existing position, but when already flat, broker smart-order implementations can place the supplied `action` and `quantity`. For example, a flat account with `position_size=0`, `action=BUY` and `quantity=100` can open a new long position.

Do not repeatedly send a zero-target request believing it is an idempotent exit. Reconcile the position first and use the intended close workflow. The public [ClosePosition API](../../api/order-management/closeposition.md) closes the account's open positions; it is not a single-symbol exit endpoint. The Positions page has a separate row-level Close action.

A `strategy` label identifies the source of an order. It does not partition the broker's net position into isolated strategy accounts. Two systems trading the same symbol, exchange and product can affect the position a smart order reads.

## Request and SDK

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "TargetPosition",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 1,
  "position_size": 1,
  "pricetype": "MARKET",
  "product": "MIS"
}
```

The Python method is `client.placesmartorder(...)`; the SDK uses `price_type` while REST JSON uses `pricetype`. See the [PlaceSmartOrder reference](../../api/order-management/placesmartorder.md) and [Python SDK](<../../prompt/openalgo python sdk.md>) for the maintained contracts.

## Verify the Outcome

- Rehearse in **Analyze** and inspect the sandbox order/trade/position books.
- A successful response with an order ID is an acceptance, not a fill. A matching position can instead return a no-action message.
- In Semi-Auto, an eligible request is queued for approval; inspect [Action Center](../22-action-center/README.md).
- A position-book failure is not proof that the position is zero.
- A timeout, missing response or detected lost broker response means an order may already exist. Check orders, trades and positions before retrying; smart orders do not replace outcome reconciliation.
- Whole-unit quantities are required outside `CRYPTO`; broker instruments and product rules still apply.

---

**Previous**: [11 - Order Types](../11-order-types/README.md)

**Next**: [13 - Basket Orders](../13-basket-orders/README.md)
