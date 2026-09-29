# What goes wrong, and what the compiler says about it

Every entry here was hit while writing the six files in `examples/`. None is
hypothetical, and each names the diagnostic code you will actually see, because
a code is a promise and the wording around it is allowed to improve.

`check-pitfalls.mjs` compiles both halves of every entry below: the wrong
spelling must still produce the code named, and the fix offered must still
compile clean. Two of the claims on the first draft of this page were wrong, and
that is what caught them.

The ones that cost money are at the top. They share a shape: **the script
compiles, runs, produces a report, and the report is of a different strategy
than the one that was meant.** A compile error costs a minute. These cost a
position.

---

## The ones that compile

### `buy` and `sell` move a position by an amount; they do not set it to a side

This is the single most expensive mistake in the language, because nothing
anywhere refuses it.

```
// Long one lot. The signal turns down.
sell(qty = lots)        // now FLAT, not short
```

`sell` sold one lot. There was one lot. The position is zero. A strategy
written this way takes its long trades correctly, never takes a short, and
reports a perfectly plausible equity curve for a strategy nobody designed.

Two correct spellings, and they are **not the same call**:

```
buy(qty = lots + abs(pos.size), tag = "Up")   // one order; new size is `lots`
order.reverse()                               // two orders; new size is the old size
```

They agree only while the open size is already `lots`. After a pyramided entry,
or after somebody changes the quantity input mid-run, they part. Pick the one
whose sentence is the sentence you mean. `examples/stop-and-reverse.oscript`
uses the first and says why.

### A value that is absent is not zero, and warmup is when it happens

`sma(close, 20)` answers nothing on bars 0 to 18. Arithmetic on an absent value
is absent, and a comparison against one is absent rather than false. That
propagation is what makes warmup safe by default: a signal built on an absent
average cannot fire.

It stops being safe the moment a script supplies a number instead:

```
trend = orElse(sma(close, 200), close)    // now "above the average" on bar 0
```

That line is a 200-bar strategy that trades from bar 1, and it will look like it
works. The warmup column in [`library.md`](./library.md) is generated from the
compiler for exactly this reason: every stateful call has a bar before which it
answers nothing, and the number is stated rather than guessed.

### `highest(high, 20)` includes this bar

```
broke = close > highest(high, 20)         // almost never true
broke = close > highest(high, 20)[1]      // the high BEFORE this bar
```

The first line asks whether the close exceeded a window that already contains
this bar's high. The bug is quiet in the other direction too: a breakout that
fires on roughly the right bars for the wrong reason.

### A crossing is a bar, not a state

```
if fastLine > slowLine              // true on every bar of the move
if crossUp(fastLine, slowLine)      // true on the bar the crossing completes
```

Written the first way, an entry guarded by `pos.isFlat` still enters, once, on
whichever bar the position happened to be flat. The report is of a strategy that
enters at a random point inside the trend.

### The first bar has no previous bar

```
turnedUp = isLong and not isLong[1]                      // fires on bar 0
turnedUp = not bar.isFirst and isLong and not isLong[1]  // does not
```

On bar 0 there is no `[1]`, so a flip test can read as true whichever way the
trend happened to start, and the run opens a position on the first bar of every
backtest. It is invisible in a long test and dominant in a short one.

---

## The warnings, which do not stop a thing

A warning compiles, emits a program, and installs. Nobody is stopped. These are
the ones to read rather than clear.

### `OS8001`: a stateful call inside a branch

```
if close > open
    trendLine = sma(close, 20)    // warning, and the script still runs
```

> `sma` advances only on the bars where this branch runs, and is absent on the
> rest.

A stateful call has to see every bar to be correct. One that runs on some bars
holds a different history than its length says, so the number it answers is the
20-bar average of a series that skipped bars: not the average of anything a
reader would name. Compute it at the top level and branch on the result:

```
trendLine = sma(close, 20)
plot(close > open ? trendLine : none, "Trend", red)
```

### `OS8010` and `OS8018`: assigned and never read, declared and never read

An input declared and never read still appears in the settings dialog, so a
trader changes it and nothing happens. Usually it means a line was renamed and
its use was not.

---

## The ones the compiler refuses

### `OS2020`: the name is real and the call is not

Ninety five of the 350 described names are **planned and not implemented in this
version**, and they are marked in [`library.md`](./library.md). The library
describes a name whether or not a version implements it, so the name resolving
is not a promise that it compiles.

The one most likely to be reached for by accident:

```
buy(qty = order.qtyForRisk(risk, entry, stop))   // OS2020
```

It reads exactly like the call you want. What it would compute is one division,
so write that:

```
units = max(1, floor(risk / stopDistance))
```

Whole families are planned: all of `leg.*`, all of `book.*`, most of `pos.*`
beyond size and side (`pos.equity`, `pos.netProfit`, `pos.winRate`,
`pos.barsHeld`), and most of `order.*` beyond `place`, `bracket` and `reverse`.
A strategy that wants to read its own equity mid-run cannot, in this version.

**Do not reach for the nearest name that compiles.** A neighbour computes
something else, and a report that quietly changes meaning is worse than one that
refuses to build.

### `OS3002`: `order.bracket` has no `stop` or `target`

```
order.bracket("Break", stop = stopAt, target = targetAt)      // OS3002, twice
order.bracket("Break", loss = stopDistance, profit = target)  // correct
```

`profit` and `loss` are **distances from the entry**, in the instrument's own
price units, not prices. The distance spelling is the whole of this call; the
absolute spelling lives on `exit`. Giving both for the same side is `OS3010`.

### `OS2010`: a value is not a function

```
if session.isLastBar()    // OS2010: series bool, not a function
if session.isLastBar      // correct
```

Read a signature from [`library.md`](./library.md) rather than from a habit of
adding parentheses. `bar.isFirst`, `pos.isFlat`, `pos.isLong`, `pos.isShort`,
`session.isLastBar` and `session.isFirstBar` are all values.

### `OS2002`: the library already has that name

```
avg = sma(close, 20)      // OS2002: avg is already declared at line built-in
trendLine = sma(close, 20)
```

350 names are taken, and the short obvious ones are the taken ones. `avg`,
`log`, `max`, `min`, `cross`, `sum`, `median`, `change`, `signal`, `size`,
`count` and `level` are all library names, and every one of those is a word
somebody reaches for when naming a variable. The message names the collision,
and the second error that usually follows it (`OS2014`) is the shadowed name
being used where a value was expected.

`range`, `trend`, `mid`, `upper`, `lower`, `width`, `spread`, `slope`, `gap`
and `body` are free, if a name that reads like the thing is wanted.

### `OS7016`: a `close` tag must name a tag an order was placed with

```
close(tag = "Square off")   // OS7016: no order in this file uses that tag
close()                     // flattens the whole leg
```

`close(tag)` closes **the part of the position that tag entered**. A tag no
order was placed with can never name a part of one, so the call would send
nothing on every bar and say nothing. A square off wants the whole leg.

### `OS3023`: do not write `leg` in a file that declares none

Leg declarations are planned, so **every** `leg` argument meets `OS3023` in this
version. The fix is to take the argument out, not to change its value.

### `OS3006` and `OS3007`: `plot`, `fill` and `input` are top level only

```
if show
    fill(upper, lower, blue)    // OS3006
```

Nothing may make a plot or a fill conditional on a branch, because the chart
needs the same columns on every bar. Make the **value** conditional instead, and
`none` is how a bar carries nothing:

```
upper = plot(show ? high : none, "Upper", blue)
lower = plot(show ? low : none, "Lower", blue)
fill(upper, lower, blue)
```

`input` is `OS3007` for the same reason and a stronger one: the settings dialog
is built from the inputs a file declares, so an input inside a branch is an
input that exists on some bars.

### `OS6018`: a declaration option cannot be an expression over an input

This one is worth knowing before it happens, because the boundary is not
guessable from the call:

```
plot(close, "c", aqua, width = n)        // fine: one input, carried as a reference
plot(close, "c", aqua, width = n + 1)    // OS6018
plot(close, "c", close > open ? lime : red)   // fine: colour varies per bar
fill(u, l, blue, opacity = show ? 0.3 : 0)    // OS6018
```

A **colour** may vary bar by bar, which is how a line is coloured by condition.
A declaration option such as `width`, `opacity`, `style` or `precision` may not:
the compiled program holds a value or a reference to one input, and an
expression is neither, so it cannot be carried. Compute it before the call, or
declare the input to hold the final number.

### `OS3020`: `fill` takes plot handles, not titles

```
fill("Upper", "Lower", blue)      // OS3020
upper = plot(u, "Upper", blue)
lower = plot(l, "Lower", blue)
fill(upper, lower, blue)          // correct
```

### `OS7001`: `pos`, `buy`, `sell`, `close(tag)` and `order.*` need a strategy

A `study()` file has no position, so none of these exist in it. If the file is
meant to trade, it declares `strategy()`; if it is meant to draw, it does not
get to place orders. There is no third thing.

---

## The three that are not about the language

### `log` is the natural logarithm

```
log("entered long")     // OS3011: log's x is number; string was given
```

There is no logging call in this version. `alert(message, id, title, frequency)`
is how a script says something, and it goes to the platform's alert delivery,
not to a console.

### There are nineteen colours, and `transparent` is not one of them

`aqua black blue brown fuchsia gray green lime maroon navy olive orange pink
purple red silver teal white yellow`. Anything else is `OS2001`. To make
something disappear on a bar, give it `none` rather than looking for a colour
that is not there.

### The source and the compiled program are one change

`strategies/openscript/` holds `<name>.oscript` and `<name>.oscript.program.json`
beside it, and **the runner reads only the program.** A source with no program is
a strategy that cannot start; a program built from different text is a run
executing one script while a trader reads another. `validate.mjs --install`
writes both from one compile, or neither. Never write either file by hand.
