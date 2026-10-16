/**
 * Call every listener with `payload`, the way the chart's buses all do.
 *
 * The listeners are copied first, so one may subscribe or unsubscribe while it
 * runs. A listener that throws does not stop the others, and does not reach
 * the caller either: the caller is the engine in the middle of a pointer event,
 * a data write or a render, and a host's bug must not leave it half done. The
 * error is not swallowed. It goes to the platform's `reportError`, which in a
 * browser is where a throwing DOM event listener's error goes: the console and
 * the window's `error` event. Where there is no such function (a test runner
 * with no DOM) there is nowhere to report it, and it is dropped.
 */
export function dispatch<T>(listeners: Iterable<(payload: T) => void> | undefined, payload: T): void {
  if (listeners === undefined) return;
  for (const listener of [...listeners]) {
    try {
      listener(payload);
    } catch (error) {
      (globalThis as { reportError?: (error: unknown) => void }).reportError?.(error);
    }
  }
}

/** Add `listener` to `listeners`; the function returned takes that one out again. */
export function subscribe<T>(listeners: Set<T>, listener: T): () => void {
  listeners.add(listener);
  return (): void => { listeners.delete(listener); };
}
