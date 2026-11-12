# 14 - Positions & Holdings

## Positions and Holdings

**Positions** describe the broker/sandbox position book: intraday equity, derivatives, delivery trades where returned, and crypto derivatives on a compatible broker. Brokers can also return squared-off rows with quantity zero and realized P&L.

**Holdings** describe delivery assets returned by the broker. Availability, average cost and fields vary by adapter. Holdings is hidden in the profile menu for crypto brokers.

Quantity is units, with positive net quantity long, negative short and zero flat. For derivatives, use the contract's current lot size when translating lots into an order quantity; do not assume the position quantity is already a number of lots.

## Positions Page

Open **Positions** in the navigation bar or `/positions`. Read symbol, exchange, product, net quantity, average price, LTP and P&L. Use the page's filters, sorting, Refresh and export controls to inspect the book. Price updates depend on feed availability; use broker books when reconciling a discrepancy.

- **Chart** opens the instrument in `/trading`.
- **Close** on a nonzero row requests a market exit for that symbol, exchange and product. A squared-off row has no Close button.
- **Close All** asks for confirmation and requests exits for the account's open positions. Review all exposure before confirming.

An accepted exit is not proof of a fill. Check the resulting orders, trades and remaining position, including any partial or rejected exit. Read the returned message if Semi-Auto or another service restriction refuses the operation.

The web row-level close is an authenticated session action. It is distinct from public `POST /api/v1/closeposition`, which closes all open positions; adding a symbol to that public request does not make it a single-position close. See [ClosePosition](../../api/order-management/closeposition.md).

## Holdings Page

Open **Holdings** from the profile menu or `/holdings` on a supported broker. It shows the holdings and values returned by the account service and offers export and order actions. Review the instrument, product and quantity in an order dialog before submitting an Add or Exit order.

An unavailable average price does not establish a zero cost basis. Historical analysis of today's holdings is available in [Portfolio Analyzer](../31-tools/README.md#17-portfolio-analyzer-portfolio-analyzer); it is different from a record of your own purchases and realized returns.

## API References

| Task | Reference |
|---|---|
| Read positions | [PositionBook](../../api/account-services/positionbook.md) |
| Read holdings | [Holdings](../../api/account-services/holdings.md) |
| Read a symbol/product's open quantity | [OpenPosition](../../api/order-information/openposition.md) |
| Submit a specific offsetting order | [PlaceOrder](../../api/order-management/placeorder.md) |
| Move toward a target position | [Smart Orders](../12-smart-orders/README.md) |
| Close all open positions | [ClosePosition](../../api/order-management/closeposition.md) |

The `strategy` field labels order provenance; it does not isolate independent positions at the broker. Coordinate scripts that trade the same symbol, exchange and product.

## Mode and Process Changes

Live and Analyze books are separate. Changing mode does not move or close positions. Stopping a strategy process or logging out is also not a position-close instruction. Reconcile positions at the destination where their entries actually went before changing mode, switching brokers or restarting automation.

If an order request loses its response, check the broker's order book, trades and positions before resubmitting. A zero row or stale local view is not a substitute for checking the broker's current state.

---

**Previous**: [13 - Basket Orders](../13-basket-orders/README.md)

**Next**: [15 - Analyzer Mode](../15-analyzer-mode/README.md)
