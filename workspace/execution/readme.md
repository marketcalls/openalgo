# execution/

Python strategies built for the `/python` Strategy Host, by the
`python-strategy` skill (`.claude/skills/python-strategy/`). Each lives in a
folder of its own, with the file you upload and what the tools wrote about it:

```
workspace/execution/
  ema_crossover_sbin/
    ema_crossover_sbin.py   the strategy: upload this one file at /python
    backtest/trades.csv     every simulated trade, with its exit reason
    backtest/equity.csv     the equity curve, bar by bar
    rehearsal.log           the log of the last rehearsal
```

Nothing here runs by itself. A strategy trades only once it is uploaded at
`/python`, which copies it into `strategies/scripts/` (that folder is the
app's; never write to it directly). Keep the copy here as the source you edit,
backtest and re-upload.

## From idea to /python

Run from the repo root, with OpenAlgo running and an API key generated at
`/apikey` (the tools read it from the database, as `/python` does):

```bash
uv run python .claude/skills/python-strategy/validate.py  workspace/execution/<name>/<name>.py
uv run python .claude/skills/python-strategy/backtest.py  workspace/execution/<name>/<name>.py --days 60
uv run python .claude/skills/python-strategy/rehearse.py  workspace/execution/<name>/<name>.py
```

- **validate** reads the file and checks it against what `/python` actually
  runs: OpenAlgo's own packages, the installed SDK, the order constants, and
  how the host starts and stops a strategy. Nothing is sent.
- **backtest** replays history through the file's own signals and OpenAlgo's
  risk engine (the same stop loss, target and trailing stop as live), with
  charges and slippage, and warns if the signals look at future bars.
- **rehearse** runs the file exactly as `/python` would, for 90 seconds, then
  presses Stop. Every order it tries to place is held back and listed, so
  nothing reaches your broker or the Sandbox, even in live mode.

Then at `/python`: **Add Strategy**, choose the file, pick the exchange that
validate prints, and set the schedule (NSE intraday: 09:15 to 15:30,
Monday to Friday). Analyzer mode decides whether its orders go to the Sandbox
or to your broker; start in the Sandbox.

## Editing

Everything you change is at the top of the file, in plain `NAME = value`
lines:

- **Connection**: `API_KEY`, `HOST` (OpenAlgo's address and port) and
  `WEBSOCKET_URL`. Under `/python` they fill themselves in; to run the file
  elsewhere, type your own values over them.
- **Instrument and timeframe**: `SYMBOL`, `EXCHANGE`, `PRODUCT`, `INTERVAL`,
  `QUANTITY` (or `LOTS`).
- **Risk**: stop loss, target, trail, daily loss limit, trades per day.
- **Time**: entry window and square-off.
- **Strategy parameters**: indicator lengths and the like.

`/python` has no settings form, so change them in the file (or in the
`/python` editor) and re-upload. The `openalgo-strategy-kit` block at the
bottom is the engine every strategy shares; leave it alone, and take a newer
one with:

```bash
uv run python .claude/skills/python-strategy/kit_sync.py --write workspace/execution/<name>/<name>.py
```

## Keep in mind

- A backtest is not a forecast. Read the trade count and the charges before
  the return, and compare with buy and hold over the same bars.
- One strategy per symbol and product: positions are account-wide, so two
  strategies in the same symbol manage each other's quantity.
- Leave `API_KEY` as it is for `/python`, which provides the key. A key typed
  into the file works but travels with every copy of it, and stops working
  when you regenerate it at `/apikey`. Everything here is gitignored except
  this readme, but gitignore is not a secrecy boundary (see
  `workspace/readme.md`).
