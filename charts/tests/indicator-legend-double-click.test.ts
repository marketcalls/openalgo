import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

const charts: Chart[] = [];
let serial = 0;

function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  charts.push(chart);
  chart.applySize(800, 600);
  const primary = chart.addSeries('line');
  primary.setData(Array.from({ length: 96 }, (_, index) => ({
    time: 1700000000 + index * 60, open: 100 + index, high: 101 + index,
    low: 99 + index, close: 100 + index,
  })));
  const id = `legend-double-click-${++serial}`;
  registerIndicator({ id, name: 'Nearby study', placement: 'onchart', inputs: [],
    plots: [{ key: 'value', type: 'line', title: 'Value' }],
    calc: bars => ({ value: bars.map(bar => bar.close * 1.1) }) });
  const study = chart.addIndicator(id);
  chart.setVisibleLogicalRange({ from: 68, to: 98 });
  primary.priceScale().setAutoScale(false);
  primary.priceScale().setPriceRange({ min: 90, max: 220 });
  const context = chart.panes()[0].top.ctx as unknown as RecordingContext;
  context.ops = [];
  chart.setGridOptions({ vertLines: true });
  const point = (text: string) => {
    const op = context.ops.find(entry => entry.type === 'fillText' && entry.text === text);
    if (!op) throw new Error(`Missing rendered label: ${text}`);
    return { x: op.args[0] + 2, y: op.args[1] };
  };
  return { chart, element, primary, study, control: point('Indicators 1'), row: point('Nearby study') };
}

function tap(element: FakeElement, point: { x: number; y: number }, pointerType: string, button = 0) {
  element.dispatch('pointerdown', pointer('down', point.x, point.y, { pointerType, button }));
  element.dispatch('pointerup', pointer('up', point.x, point.y, { pointerType, button }));
}

function doubleClick(element: FakeElement, point: { x: number; y: number }) {
  element.dispatch('dblclick', { clientX: point.x, clientY: point.y });
}

afterEach(() => {
  for (const chart of charts.splice(0)) chart.destroy();
  vi.unstubAllGlobals();
});

describe('indicator control tap provenance', () => {
  it.each(['mouse', 'touch', 'pen'])('does not pair a consumed %s tap with the now-hidden study row', pointerType => {
    const { chart, element, primary, study, control, row } = fixture();
    const before = chart.getVisibleLogicalRange(), doubled = vi.fn();
    chart.on('dblclick', doubled);
    expect(study.legend()!.hitTest(row.x, row.y)).not.toBeNull();
    tap(element, control, pointerType);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    expect(study.legend()!.hitTest(row.x, row.y)).toBeNull();
    tap(element, row, pointerType);
    // Browsers may count these as two clicks on the same canvas element even
    // though the first press was consumed by the legend count control.
    doubleClick(element, row);
    expect(chart.getVisibleLogicalRange()).toEqual(before);
    expect(primary.priceScale().priceRange()).toEqual({ min: 90, max: 220 });
    expect(primary.priceScale().autoScale).toBe(false);
    expect(doubled).not.toHaveBeenCalled();
  });

  it.each(['mouse', 'touch', 'pen'])('still resets after two subsequent genuine %s plot presses', pointerType => {
    const { chart, element, primary, control } = fixture();
    const before = chart.getVisibleLogicalRange(), point = { x: 350, y: 250 }, doubled = vi.fn();
    chart.on('dblclick', doubled);
    tap(element, control, pointerType);
    tap(element, point, pointerType);
    tap(element, point, pointerType);
    doubleClick(element, point);
    expect(chart.getVisibleLogicalRange()).not.toEqual(before);
    expect(primary.priceScale().autoScale).toBe(true);
    expect(doubled).toHaveBeenCalledTimes(1);
  });

  it.each(['mouse', 'touch', 'pen'])('retains repeated %s toggles without plot or drawing double clicks', pointerType => {
    const { chart, element, primary, control } = fixture(), doubled = vi.fn(), clicked = vi.fn();
    chart.setPlacementMode(true);
    chart.on('dblclick', doubled); chart.on('click', clicked);
    tap(element, control, pointerType);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    tap(element, control, pointerType);
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    doubleClick(element, control);
    expect(primary.priceScale().autoScale).toBe(false);
    expect(doubled).not.toHaveBeenCalled(); expect(clicked).not.toHaveBeenCalled();
  });

  it('does not finish a drawing when a control tap is followed by the hidden row tap', () => {
    const { chart, element, control, row } = fixture(), doubled = vi.fn(), clicked = vi.fn();
    chart.setPlacementMode(true);
    chart.on('dblclick', doubled); chart.on('click', clicked);
    tap(element, control, 'touch'); tap(element, row, 'touch'); doubleClick(element, row);
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(doubled).not.toHaveBeenCalled();
  });

  it('retains genuine axis double clicks after a control press', () => {
    const { element, primary, control } = fixture(), axis = { x: 780, y: 250 };
    tap(element, control, 'mouse');
    tap(element, axis, 'mouse'); tap(element, axis, 'mouse');
    expect(primary.priceScale().autoScale).toBe(false);
    doubleClick(element, axis);
    expect(primary.priceScale().autoScale).toBe(true);
  });

  it.each(['mouse', 'pen'])('does not count a non-primary %s press between the consumed tap and plot tap', pointerType => {
    const { chart, element, control, row } = fixture(), before = chart.getVisibleLogicalRange();
    tap(element, control, pointerType);
    tap(element, row, pointerType, 2);
    tap(element, row, pointerType);
    doubleClick(element, row);
    expect(chart.getVisibleLogicalRange()).toEqual(before);
  });

  it.each(['pointercancel', 'lostpointercapture', 'drag'])('does not activate an interrupted control press (%s) or poison later plot clicks', interruption => {
    const { chart, element, control } = fixture(), point = { x: 350, y: 250 };
    element.dispatch('pointerdown', pointer('down', control.x, control.y, { pointerType: 'touch' }));
    if (interruption === 'drag') {
      element.dispatch('pointermove', pointer('move', point.x, point.y, { pointerType: 'touch' }));
      element.dispatch('pointerup', pointer('up', point.x, point.y, { pointerType: 'touch' }));
    } else {
      element.dispatch(interruption, pointer('up', control.x, control.y, { pointerType: 'touch' }));
    }
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    const before = chart.getVisibleLogicalRange();
    tap(element, point, 'touch'); tap(element, point, 'touch'); doubleClick(element, point);
    expect(chart.getVisibleLogicalRange()).not.toEqual(before);
  });
});
