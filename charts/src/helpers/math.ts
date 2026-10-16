/** Clamp `value` into the inclusive range [min, max]. */
export function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

/** Linear interpolation between `a` and `b` by fraction `t` (0..1). */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Round `value` to the nearest multiple of `step` (the instrument tick size).
 * Used for snapping dragged order/SL/TP prices to a valid tick. Returns
 * `value` unchanged when `step <= 0`.
 */
export function roundToTick(value: number, step: number): number {
  if (step <= 0) return value;
  return Math.round(value / step) * step;
}

/** A canvas size: media px, or device px for a backing buffer. */
export interface Size {
  width: number;
  height: number;
}

/**
 * Pure: compute the integer device-pixel backing-buffer size for a canvas.
 * Here rather than in core/canvas.ts so a renderer can take it by path without
 * reaching back into the core.
 */
export function bitmapSize(mediaWidth: number, mediaHeight: number, dpr: number): Size {
  return {
    width: Math.round(mediaWidth * dpr),
    height: Math.round(mediaHeight * dpr),
  };
}

/** Pure: snap a media-space coordinate to a crisp device-pixel edge. */
export function snapToDevicePixel(mediaCoord: number, dpr: number): number {
  return Math.round(mediaCoord * dpr) / dpr;
}
