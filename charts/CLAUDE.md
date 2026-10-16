# CLAUDE.md

Guidance for Claude Code working in openalgo-charts. This file carries what is **not
discoverable by reading the code**: conventions, invariants, and the standard any UI built
against this engine is held to. Structure and commands are discoverable, read them from
the repo.

## What this project is

A from-scratch, dependency-free HTML5 canvas charting engine. Nine lazy ESM tiers (base,
trade, transform, profile, indicators, draw, webgl, workspace, widget), zero runtime dependencies,
enforced Brotli budgets. It is a **general library that ships an Indian default**, not an Indian library:
IST is the default timezone, never an assumption baked into behaviour.

**The engine ships no DOM.** The base and the seven other DOM-free tiers contain no toolbar,
dialog, menu or picker; those live in the host. `openalgo-charts/widget` is the one tier
that does ship them: a packaged host that drives the engine only through its public API,
kept out of every other bundle by the ESLint tier ACL and `npm run shake`. The yfinance
demo (`examples/yfinance/index.html`) is the reference host and the place to prove a
feature is usable, not just present.

## Writing rules

- Keep comparison brands out of source code, tests and comments. Describe behavior
  with generic terms; keep comparative research outside this repository.
- No emoji or icons anywhere: code, comments, log messages, commit messages, docs, tests,
  or terminal output. Plain text labels only.
- No em dashes or en dashes anywhere. Use a comma, colon, parentheses or a full stop. A
  plain hyphen inside a compound word like read-only is fine.
- Comments explain **why**, not what. Match the density and voice of the surrounding file.
- Conventional Commits.

## UI standard for host chrome

**Borrow the craft, not the design.** Professional terminals set the bar for density,
crispness and finish, and that bar is the one to clear. They do not set the layout, the
grouping, or the words. Do not reproduce another product's tab taxonomy, its panel
arrangement, or its label phrasing: openalgo-charts has its own identity and copying
someone else's chrome forfeits it, quite apart from being someone else's work.

Standard domain vocabulary is shared property and should be used plainly: logarithmic,
percent, indexed to 100, precision, timezone, invert. Product-specific phrasings are not,
and neither is a particular way of carving settings into tabs. Where a competitor's label
is the obvious industry term, use it. Where it is their turn of phrase, write our own.

The rest of this section is about craft, and applies whatever the layout ends up being.
Each rule is written down because it was got wrong once:

**Scrollbars.** Never leave a default scrollbar on a dark surface. A white OS scrollbar
against a dark panel is the single most obvious tell that a UI was not finished. Style
`::-webkit-scrollbar` (track, thumb, thumb:hover) and set `scrollbar-color` and
`scrollbar-width: thin` for Firefox. The thumb belongs a step lighter than the panel, not
white, and the track should read as part of the panel.

**Colour controls are small square swatches, not blocks.** A colour input is roughly a
26 to 28 px rounded square. It is NOT a full-width bar: a 140 px colour block is a bug,
not a style choice. `.swatch` already exists at 20 px with a 5 px radius; reuse that
vocabulary rather than inventing a second one.

**Up and down colours share one row.** A property with a bullish and a bearish colour is
one labelled row carrying its checkbox and both swatches side by side:

    [x] Body      [green] [red]
    [x] Borders   [green] [red]
    [x] Wick      [green] [red]

Not a BODY section header followed by separate Up and Down rows. The stacked form triples
the height of every panel and is what forces a scrollbar to appear at all. The settings
schema must therefore be able to express a **paired colour control**, not only single
colours, or the host cannot render this shape.

**Controls are crisp and compact.** Prefer a dense panel that fits without scrolling over
a roomy one that does not. Section headers are small, uppercase and muted. Rows are tight.

**No browser-default form controls on a dark panel.** A native blue checkbox and a native
`<select>` chevron both break the theme. Style checkboxes (dark fill, subtle border, a
clear tick when checked) and selects (panel background, custom chevron, no OS styling).

**Tab lists carry icons.** A settings dialog's left rail pairs each tab with a small
glyph. The demo has an inline SVG icon helper; use it rather than an icon font.

**Dialog furniture.** Title left, close affordance top right, actions bottom right with
the confirming action last, and any secondary control (a template picker) bottom left.

## Shipping a change: every surface that repeats a fact

The same handful of facts (tier count, tier sizes, indicator count, tool count,
chart-type count, test count) is written out by hand in eight places. There is no
single source for them, so a release that updates one and not the rest leaves the
project contradicting itself. That is not hypothetical: the architecture diagram
advertised "under 50 KB" and four tiers for several releases while the base engine
measured 59 KB across six, the site footer said "under 30 KB", the API reference
omitted the two largest tiers outright, and the skills carried seven sections still
marked "(unreleased)" for features that had shipped.

**Never quote these numbers from memory or from another doc.** Measure them:

```sh
npm run size              # tier sizes, Brotli, enforced in CI
npm test                  # test and file counts
npm run skills:coverage   # every export named in .github/skills
node -e "import('./dist/openalgo-charts.mjs').then(m=>console.log(m.registeredIndicators().length, m.registeredChartTypes().length))"
```

Counts come from the registry at runtime, never from a config label. `.size-limit.json`
called the draw tier 34 tools while `registeredDrawingTools()` returned 43.

### What to update, by kind of change

| Changed | Also update |
| --- | --- |
| Any public export added or removed | `.github/skills/openalgo-charts/references/` (the matching file), then `npm run skills:coverage` |
| A new type appearing in a public signature | Export it from its tier entry point, or `npx typedoc` warns and the reference has a dead link |
| A **new tier** | `typedoc.json` `entryPoints`, `.size-limit.json`, `package.json` exports, README tier table, `ARCHITECTURE.md` section 2, website Getting Started, the architecture diagram |
| Indicators, chart types or drawing tools | Their counts in README, `pages/index.mdx` and `theme.config.tsx` meta descriptions, `components/landing.tsx` stats and feature cards, the diagram |
| Anything that moves a bundle size | README badge and both size tables, `components/landing.tsx` `STATS` (home page sizes), website Getting Started, `theme.config.tsx` footer and meta description, the diagram subtitle and tier legend |
| A new descriptor hook or capability | `references/indicators.md`, the website docs page, a live example in `website/pages/examples.mdx` |
| A release | `CHANGELOG.md`, `website/pages/docs/release-notes.mdx`, drop every "(unreleased)" marker for what just shipped, and the release benchmark (`npm run bench:release`: `benchmarks/releases.json`, `website/pages/benchmarks.mdx` and the home page's `BENCH` in `components/landing.tsx`) |

### Before every npm publish

**Do this before the commit, not after the publish.** Once a version is on the
registry the docs shipped with it are wrong for good, and a follow-up commit
does not change what a reader of that release sees. Every item is mandatory:

1. `package.json` and `src/version.ts` carry the new version, and they agree.
2. `CHANGELOG.md` has the entry.
3. `website/pages/docs/release-notes.mdx` has the entry, and the website builds.
4. `README.md`: the version line, the test and file counts, and **both size
   tables**.
5. **The bundle sizes, measured on the build that is about to ship.**
6. `examples/yfinance/` still describes what it does. It is the reference host,
   so a count or a claim that has drifted there is a claim the first-time reader
   meets first.
7. `.github/skills/` for anything a downstream author would now do differently.
8. `npm run verify`, then the registry counts, then `npm run skills:coverage`.
9. **The release benchmark, measured on the build that is about to ship.**
   After the version bump and the final build, on the reference machine with
   nothing else running, `npm run bench:release` rebuilds the previous release
   from its tag, runs the render bench five times on each build in one
   session, and writes the version's entry into `benchmarks/releases.json` and
   the website's Benchmarks page. Commit both with the release, and link the
   entry from the release notes (`/benchmarks#<version without dots>`).
   `tests/release-benchmarks.test.ts` fails a package version with no entry,
   and CI fails when the page and the data disagree.

**A benchmark is measured, never carried over.** Like a size, it belongs to the
build that ships and to the machine and session that timed it. Never copy an
earlier entry's figures, never compare an entry with another entry measured on
another machine or day, and never run it while agents, test suites or a browser
session share the machine: load only adds time, and the previous release is
timed again in the same session precisely so that both columns share one set of
conditions. A run of the new build that fails its render bench budgets stops the
script; that is a regression to fix, not a figure to publish.

**Measure the sizes last, and substitute them by row label.** They move by
hundredths whenever the bundle changes at all, including from the version string
itself, so a figure copied from the previous release is already wrong. Worse, a
`sed` keyed on the *old* number silently does nothing once that number has
drifted, and reports success: the README's base-engine row sat two releases stale
exactly that way, through three "successful" release runs. Read `npm run size`,
match on the row name, and fail loudly when a row cannot be found.

### Release process for every new version

Apply this process to patch, minor and major releases. A version number alone does
not reduce the testing needed for changes to loading, drawing, replay or trading.

1. Record the approved scope and source commit. Use an isolated checkout when the
   shared workspace has unrelated work. Keep comparative audits and raw validation
   artifacts outside the repository; keep reusable regression tests in it.
2. Reproduce each defect before fixing it. Cover cancellation, context changes,
   teardown and replay when changing feed ownership. A drawing beyond the latest
   candle must remain visible inside the plot and clipped at every price axis.
3. Test the built candidate in real Chromium, Firefox and WebKit for the affected
   interactions. Inspect screenshots as well as assertions. Record browser or
   device limitations explicitly; synthetic traffic is not a live-broker test.
4. When a public contract affects OpenAlgo, install the packed candidate in an
   isolated consumer checkout. Run its trading tests, typecheck, production build
   and actual `/trading` browser harness. Preserve order authority, quantity units,
   exchange timestamps, session bucketing, volume accounting and replay guards.
   A dependency upgrade cannot substitute for a required consumer migration.
   For a minor or major release, run this as a dry run even when OpenAlgo is not
   upgrading in the same cycle, from the version it pins today, and report what its
   migration will meet. Commit and push nothing to OpenAlgo for a dry run.
5. Update package and lockfile versions, `src/version.ts`, changelog, website release
   notes, current-version references, examples, API docs and skills. Follow the
   measured-facts checklist above; preserve historical release facts. Run the full
   package verification, skills coverage, API generation without warnings and the
   website build before committing. Run `npm run bench:release` last, on an idle
   machine, and commit the benchmark entry and page with the release.
6. Review the final diff and commit using Conventional Commits. Push and wait for
   required CI. Publish only within the user's existing authorization; do not ask
   again when the user has already authorized this release. Otherwise prepare the
   tested candidate and release notes before seeking publication approval.
7. Push the matching immutable version tag, then manually dispatch the existing
   Release workflow with that tag for npm trusted publishing and provenance. A tag
   push alone does not publish. Create the GitHub release with the matching changelog
   after npm succeeds. Use the website deployment workflow for Pages. Do not move a published tag or reuse an npm
   version; a correction after publication requires a new version.
8. Wait for the release and Pages workflows to succeed. Download the registry
   tarball and compare every packaged file to the tested candidate. Verify package,
   source, runtime, tag and release versions agree, including npm integrity and
   provenance. Open the deployed website under `/openalgo-charts`, check assets and
   the changed interactive examples, and inspect actual browser pixels.
9. If a companion OpenAlgo change is in scope, install the published package, update
   its lockfile, rerun affected checks, then commit and push that consumer change.
   Report release links, commit IDs, validation and any remaining limitations.

### Release order that avoids measuring twice (learned on 2.6.3)

2.6.3 measured its sizes, benchmark and consumer harness three times, because every
fix after a measurement throws the measurement away. Order the work so the expensive,
measured steps run once, on code nobody will touch again:

1. **Fix, then get reviewed, then measure.** Push the candidate early and let the PR
   reviewer bot (it posts within about five minutes) and CI run on it. Fix what they
   find. Only when the code is final, measure sizes, run `npm run bench:release` and
   the OpenAlgo harness. A review fix that lands after measuring, even a one-line
   guard, moves the Brotli sizes and invalidates the benchmark.
2. **Run `npm run verify` after the last source edit, not before it.** A size table
   checked at 20:21 and source edited at 20:41 shipped a 123 byte overrun to CI.
   Compare timestamps: every log and figure must postdate the newest file in `src`.
3. **Run `npm test` after any docs edit, too.** `tests/docs-claims.test.ts` reads any
   `<number> ms` in ARCHITECTURE.md and the docs as a performance claim that needs a
   measurement record. Name a tuning constant (`ZOOM_CHASE_TAU`), do not quote it.
4. **CI timing.** The Playwright smoke job takes about 30 minutes; the rest about 10.
   Start it as early as possible and do docs work while it runs.

Tests and gates that tripped:

- **Function caps** (`scripts/function-caps.json`): one added line put
  `WidgetImpl.constructor` over its cap. Extract a method, then lower the cap to the
  new measured length (temporarily set the cap to 1 and read the failure to measure).
- **Saved documents** (`tests/saved-documents.test.ts`): any change to what a restore
  writes back must be named in `CHANGES`, for both the direct and the `widget-storage`
  (prefixed `oac-widget:compat:state.`) entries.
- **A migration must cover every restore path.** The widget restores through
  `restoreWidgetState` and, on a reload with `persist`, through `applySavedLayout`.
  A fix on one path only passed every test until a reload test was written.

Figures and substitutions:

- **Substitute sizes in one pass with a lookup table.** Values chain (an old budget
  becomes the new measured size) and one old value can split in two (a budget and its
  measured size that were equal now differ). Sequential `sed` gets both wrong. Fail
  on any file the script did not change.
- **Brotli moves in steps.** A 10 byte source change moved the classic scripts by up
  to 95 bytes and the chart-only import by 57. Respelling code to save bytes needs
  every row measured: one spelling saved 6 bytes in the shake and cost 100 in the
  base engine.
- **`bench:release` does not write the home page.** Set `BENCH` in
  `website/components/landing.tsx` from the new entry by hand: Canvas 2D at 200,000
  bars, the lowest p95 of each metric.
- **The bench runs five passes of the new build, then five of the old.** On the
  reference machine the tick cells swing by up to a fifth between sessions in either
  direction, so one slower cell is not yet a regression. Before calling one, re-time
  that cell with the two builds alternating (`OAC_RENDER_BENCH_DIST=dist` and
  `dist-baseline` with `scripts/render-bench.mjs`, about twelve passes), and report
  both in the release notes.
- The test count lives in the README badge, the README `npm test` line and the
  CHANGELOG Tests paragraph. A new regression test changes all three.
- **The version is also hand-written** in the website footer (`website/theme.config.tsx`,
  with its release-notes anchor), the diagram titles and version label, and the
  `STATS` and `BENCH` release fields in `components/landing.tsx`. A grep for the old
  version that skips the changelog and release notes finds them all.
- **A release that leaves the base untouched still moves its size.** 2.6.4 changed
  only the profile tier, yet the base measured 33 bytes more from the version string
  alone. Confirm such a claim by diffing each bundle against the previous registry
  tarball with the version string replaced, then publish the measured figure anyway.
- **Write edit scripts with the Write tool, not a shell heredoc.** The heredoc
  collapsed `\\|` in a markdown table to `\|`, so the script matched nothing.
- **Comparing the registry tarball:** every file matches a local `npm pack` byte for
  byte except `dist/index.d.ts`, whose declaration blocks the bundler orders
  differently on Windows than on the Linux runner that publishes. Compare that one
  file by its sorted lines; the published order matches the previous release's.

OpenAlgo dry run:

- The harness is this repo's runner, not OpenAlgo's: `node scripts/check-openalgo-compat.mjs
  --frontend <worktree>/frontend --browser <chromium|firefox|webkit> --navigation true`
  runs 14 checks. Without `--navigation true` it runs 13 and skips the wheel and
  trackpad check.
- The runner needs a linked git worktree (`git -C <openalgo> worktree add`) with
  copied, not linked, `node_modules`: about 7.7 GB. Put it on a drive with room. A
  full system drive stops every tool, including the one that would delete it.
  Remove it with `git worktree remove --force`, then `Remove-Item` with the `\\?\`
  prefix, because some paths are too long for the plain call.
- OpenAlgo's own extension (`--consumer-checks <abs path>/frontend/scripts/check-trading-workspace.mjs`)
  lags its UI: in October 2026 three of its selectors (the `percent` scale value,
  the CSV dialog, the replay button's `aria-label`) failed on the pinned release and
  the candidate alike. Run it on the pinned version first, so a stale script is not
  read as a regression. Swapping only `node_modules/openalgo-charts` for the pinned
  tarball is enough for that baseline.
- After a change that touches only the widget tier, hash the bundles OpenAlgo loads
  (`dist/openalgo-charts{,.profile,.indicators,.draw,.transform,.workspace,.webgl,.trade}.mjs`)
  before and after: unchanged bundles keep the harness result valid.
- WebKit reports a fetch cut off by a reload as a page error. The runner allows the
  caught index reads OpenAlgo makes; a new one OpenAlgo adds must be added there.
- The reference host needs data to render a chart. For screenshots serve it with
  `python examples/yfinance/server.py --fixture --port <port>`; `tests/e2e/serve.cjs`
  alone shows no chart.

### The API reference

`typedoc.json` `entryPoints` must list **every** tier. It listed four for a long time,
so `/api/` documented neither the 91 indicators nor the 43 drawing tools. Treat a
typedoc warning as a failure: each one names a type that is reachable from the public
API but has no page, which is a dead link for whoever follows it.

### The architecture diagram

`docs/architecture-diagram.svg`, shown in README and `ARCHITECTURE.md`. It is SVG
precisely so a number can be corrected by editing text; the PNG it replaced drifted
because fixing it meant redrawing it. `docs/openalgo-charts-architecture-diagram-brief.md`
records what each element must say and why.

### The website

`website/` is a separate build. Run `npm run build` there after touching it: a colon in
MDX frontmatter is a YAML parse error and fails the whole site, and the failure does not
show up in the library's own tests.

It deploys under `basePath: '/openalgo-charts'`. Next rewrites `<Link href>` but **not a
raw `src` or `href` in MDX or JSX**, so an asset written `/thing.svg` builds fine, passes
every check, and 404s only on Pages. Spell out `/openalgo-charts/thing.svg`, the way
`LOGO_SRC` does in `components/`. Grep the built `out/` for the emitted path rather than
trusting the source.

Examples are not decoration, they are the proof a feature is usable. An example that
throws is worse than a missing one. Anything overlaid on the chart as HTML must stop
`pointerdown`, or the chart's pointer capture eats the click.

## Keep the code lean

Bloat is debt. Every byte in a tier ships to every host that imports it, and every line
is read by the next person who changes the code. A feature is worth its cost or it does
not ship, so the cost is measured, not guessed:

- **A change reports what it costs.** Brotli bytes per tier (`npx size-limit`) and the
  chart-only import (`npm run shake`) against the previous release, plus the lines it
  adds. Raise a budget only to the measured need, in the release that needs it, never
  with headroom for later.
- **The base engine and the chart-only import carry only what a plain chart needs.** A
  feature a plain chart does not use goes behind an opt-in import, a lazy tier or a
  function the host calls, so a host that never uses it never pays for it.
- **Reuse before adding.** Search for an existing helper, module or pattern first.
  Duplicate logic, an abstraction with one caller, and an option or setting no host
  asked for are rejected in review, the same way a control with nothing behind it is.
- **Delete as well as add.** Dead code, unused exports, superseded helpers and duplicate
  tests leave in the change that makes them dead. A compatibility shim names its removal
  version (COMPATIBILITY.md; `scripts/check-deprecated.mjs` enforces the tag) and is
  removed in that version.
- **A release candidate gets a leanness review** before it ships: growth per feature in
  bytes, lines and public surface, with every proposed cut verified before it is applied.

## Quality gates for every release

Intentions do not survive a busy release, so these are checks, run before every
release candidate is tagged. The ones marked checked at release have no script yet;
turning each into a script is the preferred fix whenever one of them is missed.

- **Compatibility.** Diff every tier's public `.d.ts` against the previous release and
  against the version OpenAlgo pins. A removal or a narrowed type fails the release
  unless it is a deliberate deprecation for the next major. Saved chart state,
  workspaces and layouts written by those versions load and round-trip in tests.
- **Warnings.** Zero lint warnings and zero typedoc warnings.
- **Structure.** No import cycles between modules (`scripts/check-cycles.mjs`, in
  `verify`): no runtime cycle at all (an import whose names are all inline `type`
  counts, since it still loads its module), and the cycles that type imports close
  may not grow: their sizes, largest first, are held in `scripts/import-cycles.json`,
  which is lowered as they shrink. A module has one job and its index is its only
  door; `scripts/line-caps.json` and `scripts/function-caps.json` caps only ever go
  down, so a file or function that outgrows its cap is split, never given a larger cap.
- **Surface.** No unused exports (`scripts/check-unused-exports.mjs`, in `verify`): an
  export of a module under `src` that is not a tier's public export, and that nothing
  in `src` or the tests uses, fails. A test counts as a use; an export used only in its
  own file passes and is counted. `scripts/unused-exports.json` lists the ones the tree
  had when the gate arrived and only shrinks. `npm run skills:coverage` at 100 percent;
  every `@deprecated` names its removal version.
- **Tests.** No skipped test without a written reason beside it (checked at release), and
  a flaky test is fixed or reported with its failure rate, never retried into green.
- **Readability.** Comments say why; names match the vocabulary already in the tier; the
  same thing is done the same way across tiers.

## Testing traps that have already cost real time

**A Chart built without `applySize(w, h)` and a synchronous raf is not measured.** Every
price scale sits on its `0..1` placeholder, so assertions about ranges pass while
comparing zero to zero. Copy the `makeChart` helper in `tests/compare.test.ts`.

**Write the regression test, then revert the fix and watch it fail.** A test that passes
against the old code is worthless. This has caught vacuous tests more than once.

**Green unit tests do not prove a renderer works.** Two shipped defects passed a fully
green suite and were only caught by looking at pixels: `drawColumns` discarded per-bar
colour, and a comparison overlay labelled its axis from the previous frame's range.
Anything that draws needs a real browser check.

**Trace every new option end to end.** Declared, threaded, consumed, and actually changing
output. Options that were stored and persisted but read by nothing, and styles copied into
no renderer, have both shipped here. "Declared but not consumed" is a defect, not a
follow-up.

**Never ship a control with nothing behind it.** A checkbox that does nothing is worse
than an absent one. If a reference terminal has a control this engine cannot back, leave
it out. A control that exists but has no data in the current context is different: render
it disabled with its state visible, the way the reference greys "previous day close" when
there is no previous session.

## Never cache the forming bar

A "forming bar" is the one that has not closed yet. On a 5-minute chart at 10:07, the bar
covering 10:05 to 10:10 is still being built: its close moves with every tick and is not
final until 10:10.

Bars therefore fall into two categories, and they are not the same kind of data:

- **Closed bars are immutable.** Yesterday's daily candle will never change again, and
  neither will the 10:00 to 10:05 bar once 10:05 has passed. Cache these freely.
- **The last bar is alive** until its interval ends. It must never be served from cache.

**A cache that serves a stale forming bar is worse than no cache at all.** Concretely:

    10:07  Open INFY.  Fetch, last bar close 1120.  Cached.
    10:08  Switch to RELIANCE to check something.
    10:09  Switch back to INFY.  Cache hit, last bar close 1120.

INFY actually traded to 1135 while the user was away. That one wrong number then reaches
the last-price line, the price-axis tag, the header LTP, and every indicator computed off
that close: RSI, VWAP, the moving average, a Supertrend flip. With no cache the user waits
600ms and sees 1135, which is slower and correct. With a naive cache they get an instant
chart that is confidently wrong, with no spinner and no staleness badge to warn them.

This library draws Buy and Sell buttons on the chart. A fast wrong price is a worse
failure here than a slow right one.

So the rule is not "cache less". Keep the completed history and re-fetch only the tail,
either by dropping the last bar from a cached set or by expiring the entry at that bar's
close time. Anything that computes off `bars[bars.length - 1]` inherits this rule.

## Concurrency

When fanning out agents over this repo, **file ownership must be exclusive**, and
`src/core/chart.ts` and `src/core/pane.ts` need a single writer per run. Working-tree
corruption here comes from parallel agents, not from any other process. Since 2.5.7 the
chart's logic lives in `src/core/chart-*.ts` collaborators (ARCHITECTURE.md, Chart
internals): different agents may own different collaborator files in one run, provided
only one of them edits `chart.ts` itself, where the host interfaces meet.

## Timezone

IST (`Asia/Kolkata`) is the default and must stay byte-identical for a caller who
configures nothing. Everything else is configurable by IANA zone name. Use IANA names,
never fixed offsets: a fixed offset is silently wrong for half the year anywhere that
observes DST, which is the same class of defect as the IST session anchor fixed in 1.2.0.

`src/feed/openalgo-rest.ts` is the exception and is correct as it stands: OpenAlgo's
history API genuinely requires IST date strings, so that adapter converts at the edge.
