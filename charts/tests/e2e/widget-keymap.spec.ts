import { test, expect, type Page } from '@playwright/test';

// The shortcuts editor in a real browser, in all three engines. The unit
// suites drive the keymap through a fake DOM with hand-built key events; here
// the keys come from the browser itself, so what is proved is that a real
// Alt+H reaches the recorder before the dialog's own Escape and the chart's
// shortcuts, that the recorded chord fires on the chart afterwards, and that
// the change is still there after a reload.

const KEY = 'oac-widget:keymap-fixture:keymap';
const DIALOG = '.oac-keys-dialog';
const row = (page: Page, command: string) => page.locator(`${DIALOG} .oac-keys__row[data-command="${command}"]`);

async function mount(page: Page, query = '?persist'): Promise<string[]> {
  const errors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.setViewportSize({ width: 1180, height: 760 });
  await page.goto('/tests/e2e/widget-keymap-fixture.html' + query);
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
  return errors;
}

async function reload(page: Page): Promise<void> {
  await page.reload();
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
}

/** The pointer over the chart, which is where the widget's chords apply. */
async function overChart(page: Page): Promise<void> {
  const box = await page.locator('.oac-widget .oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
}

const activeTool = (page: Page): Promise<string | null> => page.evaluate(() => (window as any).__widget.draw.activeTool());

test('press ?, rebind a tool chord by pressing keys, see the conflict, reload and keep it, reset to the default', async ({ page }) => {
  const errors = await mount(page);
  await page.evaluate(() => (window as any).__clearStore());
  await reload(page);
  await overChart(page);

  await page.keyboard.press('Shift+Slash');
  await expect(page.locator(DIALOG)).toBeVisible();
  const trend = row(page, 'tool:trend-line');
  await expect(trend.locator('kbd')).toHaveText('Alt+T');

  // Change, then the chord itself: Alt+H is the horizontal line's.
  await trend.locator('.oac-keys__change').click();
  await expect(trend).toHaveClass(/is-listening/);
  await expect(page.locator(`${DIALOG} .oac-keys__status`)).toContainText('Press the new shortcut for Trend Line');
  await page.keyboard.press('Alt+KeyH');
  const conflict = page.locator(`${DIALOG} .oac-keys__conflict`);
  await expect(conflict).toBeVisible();
  await expect(conflict).toContainText('Alt+H is used by Horizontal Line');
  // Nothing moved yet: the choice is the user's.
  await expect(trend.locator('kbd')).toHaveText('Alt+T');
  await conflict.getByRole('button', { name: 'Replace' }).click();
  await expect(trend.locator('kbd')).toHaveText('Alt+H');
  await expect(trend).toHaveClass(/is-changed/);
  await expect(row(page, 'tool:horizontal-line').locator('kbd')).toHaveText('Not set');
  expect(await page.evaluate((k) => (window as any).__stored(k), KEY))
    .toMatchObject({ 'tool:trend-line': 'Alt+h', 'tool:horizontal-line': null });

  // Escape closes the panel now that nothing is recording; the new chord picks the tool.
  await page.keyboard.press('Escape');
  await expect(page.locator(DIALOG)).toHaveCount(0);
  await overChart(page);
  await page.keyboard.press('Alt+KeyH');
  expect(await activeTool(page)).toBe('trend-line');
  await page.keyboard.press('Escape');
  expect(await activeTool(page)).toBeNull();

  // A reload keeps the change.
  await reload(page);
  await overChart(page);
  await page.keyboard.press('Alt+KeyH');
  expect(await activeTool(page)).toBe('trend-line');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Alt+KeyT');
  expect(await activeTool(page)).toBeNull();

  // Reset the row: the default comes back and fires again.
  await page.keyboard.press('Shift+Slash');
  await expect(row(page, 'tool:trend-line').locator('kbd')).toHaveText('Alt+H');
  await row(page, 'tool:trend-line').locator('.oac-keys__reset').click();
  await expect(row(page, 'tool:trend-line').locator('kbd')).toHaveText('Alt+T');
  await expect(row(page, 'tool:trend-line')).not.toHaveClass(/is-changed/);
  // Reset all, after its confirmation, brings back what the replace took.
  await page.locator(`${DIALOG} .oac-keys__reset-all`).click();
  await page.locator(`${DIALOG} .oac-dialog__foot`).getByRole('button', { name: 'Reset all' }).click();
  await expect(row(page, 'tool:horizontal-line').locator('kbd')).toHaveText('Alt+H');
  await page.keyboard.press('Escape');
  await expect(page.locator(DIALOG)).toHaveCount(0);
  expect(await page.evaluate((k) => (window as any).__stored(k), KEY)).toBeNull();
  await overChart(page);
  await page.keyboard.press('Alt+KeyT');
  expect(await activeTool(page)).toBe('trend-line');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Alt+KeyH');
  expect(await activeTool(page)).toBe('horizontal-line');
  await page.keyboard.press('Escape');

  await reload(page);
  await overChart(page);
  await page.keyboard.press('Alt+KeyT');
  expect(await activeTool(page)).toBe('trend-line');
  expect(await page.evaluate(() => (window as any).__widgetErrors)).toEqual([]);
  expect(errors).toEqual([]);
});

test('works from the keyboard alone: Enter records, Escape cancels without closing, focus stays on the row', async ({ page }) => {
  await mount(page, '');
  await overChart(page);
  await page.keyboard.press('Shift+Slash');
  const undo = row(page, 'undo');
  const change = undo.locator('.oac-keys__change');
  await change.focus();
  await page.keyboard.press('Enter');
  await expect(undo).toHaveClass(/is-listening/);
  await page.keyboard.press('Escape');
  await expect(undo).not.toHaveClass(/is-listening/);
  await expect(page.locator(DIALOG)).toBeVisible();
  await expect(undo.locator('.oac-keys__change')).toBeFocused();

  await page.keyboard.press('Enter');
  // The browser keeps Ctrl+W; the panel says so and keeps listening. A bare letter types into the chart.
  await page.keyboard.press('Control+KeyW');
  await expect(page.locator(`${DIALOG} .oac-keys__status`)).toContainText('belongs to the browser');
  await expect(undo).toHaveClass(/is-listening/);
  await page.keyboard.press('KeyG');
  await expect(page.locator(`${DIALOG} .oac-keys__status`)).toContainText('types into the chart');
  // Space alone would take the press from every button; the refused press must not click the focused Cancel either.
  await page.keyboard.press('Space');
  await expect(page.locator(`${DIALOG} .oac-keys__status`)).toContainText('presses the focused control');
  await expect(undo).toHaveClass(/is-listening/);
  await page.keyboard.press('Alt+KeyU');
  await expect(undo.locator('kbd')).toHaveText('Alt+U');
  await expect(undo.locator('.oac-keys__change')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator(DIALOG)).toHaveCount(0);

  // The moved Undo undoes; the old chord no longer does.
  await page.evaluate(() => {
    const w = (window as any).__widget;
    const bars = w.series.getData();
    const bar = bars[bars.length - 40];
    w.draw.add({ tool: 'horizontal-line', points: [{ time: bar.time, price: bar.close }], style: {}, paneIndex: 0 });
  });
  const count = (): Promise<number> => page.evaluate(() => (window as any).__widget.draw.drawings().length);
  expect(await count()).toBe(1);
  await overChart(page);
  await page.keyboard.press('Control+KeyZ');
  expect(await count()).toBe(1);
  await page.keyboard.press('Alt+KeyU');
  expect(await count()).toBe(0);
});

test('rebinds a chart command with the physical key through the chart shortcut manager', async ({ page }) => {
  await mount(page, '');
  await overChart(page);
  await page.keyboard.press('Shift+Slash');
  const fit = row(page, 'chart:fitContent');
  await fit.locator('.oac-keys__change').click();
  await page.keyboard.press('Alt+KeyG');
  await expect(fit.locator('kbd')).toHaveText('Alt+G');
  expect(await page.evaluate(() => (window as any).__widget.chart.shortcuts.handleKey('Alt+KeyG'))).toBe('fitContent');
  await page.keyboard.press('Escape');
  // The chart fits on the new chord: zoom in first so a fit has something to undo.
  await overChart(page);
  const span = (): Promise<number> => page.evaluate(() => { const r = (window as any).__widget.chart.getVisibleLogicalRange(); return r.to - r.from; });
  await page.evaluate(() => (window as any).__widget.chart.setVisibleLogicalRange({ from: 250, to: 280 }));
  const zoomed = await span();
  await page.keyboard.press('Alt+KeyG');
  await expect.poll(span).toBeGreaterThan(zoomed + 50);
});

test('a chord recorded in one chart does not fire in the chart beside it', async ({ page }) => {
  const errors = await mount(page, '?two');
  await page.waitForFunction(() => (window as any).__loaded2 > 0);
  const charts = page.locator('.oac-widget .oac-chart');
  const at = async (i: number): Promise<void> => {
    const box = await charts.nth(i).boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  };
  await at(1);
  await page.keyboard.press('Shift+Slash');
  const dialog = page.locator('#u .oac-keys-dialog');
  await expect(dialog).toBeVisible();
  await expect(page.locator('#t .oac-keys-dialog')).toHaveCount(0);
  await dialog.locator('.oac-keys__row[data-command="tool:trend-line"] .oac-keys__change').click();
  // The pointer rests on the first chart, which is attached first and sees the key first.
  await at(0);
  await page.keyboard.press('Alt+KeyH');
  await expect(dialog.locator('.oac-keys__conflict')).toContainText('Alt+H is used by Horizontal Line');
  expect(await activeTool(page)).toBeNull();
  // Recording over, the first chart answers to its own chords again.
  await dialog.locator('.oac-keys__conflict').getByRole('button', { name: 'Cancel' }).click();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await at(0);
  await page.keyboard.press('Alt+KeyH');
  expect(await activeTool(page)).toBe('horizontal-line');
  expect(errors).toEqual([]);
});

test('fits a phone-width widget in one column, with every control reachable', async ({ page }) => {
  await mount(page, '');
  await page.setViewportSize({ width: 390, height: 760 });
  await overChart(page);
  await page.keyboard.press('Shift+Slash');
  const dialog = page.locator(DIALOG);
  await expect(dialog).toBeVisible();
  // It opens at the top of the list: the focus is on the panel, not on a Change further down.
  await expect(dialog).toBeFocused();
  expect(await page.locator(`${DIALOG} .oac-dialog__body`).evaluate((el) => el.scrollTop)).toBe(0);
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(await page.locator(`${DIALOG} .oac-keys`).evaluate((el) => getComputedStyle(el).columnCount)).toBe('1');
  const change = row(page, 'chart:zoomIn').locator('.oac-keys__change');
  await change.scrollIntoViewIfNeeded();
  const b = await change.boundingBox();
  expect(b!.x + b!.width).toBeLessThanOrEqual(390);
});
