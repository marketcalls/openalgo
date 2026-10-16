/**
 * Consolidation and Breakout, checked against a bar series small enough to read
 * by eye. Every expectation below was worked out by hand from the definition,
 * bar by bar, before the study was run once.
 *
 * The fixture is built so the mother bars and the inside bars are obvious:
 *
 *   0  a seed bar, 99..101
 *   1  the mother, a wide 98..112
 *   2  inside     bodies 103..105
 *   3  inside     bodies 102..108
 *   4  inside     bodies 104..106
 *   5  BREAKS UP  body tops out at 115, above the mother's 112
 *   6  inside the new 109..116 mother that bar 5 became
 *   7  BREAKS DOWN body bottoms at 105, below 109
 *   8  escapes bar 7 immediately, one bar after it: too soon to be a breakout
 *   9  inside bar 8
 *
 * Bars 5 and 7 are the ones worth writing a file for. Each fires a marker read
 * off the range it broke, and each is the new mother by the time the range and
 * the tint are read, so neither carries a range value or an inside tint of its
 * own. Reading the mother once instead of twice loses both markers here, which
 * is exactly the failure that still looks plausible on a chart.
 */
import { describe, it, expect } from 'vitest';
import { CONSOLIDATION_BREAKOUT, SIGNAL_INDICATORS } from '../src/indicators/signals';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const T0 = 1700000000;
const bar = (i: number, open: number, high: number, low: number, close: number): Bar =>
  ({ time: T0 + i * 60, open, high, low, close, volume: 100 + i });

/** The hand-read series the header describes. */
const FIXTURE: Bar[] = [
  bar(0, 100, 101, 99, 100),
  bar(1, 100, 112, 98, 110),
  bar(2, 105, 107, 101, 103),
  bar(3, 102, 109, 100, 108),
  bar(4, 104, 108, 102, 106),
  bar(5, 110, 116, 109, 115),
  bar(6, 112, 115, 111, 114),
  bar(7, 108, 110, 104, 105),
  bar(8, 111, 114, 110, 113),
  bar(9, 111, 113, 110, 112),
];

/** Identical bars: a zero-width mother whose body sits exactly on both edges. */
const doji = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => bar(i, 100, 100, 100, 100));

/**
 * A run of identical bars, then one bar whose body clears the mother's high.
 * The mother is bar 1 (bar 0 and bar 1 can never be inside bars), so the break
 * lands at age `at - 1`, which is what the range-age gate is measured against.
 */
const runThenBreak = (at: number): Bar[] => [
  ...Array.from({ length: at }, (_, i) => bar(i, 100, 101, 99, 100)),
  bar(at, 100, 106, 99, 105),
];

const defaults = indicatorDefaults(CONSOLIDATION_BREAKOUT);
const run = (data: readonly Bar[], over: Record<string, unknown> = {}) =>
  CONSOLIDATION_BREAKOUT.calc(data, { ...defaults, ...over }, {});
const markersOf = (data: readonly Bar[], over: Record<string, unknown> = {}) => {
  const settings = { ...defaults, ...over };
  return CONSOLIDATION_BREAKOUT.markers?.({ bars: data, values: run(data, over), settings }) ?? [];
};
const barColorsOf = (data: readonly Bar[], over: Record<string, unknown> = {}) => {
  const settings = { ...defaults, ...over };
  return CONSOLIDATION_BREAKOUT.barColors?.({ bars: data, values: run(data, over), settings }) ?? [];
};
/** The bar indices a column has a value on. */
const hits = (col: readonly (number | null)[]): number[] =>
  col.reduce<number[]>((acc, v, i) => (v === null ? acc : [...acc, i]), []);
/** Marker bar indices, recovered from the fixture's one-minute spacing. */
const markerBars = (data: readonly Bar[], over: Record<string, unknown> = {}) =>
  markersOf(data, over).map((m) => (m.time - T0) / 60);

describe('Consolidation and Breakout: the descriptor', () => {
  it('joins the signal family under its catalogue id', () => {
    expect(SIGNAL_INDICATORS).toContain(CONSOLIDATION_BREAKOUT);
    expect(CONSOLIDATION_BREAKOUT.id).toBe('consolidation-breakout');
    expect(CONSOLIDATION_BREAKOUT.name).toBe('Consolidation and Breakout');
    expect(CONSOLIDATION_BREAKOUT.placement).toBe('onchart');
    expect(new Set(SIGNAL_INDICATORS.map((d) => d.id)).size).toBe(SIGNAL_INDICATORS.length);
  });

  it('declares the two toggles and four colours, and nothing else', () => {
    expect(defaults).toEqual({
      markbreakout: true,
      colorinside: true,
      bullBreakColor: '#00c853',
      bearBreakColor: '#ff5252',
      insideColor: '#000000',
      highlowColor: '#e91e63',
    });
  });

  it('draws both range rails from the one colour input, at a fixed width', () => {
    expect(CONSOLIDATION_BREAKOUT.plots.map((p) => p.key)).toEqual(['rangeHigh', 'rangeLow']);
    for (const plot of CONSOLIDATION_BREAKOUT.plots) {
      expect(plot.colorKey).toBe('highlowColor');
      expect(plot.style?.lineWidth).toBe(2);
    }
  });
});

describe('Consolidation and Breakout: the state machine', () => {
  it('plots the mother range only while the consolidation holds', () => {
    const v = run(FIXTURE);
    // Bar 0 is its own mother and prints its high and low. Bar 1 claims the
    // range, so it prints nothing, and bars 2 to 4 print bar 1's 112 and 98.
    expect(v.rangeHigh).toEqual([101, null, 112, 112, 112, null, 116, null, null, 114]);
    expect(v.rangeLow).toEqual([99, null, 98, 98, 98, null, 109, null, null, 110]);
  });

  it('breaks the rails at every bar that takes the range over', () => {
    const v = run(FIXTURE);
    // 1, 5, 7 and 8 each become the mother; the gap is the intended look.
    expect(hits(v.rangeHigh)).toEqual([0, 2, 3, 4, 6, 9]);
    expect(hits(v.rangeLow)).toEqual([0, 2, 3, 4, 6, 9]);
  });

  it('counts how long each bar has been inside the standing range', () => {
    expect(run(FIXTURE).insideAge).toEqual([null, null, 1, 2, 3, null, 1, null, null, 1]);
  });

  it('resets the mother on the bar that escapes it, not the bar after', () => {
    const v = run(FIXTURE);
    // Bar 5 escaped bar 1's range, so bar 6 is measured against bar 5's own
    // 109..116 rather than the 98..112 it left behind.
    expect(v.rangeHigh[6]).toBe(FIXTURE[5].high);
    expect(v.rangeLow[6]).toBe(FIXTURE[5].low);
    // And bar 9 against bar 8's, the mother that never produced a breakout.
    expect(v.rangeHigh[9]).toBe(FIXTURE[8].high);
    expect(v.rangeLow[9]).toBe(FIXTURE[8].low);
  });
});

describe('Consolidation and Breakout: the two reads of the mother', () => {
  it('marks the break against the range as it stood before the bar claimed it', () => {
    const v = run(FIXTURE);
    // 112 is bar 1's high and 109 is bar 5's low: each signal carries the level
    // it cleared, which is the level the bar itself has just replaced.
    expect(v.breakUp).toEqual([null, null, null, null, null, 112, null, null, null, null]);
    expect(v.breakDown).toEqual([null, null, null, null, null, null, null, 109, null, null]);
    expect(markerBars(FIXTURE)).toEqual([5, 7]);
  });

  it('leaves the breaking bar untinted and railless, having read the mother after', () => {
    const v = run(FIXTURE);
    // The same bar, both sides of the reassignment: it fires against the old
    // range and is the new range. Testing after the reassignment instead would
    // silence bar 5 (its body cannot clear its own high) and shift the study.
    expect(v.breakUp[5]).toBe(112);
    expect(v.insideAge[5]).toBeNull();
    expect(v.rangeHigh[5]).toBeNull();
    expect(v.rangeLow[5]).toBeNull();
    expect(barColorsOf(FIXTURE)[5]).toBeNull();

    expect(v.breakDown[7]).toBe(109);
    expect(v.insideAge[7]).toBeNull();
    expect(v.rangeHigh[7]).toBeNull();
    expect(barColorsOf(FIXTURE)[7]).toBeNull();
  });

  it('ignores a body that leaves the range one bar after the mother', () => {
    const v = run(FIXTURE);
    // Bar 8's body reaches 113 against bar 7's high of 110, and bar 1's reaches
    // 110 against bar 0's 101. Both are the mother's own follow-through at an
    // age of one, so neither is a breakout, and both still reset the mother.
    expect(v.breakUp[1]).toBeNull();
    expect(v.breakUp[8]).toBeNull();
    expect(v.rangeHigh[8]).toBeNull();
    expect(v.insideAge[8]).toBeNull();
  });

  it('stops calling it a breakout once the range is older than the cap', () => {
    // The mother is bar 1, so a break at bar 251 is 250 bars old and still
    // counts, and one at bar 252 is 251 bars old and does not.
    expect(markerBars(runThenBreak(251))).toEqual([251]);
    expect(markerBars(runThenBreak(252))).toEqual([]);
  });
});

describe('Consolidation and Breakout: markers and candle tint', () => {
  it('points each shape the way the body went, clear of the bar', () => {
    const marks = markersOf(FIXTURE);
    expect(marks).toEqual([
      {
        time: FIXTURE[5].time, position: 'belowBar',
        shape: 'triangleUp', size: 'small', color: '#00c853',
      },
      {
        time: FIXTURE[7].time, position: 'aboveBar',
        shape: 'triangleDown', size: 'small', color: '#ff5252',
      },
    ]);
  });

  it('takes the breakout colours from the settings', () => {
    const marks = markersOf(FIXTURE, { bullBreakColor: '#123456', bearBreakColor: '#654321' });
    expect(marks.map((m) => m.color)).toEqual(['#123456', '#654321']);
  });

  it('draws no markers when the breakout toggle is off, and keeps the columns', () => {
    expect(markersOf(FIXTURE, { markbreakout: false })).toEqual([]);
    expect(run(FIXTURE, { markbreakout: false }).breakUp[5]).toBe(112);
  });

  it('tints every inside bar and no other, one colour per bar', () => {
    const I = '#000000';
    expect(barColorsOf(FIXTURE)).toEqual([null, null, I, I, I, null, I, null, null, I]);
    expect(barColorsOf(FIXTURE, { insideColor: '#101010' })[2]).toBe('#101010');
  });

  it('leaves every candle alone when the tint is off', () => {
    const colors = barColorsOf(FIXTURE, { colorinside: false });
    expect(colors.length).toBe(FIXTURE.length);
    expect(colors.every((c) => c === null)).toBe(true);
  });
});

describe('Consolidation and Breakout: degenerate series', () => {
  it('treats a body sitting exactly on both edges as inside', () => {
    // Every bar is the same zero-range doji, so the mother has no width at all
    // and the inclusive test is the only thing keeping the consolidation alive.
    const v = run(doji(6));
    expect(v.rangeHigh).toEqual([100, null, 100, 100, 100, 100]);
    expect(v.rangeLow).toEqual([100, null, 100, 100, 100, 100]);
    expect(v.insideAge).toEqual([null, null, 1, 2, 3, 4]);
    expect(markerBars(doji(6))).toEqual([]);
    expect(hits(v.breakUp)).toEqual([]);
    expect(hits(v.breakDown)).toEqual([]);
  });

  it('returns five empty columns for an empty series', () => {
    const v = run([]);
    expect(Object.keys(v).sort()).toEqual(
      ['breakDown', 'breakUp', 'insideAge', 'rangeHigh', 'rangeLow'],
    );
    for (const col of Object.values(v)) expect(col).toEqual([]);
    expect(markersOf([])).toEqual([]);
    expect(barColorsOf([])).toEqual([]);
  });

  it('seeds the first range from a single bar and never signals on it', () => {
    const one = [FIXTURE[0]];
    const v = run(one);
    expect(v.rangeHigh).toEqual([101]);
    expect(v.rangeLow).toEqual([99]);
    expect(v.insideAge).toEqual([null]);
    expect(v.breakUp).toEqual([null]);
    expect(v.breakDown).toEqual([null]);
    expect(barColorsOf(one)).toEqual([null]);
  });

  it('hands the range to the second bar, which can be neither inside nor a break', () => {
    const two = FIXTURE.slice(0, 2);
    const v = run(two);
    expect(v.rangeHigh).toEqual([101, null]);
    expect(v.rangeLow).toEqual([99, null]);
    expect(v.breakUp).toEqual([null, null]);
    expect(markersOf(two)).toEqual([]);
  });

  it('returns full-length columns of finite numbers or null', () => {
    const wave: Bar[] = Array.from({ length: 300 }, (_, i) => {
      const c = 100 + Math.sin(i / 7) * 6 + Math.cos(i / 3) * 2;
      return bar(i, c - 0.4, c + 1.2, c - 1.4, c + 0.3);
    });
    const v = run(wave);
    for (const [key, col] of Object.entries(v)) {
      expect(col.length, `${key} length`).toBe(wave.length);
      for (const value of col) {
        if (value === null) continue;
        expect(Number.isFinite(value), `${key} holds ${value}`).toBe(true);
      }
    }
    expect(barColorsOf(wave).length).toBe(wave.length);
  });
});
