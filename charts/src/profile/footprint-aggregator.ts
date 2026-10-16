/**
 * Streaming footprint aggregator (ARCHITECTURE.md §6A, §9.4). Ingests classified
 * trade ticks (price, qty, bid/ask) and aggregates them into footprint bars on a
 * timeframe (interval / tick-count / volume): the live orderflow pipeline.
 * Incremental: the current bar updates per tick; a new bar opens at the boundary.
 *
 * Requires classified bid/ask trade ticks. OpenAlgo doesn't store these by
 * default, so feed it from a live WS classifier or a tick-recorder backend.
 */
import type { FootprintBar, FootprintCell } from './profile-model';
import {
  addTickVolume, auctionAt, footprintRowPrice, footprintRowSize, minTradeSizeOf, validateClassifiedTrade,
  type ClassifiedTrade, type FootprintBuildOptions,
} from './footprint';
import type { TickTimeframe } from '../feed/tick-aggregator';

export interface FootprintTick extends ClassifiedTrade {
  time: number;
}

export interface FootprintUpdate {
  bar: FootprintBar;
  isNew: boolean;
}

export class FootprintAggregator {
  private readonly _tf: TickTimeframe;
  private readonly _tickSize: number;
  private readonly _rowTicks: number;
  private readonly _rowSize: number;
  private readonly _minSize: number;
  private _time = 0;
  private _cells = new Map<number, FootprintCell>();
  private _ticks = new Map<number, [number, number]>();
  private _delta = 0;
  private _minDelta = 0;
  private _maxDelta = 0;
  private _count = 0;
  private _prints = 0;
  private _volume = 0;
  private _open = false;
  private _lastTickTime = -Infinity;
  private _openPrice = 0;
  private _high = 0;
  private _low = 0;
  private _close = 0;

  /**
   * `rowTicks` widens each brick to `tickSize * rowTicks`: the same multiplier
   * the market profile uses, so an instrument's real tick stays honest while the
   * ladder stays readable. Nifty at 0.1 with 2-point bricks is `(tf, 0.1, 20)`.
   */
  public constructor(tf: TickTimeframe, tickSize: number, rowTicks = 1, options?: FootprintBuildOptions) {
    this._rowSize = footprintRowSize(tickSize, rowTicks);
    this._tickSize = tickSize;
    this._rowTicks = rowTicks;
    this._minSize = minTradeSizeOf(options);
    if (tf.mode === 'interval') {
      if (!Number.isFinite(tf.seconds) || tf.seconds <= 0) throw new RangeError('Footprint interval seconds must be positive and finite');
      if (tf.anchorSec !== undefined && !Number.isFinite(tf.anchorSec)) throw new RangeError('Footprint anchorSec must be finite');
    } else if (tf.mode === 'ticks') {
      if (!Number.isSafeInteger(tf.count) || tf.count < 1) throw new RangeError('Footprint tick count must be a positive integer');
    } else if (tf.mode === 'volume') {
      if (!Number.isFinite(tf.perBar) || tf.perBar <= 0) throw new RangeError('Footprint volume perBar must be positive and finite');
    } else throw new TypeError('Unknown footprint timeframe mode');
    this._tf = { ...tf };
  }

  private _snapshot(): FootprintBar {
    const cells = Array.from(this._cells.values(), (cell) => ({ ...cell })).sort((a, b) => b.price - a.price);
    return {
      time: this._time, cells, delta: this._delta, minDelta: this._minDelta, maxDelta: this._maxDelta, rowSize: this._rowSize,
      open: this._openPrice, high: this._high, low: this._low, close: this._close, tradeCount: this._count,
      auction: auctionAt(this._ticks, this._high, this._low, this._tickSize),
    };
  }

  public current(): FootprintBar | null {
    return this._open ? this._snapshot() : null;
  }

  /**
   * An interval bar covers [start, start + seconds): a tick stamped exactly on a
   * boundary opens the next bar, never the one that just ended.
   */
  private _intervalKey(time: number): number {
    if (this._tf.mode !== 'interval') return 0;
    const a = this._tf.anchorSec ?? 0;
    return a + Math.floor((time - a) / this._tf.seconds) * this._tf.seconds;
  }

  /**
   * Ticks must arrive in timestamp order (equal timestamps are accepted).
   * Count/volume bars coalesce trades sharing their opening timestamp until
   * time advances, so chart time keys remain unique. Such bars may exceed the
   * requested count/volume; volume trades are never split between bars. Count and
   * volume bars close on every print, filtered or not.
   */
  public onTick(tick: FootprintTick): FootprintUpdate {
    validateClassifiedTrade(tick);
    if (!Number.isFinite(tick.time)) throw new RangeError('Footprint tick time must be finite');
    if (tick.time < this._lastTickTime) throw new RangeError('Footprint tick timestamp is out of order');
    let startNew = !this._open;
    if (this._open) {
      if (this._tf.mode === 'interval') startNew = this._intervalKey(tick.time) !== this._time;
      else if (this._tf.mode === 'ticks') startNew = this._prints >= this._tf.count && tick.time > this._time;
      else startNew = this._volume >= this._tf.perBar && tick.time > this._time;
    }

    if (startNew) {
      this._cells = new Map();
      this._ticks = new Map();
      this._delta = 0;
      this._minDelta = 0;
      this._maxDelta = 0;
      this._count = 0;
      this._prints = 0;
      this._volume = 0;
      this._open = true;
      this._openPrice = this._high = this._low = tick.price;
      this._time = this._tf.mode === 'interval' ? this._intervalKey(tick.time) : tick.time;
    }

    const price = footprintRowPrice(tick.price, this._tickSize, this._rowTicks);
    let cell = this._cells.get(price);
    if (cell === undefined) { cell = { price, bidVol: 0, askVol: 0 }; this._cells.set(price, cell); }
    addTickVolume(this._ticks, tick, this._tickSize);
    if (tick.qty >= this._minSize) {
      if (tick.side === 'bid') { cell.bidVol += tick.qty; this._delta -= tick.qty; }
      else { cell.askVol += tick.qty; this._delta += tick.qty; }
      this._minDelta = Math.min(this._minDelta, this._delta);
      this._maxDelta = Math.max(this._maxDelta, this._delta);
      this._count += 1;
    }
    this._prints += 1;
    this._volume += tick.qty;
    this._high = Math.max(this._high, tick.price);
    this._low = Math.min(this._low, tick.price);
    this._close = tick.price;
    this._lastTickTime = tick.time;

    return { bar: this._snapshot(), isNew: startNew };
  }
}
