import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __nativeVisuals: { chart: Chart; indicator: IndicatorApi; source: SeriesApi };
  }
}

async function painted(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function colors(page: Page) {
  return page.evaluate(() => {
    const counts = { red: 0, magenta: 0, yellow: 0, gradient: 0 };
    for (const canvas of document.querySelectorAll('canvas')) {
      const ctx = canvas.getContext('2d');
      if (!ctx) continue;
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        const [r, g, b, a] = pixels.slice(i, i + 4);
        if (a !== 255) continue;
        if (r === 204 && g === 34 && b === 68) counts.red++;
        if (r === 153 && g === 51 && b === 204) counts.magenta++;
        if (r === 238 && g === 204 && b === 34) counts.yellow++;
        if (r === 0 && g > 30 && b > 30 && Math.abs(g + b - 255) < 3) counts.gradient++;
      }
    }
    return counts;
  });
}

test('native descriptor fills and tables paint, refresh and disappear with their owner', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 600 });
  await page.route('**/native-visuals.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/native-visuals.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    const source = chart.addSeries('candlestick');
    source.setData(Array.from({ length: 40 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    lib.registerIndicator({
      id: 'native-visuals', name: 'Native visual outputs', placement: 'onchart',
      inputs: [{ key: 'highlight', label: 'Highlight', type: 'boolean', default: true }],
      plots: [
        { key: 'upper', type: 'line', title: 'Upper', style: { color: '#ffffff' } },
        { key: 'lower', type: 'line', title: 'Lower', style: { color: '#ffffff' } },
      ],
      calc: bars => ({ upper: bars.map(() => 108), lower: bars.map(() => 92) }),
      fills: [{ between: ['upper', 'lower'], opacity: 1,
        gradient: { topValue: 108, bottomValue: 92, topColor: '#00ff00', bottomColor: '#0000ff' },
        colorBy: ({ index, settings }) => settings.highlight && index < 20 ? '#cc2244' : undefined,
      }],
      tables: ({ bars }) => [
        { id: 'quote', rows: [[{ text: `Latest ${bars[bars.length - 1].close.toFixed(2)}`, bgColor: '#9933cc', textColor: '#ffffff' }]], options: { position: 'bottom-left', cellWidth: 160, cellHeight: 32 } },
        { id: 'count', rows: [[{ text: `${bars.length} observations`, bgColor: '#eecc22', textColor: '#000000' }]], options: { position: 'bottom-right', cellWidth: 160, cellHeight: 32 } },
      ],
    });
    const indicator = chart.addIndicator('native-visuals');
    chart.setVisibleLogicalRange({ from: -2, to: 42 });
    window.__nativeVisuals = { chart, source, indicator };
  });
  await painted(page);
  const first = await colors(page);
  expect(first.red).toBeGreaterThan(10000);
  expect(first.gradient).toBeGreaterThan(10000);
  expect(first.magenta).toBeGreaterThan(1000);
  expect(first.yellow).toBeGreaterThan(1000);
  await page.screenshot({ path: info.outputPath('native-visuals.png') });
  await page.evaluate(() => {
    const { indicator, source } = window.__nativeVisuals;
    indicator.setSettings({ highlight: false });
    source.update({ time: 1700000000 + 39 * 60, open: 99, high: 106, low: 98, close: 105 });
    indicator.values();
  });
  await painted(page);
  const updated = await colors(page);
  expect(updated.red).toBe(0);
  expect(updated.gradient).toBeGreaterThan(first.gradient * 1.5);
  const rows = await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { ChartTable } = await import(bundle) as typeof Charts;
    return window.__nativeVisuals.chart.panes().flatMap(pane => pane.primitives())
      .filter(item => item instanceof ChartTable).map(item => (item as InstanceType<typeof ChartTable>).rows()[0][0].text);
  });
  expect(rows).toEqual(['Latest 105.00', '40 observations']);
  await page.evaluate(() => window.__nativeVisuals.indicator.setVisible(false));
  await painted(page);
  expect(await colors(page)).toEqual({ red: 0, magenta: 0, yellow: 0, gradient: 0 });
  await page.evaluate(() => window.__nativeVisuals.indicator.setVisible(true));
  await painted(page);
  expect((await colors(page)).yellow).toBeGreaterThan(1000);
  await page.evaluate(() => window.__nativeVisuals.indicator.remove());
  await painted(page);
  expect(await colors(page)).toEqual({ red: 0, magenta: 0, yellow: 0, gradient: 0 });
  expect(errors).toEqual([]);
});
