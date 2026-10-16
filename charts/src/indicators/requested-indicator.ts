import {
  IndicatorInputError, dataVariantKey, normalizeDataVariant,
  type Bar, type ChartDataContext, type IndicatorCalcContext, type IndicatorDataStatus,
  type IndicatorDescriptor, type IndicatorRequestState, type IndicatorSettings,
  type IndicatorSnapshotRequest, type IndicatorStore, type IndicatorValues, type RequestedBarsSnapshot,
} from 'openalgo-charts';
import { alignRequestedExpression, type RequestedAlignmentOptions } from './requested-context';
import { inheritedDataVariant, passingContext } from './inherited-variant';

/** Source and settings visible to request selection and requested calculation. */
export interface RequestedIndicatorContext {
  bars: readonly Bar[];
  settings: Readonly<IndicatorSettings>;
  dataContext?: Readonly<ChartDataContext>;
  requestState?: Readonly<IndicatorRequestState>;
  calculation?: IndicatorCalcContext;
}

/** A requested expression with an instance-owned snapshot lifecycle. */
export interface RequestedIndicatorDescriptor extends Pick<IndicatorDescriptor,
  'id' | 'name' | 'category' | 'placement' | 'inputs' | 'plots' | 'levels' | 'range'> {
  /**
   * Select a complete history window, including expression warmup. null means
   * unsupported. The helper owns cancellation; signal is not a selector input.
   * Symbol, exchange, interval, variant and explicit asOf changes start a new
   * generation, and so does a change of the chart's own variant. A request that
   * names no `variant` asks in the chart's session and adjustment (see
   * `inheritedDataVariant`); naming one, `{}` included, overrides that.
   * Window changes refresh the complete selection without merging partial pages.
   */
  request(ctx: RequestedIndicatorContext): Omit<IndicatorSnapshotRequest, 'signal'> | null;
  /**
   * Calculate on copied, frozen requested bars before alignment. Each result at
   * i must depend only on requested observations through i. Return every plot's
   * named column with one value per requested bar. Nonfinite values become null.
   * Under asOf, only the known, confirmed prefix available by that cutoff is
   * supplied. Provider correctness for historical value versions remains required.
   */
  expression(
    bars: readonly Readonly<Bar>[],
    settings: Readonly<IndicatorSettings>,
    ctx: RequestedIndicatorContext,
  ): IndicatorValues;
  /** carry retains the latest eligible row, including null; missing emits a newly selected row only. */
  gaps?: RequestedAlignmentOptions['gaps'];
  /**
   * Strictly increasing finite availability query times, one per source bar.
   * Defaults to source opening times. Use an explicit final playhead time when
   * a forming source bar should observe requested data available after opening.
   */
  targetTimes?(ctx: RequestedIndicatorContext): readonly number[];
}

interface Selection {
  key: string;
  version: string;
  request: Omit<IndicatorSnapshotRequest, 'signal'>;
}

interface Pending {
  selection: Selection;
  controller: AbortController;
  started: boolean;
  promise: Promise<RequestedBarsSnapshot>;
  resolve(value: RequestedBarsSnapshot | PromiseLike<RequestedBarsSnapshot>): void;
  reject(reason: unknown): void;
}

interface State {
  owner: number;
  key: string | null;
  completed: string | null;
  wanted: Selection | null;
  request: Pending | null;
  snapshot: RequestedBarsSnapshot | null;
  context: RequestedIndicatorContext | null;
  status: IndicatorDataStatus;
}

const STATE = '__requestedIndicator';
const EMPTY: RequestedBarsSnapshot = { bars: [], availableAt: [], confirmed: [] };
const stateOf = (store: IndicatorStore): State | undefined => store[STATE] as State | undefined;
const invalid = (message: string): never => { throw new IndicatorInputError(`Requested indicator: ${message}`); };

function checkedRequest(value: Omit<IndicatorSnapshotRequest, 'signal'>, market?: Readonly<ChartDataContext>): Omit<IndicatorSnapshotRequest, 'signal'> {
  if (value === null || typeof value !== 'object'
    || typeof value.symbol !== 'string' || value.symbol.trim() === ''
    || typeof value.interval !== 'string' || value.interval.trim() === ''
    || (value.exchange !== undefined && typeof value.exchange !== 'string')
    || !Number.isFinite(value.from) || !Number.isFinite(value.to) || value.from > value.to
    || (value.asOf !== undefined && !Number.isFinite(value.asOf))) invalid('request requires an instrument and a finite ordered time window');
  let variant;
  try { variant = value.variant === undefined ? inheritedDataVariant(market?.variant) : normalizeDataVariant(value.variant); }
  catch { invalid('request variant must be a data variant'); }
  // An absent `exchange` or `asOf` is copied as undefined, which a provider
  // reads as absent; the request types keep those members exact for hosts.
  return { symbol: value.symbol, exchange: value.exchange, interval: value.interval, from: value.from, to: value.to, asOf: value.asOf,
    ...(variant ? { variant } : {}) } as Omit<IndicatorSnapshotRequest, 'signal'>;
}

/** Validate every row before truncation, including rows beyond an availability barrier. */
function ownSnapshot(value: RequestedBarsSnapshot, asOf?: number): RequestedBarsSnapshot {
  let copied: readonly Bar[] = [];
  alignRequestedExpression([], value, bars => { copied = bars; return {}; });
  let count = copied.length;
  if (asOf !== undefined) {
    count = 0;
    while (count < copied.length && value.confirmed[count]
      && value.availableAt[count] !== null && value.availableAt[count]! <= asOf) count++;
  }
  return Object.freeze({
    bars: Object.freeze(copied.slice(0, count)),
    availableAt: Object.freeze(value.availableAt.slice(0, count)),
    confirmed: Object.freeze(value.confirmed.slice(0, count)),
  });
}

/**
 * Manage one requested snapshot per instance. Changes are observed through the
 * optional native request hooks, or through data notifications on older hosts.
 * There is at most one active request and one latest pending refresh. Provider,
 * source, history or market changes and backward replay cancel obsolete work.
 * Synchronous style reattachment retains pending work when its selection is
 * unchanged. Calculation performs no requests and never prealigns cached values.
 */
export function createRequestedIndicator(d: RequestedIndicatorDescriptor): IndicatorDescriptor {
  if (typeof d.request !== 'function' || typeof d.expression !== 'function') invalid('request and expression must be functions');
  if (d.gaps !== undefined && d.gaps !== 'carry' && d.gaps !== 'missing') invalid('gaps must be carry or missing');
  if (d.targetTimes !== undefined && typeof d.targetTimes !== 'function') invalid('targetTimes must be a function');
  const columns = [...new Set(d.plots.flatMap(plot => plot.ohlc === undefined
    ? [plot.key] : [plot.ohlc.open, plot.ohlc.high, plot.ohlc.low, plot.ohlc.close]))];
  // Native hosts can contain calculation errors instead of throwing to attach.
  const failures = new WeakMap<IndicatorStore, { snapshot: RequestedBarsSnapshot | null; error: unknown }>();
  // As in `createTier2Indicator`: the optional members are copied whether or
  // not `d` sets them, and `levels` and `range` are methods.
  return {
    id: d.id, name: d.name, category: d.category, placement: d.placement,
    inputs: d.inputs, plots: d.plots, levels: d.levels, range: d.range,
    calc: (bars, settings, store, calculation) => {
      const state = stateOf(store);
      try {
        // `calculation` is undefined when the runtime passes none, and the
        // context carries it so, which readers take as absent; as in `refresh`
        // below, the public type stays exact for hosts.
        const context = { ...state?.context, bars, settings, calculation } as RequestedIndicatorContext;
        const times = d.targetTimes?.(context) ?? bars.map(bar => bar.time);
        if (!Array.isArray(times) || times.length !== bars.length) invalid('target times must match source length');
        const values = alignRequestedExpression(times, state?.snapshot ?? EMPTY,
          requested => d.expression(requested, settings, context), { gaps: d.gaps });
        for (const column of columns) {
          if (state?.snapshot?.bars.length && !Object.prototype.hasOwnProperty.call(values, column)) invalid(`expression is missing plot column ${column}`);
          if (!Object.prototype.hasOwnProperty.call(values, column)) {
            Object.defineProperty(values, column, { value: new Array<null>(bars.length).fill(null), enumerable: true, writable: true, configurable: true });
          }
        }
        failures.delete(store);
        return values;
      } catch (error) {
        failures.set(store, { snapshot: state?.snapshot ?? null, error });
        throw error;
      }
    },
    attach: ctx => {
      const state = stateOf(ctx.store) ?? {
        owner: 0, key: null, completed: null, wanted: null, request: null,
        snapshot: null, context: null, status: { state: 'empty' },
      };
      ctx.store[STATE] = state;
      const owner = ++state.owner;
      let active = true;
      let fallbackRevision = 0;
      let refreshRevision = 0;
      let observed: Pending | null = null;
      let unsubscribe = (): void => {};
      const current = (): boolean => active && state.owner === owner && !ctx.signal?.aborted;
      const publish = (status: IndicatorDataStatus): void => {
        state.status = status;
        if (current()) ctx.setDataStatus?.(status);
      };
      const cancel = (): void => {
        const request = state.request;
        state.request = null;
        observed = null;
        request?.controller.abort();
        request?.reject(request.controller.signal.reason);
      };
      const clear = (): void => {
        state.completed = null;
        state.wanted = null;
        const hadSnapshot = state.snapshot !== null;
        state.snapshot = null;
        cancel();
        if (hadSnapshot) ctx.requestRecompute();
      };
      const observe = (request: Pending): void => {
        if (observed === request) return;
        observed = request;
        void request.promise.then(value => {
          if (!current() || state.request !== request || request.controller.signal.aborted) return;
          let snapshot: RequestedBarsSnapshot;
          try { snapshot = ownSnapshot(value, request.selection.request.asOf); }
          catch (error) { completeError(request, error); return; }
          state.request = null;
          observed = null;
          const previous = state.snapshot;
          state.snapshot = snapshot;
          state.completed = request.selection.version;
          try {
            ctx.requestRecompute();
            const failure = failures.get(ctx.store);
            if (failure?.snapshot === snapshot) throw failure.error;
          }
          catch (error) {
            if (current() && state.snapshot === snapshot && state.key === request.selection.key) {
              state.snapshot = previous;
              publish({ state: 'error', error });
              if (state.wanted?.version !== request.selection.version) refresh();
            }
            return;
          }
          if (!current() || state.snapshot !== snapshot) return;
          if (state.request === null) publish({ state: snapshot.bars.length ? 'ready' : 'empty' });
          refresh();
        }, error => completeError(request, error));
      };
      const completeError = (request: Pending, error: unknown): void => {
        if (!current() || state.request !== request || request.controller.signal.aborted) return;
        state.request = null;
        observed = null;
        state.completed = request.selection.version;
        publish({ state: 'error', error });
        if (state.wanted?.version !== request.selection.version) refresh();
      };
      const start = (request: Pending): void => {
        if (!current() || state.request !== request || request.controller.signal.aborted || request.started) return;
        request.started = true;
        try { request.resolve(ctx.requestSnapshot!({ ...request.selection.request, signal: request.controller.signal })); }
        catch (error) { request.reject(error); }
      };
      const load = (selection: Selection): void => {
        const controller = new AbortController();
        let resolve!: Pending['resolve'];
        let reject!: Pending['reject'];
        const promise = new Promise<RequestedBarsSnapshot>((answer, fail) => { resolve = answer; reject = fail; });
        const request: Pending = { selection, controller, started: false, promise, resolve, reject };
        // The same pending promise can be adopted before or during provider entry.
        state.request = request;
        observe(request);
        publish({ state: 'loading' });
        start(request);
      };
      const refresh = (retry = false): void => {
        // A context a variant-only change passes through is replaced before
        // anything could answer for it, so nothing is selected or asked for it.
        if (!current() || passingContext(ctx.dataContext?.())) return;
        const revision = ++refreshRevision;
        const fresh = (): boolean => current() && refreshRevision === revision;
        const previous = state.context?.requestState?.replay;
        const requestState = ctx.requestState?.();
        const replay = requestState?.replay;
        const context = {
          bars: ctx.bars(), settings: ctx.settings(),
          dataContext: ctx.dataContext?.(), requestState,
        } as RequestedIndicatorContext;
        state.context = context;
        let selected: Omit<IndicatorSnapshotRequest, 'signal'> | null;
        let variant = '';
        try {
          const value = d.request(context);
          selected = value === null ? null : checkedRequest(value, context.dataContext);
          // The chart's variant is part of its source even when the request
          // does not inherit it: the source bars themselves are another series.
          variant = dataVariantKey(context.dataContext?.variant);
        }
        catch (error) { if (fresh()) { clear(); if (fresh()) publish({ state: 'error', error }); } return; }
        if (!fresh()) return;
        if (selected === null || ctx.requestSnapshot === undefined || requestState?.supportsSnapshots === false
          || (replay !== undefined && replay.asOf === undefined)) {
          clear(); if (fresh()) { state.key = null; publish({ state: 'unsupported' }); } return;
        }
        if (context.bars.length === 0) { clear(); if (fresh()) publish({ state: 'empty' }); return; }
        const source = requestState?.source;
        const market = context.dataContext;
        const key = JSON.stringify([
          selected.symbol, selected.exchange, selected.interval, selected.asOf,
          market?.symbol, market?.exchange, market?.interval, variant, selected.variant ?? null,
          requestState?.providerRevision, source?.sourceId,
          replay === undefined ? source?.historyRevision : null, replay !== undefined,
        ]);
        const backward = replay?.asOf !== undefined && previous?.asOf !== undefined && replay.asOf < previous.asOf;
        if (state.key !== key || backward) { clear(); if (!fresh()) return; state.key = key; }
        if (replay?.asOf !== undefined) selected.asOf = selected.asOf === undefined ? replay.asOf : Math.min(selected.asOf, replay.asOf);
        const version = JSON.stringify([
          key, selected.from, selected.to, selected.asOf, replay === undefined ? source?.revision : null,
          requestState?.dataRevision, replay?.time, replay?.forming, fallbackRevision,
        ]);
        const selection = { key, version, request: selected };
        state.wanted = selection;
        if (state.request !== null) { observe(state.request); start(state.request); }
        else if (retry || state.completed !== version) load(selection);
      };
      const cleanup = (): void => {
        if (!active) return;
        active = false;
        unsubscribe();
        ctx.signal?.removeEventListener('abort', abort);
        if (state.owner !== owner) return;
        ctx.setDataRetry?.(null);
        // A synchronous style reattachment can adopt this request and snapshot.
        queueMicrotask(() => { if (state.owner === owner) cancel(); });
      };
      const abort = (): void => { if (state.owner === owner) cancel(); cleanup(); };
      ctx.signal?.addEventListener('abort', abort, { once: true });
      unsubscribe = ctx.subscribeRequestChanges !== undefined
        ? ctx.subscribeRequestChanges(() => refresh())
        : ctx.subscribeDataChanges?.(() => { fallbackRevision++; refresh(); }) ?? (() => {});
      ctx.setDataRetry?.(() => refresh(true));
      const failure = failures.get(ctx.store);
      ctx.setDataStatus?.(failure?.snapshot === state.snapshot ? { state: 'error', error: failure.error } : state.status);
      refresh();
      return cleanup;
    },
  } as IndicatorDescriptor;
}
