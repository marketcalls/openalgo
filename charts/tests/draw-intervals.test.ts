/**
 * Visibility per interval: a drawing may carry the range of chart intervals it
 * is shown on (`Drawing.intervals`). Outside the range it is kept, saved and
 * undone like any other drawing, but it is not on the chart: no layer lists
 * it, so nothing paints it, a click passes through it, a box or an eraser
 * sweep does not reach it, the vector export leaves it out and the object
 * inventory marks it. The chart's interval is its data context's, and a
 * change applies the moment `data:context` announces it.
 *
 * Driven through a real chart and its pointer handlers where the behaviour is
 * the user's: the hit test is the chart's own, not a stand-in.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import {
  DrawingController, DrawingLayer, INTERVAL_FIELDS, composeSettings, readDrawingSettings, applyDrawingSettings,
  coerceSettingValue, drawingShownOnInterval, clearMemoryClipboard,
} from '../src/draw/index';
import { intervalLength, readIntervalRange } from '../src/draw/intervals';
import { registerInterval } from '../src/feed/intervals';
import { publishDataContext } from '../src/feed/data-variant';
import { DataLayer } from '../src/model/data-layer';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { Drawing, DrawingInput } from '../src/draw/types';

const cleanups: (() => void)[] = [];
afterEach(() => {
  cleanups.splice(0).reverse().forEach((fn) => fn());
  clearMemoryClipboard();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Fifteen minute bars on a seeded walk: enough structure that a line sits where a click can find it. */
const BARS = (() => {
  let price = 2140;
  let seed = 97;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 100 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 18;
    price = close;
    return { time: 1700000000 + i * 900, open, high: Math.max(open, close) + next() * 6, low: Math.min(open, close) - next() * 6, close };
  });
})();

function mount(context: { interval?: string; symbol?: string } | undefined = { symbol: 'INFY', interval: '15m' }) {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el as unknown as HTMLElement, { document: doc, raf: { schedule: () => 0 }, shortcuts: false, timeNavigator: false });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  chart.setVisibleLogicalRange({ from: 0, to: 100 });
  if (context !== undefined) chart.setDataContext(context);
  const draw = new DrawingController(chart);
  cleanups.push(() => draw.destroy(), () => chart.destroy());
  const mods = (k: { ctrl?: boolean }) => ({ ctrlKey: k.ctrl === true });
  const move = (x: number, y: number, pressed = false, k: { ctrl?: boolean } = {}) =>
    el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0, ...mods(k) }));
  const click = (x: number, y: number) => {
    move(x, y);
    el.dispatch('pointerdown', pointer('down', x, y));
    el.dispatch('pointerup', pointer('up', x, y));
  };
  const drag = (path: [number, number][], k: { ctrl?: boolean } = {}) => {
    move(path[0][0], path[0][1], false, k);
    el.dispatch('pointerdown', pointer('down', path[0][0], path[0][1], mods(k)));
    for (const p of path.slice(1)) move(p[0], p[1], true, k);
    const last = path[path.length - 1];
    el.dispatch('pointerup', pointer('up', last[0], last[1], mods(k)));
  };
  const at = (x: number, y: number) => ({ time: chart.coordinateToTime(x), price: chart.coordinateToPrice(y, 0) as number });
  /** A steep line through screen x, from y 150 to 450: a click at (x + 10, 300) lands on it. */
  const post = (x: number, extra: Partial<DrawingInput> = {}) =>
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [at(x, 150), at(x + 20, 450)], ...extra });
  const interval = (code: string) => chart.setDataContext({ symbol: 'INFY', interval: code });
  const layers = () => chart.panes()[0].primitives().filter((p): p is DrawingLayer => p instanceof DrawingLayer);
  return { chart, draw, el, move, click, drag, at, post, interval, layers };
}

type ListSpy = { mock: { calls: unknown[][]; contexts: unknown[] } };

/** The ids every drawing layer was last given, across all of them. */
function listedIds(spy: ListSpy): Set<string> {
  const last = new Map<unknown, readonly Drawing[]>();
  spy.mock.calls.forEach((call, i) => last.set(spy.mock.contexts[i], call[0] as readonly Drawing[]));
  return new Set([...last.values()].flatMap((list) => list.map((d) => d.id)));
}

const HOURLY_AND_BELOW = { from: '1m', to: '1h' };

describe('which intervals a range admits', () => {
  it('shows a drawing with no range on every interval, and on a chart that names none', () => {
    for (const code of ['1s', '1m', '1h', 'D', 'W', null, undefined, 'T500', 'nonsense']) {
      expect(drawingShownOnInterval({}, code)).toBe(true);
    }
  });

  it('includes both ends and compares by bar length, so 60m is 1h', () => {
    const d = { intervals: HOURLY_AND_BELOW };
    expect(['1m', '5m', '15m', '60m', '1h', '1H'].map((c) => drawingShownOnInterval(d, c))).toEqual([true, true, true, true, true, true]);
    expect(['30s', '2h', '4h', 'D', 'W'].map((c) => drawingShownOnInterval(d, c))).toEqual([false, false, false, false, false]);
  });

  it('reads the ends either way round, and an absent end as no limit on that side', () => {
    expect(drawingShownOnInterval({ intervals: { from: '1h', to: '1m' } }, '15m')).toBe(true);
    expect(drawingShownOnInterval({ intervals: { from: '1h', to: '1m' } }, 'D')).toBe(false);
    expect(drawingShownOnInterval({ intervals: { to: '1h' } }, '1s')).toBe(true);
    expect(drawingShownOnInterval({ intervals: { to: '1h' } }, 'D')).toBe(false);
    expect(drawingShownOnInterval({ intervals: { from: 'D' } }, 'W')).toBe(true);
    expect(drawingShownOnInterval({ intervals: { from: 'D' } }, '4h')).toBe(false);
  });

  it('hides nothing on a comparison it cannot make: an unknown or trade-driven end, or chart interval', () => {
    // An end nothing resolves limits nothing; the other end still does.
    expect(drawingShownOnInterval({ intervals: { from: 'nonsense', to: '1h' } }, '1s')).toBe(true);
    expect(drawingShownOnInterval({ intervals: { from: 'nonsense', to: '1h' } }, 'D')).toBe(false);
    const off = registerInterval({ code: 'T500', bucketing: { mode: 'ticks', count: 500 } });
    try {
      expect(drawingShownOnInterval({ intervals: HOURLY_AND_BELOW }, 'T500')).toBe(true);
      expect(drawingShownOnInterval({ intervals: { from: 'T500', to: '1h' } }, '1m')).toBe(true);
    } finally { off(); }
    expect(drawingShownOnInterval({ intervals: HOURLY_AND_BELOW }, 'unregistered')).toBe(true);
    expect(drawingShownOnInterval({ intervals: HOURLY_AND_BELOW }, null)).toBe(true);
  });

  it('places a calendar interval between the week and the next longer period', () => {
    const offs = [
      registerInterval({ code: '1mo', bucketing: { mode: 'calendar', unit: 'month' } }),
      registerInterval({ code: '1q', bucketing: { mode: 'calendar', unit: 'quarter' } }),
      registerInterval({ code: '6mo', bucketing: { mode: 'calendar', unit: 'month', count: 6 } }),
    ];
    try {
      expect(intervalLength('1mo')! > intervalLength('W')!).toBe(true);
      expect(intervalLength('1q')! > intervalLength('1mo')!).toBe(true);
      expect(intervalLength('6mo')! > intervalLength('1q')!).toBe(true);
      const d = { intervals: { from: 'W', to: '1mo' } };
      expect(['D', 'W', '1mo', '1q'].map((c) => drawingShownOnInterval(d, c))).toEqual([false, true, true, false]);
    } finally { offs.forEach((off) => off()); }
  });

  it('keeps a stored range only when it names a bound, and a bound only when it is a code', () => {
    expect(readIntervalRange(undefined)).toBeNull();
    expect(readIntervalRange('1m')).toBeNull();
    expect(readIntervalRange({})).toBeNull();
    expect(readIntervalRange({ from: '', to: '  ' })).toBeNull();
    expect(readIntervalRange({ from: ' 5m ', to: 60 })).toEqual({ from: '5m' });
    expect(readIntervalRange({ from: '1m', to: '1h', extra: true })).toEqual({ from: '1m', to: '1h' });
    expect(readIntervalRange({ to: 'x'.repeat(65) })).toBeNull();
  });
});

describe('on the chart', () => {
  it('leaves a drawing off every layer on an interval outside its range, and brings it back', () => {
    const { draw, post, interval } = mount();
    const spy = vi.spyOn(DrawingLayer.prototype, 'setDrawings');
    const shown = post(200);
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    expect(listedIds(spy)).toEqual(new Set([shown.id, ranged.id]));
    interval('D');
    expect(listedIds(spy)).toEqual(new Set([shown.id]));
    expect(draw.shownOnInterval(ranged.id)).toBe(false);
    expect(draw.shownOnInterval(shown.id)).toBe(true);
    expect(draw.get(ranged.id)).toBeDefined();
    expect(draw.toJSON().drawings.map((d) => d.id)).toEqual([shown.id, ranged.id]);
    interval('5m');
    expect(listedIds(spy)).toEqual(new Set([shown.id, ranged.id]));
    expect(draw.interval()).toBe('5m');
  });

  it('lets a click pass through a drawing the interval hides', () => {
    const { draw, post, click, interval } = mount();
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    click(410, 300);
    expect(draw.selection()).toEqual([ranged.id]);
    draw.select(null);
    interval('D');
    click(410, 300);
    expect(draw.selection()).toEqual([]);
    interval('1h');
    click(410, 300);
    expect(draw.selection()).toEqual([ranged.id]);
  });

  it('drops a drawing from the selection and the hover when the interval hides it', () => {
    const { chart, draw, post, move, interval } = mount();
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    const kept = post(200);
    const hover: unknown[] = [];
    chart.on('drawing:hover', (p) => hover.push(p));
    move(410, 300);
    expect(draw.hovered()).toBe(ranged.id);
    draw.select([ranged.id, kept.id]);
    interval('W');
    expect(draw.selection()).toEqual([kept.id]);
    expect(draw.hovered()).toBeNull();
    expect(hover[hover.length - 1]).toEqual({ id: null });
    // Picked on purpose (an objects panel row) it is selectable all the same,
    // so its settings can widen the range; it has no handles to show.
    draw.select(ranged.id);
    expect(draw.selection()).toEqual([ranged.id]);
  });

  it('waits out the context a data variant change passes through, as the chart\'s own listeners do', () => {
    const { chart, draw, post, interval } = mount();
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    interval('D');
    draw.select(ranged.id);                                   // picked on purpose, from an objects panel
    const objects = new ChartObjects(chart, { drawings: draw });
    cleanups.push(() => objects.destroy());
    const marks: (boolean | undefined)[] = [];
    objects.subscribe((rows) => marks.push(rows.find((r) => r.id === 'drawing:' + ranged.id)?.hiddenOnInterval));
    const spy = vi.spyOn(DrawingLayer.prototype, 'setDrawings');
    const seen: (string | null)[] = [];
    chart.on('data:context', () => seen.push(draw.interval()));
    // The chart takes a variant alone as a source change, so the helper sets
    // the context once; nothing passes through a context with the interval
    // cleared, and the drawings, the selection and the marks stay put.
    publishDataContext(chart, { symbol: 'INFY', interval: 'D', variant: { session: 'extended' } });
    expect(chart.getDataContext()?.variant).toEqual({ session: 'extended' });
    expect(seen).toEqual(['D']);
    expect(spy).not.toHaveBeenCalled();
    expect(draw.selection()).toEqual([ranged.id]);
    expect(draw.hiddenOnInterval()).toEqual([ranged.id]);
    expect(marks).toEqual([true]);
  });

  it('reads a blank interval as none, and lists what the interval hides in model order', () => {
    const { chart, draw, post, interval } = mount();
    const a = post(200, { intervals: { to: '1h' } });
    post(300);
    const c = post(400, { intervals: { from: '1m', to: '5m' } });
    interval('D');
    expect(draw.hiddenOnInterval()).toEqual([a.id, c.id]);
    interval('30m');
    expect(draw.hiddenOnInterval()).toEqual([c.id]);
    chart.setDataContext({ symbol: 'INFY', interval: '  ' });
    expect(draw.interval()).toBeNull();
    expect(draw.hiddenOnInterval()).toEqual([]);
  });

  it('lists the layers again only when the set of hidden drawings changes', () => {
    const { chart, post, interval } = mount();
    post(400, { intervals: HOURLY_AND_BELOW });
    const spy = vi.spyOn(DrawingLayer.prototype, 'setDrawings');
    chart.setDataContext({ symbol: 'TCS', interval: '15m' });
    interval('30m');
    expect(spy).not.toHaveBeenCalled();
    interval('D');
    expect(spy).toHaveBeenCalled();
    spy.mockClear();
    interval('W');
    expect(spy).not.toHaveBeenCalled();
  });

  it('keeps a hidden drawing out of a box select and an eraser sweep', () => {
    const { draw, post, drag, interval } = mount();
    const ranged = post(300, { intervals: HOURLY_AND_BELOW });
    const plain = post(400);
    interval('D');
    drag([[250, 250], [480, 350]], { ctrl: true });
    expect(draw.selection()).toEqual([plain.id]);
    draw.setEraser(true);
    drag([[250, 300], [480, 302]]);
    expect(draw.drawings().map((d) => d.id)).toEqual([ranged.id]);
  });

  it('never paints a hidden drawing over the chart during a drag of another', () => {
    const { draw, post, drag, interval, layers } = mount();
    const ranged = post(300, { intervals: HOURLY_AND_BELOW });
    const plain = post(500);
    interval('D');
    const top = layers().find((l) => l.zOrder() === 'top')!;
    const before = draw.get(plain.id)!.points[0].time;
    const seen = vi.spyOn(DrawingLayer.prototype, 'setDrawings');
    drag([[510, 300], [560, 320], [600, 340]]);
    expect(draw.get(plain.id)!.points[0].time).not.toBe(before);   // the drag moved it
    // Every frame of the drag lists the top layer again, and none lists the hidden one.
    const onTop = seen.mock.calls.filter((_, i) => seen.mock.contexts[i] === top).map((c) => (c[0] as Drawing[]).map((d) => d.id));
    expect(onTop.length).toBeGreaterThan(1);
    expect(onTop.every((ids) => ids.includes(plain.id) && !ids.includes(ranged.id))).toBe(true);
  });

  it('follows a host that emits data:context without a getDataContext to read', () => {
    const listeners = new Map<string, Set<(p: unknown) => void>>();
    const host = {
      on(event: string, cb: (p: unknown) => void) {
        const set = listeners.get(event) ?? new Set(); set.add(cb); listeners.set(event, set);
        return () => { set.delete(cb); };
      },
      emit(event: string, payload: unknown) { for (const cb of [...listeners.get(event) ?? []]) cb(payload); },
      addPrimitive() {}, removePrimitive() {},
      dataLayer: new DataLayer(),
      getVisibleLogicalRange: () => ({ from: 0, to: 2 }),
      drawingState: () => null, setDrawingState() {},
    };
    const draw = new DrawingController(host);
    cleanups.push(() => draw.destroy());
    const d = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }], intervals: { to: '1h' } });
    expect(draw.interval()).toBeNull();
    expect(draw.shownOnInterval(d.id)).toBe(true);
    host.emit('data:context', { symbol: 'X', interval: 'D' });
    expect(draw.interval()).toBe('D');
    expect(draw.shownOnInterval(d.id)).toBe(false);
    host.emit('data:context', undefined);
    expect(draw.interval()).toBeNull();
    expect(draw.shownOnInterval(d.id)).toBe(true);
  });

  it('leaves a hidden drawing out of the vector export', () => {
    vi.stubGlobal('window', {});
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div') as unknown as HTMLElement, {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    cleanups.push(() => chart.destroy());
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(BARS);
    chart.setDataContext({ symbol: 'INFY', interval: '15m' });
    const draw = new DrawingController(chart);
    draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#7a3cf0' }, intervals: HOURLY_AND_BELOW,
      points: [{ time: BARS[20].time, price: BARS[20].low }, { time: BARS[60].time, price: BARS[60].high }] });
    expect(chart.exportSVG()).toContain('#7a3cf0');
    chart.setDataContext({ symbol: 'INFY', interval: 'D' });
    expect(chart.exportSVG()).not.toContain('#7a3cf0');
    draw.destroy();
  });
});

describe('setting a range', () => {
  it('sets, replaces and clears a range through update, one undo step each', () => {
    const { draw, post, interval } = mount();
    const d = post(400);
    interval('D');
    expect(draw.update(d.id, { intervals: HOURLY_AND_BELOW })).toBe(true);
    expect(draw.get(d.id)!.intervals).toEqual(HOURLY_AND_BELOW);
    expect(draw.shownOnInterval(d.id)).toBe(false);
    draw.update(d.id, { intervals: { from: '4h' } });
    expect(draw.get(d.id)!.intervals).toEqual({ from: '4h' });
    expect(draw.shownOnInterval(d.id)).toBe(true);
    draw.update(d.id, { intervals: null });
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    draw.update(d.id, { intervals: HOURLY_AND_BELOW });
    draw.update(d.id, { intervals: {} });
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)!.intervals).toEqual(HOURLY_AND_BELOW);
    expect(draw.shownOnInterval(d.id)).toBe(false);
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.get(d.id)!.intervals).toEqual(HOURLY_AND_BELOW);
  });

  it('keeps its own copy of a range and drops a bound that is not a code', () => {
    const { draw, post } = mount();
    const range = { from: '1m', to: '1h' };
    const d = post(400, { intervals: range });
    range.to = 'D';
    expect(draw.get(d.id)!.intervals).toEqual({ from: '1m', to: '1h' });
    // Nor does a saved document share one with the model.
    draw.toJSON().drawings[0].intervals!.to = 'W';
    expect(draw.get(d.id)!.intervals).toEqual({ from: '1m', to: '1h' });
    draw.update(d.id, { intervals: { from: 5 as unknown as string, to: '1h' } });
    expect(draw.get(d.id)!.intervals).toEqual({ to: '1h' });
    const e = post(200, { intervals: {} });
    expect(e).not.toHaveProperty('intervals');
  });

  it('takes a range the host clears into history, so no undo or redo brings it back', () => {
    const { draw, post } = mount();
    const d = post(400);                                          // the user's first step
    draw.update(d.id, { intervals: HOURLY_AND_BELOW });           // and second
    draw.update(d.id, { intervals: null }, { force: true });      // the host's own act
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    // The second step set what the host has since cleared, so it now does
    // nothing and is gone; the first is left, and a full undo and redo of
    // the history puts the drawing back without the range.
    expect(draw.historySteps().undo).toHaveLength(1);
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.redo()).toBe(false);
    expect(draw.get(d.id)!.intervals).toBeUndefined();
  });

  it('holds a range the host sets on a read-only drawing until its policy changes', () => {
    const { draw, post } = mount();
    const d = post(400);
    draw.update(d.id, { policy: { editable: false } });
    expect(draw.update(d.id, { intervals: HOURLY_AND_BELOW })).toBe(false);   // not the user's to change
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    draw.update(d.id, { intervals: HOURLY_AND_BELOW }, { force: true });
    draw.update(d.id, { policy: { editable: true } });
    expect(draw.get(d.id)!.intervals).toEqual(HOURLY_AND_BELOW);
    expect(draw.undo()).toBe(false);
    expect(draw.get(d.id)!.intervals).toEqual(HOURLY_AND_BELOW);
  });

  it('carries a range with a duplicate and a copy, and never pastes one that would land hidden', async () => {
    const { draw, post, interval } = mount();
    const d = post(400, { intervals: HOURLY_AND_BELOW });
    const [dup] = draw.duplicate([d.id]);
    expect(dup.intervals).toEqual(HOURLY_AND_BELOW);
    expect(dup.intervals).not.toBe(d.intervals);
    draw.setOptions({ clipboard: null });
    expect(await draw.copy(d.id)).toBe(true);
    const [same] = await draw.paste();
    expect(same.intervals).toEqual(HOURLY_AND_BELOW);
    interval('D');
    const [elsewhere] = await draw.paste();
    expect(elsewhere.intervals).toBeUndefined();
    expect(draw.shownOnInterval(elsewhere.id)).toBe(true);
    expect(draw.selection()).toEqual([elsewhere.id]);
  });

  it('reads and writes the range through the settings schema', () => {
    const { draw, post } = mount();
    const d = post(400, { intervals: HOURLY_AND_BELOW });
    const schema = composeSettings([INTERVAL_FIELDS]);
    expect(INTERVAL_FIELDS.map((f) => [f.path, f.kind, f.group])).toEqual([
      ['intervals.from', 'interval', 'visibility'], ['intervals.to', 'interval', 'visibility'],
    ]);
    expect(readDrawingSettings(d, schema)).toEqual({ 'intervals.from': '1m', 'intervals.to': '1h' });
    const widened = applyDrawingSettings(d, { 'intervals.to': ' D ' }, schema);
    expect(widened).toEqual({ intervals: { from: '1m', to: 'D' } });
    draw.update(d.id, widened);
    expect(draw.get(d.id)!.intervals).toEqual({ from: '1m', to: 'D' });
    const cleared = applyDrawingSettings(draw.get(d.id)!, { 'intervals.from': '', 'intervals.to': '' }, schema);
    expect(cleared).toEqual({ intervals: {} });
    draw.update(d.id, cleared);
    expect(draw.get(d.id)!.intervals).toBeUndefined();
    expect(coerceSettingValue(INTERVAL_FIELDS[0], 42)).toBeUndefined();
    expect(coerceSettingValue(INTERVAL_FIELDS[0], '1h')).toBe('1h');
    // A tool declares no interval field: the host that lists intervals adds them.
    expect(applyDrawingSettings(d, { 'intervals.from': '5m' }, composeSettings([]))).toEqual({});
  });
});

describe('the object inventory', () => {
  it('lists a hidden drawing, marks it, withholds focus, and follows the interval', () => {
    const { chart, draw, post, interval } = mount();
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    const plain = post(200);
    const objects = new ChartObjects(chart, { drawings: draw });
    cleanups.push(() => objects.destroy());
    const seen: boolean[] = [];
    objects.subscribe((rows) => { const row = rows.find((r) => r.id === 'drawing:' + ranged.id); if (row) seen.push(row.hiddenOnInterval === true); });
    expect(objects.get('drawing:' + ranged.id)!.hiddenOnInterval).toBeUndefined();
    expect(objects.get('drawing:' + ranged.id)!.capabilities.focus).toBe(true);
    interval('D');
    const row = objects.get('drawing:' + ranged.id)!;
    expect(row.hiddenOnInterval).toBe(true);
    expect(row.visible).toBe(true);                  // the user's switch is untouched
    expect(row.capabilities.focus).toBe(false);
    expect(row.capabilities.select).toBe(true);
    expect(objects.get('drawing:' + plain.id)!.hiddenOnInterval).toBeUndefined();
    interval('1m');
    expect(objects.get('drawing:' + ranged.id)!.hiddenOnInterval).toBeUndefined();
    expect(seen).toEqual([false, true, false]);
  });

  it('tells a subscriber when the interval is the only thing that changed on a row', () => {
    const { chart, draw, post, interval } = mount();
    const ranged = post(400, { intervals: HOURLY_AND_BELOW });
    chart.primarySeries()!.setData([]);                  // no bars: no row offers focus either way
    const objects = new ChartObjects(chart, { drawings: draw });
    cleanups.push(() => objects.destroy());
    const seen: (boolean | undefined)[] = [];
    objects.subscribe((rows) => seen.push(rows.find((r) => r.id === 'drawing:' + ranged.id)?.hiddenOnInterval));
    interval('D');
    interval('5m');
    expect(seen).toEqual([undefined, true, undefined]);
  });

  it('asks a drawing source once per refresh for what the interval hides, not once per drawing', () => {
    const { chart } = mount();
    const at = (i: number) => ({ id: 'd' + i, tool: 'trend-line', paneIndex: 0, zIndex: 0, points: [{ time: BARS[i].time, price: BARS[i].close }] });
    const drawings = [at(10), at(20), at(30)];
    const hiddenOnInterval = vi.fn(() => ['d20']);
    const source = {
      drawings: () => drawings, get: (id: string) => drawings.find((d) => d.id === id),
      selection: () => [], select: () => {}, update: () => {}, remove: () => false, hiddenOnInterval,
    };
    const objects = new ChartObjects(chart, { drawings: source });
    cleanups.push(() => objects.destroy());
    expect(objects.list().filter((r) => r.kind === 'drawing').map((r) => [r.id, r.hiddenOnInterval === true, r.capabilities.focus]))
      .toEqual([['drawing:d10', false, true], ['drawing:d20', true, false], ['drawing:d30', false, true]]);
    hiddenOnInterval.mockClear();
    objects.refresh();
    expect(hiddenOnInterval).toHaveBeenCalledTimes(1);
  });

  it('marks a group only when the interval hides every drawing in it', () => {
    const { chart, draw, post, interval } = mount();
    const a = post(400, { intervals: HOURLY_AND_BELOW });
    const b = post(200);
    const group = draw.createGroup('Levels', [a.id, b.id])!;
    const objects = new ChartObjects(chart, { drawings: draw });
    cleanups.push(() => objects.destroy());
    interval('D');
    expect(objects.get('group:' + group.id)!.hiddenOnInterval).toBeUndefined();
    draw.update(b.id, { intervals: { to: '4h' } });
    expect(objects.get('group:' + group.id)!.hiddenOnInterval).toBe(true);
  });
});
