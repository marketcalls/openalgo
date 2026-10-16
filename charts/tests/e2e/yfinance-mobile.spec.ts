import { test, expect, type ConsoleMessage, type Page, type Request, type Response } from '@playwright/test';

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;
const PAGE = ORIGIN + '/examples/yfinance/index.html?test=1';
const PROBE = ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo';

test('named layout controls create rename duplicate export import and delete saved configurations', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await dialog.getByLabel('Layout name', { exact: true }).fill('Morning');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Morning');
  await dialog.getByLabel('Layout name', { exact: true }).fill('Desk');
  await dialog.getByRole('button', { name: 'Rename', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Desk');
  await dialog.getByLabel('Layout name', { exact: true }).fill('Desk copy');
  await dialog.getByRole('button', { name: 'Duplicate', exact: true }).click();
  await expect(dialog.locator('#ws-select option')).toHaveCount(2);
  const downloadPending = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export selected', exact: true }).click();
  const download = await downloadPending;
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  const file = await download.path();
  if (!file) throw new Error('Export did not create a file');
  await dialog.locator('#ws-file').setInputFiles(file);
  await expect(dialog.locator('#ws-select option')).toHaveCount(3);
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Desk copy');
  await dialog.getByRole('button', { name: 'Delete selected', exact: true }).click();
  await dialog.getByRole('button', { name: 'Confirm delete', exact: true }).click();
  await expect(dialog.locator('#ws-select option')).toHaveCount(2);
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Unnamed');
  await dialog.getByLabel('Saved layouts', { exact: true }).selectOption({ label: 'Desk' });
  await dialog.getByRole('button', { name: 'Open selected', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Desk');
  await expect(dialog.locator('#ws-recent button').first()).toHaveText('Desk');
});

test('named autosave off preserves the saved source on reload and explicit or enabled saves persist changes', async ({ page }) => {
  await openDemo(page);
  await page.evaluate(async () => {
    const path = '/examples/yfinance/src/rail.js', rail = await import(path);
    rail.setMagnetMode('strong'); rail.setStayMode(true);
  });
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await dialog.getByLabel('Layout name', { exact: true }).fill('Saved source');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Saved source');
  await expect(dialog.getByLabel('Autosave current layout', { exact: true })).not.toBeChecked();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'TSLA';
    await (window as any).__oac.app.load();
    const railPath = '/examples/yfinance/src/rail.js', rail = await import(railPath);
    rail.setMagnetMode('off'); rail.setStayMode(false);
    const path = '/examples/yfinance/src/persist.js'; (await import(path)).persistLayoutNow();
  });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => (window as any).__oac.app.req.symbol)).toBe('AAPL');
  expect(await page.evaluate(async () => {
    const path = '/examples/yfinance/src/rail.js', rail = await import(path); return [rail.magnetMode(), rail.stayMode()];
  })).toEqual(['strong', true]);
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'MSFT'; await (window as any).__oac.app.load();
  });
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.workspaces[0].panes[0].symbol)).toBe('MSFT');
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'AMZN'; await (window as any).__oac.app.load();
    const path = '/examples/yfinance/src/persist.js'; (await import(path)).flushAutosave();
  });
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await dialog.getByLabel('Autosave current layout', { exact: true }).check();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.autosave)).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.workspaces[0].panes[0].symbol)).toBe('AMZN');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'NVDA'; await (window as any).__oac.app.load();
  });
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.workspaceCatalog.catalog.workspaces[0].panes[0].symbol)).toBe('NVDA');
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => (window as any).__oac.app.req.symbol)).toBe('NVDA');
});

test('pending named autosave survives replay selection without saving transient state or blocking recovery', async ({ page }) => {
  await openDemo(page);
  await page.waitForFunction(() => !(window as any).__oac.app.loading);
  const selected = await page.evaluate(async () => {
    const app = (window as any).__oac.app, catalog = app.workspaceCatalog;
    const persistPath = '/examples/yfinance/src/persist.js', replayPath = '/examples/yfinance/src/replay.js';
    const persist = await import(persistPath), replay = await import(replayPath);
    persist.flushAutosave(); await catalog.flushAutosave();
    await catalog.create('Replay selection'); await catalog.setAutosave(true);
    persist.persistLayoutNow(); await catalog.flushAutosave();
    const previous = localStorage.getItem(persist.LAYOUT_KEY);
    const nextGrid = !app.chart.getState().grid.vertLines;
    app.chart.setGridOptions({ vertLines: nextGrid });
    persist.autosave(); replay.enterReplay();
    persist.flushAutosave(); await catalog.flushAutosave();
    return { picking: app.replayPicking, unchanged: localStorage.getItem(persist.LAYOUT_KEY) === previous,
      blocked: catalog.autosaveBlocked, error: catalog.error, nextGrid };
  });
  expect(selected).toMatchObject({ picking: true, unchanged: true, blocked: false, error: '' });
  await page.locator('#rp-pick-cancel').click();
  await expect(page.locator('#replaypick')).toBeHidden();
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app, catalog = app.workspaceCatalog;
    const persistPath = '/examples/yfinance/src/persist.js', persist = await import(persistPath);
    persist.autosave(); persist.flushAutosave(); await catalog.flushAutosave();
    const saved = await catalog.storage.read(catalog.namespace);
    return { picking: app.replayPicking, blocked: catalog.autosaveBlocked, error: catalog.error,
      savedGrid: saved.workspaces.find((item: any) => item.id === catalog.currentId).panes[0].chart.grid.vertLines };
  })).toEqual({ picking: false, blocked: false, error: '', savedGrid: selected.nextGrid });
});

test('named layout storage failures stay visible and can be retried without a fallback catalog', async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.indexedDB;
    (window as any).workspaceStorageDenied = true;
    Object.defineProperty(window, 'indexedDB', { configurable: true, get() {
      if ((window as any).workspaceStorageDenied) throw new Error('Workspace storage unavailable');
      return original;
    } });
  });
  await openDemo(page);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await expect(dialog.locator('#ws-error')).toContainText('Workspace storage unavailable');
  await dialog.getByLabel('Layout name', { exact: true }).fill('Retry');
  await expect(dialog.getByRole('button', { name: 'New from current', exact: true })).toBeDisabled();
  await page.evaluate(() => { (window as any).workspaceStorageDenied = false; });
  await dialog.getByRole('button', { name: 'Reload saved layouts', exact: true }).click();
  await expect(dialog.locator('#ws-error')).toBeHidden();
  await page.evaluate(() => {
    const catalog = (window as any).__oac.app.workspaceCatalog;
    const write = catalog.storage.write;
    catalog.storage.write = async (...args: unknown[]) => {
      catalog.storage.write = write;
      throw new Error(`Workspace quota refused revision ${args[2]}`);
    };
  });
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-error')).toContainText('Workspace quota refused');
  await expect(dialog.locator('#ws-select option')).toHaveCount(0);
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Unnamed');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Retry');
  await expect(dialog.locator('#ws-error')).toBeHidden();
});

test('named layout startup preserves an unavailable saved study and blocks automatic replacement', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await dialog.getByLabel('Layout name', { exact: true }).fill('Custom study');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Custom study');
  await page.evaluate(async () => {
    const catalog = (window as any).__oac.app.workspaceCatalog;
    await catalog.setAutosave(true);
    const document = structuredClone(catalog.catalog.workspaces[0]);
    document.panes[0].chart.indicators[0].indicatorId = 'unavailable-saved-study';
    await catalog.repository.saveWorkspace(catalog.currentId, document);
  });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  await expect(dialog.locator('#ws-error')).toContainText('unavailable-saved-study');
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app, path = '/examples/yfinance/src/persist.js';
    (await import(path)).persistLayoutNow(); await app.workspaceCatalog.flushAutosave();
    const stored = await app.workspaceCatalog.storage.read(app.workspaceCatalog.namespace);
    return { blocked: app.workspaceCatalog.autosaveBlocked, owner: app.workspaceCatalog.currentId,
      retained: stored.workspaces[0].panes[0].chart.indicators.some((item: any) => item.indicatorId === 'unavailable-saved-study') };
  })).toEqual({ blocked: true, owner: null, retained: true });
});

test('closing a pending named import cancels it and replay disables source-changing layout actions', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await dialog.getByLabel('Layout name', { exact: true }).fill('Original');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Original');
  const text = await page.evaluate(async () => {
    const catalog = (window as any).__oac.app.workspaceCatalog;
    const source = JSON.parse(await catalog.export(catalog.currentId)); source.panes[0].symbol = 'TSLA';
    return JSON.stringify(source);
  });
  let release!: () => void, waiting = false;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/history?**', async route => {
    if (new URL(route.request().url()).searchParams.get('symbol') === 'TSLA') { waiting = true; await gate; }
    await route.continue();
  });
  await dialog.locator('#ws-file').setInputFiles({ name: 'pending.json', mimeType: 'application/json', buffer: Buffer.from(text) });
  await expect.poll(() => waiting).toBe(true);
  await expect(dialog.getByRole('button', { name: 'Save current', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click(); release();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.workspaceCatalog.busy)).toBe(false);
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.req.symbol, app.workspaceCatalog.catalog.workspaces.length, app.workspaceLoading];
  })).toEqual(['AAPL', 1, false]);
  await page.evaluate(async () => { const path = '/examples/yfinance/src/replay.js'; (await import(path)).enterReplay(); });
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  for (const name of ['Save current', 'New from current', 'Open selected', 'Import file']) {
    await expect(dialog.getByRole('button', { name, exact: true })).toBeDisabled();
  }
});

test('named layout controls retain errors and require refresh before overwriting a remote revision', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: 'Layouts', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await dialog.getByLabel('Layout name', { exact: true }).fill('Desk');
  await dialog.getByRole('button', { name: 'New from current', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Desk');
  await page.evaluate(async () => {
    const catalog = (window as any).__oac.app.workspaceCatalog, path = '/dist/openalgo-charts.workspace.mjs';
    const { WorkspaceRepository } = await import(path);
    await new WorkspaceRepository(catalog.storage, catalog.namespace).rename('workspace', catalog.currentId, 'Remote name');
  });
  await dialog.getByRole('button', { name: 'Save current', exact: true }).click();
  await expect(dialog.locator('#ws-error')).toContainText('another session');
  await dialog.getByRole('button', { name: 'Reload saved layouts', exact: true }).click();
  await expect(dialog.locator('#ws-current')).toHaveText('Current: Remote name');
  await dialog.getByRole('button', { name: 'Save current', exact: true }).click();
  await expect(dialog.locator('#ws-error')).toBeHidden();
  await expect(dialog.getByRole('button', { name: 'Import file', exact: true })).toBeEnabled();
  await dialog.locator('#ws-file').setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from('{invalid') });
  await expect(dialog.locator('#ws-error')).toContainText(/JSON|property|position|syntax/i);
  await expect(dialog.locator('#ws-select option')).toHaveCount(1);
});

test('named layout dialog fits narrow and wide screens and restores keyboard focus', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  const opener = page.getByRole('button', { name: 'Layouts', exact: true });
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Layouts', exact: true });
  await expect(dialog.getByLabel('Layout name', { exact: true })).toBeFocused();
  await page.screenshot({ path: info.outputPath('named-layouts-wide.png') });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden(); await expect(opener).toBeFocused();
  await page.getByRole('button', { name: 'Full screen chart', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === document.body)).toBe(true);
  await opener.click(); await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.evaluate(() => document.exitFullscreen());
  await page.setViewportSize({ width: 390, height: 740 });
  await opener.click();
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.width).toBeLessThanOrEqual(390);
  expect(box!.y + box!.height).toBeLessThanOrEqual(740);
  await page.screenshot({ path: info.outputPath('named-layouts-narrow.png') });
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
});

test('named workspace catalog publishes through real browser storage and retains saved startup ownership', async ({ page }) => {
  await openDemo(page);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const catalogPath = '/examples/yfinance/src/workspace-catalog.js', storagePath = '/dist/openalgo-charts.workspace.mjs';
    const persistPath = '/examples/yfinance/src/persist.js', adapterPath = '/examples/yfinance/src/workspace-document.js';
    const { ReferenceWorkspaceCatalog } = await import(catalogPath);
    const { createIndexedDbWorkspaceStorage } = await import(storagePath);
    const { workspaceFromLayout } = await import(adapterPath);
    const { layoutSnapshot } = await import(persistPath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'reference-catalog-browser-test');
    const options = { storage, namespace: 'demo', snapshot: () => workspaceFromLayout(layoutSnapshot()), open: app.openWorkspace };
    const catalog = new ReferenceWorkspaceCatalog(options);
    await catalog.initialize();
    const initial = await catalog.create('Original');
    const source = JSON.parse(await catalog.export(initial.id));
    source.name = 'Saved source'; source.panes[0].symbol = 'TSLA';
    const imported = await catalog.import(JSON.stringify(source));
    const stored = await storage.read('demo');
    const startup = await new ReferenceWorkspaceCatalog(options).initialize({ schema: 2, version: 1, dataset: 'MSFT|1d|1y' });
    const chart = app.chart;
    await storage.close();
    const error = await catalog.open(initial.id).then(() => '', (failure: Error) => failure.message);
    return { symbol: app.req.symbol, savedSymbol: stored.workspaces.find((item: any) => item.id === imported.id).panes[0].symbol,
      currentMatches: catalog.currentId === imported.id, recentMatches: stored.recentWorkspaceIds[0] === imported.id,
      startupSymbol: startup.request.symbol, autosave: stored.autosave, unchangedAfterFailure: app.chart === chart, error };
  })).toMatchObject({ symbol: 'TSLA', savedSymbol: 'TSLA', currentMatches: true, recentMatches: true,
    startupSymbol: 'TSLA', autosave: false, unchangedAfterFailure: true, error: expect.stringMatching(/closed/) });
});

test('prepared workspace switches both sources only after every history and storage write are ready', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  let releaseHistory!: () => void;
  const gate = new Promise<void>(resolve => { releaseHistory = resolve; });
  let waiting = false;
  await page.route('**/api/history?**', async route => {
    if (new URL(route.request().url()).searchParams.get('symbol') === 'TSLA') { waiting = true; await gate; }
    await route.continue();
  });
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    if (typeof app.openWorkspace !== 'function') throw new Error('Workspace switching is not installed');
    const snapshotPath = '/examples/yfinance/src/persist.js', adapterPath = '/examples/yfinance/src/workspace-document.js';
    const snapshot = (await import(snapshotPath)).layoutSnapshot();
    snapshot.request = { symbol: 'TSLA', interval: '15m', period: '1mo' };
    snapshot.chartType = 'line'; snapshot.timezone = 'America/New_York'; snapshot.focusPane = 2;
    snapshot.secondary = { request: { symbol: 'MSFT', interval: '1h', period: '1mo' }, chartType: 't:point-figure', pfmode: 'percent',
      width: 35, state: { version: 1, timezone: 'Asia/Kolkata', indicators: [] }, comparisons: [] };
    const stored = new Promise(resolve => { app.releaseWorkspaceStorage = resolve; });
    app.workspaceResult = app.openWorkspace((await import(adapterPath)).workspaceFromLayout(snapshot), () => stored)
      .then(() => 'done', (error: Error) => error.message);
  });
  await expect.poll(() => waiting).toBe(true);
  expect(await page.evaluate(() => { const app = (window as any).__oac.app; return [app.req.symbol, Boolean(app.chart2), app.workspaceLoading]; }))
    .toEqual(['AAPL', false, true]);
  releaseHistory();
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => (window as any).__oac.app.req.symbol)).toBe('AAPL');
  expect(await page.evaluate(async () => { const app = (window as any).__oac.app; app.releaseWorkspaceStorage(); return await app.workspaceResult; })).toBe('done');
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { primary: app.req, secondary: { symbol: app.p2.symbol, interval: app.p2.interval, period: app.p2.period },
      types: [app.chart.primarySeriesInfo().type, app.chart2.primarySeriesInfo().type],
      zones: [app.chart.timezone(), app.chart2.timezone()], focused: app.focusPane,
      secondaryWidth: (document.getElementById('pane2') as HTMLElement).style.flexBasis, pending: app.workspaceLoading };
  })).toEqual({ primary: { symbol: 'TSLA', interval: '15m', period: '1mo' }, secondary: { symbol: 'MSFT', interval: '1h', period: '1mo' },
    types: ['line', 'point-figure'], zones: ['America/New_York', 'Asia/Kolkata'], focused: 2, secondaryWidth: '35%', pending: false });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-prepared-workspace.png') });
});

test('failed workspace storage and source changes leave the current charts intact', async ({ page }) => {
  await openDemo(page);
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    if (typeof app.openWorkspace !== 'function') throw new Error('Workspace switching is not installed');
    const snapshotPath = '/examples/yfinance/src/persist.js', adapterPath = '/examples/yfinance/src/workspace-document.js';
    const snapshot = (await import(snapshotPath)).layoutSnapshot();
    snapshot.request = { symbol: 'TSLA', interval: '15m', period: '1mo' };
    const document = (await import(adapterPath)).workspaceFromLayout(snapshot);
    const original = app.chart;
    const failure = await app.openWorkspace(document, () => Promise.reject(new Error('Storage refused'))).then(() => '', (error: Error) => error.message);
    let release: () => void = () => {};
    const begun = new Promise<void>(resolve => { release = resolve; });
    const pending = app.openWorkspace(document, (signal: AbortSignal) => {
      release();
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
    }).then(() => '', (error: Error) => error.message);
    await begun;
    app.chart.setDataContext({ ...app.chart.getDataContext(), symbol: 'CHANGED' });
    const cancelled = await pending;
    return { failure, cancelled, sameChart: app.chart === original, request: app.req.symbol, pending: app.workspaceLoading };
  })).toMatchObject({ failure: 'Storage refused', cancelled: 'Layout preparation was cancelled', sameChart: true, request: 'AAPL', pending: false });
});

test('workspace installation failure restores transformed charts from their original raw histories', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.loading2);
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    (document.getElementById('ctype') as HTMLSelectElement).value = 't:heikin-ashi'; app.render();
    app.p2.chartType = 't:heikin-ashi'; app.rebuildSecondary();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const before = { primary: app.chart.primaryBars(), secondary: app.chart2.primaryBars(), request: { ...app.req }, p2: { ...app.p2 } };
    const snapshotPath = '/examples/yfinance/src/persist.js', adapterPath = '/examples/yfinance/src/workspace-document.js';
    const snapshot = (await import(snapshotPath)).layoutSnapshot(); snapshot.request.symbol = 'TSLA';
    const documentValue = (await import(adapterPath)).workspaceFromLayout(snapshot);
    const host = document.getElementById('chart')!, append = host.appendChild;
    let fail = true, revertedStorage = false;
    host.appendChild = function<T extends Node>(child: T): T {
      if (fail) { fail = false; throw new Error('Chart installation refused'); }
      return append.call(this, child) as T;
    };
    let error = '';
    try { await app.openWorkspace(documentValue, async () => ({ rollback: async () => { revertedStorage = true; } })); }
    catch (failure) { error = (failure as Error).message; }
    finally { host.appendChild = append; }
    return { error, revertedStorage, primary: JSON.stringify(app.chart.primaryBars()) === JSON.stringify(before.primary),
      secondary: JSON.stringify(app.chart2.primaryBars()) === JSON.stringify(before.secondary),
      request: app.req, expectedRequest: before.request, secondSymbol: app.p2.symbol, expectedSecondSymbol: before.p2.symbol,
      pending: app.workspaceLoading };
  })).toMatchObject({ error: 'Chart installation refused', revertedStorage: true, primary: true, secondary: true,
    request: { symbol: 'AAPL' }, expectedRequest: { symbol: 'AAPL' }, secondSymbol: 'MSFT', expectedSecondSymbol: 'MSFT', pending: false });
});

test('workspace installation keeps drawing anchors and fired alerts without evaluating restored history', async ({ page }) => {
  await openDemo(page);
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app, tail = app.chart.primaryBars().at(-1);
    const drawing = app.draw.add({ tool: 'horizontal-line', paneIndex: 0, points: [{ time: tail.time, price: 1 }], style: {} });
    app.alerts.add({ id: 'workspace-armed', source: { kind: 'drawing', drawingId: drawing.id }, condition: 'greaterThan' });
    app.alerts.add({ id: 'workspace-fired', source: { kind: 'price', price: 1 }, state: 'triggered', repeat: 'once' });
    const snapshotPath = '/examples/yfinance/src/persist.js', adapterPath = '/examples/yfinance/src/workspace-document.js';
    const snapshot = (await import(snapshotPath)).layoutSnapshot();
    const prototype = Object.getPrototypeOf(app.chart), emit = prototype.emit;
    let triggered = 0;
    prototype.emit = function(type: string, value: unknown) { if (type === 'alert:triggered') triggered++; return emit.call(this, type, value); };
    try { await app.openWorkspace((await import(adapterPath)).workspaceFromLayout(snapshot)); }
    finally { prototype.emit = emit; }
    return { triggered, anchored: Boolean(app.draw.get(drawing.id)), available: app.alerts.availability('workspace-armed').available,
      alerts: app.alerts.list().map((alert: any) => [alert.id, alert.state]), pending: app.workspaceLoading };
  })).toEqual({ triggered: 0, anchored: true, available: true,
    alerts: [['workspace-armed', 'armed'], ['workspace-fired', 'triggered']], pending: false });
});

test('portable reference workspace captures both real charts without losing studies or source ownership', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.loading2);
  const result = await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    app.chart.addIndicator('ema', { period: 9, 'plot.ema.color': '#ff0000' });
    app.chart.addIndicator('ema', { period: 21, 'plot.ema.color': '#00ffff' });
    app.chart.setTimezone('America/New_York');
    app.focusPane = 2;
    const snapshotPath = '/examples/yfinance/src/persist.js';
    const documentPath = '/examples/yfinance/src/workspace-document.js';
    const snapshot = (await import(snapshotPath)).layoutSnapshot();
    const adapter = await import(documentPath);
    const portable = adapter.workspaceFromLayout(snapshot, { magnet: 'weak', stay: true });
    const restored = adapter.layoutFromWorkspace(portable);
    const again = adapter.workspaceFromLayout(restored);
    return { same: JSON.stringify(portable) === JSON.stringify(again),
      primary: restored.request, secondary: restored.secondary.request, focus: restored.focusPane,
      timezone: restored.timezone, studies: restored.indicators,
      expectedStudies: snapshot.indicators, secondaryState: restored.secondary.state,
      expectedSecondaryState: snapshot.secondary.state, chartFields: Object.keys(snapshot).filter(key => key in portable.panes[0].chart),
      unexpectedFields: Object.keys(app.chart.getState()).filter(key => !(key in portable.panes[0].chart)),
      containsHistory: JSON.stringify(portable).includes('currentBars') };
  });
  expect(result.same).toBe(true);
  expect(result.primary.symbol).toBe('AAPL');
  expect(result.secondary.symbol).toBe('MSFT');
  expect(result.focus).toBe(2);
  expect(result.timezone).toBe('America/New_York');
  expect(result.studies).toEqual(result.expectedStudies);
  expect(result.secondaryState).toEqual(result.expectedSecondaryState);
  expect(result.unexpectedFields).toEqual([]);
  expect(result.containsHistory).toBe(false);
});

test('primary layout selection is restored before the first history request', async ({ page }, info) => {
  await openDemo(page);
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    for (const [id, value] of Object.entries({ symbol: 'TSLA', interval: '15m', period: '1mo', ctype: 't:point-figure' })) {
      (document.getElementById(id) as HTMLInputElement).value = value;
    }
    app.transforms = { 'point-figure': { mode: 'percent', percent: 0.5, reversal: 2, method: 'close' } };
    await app.load();
    app.chart.setTimezone('America/New_York');
    const source = '/examples/yfinance/src/persist.js'; (await import(source)).persistLayoutNow();
  });
  const requests: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === '/api/history') requests.push(['symbol', 'interval', 'period'].map(key => url.searchParams.get(key)).join('/'));
  });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  expect(requests[0]).toBe('TSLA/15m/1mo');
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { request: app.req, timezone: app.chart.timezone(), type: app.chart.getState().series[0].type,
      selection: (document.getElementById('ctype') as HTMLSelectElement).value,
      transform: app.chart.seriesTransform(app.chart.primarySeries()) };
  })).toEqual({ request: { symbol: 'TSLA', interval: '15m', period: '1mo' }, timezone: 'America/New_York',
    type: 'point-figure', selection: 't:point-figure',
    transform: { type: 'point-figure', options: { mode: 'percent', percent: 0.5, reversal: 2, method: 'close' } } });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-primary-layout-restored.png') });
});

test('saved calendar timezone is used for the first fold after reload', async ({ page }) => {
  await page.addInitScript(() => {
    Date.now = () => Date.UTC(2026, 2, 2, 12);
    localStorage.setItem('oa-charts:layout', JSON.stringify({ schema: 2, version: 1,
      dataset: 'TSLA|1mo|5y', request: { symbol: 'TSLA', interval: '1mo', period: '5y' },
      chartType: 'line', pfmode: 'atr', timezone: 'America/New_York', indicators: [] }));
  });
  const requests: string[] = [];
  await page.route('**/api/history?**', async route => {
    const query = new URL(route.request().url()).searchParams;
    requests.push(query.get('symbol') + '/' + query.get('interval') + '/' + query.get('period'));
    await route.fulfill({ json: ['2026-01-31T18:00:00Z', '2026-02-01T02:00:00Z', '2026-02-01T14:00:00Z'].map((time, i) => ({
      time: Date.parse(time) / 1000, open: 10 * (i + 1), high: 10 * (i + 1), low: 10 * (i + 1), close: 10 * (i + 1), volume: i + 1,
    })) });
  });
  await openDemo(page);
  expect(requests[0]).toBe('TSLA/1d/5y');
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { timezone: app.chart.timezone(), bars: app.chart.primaryBars().map((bar: any) => ({ time: bar.time, close: bar.close, volume: bar.volume })) };
  })).toEqual({ timezone: 'America/New_York', bars: [
    { time: Date.parse('2026-01-01T05:00:00Z') / 1000, close: 20, volume: 3 },
    { time: Date.parse('2026-02-01T05:00:00Z') / 1000, close: 30, volume: 3 },
  ] });
});

test('all-chart replay shares time, scope and restoration through its controls', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  await page.route('**/api/history?**', route => route.fulfill({ json: [] }));
  const seed = await page.evaluate(() => {
    const app = (window as any).__oac.app, start = Date.UTC(2024, 0, 2) / 1000;
    const bars = (step: number, count: number) => Array.from({ length: count }, (_, i) => ({
      time: start + i * step, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 100 + i,
    }));
    app.req.interval = '5m'; app.chart.setDataContext({ ...app.chart.getDataContext(), interval: '5m' });
    app.currentBars = bars(300, 20); app.chart.primarySeries().setData(app.currentBars);
    app.chart2.primarySeries().setData(bars(3600, 5));
    app.replayReadoutValues = null;
    const setValues = app.symbolLegend2.setValues.bind(app.symbolLegend2);
    app.symbolLegend2.setValues = (values: any[]) => {
      app.replayReadoutValues = values.map(value => ({ ...value })); setValues(values);
    };
    return { time: start, views: [app.chart, app.chart2].map(chart => ({
      barSpacing: chart.timeScale.barSpacing, rightOffset: chart.timeScale.rightOffset,
    })) };
  });
  const time = seed.time;
  await page.locator('#chart').focus();
  await page.getByRole('button', { name: 'Replay this session bar by bar', exact: true }).click();
  await page.locator('#rp-pick-scope').click();
  await expect(page.locator('#rp-pick-scope')).toHaveText('All charts');
  await expect(page.locator('#chart2')).toHaveClass(/is-picking/);
  await page.evaluate(async () => {
    const path = '/examples/yfinance/src/replay.js'; await (await import(path)).startReplayAt(1);
  });
  const snapshot = () => page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { time: app.replay.state().time, scope: app.replay.state().scope,
      counts: [app.chart.primaryBars().length, app.chart2.primaryBars().length],
      volume: [app.volume.getData().length, app.volume2.getData().length],
      secondaryReadout: app.replayReadoutValues,
      secondaryClose: Number(app.replayReadoutValues?.find((value: any) => value.label === 'C')?.text) };
  });
  expect(await snapshot()).toMatchObject({ time: time + 600, scope: 'all', counts: [2, 0], volume: [2, 0], secondaryReadout: [] });
  expect(await page.locator('#replaybar').evaluate(node => node.parentElement?.id)).toBe('split');
  // No finer bars arrive, so each 5-minute candle forms over five simulated
  // one-minute steps: one step forward is a minute, and the forming candle shows.
  await page.locator('#rp-fwd').focus(); await page.keyboard.press('Enter');
  expect(await snapshot()).toMatchObject({ time: time + 660, counts: [3, 0] });
  await page.locator('#chart2').focus();
  await page.locator('#rp-scope').click();
  expect(await snapshot()).toMatchObject({ time: time + 660, scope: 'focused', counts: [3, 5] });
  expect(await page.evaluate(() => {
    const scale = (window as any).__oac.app.chart2.timeScale;
    return { barSpacing: scale.barSpacing, rightOffset: scale.rightOffset };
  })).toEqual(seed.views[1]);
  await page.locator('#rp-scope').click();
  expect(await snapshot()).toMatchObject({ time: time + 660, scope: 'all', counts: [3, 0] });
  await page.evaluate(start => (window as any).__oac.app.replay.seekTime(start + 3600), time);
  expect(await snapshot()).toMatchObject({ time: time + 3600, counts: [12, 1], volume: [12, 1], secondaryClose: 101 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-all-replay.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.locator('#replaybar').evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-all-replay-narrow.png') });
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Full screen chart', exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-fullscreen-pane', '2');
  await expect(page.locator('#replaybar')).toBeVisible();
  await page.locator('#rp-fwd').click();
  expect(await snapshot()).toMatchObject({ time: time + 3660, counts: [13, 1] });
  await page.locator('#rp-scope').click();
  await expect(page.locator('#replaybar')).toBeVisible();
  expect(await snapshot()).toMatchObject({ time: time + 3660, scope: 'focused', counts: [13, 5] });
  await page.locator('#rp-scope').click();
  expect(await snapshot()).toMatchObject({ time: time + 3660, scope: 'all', counts: [13, 1] });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-all-replay-fullscreen.png') });
  await page.getByRole('button', { name: 'Exit full screen (Esc)', exact: true }).click();
  await page.getByRole('button', { name: 'Close the second chart', exact: true }).click();
  await expect(page.locator('#replaybar')).toBeHidden();
  expect(await page.evaluate(() => (window as any).__oac.app.chart.primaryBars().length)).toBe(20);
  expect(await page.evaluate(() => {
    const scale = (window as any).__oac.app.chart.timeScale;
    return { barSpacing: scale.barSpacing, rightOffset: scale.rightOffset };
  })).toEqual(seed.views[0]);
  expect(errors).toEqual([]);
});

test('narrow chart legends keep whole close readings inside the plot', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  await page.evaluate(async () => {
    const source = '/dist/openalgo-charts.mjs';
    const { PaneLegend } = await import(source);
    const draw = PaneLegend.prototype.draw;
    (window as any).__legendReadings = [];
    PaneLegend.prototype.draw = function(ctx: CanvasRenderingContext2D, rc: any) {
      const fill = ctx.fillText;
      ctx.fillText = (text: string, x: number, y: number) => {
        (window as any).__legendReadings.push({ text, right: x + ctx.measureText(text).width, limit: rc.plotWidth * rc.dpr });
        fill.call(ctx, text, x, y);
      };
      try { draw.call(this, ctx, rc); } finally { ctx.fillText = fill; }
    };
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.mouse.move(5, 835);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const readings = await page.evaluate(() => (window as any).__legendReadings as { text: string; right: number; limit: number }[]);
  expect(readings.length).toBeGreaterThan(0);
  expect(readings.filter(reading => reading.right > reading.limit + 0.1)).toEqual([]);
  expect(readings.some(reading => reading.text === 'C')).toBe(true);
  await page.screenshot({ path: info.outputPath('reference-compact-readouts.png') });
});

test('fullscreen follows the selected chart and retains shared controls and dialogs', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Full screen chart', exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-fullscreen-pane', '2');
  expect(await page.evaluate(() => document.fullscreenElement === document.body)).toBe(true);
  const geometry = await page.evaluate(() => ({ height: document.body.getBoundingClientRect().height, viewport: window.innerHeight }));
  expect(geometry.height).toBeGreaterThanOrEqual(geometry.viewport - 1);
  await expect(page.locator('#chart')).toBeHidden();
  await expect(page.locator('#chart2')).toBeVisible();
  await expect(page.locator('#shellbar')).toBeVisible();
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await expect(page.locator('#chartset')).toBeVisible();
  await page.screenshot({ path: info.outputPath('reference-fullscreen-settings.png') });
  await page.locator('#cset-x').click();
  await page.getByRole('button', { name: /^Selected chart, / }).click();
  await page.getByRole('menuitemradio', { name: 'Chart 1', exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-fullscreen-pane', '1');
  await expect(page.locator('#chart')).toBeVisible();
  await expect(page.locator('#chart2')).toBeHidden();
  await page.getByRole('button', { name: 'Exit full screen (Esc)', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  await expect(page.locator('#chart2')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#shellbar').evaluate(node => { node.scrollLeft = node.scrollWidth; });
  const selector = await page.getByRole('button', { name: /^Selected chart, / }).boundingBox();
  expect(selector?.x).toBeGreaterThanOrEqual(0);
  expect((selector?.x || 0) + (selector?.width || 0)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('reference-sticky-chart-selector.png') });
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Full screen chart', exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-fullscreen-pane', '2');
  await page.getByRole('button', { name: 'Close the second chart', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  expect(await page.locator('#rail').evaluate(node => node.parentElement?.matches('main.stage'))).toBe(true);
  expect(await page.locator('#mobilebar').evaluate(node => node.parentElement?.matches('main.stage'))).toBe(true);
});

test('shared replay keeps its selected chart owner through focus changes and exit', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  await page.route('**/api/history?**', route => new URL(route.request().url()).searchParams.get('interval') === '15m'
    ? route.fulfill({ json: [] }) : route.continue());
  const before = await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.chart.primaryBars().length, app.chart2.primaryBars().length];
  });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Replay this session bar by bar', exact: true }).click();
  await expect(page.locator('#chart2')).toHaveClass(/is-picking/);
  await expect(page.locator('#chart')).not.toHaveClass(/is-picking/);
  await page.locator('#chart').focus();
  await page.evaluate(async () => {
    const source = '/examples/yfinance/src/replay.js';
    await (await import(source)).startReplayAt(20);
  });
  await expect(page.locator('#replaybar')).toBeVisible();
  await expect(page.locator('#rp-owner')).toHaveText(/Chart 2/);
  const during = await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.chart.primaryBars().length, app.chart2.primaryBars().length, app.replayTarget.pane];
  });
  expect(during).toEqual([before[0], 21, 2]);
  // With finer history unavailable, each 1-hour candle forms over four simulated
  // observations, so observation 25 falls in the seventh candle.
  await page.locator('#rp-scrub').fill('25');
  await page.locator('#rp-scrub').dispatchEvent('input');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.primaryBars().length)).toBe(7);
  await page.screenshot({ path: info.outputPath('reference-owned-replay.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.locator('#replaybar').evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath('reference-owned-replay-narrow.png') });
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.getByRole('button', { name: 'Exit replay', exact: true }).click();
  await page.locator('#rp-leave-go').click();
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.chart.primaryBars().length, app.chart2.primaryBars().length];
  })).toEqual(before);
  await expect(page.locator('#replaybar')).toBeHidden();
});

test('pointer replay selection locks both charts and closing its owner cancels pending history', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  let release!: () => void;
  let started!: () => void;
  const waiting = new Promise<void>(resolve => { started = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/history?**', async route => {
    if (new URL(route.request().url()).searchParams.get('interval') !== '15m') { await route.continue(); return; }
    started();
    await gate;
    await route.fulfill({ json: [] }).catch(() => {});
  });
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.replayDeliveries = [];
    for (const pane of [1, 2]) {
      const chart = pane === 1 ? app.chart : app.chart2;
      chart.on('alert:triggered', (event: any) => app.replayDeliveries.push(event));
      (pane === 1 ? app.alerts : app.alerts2).add({ source: { kind: 'price', price: 1 }, condition: 'greaterThan', policy: 'onTouch' });
    }
  });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Replay this session bar by bar', exact: true }).click();
  const box = (await page.locator('#chart2').boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 3);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 3);
  await waiting;
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    for (const chart of [app.chart, app.chart2]) {
      const tail = chart.primaryBars().at(-1);
      chart.primarySeries().update({ ...tail, close: tail.close + 1, high: tail.high + 1 });
    }
    const source = '/examples/yfinance/src/orders.js';
    (await import(source)).placeOrder('BUY', 'MARKET', 100);
    return { pane: app.replayTarget.pane, loading: app.replayLoading, orders: app.orders.length, fired: app.replayDeliveries.length };
  })).toEqual({ pane: 2, loading: true, orders: 0, fired: 0 });
  await page.locator('#chart').focus();
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.replayLoading)).toBe(true);
  await page.getByRole('button', { name: 'Close the second chart', exact: true }).click();
  release();
  await page.unrouteAll({ behavior: 'wait' });
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { chart: app.chart2, replay: app.replay, owner: app.replayTarget, loading: app.replayLoading };
  })).toEqual({ chart: null, replay: null, owner: null, loading: false });
});

test('destroying a chart during active replay releases the transport and clock', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 30 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus();
  expect(await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const source = '/examples/yfinance/src/replay.js';
    await (await import(source)).startReplayAt(20);
    const replay = app.replay;
    replay.play();
    app.chart2.destroy();
    return { playing: replay.state().playing, replay: app.replay, owner: app.replayTarget };
  })).toEqual({ playing: false, replay: null, owner: null });
  await expect(page.locator('#replaybar')).toBeHidden();
});

test('comparison charts use independent scales with a common start and honest missing overlap', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: 'Compare a second symbol', exact: true }).click();
  for (const symbol of ['TSLA', 'NVDA']) {
    await page.locator('#cmp-sym').fill(symbol);
    await page.locator('#cmp-add').click();
    await expect(page.locator('#cmp-list')).toContainText(symbol);
  }
  expect(await page.evaluate(async () => {
    const source = '/dist/openalgo-charts.mjs';
    const lib = await import(source);
    return lib.comparisonController((window as any).__oac.chart).baseline;
  })).toBe('common');
  await page.locator('#cmp-close').click();
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const primary = app.chart.primaryBars();
    const source = '/examples/yfinance/src/compare.js';
    const { indexCompare } = await import(source);
    app.comparisons.forEach((spec: any, offset: number) => {
      const base = offset ? 50000 : 1000;
      spec.bars = primary.slice(0, 9).filter((_: any, index: number) => index !== (offset ? 0 : 1))
        .map((bar: any) => {
          const price = base * (1 + primary.indexOf(bar) * 0.02);
          return { time: bar.time, open: price, high: price, low: price, close: price };
        });
      indexCompare(spec);
      spec.handle.setBars(spec.bars);
    });
    app.chart.setVisibleLogicalRange({ from: 0, to: 8 });
  });
  await page.waitForFunction(() => (window as any).__oac.app.comparisons[0].handle.priceScale().baseline === 1040);
  const coordinates = await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const [a, b] = app.comparisons.map((spec: any) => spec.handle);
    const primary = app.chart.panes()[0].priceScale;
    const source = '/dist/openalgo-charts.mjs';
    const lib = await import(source);
    return { independent: a.priceScale() !== b.priceScale(),
      sameStart: lib.comparisonController(app.chart).baselineTime() === app.chart.primaryBars()[2].time,
      difference: Math.abs(a.priceScale().priceToY(1160) - b.priceScale().priceToY(58000)),
      primaryDifference: Math.abs(a.priceScale().priceToY(1160) - primary.priceToY(primary.baseline * 1160 / 1040)) };
  });
  expect(coordinates.independent).toBe(true);
  expect(coordinates.sameStart).toBe(true);
  expect(coordinates.difference).toBeLessThan(0.001);
  expect(coordinates.primaryDifference).toBeLessThan(0.001);
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    app.comparisonReadings = [];
    app.comparisons.forEach((spec: any, index: number) => {
      const update = spec.legend.setValues.bind(spec.legend);
      spec.legend.setValues = (values: any[]) => { app.comparisonReadings[index] = values; update(values); };
    });
    const source = '/examples/yfinance/src/compare.js';
    (await import(source)).setCompareLegends(app.chart.primaryBars()[8]);
  });
  expect(await page.evaluate(() => (window as any).__oac.app.comparisonReadings.every((values: any[]) => values.length > 0))).toBe(true);
  await page.screenshot({ path: info.outputPath('reference-common-comparison.png') });
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.comparisons.forEach((spec: any, index: number) => spec.handle.setBars([spec.bars[index]]));
  });
  await page.getByRole('button', { name: 'Comparing TSLA, NVDA, Compare', exact: true }).click();
  await expect(page.locator('#cmp-list')).toContainText('No common starting bar');
  expect(await page.evaluate(() => (window as any).__oac.app.comparisons.every((spec: any) =>
    spec.handle.series.getData().every((bar: any) => !Number.isFinite(bar.close))))).toBe(true);
  expect(await page.evaluate(() => (window as any).__oac.app.comparisonReadings.every((values: any[]) => values.length === 0))).toBe(true);
  await page.screenshot({ path: info.outputPath('reference-no-common-comparison.png') });
});

test('comparison controls retain chart ownership and saved visibility through reload', async ({ page }, info) => {
  const faults: string[] = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Compare a second symbol', exact: true }).click();
  await expect(page.locator('#cmp-title')).toHaveText('Compare symbols: Chart 2');
  await page.locator('#cmp-sym').fill('TSLA');
  await page.locator('#cmp-add').click();
  await expect(page.locator('#cmp-list')).toContainText('TSLA');
  await expect(page.locator('#cmp-list')).toContainText('matched');
  await page.locator('#cmp-mode').selectOption('indexed-to-100');
  await page.locator('#chart').focus();
  await page.locator('#cmp-sym').fill('NVDA');
  await page.locator('#cmp-add').click();
  await expect(page.locator('#cmp-list')).toContainText('NVDA');
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { first: app.comparisons.map((item: any) => item.symbol), second: app.comparisons2.map((item: any) => item.symbol),
      mode: app.cmpMode2, source: app.comparisons2[0].dataKey };
  })).toEqual({ first: [], second: ['TSLA', 'NVDA'], mode: 'indexed-to-100', source: expect.stringContaining('1h') });
  await page.screenshot({ path: info.outputPath('reference-owned-comparisons.png') });
  await page.getByRole('button', { name: 'Remove NVDA', exact: true }).click();
  await page.locator('#cmp-close').click();
  await page.evaluate(() => {
    const app = (window as any).__oac.app;
    app.chart2.emit('click', { id: 'cmp:TSLA::hide' });
  });
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.comparisons2?.[0]?.handle && !app.loading && !app.loading2 && !app.restoringSecondary;
  });
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { first: app.comparisons.length, symbol: app.comparisons2[0].symbol, hidden: app.comparisons2[0].hidden,
      visible: app.chart2.panes()[0].series().find((series: any) => series.style.color === app.comparisons2[0].color)?.style.visible, mode: app.cmpMode2 };
  })).toEqual({ first: 0, symbol: 'TSLA', hidden: true, visible: false, mode: 'indexed-to-100' });
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  expect(faults).toEqual([]);
  await page.getByRole('button', { name: 'Comparing TSLA, Compare', exact: true }).click();
  await page.getByRole('button', { name: 'Remove TSLA', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.comparisons2.length)).toBe(0);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.panes()[0].priceScale.options.mode)).toBe('linear');
});

test('comparison history failures remain visible and retry uses its own chart interval', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Compare a second symbol', exact: true }).click();
  await page.locator('#cmp-sym').fill('TSLA');
  await page.locator('#cmp-add').click();
  await expect(page.locator('#cmp-list')).toContainText('matched');
  await page.locator('#cmp-close').click();
  const history = '**/api/history?**';
  await page.route(history, route => {
    const url = new URL(route.request().url());
    return url.searchParams.get('symbol') === 'TSLA' && url.searchParams.get('interval') === '15m'
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Comparison source unavailable' }) })
      : route.continue();
  });
  await page.locator('#shellbar .pills').getByRole('button', { name: '15M', exact: true }).click();
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return app.p2.interval === '15m' && !app.loading2 && app.comparisons2[0].error;
  });
  await page.getByRole('button', { name: 'Comparing TSLA, Compare', exact: true }).click();
  await expect(page.locator('#cmp-list')).toContainText('Comparison source unavailable');
  await expect(page.locator('#cmp-list').getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { primary: app.req.interval, bars: app.comparisons2[0].bars.length, handle: Boolean(app.comparisons2[0].handle) };
  })).toEqual({ primary: '1d', bars: 0, handle: false });
  await page.screenshot({ path: info.outputPath('reference-comparison-source-error.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  const modal = (await page.locator('#cmpmodal .set-card').boundingBox())!;
  const remove = (await page.getByRole('button', { name: 'Remove TSLA', exact: true }).boundingBox())!;
  expect(remove.x + remove.width).toBeLessThanOrEqual(modal.x + modal.width);
  await page.screenshot({ path: info.outputPath('reference-comparison-source-error-narrow.png') });
  await page.unroute(history);
  await page.locator('#cmp-list').getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('#cmp-list')).toContainText('matched');
  await expect(page.locator('#cmp-list').getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__oac.app.comparisons2[0].dataKey)).toContain('15m');
});

test('reference selection survives hover and snapshot menus retain their chart owner', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  const secondary = page.locator('#chart2');
  const primary = page.locator('#chart');
  const box = (await secondary.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.35);
  await expect(secondary).toHaveAttribute('data-chart-focused', 'true');
  const other = (await primary.boundingBox())!;
  await page.mouse.move(other.x + other.width * 0.4, other.y + other.height * 0.35);
  expect(await page.evaluate(() => (window as any).__oac.app.focusPane)).toBe(2);
  const edge = await page.screenshot({ clip: { x: box.x, y: box.y + 80, width: 3, height: 12 } });
  // The frame's colour as the page composites it over the chart: read from the
  // stylesheet, so the check follows the palette rather than pinning one.
  const frame = await page.evaluate(() => {
    const channels = (css: string): number[] => {
      const probe = document.createElement('canvas').getContext('2d')!;
      probe.fillStyle = css;
      probe.fillRect(0, 0, 1, 1);
      return Array.from(probe.getImageData(0, 0, 1, 1).data);
    };
    const [r, g, b, a] = channels(getComputedStyle(document.getElementById('chart2')!, '::after').borderTopColor);
    const [br, bg, bb] = channels(getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#000');
    const k = a! / 255;
    return [r! * k + br! * (1 - k), g! * k + bg! * (1 - k), b! * k + bb! * (1 - k)].map(Math.round);
  });
  const visibleSelection = await page.evaluate(async ([encoded, want]) => {
    const bytes = Uint8Array.from(atob(encoded), (value) => value.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d')!;
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let index = 0; index < pixels.length; index += 4) {
      if ([0, 1, 2].every((c) => Math.abs(pixels[index + c]! - want[c]!) <= 4)) return true;
    }
    return false;
  }, [edge.toString('base64'), frame] as const);
  expect(visibleSelection, 'selected chart border must paint above its canvas').toBe(true);
  await page.screenshot({ path: info.outputPath('reference-selected-chart.png') });
  await page.getByRole('button', { name: 'Chart snapshot', exact: true }).click();
  await primary.focus();
  await expect(primary).toHaveAttribute('data-chart-focused', 'true');
  const exported = page.waitForEvent('download');
  await page.locator('#snap-save').click();
  expect((await exported).suggestedFilename()).toMatch(/^MSFT-1h-.*\.png$/);
  const primaryExport = page.waitForEvent('download');
  await primary.focus();
  await page.keyboard.press('Control+Alt+s');
  expect((await primaryExport).suggestedFilename()).toMatch(/^AAPL-1d-.*\.png$/);
  expect(await page.evaluate(() => ({
    orders: (window as any).__oac.app.orders.length,
    fills: (window as any).__oac.app.fills.length,
  }))).toEqual({ orders: 0, fills: 0 });
});

test('shared request and type controls preserve independent charts through reload', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.locator('#chart2').focus();
  await expect(page.getByRole('button', { name: /^Change symbol, / })).toContainText('MSFT');
  await page.locator('#shellbar .pills').getByRole('button', { name: '15M', exact: true }).click();
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return app.p2.interval === '15m' && !app.loading2 && app.chart2.primaryBars().length > 0;
  });
  expect(await page.evaluate(() => (window as any).__oac.app.req.interval)).toBe('1d');
  await expect(page.getByRole('button', { name: 'Place a Buy OCO bracket: entry, target and stop', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Place a Sell OCO bracket: entry, target and stop', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: /^Change symbol, / }).click();
  await page.getByPlaceholder('Symbol or expression').fill('TSLA');
  await expect(page.getByRole('option', { name: /TSLA/ })).toBeVisible();
  await page.getByPlaceholder('Symbol or expression').press('Enter');
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return app.chart2.getDataContext().symbol === 'TSLA' && !app.loading2;
  });
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  await page.locator('.oac-pick__row[data-id="ema"]').click();
  const study = await page.evaluate(() => (window as any).__oac.app.chart2.indicators()[0]?.id);
  expect(study).toBeTruthy();
  await page.evaluate(async (id) => {
    const source = '/examples/yfinance/src/indicators.js';
    (await import(source)).openSettings(id);
  }, study);
  await expect(page.locator('#setmodal')).toBeVisible();
  await page.locator('#set-body [data-key="length"]').fill('9');
  await page.locator('#set-ok').click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.indicators()[0].settings().length)).toBe(9);
  await page.getByRole('button', { name: 'Grid', exact: true }).click();
  await page.getByRole('menuitemradio', { name: 'None', exact: true }).click();
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.chart.gridOptions().vertLines, app.chart2.gridOptions().vertLines];
  })).toEqual([true, false]);
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.locator('#chart').focus();
  await expect(page.getByRole('button', { name: 'Place a Buy OCO bracket: entry, target and stop', exact: true })).toBeEnabled();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { primary: app.chart.getState().series[0].type, secondary: app.chart2.getState().series[0].type,
      symbol: app.req.symbol, study: app.chart2.indicators()[0].id };
  })).toEqual({ primary: 'candlestick', secondary: 'line', symbol: 'AAPL', study });
  await page.locator('#chart2').focus();
  await expect(page.getByRole('button', { name: /^Chart type, / })).toContainText('Line');
  await expect(page.locator('#p2bar .pills')).toHaveCount(0);
  const primaryView = await page.evaluate(() => (window as any).__oac.app.chart.getVisibleLogicalRange());
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.chart2?.primaryBars().length > 0 && !app.loading && !app.loading2 && !app.restoringSecondary;
  });
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return { request: app.p2.symbol + '/' + app.p2.interval, type: app.chart2.getState().series[0].type,
      study: app.chart2.indicators()[0].id, length: app.chart2.indicators()[0].settings().length,
      grid: app.chart2.gridOptions().vertLines, selected: app.focusPane };
  })).toEqual({ request: 'TSLA/15m', type: 'line', study, length: 9, grid: false, selected: 2 });
  const restoredView = await page.evaluate(() => (window as any).__oac.app.chart.getVisibleLogicalRange());
  expect(restoredView.from).toBeCloseTo(primaryView.from, 5);
  expect(restoredView.to).toBeCloseTo(primaryView.to, 5);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.exportSVG())).toContain('TSLA');
  await page.screenshot({ path: info.outputPath('reference-shared-controls.png') });
});

test('chart settings retain their selected owner through cancel, rebuild and reload', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const firstView = await page.evaluate(() => {
    const chart = (window as any).__oac.app.chart2;
    return { ...chart.timeScale.getVisibleLogicalRange(), count: chart.primaryBars().length, spacing: chart.timeScale.barSpacing };
  });
  // A freshly opened follower restores its own default view: the latest bar at
  // the default candle density, not its whole history fitted. This asserted the
  // fitted view until the density change, which updated the other hosts' tests
  // and missed this one.
  expect(firstView.to).toBeGreaterThanOrEqual(firstView.count - 1);
  expect(firstView.spacing).toBe(8);
  await page.locator('#chart2').focus();
  const settings = page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true });
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Readout', exact: true }).click();
  await page.locator('[data-key="statusLine.titleMode"]').selectOption('description');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.statusLineOptions().titleMode)).toBe('description');
  expect(await page.evaluate(() => (window as any).__oac.app.chart.statusLineOptions().titleMode)).not.toBe('description');
  await page.locator('#chart').focus();
  await page.locator('#cset-cancel').click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.statusLineOptions().titleMode)).toBe('symbol');
  await page.locator('#chart2').focus();
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Readout', exact: true }).click();
  await page.locator('[data-key="statusLine.titleMode"]').selectOption('description');
  await page.locator('[data-key="statusLine.barChange"]').uncheck();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Axes', exact: true }).click();
  await page.locator('[data-key="time.timezone"]').selectOption('UTC');
  await page.locator('#cset-ok').click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart.timezone())).toBe('Asia/Kolkata');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.timezone())).toBe('UTC');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.exportSVG())).toContain('Microsoft Corporation');
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.statusLineOptions().barChange)).toBe(false);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const secondaryView = await page.evaluate(() => (window as any).__oac.app.chart2.timeScale.getVisibleLogicalRange());
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.restoringSecondary);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.timezone())).toBe('UTC');
  expect(await page.evaluate(() => (window as any).__oac.app.chart.timezone())).toBe('Asia/Kolkata');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.statusLineOptions().titleMode)).toBe('description');
  const secondaryRestored = await page.evaluate(() => (window as any).__oac.app.chart2.timeScale.getVisibleLogicalRange());
  expect(secondaryRestored.from).toBeCloseTo(secondaryView.from, 5);
  expect(secondaryRestored.to).toBeCloseTo(secondaryView.to, 5);
  await page.mouse.move(5, 895);
  await page.screenshot({ path: info.outputPath('reference-owned-settings.png') });
  await settings.click();
  await page.evaluate(async () => { const source = '/examples/yfinance/src/split.js'; (await import(source)).closeSplit(); });
  await expect(page.locator('#chartset')).toBeHidden();
  expect(await page.evaluate(() => (window as any).__oac.app.chart.statusLineOptions().titleMode)).not.toBe('description');
});

test('reference volume settings follow each chart and update their own average', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Volume', exact: true }).click();
  await page.locator('[data-key="volume.showMA"]').check();
  await page.locator('[data-key="volume.maPeriod"]').fill('3');
  await page.locator('[data-key="volume.maPeriod"]').press('Tab');
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const colorFace = await page.locator('[data-key="volume.maColor"] + .oac-color__trigger').screenshot();
  const colorPixels = await page.evaluate(async encoded => {
    const bitmap = await createImageBitmap(new Blob([Uint8Array.from(atob(encoded), value => value.charCodeAt(0))], { type: 'image/png' }));
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width; canvas.height = bitmap.height;
    const context = canvas.getContext('2d')!;
    context.drawImage(bitmap, 0, 0); bitmap.close();
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let at = 0; at < data.length; at += 4) {
      if (data[at] === 230 && data[at + 1] === 181 && data[at + 2] === 60) count++;
    }
    return count;
  }, colorFace.toString('base64'));
  expect(colorPixels, 'colour control must show the selected colour').toBeGreaterThan(20);
  await page.screenshot({ path: info.outputPath('reference-volume-settings.png') });
  await page.locator('#cset-tabs').getByRole('button', { name: 'Price', exact: true }).click();
  await page.locator('[data-key="symbol.upColor"]').fill('#11aa22');
  await page.locator('[data-key="symbol.downColor"]').fill('#cc3344');
  await page.locator('#cset-ok').click();
  const result = await page.evaluate(() => {
    const app = (window as any).__oac.app;
    const time = app.chart2.primaryBars()[0].time;
    const bars = [10, 20, 30, 40].map((volume, index) => ({
      time: time + index * 3600, open: 100, high: 103, low: 97, close: index % 2 ? 99 : 101, volume,
    }));
    app.chart2.primarySeries().setData(bars);
    const initial = app.volumeMA2.getData().map((bar: any) => bar.close);
    const colors = app.volume2.getData().map((bar: any) => bar.color);
    app.chart2.primarySeries().update({ ...bars[3], volume: 60 });
    const replaced = app.volumeMA2.getData().at(-1).close;
    app.chart2.primarySeries().update({ ...bars[3], time: time + 4 * 3600, volume: 50 });
    return { initial, colors, replaced, appended: app.volumeMA2.getData().at(-1).close,
      sharedScale: app.volumeMA2.priceScale() === app.volume2.priceScale(),
      primaryAverage: app.volumeMA.getData().length };
  });
  expect(result.initial).toEqual([NaN, NaN, 20, 30]);
  expect(result.colors).toEqual(['#11aa22', '#cc3344', '#11aa22', '#cc3344']);
  expect(result.replaced).toBeCloseTo(110 / 3);
  expect(result.appended).toBeCloseTo(140 / 3);
  expect(result.sharedScale).toBe(true);
  expect(result.primaryAverage).toBe(0);
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    await app.loadSecondary();
    const path = '/examples/yfinance/src/split.js';
    (await import(path)).withoutViewportSync(() => app.chart2.resetScale());
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.restoringSecondary);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.primarySeriesInfo().style.upColor)).toBe('#11aa22');
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.primarySeriesInfo().style.downColor)).toBe('#cc3344');
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Volume', exact: true }).click();
  await expect(page.locator('[data-key="volume.showMA"]')).toBeChecked();
  await expect(page.locator('[data-key="volume.maPeriod"]')).toHaveValue('3');
  await page.locator('[data-key="volume.visible"]').uncheck();
  await page.locator('#cset-ok').click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart.getState().series.filter((series: any) => series.type === 'histogram')[0].style.visible)).not.toBe(false);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.getState().series.filter((series: any) => series.priceScaleId === '').every((series: any) => series.style.visible === false))).toBe(true);
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Volume', exact: true }).click();
  await page.locator('[data-key="volume.visible"]').check();
  await page.locator('#cset-ok').click();
  await page.mouse.move(5, 895);
  await page.locator('#shellbar').evaluate(element => { element.scrollLeft = 0; });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('reference-volume-average.png') });
  for (const theme of ['dark', 'light']) {
    await page.evaluate(async (name) => {
      const path = '/examples/yfinance/src/ui.js';
      (await import(path)).setTheme(name);
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }, theme);
    const box = (await page.locator('#chart2').boundingBox())!;
    const histogram = await page.screenshot({ clip: { x: box.x + 2, y: box.y + box.height * 0.82,
      width: box.width - 66, height: box.height * 0.14 } });
    const pixels = await page.evaluate(async encoded => {
      const bytes = Uint8Array.from(atob(encoded), value => value.charCodeAt(0));
      const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width; canvas.height = bitmap.height;
      const context = canvas.getContext('2d')!;
      context.drawImage(bitmap, 0, 0); bitmap.close();
      const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const counts = [0, 0];
      for (let at = 0; at < data.length; at += 4) {
        if (data[at] === 17 && data[at + 1] === 170 && data[at + 2] === 34) counts[0]++;
        if (data[at] === 204 && data[at + 1] === 51 && data[at + 2] === 68) counts[1]++;
      }
      return counts;
    }, histogram.toString('base64'));
    expect(pixels[0], theme + ' up-volume pixels').toBeGreaterThan(20);
    expect(pixels[1], theme + ' down-volume pixels').toBeGreaterThan(20);
    if (theme === 'light') await page.screenshot({ path: info.outputPath('reference-volume-average-light.png') });
  }
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Renko', exact: true }).click();
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Volume', exact: true }).click();
  await expect(page.locator('[data-key="volume.showMA"]')).toBeDisabled();
  await page.locator('#cset-ok').click();
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Candles', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.volumeMA2.getData().length)).toBeGreaterThan(3);
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Heikin Ashi', exact: true }).click();
  expect(await page.evaluate(() => Boolean((window as any).__oac.app.volume2))).toBe(true);
  const transformed = await page.evaluate(() => {
    const app = (window as any).__oac.app, chart = app.chart2;
    const style = { upColor: chart.theme().upColor, downColor: chart.theme().downColor, ...chart.primarySeriesInfo().style };
    return { actual: app.volume2.getData().map((bar: any) => [bar.close, bar.color]),
      expected: chart.primaryBars().map((bar: any) => [bar.volume, bar.close >= bar.open ? style.upColor : style.downColor]),
      average: app.volumeMA2.getData().length, count: chart.primaryBars().length };
  });
  expect(transformed.actual).toEqual(transformed.expected);
  expect(transformed.average).toBe(transformed.count);
});

test('transformed price readout uses displayed candles', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Heikin Ashi', exact: true }).click();
  const reading = await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const path = '/examples/yfinance/src/ui.js';
    const { fmt } = await import(path);
    const bars = app.chart.primaryBars();
    const svg = new DOMParser().parseFromString(app.chart.exportSVG(), 'image/svg+xml');
    const texts = [...svg.querySelectorAll('text')].map(node => node.textContent);
    return { actual: texts[texts.indexOf('C') + 1],
      expected: fmt(bars.at(-1).close), volume: Boolean(app.volume) };
  });
  expect(reading.actual).toBe(reading.expected);
  expect(reading.volume).toBe(true);
});

test('calendar timezone settings refold only their owner after confirmation', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.locator('#chart2').focus();
  await page.locator('#shellbar .pills').getByRole('button', { name: '1MO', exact: true }).click();
  await page.waitForFunction(() => !(window as any).__oac.app.loading2 && (window as any).__oac.app.p2.interval === '1mo');
  await page.evaluate(() => { (window as any).__settingsOwner = (window as any).__oac.app.chart2; });
  const settings = page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true });
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Axes', exact: true }).click();
  await page.locator('[data-key="time.timezone"]').selectOption('UTC');
  await page.locator('#cset-cancel').click();
  expect(await page.evaluate(() => (window as any).__oac.app.chart2 === (window as any).__settingsOwner)).toBe(true);
  expect(await page.evaluate(() => (window as any).__oac.app.p2.timezone)).toBe('Asia/Kolkata');
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Axes', exact: true }).click();
  await page.locator('[data-key="time.timezone"]').selectOption('UTC');
  await page.locator('#cset-ok').click();
  await page.waitForFunction(() => !(window as any).__oac.app.loading2 && (window as any).__oac.app.chart2 !== (window as any).__settingsOwner);
  const firstTime = await page.evaluate(() => (window as any).__oac.app.chart2.primaryBars()[0].time);
  const first = new Date(firstTime * 1000);
  expect([first.getUTCDate(), first.getUTCHours(), first.getUTCMinutes()]).toEqual([1, 0, 0]);
  expect(await page.evaluate(() => (window as any).__oac.app.chart.timezone())).toBe('Asia/Kolkata');
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.restoringSecondary);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.primaryBars()[0].time)).toBe(firstTime);
  expect(await page.evaluate(() => (window as any).__oac.app.chart2.timezone())).toBe('UTC');
});

test('volume and daily readout follow the replay prefix without future readings', async ({ page }) => {
  // Keep every status field visible; compact fitting is covered separately.
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  const evidence = await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    const volumePath = '/examples/yfinance/src/volume.js';
    const replayPath = '/examples/yfinance/src/replay.js';
    const statusPath = '/examples/yfinance/src/status.js';
    const volume = await import(volumePath), replay = await import(replayPath), status = await import(statusPath);
    volume.applyVolumeSettings(1, { 'volume.showMA': true, 'volume.maPeriod': 3 });
    const count = app.chart.primaryBars().length;
    await replay.startReplayAt(10);
    const samples = [];
    const record = () => {
      const bars = app.chart.primaryBars();
      const expected = volume.volumeAverage(bars.map((bar: any) => ({ time: bar.time, close: bar.volume })), 3);
      samples.push({ times: bars.map((bar: any) => bar.time), volume: app.volume.getData(),
        average: app.volumeMA.getData(), expected, amounts: bars.map((bar: any) => bar.volume),
        reading: status.dayChangeReading(bars, app.chart.timezone())?.text,
        supplied: app.symbolLegend.options().status().lastDayChange?.text,
        svg: app.chart.exportSVG() });
    };
    record();
    app.replay.step(); record();
    app.replay.stepBack(); record();
    app.replay.seek(30); record();
    replay.exitReplay();
    return { samples, count, restored: app.volume.getData().length, restoredAverage: app.volumeMA.getData().length };
  });
  for (const sample of evidence.samples) {
    expect(sample.times.length).toBeGreaterThan(2);
    expect(sample.times.length).toBeLessThan(evidence.count);
    expect(sample.volume.map((bar: any) => bar.time)).toEqual(sample.times);
    expect(sample.volume.map((bar: any) => bar.close)).toEqual(sample.amounts);
    expect(sample.average.map((bar: any) => bar.close)).toEqual(sample.expected.map((bar: any) => bar.close));
    expect(sample.reading).toBeTruthy();
    expect(sample.supplied).toBe(sample.reading);
    expect(sample.svg).toContain(sample.reading!);
  }
  expect(evidence.restored).toBe(evidence.count);
  expect(evidence.restoredAverage).toBe(evidence.count);
});

test('secondary requests cancel stale history and retain the last saved source during loading', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  let release: (() => void) | undefined;
  let cancelled = 0;
  page.on('requestfailed', request => { if (request.url().includes('symbol=SLOW')) cancelled++; });
  await page.route('**/api/history**', async route => {
    if (new URL(route.request().url()).searchParams.get('symbol') !== 'SLOW') { await route.continue(); return; }
    const response = await route.fetch();
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ response });
  });
  const symbol = async (value: string) => {
    await page.getByRole('button', { name: /^Change symbol, / }).click();
    const input = page.getByPlaceholder('Symbol or expression');
    await input.fill(value);
    if (value === 'TSLA') await expect(page.getByRole('option', { name: /TSLA/ })).toBeVisible();
    else await expect(input).toHaveAttribute('aria-expanded', 'false');
    await input.press('Enter');
  };
  try {
    await symbol('SLOW');
    await expect.poll(() => Boolean(release)).toBe(true);
    expect(await page.evaluate(() => {
      const app = (window as any).__oac.app;
      return { loading: app.loading2, bars: app.chart2.primaryBars().length };
    })).toEqual({ loading: true, bars: 0 });
    await expect(page.getByRole('button', { name: /^Chart type, / })).toBeDisabled();
    await page.evaluate(async () => {
      const source = '/examples/yfinance/src/persist.js';
      (await import(source)).flushAutosave();
    });
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('oa-charts:layout')!).secondary.request.symbol)).toBe('MSFT');
    await symbol('TSLA');
    await page.waitForFunction(() => {
      const app = (window as any).__oac.app;
      return app.chart2.getDataContext().symbol === 'TSLA' && !app.loading2 && app.chart2.primaryBars().length > 0;
    });
    await expect.poll(() => cancelled).toBe(1);
    release?.();
    release = undefined;
    await symbol('SLOW');
    await expect.poll(() => Boolean(release)).toBe(true);
    await page.getByRole('button', { name: 'Close the second chart', exact: true }).click();
    await expect.poll(() => cancelled).toBe(2);
    release?.();
    release = undefined;
    expect(await page.evaluate(() => {
      const app = (window as any).__oac.app;
      return { secondary: app.chart2, loading: app.loading2, selected: app.focusPane, primary: app.req.symbol,
        orders: app.orders.length, fills: app.fills.length };
    })).toEqual({ secondary: null, loading: false, selected: 1, primary: 'AAPL', orders: 0, fills: 0 });
  } finally {
    release?.();
  }
});

test('reference interval sync is optional and follows the selected chart', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  expect(await page.evaluate(() => (window as any).__oac.app.linkGroup.options().interval)).toBe(false);
  await page.locator('#chart2').focus();
  await page.getByRole('button', { name: /^Chart linking \(/ }).click();
  await page.getByRole('menuitemcheckbox', { name: /^Interval/ }).click();
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return app.req.interval === app.p2.interval && !app.loading && !app.loading2;
  });
  await page.locator('#shellbar .pills').getByRole('button', { name: '30M', exact: true }).click();
  await page.waitForFunction(() => {
    const app = (window as any).__oac.app;
    return app.req.interval === '30m' && app.p2.interval === '30m' && !app.loading && !app.loading2;
  });
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.chart2?.primaryBars().length > 0 && !app.loading && !app.loading2 && !app.restoringSecondary;
  });
  expect(await page.evaluate(() => (window as any).__oac.app.linkGroup.options().interval)).toBe(true);
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.req.interval, app.p2.interval];
  })).toEqual(['30m', '30m']);
  await page.getByRole('button', { name: /^Chart linking \(/ }).click();
  await page.getByRole('menuitemcheckbox', { name: /^Interval/ }).click();
  await page.locator('#chart').focus();
  await page.locator('#shellbar .pills').getByRole('button', { name: '1D', exact: true }).click();
  await page.waitForFunction(() => !(window as any).__oac.app.loading);
  expect(await page.evaluate(() => {
    const app = (window as any).__oac.app;
    return [app.req.interval, app.p2.interval, app.linkGroup.options().interval];
  })).toEqual(['1d', '30m', false]);
});

for (const pane of [1, 2]) {
  test(`reference context alert creation stays on chart ${pane}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1360, height: 900 });
    await openDemo(page);
    if (pane === 2) {
      await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
      await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
    }
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const point = await page.evaluate(pane => {
      const app = (window as any).__oac.app;
      const chart = pane === 1 ? app.chart : app.chart2;
      const draw = pane === 1 ? app.draw : app.draw2;
      const box = document.querySelector(pane === 1 ? '#chart' : '#chart2')!.getBoundingClientRect();
      chart.panes()[0].priceScale.setAutoScale(false);
      chart.panes()[0].priceScale.setPriceRange({ min: 80, max: 160 });
      draw.add({ id: 'clicked-context', tool: 'horizontal-line', paneIndex: 0,
        points: [{ time: chart.primaryBars().at(-1).time, price: 120 }], style: {} });
      return { x: box.left + box.width * 0.45, y: box.top + chart.priceToCoordinate(120, 0) };
    }, pane);
    await page.mouse.click(point.x, point.y, { button: 'right' });
    await page.evaluate(pane => { (window as any).__oac.app.focusPane = pane === 1 ? 2 : 1; }, pane);
    await page.getByRole('menuitem', { name: 'Create drawing alert...', exact: true }).click();
    const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
    await expect(editor.getByLabel('Source', { exact: true })).toHaveValue('drawing');
    await expect(editor.getByLabel('Drawing', { exact: true })).toHaveValue('clicked-context');
    await editor.getByLabel('Name', { exact: true }).fill(`Chart ${pane} context`);
    await page.screenshot({ path: info.outputPath(`reference-context-${pane}.png`) });
    await editor.getByRole('button', { name: 'Save', exact: true }).click();
    const result = await page.evaluate(() => {
      const app = (window as any).__oac.app;
      return { primary: app.alerts.list(), secondary: app.alerts2?.list() ?? [], orders: app.orders.length };
    });
    expect(pane === 1 ? result.primary : result.secondary).toMatchObject([{ title: `Chart ${pane} context`,
      source: { kind: 'drawing', drawingId: 'clicked-context' }, scope: { symbol: pane === 1 ? 'AAPL' : 'MSFT' } }]);
    expect(pane === 1 ? result.secondary : result.primary).toEqual([]);
    expect(result.orders).toBe(0);
  });
}

test('reference oscillator context offers its study alert without price order actions', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await openDemo(page);
  const point = await page.evaluate(() => {
    const { chart } = (window as any).__oac;
    const study = chart.indicators().find((item: any) => item.indicatorId === 'rsi');
    const values = study.values().rsi;
    const range = chart.getVisibleLogicalRange();
    let index = Math.max(20, Math.ceil(range.from));
    while (index < Math.min(values.length - 1, range.to) && !(values[index] > 10 && values[index] < 90
      && [30, 50, 70].every(level => Math.abs(values[index] - level) > 8))) index++;
    const box = document.querySelector('#chart')!.getBoundingClientRect();
    return { x: box.left + chart.timeToCoordinate(chart.primaryBars()[index].time),
      y: box.top + chart.priceToCoordinate(values[index], study.paneIndex), id: study.id };
  });
  await page.mouse.click(point.x, point.y, { button: 'right' });
  await expect(page.getByRole('menuitem', { name: /Buy|Sell/ })).toHaveCount(0);
  await page.getByRole('menuitem', { name: 'Create study alert...', exact: true }).click();
  await expect(page.getByLabel('Study', { exact: true })).toHaveValue(point.id);
  await expect(page.getByLabel('Plot', { exact: true })).toHaveValue('rsi');
});

test('reference alerts retain drawing anchors through rebuild and reload', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 850 });
  await openDemo(page);
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.locator('.oac-alert-editor');
  await editor.locator('[data-key="title"] input').fill('Reference price');
  await editor.locator('[data-key="condition"] select').selectOption('greaterThan');
  await editor.locator('[data-key="price"] input').fill('1');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  const drawingId = await page.evaluate(() => {
    const { app } = (window as any).__oac;
    const tail = app.chart.primaryBars().at(-1);
    const drawing = app.draw.add({ tool: 'horizontal-line', paneIndex: 0,
      points: [{ time: tail.time, price: tail.close + 10 }], style: {} });
    app.alertUi.openEditor({ source: { kind: 'drawing', drawingId: drawing.id } });
    return drawing.id;
  });
  await editor.locator('[data-key="title"] input').fill('Reference drawing');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  const studyId = await page.evaluate(() => (window as any).__oac.chart.indicators().find((study: any) => study.indicatorId === 'rsi').id);
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  await editor.locator('[data-key="kind"] select').selectOption('indicator');
  await editor.locator('[data-key="instanceId"] select').selectOption(studyId);
  await editor.locator('[data-key="title"] input').fill('Reference study');
  await editor.locator('[data-key="condition"] select').selectOption('greaterThan');
  await editor.locator('[data-key="value"] input').fill('1');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await page.evaluate(() => (window as any).__oac.app.alertUi.close());
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Line', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.alerts.list().length)).toBe(3);
  expect(await page.evaluate(id => (window as any).__oac.chart.indicators().some((study: any) => study.id === id), studyId)).toBe(true);
  expect(await page.evaluate(id => Boolean((window as any).__oac.draw.get(id)), drawingId)).toBe(true);
  await page.evaluate(() => {
    const { app } = (window as any).__oac;
    const tail = app.chart.primaryBars().at(-1);
    app.price.update({ ...tail, time: tail.time + 86400 });
  });
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.alerts.list()[0].state)).toBe('triggered');
  // Write the layout now rather than waiting out the autosave debounce, which a
  // loaded machine can stretch past the reload.
  await page.evaluate(async () => { const path = '/examples/yfinance/src/persist.js'; (await import(path)).persistLayoutNow(); });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.alerts?.list().length === 3);
  expect(await page.evaluate(() => (window as any).__oac.app.alerts.list().find((alert: any) => alert.title === 'Reference study').source.instanceId)).toBe(studyId);
  expect(await page.evaluate(() => (window as any).__oac.app.alerts.list()[0].state)).toBe('triggered');
  expect(await page.evaluate(id => Boolean((window as any).__oac.draw.get(id)), drawingId)).toBe(true);
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await expect(page.locator('.oac-alerts')).toContainText('Reference drawing');
  await page.screenshot({ path: testInfo.outputPath('reference-alerts-desktop.png') });
  await page.setViewportSize({ width: 390, height: 740 });
  await expect(page.locator('.oac-alerts')).toBeVisible();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  await expect(editor).toBeVisible();
  const bounds = await editor.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath('reference-alerts-narrow.png') });
});

let serverUp: boolean | null = null;

test('reference alert dialogs do not commit a replay pick underneath them', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 850 });
  await openDemo(page);
  await page.evaluate(async () => {
    const path = '/examples/yfinance/src/replay.js';
    const replay = await import(path);
    replay.enterReplay();
    (window as any).__oac.app.alertUi.openEditor();
  });
  await page.locator('.oac-alert-editor').getByRole('button', { name: 'Save', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.replayPicking)).toBe(true);
});

test('reference replay loading and playback stay silent and cancellation leaves no late replay', async ({ page }) => {
  await openDemo(page);
  let release!: () => void;
  let started!: () => void;
  const waiting = new Promise<void>(resolve => { started = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/history?**', async route => {
    if (new URL(route.request().url()).searchParams.get('interval') !== '60m') { await route.continue(); return; }
    started();
    await gate;
    await route.fulfill({ json: [] }).catch(() => {});
  });
  await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    (window as any).__alertDeliveries = [];
    app.chart.on('alert:triggered', (event: any) => (window as any).__alertDeliveries.push(event));
    app.alerts.add({ source: { kind: 'price', price: 1 }, condition: 'greaterThan', policy: 'onTouch' });
    const path = '/examples/yfinance/src/replay.js';
    const replay = await import(path);
    void replay.startReplayAt(10);
  });
  await waiting;
  const loading = await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    const tail = app.chart.primaryBars().at(-1);
    app.price.update({ ...tail, close: tail.close + 1, high: tail.high + 1 });
    const path = '/examples/yfinance/src/orders.js';
    const orders = await import(path);
    orders.placeOrder('BUY', 'MARKET', tail.close);
    return { loading: app.replayLoading, orders: app.orders.length, fills: app.fills.length, fired: (window as any).__alertDeliveries.length };
  });
  expect(loading).toEqual({ loading: true, orders: 0, fills: 0, fired: 0 });
  await page.evaluate(async () => { const path = '/examples/yfinance/src/replay.js'; (await import(path)).exitReplay(); });
  release();
  await page.unrouteAll({ behavior: 'wait' });
  const state = await page.evaluate(async () => {
    const { app } = (window as any).__oac;
    const path = '/examples/yfinance/src/replay.js';
    const replay = await import(path);
    await replay.startReplayAt(10);
    app.replay.step();
    app.replay.seek(20);
    replay.exitReplay();
    return { loading: app.replayLoading, replay: app.replay, fired: (window as any).__alertDeliveries.length, state: app.alerts.list()[0].state };
  });
  expect(state).toEqual({ loading: false, replay: null, fired: 0, state: 'armed' });
});

test('reference second-chart alerts restore on reload and stay scoped to that chart', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 850 });
  await openDemo(page);
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0);
  await page.evaluate(() => { (window as any).__oac.app.focusPane = 2; });
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  await page.locator('.oac-alert-editor [data-key="title"] input').fill('Secondary alert');
  await page.locator('.oac-alert-editor').getByRole('button', { name: 'Save', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__oac.app.alerts.list().length)).toBe(0);
  expect(await page.evaluate(() => (window as any).__oac.app.alerts2.list()[0].scope.symbol)).toBe('MSFT');
  // Write the layout now rather than waiting out the autosave debounce, which a
  // loaded machine can stretch past the reload.
  await page.evaluate(async () => { const path = '/examples/yfinance/src/persist.js'; (await import(path)).persistLayoutNow(); });
  await page.reload();
  await page.waitForFunction(() => (window as any).__oac?.app.alerts2?.list().length === 1);
  expect(await page.evaluate(() => (window as any).__oac.app.alerts2.list()[0].title)).toBe('Secondary alert');
  await page.setViewportSize({ width: 390, height: 740 });
  await page.evaluate(() => (window as any).__oac.app.alertUi2.openEditor());
  const editor = page.locator('.oac-alert-editor');
  await expect(editor).toBeVisible();
  const bounds = await editor.boundingBox();
  expect(bounds!.width).toBeGreaterThan(300);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath('reference-secondary-alerts-narrow.png') });
});

test.use({
  viewport: { width: 390, height: 740 },
  hasTouch: true,
});

test.beforeEach(async ({ request }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then((response) => response.ok(), () => false);
  test.skip(!serverUp, 'the yfinance fixture server is not available');
});

async function openDemo(page: Page): Promise<void> {
  const pending = new Set<Request>();
  const failures: { url: string; error: string }[] = [];
  const responses: { url: string; status: number }[] = [];
  const pageErrors: string[] = [], consoleErrors: string[] = [];
  const started = Date.now();
  let domContentLoaded = false, loaded = false;
  const requested = (request: Request) => pending.add(request);
  const finished = (request: Request) => pending.delete(request);
  const failed = (request: Request) => {
    pending.delete(request);
    failures.push({ url: request.url(), error: request.failure()?.errorText || 'Request failed' });
  };
  const responded = (response: Response) => {
    if (response.status() >= 400) responses.push({ url: response.url(), status: response.status() });
  };
  const pageError = (error: Error) => { pageErrors.push(error.stack || error.message); };
  const consoleError = (message: ConsoleMessage) => { if (message.type() === 'error') consoleErrors.push(message.text()); };
  const domReady = () => { domContentLoaded = true; };
  const load = () => { loaded = true; };
  page.on('request', requested); page.on('requestfinished', finished); page.on('requestfailed', failed);
  page.on('response', responded); page.on('pageerror', pageError); page.on('console', consoleError);
  page.on('domcontentloaded', domReady); page.on('load', load);
  try {
    await page.goto(PAGE);
    await page.waitForFunction(() => {
      const host = (window as any).__oac;
      return Boolean(host && host.chart && host.draw && host.app.currentBars.length > 0);
    });
  } catch (error) {
    await test.info().attach('reference-boot-diagnostics', {
      contentType: 'application/json',
      body: JSON.stringify({ url: page.url(), elapsedMs: Date.now() - started, domContentLoaded, loaded,
        pending: [...pending].map(request => ({ url: request.url(), type: request.resourceType() })),
        failures, responses, pageErrors, consoleErrors }, null, 2),
    });
    throw error;
  } finally {
    page.off('request', requested); page.off('requestfinished', finished); page.off('requestfailed', failed);
    page.off('response', responded); page.off('pageerror', pageError); page.off('console', consoleError);
    page.off('domcontentloaded', domReady); page.off('load', load);
  }
}

test('compact touch controls draw, undo and navigate in portrait and landscape', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', (error) => errors.push(String(error)));
  await openDemo(page);

  const bar = page.locator('#mobilebar');
  await expect(bar).toBeVisible();
  await expect(page.locator('#rail')).toBeHidden();
  const sizes = await bar.locator('select, button').evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().height));
  expect(Math.min(...sizes)).toBeGreaterThanOrEqual(44);

  await page.locator('#mobile-draw').selectOption('trend-line');
  expect(await page.evaluate(() => (window as any).__oac.draw.activeTool())).toBe('trend-line');
  const chart = page.locator('#chart');
  const box = await chart.boundingBox();
  if (!box) throw new Error('the chart has no layout box');
  await page.touchscreen.tap(box.x + box.width * 0.28, box.y + box.height * 0.46);
  await page.touchscreen.tap(box.x + box.width * 0.58, box.y + box.height * 0.30);
  await expect.poll(() => page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(1);

  await page.locator('#mobile-cursor').click();
  await page.keyboard.press('Control+z');
  await expect.poll(() => page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(0);
  await expect(page.locator('#mobile-undo')).toBeDisabled();
  await expect(page.locator('#mobile-redo')).toBeEnabled();
  await page.locator('#mobile-redo').click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(1);
  await page.locator('#mobile-undo').click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(0);
  await page.locator('#mobile-redo').click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(1);

  const span = () => page.evaluate(() => {
    const range = (window as any).__oac.chart.getVisibleLogicalRange();
    return range.to - range.from;
  });
  const before = await span();
  await page.locator('#mobile-zoom-in').click();
  expect(await span()).toBeLessThan(before);

  await page.setViewportSize({ width: 740, height: 390 });
  await expect(bar).toBeVisible();
  const shell = await page.locator('#shellbar').boundingBox();
  const landscapeChart = await chart.boundingBox();
  expect(shell?.height).toBeLessThanOrEqual(54);
  expect(landscapeChart?.height).toBeGreaterThan(200);
  expect(await page.evaluate(() => (window as any).__oac.draw.drawings().length)).toBe(1);

  // A phone on its side keeps the touch bar; a tablet of the same width
  // class and a taller screen gets the rail back (the container-size rule).
  await page.setViewportSize({ width: 1024, height: 600 });
  await expect(bar).toBeHidden();
  await expect(page.locator('#rail')).toBeVisible();
  await page.setViewportSize({ width: 932, height: 430 });
  await expect(bar).toBeVisible();
  await page.getByRole('button', { name: 'Replay this session bar by bar' }).click();
  await expect(page.locator('#replaypick')).toBeVisible();
  const wideChart = await chart.boundingBox();
  if (!wideChart) throw new Error('the wide chart has no layout box');
  await page.touchscreen.tap(wideChart.x + wideChart.width * 0.4, wideChart.y + wideChart.height * 0.4);
  await expect(page.locator('#replaybar')).toBeVisible();
  const replayBox = await page.locator('#replaybar').boundingBox();
  const mobileBox = await bar.boundingBox();
  if (!replayBox || !mobileBox) throw new Error('the replay or mobile controls have no layout box');
  expect(replayBox.y + replayBox.height).toBeLessThanOrEqual(mobileBox.y);
  const magnetHit = await page.locator('#mobile-magnet').evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)?.closest('#mobile-magnet') === node;
  });
  expect(magnetHit).toBe(true);
  expect(errors).toEqual([]);
});

test('reduced motion makes wheel navigation settle in the input frame', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openDemo(page);
  const wheelSpacing = (selector: '#chart' | '#chart2', key: 'chart' | 'chart2') => page.locator(selector).evaluate((node, chartKey) => {
    const host = (window as any).__oac;
    const chart = chartKey === 'chart2' ? host.app.chart2 : host.chart;
    const before = chart.timeScale.barSpacing;
    const rect = node.getBoundingClientRect();
    node.dispatchEvent(new WheelEvent('wheel', {
      deltaY: -120,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      bubbles: true,
      cancelable: true,
    }));
    return {
      before,
      after: chart.timeScale.barSpacing,
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
    };
  }, key);

  const wheelFactor = Math.exp(Math.log(1.1) * 1.2);
  const primary = await wheelSpacing('#chart', 'chart');
  expect(primary.reduced).toBe(true);
  expect(primary.after).toBeCloseTo(primary.before * wheelFactor, 8);

  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => {
    const second = (window as any).__oac.app.chart2;
    return Boolean(second && second.dataLayer.length > 0);
  });
  const second = await wheelSpacing('#chart2', 'chart2');
  expect(second.after).toBeCloseTo(second.before * wheelFactor, 8);
});

test('watermark and host branding survive chart-type and profile-mode rebuilds', async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 800 });
  await openDemo(page);
  expect(await page.evaluate(() => (window as any).__oac.chart.watermarkOptions().visible)).toBe(false);
  await page.evaluate(() => {
    const { chart } = (window as any).__oac;
    chart.setWatermarkOptions({ visible: true, text: 'Research', opacity: 0.2, fontSize: 54 });
    chart.setBranding({ label: 'Research charts', href: 'https://example.com/charts' });
  });
  for (const type of ['Line', 'Point and figure']) {
    await page.getByRole('button', { name: /^Chart type, / }).click();
    await page.getByRole('menuitemradio', { name: type, exact: true }).click();
    await expect.poll(() => page.evaluate(() => (window as any).__oac.chart.watermarkOptions().text)).toBe('Research');
    expect(await page.evaluate(() => (window as any).__oac.chart.exportSVG())).toContain('Research');
    await expect(page.getByRole('link', { name: 'Research charts', exact: true })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Point and figure settings', exact: true }).click();
  await page.getByRole('button', { name: '1%', exact: true }).click();
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.chart.seriesTransform((window as any).__oac.chart.primarySeries()).options))
    .toMatchObject({ mode: 'percent', percent: 1 });
  expect(await page.evaluate(() => (window as any).__oac.chart.watermarkOptions())).toMatchObject({ visible: true, text: 'Research', opacity: 0.2, fontSize: 54 });
  await page.evaluate(() => {
    const { chart } = (window as any).__oac;
    chart.setWatermarkOptions(false);
    chart.setBranding(false);
  });
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Candles', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 740 });
  expect(await page.evaluate(() => (window as any).__oac.chart.watermarkOptions().visible)).toBe(false);
  expect(await page.evaluate(() => (window as any).__oac.chart.brandingOptions())).toBe(false);
  await expect(page.getByRole('link', { name: 'Research charts', exact: true })).toHaveCount(0);
});
