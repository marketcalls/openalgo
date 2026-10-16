/**
 * The workspace catalog as a store a control can hold: every change takes the
 * revision it was prepared from and is refused when another session moved the
 * catalog, subscribers hear each commit before the change's own promise
 * settles, and a memory adapter keeps the same compare-and-write contract as
 * the IndexedDB one.
 */
import { describe, expect, it, vi } from 'vitest';
import {
  WorkspaceRepository, WorkspaceConflictError, WorkspaceDocumentError, createMemoryWorkspaceStorage, parseWorkspaceCatalog,
  type WorkspaceCatalog, type WorkspaceOperationOptions, type WorkspaceStorage, type WorkspaceStore,
} from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

function counted(storage: WorkspaceStorage) {
  const calls: string[] = [];
  const wrapped: WorkspaceStorage = {
    read: namespace => { calls.push('read'); return storage.read(namespace); },
    write: (namespace, catalog, expected, options) => { calls.push('write'); return storage.write(namespace, catalog, expected, options); },
  };
  return { storage: wrapped, calls };
}

function sessions() {
  const shared = createMemoryWorkspaceStorage();
  const { storage, calls } = counted(shared);
  let n = 0;
  const options = { id: () => `doc-${++n}`, now: () => 1000 + n };
  // Two tabs on one account: two repositories over one atomic storage.
  return { mine: new WorkspaceRepository(storage, 'desk', options), theirs: new WorkspaceRepository(shared, 'desk', options), shared, calls };
}

type Operation = (repo: WorkspaceRepository, ids: { workspace: string; template: string }, options: WorkspaceOperationOptions) => Promise<unknown>;

/** Every catalog change a store offers, each prepared against a given revision. */
const OPERATIONS: Record<string, Operation> = {
  createWorkspace: (repo, _ids, o) => repo.createWorkspace('New desk', workspaceFixture(), o),
  saveWorkspace: (repo, ids, o) => repo.saveWorkspace(ids.workspace, { ...workspaceFixture(), activePaneId: 'p0' }, o),
  openWorkspace: (repo, ids, o) => repo.openWorkspace(ids.workspace, o),
  'rename workspace': (repo, ids, o) => repo.rename('workspace', ids.workspace, 'Renamed', o),
  'duplicate workspace': (repo, ids, o) => repo.duplicate('workspace', ids.workspace, 'Copy', o),
  'remove workspace': (repo, ids, o) => repo.remove('workspace', ids.workspace, o),
  setAutosave: (repo, _ids, o) => repo.setAutosave(true, o),
  createTemplate: (repo, _ids, o) => repo.createTemplate('Averages', workspaceFixture().panes[0].chart.indicators, o),
  saveTemplate: (repo, ids, o) => repo.saveTemplate(ids.template, [], o),
  'rename template': (repo, ids, o) => repo.rename('indicator-template', ids.template, 'Renamed', o),
  'duplicate template': (repo, ids, o) => repo.duplicate('indicator-template', ids.template, 'Copy', o),
  'remove template': (repo, ids, o) => repo.remove('indicator-template', ids.template, o),
  importDocument: (repo, _ids, o) => repo.importDocument(workspaceFixture(), o),
};

async function seeded() {
  const s = sessions();
  const workspace = (await s.mine.createWorkspace('Desk', workspaceFixture())).id;
  const template = (await s.mine.createTemplate('Studies', [])).id;
  return { ...s, ids: { workspace, template } };
}

describe('workspace store revisions', () => {
  for (const [name, run] of Object.entries(OPERATIONS)) {
    it(`${name} refuses a revision another session has moved past, and takes the current one`, async () => {
      const { mine, theirs, shared, calls, ids } = await seeded();
      const prepared = (await mine.load()).revision;
      // Another tab renames something unrelated: the catalog moves on regardless.
      await theirs.rename('workspace', ids.workspace, 'Changed in another tab');
      const after = await shared.read('desk');
      calls.length = 0;
      await expect(run(mine, ids, { expectedRevision: prepared })).rejects.toBeInstanceOf(WorkspaceConflictError);
      // Refused after reading, before any write, and the other tab's change survives.
      expect(calls).toEqual(['read']);
      expect(await shared.read('desk')).toEqual(after);
      const current = (await mine.load()).revision;
      await run(mine, ids, { expectedRevision: current });
      expect((await mine.load()).revision).toBe(current + 1);
    });
  }

  it('keeps every change without expectedRevision last-writer-wins, as before', async () => {
    const { mine, theirs, ids } = await seeded();
    await theirs.rename('workspace', ids.workspace, 'Theirs');
    await mine.saveWorkspace(ids.workspace, { ...workspaceFixture(), activePaneId: 'p0' });
    const catalog = await mine.load();
    expect(catalog.workspaces[0]).toMatchObject({ name: 'Theirs', activePaneId: 'p0' });
    expect(catalog.revision).toBe(4);
  });

  it('refuses a malformed expected revision before touching storage', async () => {
    const { mine, calls, ids } = await seeded();
    calls.length = 0;
    for (const bad of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, '2' as unknown as number]) {
      await expect(mine.saveWorkspace(ids.workspace, workspaceFixture(), { expectedRevision: bad })).rejects.toBeInstanceOf(WorkspaceDocumentError);
      await expect(mine.setAutosave(true, { expectedRevision: bad })).rejects.toBeInstanceOf(WorkspaceDocumentError);
    }
    expect(calls).toEqual([]);
  });

  it('checks the revision after cancellation and passes the signal to storage', async () => {
    const { mine, ids } = await seeded();
    const controller = new AbortController();
    controller.abort(new Error('superseded'));
    const revision = (await mine.load()).revision;
    await expect(mine.saveWorkspace(ids.workspace, workspaceFixture(), { signal: controller.signal, expectedRevision: revision }))
      .rejects.toThrow('superseded');
    expect((await mine.load()).revision).toBe(revision);
  });
});

describe('workspace store subscribe', () => {
  it('delivers each commit, in order, before that change resolves', async () => {
    const { mine } = sessions();
    const events: string[] = [];
    mine.subscribe(catalog => events.push(`commit ${catalog.revision}`));
    const first = mine.createWorkspace('One', workspaceFixture()).then(doc => events.push(`resolved ${doc.name}`));
    const second = mine.setAutosave(true).then(() => events.push('resolved autosave'));
    const third = mine.createWorkspace('Two', workspaceFixture()).then(doc => events.push(`resolved ${doc.name}`));
    await Promise.all([first, second, third]);
    expect(events).toEqual(['commit 1', 'resolved One', 'commit 2', 'resolved autosave', 'commit 3', 'resolved Two']);
  });

  it('hands each listener a detached copy of the committed catalog', async () => {
    const { mine, shared } = sessions();
    const seen: WorkspaceCatalog[] = [];
    mine.subscribe(catalog => { seen.push(catalog); catalog.workspaces.length = 0; });
    mine.subscribe(catalog => seen.push(catalog));
    await mine.createWorkspace('Desk', workspaceFixture());
    expect(seen).toHaveLength(2);
    expect(seen[1].workspaces).toHaveLength(1);
    expect(parseWorkspaceCatalog(await shared.read('desk')).workspaces).toHaveLength(1);
  });

  it('is silent for a refused, failed or invalid change and after unsubscribe', async () => {
    const { mine, theirs, shared } = sessions();
    const listener = vi.fn();
    const off = mine.subscribe(listener);
    const doc = await mine.createWorkspace('Desk', workspaceFixture());
    expect(listener).toHaveBeenCalledTimes(1);
    await theirs.setAutosave(true);
    await expect(mine.rename('workspace', doc.id, 'Stale', { expectedRevision: 1 })).rejects.toBeInstanceOf(WorkspaceConflictError);
    await expect(mine.rename('workspace', 'missing', 'Nope')).rejects.toBeInstanceOf(WorkspaceDocumentError);
    const write = shared.write;
    shared.write = async () => { throw new Error('quota'); };
    await expect(theirs.setAutosave(false)).rejects.toThrow('quota');
    shared.write = write;
    expect(listener).toHaveBeenCalledTimes(1);
    off();
    await mine.setAutosave(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('commits and notifies the others when one listener throws', async () => {
    const { mine } = sessions();
    const reported: unknown[] = [];
    const later = vi.spyOn(globalThis, 'queueMicrotask').mockImplementation(task => {
      try { task(); } catch (error) { reported.push(error); }
    });
    try {
      const after = vi.fn();
      mine.subscribe(() => { throw new Error('host listener'); });
      mine.subscribe(after);
      const doc = await mine.createWorkspace('Desk', workspaceFixture());
      expect(doc.name).toBe('Desk');
      expect(after).toHaveBeenCalledTimes(1);
      expect(reported).toEqual([new Error('host listener')]);
    } finally { later.mockRestore(); }
  });

  it('is a WorkspaceStore, the contract a widget holds', async () => {
    const { mine } = sessions();
    const store: WorkspaceStore = mine;
    const seen: number[] = [];
    store.subscribe(catalog => seen.push(catalog.revision));
    const doc = await store.createWorkspace('Desk', workspaceFixture(), { expectedRevision: 0 });
    await store.openWorkspace(doc.id, { expectedRevision: 1 });
    await store.setAutosave(true, { expectedRevision: 2 });
    expect(seen).toEqual([1, 2, 3]);
    expect(await store.load()).toMatchObject({ activeWorkspaceId: doc.id, recentWorkspaceIds: [doc.id], autosave: true });
  });
});

describe('createMemoryWorkspaceStorage', () => {
  it('starts empty or from a seed, and hands out detached copies', async () => {
    const empty = createMemoryWorkspaceStorage();
    expect(await empty.read('desk')).toBeNull();
    const seedRepo = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => 'seeded', now: () => 5 });
    await seedRepo.createWorkspace('Seeded', workspaceFixture());
    const seed = await seedRepo.load();
    const storage = createMemoryWorkspaceStorage({ desk: seed });
    seed.workspaces.length = 0;
    const read = await storage.read('desk') as WorkspaceCatalog;
    expect(read.workspaces.map(doc => doc.name)).toEqual(['Seeded']);
    read.workspaces.length = 0;
    expect((await new WorkspaceRepository(storage, 'desk').load()).workspaces).toHaveLength(1);
    expect(await storage.read('other')).toBeNull();
  });

  it('compares and writes atomically: the loser of a race is a conflict and the winner survives', async () => {
    const storage = createMemoryWorkspaceStorage();
    let n = 0;
    const options = { id: () => `doc-${++n}`, now: () => 1000 };
    const a = new WorkspaceRepository(storage, 'desk', options);
    const b = new WorkspaceRepository(storage, 'desk', options);
    const settled = await Promise.allSettled([a.createWorkspace('A', workspaceFixture()), b.createWorkspace('B', workspaceFixture())]);
    expect(settled.map(result => result.status).sort()).toEqual(['fulfilled', 'rejected']);
    const lost = settled.find(result => result.status === 'rejected') as PromiseRejectedResult;
    expect(lost.reason).toBeInstanceOf(WorkspaceConflictError);
    const catalog = await a.load();
    expect(catalog.revision).toBe(1);
    expect(catalog.workspaces).toHaveLength(1);
  });

  it('refuses a stale, skipping or invalid write and never replaces a corrupt catalog', async () => {
    const storage = createMemoryWorkspaceStorage();
    const repo = new WorkspaceRepository(storage, 'desk', { id: () => 'doc', now: () => 1000 });
    await repo.createWorkspace('Desk', workspaceFixture());
    const current = await repo.load();
    await expect(storage.write('desk', { ...current, revision: 1 }, 0)).rejects.toBeInstanceOf(WorkspaceConflictError);
    await expect(storage.write('desk', { ...current, revision: 3 }, 1)).rejects.toBeInstanceOf(WorkspaceDocumentError);
    await expect(storage.write('desk', { ...current, revision: 2, activeWorkspaceId: 'missing' }, 1)).rejects.toBeInstanceOf(WorkspaceDocumentError);
    expect(await storage.read('desk')).toEqual(current);
    const corrupt = createMemoryWorkspaceStorage({ desk: { ...current, version: 99 } });
    const empty = parseWorkspaceCatalog({ ...current, workspaces: [], recentWorkspaceIds: [], activeWorkspaceId: null, revision: 2 });
    await expect(corrupt.write('desk', empty, 1)).rejects.toBeInstanceOf(WorkspaceDocumentError);
    expect(await corrupt.read('desk')).toMatchObject({ version: 99 });
    await expect(new WorkspaceRepository(corrupt, 'desk').createWorkspace('Lost', workspaceFixture())).rejects.toBeInstanceOf(WorkspaceDocumentError);
  });

  it('refuses a cancelled write and keeps namespaces apart', async () => {
    const storage = createMemoryWorkspaceStorage();
    const controller = new AbortController();
    controller.abort(new Error('cancelled'));
    const first = parseWorkspaceCatalog({ version: 1, revision: 1, workspaces: [], templates: [], recentWorkspaceIds: [], activeWorkspaceId: null, autosave: true });
    await expect(storage.write('desk', first, 0, { signal: controller.signal })).rejects.toThrow('cancelled');
    expect(await storage.read('desk')).toBeNull();
    await storage.write('desk', first, 0);
    expect(await storage.read('desk')).toEqual(first);
    expect(await storage.read('other desk')).toBeNull();
    await expect(storage.read(' ')).rejects.toBeInstanceOf(WorkspaceDocumentError);
  });
});
