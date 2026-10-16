import { test, expect, type Page } from '@playwright/test';
import type { Chart, ChartState, PriceScale, SeriesApi, ContextMenuTarget } from '../../src/index';
import type * as Charts from '../../src/index';

type PaintedBox = { color: string; x: number; y: number; width: number; height: number };
type PaintedText = { text: string; x: number; y: number; width: number };

declare global {
  interface Window {
    __multipleAxes: {
      chart: Chart; series: SeriesApi[]; scales: PriceScale[]; data: string[];
      contexts: ContextMenuTarget[]; boxes: PaintedBox[]; texts: PaintedText[]; saved?: ChartState;
    };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, width = 900, dpr = 1) {
  await page.setViewportSize({ width, height: 560 });
  await page.route('**/multiple-price-axes.html', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#chart{width:${width}px;height:550px}</style></head><body><div id="chart"></div></body></html>` }));
  await page.goto('/multiple-price-axes.html');
  await page.evaluate(async ({ width, dpr }) => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { createChart, darkTheme } = await import(bundle) as typeof Charts;
    const chart = createChart(document.getElementById('chart')!, {
      branding: false, theme: darkTheme, animZoom: false, animAutoscale: false,
      timeNavigator: false, pixelRatio: () => dpr,
    });
    const settings = [
      { id: 'right', min: 80, max: 160, color: '#22aadd', prefix: 'R', base: 115, amplitude: 10 },
      { id: 'overlay:outer', min: 1000, max: 2000, color: '#bb88ff', prefix: 'O', base: 1450, amplitude: 180 },
      { id: 'left', min: -10, max: 10, color: '#eeaa22', prefix: 'L', base: -2, amplitude: 3 },
    ] as const;
    const series = settings.map(({ id, min, max, color, prefix, base, amplitude }) => {
      const source = chart.addSeries('line', { priceScaleId: id, style: { color, lineWidth: 3, priceLineVisible: false } });
      source.setData(Array.from({ length: 48 }, (_, index) => {
        const close = base + Math.sin(index / 5) * amplitude;
        return { time: 1700000000 + index * 60, open: close, high: close, low: close, close };
      }));
      const scale = source.priceScale();
      scale.setAutoScale(false); scale.setPriceRange({ min, max });
      scale.setOptions({ marginTop: 0, marginBottom: 0 });
      scale.setPriceFormatter(value => `${prefix}${value.toFixed(0)}`);
      return source;
    });
    chart.setPriceAxisPlacement(0, 'overlay:outer', 'right');
    const boxes: PaintedBox[] = [], texts: PaintedText[] = [], contexts: ContextMenuTarget[] = [];
    const context = chart.panes()[0].base.ctx;
    const clearRect = context.clearRect.bind(context), fillRect = context.fillRect.bind(context), fillText = context.fillText.bind(context);
    context.clearRect = (x, y, w, h) => { boxes.length = 0; texts.length = 0; clearRect(x, y, w, h); };
    context.fillRect = (x, y, w, h) => {
      const matrix = context.getTransform(), point = new DOMPoint(x, y).matrixTransform(matrix);
      const ratio = context.canvas.width / width;
      boxes.push({ color: String(context.fillStyle), x: point.x / ratio, y: point.y / ratio, width: w * matrix.a / ratio, height: h * matrix.d / ratio });
      fillRect(x, y, w, h);
    };
    context.fillText = (text, x, y, maxWidth) => {
      const matrix = context.getTransform(), point = new DOMPoint(x, y).matrixTransform(matrix);
      const ratio = context.canvas.width / width;
      const measured = context.measureText(text).width;
      const drawnWidth = Math.min(measured, maxWidth ?? measured) * matrix.a / ratio;
      const align = context.textAlign === 'right' || context.textAlign === 'end' ? 1 : context.textAlign === 'center' ? 0.5 : 0;
      texts.push({ text, x: point.x / ratio - align * drawnWidth, y: point.y / ratio, width: drawnWidth });
      if (maxWidth === undefined) fillText(text, x, y);
      else fillText(text, x, y, maxWidth);
    };
    chart.on('contextmenu', event => { event.preventDefault(); contexts.push({ ...event.target }); });
    window.__multipleAxes = { chart, series, scales: series.map(source => source.priceScale()), data: series.map(source => JSON.stringify(source.getData())), contexts, boxes, texts };
    chart.setVisibleLogicalRange({ from: -2, to: 50 });
  }, { width, dpr });
  await paint(page);
}

async function inspect(page: Page) {
  return page.evaluate(() => {
    const { chart, series, scales, data, contexts, boxes, texts } = window.__multipleAxes;
    const slots = chart.priceAxisLayout();
    const context = chart.panes()[0].base.ctx;
    const dpr = context.canvas.width / document.getElementById('chart')!.clientWidth;
    const ink = slots.map(slot => {
      const pixels = context.getImageData(Math.round(slot.x * dpr), 0, Math.round(slot.width * dpr), Math.round(520 * dpr)).data;
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) if (Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) > 130) count++;
      return count;
    });
    return { slots, ink, ranges: scales.map(scale => ({ ...scale.priceRange() })),
      width: chart.timeScale.width, viewport: chart.getVisibleLogicalRange(),
      sameScales: series.every((source, index) => source.priceScale() === scales[index]),
      sameData: series.every((source, index) => JSON.stringify(source.getData()) === data[index]),
      contexts: [...contexts], boxes: [...boxes], texts: [...texts], dpr };
  });
}

test('three independent axes route outer-column wheel, drag and context to the exact scale', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  const initial = await inspect(page);
  expect(initial.width).toBe(732);
  expect(initial.slots).toEqual([
    { scaleId: 'left', side: 'left', order: 0, x: 0, width: 56 },
    { scaleId: 'right', side: 'right', order: 0, x: 788, width: 56 },
    { scaleId: 'overlay:outer', side: 'right', order: 1, x: 844, width: 56 },
  ]);
  expect(initial.ranges).toEqual([{ min: 80, max: 160 }, { min: 1000, max: 2000 }, { min: -10, max: 10 }]);
  expect(initial.ink.every(count => count > 100)).toBe(true);
  for (const [id, prefix] of [['right', 'R'], ['overlay:outer', 'O'], ['left', 'L']] as const) {
    const slot = initial.slots.find(axis => axis.scaleId === id)!;
    const labels = initial.texts.filter(text => new RegExp(`^${prefix}-?\\d`).test(text.text));
    expect(labels.length).toBeGreaterThan(2);
    for (const label of labels) {
      expect(label.x).toBeGreaterThanOrEqual(slot.x);
      expect(label.x + label.width).toBeLessThanOrEqual(slot.x + slot.width + 0.01);
    }
  }
  await page.locator('#chart').screenshot({ path: info.outputPath('three-independent-price-axes.png') });
  const outer = initial.slots[2], x = outer.x + outer.width / 2;
  await page.mouse.move(x, 230); await page.mouse.wheel(0, 100);
  await expect.poll(async () => (await inspect(page)).ranges[1]).not.toEqual(initial.ranges[1]);
  const wheeled = await inspect(page);
  expect(wheeled.ranges[0]).toEqual(initial.ranges[0]); expect(wheeled.ranges[2]).toEqual(initial.ranges[2]);
  expect(wheeled.viewport).toEqual(initial.viewport);
  await page.mouse.down(); await page.mouse.move(x, 290, { steps: 5 }); await page.mouse.up();
  await paint(page);
  const dragged = await inspect(page);
  expect(dragged.ranges[1]).not.toEqual(wheeled.ranges[1]);
  expect(dragged.ranges[0]).toEqual(initial.ranges[0]); expect(dragged.ranges[2]).toEqual(initial.ranges[2]);
  expect(dragged.viewport).toEqual(initial.viewport);
  for (const slot of initial.slots) {
    await page.mouse.click(slot.x + slot.width / 2, 210, { button: 'right' });
    expect((await inspect(page)).contexts.slice(-1)[0]).toMatchObject({ kind: 'price-scale', scaleId: slot.scaleId, side: slot.side });
  }
  await page.mouse.move(400, 555); await paint(page);
  const final = await inspect(page);
  expect(final.sameScales && final.sameData).toBe(true);
  await page.locator('#chart').screenshot({ path: info.outputPath('outer-axis-after-wheel-and-drag.png') });
  expect(errors).toEqual([]);
});

test('moving and reordering stable axes restores full state and identical pixels', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  await page.evaluate(() => { const state = window.__multipleAxes; state.saved = JSON.parse(JSON.stringify(state.chart.getState())) as ChartState; });
  const initial = await inspect(page);
  const before = await page.locator('#chart').screenshot({ path: info.outputPath('axis-state-before.png') });
  expect(await page.evaluate(() => window.__multipleAxes.chart.setPriceAxisPlacement(0, 'overlay:outer', 'right', 0))).toBe(true);
  await paint(page);
  expect((await inspect(page)).slots.filter(slot => slot.side === 'right').map(slot => slot.scaleId)).toEqual(['overlay:outer', 'right']);
  expect(await page.evaluate(() => window.__multipleAxes.chart.setPriceAxisPlacement(0, 'overlay:outer', 'left', 0))).toBe(true);
  await paint(page);
  const moved = await inspect(page);
  expect(moved.slots.filter(slot => slot.side === 'left').map(slot => slot.scaleId)).toEqual(['overlay:outer', 'left']);
  expect(moved.ranges).toEqual(initial.ranges); expect(moved.sameScales && moved.sameData).toBe(true);
  const shifted = await page.locator('#chart').screenshot({ path: info.outputPath('axis-state-moved-left.png') });
  expect(shifted.equals(before)).toBe(false);
  expect(await page.evaluate(() => { const state = window.__multipleAxes; return state.chart.restoreState(state.saved!).applied; })).toBe(true);
  await paint(page);
  const restored = await inspect(page);
  expect(restored.slots).toEqual(initial.slots); expect(restored.ranges).toEqual(initial.ranges);
  expect(restored.sameScales && restored.sameData).toBe(true);
  const after = await page.locator('#chart').screenshot({ path: info.outputPath('axis-state-restored.png') });
  expect(after.equals(before)).toBe(true);
  await page.evaluate(() => window.__multipleAxes.series[0].applyOptions({ lineWidth: 3 }));
  await paint(page);
  expect((await page.locator('#chart').screenshot()).equals(after)).toBe(true);
  expect(errors).toEqual([]);
});

test('narrow fractional rendering keeps bound price labels inside their own canvas and SVG columns', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await mount(page, 390, 1.5);
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { PriceLine, PriceLevels } = await import(bundle) as typeof Charts;
    const { chart } = window.__multipleAxes, pane = chart.panes()[0];
    const line = new PriceLine({ id: 'bound-outer', price: 1740, color: '#cc4477', label: 'Outer bound price line' });
    const levels = new PriceLevels({ quote: { bid: 6 }, levels: {
      previousClose: { line: false, label: false },
      bid: { line: true, label: true, text: 'Left bound price level', color: '#44cc99' },
    } });
    chart.addPrimitive(line); chart.addPrimitive(levels);
    pane.bindPrimitiveScale(line, 'overlay:outer'); pane.bindPrimitiveScale(levels, 'left');
    chart.setPriceAxisPlacement(0, 'right', 'hidden');
  });
  await paint(page);
  const state = await inspect(page);
  expect(state.dpr).toBe(1.5); expect(state.width).toBe(278);
  expect(state.slots.map(slot => slot.scaleId)).toEqual(['left', 'overlay:outer']);
  expect(state.texts.some(text => /^R-?\d/.test(text.text))).toBe(false);
  for (const [id, color, label] of [
    ['overlay:outer', '#cc4477', 'Outer bound price line'], ['left', '#44cc99', 'Left bound price level'],
  ] as const) {
    const slot = state.slots.find(axis => axis.scaleId === id)!;
    const boxes = state.boxes.filter(box => box.color === color);
    expect(boxes).toHaveLength(1);
    expect(boxes[0].x).toBeGreaterThanOrEqual(slot.x);
    expect(boxes[0].x + boxes[0].width).toBeLessThanOrEqual(slot.x + slot.width + 0.01);
    const text = state.texts.find(item => item.text === label)!;
    expect(text).toBeDefined(); expect(text.x).toBeGreaterThanOrEqual(slot.x);
    expect(text.x + text.width).toBeLessThanOrEqual(slot.x + slot.width + 0.01);
    const ink = await page.evaluate(box => {
      const context = window.__multipleAxes.chart.panes()[0].base.ctx;
      const data = context.getImageData(Math.round(box.x * 1.5), Math.round(box.y * 1.5), Math.round(box.width * 1.5), Math.round(box.height * 1.5)).data;
      const rgb = box.color.slice(1).match(/../g)!.map(value => parseInt(value, 16));
      let count = 0;
      for (let i = 0; i < data.length; i += 4) if (rgb.every((channel, index) => data[i + index] === channel)) count++;
      return count;
    }, boxes[0]);
    expect(ink).toBeGreaterThan(100);
  }
  const first = await page.locator('#chart').screenshot({ path: info.outputPath('narrow-bound-axis-labels.png') });
  const svg = await page.evaluate(() => window.__multipleAxes.chart.exportSVG());
  const pills = await page.evaluate(source => {
    const root = new DOMParser().parseFromString(source, 'image/svg+xml').documentElement as unknown as SVGSVGElement;
    root.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none'; document.body.appendChild(root);
    try {
      return ['#cc4477', '#44cc99'].map(color => ({ color, boxes: Array.from(root.querySelectorAll<SVGRectElement>(`rect[fill="${color}"]`)).map(rect => {
        const box = rect.getBBox(), matrix = rect.getCTM()!, point = new DOMPoint(box.x, box.y).matrixTransform(matrix);
        return { x: point.x, right: point.x + box.width * matrix.a, y: point.y, bottom: point.y + box.height * matrix.d };
      }) }));
    } finally { root.remove(); }
  }, svg);
  for (const pill of pills) {
    const slot = state.slots.find(axis => axis.scaleId === (pill.color === '#cc4477' ? 'overlay:outer' : 'left'))!;
    expect(pill.boxes).toHaveLength(1);
    expect(pill.boxes[0].x).toBeGreaterThanOrEqual(slot.x); expect(pill.boxes[0].right).toBeLessThanOrEqual(slot.x + slot.width);
    expect(pill.boxes[0].y).toBeGreaterThanOrEqual(0); expect(pill.boxes[0].bottom).toBeLessThanOrEqual(528);
  }
  expect(svg).toContain('Outer bound price line'); expect(svg).toContain('Left bound price level'); expect(svg).toContain('clip-path');
  await info.attach('narrow-bound-axis-labels.svg', { body: svg, contentType: 'image/svg+xml' });
  await page.evaluate(() => window.__multipleAxes.series[0].applyOptions({ lineWidth: 3 }));
  await paint(page);
  expect((await page.locator('#chart').screenshot()).equals(first)).toBe(true);
  await page.evaluate(() => window.__multipleAxes.chart.setPriceAxisPlacement(0, 'overlay:outer', 'hidden'));
  await paint(page);
  const hidden = await inspect(page);
  expect(hidden.boxes.some(box => box.color === '#cc4477')).toBe(false);
  expect(hidden.texts.some(text => text.text === 'Outer bound price line')).toBe(false);
  expect(hidden.boxes.some(box => box.color === '#44cc99')).toBe(true);
  await page.locator('#chart').screenshot({ path: info.outputPath('narrow-hidden-right-axis.png') });
  expect(errors).toEqual([]);
});
