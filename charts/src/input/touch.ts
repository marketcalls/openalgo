/**
 * Multi-touch pinch helpers (ARCHITECTURE.md §6). Pure geometry so the gesture
 * math is unit-testable without a touch device: a pinch is summarised by the
 * distance between two pointers and their midpoint; frame-to-frame it yields a
 * zoom `factor` (distance ratio) and a midpoint translation (`dx`,`dy`) for pan.
 */
interface Pt {
  x: number;
  y: number;
}

export interface PinchState {
  /** Distance between the two pointers. */
  dist: number;
  /** Midpoint x / y. */
  cx: number;
  cy: number;
}

/** Snapshot the pinch state for two pointers. */
export function pinchState(a: Pt, b: Pt): PinchState {
  return { dist: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
}

/** Frame delta: zoom factor (>1 = fingers apart = zoom in) + midpoint pan (dx,dy). */
export function pinchDelta(prev: PinchState, cur: PinchState): { factor: number; dx: number; dy: number } {
  return {
    factor: prev.dist > 0 ? cur.dist / prev.dist : 1,
    dx: cur.cx - prev.cx,
    dy: cur.cy - prev.cy,
  };
}
