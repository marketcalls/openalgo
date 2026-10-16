import { expect, test } from '@playwright/test';
import { workspaceFixture } from '../helpers/workspace-fixture';

const modulePath = '/dist/openalgo-charts.workspace.mjs';

test('cancelling a pending activation aborts the catalog transaction and allows retry', async ({ page }) => {
  await page.goto('/tests/e2e/fixture.html');
  const result = await page.evaluate(async ({ modulePath, payload }) => {
    const { WorkspaceRepository, createIndexedDbWorkspaceStorage } = await import(modulePath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-cancelled-activation');
    const repo = new WorkspaceRepository(storage, 'account', { id: () => 'desk', now: () => 4000 });
    const doc = await repo.createWorkspace('Desk', payload);
    const controller = new AbortController();
    const original = IDBObjectStore.prototype.put;
    let failure = '';
    let puts = 0;
    IDBObjectStore.prototype.put = function (...args) {
      const request = original.apply(this, args);
      puts++;
      queueMicrotask(() => controller.abort(new Error('Activation cancelled')));
      return request;
    };
    try { await repo.openWorkspace(doc.id, { signal: controller.signal }); }
    catch (error) { failure = (error as Error).message; }
    finally { IDBObjectStore.prototype.put = original; }
    const after = await repo.load();
    await repo.openWorkspace(doc.id);
    const retry = await repo.load();
    await storage.close();
    return { failure, puts, after: { active: after.activeWorkspaceId, recent: after.recentWorkspaceIds, revision: after.revision }, retry: retry.activeWorkspaceId };
  }, { modulePath, payload: workspaceFixture() });
  expect(result).toEqual({ failure: 'Activation cancelled', puts: 1, after: { active: null, recent: [], revision: 1 }, retry: 'desk' });
});

test('saved layouts and repeated indicator templates survive a reload within their account', async ({ page }) => {
  await page.goto('/tests/e2e/fixture.html');
  const result = await page.evaluate(async ({ modulePath, payload }) => {
    const { WorkspaceRepository, createIndexedDbWorkspaceStorage } = await import(modulePath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-reload');
    let next = 0;
    const repo = new WorkspaceRepository(storage, 'account-a', { now: () => 4000, id: () => `doc-${++next}` });
    const doc = await repo.createWorkspace('Two charts', payload);
    await repo.openWorkspace(doc.id);
    await repo.createTemplate('Two averages', payload.panes[0].chart.indicators);
    await repo.setAutosave(true);
    const other = await new WorkspaceRepository(storage, 'account-b').load();
    await storage.close();
    return { otherCount: other.workspaces.length, saved: doc.id };
  }, { modulePath, payload: workspaceFixture() });
  expect(result).toEqual({ otherCount: 0, saved: 'doc-1' });
  await page.reload();
  const catalog = await page.evaluate(async modulePath => {
    const { WorkspaceRepository, createIndexedDbWorkspaceStorage } = await import(modulePath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-reload');
    const loaded = await new WorkspaceRepository(storage, 'account-a').load();
    await storage.close();
    return loaded;
  }, modulePath);
  expect(catalog.revision).toBe(4);
  expect(catalog.activeWorkspaceId).toBe('doc-1');
  expect(catalog.autosave).toBe(true);
  expect(catalog.workspaces[0].panes.map((pane: any) => pane.interval)).toEqual(['5m', '1h']);
  expect(catalog.templates[0].indicators.map((study: any) => [study.settings.period, study.visible])).toEqual([[9, true], [21, false]]);
});

test('two tabs cannot both commit a catalog based on the same revision', async ({ page, context }) => {
  const other = await context.newPage();
  await Promise.all([page.goto('/tests/e2e/fixture.html'), other.goto('/tests/e2e/fixture.html')]);
  for (const tab of [page, other]) await tab.evaluate(async modulePath => {
    const { createIndexedDbWorkspaceStorage } = await import(modulePath);
    (window as any).__workspaceStorage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-concurrency');
    await (window as any).__workspaceStorage.read('same-account');
  }, modulePath);
  const writes = await Promise.all([page, other].map((tab, i) => tab.evaluate(async autosave => {
    const storage = (window as any).__workspaceStorage;
    const catalog = { version: 1, revision: 1, workspaces: [], templates: [], recentWorkspaceIds: [], activeWorkspaceId: null, autosave };
    try { await storage.write('same-account', catalog, 0); return { status: 'saved', autosave }; }
    catch (error) { return { status: (error as Error).name, autosave }; }
  }, Boolean(i))));
  expect(writes.map(item => item.status).sort()).toEqual(['WorkspaceConflictError', 'saved']);
  const saved = await page.evaluate(() => (window as any).__workspaceStorage.read('same-account'));
  expect(saved.revision).toBe(1);
  expect(saved.autosave).toBe(writes.find(item => item.status === 'saved')!.autosave);
  await Promise.all([page, other].map(tab => tab.evaluate(() => (window as any).__workspaceStorage.close())));
});

test('stale, skipped and corrupt catalog revisions are not overwritten', async ({ page }) => {
  await page.goto('/tests/e2e/fixture.html');
  const result = await page.evaluate(async modulePath => {
    const { createIndexedDbWorkspaceStorage } = await import(modulePath);
    const name = 'workspace-rejected-writes';
    const storage = createIndexedDbWorkspaceStorage(indexedDB, name);
    const catalog = { version: 1, revision: 1, workspaces: [], templates: [], recentWorkspaceIds: [], activeWorkspaceId: null, autosave: false };
    await storage.write('account', catalog, 0);
    const errors: string[] = [];
    for (const [next, expected] of [[{ ...catalog, autosave: true }, 0], [{ ...catalog, revision: 5 }, 1]] as const) {
      try { await storage.write('account', next, expected); }
      catch (error) { errors.push((error as Error).name); }
    }
    const before = await storage.read('account');
    await storage.close();
    // Deliberately corrupt persisted input through another database client.
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const transaction = db.transaction('catalogs', 'readwrite');
        transaction.objectStore('catalogs').put({ version: 99, revision: 1 }, 'account');
        transaction.oncomplete = () => { db.close(); resolve(); };
        transaction.onabort = () => { db.close(); reject(transaction.error); };
      };
    });
    const reopened = createIndexedDbWorkspaceStorage(indexedDB, name);
    try { await reopened.write('account', { ...catalog, revision: 2 }, 1); }
    catch (error) { errors.push((error as Error).name); }
    const after = await reopened.read('account');
    await reopened.close();
    return { errors, before, after };
  }, modulePath);
  expect(result.errors).toEqual(['WorkspaceConflictError', 'WorkspaceDocumentError', 'WorkspaceDocumentError']);
  expect(result.before).toMatchObject({ revision: 1, autosave: false });
  expect(result.after).toEqual({ version: 99, revision: 1 });
});

test('closed adapters reject new work and release connections for database upgrades', async ({ page }) => {
  await page.goto('/tests/e2e/fixture.html');
  const result = await page.evaluate(async modulePath => {
    const { createIndexedDbWorkspaceStorage } = await import(modulePath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-lifecycle');
    await storage.read('account');
    // The adapter must release its connection on versionchange, without a host close.
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('workspace-lifecycle', 2);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => { request.result.close(); resolve(); };
    });
    let afterUpgrade = '';
    try { await storage.read('account'); } catch (error) { afterUpgrade = (error as Error).message; }
    await storage.close();
    const manuallyClosed = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-closed-before-open');
    await manuallyClosed.close();
    let afterClose = '';
    try { await manuallyClosed.read('account'); } catch (error) { afterClose = (error as Error).message; }
    return { afterUpgrade, afterClose };
  }, modulePath);
  expect(result.afterUpgrade).toMatch(/closed/i);
  expect(result.afterClose).toMatch(/closed/i);
});
