# The shapes a strategy takes

Six worked files sit in `examples/`, and every one of them compiles: that is
checked, not claimed. This page is the map between what somebody asks for and
which file answers it, plus the decisions each shape forces.

| Ask | File | The decision it forces |
|---|---|---|
| long only | `long-only.oscript` | when to be out, since there is no short to flip into |
| short only | `short-only.oscript` | the same, mirrored, and the borrow is not modelled |
| stop and reverse | `stop-and-reverse.oscript` | the size of the turning order |
| a stop and a target | `stop-and-target.oscript` | distances, and the size that makes the stop cost what you meant |
| intraday, flat by the close | `intraday-session.oscript` | the window is not the session |
| a study, no orders | `study-bands.oscript` | whether this should be placing orders at all |

Read the file. Each carries its reasoning in comments, at the line the reasoning
is about, because that is where somebody changing it will be standing.

---

## Study or strategy: decide first, because it is not a flag

```
study("Bollinger bands", overlay = true)       // draws; has no position
strategy("Breakout", overlay = true, qty = 1)  // places orders
```

A `study()` file has no `pos`, no `buy`, no `sell`, no `order.*`. Reaching for
one is `OS7001`. This is not a restriction to work around: a file that draws and
a file that trades are read by different people at different moments, and the
one that trades is the one somebody has to be able to audit at speed.

If the answer is "it should draw, and also trade", it is a strategy. Every
strategy can plot.

---

## Long only

The whole design is in the exit, because there is no opposite side to flip into.
A long only strategy is out of the market for most of its life, and what takes
it out is the part that decides its returns.

```
if crossUp(fast, slow) and pos.isFlat
    buy(qty = lots, tag = "Long")

if crossDown(fast, slow) and pos.isLong
    close(tag = "Long")
```

`pos.isFlat` on the entry and `pos.isLong` on the exit rather than one test of
each: they are not the same condition, and writing `not pos.isFlat` on the exit
is how a short position (which this strategy should never hold) would be closed
by a long strategy's exit rule.

**The close carries the entry's tag**, so it closes the part of the position
that tag entered rather than whatever the leg happens to hold. In a file with
one entry those are the same thing; they stop being the same the moment a second
entry is added, and a tagged close keeps meaning what it meant. A tag no order
was placed with is `OS7016`, so this cannot rot silently: `close(tag = "Square
off")` does not compile.

## Short only

The mirror, and one thing that is not mirrored: **a short is not modelled as
borrowed stock.** There is no borrow cost, no locate, no recall. On Indian
equity intraday and on futures that is close enough to true; on a delivery short
it is not, and the report will be better than the trade was.

```
if crossDown(close, upper) and pos.isFlat
    sell(qty = lots, tag = "Short")

if crossUp(close, mid) and pos.isShort
    close(tag = "Short")
```

Note where the exit is: back at the mean, not at the lower band. A fade that
waits for the far side gives back most of what it made on the trades that get
there, and never exits on the ones that do not.

## Stop and reverse

Always in the market, turning round on each signal. The size is the whole
lesson, and getting it wrong produces a strategy that silently only trades one
side. `reference/pitfalls.md` opens with it.

```
buy(qty = lots + abs(pos.size), tag = "Up")    // one order, new size is lots
order.reverse()                                // two orders, new size is the old size
```

Guard the first bar. Without `not bar.isFirst`, a flip test reads as true on
bar 0 whichever way the trend started, and every backtest opens a position on
its first bar.

## A stop and a target

Attach them at the entry, not on the next bar. A strategy that enters and then
waits for a bar to send its stop is holding an unprotected position in between,
and the bar that gaps is the bar it happens on.

```
order.bracket("Break", loss = stopDistance, profit = targetDistance)
```

`profit` and `loss` are **distances from the entry**, in the instrument's own
price units. There is no `stop` or `target` argument on this call.

Then size from the risk, rather than fixing the quantity and letting the loss be
whatever the stop distance makes it:

```
units = max(1, floor(risk / stopDistance))
```

`order.qtyForRisk` would be the call for this and is planned, not implemented:
`OS2020`. The division is what it would do.

## Intraday, flat by the close

Two different clocks, and confusing them is the mistake:

```
canEnter = session.isIn("0925-1500")   // a window THIS SCRIPT states
if session.isLastBar                   // the INSTRUMENT's own session
    close()
```

`session.isLastBar` is true on the last bar of the **scheduled** session even
when trading stopped early, and it does not wait for a new bar to appear, which
would arrive after the close. It is a value, not a call.

Put the square off first and leave it unconditional. `close()` on a flat
position sends nothing, so no test is needed before it, and every test added
there is another way to end the day holding something.

---

## What a strategy cannot do in this version

Worth knowing before designing around it, because each of these reads like it
should be there:

- **Read its own equity, drawdown or win rate mid-run.** `pos.equity`,
  `pos.netProfit`, `pos.maxDrawdown`, `pos.winRate`, `pos.profitFactor` and
  `pos.tradeCount` are all planned. A strategy that sizes from its own recent
  performance cannot be written yet.
- **Declare more than one leg.** All of `leg.*` is planned and every `leg`
  argument meets `OS3023`. Multi-leg options structures belong in `/strategy`,
  which is built for them.
- **Read back an order's state.** `order.status`, `order.filled`,
  `order.avgFill`, `order.working` and `order.id` are planned. A script cannot
  ask whether its last order filled.
- **Trail a stop.** `leg.trail` is planned. A trailing stop is a rule evaluated
  every bar rather than a price an order rests at, and there is no spelling for
  it here yet.
- **Use the book-level rules.** All of `book.*` is planned, including
  `book.dailyLoss`, `book.squareOffAtExpiry` and `book.exitAt`.

The full marked list is in [`library.md`](./library.md), and it is generated
from the compiler, so it is right for the version actually installed.

---

## Before it runs anywhere near money

A compile is not a backtest and a backtest is not a live run.

1. `validate.mjs` says the compiler accepted it. That is all it says. Nothing
   here has run a single bar.
2. Backtest it in `/trading`. Read the trade list, not the equity curve: the
   curve hides a strategy that took three trades.
3. Run it in **analyzer mode**, where orders go to the sandbox rather than to a
   broker, and watch the orders it actually sends against the signals you
   expected.
4. Only then, live, and at the smallest size the instrument allows.

Where the orders go is the platform's mode, not the script's. The same compiled
program is live or sandbox depending on how the platform is set, so a script
cannot be inspected to find out which it is doing.
