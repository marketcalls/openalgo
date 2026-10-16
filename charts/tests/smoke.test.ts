import { describe, it, expect } from 'vitest';
import pkg from '../package.json';
import { version, VERSION } from '../src/index';
import { clamp, lerp, roundToTick } from '../src/helpers/math';
import { generateBars } from '../src/feed/fake-feed';
import { isWhitespace } from '../src/model/bar';

describe('package smoke', () => {
  it('exposes a version string', () => {
    expect(typeof version()).toBe('string');
    expect(version()).toBe(VERSION);
  });

  it('keeps the exported VERSION in step with package.json', () => {
    // `VERSION` is hand-maintained and had drifted four patches behind the
    // published version, so consumers reading it were told the wrong release.
    expect(VERSION).toBe(pkg.version);
  });
});

describe('helpers/math', () => {
  it('clamps into range', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(11, 0, 10)).toBe(10);
  });

  it('lerps endpoints', () => {
    expect(lerp(0, 10, 0)).toBe(0);
    expect(lerp(0, 10, 1)).toBe(10);
    expect(lerp(0, 10, 0.5)).toBe(5);
  });

  it('rounds to tick size and snaps sub-tick prices', () => {
    expect(roundToTick(100.07, 0.05)).toBeCloseTo(100.05, 10);
    expect(roundToTick(100.13, 0.05)).toBeCloseTo(100.15, 10);
    expect(roundToTick(42, 0)).toBe(42); // step <= 0 is a no-op
  });
});

describe('fake feed', () => {
  it('generates a deterministic, valid OHLC series', () => {
    const a = generateBars(1_700_000_000, 50, 60);
    const b = generateBars(1_700_000_000, 50, 60);
    expect(a).toEqual(b); // deterministic across runs
    expect(a).toHaveLength(50);
    for (const bar of a) {
      expect(bar.high).toBeGreaterThanOrEqual(Math.max(bar.open, bar.close));
      expect(bar.low).toBeLessThanOrEqual(Math.min(bar.open, bar.close));
    }
    // strictly increasing, evenly spaced timestamps (gapless logical index basis)
    for (let i = 1; i < a.length; i++) {
      expect(a[i].time - a[i - 1].time).toBe(60);
    }
  });
});

describe('whitespace detection', () => {
  it('distinguishes whitespace from data points', () => {
    expect(isWhitespace({ time: 1 })).toBe(true);
    expect(isWhitespace({ time: 1, value: 5 })).toBe(false);
    expect(isWhitespace({ time: 1, open: 1, high: 2, low: 0, close: 1 })).toBe(false);
  });
});
