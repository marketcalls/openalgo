/**
 * Volume Profile family (ARCHITECTURE.md §6A, Family C). Volume-at-price grouped
 * into sessions (composite / day / week / month), with a POC and Value Area per
 * session and an optional buy/sell split.
 *
 * The buy/sell split is an honest OHLCV approximation: a bar's whole volume is
 * attributed to buyers when it closed up (`close >= open`) and to sellers when it
 * closed down. True bid/ask delta needs classified trades - see the
 * [Footprint](./footprint.ts). Set `deltaFromBarDirection: false` to keep volume
 * un-split (buy/sell/delta all zero).
 *
 * Visible-range volume profile = pass the visible slice of bars with
 * `session: 'composite'`. Pure and deterministic.
 */
import type { Bar } from '../model/bar';
import { priceBuckets, valueArea } from './profile-model';
import { sessionKey } from './profile-calendar';
import { DEFAULT_TIMEZONE } from '../feed/time';

export type VolumeProfileSession = 'composite' | 'day' | 'week' | 'month';

export interface VolumeProfileFamilyOptions {
  /** Price bucket size. */
  tickSize: number;
  /** Session grouping. `composite` builds one profile over all bars. */
  session: VolumeProfileSession;
  /** Value-area fraction of total volume (0..1). */
  valueAreaPercent: number;
  /** Split each bar's volume into buy/sell by bar direction (close >= open => buy). */
  deltaFromBarDirection: boolean;
  /**
   * IANA zone the day / week / month buckets resolve on. Defaults to
   * `Asia/Kolkata`, so a caller who passes nothing gets what it always did.
   */
  timezone?: string;
}

export const DEFAULT_VOLUME_PROFILE_FAMILY_OPTIONS: VolumeProfileFamilyOptions = {
  tickSize: 0.05,
  session: 'composite',
  valueAreaPercent: 0.7,
  deltaFromBarDirection: true,
  timezone: DEFAULT_TIMEZONE,
};

export interface VolumeProfileLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
  /** buyVolume - sellVolume. */
  delta: number;
}

export interface VolumeProfileSessionResult {
  startTime: number;
  endTime: number;
  /** Price levels, sorted high -> low. */
  levels: VolumeProfileLevel[];
  /** Point of control (price with the most volume). */
  poc: number;
  vah: number;
  val: number;
  totalVolume: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
}

export interface VolumeProfileFamilyResult {
  sessions: VolumeProfileSessionResult[];
  options: VolumeProfileFamilyOptions;
}

interface Acc {
  volume: number;
  buy: number;
  sell: number;
}

/**
 * Volume profiles for `bars`, one per session. Out-of-range options are
 * repaired rather than refused: a `tickSize` not above 0 falls back to the
 * default, and `valueAreaPercent` is clamped to 0..1.
 */
export function computeVolumeProfileSessions(
  bars: readonly Bar[],
  options: Partial<VolumeProfileFamilyOptions> = {},
): VolumeProfileFamilyResult {
  const o: VolumeProfileFamilyOptions = { ...DEFAULT_VOLUME_PROFILE_FAMILY_OPTIONS, ...options };
  const tick = o.tickSize > 0 ? o.tickSize : DEFAULT_VOLUME_PROFILE_FAMILY_OPTIONS.tickSize;
  const vaPct = Math.min(1, Math.max(0, o.valueAreaPercent));
  const zone = o.timezone ?? DEFAULT_TIMEZONE;

  const groups = new Map<number, Bar[]>();
  const order: number[] = [];
  for (const b of bars) {
    const k = sessionKey(b.time, o.session, zone);
    let g = groups.get(k);
    if (g === undefined) { g = []; groups.set(k, g); order.push(k); }
    g.push(b);
  }

  const sessions: VolumeProfileSessionResult[] = [];
  for (const k of order) {
    const g = groups.get(k) as Bar[];
    if (g.length === 0) continue;
    const map = new Map<number, Acc>();
    let totalVolume = 0;
    let buyVolume = 0;
    let sellVolume = 0;

    for (const b of g) {
      const vol = b.volume ?? 0;
      totalVolume += vol;
      const up = b.close >= b.open;
      const barBuy = o.deltaFromBarDirection ? (up ? vol : 0) : 0;
      const barSell = o.deltaFromBarDirection ? (up ? 0 : vol) : 0;
      buyVolume += barBuy;
      sellVolume += barSell;
      const buckets = priceBuckets(b.low, b.high, tick);
      const n = Math.max(1, buckets.length);
      const vShare = vol / n;
      const buyShare = barBuy / n;
      const sellShare = barSell / n;
      for (const price of buckets) {
        let a = map.get(price);
        if (a === undefined) { a = { volume: 0, buy: 0, sell: 0 }; map.set(price, a); }
        a.volume += vShare;
        a.buy += buyShare;
        a.sell += sellShare;
      }
    }

    const levels: VolumeProfileLevel[] = Array.from(map.entries())
      .map(([price, a]) => ({ price, volume: a.volume, buyVolume: a.buy, sellVolume: a.sell, delta: a.buy - a.sell }))
      .sort((x, y) => y.price - x.price);

    if (levels.length === 0) continue;

    // POC + value area by volume, against the session's traded volume.
    // Neither levels nor the session's bars are empty, so the indices
    // `valueArea` hands back are rows of `levels`.
    const va = valueArea(levels.map((l) => l.volume), totalVolume * vaPct);
    sessions.push({
      startTime: g[0]!.time,
      endTime: g[g.length - 1]!.time,
      levels,
      poc: levels[va.poc]!.price,
      vah: levels[va.upper]!.price,
      val: levels[va.lower]!.price,
      totalVolume,
      buyVolume,
      sellVolume,
      delta: buyVolume - sellVolume,
    });
  }

  // Echo the zone actually used, so a caller can read back what it resolved to.
  return { sessions, options: { ...o, timezone: zone } };
}
