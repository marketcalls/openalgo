import { afterEach, describe, expect, it } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { createLinkGroup } from '../src/link/group';
import { TimeScale, type LogicalRange } from '../src/scale/time-scale';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const bars = Array.from({ length: 120 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i,
}));
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function fixture(options: Partial<ChartOptions> = {}) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, animZoom: false, animAutoscale: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} }, ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(bars);
  chart.setVisibleLogicalRange({ from: 20, to: 60 });
  const events: { type: string; range: LogicalRange }[] = [];
  for (const type of ['pan', 'zoom']) chart.on(type, payload => {
    const event = payload as { logicalFrom: number; logicalTo: number };
    events.push({ type, range: { from: event.logicalFrom, to: event.logicalTo } });
  });
  const paints: LogicalRange[] = [];
  chart.addPrimitive({ zOrder: () => 'normal', draw: (_ctx, rc) => { paints.push(rc.timeScale.visibleRange()); } });
  paints.length = 0;
  return { chart, series, events, paints };
}

const operations: [string, 'pan' | 'zoom', (scale: TimeScale) => void][] = [
  ['bar spacing', 'zoom', scale => scale.setBarSpacing(scale.barSpacing * 1.5)],
  ['right offset', 'pan', scale => scale.setRightOffset(scale.rightOffset - 7)],
  ['logical range', 'pan', scale => scale.setVisibleLogicalRange({ from: 30, to: 70 })],
  ['scroll', 'pan', scale => scale.scrollByPixels(80)],
  ['anchored zoom', 'zoom', scale => scale.zoomAtX(240, 1.5)],
  ['fit content', 'zoom', scale => scale.fitContent(bars.length)],
];

describe('public time scale notifications', () => {
  it.each(operations)('repaints and emits one settled event for direct %s', (_name, type, apply) => {
    const f = fixture();
    apply(f.chart.timeScale);
    const range = f.chart.getVisibleLogicalRange();
    expect(f.events).toEqual([{ type, range }]);
    expect(f.paints.length).toBeGreaterThan(0);
    expect(f.paints.every(painted => painted.from === range.from && painted.to === range.to)).toBe(true);
  });

  it.each(operations)('reports one final state to a standalone scale handler for %s', (_name, _type, apply) => {
    const scale = new TimeScale();
    scale.setWidth(744);
    scale.setBaseIndex(119);
    scale.setVisibleLogicalRange({ from: 20, to: 60 });
    const seen: LogicalRange[] = [];
    scale.setChangeHandler(() => { seen.push(scale.visibleRange()); });
    apply(scale);
    expect(seen).toEqual([scale.visibleRange()]);
  });

  it('keeps no-op and clamped mutations silent', () => {
    const f = fixture();
    const scale = f.chart.timeScale;
    scale.setBarSpacing(scale.barSpacing);
    scale.setRightOffset(scale.rightOffset);
    scale.setVisibleLogicalRange(scale.visibleRange());
    scale.setVisibleLogicalRange({ from: 10, to: 10 });
    scale.scrollByPixels(0);
    scale.zoomAtX(50, 1);
    expect(f.events).toEqual([]);
    expect(f.paints).toEqual([]);
    scale.setBarSpacing(1000);
    f.events.length = 0; f.paints.length = 0;
    scale.setBarSpacing(2000);
    scale.zoomAtX(50, 2);
    expect(f.events).toEqual([]);
    expect(f.paints).toEqual([]);
  });

  it('gives chart wrappers the same single-event behavior as direct operations', () => {
    const direct = fixture(), wrapped = fixture();
    direct.chart.timeScale.setVisibleLogicalRange({ from: 30, to: 80 });
    wrapped.chart.setVisibleLogicalRange({ from: 30, to: 80 });
    expect(direct.events).toEqual(wrapped.events);
    expect(wrapped.events).toHaveLength(1);
    direct.events.length = 0; wrapped.events.length = 0;
    direct.chart.timeScale.fitContent(bars.length);
    wrapped.chart.fitContent();
    expect(direct.events).toEqual(wrapped.events);
    expect(wrapped.events).toHaveLength(1);
  });

  it.each(operations)('synchronizes linked charts once for direct %s', (_name, _type, apply) => {
    const leader = fixture(), follower = fixture();
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(leader.chart); group.add(follower.chart);
    try {
      apply(leader.chart.timeScale);
      const range = leader.chart.getVisibleLogicalRange();
      expect(follower.chart.getVisibleLogicalRange().from).toBeCloseTo(range.from, 8);
      expect(follower.chart.getVisibleLogicalRange().to).toBeCloseTo(range.to, 8);
      expect(leader.events).toHaveLength(1);
      expect(follower.events).toHaveLength(1);
    } finally { group.destroy(); }
  });

  it('coalesces reset and restore to their final viewport', () => {
    const f = fixture({ navigation: { defaultVisibleBars: 50 } });
    f.chart.resetScale();
    expect(f.events).toEqual([{ type: 'zoom', range: f.chart.getVisibleLogicalRange() }]);
    const saved = f.chart.getState();
    f.chart.setVisibleLogicalRange({ from: 20, to: 60 });
    f.events.length = 0;
    expect(f.chart.restoreState(saved).applied).toBe(true);
    expect(f.events).toEqual([{ type: 'zoom', range: f.chart.getVisibleLogicalRange() }]);
  });

  it('keeps data bookkeeping and resize out of navigation events', () => {
    const f = fixture();
    f.series.setData(bars.slice(0, 100));
    f.series.update(bars[100]);
    f.series.prependData([{ ...bars[0], time: bars[0].time - 60 }]);
    f.chart.applySize(900, 650);
    expect(f.events).toEqual([]);
    f.chart.timeScale.setRightOffset(f.chart.timeScale.rightOffset - 1);
    expect(f.events).toEqual([{ type: 'pan', range: f.chart.getVisibleLogicalRange() }]);
  });

  it('accepts a viewport replacement from a range listener without an echo', () => {
    const f = fixture();
    const target = { from: 15, to: 45 };
    f.chart.on('zoom', () => f.chart.timeScale.setVisibleLogicalRange(target));
    f.chart.timeScale.setBarSpacing(f.chart.timeScale.barSpacing * 1.5);
    expect(f.chart.getVisibleLogicalRange()).toEqual(target);
    expect(f.events).toHaveLength(2);
    expect(f.events[1].range).toEqual(target);
  });

  it('detaches the chart callback when destroyed', () => {
    const f = fixture();
    f.chart.destroy();
    f.chart.timeScale.setRightOffset(12);
    f.chart.timeScale.setBarSpacing(8);
    expect(f.events).toEqual([]);
    expect(f.paints).toEqual([]);
  });

  it.each(operations.slice(0, 3))('cancels pending wheel motion on direct %s', (_name, _type, apply) => {
    let now = 0, id = 0;
    const queue = new Map<number, () => void>();
    const f = fixture({ animZoom: true, now: () => now,
      raf: { schedule: cb => { queue.set(++id, cb); return id; }, cancel: handle => { queue.delete(handle); } },
    });
    const tick = () => {
      now += 16;
      for (const [handle, callback] of [...queue]) if (queue.delete(handle)) callback();
    };
    const settle = () => { for (let frame = 0; frame < 100 && queue.size; frame++) tick(); };
    settle();
    (f.chart as unknown as { _onWheel(e: unknown): void })._onWheel({
      clientX: 400, clientY: 200, deltaX: 0, deltaY: -100, deltaMode: 0, preventDefault() {},
    });
    tick();
    f.events.length = 0; f.paints.length = 0;
    apply(f.chart.timeScale);
    const range = f.chart.getVisibleLogicalRange();
    expect(f.events).toHaveLength(1);
    expect(f.events[0].range).toEqual(range);
    settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual(range);
    expect(f.events).toHaveLength(1);
    expect(f.paints.length).toBeGreaterThan(0);
    expect(f.paints.every(painted => painted.from === range.from && painted.to === range.to)).toBe(true);
    expect(queue.size).toBe(0);
  });

  it('passes the detached previous range to the handler after an atomic zoom', () => {
    const scale = new TimeScale();
    scale.setWidth(744); scale.setBaseIndex(119);
    const before = scale.visibleRange();
    const focus = scale.xToIndex(140);
    const observed: LogicalRange[] = [];
    scale.setChangeHandler(previous => {
      observed.push({ ...previous });
      previous.from = 0;
      expect(scale.indexToX(focus)).toBeCloseTo(140, 10);
    });
    scale.zoomAtX(140, 1.5);
    expect(observed).toEqual([before]);
    expect(scale.visibleRange().from).not.toBe(0);
    scale.setChangeHandler(null);
    scale.setRightOffset(10);
    expect(observed).toHaveLength(1);
  });

  it('cancels wheel motion on an explicit same-range request without repaint or event', () => {
    let now = 0, id = 0;
    const queue = new Map<number, () => void>();
    const f = fixture({ animZoom: true, now: () => now,
      raf: { schedule: cb => { queue.set(++id, cb); return id; }, cancel: handle => { queue.delete(handle); } },
    });
    const tick = () => {
      now += 16;
      for (const [handle, callback] of [...queue]) if (queue.delete(handle)) callback();
    };
    const settle = () => { for (let frame = 0; frame < 100 && queue.size; frame++) tick(); };
    settle();
    (f.chart as unknown as { _onWheel(e: unknown): void })._onWheel({
      clientX: 400, clientY: 200, deltaX: 0, deltaY: -100, deltaMode: 0, preventDefault() {},
    });
    tick();
    f.events.length = 0; f.paints.length = 0;
    const range = f.chart.getVisibleLogicalRange();
    f.chart.timeScale.setVisibleLogicalRange(range);
    expect(f.events).toEqual([]);
    expect(f.paints).toEqual([]);
    settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual(range);
    expect(f.events).toEqual([]);
  });

  it('paints a direct viewport replacement from the final restore notification', () => {
    const f = fixture();
    const saved = f.chart.getState();
    const target = { from: 10, to: 30 };
    f.chart.on('objects:change', () => f.chart.timeScale.setVisibleLogicalRange(target));
    f.paints.length = 0;
    expect(f.chart.restoreState(saved).applied).toBe(true);
    expect(f.chart.getVisibleLogicalRange()).toEqual(target);
    expect(f.events).toEqual([{ type: 'zoom', range: target }]);
    expect(f.paints[f.paints.length - 1]).toEqual(target);
  });
});
