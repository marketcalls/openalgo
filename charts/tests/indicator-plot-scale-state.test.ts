import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
let next = 0;
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div') as unknown as FakeElement, {
    document, pixelRatio: () => 1, shortcuts: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} },
  });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 20 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i,
  })));
  const id = `plot-scale-state-${next++}`;
  registerIndicator({ id, name: 'Mixed readings', placement: 'pane', inputs: [],
    plots: [{ key: 'upper', title: 'Upper', type: 'line' }, { key: 'lower', title: 'Lower', type: 'line' },
      { key: 'price', title: 'Price', type: 'line', overlay: true }],
    fills: [{ between: ['upper', 'lower'] }], range: () => ({ min: 0, max: 100 }),
    calc: bars => ({ upper: bars.map(() => 75), lower: bars.map(() => 25), price: bars.map(bar => bar.close) }),
  });
  return { chart, id };
}

describe('per-plot assignments in chart state', () => {
  it('constructs and round-trips local and explicit price-pane assignments with range ownership', () => {
    const { chart, id } = fixture();
    const assignments = { upper: 'overlay:band', lower: 'overlay:band', price: 'left' } as const;
    const study = chart.addIndicator(id, {}, { plotPriceScaleIds: assignments });
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[1].scaleFor('overlay:band'));
    expect(study.series('price')!.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
    chart.setPriceAxisPlacement(1, 'overlay:band', 'left');
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.indicators[0].plotPriceScaleIds).toEqual(assignments);
    expect(state.panes[1].scales['overlay:band'].indicatorRange.instanceId).toBe(study.id);
    expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 1 });
    const restored = chart.indicators()[0];
    expect(restored.plotPriceScaleIds()).toEqual(assignments);
    expect(restored.series('price')!.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
    expect(chart.priceAxisPlacement(1, 'overlay:band')?.side).toBe('left');
    const previousScale = restored.series('upper')!.priceScale();
    expect(restored.setPlotPriceScales({ upper: 'right', lower: 'right' })).toBe(true);
    expect(previousScale.fixedRange).toBeNull();
    expect(restored.series('upper')!.priceScale().fixedRange).toEqual({ min: 0, max: 100 });
  });

  it.each([{ unknown: 'left' }, { upper: 'bad' }, { upper: 'left' }, { upper: null }])(
    'rejects invalid saved assignments %j before callbacks or mutation', assignments => {
      const { chart, id } = fixture();
      const study = chart.addIndicator(id);
      const before = chart.getState();
      const start = vi.fn(); chart.on('state:restore:start', start);
      const payload = JSON.parse(JSON.stringify(before));
      payload.indicators[0].plotPriceScaleIds = assignments;
      expect(chart.restoreState(payload).applied).toBe(false);
      expect(chart.indicators()).toEqual([study]);
      expect(chart.getState()).toEqual(before);
      expect(start).not.toHaveBeenCalled();
    },
  );

  it('detaches saved maps and rejects property accessors without invoking them', () => {
    const { chart, id } = fixture();
    const study = chart.addIndicator(id, {}, { plotPriceScaleIds: { price: 'left' } });
    const saved = chart.getState();
    saved.indicators![0].plotPriceScaleIds = { price: 'overlay:changed' };
    expect(study.plotPriceScaleId('price')).toBe('left');
    const getter = vi.fn(() => 'right');
    const payload = chart.getState();
    payload.indicators![0].plotPriceScaleIds = Object.defineProperty({}, 'price', { get: getter, enumerable: true });
    expect(chart.restoreState(payload).applied).toBe(false);
    expect(getter).not.toHaveBeenCalled();
    expect(chart.indicators()[0]).toBe(study);
  });

  it('rejects invalid construction without allocating panes, series or legends', () => {
    const { chart, id } = fixture();
    const before = chart.getState();
    for (const assignments of [{ missing: 'left' }, { upper: 'left' }, { price: 'bad' }]) {
      expect(() => chart.addIndicator(id, {}, { plotPriceScaleIds: assignments as never })).toThrow();
      expect(chart.getState()).toEqual(before);
      expect(chart.panes()).toHaveLength(1);
    }
  });

  it.each(['accessor', 'nonenumerable', 'inherited'])('rejects an outer %s map field without reading or mutating it', kind => {
    const { chart, id } = fixture();
    const study = chart.addIndicator(id);
    const payload = chart.getState();
    const spec = payload.indicators![0];
    const getter = vi.fn(() => ({ price: 'left' }));
    if (kind === 'accessor') Object.defineProperty(spec, 'plotPriceScaleIds', { enumerable: true, get: getter });
    else if (kind === 'nonenumerable') Object.defineProperty(spec, 'plotPriceScaleIds', { value: { price: 'invalid' } });
    else Object.setPrototypeOf(spec, { plotPriceScaleIds: { price: 'left' } });
    expect(chart.restoreState(payload).applied).toBe(false);
    expect(getter).not.toHaveBeenCalled();
    expect(chart.indicators()).toEqual([study]);
  });

  it('uses the validated snapshot if a restore callback changes the caller map', () => {
    const { chart, id } = fixture();
    chart.addIndicator(id);
    const payload = chart.getState();
    const assignments = { price: 'left' as const };
    payload.indicators![0].plotPriceScaleIds = assignments;
    chart.on('state:restore:start', () => { Object.assign(assignments, { price: 'invalid' }); });
    expect(chart.restoreState(payload).applied).toBe(true);
    expect(chart.indicators()[0].plotPriceScaleId('price')).toBe('left');
    expect(chart.getState().indicators![0].plotPriceScaleIds).toEqual({ price: 'left' });
  });

  it('refreshes restored legend readings after applying the saved scale precision', () => {
    const { chart, id } = fixture();
    const study = chart.addIndicator(id, {}, { plotPriceScaleIds: { upper: 'overlay:band', lower: 'overlay:band', price: 'left' } });
    chart.setPriceAxisOptions(1, 'overlay:band', { minPrecision: 4 });
    chart.setPriceAxisOptions(0, 'left', { minPrecision: 3 });
    study.updateLegendValues();
    const readings = (item: typeof study) => (item.legend() as unknown as { _values: { text: string }[] })._values.map(value => value.text);
    const before = readings(study);
    expect(before).toEqual(['75.0000', '25.0000', '121.000']);
    expect(chart.restoreState(chart.getState()).applied).toBe(true);
    expect(readings(chart.indicators()[0])).toEqual(before);
  });

  it('keeps assignments after pane relocation, settings recreation and a uniform axis move', () => {
    const { chart, id } = fixture();
    const study = chart.addIndicator(id, {}, { plotPriceScaleIds: { upper: 'left', lower: 'left', price: 'overlay:price' } });
    study.setSettings({ 'upper:type': 'area' });
    expect(chart.moveIndicator(study.id, 2)).toBe(true);
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[study.paneIndex].scaleFor('left'));
    expect(study.series('price')!.priceScale()).toBe(chart.panes()[0].scaleFor('overlay:price'));
    expect(chart.movePriceAxis(study.paneIndex, 'left', 'right')).toBe(true);
    const state = chart.getState();
    expect(state.indicators![0].plotPriceScaleIds).toEqual({ price: 'overlay:price' });
    expect(state.indicators![0].priceScaleId).toBe('right');
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.indicators()[0].series('upper')!.priceScale()).toBe(chart.panes()[study.paneIndex].scaleFor('right'));
  });

  it('restores legacy states without introducing an explicit map', () => {
    const { chart, id } = fixture();
    chart.addIndicator(id);
    const state = chart.getState();
    expect(state.indicators![0].plotPriceScaleIds).toBeUndefined();
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.indicators()[0].plotPriceScaleIds()).toEqual({});
    expect(chart.getState().indicators![0].plotPriceScaleIds).toBeUndefined();
  });

  it('replaces a prior percent formatter when a moved plot explicitly requests price units', () => {
    const { chart, id } = fixture();
    registerIndicator({ id: `${id}-units`, name: 'Independent units', placement: 'pane', inputs: [],
      plots: [{ key: 'signal', title: 'Signal', type: 'line', priceFormat: { type: 'price', precision: 2 } },
        { key: 'band', title: 'Band', type: 'line', priceScaleId: 'overlay:band', priceFormat: { type: 'percent', precision: 0 } }],
      calc: bars => ({ signal: bars.map(() => 0.35), band: bars.map(() => 67) }),
    });
    const study = chart.addIndicator(`${id}-units`);
    expect(study.setPriceScale('left')).toBe(true);
    const left = chart.panes()[study.paneIndex].scaleFor('left');
    expect(left.format(0.35)).toBe('0%');
    expect(study.setPriceScale(null)).toBe(true);
    expect(study.setPlotPriceScales({ signal: 'left' })).toBe(true);
    expect(left.format(0.35)).toBe('0.35');
    const state = chart.getState();
    study.setPriceScale('left');
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.indicators()[0].series('signal')!.priceScale().format(0.35)).toBe('0.35');
  });
});
