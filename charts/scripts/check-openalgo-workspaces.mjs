import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect } from '@playwright/test';

/** Actual host charts with the parent harness's deterministic transport. */
export async function checkWorkspaces({ page, check, reload, screenshot, orderCount, sendDepth }) {
  const ordersBefore = orderCount();
  const close = async () => {
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]') && getComputedStyle(document.body).pointerEvents !== 'none');
  };
  const menu = async () => {
    await page.getByRole('button', { name: 'Workspaces', exact: true }).click();
    await page.getByRole('dialog', { name: 'Chart workspaces' }).waitFor();
    await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled();
  };
  const ready = async count => { try { await page.waitForFunction(count => {
    const terminals = window.__compatTerminals.filter(t => !t.destroyed);
    if (document.querySelector('[data-workspace-active="false"]') || terminals.length !== count
      || terminals.some(t => !t.chart || !t.price?.getData().length)) return false;
    try { terminals.forEach(t => t.captureWorkspacePane(t.sk.replace('oa-trading-', ''))); return true; }
    catch { return false; }
  }, count); } catch (error) {
    const state = await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed).map(t => {
      try { return { key: t.sk, pane: t.captureWorkspacePane(t.sk.replace('oa-trading-', '')) }; }
      catch (error) {
        const invalid = [];
        const scan = (value, path) => {
          if (value === undefined || (typeof value === 'number' && !Number.isFinite(value))) invalid.push({ path, value: String(value) });
          else if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) scan(item, `${path}.${key}`);
        };
        scan({ chart: t.chart?.getState(), settings: t.chartSettingsSaved, drawings: t.draw?.toJSON() }, 'pane');
        return { key: t.sk, error: error.message, invalid, bars: t.price?.getData().length, context: t.chart?.getDataContext() };
      }
    }));
    throw new Error(`${error.message}\nGrid state: ${JSON.stringify(state)}`);
  } };
  const capture = () => page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart).map(t => t.captureWorkspacePane(t.sk.replace('oa-trading-', ''))));
  const download = async () => {
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
    const file = await pending;
    return JSON.parse(await readFile(await file.path(), 'utf8'));
  };
  const catalog = () => page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open('openalgo-chart-workspaces', 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result, transaction = db.transaction('catalogs', 'readonly');
      const read = transaction.objectStore('catalogs').get('oa-trading:compat');
      transaction.oncomplete = () => { db.close(); resolve(read.result); };
      transaction.onabort = () => { db.close(); reject(transaction.error); };
    };
  }));
  let saved;
  const equivalent = (actual, expected) => {
    assert.equal(actual.length, expected.length);
    for (let index = 0; index < actual.length; index++) {
      const a = actual[index].chart, b = expected[index].chart;
      // Fractional CSS grid tracks are rounded to canvas pixels on measurement.
      const spacing = Math.min(a.barSpacing, b.barSpacing);
      for (const endpoint of ['from', 'to'])
        assert(Math.abs(a.viewport[endpoint] - b.viewport[endpoint]) * spacing <= 1, `Pane ${index} viewport moved by more than one pixel`);
      assert(Math.abs(a.barSpacing - b.barSpacing) * (b.viewport.to - b.viewport.from) <= 1, `Pane ${index} spacing changed by more than one plot pixel`);
    }
    const canonical = panes => panes.map(pane => {
      const chart = { ...pane.chart };
      delete chart.viewport;
      delete chart.barSpacing;
      return { ...pane, chart: { ...chart, series: chart.series.map(series => ({ ...series, style: { ...series.style, visible: series.style.visible ?? true } })) } };
    });
    assert.deepEqual(canonical(actual), canonical(expected));
  };
  await check('workspace saves unequal grid geometry and every pane configuration', async () => {
    await page.getByRole('button', { name: /^Chart layout:/ }).click();
    await page.getByTitle('1 + 2', { exact: true }).click();
    await ready(3);
    await page.getByRole('button', { name: 'Chart sync', exact: true }).click();
    const viewport = page.getByRole('checkbox', { name: 'Time range', exact: true });
    if (await viewport.isChecked()) await viewport.click();
    const intervalSync = page.getByRole('checkbox', { name: 'Interval', exact: true });
    if (await intervalSync.isChecked()) await intervalSync.click();
    await page.keyboard.press('Escape');
    await page.evaluate(async () => {
      const terminals = window.__compatTerminals.filter(t => !t.destroyed && t.chart);
      for (const [index, t] of terminals.entries()) {
        t.setChartType('candlestick');
        t.setInterval(['5m', '15m', '1h'][index]);
      }
    });
    await ready(3);
    await page.evaluate(async () => {
      const terminals = window.__compatTerminals.filter(t => !t.destroyed && t.chart);
      await terminals[0].applyIndicatorTemplate([
        { indicatorId: 'ema', settings: { length: 9 }, paneIndex: 0, visible: true },
        { indicatorId: 'ema', settings: { length: 9 }, paneIndex: 0, visible: true },
        { indicatorId: 'rsi', settings: { length: 14 }, paneIndex: 1, visible: false },
        { indicatorId: 'rsi', settings: { length: 7 }, paneIndex: 1, visible: true },
      ], 'replace');
      const t = terminals[2];
      await t.setDrawTool(null);
      t.draw.add({ id: 'workspace-note', tool: 'text', paneIndex: 0,
        points: [{ time: t.rawBars.at(-2).time, price: 100 }], style: { color: '#4f8cff' }, text: { value: 'Workspace note' } });
      t.setMagnet(true);
      t.setDrawStay(true);
      terminals[1].setVolumeVisible(false);
      t.container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    });
    const before = await capture();
    const oscillators = await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)[0].chart.indicators().filter(study => study.indicatorId === 'rsi').map(study => ({ settings: study.settings(), values: study.values().rsi })));
    assert.deepEqual(oscillators.map(study => study.settings.length), [14, 7]);
    assert.notDeepEqual(oscillators[0].values, oscillators[1].values);
    await menu();
    await page.getByLabel('Workspace name', { exact: true }).fill('Three chart research');
    await page.getByRole('button', { name: 'Save as', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Workspace saved' }).waitFor();
    saved = await download();
    assert.deepEqual(saved.panes, before);
    assert.equal(saved.activePaneId, 'p2');
    assert.deepEqual(saved.layout.columnWeights, [1.4, 1]);
    assert.equal(saved.sync.interval, false);
    assert.equal(saved.sync.viewport, false);
    assert(!/"(?:apikey|apiKey|armed|orders|positions)"\s*:/.test(JSON.stringify(saved)));
    await close();
  });

  await check('workspace opens only a fully prepared grid and survives reload', async () => {
    await menu();
    await page.getByLabel('Workspace name', { exact: true }).fill('Clean workspace');
    await page.getByRole('button', { name: 'New workspace', exact: true }).click();
    await ready(1);
    await page.waitForFunction(() => document.querySelector('[data-workspace-active="true"]'));
    await close();
    await menu();
    await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: saved.name });
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await ready(3);
    await close();
    await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', saved.activePaneId);
    equivalent(await capture(), saved.panes);
    await expect(page.getByRole('switch', { name: 'One-Click', exact: true })).not.toBeChecked();
    const geometry = await page.locator('[data-workspace-active="true"]').evaluate(el => ({
      columns: el.style.gridTemplateColumns, areas: el.style.gridTemplateAreas,
    }));
    assert.equal(geometry.columns, '1.4fr 1fr');
    assert.equal(geometry.areas, '"cell0 cell1" "cell0 cell2"');
    await reload();
    await ready(3);
    await page.waitForFunction(() => document.querySelector('[data-workspace-active="true"]'));
    await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', saved.activePaneId);
    equivalent(await capture(), saved.panes);
    if (screenshot) await page.screenshot({ path: resolve(screenshot.replace(/\.png$/, '-workspace.png')), fullPage: true });
    assert.equal(orderCount(), ordersBefore);
  });

  await check('workspace autosave follows configuration changes and leaves market ticks out of persistence', async () => {
    await menu();
    await page.getByRole('checkbox', { name: 'Autosave chart changes' }).click();
    await expect.poll(async () => (await catalog()).autosave).toBe(true);
    await close();
    await page.evaluate(() => window.__compatTerminals.find(t => !t.destroyed && t.sk === 'oa-trading-p2').setVolumeVisible(false));
    await expect.poll(async () => (await catalog()).workspaces.find(item => item.id === saved.id).panes[2].volume).toBe(false);
    const revision = (await catalog()).revision;
    // A tick for the instrument the pane shows, whatever the groups before
    // this one left loaded there: a tick for an instrument no pane shows
    // never arrives, and proves nothing about persistence.
    const shown = await page.evaluate(() => { const { symbol, exchange } = window.__compatTerminals.find(t => !t.destroyed && t.sk === 'oa-trading-p2').sym; return { symbol, exchange }; });
    await sendDepth(shown.symbol, shown.exchange, 107);
    await page.waitForTimeout(1000);
    assert.equal((await catalog()).revision, revision);
    await menu();
    await page.getByRole('checkbox', { name: 'Autosave chart changes' }).click();
    await expect.poll(async () => (await catalog()).autosave).toBe(false);
    await close();
    await page.evaluate(() => window.__compatTerminals.find(t => !t.destroyed && t.sk === 'oa-trading-p2').setVolumeVisible(true));
    await page.waitForTimeout(1000);
    assert.equal((await catalog()).workspaces.find(item => item.id === saved.id).panes[2].volume, false);
    await menu();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect.poll(async () => (await catalog()).workspaces.find(item => item.id === saved.id).panes[2].volume).toBe(true);
    await close();
  });

  await check('workspace storage refusal preserves the visible grid and active catalog selection', async () => {
    const before = await capture(), stored = await catalog();
    await menu();
    await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: 'Clean workspace' });
    await page.evaluate(() => {
      window.__workspaceOriginalPut = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function(...args) {
        if (this.name === 'catalogs') throw new DOMException('Fixture workspace storage refused', 'QuotaExceededError');
        return window.__workspaceOriginalPut.apply(this, args);
      };
    });
    try {
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'Fixture workspace storage refused' }).first().waitFor();
      await ready(3);
      equivalent(await capture(), before);
      assert.deepEqual(await catalog(), stored);
      assert.equal(await page.locator('[data-workspace-active="false"]').count(), 0);
    } finally {
      await page.evaluate(() => { IDBObjectStore.prototype.put = window.__workspaceOriginalPut; });
    }
    await close();
  });

  await check('workspace rejects stale catalog activation and recovers after refresh', async () => {
    const before = await capture(), concurrent = await catalog();
    concurrent.revision++;
    concurrent.workspaces.find(item => item.id === saved.id).name = 'Research renamed in another tab';
    await menu();
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Open', exact: true })).toBeEnabled();
    await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: 'Clean workspace' });
    await page.evaluate(value => new Promise((resolve, reject) => {
      const request = indexedDB.open('openalgo-chart-workspaces', 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result, transaction = db.transaction('catalogs', 'readwrite');
        transaction.oncomplete = () => { db.close(); resolve(); };
        transaction.onabort = () => { db.close(); reject(transaction.error); };
        transaction.objectStore('catalogs').put(value, 'oa-trading:compat');
      };
    }), concurrent);
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: /changed in another session/i }).first().waitFor();
    await ready(3);
    equivalent(await capture(), before);
    assert.deepEqual(await catalog(), concurrent);
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Open', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await ready(1);
    await close();
    await menu();
    await page.getByLabel('Saved workspace', { exact: true }).selectOption(saved.id);
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await ready(3);
    await close();
    equivalent(await capture(), before);
  });

  await check('workspace history failure preserves the visible grid and catalog', async () => {
    const before = await capture(), stored = await catalog();
    await menu();
    await page.getByLabel('Saved workspace', { exact: true }).selectOption({ label: 'Clean workspace' });
    const unavailable = route => route.fulfill({ json: { status: 'success', data: [] } });
    await page.route('**/api/v1/history', unavailable);
    try {
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: /Workspace history is unavailable/i }).first().waitFor();
      await ready(3);
      equivalent(await capture(), before);
      assert.deepEqual(await catalog(), stored);
      assert.equal(await page.locator('[data-workspace-active="false"]').count(), 0);
    } finally {
      await page.unroute('**/api/v1/history', unavailable);
    }
    await close();
    assert.equal(orderCount(), ordersBefore);
  });

  await check('workspace cancellation destroys staged charts and keeps all order routes locked while loading', async () => {
    const stored = await catalog();
    const toolbarPane = await page.locator('[data-toolbar-pane]').getAttribute('data-toolbar-pane');
    await menu();
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Open', exact: true })).toBeEnabled();
    let requested;
    const started = new Promise(resolve => { requested = resolve; });
    const held = [];
    const delay = route => { held.push(route); requested(); };
    await page.route('**/api/v1/history', delay);
    try {
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      await started;
      assert(await page.locator('[data-workspace-active="false"]').count() > 0);
      await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
      await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', toolbarPane);
      await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('inert');
      const refused = await page.evaluate(async () => Promise.all(window.__compatTerminals.filter(t => !t.destroyed).map(async t => {
        try { await t.placeTicket({ symbol: 'BHEL', exchange: 'NSE', action: 'BUY', quantity: 1, product: 'MIS', pricetype: 'MARKET' }); return false; }
        catch (error) { return /workspace|loading/i.test(error.message); }
      })));
      assert(refused.every(Boolean));
      await page.getByRole('button', { name: 'Cancel workspace loading', exact: true }).click();
      await ready(3);
      await expect(page.locator('[data-toolbar-pane]')).not.toHaveAttribute('inert');
      assert.equal(await page.locator('[data-workspace-active="false"]').count(), 0);
      assert.deepEqual(await catalog(), stored);
    } finally {
      await Promise.all(held.map(route => route.abort('aborted')));
      await page.unroute('**/api/v1/history', delay);
    }
    await close();
    assert.equal(orderCount(), ordersBefore);
  });

  await check('workspace imports reject unsupported charts before catalog writes and restore a portable grid', async () => {
    await menu();
    const before = await catalog();
    const upload = async document => {
      const input = page.getByLabel('Import workspace JSON', { exact: true });
      await expect(input).toBeEnabled();
      await input.setInputFiles({ name: 'workspace.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(document)) });
    };
    await upload({ ...saved, panes: [] });
    await page.getByRole('alert').filter({ hasText: /at least one pane/i }).first().waitFor();
    assert.deepEqual(await catalog(), before);
    const unsupported = structuredClone(saved);
    unsupported.panes[0].interval = '17m';
    await upload(unsupported);
    await page.getByRole('alert').filter({ hasText: 'Unsupported workspace interval' }).first().waitFor();
    await ready(3);
    assert.deepEqual(await catalog(), before);
    await upload({ ...saved, name: 'Imported research' });
    await expect.poll(async () => (await catalog()).workspaces.some(item => item.name === 'Imported research')).toBe(true);
    await ready(3);
    await close();
    equivalent(await capture(), saved.panes);
    const imported = (await catalog()).workspaces.find(item => item.name === 'Imported research');
    assert.notEqual(imported.id, saved.id);
    assert.equal((await catalog()).activeWorkspaceId, imported.id);
    await page.setViewportSize({ width: 390, height: 844 });
    await menu();
    await page.getByRole('dialog', { name: 'Chart workspaces' }).evaluate(el => {
      for (const animation of el.getAnimations()) animation.finish();
    });
    const dimensions = await page.getByRole('dialog', { name: 'Chart workspaces' }).evaluate(el => ({ width: el.getBoundingClientRect().width, scroll: el.scrollWidth, client: el.clientWidth }));
    assert(dimensions.width <= 390 && dimensions.scroll <= dimensions.client + 1);
    if (screenshot) await page.screenshot({ path: resolve(screenshot.replace(/\.png$/, '-workspace-mobile.png')), fullPage: true, animations: 'disabled' });
    await close();
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal(orderCount(), ordersBefore);
  });

  await check('named layout changes preserve a surviving selection and replace a removed one', async () => {
    await page.locator('[data-workspace-active="true"] [data-chart-pane="p1"]').focus();
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', 'p1');
    await page.getByRole('button', { name: /^Chart layout:/ }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    await ready(2);
    await expect(page.locator('[data-toolbar-pane]')).toHaveCount(1);
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', 'p1');
    await page.getByRole('button', { name: 'Chart layout: 2 columns', exact: true }).click();
    await page.getByTitle('1 + 2', { exact: true }).click();
    await ready(3);
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', 'p1');
    await page.locator('[data-workspace-active="true"] [data-chart-pane="p2"]').focus();
    await page.getByRole('button', { name: /^Chart layout:/ }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    await ready(2);
    await expect(page.locator('[data-toolbar-pane]')).toHaveAttribute('data-toolbar-pane', 'p0');
    assert.equal(orderCount(), ordersBefore);
  });
}
