import { afterEach, expect, it } from 'vitest';
import { createWidget, type Widget } from '../src/widget/widget';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal, type FakeElement } from './helpers/fake-dom-widget';

const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });
function make() {
  ensureWindowGlobal();
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, { document: doc as unknown as Document,
    symbol: 'TEST', exchange: 'NSE', shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  widgets.push(widget);
  (widget.root as unknown as FakeElement).rect = { left: 0, top: 0, width: 1000, height: 600 };
  return widget;
}
it('opens readings in the widget dock and preserves optional panel state through restore', () => {
  const first = make();
  expect(first.openDataWindow()).toBe(true);
  expect(first.getState().panels?.panel).toBe('data');
  const second = make(); second.restoreState(first.getState());
  expect(second.getState().panels?.panel).toBe('data');
  expect(second.root.querySelector('.oac-data-window')).not.toBeNull();
  second.openObjects();
  expect(second.getState().panels?.panel).toBe('objects');
  expect(second.root.querySelector('.oac-data-window')).toBeNull();
  expect(first.getState().panels?.panel).toBe('data');
  first.destroy(); expect(first.openDataWindow()).toBe(false);
});
it('accepts old widget state without panels and does not open anything by default', () => {
  const widget = make();
  expect(widget.getState().panels?.panel).toBeNull();
  const old = widget.getState(); delete old.panels;
  expect(widget.restoreState(old).applied).toBe(true);
  expect(widget.getState().panels?.panel).toBeNull();
});
