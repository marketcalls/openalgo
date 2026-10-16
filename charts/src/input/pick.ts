/**
 * Interactive value capture (ARCHITECTURE.md §7). A settings input that names a
 * price or a time is declarative and the host renders it, but the *value* can
 * come from pointing at the chart, and only the engine knows what is under the
 * cursor. So the host arms a pick ("the user is now choosing a price"), the next
 * click on the plot answers with one, and the pick disarms itself.
 *
 * Built on the `click` event the draw tier's placement mode already resolves
 * anchors from, rather than a second capture path: same pane resolution, same
 * on-demand autoscale, same payload.
 *
 * Placement mode is deliberately *not* armed while picking. A pick wants panning
 * left alone (scroll back to the bar you mean, then click it), and a drag emits
 * no click outside placement mode, so panning cannot answer the pick by
 * accident. It also keeps a pick from cancelling an active drawing tool.
 */

import type { PriceScaleId } from '../model/series';

export type PickKind = 'price' | 'time';

/**
 * What a `'point'` pick answers: the bar time and the price under one click.
 * One capture rather than a time pick and a price pick in turn, so a study
 * input pairing the two is never written half from one click and half from
 * another.
 */
export interface PickPoint {
  time: number;
  price: number;
}

/** Cancel a capture, or inspect whether this invocation still owns it. */
export interface PickHandle {
  (): void;
  readonly active: () => boolean;
}

/** Optional target for Chart.beginPick. Times remain absolute UTC seconds. */
export interface PickOptions {
  paneIndex?: number;
  priceScaleId?: PriceScaleId;
}

/**
 * The slice of the chart a pick needs. Structural, so `Chart` satisfies it with
 * nothing to cast and this module never imports the core (which imports this).
 */
export interface PickHost {
  on(event: string, cb: (payload: unknown) => void): () => void;
  emit(event: string, payload: unknown): void;
  readonly dataLayer: {
    timeToIndexFloat(time: number): number;
    indexToTime(index: number): number | undefined;
  };
}

interface ClickLike {
  price: number | null;
  time: number;
}

// One pick per chart: arming a second would leave the first still listening, and
// a single click would then answer two callers. Weak so a destroyed chart and
// its pending pick are collected together.
const active = new WeakMap<PickHost, () => void>();
const starts = new WeakMap<PickHost, object>();

/** @internal Cancel before a context or interaction changes ownership. */
export function cancelPick(host: PickHost): void {
  starts.set(host, {});
  active.get(host)?.();
}

/**
 * Arm the next plot click to resolve to a price, a bar time, or both as a
 * `'point'` ({@link PickPoint}), and hand it to `cb`. Returns a cancel
 * function; calling it (or arming another pick on the same chart) disarms
 * without calling back. The chart emits `pick:start`
 * (`{ kind }`) and `pick:end` (`{ kind, value }`, `value` null when cancelled)
 * so a host can show its own cursor or hint while the pick is live.
 *
 * A time is snapped to the bar the click landed on, because a time between two
 * bars matches no bar and anything anchored to it would never line up. Clicking
 * past the last bar keeps the projected time, which is what a pick in the empty
 * right-hand space means.
 */
export function beginPick(host: PickHost, kind: 'point', cb: (value: PickPoint) => void): PickHandle;
export function beginPick(host: PickHost, kind: PickKind, cb: (value: number) => void): PickHandle;
export function beginPick(host: PickHost, kind: PickKind | 'point', cb: (value: never) => void): PickHandle {
  return beginPickResolved(host, kind, cb as (value: number | PickPoint) => void);
}

/** @internal Chart supplies measured plot bounds and its selected scale. */
export function beginPickResolved(host: PickHost, kind: PickKind | 'point', cb: (value: number | PickPoint) => void,
  resolve?: (payload: unknown) => number | PickPoint | null): PickHandle {
  if (kind !== 'price' && kind !== 'time' && kind !== 'point') throw new TypeError('Invalid pick kind');
  const token = {};
  starts.set(host, token);
  let open = false, invalidated = false;
  const cleanup: (() => void)[] = [];

  const finish = (value: number | PickPoint | null): void => {
    if (!open) return;
    open = false;
    if (active.get(host) === cancel) active.delete(host);
    try {
      // Context listeners stay live through notifications: a host can replace
      // data or destroy the chart while responding to the completed pick.
      host.emit('pick:end', { kind, value });
      if (value !== null && !invalidated && starts.get(host) === token) cb(value);
    } finally {
      for (const off of cleanup.splice(0)) off();
    }
  };
  const cancel: PickHandle = Object.assign(() => { invalidated = true; finish(null); }, { active: () => open });

  // Install fences before cancelling the previous owner, whose listeners can
  // synchronously replace the context or start a newer capture.
  for (const event of ['destroy', 'state:restore:start', 'data:context', 'paneRemoved', 'paneMoved']) cleanup.push(host.on(event, cancel));
  cleanup.push(host.on('data:update', payload => { if ((payload as { kind?: string })?.kind === 'reset') cancel(); }));
  active.get(host)?.();
  if (invalidated || starts.get(host) !== token) {
    for (const off of cleanup.splice(0)) off();
    return cancel;
  }
  open = true;

  // The bar a time falls on, or the projected time past the last bar.
  const bar = (time: number): number => {
    const dl = host.dataLayer;
    return dl.indexToTime(Math.round(dl.timeToIndexFloat(time))) ?? time;
  };
  cleanup.push(host.on('click', (payload) => {
    if (!open) return;
    const p = payload as ClickLike;
    const value = resolve ? resolve(payload) : kind === 'price' ? p.price : kind === 'time' ? p.time : { time: p.time, price: p.price };
    // A click the chart could not resolve (no pane under it, no bars loaded)
    // leaves the pick armed rather than answering with a bogus number, and a
    // point answers only when both of its halves are there.
    if (value === null) return;
    if (typeof value === 'object') {
      const at = Number.isFinite(value.time) ? bar(value.time) : NaN;
      const { price } = value as { price: number | null };
      if (Number.isFinite(at) && price !== null && Number.isFinite(price)) finish({ time: at, price });
      return;
    }
    const answer = Number.isFinite(value) && kind === 'time' ? bar(value) : value;
    if (Number.isFinite(answer)) finish(answer);
  }));
  active.set(host, cancel);
  host.emit('pick:start', { kind });
  return cancel;
}
