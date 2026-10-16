import { beforeEach, describe, expect, it } from 'vitest';
import { getIndicator } from '/dist/openalgo-charts.mjs';
import { fakeDom } from './helpers.js';
import { bindIndicatorSource, closeIndicatorSource, initIndicatorSource, sourceSignalDescriptor } from '../src/indicator-source.js';

const sampleId = 'source-signal-sample';
function chartWith(symbol, instances) {
  const events = new Map();
  return {
    on(event, callback) {
      if (!events.has(event)) events.set(event, new Set());
      events.get(event).add(callback);
      return () => events.get(event).delete(callback);
    },
    emit(event, payload) { for (const callback of [...(events.get(event) || [])]) callback(payload); },
    listeners: () => [...events.values()].reduce((sum, items) => sum + items.size, 0),
    indicators: () => instances,
    getDataContext: () => ({ symbol, interval: '1d' }),
  };
}
const instance = id => ({ id, indicatorId: sampleId, name: 'Source signal sample' });
const request = instanceId => ({ instanceId, indicatorId: sampleId, paneIndex: 0 });
const node = id => document.getElementById(id);

describe('host-owned indicator source', () => {
  beforeEach(() => {
    fakeDom();
    closeIndicatorSource();
    node('indsource').hidden = true;
    initIndicatorSource();
  });

  it('registers an opt-in example with price labels and a transparent helper', () => {
    expect(getIndicator(sampleId)).toBeDefined();
    const descriptor = sourceSignalDescriptor();
    expect(descriptor).toMatchObject({ id: sampleId, category: 'Examples', hasSource: true, markerAnchor: 'price' });
    const bars = Array.from({ length: 25 }, (_, i) => ({ time: i + 1, open: 100, high: 104, low: 98, close: 102 }));
    expect(descriptor.plots.find(plot => plot.key === 'helper').style.color).toBe('transparent');
    expect(descriptor.calc(bars)).toMatchObject({ up: expect.any(Array), down: expect.any(Array), helper: Array(25).fill(101) });
    expect(descriptor.calc(bars).up[12]).toBeNull();
    expect(descriptor.calc(bars).down[12]).toBe(102);
    expect(descriptor.markers({ bars })).toEqual([
      { time: 13, position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef5350', text: 'Down' },
      { time: 25, position: 'belowBar', shape: 'labelUp', size: 'small', color: '#26a69a', text: 'Up' },
    ]);
  });

  it('uses the emitting chart and repeated instance identity, with source rendered only as text', () => {
    const primary = chartWith('AAPL', [instance('first')]);
    const secondary = chartWith('<img src=x>', [instance('first'), instance('second')]);
    const off1 = bindIndicatorSource(primary, 1);
    const off2 = bindIndicatorSource(secondary, 2);
    secondary.emit('indicatorSource', request('second'));
    expect(node('indsource').hidden).toBe(false);
    expect(node('indsource-owner').textContent).toContain('Chart 2');
    expect(node('indsource-owner').textContent).toContain('<img src=x>');
    // The second study of its name on that chart, numbered as the widget numbers it rather than by its internal id.
    expect(node('indsource-owner').textContent).toBe('Chart 2: <img src=x>, Source signal sample (2)');
    expect(node('indsource-owner').innerHTML).toBe('');
    expect(node('indsource-code').textContent).toContain(sourceSignalDescriptor.toString());
    expect(node('indsource-code').innerHTML).toBe('');
    primary.emit('destroy');
    expect(node('indsource').hidden).toBe(false);
    secondary.emit('indicatorRemoved', request('first'));
    expect(node('indsource').hidden).toBe(false);
    secondary.emit('indicatorRemoved', request('second'));
    expect(node('indsource').hidden).toBe(true);
    off1(); off2();
  });

  it('closes on owner destruction and detaches stale chart event handlers', () => {
    const old = chartWith('AAPL', [instance('one')]);
    bindIndicatorSource(old, 1);
    old.emit('indicatorSource', request('one'));
    expect(node('indsource').hidden).toBe(false);
    old.emit('destroy');
    expect(node('indsource').hidden).toBe(true);
    expect(old.listeners()).toBe(0);
    old.emit('indicatorSource', request('one'));
    expect(node('indsource').hidden).toBe(true);
    const replacement = chartWith('MSFT', [instance('restored')]);
    const off = bindIndicatorSource(replacement, 1);
    replacement.emit('indicatorSource', request('restored'));
    expect(node('indsource-owner').textContent).toContain('MSFT');
    expect(node('indsource-owner').textContent).toBe('Chart 1: MSFT, Source signal sample');
    off();
    expect(node('indsource').hidden).toBe(true);
  });

  it('does not invent source for unknown, removed or mismatched indicator instances', () => {
    const chart = chartWith('AAPL', [instance('one'), { id: 'builtin', indicatorId: 'ema' }]);
    const off = bindIndicatorSource(chart, 1);
    for (const payload of [request('missing'), request('builtin'), { ...request('one'), indicatorId: 'ema' }]) {
      chart.emit('indicatorSource', payload);
      expect(node('indsource').hidden).toBe(true);
    }
    off();
  });
});
