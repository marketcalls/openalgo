import { describe, expect, it } from 'vitest';
import {
  WatchlistRepository, WatchlistConflictError, WorkspaceDocumentError, createMemoryWatchlistStorage,
  parseWatchlistCatalog, watchlistKey,
  type WatchlistCatalog, type WatchlistStorage,
} from '../src/workspace/index';

function rig(storage: WatchlistStorage = createMemoryWatchlistStorage()) {
  let next = 0;
  let clock = 1000;
  const repo = new WatchlistRepository(storage, 'account-a', { id: () => `list-${++next}`, now: () => clock++ });
  return { repo, storage };
}

const nse = (symbol: string) => ({ symbol, exchange: 'NSE' });

describe('watchlist identity', () => {
  it('is an exact symbol and exchange pair that no separator can forge', () => {
    expect(watchlistKey({ symbol: 'RELIANCE', exchange: 'NSE' })).not.toBe(watchlistKey({ symbol: 'RELIANCE', exchange: 'BSE' }));
    expect(watchlistKey({ symbol: 'reliance', exchange: 'NSE' })).not.toBe(watchlistKey({ symbol: 'RELIANCE', exchange: 'NSE' }));
    // A naive "exchange:symbol" join would make these two the same key.
    expect(watchlistKey({ symbol: 'B:C', exchange: 'A' })).not.toBe(watchlistKey({ symbol: 'C', exchange: 'A:B' }));
  });
});

describe('watchlist repository', () => {
  it('creates, renames, duplicates, activates and removes named lists with persisted revisions', async () => {
    const { repo, storage } = rig();
    const tech = await repo.createList('Tech', [nse('INFY'), nse('TCS')]);
    expect(tech).toMatchObject({ id: 'list-1', name: 'Tech', createdAt: 1000, updatedAt: 1000 });
    expect(tech.entries).toEqual([nse('INFY'), nse('TCS')]);
    const banks = await repo.createList('Banks');
    await repo.setActiveList(banks.id);
    await repo.renameList(tech.id, '  IT services  ');
    const copy = await repo.duplicateList(tech.id, 'IT copy');
    expect(copy.entries).toEqual(tech.entries);
    expect(copy.id).not.toBe(tech.id);
    const catalog = await repo.load();
    expect(catalog.revision).toBe(5);
    expect(catalog.lists.map(list => list.name)).toEqual(['IT services', 'Banks', 'IT copy']);
    expect(catalog.activeListId).toBe(banks.id);
    await repo.removeList(banks.id);
    const after = await repo.load();
    expect(after.lists.map(list => list.id)).toEqual([tech.id, copy.id]);
    // The active list goes with it rather than pointing at nothing.
    expect(after.activeListId).toBeNull();
    // A second repository over the same storage sees the committed catalog.
    const reopened = await new WatchlistRepository(storage, 'account-a').load();
    expect(reopened).toEqual(after);
    // Namespaces never see each other's lists.
    expect((await new WatchlistRepository(storage, 'account-b').load()).lists).toEqual([]);
  });

  it('keeps the same symbol on two venues as two entries and rejects an exact repeat', async () => {
    const { repo } = rig();
    const list = await repo.createList('Dual listed', [nse('RELIANCE')]);
    const both = await repo.addEntry(list.id, { symbol: 'RELIANCE', exchange: 'BSE' });
    expect(both.entries).toEqual([nse('RELIANCE'), { symbol: 'RELIANCE', exchange: 'BSE' }]);
    await expect(repo.addEntry(list.id, nse('RELIANCE'))).rejects.toThrow(/already/);
    // Case is part of the opaque identity: nothing is folded.
    const lower = await repo.addEntry(list.id, { symbol: 'reliance', exchange: 'NSE' });
    expect(lower.entries).toHaveLength(3);
    await expect(repo.createList('Repeats', [nse('A'), nse('A')])).rejects.toThrow(/Duplicate/);
    expect((await repo.load()).revision).toBe(3);
  });

  it('inserts, moves and removes entries by identity', async () => {
    const { repo } = rig();
    const list = await repo.createList('Order', [nse('A'), nse('B'), nse('C')]);
    expect((await repo.addEntry(list.id, nse('Z'), { index: 1 })).entries.map(e => e.symbol)).toEqual(['A', 'Z', 'B', 'C']);
    expect((await repo.moveEntry(list.id, nse('A'), 3)).entries.map(e => e.symbol)).toEqual(['Z', 'B', 'C', 'A']);
    expect((await repo.moveEntry(list.id, nse('C'), -5)).entries.map(e => e.symbol)).toEqual(['C', 'Z', 'B', 'A']);
    expect((await repo.removeEntry(list.id, nse('Z'))).entries.map(e => e.symbol)).toEqual(['C', 'B', 'A']);
    await expect(repo.removeEntry(list.id, nse('Z'))).rejects.toThrow(/not in/);
    await expect(repo.removeEntry('missing', nse('A'))).rejects.toThrow(/does not exist/);
  });

  it('applies each change to the latest stored catalog, so another session\'s edit survives', async () => {
    const storage = createMemoryWatchlistStorage();
    const first = rig(storage).repo;
    const list = await first.createList('Shared', [nse('A')]);
    const second = new WatchlistRepository(storage, 'account-a', { now: () => 5000, id: () => 'other' });
    await second.addEntry(list.id, nse('B'));
    await first.addEntry(list.id, nse('C'));
    expect((await first.load()).lists[0].entries.map(e => e.symbol)).toEqual(['A', 'B', 'C']);
  });

  it('refuses a change prepared from a revision that has since moved, and writes nothing', async () => {
    const { repo } = rig();
    const list = await repo.createList('Order', [nse('A'), nse('B')]);
    const seen = (await repo.load()).revision;
    await repo.addEntry(list.id, nse('C'));
    await expect(repo.moveEntry(list.id, nse('A'), 1, { expectedRevision: seen })).rejects.toBeInstanceOf(WatchlistConflictError);
    const catalog = await repo.load();
    expect(catalog.lists[0].entries.map(e => e.symbol)).toEqual(['A', 'B', 'C']);
    await repo.moveEntry(list.id, nse('A'), 1, { expectedRevision: catalog.revision });
    expect((await repo.load()).lists[0].entries.map(e => e.symbol)).toEqual(['B', 'A', 'C']);
  });

  it('surfaces a storage conflict from a concurrent writer and stays usable', async () => {
    const memory = createMemoryWatchlistStorage();
    let race = false;
    const storage: WatchlistStorage = {
      read: namespace => memory.read(namespace),
      async write(namespace, catalog, expected, options) {
        if (race) {
          race = false;
          // Another tab commits between this session's read and its write.
          const current = parseWatchlistCatalog(await memory.read(namespace));
          await memory.write(namespace, { ...current, revision: current.revision + 1 }, current.revision);
        }
        return memory.write(namespace, catalog, expected, options);
      },
    };
    const { repo } = rig(storage);
    const list = await repo.createList('Race', [nse('A')]);
    race = true;
    await expect(repo.addEntry(list.id, nse('B'))).rejects.toBeInstanceOf(WatchlistConflictError);
    expect((await repo.load()).lists[0].entries).toEqual([nse('A')]);
    await repo.addEntry(list.id, nse('B'));
    expect((await repo.load()).lists[0].entries).toEqual([nse('A'), nse('B')]);
  });

  it('never replaces corrupt storage and validates every candidate before writing', async () => {
    const memory = createMemoryWatchlistStorage({ 'account-a': { version: 7, revision: 1, lists: [], activeListId: null } });
    const writes: number[] = [];
    const storage: WatchlistStorage = {
      read: namespace => memory.read(namespace),
      write: async (namespace, catalog, expected) => { writes.push(expected); return memory.write(namespace, catalog, expected); },
    };
    const repo = new WatchlistRepository(storage, 'account-a', { id: () => 'x' });
    await expect(repo.load()).rejects.toBeInstanceOf(WorkspaceDocumentError);
    await expect(repo.createList('Any')).rejects.toBeInstanceOf(WorkspaceDocumentError);
    expect(writes).toEqual([]);
    const { repo: clean } = rig();
    await expect(clean.createList('', [])).rejects.toThrow(/name/);
    await expect(clean.createList('Bad', [{ symbol: 'A\u0007', exchange: 'NSE' }])).rejects.toThrow(/symbol/);
    await expect(clean.createList('Bad', [{ symbol: 'A', exchange: 3 as unknown as string }])).rejects.toThrow(/exchange/);
    expect((await clean.load()).revision).toBe(0);
  });

  it('checks cancellation before reading and before writing', async () => {
    const memory = createMemoryWatchlistStorage();
    const calls: string[] = [];
    const controller = new AbortController();
    const storage: WatchlistStorage = {
      read: async namespace => { calls.push('read'); const value = await memory.read(namespace); controller.abort(new Error('superseded')); return value; },
      write: async (namespace, catalog, expected, options) => { calls.push('write'); return memory.write(namespace, catalog, expected, options); },
    };
    const repo = new WatchlistRepository(storage, 'account-a', { id: () => 'x' });
    await expect(repo.createList('Late', [], { signal: controller.signal })).rejects.toThrow('superseded');
    expect(calls).toEqual(['read']);
    const early = new AbortController();
    early.abort(new Error('never started'));
    calls.length = 0;
    await expect(repo.createList('Early', [], { signal: early.signal })).rejects.toThrow('never started');
    expect(calls).toEqual([]);
  });

  it('notifies subscribers after each committed write and stops after unsubscribe', async () => {
    const { repo } = rig();
    const seen: WatchlistCatalog[] = [];
    const off = repo.subscribe(catalog => seen.push(catalog));
    const list = await repo.createList('Watch');
    await repo.addEntry(list.id, nse('A'));
    await expect(repo.addEntry(list.id, nse('A'))).rejects.toThrow();
    off();
    await repo.addEntry(list.id, nse('B'));
    expect(seen.map(catalog => catalog.revision)).toEqual([1, 2]);
    expect(seen[1].lists[0].entries).toEqual([nse('A')]);
    // Listeners get a copy: a listener editing it cannot touch the next reader's catalog.
    seen[1].lists[0].entries.push(nse('ZZ'));
    expect((await repo.load()).lists[0].entries).toEqual([nse('A'), nse('B')]);
  });

  it('enforces list and entry limits', async () => {
    const { repo } = rig();
    const many = Array.from({ length: 501 }, (_, i) => nse(`S${i}`));
    await expect(repo.createList('Too many', many)).rejects.toThrow(/limit/);
    const catalog = parseWatchlistCatalog({ version: 1, revision: 0, lists: [], activeListId: null });
    expect(catalog.lists).toEqual([]);
    expect(() => parseWatchlistCatalog({ version: 1, revision: 0, lists: [], activeListId: 'ghost' })).toThrow(/Active/);
  });

  it('memory storage rejects a stale or skipped revision like the IndexedDB adapter', async () => {
    const storage = createMemoryWatchlistStorage();
    const catalog = { version: 1 as const, revision: 1, lists: [], activeListId: null };
    await storage.write('ns', catalog, 0);
    await expect(storage.write('ns', catalog, 0)).rejects.toBeInstanceOf(WatchlistConflictError);
    await expect(storage.write('ns', { ...catalog, revision: 5 }, 1)).rejects.toThrow(/advance/);
    expect(await storage.read('ns')).toEqual(catalog);
    expect(await storage.read('other')).toBeNull();
  });
});
