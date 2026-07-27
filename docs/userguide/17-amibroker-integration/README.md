# 17 - Amibroker Integration

## Introduction

Amibroker is a powerful technical analysis and backtesting software widely used by Indian traders. OpenAlgo provides seamless integration via its HTTP API, allowing your Amibroker strategies to execute trades automatically.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Amibroker → OpenAlgo Flow                                │
│                                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐  │
│  │  Amibroker  │     │    HTTP     │     │  OpenAlgo   │     │  Broker  │  │
│  │    AFL      │────▶│   Request   │────▶│   Server    │────▶│   API    │  │
│  │   Signal    │     │             │     │             │     │          │  │
│  └─────────────┘     └─────────────┘     └─────────────┘     └──────────┘  │
│                                                                              │
│  AFL condition       WinHTTP sends       Validates &         Executes       │
│  generates signal    JSON to API         processes           trade          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. Amibroker 6.0 or later
2. OpenAlgo running on same machine or network
3. API key generated in OpenAlgo
4. Broker connected and logged in

## Basic AFL Integration

### Simple HTTP Function

Add this function to your AFL code:

```afl
function SendOpenAlgoOrder(apiKey, strategy, symbol, exchange, action, quantity, priceType, product)
{
    // Build JSON payload
    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"" + exchange + "\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + quantity + "\",";
    json += "\"pricetype\": \"" + priceType + "\",";
    json += "\"product\": \"" + product + "\"";
    json += "}";

    // Send HTTP request
    url = "http://127.0.0.1:5000/api/v1/placeorder";

    ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

    if(ih)
    {
        response = InternetReadString(ih);
        InternetClose(ih);
        return response;
    }

    return "Error: Failed to connect";
}
```

### Using the Function

```afl
// Strategy logic
Buy = Cross(MA(C, 9), MA(C, 21));
Sell = Cross(MA(C, 21), MA(C, 9));

// Configuration
apiKey = "YOUR_API_KEY_HERE";
strategy = "AmibrokerMA";
symbol = Name();
exchange = "NSE";
quantity = "100";
priceType = "MARKET";
product = "MIS";

// Send orders
if(LastValue(Buy) AND LastValue(Ref(Buy, -1)) == 0)
{
    response = SendOpenAlgoOrder(apiKey, strategy, symbol, exchange, "BUY", quantity, priceType, product);
    _TRACE("Buy Order: " + response);
}

if(LastValue(Sell) AND LastValue(Ref(Sell, -1)) == 0)
{
    response = SendOpenAlgoOrder(apiKey, strategy, symbol, exchange, "SELL", quantity, priceType, product);
    _TRACE("Sell Order: " + response);
}
```

## Complete AFL Template

### Full Integration Code

```afl
//=============================================================================
// OpenAlgo Integration Template for Amibroker
// Version: 1.0
//=============================================================================

// Configuration Section
_SECTION_BEGIN("OpenAlgo Configuration");

apiKey = ParamStr("API Key", "YOUR_API_KEY");
baseUrl = ParamStr("OpenAlgo URL", "http://127.0.0.1:5000");
strategy = ParamStr("Strategy Name", "AmibrokerStrategy");
exchange = ParamList("Exchange", "NSE|NFO|BSE|MCX|CDS");
product = ParamList("Product", "MIS|CNC|NRML");
quantity = Param("Quantity", 100, 1, 10000, 1);
enableLive = ParamToggle("Enable Live Trading", "No|Yes", 0);

_SECTION_END();

//=============================================================================
// HTTP Functions
//=============================================================================

function PlaceOrder(action)
{
    global apiKey, baseUrl, strategy, exchange, product, quantity;

    symbol = Name();

    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"" + exchange + "\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + NumToStr(quantity, 1.0, False) + "\",";
    json += "\"pricetype\": \"MARKET\",";
    json += "\"product\": \"" + product + "\"";
    json += "}";

    url = baseUrl + "/api/v1/placeorder";

    ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

    if(ih)
    {
        response = InternetReadString(ih);
        InternetClose(ih);
        _TRACE("Order Response: " + response);
        return True;
    }

    _TRACE("Order Failed: Connection error");
    return False;
}

function PlaceSmartOrder(action, posSize)
{
    global apiKey, baseUrl, strategy, exchange, product, quantity;

    symbol = Name();

    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"" + exchange + "\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + NumToStr(quantity, 1.0, False) + "\",";
    json += "\"position_size\": \"" + NumToStr(posSize, 1.0, False) + "\",";
    json += "\"pricetype\": \"MARKET\",";
    json += "\"product\": \"" + product + "\"";
    json += "}";

    url = baseUrl + "/api/v1/placesmartorder";

    ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

    if(ih)
    {
        response = InternetReadString(ih);
        InternetClose(ih);
        _TRACE("Smart Order Response: " + response);
        return True;
    }

    return False;
}

//=============================================================================
// Your Strategy Logic
//=============================================================================

_SECTION_BEGIN("Strategy Logic");

// Moving Average Crossover Example
fastPeriod = Param("Fast MA", 9, 5, 50, 1);
slowPeriod = Param("Slow MA", 21, 10, 200, 1);

fastMA = MA(C, fastPeriod);
slowMA = MA(C, slowPeriod);

// Generate signals
Buy = Cross(fastMA, slowMA);
Sell = Cross(slowMA, fastMA);
Short = Sell;
Cover = Buy;

// Plot
Plot(C, "Price", colorDefault, styleCandle);
Plot(fastMA, "Fast MA", colorGreen, styleLine);
Plot(slowMA, "Slow MA", colorRed, styleLine);

_SECTION_END();

//=============================================================================
// Order Execution
//=============================================================================

_SECTION_BEGIN("Order Execution");

// Static variable to track last signal
lastSignal = StaticVarGet(Name() + "_lastSignal");

// Current bar signal
currentBuy = LastValue(Buy);
currentSell = LastValue(Sell);

// Check for new signal (not duplicate)
newBuySignal = currentBuy AND lastSignal != 1;
newSellSignal = currentSell AND lastSignal != -1;

// Execute if live trading enabled
if(enableLive)
{
    if(newBuySignal)
    {
        PlaceOrder("BUY");
        StaticVarSet(Name() + "_lastSignal", 1);
        _TRACE("BUY signal sent for " + Name());
    }

    if(newSellSignal)
    {
        PlaceOrder("SELL");
        StaticVarSet(Name() + "_lastSignal", -1);
        _TRACE("SELL signal sent for " + Name());
    }
}

// Display status
Title = Name() + " | Last Signal: " +
        WriteIf(lastSignal == 1, "BUY",
        WriteIf(lastSignal == -1, "SELL", "NONE")) +
        " | Live: " + WriteIf(enableLive, "ENABLED", "DISABLED");

_SECTION_END();
```

## Smart Order Integration

### Position-Aware Trading

```afl
// Smart order for reversal strategy
function ExecuteSmartOrder(signal)
{
    global apiKey, baseUrl, strategy, exchange, product, quantity;

    symbol = Name();

    // Determine position size
    if(signal == 1) // Long
    {
        action = "BUY";
        posSize = quantity;  // Positive for long
    }
    else if(signal == -1) // Short
    {
        action = "SELL";
        posSize = -quantity;  // Negative for short
    }
    else // Flat
    {
        action = "SELL";
        posSize = 0;
    }

    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"" + exchange + "\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + NumToStr(quantity, 1.0, False) + "\",";
    json += "\"position_size\": \"" + NumToStr(posSize, 1.0, False) + "\",";
    json += "\"pricetype\": \"MARKET\",";
    json += "\"product\": \"" + product + "\"";
    json += "}";

    url = baseUrl + "/api/v1/placesmartorder";

    ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

    if(ih)
    {
        response = InternetReadString(ih);
        InternetClose(ih);
        return response;
    }

    return "Error";
}
```

## Multiple Symbol Scanning

### Exploration-Based Execution

```afl
// Run this in Exploration mode
// Scans multiple symbols and sends orders

if(Status("action") == actionExplore)
{
    Buy = Cross(MA(C, 9), MA(C, 21));
    Sell = Cross(MA(C, 21), MA(C, 9));

    // Only send order for current bar signals
    if(LastValue(Buy))
    {
        PlaceOrder("BUY");
        AddColumn(1, "Signal", 1.0);
        AddTextColumn("BUY", "Action");
    }
    else if(LastValue(Sell))
    {
        PlaceOrder("SELL");
        AddColumn(-1, "Signal", 1.0);
        AddTextColumn("SELL", "Action");
    }

    AddColumn(C, "Close", 1.2);

    // Filter to show only signals
    Filter = Buy OR Sell;
}
```

## Auto-Trading Setup

### Using Amibroker Scheduler

1. **Create Analysis Window**
   - Open Analysis → New Analysis
   - Load your AFL
   - Set up watchlist/symbol list

2. **Configure Auto-Repeat**
   - Click "Auto-repeat" in Analysis window
   - Set interval (e.g., 1 minute)
   - Select "Scan" or "Explore"

3. **Run During Market Hours**

```afl
// Add market hours check
function IsMarketOpen()
{
    currentHour = Hour();
    currentMin = Minute();
    currentTime = currentHour * 100 + currentMin;

    // NSE: 9:15 AM to 3:30 PM
    marketOpen = 915;
    marketClose = 1530;

    return currentTime >= marketOpen AND currentTime <= marketClose;
}

// Only trade during market hours
if(enableLive AND IsMarketOpen())
{
    // Execute orders
}
```

## F&O Trading

### Options Order Example

```afl
// For options, you need to specify the full symbol
// Format: SYMBOL + EXPIRY + STRIKE + CE/PE

optionSymbol = "NIFTY25JAN21500CE";
optionExchange = "NFO";
optionProduct = "NRML";

function PlaceOptionsOrder(symbol, action, qty)
{
    global apiKey, baseUrl, strategy;

    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"NFO\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + NumToStr(qty, 1.0, False) + "\",";
    json += "\"pricetype\": \"MARKET\",";
    json += "\"product\": \"NRML\"";
    json += "}";

    url = baseUrl + "/api/v1/placeorder";

    ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

    if(ih)
    {
        response = InternetReadString(ih);
        InternetClose(ih);
        return response;
    }

    return "Error";
}

// Usage
if(LastValue(Buy))
{
    PlaceOptionsOrder(optionSymbol, "BUY", 50);
}
```

## Error Handling

### Robust Order Function

```afl
function SafePlaceOrder(action)
{
    global apiKey, baseUrl, strategy, exchange, product, quantity;

    // Validate inputs
    if(StrLen(apiKey) < 10)
    {
        _TRACE("Error: Invalid API key");
        return False;
    }

    symbol = Name();
    if(StrLen(symbol) == 0)
    {
        _TRACE("Error: No symbol selected");
        return False;
    }

    // Build and send request
    json = "{";
    json += "\"apikey\": \"" + apiKey + "\",";
    json += "\"strategy\": \"" + strategy + "\",";
    json += "\"symbol\": \"" + symbol + "\",";
    json += "\"exchange\": \"" + exchange + "\",";
    json += "\"action\": \"" + action + "\",";
    json += "\"quantity\": \"" + NumToStr(quantity, 1.0, False) + "\",";
    json += "\"pricetype\": \"MARKET\",";
    json += "\"product\": \"" + product + "\"";
    json += "}";

    url = baseUrl + "/api/v1/placeorder";

    // Retry logic
    maxRetries = 3;
    retryCount = 0;

    while(retryCount < maxRetries)
    {
        ih = InternetOpenURL(url, "POST", json, "Content-Type: application/json");

        if(ih)
        {
            response = InternetReadString(ih);
            InternetClose(ih);

            // Check for success
            if(StrFind(response, "success") > 0)
            {
                _TRACE("Order successful: " + response);
                return True;
            }
            else
            {
                _TRACE("Order failed: " + response);
            }
        }

        retryCount++;
        _TRACE("Retry " + NumToStr(retryCount, 1.0, False));
    }

    _TRACE("Order failed after " + NumToStr(maxRetries, 1.0, False) + " retries");
    return False;
}
```

## Debugging

### Using TRACE for Logging

```afl
// Enable trace output
SetOption("Debug", True);

// Log everything
_TRACE("=== Order Attempt ===");
_TRACE("Symbol: " + Name());
_TRACE("Action: " + action);
_TRACE("Quantity: " + NumToStr(quantity, 1.0, False));
_TRACE("JSON: " + json);
_TRACE("Response: " + response);
```

View logs in: **Window → Trace**

## Best Practices

### 1. Prevent Duplicate Orders

```afl
// Use static variables
lastOrderTime = StaticVarGet(Name() + "_lastOrderTime");
currentTime = Now();

// Only allow order every 60 seconds
if(DateTimeDiff(currentTime, lastOrderTime) > 60)
{
    PlaceOrder("BUY");
    StaticVarSet(Name() + "_lastOrderTime", currentTime);
}
```

### 2. Test in Analyzer Mode

Always test with Analyzer Mode enabled in OpenAlgo first.

### 3. Use Limit on Position

```afl
// Maximum position limit
maxPosition = 500;
currentPosition = StaticVarGet(Name() + "_position");

if(currentPosition < maxPosition)
{
    PlaceOrder("BUY");
    StaticVarSet(Name() + "_position", currentPosition + quantity);
}
```

### 4. Market Hours Only

```afl
// Only trade during market hours
dayOfWeek = DayOfWeek();
isWeekday = dayOfWeek >= 1 AND dayOfWeek <= 5;

if(isWeekday AND IsMarketOpen())
{
    // Execute trades
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check OpenAlgo is running |
| Invalid API key | Verify key in OpenAlgo |
| Order not executing | Check broker login status |
| Duplicate orders | Implement duplicate prevention |
| Symbol not found | Verify symbol in master contract |

---

**Previous**: [16 - TradingView Integration](../16-tradingview-integration/README.md)

**Next**: [18 - ChartInk Integration](../18-chartink-integration/README.md)
