/**
 * Point & Figure (ARCHITECTURE.md §6A). Columns of X (up) / O (down); a new
 * column starts only after a reversal of `reversal` boxes.
 *
 * Construction method (`method`):
 *  - `'hl'` (default, and what every desk means by P&F): each source bar's
 *    **high** extends an X column and its **low** extends an O column; the
 *    opposite extreme triggers the reversal test.
 *  - `'close'`: only the close is considered (the older, coarser variant).
 *
 * Box sizing (`mode`):
 *  - `'fixed'`: a constant `boxSize` (the classic).
 *  - `'percent'`: `price × percent / 100`, re-resolved when each column opens.
 *  - `'atr'`: `ATR(period) × multiplier` (Wilder), re-resolved per column.
 *  - `'atrPercent'`: `ATR(period) × percent / 100`, a box that is a share of the ATR.
 *
 * Each emitted column is a Bar spanning the column's price range, with up =
 * close ≥ open (X) and down = close < open (O). A column's `high` is the
 * **exclusive top edge** of its highest box, so `[low, high)` is exactly the
 * price span the glyph stack occupies. Every column also carries the `boxSize`
 * it was built with, so the renderer never needs to be told separately (which
 * is the only way variable-box modes can render correctly).
 */
import type { Bar } from '../model/bar';
import { copyState, type ISeriesTransform } from './transform';

export type PointFigureMethod = 'hl' | 'close';
export type PointFigureBoxMode = 'fixed' | 'percent' | 'atr' | 'atrPercent';

export interface PointFigureOptions {
  /** Box size for `mode: 'fixed'`. Required unless another mode is chosen. */
  boxSize?: number | undefined;
  /** Boxes of counter-move needed to start a new column. Default 3; floored, at least 1. */
  reversal?: number | undefined;
  /** Which prices drive the column. Default `'hl'`. */
  method?: PointFigureMethod | undefined;
  /** How the box size is resolved. Default `'fixed'`. */
  mode?: PointFigureBoxMode | undefined;
  /** Box as a percentage of price for `mode: 'percent'`, or of the ATR for `'atrPercent'` (e.g. `0.5` = 0.5%). */
  percent?: number | undefined;
  /** ATR lookback for `mode: 'atr'` and `'atrPercent'`. Default 14; floored, at least 1. */
  atrPeriod?: number | undefined;
  /** ATR multiplier for `mode: 'atr'`. Default 1. */
  atrMultiplier?: number | undefined;
}

/** A P&F column. Carries the box size it was built with (modes vary it). */
export interface PointFigureColumn extends Bar {
  /** Price height of one box in this column: one X or O glyph. */
  boxSize: number;
  /** Number of boxes (glyphs) stacked in this column. */
  boxes: number;
}

/** Streaming Wilder ATR. Reports the running TR mean during warmup. Shared with Renko; tier-internal. */
export class WilderAtr {
  private readonly _period: number;
  private _prevClose = NaN;
  private _sum = 0;
  private _n = 0;
  private _atr = NaN;

  public constructor(period: number) {
    this._period = Math.max(1, Math.floor(period));
  }

  public reset(): void {
    this._prevClose = NaN;
    this._sum = 0;
    this._n = 0;
    this._atr = NaN;
  }

  public push(bar: Bar): void {
    const tr = Number.isNaN(this._prevClose)
      ? bar.high - bar.low
      : Math.max(bar.high - bar.low, Math.abs(bar.high - this._prevClose), Math.abs(bar.low - this._prevClose));
    this._prevClose = bar.close;
    if (this._n < this._period) {
      this._sum += tr;
      this._n += 1;
      this._atr = this._sum / this._n; // warmup: running mean (Wilder's own seed)
    } else {
      this._atr = (this._atr * (this._period - 1) + tr) / this._period;
    }
  }

  /** Current ATR, or NaN before any bar. */
  public value(): number {
    return this._atr;
  }
}

export class PointFigureTransform implements ISeriesTransform {
  private readonly _reversal: number;
  private readonly _method: PointFigureMethod;
  private readonly _mode: PointFigureBoxMode;
  private readonly _fixedBox: number;
  private readonly _percent: number;
  private readonly _atrMult: number;
  private readonly _atr: WilderAtr;

  /** Box size of the column currently forming. */
  private _box = NaN;
  /** +1 X, -1 O, 0 = no column established yet. */
  private _dir = 0;
  /** Column bounds as integer box indices under `_box`. */
  private _top = NaN;
  private _bot = NaN;
  private _time = 0;

  public constructor(options: PointFigureOptions) {
    const mode = options.mode ?? 'fixed';
    this._mode = mode;
    this._reversal = Math.max(1, Math.floor(options.reversal ?? 3));
    this._method = options.method ?? 'hl';
    this._fixedBox = options.boxSize ?? NaN;
    this._percent = options.percent ?? NaN;
    this._atrMult = options.atrMultiplier ?? 1;
    this._atr = new WilderAtr(options.atrPeriod ?? 14);

    if (mode === 'fixed' && !(this._fixedBox > 0)) {
      throw new Error('openalgo-charts: P&F boxSize must be > 0');
    }
    if ((mode === 'percent' || mode === 'atrPercent') && !(this._percent > 0)) {
      throw new Error('openalgo-charts: P&F percent must be > 0');
    }
  }

  /** The fixed box size, for `mode: 'fixed'`. NaN in variable modes. */
  public get boxSize(): number {
    return this._fixedBox;
  }

  public reset(): void {
    this._box = NaN;
    this._dir = 0;
    this._top = NaN;
    this._bot = NaN;
    this._time = 0;
    this._atr.reset();
  }

  public clone(): PointFigureTransform {
    const copy = copyState(this);
    // The running ATR is state too, and its own object. The field is
    // readonly to everything but a copy being made.
    Object.assign(copy, { _atr: copyState(this._atr) });
    return copy;
  }

  /**
   * Box size for a column opening at `price`. Falls back to the last valid box,
   * then to 1% of price, then to 1, so a degenerate ATR/price never throws or
   * emits a zero-height column.
   */
  private _resolveBox(price: number): number {
    let box = NaN;
    if (this._mode === 'fixed') box = this._fixedBox;
    else if (this._mode === 'percent') box = (Math.abs(price) * this._percent) / 100;
    else if (this._mode === 'atrPercent') box = (this._atr.value() * this._percent) / 100;
    else box = this._atr.value() * this._atrMult;
    if (box > 0 && Number.isFinite(box)) return box;
    if (this._box > 0) return this._box;
    const pct = Math.abs(price) * 0.01;
    return pct > 0 ? pct : 1;
  }

  private _column(): PointFigureColumn {
    const box = this._box;
    const low = this._bot * box;
    const high = (this._top + 1) * box; // exclusive top edge of the highest box
    const up = this._dir >= 0;
    return {
      time: this._time,
      open: up ? low : high,
      close: up ? high : low,
      high,
      low,
      boxSize: box,
      boxes: this._top - this._bot + 1,
    };
  }

  public push(bar: Bar): Bar[] {
    if (this._mode === 'atr' || this._mode === 'atrPercent') this._atr.push(bar);

    const useHl = this._method === 'hl';
    const upPrice = useHl ? bar.high : bar.close;
    const downPrice = useHl ? bar.low : bar.close;

    // First bar: anchor only. No column, no direction: this is what used to
    // emit a phantom zero-height column when the first move was down.
    if (Number.isNaN(this._top)) {
      this._box = this._resolveBox(bar.close);
      const b = Math.floor(bar.close / this._box);
      this._top = b;
      this._bot = b;
      this._dir = 0;
      this._time = bar.time;
      return [];
    }

    const hb = Math.floor(upPrice / this._box);
    const lb = Math.floor(downPrice / this._box);

    // Direction not established yet: the first real move sets it, still with no
    // column emitted. Ties (an outside bar) resolve up, the classic convention.
    if (this._dir === 0) {
      const up = hb - this._top;
      const down = this._bot - lb;
      if (up <= 0 && down <= 0) return [];
      if (up >= down) { this._top = hb; this._dir = 1; }
      else { this._bot = lb; this._dir = -1; }
      this._time = bar.time;
      return [];
    }

    const out: Bar[] = [];
    if (this._dir > 0) {
      if (hb > this._top) {
        this._top = hb; // extend the X column
      } else if (this._top - lb >= this._reversal) {
        // Boundary = bottom edge of the X column's highest box; the O column
        // starts at the box just below it, re-derived under the new box size.
        const boundary = this._top * this._box;
        out.push(this._column());
        this._box = this._resolveBox(downPrice);
        this._top = Math.ceil(boundary / this._box) - 1;
        this._bot = Math.floor(downPrice / this._box);
        this._dir = -1;
        this._time = bar.time;
      }
    } else {
      if (lb < this._bot) {
        this._bot = lb; // extend the O column
      } else if (hb - this._bot >= this._reversal) {
        // Boundary = top edge of the O column's lowest box.
        const boundary = (this._bot + 1) * this._box;
        out.push(this._column());
        this._box = this._resolveBox(upPrice);
        this._bot = Math.floor(boundary / this._box);
        this._top = Math.floor(upPrice / this._box);
        this._dir = 1;
        this._time = bar.time;
      }
    }
    return out;
  }

  public flush(): Bar[] {
    // Nothing to emit until a direction (and therefore a real column) exists.
    if (this._dir === 0 || Number.isNaN(this._top)) return [];
    return [this._column()];
  }
}
