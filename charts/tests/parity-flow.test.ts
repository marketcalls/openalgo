/**
 * Parity regression tests for the volume and money-flow descriptors.
 *
 * Every expectation here is worked out by hand from the standard definition of
 * the indicator and written as arithmetic, never copied back out of a run. A
 * test that records what the code currently does cannot fail when the code
 * changes, which is the whole point of the file.
 */
import { describe, it, expect } from 'vitest';
import {
  CHAIKIN_MONEY_FLOW,
  EASE_OF_MOVEMENT,
  NET_VOLUME,
  FLOW_INDICATORS,
} from '../src/indicators/flow';
import { OBV, ADL } from '../src/indicators/volume';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const defaults = (d: IndicatorDescriptor): Record<string, unknown> => indicatorDefaults(d);

/** A bar with an explicit close and volume, and a two-wide range around it. */
const bar = (i: number, close: number, volume: number): Bar => ({
  time: 1700000000 + i * 60,
  open: close,
  high: close + 1,
  low: close - 1,
  close,
  volume,
});

const firstValue = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

describe('Net Volume', () => {
  // Closes 100, 102, 102, 99, 101 against volumes 500, 300, 400, 250, 0.
  //   bar 0  no previous close, so neither direction holds:            0
  //   bar 1  close rose, the whole bar's volume counts positive:    +300
  //   bar 2  close unchanged, so neither direction holds:               0
  //   bar 3  close fell, the whole bar's volume counts negative:    -250
  //   bar 4  close rose but the bar traded nothing:                    0
  const seq: Bar[] = [
    bar(0, 100, 500),
    bar(1, 102, 300),
    bar(2, 102, 400),
    bar(3, 99, 250),
    bar(4, 101, 0),
  ];

  it('signs the bar\'s own volume by the direction of its close', () => {
    const out = NET_VOLUME.calc(seq, defaults(NET_VOLUME), {});
    // The plus zero only normalises a negative zero, which -volume produces on
    // a down bar that traded nothing and which toEqual would otherwise reject.
    expect(out.net.map((v) => (v === null ? null : (v as number) + 0)))
      .toEqual([0, 300, 0, -250, 0]);
  });

  it('has no warmup gap: the first bar prints zero rather than null', () => {
    const out = NET_VOLUME.calc(seq, defaults(NET_VOLUME), {});
    expect(firstValue(out.net)).toBe(0);
    expect(out.net[0]).toBe(0);
  });

  it('prints zero for an unchanged close instead of carrying the last sign', () => {
    expect(NET_VOLUME.calc(seq, defaults(NET_VOLUME), {}).net[2]).toBe(0);
  });

  it('prints zero for a bar that traded nothing, in either direction', () => {
    const down: Bar[] = [bar(0, 100, 500), bar(1, 90, 0)];
    expect(NET_VOLUME.calc(seq, defaults(NET_VOLUME), {}).net[4]).toBe(0);
    // A down bar negates the volume, so an empty one comes back as a negative
    // zero. It plots and serialises as zero, so the plus normalises it here
    // rather than costing the descriptor an instruction per bar to hide it.
    expect((NET_VOLUME.calc(down, defaults(NET_VOLUME), {}).net[1] as number) + 0).toBe(0);
  });

  it('treats a missing volume as no trade rather than as a hole', () => {
    const noVol: Bar[] = [bar(0, 100, 500), { ...bar(1, 105, 0), volume: undefined }];
    expect(NET_VOLUME.calc(noVol, defaults(NET_VOLUME), {}).net[1]).toBe(0);
  });

  it('is registered, in its own pane, alongside the other flow studies', () => {
    expect(FLOW_INDICATORS.map((d) => d.id)).toContain('net-volume');
    expect(NET_VOLUME.name).toBe('Net Volume');
    expect(NET_VOLUME.placement).toBe('pane');
    expect(NET_VOLUME.category).toBe('Volume');
    // One column, and its colour comes from a declared colour input.
    expect(NET_VOLUME.plots).toHaveLength(1);
    const colorKey = NET_VOLUME.plots[0].colorKey;
    expect(NET_VOLUME.inputs.find((i) => i.key === colorKey)?.type).toBe('color');
  });

  it('takes no parameters, so nothing about it is tunable by accident', () => {
    expect(NET_VOLUME.inputs.filter((i) => i.type !== 'color')).toEqual([]);
  });
});

describe('On-Balance Volume smoothing length', () => {
  // Ten bars, each closing higher on 100 shares, so the running total is
  // 0, 100, 200, ... 900 and every window mean is exact.
  const rising: Bar[] = Array.from({ length: 10 }, (_, i) => bar(i, 100 + i, 100));

  it('defaults its smoothing length to 9, the length the definition fixes', () => {
    expect(defaults(OBV).maLength).toBe(9);
  });

  it('lands the first smoothed value at index 8 with that default', () => {
    const out = OBV.calc(rising, { ...defaults(OBV), maType: 'SMA' }, {});
    // Window 0..8 of 0, 100, ... 800 averages 400. Window 1..9 averages 500.
    expect(out.ma[7]).toBeNull();
    expect(out.ma[8]).toBeCloseTo(400, 12);
    expect(out.ma[9]).toBeCloseTo(500, 12);
  });

  it('places the bands at the population deviation of that same window', () => {
    const out = OBV.calc(rising, { ...defaults(OBV), maType: 'SMA + Bollinger Bands', bbMult: 2 }, {});
    // Deviations from 400 are -400 -300 -200 -100 0 100 200 300 400, so the
    // population variance is 100^2 * (16+9+4+1+0+1+4+9+16) / 9 = 100^2 * 60/9.
    const sd = 100 * Math.sqrt(60 / 9);
    expect(out.bbUpper[8]).toBeCloseTo(400 + 2 * sd, 9);
    expect(out.bbLower[8]).toBeCloseTo(400 - 2 * sd, 9);
  });

  it('still draws no smoothed line until one is asked for', () => {
    expect(defaults(OBV).maType).toBe('None');
    expect(OBV.calc(rising, defaults(OBV), {}).ma.every((v) => v === null)).toBe(true);
  });
});

describe('zero-denominator handling across the family', () => {
  /** A bar with no range at all: high, low and close coincide. */
  const flat = (i: number, price: number, volume: number): Bar => ({
    time: 1700000000 + i * 60,
    open: price,
    high: price,
    low: price,
    close: price,
    volume,
  });

  it('contributes nothing for a rangeless bar rather than blanking the A/D line', () => {
    // Bar 0 closes at its high: multiplier +1, so the line sits at +10.
    // Bar 1 has no range, so it adds nothing and the line holds at +10.
    const seq: Bar[] = [
      { time: 1, open: 100, high: 102, low: 98, close: 102, volume: 10 },
      flat(2, 102, 40),
    ];
    const out = ADL.calc(seq, defaults(ADL), {});
    expect(out.adl[0]).toBeCloseTo(10, 12);
    expect(out.adl[1]).toBeCloseTo(10, 12);
  });

  it('keeps Chaikin Money Flow finite when the whole window is rangeless', () => {
    const seq: Bar[] = [flat(0, 100, 10), flat(1, 100, 20)];
    // Zero flow over 30 traded shares is a clean zero, not a division fault.
    expect(CHAIKIN_MONEY_FLOW.calc(seq, { length: 2 }, {}).cmf[1]).toBe(0);
  });

  it('gaps Chaikin Money Flow only when the window traded nothing at all', () => {
    const seq: Bar[] = [flat(0, 100, 0), flat(1, 100, 0)];
    expect(CHAIKIN_MONEY_FLOW.calc(seq, { length: 2 }, {}).cmf[1]).toBeNull();
  });

  it('gaps Ease of Movement for a zero-volume bar instead of emitting Infinity', () => {
    const seq: Bar[] = [
      { time: 1, open: 100, high: 102, low: 98, close: 100, volume: 10 },
      { time: 2, open: 102, high: 104, low: 100, close: 102, volume: 0 },
    ];
    expect(EASE_OF_MOVEMENT.calc(seq, { length: 1, divisor: 10000 }, {}).eom[1]).toBeNull();
  });
});
