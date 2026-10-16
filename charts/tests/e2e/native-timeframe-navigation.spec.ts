import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';
import type * as Indicators from '../../src/indicators/index';

declare global {
  interface Window {
    __requestedCharts: { charts: [Chart, Chart]; indicators: IndicatorApi[]; events: string[] };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test('requested calculations paint and direct navigation updates linked charts', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 600 });
  await page.route('**/requested-context.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}body{display:flex}#first,#second{width:600px;height:600px}</style></head><body><div id="first"></div><div id="second"></div></body></html>',
  }));
  await page.goto('/requested-context.html');
  await page.evaluate(async () => {
    const baseUrl = '/dist/openalgo-charts.mjs';
    const indicatorUrl = '/dist/openalgo-charts.indicators.mjs';
    const lib = await import(baseUrl) as typeof Charts;
    const { securityExpression, sma, nulls } = await import(indicatorUrl) as typeof Indicators;
    lib.registerIndicator({
      id: 'requested-browser-mean', name: 'Requested mean', placement: 'onchart', inputs: [],
      plots: [
        { key: 'confirmed', type: 'step', title: 'Confirmed', style: { color: '#eeaa22', lineWidth: 2 } },
        { key: 'developing', type: 'line', title: 'Developing', style: { color: '#4488ff', lineWidth: 2 } },
      ],
      calc: bars => {
        const expression = (requested: readonly Readonly<Charts.Bar>[]) => ({ mean: nulls(sma(requested.map(bar => bar.close), 2)) });
        return {
          confirmed: securityExpression(bars, '15m', expression, { timezone: 'UTC' }).mean,
          developing: securityExpression(bars, '15m', expression, { timezone: 'UTC', mode: 'developing' }).mean,
        };
      },
    });
    const indicators: IndicatorApi[] = [];
    const bars = Array.from({ length: 72 }, (_, i) => ({ time: i * 60, open: 99 + i, high: 102 + i, low: 98 + i, close: 100 + i }));
    const make = (id: string) => {
      const chart = lib.createChart(document.getElementById(id)!, { branding: false, theme: lib.darkTheme });
      chart.addSeries('candlestick').setData(bars);
      indicators.push(chart.addIndicator('requested-browser-mean'));
      chart.setVisibleLogicalRange({ from: -2, to: 74 });
      return chart;
    };
    const charts: [Chart, Chart] = [make('first'), make('second')];
    const link = lib.createLinkGroup({ viewport: true, crosshair: false });
    charts.forEach(chart => link.add(chart));
    const events: string[] = [];
    charts[0].on('pan', () => events.push('pan'));
    charts[0].on('zoom', () => events.push('zoom'));
    window.__requestedCharts = { charts, indicators, events };
  });
  await paint(page);
  expect(await page.evaluate(() => window.__requestedCharts.indicators[0].values().confirmed.slice(30, 45)))
    .toEqual(new Array(15).fill(121.5));
  expect(await page.evaluate(() => window.__requestedCharts.indicators[0].values().developing[30])).toBe(129.5);
  const ink = await page.evaluate(() => {
    const counts = { confirmed: 0, developing: 0 };
    for (const canvas of document.querySelectorAll<HTMLCanvasElement>('#first canvas')) {
      const context = canvas.getContext('2d');
      if (!context) continue;
      const pixels = context.getImageData(0, 80, Math.min(520, canvas.width), Math.min(420, canvas.height - 80)).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 238 && pixels[i + 1] === 170 && pixels[i + 2] === 34) counts.confirmed++;
        if (pixels[i] === 68 && pixels[i + 1] === 136 && pixels[i + 2] === 255) counts.developing++;
      }
    }
    return counts;
  });
  expect(ink.confirmed).toBeGreaterThan(200);
  expect(ink.developing).toBeGreaterThan(200);
  const initial = await page.locator('#first').screenshot();
  await page.evaluate(() => {
    const scale = window.__requestedCharts.charts[0].timeScale;
    scale.zoomAtX(270, 1.5);
    scale.setRightOffset(scale.rightOffset - 8);
  });
  await paint(page);
  const first = await page.locator('#first').screenshot();
  const second = await page.locator('#second').screenshot();
  expect(first.equals(initial)).toBe(false);
  expect(first.equals(second)).toBe(true);
  expect(await page.evaluate(() => window.__requestedCharts.events)).toEqual(['zoom', 'pan']);
  await page.screenshot({ path: info.outputPath('requested-linked-charts.png') });
  expect(errors).toEqual([]);
});
