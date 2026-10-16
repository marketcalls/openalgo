import { test, expect, type Page } from '@playwright/test';

// The reference host's grid view over the fixture server: four instruments,
// the grid bar's layouts, links and link groups, maximize, saved desks, the
// bar under the charts and persistence, and the hand-off from the main page
// of a layout whose geometry only the grid view can draw.
const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;

test.use({ viewport: { width: 1360, height: 900 } });
test.beforeEach(async ({ request }) => {
  const up = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
});

const grid = <T>(page: Page, fn: (grid: any) => T): Promise<T> =>
  page.evaluate(`(${fn.toString()})(window.__grid)`) as Promise<T>;
const loaded = (page: Page): Promise<boolean> => grid(page, g => g.cells().every((cell: any) => cell.widget.series.getData().length > 0));
/**
 * The grid's saved desk, read from the widget's IndexedDB store, or written
 * there with `value`: the store the grid persists through by default.
 */
const savedGrid = (page: Page, value?: string): Promise<string | null> => page.evaluate(value => new Promise<string | null>((resolve, reject) => {
  const open = indexedDB.open('openalgo-charts-widget', 1);
  open.onupgradeneeded = () => { if (!open.result.objectStoreNames.contains('entries')) open.result.createObjectStore('entries'); };
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result;
    const tx = db.transaction('entries', value === undefined ? 'readonly' : 'readwrite');
    const store = tx.objectStore('entries');
    const request = value === undefined ? store.get('oac-widget:yfinance-grid:grid') : store.put(value, 'oac-widget:yfinance-grid:grid');
    let result: string | null = null;
    request.onsuccess = () => { result = value === undefined ? (request.result as string | undefined) ?? null : value; };
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onabort = () => { db.close(); reject(tx.error); };
  };
}), value);
/** Whether a main page chart's window reaches its newest bar, rather than bars it does not have. */
const onNewest = (page: Page, key: string): Promise<boolean> => page.evaluate(name => {
  const chart = (window as any).__oac.app[name];
  const count = chart.primaryBars().length, range = chart.getVisibleLogicalRange();
  return count > 1 && range.from < count - 1 && range.to >= count - 1;
}, key);

/** Pick a layout from the grid bar's picker by its name. */
async function pickLayout(page: Page, name: string): Promise<void> {
  await page.locator('.oac-grid__layout').click();
  await page.getByRole('menu', { name: 'Arrange charts' }).getByRole('menuitemradio', { name, exact: true }).click();
}
const layoutText = (page: Page) => page.locator('.oac-grid__layout .oac-grid__bar-text');

test('the grid view loads four instruments, switches layouts and links from the grid bar, and keeps them across a reload', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  expect(await grid(page, g => g.cells().map((cell: any) => cell.widget.symbol()))).toEqual(['AAPL', 'MSFT', 'RELIANCE.NS', '^NSEI']);
  await expect(layoutText(page)).toHaveText('Two by two');
  // The page's own bar keeps the file and the way back; the grid bar has the rest.
  await expect(page.locator('#grid-presets, #grid-links')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('yfinance-grid-2x2.png') });

  await page.locator('.oac-grid__cell .oac-chart').nth(1).click();
  await pickLayout(page, 'Two columns');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(2);
  await expect(layoutText(page)).toHaveText('Two columns');
  await expect(page.locator('#grid-status')).toContainText('Two columns: 2 charts');
  await page.locator('.oac-grid__link').click();
  const symbol = page.getByRole('menu', { name: 'Linking' }).getByRole('menuitemcheckbox', { name: 'Symbol' });
  await symbol.click();
  await expect(symbol).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape');
  await expect.poll(() => grid(page, g => g.cells().map((cell: any) => cell.widget.symbol()))).toEqual(['MSFT', 'MSFT']);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);

  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 2);
  expect(await grid(page, g => g.cells().map((cell: any) => cell.widget.symbol()))).toEqual(['MSFT', 'MSFT']);
  expect(await grid(page, g => g.linkOptions().symbol)).toBe(true);
  await expect(layoutText(page)).toHaveText('Two columns');
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.screenshot({ path: info.outputPath('yfinance-grid-restored.png') });

  // A reload straight after a change keeps it: nothing waits on a timer or on unload.
  await pickLayout(page, 'Three columns');
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length > 0);
  expect(await grid(page, g => g.cells().length)).toBe(3);
  expect(errors).toEqual([]);
});

test('the grid view offers every layout to sixteen charts, names it with its glyph, and keeps link groups and a maximized view apart', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.locator('.oac-grid__layout').click();
  await expect(page.getByRole('menu', { name: 'Arrange charts' }).getByRole('menuitemradio')).toHaveCount(26);
  await page.keyboard.press('Escape');

  // An uneven layout: the status line names it with the library's own glyph.
  await pickLayout(page, 'Large corner, five around');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(6);
  await expect(page.locator('#grid-status')).toContainText('Large corner, five around: 6 charts');
  await expect(page.locator('#grid-glyph svg path')).toHaveCount(1);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  const big = (await page.locator('.oac-grid__cell').nth(0).boundingBox())!;
  const small = (await page.locator('.oac-grid__cell').nth(1).boundingBox())!;
  expect(big.width).toBeGreaterThan(small.width * 1.8);
  await page.screenshot({ path: info.outputPath('yfinance-grid-corner-5.png') });

  // Two link groups: the third chart starts its own, linked by symbol, and the fourth joins it.
  await grid(page, g => g.setActive(g.cells()[2].id));
  await page.locator('.oac-grid__link').click();
  const menu = page.getByRole('menu', { name: 'Linking' });
  await menu.getByRole('menuitem', { name: 'New group' }).click();
  await menu.getByRole('menuitemcheckbox', { name: 'Symbol' }).click();
  await page.keyboard.press('Escape');
  await grid(page, g => g.setLinkGroup(g.cells()[3].id, g.linkGroups()[1].id));
  await expect(page.locator('.oac-grid__mark').nth(2)).toHaveText('B');
  await expect.poll(() => grid(page, g => g.cells().map((cell: any) => cell.linkGroup))).toEqual(['a', 'a', 'b', 'b', 'a', 'a']);
  await expect.poll(() => grid(page, g => g.cells()[3].widget.symbol() === g.cells()[2].widget.symbol())).toBe(true);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.screenshot({ path: info.outputPath('yfinance-grid-groups.png') });

  // Maximize is a view: it shows one chart with its full chrome, and a reload opens the grid as it is.
  await page.locator('.oac-grid__max').click();
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(1);
  await expect(page.locator('.oac-grid__cell:visible')).toHaveAttribute('data-dense', 'false');
  await page.screenshot({ path: info.outputPath('yfinance-grid-maximized.png') });
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 6);
  expect(await grid(page, g => [g.maximized(), g.layout().preset, g.linkGroups().map((group: any) => group.cells.length)]))
    .toEqual([null, 'corner-5', [4, 2]]);
  await expect(page.locator('.oac-grid__cell:visible')).toHaveCount(6);

  // Sixteen charts fit the page: each keeps a plot, not a wrapped bar.
  await pickLayout(page, 'Four by four');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(16);
  await expect(page.locator('#grid-status')).toContainText('Four by four: 16 charts');
  await expect.poll(() => loaded(page), { timeout: 30_000 }).toBe(true);
  const plots = await page.locator('.oac-grid__cell .oac-chart').evaluateAll(els => els.map(el => el.clientHeight));
  for (const height of plots) expect(height).toBeGreaterThan(90);
  await page.screenshot({ path: info.outputPath('yfinance-grid-4x4.png') });
  expect(errors).toEqual([]);
});

test('the grid view has one bar under the charts for the active one, and keeps saved desks in its grid bar', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  const bar = page.locator('.oac-grid__foot .oac-bottombar');
  await expect(bar).toBeVisible();
  await expect(page.locator('.oac-grid__cell .oac-topbar__goto')).toHaveCount(0);
  // The status is the active chart's: AAPL first, then the NSE chart after a click.
  await expect(bar.locator('.oac-bottombar__status')).toBeVisible();
  await page.locator('.oac-grid__cell .oac-chart').nth(2).click();
  await bar.locator('.oac-bottombar__range[data-range="1Y"]').click();
  await expect.poll(() => grid(page, g => g.cells().map((cell: any) => cell.widget.range()))).toEqual([null, null, '1Y', null]);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.screenshot({ path: info.outputPath('yfinance-grid-bottom-bar.png') });

  await page.locator('.oac-grid__saved').click();
  const menu = page.locator('.oac-grid__overlay .oac-layouts');
  await expect(menu).toBeVisible();
  await menu.locator('[data-action="save-as"]').click();
  await menu.locator('.oac-layouts__input').fill('Four markets');
  await menu.locator('[data-action="submit-name"]').click();
  await expect(page.locator('.oac-grid__saved')).toHaveText('Four markets');
  await page.screenshot({ path: info.outputPath('yfinance-grid-layouts.png') });
  await page.keyboard.press('Escape');
  await pickLayout(page, 'Two columns');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(2);
  // The grid's own desk comes back with two charts, then the layout that was active opens over it.
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid !== undefined);
  await expect.poll(() => grid(page, g => g.cells().map((cell: any) => cell.widget.symbol())), { timeout: 20_000 })
    .toEqual(['AAPL', 'MSFT', 'RELIANCE.NS', '^NSEI']);
  await expect(page.locator('.oac-grid__saved')).toHaveText('Four markets');
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  expect(errors).toEqual([]);
});

test('the grid view lets a chart put its price pane below a study, and a reload keeps it there', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  // The grid view opts in, as the main page does, so a layout either one saves opens in the other.
  expect(await grid(page, g => g.cells().map((cell: any) => cell.widget.chart.movablePrimaryPane()))).toEqual([true, true, true, true]);
  await grid(page, g => { g.cells()[0].widget.chart.addIndicator('rsi'); });
  const box = await grid(page, g => {
    const r = g.cells()[0].widget.chart.panes()[0].element.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  await page.mouse.click(box.x, box.y, { button: 'right' });
  const row = page.locator('.oac-ctx__row[data-act="pane-down"]');
  await expect(row).toBeVisible();
  await expect(row).not.toHaveAttribute('aria-disabled', 'true');
  await row.click();
  await expect.poll(() => grid(page, g => g.cells()[0].widget.chart.primaryPaneIndex())).toBe(1);
  await expect.poll(() => grid(page, g => g.cells()[0].widget.chart.indicators()[0].paneIndex)).toBe(0);
  await page.screenshot({ path: info.outputPath('yfinance-grid-price-below.png') });
  await expect.poll(async () => JSON.parse((await savedGrid(page)) ?? '{}').panes?.[0].chart.primaryPane).toBe(1);
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  expect(await grid(page, g => g.cells()[0].widget.chart.primaryPaneIndex())).toBe(1);
  expect(await grid(page, g => g.cells()[0].widget.chart.indicators().map((item: any) => [item.indicatorId, item.paneIndex]))).toEqual([['rsi', 0]]);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.screenshot({ path: info.outputPath('yfinance-grid-price-below-reloaded.png') });
  expect(errors).toEqual([]);
});

test('the grid view offers the in-chart transforms in the chart type menu, and a reload keeps the one picked', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await page.locator('.oac-topbar__type').first().click();
  const menu = page.getByRole('menu', { name: 'Chart type' });
  await expect(menu.getByText('Transforms', { exact: true })).toBeVisible();
  await menu.getByRole('menuitemradio', { name: 'Renko', exact: true }).click();
  const renko = (): Promise<number[]> => grid(page, g => g.cells().flatMap((cell: any, i: number) =>
    cell.widget.chartType() === 'renko' && cell.widget.chart.seriesTransform(cell.widget.series)?.type === 'renko' ? [i] : []));
  await expect.poll(renko).toHaveLength(1);
  const [index] = await renko();
  // The chart forms the bricks from the fed bars itself.
  expect(await grid(page, g => g.cells().map((cell: any) => cell.widget.chart.primaryBars().length))).not.toContain(0);
  await page.screenshot({ path: info.outputPath('yfinance-grid-renko.png') });
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  await expect.poll(renko).toEqual([index]);
  expect(errors).toEqual([]);
});

test('a saved grid the page cannot restore is kept and reported, not overwritten', async ({ page }) => {
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  const text = await page.evaluate(() => {
    const payload = (window as any).__grid.getWorkspace();
    payload.panes[0].chart.indicators = [{ indicatorId: 'registered-later', settings: {}, paneIndex: 0 }];
    (window as any).__grid.destroy();
    return JSON.stringify(payload);
  });
  // The grid's last writes may still queue behind one in flight; its unload
  // journal is dropped once they have all landed, and only then is this
  // write the last one.
  await expect.poll(() => page.evaluate(() => localStorage.getItem('oac-widget-journal:yfinance-grid'))).toBeNull();
  await savedGrid(page, text);
  await page.reload();
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await expect(page.locator('#grid-status')).toContainText('could not be restored');
  await expect(page.locator('#grid-status')).toContainText('registered-later');
  await expect.poll(() => loaded(page), { timeout: 20_000 }).toBe(true);
  expect(await savedGrid(page)).toBe(text);
});

const handPane = (id: string, symbol: string, historyPeriod?: string) => ({ id, symbol, exchange: '', interval: '1d', chartType: 'candlestick',
  chart: { version: 1 }, settings: {}, volume: true, magnet: 'off', stay: false, comparisons: [] as unknown[], comparisonMode: 'percent',
  ...(historyPeriod === undefined ? {} : { historyPeriod }) });
const deskOf = (panes: ReturnType<typeof handPane>[]) => ({ kind: 'workspace', version: 1, id: 'desk', name: 'Desk', createdAt: 1, updatedAt: 1,
  panes, activePaneId: panes[2].id,
  layout: { rows: 2, columns: 2, slots: panes.map((pane, i) => ({ paneId: pane.id, row: Math.floor(i / 2), column: i % 2, rowSpan: 1, columnSpan: 1 })) },
  sync: { crosshair: true, viewport: false, symbol: false, interval: false } });

test('the main page refuses, before leaving, a layout the grid view could not open', async ({ page }) => {
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  const panes = [handPane('a', 'AAPL'), handPane('b', 'MSFT'), handPane('c', 'TSLA'), handPane('d', 'NVDA')];
  panes[1].comparisons = [{ id: 'q', symbol: 'QQQ', exchange: '', visible: true }];
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await page.locator('#ws-file').setInputFiles({ name: 'compared.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(deskOf(panes))) });
  await expect(page.locator('#ws-error')).toContainText('MSFT: comparison symbols');
  await expect(page.getByRole('button', { name: 'Open in grid view' })).toBeHidden();
  expect(page.url()).toContain('index.html');
});

test('the main page hands a layout it cannot draw to the grid view, which opens it whole', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // The grid view's own saved desk, which the hand-off replaces before any of its charts loads.
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await page.evaluate(() => { for (const cell of (window as any).__grid.cells()) cell.widget.setSymbol('IBM'); });
  await expect.poll(() => grid(page, g => g.cells().every((cell: any) => cell.widget.series.getData().length > 0 && cell.widget.symbol() === 'IBM')), { timeout: 20_000 }).toBe(true);
  const asked: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === '/api/history') asked.push(`${url.searchParams.get('symbol')}:${url.searchParams.get('period')}`);
  });
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  const desk = deskOf([handPane('a', 'AAPL'), handPane('b', 'MSFT', 'max'), handPane('c', 'TSLA', '6mo'), handPane('d', 'NVDA')]);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await page.locator('#ws-file').setInputFiles({ name: 'desk.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(desk)) });
  await expect(page.locator('#ws-notice')).toContainText('grid view');
  await page.screenshot({ path: info.outputPath('yfinance-grid-handoff.png') });
  await page.getByRole('button', { name: 'Open in grid view' }).click();
  await page.waitForURL(/grid\.html/);
  await expect(page.locator('.oac-grid__cell')).toHaveCount(4);
  await expect(page.locator('#grid-status')).toContainText('Opened the layout from the main view: 4 charts');
  await expect(page.locator('.oac-grid__cell').nth(2)).toHaveAttribute('data-active', 'true');
  // Each chart loads the history period the layout saved, or its interval's usual one: a
  // daily chart saved over six months is under 500 candles, so it loads five years too.
  await expect.poll(() => ['MSFT:max', 'TSLA:5y', 'NVDA:5y'].every(ask => asked.includes(ask)), { timeout: 20_000 }).toBe(true);
  expect(asked).not.toContain('TSLA:6mo');
  await expect(page.locator('.oac-grid__cell .oac-data-status').first()).not.toContainText('Loading');
  await page.screenshot({ path: info.outputPath('yfinance-grid-opened.png') });
  // The saved IBM desk was built first and then replaced. A feed that started
  // its requests before the hand-off was applied would have sent IBM here.
  expect(asked.filter(ask => ask.startsWith('IBM:'))).toEqual([]);
  // The periods stay with the charts, so the saved grid and an exported layout carry them back.
  await expect.poll(async () => JSON.parse((await savedGrid(page))!).panes
    .map((pane: { historyPeriod?: string }) => pane.historyPeriod ?? null)).toEqual([null, 'max', '6mo', null]);
  expect(errors).toEqual([]);
});

test('a hand-off from the main page is not replaced by the saved desk that was open', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // A saved desk held as the open layout, which a plain reload of the grid view opens again.
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await page.locator('.oac-grid__saved').click();
  const menu = page.locator('.oac-grid__overlay .oac-layouts');
  await menu.locator('[data-action="save-as"]').click();
  await menu.locator('.oac-layouts__input').fill('Four markets');
  await menu.locator('[data-action="submit-name"]').click();
  await expect(page.locator('.oac-grid__saved')).toHaveText('Four markets');
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  const desk = deskOf([handPane('a', 'AAPL'), handPane('b', 'MSFT'), handPane('c', 'TSLA'), handPane('d', 'NVDA')]);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await page.locator('#ws-file').setInputFiles({ name: 'desk.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(desk)) });
  await page.getByRole('button', { name: 'Open in grid view' }).click();
  await page.waitForURL(/grid\.html/);
  await expect(page.locator('#grid-status')).toContainText('Opened the layout from the main view: 4 charts');
  // The menu lists the saved desk once its store has been read, which is when
  // the desk that was open would be opened again; give that time to land.
  await page.locator('.oac-grid__saved').click();
  await expect(menu.locator('.oac-layouts__row-name', { hasText: 'Four markets' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1500);
  // The page was opened by the hand-off, without the test hook, so the charts are read from their symbol boxes.
  expect(await page.locator('.oac-grid__cell').getByRole('textbox', { name: 'Symbol' }).evaluateAll(boxes => boxes.map(box => (box as HTMLInputElement).value)))
    .toEqual(['AAPL', 'MSFT', 'TSLA', 'NVDA']);
  await expect(page.locator('.oac-grid__saved')).toHaveText('Layouts');
  expect(errors).toEqual([]);
});

test('a one or two chart layout the grid view exports opens on the main page', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(ORIGIN + '/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  await pickLayout(page, 'Two columns');
  await expect(page.locator('.oac-grid__cell')).toHaveCount(2);
  await page.evaluate(() => (window as any).__grid.cells()[0].widget.setInterval('1w'));
  const pending = page.waitForEvent('download');
  await page.locator('#grid-export').click();
  const file = await (await pending).path();
  if (!file) throw new Error('Export did not create a file');
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await page.locator('#ws-file').setInputFiles(file);
  await expect(page.locator('#ws-current')).toHaveText('Current: Chart grid');
  // The widget's weekly code opens as the page's own, beside the second chart, which
  // saved no period and so opens on the daily five years.
  await expect.poll(() => page.evaluate(() => {
    const app = (window as any).__oac.app;
    return app.chart2 && !app.workspaceLoading ? { primary: app.req, secondary: { symbol: app.p2.symbol, interval: app.p2.interval, period: app.p2.period } } : null;
  }), { timeout: 20_000 }).toEqual({ primary: { symbol: 'AAPL', interval: '1wk', period: '1y' }, secondary: { symbol: 'MSFT', interval: '1d', period: '5y' } });
  // Each chart shows its newest bars, not an empty plot: the grid view's window counted other bars.
  await page.getByRole('button', { name: 'Close', exact: true }).first().click();
  for (const key of ['chart', 'chart2']) await expect.poll(() => onNewest(page, key), { timeout: 20_000 }).toBe(true);
  await page.screenshot({ path: info.outputPath('yfinance-grid-export-main.png') });
  expect(errors).toEqual([]);
});
