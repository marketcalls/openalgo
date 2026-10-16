import { describe, expect, it, vi } from 'vitest';
import { dialogFrame, openPanel, tabList } from '../src/widget/form';
import { createOverlayStack } from '../src/widget/context';
import { asDoc, asEl, FakeEvent, installDom } from './widget-form.test';

describe('compact panel tab navigation', () => {
  it('follows the host width, updates arrow keys after resize and releases observation on dismissal', () => {
    const dom = installDom({ width: 350, height: 240 });
    dom.win.innerWidth = 1440;
    let resized!: () => void;
    const disconnect = vi.fn();
    Object.assign(dom.win, { ResizeObserver: class {
      constructor(callback: () => void) { resized = callback; }
      observe() {}
      disconnect = disconnect;
    } });
    const doc = asDoc(dom.doc);
    const stack = createOverlayStack(asEl(dom.root), doc);
    const frame = dialogFrame(doc, { title: 'Compact settings', onClose() {} });
    const picked: string[] = [];
    const tabs = tabList(doc, [{ id: 'a', label: 'First' }, { id: 'b', label: 'Second' }], 'a', 'rail', id => picked.push(id));
    frame.body.appendChild(tabs.el);
    const panel = openPanel({ openOverlay: stack.open }, frame.el, { placement: 'center' }, () => {});
    expect(tabs.el.getAttribute('aria-orientation')).toBe('horizontal');
    const buttons = dom.root.querySelectorAll('.oac-tab');
    buttons[0].dispatchEvent(new FakeEvent('keydown', { key: 'ArrowRight' }));
    expect(picked).toEqual(['b']);
    dom.root.rect = { width: 1000, height: 500 };
    resized();
    expect(tabs.el.getAttribute('aria-orientation')).toBe('vertical');
    buttons[1].dispatchEvent(new FakeEvent('keydown', { key: 'ArrowUp' }));
    expect(picked).toEqual(['b', 'a']);
    stack.closeTop();
    expect(panel.isOpen()).toBe(false);
    expect(disconnect).toHaveBeenCalledOnce();
    stack.destroy();
  });
});
