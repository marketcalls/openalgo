# OpenAlgo Services Documentation

## Overview

OpenAlgo Services are Python functions that provide programmatic access to trading operations. These services mirror the functionality of the OpenAlgo SDK but are designed for internal use within the OpenAlgo application. Each service function accepts the same request parameters and returns the same responses as documented in the OpenAlgo SDK.

## Table of Contents

1. [Order Management Services](#order-management-services)
   - [PlaceOrder](#placeorder)
   - [PlaceSmartOrder](#placesmartorder)
   - [OptionsOrder](#optionsorder)
   - [OptionsMultiOrder](#optionsmultiorder)
   - [BasketOrder](#basketorder)
   - [SplitOrder](#splitorder)
   - [ModifyOrder](#modifyorder)
   - [CancelOrder](#cancelorder)
   - [CancelAllOrder](#cancelallorder)
   - [ClosePosition](#closeposition)
2. [Order Information Services](#order-information-services)
   - [OrderStatus](#orderstatus)
   - [OpenPosition](#openposition)
3. [Market Data Services](#market-data-services)
   - [Quotes](#quotes)
   - [MultiQuotes](#multiquotes)
   - [Depth](#depth)
   - [History](#history)
   - [Intervals](#intervals)
4. [Symbol Services](#symbol-services)
   - [Symbol](#symbol)
   - [Search](#search)
   - [Expiry](#expiry)
   - [Instruments](#instruments)
5. [Options Services](#options-services)
   - [OptionSymbol](#optionsymbol)
   - [OptionChain](#optionchain)
   - [SyntheticFuture](#syntheticfuture)
   - [OptionGreeks](#optiongreeks)
6. [Account Services](#account-services)
   - [Funds](#funds)
   - [Margin](#margin)
   - [OrderBook](#orderbook)
   - [TradeBook](#tradebook)
   - [PositionBook](#positionbook)
   - [Holdings](#holdings)
7. [Market Calendar Services](#market-calendar-services)
   - [Holidays](#holidays)
   - [Timings](#timings)
   - [CheckHoliday](#checkholiday)
8. [Analyzer Services](#analyzer-services)
   - [AnalyzerStatus](#analyzerstatus)
   - [AnalyzerToggle](#analyzertoggle)
9. [Telegram Service](#telegram-service)
   - [TelegramAlertService](#telegramalertservice)

---

## Order Management Services

### PlaceOrder

Place a new order with the broker.

**Function:** `place_order(order_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/place_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_data | dict | Yes | Order details |
| api_key | str | Conditional | OpenAlgo API key (for API-based calls) |
| auth_token | str | Conditional | Direct broker authentication token (for internal calls) |
| broker | str | Conditional | Broker name (for internal calls) |

**Order Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| strategy | str | Yes | Strategy identifier |
| symbol | str | Yes | Trading symbol |
| action | str | Yes | BUY or SELL |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| price_type | str | Yes | MARKET, LIMIT, SL, SL-M |
| product | str | Yes | MIS, CNC, NRML |
| quantity | int/str | Yes | Order quantity |
| price | float/str | No | Order price (for LIMIT orders) |
| trigger_price | float/str | No | Trigger price (for SL orders) |
| disclosed_quantity | int/str | No | Disclosed quantity |

**Example - Market Order:**

```python
from services.place_order_service import place_order

order_data = {
    "strategy": "Python",
    "symbol": "NHPC",
    "action": "BUY",
    "exchange": "NSE",
    "price_type": "MARKET",
    "product": "MIS",
    "quantity": 1
}

success, response, status_code = place_order(
    order_data=order_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "orderid": "250408000989443",
  "status": "success"
}
```

**Example - Limit Order:**

```python
from services.place_order_service import place_order

order_data = {
    "strategy": "Python",
    "symbol": "YESBANK",
    "action": "BUY",
    "exchange": "NSE",
    "price_type": "LIMIT",
    "product": "MIS",
    "quantity": "1",
    "price": "16",
    "trigger_price": "0",
    "disclosed_quantity": "0"
}

success, response, status_code = place_order(
    order_data=order_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "orderid": "250408001003813",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with orderid and status
- `status_code` (int): HTTP status code

---

### PlaceSmartOrder

Place a smart order that considers current position size.

**Function:** `place_smart_order(order_data, api_key=None, auth_token=None, broker=None, smart_order_delay=None)`

**Location:** `openalgo/services/place_smart_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_data | dict | Yes | Smart order details |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |
| smart_order_delay | str | No | Delay in seconds (default: 0.5) |

**Order Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| strategy | str | Yes | Strategy identifier |
| symbol | str | Yes | Trading symbol |
| action | str | Yes | BUY or SELL |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| price_type | str | Yes | MARKET, LIMIT, SL, SL-M |
| product | str | Yes | MIS, CNC, NRML |
| quantity | int/str | Yes | Order quantity |
| position_size | int | Yes | Target position size |
| price | float/str | No | Order price (for LIMIT orders) |

**Example:**

```python
from services.place_smart_order_service import place_smart_order

order_data = {
    "strategy": "Python",
    "symbol": "TATAMOTORS",
    "action": "SELL",
    "exchange": "NSE",
    "price_type": "MARKET",
    "product": "MIS",
    "quantity": 1,
    "position_size": 5
}

success, response, status_code = place_smart_order(
    order_data=order_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "orderid": "250408000997543",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data
- `status_code` (int): HTTP status code

---

### OptionsOrder

Place an options order by resolving the symbol from offset (ATM/ITM/OTM) and placing the order.

**Function:** `place_options_order(options_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/place_options_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| options_data | dict | Yes | Options order details |
| api_key | str | Conditional | OpenAlgo API key (for API-based calls) |
| auth_token | str | Conditional | Direct broker authentication token (for internal calls) |
| broker | str | Conditional | Broker name (for internal calls) |

**Options Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| underlying | str | Yes | Underlying symbol (e.g., NIFTY, BANKNIFTY) |
| exchange | str | Yes | Exchange (NSE_INDEX, BSE_INDEX, NFO, BFO) |
| expiry_date | str | Yes | Expiry date in DDMMMYY format (e.g., 28OCT25) |
| offset | str | Yes | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50) |
| option_type | str | Yes | CE or PE |
| action | str | Yes | BUY or SELL |
| quantity | int | Yes | Order quantity |
| pricetype | str | Yes | MARKET, LIMIT, SL, SL-M |
| product | str | Yes | MIS or NRML |
| strategy | str | No | Strategy identifier |
| splitsize | int | No | Split large orders (0 = no split) |
| price | float | No | Limit price (for LIMIT orders) |
| trigger_price | float | No | Trigger price (for SL orders) |

**Example - ATM Options Order:**

```python
from services.place_options_order_service import place_options_order

options_data = {
    "strategy": "python",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28OCT25",
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "NRML",
    "splitsize": 0
}

success, response, status_code = place_options_order(
    options_data=options_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "exchange": "NFO",
  "offset": "ATM",
  "option_type": "CE",
  "orderid": "25102800000006",
  "status": "success",
  "symbol": "NIFTY28OCT2525950CE",
  "underlying": "NIFTY28OCT25FUT",
  "underlying_ltp": 25966.05
}
```

**Example - ITM Options Order:**

```python
options_data = {
    "strategy": "python",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28OCT25",
    "offset": "ITM4",
    "option_type": "PE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "NRML",
    "splitsize": 0
}

success, response, status_code = place_options_order(
    options_data=options_data,
    api_key='your_api_key_here'
)
```

**Response:**

```json
{
  "exchange": "NFO",
  "offset": "ITM4",
  "option_type": "PE",
  "orderid": "25102800000007",
  "status": "success",
  "symbol": "NIFTY28OCT2526150PE",
  "underlying": "NIFTY28OCT25FUT",
  "underlying_ltp": 25966.05
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with orderid, symbol, and underlying details
- `status_code` (int): HTTP status code

---

### OptionsMultiOrder

Place multiple option legs with common underlying. BUY legs execute first for margin efficiency.

**Function:** `place_options_multiorder(multiorder_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/options_multiorder_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| multiorder_data | dict | Yes | Multi-order details with legs |
| api_key | str | Conditional | OpenAlgo API key (for API-based calls) |
| auth_token | str | Conditional | Direct broker authentication token (for internal calls) |
| broker | str | Conditional | Broker name (for internal calls) |

**MultiOrder Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| strategy | str | No | Strategy identifier |
| underlying | str | Yes | Underlying symbol (e.g., NIFTY) |
| exchange | str | Yes | Exchange (NSE_INDEX, BSE_INDEX) |
| expiry_date | str | No | Common expiry date (can be overridden per leg) |
| legs | array | Yes | Array of leg objects |

**Leg Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| offset | str | Yes | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50) |
| option_type | str | Yes | CE or PE |
| action | str | Yes | BUY or SELL |
| quantity | int | Yes | Order quantity |
| expiry_date | str | No | Leg-specific expiry (for diagonal spreads) |
| pricetype | str | No | MARKET (default), LIMIT |
| product | str | No | MIS, NRML (default) |
| splitsize | int | No | Split size for this leg |

**Example - Iron Condor (Same Expiry):**

```python
from services.options_multiorder_service import place_options_multiorder

multiorder_data = {
    "strategy": "Iron Condor Test",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "25NOV25",
    "legs": [
        {"offset": "OTM6", "option_type": "CE", "action": "BUY", "quantity": 75},
        {"offset": "OTM6", "option_type": "PE", "action": "BUY", "quantity": 75},
        {"offset": "OTM4", "option_type": "CE", "action": "SELL", "quantity": 75},
        {"offset": "OTM4", "option_type": "PE", "action": "SELL", "quantity": 75}
    ]
}

success, response, status_code = place_options_multiorder(
    multiorder_data=multiorder_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 26050.45,
    "results": [
        {
            "action": "BUY",
            "leg": 1,
            "mode": "analyze",
            "offset": "OTM6",
            "option_type": "CE",
            "orderid": "25111996859688",
            "status": "success",
            "symbol": "NIFTY25NOV2526350CE"
        },
        {
            "action": "BUY",
            "leg": 2,
            "mode": "analyze",
            "offset": "OTM6",
            "option_type": "PE",
            "orderid": "25111996042210",
            "status": "success",
            "symbol": "NIFTY25NOV2525750PE"
        },
        {
            "action": "SELL",
            "leg": 3,
            "mode": "analyze",
            "offset": "OTM4",
            "option_type": "CE",
            "orderid": "25111922189638",
            "status": "success",
            "symbol": "NIFTY25NOV2526250CE"
        },
        {
            "action": "SELL",
            "leg": 4,
            "mode": "analyze",
            "offset": "OTM4",
            "option_type": "PE",
            "orderid": "25111919252668",
            "status": "success",
            "symbol": "NIFTY25NOV2525850PE"
        }
    ]
}
```

**Example - Diagonal Spread (Different Expiry):**

```python
multiorder_data = {
    "strategy": "Diagonal Spread Test",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25"},
        {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "25NOV25"}
    ]
}

success, response, status_code = place_options_multiorder(
    multiorder_data=multiorder_data,
    api_key='your_api_key_here'
)
```

**Response:**

```json
{
    "results": [
        {
            "action": "BUY",
            "leg": 1,
            "mode": "analyze",
            "offset": "ITM2",
            "option_type": "CE",
            "orderid": "25111933337854",
            "status": "success",
            "symbol": "NIFTY30DEC2525950CE"
        },
        {
            "action": "SELL",
            "leg": 2,
            "mode": "analyze",
            "offset": "OTM2",
            "option_type": "CE",
            "orderid": "25111957475473",
            "status": "success",
            "symbol": "NIFTY25NOV2526150CE"
        }
    ],
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 26052.65
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with results array
- `status_code` (int): HTTP status code

**Note:** BUY legs are always executed before SELL legs for margin efficiency.

---

### BasketOrder

Place multiple orders simultaneously.

**Function:** `place_basket_order(basket_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/basket_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| basket_data | dict | Yes | Basket order details with orders array |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Basket Data Structure:**

```python
{
    "strategy": "Strategy Name",
    "orders": [
        {
            "symbol": "BHEL",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "pricetype": "MARKET",
            "product": "MIS"
        },
        {
            "symbol": "ZOMATO",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": 1,
            "pricetype": "MARKET",
            "product": "MIS"
        }
    ]
}
```

**Example:**

```python
from services.basket_order_service import place_basket_order

basket_data = {
    "strategy": "Python",
    "orders": [
        {
            "symbol": "BHEL",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "pricetype": "MARKET",
            "product": "MIS"
        },
        {
            "symbol": "ZOMATO",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": 1,
            "pricetype": "MARKET",
            "product": "MIS"
        }
    ]
}

success, response, status_code = place_basket_order(
    basket_data=basket_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "results": [
    {
      "symbol": "BHEL",
      "status": "success",
      "orderid": "250408000999544"
    },
    {
      "symbol": "ZOMATO",
      "status": "success",
      "orderid": "250408000997545"
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with results array
- `status_code` (int): HTTP status code

---

### SplitOrder

Split a large order into multiple smaller orders.

**Function:** `split_order(split_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/split_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| split_data | dict | Yes | Split order details |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Split Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| action | str | Yes | BUY or SELL |
| quantity | int | Yes | Total quantity to split |
| splitsize | int | Yes | Size of each split order |
| price_type | str | Yes | MARKET, LIMIT, SL, SL-M |
| product | str | Yes | MIS, CNC, NRML |
| price | float/str | No | Order price (for LIMIT orders) |

**Example:**

```python
from services.split_order_service import split_order

split_data = {
    "symbol": "YESBANK",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 105,
    "splitsize": 20,
    "price_type": "MARKET",
    "product": "MIS"
}

success, response, status_code = split_order(
    split_data=split_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "split_size": 20,
  "total_quantity": 105,
  "results": [
    {
      "order_num": 1,
      "orderid": "250408001021467",
      "quantity": 20,
      "status": "success"
    },
    {
      "order_num": 2,
      "orderid": "250408001021459",
      "quantity": 20,
      "status": "success"
    },
    {
      "order_num": 3,
      "orderid": "250408001021466",
      "quantity": 20,
      "status": "success"
    },
    {
      "order_num": 4,
      "orderid": "250408001021470",
      "quantity": 20,
      "status": "success"
    },
    {
      "order_num": 5,
      "orderid": "250408001021471",
      "quantity": 20,
      "status": "success"
    },
    {
      "order_num": 6,
      "orderid": "250408001021472",
      "quantity": 5,
      "status": "success"
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with split details
- `status_code` (int): HTTP status code

**Note:** Maximum 100 orders allowed per split.

---

### ModifyOrder

Modify an existing order.

**Function:** `modify_order(order_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/modify_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_data | dict | Yes | Modified order details |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Order Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| orderid | str | Yes | Order ID to modify |
| strategy | str | No | Strategy identifier |
| symbol | str | Yes | Trading symbol |
| action | str | Yes | BUY or SELL |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| price_type | str | Yes | MARKET, LIMIT, SL, SL-M |
| product | str | Yes | MIS, CNC, NRML |
| quantity | int/str | Yes | New order quantity |
| price | float/str | Yes | New order price |

**Example:**

```python
from services.modify_order_service import modify_order

order_data = {
    "orderid": "250408001002736",
    "strategy": "Python",
    "symbol": "YESBANK",
    "action": "BUY",
    "exchange": "NSE",
    "price_type": "LIMIT",
    "product": "CNC",
    "quantity": 1,
    "price": 16.5
}

success, response, status_code = modify_order(
    order_data=order_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "orderid": "250408001002736",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data
- `status_code` (int): HTTP status code

---

### CancelOrder

Cancel an existing order.

**Function:** `cancel_order(orderid, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/cancel_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| orderid | str | Yes | Order ID to cancel |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.cancel_order_service import cancel_order

success, response, status_code = cancel_order(
    orderid="250408001002736",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "orderid": "250408001002736",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data
- `status_code` (int): HTTP status code

---

### CancelAllOrder

Cancel all open orders and trigger pending orders.

**Function:** `cancel_all_orders(order_data=None, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/cancel_all_order_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_data | dict | No | Additional order data (optional) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.cancel_all_order_service import cancel_all_orders

success, response, status_code = cancel_all_orders(
    order_data={"strategy": "Python"},
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "message": "Canceled 5 orders. Failed to cancel 0 orders.",
  "canceled_orders": [
    "250408001042620",
    "250408001042667",
    "250408001042642",
    "250408001043015",
    "250408001043386"
  ],
  "failed_cancellations": []
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with canceled and failed lists
- `status_code` (int): HTTP status code

---

### ClosePosition

Close all open positions across various exchanges.

**Function:** `close_position(position_data=None, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/close_position_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| position_data | dict | No | Additional position data (optional) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.close_position_service import close_position

success, response, status_code = close_position(
    position_data={"strategy": "Python"},
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "message": "All Open Positions Squared Off",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data
- `status_code` (int): HTTP status code

---

## Order Information Services

### OrderStatus

Get the current status of an order.

**Function:** `get_order_status(status_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/orderstatus_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status_data | dict | Yes | Order status request data |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Status Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| orderid | str | Yes | Order ID to query |
| strategy | str | No | Strategy identifier |

**Example:**

```python
from services.orderstatus_service import get_order_status

status_data = {
    "orderid": "250828000185002",
    "strategy": "Test Strategy"
}

success, response, status_code = get_order_status(
    status_data=status_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "data": {
    "action": "BUY",
    "average_price": 18.95,
    "exchange": "NSE",
    "order_status": "complete",
    "orderid": "250828000185002",
    "price": 0,
    "pricetype": "MARKET",
    "product": "MIS",
    "quantity": "1",
    "symbol": "YESBANK",
    "timestamp": "28-Aug-2025 09:59:10",
    "trigger_price": 0
  },
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with order details
- `status_code` (int): HTTP status code

---

### OpenPosition

Get the current open position for a symbol.

**Function:** `get_open_position(position_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/openposition_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| position_data | dict | Yes | Position query data |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Position Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| product | str | Yes | MIS, CNC, NRML |
| strategy | str | No | Strategy identifier |

**Example:**

```python
from services.openposition_service import get_open_position

position_data = {
    "symbol": "YESBANK",
    "exchange": "NSE",
    "product": "MIS",
    "strategy": "Test Strategy"
}

success, response, status_code = get_open_position(
    position_data=position_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "quantity": "-10",
  "status": "success"
}
```

**Note:** The service internally fetches the positionbook and filters by symbol, exchange, and product. Returns 0 if position not found.

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with position quantity
- `status_code` (int): HTTP status code

---

## Market Data Services

### Quotes

Get market quotes for a symbol.

**Function:** `get_quotes(symbol, exchange, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/quotes_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.quotes_service import get_quotes

success, response, status_code = get_quotes(
    symbol="RELIANCE",
    exchange="NSE",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "ltp": 1187.75,
    "ask": 1188.0,
    "bid": 1187.85,
    "prev_close": 1165.7,
    "volume": 14414545
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with quote information
- `status_code` (int): HTTP status code

---

### MultiQuotes

Get real-time quotes for multiple symbols in a single call.

**Function:** `get_multiquotes(symbols, api_key=None, auth_token=None, feed_token=None, broker=None)`

**Location:** `openalgo/services/quotes_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbols | list | Yes | List of dicts with 'symbol' and 'exchange' keys |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| feed_token | str | Conditional | Direct broker feed token |
| broker | str | Conditional | Broker name |

**Symbols List Structure:**

```python
[
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
]
```

**Example:**

```python
from services.quotes_service import get_multiquotes

symbols = [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
]

success, response, status_code = get_multiquotes(
    symbols=symbols,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "results": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "data": {
        "open": 1542.3,
        "high": 1571.6,
        "low": 1540.5,
        "ltp": 1569.9,
        "prev_close": 1539.7,
        "ask": 1569.9,
        "bid": 0,
        "oi": 0,
        "volume": 14054299
      }
    },
    {
      "symbol": "TCS",
      "exchange": "NSE",
      "data": {
        "open": 3118.8,
        "high": 3178,
        "low": 3117,
        "ltp": 3162.9,
        "prev_close": 3119.2,
        "ask": 0,
        "bid": 3162.9,
        "oi": 0,
        "volume": 2508527
      }
    },
    {
      "symbol": "INFY",
      "exchange": "NSE",
      "data": {
        "open": 1532.1,
        "high": 1560.3,
        "low": 1532.1,
        "ltp": 1557.9,
        "prev_close": 1530.6,
        "ask": 0,
        "bid": 1557.9,
        "oi": 0,
        "volume": 7575038
      }
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with results array
- `status_code` (int): HTTP status code

**Note:** Invalid symbols are returned with an error field. If broker doesn't support multiquotes, the service falls back to fetching quotes individually.

---

### Depth

Get market depth for a symbol.

**Function:** `get_depth(symbol, exchange, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/depth_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.depth_service import get_depth

success, response, status_code = get_depth(
    symbol="SBIN",
    exchange="NSE",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "open": 760.0,
    "high": 774.0,
    "low": 758.15,
    "ltp": 769.6,
    "ltq": 205,
    "prev_close": 746.9,
    "volume": 9362799,
    "oi": 161265750,
    "totalbuyqty": 591351,
    "totalsellqty": 835701,
    "asks": [
      {
        "price": 769.6,
        "quantity": 767
      },
      {
        "price": 769.65,
        "quantity": 115
      }
    ],
    "bids": [
      {
        "price": 769.4,
        "quantity": 886
      },
      {
        "price": 769.35,
        "quantity": 212
      }
    ]
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Response data with market depth
- `status_code` (int): HTTP status code

---

### History

Get historical data for a symbol.

**Function:** `get_history(symbol, exchange, interval, start_date, end_date, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/history_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| interval | str | Yes | Time interval (1m, 5m, 15m, 1h, D) |
| start_date | str | Yes | Start date (YYYY-MM-DD) |
| end_date | str | Yes | End date (YYYY-MM-DD) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.history_service import get_history

success, response, status_code = get_history(
    symbol="SBIN",
    exchange="NSE",
    interval="5m",
    start_date="2025-04-01",
    end_date="2025-04-08",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```
                            close    high     low    open  volume
timestamp
2025-04-01 09:15:00+05:30  772.50  774.00  763.20  766.50  318625
2025-04-01 09:20:00+05:30  773.20  774.95  772.10  772.45  197189
2025-04-01 09:25:00+05:30  775.15  775.60  772.60  773.20  227544
...
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (pandas.DataFrame or dict): Historical data
- `status_code` (int): HTTP status code

---

### Intervals

Get available time intervals for historical data.

**Function:** `get_intervals(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/intervals_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.intervals_service import get_intervals

success, response, status_code = get_intervals(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "months": [],
    "weeks": [],
    "days": ["D"],
    "hours": ["1h"],
    "minutes": ["10m", "15m", "1m", "30m", "3m", "5m"],
    "seconds": []
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Available intervals
- `status_code` (int): HTTP status code

---

## Symbol Services

### Symbol

Get detailed information about a symbol.

**Function:** `get_symbol(symbol, exchange, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/symbol_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.symbol_service import get_symbol

success, response, status_code = get_symbol(
    symbol="RELIANCE",
    exchange="NSE",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "id": 979,
    "name": "RELIANCE",
    "symbol": "RELIANCE",
    "brsymbol": "RELIANCE-EQ",
    "exchange": "NSE",
    "brexchange": "NSE",
    "instrumenttype": "",
    "expiry": "",
    "strike": -0.01,
    "lotsize": 1,
    "tick_size": 0.05,
    "token": "2885"
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Symbol details
- `status_code` (int): HTTP status code

---

### Search

Search for symbols.

**Function:** `search_symbol(query, exchange, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/search_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | Yes | Search query |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.search_service import search_symbol

success, response, status_code = search_symbol(
    query="NIFTY 25000 JUL CE",
    exchange="NFO",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "data": [
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY17JUL2525000CE",
      "exchange": "NFO",
      "expiry": "17-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY17JUL2525000CE",
      "tick_size": 0.05,
      "token": "47275"
    }
  ],
  "message": "Found 6 matching symbols",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Search results
- `status_code` (int): HTTP status code

---

### Expiry

Get expiry dates for a symbol.

**Function:** `get_expiry(symbol, exchange, instrumenttype, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/expiry_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | str | Yes | Trading symbol |
| exchange | str | Yes | Exchange (NSE, NFO, etc.) |
| instrumenttype | str | Yes | Instrument type (options, futures) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.expiry_service import get_expiry

success, response, status_code = get_expiry(
    symbol="NIFTY",
    exchange="NFO",
    instrumenttype="options",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "data": [
    "10-JUL-25",
    "17-JUL-25",
    "24-JUL-25",
    "31-JUL-25",
    "07-AUG-25",
    "28-AUG-25",
    "25-SEP-25"
  ],
  "message": "Found 18 expiry dates for NIFTY options in NFO",
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Expiry dates
- `status_code` (int): HTTP status code

---

### Instruments

Get all instruments/symbols from the database.

**Function:** `get_instruments(exchange=None, api_key=None, format='json')`

**Location:** `openalgo/services/instruments_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| exchange | str | No | Exchange filter (NSE, BSE, NFO, BFO, etc.) |
| api_key | str | Yes | OpenAlgo API key |
| format | str | No | Output format ('json' or 'csv', default: 'json') |

**Example:**

```python
from services.instruments_service import get_instruments

success, response, status_code, headers = get_instruments(
    exchange="NSE",
    api_key='your_api_key_here',
    format='json'
)

print(response)
```

**Response (JSON):**

```json
{
  "status": "success",
  "message": "Found 3046 instruments",
  "data": [
    {
      "symbol": "RELIANCE",
      "brsymbol": "RELIANCE-EQ",
      "name": "RELIANCE INDUSTRIES LTD",
      "exchange": "NSE",
      "brexchange": "NSE",
      "token": "2885",
      "expiry": null,
      "strike": -1.0,
      "lotsize": 1,
      "instrumenttype": "EQ",
      "tick_size": 0.05
    },
    {
      "symbol": "TCS",
      "brsymbol": "TCS-EQ",
      "name": "TATA CONSULTANCY SERVICES",
      "exchange": "NSE",
      "brexchange": "NSE",
      "token": "11536",
      "expiry": null,
      "strike": -1.0,
      "lotsize": 1,
      "instrumenttype": "EQ",
      "tick_size": 0.05
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict or str): Response data (JSON dict or CSV string)
- `status_code` (int): HTTP status code
- `headers` (dict): Response headers (for CSV downloads)

**Note:** When format='csv', the response is a CSV string and headers include Content-Disposition for file download.

---

## Options Services

### OptionSymbol

Get option symbol based on underlying, expiry, strike offset, and option type.

**Function:** `get_option_symbol(underlying, exchange, expiry_date, strike_int, offset, option_type, api_key, underlying_ltp=None)`

**Location:** `openalgo/services/option_symbol_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| underlying | str | Yes | Underlying symbol (e.g., NIFTY, BANKNIFTY) |
| exchange | str | Yes | Exchange (NSE_INDEX, BSE_INDEX, NFO, BFO) |
| expiry_date | str | No | Expiry date in DDMMMYY format |
| strike_int | int | No | Strike interval (optional - uses actual strikes if not provided) |
| offset | str | Yes | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50) |
| option_type | str | Yes | CE or PE |
| api_key | str | Yes | OpenAlgo API key |
| underlying_ltp | float | No | Pre-fetched LTP to avoid redundant quote requests |

**Example - ATM Option:**

```python
from services.option_symbol_service import get_option_symbol

success, response, status_code = get_option_symbol(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_int=None,
    offset="ATM",
    option_type="CE",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "symbol": "NIFTY30DEC2525950CE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 5,
  "freeze_qty": 1800,
  "underlying_ltp": 25966.4
}
```

**Example - ITM Option:**

```python
success, response, status_code = get_option_symbol(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_int=None,
    offset="ITM3",
    option_type="PE",
    api_key='your_api_key_here'
)
```

**Response:**

```json
{
  "status": "success",
  "symbol": "NIFTY30DEC2526100PE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 5,
  "freeze_qty": 1800,
  "underlying_ltp": 25966.4
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Symbol details with lotsize, tick_size, freeze_qty
- `status_code` (int): HTTP status code

**Note:** If `strike_int` is not provided, the service uses actual strikes from the database for more accurate symbol resolution.

---

### OptionChain

Get option chain data for a given underlying and expiry.

**Function:** `get_option_chain(underlying, exchange, expiry_date, strike_count, api_key)`

**Location:** `openalgo/services/option_chain_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| underlying | str | Yes | Underlying symbol (e.g., NIFTY, BANKNIFTY) |
| exchange | str | Yes | Exchange (NSE_INDEX, BSE_INDEX) |
| expiry_date | str | Yes | Expiry date in DDMMMYY format |
| strike_count | int | Yes | Number of strikes above and below ATM |
| api_key | str | Yes | OpenAlgo API key |

**Example:**

```python
from services.option_chain_service import get_option_chain

success, response, status_code = get_option_chain(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_count=10,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 26215.55,
    "expiry_date": "30DEC25",
    "atm_strike": 26200.0,
    "chain": [
        {
            "strike": 26100.0,
            "ce": {
                "symbol": "NIFTY30DEC2526100CE",
                "label": "ITM2",
                "ltp": 490,
                "bid": 490,
                "ask": 491,
                "open": 540,
                "high": 571,
                "low": 444.75,
                "prev_close": 496.8,
                "volume": 1195800,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2526100PE",
                "label": "OTM2",
                "ltp": 193,
                "bid": 191.2,
                "ask": 193,
                "open": 204.1,
                "high": 229.95,
                "low": 175.6,
                "prev_close": 215.95,
                "volume": 1832700,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            }
        },
        {
            "strike": 26200.0,
            "ce": {
                "symbol": "NIFTY30DEC2526200CE",
                "label": "ATM",
                "ltp": 427,
                "bid": 425.05,
                "ask": 427,
                "open": 449.95,
                "high": 503.5,
                "low": 384,
                "prev_close": 433.2,
                "volume": 2994000,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2526200PE",
                "label": "ATM",
                "ltp": 227.4,
                "bid": 227.35,
                "ask": 228.5,
                "open": 251.9,
                "high": 269.15,
                "low": 205.95,
                "prev_close": 251.9,
                "volume": 3745350,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            }
        }
    ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Option chain data with ATM strike and chain array
- `status_code` (int): HTTP status code

**Note:** Each strike has CE and PE objects with their own labels (ATM, ITM1, OTM1, etc.). Strikes below ATM have CE as ITM and PE as OTM, and vice versa for strikes above ATM.

---

### SyntheticFuture

Calculate synthetic futures price using ATM options.

**Function:** `calculate_synthetic_future(underlying, exchange, expiry_date, api_key)`

**Location:** `openalgo/services/synthetic_future_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| underlying | str | Yes | Underlying symbol (e.g., NIFTY, BANKNIFTY) |
| exchange | str | Yes | Exchange (NSE_INDEX, BSE_INDEX) |
| expiry_date | str | Yes | Expiry date in DDMMMYY format |
| api_key | str | Yes | OpenAlgo API key |

**Formula:**
```
Synthetic Future Price = Strike Price + Call Premium - Put Premium
```

**Example:**

```python
from services.synthetic_future_service import calculate_synthetic_future

success, response, status_code = calculate_synthetic_future(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="25NOV25",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 25910.05,
  "expiry": "25NOV25",
  "atm_strike": 25900.0,
  "synthetic_future_price": 25980.05
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Synthetic future price and ATM strike details
- `status_code` (int): HTTP status code

**Note:** The basis (Synthetic Future Price - Spot Price) indicates the cost of carry.

---

### OptionGreeks

Calculate Option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility.

**Function:** `get_option_greeks(option_symbol, exchange, interest_rate=None, forward_price=None, underlying_symbol=None, underlying_exchange=None, expiry_time=None, api_key=None)`

**Location:** `openalgo/services/option_greeks_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| option_symbol | str | Yes | Option symbol (e.g., NIFTY25NOV2526000CE) |
| exchange | str | Yes | Exchange (NFO, BFO, CDS, MCX) |
| interest_rate | float | No | Risk-free interest rate (annualized %) |
| forward_price | float | No | Custom forward/synthetic futures price |
| underlying_symbol | str | No | Underlying symbol for spot price |
| underlying_exchange | str | No | Underlying exchange |
| expiry_time | str | No | Custom expiry time in "HH:MM" format |
| api_key | str | Yes | OpenAlgo API key |

**Example:**

```python
from services.option_greeks_service import get_option_greeks

success, response, status_code = get_option_greeks(
    option_symbol="NIFTY25NOV2526000CE",
    exchange="NFO",
    interest_rate=0.00,
    underlying_symbol="NIFTY",
    underlying_exchange="NSE_INDEX",
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "symbol": "NIFTY25NOV2526000CE",
  "exchange": "NFO",
  "underlying": "NIFTY",
  "strike": 26000.0,
  "option_type": "CE",
  "expiry_date": "25-Nov-2025",
  "days_to_expiry": 28.5071,
  "spot_price": 25966.05,
  "option_price": 435,
  "interest_rate": 0.0,
  "implied_volatility": 15.6,
  "greeks": {
    "delta": 0.4967,
    "gamma": 0.000352,
    "theta": -7.919,
    "vega": 28.9489,
    "rho": 9.733994
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Greeks data with IV and all Greek values
- `status_code` (int): HTTP status code

**Note:** Uses Black-76 model (appropriate for options on futures/forwards). For deep ITM options with no time value, theoretical Greeks are returned (delta = +/-1, other Greeks = 0).

---

## Account Services

### Funds

Get account funds information.

**Function:** `get_funds(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/funds_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.funds_service import get_funds

success, response, status_code = get_funds(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "availablecash": "320.66",
    "collateral": "0.00",
    "m2mrealized": "3.27",
    "m2munrealized": "-7.88",
    "utiliseddebits": "679.34"
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Funds data
- `status_code` (int): HTTP status code

---

### Margin

Calculate margin requirement for a basket of positions.

**Function:** `calculate_margin(margin_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/margin_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| margin_data | dict | Yes | Margin calculation data with positions array |
| api_key | str | Conditional | OpenAlgo API key (for API-based calls) |
| auth_token | str | Conditional | Direct broker authentication token (for internal calls) |
| broker | str | Conditional | Broker name (for internal calls) |

**Margin Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| apikey | str | Yes | OpenAlgo API key |
| positions | array | Yes | Array of position objects (max 50) |

**Position Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| exchange | str | Yes | Exchange (NSE, NFO, BFO, etc.) |
| symbol | str | Yes | Trading symbol |
| action | str | Yes | BUY or SELL |
| quantity | int | Yes | Position quantity |
| product | str | Yes | MIS, CNC, NRML |
| pricetype | str | Yes | MARKET, LIMIT, SL, SL-M |
| price | float | No | Order price (default: 0) |

**Example:**

```python
from services.margin_service import calculate_margin

margin_data = {
    "apikey": "your_api_key_here",
    "positions": [
        {
            "exchange": "NFO",
            "symbol": "NIFTY25DEC2526000CE",
            "action": "BUY",
            "quantity": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "price": 0
        },
        {
            "exchange": "NFO",
            "symbol": "NIFTY25DEC2526000PE",
            "action": "SELL",
            "quantity": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "price": 0
        }
    ]
}

success, response, status_code = calculate_margin(
    margin_data=margin_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "total_margin": 125000.50,
    "span_margin": 100000.00,
    "exposure_margin": 25000.50,
    "margin_benefit": 15000.00,
    "positions": [
      {
        "exchange": "NFO",
        "symbol": "NIFTY25DEC2526000CE",
        "margin_required": 75000.25
      },
      {
        "exchange": "NFO",
        "symbol": "NIFTY25DEC2526000PE",
        "margin_required": 65000.25
      }
    ]
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Margin calculation results
- `status_code` (int): HTTP status code

**Note:** Maximum 50 positions allowed per request. Margin calculation support depends on broker implementation.

---

### OrderBook

Get the order book.

**Function:** `get_orderbook(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/orderbook_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.orderbook_service import get_orderbook

success, response, status_code = get_orderbook(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "orders": [
      {
        "action": "BUY",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "orderid": "250408000989443",
        "product": "MIS",
        "quantity": "1",
        "price": 1186.0,
        "pricetype": "MARKET",
        "order_status": "complete",
        "trigger_price": 0.0,
        "timestamp": "08-Apr-2025 13:58:03"
      }
    ],
    "statistics": {
      "total_buy_orders": 2.0,
      "total_sell_orders": 0.0,
      "total_completed_orders": 1.0,
      "total_open_orders": 0.0,
      "total_rejected_orders": 0.0
    }
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Order book data
- `status_code` (int): HTTP status code

---

### TradeBook

Get the trade book.

**Function:** `get_tradebook(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/tradebook_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.tradebook_service import get_tradebook

success, response, status_code = get_tradebook(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": [
    {
      "action": "BUY",
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "orderid": "250408000989443",
      "product": "MIS",
      "quantity": 0.0,
      "average_price": 1180.1,
      "timestamp": "13:58:03",
      "trade_value": 1180.1
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Trade book data
- `status_code` (int): HTTP status code

---

### PositionBook

Get the position book.

**Function:** `get_positionbook(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/positionbook_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.positionbook_service import get_positionbook

success, response, status_code = get_positionbook(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": [
    {
      "symbol": "NHPC",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "-1",
      "average_price": "83.74",
      "ltp": "83.72",
      "pnl": "0.02"
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Position book data
- `status_code` (int): HTTP status code

---

### Holdings

Get account holdings.

**Function:** `get_holdings(api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/holdings_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.holdings_service import get_holdings

success, response, status_code = get_holdings(
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "holdings": [
      {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 1,
        "pnl": -149.0,
        "pnlpercent": -11.1
      }
    ],
    "statistics": {
      "totalholdingvalue": 1768.0,
      "totalinvvalue": 2001.0,
      "totalprofitandloss": -233.15,
      "totalpnlpercentage": -11.65
    }
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Holdings data
- `status_code` (int): HTTP status code

---

## Market Calendar Services

### Holidays

Get market holidays for a specific year or current year.

**Function:** `get_holidays(year=None)`

**Location:** `openalgo/services/market_calendar_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| year | int | No | Year to get holidays for (default: current year) |

**Example:**

```python
from services.market_calendar_service import get_holidays

success, response, status_code = get_holidays(year=2025)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "year": 2025,
  "timezone": "Asia/Kolkata",
  "data": [
    {
      "date": "2025-02-26",
      "description": "Maha Shivaratri",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
      "open_exchanges": [
        {"exchange": "MCX", "start_time": 1740549000000, "end_time": 1740602700000}
      ]
    },
    {
      "date": "2025-03-14",
      "description": "Holi",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
      "open_exchanges": [
        {"exchange": "MCX", "start_time": 1741964400000, "end_time": 1742018100000}
      ]
    },
    {
      "date": "2025-08-15",
      "description": "Independence Day",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
      "open_exchanges": []
    }
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Holiday data with year and timezone
- `status_code` (int): HTTP status code

**Note:**
- Year must be between 2020 and 2050
- `holiday_type` can be: `TRADING_HOLIDAY`, `SETTLEMENT_HOLIDAY`, or `SPECIAL_SESSION`
- `closed_exchanges` lists exchanges that are fully closed
- `open_exchanges` lists exchanges with special trading sessions (e.g., MCX evening session, Muhurat trading)
- Times in `open_exchanges` are epoch milliseconds

---

### Timings

Get market timings for a specific date.

**Function:** `get_timings(date_str)`

**Location:** `openalgo/services/market_calendar_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| date_str | str | Yes | Date in YYYY-MM-DD format |

**Example:**

```python
from services.market_calendar_service import get_timings

success, response, status_code = get_timings(date_str="2025-01-15")

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": [
    {"exchange": "NSE", "start_time": 1736926500000, "end_time": 1736949000000},
    {"exchange": "BSE", "start_time": 1736926500000, "end_time": 1736949000000},
    {"exchange": "NFO", "start_time": 1736926500000, "end_time": 1736949000000},
    {"exchange": "BFO", "start_time": 1736926500000, "end_time": 1736949000000},
    {"exchange": "CDS", "start_time": 1736925600000, "end_time": 1736954400000},
    {"exchange": "BCD", "start_time": 1736925600000, "end_time": 1736954400000},
    {"exchange": "MCX", "start_time": 1736925600000, "end_time": 1736979300000}
  ]
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Market timing data
- `status_code` (int): HTTP status code

**Note:**
- Date must be between 2020-01-01 and 2050-12-31
- Times are returned as epoch milliseconds
- Returns empty array for weekends and full holidays
- For special sessions (e.g., Muhurat trading), returns only the special session timings

---

### CheckHoliday

Check if a specific date is a market holiday.

**Function:** `check_holiday(date_str, exchange=None)`

**Location:** `openalgo/services/market_calendar_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| date_str | str | Yes | Date in YYYY-MM-DD format |
| exchange | str | No | Optional exchange code to check (NSE, BSE, NFO, etc.) |

**Example:**

```python
from services.market_calendar_service import check_holiday

success, response, status_code = check_holiday(
    date_str="2025-01-26",
    exchange="NSE"
)

print(response)
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "date": "2025-01-26",
    "exchange": "NSE",
    "is_holiday": true
  }
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Holiday check result
- `status_code` (int): HTTP status code

---

## Analyzer Services

### AnalyzerStatus

Get analyzer mode status.

**Function:** `get_analyzer_status(analyzer_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/analyzer_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| analyzer_data | dict | Yes | Analyzer data (can be empty dict) |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Example:**

```python
from services.analyzer_service import get_analyzer_status

success, response, status_code = get_analyzer_status(
    analyzer_data={},
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "data": {
    "analyze_mode": true,
    "mode": "analyze",
    "total_logs": 2
  },
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Analyzer status
- `status_code` (int): HTTP status code

---

### AnalyzerToggle

Toggle analyzer mode on/off.

**Function:** `toggle_analyzer_mode(analyzer_data, api_key=None, auth_token=None, broker=None)`

**Location:** `openalgo/services/analyzer_service.py`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| analyzer_data | dict | Yes | Analyzer data containing mode |
| api_key | str | Conditional | OpenAlgo API key |
| auth_token | str | Conditional | Direct broker authentication token |
| broker | str | Conditional | Broker name |

**Analyzer Data Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| mode | bool | Yes | True to enable analyze mode, False to disable |

**Example:**

```python
from services.analyzer_service import toggle_analyzer_mode

# Switch to analyze mode (simulated responses)
analyzer_data = {
    "mode": True
}

success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key_here'
)

print(response)
```

**Response:**

```json
{
  "data": {
    "analyze_mode": true,
    "message": "Analyzer mode switched to analyze",
    "mode": "analyze",
    "total_logs": 2
  },
  "status": "success"
}
```

**Returns:**

Tuple containing:
- `success` (bool): Operation success status
- `response` (dict): Analyzer toggle response
- `status_code` (int): HTTP status code

---

## Telegram Service

### TelegramAlertService

The Telegram Alert Service provides automated notifications for order-related events via Telegram. This service is not part of the SDK yet but is available for internal use within OpenAlgo.

**Location:** `openalgo/services/telegram_alert_service.py`

**Features:**

- Asynchronous order notifications
- Support for all order types (place, modify, cancel, etc.)
- Analyze mode and live mode indicators
- Formatted messages with order details
- User-specific notifications based on API key

**Service Instance:**

```python
from services.telegram_alert_service import telegram_alert_service
```

**Methods:**

#### send_order_alert

Send order alert to a Telegram user (non-blocking).

**Function:** `telegram_alert_service.send_order_alert(order_type, order_data, response, api_key=None)`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| order_type | str | Yes | Type of order (placeorder, basketorder, etc.) |
| order_data | dict | Yes | Original order data |
| response | dict | Yes | Order response |
| api_key | str | No | API key to identify user |

**Supported Order Types:**

- `placeorder` - New order placement
- `placesmartorder` - Smart order placement
- `basketorder` - Basket order execution
- `splitorder` - Split order execution
- `modifyorder` - Order modification
- `cancelorder` - Order cancellation
- `cancelallorder` - Cancel all orders
- `closeposition` - Position closure

**Example:**

```python
from services.telegram_alert_service import telegram_alert_service

# This is typically called automatically by order services
# Manual usage example:
telegram_alert_service.send_order_alert(
    order_type='placeorder',
    order_data={
        'symbol': 'RELIANCE',
        'action': 'BUY',
        'quantity': 1,
        'pricetype': 'MARKET',
        'exchange': 'NSE',
        'product': 'MIS',
        'strategy': 'My Strategy'
    },
    response={
        'status': 'success',
        'orderid': '250408000989443',
        'mode': 'live'
    },
    api_key='your_api_key_here'
)
```

**Alert Message Format:**

The service formats alerts with the following information:

- Mode indicator (Live/Analyze)
- Order details (symbol, action, quantity, etc.)
- Order status and ID
- Timestamp
- Strategy name (if provided)

**Example Alert Message:**

```
📈 Order Placed
💰 LIVE MODE - Real Order
─────────────────────
Strategy: My Strategy
Symbol: RELIANCE
Action: BUY
Quantity: 1
Price Type: MARKET
Exchange: NSE
Product: MIS
Order ID: 250408000989443
⏰ Time: 14:35:20
```

#### send_broadcast_alert

Send broadcast alert to multiple users.

**Function:** `telegram_alert_service.send_broadcast_alert(message, filters=None)`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| message | str | Yes | Message to broadcast |
| filters | dict | No | User filters (optional) |

**Example:**

```python
from services.telegram_alert_service import telegram_alert_service

telegram_alert_service.send_broadcast_alert(
    message="🚨 Market Update: NIFTY crossed 25000!",
    filters={'notifications_enabled': True}
)
```

#### toggle_alerts

Enable or disable Telegram alerts globally.

**Function:** `telegram_alert_service.toggle_alerts(enabled)`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| enabled | bool | Yes | True to enable, False to disable |

**Example:**

```python
from services.telegram_alert_service import telegram_alert_service

# Disable all alerts
telegram_alert_service.toggle_alerts(False)

# Enable all alerts
telegram_alert_service.toggle_alerts(True)
```

**Database Integration:**

The service integrates with the following database functions:

- `get_telegram_user_by_username()` - Get user's Telegram ID
- `get_bot_config()` - Get bot configuration
- `add_notification()` - Queue notifications for offline delivery
- `get_username_by_apikey()` - Map API key to username

**Thread Pool Executor:**

The service uses a thread pool executor for non-blocking alert delivery:

```python
# Thread pool configuration
alert_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="telegram_alert")
```

**Error Handling:**

- Errors are logged but don't affect order processing
- Failed notifications are queued for retry
- Offline messages are stored in database
- Timeout protection (10 seconds max per notification)

**Requirements:**

- User must have linked their Telegram account
- Telegram bot must be running
- User must have enabled notifications in settings
- Valid API key mapping to username

**Note:** This service is automatically invoked by all order-related services and typically doesn't need to be called manually.

---

## Authentication Methods

All service functions support two authentication methods:

### Method 1: API Key Authentication

Used when calling services via API endpoints.

```python
success, response, status_code = service_function(
    data=data,
    api_key='your_api_key_here'
)
```

### Method 2: Direct Authentication

Used for internal calls within the application.

```python
success, response, status_code = service_function(
    data=data,
    auth_token='broker_auth_token',
    broker='broker_name'
)
```

**Note:** You must provide either `api_key` OR both `auth_token` and `broker`. Mixing both methods will result in an error.

---

## Analyze Mode

All order-related services support analyze mode, which simulates order operations without executing real trades. When analyze mode is enabled:

- Orders are validated but not sent to the broker
- Simulated order IDs are generated
- All responses include `"mode": "analyze"` field
- Events are logged to the analyzer database
- SocketIO events are emitted for UI updates

To enable analyze mode:

```python
from services.analyzer_service import toggle_analyzer

success, response, status_code = toggle_analyzer(
    mode=True,
    api_key='your_api_key_here'
)
```

---

## Error Handling

All service functions return a consistent tuple format:

```python
(success, response, status_code)
```

- `success` (bool): `True` if operation succeeded, `False` otherwise
- `response` (dict): Response data or error message
- `status_code` (int): HTTP status code

**Common Error Responses:**

```json
{
  "status": "error",
  "message": "Error description"
}
```

**Common HTTP Status Codes:**

- `200` - Success
- `400` - Bad Request (validation error)
- `403` - Forbidden (invalid API key)
- `404` - Not Found (broker module not found)
- `500` - Internal Server Error

**Example Error Handling:**

```python
success, response, status_code = place_order(
    order_data=order_data,
    api_key='your_api_key'
)

if not success:
    print(f"Error: {response.get('message')}")
    print(f"Status Code: {status_code}")
else:
    print(f"Order ID: {response.get('orderid')}")
```

---

## SocketIO Events

Services emit real-time events via SocketIO for UI updates:

**Order Events:**

```python
socketio.emit('order_event', {
    'symbol': 'RELIANCE',
    'action': 'BUY',
    'orderid': '250408000989443',
    'exchange': 'NSE',
    'price_type': 'MARKET',
    'product_type': 'MIS',
    'mode': 'live'
})
```

**Analyzer Events:**

```python
socketio.emit('analyzer_update', {
    'request': {...},
    'response': {...}
})
```

**Cancel Events:**

```python
socketio.emit('cancel_order_event', {
    'status': 'success',
    'orderid': '250408001002736',
    'mode': 'live'
})
```

---

## Logging

All services use structured logging:

```python
from utils.logging import get_logger

logger = get_logger(__name__)
logger.info("Order placed successfully")
logger.error("Failed to place order", exc_info=True)
```

Logs are automatically stored in the API log database:

```python
from database.apilog_db import async_log_order

executor.submit(async_log_order, 'placeorder', request_data, response_data)
```

---

## Concurrency

Services use thread pool executors for async operations:

```python
from concurrent.futures import ThreadPoolExecutor

# For API logging
executor = ThreadPoolExecutor(max_workers=10)

# For Telegram alerts
alert_executor = ThreadPoolExecutor(max_workers=5)
```

**Batch Operations:**

Basket orders and split orders use concurrent execution:

```python
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(place_single_order, order) for order in orders]
    results = [future.result() for future in as_completed(futures)]
```

---

## Best Practices

1. **Always handle errors gracefully:**
   ```python
   success, response, status_code = service_function(...)
   if not success:
       handle_error(response)
   ```

2. **Use appropriate authentication method:**
   - API key for external calls
   - Direct auth for internal calls

3. **Enable analyze mode for testing:**
   ```python
   toggle_analyzer(mode=True, api_key='...')
   ```

4. **Monitor SocketIO events for real-time updates**

5. **Check API logs for debugging:**
   - Database: `apilog_db`
   - Analyzer logs: `analyzer_db`

6. **Use batch operations for multiple orders:**
   - `place_basket_order()` for different symbols
   - `split_order()` for large quantities

7. **Handle Telegram notifications:**
   - Ensure users have linked accounts
   - Check notification settings
   - Monitor alert queue

---

## Service Dependencies

Services depend on the following modules:

**Database:**
- `database.auth_db` - Authentication
- `database.apilog_db` - API logging
- `database.settings_db` - Settings
- `database.analyzer_db` - Analyzer logs
- `database.telegram_db` - Telegram users

**Utils:**
- `utils.api_analyzer` - Request analysis
- `utils.constants` - Validation constants
- `utils.logging` - Logging utilities

**Extensions:**
- `extensions.socketio` - Real-time events

**Broker Modules:**
- `broker.{broker_name}.api.order_api` - Broker-specific APIs

---

## Support

For issues or questions:
- GitHub: https://github.com/marketcalls/openalgo
- Documentation: https://docs.openalgo.in
- Discord: Join our community

---

**Last Updated:** January 2025
**Version:** OpenAlgo Dawn
