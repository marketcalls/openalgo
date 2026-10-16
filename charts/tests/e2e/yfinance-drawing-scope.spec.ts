import { test, expect, type Page } from '@playwright/test';

// The reference host keeps drawings per symbol: a line drawn on one symbol is
// not shown on the next symbol loaded into the same chart, returns with its
// own symbol, survives a delete made on another symbol and a reload, and the
// split view's second chart follows the same rule.

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;
const PAGE = ORIGIN + '/examples/yfinance/index.html?test=1';

test.use({ viewport: { width: 1360, height: 860 } });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  await page.goto(PAGE);
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
});

/** Load `symbol` into the main chart the way the symbol box does, and wait for it. */
async function load(page: Page, symbol: string): Promise<void> {
  await page.evaluate(async s => {
    const app = (window as any).__oac.app;
    (document.getElementById('symbol') as HTMLInputElement).value = s;
    await app.load();
  }, symbol);
  await page.waitForFunction(s => {
    const app = (window as any).__oac.app;
    return app.req.symbol === s && !app.loading && app.chart.primaryBars().length > 0;
  }, symbol);
}

/** The user's drawings on a chart: the host's own session marks are never saved and are left out. */
const lines = (page: Page, which: 'draw' | 'draw2' = 'draw'): Promise<Array<{ id: string; points: unknown }>> => page.evaluate(w => {
  const draw = (window as any).__oac.app[w];
  return draw.drawings().filter((d: any) => d.policy?.persistent !== false).map((d: any) => ({ id: d.id, points: d.points }));
}, which);

/** A magenta line across recent bars of the chart behind `which`. */
const addLine = (page: Page, which: 'draw' | 'draw2' = 'draw', from = 40, to = 10): Promise<string> => page.evaluate(([w, a, b]) => {
  const app = (window as any).__oac.app;
  const chart = w === 'draw' ? app.chart : app.chart2;
  const bars = chart.primaryBars();
  const p = bars[bars.length - (a as number)], q = bars[bars.length - (b as number)];
  return app[w as string].add({ tool: 'trend-line', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 4 },
    points: [{ time: p.time, price: p.low }, { time: q.time, price: q.high }] }).id;
}, [which, from, to] as const);

/** Magenta pixels on the main chart's canvases. */
const magenta = (page: Page, selector = '#chart'): Promise<number> => page.locator(selector).evaluate(root => {
  let count = 0;
  for (const canvas of root.querySelectorAll('canvas')) {
    if (canvas.width === 0 || canvas.height === 0) continue;
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
    for (let p = 0; p < data.length; p += 4) {
      if (data[p + 3] > 120 && data[p] > 180 && data[p + 1] < 90 && data[p + 2] > 180) count++;
    }
  }
  return count;
});

test('a line drawn on one symbol is not shown on the next, and comes back with its own', async ({ page }, info) => {
  await load(page, 'AAPL');
  await addLine(page);
  const onAapl = await lines(page);
  expect(onAapl).toHaveLength(1);
  await expect.poll(() => magenta(page)).toBeGreaterThan(100);
  await load(page, 'MSFT');
  expect(await lines(page)).toEqual([]);
  await expect.poll(() => magenta(page)).toBe(0);
  await page.screenshot({ path: info.outputPath('host-msft-clean.png') });
  await load(page, 'AAPL');
  expect(await lines(page)).toEqual(onAapl);
  await expect.poll(() => magenta(page)).toBeGreaterThan(100);
  await page.screenshot({ path: info.outputPath('host-aapl-line-back.png') });
});

test('deleting on another symbol does not delete the first symbol line', async ({ page }) => {
  await load(page, 'AAPL');
  await addLine(page);
  const onAapl = await lines(page);
  await load(page, 'MSFT');
  await addLine(page, 'draw', 30, 5);
  await page.evaluate(() => {
    const draw = (window as any).__oac.app.draw;
    draw.removeMany(draw.drawings().map((d: any) => d.id));
  });
  expect(await lines(page)).toEqual([]);
  await load(page, 'AAPL');
  expect(await lines(page)).toEqual(onAapl);
  await load(page, 'MSFT');
  expect(await lines(page)).toEqual([]);
});

test('after a reload each symbol has its own drawings', async ({ page }) => {
  await load(page, 'AAPL');
  await addLine(page);
  const onAapl = await lines(page);
  await load(page, 'MSFT');
  await addLine(page, 'draw', 30, 5);
  const onMsft = await lines(page);
  expect(onMsft).toHaveLength(1);
  await page.evaluate(async () => { (await import('/examples/yfinance/src/persist.js' as string)).persistLayoutNow(); });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => (window as any).__oac.app.req.symbol)).toBe('MSFT');
  expect(await lines(page)).toEqual(onMsft);
  await load(page, 'AAPL');
  expect(await lines(page)).toEqual(onAapl);
});

test('the split view second chart keeps its drawings per symbol too', async ({ page }) => {
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac.app.chart2 && !(window as any).__oac.app.loading2);
  const first = await page.evaluate(() => (window as any).__oac.app.p2.symbol);
  await addLine(page, 'draw2');
  const before = await lines(page, 'draw2');
  const other = first === 'NVDA' ? 'AMZN' : 'NVDA';
  const load2 = (s: string) => page.evaluate(async symbol => {
    const app = (window as any).__oac.app;
    app.p2.symbol = symbol;
    await app.loadSecondary();
  }, s);
  await load2(other);
  expect(await lines(page, 'draw2')).toEqual([]);
  await expect.poll(() => magenta(page, '#chart2')).toBe(0);
  await load2(first);
  expect(await lines(page, 'draw2')).toEqual(before);
  await expect.poll(() => magenta(page, '#chart2')).toBeGreaterThan(100);
});
