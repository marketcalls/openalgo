# Option Greeks API

## Endpoint URL

This API Function Calculates Option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility using Black-76 Model

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optiongreeks
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optiongreeks
Custom Domain:  POST https://<your-custom-domain>/api/v1/optiongreeks
```

## Why Black-76 Model?

OpenAlgo uses the **Black-76 model** (via py_vollib library) instead of Black-Scholes for calculating option Greeks. This is the correct choice for Indian F&O markets:

| Model | Designed For | Used In |
|-------|--------------|---------|
| Black-Scholes | Stock options (spot-settled) | US equity options |
| **Black-76** | Options on futures/forwards | **NFO, BFO, MCX, CDS** |

**Key Benefits:**
- Accurate pricing for options on futures and forwards
- Industry-standard model used by NSE, BSE, MCX
- Greeks match with professional trading platforms
- Proper handling of cost of carry

## Prerequisites

1. **py_vollib Library Required**
   - Install with: `pip install py_vollib`
   - Or with uv: `uv pip install py_vollib`
   - Required for Black-76 calculations

2. **Market Data Access**
   - Requires real-time LTP for underlying and option
   - Uses OpenAlgo quotes API internally

3. **Valid API Key**
   - API key must be active and valid
   - Get API key from OpenAlgo settings

## Sample API Request (NFO - NIFTY Option with Auto-Detected Spot)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO"
}
```

**Note**: Auto-detects NIFTY from NSE_INDEX (spot price: 26240) as underlying

###

## Sample API Request (Explicit Underlying with Zero Interest Rate)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526100CE",
    "exchange": "NFO",
    "interest_rate": 0,
    "underlying_symbol": "NIFTY",
    "underlying_exchange": "NSE_INDEX"
}
```

**Note**: Explicitly specifies NIFTY spot (26240) from NSE_INDEX. Using interest_rate: 0 for theoretical calculations or when interest rate impact is negligible.

###

## Sample API Request (With Custom Forward Price - Synthetic Futures)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26350,
    "interest_rate": 6.5
}
```

**Note**: Uses custom forward price (26350) for Greeks calculation. Useful for:
- **Synthetic futures pricing**: Calculate forward price as `Spot x e^(rT)`
- **Illiquid underlyings**: FINNIFTY, MIDCPNIFTY where futures may be illiquid
- **Custom scenarios**: Test Greeks with specific forward price assumptions

###

## Sample API Response (Success)

```json
{
    "status": "success",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "strike": 26000,
    "option_type": "CE",
    "expiry_date": "02-Dec-2025",
    "days_to_expiry": 2.25,
    "spot_price": 26240,
    "option_price": 285.50,
    "interest_rate": 0,
    "implied_volatility": 14.85,
    "greeks": {
        "delta": 0.6125,
        "gamma": 0.000892,
        "theta": -8.4532,
        "vega": 22.4567,
        "rho": 0.001245
    }
}
```

**Note**: Greeks are in trader-friendly units - Theta is daily decay, Vega is per 1% IV change.

###

## Sample API Request (Using Futures as Underlying)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY30DEC25FUT",
    "underlying_exchange": "NFO"
}
```

**Note**: Uses futures price (26396) instead of spot (26240) for calculations. Useful when options are based on futures pricing.

###

## Sample API Response (Success - With Futures)

```json
{
    "status": "success",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "strike": 26000,
    "option_type": "CE",
    "expiry_date": "30-Dec-2025",
    "days_to_expiry": 30.25,
    "spot_price": 26396,
    "option_price": 525.75,
    "interest_rate": 0,
    "implied_volatility": 13.25,
    "greeks": {
        "delta": 0.6234,
        "gamma": 0.000425,
        "theta": -4.2678,
        "vega": 45.7654,
        "rho": 0.004234
    }
}
```

**Note**: Shows default `interest_rate: 0`. For long-dated options, specify current RBI repo rate for accurate Rho.

###

## Sample API Request (With Custom Interest Rate)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526100CE",
    "exchange": "NFO",
    "interest_rate": 6.5
}
```

**Note**: Explicitly specify interest rate (e.g., 6.5%) for accurate Rho calculations, especially for long-dated options.

###

## Sample API Request (CDS - Currency Option)

```json
{
    "apikey": "your_api_key",
    "symbol": "USDINR30DEC2585.50CE",
    "exchange": "CDS"
}
```

###

## Sample API Request (MCX - Commodity Option with Custom Expiry Time)

```json
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17DEC255400CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

**Note**: MCX contracts have different expiry times. Crude Oil expires at 7:00 PM (19:00), so specify custom expiry time.

###

## Sample API Request (MCX - NATURALGAS at 19:00)

```json
{
    "apikey": "your_api_key",
    "symbol": "NATURALGAS30DEC25300CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

**Note**: Natural Gas expires at 7:00 PM (19:00). Always specify correct expiry time for MCX.

###

## Parameter Description

| Parameters           | Description                                          | Mandatory/Optional | Default Value |
| -------------------- | ---------------------------------------------------- | ------------------ | ------------- |
| apikey               | App API key                                          | Mandatory          | -             |
| symbol               | Option symbol (e.g., NIFTY02DEC2526000CE)           | Mandatory          | -             |
| exchange             | Exchange code (NFO, BFO, CDS, MCX)                  | Mandatory          | -             |
| interest_rate        | Risk-free interest rate (annualized %). Specify current RBI repo rate (e.g., 6.5, 6.75) for accurate Rho calculations. Use 0 for theoretical calculations or when interest rate impact is negligible | Optional | 0 |
| forward_price        | Custom forward/synthetic futures price. If provided, skips underlying price fetch. Useful for synthetic futures (Spot x e^rT) or illiquid underlyings like FINNIFTY, MIDCPNIFTY | Optional | Auto-fetched |
| underlying_symbol    | Custom underlying symbol (e.g., NIFTY or NIFTY30DEC25FUT) | Optional | Auto-detected |
| underlying_exchange  | Custom underlying exchange (e.g., NSE_INDEX or NFO) | Optional           | Auto-detected |
| expiry_time          | Custom expiry time in HH:MM format (e.g., "17:00", "19:00"). Required for MCX contracts with non-standard expiry times | Optional | Exchange defaults: NFO/BFO=15:30, CDS=12:30, MCX=23:30 |

**Notes**:
- **Interest Rate**: Default is 0. For accurate Greeks (especially Rho), specify current RBI repo rate (typically 6.25-7.0%). Interest rate has minimal impact on short-term options (< 7 days).
- **Forward Price**: When provided, the API uses this value directly instead of fetching underlying price. Calculate synthetic futures as: `Forward = Spot x e^(r x T)` where r is interest rate and T is time to expiry in years.
- Use `underlying_symbol` and `underlying_exchange` to choose between spot and futures as underlying. If not specified, automatically uses spot price.
- Use `expiry_time` for MCX commodities that don't expire at the default 23:30. See MCX Commodity Expiry Times section below.

###

## Response Parameters

| Parameter           | Description                              | Type    |
| ------------------- | ---------------------------------------- | ------- |
| status              | API response status (success/error)      | string  |
| symbol              | Option symbol                            | string  |
| exchange            | Exchange code                            | string  |
| underlying          | Underlying symbol                        | string  |
| strike              | Strike price                             | number  |
| option_type         | Option type (CE/PE)                      | string  |
| expiry_date         | Expiry date (formatted)                  | string  |
| days_to_expiry      | Days remaining to expiry                 | number  |
| spot_price          | Underlying spot/futures/forward price    | number  |
| option_price        | Current option premium                   | number  |
| interest_rate       | Interest rate used                       | number  |
| implied_volatility  | Implied Volatility (%)                   | number  |
| greeks              | Object containing Greeks                 | object  |
| greeks.delta        | Delta (rate of change of option price)   | number  |
| greeks.gamma        | Gamma (rate of change of delta)          | number  |
| greeks.theta        | Theta (time decay per day)               | number  |
| greeks.vega         | Vega (sensitivity to volatility per 1%)  | number  |
| greeks.rho          | Rho (sensitivity to interest rate)       | number  |

###

## Understanding Greeks

### Delta
- **Range**: -1 to +1 (Call: 0 to 1, Put: -1 to 0)
- **Meaning**: Change in option price for Rs.1 change in underlying
- **Example**: Delta of 0.6 means option moves Rs.0.60 for Rs.1 move in underlying
- **Use**: Position sizing, hedge ratio calculation

### Gamma
- **Range**: 0 to infinity (same for Call and Put)
- **Meaning**: Change in Delta for Rs.1 change in underlying
- **Example**: Gamma of 0.001 means Delta increases by 0.001 for Rs.1 rise
- **Use**: Delta hedging frequency, risk assessment

### Theta
- **Range**: Negative for long options
- **Meaning**: Change in option price per day (time decay)
- **Example**: Theta of -8.45 means option loses Rs.8.45 per day
- **Use**: Time decay analysis, optimal holding period
- **Note**: py_vollib returns theta in trader-friendly daily units

### Vega
- **Range**: Positive for long options
- **Meaning**: Change in option price for 1% change in IV
- **Example**: Vega of 22.45 means option gains Rs.22.45 if IV rises by 1%
- **Use**: Volatility trading, event plays
- **Note**: py_vollib returns vega per 1% IV change (no conversion needed)

### Rho
- **Range**: Positive for Calls, Negative for Puts
- **Meaning**: Change in option price for 1% change in interest rate
- **Example**: Rho of 0.05 means option gains Rs.0.05 for 1% rate rise
- **Use**: Long-term options, rate-sensitive strategies

###

## Forward Price Parameter - Detailed Guide

The `forward_price` parameter allows you to specify a custom forward/futures price for Greeks calculation instead of fetching the underlying price automatically.

### When to Use forward_price

1. **Illiquid Futures**: FINNIFTY, MIDCPNIFTY futures may have low liquidity
2. **Synthetic Futures**: Calculate theoretical forward price from spot
3. **Custom Scenarios**: Test Greeks with specific price assumptions
4. **Arbitrage Analysis**: Use your calculated fair value

### Calculating Synthetic Futures Price

```python
import math

spot = 26240          # Current NIFTY spot
r = 0.065             # Interest rate (6.5% annualized)
T = 2 / 365           # Time to expiry in years (2 days for 02DEC25)

forward_price = spot * math.exp(r * T)
# forward_price = 26240 * e^(0.065 * 0.00548)
# forward_price = 26249.36

# For 30 days to expiry (30DEC25):
T_30 = 30 / 365
forward_30 = spot * math.exp(r * T_30)
# forward_30 = 26240 * e^(0.065 * 0.0822)
# forward_30 = 26380.45
```

### Example: NIFTY with Synthetic Forward (02DEC25)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26350,
    "interest_rate": 6.5
}
```

### Example: NIFTY with Futures Price (30DEC25)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526100CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY30DEC25FUT",
    "underlying_exchange": "NFO"
}
```

### forward_price vs underlying_symbol

| Parameter | Use Case | Price Source |
|-----------|----------|--------------|
| `forward_price` | Custom/synthetic forward | User-provided value (e.g., 26350) |
| `underlying_symbol` | Specific underlying | Fetched from broker (e.g., 26396) |
| Neither | Auto-detect | Fetched from broker (spot: 26240) |

**Priority**: If `forward_price` is provided, it takes precedence and `underlying_symbol`/`underlying_exchange` are ignored.

###

## Supported Exchanges and Symbols

### NFO (NSE Futures & Options)

**Index Options:**
- NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY

**Equity Options:**
- All NSE stocks with F&O segment (RELIANCE, TCS, INFY, etc.)

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `NIFTY02DEC2526000CE`

**Expiry Time:** 3:30 PM (15:30 IST)

### BFO (BSE Futures & Options)

**Index Options:**
- SENSEX, BANKEX, SENSEX50

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `SENSEX30DEC2580000CE`

**Expiry Time:** 3:30 PM (15:30 IST)

### CDS (Currency Derivatives)

**Currency Pairs:**
- USDINR, EURINR, GBPINR, JPYINR

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `USDINR30DEC2585.50CE`
- Note: Strike can have decimals for currency options

**Expiry Time:** 12:30 PM (12:30 IST)

### MCX (Multi Commodity Exchange)

**Commodities:**
- GOLD, GOLDM, SILVER, SILVERM
- CRUDEOIL, NATURALGAS
- COPPER, ZINC, LEAD, ALUMINIUM

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `CRUDEOIL17DEC255400CE`

**Default Expiry Time:** 11:30 PM (23:30 IST)

**Important**: MCX commodities have different expiry times. Always specify `expiry_time` parameter for accurate Greeks calculation.

### MCX Commodity Expiry Times

Different MCX commodities expire at different times. Use the `expiry_time` parameter to specify the correct time:

| Commodity Category        | Expiry Time       | Format   | Example Request                    |
| ------------------------- | ----------------- | -------- | ---------------------------------- |
| **Precious Metals**       |                   |          |                                    |
| GOLD, GOLDM, GOLDPETAL    | 5:00 PM           | "17:00"  | `"expiry_time": "17:00"`          |
| SILVER, SILVERM, SILVERMIC| 5:00 PM           | "17:00"  | `"expiry_time": "17:00"`          |
| **Energy**                |                   |          |                                    |
| CRUDEOIL, CRUDEOILM       | 7:00 PM           | "19:00"  | `"expiry_time": "19:00"`          |
| NATURALGAS                | 7:00 PM           | "19:00"  | `"expiry_time": "19:00"`          |
| **Base Metals**           |                   |          |                                    |
| COPPER, ZINC, LEAD        | 5:00 PM           | "17:00"  | `"expiry_time": "17:00"`          |
| ALUMINIUM, NICKEL         | 5:00 PM           | "17:00"  | `"expiry_time": "17:00"`          |
| **Agri Commodities**      |                   |          |                                    |
| COTTONCANDY, MENTHAOIL    | 5:00 PM           | "17:00"  | `"expiry_time": "17:00"`          |

**API Request Examples:**

```json
// Crude Oil expires at 7:00 PM
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17DEC255400CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}

// Gold expires at 5:00 PM
{
    "apikey": "your_api_key",
    "symbol": "GOLD30DEC2575000CE",
    "exchange": "MCX",
    "expiry_time": "17:00"
}

// Natural Gas expires at 7:00 PM
{
    "apikey": "your_api_key",
    "symbol": "NATURALGAS30DEC25300CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

**Note**: If you don't specify `expiry_time`, it defaults to 23:30 (11:30 PM), which may give incorrect Greeks for most MCX commodities.

###

## API Request Examples: With and Without Optional Parameters

This section demonstrates various usage scenarios and when to use optional parameters.

### Example 1: Basic Request (No Optional Parameters)

**Scenario**: Calculate Greeks for NIFTY option using default settings

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO"
}
```

**What Happens**:
- Auto-detects NIFTY from NSE_INDEX (spot price: 26240)
- Uses default interest rate: 0%
- Uses default expiry time: 15:30 (NFO)
- Simplest usage - good for most traders

**When to Use**:
- Standard index options trading
- Short-term options (< 7 days) where interest rate impact is negligible
- When you don't need accurate Rho calculations

---

### Example 2: With Custom Interest Rate

**Scenario**: Calculate Greeks with current RBI repo rate for long-dated option

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "interest_rate": 6.5
}
```

**What Happens**:
- Uses 6.5% instead of default 0%
- Affects Rho calculation significantly
- Minor impact on other Greeks (< 0.5%)

**When to Use**:
- Long-dated options (> 30 days to expiry)
- Interest rate sensitive strategies (Rho hedging)
- Comparing with broker Greeks that use specific rates
- Professional trading requiring accurate Rho

**When NOT to Use**:
- Short-term weekly options (impact < 0.1%)
- Theoretical calculations (use default 0)

---

### Example 3: Using Futures as Underlying

**Scenario**: Calculate Greeks based on futures price (arbitrage trading)

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526100CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY30DEC25FUT",
    "underlying_exchange": "NFO"
}
```

**What Happens**:
- Uses NIFTY futures price (26396) instead of spot (26240)
- Futures price includes cost of carry
- Delta, IV may differ by 1-3% vs spot

**When to Use**:
- Arbitrage strategies (futures vs options)
- When broker uses futures for Greeks
- Professional trading desks

---

### Example 4: Using Custom Forward Price (Synthetic Futures)

**Scenario**: Calculate Greeks using synthetic forward price

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26350,
    "interest_rate": 6.5
}
```

**What Happens**:
- Uses user-provided forward price (26350) directly
- Skips underlying price fetch
- Ideal for custom pricing scenarios

**When to Use**:
- FINNIFTY, MIDCPNIFTY (illiquid futures)
- Testing with specific forward price assumptions
- Synthetic futures pricing strategies
- When broker futures LTP is stale or unreliable

**How to Calculate Synthetic Forward**:
```python
import math
spot = 26240
rate = 0.065
T = 2 / 365  # 2 days to expiry
forward = spot * math.exp(rate * T)
# forward = 26249.36 (or use market-observed 26350)
```

---

### Example 5: MCX with Custom Expiry Time

**Scenario**: Calculate Greeks for Crude Oil options (expires at 19:00)

```json
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17DEC255400CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

**What Happens**:
- Uses 19:00 (7 PM) expiry instead of default 23:30
- DTE calculated accurately
- Theta, IV more accurate on expiry day

**When to Use**:
- ALL MCX commodity options (except those expiring at 23:30)
- Critical for accurate Greeks on expiry day
- Gold, Silver, Copper: 17:00
- Natural Gas, Crude Oil: 19:00

---

### Example 6: Currency Options (CDS)

**Scenario**: USD/INR option (expires at 12:30)

```json
{
    "apikey": "your_api_key",
    "symbol": "USDINR30DEC2585.50CE",
    "exchange": "CDS"
}
```

**What Happens**:
- Auto-detects USDINR from CDS exchange
- Uses correct expiry time: 12:30 (CDS default)
- Supports decimal strikes (85.50)

**When to Use**: Currency derivatives trading

---

### Example 7: All Parameters Combined (Professional Setup)

**Scenario**: Maximum control with custom forward price and interest rate

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26396,
    "interest_rate": 6.5
}
```

**What Happens**:
- Custom forward price: 26396 (futures price)
- Custom interest rate: 6.5%
- Maximum control over calculation

**When to Use**:
- Institutional trading with specific requirements
- Research and backtesting
- Comparing with broker platforms
- Custom forward calculation scenarios

---

### Quick Reference: When to Use Optional Parameters

| Parameter           | Use When                                          | Don't Use When                    |
| ------------------- | ------------------------------------------------- | --------------------------------- |
| `interest_rate`     | Long-dated options, Rho analysis, matching broker | Short-term weekly options         |
| `forward_price`     | Illiquid futures, synthetic futures, custom scenarios | Liquid underlyings with reliable LTP |
| `underlying_symbol` | Arbitrage, comparing with broker, futures-based pricing | Standard spot-based trading     |
| `underlying_exchange` | Custom underlying setup                         | Auto-detection works fine         |
| `expiry_time`       | **ALWAYS for MCX** (except 23:30 contracts)      | NFO/BFO/CDS (already correct)     |

---

### Impact of Optional Parameters on Greeks

**Interest Rate (Default 0% -> Custom 6.5%)**:
- Rho: Significant change (from near-zero to meaningful value)
- Delta: +/-0.2-0.5% change (for long-dated options)
- Other Greeks: < 0.1% change
- **Impact**:
  - **High for Rho** (critical for interest rate sensitive strategies)
  - **Low for other Greeks** (especially short-term options)
  - **Negligible for < 7 days to expiry**

**Forward Price (26240 spot vs 26350 synthetic vs 26396 futures)**:
- Uses provided value instead of fetching
- All Greeks calculated based on this price
- **Impact**: Direct - all Greeks change proportionally

**Underlying: Spot (26240) vs Futures (26396) - ~0.6% difference**:
- Delta: +/-1-3% change
- IV: +/-0.2-0.5% change
- Other Greeks: +/-0.5-2% change
- **Impact**: Moderate

**Expiry Time (6 hours difference: 17:00 vs 23:30)**:
- DTE: 6 hours difference
- Theta: +/-10-30% change on expiry day
- IV: +/-2-8% change near expiry
- Gamma: +/-5-15% change near expiry
- **Impact**: High (especially near expiry)

---

## Exchange-Specific Expiry Times

| Exchange | Expiry Time     | Impact on DTE & Greeks                           |
| -------- | --------------- | ------------------------------------------------ |
| NFO      | 3:30 PM (15:30) | Standard - Most index & equity options          |
| BFO      | 3:30 PM (15:30) | Standard - BSE index options                     |
| CDS      | 12:30 PM (12:30)| Earlier expiry - Higher theta near expiry morning|
| MCX      | 11:30 PM (23:30)| Later expiry - More time value on expiry day    |

**DTE Calculation:**
- Days to Expiry (DTE) is calculated in years: `(expiry_datetime - current_datetime) / 365`
- Accurate expiry time ensures precise time decay (theta) calculations
- CDS options expire 3 hours before NFO/BFO, affecting same-day calculations
- MCX options have 8 extra hours compared to NFO/BFO on expiry day

**Example - Same Expiry Date, Different Times:**
```
Date: 02-Dec-2025 at 2:00 PM

CDS Option (USDINR02DEC2585.50CE):
  - Expired 1.5 hours ago (12:30 PM)
  - DTE: 0 (already expired)

NFO Option (NIFTY02DEC2526000CE):
  - Expires in 1.5 hours (3:30 PM)
  - DTE: 0.0063 years (~1.5 hours)

MCX Option (CRUDEOIL02DEC255400CE):
  - Expires in 5 hours (7:00 PM) [Crude Oil expires at 19:00]
  - DTE: 0.0208 years (~5 hours)
```

###

## Default Interest Rates by Exchange

| Exchange | Default Rate (%) | Description              |
| -------- | ---------------- | ------------------------ |
| NFO      | 0                | NSE F&O                  |
| BFO      | 0                | BSE F&O                  |
| CDS      | 0                | Currency Derivatives     |
| MCX      | 0                | Commodities              |

**Note**: Default is 0 for all exchanges. Explicitly specify `interest_rate` parameter (e.g., 6.5, 6.75) for accurate Rho calculations and when trading long-dated options.

**When to Specify Interest Rate**:
- Long-dated options (> 30 days to expiry)
- Interest rate sensitive strategies (Rho hedging)
- Matching with broker Greeks
- Short-term options (< 7 days) - minimal impact (optional)
- Theoretical or academic calculations (use 0)

###

## Error Responses

### py_vollib Library Not Installed

```json
{
    "status": "error",
    "message": "Option Greeks calculation requires py_vollib library. Install with: pip install py_vollib"
}
```

### Invalid Symbol Format

```json
{
    "status": "error",
    "message": "Invalid option symbol format: NIFTY26000CE"
}
```

### Option Expired

```json
{
    "status": "error",
    "message": "Option has expired on 28-Nov-2025"
}
```

### Underlying Price Not Available

```json
{
    "status": "error",
    "message": "Failed to fetch underlying price: Symbol not found"
}
```

### Option Price Not Available

```json
{
    "status": "error",
    "message": "Option LTP not available"
}
```

### Invalid Forward Price

```json
{
    "status": "error",
    "message": "Spot price and option price must be positive"
}
```

###

## Common Error Messages

| Error Message                                  | Cause                                | Solution                              |
| ---------------------------------------------- | ------------------------------------ | ------------------------------------- |
| py_vollib library not installed                | Missing dependency                   | Run: pip install py_vollib            |
| Invalid option symbol format                   | Symbol pattern doesn't match         | Use: SYMBOL[DD][MMM][YY][STRIKE][CE/PE] |
| Option has expired                             | Expiry date in the past              | Use current month contracts           |
| Failed to fetch underlying price               | Underlying symbol not found          | Verify symbol and exchange, or use forward_price |
| Option LTP not available                       | No trading data for option           | Check market hours, symbol validity   |
| Invalid openalgo apikey                        | API key incorrect                    | Verify API key in settings            |
| Spot price and option price must be positive   | Invalid forward_price value          | Provide positive forward_price        |

###

## How Expiry Times Affect Calculations

### Impact on Time to Expiry (DTE)

Accurate expiry times are critical for precise Greeks calculation. The API automatically uses exchange-specific expiry times:

**Time to Expiry Formula:**
```python
time_to_expiry = (expiry_datetime - current_datetime) / 365
```

**Example on Expiry Day (02-Dec-2025):**

| Time Now | CDS (12:30)    | NFO/BFO (15:30) | MCX (23:30)    |
| -------- | -------------- | --------------- | -------------- |
| 10:00 AM | 2.5 hrs (0.0104 yrs) | 5.5 hrs (0.0229 yrs) | 13.5 hrs (0.0563 yrs) |
| 12:00 PM | 0.5 hrs (0.0021 yrs) | 3.5 hrs (0.0146 yrs) | 11.5 hrs (0.0479 yrs) |
| 1:00 PM  | Expired (0 yrs)| 2.5 hrs (0.0104 yrs) | 10.5 hrs (0.0438 yrs) |
| 4:00 PM  | Expired (0 yrs)| Expired (0 yrs) | 7.5 hrs (0.0313 yrs) |

### Impact on Theta (Time Decay)

**Theta accelerates as expiry approaches:**

```
CDS at 11:00 AM (1.5 hours to expiry):
  Theta: -50 to -100 per day (very high decay)

NFO at 11:00 AM (4.5 hours to expiry):
  Theta: -30 to -60 per day (high decay)

MCX at 11:00 AM (12.5 hours to expiry):
  Theta: -15 to -30 per day (moderate decay)
```

**Key Insight**: On expiry day morning, CDS options decay faster than NFO/BFO, which decay faster than MCX.

### Impact on Implied Volatility

**Same option, different DTE affects IV calculation:**

- **More time** -> Lower IV for same premium (more time value)
- **Less time** -> Higher IV for same premium (less time value)

**Example:**
```
NIFTY 26000CE Option Premium: Rs.285

At 10:00 AM (5.5 hrs to NFO expiry):
  Implied IV: ~14%

At 3:00 PM (0.5 hrs to NFO expiry):
  Implied IV: ~28%
  (Same premium, but much higher IV due to less time)
```

### Impact on Delta

**Delta is less affected** by small DTE changes, but:

- Very near expiry (< 1 hour), delta can shift rapidly
- ATM options approach delta of 0.5 faster
- Deep ITM -> 1.0, Deep OTM -> 0.0 faster near expiry

### Impact on Gamma

**Gamma peaks near expiry** for ATM options:

```
NIFTY 26000CE (Spot: 26240):

7 days before expiry:
  Gamma: ~0.0004

1 day before expiry:
  Gamma: ~0.001 (2.5x higher)

1 hour before expiry:
  Gamma: ~0.01 (25x higher - very sensitive!)
```

### Impact on Vega

**Vega decreases as expiry approaches:**

```
NIFTY 26000CE:

30 days to expiry (30DEC25):
  Vega: ~45 (high sensitivity to IV)

7 days to expiry:
  Vega: ~22

1 day to expiry:
  Vega: ~8 (low sensitivity)
```

### Practical Implications

1. **Trading on Expiry Day:**
   - CDS options lose time value fastest (expire by lunch)
   - NFO/BFO options decay rapidly in afternoon
   - MCX options have full day to trade

2. **IV Calculations:**
   - Use correct expiry time to avoid IV calculation errors
   - Wrong expiry time can show IV off by 2-5% near expiry

3. **Theta Strategies:**
   - CDS theta decay is most aggressive in morning
   - MCX theta spreads decay over longer period

4. **Gamma Scalping:**
   - CDS gamma peaks earlier in the day
   - NFO gamma highest 12-3 PM on expiry
   - MCX gamma peaks late evening

###

## Spot vs Futures vs Forward Price

### When to Use Spot (Default)

**Best For**:
- Index options (NIFTY, BANKNIFTY) with liquid spot
- Currency options (USDINR, EURINR)
- Most traders prefer spot for simplicity

**Example**:
```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO"
}
```
Auto-detects NIFTY spot (26240) from NSE_INDEX

### When to Use Futures

**Best For**:
- Arbitrage strategies
- When option pricing is based on futures
- Comparing with broker Greeks that use futures
- Professional trading desks

**Example - Using Futures**:
```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY30DEC25FUT",
    "underlying_exchange": "NFO"
}
```
Uses NIFTY futures (26396) instead of spot (26240)

### When to Use Forward Price

**Best For**:
- Illiquid futures (FINNIFTY, MIDCPNIFTY)
- Synthetic futures pricing
- Custom scenario analysis
- When broker futures LTP is unreliable

**Example - Using Forward Price**:
```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY02DEC2526100CE",
    "exchange": "NFO",
    "forward_price": 26350,
    "interest_rate": 6.5
}
```
Uses custom synthetic forward (26350)

### Comparison

| Method | Price Used | Use Case | Pros | Cons |
|--------|------------|----------|------|------|
| Spot (default) | 26240 | Standard trading | Simple, reliable | May differ from futures-based pricing |
| Futures | 26396 | Arbitrage, broker matching | Matches market pricing | Requires liquid futures |
| Forward Price | 26350 | Illiquid, synthetic | Full control | Requires manual calculation |

### Calculating Forward from Spot

```python
import math

# Parameters (NIFTY 02DEC25 expiry)
spot = 26240         # Current NIFTY spot
rate = 0.065         # 6.5% annual
days_to_expiry = 2   # Days to 02DEC25
T = days_to_expiry / 365

# Forward price
forward = spot * math.exp(rate * T)
print(f"Forward: {forward:.2f}")  # ~26249.36

# For 30DEC25 (30 days)
T_30 = 30 / 365
forward_30 = spot * math.exp(rate * T_30)
print(f"Forward 30DEC25: {forward_30:.2f}")  # ~26380.45
```

###

## Use Cases

### 1. Delta-Neutral Portfolio

Calculate delta of all option positions to maintain market-neutral portfolio.

```python
# Get greeks for each position
call_greeks = get_option_greeks("NIFTY02DEC2526000CE")
put_greeks = get_option_greeks("NIFTY02DEC2526000PE")

# Calculate net delta
net_delta = (call_qty * call_greeks['delta']) + (put_qty * put_greeks['delta'])

# Hedge with futures if needed
```

### 2. Time Decay Analysis

Monitor theta to understand daily decay and optimal exit timing.

```python
# Check theta for your position
greeks = get_option_greeks("NIFTY02DEC2526000CE")

# If theta is very high (e.g., -50), consider:
# - Closing position before weekend
# - Rolling to next expiry
# - Adjusting position size
```

### 3. Volatility Trading

Use vega to identify options most sensitive to IV changes.

```python
# Compare vega across strikes
atm_greeks = get_option_greeks("NIFTY30DEC2526000CE")  # Near ATM
itm_greeks = get_option_greeks("NIFTY30DEC2526100CE")  # Slightly ITM

# ATM options typically have highest vega
# Trade before events: RBI policy, budget, elections
```

### 4. Risk Assessment

Use gamma to understand risk of rapid delta changes.

```python
# High gamma = High risk/reward
# Gamma highest for ATM options near expiry

greeks = get_option_greeks("NIFTY02DEC2526000CE")

if greeks['gamma'] > 0.005:
    print("High gamma - expect rapid delta changes")
    # Consider: tighter stop-loss, reduce position size
```

### 5. Synthetic Futures Pricing

Use forward_price for custom pricing scenarios.

```python
import math

# Calculate synthetic forward for NIFTY 02DEC25
spot = 26240
rate = 0.065
T = 2 / 365
forward = spot * math.exp(rate * T)

# Use in API request
payload = {
    "apikey": "your_key",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26350,  # Or use calculated forward
    "interest_rate": 6.5
}
```

###

## Integration Examples

### Python Example

```python
import requests
import math

def get_option_greeks(symbol, exchange, interest_rate=None, forward_price=None):
    url = "http://127.0.0.1:5000/api/v1/optiongreeks"

    payload = {
        "apikey": "your_api_key_here",
        "symbol": symbol,
        "exchange": exchange
    }

    if interest_rate is not None:
        payload["interest_rate"] = interest_rate

    if forward_price is not None:
        payload["forward_price"] = forward_price

    response = requests.post(url, json=payload)
    return response.json()

# Basic usage - spot-based (26240)
greeks = get_option_greeks("NIFTY02DEC2526000CE", "NFO")

print(f"Delta: {greeks['greeks']['delta']}")
print(f"Theta: {greeks['greeks']['theta']}")
print(f"IV: {greeks['implied_volatility']}%")

# With synthetic forward price (26350)
greeks_synthetic = get_option_greeks(
    "NIFTY02DEC2526000CE",
    "NFO",
    interest_rate=6.5,
    forward_price=26350
)
print(f"Synthetic Forward Greeks: {greeks_synthetic}")

# With futures as underlying (26396)
greeks_futures = get_option_greeks(
    "NIFTY30DEC2526100CE",
    "NFO"
)
# Add underlying_symbol and underlying_exchange for futures
```

### JavaScript Example

```javascript
async function getOptionGreeks(symbol, exchange, interestRate = null, forwardPrice = null) {
    const url = 'http://127.0.0.1:5000/api/v1/optiongreeks';

    const payload = {
        apikey: 'your_api_key_here',
        symbol: symbol,
        exchange: exchange
    };

    if (interestRate !== null) {
        payload.interest_rate = interestRate;
    }

    if (forwardPrice !== null) {
        payload.forward_price = forwardPrice;
    }

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    return await response.json();
}

// Basic usage - spot-based (26240)
getOptionGreeks('NIFTY02DEC2526000CE', 'NFO')
    .then(data => {
        console.log('Delta:', data.greeks.delta);
        console.log('IV:', data.implied_volatility);
    });

// With synthetic forward price (26350)
getOptionGreeks('NIFTY02DEC2526000CE', 'NFO', 6.5, 26350)
    .then(data => {
        console.log('NIFTY Greeks with synthetic forward:', data);
    });
```

### cURL Example

```bash
# Basic request - spot-based (26240)
curl -X POST http://127.0.0.1:5000/api/v1/optiongreeks \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO"
  }'

# With synthetic forward price (26350)
curl -X POST http://127.0.0.1:5000/api/v1/optiongreeks \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "symbol": "NIFTY02DEC2526000CE",
    "exchange": "NFO",
    "forward_price": 26350,
    "interest_rate": 6.5
  }'

# With futures as underlying (26396)
curl -X POST http://127.0.0.1:5000/api/v1/optiongreeks \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "symbol": "NIFTY30DEC2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY30DEC25FUT",
    "underlying_exchange": "NFO"
  }'
```

###

## Rate Limiting

- **Limit**: 30 requests per minute
- **Scope**: Per API endpoint
- **Response**: 429 status code if limit exceeded

###

## Best Practices

1. **Install Dependencies First**
   - Install py_vollib before using API: `pip install py_vollib`
   - Verify installation: `python -c "from py_vollib.black.greeks.analytical import delta"`

2. **Use Current Contracts**
   - Expired options will return error
   - Use current or future expiry dates

3. **Verify Symbol Format**
   - Format: `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
   - Example: `NIFTY02DEC2526000CE`
   - Wrong: `NIFTY26000CE`

4. **Market Hours**
   - Greeks require live prices (unless using forward_price)
   - Ensure markets are open for accurate data
   - Pre-market/post-market may have stale data

5. **Interest Rate Selection**
   - Default is 0% (no interest rate impact)
   - Explicitly specify current RBI repo rate (6.25-7.0%) for:
     - Long-dated options (> 30 days to expiry)
     - Rho-sensitive strategies
     - Matching with broker Greeks
   - Interest rate has minimal impact on short-term options (< 7 days)

6. **Use Forward Price for Custom Scenarios**
   - FINNIFTY, MIDCPNIFTY futures may be illiquid
   - Calculate synthetic forward: `Spot x e^(rT)`
   - Provides consistent Greeks regardless of futures liquidity

7. **Understand Greek Units**
   - Theta: Daily decay (no conversion needed)
   - Vega: Per 1% IV change (no conversion needed)
   - py_vollib returns trader-friendly units directly

8. **Cache Results**
   - Greeks don't change drastically every second
   - Cache for 30-60 seconds to reduce API calls
   - Recalculate when underlying moves significantly

###

## Troubleshooting

### Import Error: No module named 'py_vollib'

**Solution**: Install py_vollib library
```bash
pip install py_vollib
# or
uv pip install py_vollib
```

### Greeks Seem Incorrect

**Possible Causes**:
1. **Stale Prices**: Check if markets are open
2. **Wrong Interest Rate**: Adjust interest_rate parameter
3. **Symbol Parsing**: Verify symbol format
4. **Deep ITM/OTM**: Greeks may be extreme for deep options
5. **Illiquid Underlying**: Use forward_price parameter

**Solution**:
- Verify underlying and option LTP manually
- Compare with broker's Greeks
- Check expiry date is future
- Try using forward_price for custom scenarios

### Greeks Don't Match Expected Values

**Solution**: OpenAlgo uses Black-76 model for Indian F&O
- Ensure you're using the latest version with py_vollib
- Check interest rate settings match
- Verify forward/spot price used is the same
- Compare with broker platform using same parameters

### High IV Calculation Errors

**Cause**: Black-76 may not converge for very deep ITM/OTM options

**Solution**:
- Use ATM or near-ATM options for accurate Greeks
- Very deep options may require different approaches

###

## Technical Notes

### Black-76 Model

The API uses Black-76 model (via py_vollib) for options on futures/forwards:

**Why Black-76 instead of Black-Scholes?**
- Black-Scholes: Designed for stock options (spot-settled)
- Black-76: Designed for options on futures/forwards
- Indian F&O markets trade options on futures, not spot

**Model Formula**:
```
Call = e^(-rT) * [F*N(d1) - K*N(d2)]
Put  = e^(-rT) * [K*N(-d2) - F*N(-d1)]

Where:
F = Forward/Futures price (e.g., 26350 or 26396)
K = Strike price (e.g., 26000 or 26100)
r = Risk-free rate (e.g., 0.065 for 6.5%)
T = Time to expiry (years)
sigma = Implied volatility
```

**Assumptions**:
- Constant volatility
- Log-normal price distribution
- No dividends (forward price already accounts for cost of carry)
- European exercise (index options)

**Calculation Steps**:
1. Parse option symbol to extract strike, expiry
2. Fetch forward price (or use provided forward_price)
3. Calculate time to expiry in years
4. Solve for Implied Volatility (IV) using Black-76
5. Calculate Greeks using Black-76 model with IV

### Symbol Parsing

Supports multiple formats across exchanges:
- **NFO**: `NIFTY02DEC2526000CE`, `NIFTY30DEC2526100CE`
- **BFO**: `SENSEX30DEC2580000CE`
- **CDS**: `USDINR30DEC2585.50CE` (decimal strikes)
- **MCX**: `CRUDEOIL17DEC255400CE`

###

## Features

1. **Black-76 Model**: Industry-standard for options on futures
2. **Multi-Exchange Support**: NFO, BFO, CDS, MCX
3. **Automatic Price Fetching**: Gets live prices via quotes API
4. **Custom Forward Price**: Support for synthetic futures and custom scenarios
5. **Accurate IV Calculation**: Solves Black-76 for IV
6. **Complete Greeks**: Delta, Gamma, Theta, Vega, Rho
7. **Trader-Friendly Units**: Theta (daily), Vega (per 1% IV)
8. **Flexible Interest Rate**: Override default per request
9. **Decimal Strike Support**: For currency options
10. **Error Handling**: Comprehensive validation and errors

###

## Limitations

1. **Requires py_vollib Library**: Must install separately
2. **European Options**: Best suited for index options
3. **No Dividend Adjustment**: Doesn't account for dividends
4. **Market Hours**: Requires live prices for accuracy (unless using forward_price)
5. **Deep Options**: May have convergence issues for very deep ITM/OTM
6. **Rate Assumption**: Uses fixed interest rate (not dynamic)

###

## Support

For issues or questions:
- Verify py_vollib installation
- Check symbol format matches documented pattern
- Ensure markets are open for live data (or use forward_price)
- Review OpenAlgo logs for detailed errors
- Compare with broker Greeks to validate
- For custom scenarios, use forward_price parameter
