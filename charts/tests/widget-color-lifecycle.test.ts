import { afterEach, expect, it, vi } from 'vitest';
import { createOverlayStack } from '../src/widget/context';
import { renderForm } from '../src/widget/form';
import { createColorPicker } from '../src/widget/color-picker';
import { fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(off => off()); vi.restoreAllMocks(); });
const domNode = (value: HTMLElement): FakeElement => value as unknown as FakeElement;
function setup() {
  const document = fakeWidgetDocument(); const root = fakeContainer(document); root.classList.add('oac-widget');
  const stack = createOverlayStack(root as unknown as HTMLElement, document as unknown as Document);
  cleanups.push(() => stack.destroy());
  const parent = document.createElement('div'); parent.classList.add('scrolling-settings');
  const closeParent = stack.open(parent as unknown as HTMLElement, { modal: true, placement: 'center' });
  const form = renderForm(parent as unknown as HTMLElement, [{ key: 'color', kind: 'color', label: 'Line color' }], {
    values: { color: '#12345680' }, idPrefix: 'lifecycle', onChange: () => {}, openOverlay: stack.open,
  });
  const trigger = parent.querySelector('.oac-color__trigger')!;
  return { document, root, stack, parent, closeParent, form, trigger };
}
it('mounts the picker outside scrolling form ancestors and closes only the picker on Escape', () => {
  const r = setup(); fire(r.trigger, 'click');
  expect(r.stack.size()).toBe(2);
  const popup = r.stack.top()!;
  expect(popup.classList.contains('oac-color__popover')).toBe(true);
  expect(r.parent.contains(domNode(popup))).toBe(false);
  fireKey(r.document.activeElement, 'Escape');
  expect(r.stack.size()).toBe(1); expect(r.stack.top()).toBe(r.parent);
  expect(r.trigger.getAttribute('aria-expanded')).toBe('false');
  expect(r.document.activeElement).toBe(r.trigger);
});
it('disposes an open picker when a generated form is replaced or destroyed', () => {
  const r = setup(); fire(r.trigger, 'click');
  expect(typeof r.form.destroy).toBe('function');
  r.form.destroy();
  expect(r.stack.size()).toBe(1);
  expect(r.root.querySelectorAll('.oac-color__popover').every(p => p.hidden)).toBe(true);
  fire(r.trigger, 'click'); expect(r.stack.size()).toBe(1);
  r.closeParent(); expect(r.stack.size()).toBe(0);
});
it('re-rendering the same form host disposes its previous open popup', () => {
  const r = setup(); fire(r.trigger, 'click');
  const next = renderForm(r.parent as unknown as HTMLElement, [{ key: 'color', kind: 'color', label: 'Line color' }], {
    values: { color: '#ffffff' }, idPrefix: 'next', onChange: () => {}, openOverlay: r.stack.open,
  });
  expect(r.stack.size()).toBe(1);
  next.destroy();
});
it('removes the standalone outside listener and blocks stale controls after destroy', () => {
  const document = fakeWidgetDocument(); const root = fakeContainer(document);
  const add = vi.spyOn(document, 'addEventListener'); const remove = vi.spyOn(document, 'removeEventListener');
  const changes: string[] = [];
  const picker = createColorPicker(document as unknown as Document, { id: 'standalone', label: 'Color', value: '#123456', onChange: value => changes.push(value) });
  root.appendChild(domNode(picker.el)); fire(domNode(picker.trigger), 'click');
  const outside = add.mock.calls.find(call => call[0] === 'pointerdown')!;
  expect(outside).toBeDefined(); picker.destroy();
  expect(remove.mock.calls.some(call => call[0] === 'pointerdown' && call[1] === outside[1])).toBe(true);
  fire(domNode(picker.trigger), 'click');
  expect(picker.trigger.getAttribute('aria-expanded')).toBe('false');
  picker.input.value = '#ffffff'; fire(domNode(picker.input), 'change');
  expect(changes).toEqual([]);
});
