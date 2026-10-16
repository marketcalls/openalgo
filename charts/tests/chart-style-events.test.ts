import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { applyChartSettings } from '../src/model/chart-settings';
import { fakeDocument } from './helpers/fake-dom';

describe('chart appearance change notifications', () => {
  it('emits the applied visual patch once and excludes unrelated settings', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), {
      document, pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 500);
    chart.addSeries('candlestick');
    const changes: unknown[] = [];
    chart.on('style:change', patch => changes.push(patch));
    applyChartSettings(chart, {
      'symbol.upColor': '#123456', 'canvas.grid.vertColor': '#abcdef',
      'time.timezone': 'UTC', 'trading.oneClick': true, 'unknown.setting': true,
    });
    expect(changes).toEqual([{
      'symbol.upColor': '#123456', 'canvas.grid.vertColor': '#abcdef',
    }]);
    applyChartSettings(chart, { 'time.timezone': 'Asia/Kolkata' });
    expect(changes).toHaveLength(1);
    chart.destroy();
  });
});
