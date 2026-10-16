import { test, expect, type Page } from '@playwright/test';
import { VERSION } from '../../src/version';

// The chart grid in a real browser: layout, measured charts, splitters,
// keyboard routing, the compact view, all-or-nothing workspace import, the
// bars over and under the charts, saved desks and the desk kept in IndexedDB.
async function mount(page: Page, preset = '2x2', size = { width: 1200, height: 800 }, extra = ''): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize(size);
  await page.goto(`/tests/e2e/widget-grid-fixture.html?preset=${preset}${extra}`);
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
  return errors;
}
const counts = (page: Page): Promise<number[]> => page.evaluate(() => (window as any).fixture.counts());
const ranges = (page: Page): Promise<Array<{ from: number; to: number }>> => page.evaluate(() => (window as any).fixture.ranges());
/**
 * True once a chart has drawn candles, not just its background, grid and
 * axes: those are grey, and the candles are the only saturated pixels.
 */
const painted = (page: Page, index: number): Promise<boolean> => page.evaluate(i => {
  const canvases = [...document.querySelectorAll('.oac-grid__cell')[i].querySelectorAll('.oac-chart canvas')] as HTMLCanvasElement[];
  let saturated = 0;
  for (const canvas of canvases) {
    if (canvas.width === 0 || canvas.height === 0) continue;
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
    for (let p = 0; p < data.length; p += 4) {
      if (data[p + 3] > 128 && Math.max(data[p], data[p + 1], data[p + 2]) - Math.min(data[p], data[p + 1], data[p + 2]) > 60) saturated++;
    }
  }
  return saturated > 500;
}, index);
const activeIndex = (page: Page): Promise<number> => page.evaluate(() => {
  const grid = (window as any).fixture.grid;
  return grid.cells().findIndex((cell: any) => cell.id === grid.active().id);
});

test('a two by two grid lays out four measured charts that load on their own', async ({ page }, info) => {
  const errors = await mount(page);
  const cells = page.locator('.oac-grid__cell');
  await expect(cells).toHaveCount(4);
  const boxes = await Promise.all([0, 1, 2, 3].map(i => cells.nth(i).boundingBox()));
  expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x);
  expect(boxes[0]!.y).toBeLessThan(boxes[2]!.y);
  for (const box of boxes) {
    expect(box!.width).toBeGreaterThan(500);
    expect(box!.height).toBeGreaterThan(300);
  }
  await page.evaluate(() => {
    const grid = (window as any).fixture.grid;
    grid.cells().forEach((cell: any, i: number) => cell.widget.setSymbol(['AAA', 'BBB', 'CCC', 'DDD'][i]));
  });
  await expect(page.locator('.oac-data-status').first()).toContainText('Loading');
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120, 120, 120]);
  const plots = await page.locator('.oac-grid__cell .oac-chart').evaluateAll(els => els.map(el => [el.clientWidth, el.clientHeight]));
  for (const [width, height] of plots) {
    expect(width).toBeGreaterThan(400);
    expect(height).toBeGreaterThan(200);
  }
  await page.screenshot({ path: info.outputPath('grid-2x2.png') });
  expect(errors).toEqual([]);
});

test('the active chart shows its outline and takes the keyboard while another is hovered', async ({ page }, info) => {
  const errors = await mount(page, '1x2');
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120]);
  const charts = page.locator('.oac-grid__cell .oac-chart');
  await charts.nth(1).click();
  expect(await activeIndex(page)).toBe(1);
  const outline = await page.locator('.oac-grid__cell').nth(1).evaluate(el => getComputedStyle(el, '::after').borderTopColor);
  expect(outline).not.toBe('rgba(0, 0, 0, 0)');
  await charts.nth(0).hover();
  const before = await ranges(page);
  await page.keyboard.press('ArrowLeft');
  const after = await ranges(page);
  expect(after[0]).toEqual(before[0]);
  expect(after[1]).not.toEqual(before[1]);
  await charts.nth(0).click();
  expect(await activeIndex(page)).toBe(0);
  await page.screenshot({ path: info.outputPath('grid-active.png') });
  expect(errors).toEqual([]);
});

test('splitters resize by drag and by keyboard, and a double click evens them', async ({ page }, info) => {
  const errors = await mount(page, '1x2');
  await page.evaluate(() => (window as any).fixture.readyAll());
  const split = page.locator('.oac-grid__split');
  await expect(split).toHaveCount(1);
  await expect(split).toHaveAttribute('aria-valuenow', '50');
  const first = page.locator('.oac-grid__cell').first();
  const start = (await first.boundingBox())!;
  const box = (await split.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 200, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  const wider = (await first.boundingBox())!;
  expect(wider.width).toBeGreaterThan(start.width + 150);
  await expect.poll(() => first.locator('.oac-chart').evaluate(el => el.clientWidth)).toBeGreaterThan(start.width + 100);
  const value = Number(await split.getAttribute('aria-valuenow'));
  await split.focus();
  await page.keyboard.press('ArrowLeft');
  expect(Number(await split.getAttribute('aria-valuenow'))).toBeLessThan(value);
  await split.dblclick();
  await expect(split).toHaveAttribute('aria-valuenow', '50');
  await page.screenshot({ path: info.outputPath('grid-split.png') });
  expect(errors).toEqual([]);
});

test('a narrow grid shows the active chart alone with tabs, and widening restores the grid', async ({ page }, info) => {
  const errors = await mount(page, '2x2', { width: 480, height: 720 });
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120, 120, 120]);
  const tabs = page.locator('.oac-grid__tab');
  await expect(tabs).toHaveCount(4);
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(1);
  const only = (await page.locator('.oac-grid__cell:visible').boundingBox())!;
  expect(only.width).toBeGreaterThan(460);
  // Linked viewports reach the charts hidden behind the tabs as well.
  await page.evaluate(() => {
    const grid = (window as any).fixture.grid;
    grid.setLinks({ viewport: true });
    grid.cells()[0].widget.chart.setVisibleLogicalRange({ from: 30, to: 60 });
  });
  await tabs.nth(2).click();
  expect(await activeIndex(page)).toBe(2);
  await expect(page.locator('.oac-grid__cell').nth(2)).toBeVisible();
  await expect(page.locator('.oac-grid__split:visible')).toHaveCount(0);
  await expect.poll(() => painted(page, 2)).toBe(true);
  const near = (range: { from: number; to: number }): boolean => Math.abs(range.from - 30) < 0.01 && Math.abs(range.to - 60) < 0.01;
  await expect.poll(async () => near((await ranges(page))[2])).toBe(true);
  await page.screenshot({ path: info.outputPath('grid-compact.png') });
  await page.setViewportSize({ width: 1200, height: 800 });
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(4);
  await expect(page.locator('.oac-grid__tabs')).toBeHidden();
  await expect.poll(async () => (await ranges(page)).every(near)).toBe(true);
  for (const index of [0, 1, 2, 3]) await expect.poll(() => painted(page, index)).toBe(true);
  await page.screenshot({ path: info.outputPath('grid-widened.png') });
  expect(errors).toEqual([]);
});

test('linked charts on the right edge keep following new bars through a splitter drag', async ({ page }, info) => {
  const errors = await mount(page, '1x2');
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120]);
  /** Append bar `n` to both charts, the way a live feed does. */
  const append = (n: number): Promise<void> => page.evaluate(i => {
    const { grid, bars } = (window as any).fixture;
    for (const cell of grid.cells()) cell.widget.series.update(bars(i + 1, 165)[i]);
  }, n);
  await page.evaluate(() => {
    const grid = (window as any).fixture.grid;
    grid.setLinks({ viewport: true });
    grid.cells()[0].widget.chart.setVisibleLogicalRange({ from: 80, to: 123 });
  });
  for (let n = 120; n < 130; n++) await append(n);
  const before = await ranges(page);
  expect(before[0].to).toBeCloseTo(133, 6);
  expect(before[1].to).toBeCloseTo(133, 6);
  const split = page.locator('.oac-grid__split');
  const box = (await split.boundingBox())!;
  const width = await page.locator('.oac-grid__cell .oac-chart').first().evaluate(el => el.clientWidth);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 200, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => page.locator('.oac-grid__cell .oac-chart').first().evaluate(el => el.clientWidth)).toBeGreaterThan(width + 150);
  // Both charts were resized and both still show the same window, up to the newest bar.
  await expect.poll(async () => (await ranges(page)).map(range => [Math.round(range.from * 1e4) / 1e4, Math.round(range.to * 1e4) / 1e4]))
    .toEqual([[90, 133], [90, 133]]);
  await append(130);
  const after = await ranges(page);
  expect(after[0].to).toBeCloseTo(134, 6);
  expect(after[1].to).toBeCloseTo(134, 6);
  await page.screenshot({ path: info.outputPath('grid-live-split.png') });
  expect(errors).toEqual([]);
});

test('importing a workspace replaces every chart at once, and a failed import changes nothing', async ({ page }, info) => {
  const errors = await mount(page, '1x2');
  await page.evaluate(() => (window as any).fixture.readyAll());
  const outcome = await page.evaluate(() => {
    const grid = (window as any).fixture.grid;
    const before = grid.cells().map((cell: any) => cell.widget);
    const broken = grid.getWorkspace();
    broken.panes[1].chart.version = 99;
    const failed = grid.applyWorkspace(broken);
    const kept = grid.cells().every((cell: any, i: number) => cell.widget === before[i] && !cell.widget.isDestroyed);
    const next = grid.getWorkspace();
    const pane = next.panes[0];
    next.panes = ['w', 'x', 'y'].map((id, i) => ({ ...pane, id, symbol: ['EEE', 'FFF', 'GGG'][i] }));
    next.layout = { rows: 2, columns: 2, rowWeights: [1.5, 1], columnWeights: [1, 1], slots: [
      { paneId: 'w', row: 0, column: 0, rowSpan: 1, columnSpan: 2 },
      { paneId: 'x', row: 1, column: 0, rowSpan: 1, columnSpan: 1 },
      { paneId: 'y', row: 1, column: 1, rowSpan: 1, columnSpan: 1 },
    ] };
    next.activePaneId = 'y';
    const applied = grid.applyWorkspace(next);
    return { failed, kept, applied, destroyed: before.every((widget: any) => widget.isDestroyed) };
  });
  expect(outcome.failed.applied).toBe(false);
  expect(outcome.kept).toBe(true);
  expect(outcome.applied).toEqual({ applied: true });
  expect(outcome.destroyed).toBe(true);
  await expect(page.locator('.oac-widget')).toHaveCount(3);
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120, 120]);
  const wide = (await page.locator('.oac-grid__cell').nth(0).boundingBox())!;
  const low = (await page.locator('.oac-grid__cell').nth(1).boundingBox())!;
  expect(wide.width).toBeGreaterThan(low.width * 1.8);
  expect(wide.height).toBeGreaterThan(low.height * 1.3);
  await expect(page.locator('.oac-grid__split')).toHaveCount(2);
  expect(await activeIndex(page)).toBe(2);
  await page.screenshot({ path: info.outputPath('grid-imported.png') });
  expect(errors).toEqual([]);
});

test('a linked appearance change is a step of the chart it was made on, and undoing it there takes it back on both', async ({ page }, info) => {
  // Stacked, so each chart's top bar has the whole width and every control on it is reachable.
  const errors = await mount(page, '2x1', { width: 1200, height: 900 });
  await page.evaluate(() => (window as any).fixture.readyAll());
  await expect.poll(() => counts(page)).toEqual([120, 120]);
  await page.evaluate(() => (window as any).fixture.grid.setLinks({ appearance: true }));
  const vertical = (): Promise<boolean[]> => page.evaluate(() => (window as any).fixture.grid.cells().map((cell: any) => cell.widget.chart.gridOptions().vertLines));
  const canUndo = (): Promise<boolean[]> => page.evaluate(() => (window as any).fixture.grid.cells().map((cell: any) => cell.widget.history.canUndo()));
  const start = await vertical();
  expect(start[0]).toBe(start[1]);
  const cells = page.locator('.oac-grid__cell');
  const charts = page.locator('.oac-grid__cell .oac-chart');

  // The first chart's settings dialog; the second chart follows the link.
  await charts.nth(0).click();
  await cells.nth(0).locator('.oac-topbar button[aria-label="Chart settings"]').click();
  await page.locator('.oac-settings [role="tab"][data-tab="appearance"]').click();
  await page.locator('#oac-cset-canvas-grid-vertLines').click({ force: true });
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  await expect.poll(vertical).toEqual([!start[0], !start[0]]);
  expect(await canUndo()).toEqual([true, false]);

  // The second chart's own step, walked back with its own chord, leaves the linked grid alone.
  await page.evaluate(() => (window as any).fixture.grid.cells()[1].widget.chart.addIndicator('rsi'));
  await charts.nth(1).click();
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => page.evaluate(() => (window as any).fixture.grid.cells()[1].widget.chart.indicators().length)).toBe(0);
  expect(await vertical()).toEqual([!start[0], !start[0]]);
  await page.screenshot({ path: info.outputPath('grid-linked-follower-undone.png') });

  // The first chart's undo takes the linked change back on both, and its redo applies it to both.
  await charts.nth(0).click();
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(vertical).toEqual(start);
  await page.screenshot({ path: info.outputPath('grid-linked-undone.png') });
  await page.keyboard.press('ControlOrMeta+y');
  await expect.poll(vertical).toEqual([!start[0], !start[0]]);
  await page.screenshot({ path: info.outputPath('grid-linked-redone.png') });
  expect(errors).toEqual([]);
});

// 2.5.10: the grid bar, layouts to sixteen charts, cell moves, link groups and capture.

/** Answer every request until each chart holds its bars: charts built late ask late. */
async function readyEvery(page: Page, bars = 120): Promise<void> {
  await expect.poll(async () => {
    await page.evaluate(() => (window as any).fixture.readyAll());
    return (await counts(page)).every(n => n === bars);
  }, { timeout: 15_000 }).toBe(true);
}
const symbols = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).fixture.grid.cells().map((c: any) => c.widget.symbol()));
const setSymbols = (page: Page, names: string[]): Promise<void> => page.evaluate(list => {
  (window as any).fixture.grid.cells().forEach((c: any, i: number) => c.widget.setSymbol(list[i]));
}, names);

test('the grid bar lays out four by four and an uneven layout from the picker, by pointer and by keyboard', async ({ page }, info) => {
  const errors = await mount(page, '2x2', { width: 1360, height: 900 }, '&toolbar=1');
  await readyEvery(page);
  await page.locator('.oac-grid__layout').click();
  const picker = page.getByRole('menu', { name: 'Arrange charts' });
  await expect(picker).toBeVisible();
  await expect(picker.getByRole('menuitemradio')).toHaveCount(26);
  await expect(picker.getByRole('menuitemradio', { name: 'Two by two' })).toHaveAttribute('aria-checked', 'true');
  await page.screenshot({ path: info.outputPath('grid-picker.png') });
  await picker.getByRole('menuitemradio', { name: 'Four by four' }).click();
  await expect(picker).toBeHidden();
  await expect(page.locator('.oac-grid__cell')).toHaveCount(16);
  await readyEvery(page);
  const body = (await page.locator('.oac-grid__cells').boundingBox())!;
  const boxes = await page.locator('.oac-grid__cell').evaluateAll(els => els.map(el => el.getBoundingClientRect().toJSON()));
  for (const box of boxes) {
    expect(Math.abs(box.width - (body.width - 12) / 4)).toBeLessThan(2);
    expect(Math.abs(box.height - (body.height - 12) / 4)).toBeLessThan(2);
  }
  // Sixteen cells are dense: one row of chart controls, the rest of the cell is the chart.
  expect(await page.locator('.oac-grid__cell[data-dense="true"]').count()).toBe(16);
  // A dense chart's type button shows its glyph alone, as its other buttons do.
  const type = page.locator('.oac-grid__cell').nth(0).locator('.oac-topbar__type');
  await expect(type.locator('.oac-glyph')).toBeVisible();
  await expect(type.locator(':scope > span:not(.oac-glyph):not(.oac-chev)')).toBeHidden();
  // A host's chart type has no glyph (the top bar hides the empty one), so it keeps its name.
  await type.locator('.oac-glyph').evaluate(el => { (el as HTMLElement).hidden = true; });
  await expect(type.locator(':scope > span:not(.oac-glyph):not(.oac-chev)')).toBeVisible();
  await type.locator('.oac-glyph').evaluate(el => { (el as HTMLElement).hidden = false; });
  const plots = await page.locator('.oac-grid__cell .oac-chart').evaluateAll(els => els.map(el => el.clientHeight));
  for (const height of plots) expect(height).toBeGreaterThan(body.height / 4 - 90);
  for (const index of [0, 5, 15]) await expect.poll(() => painted(page, index)).toBe(true);
  await page.screenshot({ path: info.outputPath('grid-4x4.png') });

  // The keyboard: the checked tile has the focus, the arrows walk the rows.
  await page.locator('.oac-grid__layout').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.oac-grid__tile[data-layout="4x4"]')).toBeFocused();
  for (const key of ['ArrowUp', 'ArrowUp', 'ArrowUp', 'ArrowRight', 'ArrowRight']) await page.keyboard.press(key);
  await expect(page.locator('.oac-grid__tile[data-layout="corner-7"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(8);
  await readyEvery(page);
  const large = (await page.locator('.oac-grid__cell').nth(0).boundingBox())!;
  const small = (await page.locator('.oac-grid__cell').nth(1).boundingBox())!;
  expect(large.width).toBeGreaterThan(small.width * 2.8);
  expect(large.height).toBeGreaterThan(small.height * 2.8);
  await expect(page.locator('.oac-grid__layout .oac-grid__bar-text')).toHaveText('Large corner, seven around');
  await page.screenshot({ path: info.outputPath('grid-corner-7.png') });
  expect(errors).toEqual([]);
});

test('a chart maximizes from the bar, a double click on its bar and Alt+Enter, and a drag on its bar swaps it', async ({ page }, info) => {
  const errors = await mount(page, '2x2', { width: 1360, height: 900 }, '&toolbar=1');
  await setSymbols(page, ['AAA', 'BBB', 'CCC', 'DDD']);
  await readyEvery(page);
  const cells = page.locator('.oac-grid__cell');
  await cells.nth(1).locator('.oac-chart').click();
  await page.locator('.oac-grid__max').click();
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(1);
  await expect(cells.nth(1)).toBeVisible();
  await expect(page.locator('.oac-grid__tab')).toHaveCount(4);
  await expect(page.locator('.oac-grid__max')).toHaveAttribute('aria-label', 'Restore the grid');
  await expect.poll(() => cells.nth(1).locator('.oac-chart').evaluate(el => el.clientWidth)).toBeGreaterThan(1200);
  await expect.poll(() => painted(page, 1)).toBe(true);
  await page.screenshot({ path: info.outputPath('grid-maximized.png') });
  await page.locator('.oac-grid__max').click();
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(4);

  // A double click on the bar's background, then Alt+Enter on the chart the pointer rests on.
  // Mid-height on the bar's own padding: its top few pixels are the row splitter's grab zone.
  const head = (await cells.nth(2).locator('.oac-topbar').boundingBox())!;
  await page.mouse.dblclick(head.x + 3, head.y + head.height / 2);
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(1);
  expect(await activeIndex(page)).toBe(2);
  await page.mouse.move(head.x + 300, head.y + 300);
  await page.keyboard.press('Alt+Enter');
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(4);

  // Drag the first chart by its bar onto the last chart's place.
  const from = (await cells.nth(0).locator('.oac-topbar').boundingBox())!;
  const to = (await cells.nth(3).boundingBox())!;
  await page.mouse.move(from.x + 3, from.y + 3);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 8 });
  await expect(cells.nth(3)).toHaveAttribute('data-drop', 'true');
  await page.screenshot({ path: info.outputPath('grid-drag.png') });
  await page.mouse.up();
  await expect.poll(() => symbols(page)).toEqual(['DDD', 'BBB', 'CCC', 'AAA']);
  await expect(page.locator('.oac-grid__cell[data-drop]')).toHaveCount(0);
  // The page order follows the places, so Tab and a screen reader read the charts as they stand.
  const inPage = (): Promise<string[]> => page.locator('.oac-grid__cell').evaluateAll(els => els.map(el => (el as HTMLElement).dataset.paneId!));
  expect(await inPage()).toEqual(await page.evaluate(() => (window as any).fixture.grid.cells().map((c: any) => c.id)));
  // The keyboard swaps too: the moved chart is active and trades places with its left neighbour,
  // keeping the focus, so a second chord moves it again.
  await page.locator('.oac-grid__cell').nth(3).locator('.oac-chart').click();
  await page.keyboard.press('ControlOrMeta+Shift+ArrowLeft');
  await expect.poll(() => symbols(page)).toEqual(['DDD', 'BBB', 'AAA', 'CCC']);
  expect(await page.evaluate(() => (document.activeElement as HTMLElement).closest('.oac-grid__cell')?.getAttribute('aria-label'))).toBe('Chart 3');
  await page.keyboard.press('ControlOrMeta+Shift+ArrowUp');
  await expect.poll(() => symbols(page)).toEqual(['AAA', 'BBB', 'DDD', 'CCC']);
  expect(await inPage()).toEqual(await page.evaluate(() => (window as any).fixture.grid.cells().map((c: any) => c.id)));
  await page.screenshot({ path: info.outputPath('grid-swapped.png') });
  expect(errors).toEqual([]);
});

test('link groups: a drawing reaches its group partner and not another group, and the chart type follows', async ({ page }, info) => {
  const errors = await mount(page, '1x3', { width: 1500, height: 820 }, '&toolbar=1');
  await readyEvery(page);
  const cells = page.locator('.oac-grid__cell');
  // The third chart starts a group of its own from the link menu.
  await cells.nth(2).locator('.oac-chart').click();
  await page.locator('.oac-grid__link').click();
  const menu = page.getByRole('menu', { name: 'Linking' });
  await menu.getByRole('menuitem', { name: 'New group' }).click();
  await expect(menu.getByRole('menuitemradio', { name: /Group B/ })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape');
  // The first chart's group links drawings and the chart type.
  await cells.nth(0).locator('.oac-chart').click();
  await page.locator('.oac-grid__link').click();
  await menu.getByRole('menuitemcheckbox', { name: 'Drawings' }).click();
  await menu.getByRole('menuitemcheckbox', { name: 'Chart type' }).click();
  await expect(menu.getByRole('menuitemcheckbox', { name: 'Drawings' })).toHaveAttribute('aria-checked', 'true');
  await page.screenshot({ path: info.outputPath('grid-link-menu.png') });
  await page.keyboard.press('Escape');
  await expect(page.locator('.oac-grid__mark')).toHaveText(['A', 'A', 'B']);

  const lines = (): Promise<number[]> => page.evaluate(() => (window as any).fixture.grid.cells()
    .map((c: any) => c.widget.draw.drawings().filter((d: any) => d.tool === 'trend-line').length));
  // A trend line from the swing low to the highest high after it, on the first chart's own bars.
  await page.evaluate(() => {
    const cell = (window as any).fixture.grid.cells()[0];
    const bars = cell.widget.series.getData();
    const low = bars.reduce((a: any, b: any) => (b.low < a.low ? b : a));
    const high = bars.filter((b: any) => b.time > low.time).reduce((a: any, b: any) => (b.high > a.high ? b : a), { high: -Infinity });
    cell.widget.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: low.time, price: low.low }, { time: high.time, price: high.high }] });
  });
  await expect.poll(lines).toEqual([1, 1, 0]);
  await cells.nth(0).locator('.oac-topbar__type').click();
  await cells.nth(0).getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).fixture.grid.cells().map((c: any) => c.widget.chartType())))
    .toEqual(['line', 'line', 'candlestick']);
  await page.screenshot({ path: info.outputPath('grid-link-groups.png') });
  await page.evaluate(() => (window as any).fixture.grid.setTheme('light'));
  await page.screenshot({ path: info.outputPath('grid-link-groups-light.png') });
  const saved = await page.evaluate(() => (window as any).fixture.grid.getWorkspace());
  expect(saved.sync.groups.map((g: any) => [g.id, g.drawings === true, g.chartType === true])).toEqual([['a', true, true], ['b', false, false]]);
  expect(saved.panes.map((p: any) => p.linkGroup)).toEqual(['a', 'a', 'b']);
  expect(errors).toEqual([]);
});

test('one PNG of the whole grid puts each chart own pixels at its place, from the bar or from a chart', async ({ page }, info) => {
  const errors = await mount(page, '1x2', { width: 1200, height: 700 }, '&toolbar=1');
  await setSymbols(page, ['AAA', 'MMM']);
  await readyEvery(page);
  for (const index of [0, 1]) await expect.poll(() => painted(page, index)).toBe(true);
  const result = await page.evaluate(() => {
    const grid = (window as any).fixture.grid;
    const out: HTMLCanvasElement = grid.takeScreenshot();
    const body = document.querySelector('.oac-grid__cells')!.getBoundingClientRect();
    const ratio = window.devicePixelRatio;
    const block = (canvas: HTMLCanvasElement, x: number, y: number): number[] => {
      const { data } = canvas.getContext('2d')!.getImageData(Math.round(x), Math.round(y), 40, 40);
      const sum = [0, 0, 0];
      for (let p = 0; p < data.length; p += 4) { sum[0] += data[p]; sum[1] += data[p + 1]; sum[2] += data[p + 2]; }
      return sum.map(v => v / (data.length / 4));
    };
    const cells = grid.cells().map((cell: any) => {
      const chart = cell.widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
      const own: HTMLCanvasElement = cell.widget.chart.takeScreenshot();
      const x = chart.width * 0.4, y = chart.height * 0.4;
      return { grid: block(out, (chart.left - body.left + x) * ratio, (chart.top - body.top + y) * ratio), own: block(own, x * ratio, y * ratio) };
    });
    return { width: out.width, height: out.height, expected: [Math.round(body.width * ratio), Math.round(body.height * ratio)], cells };
  });
  expect([result.width, result.height]).toEqual(result.expected);
  for (const cell of result.cells) for (let c = 0; c < 3; c++) expect(Math.abs(cell.grid[c] - cell.own[c])).toBeLessThan(8);
  // The two charts show different instruments, so the check could tell them apart.
  expect(result.cells[0].own.some((v: number, c: number) => Math.abs(v - result.cells[1].own[c]) > 1)).toBe(true);

  await page.locator('.oac-grid__capture').click();
  const pending = page.waitForEvent('download');
  await page.getByRole('menuitem', { name: 'Download PNG of every chart' }).click();
  expect((await pending).suggestedFilename()).toMatch(/^charts-1x2-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}\.png$/);
  // The chart's own capture menu offers the same, next to its own picture.
  await page.locator('.oac-grid__cell').nth(1).locator('.oac-topbar button[aria-label="Capture chart"]').click();
  await expect(page.locator('.oac-grid__cell').nth(1).locator('.oac-menu .oac-head')).toHaveText('Every chart');
  const second = page.waitForEvent('download');
  await page.locator('.oac-grid__cell').nth(1).getByRole('menuitem', { name: 'Download PNG of every chart' }).click();
  expect((await second).suggestedFilename()).toMatch(/^charts-1x2-/);
  // And the chart's own picture, which the menu calls saved once the browser has taken it.
  await page.evaluate(() => {
    const w = window as any;
    w.statuses = [];
    w.fixture.grid.cells()[1].widget.on('status', (e: { kind: string; text: string }) => w.statuses.push(`${e.kind} ${e.text}`));
  });
  await page.locator('.oac-grid__cell').nth(1).locator('.oac-topbar button[aria-label="Capture chart"]').click();
  const own = page.waitForEvent('download');
  // The menu opens on this row; Enter takes it, while the button's tip still shows over it.
  await expect(page.locator('.oac-grid__cell').nth(1).getByRole('menuitem', { name: 'Download PNG', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  expect((await own).suggestedFilename()).toMatch(/-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}\.png$/);
  await expect.poll(() => page.evaluate(() => (window as any).statuses)).toEqual(['info Saved a PNG of the chart']);
  await page.screenshot({ path: info.outputPath('grid-capture.png') });
  expect(errors).toEqual([]);
});

test('at phone width the bar stays usable: menus fit, maximize and capture say why they wait', async ({ page }, info) => {
  const errors = await mount(page, '2x2', { width: 400, height: 780 }, '&toolbar=1&theme=light');
  await readyEvery(page);
  await expect(page.locator('.oac-grid__bar')).toBeVisible();
  await expect(page.locator('.oac-grid__tab')).toHaveCount(4);
  await expect(page.locator('.oac-grid__max')).toHaveAttribute('aria-disabled', 'true');
  await page.locator('.oac-grid__layout').click();
  const picker = (await page.getByRole('menu', { name: 'Arrange charts' }).boundingBox())!;
  expect(picker.x).toBeGreaterThanOrEqual(0);
  expect(picker.x + picker.width).toBeLessThanOrEqual(400);
  await page.screenshot({ path: info.outputPath('grid-phone-picker.png') });
  await page.keyboard.press('Escape');
  await page.locator('.oac-grid__capture').click();
  const download = page.getByRole('menuitem', { name: 'Download PNG of every chart' });
  await expect(download).toHaveAttribute('aria-disabled', 'true');
  // The reason is said once, names the width rather than a step the user cannot take, and is tied to the row.
  await expect(download).toHaveAccessibleDescription('The grid shows one chart at a time at this width');
  const menuBox = (await page.getByRole('menu', { name: 'Capture every chart' }).boundingBox())!;
  expect(menuBox.x).toBeGreaterThanOrEqual(0);
  expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(400);
  // Each label shows whole: nothing beside it squeezes it to an ellipsis.
  for (const label of await page.locator('.oac-grid__menu .oac-menu__label').all()) {
    expect(await label.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  }
  await page.screenshot({ path: info.outputPath('grid-phone-capture.png') });
  expect(errors).toEqual([]);
});

test('one bar under the grid acts on the active chart, and its Go to opens over the grid', async ({ page }, info) => {
  for (const theme of ['dark', 'light']) {
    const errors = await mount(page, '2x2', { width: 1360, height: 900 }, `&toolbar=1&bottombar=1&theme=${theme}`);
    await readyEvery(page);
    const bar = page.locator('.oac-grid__foot .oac-bottombar');
    await expect(page.locator('.oac-bottombar')).toHaveCount(1);
    // The charts leave Go to to the bar.
    await expect(page.locator('.oac-grid__cell .oac-topbar__goto')).toHaveCount(0);
    const barBox = (await bar.boundingBox())!;
    const cellsBox = (await page.locator('.oac-grid__cells').boundingBox())!;
    const topBox = (await page.locator('.oac-grid__bar').boundingBox())!;
    expect(topBox.y).toBe(0);
    expect(Math.abs(barBox.y - (cellsBox.y + cellsBox.height))).toBeLessThanOrEqual(1);
    expect(barBox.y + barBox.height).toBeCloseTo(900, 0);
    expect(barBox.height).toBe(28);
    // A press on the second chart makes it the one the bar acts on.
    const second = (await page.locator('.oac-grid__cell').nth(1).locator('.oac-chart').boundingBox())!;
    await page.mouse.click(second.x + second.width / 2, second.y + second.height / 2);
    await expect.poll(() => activeIndex(page)).toBe(1);
    await bar.locator('.oac-bottombar__icon[data-scale="log"]').click();
    expect(await page.evaluate(() => (window as any).fixture.grid.cells().map((c: any) => c.widget.chart.priceAxisState(c.widget.chart.primaryPaneIndex(), 'right').mode)))
      .toEqual(['linear', 'logarithmic', 'linear', 'linear']);
    await expect(bar.locator('.oac-bottombar__icon[data-scale="log"]')).toHaveAttribute('aria-pressed', 'true');
    // Go to opens over the grid, above its own button, and gives the focus back to it.
    const goTo = bar.locator('.oac-bottombar__goto');
    await goTo.click();
    const panel = page.locator('.oac-grid__overlay .oac-goto');
    await expect(panel).toBeVisible();
    const box = (await panel.boundingBox())!;
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(barBox.y + 1);
    await page.screenshot({ path: info.outputPath(`grid-bottom-bar-${theme}.png`) });
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(goTo).toBeFocused();
    expect(errors).toEqual([]);
  }
});

test('the bar under a four by four grid opens Go to whole for a small chart, and fits a phone', async ({ page }, info) => {
  const errors = await mount(page, '4x4', { width: 1360, height: 900 }, '&toolbar=1&bottombar=1');
  await readyEvery(page);
  await page.locator('.oac-grid__cell').nth(5).locator('.oac-chart').click();
  await expect.poll(() => activeIndex(page)).toBe(5);
  await page.locator('.oac-bottombar__goto').click();
  const panel = page.locator('.oac-grid__overlay .oac-goto');
  await expect(panel).toBeVisible();
  // Taller than the chart it is for, and still whole.
  const cell = (await page.locator('.oac-grid__cell').nth(5).boundingBox())!;
  const box = (await panel.boundingBox())!;
  expect(box.height).toBeGreaterThan(cell.height);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(1360);
  await expect(panel.locator('[data-action="go-to"]')).toBeInViewport();
  await page.screenshot({ path: info.outputPath('grid-4x4-goto.png') });
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 780 });
  const bar = (await page.locator('.oac-bottombar').boundingBox())!;
  expect(bar.x + bar.width).toBeLessThanOrEqual(390);
  for (const control of ['.oac-bottombar__clock', '.oac-bottombar__icon[data-scale="percent"]']) {
    const b = (await page.locator(control).boundingBox())!;
    expect(b.x + b.width).toBeLessThanOrEqual(390);
  }
  await page.screenshot({ path: info.outputPath('grid-phone-bottom-bar.png') });
  expect(errors).toEqual([]);
});

test('the grid bar keeps the desk saved layouts: save, change, and the saved desk back after a reload', async ({ page }, info) => {
  const errors = await mount(page, '2x2', { width: 1360, height: 900 }, '&toolbar=1&bottombar=1&workspaces=1&persist=desk&theme=light');
  await page.evaluate(() => (window as any).fixture.grid.ready);
  await setSymbols(page, ['AAA', 'BBB', 'CCC', 'DDD']);
  await readyEvery(page);
  await expect(page.locator('.oac-grid__cell .oac-topbar__layouts')).toHaveCount(0);
  const control = page.locator('.oac-grid__bar .oac-grid__saved');
  await expect(control).toHaveText('Layouts');
  await control.click();
  const menu = page.locator('.oac-grid__overlay .oac-layouts');
  await expect(menu).toBeVisible();
  const box = (await menu.boundingBox())!;
  const at = (await control.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(at.y + at.height);
  expect(box.x + box.width).toBeLessThanOrEqual(1360);
  await menu.locator('[data-action="save-as"]').click();
  await menu.locator('.oac-layouts__input').fill('Morning desk');
  await menu.locator('[data-action="submit-name"]').click();
  await expect(control).toHaveText('Morning desk');
  await page.screenshot({ path: info.outputPath('grid-layouts-menu.png') });
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  // A change to the desk is unsaved (autosave is off), and the mark says so.
  await page.evaluate(() => (window as any).fixture.grid.setPreset('1x1'));
  await expect(control).toHaveAttribute('data-attention', 'true');
  await expect(control).toHaveAccessibleName('Layouts: Morning desk, Unsaved changes');
  // Escape handed focus back to the control, so focus goes elsewhere first:
  // only a fresh focus raises its tip, which is what rewrote the name.
  await page.locator('.oac-grid__layout').focus();
  await control.focus();
  await expect(page.locator('.oac-tip.is-on')).toBeVisible();
  await expect(control).toHaveAccessibleName('Layouts: Morning desk, Unsaved changes');
  // The grid's own desk comes back as the one chart, and then the layout that was active opens over it.
  await page.reload();
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
  await expect.poll(async () => { await page.evaluate(() => (window as any).fixture.readyAll()); return symbols(page); }, { timeout: 15_000 })
    .toEqual(['AAA', 'BBB', 'CCC', 'DDD']);
  await expect(page.locator('.oac-grid__saved')).toHaveText('Morning desk');
  await readyEvery(page);
  await page.screenshot({ path: info.outputPath('grid-layouts-reopened.png') });
  // At phone width the control keeps its glyph, rather than a name cut to a letter or two; the name stays in its tip and accessible name.
  await page.setViewportSize({ width: 390, height: 780 });
  await expect(page.locator('.oac-grid__saved .oac-grid__bar-text')).toBeHidden();
  await expect(page.locator('.oac-grid__saved')).toHaveAccessibleName('Layouts: Morning desk');
  const phone = (await page.locator('.oac-grid__saved').boundingBox())!;
  expect(phone.x + phone.width).toBeLessThanOrEqual(390);
  await page.locator('.oac-grid__bar').screenshot({ path: info.outputPath('grid-layouts-phone-bar.png') });
  expect(errors).toEqual([]);
});

test('a desk kept in localStorage, as 2.5.9 kept it, opens from IndexedDB and stays there', async ({ page }) => {
  const errors = await mount(page, '1x2', { width: 1200, height: 800 }, '&persist=legacy&storage=local');
  await setSymbols(page, ['AAA', 'BBB']);
  const second = await page.evaluate(() => (window as any).fixture.grid.cells()[1].id);
  await page.evaluate(id => (window as any).fixture.grid.setActive(id), second);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('oac-widget:legacy:grid') ?? '{}').activePaneId)).toBe(second);
  await page.evaluate(() => (window as any).fixture.grid.destroy());
  // The same page with the default store: the desk is copied in on this first visit.
  await mount(page, '2x2', { width: 1200, height: 800 }, '&persist=legacy');
  await page.evaluate(() => (window as any).fixture.grid.ready);
  expect(await symbols(page)).toEqual(['AAA', 'BBB']);
  expect(await activeIndex(page)).toBe(1);
  await setSymbols(page, ['EEE', 'BBB']);
  await page.reload();
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
  await page.evaluate(() => (window as any).fixture.grid.ready);
  expect(await symbols(page)).toEqual(['EEE', 'BBB']);
  // The copy 2.5.9 left stays as it was, for going back to it.
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('oac-widget:legacy:grid')!).panes.map((p: any) => p.symbol))).toEqual(['AAA', 'BBB']);
  expect(errors).toEqual([]);
});

test('the grid bar and its menus keep a strict style policy', async ({ page }) => {
  const NONCE = 'openalgo-grid-csp-test';
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    (window as any).__cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => (window as any).__cspViolations.push(event.effectiveDirective));
  });
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.route('**/widget-grid-csp-fixture.html', route => route.fulfill({
    contentType: 'text/html',
    headers: { 'Content-Security-Policy': `default-src 'self'; script-src 'self'; style-src-elem 'nonce-${NONCE}'; style-src-attr 'unsafe-inline'; img-src 'self' data:` },
    body: `<!doctype html><html><head><meta charset="utf-8"><style nonce="${NONCE}">html,body{margin:0;height:100%}#desk{position:absolute;inset:0}</style></head><body><div id="desk"></div></body></html>`,
  }));
  await page.goto('/widget-grid-csp-fixture.html');
  await page.evaluate(async nonce => {
    const url = '/dist/openalgo-charts.widget.mjs';
    const { createChartGrid } = await import(url);
    const workspace = '/dist/openalgo-charts.workspace.mjs';
    const { WorkspaceRepository, createMemoryWorkspaceStorage } = await import(workspace);
    (window as any).__grid = createChartGrid(document.getElementById('desk'), { styleNonce: nonce, toolbar: true, bottombar: true, preset: '1x2', rail: false,
      workspaces: new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk') });
  }, NONCE);
  await page.locator('.oac-grid__layout').click();
  await expect(page.locator('.oac-grid__picker')).toHaveCSS('display', 'flex');
  await page.keyboard.press('Escape');
  await page.locator('.oac-grid__link').click();
  await page.getByRole('menuitem', { name: 'New group' }).click();
  await expect(page.locator('.oac-grid__menu')).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await page.keyboard.press('Escape');
  await page.locator('.oac-grid__capture').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.oac-grid__bar')).toHaveCSS('display', 'flex');
  await expect(page.locator('.oac-grid__foot .oac-bottombar')).toHaveCSS('display', 'flex');
  await page.locator('.oac-grid__saved').click();
  await expect(page.locator('.oac-grid__overlay .oac-layouts')).toHaveCSS('width', '380px');
  await page.keyboard.press('Escape');
  await expect(page.locator('.oac-grid__mark')).toHaveCount(2);
  expect(await page.evaluate(() => (window as any).__cspViolations)).toEqual([]);
  expect(errors).toEqual([]);
});

test('sixteen charts: frame time while every chart follows a linked pan and crosshair, and the memory they take', async ({ page, browserName }, info) => {
  test.slow();
  // Full widgets, rail and status line included: what a host that asks for sixteen charts gets.
  const errors = await mount(page, '1x1', { width: 1360, height: 900 }, '&toolbar=1&rail=1&statusline=1');
  await readyEvery(page);
  // Chromium reports an exact heap and the main thread's busy time through its protocol;
  // the page's own memory figure is rounded to whole buckets there, and absent elsewhere.
  const cdp = browserName === 'chromium' ? await page.context().newCDPSession(page) : null;
  if (cdp !== null) await cdp.send('Performance.enable');
  const heap = async (): Promise<number | null> => {
    if (cdp === null) return null;
    await cdp.send('HeapProfiler.collectGarbage');
    return Math.round((await cdp.send('Runtime.getHeapUsage')).usedSize / 1e5) / 10;
  };
  const busy = async (): Promise<number | null> => {
    if (cdp === null) return null;
    const { metrics } = await cdp.send('Performance.getMetrics');
    return (metrics.find((m: { name: string }) => m.name === 'TaskDuration')?.value ?? 0) * 1000;
  };
  const oneChart = await heap();
  await page.evaluate(() => (window as any).fixture.grid.setPreset('2x2'));
  await readyEvery(page);
  const fourCharts = await heap();
  const built = await page.evaluate(() => {
    const t0 = performance.now();
    (window as any).fixture.grid.setPreset('4x4');
    return performance.now() - t0;
  });
  await readyEvery(page);
  for (const index of [0, 7, 15]) await expect.poll(() => painted(page, index)).toBe(true);
  const sixteenCharts = await heap();
  await page.evaluate(() => (window as any).fixture.grid.setLinks({ viewport: true, crosshair: true }));

  /** Frame intervals over 60 frames while `step(n)` runs once a frame, and the main thread's work per frame. */
  const frames = async (kind: 'pan' | 'crosshair'): Promise<{ meanMs: number; p95Ms: number; busyMs: number | null }> => {
    const before = await busy();
    const out = await page.evaluate(which => new Promise<number[]>(resolve => {
      const grid = (window as any).fixture.grid;
      const chart = grid.cells()[0].widget.chart;
      const box = grid.cells()[0].widget.root.querySelector('.oac-chart').getBoundingClientRect();
      const list: number[] = [];
      let last = performance.now(), n = 0;
      const tick = (): void => {
        const now = performance.now();
        if (n > 0) list.push(now - last);
        last = now;
        if (n++ >= 60) { resolve(list); return; }
        // The leader pans a bar, or the pointer crosses it; the fifteen followers draw with it.
        if (which === 'pan') chart.setVisibleLogicalRange({ from: 30 + (n % 40), to: 90 + (n % 40) });
        else {
          const x = box.left + box.width * (0.2 + 0.6 * (n % 30) / 30), y = box.top + box.height / 2;
          document.elementFromPoint(x, y)?.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: y, bubbles: true, pointerType: 'mouse' }));
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }), kind);
    const after = await busy();
    const sorted = out.slice().sort((a, b) => a - b);
    return {
      meanMs: Math.round(out.reduce((a, b) => a + b, 0) / out.length * 10) / 10,
      p95Ms: Math.round(sorted[Math.floor(sorted.length * 0.95)] * 10) / 10,
      busyMs: before === null || after === null ? null : Math.round((after - before) / out.length * 10) / 10,
    };
  };
  const pan = await frames('pan');
  // The last chart hears the sweep through its link group, so the frames below include its crosshair.
  await page.evaluate(() => {
    const w = window as any;
    w.followerReadouts = 0;
    w.fixture.grid.cells()[15].widget.chart.on('crosshair:readout', () => { w.followerReadouts++; });
  });
  const crosshair = await frames('crosshair');
  expect(await page.evaluate(() => (window as any).followerReadouts)).toBeGreaterThan(20);
  // Canvas pixels live outside the script heap: every layer of every chart, four bytes a pixel.
  const canvasMB = await page.evaluate(() => Math.round([...document.querySelectorAll('.oac-grid__cell canvas')]
    .reduce((sum, c) => sum + (c as HTMLCanvasElement).width * (c as HTMLCanvasElement).height * 4, 0) / 1e5) / 10);
  const stats = { browser: browserName, buildMs: Math.round(built), pan, crosshair, heapMB: { oneChart, fourCharts, sixteenCharts }, canvasMB };
  info.annotations.push({ type: 'grid-16-perf', description: JSON.stringify(stats) });
  console.log(`grid-16-perf ${JSON.stringify(stats)}`);
  // Budgets against a collapse, not a benchmark: frames of a linked pan and a linked crosshair across sixteen charts.
  expect(pan.p95Ms).toBeLessThan(250);
  expect(crosshair.p95Ms).toBeLessThan(250);
  await page.screenshot({ path: info.outputPath('grid-16-linked.png') });
  expect(errors).toEqual([]);
});
