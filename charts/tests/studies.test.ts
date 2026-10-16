import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { CPR, ALPHATREND, RANGE_ANALYSIS, STUDY_INDICATORS } from '../src/indicators/studies';

/** 2024-01-01T00:00:00Z, which is 05:30 on 1 January in IST. */
const T0 = 1704067200;

/** 09:30 IST on the given IST calendar date, in UTC seconds. IST has no daylight shift. */
const istMorning = (y: number, m: number, d: number): number => Date.UTC(y, m - 1, d, 4) / 1000;

/**
 * Hourly bars, so the 200-bar sweep series spans eight IST days and the pivot
 * study has boundaries to find. Range widens on a three-bar cycle so nothing
 * here depends on a constant high-low spread.
 */
const wave = (n = 200): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 5) * 10 + i * 0.05;
    return {
      time: T0 + i * 3600,
      open: c,
      high: c + 1 + (i % 3) * 0.5,
      low: c - 1 - (i % 3) * 0.5,
      close: c,
      volume: 100 + (i % 7) * 10,
    };
  });

/**
 * Closes stepping by `slope` with the high and low one point either side. True
 * range is then exactly 2 on every bar including the first, so a simple average
 * of it is 2 as soon as the window fills and every level below is hand-checkable.
 */
const ramp = (n: number, slope: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + i * slope;
    return { time: T0 + i * 3600, open: c, high: c + 1, low: c - 1, close: c, volume: 1000 };
  });

/** `count` bars `stepDays` apart, starting 09:30 IST on the given date. */
const spacedSeries = (count: number, y: number, m: number, d: number, stepDays = 1): Bar[] =>
  Array.from({ length: count }, (_, i) => {
    const c = 100 + i;
    return {
      time: istMorning(y, m, d) + i * stepDays * 86400,
      open: c, high: c + 2, low: c - 2, close: c, volume: 500,
    };
  });

/** One bar per listed IST date, closes stepping by one so every frame is distinct. */
const datedSeries = (dates: readonly (readonly [number, number, number])[]): Bar[] =>
  dates.map(([y, m, d], i) => {
    const c = 100 + i;
    return { time: istMorning(y, m, d), open: c, high: c + 2, low: c - 2, close: c, volume: 500 };
  });

const defaults = (d: IndicatorDescriptor): IndicatorSettings => indicatorDefaults(d);
const withSettings = (d: IndicatorDescriptor, over: IndicatorSettings): IndicatorSettings =>
  ({ ...indicatorDefaults(d), ...over });
const firstNonNull = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);
const allNull = (col: readonly (number | null)[]): boolean => col.every((v) => v === null);
const anyValue = (col: readonly (number | null)[]): boolean => col.some((v) => v !== null);

/** Every column belonging to one pivot period. */
const periodKeys = (prefix: string): string[] =>
  ['Pivot', 'S1', 'S2', 'S3', 'R1', 'R2', 'R3', 'Bc', 'Tc'].map((k) => `${prefix}${k}`);

describe('study descriptors', () => {
  const data = wave();

  it('exports the three studies under their published ids', () => {
    expect(STUDY_INDICATORS.map((d) => d.id)).toEqual(['cpr', 'alphatrend', 'range-analysis']);
    expect(CPR.placement).toBe('onchart');
    expect(ALPHATREND.placement).toBe('onchart');
    expect(RANGE_ANALYSIS.placement).toBe('pane');
    expect(RANGE_ANALYSIS.category).toBe('Volatility');
  });

  it('gives every plot a colour key that resolves to a declared input', () => {
    for (const d of STUDY_INDICATORS) {
      for (const plot of d.plots) {
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.key}`).toBe('color');
      }
      for (const fill of d.fills ?? []) {
        for (const key of [fill.colorUpKey, fill.colorDownKey]) {
          const declared = d.inputs.find((i) => i.key === key);
          expect(declared?.type, `${d.id} fill ${String(key)}`).toBe('color');
        }
      }
    }
  });

  it('returns a full-length column of finite numbers or null for every key', () => {
    for (const d of STUDY_INDICATORS) {
      const values = d.calc(data, defaults(d), {});
      for (const plot of d.plots) expect(values[plot.key], `${d.id}.${plot.key} missing`).toBeDefined();
      // Columns that only feed the marker layer are held to the same contract.
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${d.id}.${key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty, single-bar and volume-less input', () => {
    const noVolume = data.slice(0, 40).map((b) => ({ ...b, volume: undefined }));
    for (const d of STUDY_INDICATORS) {
      for (const input of [[], data.slice(0, 1), noVolume]) {
        const values = d.calc(input, defaults(d), {});
        for (const plot of d.plots) expect(values[plot.key].length, d.id).toBe(input.length);
        for (const col of Object.values(values)) {
          for (const v of col) expect(v === null || Number.isFinite(v), d.id).toBe(true);
        }
      }
    }
  });
});

// ── CPR with Floor Pivot ─────────────────────────────────────────────────────

/**
 * Three IST sessions of three hourly bars each. Session one spans 85..120 and
 * closes at 108, which is the frame every bar of session two must carry.
 */
const sessions = (): Bar[] => {
  const shape: [number, number, number][][] = [
    [[110, 90, 100], [120, 95, 105], [115, 85, 108]],
    [[130, 100, 120], [140, 110, 135], [138, 118, 130]],
    [[150, 140, 145], [152, 141, 150], [151, 139, 148]],
  ];
  const out: Bar[] = [];
  shape.forEach((day, d) => {
    day.forEach(([high, low, close], i) => {
      // 09:30 IST plus one hour per bar, so every bar of a day shares its date.
      out.push({
        time: istMorning(2024, 1, 1 + d) + i * 3600,
        open: close, high, low, close, volume: 500,
      });
    });
  });
  return out;
};

describe('CPR with Floor Pivot: the daily frame', () => {
  const bars = sessions();
  const values = CPR.calc(bars, defaults(CPR), {});

  it('is null through the first session, which has nothing behind it', () => {
    for (const key of ['dPivot', 'dS2', 'dS3', 'dR2', 'dR3', 'dBc', 'dTc']) {
      expect(firstNonNull(values[key]), key).toBe(3);
    }
  });

  it('holds one frozen frame across the whole of the following session', () => {
    // Session one: high 120, low 85, close 108.
    const pivot = (120 + 85 + 108) / 3;
    expect(values.dPivot[3]).toBeCloseTo(pivot, 12);
    expect(values.dPivot[4]).toBe(values.dPivot[3]);
    expect(values.dPivot[5]).toBe(values.dPivot[3]);
    // Session two: high 140, low 100, close 130. The frame steps at the boundary.
    expect(values.dPivot[6]).toBeCloseTo((140 + 100 + 130) / 3, 12);
    expect(values.dPivot[6]).not.toBe(values.dPivot[5]);
  });

  it('derives every level from the previous session', () => {
    const pivot = (120 + 85 + 108) / 3;
    const width = 120 - 85;
    const s1 = 2 * pivot - 120;
    const r1 = 2 * pivot - 85;
    expect(values.dS2[3]).toBeCloseTo(pivot - width, 12);
    expect(values.dS3[3]).toBeCloseTo(s1 - width, 12);
    expect(values.dR2[3]).toBeCloseTo(pivot + width, 12);
    expect(values.dR3[3]).toBeCloseTo(r1 + width, 12);
    expect(values.dBc[3]).toBeCloseTo((120 + 85) / 2, 12);
  });

  it('places the top and bottom of the central range symmetrically about the pivot', () => {
    for (let i = 3; i < bars.length; i++) {
      const p = values.dPivot[i] as number;
      const bc = values.dBc[i] as number;
      const tc = values.dTc[i] as number;
      expect(tc - p).toBeCloseTo(p - bc, 12);
    }
  });

  it('keeps S1 and R1 hidden by default and computes them when asked', () => {
    // Their plot calls are commented out in the published script, so the
    // default has to be all-null rather than a visible extra pair of levels.
    expect(allNull(values.dS1)).toBe(true);
    expect(allNull(values.dR1)).toBe(true);
    const shown = CPR.calc(bars, withSettings(CPR, { displayS1R1: true }), {});
    const pivot = (120 + 85 + 108) / 3;
    expect(shown.dS1[3]).toBeCloseTo(2 * pivot - 120, 12);
    expect(shown.dR1[3]).toBeCloseTo(2 * pivot - 85, 12);
    expect(firstNonNull(shown.dS1)).toBe(3);
  });

  it('blanks a whole group when its switch is off and leaves the others alone', () => {
    const hidden = CPR.calc(bars, withSettings(CPR, {
      displaypivots: false, displaysupport: false, displaycpr: false,
    }), {});
    for (const key of ['dPivot', 'dS1', 'dS2', 'dS3', 'dBc', 'dTc']) {
      expect(allNull(hidden[key]), key).toBe(true);
    }
    expect(firstNonNull(hidden.dR2)).toBe(3);
  });
});

describe('CPR with Floor Pivot: period selection', () => {
  it('auto mode picks the frame one step coarser than the bars', () => {
    const hourly = CPR.calc(sessions(), defaults(CPR), {});
    expect(anyValue(hourly.dPivot)).toBe(true);
    expect(allNull(hourly.wPivot)).toBe(true);
    expect(allNull(hourly.mPivot)).toBe(true);

    const daily = CPR.calc(spacedSeries(90, 2024, 1, 1), defaults(CPR), {});
    expect(anyValue(daily.wPivot)).toBe(true);
    expect(allNull(daily.dPivot)).toBe(true);
    expect(allNull(daily.mPivot)).toBe(true);

    const weekly = CPR.calc(spacedSeries(40, 2024, 1, 1, 7), defaults(CPR), {});
    expect(anyValue(weekly.mPivot)).toBe(true);
    expect(allNull(weekly.dPivot)).toBe(true);
    expect(allNull(weekly.wPivot)).toBe(true);
  });

  it('falls back to the daily frame when there is no spacing to measure', () => {
    // One bar has no gap at all, and a single bar can never resolve a frame,
    // so the answer is the daily set full of nulls rather than a throw.
    for (const bars of [[], sessions().slice(0, 1)]) {
      const values = CPR.calc(bars, defaults(CPR), {});
      for (const key of [...periodKeys('d'), ...periodKeys('w'), ...periodKeys('m')]) {
        expect(values[key].length, key).toBe(bars.length);
        expect(allNull(values[key]), key).toBe(true);
      }
    }
  });

  it('manual mode honours the three toggles independently', () => {
    const bars = spacedSeries(90, 2024, 1, 1);
    const manual = (over: IndicatorSettings): IndicatorSettings =>
      withSettings(CPR, { pivotMode: 'manual', ...over });

    const all = CPR.calc(bars, manual({ showDaily: true, showWeekly: true, showMonthly: true }), {});
    expect(anyValue(all.dPivot)).toBe(true);
    expect(anyValue(all.wPivot)).toBe(true);
    expect(anyValue(all.mPivot)).toBe(true);

    const weeklyOnly = CPR.calc(bars, manual({ showDaily: false, showWeekly: true, showMonthly: false }), {});
    expect(anyValue(weeklyOnly.wPivot)).toBe(true);
    for (const key of [...periodKeys('d'), ...periodKeys('m')]) {
      expect(allNull(weeklyOnly[key]), key).toBe(true);
    }

    const none = CPR.calc(bars, manual({ showDaily: false, showWeekly: false, showMonthly: false }), {});
    for (const key of [...periodKeys('d'), ...periodKeys('w'), ...periodKeys('m')]) {
      expect(allNull(none[key]), key).toBe(true);
    }
  });

  it('opens a weekly frame on the Monday-based week index, not on the weekend', () => {
    // 1 January 2024 is a Monday, so 4..7 January share a week and 8 January
    // opens the next one. Saturday and Sunday must not step the frame.
    const bars = datedSeries([
      [2024, 1, 4], [2024, 1, 5], [2024, 1, 6], [2024, 1, 7], [2024, 1, 8], [2024, 1, 9],
    ]);
    const values = CPR.calc(bars, withSettings(CPR, {
      pivotMode: 'manual', showDaily: false, showWeekly: true, showMonthly: false,
    }), {});
    expect(firstNonNull(values.wPivot)).toBe(4);
    // That first week ran 102..105 high, 98..101 low, closing at 103.
    expect(values.wPivot[4]).toBeCloseTo((105 + 98 + 103) / 3, 12);
    expect(values.wPivot[5]).toBe(values.wPivot[4]);
  });

  it('opens a monthly frame on the IST month change, across a year end', () => {
    const bars = datedSeries([
      [2024, 12, 30], [2024, 12, 31], [2025, 1, 1], [2025, 1, 2],
    ]);
    const values = CPR.calc(bars, withSettings(CPR, {
      pivotMode: 'manual', showDaily: false, showWeekly: false, showMonthly: true,
    }), {});
    expect(firstNonNull(values.mPivot)).toBe(2);
    // December contributed two bars: high 103, low 98, close 101.
    expect(values.mPivot[2]).toBeCloseTo((103 + 98 + 101) / 3, 12);
    expect(values.mPivot[3]).toBe(values.mPivot[2]);
  });

  it('keeps the top and bottom of every active frame symmetric about its pivot', () => {
    const bars = spacedSeries(90, 2024, 1, 1);
    const values = CPR.calc(bars, withSettings(CPR, {
      pivotMode: 'manual', showDaily: true, showWeekly: true, showMonthly: true,
    }), {});
    for (const p of ['d', 'w', 'm']) {
      for (let i = 0; i < bars.length; i++) {
        const pivot = values[`${p}Pivot`][i];
        if (pivot === null) continue;
        expect((values[`${p}Tc`][i] as number) - pivot).toBeCloseTo(
          pivot - (values[`${p}Bc`][i] as number), 12,
        );
      }
    }
  });
});

// ── AlphaTrend ───────────────────────────────────────────────────────────────

describe('AlphaTrend', () => {
  it('tracks the lower band exactly on a ramp whose true range is a constant 2', () => {
    // Every bar: high-low is 2 and both gaps to the previous close are 2 or 0,
    // so the 14-bar mean of true range is 2 from index 13. With the multiplier
    // at 1 the rising branch is low - 2, which on this ramp is 97 + i.
    const bars = ramp(40, 1);
    const values = ALPHATREND.calc(bars, withSettings(ALPHATREND, { novolumedata: true }), {});
    expect(values.alphatrend[13]).toBeNull();
    expect(values.alphatrend[14]).toBeCloseTo(111, 12);
    expect(values.alphatrend[20]).toBeCloseTo(117, 12);
    expect(values.alphatrend[39]).toBeCloseTo(136, 12);
  });

  it('starts at the common period whether the gauge is money flow or the index', () => {
    const bars = ramp(40, 1);
    const flow = ALPHATREND.calc(bars, defaults(ALPHATREND), {});
    const index = ALPHATREND.calc(bars, withSettings(ALPHATREND, { novolumedata: true }), {});
    // An all-up ramp has no down-flow and no down-close, so both gauges pin high
    // and both resolve on the same bar: the mean of true range is ready one bar
    // earlier, and the gauge is what gates the first value.
    expect(firstNonNull(flow.alphatrend)).toBe(14);
    expect(firstNonNull(index.alphatrend)).toBe(14);
    expect(flow.alphatrend[14]).toBeCloseTo(111, 12);
  });

  it('never decreases while the rising leg holds', () => {
    const bars = ramp(60, 1);
    const values = ALPHATREND.calc(bars, defaults(ALPHATREND), {});
    let prev = -Infinity;
    for (const v of values.alphatrend) {
      if (v === null) continue;
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });

  it('clamps to zero on a falling leg, because the recursion seeds from zero', () => {
    // The published recursion reads its own previous value through a
    // null-coalescing zero, so the falling branch takes the smaller of the upper
    // band and that zero and stays pinned until the first rising leg.
    const bars = ramp(40, -1);
    const values = ALPHATREND.calc(bars, withSettings(ALPHATREND, { novolumedata: true }), {});
    expect(values.alphatrend[13]).toBeNull();
    expect(values.alphatrend[14]).toBe(0);
    expect(values.alphatrend[30]).toBe(0);
  });

  it('lags the second line by exactly two bars', () => {
    const bars = ramp(40, 1);
    const values = ALPHATREND.calc(bars, defaults(ALPHATREND), {});
    expect(firstNonNull(values.lagged)).toBe(16);
    for (let i = 2; i < bars.length; i++) expect(values.lagged[i]).toBe(values.alphatrend[i - 2]);
  });

  it('anchors every marker to a real bar time and to the lagged line', () => {
    const bars = wave();
    const settings = defaults(ALPHATREND);
    const values = ALPHATREND.calc(bars, settings, {});
    const markers = ALPHATREND.markers?.({ bars, values, settings }) ?? [];
    expect(markers.length).toBeGreaterThan(0);
    const times = new Set(bars.map((b) => b.time));
    for (const m of markers) {
      expect(times.has(m.time)).toBe(true);
      expect(m.position).toBe('atPrice');
      expect(Number.isFinite(m.price as number)).toBe(true);
      expect(['labelUp', 'labelDown']).toContain(m.shape);
      expect(m.text === 'BUY' || m.text === 'SELL').toBe(true);
      // Buy sits a hair under the lagged line, sell a hair over it.
      const i = bars.findIndex((b) => b.time === m.time);
      const lag = values.lagged[i] as number;
      expect(m.price).toBeCloseTo(lag * (m.text === 'BUY' ? 0.9999 : 1.0001), 12);
    }
  });

  it('never fires the same side twice in a row', () => {
    // Each signal is gated on how long ago the other side last fired, which is
    // what stops a run of buys inside one leg.
    const bars = wave();
    const settings = defaults(ALPHATREND);
    const values = ALPHATREND.calc(bars, settings, {});
    const markers = ALPHATREND.markers?.({ bars, values, settings }) ?? [];
    for (let i = 1; i < markers.length; i++) expect(markers[i].text).not.toBe(markers[i - 1].text);
  });

  it('drops the whole marker layer and both signal columns when signals are off', () => {
    const bars = wave();
    const settings = withSettings(ALPHATREND, { showsignalsk: false });
    const values = ALPHATREND.calc(bars, settings, {});
    expect(ALPHATREND.markers?.({ bars, values, settings })).toEqual([]);
    expect(allNull(values.buySignal)).toBe(true);
    expect(allNull(values.sellSignal)).toBe(true);
  });
});

// ── Range Analysis ───────────────────────────────────────────────────────────

describe('Range Analysis', () => {
  it('reports the bar range from the very first bar', () => {
    const bars = ramp(10, 1);
    const values = RANGE_ANALYSIS.calc(bars, defaults(RANGE_ANALYSIS), {});
    expect(firstNonNull(values.range)).toBe(0);
    // High and low sit one point either side of the close on every bar.
    for (const v of values.range) expect(v).toBeCloseTo(2, 12);
  });

  it('tracks a widening range bar for bar', () => {
    const bars = wave(12);
    const values = RANGE_ANALYSIS.calc(bars, defaults(RANGE_ANALYSIS), {});
    for (let i = 0; i < bars.length; i++) {
      expect(values.range[i]).toBeCloseTo(bars[i].high - bars[i].low, 12);
    }
  });

  it('leaves the average off by default, matching the commented-out plot', () => {
    const bars = wave(12);
    const off = RANGE_ANALYSIS.calc(bars, defaults(RANGE_ANALYSIS), {});
    expect(allNull(off.avgRange)).toBe(true);
    expect(off.avgRange.length).toBe(bars.length);
  });

  it('averages the last three ranges once switched on', () => {
    const bars = wave(12);
    const on = RANGE_ANALYSIS.calc(bars, withSettings(RANGE_ANALYSIS, { showAverage: true }), {});
    expect(firstNonNull(on.avgRange)).toBe(2);
    const expected = (bars[0].high - bars[0].low + (bars[1].high - bars[1].low) + (bars[2].high - bars[2].low)) / 3;
    expect(on.avgRange[2]).toBeCloseTo(expected, 12);
  });
});

/**
 * Five-minute bars for `days` consecutive New York regular sessions
 * (13:30-20:00 UTC), skipping weekends, each spanning exactly `range` points.
 *
 * A New York session straddles IST midnight, so this is the fixture that told
 * the old calendar-day rule apart from reading the session out of the bars.
 */
function nySessions(days: number, range = 4): Bar[] {
  const bars: Bar[] = [];
  let d = 5; // 2024-03-05 is a Tuesday
  for (let s = 0; s < days; s++) {
    while ([0, 6].includes(new Date(Date.UTC(2024, 2, d)).getUTCDay())) d++;
    const base = 100 + s;
    for (let k = 0; k < 78; k++) {
      const t = Math.floor(Date.UTC(2024, 2, d, 13, 30) / 1000) + k * 300;
      bars.push({
        time: t, open: base, close: base, volume: 1000,
        high: k === 20 ? base + range / 2 : base + 0.1,
        low: k === 50 ? base - range / 2 : base - 0.1,
      });
    }
    d++;
  }
  return bars;
}

describe('CPR daily pivots', () => {
  it('builds each frame from one session, not from two half sessions', () => {
    // Each session spans exactly 4 points, so width is 4 and S3 sits 3 widths
    // below the previous high. Splicing two half sessions would widen it.
    const bars = nySessions(4, 4);
    const v = CPR.calc(bars, { pivotMode: 'auto' }, {});
    const last = bars.length - 1;
    const prevHigh = 102 + 2; // session index 2, base 102, +range/2
    const prevLow = 102 - 2;
    const prevClose = 102;
    const p = (prevHigh + prevLow + prevClose) / 3;
    expect(v.dPivot?.[last]).toBeCloseTo(p, 10);
    expect(v.dS3?.[last]).toBeCloseTo(2 * p - prevHigh - (prevHigh - prevLow), 10);
    // The whole frame is 4 wide, so no level can be more than ~12 from the pivot.
    for (const key of ['dS2', 'dS3', 'dR2', 'dR3'] as const) {
      const val = v[key]?.[last];
      expect(val).not.toBeNull();
      expect(Math.abs((val as number) - p)).toBeLessThanOrEqual(12.001);
    }
  });

  it('starts a new frame at the open of every session', () => {
    const bars = nySessions(5, 4);
    const v = CPR.calc(bars, { pivotMode: 'auto' }, {});
    const pivots = v.dPivot ?? [];
    const changes: number[] = [];
    for (let i = 1; i < bars.length; i++) if (pivots[i] !== pivots[i - 1]) changes.push(i);
    for (const i of changes) {
      const d = new Date(bars[i].time * 1000);
      expect([d.getUTCHours(), d.getUTCMinutes()]).toEqual([13, 30]);
    }
  });
});
