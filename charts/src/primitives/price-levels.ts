/**
 * Price-level family, built on the primitive API (ARCHITECTURE.md §8). A price
 * level is a horizontal line at a meaningful price **and** a matching tag on the
 * price axis, and the two halves toggle independently.
 *
 * WHY one options group per level instead of a list of lines and a list of
 * labels: the two halves of a level are one idea. Reference terminals split them
 * across separate menus, so a level's line and its label drift apart and a user
 * ends up with an axis tag for a line that is not drawn. Here `line` and `label`
 * are two flags on the same group, which cannot come apart.
 *
 * WHY the session comes from the bar gaps and never from a calendar midnight:
 * the overnight break is the only thing in the data that says where a trading
 * day ends, and a fixed midnight lands mid-session for half the world's
 * exchanges. `sessionStartFlags` already reads it back (and falls back to the
 * calendar only when the series shows no readable break, which is the right
 * answer for daily bars). That bug was fixed in 1.2.0; this file does not
 * reintroduce it.
 *
 * WHY levels with no data draw nothing rather than drawing at zero: extended
 * hours need a phase the historical feed does not carry, and bid/ask need a live
 * quote it does not carry either. A missing value is `null`, never `0`, so the
 * level stays inert and a host can render its control disabled with the state
 * still visible (`available(kind)`), which is what the UI standard asks for.
 *
 * WHY there is no `autoscaleInfo`: a previous close a gap away from the session
 * in view would stretch the range and flatten the bars the user is actually
 * looking at. A reference level that scrolls off the top is the lesser harm, and
 * it is what the last-price line already does.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';
import type { Bar } from '../model/bar';
import type { ChartTheme } from '../theme';
import type { SeriesStyle } from '../render/series-style';
import { contrastText } from '../render/pill';
import { dashPattern, type CanvasLineStyle } from '../render/grid';
import { drawAxisTag } from './axis-tag';
import { sessionStartFlags, DEFAULT_TIMEZONE } from '../feed/time';

export type PriceLevelKind =
  | 'previousClose'
  | 'sessionHigh'
  | 'sessionLow'
  | 'lastPrice'
  | 'preMarketOpen'
  | 'preMarketClose'
  | 'postMarketOpen'
  | 'postMarketClose'
  | 'bid'
  | 'ask';

/** Every level, in the order a settings panel should list them. */
export const PRICE_LEVEL_KINDS: readonly PriceLevelKind[] = [
  'previousClose', 'sessionHigh', 'sessionLow', 'lastPrice',
  'preMarketOpen', 'preMarketClose', 'postMarketOpen', 'postMarketClose',
  'bid', 'ask',
];

/** One level's appearance. `line` and `label` are the two independent toggles. */
export interface PriceLevelStyle {
  /** Draw the horizontal line across the plot. */
  line: boolean;
  /** Draw the matching tag on the price axis. */
  label: boolean;
  /** Line and tag colour. Unset falls through to the theme (see `defaultColor`). */
  color?: string;
  /** Line width in media px. Default 1. */
  lineWidth?: number;
  /** Line dash. Default per kind. */
  lineStyle?: CanvasLineStyle;
  /** Axis tag text. Default: the price, formatted by the scale. */
  text?: string;
  /**
   * Fraction of the plot width the line spans, measured from the price axis.
   * 1 = full width (default), the same meaning `PriceLine` gives it.
   */
  extentFromRight?: number;
}

/**
 * Which part of the trading day a bar belongs to. Only a host knows this: the
 * OHLC feed carries no phase, and guessing it from the clock would be wrong for
 * every exchange but the one guessed for.
 */
export type MarketPhase = 'pre' | 'regular' | 'post';

/** Classify a bar into a market phase; null/undefined means "unknown". */
export type MarketPhaseFn = (bar: Bar) => MarketPhase | null | undefined;

/** A live top-of-book quote. Either side may be absent. */
export interface PriceLevelQuote {
  bid?: number | null;
  ask?: number | null;
}

export interface PriceLevelsOptions {
  /** Per-level overrides, merged over the defaults. */
  levels?: Partial<Record<PriceLevelKind, Partial<PriceLevelStyle>>>;
  /** IANA zone for the calendar fallback when the bars show no session break. */
  timezone?: string;
  /** Extended-hours classifier. Absent leaves the four extended levels inert. */
  marketPhase?: MarketPhaseFn | null;
  /** Live quote, as a value or a callback read each frame. Absent leaves bid/ask inert. */
  quote?: PriceLevelQuote | (() => PriceLevelQuote | null | undefined) | null;
}

/** Each level's price for the current context, or null when it has no data. */
export type PriceLevelValues = Record<PriceLevelKind, number | null>;

function emptyValues(): PriceLevelValues {
  return {
    previousClose: null, sessionHigh: null, sessionLow: null, lastPrice: null,
    preMarketOpen: null, preMarketClose: null, postMarketOpen: null, postMarketClose: null,
    bid: null, ask: null,
  };
}

/**
 * Defaults. Only `previousClose` is on: it is the one level an intraday chart is
 * routinely read against, and it sits away from the current price rather than on
 * top of it. Session high and low were on too, and the three together drew a
 * cluster of dashed lines within a few points of the last price that read as
 * clutter rather than as information. A level a host has not asked for should
 * not be on the chart, so the other two are opt-in.
 *
 * `lastPrice` is off because the core already draws it from
 * `SeriesStyle.priceLineVisible` / `lastValueVisible`, and two owners would
 * double-draw it (see {@link lastPriceLevelFromSeriesStyle}). The extended-hours
 * and quote levels are off because they need data a host has to supply.
 */
const DEFAULT_LEVELS: Readonly<Record<PriceLevelKind, PriceLevelStyle>> = {
  previousClose: { line: true, label: true, lineStyle: 'dashed' },
  sessionHigh: { line: false, label: false, lineStyle: 'dashed' },
  sessionLow: { line: false, label: false, lineStyle: 'dashed' },
  lastPrice: { line: false, label: false, lineStyle: 'dashed' },
  preMarketOpen: { line: false, label: false, lineStyle: 'dotted' },
  preMarketClose: { line: false, label: false, lineStyle: 'dotted' },
  postMarketOpen: { line: false, label: false, lineStyle: 'dotted' },
  postMarketClose: { line: false, label: false, lineStyle: 'dotted' },
  bid: { line: false, label: false, lineStyle: 'dotted' },
  ask: { line: false, label: false, lineStyle: 'dotted' },
};

/** Tag/box height in media px, matching the last-price tag on the axis. */
const TAG_H = 16;

function finite(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * Session start indices for a bar array, cached against the array identity plus
 * a cheap stamp of its shape.
 *
 * The read path runs every frame over full history, and reading the sessions
 * back costs a sort of the gaps. Session boundaries cannot move under an
 * intra-bar tick (the last bar's OHLC changes, its time does not), so length
 * plus the first and last time is a sufficient stamp. A WeakMap and not a single
 * slot: two charts drawing alternately would thrash a one-entry cache and pay
 * the full cost on every frame of both.
 */
const boundaryCache = new WeakMap<readonly Bar[], {
  len: number; first: number; last: number; zone: string; starts: number[];
}>();

function sessionStarts(bars: readonly Bar[], zone: string): number[] {
  const n = bars.length;
  if (n === 0) return [];
  const first = bars[0]!.time;
  const last = bars[n - 1]!.time;
  const hit = boundaryCache.get(bars);
  if (hit !== undefined && hit.len === n && hit.first === first && hit.last === last && hit.zone === zone) {
    return hit.starts;
  }
  const times = new Array<number>(n);
  for (let i = 0; i < n; i++) times[i] = bars[i]!.time;
  const flags = sessionStartFlags(times, zone);
  // Bar 0 opens the first session in view even though it carries no flag: the
  // flag marks a break, and there is no bar before it to break from.
  const starts = [0];
  for (let i = 1; i < n; i++) if (flags[i]) starts.push(i);
  boundaryCache.set(bars, { len: n, first, last, zone, starts });
  return starts;
}

/** Last bar at or before `time`; -1 when the whole series is later than it. Needs one bar at least. */
function anchorIndex(bars: readonly Bar[], time: number | undefined): number {
  const n = bars.length;
  if (time === undefined || !Number.isFinite(time)) return n - 1;
  if (time >= bars[n - 1]!.time) return n - 1;
  if (time < bars[0]!.time) return -1;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (bars[mid]!.time <= time) lo = mid; // mid stays inside [lo, hi]
    else hi = mid - 1;
  }
  return lo;
}

/** Index into `starts` of the session containing bar `bar`. */
function sessionOf(starts: readonly number[], bar: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid]! <= bar) lo = mid; // mid stays inside [lo, hi]
    else hi = mid - 1;
  }
  return lo;
}

export interface PriceLevelInput {
  bars: readonly Bar[];
  /**
   * UTC seconds at the right edge of the viewport: the session containing it is
   * "the session in view", and the level before it is its previous session.
   * Default (and anything past the last bar) anchors on the last bar.
   */
  anchorTime?: number;
  timezone?: string;
  marketPhase?: MarketPhaseFn | null;
  quote?: PriceLevelQuote | null;
}

/**
 * Every level's price for one viewport, or null where the data cannot say.
 *
 * Pure, so the levels are testable without a canvas, and callable by a host that
 * wants the numbers for a readout rather than for a line.
 */
export function computePriceLevels(input: PriceLevelInput): PriceLevelValues {
  const out = emptyValues();

  // Bid and ask come from the quote, not from the bars: they are quoted even
  // when the chart holds no history at all.
  const quote = input.quote;
  if (quote !== null && quote !== undefined) {
    out.bid = finite(quote.bid);
    out.ask = finite(quote.ask);
  }

  const bars = input.bars;
  const n = bars.length;
  if (n === 0) return out;

  // The last trade is not a function of the viewport: scrolling back through
  // history does not change what the instrument last traded at.
  out.lastPrice = finite(bars[n - 1]!.close);

  const anchor = anchorIndex(bars, input.anchorTime);
  if (anchor < 0) return out; // viewport entirely to the left of the data

  const starts = sessionStarts(bars, input.timezone ?? DEFAULT_TIMEZONE);
  // `starts` holds bar 0 at least, and `si` indexes it; the loops below stay inside
  // [from, to], which lies inside the bars.
  const si = sessionOf(starts, anchor);
  const from = starts[si]!;
  const to = si + 1 < starts.length ? starts[si + 1]! - 1 : n - 1;

  let high = -Infinity;
  let low = Infinity;
  for (let i = from; i <= to; i++) {
    const bar = bars[i]!;
    // Whitespace normalises to a NaN bar, and NaN loses every comparison
    // silently, so extremes are taken over finite values only.
    if (Number.isFinite(bar.high) && bar.high > high) high = bar.high;
    if (Number.isFinite(bar.low) && bar.low < low) low = bar.low;
  }
  if (high > -Infinity) out.sessionHigh = high;
  if (low < Infinity) out.sessionLow = low;

  // The previous session's *last traded* close: walk back from its final bar so
  // a whitespace tail (a halted or untraded closing minute) does not blank the
  // level. The walk stops at that session's open and never crosses further back.
  if (si > 0) {
    const prevFrom = starts[si - 1]!;
    for (let i = from - 1; i >= prevFrom; i--) {
      const close = finite(bars[i]!.close);
      if (close !== null) {
        out.previousClose = close;
        break;
      }
    }
  }

  const phase = input.marketPhase;
  if (phase !== null && phase !== undefined) {
    for (let i = from; i <= to; i++) {
      const bar = bars[i]!;
      const p = phase(bar);
      if (p === 'pre') {
        if (out.preMarketOpen === null) out.preMarketOpen = finite(bar.open);
        const close = finite(bar.close);
        if (close !== null) out.preMarketClose = close;
      } else if (p === 'post') {
        if (out.postMarketOpen === null) out.postMarketOpen = finite(bar.open);
        const close = finite(bar.close);
        if (close !== null) out.postMarketClose = close;
      }
    }
  }

  return out;
}

/**
 * Theme colour for a level with no explicit one. Session extremes borrow the
 * up/down pair, the quote levels borrow buy/sell, and the last price follows the
 * tick direction exactly as the core's own last-price tag does, so a host that
 * moves that level into this family sees no change.
 */
function defaultColor(kind: PriceLevelKind, theme: ChartTheme, up: boolean): string {
  switch (kind) {
    case 'sessionHigh': return theme.upColor;
    case 'sessionLow': return theme.downColor;
    case 'bid': return theme.buy;
    case 'ask': return theme.sell;
    case 'lastPrice': return up ? theme.lastPriceUp : theme.lastPriceDown;
    default: return theme.crosshair;
  }
}

/**
 * The last-price level as the series style already expresses it.
 *
 * That level is not duplicated here: `priceLineVisible` and `lastValueVisible`
 * are exactly this family's `line` and `label` under older names, and the pane
 * draws them. These two functions are the translation, so a host can present the
 * last price in the same shape as every other level and write the answer back to
 * the series it belongs to.
 */
export function lastPriceLevelFromSeriesStyle(
  style: Pick<SeriesStyle, 'priceLineVisible' | 'lastValueVisible'>,
): Pick<PriceLevelStyle, 'line' | 'label'> {
  return { line: style.priceLineVisible !== false, label: style.lastValueVisible !== false };
}

/** The series-style patch a last-price level group means. */
export function seriesStyleForLastPriceLevel(
  level: Pick<PriceLevelStyle, 'line' | 'label'>,
): Pick<SeriesStyle, 'priceLineVisible' | 'lastValueVisible'> {
  return { priceLineVisible: level.line, lastValueVisible: level.label };
}

export class PriceLevels implements IPrimitive {
  private readonly _levels: Record<PriceLevelKind, PriceLevelStyle>;
  private _timezone: string;
  private _phase: MarketPhaseFn | null;
  private _quote: PriceLevelQuote | (() => PriceLevelQuote | null | undefined) | null;
  private _values: PriceLevelValues = emptyValues();
  private _host: PrimitiveHost | null = null;

  public constructor(options: PriceLevelsOptions = {}) {
    this._levels = { ...DEFAULT_LEVELS };
    for (const kind of PRICE_LEVEL_KINDS) {
      const patch = options.levels?.[kind];
      if (patch !== undefined) this._levels[kind] = { ...DEFAULT_LEVELS[kind], ...patch };
    }
    this._timezone = options.timezone ?? DEFAULT_TIMEZONE;
    this._phase = options.marketPhase ?? null;
    this._quote = options.quote ?? null;
  }

  public attached(host: PrimitiveHost): void {
    this._host = host;
  }

  public detached(): void {
    this._host = null;
  }

  public zOrder(): ZOrder {
    return 'normal';
  }

  /** One level's resolved style, for a host rendering its controls. */
  public level(kind: PriceLevelKind): Readonly<PriceLevelStyle> {
    return this._levels[kind];
  }

  /** Patch one level. The two toggles move independently: neither implies the other. */
  public setLevel(kind: PriceLevelKind, patch: Partial<PriceLevelStyle>): void {
    this._levels[kind] = { ...this._levels[kind], ...patch };
    this._host?.requestUpdate();
  }

  /** Patch several levels, plus the shared options, in one repaint. */
  public setOptions(options: PriceLevelsOptions): void {
    for (const kind of PRICE_LEVEL_KINDS) {
      const patch = options.levels?.[kind];
      if (patch !== undefined) this._levels[kind] = { ...this._levels[kind], ...patch };
    }
    if (options.timezone !== undefined) this._timezone = options.timezone;
    if (options.marketPhase !== undefined) this._phase = options.marketPhase;
    if (options.quote !== undefined) this._quote = options.quote;
    this._host?.requestUpdate();
  }

  /** Feed a live top-of-book quote; null clears it and the bid/ask levels go inert. */
  public setQuote(quote: PriceLevelQuote | null): void {
    this._quote = quote;
    this._host?.requestUpdate();
  }

  /**
   * Level prices as of the last frame. Values depend on the viewport, so they
   * are computed while drawing; before the first frame every level reads null.
   * A host that needs them without a chart calls {@link computePriceLevels}.
   */
  public values(): Readonly<PriceLevelValues> {
    return this._values;
  }

  /**
   * Whether a level has data in the current context. False is the signal to
   * render its control disabled rather than to hide it: "no previous session
   * yet" is information, an absent checkbox is not.
   */
  public available(kind: PriceLevelKind): boolean {
    return this._values[kind] !== null;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const bars = rc.bars?.() ?? [];
    // The right edge of the viewport, in time, is what picks the session in
    // view. `indexToTimeFloat` extrapolates past the last bar, so the usual
    // right-offset gap resolves to the newest session rather than to nothing.
    const anchorTime = rc.dataLayer.indexToTimeFloat(rc.timeScale.visibleRange().to);
    this._values = computePriceLevels({
      bars,
      anchorTime,
      timezone: this._timezone,
      marketPhase: this._phase,
      quote: typeof this._quote === 'function' ? this._quote() ?? null : this._quote,
    });

    const dpr = rc.dpr;
    const xEnd = Math.round(rc.plotWidth * dpr);
    const maxY = rc.plotHeight * dpr;
    const last = bars.length > 0 ? bars[bars.length - 1]! : null;
    const up = last !== null && last.close >= last.open;

    ctx.save();
    ctx.font = `500 ${11 * dpr}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    for (const kind of PRICE_LEVEL_KINDS) {
      const style = this._levels[kind];
      if (!style.line && !style.label) continue;
      const price = this._values[kind];
      // No data: nothing is drawn. Not a line at zero, which is what a numeric
      // fallback would put across the middle of the plot.
      if (price === null) continue;
      const y = Math.round(rc.priceScale.priceToY(price) * dpr) + 0.5;
      if (y < 0 || y > maxY) continue;
      const color = style.color ?? defaultColor(kind, rc.theme, up);

      if (style.line) {
        const extent = Math.max(0, Math.min(1, style.extentFromRight ?? 1));
        const xStart = Math.round(rc.plotWidth * (1 - extent) * dpr);
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, Math.round((style.lineWidth ?? 1) * dpr));
        ctx.setLineDash(dashPattern(style.lineStyle, dpr));
        ctx.beginPath();
        ctx.moveTo(xStart, y);
        ctx.lineTo(xEnd, y);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (style.label && rc.priceAxisSide !== 'hidden' && rc.priceAxisWidth > 0) {
        drawAxisTag(ctx, rc, y, style.text ?? rc.priceScale.format(price), color, contrastText(color), TAG_H * dpr, true);
      }
    }
    ctx.restore();
  }
}
