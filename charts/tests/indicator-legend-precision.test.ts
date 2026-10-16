/**
 * The legend prints an indicator value at the same precision as the axis
 * beside it.
 *
 * Reported from a live chart: a Supertrend sitting at 1339.70 on an equity read
 * "1340" in the legend while the price axis two inches away read 1339.70. The
 * legend formatter was a magnitude ladder written for volume columns, and one of
 * its rungs rounds anything at or above 1000 to whole numbers. On a price that
 * is not a rounding choice, it is a wrong number: a trader reading a stop off
 * the legend is 0.30 out.
 *
 * The pane's tick is the right authority, because it is the same number the axis
 * formats to and the one the instrument actually trades in.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { LegendValue } from '../src/primitives/pane-legend';

/** A host that records what the legend was asked to print, and knows a tick. */
function rig(source: Bar[], tick: number | undefined) {
  const printed: LegendValue[][] = [];
  const host: IndicatorHost = {
    addIndicatorLegend: () =>
      ({ setOptions: () => {}, setValues: (v: LegendValue[]) => { printed.push(v); } }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    addIndicatorSeries: (): SeriesApi => ({
      setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
      applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
      createMarkers: () => ({ setMarkers: () => {} }) as never,
    }),
    addIndicatorLevel: () => ({}) as never,
    removeIndicatorLevel: () => {},
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    sourceBars: () => source,
    nextPaneIndex: () => 2,
    setPaneRange: () => {},
    tickSize: () => tick,
  };
  return { host, printed };
}

const bars = (closes: number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1000 + i * 60, open: c, high: c, low: c, close: c }));

/** Emits one constant column, so the assertion is purely about formatting. */
function constantAt(id: string, value: number): IndicatorDescriptor {
  return {
    id, name: id, placement: 'onchart',
    inputs: [{ key: 'color', type: 'color', label: 'Color', default: '#26a69a' }],
    plots: [{ key: 'v', type: 'line', title: id, colorKey: 'color' }],
    calc: (b) => ({ v: b.map(() => value) }),
  };
}

function legendText(value: number, tick: number | undefined): string {
  const id = `legend-precision-${value}-${String(tick)}`;
  const source = bars([100, 101, 102]);
  const { host, printed } = rig(source, tick);
  const inst = new IndicatorInstance(host, constantAt(id, value));
  inst.recompute();
  inst.updateLegendValues();
  const last = printed[printed.length - 1];
  return last && last.length ? last[0].text : '';
}

describe('legend precision follows the pane tick', () => {
  it('keeps the paise on a four figure price', () => {
    // The reported case. 1339.70 must not become 1340.
    expect(legendText(1339.7, 0.05)).toBe('1339.70');
  });

  it('follows a coarser tick down to one decimal', () => {
    // A 0.10 tick implies one decimal, which is what the axis prints too.
    expect(legendText(1339.7, 0.1)).toBe('1339.7');
  });

  it('is unchanged below the thousand mark, where the old ladder was already right', () => {
    expect(legendText(24.55, 0.05)).toBe('24.55');
  });

  it('falls back to the magnitude ladder when the pane has no tick', () => {
    // A volume or open-interest pane sets no minMove. Compacting is right there:
    // the trailing digits of 12345678 are noise, not precision.
    expect(legendText(12345678, undefined)).toBe('12.35M');
    expect(legendText(1339.7, undefined)).toBe('1340');
  });

  it('ignores a zero tick, which means "infer", not "no decimals"', () => {
    // PriceScale treats minMove 0 as "work the precision out from the range", so
    // it is not a step and must not be read as one.
    expect(legendText(1339.7, 0)).toBe('1340');
  });
});
