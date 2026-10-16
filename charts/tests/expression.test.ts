/**
 * Symbol arithmetic: parsing what a trader types into the search box, and
 * folding the legs into one synthetic series.
 *
 * The parser half is ordinary and exhaustively checkable. The evaluation half
 * is where the care is: open and close are exact, the high and low are a
 * bound, and the tests below pin down which is which so a later "optimisation"
 * cannot quietly turn the bound into a guess.
 */
import { describe, it, expect } from 'vitest';
import {
  parseExpression, evaluateExpression, isPlainSymbol, ExpressionError,
} from '../src/transform/expression';
import type { Bar } from '../src/model/bar';

const bar = (time: number, o: number, h: number, l: number, c: number): Bar =>
  ({ time, open: o, high: h, low: l, close: c });
/** A flat bar, for the cases where only the close matters. */
const flat = (time: number, v: number): Bar => bar(time, v, v, v, v);

describe('optional combined leg volume', () => {
  it.each(['A+B', 'A-B', '2*A+B', 'A+A+B', 'A/B'])(
    'sums each distinct leg once for %s without weighting its traded activity', source => {
      const expr = parseExpression(source);
      const legs = { A: [{ ...flat(60, 10), volume: 20 }], B: [{ ...flat(60, 5), volume: 30 }] };
      expect(evaluateExpression(expr, legs)[0]).not.toHaveProperty('volume');
      expect(evaluateExpression(expr, legs, { volume: 'sum' })[0].volume).toBe(50);
    },
  );
  it('retains zero but does not invent volume for a missing, invalid or overflowing leg amount', () => {
    const expr = parseExpression('A+B');
    for (const value of [undefined, NaN, Infinity, -1]) {
      const legs = { A: [{ ...flat(60, 10), volume: 20 }], B: [{ ...flat(60, 5), volume: value }] };
      expect(evaluateExpression(expr, legs, { volume: 'sum' })[0]).not.toHaveProperty('volume');
    }
    for (const [amount, expected] of [[0, 0], [Number.MAX_VALUE, undefined]]) {
      const legs = { A: [{ ...flat(60, 10), volume: amount }], B: [{ ...flat(60, 5), volume: amount }] };
      expect(evaluateExpression(expr, legs, { volume: 'sum' })[0].volume).toBe(expected);
    }
  });
});

describe('parseExpression', () => {
  it('reports the symbols it needs, in first-seen order, before any fetch', () => {
    expect(parseExpression('NIFTY1!/NSE:RELIANCE').symbols).toEqual(['NIFTY1!', 'NSE:RELIANCE']);
    expect(parseExpression('(A+B)/(A+C)').symbols).toEqual(['A', 'B', 'C']);
  });

  it('accepts a bare symbol, so one code path serves plain and synthetic charts', () => {
    expect(parseExpression('NIFTY1!').symbols).toEqual(['NIFTY1!']);
    expect(isPlainSymbol('NIFTY1!')).toBe(true);
    expect(isPlainSymbol('NIFTY1!/RELIANCE')).toBe(false);
    expect(isPlainSymbol('')).toBe(false);
  });

  it('takes the punctuation real tickers carry', () => {
    for (const s of ['NSE:RELIANCE', 'NIFTY1!', 'BTCUSDT.P', 'ES1!', 'BSE:500325', 'A_B']) {
      expect(parseExpression(s).symbols).toEqual([s]);
    }
  });

  it('takes a hyphenated ticker in quotes, since bare - is subtraction', () => {
    expect(parseExpression("'BRK-B'/SPY").symbols).toEqual(['BRK-B', 'SPY']);
    expect(parseExpression('"BRK-B"').symbols).toEqual(['BRK-B']);
    // Unquoted, it is A minus B and that is the only sane reading.
    expect(parseExpression('BRK-B').symbols).toEqual(['BRK', 'B']);
  });

  it('accepts the glyphs the on-screen keypad prints', () => {
    expect(evalOne('A÷B', { A: 10, B: 4 })).toBe(2.5);   // divide
    expect(evalOne('A×B', { A: 10, B: 4 })).toBe(40);    // multiply
    expect(evalOne('A−B', { A: 10, B: 4 })).toBe(6);     // minus
  });

  it('honours precedence and associativity', () => {
    expect(evalOne('A+B*C', { A: 1, B: 2, C: 3 })).toBe(7);
    expect(evalOne('(A+B)*C', { A: 1, B: 2, C: 3 })).toBe(9);
    expect(evalOne('A-B-C', { A: 10, B: 3, C: 2 })).toBe(5);       // left assoc
    expect(evalOne('A/B/C', { A: 12, B: 3, C: 2 })).toBe(2);       // left assoc
    expect(evalOne('A^B^C', { A: 2, B: 3, C: 2 })).toBe(512);      // right assoc: 2^(3^2)
    expect(evalOne('-A+B', { A: 3, B: 10 })).toBe(7);
    expect(evalOne('1/A', { A: 4 })).toBe(0.25);
  });

  it('supports the function set', () => {
    expect(evalOne('abs(A-B)', { A: 3, B: 10 })).toBe(7);
    expect(evalOne('sqrt(A)', { A: 9 })).toBe(3);
    expect(evalOne('max(A,B)', { A: 3, B: 10 })).toBe(10);
    expect(evalOne('min(A,B)', { A: 3, B: 10 })).toBe(3);
    expect(evalOne('pow(A,B)', { A: 2, B: 10 })).toBe(1024);
    expect(evalOne('ln(A)', { A: Math.E })).toBeCloseTo(1, 12);
  });

  it('points at the offending character so a search box can underline it', () => {
    const cases: [string, number][] = [
      ['A//B', 2], ['A+', 2], ['(A+B', 0], ['A$B', 1], ['A+*B', 2],
    ];
    for (const [src, pos] of cases) {
      let caught: ExpressionError | null = null;
      try { parseExpression(src); } catch (e) { caught = e as ExpressionError; }
      expect(caught, src).toBeInstanceOf(ExpressionError);
      expect(caught!.position, src).toBe(pos);
    }
    expect(() => parseExpression('')).toThrow(ExpressionError);
    expect(() => parseExpression('2+2')).toThrow(/names no symbol/);
    expect(() => parseExpression('max(A)')).toThrow(/takes 2 arguments/);
  });
});

/** Evaluate a one-bar expression over flat legs and return the close. */
function evalOne(src: string, closes: Record<string, number>): number {
  const legs: Record<string, Bar[]> = {};
  for (const [k, v] of Object.entries(closes)) legs[k] = [flat(1000, v)];
  const out = evaluateExpression(parseExpression(src), legs);
  return out[0].close;
}

describe('evaluateExpression', () => {
  it('folds two legs onto the primary time grid', () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [flat(1000, 100), flat(1060, 110), flat(1120, 120)],
      B: [flat(1000, 10), flat(1060, 11), flat(1120, 10)],
    });
    expect(out.map((b) => b.close)).toEqual([10, 10, 12]);
    expect(out.map((b) => b.time)).toEqual([1000, 1060, 1120]);
  });

  it('gaps a bar the other leg did not trade, rather than carrying one forward', () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [flat(1000, 100), flat(1060, 110), flat(1120, 120)],
      B: [flat(1000, 10), flat(1120, 10)],
    });
    // A ratio against a price from another minute was never true, so 1060 is absent.
    expect(out.map((b) => b.time)).toEqual([1000, 1120]);
  });

  it('gaps rather than spiking when the divisor reaches zero', () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [flat(1000, 100), flat(1060, 100)],
      B: [flat(1000, 0), flat(1060, 4)],
    });
    expect(out.map((b) => b.time)).toEqual([1060]);
    expect(out.every((b) => Number.isFinite(b.close))).toBe(true);
  });

  it('returns nothing when a named leg was never supplied', () => {
    const e = parseExpression('A/B');
    expect(evaluateExpression(e, { A: [flat(1000, 1)] })).toEqual([]);
    expect(evaluateExpression(e, {})).toEqual([]);
  });

  it('takes its time grid from the first symbol, or from `primary`', () => {
    const e = parseExpression('A/B');
    const legs = {
      A: [flat(1000, 100), flat(1060, 110)],
      B: [flat(1000, 10), flat(1060, 11), flat(1120, 12)],
    };
    expect(evaluateExpression(e, legs).map((b) => b.time)).toEqual([1000, 1060]);
    expect(evaluateExpression(e, legs, { primary: 'B' }).map((b) => b.time)).toEqual([1000, 1060]);
  });

  it("defaults to close-only, so the bar is flat and every value is exact", () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [bar(1000, 100, 150, 90, 120)],
      B: [bar(1000, 10, 12, 8, 10)],
    });
    const b = out[0];
    expect(b.open).toBe(10);   // 100/10, both opens, simultaneous by definition
    expect(b.close).toBe(12);  // 120/10
    // No claim is made about the path between them beyond what open and close prove.
    expect(b.high).toBe(12);
    expect(b.low).toBe(10);
  });

  it("bounds the high and low under ohlc:'interval', and the bound contains the truth", () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [bar(1000, 100, 150, 90, 120)],
      B: [bar(1000, 10, 12, 8, 10)],
    }, { ohlc: 'interval' });
    const b = out[0];
    expect(b.open).toBe(10);
    expect(b.close).toBe(12);
    // Widest the ratio could have been: A at its high while B was at its low.
    expect(b.high).toBe(150 / 8);
    expect(b.low).toBe(90 / 12);
    // The bound is wider than open/close alone, and contains them.
    expect(b.high).toBeGreaterThan(Math.max(b.open, b.close));
    expect(b.low).toBeLessThan(Math.min(b.open, b.close));
  });

  it('is honest about the dependency problem: A/A bounds rather than collapsing to 1', () => {
    const e = parseExpression('A/A');
    const [flatBar] = evaluateExpression(e, { A: [bar(1000, 100, 150, 90, 120)] });
    // Close-only is exact: a thing divided by itself is 1.
    expect(flatBar.close).toBe(1);
    const [bounded] = evaluateExpression(e, { A: [bar(1000, 100, 150, 90, 120)] }, { ohlc: 'interval' });
    // Interval arithmetic cannot see that the two mentions move together, so it
    // widens. This is documented, not a bug to be "fixed" with a wrong shortcut.
    expect(bounded.close).toBe(1);
    expect(bounded.high).toBeGreaterThan(1);
    expect(bounded.low).toBeLessThan(1);
  });

  it('chains any number of legs, with exchange prefixes, in one expression', () => {
    const e = parseExpression('NSEIX:NIFTY1!/NSE:RELIANCE+NASDAQ:META');
    expect(e.symbols).toEqual(['NSEIX:NIFTY1!', 'NSE:RELIANCE', 'NASDAQ:META']);
    const out = evaluateExpression(e, {
      'NSEIX:NIFTY1!': [flat(1000, 26000)],
      'NSE:RELIANCE': [flat(1000, 1400)],
      'NASDAQ:META': [flat(1000, 700)],
    });
    // Precedence binds the division first, so it is (NIFTY/RELIANCE) + META.
    expect(out[0].close).toBeCloseTo(26000 / 1400 + 700, 10);
  });

  it('folds four legs with mixed operators onto one grid', () => {
    const e = parseExpression('(A+B)/(C+D)');
    expect(e.symbols).toEqual(['A', 'B', 'C', 'D']);
    const out = evaluateExpression(e, {
      A: [flat(1000, 10), flat(1060, 20)],
      B: [flat(1000, 30), flat(1060, 40)],
      C: [flat(1000, 2), flat(1060, 3)],
      D: [flat(1000, 2), flat(1060, 3)],
    });
    expect(out.map((b) => b.close)).toEqual([10, 10]);
  });

  it('gaps a bar any one of many legs is missing', () => {
    const e = parseExpression('A+B+C');
    const out = evaluateExpression(e, {
      A: [flat(1000, 1), flat(1060, 1), flat(1120, 1)],
      B: [flat(1000, 2), flat(1120, 2)],
      C: [flat(1000, 3), flat(1060, 3), flat(1120, 3)],
    });
    expect(out.map((b) => b.time)).toEqual([1000, 1120]);
  });

  /**
   * Weighted legs are what an options book is made of: a ratio spread is
   * `2*CE25000 - CE25200`, a straddle is `CE + PE`, and a sold one is a credit
   * and therefore negative. None of that is a special case in the grammar, but
   * it is worth pinning down, because a "simplification" that assumed prices
   * are positive would break every short position silently.
   */
  it('combines weighted legs, the shape an options spread takes', () => {
    const legs = {
      CE25000: [flat(1000, 120)], CE25200: [flat(1000, 70)], PE25000: [flat(1000, 90)],
    };
    const ev = (src: string): number => evaluateExpression(parseExpression(src), legs)[0].close;

    expect(ev('2*CE25000 - 1*CE25200')).toBe(170);      // 1x2 ratio spread
    expect(ev('CE25000 + PE25000')).toBe(210);          // long straddle
    expect(ev('(CE25000 + PE25000)/2')).toBe(105);
    expect(ev('75*(CE25000 - CE25200)')).toBe(3750);    // scaled by lot size
  });

  it('lets a combined premium go negative, because a sold spread is a credit', () => {
    const legs = { CE25000: [flat(1000, 120)], CE25200: [flat(1000, 70)], PE25000: [flat(1000, 90)] };
    const ev = (src: string): number => evaluateExpression(parseExpression(src), legs)[0].close;
    expect(ev('-CE25000 - PE25000')).toBe(-210);        // short straddle
    expect(ev('CE25000 - 2*CE25200')).toBe(-20);        // ratio spread paying a credit
  });

  it('gaps a spread when one leg did not print, rather than pricing it stale', () => {
    // An illiquid strike is the normal case, and a premium carried forward from
    // an earlier minute is exactly the number that gets someone hurt.
    const e = parseExpression('2*CE25000 - CE25200');
    const out = evaluateExpression(e, {
      CE25000: [flat(1000, 120), flat(1060, 125), flat(1120, 130)],
      CE25200: [flat(1000, 70), flat(1120, 75)],
    });
    expect(out.map((b) => b.time)).toEqual([1000, 1120]);
    expect(out.map((b) => b.close)).toEqual([170, 185]);
  });

  it('carries no volume, because a ratio has none', () => {
    const e = parseExpression('A/B');
    const out = evaluateExpression(e, {
      A: [{ ...flat(1000, 100), volume: 500 }],
      B: [{ ...flat(1000, 10), volume: 900 }],
    });
    expect(out[0].volume).toBeUndefined();
  });

  it('handles a constant-only leg combination like (A+B)/2', () => {
    const e = parseExpression('(A+B)/2');
    const out = evaluateExpression(e, { A: [flat(1000, 100)], B: [flat(1000, 50)] });
    expect(out[0].close).toBe(75);
  });

  it('an even power over a range that straddles zero bottoms out at zero', () => {
    const e = parseExpression('A^2');
    const [b] = evaluateExpression(e, { A: [bar(1000, -1, 3, -2, 1)] }, { ohlc: 'interval' });
    expect(b.low).toBe(0);
    expect(b.high).toBe(9);
  });
});
