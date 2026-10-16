/** Bound a request to every supplied lifetime, even when its provider ignores cancellation. */
export function runAbortable<T>(
  work: (signal: AbortSignal) => Promise<T> | T,
  signals: readonly (AbortSignal | undefined)[],
): Promise<T> {
  const sources = [...new Set(signals.filter((signal): signal is AbortSignal => signal !== undefined))];
  const controller = sources.length === 1 ? null : new AbortController();
  const signal = controller?.signal ?? sources[0]!; // no controller means exactly one source
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const listeners = new Map<AbortSignal, () => void>();
    const cleanup = (): void => {
      for (const [source, listener] of listeners) source.removeEventListener('abort', listener);
      listeners.clear();
    };
    const finish = (complete: () => void): void => {
      if (settled) return;
      settled = true;
      cleanup();
      complete();
    };
    const abort = (source: AbortSignal): void => {
      // Settle before dispatch: a provider's abort listener may cancel another
      // source or reject its promise synchronously with a different reason.
      finish(() => {
        reject(source.reason);
        controller?.abort(source.reason);
      });
    };
    const aborted = sources.find(source => source.aborted);
    if (aborted) { abort(aborted); return; }
    for (const source of sources) {
      const listener = (): void => abort(source);
      listeners.set(source, listener);
      source.addEventListener('abort', listener, { once: true });
    }
    try {
      // Both handlers remain attached if work aborts synchronously, so a late
      // provider failure is consumed after the caller has stopped waiting.
      void Promise.resolve(work(signal)).then(
        value => finish(() => resolve(value)),
        error => finish(() => reject(error)),
      );
    } catch (error) {
      finish(() => reject(error));
    }
  });
}
