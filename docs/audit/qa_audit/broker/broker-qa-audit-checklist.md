# Broker QA Audit — Checklist for Automated Live + Sandbox Testing

Per-broker acceptance audit, written to be executed by a script during market
hours against a single configured broker, first in **live** mode and then in
**sandbox (analyzer)** mode, producing a colour-coded `.xlsx` report.

This document defines **what to test and what "pass" means**. It is the input
specification for the automation script; it is not the script.

**Related documents**

| Topic | File |
| --- | --- |
| Service-layer contracts and exact signatures | [`services_documentation.md`](../../../prompt/services_documentation.md) |
| Symbol format, index symbol sets, exchange codes | [`symbol-format.md`](../../../prompt/symbol-format.md) |
| Product / pricetype / action / exchange constants | [`order-constants.md`](../../../prompt/order-constants.md) |
| Lot sizes | [`LotSize.md`](../../../prompt/LotSize.md) |
| WebSocket wire protocol | [`websockets-format.md`](../../../prompt/websockets-format.md) |
| Per-endpoint request/response shapes | `docs/api/**` |
| Broker plugin internals and known failure modes | `.claude/skills/broker-integration/` |
| Manual broker-agnostic test plan (predecessor) | `docs/test/BROKER_INTEGRATION_TESTING_GUIDE.md` |
| Gap analysis of the existing harness vs this checklist | [`broker-qa-existing-harness-gap-analysis.md`](../../../prompt/broker-qa-existing-harness-gap-analysis.md) |
| Zerodha-only addendum — MCX lot size (units vs contracts) | [`zerodha-mcx-lotsize-qa.md`](../../../prompt/zerodha-mcx-lotsize-qa.md) |
| Existing automated harness (prior art) | `test/test_broker.py` |

---

## 0. Scope

### 0.1 In scope

Every `/api/v1/*` surface listed below, the WebSocket feed, and the symbol
master behind them:

- Order management: placeorder, placesmartorder, basketorder, splitorder,
  optionsorder, optionsmultiorder, modifyorder, cancelorder, cancelallorder,
  closeposition
- GTT: placegttorder, modifygttorder, cancelgttorder, gttorderbook
- Order information: orderstatus, openposition
- Account: orderbook, tradebook, positionbook, holdings, funds, margin
- Market data: quotes, multiquotes, depth, history, intervals
- Symbol services: symbol, search, instruments, expiry
- Options services: optionsymbol, optionchain, optiongreeks,
  multioptiongreeks, syntheticfuture
- WebSocket: authenticate, ping, subscribe/unsubscribe (LTP / Quote / Depth),
  batch subscription, mode switching, unsubscribe-all, order updates
- Master contract / `symtoken` integrity

### 0.2 Explicitly out of scope

Excluded by instruction; the script must not spend budget on them:

- Utilities API (ping, analyzer status/toggle, market holidays, market
  timings, chart preferences) — **except** that `analyzer/toggle` is used as
  harness plumbing to switch modes, and its success is a precondition, not a
  test result
- Strategy RMS API and the `/strategy` module
- Rate-limiting behaviour as a test target (the script must still *respect*
  limits — see §1.5)
- API collections (Postman/Bruno exports)

---

## 1. Preconditions and harness rules

### 1.1 Environment

| ID | Check | Pass criteria |
| --- | --- | --- |
| PRE-01 | Broker id under test resolved from the active `Auth` row | Exactly one non-revoked row for the broker |
| PRE-02 | `plugin.json` read for `supported_exchanges`, `broker_type` | List captured; it is the **promise** that drives which exchange rows are mandatory |
| PRE-03 | Broker login valid and token not expired | Any authenticated call returns non-403 |
| PRE-04 | Master contract status is `success` for today | `master_contract_status` table shows today's successful download |
| PRE-05 | Market is open for each exchange under test | Equity/F&O and MCX have different sessions; skip-with-reason, never fail, outside session |
| PRE-06 | Both modes reachable | `analyzer/toggle` flips live <-> sandbox and back cleanly |

### 1.2 Run matrix

Every test case carries a **mode** dimension:

- **LIVE** — real broker. Order-placing cases use minimum quantity and the
  cheapest listed instrument per segment.
- **SANDBOX** — analyzer mode. Routes to `sandbox_service`; the broker plugin
  is never called.

Sandbox passing proves nothing about the broker integration. It is run to
prove *parity of contract* (same field names, same types, same status
vocabulary) and to exercise order lifecycles that are unsafe to force live.
Every result row must say which mode produced it.

### 1.3 Test symbol matrix (fill once per broker, before any test runs)

Resolve these from `/api/v1/search` + `/api/v1/expiry` at run start; never
hard-code. One row per exchange in `supported_exchanges`:

| Slot | Meaning |
| --- | --- |
| `EQ_LIQUID` | NSE/BSE liquid equity (e.g. a large-cap) |
| `EQ_CHEAP` | Lowest-priced liquid equity — the order-placement instrument |
| `EQ_SPECIAL` | Symbol with a hyphen, digit or renamed listing (e.g. `BAJAJ-AUTO`, `M&M`, a `-BE` series, a recently renamed scrip) |
| `IDX_NSE` / `IDX_BSE` | `NIFTY`, `SENSEX` on `NSE_INDEX` / `BSE_INDEX` |
| `IDX_MCX` | An `MCX_INDEX` symbol, only if the broker claims it |
| `FUT_NEAR` | Near-month index future per exchange (NFO/BFO/CDS/BCD/MCX/NCO) |
| `OPT_ATM_CE` / `OPT_ATM_PE` | Near-expiry ATM option per derivatives exchange |
| `OPT_CHEAP` | **`OTM40`** — the option 40 strikes out of the money, resolved via `/optionsymbol`. Deep enough OTM to carry a near-zero premium, so it is the F&O order-placement instrument for every live order-placing case |
| `OPT_DECIMAL_STRIKE` | An option whose strike has a decimal (e.g. `...292.5CE`) |
| `HOLDING_SYM` | A symbol actually present in holdings, if any |

Record the resolved matrix in the report. A slot that cannot be resolved is
itself a finding (see MC-08).

### 1.4 Safety rails

- Order-placement cases use **1 lot / 1 share** unless the case is explicitly
  about quantity (freeze-qty, split).
- Every live order placed by the run must be cancelled or squared off by the
  same run. The harness maintains an order ledger and runs a teardown pass.
- `cancelallorder` and `closeposition` are destructive and account-wide. Run
  them only at the end of the live phase, and only after recording the
  pre-existing orderbook/positionbook so foreign rows can be reported.
- Never place an order that could fill at an unintended price: use LIMIT far
  from LTP for resting-order tests, MARKET only where a fill is the assertion.

### 1.5 Pacing

Respect the broker's own per-category limits (quote limits are typically far
tighter than order limits) and OpenAlgo's per-IP `API_RATE_LIMIT`. A 429 is a
**harness defect**, not a broker finding — retry with backoff and flag the
test as `RETRIED`, not `FAIL`.

### 1.6 Universal assertions (apply to every case)

| ID | Check |
| --- | --- |
| UNI-01 | HTTP status matches the documented status for the scenario |
| UNI-02 | `status` field is exactly `"success"` or `"error"` — never absent, never a broker-native word |
| UNI-03 | On `error`, a human-readable `message` is present and no stack trace or raw broker payload leaks |
| UNI-04 | Field **names** match `docs/api/**` exactly (no broker-native keys surfacing) |
| UNI-05 | Field **types** match the documented type (a documented `number` is not returned as `"1,234.50"`) |
| UNI-06 | No `null` where the doc specifies a value; no `NaN`, `Infinity`, or `-0.0` |
| UNI-07 | Every price is rounded to **2 decimal places** in book/account responses |
| UNI-08 | No API key, auth token or feed token appears in the response or in `log/errors.jsonl` |
| UNI-09 | Round-trip latency recorded for every call (see §13) |
| UNI-10 | `log/errors.jsonl` is checked after each section; new entries are attached to the report even when the case passed |

---

## 2. Master contract and symbol master

Run before everything else — symbols must exist before quotes or orders can be
tested. Assertions are against the local `symtoken` table and
`/api/v1/instruments`.

| ID | Check | Pass criteria |
| --- | --- | --- |
| MC-01 | Download completes | `master_contract_status` = `success`; duration recorded |
| MC-02 | Row count per exchange | Non-zero for **every** exchange in `supported_exchanges`; counts recorded for trend comparison against the previous run |
| MC-03 | No duplicate `(symbol, exchange)` | Zero duplicates |
| MC-04 | `instrumenttype` vocabulary | Only `EQ`, `FUT`, `CE`, `PE` (and `''`). **There is no `INDEX` type** — indices are `EQ` on `NSE_INDEX` / `BSE_INDEX` |
| MC-05 | Expiry format | `DD-MMM-YY` uppercase (e.g. `30-JUN-26`); empty string for EQ and index rows. Checked for **FUT and OPT separately**, on every derivatives exchange |
| MC-06 | Symbol construction per segment | EQ: bare base symbol. FUT: `{underlying}{DDMMMYY}FUT`. CE/PE: `{underlying}{DDMMMYY}{strike}{CE\|PE}` with decimals preserved (`187.5`) and `.0` dropped. Sampled 3 rows per segment per exchange against [`symbol-format.md`](../../../prompt/symbol-format.md) |
| MC-07 | Index normalization | Every index symbol in the canonical `NSE_INDEX` / `BSE_INDEX` / `MCX_INDEX` lists in [`symbol-format.md`](../../../prompt/symbol-format.md) is present with the exact spelling; `brsymbol` holds the broker's display name (`NIFTY 50`) |
| MC-08 | **Missing-symbol report** | Diff the canonical index lists and a reference symbol set against the broker's master. Every missing symbol is **listed by name** in the report — this is a named deliverable, not a pass/fail flag. A symbol missing because the listing was renamed or delisted is annotated, not counted as a defect |
| MC-09 | `strike` is a float | Numeric; decimal strikes survive (`292.5`); non-options carry the sentinel (`0` or `-0.01`) consistently, not a mix |
| MC-10 | Strike scaling per segment | Cross-check `strike` against the strike embedded in `brsymbol` for one row per segment. Currency derivatives commonly scale differently from equity/index |
| MC-11 | `tick_size` present and correct per slab | Non-zero for every tradable row; in rupees, not paise. Asserted against the NSE slab tables and the named instrument matrix in §2.1 |
| MC-12 | `lotsize` | Non-zero for all derivatives; index and stock lot sizes match [`LotSize.md`](../../../prompt/LotSize.md) for NIFTY / BANKNIFTY / SENSEX etc. Lot is consistent across every expiry of the same underlying. Commodity lot conventions vary by broker — record the observed convention in the `Quirks` sheet rather than asserting one |
| MC-13 | `brexchange` populated | Raw broker exchange code present on every row |
| MC-14 | `name` column | Underlying for FUT/CE/PE; company name for EQ; display name for index |
| MC-15 | `token` populated | Non-empty and unique within an exchange |
| MC-16 | `contract_value` column exists | Declared in the model even if NULL |
| MC-17 | `/api/v1/instruments` JSON | Returns rows for each exchange; field names match the symtoken schema |
| MC-18 | `/api/v1/instruments` CSV | `Content-Type: text/csv`, filename `instruments_<exchange>.csv`, row count matches the JSON form |
| MC-19 | `/api/v1/instruments` invalid exchange | Clean 400, not a 500 |

### 2.1 Tick size — the standard slabs and the instrument matrix

`tick_size` is not a single value per exchange. On NSE it is a **price slab**,
so a check that only asserts "non-zero" passes a broker that returns `0.05`
for everything. Assert the slab.

**Capital market and stock futures** (NSE, effective 2025 revision):

| Security price (Rs) | Tick size (Rs) |
| --- | --- |
| Below 250 | 0.01 |
| 250 – 1,000 | 0.05 |
| 1,000 – 5,000 | 0.10 |
| 5,000 – 10,000 | 0.50 |
| 10,000 – 20,000 | 1.00 |
| Above 20,000 | 5.00 |

**Stock futures inherit the underlying's tick.** A stock future whose tick
differs from its cash symbol is a defect.

**Index futures** (by index level):

| Index level | Tick size (Rs) |
| --- | --- |
| 0 – 15,000 | 0.05 |
| 15,000 – 30,000 | 0.10 |
| Above 30,000 | 0.20 |

**Options** on stocks and indices are `0.05` as the general rule, but this is
**not universal** — options on low-priced underlyings carry `0.01`. Verified
in the current master: GMRAIRPORT, JIOFIN, IRFC, NMDC, MAHABANK, PNB, ONGC and
SAIL options all sit at `0.01`, against ~31,500 option rows at `0.05`. Assert
against the exchange contract file per underlying, not against a flat `0.05`.

**MCX is not slab-based.** Each commodity carries an exchange-defined tick.
Assert per contract against the MCX contract specification, never by slab.

#### The instrument matrix to check

Resolve these at run time and assert the tick against the slab that the
instrument's own live price lands in. Expected values below are from the
current master and serve as the regression baseline:

| ID | Class | Instrument | Exchange | Expected tick |
| --- | --- | --- | --- | --- |
| TS-01 | Cheap stock (below 250) | `IDEA`, `YESBANK`, `NHPC` | NSE | `0.01` |
| TS-02 | ETF | `GOLDBEES` | NSE | `0.01` |
| TS-03 | ETF | `NIFTYBEES` | NSE | `0.01` |
| TS-04 | Blue chip (1,000 – 5,000) | `RELIANCE`, `INFY` | NSE | `0.10` |
| TS-05 | High-priced (10,000 – 20,000) | `BAJAJ-AUTO` | NSE | `1.00` |
| TS-06 | Very high-priced (above 20,000) | `MRF` | NSE | `5.00` |
| TS-07 | **NFO stock future** | `INFY...FUT` | NFO | `0.10` — matches cash INFY |
| TS-08 | **NFO stock future**, cheap underlying | `IDEA...FUT` | NFO | `0.01` — matches cash IDEA |
| TS-09 | **NFO stock future**, high-priced underlying | `BAJAJ-AUTO...FUT` | NFO | `1.00` — matches cash BAJAJ-AUTO |
| TS-10 | Index future, 15,000 – 30,000 | `NIFTY...FUT` | NFO | `0.10` |
| TS-11 | Index future, above 30,000 | `BANKNIFTY...FUT` | NFO | `0.20` |
| TS-12 | Stock / index option | `OPT_ATM_CE` on a mid-priced underlying | NFO | `0.05` |
| TS-13 | Option on a cheap underlying | e.g. `PNB`, `ONGC`, `SAIL` option | NFO | `0.01` — not `0.05` |
| TS-14 | BSE index future | `BANKEX...FUT` | BFO | Per BSE slab; observed `0.05` |
| TS-15 | **MCX major** | `CRUDEOIL...FUT` | MCX | `1.00` |
| TS-16 | **MCX major** | `GOLD...FUT` | MCX | `1.00` |
| TS-17 | **MCX major** | `SILVER...FUT` | MCX | `1.00` |
| TS-18 | MCX, sub-rupee tick | `NATURALGAS...FUT` | MCX | `0.10` |
| TS-19 | MCX, fine tick | `COPPER...FUT` | MCX | `0.05` |
| TS-20 | Tick-boundary order rejection | Place a LIMIT priced off-tick on any row above | Snapped or cleanly rejected, never silently accepted (OD-20) |

A broker returning a single tick value across a whole exchange fails this
section even though every individual row is non-zero — that is precisely the
bug the matrix exists to catch.

---

## 3. Symbol services

| ID | Endpoint | Check | Pass criteria |
| --- | --- | --- | --- |
| SYM-01 | `/symbol` | Equity lookup | All documented fields present; `brsymbol` is the broker tradingsymbol; `tick_size` and `lotsize` sane |
| SYM-02 | `/symbol` | Futures lookup | `instrumenttype=FUT`, `expiry` in `DD-MMM-YY`, `freeze_qty` present for F&O |
| SYM-03 | `/symbol` | Options lookup incl. `OPT_DECIMAL_STRIKE` | `strike` float preserved exactly |
| SYM-04 | `/symbol` | Index lookup on `NSE_INDEX` / `BSE_INDEX` | Resolves; `exchange` echoed as the index exchange |
| SYM-05 | `/symbol` | `EQ_SPECIAL` | Hyphen/ampersand/digit symbols resolve without mangling |
| SYM-06 | `/symbol` | Unknown symbol | Clean 404/400 with a message; never 500 |
| SYM-07 | `/search` | Plain symbol query | Returns matches; every row carries the full documented field set |
| SYM-08 | `/search` | `"NIFTY 26000 DEC CE"` compound query | Correct strike + month + option type filtering |
| SYM-09 | `/search` | Case-insensitivity | Lower-case query returns the same rows |
| SYM-10 | `/search` | Per-exchange | Run once per exchange in `supported_exchanges`; non-empty for each |
| SYM-11 | `/expiry` | `instrumenttype=futures` | Ascending order, `DD-MMM-YY` format, first expiry >= today |
| SYM-12 | `/expiry` | `instrumenttype=options` | Ascending, `DD-MMM-YY`, weeklies present for index options where the exchange lists them |
| SYM-13 | `/expiry` | Every derivatives exchange | NFO, BFO, CDS, BCD, MCX, NCO as claimed. **FUT and OPT expiry formats must be identical in shape** |
| SYM-14 | `/expiry` | Non-derivative exchange | Clean error, not an empty success |

---

## 4. Market data — quotes, multiquotes, depth

### 4.1 Quotes

| ID | Check | Pass criteria |
| --- | --- | --- |
| QT-01 | Quote for EQ on every equity exchange claimed | `open`/`high`/`low`/`ltp`/`bid`/`ask`/`prev_close`/`volume` all present |
| QT-02 | Quote for FUT on every derivatives exchange claimed | As above; `oi` populated where the endpoint returns it |
| QT-03 | Quote for CE and PE on every derivatives exchange claimed | As above |
| QT-04 | **`prev_close` is non-zero and plausible** | Not 0, not equal to `ltp` by accident of a bad offset, within a sane band of the day's range |
| QT-05 | Index quotes — `NSE_INDEX` and `BSE_INDEX` | Succeed. Index quote vocabulary is the single most common broker-integration bug; a 400 here cascades into every options tool |
| QT-06 | Index quotes — `MCX_INDEX` / `GLOBAL_INDEX` | Only if claimed in `supported_exchanges`; otherwise must fail *fast and cleanly*, not hang |
| QT-07 | Index quote field sanity | `volume` may legitimately be 0 for an index; `ltp`, `open`, `high`, `low`, `prev_close` must not be |
| QT-08 | OHLC internal consistency | `low <= open <= high`, `low <= ltp <= high` |
| QT-09 | Price de-scaling | Quoted `ltp` matches the depth `ltp` and the last history candle close to within a tick — catches paise-vs-rupee (x100) errors |
| QT-10 | Unsupported exchange | Fails fast with a clear message |
| QT-11 | Unknown symbol | Clean 404/400 |

### 4.2 MultiQuotes

| ID | Check | Pass criteria |
| --- | --- | --- |
| MQ-01 | 3 symbols, one exchange | All three return `data` |
| MQ-02 | **50 symbols** | All 50 return data; elapsed time recorded |
| MQ-03 | **500 symbols** | All 500 return data, or the response degrades predictably at the broker's documented cap with a clear message. Record the observed cap |
| MQ-04 | Cap discovery | If the broker publishes no cap, binary-search (1/10/50/100/101/150/...) and record the boundary. Note whether exceeding it fails cleanly or returns an opaque 500 |
| MQ-05 | **Mixed valid + invalid symbol** | Valid symbols return data; the invalid one returns an `error` field **in its own result row**. The whole request must not fail |
| MQ-06 | **Mixed valid + invalid exchange** | Not the same as MQ-05. `exchange` is schema-validated with `validate.OneOf(VALID_EXCHANGES)`, so a bad value is rejected before the service runs and the whole request returns a clean 400 naming the offending entry. A *symbol* is not enum-validated, which is why MQ-05 degrades per row and this does not. Assert the 400 is clean and named - never a 500, never a silent partial |
| MQ-07 | Mixed exchanges including an index | NSE + NFO + `NSE_INDEX` in one request all return data |
| MQ-08 | Field parity with `/quotes` | Same field names and types as the single-quote endpoint, plus `oi` |
| MQ-09 | Duplicate symbols in request | Handled without error |
| MQ-10 | Empty `symbols` array | Clean 400 |

### 4.3 Depth

| ID | Check | Pass criteria |
| --- | --- | --- |
| DP-01 | Depth for EQ, FUT, CE/PE on every claimed exchange | 5 bid and 5 ask levels returned |
| DP-02 | Level ordering | Bids strictly descending, asks strictly ascending |
| DP-03 | Spread sanity | Best bid < best ask; both within the day's range |
| DP-04 | No zero-price levels | A `price: 0` level with non-zero quantity indicates a parsing/offset bug |
| DP-05 | `totalbuyqty` / `totalsellqty` | Present and non-zero for a liquid instrument |
| DP-06 | `oi` for F&O | Present and non-zero |
| DP-07 | `ltq` | Present |
| DP-08 | Depth for indices | Either a clean supported response or a clean unsupported error — never a partial/garbage book |

---

## 5. Market data — history

Timestamps are the highest-risk area. Assert the **IST wall-clock meaning**,
not just the presence of a value.

| ID | Check | Pass criteria |
| --- | --- | --- |
| HS-01 | `/intervals` | Returns the six documented buckets; the intervals it claims are the exact set used by the rest of this section |
| HS-02 | **1m, last 2 sessions, including today** | Data for the previous trading day **and** the current day is returned. A broker that silently drops the current day fails here |
| HS-03 | **Daily, last 2 sessions, including today** | Today's daily candle is present during market hours |
| HS-04 | **10 calendar days**, 1m and D | Continuous; no unexplained gaps beyond holidays and weekends |
| HS-05 | **100 calendar days**, 1m and D | Chunking across the broker's per-request window works; no duplicate or dropped candles at chunk boundaries |
| HS-06 | **2 years, daily, EQ** | Returns; candle count within a few percent of the expected trading-day count |
| HS-07 | **Timestamp is IST** | First intraday candle of a session is `09:15` IST for NSE/BSE equity and F&O, and the correct session open for MCX/CDS. Daily candles land on the session date, not the day before or after |
| HS-08 | Timestamp monotonicity | Strictly increasing, no duplicates |
| HS-09 | Intraday vs daily offset | Daily/weekly/monthly candles commonly need a `+5:30` shift that intraday does not. Both must land correctly — a pass on one does not imply the other |
| HS-10 | OHLC consistency per candle | `low <= open,close <= high`; `volume >= 0` |
| HS-11 | **OI for F&O symbols** | Where the broker returns OI in history, it is present and non-zero for FUT and for a liquid option. If the broker does not supply it, record as `N/A`, not `FAIL` |
| HS-12 | History for indices | `NSE_INDEX` and `BSE_INDEX`, both 1m and D. Index history commonly uses a different broker exchange code than index quotes |
| HS-13 | History per exchange | One EQ or FUT symbol per exchange in `supported_exchanges` |
| HS-14 | History for `OPT_ATM_CE` | Returns candles for a near-expiry option |
| HS-15 | **History for `EQ_SPECIAL`** | Both 1m and D return candles for a symbol carrying a hyphen, ampersand or digits (`M&M`, `BAJAJ-AUTO`, a `-BE` series). The symbol must survive URL encoding and the broker symbol lookup intact — a special character that breaks quotes usually breaks history too, but the reverse is not true: history often takes a different code path (`brsymbol` vs `token`) and can fail alone |
| HS-16 | Last candle vs live quote | Latest 1m close is within a plausible band of the live `ltp` |
| HS-17 | Unsupported interval | Clean 400 naming the supported set |
| HS-18 | Inverted date range | Clean 400 |
| HS-19 | Future-dated range | Clean empty success or clean 400 — never a 500 |

---

## 6. Options services

| ID | Endpoint | Check | Pass criteria |
| --- | --- | --- | --- |
| OS-01 | `/optionsymbol` | `offset=ATM` | Resolved strike is the listed strike nearest `underlying_ltp`; `lotsize`, `tick_size`, `freeze_qty` returned |
| OS-02 | `/optionsymbol` | ITM1, ITM3, ITM10 for CE and PE | CE ITM strikes go **down**, PE ITM strikes go **up**, in true listed strike steps |
| OS-03 | `/optionsymbol` | OTM1, OTM4, OTM10 for CE and PE | CE OTM strikes go **up**, PE OTM strikes go **down** |
| OS-04 | `/optionsymbol` | Resolved symbol exists | Every resolved symbol resolves via `/symbol` — no synthesised strike that is not listed |
| OS-05 | `/optionsymbol` | `NSE_INDEX` and `BSE_INDEX` underlyings | Both resolve to NFO / BFO respectively |
| OS-06 | `/optionsymbol` | Out-of-range offset (`OTM50` on a thin chain) | Clean error, not a fabricated symbol |
| OS-07 | `/optionchain` | Near expiry, `strike_count` around ATM | Symmetric CE/PE rows; every leg carries quote data |
| OS-08 | `/optionchain` | `with_greeks=true` | `implied_volatility` and `delta`/`gamma`/`theta`/`vega` on every leg; `expiry_ts`, `server_ts`, `forward_price` present |
| OS-09 | `/optionchain` | Exercises the batch quote path | Confirms the `get_multiquotes` cap handling under a realistic 180+ symbol load |
| OS-10 | `/optiongreeks` | ATM | IV in a plausible band; `delta` near +/-0.5 |
| OS-11 | `/optiongreeks` | OTM | `delta` magnitude < ATM; `gamma` > 0; `theta` < 0 for a long option |
| OS-12 | `/optiongreeks` | ITM | `delta` magnitude > ATM |
| OS-13 | `/optiongreeks` | **Deep ITM** | Still returns; `delta` magnitude approaching 1; IV solver does not return `NaN`, 0 or a wild value — the deep-ITM leg is where IV solvers fail |
| OS-14 | `/optiongreeks` | CE and PE both | Sign conventions correct for both |
| OS-15 | `/multioptiongreeks` | Mixed ATM/ITM/OTM batch | Per-symbol results; the documented 50-symbol cap enforced with a clean error beyond it |
| OS-16 | `/multioptiongreeks` | Invalid symbol in batch | Valid legs still return |
| OS-17 | `/syntheticfuture` | Near expiry | Returns a forward price derived from ATM CE/PE parity; within a plausible band of the listed future's LTP |
| OS-18 | `/syntheticfuture` | Both NFO and BFO underlyings | Both resolve |

---

## 7. Order placement

Run the full matrix in **sandbox** first (safe, exercises every combination),
then the safe subset in **live**.

### 7.1 `/placeorder` matrix

Dimensions to cross: `action` x `pricetype` x `product` x `exchange`.

| ID | Check | Pass criteria |
| --- | --- | --- |
| OD-01 | BUY and SELL, both, on every combination below | `orderid` returned; order appears in orderbook |
| OD-02 | `pricetype=MARKET` | Order **actually fills** — it must not rest. Verify via orderbook `order_status=complete` |
| OD-03 | `pricetype=LIMIT` far from LTP | Order **rests** as `open`; not rejected |
| OD-04 | `pricetype=SL` | Rests as `trigger pending`; does not fire on placement |
| OD-05 | `pricetype=SL-M` | Rests as `trigger pending`; does **not** fire on placement. Where the broker lacks native SL-M and OpenAlgo emulates it, verify the emulated limit is on the correct side of the trigger, tick-snapped, and at least one tick past |
| OD-06 | Emulation on a **cheap option** (`OPT_CHEAP` = `OTM40`) as well as equity | MPP percentage slabs differ sharply by price; a MARKET/SL-M emulation that works on a Rs 1,500 equity can fail on a Rs 2 option |
| OD-07 | `product=MIS` | Accepted on every exchange that supports it |
| OD-08 | `product=CNC` | Accepted on NSE/BSE |
| OD-09 | `product=NRML` | Accepted on NFO/BFO/CDS/BCD/MCX/NCO as claimed |
| OD-10 | Product/exchange mismatch (e.g. CNC on NFO) | Clean 400 |
| OD-11 | Every exchange in `supported_exchanges` | At least one successful order per exchange. **This list is a promise** — NSE working proves nothing about MCX or BFO |
| OD-12 | `EQ_SPECIAL` symbol | Order accepted with the special character intact |
| OD-13 | `OPT_DECIMAL_STRIKE` | Order accepted; decimal strike round-trips through the orderbook |
| OD-14 | `disclosed_quantity` | Accepted where the exchange allows it |
| OD-15 | Quantity below lot size on F&O | Clean 400 naming the lot size |
| OD-16 | Fractional quantity on non-crypto | Clean 400 |
| OD-17 | Negative / zero quantity | Clean 400 |
| OD-18 | LIMIT with `price=0` | Clean 400 |
| OD-19 | SL without `trigger_price` | Clean 400 |
| OD-20 | Price not on a tick boundary | Either snapped or cleanly rejected — never silently accepted and rejected by the exchange later |

### 7.2 `/placesmartorder`

Drive the documented position-matching table. Each row is a case; assert the
**net effect on the position book**, not just the response.

| ID | Current position | `action` / `quantity` / `position_size` | Expected |
| --- | --- | --- | --- |
| SO-01 | 0 | BUY 1 / 0 | Buys 1 |
| SO-02 | -1 | BUY 1 / 1 | Buys 2 |
| SO-03 | 1 | BUY 1 / 1 | **No order placed**; response says no action needed |
| SO-04 | 1 | BUY 1 / 2 | Buys 1 |
| SO-05 | 0 | SELL 1 / 0 | Sells 1 |
| SO-06 | +1 | SELL 1 / -1 | Sells 2 |
| SO-07 | -1 | SELL 1 / -1 | **No order placed** |
| SO-08 | -1 | SELL 1 / -2 | Sells 1 |
| SO-09 | any | Position already at target | No duplicate order on a repeated call |
| SO-10 | any | Symbol with no position, `position_size=0` | Places the raw quantity |

Quantities are 1 so the suite can run live on `EQ_CHEAP` at minimum risk, per
the safety rails in §1.4. The arithmetic is what is under test, not the size —
the same eight rows hold at any scale. On a derivatives exchange, substitute
one lot for `1` throughout, since a sub-lot quantity is rejected before the
position-matching logic is ever reached (OD-15).

### 7.3 `/splitorder`

| ID | Check | Pass criteria |
| --- | --- | --- |
| SP-01 | **Split ON**: quantity 105, splitsize 20 | 6 child orders: 20/20/20/20/20/5. `split_size`, `total_quantity` echoed; every child has an `orderid` |
| SP-02 | **Split OFF**: splitsize >= quantity | Exactly one order placed |
| SP-03 | `splitsize=0` or absent | Behaves as split-off; no divide-by-zero |
| SP-04 | Remainder is last | The short child is the final one |
| SP-05 | Child count cap | More than 100 children requested -> clean 400 |
| SP-06 | F&O split respects lot size | Every child is a whole multiple of the lot size |
| SP-07 | Sequential pacing | Children are spaced per `ORDER_RATE_LIMIT`; no 429 from the broker |
| SP-08 | Partial failure | If one child fails, the others still report; per-child `status` and `message` present |
| SP-09 | Fractional total on non-crypto | Clean 400 |

### 7.4 `/basketorder`

| ID | Check | Pass criteria |
| --- | --- | --- |
| BK-01 | Mixed BUY/SELL, mixed pricetypes, 3+ legs | Per-leg `orderid` and `status` |
| BK-02 | BUY-before-SELL ordering | BUY legs are submitted first (margin efficiency) — verify via orderbook timestamps |
| BK-03 | Mixed exchanges in one basket | All legs accepted |
| BK-04 | Partial success | One invalid leg fails with a `message`; valid legs still execute; top-level `status` is `success` |
| BK-05 | Batching | Live execution batches of 10 with a 1s gap; no rate-limit breach for a 25-leg basket |
| BK-06 | Empty `orders` array | Clean 400 |

### 7.5 `/optionsorder` — freeze quantity

Freeze quantities come from `data/qtyfreeze.csv`; read them at run time, never
hard-code.

**Use `offset=OTM40` for every live order-placing case in this section.** The
freeze-qty cases deliberately send large quantities — multiples of a 1,800-lot
NIFTY freeze limit — so the premium per lot decides the capital at risk. At 40
strikes out the premium is near zero, which makes a several-thousand-quantity
order cheap enough to place, fill and square off safely. An ATM leg at the same
quantity is not. Offsets other than `OTM40` are exercised in FZ-06 and §6,
where nothing is actually sent to the exchange at size.

| ID | Check | Pass criteria |
| --- | --- | --- |
| FZ-01 | **Quantity < freeze qty**, `splitsize=0` | Single order placed and accepted |
| FZ-02 | **Quantity == freeze qty**, `splitsize=0` | Boundary case — accepted or cleanly rejected per exchange rule; behaviour recorded |
| FZ-03 | **Quantity > freeze qty**, `splitsize=0` | Either a clean, informative rejection or an automatic split — **never** a silent partial or an opaque broker error |
| FZ-04 | **Quantity > freeze qty** with `splitsize` set to the freeze qty | Split into children each <= freeze qty; all accepted |
| FZ-05 | Offset resolution in the order response | `symbol`, `underlying`, `underlying_ltp`, `offset`, `option_type`, `exchange` all echoed and consistent |
| FZ-06 | ATM / ITMn / OTMn | Each resolves to the same symbol `/optionsymbol` would return for identical inputs |
| FZ-07 | `NSE_INDEX` -> NFO and `BSE_INDEX` -> BFO routing | Order lands on the correct derivatives exchange |
| FZ-08 | `expiry_date` in `DDMMMYY` | Accepted; a malformed expiry gives a clean 400 |

### 7.6 `/optionsmultiorder`

| ID | Check | Pass criteria |
| --- | --- | --- |
| MO-01 | Iron Condor, 4 legs, same expiry | 4 results, each with `leg`, `symbol`, `orderid`, `status` |
| MO-02 | Straddle and Strangle, 2 legs | Correct ATM/OTM resolution |
| MO-03 | Diagonal / calendar spread, per-leg `expiry_date` | Each leg resolves to its own expiry |
| MO-04 | **BUY legs execute before SELL legs** | Verified via orderbook timestamps — this is the margin-efficiency contract |
| MO-05 | **Freeze quantity per leg**, same rules as FZ-01..FZ-04, legs placed at `OTM40` | A leg above freeze qty behaves identically to the single-option case. Structure cases (MO-01..MO-03) keep their natural offsets, since those are shape assertions at 1 lot; only the at-size freeze-qty legs move out to `OTM40` |
| MO-06 | Leg failure isolation | A failing leg does not abort the remaining legs |
| MO-07 | Leg count bounds | 1 leg accepted; >20 legs -> clean 400 |
| MO-08 | `underlying_ltp` consistency | One LTP used for all legs' ATM calculation |

---

## 8. Order lifecycle — modify, cancel, status

| ID | Check | Pass criteria |
| --- | --- | --- |
| LC-01 | Place LIMIT far from LTP, then `/modifyorder` price | Orderbook reflects the new price; same `orderid` |
| LC-02 | Modify quantity | Reflected; F&O quantity stays a lot multiple |
| LC-03 | Modify pricetype LIMIT -> SL | `trigger_price` required and honoured; status moves to `trigger pending` |
| LC-04 | Modify an already-complete order | Clean error, not a 500 |
| LC-05 | Repeated modifies on one order | Broker per-order modification caps (some brokers cap at ~25) surface as a clean error |
| LC-06 | `/cancelorder` on an open order | Status becomes `cancelled` in orderbook |
| LC-07 | `/cancelorder` on a `trigger pending` order | Cancelled |
| LC-08 | `/cancelorder` on a completed order | Clean error |
| LC-09 | `/cancelorder` with an unknown orderid | Clean 400/404 |
| LC-10 | `/cancelallorder` | `canceled_orders[]` and `failed_cancellations[]` both present; each failure carries `orderid` + `reason`; the summary `message` counts match the arrays |
| LC-11 | `/cancelallorder` cancels trigger-pending too | SL/SL-M resting orders are included |
| LC-12 | `/cancelallorder` with nothing open | Clean success with empty arrays |
| LC-13 | `/orderstatus` for each terminal state | Returns the full documented field set; `order_status` matches what the orderbook shows for the same id |
| LC-14 | `/orderstatus` unknown orderid | Clean error |
| LC-15 | `/openposition` for a held symbol | Net quantity matches the position book row |
| LC-16 | `/openposition` for a flat symbol | Returns `0`, not an error |
| LC-17 | `/closeposition` | Every non-zero position squared off with a counter MARKET order at the **same product type**; position book shows 0 afterwards |
| LC-18 | `/closeposition` with no positions | `"No open positions to close"`, status `success` |
| LC-19 | `/closeposition` across mixed exchanges and products | MIS and NRML positions on different exchanges all closed |
| LC-20 | Full lifecycle trace | For one order: place -> open -> modify -> cancel, with every transition visible in the orderbook **and** on the `/websocket/order` stream (see §11) |

---

## 9. Books — orderbook, tradebook, positionbook, holdings, funds

### 9.1 OrderBook

| ID | Check | Pass criteria |
| --- | --- | --- |
| OB-01 | Contains every order placed in this run | Order id ledger fully reconciled |
| OB-02 | **All five `order_status` values observed**: `open`, `complete`, `cancelled`, `rejected`, `trigger pending` | Each state deliberately produced (a rejection via a deliberate circuit/price breach or invalid product) and each appears with the exact **lowercase** OpenAlgo vocabulary — no broker-native words leaking through |
| OB-03 | **Timestamp format is IST** | Matches the documented shape (e.g. `08-Apr-2025 13:58:03`), is in IST, and is within the current session. A UTC timestamp is a FAIL even though the string parses |
| OB-04 | All order types present in the book | MARKET, LIMIT, SL, SL-M each appear with the correct `pricetype` |
| OB-05 | All exchanges represented | Every exchange in `supported_exchanges` **except CDS** (excluded by instruction) has at least one row |
| OB-06 | Symbol round-trip | The `symbol` in the book is the OpenAlgo symbol that was sent, not the broker tradingsymbol |
| OB-07 | `price` and `trigger_price` | Numbers, 2 decimals, matching what was sent |
| OB-08 | `statistics` block | `total_buy_orders`, `total_sell_orders`, `total_completed_orders`, `total_open_orders`, `total_rejected_orders` all present, and each **reconciles against a count of the `orders[]` array** |
| OB-09 | `action` and `product` vocabulary | `BUY`/`SELL`; `MIS`/`CNC`/`NRML` |
| OB-10 | Empty book | Clean success with empty arrays and zeroed statistics |

### 9.2 TradeBook

| ID | Check | Pass criteria |
| --- | --- | --- |
| TB-01 | Executed orders appear | Every `complete` order from this run has at least one trade |
| TB-02 | `average_price` is the **executed** price | Non-zero; within the day's range; consistent with the fill |
| TB-03 | `quantity` non-zero | A filled trade reporting quantity 0 is a mapping bug |
| TB-04 | `trade_value` | Equals `quantity x average_price` to 2 decimals |
| TB-05 | Timestamp IST | Documented shape, within the session |
| TB-06 | Partial fills | A partially filled order produces multiple trade rows that sum to the filled quantity |
| TB-07 | `orderid` linkage | Every trade's `orderid` exists in the orderbook |

### 9.3 PositionBook

| ID | Check | Pass criteria |
| --- | --- | --- |
| PB-01 | Every position from this run appears | Reconciled against the trade book |
| PB-02 | **`average_price` is the entry price** | Non-zero for an open position; matches the executed price from the trade book to within rounding |
| PB-03 | `average_price_basis` | Present **only** when the average is not an entry price (e.g. `carry_forward_valuation`). Its presence on a same-day position is a FAIL; its absence on a broker that cannot supply entry price is also a FAIL |
| PB-04 | `ltp` | Non-zero, matches `/quotes` for the same symbol to within a tick |
| PB-05 | `pnl` arithmetic | Equals `(ltp - average_price) x quantity` for long, reversed for short, to 2 decimals |
| PB-06 | Sign convention | Positive quantity = long, negative = short, zero = closed-with-realized-P&L |
| PB-07 | Closed positions retained | Squared-off positions still appear with quantity 0 and today's realized P&L |
| PB-08 | 2-decimal rounding | `average_price`, `ltp`, `pnl` all rounded |
| PB-09 | Product and exchange | Correct per position; F&O positions align to lot size |

### 9.4 Holdings

| ID | Check | Pass criteria |
| --- | --- | --- |
| HD-01 | **No field is degenerate** | For every holding row, `quantity`, `pnl`, `pnlpercent` are populated and not all-zero across the whole book |
| HD-02 | **`average_price` present and non-zero** | The documented field table in `docs/api/account-services/holdings.md` lists only six fields, but the broker mappers emit `average_price` and `ltp` and the UI depends on them. Both must be present; a missing one is a FAIL against the mapper contract and a doc-gap finding |
| HD-03 | **`ltp` present and non-zero** | Matches `/quotes` for the same symbol |
| HD-04 | `pnlpercent` arithmetic | Equals `(ltp - average_price) / average_price x 100`, 2 decimals. A flat `-100%` across the book means `ltp` is missing and being treated as 0 |
| HD-05 | `product` | `CNC` |
| HD-06 | `statistics` block | `totalholdingvalue`, `totalinvvalue`, `totalprofitandloss`, `totalpnlpercentage` present and internally consistent with the rows |
| HD-07 | Empty holdings | Clean success with empty array and zeroed statistics — not an error |
| HD-08 | Symbol format | OpenAlgo symbols, not broker tradingsymbols |

### 9.5 Funds

| ID | Check | Pass criteria |
| --- | --- | --- |
| FN-01 | All five documented fields present | `availablecash`, `collateral`, `m2mrealized`, `m2munrealized`, `utiliseddebits` |
| FN-02 | Values are numeric strings | Parse as floats; no thousands separators, no currency symbols |
| FN-03 | Plausibility | **`availablecash` may legitimately be negative** — a debit balance, an MTM loss or margin utilised beyond the cash balance all produce one, and so do `m2mrealized` and `m2munrealized`. Assert the value parses and is present, never that it is `>= 0`. What is asserted is that the numbers **move consistently**: placing an order that blocks margin increases `utiliseddebits` and decreases `availablecash` by a comparable amount, and squaring off reverses it |
| FN-04 | 2-decimal formatting | Consistent |

---

## 10. GTT

Skip with reason (not FAIL) when the broker ships no `gtt_api` module — the
capability gate returns **501** and that 501 is itself the assertion.

| ID | Check | Pass criteria |
| --- | --- | --- |
| GT-01 | Capability gate | Broker without GTT returns 501 with a clear message on all four endpoints |
| GT-02 | Place SINGLE, trigger **below** LTP via `triggerprice_sl` | `trigger_id` returned |
| GT-03 | Place SINGLE, trigger **above** LTP via `triggerprice_tg` | `trigger_id` returned |
| GT-04 | Place SINGLE with `pricetype=MARKET`, `price=0` | Accepted; where the broker only accepts LIMIT children, the MPP conversion is transparent to the caller |
| GT-05 | Place OCO with all four trigger/limit fields | `trigger_id` returned |
| GT-06 | OCO with `triggerprice_sl >= triggerprice_tg` | Clean 400 with the documented message |
| GT-07 | SINGLE with neither trigger price set | Clean 400 |
| GT-08 | `product=MIS` | Clean 400 — GTT is CNC/NRML only |
| GT-09 | **GTT orderbook, `status` default (active)** | Only active triggers; `trigger_id`, `trigger_type`, `status`, `symbol`, `exchange`, `trigger_prices[]`, `last_price`, `legs[]`, `created_at` present |
| GT-10 | **GTT orderbook, `status=all`** | History included (`triggered`, `cancelled`, `expired`, `rejected`); active rows ordered first |
| GT-11 | `status` value other than `active`/`all` | Clean 400 |
| GT-12 | SINGLE shape | `trigger_prices` has 1 element; `legs` has 1 entry |
| GT-13 | OCO shape | `trigger_prices` has 2 elements ascending (sl then tg); `legs` has 2 matching entries |
| GT-14 | Modify SINGLE — move trigger and limit | Same `trigger_id`; orderbook reflects new values. **Modify is a full replacement** — verify omitted fields are not silently preserved |
| GT-15 | Modify OCO — both legs | Both legs updated atomically |
| GT-16 | Modify attempting SINGLE <-> OCO switch | Rejected |
| GT-17 | Modify attempting symbol/exchange/action change | Rejected |
| GT-18 | Modify a cancelled or triggered GTT | Rejected as immutable |
| GT-19 | Cancel an active GTT | Disappears from the active book; appears as `cancelled` under `status=all` |
| GT-20 | Cancel an already-cancelled GTT | Clean error |
| GT-21 | **Full GTT lifecycle** | place -> appears active -> modify -> cancel, each state confirmed via the GTT orderbook |
| GT-22 | Triggered GTT linkage | A fired GTT shows `status=triggered`, and its child order appears in the regular orderbook. In sandbox, `triggered_order_id` links the two |
| GT-23 | Broker-specific deviation recorded | Any documented divergence (e.g. Upstox OCO opening a position at market before arming legs) is asserted and reported as a **known quirk**, not a silent pass |

---

## 11. WebSocket — market data

| ID | Check | Pass criteria |
| --- | --- | --- |
| WS-01 | **Authenticate** with a valid API key | Success acknowledgement |
| WS-02 | Authenticate with an invalid key | Rejected or connection closed; no data leaks |
| WS-03 | Subscribe before authenticating | Rejected |
| WS-04 | **Ping** — application-level `{"action":"ping"}` | `{"type":"pong"}` returned; round-trip latency recorded |
| WS-05 | Control-frame keepalive | Connection survives beyond `WS_PING_INTERVAL` (default 20s) with no traffic |
| WS-06 | **Subscribe LTP, single symbol** | `market_data` frames with `mode: 1`, `ltp`, `timestamp` |
| WS-07 | **Subscribe LTP, multiple symbols in one message** | Frames for every symbol |
| WS-08 | **Subscribe Quote, single and multiple** | `mode: 2` frames with `ltp`, `open`, `high`, `low`, `close`, `volume`, `timestamp` |
| WS-09 | **Subscribe Depth, single and multiple**, `depth: 5` | `mode: 3` frames with 5 buy + 5 sell levels, `totalbuyqty`, `totalsellqty` |
| WS-10 | Depth levels 20 / 30 / 50 | Only for levels `get_supported_depth_levels()` claims. An over-declared level surfaces as a client-side `UNSUPPORTED_DEPTH_LEVEL`; an under-declared one means a working feature is unreachable. Both are findings |
| WS-11 | **Every exchange in `supported_exchanges`** | LTP, Quote and Depth each verified per exchange |
| WS-12 | **Indices — `NSE_INDEX` and `BSE_INDEX`** | Subscribe succeeds and frames arrive. Index streaming frequently uses a separate broker exchange code from index REST quotes |
| WS-13 | **Quote frame sanity — no zero values** | `bid`, `ask`, `open`, `high`, `low`, `close`, `volume` are non-zero for a liquid instrument. A `close` of `0.02` or similar is the classic binary-offset bug |
| WS-14 | **Quote frame timestamp** | Epoch milliseconds; converts to an IST wall-clock time inside the current session; monotonic across frames |
| WS-15 | Streamed LTP vs REST quote | Agree to within a tick |
| WS-16 | **Batch subscription** | A single subscribe with a large symbol list (50+, then the broker's cap) succeeds; record the observed cap and whether it degrades cleanly |
| WS-17 | Partial subscription result | A batch containing one invalid symbol returns `status: "partial"` with per-symbol `status`/`message`; valid symbols still stream |
| WS-18 | **Unsubscribe, single symbol** | Acknowledgement lists the symbol under `successful` with the canonical `mode` label; frames stop |
| WS-19 | **Unsubscribe, multiple symbols** | All listed; frames stop for all |
| WS-20 | **Unsubscribe all** | Every stream stops; registry cleared |
| WS-21 | Unsubscribe a symbol never subscribed | Listed under `failed` with a message; no crash |
| WS-22 | **Mode switching — activation** | Subscribe LTP, then Quote, then Depth on the **same symbol**; each mode's frames arrive with the correct `mode` value |
| WS-23 | **Mode switching — deactivation** | Unsubscribe one mode while another stays active; only the unsubscribed mode stops |
| WS-24 | Two modes concurrently on one symbol | Both stream independently |
| WS-25 | Reconnect after a forced drop | Client re-authenticates and re-subscribes; frames resume. Server does **not** auto-restore subscriptions — verify that is the observed behaviour |
| WS-26 | Token rollover | Adapter re-reads a fresh token on reconnect rather than reusing a stale one |
| WS-27 | Data-stall watchdog | A stalled feed is detected and the adapter reconnects rather than sitting silent |
| WS-28 | `broker` field on every frame | Names the broker under test |

---

## 12. WebSocket — order updates

Run **in parallel** with §7 and §8, so every order placed there is also
asserted on the stream.

| ID | Check | Pass criteria |
| --- | --- | --- |
| OU-01 | `subscribe_orders` | Acknowledgement with `status: success` |
| OU-02 | **Every order status observed on the stream** | `open`, `trigger pending`, `complete`, `cancelled`, `rejected` each pushed as an `order_update`, lowercase |
| OU-03 | Symbol format | OpenAlgo symbol, mapped from the broker's symbology |
| OU-04 | Constants | `action` BUY/SELL, `pricetype` MARKET/LIMIT/SL/SL-M, `product` CNC/NRML/MIS |
| OU-05 | Quantities | `filled_quantity` + `pending_quantity` reconcile with `quantity` at every transition |
| OU-06 | `average_price` on a fill | Non-zero; matches the trade book |
| OU-07 | **Rejection carries `rejection_reason`** | Non-empty and human-readable |
| OU-08 | Partial fill | Intermediate update with `filled_quantity` between 0 and `quantity` |
| OU-09 | Coverage of all order kinds | Plain, smart, split children, basket legs, options legs, and GTT-triggered child orders all appear |
| OU-10 | Non-API origin | An order placed from the broker's own app or website also appears (where the broker's feed covers it) |
| OU-11 | Polling fallback | For a broker with no push feed, `ORDER_POLL_INTERVAL` polling still emits the same events |
| OU-12 | Deduplication | With both a broker feed and a postback configured, no duplicate on the same `orderid` + `order_status` + `filled_quantity` |
| OU-13 | `mode` field | `live` in live mode, `analyze` in sandbox |
| OU-14 | Latency to first update | Time from `/placeorder` response to the first matching `order_update` recorded (see §13) |
| OU-15 | `unsubscribe_orders` | Acknowledged; updates stop |

---

## 13. Latency

Latency is measured for **every** call, not as a separate suite. Report
min / median / p95 / max per endpoint per mode.

| ID | Measurement | Notes |
| --- | --- | --- |
| LT-01 | `/placeorder` round trip, per `pricetype` | MARKET, LIMIT, SL, SL-M measured separately |
| LT-02 | `/placesmartorder` round trip | Includes the position-book fetch it performs internally |
| LT-03 | `/splitorder` total and per-child | The inter-child delay is deliberate pacing, not latency — report both |
| LT-04 | `/basketorder` total and per-leg | |
| LT-05 | `/optionsorder`, `/optionsmultiorder` | Includes symbol resolution cost |
| LT-06 | `/modifyorder`, `/cancelorder`, `/cancelallorder`, `/closeposition` | |
| LT-07 | GTT place / modify / cancel | |
| LT-08 | Book endpoints | orderbook, tradebook, positionbook, holdings, funds |
| LT-09 | Market data | quotes; multiquotes at 3 / 50 / 500 symbols; depth |
| LT-10 | History | Per interval and per range size (2d / 10d / 100d / 2y) |
| LT-11 | Options services | optionchain (the heaviest call), greeks, multigreeks |
| LT-12 | WebSocket | Time to first frame after subscribe; ping/pong RTT; order-update push delay |
| LT-13 | Outlier flagging | Any call exceeding a configurable threshold is flagged amber in the report even when functionally correct |

---

## 14. Sandbox parity

Sandbox does not validate the broker plugin. It validates that the **contract**
is identical, and it lets the script exercise lifecycles that are unsafe live.

| ID | Check | Pass criteria |
| --- | --- | --- |
| SB-01 | Every order endpoint answers in sandbox | `mode: "analyze"` present |
| SB-02 | Field-name parity | The response key set for each endpoint is identical between modes (allowing documented mode-only extras such as `mode`, `triggered_order_id`, `strategy`, `margin_blocked`) |
| SB-03 | Type parity | Same field types in both modes |
| SB-04 | Status vocabulary parity | Same lowercase `order_status` values |
| SB-05 | Sandbox order lifecycle | open -> complete and open -> cancelled both reachable |
| SB-06 | Sandbox GTT | Place / modify / cancel / trigger against live LTP; margin reserved at placement and released on fire or cancel |
| SB-07 | Sandbox order-update stream | Same `order_update` shape with `mode: "analyze"` |
| SB-08 | Sandbox P&L symbols | `/pnl/symbols` returns analyzer data |
| SB-09 | Mode isolation | No sandbox order reaches the broker; no live order appears in the sandbox book |
| SB-10 | Explicit non-claim | The report must state, in the summary sheet, that sandbox results do not evidence broker correctness |

---

## 15. Cross-cutting negative and robustness cases

| ID | Check | Pass criteria |
| --- | --- | --- |
| NG-01 | Missing `apikey` | 401 |
| NG-02 | Invalid `apikey` | 403 with `Invalid openalgo apikey` |
| NG-03 | Malformed JSON body | 400, not 500 |
| NG-04 | Unknown field in body | Ignored or cleanly rejected; never a 500 |
| NG-05 | Unsupported exchange for the broker | Clean, fast failure naming the exchange |
| NG-06 | Symbol/exchange mismatch (equity symbol on NFO) | Clean 400 |
| NG-07 | Every endpoint under an expired token | Clean 401/403 with a re-login hint; no silent empty success |
| NG-08 | Concurrent identical requests | No duplicate orders from a single logical request |
| NG-09 | `log/errors.jsonl` sweep | Any new error logged during the run is attached to the report, even for passing cases — five broken UI tools have traced back to one shared 400 before |
| NG-10 | No credential leakage anywhere | Response bodies and logs swept for the API key, auth token and feed token |

---

## 16. Report — `.xlsx` deliverable

### 16.1 Workbook structure

| Sheet | Contents |
| --- | --- |
| `Summary` | Broker, run timestamp (IST), mode(s), app version, pass/fail/skip/error counts by section, overall verdict, and the explicit sandbox non-claim (SB-10) |
| `Environment` | Broker id, `supported_exchanges`, resolved test symbol matrix (§1.3), master contract download time and row counts |
| `Results` | One row per test case: `ID`, `Section`, `Mode`, `Endpoint`, `Exchange`, `Symbol`, `Expected`, `Actual`, `Status`, `Latency_ms`, `HTTP`, `Message` |
| `Missing Symbols` | MC-08 output — every canonical symbol absent from the broker's master, with an annotation for renamed or delisted listings |
| `Latency` | Per-endpoint per-mode min / median / p95 / max, plus the outliers flagged by LT-13 |
| `Observed Limits` | Discovered caps: multiquote batch size, WebSocket batch size, supported depth levels, history chunk window, modify-count cap |
| `Quirks` | Broker-specific deviations found (GT-23 style), each with the evidence |
| `Errors Log` | New `log/errors.jsonl` entries captured during the run |

### 16.2 Status vocabulary and colour coding

| Status | Meaning | Fill |
| --- | --- | --- |
| `PASS` | Assertion met | Green |
| `FAIL` | Assertion not met — a defect | Red |
| `WARN` | Works but deviates: degraded value, missing optional field, latency outlier, undocumented behaviour | Amber |
| `SKIP` | Not applicable — capability not claimed, market closed for that segment, no holdings to assert against. **Must carry a reason** | Grey |
| `BLOCKED` | Could not run because a prerequisite failed | Dark grey |
| `ERROR` | Harness fault (429, network, timeout) — not a broker verdict | Blue |

Rules the report must follow:

- A `SKIP` with no reason string is itself reported as `FAIL` of the harness.
- `N/A` is not a status. A capability the broker genuinely lacks is `SKIP`
  with the reason; a capability it claims but does not deliver is `FAIL`.
- Section headers in `Results` are colour-banded so a reviewer can scan to the
  first red row.
- Conditional formatting applies to the `Status` column; `Latency_ms` gets its
  own gradient so slow-but-correct paths are visible.

---

## 17. Execution order

1. Preconditions (§1) — abort the run if PRE-01..PRE-04 fail.
2. Master contract (§2) — everything downstream depends on it.
3. Symbol services (§3) — resolves the test symbol matrix.
4. Market data (§4, §5) — read-only, safe, and the fastest way to find the
   deep bugs (index quote vocabulary, price scaling, timestamp offsets).
5. Options services (§6) — exercises the batch quote path under real load.
6. WebSocket market data (§11) — start the order-update subscription here and
   leave it open for the rest of the run.
7. Sandbox order suite (§7, §8, §10 under SANDBOX) — full matrix, zero risk.
8. Live order suite (§7, §8, §10 under LIVE) — safe subset, minimum size.
9. Books (§9) — asserted against the ledger the order suites built.
10. Margin (§18).
11. Destructive operations — `cancelallorder`, then `closeposition`.
12. Teardown: confirm flat, confirm no resting orders, unsubscribe, log out of
    the stream.
13. Negative cases (§15) and report generation (§16).

---

## 18. Margin

| ID | Check | Pass criteria |
| --- | --- | --- |
| MG-01 | **Single instrument** | `total_margin_required`, `span_margin`, `exposure_margin` present and non-zero for a real F&O position |
| MG-02 | **Multi instrument** — 2-leg hedged spread | Returns; and the basket figure is **less than the naive sum of the individual legs** (the broker's hedge benefit must be captured, which means routing to the basket calculator rather than summing) |
| MG-03 | 4-leg iron condor | Returns; hedge benefit visible |
| MG-04 | Equity single order | Returns a plausible figure |
| MG-05 | `margin_benefit` field | Present where the broker exposes it |
| MG-06 | Against documented example numbers | Where the broker publishes a worked example, the figure is in the same ballpark |
| MG-07 | 50-position cap | Exactly 50 accepted; 51 gives a clean 400 |
| MG-08 | Invalid symbol | Clean 400, not a 500 |
| MG-09 | Non-JSON broker reply | Surfaces as 502, not an unhandled exception |
| MG-10 | Broker error payload sent with HTTP 200 | Normalised into a 400 rather than being read as success |
| MG-11 | Broker without margin support | Clean, documented failure |

---

## 19. What a passing run does not prove

Carry these into the report's summary sheet verbatim:

- **Sandbox passing proves nothing about the broker.** Analyzer mode routes to
  `sandbox_service` and never calls broker code.
- **NSE passing proves nothing about the other exchanges.** Every exchange in
  `plugin.json` is a promise and must be exercised independently.
- **A single session proves nothing about expiry-day or rollover behaviour.**
  Expiry-day symbol changes, lot-size revisions and contract rollovers need a
  run on those dates.
- **Read-only checks do not evidence order correctness.** Only a placed,
  modified, cancelled and squared-off order does.

