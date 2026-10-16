/**
 * What a double-click on a pane does.
 *
 * The engine used to hard-code reset: fit every loaded bar and autoscale.
 * That lands the viewport on the oldest bar, which is exactly where a host's
 * history loader wakes up, so on a live terminal a double-click fetched a page
 * of history the trader never asked for. `doubleClick` makes the gesture the
 * host's choice, with the old behaviour as the default, and the event now says
 * which pane was under the pointer so a host running `'none'` can do its own
 * thing.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import type { ChartOptions, DoubleClickEvent } from '../src/core/chart';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

const BARS: Bar[] = Array.from({ length: 200 }, (_, i) => {
  const c = 100 + Math.sin(i / 9) * 5;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 10 + i };
});
const W = 800;
const H = 600;

// Pointer listeners are only wired when a `window` exists.
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

/** Two panes: the price series on 0, a second series on 1, zoomed in to the last ten bars. */
function twoPanes(options: Partial<ChartOptions> = {}): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(),
    raf: { schedule: () => 0 },
    pixelRatio: () => 1,
    shortcuts: false,
    ...options,
  });
  chart.applySize(W, H);
  chart.addSeries('candlestick').setData(BARS);
  chart.addSeries('line', { paneIndex: 1 }).setData(BARS.map((b) => ({ time: b.time, value: b.close })));
  chart.setVisibleLogicalRange({ from: 190, to: 199 });
  return { chart, el };
}

const dblclick = (el: FakeElement, x: number, y: number): void => el.dispatch('dblclick', { clientX: x, clientY: y });

describe('doubleClick option', () => {
  it("defaults to reset, which is what the chart has always done", () => {
    const { chart, el } = twoPanes();
    expect(chart.getVisibleLogicalRange().from).toBeGreaterThan(100);
    dblclick(el, 400, 100);
    expect(chart.getVisibleLogicalRange().from).toBeLessThan(10);
    expect(chart.maximizedPane()).toBeNull();
  });

  it("'maximize' toggles the pane under the pointer to the whole stack, and back", () => {
    const { chart, el } = twoPanes({ doubleClick: 'maximize' });
    const before = chart.getVisibleLogicalRange();
    dblclick(el, 400, H - 20); // the second pane sits at the bottom of the stack
    expect(chart.maximizedPane()).toBe(1);
    // The viewport is the trader's: maximizing a pane is not a reset.
    expect(chart.getVisibleLogicalRange()).toEqual(before);
    dblclick(el, 400, H - 20);
    expect(chart.maximizedPane()).toBeNull();
  });

  it("'none' leaves the view alone and only emits", () => {
    const { chart, el } = twoPanes({ doubleClick: 'none' });
    const before = chart.getVisibleLogicalRange();
    const seen: DoubleClickEvent[] = [];
    chart.on('dblclick', (e) => seen.push(e as DoubleClickEvent));
    dblclick(el, 400, 100);
    expect(seen).toHaveLength(1);
    expect(seen[0].paneIndex).toBe(0);
    expect(chart.getVisibleLogicalRange()).toEqual(before);
    expect(chart.maximizedPane()).toBeNull();
  });

  it('a listener that handled the press keeps the chart from acting on it too', () => {
    const { chart, el } = twoPanes({ doubleClick: 'maximize' });
    chart.on('dblclick', (e) => {
      (e as DoubleClickEvent).handled = true;
    });
    dblclick(el, 400, H - 20);
    expect(chart.maximizedPane()).toBeNull();
  });

  it('tells the listener which pane was under the pointer', () => {
    const { chart, el } = twoPanes({ doubleClick: 'none' });
    const panes: number[] = [];
    chart.on('dblclick', (e) => panes.push((e as DoubleClickEvent).paneIndex));
    dblclick(el, 400, 20);
    dblclick(el, 400, H - 20);
    expect(panes).toEqual([0, 1]);
  });
});
