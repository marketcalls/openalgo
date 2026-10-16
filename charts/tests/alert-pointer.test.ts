import { expect, it, vi } from 'vitest';
import { AlertController, Chart } from '../src/index';
import { fakeDocument, pointer } from './helpers/fake-dom';

it.each(['drag', 'history', 'objects'] as const)('keeps the alert under the pointer available after %s', change => {
  vi.stubGlobal('window', { devicePixelRatio: 1, addEventListener() {}, removeEventListener() {} });
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as HTMLElement & { dispatch(name: string, event: unknown): void };
  const chart = new Chart(el, { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  try {
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    series.setData([60, 120, 180].map(time => ({ time, open: 100, high: 120, low: 90, close: 100 })));
    const alerts = new AlertController(chart);
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    chart.exportSVG();
    const y = chart.priceToCoordinate(105)!;
    const targetY = chart.priceToCoordinate(110)!;
    el.dispatch('pointermove', pointer('move', 400, y, { buttons: 0 }));
    expect(alerts.hovered()).toBe(alert.id);
    if (change === 'drag') {
      el.dispatch('pointerdown', pointer('down', 400, y));
      el.dispatch('pointermove', pointer('move', 400, targetY));
      el.dispatch('pointerup', pointer('up', 400, targetY));
      expect(alerts.list()[0].source).toMatchObject({ price: 110 });
    } else if (change === 'history') series.setData(series.getData());
    else chart.emit('objects:change', {});
    el.dispatch('pointermove', pointer('move', 401, change === 'drag' ? targetY : y, { buttons: 0 }));
    expect(alerts.hovered()).toBe(alert.id);
  } finally { chart.destroy(); vi.unstubAllGlobals(); }
});

