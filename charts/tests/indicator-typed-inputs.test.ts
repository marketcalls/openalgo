import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, indicatorDefaults, IndicatorInputError, type IndicatorDescriptor } from '../src/model/indicator-registry';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
let serial = 0;
const defaults = { symbol: '', exchange: '', session: '0930-1600:23456', note: 'First\nSecond',
  price: -2.5, timestamp: 1700000000.125, legacyTime: '2024-01-01 09:30' };

function descriptor(): IndicatorDescriptor {
  return {
    id: `typed-inputs-${++serial}`, name: 'Typed inputs', placement: 'onchart',
    inputs: [
      { key: 'symbol', type: 'symbol', label: 'Instrument', default: defaults.symbol, exchangeKey: 'exchange' },
      { key: 'exchange', type: 'text', label: 'Venue', default: '' },
      { key: 'session', type: 'session', label: 'Session', default: defaults.session },
      { key: 'note', type: 'multiline', label: 'Note', default: defaults.note },
      { key: 'price', type: 'price', label: 'Price', default: defaults.price, min: -100, max: 100, step: 0.05, pick: true },
      { key: 'timestamp', type: 'timestamp', label: 'Instant', default: defaults.timestamp, pick: true },
      { key: 'legacyTime', type: 'time', label: 'Wall time', default: defaults.legacyTime },
    ],
    plots: [{ key: 'price', title: 'Price', type: 'line' }, { key: 'timestamp', title: 'Instant', type: 'line' }],
    calc: (bars, settings) => ({ price: bars.map(() => Number(settings.price)), timestamp: bars.map(() => Number(settings.timestamp)) }),
  };
}

function mount() {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false,
    timeNavigator: false, branding: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.addSeries('line').setData([{ time: 1000, value: 10 }, { time: 1060, value: 12 }]);
  return chart;
}

afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

describe('typed native study inputs', () => {
  it('defaults undeclared exchange fields to empty text so a selected pair can be reverted', () => {
    const d = descriptor(); d.inputs = d.inputs.filter(input => input.key !== 'exchange');
    registerIndicator(d);
    expect(indicatorDefaults(d).exchange).toBe('');
    const inst = mount().addIndicator(d.id), before = inst.settings();
    inst.setSettings({ symbol: 'ABC', exchange: 'VENUE' });
    inst.setSettings({ symbol: before.symbol, exchange: before.exchange });
    expect(inst.settings()).toEqual(before);
  });

  it('keeps exact scalar defaults and accepts negative, zero and subsecond values', () => {
    const d = descriptor(); registerIndicator(d);
    expect(indicatorDefaults(d)).toEqual(defaults);
    const chart = mount(), inst = chart.addIndicator(d.id);
    inst.setSettings({ symbol: 'A-B', exchange: 'X', note: '  <b>literal</b>\n\nline  ', price: 0,
      timestamp: -0.125, session: '2200-0600:23456' });
    expect(inst.settings()).toMatchObject({ symbol: 'A-B', exchange: 'X', note: '  <b>literal</b>\n\nline  ',
      timestamp: -0.125, price: 0, session: '2200-0600:23456' });
    expect(inst.values()).toEqual({ price: [0, 0], timestamp: [-0.125, -0.125] });
    inst.setSettings({ price: 1.003 });
    expect(inst.values().price).toEqual([1.003, 1.003]);
  });

  it.each([
    ['symbol', 9], ['exchange', 9], ['session', '0900-2460'], ['session', '0930-1600junk'],
    ['session', '0930-1600:8'], ['note', 4], ['price', '2'], ['price', NaN], ['price', Infinity],
    ['price', -101], ['price', 101], ['timestamp', '1700000000'], ['timestamp', -Infinity], ['timestamp', undefined],
  ])('rejects invalid %s before calculation, resources, events or state change', (key, value) => {
    const d = descriptor(); registerIndicator(d);
    const chart = mount(), inst = chart.addIndicator(d.id), changed = vi.fn();
    chart.on('objects:change', changed);
    const state = chart.getState(), values = structuredClone(inst.values()), handle = inst.series('price');
    expect(() => inst.setSettings({ note: 'uncommitted', [key]: value })).toThrow(IndicatorInputError);
    expect(inst.values()).toEqual(values);
    expect(inst.series('price')).toBe(handle);
    expect(chart.getState()).toEqual(state);
    expect(changed).not.toHaveBeenCalled();
  });

  it('rejects malformed defaults and constraints without replacing a registered descriptor', () => {
    const d = descriptor(); registerIndicator(d);
    for (const patch of [{ default: NaN }, { min: 2, max: 1 }, { step: 0 }, { pick: { paneIndex: -1 } }]) {
      const bad = { ...d, inputs: d.inputs.map(input => input.key === 'price' ? { ...input, ...patch } : input) };
      expect(() => registerIndicator(bad as IndicatorDescriptor)).toThrow(IndicatorInputError);
    }
    expect(mount().addIndicator(d.id).settings().price).toBe(defaults.price);
  });

  it('rejects getter patches before evaluating their values', () => {
    const d = descriptor(); registerIndicator(d);
    const chart = mount(), inst = chart.addIndicator(d.id), getter = vi.fn(() => 3);
    const patch = Object.defineProperty({}, 'price', { enumerable: true, get: getter });
    expect(() => inst.setSettings(patch)).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(inst.settings().price).toBe(defaults.price);
    expect(() => chart.addIndicator(d.id, patch)).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(chart.indicators()).toHaveLength(1);
  });

  it('preflights invalid saved typed values before replacing the chart', () => {
    const d = descriptor(); registerIndicator(d);
    const chart = mount(), inst = chart.addIndicator(d.id), state = chart.getState();
    const invalid = structuredClone(state);
    invalid.indicators![0].settings!.price = 'bad';
    const report = chart.restoreState(invalid);
    expect(report.applied).toBe(false);
    expect(report.reason).toContain('price');
    expect(chart.indicators()[0]).toBe(inst);
    expect(chart.getState()).toEqual(state);
  });

  it('restores absolute instants and literal text without changing legacy wall time', () => {
    const d = descriptor(); registerIndicator(d);
    const chart = mount(), inst = chart.addIndicator(d.id);
    inst.setSettings({ timestamp: 1700000000.125, note: '\nuntouched\n', price: -3.75 });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const other = mount();
    expect(other.restoreState(state).applied).toBe(true);
    expect(other.indicators()[0].settings()).toEqual(inst.settings());
    other.setTimezone('America/New_York');
    expect(other.indicators()[0].settings()).toMatchObject({ timestamp: 1700000000.125, legacyTime: defaults.legacyTime });
  });
});
