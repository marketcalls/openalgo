import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import type { PriceFormat, PriceScaleId } from '../src/model/series';
import type { PriceScale } from '../src/scale/price-scale';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

const charts: Chart[] = [];
const bars = Array.from({ length: 40 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i,
}));
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); vi.unstubAllGlobals(); });

function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false,
    animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const series = chart.addSeries('line', { style: { color: '#aabbcc', lineWidth: 3 } });
  series.setData(bars);
  chart.setVisibleLogicalRange({ from: 0, to: 39 });
  return { chart, series, element, pane: chart.panes()[0] };
}

function manual(scale: PriceScale, min = 50, max = 200): void {
  scale.setAutoScale(false);
  scale.setPriceRange({ min, max });
}

describe('live series price-scale assignment', () => {
  it.each<PriceScaleId>(['left', '', 'overlay:source', 'overlay:'])('keeps series, data and marker bindings when assigned to %j', id => {
    const { chart, series, pane } = fixture();
    const record = pane.series()[0], data = chart.dataLayer.seriesBars(record.dataId);
    const target = pane.scaleFor(id);
    manual(target); target.setOptions({ inverted: true, marginTop: 0.2 });
    const markers = series.createMarkers();
    markers.setMarkers([{ id: 'entry', time: bars[10].time, position: 'inBar', shape: 'circle', size: 'small', color: '#cc2244' }]);
    const dataChanged = vi.fn(), objects = vi.fn();
    chart.on('data:update', dataChanged); chart.on('objects:change', objects);
    expect(chart.setSeriesPriceScale(series, id)).toBe(true);
    expect(chart.primarySeries()).toBe(series);
    expect(pane.series()[0]).toBe(record);
    expect(chart.dataLayer.seriesBars(record.dataId)).toBe(data);
    expect(series.priceScale()).toBe(target);
    expect(pane.priceToY(123)).toBe(target.priceToY(123));
    expect(markers.hitTest(chart.timeScale.indexToX(10), target.priceToY((bars[10].open + bars[10].close) / 2))?.externalId).toBe('entry');
    expect(chart.getState().series?.[0]).toMatchObject({ paneIndex: 0, priceScaleId: id, style: { color: '#aabbcc', lineWidth: 3 } });
    expect(dataChanged).not.toHaveBeenCalled(); expect(objects).toHaveBeenCalledTimes(1);
    expect(chart.setSeriesPriceScale(series, 'right')).toBe(true);
    series.update({ ...bars[39], close: 160 });
    expect(chart.primaryBars()[39].close).toBe(160);
  });

  it('retains shared and previously empty scales with independent modes, ranges and ratio locks', () => {
    const { chart, series, pane } = fixture();
    const source = series.priceScale();
    const peer = chart.addSeries('line'); peer.setData(bars);
    const resident = chart.addSeries('line', { priceScaleId: 'left' }); resident.setData(bars);
    const target = resident.priceScale();
    manual(source, 80, 160); manual(target, 10, 1000);
    source.setOptions({ inverted: true }); target.setOptions({ mode: 'logarithmic', marginBottom: 0.22 });
    expect(chart.setPriceAxisLockRatio(0, 'right', true)).toBe(true);
    expect(chart.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    const before = pane.scaleStates();
    expect(chart.setSeriesPriceScale(series, 'left')).toBe(true);
    expect(peer.priceScale()).toBe(source); expect(series.priceScale()).toBe(target);
    expect(pane.scaleStates()).toEqual(before);
    expect(chart.setSeriesPriceScale(series, 'overlay:retained')).toBe(true);
    const retained = series.priceScale();
    manual(retained, 30, 300); retained.setOptions({ inverted: true });
    expect(chart.setPriceAxisLockRatio(0, 'overlay:retained', true)).toBe(true);
    const retainedState = pane.scaleStates()['overlay:retained'];
    expect(chart.setSeriesPriceScale(series, 'left')).toBe(true);
    expect(chart.setSeriesPriceScale(series, 'overlay:retained')).toBe(true);
    expect(series.priceScale()).toBe(retained);
    expect(pane.scaleStates()['overlay:retained']).toEqual(retainedState);
  });

  it.each<PriceFormat>([{ type: 'percent', precision: 1 }, { type: 'volume' },
    { type: 'custom', formatter: value => `value:${value}` }, { type: 'price', minMove: 0.25 }])('applies explicit $type formatting to the target without rewriting the source', priceFormat => {
    const { chart, pane } = fixture();
    const resident = chart.addSeries('line', { priceScaleId: 'left' }); resident.setData(bars);
    const source = chart.addSeries('line', { priceFormat }); source.setData(bars);
    const origin = source.priceScale(), originalFormat = origin.format(1234.567);
    const target = resident.priceScale(); manual(target); target.setOptions({ inverted: true });
    const range = target.priceRange();
    expect(chart.setSeriesPriceScale(source, 'left')).toBe(true);
    expect(target.format(1234.567)).toBe(originalFormat);
    expect(origin.format(1234.567)).toBe(originalFormat);
    expect(target.priceRange()).toEqual(range);
    expect(target.options.inverted).toBe(true);
    expect(pane.series()).toHaveLength(3);
  });

  it('retains an existing target formatter unless the moving series explicitly supplies one', () => {
    const { chart, series, pane } = fixture();
    const target = pane.scaleFor('left');
    target.setPriceFormatter(value => `target:${value}`); manual(target);
    expect(chart.setSeriesPriceScale(series, 'left')).toBe(true);
    expect(target.format(123.45)).toBe('target:123.45');
    const precise = chart.addSeries('line', { style: { precision: 3 }, priceFormat: { type: 'percent', precision: 1 } });
    expect(chart.setSeriesPriceScale(precise, 'left')).toBe(true);
    expect(target.format(123.45)).toBe('123.450');
  });

  it('reserves columns only for used visible axes and restores the empty-chart default', () => {
    const { chart, series } = fixture();
    const second = chart.addSeries('line'); second.setData(bars);
    expect(chart.timeScale.width).toBe(744);
    expect(chart.setSeriesPriceScale(series, 'left')).toBe(true);
    expect(chart.timeScale.width).toBe(688);
    expect(chart.setSeriesPriceScale(second, '')).toBe(true);
    expect(chart.timeScale.width).toBe(744);
    expect(chart.setSeriesPriceScale(series, 'overlay:primary')).toBe(true);
    expect(chart.timeScale.width).toBe(800);
    series.remove(); second.remove();
    expect(chart.timeScale.width).toBe(744);
  });

  it.each(['right', 'left'] as const)('hides unused %s labels while retaining scale configuration', side => {
    const { chart, series, pane } = fixture();
    if (side === 'left') chart.movePriceAxis(0, 'right', 'left');
    const other = chart.addSeries('line', { paneIndex: 1, priceScaleId: side }); other.setData(bars);
    const scale = series.priceScale(); manual(scale);
    scale.setPriceFormatter(value => `vacated:${value}`);
    const range = scale.priceRange();
    const context = pane.base.ctx as unknown as RecordingContext;
    context.ops = [];
    expect(chart.setSeriesPriceScale(series, 'overlay:moved')).toBe(true);
    expect(context.ops.filter(op => op.type === 'fillText').map(op => op.text).some(text => text?.startsWith('vacated:'))).toBe(false);
    expect(scale.priceRange()).toEqual(range);
    expect(scale.format(123)).toBe('vacated:123');
  });

  it('does not draw a hidden readout scale tag in another scale column', () => {
    const { chart, series, pane, element } = fixture();
    chart.addSeries('line').setData(bars);
    expect(chart.setSeriesPriceScale(series, 'overlay:readout')).toBe(true);
    series.priceScale().setPriceFormatter(value => `hidden:${value}`);
    const context = pane.top.ctx as unknown as RecordingContext;
    context.ops = [];
    element.dispatch('pointermove', pointer('move', 400, 200, { buttons: 0 }));
    expect(context.ops.filter(op => op.type === 'fillText').map(op => op.text).some(text => text?.startsWith('hidden:'))).toBe(false);
  });

  it('rejects invalid IDs, no-ops and stale or foreign handles before any mutation', () => {
    const { chart, series, pane } = fixture(), other = fixture();
    const removed = chart.addSeries('line'); removed.remove();
    const state = chart.getState(), objects = vi.fn(); chart.on('objects:change', objects);
    for (const id of ['unknown', '__proto__', null, 5, {}]) expect(chart.setSeriesPriceScale(series, id as PriceScaleId)).toBe(false);
    expect(chart.setSeriesPriceScale(series, 'right')).toBe(false);
    expect(chart.setSeriesPriceScale(other.series, 'left')).toBe(false);
    expect(chart.setSeriesPriceScale(removed, 'left')).toBe(false);
    expect(chart.getState()).toEqual(state);
    expect(pane.scales()).toHaveLength(1);
    expect(objects).not.toHaveBeenCalled();
    const detached = chart.addSeries('line', { paneIndex: 1 }); chart.removePane(1);
    expect(chart.setSeriesPriceScale(detached, 'left')).toBe(false);
    chart.destroy(); expect(chart.setSeriesPriceScale(series, 'left')).toBe(false);
  });

  it('preserves indicator ownership and refuses independent movement of a study plot', () => {
    const calculation = vi.fn(data => ({ value: data.map((bar: { close: number }) => bar.close / 10) }));
    registerIndicator({ id: 'scale-assignment-study', name: 'Scale assignment study', placement: 'pane', inputs: [],
      plots: [{ key: 'value', type: 'line', title: 'Value' }], calc: calculation,
    });
    const { chart, series } = fixture();
    const indicator = chart.addIndicator('scale-assignment-study');
    const plot = indicator.series('value')!, scale = plot.priceScale(), values = indicator.values();
    calculation.mockClear();
    expect(chart.setSeriesPriceScale(plot, 'left')).toBe(false);
    expect(chart.setSeriesPriceScale(series, 'left')).toBe(true);
    expect(chart.indicators()).toEqual([indicator]);
    expect(indicator.series('value')).toBe(plot); expect(plot.priceScale()).toBe(scale);
    expect(indicator.values()).toBe(values); expect(calculation).not.toHaveBeenCalled();
    series.update({ ...bars[39], close: 160 });
    expect(indicator.values().value[39]).toBe(16);
  });
});
