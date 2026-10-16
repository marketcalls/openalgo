import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { CHOP_ZONE } from '../src/indicators/volatility';

const settings: IndicatorSettings = indicatorDefaults(CHOP_ZONE);

/**
 * High sits 3 above the close and low 7 below, deliberately asymmetric: a
 * symmetric bar makes the 30-bar high-low range and the 30-bar high range
 * differ by a constant, which is exactly the case that hides this defect.
 */
const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 3, low: c - 7, close: c, volume: 100 };
  });

const angles = (data: readonly Bar[]): readonly (number | null)[] => CHOP_ZONE.calc(data, settings, {}).angle;

/**
 * The definition, transcribed from scratch rather than shared with the
 * descriptor: a 30-bar rolling range of the **high** series rescales the slope
 * of a 34-bar SMA-seeded EMA of close, measured against hlc3 over one bar.
 */
function referenceAngles(data: readonly Bar[]): (number | null)[] {
  const n = data.length;
  const periods = 30;
  const emaLength = 34;
  const highs = data.map((b) => b.high);
  const rolling = (i: number, pick: (a: number, b: number) => number): number => {
    if (i < periods - 1) return NaN;
    let m = highs[i];
    for (let k = 1; k < periods; k++) m = pick(m, highs[i - k]);
    return m;
  };
  const ema = new Array<number>(n).fill(NaN);
  if (n >= emaLength) {
    let sum = 0;
    for (let i = 0; i < emaLength; i++) sum += data[i].close;
    let prev = sum / emaLength;
    ema[emaLength - 1] = prev;
    const k = 2 / (emaLength + 1);
    for (let i = emaLength; i < n; i++) {
      prev = data[i].close * k + prev * (1 - k);
      ema[i] = prev;
    }
  }
  const out = new Array<number | null>(n).fill(null);
  for (let i = 1; i < n; i++) {
    const hi = rolling(i, Math.max);
    const lo = rolling(i, Math.min);
    const range = hi - lo;
    const hlc3 = (data[i].high + data[i].low + data[i].close) / 3;
    if (!(range > 0) || hlc3 === 0) continue;
    const dy = ((ema[i - 1] - ema[i]) / hlc3) * ((25 / range) * lo);
    if (!Number.isFinite(dy)) continue;
    const degrees = Math.round((180 * Math.acos(1 / Math.sqrt(1 + dy * dy))) / (Math.atan(1) * 4));
    out[i] = dy > 0 ? -degrees : degrees;
  }
  return out;
}

describe('Chop Zone rescales the slope against the high series', () => {
  it('reads +35 degrees on a one-per-bar advance, not the 26 a high-low range gives', () => {
    // close = 100 + i, so the 34-bar EMA settles exactly on close - 16.5 and
    // its one-bar drop is exactly -1. At bar 39: highest(high, 30) = 142,
    // lowest(high, 30) = 113, range 29, span = 25 / 29 * 113 = 97.41379...,
    // hlc3 = 139 - 4/3 = 137.66667, dy = -97.41379 / 137.66667 = -0.7075979,
    // hyp = sqrt(1.5006948) = 1.2250285, acos(1 / hyp) = 0.615786 rad
    // = 35.28 degrees, rounded to 35, and the drop is negative so the sign
    // flip leaves it positive. Reading the lows instead would put
    // lowest(low, 30) at 103, span at 66.02564, dy at -0.4795442 and the
    // angle at 26.
    const out = angles(bars(40, (i) => 100 + i));
    expect(out[39]).toBe(35);
    expect(out[34]).toBe(35);
  });

  it('reads -42 degrees on the mirrored decline', () => {
    expect(angles(bars(40, (i) => 200 - i))[39]).toBe(-42);
  });

  it('matches the definition bar for bar on a wave that turns', () => {
    const data = bars(60, (i) => 500 + 20 * Math.sin(i / 4) + i * 0.3);
    const out = angles(data);
    expect(out).toEqual(referenceAngles(data));
    // Anchors hand-checked against the same arithmetic, so a reference that
    // drifted with the descriptor could not carry this test on its own.
    expect([out[34], out[40], out[45], out[50], out[55], out[59]]).toEqual([28, -17, -22, 16, 38, 29]);
  });

  it('still starts at bar 34 and still plots the constant column', () => {
    const data = bars(60, (i) => 500 + 20 * Math.sin(i / 4) + i * 0.3);
    const out = CHOP_ZONE.calc(data, settings, {});
    expect(out.angle.findIndex((v) => v !== null)).toBe(34);
    expect(out.chopZone.every((v) => v === 1)).toBe(true);
  });
});
