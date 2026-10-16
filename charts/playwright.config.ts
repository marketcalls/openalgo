import { spawnSync } from 'node:child_process';
import { defineConfig, devices } from '@playwright/test';

// Real-browser smoke tests. A tiny static server (tests/e2e/serve.cjs) serves the
// built package + a fixture page; the suite renders a chart and exercises the
// interactions/feed paths that unit tests (fake canvas) can't catch.
//
// The yfinance demo (examples/yfinance, the reference host) is driven through
// its own server in --fixture mode: synthetic bars, no network, no yfinance.
// That server is Python, which not every machine has, so it is started only
// when a Python 3 answers on PATH; tests/e2e/yfinance.spec.ts probes for it
// and skips itself when it is absent, rather than failing a run that never
// asked for Python.

const DEMO_PORT = Number(process.env.OAC_E2E_DEMO_PORT || 8124);
const DEMO_URL = `http://127.0.0.1:${DEMO_PORT}`;
const ENGINE_PORT = process.env.OAC_E2E_ENGINE_PORT || '4173';
const ENGINE_URL = `http://127.0.0.1:${ENGINE_PORT}`;
// The widget fixtures get their own server; several checkouts can run the
// suite at once when each sets distinct ports.
const WIDGET_PORT = process.env.OAC_E2E_WIDGET_PORT || '4176';
const WIDGET_URL = `http://127.0.0.1:${WIDGET_PORT}`;

/** The first Python 3 on PATH, as the command to run it by, or null. */
function pythonOnPath(): string | null {
  // Windows ships a `python` stub that opens the Store and exits non-zero;
  // the version check rules it out along with a Python 2 (which prints its
  // version on stderr, so stdout stays empty).
  const candidates = process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python'];
  for (const py of candidates) {
    const r = spawnSync(py, ['--version'], { encoding: 'utf8' });
    if (!r.error && r.status === 0 && /^Python 3\./.test(r.stdout.trim())) return py;
  }
  return null;
}

const python = pythonOnPath();

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // The retry stays, so a report still names a test that failed once and
  // passed once as flaky, but the run fails on it: a flaky test is fixed or
  // reported with its failure rate, never retried into green (CLAUDE.md).
  retries: process.env.CI ? 1 : 0,
  failOnFlakyTests: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: ENGINE_URL },
  webServer: [
    {
      command: 'node tests/e2e/serve.cjs',
      env: { OAC_E2E_PORT: ENGINE_PORT },
      url: `${ENGINE_URL}/dist/openalgo-charts.mjs`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'node tests/e2e/serve.cjs',
      env: { OAC_E2E_PORT: WIDGET_PORT },
      url: `${WIDGET_URL}/dist/openalgo-charts.mjs`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    ...(python
      ? [{
          command: `${python} examples/yfinance/server.py --fixture --quiet --port ${DEMO_PORT}`,
          url: `${DEMO_URL}/examples/yfinance/index.html`,
          reuseExistingServer: !process.env.CI,
          timeout: 30_000,
        }]
      : []),
  ],
  projects: [
    // The engine suite, against the static server. The demo spec is not in
    // it: that page needs /api/history, which serve.cjs does not answer.
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, testIgnore: /(?:yfinance(?:-(?:ui-253|rail-replay|drawing-scope|mobile|templates|indicator-source|routed-study|grid|pane-reorder|tick-schedule|viewport|watchlist-news|account|study-policies|history|session|gestures|intervals|bottombar|timeline))?|widget-grid|widget-ui-253|widget-data-loading|widget-localization|widget-alerts|chart-data-export|instruments|indicator-source-markers|marker-lanes|alert-line-drag|table-layout|date-navigation|tick-schedule-drag|drawing-viewport|drawing-instrument|widget-watchlist-news|widget-account|icon-raster|stack-order|native-input-points|widget-history|widget-data-variants|device-pixels|resize-frames|vue-integration|line-edges|widget-drawing-ui|session-shade|widget-storage|widget-bottombar|widget-keymap|widget-layouts|widget-lazy-parts|widget-feed-events|transform-live|labels|script-tag)\.spec\.ts/ },
    ...(['chromium', 'firefox', 'webkit'] as const).map(browserName => ({
      name: `widget-loading-${browserName}`,
      testMatch: /(?:widget-grid|marker-lanes|widget-ui-253|widget-data-loading|widget-localization|widget-alerts|drawing-future|drawing-catalog|analysis-linked-events|widget-objects|navigation-wheel|widget-mobile|branding-watermark|crosshair-snap|workspace-storage|workspace-revisions|open-interest|alerts|alert-line-drag|table-layout|replay-time|chart-data-export|instruments|indicator-source-markers|indicator-visuals|scale-state|native-timeframe-navigation|native-fill-gradients|native-series-scale-assignment|native-indicator-lifecycle|native-study-scale-assignment|native-requested-provider|native-external-lifecycle|native-indicator-alerts|native-study-dependencies|native-study-source-ui|native-multiple-price-axes|native-plot-scale-assignments|native-template-layouts|native-numerical-indicators|native-chart-preferences|native-typed-inputs|native-higher-timeframe|indicator-curved-polylines|table-cell-tooltips|indicator-window-arithmetic|cpr-period-observations|user-navigation-policy(?:-reference)?|indicator-text-style|date-navigation|pane-collapse|pane-reorder|native-output-targets|tick-schedule-drag|drawing-viewport|drawing-instrument|widget-watchlist-news|widget-account|icon-raster|stack-order|native-input-points|widget-history|native-conditional-inputs|widget-data-variants|device-pixels|resize-frames|vue-integration|line-edges|widget-drawing-ui|session-shade|widget-storage|widget-bottombar|widget-keymap|widget-layouts|widget-lazy-parts|widget-feed-events|transform-live)\.spec\.ts/,
      use: { browserName, baseURL: WIDGET_URL },
    })),
    // The script-tag build, a page of classic scripts, in all three engines.
    ...(['chromium', 'firefox', 'webkit'] as const).map(browserName => ({
      name: `script-tag-${browserName}`,
      testMatch: /script-tag\.spec\.ts/,
      use: { browserName, baseURL: ENGINE_URL },
    })),
    // The label guard walks the widget fixtures and the demo in one spec: the
    // widget pages from the widget server, the demo from its own (by URL).
    { name: 'labels', testMatch: /labels\.spec\.ts/, use: { ...devices['Desktop Chrome'], baseURL: WIDGET_URL } },
    // The demo, against its own server. Kept in the list even with no
    // Python, so the spec is found and can report itself skipped.
    { name: 'yfinance-demo', testMatch: /yfinance\.spec\.ts/, use: { ...devices['Desktop Chrome'], baseURL: DEMO_URL } },
    ...(['chromium', 'firefox', 'webkit'] as const).map(browserName => ({
      name: `yfinance-mobile-${browserName}`,
      testMatch: /yfinance-(?:ui-253|rail-replay|drawing-scope|mobile|templates|indicator-source|grid|routed-study|pane-reorder|tick-schedule|viewport|watchlist-news|account|study-policies|history|session|gestures|intervals|bottombar|timeline)\.spec\.ts/,
      use: { browserName, baseURL: DEMO_URL },
    })),
    // The render bench times frames, so it must not share the machine with
    // the rest of the suite: it is a project only when OAC_RENDER_BENCH is set
    // (`npm run bench:render` and the CI bench job set it), its file is not a
    // .spec.ts that another project would collect, and it runs one test at a
    // time. It launches Chromium itself, with flags per renderer.
    ...(process.env.OAC_RENDER_BENCH
      ? [{
          name: 'render-bench',
          testMatch: /render-bench\.perf\.ts/,
          workers: 1,
          fullyParallel: false,
          use: { baseURL: ENGINE_URL },
        }]
      : []),
  ],
});
