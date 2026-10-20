# OptionChain

Get the complete option chain for a given underlying and expiry, including quotes for all strikes and, optionally, implied volatility and Greeks for every leg.

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
  "expiry_date": "25AUG26",
  "strike_count": 10,
  "with_greeks": true
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionchain \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "25AUG26",
  "strike_count": 10,
  "with_greeks": true
}'
```

## Sample API Response

Trimmed to three strikes for brevity. The Greek fields are present only when `with_greeks` is set.

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 24560.15,
  "underlying_prev_close": 24570.65,
  "expiry_date": "25AUG26",
  "expiry_ts": 1787652000,
  "server_ts": 1786356402,
  "atm_strike": 24550.0,
  "quotes_included": true,
  "greeks_included": true,
  "forward_price": 24580.0,
  "chain": [
    {
      "strike": 24450.0,
      "ce": {
        "symbol": "NIFTY25AUG2624450CE",
        "label": "ITM1",
        "ltp": 373.3,
        "bid": 372.8,
        "ask": 373.8,
        "bid_qty": 1500,
        "ask_qty": 2250,
        "open": 395.7,
        "high": 414.35,
        "low": 343.45,
        "prev_close": 388.25,
        "volume": 2841075,
        "oi": 4218300,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 15.33,
        "delta": 0.5739,
        "gamma": 0.000513,
        "theta": -9.9854,
        "vega": 19.5342
      },
      "pe": {
        "symbol": "NIFTY25AUG2624450PE",
        "label": "OTM1",
        "ltp": 243.3,
        "bid": 242.8,
        "ask": 243.8,
        "bid_qty": 2100,
        "ask_qty": 1875,
        "open": 231.15,
        "high": 262.75,
        "low": 216.55,
        "prev_close": 236.0,
        "volume": 3162450,
        "oi": 5104275,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 15.33,
        "delta": -0.4261,
        "gamma": 0.000513,
        "theta": -9.9854,
        "vega": 19.5342
      }
    },
    {
      "strike": 24550.0,
      "ce": {
        "symbol": "NIFTY25AUG2624550CE",
        "label": "ATM",
        "ltp": 311.6,
        "bid": 311.1,
        "ask": 312.1,
        "bid_qty": 1500,
        "ask_qty": 2250,
        "open": 330.3,
        "high": 345.9,
        "low": 286.65,
        "prev_close": 324.05,
        "volume": 2841075,
        "oi": 4218300,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 14.92,
        "delta": 0.5221,
        "gamma": 0.000536,
        "theta": -9.8729,
        "vega": 19.8452
      },
      "pe": {
        "symbol": "NIFTY25AUG2624550PE",
        "label": "ATM",
        "ltp": 281.6,
        "bid": 281.1,
        "ask": 282.1,
        "bid_qty": 2100,
        "ask_qty": 1875,
        "open": 267.5,
        "high": 304.15,
        "low": 250.6,
        "prev_close": 273.15,
        "volume": 3162450,
        "oi": 5104275,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 14.92,
        "delta": -0.4779,
        "gamma": 0.000536,
        "theta": -9.8729,
        "vega": 19.8452
      }
    },
    {
      "strike": 24650.0,
      "ce": {
        "symbol": "NIFTY25AUG2624650CE",
        "label": "OTM1",
        "ltp": 259.1,
        "bid": 258.6,
        "ask": 259.6,
        "bid_qty": 1500,
        "ask_qty": 2250,
        "open": 274.65,
        "high": 287.6,
        "low": 238.35,
        "prev_close": 269.45,
        "volume": 2841075,
        "oi": 4218300,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 14.71,
        "delta": 0.4679,
        "gamma": 0.000543,
        "theta": -9.717,
        "vega": 19.8115
      },
      "pe": {
        "symbol": "NIFTY25AUG2624650PE",
        "label": "ITM1",
        "ltp": 329.1,
        "bid": 328.6,
        "ask": 329.6,
        "bid_qty": 2100,
        "ask_qty": 1875,
        "open": 312.65,
        "high": 355.45,
        "low": 292.9,
        "prev_close": 319.25,
        "volume": 3162450,
        "oi": 5104275,
        "lotsize": 75,
        "tick_size": 0.05,
        "implied_volatility": 14.71,
        "delta": -0.5321,
        "gamma": 0.000543,
        "theta": -9.717,
        "vega": 19.8115
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
| exchange | Underlying exchange accepted by the shared validation constants | Mandatory | - |
| expiry_date | Expiry date in DDMMMYY format | Mandatory | - |
| strike_count | Number of strikes above and below ATM | Optional | All strikes |
| with_greeks | Attach implied volatility and Greeks to every leg | Optional | false |
| interest_rate | Risk-free rate as an annualized percentage, Greeks only | Optional | 0 |

`strike_count` must be between 1 and 100 when supplied, and `interest_rate` between 0 and 100. Broker adapters may use an optimized option-chain call; otherwise the service resolves contracts locally and retrieves quotes through the normalized market-data layer.

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| underlying | string | Underlying symbol |
| underlying_ltp | number | Current underlying price |
| underlying_prev_close | number | Underlying previous close |
| expiry_date | string | Expiry date in DDMMMYY format |
| expiry_ts | number \| null | Expiry instant as epoch seconds, carrying the exchange's cut-off time. `null` if it could not be derived |
| server_ts | number | Server time as epoch seconds |
| atm_strike | number | At-the-money strike price |
| quotes_included | boolean | Whether live quotes were fetched |
| greeks_included | boolean | Whether Greeks were attached |
| forward_price | number \| null | Forward price used for Greeks. `null` when Greeks were not requested |
| chain | array | Array of strike data |

### Chain Array Fields

| Field | Type | Description |
|-------|------|-------------|
| strike | number | Strike price |
| ce | object \| null | Call option data, `null` when the contract is not in the master contract |
| pe | object \| null | Put option data, `null` when the contract is not in the master contract |

### Option Data Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Option symbol |
| label | string | ATM, ITM1, ITM2..., OTM1, OTM2... |
| ltp | number | Last traded price |
| bid | number | Best bid price |
| ask | number | Best ask price |
| bid_qty | number | Quantity at the best bid |
| ask_qty | number | Quantity at the best ask |
| open | number | Day's open |
| high | number | Day's high |
| low | number | Day's low |
| prev_close | number | Previous close |
| volume | number | Trading volume |
| oi | number | Open interest |
| lotsize | number | Lot size |
| tick_size | number | Tick size |

### Greek Fields

Present on each leg only when `with_greeks` is set, and omitted for any leg whose Greeks are not computable.

| Field | Type | Description |
|-------|------|-------------|
| implied_volatility | number | Implied volatility as a percentage, e.g. `14.92` for 14.92% |
| delta | number | Change in option price per 1 point move in the underlying |
| gamma | number | Change in delta per 1 point move in the underlying |
| theta | number | Change in option price per calendar day |
| vega | number | Change in option price per 1% change in implied volatility |

## Greeks

Greeks are priced with the Black-76 model, which is the correct model for options on futures and forwards and therefore for Indian F&O. They are computed from the quotes the request has already fetched, so `with_greeks` adds **no extra broker calls** — the whole ladder is solved in a single vectorized pass.

- **Priced off the forward, not spot.** The forward comes from the ATM call and put via put-call parity (`forward = strike + call - put`), falling back to the underlying LTP when the ATM legs are unpriced. Indian index futures trade at a premium to spot, so pricing against spot would bias every delta.
- **Units match `/api/v1/optiongreeks`.** Vega is per 1% change in volatility and theta is per calendar day, so no conversion is needed.
- **Time to expiry** uses the exchange cut-off: 15:30 IST for NFO and BFO, 12:30 for CDS, 23:30 for MCX. `expiry_ts` exposes that instant so a client can compute its own time to expiry without re-deriving the policy.
- **Legs with no time value** — priced at or below intrinsic — return `implied_volatility: 0` with a delta of `1` or `-1` and the remaining Greeks `0`, rather than an error. An out-of-the-money leg whose volatility will not converge returns a delta of `0`.
- **`interest_rate` defaults to 0.** Set it explicitly if you want discounting applied.

## Notes

- Without **strike_count**, returns the **entire option chain** for the expiry
- The **label** field indicates whether the option is ATM, ITM, or OTM
- For CE options: strikes below ATM are ITM, above are OTM
- For PE options: strikes above ATM are ITM, below are OTM
- Use this for **options analysis** and **strategy selection**

## Use Cases

- **Option analysis**: View premiums across strikes
- **Strategy selection**: Find suitable strikes for spreads/strangles
- **Volatility analysis**: Compare implied volatility across the smile in one call
- **Risk management**: Read delta, gamma, theta and vega for the whole chain without a second request

## Related

- [OptionGreeks](optiongreeks.md) — Greeks for a single option
- [MultiOptionGreeks](multioptiongreeks.md) — Greeks for up to 50 options. Prefer `optionchain` with `with_greeks` for a whole chain, since it is not bound by that limit and costs no extra broker calls
- [SyntheticFuture](syntheticfuture.md) — the put-call parity forward on its own

---

**Back to**: [API Documentation](../README.md)
