/**
 * A `calc` that throws after the indicator is on the chart must not take the
 * frame down with it. Before 2.4.0 `_flushIndicators` ran every instance in
 * one loop with no catch, so one study's bad input left every study behind it
 * stale for that frame and re-threw into the render loop. Now the failure is
 * published on the instance's data status, the other studies still recompute,
 * and the next pass that succeeds clears it. The constructor's own pass is
 * still unguarded on purpose: a descriptor that cannot compute at all is
 * refused by `addIndicator`, not added as an empty pane.
 */
import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, IndicatorInputError } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorDataStatus, IndicatorAttachContext } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

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
    time: 1735689600 + i * 900, open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i,
  }));

let fail = false;
let laterCalcs = 0;

const FAILING: IndicatorDescriptor = {
  id: 'guard-failing', name: 'Failing', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b) => {
    if (fail) throw new IndicatorInputError('Period must be greater than 0');
    return { v: b.map((x) => x.close) };
  },
};
const LATER: IndicatorDescriptor = {
  id: 'guard-later', name: 'Later', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b) => { laterCalcs += 1; return { v: b.map((x) => x.open) }; },
};
const BROKEN: IndicatorDescriptor = {
  id: 'guard-broken', name: 'Broken', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: () => { throw new Error('cannot compute at all'); },
};
registerIndicator(FAILING);
registerIndicator(LATER);
registerIndicator(BROKEN);

describe('recompute guard', () => {
  it.each(['loading', 'unsupported', 'empty', 'error'] as const)('preserves newer lifecycle %s status when cached calculation recovers', state => {
    let attachment!: IndicatorAttachContext;
    let broken = false;
    const descriptor: IndicatorDescriptor = {
      ...FAILING, id: `guard-lifecycle-${state}`,
      calc: b => {
        if (broken) throw new Error('Rejected calculation');
        return { v: b.map(item => item.close) };
      },
      attach: context => { attachment = context; },
    };
    registerIndicator(descriptor);
    const { chart } = manualChart();
    try {
      const source = chart.addSeries('candlestick');
      const data = bars(3);
      source.setData(data);
      const indicator = chart.addIndicator(descriptor.id);
      source.update({ ...data[2], close: 110 });
      broken = true;
      attachment.requestRecompute();
      expect(indicator.dataStatus()?.state).toBe('error');
      const status: IndicatorDataStatus = state === 'error'
        ? { state, error: new Error('Provider unavailable') } : { state };
      attachment.setDataStatus!(status);
      broken = false;
      expect(indicator.values().v[2]).toBe(110);
      expect(indicator.dataStatus()).toEqual(status);
    } finally { chart.destroy(); }
  });

  it('restores the pending lifecycle status after a temporary calculation failure', () => {
    let attachment!: IndicatorAttachContext;
    let broken = false;
    registerIndicator({
      ...FAILING, id: 'guard-pending-lifecycle',
      calc: b => {
        if (broken) throw new Error('Temporary failure');
        return { v: b.map(item => item.close) };
      },
      attach: context => { attachment = context; context.setDataStatus!({ state: 'loading' }); },
    });
    const { chart } = manualChart();
    try {
      const source = chart.addSeries('candlestick');
      source.setData(bars(3));
      const indicator = chart.addIndicator('guard-pending-lifecycle');
      broken = true;
      attachment.requestRecompute();
      expect(indicator.dataStatus()?.state).toBe('error');
      broken = false;
      attachment.requestRecompute();
      expect(indicator.dataStatus()?.state).toBe('loading');
    } finally { chart.destroy(); }
  });

  it('publishes a thrown calc as an error status and keeps the other studies computing', () => {
    fail = false;
    laterCalcs = 0;
    const { chart, flush } = manualChart();
    const series = chart.addSeries('candlestick');
    const data = bars(20);
    series.setData(data);
    const failing = chart.addIndicator('guard-failing');
    const later = chart.addIndicator('guard-later');
    flush();
    const before = laterCalcs;
    const seen: IndicatorDataStatus[] = [];
    chart.on('indicator:data-status', (e: unknown) => { seen.push((e as { status: IndicatorDataStatus }).status); });

    fail = true;
    series.update({ time: data[19].time + 900, open: 1, high: 2, low: 0.5, close: 1.5 });
    expect(() => flush()).not.toThrow();

    expect(failing.dataStatus()?.state).toBe('error');
    const status = failing.dataStatus();
    expect(status?.state === 'error' && status.error instanceof IndicatorInputError).toBe(true);
    expect(seen.map((s) => s.state)).toEqual(['error']);
    // The study behind the failing one still ran this frame.
    expect(laterCalcs).toBe(before + 1);
    expect(later.values().v).toHaveLength(21);
    // The failed study keeps what it last drew rather than vanishing.
    expect(failing.values().v).toHaveLength(20);
  });

  it('clears the error on the next recompute that succeeds', () => {
    fail = false;
    const { chart, flush } = manualChart();
    const series = chart.addSeries('candlestick');
    const data = bars(10);
    series.setData(data);
    const failing = chart.addIndicator('guard-failing');
    flush();
    fail = true;
    series.update({ time: data[9].time + 900, open: 1, high: 2, low: 0.5, close: 1.5 });
    flush();
    expect(failing.dataStatus()?.state).toBe('error');
    fail = false;
    series.update({ time: data[9].time + 1800, open: 1, high: 2, low: 0.5, close: 1.5 });
    flush();
    expect(failing.dataStatus()?.state).toBe('ready');
    expect(failing.values().v).toHaveLength(12);
  });

  it('keeps the last good candle colours when a settings change makes calc throw, and does not throw itself', () => {
    // The colour hook reads a column, so running it on a pass that produced none would throw.
    registerIndicator({
      ...FAILING, id: 'guard-settings-colours', inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      calc: (b, settings) => {
        if (settings.bad === true) throw new IndicatorInputError('Bad is set');
        return { v: b.map(x => x.close) };
      },
      barColors: ({ values }) => values.v.map(() => '#00ff00'),
    });
    const { chart, flush } = manualChart();
    try {
      chart.addSeries('candlestick').setData(bars(10));
      const study = chart.addIndicator('guard-settings-colours');
      flush();
      expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
      expect(() => study.setSettings({ bad: true })).not.toThrow();
      const status = study.dataStatus();
      expect(status?.state === 'error' && status.error instanceof IndicatorInputError).toBe(true);
      expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
      study.setSettings({ bad: false });
      expect(study.dataStatus()?.state).toBe('ready');
    } finally { chart.destroy(); }
  });

  it('still refuses a descriptor that throws on its first calc', () => {
    const { chart } = manualChart();
    chart.addSeries('candlestick').setData(bars(5));
    expect(() => chart.addIndicator('guard-broken')).toThrow('cannot compute at all');
    expect(chart.indicators()).toHaveLength(0);
  });

  it('names the condition for a host: IndicatorInputError is an Error with its own name', () => {
    const e = new IndicatorInputError('Fast length must be below slow length');
    expect(e).toBeInstanceOf(Error);
    expect(e.name).toBe('IndicatorInputError');
    expect(e.message).toBe('Fast length must be below slow length');
  });
});
