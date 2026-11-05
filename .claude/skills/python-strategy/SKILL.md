---
name: python-strategy
description: Build, port, backtest or debug a Python trading strategy that OpenAlgo hosts at /python. Use when asked to write an algo, automate a strategy, port one from another platform or from the openalgo-execution-skills pack, add a stop loss, target, trailing stop or daily loss limit, or find out why a /python strategy did not trade, did not stop, or crashed. Writes one self-contained file to workspace/execution/<name>/, backtests it, validates it against the real host and SDK, and rehearses it exactly as /python runs it with every order held back.
---

# Python strategies for /python

A hosted strategy is **one file**. /python copies it alone into
`strategies/scripts/`, runs it with **OpenAlgo's own interpreter**, from
OpenAlgo's folder, with the API key and addresses in the environment, and stops
it with SIGTERM followed by a kill 5 seconds later. Everything here follows
from that.

## The one rule

**Validate and rehearse before you hand anything over.**

```bash
uv run python .claude/skills/python-strategy/validate.py  workspace/execution/<name>/<name>.py
uv run python .claude/skills/python-strategy/backtest.py  workspace/execution/<name>/<name>.py
uv run python .claude/skills/python-strategy/rehearse.py  workspace/execution/<name>/<name>.py
```

- `validate.py` is static. It checks imports against what a **server** install
  has (uv.lock's main dependencies, not this machine's extras), every client
  call against the **installed** SDK's signatures, literal exchange, product,
  price type and action values, the host contract (main block, SIGTERM, no
  `input()`, no `time.sleep`, a key or address typed in only as a WARN), and a kit
  strategy's settings. Exit 0 means no FAIL. Treat a WARN as a FAIL unless you
  know why it is fine.
- `backtest.py` imports the file and replays history through its own
  `signals()`, its kit's risk translation and OpenAlgo's risk engine. It flags
  a `signals()` that reads future bars (exit 3).
- `rehearse.py` launches the file the way /python does: same interpreter,
  folder, environment, resource limits (read from
  `blueprints/python_strategy.py`), and Stop with the same grace period. REST
  goes through a guard that forwards reads to the real OpenAlgo and **answers
  every order call itself**, so nothing reaches the broker or the Sandbox,
  whatever analyzer mode says. It reports the orders the strategy would have
  sent, tracebacks, and how long it took to stop.

## Workflow

1. **Ask only what changes the file**: symbol and exchange, intraday or
   positional, bar interval, the entry and exit idea, quantity (or lots), stop,
   target, trail, and the trading window. Default the rest from the template.
2. **Start from a template** in `templates/`. Copy it to
   `workspace/execution/<name>/<name>.py` (lower case, underscores). Never
   write to `strategies/scripts/` yourself: /python owns that folder and the
   file only runs once it is uploaded there.
3. **Edit above the kit block only**: the settings and `signals(df)` (or
   `run_live()` for time-driven strategies such as options). The block from
   `# openalgo-strategy-kit <v> BEGIN` to the end is the same in every strategy.
4. **Validate, backtest, rehearse.** Fix and repeat until all three are clean.
   Report the backtest honestly, charges included; a losing template is still
   a correct template.
5. **Hand over** the path and the upload values: at /python, Add Strategy,
   choose the file, set the exchange `validate.py` prints, then the schedule
   (for NSE intraday, start 09:15, stop 15:30, Monday to Friday). Analyzer
   mode decides Sandbox or Live; say which one OpenAlgo is in.

## The file

```python
import os

import pandas as pd
from openalgo import ta

# OpenAlgo connection: /python fills these in; elsewhere, type your own values.
API_KEY = os.getenv("OPENALGO_API_KEY", "")
HOST = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765")

STRATEGY_NAME = "EMA Crossover"
SYMBOL = "SBIN"
EXCHANGE = "NSE"  # where orders go; also the /python calendar
PRODUCT = "MIS"  # MIS intraday, CNC delivery, NRML F&O
INTERVAL = "5m"  # 1m 3m 5m 10m 15m 30m 1h D
QUANTITY = 10  # or LOTS = 1 for F&O, sized from the live lot size
SIDES = "both"  # long, short, both
STOP_LOSS_PCT = 0.8  # or STOP_LOSS_POINTS; TARGET_*, TRAIL_* likewise
MAX_LOSS_PER_DAY = 3000
ENTRY_START = "09:30"
ENTRY_END = "14:30"
SQUARE_OFF = "15:10"


def signals(df):  # closed bars, oldest first
    fast, slow = ta.ema(df["close"], 9), ta.ema(df["close"], 21)
    return pd.DataFrame(
        {"long_entry": ta.crossover(fast, slow), "long_exit": ta.crossunder(fast, slow)},
        index=df.index,
    )


# ==== openalgo-strategy-kit 1.0.0 BEGIN ... (the engine, do not edit)
```

`signals(df)` returns any of `long_entry`, `long_exit`, `short_entry`,
`short_exit` as one flag per bar. The kit acts on the **last closed bar** when
it closes, at market, through smart orders.

What the kit does, so the strategy does not have to:

- **Stops, targets, trailing stops and daily limits come from OpenAlgo's risk
  engine** (`services/risk`), the one behind the scalping terminal and the
  strategy module. Never write a second evaluator in a strategy; CLAUDE.md
  makes this an invariant.
- **The broker is the record.** At start, and every 30 seconds, it reads the
  broker position for the symbol and product, adopts one that appeared and
  forgets one closed elsewhere. No local state files.
- **Closed bars only**, decided from each bar's end time, because brokers
  differ on whether the forming bar is included. On start it waits for the
  next close rather than acting on an old signal.
- **Exits flatten safely** (`flatten()`): see the first trap below.
- Live prices over the WebSocket, quote requests as the fallback; logs in IST
  to stdout (the /python log); one thread decides, so a signal exit and a stop
  exit cannot both fire.
- It logs whether orders go to the Sandbox or to the broker, and warns when the
  /python exchange does not match the strategy's.

Hooks a strategy may define above the kit: `resolve_symbol(client, cfg)` to pick
the instrument at start (futures roll), `run_live()` to replace the bar engine
(options, scheduled entries), `NO_BACKTEST_REASON` to refuse a backtest. Kit
helpers available to them: `connect`, `check_connection`, `check_calendar`,
`pick_expiry`, `futures_symbol`, `instrument`, `Prices`, `smart_order`,
`flatten`, `broker_position`, `make_risk`, `step_risk`, `pause`, `STOP`, `log`.

## Traps

**A smart order for size 0 opens a position when the account is flat.**
`placesmartorder(action="SELL", quantity=10, position_size=0)` closes a long
of 10, but if a manual exit or the broker's square-off got there first it
**sells 10 short** (every broker plugin and the Sandbox follow this table). The
only safe close is `quantity=0, position_size=0`. `validate.py` fails the other
form. The openalgo-execution-skills pack teaches the unsafe one.

**/python has no settings form.** The upload form takes a name, the file, the
exchange and the schedule. Everything a trader changes lives at the top of the
file, in plain assignments: the connection (API_KEY, HOST, WEBSOCKET_URL), the
instrument, the timeframe, the risk and the indicator parameters. Keep it that
way in every strategy: one obvious place, no config files, no command-line
arguments. Do not tell a trader to enter parameters at /python.

**Leave the connection to /python when hosting.** The three connection settings
read the environment /python provides. A typed-in key works but travels with
every copy of the file; a typed-in HOST works on that server only and cannot be
rehearsed (the guard is reached through HOST).

**Only OpenAlgo's packages exist.** No vectorbt, TA-Lib, scikit-learn,
xgboost. `openalgo.ta` covers the indicators. A model trained elsewhere goes
into the file as numbers.

**Supertrend's direction is -1 in an uptrend** and +1 in a downtrend.
`ta.crossover` returns a numpy array, not a Series; the kit aligns it.

**Never sleep through a Stop.** /python kills the process 5 seconds after
SIGTERM. Wait with `pause(seconds)`; it returns True when a stop arrived.

**One strategy per symbol and product.** Positions are account-wide, so two
strategies (or a manual trade) in the same symbol and product see and manage
each other's quantity.

**An index cannot be traded.** `NSE_INDEX` / `BSE_INDEX` give prices; trade the
futures or options.

**Daily bars decide at `DECISION_TIME`** (15:20) on today's bar, built from a
quote if the broker has not published it, because an order after the close is
rejected.

**A signal on the last bar of a session** acts after the close live (and is
rejected), but at the next open in a backtest of a positional strategy.

**Write nothing beside the file.** `strategies/scripts/` is shared by every
strategy. Keep state at the broker.

## Files

| Path | |
|---|---|
| `kit.py` | the engine block every strategy carries |
| `kit_sync.py` | `--write <file>` puts the current kit into a file, `--check` finds stale or edited copies |
| `templates/` | starting points, each carrying the kit |
| `validate.py` | the static gate |
| `backtest.py` | history replay through the file's own code |
| `rehearse.py` | /python launch with orders held back |
| `_host.py` | the host's facts, read from its source |
| `workspace/execution/readme.md` | where strategies live and how they get to /python |
| `strategies/README.md`, `strategies/RESOURCE_LIMITS.md` | the host itself |
| `docs/prompt/openalgo python sdk.md`, `docs/api/` | the SDK and the REST API |
