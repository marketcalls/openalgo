# Porting a JavaScript chart indicator to an OpenScript study

A chart indicator here is a JavaScript descriptor handed to `registerIndicator`
(the `chart-indicator` skill describes the format): `inputs`, `plots`, `levels`,
`fills`, sometimes `markers`, `draws`, `table`, `barColors` and `background`,
and a `calc(bars, settings, store, ctx)` that returns one array per plot key. A
port is an OpenScript `study()` that computes the same numbers on the same bars.

**The original is the specification.** Port its arithmetic, statement by
statement, not the textbook indicator its name suggests. If the two disagree,
the port is wrong, however standard its formula.

Everything below was hit while porting 497 of these indicators, and every claim
was then checked against `openalgo-script` 0.8.1 and `openalgo-charts` 2.6.0:
the codes by compiling, the numbers by running both sides on the same bars.

**How to read the code blocks.** Every `openscript` block compiles with no
diagnostic once `version 1` and a `study(...)` line are put above it (a block
that starts with `version 1` is a whole file). A block whose first line begins
`// Wrong:` is the spelling to avoid, and that line says what the compiler
reports, or what the script computes instead when it reports nothing.

---

## How a port goes

1. **Read the descriptor before writing a line.** Every input `key` becomes the
   name the input is assigned to, so one settings object drives both sides,
   with the same label, default, `min`, `max`, `step` and option values, case
   included. Every visible plot keeps its title, colour, width and kind.
2. **Carry `calc` across statement by statement.** Most originals loop over `i`
   and keep their own recursions; each becomes a statement that runs once per
   bar, and each value carried between iterations becomes `var` state.
3. **Look every chart helper up in the table below** before reaching for the
   built-in of the same name.
4. **Compile with `validate.mjs`, then compare the numbers** (the last section).
   A clean compile says nothing about parity.

The shapes that recur:

| In the original | In the port |
|---|---|
| the body of `for (let i = 0; i < bars.length; i++)` | top-level statements, run once per bar |
| `values[i - k]` | `x[k]` |
| `i === 0`, `i > 0` | `bar.isFirst`, `bar.index > 0` |
| `NaN` or `null` in a column | `none` |
| `Number.isFinite(x)` | `not isNone(x)` |
| `Number.isFinite(x) ? x : 0` | `orElse(x, 0)`, only where the original really reads zero |
| a `let` declared outside the loop | `var name = none` |
| `Math.max(a, b, c)` | `max(max(a, b), c)`: `max` takes two arguments, three is `OS3001` |

---

## Chart helpers whose OpenScript twin computes something else

These were measured on 1,463 hourly bars, every bar compared.

| Original call | What it answers | In the port |
|---|---|---|
| `ema(values, n)` | Seeded with the **first value**, answers from bar 0 | Not `ema`. Write the recursion below |
| `smaSeededEma(values, n)` | Seeded with the simple average of the first `n`, answers from bar `n - 1` | `ema(src, n)`, also on a series that starts absent or has gaps |
| `highestBars(values, n)`, `lowestBars(values, n)` | 0, or a **negative** offset | `highestBars` and `lowestBars` answer a positive count of bars back: negate |
| `supertrend(bars, period, factor)` | First value on bar `period - 1` | `supertrend(factor, period)` first answers on bar `period`, one bar later; from there the line and the direction agree, direction sign included |
| `percentileNearestRank(values, n, 50)` | For an even `n`, the lower of the two middle values | `median` and `percentile` interpolate. Sort a copy of the window and take an element |
| `highest(values, n)` over a series with gaps | Skips the missing value | `highest` is absent for any window holding one. They agree on gap-free data |
| `sessionFlags(times, spec, zone)` | Day digits 1 = Sunday to 7 = Saturday; equal start and end is the whole day | `session.isIn(spec, zone)` counts 1 = Monday to 7 = Sunday, and equal start and end is an empty window. Map each digit `d` to `mod(d + 5, 7) + 1` |
| `Math.round(x)` | Halves toward positive infinity: `-2.5` is `-2` | `round` takes halves away from zero: `-3`. Write `floor(x + 0.5)` |
| `a % b` | Sign of `a`: `-1 % 3` is `-1` | `mod(a, b)` is floored, sign of `b`: `2` |
| `Math.log(0)`, `x / 0`, an overflow | `-Infinity`, `Infinity` | `none`. See the next section |

The ones that matched on every bar, with nothing to change: `sma`, `rma`,
`wma`, `stdev`, `highest` and `lowest` on gap-free data, `atr(high, low, close, n)`
as `atr(n)`, `rsi(values, n)` as `rsi(src, n)`, `trueRange` as `trueRange()`,
`rollingSum` as `sum`, `alma`, `linreg`, `pivotHigh` and `pivotLow` (both
report on the confirming bar, `right` bars after the pivot), and `cci` over
`hlc3` as `cci(n)`, which takes no source: `cci(close, 14)` is `OS3001`.

The chart core's `ema`, which is the one that most often reaches a port:

```openscript
// Seeded with the first value, so it answers from bar 0.
fn emaFromFirst(src, len) =>
    var e = none
    a = 2 / (len + 1)
    e = isNone(e) ? src : src * a + e * (1 - a)
    e

plot(emaFromFirst(close, 14), "EMA")
plot(emaFromFirst(emaFromFirst(close, 14), 14), "EMA of EMA")
```

Each call site keeps its own `var e`, so the nested call is the chart's
`ema(ema(values, 14), 14)`, and both lines match the chart's bit for bit. A closure factory
in the original (a `makeEma()` that returns a stepping function) is the same
thing: one `fn` with `var` state, called once per series.

---

## Absent is not `NaN`

Arithmetic on `none` is `none`, which is what `NaN` does. Four places part.

### Division by zero, `log` of zero and overflow are `none`, not infinities

`x / 0`, `log(0)`, `log` of a negative number, `exp(1000)` and `1e300 * 1e300`
are all `none`. An original that lets an infinity reach `Math.max`, `Math.min`
or `exp(-Infinity) = 0` and clamps it to a number has to have that edge written
out:

```openscript
// Wrong: compiles, and is none at Period 1, where the original's
// Math.max(-Infinity, 0) gives 0
period = input(1, "Period", min = 1)
len1 = max(log(sqrt(0.5 * (period - 1))) / log(2) + 2, 0)
plot(len1, "Len1")
```

```openscript
period = input(1, "Period", min = 1)
root = sqrt(0.5 * (period - 1))
len1 = root > 0 ? max(log(root) / log(2) + 2, 0) : 0
plot(len1, "Len1")
```

### `==` and `!=` against `none` are real answers, and `!=` is true

An ordering comparison with `none` (`>`, `<`, `>=`, `<=`) is `none`, and `if`
and a ternary take the false arm on it, which matches a `NaN` comparison. An
equality comparison is not: `none == 1` is `false` and **`none != 0` is
`true`**. So the original's `Number.isFinite(v) && v !== 0` cannot be written
as `v != 0`:

```openscript
// Wrong: compiles, and reads as moved on bar 0, where change1 is absent
change1 = close - close[1]
plot(change1 != 0 ? 1 : 0, "Moved")
```

```openscript
change1 = close - close[1]
plot(not isNone(change1) and change1 != 0 ? 1 : 0, "Moved")
```

### `and`, `or` and `not` keep `none`

`none and true` is `none`, `false and none` is `false`, `true or none` is
`true`, and `not none` is `none`. Inside an `if` that reads as false, but a
flag that is stored, negated or carried in a `var` carries the `none` on. Where
the original's guard makes it `false`, say so: `toBool(cond)` or
`orElse(cond, false)`.

### One absent value inside a `var` recursion stays for good

```openscript
// Wrong: compiles, and is none on every bar, because close[1] is absent on
// bar 0 and the sum never recovers
var total = 0.0
total = total + close[1]
plot(total, "Total")
```

```openscript
var total = 0.0
if not isNone(close[1])
    total = total + close[1]
plot(total, "Total")
```

An original that writes `if (!Number.isFinite(x)) continue` holds its state on
that bar. The guard is how a port holds it too: the update sits inside
`if not isNone(x)`. Price data with no gaps hides this; a ratio whose
denominator can be zero, or a series built on an average that is absent during
its warmup, does not.

---

## Bar 0, `i > 0`, and reading the previous bar

`x[1]` on bar 0 is `none`. An original whose loop starts at `i = 1` leaves bar 0
empty, which the absent `x[1]` usually does by itself. An original that compares
the first bar with itself is a test of the bar, written out:

```openscript
// The original's i > 0 ? src[i - 1] : src[i]
prevClose = bar.index > 0 ? close[1] : close
plot(close - prevClose, "Change")
```

**Reading a `var` before the line that reassigns it gives the previous bar's
final value, and so does `x[1]` wherever it is read.** Two bars back is `x[2]`.
A recursion over `out[i - 1]` and `out[i - 2]` written as `x` and `x[1]` above
the reassignment is shifted by one bar:

```openscript
// Wrong: compiles, and out2 is one bar back, not two: above the reassignment
// x and x[1] are the same value
var x = 0.0
out1 = x
out2 = x[1]
x = 0.5 * close + 0.3 * orElse(out1, close) + 0.2 * orElse(out2, close)
plot(x, "Filter")
```

```openscript
var x = 0.0
out1 = x[1]
out2 = x[2]
x = 0.5 * close + 0.3 * orElse(out1, close) + 0.2 * orElse(out2, close)
plot(x, "Filter")
```

On bar 0 the two forms part as well: `x` reads the `var`'s initial value and
`x[1]` reads `none`. Pick the one that matches what the original seeds with.

A plain name cannot read its own history before it exists:

```openscript
// Wrong: OS2001, x is not defined at this point in the file
x = 0.5 * close + 0.5 * orElse(x[1], close)
plot(x, "Smooth")
```

```openscript
var x = none
x = 0.5 * close + 0.5 * orElse(x, close)
plot(x, "Smooth")
```

---

## Stateful calls belong at the top level (`OS8001`)

A stateful call that runs on some bars and not others holds a history its
length does not describe. `reference/pitfalls.md` covers the `if` block. The
same warning comes from a **ternary arm**, because only the arm that is chosen
runs:

```openscript
// Wrong: OS8001, and ema sees only the bars where close > open, so it is the
// average of a different series
up = close > open
trendLine = up ? ema(close, 20) : close
plot(trendLine, "Trend")
```

```openscript
up = close > open
emaLine = ema(close, 20)
trendLine = up ? emaLine : close
plot(trendLine, "Trend")
```

On the 1,463 test bars the two differ on 741 of them. The warning does not stop
the script: it compiles, installs and draws the wrong line.

A menu that switches the average is `OS8001` as well
(`useEma ? ema(close, 20) : sma(close, 20)` warns twice). An input holds still
for the run, so the arm it picks happens to see every bar and the numbers come
out right, but the shape is the same one that breaks as soon as the condition
reads the bar. Compute every average at the top level and choose between the
names:

```openscript
useEma = input(true, "Use EMA")
emaLine = ema(close, 20)
smaLine = sma(close, 20)
basis = useEma ? emaLine : smaLine
plot(basis, "Basis")
```

A `fn` of your own that holds a `var`, or calls a stateful built-in, is itself
stateful: `useIt ? emaFromFirst(close, 10) : close` is `OS8001` too. A `fn` with
only arithmetic, loops and history reads is not, and can sit in an arm.

---

## `fn`: state per call site, and what a body cannot see

### An input read inside a `fn` body is absent, and nothing says so

This is the most expensive one on this page, because it compiles with no
diagnostic. A number input read directly in a body is `none`, a bool input is
`false`, and whatever depends on it quietly stops: a filter rejects everything,
a label loses its text.

```openscript
// Wrong: compiles with no diagnostic, and plots nothing: len is none in the body
len = input(3, "Length")
fn shifted(v) => v + len
plot(shifted(close), "Shifted")
```

```openscript
len = input(3, "Length")
fn shifted(v, n) => v + n
plot(shifted(close, len), "Shifted")
```

Pass every setting in as an argument. A top-level copy (`lenSetting = len`) read
in the body also works. Constants, series and `var` names declared at the top
level read correctly inside a body; inputs do not.

A **table handle** behaves the same way: `cell(t, ...)` inside a body, with `t`
read from the top level, writes nothing and reports nothing. Pass the table in:

```openscript
t = table("Stats", 2, 2, position = "bottomRight")
fn writeRow(grid, row) =>
    cell(grid, row, 0, "Close")
    cell(grid, row, 1, text(close, 2))
    0
if bar.isLast
    writeRow(t, 0)
plot(close, "Close")
```

### Names, history and return values

- **A body cannot assign a top-level name.** `total = total + v` inside a `fn`
  is `OS2002`, because it declares a local that collides. It can change a
  top-level `var` array in place (`push`, `set`, `shift`), and the change
  persists.
- **A parameter or a local cannot share a name with any top-level name, even
  one declared further down the file.** `OS2002` names that later line. Give
  helpers names used nowhere else.
- **A local has no history; a parameter does.** `d[len]` on a local is `OS2004`.
  Compute the series at the top level and pass it in, where `src[len]` works.
- **A body that ends in an `if` / `else` statement returns `none`.** It
  compiles with no diagnostic. End the body with an expression or a ternary.
- **An array literal of untyped parameters is `OS2015`.** `xs = [a, b]` inside
  `fn pair(a, b)` cannot tell the element type; annotate: `fn pair(a: number, b: number)`.

```openscript
// Wrong: compiles, and pick is none on every bar
fn pick(v) =>
    if v > 0
        1
    else
        -1
plot(pick(close - open), "Side")
```

```openscript
fn pick(v) => v > 0 ? 1 : -1
plot(pick(close - open), "Side")
```

---

## Loops and the loop budget

- `for i = 0 to n - 1` runs **zero** times when `n` is 0. A range is never
  counted down, so `for k = 1 to 0` runs nothing. A reversed range written with
  literals is warning `OS8015`.
- `src[k]` with the loop variable as the offset reads history, and is `none`
  before bar 0. That reproduces an original's partial window at the left edge
  with no special case.
- **All loops in one bar share one budget of 2,000,000 turns.** Going over is
  `OS5001` and stops the bar; it never breaks out quietly. If the original
  really needs more, raise it in the statement straight after the declaration,
  with a literal (`OS3014` anywhere else, `OS3015` from an input):

```openscript
version 1
study("Pairwise", overlay = true)
limits(loops = 4_000_000)

total = 0
if bar.isLast
    for i = 0 to 2999999
        total = total + 1
plot(total, "Turns")
```

Before raising it, ask whether the original rebuilds each bar something a `var`
could carry forward. A weight table the original builds inside `calc` depends
only on settings, which do not change during a run, so it can be built once:

```openscript
len = input(9, "Length", min = 1)
var weights: array<number> = []
if size(weights) == 0
    for k = 0 to len - 1
        push(weights, len - k)
total = 0.0
for k = 0 to len - 1
    total += orElse(close[k], 0) * element(weights, k)
plot(total / (len * (len + 1) / 2), "Weighted")
```

---

## Declarations that read like JavaScript, or like another chart language

- **There is no `:=`.** Reassignment is `=`, and `+=`, `-=`, `*=` work. `:=`
  is `OS1018`, "Unexpected : after the end of this statement", which never
  mentions assignment.
- **A type annotation is accepted only on `var`.** `vals: array<number> = []` is
  `OS1018` followed by an `OS2001` on every use. A per-bar array is `vals = []`,
  typed by its first `push`; a kept one is `var vals: array<number> = []`.
- **Reserved words** (`OS1019`): `and array as bool break case color continue
  default else false fn for if import in is live map matrix none not number or
  return series step string strategy study switch to true type var while`.
  `step` is the one ports reach for, and its `OS1019` arrives with a cascade
  (`OS3012`, `OS1012`, `OS1022`) on the lines that use it. Fix the `OS1019` and
  the rest go.
- **Library names** (`OS2002`, then `OS2014` "is a function" on each use). The
  ones ports hit, all checked: `alpha` (it reads a colour's alpha, and every
  EMA port reaches for it), `count`, `size`, `sum`, `avg`, `max`, `min`, `log`,
  `change`, `sign`, `cum`, `signal`, `level`, `median`, `percentile`, `stdev`,
  `variance`, `correlation`, `highest`, `lowest`, `pivotHigh`, `pivotLow`,
  `rising`, `falling`, `cross`, `ma`, `ema`, `sma`, `rma`, `wma`, `hma`, `dema`,
  `kama` (planned, and still taken), `atr`, `rsi`, `cci`, `cmo`, `mfi`, `mom`,
  `obv`, `nvi`, `pvi`, `eom`, `fisher`, `hv` and `oi`. A plot variable named
  after its own indicator always collides; `rsiValue` does not. Free, and
  checked: `range`, `window`, `source`, `src`, `width`, `period`, `offset`,
  `order`, `line`, `tr`, `beta`, `lambda`, `delta`, `gain`, `weight`, `day`,
  `month`, `year`, `trend`, `mid`, `upper`, `lower`, `spread`, `slope`, `gap`,
  `body`.

---

## Markers, labels and drawings

### `signal` marks this bar, with fixed position, shape and colour

`signal(text, color = ..., at = ..., shape = ...)` marks only the bar it runs on.
It has no `offset` and no `size` (`OS3002` for either). `at`, `shape` and
`color` are fixed before bar 0: the colour is a literal or an input, and a named
top-level colour is `OS3003` beside an `OS6018` that calls itself a compiler
defect; it is not one.

```openscript
// Wrong: OS3003 and OS6018: a named colour is not a literal
UP = #26a69a
signal(close > open ? "Up" : none, color = UP, at = "below", shape = "triangleUp")
plot(close, "Close")
```

A colour, side or shape that changes per bar is one call site per combination,
each switched by its text:

```openscript
up = close > open
signal(up ? "Up" : none, color = #26a69a, at = "below", shape = "triangleUp")
signal(up ? none : "Down", color = #ef5350, at = "above", shape = "triangleDown")
plot(close, "Close")
```

The shapes are `label`, `arrowUp`, `arrowDown`, `triangleUp`, `triangleDown`,
`circle`, `square`, `diamond`, `cross` and `flag`. `labelUp` is `OS3008`: write
`shape = "label"` with `at = "below"`. An empty text, `""`, still records a mark
on the bar, so a shape the original draws without text stays without text
rather than gaining an invented word.

### A mark on an earlier bar is a plot with a negative literal offset

A pivot or a fractal is known some bars after the bar it marks. Test on the
confirming bar, and draw the value back with a `lineWithMarkers` plot:

```openscript
fractal = high[2] > high[4] and high[2] > high[3] and high[2] > high[1] and high[2] > high ? high[2] : none
plot(fractal, "Up Fractal", #ff5252, style = "lineWithMarkers", offset = -2)
```

### A plot offset cannot follow an input

`offset` is fixed before bar 0. It takes a literal, or an input as the **whole**
of its value (`offset = right` compiles). Anything else is refused:

```openscript
// Wrong: OS3025 and OS6018: -right is an expression over an input
right = input(2, "Right", min = 1, max = 10)
plot(high[right], "Pivot", red, style = "lineWithMarkers", offset = -right)
```

A named constant is refused as well (`offset = -LAG` is `OS3003` and `OS6018`).
When the distance back is a setting, draw a label at the earlier bar's time
instead:

```openscript
right = input(2, "Right", min = 1, max = 10)
var marks: array<label> = []
if not isNone(pivotHigh(high, 2, right))
    push(marks, draw.label(time[right], high[right], "P", textColor = red))
    if size(marks) > 50
        draw.delete(shift(marks))
plot(close, "Close")
```

`draw.label` has no shape: `color` is the plate, `none` by default, and
`textColor` is white by default, so set `textColor` to the original's marker
colour.

A plot writes one value on each bar, and a fixed offset is the only way to
place it on another. An original that fills a span of earlier bars once it
knows where the span ends, over a distance that varies, has no exact port: say
so rather than approximate it in silence.

### Drawings the original caps at N

The block above is the pattern: keep the handles in a `var` array, and when it
passes the original's cap, `draw.delete(shift(...))` removes the oldest object
and its handle together (deleting without the `shift` is `OS8019`, see
`reference/pitfalls.md`). Checked: with a cap of 50, the 50 labels left are the
newest 50 pivots. A script holds at most 10,000 drawing objects; number 10,001
is `OS5010` and stops the run.

---

## Plots and levels

- **Plot styles** are `line`, `lineWithMarkers`, `step`, `area`, `histogram` and
  `column`. A dotted or dashed plot does not exist: `style = "dotted"` is
  `OS3008`, `lineStyle` is `OS3002`. Draw it solid and say so.
- **Levels take `style = "dotted"`, `"dashed"` or `"solid"`, and a level with no
  style is dashed.** So is the chart's: a level descriptor with neither
  `lineStyle` nor `dashed` draws dashed. Port a level with no flag with no
  `style`, and only `dashed: false` (or `lineStyle: 'solid'`) as
  `style = "solid"`.
- **Level, input and table titles are unique in a file**, groups included:
  `OS3017`. An original that repeats "Length" or "Overbought" across groups
  needs one label prefixed; the input key does not change.
- **A level's colour is a constant.** `withAlpha(#787b86, 0.3)` and
  `fade(#787b86, 70)` compile and are the same colour; `withAlpha(GRID, 0.3)`
  with a named colour is `OS3003` and `OS6018`. The original's
  `withAlpha(c, a)` is `fade(c, 100 - 100 * a)`.

---

## Tables

- **Four corners only:** `topLeft`, `topRight`, `bottomLeft`, `bottomRight`.
  `"bottom-right"` is `OS3008`.
- **The position is a literal or a whole input**, whose options are those four
  names. A ternary that maps the original's spelling is `OS3025` with `OS6018`.
  An original with nine positions, or its own spelling, keeps its menu (the key
  must match) and gets one grid per corner, with the cells written to the one
  the menu picks:

```openscript
where = input("bottom-right", "Position", options = ["top-left", "top-right", "bottom-left", "bottom-right"])
tl = table("Stats TL", 1, 2, position = "topLeft")
tr = table("Stats TR", 1, 2, position = "topRight")
bl = table("Stats BL", 1, 2, position = "bottomLeft")
br = table("Stats BR", 1, 2, position = "bottomRight")
if bar.isLast
    t = where == "top-left" ? tl : where == "top-right" ? tr : where == "bottom-left" ? bl : br
    cell(t, 0, 0, "Close", bgColor = #131722, textColor = white)
    cell(t, 0, 1, text(close, 2), bgColor = #131722, textColor = white)
plot(close, "Close")
```

  All four grids exist on every run, written or not, and the OpenScript
  reference for `table` says a grid with its own `bgColor` or `borderWidth`
  shows as an empty block.
  Keep both off the grids and colour the cells.
- **No text size, bold or border colour.** `textSize` on `table` or `cell` is
  `OS3002`. Keep the original's size input so its key exists; it is then never
  read, which is warning `OS8018`, and the page should say it has no effect.
- **A table's `bgColor` is a constant**: `withAlpha(#131722, 0.9)` compiles, a
  named colour inside it is `OS3003` and `OS6018`.
- A table handle read inside a `fn` body writes nothing: pass it in, as above.

---

## Inputs

- **An input's key is the name it is assigned to.** An input that is not
  assigned to a name, written inside an expression, is keyed by its **title**.
  `input` has no `key` argument (`OS3002`).
- **When the original's key is a library name**, `alpha = input(...)` is
  `OS2002` and `OS2014`. Keep the key by leaving the input unassigned, with the
  key as its title; the cost is that the dialog shows the key as the label:

```openscript
// Keyed "alpha", because an unassigned input takes its title as its key.
smoothing = clamp(input(0.07, "alpha", min = 0.01, max = 1), 0.01, 1)
plot(close * smoothing, "Scaled")
```

- **Menu options are strings.** `options = [2, 3]` is `OS3011`. An original menu
  with number values becomes a number input over the same range:
  `input(2, "Poles", min = 2, max = 3, step = 1)`.
- **An input the original declares and never reads is still declared**, so the
  keys match. It is warning `OS8018`, and its description should say it changes
  nothing.

---

## Time zones, sessions and calendar functions

- **An unknown zone stops the run** with `OS6005`, at run time, not at compile
  time. `"EST"` and lower-case `"utc"`, both of which JavaScript accepts, are
  refused. `orElse` cannot catch it, and there is no way to test a zone name
  first, so an original that checks a typed zone and falls back to a default
  cannot be matched for a bad name. Say so in that setting's description.
- **`date.hour`, `date.dayOfWeek` and the rest take the time**: `date.hour(time)`.
  Written bare, `date.hour` is `OS2014`, as is `chart.now` without its `()`.
- `date.dayOfWeek` counts 1 = Monday to 7 = Sunday, the same as `session.isIn`.
  The chart core's session specs count from Sunday; map the digits as in the
  helper table.

---

## Maths

- `exp`, `sqrt`, `pow`, `log`, `log10`, `abs`, `floor`, `ceil` are bare names;
  `math.cos`, `math.sin`, `math.atan` and `math.pi` sit in `math`. An `exp`
  written under `math` is `OS2001`, whose suggested fix (`math.e`) points the
  wrong way: the answer is the bare `exp`.
- `math.tanh`, `math.sinh` and `math.cosh` are planned (`OS2020`). Write them
  from `exp`; this form cannot overflow:

```openscript
fn tanhOf(v) =>
    e = exp(-2 * abs(v))
    sign(v) * (1 - e) / (1 + e)
plot(tanhOf((close - open) / 50), "Tanh")
```

- `/` is always real division: `7 / 2` is `3.5`.

---

## Checking parity

A compile proves the names resolve. Parity means running the original's `calc`
and the compiled port on the same bars, with the same settings, and comparing
every bar. This script does that. It needs the two packages the skills already
cache: `openalgo-script` (in `frontend/node_modules`, or under
`.claude/skills/openscript/.cache/` once `validate.mjs` has run) and
`openalgo-charts` (in `frontend/node_modules`, or under
`.claude/skills/chart-indicator/.cache/`). Save it to a scratch folder:

```js
// node parity.mjs <openalgo-script dir> <openalgo-charts dir> <original.js> <port.oscript> <bars.json> [settings.json]
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [scriptDir, chartsDir, originalPath, portPath, barsPath, settingsPath] = process.argv.slice(2)
const url = (p) => pathToFileURL(resolve(p)).href
const os = await import(url(join(scriptDir, 'dist', 'core', 'index.js')))
const charts = {
  ...(await import(url(join(chartsDir, 'dist', 'openalgo-charts.mjs')))),
  ...(await import(url(join(chartsDir, 'dist', 'openalgo-charts.indicators.mjs')))),
}

// [{ time (UTC seconds), open, high, low, close, volume }, ...]
const bars = JSON.parse(readFileSync(barsPath, 'utf8'))

// The original: capture its descriptor, then run calc on the bars.
let d
;(await import(url(originalPath))).default({ ...charts, registerIndicator: (x) => (d = x) })
const settings = Object.fromEntries(d.inputs.map((i) => [i.key, i.default]))
if (settingsPath) Object.assign(settings, JSON.parse(readFileSync(settingsPath, 'utf8')))
const values = d.calc(bars, settings, new Map(), { timezone: 'UTC', tickSize: 0.01 })

// The port: compile it, load it with the same settings, run the same bars.
const file = os.sourceFile('port.oscript', os.normaliseSource(readFileSync(portPath, 'utf8')))
const bag = new os.DiagnosticBag()
const { program } = os.emit(file, os.check(file, os.parse(file, bag), bag), bag)
if (bag.hasErrors) throw new Error(bag.ordered().map((x) => `${x.code} ${x.message}`).join('\n'))
const instrument = { symbol: 'TEST', interval: '60', timezone: 'UTC', tickSize: 0.01 }
const loaded = os.load(program, { source: file, settings, host: { instrument, now: bars.at(-1).time * 1000 } })
if (!loaded.ok) throw new Error(loaded.diagnostic.message)
loaded.engine.run(bars.map((b) => ({ ...b, time: b.time * 1000 })))

// Pair plots by title and name the first bar that differs.
const num = (v) => (v == null || !Number.isFinite(Number(v)) ? null : Number(v))
const differs = (a, b) =>
  (a === null) !== (b === null) || (a !== null && Math.abs(a - b) > 1e-9 + 1e-6 * Math.max(Math.abs(a), Math.abs(b)))
for (const p of d.plots) {
  const title = p.title ?? p.key
  const out = program.outputs.plots.find((q) => q.title === title)
  if (!out) { console.log(`${title}: the port has no plot of that title`); continue }
  const port = Array.from(loaded.engine.column(out.channel), num)
  const orig = Array.from(values[p.key] ?? [], num)
  const at = orig.findIndex((a, i) => differs(a, port[i]))
  console.log(at < 0 ? `${title}: same on every bar` : `${title}: bar ${at} differs, ${orig[at]} against ${port[at]}`)
}
```

It compares a column as it is computed, before any `offset` moves it. It does
not compare markers, drawings, tables or colours: read those against the
original's `markers`, `draws` and `table` hooks yourself.

What it cannot do is choose the bars and the settings, and that is where a port
that matches still hides a fault:

- **Run every setting, not only the defaults**: every menu option, every switch,
  each number at its minimum, at small values such as 1 and 2, and at its
  maximum. A branch no setting reaches is a branch nobody has compared.
- **Run settings that make the study fire.** A strict filter that draws nothing
  at its defaults compares empty against empty and proves nothing.
- **Run bars with holes in them** (a few closes set to `null` for the port and
  `NaN` for the original), and bars with gaps in time if the original reads a
  session or a calendar. Gap-free 24-hour data hides every difference in the
  sections on absent values and sessions above.
- **Run a different time zone** when the original reads one: data in UTC hides
  every zone mistake.
