import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { generateBars, getSeriesTransform, type Bar } from '../src/index';
import { chartTypeChoices, chartTypeLabel, createWidget, STATE_KEY, type Widget, type WidgetOptions } from '../src/widget/index';
import { registerTransformChartTypes, runTransform, HeikinAshiTransform } from '../src/transform/index';
import { mountIndicatorSettings } from '../src/widget/dialogs/index';
import '../src/indicators/index';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
registerTransformChartTypes();
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

/** A seeded random walk that trades like a stock, one bar a minute. */
const walk = generateBars(1_700_000_000, 240, 60);

function fixture(options: WidgetOptions = {}): Widget {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, pixelRatio: () => 1,
    rail: false, panels: false, mobile: 'never', animZoom: false, animAutoscale: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} }, ...options,
  });
  widgets.push(widget);
  widget.chart.applySize(800, 600);
  return widget;
}

/** A widget that loads its own bars from a feed, and a way to push it a live bar. */
function fed(options: WidgetOptions = {}): { widget: Widget; push: (bar: Bar) => void } {
  let push: (bar: Bar) => void = () => {};
  const widget = fixture({
    symbol: 'AAA', exchange: 'X', interval: '1m', now: () => walk[walk.length - 1].time + 30,
    feed: { getBars: async () => walk.slice(), subscribeBars: (_request, onBar) => { push = onBar; return () => {}; } },
    ...options,
  });
  return { widget, push: bar => push(bar) };
}

const transformed = (type: string, source: readonly Bar[]): Bar[] => {
  const run = getSeriesTransform(type).create({});
  run.setData(source);
  return run.elements().slice();
};

describe('widget chart types the chart transforms', () => {
  it('lists every transform once in the chart type menu, after the renderers', () => {
    const choices = chartTypeChoices();
    expect(choices.slice(-6)).toEqual(['heikin-ashi', 'renko', 'range-bars', 'line-break', 'point-figure', 'kagi']);
    expect(choices.filter(id => id === 'point-figure')).toHaveLength(1);
    expect(['heikin-ashi', 'renko', 'range-bars', 'line-break'].map(chartTypeLabel)).toEqual(['Heikin Ashi', 'Renko', 'Range bars', 'Line break']);
  });

  it('applies the transform to the bars it loads, ticks it live, and saves it', async () => {
    const { widget, push } = fed();
    await flush();
    const layouts = vi.fn(); widget.on('layout', layouts);
    widget.setChartType('renko');
    expect(widget.chartType()).toBe('renko');
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'renko' });
    expect(widget.chart.primaryBars()).toEqual(transformed('renko', walk));
    expect(widget.series.getData()).toEqual(walk);
    expect(layouts.mock.calls.filter(([event]) => event.reason === 'chartType')).toEqual([[{ reason: 'chartType', chartType: 'renko' }]]);
    // A live tick on a new bar: the bricks follow it.
    const last = walk[walk.length - 1];
    const tick = { time: last.time + 60, open: last.close, high: last.close + 9, low: last.close, close: last.close + 9 };
    push(tick);
    await flush();
    expect(widget.series.getData()).toEqual([...walk, tick]);
    // The box was sized from the history the widget loaded; a tick never resizes it.
    const run = getSeriesTransform('renko').create({});
    run.setData(walk);
    run.update(tick);
    expect(widget.chart.primaryBars()).toEqual(run.elements());
    const saved = widget.getState();
    expect(saved.chartType).toBe('renko');
    expect(saved.chart.series?.[0].transform).toEqual({ type: 'renko' });
    widget.setChartType('candlestick');
    expect(widget.chart.seriesTransform(widget.series)).toBeNull();
    expect(widget.chart.primaryBars()).toEqual([...walk, tick]);
  });

  it('transforms point and figure when it loads its own bars, and restores a 2.5.10 layout that chose it', async () => {
    const { widget } = fed();
    await flush();
    // What 2.5.10 saved for a point and figure chart: the renderer, and no transform.
    const legacy = JSON.parse(JSON.stringify({ ...widget.getState(), chartType: 'point-figure' }));
    legacy.chart.series[0].type = 'point-figure';
    expect(legacy.chart.series[0]).not.toHaveProperty('transform');
    expect(widget.restoreState(legacy).applied).toBe(true);
    expect(widget.chartType()).toBe('point-figure');
    expect(widget.chart.seriesType(widget.series)).toBe('point-figure');
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'point-figure' });
    expect(widget.chart.primaryBars()).toEqual(transformed('point-figure', walk));
    // Round trip: what it saves now restores to the same chart.
    const saved = JSON.parse(JSON.stringify(widget.getState()));
    expect(saved.chartType).toBe('point-figure');
    widget.setChartType('line');
    expect(widget.restoreState(saved).applied).toBe(true);
    expect(widget.getState().chartType).toBe('point-figure');
    expect(widget.getState().chart.series).toEqual(saved.chart.series);
  });

  it('brings the transform options a layout saved back with it', async () => {
    const { widget } = fed({ chartType: 'renko' });
    await flush();
    widget.chart.setSeriesTransform(widget.series, { type: 'renko', options: { boxSize: 2 } });
    const saved = JSON.parse(JSON.stringify(widget.getState()));
    widget.setChartType('kagi');
    expect(widget.restoreState(saved).applied).toBe(true);
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'renko', options: { boxSize: 2 } });
    // Picking the type on screen again keeps the options it was set up with.
    widget.setChartType('renko');
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'renko', options: { boxSize: 2 } });
    // Options this build refuses fall back to the defaults rather than failing the layout.
    saved.chart.series[0].transform.options = { boxSize: -3 };
    widget.setChartType('line');
    expect(widget.restoreState(saved).applied).toBe(true);
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'renko' });
  });

  it('transforms a new type over bars its host feeds, and keeps point and figure a renderer there', () => {
    const w = fixture();
    w.series.setData(walk);
    w.setChartType('heikin-ashi');
    expect(w.chart.seriesTransform(w.series)).toEqual({ type: 'heikin-ashi' });
    expect(w.chart.primaryBars()).toEqual(runTransform(new HeikinAshiTransform(), walk));
    w.setChartType('point-figure');
    expect(w.chart.seriesTransform(w.series)).toBeNull();
    expect(w.chart.seriesType(w.series)).toBe('point-figure');
    expect(w.chart.primaryBars()).toEqual(walk);
  });

  it('undoes and redoes a transform chart type as one step', async () => {
    const { widget } = fed();
    await flush();
    widget.history.clear();
    widget.setChartType('line-break');
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(widget.history.peekUndo()?.changes).toEqual(['chart-type']);
    widget.history.undo();
    expect(widget.chartType()).toBe('candlestick');
    expect(widget.chart.seriesTransform(widget.series)).toBeNull();
    widget.history.redo();
    expect(widget.chartType()).toBe('line-break');
    expect(widget.chart.seriesTransform(widget.series)).toEqual({ type: 'line-break' });
  });

  it('offers the bar source in a study settings dialog while the chart transforms, and puts it back on cancel', async () => {
    const { widget } = fed({ chartType: 'renko' });
    await flush();
    const study = widget.chart.addIndicator('sma');
    const root = widget.root as unknown as FakeElement;
    mountIndicatorSettings(widget.context, undefined, { instanceId: study.id });
    const select = root.querySelector(`#oac-ind-${study.id}--bars`) as FakeElement;
    expect(select.tagName).toBe('SELECT');
    expect(select.value).toBe('chart');
    select.value = 'underlying';
    fire(select, 'change');
    expect(study.barSource()).toBe('underlying');
    (root.querySelectorAll('.oac-dialog__actions button')[0] as FakeElement).click();
    expect(study.barSource()).toBe('chart');
    // On a chart drawn as given the two are the same bars, so there is no choice to offer.
    widget.setChartType('candlestick');
    mountIndicatorSettings(widget.context, undefined, { instanceId: study.id });
    expect(root.querySelector(`#oac-ind-${study.id}--bars`)).toBeNull();
  });

  it('keeps the brick size when a page of older history arrives', async () => {
    const recent = walk.slice(120), older = walk.slice(0, 120);
    const widget = fixture({
      symbol: 'AAA', exchange: 'X', interval: '1m', chartType: 'renko', now: () => walk[walk.length - 1].time + 30,
      feed: { getBars: async () => recent.slice(), getBarsPage: async () => ({ bars: older.slice(), hasMore: false }) },
    });
    await flush();
    const box = (): number => Math.abs(widget.chart.primaryBars()[0].close - widget.chart.primaryBars()[0].open);
    const loaded = box();
    await widget.dataController!.loadMore();
    await flush();
    expect(widget.series.getData()).toEqual(walk);
    // The size resolved at the load stands: a page of history does not resize every brick.
    expect(box()).toBe(loaded);
    const run = getSeriesTransform('renko').create({});
    run.setData(recent);
    run.prepend(older);
    expect(widget.chart.primaryBars()).toEqual(run.elements());
  });

  it('starts from a saved Renko layout with a study a timeframe refuses there, the study in its error status', async () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value); }, removeItem: (key: string) => { store.delete(key); },
    };
    const first = fed({ persist: true, storage }).widget;
    await flush();
    first.chart.addIndicator('ema', { length: 5, timeframe: '15m' });
    first.setChartType('renko');
    expect(first.chart.indicators()[0].dataStatus()?.state).toBe('error');
    first.context.storage.set(STATE_KEY, first.getState());
    const { widget } = fed({ persist: true, storage });
    await flush();
    expect(widget.chartType()).toBe('renko');
    const ema = widget.chart.indicators()[0];
    expect(ema.settings().timeframe).toBe('15m');
    expect(ema.dataStatus()?.state).toBe('error');
  });
});
