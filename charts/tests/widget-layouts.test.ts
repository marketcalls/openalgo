/**
 * The layouts controller: one saved layout held per widget or grid, every
 * write checked against the revision it was prepared from, operations run
 * one at a time, and an autosave that waits for changes to settle and stops
 * when a write fails or conflicts. A write refused because the catalog moved
 * is tried again when what it acts on is unchanged, so only a real change to
 * that layout, in another tab or by another control, is a conflict.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { Bar, DataFeed } from '../src/index';
import '../src/indicators/index';
import {
  WorkspaceRepository, createMemoryWorkspaceStorage, migrateWidgetWorkspace,
  type WorkspaceCatalog, type WorkspacePayload, type WorkspaceStorage, type WorkspaceStore,
} from '../src/workspace/index';
import { createChartGrid, createWidget, type ChartGrid, type Widget } from '../src/widget/index';
import { createLayoutsController, type LayoutTarget, type LayoutsController, type LayoutsState } from '../src/widget/layouts';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument } from './helpers/fake-dom-widget';
import layoutsSource from '../src/widget/layouts.ts?raw';
import { workspaceFixture } from './helpers/workspace-fixture';

beforeAll(ensureWindowGlobal);

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

function payload(symbol: string, interval = '5m'): WorkspacePayload {
  return {
    layout: { rows: 1, columns: 1, slots: [{ paneId: 'p0', row: 0, column: 0, rowSpan: 1, columnSpan: 1 }] },
    panes: [{
      id: 'p0', symbol, exchange: 'NSE', interval, chartType: 'candlestick', chart: { version: 1 },
      settings: {}, volume: false, magnet: 'off', stay: false, comparisons: [], comparisonMode: 'percent',
    }],
    activePaneId: 'p0',
    sync: { crosshair: true, viewport: true, symbol: false, interval: false },
  };
}

/** A target holding one payload: `edit` is the user changing it, `suspend` a replay starting or ending. */
function fakeTarget(initial = payload('INFY')) {
  let current = clone(initial);
  let refusal: string | null = null;
  let suspended = false;
  const listeners = new Set<() => void>();
  const notify = (): void => { for (const listener of Array.from(listeners)) listener(); };
  const target: LayoutTarget = {
    capture: () => clone(current),
    apply(next) {
      if (refusal !== null) return { applied: false, reason: refusal };
      current = clone(next);
      // A real chart reports its own restore as changes; the controller must not count them.
      notify();
      return { applied: true };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    suspended: () => suspended,
  };
  return {
    target,
    symbol: () => current.panes[0].symbol,
    edit(symbol: string) { current.panes[0].symbol = symbol; notify(); },
    refuse(reason: string | null) { refusal = reason; },
    suspend(on: boolean) { suspended = on; notify(); },
  };
}

/** Storage whose writes a test can fail, or interleave with another tab's. */
function scriptedStorage() {
  const inner = createMemoryWorkspaceStorage();
  let failWrites: Error | null = null;
  const beforeWrite: Array<() => Promise<void>> = [];
  const storage: WorkspaceStorage = {
    read: namespace => inner.read(namespace),
    async write(namespace, catalog, expected, options) {
      const hook = beforeWrite.shift();
      if (hook) await hook();
      if (failWrites) throw failWrites;
      await inner.write(namespace, catalog, expected, options);
    },
  };
  return {
    storage, inner,
    failWrites(error: Error | null) { failWrites = error; },
    /** Run `step` (another tab's write) after this page read the catalog, just before its next write reaches storage. */
    interleave(step: () => Promise<unknown>) { beforeWrite.push(async () => { await step(); }); },
  };
}

const METHODS = ['load', 'createWorkspace', 'saveWorkspace', 'openWorkspace', 'rename', 'duplicate', 'remove', 'setAutosave'] as const;

/** Log each store call as `method@expectedRevision` and how it ended. */
function logCalls(repo: WorkspaceRepository): string[] {
  const log: string[] = [];
  for (const method of METHODS) {
    const original = (repo[method] as (...args: unknown[]) => Promise<unknown>).bind(repo);
    (repo as unknown as Record<string, unknown>)[method] = async (...args: unknown[]) => {
      if (method === 'load') {
        log.push('load');
        return original(...args);
      }
      const options = args[args.length - 1] as { expectedRevision?: number } | undefined;
      const name = `${method}@${options?.expectedRevision ?? '-'}`;
      try {
        const result = await original(...args);
        log.push(`${name} ok`);
        return result;
      } catch (error) {
        log.push(`${name} ${(error as Error).name}`);
        throw error;
      }
    };
  }
  return log;
}

function setup(options: { autosaveDelay?: number; initial?: WorkspacePayload } = {}) {
  const scripted = scriptedStorage();
  let n = 0;
  const ids = { id: () => `layout-${++n}`, now: () => 1000 + n };
  const repo = new WorkspaceRepository(scripted.storage, 'desk', ids);
  // Another tab on the same account: the same storage, its own repository.
  const other = new WorkspaceRepository(scripted.inner, 'desk', ids);
  const fake = fakeTarget(options.initial);
  const controller = createLayoutsController(repo, fake.target, { autosaveDelay: options.autosaveDelay ?? 1000 });
  const states: LayoutsState[] = [];
  controller.subscribe(state => states.push(state));
  live.push(controller);
  return { ...scripted, repo, other, fake, controller, states };
}

/** A held layout plus a spare one this page has seen, and a store call log from here on. */
async function withSpare(options: { autosaveDelay?: number } = {}) {
  const made = setup(options);
  const held = await made.controller.saveAs('Morning');
  const spare = await made.other.createWorkspace('Spare', payload('SBIN'));
  await made.controller.reload();
  const log = logCalls(made.repo);
  return { ...made, held, spare, log };
}

const live: LayoutsController[] = [];
afterEach(() => {
  for (const controller of live.splice(0)) controller.destroy();
  vi.useRealTimers();
});

const conflict = expect.objectContaining({ name: 'WorkspaceConflictError' });
const settle = async (): Promise<void> => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

describe('layouts controller: opening and saving', () => {
  it('saves as a new layout, holds it, and records it as active and recent in one revision each', async () => {
    const { controller, repo } = setup();
    const doc = await controller.saveAs('Morning');
    const catalog = await repo.load();
    expect(catalog).toMatchObject({ revision: 2, activeWorkspaceId: doc.id, recentWorkspaceIds: [doc.id] });
    expect(catalog.workspaces[0].panes[0].symbol).toBe('INFY');
    expect(controller.state()).toMatchObject({ layoutId: doc.id, revision: 2, dirty: false, busy: false, conflict: false, error: null, autosave: 'off' });
  });

  it('writes the target into the held layout, and refuses to save with no layout held', async () => {
    const { controller, fake, repo } = setup();
    await expect(controller.save()).rejects.toThrow(/No saved layout is held/);
    expect(controller.state().error).toBeInstanceOf(Error);
    const doc = await controller.saveAs('Morning');
    fake.edit('TCS');
    await controller.save();
    expect((await repo.load()).workspaces.find(item => item.id === doc.id)?.panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ revision: 3, dirty: false, error: null });
  });

  it('opens a layout: the target shows it, the store records it, and the change events of the restore are not edits', async () => {
    const { controller, fake, repo } = setup();
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    await controller.setAutosave(true);
    const report = await controller.open(first.id);
    expect(report).toEqual({ applied: true });
    expect(fake.symbol()).toBe('INFY');
    // Nothing is waiting to be saved: the restore's own change events were not taken as edits.
    expect(controller.state()).toMatchObject({ layoutId: first.id, dirty: false, autosave: 'saved' });
    expect(await repo.load()).toMatchObject({ activeWorkspaceId: first.id, recentWorkspaceIds: [first.id, second.id] });
    await controller.flush();
    expect(controller.state()).toMatchObject({ layoutId: first.id, dirty: false });
  });

  it('reports a refused apply and changes nothing, in the store or on the target', async () => {
    const { controller, fake, repo } = setup();
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    const before = await repo.load();
    fake.refuse('unsupported chart type');
    const report = await controller.open(first.id);
    expect(report).toEqual({ applied: false, reason: 'unsupported chart type' });
    expect(await repo.load()).toEqual(before);
    expect(fake.symbol()).toBe('HDFCBANK');
    expect(controller.state()).toMatchObject({ layoutId: second.id, conflict: false, error: null, busy: false });
  });

  it('autosaves a change still waiting for the quiet period into the layout being left, then opens the other', async () => {
    const { controller, fake, repo } = setup({ autosaveDelay: 60_000 });
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    await controller.setAutosave(true);
    await controller.flush();
    fake.edit('WIPRO');
    expect(controller.state().autosave).toBe('pending');
    await controller.open(first.id);
    const catalog = await repo.load();
    expect(catalog.workspaces.find(doc => doc.id === second.id)?.panes[0].symbol).toBe('WIPRO');
    expect(fake.symbol()).toBe('INFY');
    expect(controller.state()).toMatchObject({ layoutId: first.id, dirty: false, autosave: 'saved' });
  });

  it('leaves the layout being left as saved when autosave is off', async () => {
    const { controller, fake, repo } = setup({ autosaveDelay: 60_000 });
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    fake.edit('WIPRO');
    await controller.open(first.id);
    expect((await repo.load()).workspaces.find(doc => doc.id === second.id)?.panes[0].symbol).toBe('HDFCBANK');
  });

  it('continues on the active layout after a page load, without a write', async () => {
    const first = setup({ autosaveDelay: 0 });
    const doc = await first.controller.saveAs('Morning');
    await first.controller.setAutosave(true);
    first.fake.edit('TCS');
    await first.controller.flush();
    first.controller.destroy();
    // The reloaded page: a new repository over the same storage and a chart that starts elsewhere.
    const repo = new WorkspaceRepository(first.inner, 'desk');
    const log = logCalls(repo);
    const fake = fakeTarget(payload('NIFTY', '1d'));
    const controller = createLayoutsController(repo, fake.target, { autosaveDelay: 0 });
    live.push(controller);
    const catalog = await controller.reload();
    expect(catalog.activeWorkspaceId).toBe(doc.id);
    expect(await controller.open(catalog.activeWorkspaceId as string)).toEqual({ applied: true });
    expect(fake.symbol()).toBe('TCS');
    // Reopening what is already active and first in the recent list records nothing.
    expect(log.filter(entry => entry !== 'load')).toEqual([]);
    expect(controller.state()).toMatchObject({ layoutId: doc.id, revision: catalog.revision, dirty: false, autosave: 'saved' });
    fake.edit('SBIN');
    await new Promise(resolve => setTimeout(resolve, 5));
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('SBIN');
  });

  it('puts the previous layout back when another tab saves the one being opened before it is recorded', async () => {
    const { controller, fake, repo, other, interleave } = setup();
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    interleave(() => other.saveWorkspace(first.id, payload('WIPRO')));
    await expect(controller.open(first.id)).rejects.toEqual(conflict);
    expect(fake.symbol()).toBe('HDFCBANK');
    // The held layout is untouched, so its saves go on.
    expect(controller.state()).toMatchObject({ layoutId: second.id, conflict: false, error: conflict });
    expect((await repo.load()).activeWorkspaceId).toBe(second.id);
    // Opening again shows the other tab's version: it is what is stored now.
    expect(await controller.open(first.id)).toEqual({ applied: true });
    expect(fake.symbol()).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ layoutId: first.id, conflict: false, dirty: false, error: null });
  });

  it('holds no layout when the previous one cannot go back either, so nothing autosaves into the wrong one', async () => {
    const { controller, fake, other, interleave } = setup();
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    await controller.saveAs('Second');
    const apply = fake.target.apply.bind(fake.target);
    let calls = 0;
    fake.target.apply = next => (++calls === 1 ? apply(next) : { applied: false, reason: 'the chart is gone' });
    interleave(() => other.saveWorkspace(first.id, payload('WIPRO')));
    await expect(controller.open(first.id)).rejects.toEqual(conflict);
    expect(controller.state()).toMatchObject({ layoutId: null, dirty: false, conflict: false, autosave: 'off' });
  });

  it('deletes the held layout and keeps the target, holding none', async () => {
    const { controller, fake, repo } = setup();
    const doc = await controller.saveAs('Morning');
    await controller.remove(doc.id);
    expect((await repo.load()).workspaces).toEqual([]);
    expect(fake.symbol()).toBe('INFY');
    expect(controller.state()).toMatchObject({ layoutId: null, dirty: false, revision: 3 });
  });

  it('hands reload() a copy of the catalog: a caller trimming the list leaves the held layout as it was', async () => {
    const { controller, fake } = setup();
    const doc = await controller.saveAs('Morning');
    const catalog = await controller.reload();
    catalog.workspaces.length = 0;
    expect(controller.state().catalog?.workspaces.map(item => item.id)).toEqual([doc.id]);
    fake.edit('TCS');
    await controller.save();
    expect(controller.state()).toMatchObject({ conflict: false, dirty: false, error: null });
  });

  it('renames and duplicates without touching the held layout', async () => {
    const { controller, repo } = setup();
    const doc = await controller.saveAs('Morning');
    await controller.rename(doc.id, 'Opening range');
    const copy = await controller.duplicate(doc.id, 'Opening range copy');
    const catalog = await repo.load();
    expect(catalog.workspaces.map(item => item.name)).toEqual(['Opening range', 'Opening range copy']);
    expect(copy.panes).toEqual(catalog.workspaces[0].panes);
    expect(controller.state()).toMatchObject({ layoutId: doc.id, revision: 4, conflict: false });
  });
});

describe('layouts controller: conflicts', () => {
  /** Each operation on the held layout, after another tab saved that layout. */
  const onHeld: Record<string, (c: LayoutsController, id: string) => Promise<unknown>> = {
    save: c => c.save(),
    rename: (c, id) => c.rename(id, 'Renamed here'),
    duplicate: (c, id) => c.duplicate(id, 'Copy made here'),
    remove: (c, id) => c.remove(id),
  };
  for (const [name, run] of Object.entries(onHeld)) {
    it(`${name} is refused when another tab saved the held layout, writes nothing, and marks the conflict`, async () => {
      const { controller, other, repo, held } = await withSpare();
      await other.saveWorkspace(held.id, payload('WIPRO'));
      const stored = await repo.load();
      await expect(run(controller, held.id)).rejects.toEqual(conflict);
      expect(await repo.load()).toEqual(stored);
      expect(controller.state()).toMatchObject({ conflict: true, dirty: true, error: conflict, busy: false, layoutId: held.id });
      // The newer list is shown, and the next write into the held layout is still refused.
      expect(controller.state().catalog?.revision).toBe(stored.revision);
      expect(controller.state().revision).toBeLessThan(stored.revision);
    });
  }

  /** Each operation on the spare layout, after another tab changed that one. */
  const onSpare: Record<string, (c: LayoutsController, id: string) => Promise<unknown>> = {
    open: (c, id) => c.open(id),
    rename: (c, id) => c.rename(id, 'Renamed here'),
    duplicate: (c, id) => c.duplicate(id, 'Copy made here'),
    remove: (c, id) => c.remove(id),
  };
  for (const [name, run] of Object.entries(onSpare)) {
    it(`${name} of another layout is refused when another tab changed that layout in between, and the held one carries on`, async () => {
      const { controller, other, repo, held, spare, interleave, fake } = await withSpare();
      interleave(() => other.saveWorkspace(spare.id, payload('WIPRO')));
      await expect(run(controller, spare.id)).rejects.toEqual(conflict);
      const catalog = await repo.load();
      expect(catalog.workspaces.map(doc => [doc.name, doc.panes[0].symbol])).toEqual([['Morning', 'INFY'], ['Spare', 'WIPRO']]);
      expect(fake.symbol()).toBe('INFY');
      expect(controller.state()).toMatchObject({ layoutId: held.id, conflict: false, error: conflict });
      fake.edit('TCS');
      await controller.save();
      expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    });
  }

  /** Every operation, run after another tab changed something it does not act on. */
  const elsewhere: Record<string, { run: (c: LayoutsController, spare: string) => Promise<unknown>; calls: (at: number) => string[] }> = {
    save: { run: c => c.save(), calls: at => [`saveWorkspace@${at} WorkspaceConflictError`, 'load', `saveWorkspace@${at + 1} ok`] },
    saveAs: {
      run: c => c.saveAs('Evening'),
      calls: at => ['load', `createWorkspace@${at} WorkspaceConflictError`, 'load', `createWorkspace@${at + 1} ok`, `openWorkspace@${at + 2} ok`],
    },
    open: {
      run: (c, spare) => c.open(spare),
      calls: at => ['load', `openWorkspace@${at} WorkspaceConflictError`, 'load', `openWorkspace@${at + 1} ok`],
    },
    rename: { run: (c, spare) => c.rename(spare, 'Spare, renamed'), calls: at => [`rename@${at} WorkspaceConflictError`, 'load', `rename@${at + 1} ok`] },
    duplicate: { run: (c, spare) => c.duplicate(spare, 'Spare copy'), calls: at => [`duplicate@${at} WorkspaceConflictError`, 'load', `duplicate@${at + 1} ok`] },
    remove: { run: (c, spare) => c.remove(spare), calls: at => [`remove@${at} WorkspaceConflictError`, 'load', `remove@${at + 1} ok`] },
    // Turned on, it saves the unsaved change at once.
    setAutosave: {
      run: c => c.setAutosave(true),
      calls: at => [`setAutosave@${at} WorkspaceConflictError`, 'load', `setAutosave@${at + 1} ok`, `saveWorkspace@${at + 2} ok`],
    },
  };
  for (const [name, { run, calls }] of Object.entries(elsewhere)) {
    it(`${name} reads the catalog again and goes ahead when another tab changed only something else`, async () => {
      const { controller, other, repo, spare, interleave, log, fake } = await withSpare();
      const at = (await repo.load()).revision;
      log.length = 0;
      fake.edit('TCS');
      // Another tab opens the spare layout: the recent list changes, and no layout does.
      interleave(() => other.openWorkspace(spare.id));
      await run(controller, spare.id);
      await controller.flush();
      expect(log).toEqual(calls(at));
      const catalog = await repo.load();
      expect(catalog.revision).toBe(at + calls(at).filter(entry => entry.endsWith(' ok')).length + 1);
      expect(controller.state()).toMatchObject({ conflict: false, error: null, busy: false });
      expect(controller.state().catalog?.revision).toBe(catalog.revision);
    });
  }

  it('autosave writes past another tab opening a layout, which moves the revision and nothing it holds', async () => {
    vi.useFakeTimers();
    const { controller, other, repo, spare, fake, log } = await withSpare({ autosaveDelay: 500 });
    await controller.setAutosave(true);
    await other.openWorkspace(spare.id);
    await other.rename('workspace', spare.id, 'Spare, renamed there');
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(log.filter(entry => entry.startsWith('saveWorkspace'))).toEqual(['saveWorkspace@4 WorkspaceConflictError', 'saveWorkspace@6 ok']);
    const catalog = await repo.load();
    expect(catalog.workspaces.map(doc => [doc.name, doc.panes[0].symbol])).toEqual([['Morning', 'TCS'], ['Spare, renamed there', 'SBIN']]);
    expect(catalog.activeWorkspaceId).toBe(spare.id);
    expect(controller.state()).toMatchObject({ conflict: false, autosave: 'saved', revision: 7 });
  });

  it('a rename of the held layout in another tab is not a conflict: what it shows is what this tab saved', async () => {
    const { controller, other, repo, fake, held } = await withSpare();
    await other.rename('workspace', held.id, 'Renamed there');
    fake.edit('TCS');
    await controller.save();
    expect((await repo.load()).workspaces[0]).toMatchObject({ name: 'Renamed there', panes: [expect.objectContaining({ symbol: 'TCS' })] });
    expect(controller.state()).toMatchObject({ conflict: false, dirty: false });
  });

  it('gives up with a conflict when another tab writes before every attempt, and writes nothing of its own', async () => {
    const { controller, other, repo, interleave, log } = await withSpare();
    for (let i = 0; i < 4; i++) interleave(() => other.setAutosave(i % 2 === 0));
    const before = (await repo.load()).revision;
    log.length = 0;
    await expect(controller.saveAs('Evening')).rejects.toEqual(conflict);
    expect(log.filter(entry => entry.startsWith('createWorkspace'))).toHaveLength(4);
    const catalog = await repo.load();
    expect(catalog.revision).toBe(before + 4);
    expect(catalog.workspaces.map(doc => doc.name)).toEqual(['Morning', 'Spare']);
    expect(controller.state()).toMatchObject({ conflict: false, error: conflict, busy: false });
  });

  it('turns autosave on over another tab\'s save of the held layout, and marks the conflict instead of saving over it', async () => {
    const { controller, other, repo, fake, held } = await withSpare({ autosaveDelay: 0 });
    await other.saveWorkspace(held.id, payload('WIPRO'));
    await controller.setAutosave(true);
    expect(controller.state()).toMatchObject({ conflict: true, dirty: true, autosave: 'failed', error: null });
    fake.edit('TCS');
    await new Promise(resolve => setTimeout(resolve, 5));
    await controller.flush();
    const catalog = await repo.load();
    expect(catalog.autosave).toBe(true);
    expect(catalog.workspaces[0].panes[0].symbol).toBe('WIPRO');
  });

  it('saves as a copy out of a conflict, keeping both versions', async () => {
    const { controller, other, repo, fake } = setup();
    const doc = await controller.saveAs('Morning');
    await other.saveWorkspace(doc.id, payload('WIPRO'));
    fake.edit('TCS');
    await expect(controller.save()).rejects.toEqual(conflict);
    const copy = await controller.saveAs('Morning, this tab');
    const catalog = await repo.load();
    expect(catalog.workspaces.map(item => [item.name, item.panes[0].symbol])).toEqual([['Morning', 'WIPRO'], ['Morning, this tab', 'TCS']]);
    expect(controller.state()).toMatchObject({ layoutId: copy.id, conflict: false, dirty: false });
  });

  it('reloads the list and keeps the conflict, however often; save stays refused and overwrite writes this tab over it', async () => {
    const { controller, other, repo, fake } = setup();
    const doc = await controller.saveAs('Morning');
    await other.saveWorkspace(doc.id, payload('WIPRO'));
    await controller.reload();
    expect(controller.state()).toMatchObject({ layoutId: doc.id, conflict: true, dirty: true, revision: 2 });
    await controller.reload();
    expect(controller.state()).toMatchObject({ conflict: true, dirty: true, revision: 2, autosave: 'off' });
    fake.edit('TCS');
    await expect(controller.save()).rejects.toEqual(conflict);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('WIPRO');
    const written = await controller.overwrite();
    expect(written.panes[0].symbol).toBe('TCS');
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ conflict: false, dirty: false, revision: 4, error: null });
  });

  it('overwrites straight out of a refused save, reading the newer revision itself', async () => {
    const { controller, other, repo, fake } = setup();
    const doc = await controller.saveAs('Morning');
    await other.saveWorkspace(doc.id, payload('WIPRO'));
    fake.edit('TCS');
    await expect(controller.save()).rejects.toEqual(conflict);
    await controller.overwrite();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ conflict: false, dirty: false, error: null, revision: 4 });
  });

  it('refuses to overwrite a layout another tab deleted, and a reload lets go of it', async () => {
    const { controller, other, fake } = setup();
    const doc = await controller.saveAs('Morning');
    await other.remove('workspace', doc.id);
    fake.edit('TCS');
    await expect(controller.save()).rejects.toEqual(conflict);
    expect(controller.state()).toMatchObject({ layoutId: doc.id, conflict: true });
    await expect(controller.overwrite()).rejects.toThrow(/no longer exists/);
    expect(controller.state()).toMatchObject({ layoutId: null, conflict: false, dirty: false });
    expect(fake.symbol()).toBe('TCS');
  });

  it('a reload clears the conflict only when it finds the held layout as this tab left it', async () => {
    const { controller, other, repo, fake } = setup();
    const doc = await controller.saveAs('Morning');
    await other.saveWorkspace(doc.id, payload('WIPRO'));
    await controller.reload();
    expect(controller.state().conflict).toBe(true);
    // The other tab puts back exactly what this tab saved.
    await other.saveWorkspace(doc.id, payload('INFY'));
    await controller.reload();
    expect(controller.state()).toMatchObject({ conflict: false, revision: 4 });
    fake.edit('TCS');
    await controller.save();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
  });

  it('acts on the list it shows while the held layout waits on a change made elsewhere on the page', async () => {
    const { controller, repo } = setup();
    const doc = await controller.saveAs('Morning');
    const other = await controller.saveAs('Evening');
    await controller.open(doc.id);
    const store: WorkspaceStore = repo;
    await store.saveWorkspace(doc.id, payload('WIPRO'));
    expect(controller.state()).toMatchObject({ revision: 5, catalog: expect.objectContaining({ revision: 6 }) });
    // The list the user sees is current, so renaming or deleting another layout goes ahead.
    await controller.rename(other.id, 'Evening session');
    await controller.remove(other.id);
    expect((await repo.load()).workspaces.map(item => item.name)).toEqual(['Morning']);
    // Writing this chart over the held layout would lose the other change, so it is refused.
    await expect(controller.save()).rejects.toEqual(conflict);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('WIPRO');
    expect(controller.state().conflict).toBe(true);
  });

  it('takes a commit another control on this page queued ahead as seen, when it leaves the held layout alone', async () => {
    const { controller, repo, fake } = setup();
    await controller.saveAs('Morning');
    fake.edit('TCS');
    const log = logCalls(repo);
    // The indicator picker saves a template through the same store, just before this save.
    const template = repo.createTemplate('Averages', []);
    const saved = controller.save();
    await Promise.all([template, saved]);
    expect(controller.state()).toMatchObject({ conflict: false, revision: 4, error: null });
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    // Heard through subscribe, it needed no second read: the one refused write is retried at once.
    expect(log.filter(entry => entry !== 'load')).toEqual(['saveWorkspace@2 WorkspaceConflictError', 'saveWorkspace@3 ok']);
  });

  it('refuses a save over a change another control on this page made to the held layout', async () => {
    const { controller, repo, fake } = setup();
    const doc = await controller.saveAs('Morning');
    // Another control on the page, sharing the store, writes its own chart into the same layout.
    const store: WorkspaceStore = repo;
    await store.saveWorkspace(doc.id, payload('WIPRO'), { expectedRevision: 2 });
    fake.edit('TCS');
    await expect(controller.save()).rejects.toEqual(conflict);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ revision: 2, conflict: true });
    expect(controller.state().catalog?.revision).toBe(3);
  });
});

describe('layouts controller: subscribe and serialization', () => {
  it('reports each step of an operation in order, with the commit seen before the operation resolves', async () => {
    const { controller, states } = setup();
    const resolved = controller.saveAs('Morning').then(doc => {
      states.push({ ...controller.state(), layoutId: `resolved ${doc.id}` });
    });
    await resolved;
    expect(states.map(s => [s.busy, s.catalog?.revision ?? null, s.revision, s.layoutId])).toEqual([
      [true, null, null, null],
      [true, 1, 1, null],
      [true, 2, 2, 'layout-1'],
      [false, 2, 2, 'layout-1'],
      [false, 2, 2, 'resolved layout-1'],
    ]);
  });

  it('stops notifying after unsubscribe and after destroy, and a failing listener does not stop the others', async () => {
    const { controller } = setup();
    const reported: unknown[] = [];
    const later = vi.spyOn(globalThis, 'queueMicrotask').mockImplementation(task => {
      try { task(); } catch (error) { reported.push(error); }
    });
    try {
      const after = vi.fn();
      const off = controller.subscribe(() => { throw new Error('menu listener'); });
      controller.subscribe(after);
      await controller.saveAs('Morning');
      expect(after).toHaveBeenCalled();
      expect(reported[0]).toEqual(new Error('menu listener'));
      off();
      const calls = after.mock.calls.length;
      await controller.rename('layout-1', 'Renamed');
      expect(after.mock.calls.length).toBeGreaterThan(calls);
      controller.destroy();
      const final = after.mock.calls.length;
      await expect(controller.rename('layout-1', 'After destroy')).rejects.toThrow(/destroyed/);
      expect(after.mock.calls.length).toBe(final);
    } finally { later.mockRestore(); }
  });

  it('runs a burst of operations one at a time, in call order, each against the revision the last one left', async () => {
    const { controller, repo, fake } = setup();
    const log: string[] = [];
    let active = 0;
    for (const method of METHODS) {
      const original = (repo[method] as (...args: unknown[]) => Promise<unknown>).bind(repo);
      (repo as unknown as Record<string, unknown>)[method] = async (...args: unknown[]) => {
        const options = args[args.length - 1] as { expectedRevision?: number } | undefined;
        log.push(`${method} at ${options?.expectedRevision ?? '-'}`);
        active++;
        expect(active).toBe(1);
        try {
          await new Promise(resolve => setTimeout(resolve, Math.floor(Math.random() * 3)));
          return await original(...args);
        } finally { active--; }
      };
    }
    fake.edit('TCS');
    const burst = [
      controller.saveAs('One'),
      controller.save(),
      controller.rename('layout-1', 'One renamed'),
      controller.duplicate('layout-1', 'Two'),
      controller.setAutosave(true),
      controller.remove('layout-2'),
      controller.save(),
    ];
    expect(controller.state().busy).toBe(true);
    await Promise.all(burst);
    expect(log).toEqual([
      'load at -', 'createWorkspace at 0', 'openWorkspace at 1',
      'saveWorkspace at 2', 'rename at 3', 'duplicate at 4', 'setAutosave at 5', 'remove at 6', 'saveWorkspace at 7',
    ]);
    const catalog = await repo.load();
    expect(catalog).toMatchObject({ revision: 8, autosave: true });
    expect(catalog.workspaces.map(item => item.name)).toEqual(['One renamed']);
    expect(controller.state()).toMatchObject({ busy: false, revision: 8, layoutId: 'layout-1', conflict: false });
  });

  it('keeps running after a failed operation in the burst', async () => {
    const { controller, repo } = setup();
    const results = await Promise.allSettled([
      controller.saveAs('One'), controller.rename('missing', 'Nope'), controller.saveAs(' '), controller.saveAs('Two'),
    ]);
    expect(results.map(r => r.status)).toEqual(['fulfilled', 'rejected', 'rejected', 'fulfilled']);
    expect((await repo.load()).workspaces.map(item => item.name)).toEqual(['One', 'Two']);
    expect(controller.state()).toMatchObject({ busy: false, error: null, conflict: false, layoutId: 'layout-2' });
  });
});

describe('layouts controller: dirty state and autosave', () => {
  it('marks the target dirty once changes settle, and clears it when a change is undone', async () => {
    vi.useFakeTimers();
    const { controller, fake } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    fake.edit('TCS');
    expect(controller.state().dirty).toBe(false);
    await vi.advanceTimersByTimeAsync(500);
    expect(controller.state()).toMatchObject({ dirty: true, autosave: 'off' });
    fake.edit('INFY');
    await vi.advanceTimersByTimeAsync(500);
    expect(controller.state().dirty).toBe(false);
  });

  it('writes one autosave after the changes settle, with the last of them', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo, states } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    await vi.advanceTimersByTimeAsync(0);
    const writes = vi.spyOn(repo, 'saveWorkspace');
    for (const symbol of ['TCS', 'WIPRO', 'HDFCBANK', 'SBIN']) {
      fake.edit(symbol);
      await vi.advanceTimersByTimeAsync(400);
    }
    expect(writes).not.toHaveBeenCalled();
    expect(controller.state().autosave).toBe('pending');
    const seen = states.length;
    await vi.advanceTimersByTimeAsync(100);
    await controller.flush();
    expect(writes).toHaveBeenCalledTimes(1);
    expect(writes.mock.calls[0][1].panes[0].symbol).toBe('SBIN');
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('SBIN');
    const steps = states.slice(seen).map(s => s.autosave).filter((step, i, all) => step !== all[i - 1]);
    expect(steps).toEqual(['saving', 'saved']);
    expect(controller.state()).toMatchObject({ dirty: false, autosave: 'saved' });
  });

  it('skips the write when the settled target matches what is stored', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    const writes = vi.spyOn(repo, 'saveWorkspace');
    fake.edit('TCS');
    fake.edit('INFY');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(writes).not.toHaveBeenCalled();
    expect(controller.state().autosave).toBe('saved');
  });

  it('writes nothing while autosave is off, and saves what is unsaved when it is turned on', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(1000);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('INFY');
    expect(controller.state()).toMatchObject({ dirty: true, autosave: 'off' });
    await controller.setAutosave(true);
    // No further change and no flush: the operation queued next runs after that save.
    await controller.reload();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ dirty: false, autosave: 'saved' });
  });

  it('flush saves at once, without waiting for the quiet period', async () => {
    const { controller, fake, repo } = setup({ autosaveDelay: 60_000 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    fake.edit('TCS');
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
  });

  it('stops after a failed autosave until a save succeeds, and says why', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo, failWrites } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    failWrites(new Error('quota exceeded'));
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(controller.state()).toMatchObject({ autosave: 'failed', dirty: true, conflict: false, error: new Error('quota exceeded') });
    failWrites(null);
    const writes = vi.spyOn(repo, 'saveWorkspace');
    fake.edit('WIPRO');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    // Paused: a failing store is not written on every pan.
    expect(writes).not.toHaveBeenCalled();
    await controller.save();
    expect(controller.state()).toMatchObject({ autosave: 'saved', error: null, dirty: false });
    fake.edit('SBIN');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(writes).toHaveBeenCalledTimes(2);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('SBIN');
  });

  it('resumes a paused autosave after a reload, without waiting for another change', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo, failWrites } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    failWrites(new Error('quota exceeded'));
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(controller.state()).toMatchObject({ autosave: 'failed', dirty: true });
    failWrites(null);
    await controller.reload();
    // Pending means a write is on its way: the next queued operation runs after it.
    await controller.reload();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ autosave: 'saved', dirty: false, error: null });
  });

  it('resumes a paused autosave once any write goes through again', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo, failWrites } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    const spare = await controller.duplicate('layout-1', 'Spare');
    await controller.setAutosave(true);
    failWrites(new Error('quota exceeded'));
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(controller.state()).toMatchObject({ autosave: 'failed', dirty: true });
    failWrites(null);
    // Renaming another layout proves the store takes writes again. No change follows and nothing is flushed.
    await controller.rename(spare.id, 'Spare, renamed');
    await vi.waitFor(async () => expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS'));
    expect(controller.state()).toMatchObject({ autosave: 'saved', dirty: false });
  });

  it('saves the unsaved change when another control on the page turns autosave on', async () => {
    const { controller, fake, repo } = setup({ autosaveDelay: 60_000 });
    await controller.saveAs('Morning');
    fake.edit('TCS');
    await controller.flush();
    expect(controller.state()).toMatchObject({ dirty: true, autosave: 'off' });
    const store: WorkspaceStore = repo;
    await store.setAutosave(true);
    // No change follows and nothing is flushed: the commit the controller hears queues the write.
    await vi.waitFor(async () => expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS'));
    expect(controller.state()).toMatchObject({ dirty: false, autosave: 'saved' });
  });

  it('refuses to open another layout when the change waiting for the layout being left cannot be saved', async () => {
    const { controller, fake, repo, failWrites } = setup({ autosaveDelay: 60_000 });
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    await controller.setAutosave(true);
    fake.edit('WIPRO');
    // The menu sees nothing unsaved yet: the change is still waiting for the quiet period.
    expect(controller.state()).toMatchObject({ dirty: false, autosave: 'pending' });
    failWrites(new Error('quota exceeded'));
    await expect(controller.open(first.id)).rejects.toThrow('quota exceeded');
    // The change is still on the chart, and the menu is told why it was not saved.
    expect(fake.symbol()).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ layoutId: second.id, dirty: true, autosave: 'failed', error: new Error('quota exceeded') });
    failWrites(null);
    expect((await repo.load()).activeWorkspaceId).toBe(second.id);
    // Asked again, the user has been told: the layout opens and the change is left behind.
    expect(await controller.open(first.id)).toEqual({ applied: true });
    expect(fake.symbol()).toBe('INFY');
    expect((await repo.load()).workspaces.find(doc => doc.id === second.id)?.panes[0].symbol).toBe('HDFCBANK');
  });

  it('refuses to open another layout when the change waiting for the layout being left meets another tab\'s save', async () => {
    const { controller, fake, repo, other } = setup({ autosaveDelay: 60_000 });
    const first = await controller.saveAs('First');
    fake.edit('HDFCBANK');
    const second = await controller.saveAs('Second');
    await controller.setAutosave(true);
    await other.saveWorkspace(second.id, payload('SBIN'));
    fake.edit('WIPRO');
    await expect(controller.open(first.id)).rejects.toEqual(conflict);
    expect(fake.symbol()).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ layoutId: second.id, conflict: true, dirty: true, autosave: 'failed' });
    expect((await repo.load()).workspaces.find(doc => doc.id === second.id)?.panes[0].symbol).toBe('SBIN');
  });

  it('takes the default quiet period for a delay that is not a finite number', async () => {
    for (const autosaveDelay of [Number.NaN, Number.POSITIVE_INFINITY]) {
      vi.useFakeTimers();
      const { controller, fake, repo } = setup({ autosaveDelay });
      await controller.saveAs('Morning');
      await controller.setAutosave(true);
      await vi.advanceTimersByTimeAsync(0);
      const writes = vi.spyOn(repo, 'saveWorkspace');
      fake.edit('TCS');
      await vi.advanceTimersByTimeAsync(999);
      expect(writes).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      await controller.flush();
      expect(writes).toHaveBeenCalledTimes(1);
      controller.destroy();
      vi.useRealTimers();
    }
  });

  it('never autosaves over a layout another tab saved: the conflict holds until the user chooses', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo, other } = setup({ autosaveDelay: 500 });
    const doc = await controller.saveAs('Morning');
    await controller.setAutosave(true);
    await other.saveWorkspace(doc.id, payload('WIPRO'));
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(controller.state()).toMatchObject({ conflict: true, autosave: 'failed', error: conflict });
    await controller.reload();
    fake.edit('HDFCBANK');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ conflict: true, autosave: 'failed', dirty: true });
    // Opening it again takes the other tab's version, and autosave resumes from there.
    await controller.open(doc.id);
    expect(fake.symbol()).toBe('WIPRO');
    fake.edit('SBIN');
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('SBIN');
    expect(controller.state()).toMatchObject({ conflict: false, autosave: 'saved' });
  });

  it('keeps a change made while an autosave was in flight for the next one', async () => {
    const { controller, fake, repo, states } = setup({ autosaveDelay: 0 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    await controller.flush();
    const seen = states.length;
    const save = repo.saveWorkspace.bind(repo);
    let edited = false;
    vi.spyOn(repo, 'saveWorkspace').mockImplementation(async (...args) => {
      if (!edited) { edited = true; fake.edit('WIPRO'); }
      return save(...args);
    });
    fake.edit('TCS');
    await new Promise(resolve => setTimeout(resolve, 5));
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('WIPRO');
    expect(controller.state()).toMatchObject({ dirty: false, autosave: 'saved' });
    // Between the two writes the target still differed from what was stored.
    const after = states.slice(seen);
    const first = after.findIndex(s => s.autosave === 'saving');
    const between = after.slice(first).find(s => s.autosave !== 'saving');
    expect(between).toMatchObject({ dirty: true, autosave: 'pending' });
  });

  it('drops a pending autosave on destroy and writes nothing afterwards', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    const writes = vi.spyOn(repo, 'saveWorkspace');
    fake.edit('TCS');
    controller.destroy();
    await vi.advanceTimersByTimeAsync(1000);
    await settle();
    expect(writes).not.toHaveBeenCalled();
    await expect(controller.save()).rejects.toThrow(/destroyed/);
  });

  it('takes changes from a target without subscribe through changed()', async () => {
    let symbol = 'INFY';
    const target: LayoutTarget = { capture: () => payload(symbol), apply: p => { symbol = p.panes[0].symbol; return { applied: true }; } };
    const repo = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => 'only', now: () => 1 });
    const controller = createLayoutsController(repo, target, { autosaveDelay: 0 });
    live.push(controller);
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    symbol = 'TCS';
    controller.changed();
    await new Promise(resolve => setTimeout(resolve, 5));
    await controller.flush();
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
  });
});

/** Bars like a real stock: a seeded random walk, never a smooth curve. */
function walk(count: number, start: number, seed: number): Bar[] {
  let s = seed;
  let close = start;
  return Array.from({ length: count }, (_, i) => {
    s = (s * 16807) % 2147483647;
    const open = close;
    close = Math.round((open + (s / 2147483647 - 0.5) * start * 0.004) * 20) / 20;
    return { time: 1_700_000_000 + i * 300, open, high: Math.max(open, close) + 0.35, low: Math.min(open, close) - 0.35, close, volume: 1000 + (s % 500) };
  });
}

describe('layouts controller: a suspended target', () => {
  it('holds autosave while the target is suspended and writes the change once it resumes', async () => {
    vi.useFakeTimers();
    const { controller, fake, repo } = setup({ autosaveDelay: 500 });
    await controller.saveAs('Morning');
    await controller.setAutosave(true);
    await vi.advanceTimersByTimeAsync(0);
    const writes = vi.spyOn(repo, 'saveWorkspace');
    fake.suspend(true);
    fake.edit('TCS');
    await vi.advanceTimersByTimeAsync(3000);
    await controller.flush();
    expect(writes).not.toHaveBeenCalled();
    expect(controller.state()).toMatchObject({ suspended: true, dirty: true, autosave: 'pending' });
    // The target says it is back through its listener, as the widget's replay events do.
    fake.suspend(false);
    await vi.advanceTimersByTimeAsync(500);
    await controller.flush();
    expect(writes).toHaveBeenCalledTimes(1);
    expect((await repo.load()).workspaces[0].panes[0].symbol).toBe('TCS');
    expect(controller.state()).toMatchObject({ suspended: false, dirty: false, autosave: 'saved' });
  });

  it('refuses to open a layout while suspended and changes nothing, and saves when the user asks', async () => {
    const { controller, fake, other, repo } = setup({ autosaveDelay: 0 });
    const held = await controller.saveAs('Morning');
    const spare = await other.createWorkspace('Spare', payload('SBIN'));
    fake.suspend(true);
    await expect(controller.open(spare.id)).rejects.toThrow(/suspended/);
    expect(fake.symbol()).toBe('INFY');
    expect(controller.state()).toMatchObject({ layoutId: held.id, suspended: true });
    fake.edit('TCS');
    await controller.save();
    expect((await repo.load()).workspaces.find(item => item.id === held.id)?.panes[0].symbol).toBe('TCS');
    fake.suspend(false);
    expect(await controller.open(spare.id)).toEqual({ applied: true });
    expect(fake.symbol()).toBe('SBIN');
  });

  it('treats a target that cannot say whether it is suspended as running', async () => {
    const { controller, repo } = setup({ autosaveDelay: 0 });
    const target: LayoutTarget = {
      capture: () => payload('INFY'), apply: () => ({ applied: true }),
      suspended: () => { throw new Error('host bug'); },
    };
    const second = createLayoutsController(repo, target, { autosaveDelay: 0 });
    live.push(second);
    await second.saveAs('Other');
    expect(second.state().suspended).toBe(false);
    expect(controller.state().suspended).toBe(false);
  });
});

describe('layouts controller on a chart grid', () => {
  const feed: DataFeed = { getBars: async request => walk(120, request.symbol === 'TCS' ? 3920 : 1510, request.symbol.length) };

  function makeGrid(): ChartGrid {
    const doc = fakeWidgetDocument();
    const grid = createChartGrid(fakeContainer(doc, 1200, 800) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, feed,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      symbol: 'INFY', exchange: 'NSE', interval: '5m', now: () => 1_700_040_000_000, rail: false, preset: '1x1',
    });
    for (const cell of grid.cells()) cell.widget.chart.applySize(600, 400);
    return grid;
  }

  it('saves the grid, restores it after the user changes it, and reports a desk the grid cannot show', async () => {
    const grid = makeGrid();
    try {
      const target: LayoutTarget = { capture: () => grid.getWorkspace(), apply: p => grid.applyWorkspace(p) };
      const repo = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: (() => { let n = 0; return () => `grid-${++n}`; })(), now: () => 1 });
      const controller = createLayoutsController(repo, target);
      live.push(controller);
      const saved = await controller.saveAs('Two charts');
      expect(saved.layout).toMatchObject({ rows: 1, columns: 1 });
      grid.setPreset('1x2');
      grid.cells()[1].widget.setSymbol('TCS', 'NSE');
      expect(grid.cells()).toHaveLength(2);
      expect(await controller.open(saved.id)).toEqual({ applied: true });
      expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['INFY']);
      // A desk saved by a host that shows comparisons: this grid cannot, and says so.
      const foreign = await repo.createWorkspace('Foreign desk', workspaceFixture());
      const report = await controller.open(foreign.id);
      expect(report.applied).toBe(false);
      expect(report.reason).toMatch(/comparison/);
      expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['INFY']);
      expect(controller.state().layoutId).toBe(saved.id);
      expect((await repo.load()).activeWorkspaceId).toBe(saved.id);
    } finally { grid.destroy(); }
  });
});

describe('layouts controller on one widget', () => {
  /**
   * A single widget as a target: its state in the portable one-pane form
   * (`migrateWidgetWorkspace`, as a host that loaded the workspace tier
   * would), restored through `restoreState`.
   */
  function widgetTarget(widget: Widget): LayoutTarget {
    return {
      capture() {
        // A chart state carries absent optional fields; the portable form is plain JSON.
        const state = JSON.parse(JSON.stringify(widget.getState())) as unknown;
        const { layout, panes, activePaneId, sync } = migrateWidgetWorkspace(state, { id: 'capture', name: 'capture', now: 0 });
        return { layout, panes, activePaneId, sync };
      },
      apply(next) {
        if (next.panes.length !== 1) return { applied: false, reason: `one chart cannot show ${next.panes.length}` };
        const [pane] = next.panes;
        // The pane carries the rail's magnet and stay; the rest of the rail (favourites, last tools) stays the user's.
        const rail = widget.getState().rail;
        return widget.restoreState({
          version: 1, symbol: pane.symbol, exchange: pane.exchange, interval: pane.interval, chartType: pane.chartType,
          chart: pane.chart, theme: pane.settings['widget.theme'], ...(pane.variant ? { variant: pane.variant } : {}),
          ...(rail === null ? {} : { rail: { ...rail, magnet: pane.magnet, stay: pane.stay } }),
        });
      },
      subscribe(listener) {
        const offs = (['symbol', 'interval', 'theme', 'layout'] as const).map(event => widget.on(event, listener));
        return () => { for (const off of offs) off(); };
      },
    };
  }

  it('saves one chart, autosaves the user\'s change, and restores another layout onto it', async () => {
    const doc = fakeWidgetDocument();
    const widget = createWidget(fakeContainer(doc, 900, 600) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, panels: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      symbol: 'INFY', exchange: 'NSE', interval: '5m',
    });
    try {
      widget.chart.applySize(900, 600);
      widget.series.setData(walk(200, 1510, 7));
      let n = 0;
      const repo = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => `widget-${++n}`, now: () => 1 });
      const controller = createLayoutsController(repo, widgetTarget(widget), { autosaveDelay: 0 });
      live.push(controller);
      const morning = await controller.saveAs('Morning');
      widget.setInterval('15m');
      widget.setSymbol('TCS', 'NSE');
      const evening = await controller.saveAs('Evening');
      await controller.setAutosave(true);
      widget.setInterval('1h');
      await new Promise(resolve => setTimeout(resolve, 5));
      await controller.flush();
      expect((await repo.load()).workspaces.find(item => item.id === evening.id)?.panes[0]).toMatchObject({ symbol: 'TCS', interval: '1h' });
      const writes = vi.spyOn(repo, 'saveWorkspace');
      // The target's own report comes back whole: the widget adds the engine's report for the chart.
      expect(await controller.open(morning.id)).toMatchObject({ applied: true, chart: { applied: true } });
      expect([widget.symbol(), widget.interval()]).toEqual(['INFY', '5m']);
      // The widget's own symbol and interval events during the restore were not edits.
      await new Promise(resolve => setTimeout(resolve, 5));
      await controller.flush();
      expect(writes).not.toHaveBeenCalled();
      expect(controller.state()).toMatchObject({ layoutId: morning.id, dirty: false, autosave: 'saved' });
      // A desk of two charts is not for one widget: reported, and nothing changes.
      const desk = await repo.createWorkspace('Desk', { ...workspaceFixture(), panes: workspaceFixture().panes.map(pane => ({ ...pane, comparisons: [] })) });
      expect(await controller.open(desk.id)).toEqual({ applied: false, reason: 'one chart cannot show 2' });
      expect(widget.symbol()).toBe('INFY');
    } finally { widget.destroy(); }
  });

  it('brings back the magnet and the stay-in-drawing choice a layout was saved with, as the grid does', async () => {
    const doc = fakeWidgetDocument();
    const widget = createWidget(fakeContainer(doc, 900, 600) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, panels: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      symbol: 'INFY', exchange: 'NSE', interval: '5m',
    });
    try {
      widget.chart.applySize(900, 600);
      widget.series.setData(walk(200, 1510, 11));
      const rail = widget.getState().rail;
      expect(rail).not.toBeNull();
      widget.restoreState({ ...widget.getState(), rail: { ...rail!, magnet: 'strong', stay: true } });
      const repo = new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => 'magnet', now: () => 1 });
      const controller = createLayoutsController(repo, widgetTarget(widget), { autosaveDelay: 0 });
      live.push(controller);
      const saved = await controller.saveAs('Snapping');
      expect(saved.panes[0]).toMatchObject({ magnet: 'strong', stay: true });
      widget.restoreState({ ...widget.getState(), rail: { ...rail!, magnet: 'off', stay: false } });
      expect(await controller.open(saved.id)).toMatchObject({ applied: true });
      expect(widget.getState().rail).toMatchObject({ magnet: 'strong', stay: true });
      expect(controller.state()).toMatchObject({ dirty: false, layoutId: saved.id });
    } finally { widget.destroy(); }
  });
});

describe('layouts controller tier boundary', () => {
  it('imports the workspace tier as types only, so a widget host never loads it unasked', () => {
    const imports = layoutsSource.match(/^import[^;]+;/gm) ?? [];
    expect(imports.length).toBeGreaterThan(0);
    for (const line of imports) expect(line).toMatch(/^import type /);
  });

  it('keeps catalog notifications ordered: the state names the newest catalog the store committed', async () => {
    const { controller, repo } = setup();
    await controller.reload();
    const seen: Array<WorkspaceCatalog | null> = [];
    controller.subscribe(state => seen.push(state.catalog));
    await repo.createTemplate('A', []);
    await repo.createTemplate('B', []);
    expect(seen.map(c => c?.revision)).toEqual([1, 2]);
    expect(controller.state()).toMatchObject({ revision: 2, conflict: false });
  });
});
