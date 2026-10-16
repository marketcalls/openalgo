import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

function mount() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 500);
  chart.addSeries('candlestick').setData([
    { time: 100, open: 10, high: 12, low: 9, close: 11, volume: 100 },
    { time: 200, open: 11, high: 13, low: 10, close: 12, volume: 200 },
  ]);
  return chart;
}

describe('chart-owned timeline events', () => {
  it('follows its pane when moved and returns to the price pane when removed', () => {
    const chart = mount();
    chart.addSeries('line', { paneIndex: 1 });
    chart.addSeries('line', { paneIndex: 2 });
    chart.setEvents([{ id: 'earn', time: 100, type: 'earnings', label: 'E' }], 2);
    const clicked: unknown[] = [];
    chart.on('event:click', details => clicked.push(details));
    const click = (paneIndex: number) => chart.emit('click', { id: 'earn', paneIndex, point: { x: 10, y: 10 } });
    click(2);
    expect(clicked).toHaveLength(1);
    chart.movePane(2, -1);
    click(1);
    expect(clicked).toHaveLength(2);
    chart.removePane(1);
    expect(chart.panes()[0].primitives()).toContain(chart.eventMarkers());
    click(0);
    expect(clicked).toHaveLength(3);
    chart.destroy();
  });
  it('exposes group and clustering controls without replacing the event strip', () => {
    const chart = mount();
    expect(typeof chart.setEventMarkerOptions).toBe('function');
    chart.setEventMarkerOptions({ clustering: true });
    chart.setEventGroups([{ id: 'company', label: 'Company' }]);
    chart.setEvents([{ id: 'earn', time: 100, type: 'earnings', label: 'E', group: 'company' }]);
    const markers = chart.eventMarkers();
    expect(markers?.options().clustering).toBe(true);
    chart.setEventGroupVisible('company', false);
    expect(markers?.isGroupVisible('company')).toBe(false);
    chart.setEvents([]);
    expect(chart.eventMarkers()).toBe(markers);
    chart.destroy();
  });

  it('clears the previous instrument calendar but retains it across interval changes', () => {
    const chart = mount();
    chart.setDataContext({ symbol: 'ONE', exchange: 'EX', interval: '1m' });
    chart.setEvents([{ id: 'earn', time: 100, type: 'earnings', label: 'E' }]);
    chart.setDataContext({ symbol: 'ONE', exchange: 'EX', interval: '5m' });
    expect(typeof chart.eventMarkers).toBe('function');
    expect(chart.eventMarkers()?.events()).toHaveLength(1);
    chart.setDataContext({ symbol: 'TWO', exchange: 'EX', interval: '5m' });
    expect(chart.eventMarkers()?.events()).toEqual([]);
    chart.destroy();
  });
});
