# OptionChain

Get the complete option chain for a given underlying and expiry, including quotes for all strikes.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionchain
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionchain
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionchain
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "30DEC25",
  "strike_count": 10
}
```

## Sample API Response

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
        "lotsize": 65,
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
        "lotsize": 65,
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
        "lotsize": 65,
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
        "lotsize": 65,
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
        "lotsize": 65,
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
        "lotsize": 65,
        "tick_size": 0.05
      }
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| underlying | Underlying symbol (NIFTY, BANKNIFTY, SENSEX) | Mandatory | - |
| exchange | Exchange: NSE_INDEX, BSE_INDEX | Mandatory | - |
| expiry_date | Expiry date in DDMMMYY format | Mandatory | - |
| strike_count | Number of strikes above and below ATM | Optional | All strikes |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| underlying | string | Underlying symbol |
| underlying_ltp | number | Current underlying price |
| expiry_date | string | Expiry date |
| atm_strike | number | At-the-money strike price |
| chain | array | Array of strike data |

### Chain Array Fields

| Field | Type | Description |
|-------|------|-------------|
| strike | number | Strike price |
| ce | object | Call option data |
| pe | object | Put option data |

### Option Data Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Option symbol |
| label | string | ATM, ITM1, ITM2..., OTM1, OTM2... |
| ltp | number | Last traded price |
| bid | number | Best bid price |
| ask | number | Best ask price |
| open | number | Day's open |
| high | number | Day's high |
| low | number | Day's low |
| prev_close | number | Previous close |
| volume | number | Trading volume |
| oi | number | Open interest |
| lotsize | number | Lot size |
| tick_size | number | Tick size |

## Notes

- Without **strike_count**, returns the **entire option chain** for the expiry
- The **label** field indicates whether the option is ATM, ITM, or OTM
- For CE options: strikes below ATM are ITM, above are OTM
- For PE options: strikes above ATM are ITM, below are OTM
- Use this for **options analysis** and **strategy selection**

## Use Cases

- **Option analysis**: View premiums across strikes
- **Strategy selection**: Find suitable strikes for spreads/strangles
- **Volatility analysis**: Compare premiums at different strikes

---

**Back to**: [API Documentation](../README.md)
