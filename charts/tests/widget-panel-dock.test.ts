import { describe, expect, it, vi } from 'vitest';
import { mountPanelDock, sanitizePanelDockState } from '../src/widget/panel-dock';
import { createOverlayStack, type WidgetContext } from '../src/widget/context';
import { fakeWidgetDocument, fakeContainer, fireKey, type FakeElement } from './helpers/fake-dom-widget';

function rig(width = 1000) {
  const doc = fakeWidgetDocument(), root = fakeContainer(doc, width);
  const stage = doc.createElement('div'); root.appendChild(stage);
  const stack = createOverlayStack(root as unknown as HTMLElement, doc as unknown as Document);
  const ctx = { document: doc, root, overlays: stack, openOverlay: stack.open } as unknown as WidgetContext;
  const destroyed: string[] = [], mounted: string[] = [];
  const create = (name: string) => (host: HTMLElement) => { host.textContent = `${name} content`; mounted.push(name); return { destroy: () => { destroyed.push(name); } }; };
  const change = vi.fn();
  const dock = mountPanelDock(ctx, stage as unknown as HTMLElement, { data: create('data'), objects: create('objects'), onChange: change });
  return { doc, root, stage, stack, dock, destroyed, mounted, change };
}
describe('information dock', () => {
  it('keeps legacy/malformed states closed and clamps only valid width values', () => {
    expect(sanitizePanelDockState(undefined)).toEqual({ panel: null, width: 300 });
    expect(sanitizePanelDockState({ panel: 'orders', width: NaN })).toEqual({ panel: null, width: 300 });
    expect(sanitizePanelDockState({ panel: 'data', width: 99999 })).toEqual({ panel: 'data', width: 480 });
    expect(sanitizePanelDockState({ panel: 'objects', width: -10 })).toEqual({ panel: 'objects', width: 240 });
  });
  it('mounts only the active content, disposes on switch and close, and survives repeated teardown', () => {
    const r = rig(); expect(r.mounted).toEqual([]);
    r.dock.open('data'); expect(r.mounted).toEqual(['data']);
    expect(r.stack.size()).toBe(0);
    expect(r.dock.state().panel).toBe('data');
    r.dock.open('objects'); expect(r.destroyed).toEqual(['data']);
    r.dock.close(); expect(r.destroyed).toEqual(['data', 'objects']);
    expect(r.dock.state().panel).toBeNull();
    r.dock.destroy(); r.dock.destroy(); r.stack.destroy();
  });
  it('offers keyboard resizing and restores a bounded saved width', () => {
    const r = rig(); r.dock.open('data');
    const grip = (r.dock.el as unknown as FakeElement).querySelector('[role="separator"]')!;
    fireKey(grip, 'ArrowLeft'); expect(r.dock.state().width).toBe(310);
    r.dock.restore({ panel: 'objects', width: 370 });
    expect(r.dock.state()).toEqual({ panel: 'objects', width: 370 });
    expect(grip.getAttribute('aria-valuenow')).toBe('370');
    r.dock.destroy(); r.stack.destroy();
  });
  it('uses the shared overlay focus and Escape handling on narrow displays', () => {
    const r = rig(390), opener = r.doc.createElement('button'); r.root.appendChild(opener); opener.focus();
    r.dock.open('data'); expect(r.stack.size()).toBe(1);
    expect(r.dock.el.dataset.sheet).toBe('true');
    fireKey(r.doc.activeElement, 'Escape');
    expect(r.dock.state().panel).toBeNull();
    expect(r.stack.size()).toBe(0); expect(r.doc.activeElement).toBe(opener);
    r.dock.destroy(); r.stack.destroy();
  });
});
