/**
 * Kagi (ARCHITECTURE.md §6A). A continuous line that reverses direction only
 * after a move of at least `reversal`. Turning points are emitted as vertices.
 * Line thickness (yang/yin) is encoded in `volume` (1 = thick, 0 = thin) using
 * a simplified rule: thick once the line exceeds the previous up-turn (higher
 * shoulder), thin once it falls below the previous down-turn (lower waist).
 * The kagi renderer connects vertices with a stepped line of varying width.
 */
import type { Bar } from '../model/bar';
import { copyState, type ISeriesTransform } from './transform';

export interface KagiOptions {
  /** Price move that turns the line. The constructor throws unless it is above 0. */
  reversal: number;
}

function vertex(time: number, price: number, thick: boolean): Bar {
  return { time, open: price, high: price, low: price, close: price, volume: thick ? 1 : 0 };
}

export class KagiTransform implements ISeriesTransform {
  private readonly _reversal: number;
  private _dir = 0; // +1 up, -1 down, 0 none
  private _ext = NaN; // current extreme of the active segment
  private _prevShoulder = -Infinity; // last up-turn price
  private _prevWaist = Infinity; // last down-turn price
  private _thick = false;
  /** Time of the newest bar pushed, which the vertex still forming is dated at. */
  private _time = 0;

  public constructor(options: KagiOptions) {
    if (options.reversal <= 0) throw new Error('openalgo-charts: Kagi reversal must be > 0');
    this._reversal = options.reversal;
  }

  public reset(): void {
    this._dir = 0;
    this._ext = NaN;
    this._prevShoulder = -Infinity;
    this._prevWaist = Infinity;
    this._thick = false;
    this._time = 0;
  }

  public clone(): KagiTransform {
    return copyState(this);
  }

  public push(bar: Bar): Bar[] {
    const p = bar.close;
    this._time = bar.time;
    if (Number.isNaN(this._ext)) {
      this._ext = p;
      return [];
    }
    const out: Bar[] = [];
    if (this._dir >= 0) {
      if (p > this._ext) {
        this._ext = p;
        if (p > this._prevShoulder) this._thick = true; // broke prior shoulder: yang
      } else if (this._ext - p >= this._reversal) {
        out.push(vertex(bar.time, this._ext, this._thick)); // high turning point
        this._prevShoulder = this._ext;
        this._dir = -1;
        this._ext = p;
      }
    } else {
      if (p < this._ext) {
        this._ext = p;
        if (p < this._prevWaist) this._thick = false; // broke prior waist: yin
      } else if (p - this._ext >= this._reversal) {
        out.push(vertex(bar.time, this._ext, this._thick)); // low turning point
        this._prevWaist = this._ext;
        this._dir = 1;
        this._ext = p;
      }
    }
    return out;
  }

  public flush(): Bar[] {
    if (Number.isNaN(this._ext)) return [];
    return [vertex(this._time, this._ext, this._thick)];
  }
}
