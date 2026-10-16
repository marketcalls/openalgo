/**
 * Tier-2 contract: indicators whose data is **not** derived from the chart's
 * OHLCV: cumulative volume delta, PCR, an external analytics
 * feed. Where a Tier-1 descriptor is a pure `calc(bars, settings)`, a Tier-2
 * descriptor owns a fetch / subscribe / merge lifecycle and its own series.
 *
 * `createTier2Indicator` wraps that lifecycle into an ordinary
 * `IndicatorDescriptor`, so the chart runtime, the settings model, panes,
 * levels, and removal all work identically: there is no second runtime.
 *
 * The alignment rule is deliberate and worth knowing: external points carry
 * their own timestamps, which rarely match bar times. Each bar takes the most
 * recent external point **at or before** that bar's time (last-known-value,
 * never interpolated and never forward-looking), and bars before the first
 * point are `null`.
 */
import type {
  Bar,
  IndicatorBarsRequest,
  ChartDataContext,
  IndicatorCalcContext,
  IndicatorDataStatus,
  IndicatorDescriptor,
  IndicatorPlot,
  IndicatorInput,
  IndicatorLevel,
  IndicatorRequestState,
  IndicatorSettings,
  IndicatorStore,
  IndicatorValues,
} from 'openalgo-charts';
import { inheritedDataVariant, passingContext } from './inherited-variant';

/** One external observation: a timestamp plus a value per plot key. */
export interface Tier2Point {
  /** UTC seconds. */
  time: number;
  values: Readonly<Record<string, number | null>>;
}

export interface Tier2Context {
  /** Host identity when supplied. Indicator settings remain independent. */
  dataContext?: Readonly<ChartDataContext>;
  /** Native source, provider and external-data revisions, when supplied. */
  requestState?: Readonly<IndicatorRequestState>;
  /** Inclusive availability cutoff during opted-in native timed replay. */
  asOf?: number;
  /** Cancelled when this request is obsolete or the instance is removed. */
  signal?: AbortSignal;
  settings: Readonly<IndicatorSettings>;
  /** The chart's current source bars: use for the requested time window. */
  bars: readonly Bar[];
  /** UTC seconds of the first and last source bar (0 when there are none). */
  from: number;
  to: number;
  /**
   * The host's bar provider, when the runtime supplies one, so a `fetch` that
   * needs another instrument's candles asks the host rather than carrying its
   * own transport and credentials. Rejects when the host registered none. A
   * request that names no `variant` is sent in the chart's session and
   * adjustment (see `inheritedDataVariant`); naming one, `{}` included, wins.
   */
  requestBars?(request: IndicatorBarsRequest): Promise<readonly Bar[]>;
}

export interface Tier2Descriptor {
  id: string;
  name: string;
  category?: string;
  placement: 'onchart' | 'pane';
  inputs: readonly IndicatorInput[];
  plots: readonly IndicatorPlot[];
  /**
   * External columns to align besides the plots, by key. A point may carry
   * more than what is drawn: a benchmark close that `calc` divides by, an
   * open-interest figure a ratio is built from. Anything not named here or in
   * `plots` is dropped at alignment.
   */
  series?: readonly string[];
  /**
   * Combine the aligned external columns with the chart's own bars. Without
   * it the aligned columns are the result, one per plot, exactly as before.
   * With it, `external` holds every plot and `series` key aligned onto the
   * bars (last-known-value, `null` before the first point), and the return is
   * what the plots draw: a relative strength, a beta, a spread. Pure in its
   * arguments, like any `calc`.
   */
  calc?(
    bars: readonly Bar[],
    external: IndicatorValues,
    settings: Readonly<IndicatorSettings>,
    store: IndicatorStore,
    ctx?: IndicatorCalcContext,
  ): IndicatorValues;
  /** A host/provider can explicitly decline data it cannot supply. */
  supports?(ctx: Tier2Context): boolean;
  /** Load the series for the current window. */
  fetch(ctx: Tier2Context): Promise<readonly Tier2Point[]>;
  /**
   * Opt into native timed replay. fetch must honor finite ctx.asOf, return the
   * values known then, and use point.time as availability time. Raw requestBars
   * does not supply historical value versions automatically. Native legacy
   * replay without an availability clock remains unsupported. Defaults false.
   */
  supportsReplay?: boolean;
  /**
   * Optional live subscription. Call `push` with each incoming point; return an
   * unsubscribe function.
   */
  subscribe?(ctx: Tier2Context, push: (point: Tier2Point) => void): () => void;
  /**
   * Settings keys that invalidate the fetched data when they change (symbol,
   * exchange, resolution). Changing anything else only re-runs alignment.
   */
  refetchOn?: readonly string[];
  levels?(settings: Readonly<IndicatorSettings>): readonly IndicatorLevel[];
  range?(settings: Readonly<IndicatorSettings>): { min: number; max: number } | null;
}

type Tier2Outcome = { ok: true; points: readonly Tier2Point[] } | { ok: false; error: unknown };

interface Tier2Request {
  controller: AbortController;
  context: Tier2Context;
  from: number;
  to: number;
  mode: 'replace' | 'tail' | 'prepend';
  version: string;
  liveAfter: number | null;
  started: boolean;
  outcome?: Tier2Outcome;
  receive(outcome: Tier2Outcome): void;
}

interface Tier2Subscription {
  dispose?: () => void;
}

interface Tier2State {
  key: string | null;
  points: Tier2Point[];
  live: Tier2Point[];
  loaded: boolean;
  from: number;
  to: number;
  status: IndicatorDataStatus;
  request: Tier2Request | null;
  subscription: Tier2Subscription | null;
  generation: number;
  lastContext?: Tier2Context;
  completedContext?: Tier2Context | undefined;
  baseDataRevision?: number | undefined;
  completedVersion: string | null;
  liveRevision: number;
  liveVersions: Map<number, number>;
  errorKind?: 'fetch' | 'calc' | undefined;
}

const STATE = '__tier2';

const stateOf = (store: Record<string, unknown>): Tier2State | undefined =>
  store[STATE] as Tier2State | undefined;

/** Cache key from the settings that invalidate data. */
function cacheKey(d: Tier2Descriptor, settings: Readonly<IndicatorSettings>): string {
  const keys = d.refetchOn ?? [];
  return keys.map((k) => `${k}=${String(settings[k])}`).join('&');
}

/** Upsert a point by time, keeping the series time-sorted. */
function upsert(points: Tier2Point[], point: Tier2Point): void {
  const last = points[points.length - 1];
  if (last === undefined || point.time > last.time) { points.push(point); return; }
  if (point.time === last.time) { points[points.length - 1] = point; return; }
  let lo = 0;
  let hi = points.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid]!.time < point.time) lo = mid + 1;
    else hi = mid;
  }
  if (points[lo]?.time === point.time) points[lo] = point;
  else points.splice(lo, 0, point);
}

/**
 * Project time-stamped external points onto the bar timeline: each bar reads
 * the latest point at or before it. Both arrays are time-sorted, so this is a
 * single linear merge, not a per-bar search.
 */
function align(
  bars: readonly Bar[],
  points: readonly Tier2Point[],
  keys: readonly string[],
): IndicatorValues {
  const out: Record<string, (number | null)[]> = {};
  for (const key of keys) out[key] = new Array<number | null>(bars.length).fill(null);
  if (points.length === 0) return out;
  // `p` only advances to a point that exists, and `out` has a column per key.
  let p = -1;
  for (let i = 0; i < bars.length; i++) {
    while (p + 1 < points.length && points[p + 1]!.time <= bars[i]!.time) p += 1;
    if (p < 0) continue;
    const values = points[p]!.values;
    for (const key of keys) {
      const v = values[key];
      out[key]![i] = typeof v === 'number' && Number.isFinite(v) ? v : null;
    }
  }
  return out;
}

/** The plot keys plus any extra external columns the descriptor named. */
function alignedKeys(d: Tier2Descriptor): string[] {
  const keys = d.plots.map((plot) => plot.key);
  for (const key of d.series ?? []) if (!keys.includes(key)) keys.push(key);
  return keys;
}

/**
 * Wrap a Tier-2 descriptor as a normal `IndicatorDescriptor`.
 *
 * ```ts
 * export const POSITION_INDEX = createTier2Indicator({
 *   id: 'external-position-index', name: 'Position Index', placement: 'pane',
 *   inputs: [{ key: 'symbol', type: 'text', label: 'Symbol', default: '' }],
 *   plots: [{ key: 'position', type: 'line', title: 'Position' }],
 *   refetchOn: ['symbol'],
 *   fetch: async ({ settings, from, to }) => loadPositionIndex(settings.symbol, from, to),
 * });
 * registerIndicator(POSITION_INDEX);
 * ```
 */
export function createTier2Indicator(d: Tier2Descriptor): IndicatorDescriptor {
  const failures = new WeakMap<IndicatorStore, { points: readonly Tier2Point[] | undefined; error: unknown }>();
  // `category`, `levels` and `range` are copied whether or not `d` sets
  // them, and the runtime reads a copied undefined as absent. Two of them are
  // methods, whose type cannot take undefined, hence the assertion at the end.
  return {
    id: d.id,
    name: d.name,
    category: d.category,
    placement: d.placement,
    inputs: d.inputs,
    plots: d.plots,
    levels: d.levels,
    range: d.range,

    calc: (bars, settings, store, ctx) => {
      const state = stateOf(store);
      try {
        const external = align(bars, state?.points ?? [], alignedKeys(d));
        const values = d.calc === undefined ? external : d.calc(bars, external, settings, store, ctx);
        failures.delete(store);
        return values;
      } catch (error) {
        failures.set(store, { points: state?.points, error });
        throw error;
      }
    },

    attach: (ctx) => {
      // A synchronous style reattach inherits pending history and its signal.
      const state: Tier2State = stateOf(ctx.store) ?? {
        key: null, points: [], live: [], loaded: false, from: 0, to: 0,
        status: { state: 'empty' }, request: null, subscription: null, generation: 0,
        completedVersion: null, liveRevision: 0, liveVersions: new Map(),
      };
      ctx.store[STATE] = state;
      let generation = ++state.generation;
      let active = true;
      let refreshRevision = 0;
      let unsubscribeChanges: () => void = () => {};

      const current = (): boolean => active && state.generation === generation && !ctx.signal?.aborted;
      const publish = (status: IndicatorDataStatus): void => {
        state.status = status;
        const failure = failures.get(ctx.store);
        if (current()) ctx.setDataStatus?.((status.state === 'ready' || status.state === 'empty') && failure?.points === state.points
          ? { state: 'error', error: failure.error } : status);
      };
      const context = (): Tier2Context => {
        const bars = ctx.bars();
        const market = ctx.dataContext?.() ?? {
          symbol: ctx.symbol?.(), interval: ctx.interval?.(),
        } as Readonly<ChartDataContext>;
        const requestState = ctx.requestState?.();
        // The context, and the fallback market above, carry an optional member
        // the runtime lacks as undefined, which a fetch reads as absent. The
        // public types stay exact for hosts, and `requestBars` is a method.
        return {
          settings: ctx.settings(), bars,
          dataContext: { ...market },
          requestState, asOf: requestState?.replay?.asOf,
          from: bars[0]?.time ?? 0, to: bars[bars.length - 1]?.time ?? 0,
          requestBars: ctx.requestBars && ((request: IndicatorBarsRequest) => {
            const variant = request.variant === undefined ? inheritedDataVariant(market.variant) : request.variant;
            return ctx.requestBars!(variant === undefined ? request : { ...request, variant });
          }),
        } as Tier2Context;
      };
      const cancel = (): void => {
        const request = state.request;
        state.request = null;
        request?.controller.abort();
      };
      const stopLive = (): void => {
        const subscription = state.subscription;
        state.subscription = null;
        subscription?.dispose?.();
      };
      const clear = (): void => {
        generation = ++state.generation;
        state.loaded = false;
        state.completedVersion = null;
        state.completedContext = undefined;
        state.baseDataRevision = state.lastContext?.requestState?.dataRevision;
        state.live = [];
        state.liveVersions.clear();
        state.errorKind = undefined;
        const hadPoints = state.points.length > 0;
        state.points = [];
        state.status = { state: 'empty' };
        // Invalidation precedes every callback, including abort and disposal.
        const request = state.request;
        const subscription = state.subscription;
        state.request = null;
        state.subscription = null;
        request?.controller.abort();
        subscription?.dispose?.();
        if (hadPoints) ctx.requestRecompute();
      };
      const observe = (request: Tier2Request): void => {
        request.receive = outcome => {
          if (!current() || state.request !== request || request.controller.signal.aborted) return;
          state.request = null;
          state.completedVersion = request.version;
          if (!outcome.ok) {
            state.errorKind = 'fetch';
            publish({ state: 'error', error: outcome.error });
            if (request.context.requestState !== undefined) refresh();
            return;
          }
          const merged = request.mode === 'tail' ? state.points.slice() : [];
          try {
            for (const point of outcome.points.slice().sort((a, b) => a.time - b.time)) {
              if (Number.isFinite(point.time) && (request.context.asOf === undefined || point.time <= request.context.asOf)) upsert(merged, point);
            }
          } catch (error) {
            state.errorKind = 'fetch'; publish({ state: 'error', error });
            if (request.context.requestState !== undefined) refresh();
            return;
          }
          if (request.mode === 'prepend') for (const point of state.points) upsert(merged, point);
          if (request.context.asOf === undefined) for (const point of state.live) {
            if (request.liveAfter === null || (state.liveVersions.get(point.time) ?? 0) > request.liveAfter) upsert(merged, point);
          }
          const previous = state.points;
          state.points = merged;
          try {
            ctx.requestRecompute();
            const failure = failures.get(ctx.store);
            if (failure?.points === merged) throw failure.error;
          } catch (error) {
            if (current() && state.points === merged) {
              state.points = previous;
              state.errorKind = 'calc';
              publish({ state: 'error', error });
              if (request.context.requestState !== undefined) refresh();
            }
            return;
          }
          if (!current() || state.points !== merged) return;
          if (request.liveAfter !== null) {
            state.live = state.live.filter(point => (state.liveVersions.get(point.time) ?? 0) > request.liveAfter!);
            for (const [time, revision] of state.liveVersions) if (revision <= request.liveAfter) state.liveVersions.delete(time);
          }
          state.from = state.loaded && request.mode !== 'replace' ? Math.min(state.from, request.from) : request.from;
          state.to = state.loaded && request.mode !== 'replace' ? Math.max(state.to, request.to) : request.to;
          state.loaded = true;
          state.completedContext = request.context;
          state.errorKind = undefined;
          publish({ state: merged.length > 0 ? 'ready' : 'empty' });
          refresh();
        };
        if (request.outcome !== undefined) request.receive(request.outcome);
      };
      const start = (request: Tier2Request): void => {
        if (!current() || state.request !== request || request.started || request.controller.signal.aborted) return;
        request.started = true;
        const finish = (outcome: Tier2Outcome): void => { request.outcome = outcome; request.receive(outcome); };
        let promise: Promise<readonly Tier2Point[]>;
        try { promise = d.fetch({ ...request.context, from: request.from, to: request.to, signal: request.controller.signal }); }
        catch (error) { finish({ ok: false, error }); return; }
        // The stable request dispatches directly to its current attachment, so
        // adopting work does not add a promise turn to existing custom hosts.
        void Promise.resolve(promise).then(points => finish({ ok: true, points }), error => finish({ ok: false, error }));
      };
      const load = (c: Tier2Context, from: number, to: number, mode: Tier2Request['mode'], version: string, replaceLive = false): void => {
        const controller = new AbortController();
        const request: Tier2Request = {
          controller, context: c, from, to, mode, version,
          liveAfter: replaceLive ? state.liveRevision : null, started: false, receive: () => {},
        };
        state.request = request;
        observe(request);
        publish({ state: 'loading' });
        start(request);
      };
      const refresh = (retry = false): void => {
        // The context a variant-only change passes through is replaced at
        // once: fetching or subscribing for it would be torn down unused.
        if (!current() || passingContext(ctx.dataContext?.())) return;
        const revision = ++refreshRevision;
        const fresh = (): boolean => current() && refreshRevision === revision;
        const c = context();
        const previous = state.lastContext;
        state.lastContext = c;
        const market = c.dataContext;
        const native = c.requestState;
        const replay = native?.replay;
        const source = native?.source;
        const oldSource = previous?.requestState?.source;
        const oldReplay = previous?.requestState?.replay;
        // A change of variant alone is a change of source: the chart's bars are
        // another series. Read as plain JSON, which cannot throw inside a listener.
        const key = JSON.stringify([cacheKey(d, c.settings), market?.symbol, market?.exchange, market?.interval, market?.variant ?? null,
          native?.providerRevision, source?.sourceId, replay !== undefined]);
        const offset = c.bars.length - (previous?.bars.length ?? 0);
        const safePrepend = previous !== undefined && oldSource !== undefined && source !== undefined
          && source.change === 'prepend' && source.revision === oldSource.revision + 1
          && source.historyRevision === oldSource.historyRevision + 1 && c.bars !== previous.bars && offset > 0
          && previous.bars.every((bar, i) => c.bars[offset + i] === bar);
        const historyChanged = replay === undefined && source !== undefined && oldSource !== undefined
          && source.historyRevision !== oldSource.historyRevision && !safePrepend;
        const backward = c.asOf !== undefined && oldReplay?.asOf !== undefined && c.asOf < oldReplay.asOf;
        const changed = key !== state.key || historyChanged || backward;
        if (changed) {
          clear();
          if (!fresh()) return;
          state.key = key;
        }
        let supported: boolean;
        try { supported = (replay === undefined || (d.supportsReplay === true && Number.isFinite(c.asOf))) && (d.supports?.(c) ?? true); }
        catch (error) { if (fresh()) publish({ state: 'error', error }); return; }
        if (!fresh()) return;
        if (!supported) {
          clear(); if (fresh()) publish({ state: 'unsupported' });
          return;
        }
        if (c.bars.length === 0) {
          // Older hosts use range truncation without native replay metadata.
          if (native !== undefined) { clear(); if (fresh()) publish({ state: 'empty' }); }
          else if (state.request === null) publish({ state: 'empty' });
          return;
        }
        const version = JSON.stringify([key, c.from, d.subscribe === undefined || replay !== undefined ? c.to : null,
          replay === undefined && d.subscribe === undefined ? source?.revision : null, native?.dataRevision, c.asOf]);
        // A prefix page can carry the latest revision while its right edge is
        // still unfetched. Revision equality alone cannot certify both ends.
        const uncovered = c.from < state.from || (d.subscribe === undefined && c.to > state.to);
        if (state.request !== null) { const request = state.request; observe(request); start(request); }
        else if (retry || changed || (native !== undefined
          ? state.completedVersion !== version || (uncovered && state.status.state !== 'error')
          : state.status.state !== 'error')) {
          const externalChanged = native !== undefined
            && (state.completedContext?.requestState?.dataRevision ?? state.baseDataRevision) !== native.dataRevision;
          if (!state.loaded || retry) load(c, c.from, c.to, 'replace', version, externalChanged);
          else if (replay !== undefined || externalChanged) load(c, c.from, c.to, 'replace', version, externalChanged);
          else if (c.from < state.from) load(c, c.from, state.from, 'prepend', version);
          else if (d.subscribe === undefined && (c.to > state.to || native !== undefined)) load(c, state.to, c.to, 'tail', version);
          else publish({ state: state.points.length > 0 ? 'ready' : 'empty' });
        }
        if (!fresh()) return;
        if (state.subscription === null && d.subscribe !== undefined && replay === undefined) {
          const liveGeneration = generation;
          const subscription: Tier2Subscription = {};
          state.subscription = subscription;
          try {
            const dispose = d.subscribe(c, (point) => {
              if (!current() || generation !== liveGeneration || state.subscription !== subscription || !Number.isFinite(point.time)) return;
              upsert(state.live, point);
              state.liveVersions.set(point.time, ++state.liveRevision);
              upsert(state.points, point);
              ctx.requestRecompute();
              if (!current() || generation !== liveGeneration || state.subscription !== subscription) return;
              if (state.request === null && state.status.state !== 'error') publish({ state: 'ready' });
            });
            if (current() && generation === liveGeneration && state.subscription === subscription) subscription.dispose = dispose;
            else dispose();
          } catch (error) {
            if (current() && state.subscription === subscription) { state.subscription = null; publish({ state: 'error', error }); }
          }
        }
      };
      const cleanup = (): void => {
        if (!current() && !active) return;
        active = false;
        unsubscribeChanges();
        ctx.signal?.removeEventListener('abort', abort);
        if (state.generation !== generation) return;
        state.generation += 1;
        const detached = state.generation;
        ctx.setDataRetry?.(null);
        stopLive();
        // Hand-built contexts have no lifetime signal. Allow synchronous style
        // reattachment before aborting history that no attachment still owns.
        queueMicrotask(() => { if (state.generation === detached) cancel(); });
      };
      const abort = (): void => { if (state.generation === generation) cancel(); cleanup(); };
      stopLive();
      ctx.signal?.addEventListener('abort', abort, { once: true });
      // Request notifications go with `requestState`: the revisions they
      // announce are read from it. A host without it is an older host whose
      // bars and identity arrive through data notifications, which `refresh`
      // reads by range. The requested indicator needs a native host for its
      // snapshots, so it takes request notifications whenever they exist.
      unsubscribeChanges = ctx.requestState !== undefined && ctx.subscribeRequestChanges !== undefined
        ? ctx.subscribeRequestChanges(() => refresh()) : ctx.subscribeDataChanges?.(() => refresh()) ?? (() => {});
      ctx.setDataRetry?.(() => refresh(true));
      const failure = failures.get(ctx.store);
      if (state.errorKind === 'calc' && failure === undefined) {
        state.errorKind = undefined;
        state.status = { state: state.points.length ? 'ready' : 'empty' };
      }
      ctx.setDataStatus?.(failure?.points === state.points ? { state: 'error', error: failure.error } : state.status);
      refresh(state.status.state === 'error' && state.errorKind !== 'calc');
      return cleanup;
    },
  } as IndicatorDescriptor;
}
