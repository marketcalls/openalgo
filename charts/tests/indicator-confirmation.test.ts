import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerInterval } from '../src/feed/intervals';
import { registerIndicator, type IndicatorCalcContext } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const registrations: (() => void)[] = [];
let sequence = 0;

afterEach(() => {
  charts.splice(0).forEach(chart => chart.destroy());
  registrations.splice(0).forEach(dispose => dispose());
});

const seconds = (iso: string): number => Date.parse(iso) / 1000;

function probe(times: number[], now: number, interval?: string, timezone = 'Etc/UTC') {
  const clock = { now };
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, timezone, pixelRatio: () => 1, shortcuts: false,
    axisChrome: { clock: () => clock.now },
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  if (interval !== undefined) chart.setDataContext({ symbol: 'SAMPLE', interval });
  const data = times.map(time => ({ time, open: 10, high: 12, low: 9, close: 11 }));
  chart.addSeries('candlestick').setData(data);
  let context: IndicatorCalcContext | undefined;
  const id = `confirmation-${sequence++}`;
  registerIndicator({
    id, name: 'Confirmation', placement: 'onchart', inputs: [],
    plots: [{ key: 'close', type: 'line', title: 'Close' }],
    calc: (bars, _settings, _store, ctx) => {
      context = ctx;
      return { close: bars.map(bar => bar.close) };
    },
  });
  const indicator = chart.addIndicator(id);
  return {
    confirmed: () => context?.barState.isConfirmed,
    at: (time: number) => {
      clock.now = time;
      chart.primarySeries()?.update({ ...data[data.length - 1] });
      indicator.values();
    },
  };
}

describe('indicator confirmation uses the declared interval', () => {
  it('closes a minute bar exactly one minute after a weekend opening', () => {
    const friday = seconds('2026-09-18T09:59:00Z');
    const monday = seconds('2026-09-21T03:45:00Z');
    const p = probe([friday, monday], monday + 59, '1m');
    expect(p.confirmed()).toBe(false);
    p.at(monday + 60);
    expect(p.confirmed()).toBe(true);
  });

  it('does not use missing candles as the next candle duration', () => {
    const p = probe([0, 180], 239, '1m');
    expect(p.confirmed()).toBe(false);
    p.at(240);
    expect(p.confirmed()).toBe(true);
  });

  it('waits for the first loaded bar to finish even without a preceding bar', () => {
    const p = probe([600], 899, '5m');
    expect(p.confirmed()).toBe(false);
    p.at(900);
    expect(p.confirmed()).toBe(true);
  });

  it('uses the recorded opening for a session-aligned fixed-duration bar', () => {
    // The feed opens its hourly bars at :15, not at the epoch-aligned hour.
    const open = seconds('2026-09-21T03:45:00Z');
    const p = probe([open - 3600, open], open + 3599, '1h');
    expect(p.confirmed()).toBe(false);
    p.at(open + 3600);
    expect(p.confirmed()).toBe(true);
  });

  it('honours a registered duration instead of inferring it from sparse data', () => {
    registrations.push(registerInterval({ code: 'sample-span', bucketing: { mode: 'interval', seconds: 90 } }));
    const p = probe([0, 900], 989, 'sample-span');
    expect(p.confirmed()).toBe(false);
    p.at(990);
    expect(p.confirmed()).toBe(true);
  });

  it('uses the next calendar boundary through a daylight-saving change', () => {
    registrations.push(registerInterval({ code: 'sample-month', bucketing: { mode: 'calendar', unit: 'month' } }));
    // March opens on UTC-5 and April on UTC-4. February's length cannot be reused.
    const february = seconds('2026-02-01T05:00:00Z');
    const march = seconds('2026-03-01T05:00:00Z');
    const april = seconds('2026-04-01T04:00:00Z');
    const p = probe([february, march], april - 1, 'sample-month', 'America/New_York');
    expect(p.confirmed()).toBe(false);
    p.at(april);
    expect(p.confirmed()).toBe(true);
  });

  it('uses a calendar registration timezone ahead of the display timezone', () => {
    registrations.push(registerInterval({
      code: 'sample-exchange-month',
      bucketing: { mode: 'calendar', unit: 'month', timezone: 'Asia/Kolkata' },
    }));
    const open = seconds('2026-08-31T18:30:00Z');
    const close = seconds('2026-09-30T18:30:00Z');
    const p = probe([open], close - 1, 'sample-exchange-month', 'Etc/UTC');
    expect(p.confirmed()).toBe(false);
    p.at(close);
    expect(p.confirmed()).toBe(true);
  });

  it.each(['ticks', 'volume'] as const)('cannot confirm %s bars from elapsed wall time', mode => {
    const bucketing = mode === 'ticks' ? { mode, count: 100 } : { mode, perBar: 1000 };
    registrations.push(registerInterval({ code: `sample-${mode}`, bucketing }));
    expect(probe([0, 60], 86400, `sample-${mode}`).confirmed()).toBe(false);
  });

  it('does not silently reinterpret an unknown interval as a duration', () => {
    expect(probe([0, 60], 86400, 'not-registered').confirmed()).toBe(false);
  });

  it('retains the legacy gap fallback for hosts with no interval', () => {
    const p = probe([0, 60], 119);
    expect(p.confirmed()).toBe(false);
    p.at(120);
    expect(p.confirmed()).toBe(true);
    expect(probe([0], 0).confirmed()).toBe(true);
  });

  it('reports empty history as confirmed', () => {
    expect(probe([], 0, '1m').confirmed()).toBe(true);
  });
});
