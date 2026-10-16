import { describe, expect, it, vi } from 'vitest';
import { Chart, applyChartSettings, chartSettingsSchema, generateBars, readChartSettings, type Bar } from '../src/index';
import {
  registerTransformChartTypes, runTransform, HeikinAshiTransform, RenkoTransform, PointFigureTransform, KagiTransform,
} from '../src/transform/index';
import { fakeDocument } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

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
const walk = (count: number, start = 1_700_000_000): Bar[] => generateBars(start, count, 60);
const renko = (bars: readonly Bar[], boxSize = 0.5): Bar[] => runTransform(new RenkoTransform({ boxSize }), bars);

describe('in-chart transforms', () => {
  it('draws the transform of the bars a host feeds, and hands those bars back unchanged', () => {
    const chart = makeChart();
    const series = chart.addSeries('line');
    const bars = walk(200);
    series.setData(bars);
    const changes = vi.fn(); chart.on('objects:change', changes);
    expect(chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: 0.5 } })).toBe(true);
    expect(chart.primaryBars()).toEqual(renko(bars));
    expect(chart.seriesType(series)).toBe('candlestick');
    expect(chart.seriesTransform(series)).toEqual({ type: 'renko', options: { boxSize: 0.5 } });
    expect(series.getData()).toEqual(bars);
    expect(series.getData()[7]).toBe(bars[7]);
    expect(changes).toHaveBeenCalledTimes(1);
    // The same choice again changes nothing and says nothing.
    expect(chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: 0.5 } })).toBe(false);
    expect(changes).toHaveBeenCalledTimes(1);
    // Clearing it draws the host's own bars again, the very objects it gave.
    expect(chart.setSeriesTransform(series, null)).toBe(true);
    expect(chart.seriesTransform(series)).toBeNull();
    expect(chart.primaryBars()).toEqual(bars);
    expect(chart.primaryBars()[7]).toBe(bars[7]);
    expect(chart.setSeriesTransform(series, null)).toBe(false);
  });

  it('takes a transform when the series is added, before any data', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick', { transform: { type: 'heikin-ashi' } });
    expect(chart.primaryBars()).toEqual([]);
    const bars = walk(50);
    series.setData(bars);
    expect(chart.primaryBars()).toEqual(runTransform(new HeikinAshiTransform(), bars));
    expect(chart.getState().series?.[0]).toMatchObject({ type: 'candlestick', transform: { type: 'heikin-ashi' } });
  });

  it('ticks live: the forming bar moves its brick, a closed bar keeps it, a new one completes', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 0.5 } } });
    const bars = walk(120);
    series.setData(bars.slice(0, 100));
    const updates: unknown[] = [];
    chart.on('data:update', event => updates.push(event));
    const closed = bars.slice(0, 100);
    let source = closed;
    for (let i = 100; i < 120; i++) {
      const bar = bars[i];
      let high = bar.open, low = bar.open;
      for (const close of [bar.open, bar.high, bar.low, bar.close]) {
        high = Math.max(high, close); low = Math.min(low, close);
        const tick = { ...bar, close, high, low };
        series.update(tick);
        source = [...closed, tick];
        expect(chart.primaryBars()).toEqual(renko(source));
        const last = chart.primaryBars()[chart.primaryBars().length - 1];
        expect(updates[updates.length - 1]).toEqual({ kind: 'update', time: last.time });
      }
      closed.push(source[source.length - 1]);
    }
    expect(series.getData()).toEqual(source);
    // Bricks completed over those twenty minutes of a random walk with half-point boxes.
    expect(chart.primaryBars().length).toBeGreaterThan(renko(bars.slice(0, 100)).length);
  });

  it('follows the newest element at the right edge and holds a view scrolled into history', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 0.25 } } });
    const bars = walk(400);
    series.setData(bars.slice(0, 300));
    chart.timeScale.setRightOffset(2);
    for (const bar of bars.slice(300)) series.update(bar);
    // At the right edge the view follows each new brick.
    expect(chart.getVisibleLogicalRange().to).toBeCloseTo(chart.primaryBars().length - 1 + 2, 6);
    // Scrolled back, the bricks in view stay put while new ones form and unform at the edge.
    const scrolled = makeChart();
    const held = scrolled.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 0.25 } } });
    held.setData(bars.slice(0, 300));
    scrolled.timeScale.setRightOffset(-40);
    const oldest = scrolled.dataLayer.indexToTime(Math.round(scrolled.getVisibleLogicalRange().from));
    for (const bar of bars.slice(300)) {
      for (const close of [bar.high, bar.low, bar.close]) held.update({ ...bar, close });
    }
    expect(scrolled.dataLayer.indexToTime(Math.round(scrolled.getVisibleLogicalRange().from))).toBe(oldest);
  });

  it('pages older history in at the left edge with the size resolved at the load', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick', { transform: { type: 'renko' } });
    const bars = walk(400);
    series.setData(bars.slice(200));
    const box = Math.abs(chart.primaryBars()[0].close - chart.primaryBars()[0].open);
    const events: string[] = [];
    chart.on('data:update', event => events.push((event as { kind: string }).kind));
    const newest = chart.primaryBars()[chart.primaryBars().length - 1].time;
    const right = chart.getVisibleLogicalRange().to;
    const rightTime = chart.dataLayer.indexToTime(Math.floor(right));
    series.prependData(bars.slice(0, 200));
    expect(series.getData()).toEqual(bars);
    expect(chart.primaryBars()).toEqual(runTransform(new RenkoTransform({ boxSize: Number(box.toPrecision(2)) }), bars));
    expect(chart.primaryBars()[chart.primaryBars().length - 1].time).toBe(newest);
    // The newest brick stays where it was on screen.
    expect(chart.dataLayer.indexToTime(Math.floor(chart.getVisibleLogicalRange().to))).toBe(rightTime);
    expect(events).toEqual(['prepend']);
  });

  it('never transforms a host that prepares its own elements and picks the renderer', () => {
    // The 2.5.x contract: the host runs the transform and the renderer only draws.
    const chart = makeChart();
    const columns = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), walk(300));
    const series = chart.addSeries('point-figure');
    series.setData(columns);
    expect(chart.seriesTransform(series)).toBeNull();
    expect(chart.primaryBars()).toEqual(columns);
    expect(chart.primaryBars()[3]).toBe(columns[3]);
    const vertices = runTransform(new KagiTransform({ reversal: 2 }), walk(300));
    expect(chart.setSeriesType(series, 'kagi')).toBe(true);
    series.setData(vertices);
    series.update({ ...vertices[vertices.length - 1], close: vertices[vertices.length - 1].close + 1 });
    expect(chart.seriesTransform(series)).toBeNull();
    expect(chart.primaryBars().slice(0, -1)).toEqual(vertices.slice(0, -1));
    expect(chart.primaryBars()[0]).toBe(vertices[0]);
    expect(chart.getState().series?.[0]).not.toHaveProperty('transform');
  });

  it('refuses a transform it cannot apply before changing anything', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick');
    const bars = walk(60);
    series.setData(bars);
    const state = chart.getState();
    expect(() => chart.setSeriesTransform(series, { type: 'three-line-break' })).toThrow(/unknown series transform/);
    expect(() => chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: -2 } })).toThrow(/boxSize/);
    expect(() => chart.setSeriesTransform(series, { type: 'renko', options: { box: 2 } })).toThrow(/"box"/);
    expect(() => chart.addSeries('candlestick', { transform: { type: 'kagi', options: { reversal: 'far' } } })).toThrow(/reversal/);
    expect(chart.getState()).toEqual(state);
    expect(chart.primaryBars()).toEqual(bars);
    const removed = chart.addSeries('line', { paneIndex: 1 });
    removed.remove();
    expect(chart.setSeriesTransform(removed, { type: 'renko' })).toBe(false);
    expect(chart.seriesTransform(removed)).toBeNull();
  });

  it('keeps a renderer the host picked after the transform, through an option change', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick');
    series.setData(walk(200));
    chart.setSeriesTransform(series, { type: 'heikin-ashi' });
    expect(chart.setSeriesType(series, 'bar')).toBe(true);
    chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: 1 } });
    expect(chart.seriesType(series)).toBe('candlestick');
    chart.setSeriesType(series, 'hollow-candle');
    chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: 2 } });
    expect(chart.seriesType(series)).toBe('hollow-candle');
    chart.setSeriesTransform(series, { type: 'kagi' });
    expect(chart.seriesType(series)).toBe('kagi');
  });

  it('saves the choice beside the series and restores a 2.5.10 state unchanged', () => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick');
    series.setData(walk(80));
    chart.setSeriesTransform(series, { type: 'point-figure', options: { mode: 'atr', reversal: 2 } });
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    expect(saved.series[0]).toEqual({ type: 'point-figure', style: {}, paneIndex: 0, priceScaleId: 'right',
      transform: { type: 'point-figure', options: { mode: 'atr', reversal: 2 } } });
    // A state written by 2.5.10 has no transform at all, and reads as it did.
    const legacy = { ...saved, series: [{ type: 'point-figure', style: {}, paneIndex: 0, priceScaleId: 'right' }] };
    const report = chart.restoreState(legacy);
    expect(report.applied).toBe(true);
    expect(report.series).toEqual(legacy.series);
    expect(chart.restoreState(saved).series[0].transform).toEqual({ type: 'point-figure', options: { mode: 'atr', reversal: 2 } });
  });
});

describe('transform settings', () => {
  const settingsChart = (): { chart: Chart; series: ReturnType<Chart['addSeries']> } => {
    const chart = makeChart();
    const series = chart.addSeries('candlestick');
    series.setData(walk(200));
    return { chart, series };
  };
  const priceInputs = (chart: Chart) => chartSettingsSchema(chart).find(tab => tab.id === 'price')!.inputs;

  it('offers the transform options on the Price tab and writes them to the spec', () => {
    const { chart, series } = settingsChart();
    expect(priceInputs(chart).some(input => input.key.startsWith('transform.'))).toBe(false);
    chart.setSeriesTransform(series, { type: 'renko' });
    const box = priceInputs(chart).find(input => input.key === 'transform.boxSize')!;
    expect(box).toMatchObject({ type: 'number', group: 'Renko', default: 0, min: 0 });
    expect(priceInputs(chart)[0].key).toBe('transform.mode');
    expect(readChartSettings(chart)['transform.boxSize']).toBe(0);
    applyChartSettings(chart, { 'transform.boxSize': 2 });
    expect(chart.seriesTransform(series)).toEqual({ type: 'renko', options: { boxSize: 2 } });
    expect(readChartSettings(chart)['transform.boxSize']).toBe(2);
    expect(Math.abs(chart.primaryBars()[0].close - chart.primaryBars()[0].open)).toBe(2);
    // An option the transform refuses changes nothing; the default drops it.
    applyChartSettings(chart, { 'transform.boxSize': -1 });
    expect(chart.seriesTransform(series)).toEqual({ type: 'renko', options: { boxSize: 2 } });
    applyChartSettings(chart, { 'transform.boxSize': 0 });
    expect(chart.seriesTransform(series)).toEqual({ type: 'renko' });
  });

  it('keeps each point and figure option to the box mode it belongs to', () => {
    const { chart, series } = settingsChart();
    chart.setSeriesTransform(series, { type: 'point-figure' });
    const inputs = priceInputs(chart);
    expect(inputs.filter(input => input.key.startsWith('transform.')).map(input => input.key)).toEqual([
      'transform.mode', 'transform.boxSize', 'transform.percent', 'transform.atrPeriod', 'transform.atrMultiplier',
      'transform.reversal', 'transform.method']);
    expect(inputs.find(input => input.key === 'transform.percent')!.visibleWhen).toEqual({ key: 'transform.mode', is: ['percent', 'atrPercent'] });
    applyChartSettings(chart, { 'transform.mode': 'percent', 'transform.percent': 0.5, 'transform.reversal': 2 });
    expect(chart.seriesTransform(series)).toEqual({ type: 'point-figure', options: { mode: 'percent', percent: 0.5, reversal: 2 } });
    expect(chart.primaryBars()).toEqual(runTransform(new PointFigureTransform({ mode: 'percent', percent: 0.5, reversal: 2 }), series.getData()));
    // The X and O colours are the rows that renderer reads; a line colour it ignores is not offered.
    expect(inputs.find(input => input.key === 'symbol.body')).toMatchObject({ type: 'colorPair', up: { key: 'symbol.upColor' } });
    expect(inputs.some(input => input.key === 'symbol.color' || input.key === 'symbol.lineWidth')).toBe(false);
  });

  it('offers the Kagi thick and thin colours the renderer draws with', () => {
    const { chart, series } = settingsChart();
    chart.setSeriesTransform(series, { type: 'kagi' });
    expect(priceInputs(chart).find(input => input.key === 'symbol.kagi')).toMatchObject({
      type: 'colorPair', up: { key: 'symbol.thickColor', default: '#26a69a' }, down: { key: 'symbol.thinColor', default: '#ef5350' } });
    applyChartSettings(chart, { 'symbol.thinColor': '#123456' });
    expect(chart.primarySeriesInfo()?.style.thinColor).toBe('#123456');
    expect(priceInputs(chart).some(input => input.key === 'symbol.color')).toBe(false);
  });
});

describe('the countdown on a transformed chart', () => {
  it('counts the forming source bar down, not the elements drawn from it', () => {
    const doc = fakeDocument();
    const bars = walk(120, 1_700_000_000).map(bar => ({ ...bar, time: bar.time * 5 - 1_700_000_000 * 4 })); // five-minute bars
    const last = bars[bars.length - 1].time;
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      axisChrome: { barCountdown: true, clock: () => last + 100 },
    });
    chart.applySize(800, 600);
    // Bricks three points tall form a few bars apart, so their spacing is not the bars' own.
    chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 3 } } }).setData(bars);
    expect(chart.primaryBars()[chart.primaryBars().length - 1].time).toBeLessThan(last);
    chart.invalidate(mask => mask.invalidateGlobal(3));
    const drawn = (chart.panes()[0].base.ctx as unknown as RecordingContext).ops.filter(op => op.type === 'fillText').map(op => op.text);
    // 100 seconds into the five-minute bar still forming: 200 left.
    expect(drawn).toContain('00:03:20');
  });
});
