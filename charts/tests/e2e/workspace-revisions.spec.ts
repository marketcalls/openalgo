import { expect, test } from '@playwright/test';
import { workspaceFixture } from '../helpers/workspace-fixture';

const modulePath = '/dist/openalgo-charts.workspace.mjs';

/**
 * Two tabs of one account over the browser's own IndexedDB: a change prepared
 * from a revision the other tab has since moved past is refused, the other
 * tab's layout survives, and each tab hears only the commits it made.
 */
test('a save prepared before another tab saved the same layout is refused, and that layout survives', async ({ page, context }) => {
  const other = await context.newPage();
  await Promise.all([page.goto('/tests/e2e/fixture.html'), other.goto('/tests/e2e/fixture.html')]);
  for (const [tab, prefix] of [[page, 'a'], [other, 'b']] as const) await tab.evaluate(async ({ modulePath, prefix }) => {
    const { WorkspaceRepository, createIndexedDbWorkspaceStorage } = await import(modulePath);
    const storage = createIndexedDbWorkspaceStorage(indexedDB, 'workspace-revisions');
    let next = 0;
    const repo = new WorkspaceRepository(storage, 'account', { id: () => `${prefix}-${++next}`, now: () => 5000 + next });
    const heard: number[] = [];
    repo.subscribe((catalog: { revision: number }) => heard.push(catalog.revision));
    Object.assign(window, { __workspace: { storage, repo, heard } });
  }, { modulePath, prefix });

  const created = await page.evaluate(async payload => {
    const { repo } = (window as any).__workspace;
    const doc = await repo.createWorkspace('Desk', payload);
    return { id: doc.id as string, revision: (await repo.load()).revision as number };
  }, workspaceFixture());
  expect(created).toEqual({ id: 'a-1', revision: 1 });

  // The other tab reads the catalog and saves the layout with a new interval.
  const theirs = await other.evaluate(async ({ id, payload }) => {
    const { repo } = (window as any).__workspace;
    const { revision } = await repo.load();
    payload.panes[0].interval = '15m';
    await repo.saveWorkspace(id, payload, { expectedRevision: revision });
    return (await repo.load()).revision as number;
  }, { id: created.id, payload: workspaceFixture() });
  expect(theirs).toBe(2);

  const refused = await page.evaluate(async ({ id, payload, revision }) => {
    const { repo, heard } = (window as any).__workspace;
    const errors: string[] = [];
    payload.panes[0].interval = '1m';
    for (const change of [
      () => repo.saveWorkspace(id, payload, { expectedRevision: revision }),
      () => repo.rename('workspace', id, 'Renamed here', { expectedRevision: revision }),
      () => repo.remove('workspace', id, { expectedRevision: revision }),
      () => repo.setAutosave(true, { expectedRevision: revision }),
    ]) {
      try { await change(); errors.push('saved'); } catch (error) { errors.push((error as Error).name); }
    }
    const catalog = await repo.load();
    const heardBefore = heard.slice();
    // Taking the current revision, the same change goes through.
    await repo.setAutosave(true, { expectedRevision: catalog.revision });
    return {
      errors, heardBefore, heard: heard.slice(),
      stored: { revision: catalog.revision, name: catalog.workspaces[0].name, interval: catalog.workspaces[0].panes[0].interval },
      autosave: (await repo.load()).autosave,
    };
  }, { id: created.id, payload: workspaceFixture(), revision: created.revision });
  expect(refused.errors).toEqual(['WorkspaceConflictError', 'WorkspaceConflictError', 'WorkspaceConflictError', 'WorkspaceConflictError']);
  expect(refused.stored).toEqual({ revision: 2, name: 'Desk', interval: '15m' });
  // This tab heard its own two commits, never the other tab's.
  expect(refused.heardBefore).toEqual([1]);
  expect(refused.heard).toEqual([1, 3]);
  expect(refused.autosave).toBe(true);
  expect(await other.evaluate(() => (window as any).__workspace.heard)).toEqual([2]);

  await Promise.all([page, other].map(tab => tab.evaluate(() => (window as any).__workspace.storage.close())));
});
