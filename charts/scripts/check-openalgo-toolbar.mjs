import assert from 'node:assert/strict';
import { expect } from '@playwright/test';

/** Exercise the real consumer controls against the harness's mocked transport. */
export async function checkToolbar({ page, check, screenshot, orderCount, hostFinding }) {
  const ordersBefore = orderCount();
  const toolbar = page.getByRole('toolbar', { name: 'Chart controls' });
  const state = () => page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart).map(t => ({
    key: t.sk, symbol: t.sym?.symbol, interval: t.interval, type: t.ctype,
    picking: t.replayPickingBar(), replay: t.replayActive(), locked: t.workspaceReplayLocked,
    studies: t.chart.indicators().map(s => s.indicatorId),
  })));
  const ready = () => page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed).every(t =>
    t.chart && t.price?.getData().length && !t.dataUnavailable() && t.chart.getDataContext()?.interval === t.interval));
  // The host's right rail has an Alerts button of its own, which opens its
  // alerts panel. The toolbar's opens the selected chart's alert form: the
  // terminal hands the host `cb.onAlerts`, and the host names the chart the
  // form was opened for, which is how ownership is read here.
  const alertsButton = toolbar.getByRole('button', { name: 'Alerts', exact: true });
  const alertForm = page.getByRole('dialog', { name: 'Create alert', exact: true });
  const openAlertForm = async symbol => {
    await alertsButton.click();
    await expect(alertForm).toBeVisible();
    await expect(alertForm.getByText(`${symbol} on this chart`, { exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(1);
  };
  const closeAlertForm = async () => {
    await page.keyboard.press('Escape');
    await expect(alertForm).toHaveCount(0);
  };
  await check('one workspace toolbar remains after adding a second chart', async () => {
    await expect(page.getByRole('toolbar', { name: 'Chart controls' })).toHaveCount(1);
    await page.getByRole('button', { name: 'Chart layout: Single', exact: true }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.price?.getData().length).length === 2);
    await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
    await expect(page.getByRole('toolbar', { name: 'Chart controls' })).toHaveCount(1);
    await expect(alertsButton).toHaveCount(1);
    assert.equal(await page.locator('[data-toolbar-pane]').getAttribute('data-toolbar-pane'), 'p0');
  });
  await check('keyboard and chart selection move controls without recreating terminals', async () => {
    await page.evaluate(() => { window.__toolbarOwners = window.__compatTerminals.filter(t => !t.destroyed); });
    await page.locator('[data-chart-pane="p1"]').focus();
    await expect(toolbar).toHaveAttribute('data-toolbar-pane', 'p1');
    await expect(page.locator('[data-chart-pane="p1"]')).toHaveAttribute('data-chart-focused', 'true');
    await page.getByRole('button', { name: 'Selected chart: 2', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Chart 1: NSE:BHEL', exact: true }).click();
    await expect(toolbar).toHaveAttribute('data-toolbar-pane', 'p0');
    await page.locator('[data-chart-pane="p1"]').focus();
    await expect(toolbar).toHaveAttribute('data-toolbar-pane', 'p1');
    assert(await page.evaluate(() => window.__toolbarOwners.every(t => !t.destroyed && window.__compatTerminals.includes(t))));
  });
  await check('symbol interval and chart type controls act only on the selected chart', async () => {
    await toolbar.getByRole('button', { name: '5m', exact: true }).click();
    await page.getByRole('menuitem', { name: '15m', exact: true }).click();
    await ready();
    await toolbar.getByTitle('Candles', { exact: true }).click();
    await page.getByRole('menuitem', { name: 'Line', exact: true }).click();
    await ready();
    await toolbar.getByTitle('Search symbol', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Search symbol', exact: true }).fill('NIFTY29SEP26FUT');
    await page.getByRole('dialog', { name: 'Symbol Search', exact: true }).getByText('NIFTY29SEP26FUT', { exact: true }).click();
    await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.sk === 'oa-trading-p1' && t.sym?.symbol === 'NIFTY29SEP26FUT' && !t.dataUnavailable()));
    assert.deepEqual((await state()).map(({ symbol, interval, type }) => ({ symbol, interval, type })), [
      { symbol: 'BHEL', interval: '5m', type: 'candlestick' },
      { symbol: 'NIFTY29SEP26FUT', interval: '15m', type: 'line' },
    ]);
  });
  await check('alerts snapshots and replay retain the selected chart owner', async () => {
    await openAlertForm('NIFTY29SEP26FUT');
    await closeAlertForm();
    const downloaded = page.waitForEvent('download');
    await toolbar.getByRole('button', { name: 'Chart snapshot', exact: true }).click({ modifiers: ['Shift'] });
    assert.match((await downloaded).suggestedFilename(), /^NIFTY29SEP26FUT-15m-.*\.png$/);
    await page.locator('[data-sonner-toast] [data-close-button]').last().click();
    await toolbar.getByRole('button', { name: 'Replay', exact: true }).click();
    await expect.poll(async () => (await state()).map(pane => pane.picking)).toEqual([false, true]);
    const replay = page.getByRole('region', { name: 'Workspace replay' });
    await expect(replay).toHaveCount(1);
    await expect(replay.getByLabel('Replay scope')).toHaveValue('focused');
    assert.deepEqual((await state()).map(pane => pane.locked), [true, true]);
    await replay.getByRole('button', { name: 'Cancel replay', exact: true }).click();
    await expect.poll(async () => (await state()).map(pane => pane.picking)).toEqual([false, false]);
    await expect(replay).toHaveCount(0);
    assert.deepEqual((await state()).map(pane => pane.locked), [false, false]);
    await expect(page.getByRole('dialog', { name: 'Leave replay?' })).toHaveCount(0);
    await toolbar.getByRole('button', { name: 'Replay', exact: true }).click();
    await page.evaluate(() => window.__compatTerminals.find(t => !t.destroyed && t.sk === 'oa-trading-p1').commitReplayPick());
    await expect.poll(async () => (await state()).map(pane => pane.replay)).toEqual([false, true]);
    assert.deepEqual((await state()).map(pane => pane.locked), [true, true]);
    await replay.getByRole('button', { name: 'Stop replay', exact: true }).click();
    const confirmation = page.getByRole('dialog', { name: 'Leave replay?' });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole('button', { name: 'Stay', exact: true }).click();
    await expect(confirmation).toHaveCount(0);
    assert.deepEqual((await state()).map(pane => pane.replay), [false, true]);
    await toolbar.getByTitle('Stop workspace replay', { exact: true }).click();
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole('button', { name: 'Leave', exact: true }).click();
    await expect(replay).toHaveCount(0);
    assert.deepEqual((await state()).map(pane => pane.replay), [false, false]);
    assert.deepEqual((await state()).map(pane => pane.locked), [false, false]);
    assert.equal(orderCount(), ordersBefore);
  });
  await check('study controls add an indicator only to the selected chart', async () => {
    await toolbar.getByTitle('Indicators', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Search indicators', exact: true }).fill('EMA');
    await page.getByTitle('Add EMA', { exact: true }).click();
    await expect.poll(async () => (await state()).map(pane => pane.studies.includes('ema'))).toEqual([false, true]);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('heading', { name: 'Indicators', exact: true })).toHaveCount(0);
  });
  await check('fullscreen keeps one toolbar inside the selected chart', async () => {
    if (!await page.evaluate(() => document.fullscreenEnabled)) return;
    await toolbar.getByRole('button', { name: 'Toggle full screen chart', exact: true }).click();
    await page.waitForFunction(() => !!document.fullscreenElement?.querySelector('[data-toolbar-pane="p1"]'));
    await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
    await expect(page.locator('[data-workspace-toolbar] [data-toolbar-pane]')).toHaveCount(0);
    await openAlertForm('NIFTY29SEP26FUT');
    // Only the fullscreen element's subtree is painted, so a form opened
    // anywhere else is in the DOM and invisible to the trader. Where the form
    // opens is the host's portal, not this package's, so it is reported as a
    // host finding rather than failing the package's gate.
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-fullscreen-alert.png') });
    if (!await alertForm.evaluate(el => !document.fullscreenElement || document.fullscreenElement.contains(el))) {
      hostFinding('The toolbar alert form opens outside the fullscreen chart, so it is not painted while the chart is fullscreen');
    }
    await page.keyboard.press('Escape');
    await page.evaluate(async () => {
      // Escape can also leave native fullscreen, depending on the browser.
      if (document.fullscreenElement) await document.exitFullscreen();
    });
    if (await alertForm.count()) await closeAlertForm();
    await expect(page.locator('[data-workspace-toolbar] [data-toolbar-pane]')).toHaveCount(1);
  });
  await check('compact toolbar stays reachable without expanding the page', async () => {
    const viewport = page.viewportSize();
    await page.setViewportSize({ width: 390, height: 844 });
    await openAlertForm('NIFTY29SEP26FUT');
    await closeAlertForm();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    const selection = await page.getByRole('button', { name: 'Selected chart: 2', exact: true }).boundingBox();
    assert(selection && selection.x >= 0 && selection.x + selection.width <= 390, 'Selected chart stays visible while controls scroll');
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-toolbar-mobile.png') });
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (screenshot) await page.screenshot({ path: screenshot.replace(/\.png$/, '-toolbar-desktop.png') });
  });
  await page.evaluate(async () => {
    const t = window.__compatTerminals.find(t => !t.destroyed && t.sk === 'oa-trading-p1');
    await t.applyIndicatorTemplate([], 'replace');
    await t.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' });
    t.setInterval('5m');
    t.setChartType('candlestick');
  });
  await ready();
  // Return the fixture to the single-chart starting point for subsequent checks.
  await check('removing the selected chart falls back to the surviving chart', async () => {
    await page.getByRole('button', { name: 'Chart layout: 2 columns', exact: true }).click();
    await page.getByTitle('Single', { exact: true }).click();
    await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart).length === 1);
    await expect(toolbar).toHaveAttribute('data-toolbar-pane', 'p0');
    assert.equal(orderCount(), ordersBefore);
  });
}
