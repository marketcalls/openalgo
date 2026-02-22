# OpenAlgo — Delta Exchange Integration

## CRYPTO Exchange Architecture (Final Design)

**Author:** Bashab Bhattacharjee (github.com/tradesbybashab)\
**Scope:** Full broker integration, CRYPTO exchange abstraction, canonical symbol alignment, analytics integration, streaming, sandbox, and deployment model.\
**Status:** Production-validated

---

# 1. Executive Summary

Delta Exchange India has been integrated into OpenAlgo as a **crypto broker** under a generalized exchange abstraction:

- `exchange = "CRYPTO"` (user-facing, asset class)
- `brexchange = "DELTAIN"` (broker identity, internal)

The integration includes:

- HMAC-SHA256 REST authentication
- Cursor-based master contract sync
- Canonical symbol normalization (Indian F&O style)
- WebSocket public + private feeds
- Smart per-exchange master contract cutoff (UTC for crypto)
- Leverage pre-order flow
- Rate-limit retry system
- Sandbox compatibility
- Analytics integration (Option Chain, OI, IV, GEX, etc.)
- Python 3.13-safe Black-76 Greeks engine fallback
- TLS hardening
- Production live-order validation

This document describes the **final architecture only**.

---

# 2. Exchange vs Broker Model

## 2.1 Separation of Concerns

| Field        | Value     | Purpose                                               |
| ------------ | --------- | ----------------------------------------------------- |
| `exchange`   | `CRYPTO`  | Asset class routing, analytics grouping, user-visible |
| `brexchange` | `DELTAIN` | Broker identity used by adapter                       |

This enables:

- Future addition of other crypto brokers (Binance, Bybit)
- Shared analytics layer across crypto exchanges
- Clean separation between broker API and asset class

---

# 3. Canonical Symbol Specification (Final)

CRYPTO symbols follow the **Indian F&O dashless format**, identical to NFO/MCX/BFO.

## 3.1 Perpetual

| Canonical | Broker   |
| --------- | -------- |
| `BTCUSDT` | `BTCUSD` |

Rule: append `T` to broker USD pair.

---

## 3.2 Futures

| Canonical       | Example                |
| --------------- | ---------------------- |
| `BTC28FEB25FUT` | 28 Feb 2025 BTC future |

Format:

```
{UNDERLYING}{DDMMMYY}FUT
```

---

## 3.3 Options

| Canonical           | Broker               |
| ------------------- | -------------------- |
| `BTC28FEB2580000CE` | `C-BTC-80000-280225` |
| `BTC28FEB2580000PE` | `P-BTC-80000-280225` |

Format:

```
{UNDERLYING}{DDMMMYY}{STRIKE}{CE|PE}
```

---

# 4. Master Contract Architecture

## 4.1 Cursor-Based Sync

Endpoint:

```
GET /v2/products
```

Delta uses cursor pagination (`meta.after`).

---

## 4.2 Canonical Transformation

At sync time:

- `symbol` → canonical CRYPTO format
- `brsymbol` → Delta-native
- `exchange = "CRYPTO"`
- `brexchange = "DELTAIN"`

Handled by `_to_canonical_symbol()`.

---

## 4.3 Smart Download Cutoff (Per Exchange Type)

Indian exchanges use IST cutoff. Crypto uses UTC cutoff.

| Variable                             | Applies To     | Default   |
| ------------------------------------ | -------------- | --------- |
| `MASTER_CONTRACT_CUTOFF_TIME`        | Indian brokers | 08:00 IST |
| `CRYPTO_MASTER_CONTRACT_CUTOFF_TIME` | Crypto brokers | 00:00 UTC |

---

# 5. REST API Layer

## 5.1 Authentication

Signature formula:

```
signature = HMAC(secret, METHOD + timestamp + path + query + body)
```

Headers:

```
api-key
timestamp
signature
```

---

## 5.2 Order Flow

Composite Order ID:

```
"{product_id}:{order_id}"
```

Leverage pre-call endpoint:

```
POST /v2/products/{id}/orders/leverage
```

---

## 5.3 Rate Limit Handling

- 3 retries
- Exponential backoff
- Retry-After honored
- Fresh signature per retry

---

# 6. WebSocket Architecture

## Public Channels

- L1
- L2
- Trades
- Mark Price

## Private Channels

- Orders
- Positions
- Margins

Security: TLS `CERT_REQUIRED`

---

# 7. Analytics Integration

- Direct broker bypass for CRYPTO
- `construct_crypto_option_symbol()`
- Regex underlying extraction: `^([A-Z]+)(?=\d)`
- scipy Black-76 Greeks engine

---

# 8. Sandbox Integration

Classification:

```
symbol.endswith("CE") / "PE" → option
symbol.endswith("FUT") → future
else → perpetual
```

---

# 9. Security & Operational Notes

- TLS verification enforced
- IP whitelist required (Delta account-level)
- Leverage strict mode available

---

# 10. Environment Variables

| Variable                             | Purpose              |
| ------------------------------------ | -------------------- |
| `BROKER_API_KEY`                     | Delta API key        |
| `BROKER_API_SECRET`                  | Delta secret         |
| `DELTA_DEFAULT_LEVERAGE`             | Default leverage     |
| `DELTA_ABORT_ON_LEVERAGE_FAILURE`    | Strict leverage mode |
| `CRYPTO_MASTER_CONTRACT_CUTOFF_TIME` | UTC cutoff           |
| `MASTER_CONTRACT_CUTOFF_TIME`        | IST cutoff           |

---

# Final State

Delta Exchange integration is:

- Exchange/broker separated
- Canonically aligned
- UTC-aware
- Python 3.13 compatible
- Production hardened
- Scalable to future crypto brokers

