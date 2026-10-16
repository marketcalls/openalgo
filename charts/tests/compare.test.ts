/**
 * Multi-symbol comparison: aligning a second instrument onto the primary
 * series' bars, keeping it off the primary's price axis, and making the two
 * readable together.
 */
import { describe, it, expect } from 'vitest';
import type { PriceScale } from '../src/scale/price-scale';
import type { PaneRenderContext } from '../src/core/pane';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { alignToPrimary } from '../src/compare/align';
import { addComparison, comparisonController, type ComparisonHandle } from '../src/compare/controller';
import type { Bar, SeriesDataItem } from '../src/model/bar';
import { ReplayController } from '../src/replay/controller';

const DAY = 86400;
const T0 = 1700000000;

const at = (day: number): number => T0 + day * DAY;

/** A flat OHLC bar, so extents and close are the same number. */
const bar = (day: number, value: number): Bar => ({
  time: at(day), open: value, high: value, low: value, close: value,
});

/** `count` bars starting at `from`, growing by `stepPct` of the start each bar. */
function ramp(start: number, count: number, endValue: number, fromDay = 0): Bar[] {
  const step = (endValue - start) / Math.max(1, count - 1);
  return Array.from({ length: count }, (_, i) => bar(fromDay + i, start + step * i));
}

/**
 * A chart that paints synchronously, so a frame (and with it the autoscale pass
 * and the comparison's scale mirror) has run by the time a call returns.
 */
function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

function loaded(primary: readonly Bar[]): { chart: Chart; pane: ReturnType<Chart['panes']>[number] } {
  const chart = makeChart();
  const series = chart.addSeries('candlestick');
  series.setData(primary);
  return { chart, pane: chart.panes()[0] };
}

describe('alignToPrimary', () => {
  it('projects the comparison onto the primary bars in both directions of mismatch', () => {
    // The primary trades days 0..4. The comparison is shut on day 2 (its own
    // exchange holiday) and open on day 9, when the primary is shut.
    const primary = [bar(0, 100), bar(1, 101), bar(2, 102), bar(3, 103), bar(4, 104)];
    const comparison: SeriesDataItem[] = [
      bar(0, 1000), bar(1, 1010), bar(3, 1030), bar(4, 1040),
      bar(9, 1090),
      { time: at(1) + 3600, value: 1015 }, // a stray intraday print
    ];

    const { items, alignment } = alignToPrimary(primary, comparison);

    expect(alignment).toEqual({ bars: 5, matched: 4, gaps: 1, dropped: 2 });
    expect(items.map((i) => i.time)).toEqual([at(0), at(1), at(2), at(3), at(4)]);
    // Day 2 holds its index but draws nothing: whitespace, not a value carried
    // forward and not a straight line across the holiday.
    expect(items[2]).toEqual({ time: at(2) });
    // Nothing the primary has no bar for reaches the chart, at any resolution.
    expect(items.some((i) => i.time === at(9) || i.time === at(1) + 3600)).toBe(false);
  });

  it('passes the comparison bar through whole and keeps the last of a repeated time', () => {
    const primary = [bar(0, 100), bar(1, 101)];
    const comparison = [
      { time: at(0), open: 1, high: 4, low: 0.5, close: 3 },
      bar(1, 1010),
      bar(1, 1011), // a correction for the same bar
    ];
    const { items, alignment } = alignToPrimary(primary, comparison);
    expect(items[0]).toEqual({ time: at(0), open: 1, high: 4, low: 0.5, close: 3 });
    expect(items[1]).toEqual(bar(1, 1011));
    expect(alignment.dropped).toBe(0); // the repeat is a replacement, not a drop
  });

  it('reports no coverage rather than throwing when there is nothing to align to', () => {
    expect(alignToPrimary([], [bar(0, 10)])).toEqual({
      items: [], alignment: { bars: 0, matched: 0, gaps: 0, dropped: 1 },
    });
    expect(alignToPrimary([bar(0, 10)], []).alignment).toEqual({ bars: 1, matched: 0, gaps: 1, dropped: 0 });
  });

  it('lets the latest duplicate retract a comparison reading to a gap', () => {
    const primary = [bar(0, 100), bar(1, 101)];
    const comparison: SeriesDataItem[] = [
      bar(0, 10), bar(9, 90), { time: at(0) }, { time: at(9) },
      { time: at(1) }, bar(1, 11),
    ];
    const snapshot = comparison.map(item => ({ ...item }));
    expect(alignToPrimary(primary, comparison)).toEqual({
      items: [{ time: at(0) }, bar(1, 11)],
      alignment: { bars: 2, matched: 1, gaps: 1, dropped: 0 },
    });
    expect(comparison).toEqual(snapshot);
  });
});

describe('comparison series placement', () => {
  it('goes on the hidden overlay scale and leaves the primary axis alone', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const before = pane.priceScale.priceRange();

    const handle = addComparison(chart, {
      symbol: 'BANKNIFTY',
      bars: ramp(45000, 11, 46000),
      color: '#f0b90b',
    });

    const records = pane.series();
    expect(records).toHaveLength(2);
    expect(records[1].scaleId).toBe('');
    expect(handle.priceScale()).not.toBe(pane.priceScale);
    // A 45,000 instrument on a 100 chart: the primary's ladder does not move.
    expect(pane.priceScale.priceRange()).toEqual(before);
  });

  it('adds no logical indices of its own to the shared time axis', () => {
    const { chart } = loaded(ramp(100, 5, 104));
    const axis = chart.dataLayer.length;
    const handle = addComparison(chart, {
      symbol: 'BANKNIFTY',
      bars: [...ramp(45000, 5, 45400), bar(20, 46000), bar(21, 46100)],
    });
    expect(chart.dataLayer.length).toBe(axis);
    expect(handle.alignment().dropped).toBe(2);
  });

  it('falls back to the left axis when the pane overlay already carries volume', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    chart.addSeries('histogram', { priceScaleId: '', style: { color: '#888' } });

    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 46000) });

    expect(pane.series()[2].scaleId).toBe('left');
    expect(handle.priceScale()).not.toBe(pane.priceScale);
  });
});

describe('comparison mode', () => {
  it('switches the pane while comparisons are on it and restores the mode after the last one', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    expect(pane.priceScale.options.mode).toBe('linear');

    const a = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 46000) });
    expect(pane.priceScale.options.mode).toBe('percentage');
    expect(a.priceScale().options.mode).toBe('percentage');

    const b = addComparison(chart, { symbol: 'FINNIFTY', bars: ramp(20000, 11, 20500) });
    a.remove();
    expect(pane.priceScale.options.mode).toBe('percentage'); // one is still on

    b.remove();
    expect(pane.priceScale.options.mode).toBe('linear');
    expect(pane.series()).toHaveLength(1);
  });

  it('honours an explicit mode and leaves the pane alone for none', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const controller = comparisonController(chart, { mode: 'indexed-to-100' });
    const handle = controller.add({ symbol: 'BANKNIFTY', bars: ramp(45000, 11, 46000) });
    expect(pane.priceScale.options.mode).toBe('indexed-to-100');

    controller.setMode('none');
    expect(pane.priceScale.options.mode).toBe('linear');
    expect(handle.priceScale().options.mode).toBe('linear');

    controller.setMode('percentage');
    expect(pane.priceScale.options.mode).toBe('percentage');
    controller.clear();
    expect(pane.priceScale.options.mode).toBe('linear');
  });

  it('applies the options of a later request to the controller the chart already has', () => {
    // addComparison creates the chart's controller with the defaults. A host
    // that asks for the controller afterwards with a baseline or a mode gets
    // them applied, as a second attachSessionShading call applies its options,
    // rather than silently keeping the defaults.
    const { chart, pane } = loaded(ramp(100, 11, 110));
    addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 46000) });
    const controller = comparisonController(chart, { mode: 'indexed-to-100', baseline: 'common' });
    expect(controller).toBe(comparisonController(chart));
    expect(controller.mode).toBe('indexed-to-100');
    expect(controller.baseline).toBe('common');
    expect(pane.priceScale.options.mode).toBe('indexed-to-100');
    // Asking with no options, or with only one of them, changes nothing else.
    comparisonController(chart, { baseline: 'first-visible' });
    expect(controller.mode).toBe('indexed-to-100');
    expect(controller.baseline).toBe('first-visible');
  });

  it('keeps a mode the user changed underneath it', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 46000) });
    pane.priceScale.setOptions({ mode: 'logarithmic' });
    handle.remove();
    expect(pane.priceScale.options.mode).toBe('logarithmic');
  });
});

describe('comparable coordinates', () => {
  /** y of the comparison's last value, and of the primary's last close. */
  function ends(handle: ComparisonHandle, pane: ReturnType<Chart['panes']>[number], value: number, close: number): [number, number] {
    return [handle.priceScale().priceToY(value), pane.priceScale.priceToY(close)];
  }

  it('gives multiple instruments independent baselines on the same percentage ladder', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const a = addComparison(chart, { symbol: 'A', bars: ramp(1000, 11, 1100) });
    const b = addComparison(chart, { symbol: 'B', bars: ramp(50000, 11, 55000) });
    expect(a.priceScale()).not.toBe(b.priceScale());
    for (const [handle, start, end] of [[a, 1000, 1100], [b, 50000, 55000]] as const) {
      expect(handle.priceScale().priceToY(start)).toBeCloseTo(pane.priceScale.priceToY(100), 6);
      expect(handle.priceScale().priceToY(end)).toBeCloseTo(pane.priceScale.priceToY(110), 6);
    }
    a.remove();
    expect(b.priceScale().priceToY(55000)).toBeCloseTo(pane.priceScale.priceToY(110), 6);
    b.remove();
    expect(pane.priceScale.options.mode).toBe('linear');
    expect(pane.scales()).toHaveLength(2); // primary and the retained legacy empty overlay
  });

  it('does not take a left axis or volume scale occupied by another source', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const volume = chart.addSeries('histogram', { priceScaleId: '' });
    volume.setData(ramp(100000, 11, 120000));
    const left = chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(ramp(200, 11, 220));
    const before = left.priceScale().priceRange();
    const handle = addComparison(chart, { symbol: 'A', bars: ramp(50000, 11, 55000) });
    expect(handle.priceScale()).not.toBe(left.priceScale());
    expect(handle.priceScale()).not.toBe(volume.priceScale());
    expect(left.priceScale().priceRange()).toEqual(before);
    expect(left.priceScale().options.mode).toBe('linear');
    expect(handle.priceScale().priceToY(55000)).toBeCloseTo(pane.priceScale.priceToY(110), 6);
  });

  it('lands two instruments with different absolute prices on the same pixel for the same move', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110)); // primary +10%
    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 49500) }); // +10%

    const [comparison, primary] = ends(handle, pane, 49500, 110);
    expect(comparison).toBeCloseTo(primary, 6);
    // ...and they start together too, which is what "rebased to the left edge" means.
    expect(handle.priceScale().priceToY(45000)).toBeCloseTo(pane.priceScale.priceToY(100), 6);
  });

  it('draws a smaller move below a bigger one instead of filling the pane with both', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110)); // primary +10%
    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 11, 47250) }); // +5%

    const [comparison, primary] = ends(handle, pane, 47250, 110);
    // Lower on screen is a larger y. Independent autoscales would have put both
    // at the top of the pane, which is the lie this mirror exists to prevent.
    expect(comparison).toBeGreaterThan(primary + 1);
    // Exactly where the primary would sit if it had gained 5%.
    expect(comparison).toBeCloseTo(pane.priceScale.priceToY(105), 6);
  });

  it('leaves each instrument on its own autoscale in mode none', () => {
    const { chart, pane } = loaded(ramp(100, 11, 110));
    const controller = comparisonController(chart, { mode: 'none' });
    const handle = controller.add({ symbol: 'BANKNIFTY', bars: ramp(45000, 11, 47250) });
    // No shared ladder: the comparison fills its own pane-height band, so its
    // top value sits where the primary's top value does despite the +5% / +10%.
    expect(handle.priceScale().priceToY(47250)).toBeCloseTo(pane.priceScale.priceToY(110), 6);
  });
});

describe('keeping up with the primary series', () => {
  it('replaces aligned timestamps when a same-length primary history changes', () => {
    const { chart } = loaded(ramp(100, 3, 102));
    // Another source keeps the global axis unchanged during the replacement.
    chart.addSeries('line', { priceScaleId: 'left' }).setData(ramp(10, 6, 15));
    const handle = addComparison(chart, { symbol: 'A', bars: ramp(1000, 6, 1050) });
    expect(chart.dataLayer.length).toBe(6);
    chart.primarySeries()!.setData(ramp(103, 3, 105, 3));
    expect(handle.series.getData().map(item => item.time)).toEqual([at(3), at(4), at(5)]);
    expect(chart.dataLayer.length).toBe(6);
  });

  it('admits a live comparison close only when its primary timestamp arrives', () => {
    const { chart } = loaded(ramp(100, 3, 102));
    const handle = addComparison(chart, { symbol: 'A', bars: ramp(1000, 4, 1030) });
    expect(handle.barAt(at(3))).toBeNull();
    chart.primarySeries()!.update(bar(3, 103));
    expect(handle.barAt(at(3))?.close).toBe(1030);
    handle.setBars(ramp(1000, 4, 1035));
    expect(handle.barAt(at(3))?.close).toBe(1035);
    expect(handle.series.getData()).toHaveLength(4);
    expect(chart.dataLayer.length).toBe(4);
  });

  it('releases future timestamps when replay truncates the primary', () => {
    const { chart } = loaded(ramp(100, 6, 105));
    const handle = addComparison(chart, { symbol: 'A', bars: ramp(1000, 6, 1050) });
    const replay = new ReplayController(chart, { startIndex: 2 });
    expect(handle.series.getData().map(item => item.time)).toEqual([at(0), at(1), at(2)]);
    expect(chart.dataLayer.length).toBe(3);
    replay.seek(0);
    expect(chart.dataLayer.length).toBe(1);
    replay.stop();
    expect(handle.series.getData()).toHaveLength(6);
  });

  it('withholds a forming replay candle close, including comparisons added during replay', () => {
    const { chart } = loaded(ramp(100, 3, 102));
    const handle = addComparison(chart, { symbol: 'A', bars: ramp(1000, 3, 1020) });
    const subBars = Array.from({ length: 6 }, (_, index) => ({ ...bar(0, 100 + index), time: T0 + index * DAY / 2 }));
    let disclosed = false;
    const replay = new ReplayController(chart, { startIndex: 0, subBars, onFrame: state => {
      if (state.subIndex < state.subSteps - 1) {
        disclosed ||= handle.series.getData().some(item => item.time === state.bar?.time && Number.isFinite(item.close));
      }
    } });
    replay.step();
    expect(disclosed).toBe(false);
    const during = addComparison(chart, { symbol: 'B', bars: ramp(5000, 3, 5100) });
    expect(during.series.getData().find(item => item.time === at(1))?.close).toBeNaN();
    replay.step();
    expect(handle.series.getData().find(item => item.time === at(1))?.close).toBe(1010);
    replay.stop();
    expect(during.series.getData()).toHaveLength(3);
  });
  it('re-aligns when the primary gains bars', () => {
    const chart = makeChart();
    const primary = chart.addSeries('candlestick');
    primary.setData(ramp(100, 5, 104));
    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 10, 45900) });
    expect(handle.alignment()).toEqual({ bars: 5, matched: 5, gaps: 0, dropped: 5 });

    primary.setData(ramp(100, 10, 109)); // history paged in
    expect(handle.alignment()).toEqual({ bars: 10, matched: 10, gaps: 0, dropped: 0 });
  });

  it('replaces the instrument bars through setBars', () => {
    const { chart } = loaded(ramp(100, 5, 104));
    const handle = addComparison(chart, { symbol: 'BANKNIFTY', bars: [bar(0, 45000), bar(1, 45100)] });
    expect(handle.alignment()).toEqual({ bars: 5, matched: 2, gaps: 3, dropped: 0 });

    handle.setBars(ramp(45000, 5, 45400));
    expect(handle.alignment()).toEqual({ bars: 5, matched: 5, gaps: 0, dropped: 0 });
    expect(handle.series.getData()).toHaveLength(5);
  });
});

describe('common comparison baseline', () => {
  it('anchors every visible instrument to the same available timestamp', () => {
    const { chart, pane } = loaded(ramp(100, 4, 130));
    const controller = comparisonController(chart, { baseline: 'common' });
    const a = controller.add({ symbol: 'A', bars: [bar(0, 200), bar(2, 300), bar(3, 330)] });
    const b = controller.add({ symbol: 'B', bars: [bar(1, 900), bar(2, 1000), bar(3, 1100)] });
    expect(controller.baselineTime()).toBe(at(2));
    expect(pane.priceScale.baseline).toBe(120);
    expect(a.priceScale().baseline).toBe(300);
    expect(b.priceScale().baseline).toBe(1000);
    expect(a.priceScale().priceToY(330)).toBeCloseTo(b.priceScale().priceToY(1100), 6);
    expect(a.priceScale().priceToY(330)).toBeCloseTo(pane.priceScale.priceToY(132), 6);
    controller.setMode('indexed-to-100');
    expect(a.priceScale().priceToY(300)).toBeCloseTo(pane.priceScale.priceToY(120), 6);
  });

  it('keeps the old first-visible policy unless a host opts into a shared timestamp', () => {
    const { chart, pane } = loaded(ramp(100, 4, 130));
    const controller = comparisonController(chart);
    const source = controller.add({ symbol: 'A', bars: [bar(2, 300), bar(3, 330)] });
    expect(pane.priceScale.baseline).toBe(100);
    controller.setBaseline('common');
    expect(pane.priceScale.baseline).toBe(120);
    controller.setBaseline('first-visible');
    expect(pane.priceScale.baseline).toBe(100);
    expect(source.priceScale().baseline).toBe(300);
  });

  it('shows gaps without a shared start and recovers as visibility or data changes', () => {
    const { chart } = loaded(ramp(100, 2, 110));
    const controller = comparisonController(chart, { baseline: 'common' });
    const a = controller.add({ symbol: 'A', bars: [bar(0, 200)] });
    const b = controller.add({ symbol: 'B', bars: [bar(1, 900)] });
    expect(controller.baselineTime()).toBeNull();
    expect(a.barAt?.(at(0))).toBeNull();
    expect(a.series.getData().every(item => !Number.isFinite(item.close))).toBe(true);
    expect(b.series.getData().every(item => !Number.isFinite(item.close))).toBe(true);
    b.series.applyOptions({ visible: false });
    expect(controller.baselineTime()).toBe(at(0));
    expect(a.series.getData()[0].close).toBe(200);
    expect(a.barAt?.(at(0))?.close).toBe(200);
    b.series.applyOptions({ visible: true });
    expect(controller.baselineTime()).toBeNull();
    b.setBars([bar(0, 800), bar(1, 900)]);
    expect(controller.baselineTime()).toBe(at(0));
    expect(a.series.getData()[0].close).toBe(200);
  });

  it('recomputes the common start when the visible window moves', () => {
    const { chart } = loaded(ramp(100, 6, 150));
    const controller = comparisonController(chart, { baseline: 'common' });
    const a = controller.add({ symbol: 'A', bars: [bar(0, 200), bar(4, 300), bar(5, 330)] });
    controller.add({ symbol: 'B', bars: [bar(1, 900), bar(4, 1000), bar(5, 1100)] });
    chart.setVisibleLogicalRange({ from: 0, to: 2 });
    expect(controller.baselineTime()).toBeNull();
    expect(a.series.getData().every(item => !Number.isFinite(item.close))).toBe(true);
    chart.setVisibleLogicalRange({ from: 3, to: 5 });
    expect(controller.baselineTime()).toBe(at(4));
    expect(a.series.getData().find(item => item.time === at(4))?.close).toBe(300);
  });

  it('fits larger percentage moves while preserving a manually set primary range', () => {
    const { chart, pane } = loaded(ramp(100, 4, 103));
    const controller = comparisonController(chart, { baseline: 'common' });
    const a = controller.add({ symbol: 'A', bars: ramp(1000, 4, 1500) });
    const y = a.priceScale().priceToY(1500);
    expect(y).toBeGreaterThan(0);
    expect(y).toBeLessThan(a.priceScale().height);
    pane.priceScale.setAutoScale(false);
    pane.priceScale.setPriceRange({ min: 90, max: 110 });
    a.setBars(ramp(1000, 4, 2000));
    expect(pane.priceScale.priceRange()).toEqual({ min: 90, max: 110 });
  });

  it('fits relative moves across missing prints without contaminating the range', () => {
    const { chart } = loaded(ramp(100, 3, 102));
    const controller = comparisonController(chart, { baseline: 'common' });
    const source = controller.add({ symbol: 'A', bars: [bar(0, 1000), bar(2, 1500)] });
    expect(source.priceScale().priceToY(1500)).toBeGreaterThan(0);
  });

  it('keeps equal returns on equal pixels when the primary axis is inverted', () => {
    const { chart, pane } = loaded(ramp(100, 3, 110));
    const controller = comparisonController(chart, { baseline: 'common' });
    const source = controller.add({ symbol: 'A', bars: ramp(1000, 3, 1100) });
    chart.setPriceScaleOptions({ inverted: true });
    expect(source.priceScale().priceToY(1100)).toBeCloseTo(pane.priceScale.priceToY(110), 6);
    controller.setMode('none');
    expect(source.priceScale().options.inverted).toBe(false);
  });

  it('uses positive finite anchor prices and releases suppressed data in mode none', () => {
    const { chart } = loaded(ramp(100, 2, 110));
    const controller = comparisonController(chart, { baseline: 'common' });
    const source = controller.add({ symbol: 'A', bars: [bar(0, 0), bar(1, -10)] });
    expect(controller.baselineTime()).toBeNull();
    expect(source.series.getData().every(item => !Number.isFinite(item.close))).toBe(true);
    controller.setMode('none');
    expect(source.series.getData().map(item => item.close)).toEqual([0, -10]);
  });

  it('moves the common baseline when a duplicate correction retracts its reading', () => {
    const { chart } = loaded(ramp(100, 3, 110));
    const controller = comparisonController(chart, { baseline: 'common' });
    const source = controller.add({ symbol: 'A', bars: ramp(1000, 3, 1100) });
    expect(controller.baselineTime()).toBe(at(0));
    source.setBars([...ramp(1000, 3, 1100), { time: at(0) }]);
    expect(controller.baselineTime()).toBe(at(1));
    expect(Number.isNaN(source.series.getData()[0].close)).toBe(true);
    expect(source.alignment()).toEqual({ bars: 3, matched: 2, gaps: 1, dropped: 0 });
    chart.destroy();
  });
});

describe('controller bookkeeping', () => {
  it('lists in insertion order and is idempotent on remove', () => {
    const { chart } = loaded(ramp(100, 5, 104));
    const a = addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 5, 45400) });
    const b = addComparison(chart, { symbol: 'FINNIFTY', bars: ramp(20000, 5, 20400) });
    expect(a.list().map((h) => h.symbol)).toEqual(['BANKNIFTY', 'FINNIFTY']);

    expect(comparisonController(chart).remove(a)).toBe(true);
    expect(comparisonController(chart).remove(a)).toBe(false);
    a.remove(); // no throw
    expect(b.list().map((h) => h.symbol)).toEqual(['FINNIFTY']);
  });

  it('refuses a comparison with nothing to align against', () => {
    const chart = makeChart();
    expect(() => addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 5, 45400) }))
      .toThrow(/primary series/);
  });

  it('shares one controller per chart and drops it on destroy', () => {
    const { chart } = loaded(ramp(100, 5, 104));
    const controller = comparisonController(chart);
    expect(comparisonController(chart)).toBe(controller);
    addComparison(chart, { symbol: 'BANKNIFTY', bars: ramp(45000, 5, 45400) });
    controller.destroy();
    expect(controller.list()).toHaveLength(0);
    expect(comparisonController(chart)).not.toBe(controller);
  });

  it('releases handles when the chart is destroyed before the host controller', () => {
    const { chart } = loaded(ramp(100, 5, 104));
    const controller = comparisonController(chart, { baseline: 'common' });
    const handle = controller.add({ symbol: 'A', bars: ramp(1000, 5, 1040) });
    expect(handle.barAt(at(0))?.close).toBe(1000);
    chart.destroy();
    expect(controller.list()).toEqual([]);
    expect(handle.barAt(at(0))).toBeNull();
    expect(() => {
      handle.setBars(ramp(2000, 5, 2040));
      handle.remove();
      controller.realign();
      controller.sync();
      controller.destroy();
    }).not.toThrow();
    expect(() => controller.add({ symbol: 'B', bars: [] })).toThrow(/destroyed/);
  });
});

describe('regressions found by the browser pass, not by unit tests', () => {
  /**
   * Both of these shipped green: the model was right and every assertion about it
   * passed, while the pixels were wrong. They are pinned here at the level the
   * bugs actually lived at, which is the scale, not the drawing.
   */
  const bars = (n: number, base: number): Bar[] =>
    Array.from({ length: n }, (_, i) => {
      const c = base + Math.sin(i / 5) * base * 0.05 + i * (base * 0.001);
      return { time: 1700000000 + i * 86400, open: c, high: c * 1.01, low: c * 0.99, close: c, volume: 1000 };
    });

  const chartWith = (): { chart: Chart; handle: ComparisonHandle } => {
    // makeChart applies a real size and a synchronous raf. Without both, every
    // scale stays on the 0..1 placeholder and an assertion about ranges passes
    // for the wrong reason.
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(200, 400));
    const handle = addComparison(chart, {
      symbol: 'OTHER',
      bars: bars(200, 90) as SeriesDataItem[],
    });
    return { chart, handle };
  };

  it('leaves the overlay on its own range once a rebasing mode is switched off', () => {
    // The mirror used to gate on "a baseline exists". The autoscale pass only
    // refreshes a baseline in a rebasing mode but never cleared it on the way
    // out, so the stale value kept the overlay pinned to a percentage ladder
    // the user had already turned off, and the line did not move a pixel.
    const { chart } = chartWith();
    const ctrl = comparisonController(chart);
    const pane = chart.panes()[0];
    const overlay = pane.scaleOf(pane.series()[1]);

    // Drive the pass directly: priceToCoordinate only measures the right scale,
    // and the bug lives on the overlay.
    ctrl.setMode('percentage');
    pane.autoscale(chartRenderContext(chart));
    const mirrored = overlay.priceRange();

    ctrl.setMode('none');
    pane.autoscale(chartRenderContext(chart));
    const own = overlay.priceRange();

    expect(own).not.toEqual(mirrored);
    // Back on its own data: the comparison is built around 90, not around 400.
    expect(own.max).toBeLessThan(200);
  });

  it('clears a stale baseline when the mode stops rebasing', () => {
    const scale = chart0Scale();
    scale.setOptions({ mode: 'percentage' });
    scale.setBaseline(123.45);
    expect(scale.baseline).toBe(123.45);

    scale.setOptions({ mode: 'linear' });
    expect(scale.baseline).toBeNull();
  });

  it('corrects the overlay range before the axis is painted, not after', () => {
    // The mirror ran from the primitive's draw(), but both price axes are
    // painted near the top of paintBase, so the left ladder was labelled from
    // the previous frame's range. On a chart that had stopped repainting, the
    // corrected range was never drawn at all.
    const { chart } = chartWith();
    comparisonController(chart).setMode('percentage');

    const pane = chart.panes()[0];
    const overlay = pane.scaleOf(pane.series()[1]);
    // One autoscale pass must be enough. If the correction needed a second
    // frame, this range would still be the comparison's own.
    pane.autoscale(chartRenderContext(chart));
    const after = overlay.priceRange();

    const primary = pane.priceScale.priceRange();
    const k = (overlay.baseline ?? 1) / (pane.priceScale.baseline ?? 1);
    expect(after.min).toBeCloseTo(primary.min * k, 6);
    expect(after.max).toBeCloseTo(primary.max * k, 6);
  });

  it('autoscales against the context the paint loop gives the bottom pane', () => {
    // The helper below stands in for the paint loop. If it drifted, the
    // autoscale assertions above would compare against a taller plot than any
    // frame lays out.
    const { chart } = chartWith();
    expect(chartRenderContext(chart).showTimeAxis).toBe(true);
  });

  function chart0Scale(): PriceScale {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(50, 100));
    return chart.panes()[0].priceScale;
  }

  function chartRenderContext(chart: Chart): PaneRenderContext {
    // The pane needs the same context the paint loop builds. Reach for the
    // private builder rather than reconstructing it and drifting from it, and
    // borrow its own signature so a change to it fails the typecheck here.
    return (chart as unknown as { _renderContext: Chart['_renderContext'] })._renderContext(0);
  }
});
