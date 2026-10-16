import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window { __paneReorder: { chart: Chart; rsi: IndicatorApi; macd: IndicatorApi } }
}

const W = 960;
const H = 640;
const TIME_AXIS = 22;
/** Candle colours no chrome, study or grid uses, so a pixel of them is a candle. */
const UP: [number, number, number] = [0, 229, 255];
const DOWN: [number, number, number] = [255, 176, 0];
const RSI: [number, number, number] = [255, 0, 255];

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function route(page: Page, name: string) {
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.route(`**/${name}`, route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#c{width:${W}px;height:${H}px}</style></head><body><div id="c"></div></body></html>`,
  }));
  await page.goto('/' + name);
}

/**
 * A dark price pane with an RSI pane and a MACD pane under it; `bottom` then
 * moves the price pane below both. `movable` false builds the chart the way a
 * host that never opted in does, with the price pane pinned on top.
 */
async function mount(page: Page, bottom: boolean, movable = true) {
  await route(page, 'pane-reorder.html');
  await page.evaluate(async ([up, down, rsiColor, move, movablePrimaryPane]) => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    await import('/dist/openalgo-charts.indicators.mjs');
    const chart = createChart(document.getElementById('c')!, {
      theme: darkTheme, branding: false, animZoom: false, animAutoscale: false, movablePrimaryPane,
    });
    const bars = Array.from({ length: 160 }, (_, i) => {
      const close = 100 + Math.sin(i / 6) * 8 + i * 0.05;
      return { time: 1700000000 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
    });
    const hex = (c: number[]) => '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
    chart.addSeries('candlestick', { style: { upColor: hex(up), downColor: hex(down), borderUpColor: hex(up), borderDownColor: hex(down),
      wickUpColor: hex(up), wickDownColor: hex(down) } }).setData(bars);
    const rsi = chart.addIndicator('rsi', { color: hex(rsiColor) });
    const macd = chart.addIndicator('macd');
    if (move) chart.setPrimaryPaneIndex(2);
    window.__paneReorder = { chart, rsi, macd };
  }, [UP, DOWN, RSI, bottom, movable] as const);
  await paint(page);
}

const paneBoxes = (page: Page) => page.evaluate(() => window.__paneReorder.chart.panes()
  .map(pane => { const r = pane.element.getBoundingClientRect(); return { top: r.top, height: r.height }; }));

/** Pixels of one colour on a pane's base canvas, where its series paint. */
const pixels = (page: Page, paneIndex: number, rgb: readonly [number, number, number]) => page.evaluate(([index, [r, g, b]]) => {
  const canvas = window.__paneReorder.chart.panes()[index].base.element;
  if (!canvas.width || !canvas.height) return 0;
  const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
  let hits = 0;
  for (let i = 0; i < data.length; i += 4) if (Math.abs(data[i] - r) < 24 && Math.abs(data[i + 1] - g) < 24 && Math.abs(data[i + 2] - b) < 24) hits++;
  return hits;
}, [paneIndex, rgb] as const);

const candles = async (page: Page, paneIndex: number) => await pixels(page, paneIndex, UP) + await pixels(page, paneIndex, DOWN);

/** Bright text in the last strip of a pane's base canvas: the time axis labels. */
const axisText = (page: Page, paneIndex: number) => page.evaluate(([index, axis]) => {
  const canvas = window.__paneReorder.chart.panes()[index].base.element;
  const ratio = canvas.width / canvas.getBoundingClientRect().width;
  const rows = Math.round(axis * ratio);
  const data = canvas.getContext('2d')!.getImageData(0, canvas.height - rows, Math.round(canvas.width * 0.8), rows).data;
  let bright = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] + data[i + 1] + data[i + 2] > 300) bright++;
  return bright;
}, [paneIndex, TIME_AXIS] as const);

/** One of a study row's controls, found once the pointer has revealed it and it holds still. */
async function rowControl(page: Page, study: 'rsi' | 'macd', action: string): Promise<{ x: number; y: number }> {
  const find = () => page.evaluate(([key, name]) => {
    const { chart } = window.__paneReorder;
    const handle = window.__paneReorder[key];
    const buttons = (handle.legend() as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
    const button = buttons.find(b => b.id.endsWith('::' + name));
    if (!button) return null;
    const pane = chart.panes()[handle.paneIndex].element.getBoundingClientRect();
    return { x: pane.left + button.x + 8, y: pane.top + button.y + 8 };
  }, [study, action] as const);
  const pane = await page.evaluate(key => window.__paneReorder[key].paneIndex, study);
  const boxes = await paneBoxes(page);
  await page.mouse.move(40, boxes[pane].top + 15);
  await paint(page);
  let at = await find();
  expect(at).not.toBeNull();
  for (let tries = 0; tries < 4; tries++) {
    await page.mouse.move(at!.x, at!.y);
    await paint(page);
    const next = await find();
    expect(next).not.toBeNull();
    const settled = Math.abs(next!.x - at!.x) < 0.5 && Math.abs(next!.y - at!.y) < 0.5;
    at = next;
    if (settled) break;
  }
  return at!;
}

test('the price pane paints at the bottom of the stack, owns the time axis, and survives a save and restore', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page, true);
  expect(await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex())).toBe(2);
  const boxes = await paneBoxes(page);
  const container = await page.locator('#c').boundingBox();
  // RSI, MACD, then the price pane: the tallest box, flush with the foot of the chart.
  expect(boxes[2].top).toBeGreaterThan(boxes[1].top);
  expect(boxes[1].top).toBeGreaterThan(boxes[0].top);
  expect(boxes[2].height).toBeGreaterThan(boxes[0].height * 2);
  expect(boxes[2].top + boxes[2].height).toBeCloseTo(container!.y + H, 0);
  // Candles on the bottom pane and nowhere else; the RSI line on the top pane.
  expect(await candles(page, 2)).toBeGreaterThan(200);
  expect(await candles(page, 0)).toBe(0);
  expect(await candles(page, 1)).toBe(0);
  expect(await pixels(page, 0, RSI)).toBeGreaterThan(50);
  // The time axis prints under the price pane, the bottom one.
  expect(await axisText(page, 2)).toBeGreaterThan(0);
  expect(await axisText(page, 0)).toBe(0);
  // The default coordinate call and a hover both find the price pane where it is.
  const y = await page.evaluate(() => window.__paneReorder.chart.priceToCoordinate(100)!);
  expect(container!.y + y).toBeGreaterThan(boxes[2].top);
  await page.mouse.move(container!.x + 400, boxes[2].top + boxes[2].height / 2);
  await paint(page);
  await page.screenshot({ path: info.outputPath('price-pane-bottom.png') });

  const saved = await page.evaluate(() => JSON.stringify(window.__paneReorder.chart.getState()));
  expect(JSON.parse(saved)).toMatchObject({ version: 2, primaryPane: 2 });
  await page.evaluate(async state => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    const old = window.__paneReorder.chart;
    const bars = old.primaryBars().slice();
    const style = old.primarySeriesInfo()!.style;
    old.destroy();
    const chart = createChart(document.getElementById('c')!, { theme: darkTheme, branding: false, animZoom: false, animAutoscale: false, movablePrimaryPane: true });
    chart.addSeries('candlestick', { style: { ...style } }).setData(bars);
    const report = chart.restoreState(JSON.parse(state));
    if (!report.applied) throw new Error(report.reason);
    window.__paneReorder = { chart, rsi: chart.indicators()[0], macd: chart.indicators()[1] };
  }, saved);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex())).toBe(2);
  expect(await candles(page, 2)).toBeGreaterThan(200);
  expect(await candles(page, 0)).toBe(0);
  expect(await pixels(page, 0, RSI)).toBeGreaterThan(50);
  await page.screenshot({ path: info.outputPath('price-pane-bottom-restored.png') });
  expect(errors).toEqual([]);
});

test('study rows move past the price pane from their own controls until it sits at the bottom', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page, false);
  expect(await candles(page, 0)).toBeGreaterThan(200);
  // RSI sits just below the price pane: its Up control displaces the price pane down a slot.
  const up = await rowControl(page, 'rsi', 'up');
  await page.mouse.click(up.x, up.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex())).toBe(1);
  const again = await rowControl(page, 'macd', 'up');
  await page.mouse.click(again.x, again.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => ({ primary: window.__paneReorder.chart.primaryPaneIndex(),
    rsi: window.__paneReorder.rsi.paneIndex, macd: window.__paneReorder.macd.paneIndex }))).toEqual({ primary: 2, rsi: 0, macd: 1 });
  expect(await candles(page, 2)).toBeGreaterThan(200);
  expect(await candles(page, 0)).toBe(0);
  await page.screenshot({ path: info.outputPath('moved-by-study-controls.png') });

  // The study pane now at the top folds from its own row; the price pane never does.
  const fold = await rowControl(page, 'rsi', 'collapse');
  await page.mouse.click(fold.x, fold.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneReorder.chart.paneCollapsed(0))).toBe(true);
  expect(await page.evaluate(() => window.__paneReorder.chart.setPaneCollapsed(2, true))).toBe(false);
  const boxes = await paneBoxes(page);
  expect(boxes[0].height).toBeCloseTo(30, 0);
  expect(await pixels(page, 0, RSI)).toBe(0);
  await page.screenshot({ path: info.outputPath('top-study-folded-price-bottom.png') });
  expect(errors).toEqual([]);
});

test('without the option the up control of the first study leaves the price pane on top, where pane 0 still reads prices', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page, false, false);
  const probe = () => page.evaluate(() => {
    const { chart, rsi } = window.__paneReorder;
    const y = chart.priceToCoordinate(100, 0);
    return { movable: chart.movablePrimaryPane(), primary: chart.primaryPaneIndex(), rsi: rsi.paneIndex,
      price: y === null ? null : chart.coordinateToPrice(y, 0), refused: chart.setPrimaryPaneIndex(2) };
  });
  const before = await probe();
  expect(before).toMatchObject({ movable: false, primary: 0, rsi: 1, refused: false });
  expect(before.price).toBeCloseTo(100, 6);
  const up = await rowControl(page, 'rsi', 'up');
  await page.mouse.click(up.x, up.y);
  await page.mouse.move(980, 690);
  await paint(page);
  const after = await probe();
  expect(after).toMatchObject({ movable: false, primary: 0, rsi: 1, refused: false });
  expect(after.price).toBeCloseTo(100, 6);
  expect(await candles(page, 0)).toBeGreaterThan(200);
  expect(await candles(page, 1)).toBe(0);
  expect(await pixels(page, 1, RSI)).toBeGreaterThan(50);
  await page.screenshot({ path: info.outputPath('pinned-price-pane-after-up.png') });
  expect(errors).toEqual([]);
});

/**
 * The packaged widget over the same stack. `movable` undefined leaves the
 * option out, which is what a host that never heard of it builds.
 */
async function mountWidget(page: Page, movable?: boolean) {
  await route(page, 'pane-reorder-widget.html');
  await page.evaluate(async ([up, down, movablePrimaryPane]) => {
    const { createWidget } = await import('/dist/openalgo-charts.widget.mjs');
    await import('/dist/openalgo-charts.indicators.mjs');
    const bars = Array.from({ length: 160 }, (_, i) => {
      const close = 100 + Math.sin(i / 6) * 8 + i * 0.05;
      return { time: 1700000000 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
    });
    const widget = createWidget(document.getElementById('c')!, {
      symbol: 'NOVA', exchange: 'NSE', interval: '5m', persist: false, rail: false, animZoom: false, animAutoscale: false,
      feed: { getBars: async () => bars, subscribeBars: () => () => {} },
      ...(movablePrimaryPane === null ? {} : { movablePrimaryPane }),
    });
    widget.series.setData(bars);
    const hex = (c: number[]) => '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
    widget.series.applyOptions({ upColor: hex(up), downColor: hex(down), borderUpColor: hex(up), borderDownColor: hex(down),
      wickUpColor: hex(up), wickDownColor: hex(down) });
    const rsi = widget.chart.addIndicator('rsi', { color: '#ff00ff' });
    const macd = widget.chart.addIndicator('macd');
    (window as unknown as { __widget: unknown }).__widget = widget;
    window.__paneReorder = { chart: widget.chart, rsi, macd };
  }, [UP, DOWN, movable ?? null] as const);
  await paint(page);
}

test('the widget pane menu moves the price pane to the bottom and the saved widget state keeps it there', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mountWidget(page, true);
  const moveDown = async () => {
    const boxes = await paneBoxes(page);
    const primary = await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex());
    const box = boxes[primary];
    await page.mouse.click(300, box.top + box.height / 2, { button: 'right' });
    const row = page.locator('.oac-ctx__row[data-act="pane-down"]');
    await expect(row).toBeVisible();
    await row.click();
    await paint(page);
  };
  await moveDown();
  expect(await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex())).toBe(1);
  await moveDown();
  expect(await page.evaluate(() => window.__paneReorder.chart.primaryPaneIndex())).toBe(2);
  // At the bottom the menu greys the row that has nowhere to go and offers no fold.
  const boxes = await paneBoxes(page);
  await page.mouse.click(300, boxes[2].top + boxes[2].height / 2, { button: 'right' });
  await expect(page.locator('.oac-ctx__row[data-act="pane-down"]')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.locator('.oac-ctx__row[data-act="pane-collapse"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('widget-menu-price-bottom.png') });
  await page.keyboard.press('Escape');
  await page.mouse.move(990, 695);
  await paint(page);
  expect(await candles(page, 2)).toBeGreaterThan(200);
  expect(await candles(page, 0)).toBe(0);
  const state = await page.evaluate(() => JSON.parse(JSON.stringify((window as unknown as { __widget: { getState(): unknown } }).__widget.getState())));
  expect(state.chart).toMatchObject({ version: 2, primaryPane: 2 });
  await page.screenshot({ path: info.outputPath('widget-price-bottom.png') });
  expect(errors).toEqual([]);
});

test('a widget built without the option keeps the price pane on top: the up control of the first study and its menu row do nothing', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mountWidget(page);
  const probe = () => page.evaluate(() => {
    const { chart, rsi } = window.__paneReorder;
    const y = chart.priceToCoordinate(100, 0);
    return { movable: chart.movablePrimaryPane(), primary: chart.primaryPaneIndex(), rsi: rsi.paneIndex,
      price: y === null ? null : chart.coordinateToPrice(y, 0) };
  });
  const before = await probe();
  expect(before).toMatchObject({ movable: false, primary: 0, rsi: 1 });
  expect(before.price).toBeCloseTo(100, 6);
  const up = await rowControl(page, 'rsi', 'up');
  await page.mouse.click(up.x, up.y);
  await page.mouse.move(990, 695);
  await paint(page);
  // The study pane's menu greys the row that would displace the price pane, and says why.
  const boxes = await paneBoxes(page);
  await page.mouse.click(300, boxes[1].top + boxes[1].height / 2, { button: 'right' });
  const row = page.locator('.oac-ctx__row[data-act="pane-up"]');
  await expect(row).toHaveAttribute('aria-disabled', 'true');
  await expect(row).toContainText('price pane stays on top');
  await page.screenshot({ path: info.outputPath('widget-pinned-menu.png') });
  await row.click({ force: true });
  await page.keyboard.press('Escape');
  await page.mouse.move(990, 695);
  await paint(page);
  const after = await probe();
  expect(after).toMatchObject({ movable: false, primary: 0, rsi: 1 });
  expect(after.price).toBeCloseTo(100, 6);
  expect(await candles(page, 0)).toBeGreaterThan(200);
  expect(await candles(page, 1)).toBe(0);
  const state = await page.evaluate(() => JSON.parse(JSON.stringify((window as unknown as { __widget: { getState(): unknown } }).__widget.getState())));
  expect(state.chart.version).toBe(1);
  expect(state.chart).not.toHaveProperty('primaryPane');
  await page.screenshot({ path: info.outputPath('widget-pinned-price-top.png') });
  expect(errors).toEqual([]);
});
