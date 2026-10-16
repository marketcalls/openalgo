import { test, expect, type Page } from '@playwright/test';
import { VERSION } from '../../src/version';

// Drawings belong to the instrument they were drawn on. A trend line drawn on
// one symbol must not appear on the next symbol loaded into the same chart,
// must come back when the first symbol does, and must survive a delete made
// on another symbol and a reload. Driven in real browsers through the built
// widget and chart grid, with the pixels checked as well as the model.

async function mount(page: Page, query: string): Promise<void> {
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto(`/tests/e2e/drawing-instrument-fixture.html?${query}`);
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
}

/** Wait until chart `index` shows `symbol` with its bars on it. */
async function showing(page: Page, symbol: string, index = 0): Promise<void> {
  await page.waitForFunction(([s, i]) => {
    const f = (window as any).fixture;
    return f.symbol(i) === s && f.loaded(i) === 200;
  }, [symbol, index] as const);
}

async function setSymbol(page: Page, symbol: string, index = 0): Promise<void> {
  await page.evaluate(([s, i]) => (window as any).fixture.at(i).setSymbol(s), [symbol, index] as const);
}

const drawings = (page: Page, index = 0): Promise<Array<{ id: string; tool: string; points: Array<{ time: number; price: number }> }>> =>
  page.evaluate(i => (window as any).fixture.drawings(i), index);

/** Magenta pixels on the canvases of chart `index`: the fixture's lines are the only magenta on screen. */
const magenta = (page: Page, index = 0): Promise<number> => page.evaluate(i => {
  const charts = document.querySelectorAll('.oac-widget .oac-chart');
  let count = 0;
  for (const canvas of charts[i].querySelectorAll('canvas')) {
    if (canvas.width === 0 || canvas.height === 0) continue;
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
    for (let p = 0; p < data.length; p += 4) {
      if (data[p + 3] > 120 && data[p] > 180 && data[p + 1] < 90 && data[p + 2] > 180) count++;
    }
  }
  return count;
}, index);

test('a trend line drawn with the pointer stays on its symbol and comes back with it', async ({ page }, info) => {
  await mount(page, 'symbol=AAA');
  await showing(page, 'AAA');
  // Placed with two real clicks at two bars' places on the plot.
  const where = await page.evaluate(() => {
    const f = (window as any).fixture, chart = f.widget.chart, b = f.bars();
    f.widget.draw.setTool('trend-line');
    return [[b[60].time, b[60].low - 3], [b[150].time, b[150].high + 3]]
      .map(([time, price]) => ({ x: chart.timeToCoordinate(time), y: chart.priceToCoordinate(price, 0) }));
  });
  const box = (await page.locator('.oac-widget .oac-chart').boundingBox())!;
  for (const p of where) await page.mouse.click(box.x + p.x, box.y + p.y);
  const placed = await drawings(page);
  expect(placed).toHaveLength(1);
  await page.evaluate(id => (window as any).fixture.widget.draw.update(id, { style: { color: '#ff00ff', lineWidth: 4 } }), placed[0].id);
  await page.mouse.move(box.x + 5, box.y + 5);
  await page.evaluate(() => (window as any).fixture.widget.draw.select(null));
  await expect.poll(() => magenta(page)).toBeGreaterThan(200);
  await page.screenshot({ path: info.outputPath('aaa-with-line.png') });

  await setSymbol(page, 'BBB');
  await showing(page, 'BBB');
  expect(await drawings(page)).toEqual([]);
  await expect.poll(() => magenta(page)).toBe(0);
  await page.screenshot({ path: info.outputPath('bbb-clean.png') });

  await setSymbol(page, 'AAA');
  await showing(page, 'AAA');
  expect(await drawings(page)).toEqual(placed);
  await expect.poll(() => magenta(page)).toBeGreaterThan(200);
  await page.screenshot({ path: info.outputPath('aaa-line-back.png') });
});

test('deleting everything on one symbol leaves the other symbol drawings alone', async ({ page }) => {
  await mount(page, 'symbol=AAA');
  await showing(page, 'AAA');
  const mine = await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120));
  await setSymbol(page, 'BBB');
  await showing(page, 'BBB');
  await page.evaluate(() => (window as any).fixture.addLine(0, 90, 180));
  // Everything on B, deleted from the keyboard the way a user would.
  const box = (await page.locator('.oac-widget .oac-chart').boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.evaluate(() => { const d = (window as any).fixture.widget.draw; d.select(d.drawings().map((x: any) => x.id)); });
  await page.keyboard.press('Delete');
  expect(await drawings(page)).toEqual([]);
  await setSymbol(page, 'AAA');
  await showing(page, 'AAA');
  expect((await drawings(page)).map(d => d.id)).toEqual([mine]);
  await setSymbol(page, 'BBB');
  await showing(page, 'BBB');
  expect(await drawings(page)).toEqual([]);
});

test('after a reload each symbol gets its own drawings back', async ({ page }) => {
  await mount(page, 'persist=reload&symbol=AAA');
  await showing(page, 'AAA');
  await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120));
  const onA = await drawings(page);
  await setSymbol(page, 'BBB');
  await showing(page, 'BBB');
  await page.evaluate(() => (window as any).fixture.addLine(0, 100, 190));
  const onB = await drawings(page);
  expect(onB).toHaveLength(1);
  // Teardown writes the layout at once, as the page going away would.
  await page.evaluate(() => (window as any).fixture.widget.destroy());
  // No symbol given: the widget opens on the saved one.
  await mount(page, 'persist=reload&nosymbol');
  await showing(page, 'BBB');
  expect(await drawings(page)).toEqual(onB);
  await setSymbol(page, 'AAA');
  await showing(page, 'AAA');
  expect(await drawings(page)).toEqual(onA);
});

test('a layout saved before drawings were per symbol keeps them on the symbol it was saved on', async ({ page }) => {
  await mount(page, 'symbol=AAA');
  await showing(page, 'AAA');
  await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120));
  const onA = await drawings(page);
  await page.evaluate(() => {
    const widget = (window as any).fixture.widget;
    // Only the layout itself, its drawings inside it, in localStorage: the
    // way an older release left the storage. The default store is IndexedDB
    // now, which copies it in on the first read of the namespace.
    localStorage.setItem('oac-widget:legacy:state', JSON.stringify(widget.getState()));
    widget.destroy();
  });
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('oac-widget:legacy:state')!).chart.drawings.drawings.length)).toBe(1);
  // Opened on another symbol: the saved drawings are not that symbol's.
  await mount(page, 'persist=legacy&symbol=BBB');
  await showing(page, 'BBB');
  expect(await drawings(page)).toEqual([]);
  await expect.poll(() => magenta(page)).toBe(0);
  await setSymbol(page, 'AAA');
  await showing(page, 'AAA');
  expect(await drawings(page)).toEqual(onA);
  await expect.poll(() => magenta(page)).toBeGreaterThan(200);
});

test('switching back and forth before a load lands leaves each symbol with its own drawings', async ({ page }) => {
  await mount(page, 'hold&symbol=AAA');
  await page.evaluate(() => (window as any).fixture.answer());
  await showing(page, 'AAA');
  const onA = [await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120))];
  await page.evaluate(() => {
    const w = (window as any).fixture.widget;
    w.setSymbol('BBB');
    w.setSymbol('AAA');
    w.setSymbol('BBB');
  });
  expect(await drawings(page)).toEqual([]);
  await page.evaluate(() => (window as any).fixture.answer());
  await showing(page, 'BBB');
  expect(await drawings(page)).toEqual([]);
  await expect.poll(() => magenta(page)).toBe(0);
  await setSymbol(page, 'AAA');
  expect((await drawings(page)).map(d => d.id)).toEqual(onA);
  await page.evaluate(() => (window as any).fixture.answer());
  await showing(page, 'AAA');
  expect((await drawings(page)).map(d => d.id)).toEqual(onA);
});

test('a grid cell keeps drawings per symbol, through a reload of the grid', async ({ page }, info) => {
  await mount(page, 'mode=grid&persist=grid&symbol=AAA');
  await showing(page, 'AAA', 0);
  await showing(page, 'AAA', 1);
  await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120));
  const onA = await drawings(page, 0);
  await setSymbol(page, 'BBB', 0);
  await showing(page, 'BBB', 0);
  expect(await drawings(page, 0)).toEqual([]);
  await expect.poll(() => magenta(page, 0)).toBe(0);
  await page.evaluate(() => (window as any).fixture.addLine(0, 100, 190));
  const onB = await drawings(page, 0);
  await page.screenshot({ path: info.outputPath('grid-bbb.png') });
  await setSymbol(page, 'AAA', 0);
  await showing(page, 'AAA', 0);
  expect(await drawings(page, 0)).toEqual(onA);
  await setSymbol(page, 'BBB', 0);
  await showing(page, 'BBB', 0);
  expect(await drawings(page, 0)).toEqual(onB);
  await page.evaluate(() => (window as any).fixture.grid.destroy());
  await mount(page, 'mode=grid&persist=grid&symbol=AAA');
  await showing(page, 'BBB', 0);
  expect(await drawings(page, 0)).toEqual(onB);
  await expect.poll(() => magenta(page, 0)).toBeGreaterThan(200);
  await setSymbol(page, 'AAA', 0);
  await showing(page, 'AAA', 0);
  expect(await drawings(page, 0)).toEqual(onA);
  // The other cell never had a drawing of its own.
  expect(await drawings(page, 1)).toEqual([]);
});

test('drawingScope chart keeps one drawing set for the chart, for a host that wants it', async ({ page }) => {
  await mount(page, 'scope=chart&symbol=AAA');
  await showing(page, 'AAA');
  const id = await page.evaluate(() => (window as any).fixture.addLine(0, 40, 120));
  await setSymbol(page, 'BBB');
  await showing(page, 'BBB');
  expect((await drawings(page)).map(d => d.id)).toEqual([id]);
});
