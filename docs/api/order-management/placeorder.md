# PlaceOrder

Place a new order with the broker.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/placeorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/placeorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/placeorder
```

## Sample API Request (Market Order)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "NHPC",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "1"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/placeorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "NHPC",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "1"
}'
```

## Sample API Response

```json
{
  "orderid": "250408000989443",
  "status": "success"
}
```

## Sample API Request (Limit Order)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "YESBANK",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "LIMIT",
  "product": "MIS",
  "quantity": "1",
  "price": "16",
  "trigger_price": "0",
  "disclosed_quantity": "0"
}
```

## Sample API Response (Limit Order)

```json
{
  "orderid": "250408001003813",
  "status": "success"
}
```

## Sample API Request (Stop-Loss Order)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "RELIANCE",
  "action": "SELL",
  "exchange": "NSE",
  "pricetype": "SL",
  "product": "MIS",
  "quantity": "1",
  "price": "1180",
  "trigger_price": "1185"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier for tracking | Mandatory | - |
| symbol | Trading symbol (e.g., RELIANCE, NIFTY25AUG26FUT) | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| exchange | Exchange code accepted by the shared validation constants | Mandatory | - |
| pricetype | Price type: MARKET, LIMIT, SL, SL-M | Optional | MARKET |
| product | Product type: MIS, CNC, NRML | Optional | MIS |
| quantity | Positive numeric order quantity | Mandatory | - |
| price | Order price (required for LIMIT and SL orders) | Optional | 0 |
| trigger_price | Trigger price (required for SL and SL-M orders) | Optional | 0 |
| disclosed_quantity | Disclosed quantity for iceberg orders | Optional | 0 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| orderid | string | Broker/sandbox order ID on a direct successful placement; absent when queued |
| pending_order_id | integer | Approval record ID when queued in Semi-Auto; not a broker order ID |
| message | string | Queue acknowledgement or error explanation |
| mode | string | `analyze` for sandbox or `semi_auto` for an approval queue; direct live responses may omit it |

## Ambiguous outcomes

A directly executed placement returns `orderid` on success; execution still needs order-status/trade-book confirmation. Semi-Auto also returns `200`, with `mode: "semi_auto"` and `pending_order_id` instead of a broker order ID: it acknowledges an approval record before any broker submission. If the shared transport detects that a write may have reached the broker but its reply was lost, this endpoint returns `502` with `status: "error"` and a message explaining that the order may have been placed. Check the broker order book before sending it again. The endpoint does not provide a universal idempotency key.

A gthread broker-queue refusal returns `429` before sending. See [response and retry conventions](../README.md#order-outcomes-and-retries).

## Notes

- For **MARKET** orders, price and trigger_price are not required
- For **LIMIT** orders, price is required
- For **SL** (Stop-Loss Limit) orders, both price and trigger_price are required
- For **SL-M** (Stop-Loss Market) orders, only trigger_price is required
- The **symbol** must be in OpenAlgo standard format:
  - Equity: `RELIANCE`
  - Futures: `NIFTY25AUG26FUT`
  - Options: `NIFTY25AUG2625000CE`
- Use **MIS** for intraday, **CNC** for equity delivery, **NRML** for F&O overnight positions
- Fractional quantities are accepted only when `exchange` is `CRYPTO`. Other exchanges reject fractional values during schema validation.

---

**Back to**: [API Documentation](../README.md)
