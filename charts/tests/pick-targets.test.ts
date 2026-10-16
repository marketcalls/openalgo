import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false, branding: false,
    timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  charts.push(chart); chart.applySize(800, 600);
  const primary = chart.addSeries('line');
  primary.setData([10, 12, 15].map((value, index) => ({ time: 1000 + index * 60, value })));
  const secondary = chart.addSeries('line', { paneIndex: 1, priceScaleId: 'left' });
  secondary.setData([1000, 1200, 1500].map((value, index) => ({ time: 1000 + index * 60, value })));
  const hidden = chart.addSeries('line', { paneIndex: 1, priceScaleId: 'overlay:pick' });
  hidden.setData([-10, 0, 10].map((value, index) => ({ time: 1000 + index * 60, value })));
  chart.setPaneWeight(0, 1); chart.setPaneWeight(1, 1);
  chart.setVisibleLogicalRange({ from: 0, to: 2 });
  return { chart, element, secondary, hidden, primary };
}
function tap(element: FakeElement, x: number, y: number) {
  element.dispatch('pointerdown', pointer('down', x, y));
  element.dispatch('pointerup', pointer('up', x, y));
}
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

describe('targeted chart picks', () => {
  it('does not arm a replacement if cancelling its predecessor destroys the chart', () => {
    const { chart } = fixture();
    chart.beginPick('price', vi.fn());
    chart.once('pick:end', () => chart.destroy());
    const handle = chart.beginPick('price', vi.fn());
    expect(chart.isDestroyed).toBe(true);
    expect(handle.active()).toBe(false);
  });

  it.each(['remove', 'move'] as const)('cancels a targeted capture when panes %s', change => {
    const { chart, element } = fixture(), selected = vi.fn();
    chart.addSeries('line', { paneIndex: 2 }).setData([{ time: 1000, value: 3000 }]);
    const handle = chart.beginPick('price', selected, { paneIndex: 1, priceScaleId: 'left' });
    if (change === 'remove') chart.removePane(1);
    else chart.movePane(1, 1);
    tap(element, 250, chart.panes()[0].base.mediaHeight + 100);
    expect(selected).not.toHaveBeenCalled();
    expect(handle.active()).toBe(false);
  });

  it.each(['context', 'destroy', 'restore', 'replace', 'placement'] as const)('does not deliver a value after pick:end causes %s', change => {
    const { chart, element } = fixture(), selected = vi.fn();
    chart.once('pick:end', () => {
      if (change === 'context') chart.setDataContext({ symbol: 'NEW', exchange: 'TEST', interval: '1m' });
      if (change === 'destroy') chart.destroy();
      if (change === 'restore') chart.restoreState(chart.getState());
      if (change === 'replace') chart.beginPick('time', vi.fn());
      if (change === 'placement') chart.setPlacementMode(true);
    });
    const handle = chart.beginPick('price', selected);
    tap(element, 250, 140);
    expect(selected).not.toHaveBeenCalled();
    expect(handle.active()).toBe(false);
  });

  it.each(['left', 'overlay:pick'] as const)('uses the actual %s scale in the requested pane', priceScaleId => {
    const { chart, element, secondary, hidden } = fixture(), selected = vi.fn();
    const options = { paneIndex: 1, priceScaleId };
    chart.beginPick('price', selected, options);
    options.paneIndex = 0;
    tap(element, 250, 140);
    expect(selected).not.toHaveBeenCalled();
    const top = chart.panes()[0].base.mediaHeight;
    tap(element, 250, top + 140);
    const scale = priceScaleId === 'left' ? secondary.priceScale() : hidden.priceScale();
    expect(selected).toHaveBeenCalledExactlyOnceWith(scale.yToPrice(140));
  });

  it('rejects invalid targets without replacing an already armed pick', () => {
    const { chart, element } = fixture(), selected = vi.fn();
    chart.beginPick('price', selected);
    for (const options of [{ paneIndex: -1 }, { paneIndex: 99 }, { paneIndex: 0, priceScaleId: 'overlay:missing' },
      { paneIndex: 1.5 }, Object.defineProperty({}, 'paneIndex', { enumerable: true, get: () => { throw new Error('getter ran'); } })]) {
      expect(() => chart.beginPick('price', vi.fn(), options as never)).toThrow();
    }
    tap(element, 250, 140);
    expect(selected).toHaveBeenCalledTimes(1);
  });

  it('ignores other panes, off-plot events and cancelled gestures for time selection', () => {
    const { chart, element } = fixture(), selected = vi.fn();
    chart.beginPick('time', selected, { paneIndex: 1 });
    tap(element, 250, 140);
    chart.emit('click', { paneIndex: 1, point: { x: -1, y: 100 }, time: 1060, price: 5, id: null });
    chart.emit('click', { paneIndex: 1, point: { x: 250, y: 900 }, time: 1060, price: 5, id: null });
    const top = chart.panes()[0].base.mediaHeight, x = chart.timeToCoordinate(1060);
    element.dispatch('pointerdown', pointer('down', x, top + 140));
    element.dispatch('pointercancel', pointer('up', x, top + 140, { type: 'pointercancel' }));
    expect(selected).not.toHaveBeenCalled();
    tap(element, x, top + 140);
    expect(selected).toHaveBeenCalledExactlyOnceWith(1060);
  });

  it.each(['context', 'restore', 'destroy', 'data'] as const)('cancels after %s replacement without delivering a stale value', action => {
    const { chart, primary } = fixture(), selected = vi.fn(), ended = vi.fn();
    chart.on('pick:end', ended); chart.beginPick('price', selected);
    if (action === 'context') chart.setDataContext({ symbol: 'ABC', exchange: 'TEST', interval: '1m' });
    if (action === 'restore') chart.restoreState(chart.getState());
    if (action === 'destroy') chart.destroy();
    if (action === 'data') primary.setData([{ time: 1000, value: 44 }]);
    chart.emit('click', { paneIndex: 0, point: { x: 250, y: 100 }, price: 5, time: 1060, id: null });
    expect(selected).not.toHaveBeenCalled();
    expect(ended).toHaveBeenCalledExactlyOnceWith({ kind: 'price', value: null });
  });

  it('refuses active drawing placement and cancels if placement starts later', () => {
    const { chart } = fixture(), selected = vi.fn(), ended = vi.fn();
    chart.setPlacementMode(true);
    expect(() => chart.beginPick('price', selected)).toThrow(/drawing|placement/i);
    chart.setPlacementMode(false); chart.on('pick:end', ended);
    chart.beginPick('price', selected); chart.setPlacementMode(true);
    expect(ended).toHaveBeenCalledExactlyOnceWith({ kind: 'price', value: null });
    expect(selected).not.toHaveBeenCalled();
  });

  it('lets a newer pick started by cancellation take ownership', () => {
    const { chart, element } = fixture(), first = vi.fn(), second = vi.fn(), newest = vi.fn();
    chart.beginPick('price', first);
    const off = chart.on('pick:end', () => { off(); chart.beginPick('time', newest); });
    chart.beginPick('price', second);
    tap(element, 250, 140);
    expect(first).not.toHaveBeenCalled(); expect(second).not.toHaveBeenCalled();
    expect(newest).toHaveBeenCalledTimes(1);
  });
});
