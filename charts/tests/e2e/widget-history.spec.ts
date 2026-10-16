import { test, expect, type Page } from '@playwright/test';

// The chart-wide timeline with real input: a study from the picker, a line
// drawn with the pointer, a pane folded from the right-click menu and a
// chart type from the top bar, walked back and forth with the keyboard, the
// rail and, on a narrow screen, the mobile sheet. Pixels are read as well as
// the model: a pane that came back has to be painted where it was.

const TREND = '.oac-rail .oac-rail__fav[data-tools="trend-line"]';

async function mount(page: Page, fixture = 'widget-fixture.html', width = 1100, height = 700): Promise<string[]> {
  const errors: string[] = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  await page.setViewportSize({ width, height });
  await page.goto('/tests/e2e/' + fixture);
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0, undefined, { timeout: 20_000 });
  return errors;
}

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** What the timeline should be walking: the model the user sees. */
const state = (page: Page) => page.evaluate(() => {
  const w = (window as any).__widget;
  return {
    studies: w.chart.indicators().map((s: any) => s.indicatorId),
    panes: w.chart.panes().length,
    folded: w.chart.panes().map((_: unknown, i: number) => w.chart.paneCollapsed(i)),
    drawings: w.draw.drawings().length,
    type: w.chartType(),
  };
});

/** Where each pane of the chart sits on the page. */
const paneBoxes = (page: Page) => page.evaluate(() => (window as any).__widget.chart.panes()
  .map((pane: any) => { const r = pane.element.getBoundingClientRect(); return { x: r.left, y: r.top, width: r.width, height: r.height }; }));

/** Lit pixels on one pane's base canvas, to see that the pane is painted with something on it. */
const ink = (page: Page, pane: number) => page.evaluate(index => {
  const element = (window as any).__widget.chart.panes()[index]?.element as HTMLElement | undefined;
  const canvas = element?.querySelector('canvas');
  if (!canvas || canvas.width === 0 || canvas.height === 0) return 0;
  const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
  let lit = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] > 60 || data[i + 1] > 60 || data[i + 2] > 70) lit++;
  return lit;
}, pane);

test('keys walk a study, a drawing, a pane fold and a chart type back and forth in order', async ({ page }, info) => {
  const errors = await mount(page);

  // A study from the picker.
  await page.locator('.oac-topbar button[aria-label="Indicators"]').click();
  await page.getByRole('searchbox', { name: 'Search indicators' }).fill('RSI');
  await page.locator('.oac-pick__list [role="option"][data-id="rsi"]').click();
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect.poll(() => state(page).then(s => s.studies)).toEqual(['rsi']);

  // A line drawn with the pointer.
  await page.locator(TREND).click();
  const price = (await paneBoxes(page))[0];
  await page.mouse.click(price.x + price.width * 0.3, price.y + price.height * 0.3);
  await page.mouse.click(price.x + price.width * 0.6, price.y + price.height * 0.6);
  await expect.poll(() => state(page).then(s => s.drawings)).toBe(1);
  await page.keyboard.press('Escape');

  // The study pane folded from the right-click menu.
  const study = (await paneBoxes(page))[1];
  await page.mouse.click(study.x + study.width * 0.4, study.y + study.height * 0.5, { button: 'right' });
  await page.locator('.oac-ctx__row[data-act="pane-collapse"]').click();
  await expect.poll(() => state(page).then(s => s.folded)).toEqual([false, true]);

  // A chart type from the top bar.
  await page.locator('.oac-topbar button[aria-label="Chart type"]').click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  await expect.poll(() => state(page).then(s => s.type)).toBe('line');
  await paint(page);
  await page.screenshot({ path: info.outputPath('history-all-steps.png') });

  // Back through all four with the keyboard, the pointer over the chart.
  await page.mouse.move(price.x + price.width * 0.5, price.y + price.height * 0.5);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page).then(s => s.type)).toBe('candlestick');
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page).then(s => s.folded)).toEqual([false, false]);
  await paint(page);
  const opened = (await paneBoxes(page))[1];
  expect(opened.height).toBeGreaterThan(60);
  await expect.poll(() => ink(page, 1)).toBeGreaterThan(200);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page).then(s => s.drawings)).toBe(0);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page)).toMatchObject({ studies: [], panes: 1 });
  await paint(page);
  await page.screenshot({ path: info.outputPath('history-all-undone.png') });

  // And forward again with the two redo chords.
  await page.keyboard.press('ControlOrMeta+y');
  await expect.poll(() => state(page).then(s => s.studies)).toEqual(['rsi']);
  await paint(page);
  expect((await paneBoxes(page))[1].height).toBeGreaterThan(60);
  await expect.poll(() => ink(page, 1)).toBeGreaterThan(200);
  await page.keyboard.press('ControlOrMeta+Shift+z');
  await expect.poll(() => state(page).then(s => s.drawings)).toBe(1);
  await page.keyboard.press('ControlOrMeta+y');
  await page.keyboard.press('ControlOrMeta+y');
  await expect.poll(() => state(page)).toMatchObject({ studies: ['rsi'], folded: [false, true], drawings: 1, type: 'line' });
  await paint(page);
  await page.screenshot({ path: info.outputPath('history-all-redone.png') });
  expect(await page.evaluate(() => (window as any).__lastOrder)).toBeUndefined();
  expect(errors).toEqual([]);
});

test('the rail buttons follow a study step, and a settings session is one step that Cancel leaves out', async ({ page }, info) => {
  const errors = await mount(page);
  const undo = page.locator('.oac-rail .oac-rail__btn[aria-label^="Undo"]');
  const redo = page.locator('.oac-rail .oac-rail__btn[aria-label^="Redo"]');
  await expect(undo).toHaveAttribute('aria-disabled', 'true');
  await page.evaluate(() => (window as any).__widget.chart.addIndicator('rsi'));
  await expect(undo).toHaveAttribute('aria-disabled', 'false');
  await undo.click();
  await expect.poll(() => state(page).then(s => s.studies)).toEqual([]);
  await expect(redo).toHaveAttribute('aria-disabled', 'false');
  await redo.click();
  await expect.poll(() => state(page).then(s => s.studies)).toEqual(['rsi']);

  const grid = () => page.evaluate(() => (window as any).__widget.chart.gridOptions().vertLines);
  const before = await grid();
  await page.locator('.oac-topbar button[aria-label="Chart settings"]').click();
  await page.locator('.oac-settings [role="tab"][data-tab="appearance"]').click();
  await page.locator('#oac-cset-canvas-grid-vertLines').click({ force: true });
  expect(await grid()).toBe(!before);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(await grid()).toBe(before);
  expect(await page.evaluate(() => (window as any).__widget.history.peekUndo()?.changes)).toEqual(['study-add']);

  await page.locator('.oac-topbar button[aria-label="Chart settings"]').click();
  await page.locator('.oac-settings [role="tab"][data-tab="appearance"]').click();
  await page.locator('#oac-cset-canvas-grid-vertLines').click({ force: true });
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  expect(await grid()).toBe(!before);
  await undo.click();
  expect(await grid()).toBe(before);
  await expect.poll(() => state(page).then(s => s.studies)).toEqual(['rsi']);
  await paint(page);
  await page.screenshot({ path: info.outputPath('history-rail.png') });
  expect(errors).toEqual([]);
});

test('the mobile sheet walks the same timeline on a narrow screen', async ({ page }, info) => {
  const errors = await mount(page, 'widget-mobile-fixture.html', 390, 740);
  await page.evaluate(() => (window as any).__widget.chart.addIndicator('rsi'));
  await page.locator('[data-mobile-action="more"]').click();
  const sheet = page.locator('.oac-mobile-sheet');
  await expect(sheet.locator('[data-mobile-action="undo"]')).toHaveAttribute('aria-disabled', 'false');
  await expect(sheet.locator('[data-mobile-action="redo"]')).toHaveAttribute('aria-disabled', 'true');
  await sheet.locator('[data-mobile-action="undo"]').click();
  await expect.poll(() => state(page).then(s => s.studies)).toEqual([]);
  await expect(sheet.locator('[data-mobile-action="undo"]')).toHaveAttribute('aria-disabled', 'true');
  await sheet.locator('[data-mobile-action="redo"]').click();
  await expect.poll(() => state(page).then(s => s.studies)).toEqual(['rsi']);
  const box = await sheet.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  await page.screenshot({ path: info.outputPath('history-mobile.png') });
  expect(errors).toEqual([]);
});

/** Lit pixels across every canvas of one pane: a drawing may paint over or under the series. */
const inkAll = (page: Page, pane: number) => page.evaluate(index => {
  const element = (window as any).__widget.chart.panes()[index]?.element as HTMLElement | undefined;
  let lit = 0;
  for (const canvas of [...(element?.querySelectorAll('canvas') ?? [])] as HTMLCanvasElement[]) {
    if (canvas.width === 0 || canvas.height === 0) continue;
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 128 && (data[i] > 60 || data[i + 1] > 60 || data[i + 2] > 70)) lit++;
  }
  return lit;
}, pane);

test('a pane left with only a drawing comes back painted, and a drawing the host makes in ignore survives every press', async ({ page }, info) => {
  const errors = await mount(page);
  // Two study panes, a line on the first, then its study moved away: the pane holds only the line.
  const line = await page.evaluate(() => {
    const w = (window as any).__widget;
    const rsi = w.chart.addIndicator('rsi');
    w.chart.addIndicator('cci');
    const bars = w.series.getData();
    const made = w.draw.add({ tool: 'horizontal-line', paneIndex: 1, points: [{ time: bars[bars.length - 20].time, price: 50 }], style: { color: '#ffcc00', lineWidth: 3 } });
    w.chart.moveIndicator(rsi.id, 2);
    return made.id;
  });
  await expect.poll(() => state(page).then(s => s.panes)).toBe(3);
  await page.evaluate(() => (window as any).__widget.history.clear());
  await paint(page);
  const held = await inkAll(page, 1);
  expect(held).toBeGreaterThan(300);

  await page.evaluate(() => (window as any).__widget.chart.removePane(1));
  await expect.poll(() => state(page).then(s => s.panes)).toBe(2);
  expect(await page.evaluate(() => (window as any).__widget.history.peekUndo()?.changes)).toEqual(['pane-remove']);
  const price = (await paneBoxes(page))[0];
  await page.mouse.move(price.x + price.width * 0.5, price.y + price.height * 0.5);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page).then(s => s.panes)).toBe(3);
  expect(await page.evaluate(id => (window as any).__widget.draw.get(id)?.paneIndex, line)).toBe(1);
  await paint(page);
  await expect.poll(() => inkAll(page, 1)).toBeGreaterThan(held * 0.8);
  await page.screenshot({ path: info.outputPath('history-pane-back.png') });

  // The host's own line, drawn inside ignore: no step, and no press takes it back.
  const host = await page.evaluate(() => {
    const w = (window as any).__widget;
    const bars = w.series.getData();
    return w.history.ignore(() => w.draw.add({ tool: 'horizontal-line', paneIndex: 0, points: [{ time: bars[bars.length - 30].time, price: bars[bars.length - 30].close }], style: { color: '#00e5ff' } })).id;
  });
  await page.keyboard.press('ControlOrMeta+y');
  await expect.poll(() => state(page).then(s => s.panes)).toBe(2);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => state(page).then(s => s.panes)).toBe(3);
  expect(await page.evaluate(id => (window as any).__widget.draw.get(id) !== undefined, host)).toBe(true);
  expect(await page.evaluate(() => (window as any).__widget.history.canUndo())).toBe(false);
  await paint(page);
  await page.screenshot({ path: info.outputPath('history-host-line.png') });
  expect(errors).toEqual([]);
});
