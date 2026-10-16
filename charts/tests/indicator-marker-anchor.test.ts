/**
 * What `aboveBar` and `belowBar` are measured against.
 *
 * Reported from a live chart: an overlay study wrote its buy marks as `below`
 * and its sell marks as `above`, and both came out through the middle of the
 * candle. The study declares an invisible mid-body column first, so that its
 * marks have a series with a point on every bar, and the marker layer binds to
 * the first plot: "below the bar" was below the mid-body value, which is inside
 * the candle. Every ingredient was behaving as written and the result was
 * wrong, which is why this is a descriptor choice now rather than a rule.
 *
 * A mark that belongs to a line still anchors to the line: an arrow on a moving
 * average sits against the average, and that stays the default.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';

const BARS: Bar[] = [
  { time: 100, open: 10, high: 14, low: 6, close: 12 },
  { time: 200, open: 12, high: 16, low: 8, close: 10 },
];

/** A stand-in series that remembers whether it was asked for a marker layer. */
function fakeSeries(name: string, asked: string[]): SeriesApi {
  return {
    setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
    applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
    createMarkers: () => {
      asked.push(name);
      return { setMarkers: () => {} } as never;
    },
  } as unknown as SeriesApi;
}

function rig(hasPrimary: boolean): { host: IndicatorHost; asked: string[] } {
  const asked: string[] = [];
  const host: IndicatorHost = {
    addIndicatorLegend: () => ({ setOptions: () => {}, setValues: () => {} }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    primarySeries: () => (hasPrimary ? fakeSeries('price', asked) : null),
    addIndicatorSeries: () => fakeSeries('plot', asked),
    addIndicatorLevel: () => ({}) as never,
    removeIndicatorLevel: () => {},
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    sourceBars: () => BARS,
    nextPaneIndex: () => 2,
    setPaneRange: () => {},
    tickSize: () => 0.05,
  };
  return { host, asked };
}

/** One study with one mark, anchored however the caller says. */
function study(
  id: string,
  anchor: 'plot' | 'price' | undefined,
  placement: 'onchart' | 'pane' = 'onchart'
): IndicatorDescriptor {
  return {
    id, name: id, placement, inputs: [],
    ...(anchor === undefined ? {} : { markerAnchor: anchor }),
    plots: [{ key: 'mid', type: 'line', title: 'Mid', style: { color: '#26a69a' } }],
    calc: (b) => ({ mid: b.map((one) => (one.open + one.close) / 2) }),
    markers: () => [
      { time: 200, position: 'belowBar', shape: 'labelUp', size: 'medium', color: '#26a69a', text: 'BUY' },
    ],
  };
}

/** Which series the marker layer was created on. */
function anchorOf(
  id: string,
  anchor: 'plot' | 'price' | undefined,
  hasPrimary = true,
  placement: 'onchart' | 'pane' = 'onchart'
): string {
  const { host, asked } = rig(hasPrimary);
  const inst = new IndicatorInstance(host, study(id, anchor, placement));
  inst.recompute();
  return asked[asked.length - 1] ?? 'none';
}

describe('which series a marker measures against', () => {
  it('anchors to the study\'s own plot by default', () => {
    // Unchanged for every descriptor written before this existed, which is the
    // whole reason it is opt-in.
    expect(anchorOf('anchor-default', undefined)).toBe('plot');
    expect(anchorOf('anchor-explicit-plot', 'plot')).toBe('plot');
  });

  it('anchors to the instrument when the descriptor asks for price', () => {
    // The reported case. Against the behaviour that shipped this is 'plot',
    // and every below mark is drawn inside the candle.
    expect(anchorOf('anchor-price', 'price')).toBe('price');
  });

  it('ignores a price anchor on a study that owns a pane', () => {
    // There are no candles on an oscillator's pane, and the primary series
    // lives on another one with another price scale. Binding the layer there
    // would put the marks on the price pane, where the study that raised them
    // is not, and at prices the oscillator never reaches.
    expect(anchorOf('anchor-own-pane', 'price', true, 'pane')).toBe('plot');
  });

  it('falls back to the plot when there is no primary series', () => {
    // A chart built indicator-first has no candles yet. Drawing the mark
    // against the study's own line is worse than against the candle and far
    // better than not drawing it, which is what returning early would do.
    expect(anchorOf('anchor-no-primary', 'price', false)).toBe('plot');
  });
});
