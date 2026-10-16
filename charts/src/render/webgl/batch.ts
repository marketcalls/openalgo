/**
 * The vertex batch the WebGL2 backend fills during a frame and flushes in one
 * draw call. Every shape is one quad (four vertices, six indices) carrying a
 * signed-distance description of itself, so the fragment shader can compute
 * an analytic coverage at its edge:
 *
 *   x y            device px
 *   r g b a        premultiplied colour
 *   u v            position in the shape's own frame (centre 0,0, device px)
 *   hx hy          half extents of the shape's inner box
 *   rad            corner radius added to that box
 *
 * A rect is a box with no radius, a round-capped line is a box of zero
 * height with the half line width as radius (a capsule), a marker dot is a
 * capsule of zero length, and a solid triangle sets its extents so large no
 * fragment is ever near an edge. One layout, one program, one draw call, in
 * submission order, which is what keeps a wick under its body and an area
 * fill under its line without sorting anything.
 *
 * Index pattern is fixed per quad slot and identical for every batch, so the
 * device uploads an index buffer only when a batch outgrows the one it has;
 * a frame that fits the capacity from the last one allocates nothing.
 */
import type { PremultipliedRgba } from './color';

export const FLOATS_PER_VERTEX = 11;
export const VERTICES_PER_QUAD = 4;
export const INDICES_PER_QUAD = 6;
/** Byte offsets of each attribute inside a vertex, for `vertexAttribPointer`. */
export const OFFSET_POS = 0;
export const OFFSET_COLOR = 8;
export const OFFSET_LOCAL = 24;
export const OFFSET_SHAPE = 32;
export const VERTEX_BYTES = FLOATS_PER_VERTEX * 4;

/**
 * A half extent that puts every fragment of a quad far inside its shape. The
 * shader's coverage saturates to one there, so a fill with these extents has
 * hard edges: the triangles of an area or a band meet edge to edge and must
 * not each fade at the seam.
 */
export const SOLID = 1e6;

/** Whether a rect edge sits on a whole device pixel. */
const whole = (v: number): boolean => v === Math.round(v);

export class VertexBatch {
  public vertices: Float32Array;
  public indices: Uint32Array;
  public quadCount = 0;
  private _capacity: number;

  public constructor(capacity = 256) {
    this._capacity = Math.max(1, capacity);
    this.vertices = new Float32Array(this._capacity * VERTICES_PER_QUAD * FLOATS_PER_VERTEX);
    this.indices = new Uint32Array(this._capacity * INDICES_PER_QUAD);
    this._fillIndices(0);
  }

  public get capacity(): number {
    return this._capacity;
  }

  public get vertexCount(): number {
    return this.quadCount * VERTICES_PER_QUAD;
  }

  public get indexCount(): number {
    return this.quadCount * INDICES_PER_QUAD;
  }

  public get floatCount(): number {
    return this.vertexCount * FLOATS_PER_VERTEX;
  }

  /** Empty the batch for the next frame. Keeps every buffer. */
  public reset(): void {
    this.quadCount = 0;
  }

  /**
   * An axis-aligned rectangle in device px. Edges on whole pixels cover
   * exactly those pixels; fractional edges get analytic coverage, the way a
   * 2D `fillRect` does. The quad only grows a one-pixel skirt for the
   * anti-aliased fringe when an edge is fractional, so the integer rects a
   * candle is made of rasterise no fragment outside themselves.
   */
  public rect(x: number, y: number, w: number, h: number, color: PremultipliedRgba): void {
    if (!(w > 0) || !(h > 0)) return;
    const hx = w / 2;
    const hy = h / 2;
    const cx = x + hx;
    const cy = y + hy;
    const skirt = whole(x) && whole(y) && whole(x + w) && whole(y + h) ? 0 : 1;
    const ex = hx + skirt;
    const ey = hy + skirt;
    const o = this._claim();
    const v = this.vertices;
    this._vertex(v, o, cx - ex, cy - ey, color, -ex, -ey, hx, hy, 0);
    this._vertex(v, o + FLOATS_PER_VERTEX, cx + ex, cy - ey, color, ex, -ey, hx, hy, 0);
    this._vertex(v, o + 2 * FLOATS_PER_VERTEX, cx - ex, cy + ey, color, -ex, ey, hx, hy, 0);
    this._vertex(v, o + 3 * FLOATS_PER_VERTEX, cx + ex, cy + ey, color, ex, ey, hx, hy, 0);
  }

  /**
   * A stroked segment of half width `hw` between two device-px points.
   * `round` gives it the round caps a series line is stroked with (a capsule,
   * so two segments meeting at a point also form a round join); otherwise it
   * is cut square at both ends, the default butt cap. A zero-length round
   * segment is a dot of radius `hw`; a zero-length butt one is nothing.
   */
  public segment(x0: number, y0: number, x1: number, y1: number, hw: number, color: PremultipliedRgba, round: boolean): void {
    if (!(hw > 0)) return;
    const dx = x1 - x0;
    const dy = y1 - y0;
    const len = Math.hypot(dx, dy);
    if (!Number.isFinite(len)) return;
    if (len === 0 && !round) return;
    // Unit axis of the segment; an arbitrary one for a dot, where it does not matter.
    const ux = len === 0 ? 1 : dx / len;
    const uy = len === 0 ? 0 : dy / len;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const half = len / 2;
    // Inner box and radius: a capsule is a zero-height box rounded by hw, a
    // butt segment is the full box with square corners.
    const hx = half;
    const hy = round ? 0 : hw;
    const rad = round ? hw : 0;
    // The quad covers the shape plus a one-pixel skirt for the fringe.
    const ex = half + hw + 1;
    const ey = hw + 1;
    const o = this._claim();
    const v = this.vertices;
    this._vertex(v, o, cx - ux * ex + uy * ey, cy - uy * ex - ux * ey, color, -ex, -ey, hx, hy, rad);
    this._vertex(v, o + FLOATS_PER_VERTEX, cx + ux * ex + uy * ey, cy + uy * ex - ux * ey, color, ex, -ey, hx, hy, rad);
    this._vertex(v, o + 2 * FLOATS_PER_VERTEX, cx - ux * ex - uy * ey, cy - uy * ex + ux * ey, color, -ex, ey, hx, hy, rad);
    this._vertex(v, o + 3 * FLOATS_PER_VERTEX, cx + ux * ex - uy * ey, cy + uy * ex + ux * ey, color, ex, ey, hx, hy, rad);
  }

  /**
   * A solid quad with a colour per corner, in strip order (the two triangles
   * are 0-1-2 and 2-1-3), for gradient fills. No anti-aliasing: these tile
   * edge to edge under a line that covers the seam.
   */
  public quad(
    x0: number, y0: number, c0: PremultipliedRgba,
    x1: number, y1: number, c1: PremultipliedRgba,
    x2: number, y2: number, c2: PremultipliedRgba,
    x3: number, y3: number, c3: PremultipliedRgba,
  ): void {
    const o = this._claim();
    const v = this.vertices;
    this._vertex(v, o, x0, y0, c0, 0, 0, SOLID, SOLID, 0);
    this._vertex(v, o + FLOATS_PER_VERTEX, x1, y1, c1, 0, 0, SOLID, SOLID, 0);
    this._vertex(v, o + 2 * FLOATS_PER_VERTEX, x2, y2, c2, 0, 0, SOLID, SOLID, 0);
    this._vertex(v, o + 3 * FLOATS_PER_VERTEX, x3, y3, c3, 0, 0, SOLID, SOLID, 0);
  }

  /** A solid triangle: a quad whose last corner repeats, leaving one triangle degenerate. */
  public triangle(
    x0: number, y0: number, c0: PremultipliedRgba,
    x1: number, y1: number, c1: PremultipliedRgba,
    x2: number, y2: number, c2: PremultipliedRgba,
  ): void {
    this.quad(x0, y0, c0, x1, y1, c1, x2, y2, c2, x2, y2, c2);
  }

  /** Reserve one quad slot; returns the float offset of its first vertex. */
  private _claim(): number {
    if (this.quadCount === this._capacity) this._grow();
    const o = this.quadCount * VERTICES_PER_QUAD * FLOATS_PER_VERTEX;
    this.quadCount++;
    return o;
  }

  private _vertex(
    v: Float32Array, o: number, x: number, y: number, c: PremultipliedRgba,
    u: number, w: number, hx: number, hy: number, rad: number,
  ): void {
    v[o] = x;
    v[o + 1] = y;
    v[o + 2] = c[0];
    v[o + 3] = c[1];
    v[o + 4] = c[2];
    v[o + 5] = c[3];
    v[o + 6] = u;
    v[o + 7] = w;
    v[o + 8] = hx;
    v[o + 9] = hy;
    v[o + 10] = rad;
  }

  private _grow(): void {
    const from = this._capacity;
    this._capacity *= 2;
    const vertices = new Float32Array(this._capacity * VERTICES_PER_QUAD * FLOATS_PER_VERTEX);
    vertices.set(this.vertices);
    this.vertices = vertices;
    const indices = new Uint32Array(this._capacity * INDICES_PER_QUAD);
    indices.set(this.indices);
    this.indices = indices;
    this._fillIndices(from);
  }

  /** Write the fixed two-triangle pattern for every slot from `from` up. */
  private _fillIndices(from: number): void {
    const ix = this.indices;
    for (let q = from; q < this._capacity; q++) {
      const b = q * VERTICES_PER_QUAD;
      const o = q * INDICES_PER_QUAD;
      ix[o] = b;
      ix[o + 1] = b + 1;
      ix[o + 2] = b + 2;
      ix[o + 3] = b + 2;
      ix[o + 4] = b + 1;
      ix[o + 5] = b + 3;
    }
  }
}
