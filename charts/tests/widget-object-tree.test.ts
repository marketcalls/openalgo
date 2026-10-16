import { afterEach, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { DrawingController } from '../src/draw/index';
import * as panels from '../src/widget/objects-panel';
import type { WidgetContext } from '../src/widget/context';
import { fakeDocument } from './helpers/fake-dom';
import { fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';
const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(off => off()));
function rig() {
  const engineDoc = fakeDocument();
  const chart = new Chart(engineDoc.createElement('div'), { document: engineDoc, pixelRatio: () => 1, raf: { schedule: () => 0 } });
  const draw = new DrawingController(chart);
  const objects = new ChartObjects(chart, { drawings: draw });
  const document = fakeWidgetDocument();
  const ctx = { document, chart, objects, toast: () => {} } as unknown as WidgetContext;
  cleanup.push(() => chart.destroy(), () => draw.destroy(), () => objects.destroy());
  return { chart, draw, objects, ctx };
}
it('embeds pane sections and executes real movement and ordering through accessible controls', () => {
  const r = rig();
  const first = r.chart.addIndicator('sma');
  const second = r.chart.addIndicator('ema');
  expect(typeof panels.createObjectsPanelContent).toBe('function');
  const content = panels.createObjectsPanelContent(r.ctx);
  cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  expect(root.querySelector('[data-pane-index="0"]')).not.toBeNull();
  const row = root.querySelector(`[data-object-id="indicator:${second.id}"]`)!;
  fire(row.querySelector('[data-action="earlier"]')!, 'click');
  expect(r.chart.indicators()).toEqual([second, first]);
  const move = row.querySelector('select')!;
  move.value = '1';
  fire(move, 'change');
  expect(second.paneIndex).toBe(1);
  expect(root.querySelector('[data-pane-index="1"]')).not.toBeNull();
  content.destroy();
  const saved = root.textContent;
  r.chart.addIndicator('rsi');
  expect(root.textContent).toBe(saved);
});
it('creates a named group from selected drawings and shows its member rows', () => {
  const r = rig();
  const one = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }], style: {} });
  const two = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 2, price: 3 }], style: {} });
  r.draw.select([one.id, two.id]);
  expect(typeof panels.createObjectsPanelContent).toBe('function');
  const content = panels.createObjectsPanelContent(r.ctx);
  cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  const name = root.querySelector('[data-action="group-name"]')!;
  name.value = 'Entry levels';
  fire(name, 'input');
  fire(root.querySelector('[data-action="group"]')!, 'click');
  expect(r.draw.groups()[0].name).toBe('Entry levels');
  const group = root.querySelector(`[data-object-id="group:${r.draw.groups()[0].id}"]`)!;
  expect(group.textContent).toContain('Entry levels');
  expect(group.querySelector(`[data-object-id="drawing:${one.id}"]`)).not.toBeNull();
  expect(root.querySelector(`[data-object-id="drawing:${one.id}"]`)!.dataset.groupId).toBe('group:' + r.draw.groups()[0].id);
  fire(group.querySelector('[data-action="visibility"]')!, 'click');
  expect(r.draw.drawings().every(d => d.visible === false)).toBe(true);
});

it('does not execute movement controls after the embeddable tree is destroyed', () => {
  const r = rig();
  const first = r.chart.addIndicator('sma'); const second = r.chart.addIndicator('ema');
  const content = panels.createObjectsPanelContent(r.ctx);
  const root = content.element as unknown as FakeElement;
  const row = root.querySelector(`[data-object-id="indicator:${second.id}"]`)!;
  content.destroy();
  fire(row.querySelector('[data-action="earlier"]')!, 'click');
  expect(r.chart.indicators()).toEqual([first, second]);
});

it('lets touch and keyboard users select several drawings without modifier keys', () => {
  const r = rig();
  const one = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }], style: {} });
  const two = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 2, price: 3 }], style: {} });
  const content = panels.createObjectsPanelContent(r.ctx); cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  for (const id of [one.id, two.id]) {
    const control = root.querySelector(`[data-object-id="drawing:${id}"] [data-action="add-selection"]`);
    expect(control).not.toBeNull(); fire(control!, 'click');
  }
  expect(r.draw.selection()).toEqual([one.id, two.id]);
});

it('executes same-pane drag ordering and cross-pane drops through the model', () => {
  const r = rig(); const first = r.chart.addIndicator('sma'); const second = r.chart.addIndicator('ema');
  const target = r.chart.addIndicator('rsi');
  const content = panels.createObjectsPanelContent(r.ctx); cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  const secondRow = root.querySelector(`[data-object-id="indicator:${second.id}"]`)!;
  fire(secondRow, 'dragstart');
  fire(root.querySelector(`[data-object-id="indicator:${first.id}"]`)!, 'drop');
  expect(r.chart.indicators()).toEqual([second, first, target]);
  fire(secondRow, 'dragstart');
  fire(root.querySelector('[data-pane-index="1"]')!, 'drop');
  expect(second.paneIndex).toBe(target.paneIndex);
});

it('names the add-to-selection button for its action and gives it no pressed state', () => {
  const r = rig();
  const one = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }], style: {} });
  const content = panels.createObjectsPanelContent(r.ctx); cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  const control = root.querySelector(`[data-object-id="drawing:${one.id}"] [data-action="add-selection"]`)!;
  fire(control, 'click');
  expect(r.draw.selection()).toEqual([one.id]);
  expect(control.getAttribute('aria-label')).toMatch(/^Remove .* from selection$/);
  expect(control.getAttribute('aria-pressed')).toBeNull();
});

it('tells rows of one name apart and counts one object in the singular', () => {
  const r = rig();
  const one = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }], style: {} });
  const content = panels.createObjectsPanelContent(r.ctx); cleanup.push(() => content.destroy());
  const root = content.element as unknown as FakeElement;
  expect(root.querySelector('.oac-objects__count')!.textContent).toBe('1 object');
  const two = r.draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: 2, price: 3 }], style: {} });
  const label = (id: string): string | null => root.querySelector(`[data-object-id="drawing:${id}"] [data-action="remove"]`)!.getAttribute('aria-label');
  expect(label(one.id)).not.toBe(label(two.id));
  expect(root.querySelector('.oac-objects__count')!.textContent).toBe('2 objects');
});
