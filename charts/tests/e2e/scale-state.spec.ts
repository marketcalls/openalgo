import { test, expect, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window { __scaleStateCharts: [Chart, Chart] }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test('restored secondary scales retain pixels and ratio behavior', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 650 });
  await page.route('**/scale-state.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}body{display:flex}#before,#after{width:600px;height:600px}</style></head><body><div id="before"></div><div id="after"></div></body></html>',
  }));
  await page.goto('/scale-state.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { createChart, darkTheme } = await import(bundle) as typeof Charts;
    const bars = Array.from({ length: 30 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 103, low: 98, close: 100 + Math.sin(i) }));
    const make = (id: string) => {
      const chart = createChart(document.getElementById(id)!, { branding: false, theme: darkTheme });
      chart.addSeries('candlestick').setData(bars);
      chart.addSeries('line', { priceScaleId: 'left', style: { color: '#4488ff', lineWidth: 2 } })
        .setData(bars.map((bar, i) => ({ ...bar, open: 20 + i / 3, high: 20 + i / 3, low: 20 + i / 3, close: 20 + i / 3 })));
      chart.addSeries('line', { priceScaleId: 'overlay:score', style: { color: '#eeaa22', lineWidth: 2 } })
        .setData(bars.map((bar, i) => ({ ...bar, open: 1000 + i * 3, high: 1000 + i * 3, low: 1000 + i * 3, close: 1000 + i * 3 })));
      return chart;
    };
    const first = make('before');
    const second = make('after');
    first.setVisibleLogicalRange({ from: -2, to: 32 });
    first.setPriceAxisOptions(0, 'left', { inverted: true, marginTop: 0.2, marginBottom: 0.15, minPrecision: 2 });
    first.setPriceAxisAutoFit(0, 'left', false);
    first.panes()[0].scaleFor('left').setPriceRange({ min: 10, max: 40 });
    first.setPriceAxisOptions(0, 'overlay:score', { mode: 'logarithmic', marginTop: 0.1, marginBottom: 0.2 });
    first.setPriceAxisAutoFit(0, 'overlay:score', false);
    first.panes()[0].scaleFor('overlay:score').setPriceRange({ min: 900, max: 1200 });
    window.__scaleStateCharts = [first, second];
  });
  await paint(page);
  await page.evaluate(() => {
    const [first, second] = window.__scaleStateCharts;
    first.setPriceAxisLockRatio(0, 'left', true);
    first.setPriceAxisLockRatio(0, 'overlay:score', true);
    const result = second.restoreState(JSON.parse(JSON.stringify(first.getState())));
    if (!result.applied) throw new Error(result.reason);
  });
  await paint(page);
  const first = await page.locator('#before').screenshot();
  const second = await page.locator('#after').screenshot();
  expect(second.equals(first)).toBe(true);
  await page.screenshot({ path: info.outputPath('restored-scales.png') });
  await page.evaluate(() => {
    for (const chart of window.__scaleStateCharts) chart.setVisibleLogicalRange({ from: 5, to: 25 });
  });
  await paint(page);
  const ranges = await page.evaluate(() => window.__scaleStateCharts.map(chart => ({
    left: chart.panes()[0].scaleFor('left').priceRange(),
    overlay: chart.panes()[0].scaleFor('overlay:score').priceRange(),
    locked: [chart.priceAxisState(0, 'left')?.lockRatio, chart.priceAxisState(0, 'overlay:score')?.lockRatio],
  })));
  expect(ranges[1]).toEqual(ranges[0]);
  expect(ranges[1].locked).toEqual([true, true]);
  expect(ranges[1].left).not.toEqual({ min: 10, max: 40 });
  expect(errors).toEqual([]);
});
