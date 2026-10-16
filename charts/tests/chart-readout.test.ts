import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { createLinkGroup } from '../src/link/group';
import { registerIndicator } from '../src/model/indicator-registry';
import type { IndicatorApi } from '../src/model/indicator-instance';
import type { LegendValue } from '../src/primitives/pane-legend';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

registerIndicator({
  id: 'readout-close', name: 'Readout close', category: 'Test', placement: 'onchart',
  inputs: [], plots: [{ key: 'value', title: 'Value', type: 'line' }],
  calc: bars => ({ value: bars.map(bar => bar.close) }),
});
const bar = (time: number, close: number) => ({ time, open: close, high: close + 1, low: close - 1, close });
const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });
function mount(step = 60) {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const el = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document, shortcuts: false, timeNavigator: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  const bars = Array.from({ length: 30 }, (_, i) => bar(6000 + i * step, 100 + i));
  series.setData(bars);
  const indicator = chart.addIndicator('readout-close');
  const move = (index: number) => el.dispatch('pointermove', pointer('move', chart.timeScale.indexToX(index), 200));
  return { chart, el, series, bars, indicator, move };
}
function text(indicator: IndicatorApi): string {
  indicator.values(); // Flush pending calculations as a real host read does.
  return (indicator.legend() as unknown as { _values: LegendValue[] })._values[0]?.text;
}
function expected(chart: Chart, price: number): string { return chart.panes()[0].priceScale.format(price); }

describe('selected candle study readouts', () => {
  it('gives physical hover priority and initializes a newly added study at that candle', () => {
    const { chart, el, indicator, move } = mount();
    move(10);
    chart.setLinkedCrosshairIndex(2);
    expect(text(indicator)).toBe(expected(chart, 110));
    expect(text(chart.addIndicator('readout-close'))).toBe(expected(chart, 110));
    el.dispatch('pointerleave', pointer('move', -1, -1));
    expect(text(indicator)).toBe(expected(chart, 129));
    chart.destroy();
    expect(() => chart.setLinkedCrosshairIndex(2)).not.toThrow();
  });
  it('keeps a hovered historical time through live replacement and prepended history', () => {
    const { chart, series, bars, indicator, move } = mount();
    move(10);
    expect(text(indicator)).toBe(expected(chart, 110));
    series.update(bar(bars[bars.length - 1].time, 150));
    expect(text(indicator)).toBe(expected(chart, 110));
    series.setData([bar(5940, 99), ...bars]);
    expect(text(indicator)).toBe(expected(chart, 110));
  });
  it('updates the selected forming candle and falls back to latest in future space or on leave', () => {
    const { chart, el, series, bars, indicator, move } = mount();
    move(29);
    series.update(bar(bars[bars.length - 1].time, 150));
    expect(text(indicator)).toBe(expected(chart, 150));
    move(31);
    series.update(bar(7800, 160));
    expect(text(indicator)).toBe(expected(chart, 160));
    move(10);
    el.dispatch('pointerleave', pointer('move', -1, -1));
    expect(text(indicator)).toBe(expected(chart, 160));
  });
  it('updates linked OHLC and study readouts at the mapped follower time without rebroadcasting', () => {
    const leader = mount();
    const follower = mount(300);
    const group = createLinkGroup({ viewport: false });
    group.add(leader.chart); group.add(follower.chart);
    const callback = vi.fn();
    const rebroadcast = vi.fn();
    follower.chart.subscribeCrosshairMove(callback);
    follower.chart.on('crosshair:move', rebroadcast);
    leader.move(12);
    expect(group.crosshairIndex(follower.chart)).toBe(2);
    expect(callback).toHaveBeenLastCalledWith(expect.objectContaining({ time: 6600, bar: follower.bars[2] }));
    expect(text(follower.indicator)).toBe(expected(follower.chart, 102));
    follower.series.update(bar(follower.bars[follower.bars.length - 1].time, 150));
    expect(text(follower.indicator)).toBe(expected(follower.chart, 102));
    expect(rebroadcast).not.toHaveBeenCalled();
    group.setOptions({ crosshair: false });
    expect(callback).toHaveBeenLastCalledWith(expect.objectContaining({ time: null, bar: null }));
    expect(text(follower.indicator)).toBe(expected(follower.chart, 150));
    group.destroy();
  });
  it('clears linked readouts on missing time and member removal', () => {
    const leader = mount();
    const follower = mount(300);
    const group = createLinkGroup({ viewport: false, whenMissing: 'hide' });
    group.add(leader.chart); group.add(follower.chart);
    leader.move(10);
    expect(text(follower.indicator)).toBe(expected(follower.chart, 102));
    leader.move(11);
    expect(text(follower.indicator)).toBe(expected(follower.chart, 129));
    leader.move(10);
    group.remove(follower.chart);
    expect(text(follower.indicator)).toBe(expected(follower.chart, 129));
    group.destroy();
  });
});
