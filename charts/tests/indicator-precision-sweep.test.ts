/**
 * The precision rule, checked against every registered indicator rather than
 * the two that were reported.
 *
 * "Williams VIX Fix reads 0.6 where it should read 0.61" was one symptom of a
 * rule that was wrong for a whole class: the host pushes the instrument's tick
 * size down chart-wide, and it used to land on every pane, including panes
 * measuring things the instrument's tick says nothing about. An RSI is a
 * dimensionless 0..100 band; a percentage study is a percentage. Fixing the two
 * that were noticed would have left the other sixty-three quietly wrong.
 *
 * So this sweeps the registry. It is deliberately a property test rather than a
 * table of expected decimals per indicator: a table would need editing every
 * time an indicator is added, and the point of keying the rule on the pane is
 * that nothing needs editing, custom descriptors included.
 */
import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins
import { Chart } from '../src/core/chart';
import { registeredIndicators, getIndicator, registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

/** A tick a real instrument would carry, and one that formats to two decimals. */
const TICK = 0.05;

/** Enough bars, and enough shape, for a long-lookback study to produce values. */
function bars(n = 400): Bar[] {
  const out: Bar[] = [];
  let p = 1300;
  for (let i = 0; i < n; i++) {
    const o = p;
    const c = o + Math.sin(i / 13) * 9 + Math.cos(i / 7) * 4;
    out.push({
      time: 1735689600 + i * 300,
      open: o, high: Math.max(o, c) + 2.5, low: Math.min(o, c) - 2.5, close: c,
      volume: 100_000 + (i % 37) * 5_000,
    });
    p = c;
  }
  return out;
}

function chartWithTick(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(1200, 800);
  chart.addSeries('candlestick').setData(bars());
  // The host gesture that caused the defect: the symbol loads and its tick is
  // pushed down chart-wide.
  chart.setPriceScaleOptions({ minMove: TICK });
  return chart;
}

// Ids only: registeredIndicators() hands back whole descriptors, and vitest
// prints the argument as the case name.
const ALL = registeredIndicators().map((d) => d.id).sort();

describe('every registered indicator lands on a scale that quotes what it measures', () => {
  it('has indicators to sweep, so a broken registry cannot pass this file', () => {
    expect(ALL.length).toBeGreaterThan(90);
  });

  it.each(ALL)('%s', (id) => {
    const descriptor = getIndicator(id);
    const chart = chartWithTick();
    const inst = chart.addIndicator(id);
    const scale = chart.panes()[inst.paneIndex].priceScale;

    if (descriptor.placement === 'onchart') {
      // Drawn against the price axis, so it is a price and must agree with it.
      // A Supertrend that reads 1339.7 where the axis reads 1339.70 is the
      // number a trader places a stop at, off by a rounding nobody chose.
      expect(inst.paneIndex).toBe(0);
      expect(scale.options.minMove).toBe(TICK);
      expect(scale.format(1339.7)).toBe('1339.70');
      return;
    }

    // Its own pane: the instrument's tick is not its unit and must not reach it.
    expect(inst.paneIndex).toBeGreaterThan(0);
    expect(scale.options.minMove).toBe(0);
    // And the span alone is not enough, so the floor is in place. Whether the
    // floor actually applies depends on the pane's magnitude, which is the
    // indicator's business; what every study pane must carry is the intent.
    expect(scale.options.minPrecision).toBe(2);
  });
});

describe('a custom descriptor inherits the rule with nothing declared', () => {
  it('gets the study-pane treatment on a pane of its own', () => {
    registerIndicator({
      id: 'sweep-custom-pane', name: 'Custom (test)', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      // Spanning 0..1.19, the shape of the percentage study that was reported.
      calc: (b) => ({ v: b.map((_, i) => (i % 120) / 100) }),
    });
    const chart = chartWithTick();
    const inst = chart.addIndicator('sweep-custom-pane');
    const scale = chart.panes()[inst.paneIndex].priceScale;
    expect(scale.options.minMove).toBe(0);
    expect(scale.format(0.6123)).toBe('0.61');
  });

  it('still gets more than the floor where its own span is tighter', () => {
    // The floor is a minimum, not a target. A study living inside a tenth of a
    // point needs three decimals, and asking for two would round its whole
    // range into a handful of rungs.
    registerIndicator({
      id: 'sweep-custom-tight', name: 'Custom Tight (test)', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((_, i) => 0.2 + (i % 50) / 1000) }),
    });
    const chart = chartWithTick();
    const inst = chart.addIndicator('sweep-custom-tight');
    expect(chart.panes()[inst.paneIndex].priceScale.format(0.21234)).toBe('0.2123');
  });

  it('gets the instrument tick when it overlays the candles', () => {
    registerIndicator({
      id: 'sweep-custom-overlay', name: 'Custom Overlay (test)', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
    });
    const chart = chartWithTick();
    const inst = chart.addIndicator('sweep-custom-overlay');
    expect(inst.paneIndex).toBe(0);
    expect(chart.panes()[0].priceScale.format(1339.7)).toBe('1339.70');
  });
});
