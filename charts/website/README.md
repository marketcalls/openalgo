# OpenAlgo Charts documentation site

The docs site, built with [Nextra](https://nextra.site) (Next.js) and statically exported to
GitHub Pages at https://marketcalls.github.io/openalgo-charts/.

## Run locally

The live, in-page chart demos import the real built library, so build it first:

```bash
# from the repo root
npm run build

# then start the docs site
cd website
npm install
npm run dev          # http://localhost:3000/openalgo-charts
```

`npm run dev` / `npm run build` automatically run `scripts/sync-lib.mjs`, which copies the
built bundles from `../dist` into `lib/oac/` for the demos.
The same step copies the standalone profile demo, its theme module and the
drawing gallery into generated `public/demos/` assets, along with all required
bundles. Relative imports keep these demos working under the website's
`/openalgo-charts` base path. The drawing gallery at `/demos/drawings/index.html`
exposes all 85 registered tools with sample anchors, manual placement and the
packaged widget's settings and object controls.

To preview the actual static export:

```bash
npm run build
npm run preview      # http://127.0.0.1:4174/openalgo-charts/
# In another terminal, with the preview running:
npm run check:profile
```

## Profile screenshots

The source demo is `../examples/market-profile/index.html`. Edit its theme
presets in `themes.js`; the website embeds that same source after the sync step.
The gallery is at `/docs/market-profile-examples` and also appears on `/examples`.

From the repository root, with the library built:

```bash
node tests/e2e/serve.cjs
# In another terminal:
node scripts/capture-profile-screenshots.mjs
```

The capture script writes five theme PNGs at 800 × 1320, DPR 2, focusing on the
same newest synthetic session with 18 CSS pixels per row and 16-pixel letters.
It also captures packed/split views with the same framing and unchanged price
aggregation. Gallery cards display images at 320 to 400 CSS pixels wide; narrow
screens scroll within a card instead of shrinking letters further. Screenshots are
tracked in `public/screenshots/market-profile-v2.1.1/`; generated demo bundles are ignored.
Pass a full demo URL as the script's first argument to capture another local host.

The 2.2.0 build retains these captures because their renderer/demo source
fingerprints are unchanged. The gallery shows the current profile implementation;
the 2.1.1 release notes record when its themes and footprint controls shipped.
CI and Pages run the profile, depth and drawing checks before publishing the site.
CI also runs the site design check, which holds the pages and the API reference to
phone widths (320 and 390 px) without horizontal scrolling. Before it opens a page it
reads the sources in `pages/` and `components/` and fails on example prices or study
outputs written as a formula of the bar index (a sine, a ramp, a sawtooth): examples
draw from the seeded random walk in `components/synthetic-market.ts`.

## Interactive and API checks

After building and starting the static preview, run these from the repository root:

```bash
node scripts/check-profile-website.mjs
node scripts/check-navigation-website.mjs
node scripts/check-depth-demo.mjs
node scripts/check-drawing-demo.mjs
node scripts/check-site-design.mjs
node --test scripts/check-btc-usd-feed.test.mjs
```

To verify actual exchange responses, all four timeframes, refreshes, reconnection
and cleanup in a browser, run `node scripts/check-btc-usd-chart.mjs
http://127.0.0.1:4174/openalgo-charts`. This check requires network access to the
public data endpoint; the feed unit tests run without external requests.

The depth demo uses simulated updates and the published tick-grouping API.
The drawing playground exercises the same controller used by applications.
The homepage, guides and API reference share the site's dark and light palettes.
A first visit opens in the light theme; the navbar toggle saves the reader's
choice for later visits. Live examples, the embedded profile and order-flow
demos, example code and the architecture diagram follow the active theme, so
host controls in an example take their colours from the page (`light-dark()`)
or, for anything drawn on the canvas, from the chart's palette rather than a
fixed dark value. The light diagram is generated from the dark one by
`scripts/diagram-light.mjs` during the sync step.
Intro animations respect the visitor's reduced-motion preference.

The homepage chart uses public BTC/USD exchange candles through
`lib/market-data/btc-usd.mjs`. It refreshes every 15 seconds and supports 15-minute,
hourly, four-hour and daily candles, with Supertrend (10, 3) over price and MACD
(12, 26, 9) in a separate pane. Four-hour candles aggregate hourly OHLCV on
UTC boundaries. No API key or server is required. The source is linked below the
chart. Failed requests show an unavailable state or label previously received
candles as disconnected; the homepage never substitutes generated prices.

The deployment generates the API reference from all eight current source entry
points with `npx typedoc --out website/public/api` before exporting the site.
`typedoc.json` includes the package version in page titles, applies
`styles/api.css`, and changes asset URLs on regeneration to refresh cached styles.
The API introduction lives in `../docs/api-introduction.md`; generated API pages
are ignored in git and rebuilt by CI on every site deployment.

## Add or edit a page

1. Create an `.mdx` file in `pages/docs/`.
2. Add one entry to `pages/docs/_meta.ts` to place it in the sidebar (the key is the file
   name without extension; the value is the sidebar label). Use a `{ type: 'separator' }`
   entry to start a new section.

That is the whole workflow. Prose is plain Markdown.

## Add a live demo

Import the demo component and pass it a code string. The same string is both displayed
(syntax-highlighted) and executed, so the example can never drift from what readers see:

```mdx
import RunnableExample from '../../components/RunnableExample'

<RunnableExample height={320} code={`const chart = lib.createChart(el);
chart.addSeries('candlestick').setData(lib.generateBars(1700000000, 140, 3600));
chart.timeScale.fitContent(140);
return chart;`} />
```

Inside the code string, `el` is the chart container and `lib` is the library namespace. End
with `return chart;` so the demo tears down cleanly. To use a non-base tier, pass
`tiers={['transform']}` (or `'trade'` / `'profile'`).

Two rules for the code string (it is a template literal in MDX): no backticks, and no `${`
interpolation.

## Structure

```
pages/                 docs pages (.mdx) + _meta.ts sidebars; index.mdx is the landing page
components/            RunnableExample (live demos), landing sections, code highlighter
styles/globals.css     site + demo styling
theme.config.tsx       Nextra theme (logo, nav, footer, SEO)
scripts/sync-lib.mjs   copies ../dist bundles into lib/oac for the demos
public/api/            TypeDoc API reference (generated; served at /openalgo-charts/api)
```

Deployment is automated by `.github/workflows/deploy-docs.yml`.

The managed-loading example is validated with
`node scripts/check-data-loading-website.mjs <preview-base-url>` from the repository
root. It covers older pages, failed refresh and Retry, reconnect, empty/restore and
mobile layout against the built public widget. Its screenshots are written under
`artifacts/`. This check also runs before website deployment.
