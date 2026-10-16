import { test, expect, type Page } from '@playwright/test';
import { VERSION } from '../../src/version';

// The widget keeps its layout in IndexedDB by default. In a real browser: a
// layout survives a reload, and the reload asks the feed for the saved
// instrument alone, never the default first; a layout an earlier release
// left in localStorage is copied in once; the last change before the page
// goes away survives through the journal when IndexedDB does not commit it;
// and a host that passes localStorage keeps it.

async function mount(page: Page, query: string, width = 1200): Promise<void> {
  await page.setViewportSize({ width, height: 760 });
  await page.goto(`/tests/e2e/widget-storage-fixture.html?${query}`);
  await page.waitForFunction(version => {
    const f = (window as any).fixture;
    return f?.version === version && f.ready && f.loaded() > 0;
  }, VERSION);
}

const facts = (page: Page) => page.evaluate(() => {
  const w = (window as any).fixture.widget;
  return { symbol: w.symbol(), interval: w.interval(), theme: w.theme(), studies: w.chart.indicators().map((i: any) => i.indicatorId) };
});

const requests = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).fixture.requests.slice());
const records = (page: Page): Promise<Record<string, string>> => page.evaluate(() => (window as any).fixture.records());
const localKeys = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).fixture.localKeys());
const drawings = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).fixture.drawings());
const stored = async (page: Page, key: string): Promise<any> => {
  const text = (await records(page))[key];
  return text === undefined ? undefined : JSON.parse(text);
};

/** Magenta pixels on the chart's canvases: the support line is the only magenta on screen. */
const magenta = (page: Page): Promise<number> => page.evaluate(() => {
  let count = 0;
  for (const canvas of document.querySelectorAll('.oac-widget .oac-chart canvas')) {
    const c = canvas as HTMLCanvasElement;
    if (c.width === 0 || c.height === 0) continue;
    const { data } = c.getContext('2d')!.getImageData(0, 0, c.width, c.height);
    for (let p = 0; p < data.length; p += 4) if (data[p + 3] > 120 && data[p] > 180 && data[p + 1] < 90 && data[p + 2] > 180) count++;
  }
  return count;
});

test('a layout survives a reload on IndexedDB, and the reload asks the feed for the saved instrument alone', async ({ page }, info) => {
  await mount(page, 'ns=desk&symbol=INFY');
  // Out of sight and asking for nothing until the store has answered.
  expect(await page.evaluate(() => [(window as any).fixture.hiddenAtStart, (window as any).fixture.requestsAtStart])).toEqual([true, 0]);
  await page.locator('.oac-topbar [data-interval="15m"]').click();
  await expect.poll(() => requests(page)).toEqual(['INFY 1d', 'INFY 15m']);
  await page.waitForFunction(() => (window as any).fixture.loaded() > 0 && (window as any).fixture.widget.series.getData()[1].time - (window as any).fixture.widget.series.getData()[0].time === 900);
  await page.locator('.oac-topbar .oac-topbar__theme').click();
  const line = await page.evaluate(() => (window as any).fixture.drawSupport());
  await page.evaluate(() => (window as any).fixture.widget.chart.addIndicator('sma', { length: 20 }));
  await expect.poll(async () => (await stored(page, 'oac-widget:desk:state'))?.theme).toBe('light');
  expect((await stored(page, 'oac-widget:desk:state')).interval).toBe('15m');
  await expect.poll(async () => (await stored(page, 'oac-widget:desk:drawings:NSE:INFY'))?.drawings?.length).toBe(1);
  // Nothing of the layout in the page's localStorage.
  expect(await localKeys(page)).toEqual([]);

  // The next visit names no symbol: it opens on the saved one.
  await mount(page, 'ns=desk');
  expect(await requests(page)).toEqual(['INFY 15m']);
  expect(await facts(page)).toEqual({ symbol: 'INFY', interval: '15m', theme: 'light', studies: ['sma'] });
  expect(await drawings(page)).toEqual([line]);
  await expect.poll(() => magenta(page)).toBeGreaterThan(150);
  await page.screenshot({ path: info.outputPath('restored-light-desktop.png') });
});

test('a layout an earlier release left in localStorage opens from IndexedDB, copied in once', async ({ page }, info) => {
  // Saved over localStorage, the way every release before this one saved it.
  await mount(page, 'ns=legacy&symbol=TCS&storage=local');
  expect(await page.evaluate(() => (window as any).fixture.hiddenAtStart)).toBe(false);
  await page.locator('.oac-topbar [data-interval="1h"]').click();
  await expect.poll(() => requests(page)).toEqual(['TCS 1d', 'TCS 1h']);
  await page.waitForFunction(() => (window as any).fixture.widget.series.getData().length > 0
    && (window as any).fixture.widget.series.getData()[1].time - (window as any).fixture.widget.series.getData()[0].time === 3600);
  const line = await page.evaluate(() => (window as any).fixture.drawSupport());
  await page.evaluate(() => (window as any).fixture.widget.destroy());
  const legacy = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage)
    .filter(k => k.startsWith('oac-widget:legacy:')).map(k => [k, localStorage.getItem(k)])));
  expect(Object.keys(legacy).sort()).toEqual(['oac-widget:legacy:drawings:NSE:TCS', 'oac-widget:legacy:state']);
  expect(Object.keys(await records(page)).filter(k => k.startsWith('oac-widget:legacy:'))).toEqual([]);

  // The default store now: IndexedDB, empty for this namespace.
  await mount(page, 'ns=legacy');
  expect(await requests(page)).toEqual(['TCS 1h']);
  expect(await facts(page)).toMatchObject({ symbol: 'TCS', interval: '1h', theme: 'dark' });
  expect(await drawings(page)).toEqual([line]);
  await expect.poll(() => magenta(page)).toBeGreaterThan(150);
  const copied = await records(page);
  for (const [key, value] of Object.entries(legacy)) expect(copied[key]).toBe(value);
  // Left in place for an earlier release, and not copied over newer work again.
  expect(await localKeys(page)).toEqual(Object.keys(legacy).sort());
  await page.locator('.oac-topbar [data-interval="5m"]').click();
  await expect.poll(async () => (await stored(page, 'oac-widget:legacy:state'))?.interval).toBe('5m');
  await mount(page, 'ns=legacy');
  expect(await facts(page)).toMatchObject({ symbol: 'TCS', interval: '5m' });
  await page.screenshot({ path: info.outputPath('migrated-dark-desktop.png') });
});

test('the last change before the page goes away survives through the journal when IndexedDB does not commit it', async ({ page }) => {
  await mount(page, 'ns=journal&symbol=RELIANCE');
  await page.locator('.oac-topbar [data-interval="5m"]').click();
  await expect.poll(async () => (await stored(page, 'oac-widget:journal:state'))?.interval).toBe('5m');
  // Every IndexedDB write on this page hangs, as one started while a page unloads can.
  await mount(page, 'ns=journal&stall');
  expect(await requests(page)).toEqual(['RELIANCE 5m']);
  await page.locator('.oac-topbar [data-interval="15m"]').click();
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })));
  const journal = await page.evaluate(() => JSON.parse(localStorage.getItem('oac-widget-journal:journal') ?? 'null'));
  expect(JSON.parse(journal.entries['oac-widget:journal:state']).interval).toBe('15m');
  expect((await stored(page, 'oac-widget:journal:state'))?.interval).toBe('5m');

  await mount(page, 'ns=journal');
  expect(await facts(page)).toMatchObject({ symbol: 'RELIANCE', interval: '15m' });
  expect(await requests(page)).toEqual(['RELIANCE 15m']);
  // Written through, then dropped.
  await expect.poll(async () => (await stored(page, 'oac-widget:journal:state'))?.interval).toBe('15m');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('oac-widget-journal:journal'))).toBeNull();
});

test('two tabs on one namespace: a line drawn in one is there when the other opens its instrument, and neither loses it', async ({ page, context }, info) => {
  await mount(page, 'ns=tabs&symbol=INFY');
  const other = await context.newPage();
  await mount(other, 'ns=tabs&symbol=TCS');
  const line = await page.evaluate(() => (window as any).fixture.drawSupport());
  await expect.poll(async () => (await stored(page, 'oac-widget:tabs:drawings:NSE:INFY'))?.drawings?.length).toBe(1);
  // The other tab read the namespace before the line existed; it hears of it once it lands.
  await expect.poll(() => other.evaluate(() => (window as any).fixture.widget.context.storage.get('drawings:NSE:INFY') !== null)).toBe(true);
  await other.evaluate(() => (window as any).fixture.widget.setSymbol('INFY'));
  await expect.poll(() => drawings(other)).toEqual([line]);
  await other.waitForFunction(() => (window as any).fixture.loaded() > 0);
  await expect.poll(() => magenta(other)).toBeGreaterThan(150);
  await other.screenshot({ path: info.outputPath('other-tab-dark-desktop.png') });
  const second = await other.evaluate(() => (window as any).fixture.drawSupport());
  await expect.poll(async () => (await stored(page, 'oac-widget:tabs:drawings:NSE:INFY'))?.drawings?.map((d: any) => d.id)).toEqual([line, second]);
  await other.close();
});

test('a host that passes localStorage keeps it, and the widget restores before createWidget returns', async ({ page }) => {
  await mount(page, 'ns=kept&symbol=INFY&storage=local');
  await page.locator('.oac-topbar [data-interval="5m"]').click();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('oac-widget:kept:state') ?? '{}').interval)).toBe('5m');
  expect(Object.keys(await records(page)).filter(k => k.startsWith('oac-widget:kept:'))).toEqual([]);
  await page.evaluate(() => (window as any).fixture.widget.destroy());
  await mount(page, 'ns=kept&storage=local');
  expect(await page.evaluate(() => [(window as any).fixture.hiddenAtStart, (window as any).fixture.widget.interval()])).toEqual([false, '5m']);
  expect(await requests(page)).toEqual(['INFY 5m']);
});

test('a restored layout in the phone layout, dark then light', async ({ page }, info) => {
  await mount(page, 'ns=phone&symbol=INFY&phone', 390);
  const line = await page.evaluate(() => (window as any).fixture.drawSupport());
  await page.evaluate(() => (window as any).fixture.widget.chart.addIndicator('ema', { length: 21 }));
  await expect.poll(async () => (await stored(page, 'oac-widget:phone:drawings:NSE:INFY'))?.drawings?.length).toBe(1);
  await expect.poll(async () => (await stored(page, 'oac-widget:phone:state'))?.chart?.indicators?.length).toBe(1);
  await mount(page, 'ns=phone&phone', 390);
  expect(await drawings(page)).toEqual([line]);
  expect(await requests(page)).toEqual(['INFY 1d']);
  await expect.poll(() => magenta(page)).toBeGreaterThan(80);
  await page.screenshot({ path: info.outputPath('restored-dark-phone.png') });
  await page.evaluate(() => (window as any).fixture.widget.setTheme('light'));
  await expect.poll(async () => (await stored(page, 'oac-widget:phone:state'))?.theme).toBe('light');
  await mount(page, 'ns=phone&phone', 390);
  expect((await facts(page)).theme).toBe('light');
  await page.screenshot({ path: info.outputPath('restored-light-phone.png') });
  expect(await page.evaluate(() => (window as any).fixture.errors)).toEqual([]);
});
