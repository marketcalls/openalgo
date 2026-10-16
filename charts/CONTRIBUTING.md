# Contributing to OpenAlgo Charts

Report reproducible problems, improve examples and documentation, or send focused code
changes. Use the existing public API and repository conventions as the starting point.
Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

Follow [compatibility and maintenance](COMPATIBILITY.md) for public API changes,
deprecation, persistence migrations, host boundaries and release evidence.

## Set up a checkout

Use an active LTS Node.js release satisfying the package's Node.js `>=20` engine,
and npm. From the repository root:

```sh
npm ci
npm run build
```

`npm run build:watch` rebuilds the library while editing. Website dependencies are
installed separately with `npm --prefix website ci`. Use synthetic fixtures for local
feed tests; keep credentials and recorded account data out of commits.

## Choose the relevant checks

For library or reference-demo code, run the complete local gate:

```sh
npm run verify
```

This runs lint, TypeScript, the import-cycle and unused-export gates, unit tests, the
library build, demo tests, declaration checks, the compatibility gate, bundle budgets
and tree-shaking checks. Run a focused test while developing, for example
`npx vitest run tests/navigation-settings.test.ts`.

TypeScript runs twice, and `npm run typecheck` runs both. `tsconfig.json` compiles
`src`, the code that ships, with `strict` and two more flags:
`noUncheckedIndexedAccess` (an index read may be `undefined`) and
`exactOptionalPropertyTypes` (an optional property that is absent is not one set to
`undefined`). `tests/tsconfig.json` compiles the tests without those two. A test reads
back by index the bars, rows and calls it built itself, on almost every line, and a
read that misses already fails the test when it runs, so asserting each read would add
thousands of `!` that catch nothing. That file says the same, and
`tests/typecheck-config.test.ts` keeps it to exactly those two flags. Editors pick the
configuration by folder, so a test gets the tests' and a source file the stricter one.

In `src`, prefer a fix that shows the compiler what the code already guarantees (a
checked index, a narrowed local, an optional property typed `| undefined` where
`undefined` is written) over a non-null assertion. Widen only a type the host writes:
one the library also hands back, such as `ChartDataContext`, stays exact, since a host
that forwards it into an exact type of its own would stop compiling. A literal that
writes `undefined` into such a type is written `{ ... } satisfies LooseOptional<T> as T`
(`src/helpers/types.ts`), which still checks every member against `T` where a bare
`as T` would not. A built-in drawing tool ends in `satisfies AnchoredTool<N>`
(`src/draw/types.ts`), which hands its body the anchors the layer guarantees for
`points: N`, so it reads them without one. Indicator maths and the renderers read
series by index inside loops whose bounds hold the index, which no type can state;
those reads carry `!`, with the bound said once per block. A read that nothing bounds
is not asserted: it is a defect, and it is fixed with a test first. `npm run check:dts`
compiles a host against the built declarations with both flags and without
`skipLibCheck`, so the published types hold for a host that is as strict.

Write regression tests around observable behavior and realistic inputs. A bug test
should fail against the original behavior; avoid assertions that merely repeat the
implementation. Rendering and gesture changes also need a real browser check and
inspection of the resulting pixels. Trace new options through their effect on output.

```sh
npx playwright install chromium
npm run e2e
```

Build the library first. Playwright starts its fixture servers; the yfinance browser
scenario requires Python 3 and reports a skip when it is unavailable. Optional visual
parity checks compare against `dist-baseline/`: run `npm run baseline -- HEAD~1`, replacing
`HEAD~1` with a suitable known-good ref, then run the browser suite. Inspect intentional
visual changes before accepting a new comparison point.

For indicator performance or allocation changes, use `npm run bench` or `npm run soak`
as appropriate. [CI](.github/workflows/ci.yml) also checks skill coverage, browser
behavior, documentation builds and supply-chain constraints.

A prose-only change needs accurate links and examples. Run the website build when
editing its MDX or components; a root Markdown correction does not require new tests
or an unrelated screenshot refresh.

## The compatibility gate

Within a major version a release is additive ([compatibility](COMPATIBILITY.md)), and
two checks hold every change to that against two published releases: the previous one
and the one OpenAlgo pins. Both are listed in `BASELINES` in
`scripts/compat-packages.mjs`, which fetches each with `npm pack` into a cache outside the
repository (the system temporary folder, or `OAC_COMPAT_CACHE`). Nothing is installed or
published; the registry is needed once per version.

`npm run check:compat`, part of `npm run verify` after the build, compares every tier's
public declarations with each release's. Every name a tier exported must still be
exported, every member of every type reachable from it must still exist, and each type
is held in the direction it travels: what the host passes in (an argument, an option, a
callback's return) may only accept more, and what the library hands back (a return, a
property, a callback's argument) may only promise less. A line starting `FAIL` names the
member and the direction:

```text
FAIL: ChartOptions.pixelRatio (host passes in): member removed
FAIL: Chart.restoreState(state) (host passes in): type changed incompatibly: unknown -> object
FAIL: RestoreReport.applied (library hands back): member is now optional, so it may be missing
```

Restore the name or the type. A name that is going away stays, marked `@deprecated` with
its removal in the next major and a row under Deprecated APIs in COMPATIBILITY.md; the
gate reads that table and reports such a finding as deprecated rather than failing.
`--verbose` also lists the additions and the unions that grew, and `--json` writes every
finding. An interface only the library implements, which a host holds but never builds,
is listed in `HANDLES` in the script with the reason, so a member added to it is additive;
`tests/check-compat.test.ts` proves each rule on the fixture in `scripts/fixtures/compat`.

`tests/saved-documents.test.ts`, part of `npm test`, loads what each release saved and
saves it again: a chart state with its studies, drawings and alerts, the drawings and
alert documents, the widget's persisted layout and its `getState`, and a workspace with
its catalog. The documents in `tests/fixtures/saved-documents/<version>/` were written by
that release as published, in Chromium, through its public API
(`node scripts/generate-saved-documents.mjs`). A load that refuses a document, drops a
study, drawing or alert, or changes a field fails, unless the test names that change with
its reason. A named change that stops happening fails too, so the list stays exact. When
a change of yours fails it, either it is a regression to fix or it is a deliberate new
field: name it, with the release that introduced it. Three modes of the generator print
and write nothing, and help decide which: `--check` loads the fixtures with the working
tree in a real browser, `--self` loads each release's documents with that release, which
tells what it already changes on its own documents from what this change does, and
`--reverse` has the working tree write the documents and the previous release load them,
which is what a rollback meets.

After a release is published, the next release is held to it: set the previous release in
`BASELINES` to the new version (and the pinned one, when OpenAlgo upgrades), run
`node scripts/generate-saved-documents.mjs` to add its documents, name in
`tests/saved-documents.test.ts` any change the working tree makes to them, and commit
both.

## Documentation and browser demos

Build the library, generate the API reference, then build the static website:

```sh
npm run build
npm run docs
npm --prefix website ci
npm --prefix website run build
npm --prefix website run preview
```

The preview serves `http://127.0.0.1:4174/openalgo-charts/`. For iterative editing,
`npm --prefix website run dev` serves the development site. Both development startup
and production builds sync current library bundles and standalone demos automatically.
Edit source demos and library code, then rebuild; generated copies are not source files.
Treat TypeDoc warnings as defects in API documentation or exported types.

With the static preview running, execute the relevant checks from another terminal:

```sh
node scripts/check-depth-demo.mjs
node scripts/check-profile-website.mjs
node scripts/check-navigation-website.mjs
```

For loading or drawing changes, run the managed-loading Playwright projects in
Chromium, Firefox and WebKit. Keep drawing previews visible past the newest candle
and assert that saved drawings never paint inside either price-axis strip.

For a drawing descriptor change, run `npx playwright test drawing-catalog`
against the built package. The catalogue sweep covers visible pixels, persistence,
pointer placement, touch placement, body and handle movement, and undo. Inspect
the screenshots as well as the assertions. Open `/examples/drawings/index.html`
for a sample of every tool; use `node scripts/check-drawing-demo.mjs` for the
website's embedded playground and standalone gallery. Keep registry, rail and
icon coverage in step, and preserve the version-2 drawing document.

Measure drawing paint, hit and drag work separately when changing performance.
Use identical data, viewport, DPR and drawing counts, and run timings without
concurrent builds or test workers. Bound curve/recursive work and include loaded
history with a changing forming bar. A faster result must preserve accurate
hit regions, level visibility, font changes and price-axis clipping.

These check depth grouping, profile/orderflow controls and screenshot fingerprints,
and current bundles plus time-axis dragging, two-axis plot panning, optional horizontal
panning and Reset view across website charts. They accept
an alternative preview base URL as the first argument. Inspect browser artifacts when
debugging failures. Other targeted checks are listed in [website/README.md](website/README.md).

When a source listed in
[the profile capture manifest](website/public/screenshots/market-profile-v2.1.1/captures.json)
changes, regenerate its screenshots and fingerprints from the newly built library:
start `node tests/e2e/serve.cjs`, then run
`node scripts/capture-profile-screenshots.mjs` in another terminal. Review the PNGs and
manifest together, rebuild the website, and rerun the profile check. Keep compressed
overviews and enlarged session close-ups faithful to their documented framing. The
capture directory identifies a capture generation, not the current package version.

## API contracts and agent skills

Keep the eight tier boundaries and zero runtime dependency model intact. Use registry
extensions and public tier exports; avoid deep imports that create separate registries.
Time is UTC seconds, while display zones are configurable. `DataLoadingController`
can own history, paging and recovery for a host; the host still owns display binding,
shared-feed lifetime, replay controls and broker execution.
See [ARCHITECTURE.md](ARCHITECTURE.md), [project conventions](CLAUDE.md), and
[host lifecycle guidance](.github/skills/openalgo-charts/references/host-integration.md).

A helper that keeps one object per chart answers a second request by one of two rules.
An attach helper whose object only draws or arranges (`attachSessionShading`,
`comparisonController`) returns the existing object with the new options applied. An
owner that holds state a second owner would fight over (`AlertController`, a
`ReplayGroup`) throws. A new per-chart helper picks one of the two and says which.

Update the matching [skill reference](.github/skills/README.md) whenever an API, default
or supported workflow changes. Preserve useful migration guidance, including the
[2.0 drawing migration](docs/migrating-to-2.md), and remove contradictory older examples.
After building, run `npm run skills:coverage`. Also validate Markdown links and skill
frontmatter, then try realistic task prompts using only the affected skill references.
Export-name coverage alone cannot establish correct lifecycle advice or working examples.

## Errors a host can tell apart

A host needs to tell its own bug from a refusal by the library, and it can only go
by the error's class and text. New code, and code a change already touches, follows
one convention:

- `TypeError` for an argument of the wrong type or shape (a string where a schedule
  was expected, an options object with an accessor property).
- `RangeError` for a number or index outside what the call accepts (a pane index
  that names no slot, `dpr` other than 1 for a vector export).
- `Error` for a state the library refuses (a pick on a destroyed chart, a second
  alert controller on one chart). A family a host must catch by kind gets its own
  class with a `name` (`IndicatorInputError`, `WorkspaceDocumentError`,
  `DataVariantUnsupportedError`), never a new message format.
- The message starts `openalgo-charts: `, then names the subject and the problem:
  `openalgo-charts: unknown IANA time zone "Asia/Calcuta"`.

Existing classes and messages stay as they are within a major release, however
they are spelled: hosts check `instanceof` and match on text (the instrument
parser's errors say so), so changing either is a breaking change for 3.0.0, not a
tidy-up.

## Issues and pull requests

For a bug, include the package version, browser or host, a minimal reproduction, and
expected versus actual behavior. Include relevant errors or screenshots. Feature
requests should explain the user workflow and the result the API should enable.

Keep a pull request focused. Describe the concrete problem, resulting behavior and
validation performed; identify meaningful limitations or skipped checks. Update the
related docs and runnable example when behavior changes. Use Conventional Commits,
such as `fix(navigation): preserve the preferred view` or `docs: explain local previews`.
Use generic behavior descriptions, keep comparison brands out of repository content,
and follow the plain-text writing rules in [CLAUDE.md](CLAUDE.md).

## Publishing a release

Maintainers use the authorized release workflow. Prepare the version, lockfile,
`src/version.ts`, changelog, website release notes, measured size/count claims and skill
updates before tagging; follow [the release process](CLAUDE.md#release-process-for-every-new-version) and
[the measured-facts checklist](CLAUDE.md#before-every-npm-publish).
Verify that package, source and built `version()` agree with the intended `vX.Y.Z` tag.

Push the verified tag, then manually dispatch [Release](.github/workflows/release.yml)
with that existing tag. A tag push alone does not publish. The job verifies the tagged
source and publishes with npm trusted publishing through OIDC and signed provenance,
using the configured `release` environment rather than a long-lived npm token.

Confirm the npm version and provenance, create or update the GitHub release for the
same tag using the changelog, and verify the separate
[Pages deployment](.github/workflows/deploy-docs.yml). Pages runs on matching source/site
changes or manual dispatch; npm publication does not create a GitHub release or deploy
the site itself. Keep published tags immutable. Follow-up documentation changes can be
ordinary commits; changes to a published package require a new version.

Once the release is on the registry, move [the compatibility gate](#the-compatibility-gate)
on to it: its version becomes the previous release in `BASELINES`, and its saved
documents join the fixtures.
