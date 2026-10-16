/**
 * The drawings channel. The base group decides who shares drawings with whom
 * (the members of the group, while the channel is on); the draw tier's
 * `DrawingLinkGroup` decides which drawings cross. The first block proves the
 * membership half against stub adapters, the second runs the whole path on
 * real charts with drawings kept per instrument, which is how a grid holds them.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { createLinkGroup, type LinkChart, type LinkDrawingsAdapter } from '../src/link/index';
import { DrawingController, InstrumentDrawings, createDrawingLinkGroup, memoryDrawingStore } from '../src/draw/index';
import type { DrawingLinkGroup } from '../src/draw/drawing-link';
import type { Drawing } from '../src/draw/types';
import { DataLayer } from '../src/model/data-layer';
import type { Bar } from '../src/model/bar';
import type { IPrimitive } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';

class MemberChart implements LinkChart {
  readonly dataLayer = new DataLayer();
  readonly listeners = new Map<string, Set<(payload: unknown) => void>>();
  isDestroyed = false;
  on(event: string, cb: (payload: unknown) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(cb);
    return () => { this.listeners.get(event)?.delete(cb); };
  }
  emit(event: string, payload: unknown) {
    for (const cb of [...(this.listeners.get(event) ?? [])]) cb(payload);
  }
  panes() { return this.isDestroyed ? [] : [{}]; }
  getVisibleLogicalRange() { return { from: 0, to: 10 }; }
  setVisibleLogicalRange() {}
  addPrimitive(_primitive: IPrimitive) {}
  removePrimitive(_primitive: IPrimitive) {}
}

/** An adapter that records what the group asked of it, in order. */
function recorder(log: string[], name: string): LinkDrawingsAdapter {
  return { join: () => { log.push(`${name}:join`); }, leave: () => { log.push(`${name}:leave`); } };
}

describe('drawings channel membership', () => {
  it('is off by default and joins or leaves every member as the switch moves', () => {
    const log: string[] = [];
    const group = createLinkGroup();
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    group.add(a, { drawings: recorder(log, 'a') });
    group.add(b, { drawings: recorder(log, 'b') });
    group.add(c); // no adapter: it never shares drawings
    expect(group.options().drawings).toBe(false);
    expect(log).toEqual([]);
    group.setOptions({ drawings: true });
    expect(log).toEqual(['a:join', 'b:join']);
    group.setOptions({ drawings: true, crosshair: false });
    expect(log).toEqual(['a:join', 'b:join']);
    group.setOptions({ drawings: false });
    expect(log).toEqual(['a:join', 'b:join', 'a:leave', 'b:leave']);
  });

  it('joins a member added while the channel is on and leaves when it is removed', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart(); const b = new MemberChart();
    group.add(a, { drawings: recorder(log, 'a') });
    group.add(b, { drawings: recorder(log, 'b') });
    group.remove(b);
    group.remove(b);
    expect(log).toEqual(['a:join', 'b:join', 'b:leave']);
    group.destroy();
    expect(log).toEqual(['a:join', 'b:join', 'b:leave', 'a:leave']);
    group.setOptions({ drawings: false });
    expect(log).toHaveLength(4);
  });

  it('swaps an adapter in place: the old one leaves before the new one joins', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart();
    group.add(a, { drawings: recorder(log, 'first') });
    group.add(a, { symbol: 'INFY' });
    expect(log).toEqual(['first:join']);
    group.add(a, { drawings: recorder(log, 'second') });
    expect(log).toEqual(['first:join', 'first:leave', 'second:join']);
    group.setOptions({ drawings: false });
    expect(log).toEqual(['first:join', 'first:leave', 'second:join', 'second:leave']);
  });

  it('lets a destroyed chart leave without the group touching it again', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart(); const b = new MemberChart();
    group.add(a, { drawings: recorder(log, 'a') });
    group.add(b, { drawings: recorder(log, 'b') });
    b.isDestroyed = true;
    b.emit('destroy', undefined);
    expect(group.members()).toEqual([a]);
    expect(log).toEqual(['a:join', 'b:join', 'b:leave']);
    group.setOptions({ drawings: false });
    expect(log).toEqual(['a:join', 'b:join', 'b:leave', 'a:leave']);
  });

  it('treats a drawings option spread in as undefined as off, and never leaves before joining', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: undefined });
    const a = new MemberChart();
    group.add(a, { drawings: recorder(log, 'a') });
    group.add(a, { symbol: 'INFY' });
    group.setOptions({ drawings: undefined });
    group.remove(a);
    expect(log).toEqual([]);
  });

  it('never joins a member twice when an adapter calls back into the group', () => {
    const log: string[] = [];
    const group = createLinkGroup();
    const a = new MemberChart();
    group.add(a, { drawings: {
      join: () => { log.push('join'); group.setOptions({ drawings: true }); },
      leave: () => { log.push('leave'); group.remove(a); },
    } });
    group.setOptions({ drawings: true });
    group.setOptions({ drawings: false });
    expect(log).toEqual(['join', 'leave']);
    expect(group.has(a)).toBe(false);
  });

  /** An adapter whose `leave` takes its own chart out of the group again, as a host tidying up might. */
  const selfRemoving = (log: string[], group: ReturnType<typeof createLinkGroup>, chart: MemberChart): LinkDrawingsAdapter => ({
    join: () => { log.push('a:join'); },
    leave: () => { log.push('a:leave'); group.remove(chart); },
  });

  it('keeps the other members when a leaving adapter removes its chart again', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    group.add(a, { drawings: selfRemoving(log, group, a) });
    group.add(b, { drawings: recorder(log, 'b') });
    group.add(c, { drawings: recorder(log, 'c') });
    group.remove(a);
    expect(group.members()).toEqual([b, c]);
    expect(log).toEqual(['a:join', 'b:join', 'c:join', 'a:leave']);
  });

  it('lets every member leave on destroy when an adapter calls back into the group', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    group.add(a, { drawings: selfRemoving(log, group, a) });
    group.add(b, { drawings: recorder(log, 'b') });
    group.add(c, { drawings: recorder(log, 'c') });
    group.destroy();
    expect(log).toEqual(['a:join', 'b:join', 'c:join', 'a:leave', 'b:leave', 'c:leave']);
    expect(group.members()).toEqual([]);
  });

  it('never joins a member that a host callback took out, destroyed or unlinked meanwhile', () => {
    for (const spoil of ['remove', 'destroy chart', 'destroy group'] as const) {
      const log: string[] = [];
      const group = createLinkGroup();
      const a = new MemberChart(); const b = new MemberChart();
      group.add(a, { drawings: { join: () => {
        log.push('a:join');
        if (spoil === 'remove') group.remove(b);
        else if (spoil === 'destroy chart') b.isDestroyed = true;
        else group.destroy();
      }, leave: () => { log.push('a:leave'); } } });
      group.add(b, { drawings: recorder(log, 'b') });
      group.setOptions({ drawings: true });
      // B was never joined, so nothing is left for it to leave, and the sharer never holds it.
      group.destroy();
      expect(log, spoil).toEqual(['a:join', 'a:leave']);
    }
  });

  it('drops a destroyed chart even when its leaving adapter removes another member', () => {
    const log: string[] = [];
    const group = createLinkGroup({ drawings: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    group.add(a, { drawings: recorder(log, 'a') });
    group.add(b, { drawings: recorder(log, 'b') });
    // A host tidying up the cell of a destroyed chart takes the chart beside it out too.
    group.add(c, { drawings: { join: () => { log.push('c:join'); }, leave: () => { log.push('c:leave'); group.remove(a); } } });
    c.isDestroyed = true;
    expect(() => c.emit('destroy', undefined)).not.toThrow();
    expect(group.members()).toEqual([b]);
    expect(log).toEqual(['a:join', 'b:join', 'c:join', 'c:leave', 'a:leave']);
  });
});

describe('drawings channel on real charts, drawings kept per instrument', () => {
  const live: Array<() => void> = [];
  afterEach(() => { for (const off of live.splice(0)) off(); });

  /** A seeded random walk, one five-minute bar after another, like a real session. */
  function walk(seed: number, count: number, start: number): Bar[] {
    let s = seed, close = start;
    const rand = (): number => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
    return Array.from({ length: count }, (_, i) => {
      const open = close;
      close = Math.round(open * (1 + (rand() - 0.5) * 0.012) * 100) / 100;
      return { time: 1758771900 + i * 300, open, close,
        high: Math.round(Math.max(open, close) * (1 + rand() * 0.004) * 100) / 100,
        low: Math.round(Math.min(open, close) * (1 - rand() * 0.004) * 100) / 100 };
    });
  }

  const PRICES: Record<string, number> = { INFY: 1512, TCS: 3040, SBIN: 812 };

  /**
   * One chart as a grid cell holds it: its own drawing controller, its own
   * store of drawings per instrument, and a host that loads an instrument by
   * replacing the bars and naming it in the data context.
   */
  function cell(symbol: string, seed: number) {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    const draw = new DrawingController(chart);
    const scoped = new InstrumentDrawings(chart, draw, { store: memoryDrawingStore() });
    const load = (next: string): void => {
      series.setData(walk(seed, 150, PRICES[next]));
      chart.setDataContext({ symbol: next, exchange: 'NSE', interval: '5m' });
    };
    load(symbol);
    live.push(() => chart.destroy());
    return { chart, draw, scoped, load, bars: () => series.getData() as Bar[] };
  }
  type Cell = ReturnType<typeof cell>;

  /** A trend line from the lowest low to the highest high of what the chart shows. */
  function trend(c: Cell): Drawing {
    const bars = c.bars();
    const low = bars.reduce((a, b) => (b.low < a.low ? b : a));
    const high = bars.reduce((a, b) => (b.high > a.high ? b : a));
    return c.draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: low.time, price: low.low }, { time: high.time, price: high.high }] });
  }

  function link(cells: Cell[], options: { symbol?: boolean; drawings?: boolean }) {
    const sharing: DrawingLinkGroup = createDrawingLinkGroup({ enabled: true });
    const group = createLinkGroup({ crosshair: false, viewport: false, ...options });
    for (const c of cells) {
      group.add(c.chart, {
        symbol: c.chart.getDataContext()?.symbol,
        onSymbol: next => c.load(next),
        drawings: { join: () => sharing.add(c.chart, c.draw), leave: () => sharing.remove(c.chart) },
      });
    }
    live.push(() => { group.destroy(); sharing.destroy(); });
    return { group, sharing };
  }

  /** The host changing one chart's instrument: it loads, then tells the group. */
  const choose = (group: ReturnType<typeof link>['group'], c: Cell, symbol: string): void => {
    c.load(symbol);
    group.setSymbol(c.chart, symbol);
  };
  const lines = (c: Cell) => c.draw.drawings().map(d => d.points);

  it('shares a drawing between charts on one instrument while the channel is on', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group } = link([a, b], { drawings: true });
    const made = trend(a);
    expect(lines(b)).toEqual([made.points]);
    const [copy] = b.draw.drawings();
    b.draw.update(copy.id, { style: { color: '#e0a100' } });
    expect(a.draw.get(made.id)?.style.color).toBe('#e0a100');
    group.setOptions({ drawings: false });
    trend(a);
    expect(b.draw.drawings()).toHaveLength(1);
    // Switching it on again shares what is drawn from then on, not what was drawn while it was off.
    group.setOptions({ drawings: true });
    expect(b.draw.drawings()).toHaveLength(1);
    trend(a);
    expect(b.draw.drawings()).toHaveLength(2);
  });

  it('shares nothing between charts on different instruments', () => {
    const a = cell('INFY', 3); const b = cell('TCS', 5);
    link([a, b], { drawings: true });
    trend(a);
    trend(b);
    expect(a.draw.drawings()).toHaveLength(1);
    expect(b.draw.drawings()).toHaveLength(1);
    expect(a.draw.drawings()[0].points[0].price).toBeLessThan(2000);
    expect(b.draw.drawings()[0].points[0].price).toBeGreaterThan(2000);
  });

  it('moves with the instrument under symbol linking and brings shared drawings back with it', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group } = link([a, b], { symbol: true, drawings: true });
    const infy = trend(a);
    expect(lines(b)).toEqual([infy.points]);
    choose(group, a, 'TCS');
    expect(b.chart.getDataContext()?.symbol).toBe('TCS');
    // Each chart shows the incoming instrument's drawings: none yet.
    expect(a.draw.drawings()).toEqual([]);
    expect(b.draw.drawings()).toEqual([]);
    const tcs = trend(b);
    expect(lines(a)).toEqual([tcs.points]);
    choose(group, b, 'INFY');
    expect(lines(a)).toEqual([infy.points]);
    expect(lines(b)).toEqual([infy.points]);
    // Still one drawing in two places: an edit on either reaches the other.
    const moved = infy.points.map(p => ({ ...p, price: Math.round(p.price * 1.01 * 100) / 100 }));
    b.draw.update(b.draw.drawings()[0].id, { points: moved });
    expect(lines(a)).toEqual([moved]);
    // The TCS line stayed with TCS on both charts.
    expect(a.scoped.document({ symbol: 'TCS', exchange: 'NSE' })?.drawings.map(d => d.points)).toEqual([tcs.points]);
    expect(b.scoped.document({ symbol: 'TCS', exchange: 'NSE' })?.drawings.map(d => d.points)).toEqual([tcs.points]);
  });

  it('keeps the copies a chart holds when it leaves the group, and sends it nothing after', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group } = link([a, b], { drawings: true });
    const first = trend(a);
    group.remove(b.chart);
    expect(lines(b)).toEqual([first.points]);
    a.draw.remove(first.id);
    trend(a);
    expect(lines(b)).toEqual([first.points]);
  });

  it('reconnects a copy when sharing resumes, and the chart already sharing sets its state', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group } = link([a, b], { drawings: true });
    const made = trend(a);
    group.setOptions({ drawings: false });
    // While unlinked, an edit to the copy stays on the chart that made it.
    const lowered = made.points.map(p => ({ ...p, price: Math.round(p.price * 0.98 * 100) / 100 }));
    b.draw.update(b.draw.drawings()[0].id, { points: lowered });
    expect(lines(a)).toEqual([made.points]);
    expect(lines(b)).toEqual([lowered]);
    // Members join in the order they were added, so A is sharing when B
    // reconnects, and B's unlinked edit gives way to A's drawing.
    group.setOptions({ drawings: true });
    expect(lines(b)).toEqual([made.points]);
    const raised = made.points.map(p => ({ ...p, price: Math.round(p.price * 1.02 * 100) / 100 }));
    a.draw.update(made.id, { points: raised });
    expect(lines(b)).toEqual([raised]);
  });

  it('applies a deletion made while a chart was out of the group when it rejoins', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group, sharing } = link([a, b], { drawings: true });
    const made = trend(a);
    group.remove(b.chart);
    a.draw.remove(made.id);
    expect(lines(b)).toEqual([made.points]);
    group.add(b.chart, { drawings: { join: () => sharing.add(b.chart, b.draw), leave: () => sharing.remove(b.chart) } });
    expect(b.draw.drawings()).toEqual([]);
  });

  it('never carries one instrument\'s drawing onto another when a chart changes instrument alone', () => {
    const a = cell('INFY', 3); const b = cell('INFY', 5);
    const { group, sharing } = link([a, b], { drawings: true });
    const infy = trend(a);
    choose(group, b, 'SBIN');
    expect(b.draw.drawings()).toEqual([]);
    const away = a.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {},
      points: [{ time: a.bars()[100].time, price: a.bars()[100].high }] });
    expect(b.draw.drawings()).toEqual([]);
    const sbin = trend(b);
    expect(lines(a)).toEqual([infy.points, away.points]);
    // Back on INFY, the copy it held reconnects and follows A's edits again.
    choose(group, b, 'INFY');
    expect(lines(b)).toEqual([infy.points]);
    const raised = infy.points.map(p => ({ ...p, price: Math.round(p.price * 1.02 * 100) / 100 }));
    a.draw.update(infy.id, { points: raised });
    expect(lines(b)).toEqual([raised]);
    // A drawing made while it was away is not pushed at it on arrival: it is
    // shared with the charts that were there, and reaches this one when the
    // host shares it again.
    expect(sharing.share(a.chart, [away.id])).toBe(1);
    expect(lines(b)).toEqual([raised, away.points]);
    // The SBIN level stayed with SBIN.
    expect(b.scoped.document({ symbol: 'SBIN', exchange: 'NSE' })?.drawings.map(d => d.points)).toEqual([sbin.points]);
  });
});

describe('new channel defaults', () => {
  it('starts with chart type and drawings off, and asks nothing of an adapter until then', () => {
    const group = createLinkGroup();
    expect(group.options()).toMatchObject({ drawings: false, chartType: false });
    const join = vi.fn();
    group.add(new MemberChart(), { drawings: { join, leave: vi.fn() } });
    expect(join).not.toHaveBeenCalled();
  });
});
