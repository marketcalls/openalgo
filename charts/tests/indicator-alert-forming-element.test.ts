/**
 * On an in-chart Kagi or range bar chart the element still forming is dated at
 * the newest source bar, so each newer source bar dates it again, forward, at
 * the same index. That is a revision of the forming element, plus whatever the
 * bar appended after it, not a correction: a study alert judges each new
 * element once, the calculation is told the bar is live and whether it is new,
 * and the tail path stays open. A real correction (an element before the
 * forming one changed, an element dated backward, fewer elements) still seeds
 * the alerts silently.
 */
import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import {
  Chart, generateBars, registerIndicator, registerSeriesTransform,
  type Bar, type IndicatorAlertFrequency, type IndicatorAlertPayload, type IndicatorBarSource, type IndicatorCalcContext,
  type SeriesTransformSpec,
} from '../src/index';
import { registerTransformChartTypes } from '../src/transform/index';
import { fakeDocument } from './helpers/fake-dom';

registerTransformChartTypes();

const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

/** Five-minute bars from 1 October 2026, 09:15 IST. */
const START = Date.UTC(2026, 9, 1, 3, 45) / 1000;
const at = (i: number): number => START + i * 300;

/** Source bar `i`, opening at `open`, with a small wick either side. */
function source(i: number, open: number, close: number): Bar {
  return { time: at(i), open, close, high: Math.max(open, close) + 0.05, low: Math.min(open, close) - 0.05, volume: 41_000 + i * 700 };
}

/** Consecutive source bars from bar `first`, each opening at the close before it. */
const session = (closes: readonly number[], first = 0, open = closes[0]!): Bar[] =>
  closes.map((close, k) => source(first + k, k === 0 ? open : closes[k - 1]!, close));

/**
 * Kagi, reversal 2. The history turns down at 104, up at 100 and is still
 * rising at 105, so its vertices are 104, 100 and 105, the last one forming.
 * The bars fed after it: 106 extends that rise, 103 turns the line down at 106,
 * 102 extends the fall, 104.5 turns it up at 102, and 105 extends the rise.
 * Every one of them dates the forming vertex again.
 */
const KAGI: SeriesTransformSpec = { type: 'kagi', options: { reversal: 2 } };
const KAGI_HISTORY = session([104, 101, 100, 103, 105]);
const KAGI_FEED = session([106, 103, 102, 104.5, 105], 5, 105);

/**
 * Range bars, range 2. The history completes one bar at 102.2 and starts the
 * next at 101.5. The bars fed after it extend that bar twice, complete it at
 * 103, start a new one at 103.4 and extend it.
 */
const RANGE: SeriesTransformSpec = { type: 'range-bars', options: { range: 2 } };
const RANGE_HISTORY = session([100, 100.5, 101, 102.2, 101.5]);
const RANGE_FEED = session([102, 100.8, 103, 103.4, 102.9], 5, 101.5);

/**
 * A chart whose recompute waits for a read, so each source bar is one pass,
 * with the transform switched on over a loaded history as a trader does. The
 * clock stands halfway into the newest source bar, as it does live, or for
 * `late` bars fed long after they traded, past all of them.
 */
function mount(spec: SeriesTransformSpec, history: readonly Bar[], late = false) {
  const document = fakeDocument();
  const clock = { now: late ? at(1000) : history[history.length - 1]!.time + 150 };
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, timezone: 'Asia/Kolkata',
    axisChrome: { clock: () => clock.now }, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', interval: '5m' });
  const series = chart.addSeries('candlestick');
  series.setData(history);
  chart.setSeriesTransform(series, spec);
  const events: IndicatorAlertPayload[] = [];
  chart.on('indicator:alert', payload => events.push(payload as IndicatorAlertPayload));
  /** One more source bar, halfway into it, and the pass it starts. */
  const feed = (bar: Bar, read: () => unknown): void => {
    if (!late) clock.now = bar.time + 150;
    series.update(bar);
    read();
  };
  return { chart, series, events, feed };
}

/**
 * A study with an alert on every new element and one on an element whose
 * close crosses `level`, either way. The message carries the close and how
 * many bars the context held, so a test sees that it ended at the element.
 */
function crossStudy(level: number, frequency?: IndicatorAlertFrequency): string {
  const id = `forming-element-${sequence++}`;
  const message = ({ bars, index }: { bars: readonly Bar[]; index: number }): string => `${bars[index]!.close} at ${index + 1} of ${bars.length}`;
  const timing = frequency === undefined ? {} : { frequency };
  registerIndicator({
    id, name: 'Element cross', placement: 'onchart', inputs: [],
    plots: [{ key: 'close', type: 'line', title: 'Close' }],
    calc: bars => ({ close: bars.map(bar => bar.close) }),
    alerts: [
      { id: 'element', title: 'New element', ...timing, when: () => true, message },
      {
        id: 'cross', title: `Crossed ${level}`, ...timing, message,
        when: ({ bars, index }) => index > 0 && (bars[index - 1]!.close - level) * (bars[index]!.close - level) < 0,
      },
    ],
  });
  return id;
}

const summary = (events: readonly IndicatorAlertPayload[]) => events.map(e => ({ alertId: e.alertId, index: e.index, time: e.time, message: e.message }));
const closes = (chart: Chart): number[] => chart.primaryBars().map(bar => bar.close);

describe('study alerts on an in-chart Kagi chart', () => {
  it.each(['chart', 'underlying'] as IndicatorBarSource[])('judges each new vertex once through a reversal, on %s bars', barSource => {
    const h = mount(KAGI, KAGI_HISTORY);
    expect(closes(h.chart)).toEqual([104, 100, 105]);
    const study = h.chart.addIndicator(crossStudy(105.5), {}, { barSource });
    const read = () => study.values();
    const fired: ReturnType<typeof summary>[] = [];
    for (const bar of KAGI_FEED) {
      const before = h.events.length;
      h.feed(bar, read);
      fired.push(summary(h.events.slice(before)));
    }
    const vertices = h.chart.primaryBars();
    expect(vertices.map(bar => bar.close)).toEqual([104, 100, 106, 102, 105]);
    // The turning points are dated at the bar that turned the line.
    expect(vertices.map(bar => bar.time)).toEqual([at(1), at(3), at(6), at(8), at(9)]);
    // 106 and 102 only move the forming vertex: nothing new to judge, and the
    // revised vertex is not judged again (100 to 106 would cross 105.5).
    expect(fired).toEqual([
      [],
      [
        { alertId: 'element', index: 3, time: at(6) + 1, message: '103 at 4 of 4' },
        { alertId: 'cross', index: 3, time: at(6) + 1, message: '103 at 4 of 4' },
      ],
      [],
      [{ alertId: 'element', index: 4, time: at(8) + 1, message: '104.5 at 5 of 5' }],
      [],
    ]);
  });

  it.each([
    ['everyUpdate', [2, 3, 3, 4, 4]],
    ['oncePerBar', [2, 3, 4]],
    ['once', [2]],
    ['onBarClose', [2, 3]],
  ] as [IndicatorAlertFrequency, number[]][])('judges a %s alert on the forming vertex as one element', (frequency, expected) => {
    const h = mount(KAGI, KAGI_HISTORY);
    const study = h.chart.addIndicator(crossStudy(1000, frequency));
    for (const bar of KAGI_FEED) h.feed(bar, () => study.values());
    expect(h.events.filter(e => e.alertId === 'element').map(e => e.index)).toEqual(expected);
  });

  it('judges the first reversal after a history of one vertex', () => {
    // Two bars make one vertex, still forming, and the bars after date it again until the line turns.
    const h = mount(KAGI, session([100, 101]));
    expect(closes(h.chart)).toEqual([101]);
    const study = h.chart.addIndicator(crossStudy(1000));
    for (const bar of session([101.5, 99], 2, 101)) h.feed(bar, () => study.values());
    expect(closes(h.chart)).toEqual([101.5, 99]);
    expect(h.events.map(e => ({ alertId: e.alertId, index: e.index, time: e.time }))).toEqual([{ alertId: 'element', index: 1, time: at(3) + 1 }]);
  });

  it('closes each vertex once when the clock has passed every bar', () => {
    // The clock confirms the forming vertex as it appears, so a close alert
    // judges it then, and not again as each newer bar dates it later.
    const h = mount(KAGI, KAGI_HISTORY, true);
    const study = h.chart.addIndicator(crossStudy(1000, 'onBarClose'));
    for (const bar of KAGI_FEED) h.feed(bar, () => study.values());
    expect(h.events.filter(e => e.alertId === 'element').map(e => ({ index: e.index, time: e.time })))
      .toEqual([{ index: 3, time: at(6) + 1 }, { index: 4, time: at(8) + 1 }]);
  });

  it('stays silent when a tick takes a provisional vertex back, and judges it when it forms again', () => {
    const h = mount(KAGI, KAGI_HISTORY);
    const study = h.chart.addIndicator(crossStudy(1000));
    const read = () => study.values();
    h.feed(KAGI_FEED[0]!, read);
    // The next bar's first tick turns the line at 106; its second takes the turn back.
    h.feed(source(6, 106, 103), read);
    expect(h.events.map(e => e.index)).toEqual([3]);
    h.feed(source(6, 106, 105), read);
    expect(closes(h.chart)).toEqual([104, 100, 106]);
    expect(h.events).toHaveLength(1);
    // The bar after turns it at 106 again: a new vertex, judged as one.
    h.feed(source(7, 105, 103.5), read);
    expect(closes(h.chart)).toEqual([104, 100, 106, 103.5]);
    expect(h.events.map(e => ({ index: e.index, time: e.time }))).toEqual([{ index: 3, time: at(6) + 1 }, { index: 3, time: at(7) + 1 }]);
  });
});

describe('study alerts on an in-chart range bar chart', () => {
  it('judges each new range bar once while the forming one is extended and completed', () => {
    const h = mount(RANGE, RANGE_HISTORY);
    expect(h.chart.primaryBars().map(bar => [bar.time, bar.close])).toEqual([[at(3), 102.2], [at(4), 101.5]]);
    const study = h.chart.addIndicator(crossStudy(103.2));
    for (const bar of RANGE_FEED) h.feed(bar, () => study.values());
    expect(h.chart.primaryBars().map(bar => [bar.time, bar.high, bar.low, bar.close])).toEqual([
      [at(3), 102.2, 100, 102.2], [at(7), 103, 100.8, 103], [at(9), 103.4, 102.9, 102.9],
    ]);
    expect(summary(h.events)).toEqual([
      { alertId: 'element', index: 2, time: at(8), message: '103.4 at 3 of 3' },
      { alertId: 'cross', index: 2, time: at(8), message: '103.4 at 3 of 3' },
    ]);
  });

  it.each([
    ['everyUpdate', [1, 1, 1, 2, 2]],
    ['oncePerBar', [1, 2]],
    ['once', [1]],
    ['onBarClose', [1]],
  ] as [IndicatorAlertFrequency, number[]][])('judges a %s alert on the forming range bar as one element', (frequency, expected) => {
    const h = mount(RANGE, RANGE_HISTORY);
    const study = h.chart.addIndicator(crossStudy(1000, frequency));
    for (const bar of RANGE_FEED) h.feed(bar, () => study.values());
    expect(h.events.filter(e => e.alertId === 'element').map(e => e.index)).toEqual(expected);
  });
});

/** A study that records what each calculation was told, and the tail calls it took. */
function observer() {
  const id = `forming-observer-${sequence++}`;
  const seen: { isNew: boolean; isRealtime: boolean; change?: string; provenance?: string }[] = [];
  const record = (ctx?: IndicatorCalcContext): void => {
    seen.push({ isNew: ctx!.barState.isNew, isRealtime: ctx!.barState.isRealtime, change: ctx!.execution?.change, provenance: ctx!.execution?.provenance });
  };
  let tails = 0;
  registerIndicator({
    id, name: 'Observer', placement: 'onchart', inputs: [],
    plots: [{ key: 'close', type: 'line', title: 'Close' }],
    calc: (bars, _settings, _store, ctx) => { record(ctx); return { close: bars.map(bar => bar.close) }; },
    calcTail: (bars, _settings, from, _previous, _store, ctx) => {
      record(ctx);
      tails++;
      return { close: bars.slice(from).map(bar => bar.close) };
    },
  });
  return { id, seen, tails: () => tails };
}

describe('what a calculation is told on a forming element dated again', () => {
  const revised = { isNew: false, isRealtime: true, change: 'replace', provenance: 'live' };
  const appended = { isNew: true, isRealtime: true, change: 'append', provenance: 'live' };

  it.each([
    ['Kagi', KAGI, KAGI_HISTORY, KAGI_FEED, [revised, appended, revised, appended, revised]],
    ['range bar', RANGE, RANGE_HISTORY, RANGE_FEED, [revised, revised, revised, appended, revised]],
  ] as [string, SeriesTransformSpec, Bar[], Bar[], typeof revised[]][])('says live, new only when an element was appended, and takes the tail on a %s chart',
    (_name, spec, history, feed, expected) => {
      const h = mount(spec, history);
      const probe = observer();
      const study = h.chart.addIndicator(probe.id);
      const first = probe.seen.length;
      for (const bar of feed) h.feed(bar, () => study.values());
      expect(probe.seen.slice(first)).toEqual(expected);
      expect(probe.tails()).toBe(feed.length);
      expect(study.values().close).toEqual(closes(h.chart));
    });

  it('says every source bar is new to a study on the bars under a Kagi chart', () => {
    const h = mount(KAGI, KAGI_HISTORY);
    const probe = observer();
    const study = h.chart.addIndicator(probe.id, {}, { barSource: 'underlying' });
    const first = probe.seen.length;
    for (const bar of KAGI_FEED) h.feed(bar, () => study.values());
    expect(probe.seen.slice(first).map(seen => [seen.isNew, seen.isRealtime, seen.change]))
      .toEqual([[true, true, 'replace'], [true, true, 'append'], [true, true, 'replace'], [true, true, 'append'], [true, true, 'replace']]);
    // Its values are read across onto the vertices, so it takes the full calculation.
    expect(probe.tails()).toBe(0);
  });

  it.each([
    ['Kagi', { type: 'kagi', options: { reversal: 2 } }],
    ['range bar', { type: 'range-bars', options: { range: 2 } }],
  ] as [string, SeriesTransformSpec][])('keeps the built-in tails equal to a full calculation on a %s chart', (_name, spec) => {
    // A seeded random walk: three hundred bars loaded, a hundred more fed one at a time.
    const bars = generateBars(START, 400, 300);
    const live = mount(spec, bars.slice(0, 300));
    const studies = [live.chart.addIndicator('ema', { length: 5 }), live.chart.addIndicator('sma', { length: 4 })];
    for (const bar of bars.slice(300)) live.feed(bar, () => studies.forEach(s => s.values()));
    const loaded = mount(spec, bars);
    expect(closes(live.chart)).toEqual(closes(loaded.chart));
    const full = [loaded.chart.addIndicator('ema', { length: 5 }), loaded.chart.addIndicator('sma', { length: 4 })];
    studies.forEach((study, k) => expect(study.values()).toEqual(full[k]!.values()));
  });
});

/**
 * A transform whose elements the test writes, so each step makes exactly the
 * change it names. A bar written through the series is the cue to read them.
 */
let scripted: Bar[] = [];
registerSeriesTransform('scripted-elements', {
  name: 'Scripted', renderer: 'candlestick', inputs: [],
  create: () => {
    const given: Bar[] = [];
    return {
      setData: bars => { given.splice(0, given.length, ...bars); scripted = [...bars]; },
      prepend: () => {},
      update: bar => { given.push(bar); return 0; },
      source: () => given,
      elements: () => scripted,
      sourceIndex: () => null,
    };
  },
});

describe('a correction on a transformed chart still seeds silently', () => {
  const ELEMENTS = session([100, 101.5, 99.8, 102.4]);
  const redated = { ...ELEMENTS[3]!, time: at(5), close: 102.9, high: 102.95 };
  const newer = source(6, 102.9, 104.1);

  /** The scripted chart, a study with an alert on every new element, and the change the next step recorded. */
  function step(elements: readonly Bar[]) {
    const h = mount({ type: 'scripted-elements' }, ELEMENTS);
    const probe = observer();
    const id = crossStudy(1000);
    const alerts = h.chart.addIndicator(id);
    const study = h.chart.addIndicator(probe.id);
    scripted = [...elements];
    h.feed(newer, () => { alerts.values(); study.values(); });
    expect(h.chart.primaryBars()).toEqual(elements);
    return { events: h.events.filter(e => e.alertId === 'element').map(e => e.index), told: probe.seen[probe.seen.length - 1] };
  }

  it('judges what follows a forming element dated forward', () => {
    expect(step([...ELEMENTS.slice(0, 3), redated, newer])).toEqual({
      events: [4], told: { isNew: true, isRealtime: true, change: 'append', provenance: 'live' },
    });
  });

  it.each([
    ['an element before the forming one changed', [ELEMENTS[0]!, { ...ELEMENTS[1]!, close: 101.2 }, ELEMENTS[2]!, redated, newer]],
    ['the forming element dated backward', [...ELEMENTS.slice(0, 3), { ...ELEMENTS[3]!, time: at(3) - 60 }, newer]],
    ['fewer elements', ELEMENTS.slice(0, 3)],
  ] as [string, Bar[]][])('stays silent when %s', (_name, elements) => {
    expect(step(elements)).toEqual({
      events: [], told: { isNew: false, isRealtime: false, change: 'correction', provenance: 'history' },
    });
  });
});
