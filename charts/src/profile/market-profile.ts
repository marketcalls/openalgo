/**
 * Market Profile / TPO (Time Price Opportunity): ARCHITECTURE.md §6A, Family C.
 *
 * Groups bars into sessions (day / week / month / composite), splits each
 * session into fixed-length time blocks ("periods", one letter each), and counts
 * how many periods traded at each price. Derives the Point of Control, Value
 * Area, Initial Balance, single prints, tails, range extension, day / open type
 * and the developing POC-VA track, plus volume at price.
 *
 * Pure and deterministic (no Date.now / Math.random), so it is fully
 * unit-testable and derivable from intraday OHLCV bars alone.
 */
import type { Bar } from '../model/bar';
import { bucketPrice, priceBuckets, valueArea } from './profile-model';
import { partsIn, minuteOfDay, sessionKey } from './profile-calendar';
import { DEFAULT_TIMEZONE, zonedWallClockToUtcSeconds } from '../feed/time';

export type MarketProfileSession = 'day' | 'week' | 'month' | 'composite';

/**
 * A session window in minutes from local midnight. `end <= start` means the
 * window crosses midnight (an overnight session), which is why the test below is
 * a wrap-aware range check rather than a plain `>= start && < end`.
 *
 * "Local" is `zone` when the window names one, and `MarketProfileOptions.timezone`
 * otherwise. A window that names its own zone selects the same real instants
 * whatever the rest of the profile is read on.
 */
export interface SessionWindow {
  /** Minutes from midnight, 0..1439. Equal start and end means all hours. */
  startMinute: number;
  endMinute: number;
  /** Shown on the chart when the renderer draws a session label. */
  name?: string;
  /**
   * IANA zone the two minute counts are written in. Omitted means "read them on
   * `MarketProfileOptions.timezone`", which is what a caller hand-writing a
   * window for their own market wants. This module is a pure calculation and is
   * never handed the chart, so a host that wants the two to agree passes
   * `chart.timezone()` into the options.
   */
  zone?: string;
}

/**
 * Named windows, each written in the clock of the market it belongs to.
 *
 * The zone is half the definition, not decoration. `us-regular` as a bare 1140
 * was unreadable as "09:30 New York", and it silently froze the US session at
 * whatever offset New York happened to have on the day the number was written,
 * so it opened an hour early for the five winter months. Written as 09:30 in
 * America/New_York it follows the exchange through both changeovers.
 *
 * The bands are the same partition of the day as before, re-expressed: London
 * and New York keep exactly the instants they selected under DST (where the old
 * numbers were right) and gain the hour the old numbers lost in winter.
 *
 * `all-hours` names no zone because it never reads one: an empty window
 * (`start === end`) short-circuits before any clock is consulted.
 */
export const TRADING_HOURS: Record<string, SessionWindow> = {
  'all-hours': { startMinute: 0, endMinute: 0, name: 'All Hours' },
  'india': { startMinute: 9 * 60 + 15, endMinute: 15 * 60 + 30, zone: 'Asia/Kolkata', name: 'India' },
  'asia': { startMinute: 9 * 60, endMinute: 15 * 60, zone: 'Asia/Tokyo', name: 'Asia' },
  'london': { startMinute: 7 * 60, endMinute: 13 * 60, zone: 'Europe/London', name: 'London' },
  'new-york': { startMinute: 8 * 60, endMinute: 15 * 60 + 30, zone: 'America/New_York', name: 'New York' },
  'us-regular': { startMinute: 9 * 60 + 30, endMinute: 16 * 60, zone: 'America/New_York', name: 'US Regular' },
};

export interface MarketProfileOptions {
  /**
   * Instrument tick size: the finest price increment (Nifty: 0.1). One that
   * is not above 0 falls back to the default, 0.05.
   */
  tickSize: number;
  /**
   * Ticks per TPO row, so row height is `tickSize * rowTicks`. This is the
   * multiplier a trader thinks in: 2-point rows on a 0.1-tick instrument is
   * `2 / 0.1 = 20`. Keeping it separate from `tickSize` means widening rows
   * never means lying about the instrument's real tick.
   */
  rowTicks: number;
  /** Session grouping. `composite` builds one profile over all bars. */
  session: MarketProfileSession;
  /** TPO period length in minutes: one letter per period. */
  blockMinutes: number;
  /** Value-area fraction of total TPOs (0..1). */
  valueAreaPercent: number;
  /** Number of opening periods that form the Initial Balance. */
  initialBalancePeriods: number;
  /** Restrict each session to this window. Bars outside it are dropped. */
  window?: SessionWindow;
  /**
   * IANA zone the session / day / week / month calendar resolves on. Defaults to
   * `Asia/Kolkata`, so a caller who passes nothing gets what it always did.
   *
   * A `window` that names its own zone overrides this for both the window test
   * and the bucketing, because a session must not be cut in half by the clock
   * someone happens to be reading the chart on.
   */
  timezone?: string;
  /**
   * Merge consecutive sessions into one profile (1 = off). With
   * `session: 'day'`, 5 gives a rolling weekly composite.
   */
  compositeSessions: number;
  /**
   * Minimum run of consecutive single prints that promotes a buying / selling
   * tail at a session extreme. 0 disables tail detection.
   */
  tailEdges: number;
}

export const DEFAULT_MARKET_PROFILE_OPTIONS: MarketProfileOptions = {
  tickSize: 0.05,
  rowTicks: 1,
  session: 'day',
  blockMinutes: 30,
  valueAreaPercent: 0.7,
  initialBalancePeriods: 2,
  compositeSessions: 1,
  tailEdges: 0,
  timezone: DEFAULT_TIMEZONE,
};

/**
 * Ticks per row for a desired row height: `rowTicksFor(2, 0.1)` is 20.
 * Saves callers from writing the division (and from off-by-one float dust).
 */
export function rowTicksFor(rowSize: number, tickSize: number): number {
  if (!(rowSize > 0) || !(tickSize > 0)) return 1;
  return Math.max(1, Math.round(rowSize / tickSize));
}

export interface MarketProfileLevel {
  price: number;
  /** Distinct periods (TPOs) that traded at this price. */
  count: number;
  /** Period letters at this price, in period order (e.g. `"ABF"`). */
  letters: string;
  /** Period indices at this price: the renderer colours blocks from these. */
  periods: number[];
  /** Volume traded at this price (each bar's volume split across its range). */
  volume: number;
}

/** One time block within a session. */
export interface MarketProfilePeriod {
  /** 0-based index within the session. */
  index: number;
  letter: string;
  /** UTC seconds covered by this block. */
  startTime: number;
  endTime: number;
  high: number;
  low: number;
  volume: number;
}

/** POC / value area as they stood at the close of each period. */
export interface DevelopingValue {
  periodIndex: number;
  /** UTC seconds at which this snapshot became current. */
  time: number;
  poc: number;
  vah: number;
  val: number;
}

/**
 * Classic market-profile day types.
 * `normal`: a wide initial balance the rest of the day stays inside.
 * `normal-variation`: range extends to roughly 1.5-2x the initial balance.
 * `trend`: one-way extension, small IB relative to the range.
 * `double-distribution`: two separated high-volume nodes with a thin middle.
 * `neutral`: extension on both sides of the initial balance.
 */
export type DayType = 'normal' | 'normal-variation' | 'trend' | 'double-distribution' | 'neutral';

/**
 * How the session opened.
 * `drive`: opens at an extreme and runs one way without looking back.
 * `test-drive`: probes one side first, then drives the other.
 * `rejection-reverse`: pushes one way, fails, reverses back through the open.
 * `auction`: rotates around the open with no conviction.
 */
export type OpenType = 'drive' | 'test-drive' | 'rejection-reverse' | 'auction';

export interface MarketProfileSessionResult {
  /** UTC seconds of the session's first and last bar. */
  startTime: number;
  endTime: number;
  /** Window name when one was applied: the renderer's session label. */
  label?: string | undefined;
  /** Price levels, sorted high -> low. */
  levels: MarketProfileLevel[];
  /** Point of control (price with the most TPOs). */
  poc: number;
  /** Value-area high / low. */
  vah: number;
  val: number;
  /** Session extremes. */
  high: number;
  low: number;
  /** The session's opening and closing trade price. */
  open: number;
  close: number;
  /** Number of periods (letters) in the session. */
  periods: number;
  /** Per-period detail, in order. */
  periodDetail: MarketProfilePeriod[];
  /** Initial balance: price range of the opening `initialBalancePeriods`. */
  initialBalance: { high: number; low: number };
  /** How far price extended beyond the initial balance each way (0 when none). */
  rangeExtension: { up: number; down: number };
  /** Prices that printed a single TPO away from the session extremes. */
  singlePrints: number[];
  /** Runs of single prints at the extremes, when `tailEdges` promotes them. */
  buyingTail: { high: number; low: number } | null;
  sellingTail: { high: number; low: number } | null;
  /** True when the session high / low printed more than one TPO (weak extreme). */
  poorHigh: boolean;
  poorLow: boolean;
  /** POC / VA after each period closed: the developing track. */
  developing: DevelopingValue[];
  dayType: DayType;
  openType: OpenType;
  /** Volume-weighted POC (most volume, as opposed to the most time). */
  volumePoc: number;
  /** Total traded volume in the session. */
  totalVolume: number;
}

export interface MarketProfileResult {
  sessions: MarketProfileSessionResult[];
  options: MarketProfileOptions;
}

/** Period index -> TPO letter (`A`-`Z`, then `a`-`z`, then wraps). */
export function tpoLetter(period: number): string {
  const m = ((period % 52) + 52) % 52;
  return m < 26 ? String.fromCharCode(65 + m) : String.fromCharCode(97 + (m - 26));
}

/**
 * The clock a window's minutes are counted on: its own when it names one, the
 * chart's configured zone otherwise.
 *
 * A preset carrying its own zone is what makes it independent of the display.
 * Viewing an NSE chart with the display set to New York must not drag the Indian
 * session nine and a half hours along the tape: the window still selects
 * 09:15-15:30 in Kolkata and the sessions it forms still break on the Indian
 * calendar day. Only the labels move.
 */
function windowZone(w: SessionWindow | undefined, zone: string): string {
  return w?.zone ?? zone;
}

/**
 * Wrap-aware window test, so an overnight session is one window, not two.
 *
 * `zone` is the chart's configured timezone and is only consulted when the
 * window does not name one of its own.
 */
export function inWindow(utcSeconds: number, w: SessionWindow, zone: string = DEFAULT_TIMEZONE): boolean {
  if (w.startMinute === w.endMinute) return true; // all hours
  const m = minuteOfDay(utcSeconds, windowZone(w, zone));
  return w.startMinute < w.endMinute
    ? m >= w.startMinute && m < w.endMinute
    : m >= w.startMinute || m < w.endMinute;
}

/**
 * UTC seconds of the window's opening wall-clock time, `dayOffset` local days
 * from the day holding `utcSeconds`.
 *
 * Wall clock rather than "local midnight plus startMinute seconds": on a
 * changeover day the two are an hour apart, and this anchor decides which letter
 * every bar in the session gets. Runs once per session, so it stays on the
 * general path.
 */
function windowOpenOn(utcSeconds: number, w: SessionWindow, zone: string, dayOffset: number): number {
  const p = partsIn(utcSeconds, zone);
  // Step in calendar days through Date's own overflow, so the last of a month
  // rolls into the first of the next instead of landing on the 32nd.
  const civil = new Date(Date.UTC(p.year, p.month - 1, p.day + dayOffset));
  return zonedWallClockToUtcSeconds(
    civil.getUTCFullYear(), civil.getUTCMonth() + 1, civil.getUTCDate(),
    Math.floor(w.startMinute / 60), w.startMinute % 60, 0, zone,
  );
}

/**
 * UTC seconds at which the session holding `time` opened: today's window open
 * when that has passed, otherwise yesterday's, so an overnight session keeps one
 * anchor across midnight. Tier-internal; the footprint letters its bars from it
 * so they agree with the market profile's periods.
 */
export function sessionOpen(time: number, w: SessionWindow, zone: string = DEFAULT_TIMEZONE): number {
  const cal = windowZone(w, zone);
  const today = windowOpenOn(time, w, cal, 0);
  return today <= time ? today : windowOpenOn(time, w, cal, -1);
}

/** Internal identity shared by the renderer's per-session display overrides. */
export function profileSessionIdentity(time: number, options: MarketProfileOptions): string {
  const zone = windowZone(options.window, options.timezone ?? DEFAULT_TIMEZONE);
  return [options.session, options.compositeSessions, zone,
    options.window?.startMinute ?? '', options.window?.endMinute ?? '',
    sessionKey(time, options.session, zone, options.window)].join('|');
}

interface LevelAcc {
  periods: Set<number>;
  volume: number;
}

/**
 * POC + value area over a level list, by TPO count. Both callers pass a
 * non-empty list, so the indices `valueArea` hands back are rows of it.
 */
function pocAndValueArea(
  levels: readonly { price: number; count: number }[],
  vaPct: number,
): { poc: number; vah: number; val: number } {
  const counts = levels.map((l) => l.count);
  const va = valueArea(counts, counts.reduce((s, c) => s + c, 0) * vaPct);
  return { poc: levels[va.poc]!.price, vah: levels[va.upper]!.price, val: levels[va.lower]!.price };
}

/** Length of the run of consecutive single prints from `from`, walking `step`. */
function tailRun(levels: readonly MarketProfileLevel[], from: number, step: number): number {
  let n = 0;
  for (let i = from; i >= 0 && i < levels.length; i += step) {
    if (levels[i]!.count !== 1) break;
    n++;
  }
  return n;
}

function classifyDay(
  ib: { high: number; low: number },
  high: number,
  low: number,
  ext: { up: number; down: number },
  levels: readonly MarketProfileLevel[],
  poc: number,
): DayType {
  const ibRange = ib.high - ib.low;
  const range = high - low;
  if (range <= 0 || ibRange <= 0) return 'normal';
  if (ext.up > 0 && ext.down > 0) return 'neutral';
  // A thin middle between two busy nodes is a double distribution, not a trend.
  const pocIdx = levels.findIndex((l) => l.price === poc);
  if (pocIdx >= 0 && levels.length >= 5) {
    const peak = levels[pocIdx]!.count;
    let minMid = Infinity;
    let second = 0;
    for (let i = 0; i < levels.length; i++) {
      const d = Math.abs(i - pocIdx);
      if (d > 1) second = Math.max(second, levels[i]!.count);
      if (d > 0 && d <= Math.max(2, Math.floor(levels.length / 4))) minMid = Math.min(minMid, levels[i]!.count);
    }
    if (second >= peak * 0.7 && minMid <= peak * 0.35) return 'double-distribution';
  }
  const ratio = range / ibRange;
  if (ratio >= 2.5) return 'trend';
  if (ratio >= 1.4) return 'normal-variation';
  return 'normal';
}

function classifyOpen(
  open: number,
  first: MarketProfilePeriod | undefined,
  second: MarketProfilePeriod | undefined,
  high: number,
  low: number,
): OpenType {
  if (first === undefined) return 'auction';
  const range = high - low;
  if (range <= 0) return 'auction';
  const firstRange = first.high - first.low;
  const pos = (open - low) / range;
  // Opening on an extreme and holding a tight first period is a drive.
  if ((pos > 0.7 || pos < 0.3) && firstRange <= range * 0.35) return 'drive';
  if (second !== undefined) {
    const probedDown = first.low < open - firstRange * 0.25;
    const probedUp = first.high > open + firstRange * 0.25;
    if ((probedDown && second.high > first.high) || (probedUp && second.low < first.low)) return 'test-drive';
    if ((probedUp && second.low < open) || (probedDown && second.high > open)) return 'rejection-reverse';
  }
  return 'auction';
}

/** The repaired options one computation reads, resolved once. */
interface Resolved {
  /** The row grid, not the instrument grid: this is what TPOs are counted on. */
  row: number;
  blockSec: number;
  vaPct: number;
  ibPeriods: number;
  tailEdges: number;
  win: SessionWindow | undefined;
  /**
   * One clock for the whole profile: the window's when it names one, so a
   * windowed session stays a session however the chart is displayed.
   */
  cal: string;
}

/**
 * Market profiles for `bars`, one per session (see {@link MarketProfileOptions}).
 * Out-of-range options are repaired rather than refused: a `tickSize` not
 * above 0 falls back to 0.05; `rowTicks`, `initialBalancePeriods` and
 * `compositeSessions` are floored to a whole number of at least 1;
 * `blockMinutes` is rounded to whole seconds, at least one; and
 * `valueAreaPercent` is clamped to 0..1. `result.options` echoes the repaired
 * `rowTicks`. The footprint, which shares `rowTicks`, throws instead.
 */
export function computeMarketProfile(
  bars: readonly Bar[],
  options: Partial<MarketProfileOptions> = {},
): MarketProfileResult {
  const o: MarketProfileOptions = { ...DEFAULT_MARKET_PROFILE_OPTIONS, ...options };
  const baseTick = o.tickSize > 0 ? o.tickSize : DEFAULT_MARKET_PROFILE_OPTIONS.tickSize;
  const rowTicks = Math.max(1, Math.floor(o.rowTicks));
  const zone = o.timezone ?? DEFAULT_TIMEZONE;
  const r: Resolved = {
    row: baseTick * rowTicks,
    blockSec: Math.max(1, Math.round(o.blockMinutes * 60)),
    vaPct: Math.min(1, Math.max(0, o.valueAreaPercent)),
    ibPeriods: Math.max(1, Math.floor(o.initialBalancePeriods)),
    tailEdges: o.tailEdges,
    win: o.window,
    cal: windowZone(o.window, zone),
  };
  const sessions: MarketProfileSessionResult[] = [];
  for (const g of groupSessions(bars, o, zone, r.cal)) {
    const session = buildSession(g, r);
    if (session !== null) sessions.push(session);
  }
  // Echo the zone actually used, so a caller can read back what it resolved to.
  return { sessions, options: { ...o, rowTicks, timezone: zone } };
}

/**
 * The bars of each profile, in first-seen order (bars assumed ascending):
 * grouped by session key on `cal`, less those outside the window, and with
 * `compositeSessions` consecutive keys folded into one.
 */
function groupSessions(bars: readonly Bar[], o: MarketProfileOptions, zone: string, cal: string): Bar[][] {
  const win = o.window;
  const merge = Math.max(1, Math.floor(o.compositeSessions));
  const groups = new Map<number, Bar[]>();
  const order: number[] = [];
  for (const b of bars) {
    if (win !== undefined && !inWindow(b.time, win, zone)) continue;
    const k = sessionKey(b.time, o.session, cal, win);
    let g = groups.get(k);
    if (g === undefined) { g = []; groups.set(k, g); order.push(k); }
    g.push(b);
  }

  // Rolling composite: fold each key together with the `merge - 1` before it.
  const bucketsOfBars: Bar[][] = [];
  if (merge > 1 && o.session !== 'composite') {
    for (let i = 0; i < order.length; i += merge) {
      const slice: Bar[] = [];
      for (let j = i; j < Math.min(i + merge, order.length); j++) {
        slice.push(...(groups.get(order[j]!) as Bar[]));
      }
      bucketsOfBars.push(slice);
    }
  } else {
    for (const k of order) bucketsOfBars.push(groups.get(k) as Bar[]);
  }
  return bucketsOfBars;
}

/** One session's profile and its analytics, or null when it holds no row. */
function buildSession(g: readonly Bar[], r: Resolved): MarketProfileSessionResult | null {
  // From here on g has a first and a last bar, and once `levels` is known
  // not to be empty, a first and a last level; loop indexes stay in range.
  if (g.length === 0) return null;
  // Anchor periods to the session's own window start, not the first bar:
  // otherwise a session whose first bar arrives late shifts every letter.
  const first = g[0]!.time;
  let anchor = first;
  const win = r.win;
  if (win !== undefined && win.startMinute !== win.endMinute) anchor = sessionOpen(first, win, r.cal);

  const map = new Map<number, LevelAcc>();
  const byPeriod = new Map<number, MarketProfilePeriod>();
  let maxPeriod = 0;
  let ibHigh = -Infinity;
  let ibLow = Infinity;
  let totalVolume = 0;
  let high = -Infinity;
  let low = Infinity;

  for (const b of g) {
    const period = Math.max(0, Math.floor((b.time - anchor) / r.blockSec));
    if (period > maxPeriod) maxPeriod = period;
    if (period < r.ibPeriods) { ibHigh = Math.max(ibHigh, b.high); ibLow = Math.min(ibLow, b.low); }
    high = Math.max(high, b.high);
    low = Math.min(low, b.low);
    const vol = b.volume ?? 0;
    totalVolume += vol;

    let p = byPeriod.get(period);
    if (p === undefined) {
      p = { index: period, letter: tpoLetter(period), startTime: b.time, endTime: b.time,
        high: b.high, low: b.low, volume: 0 };
      byPeriod.set(period, p);
    }
    p.endTime = b.time;
    p.high = Math.max(p.high, b.high);
    p.low = Math.min(p.low, b.low);
    p.volume += vol;

    const cells = priceBuckets(b.low, b.high, r.row);
    const vShare = vol / Math.max(1, cells.length);
    for (const price of cells) {
      let a = map.get(price);
      if (a === undefined) { a = { periods: new Set<number>(), volume: 0 }; map.set(price, a); }
      a.periods.add(period);
      a.volume += vShare;
    }
  }
  const periodDetail = Array.from(byPeriod.values()).sort((a, b) => a.index - b.index);

  const levels: MarketProfileLevel[] = Array.from(map.entries())
    .map(([price, a]) => {
      const ps = Array.from(a.periods).sort((x, y) => x - y);
      return { price, count: ps.length, periods: ps, volume: a.volume,
        letters: ps.map(tpoLetter).join('') };
    })
    .sort((x, y) => y.price - x.price);
  if (levels.length === 0) return null;

  const va = pocAndValueArea(levels, r.vaPct);

  const singlePrints: number[] = [];
  for (let i = 1; i < levels.length - 1; i++) if (levels[i]!.count === 1) singlePrints.push(levels[i]!.price);

  const ib = {
    high: Number.isFinite(ibHigh) ? ibHigh : levels[0]!.price,
    low: Number.isFinite(ibLow) ? ibLow : levels[levels.length - 1]!.price,
  };
  const rangeExtension = { up: Math.max(0, high - ib.high), down: Math.max(0, ib.low - low) };

  let volumePoc = levels[0]!.price;
  let maxVol = -1;
  for (const l of levels) if (l.volume > maxVol) { maxVol = l.volume; volumePoc = l.price; }

  return {
    startTime: first,
    endTime: g[g.length - 1]!.time,
    label: win?.name,
    levels,
    poc: va.poc, vah: va.vah, val: va.val,
    high, low,
    open: g[0]!.open,
    close: g[g.length - 1]!.close,
    periods: maxPeriod + 1,
    periodDetail,
    initialBalance: ib,
    rangeExtension,
    singlePrints,
    ...tailsOf(levels, r.tailEdges),
    poorHigh: levels[0]!.count > 1,
    poorLow: levels[levels.length - 1]!.count > 1,
    developing: developingValues(levels, periodDetail, r.vaPct),
    dayType: classifyDay(ib, high, low, rangeExtension, levels, va.poc),
    openType: classifyOpen(g[0]!.open, periodDetail[0], periodDetail[1], high, low),
    volumePoc,
    totalVolume,
  };
}

/** Developing POC / VA: the profile recounted with only the periods closed so far. */
function developingValues(
  levels: readonly MarketProfileLevel[], periodDetail: readonly MarketProfilePeriod[], vaPct: number,
): DevelopingValue[] {
  const developing: DevelopingValue[] = [];
  for (const p of periodDetail) {
    const upto: { price: number; count: number }[] = [];
    for (const l of levels) {
      let n = 0;
      for (const q of l.periods) if (q <= p.index) n++;
      if (n > 0) upto.push({ price: l.price, count: n });
    }
    if (upto.length === 0) continue;
    developing.push({ periodIndex: p.index, time: p.endTime, ...pocAndValueArea(upto, vaPct) });
  }
  return developing;
}

/**
 * Tails: a run of single prints hanging off an extreme, long enough to matter.
 * `levels` is not empty, and `tailEdges` of 0 disables both.
 */
function tailsOf(
  levels: readonly MarketProfileLevel[], tailEdges: number,
): { buyingTail: { high: number; low: number } | null; sellingTail: { high: number; low: number } | null } {
  let buyingTail: { high: number; low: number } | null = null;
  let sellingTail: { high: number; low: number } | null = null;
  if (tailEdges > 0) {
    const top = tailRun(levels, 0, 1);
    // A run of `top` levels from the top, at least one long since tailEdges is positive.
    if (top >= tailEdges) sellingTail = { high: levels[0]!.price, low: levels[top - 1]!.price };
    const bot = tailRun(levels, levels.length - 1, -1);
    if (bot >= tailEdges) {
      buyingTail = { high: levels[levels.length - bot]!.price, low: levels[levels.length - 1]!.price };
    }
  }
  return { buyingTail, sellingTail };
}

/**
 * Prior-session levels no later session has traded back through: the "naked"
 * POC / VAH / VAL that so often act as magnets. Oldest first, each tagged with
 * the session it came from.
 */
export function nakedLevels(
  result: MarketProfileResult,
): { time: number; price: number; kind: 'poc' | 'vah' | 'val' }[] {
  const out: { time: number; price: number; kind: 'poc' | 'vah' | 'val' }[] = [];
  const s = result.sessions;
  const kinds: ('poc' | 'vah' | 'val')[] = ['poc', 'vah', 'val'];
  for (let i = 0; i < s.length; i++) {
    for (const kind of kinds) {
      const price = s[i]![kind];
      let touched = false;
      for (let j = i + 1; j < s.length && !touched; j++) {
        if (price <= s[j]!.high && price >= s[j]!.low) touched = true;
      }
      if (!touched) out.push({ time: s[i]!.startTime, price, kind });
    }
  }
  return out;
}

/** Round a price onto the profile's row grid: handy for hit-testing. */
export function rowOf(price: number, options: MarketProfileOptions): number {
  return bucketPrice(price, options.tickSize * Math.max(1, Math.floor(options.rowTicks)));
}
