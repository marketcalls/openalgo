import { test, expect, type Page } from '@playwright/test';

/**
 * Visibility per interval in the reference host, in a real browser. A trend
 * line through the two swing lows of the daily window is limited, from the
 * properties bar, to weekly bars and up, and a level at the window's high to
 * daily bars and down; switching the interval with the toolbar's pills then
 * shows and hides each one. What is checked is the pixels the chart paints,
 * not only the model: a drawing a range hides must leave nothing on screen,
 * and one it shows must be drawn. First of all, the page opens on a history
 * range its daily chart can serve.
 */

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

/** A trend line through the lowest low of each half of the window, and a level at its highest high. */
async function place(page: Page): Promise<{ line: string; level: string }> {
  return page.evaluate(() => {
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
    return { line: line.id, level: level.id };
  });
}

/** Two frames: whatever changed lands on the canvases in the next one. */
const frames = (page: Page) => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

/**
 * Pixels of the chart's canvases in a drawing's colour, after the next frame:
 * magenta for the line, cyan for the level. The level is horizontal, so only
 * cyan pixels in a horizontal run of at least 12 count: on Linux the legend's
 * anti-aliased text leaves scattered pixels in that colour range, which no
 * glyph stroke ever runs 12 pixels long.
 */
const painted = async (page: Page) => { await frames(page); return page.evaluate(() => {
  let magenta = 0;
  let cyan = 0;
  for (const cv of document.querySelectorAll<HTMLCanvasElement>('#chart canvas')) {
    const ctx = cv.getContext('2d');
    if (!ctx || cv.width === 0 || cv.height === 0) continue;
    const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
    for (let y = 0; y < cv.height; y++) {
      let run = 0;
      for (let x = 0; x <= cv.width; x++) {
        const i = (y * cv.width + x) * 4;
        const isCyan = x < cv.width && data[i] < 40 && data[i + 1] > 200 && data[i + 2] > 225;
        if (x < cv.width && data[i] > 225 && data[i + 1] < 50 && data[i + 2] > 225) magenta++;
        if (isCyan) { run++; continue; }
        if (run >= 12) cyan += run;
        run = 0;
      }
    }
  }
  return { magenta, cyan };
}); };

/** Switch the interval with the toolbar's pill, and wait for the rebuilt chart to draw it. */
async function switchTo(page: Page, label: string, code: string): Promise<void> {
  await page.locator('#shellbar .pills button', { hasText: new RegExp(`^${label}$`) }).first().click();
  await page.waitForFunction((c) => {
    const app = (window as any).__oac?.app;
    return app?.req?.interval === c && !app.loading && app.draw?.interval?.() === c && app.currentBars?.length > 0;
  }, code);
}

/** Pick an interval for one end of the selected drawing's range from the properties bar. */
async function limit(page: Page, path: 'intervals.from' | 'intervals.to', value: string): Promise<void> {
  if (await page.locator('.pb-pop').count() === 0) await page.locator('#propbar [data-pop="more"]').click();
  await page.locator(`.pb-pop select[data-path="${path}"]`).selectOption(value);
}

test('the page opens on the five years a daily chart loads, with no range it had to refuse', async ({ page }) => {
  await page.waitForFunction(() => !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => (window as any).__oac.app.req)).toMatchObject({ interval: '1d', period: '5y' });
  await expect(page.locator('#status')).toContainText('1d/5y');
  await expect(page.locator('#status')).not.toContainText('unavailable');
  await expect(page.getByRole('button', { name: 'History range' })).toHaveText('5y');
});

test('a range set from the properties bar shows and hides each drawing as the interval changes', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const s = await place(page);
  const before = await painted(page);
  expect(before.magenta).toBeGreaterThan(40);
  expect(before.cyan).toBeGreaterThan(40);

  // Weekly bars and up for the line: off the daily chart at once, kept in the model.
  await page.evaluate(id => (window as any).__oac.app.draw.select(id), s.line);
  await limit(page, 'intervals.from', '1wk');
  expect(await page.evaluate(id => (window as any).__oac.app.draw.get(id).intervals, s.line)).toEqual({ from: '1wk' });
  await expect(page.locator('#propbar [data-note="interval"]')).toHaveText(/hidden on 1d/i);
  await page.screenshot({ path: info.outputPath('line-hidden-on-daily.png') });
  await page.keyboard.press('Escape');
  await page.evaluate(() => (window as any).__oac.app.draw.select(null));
  const daily = await painted(page);
  expect(daily.magenta).toBe(0);
  expect(daily.cyan).toBeGreaterThan(40);

  // On weekly bars the line is drawn; limit the level to daily bars and down.
  await switchTo(page, '1W', '1wk');
  expect(await page.evaluate(id => (window as any).__oac.app.draw.shownOnInterval(id), s.line)).toBe(true);
  const weekly = await painted(page);
  expect(weekly.magenta).toBeGreaterThan(40);
  expect(weekly.cyan).toBeGreaterThan(40);
  await page.evaluate(id => (window as any).__oac.app.draw.select(id), s.level);
  await limit(page, 'intervals.to', '1d');
  await page.keyboard.press('Escape');
  await page.evaluate(() => (window as any).__oac.app.draw.select(null));
  const weeklyLimited = await painted(page);
  expect(weeklyLimited.magenta).toBeGreaterThan(40);
  expect(weeklyLimited.cyan).toBe(0);
  await page.screenshot({ path: info.outputPath('weekly-line-shown-level-hidden.png') });

  // And back on daily bars: the level returns and the line goes, with both ranges saved.
  await switchTo(page, '1D', '1d');
  const back = await painted(page);
  expect(back.magenta).toBe(0);
  expect(back.cyan).toBeGreaterThan(40);
  const saved = await page.evaluate(() => (window as any).__oac.app.draw.toJSON());
  expect(saved.version).toBe(3);
  expect(saved.drawings.map((d: { id: string; intervals?: unknown }) => [d.id, d.intervals])).toEqual([
    [s.line, { from: '1wk' }], [s.level, { to: '1d' }],
  ]);
  await page.screenshot({ path: info.outputPath('daily-level-shown-line-hidden.png') });
  expect(errors).toEqual([]);
});

test('Select all leaves out what the interval hides, and the hidden note follows the interval', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const s = await place(page);
  await page.evaluate(id => (window as any).__oac.app.draw.update(id, { intervals: { from: '1wk' } }), s.line);
  const shown = await page.evaluate(() => {
    const { draw } = (window as any).__oac.app;
    return draw.drawings().filter((d: { id: string }) => draw.shownOnInterval(d.id)).map((d: { id: string }) => d.id);
  });
  expect(shown).toContain(s.level);
  expect(shown).not.toContain(s.line);

  // The trash menu: Select all counts and takes only what is on the chart.
  // With nothing selected the button reads as off for a press, but a right
  // click still opens its menu, so the check of actionability is skipped.
  await page.locator('#rail .rail__btn--danger').first().click({ button: 'right', force: true });
  const rows = page.locator('.rail-menu button');
  await expect(rows.first()).toHaveText(`Select all (${shown.length})`);
  await page.screenshot({ path: info.outputPath('select-all-leaves-hidden-out.png') });
  await rows.first().click();
  expect(await page.evaluate(() => [...(window as any).__oac.app.draw.selection()])).toEqual(shown);

  // Picked on purpose, as an objects panel does: the note names the interval
  // on screen. This page rebuilds its chart on a pill, which drops the
  // selection, so the context is changed on the chart in place, as a host
  // that keeps its chart across intervals does.
  await page.evaluate(id => (window as any).__oac.app.draw.select(id), s.line);
  const note = page.locator('#propbar [data-note="interval"]');
  await expect(note).toHaveText(/hidden on 1d/i);
  const context = (interval: string) => page.evaluate((iv) => {
    const { chart } = (window as any).__oac.app;
    chart.setDataContext({ ...chart.getDataContext(), interval: iv });
  }, interval);
  await context('1h');
  expect(await page.evaluate(() => [...(window as any).__oac.app.draw.selection()])).toEqual([s.line]);
  await expect(note).toHaveText(/hidden on 1h/i);
  await page.screenshot({ path: info.outputPath('note-follows-interval.png') });
  await context('1wk');
  expect(await page.evaluate(() => [...(window as any).__oac.app.draw.selection()])).toEqual([s.line]);
  await expect(note).toBeHidden();
  expect((await painted(page)).magenta).toBeGreaterThan(40);
  expect(errors).toEqual([]);
});

test('a click where a hidden drawing lies selects nothing, and the same click selects it where it is shown', async ({ page }) => {
  const s = await place(page);
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('Chart is not visible');
  const at = await page.evaluate((id) => {
    const { chart, draw } = (window as any).__oac.app;
    const [p0, p1] = draw.get(id).points;
    return { x: (chart.timeToCoordinate(p0.time) + chart.timeToCoordinate(p1.time)) / 2,
      y: (chart.priceToCoordinate(p0.price, 0) + chart.priceToCoordinate(p1.price, 0)) / 2 };
  }, s.line);
  await page.evaluate(id => (window as any).__oac.app.draw.update(id, { intervals: { from: '1wk' } }), s.line);
  await frames(page);
  await page.mouse.click(box.x + at.x, box.y + at.y);
  expect(await page.evaluate(() => [...(window as any).__oac.app.draw.selection()])).toEqual([]);
  await page.evaluate(id => (window as any).__oac.app.draw.update(id, { intervals: null }), s.line);
  await page.mouse.move(box.x + 5, box.y + 5);
  await frames(page);
  await page.mouse.click(box.x + at.x, box.y + at.y);
  expect(await page.evaluate(() => [...(window as any).__oac.app.draw.selection()])).toEqual([s.line]);
});
