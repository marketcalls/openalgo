import { describe, expect, it } from 'vitest';
import { mountPanelDock, sanitizePanelDockState, type PanelDockOptions } from '../src/widget/panel-dock';
import { createOverlayStack, type WidgetContext } from '../src/widget/context';
import { fakeWidgetDocument, fakeContainer, type FakeElement } from './helpers/fake-dom-widget';

function rig(extra: Partial<PanelDockOptions> = {}) {
  const doc = fakeWidgetDocument(), root = fakeContainer(doc, 1000);
  const stage = doc.createElement('div'); root.appendChild(stage);
  const stack = createOverlayStack(root as unknown as HTMLElement, doc as unknown as Document);
  const ctx = { document: doc, root, overlays: stack, openOverlay: stack.open } as unknown as WidgetContext;
  const mounted: string[] = [], destroyed: string[] = [];
  const create = (name: string) => (host: HTMLElement) => { host.textContent = name; mounted.push(name); return { destroy: () => { destroyed.push(name); } }; };
  const withSources: Partial<PanelDockOptions> = {};
  if ('watchlist' in extra) withSources.watchlist = extra.watchlist ?? create('watchlist');
  if ('news' in extra) withSources.news = extra.news ?? create('news');
  const dock = mountPanelDock(ctx, stage as unknown as HTMLElement, { data: create('data'), objects: create('objects'), ...withSources, state: extra.state });
  const tabs = () => (dock.el as unknown as FakeElement).querySelectorAll('.oac-panel-dock__tabs button').map(b => b.textContent);
  return { dock, mounted, destroyed, tabs, stack };
}

describe('panel dock sources', () => {
  it('offers Watchlist and News tabs only when the host supplies them', () => {
    const plain = rig();
    expect(plain.tabs()).toEqual(['Data', 'Objects']);
    const full = rig({ watchlist: undefined, news: undefined });
    expect(full.tabs()).toEqual(['Data', 'Objects', 'Watchlist', 'News']);
    plain.dock.destroy(); full.dock.destroy();
  });

  it('keeps saved watchlist and news states, and opens them only where they exist', () => {
    expect(sanitizePanelDockState({ panel: 'watchlist', width: 320 })).toEqual({ panel: 'watchlist', width: 320 });
    expect(sanitizePanelDockState({ panel: 'news' })).toEqual({ panel: 'news', width: 300 });
    const plain = rig();
    plain.dock.open('news');
    expect(plain.dock.state().panel).toBeNull();
    plain.dock.restore({ panel: 'watchlist', width: 320 });
    expect(plain.dock.state()).toEqual({ panel: null, width: 320 });
    expect(plain.mounted).toEqual([]);
    const restored = rig({ watchlist: undefined, news: undefined, state: { panel: 'news', width: 300 } });
    expect(restored.mounted).toEqual(['news']);
    plain.dock.destroy(); restored.dock.destroy();
  });

  it('restoring a panel this dock lacks closes the one that was open, so the state and the dock agree', () => {
    const plain = rig();
    plain.dock.open('data');
    expect(plain.dock.state().panel).toBe('data');
    plain.dock.restore({ panel: 'watchlist', width: 320 });
    expect(plain.dock.state()).toEqual({ panel: null, width: 320 });
    expect(plain.destroyed).toEqual(['data']);
    expect(plain.dock.el.hidden).toBe(true);
    plain.dock.destroy();
  });

  it('mounts one source at a time and releases it on switch, close and destroy', () => {
    const r = rig({ watchlist: undefined, news: undefined });
    r.dock.open('watchlist');
    expect(r.mounted).toEqual(['watchlist']);
    r.dock.toggle('news');
    expect(r.destroyed).toEqual(['watchlist']);
    expect(r.dock.state().panel).toBe('news');
    const pressed = (r.dock.el as unknown as FakeElement).querySelectorAll('.oac-panel-dock__tabs button').map(b => b.getAttribute('aria-pressed'));
    expect(pressed).toEqual(['false', 'false', 'false', 'true']);
    r.dock.close();
    expect(r.destroyed).toEqual(['watchlist', 'news']);
    r.dock.open('watchlist');
    r.dock.destroy();
    expect(r.destroyed).toEqual(['watchlist', 'news', 'watchlist']);
    r.stack.destroy();
  });
});
