import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions, type ChartNavigationOptions } from '../src/core/chart';
import { applyChartSettings, readChartSettings } from '../src/model/chart-settings';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { ShortcutManager } from '../src/input/shortcuts';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';
import type { WidgetContext } from '../src/widget/context';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });
function mount(options: Partial<ChartOptions> = {}) {
  vi.stubGlobal('window', {});
  let now = 0, id = 0;
  const queue = new Map<number, () => void>();
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, {
    document, pixelRatio: () => 1, shortcuts: { scope: 'global', persist: false },
    timeNavigator: false, animAutoscale: false, animZoom: false, now: () => now,
    raf: { schedule: cb => { queue.set(++id, cb); return id; }, cancel: key => { queue.delete(key); } }, ...options,
  });
  charts.push(chart);
  const tick = () => { now += 16; const due = [...queue]; for (const [key, cb] of due) if (queue.delete(key)) cb(); };
  const settle = () => { for (let i = 0; queue.size && i < 150; i++) tick(); };
  chart.applySize(800, 600);
  const source = chart.addSeries('line');
  source.setData(Array.from({ length: 200 }, (_, i) => ({ time: 1700000000 + i * 60, open: 100, high: 102, low: 98, close: 100 })));
  chart.setVisibleLogicalRange({ from: 100, to: 199 }); settle();
  const view = () => ({ range: chart.getVisibleLogicalRange(), price: { ...source.priceScale().priceRange() }, auto: source.priceScale().autoScale });
  const wheel = (extra: Record<string, unknown> = {}) => {
    const preventDefault = vi.fn();
    element.dispatch('wheel', { clientX: 300, clientY: 220, deltaX: 0, deltaY: -100, deltaMode: 0, preventDefault, ...extra });
    return preventDefault;
  };
  const key = (code: string, extra: Record<string, unknown> = {}) => {
    const preventDefault = vi.fn(); element.dispatch('keydown', { code, key: code, target: null, preventDefault, ...extra }); return preventDefault;
  };
  const press = (type: 'down' | 'move' | 'up', x: number, y: number, extra: Record<string, unknown> = {}) =>
    element.dispatch(`pointer${type}`, pointer(type, x, y, { type: `pointer${type}`, ...extra }));
  return { chart, element, source, queue, tick, settle, view, wheel, key, press };
}

describe('independent user navigation', () => {
  it('finishes navigator reveal and hide after one pointer event on an idle chart', () => {
    const f = mount({ timeNavigator: true });
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    const x = f.chart.timeScale.width / 2, y = 555;
    f.press('move', x, y, { buttons: 0 }); f.tick();
    expect(nav.animating()).toBe(true);
    f.settle();
    expect(nav.animating()).toBe(false);
    expect(nav.hitTest(x, y)?.externalId).toBe('timenav::resetScale');
    expect(f.queue.size).toBe(0);
    f.element.dispatch('pointerleave', pointer('move', x, y, { buttons: 0 }));
    f.tick(); expect(nav.animating()).toBe(true);
    f.settle();
    expect(nav.animating()).toBe(false);
    expect(nav.hitTest(x, y)).toBeNull();
    expect(f.queue.size).toBe(0);
  });

  it('cancels the remaining navigator animation frame on destruction', () => {
    const f = mount({ timeNavigator: true });
    f.press('move', f.chart.timeScale.width / 2, 555, { buttons: 0 }); f.tick();
    expect(f.queue.size).toBeGreaterThan(0);
    f.chart.destroy();
    expect(f.queue.size).toBe(0);
  });

  it('does not recurse indefinitely with a synchronous scheduler and a frozen clock', () => {
    let frames = 0;
    const f = mount({ timeNavigator: true, now: () => 0, raf: {
      schedule: callback => { if (++frames > 200) throw new Error('Unbounded frame scheduling'); callback(); return frames; },
      cancel: () => {},
    } });
    expect(() => f.press('move', f.chart.timeScale.width / 2, 555, { buttons: 0 })).not.toThrow();
    expect(frames).toBeLessThan(200);
  });

  it('suspends the fade during native image capture and resumes on pointer input', () => {
    const f = mount({ timeNavigator: true });
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    const x = f.chart.timeScale.width / 2;
    f.press('move', x, 555, { buttons: 0 }); f.tick();
    f.element.dispatch('contextmenu', { clientX: x, clientY: 555, preventDefault: vi.fn() });
    f.settle();
    expect(f.queue.size).toBe(0);
    f.press('move', x, 555, { buttons: 0 }); f.settle();
    expect(nav.animating()).toBe(false);
    expect(nav.hitTest(x, 555)?.externalId).toBe('timenav::resetScale');
  });

  it('stops scheduling when an animating navigator is detached', () => {
    const f = mount({ timeNavigator: true });
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    f.press('move', f.chart.timeScale.width / 2, 555, { buttons: 0 }); f.tick();
    f.chart.panes()[0].removePrimitive(nav); f.settle();
    expect(f.queue.size).toBe(0);
  });

  it('does not revive navigator frames when a cancelled callback arrives after destruction', () => {
    const f = mount({ timeNavigator: true });
    f.press('move', f.chart.timeScale.width / 2, 555, { buttons: 0 }); f.tick();
    const stale = [...f.queue.values()];
    expect(stale.length).toBeGreaterThan(0);
    f.chart.destroy();
    stale.forEach(callback => callback());
    expect(f.queue.size).toBe(0);
  });

  it('notifies host persistence once when policies change and ignores repeated values', () => {
    const f = mount(), changed = vi.fn(); f.chart.on('objects:change', changed);
    applyChartSettings(f.chart, { 'navigation.panEnabled': false });
    expect(changed).toHaveBeenCalledTimes(1);
    f.chart.setNavigationOptions({ panEnabled: false, zoomEnabled: true });
    expect(changed).toHaveBeenCalledTimes(1);
    f.chart.setNavigationOptions({ panEnabled: true, zoomEnabled: false });
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it('keeps a clean plot click when releasing capture reports loss synchronously', () => {
    const f = mount(), click = vi.fn(); f.chart.on('click', click);
    f.element.releasePointerCapture = () => f.element.dispatch('lostpointercapture', pointer('up', 300, 220));
    f.press('down', 300, 220); f.press('up', 300, 220);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('defaults both policies to true and accepts only own boolean data properties', () => {
    const f = mount();
    expect(f.chart.navigationOptions()).toMatchObject({ panEnabled: true, zoomEnabled: true });
    const getter = vi.fn(() => false);
    const patch = Object.create({ panEnabled: false });
    Object.defineProperty(patch, 'zoomEnabled', { get: getter });
    f.chart.setNavigationOptions(patch);
    f.chart.setNavigationOptions({ panEnabled: 0, zoomEnabled: 'false' } as unknown as ChartNavigationOptions);
    expect(getter).not.toHaveBeenCalled();
    expect(f.chart.navigationOptions()).toMatchObject({ panEnabled: true, zoomEnabled: true });
    f.chart.setNavigationOptions({ panEnabled: false, zoomEnabled: false });
    const detached = f.chart.navigationOptions() as ChartNavigationOptions;
    detached.panEnabled = true;
    expect(f.chart.navigationOptions().panEnabled).toBe(false);
    expect(mount().chart.navigationOptions().panEnabled).toBe(true);
  });

  for (const panEnabled of [false, true]) for (const zoomEnabled of [false, true]) {
    it(`gates wheel directions independently (${panEnabled},${zoomEnabled})`, () => {
      const f = mount({ navigation: { panEnabled, zoomEnabled } });
      const pan = vi.fn(), zoom = vi.fn(); f.chart.on('pan', pan); f.chart.on('zoom', zoom);
      const before = f.view();
      expect(f.wheel({ deltaX: 80, deltaY: 0 }).mock.calls.length).toBe(Number(panEnabled));
      expect(f.view().range.from !== before.range.from).toBe(panEnabled);
      expect(pan.mock.calls.length > 0).toBe(panEnabled);
      const spacing = f.chart.timeScale.barSpacing;
      expect(f.wheel().mock.calls.length).toBe(Number(zoomEnabled));
      expect(f.chart.timeScale.barSpacing !== spacing).toBe(zoomEnabled);
      expect(zoom.mock.calls.length > 0).toBe(zoomEnabled);
    });

    it(`separates pinch scale and centroid translation (${panEnabled},${zoomEnabled})`, () => {
      const f = mount({ navigation: { panEnabled, zoomEnabled } });
      const click = vi.fn(); f.chart.on('click', click);
      f.press('down', 250, 220, { pointerType: 'touch', pointerId: 1 });
      f.press('down', 450, 220, { pointerType: 'touch', pointerId: 2 });
      const spacing = f.chart.timeScale.barSpacing, price = f.view().price;
      f.press('move', 490, 250, { pointerType: 'touch', pointerId: 2 });
      expect(f.chart.timeScale.barSpacing !== spacing).toBe(zoomEnabled);
      expect(f.view().price.min !== price.min).toBe(panEnabled);
      if (!panEnabled && !zoomEnabled) expect(f.view().auto).toBe(true);
      f.press('up', 250, 220, { pointerType: 'touch', pointerId: 1 });
      f.press('up', 490, 250, { pointerType: 'touch', pointerId: 2 });
      expect(click).not.toHaveBeenCalled();
    });
  }

  it.each(['mouse', 'pen', 'touch'])('blocks %s plot drags without inventing a click or disabling autofit', pointerType => {
    const f = mount({ navigation: { panEnabled: false } }), before = f.view();
    const click = vi.fn(); f.chart.on('click', click);
    f.press('down', 300, 220, { pointerType }); f.tick();
    f.press('move', 370, 260, { pointerType }); f.press('up', 370, 260, { pointerType }); f.settle();
    expect(f.view()).toEqual(before); expect(click).not.toHaveBeenCalled();
    f.press('down', 300, 220, { pointerType }); f.press('up', 300, 220, { pointerType });
    expect(click).toHaveBeenCalledOnce();
  });

  it.each([{ shiftKey: true }, { ctrlKey: true }, { metaKey: true }])('classifies modified wheel input before consuming it (%j)', modifiers => {
    const f = mount({ navigation: { panEnabled: false, zoomEnabled: false } }), before = f.view();
    expect(f.wheel(modifiers)).not.toHaveBeenCalled(); expect(f.view()).toEqual(before);
  });

  it.each(['right', 'left', 'overlay:extra'])('blocks axis wheel and axis drag on %s without falling through to placement', scaleId => {
    const f = mount({ navigation: { zoomEnabled: false } });
    const source = scaleId === 'right' ? f.source : f.chart.addSeries('line', { priceScaleId: scaleId as 'left' });
    if (source !== f.source) source.setData(f.source.getData());
    f.chart.setPriceAxisPlacement(0, scaleId as 'right', scaleId === 'left' ? 'left' : 'right'); f.settle();
    const slot = f.chart.priceAxisLayout(0).find(s => s.scaleId === scaleId)!;
    const x = slot.x + slot.width / 2, before = { ...source.priceScale().priceRange() };
    expect(f.wheel({ clientX: x })).not.toHaveBeenCalled();
    const click = vi.fn(); f.chart.on('click', click); f.chart.setPlacementMode(true);
    f.press('down', x, 220); f.press('move', x, 260); f.press('up', x, 260);
    expect(source.priceScale().priceRange()).toEqual(before); expect(click).not.toHaveBeenCalled();
    const spacing = f.chart.timeScale.barSpacing;
    f.press('down', 300, 590); f.press('move', 400, 590); f.press('up', 400, 590);
    expect(f.chart.timeScale.barSpacing).toBe(spacing); expect(click).not.toHaveBeenCalled();
  });

  it.each(['panLeft', 'panRight', 'panLeftFast', 'panRightFast', 'panUp', 'panDown', 'panLeftBar', 'panRightBar', 'zoomIn', 'zoomOut', 'resetScale', 'fitContent'])('blocks the known %s shortcut without custom fallback', command => {
    const custom = vi.fn();
    const f = mount({ navigation: { panEnabled: false, zoomEnabled: false }, shortcuts: {
      scope: 'global', persist: false, overrides: { [command]: 'KeyQ' },
      customShortcuts: [{ command, combos: 'KeyQ', onTrigger: custom }],
    } });
    const trigger = vi.fn(); f.chart.shortcuts?.on(trigger);
    const before = f.view(); expect(f.key('KeyQ')).not.toHaveBeenCalled();
    expect(f.view()).toEqual(before); expect(custom).not.toHaveBeenCalled(); expect(trigger).not.toHaveBeenCalled();
  });

  it('keeps non-navigation keys and programmatic view setters operational', () => {
    const f = mount({ navigation: { panEnabled: false, zoomEnabled: false } });
    expect(f.key('KeyV', { altKey: true })).toHaveBeenCalledOnce();
    const before = f.view().range; f.chart.fitContent(); expect(f.view().range).not.toEqual(before);
    f.chart.setVisibleLogicalRange({ from: 20, to: 80 }); expect(f.view().range.from).toBeCloseTo(20);
    f.source.priceScale().setPriceRange({ min: 10, max: 20 });
    f.chart.resetScale(); expect(f.source.priceScale().autoScale).toBe(true);
  });

  it('suppresses default double-click reset after listeners change the policy', () => {
    const f = mount(), before = f.view();
    const listener = vi.fn(() => f.chart.setNavigationOptions({ zoomEnabled: false }));
    f.chart.on('dblclick', listener); f.element.dispatch('dblclick', { clientX: 300, clientY: 220 });
    expect(listener).toHaveBeenCalledOnce(); expect(f.view()).toEqual(before);
  });

  it.each(['plot', 'price', 'time', 'pinch'])('consumes the old %s gesture after disable and re-enable', gesture => {
    const f = mount(), click = vi.fn(); f.chart.on('click', click);
    const x = gesture === 'price' ? 780 : 300, y = gesture === 'time' ? 590 : 220;
    f.press('down', x, y, { pointerType: 'touch' });
    if (gesture === 'pinch') f.press('down', 500, 220, { pointerType: 'touch', pointerId: 2 });
    f.chart.setNavigationOptions({ panEnabled: false, zoomEnabled: false });
    f.chart.setNavigationOptions({ panEnabled: true, zoomEnabled: true });
    const before = f.view();
    f.press('move', x + 30, y + 20, { pointerType: 'touch' });
    f.press('up', x + 30, y + 20, { pointerType: 'touch' });
    if (gesture === 'pinch') f.press('up', 500, 220, { pointerType: 'touch', pointerId: 2 });
    f.settle(); expect(f.view()).toEqual(before); expect(click).not.toHaveBeenCalled();
    f.press('down', 300, 220); f.press('up', 300, 220); expect(click).toHaveBeenCalledOnce();
  });

  it.each(['panEnabled', 'zoomEnabled'] as const)('invalidates queued %s animation even if cancellation cannot remove old frames', field => {
    const f = mount({ animZoom: true });
    if (field === 'zoomEnabled') f.wheel();
    else { f.press('down', 300, 220, { pointerType: 'touch' }); f.tick(); f.press('move', 420, 220, { pointerType: 'touch' }); f.press('up', 420, 220, { pointerType: 'touch' }); }
    const queued = [...f.queue.values()];
    f.chart.setNavigationOptions({ [field]: false }); f.chart.setNavigationOptions({ [field]: true });
    const before = f.view(); queued.forEach(cb => cb()); f.settle(); expect(f.view()).toEqual(before);
  });

  it('retains an active gesture for same-value or invalid patches', () => {
    const f = mount(); f.press('down', 300, 220);
    f.chart.setNavigationOptions({ panEnabled: true, zoomEnabled: true });
    f.chart.setNavigationOptions({ panEnabled: null } as unknown as ChartNavigationOptions);
    const before = f.view(); f.press('move', 350, 220); expect(f.view().range).not.toEqual(before.range);
  });

  it('does not cancel zoom when a reentrant zoom listener disables only panning', () => {
    const f = mount({ animZoom: true }), spacing = f.chart.timeScale.barSpacing;
    f.chart.on('zoom', () => f.chart.setNavigationOptions({ panEnabled: false }));
    f.wheel(); f.settle(); expect(f.chart.timeScale.barSpacing).toBeCloseTo(spacing * 1.1, 9);
  });

  it('cannot restart a zoom glide from a listener that disables and re-enables zoom', () => {
    const f = mount({ animZoom: true });
    f.chart.on('zoom', () => {
      f.chart.setNavigationOptions({ zoomEnabled: false }); f.chart.setNavigationOptions({ zoomEnabled: true });
    });
    f.wheel(); const before = f.view(); f.settle(); expect(f.view()).toEqual(before);
  });

  it.each(['pointercancel', 'lostpointercapture'])('ends a pinch on %s without reviving the remaining finger', end => {
    const f = mount(), clicks = vi.fn(); f.chart.on('click', clicks);
    f.press('down', 200, 220, { pointerType: 'touch' });
    f.press('down', 400, 220, { pointerType: 'touch', pointerId: 2 });
    f.element.dispatch(end, pointer('up', 200, 220, { pointerType: 'touch', type: end }));
    const before = f.view();
    f.press('move', 500, 260, { pointerType: 'touch', pointerId: 2 });
    f.press('up', 500, 260, { pointerType: 'touch', pointerId: 2 }); f.settle();
    expect(f.view()).toEqual(before); expect(clicks).not.toHaveBeenCalled();
  });

  it('preserves drawing placement and primitive drags when policy changes', () => {
    const f = mount(), clicks = vi.fn(), dragged = vi.fn(); f.chart.on('click', clicks);
    f.chart.setPlacementMode(true); f.press('down', 300, 220);
    f.chart.setNavigationOptions({ panEnabled: false, zoomEnabled: false });
    f.press('move', 350, 260); f.press('up', 350, 260); expect(clicks).toHaveBeenCalledTimes(2);
    f.chart.setPlacementMode(false); f.chart.subscribeDrag(dragged);
    f.chart.addPriceLine({ id: 'editable', price: 100, color: '#336699', cursor: 'ns-resize' }); f.settle();
    const y = f.chart.priceToCoordinate(100)!;
    f.press('down', 300, y); f.chart.setNavigationOptions({ panEnabled: true });
    f.chart.setNavigationOptions({ panEnabled: false }); f.press('move', 320, y + 30); f.press('up', 320, y + 30);
    expect(dragged).toHaveBeenCalled();
  });

  it('uses the shared cancellation path when restore disables an active drag', () => {
    const f = mount(), clicks = vi.fn(); f.chart.on('click', clicks);
    const state = f.chart.getState(); f.press('down', 300, 220);
    f.chart.restoreState({ ...state, navigation: { panEnabled: false } });
    f.chart.setNavigationOptions({ panEnabled: true }); const before = f.view();
    f.press('move', 350, 250); f.press('up', 350, 250); expect(f.view()).toEqual(before); expect(clicks).not.toHaveBeenCalled();
  });

  it('rejects a stale host fit menu while leaving programmatic fit available', () => {
    const f = mount();
    const entries = () => contextMenuEntries({ chart: f.chart } as unknown as WidgetContext, {
      paneIndex: 0, point: { x: 300, y: 590 }, price: null, time: null, index: null,
      preventDefault() {}, target: { kind: 'time-scale', id: null },
    });
    const action = entries().find(entry => 'id' in entry && entry.id === 'chart-fit') as MenuItem;
    f.chart.setNavigationOptions({ zoomEnabled: false }); const before = f.view();
    expect(entries().find(entry => 'id' in entry && entry.id === 'chart-fit')).toMatchObject({ disabled: true });
    action.run?.(); expect(f.view()).toEqual(before);
    f.chart.fitContent(); expect(f.view().range).not.toEqual(before.range);
  });

  it('restores original navigator order and hints after filtering blocked controls', () => {
    const f = mount({ timeNavigator: { buttons: ['panRightBar', null, 'zoomIn', null, 'panLeftBar'], hints: { zoomIn: 'Custom' } } });
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    f.chart.setNavigationOptions({ panEnabled: false });
    expect(nav.options().buttons).toEqual(['zoomIn']); expect(nav.options().hints.zoomIn).toBe('Custom');
    f.chart.setNavigationOptions({ zoomEnabled: false }); expect(nav.options().buttons).toEqual([]);
    const before = f.view();
    expect((f.chart as unknown as { _handleLegendAction(id: string): boolean })._handleLegendAction('timenav::zoomIn')).toBe(true);
    expect(f.view()).toEqual(before);
    f.chart.setNavigationOptions({ panEnabled: true, zoomEnabled: true });
    expect(nav.options().buttons).toEqual(['panRightBar', null, 'zoomIn', null, 'panLeftBar']);
  });

  it('preserves deliberate custom navigator spacing whenever no actions are filtered', () => {
    const buttons = [null, 'panRightBar', null, null, 'zoomIn', null] as const;
    const f = mount({ timeNavigator: { buttons } });
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    expect(nav.options().buttons).toEqual(buttons);
    f.chart.setNavigationOptions({ panEnabled: false }); expect(nav.options().buttons).toEqual(['zoomIn']);
    f.chart.setNavigationOptions({ panEnabled: true }); expect(nav.options().buttons).toEqual(buttons);
  });

  it('saves and restores policy through settings while older partial state keeps it', () => {
    const f = mount(); applyChartSettings(f.chart, { 'navigation.panEnabled': false, 'navigation.zoomEnabled': false });
    expect(readChartSettings(f.chart)['navigation.panEnabled']).toBe(false);
    expect(f.chart.getState().navigation).toMatchObject({ panEnabled: false, zoomEnabled: false });
    const saved = f.chart.getState(); f.chart.setNavigationOptions({ panEnabled: true, zoomEnabled: true });
    f.chart.restoreState(saved); expect(f.chart.navigationOptions()).toMatchObject({ panEnabled: false, zoomEnabled: false });
    f.chart.restoreState({ ...saved, navigation: { mousePan: 'horizontal' } });
    expect(f.chart.navigationOptions()).toMatchObject({ panEnabled: false, zoomEnabled: false, mousePan: 'horizontal' });
  });

  it('names the Mod key Cmd in a navigator hint on a Mac', () => {
    const f = mount({ timeNavigator: true });
    vi.stubGlobal('navigator', { platform: 'MacIntel', userAgent: '' });
    expect(f.chart.shortcuts!.setBinding('zoomIn', 'Mod+Equal')).toBe(true);
    const nav = f.chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    expect(nav.options().hints.zoomIn).toBe('Cmd + +');
  });

  it('keeps the navigator hints on the chords in force after a rebind, unless the host fixed them', () => {
    const navOf = (chart: Chart) => chart.panes()[0].primitives().find(p => p instanceof TimeNavigator) as TimeNavigator;
    const f = mount({ timeNavigator: true });
    const nav = navOf(f.chart);
    const before = nav.options().hints.zoomIn;
    expect(before).toBeDefined();
    expect(f.chart.shortcuts!.setBinding('zoomIn', 'Alt+KeyI')).toBe(true);
    expect(nav.options().hints.zoomIn).not.toBe(before);
    f.chart.shortcuts!.resetBinding('zoomIn');
    expect(nav.options().hints.zoomIn).toBe(before);
    // Hints the host passed are its own, and stay.
    const fixed = mount({ timeNavigator: { hints: { zoomIn: 'Custom' } } });
    fixed.chart.shortcuts!.setBinding('zoomIn', 'Alt+KeyI');
    expect(navOf(fixed.chart).options().hints.zoomIn).toBe('Custom');
    // A destroyed chart lets go of a manager it shares with another.
    const shared = new ShortcutManager({ persist: false });
    const a = mount({ timeNavigator: true, shortcuts: shared });
    const b = mount({ timeNavigator: true, shortcuts: shared });
    const navA = navOf(a.chart);
    const gone = navA.options().hints.zoomIn;
    a.chart.destroy();
    shared.setBinding('zoomIn', 'Alt+KeyJ');
    expect(navA.options().hints.zoomIn).toBe(gone);
    expect(navOf(b.chart).options().hints.zoomIn).not.toBe(gone);
  });
});
