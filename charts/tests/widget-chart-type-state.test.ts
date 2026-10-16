import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { getChartType, registerChartType, registerIndicator, type PriceFormat, type SeriesType } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { registerTransformChartTypes, runTransform, PointFigureTransform, KagiTransform } from '../src/transform/index';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });
const bars = Array.from({ length: 30 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i % 5, high: 110 + i % 5, low: 90 + i % 5,
  close: 105 + i % 5, volume: 100 + i, oi: 500 + i, color: i === 5 ? '#aabbcc' : undefined,
}));

function fixture(options: WidgetOptions = {}) {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, pixelRatio: () => 1,
    rail: false, panels: false, mobile: 'never', animZoom: false, animAutoscale: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} }, ...options,
  });
  widgets.push(widget);
  widget.chart.applySize(800, 600);
  widget.series.setData(bars);
  widget.chart.setVisibleLogicalRange({ from: 0, to: 29 });
  return widget;
}

describe('widget chart type state', () => {
  it('keeps the primary handle, data identity, style and viewport across regular types', () => {
    const w = fixture();
    const series = w.series;
    const record = w.chart.panes()[0].series()[0];
    const style = { title: 'Primary source', color: '#abcdef', lineWidth: 4, lineStyle: 'dashed' as const,
      upColor: '#008844', downColor: '#bb2200', wickVisible: false, precision: 3,
      priceLineVisible: false, lastValueVisible: false, barOffset: 1 };
    series.applyOptions(style);
    const viewport = w.chart.getVisibleLogicalRange();
    const changes = vi.fn(); w.chart.on('data:update', changes);
    const layout = vi.fn(); w.on('layout', layout);
    for (const type of ['line', 'area', 'bar', 'candlestick']) {
      w.setChartType(type);
      expect(w.series).toBe(series);
      expect(w.chart.primarySeries()).toBe(series);
      expect(w.chart.panes()[0].series()[0]).toBe(record);
      expect(w.chart.primarySeriesInfo()).toMatchObject({ type, style });
      expect(w.series.getData()).toEqual(bars);
      expect(w.series.getData()[5]).toBe(bars[5]);
      expect(w.chart.getVisibleLogicalRange()).toEqual(viewport);
      expect(w.getState().chart.series?.[0]).toMatchObject({ type, style, paneIndex: 0 });
    }
    expect(changes).not.toHaveBeenCalled();
    expect(layout.mock.calls.filter(([event]) => event.reason === 'chartType')).toHaveLength(4);
    series.update({ ...bars[29], close: 120 });
    expect(w.series.getData()[29].close).toBe(120);
    expect(changes).toHaveBeenCalledTimes(1);
  });

  it('preserves left-scale configuration, ratio lock and marker data bindings', () => {
    const w = fixture();
    const series = w.series;
    expect(w.chart.movePriceAxis(0, 'right', 'left')).toBe(true);
    const scale = series.priceScale();
    scale.setOptions({ inverted: true, minMove: 0.25, minPrecision: 3 });
    scale.setAutoScale(false); scale.setPriceRange({ min: 50, max: 150 });
    expect(w.chart.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    const scaleState = w.getState().chart.panes?.[0].scales?.left;
    const markers = series.createMarkers();
    markers.setMarkers([{ id: 'entry', time: bars[5].time, position: 'inBar', shape: 'circle', size: 'small', color: '#aa22cc' }]);
    const hit = () => markers.hitTest(w.chart.timeScale.indexToX(5), scale.priceToY((bars[5].open + bars[5].close) / 2));
    expect(hit()?.externalId).toBe('entry');
    w.setChartType('line');
    expect(w.series.priceScale()).toBe(scale);
    expect(w.getState().chart.panes?.[0].scales?.left).toEqual(scaleState);
    expect(w.getState().chart.series?.[0].priceScaleId).toBe('left');
    expect(hit()?.externalId).toBe('entry');
  });

  it('retains panes, indicator instances and their source data', () => {
    registerIndicator({ id: 'type-state-study', name: 'Type state study', placement: 'pane', inputs: [],
      plots: [{ key: 'value', type: 'line', title: 'Value' }], calc: data => ({ value: data.map(bar => bar.close * 2) }),
    });
    const w = fixture();
    const indicator = w.chart.addIndicator('type-state-study');
    const panes = [...w.chart.panes()];
    const plot = panes[1].series()[0];
    const before = w.chart.dataLayer.seriesBars(plot.dataId);
    w.setChartType('area');
    expect(w.chart.panes()).toEqual(panes);
    expect(w.chart.indicators()).toEqual([indicator]);
    expect(w.chart.panes()[1].series()[0]).toBe(plot);
    expect(w.chart.dataLayer.seriesBars(plot.dataId)).toBe(before);
    w.series.update({ ...bars[29], close: 120 });
    expect(w.chart.dataLayer.seriesBars(plot.dataId)[29].close).toBe(240);
  });

  it('keeps same-type and invalid selections free of mutations and notifications', () => {
    const w = fixture();
    const series = w.series, state = w.getState();
    const layout = vi.fn(), changed = vi.fn();
    w.on('layout', layout); w.chart.on('objects:change', changed); w.chart.on('data:update', changed);
    w.setChartType('candlestick');
    expect(() => w.setChartType('unregistered-type')).toThrow(/not a registered chart type/);
    expect(w.series).toBe(series);
    expect(w.getState()).toEqual(state);
    expect(layout).not.toHaveBeenCalled(); expect(changed).not.toHaveBeenCalled();
  });

  it.each(['step', 'line-markers'])('drops inherited %s geometry defaults when selecting line', type => {
    const w = fixture({ chartType: type });
    w.setChartType('line');
    expect(w.chart.primarySeriesInfo()?.style.step).toBeUndefined();
    expect(w.chart.primarySeriesInfo()?.style.markers).toBeUndefined();
    expect(w.chart.primarySeriesInfo()?.style.lineWidth).toBe(1.5);
  });

  it('preserves explicit options while supplying only missing renderer defaults', () => {
    registerTransformChartTypes();
    const w = fixture({ chartType: 'line-markers' });
    w.series.applyOptions({ markers: false, step: false, lineWidth: 6, thickColor: '#112233', thinColor: undefined });
    w.setChartType('kagi');
    expect(w.chart.primarySeriesInfo()?.style).toMatchObject({ markers: false, step: false, lineWidth: 6, thickColor: '#112233' });
    expect(w.chart.primarySeriesInfo()?.style).toHaveProperty('thinColor', undefined);
    w.setChartType('line');
    expect(w.chart.primarySeriesInfo()?.style).toMatchObject({ markers: false, step: false, lineWidth: 6, thickColor: '#112233' });
    const defaults = fixture();
    defaults.setChartType('kagi');
    expect(defaults.chart.primarySeriesInfo()?.style).toMatchObject({ thickColor: '#26a69a', thinColor: '#ef5350' });
  });

  it.each(['point-figure', 'kagi'])('selects the %s renderer without transforming host-owned data', type => {
    registerTransformChartTypes();
    const w = fixture();
    const series = w.series;
    const transform = type === 'point-figure' ? new PointFigureTransform({ boxSize: 1, reversal: 2 }) : new KagiTransform({ reversal: 1 });
    const derived = runTransform(transform, bars);
    expect(derived.length).toBeGreaterThan(0);
    series.setData(derived);
    const stored = series.getData();
    w.setChartType(type);
    expect(w.series).toBe(series);
    expect(w.series.getData()).toEqual(stored);
    expect(w.series.getData()[0]).toBe(stored[0]);
    expect(w.getState().chart.series?.[0].type).toBe(type);
    w.setChartType('candlestick');
    expect(w.series.getData()).toEqual(stored);
    series.setData(bars);
    w.setChartType(type);
    expect(w.series.getData()).toEqual(bars);
  });

  it('keeps the existing handle through a saved type restore', () => {
    const w = fixture();
    w.series.applyOptions({ color: '#667788', lineWidth: 5 });
    w.setChartType('area');
    const saved = w.getState(), series = w.series;
    w.setChartType('line');
    expect(w.restoreState(saved).applied).toBe(true);
    expect(w.series).toBe(series);
    expect(w.chartType()).toBe('area');
    expect(w.getState().chart.series?.[0]).toEqual(saved.chart.series?.[0]);
    expect(series.getData()).toEqual(bars);
  });

  it('follows native renderer changes before making a widget selection', () => {
    const w = fixture();
    expect(w.chart.setSeriesType(w.series, 'line')).toBe(true);
    expect(w.chartType()).toBe('line');
    expect(w.getState().chartType).toBe('line');
    expect(w.root.querySelector('.oac-topbar__type')?.textContent).toContain('Line');
    w.setChartType('candlestick');
    expect(w.chartType()).toBe('candlestick');
    expect(w.chart.primarySeriesInfo()?.type).toBe('candlestick');
  });

  it('reads its live renderer even when the initial series did not claim primary ownership', () => {
    const w = fixture({ chartType: 'histogram' });
    expect(w.chart.primarySeries()).toBeNull();
    expect(w.chart.setSeriesType(w.series, 'line')).toBe(true);
    expect(w.chart.seriesType(w.series)).toBe('line');
    expect(w.chartType()).toBe('line');
    expect(w.getState().chartType).toBe('line');
    w.setChartType('histogram');
    expect(w.chart.seriesType(w.series)).toBe('histogram');
    expect(w.chart.primarySeries()).toBeNull();
  });

  it('keeps the latest reentrant chart type and publishes coherent notifications', () => {
    const w = fixture();
    const seen: [string, string | undefined][] = [];
    const layouts: string[] = [];
    w.on('layout', event => {
      seen.push([w.chartType(), w.chart.primarySeriesInfo()?.type]);
      if (event.reason === 'chartType') layouts.push(event.chartType!);
    });
    let changed = false;
    w.chart.on('objects:change', () => {
      if (changed) return;
      changed = true;
      w.setChartType('area');
    });
    w.setChartType('line');
    expect(w.chartType()).toBe('area');
    expect(w.chart.primarySeriesInfo()?.type).toBe('area');
    expect(seen.every(([widget, renderer]) => widget === renderer)).toBe(true);
    expect(layouts).toEqual(['area']);
  });
});

describe('native series renderer changes', () => {
  it('rejects unknown types and foreign, removed or destroyed series handles', () => {
    const w = fixture(), other = fixture();
    const before = w.getState();
    expect(() => w.chart.setSeriesType(w.series, 'unregistered-type' as SeriesType)).toThrow(/unknown series type/);
    expect(w.chart.seriesType(w.series)).toBe('candlestick');
    expect(w.chart.setSeriesType(other.series, 'line')).toBe(false);
    expect(w.chart.seriesType(other.series)).toBeNull();
    const removed = w.chart.addSeries('line');
    removed.remove();
    expect(w.chart.setSeriesType(removed, 'area')).toBe(false);
    expect(w.chart.seriesType(removed)).toBeNull();
    expect(w.chart.setSeriesType(w.series, 'candlestick')).toBe(false);
    expect(w.getState()).toEqual(before);
    w.destroy();
    expect(w.chart.setSeriesType(w.series, 'line')).toBe(false);
    expect(w.chart.seriesType(w.series)).toBeNull();
  });

  it('changes a secondary series without moving it or claiming primary ownership', () => {
    const w = fixture();
    const series = w.chart.addSeries('line', { paneIndex: 1, priceScaleId: 'overlay:native', style: { lineWidth: 3 } });
    series.setData(bars);
    const pane = w.chart.panes()[1], record = pane.series()[0], scale = series.priceScale();
    expect(w.chart.setSeriesType(series, 'area')).toBe(true);
    expect(w.chart.primarySeries()).toBe(w.series);
    expect(pane.series()[0]).toBe(record);
    expect(series.priceScale()).toBe(scale);
    expect(w.getState().chart.series?.[1]).toMatchObject({ type: 'area', paneIndex: 1, priceScaleId: 'overlay:native', style: { lineWidth: 3 } });
    w.chart.removePane(1);
    expect(w.chart.setSeriesType(series, 'line')).toBe(false);
  });

  it('applies and clears a target renderer precision default while preserving explicit precision', () => {
    const type = 'type-state-precision' as SeriesType;
    registerChartType(type, { ...getChartType('line'), defaultStyle: { precision: 1 } });
    const w = fixture();
    const scale = w.series.priceScale(), format = scale.format(107.123);
    expect(w.chart.setSeriesType(w.series, type)).toBe(true);
    expect(scale.format(107.123)).toBe('107.1');
    expect(w.chart.setSeriesType(w.series, 'candlestick')).toBe(true);
    expect(scale.format(107.123)).toBe(format);
    w.series.applyOptions({ precision: 3 });
    expect(w.chart.setSeriesType(w.series, type)).toBe(true);
    expect(scale.format(107.123)).toBe('107.123');
  });

  it.each<PriceFormat>([{ type: 'percent', precision: 1 }, { type: 'volume' },
    { type: 'custom', formatter: value => `value:${value}` }])('restores an explicit $type formatter after leaving a renderer precision default', priceFormat => {
    const type = 'type-state-format-precision' as SeriesType;
    registerChartType(type, { ...getChartType('line'), defaultStyle: { precision: 2 } });
    const w = fixture();
    const series = w.chart.addSeries('line', { paneIndex: 1, priceFormat });
    series.setData(bars);
    const scale = series.priceScale();
    const original = scale.format(12.345);
    if (priceFormat.type === 'percent') expect(original).toBe('12.3%');
    expect(w.chart.setSeriesType(series, type)).toBe(true);
    expect(scale.format(12.345)).toBe('12.35');
    expect(w.chart.setSeriesType(series, 'line')).toBe(true);
    expect(scale.format(12.345)).toBe(original);
  });
});
