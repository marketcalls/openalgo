import { describe, expect, it } from 'vitest';
import {
  WorkspaceRepository, WorkspaceConflictError, parseWorkspaceCatalog,
  type WorkspaceCatalog, type WorkspaceStorage,
} from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

function memory() {
  const values = new Map<string, WorkspaceCatalog>();
  const calls: string[] = [];
  let fail = false;
  const storage: WorkspaceStorage = {
    async read(namespace) { calls.push(`read:${namespace}`); return values.get(namespace) ?? null; },
    async write(namespace, catalog, expectedRevision) {
      calls.push(`write:${namespace}`);
      if (fail) { fail = false; throw new Error('quota'); }
      if ((values.get(namespace)?.revision ?? 0) !== expectedRevision) throw new WorkspaceConflictError();
      values.set(namespace, structuredClone(catalog));
    },
  };
  let next = 0;
  let clock = 1000;
  const options = { id: () => `item-${++next}`, now: () => clock++ };
  const repo = new WorkspaceRepository(storage, 'user-a', options);
  return { repo, storage, values, calls, options, failNext: () => { fail = true; } };
}

describe('workspace repository', () => {
  it('refuses to activate a catalog revision different from the prepared grid', async () => {
    const { repo } = memory();
    const doc = await repo.createWorkspace('Desk', workspaceFixture());
    const revision = (await repo.load()).revision;
    await repo.saveWorkspace(doc.id, { ...workspaceFixture(), activePaneId: 'p1' });
    await expect(repo.openWorkspace(doc.id, { expectedRevision: revision })).rejects.toBeInstanceOf(WorkspaceConflictError);
    expect((await repo.load()).activeWorkspaceId).toBeNull();
    await expect(repo.openWorkspace(doc.id, { expectedRevision: -1 })).rejects.toThrow();
    const current = await repo.load();
    await repo.openWorkspace(doc.id, { expectedRevision: current.revision });
    expect((await repo.load()).activeWorkspaceId).toBe(doc.id);
  });

  it('does not read or write for an already cancelled open and keeps the queue usable', async () => {
    const { repo, calls } = memory();
    const doc = await repo.createWorkspace('Desk', workspaceFixture());
    const controller = new AbortController();
    controller.abort(new Error('cancelled open'));
    calls.length = 0;
    await expect(repo.openWorkspace(doc.id, { signal: controller.signal })).rejects.toThrow('cancelled open');
    expect(calls).toEqual([]);
    expect((await repo.load()).activeWorkspaceId).toBeNull();
    await repo.openWorkspace(doc.id);
    expect((await repo.load()).activeWorkspaceId).toBe(doc.id);
  });

  it('rechecks cancellation after catalog reads before changing active or recent selection', async () => {
    const { repo, storage, calls } = memory();
    const doc = await repo.createWorkspace('Desk', workspaceFixture());
    const controller = new AbortController();
    const read = storage.read.bind(storage);
    storage.read = async namespace => { const value = await read(namespace); controller.abort(new Error('superseded')); return value; };
    calls.length = 0;
    await expect(repo.openWorkspace(doc.id, { signal: controller.signal })).rejects.toThrow('superseded');
    expect(calls).toEqual(['read:user-a']);
    const catalog = await repo.load();
    expect(catalog.activeWorkspaceId).toBeNull();
    expect(catalog.recentWorkspaceIds).toEqual([]);
  });

  it('passes the opening owner signal to the atomic write adapter', async () => {
    const { repo, storage } = memory();
    const doc = await repo.createWorkspace('Desk', workspaceFixture());
    const controller = new AbortController();
    const write = storage.write.bind(storage);
    let observed: AbortSignal | undefined;
    storage.write = async (namespace, catalog, revision, options) => {
      observed = options?.signal;
      await write(namespace, catalog, revision);
    };
    await repo.openWorkspace(doc.id, { signal: controller.signal });
    expect(observed).toBe(controller.signal);
  });

  it('creates, saves, renames, duplicates and exports detached documents', async () => {
    const { repo } = memory();
    const created = await repo.createWorkspace('Desk', workspaceFixture());
    expect(created).toMatchObject({ id: 'item-1', name: 'Desk', createdAt: 1000, updatedAt: 1000 });
    created.panes[0].symbol = 'MUTATED';
    expect(JSON.parse(await repo.exportDocument('workspace', created.id)).panes[0].symbol).toBe('BHEL');
    const changed = workspaceFixture();
    changed.panes[0].interval = '15m';
    await repo.saveWorkspace(created.id, changed);
    await repo.rename('workspace', created.id, '  Afternoon  ');
    const copy = await repo.duplicate('workspace', created.id, 'Second desk');
    expect(copy.id).not.toBe(created.id);
    expect(copy.name).toBe('Second desk');
    const source = JSON.parse(await repo.exportDocument('workspace', created.id));
    expect(source).toMatchObject({ name: 'Afternoon', createdAt: 1000 });
    expect(source.panes[0].interval).toBe('15m');
    expect((await repo.load()).revision).toBe(4);
  });

  it('keeps study instances, styles and empty templates through CRUD', async () => {
    const { repo } = memory();
    const created = await repo.createTemplate('Two averages', workspaceFixture().panes[0].chart.indicators);
    expect(created.indicators).toHaveLength(2);
    expect(created.indicators[1].visible).toBe(false);
    const duplicate = await repo.duplicate('indicator-template', created.id, 'Copy');
    await repo.rename('indicator-template', duplicate.id, 'Renamed copy');
    const empty = await repo.createTemplate('Clear', []);
    expect(JSON.parse(await repo.exportDocument('indicator-template', empty.id)).indicators).toEqual([]);
    await repo.remove('indicator-template', created.id);
    expect((await repo.load()).templates.map(item => item.name)).toEqual(['Renamed copy', 'Clear']);
  });

  it('updates a template in place with detached settings and reusable identities', async () => {
    const { repo } = memory();
    const original = await repo.createTemplate('Studies', []);
    const untouched = await repo.createTemplate('Other', []);
    const incoming = workspaceFixture().panes[0].chart.indicators.map((item, index) => ({ ...item, instanceId: `chart-${index}` }));
    const pending = repo.saveTemplate(original.id, incoming);
    incoming[0].settings.period = 99;
    const updated = await pending;
    expect(updated).toMatchObject({ id: original.id, name: original.name, createdAt: original.createdAt });
    expect(updated.updatedAt).toBeGreaterThan(original.updatedAt);
    expect(updated.indicators.map(item => item.instanceId)).toEqual([undefined, undefined]);
    expect(updated.indicators[0].settings.period).toBe(9);
    expect((await repo.load()).templates[1]).toEqual(untouched);
    await repo.saveTemplate(original.id, []);
    expect((await repo.load()).templates[0].indicators).toEqual([]);
  });

  it('preserves the old template and queue after a failed update', async () => {
    const { repo, failNext } = memory();
    const original = await repo.createTemplate('Studies', []);
    const before = await repo.load();
    failNext();
    await expect(repo.saveTemplate(original.id, workspaceFixture().panes[0].chart.indicators)).rejects.toThrow('quota');
    expect(await repo.load()).toEqual(before);
    await repo.saveTemplate(original.id, workspaceFixture().panes[0].chart.indicators);
    expect((await repo.load()).templates[0].indicators).toHaveLength(2);
    await expect(repo.saveTemplate('missing', [])).rejects.toThrow(/does not exist/);
  });

  it('rejects malformed template updates before reading or writing storage', async () => {
    const { repo, calls } = memory();
    const original = await repo.createTemplate('Studies', []);
    calls.length = 0;
    await expect(repo.saveTemplate(original.id, [{ indicatorId: 'ema', settings: {}, paneIndex: 32 }])).rejects.toThrow(/paneIndex/);
    expect(calls).toEqual([]);
    expect((await repo.load()).templates[0]).toEqual(original);
  });

  it('maintains a unique bounded recent list and repairs active selection after deletion', async () => {
    const { repo } = memory();
    for (let i = 0; i < 12; i++) {
      const doc = await repo.createWorkspace(`Desk ${i}`, workspaceFixture());
      await repo.openWorkspace(doc.id);
    }
    await repo.openWorkspace('item-5');
    let catalog = await repo.load();
    expect(catalog.recentWorkspaceIds).toHaveLength(10);
    expect(new Set(catalog.recentWorkspaceIds).size).toBe(10);
    expect(catalog.recentWorkspaceIds.slice(0, 2)).toEqual(['item-5', 'item-12']);
    await repo.remove('workspace', 'item-5');
    catalog = await repo.load();
    expect(catalog.activeWorkspaceId).toBe('item-12');
    expect(catalog.recentWorkspaceIds).not.toContain('item-5');
    for (const doc of catalog.workspaces) await repo.remove('workspace', doc.id);
    expect((await repo.load()).activeWorkspaceId).toBeNull();
  });

  it('surfaces failed saves, retains old content and recovers for the next operation', async () => {
    const { repo, failNext } = memory();
    failNext();
    await expect(repo.createWorkspace('Desk', workspaceFixture())).rejects.toThrow('quota');
    expect((await repo.load()).workspaces).toEqual([]);
    const saved = await repo.createWorkspace('Desk', workspaceFixture());
    failNext();
    await expect(repo.rename('workspace', saved.id, 'Not saved')).rejects.toThrow('quota');
    expect((await repo.load()).workspaces[0].name).toBe('Desk');
    await repo.rename('workspace', saved.id, 'Saved');
    expect((await repo.load()).revision).toBe(2);
  });

  it('serializes concurrent mutations and captures inputs when the operation starts', async () => {
    const { repo } = memory();
    const input = workspaceFixture();
    const first = repo.createWorkspace('First', input);
    input.panes[0].symbol = 'CHANGED';
    const second = repo.createWorkspace('Second', input);
    await Promise.all([first, second, repo.setAutosave(true)]);
    const catalog = await repo.load();
    expect(catalog.workspaces.map(doc => doc.panes[0].symbol)).toEqual(['BHEL', 'CHANGED']);
    expect(catalog.autosave).toBe(true);
    expect(catalog.revision).toBe(3);
  });

  it('does not redirect an in-flight save when the host opens another account namespace', async () => {
    const store = memory();
    const other = new WorkspaceRepository(store.storage, 'user-b', store.options);
    await Promise.all([
      store.repo.createWorkspace('A', workspaceFixture()), other.createWorkspace('B', workspaceFixture()),
    ]);
    expect((await store.repo.load()).workspaces.map(doc => doc.name)).toEqual(['A']);
    expect((await other.load()).workspaces.map(doc => doc.name)).toEqual(['B']);
    expect(store.calls.filter(call => call.startsWith('write:'))).toEqual(['write:user-a', 'write:user-b']);
  });

  it('lets the atomic adapter reject a stale revision without losing the winner', async () => {
    const store = memory();
    const other = new WorkspaceRepository(store.storage, 'user-a', store.options);
    const settled = await Promise.allSettled([
      store.repo.createWorkspace('One', workspaceFixture()), other.createWorkspace('Two', workspaceFixture()),
    ]);
    expect(settled.filter(result => result.status === 'fulfilled')).toHaveLength(1);
    const rejection = settled.find(result => result.status === 'rejected');
    expect(rejection?.status === 'rejected' && rejection.reason).toBeInstanceOf(WorkspaceConflictError);
    expect((await store.repo.load()).workspaces).toHaveLength(1);
  });

  it('imports as a new identity and never brings private fields into storage', async () => {
    const { repo, values } = memory();
    const original = await repo.createWorkspace('Current', workspaceFixture());
    const input = { ...workspaceFixture(), id: original.id, apiKey: 'secret-value', armed: true };
    const imported = await repo.importDocument(JSON.stringify(input));
    expect(imported.id).not.toBe(original.id);
    expect((await repo.load()).workspaces).toHaveLength(2);
    expect(JSON.stringify([...values.values()])).not.toMatch(/secret-value|armed/);
    const studies = await repo.createTemplate('Study', []);
    const importedStudies = await repo.importDocument(await repo.exportDocument('indicator-template', studies.id));
    expect(importedStudies.kind).toBe('indicator-template');
    expect(importedStudies.id).not.toBe(studies.id);
  });

  it('rejects missing IDs, colliding generated IDs and invalid names before writing', async () => {
    const store = memory();
    await expect(store.repo.openWorkspace('missing')).rejects.toThrow();
    await expect(store.repo.remove('workspace', 'missing')).rejects.toThrow();
    await expect(store.repo.saveWorkspace('missing', workspaceFixture())).rejects.toThrow();
    await expect(store.repo.createTemplate(' ', [])).rejects.toThrow();
    const repo = new WorkspaceRepository(store.storage, 'user-a', { id: () => 'same', now: () => 1000 });
    await repo.createWorkspace('A', workspaceFixture());
    await expect(repo.createTemplate('B', [])).rejects.toThrow(/collision/i);
    expect((await repo.load()).revision).toBe(1);
  });

  it('rejects unsupported or inconsistent catalogs without overwriting them', async () => {
    const store = memory();
    const valid = await store.repo.load();
    for (const corrupt of [
      { ...valid, version: 99 }, { ...valid, revision: -1 },
      { ...valid, recentWorkspaceIds: ['missing'] }, { ...valid, activeWorkspaceId: 'missing' },
      { ...valid, workspaces: [workspaceFixture(), workspaceFixture()] },
    ]) expect(() => parseWorkspaceCatalog(corrupt)).toThrow();
    store.values.set('user-a', { ...valid, revision: -1 });
    await expect(store.repo.createWorkspace('No overwrite', workspaceFixture())).rejects.toThrow();
    expect(store.values.get('user-a')?.revision).toBe(-1);
  });
});
