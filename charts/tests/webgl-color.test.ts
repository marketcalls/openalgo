/**
 * Colour strings to premultiplied RGBA for the WebGL2 backend
 * (src/render/webgl/color.ts): every form the theme uses, the 2D-context
 * normaliser for the rest, and the cache in front of both.
 */
import { describe, it, expect } from 'vitest';
import {
  parsePremultiplied, lerpPremultiplied, normaliseWith2d, ColorCache, TRANSPARENT,
  type PremultipliedRgba,
} from '../src/render/webgl/color';

const close = (got: PremultipliedRgba, want: readonly number[]): void => {
  expect(got).toHaveLength(4);
  for (let i = 0; i < 4; i++) expect(got[i]).toBeCloseTo(want[i], 6);
};

describe('parsePremultiplied', () => {
  it('reads the hex forms the theme uses', () => {
    close(parsePremultiplied('#fff') as PremultipliedRgba, [1, 1, 1, 1]);
    close(parsePremultiplied('#26a69a') as PremultipliedRgba, [0x26 / 255, 0xa6 / 255, 0x9a / 255, 1]);
    close(parsePremultiplied('#0d0e12') as PremultipliedRgba, [0x0d / 255, 0x0e / 255, 0x12 / 255, 1]);
    // Eight digits: the alpha byte premultiplies the rest.
    close(parsePremultiplied('#ff000080') as PremultipliedRgba, [128 / 255, 0, 0, 128 / 255]);
    close(parsePremultiplied('#f008') as PremultipliedRgba, [0x88 / 255, 0, 0, 0x88 / 255]);
  });

  it('reads rgb() and rgba(), premultiplying by the alpha', () => {
    close(parsePremultiplied('rgb(79,140,255)') as PremultipliedRgba, [79 / 255, 140 / 255, 1, 1]);
    close(parsePremultiplied('rgba(79,140,255,0.40)') as PremultipliedRgba, [79 / 255 * 0.4, 140 / 255 * 0.4, 0.4, 0.4]);
    close(parsePremultiplied('rgba(79, 140, 255, 0.00)') as PremultipliedRgba, [0, 0, 0, 0]);
    close(parsePremultiplied(' rgba(0,0,0,0) ') as PremultipliedRgba, [0, 0, 0, 0]);
  });

  it('clamps out-of-range channels and alpha instead of producing a colour the GPU cannot blend', () => {
    close(parsePremultiplied('rgba(300,0,0,2)') as PremultipliedRgba, [1, 0, 0, 1]);
  });

  it('returns null for what the parser does not read', () => {
    expect(parsePremultiplied('red')).toBeNull();
    expect(parsePremultiplied('hsl(10, 50%, 50%)')).toBeNull();
    expect(parsePremultiplied('#12345')).toBeNull();
    expect(parsePremultiplied('')).toBeNull();
  });
});

describe('lerpPremultiplied', () => {
  it('blends each channel linearly and does not clamp t', () => {
    const a: PremultipliedRgba = [1, 0, 0, 1];
    const b: PremultipliedRgba = [0, 0, 0, 0];
    close(lerpPremultiplied(a, b, 0), [1, 0, 0, 1]);
    close(lerpPremultiplied(a, b, 1), [0, 0, 0, 0]);
    close(lerpPremultiplied(a, b, 0.25), [0.75, 0, 0, 0.75]);
    // A vertex above the gradient's span extrapolates, so the interpolated
    // value inside the span is exact; the shader clamps what it writes.
    close(lerpPremultiplied(a, b, -1), [2, 0, 0, 2]);
    close(lerpPremultiplied(a, b, 2), [-1, 0, 0, -1]);
  });
});

/** A 2D context that accepts a known set of strings and normalises like a browser. */
function normalisingCtx(known: Record<string, string>): CanvasRenderingContext2D & { writes: string[] } {
  let current = '#000000';
  const writes: string[] = [];
  const ctx = {
    writes,
    get fillStyle(): string { return current; },
    set fillStyle(v: string) {
      writes.push(v);
      // A browser normalises a valid string and ignores an invalid one.
      if (/^#[0-9a-f]{6}$/i.test(v)) current = v.toLowerCase();
      else if (known[v] !== undefined) current = known[v];
    },
  };
  return ctx as unknown as CanvasRenderingContext2D & { writes: string[] };
}

describe('normaliseWith2d', () => {
  it('turns a string the browser accepts into the parser form and puts the fill style back', () => {
    const ctx = normalisingCtx({ red: '#ff0000' });
    ctx.fillStyle = '#123456';
    expect(normaliseWith2d(ctx, 'red')).toBe('#ff0000');
    expect(ctx.fillStyle).toBe('#123456');
  });

  it('detects a rejected string by reading back two different sentinels', () => {
    const ctx = normalisingCtx({});
    expect(normaliseWith2d(ctx, 'nonsense')).toBeNull();
    // A string that happens to name one of the sentinels is still valid.
    expect(normaliseWith2d(ctx, '#000000')).toBe('#000000');
    expect(normaliseWith2d(ctx, '#ffffff')).toBe('#ffffff');
  });
});

describe('ColorCache', () => {
  it('parses once and serves the same tuple afterwards', () => {
    const cache = new ColorCache();
    const first = cache.get('#26a69a');
    expect(cache.get('#26a69a')).toBe(first);
    expect(cache.size).toBe(1);
    close(first, [0x26 / 255, 0xa6 / 255, 0x9a / 255, 1]);
  });

  it('asks the normaliser only for what the parser cannot read, and only once per string', () => {
    const cache = new ColorCache();
    const asked: string[] = [];
    const normalise = (css: string): string | null => { asked.push(css); return css === 'red' ? '#ff0000' : null; };
    close(cache.get('#fff', normalise), [1, 1, 1, 1]);
    expect(asked).toEqual([]);
    close(cache.get('red', normalise), [1, 0, 0, 1]);
    close(cache.get('red', normalise), [1, 0, 0, 1]);
    expect(asked).toEqual(['red']);
    // Neither reads it: transparent, so the bar is absent rather than wrong.
    expect(cache.get('nonsense', normalise)).toBe(TRANSPARENT);
    expect(cache.get('nonsense', normalise)).toBe(TRANSPARENT);
    expect(asked).toEqual(['red', 'nonsense']);
  });

  it('is transparent for an unreadable string with no normaliser', () => {
    expect(new ColorCache().get('red')).toBe(TRANSPARENT);
  });

  it('stays bounded: a plot inventing a colour per bar cannot grow it without limit', () => {
    const cache = new ColorCache();
    for (let i = 0; i < 5000; i++) cache.get(`rgba(${i % 256},0,0,0.5)`);
    expect(cache.size).toBeLessThanOrEqual(4096);
    expect(cache.size).toBeGreaterThan(0);
    close(cache.get('rgba(255,0,0,0.5)'), [0.5, 0, 0, 0.5]);
    cache.clear();
    expect(cache.size).toBe(0);
  });
});
