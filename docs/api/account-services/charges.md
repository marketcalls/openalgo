# Charges

Brokerage and statutory charges for one order, before it is placed. Useful for
checking what a trade costs, and for working out the price move a strategy
needs before it is in profit.

The charges are worked out by OpenAlgo from the brokerage plan saved on
`/sandbox/commissions` and the published statutory rates. No broker is called,
so the answer is the same in live and analyzer mode and does not depend on
which broker is logged in. They are the figures a sandbox trade of the same
order pays.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/charges
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/charges
Custom Domain:  POST https://<your-custom-domain>/api/v1/charges
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "product": "CNC",
  "quantity": 50,
  "price": 2500
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/charges \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "product": "CNC",
  "quantity": 50,
  "price": 2500
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "CNC",
    "action": "BUY",
    "quantity": 50,
    "price": 2500.0,
    "segment": "Equity Delivery",
    "trade_value": 125000.0,
    "charges": {
      "total": 172.28,
      "brokerage": 20.0,
      "taxes": {
        "gst": 4.31,
        "stt": 125.0,
        "stamp_duty": 19.0
      },
      "other_charges": {
        "transaction": 3.71,
        "clearing": 0.0,
        "ipft": 0.13,
        "sebi_turnover": 0.13
      }
    }
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Trading symbol in OpenAlgo format | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NCO, CRYPTO | Mandatory | - |
| action | BUY or SELL | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| quantity | Order quantity, in units. One lot of 75 is 75 | Mandatory | - |
| price | The price the order would trade at. For a MARKET order, send the last traded price | Mandatory | - |

`price` must be above zero. Every charge is a share of the trade value, so
there is nothing to work out without it. For options, send the premium.

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | The order and its charges |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol, exchange, product, action, quantity, price | - | The order as it was priced |
| segment | string | The rate-card segment the order falls in, for example "Equity Delivery" or "F&O Options" |
| trade_value | number | Price times quantity, times the contract multiplier where the symbol has one |
| charges | object | The charges, described below |

### Charges Object Fields

| Field | Type | Description |
|-------|------|-------------|
| total | number | Everything the order pays: the sum of every line below |
| brokerage | number | Brokerage under the saved plan for the segment |
| taxes.gst | number | GST on brokerage, exchange transaction charges and SEBI fees |
| taxes.stt | number | Securities Transaction Tax, or Commodities Transaction Tax on a commodity exchange |
| taxes.stamp_duty | number | Stamp duty. Charged on a buy only |
| other_charges.transaction | number | Exchange transaction charges |
| other_charges.clearing | number | Clearing charges. Always 0: they are not charged separately |
| other_charges.ipft | number | Investor Protection Fund Trust levy, where the exchange has one |
| other_charges.sebi_turnover | number | SEBI turnover fee |

## Error Responses

| Status | Message | Meaning |
|--------|---------|---------|
| 400 | A validation message naming the field | A field is missing, or is not one of the allowed values |
| 400 | `Symbol <symbol> not found on <exchange>` | The symbol is not in the master contract |
| 400 | `Orders cannot be placed on <exchange>, so no charges apply to it` | The exchange is an index exchange |
| 403 | `Invalid openalgo apikey` | The API key is not valid |

## Notes

- The brokerage is the plan saved on `/sandbox/commissions`. Each segment has an
  amount per executed order and a percentage of the trade value. With both
  set, the lower of the two is charged; with one set, that one is charged.
- The statutory lines use the published rates and cannot be changed. On NSE
  and BSE the product decides the segment: **MIS** is intraday, **CNC** is
  delivery.
- The result is **an estimate of what the trade costs**. It does not depend on
  whether charges are switched on for the sandbox.
- The order is priced as a contract note for that one order: **STT and stamp
  duty to the nearest rupee** (CTT on commodities is kept to the paisa), every
  other line to the paisa, and GST on the brokerage, exchange and SEBI lines as
  printed. `total` is always the sum of the lines. A contract note for a day
  of several orders rounds STT and stamp duty once on the day's total, so it
  can differ from the sum of the orders by a rupee or two.
- **Crypto** is charged nothing by default. Every crypto value is zero until a
  venue fee is entered on `/sandbox/commissions`, and that fee is charged as
  entered with nothing added.
- **Not included:** depository (DP) charges on a delivery sell, and STT on an
  option that is exercised at expiry.
