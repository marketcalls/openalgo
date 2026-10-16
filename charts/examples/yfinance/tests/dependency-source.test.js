import { afterEach, describe, expect, it, vi } from 'vitest';
import { INDICATOR_SOURCES, registerIndicator } from '/dist/openalgo-charts.mjs';
import { installDom } from './fake-dom.js';
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
vi.mock('../src/ui.js', async original => ({ ...await original(), toast: vi.fn() }));
import { toast } from '../src/ui.js';
import { initIndicators, openSettings, closeSettings, collectSettings, applySettings, collectInputRows } from '../src/indicators.js';

const reference = instanceId => ({ kind: 'indicator', instanceId, plotKey: 'scalar' });
registerIndicator({ id: 'demo-dependency-consumer-test', name: 'Consumer', placement: 'onchart',
  inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true },
    { key: 'priceOnly', type: 'source', label: 'Price only', default: 'open' }],
  plots: [{ key: 'value', type: 'line', title: 'Consumer value' }], calc: () => ({ value: [] }) });
registerIndicator({ id: 'demo-dependency-producer-test', name: 'Repeated study', placement: 'pane', inputs: [],
  plots: [{ key: 'scalar', type: 'line', title: 'Scalar', offset: 4 },
    { key: 'candles', type: 'candlestick', title: 'Candles', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }],
  calc: () => ({ scalar: [], o: [], h: [], l: [], c: [] }) });

afterEach(() => { closeSettings(); vi.clearAllMocks(); });
function setup(source = 'close') {
  const { document } = installDom();
  for (const id of ['set-body', 'set-title', 'setmodal', 'indadd', 'indpick', 'set-ok', 'set-x', 'set-reset', 'status', 'indlist']) {
    const node = document.createElement(id.startsWith('set-') && !['set-body', 'set-title'].includes(id) ? 'button' : 'div');
    node.id = id; document.body.appendChild(node);
  }
  for (const name of ['inputs', 'style']) {
    const tab = document.createElement('button'); tab.className = 'set-tab'; tab.dataset.tab = name; document.body.appendChild(tab);
  }
  let settings = { source, priceOnly: 'open' }, reject = false;
  const setSettings = vi.fn(patch => {
    if (reject) throw new Error('Study dependency would create a cycle');
    settings = { ...settings, ...structuredClone(patch) };
  });
  const consumer = { id: 'consumer', indicatorId: 'demo-dependency-consumer-test', name: 'Consumer',
    settings: () => structuredClone(settings), setSettings, values: () => ({}), series: () => null };
  const producers = ['first', 'second'].map((id, index) => ({ id, indicatorId: 'demo-dependency-producer-test', name: 'Repeated study',
    paneIndex: index + 2, visible: () => false, settings: () => ({}), values: () => ({}), series: () => null }));
  const instances = [consumer, ...producers];
  const listeners = new Map();
  const chart = { indicators: () => instances, getState: () => ({ indicators: [] }),
    on: (event, callback) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(callback); return () => listeners.get(event).delete(callback);
    } };
  const app = { chart, req: {}, focusPane: 1 }, target = { chart, pane: 1, current: () => true };
  initIndicators(app); openSettings('consumer', target);
  const field = () => document.getElementById('set-body_source');
  return { document, instances, setSettings, field, options: () => field().querySelectorAll('option'),
    removed: () => { for (const callback of listeners.get('indicatorRemoved') ?? []) callback(); },
    settings: () => settings, reject: value => { reject = value; } };
}

describe('reference host study source selection', () => {
  it('offers scalar study outputs with distinct identities while keeping price-only selectors unchanged', () => {
    const rig = setup(), labels = rig.options().map(option => option.textContent);
    // Numbered by their place among their name, as the widget numbers them, never named by an internal id.
    expect(labels).toContain('Repeated study (1) / Scalar');
    expect(labels).toContain('Repeated study (2) / Scalar');
    expect(labels.some(label => label.includes('first') || label.includes('second') || label.includes('['))).toBe(false);
    expect(labels.some(label => label.includes('Consumer value') || label.includes('Candles'))).toBe(false);
    expect(rig.document.getElementById('set-body_priceOnly').querySelectorAll('option').map(option => option.value))
      .toEqual(INDICATOR_SOURCES.map(option => option.value));
    const token = rig.options().find(option => option.textContent.startsWith('Repeated study (1)')).value;
    expect(token).not.toContain('first');
    rig.field().value = token;
    const values = collectInputRows(rig.document.getElementById('set-body'));
    expect(values.source).toEqual(reference('first'));
    values.source.instanceId = 'changed';
    expect(collectSettings()).toBe(true);
    expect(rig.settings().source).toEqual(reference('first'));
  });

  it('keeps an unresolved selected reference visible and unchanged on Apply', () => {
    const rig = setup(reference('missing'));
    expect(rig.options().find(option => option.value === rig.field().value).textContent).toContain('Unavailable');
    applySettings();
    expect(rig.settings().source).toEqual(reference('missing'));
    expect(rig.document.getElementById('setmodal').hidden).toBe(true);
  });

  it('keeps a rejected Apply or tab switch draft visible and reports the graph error', () => {
    const rig = setup(); rig.reject(true);
    rig.field().value = 'hl2';
    expect(() => applySettings()).not.toThrow();
    expect(rig.document.getElementById('setmodal').hidden).toBe(false);
    expect(rig.field().value).toBe('hl2');
    expect(rig.settings().source).toBe('close');
    expect(toast).toHaveBeenCalledWith('error', 'Study dependency would create a cycle');
    expect(() => rig.document.querySelectorAll('.set-tab')[1].click()).not.toThrow();
    expect(rig.field().value).toBe('hl2');
    rig.reject(false); applySettings();
    expect(rig.settings().source).toBe('hl2');
    expect(rig.document.getElementById('setmodal').hidden).toBe(true);
  });

  it('marks a removed draft producer unavailable without discarding the draft or choosing price', () => {
    const rig = setup();
    rig.field().value = rig.options().find(option => option.textContent.startsWith('Repeated study (1)')).value;
    rig.instances.splice(1, 1); rig.removed();
    expect(rig.options().find(option => option.value === rig.field().value).textContent).toContain('Unavailable');
    expect(collectInputRows(rig.document.getElementById('set-body')).source).toEqual(reference('first'));
    expect(rig.settings().source).toBe('close');
  });

  it('does not write a removed consumer even when a replacement has reused its saved identity', () => {
    const rig = setup();
    rig.instances[0] = { ...rig.instances[0], setSettings: vi.fn() };
    expect(collectSettings()).toBe(false);
    expect(rig.setSettings).not.toHaveBeenCalled();
    expect(rig.document.getElementById('setmodal').hidden).toBe(true);
  });
});
