/**
 * Indicator recompute is scheduled with the frame, not driven from the data
 * update.
 *
 * A busy symbol delivers ticks in bursts far faster than the display refreshes.
 * Recomputing on the data update spends a full pass over every bar, for every
 * indicator, on every tick, and throws all but the last away unseen: measured at
 * 50 recomputes per indicator and 642 ms of blocked main thread for a 50-tick
 * burst on a ten indicator chart. Deferring to the frame makes that one pass.
 *
 * These tests pin the property, not the timing, so they say something on any
 * machine: how many times `calc` runs, and that a value read back in the same
 * turn is still the fresh one.
 */
import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins
import { Chart } from '../src/core/chart';
import { registerIndicator, getIndicator } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

/**
 * A chart whose frames are driven by hand.
 *
 * The scheduler is a queue rather than a single slot: a chart runs more than one
 * frame loop, and a one-callback fake lets the second overwrite the first, after
 * which the loop believes a frame is forever pending and nothing recomputes
 * again. That failure reads as a spectacular optimisation, so it is worth not
 * reproducing here.
 */
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
  // Take the batch and clear before invoking: running a frame schedules the next.
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
    time: 1735689600 + i * 900,
    open: 100 + i,
    high: 101 + i,
    low: 99 + i,
    close: 100 + i,
    volume: 1000,
  }));

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

describe('indicator recompute scheduling', () => {
  it('collapses a burst of ticks into one recompute per frame', () => {
    const probe = counted('sma');
    try {
      const { chart, flush } = manualChart();
      const data = bars(200);
      const price = chart.addSeries('candlestick');
      price.setData(data);
      chart.addIndicator('sma');
      while (flush()) { /* settle the frames the setup scheduled */ }

      const before = probe.calls();
      const last = data[data.length - 1];
      for (let i = 0; i < 50; i++) price.update({ ...last, close: 500 + i });

      // Nothing has recomputed yet: the ticks only marked the maths stale.
      expect(probe.calls()).toBe(before);

      flush();
      expect(probe.calls() - before).toBe(1);
    } finally {
      probe.restore();
    }
  });

  it('still gives a caller the fresh value read back in the same turn', () => {
    const { chart, flush } = manualChart();
    const data = bars(200);
    const price = chart.addSeries('candlestick');
    price.setData(data);
    const sma = chart.addIndicator('sma', { length: 3 });
    while (flush()) { /* settle */ }

    const last = data[data.length - 1];
    // No frame between the update and the read. Deferring the maths must not
    // mean handing back the previous tick's numbers.
    price.update({ ...last, close: 900 });

    const values = sma.values().ma as (number | null)[];
    // The update carries the last bar's timestamp, so it replaces bar 199 rather
    // than appending: the closing window is 297, 298, 900.
    expect(values[values.length - 1]).toBeCloseTo((297 + 298 + 900) / 3, 10);
    // Worth stating why this number is the assertion. Without the flush the read
    // would return the pre-update window, (297 + 298 + 299) / 3 = 298.
    expect(values[values.length - 1]).not.toBeCloseTo(298, 6);
  });

  it('does not recompute a second time on the frame after a value was read', () => {
    const probe = counted('sma');
    try {
      const { chart, flush } = manualChart();
      const data = bars(200);
      const price = chart.addSeries('candlestick');
      price.setData(data);
      const sma = chart.addIndicator('sma');
      while (flush()) { /* settle */ }

      const before = probe.calls();
      const last = data[data.length - 1];
      price.update({ ...last, close: 777 });

      sma.values(); // flushes
      expect(probe.calls() - before).toBe(1);

      flush(); // the frame finds nothing left to do
      expect(probe.calls() - before).toBe(1);
    } finally {
      probe.restore();
    }
  });
});
