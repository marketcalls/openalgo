/**
 * Date and range navigation for a host: load the history a request needs
 * through the host's own loader, then place it with the chart's public
 * viewport and time conversion. DOM-free, so the packaged widget and a custom
 * host apply one set of rules.
 *
 * Three decisions carry it:
 *
 * - **A date names a bar by its calendar day, not by its stamp.** Daily bars
 *   arrive stamped at local midnight, at the session open or at UTC midnight,
 *   so a typed date is before its own bar in two of those three. Bars a day or
 *   longer are therefore counted from the local midnight of their first day;
 *   shorter bars keep their stamp, and an instant in an overnight or weekend
 *   gap moves to the next session.
 * - **History stays contiguous.** Missing history is older bars prepended to
 *   what is loaded, never a detached window, because the gapless axis would
 *   draw a detached window as if it continued straight into the live tail.
 * - **The placement is the last thing that happens.** It runs after the
 *   accepted load and only for the request, instrument and chart it was made
 *   for, so an obsolete answer cannot move the view and a later refresh keeps
 *   the anchor it finds.
 */
import {
  bucketStartOf, isReplaying, isTimeBucketed, nextBucketStart, startOfZonedDay, tryResolveInterval,
  type Bucketing, type Chart,
} from 'openalgo-charts';

/** A date to show, or an explicit range. UTC seconds throughout. */
export interface DateNavigationTarget {
  /** The date to show, or the start of the range. */
  from: number;
  /**
   * Inclusive end of a range: bars that open at or before it, a bar a day or
   * longer counting from the local midnight of its first day. Omit to centre
   * `from` at the current zoom.
   */
  to?: number;
}

/**
 * What one call to a host history loader achieved. `loaded` means older bars
 * reached the chart; `empty` means the windows it inspected held none, though
 * older history may still exist; `exhausted` means the source has nothing
 * older; `limited` means a retention limit stopped it; `unavailable` means
 * history cannot load now (no loader, replay, a paused source).
 */
export type HistoryReach = 'loaded' | 'empty' | 'exhausted' | 'limited' | 'unavailable';

/**
 * `placed`: the request is in view. `partial`: something is in view, but
 * history stops after the requested start or the range is wider than the
 * chart. `no-data`: nothing to show, the view is unchanged. `unsupported`:
 * the interval has no time buckets (tick or volume bars), so it has no dates
 * to go to. `invalid`: `from` or `to` is not a finite time, `to` is before
 * `from`, or (from `setRange`) the range id is not one the widget has.
 * `cancelled`: a newer request, a context change or destruction took over.
 * `error`: the history loader failed; the result's `error` says how.
 */
export type DateNavigationStatus = 'placed' | 'partial' | 'no-data' | 'unsupported' | 'invalid' | 'cancelled' | 'error';

export interface DateNavigationResult {
  status: DateNavigationStatus;
  /** Open time of the first bar the placement shows. */
  from?: number | undefined;
  /** Open time of the last bar the placement shows. */
  to?: number | undefined;
  /** Why loaded history stops after the requested start. */
  history?: Exclude<HistoryReach, 'loaded'>;
  /** The range held more bars than the chart can show at its narrowest spacing; its start is in view. */
  clipped?: boolean;
  error?: Error;
}

export interface DateNavigatorOptions {
  /** The chart to place. A function is read again after every load, for a host that rebuilds its chart. */
  chart: Chart | (() => Chart | null);
  /**
   * Prepend older primary bars reaching back to `time`, resolving once they
   * are on the chart. Called again while it adds bars and `time` is not yet
   * reached. Omit to navigate loaded history only.
   */
  loadHistory?(time: number, signal: AbortSignal): Promise<HistoryReach>;
  /** Interval code of the primary bars. Default: the chart's data context. */
  interval?(): string | undefined;
}

/** Bars kept to the right of the newest one when a date near it is centred: the engine's default margin. */
const RIGHT_MARGIN = 4;

interface Frame {
  /** The instant a bar starting at `t` counts from. */
  open(t: number): number;
  /** The instant it closes. */
  close(t: number): number;
}

function frameOf(b: Bucketing, zone: string): Frame {
  if (b.mode === 'interval') {
    if (b.seconds < 86400) return { open: t => t, close: t => t + b.seconds };
    const open = (t: number): number => startOfZonedDay(t, zone);
    // Across a clock change a day is 23 or 25 hours, so the close is the local
    // midnight that ends the bar's last day. Half a day past the fixed length
    // lands inside that next day whichever way the clock moved.
    return { open, close: t => startOfZonedDay(open(t) + b.seconds + 43200, zone) };
  }
  return { open: t => bucketStartOf(b, t, zone), close: t => nextBucketStart(b, t, zone) ?? t };
}

/** The clock or calendar buckets of `code`, or null when it has none a date can name. */
export function timeBuckets(code: string | undefined): Bucketing | null {
  const found = code === undefined ? null : tryResolveInterval(code);
  return found !== null && isTimeBucketed(found.bucketing) ? found.bucketing : null;
}

const cancelled = (): DateNavigationResult => ({ status: 'cancelled' });

function identity(chart: Chart): string {
  const context = chart.getDataContext();
  return `${context?.symbol}\u0000${context?.exchange}\u0000${context?.interval}`;
}

/** Settle with the host's answer, or at once when the request is abandoned. */
function abortable<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const stop = (): void => reject(signal.reason);
    if (signal.aborted) { stop(); return; }
    signal.addEventListener('abort', stop, { once: true });
    work.then(resolve, reject).finally(() => signal.removeEventListener('abort', stop));
  });
}

/** The first index in [0, n) for which `after` holds, or n. `after` must be monotonic. */
function firstWhere(n: number, after: (i: number) => boolean): number {
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (after(mid)) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/**
 * Whether bars could be missing between `from` and `firstOpen`, the open of
 * the first loaded bar. A gap no session trades in (a weekend, a holiday, the
 * hours before another venue's open) holds no bars, so history that starts
 * after one is whole. Without a calendar, or one that cannot answer, any gap
 * counts, as it always has. So does a calendar that finds no session at all:
 * its search has a horizon, so that says nothing about the gap.
 */
function sessionBefore(chart: Chart, from: number, firstOpen: number): boolean {
  const calendar = chart.dataLayer.sessionCalendar;
  if (calendar === null) return true;
  try {
    const session = calendar.sessionFrom(from);
    return session === null || session.open < firstOpen;
  } catch {
    return true;
  }
}

function place(chart: Chart, frame: Frame, from: number, to: number | undefined, reach: HistoryReach | undefined): DateNavigationResult {
  const bars = chart.primaryBars();
  const n = bars.length;
  // Every index read below is inside the bars: firstWhere probes [0, n), and
  // start, stop, last and n - 1 are in [0, n) once the no-data return has passed.
  // History only falls short when its first bar still counts from after the
  // request, and a session could have traded in between.
  const firstOpen = n > 0 ? frame.open(bars[0]!.time) : from;
  const history = reach !== undefined && reach !== 'loaded' && firstOpen > from && sessionBefore(chart, from, firstOpen) ? reach : undefined;
  const start = firstWhere(n, i => frame.close(bars[i]!.time) > from);
  const stop = to === undefined ? start : firstWhere(n, i => frame.open(bars[i]!.time) > to) - 1;
  if (start >= n || stop < start) return history === undefined ? { status: 'no-data' } : { status: 'no-data', history };
  const index = (i: number): number => chart.dataLayer.timeToIndex(bars[i]!.time) ?? i;
  let a: number;
  let z: number;
  let last = stop;
  let clipped = false;
  if (to === undefined) {
    const view = chart.getVisibleLogicalRange();
    const half = (view.to - view.from) / 2;
    const at = index(start);
    const shift = Math.max(0, at + half - index(n - 1) - RIGHT_MARGIN);
    a = at - half - shift;
    z = at + half - shift;
  } else {
    a = index(start) - 0.5;
    z = index(stop) + 0.5;
    const width = chart.timeScale.width;
    if (width > 0) {
      const fit = width / chart.timeScale.constrainBarSpacing(width / (z - a));
      if (fit < z - a - 1e-9) {
        z = a + fit;
        clipped = true;
        while (last > start && index(last) > z - 0.5) last--;
      } else {
        a -= (fit - (z - a)) / 2;
        z = a + fit;
      }
    }
  }
  chart.setVisibleLogicalRange({ from: a, to: z });
  const result: DateNavigationResult = { status: history !== undefined || clipped ? 'partial' : 'placed', from: bars[start]!.time, to: bars[last]!.time };
  if (history !== undefined) result.history = history;
  if (clipped) result.clipped = true;
  return result;
}

/**
 * Loads missing history, then places a date or an explicit UTC range. One
 * request at a time: a new `goTo` supersedes the one in flight, whose promise
 * settles `cancelled` without touching the view.
 */
export class DateNavigator {
  private readonly _options: DateNavigatorOptions;
  private _abort: AbortController | null = null;
  private _destroyed = false;

  public constructor(options: DateNavigatorOptions) {
    this._options = options;
  }

  public goTo(target: DateNavigationTarget): Promise<DateNavigationResult> {
    this.cancel();
    if (this._destroyed) return Promise.resolve(cancelled());
    const abort = new AbortController();
    this._abort = abort;
    return this._run(target, abort.signal)
      .catch((error: unknown): DateNavigationResult => abort.signal.aborted ? cancelled()
        : { status: 'error', error: error instanceof Error ? error : new Error(String(error)) })
      .finally(() => { if (this._abort === abort) this._abort = null; });
  }

  /** Abandon the request in flight. Bars it already loaded stay. */
  public cancel(): void {
    const abort = this._abort;
    this._abort = null;
    abort?.abort();
  }

  public destroy(): void {
    this._destroyed = true;
    this.cancel();
  }

  private _chart(): Chart | null {
    const source = this._options.chart;
    const chart = typeof source === 'function' ? source() : source;
    return chart !== null && !chart.isDestroyed ? chart : null;
  }

  private async _run(target: DateNavigationTarget, signal: AbortSignal): Promise<DateNavigationResult> {
    const { from, to } = target;
    if (!Number.isFinite(from) || (to !== undefined && !(Number.isFinite(to) && to >= from))) return { status: 'invalid' };
    let chart = this._chart();
    if (chart === null) return cancelled();
    const context = identity(chart);
    const buckets = timeBuckets(this._options.interval?.() ?? chart.getDataContext()?.interval);
    if (buckets === null) return { status: 'unsupported' };
    const frame = frameOf(buckets, chart.timezone());
    const bars = chart.primaryBars();
    if (bars.length === 0 || frame.close(bars[bars.length - 1]!.time) <= from) return { status: 'no-data' }; // length checked first
    // A date is centred, so aim far enough back that the left half of the view has bars too.
    const view = chart.getVisibleLogicalRange();
    const lead = to === undefined ? Math.ceil(Math.max(0, view.to - view.from) / 2) : 0;
    const aim = from - lead * (frame.close(from) - frame.open(from));
    let first = bars[0]!.time; // not empty: the no-data return above
    let reach: HistoryReach | undefined;
    while (frame.open(first) > aim && sessionBefore(chart, aim, frame.open(first))) {
      const load = this._options.loadHistory;
      if (load === undefined || isReplaying(chart)) { reach = 'unavailable'; break; }
      reach = await abortable(load(aim, signal), signal);
      chart = this._chart();
      if (signal.aborted || chart === null || identity(chart) !== context) return cancelled();
      const next = chart.primaryBars()[0]?.time;
      if (reach !== 'loaded') break;
      // A loader that reports progress it did not make would otherwise be asked forever.
      if (next === undefined || next >= first) { reach = 'empty'; break; }
      first = next;
    }
    return place(chart, frame, from, to, reach);
  }
}
