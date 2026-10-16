import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import * as runtime from '../src/model/indicator-instance';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { PriceScaleId } from '../src/model/series';
import { PriceLine } from '../src/primitives/price-line';
import { IndicatorFill } from '../src/primitives/indicator-fill';
import { SeriesMarkers } from '../src/primitives/markers';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [], detached: runtime.IndicatorInstance[] = [];
let sequence = 0;
afterEach(() => {
  detached.splice(0).forEach(instance => instance.remove());
  charts.splice(0).forEach(chart => chart.destroy());
  vi.unstubAllGlobals();
});

function fixture(patch: Partial<IndicatorDescriptor> = {}) {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false, branding: false,
    pixelRatio: () => 1, raf: { schedule: () => 1, cancel() {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.addSeries('candlestick').setData([1, 2, 3].map(time => ({ time, open: 10, high: 20, low: 5, close: 12.345 })));
  const calc = vi.fn(() => ({ a: [1, 2, 3], b: [4, 5, 6], price: [10, 11, 12] }));
  const attach = vi.fn();
  const descriptor: IndicatorDescriptor = { id: `plot-scales-${sequence++}`, name: 'Plot scales', placement: 'pane', inputs: [],
    plots: [{ key: 'a', type: 'line', title: 'A' }, { key: 'b', type: 'line', title: 'B', priceScaleId: 'left' },
      { key: 'price', type: 'line', title: 'Price', overlay: true }], calc, attach, ...patch };
  registerIndicator(descriptor);
  const host = (chart as unknown as { _indicatorHost(): runtime.IndicatorHost })._indicatorHost();
  return { chart, document, host, descriptor, calc, attach,
    add: () => chart.addIndicator(descriptor.id) as runtime.IndicatorInstance,
    construct: (map?: Readonly<Record<string, PriceScaleId>>, whole?: PriceScaleId) => {
      const instance = new runtime.IndicatorInstance(host, descriptor, {}, undefined, undefined, undefined, whole, map);
      detached.push(instance); return instance;
    },
  };
}

describe('per-plot scale assignments in the indicator model', () => {
  it('uses explicit constructor bindings before whole-study and descriptor defaults', () => {
    const h = fixture(), input = { a: 'overlay:a', price: 'left' } as const;
    const study = h.construct(input, '');
    const pane = h.chart.panes()[study.paneIndex];
    expect(study.series('a')!.priceScale()).toBe(pane.scaleFor('overlay:a'));
    expect(study.series('b')!.priceScale()).toBe(pane.scaleFor(''));
    expect(study.series('price')!.priceScale()).toBe(h.chart.panes()[0].scaleFor('left'));
    expect(study.plotPriceScaleId('missing')).toBeNull();
    expect(study.plotPriceScaleIds()).toEqual(input);
    expect(study.plotPriceScaleId('b')).toBe('');
  });

  it('detaches accepted and returned maps while retaining explicit default assignments', () => {
    const h = fixture(), input: Record<string, PriceScaleId> = { a: 'right' };
    const study = h.construct(input);
    input.a = 'left';
    const returned = study.plotPriceScaleIds() as Record<string, PriceScaleId>; returned.a = '';
    expect(study.plotPriceScaleIds()).toEqual({ a: 'right' });
    expect(study.plotPriceScaleId('a')).toBe('right');
  });

  it('rejects incompatible constructor fills before creating an owned pane or any resource', () => {
    const h = fixture({ fills: [{ between: ['a', 'b'] }] });
    const before = h.chart.getState(), event = vi.fn(); h.chart.on('paneAdded', event);
    expect(() => h.construct({ a: 'overlay:split' })).toThrow(/fill/i);
    expect(h.chart.getState()).toEqual(before);
    expect(event).not.toHaveBeenCalled(); expect(h.calc).not.toHaveBeenCalled(); expect(h.attach).not.toHaveBeenCalled();
  });

  it('rejects explicit whole-study fills across panes before allocation and retains legacy omission', () => {
    const h = fixture({ fills: [{ between: ['a', 'price'] }] });
    expect(() => h.construct(undefined, 'left')).toThrow(/fill/i);
    expect(h.chart.panes()).toHaveLength(1);
    expect(() => h.construct()).not.toThrow();
  });

  it('patches mixed local and price-pane plots without replacing handles or recomputing', () => {
    const h = fixture(), study = h.add();
    const handles = ['a', 'b', 'price'].map(key => study.series(key)), values = study.values();
    const calls = h.calc.mock.calls.length, attachments = h.attach.mock.calls.length;
    const changed = vi.fn(); h.chart.on('objects:change', changed);
    expect(study.setPlotPriceScales({ a: '', price: 'overlay:price' })).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({ a: '', price: 'overlay:price' });
    expect(['a', 'b', 'price'].map(key => study.series(key))).toEqual(handles);
    expect(study.series('a')!.priceScale()).toBe(h.chart.panes()[1].scaleFor(''));
    expect(study.series('b')!.priceScale()).toBe(h.chart.panes()[1].scaleFor('left'));
    expect(study.series('price')!.priceScale()).toBe(h.chart.panes()[0].scaleFor('overlay:price'));
    expect(study.values()).toBe(values); expect(h.calc).toHaveBeenCalledTimes(calls);
    expect(h.attach).toHaveBeenCalledTimes(attachments); expect(changed).toHaveBeenCalledTimes(1);
  });

  it('validates a whole patch and moves a fill only when both endpoints agree', () => {
    const h = fixture({ plots: [{ key: 'a', type: 'line', title: 'A' }, { key: 'b', type: 'line', title: 'B' }], fills: [{ between: ['a', 'b'] }] });
    const study = h.add(), pane = h.chart.panes()[1];
    const band = study.renderResources().primitives.find(item => item.primitive instanceof IndicatorFill)!.primitive;
    const changed = vi.fn(); h.chart.on('objects:change', changed);
    expect(study.setPlotPriceScales({ a: 'left' })).toBe(false);
    expect(study.plotPriceScaleIds()).toEqual({}); expect(pane.primitiveScaleId(band)).toBe('right');
    expect(changed).not.toHaveBeenCalled();
    expect(study.setPlotPriceScales({ a: 'left', b: 'left' })).toBe(true);
    expect(pane.primitiveScaleId(band)).toBe('left');
    expect(study.setPlotPriceScales({ a: null })).toBe(false);
    expect(study.plotPriceScaleIds()).toEqual({ a: 'left', b: 'left' });
    expect(study.setPlotPriceScales({ a: null, b: null })).toBe(true);
    expect(pane.primitiveScaleId(band)).toBe('right'); expect(changed).toHaveBeenCalledTimes(2);
  });

  it('keeps fixed defaults, levels and attached price drawings on the first local plot', () => {
    const drawing = new PriceLine({ price: 3, color: '#123456', id: 'attached' });
    const h = fixture({ range: () => ({ min: 0, max: 10 }), levels: () => [{ price: 5 }], attach: ctx => ctx.addPrimitive?.(drawing) });
    const study = h.add(), pane = h.chart.panes()[1];
    const level = study.renderResources().primitives.find(item => item.primitive instanceof PriceLine && item.primitive !== drawing)!.primitive;
    expect(study.setPlotPriceScales({ a: 'overlay:range' })).toBe(true);
    expect(pane.primitiveScaleId(level)).toBe('overlay:range'); expect(pane.primitiveScaleId(drawing)).toBe('overlay:range');
    expect(pane.priceScale.fixedRange).toBeNull(); expect(pane.scaleFor('overlay:range').fixedRange).toEqual({ min: 0, max: 10 });
    expect(pane.scaleFor('left').fixedRange).toBeNull();
    study.setVisible(false); study.setVisible(true);
    const rebuilt = study.renderResources().primitives.find(item => item.primitive instanceof PriceLine && item.primitive !== drawing)!.primitive;
    expect(pane.primitiveScaleId(rebuilt)).toBe('overlay:range');
  });

  it('clears local overrides through the unchanged whole ID but preserves price-overlay overrides', () => {
    const h = fixture(), study = h.add();
    expect(study.setPriceScale('left')).toBe(true);
    expect(study.setPlotPriceScales({ a: 'overlay:a', b: '', price: 'overlay:price' })).toBe(true);
    expect(study.setPriceScale('left')).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({ price: 'overlay:price' });
    expect(study.plotPriceScaleId('a')).toBe('left'); expect(study.plotPriceScaleId('b')).toBe('left');
    expect(study.setPriceScale('left')).toBe(false);
    expect(study.setPlotPriceScales({ a: '' })).toBe(true);
    expect(study.setPriceScale(null)).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({ price: 'overlay:price' });
    expect(study.plotPriceScaleId('a')).toBe('right'); expect(study.plotPriceScaleId('b')).toBe('left');
  });

  it('retains bindings during native renderer changes and legacy whole-axis adoption', () => {
    const h = fixture({ plots: [{ key: 'a', type: 'line', title: 'A' }, { key: 'b', type: 'line', title: 'B' }] }), study = h.add();
    study.setPlotPriceScales({ a: 'left', b: 'left' });
    const series = study.series('a'); study.setSettings({ 'a:type': 'area' });
    expect(study.series('a')).toBe(series); expect(study.plotPriceScaleId('a')).toBe('left');
    expect(h.chart.movePriceAxis(1, 'left', 'right')).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({}); expect(study.priceScaleId()).toBe('right');
    study.setSettings({ 'a:type': 'line' }); expect(study.plotPriceScaleId('a')).toBe('right');
  });

  it('retains bindings when an older host recreates plot series', () => {
    const h = fixture(); h.host.setIndicatorSeriesType = undefined;
    const study = h.construct({ a: 'overlay:retained', price: 'left' }), before = study.series('a');
    study.setSettings({ 'a:type': 'area' });
    expect(study.series('a')).not.toBe(before);
    expect(study.series('a')!.priceScale()).toBe(h.chart.panes()[study.paneIndex].scaleFor('overlay:retained'));
    expect(study.plotPriceScaleIds()).toEqual({ a: 'overlay:retained', price: 'left' });
  });

  it('publishes a complete assignment before synchronous observer reentry', () => {
    const h = fixture(), study = h.add(); let calls = 0;
    h.chart.on('objects:change', () => {
      if (++calls !== 1) return;
      expect(study.plotPriceScaleIds()).toEqual({ a: 'left', price: '' });
      expect(study.series('price')!.priceScale()).toBe(h.chart.panes()[0].scaleFor(''));
      expect(study.setPlotPriceScales({ a: 'overlay:later' })).toBe(true);
    });
    expect(study.setPlotPriceScales({ a: 'left', price: '' })).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({ a: 'overlay:later', price: '' }); expect(calls).toBe(2);
  });

  it('moves explicit overlay fills on the price pane and keeps them through a whole-study move', () => {
    const h = fixture({ plots: [{ key: 'a', type: 'line', title: 'A' },
      { key: 'b', type: 'line', title: 'B', overlay: true }, { key: 'price', type: 'line', title: 'Price', overlay: true }],
    fills: [{ between: ['b', 'price'], overlay: true }] });
    const study = h.add(), pane = h.chart.panes()[0];
    const band = study.renderResources().primitives.find(item => item.primitive instanceof IndicatorFill)!.primitive;
    expect(study.setPlotPriceScales({ b: 'overlay:band', price: 'overlay:band' })).toBe(true);
    expect(pane.primitiveScaleId(band)).toBe('overlay:band');
    expect(study.setPriceScale('left')).toBe(true);
    expect(pane.primitiveScaleId(band)).toBe('overlay:band');
    expect(study.plotPriceScaleIds()).toEqual({ b: 'overlay:band', price: 'overlay:band' });
  });

  it('keeps marker identity and follows its plot scale while refreshing legend formatting', () => {
    const h = fixture({ markers: () => [{ time: 3, position: 'atPrice', price: 3, shape: 'circle', size: 'small', color: '#123456' }] });
    const study = h.add(), pane = h.chart.panes()[1];
    const markers = study.renderResources().primitives.find(item => item.primitive instanceof SeriesMarkers)!.primitive;
    const values = vi.spyOn(study.legend()!, 'setValues');
    pane.scaleFor('overlay:format').setPriceFormatter(value => `unit ${value}`);
    expect(study.setPlotPriceScales({ a: 'overlay:format' })).toBe(true);
    expect(study.renderResources().primitives.some(item => item.primitive === markers)).toBe(true);
    h.chart.setVisibleLogicalRange({ from: 0, to: 2 });
    const projected = vi.spyOn(pane.scaleFor('overlay:format'), 'priceToY').mockReturnValue(33);
    markers.draw(h.document.createElement('canvas').getContext('2d')!, {
      dataLayer: h.chart.dataLayer, timeScale: h.chart.timeScale, priceScale: pane.priceScale, dpr: 1,
    } as PrimitiveRenderContext);
    expect(projected).toHaveBeenCalledWith(3);
    expect(values.mock.calls[values.mock.calls.length - 1]?.[0][0].text).toBe('unit 3');
  });

  it('retains unrelated scale formatting and resolves target peers in descriptor order', () => {
    const h = fixture({ plots: [
      { key: 'a', type: 'line', title: 'A', priceFormat: { type: 'percent', precision: 1 } },
      { key: 'b', type: 'line', title: 'B', priceScaleId: 'left', priceFormat: { type: 'volume' } },
      { key: 'price', type: 'line', title: 'Price', overlay: true, priceFormat: { type: 'percent', precision: 2 } },
    ] }), study = h.add();
    const untouched = h.chart.panes()[0].priceScale;
    untouched.setPriceFormatter(value => `host ${value}`);
    expect(study.setPlotPriceScales({ a: 'left' })).toBe(true);
    expect(h.chart.panes()[1].scaleFor('left').format(1000)).toBe('1.00K');
    expect(untouched.format(1000)).toBe('host 1000');
  });

  it('treats an explicit matching default as a change once and can clear it at the same null whole override', () => {
    const h = fixture(), study = h.add(), changed = vi.fn(); h.chart.on('objects:change', changed);
    expect(study.setPlotPriceScales({ a: 'right' })).toBe(true);
    expect(study.setPlotPriceScales({ a: 'right' })).toBe(false);
    expect(study.setPriceScale(null)).toBe(true);
    expect(study.plotPriceScaleIds()).toEqual({}); expect(changed).toHaveBeenCalledTimes(2);
  });

  it('does not rewrite a host formatter when only explicit assignment metadata changes', () => {
    const h = fixture({ plots: [{ key: 'a', type: 'line', title: 'A', priceFormat: { type: 'percent', precision: 2 } }] });
    const study = h.add(), scale = study.series('a')!.priceScale();
    scale.setPriceFormatter(value => `manual ${value}`);
    expect(study.setPlotPriceScales({ a: 'right' })).toBe(true);
    expect(scale.format(12)).toBe('manual 12');
    expect(study.setPriceScale('right')).toBe(true);
    expect(scale.format(12)).toBe('manual 12');
    expect(study.plotPriceScaleIds()).toEqual({});
  });

  it('rejects malformed construction before resource allocation or getter execution', () => {
    const h = fixture(), getter = vi.fn(() => 'left'), before = h.chart.getState();
    for (const map of [{ a: 'invalid' }, { missing: 'right' }, Object.defineProperty({}, 'a', { enumerable: true, get: getter })]) {
      expect(() => h.construct(map as never)).toThrow(TypeError);
      expect(h.chart.getState()).toEqual(before);
    }
    expect(getter).not.toHaveBeenCalled(); expect(h.calc).not.toHaveBeenCalled();
  });

  it('rejects invalid patches atomically without reading accessors', () => {
    const h = fixture(), study = h.add(), getter = vi.fn(() => 'left');
    const input = { a: 'left', get b() { return getter(); } };
    const changed = vi.fn(); h.chart.on('objects:change', changed);
    for (const patch of [input, { a: 'left', missing: 'right' }, { a: 'left', b: 'invalid' }, [], null, undefined]) {
      expect(study.setPlotPriceScales(patch as never)).toBe(false);
      expect(study.plotPriceScaleIds()).toEqual({});
    }
    expect(getter).not.toHaveBeenCalled(); expect(changed).not.toHaveBeenCalled();
    expect(study.setPlotPriceScales({})).toBe(false); expect(study.setPlotPriceScales({ a: null })).toBe(false);
    study.remove(); expect(study.setPlotPriceScales({ a: 'left' })).toBe(false);
  });

  it('leaves bindings, defaults and metadata untouched when the range callback throws', () => {
    let fail = false;
    const h = fixture({ range: () => { if (fail) throw new Error('Range failed'); return { min: 0, max: 10 }; } });
    const study = h.add(), before = h.chart.getState(), changed = vi.fn(); h.chart.on('objects:change', changed);
    fail = true;
    expect(() => study.setPlotPriceScales({ a: 'left' })).toThrow('Range failed');
    expect(study.plotPriceScaleIds()).toEqual({});
    expect(study.series('a')!.priceScale()).toBe(h.chart.panes()[1].priceScale);
    expect(h.chart.getState()).toEqual(before); expect(changed).not.toHaveBeenCalled();
    expect(() => study.setPriceScale('left')).toThrow('Range failed');
    expect(study.priceScaleId()).toBeNull(); expect(h.chart.getState()).toEqual(before);
  });

  it('abandons an outer assignment when range evaluation commits a newer assignment', () => {
    let redirect = false;
    const h = fixture({ range: () => {
      if (redirect) { redirect = false; study.setPlotPriceScales({ a: 'overlay:later' }); }
      return { min: 0, max: 10 };
    } });
    const study = h.add(); redirect = true;
    expect(study.setPlotPriceScales({ a: 'left' })).toBe(false);
    expect(study.plotPriceScaleIds()).toEqual({ a: 'overlay:later' });
    expect(study.series('a')!.priceScale()).toBe(h.chart.panes()[1].scaleFor('overlay:later'));
  });

  it('finishes geometry and notification before a legend formatter failure escapes', () => {
    const h = fixture({ plots: [{ key: 'a', type: 'line', title: 'A' }], range: () => ({ min: 0, max: 10 }) });
    const study = h.add(), pane = h.chart.panes()[1], changed = vi.fn(); h.chart.on('objects:change', changed);
    pane.scaleFor('left').setPriceFormatter(() => { throw new Error('Formatter failed'); });
    expect(() => study.setPlotPriceScales({ a: 'left' })).toThrow('Formatter failed');
    expect(study.plotPriceScaleIds()).toEqual({ a: 'left' });
    expect(study.series('a')!.priceScale()).toBe(pane.scaleFor('left'));
    expect(pane.scaleFor('left').fixedRange).toEqual({ min: 0, max: 10 }); expect(pane.priceScale.fixedRange).toBeNull();
    expect(h.chart.priceAxisLayout(1).find(slot => slot.scaleId === 'left')!.x).toBeGreaterThanOrEqual(0);
    expect(changed).toHaveBeenCalledTimes(1);
  });
});

describe('plot scale map preflight', () => {
  it('accepts undefined, null-prototype records and all native IDs with detached output', () => {
    const h = fixture(); expect(runtime.parseIndicatorPlotPriceScales(h.descriptor, undefined)).toEqual({});
    for (const id of ['right', 'left', '', 'overlay:', 'overlay:units']) {
      const input = Object.assign(Object.create(null), { a: id });
      const parsed = runtime.parseIndicatorPlotPriceScales(h.descriptor, input);
      input.a = 'changed'; expect(parsed).toEqual({ a: id });
    }
  });

  it('rejects unknown, malformed and non-data properties without evaluating getters', () => {
    const h = fixture(), getter = vi.fn();
    for (const input of [null, [], { a: null }, { a: 'invalid' }, { missing: 'right' },
      Object.create({ a: 'left' }), Object.defineProperty({}, 'a', { get: getter }),
      Object.defineProperty({}, 'a', { value: 'left' }), { [Symbol('a')]: 'left' }]) {
      expect(() => runtime.parseIndicatorPlotPriceScales(h.descriptor, input)).toThrow();
    }
    expect(getter).not.toHaveBeenCalled(); expect(h.chart.panes()).toHaveLength(1);
  });

  it('preflights fill geometry against proposed pane and scale before restore mutates resources', () => {
    const h = fixture({ fills: [{ between: ['a', 'b'] }] });
    expect(() => runtime.validateIndicatorScaleAssignment(h.descriptor, undefined, undefined, 1)).not.toThrow();
    expect(() => runtime.validateIndicatorScaleAssignment(h.descriptor, undefined, { a: 'left' }, 1)).not.toThrow();
    expect(() => runtime.validateIndicatorScaleAssignment(h.descriptor, undefined, { a: '' }, 1)).toThrow(/fill/i);
    const mixed = { ...h.descriptor, fills: [{ between: ['a', 'price'] as const }] };
    expect(() => runtime.validateIndicatorScaleAssignment(mixed, 'right', {}, 1)).toThrow(/fill/i);
    expect(() => runtime.validateIndicatorScaleAssignment(mixed, 'right', {}, 0)).not.toThrow();
  });

  it('treats an empty constructor map as omission for legacy descriptor-only fills', () => {
    const h = fixture({ fills: [{ between: ['a', 'b'] }] });
    expect(() => runtime.validateIndicatorScaleAssignment(h.descriptor, undefined, {}, 1)).not.toThrow();
    expect(() => h.construct({})).not.toThrow();
  });

  it('retains declared keys that also name object properties without changing prototypes', () => {
    const h = fixture({ plots: [{ key: '__proto__', type: 'line', title: 'Prototype' }, { key: 'toString', type: 'line', title: 'String' }] });
    const input = JSON.parse('{"__proto__":"left","toString":""}');
    const parsed = runtime.parseIndicatorPlotPriceScales(h.descriptor, input);
    expect(Object.getPrototypeOf(parsed)).toBe(Object.prototype);
    expect(Object.entries(parsed)).toEqual([['__proto__', 'left'], ['toString', '']]);
  });
});
