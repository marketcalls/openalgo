import { describe, expect, it, vi } from 'vitest';
import { Chart, SeriesMarkers, generateBars, registerIndicator, type Bar, type IndicatorValues } from '../src/index';
import { registerTransformChartTypes, runTransform, HeikinAshiTransform, RenkoTransform } from '../src/transform/index';
import '../src/indicators/index';
import { fakeDocument } from './helpers/fake-dom';

registerTransformChartTypes();

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

/** A seeded random walk that trades like a stock. */
const walk = (count: number): Bar[] => generateBars(1_700_000_000, count, 60);
const BOX = 0.5;

/** A five-bar simple moving average of the close, the plan's reference study. */
function sma(bars: readonly Bar[], length = 5): (number | null)[] {
  return bars.map((_, i) => i + 1 < length ? null : bars.slice(i + 1 - length, i + 1).reduce((sum, bar) => sum + bar.close, 0) / length);
}

registerIndicator({
  id: 'bar-source-sma', name: 'Bar source SMA', placement: 'onchart', inputs: [],
  plots: [{ key: 'value', type: 'line', title: 'SMA' }],
  calc: (bars): IndicatorValues => ({ value: sma(bars) }),
});

/** The source bar each Renko brick was completed on. */
function completedOn(bars: readonly Bar[]): number[] {
  const t = new RenkoTransform({ boxSize: BOX });
  return bars.flatMap((bar, i) => t.push(bar).map(() => i));
}

describe('study bar source', () => {
  it('computes on the bars the chart draws by default', () => {
    const chart = makeChart();
    const bars = walk(300);
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    const study = chart.addIndicator('bar-source-sma');
    const bricks = runTransform(new RenkoTransform({ boxSize: BOX }), bars);
    expect(study.barSource()).toBe('chart');
    expect(study.values().value).toEqual(sma(bricks));
    expect(chart.getState().indicators?.[0]).not.toHaveProperty('barSource');
  });

  it('computes on the underlying bars and reads each value at the bar its brick completed on', () => {
    const chart = makeChart();
    const bars = walk(300);
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    const study = chart.addIndicator('bar-source-sma', {}, { barSource: 'underlying' });
    const bricks = chart.primaryBars();
    const raw = sma(bars);
    expect(study.values().value).toEqual(completedOn(bars).map(i => raw[i]));
    // Written on the bricks' own times: the raw bars never reach the shared axis.
    expect(chart.dataLayer.length).toBe(bricks.length);
    expect(study.series('value')!.getData().map(point => point.time)).toEqual(bricks.map(brick => brick.time));
  });

  it('switches either way live, and follows the forming bar on every tick', () => {
    const chart = makeChart();
    const bars = walk(260);
    const series = chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } });
    series.setData(bars.slice(0, 200));
    const study = chart.addIndicator('bar-source-sma');
    const changes = vi.fn(); chart.on('objects:change', changes);
    expect(study.setBarSource('underlying')).toBe(true);
    expect(study.setBarSource('underlying')).toBe(false);
    expect(changes).toHaveBeenCalledTimes(1);
    for (const bar of bars.slice(200)) {
      series.update({ ...bar, close: bar.open });
      series.update(bar);
      const source = series.getData(), raw = sma(source);
      expect(chart.indicators()[0].values().value).toEqual(completedOn(source).map(i => raw[i]));
    }
    expect(study.setBarSource('chart')).toBe(true);
    expect(study.values().value).toEqual(sma(chart.primaryBars()));
  });

  it('needs no sampling on Heikin Ashi, whose candles keep their bars times', () => {
    const chart = makeChart();
    const bars = walk(120);
    chart.addSeries('candlestick', { transform: { type: 'heikin-ashi' } }).setData(bars);
    const onChart = chart.addIndicator('bar-source-sma');
    const underlying = chart.addIndicator('bar-source-sma', {}, { barSource: 'underlying' });
    expect(onChart.values().value).toEqual(sma(runTransform(new HeikinAshiTransform(), bars)));
    expect(underlying.values().value).toEqual(sma(bars));
    expect(chart.dataLayer.length).toBe(bars.length);
  });

  it('is the same study on a chart with no transform', () => {
    const chart = makeChart();
    const bars = walk(80);
    chart.addSeries('candlestick').setData(bars);
    const study = chart.addIndicator('sma', { length: 9 }, { barSource: 'underlying' });
    const plain = chart.addIndicator('sma', { length: 9 });
    expect(study.values()).toEqual(plain.values());
  });

  it('places a mark a study dates on the underlying bars on the brick that bar completed into', () => {
    // A study that builds its marks while it computes, dated at the bars it computes on.
    let marks: { time: number; position: 'aboveBar'; shape: 'circle'; size: 'small'; color: string }[] = [];
    registerIndicator({
      id: 'bar-source-marks', name: 'Bar source marks', placement: 'onchart', inputs: [], markerAnchor: 'price',
      plots: [{ key: 'value', type: 'line', title: 'Close' }],
      calc: (calcBars): IndicatorValues => {
        marks = calcBars.flatMap((bar, i) => i % 25 === 24 ? [{ time: bar.time, position: 'aboveBar' as const, shape: 'circle' as const, size: 'small' as const, color: '#26a69a' }] : []);
        return { value: calcBars.map(bar => bar.close) };
      },
      markers: () => marks,
    });
    const chart = makeChart();
    const bars = walk(300);
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    const written = vi.spyOn(SeriesMarkers.prototype, 'setMarkers');
    chart.addIndicator('bar-source-marks', {}, { barSource: 'underlying' });
    const placed = written.mock.calls[written.mock.calls.length - 1][0].map(mark => mark.time);
    written.mockRestore();
    const bricks = chart.primaryBars(), index = completedOn(bars);
    const expected = bars.flatMap((_, i) => {
      if (i % 25 !== 24) return [];
      const k = index.findIndex(source => source >= i);
      return k < 0 ? [] : [bricks[k].time];
    });
    expect(expected.length).toBeGreaterThan(5);
    expect(placed).toEqual(expected);
    for (const time of placed) expect(chart.dataLayer.timeToIndex(time)).not.toBeUndefined();
  });

  it('saves the choice only when it is not the default, and restores it', () => {
    const chart = makeChart();
    const bars = walk(200);
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    chart.addIndicator('bar-source-sma', {}, { barSource: 'underlying' });
    chart.addIndicator('bar-source-sma');
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    expect(saved.indicators[0].barSource).toBe('underlying');
    expect(saved.indicators[1]).not.toHaveProperty('barSource');
    const other = makeChart();
    other.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    expect(other.restoreState(saved).applied).toBe(true);
    expect(other.indicators().map(study => study.barSource())).toEqual(['underlying', 'chart']);
    expect(other.indicators()[0].values()).toEqual(chart.indicators()[0].values());
    expect(other.getState().indicators).toEqual(saved.indicators);
    const bad = { ...saved, indicators: [{ ...saved.indicators[0], barSource: 'raw' }] };
    const report = other.restoreState(bad);
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/bar source/);
    expect(other.indicators().map(study => study.barSource())).toEqual(['underlying', 'chart']);
  });

  it('honours the study policy and refuses a value it does not know', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(walk(40));
    const study = chart.addIndicator('bar-source-sma', {}, { policy: { configurable: false } });
    expect(study.setBarSource('underlying')).toBe(false);
    expect(study.barSource()).toBe('chart');
    expect(study.setBarSource('underlying', { force: true })).toBe(true);
    expect(() => study.setBarSource('raw' as never)).toThrow(/bar source/);
    expect(() => chart.addIndicator('bar-source-sma', {}, { barSource: 'raw' as never })).toThrow(/bar source/);
  });
});

describe('a study lifecycle on a transformed chart', () => {
  it('hands attach the bars the study computes on', () => {
    let read: (() => readonly Bar[]) | null = null;
    registerIndicator({
      id: 'bar-source-attach', name: 'Bar source attach', placement: 'pane', inputs: [],
      plots: [{ key: 'value', type: 'line', title: 'Close' }],
      calc: (bars): IndicatorValues => ({ value: bars.map(bar => bar.close) }),
      attach: (ctx) => { read = ctx.bars; return () => {}; },
    });
    const chart = makeChart();
    const bars = walk(200);
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: BOX } } }).setData(bars);
    const study = chart.addIndicator('bar-source-attach');
    expect(read!()).toEqual(chart.primaryBars());
    study.setBarSource('underlying');
    expect(read!()).toEqual(bars);
  });
});
