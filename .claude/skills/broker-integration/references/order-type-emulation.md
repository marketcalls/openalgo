# Order-type emulation — when the broker lacks MARKET or SL-M

OpenAlgo's contract is fixed: every broker must accept `MARKET`, `LIMIT`, `SL`,
and `SL-M`. Many Indian brokers do not support all four natively, and several
that *claim* to support MARKET mangle it server-side. Bridging that gap is your
job in `mapping/transform_data.py`, and getting it wrong fails quietly — the
order is accepted, then rests unfilled or fills at a price nobody intended.

## Classify the broker first

| Broker behaviour | What to do |
| --- | --- |
| Supports all four natively and honours them | Straight enum map. Verify with a live order — "documented" is not "honoured". |
| **No MARKET** (LIMIT / SL-limit only) | Emulate MARKET as an aggressive LIMIT that crosses the spread |
| **No SL-M** (SL-limit only) | Emulate SL-M as a stop-limit whose limit sits beyond the trigger |
| **Converts MARKET to LIMIT server-side** (its own MPP) | Do not double-protect. Send native MARKET and let the broker convert — but check what it does to *stops* |

The third case is the trap. Under the SEBI Market Price Protection regime many
brokers silently rewrite a MARKET order into a LIMIT crossing the spread. That
is fine for plain MARKET, and destructive for SL-M: the broker substitutes a
limit price that lands on the *wrong side* of the trigger, so the order either
fills instantly instead of resting, or is rejected outright.

## Use the shared MPP module — do not invent percentages

`utils/mpp_slab.py` is the canonical implementation, used by **12 brokers**
(dhan, firstock, fivepaisa, flattrade, hdfcsky, iiflcapital, motilal, pocketful,
samco, shoonya, tradesmart, zebu). It encodes the exchange protection slabs:

```python
EQ_FUT_MPP_SLABS = [(100, 2.0), (500, 1.0), (inf, 0.5)]      # price < 100 -> 2%, 100-500 -> 1%, > 500 -> 0.5%
OPT_MPP_SLABS    = [(10, 5.0), (100, 3.0), (500, 2.0), (inf, 1.0)]   # options are wider
```

Public helpers:

- `get_instrument_type_from_symbol(symbol)` -> `EQ` / `FUT` / `CE` / `PE`
- `get_mpp_percentage(price, instrument_type)` -> the protection percentage
- `round_to_tick_size(price, tick_size)`

Options get materially wider buffers than equity — a 5-rupee option uses 5%,
not 0.5%. A single hardcoded percentage across all instruments will be far too
tight on cheap options (order never fills) and needlessly loose on expensive
equity.

`broker/indmoney/` is the outlier: it applies a flat 0.1% off LTP and does not
import `mpp_slab`. Do not copy it for a new integration — prefer the shared
slabs.

## Pattern A — emulating MARKET with a crossing LIMIT

Fetch a quote, push the price through the spread in the fill direction, switch
the order type to LIMIT. `broker/indmoney/mapping/transform_data.py`:

```python
if data["pricetype"] == "MARKET":
    ltp = float(quote_data.get("ltp", 0))
    if action == "BUY":
        price = round(ltp * 1.001, 2)   # above the market so it lifts the offer
    else:
        price = round(ltp * 0.999, 2)   # below the market so it hits the bid
    order_type = "LIMIT"
```

Three things that implementation gets right and are easy to miss:

- **Resolve the user from the Flask session, never a hardcoded username.**
  Falling back to a fixed user borrows another account's auth token.
- **Fall back to a native MARKET order** when there is no session user, no auth
  token, or `ltp <= 0`. A quote lookup that fails must not turn into a limit
  order at price 0.
- **Emulation costs a quote round-trip on every order.** On a broker with a
  1 req/sec quote limit that is a real latency and rate-limit cost. Prefer
  native MARKET wherever the broker honours it.

Use `get_mpp_percentage()` rather than a flat 0.1% unless you have a specific
reason — 0.1% will not cross the spread on an illiquid option.

## Pattern B — emulating SL-M with a protected stop-limit

Harder, and the source of real production bugs. `broker/dhan/` (GitHub issue
#1647) is the reference: a bare stop-loss-market either drops its trigger and
fills immediately, or is rejected with `DH-906 "Trigger Price should be greater
than Price"` because the broker's own MPP substitution lands the limit on the
wrong side of the trigger.

The fix is to map `SL-M` to the broker's **stop-limit** type and compute the
limit price yourself, offset beyond the trigger in the direction the order will
fill:

- **SELL stop** — limit strictly **below** the trigger
- **BUY stop** — limit strictly **above** the trigger

so the order stays marketable once it triggers. The rules that make it correct:

1. **Offset by the MPP percentage**, from the shared slab table, based on the
   trigger price and instrument type.
2. **Snap to the instrument tick** in the beyond-trigger direction — SELL
   floors, BUY ceils. Rounding the ordinary way can land the limit back on the
   trigger and re-trip the rejection.
3. **Force at least one full tick past the trigger.** Take the more aggressive
   of `trigger * (1 ± pct)` and `trigger ± tick_size`, so a tiny percentage on
   a low-priced instrument still clears the trigger.
4. **Read `tick_size` from `SymToken`** via `get_symbol_info(symbol, exchange)`
   — the master contract is the source of truth.
5. **Fail closed if the tick size is unresolvable.** Master-contract rows can
   coerce to `NaN`; validate `math.isfinite(tick) and tick > 0` and raise rather
   than emitting a 2-decimal guess the broker will reject.
6. **Guard against a non-positive limit** on cheap options — a SELL stop on a
   0.05 option can compute its way to zero.

```python
if action.upper() == "SELL":
    raw = min(trigger_price * (1 - pct), trigger_price - tick_size)
    limit = _snap_to_tick(raw, tick_size, "floor")
    if limit <= 0:
        raise ValueError(...)          # too low to protect
else:
    raw = max(trigger_price * (1 + pct), trigger_price + tick_size)
    limit = _snap_to_tick(raw, tick_size, "ceil")
```

`_snap_to_tick` is currently duplicated in `broker/dhan/` and
`broker/iiflcapital/` rather than shared — copy from either.

## How brokers actually spell SL-M

There is no convention. Real mappings in the tree:

| Broker | `SL-M` maps to |
| --- | --- |
| flattrade, arrow | `SL-MKT` |
| indmoney | `MARKET` (its stop handling is separate) |
| dhan | `STOP_LOSS` (stop-limit) + computed protective price |

Check the broker's enum before assuming a spelling, and check whether their
"stop-loss-market" actually rests.

## Failure modes and how they present

| Symptom | Likely cause |
| --- | --- |
| Order accepted, never fills | Limit not aggressive enough — flat percentage too tight, or wrong side of the spread |
| Stop fills the instant it is placed | Trigger dropped by the broker's MPP; needs Pattern B |
| Rejection naming trigger vs price | Limit computed on the wrong side of the trigger |
| Rejection about tick / price precision | Limit not snapped to `tick_size`, or a 2-decimal guess |
| Works on equity, fails on cheap options | Single percentage instead of the options slab; or limit rounded to zero |
| Works in analyzer, fails live | Analyzer never calls broker code — it proves nothing here |

## Checklist

- [ ] Broker classified: native / no MARKET / no SL-M / server-side MPP conversion
- [ ] `utils/mpp_slab.py` used rather than a hardcoded percentage
- [ ] Options slab applied to CE/PE (wider than EQ/FUT)
- [ ] MARKET emulation falls back to native MARKET when the quote is unavailable
- [ ] No hardcoded username in the quote-fetch path
- [ ] SL-M limit on the correct side of the trigger for both BUY and SELL
- [ ] Limit snapped to tick in the beyond-trigger direction (SELL floor, BUY ceil)
- [ ] At least one tick past the trigger enforced
- [ ] `tick_size` read from `SymToken`; fails closed when missing or NaN
- [ ] Positive-limit guard for low-priced options
- [ ] Live-tested: MARKET and SL-M, BUY and SELL, on equity **and** a cheap option
