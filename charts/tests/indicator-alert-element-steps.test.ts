/**
 * A pass that appends several elements after an unchanged prefix: one source
 * bar that completes two Renko bricks, or a host that writes two elements
 * before the chart recomputes. Each new element is judged in order, exactly as
 * separate appends would judge it, on a context that ends at that element. A
 * pass that replaced history still seeds silently, and a close alert still
 * waits for the forming element to close.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  Chart, generateBars, registerIndicator,
  type Bar, type IndicatorAlertFrequency, type IndicatorAlertPayload, type IndicatorBarSource, type SeriesApi,
} from '../src/index';
import { registerTransformChartTypes, runTransform, RenkoTransform } from '../src/transform/index';
import { fakeDocument } from './helpers/fake-dom';

registerTransformChartTypes();

const BOX = 0.5;
const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

/** Five hours of one-minute bars from a seeded random walk. */
const history = (): Bar[] => generateBars(1_700_000_040, 300, 60);
const renko = (bars: readonly Bar[]): Bar[] => runTransform(new RenkoTransform({ boxSize: BOX }), bars);
const last = (bars: readonly Bar[]): Bar => bars[bars.length - 1]!;

/**
 * A study whose alerts watch the drawn element's close cross a level, one
 * alert per level. The message carries the study's value at the element and
 * how many bars the context held, so a test sees both the sampled value and
 * that the context ended at the element judged.
 */
function crossStudy(levels: readonly number[], frequency?: IndicatorAlertFrequency): string {
  const id = `element-step-${sequence++}`;
  registerIndicator({
    id, name: 'Element cross', placement: 'onchart', inputs: [],
    plots: [{ key: 'close', type: 'line', title: 'Close' }],
    calc: bars => ({ close: bars.map(bar => bar.close) }),
    alerts: levels.map((level, k) => ({
      id: `above-${k}`, title: `Crossed ${level}`, ...(frequency === undefined ? {} : { frequency }),
      when: ({ bars, index }) => index > 0 && bars[index - 1]!.close < level && bars[index]!.close >= level,
      message: ({ bars, values, index }) => `${values.close![index]} at ${index + 1} of ${bars.length}`,
    })),
  });
  return id;
}

/**
 * A chart whose recompute waits for a read, so every write between two reads
 * lands in one pass, the way a frame batches them.
 */
function mount(options: { transform?: boolean; now?: number } = {}) {
  const document = fakeDocument();
  const clock = { now: options.now ?? 2_000_000_000 };
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, timezone: 'Etc/UTC',
    axisChrome: { clock: () => clock.now }, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
  const series: SeriesApi = options.transform
    ? chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } })
    : chart.addSeries('candlestick');
  const events: IndicatorAlertPayload[] = [];
  chart.on('indicator:alert', payload => events.push(payload as IndicatorAlertPayload));
  return { chart, series, events, clock };
}

/**
 * The next minute's bar, closing 2.2 boxes above the last brick: on a Renko
 * chart it completes exactly two up bricks.
 */
function twoBrickBar(bars: readonly Bar[]): Bar {
  const prior = last(bars);
  const close = last(renko(bars)).close + 2.2 * BOX;
  return { time: prior.time + 60, open: prior.close, high: Math.max(prior.close, close), low: Math.min(prior.close, close), close };
}

/** The levels the two new bricks cross: half a box above the last brick's close, then one and a half. */
const levelsAbove = (bars: readonly Bar[]): number[] => {
  const edge = last(renko(bars)).close;
  return [edge + BOX / 2, edge + 1.5 * BOX];
};

const summary = (events: readonly IndicatorAlertPayload[]) => events.map(e => ({ alertId: e.alertId, time: e.time, index: e.index, message: e.message }));

describe('alerts on a pass that appends several elements', () => {
  it.each(['chart', 'underlying'] as IndicatorBarSource[])('judges each brick one source bar completes, on %s bars', barSource => {
    const bars = history();
    const h = mount({ transform: true });
    h.series.setData(bars);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars)), {}, { barSource });
    expect(h.events).toEqual([]);
    const before = h.chart.primaryBars().length;

    const next = twoBrickBar(bars);
    h.series.update(next);
    study.values();
    const bricks = h.chart.primaryBars();
    expect(bricks.length).toBe(before + 2);
    // On the chart's bars each brick is a bar of the study, judged in turn, and
    // the value is the brick's close. On the underlying bars both bricks read
    // the source bar that completed them, which is judged once, at the first.
    const value = (i: number): number => barSource === 'chart' ? bricks[i]!.close : next.close;
    const n = bricks.length;
    expect(summary(h.events)).toEqual([
      { alertId: 'above-0', time: bricks[n - 2]!.time, index: n - 2, message: `${value(n - 2)} at ${n - 1} of ${n - 1}` },
      ...barSource === 'chart'
        ? [{ alertId: 'above-1', time: bricks[n - 1]!.time, index: n - 1, message: `${value(n - 1)} at ${n} of ${n}` }] : [],
    ]);
    expect(h.events.every(e => e.indicatorId === study.indicatorId && e.instanceId === study.id)).toBe(true);

    // The forming bar ticks on without completing another brick: nothing new to judge.
    const judged = h.events.length;
    h.series.update({ ...next, close: next.close + 0.1, high: next.high + 0.1 });
    study.values();
    expect(h.events).toHaveLength(judged);
  });

  it('judges each element a host writes before the chart recomputes', () => {
    const bars = history();
    const next = twoBrickBar(bars);
    const all = renko([...bars, next]);
    const shown = renko(bars);
    expect(all.length).toBe(shown.length + 2);
    const h = mount();
    h.series.setData(shown);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars)));
    h.series.update(all[all.length - 2]!);
    h.series.update(all[all.length - 1]!);
    expect(h.events).toEqual([]);
    study.values();
    const n = all.length;
    expect(summary(h.events)).toEqual([
      { alertId: 'above-0', time: all[n - 2]!.time, index: n - 2, message: `${all[n - 2]!.close} at ${n - 1} of ${n - 1}` },
      { alertId: 'above-1', time: all[n - 1]!.time, index: n - 1, message: `${all[n - 1]!.close} at ${n} of ${n}` },
    ]);
  });

  it.each(['everyUpdate', 'oncePerBar', 'once'] as IndicatorAlertFrequency[])('judges each new brick for a %s alert', frequency => {
    const bars = history();
    const h = mount({ transform: true });
    h.series.setData(bars);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars), frequency));
    const next = twoBrickBar(bars);
    h.series.update(next);
    study.values();
    const bricks = h.chart.primaryBars(), n = bricks.length;
    expect(summary(h.events)).toEqual([
      { alertId: 'above-0', time: bricks[n - 2]!.time, index: n - 2, message: `${bricks[n - 2]!.close} at ${n - 1} of ${n - 1}` },
      { alertId: 'above-1', time: bricks[n - 1]!.time, index: n - 1, message: `${bricks[n - 1]!.close} at ${n} of ${n}` },
    ]);
  });

  it('closes the first brick at once and the forming one only when it closes', () => {
    const bars = history();
    const next = twoBrickBar(bars);
    // Half a minute into the new bar: the brick it formed last is still forming.
    const h = mount({ transform: true, now: next.time + 30 });
    h.series.setData(bars);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars), 'onBarClose'));
    h.series.update(next);
    study.values();
    const bricks = h.chart.primaryBars(), n = bricks.length;
    expect(summary(h.events)).toEqual([
      { alertId: 'above-0', time: bricks[n - 2]!.time, index: n - 2, message: `${bricks[n - 2]!.close} at ${n - 1} of ${n - 1}` },
    ]);
    // The next minute opens inside the box: no brick forms, and the last one has closed.
    h.clock.now = next.time + 90;
    h.series.update({ time: next.time + 60, open: next.close, high: next.close, low: next.close, close: next.close });
    study.values();
    expect(h.chart.primaryBars()).toHaveLength(n);
    expect(summary(h.events).slice(1)).toEqual([
      { alertId: 'above-1', time: bricks[n - 1]!.time, index: n - 1, message: `${bricks[n - 1]!.close} at ${n} of ${n}` },
    ]);
  });

  it('stays silent when a reload hands the same bars with two more bricks', () => {
    const bars = history();
    const h = mount({ transform: true });
    h.series.setData(bars);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars)));
    h.series.setData([...bars, twoBrickBar(bars)]);
    study.values();
    expect(h.chart.primaryBars()).toHaveLength(renko(bars).length + 2);
    expect(h.events).toEqual([]);
  });

  it('stays silent when an earlier element changed and two were appended', () => {
    const bars = history();
    const shown = renko(bars);
    const all = renko([...bars, twoBrickBar(bars)]);
    const h = mount();
    h.series.setData(shown);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars)));
    const edited = all.map((bar, i) => i === 3 ? { ...bar, close: bar.close + BOX, high: bar.high + BOX } : bar);
    h.series.setData(edited);
    study.values();
    expect(h.events).toEqual([]);
    // A correction to an earlier element followed by two appends in one pass is history too.
    const h2 = mount();
    h2.series.setData(shown);
    const study2 = h2.chart.addIndicator(crossStudy(levelsAbove(bars)));
    h2.series.update({ ...shown[shown.length - 3]!, close: shown[shown.length - 3]!.close });
    h2.series.update(all[all.length - 2]!);
    h2.series.update(all[all.length - 1]!);
    study2.values();
    expect(h2.events).toEqual([]);
  });

  it('stays silent across a symbol change that lands on a longer history', () => {
    const bars = history();
    const h = mount({ transform: true });
    h.series.setData(bars);
    const study = h.chart.addIndicator(crossStudy(levelsAbove(bars)));
    h.chart.setDataContext({ symbol: 'OTHER', interval: '1m' });
    h.series.setData([...bars, twoBrickBar(bars)]);
    study.values();
    expect(h.events).toEqual([]);
  });
});
