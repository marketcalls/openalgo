/**
 * Hardening of src/trade/validation.ts.
 *
 * Every test here fails against the pre-fix module: either the assertion is on
 * behaviour that did not exist (finite/whole/lot quantity checks, the rejection
 * code, a price-free call) or on a message the old code spelled differently.
 */
import { describe, it, expect } from 'vitest';
import {
  validateOrder,
  validateQuantity,
  validatePrice,
  withinPriceBand,
  type OrderConstraints,
} from '../src/trade/validation';

/** Cash equity: tick 0.05, band 90..110, freeze 1000, whole quantities. */
const C: OrderConstraints = { tickSize: 0.05, priceBand: { lower: 90, upper: 110 }, freezeQty: 1000 };
/** A 75-lot future with a 1800 freeze limit (24 lots). */
const FO: OrderConstraints = { tickSize: 0.05, lotSize: 75, freezeQty: 1800 };

describe('quantity finiteness and positivity', () => {
  it('rejects NaN quantity', () => {
    const r = validateOrder(100, Number.NaN, C);
    expect(r.ok).toBe(false);
    expect(r.code).toBe('QTY_INVALID');
    expect(r.reason).toBe('quantity must be a finite number');
  });

  it('rejects infinite quantity in both directions', () => {
    expect(validateOrder(100, Number.POSITIVE_INFINITY, C).ok).toBe(false);
    expect(validateOrder(100, Number.NEGATIVE_INFINITY, C).ok).toBe(false);
    expect(validateOrder(100, Number.POSITIVE_INFINITY, C).code).toBe('QTY_INVALID');
  });

  it('keeps rejecting zero and negative quantity, with the code attached', () => {
    const zero = validateOrder(100, 0, C);
    expect(zero.ok).toBe(false);
    expect(zero.reason).toBe('quantity must be positive'); // unchanged wording
    expect(zero.code).toBe('QTY_INVALID');
    expect(validateOrder(100, -10, C).ok).toBe(false);
  });
});

describe('whole-quantity and lot-size grid', () => {
  it('rejects a fractional quantity on a whole-lot instrument', () => {
    const r = validateOrder(100, 1.5, C);
    expect(r.ok).toBe(false);
    expect(r.code).toBe('QTY_STEP');
    expect(r.reason).toContain('whole number');
  });

  it('rejects a quantity that is not a multiple of the lot size', () => {
    const r = validateOrder(100, 100, FO);
    expect(r.ok).toBe(false);
    expect(r.code).toBe('QTY_STEP');
    expect(r.reason).toContain('lot size 75');
    expect(validateOrder(100, 150, FO).ok).toBe(true); // two lots is fine
    expect(validateOrder(100, 75 * 1000, { tickSize: 0.05, lotSize: 75 }).ok).toBe(true);
  });

  it('lets a fractional venue opt in, and still holds it to any lot grid', () => {
    const crypto: OrderConstraints = { tickSize: 0.01, allowFractionalQty: true };
    expect(validateOrder(100, 0.25, crypto).ok).toBe(true);

    const stepped: OrderConstraints = { tickSize: 0.01, allowFractionalQty: true, lotSize: 0.1 };
    // 0.3 / 0.1 is 2.9999999999999996: the grid check must be epsilon-tolerant.
    expect(validateOrder(100, 0.3, stepped).ok).toBe(true);
    expect(validateOrder(100, 0.25, stepped).ok).toBe(false);
    expect(validateOrder(100, 0.25, stepped).code).toBe('QTY_STEP');
  });
});

describe('quantity grids at floating-point boundaries', () => {
  it.each([
    { qty: 1000.0005, step: 0.001 },
    { qty: 1_000_000.5, step: 1 },
    { qty: 1_000_000_000_000.25, step: 1 },
  ])('rejects fractional steps without increasing slack with quantity: %j', ({ qty, step }) => {
    const constraints = { tickSize: 0.01, lotSize: step, allowFractionalQty: true };
    expect(validateQuantity(qty, constraints)).toMatchObject({ ok: false, code: 'QTY_STEP' });
    expect(validateOrder(undefined, qty, constraints)).toMatchObject({ ok: false, code: 'QTY_STEP' });
  });

  it.each([
    { qty: 0.3, step: 0.1 },
    { qty: 0.1 + 0.2, step: 0.1 },
    { qty: 1000.001, step: 0.001 },
    { qty: 10.00000001, step: 0.00000001 },
    { qty: 10000000000000.1, step: 0.1 },
  ])('accepts representable decimal multiples without changing quantity: %j', ({ qty, step }) => {
    const constraints = { tickSize: 0.01, lotSize: step, allowFractionalQty: true };
    expect(validateQuantity(qty, constraints)).toEqual({ ok: true });
  });

  it('rejects a positive quantity smaller than one grid step instead of rounding it to zero', () => {
    expect(validateQuantity(1e-20, { tickSize: 0.05 })).toMatchObject({ ok: false, code: 'QTY_STEP' });
    expect(validateQuantity(Number.MIN_VALUE, { tickSize: 0.05, lotSize: 0.001 })).toMatchObject({ ok: false, code: 'QTY_STEP' });
  });

  it('rejects grid counts outside safe integer precision and division overflow', () => {
    expect(validateQuantity(Number.MAX_SAFE_INTEGER, { tickSize: 0.05 })).toEqual({ ok: true });
    expect(validateQuantity(Number.MAX_SAFE_INTEGER + 1, { tickSize: 0.05 })).toMatchObject({ ok: false, code: 'QTY_STEP' });
    expect(validateQuantity(1, { tickSize: 0.05, lotSize: Number.MIN_VALUE })).toMatchObject({ ok: false, code: 'QTY_STEP' });
  });
});

describe('quantity validation is independent of price', () => {
  it('exposes validateQuantity so a market order can be checked on its own', () => {
    expect(validateQuantity(10, C).ok).toBe(true);
    expect(validateQuantity(5000, C).ok).toBe(false);
    expect(validateQuantity(5000, C).code).toBe('QTY_FREEZE_LIMIT');
    expect(validateQuantity(1.5, C).code).toBe('QTY_STEP');
    expect(validateQuantity(Number.NaN, C).code).toBe('QTY_INVALID');
  });

  it('validates quantity alone when validateOrder is given no price', () => {
    expect(validateOrder(undefined, 10, C).ok).toBe(true);
    expect(validateOrder(undefined, 10, C).price).toBeUndefined();

    const frozen = validateOrder(undefined, 5000, C);
    expect(frozen.ok).toBe(false);
    expect(frozen.code).toBe('QTY_FREEZE_LIMIT');
    expect(frozen.reason).toContain('freeze limit 1000');
  });

  it('reports the quantity first when price and quantity are both wrong', () => {
    const r = validateOrder(999, 0, C);
    expect(r.code).toBe('QTY_INVALID');
  });

  it('applies the freeze limit after the grid, so 25 lots over the cap is a freeze reject', () => {
    const r = validateQuantity(75 * 25, FO); // 1875 units, whole lots, over 1800
    expect(r.ok).toBe(false);
    expect(r.code).toBe('QTY_FREEZE_LIMIT');
  });
});

describe('price validation', () => {
  it('rejects a non-finite price instead of snapping it to NaN', () => {
    const noBand: OrderConstraints = { tickSize: 0.05 };
    const r = validateOrder(Number.NaN, 10, noBand);
    expect(r.ok).toBe(false);
    expect(r.code).toBe('PRICE_INVALID');
    expect(validateOrder(Number.POSITIVE_INFINITY, 10, noBand).ok).toBe(false);
    expect(validatePrice(Number.NaN, C).ok).toBe(false);
  });

  it('keeps tick snapping and band behaviour, with the en dash gone from the message', () => {
    expect(validateOrder(100.07, 10, C).price).toBeCloseTo(100.05);
    expect(validatePrice(100.07, C).price).toBeCloseTo(100.05);
    expect(withinPriceBand(100, C.priceBand!)).toBe(true);

    const out = validateOrder(200, 10, C);
    expect(out.ok).toBe(false);
    expect(out.code).toBe('PRICE_OUT_OF_BAND');
    expect(out.reason).toContain('outside band 90 to 110');
    expect(out.reason).not.toMatch(/[\u2013\u2014]/); // house rule: no en or em dashes
  });
});

/**
 * `scaleFont` bounds its digit runs so the pattern cannot backtrack
 * polynomially, and requires a leading boundary so the bound cannot make it
 * match the tail of a longer number.
 */
describe('scaleFont', () => {
  // Imported lazily: axis.ts is a render module and this is the only bit of it
  // these tests care about.
  const scale = async (font: string, dpr: number): Promise<string> => {
    const mod = await import('../src/render/axis');
    const fn = (mod as unknown as { scaleFont?: (f: string, d: number) => string }).scaleFont;
    if (!fn) return font;
    return fn(font, dpr);
  };

  it('scales an ordinary font string', async () => {
    expect(await scale('12px sans-serif', 2)).toBe('24px sans-serif');
    expect(await scale('bold 11.5px Inter', 2)).toBe('bold 23px Inter');
  });

  it('leaves an oversized numeric token alone rather than rewriting its middle', async () => {
    // The bounded-but-unanchored form matched the last five digits of this and
    // produced '1' followed by a scaled '23456px'. Nonsense in, nonsense out is
    // acceptable; nonsense in, plausible-looking nonsense out is not.
    expect(await scale('123456px x', 2)).toBe('123456px x');
  });

  it('is linear on a long digit run', async () => {
    const evil = `${'0'.repeat(40000)} sans-serif`;
    const t = Date.now();
    await scale(evil, 2);
    // The unbounded form took ~800ms on this input; anything near that is the
    // backtracking coming back.
    expect(Date.now() - t).toBeLessThan(100);
  });
});
