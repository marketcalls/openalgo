# OptionsMultiOrder

## Options Multi-Order

### Endpoint URL

This API Function Places Multiple Option Legs with Common Underlying by Auto-Resolving Symbols based on Offset. BUY legs are executed first for margin efficiency, then SELL legs.

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsmultiorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsmultiorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsmultiorder
```

### Sample API Request (Iron Condor Strategy)

```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Iron Condor",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "splitsize": 0
        },
        {
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "splitsize": 0
        },
        {
            "offset": "OTM5",
            "option_type": "CE",
            "action": "SELL",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "splitsize": 0
        },
        {
            "offset": "OTM5",
            "option_type": "PE",
            "action": "SELL",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "splitsize": 0
        }
    ]
}
```

####

### Sample API Response (Live Mode)

```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {
            "leg": 1,
            "symbol": "NIFTY30DEC2524650CE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "status": "success",
            "orderid": "240123000001234"
        },
        {
            "leg": 2,
            "symbol": "NIFTY30DEC2523650PE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "status": "success",
            "orderid": "240123000001235"
        },
        {
            "leg": 3,
            "symbol": "NIFTY30DEC2524400CE",
            "exchange": "NFO",
            "offset": "OTM5",
            "option_type": "CE",
            "action": "SELL",
            "status": "success",
            "orderid": "240123000001236"
        },
        {
            "leg": 4,
            "symbol": "NIFTY30DEC2523900PE",
            "exchange": "NFO",
            "offset": "OTM5",
            "option_type": "PE",
            "action": "SELL",
            "status": "success",
            "orderid": "240123000001237"
        }
    ]
}
```

####

### Sample API Response (Analyze Mode)

```json
{
    "status": "success",
    "mode": "analyze",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {
            "leg": 1,
            "symbol": "NIFTY30DEC2524650CE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "status": "success",
            "orderid": "SB-1234567890"
        },
        {
            "leg": 2,
            "symbol": "NIFTY30DEC2523650PE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "status": "success",
            "orderid": "SB-1234567891"
        },
        {
            "leg": 3,
            "symbol": "NIFTY30DEC2524400CE",
            "exchange": "NFO",
            "offset": "OTM5",
            "option_type": "CE",
            "action": "SELL",
            "status": "success",
            "orderid": "SB-1234567892"
        },
        {
            "leg": 4,
            "symbol": "NIFTY30DEC2523900PE",
            "exchange": "NFO",
            "offset": "OTM5",
            "option_type": "PE",
            "action": "SELL",
            "status": "success",
            "orderid": "SB-1234567893"
        }
    ]
}
```

####

### Sample API Request (Straddle with LIMIT Orders)

```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Long Straddle",
    "underlying": "BANKNIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 30,
            "expiry_date": "30DEC25",
            "pricetype": "LIMIT",
            "product": "MIS",
            "price": 250.0,
            "splitsize": 0
        },
        {
            "offset": "ATM",
            "option_type": "PE",
            "action": "BUY",
            "quantity": 30,
            "expiry_date": "30DEC25",
            "pricetype": "LIMIT",
            "product": "MIS",
            "price": 250.0,
            "splitsize": 0
        }
    ]
}
```

####

### Sample API Request (Future as Underlying)

```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Bull Call Spread",
    "underlying": "NIFTY30DEC25FUT",
    "exchange": "NFO",
    "legs": [
        {
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "product": "NRML",
            "splitsize": 0
        },
        {
            "offset": "OTM3",
            "option_type": "CE",
            "action": "SELL",
            "quantity": 75,
            "expiry_date": "30DEC25",
            "product": "NRML",
            "splitsize": 0
        }
    ]
}
```

####

### Parameter Description (Request Level)

| Parameters   | Description                                                | Mandatory/Optional | Default Value |
| ------------ | ---------------------------------------------------------- | ------------------ | ------------- |
| apikey       | App API key                                                | Mandatory          | -             |
| strategy     | Strategy name                                              | Mandatory          | -             |
| underlying   | Underlying symbol (NIFTY, BANKNIFTY, NIFTY30DEC25FUT)      | Mandatory          | -             |
| exchange     | Exchange code (NSE\_INDEX, NSE, NFO, BSE\_INDEX, BSE, BFO) | Mandatory          | -             |
| legs         | Array of leg objects (1-20 legs)                           | Mandatory          | -             |

\*Note: expiry\_date should be specified per-leg to support calendar and diagonal spreads

####

### Parameter Description (Per Leg)

| Parameters          | Description                                 | Mandatory/Optional | Default Value |
| ------------------- | ------------------------------------------- | ------------------ | ------------- |
| offset              | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50) | Mandatory          | -             |
| option\_type        | Option type (CE for Call, PE for Put)       | Mandatory          | -             |
| action              | Action (BUY/SELL)                           | Mandatory          | -             |
| quantity            | Quantity (must be multiple of lot size)     | Mandatory          | -             |
| expiry\_date        | Expiry date in DDMMMYY format (e.g., 30DEC25) | Mandatory        | -             |
| splitsize           | Auto-split order into chunks of this size (0=no split) | Optional | 0             |
| pricetype           | Price type (MARKET/LIMIT/SL/SL-M)           | Optional           | MARKET        |
| product             | Product type (MIS/NRML)\*\*                 | Optional           | MIS           |
| price               | Limit price                                 | Optional           | 0             |
| trigger\_price      | Trigger price for SL orders                 | Optional           | 0             |
| disclosed\_quantity | Disclosed quantity                          | Optional           | 0             |

\*\*Note: Options only support MIS and NRML products (CNC not supported)

\*\*\*Note: Per-leg expiry\_date enables diagonal and calendar spreads with different expiries in a single API call

####

### Response Parameters

| Parameter       | Description                                  | Type   |
| --------------- | -------------------------------------------- | ------ |
| status          | API response status (success/error)          | string |
| underlying      | Underlying symbol from request               | string |
| underlying\_ltp | Last Traded Price of underlying              | number |
| mode            | Trading mode (analyze/live)\*\*\*            | string |
| results         | Array of leg results                         | array  |

\*\*\*Note: mode field is only present in Analyze Mode responses

####

### Result Parameters (Per Leg)

| Parameter    | Description                                  | Type   |
| ------------ | -------------------------------------------- | ------ |
| leg          | Leg number (1, 2, 3, ...)                    | number |
| symbol       | Resolved option symbol                       | string |
| exchange     | Resolved exchange (NFO/BFO)                  | string |
| offset       | Strike offset from request                   | string |
| option\_type | Option type (CE/PE)                          | string |
| action       | Action (BUY/SELL)                            | string |
| status       | Leg status (success/error)                   | string |
| orderid      | Broker order ID (or SB-xxx for analyze mode) | string |
| message      | Error message (only if status is error)      | string |

####

### Execution Order - BUY First Strategy

The API automatically sorts and executes legs in the following order for **margin efficiency**:

1. **BUY legs execute first** (in parallel) - establishes long positions
2. **Wait for all BUY orders to complete**
3. **SELL legs execute next** (in parallel) - establishes short positions

This order ensures:
- Margin benefit from hedged positions
- Better fill rates on protective legs
- Reduced margin requirements for spreads

####

### Live Mode vs Analyze Mode

#### Live Mode

* **When**: Analyze Mode toggle is OFF in OpenAlgo settings
* **Behavior**: Places real orders with connected broker
* **Order ID Format**: Broker's order ID (e.g., "240123000001234")
* **Response**: No "mode" field present

#### Analyze Mode (Sandbox)

* **When**: Analyze Mode toggle is ON in OpenAlgo settings
* **Behavior**: Places virtual orders in sandbox environment
* **Order ID Format**: Sandbox ID with "SB-" prefix (e.g., "SB-1234567890")
* **Response**: Includes "mode": "analyze" field
* **Features**: Virtual capital, realistic execution, auto square-off

**Note**: Same API call works in both modes. The system automatically detects which mode is active.

####

### Common Option Strategies with Request/Response Examples

#### 1. Iron Condor (4 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Iron Condor",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "OTM10", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM10", "option_type": "PE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM5", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM5", "option_type": "PE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524650CE", "exchange": "NFO", "offset": "OTM10", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001234"},
        {"leg": 2, "symbol": "NIFTY30DEC2523650PE", "exchange": "NFO", "offset": "OTM10", "option_type": "PE", "action": "BUY", "status": "success", "orderid": "240123000001235"},
        {"leg": 3, "symbol": "NIFTY30DEC2524400CE", "exchange": "NFO", "offset": "OTM5", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001236"},
        {"leg": 4, "symbol": "NIFTY30DEC2523900PE", "exchange": "NFO", "offset": "OTM5", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001237"}
    ]
}
```

#### 2. Long Straddle (2 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Long Straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "legs": [
        {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75},
        {"offset": "ATM", "option_type": "PE", "action": "BUY", "quantity": 75}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001238"},
        {"leg": 2, "symbol": "NIFTY30DEC2524150PE", "exchange": "NFO", "offset": "ATM", "option_type": "PE", "action": "BUY", "status": "success", "orderid": "240123000001239"}
    ]
}
```

#### 3. Short Straddle (2 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Short Straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "legs": [
        {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 75},
        {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": 75}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001240"},
        {"leg": 2, "symbol": "NIFTY30DEC2524150PE", "exchange": "NFO", "offset": "ATM", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001241"}
    ]
}
```

#### 4. Short Strangle (2 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Short Strangle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "OTM3", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM3", "option_type": "PE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524300CE", "exchange": "NFO", "offset": "OTM3", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001242"},
        {"leg": 2, "symbol": "NIFTY30DEC2524000PE", "exchange": "NFO", "offset": "OTM3", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001243"}
    ]
}
```

#### 5. Bull Call Spread (2 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Bull Call Spread",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM3", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001244"},
        {"leg": 2, "symbol": "NIFTY30DEC2524300CE", "exchange": "NFO", "offset": "OTM3", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001245"}
    ]
}
```

#### 6. Bear Put Spread (2 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Bear Put Spread",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "ATM", "option_type": "PE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM3", "option_type": "PE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524150PE", "exchange": "NFO", "offset": "ATM", "option_type": "PE", "action": "BUY", "status": "success", "orderid": "240123000001246"},
        {"leg": 2, "symbol": "NIFTY30DEC2524000PE", "exchange": "NFO", "offset": "OTM3", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001247"}
    ]
}
```

#### 7. Iron Butterfly (4 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Iron Butterfly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "OTM5", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM5", "option_type": "PE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524400CE", "exchange": "NFO", "offset": "OTM5", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001248"},
        {"leg": 2, "symbol": "NIFTY30DEC2523900PE", "exchange": "NFO", "offset": "OTM5", "option_type": "PE", "action": "BUY", "status": "success", "orderid": "240123000001249"},
        {"leg": 3, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001250"},
        {"leg": 4, "symbol": "NIFTY30DEC2524150PE", "exchange": "NFO", "offset": "ATM", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001251"}
    ]
}
```

#### 8. Long Call Butterfly (3 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Long Call Butterfly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "legs": [
        {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75},
        {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 150},
        {"offset": "OTM2", "option_type": "CE", "action": "BUY", "quantity": 75}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524050CE", "exchange": "NFO", "offset": "ITM2", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001252"},
        {"leg": 2, "symbol": "NIFTY30DEC2524250CE", "exchange": "NFO", "offset": "OTM2", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001253"},
        {"leg": 3, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001254"}
    ]
}
```

#### 9. Call Ratio Spread (1:2 Ratio)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Call Ratio Spread",
    "underlying": "BANKNIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "legs": [
        {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 30},
        {"offset": "OTM3", "option_type": "CE", "action": "SELL", "quantity": 60}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "BANKNIFTY",
    "underlying_ltp": 51200.00,
    "results": [
        {"leg": 1, "symbol": "BANKNIFTY30DEC2551200CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001255"},
        {"leg": 2, "symbol": "BANKNIFTY30DEC2551500CE", "exchange": "NFO", "offset": "OTM3", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001256"}
    ]
}
```

#### 10. Jade Lizard (3 Legs)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Jade Lizard",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "OTM5", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0},
        {"offset": "OTM3", "option_type": "PE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524400CE", "exchange": "NFO", "offset": "OTM5", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001257"},
        {"leg": 2, "symbol": "NIFTY30DEC2524250CE", "exchange": "NFO", "offset": "OTM2", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001258"},
        {"leg": 3, "symbol": "NIFTY30DEC2524000PE", "exchange": "NFO", "offset": "OTM3", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001259"}
    ]
}
```

#### 11. Put Ratio Spread (1:2 Ratio)

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Put Ratio Spread",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "legs": [
        {"offset": "ATM", "option_type": "PE", "action": "BUY", "quantity": 75},
        {"offset": "OTM3", "option_type": "PE", "action": "SELL", "quantity": 150}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30DEC2524150PE", "exchange": "NFO", "offset": "ATM", "option_type": "PE", "action": "BUY", "status": "success", "orderid": "240123000001260"},
        {"leg": 2, "symbol": "NIFTY30DEC2524000PE", "exchange": "NFO", "offset": "OTM3", "option_type": "PE", "action": "SELL", "status": "success", "orderid": "240123000001261"}
    ]
}
```

#### 12. Calendar Spread (Different Expiries - Single API Call)

**Note:** Calendar spreads use the same strike but different expiry dates. Use per-leg `expiry_date` to specify different expiries.

**Request:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Calendar Spread",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30JAN26", "splitsize": 0},
        {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30JAN2624150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001262"},
        {"leg": 2, "symbol": "NIFTY30DEC2524150CE", "exchange": "NFO", "offset": "ATM", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001263"}
    ]
}
```

#### 13. Diagonal Spread (Different Strikes & Expiries - Single API Call)

**Note:** Diagonal spreads combine different strike prices AND different expiry dates. Use per-leg `expiry_date` to specify different expiries.

**Request (Bullish Diagonal Call Spread):**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "Diagonal Spread",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "legs": [
        {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30JAN26", "splitsize": 0},
        {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "30DEC25", "splitsize": 0}
    ]
}
```

**Response:**
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {"leg": 1, "symbol": "NIFTY30JAN2624050CE", "exchange": "NFO", "offset": "ITM2", "option_type": "CE", "action": "BUY", "status": "success", "orderid": "240123000001264"},
        {"leg": 2, "symbol": "NIFTY30DEC2524250CE", "exchange": "NFO", "offset": "OTM2", "option_type": "CE", "action": "SELL", "status": "success", "orderid": "240123000001265"}
    ]
}
```

**Note:** BUY legs always execute first for margin efficiency, regardless of order in the request.

####

### Product Types for Options

| Product | Description            | Margin | Square-off     | Use Case            |
| ------- | ---------------------- | ------ | -------------- | ------------------- |
| MIS     | Margin Intraday        | Lower  | Auto (3:15 PM) | Intraday trading    |
| NRML    | Normal (Carry Forward) | Higher | Manual         | Overnight positions |

**Note**: CNC (Cash & Carry) is not supported for options trading.

####

### Error Response

```json
{
    "status": "error",
    "message": "Validation error",
    "errors": {
        "legs": ["Legs must contain 1 to 20 items."]
    }
}
```

####

### Partial Success Response

```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24150.50,
    "results": [
        {
            "leg": 1,
            "symbol": "NIFTY30DEC2524650CE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "status": "success",
            "orderid": "240123000001234"
        },
        {
            "leg": 2,
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "status": "error",
            "message": "Insufficient funds"
        }
    ]
}
```

####

### Common Error Messages

| Error Message                       | Cause                           | Solution                     |
| ----------------------------------- | ------------------------------- | ---------------------------- |
| Invalid openalgo apikey             | API key is incorrect or expired | Check API key in settings    |
| Option symbol not found             | Calculated strike doesn't exist | Check offset and expiry\_date |
| Quantity must be a positive integer | Invalid quantity value          | Provide valid quantity       |
| Insufficient funds                  | Not enough margin (Live mode)   | Add funds or reduce quantity |
| Master contract needs update        | Symbol database is outdated     | Update master contract data  |
| Legs must contain 1 to 20 items     | Too many or no legs provided    | Provide 1-20 legs            |

####

### Features

1. **Multi-Leg Execution**: Execute up to 20 legs in a single API call
2. **BUY-First Strategy**: Automatically executes BUY legs before SELL for margin efficiency
3. **Parallel Execution**: Legs within same group (BUY/SELL) execute in parallel
4. **Auto Symbol Resolution**: Automatically calculates ATM and resolves option symbols
5. **Dual Mode Support**: Works in both Live and Analyze (Sandbox) modes
6. **All Order Types**: Supports MARKET, LIMIT, SL, and SL-M orders per leg
7. **Real-time LTP**: Uses current market price for ATM calculation
8. **Strategy Tracking**: Associates all legs with strategy name for analytics
9. **Telegram Alerts**: Automatic notifications for order placement
10. **Partial Success Handling**: Returns status for each leg individually

####

### Rate Limiting

* **Limit**: 10 requests per second
* **Scope**: Per API endpoint
* **Response**: 429 status code if limit exceeded

####

### Best Practices

1. **Test in Analyze Mode First**: Enable Analyze Mode to test strategies without real money
2. **Verify Lot Sizes**: Ensure all leg quantities are multiples of lot size
3. **Verify Offset**: Ensure offset value is valid (ATM, ITM1-ITM50, OTM1-OTM50)
4. **Use Appropriate Product**: MIS for intraday, NRML for overnight
5. **Handle Partial Failures**: Check status of each leg in response
6. **Monitor Margin**: Check available margin before placing multi-leg orders
7. **Update Master Contracts**: Keep symbol database updated for accurate symbol resolution
8. **Consistent Quantities**: Use same quantity across legs for proper hedging
9. **Use BUY-First Design**: Let the API handle execution order for margin benefits

####

### Comparison with Single Options Order

| Feature             | optionsorder           | optionsmultiorder            |
| ------------------- | ---------------------- | ---------------------------- |
| Legs per call       | 1                      | 1-20                         |
| API calls needed    | Multiple for strategy  | Single for entire strategy   |
| Execution control   | Manual sequencing      | Automatic BUY-first          |
| Margin efficiency   | Depends on order       | Optimized automatically      |
| Error handling      | Per order              | Per leg with partial success |
| Latency             | Higher (multiple RTT)  | Lower (single RTT)           |

####

### Use Cases

1. **Spread Strategies**: Bull/Bear spreads, ratio spreads
2. **Volatility Strategies**: Straddles, strangles, butterflies
3. **Income Strategies**: Iron condors, jade lizards
4. **Hedging**: Multi-leg protective positions
5. **Complex Combos**: Custom multi-leg strategies
