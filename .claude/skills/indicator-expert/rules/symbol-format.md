# OpenAlgo Symbol Format

## Exchange Codes

| Exchange | Code | Description |
|----------|------|-------------|
| NSE | `NSE` | National Stock Exchange equities |
| BSE | `BSE` | Bombay Stock Exchange equities |
| NFO | `NFO` | NSE Futures and Options |
| BFO | `BFO` | BSE Futures and Options |
| CDS | `CDS` | NSE Currency Derivatives |
| BCD | `BCD` | BSE Currency Derivatives |
| MCX | `MCX` | Multi Commodity Exchange |
| NSE_INDEX | `NSE_INDEX` | NSE Indices |
| BSE_INDEX | `BSE_INDEX` | BSE Indices |

## Equity Symbols

Direct base symbol. Examples:
- `SBIN` (NSE/BSE)
- `RELIANCE` (NSE/BSE)
- `INFY` (NSE/BSE)
- `TATAMOTORS` (NSE/BSE)

## Futures Format

`[BaseSymbol][ExpiryDate]FUT`

Examples:
- `BANKNIFTY24APR24FUT` — Bank Nifty futures
- `NIFTY30DEC25FUT` — Nifty futures
- `USDINR10MAY24FUT` — Currency futures
- `CRUDEOILM20MAY24FUT` — MCX crude oil

## Options Format

`[BaseSymbol][ExpiryDate][StrikePrice][CE/PE]`

Examples:
- `NIFTY28MAR2420800CE` — Nifty 20800 Call
- `VEDL25APR24292.5CE` — VEDL 292.5 Call
- `USDINR19APR2482CE` — Currency option
- `CRUDEOIL17APR246750CE` — MCX option

## Common NSE Index Symbols (NSE_INDEX)

| Symbol | Description |
|--------|-------------|
| NIFTY | Nifty 50 |
| BANKNIFTY | Bank Nifty |
| FINNIFTY | Fin Nifty |
| MIDCPNIFTY | Midcap Nifty |
| NIFTYNXT50 | Nifty Next 50 |
| NIFTYIT | Nifty IT |
| NIFTYPHARMA | Nifty Pharma |
| NIFTYAUTO | Nifty Auto |
| NIFTYMETAL | Nifty Metal |
| NIFTYPVTBANK | Nifty Private Bank |
| NIFTYPSUBANK | Nifty PSU Bank |
| NIFTYREALTY | Nifty Realty |
| NIFTYENERGY | Nifty Energy |
| NIFTYFMCG | Nifty FMCG |
| NIFTYMIDCAP50 | Nifty Midcap 50 |
| NIFTYSMLCAP50 | Nifty Smallcap 50 |
| INDIAVIX | India VIX |

## Common BSE Index Symbols (BSE_INDEX)

| Symbol | Description |
|--------|-------------|
| SENSEX | Sensex 30 |
| BANKEX | Bank Index |
| SENSEX50 | Sensex 50 |

## API Usage

```python
# Equity
df = client.history(symbol="SBIN", exchange="NSE", interval="D", ...)

# Index
df = client.history(symbol="NIFTY", exchange="NSE_INDEX", interval="D", ...)

# Futures
df = client.history(symbol="NIFTY30DEC25FUT", exchange="NFO", interval="5m", ...)

# Quotes
quote = client.quotes(symbol="SBIN", exchange="NSE")

# Symbol lookup
info = client.symbol(symbol="NIFTY30DEC25FUT", exchange="NFO")
# Returns: {symbol, brsymbol, exchange, expiry, lotsize, tick_size, token, ...}

# Option chain
chain = client.optionchain(underlying="NIFTY", exchange="NSE_INDEX", expiry_date="30DEC25")
```
