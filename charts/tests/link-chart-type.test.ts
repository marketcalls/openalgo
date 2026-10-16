/**
 * The chart type channel: the chart style a linked chart shows (candles, bars,
 * a line) follows the leader's, independently of the interval and the
 * appearance channels. The host owns applying it, as it owns the interval.
 */
import { describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import {
  applyChartSettings, createLinkGroup, readChartSettings, registeredChartTypes, type LinkChart, type SeriesApi, type SeriesType,
} from '../src/index';
import { DataLayer } from '../src/model/data-layer';
import type { IPrimitive } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

class MemberChart implements LinkChart {
  readonly dataLayer = new DataLayer();
  readonly listeners = new Map<string, Set<(payload: unknown) => void>>();
  isDestroyed = false;
  on(event: string, cb: (payload: unknown) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(cb);
    return () => { this.listeners.get(event)?.delete(cb); };
  }
  emit(event: string, payload: unknown) {
    for (const cb of [...(this.listeners.get(event) ?? [])]) cb(payload);
  }
  panes() { return this.isDestroyed ? [] : [{}]; }
  getVisibleLogicalRange() { return { from: 0, to: 10 }; }
  setVisibleLogicalRange() {}
  addPrimitive(_primitive: IPrimitive) {}
  removePrimitive(_primitive: IPrimitive) {}
}

describe('chart type linking', () => {
  it('is off by default and remembers the latest chart type before it is switched on', () => {
    const group = createLinkGroup();
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { chartType: 'candlestick' });
    group.add(b, { chartType: 'line', onChartType: follow });
    expect(group.options().chartType).toBe(false);
    group.setChartType(a, 'bar');
    expect(follow).not.toHaveBeenCalled();
    expect(group.chartType()).toBe('bar');
    group.setOptions({ chartType: true });
    expect(follow).toHaveBeenCalledExactlyOnceWith('bar', b);
  });

  it('follows events and reports without calling the leader back', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart();
    const first = vi.fn(); const second = vi.fn();
    group.add(a, { chartType: 'candlestick', onChartType: first });
    group.add(b, { chartType: 'candlestick', onChartType: second });
    a.emit('chartType', { chartType: 'hollow-candle' });
    expect(second).toHaveBeenLastCalledWith('hollow-candle', b);
    expect(first).not.toHaveBeenCalled();
    b.emit('chartType', 'area');
    expect(first).toHaveBeenLastCalledWith('area', a);
    group.setChartType(a, 'area');
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('is independent of the interval channel in both directions', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart();
    const interval = vi.fn(); const chartType = vi.fn();
    group.add(a, { interval: '1m', chartType: 'candlestick' });
    group.add(b, { interval: '1m', chartType: 'candlestick', onInterval: interval, onChartType: chartType });
    group.setInterval(a, '15m');
    expect(interval).not.toHaveBeenCalled();
    group.setChartType(a, 'line');
    expect(chartType).toHaveBeenCalledExactlyOnceWith('line', b);
    group.setOptions({ chartType: false, interval: true });
    expect(interval).toHaveBeenCalledExactlyOnceWith('15m', b);
    group.setChartType(a, 'bar');
    expect(chartType).toHaveBeenCalledTimes(1);
    expect(group.interval()).toBe('15m');
    expect(group.chartType()).toBe('bar');
  });

  it('brings a late member in line and releases every listener when destroyed', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { chartType: 'step' });
    group.add(b, { chartType: 'candlestick', onChartType: follow });
    expect(follow).toHaveBeenCalledExactlyOnceWith('step', b);
    group.destroy();
    expect(group.chartType()).toBeNull();
    expect([...a.listeners.values()].every(list => list.size === 0)).toBe(true);
    expect([...b.listeners.values()].every(list => list.size === 0)).toBe(true);
    a.emit('chartType', 'bar');
    expect(follow).toHaveBeenCalledTimes(1);
  });

  it('does not let a follower echo replace the chart type the leader chose', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    const follow = vi.fn();
    group.add(a, { chartType: 'candlestick' });
    group.add(b, { chartType: 'candlestick', onChartType: () => b.emit('chartType', 'bar') });
    group.add(c, { chartType: 'candlestick', onChartType: follow });
    group.setChartType(a, 'line');
    expect(follow).toHaveBeenCalledExactlyOnceWith('line', c);
    expect(group.chartType()).toBe('line');
  });

  it('lets a host refuse a chart type it cannot show, and asks again next time', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn().mockReturnValueOnce(false).mockReturnValue(true);
    group.add(a, { chartType: 'candlestick' });
    group.add(b, { chartType: 'candlestick', onChartType: follow });
    group.setChartType(a, 'volume-candle');
    group.setChartType(a, 'volume-candle');
    expect(follow).toHaveBeenCalledTimes(2);
    group.setChartType(a, 'volume-candle');
    expect(follow).toHaveBeenCalledTimes(2);
  });

  it('ignores malformed events, reports from charts outside the group and updates in place', () => {
    const group = createLinkGroup({ chartType: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { chartType: 'candlestick' });
    group.add(b, { chartType: 'candlestick' });
    for (const invalid of [null, undefined, '', '  ', 5, {}, { chartType: 5 }]) a.emit('chartType', invalid);
    group.setChartType(new MemberChart(), 'line');
    expect(group.chartType()).toBe('candlestick');
    group.add(b, { onChartType: follow });
    expect(b.listeners.get('chartType')?.size).toBe(1);
    a.emit('chartType', 'baseline');
    expect(follow).toHaveBeenCalledExactlyOnceWith('baseline', b);
  });
});

describe('chart type linking on real charts', () => {
  /** A seeded random walk in the price range of a large-cap stock. */
  function walk(seed: number, count: number, start: number): Bar[] {
    let s = seed, close = start;
    const rand = (): number => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
    return Array.from({ length: count }, (_, i) => {
      const open = close;
      close = Math.round(open * (1 + (rand() - 0.5) * 0.012) * 100) / 100;
      return { time: 1758771900 + i * 300, open, close,
        high: Math.round(Math.max(open, close) * (1 + rand() * 0.004) * 100) / 100,
        low: Math.round(Math.min(open, close) * (1 - rand() * 0.004) * 100) / 100 };
    });
  }
  function loaded(seed: number): { chart: Chart; series: SeriesApi } {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    series.setData(walk(seed, 150, 1500 + seed));
    return { chart, series };
  }

  it('changes the follower series type and never moves a colour through the chart type channel', () => {
    const a = loaded(3); const b = loaded(5);
    const group = createLinkGroup({ chartType: true });
    try {
      for (const member of [a, b]) {
        group.add(member.chart, {
          chartType: member.chart.seriesType(member.series) ?? undefined,
          // The host checks the registry, as the widget does, and refuses a type it cannot draw.
          onChartType: type => registeredChartTypes().includes(type)
            && member.chart.setSeriesType(member.series, type as SeriesType),
        });
      }
      applyChartSettings(b.chart, { 'symbol.upColor': '#1b8f5a' });
      const colour = readChartSettings(b.chart)['symbol.upColor'];
      expect(a.chart.setSeriesType(a.series, 'bar')).toBe(true);
      group.setChartType(a.chart, 'bar');
      expect(b.chart.seriesType(b.series)).toBe('bar');
      expect(readChartSettings(b.chart)['symbol.upColor']).toBe(colour);
      expect(readChartSettings(a.chart)['symbol.upColor']).not.toBe(colour);
      // A registered type the follower refuses leaves it where it was.
      group.setChartType(a.chart, 'not-a-chart-type');
      expect(b.chart.seriesType(b.series)).toBe('bar');
    } finally {
      group.destroy();
      a.chart.destroy(); b.chart.destroy();
    }
  });
});
