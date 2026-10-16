/**
 * Price-scale modes: the rebasing pair (percentage, indexed-to-100) plus proof
 * that adding them left linear and logarithmic bit for bit where they were.
 */
import { describe, it, expect } from 'vitest';
import { PriceScale, type PriceScaleMode } from '../src/scale/price-scale';
import { niceTicks, precisionForStep } from '../src/scale/ticks';
import { drawPriceAxis, priceTickCount, type PlotLayout } from '../src/render/axis';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

/**
 * The pre-change implementation, transcribed. Linear and log must still agree
 * with this for every input, so the reference lives here rather than being
 * approximated by hand-picked expected numbers.
 */
class ReferenceScale {
  public constructor(
    private readonly mode: 'linear' | 'logarithmic',
    private readonly height: number,
    private readonly min: number,
    private readonly max: number,
    private readonly inverted = false,
    private readonly minMove = 0,
  ) {}

  private t(v: number): number {
    return this.mode === 'logarithmic' ? Math.log10(Math.max(1e-10, v)) : v;
  }

  private tInv(c: number): number {
    return this.mode === 'logarithmic' ? Math.pow(10, c) : c;
  }

  public priceToY(price: number): number {
    const lo = this.t(this.min);
    const span = this.t(this.max) - lo;
    if (span <= 0) return this.height / 2;
    const r = (this.t(price) - lo) / span;
    return this.inverted ? this.height * r : this.height * (1 - r);
  }

  public yToPrice(y: number): number {
    const lo = this.t(this.min);
    const span = this.t(this.max) - lo;
    const r = this.inverted ? y / this.height : 1 - y / this.height;
    return this.tInv(lo + r * span);
  }

  public precision(): number {
    if (this.minMove > 0) return precisionForStep(this.minMove);
    return precisionForStep((this.max - this.min) / 100);
  }

  public format(price: number): string {
    return price.toFixed(this.precision());
  }

  /** What src/render/axis.ts built inline: nice ticks over the price range. */
  public ticks(maxTicks = 6): number[] {
    return niceTicks(this.min, this.max, maxTicks);
  }
}

function makeScale(mode: PriceScaleMode, baseline: number | null = null): PriceScale {
  const ps = new PriceScale({ mode });
  ps.setHeight(400);
  ps.setPriceRange({ min: 90, max: 110 });
  ps.setBaseline(baseline);
  return ps;
}

describe('percentage mode', () => {
  it('puts the baseline at zero percent and maps the range around it', () => {
    const ps = makeScale('percentage', 100);
    // 90..110 around a baseline of 100 is -10%..+10%, so the baseline is centred.
    expect(ps.priceToY(100)).toBeCloseTo(200, 9);
    expect(ps.priceToY(110)).toBeCloseTo(0, 9);
    expect(ps.priceToY(90)).toBeCloseTo(400, 9);
    // Halfway up the top half is +5%, i.e. 105.
    expect(ps.yToPrice(100)).toBeCloseTo(105, 9);
  });

  it('round-trips priceToY and yToPrice', () => {
    const ps = makeScale('percentage', 97.25);
    for (const price of [90, 93.7, 100, 104.125, 110]) {
      expect(ps.yToPrice(ps.priceToY(price))).toBeCloseTo(price, 9);
    }
    for (const y of [0, 37, 200, 399.5, 400]) {
      expect(ps.priceToY(ps.yToPrice(y))).toBeCloseTo(y, 9);
    }
  });

  it('labels percent change with an explicit sign', () => {
    const ps = makeScale('percentage', 100);
    expect(ps.format(103.42)).toBe('+3.42%');
    expect(ps.format(96.58)).toBe('-3.42%');
    expect(ps.format(100)).toBe('0.00%');
    // A hair below the baseline still reads as zero, not as "-0.00%".
    expect(ps.format(99.999999)).toBe('0.00%');
  });

  it('re-bases the labels when the baseline moves, without moving the pixels', () => {
    const ps = makeScale('percentage', 100);
    const at105 = ps.priceToY(105);
    expect(ps.format(105)).toBe('+5.00%');
    ps.setBaseline(105); // what a pan does: a new first visible bar
    expect(ps.format(105)).toBe('0.00%');
    expect(ps.format(110)).toBe('+4.76%');
    // The rebase is affine over a price-space range, so it relabels the pane
    // rather than reshaping it. Only the ladder underneath the prices moved.
    expect(ps.priceToY(105)).toBeCloseTo(at105, 9);
  });

  it('tracks the drag 1:1 when panned, like the linear scale', () => {
    const ps = makeScale('percentage', 100);
    const y0 = ps.priceToY(103);
    ps.panByPixels(40);
    expect(ps.priceToY(103)).toBeCloseTo(y0 + 40, 6);
    expect(ps.autoScale).toBe(false);
  });
});

describe('indexed-to-100 mode', () => {
  it('rebases the baseline to 100 and scales proportionally', () => {
    const ps = makeScale('indexed-to-100', 100);
    expect(ps.format(103.42)).toBe('103.42');
    expect(ps.format(100)).toBe('100.00');
    expect(ps.format(96.58)).toBe('96.58');
  });

  it('works off a baseline that is nothing like 100', () => {
    const ps = new PriceScale({ mode: 'indexed-to-100' });
    ps.setHeight(400);
    ps.setPriceRange({ min: 19000, max: 21000 });
    ps.setBaseline(20000);
    expect(ps.format(20000)).toBe('100.00');
    expect(ps.format(21000)).toBe('105.00');
    expect(ps.yToPrice(ps.priceToY(20500))).toBeCloseTo(20500, 6);
  });

  it('round-trips priceToY and yToPrice', () => {
    const ps = makeScale('indexed-to-100', 102.5);
    for (const price of [90, 95.5, 100, 107.75, 110]) {
      expect(ps.yToPrice(ps.priceToY(price))).toBeCloseTo(price, 9);
    }
  });

  it('shares its geometry with percentage and linear: only the labels differ', () => {
    // Both rebases are affine over a range held in price units, so the pane
    // keeps the shape a linear scale would draw. The mode buys the axis, not
    // a different curve.
    const linear = makeScale('linear');
    const pct = makeScale('percentage', 103);
    const idx = makeScale('indexed-to-100', 103);
    for (const price of [90, 96.25, 103, 110]) {
      expect(pct.priceToY(price)).toBeCloseTo(linear.priceToY(price), 9);
      expect(idx.priceToY(price)).toBeCloseTo(pct.priceToY(price), 9);
    }
    expect(idx.format(103)).toBe('100.00');
    expect(pct.format(103)).toBe('0.00%');
    expect(linear.format(103)).toBe('103.0'); // price precision, from the span
  });
});

describe('baseline handling', () => {
  it('falls back to the identity transform until a baseline arrives', () => {
    const linear = makeScale('linear');
    for (const mode of ['percentage', 'indexed-to-100'] as const) {
      const ps = makeScale(mode);
      expect(ps.baseline).toBeNull();
      for (const price of [90, 100, 110]) {
        expect(ps.priceToY(price)).toBe(linear.priceToY(price));
        expect(ps.format(price)).toBe(linear.format(price));
      }
      expect(ps.ticks(6)).toEqual(linear.ticks(6));
    }
  });

  it('clears back to the identity when the baseline is set to null', () => {
    const ps = makeScale('percentage', 100);
    expect(ps.format(105)).toBe('+5.00%');
    ps.setBaseline(null);
    expect(ps.baseline).toBeNull();
    expect(ps.format(105)).toBe(makeScale('linear').format(105));
  });

  it('rejects a zero or negative baseline rather than inverting the axis', () => {
    // Zero has no percent change to report and a negative baseline flips the
    // sign of the transform, so both fall back to linear (documented choice).
    const linear = makeScale('linear');
    for (const bad of [0, -50, -0.01, NaN, Infinity, -Infinity]) {
      for (const mode of ['percentage', 'indexed-to-100'] as const) {
        const ps = makeScale(mode, bad);
        for (const price of [90, 100, 110]) {
          expect(ps.priceToY(price), `${mode} @ ${bad}`).toBe(linear.priceToY(price));
          expect(ps.yToPrice(price), `${mode} @ ${bad}`).toBe(linear.yToPrice(price));
        }
        expect(ps.format(105), `${mode} @ ${bad}`).toBe(linear.format(105));
        expect(ps.precision(), `${mode} @ ${bad}`).toBe(linear.precision());
      }
    }
  });

  it('never inverts: a rising price always draws upward in both modes', () => {
    for (const mode of ['percentage', 'indexed-to-100'] as const) {
      for (const baseline of [0.5, 100, 65000, -20, 0]) {
        const ps = makeScale(mode, baseline);
        expect(ps.priceToY(105), `${mode} @ ${baseline}`).toBeLessThan(ps.priceToY(95));
      }
    }
  });

  it('drops the baseline on reset, but leaves a manual scale alone', () => {
    const auto = makeScale('percentage', 100);
    auto.reset();
    expect(auto.baseline).toBeNull();

    const manual = makeScale('percentage', 100);
    manual.setAutoScale(false);
    manual.reset();
    expect(manual.baseline).toBe(100);
  });

  it('ignores the baseline in linear and logarithmic modes', () => {
    for (const mode of ['linear', 'logarithmic'] as const) {
      const withBase = makeScale(mode, 100);
      const without = makeScale(mode);
      expect(withBase.priceToY(105)).toBe(without.priceToY(105));
      expect(withBase.format(105)).toBe(without.format(105));
    }
  });
});

describe('formatting and the tick ladder', () => {
  it('overrides a custom price formatter while a rebase is in force', () => {
    const ps = makeScale('percentage', 100);
    ps.setPriceFormatter((p) => `INR ${p.toFixed(1)}`);
    expect(ps.format(105)).toBe('+5.00%');
    // The formatter is ignored, not lost: it returns when the mode does.
    ps.setOptions({ mode: 'linear' });
    expect(ps.format(105)).toBe('INR 105.0');
  });

  it('ignores minMove for rebased precision but keeps it for snapping', () => {
    const ps = new PriceScale({ mode: 'percentage', minMove: 0.05 });
    ps.setHeight(400);
    ps.setPriceRange({ min: 90, max: 110 });
    ps.setBaseline(100);
    expect(ps.precision()).toBe(2); // not precisionForStep(0.05)'s price reading
    expect(ps.snapToTick(100.07)).toBeCloseTo(100.05, 9);
  });

  it('tightens precision when the visible band is under a percent', () => {
    const ps = new PriceScale({ mode: 'percentage' });
    ps.setHeight(400);
    ps.setPriceRange({ min: 99.8, max: 100.2 });
    ps.setBaseline(100);
    expect(ps.precision()).toBeGreaterThan(2);
    expect(ps.format(100.05)).toMatch(/^\+0\.050+%$/);
  });

  it('builds the ladder on round percentages, not on round prices', () => {
    const ps = makeScale('percentage', 100);
    expect(ps.ticks(6).map((p) => ps.format(p)))
      .toEqual(['-10.00%', '-5.00%', '0.00%', '+5.00%', '+10.00%']);
  });

  it('keeps the ladder round on a baseline that is not a round number', () => {
    const ps = new PriceScale({ mode: 'percentage' });
    ps.setHeight(400);
    ps.setBaseline(64123.45);
    ps.autoscale(63000, 65000);
    const labels = ps.ticks(6).map((p) => ps.format(p));
    expect(labels.length).toBeGreaterThan(1);
    for (const label of labels) expect(label).toMatch(/^[+-]?\d+(\.\d+)?%$/);
    // Evenly spaced, and every rung a multiple of that spacing.
    const values = labels.map((l) => Number(l.replace('%', '')));
    const step = values[1] - values[0];
    for (let i = 1; i < values.length; i++) expect(values[i] - values[i - 1]).toBeCloseTo(step, 6);
    for (const v of values) expect(Math.abs(v / step - Math.round(v / step))).toBeLessThan(1e-6);
  });

  it('labels the indexed ladder as index points', () => {
    const ps = makeScale('indexed-to-100', 100);
    expect(ps.ticks(6).map((p) => ps.format(p)))
      .toEqual(['90.00', '95.00', '100.00', '105.00', '110.00']);
  });
});

describe('autoscale under every mode', () => {
  const modes: PriceScaleMode[] = ['linear', 'logarithmic', 'percentage', 'indexed-to-100'];

  it('produces a finite, ordered, on-pane range', () => {
    for (const mode of modes) {
      const ps = new PriceScale({ mode });
      ps.setHeight(400);
      ps.setBaseline(100);
      ps.autoscale(95, 105);
      const r = ps.priceRange();
      expect(Number.isFinite(r.min), mode).toBe(true);
      expect(r.max, mode).toBeGreaterThan(r.min);
      expect(ps.priceToY(105), mode).toBeGreaterThan(0);
      expect(ps.priceToY(95), mode).toBeLessThan(400);
      expect(ps.priceToY(105), mode).toBeLessThan(ps.priceToY(95));
      expect(ps.scaled, mode).toBe(true);
    }
  });

  it('leaves the data the same 80 percent of the pane as linear does', () => {
    // The rebasing transforms are affine with a positive factor, so a margin
    // measured in price space is the same margin in percent space.
    for (const mode of ['linear', 'percentage', 'indexed-to-100'] as const) {
      const ps = new PriceScale({ mode });
      ps.setHeight(400);
      ps.setBaseline(100);
      ps.autoscale(95, 105);
      expect(ps.priceToY(95) - ps.priceToY(105), mode).toBeCloseTo(320, 6);
    }
  });

  it('leaves the data 80 percent of the pane on a log scale too, whatever the price span', () => {
    // The margins used to be padded in price units and then drawn in log
    // units. A monthly series from 150 to 1230 got a floor near 15, a whole
    // empty decade under the lowest bar, and its bars filled the top 42
    // percent of the pane (issue #53). The margins are fractions of the pane
    // in every mode, so a log scale pads in log space.
    for (const [low, high] of [[150, 1230], [95, 105], [0.5, 4000]] as const) {
      const ps = new PriceScale({ mode: 'logarithmic' });
      ps.setHeight(400);
      ps.autoscale(low, high);
      expect(ps.priceToY(high), `${low}..${high}`).toBeCloseTo(40, 6);
      expect(ps.priceToY(low), `${low}..${high}`).toBeCloseTo(360, 6);
    }
  });

  it('keeps a log scale drawable for data at or below zero', () => {
    // There is no log of zero: such a range keeps the price-space margins
    // rather than reaching for a floor ten decades down.
    const ps = new PriceScale({ mode: 'logarithmic' });
    ps.setHeight(400);
    ps.autoscale(0, 100);
    const r = ps.priceRange();
    expect(Number.isFinite(r.min)).toBe(true);
    expect(r.max).toBeGreaterThan(100);
  });

  it('gives a log scale the same fallback as a linear one for an unbounded range', () => {
    // A finite low and an infinite high have a log, but no padding: taken in
    // log space the fallback range 0..1 came back as 1..10.
    for (const [low, high] of [[5, Infinity], [5, NaN]] as const) {
      const linear = new PriceScale();
      const log = new PriceScale({ mode: 'logarithmic' });
      linear.autoscale(low, high);
      log.autoscale(low, high);
      expect(log.priceRange(), `${low}..${high}`).toEqual(linear.priceRange());
    }
  });

  it('survives a flat series in the rebasing modes', () => {
    for (const mode of ['percentage', 'indexed-to-100'] as const) {
      const ps = new PriceScale({ mode });
      ps.setHeight(400);
      ps.setBaseline(100);
      ps.autoscale(100, 100);
      expect(Number.isFinite(ps.priceToY(100)), mode).toBe(true);
      expect(ps.priceToY(100), mode).toBeCloseTo(200, 6);
      expect(ps.format(100), mode).toMatch(mode === 'percentage' ? /^0\.00%$/ : /^100\.00$/);
    }
  });

  it('handles a series that autoscales below its baseline', () => {
    const ps = new PriceScale({ mode: 'percentage' });
    ps.setHeight(400);
    ps.setBaseline(100);
    ps.autoscale(80, 90); // panned into a window entirely under the baseline
    expect(ps.format(90)).toBe('-10.00%');
    expect(ps.priceToY(90)).toBeLessThan(ps.priceToY(80));
    expect(ps.yToPrice(ps.priceToY(85))).toBeCloseTo(85, 6);
  });
});

describe('linear and logarithmic are unchanged', () => {
  const ranges: [number, number][] = [[90, 110], [0.0001, 0.0009], [19800, 20450], [1, 1000]];
  const prices = [0.0005, 1, 95, 100.05, 110, 20000, 999];

  it('matches the pre-change transform, precision, format and ladder', () => {
    for (const mode of ['linear', 'logarithmic'] as const) {
      for (const [min, max] of ranges) {
        for (const inverted of [false, true]) {
          for (const minMove of [0, 0.05]) {
            const ps = new PriceScale({ mode, inverted, minMove });
            ps.setHeight(400);
            ps.setPriceRange({ min, max });
            // A baseline is present but must be inert in these modes.
            ps.setBaseline(100);
            const ref = new ReferenceScale(mode, 400, min, max, inverted, minMove);
            const where = `${mode} [${min},${max}] inv=${inverted} mm=${minMove}`;
            expect(ps.precision(), where).toBe(ref.precision());
            expect(ps.ticks(6), where).toEqual(ref.ticks(6));
            for (const price of prices) {
              expect(ps.priceToY(price), `${where} @ ${price}`).toBe(ref.priceToY(price));
              expect(ps.format(price), `${where} @ ${price}`).toBe(ref.format(price));
            }
            for (const y of [0, 1, 133.5, 400]) {
              expect(ps.yToPrice(y), `${where} @ y${y}`).toBe(ref.yToPrice(y));
            }
          }
        }
      }
    }
  });

  it('keeps a linear scale on its custom price formatter', () => {
    const ps = makeScale('linear');
    ps.setPriceFormatter((p) => `${p.toFixed(3)} USD`);
    expect(ps.format(105)).toBe('105.000 USD');
  });

  it('keeps the degenerate-span guard', () => {
    const ps = new PriceScale({ mode: 'percentage' });
    ps.setHeight(400);
    ps.setPriceRange({ min: 100, max: 100 });
    ps.setBaseline(100);
    expect(ps.priceToY(100)).toBe(200); // pane centre, not NaN
  });
});

/**
 * Every label evenly spaced, and every value a whole multiple of that spacing.
 * That is what "a round ladder" means, and it holds however many rungs the
 * pane height asks for.
 */
function expectRoundLadder(drawn: readonly (string | undefined)[], suffix = ''): void {
  const values = drawn.map((l) => Number(String(l).replace(suffix, '')));
  expect(values.length).toBeGreaterThan(2);
  for (const v of values) expect(Number.isFinite(v)).toBe(true);
  const step = values[1] - values[0];
  expect(Math.abs(step)).toBeGreaterThan(0);
  for (let i = 1; i < values.length; i++) expect(values[i] - values[i - 1]).toBeCloseTo(step, 6);
  for (const v of values) expect(Math.abs(v / step - Math.round(v / step))).toBeLessThan(1e-6);
}

describe('the drawn axis reads the scale ladder', () => {
  const layout: PlotLayout = {
    plotWidth: 700, plotHeight: 400, priceAxisWidth: 60, timeAxisHeight: 24, plotLeft: 0,
  };
  const labels = (rec: RecordingContext): (string | undefined)[] =>
    rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text);

  /**
   * A baseline that is not a round number, so the two candidate ladders differ:
   * round prices land on '-1.75%, -0.97%, ...', round percentages on '-1.50%,
   * -1.00%, ...'. A round baseline maps one onto the other and would pass
   * either way, which is how the renderers kept their own ladder unnoticed.
   */
  const offBaseline = (mode: PriceScaleMode): PriceScale => {
    const ps = new PriceScale({ mode });
    ps.setHeight(400);
    ps.setBaseline(64123.45);
    ps.setPriceRange({ min: 63000, max: 65000 });
    return ps;
  };

  it('labels a percentage axis on round percentages, not on round prices', () => {
    const ps = offBaseline('percentage');
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, layout, 1);
    // Asserted as a property, not a golden list: the label count follows the
    // pane height, but "round percentages" does not. A renderer building its
    // own ladder on round prices would give -1.75%, -0.97%, -0.19% ..., which
    // is neither evenly spaced nor a multiple of its own step.
    expectRoundLadder(labels(rec), '%');
  });

  it('labels the left axis from the same ladder', () => {
    const ps = offBaseline('indexed-to-100');
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, { ...layout, plotLeft: 60 }, 1, undefined, undefined, 'left');
    expectRoundLadder(labels(rec));
  });

  it('leaves a linear axis on the prices it always drew', () => {
    const ps = makeScale('linear');
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, layout, 1);
    // Less the rungs within half a tag of the pane's edges (90 and 110 here),
    // whose labels the edges would cut in half.
    const whole = (p: number): boolean => {
      const y = Math.round(ps.priceToY(p));
      return y >= 8 && y <= layout.plotHeight - 8;
    };
    expect(labels(rec))
      .toEqual(niceTicks(90, 110, priceTickCount(layout.plotHeight)).filter(whole).map((p) => ps.format(p)));
  });
});
