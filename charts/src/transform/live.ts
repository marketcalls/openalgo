/**
 * The transforms a chart runs itself (ARCHITECTURE.md §6A). Each built-in
 * transform is registered with the base as a `SeriesTransformDefinition`: the
 * renderer its elements draw with, the options it takes, and the run the chart
 * drives as bars and ticks arrive.
 *
 * A run keeps the transform's state as of the last closed source bar. The
 * newest bar is still forming, and `push` changes state on every call, so each
 * tick is pushed through a copy of that state (`clone`) and the elements it
 * produces are provisional: the next tick throws them away and forms them
 * again. Only when a newer bar arrives is the forming one pushed into the
 * state itself. Pushing every tick into the state instead would bake a price
 * that is gone by the next tick into every element after it.
 *
 * Elements carry strictly increasing times, bumped a second where several form
 * on one bar, exactly as `runTransform` does, so a run's elements are always
 * the batch transform of its source bars.
 */
import { registerSeriesTransform } from 'openalgo-charts';
import type { Bar, IndicatorInput, SeriesTransformRun, SeriesType } from 'openalgo-charts';
import type { ISeriesTransform } from './transform';
import { HeikinAshiTransform } from './heikin-ashi';
import { RenkoTransform } from './renko';
import { RangeBarsTransform } from './range-bars';
import { LineBreakTransform } from './line-break';
import { PointFigureTransform, type PointFigureBoxMode, type PointFigureMethod } from './point-figure';
import { KagiTransform } from './kagi';

type Options = Readonly<Record<string, number | string>>;
type Cloneable = ISeriesTransform & { clone(): ISeriesTransform };

/** Sort by time, keeping the last bar given for a time, as the data layer does. */
function sortedUnique(bars: readonly Bar[]): Bar[] {
  const byTime = new Map<number, Bar>();
  for (const bar of bars) byTime.set(bar.time, bar);
  return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
}

/**
 * A size taken from the loaded history: a fortieth of its price span, so one
 * default suits a penny stock and an index alike, and never under a tenth of
 * a percent of the last close. Two significant figures, so it reads as a
 * number a trader would pick.
 */
function historyBox(bars: readonly Bar[]): number {
  let high = -Infinity, low = Infinity;
  for (const bar of bars) { if (bar.high > high) high = bar.high; if (bar.low < low) low = bar.low; }
  const size = Math.max((high - low) / 40, Math.abs(bars[bars.length - 1]?.close ?? 0) / 1000);
  return size > 0 && Number.isFinite(size) ? Number(size.toPrecision(2)) : 1;
}

/** An option given as a positive size, or the one taken from history. */
const sized = (value: number | string | undefined, history: () => number): number =>
  typeof value === 'number' && value > 0 ? value : history();

class LiveTransform implements SeriesTransformRun {
  private _source: Bar[] = [];
  /** The state after every source bar but the newest, or null before any bar. */
  private _state: Cloneable | null = null;
  /** Committed elements first, then the forming bar's: one array, so a tick rewrites its tail alone. */
  private readonly _elements: Bar[] = [];
  private readonly _index: number[] = [];
  private _committed = 0;
  /** The options with every size resolved, fixed from the load until the next one. */
  private _resolved: Options | null = null;

  public constructor(
    private readonly _given: Options,
    private readonly _resolve: (given: Options, bars: readonly Bar[]) => Options,
    private readonly _make: (options: Options) => Cloneable,
    private readonly _oneToOne: boolean,
  ) {}

  public setData(bars: readonly Bar[]): void {
    this._source = sortedUnique(bars);
    this._resolved = null;
    this._rebuild();
  }

  public prepend(bars: readonly Bar[]): void {
    this._source = sortedUnique([...this._source, ...bars]);
    this._rebuild();
  }

  public update(bar: Bar): number {
    const n = this._source.length;
    const last = this._source[n - 1];
    if (last === undefined || bar.time < last.time) {
      // The first bar, or a correction of history: every element after it can move.
      this._source = sortedUnique([...this._source, bar]);
      this._rebuild();
      return 0;
    }
    const from = this._committed;
    if (bar.time > last.time) {
      this._commit(n - 1);
      this._source.push(bar);
    } else {
      this._source[n - 1] = bar;
    }
    this._formTail();
    return from;
  }

  public source(): readonly Bar[] { return this._source; }

  public elements(): readonly Bar[] { return this._elements; }

  public sourceIndex(): readonly number[] | null { return this._oneToOne ? null : this._index; }

  private _rebuild(): void {
    this._elements.length = 0;
    this._index.length = 0;
    this._committed = 0;
    const n = this._source.length;
    if (n === 0) { this._state = null; return; }
    this._resolved ??= this._resolve(this._given, this._source);
    this._state = this._make(this._resolved);
    for (let i = 0; i < n - 1; i++) this._commit(i);
    this._formTail();
  }

  /** Push a closed bar into the state, replacing the provisional tail with what it completes. */
  private _commit(i: number): void {
    this._elements.length = this._committed;
    this._index.length = this._committed;
    for (const element of this._state!.push(this._source[i]!)) this._append(element, i);
    this._committed = this._elements.length;
  }

  /** The forming bar's elements, and whatever is still in progress, from a copy of the state. */
  private _formTail(): void {
    this._elements.length = this._committed;
    this._index.length = this._committed;
    const n = this._source.length;
    if (n === 0 || this._state === null) return;
    const probe = this._state.clone();
    for (const element of probe.push(this._source[n - 1]!)) this._append(element, n - 1);
    for (const element of probe.flush?.() ?? []) this._append(element, n - 1);
  }

  private _append(element: Bar, sourceIndex: number): void {
    const previous = this._elements[this._elements.length - 1]?.time ?? -Infinity;
    this._elements.push(element.time > previous ? element : { ...element, time: previous + 1 });
    this._index.push(sourceIndex);
  }
}

/**
 * The options a spec gives, checked against the transform's own inputs: a key
 * it does not declare, or a value outside what the input allows, throws before
 * a run exists, so a bad spec never leaves a series half changed.
 */
function checked(type: string, inputs: readonly IndicatorInput[], options: Options): Options {
  const fail = (reason: string): never => { throw new TypeError(`openalgo-charts: invalid series transform: ${reason}`); };
  if (options === null || typeof options !== 'object' || Array.isArray(options)) fail('options must be an object');
  const out: Record<string, number | string> = {};
  for (const [key, value] of Object.entries(options)) {
    const input = inputs.find(item => item.key === key);
    if (input === undefined) fail(`${type} option "${key}" is not one it takes`);
    const ok = input!.type === 'number'
      ? typeof value === 'number' && Number.isFinite(value) && (input!.min === undefined || value >= input!.min)
        && (input!.max === undefined || value <= input!.max) && (input!.step !== 1 || Number.isInteger(value))
      : input!.type === 'select' && input!.options.some(option => option.value === value);
    if (!ok) fail(`${type} option "${key}" cannot be ${String(value)}`);
    out[key] = value;
  }
  return out;
}

/** The history-sized option, with its 0 standing for "from history". */
const historySize = (key: string, label: string): IndicatorInput =>
  ({ key, type: 'number', label: `${label} (0 = from history)`, default: 0, min: 0 });

/**
 * Register one transform. Its options are validated against its own inputs
 * before a run exists, so a bad spec throws before any series changes.
 */
function define(
  type: string, name: string, renderer: SeriesType, inputs: readonly IndicatorInput[],
  resolve: (given: Options, bars: readonly Bar[]) => Options, make: (options: Options) => Cloneable, oneToOne = false,
): void {
  registerSeriesTransform(type, {
    name, renderer, inputs,
    create: (options) => new LiveTransform(checked(type, inputs, options), resolve, make, oneToOne),
  });
}

const num = (options: Options, key: string): number => options[key] as number;

/** Register the six transforms a chart can apply itself. Idempotent, like the renderers beside it. */
export function registerSeriesTransforms(): void {
  define('heikin-ashi', 'Heikin Ashi', 'candlestick', [], () => ({}), () => new HeikinAshiTransform(), true);
  const atr = { key: 'mode', is: 'atr' } as const;
  const percentOf = { key: 'mode', is: ['percent', 'atrPercent'] } as const;
  // One sizing schema for Renko and point and figure, so a host renders one form for both.
  const boxInputs: readonly IndicatorInput[] = [
    { key: 'mode', type: 'select', label: 'Box size from', default: 'fixed', options: [
      { label: 'Fixed size', value: 'fixed' }, { label: 'Percent of price', value: 'percent' }, { label: 'ATR', value: 'atr' },
      { label: 'Percent of ATR', value: 'atrPercent' }] },
    { ...historySize('boxSize', 'Box size'), visibleWhen: { key: 'mode', is: 'fixed' } },
    { key: 'percent', type: 'number', label: 'Box percent', default: 1, min: 0, visibleWhen: percentOf },
    { key: 'atrPeriod', type: 'number', label: 'ATR length', default: 14, min: 1, step: 1, visibleWhen: { key: 'mode', is: ['atr', 'atrPercent'] } },
    { key: 'atrMultiplier', type: 'number', label: 'ATR multiplier', default: 1, min: 0, visibleWhen: atr },
  ];
  const boxResolved = (given: Options, bars: readonly Bar[]): Options => {
    const mode = (given.mode ?? 'fixed') as PointFigureBoxMode;
    return {
      ...given, mode,
      ...(mode === 'fixed' ? { boxSize: sized(given.boxSize, () => historyBox(bars)) } : {}),
      ...(mode === 'percent' || mode === 'atrPercent' ? { percent: sized(given.percent, () => 1) } : {}),
    };
  };
  const boxOptions = (o: Options) => ({
    mode: o.mode as PointFigureBoxMode, boxSize: o.boxSize as number | undefined, percent: o.percent as number | undefined,
    atrPeriod: o.atrPeriod as number | undefined, atrMultiplier: o.atrMultiplier as number | undefined,
  });
  define('renko', 'Renko', 'candlestick', [...boxInputs,
    { key: 'method', type: 'select', label: 'Prices', default: 'close', options: [
      { label: 'Close', value: 'close' }, { label: 'High and low', value: 'hl' }] },
  ], boxResolved, (o) => new RenkoTransform({ ...boxOptions(o), method: o.method as 'close' | 'hl' | undefined }));
  // Twice the box, the proportion the reference host always used for both.
  define('range-bars', 'Range bars', 'candlestick', [historySize('range', 'Range')],
    (given, bars) => ({ range: sized(given.range, () => historyBox(bars) * 2) }),
    (o) => new RangeBarsTransform({ range: num(o, 'range') }));
  define('line-break', 'Line break', 'candlestick', [{ key: 'lines', type: 'number', label: 'Lines to break', default: 3, min: 1, step: 1 }],
    (given) => ({ lines: given.lines ?? 3 }),
    (o) => new LineBreakTransform({ lines: num(o, 'lines') }));
  define('point-figure', 'Point and figure', 'point-figure', [...boxInputs,
    { key: 'reversal', type: 'number', label: 'Reversal boxes', default: 3, min: 1, step: 1 },
    { key: 'method', type: 'select', label: 'Prices', default: 'hl', options: [
      { label: 'High and low', value: 'hl' }, { label: 'Close', value: 'close' }] },
  ], boxResolved, (o) => new PointFigureTransform({
    ...boxOptions(o), reversal: o.reversal as number | undefined, method: o.method as PointFigureMethod | undefined,
  }));
  define('kagi', 'Kagi', 'kagi', [historySize('reversal', 'Reversal')],
    (given, bars) => ({ reversal: sized(given.reversal, () => historyBox(bars) * 2) }),
    (o) => new KagiTransform({ reversal: num(o, 'reversal') }));
}
