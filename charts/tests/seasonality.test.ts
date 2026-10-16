import { describe, it, expect } from 'vitest';
import { SEASONALITY, SEASONALITY_INDICATORS } from '../src/indicators/seasonality';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { TableCell } from '../src/primitives/table';
import type { Bar } from '../src/model/bar';

const IST_OFFSET = 5.5 * 3600;

/** A bar stamped at a given IST wall clock, so month boundaries are explicit. */
const istBar = (y: number, m: number, d: number, close: number, hour = 12, minute = 0): Bar => ({
  time: Date.UTC(y, m - 1, d, hour, minute, 0) / 1000 - IST_OFFSET,
  open: close,
  high: close + 1,
  low: close - 1,
  close,
  volume: 100,
});

/**
 * Three bars in one month, closing at `close`. The two earlier closes are
 * deliberately nothing like it: only the month's last close should be read.
 */
const monthBars = (y: number, m: number, close: number): Bar[] => [
  istBar(y, m, 2, close * 3),
  istBar(y, m, 15, close / 2),
  istBar(y, m, 27, close),
];

/**
 * Month-end closes chosen so every close-to-close change is a whole percent and
 * exactly representable, and the changes they imply, worked out by hand:
 *
 *   2023: 100 -> 125 -> 100 -> 200 -> 100 -> 150 -> 120 -> 150 -> 75 -> 150 -> 120 -> 150 -> 75
 *          +25   -20   +100   -50    +50   -20    +25    -50   +100   -20    +25    -50
 *
 * December 2022 is the seed: as the first month in the data it has no
 * predecessor, so it carries no change and never earns a row of its own.
 */
const SEED_CLOSE = 100;
const CLOSES_2023 = [125, 100, 200, 100, 150, 120, 150, 75, 150, 120, 150, 75];
const CLOSES_2024 = [60, 75, 150, 75, 60, 75, 150, 75, 60, 75, 150, 75];
const CHANGES_2023 = [25, -20, 100, -50, 50, -20, 25, -50, 100, -20, 25, -50];
const CHANGES_2024 = [-20, 25, 100, -50, -20, 25, 100, -50, -20, 25, 100, -50];

/** The two full years above, plus a lone bar absorbing the "still forming" rule. */
const twoYears = (): Bar[] => {
  const out: Bar[] = [...monthBars(2022, 12, SEED_CLOSE)];
  CLOSES_2023.forEach((c, i) => out.push(...monthBars(2023, i + 1, c)));
  CLOSES_2024.forEach((c, i) => out.push(...monthBars(2024, i + 1, c)));
  out.push(istBar(2025, 1, 3, 100));
  return out;
};

const meanOf = (v: readonly number[]): number => v.reduce((a, b) => a + b, 0) / v.length;
const stdevOf = (v: readonly number[]): number => {
  const mu = meanOf(v);
  return Math.sqrt(v.reduce((a, x) => a + (x - mu) * (x - mu), 0) / (v.length - 1));
};

const defaults = (d: IndicatorDescriptor): Record<string, unknown> => indicatorDefaults(d);

const tableOf = (data: readonly Bar[], over: Record<string, unknown> = {}) => {
  const settings = { ...defaults(SEASONALITY), ...over };
  return SEASONALITY.table?.({ bars: data, values: SEASONALITY.calc(data, settings, {}), settings }) ?? null;
};

const gridOf = (data: readonly Bar[], over: Record<string, unknown> = {}): readonly (readonly TableCell[])[] => {
  const spec = tableOf(data, over);
  expect(spec).not.toBeNull();
  return spec?.rows ?? [];
};

const texts = (row: readonly TableCell[]): string[] => row.map((c) => c.text);
const rowNamed = (
  rows: readonly (readonly TableCell[])[],
  label: string,
): readonly TableCell[] | undefined => rows.find((r) => r[0]?.text === label);

describe('Seasonality catalogue entry', () => {
  it('exports the study under its catalogue id, in its own pane', () => {
    expect(SEASONALITY_INDICATORS.map((d) => d.id)).toEqual(['seasonality']);
    expect(SEASONALITY.id).toBe('seasonality');
    expect(SEASONALITY.placement).toBe('pane');
    expect(typeof SEASONALITY.table).toBe('function');
  });

  it('mirrors the reference inputs and their defaults', () => {
    expect(defaults(SEASONALITY)).toEqual({
      startYear: 2015,
      posColor: '#089981',
      negColor: '#F23745',
      cutoffPercent: 10,
      tablePosition: 'Center',
      tableWidth: 100,
      tableHeight: 95,
      showAvg: true,
      showStDev: true,
      showPos: true,
      ignoredMonths: 'YYYY-MM, YYYY-MM',
    });
  });

  it('returns one full-length column per declared plot, all null', () => {
    const bars = twoYears();
    const values = SEASONALITY.calc(bars, defaults(SEASONALITY), {});
    expect(Object.keys(values)).toEqual(SEASONALITY.plots.map((p) => p.key));
    expect(values.seasonality).toHaveLength(bars.length);
    expect(values.seasonality.every((v) => v === null)).toBe(true);
  });
});

describe('Seasonality monthly changes', () => {
  it('measures each month against the previous month close', () => {
    const rows = gridOf(twoYears());
    const y2023 = rowNamed(rows, '2023') ?? [];
    const y2024 = rowNamed(rows, '2024') ?? [];
    expect(texts(y2023).slice(1)).toEqual([
      '25.00%', '-20.00%', '100.00%', '-50.00%', '50.00%', '-20.00%',
      '25.00%', '-50.00%', '100.00%', '-20.00%', '25.00%', '-50.00%',
    ]);
    expect(texts(y2024).slice(1)).toEqual([
      '-20.00%', '25.00%', '100.00%', '-50.00%', '-20.00%', '25.00%',
      '100.00%', '-50.00%', '-20.00%', '25.00%', '100.00%', '-50.00%',
    ]);
    // The same numbers, read off the hand-built close chain rather than the grid.
    expect(texts(y2023).slice(1)).toEqual(CHANGES_2023.map((c) => `${c.toFixed(2)}%`));
    expect(texts(y2024).slice(1)).toEqual(CHANGES_2024.map((c) => `${c.toFixed(2)}%`));
  });

  it('counts the gap over the turn of the month, not just the move inside it', () => {
    // Both months travel from 50 to 100 internally; only the second one follows
    // a month that closed at 100, so only it reads flat.
    const bars = [
      istBar(2024, 1, 5, 50), istBar(2024, 1, 28, 100),
      istBar(2024, 2, 5, 50), istBar(2024, 2, 28, 100),
      istBar(2024, 3, 5, 100),
    ];
    const y2024 = rowNamed(gridOf(bars), '2024') ?? [];
    expect(y2024[2].text).toBe('0.00%');
  });

  it('resolves months on the IST calendar, not on UTC', () => {
    // 00:15 IST on 1 January is 18:45 UTC on 31 December. Read as UTC that bar
    // would close December at 200 and turn these two figures inside out.
    const bars = [
      ...monthBars(2023, 11, 100),
      istBar(2023, 12, 2, 105), istBar(2023, 12, 27, 110),
      istBar(2024, 1, 1, 200, 0, 15),
      istBar(2024, 1, 20, 220),
      istBar(2024, 2, 3, 300),
    ];
    const rows = gridOf(bars);
    expect((rowNamed(rows, '2023') ?? [])[12].text).toBe('10.00%');
    expect((rowNamed(rows, '2024') ?? [])[1].text).toBe('100.00%');
  });

  it('bridges a hole in the series to the most recent earlier month present', () => {
    // March and April are missing outright, so May is measured against February.
    const bars = [
      ...monthBars(2024, 1, 100),
      ...monthBars(2024, 2, 110),
      ...monthBars(2024, 5, 55),
      istBar(2024, 6, 4, 55),
    ];
    const y2024 = rowNamed(gridOf(bars), '2024') ?? [];
    expect(y2024[1].text).toBe('');
    expect(y2024[2].text).toBe('10.00%');
    expect(y2024[3].text).toBe('');
    expect(y2024[4].text).toBe('');
    expect(y2024[5].text).toBe('-50.00%');
  });

  it('honours the starting year, and reports nothing before it', () => {
    const rows = gridOf(twoYears(), { startYear: 2024 });
    expect(rows.filter((r) => /^\d{4}$/.test(r[0]?.text ?? ''))).toHaveLength(1);
    expect(rows[1][0].text).toBe('2024');
    expect(tableOf(twoYears(), { startYear: 2026 })).toBeNull();
  });
});

describe('Seasonality first month in the data', () => {
  it('leaves it unmeasured: blank, unfilled, and not SKIP', () => {
    const bars = [
      ...monthBars(2024, 2, 100),
      ...monthBars(2024, 3, 110),
      istBar(2024, 4, 2, 110),
    ];
    const y2024 = rowNamed(gridOf(bars), '2024') ?? [];
    expect(y2024[2].text).toBe('');
    expect(y2024[2].bgColor).toBeUndefined();
    expect(y2024[3].text).toBe('10.00%');
  });

  it('keeps it out of the column metrics', () => {
    const rows = gridOf([
      ...monthBars(2024, 2, 100),
      ...monthBars(2024, 3, 110),
      istBar(2024, 4, 2, 110),
    ]);
    for (const label of ['Avgs:', 'StDev:', 'Pos%:']) {
      expect((rowNamed(rows, label) ?? [])[2].text).toBe('');
    }
    expect((rowNamed(rows, 'Avgs:') ?? [])[3].text).toBe('10.00%');
  });

  it('gives its year no row at all when it is that year\'s only month', () => {
    const rows = gridOf(twoYears());
    // December 2022 seeds the chain and nothing else, so 2022 never appears.
    expect(rowNamed(rows, '2022')).toBeUndefined();
    expect(rowNamed(rows, '2023')).toBeDefined();
  });
});

describe('Seasonality grid shape', () => {
  it('is thirteen columns wide on every row', () => {
    for (const row of gridOf(twoYears())) expect(row).toHaveLength(13);
  });

  it('leads with the year and month header row', () => {
    expect(texts(gridOf(twoYears())[0])).toEqual([
      'Year', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ]);
  });

  it('carries one header row, one row per year, a divider and three metrics', () => {
    const rows = gridOf(twoYears());
    // header + 2023 + 2024 + divider + Avgs + StDev + Pos%
    expect(rows).toHaveLength(7);
    expect(texts(rows[3]).every((t) => t === '')).toBe(true);
    expect(rows[4][0].text).toBe('Avgs:');
    expect(rows[5][0].text).toBe('StDev:');
    expect(rows[6][0].text).toBe('Pos%:');
  });

  it('drops each metrics row with its own input, and the divider with all three', () => {
    const bars = twoYears();
    expect(gridOf(bars, { showAvg: false })).toHaveLength(6);
    expect(rowNamed(gridOf(bars, { showAvg: false }), 'Avgs:')).toBeUndefined();
    expect(rowNamed(gridOf(bars, { showStDev: false }), 'StDev:')).toBeUndefined();
    expect(rowNamed(gridOf(bars, { showPos: false }), 'Pos%:')).toBeUndefined();

    const bare = gridOf(bars, { showAvg: false, showStDev: false, showPos: false });
    expect(bare).toHaveLength(3);
    expect(bare[2][0].text).toBe('2024');
  });

  it('computes the metrics over each month column', () => {
    const rows = gridOf(twoYears());
    const avgs = rowNamed(rows, 'Avgs:') ?? [];
    const stdev = rowNamed(rows, 'StDev:') ?? [];
    const pos = rowNamed(rows, 'Pos%:') ?? [];
    for (let m = 1; m <= 12; m++) {
      const col = [CHANGES_2023[m - 1], CHANGES_2024[m - 1]];
      expect(avgs[m].text).toBe(`${meanOf(col).toFixed(2)}%`);
      expect(stdev[m].text).toBe(stdevOf(col).toFixed(2));
      expect(pos[m].text).toBe(`${Math.round((100 * col.filter((x) => x >= 0).length) / 2)}%`);
    }
    // Hand-checked: January holds +25 and -20, March holds +100 twice.
    expect(avgs[1].text).toBe('2.50%');
    expect(stdev[1].text).toBe('31.82');
    expect(pos[1].text).toBe('50%');
    expect(avgs[3].text).toBe('100.00%');
    expect(stdev[3].text).toBe('0.00');
    expect(pos[3].text).toBe('100%');
    expect(pos[4].text).toBe('0%');
  });

  it('leaves a single-reading column without a sample deviation', () => {
    const bars = [
      ...monthBars(2024, 5, 100),
      ...monthBars(2024, 6, 110),
      istBar(2024, 7, 2, 110),
    ];
    const rows = gridOf(bars);
    expect((rowNamed(rows, 'Avgs:') ?? [])[6].text).toBe('10.00%');
    expect((rowNamed(rows, 'StDev:') ?? [])[6].text).toBe('');
    expect((rowNamed(rows, 'Pos%:') ?? [])[6].text).toBe('100%');
  });
});

describe('Seasonality colour ramp', () => {
  it('scales opacity with magnitude and saturates at the cutoff', () => {
    const y2023 = rowNamed(gridOf(twoYears(), { cutoffPercent: 100 }), '2023') ?? [];
    // +25 of a 100 cutoff is 0.1 + 0.4 * 0.25 = 0.2 alpha; +50 is 0.3.
    expect(y2023[1].bgColor).toBe('#08998133');
    expect(y2023[5].bgColor).toBe('#0899814d');
    expect(y2023[3].bgColor).toBe('#08998180');
    // At and above the cutoff the fill stops changing.
    const tight = rowNamed(gridOf(twoYears(), { cutoffPercent: 20 }), '2023') ?? [];
    expect(tight[1].bgColor).toBe('#08998180');
    expect(tight[3].bgColor).toBe('#08998180');
  });

  it('flips to the negative base colour at the same intensity', () => {
    const rows = gridOf(twoYears(), { cutoffPercent: 100 });
    const y2023 = rowNamed(rows, '2023') ?? [];
    // April fell 50 percent and May rose 50: one alpha, two bases.
    expect(y2023[4].bgColor).toBe('#F237454d');
    expect(y2023[5].bgColor).toBe('#0899814d');
    expect((rowNamed(rows, '2024') ?? [])[1].bgColor).toBe('#F237452e');
  });

  it('takes the base colours from the inputs', () => {
    const y2023 = rowNamed(
      gridOf(twoYears(), { cutoffPercent: 50, posColor: '#00ff00', negColor: '#ff0000' }),
      '2023',
    ) ?? [];
    expect(y2023[3].bgColor).toBe('#00ff0080');
    expect(y2023[4].bgColor).toBe('#ff000080');
  });

  it('saturates everything when the cutoff is zero', () => {
    const y2023 = rowNamed(gridOf(twoYears(), { cutoffPercent: 0 }), '2023') ?? [];
    expect(y2023[1].bgColor).toBe('#08998180');
    expect(y2023[2].bgColor).toBe('#F2374580');
  });

  it('fills the header, year and deviation cells with the neutral tint', () => {
    const rows = gridOf(twoYears());
    expect(rows[0][0].bgColor).toBe('#787b8633');
    expect((rowNamed(rows, '2023') ?? [])[0].bgColor).toBe('#787b8633');
    expect((rowNamed(rows, 'StDev:') ?? [])[6].bgColor).toBe('#787b8633');
    expect(rows[3][0].bgColor).toBe('#787b8633');
  });

  it('measures the positive share against a coin flip', () => {
    const rows = gridOf(twoYears());
    const pos = rowNamed(rows, 'Pos%:') ?? [];
    // March is positive in both years: 50 above the midpoint, which is where
    // that ramp saturates, so the cell reaches full intensity. April is the
    // mirror, and January's even split sits at the midpoint.
    expect(pos[3].bgColor).toBe('#08998180');
    expect(pos[4].bgColor).toBe('#F2374580');
    expect(pos[1].bgColor).toBe('#0899811a');
  });

  it('derives no ink of its own, leaving contrast to the primitive', () => {
    for (const row of gridOf(twoYears())) {
      for (const cell of row) expect(cell.textColor).toBeUndefined();
    }
  });
});

describe('Seasonality skipped months', () => {
  it('marks the month still forming as SKIP and keeps it out of the maths', () => {
    const bars: Bar[] = [...monthBars(2022, 12, SEED_CLOSE)];
    CLOSES_2023.forEach((c, i) => bars.push(...monthBars(2023, i + 1, c)));
    CLOSES_2024.forEach((c, i) => bars.push(...monthBars(2024, i + 1, c)));
    const rows = gridOf(bars);
    const y2024 = rowNamed(rows, '2024') ?? [];
    expect(y2024[12].text).toBe('SKIP');
    expect(y2024[12].bgColor).toBe('#787b8680');
    // December now holds 2023 alone: -50 percent, and no sample deviation.
    expect((rowNamed(rows, 'Avgs:') ?? [])[12].text).toBe('-50.00%');
    expect((rowNamed(rows, 'StDev:') ?? [])[12].text).toBe('');
    expect((rowNamed(rows, 'Pos%:') ?? [])[12].text).toBe('0%');
  });

  it('marks the months named in the ignored list', () => {
    const rows = gridOf(twoYears(), { ignoredMonths: '2023-03, 2024-07' });
    const y2023 = rowNamed(rows, '2023') ?? [];
    const y2024 = rowNamed(rows, '2024') ?? [];
    expect(y2023[3].text).toBe('SKIP');
    expect(y2023[3].bgColor).toBe('#787b8680');
    expect(y2024[7].text).toBe('SKIP');
    expect(y2024[3].text).toBe('100.00%');
    expect(y2023[7].text).toBe('25.00%');
    // An ignored month is withheld from the grid, not cut out of the chain:
    // April 2023 is still measured against March's close.
    expect(y2023[4].text).toBe('-50.00%');
    expect(y2024[8].text).toBe('-50.00%');
    // Each ignored month leaves one reading behind in its column.
    expect((rowNamed(rows, 'Avgs:') ?? [])[3].text).toBe('100.00%');
    expect((rowNamed(rows, 'Avgs:') ?? [])[7].text).toBe('25.00%');
  });

  it('ignores an unparsed or placeholder ignore list', () => {
    for (const spec of ['YYYY-MM, YYYY-MM', '', 'nonsense', '2023-13', '2023-3']) {
      const y2023 = rowNamed(gridOf(twoYears(), { ignoredMonths: spec }), '2023') ?? [];
      expect(texts(y2023)).not.toContain('SKIP');
    }
  });
});

describe('Seasonality table placement', () => {
  it('maps the three position choices onto the bottom of the pane', () => {
    expect(tableOf(twoYears(), { tablePosition: 'Left' })?.options?.position).toBe('bottom-left');
    expect(tableOf(twoYears(), { tablePosition: 'Center' })?.options?.position).toBe('bottom-center');
    expect(tableOf(twoYears(), { tablePosition: 'Right' })?.options?.position).toBe('bottom-right');
  });

  it('falls back to the centre for an unknown choice', () => {
    expect(tableOf(twoYears(), { tablePosition: 'Top' })?.options?.position).toBe('bottom-center');
    expect(tableOf(twoYears(), { tablePosition: 7 })?.options?.position).toBe('bottom-center');
  });

  it('sizes one column per grid column', () => {
    const widths = tableOf(twoYears())?.options?.cellWidth;
    expect(Array.isArray(widths)).toBe(true);
    expect(widths as readonly number[]).toHaveLength(13);
  });
});

describe('Seasonality degenerate input', () => {
  it('draws nothing when no month has completed', () => {
    expect(tableOf([])).toBeNull();
    expect(tableOf([istBar(2024, 3, 5, 100)])).toBeNull();
    expect(tableOf(monthBars(2024, 3, 100))).toBeNull();
    // One seed month and one forming month still leave nothing measurable.
    expect(tableOf([...monthBars(2024, 3, 100), istBar(2024, 4, 2, 110)])).toBeNull();
  });

  it('survives empty and single-bar input from both hooks', () => {
    const settings = defaults(SEASONALITY);
    expect(() => SEASONALITY.calc([], settings, {})).not.toThrow();
    expect(SEASONALITY.calc([], settings, {}).seasonality).toEqual([]);
    const one = [istBar(2024, 3, 5, 100)];
    expect(SEASONALITY.calc(one, settings, {}).seasonality).toEqual([null]);
    expect(() => tableOf([])).not.toThrow();
    expect(() => tableOf(one)).not.toThrow();
  });

  it('handles less than a full year of data', () => {
    const bars = [
      ...monthBars(2024, 8, 100),
      ...monthBars(2024, 9, 105),
      ...monthBars(2024, 10, 84),
      istBar(2024, 11, 4, 84),
    ];
    const rows = gridOf(bars);
    expect(rows).toHaveLength(6);
    const y2024 = rowNamed(rows, '2024') ?? [];
    expect(y2024[9].text).toBe('5.00%');
    expect(y2024[10].text).toBe('-20.00%');
    expect(y2024[1].text).toBe('');
  });

  it('skips a month whose predecessor closed at zero rather than dividing by it', () => {
    const bars = [
      ...monthBars(2023, 12, 100),
      ...monthBars(2024, 1, 0),
      ...monthBars(2024, 2, 10),
      ...monthBars(2024, 3, 11),
      istBar(2024, 4, 2, 11),
    ];
    const y2024 = rowNamed(gridOf(bars), '2024') ?? [];
    expect(y2024[1].text).toBe('-100.00%');
    expect(y2024[2].text).toBe('');
    expect(y2024[3].text).toBe('10.00%');
  });
});
