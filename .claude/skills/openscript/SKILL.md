---
name: openscript
description: Write an OpenScript study or strategy for OpenAlgo, and install it into strategies/openscript/ only after it compiles. Use when asked to create, port or debug an OpenScript indicator, study, strategy, backtest script or .oscript file, including porting a study or strategy written for another charting platform. This is the OpenScript path, not the JavaScript chart-indicator path and not the Python openalgo.ta path.
argument-hint: "[what the study or strategy should do]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# OpenScript studies and strategies

Write a `.oscript` file and install it into `strategies/openscript/`, where it
becomes a study or a strategy a trader can open in the editor, backtest on
`/trading`, and deploy on an instrument.

**Which path is this.** Three unrelated things in this repository are called
indicators, and they share nothing but the word:

- **OpenScript** (this skill) is a language, compiled to a program. Files are
  `.oscript`, and they can both draw and place orders.
- **`chart-indicator`** is a plain JavaScript descriptor on `openalgo-charts`,
  drawing only, loaded by the browser at runtime.
- **`openalgo.ta`** is a Python library used from the Python strategy host,
  scanners and backtests.

If the request names a `.oscript` file, the OpenScript editor, or a strategy to
deploy on `/trading`, it is this one. If it is "add an indicator to my chart"
with no more said, it is probably `chart-indicator`.

## The one rule

**Never write into `strategies/openscript/` by hand.** That folder holds two
files per script, `<name>.oscript` and `<name>.oscript.program.json`, and **the
runner reads only the program.** It never opens the source.

That makes two silent failures possible, and both matter more than a compile
error:

- **A source with no program is a strategy that cannot run.** It saves, it opens
  in the editor, it appears in the list, and starting it is refused a minute
  later in a log nobody is reading.
- **A program built from different text is worse.** A run executes one script
  while a trader reads another.

So the two files are written together, from one compile, or neither is:

```bash
# 1. draft to a scratch file (never the openscript folder)
#    e.g. <scratchpad>/my_strategy.oscript

# 2. compile it the way the browser will
node .claude/skills/openscript/validate.mjs <scratch>/my_strategy.oscript

# 3. only on PASSED, install both files
node .claude/skills/openscript/validate.mjs <scratch>/my_strategy.oscript --install

#    with a different installed name:
node .claude/skills/openscript/validate.mjs <scratch>/draft.oscript --install --as mean-reversion.oscript
```

`--install` writes both files **only** when there are zero errors, and exits 1
otherwise. Before writing either, it checks that the hash the compiled program
records matches the source it is about to write beside it, which is the same
check the platform's own save route makes. A mismatched pair is refused and
nothing is written, so the failure cannot be half-applied.

## What a pass means

The compiler accepted the text: the names resolve, the types agree, the calls
exist, the limits hold. **Nothing here runs a single bar.** It does not mean the
strategy is any good, that its numbers are right, or that it will make money.

`reference/strategies.md` ends with the four steps between a compile and money,
and they are not optional.

## Read these before writing

| Page | What it is for |
|---|---|
| `reference/library.md` | every one of the 350 names, with what it answers and its warmup. Generated from the installed compiler. |
| `reference/pitfalls.md` | what goes wrong, with the diagnostic code you will actually see. Every code on it is proved against the compiler. |
| `reference/strategies.md` | the shapes a strategy takes, and which example answers which ask. |
| `examples/*.oscript` | six worked files, all of which compile. The reasoning is in the comments. |

**Look a name up rather than recalling it.** 350 names is more than anyone holds,
and the dangerous failure is not reaching for a name that does not exist: it is
reaching for a neighbour that computes something else, which compiles and
reports a different strategy than the one that was meant.

## Three things that cost the most time

**Ninety five of the 350 names are planned and not implemented in this version.**
The library describes a name whether or not a version implements it, so a name
resolving is not a promise that it compiles. Reaching for one is `OS2020`. They
are marked in `reference/library.md`. `order.qtyForRisk` is the one most likely
to be reached for by accident, because it reads exactly like the call you want;
whole families are planned, including all of `leg.*` and all of `book.*`.

**`buy` and `sell` move a position by an amount; they do not set it to a side.**
`sell(qty = lots)` while long one lot leaves the position flat, not short.
Nothing refuses it. It is the first entry in `reference/pitfalls.md` and the
reason `examples/stop-and-reverse.oscript` exists.

**A value that is absent is not zero.** Every stateful call has a warmup, and
arithmetic on an absent value is absent rather than zero, which is what keeps a
signal from firing before its average exists. A script that substitutes a number
during warmup, with `orElse` or otherwise, is quietly wrong for its first stretch
of bars and looks like it works.

## Keeping the skill honest

Two scripts, both of which must pass, and both of which the CI job runs:

```bash
node .claude/skills/openscript/generate-reference.mjs   # rewrites reference/library.md
node .claude/skills/openscript/coverage.mjs             # must print COVERAGE COMPLETE
node .claude/skills/openscript/check-pitfalls.mjs       # must print PITFALLS VERIFIED
```

`coverage.mjs` holds the reference to the compiler in both directions (a name
the compiler has and the page lacks fails, and so does a name the page teaches
that the compiler does not have), checks that every planned name is marked, and
checks that each shape an author asks for is demonstrated in an example **that
compiles**, with the kind read from the compiled program rather than from the
text.

`check-pitfalls.mjs` compiles both halves of every entry in `reference/pitfalls.md`:
the wrong spelling must still produce the code named, and the fix offered must
still come out clean. It also checks that the page and the script name the same
set of codes, so neither can drift alone. Two claims on the first draft of that
page were wrong, and this is what found them.

**Bumping `openalgo-script` means updating this skill in the same change**, the
way a chart bump does. Run the generator, run both checks, then update the prose
by hand: the generator owns the name table and nothing generates the teaching.
