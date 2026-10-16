import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window { __paneCollapse: { chart: Chart; rsi: IndicatorApi; cci?: IndicatorApi } }
}

const STRIP = 30;
const TIME_AXIS = 22;

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** A dark price pane with an RSI pane and a MACD pane under it, drawn in colours no chrome uses. */
async function mount(page: Page) {
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.route('**/pane-collapse.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#c{width:960px;height:640px}</style></head><body><div id="c"></div></body></html>',
  }));
  await page.goto('/pane-collapse.html');
  await page.evaluate(async () => {
    const base = '/dist/openalgo-charts.mjs', studies = '/dist/openalgo-charts.indicators.mjs';
    const { createChart, darkTheme } = await import(base) as typeof Charts;
    await import(studies);
    const chart = createChart(document.getElementById('c')!, {
      theme: darkTheme, branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    });
    const bars = Array.from({ length: 160 }, (_, i) => {
      const close = 100 + Math.sin(i / 6) * 8 + i * 0.05;
      return { time: 1700000000 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
    });
    chart.addSeries('candlestick').setData(bars);
    const rsi = chart.addIndicator('rsi', { color: '#ff00ff' });
    chart.addIndicator('macd');
    window.__paneCollapse = { chart, rsi };
  });
  await paint(page);
}

const paneBoxes = (page: Page) => page.evaluate(() => window.__paneCollapse.chart.panes()
  .map(pane => { const r = pane.element.getBoundingClientRect(); return { top: r.top, height: r.height }; }));

/**
 * Pixels of one colour on a pane's base canvas, where its series paint. The
 * legend row, which also wears the plot colour, is on the overlay canvas.
 */
const plotPixels = (page: Page, paneIndex: number, rgb: [number, number, number]) => page.evaluate(([index, [r, g, b]]) => {
  const canvas = window.__paneCollapse.chart.panes()[index].base.element;
  if (!canvas.width || !canvas.height) return 0;
  const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
  let hits = 0;
  for (let i = 0; i < data.length; i += 4) if (Math.abs(data[i] - r) < 24 && Math.abs(data[i + 1] - g) < 24 && Math.abs(data[i + 2] - b) < 24) hits++;
  return hits;
}, [paneIndex, rgb] as const);

/** One of a study row's controls, the collapse control unless told otherwise, found once the pointer has revealed it. */
async function rowControl(page: Page, study: 'rsi' | 'cci' = 'rsi', action = 'collapse'): Promise<{ x: number; y: number }> {
  const find = () => page.evaluate(([key, name]) => {
    const { chart } = window.__paneCollapse;
    const handle = window.__paneCollapse[key]!;
    const buttons = (handle.legend() as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
    const button = buttons.find(b => b.id.endsWith('::' + name));
    if (!button) return null;
    const pane = chart.panes()[handle.paneIndex].element.getBoundingClientRect();
    return { x: pane.left + button.x + 8, y: pane.top + button.y + 8 };
  }, [study, action] as const);
  const boxes = await paneBoxes(page);
  await page.mouse.move(40, boxes[1].top + 15);
  await paint(page);
  let at = await find();
  expect(at).not.toBeNull();
  // The row's readings follow the crosshair, so a control can shift as the
  // pointer moves onto it. Follow it until it holds still under the pointer.
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

test('a lower pane folds to its header strip from its legend and opens back pixel for pixel', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  const open = await paneBoxes(page);
  const before = await page.locator('#c').screenshot();
  expect(await plotPixels(page, 1, [255, 0, 255])).toBeGreaterThan(50);

  const control = await rowControl(page);
  await page.mouse.click(control.x, control.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneCollapse.chart.paneCollapsed(1))).toBe(true);
  const folded = await paneBoxes(page);
  expect(folded[1].height).toBeCloseTo(STRIP, 0);
  expect(folded[0].height).toBeGreaterThan(open[0].height);
  expect(folded[0].height + folded[1].height + folded[2].height).toBeCloseTo(640, 0);
  // The strip keeps the study's legend row and drops its plot.
  expect(await plotPixels(page, 1, [255, 0, 255])).toBe(0);
  expect(await page.evaluate(() => window.__paneCollapse.rsi.legend()!.options().collapsed)).toBe(true);
  await page.screenshot({ path: info.outputPath('collapsed.png') });

  const again = await rowControl(page);
  await page.mouse.click(again.x, again.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneCollapse.chart.paneCollapsed(1))).toBe(false);
  expect(await paneBoxes(page)).toEqual(open);
  // The clicks focused the chart; the first capture was taken before any focus.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await paint(page);
  const after = await page.locator('#c').screenshot();
  await page.screenshot({ path: info.outputPath('restored.png') });
  expect(after.equals(before)).toBe(true);
  expect(errors).toEqual([]);
});

test('a strip keeps its row and the way back while study legends are compact', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  await page.evaluate(() => {
    const { chart } = window.__paneCollapse;
    chart.setPaneCollapsed(1, true);
    chart.setIndicatorLegendCollapsed(true);
  });
  await paint(page);
  await page.screenshot({ path: info.outputPath('compact-strip.png') });
  const control = await rowControl(page);
  await page.mouse.click(control.x, control.y);
  await paint(page);
  expect(await page.evaluate(() => window.__paneCollapse.chart.paneCollapsed(1))).toBe(false);
  // Open again, the row folds back behind the count like every other study row.
  expect(await page.evaluate(() => window.__paneCollapse.chart.indicatorLegendCollapsed())).toBe(true);
  expect(await plotPixels(page, 1, [255, 0, 255])).toBeGreaterThan(50);
  expect(errors).toEqual([]);
});

test('the bottom pane folds above a time axis that stays at the foot of the chart', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  await page.evaluate(() => window.__paneCollapse.chart.setPaneCollapsed(2, true));
  await paint(page);
  const boxes = await paneBoxes(page);
  expect(boxes[2].height).toBeCloseTo(STRIP + TIME_AXIS, 0);
  expect(boxes[2].top + boxes[2].height).toBeCloseTo(640, 0);
  // Time labels still print in the bottom row of the strip, and nothing prints above them.
  const rows = await page.evaluate(([strip]) => {
    const canvas = window.__paneCollapse.chart.panes()[2].base.element;
    const ctx = canvas.getContext('2d')!;
    const ratio = canvas.width / canvas.getBoundingClientRect().width;
    const lit = (from: number, to: number) => {
      const data = ctx.getImageData(0, Math.round(from * ratio), Math.round(canvas.width * 0.8), Math.round((to - from) * ratio)).data;
      let bright = 0;
      for (let i = 0; i < data.length; i += 4) if (data[i] + data[i + 1] + data[i + 2] > 300) bright++;
      return bright;
    };
    return { plot: lit(1, strip - 1), axis: lit(strip + 2, strip + 20) };
  }, [STRIP] as const);
  expect(rows.axis).toBeGreaterThan(0);
  expect(rows.plot).toBe(0);
  await page.screenshot({ path: info.outputPath('bottom-collapsed.png') });
  expect(errors).toEqual([]);
});

test('a strip shows one row, and closing that row on the strip leaves the next one the way back', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  await page.evaluate(() => {
    const state = window.__paneCollapse;
    state.cci = state.chart.addIndicator('cci', {}, { paneIndex: 1 });
    state.chart.setPaneCollapsed(1, true);
  });
  await page.mouse.move(980, 690);
  await paint(page);
  // The second row starts inside the strip's lower inset: drawn, the tops of
  // its letters would show along the strip's bottom edge.
  const band = await page.evaluate(([strip]) => {
    const canvas = window.__paneCollapse.chart.panes()[1].top.element;
    const ratio = canvas.width / canvas.getBoundingClientRect().width;
    const data = canvas.getContext('2d')!.getImageData(0, Math.round((strip - 6) * ratio), Math.round(canvas.width * 0.5), Math.round(6 * ratio)).data;
    let lit = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) lit++;
    return lit;
  }, [STRIP] as const);
  expect(band).toBe(0);
  await page.screenshot({ path: info.outputPath('two-study-strip.png') });

  const close = await rowControl(page, 'rsi', 'close');
  await page.mouse.click(close.x, close.y);
  await page.mouse.move(980, 690);
  await paint(page);
  expect(await page.evaluate(() => window.__paneCollapse.chart.indicators().map(study => study.id)))
    .not.toContain(await page.evaluate(() => window.__paneCollapse.rsi.id));
  expect(await page.evaluate(() => window.__paneCollapse.chart.paneCollapsed(1))).toBe(true);
  await page.screenshot({ path: info.outputPath('strip-after-close.png') });
  const control = await rowControl(page, 'cci');
  await page.mouse.click(control.x, control.y);
  await paint(page);
  expect(await page.evaluate(() => window.__paneCollapse.chart.paneCollapsed(1))).toBe(false);
  expect(errors).toEqual([]);
});
