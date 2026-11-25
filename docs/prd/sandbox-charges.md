# Sandbox Charges

Brokerage and statutory charges on sandbox trades: what is charged, where it
lands, how a trader configures it, and what is deliberately left out.

## Overview

Every sandbox fill pays two things:

- **Brokerage**, under the trader's own plan. One plan per segment, saved on
  `/sandbox/commissions`.
- **Statutory charges**: STT or CTT, exchange transaction charges, SEBI
  turnover fees, stamp duty and GST. These are the published rates, the same
  at every broker, and are not configurable.

The charge is taken from the available balance in the commit that fills the
order, and recorded on the trade line by line. P&L stays gross, as a broker's
position book shows it, with the charges beside it.

## Surfaces

| Surface | Path | Purpose |
|---------|------|---------|
| Brokerage plan | `/sandbox/commissions` | The charges switch, the plan for each segment, the statutory schedule (read-only), and what is not charged |
| Transaction costs | `/sandbox/commissions?tab=report` | Charges paid in a date range: totals, by segment, by day and by trade, with a CSV export |
| Brokerage calculator | `/sandbox/calculator` | A card per segment: buy, sell, quantity and exchange in, the full breakdown, points to breakeven and net P&L out. Each card opens on the segment's main exchange |
| Charges API | `POST /api/v1/charges` | The charges for one order, before it is placed. See [the API reference](../api/account-services/charges.md) |
| P&L page | `/sandbox/mypnl` | Today's and lifetime charges, net figures, and a charges column per day and per trade |

## One market per broker

A trader is on one market or the other, and is shown that one alone:

| Logged in to | Brokerage plan page | Calculator | Report columns |
|--------------|---------------------|------------|----------------|
| A broker on the Indian exchanges | The eight Indian segments and the statutory schedule | Brokerage Calculator, with tabs for Equities and F&O, Currency and Commodities | Brokerage, STT / CTT, exchange, SEBI, stamp duty, GST |
| A crypto venue | The two crypto segments, as a venue fee | Fee Calculator, the two crypto cards and no tabs | The fee |

The two are never on one page. They are priced differently (a schedule of
statutory charges on one side, a venue fee and nothing else on the other), and
a calculator that offered both would offer a trader a market the account cannot
trade.

The server decides, not the page: `blueprints/sandbox._charge_market` reads what
the logged-in broker's plugin says it is (`broker_type` in `plugin.json`), the
settings endpoint sends that market's segments alone with a `market` field, and
the estimate endpoint refuses a segment of the other market. Only a plugin that
says `crypto` is the crypto market; anything else, an unknown type included, is
the Indian one. The plan of the market that is not shown stays stored and
untouched, apart from a reset to defaults, which restores every segment.

`POST /api/v1/charges` is not split this way. It prices one order, and the
order's exchange decides its segment.

## The brokerage plan

Each segment has two numbers:

| Field | Meaning |
|-------|---------|
| Per executed order | A flat amount. `0` means not used |
| % of trade value | A percentage. `0` means not used |

| Both set | Only the amount | Only the percentage | Neither |
|----------|-----------------|---------------------|---------|
| The lower of the two | That amount per order | That share of the trade value | No brokerage |

Defaults:

| Segment | Applies to | Per order | % of trade value |
|---------|-----------|-----------|------------------|
| Equity Delivery | CNC on NSE, BSE | 20 | 2.5 |
| Equity Intraday | MIS on NSE, BSE | 20 | 0.1 |
| F&O Futures | Futures on NFO, BFO | 20 | 0.03 |
| F&O Options | Options on NFO, BFO | 20 | 0 |
| Currency Futures | Futures on CDS, BCD | 20 | 0.03 |
| Currency Options | Options on CDS, BCD | 20 | 0 |
| Commodity Futures | Futures on MCX, NCDEX, NCO | 20 | 0.03 |
| Commodity Options | Options on MCX, NCDEX, NCO | 20 | 0 |
| Crypto Futures and Spot | Non-options on CRYPTO | 0 | 0 |
| Crypto Options | Options on CRYPTO | 0 | 0 |

A plan is saved whole, in one commit, so a fill that lands during a save is
charged under the old plan or the new one and never a mixture. A change applies
from the next fill; trades already made keep what they paid.

Limits (guards against a slip of the keyboard, not limits a broker observes):
at most 1000 per order and 5 percent.

## The statutory schedule

Percent of trade value. On options the trade value is the premium.

| Segment | STT / CTT | Exchange transaction | SEBI | Stamp duty (buy) | GST |
|---------|-----------|----------------------|------|------------------|-----|
| Equity Delivery | 0.1 buy and sell | NSE 0.00307, BSE 0.00375 | 0.0001 | 0.015 | 18 |
| Equity Intraday | 0.025 sell | NSE 0.00307, BSE 0.00375 | 0.0001 | 0.003 | 18 |
| F&O Futures | 0.05 sell | NFO 0.00183, BFO 0 | 0.0001 | 0.002 | 18 |
| F&O Options | 0.15 sell | NFO 0.03553, BFO 0.0325 | 0.0001 | 0.003 | 18 |
| Currency Futures | none | CDS 0.0004, BCD 0.00045 | 0.0001 | 0.0001 | 18 |
| Currency Options | none | CDS 0.0331, BCD 0.001 | 0.0001 | 0.0001 | 18 |
| Commodity Futures | CTT 0.01 sell | MCX 0.0021, NCDEX 0.0021, NCO 0.0001 | 0.0001 | 0.002 | 18 |
| Commodity Options | CTT 0.05 sell | MCX 0.0418, NCDEX 0.0418, NCO 0.001 | 0.0001 | 0.003 | 18 |
| Crypto | none | none | none | none | none |

GST is charged on brokerage, exchange transaction charges and SEBI fees. The
NSE-family rates (NSE, NFO, CDS) include the Investor Protection Fund Trust
levy; the charges API reports that part on its own line.

Each segment lists its exchanges main exchange first (NSE, NFO, CDS, MCX), and
that order is sent to the page as a list (`exchanges`). The rates themselves
travel as a JSON object, whose keys the server sorts, so a page that read the
exchange codes off the rates got BSE and BFO first: every calculator card
opened on the exchange fewer traders use and showed a different exchange
transaction charge from the one a trader expected.

## Rounding

As a contract note prints it:

| Line | Rounded to |
|------|-----------|
| STT | The nearest rupee |
| Stamp duty | The nearest rupee |
| CTT (commodities) | The paisa |
| Brokerage, exchange transaction charges, SEBI fees, GST | The paisa |

- The exchange's own charge and its investor protection levy are two amounts,
  each rounded on its own, and the exchange line is their sum.
- GST is 18 percent of the brokerage, exchange and SEBI lines as printed.
- The total is the sum of the lines, so it never disagrees with them.
- **A fill** is charged as a contract note for that one trade.
- **The calculator** prices a buy and a sell together, as one note for the two:
  each line is worked on the combined value and rounded once. The two fills,
  charged one at a time, can come to a paisa more or less on a line.

## Checked against a published brokerage calculator

`test/sandbox/charges_reference.json` holds 117 round trips read from a
discount broker's public calculator on 23 November 2026: sixteen trades of odd
sizes in each equity and F&O segment, and smaller sets for currency and
commodities on each exchange. `test/sandbox/test_charges.py` prices every one
and compares every line.

| Result | Trades | Why |
|--------|--------|-----|
| Every line the same | 103 | |
| One line a paisa over | 8 | The exact figure is a half paisa (brokerage of 30.015, an exchange charge of 148.005). Exact arithmetic rounds it up; the page's floating point rounds it down |
| GST and total higher | 6 | Currency futures on NSE. The page shows the exchange charge with the investor protection levy in it, then leaves the levy out of its own GST and total, so its lines do not add up to its total. Here the levy is charged throughout |

The same trades under the first version of this arithmetic, which rounded every
line to the paisa on each fill, matched on 8 of the 117.

The default plan differs from that calculator's on purpose in one place: equity
delivery is charged 20 per executed order here, where that plan charges none.

The schedule lives in `sandbox/charges.py` with the date it was last checked
(`STATUTORY_SCHEDULE_AS_OF`). When a rate changes, change it there and add the
case to `test/sandbox/test_charges.py`: nothing is stored in a database, so no
migration is needed for a rate change, and trades already made keep what they
were charged.

## Where a charge lands

`ExecutionEngine._execute_order` is the only place a sandbox trade is written,
so it is the only place a charge is applied:

1. The order is claimed (the conditional UPDATE that makes a fill single).
2. The charge is worked out for the fill price.
3. The trade row is added with its seven charge columns.
4. `FundManager.stage_charges` takes the total from the available balance and
   adds it to `total_charges` and `today_charges`, as a compare-and-set.
5. One commit lands the claim, the trade and the debit together.

What follows from that:

- An order two threads reach is charged once: the loser fails its claim before
  it stages anything.
- A fill that fails at its commit takes its charge back.
- Used margin and the P&L columns are not touched, so margin reconciliation and
  the position book are unaffected.
- A balance that cannot cover the charge goes below zero. The order has filled
  and the charge is owed, as on a broker's ledger.
- A fault in the calculation fills the order uncharged rather than rejecting it.

`sandbox/charges.py` performs no I/O, like `services/risk/`. Consumers
translate and store; they do not decide. Adding a rule means changing that
module, not adding arithmetic beside it.

## Data

| Table | Columns added | Meaning |
|-------|---------------|---------|
| `sandbox_trades` | `brokerage`, `stt`, `exchange_charges`, `sebi_charges`, `stamp_duty`, `gst`, `total_charges` | What that fill paid |
| `sandbox_funds` | `total_charges`, `today_charges` | Running totals. `today_charges` resets with `today_realized_pnl` |
| `sandbox_daily_pnl` | `charges` | The day's charges beside the day's P&L |
| `sandbox_config` | `charges_enabled`, `brokerage_<segment>_flat`, `brokerage_<segment>_percent` | The switch and the plan |

Existing installs get the columns from `upgrade/migrate_sandbox_charges.py`
(run by `migrate_all.py`) and, for an install that restarts without running it,
from the startup hook in `database/sandbox_db.py`. Rows that already exist read
0.00, which is what they paid: charges apply from the first fill after the
upgrade and are never applied to earlier trades.

## What is not charged

| Not modelled | Effect |
|--------------|--------|
| Depository (DP) charges on a delivery sell | A live delivery sell costs a little more |
| STT on an option exercised at expiry | Expiry settlement closes a position without an order and carries no charges |
| Intraday netting of a same-day delivery buy and sell | Both sides pay delivery rates |
| Agricultural commodity rates and NCDEX slab rates | NCDEX trades use the MCX non-agricultural rates |
| BSE scrip groups other than the standard rate | The standard rate is used |
| A crypto venue's fee schedule | Every crypto value is zero until the trader enters a fee; nothing is added to it. One fee applies to every executed order, with no separate maker and taker rates |
| Rounding on the day's total | STT and stamp duty are rounded to the rupee on each fill. A contract note rounds them once on the day's total, so a day of many small fills can differ by a rupee or two |

## Key files

| File | Purpose |
|------|---------|
| `sandbox/charges.py` | The rate card and the arithmetic. No I/O |
| `sandbox/charge_manager.py` | Reads and saves the plan, prices a fill, builds the report |
| `sandbox/fund_manager.py` | `stage_charges`, the debit |
| `sandbox/execution_engine.py` | Applies the charge inside the fill |
| `services/charges_service.py`, `restx_api/charges.py` | The charges API |
| `blueprints/sandbox.py` | The page endpoints |
| `frontend/src/pages/SandboxCommissions.tsx`, `SandboxCalculator.tsx` | The pages |
| `test/sandbox/charges_reference.json` | The published figures the arithmetic is held to |
| `upgrade/migrate_sandbox_charges.py` | The migration |

## Related documentation

| Document | Description |
|----------|-------------|
| [Sandbox](./sandbox.md) | The sandbox as a whole |
| [Margin System](./sandbox-margin-system.md) | Margin and fund management |
| [Charges API](../api/account-services/charges.md) | The REST endpoint |
