/**
 * The widget's side of the bottom bar: the options it reads, the preset
 * ranges it applies, the session calendar it hands the chart and the shading
 * it attaches from that calendar.
 *
 * Its own module so widget.ts keeps only the hooks: a mount call, the load
 * window a range widens, and the two public methods. The shell calls
 * `attachBottombar` with itself as `this`, typed `BottombarHost`, for the
 * reasons widget-keys.ts gives: a member the shell renames or retypes fails
 * to compile here.
 *
 * A range is the widget's, not the bar's: `setRange` works with the bar
 * turned off, and a grid cell (which has none) is driven by the grid's bar
 * through it. The range holds while its interval does. A symbol change keeps
 * it and places it again on the new instrument; an interval changed by any
 * other means leaves it, and loads go back to the ordinary lookback.
 */
import { attachSessionShading, type SessionCalendarSource } from 'openalgo-charts';
import { h } from './context';
import type { DateNavigationResult } from './date-navigator';
import { mountBottombar, type BottombarControls } from './bottombar';
import { DEFAULT_RANGES, rangeInterval, rangeWindow, type WidgetRange, type WidgetRangeWindow } from './ranges';
import type { WidgetImpl } from './widget';

/**
 * Trading hours for the widget's instruments: one calendar for every symbol,
 * or a function asked on each symbol change. A `SessionCalendar` or an
 * `Instrument` is one; null means none.
 */
export type WidgetSessionCalendar =
  | SessionCalendarSource
  | null
  | ((instrument: { readonly symbol: string; readonly exchange: string }) => SessionCalendarSource | null | undefined);

/** The widget options the bottom bar and the session calendar read. */
export interface WidgetBottombarOptions {
  /**
   * The strip under the chart: preset ranges and Go to on the left, the
   * market status, a clock that opens the timezone choice and the price
   * scale toggles on the right. The phone layout hides it and lists its
   * controls in the More sheet. Default true.
   */
  bottombar?: boolean;
  /** Preset ranges for the bar and `setRange`. `[]` leaves the range buttons out. Default `DEFAULT_RANGES`. */
  ranges?: readonly WidgetRange[];
  /**
   * Trading hours, applied with `chart.setSessionCalendar` for the first
   * symbol and on every symbol change. They size a range's fetch in
   * sessions, give the bar its market status and the shading its hours.
   * Default: the widget leaves the chart's calendar to the host.
   */
  sessionCalendar?: WidgetSessionCalendar;
  /**
   * Shade the pre-open, post-close and extended-hours bars from the chart's
   * calendar (`attachSessionShading`). A calendar without those hours, or no
   * calendar, shades nothing. Default true.
   */
  sessionShading?: boolean;
}

/** The option names above, which the shell keeps from the chart. */
export const BOTTOMBAR_OPTION_KEYS = ['bottombar', 'ranges', 'sessionCalendar', 'sessionShading'] as const;

/** The slice of the shell the bottom bar reads and drives. */
export interface BottombarHost {
  readonly chart: WidgetImpl['chart'];
  readonly root: WidgetImpl['root'];
  readonly context: WidgetImpl['context'];
  readonly _statusline: WidgetImpl['_statusline'];
  readonly _opts: WidgetImpl['_opts'];
  readonly _bus: WidgetImpl['_bus'];
  readonly _intervals: WidgetImpl['_intervals'];
  readonly _cleanups: WidgetImpl['_cleanups'];
  readonly _destroyed: WidgetImpl['_destroyed'];
  readonly _loading: WidgetImpl['_loading'];
  readonly _symbol: WidgetImpl['_symbol'];
  readonly _exchange: WidgetImpl['_exchange'];
  readonly _interval: WidgetImpl['_interval'];
  readonly setInterval: WidgetImpl['setInterval'];
  readonly goTo: WidgetImpl['goTo'];
  readonly _openGoTo: WidgetImpl['_openGoTo'];
  readonly _scheduleSave: WidgetImpl['_scheduleSave'];
}

/** What the shell keeps of the bar: the range methods, the load window hook and the controls for the phone layout. */
export interface ShellBottombar {
  setRange(id: string): Promise<DateNavigationResult>;
  range(): string | null;
  /** The window a load asks for: `fallback`, widened to the range in force. */
  fetchWindow(fallback: WidgetRangeWindow, nowSec: number): WidgetRangeWindow;
  /** The bar's controls for the More sheet, or undefined with the bar off. */
  readonly controls: BottombarControls | undefined;
}

const asError = (error: unknown): Error => (error instanceof Error ? error : new Error(String(error)));

/** Wire the calendar, the shading, the ranges and, unless it is off, the bar, inserted before `before`. */
export function attachBottombar(this: BottombarHost, before: HTMLElement): ShellBottombar {
  return wire(this, before);
}

function wire(host: BottombarHost, before: HTMLElement): ShellBottombar {
  const opts = host._opts;
  const chart = host.chart;
  const ranges = opts.ranges ?? DEFAULT_RANGES;

  // ── the instrument's hours ───────────────────────────────────────────
  // Resolved from the widget's own symbol rather than read back from the
  // chart: a load starts before the symbol is announced, and its window has
  // to be sized in the new instrument's sessions, not the last one's.
  const option = opts.sessionCalendar;
  let resolvedFor: string | null = null;
  let resolved: SessionCalendarSource | null = null;
  const calendarOf = (symbol: string, exchange: string): SessionCalendarSource | null => {
    if (typeof option !== 'function') return option ?? null;
    const key = `${exchange}\u0000${symbol}`;
    if (key !== resolvedFor) {
      resolvedFor = key;
      try { resolved = symbol === '' ? null : option({ symbol, exchange }) ?? null; } catch { resolved = null; }
    }
    return resolved;
  };
  const calendar = (): SessionCalendarSource | null => (option === undefined
    ? chart.dataLayer.sessionCalendar : calendarOf(host._symbol, host._exchange));
  if (option !== undefined) {
    const apply = (): void => {
      if (chart.isDestroyed) return;
      chart.setSessionCalendar(calendarOf(host._symbol, host._exchange));
      // Setting hours announces nothing; the status line reads them again now.
      host._statusline?.refresh();
    };
    apply();
    host._cleanups.push(host._bus.on('symbol', apply));
  }
  if (opts.sessionShading !== false) {
    const shading = attachSessionShading(chart);
    host._cleanups.push(() => shading.destroy());
  }
  // The zone is part of the saved layout, and nothing else the shell follows
  // announces it: a zone picked from the bar or set by the host's own call
  // would otherwise be lost on the next visit.
  host._cleanups.push(chart.on('timezone:changed', () => {
    if (host._destroyed) return;
    host._scheduleSave();
    host._bus.emit('layout', { reason: 'timezone' });
  }));

  // ── ranges ───────────────────────────────────────────────────────────
  let applied: { id: string; interval: string } | null = null;
  let applying = false;
  /** Bumped by every range and every change that ends one, so a placement waiting on a load knows it lost. */
  let request = 0;
  const current = (): WidgetRange | null => {
    const a = applied;
    return a === null || a.interval !== host._interval ? null : ranges.find(r => r.id === a.id) ?? null;
  };

  /**
   * A range ends at the latest bar, so one wider than the plot gives up its
   * oldest bars, not its newest: the placement keeps a range's start in view,
   * which here would push the last price off the chart.
   */
  const keepLatest = (result: DateNavigationResult): DateNavigationResult => {
    const bars = chart.primaryBars();
    const lastBar = bars[bars.length - 1];
    if (lastBar === undefined) return result;
    const last = chart.dataLayer.timeToIndex(lastBar.time) ?? bars.length - 1;
    const view = chart.getVisibleLogicalRange();
    const from = last + 0.5 - (view.to - view.from);
    chart.setVisibleLogicalRange({ from, to: last + 0.5 });
    return { ...result, from: chart.dataLayer.indexToTime(Math.ceil(from + 0.5)) ?? result.from, to: lastBar.time };
  };

  /** Place `range` on the bars once the load in flight has landed. */
  const place = async (range: WidgetRange, mine: number): Promise<DateNavigationResult> => {
    for (let i = 0; i < 4 && host._loading !== null; i++) {
      try { await host._loading; } catch { /* a failed load leaves no bars, reported below */ }
      if (mine !== request || host._destroyed) return { status: 'cancelled' };
    }
    if (mine !== request || host._destroyed) return { status: 'cancelled' };
    const bars = chart.primaryBars();
    if (bars.length === 0) return { status: 'no-data' };
    // All history is asked of the source rather than read off the bars: on
    // the interval already in force no load came first, and the bars hold
    // only an ordinary lookback.
    const all = range.unit === 'all';
    // bars is not empty: checked above.
    const window = rangeWindow(range, { end: bars[bars.length - 1]!.time, zone: chart.timezone(), calendar: calendar(), bars: all ? undefined : bars });
    let result = await host.goTo(window);
    if (mine !== request || host._destroyed) return result;
    // For All, history that ends is the range itself, not a shortfall to report.
    if (all && result.status === 'partial' && (result.history === 'exhausted' || result.history === 'empty')) {
      result = { status: result.clipped === true ? 'partial' : 'placed', from: result.from, to: result.to, ...(result.clipped === true ? { clipped: true } : {}) };
    }
    return result.status === 'partial' && result.clipped === true ? keepLatest(result) : result;
  };

  const setRange = async (id: string): Promise<DateNavigationResult> => {
    const range = ranges.find(r => r.id === id);
    if (range === undefined || host._destroyed) return { status: 'invalid' };
    const mine = ++request;
    const interval = rangeInterval(range, host._intervals);
    applied = { id, interval };
    applying = true;
    try { host.setInterval(interval); }
    catch (error) { applied = null; return { status: 'error', error: asError(error) }; }
    finally { applying = false; }
    return place(range, mine);
  };

  host._cleanups.push(host._bus.on('interval', () => {
    if (applying) return;
    applied = null;
    request++;
  }));
  // The same span on the next instrument, or on the source's other series.
  const again = (): void => {
    const range = current();
    if (range !== null) void place(range, ++request);
  };
  host._cleanups.push(host._bus.on('symbol', again));
  host._cleanups.push(host._bus.on('variant', again));

  const fetchWindow = (fallback: WidgetRangeWindow, nowSec: number): WidgetRangeWindow => {
    const range = current();
    if (range === null) return fallback;
    const w = rangeWindow(range, { end: nowSec, zone: chart.timezone(), calendar: calendar() });
    // Never less history than an ordinary load: a range over a quiet morning
    // would otherwise leave older pages a window of minutes wide to fill.
    return { from: Math.min(w.from, fallback.from), to: fallback.to };
  };

  // ── the bar ──────────────────────────────────────────────────────────
  let controls: BottombarControls | undefined;
  if (opts.bottombar !== false) {
    const el = h(host.context.document, 'div', 'oac-bottombar');
    // Without a top bar the phone layout has no More sheet to take the bar's
    // controls, so the bar stays there instead of hiding.
    if (opts.topbar === false) el.classList.add('is-kept');
    host.root.insertBefore(el, before);
    host.root.classList.add('has-bottombar');
    const bar = mountBottombar(host.context, el, {
      target: () => ({ chart, interval: () => host._interval, range: () => current()?.id ?? null, setRange }),
      ranges,
      onGoTo: anchor => host._openGoTo(anchor),
      now: () => (opts.now ?? Date.now)(),
    });
    controls = bar.controls;
    host._cleanups.push(() => {
      bar.destroy();
      el.remove();
      host.root.classList.remove('has-bottombar');
    });
  }

  return { setRange, range: () => current()?.id ?? null, fetchWindow, controls };
}
