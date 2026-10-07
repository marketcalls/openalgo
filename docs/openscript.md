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
- **The compiled program is saved with it.** When the script compiles cleanly,
  the browser sends the compiled program along with the source and the server
  keeps the two together. That is not an optimisation. It is the only way
  anything on the server can ever run your script, and the next section says
  why.
- **It saves either way.** A script that does not compile is still written to
  disk. Being half way through a thought is not a reason to lose it. What you
  get back is a saved script with no compiled program beside it, which means it
  is yours to keep editing and nothing on the server will run it.
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

A saved script is up to three files, all in that one folder:

| File | Holds |
| --- | --- |
| `<name>.oscript` | The source, as you wrote it |
| `<name>.oscript.program.json` | The compiled program, when the script compiles |
| `<name>.oscript.bak` | The source as it was before the last save |

Deleting a script removes all three.

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
that the page cannot import one even by mistake. The compiled program is held to
the same rule and it is the harder half, because a program is the thing that
will one day be handed to an engine: it is stored as data under a name ending
`.program.json`, served as JSON, and nothing in the platform imports it,
evaluates it or builds anything callable out of it. It is read as bytes and
walked as instructions.

## Choosing between the two

| You want | Use |
| --- | --- |
| A study, on your own chart, written quickly and safely | OpenScript |
| To share a study with someone who should not have to trust you | OpenScript |
| Full access to the platform from inside an indicator | A custom indicator |
| Something the language cannot express yet | A custom indicator |

A custom indicator can do more because it is unrestricted. That is its purpose
and its price.

## What is stored, and how a runner reads it

This section is the contract. Anything on the server that comes to run an
OpenScript strategy reads what is described here, and nothing else.

### Why the compiled program is stored at all

A `.oscript` file is source, and source on its own runs nothing. Turning it into
a compiled program takes a compiler, the compiler is written in TypeScript, and
a production install has no JavaScript runtime in it. The engine that will run a
strategy on the server is Python and has no compiler in it either, deliberately:
an engine walks a list of instructions, and a compiler inside it would be a
second implementation of the language to keep in step with the first.

That leaves exactly one place in the whole deployment where a program can be
produced, and it is the page you are already typing into. So the browser sends
it, and the server keeps it. A platform that stored only the source would have
no way to run a strategy at all.

### What the program file holds

The **canonical encoding** of the compiled program, exactly as the compiler
produced it: UTF-8 with no byte order mark, no whitespace between tokens, object
keys sorted by code point, and numbers written by the language's own rule. The
platform stores those bytes and never re-encodes them, because it cannot. A
program's hash is taken over the canonical bytes and an engine that loads a
program from text refuses text that is not that encoding, so a round trip
through any other JSON writer would produce a program the engine rejects, for a
difference the platform introduced and nobody could see.

The top level is the compiled program as the language's own specification
defines it. Four fields matter before any of the others:

- `openscript.format` and `openscript.language`, the two version numbers an
  engine checks before it does anything else.
- `meta.kind`, either `study` or `strategy`. A study computes and draws. Only a
  strategy holds order instructions.
- `source.hash`, the identity of the text it was compiled from: `sha256:`
  followed by the lowercase hexadecimal SHA-256 of the source after the
  language's normalisation, which is a leading byte order mark removed and every
  carriage return before a newline removed.
- `inputs`, the settings the script declares, which an engine resolves once
  before the first bar.

### The states a script can be in

| On disk | Means |
| --- | --- |
| Source and program | It compiled cleanly at the last save. This is the one state anything can run. |
| Source, no program | Saved and not runnable. Either it does not compile, or it was written by something that does not send programs. |
| Program, no source | Never happens. A delete removes both. |
| Source with an older program | Never happens, and the two rules below are why. |

The last row is the one this design exists for. A stale program is not a wrong
line on a chart: it is instructions executing that nobody can read the source
of. Two rules keep it from arising.

- **A save that carries no program removes the program that was stored.** Not
  "leaves it alone", which reads as the careful choice and is the dangerous one.
  Losing a program costs one recompile. Keeping the wrong one costs a trade.
- **A save is refused when the program was built from other text.** The program
  records the hash of its source, so the server recomputes that hash over the
  source it was handed and compares. It has no compiler and this is the one
  question it can answer without one.

The order the files are written in follows from the same rule: the program is
removed before the source is replaced and written after it, so the only states
an interrupted save can leave behind are a source with the program that belongs
to it or a source with no program at all.

### How a runner reads it

1. Ask `GET /openscript/index.json` which scripts have a program, or look for
   the `.oscript.program.json` files in the folder. An entry whose `program` is
   false has nothing to run.
2. Take the program bytes unchanged, from `GET /openscript/program/<name>.oscript`
   or from the file.
3. Hand those bytes to an engine that loads a program from text. **The load is
   where a program is verified**, in full, before a single bar executes. Do not
   parse the JSON and hand over an object rebuilt from it; the encoding is part
   of what is being loaded.
4. Read `meta.kind` before anything to do with orders. A `study` computes and
   draws and has no order instruction in it.
5. Place orders the way a strategy on this platform already places them, through
   the platform's own order path, so that sandbox mode and analyzer mode are
   honoured by the same code that honours them everywhere else. An engine
   reports what a script asked for; it does not reach a broker.

### What the platform does not do

Said plainly, because a contract is worth less than nothing if a reader assumes
more of it than it promises.

- **It does not compile.** No compiler runs on the server, and none is planned
  here.
- **It does not verify a program.** It checks that what arrived is JSON, that it
  is an object carrying a source stamp, and that the stamp matches the source
  saved with it. Whether the program is well formed, whether its instructions
  are consistent, whether it is the canonical encoding: all of that is the
  engine's work, done at load.
- **It does not run anything.** Saving a script starts nothing, schedules
  nothing and places no order. Storage is storage. Running a saved script is a
  separate act on a separate surface, and
  [Running one as a strategy](#running-one-as-a-strategy) is where it is
  described.

### Sizes

A source is refused above 256 kB and a program above 512 kB. A program is
several times the size of the source it came from, because the instruction list,
the constant pool and the debug table are all written out: measured on real
scripts, a 3 kB source compiles to 8 kB and a 5.4 kB one to 14 kB. The two
travel in one request, and the pair is sized to fit under the request limit the
smallest deployment leaves at its default.

## The routes that store a script

All five require a logged-in session. They are under the path the web server
already proxies, so a hosted install needs no configuration change.

| Method and path | Does |
| --- | --- |
| `GET /openscript/index.json` | Lists your scripts with the size, modification time and whether a compiled program is stored for each |
| `GET /openscript/<name>.oscript` | Returns one script as plain text |
| `GET /openscript/program/<name>.oscript` | Returns the compiled program stored beside that script, as JSON, byte for byte as it was stored |
| `POST /openscript/<name>.oscript` | Creates or replaces one, from a JSON body carrying `source` and optionally `program` |
| `DELETE /openscript/<name>.oscript` | Removes one, its backup, and its compiled program |

The save body is `{"source": "...", "program": "..."}`. `program` is the
canonical text of the compiled program and may be left out or sent as null,
which saves the script on its own and removes any program stored for it. A save
that carries a program built from different text is refused and changes nothing.
Asking for the program of a script that has none says so in a sentence rather
than answering with an empty body.

A save keeps a `.bak` beside the script holding what was there before, because
the browser editor is the only copy. The compiled program gets no backup: it is
not a copy of anything anybody wrote, it is derived from the source, and the
source is what is kept. The write is atomic: a save that is interrupted leaves
the previous script whole rather than half of the new one.

## Running one as a strategy

Saving a script starts nothing. A script that has compiled is also something the
server can run on its own, in a process of its own, against a live feed, placing
orders the way every hosted strategy places them. That is the runner, and it is
under `/openscript/runner`.

A run is one script, one instrument, one process. It writes a log, it can be
stopped, and it can be given times to start and stop by itself. It outlives the
request that started it, which is the fact the rest of this section follows
from.

### Before it can start: what it runs on

A start carries nothing. What a script runs on is saved against that script, and
the run reads it when it begins:

| Field | Means |
| --- | --- |
| `symbol` | The instrument, in the platform's own symbol format |
| `exchange` | The exchange that instrument trades on |
| `interval` | The bar interval, for example `5m` |
| `product` | Optional. `CNC`, `NRML` or `MIS`. Left empty, the script's own declaration decides |

Saved settings live in `strategies/openscript_run_configs.json`, beside the
Python strategy host's own configuration file and inside the same folder a
container install keeps on a named volume, so what you set survives a rebuild
and an upgrade leaves it alone. The write goes through a temporary file and a
rename, so an interrupted save leaves the previous settings whole.

**A script with nothing saved against it is refused by name.** The refusal names
the script and says which of the instrument, the exchange and the interval is
missing, and nothing is started. This is deliberate and it is the reason the
start route takes no body at all: if a start could carry the instrument, a run
started from a page and a run started by a schedule could differ by one typed
character, and the difference would first be visible as an order on something
nobody meant to trade. A body carrying anything is refused rather than ignored,
because a caller that believes it asked for something and was silently not given
it is worse off than one that was told no.

### Starting answers with an identifier, never an outcome

A start replies at once with the identity of the run: its id, the file, the
instrument, the exchange, the interval, the product, the process id, the time it
started and the log it is writing to. Nothing in that reply says what the
strategy did, because at the moment it is written the strategy has not done
anything yet.

That is a property of the deployment rather than a preference. A request has a
few minutes before the web server gives up on it and the response is buffered on
the way back, so a route that waited for a run to finish would time out with the
strategy still on the market and the operator told nothing about it. The two
things to do next are both on this page: read the status route, and read the
log.

### The runner routes

All of them need a logged-in session, and all of them name a script the way the
source routes name one.

| Method and path | Does |
| --- | --- |
| `POST /openscript/runner/start/<name>.oscript` | Starts it and answers with the identity of the run. Refused when there is no such script, no compiled program beside it, no run settings saved, or it is already running |
| `POST /openscript/runner/stop/<name>.oscript` | Stops the run and reaps its process. A script that is not running is told so and is never told it was stopped |
| `GET /openscript/runner/status` | Everything running, everything scheduled, what every script is run on, and the folder logs are written to |
| `GET /openscript/runner/status/<name>.oscript` | The same for one script, plus the names of the recent logs it has written |
| `GET /openscript/runner/config` | What every script with settings saved is run on, and the products this platform sends |
| `GET /openscript/runner/config/<name>.oscript` | What one script is run on |
| `POST /openscript/runner/config/<name>.oscript` | Saves that, from a body carrying `symbol`, `exchange`, `interval` and optionally `product` |
| `DELETE /openscript/runner/config/<name>.oscript` | Forgets it. A run already started is not touched, since that run is the one on the market |
| `POST /openscript/runner/schedule/<name>.oscript` | Sets the times it starts and stops, from a body carrying `start_time`, optionally `stop_time`, and optionally `days` |
| `DELETE /openscript/runner/schedule/<name>.oscript` | Removes the schedule. Nothing running is touched |

The settings body refuses a field it does not know, by name, rather than
dropping it. Schedule times are 24 hour `HH:MM` in IST and days are the three
letter names; with no days given a schedule runs Monday to Friday. A schedule
carries no exchange of its own: the calendar it checks is the one the script's
own run settings name, so a venue is typed in one place and not two that can
disagree.

### Where the logs go

`log/strategies/`, the same folder every hosted strategy writes into. There is
one file per run, named `openscript_<name>_<date>_<time>_IST.log`, where
`<name>` is the script without its extension. Everything the run prints, on both
of its output streams, goes there; the first line records when it started. On a
container install `log/` is a named volume, so the logs of a run survive a
rebuild.

The status route names the folder and the recent log files for a script, and the
strategy log viewer reads them, because the runner deliberately writes where the
Python strategy host already writes rather than inventing a second place an
operator has to know about.

### Where the orders go, and the one thing this surface does not offer

A run places orders through this platform's own order API with the platform's
own key, exactly as a hosted Python strategy does. That path reads the
platform-wide analyzer setting before anything else, so **sandbox mode and
analyzer mode are honoured by the same code that honours them everywhere else**.
An engine reports what a script asked for; it never reaches a broker itself.

There is no route, field or flag anywhere on this surface that chooses a
destination, and a settings body that invents one is refused by name. Where an
order goes is one question with one answer, decided in the platform's own
setting, and a second switch here would be a second answer to it.

### What actually runs

`openscript_host/openscript_runner.py`, a program that ships with the platform.
It is deliberately not under `strategies/`: that folder is a named volume on a
container install, a named volume is seeded from the image only while it is
empty, and a platform file put there would reach a brand new install and no
existing one. An install that still has it in the old place keeps working and
says so in the log on every start.

Schedules go on the one scheduler this platform runs, the Python strategy host's
own, with job identifiers prefixed so they cannot collide with a strategy that
happens to share a name. They are stored in
`strategies/openscript_runner_schedules.json` and put back on the scheduler at
startup.

## The language itself

OpenScript is developed as its own open source project so that other platforms
can adopt it, under Apache-2.0, with a written specification and a conformance
suite. The language reference, the error catalogue and the integration guides
live there rather than being restated here.

## Where a run's orders go, and what happens if that changes

A strategy run sends its orders through the platform's own order path, the same
one every other surface uses, so sandbox mode and analyzer mode are honoured
without this runner knowing anything about them. It does **not** pass
`force_live`.

That is a deliberate decision and it has a consequence worth stating plainly.
The destination is decided per order and not per run, so an operator who turns
the analyzer on while a strategy is holding a position would send that
strategy's exits to the sandbox while the broker still holds what its entries
opened. The platform describes this failure in its own words in
`services/place_order_service.py`.

So the run watches for it. The destination of the first order the platform
accepts is remembered, every later order is checked against it, and a run whose
destination changes underneath it **stops immediately** and says so in its log,
naming what is open. It does not try to put the position back: the entry is
where it is, and a run that can no longer reason about what it holds should not
be sending anything. Whatever is open at that point has to be checked and closed
by a person.

A run that stays where it started is never interrupted by this.
