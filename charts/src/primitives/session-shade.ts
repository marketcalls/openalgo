/**
 * Shades the hours outside the regular session: pre-open, post-close and
 * extended hours, read from a session calendar.
 *
 * On an extended-hours chart the bars before the opening and after the close
 * look exactly like the session's own, and a move made on thin pre-open volume
 * is easy to read as one the whole market made. A faint wash behind those bars
 * says which is which without a legend.
 *
 * The phases come from the calendar as spans, not from a question per bar: the
 * spans of the visible time are laid out once and kept while a pan stays inside
 * them, and each span becomes one rect found by a binary search over the bar
 * times. The cost per frame follows the sessions in view, not the bars. With a
 * gapless axis a span shows only where bars fall in it, so a regular-hours feed
 * shades nothing, and daily or longer bars, which have no part of the day to
 * show, are skipped.
 */
import type { Chart } from '../core/chart';
import type { DataLayer } from '../model/data-layer';
import type { SessionPhase, SessionPhaseSource, SessionPhaseSpan } from '../feed/market-status';
import { luminance, parseColor, withAlpha } from '../render/pill';
import { darkTheme, lightTheme } from '../theme';
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';

export interface SessionShadeOptions {
  /**
   * The hours to shade by. Absent or null, the chart's own calendar is read
   * each frame (`chart.setSessionCalendar`, `Instrument.applyTo`), so the
   * shade follows the instrument and clears when the chart drops its hours.
   */
  calendar?: SessionPhaseSource | null;
  /** Wash behind pre-open bars; null leaves them unshaded. Default: a faint tint of the theme's line colour. */
  preColor?: string | null;
  /** Wash behind post-close bars; null leaves them unshaded. Default: a faint amber. */
  postColor?: string | null;
  /** Wash behind extended-hours bars; null leaves them unshaded. Default: a faint tint of the theme's axis text. */
  extendedColor?: string | null;
  /** Draw at all. Default true. */
  visible?: boolean;
}

/** What `attachSessionShading` returns: the shade's controls, and its removal. */
export interface SessionShading {
  /** Change some options; the rest keep their values. */
  setOptions(patch: SessionShadeOptions): void;
  /** The options in force. */
  options(): SessionShadeOptions;
  /** Take the shade off the chart. Calling it again does nothing. */
  destroy(): void;
}

const DAY = 86400;
/**
 * Bars closer than this are intraday. A daily bar is at least 23 hours after
 * the one before, across a spring-forward night, and a 12-hour bar still has
 * a morning and an evening to tell apart.
 */
const INTRADAY = 20 * 3600;
/** Past this much visible time, bars are too dense for a per-bar wash to mean anything. */
const MAX_VISIBLE = 90 * DAY;

/** Index of the first bar at or after `time` in `[lo, hi]`, or `hi + 1` when none is. */
function firstAtOrAfter(data: DataLayer, time: number, lo: number, hi: number): number {
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (data.indexToTime(mid)! < time) lo = mid + 1;
    else hi = mid - 1;
  }
  return lo;
}

/** Whether the bars from `lo` on are intraday, by the lower median of a few gaps. */
function intraday(data: DataLayer, lo: number, hi: number): boolean {
  const gaps: number[] = [];
  for (let i = Math.max(1, lo), end = Math.max(i, Math.min(hi, lo + 15)); i <= end; i++) {
    gaps.push(data.indexToTime(i)! - data.indexToTime(i - 1)!);
  }
  gaps.sort((a, b) => a - b);
  // The loop runs at least once: its end is never below its start.
  return gaps[(gaps.length - 1) >> 1]! < INTRADAY;
}

export class SessionShade implements IPrimitive {
  private _opts: SessionShadeOptions;
  private _host: PrimitiveHost | null = null;
  /** The spans last laid out, the source they came from and the time they cover. */
  private _cache: { source: SessionPhaseSource; from: number; to: number; spans: readonly SessionPhaseSpan[] } | null = null;

  public constructor(options: SessionShadeOptions = {}) {
    this._opts = { ...options };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  /** Behind the series, like any background: the candles stay crisp over it. */
  public zOrder(): ZOrder { return 'bottom'; }
  /** A wash has no price and never widens the range. */
  public autoscaleInfo(): null { return null; }
  /** Never hit, so every click reaches the bars and drawings under it. */
  public hitTest(): null { return null; }
  public hitBounds(): null { return null; }

  public options(): SessionShadeOptions { return { ...this._opts }; }

  public setOptions(patch: SessionShadeOptions): void {
    this._opts = { ...this._opts, ...patch };
    // A host passing the same source object after changing its hours means
    // the new hours, so nothing laid out before is trusted.
    this._cache = null;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts, data = rc.dataLayer, n = data.length;
    if (o.visible === false || n < 2) return;
    const own = data.sessionCalendar;
    const source = o.calendar ?? (own?.phaseSpans ? own as SessionPhaseSource : null);
    if (source === null) return;
    const range = rc.timeScale.visibleRange();
    const lo = Math.max(0, Math.floor(range.from)), hi = Math.min(n - 1, Math.ceil(range.to));
    if (lo > hi || !intraday(data, lo, hi)) return;
    const from = data.indexToTime(lo)!, to = data.indexToTime(hi)! + 1;
    if (to - from > MAX_VISIBLE) return;

    const spans = this._spans(source, from, to);
    // A light background shows a tint more strongly than a dark one does. A
    // theme colour the tint cannot read (a named or hsl() colour) would come
    // back opaque and cover the whole column, so the built-in theme's own
    // colour stands in for it.
    const [alpha, grey, builtIn] = luminance(rc.theme.background) < 0.5 ? [0.1, 0.13, darkTheme] as const : [0.07, 0.1, lightTheme] as const;
    const tint = (key: 'lineColor' | 'axisText', a: number): string => withAlpha(parseColor(rc.theme[key]) ? rc.theme[key] : builtIn[key], a);
    const colors: Partial<Record<SessionPhase, string | null>> = {
      pre: o.preColor !== undefined ? o.preColor : tint('lineColor', alpha),
      post: o.postColor !== undefined ? o.postColor : withAlpha('#f59e0b', alpha),
      extended: o.extendedColor !== undefined ? o.extendedColor : tint('axisText', grey),
    };
    const d = rc.dpr, w = rc.plotWidth * d, h = rc.plotHeight * d;
    // Edges on bar midpoints, as the indicator background has them, so two
    // spans meet exactly. The pane clips to the plot anyway; the clamp keeps a
    // run reaching far off screen from asking for a rect millions of pixels wide.
    const edge = (i: number): number => Math.min(w, Math.max(0, Math.round(rc.timeScale.indexToX(i) * d)));
    ctx.save();
    for (const span of spans) {
      const color = colors[span.phase];
      if (!color || span.end <= from || span.start >= to) continue;
      const a = firstAtOrAfter(data, span.start, lo, hi), b = firstAtOrAfter(data, span.end, lo, hi) - 1;
      if (a > b) continue;
      const x = edge(a - 0.5);
      ctx.fillStyle = color;
      ctx.fillRect(x, 0, edge(b + 0.5) - x, h);
    }
    ctx.restore();
  }

  /**
   * The spans over `[from, to)`, laid out again only when the view leaves the
   * time the last answer covered. That answer reaches a view's width, and at
   * least a day, past each side, so a pan reuses it.
   */
  private _spans(source: SessionPhaseSource, from: number, to: number): readonly SessionPhaseSpan[] {
    const c = this._cache;
    if (c && c.source === source && c.from <= from && c.to >= to) return c.spans;
    const pad = Math.max(DAY, to - from);
    let spans: readonly SessionPhaseSpan[];
    // A calendar that cannot answer, such as a window a daylight-saving
    // change removes, shades nothing rather than stopping the frame.
    try { spans = source.phaseSpans(from - pad, to + pad); } catch { spans = []; }
    this._cache = { source, from: from - pad, to: to + pad, spans };
    return spans;
  }
}

/** The shading each chart carries, so attaching twice never stacks two washes. */
const attachedTo = new WeakMap<Chart, { shading: SessionShading; shade: SessionShade }>();

/**
 * Shade a chart's pre-open, post-close and extended hours. Nothing is shaded
 * until a host calls this. The shade sits behind the series in the price pane,
 * follows that pane when it moves, and fills the pane maximized over it. A
 * chart carries one: a second call returns the same shading with the new
 * options merged in.
 */
export function attachSessionShading(chart: Chart, options: SessionShadeOptions = {}): SessionShading {
  const existing = attachedTo.get(chart);
  if (existing) {
    // A host that took the shade off with `removePrimitive` still holds this
    // handle, and asking again means it wants the shading back, not a handle
    // that shades nothing.
    if (!chart.isDestroyed && !chart.panes().some(pane => pane.primitives().includes(existing.shade))) {
      chart.addPrimitive(existing.shade, { anchor: 'primary-pane' });
    }
    existing.shading.setOptions(options);
    return existing.shading;
  }
  const shade = new SessionShade(options);
  chart.addPrimitive(shade, { anchor: 'primary-pane' });
  const shading: SessionShading = {
    setOptions: patch => shade.setOptions(patch),
    options: () => shade.options(),
    destroy: () => {
      if (attachedTo.get(chart)?.shading !== shading) return;
      attachedTo.delete(chart);
      if (!chart.isDestroyed) chart.removePrimitive(shade);
    },
  };
  attachedTo.set(chart, { shading, shade });
  return shading;
}
