import { test, expect, type Page } from '@playwright/test';

/**
 * Viewport-anchored drawings in a real browser: a note and a box pinned to the
 * screen must hold their pixels through a pan, move with the hand when
 * dragged, scale with the chart, and read the same at a device pixel ratio of
 * two. A data-space box painted beside them is the control that does move.
 */

type Box = { x0: number; y0: number; x1: number; y1: number; count: number };

const MAGENTA = 'magenta';
const CYAN = 'cyan';
const YELLOW = 'yellow';

async function mount(page: Page, width = 1200, height = 760) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const { createChart } = await import('/dist/openalgo-charts.mjs');
    const { DrawingController } = await import('/dist/openalgo-charts.draw.mjs');
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const bars = Array.from({ length: 200 }, (_, i) => {
      const close = 23800 + Math.sin(i / 8) * 160;
      return { time: 1750000000 + i * 86400, open: close - 20, high: close + 35, low: close - 40, close };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.setVisibleLogicalRange({ from: 60, to: 160 });
    const draw = new DrawingController(chart);
    const note = draw.add({ tool: 'text', paneIndex: 0, points: [], space: 'viewport', viewportPoints: [{ x: 0.04, y: 0.05 }],
      style: {}, text: { value: 'Pinned note', color: '#ffd400', fontSize: 18, bold: true } });
    const box = draw.add({ tool: 'rectangle', paneIndex: 0, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.55, y: 0.12 }, { x: 0.8, y: 0.3 }], style: { color: '#ff00ff', lineWidth: 4 } });
    const moving = draw.add({ tool: 'rectangle', paneIndex: 0,
      points: [{ time: bars[100].time, price: 23700 }, { time: bars[120].time, price: 23600 }], style: { color: '#00ffff', lineWidth: 4 } });
    (window as any).__pin = { chart, draw, note: note.id, box: box.id, moving: moving.id };
  });
  // Park the pointer off the plot so no hover ring is in the pixels.
  await page.mouse.move(2, 2);
  return errors;
}

/** Bounding box, in device px, of the pixels of one colour on the pane's top canvas. */
async function inkBox(page: Page, color: string, selector = '#c canvas', index = 1): Promise<Box> {
  return page.locator(selector).nth(index).evaluate((element, which) => {
    const c = element as HTMLCanvasElement;
    const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    const box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, count: 0 };
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]];
        if (a < 120) continue;
        const hit = which === 'magenta' ? r > 180 && g < 90 && b > 180
          : which === 'cyan' ? r < 90 && g > 180 && b > 180
          : r > 200 && g > 170 && b < 80;
        if (!hit) continue;
        box.count++;
        box.x0 = Math.min(box.x0, x); box.y0 = Math.min(box.y0, y);
        box.x1 = Math.max(box.x1, x); box.y1 = Math.max(box.y1, y);
      }
    }
    return box;
  }, color);
}

const same = (a: Box, b: Box, tolerance = 1) => {
  expect(a.count).toBeGreaterThan(20);
  expect(Math.abs(a.x0 - b.x0)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.y0 - b.y0)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.x1 - b.x1)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.y1 - b.y1)).toBeLessThanOrEqual(tolerance);
};

/** Pan the chart by dragging empty plot, the way a user does. */
async function pan(page: Page, from: { x: number; y: number }, dx: number, dy: number) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + dx, from.y + dy, { steps: 12 });
  await page.mouse.up();
  await page.mouse.move(2, 2);
}

test('a pinned note and box hold their pixels through a pan while a data box moves', async ({ page }, info) => {
  const errors = await mount(page);
  const before = { box: await inkBox(page, MAGENTA), note: await inkBox(page, YELLOW), moving: await inkBox(page, CYAN) };
  expect(before.moving.count).toBeGreaterThan(20);
  await page.screenshot({ path: info.outputPath('before-pan.png') });
  const range0 = await page.evaluate(() => (window as any).__pin.chart.getVisibleLogicalRange());
  await pan(page, { x: 200, y: 640 }, -260, -40);
  const range1 = await page.evaluate(() => (window as any).__pin.chart.getVisibleLogicalRange());
  expect(Math.abs(range1.from - range0.from)).toBeGreaterThan(5);
  await page.screenshot({ path: info.outputPath('after-pan.png') });
  same(await inkBox(page, MAGENTA), before.box);
  same(await inkBox(page, YELLOW), before.note);
  const moved = await inkBox(page, CYAN);
  expect(Math.abs(moved.x0 - before.moving.x0)).toBeGreaterThan(50);
  // Zoom with the wheel: still where it was.
  await page.mouse.move(500, 500);
  await page.mouse.wheel(0, -400);
  await page.mouse.move(2, 2);
  const span = () => page.evaluate(() => {
    const range = (window as any).__pin.chart.getVisibleLogicalRange();
    return range.to - range.from;
  });
  await expect.poll(async () => Math.abs((await span()) - (range1.to - range1.from))).toBeGreaterThan(2);
  same(await inkBox(page, MAGENTA), before.box);
  same(await inkBox(page, YELLOW), before.note);
  await page.screenshot({ path: info.outputPath('after-zoom.png') });
  expect(errors).toEqual([]);
});

test('a pinned box moves with the pointer, stays proportional on resize and restores', async ({ page }, info) => {
  const errors = await mount(page);
  const before = await inkBox(page, MAGENTA);
  const dpr = await page.evaluate(() => window.devicePixelRatio);
  // Grab the box by its edge (its outline is the part that answers the pointer).
  const grab = { x: (before.x0 + before.x1) / 2 / dpr, y: before.y0 / dpr + 2 };
  await pan(page, grab, 80, 40);
  const dragged = await inkBox(page, MAGENTA);
  expect(dragged.x0 - before.x0).toBeGreaterThan(80 * dpr - 3);
  expect(dragged.x0 - before.x0).toBeLessThan(80 * dpr + 3);
  expect(dragged.y0 - before.y0).toBeGreaterThan(40 * dpr - 3);
  expect(dragged.y0 - before.y0).toBeLessThan(40 * dpr + 3);
  const stored = await page.evaluate(() => {
    const { draw, box } = (window as any).__pin;
    return draw.get(box);
  });
  expect(stored.space).toBe('viewport');
  expect(stored.points).toEqual([]);
  await page.screenshot({ path: info.outputPath('after-drag.png') });
  // Resize: the corners stay at the same fraction of the smaller plot.
  await page.setViewportSize({ width: 900, height: 560 });
  await expect.poll(() => page.evaluate(() => (window as any).__pin.chart.timeScale.width)).toBeLessThan(900);
  await page.mouse.move(2, 2);
  const size = await page.evaluate(() => {
    const { chart, draw, box } = (window as any).__pin;
    return { w: chart.timeScale.width, h: chart.panes()[0].priceScale.height, anchors: draw.get(box).viewportPoints };
  });
  await expect.poll(async () => (await inkBox(page, MAGENTA)).x0).toBeLessThan(dragged.x0);
  const resized = await inkBox(page, MAGENTA);
  expect(Math.abs(resized.x0 - size.anchors[0].x * size.w * dpr)).toBeLessThanOrEqual(4);
  expect(Math.abs(resized.y0 - size.anchors[0].y * size.h * dpr)).toBeLessThanOrEqual(4);
  expect(Math.abs(resized.x1 - size.anchors[1].x * size.w * dpr)).toBeLessThanOrEqual(4);
  expect(Math.abs(resized.y1 - size.anchors[1].y * size.h * dpr)).toBeLessThanOrEqual(4);
  await page.screenshot({ path: info.outputPath('after-resize.png') });
  // A save and a restore into a fresh controller put it back where it was.
  await page.evaluate(() => {
    const api = (window as any).__pin;
    const saved = JSON.parse(JSON.stringify(api.draw.toJSON()));
    api.draw.fromJSON({ version: 2, drawings: [] });
    api.draw.fromJSON(saved);
  });
  await page.mouse.move(3, 3);
  same(await inkBox(page, MAGENTA), resized);
  expect(errors).toEqual([]);
});

test.describe('at a device pixel ratio of two', () => {
  test.use({ deviceScaleFactor: 2 });

  test('paints at the same fraction in device px and holds through a pan', async ({ page }, info) => {
    const errors = await mount(page);
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(2);
    const size = await page.evaluate(() => {
      const { chart } = (window as any).__pin;
      return { w: chart.timeScale.width, h: chart.panes()[0].priceScale.height };
    });
    const before = await inkBox(page, MAGENTA);
    // The outline is centred on the anchors, so its outer edge sits half a line out.
    expect(Math.abs(before.x0 - 0.55 * size.w * 2)).toBeLessThanOrEqual(6);
    expect(Math.abs(before.y1 - 0.3 * size.h * 2)).toBeLessThanOrEqual(6);
    await page.screenshot({ path: info.outputPath('dpr2-before-pan.png') });
    await pan(page, { x: 200, y: 640 }, -260, -40);
    await page.screenshot({ path: info.outputPath('dpr2-after-pan.png') });
    same(await inkBox(page, MAGENTA), before);
    expect(errors).toEqual([]);
  });
});

test('the widget pins a drawing from its properties, and a pan leaves it in place', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1100, height: 720 });
  await page.goto('/tests/e2e/drawing-viewport-fixture.html');
  await page.waitForFunction(() => !!(window as any).__viewport);
  const canvas = '.oac-chart canvas';
  await expect.poll(async () => (await inkBox(page, MAGENTA, canvas)).count).toBeGreaterThan(20);
  // Right-click the box's outline, then Properties.
  const edge = await page.evaluate(() => {
    const { widget, rectId } = (window as any).__viewport;
    const [a, b] = widget.draw.screenPoints(rectId);
    const rect = widget.root.querySelector('.oac-chart').getBoundingClientRect();
    return { x: rect.left + (a.x + b.x) / 2, y: rect.top + Math.min(a.y, b.y) };
  });
  await page.mouse.click(edge.x, edge.y, { button: 'right' });
  await page.getByRole('menuitem', { name: /^Properties/ }).click();
  const anchor = page.locator('.oac-props [data-key="space"] select');
  await expect(anchor).toHaveValue('data');
  await anchor.selectOption('viewport');
  await expect.poll(() => page.evaluate(() => {
    const { widget, rectId } = (window as any).__viewport;
    return widget.draw.get(rectId).space;
  })).toBe('viewport');
  await expect(anchor).toHaveValue('viewport');
  await anchor.scrollIntoViewIfNeeded();
  await page.locator('.oac-props').screenshot({ path: info.outputPath('widget-anchor-row.png') });
  await page.getByRole('button', { name: 'Done' }).click();
  await page.mouse.move(5, 5);
  const before = await inkBox(page, MAGENTA, canvas);
  await page.screenshot({ path: info.outputPath('widget-before-pan.png') });
  const plot = await page.evaluate(() => (window as any).__viewport.widget.root.querySelector('.oac-chart').getBoundingClientRect().toJSON());
  await pan(page, { x: plot.left + 300, y: plot.top + plot.height - 80 }, -220, 0);
  await page.screenshot({ path: info.outputPath('widget-after-pan.png') });
  same(await inkBox(page, MAGENTA, canvas), before);
  expect(errors).toEqual([]);
});

// ── the whole drawing on the plot ───────────────────────────────────────────
//
// A note and a table are laid out from one corner, so a rule that holds only
// the anchors inside the pane still lets them sit wholly outside the clipped
// plot. These drag each pinned drawing past every corner with the real
// pointer and check that all of it is still painted (its ink keeps its size,
// so the clip has cut nothing) and that a click on it selects it.

const GREEN = 'green';

/** Bounding box of one colour's ink, like `inkBox`, with pure green for the table. */
async function ink(page: Page, color: string): Promise<Box> {
  if (color !== GREEN) return inkBox(page, color);
  return page.locator('#c canvas').nth(1).evaluate((element) => {
    const c = element as HTMLCanvasElement;
    const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    const box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, count: 0 };
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        if (data[i + 3] < 120 || !(data[i] < 90 && data[i + 1] > 200 && data[i + 2] < 90)) continue;
        box.count++;
        box.x0 = Math.min(box.x0, x); box.y0 = Math.min(box.y0, y);
        box.x1 = Math.max(box.x1, x); box.y1 = Math.max(box.y1, y);
      }
    }
    return box;
  });
}

async function mountEdges(page: Page, width = 1200, height = 760) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const { createChart } = await import('/dist/openalgo-charts.mjs');
    const { DrawingController } = await import('/dist/openalgo-charts.draw.mjs');
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const bars = Array.from({ length: 200 }, (_, i) => {
      const close = 23800 + Math.sin(i / 8) * 160;
      return { time: 1750000000 + i * 86400, open: close - 20, high: close + 35, low: close - 40, close };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.setVisibleLogicalRange({ from: 60, to: 160 });
    const draw = new DrawingController(chart);
    const note = draw.add({ tool: 'text', paneIndex: 0, points: [], space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.1 }],
      style: {}, text: { value: 'Pinned note', color: '#ffd400', fontSize: 18, bold: true } });
    const table = draw.add({ tool: 'table', paneIndex: 0, points: [], space: 'viewport', viewportPoints: [{ x: 0.4, y: 0.4 }],
      style: { lineWidth: 2 }, text: { value: 'Level|Price\nEntry|23810\nStop|23640', color: '#00ff00', borderColor: '#00ff00', fontSize: 14 } });
    const box = draw.add({ tool: 'rectangle', paneIndex: 0, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.6, y: 0.55 }, { x: 0.8, y: 0.8 }], style: { color: '#ff00ff', lineWidth: 4 } });
    (window as any).__edge = { chart, draw, ids: { [note.id]: 'yellow', [table.id]: 'green', [box.id]: 'magenta' }, note: note.id, table: table.id, box: box.id };
  });
  await page.mouse.move(2, 2);
  return errors;
}

/** Show one drawing alone, so another's ink or body never stands in for it. */
async function only(page: Page, id: string | null) {
  await page.evaluate((which) => {
    const { draw, ids } = (window as any).__edge;
    draw.select(null);
    for (const id of Object.keys(ids)) draw.update(id, { visible: which === null || id === which });
  }, id);
  await page.mouse.move(2, 2);
}

async function plotSize(page: Page) {
  return page.evaluate(() => {
    const { chart } = (window as any).__edge;
    return { w: chart.timeScale.width, h: chart.panes()[0].priceScale.height, dpr: window.devicePixelRatio };
  });
}

/**
 * The drawing is whole on screen (its ink has its full size, times `scale`
 * for a box whose corners scale with the plot) and a click on it selects it.
 */
async function expectWholeAndClickable(page: Page, id: string, color: string, full: Box, where: string, scale = { x: 1, y: 1 }) {
  const { dpr } = await plotSize(page);
  const now = await ink(page, color);
  expect(now.count, `${where}: painted`).toBeGreaterThan(full.count * 0.6 * Math.min(scale.x, scale.y));
  expect(Math.abs((now.x1 - now.x0) - (full.x1 - full.x0) * scale.x), `${where}: full width`).toBeLessThanOrEqual(4 * dpr);
  expect(Math.abs((now.y1 - now.y0) - (full.y1 - full.y0) * scale.y), `${where}: full height`).toBeLessThanOrEqual(4 * dpr);
  await page.evaluate(() => (window as any).__edge.draw.select(null));
  // Near its top-right, clear of the chart's logo mark in the bottom-left.
  await page.mouse.click((now.x1 - 6 * dpr) / dpr, (now.y0 + 6 * dpr) / dpr);
  await page.mouse.move(2, 2);
  expect(await page.evaluate(() => (window as any).__edge.draw.selected()), `${where}: clickable`).toBe(id);
  await page.evaluate(() => (window as any).__edge.draw.select(null));
  return now;
}

async function throwTo(page: Page, from: Box, sx: number, sy: number) {
  const { dpr } = await plotSize(page);
  const viewport = page.viewportSize()!;
  // Pressed near its top-right: the chart's logo mark in the bottom-left takes
  // a press on it before any drawing under it does.
  await page.mouse.move((from.x1 - 6 * dpr) / dpr, (from.y0 + 6 * dpr) / dpr);
  await page.mouse.down();
  await page.mouse.move(sx > 0 ? viewport.width - 2 : 1, sy > 0 ? viewport.height - 2 : 1, { steps: 16 });
  await page.mouse.up();
  await page.mouse.move(2, 2);
}

async function edgesAndResize(page: Page, info: { outputPath(name: string): string }, prefix: string) {
  const ids = await page.evaluate(() => {
    const { note, table, box } = (window as any).__edge;
    return [[note, 'yellow'], [table, 'green'], [box, 'magenta']] as [string, string][];
  });
  const full = new Map<string, Box>();
  for (const [id, color] of ids) {
    await only(page, id);
    full.set(id, await ink(page, color));
    expect(full.get(id)!.count).toBeGreaterThan(20);
  }
  const corners: [number, number, string][] = [[1, 1, 'bottom-right'], [-1, -1, 'top-left'], [1, -1, 'top-right'], [-1, 1, 'bottom-left'], [1, 1, 'bottom-right']];
  for (const [id, color] of ids) {
    await only(page, id);
    for (const [sx, sy, name] of corners) {
      await throwTo(page, await ink(page, color), sx, sy);
      const now = await expectWholeAndClickable(page, id, color, full.get(id)!, `${color} ${name}`);
      // It went all the way into the corner it was thrown at.
      const { w, h, dpr } = await plotSize(page);
      if (sx > 0) expect(now.x1).toBeGreaterThan(w * dpr - 24 * dpr); else expect(now.x0).toBeLessThan(24 * dpr);
      if (sy > 0) expect(now.y1).toBeGreaterThan(h * dpr - 24 * dpr); else expect(now.y0).toBeLessThan(24 * dpr);
      if (name === 'bottom-right') await page.screenshot({ path: info.outputPath(`${prefix}${color}-${name}.png`) });
    }
  }
  // All three sit in the bottom-right corner; a smaller chart must still show
  // each whole and let it be clicked.
  const before = await plotSize(page);
  await page.setViewportSize({ width: 760, height: 480 });
  await expect.poll(async () => (await plotSize(page)).w).toBeLessThan(before.w - 100);
  const after = await plotSize(page);
  for (const [id, color] of ids) {
    await only(page, id);
    await expect.poll(async () => (await ink(page, color)).count).toBeGreaterThan(20);
    // Type keeps its pixel size; a box's corners are fractions of the plot.
    const scale = color === MAGENTA ? { x: after.w / before.w, y: after.h / before.h } : { x: 1, y: 1 };
    await expectWholeAndClickable(page, id, color, full.get(id)!, `${color} after resize`, scale);
    await page.screenshot({ path: info.outputPath(`${prefix}${color}-after-resize.png`) });
  }
  await only(page, null);
  await page.screenshot({ path: info.outputPath(`${prefix}all-after-resize.png`) });
}

test('a pinned note, table and box stay whole on the plot and clickable at every edge and after a resize', async ({ page }, info) => {
  const errors = await mountEdges(page);
  await edgesAndResize(page, info, 'edge-');
  expect(errors).toEqual([]);
});

test.describe('the whole drawing at a device pixel ratio of two', () => {
  test.use({ deviceScaleFactor: 2 });

  test('a pinned note, table and box stay whole on the plot and clickable at every edge and after a resize', async ({ page }, info) => {
    const errors = await mountEdges(page);
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(2);
    await edgesAndResize(page, info, 'dpr2-edge-');
    expect(errors).toEqual([]);
  });
});

// ── a label outside a pinned box ─────────────────────────────────────────────
//
// A box's label with `position: 'outside'` is painted above the box, so a box
// kept on the plot by its outline alone loses the label off the top edge.

async function mountLabelled(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const { createChart } = await import('/dist/openalgo-charts.mjs');
    const { DrawingController } = await import('/dist/openalgo-charts.draw.mjs');
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const bars = Array.from({ length: 200 }, (_, i) => {
      const close = 23800 + Math.sin(i / 8) * 160;
      return { time: 1750000000 + i * 86400, open: close - 20, high: close + 35, low: close - 40, close };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.setVisibleLogicalRange({ from: 60, to: 160 });
    const draw = new DrawingController(chart);
    const box = draw.add({ tool: 'rectangle', paneIndex: 0, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.3, y: 0.4 }, { x: 0.6, y: 0.7 }], style: { color: '#ff00ff', lineWidth: 4 },
      text: { value: 'Outside label', position: 'outside', color: '#ffd400', fontSize: 18, bold: true } });
    (window as any).__label = { chart, draw, box: box.id };
  });
  await page.mouse.move(2, 2);
  return errors;
}

async function labelAtTheTop(page: Page, info: { outputPath(name: string): string }, prefix: string) {
  const dpr = await page.evaluate(() => window.devicePixelRatio);
  const full = { label: await inkBox(page, YELLOW), box: await inkBox(page, MAGENTA) };
  expect(full.label.count).toBeGreaterThan(20);
  expect(full.label.y1).toBeLessThan(full.box.y0);
  // At the top, the label's line (18 px at a gap of 1.35) and its 6 px lift sit
  // above the outline, whose 4 px stroke then starts 2 px higher. Measured on
  // the outline, since where a glyph's ink starts in its line differs by engine.
  const top = (18 * 1.35 + 6 - 2) * dpr;
  const whole = (at: { label: Box; box: Box }) => {
    expect(at.label.count).toBeGreaterThan(full.label.count * 0.9);
    expect(Math.abs((at.label.y1 - at.label.y0) - (full.label.y1 - full.label.y0))).toBeLessThanOrEqual(2 * dpr);
    expect(at.label.y0).toBeGreaterThanOrEqual(0);
    expect(at.label.y1).toBeLessThan(at.box.y0);
    expect(Math.abs(at.box.y0 - top)).toBeLessThanOrEqual(2 * dpr);
  };

  // The top-left handle dragged to the top of the page stops below the label,
  // and the bottom edge stays where it was.
  const corner = await page.evaluate(() => {
    const { draw, box } = (window as any).__label;
    draw.select(box);
    return draw.screenPoints(box)[0];
  });
  await pan(page, corner, 0, -corner.y + 1);
  await page.evaluate(() => (window as any).__label.draw.select(null));
  await page.mouse.move(2, 2);
  const handled = { label: await inkBox(page, YELLOW), box: await inkBox(page, MAGENTA) };
  whole(handled);
  expect(Math.abs(handled.box.y1 - full.box.y1)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath(`${prefix}label-handle-top.png`) });

  // The body thrown past the top-right corner keeps the label whole on the plot.
  await page.evaluate(() => {
    const { draw, box } = (window as any).__label;
    draw.update(box, { viewportPoints: [{ x: 0.3, y: 0.4 }, { x: 0.6, y: 0.7 }] });
  });
  await page.mouse.move(2, 2);
  const from = await inkBox(page, MAGENTA);
  const grab = { x: (from.x1 - 6 * dpr) / dpr, y: (from.y0 + 6 * dpr) / dpr };
  await pan(page, grab, page.viewportSize()!.width - 2 - grab.x, 1 - grab.y);
  await page.evaluate(() => (window as any).__label.draw.select(null));
  await page.mouse.move(2, 2);
  const thrown = { label: await inkBox(page, YELLOW), box: await inkBox(page, MAGENTA) };
  whole(thrown);
  expect(Math.abs((thrown.box.y1 - thrown.box.y0) - (full.box.y1 - full.box.y0))).toBeLessThanOrEqual(2 * dpr);
  await page.screenshot({ path: info.outputPath(`${prefix}label-thrown-top.png`) });
  // Still clickable where it landed.
  await page.mouse.click((thrown.box.x1 - 6 * dpr) / dpr, (thrown.box.y0 + 6 * dpr) / dpr);
  await page.mouse.move(2, 2);
  expect(await page.evaluate(() => (window as any).__label.draw.selected())).toBe(await page.evaluate(() => (window as any).__label.box));
}

test('a pinned box keeps its outside label whole on the plot at the top edge, through a handle and a throw', async ({ page }, info) => {
  const errors = await mountLabelled(page);
  await labelAtTheTop(page, info, '');
  expect(errors).toEqual([]);
});

test.describe('a label outside a pinned box at a device pixel ratio of two', () => {
  test.use({ deviceScaleFactor: 2 });

  test('a pinned box keeps its outside label whole on the plot at the top edge, through a handle and a throw', async ({ page }, info) => {
    const errors = await mountLabelled(page);
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(2);
    await labelAtTheTop(page, info, 'dpr2-');
    expect(errors).toEqual([]);
  });
});

// ── panes, the clipboard, and the other pinnable tools ───────────────────────

type PageBox = { x0: number; y0: number; x1: number; y1: number; count: number };

/** One colour's ink over every canvas of the chart, in page CSS px. */
async function inkAll(page: Page, color: string): Promise<PageBox> {
  return page.evaluate((which) => {
    const out = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, count: 0 };
    for (const c of Array.from(document.querySelectorAll('#c canvas')) as HTMLCanvasElement[]) {
      const rect = c.getBoundingClientRect();
      if (c.width === 0 || c.height === 0) continue;
      const sx = rect.width / c.width;
      const sy = rect.height / c.height;
      const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      for (let y = 0; y < c.height; y++) {
        for (let x = 0; x < c.width; x++) {
          const i = (y * c.width + x) * 4;
          const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]];
          if (a < 120) continue;
          const hit = which === 'magenta' ? r > 180 && g < 90 && b > 180
            : which === 'cyan' ? r < 90 && g > 180 && b > 180
            : which === 'green' ? r < 90 && g > 200 && b < 90
            : r > 200 && g > 170 && b < 80;
          if (!hit) continue;
          out.count++;
          out.x0 = Math.min(out.x0, rect.left + x * sx); out.y0 = Math.min(out.y0, rect.top + y * sy);
          out.x1 = Math.max(out.x1, rect.left + x * sx); out.y1 = Math.max(out.y1, rect.top + y * sy);
        }
      }
    }
    return out;
  }, color);
}

const samePage = (a: PageBox, b: PageBox, tolerance = 1.5) => {
  expect(a.count).toBeGreaterThan(20);
  expect(Math.abs(a.x0 - b.x0)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.y0 - b.y0)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.x1 - b.x1)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(a.y1 - b.y1)).toBeLessThanOrEqual(tolerance);
};

test('a pinned ellipse and table hold through a pan, a note follows its pane through a move and a fold, and a paste lands at the offset', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const { createChart } = await import('/dist/openalgo-charts.mjs');
    const { DrawingController } = await import('/dist/openalgo-charts.draw.mjs');
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const bars = Array.from({ length: 200 }, (_, i) => {
      const close = 23800 + Math.sin(i / 8) * 160;
      return { time: 1750000000 + i * 86400, open: close - 20, high: close + 35, low: close - 40, close };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.addSeries('line', { paneIndex: 1, style: { color: '#8080ff' } }).setData(bars.map(b => ({ time: b.time, value: b.close })));
    chart.addSeries('line', { paneIndex: 2, style: { color: '#8080ff' } }).setData(bars.map(b => ({ time: b.time, value: b.open })));
    chart.setVisibleLogicalRange({ from: 60, to: 160 });
    let memory = '';
    const draw = new DrawingController(chart, { clipboard: { writeText: async (t: string) => { memory = t; }, readText: async () => memory } });
    const ellipse = draw.add({ tool: 'ellipse', paneIndex: 0, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.55, y: 0.12 }, { x: 0.8, y: 0.45 }], style: { color: '#ff00ff', lineWidth: 4, fill: false } });
    const table = draw.add({ tool: 'table', paneIndex: 0, points: [], space: 'viewport', viewportPoints: [{ x: 0.08, y: 0.1 }],
      style: { lineWidth: 2 }, text: { value: 'Level|Price\nEntry|23810\nStop|23640', color: '#00ff00', borderColor: '#00ff00', fontSize: 14 } });
    const note = draw.add({ tool: 'text', paneIndex: 1, points: [], space: 'viewport', viewportPoints: [{ x: 0.3, y: 0.25 }],
      style: {}, text: { value: 'Pane note', color: '#ffd400', fontSize: 16, bold: true } });
    const moving = draw.add({ tool: 'rectangle', paneIndex: 0,
      points: [{ time: bars[100].time, price: 23700 }, { time: bars[120].time, price: 23600 }], style: { color: '#00ffff', lineWidth: 4 } });
    (window as any).__panes = { chart, draw, ellipse: ellipse.id, table: table.id, note: note.id, moving: moving.id };
  });
  await page.mouse.move(2, 2);
  const paneFrame = (index: number) => page.evaluate((i) => {
    const { chart } = (window as any).__panes;
    const pane = chart.panes()[i];
    return { top: chart.priceToCoordinate(pane.yToPrice(0), i), h: pane.priceScale.height, w: chart.timeScale.width };
  }, index);

  const before = { ellipse: await inkAll(page, MAGENTA), table: await inkAll(page, GREEN), note: await inkAll(page, YELLOW), moving: await inkAll(page, CYAN) };
  expect(before.note.count).toBeGreaterThan(20);
  await page.screenshot({ path: info.outputPath('panes-before.png') });
  await pan(page, { x: 300, y: 380 }, -260, 0);
  samePage(await inkAll(page, MAGENTA), before.ellipse);
  samePage(await inkAll(page, GREEN), before.table);
  samePage(await inkAll(page, YELLOW), before.note);
  expect(Math.abs((await inkAll(page, CYAN)).x0 - before.moving.x0)).toBeGreaterThan(50);
  await page.screenshot({ path: info.outputPath('panes-after-pan.png') });

  // The note's pane moves down a slot: the note goes with it, at the same fraction of it.
  const upper = await paneFrame(1);
  const fraction = { x: before.note.x0 / upper.w, y: (before.note.y0 - upper.top) / upper.h };
  expect(await page.evaluate(() => (window as any).__panes.chart.movePane(1, 1))).toBe(true);
  expect(await page.evaluate(() => { const { draw, note } = (window as any).__panes; return draw.get(note).paneIndex; })).toBe(2);
  const lower = await paneFrame(2);
  expect(lower.top).toBeGreaterThan(upper.top + 20);
  await expect.poll(async () => (await inkAll(page, YELLOW)).y0).toBeGreaterThan(lower.top);
  const moved = await inkAll(page, YELLOW);
  expect(Math.abs(moved.x0 / lower.w - fraction.x) * lower.w).toBeLessThanOrEqual(3);
  expect(Math.abs((moved.y0 - lower.top) / lower.h - fraction.y) * lower.h).toBeLessThanOrEqual(3);
  expect(Math.abs((moved.x1 - moved.x0) - (before.note.x1 - before.note.x0))).toBeLessThanOrEqual(2);
  await page.screenshot({ path: info.outputPath('panes-after-move.png') });

  // Folded to its strip, the pane shows no note; opened again, the note is back where it was.
  expect(await page.evaluate(() => (window as any).__panes.chart.setPaneCollapsed(2, true))).toBe(true);
  await expect.poll(async () => (await inkAll(page, YELLOW)).count).toBe(0);
  await page.screenshot({ path: info.outputPath('panes-folded.png') });
  expect(await page.evaluate(() => (window as any).__panes.chart.setPaneCollapsed(2, false))).toBe(true);
  await expect.poll(async () => (await inkAll(page, YELLOW)).count).toBeGreaterThan(20);
  samePage(await inkAll(page, YELLOW), moved);
  await page.screenshot({ path: info.outputPath('panes-unfolded.png') });

  // Copy and paste the ellipse: a second one, offset by the paste offset on both axes.
  const one = await inkAll(page, MAGENTA);
  const pasted = await page.evaluate(async () => {
    const { draw, ellipse } = (window as any).__panes;
    await draw.copy(ellipse);
    const [copy] = await draw.paste();
    draw.select(null);
    return { space: copy.space, paneIndex: copy.paneIndex };
  });
  expect(pasted.space).toBe('viewport');
  await page.mouse.move(2, 2);
  await expect.poll(async () => (await inkAll(page, MAGENTA)).count).toBeGreaterThan(one.count * 1.5);
  const two = await inkAll(page, MAGENTA);
  expect(Math.abs(two.x0 - one.x0)).toBeLessThanOrEqual(1.5);
  expect(Math.abs(two.y0 - one.y0)).toBeLessThanOrEqual(1.5);
  expect(Math.abs(two.x1 - one.x1 - 16)).toBeLessThanOrEqual(2);
  expect(Math.abs(two.y1 - one.y1 - 16)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: info.outputPath('panes-after-paste.png') });
  expect(errors).toEqual([]);
});

test('a pinned box paints inside chart.plotRect, beside a left axis and in a lower pane', async ({ page }, info) => {
  const errors = await mount(page);
  const layout = await page.evaluate(() => {
    const { chart, draw, box, note, moving } = (window as any).__pin;
    for (const id of [box, note, moving]) draw.remove(id);
    // A left scale gives the plot a left column, and a second pane moves the plot down.
    const bars = chart.primaryBars();
    chart.addSeries('line', { priceScaleId: 'left' }).setData(bars.map((bar: { time: number; close: number }) => ({ time: bar.time, value: bar.close / 100 })));
    chart.addSeries('line', { paneIndex: 1 }).setData(bars.map((bar: { time: number; close: number }) => ({ time: bar.time, value: bar.close })));
    const pinned = draw.add({ tool: 'rectangle', paneIndex: 1, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.2, y: 0.25 }, { x: 0.6, y: 0.75 }], style: { color: '#ff00ff', lineWidth: 4 } });
    (window as any).__pin.box = pinned.id;
    return { rect: chart.plotRect(1), top0: chart.plotRect(0), screen: draw.screenPoints(pinned.id), dpr: devicePixelRatio };
  });
  expect(layout.rect.left).toBeGreaterThan(20);
  expect(layout.rect.top).toBeGreaterThan(layout.top0.top + layout.top0.height - 1);
  // The host reads the same rectangle the drawing is placed by.
  expect(layout.screen[0].x).toBeCloseTo(layout.rect.left + 0.2 * layout.rect.width, 6);
  expect(layout.screen[0].y).toBeCloseTo(layout.rect.top + 0.25 * layout.rect.height, 6);
  expect(layout.screen[1].x).toBeCloseTo(layout.rect.left + 0.6 * layout.rect.width, 6);
  expect(layout.screen[1].y).toBeCloseTo(layout.rect.top + 0.75 * layout.rect.height, 6);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('pinned-in-lower-pane.png') });
  // Pane 1's top canvas: its pixels sit where the rectangle says, within a stroke.
  const ink = await inkBox(page, MAGENTA, '#c canvas', 3);
  const { rect, dpr } = layout, stroke = 4 * dpr;
  expect(Math.abs(ink.x0 - (rect.left + 0.2 * rect.width) * dpr)).toBeLessThanOrEqual(stroke);
  expect(Math.abs(ink.x1 - (rect.left + 0.6 * rect.width) * dpr)).toBeLessThanOrEqual(stroke);
  expect(Math.abs(ink.y0 - 0.25 * rect.height * dpr)).toBeLessThanOrEqual(stroke);
  expect(Math.abs(ink.y1 - 0.75 * rect.height * dpr)).toBeLessThanOrEqual(stroke);
  expect(errors).toEqual([]);
});
