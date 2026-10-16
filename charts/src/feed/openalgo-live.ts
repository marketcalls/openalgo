/**
 * Composed OpenAlgo live data feed. Implements the full
 * `DataFeed` contract by combining history (REST), live ticks (WS), and a
 * per-subscription aggregator, so `subscribeBars()` actually delivers live
 * interval bars instead of being a no-op trap.
 */
import type { Bar } from '../model/bar';
import type { BarsRequest, BarSubscriptionOptions, DataFeed, LiveBarMeta, MarketDepth, SymbolMatch, SymbolSearchRequest, UnsubscribeFn } from './types';
import { OpenAlgoDataFeed, type OpenAlgoConfig } from './openalgo-rest';
import { OpenAlgoWsFeed, type OpenAlgoWsConfig, type SocketFactory, type LtpEvent, type WsMode } from './openalgo-ws';
import { CandleBuilder, type Tick, type VolumeMode } from './candle-builder';
import { resolveInterval, isTimeBucketed, type Bucketing, type IntervalBucketing } from './intervals';
import { TickBarAggregator } from './tick-aggregator';
import { dataVariantError, unsupportedDataVariant } from './data-variant';
import type { LooseOptional } from '../helpers/types';

export interface OpenAlgoLiveConfig extends OpenAlgoConfig {
  /** WS proxy URL, e.g. ws://127.0.0.1:8765. */
  wsUrl: string;
  /**
   * Volume accounting for the live candle builder (default 'ltq-sum').
   *
   * 'day-delta' also selects the wire mode: a cumulative day volume only exists
   * on the Quote stream, so this feed subscribes Quote rather than LTP for it.
   */
  volumeMode?: VolumeMode;
  /**
   * Zone calendar intervals bucket in (default IST). Should be the chart's
   * configured timezone: a monthly bar opens at local midnight on the first,
   * and that instant differs by exchange.
   */
  timezone?: string;
  /**
   * Default book depth for `subscribeDepth`, broker-dependent (5/20/30/50).
   * Omitted leaves it to the broker, which is what this feed always did.
   * A per-call `opts.depthLevel` overrides it.
   */
  depthLevel?: number;
  /** Inject a custom socket (tests, React Native, non-browser runtimes). */
  socketFactory?: SocketFactory;
  /**
   * Socket policy, passed straight to `OpenAlgoWsFeed`. Present because the
   * handshake gate, the liveness watchdog and the backoff all have escape
   * hatches that were otherwise unreachable through this composed feed: a proxy
   * build that answers nothing needs `auth: { requireAck: false }`, and a host
   * with no way to say so would just see a chart that never receives a tick.
   */
  reconnect?: OpenAlgoWsConfig['reconnect'];
  auth?: OpenAlgoWsConfig['auth'];
  heartbeat?: OpenAlgoWsConfig['heartbeat'];
}

/**
 * One remote subscription and the consumers depending on it.
 *
 * The socket keys subscriptions by mode/symbol/exchange, so two panes on the
 * same symbol share one. Without a count, the first pane to close sent the
 * unsubscribe and the second went silent while still believing it was live.
 */
interface SubEntry {
  count: number;
  /** Depth level currently on the wire: the largest any attached consumer asked for. */
  level?: number | undefined;
}

/**
 * Seconds per bar for a fixed-length interval code, e.g. `D` -> 86400,
 * `1m` -> 60, `1h` -> 3600.
 *
 * Throws `UnknownIntervalError` for a code nothing recognises, and a plain
 * error for a calendar or count-driven code, which has no seconds to give.
 * It used to answer 60 for both, which drew minute bars under whatever label
 * the caller thought it had asked for.
 *
 * Prefer `resolveInterval()` and `bucketStartOf()`: they cover every registered
 * code, not just the ones that happen to have a fixed length.
 */
export function intervalToSeconds(interval: string): number {
  const { bucketing } = resolveInterval(interval);
  if (bucketing.mode !== 'interval') {
    throw new Error(
      `openalgo-charts: interval "${interval}" is ${bucketing.mode}-bucketed and has no fixed length. `
      + 'Use resolveInterval() and bucketStartOf() instead of intervalToSeconds().',
    );
  }
  return bucketing.seconds;
}

/**
 * Per-tick quantity for the aggregator path, honouring the configured volume
 * mode. `day-delta` feeds arrive as a cumulative day total, so the bar wants
 * the difference; a total that went backwards is the daily reset, and the new
 * value is then the first delta of the new day.
 */
function volumeDeltaReader(mode: VolumeMode, cumSoFar?: number): (e: LtpEvent) => number {
  if (mode === 'ltq-sum') return (e) => e.ltq ?? 0;
  let lastCum: number | null = cumSoFar ?? null;
  return (e) => {
    const cum = e.volume ?? 0;
    const delta = lastCum === null ? 0 : cum < lastCum ? cum : cum - lastCum;
    lastCum = cum;
    return Math.max(0, delta);
  };
}

export class OpenAlgoLiveDataFeed implements DataFeed {
  private readonly _rest: OpenAlgoDataFeed;
  private readonly _ws: OpenAlgoWsFeed;
  private readonly _volumeMode: VolumeMode;
  private readonly _timezone: string | undefined;
  private readonly _depthLevel: number | undefined;
  /** Wire mode ticks arrive on, decided once by `volumeMode`. */
  private readonly _tickMode: WsMode;
  /** Reference counts per `mode:symbol:exchange`, so one consumer leaving cannot cut the rest off. */
  private readonly _subs = new Map<string, SubEntry>();

  public constructor(config: OpenAlgoLiveConfig) {
    this._rest = new OpenAlgoDataFeed(config);
    this._ws = new OpenAlgoWsFeed({
      url: config.wsUrl, apiKey: config.apiKey, socketFactory: config.socketFactory,
      reconnect: config.reconnect, auth: config.auth, heartbeat: config.heartbeat,
    });
    this._volumeMode = config.volumeMode ?? 'ltq-sum';
    this._timezone = config.timezone;
    this._depthLevel = config.depthLevel;
    // LTP frames carry a price and a last-traded quantity, nothing else, so a
    // day-delta builder subscribed to LTP diffs a volume that never arrives and
    // every bar comes out at zero. The cumulative day total is a Quote-mode
    // field, which is what the documented option always meant.
    this._tickMode = this._volumeMode === 'day-delta' ? 'Quote' : 'LTP';
    this._ws.connect();
  }

  /**
   * Take a share in the remote subscription for this stream, subscribing only
   * if nobody held one, and hand back a release that unsubscribes remotely only
   * when the last holder lets go.
   *
   * Depth is negotiated upward: a consumer needing 20 levels re-subscribes
   * at 20 rather than living with the 5 an earlier one asked for. It is never
   * negotiated back down while consumers remain, because shrinking a book under
   * a consumer that is still reading it is the failure this method exists to
   * prevent, and the extra levels cost only bandwidth. The high-water mark is
   * per entry, so it resets when the last holder leaves.
   */
  private _acquire(mode: WsMode, symbol: string, exchange: string, depthLevel?: number): UnsubscribeFn {
    const key = `${mode}:${symbol}:${exchange}`;
    const held = this._subs.get(key);
    if (held === undefined) {
      this._subs.set(key, { count: 1, level: depthLevel });
      this._ws.subscribe(mode, symbol, exchange, depthLevel);
    } else {
      held.count += 1;
      if (depthLevel !== undefined && (held.level === undefined || depthLevel > held.level)) {
        held.level = depthLevel;
        this._ws.subscribe(mode, symbol, exchange, depthLevel);
      }
    }
    let released = false;
    return () => {
      // Idempotent: a host that calls its unsubscribe twice must not spend a
      // second consumer's share and take the stream away from them.
      if (released) return;
      released = true;
      const entry = this._subs.get(key);
      if (entry === undefined) return;
      entry.count -= 1;
      if (entry.count > 0) return;
      this._subs.delete(key);
      this._ws.unsubscribe(mode, symbol, exchange);
    };
  }

  public getBars(req: BarsRequest): Promise<Bar[]> {
    return this._rest.getBars(req);
  }

  public searchSymbols(request: SymbolSearchRequest): Promise<SymbolMatch[]> {
    return this._rest.searchSymbols(request);
  }

  /**
   * Live bars: WS tick -> aggregator -> onBar (mutated/append bar). The tick
   * stream is LTP, or Quote when `volumeMode` is 'day-delta' and the bar
   * therefore needs a cumulative day volume.
   *
   * Fixed intervals go through `CandleBuilder`, which carries the late-tick
   * policy; calendar, tick-count and volume intervals go through
   * `TickBarAggregator`, which is the one that knows those boundaries.
   *
   * Pass `opts.seedFrom` (the last history bar) to continue that bar's bucket
   * seamlessly instead of starting a fresh one, and `opts.cumDayVolumeSoFar` so
   * a `day-delta` builder diffs against the right baseline. Seeding applies to
   * time-bucketed intervals: a count-driven bar cannot resume a historical one.
   */
  public subscribeBars(
    req: BarsRequest,
    onBar: (bar: Bar, meta?: LiveBarMeta) => void,
    opts?: BarSubscriptionOptions,
  ): UnsubscribeFn {
    // Resolve up front: a bad interval code fails here, at subscribe time, and
    // not silently on every tick for the life of the subscription. The stream
    // carries one series per instrument, so another variant fails here too.
    const unsupported = unsupportedDataVariant(undefined, req.variant);
    if (unsupported) throw dataVariantError(unsupported, req.variant);
    const { bucketing } = resolveInterval(req.interval);
    const onEvent = bucketing.mode === 'interval'
      ? this._candleReader(bucketing, onBar, opts)
      : this._aggregatorReader(bucketing, onBar, opts);

    const off = this._ws.onLtp((e) => {
      // Match both symbol and exchange (a broker can multiplex venues on one socket).
      if (e.symbol !== req.symbol) return;
      if (e.exchange && req.exchange && e.exchange !== req.exchange) return;
      onEvent(e);
    });
    const offControl = opts?.onResync ? this._ws.onControl((message) => {
      if (message.type === 'client_warning' && message.code === 'STREAM_RESYNC') opts.onResync?.();
    }) : undefined;
    const release = this._acquire(this._tickMode, req.symbol, req.exchange);
    return () => { off(); offControl?.(); release(); };
  }

  /** A broker may omit the tick timestamp; never bucket at the epoch, use now. */
  private static _tickTime(e: LtpEvent): number {
    return e.timeSec && e.timeSec > 0 ? e.timeSec : Math.floor(Date.now() / 1000);
  }

  private _candleReader(
    bucketing: IntervalBucketing,
    onBar: (bar: Bar, meta?: LiveBarMeta) => void,
    opts?: { seedFrom?: Bar; cumDayVolumeSoFar?: number },
  ): (e: LtpEvent) => void {
    // The anchor travels with the interval, and dropping it put a
    // session-anchored code back on the epoch grid: hourly bars anchored to a
    // 09:15 open then formed at 03:00 UTC live and 03:45 UTC in history, one
    // interval disagreeing with itself. Same rule `bucketStartOf` applies to
    // the codes the aggregator path handles.
    const builder = new CandleBuilder({
      intervalSec: bucketing.seconds,
      sessionAnchorSec: bucketing.anchorSec ?? 0,
      volumeMode: this._volumeMode,
    });
    if (opts?.seedFrom) builder.seed(opts.seedFrom, opts.cumDayVolumeSoFar);
    return (e) => {
      // cumDayVolume is only consumed in 'day-delta' mode; harmless otherwise.
      const u = builder.onTick({ // a quantity the frame lacks is undefined, which the builder reads as absent
        time: OpenAlgoLiveDataFeed._tickTime(e), price: e.ltp, ltq: e.ltq, cumDayVolume: e.volume,
      } satisfies LooseOptional<Tick> as Tick);
      // A bucket the builder opened without having streamed the one before it
      // carries only the ticks it saw; the consumer holds history for the rest.
      if (u !== null) onBar(u.bar, u.provisional ? { provisional: true } : undefined);
    };
  }

  private _aggregatorReader(
    bucketing: Exclude<Bucketing, IntervalBucketing>,
    onBar: (bar: Bar, meta?: LiveBarMeta) => void,
    opts?: { seedFrom?: Bar; cumDayVolumeSoFar?: number },
  ): (e: LtpEvent) => void {
    const agg = new TickBarAggregator(bucketing, { timezone: this._timezone });
    if (opts?.seedFrom && isTimeBucketed(bucketing)) agg.seed(opts.seedFrom);
    const qtyOf = volumeDeltaReader(this._volumeMode, opts?.cumDayVolumeSoFar);
    return (e) => {
      const u = agg.onTick({ time: OpenAlgoLiveDataFeed._tickTime(e), price: e.ltp, qty: qtyOf(e) });
      onBar(u.bar);
    };
  }

  /**
   * Live book. `opts.depthLevel` requests a book depth (broker-dependent:
   * 5/20/30/50), falling back to the feed's configured default and then to
   * whatever the broker sends unasked, which is what this method always did.
   * The socket has accepted a depth level all along; only the composed feed had
   * no way to name one.
   */
  public subscribeDepth(
    req: BarsRequest,
    onDepth: (depth: MarketDepth) => void,
    opts?: { depthLevel?: number },
  ): UnsubscribeFn {
    const off = this._ws.onDepth((symbol, ex, depth) => {
      if (symbol !== req.symbol) return;
      if (ex && req.exchange && ex !== req.exchange) return;
      onDepth(depth);
    });
    const release = this._acquire('Depth', req.symbol, req.exchange, opts?.depthLevel ?? this._depthLevel);
    return () => { off(); release(); };
  }

  public close(): void {
    // Drop the counts with the socket: a feed reopened after close() holds no
    // remote subscription, and a stale entry would suppress the resubscribe.
    this._subs.clear();
    this._ws.close();
  }
}
