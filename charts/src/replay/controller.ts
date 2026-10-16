/**
 * Market replay: walk a historical session forward bar by bar so a trader can
 * practise on it, and so every indicator redraws exactly as it stood at that
 * past moment.
 *
 * Headless, in the spirit of `DrawingController` (src/draw/controller.ts): it
 * owns the playhead and the transitions and ships no DOM, so the host renders
 * its own transport bar, scrub slider and clock from `state()` and the events.
 *
 * The mechanic is deliberately boring. Replay feeds the chart a **prefix** of
 * the full bar array through the ordinary `series.setData` path, and that is
 * what makes indicators free: for the primary series that path invalidates and
 * recomputes every study at once (`ChartSeries._setData`), and
 * `IndicatorInstance.recompute` re-reads the whole history from `sourceBars()`. Shorten that history and every indicator, level,
 * fill, marker and legend reconstructs itself as it was at that bar, with no
 * replay-aware code anywhere in the indicator tier.
 */
import type { Bar } from '../model/bar';
import { foldFiner, formingWithin, simulatedForming, startFiner } from './forming';
import type { BarConfirmationOptions, SeriesApi } from '../model/series';
import { seriesConfirmation } from '../model/series-provenance';
import { clamp } from '../helpers/math';
import { setReplayWindow } from '../model/replay-window';
import { ReplayTimeline, type ReplayTiming } from './timeline';
import { monotonicNow, repeat } from '../helpers/timers';

/** Schedules a repeating callback and returns its canceller. Inject in tests. */
export type ReplayScheduler = (cb: () => void, intervalMs: number) => () => void;

/**
 * Most bars a single timer tick may consume. A backgrounded tab throttles its
 * timers to about one call a second, so without a ceiling the first tick after
 * the user comes back would fast-forward minutes of the session in one frame.
 */
export const CATCH_UP_LIMIT = 10;

/**
 * The slice of the time scale replay saves and restores. Declared structurally
 * rather than as `TimeScale` so nothing here depends on the scale's shape
 * beyond the two numbers that *are* the viewport.
 */
export interface ReplayViewport {
  readonly barSpacing: number;
  readonly rightOffset: number;
  setBarSpacing(value: number): void;
  setRightOffset(value: number): void;
}

/**
 * The slice of the chart this controller needs. `Chart` satisfies it; declaring
 * it structurally keeps the controller testable against a stub and free of a
 * circular import back into core.
 */
export interface ReplayChartHost {
  emit(event: string, payload: unknown): void;
  readonly timeScale: ReplayViewport;
  /**
   * Optional. When the chart can name its own primary price series, `series`
   * may be omitted and replay drives that one.
   */
  primarySeries?(): SeriesApi | null;
  /**
   * Optional. When the chart reports its own end, replay listens for it while
   * it owns the chart's data: a chart destroyed mid-session stops the playback
   * timer and is written to no more, and nothing is restored to it.
   */
  on?(event: 'destroy', callback: () => void): () => void;
}

/** Everything a transport bar and a clock need, in one object. */
export interface ReplayState {
  /** 0-based newest bar; -1 before the first observation in timed replay. */
  index: number;
  /** Bars in the replay set (the scrub bar's maximum is `total - 1`). */
  total: number;
  playing: boolean;
  /** Multiplier over `barMs`: 2 plays two bars per `barMs`. */
  speed: number;
  /**
   * The bar at `index`, the replay clock's "now". Null when there is no data.
   *
   * Under intra-bar replay this is the **partial** bar as it stands this step,
   * not the completed one, which is what makes it the right thing to drive a
   * host's own forming volume bar or an OHLC readout from.
   */
  bar: Bar | null;
  /**
   * Which step of the forming bar this is, 0-based, and how many it takes. Both
   * are 0 and 1 without `subBars`, so a transport that shows them needs no
   * special case for the plain mode.
   */
  subIndex: number;
  subSteps: number;
  /**
   * True while the newest bar forms along a simulated path (`simulate`), because
   * no finer bar covers it. Its forming prices were never traded, so a host shows
   * that plainly; the bar closes on the real bar either way.
   */
  simulated: boolean;
}

/** How a bar without finer data forms under `ReplayOptions.simulate`. */
export interface ReplaySimulation {
  /**
   * Steps such a bar takes, the last being the bar itself: a whole number from 2
   * to 240. The displayed interval over the finer one it stands in for (5 for a
   * 5-minute chart over 1-minute data) keeps the pace the same either way.
   */
  steps: number;
}

export interface ReplayOptions {
  /** Explicit candle availability for time-aligned replay. Omitted preserves index-based replay. */
  timing?: ReplayTiming;
  /** Initial UTC availability time. Requires timing; otherwise startIndex selects a completed candle. */
  startTime?: number;
  /** False prepares and validates the snapshot without changing the chart. Default true. */
  autoStart?: boolean;
  /**
   * The series replay drives. The first one owns the timeline; any others (a
   * volume histogram, a comparison line) are truncated to the same instant by
   * time, because the shared DataLayer merges *every* series onto one axis and
   * a series left at full length would drag future timestamps back onto it.
   *
   * Optional only if the host chart implements `primarySeries()`.
   */
  series?: SeriesApi | readonly SeriesApi[];
  /**
   * The full session. Defaults to the primary series' current data. Never
   * mutated, and never handed to the chart as-is: each frame gets its own slice.
   */
  bars?: readonly Bar[];
  /**
   * Finer-grained bars the displayed ones are built from: the 1-minute session
   * under a 5-minute chart. Given these, the playhead advances a **sub-bar** at
   * a time and the newest bar forms in front of the user the way a live one
   * does, instead of appearing complete. A 5-minute bar over 1-minute data
   * takes five steps.
   *
   * They must cover the same session as `bars` and be sorted by time; sub-bars
   * outside any displayed bucket are ignored. The last step of a bucket emits
   * the displayed bar **verbatim** rather than the aggregate, so a bucket always
   * closes on exactly the number the chart would have shown without this option,
   * whatever the two feeds disagree about in between. Every step before it is
   * held inside that bar, the way a live candle grows: the displayed bar's open
   * from the first step, the finer extremes and close within its high and low,
   * and volume no more than its volume. A forming bar never shows a price its
   * closed bar denies.
   *
   * Only the first driven series forms partially. Followers are cut to completed
   * buckets, because the controller cannot know how to half-aggregate an
   * arbitrary one: a volume histogram is summed, not OHLC-merged. The partial
   * bar reaches the host as `ReplayState.bar` on every frame, so a host that
   * wants a growing volume bar writes it from there.
   */
  subBars?: readonly Bar[];
  /**
   * Form a displayed bar that no finer bar covers over simulated steps instead
   * of landing it whole: the 5-minute bars older than the 1-minute history a feed
   * keeps, or every bar when there is no finer feed at all. The path runs from
   * the open to the nearer extreme, the other extreme and the close, held inside
   * the bar like every forming bar (see `subBars`), and closes on the bar itself.
   * Real finer bars always win where they exist. `ReplayState.simulated` says
   * which steps are simulated. Off by default, so a bar without finer data takes
   * one step as before.
   */
  simulate?: ReplaySimulation;
  /** Bar to open at (0-based). Default 0. */
  startIndex?: number;
  /** Wall-clock milliseconds per bar at speed 1. Default 1000. */
  barMs?: number;
  /** Initial speed multiplier. Default 1. */
  speed?: number;
  /** Called on every playhead move, after the chart has been updated. */
  onFrame?: ((state: ReplayState) => void) | undefined;
  /** Playback clock. Default `performance.now`. */
  now?: () => number;
  /**
   * Playback timer. Default `setInterval`, with the interval held from 1 ms to
   * 2^31 - 1 ms, the longest a platform timer waits (a longer one fires at once).
   */
  scheduler?: ReplayScheduler;
}

/** Index of the first bar with `time` greater than `cutoff`. */
function countUpTo(bars: readonly Bar[], cutoff: number): number {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid]!.time <= cutoff) lo = mid + 1; // lo <= mid < hi <= length
    else hi = mid;
  }
  return lo;
}

/**
 * The forming bar after the sub-bars `from..to` of a bucket: their aggregate
 * (extremes and volume accumulate, the same merge a live candle builder does),
 * held inside `final`, the displayed bar the bucket closes on, so the open never
 * moves and nothing shrinks back at the close (see `formingWithin`).
 *
 * `time` is the bucket's, not the sub-bar's, or the chart would index the
 * partial as a new bar every step instead of replacing the forming one.
 */
function mergeSubBars(subs: readonly Bar[], from: number, to: number, final: Bar): Bar {
  // `from..to` lies inside the sub-bars of one bucket.
  const raw = startFiner(subs[from]!, final.time);
  for (let i = from + 1; i <= to; i++) foldFiner(raw, subs[i]!);
  return formingWithin(raw, final);
}

/** `simulate.steps` as a count, or 0 when simulation is off. Throws on a count it cannot use. */
function simulationSteps(simulate: ReplaySimulation | undefined): number {
  if (simulate === undefined) return 0;
  const steps = simulate.steps;
  if (!Number.isInteger(steps) || steps < 2 || steps > 240) {
    throw new Error('openalgo-charts: replay simulate.steps must be a whole number from 2 to 240');
  }
  return steps;
}

export class ReplayController {
  private readonly _chart: ReplayChartHost;
  private readonly _series: readonly SeriesApi[];
  private readonly _bars: readonly Bar[];
  /** What each driven series held before replay took over, for `stop()`. */
  private readonly _restore: readonly Bar[][];
  private readonly _restoreConfirmation: readonly (BarConfirmationOptions | undefined)[];
  private readonly _view: { barSpacing: number; rightOffset: number };
  private readonly _onFrame: ((state: ReplayState) => void) | null;
  private readonly _now: () => number;
  private readonly _schedule: ReplayScheduler;
  private readonly _barMs: number;
  private readonly _startIndex: number;
  private readonly _timeline: ReplayTimeline | null;
  private readonly _startTime: number | null;
  private _time: number | null = null;
  private _pointIndex = -1;
  private readonly _subBars: readonly Bar[];
  /**
   * For each displayed bar, where its sub-bars start in `_subBars` and how many
   * there are. Built once: the alternative is a binary search per step, on a
   * path that runs on every played frame.
   *
   * A bucket with no sub-bars takes one step and shows the displayed bar, so a
   * gap in the finer feed costs that bar its formation, not its existence.
   */
  private readonly _subStart: Int32Array;
  private readonly _subCount: Int32Array;
  private readonly _intra: boolean;
  /** Steps a bar without finer data takes under `simulate`; 0 when off. */
  private readonly _simSteps: number;
  private _speed: number;
  private _index: number;
  /** Step within the forming bar, 0-based. Always 0 without `subBars`. */
  private _sub = 0;
  private _playing = false;
  /** True once replay owns the chart's data; false before start and after stop. */
  private _active = false;
  private _transition = 0;
  private _cancel: (() => void) | null = null;
  private _interval = 0;
  /** Clock reading the last advance was charged to; keeps playback drift-free. */
  private _lastAdvance = 0;
  /** Stops listening for the chart's end; held only while replay owns its data. */
  private _release: (() => void) | undefined;

  /**
   * Constructing the controller **enters replay**: it snapshots the chart's data
   * and viewport and immediately shows `startIndex`. That is the gesture a
   * replay button makes, and it means the snapshot is taken before anything has
   * moved, so `stop()` can put the user back exactly where they were.
   */
  public constructor(chart: ReplayChartHost, options: ReplayOptions = {}) {
    this._chart = chart;
    const given = options.series;
    const list: SeriesApi[] = given === undefined
      ? []
      : 'setData' in given ? [given] : [...given];
    if (list.length === 0) {
      const primary = chart.primarySeries?.() ?? null;
      if (primary === null) {
        throw new Error('openalgo-charts: replay needs a series to drive (pass options.series)');
      }
      list.push(primary);
    }
    this._series = list;
    this._restore = list.map((s) => s.getData());
    this._restoreConfirmation = list.map(seriesConfirmation);
    this._bars = options.bars ?? this._restore[0]!; // `list` holds a series by now
    this._view = { barSpacing: chart.timeScale.barSpacing, rightOffset: chart.timeScale.rightOffset };
    this._subBars = options.subBars ?? [];
    this._simSteps = simulationSteps(options.simulate);
    this._intra = (this._subBars.length > 0 || this._simSteps > 0) && this._bars.length > 0;
    const buckets = this._buildBuckets();
    this._subStart = buckets.start;
    this._subCount = buckets.count;
    this._startIndex = clamp(Math.floor(options.startIndex ?? 0), 0, Math.max(0, this._bars.length - 1));
    this._index = this._startIndex;
    this._timeline = options.timing ? new ReplayTimeline(this._bars, this._subBars, options.timing, this._simSteps) : null;
    if (options.startTime !== undefined && (!this._timeline || !Number.isFinite(options.startTime))) {
      throw new Error('openalgo-charts: replay start time must be finite and requires timing');
    }
    this._startTime = options.startTime ?? this._timeline?.ends[this._startIndex] ?? null;
    this._time = this._startTime;
    if (this._timeline) this._index = -1;
    const barMs = options.barMs ?? 1000;
    this._barMs = barMs > 0 ? barMs : 1000;
    const speed = options.speed ?? 1;
    this._speed = speed > 0 ? speed : 1;
    this._onFrame = options.onFrame ?? null;
    this._now = options.now ?? monotonicNow;
    this._schedule = options.scheduler ?? repeat;
    // Opening on a half-formed candle is not a position anyone asked for, so
    // entering replay lands on the last step of `startIndex`, the same place a
    // `seek` there would.
    if (options.autoStart !== false) {
      if (this._timeline) {
        if (this._startTime !== null) this.seekTime(this._startTime);
      } else this._apply(this._startIndex, this._steps(this._startIndex) - 1);
    }
  }

  /**
   * Map every sub-bar onto the displayed bar whose bucket it falls in.
   *
   * The displayed bars' own times are the bucket starts, so one forward pass
   * over both sorted arrays does it. A sub-bar before the first displayed bar
   * belongs to no bucket and is dropped rather than folded into bar 0, which
   * would open that bar at a price the chart never showed.
   */
  private _buildBuckets(): { start: Int32Array; count: Int32Array } {
    const n = this._bars.length;
    const start = new Int32Array(n);
    const count = new Int32Array(n);
    if (!this._intra) return { start, count };
    const subs = this._subBars;
    let d = -1;
    for (let i = 0; i < subs.length; i++) {
      const t = subs[i]!.time;
      // Advance to the last displayed bar that opens at or before this sub-bar.
      while (d + 1 < n && this._bars[d + 1]!.time <= t) {
        d++;
        start[d] = i;
      }
      if (d >= 0) count[d]!++; // `count` holds one entry per displayed bar, `d` among them
    }
    return { start, count };
  }

  // Below, `index` is a displayed bar's, and `_subCount` and `_subStart` hold one entry
  // per displayed bar: intra-bar replay needs bars, and `_apply` and `seek` clamp to them.

  /** How many steps the bar at `index` takes. At least one, always. */
  private _steps(index: number): number {
    if (this._timeline) return this._timeline.steps[index] ?? 1;
    if (!this._intra) return 1;
    const covered = this._subCount[index]!;
    return covered > 0 ? covered : Math.max(1, this._simSteps);
  }

  /** Whether the bar at `index` forms along the simulated path. */
  private _simulated(index: number): boolean {
    if (this._timeline) return !!this._timeline.points[this._pointIndex]?.simulated;
    return this._simSteps > 0 && index >= 0 && index < this._bars.length && this._subCount[index] === 0;
  }

  /** The bar shown at step `sub` of `index`, for a step before its last. */
  private _formingAt(index: number, sub: number): Bar {
    const final = this._bars[index]!;
    if (this._subCount[index]! > 0) {
      const from = this._subStart[index]!;
      return mergeSubBars(this._subBars, from, from + sub, final);
    }
    return simulatedForming(final, sub, this._simSteps, this._bars[index - 1]?.oi);
  }

  // ── transport ───────────────────────────────────────────────────────────

  /**
   * Jump the playhead to a bar. Out-of-range values clamp to the session.
   *
   * A seek lands on a **complete** bar even under intra-bar replay: scrubbing to
   * a half-formed candle is not a position anyone asks for, and it would make
   * the same slider position mean different things on the way past.
   */
  public seek(index: number): void {
    if (this._timeline) {
      const end = this._timeline.ends[clamp(Math.floor(index), 0, Math.max(0, this._bars.length - 1))];
      if (end !== undefined) this.seekTime(end);
      return;
    }
    this._apply(index, this._steps(clamp(Math.floor(index), 0, Math.max(0, this._bars.length - 1))) - 1);
  }

  /** Project only observations available by these UTC seconds. Requires timing. */
  public seekTime(time: number): void {
    if (!this._timeline) throw new Error('openalgo-charts: replay seekTime requires timing');
    if (!Number.isFinite(time)) throw new Error('openalgo-charts: replay time must be finite');
    const pointIndex = this._timeline.at(time);
    const changedTime = this._time !== time;
    this._time = time;
    if (this._active && pointIndex === this._pointIndex) {
      if (changedTime) {
        const point = this._timeline.points[pointIndex];
        setReplayWindow(this._chart, { time: point?.bar.time ?? Number.NEGATIVE_INFINITY, asOf: time,
          forming: !!point && point.subIndex < point.subSteps - 1 });
      }
      return;
    }
    const first = !this._active, point = this._timeline.points[pointIndex];
    this._active = true;
    this._pointIndex = pointIndex;
    this._index = point?.index ?? -1;
    this._sub = point?.subIndex ?? 0;
    const shown = this._bars.slice(0, this._index + 1);
    if (point) shown[this._index] = point.bar;
    this._write(shown, !!point && point.subIndex < point.subSteps - 1, first);
  }

  /** Availability clock in timed mode; the displayed bar's timestamp in legacy mode. */
  public time(): number | null { return this._timeline ? this._time : this.state().bar?.time ?? null; }

  /** Observation timestamps for a shared clock. Requires timing; returns a copy. */
  public timePoints(): readonly number[] {
    if (!this._timeline) throw new Error('openalgo-charts: replay timePoints requires timing');
    return this._timeline.points.map(point => point.time);
  }

  /**
   * Move `n` steps forward. Stops dead at the end of the session.
   *
   * A step is one displayed bar normally, and one sub-bar under intra-bar
   * replay, so the transport button means "advance the chart by the smallest
   * amount it can show" in both modes.
   */
  public step(n = 1): void {
    this._advance(n);
  }

  /** Move `n` steps back. Stops dead at the first bar. */
  public stepBack(n = 1): void {
    this._advance(-n);
  }

  /**
   * Move the playhead `delta` steps, carrying across bar boundaries.
   *
   * Written as a walk rather than arithmetic on a flat step count because
   * buckets hold different numbers of sub-bars: a session with a gap, or a
   * partial first bucket, has no constant steps-per-bar to divide by.
   */
  private _advance(delta: number): void {
    if (this._timeline) {
      if (!Number.isFinite(delta)) throw new Error('openalgo-charts: replay step must be finite');
      const steps = Math.trunc(delta);
      if (steps === 0 || (steps < 0 && this._pointIndex < 0)) return;
      const next = clamp(this._pointIndex + steps, 0, this._timeline.points.length - 1);
      const point = this._timeline.points[next];
      if (point) this.seekTime(point.time);
      return;
    }
    if (!this._intra) {
      this._apply(this._index + delta, 0);
      return;
    }
    let i = this._index;
    let sub = this._sub;
    const last = this._bars.length - 1;
    for (let k = 0; k < Math.abs(delta); k++) {
      if (delta > 0) {
        if (sub + 1 < this._steps(i)) sub++;
        else if (i < last) { i++; sub = 0; }
        else break;
      } else {
        if (sub > 0) sub--;
        else if (i > 0) { i--; sub = this._steps(i) - 1; }
        else break;
      }
    }
    this._apply(i, sub);
  }

  /**
   * Start (or re-speed) playback. Calling it on the last bar plays nothing and
   * reports `replay:end` instead of arming a timer that could never advance.
   */
  public play(options: { speed?: number } = {}): void {
    const speed = options.speed;
    if (speed !== undefined && speed > 0) this._speed = speed;
    if (this._bars.length === 0) return;
    if (this._timeline) {
      if (this._time !== null) this.seekTime(this._time);
    } else this._apply(this._index, this._sub); // a host may go straight to play() after stop()
    if (this._atEnd()) {
      this._end();
      return;
    }
    this._stopTimer();
    this._interval = this._barMs / this._speed;
    this._lastAdvance = this._now();
    this._playing = true;
    this._cancel = this._schedule(this._tick, this._interval);
    this._chart.emit('replay:play', this.state());
  }

  /** Halt playback, leaving the playhead (and the chart) where it is. */
  public pause(): void {
    if (!this._playing) return;
    this._playing = false;
    this._stopTimer();
    this._chart.emit('replay:pause', this.state());
  }

  /**
   * Leave replay: every driven series gets its pre-replay data back and the
   * viewport is restored to the pixel, so a user who exits does not lose their
   * place. Safe to call twice; a later `seek`/`step`/`play` re-enters replay
   * from `startIndex`.
   */
  public stop(): void {
    this._playing = false;
    this._stopTimer();
    if (!this._active) return;
    this._release?.();
    this._release = undefined;
    const transition = ++this._transition;
    this._active = false;
    this._index = this._startIndex;
    this._sub = 0;
    if (this._timeline) {
      this._time = this._startTime;
      this._pointIndex = this._time === null ? -1 : this._timeline.at(this._time);
      const point = this._timeline.points[this._pointIndex];
      this._index = point?.index ?? -1;
      this._sub = point?.subIndex ?? 0;
    }
    setReplayWindow(this._chart);
    if (transition !== this._transition) return;
    // `_restore` and `_restoreConfirmation` hold one entry per series.
    for (let i = 0; i < this._series.length; i++) {
      this._series[i]!.setData(this._restore[i]!, this._restoreConfirmation[i]);
      if (transition !== this._transition) return;
    }
    // Bar spacing and right offset *are* the viewport: the visible logical
    // range is (baseIndex + rightOffset) back by width / barSpacing, and
    // restoring the data restores baseIndex.
    const ts = this._chart.timeScale;
    ts.setBarSpacing(this._view.barSpacing);
    if (transition !== this._transition) return;
    ts.setRightOffset(this._view.rightOffset);
    if (transition !== this._transition) return;
    this._chart.emit('replay:stop', this.state());
  }

  public state(): ReplayState {
    const total = this._bars.length;
    const steps = total === 0 ? 1 : this._steps(this._index);
    let bar: Bar | null = null;
    if (this._timeline) {
      bar = this._timeline.points[this._pointIndex]?.bar ?? null;
    } else if (total > 0) {
      bar = this._bars[this._index]!; // without a timeline the index is always a bar's
      if (this._intra && this._sub < steps - 1) bar = this._formingAt(this._index, this._sub);
    }
    return {
      index: this._index,
      total,
      playing: this._playing,
      speed: this._speed,
      bar,
      subIndex: this._sub,
      subSteps: steps,
      simulated: total > 0 && this._simulated(this._index),
    };
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  /**
   * Put the chart at `index`. Every transition goes through here (seek, step
   * and each played frame alike), so arriving at a bar leaves the chart in the
   * same state however the user got there.
   */
  private _apply(index: number, sub = 0): void {
    const total = this._bars.length;
    if (total === 0) return;
    const next = clamp(Math.floor(index), 0, total - 1);
    const steps = this._steps(next);
    const nextSub = clamp(Math.floor(sub), 0, steps - 1);
    if (this._active && next === this._index && nextSub === this._sub) return;
    const first = !this._active;
    this._active = true;
    this._index = next;
    this._sub = nextSub;

    const shown = this._bars.slice(0, next + 1);
    // The last step of a bucket is the displayed bar itself, so a bucket always
    // closes on the number the chart would have shown without `subBars`. Only
    // the steps before it are aggregates, and only when the finer feed actually
    // covers this bucket.
    if (this._intra && nextSub < steps - 1) shown[next] = this._formingAt(next, nextSub);
    const forming = this._intra && nextSub < steps - 1;
    this._write(shown, forming, first);
  }

  private _write(shown: Bar[], forming: boolean, first: boolean): void {
    const transition = ++this._transition;
    if (first) this._release = this._chart.on?.('destroy', this._gone);
    // Other data owners must know the boundary before the primary write can
    // paint or notify a host. A comparison added later reads the same boundary.
    const lastTime = shown[shown.length - 1]?.time ?? Number.NEGATIVE_INFINITY;
    setReplayWindow(this._chart, { time: lastTime, forming,
      ...(this._timeline && this._time !== null ? { asOf: this._time } : {}) });
    // A boundary listener can stop or seek again before the first series write.
    if (transition !== this._transition) return;
    this._series[0]!.setData(shown); // replay drives at least one series
    if (transition !== this._transition) return;
    // Followers cut by time, not by count: a volume series may be shorter than
    // the price series, or start later. Under intra-bar replay they stop at the
    // last *completed* bucket, because summing a volume histogram and merging a
    // candle are not the same operation and the controller is not told which it
    // has. A host that wants its follower to grow with the forming bar writes it
    // from `ReplayState.bar`, which `onFrame` hands over below.
    const cutoff = forming
      ? (shown[shown.length - 2]?.time ?? Number.NEGATIVE_INFINITY)
      : lastTime;
    for (let i = 1; i < this._series.length; i++) {
      const snap = this._restore[i]!;
      this._series[i]!.setData(snap.slice(0, countUpTo(snap, cutoff)));
      if (transition !== this._transition) return;
    }
    if (first) this._chart.emit('replay:start', this.state());
    if (transition !== this._transition) return;
    const s = this.state();
    this._onFrame?.(s);
    if (transition !== this._transition) return;
    this._chart.emit('replay:frame', s);
  }

  /**
   * One timer tick. The number of bars owed comes from the clock, not from the
   * tick count, so a coarse or throttled timer still plays at the requested
   * speed, and a host may drive this from rAF instead with no change here.
   */
  private readonly _tick = (): void => {
    if (!this._playing) return;
    const t = this._now();
    let due = Math.floor((t - this._lastAdvance) / this._interval);
    if (due <= 0) return;
    if (due > CATCH_UP_LIMIT) {
      due = CATCH_UP_LIMIT;
      this._lastAdvance = t; // drop the unplayable backlog rather than owing it forever
    } else {
      this._lastAdvance += due * this._interval;
    }
    this._advance(due);
    if (this._atEnd()) this._end();
  };

  /**
   * The chart is gone: there is nothing to restore to and nothing to draw on,
   * so the clock stops and the controller leaves replay without writing. A
   * write in progress sees the transition move and goes no further.
   */
  private readonly _gone = (): void => {
    this._transition++;
    this._playing = false;
    this._stopTimer();
    this._active = false;
    this._release = undefined;
  };

  /** True on the last step of the last bar, which is where playback stops. */
  private _atEnd(): boolean {
    if (this._timeline) return this._pointIndex >= this._timeline.points.length - 1;
    const last = this._bars.length - 1;
    return this._index >= last && this._sub >= this._steps(last) - 1;
  }

  /** The session is over: stop the timer and tell the host once. */
  private _end(): void {
    this.pause();
    this._chart.emit('replay:end', this.state());
  }

  private _stopTimer(): void {
    this._cancel?.();
    this._cancel = null;
  }
}
