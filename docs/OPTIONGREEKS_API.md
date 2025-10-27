# Option Greeks API

## Endpoint URL

This API Function Calculates Option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility using Black-Scholes Model

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optiongreeks
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optiongreeks
Custom Domain:  POST https://<your-custom-domain>/api/v1/optiongreeks
```

## Prerequisites

1. **mibian Library Required**
   - Install with: `pip install mibian`
   - Or with uv: `uv pip install mibian`
   - Required for Black-Scholes calculations

2. **Market Data Access**
   - Requires real-time LTP for underlying and option
   - Uses OpenAlgo quotes API internally

3. **Valid API Key**
   - API key must be active and valid
   - Get API key from OpenAlgo settings

## Sample API Request (NFO - NIFTY Option with Auto-Detected Spot)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "symbol": "NIFTY28OCT2526000CE",
    "exchange": "NFO"
}
```

**Note**: Auto-detects NIFTY from NSE_INDEX (spot) as underlying

###

## Sample API Request (Explicit Underlying with Zero Interest Rate)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "symbol": "NIFTY28OCT2526000CE",
    "exchange": "NFO",
    "interest_rate": 0,
    "underlying_symbol": "NIFTY",
    "underlying_exchange": "NSE_INDEX"
}
```

**Note**: Explicitly specifies NIFTY spot from NSE_INDEX. Using interest_rate: 0 for theoretical calculations or when interest rate impact is negligible.

###

## Sample API Response (Success)

```json
{
    "status": "success",
    "symbol": "NIFTY28OCT2526000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "strike": 26000,
    "option_type": "CE",
    "expiry_date": "28-Oct-2025",
    "days_to_expiry": 0.59,
    "spot_price": 25966.05,
    "option_price": 85.55,
    "interest_rate": 0,
    "implied_volatility": 464.42,
    "greeks": {
        "delta": 0.4489,
        "gamma": 0.001554,
        "theta": -30962.4879,
        "vega": 0.2169,
        "rho": 0.000516
    }
}
```

**Note**: This is an expiry day example (0.59 days to expiry) showing very high IV (464.42%) and extreme theta decay (-30962.48 per day), typical of near-expiry ATM options.

###

## Sample API Request (Using Futures as Underlying)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY28NOV25FUT",
    "underlying_exchange": "NFO"
}
```

**Note**: Uses futures price instead of spot for calculations. Useful when options are based on futures pricing.

###

## Sample API Response (Success - Standard)

```json
{
    "status": "success",
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "strike": 26000,
    "option_type": "CE",
    "expiry_date": "28-Nov-2025",
    "days_to_expiry": 5.42,
    "spot_price": 26015.75,
    "option_price": 125.50,
    "interest_rate": 0,
    "implied_volatility": 15.25,
    "greeks": {
        "delta": 0.5234,
        "gamma": 0.000125,
        "theta": -12.5678,
        "vega": 18.7654,
        "rho": 0.001234
    }
}
```

**Note**: Shows default `interest_rate: 0`. For long-dated options, specify current RBI repo rate for accurate Rho.

###

## Sample API Request (With Custom Interest Rate)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "symbol": "BANKNIFTY28NOV2550000CE",
    "exchange": "NFO",
    "interest_rate": 6.5
}
```

**Note**: Explicitly specify interest rate (e.g., 6.5%) for accurate Rho calculations, especially for long-dated options.

###

## Sample API Request (BFO - SENSEX Option)

```json
{
    "apikey": "your_api_key",
    "symbol": "SENSEX28NOV2580000CE",
    "exchange": "BFO"
}
```

###

## Sample API Request (CDS - Currency Option)

```json
{
    "apikey": "your_api_key",
    "symbol": "USDINR28NOV2585.50CE",
    "exchange": "CDS"
}
```

###

## Sample API Request (MCX - Commodity Option with Custom Expiry Time)

```json
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17NOV255400CE",
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
    "symbol": "NATURALGAS28DEC25300CE",
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
| symbol               | Option symbol (e.g., NIFTY28NOV2526000CE)           | Mandatory          | -             |
| exchange             | Exchange code (NFO, BFO, CDS, MCX)                  | Mandatory          | -             |
| interest_rate        | Risk-free interest rate (annualized %). Specify current RBI repo rate (e.g., 6.5, 6.75) for accurate Rho calculations. Use 0 for theoretical calculations or when interest rate impact is negligible | Optional | 0 |
| underlying_symbol    | Custom underlying symbol (e.g., NIFTY or NIFTY28NOV25FUT) | Optional | Auto-detected |
| underlying_exchange  | Custom underlying exchange (e.g., NSE_INDEX or NFO) | Optional           | Auto-detected |
| expiry_time          | Custom expiry time in HH:MM format (e.g., "17:00", "19:00"). Required for MCX contracts with non-standard expiry times | Optional | Exchange defaults: NFO/BFO=15:30, CDS=12:30, MCX=23:30 |

**Notes**:
- **Interest Rate**: Default is 0. For accurate Greeks (especially Rho), specify current RBI repo rate (typically 6.25-7.0%). Interest rate has minimal impact on short-term options (< 7 days).
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
| spot_price          | Underlying spot/futures price            | number  |
| option_price        | Current option premium                   | number  |
| interest_rate       | Interest rate used                       | number  |
| implied_volatility  | Implied Volatility (%)                   | number  |
| greeks              | Object containing Greeks                 | object  |
| greeks.delta        | Delta (rate of change of option price)   | number  |
| greeks.gamma        | Gamma (rate of change of delta)          | number  |
| greeks.theta        | Theta (time decay per day)               | number  |
| greeks.vega         | Vega (sensitivity to volatility)         | number  |
| greeks.rho          | Rho (sensitivity to interest rate)       | number  |

###

## Understanding Greeks

### Delta
- **Range**: -1 to +1 (Call: 0 to 1, Put: -1 to 0)
- **Meaning**: Change in option price for ₹1 change in underlying
- **Example**: Delta of 0.5 means option moves ₹0.50 for ₹1 move in underlying
- **Use**: Position sizing, hedge ratio calculation

### Gamma
- **Range**: 0 to ∞ (same for Call and Put)
- **Meaning**: Change in Delta for ₹1 change in underlying
- **Example**: Gamma of 0.01 means Delta increases by 0.01 for ₹1 rise
- **Use**: Delta hedging frequency, risk assessment

### Theta
- **Range**: Negative for long options
- **Meaning**: Change in option price per day (time decay)
- **Example**: Theta of -10 means option loses ₹10 per day
- **Use**: Time decay analysis, optimal holding period

### Vega
- **Range**: Positive for long options
- **Meaning**: Change in option price for 1% change in IV
- **Example**: Vega of 15 means option gains ₹15 if IV rises by 1%
- **Use**: Volatility trading, earnings plays

### Rho
- **Range**: Positive for Calls, Negative for Puts
- **Meaning**: Change in option price for 1% change in interest rate
- **Example**: Rho of 0.05 means option gains ₹0.05 for 1% rate rise
- **Use**: Long-term options, rate-sensitive strategies

###

## Supported Exchanges and Symbols

### NFO (NSE Futures & Options)

**Index Options:**
- NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY

**Equity Options:**
- All NSE stocks with F&O segment (RELIANCE, TCS, INFY, etc.)

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `NIFTY28NOV2526000CE`

**Expiry Time:** 3:30 PM (15:30 IST)

### BFO (BSE Futures & Options)

**Index Options:**
- SENSEX, BANKEX, SENSEX50

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `SENSEX28NOV2580000CE`

**Expiry Time:** 3:30 PM (15:30 IST)

### CDS (Currency Derivatives)

**Currency Pairs:**
- USDINR, EURINR, GBPINR, JPYINR

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `USDINR28NOV2585.50CE`
- Note: Strike can have decimals for currency options

**Expiry Time:** 12:30 PM (12:30 IST)

### MCX (Multi Commodity Exchange)

**Commodities:**
- GOLD, GOLDM, SILVER, SILVERM
- CRUDEOIL, NATURALGAS
- COPPER, ZINC, LEAD, ALUMINIUM

**Symbol Format:** `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- Example: `CRUDEOIL17NOV255400CE`

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
// Crude Oil expires at 7:00 PM (LTP: 5443)
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17NOV255400CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}

// Gold expires at 5:00 PM
{
    "apikey": "your_api_key",
    "symbol": "GOLD28DEC2575000CE",
    "exchange": "MCX",
    "expiry_time": "17:00"
}

// Natural Gas expires at 7:00 PM
{
    "apikey": "your_api_key",
    "symbol": "NATURALGAS28DEC25300CE",
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
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO"
}
```

**What Happens**:
- ✓ Auto-detects NIFTY from NSE_INDEX (spot price)
- ✓ Uses default interest rate: 0%
- ✓ Uses default expiry time: 15:30 (NFO)
- ✓ Simplest usage - good for most traders

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
    "symbol": "BANKNIFTY28NOV2550000CE",
    "exchange": "NFO",
    "interest_rate": 6.5
}
```

**What Happens**:
- ✓ Uses 6.5% instead of default 0%
- ✓ Affects Rho calculation significantly
- ✓ Minor impact on other Greeks (< 0.5%)

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
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY28NOV25FUT",
    "underlying_exchange": "NFO"
}
```

**What Happens**:
- ✓ Uses NIFTY futures price instead of spot
- ✓ Futures price includes cost of carry
- ✓ Delta, IV may differ by 1-3% vs spot

**When to Use**:
- Arbitrage strategies (futures vs options)
- When broker uses futures for Greeks
- Equity options with liquid futures
- Professional trading desks

**Example - Equity with Futures**:
```json
{
    "apikey": "your_api_key",
    "symbol": "RELIANCE28NOV251600CE",
    "exchange": "NFO",
    "underlying_symbol": "RELIANCE28NOV25FUT",
    "underlying_exchange": "NFO"
}
```

---

### Example 4: MCX with Custom Expiry Time

**Scenario**: Calculate Greeks for Crude Oil options (expires at 19:00)

```json
{
    "apikey": "your_api_key",
    "symbol": "CRUDEOIL17NOV255400CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

**What Happens**:
- ✓ Uses 19:00 (7 PM) expiry instead of default 23:30
- ✓ DTE calculated accurately
- ✓ Theta, IV more accurate on expiry day

**When to Use**:
- ALL MCX commodity options (except those expiring at 23:30)
- Critical for accurate Greeks on expiry day
- Gold, Silver, Copper: 17:00
- Natural Gas, Crude Oil: 19:00

**Example - Natural Gas at 19:00**:
```json
{
    "apikey": "your_api_key",
    "symbol": "NATURALGAS28DEC245000CE",
    "exchange": "MCX",
    "expiry_time": "19:00"
}
```

---

### Example 5: Currency Options (CDS)

**Scenario**: USD/INR option (expires at 12:30)

```json
{
    "apikey": "your_api_key",
    "symbol": "USDINR28NOV2483.50CE",
    "exchange": "CDS"
}
```

**What Happens**:
- ✓ Auto-detects USDINR from CDS exchange
- ✓ Uses correct expiry time: 12:30 (CDS default)
- ✓ Supports decimal strikes (83.50)

**When to Use**: Currency derivatives trading

---

### Example 6: All Parameters Combined

**Scenario**: Professional setup with full control

```json
{
    "apikey": "your_api_key",
    "symbol": "NIFTY28DEC2526500CE",
    "exchange": "NFO",
    "interest_rate": 6.75,
    "underlying_symbol": "NIFTY28DEC25FUT",
    "underlying_exchange": "NFO"
}
```

**What Happens**:
- ✓ Custom interest rate: 6.75% (instead of default 0%)
- ✓ Uses futures as underlying (instead of spot)
- ✓ Maximum control over calculation

**When to Use**:
- Institutional trading with specific interest rate requirements
- Greeks matching with broker platform that uses specific rates
- Research and backtesting with historical interest rates
- Long-dated options requiring accurate Rho

---

### Example 7: BSE Options (BFO)

**Scenario**: SENSEX option

```json
{
    "apikey": "your_api_key",
    "symbol": "SENSEX28NOV2475000CE",
    "exchange": "BFO"
}
```

**What Happens**:
- ✓ Auto-detects SENSEX from BSE_INDEX
- ✓ Uses correct expiry time: 15:30 (BFO)

**When to Use**: BSE index options trading

---

### Quick Reference: When to Use Optional Parameters

| Parameter           | Use When                                          | Don't Use When                    |
| ------------------- | ------------------------------------------------- | --------------------------------- |
| `interest_rate`     | Long-dated options, Rho analysis, matching broker | Short-term weekly options         |
| `underlying_symbol` | Arbitrage, comparing with broker, equity options  | Standard index option trading     |
| `underlying_exchange` | Custom underlying setup                         | Auto-detection works fine         |
| `expiry_time`       | **ALWAYS for MCX** (except 23:30 contracts)      | NFO/BFO/CDS (already correct)     |

---

### Impact of Optional Parameters on Greeks

**Interest Rate (Default 0% → Custom 6.5%)**:
- Rho: Significant change (from near-zero to meaningful value)
- Delta: ±0.2-0.5% change (for long-dated options)
- Other Greeks: < 0.1% change
- **Impact**:
  - **High for Rho** (critical for interest rate sensitive strategies)
  - **Low for other Greeks** (especially short-term options)
  - **Negligible for < 7 days to expiry**

**Underlying: Spot vs Futures (1% difference in price)**:
- Delta: ±2-5% change
- IV: ±0.3-1% change
- Other Greeks: ±1-3% change
- **Impact**: Moderate to High

**Expiry Time (6 hours difference: 17:00 vs 23:30)**:
- DTE: 6 hours difference
- Theta: ±10-30% change on expiry day
- IV: ±2-8% change near expiry
- Gamma: ±5-15% change near expiry
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
Date: 17-Nov-2025 at 2:00 PM

CDS Option (USDINR17NOV2585.50CE):
  - Expired 1.5 hours ago (12:30 PM)
  - DTE: 0 (already expired)

NFO Option (NIFTY17NOV2526000CE):
  - Expires in 1.5 hours (3:30 PM)
  - DTE: 0.0063 years (~1.5 hours)

MCX Option (CRUDEOIL17NOV255400CE):
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
- ✓ Long-dated options (> 30 days to expiry)
- ✓ Interest rate sensitive strategies (Rho hedging)
- ✓ Matching with broker Greeks
- ✗ Short-term options (< 7 days) - minimal impact
- ✗ Theoretical or academic calculations

###

## Error Responses

### mibian Library Not Installed

```json
{
    "status": "error",
    "message": "Option Greeks calculation requires mibian library. Install with: pip install mibian"
}
```

### Invalid Symbol Format

```json
{
    "status": "error",
    "message": "Invalid option symbol format: NIFTY2400CE"
}
```

### Option Expired

```json
{
    "status": "error",
    "message": "Option has expired on 28-Oct-2024"
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

###

## Common Error Messages

| Error Message                                  | Cause                                | Solution                              |
| ---------------------------------------------- | ------------------------------------ | ------------------------------------- |
| mibian library not installed                   | Missing dependency                   | Run: pip install mibian               |
| Invalid option symbol format                   | Symbol pattern doesn't match         | Use: SYMBOL[DD][MMM][YY][STRIKE][CE/PE] |
| Option has expired                             | Expiry date in the past              | Use current month contracts           |
| Failed to fetch underlying price               | Underlying symbol not found          | Verify symbol and exchange            |
| Option LTP not available                       | No trading data for option           | Check market hours, symbol validity   |
| Invalid openalgo apikey                        | API key incorrect                    | Verify API key in settings            |

###

## How Expiry Times Affect Calculations

### Impact on Time to Expiry (DTE)

Accurate expiry times are critical for precise Greeks calculation. The API automatically uses exchange-specific expiry times:

**Time to Expiry Formula:**
```python
time_to_expiry = (expiry_datetime - current_datetime) / 365
```

**Example on Expiry Day (28-Nov-2025):**

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

- **More time** → Lower IV for same premium (more time value)
- **Less time** → Higher IV for same premium (less time value)

**Example:**
```
NIFTY Option Premium: ₹50

At 10:00 AM (5.5 hrs to NFO expiry):
  Implied IV: ~18%

At 3:00 PM (0.5 hrs to NFO expiry):
  Implied IV: ~35%
  (Same premium, but much higher IV due to less time)
```

### Impact on Delta

**Delta is less affected** by small DTE changes, but:

- Very near expiry (< 1 hour), delta can shift rapidly
- ATM options approach delta of 0.5 faster
- Deep ITM → 1.0, Deep OTM → 0.0 faster near expiry

### Impact on Gamma

**Gamma peaks near expiry** for ATM options:

```
NIFTY ATM Call:

7 days before expiry:
  Gamma: ~0.0001

1 day before expiry:
  Gamma: ~0.001 (10x higher)

1 hour before expiry:
  Gamma: ~0.01 (100x higher - very sensitive!)
```

**Exchange Comparison on Expiry Day 10:00 AM:**
- **CDS** (2.5 hrs left): Gamma ~0.008 (very high)
- **NFO** (5.5 hrs left): Gamma ~0.005 (high)
- **MCX** (13.5 hrs left): Gamma ~0.002 (moderate)

### Impact on Vega

**Vega decreases as expiry approaches:**

```
NIFTY ATM Call:

30 days to expiry:
  Vega: ~25 (high sensitivity to IV)

7 days to expiry:
  Vega: ~12

1 day to expiry:
  Vega: ~3 (low sensitivity)
```

**On Expiry Day:** MCX options retain more vega than NFO, which retain more than CDS.

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

## Spot vs Futures as Underlying

### When to Use Spot (Default)

**Best For**:
- Index options (NIFTY, BANKNIFTY, SENSEX)
- Currency options (USDINR, EURINR)
- Most traders prefer spot for simplicity

**Example**:
```json
{
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO"
}
```
Auto-detects NIFTY from NSE_INDEX

### When to Use Futures

**Best For**:
- Arbitrage strategies
- When option pricing is based on futures
- Comparing with broker Greeks that use futures
- Equity options where futures are liquid

**Example - Using Futures**:
```json
{
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO",
    "underlying_symbol": "NIFTY28NOV25FUT",
    "underlying_exchange": "NFO"
}
```

**Example - Equity with Futures**:
```json
{
    "symbol": "RELIANCE28NOV251600CE",
    "exchange": "NFO",
    "underlying_symbol": "RELIANCE28NOV25FUT",
    "underlying_exchange": "NFO"
}
```

### Spot vs Futures Pricing Difference

- **Spot**: Current index/stock price
- **Futures**: Forward price (includes cost of carry)
- **Difference**: Typically 0.5-2% depending on time to expiry
- **Impact**: Can affect Delta by 1-3% and IV by 0.1-0.5%

###

## Use Cases

### 1. Delta-Neutral Portfolio

Calculate delta of all option positions to maintain market-neutral portfolio.

```python
# Get greeks for each position
call_greeks = get_option_greeks("NIFTY28NOV2526000CE")
put_greeks = get_option_greeks("NIFTY28NOV2526000PE")

# Calculate net delta
net_delta = (call_qty * call_greeks['delta']) + (put_qty * put_greeks['delta'])

# Hedge with futures if needed
```

### 2. Time Decay Analysis

Monitor theta to understand daily decay and optimal exit timing.

```python
# Check theta for your position
greeks = get_option_greeks("BANKNIFTY28NOV2550000CE")

# If theta is very high (e.g., -50), consider:
# - Closing position before weekend
# - Rolling to next expiry
# - Adjusting position size
```

### 3. Volatility Trading

Use vega to identify options most sensitive to IV changes.

```python
# Compare vega across strikes
atm_greeks = get_option_greeks("NIFTY28NOV2526000CE")  # ATM
otm_greeks = get_option_greeks("NIFTY28NOV2526500CE")  # OTM

# ATM options typically have highest vega
# Trade before events: earnings, RBI policy, budget
```

### 4. Risk Assessment

Use gamma to understand risk of rapid delta changes.

```python
# High gamma = High risk/reward
# Gamma highest for ATM options near expiry

greeks = get_option_greeks("NIFTY28NOV2526000CE")

if greeks['gamma'] > 0.01:
    print("High gamma - expect rapid delta changes")
    # Consider: tighter stop-loss, reduce position size
```

###

## Integration Examples

### Python Example

```python
import requests

def get_option_greeks(symbol, exchange, interest_rate=None):
    url = "http://127.0.0.1:5000/api/v1/optiongreeks"

    payload = {
        "apikey": "your_api_key_here",
        "symbol": symbol,
        "exchange": exchange
    }

    if interest_rate:
        payload["interest_rate"] = interest_rate

    response = requests.post(url, json=payload)
    return response.json()

# Usage
greeks = get_option_greeks("NIFTY28NOV2526000CE", "NFO")

print(f"Delta: {greeks['greeks']['delta']}")
print(f"Theta: {greeks['greeks']['theta']}")
print(f"IV: {greeks['implied_volatility']}%")
```

### JavaScript Example

```javascript
async function getOptionGreeks(symbol, exchange, interestRate = null) {
    const url = 'http://127.0.0.1:5000/api/v1/optiongreeks';

    const payload = {
        apikey: 'your_api_key_here',
        symbol: symbol,
        exchange: exchange
    };

    if (interestRate) {
        payload.interest_rate = interestRate;
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

// Usage
getOptionGreeks('BANKNIFTY28NOV2550000CE', 'NFO')
    .then(data => {
        console.log('Delta:', data.greeks.delta);
        console.log('IV:', data.implied_volatility);
    });
```

### cURL Example

```bash
curl -X POST http://127.0.0.1:5000/api/v1/optiongreeks \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "symbol": "NIFTY28NOV2526000CE",
    "exchange": "NFO"
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
   - Install mibian before using API: `pip install mibian`
   - Verify installation: `python -c "import mibian"`

2. **Use Current Contracts**
   - Expired options will return error
   - Use current or future expiry dates

3. **Verify Symbol Format**
   - Format: `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
   - Example: `NIFTY28NOV2526000CE` ✓
   - Wrong: `NIFTY24000CE` ✗

4. **Market Hours**
   - Greeks require live prices
   - Ensure markets are open for accurate data
   - Pre-market/post-market may have stale data

5. **Interest Rate Selection**
   - Default is 0% (no interest rate impact)
   - Explicitly specify current RBI repo rate (6.25-7.0%) for:
     - Long-dated options (> 30 days to expiry)
     - Rho-sensitive strategies
     - Matching with broker Greeks
   - Interest rate has minimal impact on short-term options (< 7 days)

6. **Understand Greek Limitations**
   - Based on Black-Scholes (assumes log-normal distribution)
   - May not account for dividends, early exercise
   - More accurate for European-style index options

7. **Cache Results**
   - Greeks don't change drastically every second
   - Cache for 30-60 seconds to reduce API calls
   - Recalculate when underlying moves significantly

###

## Troubleshooting

### Import Error: No module named 'mibian'

**Solution**: Install mibian library
```bash
pip install mibian
# or
uv pip install mibian
```

### Greeks Seem Incorrect

**Possible Causes**:
1. **Stale Prices**: Check if markets are open
2. **Wrong Interest Rate**: Adjust interest_rate parameter
3. **Symbol Parsing**: Verify symbol format
4. **Deep ITM/OTM**: Greeks may be extreme for deep options

**Solution**:
- Verify underlying and option LTP manually
- Compare with broker's Greeks
- Check expiry date is future

### High IV Calculation Errors

**Cause**: Black-Scholes may not converge for very deep ITM/OTM options

**Solution**:
- Use ATM or near-ATM options for accurate Greeks
- Very deep options may require different models

###

## Technical Notes

### Black-Scholes Model

The API uses Black-Scholes model for European options:

**Assumptions**:
- Constant volatility
- Log-normal price distribution
- No dividends
- European exercise (index options)

**Calculation Steps**:
1. Parse option symbol to extract strike, expiry
2. Fetch spot price and option premium
3. Calculate time to expiry in years
4. Solve for Implied Volatility (IV)
5. Calculate Greeks using BS model with IV

### Symbol Parsing

Supports multiple formats across exchanges:
- **NFO**: `NIFTY28NOV2526000CE`
- **BFO**: `SENSEX28NOV2580000CE`
- **CDS**: `USDINR28NOV2585.50CE` (decimal strikes)
- **MCX**: `CRUDEOIL17NOV255400CE`

###

## Features

1. **Multi-Exchange Support**: NFO, BFO, CDS, MCX
2. **Automatic Price Fetching**: Gets live prices via quotes API
3. **Accurate IV Calculation**: Solves Black-Scholes for IV
4. **Complete Greeks**: Delta, Gamma, Theta, Vega, Rho
5. **Flexible Interest Rate**: Override default per request
6. **Decimal Strike Support**: For currency options
7. **Error Handling**: Comprehensive validation and errors

###

## Limitations

1. **Requires mibian Library**: Must install separately
2. **European Options**: Best suited for index options
3. **No Dividend Adjustment**: Doesn't account for dividends
4. **Market Hours**: Requires live prices for accuracy
5. **Deep Options**: May have convergence issues for very deep ITM/OTM
6. **Rate Assumption**: Uses fixed interest rate (not dynamic)

###

## Support

For issues or questions:
- Verify mibian installation
- Check symbol format matches documented pattern
- Ensure markets are open for live data
- Review OpenAlgo logs for detailed errors
- Compare with broker Greeks to validate
