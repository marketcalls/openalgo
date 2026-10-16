import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type { DrawingTemplateRepository } from '../../src/workspace/drawing-templates';

declare global {
  interface Window {
    __drawUi: {
      widget: Widget; templates: DrawingTemplateRepository; ready: boolean; errors: string[];
      ids: { trend: string; level: string; box: string };
      bars: Array<{ time: number; open: number; high: number; low: number; close: number }>;
    };
  }
}

async function mount(page: Page, theme: 'dark' | 'light' = 'dark'): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 760 });
  await page.goto(`/tests/e2e/widget-drawing-ui-fixture.html?theme=${theme}`);
  await page.waitForFunction(() => window.__drawUi?.ready === true);
  return errors;
}

const WORKSPACE_MODULE = '/dist/openalgo-charts.workspace.mjs';

const select = (page: Page, ...keys: Array<'trend' | 'level' | 'box'>) => page.evaluate(names => {
  const { widget, ids } = window.__drawUi;
  widget.draw.select(names.map(name => ids[name]));
}, keys);

/** A point on the chart in page pixels, from a time and a price. */
const at = (page: Page, time: number, price: number) => page.evaluate(([t, p]) => {
  const { widget } = window.__drawUi;
  const box = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
  return { x: box.left + widget.chart.timeToCoordinate(t), y: box.top + widget.chart.priceToCoordinate(p)! };
}, [time, price] as const);

/** Pixels of one colour on the top drawing canvas, to see a stroke get heavier. */
const ink = (page: Page, rgb: [number, number, number]) => page.locator('.oac-chart canvas').nth(1).evaluate((element, target) => {
  const canvas = element as HTMLCanvasElement;
  const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
  let n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (Math.abs(data[i] - target[0]) < 40 && Math.abs(data[i + 1] - target[1]) < 40 && Math.abs(data[i + 2] - target[2]) < 40 && data[i + 3] > 120) n++;
  }
  return n;
}, rgb);

const style = (page: Page, key: 'trend' | 'level' | 'box') => page.evaluate(name => {
  const { widget, ids } = window.__drawUi;
  const d = widget.draw.get(ids[name])!;
  return { ...d.style, locked: d.locked === true, points: d.points };
}, key);

test('the floating toolbar sits by the selection, edits it in one step and follows a pan', async ({ page }, info) => {
  const errors = await mount(page);
  const bar = page.locator('.oac-drawbar');
  await expect(bar).toBeHidden();
  await select(page, 'trend');
  await expect(bar).toBeVisible();
  const chart = await page.locator('.oac-chart').boundingBox();
  const placed = await bar.boundingBox();
  // Inside the chart, above the line's highest visible anchor.
  expect(placed!.x).toBeGreaterThanOrEqual(chart!.x);
  expect(placed!.x + placed!.width).toBeLessThanOrEqual(chart!.x + chart!.width);
  const anchors = await page.evaluate(() => window.__drawUi.widget.draw.screenPoints(window.__drawUi.ids.trend)!);
  expect(placed!.y + placed!.height).toBeLessThanOrEqual(chart!.y + Math.min(...anchors.map(p => p.y)));
  await page.screenshot({ path: info.outputPath('toolbar.png') });

  const before = await ink(page, [240, 160, 32]);
  await bar.locator('[data-drawbar="width"]').click();
  await page.getByRole('menuitemradio', { name: '4 px' }).click();
  expect((await style(page, 'trend')).lineWidth).toBe(4);
  await expect.poll(() => ink(page, [240, 160, 32])).toBeGreaterThan(before * 1.4);
  await bar.locator('[data-drawbar="style"]').click();
  await page.getByRole('menuitemradio', { name: 'Dashed' }).click();
  expect((await style(page, 'trend')).lineStyle).toBe('dashed');
  await expect(bar.locator('[data-drawbar="style"]')).toHaveAttribute('aria-label', 'Line style: Dashed');
  // One press per change, newest first.
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  expect((await style(page, 'trend')).lineStyle).toBeUndefined();
  expect((await style(page, 'trend')).lineWidth).toBe(4);
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  expect((await style(page, 'trend')).lineWidth).toBe(2);

  // A pan carries the drawing, and the bar with it.
  const x0 = (await bar.boundingBox())!.x;
  await page.evaluate(() => {
    const { widget } = window.__drawUi;
    const r = widget.chart.getVisibleLogicalRange();
    widget.chart.setVisibleLogicalRange({ from: r.from + 40, to: r.to + 40 });
  });
  await expect.poll(async () => (await bar.boundingBox())!.x).not.toBe(x0);

  // Dragging the price axis rescales it with no pan or zoom: the bar keeps its gap over the line.
  const gap = () => page.evaluate(() => {
    const { widget, ids } = window.__drawUi;
    const box = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
    const top = box.top + Math.min(...widget.draw.screenPoints(ids.trend)!.map(p => p.y));
    return top - widget.root.querySelector('.oac-drawbar')!.getBoundingClientRect().bottom;
  });
  expect(await gap()).toBeCloseTo(10, 0);
  const axisX = chart!.x + chart!.width - 25;
  const lineTop = await page.evaluate(() => window.__drawUi.widget.draw.screenPoints(window.__drawUi.ids.trend)!.map(p => p.y));
  await page.mouse.move(axisX, chart!.y + chart!.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(axisX, chart!.y + chart!.height * 0.45 + 90, { steps: 8 });
  await page.mouse.up();
  expect(await page.evaluate(() => window.__drawUi.widget.draw.screenPoints(window.__drawUi.ids.trend)!.map(p => p.y))).not.toEqual(lineTop);
  await expect.poll(gap).toBeCloseTo(10, 0);
  await page.screenshot({ path: info.outputPath('axis-drag.png') });
  expect(errors).toEqual([]);
});

test('a mixed selection says mixed, locks and deletes as one step, and a read-only one is greyed', async ({ page }, info) => {
  const errors = await mount(page);
  const bar = page.locator('.oac-drawbar');
  await select(page, 'trend', 'level');
  await expect(bar.locator('[data-drawbar="color"]')).toHaveAttribute('aria-label', 'Color: mixed');
  await expect(bar.locator('[data-drawbar="width"]')).toHaveText('Mixed');
  await page.screenshot({ path: info.outputPath('mixed.png') });
  await bar.locator('[data-drawbar="lock"]').click();
  expect((await style(page, 'trend')).locked && (await style(page, 'level')).locked).toBe(true);
  await expect(bar.locator('[data-drawbar="lock"]')).toHaveAttribute('aria-pressed', 'true');
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  await expect(bar.locator('[data-drawbar="lock"]')).toHaveAttribute('aria-pressed', 'false');
  await bar.locator('[data-drawbar="delete"]').click();
  expect(await page.evaluate(() => window.__drawUi.widget.draw.drawings().length)).toBe(1);
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  expect(await page.evaluate(() => window.__drawUi.widget.draw.drawings().length)).toBe(3);

  await page.evaluate(() => {
    const { widget, ids } = window.__drawUi;
    widget.draw.update(ids.box, { policy: { editable: false } }, { force: true });
    widget.draw.select(ids.box);
  });
  for (const name of ['color', 'width', 'style', 'lock', 'delete']) {
    await expect(bar.locator(`[data-drawbar="${name}"]`)).toBeDisabled();
  }
  await expect(bar.locator('[data-drawbar="more"]')).toBeEnabled();
  expect(errors).toEqual([]);
});

test('the rail and the right-click menu act on a selection in one step each, by the toolbar\'s rules', async ({ page }, info) => {
  const errors = await mount(page);
  const order = () => page.evaluate(() => window.__drawUi.widget.draw.drawings().map(d => `${d.id}:${d.zIndex}`));
  const undo = () => page.evaluate(() => window.__drawUi.widget.history.undo());
  await select(page, 'trend', 'level');
  // The rail's lock: one press, one step back.
  const railLock = page.locator('.oac-rail__ctl .oac-rail__btn').nth(2);
  await railLock.click();
  expect((await style(page, 'trend')).locked && (await style(page, 'level')).locked).toBe(true);
  await undo();
  expect((await style(page, 'trend')).locked || (await style(page, 'level')).locked).toBe(false);
  // A partly locked selection reads unlocked in the menu, deletes, and locks whole in one step.
  await page.evaluate(() => { const { widget, ids } = window.__drawUi; widget.draw.update(ids.level, { locked: true }); });
  await select(page, 'trend', 'level');
  const ends = await page.evaluate(() => { const { widget, ids } = window.__drawUi; return widget.draw.get(ids.trend)!.points; });
  const [a, b] = [await at(page, ends[0]!.time, ends[0]!.price), await at(page, ends[1]!.time, ends[1]!.price)];
  const onTrend = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const menu = page.locator('.oac-ctx');
  await page.mouse.click(onTrend.x, onTrend.y, { button: 'right' });
  await expect(menu.locator('[data-act="draw-lock"]')).toHaveAttribute('aria-checked', 'false');
  await expect(menu.locator('[data-act="draw-delete"]')).not.toHaveAttribute('aria-disabled', 'true');
  await page.screenshot({ path: info.outputPath('menu-partly-locked.png') });
  await menu.locator('[data-act="draw-lock"]').click();
  expect((await style(page, 'trend')).locked && (await style(page, 'level')).locked).toBe(true);
  await undo();
  expect([(await style(page, 'trend')).locked, (await style(page, 'level')).locked]).toEqual([false, true]);
  // The order moves of a selection are one step too.
  const before = await order();
  await page.mouse.click(onTrend.x, onTrend.y, { button: 'right' });
  await menu.locator('[data-act="draw-front"]').click();
  expect(await order()).not.toEqual(before);
  await undo();
  expect(await order()).toEqual(before);
  // The rail's right-click menus walk with the arrows, as every other menu does.
  const trash = page.locator('.oac-rail__ctl .oac-rail__btn').nth(4);
  await trash.click({ button: 'right' });
  const rows = page.locator('.oac-menu .oac-menu__row');
  await expect(rows.first()).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(rows.nth(1)).toBeFocused();
  await page.screenshot({ path: info.outputPath('rail-menu.png') });
  await page.keyboard.press('Escape');
  expect(errors).toEqual([]);
});

test('the keyboard reaches the toolbar from the chart and walks it without moving the drawing', async ({ page }) => {
  const errors = await mount(page);
  await select(page, 'trend');
  const points = JSON.stringify((await style(page, 'trend')).points);
  await page.locator('.oac-chart').focus();
  await page.keyboard.press('Tab');
  const focused = () => page.evaluate(() => (document.activeElement as HTMLElement).dataset.drawbar ?? document.activeElement?.className);
  await expect.poll(focused).toBe('more');
  await page.keyboard.press('Home');
  await expect.poll(focused).toBe('color');
  await page.keyboard.press('ArrowRight');
  await expect.poll(focused).toBe('width');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menuitemradio', { name: '3 px' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.keyboard.press('ArrowRight');
  await expect.poll(focused).toBe('style');
  // Every arrow walks the bar, Shift or not: none of them nudges the line it edits.
  await page.keyboard.press('ArrowDown');
  await expect.poll(focused).toBe('lock');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Shift+ArrowUp');
  await expect.poll(focused).toBe('width');
  await page.keyboard.press('Shift+ArrowDown');
  await page.keyboard.press('Shift+ArrowRight');
  await page.keyboard.press('Shift+ArrowLeft');
  await expect.poll(focused).toBe('style');
  expect(JSON.stringify((await style(page, 'trend')).points)).toBe(points);
  await page.keyboard.press('Escape');
  await expect.poll(focused).toContain('oac-chart');
  expect(await page.evaluate(() => window.__drawUi.widget.draw.selection())).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('a saved default reaches the next drawing placed with that tool, in the one undo step of its placement', async ({ page }, info) => {
  const errors = await mount(page);
  const bar = page.locator('.oac-drawbar');
  await select(page, 'trend');
  await bar.locator('[data-drawbar="width"]').click();
  await page.getByRole('menuitemradio', { name: '3 px' }).click();
  await bar.locator('[data-drawbar="more"]').click();
  await page.getByRole('menuitem', { name: 'Save as default for this tool' }).click();
  await expect.poll(() => page.evaluate(async () => (await window.__drawUi.templates.load()).defaults.map(d => d.tool))).toEqual(['trend-line']);
  const existing = await page.evaluate(() => window.__drawUi.widget.draw.get(window.__drawUi.ids.box)!.style.lineWidth);

  // Place a trend line the way a user does: the rail's tool, two clicks on the chart.
  const bars = await page.evaluate(() => window.__drawUi.bars.slice(-120, -20).map(b => ({ time: b.time, low: b.low, high: b.high })));
  const from = await at(page, bars[10].time, bars[10].low);
  const to = await at(page, bars[80].time, bars[80].high);
  await page.evaluate(() => window.__drawUi.widget.draw.setTool('trend-line'));
  await page.mouse.click(from.x, from.y);
  await page.mouse.click(to.x, to.y);
  const placed = await page.evaluate(() => {
    const all = window.__drawUi.widget.draw.drawings();
    return { count: all.length, last: all[all.length - 1] };
  });
  expect(placed.count).toBe(4);
  expect(placed.last.tool).toBe('trend-line');
  expect(placed.last.style.lineWidth).toBe(3);
  expect(placed.last.style.color).toBe('#f0a020');
  // The other tools, and the drawings already there, keep their own look.
  expect(await page.evaluate(() => window.__drawUi.widget.draw.get(window.__drawUi.ids.box)!.style.lineWidth)).toBe(existing);
  await page.screenshot({ path: info.outputPath('default-placed.png') });
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z');
  await expect.poll(() => page.evaluate(() => window.__drawUi.widget.draw.drawings().length)).toBe(3);
  expect(errors).toEqual([]);
});

test('a named template saves from the more menu and applies to another drawing of the tool', async ({ page }) => {
  const errors = await mount(page);
  const bar = page.locator('.oac-drawbar');
  await page.evaluate(() => {
    const { widget, ids, bars } = window.__drawUi;
    const n = bars.length;
    (window as unknown as { second: string }).second = widget.draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: bars[n - 90].time, price: bars[n - 90].high }, { time: bars[n - 30].time, price: bars[n - 30].high }] }).id;
    widget.draw.select(ids.trend);
  });
  await bar.locator('[data-drawbar="more"]').click();
  await page.getByRole('menuitem', { name: 'Save as template...' }).click();
  const input = page.getByLabel('Template name');
  await expect(input).toBeFocused();
  await input.fill('Swing low support');
  await input.press('Enter');
  await expect(input).toBeHidden();
  await page.evaluate(() => window.__drawUi.widget.draw.select((window as unknown as { second: string }).second));
  await bar.locator('[data-drawbar="more"]').click();
  await page.getByRole('menuitem', { name: 'Apply Swing low support' }).click();
  expect(await page.evaluate(() => window.__drawUi.widget.draw.get((window as unknown as { second: string }).second)!.style.color)).toBe('#f0a020');
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  expect(await page.evaluate(() => window.__drawUi.widget.draw.get((window as unknown as { second: string }).second)!.style.color)).not.toBe('#f0a020');
  expect(errors).toEqual([]);
});

test('templates kept in IndexedDB survive a reload, per namespace, and a stale write is refused', async ({ page }) => {
  const errors = await mount(page);
  const saved = await page.evaluate(async modulePath => {
    const { DrawingTemplateRepository, createIndexedDbDrawingTemplateStorage } = await import(modulePath);
    const storage = createIndexedDbDrawingTemplateStorage(indexedDB, 'drawing-templates-e2e');
    let n = 0;
    const repo = new DrawingTemplateRepository(storage, 'desk', { id: () => `t${++n}`, now: () => 1000 });
    await repo.saveTemplate('Swing low support', 'trend-line', { 'style.color': '#f0a020', 'style.lineWidth': 2 });
    await repo.setDefault('rectangle', { 'style.fill': true, 'style.fillOpacity': 0.1 });
    // Prepared against revision 1, after the catalog moved on to 2.
    let refused = '';
    try { await repo.setDefault('ray', { 'style.lineWidth': 3 }, { expectedRevision: 1 }); } catch (error) { refused = (error as Error).name; }
    const other = await new DrawingTemplateRepository(storage, 'another-account').load();
    await storage.close();
    return { refused, other: other.templates.length + other.defaults.length };
  }, WORKSPACE_MODULE);
  expect(saved).toEqual({ refused: 'DrawingTemplateConflictError', other: 0 });
  await page.reload();
  const loaded = await page.evaluate(async modulePath => {
    const { DrawingTemplateRepository, createIndexedDbDrawingTemplateStorage } = await import(modulePath);
    const storage = createIndexedDbDrawingTemplateStorage(indexedDB, 'drawing-templates-e2e');
    const catalog = await new DrawingTemplateRepository(storage, 'desk').load();
    await storage.close();
    return catalog;
  }, WORKSPACE_MODULE);
  expect(loaded).toEqual({
    version: 1, revision: 2,
    templates: [{ id: 't1', name: 'Swing low support', tool: 'trend-line', values: { 'style.color': '#f0a020', 'style.lineWidth': 2 }, createdAt: 1000, updatedAt: 1000 }],
    defaults: [{ tool: 'rectangle', values: { 'style.fill': true, 'style.fillOpacity': 0.1 }, updatedAt: 1000 }],
  });
  expect(errors).toEqual([]);
});

test('the coordinates tab shows each anchor on the chart clock and moves it to a typed price in one step', async ({ page }, info) => {
  const errors = await mount(page);
  await select(page, 'trend');
  await page.locator('.oac-drawbar [data-drawbar="more"]').click();
  await page.getByRole('menuitem', { name: 'Properties...' }).click();
  const dialog = page.locator('.oac-props');
  await dialog.getByRole('tab', { name: 'Coordinates' }).click();
  const anchor = await style(page, 'trend');
  const row = dialog.locator('.oac-coords__row').nth(1);
  const expected = await page.evaluate(time => {
    const f = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    const p = Object.fromEntries(f.formatToParts(new Date(time * 1000)).map(part => [part.type, part.value]));
    return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
  }, anchor.points[1].time);
  await expect(row.locator('.oac-coords__date')).toHaveValue(expected.date);
  await expect(row.locator('.oac-coords__time')).toHaveValue(expected.time);
  await page.screenshot({ path: info.outputPath('coordinates.png') });
  const price = row.locator('.oac-coords__price');
  await price.fill('2,300.25');
  await price.press('Enter');
  await expect.poll(async () => (await style(page, 'trend')).points[1].price).toBe(2300.25);
  expect((await style(page, 'trend')).points[1].time).toBe(anchor.points[1].time);
  await price.fill('abc');
  await price.press('Enter');
  await expect(row.locator('.oac-input-error')).toHaveText('Enter a price as a number');
  await expect(price).toHaveAttribute('aria-invalid', 'true');
  await page.evaluate(() => window.__drawUi.widget.history.undo());
  await expect.poll(async () => (await style(page, 'trend')).points[1].price).toBe(anchor.points[1].price);
  expect(errors).toEqual([]);
});

test('a date typed into the coordinates tab moves the anchor once, when the focus leaves the row', async ({ page, browserName }) => {
  const errors = await mount(page);
  await select(page, 'trend');
  await page.locator('.oac-drawbar [data-drawbar="more"]').click();
  await page.getByRole('menuitem', { name: 'Properties...' }).click();
  const dialog = page.locator('.oac-props');
  await dialog.getByRole('tab', { name: 'Coordinates' }).click();
  const anchor = await style(page, 'trend');
  const steps = () => page.evaluate(() => window.__drawUi.widget.draw.historySteps().undo.length);
  const before = await steps();
  const row = dialog.locator('.oac-coords__row').nth(0);
  const date = row.locator('.oac-coords__date');
  const shown = await date.inputValue();
  const target = `2025${shown.slice(4)}`;
  if (browserName === 'webkit') {
    // This engine lays a date field out as plain text here, so it takes the whole value.
    await date.fill(target);
  } else {
    // Typed the way a person does, into the year segment (last in every order this runs
    // in): the field reports each partial year, 0002, 0020 and 0202, on the way to 2025.
    await date.click({ position: { x: 8, y: 8 } });
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.type('2025');
  }
  await expect(date).toHaveValue(target);
  expect((await style(page, 'trend')).points[0].time).toBe(anchor.points[0].time);
  // Across the row is still the same edit; out of it is one write and one step.
  await row.locator('.oac-coords__time').focus();
  expect((await style(page, 'trend')).points[0].time).toBe(anchor.points[0].time);
  await dialog.locator('.oac-coords__row').nth(1).locator('.oac-coords__price').focus();
  await expect.poll(async () => (await style(page, 'trend')).points[0].time).toBe(anchor.points[0].time - 365 * 86400);
  expect(await steps()).toBe(before + 1);
  expect(errors).toEqual([]);
});

test('the objects panel reorders by dragging a row and by Alt with an arrow key', async ({ page }, info) => {
  const errors = await mount(page);
  await page.evaluate(() => window.__drawUi.widget.openObjects());
  const stack = () => page.evaluate(() => window.__drawUi.widget.objects.stack(0).map(item => item.name));
  expect(await stack()).toEqual(['RELIANCE', 'Trend Line', 'Horizontal Line', 'Rectangle']);
  const rows = page.locator('.oac-objects__row[data-object-id^="drawing:"]');
  await expect(page.locator('.oac-objects__hint')).toContainText('back to front');
  await expect(rows.first().locator('.oac-objects__grip')).toBeVisible();
  const source = (await rows.nth(0).boundingBox())!;
  const target = (await rows.nth(2).boundingBox())!;
  // Pressed on the row's edge, released on the lower half of the last row: over it in paint order.
  await page.mouse.move(source.x + 4, source.y + 4);
  await page.mouse.down();
  await page.mouse.move(source.x + 10, source.y + 10, { steps: 3 });
  await page.mouse.move(target.x + 60, target.y + target.height - 6, { steps: 10 });
  // Some engines deliver the drop target only once the pointer rests on it.
  await page.waitForTimeout(100);
  await page.mouse.move(target.x + 62, target.y + target.height - 5, { steps: 3 });
  await page.waitForTimeout(100);
  await page.mouse.up();
  await expect.poll(stack).toEqual(['RELIANCE', 'Horizontal Line', 'Rectangle', 'Trend Line']);
  await page.screenshot({ path: info.outputPath('objects-dragged.png') });
  await page.locator('.oac-objects__row[data-object-id^="drawing:"]').last().locator('.oac-objects__summary').focus();
  await page.keyboard.press('Alt+ArrowUp');
  await expect.poll(stack).toEqual(['RELIANCE', 'Horizontal Line', 'Trend Line', 'Rectangle']);
  expect(errors).toEqual([]);
});

for (const theme of ['dark', 'light'] as const) {
  test(`faint chrome text reads at the contrast minimum in the ${theme} theme`, async ({ page }) => {
    const errors = await mount(page, theme);
    const ratios = await page.evaluate(() => {
      const root = window.__drawUi.widget.root;
      const probe = (color: string): [number, number, number] => {
        const node = document.createElement('span');
        node.style.color = color;
        root.appendChild(node);
        const rgb = getComputedStyle(node).color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number) as [number, number, number];
        node.remove();
        return rgb;
      };
      const lum = ([r, g, b]: [number, number, number]) => {
        const c = (v: number) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
        return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
      };
      const ratio = (a: string, b: string) => {
        const [x, y] = [lum(probe(a)), lum(probe(b))];
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
      };
      return Object.fromEntries(['faint', 'up', 'down'].flatMap(role => ['bg', 'panel', 'panel-2', 'elev']
        .map(surface => [`${role} on ${surface}`, ratio(`var(--oac-${role})`, `var(--oac-${surface})`)])));
    });
    for (const [pair, value] of Object.entries(ratios)) expect(value, pair).toBeGreaterThanOrEqual(4.5);
    expect(errors).toEqual([]);
  });
}
