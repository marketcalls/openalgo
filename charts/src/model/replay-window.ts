/** Internal boundary shared by replay and data owners added during an active replay. */
interface ReplayWindow { time: number; forming: boolean; asOf?: number }
const windows = new WeakMap<object, ReplayWindow>();
const listeners = new WeakMap<object, Set<() => void>>();

export function replayWindow(chart: object): ReplayWindow | undefined { return windows.get(chart); }

/** True while replay owns this chart, including when its playback clock is paused. */
export function isReplaying(chart: object): boolean { return windows.has(chart); }

export function setReplayWindow(chart: object, window?: ReplayWindow): void {
  if (window) windows.set(chart, Object.freeze({ ...window }));
  else windows.delete(chart);
  for (const callback of listeners.get(chart) ?? []) callback();
}

export function observeReplayWindow(chart: object, callback: () => void): () => void {
  let callbacks = listeners.get(chart);
  if (!callbacks) { callbacks = new Set(); listeners.set(chart, callbacks); }
  callbacks.add(callback);
  return () => {
    callbacks.delete(callback);
    if (!callbacks.size) listeners.delete(chart);
  };
}
