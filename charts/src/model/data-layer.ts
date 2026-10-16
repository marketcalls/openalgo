/**
 * Shared data layer (ARCHITECTURE.md §4.1). One per chart. Merges all series by
 * time onto a single logical-index space (0..N-1) so price + volume + indicator
 * panes stay aligned, and so non-trading gaps collapse (an absent time simply
 * has no logical index). Per-series rows are addressable by that shared index.
 */
import type { Bar } from './bar';
import type { InstrumentSession } from '../feed/instrument';
import type { SessionPhaseSpan } from '../feed/market-status';

export type SeriesId = number;

/**
 * Trading hours the time axis follows past the last bar. `Instrument` and
 * `SessionCalendar` both satisfy it.
 */
export interface SessionCalendarSource {
  /** The window active at `utcSeconds`, or else the next one to open; null when none opens. */
  sessionFrom(utcSeconds: number): InstrumentSession | null;
  /**
   * Optional: the phases of the trading day over a range, which session
   * shading and `marketStatusAt` read from the chart's calendar. The axis
   * never calls it. `Instrument` and `SessionCalendar` provide it.
   */
  phaseSpans?(fromUtcSeconds: number, toUtcSeconds: number): readonly SessionPhaseSpan[];
}

const DAY = 86400;
/** Recent gaps a spacing is read from: enough to outvote a weekend and a few holidays. */
const SAMPLE = 64;
/**
 * Future bar times generated from a calendar, and calendar reads spent on one
 * plan. Past either, the axis continues at the average pace of what was
 * generated, so an anchor years out costs a bounded amount once rather than a
 * walk through every session in between.
 */
const MAX_SLOTS = 4096;
const MAX_LOOKUPS = 512;

/**
 * The lower median of some gaps, sorting them in place. Lower, because a
 * closure only ever lengthens a gap: after Thursday, Friday and Monday the
 * answer is one day, not three. Every caller passes at least one gap.
 */
function lowerMedian(gaps: number[]): number {
  gaps.sort((a, b) => a - b);
  return gaps[(gaps.length - 1) >> 1]!;
}

function gapsOf(t: readonly number[]): number[] {
  const gaps: number[] = [];
  for (let i = 1; i < t.length; i++) gaps.push(t[i]! - t[i - 1]!);
  return gaps;
}

/** Largest index in `a[0..hi]` whose value is at most `v`; the caller ensures `a[0] <= v` and `hi < a.length`. */
function floorIndex(a: readonly number[], v: number, hi: number): number {
  let lo = 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (a[mid]! <= v) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/**
 * The bar times to the right of the data, from the last bar on. `slots` grows
 * on demand from `next`; past it the axis runs at `step` per bar.
 */
interface FuturePlan {
  version: number;
  readonly tail: readonly number[];
  readonly slots: number[];
  /** The next bar time; null when the calendar has no more, NaN when a budget ran out. */
  next: (() => number | null) | null;
  step: number;
}

/**
 * A generator of future bar times that follows `calendar`, or null when the
 * recent bars `w` do not sit in its sessions (hours that do not describe this
 * feed, such as regular hours against extended-hours bars).
 *
 * Bars sharing a session are intraday: the spacing is their median gap, and a
 * session that ends restarts at the next opening, at the offset the feed's
 * bars keep from that opening. The offset belongs to each window, since one
 * bar grid can meet the windows of a day differently: hourly bars on the
 * clock put 09:00 at a 09:00 opening and 12:00 before a 12:30 one after
 * lunch, and 09:00 before a 09:15 open. One bar per session is daily: each
 * later trading date, at the last bar's offset from its opening. Weekly and
 * longer bars keep the median.
 */
function sessionSlots(w: readonly number[], calendar: SessionCalendarSource, median: number): (() => number | null) | null {
  let lookups = 0;
  const from = (time: number): InstrumentSession | null | undefined =>
    ++lookups > MAX_LOOKUPS ? undefined : calendar.sessionFrom(time);
  // `w` is the plan's tail, two bars or more, and `opens` gets one entry per bar.
  let s = from(w[0]!);
  if (!s) return null;
  const same: number[] = [], opens = [s.open];
  let lead = s.open - w[0]!;
  for (let i = 1; i < w.length; i++) {
    if (w[i]! < s.close) same.push(w[i]! - w[i - 1]!);
    else if (!(s = from(w[i]!))) return null;
    opens.push(s.open);
    lead = Math.max(lead, s.open - w[i]!);
  }
  const last = w[w.length - 1]!;
  let session = s, cur = last;
  if (same.length > 0) {
    const step = lowerMedian(same);
    // A bar a whole step before the session it is filed under is outside it.
    if (lead >= step) return null;
    // Where a bar sits against its opening, as the first bar's offset: zero,
    // or up to a step before the opening for a bar stamped on an earlier grid.
    const offsetOf = (t: number, open: number): number => {
      const phase = (((t - open) % step) + step) % step;
      return phase > 1e-6 && step - phase > 1e-6 ? phase - step : 0;
    };
    // Each window's offset, keyed by its opening's time of day and read from
    // the latest bar in a window like it. A window no bar has shown, such as
    // a special session or an opening the clocks moved, takes the last bar's.
    const offsets = new Map<number, number>();
    for (let i = 0; i < w.length; i++) offsets.set(opens[i]! % DAY, offsetOf(w[i]!, opens[i]!));
    const fallback = offsetOf(last, session.open);
    return () => {
      let t = cur + step;
      while (t >= session.close) {
        const n = from(session.close);
        if (!n) return n === null ? null : NaN;
        session = n;
        // Back-to-back windows with a first bar stamped before the open would
        // step backwards; the next bar is then simply one step on.
        const first = n.open + (offsets.get(n.open % DAY) ?? fallback);
        if (first > cur) t = first;
      }
      return (cur = t);
    };
  }
  if (median >= 2 * DAY || lead >= DAY) return null;
  const offset = last - session.open;
  return () => {
    // Skip the later windows of the same date, a lunch break's afternoon.
    for (const date = session.date; session.date === date;) {
      const n = from(session.close);
      if (!n) return n === null ? null : NaN;
      session = n;
    }
    const t = session.open + offset;
    return t > cur ? (cur = t) : null;
  };
}

/** One more future bar time, or the end of generation and the spacing that replaces it. */
function grow(p: FuturePlan): void {
  // A plan's slots start with the last bar's time and only grow.
  const s = p.slots, m = s.length - 1;
  let t: number | null = NaN;
  if (m < MAX_SLOTS) {
    try { t = p.next!(); } catch { t = null; }
  }
  if (t !== null && t > s[m]!) {
    s.push(t);
    return;
  }
  p.next = null;
  // A budget ran out: continue at the pace the calendar set, weekends and
  // nights included. A calendar with nothing more, or one that threw, leaves
  // the median, which is the answer without a calendar.
  if (t !== null && Number.isNaN(t) && m > 0) p.step = (s[m]! - s[0]!) / m;
}

function futureSlot(p: FuturePlan, k: number): number {
  const s = p.slots;
  while (s.length <= k && p.next) grow(p);
  const m = s.length - 1;
  return k <= m ? s[k]! : s[m]! + (k - m) * p.step;
}

interface SeriesEntry {
  /** Bars sorted ascending by time. */
  bars: Bar[];
}

export interface IndexedBar {
  index: number;
  bar: Bar;
}

const EMPTY_BARS: readonly Bar[] = [];

/** Where the visible bars of one series start, and the last time they may carry. */
export interface VisibleSpan {
  start: number;
  lastTime: number;
}

/**
 * Find the bars of `bars` whose logical index lies within [from, to], the way
 * `DataLayer.visibleBars` does (it is built on this), without building its list: `out.start` is the
 * first candidate and `out.lastTime` the time past which none is in view.
 * Returns false when nothing can be.
 *
 * A caller walks `bars` from `start` while `time <= lastTime` and keeps the
 * bars `timeToIndex` answers for, which is the list `visibleBars` returns,
 * in the same order.
 */
export function visibleSpan(layer: DataLayer, bars: readonly Bar[], from: number, to: number, out: VisibleSpan): boolean {
  const lo = Math.max(0, Math.floor(from));
  const hi = Math.min(layer.baseIndex, Math.ceil(to));
  if (hi < lo || bars.length === 0) return false;
  const loTime = layer.indexToTime(lo);
  const hiTime = layer.indexToTime(hi);
  if (loTime === undefined || hiTime === undefined) return false;
  let start = 0;
  let end = bars.length;
  while (start < end) {
    const mid = (start + end) >> 1;
    if (bars[mid]!.time < loTime) start = mid + 1; // start <= mid < end <= bars.length
    else end = mid;
  }
  out.start = start;
  out.lastTime = hiTime;
  return true;
}

/** Scratch for the walks below, which run start to end without yielding. */
const SPAN: VisibleSpan = { start: 0, lastTime: 0 };

/**
 * The bar of series `id` at a logical index, as `visibleBars(id, index, index)[0]`
 * answers it, without building a list: the crosshair, the readout and the
 * snap ask for one bar on every pointer move.
 */
export function barAtIndex(layer: DataLayer, id: SeriesId, index: number): Bar | undefined {
  const bars = layer.seriesBars(id);
  if (!visibleSpan(layer, bars, index, index, SPAN)) return undefined;
  for (let i = SPAN.start; i < bars.length; i++) {
    const bar = bars[i]!; // below the length the loop checks
    if (bar.time > SPAN.lastTime) return undefined;
    if (layer.timeToIndex(bar.time) !== undefined) return bar;
  }
  return undefined;
}

/**
 * Where the bar at `time` sits in a series, or -1. A study writes a revised
 * older point of its plot through `update`, so this runs per point per tick and
 * searches rather than scans. A miss scans after all: only a series holding a
 * time that does not order (NaN) can be out of order, and a miss is followed by
 * an insert that costs more than the scan.
 */
function indexOfTime(bars: readonly Bar[], time: number): number {
  let lo = 0;
  let hi = bars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const t = bars[mid]!.time;
    if (t === time) return mid;
    if (t < time) lo = mid + 1;
    else if (t > time) hi = mid - 1;
    else break;
  }
  return bars.findIndex((b) => b.time === time);
}

/**
 * Sort ascending by time and collapse repeated times, keeping the **last**
 * occurrence.
 *
 * One bar per time is an invariant every reader relies on: `_rebuild` maps times
 * onto logical indices through a Set, so two bars sharing a time both resolve to
 * the same index and get projected to the same x: two candles drawn on top of
 * each other, each with its own colour. A live feed whose candle builder starts
 * unseeded produces exactly that: it opens a fresh bar for the bucket the
 * fetched history already ends in, and the host appends it alongside.
 *
 * `Array#sort` is stable, so "last" means last in the caller's array: the newer
 * value when a live bar arrives alongside the historical one it supersedes.
 */
function sortedUniqueByTime(bars: readonly Bar[]): Bar[] {
  // A study's plots and most feeds arrive in time order already, so that case
  // is checked for first rather than paid a sort for.
  let ordered = true;
  for (let i = 1; i < bars.length && ordered; i++) ordered = bars[i]!.time > bars[i - 1]!.time;
  if (ordered) return bars.slice();
  const out = bars.slice().sort((a, b) => a.time - b.time);
  let w = 0;
  for (let r = 0; r < out.length; r++) { // `w` never passes `r`
    if (w > 0 && out[r]!.time === out[w - 1]!.time) out[w - 1] = out[r]!;
    else out[w++] = out[r]!;
  }
  out.length = w;
  return out;
}

export class DataLayer {
  private readonly _series = new Map<SeriesId, SeriesEntry>();
  private _sortedTimes: number[] = [];
  private readonly _indexByTime = new Map<number, number>();
  /** How many series hold each time on the axis; a time leaves the axis at zero. */
  private readonly _timeRefs = new Map<number, number>();
  private _nextId: SeriesId = 1;
  /** Bumped whenever the time axis changes, so the future plan knows to look again. */
  private _version = 0;
  private _calendar: SessionCalendarSource | null = null;
  private _future: FuturePlan | null = null;

  /**
   * Trading hours for the time axis to the right of the last bar, or null for
   * none. With a calendar, the bar after a session's last one is the next
   * session's first, across a night, a weekend or a closed date, so an anchor
   * placed there lands on a time the market will print. Without one, or when
   * the recent bars do not sit in its sessions, the axis continues at the
   * median of the recent bar spacing.
   *
   * This changes where times fall but asks for no frame: the data layer has
   * no way to reach the chart, so a drawing already placed past the last bar
   * stays where it was painted until something repaints. `chart.setSessionCalendar`
   * sets the same and repaints, and so do `SessionCalendar.applyTo` and
   * `Instrument.applyTo`, which go through it; call this directly only where
   * bars or a view change follow anyway.
   */
  public setSessionCalendar(calendar: SessionCalendarSource | null): void {
    this._calendar = calendar;
    this._future = null;
  }

  /** The calendar the time axis follows past the last bar, or null. */
  public get sessionCalendar(): SessionCalendarSource | null {
    return this._calendar;
  }

  /** Register a new series; returns its id. */
  public createSeries(): SeriesId {
    const id = this._nextId++;
    this._series.set(id, { bars: [] });
    return id;
  }

  public removeSeries(id: SeriesId): void {
    const entry = this._series.get(id);
    if (entry === undefined) return;
    this._replaceBars(entry, []);
    this._series.delete(id);
  }

  /**
   * Bulk-load (full replace) one series' data. Input is sorted and
   * de-duplicated by time by a private `sortedUniqueByTime`.
   *
   * The shared index is rebuilt only when the set of times changes, and then
   * only where it changed. Most whole writes do not change the set: a study's
   * plots carry the source's own times, which the source put in the index
   * before any study recomputed, and a colour overlay on the source keeps its
   * times. Ten studies on a long history used to pay for the index two dozen
   * times per tick while it came out unchanged.
   */
  public setSeriesData(id: SeriesId, bars: readonly Bar[]): void {
    const entry = this._series.get(id);
    if (entry === undefined) throw new Error(`openalgo-charts: unknown series ${id}`);
    this._replaceBars(entry, sortedUniqueByTime(bars));
  }

  /**
   * Upsert bars into a series by time (used for history paging / backfill /
   * out-of-order corrections, ARCHITECTURE.md §4.2). Existing times are
   * replaced; new times are inserted; the result stays time-sorted.
   *
   * Prepending older bars shifts every existing logical index up by the
   * inserted count: callers preserve the viewport by re-reading `baseIndex`
   * (the invariant `rightEdge − index` is unchanged, so visible bars don't move).
   */
  public addBars(id: SeriesId, bars: readonly Bar[]): void {
    const entry = this._series.get(id);
    if (entry === undefined) throw new Error(`openalgo-charts: unknown series ${id}`);
    if (bars.length === 0) return;
    const byTime = new Map<number, Bar>();
    for (const b of entry.bars) byTime.set(b.time, b);
    for (const b of bars) byTime.set(b.time, b);
    this._replaceBars(entry, Array.from(byTime.values()).sort((a, b) => a.time - b.time));
  }

  /**
   * Apply a single live bar (ARCHITECTURE.md §4.2 hot path). Returns the kind of
   * change so the chart auto-scrolls only on a genuine right-edge append:
   * - `'append'`: newer than the last bar (advances baseIndex)
   * - `'replace'`: same time as the last bar (intra-bar tick) or an existing time
   * - `'insert'`: an older time inserted into history (late / out-of-order)
   */
  public update(id: SeriesId, bar: Bar): 'append' | 'replace' | 'insert' {
    const entry = this._series.get(id);
    if (entry === undefined) throw new Error(`openalgo-charts: unknown series ${id}`);
    const bars = entry.bars;
    const last = bars[bars.length - 1];
    if (last === undefined || bar.time > last.time) {
      // Newer than THIS series' last bar, so pushing keeps the series sorted.
      bars.push(bar);
      const n = this._sortedTimes.length;
      const globalLast = n > 0 ? this._sortedTimes[n - 1] : undefined;
      const isNew = this._retain(bar.time);
      if (globalLast === undefined || bar.time > globalLast) {
        this._appendTime(bar.time); // genuine global right-edge append
        return 'append';
      }
      // Series-local append but NOT the global newest: the time belongs mid-axis.
      // If it already exists globally (another series has it) no new index is
      // added; otherwise reindex so _sortedTimes stays ordered.
      if (!isNew) return 'replace';
      this._rebuild([bar.time], false);
      return 'insert';
    }
    if (bar.time === last.time) {
      bars[bars.length - 1] = bar; // mutate last
      return 'replace';
    }
    // older than the last bar: replace if the time exists, else insert into history
    const i = indexOfTime(bars, bar.time);
    if (i >= 0) {
      bars[i] = bar;
      return 'replace';
    }
    this.addBars(id, [bar]);
    return 'insert';
  }

  private _appendTime(time: number): void {
    if (!this._indexByTime.has(time)) {
      this._indexByTime.set(time, this._sortedTimes.length);
      this._sortedTimes.push(time);
      this._version++;
    }
  }

  /** Number of logical indices (distinct time points across all series). */
  public get length(): number {
    return this._sortedTimes.length;
  }

  /** Logical index of the latest real bar (length - 1), or -1 if empty. */
  public get baseIndex(): number {
    return this._sortedTimes.length - 1;
  }

  public indexToTime(index: number): number | undefined {
    return this._sortedTimes[index];
  }

  public timeToIndex(time: number): number | undefined {
    return this._indexByTime.get(time);
  }

  /**
   * Fractional logical index to UTC seconds, interpolating between bars and
   * extrapolating past either edge.
   *
   * `indexToTime` only answers for indices that have a bar. Anything anchored to
   * an arbitrary x (a drawing endpoint, a cursor readout, a projection to the
   * right of the last bar) needs a time for positions *between* bars too, which
   * the gapless axis (§5.3) makes common: everything a weekend or a session
   * break collapsed away lands there. Returns NaN when there is no data.
   *
   * Past the last bar the whole indices are the bar times still to come: from
   * the session calendar when one is set (`setSessionCalendar`), otherwise one
   * median recent spacing apart. Never the last gap alone, which is the gap most
   * likely to be a night or a weekend. Left of the first bar the first gap
   * applies.
   */
  public indexToTimeFloat(index: number): number {
    const t = this._sortedTimes;
    const n = t.length;
    // Each read below sits inside the length the branch before it checked.
    if (n === 0) return NaN;
    if (n === 1) return t[0]!;
    if (index <= 0) return t[0]! + index * (t[1]! - t[0]!);
    if (index >= n - 1) {
      const p = this._plan(), d = index - (n - 1), k = Math.floor(d), a = futureSlot(p, k);
      return d === k ? a : a + (d - k) * (futureSlot(p, k + 1) - a);
    }
    const i = Math.floor(index);
    return t[i]! + (index - i) * (t[i + 1]! - t[i]!);
  }

  /** UTC seconds to fractional logical index. The inverse of `indexToTimeFloat`. */
  public timeToIndexFloat(time: number): number {
    const t = this._sortedTimes;
    const n = t.length;
    // As above; the slots start at t[n - 1], and `time` below the last slot or
    // the last bar puts `k` and `lo` one short of the end.
    if (n === 0) return NaN;
    if (n === 1) return 0;
    if (time <= t[0]!) {
      const step = t[1]! - t[0]!;
      return step > 0 ? (time - t[0]!) / step : 0;
    }
    if (time >= t[n - 1]!) {
      const p = this._plan(), s = p.slots;
      while (p.next && s[s.length - 1]! <= time) grow(p);
      const m = s.length - 1;
      if (time >= s[m]!) return n - 1 + m + (time - s[m]!) / p.step;
      const k = floorIndex(s, time, m);
      return n - 1 + k + (time - s[k]!) / (s[k + 1]! - s[k]!);
    }
    const lo = floorIndex(t, time, n - 1);
    return lo + (time - t[lo]!) / (t[lo + 1]! - t[lo]!);
  }

  /**
   * The future plan for the current last bars and calendar. A rebuild that
   * leaves the recent bars as they were (a page of older history, a gap filled
   * well to the left) keeps the plan and the times it already generated.
   */
  private _plan(): FuturePlan {
    const t = this._sortedTimes, from = Math.max(0, t.length - 1 - SAMPLE);
    let p = this._future;
    if (p !== null && p.version !== this._version
      && p.tail.length === t.length - from && p.tail.every((time, i) => time === t[from + i])) p.version = this._version;
    if (p === null || p.version !== this._version) {
      const tail = t.slice(from), median = lowerMedian(gapsOf(tail));
      let next: (() => number | null) | null = null;
      try {
        if (this._calendar) next = sessionSlots(tail, this._calendar, median);
      } catch {
        // A calendar that cannot answer, such as a window in a daylight-saving
        // gap, must not stop a chart painting: the median answers instead.
      }
      // Only the two readers above ask, and both hold two bars or more.
      p = this._future = { version: this._version, tail, slots: [tail[tail.length - 1]!], next, step: median };
    }
    return p;
  }

  /**
   * A series' bars, time-sorted, with no per-call allocation: the read path
   * for anything that recomputes over full history (indicators, transforms).
   * The array is live: treat it as read-only.
   */
  public seriesBars(id: SeriesId): readonly Bar[] {
    return this._series.get(id)?.bars ?? EMPTY_BARS;
  }

  /** All bars of a series paired with their shared logical index. */
  public indexedBars(id: SeriesId): IndexedBar[] {
    const entry = this._series.get(id);
    if (entry === undefined) return [];
    const out: IndexedBar[] = [];
    for (const bar of entry.bars) {
      const index = this._indexByTime.get(bar.time);
      if (index !== undefined) out.push({ index, bar });
    }
    return out;
  }

  /**
   * Bars of a series whose logical index lies within [fromIndex, toIndex].
   * Binary-searches the (time-sorted) series into the visible time window instead
   * of scanning all bars, so a full repaint costs O(log n + visible) per series,
   * not O(total bars) - the hot path called for autoscale and drawing every frame.
   */
  public visibleBars(id: SeriesId, fromIndex: number, toIndex: number): IndexedBar[] {
    const entry = this._series.get(id);
    if (entry === undefined) return [];
    const bars = entry.bars;
    if (!visibleSpan(this, bars, fromIndex, toIndex, SPAN)) return [];
    const out: IndexedBar[] = [];
    for (let i = SPAN.start; i < bars.length; i++) {
      const t = bars[i]!.time;
      if (t > SPAN.lastTime) break;
      const index = this._indexByTime.get(t);
      if (index !== undefined) out.push({ index, bar: bars[i]! });
    }
    return out;
  }

  /** The last bar of a series with its shared logical index, in O(1). */
  public lastIndexedBar(id: SeriesId): IndexedBar | null {
    const entry = this._series.get(id);
    if (entry === undefined || entry.bars.length === 0) return null;
    const bar = entry.bars[entry.bars.length - 1]!;
    const index = this._indexByTime.get(bar.time);
    return index === undefined ? null : { index, bar };
  }

  /** Count one more series holding `time`; true when no series held it before. */
  private _retain(time: number): boolean {
    const n = this._timeRefs.get(time) ?? 0;
    this._timeRefs.set(time, n + 1);
    return n === 0;
  }

  /**
   * Swap a series' bars and bring the time axis along. The counts say which
   * times entered or left the union, so the work is the series' own change,
   * never every series the chart holds: re-sending the same times touches no
   * index at all, times past the right edge are appended, and anything else
   * is merged in by `_rebuild`.
   */
  private _replaceBars(entry: SeriesEntry, next: Bar[]): void {
    const prev = entry.bars;
    entry.bars = next;
    // Both are sorted, so the times they share from the start are the same set
    // and their counts stand. A refresh, or a refresh with a bar appended,
    // leaves nothing or one bar past it.
    let p = 0;
    while (p < prev.length && p < next.length && prev[p]!.time === next[p]!.time) p++;
    // Count the new bars before releasing the old, so a time both hold never
    // passes through zero. `next` is sorted, so `added` comes out sorted.
    let added: number[] | null = null;
    for (let i = p; i < next.length; i++) if (this._retain(next[i]!.time)) (added ??= []).push(next[i]!.time);
    let removed = false;
    for (let i = p; i < prev.length; i++) {
      const t = prev[i]!.time, n = this._timeRefs.get(t) ?? 0;
      if (n <= 1) { this._timeRefs.delete(t); removed = true; } else this._timeRefs.set(t, n - 1);
    }
    if (added === null && !removed) return;
    const edge = this._sortedTimes.length > 0 ? this._sortedTimes[this._sortedTimes.length - 1]! : -Infinity;
    // `added` is null until its first push, so it is never empty here.
    if (!removed && added !== null && added[0]! > edge) {
      for (const t of added) this._appendTime(t);
      return;
    }
    this._rebuild(added ?? [], removed);
  }

  /**
   * Merge `added` (sorted, new to the axis) into it and drop the times no
   * series holds any longer. Indices before the first change keep their value,
   * so a change near the right edge reindexes only what moved. A time that
   * does not order (NaN) cannot be merged, and the union is sorted afresh.
   */
  private _rebuild(added: readonly number[] = [], removed = true): void {
    const old = this._sortedTimes;
    if (added.some(Number.isNaN) || old.some(Number.isNaN)) {
      const all = Array.from(this._timeRefs.keys()).sort((a, b) => a - b);
      this._indexByTime.clear();
      for (let k = 0; k < all.length; k++) this._indexByTime.set(all[k]!, k);
      this._sortedTimes = all;
      this._version++;
      return;
    }
    const merged: number[] = [];
    let i = 0, j = 0;
    // The loop condition and the test that picks a side keep `i` and `j` in range.
    while (i < old.length || j < added.length) {
      if (j >= added.length || (i < old.length && old[i]! < added[j]!)) {
        const t = old[i++]!;
        if (!removed || this._timeRefs.has(t)) merged.push(t);
        else this._indexByTime.delete(t);
      } else {
        merged.push(added[j++]!);
      }
    }
    let first = 0;
    while (first < merged.length && first < old.length && merged[first] === old[first]) first++;
    for (let k = first; k < merged.length; k++) this._indexByTime.set(merged[k]!, k);
    this._sortedTimes = merged;
    this._version++;
  }
}
