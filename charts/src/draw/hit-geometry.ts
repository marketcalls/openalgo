/**
 * Whether a drawing's geometry reaches a region of its pane: the box a
 * Ctrl+drag selects with, or the path an eraser sweeps. A drawing touches a
 * region when its geometry intersects it, measured with the tool's own
 * `distance`, the answer a click gets: lines, levels, fills and labels count
 * exactly where a click would grab them, to within the same reach, so what a
 * box or an eraser takes is what a click there would have taken.
 *
 * `distance` answers for one point, so a region is sampled. A box is sampled
 * on a grid fine enough that every point of it lies within `reach` of a
 * sample, which makes the test exact to that reach: any part of a drawing
 * inside the box is found. A path is sampled along its length.
 */
import type { PrimitiveRenderContext } from 'openalgo-charts';
import type { Drawing, DrawingTool, HitContext, ScreenPoint } from './types';
import { getDrawingTool, hasDrawingTool } from './registry';
import { projectAnchors } from './layer';
import { anchorCount } from './viewport';
import type { GestureBox } from './gesture-layer';

/** A drawing ready to measure: its tool and its hit context on the pane. */
interface Measured {
  tool: DrawingTool;
  hit: HitContext;
}

/**
 * The tool and hit context of `d`, or null for a drawing the layer neither
 * paints nor hit-tests: hidden, unfinished, an unknown tool, a viewport
 * drawing whose tool cannot be one, or an anchor with no place on screen.
 */
function measured(d: Drawing, rc: PrimitiveRenderContext): Measured | null {
  if (d.visible === false || !hasDrawingTool(d.tool)) return null;
  const tool = getDrawingTool(d.tool);
  if ((d.space === 'viewport' && tool.viewport !== true) || anchorCount(d) < Math.max(1, tool.points)) return null;
  const pts = projectAnchors(rc, d);
  if (pts.length === 0 || !pts.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))) return null;
  return { tool, hit: { pts, drawing: d, rc } };
}

const near = (m: Measured, x: number, y: number, reach: number): boolean => {
  const dist = m.tool.distance(x, y, m.hit);
  return dist !== null && Number.isFinite(dist) && dist <= reach;
};

/** The box's own corners, ordered. */
export function normalizeBox(box: GestureBox): GestureBox {
  return { x0: Math.min(box.x0, box.x1), y0: Math.min(box.y0, box.y1), x1: Math.max(box.x0, box.x1), y1: Math.max(box.y0, box.y1) };
}

/** The grid a box is sampled on at `reach`: cells no wider than `reach * sqrt(2)`, so no point is further than `reach` from a sample. */
function grid(box: GestureBox, reach: number): { nx: number; ny: number } {
  const cell = reach * Math.SQRT2;
  return { nx: Math.max(1, Math.ceil((box.x1 - box.x0) / cell)), ny: Math.max(1, Math.ceil((box.y1 - box.y0) / cell)) };
}

/** How many `distance` calls one drawing costs a box at most: what a caller budgets live work by. */
export function boxSamples(box: GestureBox, reach: number): number {
  const { nx, ny } = grid(normalizeBox(box), reach);
  return (nx + 1) * (ny + 1);
}

/**
 * Whether `d` touches `box` (plot media px, corners in any order): an anchor
 * inside it, or any part of its geometry within `reach` of a point inside it.
 */
export function touchesBox(d: Drawing, rc: PrimitiveRenderContext, box: GestureBox, reach: number): boolean {
  const m = measured(d, rc);
  if (m === null) return false;
  const b = normalizeBox(box);
  if (m.hit.pts.some((p) => p.x >= b.x0 && p.x <= b.x1 && p.y >= b.y0 && p.y <= b.y1)) return true;
  const { nx, ny } = grid(b, reach);
  for (let j = 0; j <= ny; j++) {
    const y = b.y0 + ((b.y1 - b.y0) * j) / ny;
    for (let i = 0; i <= nx; i++) {
      if (near(m, b.x0 + ((b.x1 - b.x0) * i) / nx, y, reach)) return true;
    }
  }
  return false;
}

/** Whether any part of `d` comes within `reach` of the segment `a..b` (plot media px). */
export function touchesPath(d: Drawing, rc: PrimitiveRenderContext, a: ScreenPoint, b: ScreenPoint, reach: number): boolean {
  const m = measured(d, rc);
  if (m === null) return false;
  const steps = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / (reach / 2)));
  for (let i = 0; i <= steps; i++) {
    if (near(m, a.x + ((b.x - a.x) * i) / steps, a.y + ((b.y - a.y) * i) / steps, reach)) return true;
  }
  return false;
}
