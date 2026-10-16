import { describe, it, expect, vi } from 'vitest';
import { WorkspaceConflictError, parseWorkspacePayload } from '/dist/openalgo-charts.workspace.mjs';
import { ReferenceWorkspaceCatalog } from '../src/workspace-catalog.js';

const payload = (symbol = 'AAPL') => ({ layout: { rows: 1, columns: 1,
  slots: [{ paneId: 'primary', row: 0, column: 0, rowSpan: 1, columnSpan: 1 }] },
  panes: [{ id: 'primary', symbol, exchange: '', interval: '1d', historyPeriod: '1y', chartType: 'candlestick',
    chart: { version: 1, indicators: [] }, settings: {}, volume: true, magnet: 'off', stay: false,
    comparisons: [], comparisonMode: 'percent' }], activePaneId: 'primary',
  sync: { crosshair: true, viewport: true, symbol: false, interval: false } });

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function setup() {
  let stored = null, next = 0, fail = false, current = payload();
  const storage = { read: vi.fn(async () => structuredClone(stored)),
    write: vi.fn(async (_namespace, nextCatalog, revision, options) => {
      options?.signal?.throwIfAborted();
      if (fail) { fail = false; throw new Error('Storage refused'); }
      if ((stored?.revision ?? 0) !== revision) throw new WorkspaceConflictError();
      stored = structuredClone(nextCatalog);
    }) };
  const open = vi.fn(async (document, persist) => {
    const controller = new AbortController();
    await persist(controller.signal);
    current = parseWorkspacePayload(document);
  });
  const changed = vi.fn();
  const catalog = new ReferenceWorkspaceCatalog({ storage, namespace: 'reference-test',
    snapshot: () => current, open, changed, id: () => `saved-${++next}`, now: () => next * 1000 });
  return { catalog, storage, open, changed, get stored() { return stored; },
    change: symbol => { current = payload(symbol); }, failNext: () => { fail = true; },
    remoteChange: () => { stored.revision++; stored.workspaces[0].name = 'Remote edit'; } };
}

describe('reference named workspace catalog', () => {
  it('creates, saves, renames and duplicates named chart configuration', async () => {
    const h = setup(); await h.catalog.initialize();
    const first = await h.catalog.create('First');
    expect(h.catalog.currentId).toBe(first.id);
    expect(h.stored.activeWorkspaceId).toBe(first.id);
    h.change('TSLA'); await h.catalog.save();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('TSLA');
    await h.catalog.rename(first.id, 'Desk');
    const copy = await h.catalog.duplicate(first.id, 'Desk copy');
    expect(copy.id).not.toBe(first.id);
    expect(h.stored.workspaces.map(item => item.name)).toEqual(['Desk', 'Desk copy']);
    expect(h.catalog.currentId).toBe(first.id);
  });

  it('opens through prepared publication and updates recent ordering only after success', async () => {
    const h = setup(); await h.catalog.initialize();
    const one = await h.catalog.create('One'); h.change('MSFT'); const two = await h.catalog.create('Two');
    await h.catalog.open(one.id);
    expect(h.open).toHaveBeenCalledTimes(1);
    expect(h.catalog.currentId).toBe(one.id);
    expect(h.stored.recentWorkspaceIds).toEqual([one.id, two.id]);
    h.failNext(); await expect(h.catalog.open(two.id)).rejects.toThrow('Storage refused');
    expect(h.catalog.currentId).toBe(one.id);
    expect(h.stored.recentWorkspaceIds).toEqual([one.id, two.id]);
    expect(h.catalog.error).toContain('Storage refused');
  });

  it('leaves the saved layout unchanged when autosave is off and persists the active owner when on', async () => {
    const h = setup(); await h.catalog.initialize(); await h.catalog.create('Desk');
    h.change('TSLA'); h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('AAPL');
    await h.catalog.setAutosave(true); h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('TSLA');
    const writes = h.storage.write.mock.calls.length;
    h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.storage.write).toHaveBeenCalledTimes(writes);
  });

  it('does not autosave a deleted active chart into the replacement recent entry', async () => {
    const h = setup(); await h.catalog.initialize();
    const one = await h.catalog.create('One'); h.change('MSFT'); const two = await h.catalog.create('Two');
    await h.catalog.setAutosave(true); await h.catalog.remove(two.id);
    expect(h.catalog.currentId).toBeNull(); expect(h.stored.activeWorkspaceId).toBe(one.id);
    h.change('TSLA'); h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('AAPL');
  });

  it('detects a remote catalog revision before overwriting it and permits an explicit refresh', async () => {
    const h = setup(); await h.catalog.initialize(); await h.catalog.create('Desk');
    h.remoteChange(); h.change('TSLA');
    await expect(h.catalog.save()).rejects.toBeInstanceOf(WorkspaceConflictError);
    expect(h.stored.workspaces[0].name).toBe('Remote edit');
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('AAPL');
    await h.catalog.refresh(); await h.catalog.save();
    expect(h.stored.workspaces[0].name).toBe('Remote edit');
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('TSLA');
  });

  it('blocks repeated failed autosaves until refreshed and never reports an unsuccessful write as saved', async () => {
    const h = setup(); await h.catalog.initialize(); await h.catalog.create('Desk'); await h.catalog.setAutosave(true);
    h.change('TSLA'); h.failNext(); h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.catalog.error).toContain('Storage refused');
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('AAPL');
    const writes = h.storage.write.mock.calls.length;
    h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.storage.write).toHaveBeenCalledTimes(writes);
    await h.catalog.refresh(); h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('TSLA');
  });

  it('imports and exports a portable workspace with a fresh identity', async () => {
    const h = setup(); await h.catalog.initialize(); const one = await h.catalog.create('Source');
    const text = await h.catalog.export(one.id);
    const copied = await h.catalog.import(text);
    expect(copied.id).not.toBe(one.id);
    expect(h.catalog.currentId).toBe(copied.id);
    expect(h.stored.workspaces).toHaveLength(2);
    expect(JSON.parse(text)).toMatchObject({ kind: 'workspace', name: 'Source', panes: [{ symbol: 'AAPL' }] });
    await expect(h.catalog.import('{bad json')).rejects.toThrow();
    expect(h.stored.workspaces).toHaveLength(2);
  });

  it('migrates legacy recovery only once and prefers the saved named document when autosave is off', async () => {
    const h = setup();
    const legacy = { schema: 2, version: 1, dataset: 'AAPL|1d|1y', chartType: 'line' };
    const initial = await h.catalog.initialize(legacy);
    expect(initial.request.symbol).toBe('AAPL');
    expect(h.stored.autosave).toBe(true);
    expect(h.stored.workspaces).toHaveLength(1);
    await h.catalog.setAutosave(false);
    const restored = await h.catalog.initialize({ ...legacy, dataset: 'TSLA|1d|1y' });
    expect(restored.request.symbol).toBe('AAPL');
    expect(h.stored.workspaces).toHaveLength(1);
  });

  it('recovers selection and recent state when publication fails after storage commits', async () => {
    const h = setup(); await h.catalog.initialize();
    const one = await h.catalog.create('One'); const two = await h.catalog.create('Two');
    const before = structuredClone(h.stored);
    h.open.mockImplementationOnce(async (_document, persist) => {
      const receipt = await persist(new AbortController().signal);
      await receipt.rollback(); throw new Error('Installation failed');
    });
    await expect(h.catalog.open(one.id)).rejects.toThrow('Installation failed');
    expect(h.catalog.currentId).toBe(two.id);
    expect(h.stored.activeWorkspaceId).toBe(before.activeWorkspaceId);
    expect(h.stored.recentWorkspaceIds).toEqual(before.recentWorkspaceIds);
    expect(h.stored.revision).toBeGreaterThan(before.revision);
  });

  it('coalesces changes during a slow autosave and writes the latest captured value next', async () => {
    const h = setup(); await h.catalog.initialize(); await h.catalog.create('Desk'); await h.catalog.setAutosave(true);
    const gate = deferred(), started = deferred(), write = h.storage.write.getMockImplementation();
    h.storage.write.mockImplementationOnce(async (...args) => { started.resolve(); await gate.promise; await write(...args); });
    const before = h.storage.write.mock.calls.length;
    h.change('MSFT'); h.catalog.requestAutosave(); await started.promise;
    h.change('TSLA'); h.catalog.requestAutosave(); h.change('NVDA'); h.catalog.requestAutosave();
    gate.resolve(); await h.catalog.flushAutosave();
    expect(h.storage.write).toHaveBeenCalledTimes(before + 2);
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('NVDA');
  });

  it('rolls back an inserted layout when its activation cannot be stored', async () => {
    const h = setup(); await h.catalog.initialize();
    const write = h.storage.write.getMockImplementation();
    h.storage.write.mockImplementationOnce(write).mockRejectedValueOnce(new Error('Activation refused'));
    await expect(h.catalog.create('Desk')).rejects.toThrow('Activation refused');
    expect(h.stored.workspaces).toEqual([]);
    expect(h.stored.activeWorkspaceId).toBeNull();
    expect(h.stored.revision).toBe(2);
    expect(h.catalog.currentId).toBeNull();
  });

  it('leaves import storage untouched when source preparation fails', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    const text = await h.catalog.export(first.id), before = structuredClone(h.stored);
    h.open.mockRejectedValueOnce(new Error('History unavailable'));
    await expect(h.catalog.import(text)).rejects.toThrow('History unavailable');
    expect(h.stored).toEqual(before);
    expect(h.catalog.currentId).toBe(first.id);
  });

  it('recovers an import cancelled after insertion without leaving an orphaned layout', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    const text = await h.catalog.export(first.id), before = structuredClone(h.stored);
    const controller = new AbortController(), write = h.storage.write.getMockImplementation();
    h.open.mockImplementationOnce((_doc, persist) => persist(controller.signal));
    h.storage.write.mockImplementationOnce(async (...args) => { await write(...args); controller.abort(new Error('Source changed')); });
    await expect(h.catalog.import(text)).rejects.toThrow('Source changed');
    expect(h.stored.workspaces).toEqual(before.workspaces);
    expect(h.stored.activeWorkspaceId).toBe(first.id);
  });

  it('preserves a remote edit when compensation conflicts with a newer revision', async () => {
    const h = setup(); await h.catalog.initialize(); const one = await h.catalog.create('One');
    const two = await h.catalog.create('Two');
    h.open.mockImplementationOnce(async (_doc, persist) => {
      const receipt = await persist(new AbortController().signal); h.remoteChange(); await receipt.rollback();
    });
    await expect(h.catalog.open(one.id)).rejects.toBeInstanceOf(WorkspaceConflictError);
    expect(h.stored.workspaces[0].name).toBe('Remote edit');
    expect(h.catalog.currentId).toBe(two.id);
    expect(h.catalog.autosaveBlocked).toBe(true);
  });

  it('does not let a queued autosave overwrite a layout that is being reopened', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    await h.catalog.setAutosave(true); h.change('TSLA');
    const gate = deferred(), started = deferred(), open = h.open.getMockImplementation();
    h.open.mockImplementationOnce(async (...args) => { started.resolve(); await gate.promise; return open(...args); });
    const opening = h.catalog.open(first.id); await started.promise;
    h.catalog.requestAutosave(); gate.resolve(); await opening; await h.catalog.flushAutosave();
    expect(h.stored.workspaces[0].panes[0].symbol).toBe('AAPL');
  });

  it('keeps a failed autosave visible and blocked after an unrelated export', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    await h.catalog.setAutosave(true); h.change('TSLA'); h.failNext();
    h.catalog.requestAutosave(); await h.catalog.flushAutosave();
    await h.catalog.export(first.id);
    expect(h.catalog.autosaveBlocked).toBe(true);
    expect(h.catalog.error).toContain('Storage refused');
  });

  it('does not remigrate legacy recovery after all named layouts were deliberately deleted', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    await h.catalog.remove(first.id);
    const result = await h.catalog.initialize({ schema: 2, version: 1, dataset: 'AAPL|1d|1y' });
    expect(result).toBeNull(); expect(h.stored.workspaces).toEqual([]);
  });

  it('rejects concurrent manual actions while an existing save owns storage', async () => {
    const h = setup(); await h.catalog.initialize(); const first = await h.catalog.create('Desk');
    const gate = deferred(), started = deferred(), write = h.storage.write.getMockImplementation();
    h.storage.write.mockImplementationOnce(async (...args) => { started.resolve(); await gate.promise; await write(...args); });
    h.change('TSLA'); const saving = h.catalog.save(); await started.promise;
    await expect(h.catalog.remove(first.id)).rejects.toThrow(/in progress/);
    gate.resolve(); await saving;
    expect(h.stored.workspaces).toHaveLength(1);
  });
});
