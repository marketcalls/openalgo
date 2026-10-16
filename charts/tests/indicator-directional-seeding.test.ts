import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { ADX } from '../src/indicators/momentum';
import type { Bar } from '../src/model/bar';
import { registerIndicator, type IndicatorValues } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

registerIndicator(ADX);
const charts: Chart[] = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

const bars = (rows: readonly (readonly [number, number, number])[]): Bar[] =>
  rows.map(([high, low, close], index) => ({
    time: 1700000000 + index * 60, open: close, high, low, close, volume: 100,
  }));
const ramp = (length: number, direction = 1): Bar[] => bars(
  Array.from({ length }, (_, index) => {
    const close = 40 + direction * index;
    return [close + 1, close - 1, close] as const;
  }),
);
const asymmetric = bars([[10, 8, 9], [12, 9, 11], [11, 7, 8], [13, 9, 12], [12, 10, 11]]);
const expected = {
  plusDi: [null, null, 200 / 7, 600 / 17, 24],
  minusDi: [null, null, 200 / 7, 200 / 17, 8],
  adx: [null, null, null, 25, 37.5],
};
const interrupted = bars([[10, 8, 9], [12, 9, 11], [11, 7, 8], [13, 9, 12], [12, 10, 11],
  [NaN, NaN, NaN], [15, 11, 14], [16, 12, 15]]);
const resumedPlus = (0.875 / 3.5625) * 100;
const resumedMinus = (0.125 / 3.5625) * 100;
const resumedDx = (Math.abs(resumedPlus - resumedMinus) / (resumedPlus + resumedMinus)) * 100;
const interruptedExpected = {
  plusDi: [null, null, (1 / 3.5) * 100, (1.5 / 4.25) * 100, (0.75 / 3.125) * 100, null, null, resumedPlus],
  minusDi: [null, null, (1 / 3.5) * 100, (0.5 / 4.25) * 100, (0.25 / 3.125) * 100, null, null, resumedMinus],
  adx: [...expected.adx, null, null, (37.5 + resumedDx) / 2],
};

function expectValues(actual: IndicatorValues, wanted: Record<string, readonly (number | null)[]>): void {
  for (const [key, values] of Object.entries(wanted)) {
    expect(actual[key], key).toHaveLength(values.length);
    values.forEach((value, index) => {
      if (value === null) expect(actual[key][index], `${key}[${index}]`).toBeNull();
      else expect(actual[key][index], `${key}[${index}]`).toBeCloseTo(value, 12);
    });
  }
}

describe('directional movement and range use the same seed window', () => {
  it('matches independently calculated directional reversals and strength', () => {
    // At bar 2, TR seeds at 7/2 and both movement means at 1. The next
    // movement means are 3/2 and 1/2, giving DX 50 and the first ADX 25.
    expectValues(ADX.calc(asymmetric, { period: 2, adxPeriod: 2 }, {}), expected);
  });

  it.each([1, -1])('keeps unit movement over a two-unit range at fifty for direction %s', direction => {
    const output = ADX.calc(ramp(9, direction), { period: 3, adxPeriod: 3 }, {});
    expectValues(output, {
      plusDi: [null, null, null, ...Array<number>(6).fill(direction === 1 ? 50 : 0)],
      minusDi: [null, null, null, ...Array<number>(6).fill(direction === -1 ? 50 : 0)],
      adx: [null, null, null, null, null, 100, 100, 100, 100],
    });
  });

  it('preserves default warmup while removing the directional seed bias', () => {
    const output = ADX.calc(ramp(30), {}, {});
    expect(output.plusDi.slice(0, 14)).toEqual(Array(14).fill(null));
    expect(output.plusDi.slice(14)).toEqual(Array(16).fill(50));
    expect(output.minusDi.slice(14)).toEqual(Array(16).fill(0));
    expect(output.adx.slice(0, 27)).toEqual(Array(27).fill(null));
    expect(output.adx.slice(27)).toEqual([100, 100, 100]);
  });

  it('keeps period-one readings absent when their true range is zero', () => {
    const data = bars([[10, 8, 9], [12, 9, 11], [11, 7, 8], [8, 8, 8], [14, 11, 13], [15, 13, 14]]);
    expect(ADX.calc(data, { period: 1, adxPeriod: 2 }, {})).toEqual({
      plusDi: [null, (2 / 3) * 100, 0, null, 100, 50],
      minusDi: [null, 0, 50, null, 0, 0],
      adx: [null, null, 100, null, 100, 100],
    });
  });

  it('retains ADX through an undefined zero-range ratio before movement reverses', () => {
    const data = bars([[10, 0, 5], [11, 1, 6], [10, 2, 6], [6, 6, 6], [12, 6, 9], [11, 5, 8]]);
    // DX 100 and 0 seed ADX at 50. The flat bar contributes no ratio, so the
    // next DX 100 produces 75 rather than advancing the old zero a second time.
    expect(ADX.calc(data, { period: 1, adxPeriod: 2 }, {})).toEqual({
      plusDi: [null, 10, 0, null, 100, 0],
      minusDi: [null, 0, 0, null, 0, (1 / 6) * 100],
      adx: [null, null, 50, null, 75, 87.5],
    });
  });

  it('leaves an entirely flat zero-range history absent', () => {
    const data = bars(Array.from({ length: 8 }, () => [10, 10, 10] as const));
    expectValues(ADX.calc(data, { period: 2, adxPeriod: 2 }, {}), {
      plusDi: Array(8).fill(null), minusDi: Array(8).fill(null), adx: Array(8).fill(null),
    });
  });

  it('treats equally strong opposing movements as zero in both directions', () => {
    const data = bars([[10, 8, 9], [12, 6, 9], [11, 7, 9], [13, 5, 9], [13, 5, 9], [14, 4, 9]]);
    expectValues(ADX.calc(data, { period: 2, adxPeriod: 2 }, {}), {
      plusDi: [null, null, 0, 0, 0, 0], minusDi: [null, null, 0, 0, 0, 0],
      adx: [null, null, null, 0, 0, 0],
    });
  });

  it.each([1, -1])('retains smoothing state without emitting stale readings across missing OHLC for direction %s', direction => {
    const data = ramp(9, direction);
    data[6] = { ...data[6], open: NaN, high: NaN, low: NaN, close: NaN };
    expect(ADX.calc(data, { period: 3, adxPeriod: 3 }, {})).toEqual({
      plusDi: [null, null, null, ...Array<number>(3).fill(direction === 1 ? 50 : 0), null, null, direction === 1 ? 50 : 0],
      minusDi: [null, null, null, ...Array<number>(3).fill(direction === -1 ? 50 : 0), null, null, direction === -1 ? 50 : 0],
      adx: [null, null, null, null, null, 100, null, null, 100],
    });
  });

  it.each(['high', 'low', 'close', 'open'] as const)('uses only the current and previous observations needed after missing %s', key => {
    const data = ramp(9);
    data[6] = { ...data[6], [key]: NaN };
    const unavailable = key === 'open' ? [] : key === 'close' ? [7] : [6, 7];
    const output = ADX.calc(data, { period: 3, adxPeriod: 3 }, {});
    expect(output).toEqual({
      plusDi: data.map((_, i) => i < 3 || unavailable.includes(i) ? null : 50),
      minusDi: data.map((_, i) => i < 3 || unavailable.includes(i) ? null : 0),
      adx: data.map((_, i) => i < 5 || unavailable.includes(i) ? null : 100),
    });
  });

  it('seeds movement independently when an initial missing close delays the range', () => {
    const data = bars([[10, 8, NaN], [12, 10, 11], [16, 14, 15], [17, 15, 16], [20, 18, 19]]);
    // Movement seeds from 2 and 4 at bar 2, then becomes 2 and 5/2.
    // Range seeds from 5 and 2 at bar 3, then becomes 15/4.
    expect(ADX.calc(data, { period: 2, adxPeriod: 2 }, {})).toEqual({
      plusDi: [null, null, null, (2 / 3.5) * 100, (2.5 / 3.75) * 100],
      minusDi: [null, null, null, 0, 0],
      adx: [null, null, null, null, 100],
    });
  });

  it('waits for finite movement seeds after a missing initial extreme', () => {
    const data = bars([[NaN, 8, 9], [12, 10, 11], [16, 14, 15], [17, 15, 16], [20, 18, 19]]);
    // Range seeds to 4 at bar 2 and reaches 3 at bar 3; movement seeds later
    // from 4 and 1, with no fabricated zero for the missing previous high.
    expect(ADX.calc(data, { period: 2, adxPeriod: 2 }, {})).toEqual({
      plusDi: [null, null, null, (2.5 / 3) * 100, (2.75 / 3.5) * 100],
      minusDi: [null, null, null, 0, 0],
      adx: [null, null, null, null, 100],
    });
  });

  it('leaves an overflowed finite difference absent and resumes from retained states', () => {
    const data = bars([[-1e308, -1e308, -1e308], [-1e308, -1e308, -1e308],
      [1e308, 1e308, 1e308], [1e308, 5e307, 1e308], [1e308, 5e307, 1e308]]);
    expect(ADX.calc(data, { period: 1, adxPeriod: 1 }, {})).toEqual({
      plusDi: [null, null, null, 0, 0], minusDi: [null, null, null, 100, 0],
      adx: [null, null, null, 100, 0],
    });
  });

  it('does not advance the strength average using held directional values during a gap', () => {
    // The last available ADX is 37.5. Missing observations contribute no DX;
    // the next directional observation uses movement 7/8, 1/8 and range 57/16.
    expect(ADX.calc(interrupted, { period: 2, adxPeriod: 2 }, {})).toEqual(interruptedExpected);
  });

  it('produces missing and resumed values from each causal prefix', () => {
    for (let length = 0; length <= interrupted.length; length++) {
      const wanted = Object.fromEntries(Object.entries(interruptedExpected).map(([key, values]) => [key, values.slice(0, length)]));
      expect(ADX.calc(interrupted.slice(0, length), { period: 2, adxPeriod: 2 }, {})).toEqual(wanted);
    }
  });

  it('produces each expected prefix without requiring later bars', () => {
    for (let length = 0; length <= asymmetric.length; length++) {
      const wanted = Object.fromEntries(Object.entries(expected).map(([key, values]) => [key, values.slice(0, length)]));
      expectValues(ADX.calc(asymmetric.slice(0, length), { period: 2, adxPeriod: 2 }, {}), wanted);
    }
  });

  it('recomputes native forming updates without changing the completed prefix', () => {
    const document = fakeDocument();
    const pending = new Map<number, () => void>();
    let handle = 0;
    const chart = new Chart(document.createElement('div'), {
      document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
      raf: {
        schedule: callback => { pending.set(++handle, callback); return handle; },
        cancel: id => { pending.delete(id); },
      },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    const source = chart.addSeries('candlestick');
    source.setData(asymmetric.slice(0, 4));
    const study = chart.addIndicator('adx', { period: 2, adxPeriod: 2 });
    const prefix = Object.fromEntries(Object.entries(expected).map(([key, values]) => [key, values.slice(0, 4)]));
    expectValues(study.values(), prefix);

    const changed = { ...asymmetric[3], high: 14, close: 13 };
    source.update(changed);
    const revised = {
      plusDi: [null, null, 200 / 7, 800 / 19],
      minusDi: [null, null, 200 / 7, 200 / 19],
      adx: [null, null, null, 30],
    };
    expectValues(study.values(), revised);
    source.update(changed);
    expectValues(study.values(), revised);
    source.update(asymmetric[3]);
    expectValues(study.values(), prefix);
    source.update(asymmetric[4]);
    expectValues(study.values(), expected);
  });

  it('restores the recovered state after rewriting a native forming tail as missing', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), {
      document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => undefined },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    const source = chart.addSeries('candlestick');
    source.setData(interrupted);
    const study = chart.addIndicator('adx', { period: 2, adxPeriod: 2 });
    expect(study.values()).toEqual(interruptedExpected);
    const last = interrupted[interrupted.length - 1];
    source.update({ ...last, open: NaN, high: NaN, low: NaN, close: NaN });
    const missing = Object.fromEntries(Object.entries(interruptedExpected).map(([key, values]) => [key, [...values.slice(0, -1), null]]));
    expect(study.values()).toEqual(missing);
    source.update(last);
    expect(study.values()).toEqual(interruptedExpected);
  });
});
