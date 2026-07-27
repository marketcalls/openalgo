# Crypto Symbol Format

#### OpenAlgo Crypto Symbol Standardization

OpenAlgo maps every crypto contract to the **same OpenAlgo symbology used for
Indian F&O**, so a strategy written for `NIFTY…FUT` / `…CE` transfers to crypto
with no new syntax. Crypto instruments live under a single exchange code —
`CRYPTO` — with the broker identity carried in `brexchange` (e.g.
`deltaexchange`). This document is **code-accurate to the live Delta Exchange
integration** (`broker/deltaexchange/database/master_contract_db.py`,
`_to_canonical_symbol`).

> Design note: crypto **reuses the Indian dated-future and option renderers
> unchanged**. Only **perpetual futures** and **spot** are crypto-specific
> shapes. See the global-market design in
> [`docs/superpowers/`](../superpowers/README.md).

### Exchange Code

* **CRYPTO** — all crypto contracts (perpetuals, dated futures, options, spot).
  `brexchange` carries the actual venue (`deltaexchange`, and future
  `binance`, `coindcx`, `hyperliquid`).

### Perpetual Futures Format  *(crypto-specific)*

Perpetual (no-expiry) futures are the dominant crypto derivative.

**Format:** `[DeltaSymbol]FUT`

| Instrument | Venue native | OpenAlgo symbol | Quote (current) |
| --- | --- | --- | --- |
| BTC perpetual | `BTCUSD` | `BTCUSDFUT` | ≈ $62,000 |
| ETH perpetual | `ETHUSD` | `ETHUSDFUT` | — |

`instrumenttype = PERPFUT`, `expiry = ""` (empty — perpetuals never expire). The
symbol never encodes price — `BTCUSDFUT` marks the contract; its last-traded
value (≈ 62,000 USD today) lives in quotes, not the symbol.

> **Known discrepancy (tracked for P7 cleanup):** the code currently emits
> `…FUT` (e.g. `BTCUSDFUT`) while an in-code comment and some search aliases
> still reference the TradingView `.P` suffix (`BTCUSD.P`). The **stored/served
> canonical form is `BTCUSDFUT`**. Resolving this comment/code/alias
> inconsistency is a P7 task.

### Dated Futures Format  *(reuses the Indian future renderer)*

**Format:** `[Underlying][ExpiryDate]FUT` — identical to Indian futures.

| Instrument | Venue native | OpenAlgo symbol |
| --- | --- | --- |
| BTC future, 28 Feb 2025 | `BTCUSD28Feb2025` | `BTC28FEB25FUT` |

The quote-currency suffix (`USD`/`USDT`/`BTC`/`ETH`) is stripped to yield the
underlying, then `[Underlying][DDMONYY]FUT` is emitted — exactly the Indian
convention.

### Options Format  *(reuses the Indian option renderer)*

**Format:** `[Underlying][ExpiryDate][Strike][CE/PE]` — identical to Indian
options.

With BTC ≈ **$62,000**, the at-the-money strike is `62000`:

| Instrument | Venue native | OpenAlgo symbol |
| --- | --- | --- |
| BTC 62000 Call (ATM), 28 Feb 2025 | `C-BTC-62000-280225` | `BTC28FEB2562000CE` |
| BTC 62000 Put (ATM), 28 Feb 2025 | `P-BTC-62000-280225` | `BTC28FEB2562000PE` |
| BTC 65000 Call (OTM), 28 Feb 2025 | `C-BTC-65000-280225` | `BTC28FEB2565000CE` |
| BTC 60000 Put (OTM), 28 Feb 2025 | `P-BTC-60000-280225` | `BTC28FEB2560000PE` |

**Turbo** and **synthetic** options normalize to the same `CE`/`PE` suffix:
turbo-call (`TCE`) and synth-call (`SYNCE`) → `CE`; turbo-put (`TPE`) and
synth-put (`SYNPE`) → `PE`.

### Spot Format  *(crypto-specific)*

**Format:** `[Base][Quote]` — the venue pair with the underscore removed.

| Instrument | Venue native | OpenAlgo symbol | Price (current) |
| --- | --- | --- | --- |
| BTC/INR spot | `BTC_INR` | `BTCINR` | ≈ ₹59,52,000 |
| ETH/USDT spot | `ETH_USDT` | `ETHUSDT` | — |

`instrumenttype = SPOT`, `expiry = ""`. The quote currency is part of the pair,
not the symbol grammar: `BTCINR` settles in INR, `BTCUSDT` in USDT.

**Worked currency example (current market):** BTC ≈ **$62,000**, USD/INR ≈ **96**,
so `BTCINR` ≈ 62,000 × 96 = **₹59,52,000** (₹59.52 L). This is exactly why the
**Currency resolver** is keyed on the *instrument's* quote currency, not the
account's home currency — the same BTC contract is quoted ~62,000 on `BTCUSDFUT`
(USD) and ~₹59.5 L on `BTCINR` (INR). Formatting must follow the instrument.

### Other Contract Types

`MOVE` (move options), `IRS` (interest-rate swaps), `SPREAD`, and `COMBO`
(options combos) are retained in their **native venue form** (not remapped) until
a canonical convention is defined.

### Instrument Type Codes

Delta `contract_type` → OpenAlgo `instrumenttype`:

| Delta `contract_type` | OpenAlgo code | Renders as |
| --- | --- | --- |
| `perpetual_futures` | `PERPFUT` | `[sym]FUT` |
| `futures` | `FUT` | `[underlying][expiry]FUT` |
| `call_options` | `CE` | `…CE` |
| `put_options` | `PE` | `…PE` |
| `turbo_call_options` | `TCE` | `…CE` |
| `turbo_put_options` | `TPE` | `…PE` |
| `synth_call_options` | `SYNCE` | `…CE` |
| `synth_put_options` | `SYNPE` | `…PE` |
| `spot` | `SPOT` | `[base][quote]` |
| `move_options` | `MOVE` | native |
| `interest_rate_swaps` | `IRS` | native |
| `spreads` | `SPREAD` | native |
| `options_combos` | `COMBO` | native |

### Order Constants for Crypto

* **Exchange:** `CRYPTO`
* **Product:** crypto is leverage-based; product-type mapping is
  broker-declared in the capability manifest (see design docs). Do **not** assume
  Indian `CNC/NRML/MIS` apply.
* **Price Type:** `MARKET`, `LIMIT`, `SL`, `SL-M` (shared), plus venue-declared
  execution flags (`post_only`, `reduce_only`) and time-in-force (`IOC`, `FOK`,
  `GTC`) exposed additively via the manifest — **not** as Indian order flags.

### Database Schema (`SymToken`) for Crypto

Same table as Indian instruments:

| Field | Crypto meaning |
| --- | --- |
| `symbol` | OpenAlgo canonical (e.g. `BTCUSDFUT`) |
| `brsymbol` | Delta native (e.g. `BTCUSD`) |
| `exchange` | `CRYPTO` |
| `brexchange` | venue (`deltaexchange`) |
| `expiry` | `DD-MON-YY` for dated/option; `""` for perpetual/spot |
| `strike` | option strike (`Float` today — **precision revisit planned**, see design docs) |
| `lotsize` / `tick_size` / `contract_value` | contract metadata |
| `instrumenttype` | `PERPFUT` / `FUT` / `CE` / `PE` / `SPOT` / … |

> **Precision caveat:** `strike`, `tick_size`, and `contract_value` are `Float`
> today. Crypto/FX need Decimal + step-size + min-notional semantics — tracked as
> a design correction (P2). Do not rely on `Float` for exact crypto price/size
> math.

---

_Reference implementation:_ `broker/deltaexchange/database/master_contract_db.py`.
_Global-market design:_ [`docs/superpowers/`](../superpowers/README.md).
