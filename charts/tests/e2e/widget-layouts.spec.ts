import { expect, test, type Page } from '@playwright/test';

// Saved layouts and indicator templates in the widget, over the browser's own
// IndexedDB: a layout saved, renamed, reloaded and reopened; a second tab that
// saved the same layout meanwhile, settled with a copy and with an overwrite;
// autosave across a reload; a template applied from the picker and walked back
// and forth with the keyboard; and the phone layout's More sheet. Each test
// has a browser context of its own, so its catalog starts empty.

const FIXTURE = '/tests/e2e/widget-layouts-fixture.html';

async function mount(page: Page, query = '', width = 1280, height = 720): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.setViewportSize({ width, height });
  await page.goto(FIXTURE + query);
  await ready(page);
  return errors;
}

async function ready(page: Page): Promise<void> {
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0, undefined, { timeout: 20_000 });
}

const menu = (page: Page) => page.locator('.oac-layouts');
const label = (page: Page) => page.locator('.oac-topbar__layouts-name');

async function openMenu(page: Page): Promise<void> {
  await page.locator('.oac-topbar__layouts').click();
  await expect(menu(page)).toBeVisible();
}

/** Name the chart through the menu's form. */
async function saveAs(page: Page, name: string, trigger = 'save-as'): Promise<void> {
  await menu(page).locator(`[data-action="${trigger}"]`).click();
  await menu(page).locator('.oac-layouts__input').fill(name);
  await menu(page).locator('[data-action="submit-name"]').click();
  await expect(menu(page).locator('.oac-layouts__name')).toHaveText(name);
}

const chart = (page: Page) => page.evaluate(() => {
  const w = (window as any).__widget;
  return { symbol: w.symbol(), interval: w.interval(), chartType: w.chartType(), studies: w.chart.indicators().map((s: any) => s.indicatorId) };
});

/** The stored layouts, by name. */
const stored = (page: Page) => page.evaluate(async () => {
  const catalog = await (window as any).__repo.load();
  return Object.fromEntries(catalog.workspaces.map((doc: any) => [doc.name, { interval: doc.panes[0].interval, chartType: doc.panes[0].chartType, symbol: doc.panes[0].symbol }]));
});

async function pickChartType(page: Page, name: string): Promise<void> {
  await page.locator('.oac-topbar button[aria-label="Chart type"]').click();
  await page.getByRole('menuitemradio', { name, exact: true }).click();
}

test('saves, renames, reloads and reopens a layout, asking before it drops a change', async ({ page }, info) => {
  const errors = await mount(page);
  await expect(label(page)).toHaveText('Layouts');
  await openMenu(page);
  await expect(menu(page).locator('.oac-layouts__name')).toHaveText('No layout open');
  // With nothing held, Save names the chart first.
  await menu(page).locator('[data-action="save"]').click();
  await expect(menu(page).locator('.oac-layouts__input')).toHaveValue('INFY 5m');
  await menu(page).locator('.oac-layouts__input').fill('Morning');
  await menu(page).locator('.oac-layouts__input').press('Enter');
  await expect(menu(page).locator('.oac-layouts__name')).toHaveText('Morning');
  await expect(label(page)).toHaveText('Morning');
  await page.keyboard.press('Escape');
  await expect(menu(page)).toHaveCount(0);

  // A change, then Save.
  await page.locator('.oac-pills button[data-interval="15m"]').click();
  // The dot's meaning is in the name, and stays there when the keyboard reaches the button.
  await expect(page.locator('.oac-topbar__layouts')).toHaveAttribute('aria-label', /, Unsaved changes$/);
  await page.locator('.oac-topbar__layouts').focus();
  await expect(page.locator('.oac-topbar__layouts')).toHaveAttribute('aria-label', /, Unsaved changes$/);
  await openMenu(page);
  await expect(menu(page).locator('.oac-layouts__line')).toHaveText('Unsaved changes');
  await expect(page.locator('.oac-topbar__layouts')).toHaveAttribute('data-attention', 'true');
  await menu(page).locator('[data-action="save"]').click();
  await expect(menu(page).locator('.oac-layouts__line')).toHaveText(/^Saved /);
  await expect(page.locator('.oac-topbar__layouts')).toHaveAttribute('data-attention', 'false');

  // Rename it.
  await menu(page).locator('[data-action="rename"]').click();
  await expect(menu(page).locator('.oac-layouts__input')).toHaveValue('Morning');
  await menu(page).locator('.oac-layouts__input').fill('Opening range');
  await menu(page).locator('[data-action="submit-name"]').click();
  await expect(label(page)).toHaveText('Opening range');
  await info.attach('layouts menu, a held layout', { body: await page.screenshot(), contentType: 'image/png' });
  expect(await stored(page)).toEqual({ 'Opening range': { interval: '15m', chartType: 'candlestick', symbol: 'INFY' } });

  // A reload reopens it.
  await page.reload();
  await ready(page);
  await expect(label(page)).toHaveText('Opening range');
  await expect.poll(() => chart(page).then(c => c.interval)).toBe('15m');

  // Another symbol, then reopening the saved version asks first.
  await page.locator('.oac-sym__input').fill('TCS');
  await page.locator('.oac-sym__input').press('Enter');
  await expect.poll(() => chart(page).then(c => c.symbol)).toBe('TCS');
  await openMenu(page);
  await menu(page).locator('[data-list="recent"] .oac-layouts__row').first().click();
  const confirm = menu(page).locator('.oac-layouts__confirm');
  await expect(confirm).toBeVisible();
  await expect(confirm.locator('.oac-layouts__confirm-text')).toHaveText('Opening range has unsaved changes. Open the saved version?');
  await info.attach('asking before a change is dropped', { body: await page.screenshot(), contentType: 'image/png' });
  // By keyboard: the question takes the focus, and gives it back to the row it
  // asked about rather than to the page. (A click in WebKit does not focus a
  // button, so the keys are the path every engine shares.)
  await expect(confirm.locator('[data-action="stay"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(confirm).toBeHidden();
  await expect(menu(page).locator('[data-list="recent"] .oac-layouts__row').first()).toBeFocused();
  expect((await chart(page)).symbol).toBe('TCS');
  await menu(page).locator('[data-list="recent"] .oac-layouts__row').first().click();
  await confirm.locator('[data-action="discard"]').click();
  await expect(menu(page)).toHaveCount(0);
  await expect.poll(() => chart(page)).toMatchObject({ symbol: 'INFY', interval: '15m' });
  expect(errors).toEqual([]);
});

test('a second tab that saved the held layout meanwhile is a conflict, settled with a copy and with an overwrite', async ({ page, context }, info) => {
  const errors = await mount(page);
  await openMenu(page);
  await saveAs(page, 'Desk', 'save');
  await page.keyboard.press('Escape');

  // The second tab reopens Desk, and saves it on a line chart.
  const other = await context.newPage();
  const otherErrors = await mount(other);
  await expect(label(other)).toHaveText('Desk');
  await pickChartType(other, 'Line');
  await openMenu(other);
  await menu(other).locator('[data-action="save"]').click();
  await expect(menu(other).locator('.oac-layouts__line')).toHaveText(/^Saved /);

  // This tab changes Desk too. The menu reads the list again as it opens,
  // finds Desk changed elsewhere, and saves nothing over it.
  await page.locator('.oac-pills button[data-interval="1h"]').click();
  await openMenu(page);
  const conflict = menu(page).locator('.oac-layouts__conflict');
  await expect(conflict).toBeVisible();
  await expect(conflict).toHaveAttribute('role', 'alert');
  await expect(conflict.locator('.oac-layouts__conflict-text')).toHaveText('Desk was changed in another window. This chart is not saved over it.');
  await expect(menu(page).locator('[data-action="save"]')).toHaveAttribute('aria-disabled', 'true');
  await info.attach('conflict with another tab', { body: await page.screenshot(), contentType: 'image/png' });

  // A copy keeps both versions.
  await conflict.locator('[data-action="copy"]').click();
  await expect(menu(page).locator('.oac-layouts__input')).toHaveValue('Desk copy');
  await menu(page).locator('[data-action="submit-name"]').click();
  await expect(menu(page).locator('.oac-layouts__name')).toHaveText('Desk copy');
  await expect(conflict).toBeHidden();
  expect(await stored(page)).toEqual({
    Desk: { interval: '5m', chartType: 'line', symbol: 'INFY' },
    'Desk copy': { interval: '1h', chartType: 'candlestick', symbol: 'INFY' },
  });

  // The other tab changes Desk again; this tab reopens Desk and overwrites it.
  await page.keyboard.press('Escape');
  await openMenu(page);
  await menu(page).locator('.oac-layouts__row', { hasText: /^Desk/ }).filter({ hasNotText: 'copy' }).click();
  await expect.poll(() => chart(page)).toMatchObject({ interval: '5m', chartType: 'line' });
  await other.locator('.oac-pills button[data-interval="15m"]').click();
  await other.locator('.oac-topbar__layouts').click();
  await menu(other).locator('[data-action="save"]').click();
  await expect(menu(other).locator('.oac-layouts__line')).toHaveText(/^Saved /);
  await pickChartType(page, 'Bars');
  await openMenu(page);
  await expect(conflict).toBeVisible();
  await conflict.locator('[data-action="overwrite"]').click();
  await expect(conflict).toBeHidden();
  await expect(menu(page).locator('.oac-layouts__line')).toHaveText(/^Saved /);
  expect((await stored(other)).Desk).toEqual({ interval: '5m', chartType: 'bar', symbol: 'INFY' });
  expect([...errors, ...otherErrors]).toEqual([]);
});

test('autosave writes each change and the chart comes back after a reload', async ({ page }) => {
  const errors = await mount(page);
  await openMenu(page);
  await saveAs(page, 'Auto', 'save');
  const toggle = menu(page).locator('[data-action="autosave"]');
  await expect(toggle).toHaveAttribute('role', 'switch');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await expect(menu(page).locator('.oac-layouts__autosave-state')).toHaveText('Saved');
  await page.keyboard.press('Escape');
  await page.locator('.oac-pills button[data-interval="1h"]').click();
  await pickChartType(page, 'Area');
  await expect.poll(() => stored(page).then(s => s.Auto), { timeout: 10_000 }).toEqual({ interval: '1h', chartType: 'area', symbol: 'INFY' });
  await page.reload();
  await ready(page);
  await expect.poll(() => chart(page)).toMatchObject({ interval: '1h', chartType: 'area' });
  await expect(label(page)).toHaveText('Auto');
  expect(errors).toEqual([]);
});

test('applies an indicator template from the picker, and one undo and redo walk it', async ({ page }, info) => {
  const errors = await mount(page);
  await page.locator('.oac-topbar button[aria-label="Indicators"]').click();
  const picker = page.locator('.oac-pick');
  for (const id of ['rsi', 'macd']) {
    await picker.getByRole('searchbox', { name: 'Search indicators' }).fill(id);
    await picker.locator(`.oac-pick__list [role="option"][data-id="${id}"]`).click();
  }
  await picker.locator('[data-action="templates"]').click();
  const templates = page.locator('.oac-templates');
  await expect(templates).toBeVisible();
  await templates.locator('[data-action="save-template"]').click();
  await page.locator('.oac-template-name__input').fill('Oscillators');
  await page.locator('.oac-template-name [data-action="save-template"]').click();
  await expect(page.locator('.oac-template-name')).toHaveCount(0);
  await expect(templates.locator('.oac-templates__row')).toHaveCount(1);
  await expect(templates.locator('.oac-templates__meta')).toHaveText('2 studies');
  await page.keyboard.press('Escape');
  await expect(templates).toHaveCount(0);

  // The studies go, a moving average takes their place.
  for (let i = 0; i < 2; i++) await picker.locator('.oac-pick__running .oac-pick__remove').first().click();
  await picker.getByRole('searchbox', { name: 'Search indicators' }).fill('sma');
  await picker.locator('.oac-pick__list [role="option"][data-id="sma"]').click();
  await expect.poll(() => chart(page).then(c => c.studies)).toEqual(['sma']);

  await picker.locator('[data-action="templates"]').click();
  await templates.locator('.oac-templates__row', { hasText: 'Oscillators' }).locator('[data-action="replace"]').click();
  await expect(templates).toHaveCount(0);
  await expect.poll(() => chart(page).then(c => c.studies)).toEqual(['rsi', 'macd']);
  await expect(page.locator('.oac-toast', { hasText: 'Applied Oscillators' })).toBeVisible();
  await picker.getByRole('button', { name: 'Done', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__widget.chart.panes().length)).toBe(3);
  await info.attach('template applied', { body: await page.screenshot(), contentType: 'image/png' });

  // One undo takes the template back, one redo puts it on again.
  const box = await page.locator('.oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.3);
  await page.keyboard.press('ControlOrMeta+z');
  await expect.poll(() => chart(page).then(c => c.studies)).toEqual(['sma']);
  expect(await page.evaluate(() => (window as any).__widget.chart.panes().length)).toBe(1);
  await page.keyboard.press('ControlOrMeta+y');
  await expect.poll(() => chart(page).then(c => c.studies)).toEqual(['rsi', 'macd']);

  // Append puts a copy beside them, in panes of its own.
  await page.locator('.oac-topbar button[aria-label="Indicators"]').click();
  await picker.locator('[data-action="templates"]').click();
  await templates.locator('.oac-templates__row', { hasText: 'Oscillators' }).locator('[data-action="append"]').click();
  await expect.poll(() => chart(page).then(c => c.studies)).toEqual(['rsi', 'macd', 'rsi', 'macd']);
  expect(errors).toEqual([]);
});

for (const theme of ['dark', 'light'] as const) {
  test(`opens from the More sheet on a phone, ${theme}`, async ({ page }, info) => {
    const errors = await mount(page, `?phone&theme=${theme}`, 390, 780);
    await page.locator('.oac-mobile__action[data-mobile-action="more"]').click();
    await page.locator('.oac-mobile-sheet [data-mobile-action="layouts"]').click();
    await expect(page.locator('.oac-mobile-sheet')).toHaveCount(0);
    await expect(menu(page)).toBeVisible();
    await expect(menu(page)).toHaveAttribute('aria-modal', 'true');
    await saveAs(page, 'Phone', 'save');
    const box = await menu(page).boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    const row = menu(page).locator('.oac-layouts__row').first();
    expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await info.attach(`phone layouts menu, ${theme}`, { body: await page.screenshot(), contentType: 'image/png' });
    expect(errors).toEqual([]);
  });
}

test('the menu and the templates list are styled under a strict stylesheet policy', async ({ page }) => {
  const NONCE = 'openalgo-layouts-csp-test';
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.addInitScript(() => {
    (window as any).__cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => { (window as any).__cspViolations.push(event.effectiveDirective); });
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.route('**/widget-layouts-csp.html', route => route.fulfill({
    contentType: 'text/html',
    headers: { 'Content-Security-Policy': `default-src 'self'; script-src 'self'; style-src-elem 'nonce-${NONCE}'; style-src-attr 'unsafe-inline'; img-src 'self' data:` },
    body: `<!doctype html><html><head><meta charset="utf-8"><style nonce="${NONCE}">body{margin:0;background:#0d0e12}#t{width:1200px;height:680px}</style></head><body><div id="t"></div></body></html>`,
  }));
  await page.goto('/widget-layouts-csp.html');
  await page.evaluate(async nonce => {
    const { createWidget } = await import('/dist/openalgo-charts.widget.mjs');
    await import('/dist/openalgo-charts.indicators.mjs');
    const { WorkspaceRepository, createMemoryWorkspaceStorage } = await import('/dist/openalgo-charts.workspace.mjs');
    // A seeded random walk, as every chart a person sees.
    let seed = 7, close = 1486.4;
    const bars = Array.from({ length: 200 }, (_, i) => {
      seed = (seed * 16807) % 2147483647;
      const open = close;
      close = Math.round((open + (seed / 2147483647 - 0.5) * 6) * 20) / 20;
      return { time: 1_700_000_000 + i * 300, open, high: Math.max(open, close) + 0.6, low: Math.min(open, close) - 0.6, close, volume: 40_000 + (seed % 9000) };
    });
    const workspaces = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk');
    const widget = createWidget(document.getElementById('t'), { styleNonce: nonce, symbol: 'INFY', exchange: 'NSE', interval: '5m', workspaces });
    widget.series.setData(bars);
    widget.chart.addIndicator('rsi');
    (window as any).__widget = widget;
  }, NONCE);
  await openMenu(page);
  await expect(menu(page).locator('.oac-layouts__current')).toHaveCSS('display', 'grid');
  await expect(menu(page).locator('.oac-layouts__track')).toHaveCSS('border-radius', '999px');
  await saveAs(page, 'Strict', 'save');
  await expect(menu(page).locator('.oac-layouts__row').first()).toHaveCSS('display', 'flex');
  await page.keyboard.press('Escape');
  await page.locator('.oac-topbar button[aria-label="Indicators"]').click();
  await page.locator('.oac-pick [data-action="templates"]').click();
  await expect(page.locator('.oac-templates')).toHaveCSS('display', 'flex');
  expect(await page.evaluate(() => (window as any).__cspViolations)).toEqual([]);
  expect(errors).toEqual([]);
});
