import type { Bar } from './bar';
import type {
  IndicatorAlertContext, IndicatorAlertFrequency, IndicatorAlertPayload, IndicatorAlertSpec,
  IndicatorCalcContext, IndicatorSettings, IndicatorValues,
} from './indicator-registry';

/** What a declared alert delivers before the instance adds whose it is. */
type PolicyAlert = Omit<IndicatorAlertPayload, 'indicatorId' | 'instanceId'>;

/** Original calculation inputs and an ownership fence supplied by the instance. */
export interface IndicatorAlertPolicyPass {
  bars: readonly Bar[];
  values: IndicatorValues;
  settings: Readonly<IndicatorSettings>;
  calculation: IndicatorCalcContext;
  tailOnly: boolean;
  refresh: boolean;
  current(): boolean;
  /** The first bar this pass appended after an unchanged prefix; `bars.length` when it appended none. */
  from: number;
  /** A study computed on the bars under a transform: those bars, and the one each element reads. */
  sampled?: { bars: readonly Bar[]; sourceIndex: readonly number[] } | null;
}

interface Entry {
  spec: IndicatorAlertSpec & { frequency: IndicatorAlertFrequency };
  onceSpent: boolean;
  perBarTime: number;
  closedTime: number;
  failedCloses: Set<number>;
  busy: boolean;
}

const FREQUENCIES = new Set<string>(['everyUpdate', 'oncePerBar', 'onBarClose', 'once']);

function copyValues(values: IndicatorValues, end?: number): IndicatorValues {
  const result: IndicatorValues = {};
  for (const key of Object.keys(values)) {
    Object.defineProperty(result, key, {
      value: Object.freeze(values[key]!.slice(0, end)), enumerable: true, // an own key
    });
  }
  return Object.freeze(result);
}

/**
 * What an alert judges at `index`: the bars and outputs through it. A bar
 * before the newest is judged as it stood when it was the newest, so a pass
 * that appended several bars reads each the way separate appends would have.
 */
export function alertContext(bars: readonly Bar[], values: IndicatorValues, settings: Readonly<IndicatorSettings>,
  index: number): IndicatorAlertContext {
  return index === bars.length - 1 ? { bars, values, settings, index }
    : { bars: Object.freeze(bars.slice(0, index + 1)), values: copyValues(values, index + 1), settings, index };
}

/**
 * The time of the bar the study read at each element, the time an alert's
 * marks are kept in: the element's own, or for a study computed on the bars
 * under a transform the source bar its values were read at. The elements that
 * one source bar completed all read that bar, so they are one bar of the
 * study, judged once, at the first of them.
 */
export function studyBarTime(bars: readonly Bar[], sampled?: IndicatorAlertPolicyPass['sampled']): (index: number) => number {
  return sampled ? i => sampled.bars[sampled.sourceIndex[i]!]!.time : i => bars[i]!.time;
}

/** Explicit policies only. The instance retains the omitted-frequency legacy path. */
export class IndicatorAlertPolicy {
  private readonly _entries: Entry[] = [];
  private readonly _legacyCalculations = new WeakSet<IndicatorCalcContext>();
  private _initialized = false;
  private _native = false;
  private _sourceId: number | undefined;
  private _historyRevision: number | undefined;
  private _revision: number | undefined;
  private _replaying = false;
  private _epoch = 0;

  public constructor(specs: readonly IndicatorAlertSpec[]) {
    const ids = new Set<string>();
    for (const spec of specs) {
      const frequency = spec.frequency;
      if (frequency === undefined) continue;
      if (!FREQUENCIES.has(frequency)) throw new TypeError('Indicator alert frequency is invalid');
      if (typeof spec.id !== 'string' || spec.id.trim() === '') throw new TypeError('Explicit indicator alert id must be nonempty');
      if (ids.has(spec.id)) throw new TypeError('Explicit indicator alert ids must be unique');
      ids.add(spec.id);
      this._entries.push({
        spec: Object.freeze({ ...spec, frequency }), onceSpent: false,
        perBarTime: -Infinity, closedTime: -Infinity, failedCloses: new Set(), busy: false,
      });
    }
  }

  /** Evaluate one observed calculation. There is no timer or notification transport. */
  public evaluate(pass: IndicatorAlertPolicyPass, emit: (payload: PolicyAlert) => void): void {
    if (this._entries.length === 0 || !pass.current()) return;
    const execution = pass.calculation.execution;
    const native = execution !== undefined;
    const replaying = execution?.provenance === 'replay';
    const generation = !this._initialized || this._native !== native || (native && (
      execution.sourceId !== this._sourceId || execution.historyRevision !== this._historyRevision || replaying !== this._replaying
    ));
    if (native) {
      if (!generation && this._revision !== undefined && execution.revision <= this._revision) return;
    } else {
      if (this._legacyCalculations.has(pass.calculation)) return;
      this._legacyCalculations.add(pass.calculation);
    }

    // Reserve before callbacks. Repeated reads of a failed revision cannot
    // redeliver successful siblings or retry a failed predicate immediately.
    const epoch = ++this._epoch;
    this._initialized = true;
    this._native = native;
    this._sourceId = execution?.sourceId;
    this._historyRevision = execution?.historyRevision;
    this._revision = execution?.revision;
    this._replaying = replaying;
    // The checkpoints are kept in the times of the bars the study computed on;
    // `closed` is the newest of them that has closed.
    const rows = pass.sampled?.bars ?? pass.bars;
    const read = studyBarTime(pass.bars, pass.sampled);
    const closed = rows[rows.length - (pass.calculation.barState.isConfirmed ? 1 : 2)]?.time ?? -Infinity;
    const refresh = pass.refresh || execution?.change === 'refresh';
    const live = native ? execution.provenance === 'live' : pass.tailOnly;
    if (generation || (!refresh && !live)) {
      this._seed(closed);
      return;
    }
    if (refresh || !live || pass.bars.length === 0) return;

    const bars = Object.freeze(pass.bars.map(bar => Object.freeze({ ...bar })));
    const values = copyValues(pass.values);
    const settings = Object.freeze({ ...pass.settings });
    const current = (): boolean => this._epoch === epoch && pass.current();
    if (!current()) return;
    let failed = false;
    let firstError: unknown;
    const last = bars.length - 1;
    // Each bar the pass appended, in order, as separate appends would judge
    // them, and elements that read one bar once, at the first; a tick that
    // appended none judges the newest alone, and only when it reads the bar
    // that moved.
    const start = Math.min(pass.from, last);
    const fresh: number[] = [];
    for (let i = start; i <= last; i++) {
      if (i > start ? read(i) !== read(i - 1) : start === pass.from || read(i) === rows[rows.length - 1]!.time) fresh.push(i);
    }
    for (const entry of this._entries) {
      if (!current()) return;
      if (entry.busy) continue;
      const close = entry.spec.frequency === 'onBarClose';
      const indices = close ? this._closeIndices(entry, read, last, closed) : fresh;
      for (const index of indices) { // bar indices, `last` at most
        if (!current()) return;
        if (entry.spec.frequency === 'once' && entry.onceSpent) break;
        const time = bars[index]!.time, bar = read(index);
        if (entry.spec.frequency === 'oncePerBar' && bar <= entry.perBarTime) continue;
        const context = alertContext(bars, values, settings, index);
        let committed = false;
        entry.busy = true;
        try {
          if (!current()) return;
          const matches = entry.spec.when(context);
          if (!current()) return;
          if (!matches) {
            if (close) this._judgeClose(entry, bar);
            continue;
          }
          const message = typeof entry.spec.message === 'function'
            ? entry.spec.message(context) : entry.spec.message ?? entry.spec.title;
          if (!current()) return;
          const payload: PolicyAlert = { alertId: entry.spec.id, title: entry.spec.title, message, time, index };
          // Native event dispatch is the commitment boundary. A subscriber
          // exception cannot make a spent alert available for another delivery.
          if (entry.spec.frequency === 'once') entry.onceSpent = true;
          if (entry.spec.frequency === 'oncePerBar') entry.perBarTime = bar;
          if (close) this._judgeClose(entry, bar);
          committed = true;
          emit(payload);
          if (!current()) return;
        } catch (error) {
          if (!current()) return;
          if (close && !committed) entry.failedCloses.add(bar);
          if (!failed) { failed = true; firstError = error; }
        } finally {
          entry.busy = false;
        }
      }
    }
    if (failed && current()) throw firstError;
  }

  /**
   * The newest bar was dated again at `to` and is the same bar: a transformed
   * chart's forming element moved forward by a newer source bar. A bar it
   * already delivered or closed stays delivered or closed at its new time.
   */
  public redate(from: number, to: number): void {
    for (const entry of this._entries) {
      if (entry.perBarTime === from) entry.perBarTime = to;
      if (entry.closedTime === from) entry.closedTime = to;
    }
  }

  private _seed(time: number): void {
    for (const entry of this._entries) {
      entry.perBarTime = time;
      entry.closedTime = time;
      entry.failedCloses.clear();
    }
  }

  private _judgeClose(entry: Entry, time: number): void {
    entry.closedTime = Math.max(entry.closedTime, time);
    entry.failedCloses.delete(time);
  }

  /** The elements whose bar has closed and is still to judge, the first element that reads each. */
  private _closeIndices(entry: Entry, read: (index: number) => number, last: number, closed: number): number[] {
    const indices: number[] = [];
    const available = new Set<number>();
    for (let i = 0, time = 0; i <= last && (time = read(i)) <= closed; i++) {
      if ((time > entry.closedTime || entry.failedCloses.has(time)) && !available.has(time)) indices.push(i);
      available.add(time);
    }
    for (const time of entry.failedCloses) if (!available.has(time)) entry.failedCloses.delete(time);
    return indices;
  }
}
