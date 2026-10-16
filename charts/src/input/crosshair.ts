/**
 * Crosshair magnet snapping (ARCHITECTURE.md §6). Pure helpers so the snap
 * logic is unit-testable; the crosshair's position lives in the chart's input
 * routing (core/chart-input.ts) and its drawing in render/crosshair.ts.
 */
import type { Bar } from '../model/bar';

export type CrosshairMode = 'normal' | 'magnet';

/** Return whichever of the bar's O/H/L/C values is closest to `price`. */
export function magnetSnapPrice(price: number, bar: Bar): number {
  const candidates = [bar.open, bar.high, bar.low, bar.close] as const;
  let best = candidates[0];
  let bestDist = Math.abs(price - best);
  for (let i = 1; i < candidates.length; i++) {
    const d = Math.abs(price - candidates[i]!);
    if (d < bestDist) {
      bestDist = d;
      best = candidates[i]!;
    }
  }
  return best;
}
