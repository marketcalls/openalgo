/**
 * Candlestick renderer (ARCHITECTURE.md §6). Pure geometry helpers are split
 * out for unit testing; drawing happens in the bitmap (device-px) scope.
 */
import type { Bar } from '../model/bar';
import type { SeriesStyle } from './series-style';
import type { ChartTheme } from '../theme';
import type { LooseOptional } from '../helpers/types';

export interface CandleStyle {
  upColor: string;
  downColor: string;
  borderUpColor: string;
  borderDownColor: string;
  wickUpColor: string;
  wickDownColor: string;
  borderVisible: boolean;
  wickVisible: boolean;
  /**
   * Paint the body at all. Off leaves the candle as its outline and wick, which
   * is what a settings dialog's "Body" switch means.
   *
   * Distinct from `hollow`, which empties only the UP candles and is the
   * hollow-candle chart type. This empties both, and it is the one switch here
   * that can legitimately leave nothing drawn: with borders off as well, a
   * candle is reduced to its wick. That is two deliberate switches rather than
   * an accident, so it is honoured rather than second-guessed.
   */
  bodyVisible?: boolean;
  /** Draw up-candle bodies as outlines only (hollow candles). */
  hollow?: boolean;
  /**
   * "Color bars based on previous close": a bar is up when it closed above the
   * bar before it rather than above its own open. Body, border and wick all
   * follow the same verdict, so the candle never disagrees with itself.
   */
  colorByPreviousClose?: boolean;
  /** Per-bar body-width scale 0..1 (volume candles); 1 = full width. */
  widthScale?: (bar: Bar) => number;
}

export const DEFAULT_CANDLE_STYLE: CandleStyle = {
  upColor: '#26a69a',
  downColor: '#ef5350',
  borderUpColor: '#26a69a',
  borderDownColor: '#ef5350',
  wickUpColor: '#26a69a',
  wickDownColor: '#ef5350',
  borderVisible: true,
  wickVisible: true,
};

/**
 * A candle style from a series style: the style over the theme, plus the
 * type's own switches (`hollow`, `widthScale`). The 2D registry and the GPU
 * backend both resolve through this, so a new option is threaded once.
 */
export function resolveCandleStyle(s: SeriesStyle, theme: ChartTheme, extra: Partial<CandleStyle> = {}): CandleStyle {
  return {
    ...DEFAULT_CANDLE_STYLE,
    upColor: s.upColor ?? theme.upColor,
    downColor: s.downColor ?? theme.downColor,
    borderUpColor: s.borderUpColor ?? theme.upColor,
    borderDownColor: s.borderDownColor ?? theme.downColor,
    wickUpColor: s.wickUpColor ?? theme.wickUpColor,
    wickDownColor: s.wickDownColor ?? theme.wickDownColor,
    borderVisible: s.borderVisible ?? DEFAULT_CANDLE_STYLE.borderVisible,
    bodyVisible: s.bodyVisible ?? true,
    wickVisible: s.wickVisible ?? DEFAULT_CANDLE_STYLE.wickVisible,
    // Unset stays unset: the renderer reads only `=== true`.
    colorByPreviousClose: s.colorByPreviousClose,
    ...extra,
  } satisfies LooseOptional<CandleStyle> as CandleStyle;
}

/**
 * Pure: optimal candle body width in device px for a given bar spacing. Leaves
 * a ~1px gap between candles, keeps a minimum of 1px, and matches odd/even
 * parity with the wick so the body stays symmetric about the (1px) wick.
 */
export function optimalBarWidth(barSpacing: number, dpr: number): number {
  const raw = Math.floor(barSpacing * dpr * 0.8);
  let w = Math.max(1, raw);
  if (w >= 2) {
    const wick = Math.max(1, Math.floor(dpr));
    if (w % 2 !== wick % 2) w -= 1;
  }
  return Math.max(1, w);
}

/**
 * Level-of-detail tier for one candle.
 *
 * - `full`: the body (and any border) is distinguishable from the wick, so all
 *   of it is drawn.
 * - `wick`: the body would repaint exactly the pixels the wick already covered,
 *   so it is skipped. This is not an approximation: `optimalBarWidth` matches
 *   the body's odd/even parity to the wick's, which collapses the two to the
 *   same width and the same `x` once bars get tight, and the wick's high-low
 *   span always contains the body's open-close span. Same rect, same colour,
 *   twice the work.
 */
export type CandleTier = 'full' | 'wick';

/**
 * Pure: whether a candle's body still shows once it is this narrow.
 *
 * Only returns `wick` when the body is provably invisible under the wick, so a
 * chart drawn at either tier is pixel-identical. Anything that could make the
 * body read differently - a hollow candle's outline, a border wide enough to
 * survive, a body colour that differs from the wick's, a hidden wick with
 * nothing to hide behind - stays `full`.
 *
 * `bodyW` is the per-bar width, so a volume candle whose `widthScale` has
 * narrowed it is judged on what it will actually draw.
 */
export function candleTier(bodyW: number, wickW: number, style: CandleStyle): CandleTier {
  if (!style.wickVisible) return 'full';       // no wick to hide behind
  if (style.hollow === true) return 'full';    // the outline IS the candle
  if (style.bodyVisible === false) return 'full';
  if (bodyW > wickW) return 'full';            // wider than the wick: visible
  // Below 3px `drawCandles` already drops the border; at or above it the
  // outline is its own mark and the body cannot be skipped under it.
  if (style.borderVisible && bodyW >= 3) return 'full';
  // Equal width only hides the body if it is painted the same colour. A
  // per-bar `bar.color` override sets body and wick together, so it can only
  // make them agree, never disagree.
  if (style.upColor !== style.wickUpColor) return 'full';
  if (style.downColor !== style.wickDownColor) return 'full';
  return 'wick';
}

/** Where one candle lands, in device px. Every field is an integer. */
export interface CandleGeometry {
  /** Bar centre. */
  cx: number;
  /** Left edge of the body. */
  bodyX: number;
  /** Body width after any per-bar scale, never below 1. */
  bodyW: number;
  /** Left edge of the wick. */
  wickX: number;
  /** Wick width: 1 device px per whole unit of `dpr`. */
  wickW: number;
}

/**
 * Pure: the device-pixel rectangle geometry of one candle. This is the single
 * source of the snapping and parity rules, so a second backend rasterising
 * candles with its own primitives lands on the same pixels as `drawCandles`.
 *
 * `widthScale` is the per-bar body scale a volume candle applies (1 = the
 * full `optimalBarWidth`). It is clamped to 0.05..1: a zero-volume bar still
 * has to show a sliver of body, and nothing may grow past the gap.
 */
export function candleGeometry(x: number, barSpacing: number, dpr: number, widthScale = 1): CandleGeometry {
  const fullW = optimalBarWidth(barSpacing, dpr);
  const wickW = Math.max(1, Math.floor(dpr));
  const cx = Math.round(x * dpr);
  const bodyW = scaledBodyWidth(fullW, widthScale);
  return {
    cx,
    bodyX: cx - Math.floor(bodyW / 2),
    bodyW,
    wickX: cx - Math.floor(wickW / 2),
    wickW,
  };
}

/** A body `fullW` wide scaled by `widthScale`, clamped the way `candleGeometry` documents. */
function scaledBodyWidth(fullW: number, widthScale: number): number {
  const scale = Math.max(0.05, Math.min(1, widthScale));
  return scale === 1 ? fullW : Math.max(1, Math.round(fullW * scale));
}

export interface CandleDrawItem {
  /** Bar center x, media px. */
  x: number;
  bar: Bar;
  /**
   * Close of the bar immediately before this one when that bar is not itself in
   * `items`, which is the case for the first visible bar after a scroll. Only
   * read when `colorByPreviousClose` is on, and only for the first item.
   */
  prevClose?: number;
}

/**
 * Draw candles onto a bitmap-scope context. `priceToY` and `x` are media-px;
 * everything is multiplied by `dpr` and snapped to device pixels here.
 */
export function drawCandles(
  ctx: CanvasRenderingContext2D,
  items: readonly CandleDrawItem[],
  priceToY: (price: number) => number,
  barSpacing: number,
  dpr: number,
  style: CandleStyle = DEFAULT_CANDLE_STYLE,
): void {
  const bodyW = optimalBarWidth(barSpacing, dpr);
  const wickW = Math.max(1, Math.floor(dpr));
  // Without a per-bar width scale every candle is the same width, so the tier
  // is a property of the style and the zoom rather than of the bar: decide it
  // once instead of per candle.
  const uniformTier = style.widthScale ? null : candleTier(bodyW, wickW, style);

  for (let i = 0; i < items.length; i++) {
    const { x, bar } = items[i]!; // i, and i - 1 when positive, index items
    // Previous-close colouring needs the bar before this one. The first drawn
    // bar has none in `items`, so it takes the caller's `prevClose` (the bar
    // left of the visible range) and otherwise falls back to open-vs-close:
    // the first bar of history has nothing to compare against, and inventing a
    // reference would make it lie. A non-finite reference (a whitespace gap)
    // falls back too, or every bar after a gap would go down off a NaN test.
    const ref = i > 0 ? items[i - 1]!.bar.close : items[i]!.prevClose;
    const up = style.colorByPreviousClose === true && ref !== undefined && Number.isFinite(ref)
      ? bar.close >= ref
      : bar.close >= bar.open;
    const yOpen = Math.round(priceToY(bar.open) * dpr);
    const yClose = Math.round(priceToY(bar.close) * dpr);
    const yHigh = Math.round(priceToY(bar.high) * dpr);
    const yLow = Math.round(priceToY(bar.low) * dpr);

    // Per-bar width (volume candles scale the body by relative volume). The
    // geometry is `candleGeometry`'s, worked out in place rather than returned
    // as an object: this runs for every candle in view on every frame.
    const cx = Math.round(x * dpr);
    const w = style.widthScale ? scaledBodyWidth(bodyW, style.widthScale(bar)) : bodyW;
    const halfW = Math.floor(w / 2);

    // A per-bar colour override replaces the whole up/down verdict
    // for this bar: body, border and wick together, or a recoloured candle would
    // keep a wick arguing the other way.
    const over = bar.color;
    const color = over ?? (up ? style.upColor : style.downColor);
    // A bar may name its wick and border apart from its body (a solid wick
    // over a translucent body); otherwise both follow the override, then the style.
    const wickColor = bar.wickColor ?? over ?? (up ? style.wickUpColor : style.wickDownColor);
    const borderColor = bar.borderColor ?? over ?? (up ? style.borderUpColor : style.borderDownColor);

    if (style.wickVisible) {
      ctx.fillStyle = wickColor;
      ctx.fillRect(cx - (wickW >> 1), yHigh, wickW, Math.max(1, yLow - yHigh));
    }

    // At the `wick` tier the body would repaint the pixels the wick just
    // covered, in the same colour, at the same x and the same width. Skipping
    // it is free: the candle is already fully drawn. A wick painted in its own
    // colour is the one case the tier cannot know about, so it is checked here.
    if ((uniformTier ?? candleTier(w, wickW, style)) === 'wick' && wickColor === color) continue;

    const top = Math.min(yOpen, yClose);
    const bodyH = Math.max(1, Math.abs(yClose - yOpen));

    if (style.hollow && up) {
      // Hollow up candle: the outline is the body, so it is drawn whether or not
      // borders are on. With Borders on it takes the border colour like any
      // other candle; with Borders off it falls back to the body colour, since
      // dropping the outline would erase the candle entirely.
      ctx.strokeStyle = style.borderVisible ? borderColor : color;
      ctx.lineWidth = Math.max(1, wickW);
      ctx.strokeRect(cx - halfW + 0.5, top + 0.5, w - 1, bodyH - 1);
    } else {
      const filled = style.bodyVisible !== false;
      if (filled) {
        ctx.fillStyle = color;
        ctx.fillRect(cx - halfW, top, w, bodyH);
      }
      // A filled body takes its border in hollow mode too: in that mode only the
      // up candles go hollow, and the down ones are ordinary filled candles.
      // Below 3px the 1px inset outline would swallow the body, so it is
      // dropped rather than repainting the candle in the border colour. With the
      // body hidden there is no fill to swallow and the outline IS the candle,
      // so that width guard does not apply.
      if (style.borderVisible && (!filled || w >= 3)) {
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 1;
        ctx.strokeRect(cx - halfW + 0.5, top + 0.5, w - 1, bodyH - 1);
      }
    }
  }
}
