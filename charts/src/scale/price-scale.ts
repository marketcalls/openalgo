/**
 * Price scale (ARCHITECTURE.md §5.2). Maps between price and y for a pane, in any of the
 * four modes (linear, logarithmic, percentage, indexed-to-100), with
 * tick-size-aware formatting and support for hidden overlay scales.
 */
import { clamp } from '../helpers/math';
import { niceTicks, precisionForStep } from './ticks';

export interface PriceRange {
  min: number;
  max: number;
}

/**
 * Price-scale mode, each one a coordinate transform (see `PriceScale._t`):
 * `linear` is the identity, `logarithmic` is log10, and `percentage` /
 * `indexed-to-100` rebase every price against a baseline: percent change from
 * it, or the baseline rebased to 100. The rebasing pair needs a baseline from
 * the data before it can transform anything, see `PriceScale.setBaseline`.
 *
 * Overlay scales are supported in every mode: a series added with
 * `priceScaleId: ''` gets a hidden scale with its own autoscale, see
 * `Pane._scaleFor`.
 */
export type PriceScaleMode = 'linear' | 'logarithmic' | 'percentage' | 'indexed-to-100';

/**
 * The four price-scale modes, in the order a menu lists them. The one list:
 * restore, the hit prefilter and the settings schema read it, so a fifth mode
 * is added here and in the type above.
 */
export const PRICE_SCALE_MODES: readonly PriceScaleMode[] =
  ['linear', 'logarithmic', 'percentage', 'indexed-to-100'];

/** Whether a mode rebases prices against a baseline rather than mapping them directly. */
export function isRebasing(mode: PriceScaleMode): boolean {
  return mode === 'percentage' || mode === 'indexed-to-100';
}

export interface PriceScaleOptions {
  /** Fraction of pane height kept empty at top/bottom (default 0.1 each). */
  marginTop: number;
  marginBottom: number;
  /**
   * Instrument tick size (minMove), e.g. 0.05. 0 infers it from the range.
   *
   * A property of the instrument and not of the axis, so it belongs only on a
   * scale that quotes one. An oscillator's pane reads in its own units and is
   * left at 0 there, which is why `Chart.setPriceScaleOptions` withholds it
   * from those panes rather than broadcasting it like the rest of this block.
   */
  minMove: number;
  /**
   * Least decimals a scale with no tick will print. 0 leaves the span to
   * decide alone, which is right for a price axis and too coarse for a bounded
   * oscillator: see `precision()`.
   *
   * Ignored once `minMove` is set, because a declared tick is a stronger
   * statement about the instrument than a floor is about the axis.
   */
  minPrecision: number;
  /** Linear, logarithmic or rebased (percentage / indexed-to-100) mapping between price and y. */
  mode: PriceScaleMode;
  /** Flip the axis (price increases downward): for spread/short views. */
  inverted: boolean;
}

export const DEFAULT_PRICE_SCALE_OPTIONS: PriceScaleOptions = {
  marginTop: 0.1,
  marginBottom: 0.1,
  minMove: 0,
  minPrecision: 0,
  mode: 'linear',
  inverted: false,
};

/**
 * Above this the floor lifts: the integer part already carries five digits, so
 * a decimal adds width without adding information.
 */
const FLOOR_MAX_MAGNITUDE = 1e4;

/**
 * Pure: compute a price range from data extremes plus top/bottom margins.
 * Returns a padded [min,max]; widens a degenerate (flat) range so it's drawable.
 *
 * The margins are fractions of the **pane height**, so the data band occupies
 * the `1 - marginTop - marginBottom` left between them. Padding the data span
 * by the margin instead (which is what this did) makes the reserved space
 * depend on how tall the data happens to be: an overlay asking for `0.82` to
 * sit in the bottom 18% got `high + 0.82 * span`, leaving its bars 55% of the
 * pane. The difference only shows at large margins; at the 0.1 default the two
 * readings land within a few percent of each other.
 */
export function autoscaleRange(low: number, high: number, marginTop: number, marginBottom: number): PriceRange {
  if (!isFinite(low) || !isFinite(high)) return { min: 0, max: 1 };
  if (high <= low) {
    const pad = Math.abs(high) > 0 ? Math.abs(high) * 0.05 : 0.5;
    return { min: low - pad, max: high + pad };
  }
  const span = high - low;
  // Margins totalling >= 1 would leave the data no room at all; keep a sliver
  // so the range stays finite and the series remains drawable.
  const visible = Math.max(1 - marginTop - marginBottom, 0.01);
  const total = span / visible;
  return { min: low - total * marginBottom, max: high + total * marginTop };
}

/**
 * `autoscaleRange` in the space the scale draws in. The margins are fractions
 * of the pane, so a log scale pads in log units: padded in price units, a
 * series from 150 to 1230 got a floor near 15 and a whole empty decade under
 * its lowest bar. A range a log scale cannot take the log of (zero, a
 * negative low, a flat series) keeps the price-space padding, and so does an
 * unbounded one, whose fallback is a range in price units, not in log units.
 */
export function scaleAutoscaleRange(mode: PriceScaleMode, low: number, high: number, marginTop: number, marginBottom: number): PriceRange {
  if (mode !== 'logarithmic' || !(low > 0) || !(high > low) || !isFinite(high)) return autoscaleRange(low, high, marginTop, marginBottom);
  const r = autoscaleRange(Math.log10(low), Math.log10(high), marginTop, marginBottom);
  return { min: Math.pow(10, r.min), max: Math.pow(10, r.max) };
}

export class PriceScale {
  private _options: PriceScaleOptions;
  private _height = 0;
  private _min = 0;
  private _max = 1;
  private _autoScale = true;
  /**
   * True once a real range has been applied. The default 0..1 is a placeholder,
   * not a measurement: anything converting between y and price before that would answer
   * confidently with nonsense.
   */
  private _scaled = false;
  /**
   * Baseline for the rebasing modes. null is "nothing measured yet", the same
   * idea as `_scaled`: until the data supplies one there is no percent change
   * to report, so the transform stays the identity.
   */
  private _baseline: number | null = null;
  /**
   * A range declared by whoever owns this scale rather than measured from the
   * data: an oscillator's 0..100, a signal's -1..1. It is remembered, not just
   * applied, because "fit this axis" has a different answer on a declared axis:
   * the fit *is* the declared range, and a request to auto-fit has to be able
   * to find its way back to it. See `setFixedRange`.
   */
  private _fixedRange: PriceRange | null = null;
  private _fixedRangeOwner: object | null = null;
  /** Host writes can keep the same numeric range and still take control of the view. */
  private _manualRangeOverride = false;
  private _priceFormatter: ((price: number) => string) | null = null;

  public constructor(options: Partial<PriceScaleOptions> = {}) {
    this._options = { ...DEFAULT_PRICE_SCALE_OPTIONS, ...options };
  }

  public get options(): PriceScaleOptions {
    return this._options;
  }

  /** Merge partial options (minMove, mode, inverted, margins) at runtime. */
  public setOptions(opts: Partial<PriceScaleOptions>): void {
    this._options = { ...this._options, ...opts };
    // A baseline only means something while a rebasing mode is in force, and
    // the autoscale pass only refreshes it in those modes. Leaving it set on the
    // way back to linear strands a stale number that still reads as "this scale
    // is rebasing" to anyone who asks, which is how a comparison overlay kept
    // mirroring a percentage ladder after the user had turned percentage off.
    if (!isRebasing(this._options.mode)) this._baseline = null;
  }

  public setHeight(height: number): void {
    this._height = height;
  }

  public get height(): number {
    return this._height;
  }

  public setPriceRange(range: PriceRange): void {
    this._manualRangeOverride = true;
    this._writePriceRange(range);
  }

  /** Internal renderer projection update, preserving host ownership of the view. */
  public setComputedRange(range: PriceRange): void { this._writePriceRange(range); }

  private _writePriceRange(range: PriceRange): void {
    this._min = range.min;
    this._max = range.max;
    this._scaled = true;
  }

  /** Whether a real price range has been applied (see `_scaled`). */
  public get scaled(): boolean {
    return this._scaled;
  }

  /**
   * Set the baseline the rebasing modes (`percentage`, `indexed-to-100`) quote
   * against. Ignored by `linear` and `logarithmic`.
   *
   * The baseline is *data*, not geometry, so the scale cannot find it alone:
   * the autoscale pass supplies the first value of the visible range each
   * frame. That is what makes panning re-base, so the axis always reads as
   * change measured from the left edge of what is on screen.
   *
   * Pass null when there is nothing to measure (no series, no visible bars).
   * A rebasing mode without a baseline falls back to the identity transform
   * and behaves exactly like `linear`, rather than answering confidently with
   * nonsense before the first frame.
   *
   * Note what a rebase does *not* do: it is affine over a range held in price
   * units, so it relabels the pane rather than reshaping it. One series looks
   * the same as it does on a linear scale, by definition (percent change is a
   * straight-line function of price). Two instruments become comparable when
   * each sits on its own scale with its own baseline, which is the overlay
   * mechanism, not a second transform here.
   */
  public setBaseline(value: number | null): void {
    this._baseline = value;
  }

  /** The baseline last supplied, or null if none (see `setBaseline`). */
  public get baseline(): number | null {
    return this._baseline;
  }

  public priceRange(): PriceRange {
    return { min: this._min, max: this._max };
  }

  /** Whether the range tracks the data (true) or has been set manually (false). */
  public get autoScale(): boolean {
    return this._autoScale;
  }

  public setAutoScale(on: boolean): void {
    this._manualRangeOverride = !on;
    // A declared range is this axis' idea of a fit, so asking for auto-fit puts
    // it back rather than handing the axis to the measuring pass. Without this,
    // a chart-wide "Auto" sweep re-measured every oscillator pane against its
    // own values: an RSI band pinned to 0..100 came back as 18..86, relabelled,
    // and nothing could put it back, with the declared range gone.
    if (on && this._fixedRange !== null) {
      this._writePriceRange(this._fixedRange);
      return;
    }
    this._autoScale = on;
  }

  /**
   * Declare the range this scale must hold, or pass null to withdraw it.
   *
   * It is what an indicator that owns its pane asks for (RSI 0..100, a signal
   * line -1..1): a band whose meaning is in the numbers themselves, so fitting
   * it to the values on screen would destroy the reading rather than improve
   * it. The scale goes manual while one is held, because the range is declared
   * and not measured, and `setAutoScale(true)` returns to it.
   *
   * Withdrawing (null) leaves the range where it is; the caller decides whether
   * the scale goes back under autoscale, because it is the one that knows
   * whether anything is left on the pane to measure.
   */
  public setFixedRange(range: PriceRange | null): void {
    this._fixedRangeOwner = null;
    this._fixedRange = range === null ? null : { ...range };
    if (range !== null) {
      this._manualRangeOverride = true;
      this._autoScale = false;
      this._writePriceRange(range);
    }
  }

  /** Internal host helper: install a study default without taking over a host-controlled range. */
  public setOwnedFixedRange(owner: object, range: PriceRange): boolean {
    if (this._fixedRangeOwner === owner && this._manualRangeOverride) {
      this._fixedRange = { ...range };
      return true;
    }
    if (this._manualRangeOverride || (this._fixedRangeOwner !== owner && (this._fixedRange !== null || !this._autoScale))) return false;
    this._fixedRangeOwner = owner;
    this._fixedRange = { ...range };
    this._autoScale = false;
    this._writePriceRange(range);
    return true;
  }

  /** Internal host helper: withdraw only this owner's default, preserving later host range writes. */
  public clearOwnedFixedRange(owner: object): boolean {
    if (!this.ownsFixedRange(owner)) return false;
    this._fixedRangeOwner = null;
    this._fixedRange = null;
    if (!this._manualRangeOverride) this._autoScale = true;
    return true;
  }

  /** Internal host helper: ownership is identity-based, independent of equal numeric endpoints. */
  public ownsFixedRange(owner: object): boolean {
    return this._fixedRangeOwner === owner && this._fixedRange !== null;
  }

  /** Internal host metadata for saving an owned default and any later manual view override. */
  public ownedFixedRangeState(owner: object): { manual: boolean } | null {
    return this.ownsFixedRange(owner) ? { manual: this._manualRangeOverride } : null;
  }

  /** Whether an unused scale retains configuration beyond a measured automatic range. */
  public hasConfiguration(): boolean {
    return this._manualRangeOverride || this._fixedRange !== null || this._priceFormatter !== null
      || (Object.keys(DEFAULT_PRICE_SCALE_OPTIONS) as (keyof PriceScaleOptions)[])
        .some(key => this._options[key] !== DEFAULT_PRICE_SCALE_OPTIONS[key]);
  }

  /** The declared range this scale is holding, or null. See `setFixedRange`. */
  public get fixedRange(): PriceRange | null {
    return this._fixedRange === null ? null : { ...this._fixedRange };
  }

  /**
   * Forget the measured range and go back to the placeholder.
   *
   * Called when a scale loses its last series: the range it holds described
   * something that is no longer on the chart, and whatever arrives next may
   * plot nothing at all. An indicator whose entire output is a table plots no
   * values, and inheriting a departed oscillator's 0..100 left its pane
   * labelled with a ladder it had no prices for.
   *
   * A manually scaled axis is left alone: the user set that range, and nothing
   * would recompute it if it were thrown away.
   */
  public reset(): void {
    if (!this._autoScale) return;
    this._min = 0;
    this._max = 1;
    this._scaled = false;
    // The baseline described the departed series too, and nothing else would
    // clear it: a rebasing scale would keep quoting the next series against a
    // price that is no longer on the chart.
    this._baseline = null;
  }

  /**
   * Manually scale the visible range around its centre. `factor` > 1 widens the
   * range (compress / zoom out), < 1 narrows it (expand / zoom in). Switches the
   * scale to manual mode so autoscale stops overriding it.
   */
  public scaleAroundCenter(factor: number): void {
    this._manualRangeOverride = true;
    const centre = (this._min + this._max) / 2;
    const half = ((this._max - this._min) / 2) * factor;
    this._min = centre - half;
    this._max = centre + half;
    this._autoScale = false;
  }

  /** Scale around a screen coordinate, retaining its price in every scale mode. */
  public scaleAtY(y: number, factor: number): void {
    if (!this._scaled || this._height <= 0 || !Number.isFinite(factor) || factor <= 0) return;
    const lo = this._t(this._min);
    const hi = this._t(this._max);
    const anchor = this._t(this.yToPrice(y));
    const min = this._tInv(anchor + (lo - anchor) * factor);
    const max = this._tInv(anchor + (hi - anchor) * factor);
    if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) return;
    this.setPriceRange({ min, max });
    this._autoScale = false;
  }

  /**
   * Pan the visible range vertically by `dy` media px (dragging the plot up/down).
   * Works in transformed space so it's correct for log scales, and respects
   * `inverted`. Switches to manual mode so autoscale stops overriding it.
   */
  public panByPixels(dy: number): void {
    if (this._height <= 0 || dy === 0) return;
    const lo = this._t(this._min);
    const hi = this._t(this._max);
    const span = hi - lo;
    if (!(span > 0)) return;
    // Drag down (dy>0) reveals higher prices, so shift the range up; inverted flips it.
    const delta = span * ((this._options.inverted ? -dy : dy) / this._height);
    this._min = this._tInv(lo + delta);
    this._max = this._tInv(hi + delta);
    this._manualRangeOverride = true;
    this._autoScale = false;
  }

  /**
   * Recompute the visible range from data extremes + configured margins.
   *
   * The range stays in *price* units in every mode, so the rebasing modes need
   * no separate pass: their transform is affine with a positive scale factor,
   * which maps a margin of 10% of the price span onto a margin of 10% of the
   * percent span. Log pads in log space (`scaleAutoscaleRange`), so the data
   * keeps the same share of the pane there too.
   */
  public autoscale(low: number, high: number, progress = 1): boolean {
    if (this._fixedRange !== null) {
      this._writePriceRange(this._fixedRange);
      return false;
    }
    const target = scaleAutoscaleRange(this._options.mode, low, high, this._options.marginTop, this._options.marginBottom);
    const lo = this._t(this._min);
    const hi = this._t(this._max);
    const nextLo = this._t(target.min);
    const nextHi = this._t(target.max);
    const span = hi - lo;
    const nextSpan = nextHi - nextLo;
    const displacement = Math.max(Math.abs((nextLo - lo) / span), Math.abs((nextHi - hi) / span)) * this._height;
    if (!this._scaled || progress >= 1 || !Number.isFinite(progress) || !(span > 0) || !(nextSpan > 0) || displacement < 0.1) {
      this._writePriceRange(target);
      return false;
    }
    const fraction = clamp(progress, 0, 1);
    // Interpolate the projection, not the extent. Interpolating a narrow range
    // towards a tall new candle spends most of the screen movement immediately.
    const slope = (1 - fraction) / span + fraction / nextSpan;
    const min = ((1 - fraction) * lo / span + fraction * nextLo / nextSpan) / slope;
    this._writePriceRange({ min: this._tInv(min), max: this._tInv(min + 1 / slope) });
    return true;
  }

  /**
   * The baseline actually in force, or null when this mode does not rebase or
   * the value it was given cannot carry one.
   *
   * Zero and negative baselines are rejected on purpose. Percent change from
   * zero is undefined (every price is an infinite move away), and a negative
   * baseline flips the sign of the whole transform, so a rising price would
   * draw *downward* on an axis that still labels itself normally. Falling back
   * to the identity is recoverable and obvious on screen; an axis that
   * silently runs backwards is neither. Instruments that legitimately cross
   * zero (spreads, oscillators) have no percent-of-baseline reading to want.
   */
  private _rebase(): number | null {
    const mode = this._options.mode;
    if (mode !== 'percentage' && mode !== 'indexed-to-100') return null;
    const b = this._baseline;
    return b !== null && isFinite(b) && b > 0 ? b : null;
  }

  /**
   * Coordinate transform for the active mode: identity for linear, log10 for
   * log, and a rebase against the baseline for percentage/indexed-to-100.
   * The rebasing pair share one ladder: percent change is the index minus the
   * 100 it is rebased to.
   */
  private _t(v: number): number {
    if (this._options.mode === 'logarithmic') return Math.log10(Math.max(1e-10, v));
    const base = this._rebase();
    if (base === null) return v;
    const indexed = (v / base) * 100;
    return this._options.mode === 'percentage' ? indexed - 100 : indexed;
  }

  private _tInv(c: number): number {
    if (this._options.mode === 'logarithmic') return Math.pow(10, c);
    const base = this._rebase();
    if (base === null) return c;
    return ((this._options.mode === 'percentage' ? c + 100 : c) * base) / 100;
  }

  /** Price to y (media px). A higher price gives a smaller y (top of pane), unless inverted. */
  public priceToY(price: number): number {
    const lo = this._t(this._min);
    const span = this._t(this._max) - lo;
    if (span <= 0) return this._height / 2;
    const r = (this._t(price) - lo) / span; // 0 at min … 1 at max
    return this._options.inverted ? this._height * r : this._height * (1 - r);
  }

  /** y (media px) to price. */
  public yToPrice(y: number): number {
    const lo = this._t(this._min);
    const span = this._t(this._max) - lo;
    const r = this._options.inverted ? y / this._height : 1 - y / this._height;
    return this._tInv(lo + r * span);
  }

  /**
   * Decimal precision implied by minMove (or the visible range if unset).
   *
   * While a rebase is in force the labels are percent/index points, where a
   * price tick size means nothing: precision comes from the transformed span
   * instead, with two decimals as the floor traders expect of a percentage
   * ("+3.42%") and more only when the visible band is tighter than that.
   *
   * A scale carrying no tick is not quoting an instrument, so the span is all
   * there is to go on. That alone reads too coarse on a bounded oscillator: an
   * RSI spanning 0 to 100 implies a step of 1 and prints a whole-number ladder,
   * so a reading of 62.24 lands on a rung labelled "62" and a trader comparing
   * it to a 70 level is reading a number that has been rounded past the part
   * they care about. `minPrecision` is the floor for that case, and it is the
   * same two decimals the percent branch above already settles on for the same
   * reason.
   */
  public precision(): number {
    if (this._rebase() !== null) {
      return Math.max(2, precisionForStep((this._t(this._max) - this._t(this._min)) / 100));
    }
    if (this._options.minMove > 0) return precisionForStep(this._options.minMove);
    const inferred = precisionForStep((this._max - this._min) / 100);
    // Only where decimals are still information. Past five integer digits they
    // are not: an on-balance-volume of 1,234,567.00 says nothing the integer
    // did not, and the two zeroes cost the axis width that the digits need.
    const magnitude = Math.max(Math.abs(this._min), Math.abs(this._max));
    if (!Number.isFinite(magnitude) || magnitude >= FLOOR_MAX_MAGNITUDE) return inferred;
    return Math.max(this._options.minPrecision, inferred);
  }

  /**
   * Tick prices for the axis ladder, at most `maxTicks` of them. Linear and log
   * get the nice ladder over the price range, exactly what the axis renderer
   * used to build for itself.
   *
   * The rebasing modes need it built in *label* space: a nice price is an ugly
   * percentage, and a ladder of "+3.47%, +6.94%" is not a ladder. So the nice
   * values are chosen over the transformed range and mapped back to the prices
   * the axis positions with.
   */
  public ticks(maxTicks = 6): number[] {
    if (this._rebase() === null) return niceTicks(this._min, this._max, maxTicks);
    return niceTicks(this._t(this._min), this._t(this._max), maxTicks).map((v) => this._tInv(v));
  }

  /** Snap a price to the instrument tick size (no-op if minMove is 0). */
  public snapToTick(price: number): number {
    const step = this._options.minMove;
    if (step <= 0) return price;
    return Math.round(price / step) * step;
  }

  /**
   * Override the numeric formatting used for axis tick labels, the last-price
   * tag, and price-line labels (e.g. a currency or percent format). Pass null
   * to restore the default tick-size-aware `toFixed`.
   */
  public setPriceFormatter(fn: ((price: number) => string) | null): void {
    this._priceFormatter = fn;
  }

  /**
   * Format a price for axis/label display. While a rebase is in force the
   * label is the rebased value, "+3.42%" or "103.42", and it outranks a custom
   * price formatter: a currency prefix on a percent change would read as money
   * that is not there. The formatter takes over again the moment the mode does.
   */
  public format(price: number): string {
    if (this._rebase() !== null) {
      const digits = this.precision();
      const v = this._t(price);
      if (this._options.mode === 'indexed-to-100') return v.toFixed(digits);
      // Sign is explicit so the axis reads as change rather than as a level.
      // A value that rounds to zero drops it, including the hair-below-zero
      // one that toFixed would otherwise render as "-0.00".
      const rounded = Number(v.toFixed(digits));
      return `${rounded > 0 ? '+' : ''}${(rounded === 0 ? 0 : v).toFixed(digits)}%`;
    }
    if (this._priceFormatter !== null) return this._priceFormatter(price);
    return price.toFixed(this.precision());
  }

  /** Clamp a y to the pane (used by crosshair/order dragging). */
  public clampY(y: number): number {
    return clamp(y, 0, this._height);
  }
}
