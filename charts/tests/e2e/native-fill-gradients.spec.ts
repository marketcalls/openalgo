import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window { __gradientChart: { chart: Chart; indicator: IndicatorApi } }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function samples(page: Page) {
  return page.evaluate(() => {
    const { chart } = window.__gradientChart;
    return [[5.3, 70], [25.3, 30]].map(([index, price]) => {
      const x = chart.timeScale.indexToX(index);
      const y = chart.priceToCoordinate(price)!;
      for (const canvas of document.querySelectorAll<HTMLCanvasElement>('#chart canvas')) {
        const ratio = canvas.width / canvas.clientWidth;
        const pixel = canvas.getContext('2d')!.getImageData(Math.round(x * ratio), Math.round(y * ratio), 1, 1).data;
        if (pixel[0] + pixel[2] > 240 && pixel[1] < 5 && pixel[3] === 255) return Array.from(pixel);
      }
      return null;
    });
  });
}

function expectMidpoints(readings: (number[] | null)[]) {
  for (const reading of readings) {
    expect(reading).not.toBeNull();
    expect(Math.abs(reading![0] - 128)).toBeLessThan(6);
    expect(reading![1]).toBe(0);
    expect(Math.abs(reading![2] - 128)).toBeLessThan(6);
  }
}

test('per-bar gradients retain their price anchors through pan, inversion and refresh', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 600 });
  await page.route('**/native-gradient.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/native-gradient.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, { branding: false, theme: lib.darkTheme });
    chart.addSeries('line', { style: { color: '#ffffff' } }).setData(Array.from({ length: 40 }, (_, index) => ({
      time: 1700000000 + index * 60, open: 50, high: 50, low: 50, close: 50,
    })));
    lib.registerIndicator({
      id: 'native-gradient', name: 'Gradient anchors', placement: 'onchart',
      inputs: [{ key: 'vary', type: 'boolean', label: 'Vary', default: true }],
      plots: [{ key: 'a', type: 'line', title: 'Upper' }, { key: 'b', type: 'line', title: 'Lower' }],
      calc: bars => ({ a: bars.map(() => 80), b: bars.map(() => 20) }),
      fills: [{ between: ['a', 'b'], opacity: 1,
        gradient: { topValue: 80, bottomValue: 20, topColor: '#ff0000', bottomColor: '#0000ff' },
        gradientBy: ({ index, settings }) => settings.vary ? {
          topValue: index < 20 ? 80 : 40, bottomValue: index < 20 ? 60 : 20,
          topColor: '#ff0000', bottomColor: '#0000ff',
        } : undefined,
      }],
    });
    const indicator = chart.addIndicator('native-gradient');
    chart.setVisibleLogicalRange({ from: -2, to: 42 });
    chart.setPriceAxisAutoFit(0, 'right', false);
    chart.panes()[0].priceScale.setPriceRange({ min: 0, max: 100 });
    window.__gradientChart = { chart, indicator };
  });
  await paint(page);
  expectMidpoints(await samples(page));
  await page.screenshot({ path: info.outputPath('varying-gradient.png') });
  await page.evaluate(() => {
    const { chart } = window.__gradientChart;
    chart.panes()[0].priceScale.setPriceRange({ min: -10, max: 90 });
    chart.setPriceAxisOptions(0, 'right', {});
  });
  await paint(page);
  expectMidpoints(await samples(page));
  await page.evaluate(() => window.__gradientChart.chart.setPriceAxisOptions(0, 'right', { inverted: true }));
  await paint(page);
  expectMidpoints(await samples(page));
  await page.screenshot({ path: info.outputPath('inverted-gradient.png') });
  await page.evaluate(() => window.__gradientChart.indicator.setSettings({ vary: false }));
  await paint(page);
  const fallback = await samples(page);
  expect(fallback[0]![0]).toBeGreaterThan(205);
  expect(fallback[1]![2]).toBeGreaterThan(205);
  await page.evaluate(() => window.__gradientChart.indicator.setVisible(false));
  await paint(page);
  expect(await samples(page)).toEqual([null, null]);
  await page.evaluate(() => {
    window.__gradientChart.indicator.setSettings({ vary: true });
    window.__gradientChart.indicator.setVisible(true);
  });
  await paint(page);
  expectMidpoints(await samples(page));
  expect(errors).toEqual([]);
});
