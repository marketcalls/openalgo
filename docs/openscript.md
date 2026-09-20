# OpenScript on the charting terminal

OpenScript is an open trading language. You write a study once, plot it on the
`/trading` chart, and later backtest and trade the same file.

It is not a replacement for the custom indicators described in
[custom-indicators.md](custom-indicators.md). The two sit side by side and are
meant for different people. The difference that matters is below, and it is
worth reading before you choose between them.

## Writing one

Open the chart at `/trading`, choose **Scripts** on the right rail, and select
**New**. You get a working study to edit rather than an empty file.

The panel is an editor, a compiler and the chart, in that order:

- **It compiles as you save.** There is no build step. If the script will not
  run, the console under the editor says what is wrong, on which line, and what
  to do about it, in the compiler's own words. The line is marked in the gutter.
- **It saves either way.** A script that does not compile is still written to
  disk. Being half way through a thought is not a reason to lose it.
- **Add to chart** puts the study on the focused chart without going near the
  indicator picker. It is available once the script is saved and compiling.
- **Ctrl+S** saves, so the browser does not open its own save dialog over the
  panel.

Colours come from the language's own lexer, which is the same one the compiler
runs. A word added to the language is coloured the day it lexes, because nothing
here keeps a second list of what the keywords are.

Editing is a plain text area today, deliberately. The language ships its editor
intelligence, completion, hover, signature help and inline diagnostics, as
headless functions in a later release, built to drop into a full code editor
component. Wiring one in now would mean wiring it twice.

## Where your scripts live

`strategies/openscript/`, beside `strategies/indicators/` and
`strategies/scripts/`. On Docker that folder is a named volume
(`openalgo_strategies:/app/strategies`), so your scripts survive a container
rebuild and an upgrade leaves them alone. They are not committed to the
repository and a `git pull` never touches them.

A script is a plain text file ending in `.oscript`. The name may hold letters,
digits, dots, dashes and underscores, must start with a letter or a digit, and
may be up to 64 characters. A script may be up to 256 kB, which is far larger
than any study anyone writes; the limit exists because the smallest deployment
leaves the web server's request size at its default and a script that grew past
it would fail with a gateway error rather than a sentence.

## Why this is safer than a custom indicator

A custom indicator is JavaScript, and the page imports it and runs it. It has
the same reach you do: your logged-in session, `/api/v1/`, your positions, your
orders. The custom indicators page says so plainly, and it is right to. Adding
one from a stranger is the same act as pasting a script into the browser
console.

An OpenScript file is not code the page runs. It is text a compiler turns into a
list of instructions, and an engine walks that list. A script can only name what
the instruction set gives it, which is bars, arithmetic and things to draw.
There is no way to spell a network call, a file, or a reach into the page,
because those names do not exist in the language. Nothing was handed over, so
there is nothing to escape from.

Two consequences worth knowing:

- **A script from a stranger is a much smaller decision.** It can draw a wrong
  line on your chart. It cannot place an order you did not write, and it cannot
  send your positions anywhere.
- **It needs no change to the security policy.** OpenAlgo serves pages with
  scripts restricted to its own origin and no permission to build code out of
  text. A language that compiled to JavaScript would need that permission
  turned on for every page in the platform. This one does not, and that is the
  reason the compiled program is data rather than code.

The sources are served as plain text and never as JavaScript, deliberately, so
that the page cannot import one even by mistake.

## Choosing between the two

| You want | Use |
| --- | --- |
| A study, on your own chart, written quickly and safely | OpenScript |
| To share a study with someone who should not have to trust you | OpenScript |
| Full access to the platform from inside an indicator | A custom indicator |
| Something the language cannot express yet | A custom indicator |

A custom indicator can do more because it is unrestricted. That is its purpose
and its price.

## The routes

All four require a logged-in session. They are under the path the web server
already proxies, so a hosted install needs no configuration change.

| Method and path | Does |
| --- | --- |
| `GET /openscript/index.json` | Lists your scripts with the size and modification time of each |
| `GET /openscript/<name>.oscript` | Returns one script as plain text |
| `POST /openscript/<name>.oscript` | Creates or replaces one, from a JSON body carrying `source` |
| `DELETE /openscript/<name>.oscript` | Removes one, and the backup taken of it |

A save keeps a `.bak` beside the script holding what was there before, because
the browser editor is the only copy. The write is atomic: a save that is
interrupted leaves the previous script whole rather than half of the new one.

## The language itself

OpenScript is developed as its own open source project so that other platforms
can adopt it, under Apache-2.0, with a written specification and a conformance
suite. The language reference, the error catalogue and the integration guides
live there rather than being restated here.
