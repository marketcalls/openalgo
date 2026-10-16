import { expect, test, type Page } from '@playwright/test';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __numeric: {
      lib: typeof Charts;
      chart: Charts.Chart;
      source: Charts.SeriesApi;
      study?: Charts.IndicatorApi;
      paint: () => Promise<void>;
      ink: (series: Charts.SeriesApi, paneIndex: number, index: number, value: number, color?: readonly number[]) => number;
    };
  }
}

async function numericalFixture(page: Page) {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/numeric-recovery.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><style>html,body{margin:0;background:#101010}#chart{width:900px;height:600px}</style><div id="chart"></div>',
  }));
  await page.goto('/numeric-recovery.html');
  await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.all.mjs';
    const lib = await import(url) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, {
      theme: lib.darkTheme, branding: false, animZoom: false, animAutoscale: false,
      timeNavigator: false, pixelRatio: () => 1, timezone: 'UTC',
    });
    const source = chart.addSeries('line', { style: { color: '#888888' } });
    window.__numeric = {
      lib, chart, source,
      paint: () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
      ink: (series, paneIndex, index, value, color = [255, 153, 0]) => {
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

test('Hull smoothing draws the rounded-length warmup and independently calculated ramp', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/hull-numerical.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><style>html,body{margin:0;background:#101010}#chart{width:900px;height:600px}</style><div id="chart"></div>',
  }));
  await page.goto('/hull-numerical.html');
  const result = await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.all.mjs';
    const lib = await import(url) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, {
      theme: lib.darkTheme, animZoom: false, timeNavigator: false, pixelRatio: () => 1,
    });
    chart.addSeries('candlestick').setData(Array.from({ length: 20 }, (_, i) => ({
      time: 1700000000 + i * 60, open: i + 1, high: i + 2, low: i, close: i + 1, volume: 1,
    })));
    const study = chart.addIndicator('hma', { length: 13, color: '#ff9900' });
    chart.setVisibleLogicalRange({ from: 10, to: 21 });
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const canvas = chart.panes()[study.paneIndex].base.element;
    const x = chart.timeScale.indexToX(17.5);
    const y = study.series('hma')!.priceScale().priceToY(18.5 - 1 / 3);
    const pixels = canvas.getContext('2d')!.getImageData(Math.round(x - 4), Math.round(y - 4), 9, 9).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 240 && Math.abs(pixels[i + 1] - 153) < 10 && pixels[i + 2] < 10) ink++;
    }
    return { values: study.values().hma, ink };
  });
  expect(result.values.slice(0, 15)).toEqual(Array(15).fill(null));
  for (let i = 15; i < 20; i++) expect(result.values[i]).toBeCloseTo(i + 1 - 1 / 3, 12);
  expect(result.ink).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('hull-lengths.png') });
});

test('directional strength draws the independently calculated seed and next reading', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/numerical-indicators.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><style>html,body{margin:0;background:#101010}#chart{width:900px;height:600px}</style><div id="chart"></div>',
  }));
  await page.goto('/numerical-indicators.html');
  const result = await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.all.mjs';
    const lib = await import(url) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, {
      theme: lib.darkTheme, animZoom: false, timeNavigator: false, pixelRatio: () => 1,
    });
    chart.addSeries('candlestick').setData([
      [10, 8, 9], [12, 9, 11], [11, 7, 8], [13, 9, 12], [12, 10, 11],
    ].map(([high, low, close], index) => ({
      time: 1700000000 + index * 60, open: close, high, low, close, volume: 100,
    })));
    const study = chart.addIndicator('adx', { period: 2, adxPeriod: 2, adxColor: '#ff9900' });
    chart.setVisibleLogicalRange({ from: -1, to: 5 });
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const pane = chart.panes()[study.paneIndex];
    const x = chart.timeScale.indexToX(3.5);
    const y = study.series('adx')!.priceScale().priceToY(31.25);
    const pixels = pane.base.element.getContext('2d')!.getImageData(
      Math.round(x - 4), Math.round(y - 4), 9, 9,
    ).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 240 && Math.abs(pixels[i + 1] - 153) < 10 && pixels[i + 2] < 10) ink++;
    }
    return { values: study.values(), ink };
  });
  expect(result.values.adx).toEqual([null, null, null, 25, 37.5]);
  expect(result.values.plusDi[4]).toBeCloseTo(24, 12);
  expect(result.values.minusDi[4]).toBeCloseTo(8, 12);
  expect(result.ink).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('directional-seed.png') });
});

test('RSI draws recovered finite suffixes and leaves missing deltas unpainted', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData([NaN, 1, 2, 3, 2, 3, NaN, 4, 5, 4].map((close, i) => ({
      time: 1700000000 + i * 60, open: close, high: close, low: close, close,
    })));
    const study = chart.addIndicator('rsi', { length: 2, color: '#ff9900' });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 10 });
    await paint();
    const plot = study.series('rsi')!;
    return { values: study.values().rsi, initial: ink(plot, study.paneIndex, 4.5, 62.5),
      recovered: ink(plot, study.paneIndex, 8.5, 65.625), gap: ink(plot, study.paneIndex, 6.5, 75) };
  });
  expect(result.values).toEqual([null, null, null, 100, 50, 75, null, null, 87.5, 43.75]);
  expect(result.initial).toBeGreaterThan(1);
  expect(result.recovered).toBeGreaterThan(1);
  expect(result.gap).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('rsi-finite-recovery.png') });
});

test('Balance of Power omits an overflowing range and paints the later finite ratio', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData([
      [10, 14, 6, 12], [10, 14, 6, 14], [0, 1e308, -1e308, 1],
      [10, 14, 6, 12], [10, 14, 6, 14],
    ].map(([open, high, low, close], i) => ({ time: 1700000000 + i * 60, open, high, low, close })));
    const study = chart.addIndicator('balance-of-power', { color: '#ff9900' });
    const plot = study.series('bop')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -0.25, max: 0.75 });
    chart.setVisibleLogicalRange({ from: -1, to: 5 });
    await paint();
    return { values: study.values().bop, recovered: ink(plot, study.paneIndex, 3.5, 0.375),
      unavailable: ink(plot, study.paneIndex, 2, 0) };
  });
  expect(result.values).toEqual([0.25, 0.5, null, 0.25, 0.5]);
  expect(result.recovered).toBeGreaterThan(1);
  expect(result.unavailable).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('bop-overflow-gap.png') });
});

test('MFI paints finite windows and removes unavailable overflowing money flow', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const initial = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    const volume = [1, 1, 2, 1, 1e308, 1, 1, 1, 1];
    source.setData([1, 2, 1, 2, 3, 2, 1, 2, 3].map((close, i) => ({
      time: 1700000000 + i * 60, open: close, high: close + 1, low: close - 1,
      close, volume: volume[i],
    })));
    const study = chart.addIndicator('mfi', { period: 2, color: '#ff9900' });
    window.__numeric.study = study;
    const plot = study.series('mfi')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -10, max: 110 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 9 });
    await paint();
    return { values: study.values().mfi, ordinary: ink(plot, study.paneIndex, 2.5, 50),
      recovered: ink(plot, study.paneIndex, 7.5, (100 - 100 / 3 + 100) / 2),
      unavailable: ink(plot, study.paneIndex, 4.5, 100) };
  });
  expect(initial.values).toEqual([null, null, 50, 50, null, null, 0, 100 - 100 / 3, 100]);
  expect(initial.ordinary).toBeGreaterThan(1);
  expect(initial.recovered).toBeGreaterThan(1);
  expect(initial.unavailable).toBe(0);
  await page.screenshot({ path: info.outputPath('mfi-finite-recovery.png') });

  const forming = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__numeric;
    source.update({ time: 1700000000 + 8 * 60, open: 3, high: 4, low: 2, close: 3, volume: 1e308 });
    await paint();
    return { values: study!.values().mfi,
      stale: ink(study!.series('mfi')!, study!.paneIndex, 7.5, (100 - 100 / 3 + 100) / 2) };
  });
  expect(forming.values[8]).toBeNull();
  expect(forming.stale).toBe(0);
  const restored = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__numeric;
    source.update({ time: 1700000000 + 8 * 60, open: 3, high: 4, low: 2, close: 3, volume: 1 });
    await paint();
    return { values: study!.values().mfi,
      line: ink(study!.series('mfi')!, study!.paneIndex, 7.5, (100 - 100 / 3 + 100) / 2) };
  });
  expect(restored.values).toEqual(initial.values);
  expect(restored.line).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('mfi-replaced-forming-flow.png') });
});

test('WaveTrend draws a genuine crossing but no marker for equal finite lines', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const flat = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(Array.from({ length: 10 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100 + i / 4, high: 101 + i / 4,
      low: 99 + i / 4, close: 100 + i / 4, volume: 0,
    })));
    const study = chart.addIndicator('wavetrend', {
      source: 'close', n1: 3, n2: 4, sigLen: 2, filterZone: false,
      wt1Color: '#ff9900', wt2Color: '#ff9900', buyColor: '#ff00ff', sellColor: '#ff00ff',
      showRegDiv: false, showHidDiv: false,
    });
    window.__numeric.study = study;
    const plot = study.series('wt2')!;
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -120, max: 120 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 5, to: 12 });
    await paint();
    return { values: study.values(), marker: ink(plot, study.paneIndex, 9, 1 / 0.015, [255, 0, 255]),
      line: ink(plot, study.paneIndex, 8.5, 1 / 0.015) };
  });
  expect(flat.values.wt1.slice(7)).toEqual([1 / 0.015, 1 / 0.015, 1 / 0.015]);
  expect(flat.values.wt2.slice(8)).toEqual([1 / 0.015, 1 / 0.015]);
  expect(flat.values.buy).toEqual(Array(10).fill(null));
  expect(flat.values.sell).toEqual(Array(10).fill(null));
  expect(flat.marker).toBe(0);
  expect(flat.line).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('wavetrend-equal-no-signal.png') });
  const crossed = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__numeric;
    source.update({ time: 1700000000 + 10 * 60, open: 100, high: 101, low: 99, close: 100, volume: 0 });
    await paint();
    const values = study!.values(), price = values.wt2[10]!;
    return { values, marker: ink(study!.series('wt2')!, study!.paneIndex, 10, price, [255, 0, 255]) };
  });
  expect(crossed.values.wt1[10]!).toBeLessThan(crossed.values.wt2[10]!);
  expect(crossed.values.sell[10]).toBe(crossed.values.wt2[10]);
  expect(crossed.values.buy[10]).toBeNull();
  expect(crossed.marker).toBeGreaterThan(3);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('wavetrend-genuine-signal.png') });
});

test('AlphaTrend paints a recovered band after the overflowing window expires', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(Array.from({ length: 6 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100, close: 100,
      high: i === 1 || i === 2 ? 1e308 : 102, low: i === 1 || i === 2 ? 0 : 98, volume: 0,
    })));
    const study = chart.addIndicator('alphatrend', { AP: 2, color: '#ff9900' });
    const plot = study.series('alphatrend')!;
    plot.applyOptions({ color: '#ff9900', lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -10, max: 110 });
    chart.setVisibleLogicalRange({ from: -1, to: 6 });
    await paint();
    return { values: study.values(), recovered: ink(plot, study.paneIndex, 4.5, 94) };
  });
  expect(result.values.alphatrend).toEqual([null, null, null, 0, 94, 94]);
  expect(result.recovered).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('alphatrend-finite-recovery.png') });
});

test('Seasonality paints finite completed-month cells and omits unavailable changes', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, lib, paint } = window.__numeric;
    const data = [1e308, -1e308, 100, 120, 110].map((close, i) => ({
      time: Date.UTC(2024, i, 15) / 1000, open: close, high: close, low: close, close,
    }));
    source.setData(data);
    const study = chart.addIndicator('seasonality', { startYear: 1800 });
    chart.setPaneWeight(study.paneIndex, 2);
    const pane = chart.panes()[study.paneIndex], painted: string[] = [];
    const original = pane.top.ctx.fillText.bind(pane.top.ctx);
    pane.top.ctx.fillText = (text, x, y, maxWidth) => {
      painted.push(text);
      if (maxWidth === undefined) original(text, x, y); else original(text, x, y, maxWidth);
    };
    chart.setVisibleLogicalRange({ from: -1, to: 5 });
    await paint();
    const descriptor = lib.getIndicator('seasonality')!;
    const rows = descriptor.table!({ bars: data, settings: { ...study.settings(), timezone: 'UTC' }, values: study.values() })!.rows;
    const pixels = pane.top.ctx.getImageData(0, 0, pane.top.element.width, pane.top.element.height).data;
    let tableInk = 0;
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i + 1] > pixels[i] + 30 && pixels[i + 1] > pixels[i + 2] + 5) tableInk++;
    return { rows: rows.map(row => row.map(cell => cell.text ?? '')), painted, tableInk };
  });
  const year = result.rows.find(row => row[0] === '2024')!;
  const average = result.rows.find(row => row[0] === 'Avgs:')!;
  expect(year[2]).toBe('');
  expect(average[2]).toBe('');
  expect(year[4]).toBe('20.00%');
  expect(average[4]).toBe('20.00%');
  expect(result.rows.flat().some(text => /NaN|Infinity/.test(text))).toBe(false);
  expect(result.painted.some(text => /NaN|Infinity/.test(text))).toBe(false);
  expect(result.painted).toContain('20.00%');
  expect(result.tableInk).toBeGreaterThan(20);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('seasonality-finite-table.png') });
});

// Open, high, low, close and volume rows; NaN marks what the feed did not send.
// Bar 2 of GAP_ROWS has no high, the numerical audit's ATR hole.
const GAP_ROWS = [
  [9, 10, 8, 9, 1], [9, 12, 9, 11, 1], [11, NaN, 10, 11, 1],
  [11, 14, 11, 13, 1], [13, 13, 10, 11, 1], [11, 12, 10, 12, 1],
];

test('ATR and Supertrend resume after a missing high and never bridge it', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async (rows) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(rows.map(([open, high, low, close, volume], i) => ({
      time: 1700000000 + i * 60, open, high, low, close, volume,
    })));
    const study = chart.addIndicator('atr', { period: 2, color: '#ff9900' });
    const trend = chart.addIndicator('supertrend', { period: 2, multiplier: 1, downColor: '#00c8ff' });
    window.__numeric.study = study;
    const plot = study.series('atr')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 2, max: 3.25 });
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 8, max: 15 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 6 });
    await paint();
    const band = trend.series('down')!;
    return {
      atr: study.values().atr, down: trend.values().down,
      resumed: ink(plot, study.paneIndex, 3.5, (2.75 + 2.875) / 2),
      bridged: ink(plot, study.paneIndex, 2, (2.5 + 2.75) / 2),
      band: ink(band, 0, 4.5, 13, [0, 200, 255]),
    };
  }, GAP_ROWS);
  expect(result.atr).toEqual([null, 2.5, null, 2.75, 2.875, 2.4375]);
  expect(result.down).toEqual([null, 13, null, 13, 13, 13]);
  expect(result.resumed).toBeGreaterThan(1);
  expect(result.bridged).toBe(0);
  expect(result.band).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('atr-gap-recovery.png') });

  // A forming bar that arrives without its high is a gap of its own, and the
  // complete bar that replaces it restores the reading.
  const forming = await page.evaluate(async () => {
    const { source, study, paint, ink } = window.__numeric;
    source.update({ time: 1700000000 + 5 * 60, open: 11, high: NaN, low: 10, close: 12, volume: 1 });
    await paint();
    const gap = { values: study!.values().atr, line: ink(study!.series('atr')!, study!.paneIndex, 4.5, (2.875 + 2.4375) / 2) };
    source.update({ time: 1700000000 + 5 * 60, open: 11, high: 12, low: 10, close: 12, volume: 1 });
    await paint();
    return { gap, values: study!.values().atr, line: ink(study!.series('atr')!, study!.paneIndex, 4.5, (2.875 + 2.4375) / 2) };
  });
  expect(forming.gap.values[5]).toBeNull();
  expect(forming.gap.line).toBe(0);
  expect(forming.values).toEqual(result.atr);
  expect(forming.line).toBeGreaterThan(1);
  expect(errors).toEqual([]);
});

test('VWAP and its band continue past a bar with a NaN volume', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData([
      [10, 11, 9, 10, 100], [10, 12, 10, 11, NaN], [11, 13, 11, 12, 100], [12, 13, 11, 12, 200],
    ].map(([open, high, low, close, volume], i) => ({ time: 1700000000 + i * 60, open, high, low, close, volume })));
    const study = chart.addIndicator('vwap', { anchor: 'continuous', color: '#ff9900', band1Color: '#00c8ff' });
    const line = study.series('vwap')!;
    line.applyOptions({ lineWidth: 3 });
    study.series('upper1')!.applyOptions({ lineWidth: 3 });
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 9, max: 13 });
    chart.setVisibleLogicalRange({ from: -1, to: 4 });
    await paint();
    return {
      values: study.values(),
      resumed: ink(line, 0, 2.5, 11.25),
      bridged: ink(line, 0, 1, 10.5),
      band: ink(study.series('upper1')!, 0, 2.5, (12 + 11.5 + Math.sqrt(0.75)) / 2, [0, 200, 255]),
    };
  });
  expect(result.values.vwap).toEqual([10, null, 11, 11.5]);
  expect(result.values.upper1).toEqual([10, null, 12, 11.5 + Math.sqrt(0.75)]);
  expect(result.resumed).toBeGreaterThan(1);
  expect(result.bridged).toBe(0);
  expect(result.band).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('vwap-nan-volume.png') });
});

test('Parabolic SAR and OBV keep drawing after an incomplete bar', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData([
      [10, 11, 9, 10, 100], [10, 12, 10, 11, NaN], [11, 13, NaN, 12, 100],
      [12, 14, 12, 13, 100], [13, 15, 13, 14, 100], [14, 16, 14, 15, 100],
    ].map(([open, high, low, close, volume], i) => ({ time: 1700000000 + i * 60, open, high, low, close, volume })));
    const sar = chart.addIndicator('parabolic-sar', { color: '#ff9900' });
    const obv = chart.addIndicator('obv', { color: '#00c8ff' });
    const dots = sar.series('sar')!;
    dots.applyOptions({ markerRadius: 4 });
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 8, max: 17 });
    const total = obv.series('obv')!;
    total.applyOptions({ lineWidth: 3 });
    total.priceScale().setAutoScale(false);
    total.priceScale().setPriceRange({ min: -50, max: 450 });
    chart.setPaneWeight(obv.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 6 });
    await paint();
    const values = sar.values().sar;
    return {
      sar: values, obv: obv.values().obv,
      lateDot: ink(dots, 0, 5, values[5]!),
      holeDot: ink(dots, 0, 2, 9),
      obvLine: ink(total, obv.paneIndex, 4.5, 350, [0, 200, 255]),
    };
  });
  expect(result.sar[2]).toBeNull();
  expect(result.sar.slice(3).every(value => value !== null)).toBe(true);
  expect(result.obv).toEqual([0, 0, 100, 200, 300, 400]);
  expect(result.lateDot).toBeGreaterThan(3);
  expect(result.holeDot).toBe(0);
  expect(result.obvLine).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('psar-obv-incomplete-bar.png') });
});

test('Supertrend holds its side and A/D keeps drawing across a missing close', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const result = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    // A steady fall. Every true range is 2, so the ATR is 2 and the upper band sits
    // at close + 2.5. Bar 6 has no close: bar 7's true range reads it and has no
    // ATR, and every close sits a quarter of the range from the low, so each
    // complete bar moves A/D by -50.
    source.setData(Array.from({ length: 10 }, (_, i) => {
      const c = 20 - 0.5 * i;
      return { time: 1700000000 + i * 60, open: c, high: c + 1.5, low: c - 0.5, close: i === 6 ? NaN : c, volume: 100 };
    }));
    const trend = chart.addIndicator('supertrend', { period: 3, multiplier: 1, upColor: '#ff9900', downColor: '#00c8ff' });
    const flow = chart.addIndicator('adl', { color: '#ff9900' });
    trend.series('down')!.applyOptions({ lineWidth: 3 });
    const line = flow.series('adl')!;
    line.applyOptions({ lineWidth: 3 });
    line.priceScale().setAutoScale(false);
    line.priceScale().setPriceRange({ min: -500, max: 0 });
    source.priceScale().setAutoScale(false);
    source.priceScale().setPriceRange({ min: 12, max: 23 });
    chart.setPaneWeight(flow.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 10 });
    await paint();
    const down = trend.series('down')!;
    const up = trend.series('up')!;
    return {
      values: trend.values(), adl: flow.values().adl,
      resumed: ink(down, 0, 8.5, 18.25, [0, 200, 255]),
      bridged: ink(down, 0, 6.5, 19.25, [0, 200, 255]),
      // Where the flipped support line of the NaN comparison used to run.
      flipped: ink(up, 0, 8.5, 14.5, [255, 153, 0]),
      flowResumed: ink(line, flow.paneIndex, 7.5, -375),
      flowBridged: ink(line, flow.paneIndex, 6, -325),
    };
  });
  expect(result.values.down).toEqual([null, null, 21.5, 21, 20.5, 20, null, null, 18.5, 18]);
  expect(result.values.up).toEqual(Array(10).fill(null));
  expect(result.adl).toEqual([-50, -100, -150, -200, -250, -300, null, -350, -400, -450]);
  expect(result.resumed).toBeGreaterThan(1);
  expect(result.bridged).toBe(0);
  expect(result.flipped).toBe(0);
  expect(result.flowResumed).toBeGreaterThan(1);
  expect(result.flowBridged).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('supertrend-adl-missing-close.png') });
});

type Row = readonly [number, number, number, number];
const rowsToBars = (rows: readonly Row[]) => rows.map(([open, high, low, close], i) => ({
  time: 1700000000 + i * 60, open, high, low, close, volume: 1,
}));

test('CCI leaves the window holding a missing high unpainted instead of drawing 0', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const bars = rowsToBars([
    [10, 11, 9, 10], [10, 12, 10, 11], [11, NaN, 10, 12], [12, 13, 11, 12],
    [12, 14, 12, 13], [13, 15, 12, 14], [14, 16, 13, 15],
  ]);
  const result = await page.evaluate(async (data) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(data);
    const study = chart.addIndicator('cci', { period: 3, maType: 'None', color: '#ff9900' });
    const plot = study.series('cci')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -20, max: 120 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 7 });
    await paint();
    return { values: study.values().cci, recovered: ink(plot, study.paneIndex, 5.5, 93.75),
      zero: ink(plot, study.paneIndex, 3, 0) };
  }, bars);
  expect(result.values).toEqual([null, null, null, null, null, 87.50000000000006, 100.0000000000001]);
  expect(result.recovered).toBeGreaterThan(1);
  expect(result.zero).toBe(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('cci-missing-window.png') });
});

test('Fisher Transform paints again on the bars after a missing midpoint', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const bars = rowsToBars([
    [10, 11, 9, 10], [10, 12, 10, 11], [11, 13, 10, 12], [12, NaN, 11, 12],
    [12, 14, 12, 13], [13, 15, 12, 14], [14, 16, 13, 15],
  ]);
  const result = await page.evaluate(async (data) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(data);
    const study = chart.addIndicator('fisher-transform', { length: 2, fisherColor: '#ff9900', triggerColor: '#00ffff' });
    const plot = study.series('fisher')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: -1, max: 1.2 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 7 });
    await paint();
    const values = study.values().fisher;
    return { values, recovered: ink(plot, study.paneIndex, 5.5, (values[5]! + values[6]!) / 2) };
  }, bars);
  expect(result.values).toEqual([
    null, 0.34282825441539394, 0.7913738721291064, null,
    -0.34282825441539394, -0.06208054853744893, 0.39614103556792124,
  ]);
  expect(result.recovered).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('fisher-missing-midpoint.png') });
});

test('RVI and Mass Index resume on the bar after a gap instead of reseeding', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const rvi = rowsToBars(Array.from({ length: 40 }, (_, i): Row => {
    if (i === 20) return [NaN, NaN, NaN, NaN];
    const c = 100 + ((i * 7) % 5) - ((i * 3) % 4);
    return [c, c + 1, c - 1, c];
  }));
  const first = await page.evaluate(async (data) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(data);
    const study = chart.addIndicator('relative-volatility-index', { length: 2, maType: 'None', color: '#ff9900' });
    window.__numeric.study = study;
    const plot = study.series('rvi')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 30, max: 75 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 15, to: 30 });
    await paint();
    const values = study.values().rvi;
    return { values, resumed: ink(plot, study.paneIndex, 22.5, (values[22]! + values[23]!) / 2) };
  }, rvi);
  expect(first.values.slice(19, 24)).toEqual([54.149295689517594, null, null, 61.120663786150075, 54.720663337316736]);
  expect(first.resumed).toBeGreaterThan(1);
  await page.screenshot({ path: info.outputPath('rvi-gap-resume.png') });

  const mass = rowsToBars(Array.from({ length: 45 }, (_, i): Row => {
    const c = 100 + (i % 4);
    return i === 25 ? [101, NaN, 99, 101] : [c, c + 1 + (i % 3), c - 1, c];
  }));
  const second = await page.evaluate(async (data) => {
    const { chart, source, study, paint, ink } = window.__numeric;
    study!.remove();
    source.setData(data);
    const mi = chart.addIndicator('mass-index', { length: 3, color: '#ff9900' });
    const plot = mi.series('mi')!;
    plot.applyOptions({ lineWidth: 3 });
    plot.priceScale().setAutoScale(false);
    plot.priceScale().setPriceRange({ min: 2.98, max: 3.01 });
    chart.setPaneWeight(mi.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: 20, to: 40 });
    await paint();
    const values = mi.values().mi;
    return { values, resumed: ink(plot, mi.paneIndex, 28.5, (values[28]! + values[29]!) / 2) };
  }, mass);
  expect(second.values.slice(24, 30)).toEqual([
    3.013616226598646, null, null, null, 2.9934105582882236, 2.9968084394205077,
  ]);
  expect(second.resumed).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('mass-index-gap-resume.png') });
});

test('Trend Strength Index paints a reading at a price level of one billion', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  // Offsets 0, 1, 3, 2, 4, 5 from 1e9: every 4-bar window correlates 0.8 with
  // its bar index (deviations of 1.5 and 0.5 give cross 4 over squares 5).
  const bars = rowsToBars([0, 1, 3, 2, 4, 5].map((d): Row => {
    const c = 1e9 + d;
    return [c, c, c, c];
  }));
  const result = await page.evaluate(async (data) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(data);
    const study = chart.addIndicator('trend-strength-index', { length: 4, color: '#ff9900' });
    const plot = study.series('tsi')!;
    plot.applyOptions({ lineWidth: 3 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 6 });
    await paint();
    return { values: study.values().tsi, line: ink(plot, study.paneIndex, 4.5, 0.8) };
  }, bars);
  expect(result.values.slice(0, 3)).toEqual([null, null, null]);
  for (const value of result.values.slice(3)) expect(value!).toBeCloseTo(0.8, 12);
  expect(result.line).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('trend-strength-large-level.png') });
});

test('NVI and its average paint on through a bar with no close', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  // Volume falls on every bar, so every bar qualifies for NVI. Bar 2 has no
  // close: the index holds there and on bar 3, then compounds 132/120.
  const closes = [100, 110, NaN, 120, 132, 145.2, 159.72, 175.692];
  const bars = closes.map((close, i) => ({
    time: 1700000000 + i * 60, open: close, high: close, low: close, close, volume: 80 - 10 * i,
  }));
  const result = await page.evaluate(async (data) => {
    const { chart, source, paint, ink } = window.__numeric;
    source.setData(data);
    const study = chart.addIndicator('nvi', { maLength: 2, color: '#ff9900', emaColor: '#00ffff' });
    const line = study.series('nvi')!;
    const average = study.series('ema')!;
    line.applyOptions({ lineWidth: 3 });
    average.applyOptions({ lineWidth: 3 });
    line.priceScale().setAutoScale(false);
    line.priceScale().setPriceRange({ min: 950, max: 1800 });
    chart.setPaneWeight(study.paneIndex, 1.5);
    chart.setVisibleLogicalRange({ from: -1, to: 8 });
    await paint();
    const values = study.values();
    const nvi = values.nvi as number[];
    const ema = values.ema as number[];
    return {
      nvi, ema,
      held: ink(line, study.paneIndex, 2.5, 1100),
      resumed: ink(line, study.paneIndex, 4.5, (nvi[4] + nvi[5]) / 2),
      averageResumed: ink(average, study.paneIndex, 4.5, (ema[4] + ema[5]) / 2, [0, 255, 255]),
    };
  }, bars);
  expect(result.nvi.slice(0, 5)).toEqual([1000, 1100, 1100, 1100, (110 / 100) * (132 / 120) * 1000]);
  expect(result.nvi.every(v => v !== null)).toBe(true);
  expect(result.ema.slice(1).every(v => v !== null)).toBe(true);
  expect(result.held).toBeGreaterThan(1);
  expect(result.resumed).toBeGreaterThan(1);
  expect(result.averageResumed).toBeGreaterThan(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('nvi-missing-close.png') });
});

test('Ichimoku draws its spans from a fractional period instead of failing its calculation', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await numericalFixture(page);
  const fractional = await page.evaluate(async () => {
    const { chart, source, paint, ink } = window.__numeric;
    // A unit ramp: close = 100 + i, each bar one either side of it.
    source.setData(Array.from({ length: 90 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 0,
    })));
    // 9.4 is what a settings blob can carry; it used to index bar 8.4 and throw.
    const study = chart.addIndicator('ichimoku', { conversionPeriod: 9.4, spanAColor: '#ff9900' });
    window.__numeric.study = study;
    const spanA = study.series('spanA')!;
    spanA.applyOptions({ lineWidth: 3 });
    // Wide enough to hold the stretch where both spans, and so the cloud, print.
    chart.setVisibleLogicalRange({ from: 45, to: 92 });
    await paint();
    const values = study.values();
    return { values, painted: ink(spanA, study.paneIndex, 60, values.spanA[60] ?? NaN) };
  });
  await page.screenshot({ path: info.outputPath('ichimoku-fractional-period.png') });
  const whole = await page.evaluate(async () => {
    const { study, paint } = window.__numeric;
    study!.setSettings({ conversionPeriod: 9 });
    await paint();
    return study!.values();
  });
  // Span A is (conversion + base) / 2 drawn 26 bars forward: at bar 25 that is
  // ((126 + 116) / 2 + (126 + 99) / 2) / 2, landing on index 51.
  expect(fractional.values.spanA[50]).toBeNull();
  expect(fractional.values.spanA[51]).toBeCloseTo(116.75, 9);
  expect(fractional.values).toEqual(whole);
  expect(fractional.painted).toBeGreaterThan(1);
  expect(errors).toEqual([]);
});
