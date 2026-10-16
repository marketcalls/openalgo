import { writeFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __outputTargets: { chart: Chart; study: IndicatorApi; clicks: string[] };
    __shadingExample: { chart: Chart; lib: typeof Charts };
  }
}

async function painted(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** Exact-colour ink per pane: the routed box, the routed marker and the plot-bound label. */
async function inkByPane(page: Page) {
  return page.evaluate(() => window.__outputTargets.chart.panes().map(pane => {
    const counts = { box: 0, dot: 0, label: 0 };
    for (const canvas of pane.element.querySelectorAll('canvas')) {
      const ctx = canvas.getContext('2d');
      if (!ctx || canvas.width === 0 || canvas.height === 0) continue;
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] !== 255) continue;
        const [r, g, b] = [pixels[i], pixels[i + 1], pixels[i + 2]];
        if (r === 204 && g === 34 && b === 68) counts.box++;
        if (r === 238 && g === 204 && b === 34) counts.dot++;
        if (r === 153 && g === 51 && b === 204) counts.label++;
      }
    }
    return counts;
  }));
}

test('routed study drawings and markers paint where they are sent and follow the study', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 700 });
  await page.route('**/output-targets.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/output-targets.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    const source = chart.addSeries('candlestick');
    source.setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    lib.registerIndicator({
      id: 'native-output-targets', name: 'Routed outputs', placement: 'pane',
      inputs: [{ key: 'onPrice', label: 'On price', type: 'boolean', default: true }],
      plots: [
        { key: 'osc', type: 'line', title: 'Osc', style: { color: '#ffffff' } },
        { key: 'alt', type: 'line', title: 'Alt', style: { color: '#888888' } },
      ],
      calc: bars => ({ osc: bars.map((_, i) => 30 + (i % 10)), alt: bars.map((_, i) => 500 + i) }),
      // Priced in the units of wherever the box is sent: the candles, or the oscillator.
      draws: ({ bars, settings }) => [
        { kind: 'box', from: { time: bars[20].time, price: settings.onPrice ? 104 : 37 }, to: { time: bars[35].time, price: settings.onPrice ? 96 : 32 },
          color: '#cc2244', fillColor: '#cc2244', opacity: 1, id: 'zone', ...(settings.onPrice ? { overlay: true } : {}) },
        { kind: 'label', at: { time: bars[45].time, price: 530 }, text: 'ALT', color: '#9933cc', textColor: '#9933cc', plot: 'alt' },
      ],
      markers: ({ bars }) => [{ time: bars[10].time, position: 'belowBar', shape: 'circle', size: 'big', color: '#eecc22', id: 'dot', overlay: true }],
    });
    const study = chart.addIndicator('native-output-targets', {}, { plotPriceScaleIds: { alt: 'left' } });
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    const clicks: string[] = [];
    chart.subscribeClick(id => { clicks.push(id); });
    window.__outputTargets = { chart, study, clicks };
  });
  await painted(page);
  const first = await inkByPane(page);
  expect(first).toHaveLength(2);
  expect(first[0].box).toBeGreaterThan(1000);
  expect(first[0].dot).toBeGreaterThan(20);
  expect(first[1]).toMatchObject({ box: 0, dot: 0 });
  expect(first[1].label).toBeGreaterThan(20);
  await page.screenshot({ path: info.outputPath('output-targets.png') });

  // The box reports its id where it is drawn, on the price pane.
  const point = await page.evaluate(() => {
    const { chart } = window.__outputTargets;
    const box = document.querySelector('#chart')!.getBoundingClientRect();
    return { x: box.left + chart.timeToCoordinate(1700000000 + 27 * 60), y: box.top + chart.priceToCoordinate(100, 0)! };
  });
  await page.mouse.click(point.x, point.y);
  await expect.poll(() => page.evaluate(() => window.__outputTargets.clicks)).toEqual(['zone']);

  await page.evaluate(() => window.__outputTargets.study.setVisible(false));
  await painted(page);
  expect(await inkByPane(page)).toEqual([{ box: 0, dot: 0, label: 0 }, { box: 0, dot: 0, label: 0 }]);
  await page.evaluate(() => window.__outputTargets.study.setVisible(true));
  await painted(page);
  expect((await inkByPane(page))[0].box).toBeGreaterThan(1000);

  // A second instance owns a price-pane box of its own. Moving the first to a new
  // pane leaves its routed layers on the candles and takes its plot label along.
  await page.evaluate(() => {
    const { chart, study } = window.__outputTargets;
    chart.addIndicator('native-output-targets', {}, { plotPriceScaleIds: { alt: 'left' } });
    chart.moveIndicator(study.id, chart.panes().length);
  });
  await painted(page);
  const moved = await page.evaluate(() => window.__outputTargets.study.paneIndex);
  const afterMove = await inkByPane(page);
  expect(afterMove).toHaveLength(3);
  expect(afterMove[0].box).toBeGreaterThan(1000);
  expect(afterMove[moved].label).toBeGreaterThan(20);
  expect(afterMove[moved].box).toBe(0);

  // Switching the input sends the box back to the study's own pane.
  await page.evaluate(() => window.__outputTargets.study.setSettings({ onPrice: false }));
  await painted(page);
  const local = await inkByPane(page);
  expect(local[moved].box).toBeGreaterThan(20);
  expect(local[0].box).toBeGreaterThan(1000);

  // Removing the first leaves the second instance's box on the candles.
  await page.evaluate(() => window.__outputTargets.study.remove());
  await painted(page);
  const remaining = await inkByPane(page);
  expect(remaining[0].box).toBeGreaterThan(1000);
  expect(remaining.slice(1).every(counts => counts.box === 0)).toBe(true);
  await page.screenshot({ path: info.outputPath('output-targets-after-removal.png') });
  expect(errors).toEqual([]);
});

test('a routed box follows candles on the left axis and leaves the axis free to move', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 700 });
  await page.route('**/output-targets.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/output-targets.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    // The instrument on the left axis from the start, nothing on the right.
    chart.addSeries('candlestick', { priceScaleId: 'left' })
      .setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    lib.registerIndicator({
      id: 'native-output-targets-left', name: 'Routed box', placement: 'pane', inputs: [],
      plots: [{ key: 'osc', type: 'line', title: 'Osc', style: { color: '#ffffff' } }],
      calc: bars => ({ osc: bars.map((_, i) => 30 + (i % 10)) }),
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[20].time, price: 104 }, to: { time: bars[35].time, price: 96 },
        color: '#cc2244', fillColor: '#cc2244', opacity: 1, id: 'zone', overlay: true }],
    });
    const study = chart.addIndicator('native-output-targets-left');
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    const clicks: string[] = [];
    chart.subscribeClick(id => { clicks.push(id); });
    window.__outputTargets = { chart, study, clicks };
  });
  await painted(page);
  const onLeft = await inkByPane(page);
  expect(onLeft[0].box).toBeGreaterThan(1000);
  expect(await page.evaluate(() => window.__outputTargets.chart.panes()[0].usesScale('right'))).toBe(false);
  await page.screenshot({ path: info.outputPath('output-targets-left-axis.png') });
  const clickBox = async () => {
    const point = await page.evaluate(() => {
      const { chart } = window.__outputTargets;
      const box = document.querySelector('#chart')!.getBoundingClientRect();
      return { x: box.left + chart.timeToCoordinate(1700000000 + 27 * 60), y: box.top + chart.priceToCoordinate(100, 0)! };
    });
    await page.mouse.click(point.x, point.y);
  };
  await clickBox();
  await expect.poll(() => page.evaluate(() => window.__outputTargets.clicks)).toEqual(['zone']);

  // The axis can move back and forth; the box goes with the candles each time.
  expect(await page.evaluate(() => window.__outputTargets.chart.movePriceAxis(0, 'left', 'right'))).toBe(true);
  await painted(page);
  expect((await inkByPane(page))[0].box).toBeGreaterThan(1000);
  await clickBox();
  await expect.poll(() => page.evaluate(() => window.__outputTargets.clicks)).toEqual(['zone', 'zone']);
  expect(await page.evaluate(() => window.__outputTargets.chart.movePriceAxis(0, 'right', 'left'))).toBe(true);
  await painted(page);
  expect((await inkByPane(page))[0].box).toBeGreaterThan(1000);
  await page.screenshot({ path: info.outputPath('output-targets-axis-moved-back.png') });
  expect(errors).toEqual([]);
});

/** A blank page with a chart host, collecting page errors. */
async function blank(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 700 });
  await page.route('**/output-targets.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/output-targets.html');
  return errors;
}

test('a study keeps its marks under its shapes on the candles when a later study restacks the pane', async ({ page }, info) => {
  const errors = await blank(page);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    const source = chart.addSeries('candlestick');
    source.setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    const plots = [{ key: 'osc', type: 'line' as const, title: 'Osc', style: { color: '#ffffff' } }];
    const calc = (rows: readonly unknown[]) => ({ osc: rows.map((_, i) => 30 + (i % 10)) });
    lib.registerIndicator({
      id: 'native-restack-sample', name: 'Sample', placement: 'pane', inputs: [], plots, calc,
      // The dot sits inside the opaque box, so it shows only if the box is drawn under it.
      markers: ({ bars }) => [{ time: bars[27].time, position: 'atPrice', price: 100, shape: 'circle', size: 'big', color: '#eecc22', overlay: true }],
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[20].time, price: 104 }, to: { time: bars[35].time, price: 96 },
        color: '#cc2244', fillColor: '#cc2244', opacity: 1, overlay: true }],
    });
    // A later study whose price-pane label first appears on a live bar, which restacks the pane.
    lib.registerIndicator({
      id: 'native-restack-late', name: 'Late', placement: 'pane', inputs: [], plots, calc,
      draws: ({ bars }) => (bars.length > 60 ? [{ kind: 'label', at: { time: bars[45].time, price: 100 }, text: 'LATE',
        color: '#9933cc', textColor: '#9933cc', overlay: true }] : []),
    });
    const study = chart.addIndicator('native-restack-sample');
    chart.addIndicator('native-restack-late');
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    window.__outputTargets = { chart, study, clicks: [] };
    (window as unknown as { __tick: () => void }).__tick = () => source.update({ time: 1700000000 + 60 * 60, open: 99, high: 102, low: 98, close: 100 });
  });
  await painted(page);
  const before = await inkByPane(page);
  expect(before[0].box).toBeGreaterThan(1000);
  expect(before[0].dot).toBe(0);
  expect(before[0].label).toBe(0);
  await page.evaluate(() => (window as unknown as { __tick: () => void }).__tick());
  await painted(page);
  const after = await inkByPane(page);
  expect(after[0].label).toBeGreaterThan(20);
  expect(after[0].box).toBeGreaterThan(1000);
  expect(after[0].dot).toBe(0);
  await page.screenshot({ path: info.outputPath('output-targets-restacked.png') });
  expect(errors).toEqual([]);
});

test('marks sent to the candles stack with the study\'s own marks there instead of covering them', async ({ page }, info) => {
  const errors = await blank(page);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    chart.addSeries('candlestick')
      .setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    lib.registerIndicator({
      id: 'native-shared-anchor', name: 'Shared anchor', placement: 'onchart', markerAnchor: 'price', inputs: [],
      plots: [{ key: 'mid', type: 'line', title: 'Mid', style: { color: '#ffffff' } }],
      calc: bars => ({ mid: bars.map(bar => bar.close) }),
      // Same bar, same size, same position: one layer stacks them, two layers draw one over the other.
      markers: ({ bars }) => [
        { time: bars[30].time, position: 'belowBar', shape: 'circle', size: 'big', color: '#eecc22' },
        { time: bars[30].time, position: 'belowBar', shape: 'circle', size: 'big', color: '#9933cc', overlay: true },
      ],
    });
    const study = chart.addIndicator('native-shared-anchor');
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    window.__outputTargets = { chart, study, clicks: [] };
  });
  await painted(page);
  const ink = await inkByPane(page);
  expect(ink).toHaveLength(1);
  expect(ink[0].dot).toBeGreaterThan(20);
  expect(ink[0].label).toBeGreaterThan(20);
  await page.screenshot({ path: info.outputPath('output-targets-shared-anchor.png') });
  expect(errors).toEqual([]);
});

test('a price-pane box measures on the price pane when the candles live on another pane', async ({ page }, info) => {
  const errors = await blank(page);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    // The candles on pane 1, quoting 98 to 102; pane 0 holds only the guide, quoting 90 to 110.
    chart.addSeries('candlestick', { paneIndex: 1 })
      .setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 100 + Math.sin(i) })));
    lib.registerIndicator({
      id: 'native-candles-elsewhere', name: 'Candles elsewhere', placement: 'pane', inputs: [],
      plots: [
        { key: 'osc', type: 'line', title: 'Osc', style: { color: '#ffffff' } },
        { key: 'guide', type: 'line', title: 'Guide', overlay: true, style: { color: '#888888' } },
      ],
      calc: bars => ({ osc: bars.map((_, i) => 30 + (i % 10)), guide: bars.map((_, i) => 100 + 10 * Math.sin(i / 4)) }),
      // Priced where only pane 0's own scale can show it: above the candles' whole range.
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[20].time, price: 105 }, to: { time: bars[35].time, price: 103 },
        color: '#cc2244', fillColor: '#cc2244', opacity: 1, id: 'zone', overlay: true }],
    });
    const study = chart.addIndicator('native-candles-elsewhere');
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    const clicks: string[] = [];
    chart.subscribeClick(id => { clicks.push(id); });
    window.__outputTargets = { chart, study, clicks };
  });
  await painted(page);
  const ink = await inkByPane(page);
  expect(ink[0].box).toBeGreaterThan(200);
  expect(ink[1].box).toBe(0);
  const point = await page.evaluate(() => {
    const { chart } = window.__outputTargets;
    const box = document.querySelector('#chart')!.getBoundingClientRect();
    return { x: box.left + chart.timeToCoordinate(1700000000 + 27 * 60), y: box.top + chart.priceToCoordinate(104, 0)! };
  });
  await page.mouse.click(point.x, point.y);
  await expect.poll(() => page.evaluate(() => window.__outputTargets.clicks)).toEqual(['zone']);
  await page.screenshot({ path: info.outputPath('output-targets-candles-elsewhere.png') });
  expect(errors).toEqual([]);
});

/** Exact-colour ink per pane for the shading tests: own and sent columns, the routed box and dot, two studies' columns. */
async function shadeInk(page: Page) {
  return page.evaluate(() => window.__outputTargets.chart.panes().map(pane => {
    const counts = { own: 0, sent: 0, box: 0, dot: 0, first: 0, second: 0 };
    for (const canvas of pane.element.querySelectorAll('canvas')) {
      const ctx = canvas.getContext('2d');
      if (!ctx || canvas.width === 0 || canvas.height === 0) continue;
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] !== 255) continue;
        const rgb = `${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`;
        if (rgb === '34,85,170') counts.own++;
        else if (rgb === '34,170,102') counts.sent++;
        else if (rgb === '204,34,68') counts.box++;
        else if (rgb === '238,204,34') counts.dot++;
        else if (rgb === '170,51,34') counts.first++;
        else if (rgb === '51,34,170') counts.second++;
      }
    }
    return counts;
  }));
}

/** The opaque colour on screen at a chart coordinate, read from the topmost pane canvas that painted it. */
async function colourAt(page: Page, x: number, y: number): Promise<string | null> {
  return page.evaluate(([cx, cy]) => {
    const box = document.querySelector('#chart')!.getBoundingClientRect();
    const px = box.left + cx, py = box.top + cy;
    const canvases = [...document.querySelectorAll<HTMLCanvasElement>('#chart canvas')].reverse();
    for (const canvas of canvases) {
      const rect = canvas.getBoundingClientRect();
      if (px < rect.left || px >= rect.right || py < rect.top || py >= rect.bottom) continue;
      const scale = canvas.width / rect.width;
      const [r, g, b, a] = canvas.getContext('2d')!.getImageData(Math.floor((px - rect.left) * scale), Math.floor((py - rect.top) * scale), 1, 1).data;
      if (a === 255) return `${r},${g},${b}`;
    }
    return null;
  }, [x, y]);
}

test('routed study shading paints where it is sent, under the candles, shapes and marks, and follows the study', async ({ page }, info) => {
  const errors = await blank(page);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    // Rising bodies from 99 to 101, so a body sits at 100 on every bar.
    chart.addSeries('candlestick')
      .setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 101 })));
    lib.registerIndicator({
      id: 'native-shading-targets', name: 'Routed shading', placement: 'pane',
      inputs: [{ key: 'shade', label: 'Shade', type: 'select', default: 'price',
        options: [{ label: 'Price', value: 'price' }, { label: 'Alt', value: 'alt' }, { label: 'None', value: 'none' }] }],
      plots: [
        { key: 'osc', type: 'line', title: 'Osc', style: { color: '#ffffff' } },
        { key: 'alt', type: 'line', title: 'Alt', style: { color: '#888888' } },
      ],
      calc: bars => ({ osc: bars.map((_, i) => 30 + (i % 10)), alt: bars.map((_, i) => 500 + i) }),
      // Opaque on purpose, so every colour can be counted exactly and covering is visible.
      background: ({ bars, settings }) => [
        { colors: bars.map((_, i) => (i >= 5 && i < 15 ? '#2255aa' : null)) },
        ...(settings.shade === 'none' ? [] : [{ colors: bars.map((_, i) => (i >= 18 && i < 36 ? '#22aa66' : null)),
          ...(settings.shade === 'alt' ? { plot: 'alt' } : { overlay: true }) }]),
      ],
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[26].time, price: 101.5 }, to: { time: bars[32].time, price: 98.5 },
        color: '#cc2244', fillColor: '#cc2244', opacity: 1, overlay: true }],
      markers: ({ bars }) => [{ time: bars[22].time, position: 'atPrice', price: 100, shape: 'circle', size: 'big', color: '#eecc22', overlay: true }],
    });
    const study = chart.addIndicator('native-shading-targets', {}, { plotPriceScaleIds: { alt: 'left' } });
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    window.__outputTargets = { chart, study, clicks: [] };
  });
  await painted(page);
  const first = await shadeInk(page);
  await page.screenshot({ path: info.outputPath('shading-targets.png') });
  expect(first).toHaveLength(2);
  // The sent column on the candles, the study's own column in its pane.
  expect(first[0].sent).toBeGreaterThan(5000);
  expect(first[0].own).toBe(0);
  expect(first[1].own).toBeGreaterThan(2000);
  expect(first[1].sent).toBe(0);
  // The box and the dot paint over the shading, whole.
  expect(first[0].box).toBeGreaterThan(1000);
  expect(first[0].dot).toBeGreaterThan(20);
  // A candle body covers the shading at its bar; between two bars the shading shows.
  const at = await page.evaluate(() => {
    const { chart } = window.__outputTargets;
    return { x: chart.timeToCoordinate(1700000000 + 20 * 60), gap: chart.timeScale.barSpacing / 2, y: chart.priceToCoordinate(100, 0)! };
  });
  expect(await colourAt(page, at.x, at.y)).not.toBe('34,170,102');
  expect(await colourAt(page, at.x + at.gap - 0.5, at.y)).toBe('34,170,102');

  await page.evaluate(() => window.__outputTargets.study.setVisible(false));
  await painted(page);
  const hidden = await shadeInk(page);
  expect(hidden.map(counts => counts.own + counts.sent)).toEqual([0, 0]);
  await page.evaluate(() => window.__outputTargets.study.setVisible(true));
  await painted(page);
  expect((await shadeInk(page))[0].sent).toBeGreaterThan(5000);

  // Moving the study to a new pane takes its own column along and leaves the sent one on the candles.
  await page.evaluate(() => {
    const { chart, study } = window.__outputTargets;
    chart.addIndicator('native-shading-targets', { shade: 'none' });
    chart.moveIndicator(study.id, chart.panes().length);
  });
  await painted(page);
  const moved = await page.evaluate(() => window.__outputTargets.study.paneIndex);
  const afterMove = await shadeInk(page);
  expect(afterMove).toHaveLength(3);
  expect(afterMove[0].sent).toBeGreaterThan(5000);
  expect(afterMove[moved].own).toBeGreaterThan(2000);
  expect(afterMove[moved].sent).toBe(0);

  // Naming the alt plot sends the column to the study pane and releases the price-pane one.
  await page.evaluate(() => window.__outputTargets.study.setSettings({ shade: 'alt' }));
  await painted(page);
  const onPlot = await shadeInk(page);
  expect(onPlot[0].sent).toBe(0);
  expect(onPlot[moved].sent).toBeGreaterThan(2000);
  await page.screenshot({ path: info.outputPath('shading-targets-plot.png') });

  // Naming no target any more releases it; the study's own column stays.
  await page.evaluate(() => window.__outputTargets.study.setSettings({ shade: 'none' }));
  await painted(page);
  const released = await shadeInk(page);
  expect(released.every(counts => counts.sent === 0)).toBe(true);
  expect(released[moved].own).toBeGreaterThan(2000);

  await page.evaluate(() => {
    const { study } = window.__outputTargets;
    study.setSettings({ shade: 'price' });
    study.remove();
  });
  await painted(page);
  // The second instance keeps its own box, dot and column; nothing of the first is left.
  const removed = await shadeInk(page);
  expect(removed).toHaveLength(2);
  expect(removed.map(counts => counts.sent)).toEqual([0, 0]);
  expect(removed[1].own).toBeGreaterThan(2000);
  await page.screenshot({ path: info.outputPath('shading-targets-removed.png') });
  expect(errors).toEqual([]);
});

test('shading from two studies stacks in study order on the candles, also when the first starts on a live bar', async ({ page }, info) => {
  const errors = await blank(page);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    const chart = lib.createChart(document.querySelector<HTMLElement>('#chart')!, { branding: false, theme: lib.darkTheme });
    const source = chart.addSeries('candlestick');
    source.setData(Array.from({ length: 60 }, (_, i) => ({ time: 1700000000 + i * 60, open: 99, high: 102, low: 98, close: 101 })));
    const plots = [{ key: 'osc', type: 'line' as const, title: 'Osc', style: { color: '#ffffff' } }];
    const calc = (rows: readonly unknown[]) => ({ osc: rows.map((_, i) => 30 + (i % 10)) });
    // The first study only shades once a live bar arrives, over bars 10 to 29.
    lib.registerIndicator({
      id: 'native-shading-first', name: 'First', placement: 'pane', inputs: [], plots, calc,
      background: ({ bars }) => (bars.length > 60 ? [{ overlay: true, colors: bars.map((_, i) => (i >= 10 && i < 30 ? '#aa3322' : null)) }] : []),
    });
    // The second shades bars 20 to 39 from the start, so the two overlap on bars 20 to 29.
    lib.registerIndicator({
      id: 'native-shading-second', name: 'Second', placement: 'pane', inputs: [], plots, calc,
      background: ({ bars }) => [{ overlay: true, colors: bars.map((_, i) => (i >= 20 && i < 40 ? '#3322aa' : null)) }],
    });
    const study = chart.addIndicator('native-shading-first');
    chart.addIndicator('native-shading-second');
    chart.setVisibleLogicalRange({ from: -2, to: 62 });
    window.__outputTargets = { chart, study, clicks: [] };
    (window as unknown as { __tick: () => void }).__tick = () => source.update({ time: 1700000000 + 60 * 60, open: 99, high: 102, low: 98, close: 101 });
  });
  await painted(page);
  const before = await shadeInk(page);
  expect(before[0].first).toBe(0);
  expect(before[0].second).toBeGreaterThan(5000);
  await page.evaluate(() => (window as unknown as { __tick: () => void }).__tick());
  await painted(page);
  const after = await shadeInk(page);
  expect(after[0].first).toBeGreaterThan(2000);
  // Where the two overlap, the later study's shading covers the earlier one's.
  const x = await page.evaluate(() => {
    const { chart } = window.__outputTargets;
    return [15, 25, 35].map(i => chart.timeToCoordinate(1700000000 + i * 60) + chart.timeScale.barSpacing / 2 - 0.5);
  });
  const y = await page.evaluate(() => window.__outputTargets.chart.priceToCoordinate(100, 0)!);
  expect(await colourAt(page, x[0], y)).toBe('170,51,34');
  expect(await colourAt(page, x[1], y)).toBe('51,34,170');
  expect(await colourAt(page, x[2], y)).toBe('51,34,170');
  await page.screenshot({ path: info.outputPath('shading-targets-stacked.png') });
  expect(errors).toEqual([]);
});

/**
 * The live example on the website, run from its source at a desktop and a phone width. Each
 * shading layer is switched off and on again by itself, so every pixel that changes is that
 * layer's: on the candles a green tint where momentum is up and red where it is down, and in
 * the study pane a blue tint only at the strongest readings. Read at each bar's centre column.
 */
for (const width of [900, 390]) test(`the documented background targets example shades the candles and its pane at ${width}px`, async ({ page }, info) => {
  const errors: string[] = [];
  const dialogs: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => { dialogs.push(dialog.message()); void dialog.dismiss(); });
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  const section = (await response.text()).split('### Shading the candles from a study pane')[1];
  expect(section).toBeDefined();
  const code = section.split('code={`')[1].split('`} />')[0];
  await page.setViewportSize({ width, height: 600 });
  await page.route('**/shading-example.html', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:${width}px;height:420px}</style></head><body><div id="example"></div></body></html>` }));
  await page.goto('/shading-example.html');
  await page.evaluate(async source => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    // The site hands every example a chart in its own theme; dark is its default.
    const themed = { ...lib, createChart: (host: HTMLElement, options?: Charts.ChartOptions) => lib.createChart(host, { theme: lib.darkTheme, ...options }) };
    window.__shadingExample = { chart: new Function('el', 'lib', source)(document.getElementById('example'), themed) as Chart, lib };
  }, code);
  await painted(page);
  await page.locator('#example').screenshot({ path: info.outputPath(`shading-example-${width}.png`) });

  const result = await page.evaluate(async () => {
    const { chart, lib } = window.__shadingExample;
    const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const study = chart.indicators()[0];
    const momentum = study.values().momentum;
    const peak = Math.max(...momentum.map(value => Math.abs(value ?? 0)));
    const layers = chart.panes().map(pane => pane.primitives().filter(primitive => primitive instanceof lib.IndicatorBackground) as InstanceType<typeof lib.IndicatorBackground>[]);
    const snap = (index: number) => {
      const { element, ctx } = chart.panes()[index].base;
      return { data: ctx.getImageData(0, 0, element.width, element.height).data, width: element.width, height: element.height,
        ratio: element.width / element.getBoundingClientRect().width };
    };
    /** Per bar: pixels in its centre column that the layer changed, and how many of them lean the wrong way. */
    const compare = async (index: number, expected: (value: number | null) => 'up' | 'down' | 'blue' | null) => {
      const shown = snap(index);
      for (const layer of layers[index]) layer.setVisible(false);
      await frame();
      const plain = snap(index);
      for (const layer of layers[index]) layer.setVisible(true);
      await frame();
      const left = chart.priceAxisLayout(index).filter(slot => slot.side === 'left').reduce((sum, slot) => sum + slot.width, 0);
      const verdicts = { right: 0, wrong: [] as string[], shaded: 0, unshaded: 0 };
      momentum.forEach((value, i) => {
        const want = expected(value);
        const x = Math.floor((left + chart.timeScale.indexToX(i)) * shown.ratio);
        let changed = 0, wrong = 0;
        for (let y = 0; y < shown.height; y++) {
          const at = (y * shown.width + x) * 4;
          const [dr, dg, db] = [0, 1, 2].map(k => shown.data[at + k] - plain.data[at + k]);
          if (dr === 0 && dg === 0 && db === 0) continue;
          changed++;
          const leans = want === 'up' ? dg > dr : want === 'down' ? dr > dg : want === 'blue' ? db > dr && db > dg : false;
          if (!leans) wrong++;
        }
        if (want === null) { if (changed > 0) verdicts.wrong.push(`bar ${i} changed ${changed} with no shade`); else verdicts.unshaded++; return; }
        verdicts.shaded++;
        if (wrong > 0) verdicts.wrong.push(`bar ${i} ${wrong} of ${changed} lean away from ${want}`);
        else if (changed > 0) verdicts.right++;
      });
      return verdicts;
    };
    const candles = await compare(0, value => (value === null || value === 0 ? null : value > 0 ? 'up' : 'down'));
    const own = await compare(study.paneIndex, value => (value !== null && Math.abs(value) > peak * 0.6 ? 'blue' : null));
    return { panes: chart.panes().length, pane: study.paneIndex, layers: layers.map(list => list.length), candles, own };
  });
  const verdicts = info.outputPath(`shading-example-${width}.json`);
  await writeFile(verdicts, JSON.stringify(result, null, 1));
  await info.attach(`shading-example-${width}.json`, { path: verdicts, contentType: 'application/json' });
  expect(result.panes).toBe(2);
  expect(result.pane).toBe(1);
  // One layer on the candles, sent there by the study, and the study's own in its pane.
  expect(result.layers).toEqual([1, 1]);
  expect(result.candles.wrong).toEqual([]);
  expect(result.candles.shaded).toBeGreaterThan(100);
  expect(result.candles.right).toBeGreaterThan(result.candles.shaded * 0.9);
  expect(result.own.wrong).toEqual([]);
  expect(result.own.shaded).toBeGreaterThan(3);
  expect(result.own.right).toBeGreaterThan(result.own.shaded * 0.9);
  expect(result.own.unshaded).toBeGreaterThan(100);
  expect(dialogs).toEqual([]);
  expect(errors).toEqual([]);
});
