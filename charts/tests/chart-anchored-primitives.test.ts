import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import type { IPrimitive } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => ({ time: 1700000000 + i * 60, open: 100, high: 101, low: 99, close: 100, volume: 1 }));

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

function makeChart(): Chart {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(),
    raf: { schedule: () => 0 },
    pixelRatio: () => 1,
    shortcuts: false,
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars(40));
  return chart;
}

/** Minimal primitive; identity is all these tests need. */
const mark = (): IPrimitive => ({ draw: () => {}, zOrder: () => 'top' });

/** Which pane currently holds it, or -1. */
const paneOf = (chart: Chart, p: IPrimitive): number =>
  chart.panes().findIndex((pane) => pane.hasPrimitive(p));

describe('paneAdded', () => {
  it('fires when an indicator pane is created lazily', () => {
    const chart = makeChart();
    const seen: number[] = [];
    chart.on('paneAdded', (e) => seen.push((e as { paneIndex: number }).paneIndex));
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect(seen).toEqual([1]);
  });

  it('fires once per pane when several are created at once', () => {
    const chart = makeChart();
    const seen: number[] = [];
    chart.on('paneAdded', (e) => seen.push((e as { paneIndex: number }).paneIndex));
    // Asking for pane 3 makes 1, 2 and 3.
    chart.addSeries('line', { paneIndex: 3 }).setData(bars(40));
    expect(seen).toEqual([1, 2, 3]);
  });

  it('does not fire when the pane already exists', () => {
    const chart = makeChart();
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    const seen: number[] = [];
    chart.on('paneAdded', () => seen.push(1));
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect(seen).toEqual([]);
  });
});

describe('chart-anchored primitives follow the edge', () => {
  it('chart-bottom starts on the only pane', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    expect(paneOf(chart, m)).toBe(0);
  });

  it('moves down when an indicator pane appears beneath it', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    // This is the bug the issue was filed for: the mark used to stay on pane 0,
    // which is now the middle of the chart.
    expect(paneOf(chart, m)).toBe(1);
    chart.addSeries('line', { paneIndex: 2 }).setData(bars(40));
    expect(paneOf(chart, m)).toBe(2);
  });

  it('moves back up when the bottom pane is removed', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect(paneOf(chart, m)).toBe(1);
    chart.removePane(1);
    expect(paneOf(chart, m)).toBe(0);
  });

  it('follows a maximized pane, which hides the others entirely', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    chart.addSeries('line', { paneIndex: 2 }).setData(bars(40));
    expect(paneOf(chart, m)).toBe(2);
    // Maximizing pane 1 hides 0 and 2. A mark left on 2 would vanish with it.
    chart.maximizePane(1);
    expect(paneOf(chart, m)).toBe(1);
    chart.maximizePane(1); // restore
    expect(paneOf(chart, m)).toBe(2);
  });

  it('chart-top stays on the top visible pane', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-top' });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect(paneOf(chart, m)).toBe(0);
    chart.maximizePane(1);
    expect(paneOf(chart, m)).toBe(1);
  });

  it('a pane-indexed primitive is left exactly where the host put it', () => {
    const chart = makeChart();
    const pinned = mark();
    chart.addPrimitive(pinned, 0);
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    // Unchanged behaviour: only an anchored primitive is re-homed.
    expect(paneOf(chart, pinned)).toBe(0);
  });
});

/**
 * Registry lifecycle. The placement tests above prove an anchored primitive
 * MOVES; these prove it stops existing when removed, which is a different
 * property and the one an anchor registry gets wrong.
 */
describe('anchored primitives can actually be removed', () => {
  it('removePrimitive is not undone by a later pane change', () => {
    const chart = makeChart();
    const m = mark();
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    chart.removePrimitive(m);
    expect(paneOf(chart, m)).toBe(-1);
    // Was: the pane copy went but the registry entry stayed, so the next
    // re-home put the removed primitive back on the chart.
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect(paneOf(chart, m)).toBe(-1);
    chart.removePane(1);
    expect(paneOf(chart, m)).toBe(-1);
  });

  it('survives repeated add and remove without duplicating itself', () => {
    const chart = makeChart();
    const m = mark();
    for (let i = 0; i < 3; i++) {
      chart.addPrimitive(m, { anchor: 'chart-bottom' });
      chart.removePrimitive(m);
    }
    chart.addPrimitive(m, { anchor: 'chart-bottom' });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    const holders = chart.panes().filter((p) => p.hasPrimitive(m)).length;
    expect(holders).toBe(1);
  });

  it('attaches and detaches exactly once per move', () => {
    const chart = makeChart();
    let attached = 0;
    let detached = 0;
    const counting: IPrimitive = {
      draw: () => {},
      zOrder: () => 'top',
      attached: () => { attached += 1; },
      detached: () => { detached += 1; },
    };
    chart.addPrimitive(counting, { anchor: 'chart-bottom' });
    expect([attached, detached]).toEqual([1, 0]);
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(40));
    expect([attached, detached]).toEqual([2, 1]);
    chart.removePrimitive(counting);
    expect([attached, detached]).toEqual([2, 2]);
  });
});
