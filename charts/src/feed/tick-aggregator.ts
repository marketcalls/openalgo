/**
 * Tick aggregation (ARCHITECTURE.md 10.2). Aggregates raw trade ticks into
 * bars on a chosen bucketing: clock interval, calendar period, tick count, or
 * traded volume. Incremental and deterministic, so it works live and is
 * unit-testable.
 *
 * This is the foundation for tick / volume timeframes and (with classified
 * bid/ask ticks) for the footprint aggregator. Tick-count and volume bars need
 * real trade ticks: OHLCV alone can't produce them.
 *
 * The bucketing rules themselves live in `./intervals`, which is also where a
 * host registers its own interval codes; this class just applies one.
 */
import type { Bar } from '../model/bar';
import { bucketStartOf, isTimeBucketed, type Bucketing } from './intervals';

// The three original modes keep their name and their home in the public API.
export type { TickTimeframe } from './intervals';

export interface AggTick {
  time: number;
  price: number;
  qty: number;
  /**
   * Open interest as at this tick, where the feed carries it. Carried onto the
   * bar as the latest reading rather than accumulated: see `Bar.oi`.
   */
  oi?: number;
}

export interface BarUpdate {
  bar: Bar;
  isNew: boolean;
}

export interface TickBarOptions {
  /**
   * Zone a calendar bucket resolves in when the bucketing did not pin its own.
   * Pass the chart's configured timezone: a month boundary is local midnight on
   * the first, and which instant that is depends on where the exchange is.
   */
  timezone?: string | undefined;
}

export class TickBarAggregator {
  private readonly _tf: Bucketing;
  private readonly _zone: string | undefined;
  private _cur: Bar | null = null;
  private _count = 0;

  public constructor(tf: Bucketing, options: TickBarOptions = {}) {
    this._tf = tf;
    this._zone = options.timezone;
  }

  public current(): Bar | null {
    return this._cur === null ? null : { ...this._cur };
  }

  /**
   * Continue a historical bar instead of opening a fresh one on the first tick.
   * Time-bucketed modes only: a count-driven bar cannot be resumed, because the
   * trades that filled it were never counted here.
   */
  public seed(lastBar: Bar): void {
    if (!isTimeBucketed(this._tf)) return;
    this._cur = { ...lastBar };
    this._count = 0;
  }

  public onTick(tick: AggTick): BarUpdate {
    const open = this._cur === null;
    let startNew = open;

    if (!open && this._cur !== null) {
      if (this._tf.mode === 'interval' || this._tf.mode === 'calendar') {
        startNew = bucketStartOf(this._tf, tick.time, this._zone) !== this._cur.time;
      } else if (this._tf.mode === 'ticks') {
        startNew = this._count >= this._tf.count;
      } else {
        startNew = (this._cur.volume ?? 0) >= this._tf.perBar;
      }
    }

    if (startNew) {
      // Time-bucketed bars open on their boundary; count-driven bars are not
      // time-keyed at all, so bucketStartOf hands back the opening tick's time.
      const time = bucketStartOf(this._tf, tick.time, this._zone);
      this._cur = { time, open: tick.price, high: tick.price, low: tick.price, close: tick.price, volume: tick.qty };
      if (tick.oi !== undefined && Number.isFinite(tick.oi)) this._cur.oi = tick.oi;
      this._count = 1;
      return { bar: { ...this._cur }, isNew: true };
    }

    const c = this._cur as Bar;
    if (tick.price > c.high) c.high = tick.price;
    if (tick.price < c.low) c.low = tick.price;
    c.close = tick.price;
    c.volume = (c.volume ?? 0) + tick.qty;
    if (tick.oi !== undefined && Number.isFinite(tick.oi)) c.oi = tick.oi;
    else delete c.oi;
    this._count += 1;
    return { bar: { ...c }, isNew: false };
  }
}
