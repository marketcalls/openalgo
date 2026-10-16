import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { indicatorDefaults } from '../src/model/indicator-registry';
import { CPR } from '../src/indicators/studies';

type Period = 'daily' | 'weekly' | 'monthly';
const prefixes = { daily: 'd', weekly: 'w', monthly: 'm' };
const levels = ['Pivot', 'S1', 'S2', 'S3', 'R1', 'R2', 'R3', 'Bc', 'Tc'];
const ordinary = [35, -30, -65, -130, 70, 135, 170, 50, 20];
// Complete next period: high7, low4, final close5, pivot16/3.
const recovered = [
  5.333333333333333, 3.666666666666666, 2.333333333333333,
  0.6666666666666661, 6.666666666666666, 8.333333333333332,
  9.666666666666666, 5.5, 5.166666666666666,
];

function observations(period: Period): Bar[] {
  const dates = period === 'daily'
    ? [[0, 2, 9], [0, 2, 10], [0, 2, 11], [0, 3, 9], [0, 4, 9]]
    : period === 'weekly'
      ? [[0, 1, 9], [0, 2, 9], [0, 3, 9], [0, 8, 9], [0, 15, 9]]
      : [[0, 2, 9], [0, 3, 9], [0, 4, 9], [1, 2, 9], [2, 2, 9]];
  return dates.map(([month, day, hour], i) => ({
    time: Date.UTC(2024, month, day, hour) / 1000,
    open: 5, high: [100, 20, 10, 7, 7][i], low: [0, 1, 2, 4, 4][i], close: 5,
  }));
}

function run(bars: readonly Bar[], period: Period) {
  return CPR.calc(bars, {
    ...indicatorDefaults(CPR), pivotMode: 'manual', timezone: 'UTC', displayS1R1: true,
    showDaily: period === 'daily', showWeekly: period === 'weekly', showMonthly: period === 'monthly',
  }, {});
}

function readings(bars: readonly Bar[], period: Period, index: number) {
  const values = run(bars, period);
  return levels.map(level => values[prefixes[period] + level][index]);
}

for (const period of ['daily', 'weekly', 'monthly'] as const) {
  describe(`CPR incomplete ${period} observations`, () => {
    it('preserves all ordinary levels and the first-period warmup', () => {
      const bars = observations(period), values = run(bars, period);
      for (const level of levels) expect(values[prefixes[period] + level].slice(0, 3)).toEqual([null, null, null]);
      expect(readings(bars, period, 3)).toEqual(ordinary);
      expect(readings(bars, period, 4)).toEqual(recovered);
      for (const prefix of Object.values(prefixes).filter(p => p !== prefixes[period])) {
        for (const level of levels) expect(values[prefix + level]).toEqual(Array(5).fill(null));
      }
    });

    for (const field of ['high', 'low'] as const) {
      for (const position of [0, 1, 2]) {
        it.each([NaN, Infinity, -Infinity])(`keeps ${field} unavailable from observation ${position} until the next boundary (%s)`, missing => {
          const bars = observations(period);
          bars[position][field] = missing;
          expect(readings(bars, period, 3)).toEqual(Array(9).fill(null));
          expect(readings(bars, period, 4)).toEqual(recovered);
        });
      }
    }

    it.each([NaN, Infinity, -Infinity])('uses the final close after an earlier unavailable close (%s)', missing => {
      const bars = observations(period);
      bars[0].close = missing;
      bars[1].close = missing;
      expect(readings(bars, period, 3)).toEqual(ordinary);
    });

    it.each([NaN, Infinity, -Infinity])('withholds all nine levels when the final close is unavailable (%s)', missing => {
      const bars = observations(period);
      bars[2].close = missing;
      expect(readings(bars, period, 3)).toEqual(Array(9).fill(null));
      expect(readings(bars, period, 4)).toEqual(recovered);
    });

    it('does not change the frozen prior frame when the current period is incomplete', () => {
      const bars = observations(period);
      bars[3].high = NaN;
      expect(readings(bars, period, 3)).toEqual(ordinary);
      expect(readings(bars, period, 4)).toEqual(Array(9).fill(null));
    });

    it('recomputes a corrected observation without caching the incomplete frame', () => {
      const bars = observations(period);
      bars[1].high = NaN;
      expect(readings(bars, period, 3)).toEqual(Array(9).fill(null));
      bars[1].high = 20;
      expect(readings(bars, period, 3)).toEqual(ordinary);
      bars[1].high = NaN;
      expect(readings(bars, period, 3)).toEqual(Array(9).fill(null));
    });

    it('keeps prefix results stable and does not mutate observations', () => {
      const bars = observations(period);
      bars[1].high = NaN;
      bars.forEach(Object.freeze);
      Object.freeze(bars);
      const full = run(bars, period);
      for (let end = 1; end <= bars.length; end++) {
        const prefix = run(bars.slice(0, end), period);
        for (const key of Object.keys(full)) expect(prefix[key]).toEqual(full[key].slice(0, end));
      }
    });
  });
}
