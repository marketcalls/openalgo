/**
 * Live candle aggregation (ARCHITECTURE.md §10.2). The WS feed does not deliver
 * interval candles: LTP mode gives a tick price (+ last-traded-qty), Quote mode
 * gives a *cumulative day* volume. This builder buckets ticks into interval OHLC
 * with explicit volume, session-reset, and late-tick policies. Pure and
 * deterministic (no Date/rAF) so it is fully unit-testable.
 */
import type { Bar, UTCSeconds } from '../model/bar';
import type { LooseOptional } from '../helpers/types';

export type VolumeMode = 'ltq-sum' | 'day-delta';
export type LateTickPolicy = 'foldIntoBar' | 'dropOlderThanPrevBar';

/**
 * Two observations of one bucket as one bar: the extremes are the union,
 * since each side saw real prices, and the volume the larger, since volume
 * inside a bar only grows (a bar neither side gave a volume keeps none).
 * Every other field is `base`'s. Which side owns the open, the close and the
 * open interest depends on which one the caller trusts for them, so each
 * caller sets those itself.
 */
export function widenBar(base: Bar, observed: Bar): Bar {
  return {
    ...base,
    high: Math.max(base.high, observed.high),
    low: Math.min(base.low, observed.low),
    // Bar stays exact for hosts; an undefined volume here is a bar without one.
    volume: base.volume === undefined && observed.volume === undefined
      ? undefined : Math.max(base.volume ?? 0, observed.volume ?? 0),
  } satisfies LooseOptional<Bar> as Bar;
}

export interface CandleBuilderOptions {
  intervalSec: number;
  /** 'ltq-sum' accumulates last-traded-qty; 'day-delta' diffs cumulative day volume. */
  volumeMode: VolumeMode;
  lateTickPolicy: LateTickPolicy;
  /**
   * UTC-seconds of a known session open. Buckets align to it so e.g. 5-minute
   * bars start at 09:15, not at an arbitrary epoch floor. Defaults to 0 (epoch).
   */
  sessionAnchorSec: number;
}

export const DEFAULT_CANDLE_BUILDER_OPTIONS: CandleBuilderOptions = {
  intervalSec: 60,
  volumeMode: 'ltq-sum',
  lateTickPolicy: 'foldIntoBar',
  sessionAnchorSec: 0,
};

export interface Tick {
  time: UTCSeconds;
  price: number;
  /** Last-traded quantity (LTP mode). */
  ltq?: number;
  /** Cumulative day volume (Quote mode). */
  cumDayVolume?: number;
  /**
   * Open interest as at this tick, where the feed carries it. Unlike the two
   * quantities above it is not accumulated into the bar: it replaces, because
   * it is a level and not a flow (see `Bar.oi`). A feed that does not report it
   * leaves the built bar without one, which is the honest result rather than a
   * zero that reads as "nobody is holding this".
   */
  oi?: number;
}

export interface CandleUpdate {
  bar: Bar;
  /** True when this tick started a new interval bar (append vs mutate-in-place). */
  isNew: boolean;
  /**
   * True while the bar's open, high, low and volume cover only the ticks this
   * builder has seen. A bar is provisional when it was opened from a tick
   * without the builder having streamed the bar before it: a cold start, or a
   * seed from an older bucket, both of which mean the trades between the
   * bucket's true open and the first tick seen were missed. The close is still
   * the latest price. An authoritative bar for the same bucket, from history,
   * corrects the rest through `reconcile`.
   */
  provisional?: boolean;
}

export class CandleBuilder {
  private readonly _opts: CandleBuilderOptions;
  private _current: Bar | null = null;
  private _cumAtBarStart = 0;
  private _lastCum = 0;
  private _hasCum = false;
  /** The current bar has received at least one tick, so a rollover from it sees the true open. */
  private _streamed = false;
  private _provisional = false;

  public constructor(options: Partial<CandleBuilderOptions> = {}) {
    this._opts = { ...DEFAULT_CANDLE_BUILDER_OPTIONS, ...options };
  }

  /** Seed with the last historical bar so the first live tick continues it. */
  public seed(lastBar: Bar, cumDayVolumeSoFar?: number): void {
    this._current = { ...lastBar };
    this._hasCum = false;
    this._streamed = false;
    this._provisional = false;
    if (cumDayVolumeSoFar !== undefined) {
      this._lastCum = cumDayVolumeSoFar;
      this._cumAtBarStart = cumDayVolumeSoFar - (lastBar.volume ?? 0);
      this._hasCum = true;
    }
  }

  public current(): Bar | null {
    return this._current === null ? null : { ...this._current };
  }

  /** Whether the current bar is provisional; see `CandleUpdate.provisional`. */
  public isProvisional(): boolean {
    return this._current !== null && this._provisional;
  }

  /**
   * Adopt an authoritative bar for the current bucket, typically the broker's
   * history for the bar that is still forming.
   *
   * A provisional bar takes the authoritative open, because its own is the
   * first tick this builder happened to see. Every bar takes the union of the
   * extremes, since both sides observed real prices, and the larger volume,
   * since volume inside a bar only grows. The close stays with the ticks: a
   * history snapshot was taken before the request went out, and a price that
   * jumps backwards on every repair is the one thing a live chart must not do.
   *
   * Returns the reconciled bar, or null when the builder holds no bar for that
   * bucket, in which case the caller decides whether to `seed` instead.
   */
  public reconcile(authoritative: Bar): Bar | null {
    const current = this._current;
    if (current === null || authoritative.time !== current.time) return null;
    const merged = widenBar(current, authoritative);
    if (this._provisional) merged.open = authoritative.open;
    const volume = merged.volume;
    // In day-delta mode the volume is recomputed from the cumulative on every
    // tick, so the baseline moves with it or the next tick would shrink it back.
    if (this._opts.volumeMode === 'day-delta' && this._hasCum && volume !== undefined) {
      this._cumAtBarStart = this._lastCum - volume;
    }
    this._current = merged;
    this._provisional = false;
    return { ...merged };
  }

  /** Bucket-start (bar-open) time for a tick, aligned to the session anchor. */
  public bucketStart(time: UTCSeconds): UTCSeconds {
    const a = this._opts.sessionAnchorSec;
    const i = this._opts.intervalSec;
    return a + Math.floor((time - a) / i) * i;
  }

  /**
   * Feed one tick. Returns the affected bar (mutated current or a fresh one),
   * or `null` if the tick was dropped by the late-tick policy.
   */
  public onTick(tick: Tick): CandleUpdate | null {
    const bs = this.bucketStart(tick.time);

    if (this._current !== null && bs < this._current.time) {
      // Tick older than the current bar's open.
      if (this._opts.lateTickPolicy === 'dropOlderThanPrevBar') return null;
      // foldIntoBar: merge into the current bar.
      this._foldInto(this._current, tick);
      this._streamed = true;
      return { bar: { ...this._current }, isNew: false, provisional: this._provisional };
    }

    if (this._current === null || bs > this._current.time) {
      // Start a new bar. Its open is the true open only when this builder was
      // already streaming the bar before it; otherwise the trades between the
      // bucket's start and this tick were never seen.
      const provisional = this._current === null || !this._streamed;
      const vol = this._volumeForNewBar(tick);
      const bar: Bar = {
        time: bs,
        open: tick.price,
        high: tick.price,
        low: tick.price,
        close: tick.price,
        volume: vol,
      };
      if (tick.oi !== undefined && Number.isFinite(tick.oi)) bar.oi = tick.oi;
      this._current = bar;
      this._streamed = true;
      this._provisional = provisional;
      return { bar: { ...bar }, isNew: true, provisional };
    }

    // Same bucket: update the current bar in place.
    this._foldInto(this._current, tick);
    this._streamed = true;
    return { bar: { ...this._current }, isNew: false, provisional: this._provisional };
  }

  private _foldInto(bar: Bar, tick: Tick): void {
    if (tick.price > bar.high) bar.high = tick.price;
    if (tick.price < bar.low) bar.low = tick.price;
    bar.close = tick.price;
    bar.volume = this._volumeForSameBar(bar, tick);
    // An older history or tick reading cannot masquerade as a current level.
    if (tick.oi !== undefined && Number.isFinite(tick.oi)) bar.oi = tick.oi;
    else delete bar.oi;
  }

  private _volumeForNewBar(tick: Tick): number {
    if (this._opts.volumeMode === 'ltq-sum') return tick.ltq ?? 0;
    const cum = tick.cumDayVolume ?? 0;
    if (!this._hasCum) {
      // First observation: this bar starts at the current cumulative (volume 0).
      this._cumAtBarStart = cum;
    } else if (cum < this._lastCum) {
      // Daily reset (cumulative dropped): the new day's bar starts from 0.
      this._cumAtBarStart = 0;
    } else {
      // Carry from the previous bar's closing cumulative.
      this._cumAtBarStart = this._lastCum;
    }
    this._lastCum = cum;
    this._hasCum = true;
    return Math.max(0, cum - this._cumAtBarStart);
  }

  private _volumeForSameBar(bar: Bar, tick: Tick): number {
    if (this._opts.volumeMode === 'ltq-sum') return (bar.volume ?? 0) + (tick.ltq ?? 0);
    const cum = tick.cumDayVolume ?? 0;
    if (!this._hasCum) {
      // History carries this bar's volume, not the day's cumulative baseline.
      // The first quote establishes that baseline without inventing old trades.
      this._cumAtBarStart = cum - (bar.volume ?? 0);
      this._hasCum = true;
    }
    this._lastCum = cum;
    return Math.max(0, cum - this._cumAtBarStart);
  }
}
