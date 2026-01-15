# Python

To install the OpenAlgo Python library, use pip:

```bash
pip install openalgo
```

### Get the OpenAlgo apikey

Make Sure that your OpenAlgo Application is running. Login to OpenAlgo Application with valid credentials and get the OpenAlgo apikey

For detailed function parameters refer to the [API Documentation](https://docs.openalgo.in/api-documentation/v1)

### Getting Started with OpenAlgo

First, import the `api` class from the OpenAlgo library and initialize it with your API key:

```python
from openalgo import api

# Replace 'your_api_key_here' with your actual API key
# Specify the host URL with your hosted domain or ngrok domain. 
# If running locally in windows then use the default host value. 
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')

```

### Check OpenAlgo Version

```python
import openalgo 
openalgo.__version__
```

### Examples

Please refer to the documentation on [order constants](https://docs.openalgo.in/api-documentation/v1/order-constants), and consult the API reference for details on optional parameters

### PlaceOrder example

To place a new market order:

```python
response = client.placeorder(
    strategy="Python",
    symbol="NHPC",
    action="BUY",
    exchange="NSE",
    price_type="MARKET",
    product="MIS",
    quantity=1
)
print(response)

```

Place Market Order Response

```json
{'orderid': '250408000989443', 'status': 'success'}
```

To place a new limit order:

```python
response = client.placeorder(
    strategy="Python",
    symbol="YESBANK",
    action="BUY",
    exchange="NSE",
    price_type="LIMIT",
    product="MIS",
    quantity="1",
    price="16",
    trigger_price="0",
    disclosed_quantity ="0",
)
print(response)
```

Place Limit Order Response

```json
{'orderid': '250408001003813', 'status': 'success'}
```

### PlaceSmartOrder Example

To place a smart order considering the current position size:

```python
response = client.placesmartorder(
    strategy="Python",
    symbol="TATAMOTORS",
    action="SELL",
    exchange="NSE",
    price_type="MARKET",
    product="MIS",
    quantity=1,
    position_size=5
)
print(response)

```

Place Smart Market Order Response

```json
{'orderid': '250408000997543', 'status': 'success'}
```

### OptionsOrder Example

To place ATM options order

```python
response = client.optionsorder(
      strategy="python",
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="ATM",
      option_type="CE",
      action="BUY",
      quantity=75,
      pricetype="MARKET",
      product="NRML",
      splitsize = 0
  )

print(response)
```

Place Options Order Response

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

To place ITM options order

```python
response = client.optionsorder(
      strategy="python",
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="ITM4",
      option_type="PE",
      action="BUY",
      quantity=75,
      pricetype="MARKET",
      product="NRML",
      splitsize = 0
  )

print(response)
```

Place Options Order Response

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

To place OTM options order

```python
response = client.optionsorder(
      strategy="python",
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="OTM5",
      option_type="CE",
      action="BUY",
      quantity=75,
      pricetype="MARKET",
      product="NRML",
      splitsize = 0
  )

print(response)
```

Place Options Order Response

```json
{
  "exchange": "NFO",
  "mode": "analyze",
  "offset": "OTM5",
  "option_type": "CE",
  "orderid": "25102800000008",
  "status": "success",
  "symbol": "NIFTY28OCT2526200CE",
  "underlying": "NIFTY28OCT25FUT",
  "underlying_ltp": 25966.05
}
```

### OptionsMultiOrder Example

To place Iron options order (Same Expiry)

```python
response = client.optionsmultiorder(
    strategy="Iron Condor Test",
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="25NOV25",
    legs=[
        {"offset": "OTM6", "option_type": "CE", "action": "BUY", "quantity": 75},
        {"offset": "OTM6", "option_type": "PE", "action": "BUY", "quantity": 75},
        {"offset": "OTM4", "option_type": "CE", "action": "SELL", "quantity": 75},
        {"offset": "OTM4", "option_type": "PE", "action": "SELL", "quantity": 75}
    ]
)

print(response)
```

Place OptionsMultiOrder Response

```json
{
    'status': 'success',
    'underlying': 'NIFTY',
    'underlying_ltp': 26050.45,
    'results': [
        {
            'action': 'BUY',
            'leg': 1,
            'mode': 'analyze',
            'offset': 'OTM6',
            'option_type': 'CE',
            'orderid': '25111996859688',
            'status': 'success',
            'symbol': 'NIFTY25NOV2526350CE'
        },
        {
            'action': 'BUY',
            'leg': 2,
            'mode': 'analyze',
            'offset': 'OTM6',
            'option_type': 'PE',
            'orderid': '25111996042210',
            'status': 'success',
            'symbol': 'NIFTY25NOV2525750PE'
        },
        {
            'action': 'SELL',
            'leg': 3,
            'mode': 'analyze',
            'offset': 'OTM4',
            'option_type': 'CE',
            'orderid': '25111922189638',
            'status': 'success',
            'symbol': 'NIFTY25NOV2526250CE'
        },
        {
            'action': 'SELL',
            'leg': 4,
            'mode': 'analyze',
            'offset': 'OTM4',
            'option_type': 'PE',
            'orderid': '25111919252668',
            'status': 'success',
            'symbol': 'NIFTY25NOV2525850PE'
        }
    ]
}

```

To place Diagonal Spread options order (Different Expiry)

```python
response = client.optionsmultiorder(
      strategy="Diagonal Spread Test",
      underlying="NIFTY",
      exchange="NSE_INDEX",
      legs=[
          {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25"},
          {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "25NOV25"}
      ]
  )

print(response)

```

Place OptionsMultiOrder Response

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

### BasketOrder example

To place a new basket order:

```python
basket_orders = [
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
response = client.basketorder(orders=basket_orders)
print(response)
```

**Basket Order Response**

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

### SplitOrder example

To place a new split order:

```python
response = client.splitorder(
    symbol="YESBANK",
    exchange="NSE",
    action="SELL",
    quantity=105,
    splitsize=20,
    price_type="MARKET",
    product="MIS"
    )
print(response)

```

**SplitOrder Response**

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

### ModifyOrder Example

To modify an existing order:

```python
response = client.modifyorder(
    order_id="250408001002736",
    strategy="Python",
    symbol="YESBANK",
    action="BUY",
    exchange="NSE",
    price_type="LIMIT",
    product="CNC",
    quantity=1,
    price=16.5
)
print(response)
```

**Modify Order Response**

```json
{'orderid': '250408001002736', 'status': 'success'}
```

### CancelOrder Example

To cancel an existing order:

```python
response = client.cancelorder(
    order_id="250408001002736",
    strategy="Python"
)
print(response)
```

**Cancelorder Response**

```json
{'orderid': '250408001002736', 'status': 'success'}
```

### CancelAllOrder Example

To cancel all open orders and trigger pending orders

```python
response = client.cancelallorder(
    strategy="Python"
)
print(response)
```

**Cancelallorder Response**

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

### ClosePosition Example

To close all open positions across various exchanges

```python
response = client.closeposition(
    strategy="Python"
)
print(response)
```

**ClosePosition Response**

```json
{'message': 'All Open Positions Squared Off', 'status': 'success'}
```

### OrderStatus Example

To Get the Current OrderStatus

```python
response = client.orderstatus(
    order_id="250828000185002",
    strategy="Test Strategy"
    )
print(response)
```

**Orderstatus Response**

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

### OpenPosition Example

To Get the Current OpenPosition

```python
response = client.openposition(
            strategy="Test Strategy",
            symbol="YESBANK",
            exchange="NSE",
            product="MIS"
        )
print(response)
```

OpenPosition Response

```json
{'quantity': '-10', 'status': 'success'}
```

### Quotes Example

```python
response = client.quotes(symbol="RELIANCE", exchange="NSE")
print(response)
```

**Quotes response**

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

### MultiQuotes Example

```python
response = client.multiquotes(symbols=[
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
])

print(response)
```

**Quotes response**

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

### Depth Example

```python
response = client.depth(symbol="SBIN", exchange="NSE")
print(response)
```

**Depth Response**

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
      },
      {
        "price": 769.7,
        "quantity": 162
      },
      {
        "price": 769.75,
        "quantity": 1121
      },
      {
        "price": 769.8,
        "quantity": 430
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
      },
      {
        "price": 769.3,
        "quantity": 351
      },
      {
        "price": 769.25,
        "quantity": 343
      },
      {
        "price": 769.2,
        "quantity": 399
      }
    ]
  }
}

```

### History Example

```python
response = client.history(symbol="SBIN", 
    exchange="NSE", 
    interval="5m", 
    start_date="2025-04-01", 
    end_date="2025-04-08"
    )
print(response)
```

**History Response**

```json
                            close    high     low    open  volume
timestamp                                                        
2025-04-01 09:15:00+05:30  772.50  774.00  763.20  766.50  318625
2025-04-01 09:20:00+05:30  773.20  774.95  772.10  772.45  197189
2025-04-01 09:25:00+05:30  775.15  775.60  772.60  773.20  227544
2025-04-01 09:30:00+05:30  777.35  777.50  774.85  775.15  134596
2025-04-01 09:35:00+05:30  778.00  778.00  776.25  777.50  145385
...                           ...     ...     ...     ...     ...
2025-04-08 14:00:00+05:30  768.25  770.70  767.85  768.50  142478
2025-04-08 14:05:00+05:30  769.10  769.80  766.60  768.15  128283
2025-04-08 14:10:00+05:30  769.05  769.85  768.40  769.10  119084
2025-04-08 14:15:00+05:30  770.05  770.50  769.05  769.05  158299
2025-04-08 14:20:00+05:30  769.95  770.50  769.40  770.05  125485

[437 rows x 5 columns]
```

### Intervals Example

```python
response = client.intervals()
print(response)
```

**Intervals response**

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

### OptionChain Example

Note : To fetch entire option chain for a expiry remove the strike\_count (optional) parameter

```python
chain = client.optionchain(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_count=10
)
```

**Symbols Response**

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
            "strike": 26150.0,
            "ce": {
                "symbol": "NIFTY30DEC2526150CE",
                "label": "ITM1",
                "ltp": 460.5,
                "bid": 452.9,
                "ask": 463,
                "open": 475.8,
                "high": 535.7,
                "low": 414.6,
                "prev_close": 461.05,
                "volume": 183525,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2526150PE",
                "label": "OTM1",
                "ltp": 208.5,
                "bid": 207.85,
                "ask": 210.1,
                "open": 218.2,
                "high": 248.8,
                "low": 190.75,
                "prev_close": 233.7,
                "volume": 332100,
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
        },
        {
            "strike": 26250.0,
            "ce": {
                "symbol": "NIFTY30DEC2526250CE",
                "label": "OTM1",
                "ltp": 398,
                "bid": 395.4,
                "ask": 400.5,
                "open": 442.1,
                "high": 468.5,
                "low": 355.75,
                "prev_close": 401.9,
                "volume": 407100,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2526250PE",
                "label": "ITM1",
                "ltp": 243.85,
                "bid": 243.6,
                "ask": 246.15,
                "open": 264.25,
                "high": 288,
                "low": 222.15,
                "prev_close": 269.7,
                "volume": 487575,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            }
        },
        {
            "strike": 26300.0,
            "ce": {
                "symbol": "NIFTY30DEC2526300CE",
                "label": "OTM2",
                "ltp": 367.55,
                "bid": 364,
                "ask": 367.55,
                "open": 378,
                "high": 437.4,
                "low": 327.25,
                "prev_close": 371.45,
                "volume": 2416350,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2526300PE",
                "label": "ITM2",
                "ltp": 266,
                "bid": 264.2,
                "ask": 266.5,
                "open": 263.1,
                "high": 311.55,
                "low": 240,
                "prev_close": 289.85,
                "volume": 2891100,
                "oi": 0,
                "lotsize": 75,
                "tick_size": 0.05
            }
        }
    ]
}

```

### Symbol Example

```python
response = client.symbol(
            symbol="RELIANCE",
            exchange="NSE"
            )
print(response)
```

**Symbols Response**

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

### Search Example

```python
response = client.search(query="NIFTY 25000 JUL CE",exchange="NFO")
print(response)
```

**Search Response**

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
    },
    {
      "brexchange": "NFO",
      "brsymbol": "FINNIFTY31JUL2525000CE",
      "exchange": "NFO",
      "expiry": "31-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 65,
      "name": "FINNIFTY",
      "strike": 25000,
      "symbol": "FINNIFTY31JUL2525000CE",
      "tick_size": 0.05,
      "token": "54763"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY24JUL2525000CE",
      "exchange": "NFO",
      "expiry": "24-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY24JUL2525000CE",
      "tick_size": 0.05,
      "token": "49487"
    }
  ],
  "message": "Found 6 matching symbols",
  "status": "success"
}
```

### OptionSymbol Example

ATM Option

```python
response = client.optionsymbol(
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="ATM",
      option_type="CE"
  )

print(response)
```

**OptionSymbol Response**

```json
{
  "status": "success",
  "symbol": "NIFTY28OCT2525950CE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 0.05,
  "underlying_ltp": 25966.05
}
```

ITM Option

```python
response = client.optionsymbol(
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="ITM3",
      option_type="PE"
  )

print(response)
```

**OptionSymbol Response**

```json
{
  "status": "success",
  "symbol": "NIFTY28OCT2526100PE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 0.05,
  "underlying_ltp": 25966.05
}
```

OTM Option

```python
response = client.optionsymbol(
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="28OCT25",
      offset="OTM4",
      option_type="CE"
  )

print(response)
```

**OptionSymbol Response**

```json
{
  "status": "success",
  "symbol": "NIFTY28OCT2526150CE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 0.05,
  "underlying_ltp": 25966.05
}
```

### SyntheticFuture Example

```python
response = client.syntheticfuture(
      underlying="NIFTY",
      exchange="NSE_INDEX",
      expiry_date="25NOV25"
  )

print(response)
```

SyntheticFuture **Response**

```
{
 'atm_strike': 25900.0,
 'expiry': '25NOV25',
 'status': 'success',
 'synthetic_future_price': 25980.05,
 'underlying': 'NIFTY',
 'underlying_ltp': 25910.05
}
```

### OptionGreeks Example

```python
response = client.optiongreeks(
      symbol="NIFTY25NOV2526000CE",
      exchange="NFO",
      interest_rate=0.00,
      underlying_symbol="NIFTY",
      underlying_exchange="NSE_INDEX"
  )

print(response)
```

OptionGreeks  **Response**

```
{
'days_to_expiry': 28.5071,
 'exchange': 'NFO',
 'expiry_date': '25-Nov-2025',
 'greeks': {'delta': 0.4967,
  'gamma': 0.000352,
  'rho': 9.733994,
  'theta': -7.919,
  'vega': 28.9489},
 'implied_volatility': 15.6,
 'interest_rate': 0.0,
 'option_price': 435,
 'option_type': 'CE',
 'spot_price': 25966.05,
 'status': 'success',
 'strike': 26000.0,
 'symbol': 'NIFTY25NOV2526000CE',
 'underlying': 'NIFTY'
}
```

### Expiry Example

```python
response = client.expiry(
    symbol="NIFTY",
    exchange="NFO",
    instrumenttype="options"
)

response
```

**Expiry Response**

```
{'data': ['10-JUL-25',
  '17-JUL-25',
  '24-JUL-25',
  '31-JUL-25',
  '07-AUG-25',
  '28-AUG-25',
  '25-SEP-25',
  '24-DEC-25',
  '26-MAR-26',
  '25-JUN-26',
  '31-DEC-26',
  '24-JUN-27',
  '30-DEC-27',
  '29-JUN-28',
  '28-DEC-28',
  '28-JUN-29',
  '27-DEC-29',
  '25-JUN-30'],
 'message': 'Found 18 expiry dates for NIFTY options in NFO',
 'status': 'success'}
```

### Instruments Example

```python
response = client.instruments(exchange="NSE")

print(response.tail())
```

Instruments **Response**

```json
     brexchange           brsymbol exchange expiry instrumenttype  lotsize  \
3041        NSE      NSE:NEOGEN-EQ      NSE   None             EQ        1   
3042        NSE     NSE:ALANKIT-EQ      NSE   None             EQ        1   
3043        NSE  NSE:EVERESTIND-EQ      NSE   None             EQ        1   
3044        NSE   NSE:VIKASLIFE-EQ      NSE   None             EQ        1   
3045        NSE    NSE:ONEPOINT-EQ      NSE   None             EQ        1   

                          name  strike      symbol  tick_size           token  
3041  NEOGEN CHEMICALS LIMITED    -1.0      NEOGEN       0.10  10100000009917  
3042           ALANKIT LIMITED    -1.0     ALANKIT       0.01  10100000009921  
3043    EVEREST INDUSTRIES LTD    -1.0  EVERESTIND       0.05   1010000000993  
3044    VIKAS LIFECARE LIMITED    -1.0   VIKASLIFE       0.01  10100000009931  
3045     ONE POINT ONE SOL LTD    -1.0    ONEPOINT       0.01  10100000009939  
```

### Telegram Alert Example

```python
response = client.telegram(
      username="<openalgo_loginid>",
      message="NIFTY crossed 26000!"
  )

print(response)
```

**Telegram Alert Response**

```json
{
  "message": "Notification sent successfully",
  "status": "success"
}
```

### Funds Example

```python
response = client.funds()
print(response)
```

**Funds Response**

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

### Margin Example

```python
response = client.margin(positions=[
      {
          "symbol": "NIFTY25NOV2525000CE",
          "exchange": "NFO",
          "action": "BUY",
          "product": "NRML",
          "pricetype": "MARKET",
          "quantity": "75"
      },
      {
          "symbol": "NIFTY25NOV2525500CE",
          "exchange": "NFO",
          "action": "SELL",
          "product": "NRML",
          "pricetype": "MARKET",
          "quantity": "75"
      }
  ])
```

**Margin Response**

```json
{
    "status": "success",
    "data": {
      "total_margin_required": 91555.7625,
      "span_margin": 0.0,
      "exposure_margin": 91555.7625
    }
}
```

### OrderBook Example

```python
response = client.orderbook()
print(response)
```

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
      },
      {
        "action": "BUY",
        "symbol": "YESBANK",
        "exchange": "NSE",
        "orderid": "250408001002736",
        "product": "MIS",
        "quantity": "1",
        "price": 16.5,
        "pricetype": "LIMIT",
        "order_status": "cancelled",
        "trigger_price": 0.0,
        "timestamp": "08-Apr-2025 14:13:45"
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

### TradeBook Example

```python
response = client.tradebook()
print(response)
```

TradeBook Response

```python
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
    },
    {
      "action": "SELL",
      "symbol": "NHPC",
      "exchange": "NSE",
      "orderid": "250408001086129",
      "product": "MIS",
      "quantity": 0.0,
      "average_price": 83.74,
      "timestamp": "14:28:49",
      "trade_value": 83.74
    }
  ]
}

```

### PositionBook Example

```python
response = client.positionbook()
print(response)
```

**PositionBook Response**

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
    },
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "0",
      "average_price": "0.0",
      "ltp": "1189.9",
      "pnl": "5.90"
    },
    {
      "symbol": "YESBANK",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "-104",
      "average_price": "17.2",
      "ltp": "17.31",
      "pnl": "-10.44"
    }
  ]
}

```

### Holdings Example

```python
response = client.holdings()
print(response)
```

Holdings Response

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
      },
      {
        "symbol": "TATASTEEL",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 1,
        "pnl": -15.0,
        "pnlpercent": -10.41
      },
      {
        "symbol": "CANBK",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 5,
        "pnl": -69.0,
        "pnlpercent": -13.43
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

### Analyzer Status Example

```python
response  = client.analyzerstatus()
print(response)
```

Analyzer Status Response

```json
{'data': {'analyze_mode': True, 'mode': 'analyze', 'total_logs': 2},
 'status': 'success'}
```

### Analyzer Toggle Example

```python
# Switch to analyze mode (simulated responses)
response = client.analyzertoggle(mode=True)
print(response)
```

Analyzer Toggle Response

```
{'data': {'analyze_mode': True,
  'message': 'Analyzer mode switched to analyze',
  'mode': 'analyze',
  'total_logs': 2},
 'status': 'success'}
```

### LTP Data (Streaming Websocket)

```python
from openalgo import api
import time

# Initialize OpenAlgo client
client = api(
    api_key="your_api_key",                  # Replace with your actual OpenAlgo API key
    host="http://127.0.0.1:5000",            # REST API host
    ws_url="ws://127.0.0.1:8765"             # WebSocket host
)

# Define instruments to subscribe for LTP
instruments = [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
]

# Callback function for LTP updates
def on_ltp(data):
    print("LTP Update Received:")
    print(data)

# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments, on_data_received=on_ltp)

# Run for a few seconds to receive data
try:
    time.sleep(10)
finally:
    client.unsubscribe_ltp(instruments)
    client.disconnect()

```

### Quotes (Streaming Websocket)

```python
from openalgo import api
import time

# Initialize OpenAlgo client
client = api(
    api_key="your_api_key",                  # Replace with your actual OpenAlgo API key
    host="http://127.0.0.1:5000",            # REST API host
    ws_url="ws://127.0.0.1:8765"             # WebSocket host
)

# Instruments list
instruments = [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
]

# Callback for Quote updates
def on_quote(data):
    print("Quote Update Received:")
    print(data)

# Connect and subscribe to quote stream
client.connect()
client.subscribe_quote(instruments, on_data_received=on_quote)

# Keep the script running to receive data
try:
    time.sleep(10)
finally:
    client.unsubscribe_quote(instruments)
    client.disconnect()

```

### Depth (Streaming Websocket)

```python
from openalgo import api
import time

# Initialize OpenAlgo client
client = api(
    api_key="your_api_key",                  # Replace with your actual OpenAlgo API key
    host="http://127.0.0.1:5000",            # REST API host
    ws_url="ws://127.0.0.1:8765"             # WebSocket host
)

# Instruments list for depth
instruments = [
    {"exchange": "NSE", "symbol": "RELIANCE"},
    {"exchange": "NSE", "symbol": "INFY"}
]

# Callback for market depth updates
def on_depth(data):
    print("Market Depth Update Received:")
    print(data)

# Connect and subscribe to depth stream
client.connect()
client.subscribe_depth(instruments, on_data_received=on_depth)

# Run for a few seconds to collect data
try:
    time.sleep(10)
finally:
    client.unsubscribe_depth(instruments)
    client.disconnect()

```