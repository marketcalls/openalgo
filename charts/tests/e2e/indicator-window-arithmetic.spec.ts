import { expect, test, type Page } from '@playwright/test';
import type * as Charts from '../../src/index';
import type * as Indicators from '../../src/indicators/index';

declare global {
  interface Window {
    __windowArithmetic: {
      chart: Charts.Chart;
      source: Charts.SeriesApi;
      math: typeof Indicators;
      lib: typeof Charts;
      study?: Charts.IndicatorApi;
      paint: () => Promise<void>;
      ink: (series: Charts.SeriesApi, pane: number, index: number, value: number, color: readonly number[]) => number;
    };
  }
}

async function fixture(page: Page) {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/window-arithmetic.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><style>html,body{margin:0;background:#101010}#chart{width:900px;height:600px}</style><div id="chart"></div>',
  }));
  await page.goto('/window-arithmetic.html');
  await page.evaluate(async () => {
    const baseUrl = '/dist/openalgo-charts.mjs';
    const indicatorUrl = '/dist/openalgo-charts.indicators.mjs';
    const lib = await import(baseUrl) as typeof Charts;
    const math = await import(indicatorUrl) as typeof Indicators;
    const chart = lib.createChart(document.getElementById('chart')!, {
      theme: lib.darkTheme, branding: false, animZoom: false, animAutoscale: false,
      timeNavigator: false, pixelRatio: () => 1, timezone: 'UTC',
    });
    const source = chart.addSeries('line', { style: { color: '#888888' } });
    window.__windowArithmetic = {
      lib, math, chart, source,
      paint: () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
      ink: (series, paneIndex, index, value, color) => {
        const pane = chart.panes()[paneIndex];
        const x = chart.timeScale.indexToX(index), y = series.priceScale().priceToY(value);
        const pixels = pane.base.ctx.getImageData(Math.round(x - 5), Math.round(y - 5), 11, 11).data;
        let count = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (color.every((component, channel) => Math.abs(pixels[i + channel] - component) < 12)) count++;
        }
        return count;
      },
    };
  });
}

test('MA Cross paints real events without an expired-prefix false marker', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const initial = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__windowArithmetic;
    source.setData([1e16, 3, 1, 1, 3, 1].map((close, i) => ({
      time: 1700000000 + i * 60, open: close, high: close, low: close, close,
    })));
    const study = chart.addIndicator('ma-cross', { shortLength: 1, longLength: 2, crossColor: '#ff00cc' });
    window.__windowArithmetic.study = study;
    const plot = study.series('cross')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 0, max: 4 });
    chart.setVisibleLogicalRange({ from: 1.5, to: 6 });
    await paint();
    return { values: study.values(), falseMarker: ink(plot, study.paneIndex, 3, 2, [255, 0, 204]),
      up: ink(plot, study.paneIndex, 4, 3, [255, 0, 204]), down: ink(plot, study.paneIndex, 5, 1, [255, 0, 204]) };
  });
  expect(initial.values.short).toEqual([1e16, 3, 1, 1, 3, 1]);
  expect(initial.values.long).toEqual([null, (1e16 + 3) / 2, 2, 1, 2, 2]);
  expect(initial.values.cross).toEqual([null, null, null, null, 3, 1]);
  expect(initial.falseMarker).toBe(0);
  expect(initial.up).toBeGreaterThan(1);
  expect(initial.down).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('ma-cross-current-windows.png') });

  const revised = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__windowArithmetic;
    source.update({ time: 1700000300, open: 3, high: 3, low: 3, close: 3 });
    await paint();
    return { values: study!.values().cross, removed: ink(study!.series('cross')!, study!.paneIndex, 5, 1, [255, 0, 204]) };
  });
  expect(revised.values).toEqual([null, null, null, null, 3, null]);
  expect(revised.removed).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('ma-cross-forming-recalculation.png') });
});

test('the packaged sum helper draws recovered windows and keeps missing segments clear', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const result = await page.evaluate(async () => {
    const { lib, math, chart, source, paint, ink } = window.__windowArithmetic;
    lib.registerIndicator({
      id: 'browser-window-sum', name: 'Window sum', placement: 'pane', inputs: [],
      plots: [{ key: 'sum', type: 'line', style: { color: '#ff9900', lineWidth: 3 } }],
      calc: bars => ({ sum: math.rollingSum(bars.map(bar => bar.close), 2).map(value => Number.isFinite(value) ? value : null) }),
    });
    source.setData([1e308, 1e308, 1, 2, 3, NaN, 4, 5, 6].map((close, i) => ({
      time: 1700000000 + i * 60, open: close, high: close, low: close, close,
    })));
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 0, max: 8 });
    const study = chart.addIndicator('browser-window-sum');
    const plot = study.series('sum')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 0, max: 12 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 2.5, to: 9 });
    await paint();
    return { values: study.values().sum,
      afterOverflow: ink(plot, study.paneIndex, 3.5, 4, [255, 153, 0]),
      afterGap: ink(plot, study.paneIndex, 7.5, 10, [255, 153, 0]),
      missing: ink(plot, study.paneIndex, 5.5, 6, [255, 153, 0]) };
  });
  expect(result.values).toEqual([null, null, 1e308, 3, 5, null, null, 9, 11]);
  expect(result.afterOverflow).toBeGreaterThan(1);
  expect(result.afterGap).toBeGreaterThan(1);
  expect(result.missing).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('sum-overflow-gap-recovery.png') });
});

test('the packaged weighted and deviation helpers retain chronological bits', async ({ page }) => {
  await fixture(page);
  const result = await page.evaluate(() => {
    const { math } = window.__windowArithmetic;
    return {
      weighted: math.wma([1e16, -5e15, 1 / 3], 3),
      deviation: math.stdev([10.46, 18.45, 12.48], 3),
      absolute: math.dev([15.35, 37.86, 34.97], 3),
      recovered: math.stdev([1e200, -1e200, 1, 2, 3], 2),
      compensated: math.stdev([1e308, -1e308], 2, {}),
    };
  });
  expect(result.weighted).toEqual([NaN, NaN, 1 / 6]);
  expect(result.deviation).toEqual([NaN, NaN, 3.392170724215133]);
  expect(result.absolute).toEqual([NaN, NaN, 9.36222222222222]);
  expect(result.recovered).toEqual([NaN, NaN, NaN, 0.5, 0.5]);
  expect(result.compensated).toEqual([NaN, 1e308]);
});

test('Vortex and Ultimate paint finite suffixes after expired bad windows', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__windowArithmetic;
    source.setData([1e308, 1e308, 2, NaN, 2, 2, 2, 2].map((high, i) => ({
      time: 1700000000 + i * 60, open: 1, high, low: 0, close: 1,
    })));
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 0, max: 2 });
    const vortex = chart.addIndicator('vortex', { length: 2, upColor: '#ff9900', downColor: '#00ccff' });
    const vip = vortex.series('vip')!, vim = vortex.series('vim')!;
    vip.applyOptions({ lineWidth: 6 });
    vim.applyOptions({ lineWidth: 2 });
    vip.priceScale().setAutoScale(false);
    vip.priceScale().setPriceRange({ min: 0, max: 2 });
    const ultimate = chart.addIndicator('ultimate-oscillator', { length1: 1, length2: 1, length3: 1, color: '#ff9900' });
    const uo = ultimate.series('uo')!;
    uo.applyOptions({ lineWidth: 3 });
    uo.priceScale().setAutoScale(false);
    uo.priceScale().setPriceRange({ min: 0, max: 100 });
    chart.setVisibleLogicalRange({ from: 2.5, to: 8 });
    await paint();
    return { up: vortex.values().vip.slice(6), down: vortex.values().vim.slice(6), uo: ultimate.values().uo.slice(3),
      upInk: ink(vip, vortex.paneIndex, 6.5, 1, [255, 153, 0]), downInk: ink(vim, vortex.paneIndex, 6.5, 1, [0, 204, 255]),
      uoInk: ink(uo, ultimate.paneIndex, 5.5, 50, [255, 153, 0]), uoGap: ink(uo, ultimate.paneIndex, 3.5, 50, [255, 153, 0]) };
  });
  expect(result.up).toEqual([1, 1]);
  expect(result.down).toEqual([1, 1]);
  expect(result.uo).toEqual([null, 50, 50, 50, 50]);
  expect(result.upInk).toBeGreaterThan(1);
  expect(result.downInk).toBeGreaterThan(1);
  expect(result.uoInk).toBeGreaterThan(1);
  expect(result.uoGap).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('finite-window-consumer-recovery.png') });
});

test('seeded smoothers paint recovered windows and revise the forming observation', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const result = await page.evaluate(async () => {
    const { lib, math, chart, source, paint, ink } = window.__windowArithmetic;
    lib.registerIndicator({
      id: 'browser-seeded-recovery', name: 'Seeded recovery', placement: 'pane', inputs: [],
      plots: [
        { key: 'ema', type: 'line', style: { color: '#ff9900', lineWidth: 3 } },
        { key: 'rma', type: 'line', style: { color: '#00ccff', lineWidth: 3 } },
      ],
      calc: bars => {
        const values = bars.map(bar => bar.close);
        return { ema: math.nulls(math.smaSeededEma(values, 2)), rma: math.nulls(math.rma(values, 2)) };
      },
    });
    source.setData([NaN, 1, 3, NaN, 7, 9, 11].map((close, i) => ({
      time: 1700000000 + i * 60, open: close, high: close, low: close, close,
    })));
    const study = chart.addIndicator('browser-seeded-recovery');
    window.__windowArithmetic.study = study;
    const plot = study.series('ema')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 0, max: 12 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 0.5, to: 7 });
    await paint();
    return { values: study.values(),
      ema: ink(plot, study.paneIndex, 4.5, 59 / 9, [255, 153, 0]),
      rma: ink(plot, study.paneIndex, 4.5, 5.625, [0, 204, 255]),
      gap: ink(plot, study.paneIndex, 3, 11 / 3, [255, 153, 0]),
    };
  });
  expect(result.values.ema).toEqual([null, null, 2, null, 16 / 3, 70 / 9, 268 / 27]);
  expect(result.values.rma).toEqual([null, null, 2, null, 4.5, 6.75, 8.875]);
  expect(result.ema).toBeGreaterThan(1);
  expect(result.rma).toBeGreaterThan(1);
  expect(result.gap).toBe(0);
  await page.screenshot({ path: info.outputPath('seeded-recovery.png') });
  const revision = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__windowArithmetic;
    const update = (close: number) => source.update({
      time: 1700000000 + 6 * 60, open: close, high: close, low: close, close,
    });
    update(NaN);
    await paint();
    const absent = study!.values();
    const gapInk = ink(study!.series('rma')!, study!.paneIndex, 5.5, 7.8125, [0, 204, 255]);
    update(13);
    await paint();
    const revised = study!.values();
    update(11);
    await paint();
    return { absent, gapInk, revised, restored: study!.values(),
      restoredInk: ink(study!.series('rma')!, study!.paneIndex, 5.5, 7.8125, [0, 204, 255]) };
  });
  expect(revision.absent.ema).toEqual([...result.values.ema.slice(0, -1), null]);
  expect(revision.absent.rma).toEqual([...result.values.rma.slice(0, -1), null]);
  expect(revision.gapInk).toBe(0);
  expect(revision.revised.ema).toEqual([...result.values.ema.slice(0, -1), 11.25925925925926]);
  expect(revision.revised.rma).toEqual([...result.values.rma.slice(0, -1), 9.875]);
  expect(revision.restored).toEqual(result.values);
  expect(revision.restoredInk).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('seeded-forming-restored.png') });
});

test('WaveTrend retains a genuine later crossing after an absent observation', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__windowArithmetic;
    source.setData(Array.from({ length: 23 }, (_, i) => {
      const close = i === 15 ? NaN : 100 + i / 4;
      return { time: 1700000000 + i * 60, open: close, high: close, low: close, close };
    }));
    const study = chart.addIndicator('wavetrend', {
      source: 'close', n1: 3, n2: 4, sigLen: 2, filterZone: false,
      wt1Color: '#ff9900', wt2Color: '#00ccff', buyColor: '#ff00ff', sellColor: '#ff00ff',
      showRegDiv: false, showHidDiv: false,
    });
    window.__windowArithmetic.study = study;
    const plot = study.series('wt2')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 60, max: 80 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 13.5, to: 23 });
    await paint();
    return { values: study.values(),
      falseMarker: ink(plot, study.paneIndex, 18, 68.52491228070176, [255, 0, 255]),
      genuine: ink(plot, study.paneIndex, 22, 64.88242660009399, [255, 0, 255]),
      resumedLine: ink(plot, study.paneIndex, 16.5, 70.93333333333334, [255, 153, 0]) };
  });
  expect(result.values.wt1.slice(15, 18)).toEqual([null, 72, 69.86666666666667]);
  expect(result.values.wt2.slice(15, 18)).toEqual([null, null, 70.93333333333334]);
  expect(result.values.buy).toEqual([...Array(22).fill(null), 64.88242660009399]);
  expect(result.values.sell).toEqual(Array(23).fill(null));
  expect(result.falseMarker).toBe(0);
  expect(result.genuine).toBeGreaterThan(3);
  expect(result.resumedLine).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('wavetrend-gap-crossing.png') });
  const revision = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__windowArithmetic;
    const update = (close: number) => source.update({
      time: 1700000000 + 22 * 60, open: close, high: close, low: close, close,
    });
    update(105);
    await paint();
    const removed = study!.values().buy[22];
    const removedInk = ink(study!.series('wt2')!, study!.paneIndex, 22, 64.88242660009399, [255, 0, 255]);
    update(105.5);
    await paint();
    return { removed, removedInk, restored: study!.values(),
      restoredInk: ink(study!.series('wt2')!, study!.paneIndex, 22, 64.88242660009399, [255, 0, 255]) };
  });
  expect(revision.removed).toBeNull();
  expect(revision.removedInk).toBe(0);
  expect(revision.restored).toEqual(result.values);
  expect(revision.restoredInk).toBeGreaterThan(3);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('wavetrend-forming-crossing-restored.png') });
});

test('directional averages retain state across unavailable changes without drawing stale readings', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__windowArithmetic;
    source.setData(Array.from({ length: 11 }, (_, i) => {
      const close = i === 6 ? NaN : 40 + i;
      return { time: 1700000000 + i * 60, open: close, high: close + 1, low: close - 1, close };
    }));
    const study = chart.addIndicator('adx', {
      period: 3, adxPeriod: 3, plusColor: '#ff9900', minusColor: '#00ccff', adxColor: '#ff00ff',
    });
    window.__windowArithmetic.study = study;
    const plot = study.series('plusDi')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 0, max: 120 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 2.5, to: 11 });
    await paint();
    return { values: study.values(),
      gap: ink(plot, study.paneIndex, 6.5, 50, [255, 153, 0]),
      resumed: ink(plot, study.paneIndex, 8.5, 50, [255, 153, 0]),
      strength: ink(plot, study.paneIndex, 8.5, 100, [255, 0, 255]) };
  });
  expect(result.values.plusDi).toEqual([null, null, null, 50, 50, 50, null, null, 50, 50, 50]);
  expect(result.values.minusDi).toEqual([null, null, null, 0, 0, 0, null, null, 0, 0, 0]);
  expect(result.values.adx).toEqual([null, null, null, null, null, 100, null, null, 100, 100, 100]);
  expect(result.gap).toBe(0);
  expect(result.resumed).toBeGreaterThan(1);
  expect(result.strength).toBeGreaterThan(1);
  const revision = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__windowArithmetic;
    const update = (close: number) => source.update({
      time: 1700000000 + 10 * 60, open: close, high: close + 1, low: close - 1, close,
    });
    update(NaN);
    await paint();
    const absent = study!.values();
    const gapInk = ink(study!.series('plusDi')!, study!.paneIndex, 9.5, 50, [255, 153, 0]);
    update(50);
    await paint();
    return { absent, gapInk, restored: study!.values(),
      restoredInk: ink(study!.series('plusDi')!, study!.paneIndex, 9.5, 50, [255, 153, 0]) };
  });
  for (const key of ['plusDi', 'minusDi', 'adx']) {
    expect(revision.absent[key]).toEqual([...result.values[key].slice(0, -1), null]);
  }
  expect(revision.gapInk).toBe(0);
  expect(revision.restored).toEqual(result.values);
  expect(revision.restoredInk).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('directional-gap-restored.png') });
  const flat = await page.evaluate(async () => {
    const { chart, source, study, paint, ink } = window.__windowArithmetic;
    study!.setSettings({ period: 1, adxPeriod: 2 });
    source.setData([[10, 0, 5], [11, 1, 6], [10, 2, 6], [6, 6, 6], [12, 6, 9], [11, 5, 8]]
      .map(([high, low, close], i) => ({ time: 1700000000 + i * 60, open: close, high, low, close })));
    chart.setVisibleLogicalRange({ from: 0.5, to: 6 });
    await paint();
    const plot = study!.series('adx')!;
    return { values: study!.values(),
      stale: ink(plot, study!.paneIndex, 3, 25, [255, 0, 255]),
      resumed: ink(plot, study!.paneIndex, 4.5, 81.25, [255, 0, 255]) };
  });
  expect(flat.values.plusDi).toEqual([null, 10, 0, null, 100, 0]);
  expect(flat.values.minusDi).toEqual([null, 0, 0, null, 0, (1 / 6) * 100]);
  expect(flat.values.adx).toEqual([null, null, 50, null, 75, 87.5]);
  expect(flat.stale).toBe(0);
  expect(flat.resumed).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('directional-zero-range-recovery.png') });
});
