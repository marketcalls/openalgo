import { test, expect, type Page } from '@playwright/test';

/**
 * The drawing gestures in the reference host, in a real browser: Ctrl held is
 * a strong magnet on a handle, Shift+click lays down a ruler that Escape
 * clears, Ctrl+drag on empty space selects what the box touches without
 * panning, Alt+drag leaves a drawing and moves a copy (one Ctrl+Z takes it
 * back), and the rail's eraser deletes what a drag crosses as one step.
 *
 * Every drawing is computed from the bars on screen: a trend line through the
 * two swing lows of the window and a level at its high, the way a user would
 * place them.
 */

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

type Pt = { x: number; y: number };
type Setup = { line: string; level: string; lineMid: Pt; lineEnd: Pt; levelAt: Pt; box: { x: number; y: number; width: number; height: number } };

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

/**
 * A trend line through the lowest low of each half of the window and a level
 * at the window's highest high, in page px where the test will grab them.
 */
async function place(page: Page): Promise<Setup> {
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('Chart is not visible');
  const at = await page.evaluate(() => {
    const { app } = (window as any).__oac;
    const { chart, draw } = app;
    const bars = app.currentBars as { time: number; high: number; low: number }[];
    const range = chart.getVisibleLogicalRange();
    const from = Math.max(0, Math.ceil(range.from) + 4);
    const to = Math.min(bars.length - 1, Math.floor(range.to) - 4);
    const mid = Math.floor((from + to) / 2);
    const lowest = (a: number, b: number) => {
      let best = a;
      for (let i = a; i <= b; i++) if (bars[i].low < bars[best].low) best = i;
      return best;
    };
    const a = lowest(from, mid - 3);
    const b = lowest(mid + 3, to);
    let top = from;
    for (let i = from; i <= to; i++) if (bars[i].high > bars[top].high) top = i;
    const line = draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 3 },
      points: [{ time: bars[a].time, price: bars[a].low }, { time: bars[b].time, price: bars[b].low }] });
    const level = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: { color: '#00e5ff', lineWidth: 3 },
      points: [{ time: bars[top].time, price: bars[top].high }] });
    draw.select(null);
    const px = (time: number, price: number) => ({ x: chart.timeToCoordinate(time), y: chart.priceToCoordinate(price, 0) });
    const p0 = px(bars[a].time, bars[a].low);
    const p1 = px(bars[b].time, bars[b].low);
    const lvl = px(bars[Math.floor((from + to) / 2)].time, bars[top].high);
    return { line: line.id, level: level.id, lineMid: { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 }, lineEnd: p1, levelAt: lvl };
  });
  const page_ = (p: Pt): Pt => ({ x: box.x + p.x, y: box.y + p.y });
  return { line: at.line, level: at.level, lineMid: page_(at.lineMid), lineEnd: page_(at.lineEnd), levelAt: page_(at.levelAt), box };
}

const state = (page: Page) => page.evaluate(() => {
  const { app } = (window as any).__oac;
  return { ids: app.draw.drawings().map((d: { id: string }) => d.id) as string[], selection: [...app.draw.selection()] as string[],
    range: app.chart.getVisibleLogicalRange(), measuring: app.draw.measuring() as boolean, erasing: app.draw.erasing() as boolean };
});

test('Ctrl held lands a dragged handle on the bar under it, with the magnet off', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const s = await place(page);
  await page.evaluate(id => (window as any).__oac.app.draw.select(id), s.line);
  const target = await page.evaluate(() => {
    const { app } = (window as any).__oac;
    const bars = app.currentBars;
    const k = Math.floor(app.chart.getVisibleLogicalRange().to) - 6;
    const bar = bars[k];
    return { time: bar.time, values: [bar.open, bar.high, bar.low, bar.close],
      x: app.chart.timeToCoordinate(bar.time) + 2, y: app.chart.priceToCoordinate(bar.high, 0) - 3 };
  });
  await page.keyboard.down('Control');
  await page.mouse.move(s.lineEnd.x, s.lineEnd.y);
  await page.mouse.down();
  await page.mouse.move(s.box.x + target.x, s.box.y + target.y, { steps: 6 });
  await page.mouse.up();
  await page.keyboard.up('Control');
  const end = await page.evaluate(id => (window as any).__oac.app.draw.get(id).points[1], s.line);
  expect(end.time).toBe(target.time);
  expect(target.values).toContain(end.price);
  await page.screenshot({ path: info.outputPath('magnet-handle.png') });
  expect(errors).toEqual([]);
});

test('Shift+click lays down a ruler that is never a drawing, and Escape clears it', async ({ page }, info) => {
  const s = await place(page);
  const before = await state(page);
  const start = { x: s.box.x + s.box.width * 0.35, y: s.lineMid.y + 40 };
  await page.mouse.move(start.x, start.y);
  await page.keyboard.down('Shift');
  await page.mouse.click(start.x, start.y);
  await page.keyboard.up('Shift');
  await page.mouse.move(start.x + 220, start.y - 120, { steps: 5 });
  await expect.poll(async () => (await state(page)).measuring).toBe(true);
  await expect(page.locator('#status')).toContainText('measuring');
  await page.screenshot({ path: info.outputPath('ruler.png') });
  expect((await state(page)).ids).toEqual(before.ids);
  await page.keyboard.press('Escape');
  await expect.poll(async () => (await state(page)).measuring).toBe(false);
  expect((await state(page)).ids).toEqual(before.ids);
});

test('Ctrl+drag on empty space selects the line the box crosses, without panning', async ({ page }, info) => {
  const s = await place(page);
  const before = await state(page);
  // The box starts only where nothing answers the pointer: a study's marks are
  // objects too, and where they fall moves with the fixture's clock. Probe the
  // chart's own hover for a start with nothing under it.
  await page.evaluate(() => {
    const w = window as any;
    w.__hover = null;
    w.__oac.app.chart.on('hover', (p: { id: string | null }) => { w.__hover = p.id; });
  });
  let from = { x: s.lineMid.x - 50, y: s.lineMid.y - 45 };
  for (const [dx, dy] of [[-50, -45], [-60, -60], [-40, -70], [-70, -40], [-50, 45], [-60, 60]]) {
    from = { x: s.lineMid.x + dx, y: s.lineMid.y + dy };
    await page.mouse.move(from.x, from.y);
    if (await page.evaluate(() => (window as any).__hover) === null) break;
  }
  expect(await page.evaluate(() => (window as any).__hover)).toBeNull();
  const to = { x: 2 * s.lineMid.x - from.x, y: 2 * s.lineMid.y - from.y };
  await page.keyboard.down('Control');
  await page.mouse.move(from.x - 4, from.y - 4);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 8 });
  await page.screenshot({ path: info.outputPath('box-select.png') });
  await page.mouse.up();
  await page.keyboard.up('Control');
  const after = await state(page);
  expect(after.selection).toEqual([s.line]);
  expect(after.range).toEqual(before.range);
});

test('Alt+drag leaves the level and moves a copy, and one Ctrl+Z takes the copy back', async ({ page }, info) => {
  const s = await place(page);
  const price = () => page.evaluate(id => (window as any).__oac.app.draw.get(id).points[0].price, s.level);
  const original = await price();
  await page.mouse.move(s.levelAt.x, s.levelAt.y);
  await page.keyboard.down('Alt');
  await page.mouse.down();
  await page.mouse.move(s.levelAt.x, s.levelAt.y + 70, { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up('Alt');
  const after = await state(page);
  expect(after.ids).toHaveLength(3);
  expect(await price()).toBe(original);
  const copy = after.ids.find(id => id !== s.line && id !== s.level)!;
  expect(after.selection).toEqual([copy]);
  expect(await page.evaluate(id => (window as any).__oac.app.draw.get(id).points[0].price, copy)).toBeLessThan(original);
  await page.screenshot({ path: info.outputPath('drag-copy.png') });
  await page.mouse.move(s.box.x + 5, s.box.y + 5);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(async () => (await state(page)).ids).toEqual([s.line, s.level]);
});

test('the rail eraser deletes what a drag crosses as one step, and Escape puts it away', async ({ page }, info) => {
  const s = await place(page);
  const eraser = page.locator('#rail .rail__btn--eraser');
  await eraser.click();
  await expect(eraser).toHaveAttribute('aria-pressed', 'true');
  expect((await state(page)).erasing).toBe(true);
  const range = (await state(page)).range;
  // A vertical sweep through the line's middle and up across the level.
  const x = s.lineMid.x;
  await page.mouse.move(x, s.lineMid.y + 30);
  await page.mouse.down();
  await page.mouse.move(x, (s.lineMid.y + s.levelAt.y) / 2, { steps: 6 });
  await page.screenshot({ path: info.outputPath('eraser.png') });
  await page.mouse.move(x, s.levelAt.y - 20, { steps: 6 });
  await page.mouse.up();
  const after = await state(page);
  expect(after.ids).toEqual([]);
  expect(after.range).toEqual(range);
  await page.mouse.move(s.box.x + 5, s.box.y + 5);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(async () => (await state(page)).ids).toEqual([s.line, s.level]);
  await page.keyboard.press('Escape');
  await expect.poll(async () => (await state(page)).erasing).toBe(false);
  await expect(eraser).toHaveAttribute('aria-pressed', 'false');
});
