# OpenScript on the charting terminal

OpenScript is an open trading language. You write a study once, plot it on the
`/trading` chart, and backtest or deploy a strategy from the same file.

It is not a replacement for the custom indicators described in
[custom-indicators.md](custom-indicators.md). The two sit side by side and are
meant for different people. The difference that matters is below, and it is
worth reading before you choose between them.

## Writing one

Open the chart at `/trading`, choose **Scripts** on the right rail, and select
**New script**. Choose Study or Strategy to start from its working template.

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
- **Add to chart** puts a study on the focused chart. For a strategy, **Run on chart** opens its backtest and draws its plots and historical fills. Both require the saved source to compile; neither starts a server deployment.
- **Ctrl+S** saves, so the browser does not open its own save dialog over the
  panel.

Colours come from the language's own lexer, which is the same one the compiler
runs. A word added to the language is coloured the day it lexes, because nothing
here keeps a second list of what the keywords are.

The editor has syntax colours, a line-number gutter, compiler diagnostics, Tab/Shift+Tab indentation and Ctrl+S saving. Unsaved drafts stay per script in this browser when you switch scripts or panels; discard is a separate action. Save to persist source on the server before backtesting or deploying it.

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
the instruction set gives it: market data, calculations, drawings and, for a strategy, order instructions.
There is no way to spell a network call, a file, or a reach into the page,
because those names do not exist in the language. Nothing was handed over, so
there is nothing to escape from.

Two consequences worth knowing:

- **A study cannot use arbitrary browser or server APIs.** It can still draw misleading values. A strategy can issue order instructions when you explicitly deploy and start it, including live orders in Live mode, so review its trading logic and sizing before running it. OpenScript has no general network/file API for sending your positions elsewhere.
- **It needs no change to the security policy.** OpenAlgo serves pages with
  scripts restricted to its own origin and no permission to build code out of
  text. A language that compiled to JavaScript would need that permission
  turned on for every page in the platform. This one does not, and that is the
  reason the compiled program is data rather than code.

The sources are served as plain text and never as JavaScript, deliberately, so
that the page cannot import one even by mistake. The compiled program is held to
the same rule and it is the harder half, because a program is the thing that
is handed to an engine: it is stored as data under a name ending
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

### What saving does not do

Said plainly, because a contract is worth less than nothing if a reader assumes
more of it than it promises.

- **It does not compile.** No compiler runs on the server, and none is planned
  here.
- **It does not verify a program.** It checks that what arrived is JSON, that it
  is an object carrying a source stamp, and that the stamp matches the source
  saved with it. Whether the program is well formed, whether its instructions
  are consistent, whether it is the canonical encoding: all of that is the
  engine's work, done at load.
- **Saving does not run anything.** Saving a script starts nothing, schedules
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

## Backtesting on the Chart

Save a compiling Strategy, then choose **Run on chart** in Scripts or open **Backtest** on the right rail and choose the file. A study is not an order-generating strategy.

The run uses the selected chart's instrument and interval with historical bars. Choose From/To dates, set the script's inputs or leave them blank for its defaults, and choose **Run backtest** after changing dates or inputs. Selecting a strategy, changing the charted instrument or changing its interval can run the test automatically.

Results include the summary, equity, drawdown and trades. **Show trades on chart** controls fill markers, and **Clear marks** removes them. Markers also leave when their strategy is removed from the chart. These are historical engine results: the browser backtest sends no orders to a broker and does not start a server run. Backtest inputs do not change a deployment's saved inputs.

## Running one as a strategy

A deployment is a saved strategy, instrument, exchange and interval, with an optional product and input overrides. The same script can have several deployments on different instruments or intervals, each with its own run, attributed orders, trades, positions and log. A second deployment on the same script/instrument/interval is refused.

### Deploy and Start

1. Open **Strategies** on `/trading`'s right rail and choose **Deploy a strategy**.
2. Choose a saved, compiling Strategy. Pick the instrument from the symbol master, its exchange, an available interval and the product where needed (`CNC`, `NRML` or `MIS`).
3. Set the script's inputs, or leave them empty to use its defaults, then choose **Deploy** to save the settings. Saving settings does not start a process.
4. Check the panel's **Live/Analyzer** badge. Choose **Start live** or **Start in sandbox**, as the current platform mode requires.
5. Read the status, Activity books and log. A start response identifies a process; it is not a trade result or proof that the process remained running.

The instrument and interval are part of a deployment's identity. Changing either creates another deployment; it does not move a running strategy to a new instrument. Inputs are read when the process starts. Pause or stop, save the intended changes, and start again to apply them.

The current server runner sizes orders from units or lots, using known contract metadata; money-based and percent-of-equity sizing are refused. It sends whole-unit order quantities, so a fractional quantity that another API path accepts is not automatically supported here. Read startup refusals in the log.

A server run outlives the browser tab. Closing `/trading` does not stop it. Its orders use OpenAlgo's own order path and key; it does not bypass order-mode checks or choose a destination independently of the platform's Live/Analyze setting.

### Pause and Stop Have Different Effects

| Control | Effect |
|---|---|
| Pause | Ends the process and leaves its position for you to manage |
| Stop | Asks the run to cancel its outstanding orders, close its own position, then end; asks for confirmation |
| Start live / Start in sandbox | Starts a stopped deployment with its saved settings, in the platform's current mode |
| Activity | Opens that deployment's order book, trade book and positions |
| Remove | Removes a stopped deployment's settings and schedule; does not close a broker position |

Read any close refusal carefully. A failed close can leave the strategy running and holding, or a terminated process can leave a close unconfirmed. Verify actual orders and positions rather than assuming a stopped process means a flat account. A scheduled stop uses the pause behavior and does not itself close a position.

### Settings, Schedules and Logs

Settings live in `strategies/openscript_run_configs.json`. Schedules live in `strategies/openscript_runner_schedules.json` and are restored on the Python strategy host's shared scheduler at startup. On Docker these files are inside the strategies volume.

Schedule times are 24-hour `HH:MM` in IST; `days` uses three-letter names and defaults to Monday through Friday. Start is required and stop is optional. A supplied stop must be later than start. The calendar is the exchange saved in the deployment's settings. Removing a schedule does not pause or close a running strategy.

Per-run logs live under `log/strategies/`. The runner's status response identifies its log directory and recent log files. Deployment IDs, rather than script names alone, identify runs and attribute their books.

### Runner Routes

These are authenticated browser-session routes under `/openscript/runner`, not public API-key routes under `/api/v1`. Mutations require CSRF protection. Use the returned deployment ID for lifecycle calls. A script filename is accepted for compatibility only when it resolves unambiguously to one deployment.

| Method and path | Purpose |
|---|---|
| `POST /config/<name>.oscript` | Create a deployment with `symbol`, `exchange`, `interval`, optional `product` and `inputs`; include `deployment` to edit that deployment |
| `GET /config` | List deployment settings |
| `GET /config/<deployment>` | Read one deployment's settings |
| `DELETE /config/<deployment>` | Remove a stopped deployment's settings and schedule |
| `POST /start/<deployment>` | Start from saved settings; no request-body options; responds `202` with run identity |
| `POST /pause/<deployment>` | End the process and leave its position |
| `POST /stop/<deployment>` | Compatibility alias for **pause**, not a position close |
| `POST /close/<deployment>` | Close and stop; the UI's confirmed Stop calls this |
| `GET /status` or `GET /status/<deployment>` | Read runs, settings, schedules and log information |
| `POST /schedule/<deployment>` | Save `start_time`, optional `stop_time` and `days` |
| `DELETE /schedule/<deployment>` | Remove a schedule without touching a running process |
| `GET /orderbook/<deployment>` | Deployment's attributed orders |
| `GET /tradebook/<deployment>` | Deployment's attributed trades |
| `GET /positions/<deployment>` | Deployment's attributed positions |
| `GET /instruments?q=<query>&exchange=<exchange>` | Search the symbol master |
| `GET /intervals` | Read the active broker's interval choices |

Unknown settings fields are refused. There is no `mode`, destination or `force_live` setting on this surface. The runner process ships at `openscript_host/openscript_runner.py`; it is separate from user files in the strategies volume.

## Where a run's orders go, and what happens if that changes

The platform-wide analyzer setting decides the destination of each order. Live mode can send real broker orders; Analyze uses the sandbox. The runner does not pass `force_live`. Rehearse in Analyze and reconcile positions before changing mode.

The runner remembers the destination of accepted orders. If it detects a destination change while holding a position, it stops and records what must be checked manually. If it was flat, it can follow the new destination. This safeguard does not move or close the old position, and a response can already have arrived from the changed destination when the difference is detected. Check both books and the broker terminal.

Broker switching is refused while relevant live automation, including Live OpenScript runs, is still running. See [Broker Connection](userguide/06-broker-connection/README.md). Pausing or logging out is not an instruction to close a position.

## The language itself

OpenScript is developed separately from the platform under Apache-2.0. The installed language and engine versions must agree on the compiled program format; a program that an engine cannot load is refused in its log. Use the [charting guide](userguide/32-charting-terminal/README.md) for terminal workflows and the language's bundled reference when writing a study or strategy.
