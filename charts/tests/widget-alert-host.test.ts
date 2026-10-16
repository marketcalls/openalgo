import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { AlertController, createChart, lightTheme } from '../src/index';
import { DrawingController } from '../src/draw/index';
import * as widget from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const cleanup: (() => void)[] = [];
afterEach(() => { for (const dispose of cleanup.splice(0).reverse()) dispose(); });

function host() {
  const doc = fakeWidgetDocument();
  const container = fakeContainer(doc) as unknown as HTMLElement;
  const chart = createChart(container, { document: doc as unknown as Document, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  cleanup.push(() => chart.destroy());
  const series = chart.addSeries('candlestick');
  series.setData([940, 1000].map(time => ({ time, open: 100, high: 100, low: 100, close: 100 })));
  chart.applySize(800, 600);
  chart.fitContent();
  chart.setDataContext({ symbol: 'HOST', exchange: 'SIM', interval: '1m' });
  const draw = new DrawingController(chart);
  cleanup.push(() => draw.destroy());
  const alerts = new AlertController(chart, { drawings: draw });
  cleanup.push(() => alerts.destroy());
  const onOpenChange = vi.fn();
  expect(widget.createAlertUi).toBeTypeOf('function');
  const ui = widget.createAlertUi(container, { chart, draw, alerts, onOpenChange });
  cleanup.push(() => ui.destroy());
  return { chart, series, draw, alerts, ui, onOpenChange, root: ui.root as unknown as FakeElement };
}

describe('alert dialogs in a custom host', () => {
  it('uses the host controller, tracks nested dialogs, and keeps one list', () => {
    const { ui, root, alerts, onOpenChange } = host();
    expect(ui.isOpen()).toBe(false);
    expect(ui.openList()).toBe(true);
    ui.openList();
    expect(root.querySelectorAll('.oac-alerts')).toHaveLength(1);
    fire(root.querySelector('[data-action="create-alert"]')!, 'click');
    expect(root.querySelector('.oac-alert-editor')).not.toBeNull();
    fire(root.querySelector('[data-action="save-alert"]')!, 'click');
    expect(alerts.list()).toMatchObject([{ source: { kind: 'price', price: 100 }, policy: 'onBarClose' }]);
    expect(ui.isOpen()).toBe(true);
    expect(onOpenChange.mock.calls).toEqual([[true]]);
    ui.close();
    expect(ui.isOpen()).toBe(false);
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it('seeds a drawing editor and destroys only its own UI', () => {
    const { ui, root, draw, alerts, series, chart } = host();
    const drawing = draw.add({ tool: 'horizontal-line', paneIndex: 0, points: [{ time: 1000, price: 105 }], style: {} });
    ui.openEditor({ source: { kind: 'drawing', drawingId: drawing.id } });
    fire(root.querySelector('[data-action="save-alert"]')!, 'click');
    expect(alerts.list()[0].source).toMatchObject({ kind: 'drawing', drawingId: drawing.id });
    ui.setTheme('light', lightTheme);
    expect(root.dataset.theme).toBe('light');
    ui.openList();
    ui.destroy();
    expect(root.parentElement).toBeNull();
    expect(ui.openList()).toBe(false);
    expect(ui.openEditor()).toBe(false);
    series.update({ time: 1000, open: 100, high: 110, low: 100, close: 110 });
    series.update({ time: 1060, open: 110, high: 110, low: 110, close: 110 });
    expect(alerts.list()[0].state).toBe('triggered');
    expect(chart.primaryBars()).toHaveLength(3);
    expect(draw.get(drawing.id)).toBeTruthy();
  });

  it('releases open UI when the chart is destroyed and isolates other hosts', () => {
    const first = host();
    const second = host();
    first.ui.openList(); second.ui.openList();
    first.chart.destroy();
    expect(first.ui.isOpen()).toBe(false);
    expect(first.root.parentElement).toBeNull();
    expect(first.onOpenChange.mock.calls).toEqual([[true], [false]]);
    expect(second.ui.isOpen()).toBe(true);
    second.ui.close();
  });
});
