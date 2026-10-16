import { expect, test } from '@playwright/test';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __cprPeriod: {
      source: Charts.SeriesApi;
      bars: Charts.Bar[];
      snapshot: () => Promise<{ values: readonly (number | null)[]; falseLevel: number; corrected: number; recovered: number }>;
    };
  }
}

test('CPR omits incomplete prior periods and redraws corrected observations', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/cpr-period-observations.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><style>html,body{margin:0;background:#101010}#chart{width:900px;height:600px}</style><div id="chart"></div>',
  }));
  await page.goto('/cpr-period-observations.html');
  const initial = await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.all.mjs';
    const lib = await import(url) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, {
      theme: lib.darkTheme, branding: false, animZoom: false, animAutoscale: false,
      timeNavigator: false, pixelRatio: () => 1, timezone: 'UTC',
    });
    const bars = Array.from({ length: 9 }, (_, i) => ({
      time: Date.UTC(2024, 0, 2 + Math.floor(i / 3), 9 + i % 3) / 1000,
      open: 5, high: i < 3 ? [100, NaN, 10][i] : 7, low: i < 3 ? i : 4, close: 5,
    }));
    const source = chart.addSeries('line', { style: { color: '#888888' } });
    source.setData(bars);
    const study = chart.addIndicator('cpr', {
      pivotMode: 'manual', showDaily: true, showWeekly: false, showMonthly: false,
      displaysupport: false, displayresistance: false, displaycpr: false, dPivotColor: '#ff9900',
    });
    const plot = study.series('dPivot')!;
    plot.applyOptions({ lineWidth: 3, priceLineVisible: false, lastValueVisible: false });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 0, max: 40 });
    chart.setVisibleLogicalRange({ from: -1, to: 9 });
    const ink = (index: number, value: number) => {
      const x = chart.timeScale.indexToX(index), y = plot.priceScale().priceToY(value);
      const pixels = chart.panes()[study.paneIndex].base.ctx.getImageData(Math.round(x - 2), Math.round(y - 2), 5, 5).data;
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] > 240 && Math.abs(pixels[i + 1] - 153) < 12 && pixels[i + 2] < 12) count++;
      }
      return count;
    };
    const snapshot = async () => {
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      return { values: study.values().dPivot, falseLevel: ink(3.5, 5), corrected: ink(3.5, 35), recovered: ink(6.5, 16 / 3) };
    };
    window.__cprPeriod = { source, bars, snapshot };
    return snapshot();
  });
  const expected = [null, null, null, null, null, null, 16 / 3, 16 / 3, 16 / 3];
  expect(initial.values).toEqual(expected);
  expect(initial.falseLevel).toBe(0);
  expect(initial.recovered).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('cpr-incomplete-period.png') });

  const corrected = await page.evaluate(async () => {
    const { source, bars, snapshot } = window.__cprPeriod;
    source.update({ ...bars[1], high: 20 });
    return snapshot();
  });
  expect(corrected.values).toEqual([null, null, null, 35, 35, 35, 16 / 3, 16 / 3, 16 / 3]);
  expect(corrected.corrected).toBeGreaterThan(1);
  expect(corrected.recovered).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('cpr-corrected-period.png') });

  const unavailable = await page.evaluate(async () => {
    const { source, bars, snapshot } = window.__cprPeriod;
    source.update(bars[1]);
    return snapshot();
  });
  expect(unavailable.values).toEqual(expected);
  expect(unavailable.falseLevel).toBe(0);
  expect(unavailable.corrected).toBe(0);
  expect(unavailable.recovered).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('cpr-restored-gap.png') });
});
