# Option Greeks Baseline — py_vollib (Black-76)

Captured before migrating from `py_vollib==1.0.1` to `opengreeks`. This snapshot is the parity oracle for the post-migration check.

- **Engine**: `py_vollib==1.0.1` (Black-76, options on futures/forwards)
- **Service**: `services/option_greeks_service.py` → `POST /api/v1/optiongreeks`
- **Underlying**: NIFTY @ ₹23659.00 (NSE_INDEX LTP)
- **Expiry**: 26-MAY-2026 (`NIFTY26MAY26<strike><CE/PE>`)
- **Risk-free rate**: 0 (default for NFO in `DEFAULT_INTEREST_RATES`)
- **Samples**: 40 (20 CE + 20 PE)
- **Raw JSON**: [`greeks_baseline_pyvollib.json`](./greeks_baseline_pyvollib.json)

## Moneyness classification

Computed from strike vs spot (23659):

| Bucket | CE rule | PE rule |
|:---|:---|:---|
| DEEP ITM | strike ≤ spot − 1000 | strike ≥ spot + 1000 |
| ITM | spot − 1000 < strike < spot − 100 | spot + 100 < strike < spot + 1000 |
| ATM | \|strike − spot\| ≤ 100 | \|strike − spot\| ≤ 100 |
| OTM | spot + 100 < strike < spot + 1000 | spot − 1000 < strike < spot − 100 |
| DEEP OTM | strike ≥ spot + 1000 | strike ≤ spot − 1000 |

### Moneyness coverage

| Type | DEEP ITM | ITM | ATM | OTM | DEEP OTM | Total |
|:---|---:|---:|---:|---:|---:|---:|
| CE | 4 | 5 | 3 | 5 | 3 | 20 |
| PE | 3 | 5 | 3 | 5 | 4 | 20 |

### End-to-end latency (HTTP → broker quotes → py_vollib → response)

| Bucket | n | min | p50 | mean | p95 | max |
|:---|---:|---:|---:|---:|---:|---:|
| CE | 20 | 97.3 | 103.9 | 174.8 | 1198.1 | 1198.1 |
| PE | 20 | 99.7 | 120.1 | 273.3 | 1167.5 | 1167.5 |
| All | 40 | 97.3 | 113.0 | 224.0 | 1167.5 | 1198.1 |

*Latency is wall-clock per HTTP round-trip and dominated by broker quote fetching, not by py_vollib's math (which is microseconds). It serves as the baseline reference for the post-migration comparison.*

### CE samples (20 strikes, NIFTY26MAY26)

| Strike | Moneyness | Symbol | LTP | IV % | Delta | Gamma | Theta | Vega | Rho | Latency (ms) |
|---:|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| 21000 | DEEP ITM | `NIFTY26MAY2621000CE` | 2691.30 | 57.90 | +0.9550 | 0.000056 | -14.3378 | +2.7832 | -0.414380 | 1198.1 |
| 21500 | DEEP ITM | `NIFTY26MAY2621500CE` | 2183.45 | 45.83 | +0.9565 | 0.000069 | -11.0444 | +2.7088 | -0.336186 | 121.4 |
| 22000 | DEEP ITM | `NIFTY26MAY2622000CE` | 1701.40 | 41.61 | +0.9242 | 0.000117 | -15.5040 | +4.1885 | -0.261965 | 107.4 |
| 22500 | DEEP ITM | `NIFTY26MAY2622500CE` | 1204.20 | 32.06 | +0.9002 | 0.000186 | -14.6743 | +5.1451 | -0.185411 | 97.3 |
| 23000 | ITM | `NIFTY26MAY2623000CE` | 730.00 | 24.97 | +0.8231 | 0.000354 | -16.9218 | +7.6184 | -0.112398 | 103.0 |
| 23200 | ITM | `NIFTY26MAY2623200CE` | 554.95 | 22.80 | +0.7601 | 0.000464 | -18.5140 | +9.1251 | -0.085446 | 101.5 |
| 23300 | ITM | `NIFTY26MAY2623300CE` | 471.65 | 21.73 | +0.7192 | 0.000528 | -19.1358 | +9.8961 | -0.072620 | 103.9 |
| 23400 | ITM | `NIFTY26MAY2623400CE` | 391.00 | 20.57 | +0.6715 | 0.000599 | -19.4189 | +10.6121 | -0.060202 | 102.6 |
| 23500 | ITM | `NIFTY26MAY2623500CE` | 320.70 | 19.93 | +0.6122 | 0.000655 | -19.9383 | +11.2455 | -0.049378 | 364.6 |
| 23600 | ATM | `NIFTY26MAY2623600CE` | 256.35 | 19.29 | +0.5463 | 0.000700 | -19.9637 | +11.6329 | -0.039470 | 103.1 |
| 23650 | ATM | `NIFTY26MAY2623650CE` | 226.20 | 18.93 | +0.5111 | 0.000718 | -19.7185 | +11.7072 | -0.034828 | 104.3 |
| 23700 | ATM | `NIFTY26MAY2623700CE` | 199.10 | 18.68 | +0.4748 | 0.000726 | -19.4283 | +11.6885 | -0.030655 | 99.5 |
| 23800 | OTM | `NIFTY26MAY2623800CE` | 150.70 | 18.21 | +0.4006 | 0.000723 | -18.3779 | +11.3465 | -0.023203 | 108.7 |
| 23900 | OTM | `NIFTY26MAY2623900CE` | 109.50 | 17.69 | +0.3261 | 0.000694 | -16.6479 | +10.5800 | -0.016860 | 98.0 |
| 24000 | OTM | `NIFTY26MAY2624000CE` | 77.15 | 17.28 | +0.2557 | 0.000634 | -14.5179 | +9.4412 | -0.011879 | 99.7 |
| 24200 | OTM | `NIFTY26MAY2624200CE` | 34.60 | 16.70 | +0.1399 | 0.000454 | -9.6989 | +6.5295 | -0.005327 | 148.1 |
| 24500 | OTM | `NIFTY26MAY2624500CE` | 9.50 | 16.72 | +0.0471 | 0.000200 | -4.2949 | +2.8876 | -0.001463 | 103.7 |
| 25000 | DEEP OTM | `NIFTY26MAY2625000CE` | 1.90 | 19.03 | +0.0101 | 0.000048 | -1.3363 | +0.7891 | -0.000293 | 121.7 |
| 25500 | DEEP OTM | `NIFTY26MAY2625500CE` | 1.10 | 23.38 | +0.0051 | 0.000021 | -0.8992 | +0.4323 | -0.000169 | 103.1 |
| 26000 | DEEP OTM | `NIFTY26MAY2626000CE` | 0.80 | 27.77 | +0.0033 | 0.000012 | -0.7149 | +0.2893 | -0.000123 | 105.8 |

### PE samples (20 strikes, NIFTY26MAY26)

| Strike | Moneyness | Symbol | LTP | IV % | Delta | Gamma | Theta | Vega | Rho | Latency (ms) |
|---:|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| 21000 | DEEP OTM | `NIFTY26MAY2621000PE` | 2.15 | 38.47 | -0.0058 | 0.000015 | -1.6702 | +0.4879 | -0.000331 | 105.9 |
| 21500 | DEEP OTM | `NIFTY26MAY2621500PE` | 2.50 | 32.22 | -0.0079 | 0.000023 | -1.8238 | +0.6363 | -0.000385 | 290.2 |
| 22000 | DEEP OTM | `NIFTY26MAY2622000PE` | 3.95 | 26.89 | -0.0141 | 0.000045 | -2.5163 | +1.0518 | -0.000608 | 101.0 |
| 22500 | DEEP OTM | `NIFTY26MAY2622500PE` | 8.10 | 21.99 | -0.0318 | 0.000111 | -4.1036 | +2.0976 | -0.001247 | 853.2 |
| 23000 | OTM | `NIFTY26MAY2623000PE` | 30.30 | 18.88 | -0.1117 | 0.000343 | -9.3764 | +5.5816 | -0.004665 | 282.9 |
| 23200 | OTM | `NIFTY26MAY2623200PE` | 52.75 | 17.74 | -0.1838 | 0.000510 | -12.3182 | +7.8045 | -0.008122 | 567.1 |
| 23300 | OTM | `NIFTY26MAY2623300PE` | 69.90 | 17.23 | -0.2340 | 0.000606 | -13.7965 | +8.9996 | -0.010762 | 101.8 |
| 23400 | OTM | `NIFTY26MAY2623400PE` | 92.35 | 16.75 | -0.2946 | 0.000701 | -15.0875 | +10.1231 | -0.014219 | 99.7 |
| 23500 | OTM | `NIFTY26MAY2623500PE` | 121.00 | 16.28 | -0.3654 | 0.000787 | -15.9884 | +11.0392 | -0.018630 | 547.4 |
| 23600 | ATM | `NIFTY26MAY2623600PE` | 156.10 | 15.74 | -0.4453 | 0.000855 | -16.2454 | +11.6014 | -0.024034 | 288.8 |
| 23650 | ATM | `NIFTY26MAY2623650PE` | 176.25 | 15.44 | -0.4883 | 0.000880 | -16.0809 | +11.7044 | -0.027126 | 1167.5 |
| 23700 | ATM | `NIFTY26MAY2623700PE` | 199.00 | 15.17 | -0.5329 | 0.000893 | -15.7533 | +11.6696 | -0.030628 | 123.1 |
| 23800 | ITM | `NIFTY26MAY2623800PE` | 250.55 | 14.55 | -0.6256 | 0.000888 | -14.4062 | +11.1244 | -0.038561 | 113.8 |
| 23900 | ITM | `NIFTY26MAY2623900PE` | 306.70 | 13.41 | -0.7261 | 0.000846 | -11.6636 | +9.7744 | -0.047203 | 112.3 |
| 24000 | ITM | `NIFTY26MAY2624000PE` | 375.90 | 12.41 | -0.8217 | 0.000716 | -8.4579 | +7.6568 | -0.057853 | 120.1 |
| 24200 | ITM | `NIFTY26MAY2624200PE` | 531.60 | 0.00 | -1.0000 | 0.000000 | +0.0000 | +0.0000 | +0.000000 | 116.6 |
| 24500 | ITM | `NIFTY26MAY2624500PE` | 806.60 | 0.00 | -1.0000 | 0.000000 | +0.0000 | +0.0000 | +0.000000 | 116.5 |
| 25000 | DEEP ITM | `NIFTY26MAY2625000PE` | 1300.00 | 0.00 | -1.0000 | 0.000000 | +0.0000 | +0.0000 | +0.000000 | 129.9 |
| 25500 | DEEP ITM | `NIFTY26MAY2625500PE` | 1807.15 | 0.00 | -1.0000 | 0.000000 | +0.0000 | +0.0000 | +0.000000 | 115.5 |
| 26000 | DEEP ITM | `NIFTY26MAY2626000PE` | 2296.65 | 0.00 | -1.0000 | 0.000000 | +0.0000 | +0.0000 | +0.000000 | 113.0 |

## Notes

- All Greeks are returned in trader-friendly units by py_vollib's Black-76:
  - **Theta**: per-day (already scaled by 1/365 inside the library)
  - **Vega**: per 1% absolute vol change (scaled by 0.01)
  - **Rho**: per 1% absolute rate change (scaled by 0.01)
  - **IV** in the table is shown as percentage (the service multiplies the decimal by 100 for display).
- Deep-ITM options with option price ≤ intrinsic value return theoretical Greeks (Δ=±1, others=0, IV=0) — see `option_greeks_service.py` lines 348-378.
- The service auto-resolves the underlying for NIFTY → `NSE_INDEX` and uses spot LTP as the forward `F` in Black-76. For a more accurate parity check against a true forward, pass `forward_price` explicitly.

## Next step: opengreeks migration

The follow-up document `greeks_opengreeks_parity.md` will replay these same 40 samples against `opengreeks.black76` and report:

1. Bit-for-bit / max-abs / max-rel error vs this baseline for every Greek and IV
2. End-to-end latency improvement
3. Pure-math latency (`calculate_greeks()` excluding broker fetch) — the genuine apples-to-apples speedup
