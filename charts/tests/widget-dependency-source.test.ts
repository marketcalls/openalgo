import { afterEach, describe, expect, it, vi } from 'vitest';
import { INDICATOR_SOURCES, registerIndicator, type IndicatorApi, type IndicatorSettings, type IndicatorStudySource } from '../src/index';
import { createOverlayStack, type WidgetContext } from '../src/widget/context';
import { mountIndicatorSettings } from '../src/widget/dialogs/indicator-settings';
import { asDoc, asEl, installDom, type FakeElement } from './widget-form.test';

const reference = (instanceId: string): IndicatorStudySource => ({ kind: 'indicator', instanceId, plotKey: 'scalar' });
registerIndicator({ id: 'ui-dependency-consumer', name: 'Consumer', placement: 'onchart',
  inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true },
    { key: 'priceOnly', type: 'source', label: 'Price only', default: 'open' }],
  plots: [{ key: 'value', type: 'line', title: 'Consumer value' }], calc: () => ({ value: [] }) });
registerIndicator({ id: 'ui-dependency-producer', name: 'Repeated study', placement: 'pane', inputs: [],
  plots: [{ key: 'scalar', type: 'line', title: 'Scalar', offset: 4 },
    { key: 'candles', type: 'candlestick', title: 'Candles', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }],
  calc: () => ({ scalar: [], o: [], h: [], l: [], c: [] }) });

const cleanups: (() => void)[] = [];
afterEach(() => { for (const cleanup of cleanups.splice(0)) cleanup(); });
function setup(source: unknown = 'close') {
  const dom = installDom(), doc = asDoc(dom.doc), stack = createOverlayStack(asEl(dom.root), doc);
  cleanups.push(() => stack.destroy());
  const toasts: string[] = [], listeners = new Map<string, Set<() => void>>();
  let settings: IndicatorSettings = { source, priceOnly: 'open' }, reject = false;
  const setSettings = vi.fn((patch: IndicatorSettings) => {
    if (reject) throw new Error('Study dependency would create a cycle');
    settings = { ...settings, ...structuredClone(patch) };
  });
  // Every study handle has a policy; these allow everything, as a study the host placed without one does.
  const consumer = { id: 'consumer', indicatorId: 'ui-dependency-consumer', name: 'Consumer', policy: () => ({}),
    settings: () => structuredClone(settings), setSettings } as unknown as IndicatorApi;
  const producers = ['first', 'second'].map((id, index) => ({ id, indicatorId: 'ui-dependency-producer',
    name: 'Repeated study', paneIndex: index + 2, visible: () => false, policy: () => ({}),
    settings: () => ({ 'scalar:visible': false }), values: () => { throw new Error('Source choices must not calculate'); },
  }) as unknown as IndicatorApi);
  const instances = [consumer, ...producers];
  const chart = { indicators: () => instances.slice(), isDestroyed: false,
    on: (event: string, listener: () => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(listener); return () => { listeners.get(event)!.delete(listener); };
    } };
  const ctx = { chart, root: asEl(dom.root), document: doc, openOverlay: stack.open,
    toast: (message: string) => { toasts.push(message); },
  } as unknown as WidgetContext;
  const onClose = vi.fn();
  const handle = mountIndicatorSettings(ctx, undefined, { instanceId: consumer.id, onClose });
  const layer = stack.layer as unknown as FakeElement;
  const field = () => layer.querySelector('#oac-ind-consumer-source')!;
  const options = () => field().querySelectorAll('option');
  const click = (text: string) => layer.querySelectorAll('button').find(button => button.textContent === text)!.click();
  const select = (token: string) => { const input = field(); input.focus(); input.value = token; input.fire('change'); };
  return { consumer, instances, handle, layer, field, options, click, select, setSettings, toasts, onClose,
    dismiss: () => stack.destroy(),
    settings: () => settings, reject: (value: boolean) => { reject = value; },
    removed: () => { for (const listener of listeners.get('indicatorRemoved') ?? []) listener(); } };
}

describe('widget study source selection', () => {
  it('lists scalar outputs for distinct hidden and moved instances without changing ordinary source controls', () => {
    const rig = setup();
    const labels = rig.options().map(option => option.textContent);
    // Told apart by their place among their name, as every surface numbers them, never by an internal id.
    expect(labels).toContain('Repeated study (1) / Scalar');
    expect(labels).toContain('Repeated study (2) / Scalar');
    expect(labels.some(label => label.includes('first') || label.includes('second') || label.includes('['))).toBe(false);
    expect(labels.some(label => label.includes('Consumer value') || label.includes('Candles'))).toBe(false);
    expect(rig.options().some(option => option.value === 'close')).toBe(true);
    expect(rig.layer.querySelector('#oac-ind-consumer-priceOnly')!.querySelectorAll('option').map(option => option.value))
      .toEqual(INDICATOR_SOURCES.map(option => option.value));
  });

  it('maps opaque DOM tokens to fresh references and retains ordinary strings', () => {
    const rig = setup();
    const token = rig.options().find(option => option.textContent.startsWith('Repeated study (1)'))!.value;
    expect(token).not.toContain('first');
    rig.select(token);
    expect(rig.settings().source).toEqual(reference('first'));
    const passed = rig.setSettings.mock.calls[0][0].source as { instanceId: string };
    passed.instanceId = 'mutated outside';
    rig.select('hlc3'); expect(rig.settings().source).toBe('hlc3');
    rig.select(token); expect(rig.settings().source).toEqual(reference('first'));
  });

  it('shows an unavailable stored source without replacing it with close', () => {
    const rig = setup(reference('missing'));
    const selected = rig.options().find(option => option.value === rig.field().value)!;
    expect(selected.textContent).toContain('Unavailable');
    expect(selected.textContent).toContain('missing');
    expect(rig.field().value).not.toBe('close');
    rig.click('OK');
    expect(rig.setSettings).not.toHaveBeenCalled();
    expect(rig.settings().source).toEqual(reference('missing'));
  });

  it('restores a rejected focused selection and does not record a failed edit for Cancel', () => {
    const rig = setup(); rig.reject(true);
    expect(() => rig.select('hl2')).not.toThrow();
    expect(rig.field().value).toBe('close');
    expect(rig.toasts).toEqual(['Study dependency would create a cycle']);
    rig.click('Cancel');
    expect(rig.handle.isOpen()).toBe(false);
    expect(rig.setSettings).toHaveBeenCalledTimes(1);
  });

  it('keeps Cancel open when changed graph constraints reject the old source', () => {
    const rig = setup(reference('first'));
    rig.select('close'); rig.reject(true);
    expect(() => rig.click('Cancel')).not.toThrow();
    expect(rig.handle.isOpen()).toBe(true);
    expect(rig.settings().source).toBe('close');
    expect(rig.toasts).toEqual(['Study dependency would create a cycle']);
    rig.reject(false); rig.click('Cancel');
    expect(rig.settings().source).toEqual(reference('first'));
    expect(rig.handle.isOpen()).toBe(false);
  });

  it('keeps a rejected Escape rollback visible and allows accepting the current valid settings', () => {
    const rig = setup(reference('first'));
    rig.select('close'); rig.reject(true);
    expect(() => rig.field().fire('keydown', { key: 'Escape' })).not.toThrow();
    expect(rig.handle.isOpen()).toBe(true);
    expect(rig.settings().source).toBe('close');
    expect(rig.toasts).toEqual(['Study dependency would create a cycle']);
    rig.click('OK');
    expect(rig.handle.isOpen()).toBe(false);
  });

  it('keeps a removed producer readable and closes a removed consumer without writing stale settings', () => {
    const rig = setup(reference('first'));
    rig.instances.splice(1, 1); rig.removed();
    expect(rig.options().find(option => option.value === rig.field().value)!.textContent).toContain('Unavailable');
    rig.select('close');
    rig.instances.splice(0, 1);
    const calls = rig.setSettings.mock.calls.length;
    expect(() => rig.click('Cancel')).not.toThrow();
    expect(rig.setSettings).toHaveBeenCalledTimes(calls);
    expect(rig.handle.isOpen()).toBe(false);
  });

  it('finishes forced overlay teardown once when rollback has become invalid', () => {
    const rig = setup(reference('first'));
    rig.select('close'); rig.reject(true);
    expect(() => rig.dismiss()).not.toThrow();
    expect(rig.handle.isOpen()).toBe(false);
    expect(rig.settings().source).toBe('close');
    expect(rig.onClose).toHaveBeenCalledExactlyOnceWith(false);
  });
});
