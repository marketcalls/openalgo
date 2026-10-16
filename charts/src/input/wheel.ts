/** Wheel deltas arrive in CSS pixels, lines or pages, depending on the device. */
export function wheelPixels(event: Pick<WheelEvent, 'deltaX' | 'deltaY' | 'deltaMode'>, width: number, height: number): { x: number; y: number } {
  const unit = event.deltaMode;
  const x = event.deltaX ?? 0;
  const y = event.deltaY ?? 0;
  return {
    x: Number.isFinite(x) ? x * (unit === 1 ? 16 : unit === 2 ? width : 1) : 0,
    y: Number.isFinite(y) ? y * (unit === 1 ? 16 : unit === 2 ? height : 1) : 0,
  };
}

/** Preserve the established 100 px mouse notch while allowing finer trackpad input. */
export function wheelLogFactor(delta: number): number {
  return Math.max(-2, Math.min(2, -delta * Math.log(1.1) / 100));
}
