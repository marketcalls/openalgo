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
| quantity | Order quantity, in units. One lot of 65 is 65 | Mandatory | - |
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

## Examples

Every response in this section is what a running OpenAlgo server answered to
the request shown, under the default brokerage plan (20 per executed order, or
a percentage of the trade value where that is lower). The symbol has to be in
your own master contract, so use a contract that is listed for you: the expiry
dates below are only examples.

### What twelve orders cost

| Order | Exchange | Product | Segment | Trade value | Brokerage | STT or CTT | Stamp duty | Exchange, IPFT and SEBI | GST | Total |
|-------|----------|---------|---------|-------------|-----------|------------|------------|-------------------------|-----|-------|
| BUY 50 RELIANCE at 2500 | NSE | CNC | Equity Delivery | 125000.00 | 20.00 | 125.00 | 19.00 | 3.97 | 4.31 | **172.28** |
| SELL 50 RELIANCE at 2600 | NSE | CNC | Equity Delivery | 130000.00 | 20.00 | 130.00 | 0.00 | 4.12 | 4.34 | **158.46** |
| BUY 50 RELIANCE at 2500 | BSE | CNC | Equity Delivery | 125000.00 | 20.00 | 125.00 | 19.00 | 4.82 | 4.47 | **173.29** |
| BUY 400 SBIN at 1000 | NSE | MIS | Equity Intraday | 400000.00 | 20.00 | 0.00 | 12.00 | 12.68 | 5.88 | **50.56** |
| SELL 400 SBIN at 1100 | NSE | MIS | Equity Intraday | 440000.00 | 20.00 | 110.00 | 0.00 | 13.95 | 6.11 | **150.06** |
| BUY 65 NIFTY29DEC26FUT at 26000 | NFO | NRML | F&O Futures | 1690000.00 | 20.00 | 0.00 | 34.00 | 32.62 | 9.47 | **96.09** |
| SELL 65 NIFTY29DEC26FUT at 26100 | NFO | NRML | F&O Futures | 1696500.00 | 20.00 | 848.00 | 0.00 | 32.75 | 9.50 | **910.25** |
| BUY 65 NIFTY29DEC2626000CE at 120 | NFO | NRML | F&O Options | 7800.00 | 20.00 | 0.00 | 0.00 | 2.78 | 4.10 | **26.88** |
| SELL 65 NIFTY29DEC2626000CE at 135.5 | NFO | NRML | F&O Options | 8807.50 | 20.00 | 13.00 | 0.00 | 3.14 | 4.17 | **40.31** |
| BUY 1000 USDINR29DEC26FUT at 88.5 | CDS | NRML | Currency Futures | 88500.00 | 20.00 | 0.00 | 0.00 | 0.44 | 3.68 | **24.12** |
| SELL 100 CRUDEOIL18DEC26FUT at 5823 | MCX | NRML | Commodity Futures | 582300.00 | 20.00 | 58.23 | 0.00 | 12.81 | 5.91 | **96.95** |
| BUY 1 BTCUSDFUT at 60000 | CRYPTO | NRML | Crypto Futures and Spot | 60.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.00** |

What the table shows:

- **Stamp duty is charged on a buy only**, to the nearest rupee, so on a small
  buy it is 0.00 (the option and the currency rows).
- **STT is charged on a sell**, except on equity delivery, which pays it on
  both sides, and on currency, which pays none.
- **An option is charged on its premium**, so its trade value is the premium
  times the quantity, not the strike.
- **The exchange decides the rate.** The same delivery buy pays 3.71 in
  transaction charges and 0.13 in IPFT levy on NSE, and 4.69 with no
  levy on BSE.
- **STT is rounded to the rupee and CTT is not.** The option sell pays
  13.00 and the commodity sell pays 58.23.
- **Crypto pays nothing** until a venue fee is entered on
  `/sandbox/commissions`.

### An intraday trade, both orders

One request prices one order, so a round trip is two requests. The buy:

Request:

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "product": "MIS",
  "quantity": 400,
  "price": 1000
}
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "action": "BUY",
    "quantity": 400,
    "price": 1000.0,
    "segment": "Equity Intraday",
    "trade_value": 400000.0,
    "charges": {
      "total": 50.56,
      "brokerage": 20.0,
      "taxes": {
        "gst": 5.88,
        "stt": 0.0,
        "stamp_duty": 12.0
      },
      "other_charges": {
        "transaction": 11.88,
        "clearing": 0.0,
        "ipft": 0.4,
        "sebi_turnover": 0.4
      }
    }
  }
}
```

The sell:

Request:

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "SELL",
  "product": "MIS",
  "quantity": 400,
  "price": 1100
}
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "action": "SELL",
    "quantity": 400,
    "price": 1100.0,
    "segment": "Equity Intraday",
    "trade_value": 440000.0,
    "charges": {
      "total": 150.06,
      "brokerage": 20.0,
      "taxes": {
        "gst": 6.11,
        "stt": 110.0,
        "stamp_duty": 0.0
      },
      "other_charges": {
        "transaction": 13.07,
        "clearing": 0.0,
        "ipft": 0.44,
        "sebi_turnover": 0.44
      }
    }
  }
}
```

The two orders cost 50.56 + 150.06 = **200.62**. The gross profit is
(1100 - 1000) x 400 = 40000, so the trade keeps 39799.38. The brokerage
calculator at `/sandbox/calculator` shows the same figures for this trade.

### Selling an option

STT on an option is charged on the sell, on the premium (0.15% of 8807.50
is 13.21, which is 13.00 to the nearest rupee):

Request:

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTY29DEC2626000CE",
  "exchange": "NFO",
  "action": "SELL",
  "product": "NRML",
  "quantity": 65,
  "price": 135.5
}
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "NIFTY29DEC2626000CE",
    "exchange": "NFO",
    "product": "NRML",
    "action": "SELL",
    "quantity": 65,
    "price": 135.5,
    "segment": "F&O Options",
    "trade_value": 8807.5,
    "charges": {
      "total": 40.31,
      "brokerage": 20.0,
      "taxes": {
        "gst": 4.17,
        "stt": 13.0,
        "stamp_duty": 0.0
      },
      "other_charges": {
        "transaction": 3.09,
        "clearing": 0.0,
        "ipft": 0.04,
        "sebi_turnover": 0.01
      }
    }
  }
}
```

### A commodity futures sell

On a commodity exchange `taxes.stt` carries the Commodities Transaction Tax,
kept to the paisa, and there is no IPFT levy:

Request:

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "CRUDEOIL18DEC26FUT",
  "exchange": "MCX",
  "action": "SELL",
  "product": "NRML",
  "quantity": 100,
  "price": 5823
}
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "CRUDEOIL18DEC26FUT",
    "exchange": "MCX",
    "product": "NRML",
    "action": "SELL",
    "quantity": 100,
    "price": 5823.0,
    "segment": "Commodity Futures",
    "trade_value": 582300.0,
    "charges": {
      "total": 96.95,
      "brokerage": 20.0,
      "taxes": {
        "gst": 5.91,
        "stt": 58.23,
        "stamp_duty": 0.0
      },
      "other_charges": {
        "transaction": 12.23,
        "clearing": 0.0,
        "ipft": 0.0,
        "sebi_turnover": 0.58
      }
    }
  }
}
```

### A crypto order

`trade_value` is the price times the quantity times the contract multiplier of
the symbol (60000 x 1 x 0.001 here). Every charge is zero until a venue fee is
entered on `/sandbox/commissions`:

Request:

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "BTCUSDFUT",
  "exchange": "CRYPTO",
  "action": "BUY",
  "product": "NRML",
  "quantity": 1,
  "price": 60000
}
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "BTCUSDFUT",
    "exchange": "CRYPTO",
    "product": "NRML",
    "action": "BUY",
    "quantity": 1,
    "price": 60000.0,
    "segment": "Crypto Futures and Spot",
    "trade_value": 60.0,
    "charges": {
      "total": 0.0,
      "brokerage": 0.0,
      "taxes": {
        "gst": 0.0,
        "stt": 0.0,
        "stamp_duty": 0.0
      },
      "other_charges": {
        "transaction": 0.0,
        "clearing": 0.0,
        "ipft": 0.0,
        "sebi_turnover": 0.0
      }
    }
  }
}
```

### When a request is refused

A key that is not valid (HTTP 403):

```json
{
  "status": "error",
  "message": "Invalid openalgo apikey"
}
```

A symbol that is not in the master contract (HTTP 400):

```json
{
  "status": "error",
  "message": "Symbol NOSUCHSYMBOL not found on NSE"
}
```

An index, which cannot be traded (HTTP 400):

```json
{
  "status": "error",
  "message": "Orders cannot be placed on NSE_INDEX, so no charges apply to it"
}
```

A request with no `price` (HTTP 400):

```json
{
  "status": "error",
  "message": "{'price': ['Missing data for required field.']}"
}
```

A price of zero (HTTP 400):

```json
{
  "status": "error",
  "message": "{'price': ['Price must be a positive number.']}"
}
```

`apikey` is read from the request body. A request that sends the key only in
a header is answered as a request with no key.
