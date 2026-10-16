/**
 * A study on the bars under a transform that is not one element per bar reads
 * its values at the source bar each element was completed on, so every element
 * one source bar completed reads that bar. Its alerts judge such a bar once, at
 * the first element it completed, whatever the frequency: a second brick from
 * the same bar is not a second bar of the study. On the chart's own bars each
 * brick is a bar of its own and is still judged one by one, and Heikin Ashi,
 * one candle per bar, reads nothing across.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  Chart, generateBars, registerIndicator,
  type Bar, type IndicatorAlertFrequency, type IndicatorAlertPayload, type IndicatorCalcContext,
  type SeriesTransformSpec,
} from '../src/index';
import { registerTransformChartTypes, runTransform, RenkoTransform } from '../src/transform/index';
import { fakeDocument } from './helpers/fake-dom';

registerTransformChartTypes();

const BOX = 0.5;
const RENKO: SeriesTransformSpec = { type: 'renko', options: { boxSize: BOX } };
const HEIKIN_ASHI: SeriesTransformSpec = { type: 'heikin-ashi' };
const KAGI: SeriesTransformSpec = { type: 'kagi', options: { reversal: 2 } };
const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

/** Five hours of one-minute bars from a seeded random walk. */
const history = (): Bar[] => generateBars(1_700_000_040, 300, 60);
const last = <T>(items: readonly T[]): T => items[items.length - 1]!;
/** The close of the last brick the bars complete, which the next brick grows from. */
const edge = (bars: readonly Bar[]): number => last(runTransform(new RenkoTransform({ boxSize: BOX }), bars)).close;

/** The next minute's bar, opening at the last close and closing `boxes` boxes above the last brick. */
function rising(bars: readonly Bar[], boxes: number): Bar {
  const prior = last(bars), close = edge(bars) + boxes * BOX;
  return { time: prior.time + 60, open: prior.close, high: Math.max(prior.close, close), low: Math.min(prior.close, close), close };
}

/** The same bar ticked `boxes` boxes higher. */
const higher = (bar: Bar, boxes: number): Bar => ({ ...bar, close: bar.close + boxes * BOX, high: bar.high + boxes * BOX });

/** The next minute's bar, flat at the last close: on a Renko chart it completes nothing. */
function flat(bars: readonly Bar[]): Bar {
  const prior = last(bars);
  return { time: prior.time + 60, open: prior.close, high: prior.close, low: prior.close, close: prior.close };
}

/**
 * A study that flags a bar closing above its open, with an alert on it whose
 * message names the bar it read: the source bar on the underlying bars, the
 * brick on the chart's. `states` collects what each calculation was told.
 */
function risingStudy(frequency?: IndicatorAlertFrequency, states?: IndicatorCalcContext['barState'][]): string {
  const id = `underlying-bars-${sequence++}`;
  registerIndicator({
    id, name: 'Rising bar', placement: 'onchart', inputs: [],
    plots: [{ key: 'up', type: 'line', title: 'Rising' }],
    calc: (bars, _settings, _store, ctx) => {
      if (ctx) states?.push(ctx.barState);
      return { up: bars.map(bar => bar.close > bar.open ? 1 : 0), at: bars.map(bar => bar.time) };
    },
    alerts: [{
      id: 'rising', title: 'Rising bar', ...(frequency === undefined ? {} : { frequency }),
      when: ({ values, index }) => values.up![index] === 1,
      message: ({ values, index }) => `bar ${values.at![index]}`,
    }],
  });
  return id;
}

/**
 * A chart with the transform switched on over a loaded history, whose
 * recompute waits for a read, so every write between two reads lands in one
 * pass. The clock stands half a minute into the newest bar, as it does live.
 */
function mount(spec: SeriesTransformSpec, bars = history()) {
  const document = fakeDocument();
  const clock = { now: last(bars).time + 90 };
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, timezone: 'Etc/UTC',
    axisChrome: { clock: () => clock.now }, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
  const series = chart.addSeries('candlestick');
  series.setData(bars);
  chart.setSeriesTransform(series, spec);
  const events: IndicatorAlertPayload[] = [];
  chart.on('indicator:alert', payload => events.push(payload as IndicatorAlertPayload));
  const feed = (bar: Bar): void => { clock.now = bar.time + 30; series.update(bar); };
  return { chart, bars, events, feed };
}

const summary = (events: readonly IndicatorAlertPayload[]) => events.map(e => ({ index: e.index, time: e.time, message: e.message }));

describe('alerts on the bars under a Renko chart', () => {
  it('judges a source bar that completes two bricks once, at the first brick', () => {
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy(), {}, { barSource: 'underlying' });
    const before = h.chart.primaryBars().length;
    const next = rising(h.bars, 2.2);
    h.feed(next);
    study.values();
    const bricks = h.chart.primaryBars();
    expect(bricks).toHaveLength(before + 2);
    expect(summary(h.events)).toEqual([{ index: before, time: bricks[before]!.time, message: `bar ${next.time}` }]);
    // A later tick on the same bar completes a third brick: that bar was judged already.
    h.feed(higher(next, 1));
    study.values();
    expect(h.chart.primaryBars()).toHaveLength(before + 3);
    expect(h.events).toHaveLength(1);
  });

  it('judges each source bar of a pass once, however many bricks each completed', () => {
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy(), {}, { barSource: 'underlying' });
    const before = h.chart.primaryBars().length;
    const first = rising(h.bars, 2.2);
    const second = rising([...h.bars, first], 1.2);
    h.feed(first);
    h.feed(second);
    study.values();
    const bricks = h.chart.primaryBars();
    expect(bricks).toHaveLength(before + 3);
    expect(summary(h.events)).toEqual([
      { index: before, time: bricks[before]!.time, message: `bar ${first.time}` },
      { index: before + 2, time: bricks[before + 2]!.time, message: `bar ${second.time}` },
    ]);
  });

  it('judges the bars after a reload onto a history that ends earlier', () => {
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy(), {}, { barSource: 'underlying' });
    h.feed(rising(h.bars, 2.2));
    study.values();
    expect(h.events).toHaveLength(1);
    // A reload ending fifty bars back, as another interval or symbol would: it
    // seeds silently, and the next bar, older than the one judged, is judged.
    const shorter = h.bars.slice(0, 250);
    h.chart.primarySeries()!.setData(shorter);
    study.values();
    expect(h.events).toHaveLength(1);
    const next = rising(shorter, 2.2);
    h.feed(next);
    study.values();
    expect(summary(h.events.slice(1)).map(e => e.message)).toEqual([`bar ${next.time}`]);
  });

  it.each([
    // Two bricks; the same bar ticks on; it completes a third; the next bar completes nothing.
    ['oncePerBar', [1, 0, 0, 0]],
    // Each update of the bar is judged once, and a bar no brick reads is not judged at all.
    ['everyUpdate', [1, 1, 1, 0]],
  ] as [IndicatorAlertFrequency, number[]][])('judges each update of a source bar once for a %s alert', (frequency, expected) => {
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy(frequency), {}, { barSource: 'underlying' });
    const before = h.chart.primaryBars().length;
    const next = rising(h.bars, 2.2);
    const delivered: number[] = [];
    for (const bar of [next, higher(next, 0.2), higher(next, 1), flat([...h.bars, higher(next, 1)])]) {
      const count = h.events.length;
      h.feed(bar);
      study.values();
      delivered.push(h.events.length - count);
    }
    expect(h.chart.primaryBars()).toHaveLength(before + 3);
    expect(delivered).toEqual(expected);
    expect(h.events.every(e => e.message === `bar ${next.time}`)).toBe(true);
    expect(h.events[0]!.index).toBe(before);
  });

  it('closes a source bar that completed two bricks once, and only after it closed', () => {
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy('onBarClose'), {}, { barSource: 'underlying' });
    const before = h.chart.primaryBars().length;
    const next = rising(h.bars, 2.2);
    h.feed(next);
    study.values();
    // Both bricks read a bar that is still forming: nothing has closed.
    expect(h.events).toEqual([]);
    // The next minute completes nothing, and the bar under the two bricks has closed.
    const pause = flat([...h.bars, next]);
    h.feed(pause);
    study.values();
    const bricks = h.chart.primaryBars();
    expect(bricks).toHaveLength(before + 2);
    expect(summary(h.events)).toEqual([{ index: before, time: bricks[before]!.time, message: `bar ${next.time}` }]);
    // A brick from a later bar: the two before it read a bar already closed and judged.
    h.feed(rising([...h.bars, next, pause], 1.2));
    study.values();
    expect(h.chart.primaryBars()).toHaveLength(before + 3);
    expect(h.events).toHaveLength(1);
  });

  it('tells the calculation the bar is new once, however many bricks it completes', () => {
    const states: IndicatorCalcContext['barState'][] = [];
    const h = mount(RENKO);
    const study = h.chart.addIndicator(risingStudy(undefined, states), {}, { barSource: 'underlying' });
    const next = rising(h.bars, 2.2);
    const told: [boolean, boolean, number][] = [];
    for (const bar of [next, higher(next, 1)]) {
      states.length = 0;
      h.feed(bar);
      study.values();
      told.push(...states.map(s => [s.isNew, s.isRealtime, s.lastIndex] as [boolean, boolean, number]));
    }
    expect(told).toEqual([[true, true, h.bars.length], [false, true, h.bars.length]]);
  });

  it.each([undefined, 'oncePerBar', 'everyUpdate'] as (IndicatorAlertFrequency | undefined)[])(
    'still judges each brick on the chart\'s own bars (frequency %s)', frequency => {
      const h = mount(RENKO);
      const study = h.chart.addIndicator(risingStudy(frequency), {}, { barSource: 'chart' });
      const before = h.chart.primaryBars().length;
      h.feed(rising(h.bars, 2.2));
      study.values();
      const bricks = h.chart.primaryBars();
      expect(summary(h.events)).toEqual([before, before + 1].map(i => ({ index: i, time: bricks[i]!.time, message: `bar ${bricks[i]!.time}` })));
    },
  );
});

describe('alerts on the bars under a Kagi chart', () => {
  /** Minute `i` of the history, opening at `open`, with a small wick either side. */
  const minute = (i: number, open: number, close: number): Bar =>
    ({ time: 1_700_000_040 + i * 60, open, close, high: Math.max(open, close) + 0.05, low: Math.min(open, close) - 0.05 });
  // Reversal 2: the line turns down at 104, up at 100, and is still rising at
  // 105, so its vertices are 104, 100 and 105, the last one forming. The bars
  // fed after it extend that rise three times, each rising, and the fourth
  // turns the line down.
  const closes = [104, 101, 100, 103, 105];
  const feed = [[105, 106], [106, 107], [107, 107.5], [107.5, 104]].map(([open, close], k) => minute(5 + k, open!, close!));

  it.each([
    // Each rising bar the forming vertex reads is a bar of the study: one delivery each.
    ['oncePerBar', [5, 6, 7]],
    // An omitted frequency judges a new vertex only, and the rise added none.
    [undefined, []],
  ] as [IndicatorAlertFrequency | undefined, number[]][])('delivers a %s alert once for each bar the forming vertex reads', (frequency, expected) => {
    const h = mount(KAGI, closes.map((close, i) => minute(i, closes[i - 1] ?? close, close)));
    const study = h.chart.addIndicator(risingStudy(frequency), {}, { barSource: 'underlying' });
    expect(h.chart.primaryBars().map(bar => bar.close)).toEqual([104, 100, 105]);
    for (const bar of feed) {
      h.feed(bar);
      study.values();
    }
    expect(h.chart.primaryBars().map(bar => bar.close)).toEqual([104, 100, 107.5, 104]);
    expect(summary(h.events)).toEqual(expected.map(i => ({ index: 2, time: feed[i - 5]!.time, message: `bar ${feed[i - 5]!.time}` })));
  });
});

describe('alerts on the bars under a Heikin Ashi chart', () => {
  it.each([undefined, 'oncePerBar', 'everyUpdate'] as (IndicatorAlertFrequency | undefined)[])(
    'judges each source bar once, one candle per bar (frequency %s)', frequency => {
      const h = mount(HEIKIN_ASHI);
      const study = h.chart.addIndicator(risingStudy(frequency), {}, { barSource: 'underlying' });
      const bars = [...h.bars];
      const fed: Bar[] = [];
      for (const boxes of [1.4, 0.6, -2, 1.1]) {
        const prior = last(bars), close = prior.close + boxes * BOX;
        const bar = { time: prior.time + 60, open: prior.close, high: Math.max(prior.close, close), low: Math.min(prior.close, close), close };
        bars.push(bar);
        fed.push(bar);
        h.feed(bar);
        study.values();
      }
      const up = fed.filter(bar => bar.close > bar.open);
      expect(h.events.map(e => [e.time, e.message])).toEqual(up.map(bar => [bar.time, `bar ${bar.time}`]));
    },
  );
});
