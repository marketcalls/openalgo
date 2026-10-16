import { describe, it, expect, beforeAll } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { PaneLegend } from '../src/primitives/pane-legend';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 10 + i };
  });

const W = 800;
const H = 600;

// The chart only wires pointer listeners when a `window` exists (`_attachInput`),
// so under the node environment these tests would otherwise assert against
// handlers that were never attached, and pass for the wrong reason.
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

function makeChart(): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(),
    raf: { schedule: () => 0 },
    pixelRatio: () => 1,
    shortcuts: false,
  });
  chart.applySize(W, H);
  return { chart, el };
}

/** Cumulative pane tops, mirroring the chart's own weighted layout. */
function paneTops(chart: Chart): number[] {
  const total = chart.panes().reduce((s, p) => s + p.weight, 0);
  let top = 0;
  return chart.panes().map((p) => {
    const t = top;
    top += (H * p.weight) / total;
    return t;
  });
}

describe('pane weights', () => {
  it('setPaneWeight resizes and sizes the DOM box to the same pixels', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(50));
    chart.addSeries('histogram', { paneIndex: 1 }).setData(bars(50));
    chart.setPaneWeight(1, 0.8);
    expect(chart.paneWeight(1)).toBe(0.8);
    // The DOM flex-basis must equal the pixel height the canvas was sized to:
    // when they diverge, every hit-test lands somewhere other than what's drawn.
    // The boundary between them sits on a whole pixel (the ratio is 1 here),
    // and the pane below takes what the one above leaves.
    const total = 1 + 0.8;
    const expected = H - Math.round(H / total);
    expect(chart.panes()[1].element.style.flex).toBe(`0 0 ${expected}px`);
    expect(chart.panes()[1].base.mediaHeight).toBe(expected);
  });

  it('clamps a non-positive weight instead of collapsing the layout', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(10));
    chart.setPaneWeight(0, 0);
    expect(chart.paneWeight(0)).toBeGreaterThan(0);
  });

  it('ignores a weight that is not a finite number, which would poison the layout', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(50));
    chart.addSeries('histogram', { paneIndex: 1 }).setData(bars(50));
    chart.setPaneWeight(1, 0.5);
    const flex = chart.panes().map((p) => p.element.style.flex);
    for (const weight of [NaN, Infinity, -Infinity]) chart.setPaneWeight(1, weight);
    expect(chart.paneWeight(1)).toBe(0.5);
    expect(chart.panes().map((p) => p.element.style.flex)).toEqual(flex);
  });
});

describe('pane divider drag', () => {
  function threePane(): { chart: Chart; el: FakeElement } {
    const made = makeChart();
    made.chart.addSeries('candlestick').setData(bars(60));
    made.chart.addSeries('histogram', { paneIndex: 1 }).setData(bars(60));
    made.chart.addSeries('line', { paneIndex: 2 }).setData(bars(60));
    return made;
  }

  it('dragging the boundary moves height between the two adjacent panes', () => {
    const { chart, el } = threePane();
    const tops = paneTops(chart);
    const boundary = tops[2]; // between pane 1 and pane 2
    const before = chart.panes().map((p) => p.weight);

    el.dispatch('pointerdown', pointer('down', 400, boundary));
    el.dispatch('pointermove', pointer('move', 400, boundary - 40));
    el.dispatch('pointerup', pointer('up', 400, boundary - 40));

    const after = chart.panes().map((p) => p.weight);
    expect(after[1]).toBeLessThan(before[1]);   // pane above shrank
    expect(after[2]).toBeGreaterThan(before[2]); // pane below grew
    // Panes not adjacent to the boundary are untouched.
    expect(after[0]).toBe(before[0]);
    // ...and the pair's combined weight is conserved.
    expect(after[1] + after[2]).toBeCloseTo(before[1] + before[2], 9);
  });

  it('grabs the divider anywhere within the tolerance band', () => {
    for (const offset of [-3, 0, 3]) {
      const { chart, el } = threePane();
      const boundary = paneTops(chart)[2];
      const before = chart.paneWeight(1);
      el.dispatch('pointerdown', pointer('down', 400, boundary + offset));
      el.dispatch('pointermove', pointer('move', 400, boundary + offset - 30));
      el.dispatch('pointerup', pointer('up', 400, boundary + offset - 30));
      expect(chart.paneWeight(1), `offset ${offset}`).toBeLessThan(before);
    }
  });

  it('ignores a press well away from any boundary (that still pans)', () => {
    const { chart, el } = threePane();
    const before = chart.panes().map((p) => p.weight);
    const mid = paneTops(chart)[1] + 40;
    el.dispatch('pointerdown', pointer('down', 400, mid));
    el.dispatch('pointermove', pointer('move', 400, mid - 40));
    el.dispatch('pointerup', pointer('up', 400, mid - 40));
    expect(chart.panes().map((p) => p.weight)).toEqual(before);
  });

  it('never collapses a pane to zero, however far the drag goes', () => {
    const { chart, el } = threePane();
    const boundary = paneTops(chart)[2];
    el.dispatch('pointerdown', pointer('down', 400, boundary));
    el.dispatch('pointermove', pointer('move', 400, boundary - 5000));
    el.dispatch('pointerup', pointer('up', 400, boundary - 5000));
    for (const p of chart.panes()) expect(p.weight).toBeGreaterThan(0);
  });
});

describe('pane legend rows', () => {
  it('stacks host-added and indicator legends in one sequence', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    // A host row (symbol / OHLC) added first must keep row 0, with the
    // indicator's own legend flowing beneath it rather than overlapping.
    const symbol = new PaneLegend({ id: 'symbol', title: 'AAPL', actions: [] });
    chart.addPrimitive(symbol, 0);
    chart.addIndicator('ema'); // onchart: same pane
    expect(symbol.options().row).toBe(0);
    const ema = chart.indicators()[0].legend();
    expect(ema?.options().row).toBe(2); // the persistent study count reserves one row
  });

  it('starts indicator legends below a host overlay when legendOffset says so', () => {
    // A host that draws its own OHLC readout in the corner needs the canvas
    // rows pushed clear of it; otherwise they land underneath, and their
    // settings / close buttons are invisible and unclickable.
    const el = fakeDocument().createElement('div') as unknown as FakeElement;
    const chart = new Chart(el, {
      document: fakeDocument(), raf: { schedule: () => 0 },
      pixelRatio: () => 1, shortcuts: false,
      legendOffset: { top: 40, left: 14 },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('ema');

    const opts = chart.indicators()[0].legend()?.options();
    expect(opts?.top).toBe(40);
    expect(opts?.left).toBe(14);
    expect(opts?.row).toBe(1); // below the count, with the same host overlay offset
  });

  it('offsets only the overlaid pane, leaving lower panes at the corner', () => {
    // A lower indicator pane is short. Applying a price-pane offset there would
    // push its legend (and so its settings and close buttons) off the pane.
    const el = fakeDocument().createElement('div') as unknown as FakeElement;
    const chart = new Chart(el, {
      document: fakeDocument(), raf: { schedule: () => 0 },
      pixelRatio: () => 1, shortcuts: false,
      legendOffset: { top: 80 },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('ema');   // onchart -> pane 0, shifted
    chart.addIndicator('rsi');   // own pane -> default corner

    const [onchart, lower] = chart.indicators();
    expect(onchart.legend()?.options().top).toBe(80);
    expect(lower.paneIndex).toBeGreaterThan(0);
    expect(lower.legend()?.options().top).toBe(6);
  });

  it('moves the offset to a maximized lower pane, which now sits at the top', () => {
    // Maximizing parks the other panes at a placeholder weight, so the
    // maximized pane renders in the corner the host overlay covers. Pinning the
    // offset to pane 0 left the maximized pane drawing through that overlay.
    const el = fakeDocument().createElement('div') as unknown as FakeElement;
    const chart = new Chart(el, {
      document: fakeDocument(), raf: { schedule: () => 0 },
      pixelRatio: () => 1, shortcuts: false,
      legendOffset: { top: 80 },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('ema');   // pane 0
    chart.addIndicator('rsi');   // own pane
    const [onchart, lower] = chart.indicators();
    expect(lower.legend()?.options().top).toBe(6);

    chart.maximizePane(lower.paneIndex);
    expect(lower.legend()?.options().top).toBe(80);
    // ...and pane 0, now a sliver still at the very top, keeps it too.
    expect(onchart.legend()?.options().top).toBe(80);

    chart.maximizePane(lower.paneIndex); // toggle back
    expect(lower.legend()?.options().top).toBe(6);
  });

  it('leaves legends at the default corner with no offset given', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('ema');
    const opts = chart.indicators()[0].legend()?.options();
    expect(opts?.top).toBe(6);
    expect(opts?.left).toBe(8);
  });

  it('closes the gap when a legend above is removed', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const a = new PaneLegend({ id: 'a', title: 'A', actions: [] });
    const b = new PaneLegend({ id: 'b', title: 'B', actions: [] });
    chart.addPrimitive(a, 0);
    chart.addPrimitive(b, 0);
    expect(b.options().row).toBe(1);
    chart.removePrimitive(a);
    expect(b.options().row).toBe(0);
  });

  it('reports one reading per plot, in each plot colour', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const inst = chart.addIndicator('macd');
    inst.setSettings({ macdColor: '#111111', signalColor: '#222222' });
    const legend = inst.legend();
    const values = (legend as unknown as { _values: { text: string; color?: string }[] })._values;
    expect(values.length).toBeGreaterThanOrEqual(2);
    expect(values.map((v) => v.color)).toContain('#111111');
    expect(values.map((v) => v.color)).toContain('#222222');
  });

  it('gives every plot colour / opacity / thickness / line style', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const macd = chart.addIndicator('macd');
    const s = macd.settings();
    // Generated per-plot appearance keys, no descriptor boilerplate.
    expect(s['macd:width']).toBeDefined();
    expect(s['macd:opacity']).toBe(100);
    expect(s['macd:lineStyle']).toBe('solid');

    macd.setSettings({ 'macd:width': 4, 'macd:lineStyle': 'dashed', 'macd:opacity': 50, macdColor: '#ff0000' });
    const series = macd.series('macd') as unknown as { __style?: unknown };
    void series;
    expect(macd.settings()['macd:width']).toBe(4);
    // Opacity folds into the colour as an alpha: a canvas stroke has no
    // separate opacity channel.
    const legend = macd.legend();
    const values = (legend as unknown as { _values: { color?: string }[] })._values;
    expect(values.some((v) => v.color === '#ff0000')).toBe(true);
  });

  it('hides a source without removing it', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');
    expect(rsi.visible()).toBe(true);
    rsi.setVisible(false);
    expect(rsi.visible()).toBe(false);
    expect(chart.indicators()).toHaveLength(1); // hidden, not deleted
    rsi.setVisible(true);
    expect(rsi.visible()).toBe(true);
  });
});

describe('pane removal, ordering, and maximize', () => {
  it('removePane drops the pane, its series, and its indicators', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');
    expect(chart.panes().length).toBe(2);
    expect(chart.removePane(rsi.paneIndex)).toBe(true);
    expect(chart.panes().length).toBe(1);
    expect(chart.indicators()).toHaveLength(0);
  });

  it('refuses to remove the price pane', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(20));
    expect(chart.removePane(0)).toBe(false);
    expect(chart.removePane(99)).toBe(false);
  });

  it('re-indexes indicators below a removed pane', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');    // pane 1
    const macd = chart.addIndicator('macd');  // pane 2
    expect([rsi.paneIndex, macd.paneIndex]).toEqual([1, 2]);
    chart.removePane(1);
    expect(macd.paneIndex).toBe(1); // shifted up with its pane
  });

  it('movePane swaps two panes and their indicators', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');
    const macd = chart.addIndicator('macd');
    expect(chart.movePane(2, -1)).toBe(true);
    expect(macd.paneIndex).toBe(1);
    expect(rsi.paneIndex).toBe(2);
    expect(chart.movePane(0, 1)).toBe(false);  // the price pane is pinned
    expect(chart.movePane(1, -1)).toBe(false); // ...and cannot be displaced
    // Off either end is refused too. A host that opts in with
    // `movablePrimaryPane` can move the price pane (primary-pane-reorder.test.ts).
    expect(chart.movePane(0, -1)).toBe(false);
    expect(chart.movePane(2, 1)).toBe(false);
    expect(chart.movePane(1, 2 as unknown as 1)).toBe(false);
    expect([chart.primaryPaneIndex(), macd.paneIndex, rsi.paneIndex]).toEqual([0, 1, 2]);
  });

  it('maximizePane gives one pane the whole chart and hides the rest', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('rsi');
    const before = chart.panes().map((p) => p.weight);

    chart.maximizePane(1);
    expect(chart.maximizedPane()).toBe(1);
    // Hidden outright, not collapsed to a sliver: a sliver still paints a strip
    // of squeezed candles and a separator hairline above the maximized pane.
    expect(chart.panes()[0].element.style.display).toBe('none');
    expect(chart.panes()[0].element.style.flex).toBe('0 0 0px');
    expect(chart.panes()[1].element.style.display).toBe('');
    expect(chart.panes()[1].element.style.flex).toBe(`0 0 ${H}px`);
    // The maximized pane is now against the top edge, so it wears no separator.
    expect(chart.panes()[1].element.style.borderTopWidth).toBe('0px');
    // Stored weights are never disturbed, so nothing can be stranded.
    expect(chart.panes().map((p) => p.weight)).toEqual(before);

    chart.maximizePane(1);
    expect(chart.maximizedPane()).toBeNull();
    expect(chart.panes().map((p) => p.weight)).toEqual(before);
    expect(chart.panes()[0].element.style.display).toBe('');
    // Restored, the study pane sits under the price pane again and wears the rule.
    expect(chart.panes()[1].element.style.borderTopWidth).toBe('1px');
    expect(chart.panes()[0].element.style.borderTopWidth).toBe('0px');
  });

  it('drops a study pane with the study, host visuals and all, but keeps one a move leaves them on', () => {
    // Two rules on purpose: a removed study takes its pane, whatever was
    // placed on it against the study's units; a study moved away leaves a
    // pane that still holds such a visual, as ChartPanes._holdsOnlyFurniture says.
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const removed = chart.addIndicator('rsi');
    chart.addPrimitive(new PaneLegend({ id: 'host-note', title: 'Note' }), removed.paneIndex);
    expect(chart.panes()).toHaveLength(2);
    chart.removeIndicator(removed.id);
    expect(chart.panes()).toHaveLength(1);

    const moved = chart.addIndicator('rsi');
    chart.addPrimitive(new PaneLegend({ id: 'host-note-2', title: 'Note' }), moved.paneIndex);
    expect(chart.moveIndicator(moved.id, 0)).toBe(true);
    expect(chart.panes()).toHaveLength(2);

    // A pane that held nothing but the study goes with a move too.
    const bare = chart.addIndicator('rsi');
    expect(chart.panes()).toHaveLength(3);
    expect(chart.moveIndicator(bare.id, 0)).toBe(true);
    expect(chart.panes()).toHaveLength(2);
  });

  it('refuses to maximize an index that names no pane, which would hide every pane', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('rsi');
    for (const index of [0.5, 1.5, NaN, -1, 2]) expect(chart.maximizePane(index)).toBe(false);
    expect(chart.maximizedPane()).toBeNull();
    expect(chart.panes().map((p) => p.element.style.display)).toEqual(['', '']);
  });

  it('hands the time axis to the maximized pane', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    chart.addIndicator('rsi');
    // Normally the bottom pane owns the time axis and gives up height for it.
    const full = (i: number): string => chart.panes()[i].element.style.flex;
    chart.maximizePane(0);
    expect(full(0)).toBe(`0 0 ${H}px`);
    // Pane 0 is now the bottom visible pane, so its scale stops short of the
    // time axis rather than running the full height.
    expect(chart.panes()[0].priceScale.height).toBeLessThan(H);
  });
});

describe('repeated indicators get distinct colours', () => {
  // Three EMAs in the descriptor's one default blue are indistinguishable on
  // the chart and in the legend alike.
  const emaColor = (i: { settings(): Record<string, unknown> }): unknown => i.settings().color;

  it('rotates the colour for the 2nd and later instances', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    const a = chart.addIndicator('ema');
    const b = chart.addIndicator('ema');
    const c = chart.addIndicator('ema');
    expect(emaColor(b)).not.toBe(emaColor(a));
    expect(emaColor(c)).not.toBe(emaColor(a));
    expect(emaColor(c)).not.toBe(emaColor(b));
  });

  it('leaves the first instance on the descriptor colour', () => {
    const one = makeChart().chart;
    one.addSeries('candlestick').setData(bars(80));
    const two = makeChart().chart;
    two.addSeries('candlestick').setData(bars(80));
    expect(emaColor(one.addIndicator('ema'))).toBe(emaColor(two.addIndicator('ema')));
  });

  it('never overrides a colour the caller passed', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    chart.addIndicator('ema');
    expect(emaColor(chart.addIndicator('ema', { color: '#123456' }))).toBe('#123456');
  });

  it('counts per indicator id, so another indicator starts fresh', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    chart.addIndicator('ema');
    chart.addIndicator('ema');
    const other = makeChart().chart;
    other.addSeries('candlestick').setData(bars(80));
    expect(emaColor(chart.addIndicator('rsi'))).toBe(emaColor(other.addIndicator('rsi')));
  });
});

describe('a pane scale forgets a departed series', () => {
  it('clears the range when the last series on a scale is removed', () => {
    const { chart } = makeChart();
    const s = chart.addSeries('line');
    s.setData(bars(60).map((b) => ({ time: b.time, value: b.close })));
    chart.priceToCoordinate(0); // forces the on-demand autoscale
    const scale = chart.panes()[0].priceScale;
    expect(scale.scaled).toBe(true);

    s.remove();
    // The old range described something no longer on the chart, and whatever
    // arrives next may plot nothing at all.
    expect(scale.scaled).toBe(false);
    expect(scale.priceRange()).toEqual({ min: 0, max: 1 });
  });

  it('leaves a manually scaled axis alone, since nothing would recompute it', () => {
    const { chart } = makeChart();
    const s = chart.addSeries('line');
    s.setData(bars(60).map((b) => ({ time: b.time, value: b.close })));
    chart.priceToCoordinate(0); // forces the on-demand autoscale
    const scale = chart.panes()[0].priceScale;
    scale.setPriceRange({ min: 10, max: 20 });
    scale.setAutoScale(false);

    s.remove();
    expect(scale.scaled).toBe(true);
    expect(scale.priceRange()).toEqual({ min: 10, max: 20 });
  });

  it('keeps the range while another series still uses the scale', () => {
    const { chart } = makeChart();
    const a = chart.addSeries('line');
    const b = chart.addSeries('line');
    const data = bars(60).map((x) => ({ time: x.time, value: x.close }));
    a.setData(data);
    b.setData(data);
    chart.priceToCoordinate(0); // forces the on-demand autoscale
    const scale = chart.panes()[0].priceScale;

    a.remove();
    expect(scale.scaled).toBe(true);
  });

  it('gives a table-only indicator a pane with no price ladder', () => {
    const { chart } = makeChart();
    const s = chart.addSeries('candlestick');
    s.setData(bars(400));
    // An oscillator scales the second pane 0..100, then leaves.
    const rsi = chart.addIndicator('rsi');
    chart.priceToCoordinate(0, 1); // forces the on-demand autoscale on the RSI pane
    chart.removeIndicator(rsi.id);
    // Seasonality's only column is all-null: its output is the table.
    chart.addIndicator('seasonality');
    chart.priceToCoordinate(0); // forces the on-demand autoscale
    const pane = chart.panes()[chart.panes().length - 1];
    expect(pane.priceScale.scaled).toBe(false);
  });
});

/**
 * A series addresses its pane by identity, not by the slot it was created in.
 *
 * Slots move: `removeIndicator` prunes the emptied pane, which splices the array
 * so every pane below shifts up one, and `movePane` swaps two entries outright.
 * A series holding the number it was born with then points at a different pane,
 * or past the end of the array.
 *
 * These drive `removeIndicator`, which is the path that actually goes through
 * the series' own teardown closure. Driving `removePane` instead proves nothing:
 * it strips series by walking the pane object it already holds, so it never
 * touches the closure and passes just as happily with the bug in place.
 */
describe('sub-plot indicators survive their pane changing slot', () => {
  const threeSubPlots = (): { chart: Chart; ids: string[] } => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    const ids = ['rsi', 'macd', 'cci'].map((id) => chart.addIndicator(id).id);
    return { chart, ids };
  };

  it('removing the last sub-plot after an earlier one does not throw', () => {
    const { chart, ids } = threeSubPlots();
    expect(chart.panes()).toHaveLength(4);
    // Panes 2 and 3 shift up to 1 and 2 here; their series still name 2 and 3.
    chart.removeIndicator(ids[0]);
    expect(chart.panes()).toHaveLength(3);
    chart.removeIndicator(ids[1]);
    // Was: `this._panes[3]` is undefined, so removeSeries threw on undefined and
    // the teardown aborted half-done -- legend gone, plot still on the chart.
    expect(() => chart.removeIndicator(ids[2])).not.toThrow();
    expect(chart.panes()).toHaveLength(1);
  });

  it('strips its own pane, not whichever one inherited the slot', () => {
    const { chart, ids } = threeSubPlots();
    chart.removeIndicator(ids[0]);
    const survivor = chart.panes()[1]; // was pane 2, holds the second indicator
    const before = survivor.series().length;
    expect(before).toBeGreaterThan(0);
    // The quiet half of the bug: a stale index that still lands on a live pane
    // strips the wrong one, and nothing anywhere reports it.
    chart.removeIndicator(ids[2]);
    expect(survivor.series()).toHaveLength(before);
  });

  it('follows its pane through a move', () => {
    const { chart, ids } = threeSubPlots();
    chart.movePane(1, 1); // panes 1 and 2 swap objects
    const moved = chart.panes()[2];
    const held = moved.series().length;
    expect(held).toBeGreaterThan(0);
    expect(() => chart.removeIndicator(ids[0])).not.toThrow();
    expect(chart.panes().some((p) => p === moved)).toBe(false);
  });
})

describe('a pane index that names no slot', () => {
  // A slot is a whole number of 0 or more. Anything else used to add panes up
  // to it, find none there and throw a TypeError from inside, leaving the
  // stray pane behind on a chart the call never changed.
  it('is refused by addSeries before the chart changes', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(20));
    for (const paneIndex of [1.5, -1, Number.NaN]) {
      expect(() => chart.addSeries('line', { paneIndex })).toThrow(RangeError);
      expect(chart.panes()).toHaveLength(1);
    }
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(20));
    expect(chart.panes()).toHaveLength(2);
  });

  it('is refused by the primitive adders before the chart changes', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(20));
    for (const paneIndex of [1.5, -1, Number.NaN]) {
      expect(() => chart.addPriceLine({ id: 'level', price: 100, color: '#26a69a' }, paneIndex)).toThrow(RangeError);
      expect(() => chart.addPrimitive(new PaneLegend({ id: 'row', title: 'Row', actions: [] }), paneIndex)).toThrow(RangeError);
      expect(chart.panes()).toHaveLength(1);
    }
  });
});
