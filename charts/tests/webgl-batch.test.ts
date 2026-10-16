/**
 * The vertex batch behind the WebGL2 backend (src/render/webgl/batch.ts):
 * the interleaved layout the shader reads, the quad each emitter writes,
 * growth that keeps what was written, and a reset that allocates nothing.
 */
import { describe, it, expect } from 'vitest';
import {
  VertexBatch, FLOATS_PER_VERTEX, VERTICES_PER_QUAD, INDICES_PER_QUAD, SOLID,
  OFFSET_POS, OFFSET_COLOR, OFFSET_LOCAL, OFFSET_SHAPE, VERTEX_BYTES,
} from '../src/render/webgl/batch';
import type { PremultipliedRgba } from '../src/render/webgl/color';

const RED: PremultipliedRgba = [1, 0, 0, 1];
const HALF: PremultipliedRgba = [0, 0.5, 0, 0.5];

interface Vertex {
  x: number; y: number; color: number[]; u: number; v: number; hx: number; hy: number; rad: number;
}

/** The four vertices of quad `q`, decoded through the documented layout. */
function quad(b: VertexBatch, q: number): Vertex[] {
  const out: Vertex[] = [];
  for (let i = 0; i < VERTICES_PER_QUAD; i++) {
    const o = (q * VERTICES_PER_QUAD + i) * FLOATS_PER_VERTEX;
    const f = b.vertices;
    out.push({
      x: f[o], y: f[o + 1], color: [f[o + 2], f[o + 3], f[o + 4], f[o + 5]],
      u: f[o + 6], v: f[o + 7], hx: f[o + 8], hy: f[o + 9], rad: f[o + 10],
    });
  }
  return out;
}

describe('layout', () => {
  it('is eleven floats per vertex at the byte offsets the shader binds', () => {
    expect(FLOATS_PER_VERTEX).toBe(11);
    expect(VERTEX_BYTES).toBe(44);
    expect([OFFSET_POS, OFFSET_COLOR, OFFSET_LOCAL, OFFSET_SHAPE]).toEqual([0, 8, 24, 32]);
    expect(VERTICES_PER_QUAD).toBe(4);
    expect(INDICES_PER_QUAD).toBe(6);
  });

  it('carries a fixed two-triangle index pattern per slot from construction', () => {
    const b = new VertexBatch(3);
    expect(Array.from(b.indices)).toEqual([0, 1, 2, 2, 1, 3, 4, 5, 6, 6, 5, 7, 8, 9, 10, 10, 9, 11]);
    expect(b.vertices.length).toBe(3 * VERTICES_PER_QUAD * FLOATS_PER_VERTEX);
  });
});

describe('rect', () => {
  it('writes a box centred on the rect with corner locals matching the corner positions', () => {
    const b = new VertexBatch();
    b.rect(10, 20, 4, 6, RED);
    expect(b.quadCount).toBe(1);
    expect(b.vertexCount).toBe(4);
    expect(b.indexCount).toBe(6);
    expect(b.floatCount).toBe(44);
    const q = quad(b, 0);
    // Whole-pixel edges: no skirt, the quad is exactly the rect.
    expect(q.map((v) => [v.x, v.y])).toEqual([[10, 20], [14, 20], [10, 26], [14, 26]]);
    expect(q.map((v) => [v.u, v.v])).toEqual([[-2, -3], [2, -3], [-2, 3], [2, 3]]);
    for (const v of q) {
      expect([v.hx, v.hy, v.rad]).toEqual([2, 3, 0]);
      expect(v.color).toEqual(RED);
    }
  });

  it('grows a one-pixel skirt only when an edge is fractional, so the fringe can be shaded', () => {
    const b = new VertexBatch();
    b.rect(10.5, 20, 4, 6, RED);
    const q = quad(b, 0);
    expect(q.map((v) => [v.x, v.y])).toEqual([[9.5, 19], [15.5, 19], [9.5, 27], [15.5, 27]]);
    expect(q.map((v) => [v.u, v.v])).toEqual([[-3, -4], [3, -4], [-3, 4], [3, 4]]);
    expect([q[0].hx, q[0].hy]).toEqual([2, 3]);
  });

  it('emits nothing for a rect with no area', () => {
    const b = new VertexBatch();
    b.rect(0, 0, 0, 5, RED);
    b.rect(0, 0, 5, 0, RED);
    b.rect(0, 0, NaN, 5, RED);
    expect(b.quadCount).toBe(0);
  });
});

describe('segment', () => {
  it('is a capsule in its own frame: zero-height box rounded by the half width', () => {
    const b = new VertexBatch();
    b.segment(0, 0, 10, 0, 1.5, RED, true);
    const q = quad(b, 0);
    // Half length 5, half width 1.5, one-pixel skirt: the quad spans 7.5 by 2.5 from the centre (5, 0).
    expect(q.map((v) => [v.x, v.y])).toEqual([[-2.5, -2.5], [12.5, -2.5], [-2.5, 2.5], [12.5, 2.5]]);
    expect(q.map((v) => [v.u, v.v])).toEqual([[-7.5, -2.5], [7.5, -2.5], [-7.5, 2.5], [7.5, 2.5]]);
    for (const v of q) expect([v.hx, v.hy, v.rad]).toEqual([5, 0, 1.5]);
  });

  it('is a square-ended box when not round', () => {
    const b = new VertexBatch();
    b.segment(0, 0, 10, 0, 1.5, RED, false);
    const v = quad(b, 0)[0];
    expect([v.hx, v.hy, v.rad]).toEqual([5, 1.5, 0]);
  });

  it('rotates the frame with the segment', () => {
    const b = new VertexBatch();
    b.segment(0, 0, 0, 10, 1, RED, true);
    const q = quad(b, 0);
    // Along +y: the local u axis points down the page, v to the left.
    expect(q.map((v) => [v.x, v.y])).toEqual([[2, -2], [2, 12], [-2, -2], [-2, 12]]);
    expect(q.map((v) => [v.u, v.v])).toEqual([[-7, -2], [7, -2], [-7, 2], [7, 2]]);
  });

  it('draws a dot for a zero-length round segment and nothing for a butt one', () => {
    const b = new VertexBatch();
    b.segment(5, 5, 5, 5, 2, RED, false);
    expect(b.quadCount).toBe(0);
    b.segment(5, 5, 5, 5, 2, RED, true);
    expect(b.quadCount).toBe(1);
    const q = quad(b, 0);
    expect(q.map((v) => [v.x, v.y])).toEqual([[2, 2], [8, 2], [2, 8], [8, 8]]);
    expect([q[0].hx, q[0].hy, q[0].rad]).toEqual([0, 0, 2]);
  });

  it('skips a segment with no width or a non-finite end', () => {
    const b = new VertexBatch();
    b.segment(0, 0, 10, 0, 0, RED, true);
    b.segment(0, 0, NaN, 0, 1, RED, true);
    expect(b.quadCount).toBe(0);
  });
});

describe('quad and triangle', () => {
  it('takes a colour per corner and marks the fill solid', () => {
    const b = new VertexBatch();
    b.quad(0, 0, RED, 10, 0, HALF, 0, 10, RED, 10, 10, HALF);
    const q = quad(b, 0);
    expect(q.map((v) => [v.x, v.y])).toEqual([[0, 0], [10, 0], [0, 10], [10, 10]]);
    expect(q.map((v) => v.color)).toEqual([RED, HALF, RED, HALF]);
    for (const v of q) expect([v.u, v.v, v.hx, v.hy, v.rad]).toEqual([0, 0, SOLID, SOLID, 0]);
  });

  it('spells a triangle as a quad whose last corner repeats', () => {
    const b = new VertexBatch();
    b.triangle(0, 0, RED, 10, 0, RED, 5, 5, HALF);
    const q = quad(b, 0);
    expect(q.map((v) => [v.x, v.y])).toEqual([[0, 0], [10, 0], [5, 5], [5, 5]]);
    expect(q[3].color).toEqual(HALF);
  });
});

describe('growth and reset', () => {
  it('doubles when full, keeps every vertex written so far and extends the index pattern', () => {
    const b = new VertexBatch(2);
    b.rect(0, 0, 1, 1, RED);
    b.rect(1, 0, 1, 1, RED);
    const before = b.vertices;
    b.rect(2, 0, 1, 1, HALF);
    expect(b.capacity).toBe(4);
    expect(b.vertices).not.toBe(before);
    expect(b.indices.length).toBe(4 * INDICES_PER_QUAD);
    expect(quad(b, 0)[0].x).toBe(0);
    expect(quad(b, 1)[0].x).toBe(1);
    expect(quad(b, 2)[0].x).toBe(2);
    expect(quad(b, 2)[0].color).toEqual(HALF);
    expect(Array.from(b.indices.slice(12, 24))).toEqual([8, 9, 10, 10, 9, 11, 12, 13, 14, 14, 13, 15]);
    // Another two rects fill the new capacity without growing again.
    b.rect(3, 0, 1, 1, RED);
    expect(b.capacity).toBe(4);
    b.rect(4, 0, 1, 1, RED);
    expect(b.capacity).toBe(8);
  });

  it('resets to empty without allocating: the next frame reuses the same buffers', () => {
    const b = new VertexBatch(4);
    for (let i = 0; i < 4; i++) b.rect(i, 0, 1, 1, RED);
    const vertices = b.vertices;
    const indices = b.indices;
    b.reset();
    expect(b.quadCount).toBe(0);
    expect(b.floatCount).toBe(0);
    for (let i = 0; i < 4; i++) b.segment(i, 0, i + 1, 0, 1, RED, true);
    expect(b.vertices).toBe(vertices);
    expect(b.indices).toBe(indices);
    expect(quad(b, 0)[0].rad).toBe(1);
  });
});
