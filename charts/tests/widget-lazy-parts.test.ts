/**
 * The widget's parts that load on first use (src/widget/lazy.ts), held back
 * or failed on purpose. Every other suite meets them already arrived, which
 * is how a page meets them after the first open; here each part has not
 * arrived, so a press waits for it, a second press meanwhile opens it once,
 * a caller that has gone by then gets nothing, and a part that cannot load
 * says so and is fetched again on the next press.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar } from '../src/index';
import '../src/indicators/index';
import { WorkspaceRepository, createMemoryWorkspaceStorage } from '../src/workspace/index';
import {
  createIndexedDbWidgetStorage, createWidget, openLayoutsMenu, openShortcutsPanel, createLayoutsController, widgetLayoutTarget,
  WIDGET_STYLE_ID, type WidgetOptions,
} from '../src/widget/index';
import { lazyPart, partFailed, usePart, type LazyPart } from '../src/widget/lazy';
import { shortcutsPart } from '../src/widget/keymap';
import { layoutsMenuPart } from '../src/widget/layouts-widget';
import { templatesPart } from '../src/widget/dialogs/indicator-picker';
import { gridBarPart, gridMenusPart } from '../src/widget/grid';
import { dataExportPart } from '../src/widget/topbar';
import { indexedDbPart } from '../src/widget/storage';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';
import { FakeIndexedDb } from './helpers/fake-indexeddb';
import { makeGrid } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

/** A seeded random walk of five-minute bars, so the chart reads like a traded stock. */
const bars: Bar[] = (() => {
  let s = 11;
  let close = 1512.4;
  return Array.from({ length: 240 }, (_, i) => {
    s = (s * 16807) % 2147483647;
    const open = close;
    close = Math.round((open + (s / 2147483647 - 0.5) * 6) * 20) / 20;
    return { time: 1_700_000_000 + i * 300, open, high: Math.max(open, close) + 0.6, low: Math.min(open, close) - 0.6, close, volume: 40_000 + (s % 9000) };
  });
})();

const settle = async (): Promise<void> => { for (let i = 0; i < 12; i++) await Promise.resolve(); await new Promise(r => setTimeout(r, 0)); };

const restores: Array<() => void> = [];
const live: Array<{ destroy(): void; isDestroyed: boolean }> = [];
afterEach(() => {
  for (const item of live.splice(0)) if (!item.isDestroyed) item.destroy();
  for (const restore of restores.splice(0).reverse()) restore();
});

/**
 * Hold a part back: it has not arrived, and each load waits until the test
 * lets it `arrive` or `fail`. The part as the setup left it comes back after
 * the test.
 */
function holdBack<T>(part: LazyPart<T>) {
  const arrived = part.now;
  const load = part.load;
  if (arrived === null) throw new Error('the setup fetches every declared part first');
  const waiting: Array<{ resolve(module: T): void; reject(error: unknown): void }> = [];
  // One fetch shared by every caller while it is out, as lazyPart shares it.
  let out: Promise<T> | null = null;
  part.now = null;
  part.load = () => (out ??= new Promise<T>((resolve, reject) => { waiting.push({ resolve, reject }); }));
  restores.push(() => { part.now = arrived; part.load = load; });
  return {
    get loads() { return waiting.length; },
    arrive: async () => {
      part.now = arrived;
      out = null;
      for (const w of waiting.splice(0)) w.resolve(arrived);
      await settle();
    },
    fail: async (error: Error) => {
      out = null;
      for (const w of waiting.splice(0)) w.reject(error);
      await settle();
    },
  };
}

function make(options: WidgetOptions = {}, doc: FakeDocument = fakeWidgetDocument()) {
  const widget = createWidget(fakeContainer(doc, 1100, 700) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1, mobile: 'never', panels: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    symbol: 'INFY', exchange: 'NSE', interval: '5m', ...options,
  });
  widget.chart.applySize(1000, 600);
  widget.series.setData(bars);
  live.push(widget);
  const root = widget.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width: 1100, height: 700 };
  const chartEl = root.querySelector('.oac-chart') as FakeElement;
  chartEl.rect = { left: 42, top: 40, width: 1058, height: 636 };
  // The widget's chords answer while the pointer is over it.
  fire(root, 'pointerenter');
  return { widget, doc, root, chartEl };
}

const toasts = (root: FakeElement): string[] => root.querySelectorAll('.oac-toast__msg').map(t => t.textContent ?? '');
const pressQuestion = (chartEl: FakeElement): void => { fireKey(chartEl, '?', { shiftKey: true, code: 'Slash' }); };
const repository = (): WorkspaceRepository => {
  let n = 0;
  return new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => `layout-${++n}`, now: () => 1000 + n });
};

describe('a part', () => {
  it('is fetched once for every caller, and kept', async () => {
    let fetches = 0;
    const part = lazyPart(() => { fetches++; return Promise.resolve({ value: 7 }); });
    expect(part.now).toBeNull();
    const [a, b] = await Promise.all([part.load(), part.load()]);
    expect(a).toBe(b);
    expect(part.now).toBe(a);
    await part.load();
    expect(fetches).toBe(1);
  });

  it('forgets a failed fetch, so the next use fetches it again', async () => {
    let fetches = 0;
    const part = lazyPart(() => (++fetches === 1 ? Promise.reject(new Error('offline')) : Promise.resolve({ value: 7 })));
    await expect(part.load()).rejects.toThrow('offline');
    expect(part.now).toBeNull();
    await expect(part.load()).resolves.toEqual({ value: 7 });
    expect(fetches).toBe(2);
  });

  it('is used at once when it has arrived, and later when it has not', async () => {
    const part = lazyPart(() => Promise.resolve('module'));
    const used: string[] = [];
    usePart(part, m => used.push(`late ${m}`), () => used.push('failed'), () => true);
    expect(used).toEqual([]);
    await settle();
    expect(used).toEqual(['late module']);
    usePart(part, m => used.push(`now ${m}`), () => used.push('failed'), () => true);
    expect(used).toEqual(['late module', 'now module']);
  });

  it('answers a slot once however often it is asked while loading, and nothing once its caller has gone', async () => {
    let arrive: (m: string) => void = () => {};
    const part = lazyPart(() => new Promise<string>(resolve => { arrive = resolve; }));
    const doc = fakeWidgetDocument();
    const ask = { slot: { waiting: null }, doc: doc as unknown as Document };
    const used: string[] = [];
    usePart(part, m => used.push(m), () => {}, () => true, ask);
    usePart(part, m => used.push(m), () => {}, () => true, ask);
    expect(ask.slot.waiting).not.toBeNull();
    let gone = false;
    usePart(part, m => used.push(`gone ${m}`), () => {}, () => !gone);
    gone = true;
    arrive('menu');
    await settle();
    expect(used).toEqual(['menu']);
    expect(ask.slot.waiting).toBeNull();
  });

  /** A part held until `arrive`, or failed by `fail`, and a page with two controls and a text field. */
  function pending() {
    let arrive: (m: string) => void = () => {};
    let fail: (e: Error) => void = () => {};
    const part = lazyPart(() => new Promise<string>((resolve, reject) => { arrive = resolve; fail = reject; }));
    const doc = fakeWidgetDocument();
    const add = (tag: string): FakeElement => doc.body.appendChild(doc.createElement(tag)) as FakeElement;
    const first = add('button'), second = add('button'), field = add('input');
    const slot = { waiting: null };
    const used: string[] = [], told: string[] = [];
    const ask = (name: string, from: FakeElement | null): void => usePart(part, m => used.push(`${name} ${m}`),
      e => told.push(`${name} ${(e as Error).message}`), () => true, { slot, doc: doc as unknown as Document, from: from as unknown as Element });
    return {
      doc, first, second, field, used, told, ask,
      arrive: async () => { arrive('menu'); await settle(); },
      fail: async () => { fail(new Error('offline')); await settle(); },
    };
  }

  it('answers the latest request of a slot, not the first', async () => {
    const p = pending();
    p.ask('layouts', p.first);
    p.ask('link', p.second);
    await p.arrive();
    expect(p.used).toEqual(['link menu']);
  });

  it('opens nothing once the user pressed elsewhere or Escape while it loaded, and still tells a failure', async () => {
    const p = pending();
    p.ask('layouts', p.first);
    fire(p.first, 'pointerdown');
    await p.arrive();
    // Pressing the control that asked is asking again.
    expect(p.used).toEqual(['layouts menu']);

    const q = pending();
    q.ask('layouts', q.first);
    fire(q.doc.body, 'pointerdown');
    await q.arrive();
    expect(q.used).toEqual([]);

    const r = pending();
    r.ask('shortcuts', null);
    fireKey(r.doc.body, 'Escape');
    await r.arrive();
    expect(r.used).toEqual([]);

    const s = pending();
    s.ask('shortcuts', null);
    fireKey(s.doc.body, 'Escape');
    await s.fail();
    expect(s.told).toEqual(['shortcuts offline']);
  });

  it('opens nothing over a field the user started typing in while it loaded, but does over the one they asked from', async () => {
    const p = pending();
    p.ask('shortcuts', null);
    p.field.focus();
    await p.arrive();
    expect(p.used).toEqual([]);

    const q = pending();
    q.field.focus();
    q.ask('templates', q.first);
    await q.arrive();
    expect(q.used).toEqual(['templates menu']);
  });

  it('names what could not load and why', () => {
    expect(partFailed({}, 'Layouts', new Error('network down'))).toBe('Layouts could not load: network down');
    expect(partFailed({}, 'Layouts', 'blocked')).toBe('Layouts could not load: blocked');
  });
});

describe('the shortcuts panel', () => {
  it('opens once it arrives, once however often ? is pressed meanwhile', async () => {
    const held = holdBack(shortcutsPart);
    const { root, chartEl } = make();
    pressQuestion(chartEl);
    pressQuestion(chartEl);
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
    expect(held.loads).toBe(1);
    await held.arrive();
    expect(root.querySelectorAll('.oac-keys-dialog')).toHaveLength(1);
  });

  it('opens nothing when its closer ran before it arrived', async () => {
    const held = holdBack(shortcutsPart);
    const { widget, root } = make();
    const close = openShortcutsPanel(widget.context);
    close();
    await held.arrive();
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
  });

  it('opens nothing when Escape was pressed before it arrived', async () => {
    const held = holdBack(shortcutsPart);
    const { root, chartEl } = make();
    pressQuestion(chartEl);
    fireKey(chartEl, 'Escape');
    await held.arrive();
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
    pressQuestion(chartEl);
    expect(root.querySelector('.oac-keys-dialog')).not.toBeNull();
  });

  it('opens nothing on a widget destroyed before it arrived', async () => {
    const held = holdBack(shortcutsPart);
    const { widget, root, chartEl } = make();
    pressQuestion(chartEl);
    widget.destroy();
    await held.arrive();
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
    expect(toasts(root)).toEqual([]);
  });

  it('says why it could not load, and the next ? fetches it again', async () => {
    const held = holdBack(shortcutsPart);
    const { root, chartEl } = make();
    pressQuestion(chartEl);
    await held.fail(new Error('network down'));
    expect(toasts(root)).toContain('Keyboard shortcuts could not load: network down');
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
    pressQuestion(chartEl);
    expect(held.loads).toBe(1);
    await held.arrive();
    expect(root.querySelector('.oac-keys-dialog')).not.toBeNull();
  });

  it('adds its rules to the widget sheet once, however often it opens', () => {
    const { widget, doc } = make();
    const sheet = (doc as unknown as Document).getElementById(WIDGET_STYLE_ID)!;
    const rule = '.oac-widget .oac-keys__conflict {';
    expect(sheet.textContent).not.toContain(rule);
    openShortcutsPanel(widget.context)();
    openShortcutsPanel(widget.context)();
    expect(sheet.textContent!.split(rule)).toHaveLength(2);
  });
});

describe('the Layouts menu', () => {
  it('opens once it arrives, once however often its button is pressed meanwhile', async () => {
    const held = holdBack(layoutsMenuPart);
    const { root } = make({ workspaces: repository() });
    await settle();
    const button = root.querySelector('.oac-topbar__layouts') as FakeElement;
    button.click();
    button.click();
    expect(root.querySelector('.oac-layouts')).toBeNull();
    await held.arrive();
    expect(root.querySelectorAll('.oac-layouts')).toHaveLength(1);
  });

  it('says why it could not load, and the next press fetches it again', async () => {
    const held = holdBack(layoutsMenuPart);
    const { widget, root } = make({ workspaces: repository() });
    await settle();
    expect(widget.openLayouts()).toBe(true);
    await held.fail(new Error('network down'));
    expect(toasts(root)).toContain('Layouts could not load: network down');
    expect(widget.openLayouts()).toBe(true);
    await held.arrive();
    expect(root.querySelector('.oac-layouts')).not.toBeNull();
  });

  it('resolves openLayoutsMenu with its handle once it arrives, and rejects when it cannot load', async () => {
    const held = holdBack(layoutsMenuPart);
    const { widget, root } = make();
    const controller = createLayoutsController(repository(), widgetLayoutTarget(widget));
    live.push({ destroy: () => controller.destroy(), isDestroyed: false });
    const failing = expect(openLayoutsMenu(widget.context, controller)).rejects.toThrow('network down');
    await held.fail(new Error('network down'));
    await failing;
    const opening = openLayoutsMenu(widget.context, controller);
    await held.arrive();
    const handle = await opening;
    expect(handle.isOpen()).toBe(true);
    expect(root.querySelector('.oac-layouts')).toBe(handle.el);
  });

  it('rejects openLayoutsMenu over a widget destroyed before the menu arrived, and opens nothing', async () => {
    const held = holdBack(layoutsMenuPart);
    const { widget, root } = make();
    const controller = createLayoutsController(repository(), widgetLayoutTarget(widget));
    live.push({ destroy: () => controller.destroy(), isDestroyed: false });
    const opening = expect(openLayoutsMenu(widget.context, controller)).rejects.toThrow('destroyed');
    widget.destroy();
    await held.arrive();
    await opening;
    expect(root.querySelector('.oac-layouts')).toBeNull();
  });
});

describe('the indicator templates list', () => {
  it('opens once it arrives, and not at all once the picker has closed', async () => {
    const held = holdBack(templatesPart);
    const { widget, root } = make({ workspaces: repository() });
    await settle();
    expect(widget.openIndicatorPicker()).toBe(true);
    const templates = root.querySelector('.oac-pick [data-action="templates"]') as FakeElement;
    templates.click();
    templates.click();
    expect(held.loads).toBe(1);
    await held.arrive();
    expect(root.querySelectorAll('.oac-templates')).toHaveLength(1);
    // A picker closed while the list is on its way opens no list.
    root.querySelector('.oac-templates')!.remove();
    const again = holdBack(templatesPart);
    root.querySelector('.oac-pick [data-action="templates"]')!.click();
    root.querySelectorAll('.oac-pick .oac-btn').find(b => b.textContent === 'Done')!.click();
    await again.arrive();
    expect(root.querySelector('.oac-pick')).toBeNull();
    expect(root.querySelector('.oac-templates')).toBeNull();
  });
});

describe('the chart data dialog', () => {
  it('opens once it arrives, and says so on the status line when it cannot load', async () => {
    const held = holdBack(dataExportPart);
    const { root } = make();
    const choose = (): void => {
      root.querySelector('[aria-label="Capture chart"]')!.click();
      root.querySelectorAll('.oac-menu__row').find(row => row.textContent === 'Download chart data (CSV)')!.click();
    };
    choose();
    await held.fail(new Error('network down'));
    expect(root.querySelector('.oac-statusline')?.textContent).toContain('Download chart data (CSV) could not load: network down');
    choose();
    await held.arrive();
    expect(root.querySelector('.oac-csv')).not.toBeNull();
  });
});

describe('the grid bar and its menus', () => {
  it('fill a strip already laid out at the bar height, and open a menu once it arrives', async () => {
    const bar = holdBack(gridBarPart);
    const menus = holdBack(gridMenusPart);
    const { grid, root } = makeGrid({ preset: '2x2', toolbar: true });
    const strip = root.querySelector('.oac-grid__bar') as FakeElement;
    expect(strip.getAttribute('role')).toBe('toolbar');
    expect(strip.querySelector('.oac-grid__layout')).toBeNull();
    await bar.arrive();
    const layout = strip.querySelector('.oac-grid__layout') as FakeElement;
    expect(layout).not.toBeNull();
    layout.click();
    layout.click();
    expect(root.querySelector('.oac-grid__picker')).toBeNull();
    await menus.arrive();
    expect(root.querySelectorAll('.oac-grid__picker')).toHaveLength(1);
    expect(grid.isDestroyed).toBe(false);
  });

  it('open the menu pressed last while they load, not the first', async () => {
    const menus = holdBack(gridMenusPart);
    const { root } = makeGrid({ preset: '1x2', toolbar: true });
    (root.querySelector('.oac-grid__layout') as FakeElement).click();
    (root.querySelector('.oac-grid__link') as FakeElement).click();
    await menus.arrive();
    expect(root.querySelector('.oac-grid__picker')).toBeNull();
    expect(root.querySelectorAll('.oac-grid__menu')).toHaveLength(1);
  });

  it('say on the active chart when a menu cannot load', async () => {
    const menus = holdBack(gridMenusPart);
    const { grid, root } = makeGrid({ preset: '1x2', toolbar: true });
    (root.querySelector('.oac-grid__link') as FakeElement).click();
    await menus.fail(new Error('network down'));
    expect(toasts(grid.active().widget.root as unknown as FakeElement)).toContain('Linking could not load: network down');
  });

  it('mount nothing on a grid destroyed before the bar arrived', async () => {
    const bar = holdBack(gridBarPart);
    const { grid, root } = makeGrid({ preset: '1x2', toolbar: true });
    grid.destroy();
    await bar.arrive();
    expect(root.querySelector('.oac-grid__layout')).toBeNull();
  });
});

describe('the IndexedDB store', () => {
  it('waits for its code, hears changes asked for meanwhile, and then reads and writes as before', async () => {
    const held = holdBack(indexedDbPart);
    const store = createIndexedDbWidgetStorage(new FakeIndexedDb() as unknown as IDBFactory, 'lazy-test', { journal: null, migrateFrom: null });
    const heard: Array<[string, string | null]> = [];
    store.subscribe((key, value) => heard.push([key, value]));
    const write = store.setItem('oac-widget:a:state', '{"n":1}');
    await settle();
    expect(held.loads).toBe(1);
    await held.arrive();
    await write;
    expect(await store.entries('oac-widget:a:')).toEqual([['oac-widget:a:state', '{"n":1}']]);
    expect(heard).toEqual([['oac-widget:a:state', '{"n":1}']]);
    store.close();
  });

  it('fetches its code as it is created, so a listener alone hears another tab without a read or write here', async () => {
    const held = holdBack(indexedDbPart);
    const db = new FakeIndexedDb() as unknown as IDBFactory;
    const listening = createIndexedDbWidgetStorage(db, 'lazy-listen', { journal: null, migrateFrom: null });
    const heard: Array<[string, string | null]> = [];
    listening.subscribe((key, value) => heard.push([key, value]));
    expect(held.loads).toBe(1);
    await held.arrive();
    const writer = createIndexedDbWidgetStorage(db, 'lazy-listen', { journal: null, migrateFrom: null });
    await writer.setItem('oac-widget:a:state', '{"n":2}');
    for (let i = 0; i < 50 && heard.length === 0; i++) await new Promise(resolve => setTimeout(resolve, 1));
    expect(heard).toEqual([['oac-widget:a:state', '{"n":2}']]);
    listening.close();
    writer.close();
  });

  it('fails its reads when its code cannot load', async () => {
    const held = holdBack(indexedDbPart);
    const store = createIndexedDbWidgetStorage(new FakeIndexedDb() as unknown as IDBFactory, 'lazy-test', { journal: null, migrateFrom: null });
    const read = expect(store.entries('oac-widget:a:')).rejects.toThrow('network down');
    await settle();
    await held.fail(new Error('network down'));
    await read;
  });
});
