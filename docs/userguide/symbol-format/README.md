# OpenAlgo Symbol Format Guide

## Introduction

OpenAlgo uses a standardized symbol format across all exchanges and brokers. This uniform symbology eliminates the need for traders to adapt to varied broker-specific formats, streamlining algorithm development and execution.

Understanding the symbol format is **essential** for placing orders correctly. Incorrect symbol format is the most common cause of order failures.

## Quick Reference

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OpenAlgo Symbol Format                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  EQUITY                                                                      │
│  ───────                                                                     │
│  Format: [Symbol]                                                           │
│  Example: SBIN, INFY, RELIANCE, TATAMOTORS                                  │
│                                                                              │
│  FUTURES                                                                     │
│  ────────                                                                    │
│  Format: [Symbol][DD][MMM][YY]FUT                                           │
│  Example: NIFTY30JAN25FUT, BANKNIFTY27FEB25FUT                             │
│                                                                              │
│  OPTIONS                                                                     │
│  ────────                                                                    │
│  Format: [Symbol][DD][MMM][YY][Strike][CE/PE]                               │
│  Example: NIFTY30JAN2521500CE, BANKNIFTY27FEB2548000PE                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Equity Symbol Format

Equity symbols use the base trading symbol without any modifications.

### Format

```
[Base Symbol]
```

### Examples

| Company | Base Symbol | OpenAlgo Symbol |
|---------|-------------|-----------------|
| State Bank of India | SBIN | `SBIN` |
| Infosys | INFY | `INFY` |
| Reliance Industries | RELIANCE | `RELIANCE` |
| Tata Motors | TATAMOTORS | `TATAMOTORS` |
| HDFC Bank | HDFCBANK | `HDFCBANK` |
| ICICI Bank | ICICIBANK | `ICICIBANK` |
| Tata Consultancy Services | TCS | `TCS` |

### Usage

```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "CNC"
}
```

## Future Symbol Format

Futures symbols include the base symbol, expiry date, and "FUT" suffix.

### Format

```
[Base Symbol][DD][MMM][YY]FUT
```

Where:
- **Base Symbol**: Underlying symbol (e.g., NIFTY, BANKNIFTY, SBIN)
- **DD**: Two-digit day of expiry (e.g., 30, 27, 25)
- **MMM**: Three-letter month in CAPS (JAN, FEB, MAR, APR, MAY, JUN, JUL, AUG, SEP, OCT, NOV, DEC)
- **YY**: Two-digit year (e.g., 25 for 2025)
- **FUT**: Literal suffix indicating futures

### Examples

| Description | OpenAlgo Symbol |
|-------------|-----------------|
| Nifty Future expiring 30th Jan 2025 | `NIFTY30JAN25FUT` |
| Bank Nifty Future expiring 27th Feb 2025 | `BANKNIFTY27FEB25FUT` |
| SBIN Future expiring 27th Mar 2025 | `SBIN27MAR25FUT` |
| SENSEX Future expiring 28th Feb 2025 | `SENSEX28FEB25FUT` |
| USDINR Future expiring 27th Jan 2025 | `USDINR27JAN25FUT` |
| Crude Oil Future expiring 19th Feb 2025 | `CRUDEOIL19FEB25FUT` |

### Usage

```json
{
  "symbol": "NIFTY30JAN25FUT",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

## Options Symbol Format

Options symbols include the base symbol, expiry date, strike price, and option type.

### Format

```
[Base Symbol][DD][MMM][YY][Strike][CE/PE]
```

Where:
- **Base Symbol**: Underlying symbol
- **DD**: Two-digit day of expiry
- **MMM**: Three-letter month in CAPS
- **YY**: Two-digit year
- **Strike**: Strike price (can include decimals for stock options)
- **CE**: Call option
- **PE**: Put option

### Examples

#### Index Options (NSE)

| Description | OpenAlgo Symbol |
|-------------|-----------------|
| Nifty 21500 Call, 30th Jan 2025 | `NIFTY30JAN2521500CE` |
| Nifty 21000 Put, 30th Jan 2025 | `NIFTY30JAN2521000PE` |
| Bank Nifty 48000 Call, 27th Feb 2025 | `BANKNIFTY27FEB2548000CE` |
| Bank Nifty 47500 Put, 27th Feb 2025 | `BANKNIFTY27FEB2547500PE` |
| Fin Nifty 22000 Call, 28th Jan 2025 | `FINNIFTY28JAN2522000CE` |

#### Stock Options (NSE)

| Description | OpenAlgo Symbol |
|-------------|-----------------|
| SBIN 800 Call, 27th Feb 2025 | `SBIN27FEB25800CE` |
| RELIANCE 1300 Put, 27th Feb 2025 | `RELIANCE27FEB251300PE` |
| VEDL 292.50 Call, 24th Apr 2025 | `VEDL24APR25292.5CE` |

#### Currency Options

| Description | OpenAlgo Symbol |
|-------------|-----------------|
| USDINR 84 Call, 27th Jan 2025 | `USDINR27JAN2584CE` |
| USDINR 83.50 Put, 27th Jan 2025 | `USDINR27JAN2583.5PE` |

#### Commodity Options (MCX)

| Description | OpenAlgo Symbol |
|-------------|-----------------|
| Crude Oil 6500 Call, 17th Feb 2025 | `CRUDEOIL17FEB256500CE` |
| Gold 62000 Put, 5th Feb 2025 | `GOLD05FEB2562000PE` |

### Usage

```json
{
  "symbol": "NIFTY30JAN2521500CE",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

## Exchange Codes

OpenAlgo uses standardized exchange codes to identify trading venues.

### Equity Exchanges

| Exchange | Code | Description |
|----------|------|-------------|
| National Stock Exchange | `NSE` | NSE equities |
| Bombay Stock Exchange | `BSE` | BSE equities |

### Derivatives Exchanges

| Exchange | Code | Description |
|----------|------|-------------|
| NSE F&O | `NFO` | NSE Futures & Options |
| BSE F&O | `BFO` | BSE Futures & Options |

### Currency Derivatives

| Exchange | Code | Description |
|----------|------|-------------|
| NSE Currency | `CDS` | NSE Currency Derivatives |
| BSE Currency | `BCD` | BSE Currency Derivatives |

### Commodity Exchange

| Exchange | Code | Description |
|----------|------|-------------|
| Multi Commodity Exchange | `MCX` | Commodities trading |

### Index Symbols

| Exchange | Code | Description |
|----------|------|-------------|
| NSE Index | `NSE_INDEX` | NSE index values |
| BSE Index | `BSE_INDEX` | BSE index values |

## Common Index Symbols

### NSE Indices (Exchange: NSE_INDEX)

| Symbol | Description |
|--------|-------------|
| `NIFTY` | Nifty 50 |
| `BANKNIFTY` | Nifty Bank |
| `FINNIFTY` | Nifty Financial Services |
| `NIFTYNXT50` | Nifty Next 50 |
| `MIDCPNIFTY` | Nifty Midcap Select |
| `INDIAVIX` | India VIX |

### BSE Indices (Exchange: BSE_INDEX)

| Symbol | Description |
|--------|-------------|
| `SENSEX` | S&P BSE Sensex |
| `BANKEX` | S&P BSE Bankex |
| `SENSEX50` | S&P BSE Sensex 50 |

## Product Types

| Product | Description | Use Case |
|---------|-------------|----------|
| `MIS` | Margin Intraday Square-off | Intraday equity/F&O |
| `CNC` | Cash and Carry | Delivery equity |
| `NRML` | Normal | Overnight F&O positions |

## Complete Order Examples

### Equity Intraday Order

```json
{
  "apikey": "your-api-key",
  "strategy": "MyStrategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Equity Delivery Order

```json
{
  "apikey": "your-api-key",
  "strategy": "Investment",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "10",
  "pricetype": "LIMIT",
  "price": "2450.00",
  "product": "CNC"
}
```

### Futures Order

```json
{
  "apikey": "your-api-key",
  "strategy": "FuturesStrategy",
  "symbol": "NIFTY30JAN25FUT",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

### Options Order

```json
{
  "apikey": "your-api-key",
  "strategy": "OptionsStrategy",
  "symbol": "NIFTY30JAN2521500CE",
  "exchange": "NFO",
  "action": "BUY",
  "quantity": "50",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

### Currency Futures Order

```json
{
  "apikey": "your-api-key",
  "strategy": "CurrencyStrategy",
  "symbol": "USDINR27JAN25FUT",
  "exchange": "CDS",
  "action": "BUY",
  "quantity": "1",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

### Commodity Futures Order

```json
{
  "apikey": "your-api-key",
  "strategy": "CommodityStrategy",
  "symbol": "CRUDEOIL19FEB25FUT",
  "exchange": "MCX",
  "action": "BUY",
  "quantity": "1",
  "pricetype": "MARKET",
  "product": "NRML"
}
```

## Multi-Leg Options Strategies

### Bull Call Spread

```json
{
  "apikey": "your-api-key",
  "strategy": "BullCallSpread",
  "orders": [
    {
      "symbol": "NIFTY30JAN2521500CE",
      "exchange": "NFO",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY30JAN2521600CE",
      "exchange": "NFO",
      "action": "SELL",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    }
  ]
}
```

### Iron Condor

```json
{
  "apikey": "your-api-key",
  "strategy": "IronCondor",
  "orders": [
    {
      "symbol": "NIFTY30JAN2522000CE",
      "exchange": "NFO",
      "action": "SELL",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY30JAN2522100CE",
      "exchange": "NFO",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY30JAN2521000PE",
      "exchange": "NFO",
      "action": "SELL",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY30JAN2520900PE",
      "exchange": "NFO",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    }
  ]
}
```

## Finding the Correct Symbol

### Method 1: OpenAlgo Symbol Search

1. Go to OpenAlgo dashboard
2. Navigate to **Search** page
3. Enter the symbol name
4. Copy the exact symbol from results

### Method 2: Master Contract Database

OpenAlgo maintains a master contract database that maps broker symbols to standardized symbols. The database is updated daily.

### Method 3: API Endpoint

```
POST /api/v1/search
{
  "apikey": "your-key",
  "query": "NIFTY"
}
```

## Common Mistakes

### Mistake 1: Wrong Date Format

```
❌ NIFTY25JAN2521500CE      (missing day)
❌ NIFTYJAN2521500CE        (missing day and year format)
✅ NIFTY30JAN2521500CE      (correct)
```

### Mistake 2: Wrong Exchange Code

```
❌ symbol: "NIFTY30JAN2521500CE", exchange: "NSE"  (wrong exchange)
✅ symbol: "NIFTY30JAN2521500CE", exchange: "NFO"  (correct)
```

### Mistake 3: Wrong Product Type

```
❌ Options with product: "CNC"  (CNC is for equity only)
✅ Options with product: "NRML" (correct for F&O)
```

### Mistake 4: Case Sensitivity

```
❌ "sbin", "Sbin"  (lowercase/mixed case)
✅ "SBIN"          (uppercase - correct)
```

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| Symbol not found | Incorrect format | Verify symbol using Search |
| Invalid exchange | Wrong exchange code | Match exchange to instrument type |
| Order rejected | Expired contract | Update to current expiry |
| Invalid product | Wrong product type | Use MIS/NRML for F&O, CNC for delivery |

## Symbol Format Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OpenAlgo Symbol Quick Reference                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  TYPE          FORMAT                      EXAMPLE                          │
│  ────          ──────                      ───────                          │
│  Equity        [Symbol]                    SBIN                             │
│  Future        [Symbol][DD][MMM][YY]FUT    NIFTY30JAN25FUT                  │
│  Call Option   [Symbol][DD][MMM][YY][Strike]CE   NIFTY30JAN2521500CE       │
│  Put Option    [Symbol][DD][MMM][YY][Strike]PE   NIFTY30JAN2521000PE       │
│                                                                              │
│  EXCHANGE CODES                                                             │
│  ──────────────                                                             │
│  NSE     = NSE Equity           NFO = NSE F&O                              │
│  BSE     = BSE Equity           BFO = BSE F&O                              │
│  CDS     = NSE Currency         BCD = BSE Currency                         │
│  MCX     = Commodities                                                      │
│  NSE_INDEX / BSE_INDEX = Index values                                       │
│                                                                              │
│  PRODUCT CODES                                                              │
│  ─────────────                                                              │
│  MIS  = Intraday                                                            │
│  CNC  = Delivery (Equity only)                                              │
│  NRML = Overnight (F&O)                                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**Return to**: [User Guide Home](../README.md)
