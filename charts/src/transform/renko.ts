/**
 * Renko bricks (ARCHITECTURE.md §6A). Each box-size move emits one brick.
 * Renders with the candlestick renderer (brick = a body). Simplified
 * single-box step (no 2× reversal rule): deterministic and incremental for
 * live updates.
 *
 * Brick sizing (`mode`), the same choices as point and figure:
 *  - `'fixed'` (default): a constant `boxSize`.
 *  - `'percent'`: `price × percent / 100`, re-resolved as each brick forms.
 *  - `'atr'`: `ATR(atrPeriod) × atrMultiplier` (Wilder), re-resolved as each
 *    brick forms.
 *    multiplier divided by 100.
 *  - `'atrPercent'`: `ATR(atrPeriod) × percent / 100`, a brick that is a share of the ATR.
 *
 * Prices (`method`): `'close'` (default) moves bricks on the close alone;
 * `'hl'` walks the bar's low and high in the order the bar most likely traded
 * them (low first on an up bar, high first on a down bar), so a long wick can
 * form bricks the close never reaches.
 */
import type { Bar } from '../model/bar';
import { copyState, type ISeriesTransform } from './transform';
import { WilderAtr, type PointFigureBoxMode } from './point-figure';

export interface RenkoOptions {
  /** Brick height in price for `mode: 'fixed'`. The constructor throws unless it is above 0. */
  boxSize?: number | undefined;
  /** How the brick height is resolved. Default `'fixed'`. */
  mode?: PointFigureBoxMode | undefined;
  /** Brick as a percentage of price for `mode: 'percent'`, or of the ATR for `'atrPercent'`. */
  percent?: number | undefined;
  /** ATR lookback for `mode: 'atr'` and `'atrPercent'`. Default 14; floored, at least 1. */
  atrPeriod?: number | undefined;
  /** ATR multiplier for `mode: 'atr'`. Default 1. */
  atrMultiplier?: number | undefined;
  /** Which prices move the bricks. Default `'close'`. */
  method?: 'close' | 'hl' | undefined;
}

export class RenkoTransform implements ISeriesTransform {
  private readonly _mode: PointFigureBoxMode;
  private readonly _fixed: number;
  private readonly _percent: number;
  private readonly _atrMult: number;
  private readonly _method: 'close' | 'hl';
  private readonly _atr: WilderAtr;
  private _box = NaN;
  private _edge = NaN; // price level of the last brick's far edge

  public constructor(options: RenkoOptions) {
    this._mode = options.mode ?? 'fixed';
    this._fixed = options.boxSize ?? NaN;
    this._percent = options.percent ?? NaN;
    this._atrMult = options.atrMultiplier ?? 1;
    this._method = options.method ?? 'close';
    this._atr = new WilderAtr(options.atrPeriod ?? 14);
    if (this._mode === 'fixed' && !(this._fixed > 0)) throw new Error('openalgo-charts: Renko boxSize must be > 0');
    if ((this._mode === 'percent' || this._mode === 'atrPercent') && !(this._percent > 0)) throw new Error('openalgo-charts: Renko percent must be > 0');
  }

  public reset(): void {
    this._box = NaN;
    this._edge = NaN;
    this._atr.reset();
  }

  public clone(): RenkoTransform {
    const copy = copyState(this);
    // The running ATR is state too, and its own object.
    Object.assign(copy, { _atr: copyState(this._atr) });
    return copy;
  }

  /**
   * Brick height for a brick starting at `price`. Falls back to the last valid
   * height, then to 1% of price, then to 1, so a degenerate ATR or price never
   * throws or forms a zero-height brick.
   */
  private _resolve(price: number): number {
    const box = this._mode === 'fixed' ? this._fixed
      : this._mode === 'percent' ? Math.abs(price) * this._percent / 100
        : this._mode === 'atrPercent' ? this._atr.value() * this._percent / 100 : this._atr.value() * this._atrMult;
    if (box > 0 && Number.isFinite(box)) return box;
    if (this._box > 0) return this._box;
    const pct = Math.abs(price) * 0.01;
    return pct > 0 ? pct : 1;
  }

  public push(bar: Bar): Bar[] {
    if (this._mode === 'atr' || this._mode === 'atrPercent') this._atr.push(bar);
    const out: Bar[] = [];
    if (Number.isNaN(this._edge)) {
      this._box = this._resolve(bar.close);
      this._edge = Math.floor(bar.close / this._box) * this._box; // anchor, no brick yet
      return out;
    }
    const path = this._method === 'close' ? [bar.close] : bar.close >= bar.open ? [bar.low, bar.high] : [bar.high, bar.low];
    for (const p of path) {
      while (p >= this._edge + this._box) {
        const lo = this._edge;
        const hi = this._edge + this._box;
        out.push({ time: bar.time, open: lo, high: hi, low: lo, close: hi }); // up brick (close>open)
        this._edge = hi;
        this._box = this._resolve(hi);
      }
      while (p <= this._edge - this._box) {
        const hi = this._edge;
        const lo = this._edge - this._box;
        out.push({ time: bar.time, open: hi, high: hi, low: lo, close: lo }); // down brick (close<open)
        this._edge = lo;
        this._box = this._resolve(lo);
      }
    }
    return out;
  }
}
