/**
 * Internal time is always **UTC seconds** (integer). Feed adapters convert
 * broker formats (IST strings, epoch ms) to this at the edge; see ARCHITECTURE.md §4.0.
 */
export type UTCSeconds = number;

/** The original, caller-supplied time value, echoed back untouched in callbacks. */
export type OriginalTime = number | string;

/** A single OHLC(V) bar. `volume` is optional (not all feeds carry it). */
export interface Bar {
  time: UTCSeconds;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  /**
   * Open interest: contracts outstanding at the end of this bar. Optional,
   * because only a derivatives feed carries it; on a cash instrument it is
   * absent, and absent is not zero. Zero is a real reading on a contract nobody
   * holds.
   *
   * **It is a level, not a flow, and that is the whole reason it needs saying
   * here.** Volume is a quantity traded *during* the bar, so folding five
   * one-minute bars into a five-minute bar adds five volumes together. Open
   * interest is a position *as at* the bar, so the same fold takes the last
   * one and adding them would produce a number five times too large that still
   * looks entirely plausible on a chart.
   *
   * Every aggregation path in this library therefore treats the two
   * differently: `mergeBars`, the higher-timeframe fold in `securitySeries`,
   * and the tick-to-bar builders all sum volume and carry the latest open
   * interest. A transform that maps one source bar to one output bar passes it
   * through; one that invents bars from price alone (Renko, Point and Figure)
   * does not carry it at all, because a synthetic bar has no instant to be the
   * position as at.
   */
  oi?: number;
  /**
   * Per-bar colour override, honoured by every Family-A renderer: candles and
   * OHLC bars take it on body, border and wick together, histogram and column
   * on the bar, and line, step, area and the HLC-area close line split their
   * stroke into runs at the bars where it changes. Baseline is the exception,
   * its stroke is already split by the above/below-base rule.
   * A MACD histogram is four colours by momentum, and a conditional study is
   * two. Neither is expressible with one colour for the whole series.
   */
  color?: string;
  /**
   * Wick colour for this bar alone, over `color`. A study that paints candles
   * with a translucent body and a solid wick cannot say so with one colour,
   * and without this a per-bar override always set the two together. Read by
   * the candle renderers only; absent means the wick follows `color`.
   */
  wickColor?: string;
  /** Border colour for this bar alone, on the same terms as `wickColor`. */
  borderColor?: string;
}

/** A single value point (for line/area/baseline series). */
export interface LinePoint {
  time: UTCSeconds;
  value: number;
  /** Per-bar colour override; carried through to the Bar. */
  color?: string;
}

/** A whitespace point: occupies a logical index for alignment but draws nothing. */
export interface Whitespace {
  time: UTCSeconds;
}

export function isWhitespace(p: Bar | LinePoint | Whitespace): p is Whitespace {
  return !('open' in p) && !('value' in p);
}

/** Any item a series accepts: an OHLC bar, a value point, or a whitespace gap. */
export type SeriesDataItem = Bar | LinePoint | Whitespace;

/**
 * Normalize any series data item into an internal OHLC bar:
 * - a `Bar` passes through untouched;
 * - a `LinePoint` `{ time, value }` becomes a flat OHLC bar (open=high=low=close=value);
 * - a `Whitespace` `{ time }` becomes a NaN bar, which the line renderer draws as a
 *   gap and autoscale skips.
 */
export function toBar(item: SeriesDataItem): Bar {
  if ('open' in item) return item;
  if ('value' in item) {
    const v = item.value;
    const bar: Bar = { time: item.time, open: v, high: v, low: v, close: v };
    // A value point may carry its own colour (a per-bar histogram).
    if (item.color !== undefined) bar.color = item.color;
    return bar;
  }
  return { time: item.time, open: NaN, high: NaN, low: NaN, close: NaN };
}
