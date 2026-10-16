import { test, expect, type Page } from '@playwright/test';

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;

test.use({ viewport: { width: 1360, height: 900 }, hasTouch: true });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
});

async function openTemplates(page: Page) {
  await page.getByRole('button', { name: 'Templates', exact: true }).click();
  return page.getByRole('dialog', { name: 'Indicator templates', exact: true });
}

test('template controls preserve repeated styles visibility and grouping on the selected chart through rebuild and reload', async ({ page }, info) => {
  const original = await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs', { getIndicator } = await import(bundle);
    const app = (window as any).__oac.app;
    app.chart.restoreState({ version: 1, indicators: [] });
    app.chart.addIndicator('ema', { length: 9, color: '#ff3366', 'ma:width': 3 });
    app.chart.addIndicator('ema', { length: 21, color: '#33ccff' }).setVisible(false);
    const first = app.chart.addIndicator('rsi', { length: 7 });
    app.chart.addIndicator('rsi', { length: 14 }, { paneIndex: first.paneIndex });
    const source = app.chart.getState().indicators.map(({ instanceId: _id, ...study }: any) => study);
    const copy = source.map((study: any, index: number) => ({ ...study, plotPriceScaleIds:
      Object.fromEntries(getIndicator(study.indicatorId).plots.map((plot: any) => [plot.key, app.chart.indicators()[index].plotPriceScaleId(plot.key)])) }));
    return { source, copy };
  });
  let dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Trend and momentum');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac.app.chart2 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus(); dialog = await openTemplates(page);
  await expect(dialog.locator('#tp-owner')).toContainText('Chart 2:');
  await dialog.getByRole('button', { name: 'Replace studies', exact: true }).click();
  await expect(dialog.locator('#tp-notice')).toContainText('applied');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.getState().indicators.map(({ instanceId: _id, ...study }: any) => study))).toEqual(original.copy);
  expect(await page.evaluate(() => (window as any).__oac.app.chart.getState().indicators.map(({ instanceId: _id, ...study }: any) => study))).toEqual(original.source);
  await page.screenshot({ path: info.outputPath('templates-selected-chart.png') });
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    app.p2.symbol = 'MSFT'; await app.loadSecondary(); app.p2.chartType = 'line'; app.rebuildSecondary({ typeChanged: true });
    const path = '/examples/yfinance/src/persist.js'; (await import(path)).persistLayoutNow();
  });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2 && !(window as any).__oac.app.loading2 && !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { symbol: app.p2.symbol, type: app.chart2.primarySeriesInfo().type,
      indicators: app.chart2.getState().indicators.map(({ instanceId: _id, ...study }: any) => study) };
  })).toEqual({ symbol: 'MSFT', type: 'line', indicators: original.copy });
});

test('template append retains drawing and alert ownership and empty replacement removes studies without firing history', async ({ page }) => {
  await page.evaluate(() => {
    const app = (window as any).__oac.app, bar = app.chart.primaryBars().at(-1);
    app.chart.restoreState({ version: 1, indicators: [] });
    const study = app.chart.addIndicator('ema', { length: 9 });
    const drawing = app.draw.add({ tool: 'horizontal-line', paneIndex: 0, points: [{ time: bar.time, price: 1 }], style: {} });
    app.alerts.add({ id: 'template-anchor', source: { kind: 'drawing', drawingId: drawing.id }, condition: 'greaterThan' });
    app.alerts.add({ id: 'template-fired', source: { kind: 'price', price: 1 }, state: 'triggered', repeat: 'once' });
    app.alerts.add({ id: 'template-study-anchor', source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 1 }, condition: 'greaterThan' });
    app.templateEvents = []; app.chart.on('alert:triggered', (event: unknown) => app.templateEvents.push(event));
    app.templateBefore = app.chart.getState();
  });
  const dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Average');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Append studies', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.indicators().length)).toBe(2);
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app, state = app.chart.getState();
    return { drawings: state.drawings, alerts: state.alerts, originalId: state.indicators[0].instanceId,
      beforeId: app.templateBefore.indicators[0].instanceId, events: app.templateEvents };
  })).toMatchObject(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { drawings: app.templateBefore.drawings, alerts: app.templateBefore.alerts,
      originalId: app.templateBefore.indicators[0].instanceId, events: [] };
  }));
  const empty = JSON.stringify({ kind: 'indicator-template', version: 1, id: 'empty', name: 'Clear studies', createdAt: 0, updatedAt: 0, indicators: [] });
  await dialog.locator('#tp-file').setInputFiles({ name: 'empty.json', mimeType: 'application/json', buffer: Buffer.from(empty) });
  await expect(dialog.locator('#tp-select option')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Replace studies', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.indicators().length)).toBe(0);
  expect(await page.evaluate(() => (window as any).__oac.app.templateEvents)).toEqual([]);
  expect(await page.evaluate(() => (window as any).__oac.app.chart.getState().alerts.alerts.map((item: any) => item.id).sort()))
    .toEqual(['template-anchor', 'template-fired']);
});

test('template controls choose independent or shared scales and retain saved manual views', async ({ page }, info) => {
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.chart.restoreState({ version: 1, indicators: [] });
    const metric = app.chart.addIndicator('ema', { length: 9 }, { priceScaleId: 'overlay:template-metric' });
    const signal = app.chart.addIndicator('rsi', { length: 7 });
    app.chart.setPaneWeight(signal.paneIndex, 0.6);
    app.chart.setPriceAxisPlacement(0, 'overlay:template-metric', 'left');
    const scale = metric.series('ma').priceScale();
    scale.setOptions({ inverted: true, minMove: 0.25 });
    scale.setPriceRange({ min: 0, max: 500 }); scale.setAutoScale(false);
    app.templateLayoutBefore = app.chart.getState();
    app.templateLayoutSource = app.chart.primarySeries();
    app.templateLayoutBars = app.chart.primaryBars();
  });
  const dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Axis layout');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  const layout = await page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.templates[0].layout);
  expect(layout.panes[1].weight).toBe(0.6);
  expect(layout.plots).toHaveLength(2);
  expect(layout.panes[0].scales['overlay:template-metric']).toMatchObject({ inverted: true, minMove: 0.25, range: { min: 0, max: 500 } });
  for (const policy of ['share', 'copy']) {
    await page.evaluate(() => {
      const app = (window as any).__oac.app;
      if (!app.chart.restoreState(app.templateLayoutBefore).applied) throw new Error('Fixture reset failed');
    });
    await dialog.getByLabel('Scale ownership', { exact: true }).selectOption(policy);
    await dialog.getByLabel('Saved view', { exact: true }).selectOption('preserve');
    await dialog.getByRole('button', { name: 'Append studies', exact: true }).click();
    await expect(dialog.locator('#tp-notice')).toContainText('applied');
    const state = await page.evaluate(() => {
      const app = (window as any).__oac.app, studies = app.chart.indicators();
      const original = studies[0].series('ma').priceScale(), copy = studies[2].series('ma').priceScale();
      return { count: studies.length, shared: original === copy, range: copy.priceRange(), auto: copy.autoScale,
        inverted: copy.options.inverted, tick: copy.options.minMove,
        weights: app.chart.getState().panes.map((pane: any) => pane.weight),
        sameSource: app.chart.primarySeries() === app.templateLayoutSource,
        sameBars: JSON.stringify(app.chart.primaryBars()) === JSON.stringify(app.templateLayoutBars) };
    });
    expect(state).toMatchObject({ count: 4, shared: policy === 'share', range: { min: 0, max: 500 }, auto: false,
      inverted: true, tick: 0.25, sameSource: true, sameBars: true });
    expect(state.weights.slice(1)).toEqual([0.6, 0.6]);
    await page.screenshot({ path: info.outputPath(`template-${policy}-scales.png`) });
  }
});

test('template metadata and files share storage with visible errors and captured chart guards', async ({ page }, info) => {
  const dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Original');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  await dialog.getByLabel('Template name', { exact: true }).fill('Renamed');
  await dialog.getByRole('button', { name: 'Rename', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveText('Renamed');
  await dialog.getByLabel('Template name', { exact: true }).fill('Copy');
  await dialog.getByRole('button', { name: 'Duplicate', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(2);
  const pending = page.waitForEvent('download'); await dialog.getByRole('button', { name: 'Export selected', exact: true }).click();
  const download = await pending, path = await download.path(); if (!path) throw new Error('Missing template export');
  await dialog.locator('#tp-file').setInputFiles(path);
  await expect(dialog.locator('#tp-select option')).toHaveCount(3);
  await dialog.getByRole('button', { name: 'Delete selected', exact: true }).click();
  await dialog.getByRole('button', { name: 'Confirm delete', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(2);
  await page.evaluate(() => { const app = (window as any).__oac.app; for (const item of [...app.chart.indicators()]) app.chart.removeIndicator(item.id); });
  await dialog.getByRole('button', { name: 'Update selected', exact: true }).click();
  await expect(dialog.locator('#tp-summary')).toHaveText('0 studies');
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'MSFT'; await (window as any).__oac.app.load();
  });
  await expect(dialog.getByRole('button', { name: 'Replace studies', exact: true })).toBeDisabled();
  await expect(dialog.locator('#tp-notice')).toContainText('changed');
  await page.setViewportSize({ width: 390, height: 740 });
  const bounds = await dialog.boundingBox(); expect(bounds!.width).toBeLessThanOrEqual(390);
  for (const button of ['Append studies', 'Replace studies', 'Reload templates']) {
    const box = await dialog.getByRole('button', { name: button, exact: true }).boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  }
  await page.screenshot({ path: info.outputPath('templates-narrow.png') });
  await page.keyboard.press('Escape'); await expect(dialog).toBeHidden();
  await expect(page.getByRole('button', { name: 'Templates', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Full screen chart', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === document.body)).toBe(true);
  await openTemplates(page); await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Template name', { exact: true })).toBeFocused();
  // Some browsers reserve the first Escape for leaving fullscreen and do not dispatch it to the page.
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => !document.fullscreenElement || document.getElementById('templatemodal')!.hidden)).toBe(true);
  if (await dialog.isVisible()) await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.evaluate(() => document.fullscreenElement ? document.exitFullscreen() : undefined);
});

test('template write failures preserve saved content and custom descriptors must be available before replacement', async ({ page }) => {
  const dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Durable');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  const before = await page.evaluate(() => {
    const catalog = (window as any).__oac.app.workspaceCatalog, write = catalog.storage.write;
    catalog.storage.write = async () => { catalog.storage.write = write; throw new Error('Template quota refused'); };
    return structuredClone(catalog.catalog.templates[0]);
  });
  await dialog.getByRole('button', { name: 'Update selected', exact: true }).click();
  await expect(dialog.locator('#tp-error')).toContainText('Template quota refused');
  expect(await page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.templates[0])).toEqual(before);
  await dialog.getByRole('button', { name: 'Reload templates', exact: true }).click();
  await expect(dialog.locator('#tp-error')).toBeHidden();
  const source = JSON.stringify({ kind: 'indicator-template', version: 1, id: 'custom', name: 'Custom', createdAt: 0, updatedAt: 0,
    indicators: [{ indicatorId: 'custom-template-study', settings: { length: 17 }, paneIndex: 0, visible: false }] });
  await dialog.locator('#tp-file').setInputFiles({ name: 'custom.json', mimeType: 'application/json', buffer: Buffer.from(source) });
  await expect(dialog.locator('#tp-select option')).toHaveCount(2);
  const current = await page.evaluate(() => (window as any).__oac.app.chart.getState().indicators);
  await dialog.getByRole('button', { name: 'Replace studies', exact: true }).click();
  await expect(dialog.locator('#tp-error')).toContainText('custom-template-study');
  expect(await page.evaluate(() => (window as any).__oac.app.chart.getState().indicators)).toEqual(current);
  await page.evaluate(async () => {
    const path = '/dist/openalgo-charts.mjs', { getIndicator, registerIndicator } = await import(path);
    registerIndicator({ ...getIndicator('ema'), id: 'custom-template-study', name: 'Custom template study' });
  });
  await dialog.getByRole('button', { name: 'Replace studies', exact: true }).click();
  await expect(dialog.locator('#tp-error')).toBeHidden();
  expect(await page.evaluate(() => (window as any).__oac.app.chart.getState().indicators))
    .toMatchObject([{ indicatorId: 'custom-template-study', settings: { length: 17 }, visible: false }]);
});

test('applying a template during replay retains the displayed prefix and paused alerts', async ({ page }) => {
  const dialog = await openTemplates(page);
  await dialog.getByLabel('Template name', { exact: true }).fill('Replay studies');
  await dialog.getByRole('button', { name: 'Save new template', exact: true }).click();
  await expect(dialog.locator('#tp-select option')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  const before = await page.evaluate(async () => {
    const app = (window as any).__oac.app, path = '/examples/yfinance/src/replay.js', replay = await import(path);
    replay.enterReplay(); await replay.startReplayAt(Math.floor(app.currentBars.length / 2));
    app.templateReplayEvents = []; app.chart.on('alert:triggered', (event: unknown) => app.templateReplayEvents.push(event));
    return { count: app.chart.primaryBars().length, last: app.chart.primaryBars().at(-1).time, studies: app.chart.indicators().length };
  });
  await openTemplates(page);
  await dialog.getByRole('button', { name: 'Append studies', exact: true }).click();
  await expect(dialog.locator('#tp-notice')).toContainText('applied');
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { count: app.chart.primaryBars().length, last: app.chart.primaryBars().at(-1).time,
      studies: app.chart.indicators().length, replay: Boolean(app.replay), events: app.templateReplayEvents };
  })).toEqual({ ...before, studies: before.studies * 2, replay: true, events: [] });
});
