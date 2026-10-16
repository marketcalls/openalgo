/**
 * The drawing rail: what it builds from the tool registry, how a click, a
 * flyout pick, a chord and a double-click arm a tool, the controls block that
 * follows the controller, the roving keyboard, and the preferences that
 * survive a reload.
 */
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { registerIndicator, type Bar } from '../src/index';
import { hasDrawingTool, getDrawingTool } from '../src/draw/index';
import {
  createWidget, sanitizeRailPrefs, RAIL_GROUPS, RAIL_PREFS_KEY, STORAGE_PREFIX,
  type Widget, type WidgetOptions, type StorageLike, type RailGroup,
} from '../src/widget/index';
import { fakeWidgetDocument, fakeContainer, fireKey, fire, ensureWindowGlobal, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const DAY = 86400;
const T0 = 1700000000;
const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: T0 + i * DAY, open: c - 1, high: c + 2, low: c - 2, close: c, volume: 1000 };
});

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

interface Made { w: Widget; doc: FakeDocument; root: FakeElement; rail: FakeElement; chartEl: FakeElement }

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
  const rail = root.querySelector('.oac-rail') as FakeElement;
  rail.rect = { left: 0, top: 40, width: 42, height: 536 };
  const chartEl = root.querySelector('.oac-chart') as FakeElement;
  fire(root, 'pointerenter');
  return { w, doc, root, rail, chartEl };
}

const groupBtn = (rail: FakeElement, id: string): FakeElement => rail.querySelector(`.oac-rail__group[data-group="${id}"]`) as FakeElement;
const ctl = (rail: FakeElement, glyphClass: string): FakeElement => rail.querySelector(`.oac-rail__ctl .${glyphClass}`) as FakeElement;
const addLine = (w: Widget, price = 100): string =>
  w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price }], style: {}, paneIndex: 0 }).id;

describe('building the rail', () => {
  it('renders the cursor, one button per group that has registered tools, and the controls block', () => {
    const { rail, doc } = make();
    expect(rail.getAttribute('role')).toBe('toolbar');
    const tools = rail.querySelectorAll('.oac-rail__tool');
    expect(tools[0].dataset.tools).toBe('');
    const groups = rail.querySelectorAll('.oac-rail__group').map((b) => b.dataset.group);
    const expected = RAIL_GROUPS.filter((g) => g.id && (g.items ?? []).some((i) => i.tool && hasDrawingTool(i.tool))).map((g) => g.id);
    expect(groups).toEqual(expected);
    // Each group stands for its first tool and lists every registered one.
    const lines = groupBtn(rail, 'lines');
    expect(lines.dataset.face).toBe('trend-line');
    expect(lines.dataset.tools?.split(',')).toContain('horizontal-ray');
    expect(lines.getAttribute('aria-label')).toBe(getDrawingTool('trend-line').name);
    expect(rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn')).toHaveLength(8);
    // The sprite lives on the body, once, so a second widget's glyphs still resolve.
    expect(doc.body.children.filter((c) => c.id === 'oac-rail-sprite')).toHaveLength(1);
    make({}, doc);
    expect(doc.body.children.filter((c) => c.id === 'oac-rail-sprite')).toHaveLength(1);
  });

  it('restricts itself to the tools a host names and seeds the pins it asks for', () => {
    const { rail } = make({ rail: { tools: ['trend-line', 'rectangle'], favorites: ['rectangle', 'nonsense'] } });
    expect(rail.querySelectorAll('.oac-rail__group').map((b) => b.dataset.group)).toEqual(['lines', 'shapes']);
    expect(groupBtn(rail, 'lines').dataset.tools).toBe('trend-line');
    expect(rail.querySelectorAll('.oac-rail__fav').map((b) => b.dataset.tools)).toEqual(['rectangle']);
  });
});

describe('arming a tool', () => {
  it('a click on a group arms its face tool, and a second click on the armed tool opens the list', () => {
    const { w, rail, root, chartEl } = make();
    const lines = groupBtn(rail, 'lines');
    lines.click();
    expect(w.draw.activeTool()).toBe('trend-line');
    expect(lines.classList.contains('is-on')).toBe(true);
    expect(lines.getAttribute('aria-pressed')).toBe('true');
    expect(chartEl.style.getPropertyValue('--oac-tool-cursor')).toContain('data:image/svg+xml');
    expect(root.querySelector('.oac-fly')).toBeNull();
    lines.click();
    const fly = root.querySelector('.oac-fly') as FakeElement;
    expect(fly).not.toBeNull();
    expect(lines.getAttribute('aria-expanded')).toBe('true');
    expect(fly.querySelector('.oac-fly__row[aria-checked="true"]')?.dataset.tool).toBe('trend-line');
    // The cursor button drops the tool and the cursor property.
    (rail.querySelectorAll('.oac-rail__tool')[0]).click();
    expect(w.draw.activeTool()).toBeNull();
    expect(chartEl.style.getPropertyValue('--oac-tool-cursor')).toBe('');
  });

  it('the chevron opens the list for a press that went down on it, and a touch landing there picks the tool', () => {
    const { w, rail, root } = make();
    const lines = groupBtn(rail, 'lines');
    const chev = lines.querySelector('.oac-rail__chev') as FakeElement;
    // A mouse press on the chevron opens the list and leaves the tool alone.
    fire(chev, 'pointerdown', { pointerType: 'mouse' });
    fire(chev, 'click');
    expect(root.querySelector('.oac-fly')).not.toBeNull();
    expect(w.draw.activeTool()).toBeNull();
    fire(lines, 'pointerdown', { pointerType: 'mouse' });
    fire(lines, 'click');
    expect(root.querySelector('.oac-fly')).toBeNull();
    // A browser that moves a tap on the face onto the chevron delivers the
    // click there; the touch still means the face.
    fire(chev, 'pointerdown', { pointerType: 'touch' });
    fire(chev, 'click');
    expect(w.draw.activeTool()).toBe('trend-line');
    expect(root.querySelector('.oac-fly')).toBeNull();
    // A keyboard click after a press dragged off the chevron is not the chevron.
    (rail.querySelectorAll('.oac-rail__tool')[0]).click();
    fire(chev, 'pointerdown', { pointerType: 'mouse' });
    fire(chev, 'click', { detail: 0 });
    expect(w.draw.activeTool()).toBe('trend-line');
    expect(root.querySelector('.oac-fly')).toBeNull();
  });

  it('a flyout pick arms the tool, becomes the group face, and is remembered', () => {
    const store = new MemoryStorage();
    const { w, rail, root } = make({ persist: true, storage: store });
    const lines = groupBtn(rail, 'lines');
    fire(lines, 'contextmenu');
    const row = root.querySelector('.oac-fly__row[data-tool="vertical-line"]') as FakeElement;
    row.click();
    expect(w.draw.activeTool()).toBe('vertical-line');
    expect(lines.dataset.face).toBe('vertical-line');
    expect(root.querySelector('.oac-fly')).toBeNull();
    expect(w.getState().rail?.last.lines).toBe('vertical-line');
    const saved = JSON.parse(store.map.get(`${STORAGE_PREFIX}default:${RAIL_PREFS_KEY}`) as string);
    expect(saved.last.lines).toBe('vertical-line');
    // A later widget on the same store opens with that face.
    const again = make({ persist: true, storage: store });
    expect(groupBtn(again.rail, 'lines').dataset.face).toBe('vertical-line');
  });

  it('the star pins a tool above the groups, and the pinned button unpins from its menu', () => {
    const { rail, root } = make();
    fire(groupBtn(rail, 'shapes'), 'contextmenu');
    const star = root.querySelector('.oac-fly__row[data-tool="ellipse"] .oac-fly__star') as FakeElement;
    expect(star.getAttribute('aria-pressed')).toBe('false');
    expect(star.getAttribute('aria-label')).toBe('Pin to rail');
    star.click();
    expect(star.getAttribute('aria-pressed')).toBe('true');
    // One name, the pressed state saying it is pinned.
    expect(star.getAttribute('aria-label')).toBe('Pin to rail');
    expect(root.querySelector('.oac-fly')).not.toBeNull();   // pinning keeps the list open
    const fav = rail.querySelector('.oac-rail__fav') as FakeElement;
    expect(fav.dataset.tools).toBe('ellipse');
    // Not the name of the group button that may show the same tool.
    expect(fav.getAttribute('aria-label')).toBe('Ellipse (pinned)');
    fire(root.ownerDocument.body, 'pointerdown');
    fire(fav, 'contextmenu');
    const unpin = root.querySelector('.oac-menu .oac-menu__row') as FakeElement;
    expect(unpin.textContent).toBe('Unpin from rail');
    unpin.click();
    expect(rail.querySelector('.oac-rail__fav')).toBeNull();
  });

  it('a double-click holds the tool until Escape; the rail shows the hold', () => {
    const { w, rail, chartEl } = make();
    const lines = groupBtn(rail, 'lines');
    fire(lines, 'click', { detail: 2 });
    expect(w.draw.activeTool()).toBe('trend-line');
    expect(lines.classList.contains('is-held')).toBe(true);
    const setOptions = vi.spyOn(w.draw, 'setOptions');
    fireKey(chartEl, 'Escape');
    expect(w.draw.activeTool()).toBeNull();
    expect(lines.classList.contains('is-held')).toBe(false);
    expect(setOptions).toHaveBeenCalledWith({ stayInDrawingMode: false });
  });

  it('follows a tool armed from code or a chord through the controller event', () => {
    const { w, rail, chartEl } = make();
    w.draw.setTool('fib-retracement');
    const fib = groupBtn(rail, 'fib');
    expect(fib.classList.contains('is-on')).toBe(true);
    expect(fib.dataset.face).toBe('fib-retracement');
    fireKey(chartEl, 'h', { altKey: true });
    expect(w.draw.activeTool()).toBe('horizontal-line');
    expect(fib.classList.contains('is-on')).toBe(false);
    expect(groupBtn(rail, 'lines').dataset.face).toBe('horizontal-line');
  });
});

describe('the controls block', () => {
  it('cycles the magnet through off, weak and strong and the controller follows', () => {
    const { w, rail, root } = make();
    const magnet = ctl(rail, 'oac-rail__btn--magnet');
    expect(w.draw.magnetMode()).toBe('off');
    magnet.click();
    expect(w.draw.magnetMode()).toBe('weak');
    expect(magnet.dataset.mode).toBe('weak');
    expect(magnet.classList.contains('is-weak')).toBe(true);
    // It snaps to study values as well as to the bar, and says so.
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('Magnet weak: snaps when a bar or study value is within a few pixels');
    magnet.click();
    expect(w.draw.magnetMode()).toBe('strong');
    expect(magnet.classList.contains('is-on')).toBe(true);
    magnet.click();
    expect(w.draw.magnetMode()).toBe('off');
    expect(magnet.getAttribute('aria-pressed')).toBe('false');
    expect(w.getState().rail?.magnet).toBe('off');
  });

  it('the stay toggle changes the controller option and is remembered', () => {
    const { w, rail } = make();
    const setOptions = vi.spyOn(w.draw, 'setOptions');
    const stay = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[1];
    stay.click();
    expect(setOptions).toHaveBeenCalledWith({ stayInDrawingMode: true });
    expect(stay.getAttribute('aria-pressed')).toBe('true');
    expect(w.getState().rail?.stay).toBe(true);
    stay.click();
    expect(setOptions).toHaveBeenLastCalledWith({ stayInDrawingMode: false });
  });

  it('lock, hide and delete are off without a selection and act on it when there is one', () => {
    const { w, rail } = make();
    const [, , lock, eye, trash] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    for (const b of [lock, eye, trash]) expect(b.classList.contains('is-off')).toBe(true);
    const id = addLine(w);
    w.draw.select(id);
    for (const b of [lock, eye, trash]) expect(b.classList.contains('is-off')).toBe(false);
    lock.click();
    expect(w.draw.get(id)?.locked).toBe(true);
    // The glyph shows the state, as the eye beside it does; the name stays and the pressed state says locked.
    expect(lock.dataset.glyph).toBe('lock');
    expect(lock.getAttribute('aria-label')).toBe('Lock drawing');
    expect(lock.getAttribute('aria-pressed')).toBe('true');
    lock.click();
    expect(w.draw.get(id)?.locked).toBe(false);
    expect(lock.dataset.glyph).toBe('unlock');
    expect(lock.getAttribute('aria-pressed')).toBe('false');
    eye.click();
    expect(w.draw.get(id)?.visible).toBe(false);
    expect(eye.dataset.glyph).toBe('eye-off');
    expect(eye.getAttribute('aria-label')).toBe('Hide drawing');
    expect(eye.getAttribute('aria-pressed')).toBe('true');
    trash.click();
    expect(w.draw.drawings()).toHaveLength(0);
    expect(trash.classList.contains('is-off')).toBe(true);
  });

  it('keeps a locked selection from the trash, as the drawing toolbar and the menu do', () => {
    const { w, rail } = make();
    const [, , lock, , trash] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    const id = addLine(w);
    w.draw.select(id);
    lock.click();
    expect(trash.getAttribute('aria-disabled')).toBe('true');
    trash.click();
    expect(w.draw.get(id)).toBeDefined();
  });

  it('undo and redo follow the history', () => {
    const { w, rail } = make();
    const [, , , , , undo, redo] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    expect(undo.classList.contains('is-off')).toBe(true);
    addLine(w);
    expect(undo.classList.contains('is-off')).toBe(false);
    undo.click();
    expect(w.draw.drawings()).toHaveLength(0);
    expect(redo.classList.contains('is-off')).toBe(false);
    redo.click();
    expect(w.draw.drawings()).toHaveLength(1);
  });

  it('undo and redo take back a dragged study anchor, and the buttons follow it', () => {
    const { w, rail } = make();
    registerIndicator({ id: 'rail-anchor-study', name: 'Anchored', placement: 'onchart', inputs: [
      { key: 'at', type: 'timestamp', label: 'Anchor time', default: T0 + 5 * DAY, pick: true },
      { key: 'level', type: 'price', label: 'Anchor price', default: 100, pick: true, timeKey: 'at', anchor: true },
    ], plots: [{ key: 'v', title: 'Level', type: 'line' }], calc: bs => ({ v: bs.map(() => 100) }) });
    const study = w.chart.addIndicator('rail-anchor-study');
    const [, , , , , undo, redo] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    expect(undo.classList.contains('is-off')).toBe(true);
    const id = `input-anchor:${study.id}:level`;
    w.chart.emit('drag:start', { id, time: T0 + 5 * DAY, price: 100, paneIndex: 0 });
    w.chart.emit('drag', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    w.chart.emit('drag:end', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });
    expect(undo.classList.contains('is-off')).toBe(false);
    undo.click();
    expect(study.settings()).toMatchObject({ at: T0 + 5 * DAY, level: 100 });
    expect(redo.classList.contains('is-off')).toBe(false);
    redo.click();
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });
  });

  it('right-click on delete offers select all and remove all with their counts', () => {
    const { w, rail, root } = make();
    const trash = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[4];
    fire(trash, 'contextmenu');
    let rows = root.querySelectorAll('.oac-menu .oac-menu__row');
    expect(rows.map((r) => r.textContent)).toEqual(['Select all (0)', 'Remove all drawings (0)']);
    expect(rows[1].getAttribute('aria-disabled')).toBe('true');
    rows[1].click();
    expect(root.querySelector('.oac-menu')).not.toBeNull();   // a disabled row does nothing
    fire(root.ownerDocument.body, 'pointerdown');
    addLine(w, 100);
    addLine(w, 101);
    fire(trash, 'contextmenu');
    rows = root.querySelectorAll('.oac-menu .oac-menu__row');
    expect(rows[0].textContent).toBe('Select all (2)');
    rows[0].click();
    expect(w.draw.selection()).toHaveLength(2);
    fire(trash, 'contextmenu');
    root.querySelectorAll('.oac-menu .oac-menu__row')[1].click();
    expect(w.draw.drawings()).toHaveLength(0);
    expect(w.draw.canUndo()).toBe(true);
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('Removed 2 drawings');
  });

  it('walks its right-click menus with the arrows, as every other menu in the chrome is walked', () => {
    const { w, rail, root, doc } = make();
    addLine(w, 100);
    const trash = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[4];
    fire(trash, 'contextmenu');
    const menu = root.querySelector('.oac-menu') as FakeElement;
    const rows = root.querySelectorAll('.oac-menu .oac-menu__row');
    expect(doc.activeElement).toBe(rows[0]);
    fireKey(menu, 'ArrowDown');
    expect(doc.activeElement).toBe(rows[1]);
    fireKey(menu, 'ArrowDown');
    expect(doc.activeElement).toBe(rows[0]);
    fireKey(menu, 'ArrowUp');
    expect(doc.activeElement).toBe(rows[1]);
  });
});

describe('keyboard', () => {
  it('walks the buttons with the arrows on one tab stop, opens a group on ArrowRight, and Escape returns to the chart', () => {
    const { rail, root, doc, chartEl } = make();
    const buttons = rail.querySelectorAll('.oac-rail__btn');
    buttons[0].focus();
    expect(buttons[0].tabIndex).toBe(0);
    fireKey(buttons[0], 'ArrowDown');
    expect(doc.activeElement).toBe(buttons[1]);
    expect(buttons[0].tabIndex).toBe(-1);
    expect(buttons[1].tabIndex).toBe(0);
    fireKey(buttons[1], 'ArrowUp');
    expect(doc.activeElement).toBe(buttons[0]);
    fireKey(buttons[0], 'ArrowUp');
    expect(doc.activeElement).toBe(buttons[buttons.length - 1]);
    fireKey(buttons[buttons.length - 1], 'Home');
    expect(doc.activeElement).toBe(buttons[0]);
    const lines = groupBtn(rail, 'lines');
    lines.focus();
    fireKey(lines, 'ArrowRight');
    const fly = root.querySelector('.oac-fly') as FakeElement;
    expect(fly).not.toBeNull();
    expect((doc.activeElement as FakeElement).classList.contains('oac-fly__row')).toBe(true);
    fireKey(doc.activeElement, 'ArrowDown');
    expect((doc.activeElement as FakeElement).dataset.tool).toBe('ray');
    fireKey(doc.activeElement, 'Escape');
    expect(root.querySelector('.oac-fly')).toBeNull();
    expect(doc.activeElement).toBe(lines);
    fireKey(lines, 'Escape');
    expect(doc.activeElement).toBe(chartEl);
  });

  it('the rail arrows never nudge a selected drawing while the rail has focus', () => {
    const { w, rail } = make();
    const id = addLine(w);
    w.draw.select(id);
    const before = w.draw.get(id)?.points[0].price;
    const buttons = rail.querySelectorAll('.oac-rail__btn');
    buttons[0].focus();
    fireKey(buttons[0], 'ArrowDown');
    expect(w.draw.get(id)?.points[0].price).toBe(before);
  });
});

describe('tooltips', () => {
  it('shows a control label after the pointer has rested, reading the spec at show time', () => {
    vi.useFakeTimers();
    try {
      const { w, rail, root } = make();
      const magnet = ctl(rail, 'oac-rail__btn--magnet');
      magnet.rect = { left: 5, top: 400, width: 32, height: 32 };
      fire(magnet, 'pointerenter');
      expect(root.querySelector('.oac-tip')).toBeNull();
      vi.advanceTimersByTime(700);
      const tip = root.querySelector('.oac-tip') as FakeElement;
      expect(tip.classList.contains('is-on')).toBe(true);
      expect(tip.textContent).toContain('Magnet: off');
      expect(w.context.tips.target()).toBe(magnet);
      // Beside the button, to its right, inside the widget.
      expect(Number.parseFloat(tip.style.left as string)).toBeGreaterThan(37);
      fire(magnet, 'pointerleave');
      expect(tip.classList.contains('is-on')).toBe(false);
      magnet.click();
      fire(magnet, 'pointerenter');
      vi.advanceTimersByTime(700);
      expect(tip.textContent).toContain('Magnet: weak');
      // A press takes the label down: the user has decided.
      fire(magnet, 'pointerdown');
      expect(tip.classList.contains('is-on')).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('preferences', () => {
  it('sanitizeRailPrefs keeps what this build can honour and drops the rest', () => {
    const toolsOf = (g: RailGroup): string[] => (g.items ?? []).filter((i) => i.tool && hasDrawingTool(i.tool)).map((i) => i.tool as string);
    const prefs = sanitizeRailPrefs({
      favorites: ['rectangle', 'rectangle', 'no-such-tool', 42],
      magnet: 'sideways',
      stay: 'yes',
      last: { lines: 'rectangle', shapes: 'circle', nope: 'trend-line' },
    }, RAIL_GROUPS, toolsOf);
    expect(prefs).toEqual({ favorites: ['rectangle'], magnet: 'off', stay: false, last: { shapes: 'circle' } });
    expect(sanitizeRailPrefs(null, RAIL_GROUPS, toolsOf)).toEqual({ favorites: [], magnet: 'off', stay: false, last: {} });
    expect(sanitizeRailPrefs({ magnet: 'weak', stay: true }, RAIL_GROUPS, toolsOf)).toMatchObject({ magnet: 'weak', stay: true });
    // Folded only for a stored true: a truthy string is not a choice anyone made.
    expect(sanitizeRailPrefs({ collapsed: true }, RAIL_GROUPS, toolsOf).collapsed).toBe(true);
    expect(sanitizeRailPrefs({ collapsed: 'yes' }, RAIL_GROUPS, toolsOf)).not.toHaveProperty('collapsed');
  });

  it('a restored state re-applies the pins and the magnet', () => {
    const a = make();
    a.w.context.overlays.closeAll();
    (a.rail.querySelector('.oac-rail__ctl .oac-rail__btn--magnet') as FakeElement).click();
    fire(groupBtn(a.rail, 'shapes'), 'contextmenu');
    (a.root.querySelector('.oac-fly__row[data-tool="circle"] .oac-fly__star') as FakeElement).click();
    const state = a.w.getState();
    const b = make();
    b.w.restoreState(state);
    expect(b.w.draw.magnetMode()).toBe('weak');
    expect(b.rail.querySelectorAll('.oac-rail__fav').map((f) => f.dataset.tools)).toEqual(['circle']);
  });
});

describe('folding the rail', () => {
  const tabOf = (root: FakeElement): FakeElement => root.querySelector('.oac-rail-tab') as FakeElement;
  const fold = (rail: FakeElement): void => { ctl(rail, 'oac-rail__collapse').click(); };

  it('folds behind a tab at the chart edge and comes back from it', () => {
    const { doc, root, rail } = make();
    const tab = tabOf(root);
    expect(tab).toBeTruthy();
    expect(tab.hidden).toBe(true);
    expect(rail.classList.contains('is-collapsed')).toBe(false);
    const button = ctl(rail, 'oac-rail__collapse');
    button.focus();
    button.click();
    expect(rail.classList.contains('is-collapsed')).toBe(true);
    expect(tab.hidden).toBe(false);
    // The pressed button is gone, so focus lands on the control that replaced it.
    expect(doc.activeElement).toBe(tab);
    tab.click();
    expect(rail.classList.contains('is-collapsed')).toBe(false);
    expect(tab.hidden).toBe(true);
    expect(doc.activeElement).toBe(ctl(rail, 'oac-rail__collapse'));
  });

  it('closes an open group list as it folds, and keeps the tab out of the chart pointer', () => {
    const { root, rail } = make();
    fire(groupBtn(rail, 'shapes'), 'contextmenu');
    expect(root.querySelector('.oac-fly')).toBeTruthy();
    fold(rail);
    expect(root.querySelector('.oac-fly')).toBeFalsy();
    const down = vi.fn();
    root.addEventListener('pointerdown', down);
    fire(tabOf(root), 'pointerdown');
    expect(down).not.toHaveBeenCalled();
  });

  it('remembers the fold across a reload and through a saved state', () => {
    const storage = new MemoryStorage();
    const a = make({ persist: true, storage });
    fold(a.rail);
    const b = make({ persist: true, storage });
    expect(b.rail.classList.contains('is-collapsed')).toBe(true);
    expect(tabOf(b.root).hidden).toBe(false);
    const state = a.w.getState();
    const c = make();
    expect(c.rail.classList.contains('is-collapsed')).toBe(false);
    c.w.restoreState(state);
    expect(c.rail.classList.contains('is-collapsed')).toBe(true);
    expect(tabOf(c.root).hidden).toBe(false);
  });
});
