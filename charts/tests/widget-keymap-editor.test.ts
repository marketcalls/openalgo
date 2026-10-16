/**
 * The shortcuts editor inside a real widget shell: a moved chord does what
 * the old one did (the editing keys included, which used to read the key
 * pressed), the rail's tips follow it, the change survives a new widget on
 * the same storage, and the panel records a chord, names a conflict, refuses
 * what it must and resets. Everything runs against the fake DOM.
 */
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import type { Bar } from '../src/index';
import {
  createWidget, openShortcutsPanel, contextMenuEntries, mountContextMenu, mountDrawingProperties, KEYMAP_KEY, STORAGE_PREFIX,
  type Widget, type WidgetOptions, type StorageLike, type WidgetMessageKey,
} from '../src/widget/index';
import { fakeWidgetDocument, fakeContainer, fireKey, fire, ensureWindowGlobal, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const DAY = 86400;
const T0 = 1700000000;
/** A seeded random walk, so a failing snapshot of the chart reads like a traded instrument. */
const bars = (n: number): Bar[] => {
  let seed = 7;
  const next = (): number => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  let price = 100;
  return Array.from({ length: n }, (_, i) => {
    const open = price;
    price = Math.max(1, price * (1 + (next() - 0.5) * 0.03));
    return { time: T0 + i * DAY, open, high: Math.max(open, price) * 1.004, low: Math.min(open, price) * 0.996, close: price, volume: 1000 + Math.round(next() * 500) };
  });
};

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

interface Made { w: Widget; doc: FakeDocument; root: FakeElement; chartEl: FakeElement }

function make(opts: WidgetOptions = {}, doc: FakeDocument = fakeWidgetDocument()): Made {
  const container = fakeContainer(doc);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(800, 600);
  w.series.setData(bars(30));
  live.push(w);
  const root = w.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width: 800, height: 600 };
  const chartEl = root.querySelector('.oac-chart') as FakeElement;
  chartEl.rect = { left: 42, top: 40, width: 758, height: 536 };
  fire(root, 'pointerenter');
  return { w, doc, root, chartEl };
}

const addLine = (w: Widget, price = 100): string =>
  w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price }], style: {}, paneIndex: 0 }).id;

const row = (root: FakeElement, command: string): FakeElement =>
  root.querySelectorAll('.oac-keys__row').find((r) => r.dataset.command === command) as FakeElement;
const chordOf = (root: FakeElement, command: string): string => row(root, command).querySelector('kbd')?.textContent ?? '';
const status = (root: FakeElement): string => root.querySelector('.oac-keys__status')?.textContent ?? '';

describe('a moved chord does what the old one did', () => {
  it('undo, copy and delete follow their command to a new chord, and the old chord is free', () => {
    const { w, chartEl } = make();
    const km = w.context.keymap;
    const id = addLine(w);
    expect(km.rebind('undo', 'Alt+U').ok).toBe(true);
    // The old chord belongs to nobody now: nothing claims it.
    const old = fireKey(chartEl, 'z', { ctrlKey: true, code: 'KeyZ' });
    expect(old.defaultPrevented).toBe(false);
    expect(w.draw.drawings()).toHaveLength(1);
    fireKey(chartEl, 'u', { altKey: true, code: 'KeyU' });
    expect(w.draw.drawings()).toHaveLength(0);
    fireKey(chartEl, 'z', { ctrlKey: true, shiftKey: true, code: 'KeyZ' });
    expect(w.draw.get(id)).toBeDefined();

    expect(km.rebind('delete', 'Alt+D').ok).toBe(true);
    // Nothing selected or hovered: the moved delete declines, like the old key did.
    expect(fireKey(chartEl, 'd', { altKey: true, code: 'KeyD' }).defaultPrevented).toBe(false);
    w.draw.select(id);
    expect(fireKey(chartEl, 'Delete').defaultPrevented).toBe(false);
    expect(w.draw.drawings()).toHaveLength(1);
    fireKey(chartEl, 'd', { altKey: true, code: 'KeyD' });
    expect(w.draw.drawings()).toHaveLength(0);
  });

  it('a moved tool chord picks its tool, and the fixed keys keep the tier\'s declines', () => {
    const { w, chartEl } = make();
    w.context.keymap.rebind('tool:trend-line', 'Alt+Y');
    fireKey(chartEl, 't', { altKey: true, code: 'KeyT' });
    expect(w.draw.activeTool()).toBeNull();
    fireKey(chartEl, 'y', { altKey: true, code: 'KeyY' });
    expect(w.draw.activeTool()).toBe('trend-line');
    fireKey(chartEl, 'Escape');
    expect(w.draw.activeTool()).toBeNull();
    // An arrow with nothing selected is still the chart's pan.
    expect(fireKey(chartEl, 'ArrowLeft').defaultPrevented).toBe(false);
    expect(w.context.keymap.rebind('leave', 'Alt+E')).toMatchObject({ ok: false, reason: 'fixed' });
    expect(w.context.keymap.rebind('shortcuts', 'Alt+K')).toMatchObject({ ok: false, reason: 'fixed' });
  });

  it('the context menu, the properties dialog and the toolbar\'s more menu name the chord in force', () => {
    const { w, root } = make();
    const km = w.context.keymap;
    const id = addLine(w);
    w.draw.select(id);
    const menuChords = (): Record<string, string | undefined> => {
      const at = { paneIndex: 0, point: { x: 200, y: 150 }, price: 100, time: T0 + 5 * DAY, index: 5, preventDefault: () => {} };
      const entries = [
        ...contextMenuEntries(w.context, { ...at, target: { kind: 'drawing', id: `draw:${id}` } }),
        ...contextMenuEntries(w.context, { ...at, target: { kind: 'empty', id: null } }),
      ];
      const out: Record<string, string | undefined> = {};
      for (const e of entries) if ('id' in e && e.id !== undefined && e.id.startsWith('draw-')) out[e.id] = (e as { chord?: string }).chord;
      return out;
    };
    const before = menuChords();
    expect(before['draw-copy']).toBe(km.format('Mod+C'));
    // Fit all bars names the chart's chord too, as every other row with one does.
    const fit = contextMenuEntries(w.context, { paneIndex: 0, point: { x: 200, y: 150 }, price: 100, time: T0 + 5 * DAY, index: 5, preventDefault: () => {}, target: { kind: 'empty', id: null } })
      .find((e) => 'id' in e && e.id === 'chart-fit') as { chord?: string };
    expect(fit.chord).toBe(km.format('Alt+F'));
    // Painted rows keep the chord out of the name and carry it as the row's shortcut.
    mountContextMenu(w.context, undefined, { event: { paneIndex: 0, point: { x: 200, y: 150 }, price: 100, time: T0 + 5 * DAY, index: 5, preventDefault: () => {}, target: { kind: 'empty', id: null } } });
    const row = root.querySelector('.oac-ctx [data-act="chart-fit"]') as FakeElement;
    expect(row.querySelector('.oac-ctx__key')!.getAttribute('aria-hidden')).toBe('true');
    expect(row.getAttribute('aria-keyshortcuts')).toBe('Alt+F');
    expect(before['draw-delete']).toBe(km.format('Delete'));
    for (const [command, combo] of [['copy', 'Alt+Shift+C'], ['cut', 'Alt+Shift+X'], ['paste', 'Alt+Shift+V'], ['duplicate', 'Alt+Shift+D'], ['delete', 'Alt+Shift+Backspace']]) {
      expect(km.rebind(command, combo).ok, command).toBe(true);
    }
    const after = menuChords();
    expect([after['draw-copy'], after['draw-cut'], after['draw-duplicate'], after['draw-delete']])
      .toEqual([km.format('Alt+Shift+C'), km.format('Alt+Shift+X'), km.format('Alt+Shift+D'), km.format('Alt+Shift+Backspace')]);
    // Paste shows on an empty spot once the clipboard holds a drawing.
    void w.draw.copy([id]);
    expect(menuChords()['draw-paste']).toBe(km.format('Alt+Shift+V'));
    // An unbound command shows no chord rather than one that does nothing.
    km.rebind('copy', null);
    expect(menuChords()['draw-copy']).toBeUndefined();

    const props = mountDrawingProperties(w.context, undefined, { ids: [id] });
    const titleOf = (act: string): string => (root.querySelector(`.oac-btn[data-act="${act}"]`) as FakeElement).title;
    expect(titleOf('duplicate')).toContain(km.format('Alt+Shift+D'));
    expect(titleOf('delete')).toContain(km.format('Alt+Shift+Backspace'));
    props.close();

    (root.querySelector('[data-drawbar="more"]') as FakeElement).click();
    const duplicateRow = root.querySelectorAll('.oac-menu__row').find((r) => r.textContent.startsWith('Duplicate'));
    expect(duplicateRow?.querySelector('.oac-menu__key')?.textContent).toBe(km.format('Alt+Shift+D'));
  });

  it('the rail reads the chord in force for its tool rows and tips', () => {
    const { w, root } = make();
    const km = w.context.keymap;
    const flyoutChord = (): string => {
      const rail = w.root.querySelector('.oac-rail') as unknown as FakeElement;
      (rail.querySelector('.oac-rail__group[data-group="lines"]') as FakeElement).click();
      (rail.querySelector('.oac-rail__group[data-group="lines"]') as FakeElement).click();
      const text = root.querySelector('.oac-fly__row[data-tool="trend-line"] .oac-fly__chord')?.textContent ?? '';
      w.context.overlays.closeAll();
      w.draw.setTool(null);
      return text;
    };
    // The rail's controls in order: magnet, stay, lock, eye, trash, undo, redo.
    const tip = (index: number): string => {
      const btn = root.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[index];
      w.context.tips.show(btn as unknown as HTMLElement);
      return root.querySelector('.oac-tip .oac-tip__chord')?.textContent ?? '';
    };
    expect(flyoutChord()).toBe(km.format('Alt+T'));
    km.rebind('tool:trend-line', 'Alt+Y');
    expect(flyoutChord()).toBe(km.format('Alt+Y'));
    km.rebind('tool:trend-line', null);
    expect(flyoutChord()).toBe('');
    expect(tip(5)).toBe(km.format('Mod+Z'));
    km.rebind('undo', 'Alt+U');
    expect(tip(5)).toBe(km.format('Alt+U'));
    expect(tip(4)).toBe(km.format('Delete'));
    km.rebind('delete', 'Alt+D');
    expect(tip(4)).toBe(km.format('Alt+D'));
    // Ctrl+Y still redoes, so the tip keeps it; once it goes, the listed Redo shows.
    expect(tip(6)).toBe(km.format('Mod+Y'));
    km.rebind('undo', 'Mod+Y', { replace: true });
    expect(tip(6)).toBe(km.format('Mod+Shift+Z'));
  });
});

describe('the user\'s chords persist', () => {
  it('are written under the keymap key and put back in a new widget on the same storage', () => {
    const store = new MemoryStorage();
    const key = `${STORAGE_PREFIX}default:${KEYMAP_KEY}`;
    const first = make({ persist: true, storage: store });
    first.w.context.keymap.rebind('tool:trend-line', 'Alt+H', { replace: true });
    first.w.context.keymap.rebind('chart:fitContent', 'Alt+KeyG');
    expect(JSON.parse(store.map.get(key) as string)).toEqual({
      'tool:trend-line': 'Alt+h', 'tool:horizontal-line': null, 'chart:toggleGridHorz': null, 'chart:fitContent': ['Alt+KeyG'],
    });
    first.w.destroy();

    const again = make({ persist: true, storage: store });
    const km = again.w.context.keymap;
    expect(km.chord('tool:trend-line')).toBe('Alt+h');
    expect(km.chord('tool:horizontal-line')).toBe('');
    expect(again.w.chart.shortcuts?.handleKey('Alt+KeyG')).toBe('fitContent');
    fireKey(again.chartEl, 'h', { altKey: true, code: 'KeyH' });
    expect(again.w.draw.activeTool()).toBe('trend-line');
    km.resetAll();
    // Nothing left to keep: the entry goes rather than holding an empty record.
    expect(store.map.has(key)).toBe(false);
    expect(again.w.chart.shortcuts?.handleKey('Alt+KeyF')).toBe('fitContent');
  });

  it('a widget that does not persist still rebinds for the session and writes nothing', () => {
    const store = new MemoryStorage();
    const { w } = make({ persist: false, storage: store });
    expect(w.context.keymap.rebind('undo', 'Alt+U').ok).toBe(true);
    expect(store.map.size).toBe(0);
  });

  it('with the editor off, the panel only lists and a saved record is not applied', () => {
    const store = new MemoryStorage();
    const key = `${STORAGE_PREFIX}default:${KEYMAP_KEY}`;
    store.setItem(key, JSON.stringify({ undo: 'Alt+u' }));
    const m = make({ persist: true, storage: store, shortcutsEditor: false });
    expect(m.w.context.keymap.chord('undo')).toBe('Mod+z');
    fireKey(m.chartEl, '?', { shiftKey: true, code: 'Slash' });
    expect(m.root.querySelector('.oac-keys-dialog')).not.toBeNull();
    expect(m.root.querySelector('.oac-keys__change')).toBeNull();
    // A host's own change is the host's to keep: nothing is written for it.
    m.w.context.keymap.rebind('undo', 'Alt+J');
    expect(store.getItem(key)).toBe(JSON.stringify({ undo: 'Alt+u' }));
    // A host control that opens the panel gets the same list `?` opens.
    m.w.context.overlays.closeAll();
    openShortcutsPanel(m.w.context);
    expect(m.root.querySelector('.oac-keys-dialog')).not.toBeNull();
    expect(m.root.querySelector('.oac-keys__change')).toBeNull();
    expect(m.root.querySelector('.oac-keys-dialog .oac-dialog__foot')).toBeNull();
  });

  it('a host control opens the editor on a widget that keeps it', () => {
    const m = make();
    openShortcutsPanel(m.w.context);
    expect(m.root.querySelector('.oac-keys__change')).not.toBeNull();
    expect(m.root.querySelector('.oac-keys__reset-all')).not.toBeNull();
  });

  it('a saved record the widget cannot read leaves the defaults', () => {
    const store = new MemoryStorage();
    store.setItem(`${STORAGE_PREFIX}default:${KEYMAP_KEY}`, '{"undo": 5, "tool:trend-line": "Foo+x", "leave": "Alt+E"}');
    const { w } = make({ persist: true, storage: store });
    expect(w.context.keymap.chord('undo')).toBe('Mod+z');
    expect(w.context.keymap.chord('tool:trend-line')).toBe('Alt+t');
    expect(w.context.keymap.chord('leave')).toBe('Escape');
  });
});

describe('the shortcuts panel as an editor', () => {
  const open = (m: Made): FakeElement => {
    fireKey(m.chartEl, '?', { shiftKey: true, code: 'Slash' });
    return m.root.querySelector('.oac-keys-dialog') as FakeElement;
  };
  const change = (root: FakeElement, command: string): FakeElement => row(root, command).querySelector('.oac-keys__change') as FakeElement;
  const reset = (root: FakeElement, command: string): FakeElement => row(root, command).querySelector('.oac-keys__reset') as FakeElement;

  it('opens with the focus on the panel itself, so the list starts at its top', () => {
    const m = make();
    const panel = open(m);
    // The first control is a Change halfway down; focusing it would scroll the first groups away.
    expect(m.doc.activeElement).toBe(panel);
    m.w.context.overlays.closeAll();
    // The plain list keeps its old landing place, the first control there is.
    openShortcutsPanel(m.w.context, { edit: false });
    expect(m.doc.activeElement).toBe(m.root.querySelector('.oac-keys-dialog .oac-dialog__head .oac-btn'));
  });

  it('offers Change on the rows a user may move and none on the fixed ones', () => {
    const m = make();
    const panel = open(m);
    expect(panel).not.toBeNull();
    expect(change(m.root, 'tool:trend-line')).not.toBeNull();
    expect(change(m.root, 'chart:fitContent')).not.toBeNull();
    expect(change(m.root, 'leave')).toBeNull();
    expect(change(m.root, 'shortcuts')).toBeNull();
    // A row with nothing to reset keeps its place but offers no control.
    expect(reset(m.root, 'tool:trend-line').disabled).toBe(true);
    expect(reset(m.root, 'tool:trend-line').classList.contains('is-idle')).toBe(true);
    expect((m.root.querySelector('.oac-keys__reset-all') as FakeElement).disabled).toBe(true);
    // The rail keys carry no command and stay listed as they were.
    expect(m.root.querySelectorAll('.oac-keys__row').some((r) => r.dataset.command === undefined && r.querySelector('.oac-keys__change') === null)).toBe(true);
  });

  it('records the next chord pressed, and Escape cancels without closing the panel', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'tool:trend-line').click();
    expect(row(m.root, 'tool:trend-line').classList.contains('is-listening')).toBe(true);
    expect(status(m.root)).toMatch(/Press the new shortcut for Trend Line/i);
    // A modifier alone is the start of a chord: still listening.
    fireKey(panel, 'Alt', { altKey: true, code: 'AltLeft' });
    expect(row(m.root, 'tool:trend-line').classList.contains('is-listening')).toBe(true);
    fireKey(panel, 'Escape');
    expect(m.w.context.overlays.size()).toBe(1);
    expect(row(m.root, 'tool:trend-line').classList.contains('is-listening')).toBe(false);
    expect(m.w.context.keymap.chord('tool:trend-line')).toBe('Alt+t');

    change(m.root, 'tool:trend-line').click();
    fireKey(panel, 'y', { altKey: true, code: 'KeyY' });
    expect(m.w.context.keymap.chord('tool:trend-line')).toBe('Alt+y');
    expect(chordOf(m.root, 'tool:trend-line')).toBe(m.w.context.keymap.format('Alt+Y'));
    expect(row(m.root, 'tool:trend-line').classList.contains('is-changed')).toBe(true);
    expect(reset(m.root, 'tool:trend-line').disabled).toBe(false);
    expect(status(m.root)).toMatch(/is now/);
    // Recording is over: the next chord is a chord again, and the panel keeps it from the chart.
    fireKey(panel, 'y', { altKey: true, code: 'KeyY' });
    expect(m.w.draw.activeTool()).toBeNull();
    expect(m.w.context.keymap.chord('tool:trend-line')).toBe('Alt+y');
  });

  it('names the bindings holding a chord and replaces them only when asked', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'tool:trend-line').click();
    fireKey(panel, 'h', { altKey: true, code: 'KeyH' });
    const notice = m.root.querySelector('.oac-keys__conflict') as FakeElement;
    expect(notice).not.toBeNull();
    expect(notice.querySelector('span')?.textContent).toMatch(/Horizontal Line/i);
    expect(notice.querySelector('span')?.textContent).toMatch(/Toggle horizontal grid/);
    expect(m.w.context.keymap.chord('tool:trend-line')).toBe('Alt+t');
    // Cancel leaves both where they were.
    (notice.querySelectorAll('button')[0]).click();
    expect(m.root.querySelector('.oac-keys__conflict')).toBeNull();
    expect(m.w.context.keymap.chord('tool:horizontal-line')).toBe('Alt+h');

    change(m.root, 'tool:trend-line').click();
    fireKey(panel, 'h', { altKey: true, code: 'KeyH' });
    (m.root.querySelector('.oac-keys__conflict') as FakeElement).querySelectorAll('button')[1].click();
    expect(m.w.context.keymap.chord('tool:trend-line')).toBe('Alt+h');
    expect(chordOf(m.root, 'tool:horizontal-line')).toBe('Not set');
    expect(chordOf(m.root, 'chart:toggleGridHorz')).toBe('Not set');
    expect(status(m.root)).toMatch(/Taken from/);
  });

  it('refuses a fixed holder, a browser chord and a bare letter, and keeps listening', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'undo').click();
    fireKey(panel, 'Enter');
    expect(status(m.root)).toMatch(/cannot change/);
    fireKey(panel, 'w', { ctrlKey: true, code: 'KeyW' });
    expect(status(m.root)).toMatch(/belongs to the browser/);
    fireKey(panel, 'g', { code: 'KeyG' });
    expect(status(m.root)).toMatch(/types into the chart/);
    // Space alone presses the focused button: bound, it would take that from every control.
    fireKey(panel, ' ', { code: 'Space' });
    expect(status(m.root)).toMatch(/presses the focused control/);
    fireKey(panel, ' ', { shiftKey: true, code: 'Space' });
    expect(status(m.root)).toMatch(/presses the focused control/);
    expect(m.w.context.keymap.chord('undo')).toBe('Mod+z');
    expect(row(m.root, 'undo').classList.contains('is-listening')).toBe(true);
    fireKey(panel, 'u', { altKey: true, code: 'KeyU' });
    expect(m.w.context.keymap.chord('undo')).toBe('Alt+u');
  });

  it('Tab ends the recording and moves the focus as usual', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'undo').click();
    const tab = fireKey(panel, 'Tab');
    expect(row(m.root, 'undo').classList.contains('is-listening')).toBe(false);
    expect(m.w.context.keymap.capturing).toBe(false);
    expect(m.w.context.keymap.chord('undo')).toBe('Mod+z');
    expect(tab.immediateStopped).toBe(false);
  });

  it('rebinds a chart command with the physical key, through the chart\'s manager', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'chart:fitContent').click();
    fireKey(panel, 'g', { altKey: true, code: 'KeyG' });
    expect(m.w.chart.shortcuts?.handleKey('Alt+KeyG')).toBe('fitContent');
    expect(chordOf(m.root, 'chart:fitContent')).toBe(m.w.context.keymap.format('Alt+G'));
    reset(m.root, 'chart:fitContent').click();
    expect(m.w.chart.shortcuts?.handleKey('Alt+KeyF')).toBe('fitContent');
  });

  it('records a chart chord on macOS as the one it shows: Control or Cmd, both are Mod', () => {
    vi.stubGlobal('navigator', { platform: 'MacIntel', userAgent: '' });
    try {
      const m = make();
      expect(m.w.context.keymap.isMac).toBe(true);
      const panel = open(m);
      change(m.root, 'chart:fitContent').click();
      fireKey(panel, 'g', { ctrlKey: true, code: 'KeyG' });
      expect(chordOf(m.root, 'chart:fitContent')).toBe('Cmd+G');
      // Cmd+G, the chord the row names, is what now fits the content.
      expect(m.w.chart.shortcuts?.handleKey('Mod+KeyG')).toBe('fitContent');
    } finally { vi.unstubAllGlobals(); }
  });

  it('resets a row, offers the choice when its default is taken, and resets all after a confirmation', () => {
    const m = make();
    const km = m.w.context.keymap;
    open(m);
    km.rebind('tool:horizontal-line', 'Alt+K');
    km.rebind('tool:trend-line', 'Alt+H', { replace: true });
    // The panel redraws for a change it did not make.
    expect(chordOf(m.root, 'tool:trend-line')).toBe(km.format('Alt+H'));
    reset(m.root, 'tool:horizontal-line').click();
    const notice = m.root.querySelector('.oac-keys__conflict') as FakeElement;
    expect(notice.querySelector('span')?.textContent).toMatch(/Trend Line/i);
    notice.querySelectorAll('button')[1].click();
    expect(km.chord('tool:horizontal-line')).toBe('Alt+h');
    expect(km.chord('tool:trend-line')).toBe('');

    const all = m.root.querySelector('.oac-keys__reset-all') as FakeElement;
    expect(all.disabled).toBe(false);
    all.click();
    expect(status(m.root)).toMatch(/every shortcut back/i);
    expect(km.overrides()).not.toEqual({});
    const [no, yes] = m.root.querySelectorAll('.oac-dialog__foot .oac-btn').filter((b) => !b.hidden && !b.classList.contains('oac-keys__reset-all'));
    expect(no.textContent).toBe('Cancel');
    yes.click();
    expect(km.overrides()).toEqual({});
    expect(chordOf(m.root, 'tool:trend-line')).toBe(km.format('Alt+T'));
  });

  it('closes on Escape once nothing is recording, and stops recording when it closes', () => {
    const m = make();
    const panel = open(m);
    change(m.root, 'undo').click();
    (m.root.querySelector('.oac-keys-dialog .oac-dialog__head .oac-btn') as FakeElement).click();
    expect(m.w.context.overlays.size()).toBe(0);
    expect(m.w.context.keymap.capturing).toBe(false);
    const again = open(m);
    expect(again).not.toBe(panel);
    fireKey(again, 'Escape');
    expect(m.w.context.overlays.size()).toBe(0);
  });

  it('heads the own group of the widget General', () => {
    const m = make();
    open(m);
    const heads = m.root.querySelectorAll('.oac-keys__group h3, .oac-keys__group .oac-head').map((h) => h.textContent);
    expect(heads).toContain('General');
    expect(heads).not.toContain('Widget');
  });

  it('says another shortcut takes precedence, in the active wording', () => {
    const m = make();
    open(m);
    const note = m.root.querySelector('.oac-keys__note')?.textContent ?? '';
    expect(note).toMatch(/another shortcut uses the same chord here and takes precedence/);
    expect(note).not.toMatch(/\barm/i);
  });

  it('keeps the retired note keys valid in a typed host catalog until 3.0.0', () => {
    // A catalog written for 2.5.9 still compiles: tsc reads this file, so
    // dropping either key from the union fails the typecheck.
    const messages: Partial<Record<WidgetMessageKey, string>> = {
      '{count} chart shortcut struck through: the same chord arms a drawing tool here and takes precedence.': '{count}',
      '{count} chart shortcuts struck through: the same chord arms a drawing tool here and takes precedence.': '{count}',
    };
    // The panel asks for the new keys, so a catalog translates those instead.
    const asked: string[] = [];
    const m = make({ translate: (key, fallback) => { asked.push(key); return messages[key as WidgetMessageKey] ?? fallback; } });
    open(m);
    expect(asked).toContain('{count} chart shortcuts struck through: another shortcut uses the same chord here and takes precedence.');
    expect(asked.some((k) => /arms a drawing tool/.test(k))).toBe(false);
  });

  it('keeps the focus on its control when a change made elsewhere redraws the rows', () => {
    const m = make();
    open(m);
    change(m.root, 'undo').focus();
    // A host, or a neighbouring chart sharing the chords, moves another command.
    m.w.context.keymap.rebind('tool:trend-line', 'Alt+Y');
    expect(chordOf(m.root, 'tool:trend-line')).toBe(m.w.context.keymap.format('Alt+Y'));
    expect(m.doc.activeElement).toBe(change(m.root, 'undo'));
    expect(change(m.root, 'undo').isConnected).toBe(true);
    // A Reset that the change leaves with nothing to reset hands the focus to its row's Change.
    m.w.context.keymap.rebind('undo', 'Alt+U');
    reset(m.root, 'undo').focus();
    m.w.context.keymap.reset('undo');
    expect(reset(m.root, 'undo').disabled).toBe(true);
    expect(m.doc.activeElement).toBe(change(m.root, 'undo'));
  });

  it('a chord recorded in one widget does not fire in another on the same page', () => {
    const doc = fakeWidgetDocument();
    const a = make({}, doc);
    const b = make({}, doc);
    // The pointer rests over the first chart while the user records in the second.
    fire(a.root, 'pointerenter');
    openShortcutsPanel(b.w.context);
    change(b.root, 'tool:trend-line').click();
    fireKey(b.root.querySelector('.oac-keys-dialog') as FakeElement, 'h', { altKey: true, code: 'KeyH' });
    expect(b.root.querySelector('.oac-keys__conflict')).not.toBeNull();
    expect(a.w.draw.activeTool()).toBeNull();
    // Recording over, the first chart answers to its chords again.
    (b.root.querySelector('.oac-keys__conflict') as FakeElement).querySelectorAll('button')[0].click();
    b.w.context.overlays.closeAll();
    fireKey(a.chartEl, 'h', { altKey: true, code: 'KeyH' });
    expect(a.w.draw.activeTool()).toBe('horizontal-line');
  });

  it('lists the chords only when a host asks for no editing', () => {
    const m = make();
    openShortcutsPanel(m.w.context, { edit: false });
    expect(m.root.querySelector('.oac-keys__change')).toBeNull();
    expect(m.root.querySelector('.oac-keys-dialog .oac-dialog__foot')).toBeNull();
    expect(chordOf(m.root, 'undo')).toBe(m.w.context.keymap.format('Mod+Z'));
  });
});
