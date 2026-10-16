import { test, expect, type Page } from '@playwright/test';

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;

test.use({ viewport: { width: 1360, height: 900 } });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading
    && (window as any).__oac.app.currentBars?.length);
});

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** Right-click the main chart at a point in its own px, and wait for the menu. */
async function menuAt(page: Page, x: number, y: number) {
  const box = (await page.locator('#chart').boundingBox())!;
  await page.mouse.click(box.x + x, box.y + y, { button: 'right' });
  await expect(page.locator('#ctxmenu')).toBeVisible();
}

const study = (page: Page) => page.evaluate(() => {
  const found = (window as any).__oac.app.chart.indicators().find((item: any) => item.indicatorId === 'vwap');
  return found ? { id: found.id as string, policy: found.policy(), actions: found.legend()?.options().actions as string[] } : null;
});

test('the protected VWAP keeps every user control from removing, configuring or moving it, and only the host row takes it away', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(() => { (window as any).__oac.app.chart.restoreState({ version: 1, indicators: [] }); });
  await paint(page);
  await menuAt(page, 300, 200);
  const hostRow = page.locator('#ctxmenu [data-act="hoststudy"]');
  await expect(hostRow).toHaveText('Add protected VWAP');
  await hostRow.click();
  await expect.poll(() => study(page)).not.toBeNull();
  const added = (await study(page))!;
  expect(added.policy).toEqual({ removable: false, configurable: false, movable: false });
  expect(added.actions).not.toContain('close');
  expect(added.actions).not.toContain('settings');
  expect(added.actions).toContain('hide');

  // Over its line the settings row is greyed with the reason.
  const point = await page.evaluate((id) => {
    const app = (window as any).__oac.app, chart = app.chart;
    const found = chart.indicators().find((item: any) => item.id === id);
    const bars = app.currentBars, at = bars.length - 10;
    const column = Object.values(found.values()).find((values: any) => Number.isFinite(values?.[at])) as number[];
    return { x: chart.timeToCoordinate(bars[at].time), y: chart.priceToCoordinate(column[at]) };
  }, added.id);
  await paint(page);
  await menuAt(page, point.x, point.y);
  const settingsRow = page.locator('#ctxmenu [data-act="indset"]');
  await expect(settingsRow).toBeVisible();
  await expect(settingsRow).toBeDisabled();
  await expect(settingsRow).toHaveAttribute('title', 'protected by the host');
  await page.screenshot({ path: info.outputPath('protected-menu.png') });
  await page.keyboard.press('Escape');

  // The Objects dock offers only what the policy allows.
  await page.getByRole('button', { name: 'Chart objects', exact: true }).click();
  const row = page.locator(`#inspect-layout-1 [data-object-id="indicator:${added.id}"]`);
  await expect(row).toBeVisible();
  for (const action of ['remove', 'settings', 'earlier', 'later', 'move']) await expect(row.locator(`[data-action="${action}"]`)).toHaveCount(0);
  await expect(row.locator('[data-action="visibility"]')).toHaveCount(1);
  await expect(row).toHaveAttribute('draggable', 'false');
  await page.screenshot({ path: info.outputPath('protected-objects.png') });
  await row.locator('[data-action="visibility"]').click();
  expect(await page.evaluate((id) => (window as any).__oac.app.chart.indicators().find((item: any) => item.id === id).visible(), added.id)).toBe(false);
  await row.locator('[data-action="visibility"]').click();

  // The shared indicator picker greys its remove button.
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  const remove = page.locator(`.oac-pick__running-row[data-instance-id="${added.id}"] .oac-pick__remove`);
  await expect(remove).toBeDisabled();
  await expect(remove).toHaveAttribute('title', 'protected');
  await page.keyboard.press('Escape');

  // Saved with the layout: a reload brings it back protected.
  // `pagehide` flushes the pending autosave, so the reload reads the layout just made.
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading
    && (window as any).__oac.app.currentBars?.length);
  await expect.poll(async () => (await study(page))?.policy).toEqual({ removable: false, configurable: false, movable: false });

  // Only the host row, which passes force, takes it away.
  await menuAt(page, 300, 200);
  await expect(hostRow).toHaveText('Remove protected VWAP');
  await hostRow.click();
  await expect.poll(() => study(page)).toBeNull();
  expect(errors).toEqual([]);
});

test('undo and redo leave the protected VWAP to the host, and walk the user\'s own studies around it', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // A restored layout starts a new timeline.
  await page.evaluate(() => { (window as any).__oac.app.chart.restoreState({ version: 1, indicators: [] }); });
  await paint(page);
  const undo = page.locator('#rail button[aria-label="Undo"]'), redo = page.locator('#rail button[aria-label="Redo"]');
  await expect(undo).toHaveAttribute('aria-disabled', 'true');
  await menuAt(page, 300, 200);
  const hostRow = page.locator('#ctxmenu [data-act="hoststudy"]');
  await hostRow.click();
  await expect.poll(() => study(page)).not.toBeNull();
  // Placing it was the host's act, not a step.
  await expect(undo).toHaveAttribute('aria-disabled', 'true');
  const ids = () => page.evaluate(() => (window as any).__oac.app.chart.indicators().map((item: any) => item.indicatorId as string));
  await page.evaluate(() => { (window as any).__oac.app.chart.addIndicator('sma'); });
  await expect(undo).toHaveAttribute('aria-disabled', 'false');
  await undo.click();
  await paint(page);
  expect(await ids()).toEqual(['vwap']);
  await expect(undo).toHaveAttribute('aria-disabled', 'true');
  await redo.click();
  await paint(page);
  expect(await ids()).toEqual(['vwap', 'sma']);
  await page.screenshot({ path: info.outputPath('protected-undo.png') });
  // Taken away by the host row, which passes force: no step brings it back.
  await menuAt(page, 300, 200);
  await hostRow.click();
  await expect.poll(() => study(page)).toBeNull();
  await undo.click();
  await paint(page);
  expect(await ids()).toEqual([]);
  await expect(undo).toHaveAttribute('aria-disabled', 'true');
  expect(errors).toEqual([]);
});

test('a study the user moves past the protected VWAP is a step the rail takes back, and the VWAP never moves by a call of its own', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(() => { (window as any).__oac.app.chart.restoreState({ version: 1, indicators: [] }); });
  await paint(page);
  const undo = page.locator('#rail button[aria-label="Undo"]'), redo = page.locator('#rail button[aria-label="Redo"]');
  await menuAt(page, 300, 200);
  await page.locator('#ctxmenu [data-act="hoststudy"]').click();
  await expect.poll(() => study(page)).not.toBeNull();
  const vwap = (await study(page))!.id;
  const sma = await page.evaluate(() => (window as any).__oac.app.chart.addIndicator('sma').id as string);
  await paint(page);
  const order = () => page.evaluate(() => (window as any).__oac.app.chart.indicators().map((item: any) => item.indicatorId as string));
  expect(await order()).toEqual(['vwap', 'sma']);
  // Watch every call a press makes on the chart: none may name the VWAP.
  await page.evaluate((id) => {
    const chart = (window as any).__oac.app.chart;
    const calls: string[] = (window as any).__pinnedCalls = [];
    for (const name of ['reorderIndicator', 'moveIndicator', 'moveInSeriesStack']) {
      const own = chart[name].bind(chart);
      chart[name] = (target: string, ...rest: unknown[]) => { if (String(target).endsWith(id)) calls.push(name); return own(target, ...rest); };
    }
  }, vwap);

  // The Objects dock steps the user's SMA through the stack, past the VWAP.
  await page.getByRole('button', { name: 'Chart objects', exact: true }).click();
  const row = page.locator(`#inspect-layout-1 [data-object-id="indicator:${sma}"]`);
  await expect(row).toBeVisible();
  for (let i = 0; i < 3 && (await order())[0] !== 'sma'; i++) {
    await row.locator('[data-action="earlier"]').click();
    await paint(page);
  }
  expect(await order()).toEqual(['sma', 'vwap']);
  await expect(undo).toHaveAttribute('aria-disabled', 'false');
  await page.screenshot({ path: info.outputPath('moved-past-protected.png') });
  await page.keyboard.press('Escape');

  // Walked back with the rail until the stack is as it was, and forward again
  // by as many presses: each press the dock made is one step.
  let presses = 0;
  for (; presses < 3 && (await order())[0] !== 'vwap'; presses++) { await undo.click(); await paint(page); }
  expect(await order()).toEqual(['vwap', 'sma']);
  expect(presses).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath('moved-back.png') });
  for (let i = 0; i < presses; i++) { await redo.click(); await paint(page); }
  expect(await order()).toEqual(['sma', 'vwap']);
  expect((await study(page))!.policy).toEqual({ removable: false, configurable: false, movable: false });
  expect(await page.evaluate(() => (window as any).__pinnedCalls)).toEqual([]);
  expect(errors).toEqual([]);
});
