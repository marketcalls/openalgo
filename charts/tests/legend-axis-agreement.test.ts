/**
 * The legend and the axis name the same number, so they have to spell it the
 * same way.
 *
 * Seen on a live chart after 1.8.9: a Supertrend legend read `1034.0` beside a
 * price axis reading `1029.20`, and a Williams VIX Fix legend read `0.618`
 * beside its own axis reading `0.62`. The two sit inches apart and describe the
 * same quantity, so a reader has to reconcile the difference themselves and has
 * no way to know which one to trust.
 *
 * The cause was a second opinion. The legend worked its format out from the
 * pane's tick, which gets it wrong in both directions: a study pane carries no
 * tick at all (1.8.9 stopped the instrument's reaching it), and a price pane's
 * tick alone knows nothing about the precision floor or a host's own price
 * formatter. The axis already answers all of that, so the legend asks it.
 */
import { describe, it, expect } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import type { LegendValue } from '../src/primitives/pane-legend';

const TICK = 0.05;

const bars = (n = 300): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 1030 + Math.sin(i / 11) * 6;
    return { time: 1735689600 + i * 300, open: c, high: c + 2, low: c - 2, close: c, volume: 100_000 + i * 37 };
  });

/** A chart with an instrument tick, the way a host sets one on symbol load. */
function priced(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(1200, 800);
  chart.addSeries('candlestick').setData(bars());
  chart.setPriceScaleOptions({ minMove: TICK });
  return chart;
}

/** A study on its own pane, spanning a fraction of a point like a percentage. */
registerIndicator({
  id: 'agree-percent', name: 'Percent (test)', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b) => ({ v: b.map((_, i) => 0.05 + (i % 120) / 100) }),
});

/** An overlay, drawn against the price axis, so it is a price. */
registerIndicator({
  id: 'agree-overlay', name: 'Overlay (test)', placement: 'onchart', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b) => ({ v: b.map((x) => x.close) }),
});

/** What the legend was last told to print for an indicator's single plot. */
function legendText(chart: Chart, id: string): string {
  const inst = chart.addIndicator(id);
  inst.updateLegendValues();
  const values = (inst.legend() as unknown as { _values?: LegendValue[] })._values;
  if (values && values.length) return values[0].text;
  // Fall back to reading it off the legend object however it stores them.
  const any = inst.legend() as unknown as Record<string, unknown>;
  for (const k of Object.keys(any)) {
    const v = any[k];
    if (Array.isArray(v) && v.length && typeof (v[0] as LegendValue)?.text === 'string') {
      return (v[0] as LegendValue).text;
    }
  }
  throw new Error('could not read the legend values');
}

describe('the legend prints what the axis prints', () => {
  it('agrees with the price axis for an overlay study', () => {
    const chart = priced();
    const text = legendText(chart, 'agree-overlay');
    const axis = chart.panes()[0].priceScale;
    const last = bars()[bars().length - 1].close;
    // Whatever the axis makes of that price, the legend makes the same.
    expect(text).toBe(axis.format(last));
    // And concretely: a 0.05 tick is two decimals, not one.
    expect(text.split('.')[1]).toHaveLength(2);
  });

  it('agrees with its own axis for a study on its own pane', () => {
    // The reported case. The pane carries no tick since 1.8.9, so the legend
    // used to fall through to a magnitude ladder and print three significant
    // figures where the axis printed two decimals.
    const chart = priced();
    const before = chart.panes().length;
    const text = legendText(chart, 'agree-percent');
    const pane = chart.panes()[before];
    const last = 0.05 + ((bars().length - 1) % 120) / 100;
    expect(text).toBe(pane.priceScale.format(last));
    expect(text).not.toContain('e');
  });

  it('does not fall back to the price pane for a study on another pane', () => {
    // Formatting a percentage in the instrument's paise would be the old bug
    // wearing the other hat.
    const chart = priced();
    const before = chart.panes().length;
    const studyText = legendText(chart, 'agree-percent');
    const last = 0.05 + ((bars().length - 1) % 120) / 100;
    const priceFormat = chart.panes()[0].priceScale.format(last);
    const studyFormat = chart.panes()[before].priceScale.format(last);
    expect(studyText).toBe(studyFormat);
    if (priceFormat !== studyFormat) expect(studyText).not.toBe(priceFormat);
  });

  it('uses the host price formatter, so a volume pane still compacts', () => {
    // A pane with a formatter of its own must win over any tick arithmetic:
    // seven digits of share count in a legend is not a reading.
    const chart = priced();
    const before = chart.panes().length;
    registerIndicator({
      id: 'agree-volume', name: 'Volume (test)', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.volume ?? 0) }),
    });
    const inst = chart.addIndicator('agree-volume');
    chart.panes()[before].priceScale.setPriceFormatter((n) => `${(n / 1e3).toFixed(2)}K`);
    inst.updateLegendValues();
    const values = (inst.legend() as unknown as { _values?: LegendValue[] })._values ?? [];
    expect(values.length).toBeGreaterThan(0);
    expect(values[0].text.endsWith('K')).toBe(true);
  });
});
