import { test, expect, type Page } from '@playwright/test';

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;

test.use({ viewport: { width: 1360, height: 900 } });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
});

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** Where each pane of the main chart sits on the page. */
const boxes = (page: Page) => page.evaluate(() => (window as any).__oac.app.chart.panes()
  .map((pane: any) => { const r = pane.element.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; }));

/** Which pane holds what the host puts beside the candles. */
const placement = (page: Page) => page.evaluate(() => {
  const app = (window as any).__oac.app, chart = app.chart, panes = chart.panes();
  const holding = (primitive: unknown) => panes.findIndex((pane: any) => pane.primitives().includes(primitive));
  const scaleOf = (series: any) => series ? panes.findIndex((pane: any) => pane.scales().includes(series.priceScale())) : -1;
  return {
    primary: chart.primaryPaneIndex(), panes: panes.length,
    symbolRow: holding(app.symbolLegend), price: scaleOf(app.price), volume: scaleOf(app.volume),
    orders: app.orders.map((order: any) => holding(order.line)),
    rsi: chart.indicators().filter((study: any) => study.indicatorId === 'rsi').map((study: any) => study.paneIndex),
  };
});

async function rightClick(page: Page, pane: number) {
  const box = (await boxes(page))[pane];
  await page.mouse.click(box.left + box.width * 0.45, box.top + box.height * 0.5, { button: 'right' });
  await expect(page.locator('#ctxmenu')).toBeVisible();
}

test('the right-click menu puts the price pane below a study, with its trading lines, and a type switch and a reload keep it there', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.chart.restoreState({ version: 1, indicators: [] });
    app.chart.addIndicator('rsi');
  });
  await paint(page);
  expect(await placement(page)).toMatchObject({ primary: 0, panes: 2, symbolRow: 0, price: 0, rsi: [1] });

  // Over the price pane: the study pane is below, so Move pane down is live and Move pane up is not.
  await rightClick(page, 0);
  await expect(page.locator('#ctxmenu [data-act="paneup"]')).toBeDisabled();
  await expect(page.locator('#ctxmenu [data-act="panecollapse"]')).toBeHidden();
  await page.locator('#ctxmenu [data-act="panedown"]').click();
  await paint(page);
  expect(await placement(page)).toMatchObject({ primary: 1, symbolRow: 1, price: 1, rsi: [0] });
  const volume = (await placement(page)).volume;
  if (volume >= 0) expect(volume).toBe(1);

  // Order entry is offered over the price pane where it now sits, and the order line lands there.
  await rightClick(page, 1);
  await expect(page.locator('#ctxmenu button[data-side="BUY"][data-type="LIMIT"]')).toBeVisible();
  await page.locator('#ctxmenu button[data-side="BUY"][data-type="LIMIT"]').click();
  await paint(page);
  expect((await placement(page)).orders).toEqual([1]);
  // The study pane now at the top folds; the price pane at the bottom does not offer it.
  await rightClick(page, 0);
  await expect(page.locator('#ctxmenu [data-act="panecollapse"]')).toBeVisible();
  await expect(page.locator('#ctxmenu [data-act="paneup"]')).toBeDisabled();
  await page.keyboard.press('Escape');
  await page.mouse.click(5, 5);
  await page.mouse.move(1300, 880);
  await paint(page);
  await page.screenshot({ path: info.outputPath('host-price-pane-bottom.png') });

  // A chart-type switch rebuilds the chart from its saved state.
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  await page.waitForFunction(() => (window as any).__oac.app.chart.primarySeriesInfo()?.type === 'line');
  await paint(page);
  expect(await placement(page)).toMatchObject({ primary: 1, symbolRow: 1, price: 1, rsi: [0], orders: [1] });
  await page.screenshot({ path: info.outputPath('host-price-pane-bottom-line.png') });

  await page.evaluate(async () => { const path = '/examples/yfinance/src/persist.js'; (await import(path)).persistLayoutNow(); });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  await paint(page);
  expect(await placement(page)).toMatchObject({ primary: 1, symbolRow: 1, price: 1, rsi: [0] });
  await page.mouse.move(1300, 880);
  await paint(page);
  await page.screenshot({ path: info.outputPath('host-price-pane-bottom-reloaded.png') });
  expect(errors).toEqual([]);
});

test('a drawing copied beside the candles pastes beside the candles on either chart, wherever each keeps its price pane', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.chart.restoreState({ version: 1, indicators: [] });
    app.chart.addIndicator('rsi');
  });
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return Boolean(app.chart2?.primaryBars().length) && !app.loading2 && Boolean(app.draw2);
  });
  await paint(page);
  // Chart 1 puts its price pane below RSI from its right-click menu; chart 2 keeps its price pane on top.
  await rightClick(page, 0);
  await page.locator('#ctxmenu [data-act="panedown"]').click();
  await paint(page);
  const result = await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const path = '/examples/yfinance/src/clipboard.js';
    const { clipboardAction } = await import(path);
    const ids = (draw: any) => new Set(draw.drawings().map((d: any) => d.id));
    // Everything a paste added to one chart, by pane.
    const pasteInto = async (pane: 1 | 2) => {
      const draw = pane === 1 ? app.draw : app.draw2;
      const before = ids(draw);
      app.focusPane = pane;
      await clipboardAction('paste');
      return draw.drawings().filter((d: any) => !before.has(d.id)).map((d: any) => d.paneIndex);
    };
    const bars = app.chart.primaryBars(), at = bars[bars.length - 12];
    const line = app.draw.add({ tool: 'horizontal-line', paneIndex: app.chart.primaryPaneIndex(), style: {},
      points: [{ time: at.time, price: at.close }] });
    app.focusPane = 1;
    app.draw.select(line.id);
    await clipboardAction('copy');
    const same = await pasteInto(1);
    const other = await pasteInto(2);
    const bars2 = app.chart2.primaryBars(), at2 = bars2[bars2.length - 20];
    const line2 = app.draw2.add({ tool: 'horizontal-line', paneIndex: app.chart2.primaryPaneIndex(), style: {},
      points: [{ time: at2.time, price: at2.close }] });
    app.focusPane = 2;
    app.draw2.select(line2.id);
    await clipboardAction('copy');
    const back = await pasteInto(1);
    return { primary1: app.chart.primaryPaneIndex(), primary2: app.chart2.primaryPaneIndex(), same, other, back };
  });
  expect(result.primary1).toBe(1);
  expect(result.primary2).toBe(0);
  expect(result.same).toEqual([1]);
  expect(result.other.length).toBeGreaterThan(0);
  expect(result.other.every((pane: number) => pane === 0)).toBe(true);
  expect(result.back.length).toBeGreaterThan(0);
  expect(result.back.every((pane: number) => pane === 1)).toBe(true);
  await page.mouse.move(1300, 880);
  await paint(page);
  await page.screenshot({ path: info.outputPath('host-paste-price-pane.png') });
  expect(errors).toEqual([]);
});
