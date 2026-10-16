/**
 * Trader alerts on a data update that appends several elements at once: one
 * source bar completing two or three Renko bricks, a Kagi reversal, or a host
 * that writes two bars before it says so. Each new element is judged in order,
 * exactly as separate appends would judge it, and each crossing is dated at its
 * own element. A replacement of history still seeds silently, and the newest
 * element is never judged as closed while it is forming.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertController, Chart, registerBarCondition, registerIndicator, unregisterBarCondition } from '../src/index';
import type { AlertChartHost, AlertInput, AlertTriggeredPayload, Bar, SeriesApi } from '../src/index';
import { DrawingController } from '../src/draw/index';
import { registerTransformChartTypes } from '../src/transform/index';
import { fakeDocument } from './helpers/fake-dom';

registerTransformChartTypes();

const cleanup: (() => void)[] = [];
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1_000_000); });
afterEach(() => {
  for (const destroy of cleanup.splice(0).reverse()) destroy();
  vi.useRealTimers();
});

/** Five-minute bars from 1 October 2026, 09:15 IST. */
const START = Date.UTC(2026, 9, 1, 3, 45) / 1000;
const at = (i: number): number => START + i * 300;

/** A source bar that opens at the previous close, with a small wick either side. */
function source(i: number, open: number, close: number): Bar {
  return { time: at(i), open, close, high: Math.max(open, close) + 0.05, low: Math.min(open, close) - 0.05, volume: 41_000 + i * 700 };
}

/**
 * A short session that wanders up from 99.6 to 102.3. With a box of 1 its
 * bricks are 100, 101 and 102, so the next bar closing at 104.4 completes
 * bricks 103 and 104 in one update, and one closing at 105.4 completes three.
 */
const CLOSES = [99.6, 100.4, 99.8, 100.9, 101.6, 101.2, 102.3];
const history = (): Bar[] => CLOSES.map((close, i) => source(i, CLOSES[i - 1] ?? close, close));
const next = (bars: readonly Bar[], close: number): Bar => {
  const last = bars[bars.length - 1]!;
  return source((last.time - START) / 300 + 1, last.close, close);
};

function chartWith(options: { transform?: { type: string; options?: Record<string, number> } } = {}) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  cleanup.push(() => chart.destroy());
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', exchange: 'NSE', interval: '5m' });
  const series: SeriesApi = chart.addSeries('candlestick');
  const bars = history();
  series.setData(bars);
  if (options.transform) chart.setSeriesTransform(series, options.transform);
  const draw = new DrawingController(chart);
  cleanup.push(() => draw.destroy());
  const alerts = new AlertController(chart, { drawings: draw });
  const fired: AlertTriggeredPayload[] = [];
  chart.on('alert:triggered', event => fired.push(event as AlertTriggeredPayload));
  /** Write the next source bar, closing at `close`. */
  const write = (close: number): void => { const bar = next(series.getData(), close); series.update(bar); };
  return { chart, series, draw, alerts, fired, write };
}

const renko = () => chartWith({ transform: { type: 'renko', options: { boxSize: 1 } } });
const price = (value: number, patch: Partial<AlertInput> = {}): AlertInput =>
  ({ source: { kind: 'price', price: value }, condition: 'crossingUp', ...patch });
const when = (fired: readonly AlertTriggeredPayload[], id: string) =>
  fired.filter(event => event.alertId === id).map(event => ({ index: event.index, time: event.time, price: event.price }));

describe('trader alerts on a step that completes several Renko bricks', () => {
  it('confirms the first of two bricks at once and dates each touch at its own brick', () => {
    const { chart, alerts, fired, write } = renko();
    expect(chart.primaryBars().map(bar => bar.close)).toEqual([100, 101, 102]);
    const close = alerts.add(price(102.5));
    const forming = alerts.add(price(103.5));
    const touchLow = alerts.add(price(102.5, { policy: 'onTouch' }));
    const touchHigh = alerts.add(price(103.5, { policy: 'onTouch' }));
    write(104.4);
    const bricks = chart.primaryBars();
    expect(bricks.map(bar => bar.close)).toEqual([100, 101, 102, 103, 104]);
    expect(when(fired, close.id)).toEqual([{ index: 3, time: bricks[3]!.time, price: 103 }]);
    expect(when(fired, touchLow.id)).toEqual([{ index: 3, time: bricks[3]!.time, price: 102.5 }]);
    expect(when(fired, touchHigh.id)).toEqual([{ index: 4, time: bricks[4]!.time, price: 103.5 }]);
    // Brick 104 is still forming: it is judged only once a newer brick closes it.
    expect(when(fired, forming.id)).toEqual([]);
    write(105.3);
    expect(when(fired, forming.id)).toEqual([{ index: 4, time: bricks[4]!.time, price: 104 }]);
    expect(when(fired, close.id)).toHaveLength(1);
  });

  it('judges each closed brick once across further steps, never the forming one twice', () => {
    const { alerts, fired, write, chart } = renko();
    const every = alerts.add(price(102.5, { condition: 'greaterThan', repeat: 'everyTime' }));
    write(105.4);
    const bricks = chart.primaryBars();
    expect(bricks.map(bar => bar.close)).toEqual([100, 101, 102, 103, 104, 105]);
    expect(when(fired, every.id).map(event => event.index)).toEqual([3, 4]);
    write(105.6);
    write(106.2);
    expect(when(fired, every.id).map(event => event.index)).toEqual([3, 4, 5]);
    expect(when(fired, every.id).map(event => event.time)).toEqual([3, 4, 5].map(i => chart.primaryBars()[i]!.time));
  });

  it('honours once and every-time repeats inside one step, and a cooldown as separate appends would', () => {
    const { chart, alerts, fired, write } = renko();
    const closeOnce = alerts.add(price(102.5, { condition: 'greaterThan' }));
    const closeEvery = alerts.add(price(102.5, { condition: 'greaterThan', repeat: 'everyTime' }));
    const touchOnce = alerts.add(price(102.5, { policy: 'onTouch' }));
    const touchEvery = alerts.add(price(102.5, { condition: 'greaterThan', policy: 'onTouch', repeat: 'everyTime' }));
    const cooled = alerts.add(price(102.5, { condition: 'greaterThan', policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 60 }));
    write(105.4);
    const times = chart.primaryBars().map(bar => bar.time);
    expect(when(fired, closeOnce.id).map(event => event.index)).toEqual([3]);
    expect(when(fired, closeEvery.id).map(event => event.index)).toEqual([3, 4]);
    expect(when(fired, touchOnce.id).map(event => event.index)).toEqual([3]);
    // A greater-than touch reports the brick's high, which is its close.
    expect(when(fired, touchEvery.id)).toEqual([3, 4, 5].map(i => ({ index: i, time: times[i], price: 100 + i })));
    // Three appends in one instant: the first delivers, the cooldown holds the
    // other two, and both are consumed rather than waiting for the cooldown.
    expect(when(fired, cooled.id).map(event => event.index)).toEqual([3]);
    const state = (id: string) => alerts.list().find(alert => alert.id === id)!;
    expect(state(closeOnce.id)).toMatchObject({ state: 'triggered', lastTriggeredTime: times[3], lastClosedTime: times[3] });
    expect(state(touchOnce.id)).toMatchObject({ state: 'triggered', lastTriggeredTime: times[3] });
    expect(state(closeEvery.id)).toMatchObject({ state: 'armed', lastTriggeredTime: times[4], lastClosedTime: times[4] });
    expect(state(cooled.id)).toMatchObject({ state: 'armed', lastTriggeredTime: times[3], lastTouchedTime: times[5] });
    vi.advanceTimersByTime(61_000);
    write(105.7);
    expect(when(fired, cooled.id)).toHaveLength(1);
  });

  it('does not judge again a tail the step left as it was', () => {
    const { alerts, fired, write } = renko();
    // Every up brick is bullish, brick 102 included, but a single append of
    // brick 103 would judge brick 103 alone.
    const bullish = alerts.add({ source: { kind: 'barCondition', id: 'bullish' }, policy: 'onTouch', repeat: 'everyTime' });
    write(104.4);
    expect(when(fired, bullish.id).map(event => event.index)).toEqual([3, 4]);
  });

  it('delivers in element order, as separate appends would interleave the alerts', () => {
    const { alerts, fired, write } = renko();
    const high = alerts.add(price(103.5, { policy: 'onTouch' }));
    const low = alerts.add(price(102.5, { policy: 'onTouch' }));
    write(104.4);
    expect(fired.map(event => [event.alertId, event.index])).toEqual([[low.id, 3], [high.id, 4]]);
  });

  it('judges study and drawing sources and named conditions at each brick, on the prefix through it', () => {
    const { chart, draw, alerts, fired, write } = renko();
    registerIndicator({
      id: 'element-step-brick-close', name: 'Brick close', placement: 'pane', inputs: [],
      plots: [{ key: 'close', type: 'line', title: 'Close' }],
      calc: bars => ({ close: bars.map(bar => bar.close) }),
    });
    const study = chart.addIndicator('element-step-brick-close');
    const seen: [number, number][] = [];
    registerBarCondition({ id: 'element-step-seen', title: 'Seen', when: ({ bars, index }) => { seen.push([index, bars.length]); return true; } });
    cleanup.push(() => unregisterBarCondition('element-step-seen'));
    const line = draw.add({ tool: 'horizontal-line', points: [{ time: chart.primaryBars()[0]!.time, price: 102.5 }], style: {}, paneIndex: 0 });
    const plot = { kind: 'indicator', instanceId: study.id, plotKey: 'close', value: 102.5 } as const;
    const plotClose = alerts.add({ source: plot, condition: 'crossingUp' });
    const plotTouch = alerts.add({ source: plot, condition: 'crossingUp', policy: 'onTouch' });
    const lineClose = alerts.add({ source: { kind: 'drawing', drawingId: line.id }, condition: 'crossingUp' });
    const lineTouch = alerts.add({ source: { kind: 'drawing', drawingId: line.id }, condition: 'crossingUp', policy: 'onTouch' });
    const named = alerts.add({ source: { kind: 'barCondition', id: 'element-step-seen' }, repeat: 'everyTime' });
    write(105.4);
    const brick3 = chart.primaryBars()[3]!.time;
    expect(when(fired, plotClose.id)).toEqual([{ index: 3, time: brick3, price: 103 }]);
    expect(when(fired, plotTouch.id)).toEqual([{ index: 3, time: brick3, price: 103 }]);
    expect(when(fired, lineClose.id)).toEqual([{ index: 3, time: brick3, price: 103 }]);
    expect(when(fired, lineTouch.id)).toEqual([{ index: 3, time: brick3, price: 102.5 }]);
    // Each brick the step closes, from the old tail 102 on, on the bricks
    // through itself only; the forming brick 105 waits.
    expect(seen).toEqual([[2, 3], [3, 4], [4, 5]]);
    expect(when(fired, named.id).map(event => event.index)).toEqual([2, 3, 4]);
  });

  it('keeps a step that a delivery listener interrupts, judging the rest on the next update', () => {
    const { chart, series, alerts, fired, write } = renko();
    const every = alerts.add(price(102.5, { condition: 'greaterThan', repeat: 'everyTime' }));
    let wrote = false;
    chart.on('alert:triggered', () => {
      if (wrote) return;
      wrote = true;
      series.update(next(series.getData(), 106.4));
    });
    write(105.4);
    expect(chart.primaryBars().map(bar => bar.close)).toEqual([100, 101, 102, 103, 104, 105, 106]);
    expect(when(fired, every.id).map(event => event.index)).toEqual([3, 4, 5]);
  });
});

describe('trader alerts on a Kagi reversal', () => {
  it('confirms the turning point once the reversal leaves it behind', () => {
    const { chart, alerts, fired, series } = chartWith({ transform: { type: 'kagi', options: { reversal: 2 } } });
    // Down from 104 to 100, back up to 105, then a fall that turns the line at 105.
    series.setData([104, 101, 100, 103, 105].map((close, i, all) => source(i, all[i - 1] ?? close, close)));
    expect(chart.primaryBars().map(bar => bar.close)).toEqual([104, 100, 105]);
    const close = alerts.add(price(104.5));
    const touch = alerts.add(price(103.5, { condition: 'crossingDown', policy: 'onTouch' }));
    series.update(next(series.getData(), 102));
    const vertices = chart.primaryBars();
    expect(vertices.map(bar => bar.close)).toEqual([104, 100, 105, 102]);
    expect(when(fired, close.id)).toEqual([{ index: 2, time: vertices[2]!.time, price: 105 }]);
    expect(when(fired, touch.id)).toEqual([{ index: 3, time: vertices[3]!.time, price: 103.5 }]);
  });
});

/**
 * A host that implements the alert surface itself and announces a write only
 * after it has made it, so one update can carry several bars.
 */
function hostFed() {
  const listeners = new Map<string, Set<(payload: unknown) => void>>();
  const bars: Bar[] = history();
  const host: AlertChartHost = {
    primaryBars: () => bars,
    getDataContext: () => ({ symbol: 'SAMPLE', exchange: 'NSE', interval: '5m' }),
    on: (event, callback) => {
      const set = listeners.get(event) ?? new Set();
      listeners.set(event, set.add(callback));
      return () => { set.delete(callback); };
    },
    emit: (event, payload) => { for (const callback of [...listeners.get(event) ?? []]) callback(payload); },
  };
  const alerts = new AlertController(host, { visuals: false });
  cleanup.push(() => alerts.destroy());
  const fired: AlertTriggeredPayload[] = [];
  host.on('alert:triggered', event => fired.push(event as AlertTriggeredPayload));
  /** Replace or append each bar by time, then announce one update. */
  const write = (...items: Bar[]): void => {
    for (const item of items) {
      const index = bars.findIndex(bar => bar.time >= item.time);
      if (index < 0) bars.push(item);
      else bars.splice(index, bars[index]!.time === item.time ? 1 : 0, item);
    }
    host.emit('data:update', { kind: 'update', time: bars[bars.length - 1]!.time });
  };
  return { host, bars, alerts, fired, write };
}

describe('trader alerts on a host that writes two bars in one update', () => {
  it('judges both bars in order, the first as closed and the second as forming', () => {
    const { bars, alerts, fired, write } = hostFed();
    const close = alerts.add(price(102.5));
    const forming = alerts.add(price(102.9));
    const touchLow = alerts.add(price(102.5, { policy: 'onTouch' }));
    const touchHigh = alerts.add(price(103, { policy: 'onTouch' }));
    const first = next(bars, 102.8);
    const second = source((first.time - START) / 300 + 1, 102.8, 103.1);
    write(first, second);
    expect(when(fired, close.id)).toEqual([{ index: 7, time: first.time, price: 102.8 }]);
    expect(when(fired, touchLow.id)).toEqual([{ index: 7, time: first.time, price: 102.5 }]);
    expect(when(fired, touchHigh.id)).toEqual([{ index: 8, time: second.time, price: 103 }]);
    expect(when(fired, forming.id)).toEqual([]);
    write(next(bars, 103.2));
    expect(when(fired, forming.id)).toEqual([{ index: 8, time: second.time, price: 103.1 }]);
  });

  it('judges a revised tail before the bars appended after it', () => {
    const { bars, alerts, fired, write } = hostFed();
    const touch = alerts.add(price(102.5, { policy: 'onTouch' }));
    const tail = bars[bars.length - 1]!;
    write({ ...tail, close: 102.7, high: 102.8 }, next(bars, 102.4));
    expect(when(fired, touch.id)).toEqual([{ index: 6, time: tail.time, price: 102.5 }]);
  });

  it('never judges a corrected bar, only the bars appended after the tail', () => {
    const { bars, alerts, fired, write } = hostFed();
    const corrected = alerts.add(price(101, { condition: 'crossingDown' }));
    const appended = alerts.add(price(102.5));
    // Bar 5 closed at 101.2; it is corrected to 100.8, below the level, while two new bars arrive.
    write({ ...bars[5]!, close: 100.8, low: 100.75 }, next(bars, 102.8), source(8, 102.8, 103));
    expect(when(fired, corrected.id)).toEqual([]);
    expect(when(fired, appended.id)).toEqual([{ index: 7, time: at(7), price: 102.8 }]);
  });
});

describe('a replacement of history stays silent', () => {
  const crossing = (alerts: AlertController) => [
    alerts.add(price(102.5)), alerts.add(price(103.5)), alerts.add(price(102.5, { policy: 'onTouch' })),
    alerts.add(price(103.5, { policy: 'onTouch', repeat: 'everyTime' })),
    alerts.add(price(101.5, { condition: 'crossingDown', policy: 'onTouch', repeat: 'everyTime' })),
  ];

  it('on a reload that brings two more bricks', () => {
    const { chart, series, alerts, fired } = renko();
    crossing(alerts);
    series.setData([...history(), source(7, 102.3, 104.4)]);
    expect(chart.primaryBars().map(bar => bar.close)).toEqual([100, 101, 102, 103, 104]);
    expect(fired).toEqual([]);
  });

  it('on older history paged in', () => {
    const { chart, series, alerts, fired } = renko();
    crossing(alerts);
    series.prependData([95.2, 97.4, 104.6, 99.1].map((close, i) => source(i - 4, close, close)));
    expect(chart.primaryBars().length).toBeGreaterThan(3);
    expect(fired).toEqual([]);
  });

  it('on a symbol or interval change', () => {
    const { chart, series, alerts, fired, write } = renko();
    const [, closeHigh] = crossing(alerts);
    series.setData([]);
    chart.setDataContext({ symbol: 'SAMPLE', exchange: 'NSE', interval: '1m' });
    series.setData([...history(), source(7, 102.3, 104.4)]);
    chart.setDataContext({ symbol: 'OTHER', exchange: 'NSE', interval: '5m' });
    series.setData([...history(), source(7, 102.3, 104.4)]);
    series.setData([]);
    chart.setDataContext({ symbol: 'SAMPLE', exchange: 'NSE', interval: '5m' });
    series.setData([...history(), source(7, 102.3, 104.4)]);
    expect(fired).toEqual([]);
    // Back on its own series it is live again: brick 105 closes brick 104, across 103.5.
    write(105.3);
    expect(fired.map(event => event.alertId)).toEqual([closeHigh!.id]);
  });

  it('on a correction of an older source bar that forms the bricks again', () => {
    const { chart, series, alerts, fired } = renko();
    crossing(alerts);
    series.update(source(5, 101.6, 103.4));
    expect(chart.primaryBars().map(bar => bar.close)).toEqual([100, 101, 102, 103]);
    expect(fired).toEqual([]);
  });

  it('on a plain chart, where a bar inserted behind the tail is never confirmed', () => {
    const { series, alerts, fired } = chartWith();
    const close = alerts.add(price(102.5));
    const bars = series.getData();
    const tail = bars[bars.length - 1]!;
    // A late bar between the last closed bar and the tail, closing above the level.
    series.update({ ...source(5, 101.6, 102.9), time: tail.time - 150 });
    series.update(source(7, 102.3, 102.4));
    expect(when(fired, close.id)).toEqual([]);
  });
});
