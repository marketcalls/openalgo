/**
 * Timers for a delay a caller chose. A platform timer holds at most 2^31 - 1
 * ms; a longer delay overflows and fires at once, so a replay slowed far
 * enough ticked every millisecond and a timeout set in weeks failed at once.
 * These hold the delay under that ceiling, the one rule every module used to
 * write for itself, and some forgot.
 */

/** The longest delay a platform timer holds. */
export const MAX_DELAY = 2_147_483_647;

/** A repeating timer, from 1 ms to `MAX_DELAY` apart. Returns its canceller. */
export function repeat(cb: () => void, ms: number): () => void {
  const id = setInterval(cb, Math.min(MAX_DELAY, Math.max(1, ms)));
  return () => clearInterval(id);
}

/**
 * A one-shot timer held under `MAX_DELAY` that never keeps a Node process
 * alive on its own (`unref` is absent in browsers).
 */
export function later(cb: () => void, ms: number): ReturnType<typeof setTimeout> {
  const timer = setTimeout(cb, Math.min(MAX_DELAY, ms));
  (timer as unknown as { unref?: () => void }).unref?.();
  return timer;
}

/** A playback clock: `performance.now`, or 0 where the platform has none. */
export const monotonicNow = (): number => (typeof performance !== 'undefined' ? performance.now() : 0);
