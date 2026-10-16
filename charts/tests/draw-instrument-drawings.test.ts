/**
 * Drawings per instrument: `InstrumentDrawings` keeps one drawing document per
 * instrument and swaps them as the chart's data context moves. Checked here
 * against a controller on a minimal chart host: the swap and the round trip,
 * migration of a document saved before there were instruments, a store that
 * fails, switches made in quick succession, a switch in the middle of a
 * placement or a drag, the undo history across a swap, the clipboard, drawings
 * pinned to the viewport, a drawing link group, and teardown.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DrawingController, DrawingLinkGroup, InstrumentDrawings, createInstrumentDrawings, instrumentDrawingsKey, memoryDrawingStore,
  migrateUnscopedDrawings, webStorageDrawingStore, clearMemoryClipboard,
  type DrawingDocumentStore, type DrawingInstrument, type DrawingsDocument, type InstrumentDrawingsError,
} from '../src/draw/index';
import { DataLayer } from '../src/model/data-layer';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Drawing, DrawingInput } from '../src/draw/types';

interface Context extends DrawingInstrument { interval?: string; variant?: { session?: string } }
interface Host { chart: DrawingChartHost & { getDataContext(): Context | undefined; setDataContext(c: Context | undefined): void }; draw: DrawingController }

const hosts: Host[] = [];
afterEach(() => {
  for (const h of hosts.splice(0)) if (!h.draw.isDestroyed) h.draw.destroy();
  clearMemoryClipboard();
  vi.restoreAllMocks();
});

/** A chart host with a data context, over three bars a minute apart. */
function host(context?: Context): Host {
  const listeners = new Map<string, Set<(p: unknown) => void>>();
  const dataLayer = new DataLayer();
  dataLayer.setSeriesData(dataLayer.createSeries(), [0, 1, 2].map(i => ({ time: 1000 + i * 60, open: 100, high: 110, low: 90, close: 105 })));
  let current = context;
  const chart: Host['chart'] = {
    on(event, cb) {
      const set = listeners.get(event) ?? new Set(); set.add(cb); listeners.set(event, set);
      return () => { set.delete(cb); };
    },
    emit(event, payload) { for (const cb of [...listeners.get(event) ?? []]) cb(payload); },
    addPrimitive() {}, removePrimitive() {},
    dataLayer, getVisibleLogicalRange: () => ({ from: 0, to: 2 }),
    drawingState: () => null, setDrawingState() {}, panes: () => [{}],
    plotRect: () => ({ left: 0, top: 0, width: 400, height: 200 }),
    getDataContext: () => current,
    setDataContext(next) { current = next; chart.emit('data:context', next); },
  };
  const h = { chart, draw: new DrawingController(chart) };
  hosts.push(h);
  return h;
}

const A: Context = { symbol: 'AAA', exchange: 'NSE', interval: '1m' };
const B: Context = { symbol: 'BBB', exchange: 'NSE', interval: '1m' };
const line = (price = 100, extra: Partial<DrawingInput> = {}): DrawingInput => ({
  tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1000, price }, { time: 1120, price: price + 10 }], ...extra,
});
const ids = (draw: DrawingController): string[] => draw.drawings().map(d => d.id);
const stored = (store: DrawingDocumentStore, key: string): DrawingsDocument | null => store.get(key) as DrawingsDocument | null;

/** A store that records what reaches it, and can be made to fail. */
function recording() {
  const inner = memoryDrawingStore();
  const log: string[] = [];
  const failing = { get: false, set: false, remove: false, refuse: false };
  const store: DrawingDocumentStore = {
    get: key => { log.push(`get ${key}`); if (failing.get) throw new Error('read failed'); return inner.get(key); },
    set: (key, document) => {
      log.push(`set ${key}`);
      if (failing.set) throw new Error('quota');
      if (failing.refuse) return false;
      return inner.set(key, document);
    },
    remove: key => { log.push(`remove ${key}`); if (failing.remove) throw new Error('remove failed'); inner.remove(key); },
  };
  return { store, inner, log, failing };
}

describe('instrument keys and stores', () => {
  it('keys an instrument by exchange and symbol, encoded, and names none without a symbol', () => {
    expect(instrumentDrawingsKey({ symbol: 'INFY', exchange: 'NSE' })).toBe('NSE:INFY');
    expect(instrumentDrawingsKey({ symbol: 'AAPL' })).toBe('AAPL');
    expect(instrumentDrawingsKey({ symbol: 'AAPL', exchange: '' })).toBe('AAPL');
    // A colon inside a part cannot make two instruments one key.
    expect(instrumentDrawingsKey({ symbol: 'B:C', exchange: 'A' })).not.toBe(instrumentDrawingsKey({ symbol: 'C', exchange: 'A:B' }));
    expect(instrumentDrawingsKey({ symbol: '  ', exchange: 'NSE' })).toBeNull();
    expect(instrumentDrawingsKey({ exchange: 'NSE' })).toBeNull();
    expect(instrumentDrawingsKey(undefined)).toBeNull();
    // Case is the host's: the helper does not decide two spellings are one instrument.
    expect(instrumentDrawingsKey({ symbol: 'infy', exchange: 'NSE' })).toBe('NSE:infy');
  });

  it('keeps copies in memory, so a caller never shares an object with the store', () => {
    const store = memoryDrawingStore();
    const document: DrawingsDocument = { version: 2, drawings: [] };
    store.set('k', document);
    document.drawings.push({} as Drawing);
    expect((store.get('k') as DrawingsDocument).drawings).toEqual([]);
    store.remove('k');
    expect(store.get('k')).toBeNull();
  });

  it('writes JSON under a prefix in a web storage the host hands over', () => {
    const data = new Map<string, string>();
    const web = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v); }, removeItem: (k: string) => { data.delete(k); } };
    const store = webStorageDrawingStore(web, 'app:drawings:');
    store.set('NSE:INFY', { version: 2, drawings: [] });
    expect([...data.keys()]).toEqual(['app:drawings:NSE:INFY']);
    expect(store.get('NSE:INFY')).toEqual({ version: 2, drawings: [] });
    store.remove('NSE:INFY');
    expect(data.size).toBe(0);
    data.set('app:drawings:bad', '{not json');
    expect(() => store.get('bad')).toThrow();
  });
});

describe('swapping documents with the instrument', () => {
  it('saves the outgoing instrument, shows the incoming one, and brings the first back', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    const scoped = new InstrumentDrawings(chart, draw, { store });
    expect(scoped.key()).toBe('NSE:AAA');
    const first = draw.add(line(100));
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual([first.id]);

    chart.setDataContext(B);
    expect(scoped.key()).toBe('NSE:BBB');
    expect(draw.drawings()).toEqual([]);
    const second = draw.add(line(120));
    // Deleting everything on B is B's business alone.
    draw.remove(second.id);
    expect(store.get('NSE:BBB')).toBeNull();

    chart.setDataContext(A);
    expect(ids(draw)).toEqual([first.id]);
    expect(draw.get(first.id)?.points).toEqual(line(100).points);
  });

  it('round-trips the whole document: groups, styles, text, z-order and drawings pinned to the viewport', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    const a = draw.add(line(100, { style: { color: '#123456', lineWidth: 3 }, zIndex: 4 }));
    const b = draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [{ time: 1060, price: 104 }], text: { value: 'breakout' } });
    const pinned = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.2 }] });
    draw.createGroup('Plan', [a.id, b.id]);
    const before = draw.toJSON();
    chart.setDataContext(B);
    // The note pinned to the screen was about A, and goes with A.
    expect(draw.drawings()).toEqual([]);
    expect(draw.groups()).toEqual([]);
    chart.setDataContext(A);
    expect(draw.toJSON()).toEqual(before);
    expect(draw.get(pinned.id)?.space).toBe('viewport');
  });

  it('leaves the drawings alone for an interval, a data variant, or a context that names no instrument', () => {
    const { chart, draw } = host(A);
    const { store, log } = recording();
    new InstrumentDrawings(chart, draw, { store });
    const made = draw.add(line());
    log.length = 0;
    chart.setDataContext({ ...A, interval: '5m' });
    chart.setDataContext({ ...A, interval: '5m', variant: { session: 'extended' } });
    chart.setDataContext(undefined);
    chart.setDataContext({ interval: '5m' });
    expect(ids(draw)).toEqual([made.id]);
    expect(log).toEqual([]);
    // A drawing made while nothing was named is still A's.
    const more = draw.add(line(130));
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual([made.id, more.id]);
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([made.id, more.id]);
  });

  it('keeps transient drawings out of the saved document, as every save does', () => {
    const { chart, draw } = host(A);
    const { store, log } = recording();
    new InstrumentDrawings(chart, draw, { store });
    draw.add(line());
    log.length = 0;
    const mark = draw.add(line(140, { policy: { persistent: false, editable: false } }));
    // A stream of updates to a transient drawing writes nothing.
    for (let i = 0; i < 5; i++) draw.update(mark.id, { points: [{ time: 1000, price: 140 + i }, { time: 1120, price: 150 }] }, { force: true });
    expect(log).toEqual([]);
    chart.setDataContext(B);
    chart.setDataContext(A);
    expect(draw.get(mark.id)).toBeUndefined();
  });

  it('follows a custom key, here one set of drawings per data variant too', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store,
      key: c => `${instrumentDrawingsKey(c)}|${(c as Context).variant?.session ?? 'regular'}` });
    const regular = draw.add(line());
    chart.setDataContext({ ...A, variant: { session: 'extended' } });
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([regular.id]);
    expect(Object.keys(Object.fromEntries(['NSE:AAA|regular', 'NSE:AAA|extended'].map(k => [k, store.get(k)])))).toHaveLength(2);
  });

  it('moves on an explicit instrument, ahead of the data context', () => {
    const { chart, draw } = host(A);
    const scoped = createInstrumentDrawings(chart, draw);
    const made = draw.add(line());
    scoped.setInstrument(B);
    expect(draw.drawings()).toEqual([]);
    // The context catching up to the same instrument changes nothing.
    const onB = draw.add(line(120));
    chart.setDataContext(B);
    expect(ids(draw)).toEqual([onB.id]);
    scoped.setInstrument(null);
    scoped.setInstrument({ exchange: 'NSE' });
    expect(ids(draw)).toEqual([onB.id]);
    scoped.setInstrument(A);
    expect(ids(draw)).toEqual([made.id]);
  });

  it('reads and replaces another instrument document without showing it', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    const scoped = new InstrumentDrawings(chart, draw, { store });
    const made = draw.add(line());
    expect(scoped.document(A)?.drawings.map(d => d.id)).toEqual([made.id]);
    expect(scoped.document(B)).toBeNull();
    scoped.setDocument(B, { version: 2, drawings: [{ ...line(90), id: 'from-layout', zIndex: 0 }] });
    expect(ids(draw)).toEqual([made.id]);
    expect(scoped.document(B)?.drawings.map(d => d.id)).toEqual(['from-layout']);
    chart.setDataContext(B);
    expect(ids(draw)).toEqual(['from-layout']);
    // On the current instrument it is the controller's own restore.
    scoped.setDocument(B, []);
    expect(draw.drawings()).toEqual([]);
    expect(store.get('NSE:BBB')).toBeNull();
    const copy = scoped.document(A)!;
    copy.drawings.length = 0;
    expect(scoped.document(A)?.drawings).toHaveLength(1);
  });

  it('writes a document the host loads itself (a layout) as the current instrument', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    draw.fromJSON([{ ...line(), id: 'restored', zIndex: 0 }]);
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual(['restored']);
  });
});

describe('starting, and migrating documents saved before drawings were per instrument', () => {
  it('attaches the drawings a chart already holds to its instrument when the store has none for it', () => {
    const { chart, draw } = host(A);
    const legacy = draw.add(line());
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual([legacy.id]);
    chart.setDataContext(B);
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([legacy.id]);
  });

  it('attaches them to the first instrument named when the chart named none at the start', () => {
    const { chart, draw } = host();
    const legacy = draw.add(line());
    const store = memoryDrawingStore();
    const scoped = new InstrumentDrawings(chart, draw, { store });
    expect(scoped.key()).toBeNull();
    draw.add(line(120));
    expect(store.get('NSE:AAA')).toBeNull();
    chart.setDataContext(A);
    expect(stored(store, 'NSE:AAA')?.drawings).toHaveLength(2);
    expect(ids(draw)[0]).toBe(legacy.id);
  });

  it('loads what the store holds over the chart drawings by default, and keeps the chart ones with prefer live', () => {
    const store = memoryDrawingStore();
    store.set('NSE:AAA', { version: 2, drawings: [{ ...line(90), id: 'kept', zIndex: 0 }] });
    const first = host(A);
    first.draw.add(line(100, { id: 'stale' }));
    new InstrumentDrawings(first.chart, first.draw, { store });
    expect(ids(first.draw)).toEqual(['kept']);

    const second = host(A);
    second.draw.add(line(100, { id: 'loaded' }));
    new InstrumentDrawings(second.chart, second.draw, { store, prefer: 'live' });
    expect(ids(second.draw)).toEqual(['loaded']);
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual(['loaded']);

    // Live even when empty: a layout with no drawings on it clears the instrument.
    const third = host(A);
    new InstrumentDrawings(third.chart, third.draw, { store, prefer: 'live' });
    expect(store.get('NSE:AAA')).toBeNull();
  });

  it('migrateUnscopedDrawings writes a pane-wide document to its instrument once, and never over one it has', () => {
    const store = memoryDrawingStore();
    // A 1.9 save is a bare array; it is upgraded on the way in.
    const legacy = [{ id: 'old', tool: 'trend-line', paneIndex: 0, points: line().points, style: {} }];
    expect(migrateUnscopedDrawings(store, 'NSE:AAA', legacy)).toBe(true);
    expect(stored(store, 'NSE:AAA')).toMatchObject({ version: 2, drawings: [{ id: 'old' }] });
    expect(migrateUnscopedDrawings(store, 'NSE:AAA', [{ ...legacy[0], id: 'newer' }])).toBe(false);
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual(['old']);
    expect(migrateUnscopedDrawings(store, 'NSE:BBB', { version: 2, drawings: [] })).toBe(false);
    expect(migrateUnscopedDrawings(store, null, legacy)).toBe(false);
    expect(store.get('NSE:BBB')).toBeNull();
    // A store that cannot say what it holds is not written over.
    const broken = recording();
    broken.failing.get = true;
    expect(migrateUnscopedDrawings(broken.store, 'NSE:AAA', legacy)).toBe(false);
    expect(broken.log).toEqual(['get NSE:AAA']);
    const refusing = recording();
    refusing.failing.refuse = true;
    expect(migrateUnscopedDrawings(refusing.store, 'NSE:AAA', legacy)).toBe(false);
  });
});

describe('a store that fails', () => {
  it('reports a refused write, keeps the document for the session, and writes it once the store takes it', () => {
    const { chart, draw } = host(A);
    const { store, inner, failing } = recording();
    const errors: InstrumentDrawingsError[] = [];
    const scoped = new InstrumentDrawings(chart, draw, { store, onError: e => errors.push(e) });
    failing.set = true;
    const made = draw.add(line());
    expect(errors.map(e => [e.operation, e.key])).toEqual([['write', 'NSE:AAA']]);
    chart.setDataContext(B);
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([made.id]);
    expect(scoped.save()).toBe(false);
    failing.set = false;
    expect(scoped.save()).toBe(true);
    expect((inner.get('NSE:AAA') as DrawingsDocument).drawings.map(d => d.id)).toEqual([made.id]);
  });

  it('treats a refused write (false) and a failed removal the same way', () => {
    const { chart, draw } = host(A);
    const { store, inner, failing } = recording();
    const errors: InstrumentDrawingsError[] = [];
    new InstrumentDrawings(chart, draw, { store, onError: e => errors.push(e) });
    const made = draw.add(line());
    failing.refuse = true;
    draw.update(made.id, { style: { color: '#654321' } });
    failing.remove = true;
    draw.remove(made.id);
    expect(errors.map(e => e.operation)).toEqual(['write', 'remove']);
    // The session still knows A has nothing, whatever the store says.
    chart.setDataContext(B);
    chart.setDataContext(A);
    expect(draw.drawings()).toEqual([]);
    expect((inner.get('NSE:AAA') as DrawingsDocument).drawings).toHaveLength(1);
  });

  it('shows no drawings for an instrument the store cannot read, and says so', () => {
    const { chart, draw } = host(A);
    const { store, failing } = recording();
    const errors: InstrumentDrawingsError[] = [];
    new InstrumentDrawings(chart, draw, { store, onError: e => { errors.push(e); throw new Error('a host listener that throws'); } });
    draw.add(line());
    failing.get = true;
    chart.setDataContext(B);
    expect(draw.drawings()).toEqual([]);
    expect(errors.map(e => [e.operation, e.key])).toEqual([['read', 'NSE:BBB']]);
  });

  it('shows nothing for an entry that is not a drawing document', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    store.set('NSE:BBB', { nonsense: true } as unknown as DrawingsDocument);
    new InstrumentDrawings(chart, draw, { store });
    chart.setDataContext(B);
    expect(draw.drawings()).toEqual([]);
  });
});

describe('switches at awkward moments', () => {
  it('ends with each instrument holding its own drawings after quick switches back and forth', () => {
    const { chart, draw } = host(A);
    const { store, log } = recording();
    new InstrumentDrawings(chart, draw, { store });
    const onA = draw.add(line());
    for (const context of [B, A, B, A, B]) chart.setDataContext(context);
    expect(draw.drawings()).toEqual([]);
    const onB = draw.add(line(130));
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([onA.id]);
    chart.setDataContext(B);
    expect(ids(draw)).toEqual([onB.id]);
    // Nothing changed on A during the switches, so it was written once.
    expect(log.filter(entry => entry === 'set NSE:AAA')).toHaveLength(1);
  });

  it('drops a shape half placed on the outgoing instrument and keeps the tool armed', () => {
    const { chart, draw } = host(A);
    new InstrumentDrawings(chart, draw);
    const click = (time: number, price: number) => chart.emit('click', { id: null, time, price, paneIndex: 0, point: { x: 0, y: 0 } });
    draw.setTool('trend-line');
    click(1000, 100);
    chart.setDataContext(B);
    expect(draw.activeTool()).toBe('trend-line');
    click(1060, 104);
    // The first click on B is B's first anchor, not the end of A's line.
    expect(draw.drawings()).toEqual([]);
    click(1120, 108);
    expect(draw.drawings().map(d => d.points)).toEqual([[{ time: 1060, price: 104 }, { time: 1120, price: 108 }]]);
    chart.setDataContext(A);
    expect(draw.drawings()).toEqual([]);
  });

  it('puts a drag in progress back before saving, and the drag goes no further', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    const made = draw.add(line());
    chart.emit('drag', { id: `draw:${made.id}`, fromTime: 1000, fromPrice: 100, time: 1060, price: 150, paneIndex: 0 });
    expect(draw.get(made.id)?.points[0].price).toBe(150);
    chart.setDataContext(B);
    expect(stored(store, 'NSE:AAA')?.drawings[0].points).toEqual(line().points);
    chart.emit('drag', { id: `draw:${made.id}`, fromTime: 1000, fromPrice: 100, time: 1060, price: 170, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext(A);
    expect(draw.get(made.id)?.points).toEqual(line().points);
  });

  it('records no undo step for a swap, and no undo on one instrument reaches the other', () => {
    const { chart, draw } = host(A);
    new InstrumentDrawings(chart, draw);
    const made = draw.add(line());
    expect(draw.canUndo()).toBe(true);
    chart.setDataContext(B);
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    const onB = draw.add(line(130));
    draw.undo();
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext(A);
    expect(ids(draw)).toEqual([made.id]);
    chart.setDataContext(B);
    expect(draw.get(onB.id)).toBeUndefined();
  });

  it('lets a copy made on one instrument be pasted on another, as the user asked', async () => {
    const { chart, draw } = host(A);
    draw.setOptions({ clipboard: null });
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    const made = draw.add(line());
    expect(await draw.copy(made.id)).toBe(true);
    chart.setDataContext(B);
    const pasted = await draw.paste();
    expect(pasted).toHaveLength(1);
    expect(stored(store, 'NSE:BBB')?.drawings.map(d => d.id)).toEqual([pasted[0].id]);
    expect(stored(store, 'NSE:AAA')?.drawings.map(d => d.id)).toEqual([made.id]);
  });
});

describe('a drawing link group across a swap', () => {
  it('never shares one instrument drawings as another instrument', () => {
    const one = host(A), two = host(B);
    const group = new DrawingLinkGroup({ enabled: true });
    new InstrumentDrawings(one.chart, one.draw);
    new InstrumentDrawings(two.chart, two.draw);
    group.add(one.chart, one.draw);
    group.add(two.chart, two.draw);
    const onA = one.draw.add(line());
    expect(two.draw.drawings()).toEqual([]);
    const shared = two.draw.add(line(130));
    // Chart one moves to B: A's line stays A's, and it sees B's shared line
    // only once it draws or restores one of its own, as any member does.
    one.chart.setDataContext(B);
    expect(two.draw.drawings().map(d => d.id)).toEqual([shared.id]);
    expect(one.draw.get(onA.id)).toBeUndefined();
    const mine = one.draw.add(line(150));
    expect(two.draw.drawings().map(d => d.points[0].price)).toEqual([130, 150]);
    one.chart.setDataContext(A);
    expect(ids(one.draw)).toEqual([onA.id]);
    expect(two.draw.drawings().map(d => d.points[0].price)).toEqual([130, 150]);
    // Back on B the chart reconnects its own shared copies by their lineage.
    one.chart.setDataContext(B);
    expect(one.draw.drawings().map(d => d.id)).toEqual([mine.id]);
    one.draw.update(mine.id, { style: { color: '#00ff00' } });
    expect(two.draw.drawings().find(d => d.points[0].price === 150)?.style.color).toBe('#00ff00');
    group.destroy();
  });
});

describe('teardown', () => {
  it('stops following once destroyed, and when its controller goes', () => {
    const { chart, draw } = host(A);
    const { store, log } = recording();
    const scoped = new InstrumentDrawings(chart, draw, { store });
    const made = draw.add(line());
    scoped.destroy();
    scoped.destroy();
    expect(scoped.isDestroyed).toBe(true);
    log.length = 0;
    chart.setDataContext(B);
    draw.add(line(130));
    expect(ids(draw)[0]).toBe(made.id);
    expect(log).toEqual([]);
    expect(scoped.save()).toBe(true);
    scoped.setInstrument(A);
    scoped.setDocument(A, []);
    expect(draw.drawings()).toHaveLength(2);

    const other = host(A);
    const second = new InstrumentDrawings(other.chart, other.draw);
    other.draw.destroy();
    expect(second.isDestroyed).toBe(true);
    const late = new InstrumentDrawings(other.chart, other.draw);
    expect(late.isDestroyed).toBe(true);
    expect(late.key()).toBeNull();
  });
});

describe('document versions and interval ranges', () => {
  /** A document as 2.5.8 stored it: version 2, no interval range. */
  const v2 = (): DrawingsDocument => ({
    version: 2,
    drawings: [{ id: 'kept', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: { color: '#089981' },
      points: [{ time: 1000, price: 101.5 }, { time: 1120, price: 108.25 }] }],
  });

  it('loads a stored version 2 document unchanged and writes nothing until something changes', () => {
    const { chart, draw } = host(B);
    const { store, inner, log } = recording();
    inner.set('NSE:AAA', v2());
    new InstrumentDrawings(chart, draw, { store });
    log.length = 0;
    chart.setDataContext(A);
    expect(draw.toJSON()).toEqual(v2());
    // Going to an instrument with nothing stored leaves no write behind for it either.
    chart.setDataContext(B);
    chart.setDataContext(A);
    expect(log.filter(entry => !entry.startsWith('get '))).toEqual([]);
    expect(stored(inner, 'NSE:AAA')).toEqual(v2());
  });

  it('writes a stored version 2 document as version 3 once a drawing in it has a range, and as 2 once none has', () => {
    const { chart, draw } = host(B);
    const store = memoryDrawingStore();
    store.set('NSE:AAA', v2());
    new InstrumentDrawings(chart, draw, { store });
    chart.setDataContext(A);
    draw.update('kept', { intervals: { from: '1m', to: '1h' } });
    expect(stored(store, 'NSE:AAA')?.version).toBe(3);
    expect(stored(store, 'NSE:AAA')?.drawings[0].intervals).toEqual({ from: '1m', to: '1h' });
    draw.update('kept', { intervals: null });
    expect(stored(store, 'NSE:AAA')).toEqual(v2());
  });

  it('round-trips a version 3 document through a swap, and shows it by the interval of each instrument', () => {
    const { chart, draw } = host(A);
    const store = memoryDrawingStore();
    new InstrumentDrawings(chart, draw, { store });
    const ranged = draw.add(line(100, { intervals: { to: '5m' } }));
    const written = stored(store, 'NSE:AAA');
    expect(written?.version).toBe(3);
    chart.setDataContext({ ...B, interval: 'D' });
    expect(draw.drawings()).toEqual([]);
    chart.setDataContext({ ...A, interval: 'D' });
    expect(draw.toJSON()).toEqual(written);
    expect(draw.shownOnInterval(ranged.id)).toBe(false);
    chart.setDataContext(A);
    expect(draw.shownOnInterval(ranged.id)).toBe(true);
  });

  it('writes nothing when only the interval changes, whatever it hides', () => {
    const { chart, draw } = host(A);
    const { store, log } = recording();
    new InstrumentDrawings(chart, draw, { store });
    const ranged = draw.add(line(100, { intervals: { to: '5m' } }));
    log.length = 0;
    chart.setDataContext({ ...A, interval: 'D' });
    expect(draw.shownOnInterval(ranged.id)).toBe(false);
    chart.setDataContext(A);
    expect(log).toEqual([]);
  });
});
