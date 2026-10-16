import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, IndicatorSnapshotRequest, ReplayController, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __requestedProvider: {
      chart: Chart; study: IndicatorApi; plot: SeriesApi; source: SeriesApi;
      requests: IndicatorSnapshotRequest[]; originalData: string;
      replay?: ReplayController; raw?: () => Promise<readonly Charts.Bar[]>;
    };
  }
}

const START = 1700000000;

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function loadExample(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  const markdown = await response.text();
  let code = markdown.split('## Requested snapshots from a deferred provider')[1].split('code={`')[1].split('`} />')[0];
  // The site's template splices the shared bar generator in; do the same here.
  const market = await (await page.request.get('/website/components/synthetic-market.ts')).text();
  code = code.replace('${STOCK_BARS_SOURCE}', market.split('STOCK_BARS_SOURCE = `')[1].split('`;')[0]);
  await page.setViewportSize({ width: 960, height: 470 });
  await page.route('**/requested-provider.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:960px;height:460px}</style></head><body><div id="example"></div></body></html>' }));
  await page.goto('/requested-provider.html');
  await page.evaluate(async sourceCode => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const requests: IndicatorSnapshotRequest[] = [];
    const instrumented = { ...lib, createChart: (host: HTMLElement, options: Charts.ChartOptions) => {
      const chart = lib.createChart(host, { ...options, theme: lib.darkTheme, animZoom: false, timeNavigator: false });
      const setProvider = chart.setBarsProvider.bind(chart);
      chart.setBarsProvider = provider => {
        if (typeof provider === 'object' && provider?.requestSnapshot) {
          const snapshot = provider.requestSnapshot.bind(provider);
          setProvider({ ...provider, requestSnapshot: request => { requests.push(request); return snapshot(request); } });
        } else setProvider(provider);
      };
      return chart;
    } };
    const chart = new Function('el', 'lib', sourceCode)(document.getElementById('example'), instrumented) as Chart;
    const study = chart.indicators()[0], series = chart.primarySeries()!;
    window.__requestedProvider = { chart, study, plot: study.series('close')!, source: series,
      requests, originalData: JSON.stringify(series.getData()) };
  }, code);
  await paint(page);
  return errors;
}

async function release(page: Page) {
  await page.getByRole('button', { name: 'Release response', exact: true }).click();
  await paint(page);
}

async function releaseReady(page: Page) {
  // Replay's clock notification precedes its source replacement, allowing one catch-up.
  await release(page);
  if (await page.evaluate(() => window.__requestedProvider.study.dataStatus()?.state) === 'loading') {
    await release(page);
  }
  expect(await page.evaluate(() => window.__requestedProvider.study.dataStatus()?.state)).toBe('ready');
}

async function inspect(page: Page, index = 8) {
  return page.evaluate(barIndex => {
    const { chart, study, plot, source, requests, originalData } = window.__requestedProvider;
    const values = study.values().close, price = values[barIndex];
    let ink = 0;
    if (typeof price === 'number') {
      const canvas = chart.panes()[study.paneIndex].base.element, context = canvas.getContext('2d')!;
      const ratio = canvas.width / 960, x = chart.timeScale.indexToX(barIndex), y = plot.priceScale().priceToY(price);
      const pixels = context.getImageData(Math.round((x - 5) * ratio), Math.round((y - 5) * ratio),
        Math.round(10 * ratio), Math.round(10 * ratio)).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 232 && pixels[i + 1] === 162 && pixels[i + 2] === 58) ink++;
      }
    }
    return { values, ink, status: study.dataStatus()?.state, samePlot: study.series('close') === plot,
      sameSource: chart.primarySeries() === source, sameData: JSON.stringify(source.getData()) === originalData,
      hasSnapshots: chart.hasSnapshotProvider(), requests: requests.map(request => ({
        asOf: request.asOf ?? null, from: request.from, to: request.to, aborted: request.signal?.aborted ?? false,
      })) };
  }, index);
}

test('deferred example renders updates, provider replacement and explicit confirmation with owned cancellation', async ({ page }, info) => {
  const errors = await loadExample(page);
  expect(await inspect(page)).toMatchObject({ status: 'loading', hasSnapshots: true, values: new Array(12).fill(null) });
  await release(page);
  let state = await inspect(page);
  expect(state).toMatchObject({ status: 'ready', values: [null, 10, 10, 10, 10, 10, 20, 20, 20, 20, 20, 20] });
  expect(state.ink).toBeGreaterThan(12);
  await page.screenshot({ path: info.outputPath('requested-initial.png') });

  await page.getByRole('button', { name: 'Revise values', exact: true }).click();
  await release(page);
  state = await inspect(page);
  expect(state).toMatchObject({ status: 'ready', values: [null, 15, 15, 15, 15, 15, 25, 25, 25, 25, 25, 25] });
  expect(state.ink).toBeGreaterThan(12);
  await page.screenshot({ path: info.outputPath('requested-revised.png') });

  await page.getByRole('button', { name: 'Revise values', exact: true }).click();
  const obsolete = (await inspect(page)).requests.length - 1;
  await page.getByRole('button', { name: 'Replace provider', exact: true }).click();
  state = await inspect(page);
  expect(state.requests[obsolete].aborted).toBe(true);
  expect(state.values).toEqual(new Array(12).fill(null));
  await release(page);
  state = await inspect(page);
  expect(state.values).toEqual([null, 110, 110, 110, 110, 110, 120, 120, 120, 120, 120, 120]);
  expect(state.ink).toBeGreaterThan(12);
  await page.screenshot({ path: info.outputPath('requested-replaced.png') });

  await page.getByRole('button', { name: 'Confirm latest', exact: true }).click();
  await release(page);
  state = await inspect(page, 10);
  expect(state).toMatchObject({ status: 'ready', values: [null, 110, 110, 110, 110, 110, 120, 120, 120, 120, 130, 130],
    samePlot: true, sameSource: true, sameData: true });
  expect(state.ink).toBeGreaterThan(12);
  await page.screenshot({ path: info.outputPath('requested-confirmed.png') });

  await page.getByRole('button', { name: 'Revise values', exact: true }).click();
  await page.evaluate(() => window.__requestedProvider.study.remove());
  await paint(page);
  expect(await page.evaluate(() => ({ aborted: window.__requestedProvider.requests.slice(-1)[0].signal!.aborted,
    count: window.__requestedProvider.chart.indicators().length }))).toEqual({ aborted: true, count: 0 });
  await release(page);
  expect(await page.evaluate(() => window.__requestedProvider.chart.indicators().length)).toBe(0);
  expect(errors).toEqual([]);
});

test('snapshot replay advances availability within one source observation and rejects legacy cutoffs', async ({ page }, info) => {
  const errors = await loadExample(page);
  await release(page);
  await page.getByRole('button', { name: 'Revise values', exact: true }).click();
  await release(page);
  await page.evaluate(async start => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const state = window.__requestedProvider;
    state.replay = new lib.ReplayController(state.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: start + 300 });
  }, START);
  await releaseReady(page);
  let state = await inspect(page, 4);
  expect(state.status, JSON.stringify(state)).toBe('ready');
  expect(state.values).toEqual([null, 10, 10, 10, 10]);
  expect(state.requests.slice(-1)[0].asOf).toBe(START + 300);
  expect(state.ink).toBeGreaterThan(12);
  await page.screenshot({ path: info.outputPath('requested-replay-before-release.png') });
  const dataBefore = await page.evaluate(() => JSON.stringify(window.__requestedProvider.source.getData()));
  const before = state.requests.length;

  await page.evaluate(start => window.__requestedProvider.replay!.seekTime(start + 330), START);
  await release(page);
  state = await inspect(page, 4);
  expect(state.requests.length).toBe(before + 1);
  expect(state.requests.slice(-1)[0].asOf).toBe(START + 330);
  expect(state.values).toEqual([null, 10, 10, 10, 20]);
  expect(state.ink).toBeGreaterThan(12);
  expect(await page.evaluate(() => JSON.stringify(window.__requestedProvider.source.getData()))).toBe(dataBefore);
  await page.screenshot({ path: info.outputPath('requested-replay-after-release.png') });

  await page.evaluate(() => window.__requestedProvider.replay!.stop());
  await releaseReady(page);
  expect((await inspect(page)).values.slice(-1)).toEqual([25]);
  await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const state = window.__requestedProvider;
    lib.registerIndicator({ id: 'requested-raw-probe', name: 'Raw request', placement: 'onchart', inputs: [], plots: [],
      calc: () => ({}), attach: context => {
        state.raw = () => context.requestBars!({ symbol: 'REQUESTED', interval: '3m', from: 1700000000, to: 1700000660 });
      } });
    state.chart.addIndicator('requested-raw-probe');
    state.replay = new lib.ReplayController(state.chart, { startIndex: 5 });
  });
  await paint(page);
  state = await inspect(page, 4);
  expect(state).toMatchObject({ status: 'unsupported', values: new Array(6).fill(null), ink: 0 });
  expect(await page.evaluate(async () => (await window.__requestedProvider.raw!()).map(bar => bar.close))).toEqual([15, 25, 35]);
  await page.screenshot({ path: info.outputPath('requested-legacy-unsupported.png') });
  await page.evaluate(() => window.__requestedProvider.replay!.stop());
  await paint(page);
  await page.evaluate(() => window.__requestedProvider.chart.destroy());
  expect(await page.evaluate(() => window.__requestedProvider.requests.slice(-1)[0].signal!.aborted)).toBe(true);
  expect(errors).toEqual([]);
});
