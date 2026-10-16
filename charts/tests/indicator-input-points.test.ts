/**
 * A time input and a price input that name one point together: the
 * descriptor pairing, its validation, and the pick that captures both halves
 * from one click.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { IndicatorInputError, registerIndicator, type IndicatorInput } from '../src/model/indicator-registry';
import type { PickPoint } from '../src/input/pick';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

let serial = 0;
const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

const time: IndicatorInput = { key: 'at', type: 'timestamp', label: 'Anchor time', default: 1000 };
const price = (extra: Partial<Extract<IndicatorInput, { type: 'price' }>> = {}): IndicatorInput =>
  ({ key: 'level', type: 'price', label: 'Anchor price', default: 10, pick: true, timeKey: 'at', ...extra }) as IndicatorInput;
function register(inputs: IndicatorInput[]): string {
  const id = `input-point-${++serial}`;
  registerIndicator({ id, name: 'Anchored level', placement: 'onchart', inputs,
    plots: [{ key: 'v', title: 'Level', type: 'line' }], calc: (bars, settings) => ({ v: bars.map(() => settings.level as number) }) });
  return id;
}

describe('paired time and price inputs', () => {
  it('registers a price that names the timestamp it pairs with, anchor or not', () => {
    expect(() => register([time, price()])).not.toThrow();
    expect(() => register([price({ anchor: true }), time])).not.toThrow();
    expect(() => register([time, price({ anchor: false })])).not.toThrow();
  });

  it.each([
    ['an undeclared input', [price({ timeKey: 'missing' })]],
    ['a text input', [{ key: 'at', type: 'text', label: 'Time', default: '' } as IndicatorInput, price()]],
    ['a wall-clock time input', [{ key: 'at', type: 'time', label: 'Time', default: '2026-01-01 09:15' } as IndicatorInput, price()]],
    ['itself', [time, price({ timeKey: 'level' })]],
    ['an empty key', [time, price({ timeKey: '' })]],
    ['a non-string key', [time, price({ timeKey: 5 as unknown as string })]],
    ['a timestamp another price already pairs with', [time, price(), price({ key: 'other' })]],
  ])('refuses a pair with %s', (_name, inputs) => {
    expect(() => register(inputs as IndicatorInput[])).toThrow(IndicatorInputError);
  });

  it('refuses an anchor that is not a boolean or has no time to pair with', () => {
    expect(() => register([time, price({ anchor: 'yes' as unknown as boolean })])).toThrow(IndicatorInputError);
    expect(() => register([time, price({ timeKey: undefined, anchor: true })])).toThrow(/anchor/);
  });
});

function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false, branding: false,
    timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('line').setData([10, 12, 15, 11].map((value, index) => ({ time: 1000 + index * 60, value })));
  const other = chart.addSeries('line', { paneIndex: 1, priceScaleId: 'overlay:point' });
  other.setData([-10, 0, 10, 5].map((value, index) => ({ time: 1000 + index * 60, value })));
  chart.setPaneWeight(0, 1); chart.setPaneWeight(1, 1);
  chart.setVisibleLogicalRange({ from: 0, to: 3 });
  return { chart, element, other };
}
function tap(element: FakeElement, x: number, y: number) {
  element.dispatch('pointerdown', pointer('down', x, y));
  element.dispatch('pointerup', pointer('up', x, y));
}

describe('Chart.beginPick for a point', () => {
  it('answers one click with the bar time under it and the price under it, together', () => {
    const { chart, element } = fixture(), selected = vi.fn<(value: PickPoint) => void>();
    const events: unknown[] = [];
    for (const event of ['pick:start', 'pick:end']) chart.on(event, payload => events.push({ event, payload }));
    const handle = chart.beginPick('point', selected);
    expect(handle.active()).toBe(true);
    // A little right of the second bar: the time snaps to that bar.
    const x = chart.timeToCoordinate(1060)! + 3;
    tap(element, x, 140);
    expect(selected).toHaveBeenCalledOnce();
    const value = selected.mock.calls[0][0];
    expect(value.time).toBe(1060);
    expect(value.price).toBeCloseTo(chart.coordinateToPrice(140, 0)!, 9);
    expect(events).toEqual([
      { event: 'pick:start', payload: { kind: 'point' } },
      { event: 'pick:end', payload: { kind: 'point', value } },
    ]);
    expect(handle.active()).toBe(false);
  });

  it('reads the price on a requested scale and ignores a click on another pane', () => {
    const { chart, element, other } = fixture(), selected = vi.fn<(value: PickPoint) => void>();
    chart.beginPick('point', selected, { paneIndex: 1, priceScaleId: 'overlay:point' });
    tap(element, 250, 140);
    expect(selected).not.toHaveBeenCalled();
    const top = chart.plotRect(1)!.top;
    tap(element, chart.timeToCoordinate(1120)!, top + 60);
    expect(selected).toHaveBeenCalledExactlyOnceWith({ time: 1120, price: other.priceScale().yToPrice(60) });
  });

  it('delivers nothing when cancelled, and a time-only or price-only pick still answers a number', () => {
    const { chart, element } = fixture(), selected = vi.fn();
    const ends: unknown[] = [];
    chart.on('pick:end', payload => ends.push(payload));
    const handle = chart.beginPick('point', selected);
    handle();
    tap(element, 250, 140);
    expect(selected).not.toHaveBeenCalled();
    expect(ends).toEqual([{ kind: 'point', value: null }]);
    const scalar = vi.fn();
    chart.beginPick('time', scalar);
    tap(element, chart.timeToCoordinate(1120)!, 140);
    expect(scalar).toHaveBeenCalledExactlyOnceWith(1120);
  });

  it('refuses a point pick during drawing placement, and answers one with a point once placement ends', () => {
    const { chart, element } = fixture();
    chart.setPlacementMode(true);
    expect(() => chart.beginPick('point', vi.fn())).toThrow(/placement/);
    chart.setPlacementMode(false);
    const selected = vi.fn<(value: PickPoint) => void>();
    chart.beginPick('point', selected);
    tap(element, chart.timeToCoordinate(1060)!, 140);
    expect(selected).toHaveBeenCalledOnce();
    expect(selected.mock.calls[0][0]).toMatchObject({ time: 1060 });
  });
});
