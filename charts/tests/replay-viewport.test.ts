/**
 * Shrinking the primary series must leave the chart's geometry consistent with
 * its data before the call returns.
 *
 * Reported from a live terminal: pressing Replay showed an empty chart. The
 * data was there and the price axis was measured correctly; the viewport was
 * ~280 bars to the left of every bar.
 *
 * The cause is that an indicator's plots are series in the same data layer, so
 * `dataLayer.baseIndex` counts them. Deferring indicator recompute to the frame
 * (1.8.5) meant that after replay truncated the price series to a prefix, the
 * indicator's own series was still at full length for the rest of the turn, and
 * `baseIndex` with it. A host that truncates and then positions the viewport in
 * the same turn -- which is exactly what entering replay does -- converted its
 * logical range against a base index ~280 bars too high.
 *
 * Growth is safe and stays deferred: an appended bar makes the price series the
 * longest, so `baseIndex` is right even with the indicator a bar behind. Only a
 * shrink leaves a stale series holding the base index up, so only the wholesale
 * `setData` path flushes.
 */
import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins
import { Chart } from '../src/core/chart';
import { ReplayController } from '../src/replay/controller';
import { registerIndicator, getIndicator } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

/** A chart whose frames are driven by hand, so "before the next frame" is real. */
function manualChart(): { chart: Chart; flush: () => number } {
  const doc = fakeDocument();
  let next = 1;
  const pending = new Map<number, () => void>();
  const chart = new Chart(doc.createElement('div'), {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    raf: {
      schedule: (cb: () => void) => { const h = next++; pending.set(h, cb); return h; },
      cancel: (h: number) => { pending.delete(h); },
    },
  });
  chart.applySize(800, 600);
  const flush = (): number => {
    const batch = [...pending.values()];
    pending.clear();
    for (const cb of batch) cb();
    return batch.length;
  };
  return { chart, flush };
}

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1735689600 + i * 60,
    open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 1000 + i,
  }));

const TOTAL = 375;

/** Registers a counting stand-in for a built-in, and restores it afterwards. */
function counted(id: string): { calls: () => number; restore: () => void } {
  const original = getIndicator(id);
  let n = 0;
  const wrapper: IndicatorDescriptor = {
    ...original,
    calc: (...args: Parameters<IndicatorDescriptor['calc']>) => {
      n++;
      return original.calc(...args);
    },
  };
  registerIndicator(wrapper);
  return { calls: () => n, restore: () => registerIndicator(original) };
}

describe('the base index is settled before a shrinking setData returns', () => {
  it('leaves the viewport on the data when a host positions it in the same turn', () => {
    // The host's gesture, verbatim: truncate to a prefix, then put the viewport
    // on the playhead. Both happen before any frame runs.
    const { chart, flush } = manualChart();
    const price = chart.addSeries('candlestick');
    price.setData(bars(TOTAL));
    chart.addIndicator('sma');
    flush();

    const from = Math.floor(TOTAL / 4);
    new ReplayController(chart, { series: price, bars: bars(TOTAL), startIndex: from });
    chart.timeScale.setVisibleLogicalRange({ from: -1, to: from + 4 });

    // The prefix occupies 0..from. A viewport that does not reach it draws an
    // empty chart, which is the reported symptom.
    const view = chart.timeScale.visibleRange();
    expect(view.to).toBeGreaterThanOrEqual(0);
    expect(view.from).toBeLessThanOrEqual(from);

    // And it stays put once the frame the host never waited for finally runs.
    flush();
    const after = chart.timeScale.visibleRange();
    expect(after.to).toBeGreaterThanOrEqual(0);
    expect(after.from).toBeLessThanOrEqual(from);
  });

  it('is the indicator series that used to hold it up, so the count is what moved', () => {
    const { chart, flush } = manualChart();
    const price = chart.addSeries('candlestick');
    price.setData(bars(TOTAL));
    chart.addIndicator('sma');
    flush();

    price.setData(bars(100));
    // Read the axis the way a host does, with no frame in between. Index 99 is
    // the last real bar; anything beyond it is a bar the chart no longer has.
    chart.timeScale.setVisibleLogicalRange({ from: 0, to: 99 });
    expect(chart.timeScale.rightOffset).toBe(0);
  });

  it('does not flush on the tick path, which is what the deferral is for', () => {
    // Appending keeps the price series the longest, so the base index is right
    // without a flush, and a burst of ticks between two frames must still cost
    // one recompute rather than one per tick.
    const probe = counted('sma');
    try {
      const { chart, flush } = manualChart();
      const price = chart.addSeries('candlestick');
      price.setData(bars(TOTAL));
      chart.addIndicator('sma');
      flush();

      const before = probe.calls();
      const t = 1735689600 + TOTAL * 60;
      for (let i = 0; i < 20; i++) {
        price.update({ time: t, open: 200, high: 201, low: 199, close: 200 + i, volume: 5 });
      }
      expect(probe.calls()).toBe(before); // nothing ran before the frame
      flush();
      expect(probe.calls() - before).toBe(1);
    } finally {
      probe.restore();
    }
  });

  it('costs one recompute per shrinking setData, not one per frame as well', () => {
    // The flush marks the indicators clean, so the frame that follows finds
    // nothing to do rather than repeating the pass.
    const probe = counted('sma');
    try {
      const { chart, flush } = manualChart();
      const price = chart.addSeries('candlestick');
      price.setData(bars(TOTAL));
      chart.addIndicator('sma');
      flush();

      const before = probe.calls();
      price.setData(bars(100));
      expect(probe.calls() - before).toBe(1);
      flush();
      expect(probe.calls() - before).toBe(1);
    } finally {
      probe.restore();
    }
  });
});
