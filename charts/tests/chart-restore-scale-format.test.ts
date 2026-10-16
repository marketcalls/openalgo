import { afterEach, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
let next = 0;
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

function fixture(studyPrecision?: number) {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, shortcuts: false, branding: false, pixelRatio: () => 1,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} },
  });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('line').setData([{ time: 1, value: 10 }, { time: 2, value: 12 }]);
  const id = `restore-scale-format-${next++}`;
  registerIndicator({ id, name: 'Percent reading', placement: 'onchart', inputs: [],
    plots: [{ key: 'value', title: 'Value', type: 'line', priceFormat: { type: 'percent', precision: 2 },
      ...(studyPrecision === undefined ? {} : { style: { precision: studyPrecision } }) }],
    calc: bars => ({ value: bars.map(bar => bar.close) }),
  });
  return { chart, id, state: { version: 1, indicators: [{ indicatorId: id, settings: {}, paneIndex: 0 }] } };
}

it.each(['default', 'custom', 'precision'] as const)('preserves selected %s formatting during automatic study reconstruction', kind => {
  const { chart, state } = fixture(), scale = chart.primarySeries()!.priceScale();
  if (kind === 'custom') scale.setPriceFormatter(value => `unit ${value.toFixed(3)}`);
  if (kind === 'precision') chart.primarySeries()!.applyOptions({ precision: 3 });
  const before = scale.format(12.3456), observed: string[] = [];
  chart.on('objects:change', () => observed.push(scale.format(12.3456)));
  expect(chart.restoreState(state, { preserveScaleFormats: [{ paneIndex: 0, scaleId: 'right' }] }).applied).toBe(true);
  expect(scale.format(12.3456)).toBe(before);
  expect(observed.length).toBeGreaterThan(0);
  expect(observed.every(value => value === before)).toBe(true);
  expect(chart.restoreState(state).applied).toBe(true);
  expect(scale.format(12.3456)).toBe('12.35%');
});

it('scopes preservation to selected existing scales and releases it before later study changes', () => {
  const { chart, state } = fixture(1);
  chart.primarySeries()!.applyOptions({ precision: 3 });
  const named = chart.addSeries('line', { priceScaleId: 'overlay:units', style: { precision: 1 } }).priceScale();
  const pane = chart.getState().panes!;
  const studies = [state.indicators[0], { ...state.indicators[0], priceScaleId: 'overlay:units' as const }];
  expect(chart.restoreState({ ...state, panes: pane, indicators: studies }, {
    preserveScaleFormats: [{ paneIndex: 0, scaleId: 'right' }],
  }).applied).toBe(true);
  expect(chart.primarySeries()!.priceScale().format(12.3456)).toBe('12.346');
  expect(named.format(12.3456)).toBe('12.3');
  chart.indicators()[0].setSettings({});
  expect(chart.primarySeries()!.priceScale().format(12.3456)).toBe('12.3');
});

it.each([
  { preserveScaleFormats: 'right' },
  { preserveScaleFormats: [{ paneIndex: -1, scaleId: 'right' }] },
  { preserveScaleFormats: [{ paneIndex: 1, scaleId: 'right' }] },
  { preserveScaleFormats: [{ paneIndex: 0, scaleId: 'overlay:absent' }] },
  { preserveScaleFormats: [{ paneIndex: 0, scaleId: 'invalid' }] },
])('rejects malformed or absent format selectors before mutation: %j', options => {
  const { chart, state } = fixture(), before = chart.getState(), start = vi.fn();
  chart.on('state:restore:start', start);
  expect(chart.restoreState(state, options as never).applied).toBe(false);
  expect(chart.getState()).toEqual(before);
  expect(start).not.toHaveBeenCalled();
});

it('does not read selector accessors or leave preservation active after a failed constructor', () => {
  const { chart, state, id } = fixture(), getter = vi.fn(() => 0);
  const selector = Object.defineProperty({ scaleId: 'right' }, 'paneIndex', { enumerable: true, get: getter });
  expect(chart.restoreState(state, { preserveScaleFormats: [selector as never] }).applied).toBe(false);
  expect(getter).not.toHaveBeenCalled();
  registerIndicator({ id: `${id}-fails`, name: 'Failure', placement: 'onchart', inputs: [],
    plots: [{ key: 'value', type: 'line', title: 'Value', priceFormat: { type: 'percent' } }],
    calc: () => { throw new Error('Calculation failed'); },
  });
  chart.primarySeries()!.applyOptions({ precision: 3 });
  expect(() => chart.restoreState({ version: 1, indicators: [{ indicatorId: `${id}-fails`, settings: {}, paneIndex: 0 }] }, {
    preserveScaleFormats: [{ paneIndex: 0, scaleId: 'right' }],
  })).toThrow('Calculation failed');
  expect(chart.primarySeries()!.priceScale().format(12.3456)).toBe('12.346');
  chart.addIndicator(id);
  expect(chart.primarySeries()!.priceScale().format(12.3456)).toBe('12.35%');
});

it('keeps an explicit default formatter when an unused hidden scale is recreated', () => {
  const { chart, id } = fixture();
  const study = chart.addIndicator(id, {}, { priceScaleId: 'overlay:solo' });
  study.series('value')!.priceScale().setPriceFormatter(null);
  const before = study.series('value')!.priceScale().format(12.3456);
  expect(before).toBe('12.35');
  expect(chart.restoreState(chart.getState(), {
    preserveScaleFormats: [{ paneIndex: 0, scaleId: 'overlay:solo' }],
  }).applied).toBe(true);
  expect(chart.indicators()[0].series('value')!.priceScale().format(12.3456)).toBe(before);
});

it('rejects selector-list accessors without invoking them or mutating the chart', () => {
  const { chart, state } = fixture(), before = chart.getState();
  const getter = vi.fn(() => {
    chart.primarySeries()!.priceScale().setOptions({ inverted: true });
    return { paneIndex: 0, scaleId: 'overlay:absent' };
  });
  const selectors = Object.defineProperty([], '0', { enumerable: true, get: getter });
  expect(chart.restoreState(state, { preserveScaleFormats: selectors }).applied).toBe(false);
  expect(getter).not.toHaveBeenCalled();
  expect(chart.getState()).toEqual(before);
});
