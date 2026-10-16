/**
 * CSS colour strings to the premultiplied RGBA the GPU path blends with.
 *
 * The theme and every per-bar override arrive as the strings a 2D context
 * accepts. The shapes program blends premultiplied (ONE, ONE_MINUS_SRC_ALPHA)
 * and the gradient fills are interpolated per vertex, so a colour is
 * premultiplied here, once, and the interpolation across an area's trapezoid
 * lands on the same hue as a 2D gradient rather than dragging through black
 * on its way to a transparent stop.
 *
 * `parseColor` in pill.ts already reads the hex and rgb() forms the theme
 * uses, so that is the parser. Anything it does not read (a named colour, a
 * modern space-separated rgb(), hsl()) goes through the host's own 2D context
 * via `normalise`, which turns any string a browser accepts into one of the
 * forms the parser does, and the answer is cached against the original text.
 */
import { parseColor } from '../pill';

/** Premultiplied red, green, blue, alpha, each 0..1. */
export type PremultipliedRgba = readonly [number, number, number, number];

export const TRANSPARENT: PremultipliedRgba = [0, 0, 0, 0];

function unit(v: number): number {
  return v > 0 ? (v < 1 ? v : 1) : 0;
}

/** Parse a hex or rgb()/rgba() colour to premultiplied RGBA, or null. */
export function parsePremultiplied(css: string): PremultipliedRgba | null {
  const c = parseColor(css);
  if (c === null) return null;
  const a = unit(c.a);
  return [unit(c.r / 255) * a, unit(c.g / 255) * a, unit(c.b / 255) * a, a];
}

/**
 * Linear blend of two premultiplied colours. `t` is deliberately not
 * clamped: a gradient fill evaluates its stops at polygon vertices that may
 * sit outside the gradient's span (a point above the plot), and the GPU
 * interpolates linearly between vertices, so only an unclamped value at the
 * vertex puts the exact gradient colour on every visible pixel between them.
 * The fragment shader clamps what it writes.
 */
export function lerpPremultiplied(a: PremultipliedRgba, b: PremultipliedRgba, t: number): PremultipliedRgba {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
    a[3] + (b[3] - a[3]) * t,
  ];
}

/**
 * Turn any colour string a 2D context accepts into one `parseColor` reads, or
 * null when the context rejects it. Assigning an invalid string leaves
 * `fillStyle` untouched, so the probe runs from two different starting
 * colours: a valid string reads back the same both times, an invalid one
 * reads back the two sentinels.
 */
export function normaliseWith2d(ctx: CanvasRenderingContext2D, css: string): string | null {
  const keep = ctx.fillStyle;
  ctx.fillStyle = '#000000';
  ctx.fillStyle = css;
  const first = ctx.fillStyle;
  ctx.fillStyle = '#ffffff';
  ctx.fillStyle = css;
  const second = ctx.fillStyle;
  ctx.fillStyle = keep;
  return typeof first === 'string' && first === second ? first : null;
}

/** Entries kept before the cache is dropped and rebuilt. */
const CACHE_LIMIT = 4096;

/**
 * Memoised colour lookup. A frame asks for the same handful of strings a few
 * thousand times, and a heatmap plot asks for a fresh rgba() string per bar,
 * so the map is bounded: past the limit it is cleared rather than trimmed,
 * because the strings that matter are re-asked on the next frame anyway.
 */
export class ColorCache {
  private readonly _map = new Map<string, PremultipliedRgba>();

  /**
   * The premultiplied colour for `css`. `normalise` is consulted only on a
   * parse failure, and only once per string. A string neither can read is
   * transparent: that is a colour nothing can blend with, so the bar it was
   * meant for is visibly absent rather than painted in a neighbour's colour,
   * which is what a 2D context's silently kept `fillStyle` would do.
   */
  public get(css: string, normalise?: (css: string) => string | null): PremultipliedRgba {
    let out = this._map.get(css);
    if (out !== undefined) return out;
    out = parsePremultiplied(css) ?? undefined;
    if (out === undefined && normalise !== undefined) {
      const plain = normalise(css);
      if (plain !== null) out = parsePremultiplied(plain) ?? undefined;
    }
    if (out === undefined) out = TRANSPARENT;
    if (this._map.size >= CACHE_LIMIT) this._map.clear();
    this._map.set(css, out);
    return out;
  }

  public get size(): number {
    return this._map.size;
  }

  public clear(): void {
    this._map.clear();
  }
}
