import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { indicatorDefaults } from '../src/model/indicator-registry';
import { SEASONALITY } from '../src/indicators/seasonality';

const data = (closes: readonly number[]): Bar[] => closes.map((close, i) => ({
  time: Date.UTC(2024, i, 15) / 1000, open: close, high: close, low: close, close,
}));
const table = (bars: readonly Bar[]) => SEASONALITY.table?.({
  bars, settings: { ...indicatorDefaults(SEASONALITY), timezone: 'UTC', startYear: 1800 }, values: {},
});
const texts = (bars: readonly Bar[]) => table(bars)?.rows.map((row) => row.map((cell) => cell.text ?? '')) ?? null;

describe('Seasonality finite table values', () => {
  for (const [name, closes] of [
    ['overflow', [1e308, -1e308, 100, 120, 110]],
    ['tiny denominator', [Number.MIN_VALUE, 1, 2, 3, 4]],
  ] as const) {
    for (const length of [3, 4, 5]) {
      it(`omits an unavailable ${name} month at prefix ${length}`, () => {
        const rows = texts(data(closes.slice(0, length)));
        expect(rows?.flat().some((text) => /NaN|Infinity/.test(text)) ?? false).toBe(false);
        if (length === 3 || name === 'overflow' && length === 4) expect(rows).toBeNull();
        else {
          const year = rows!.find((row) => row[0] === '2024')!;
          const averages = rows!.find((row) => row[0] === 'Avgs:')!;
          const positive = rows!.find((row) => row[0] === 'Pos%:')!;
          expect(year[2]).toBe('');
          expect(averages[2]).toBe('');
          expect(positive[2]).toBe('');
          const measuredMonth = name === 'overflow' ? 4 : 3;
          expect(year[measuredMonth]).toBe(name === 'overflow' ? '20.00%' : '100.00%');
          expect(positive[measuredMonth]).toBe('100%');
        }
      });
    }
  }

  it('does not format an overflowing aggregate of finite monthly changes', () => {
    const bars: Bar[] = [];
    for (let year = 1800; year < 1850; year++) {
      for (const [month, close] of [[0, 1], [1, 1e305], [2, 1e305]]) {
        bars.push({ time: Date.UTC(year, month, 15) / 1000, open: close, high: close, low: close, close });
      }
    }
    const rows = texts(bars)!;
    expect(rows.flat().some((text) => /NaN|Infinity/.test(text))).toBe(false);
    expect(rows.find((row) => row[0] === 'Avgs:')![2]).toBe('');
    expect(rows.find((row) => row[0] === 'Pos%:')![2]).toBe('100%');
  });

  it('does not format an overflowing variance of finite monthly changes', () => {
    const bars = [
      [2023, 0, 100], [2023, 1, 1e155], [2023, 2, 1e155],
      [2024, 0, 100], [2024, 1, 2e155], [2024, 2, 2e155],
    ].map(([year, month, close]) => ({
      time: Date.UTC(year, month, 15) / 1000, open: close, high: close, low: close, close,
    }));
    const rows = texts(bars)!;
    expect(rows.flat().some((text) => /NaN|Infinity/.test(text))).toBe(false);
    expect(rows.find((row) => row[0] === 'StDev:')![2]).toBe('');
    expect(rows.find((row) => row[0] === 'Pos%:')![2]).toBe('100%');
  });
});
