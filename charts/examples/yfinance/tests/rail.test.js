// The drawing rail: built on the tier's sprite, driven by the controller's
// public API, with the keyboard the tier answers for and the pins, magnet
// and stay modes the rail keeps between visits. Runs against a small fake
// DOM (rail-dom.js) and a fake controller, so every claim here is about
// what the rail asks of the engine, not about pixels.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { railPage, pressKey, clickOn, pointer, FakeEvent } from './rail-dom.js';
import { fakeStorage } from './helpers.js';
import {
  initRail, buildRail, syncRail, armCursor, setDrawLock, setMagnetMode, cycleMagnet, magnetMode,
  setStayMode, stayMode, toggleFavorite, favorites, railPrefs, RAIL_PREFS_KEY, RAIL_GROUPS,
  setRailCollapsed, railCollapsed,
  showWidget, positionWidget, openTextDialog, refreshControls,
} from '../src/rail.js';
import {
  closeFlyout, flyoutOpen, flyoutEl, closeRailMenu, hideRailTip, railTipTarget,
  placeBeside, placeTip, TIP_DWELL_MS,
} from '../src/rail-flyout.js';
import { toolCursor, ICON_SYMBOL_PREFIX } from '/dist/openalgo-charts.draw.mjs';

function fakeDraw() {
  const calls = [];
  const state = { tool: null, opts: {}, selection: [], drawings: [], undo: 0, redo: 0, hovered: null };
  const d = {
    calls, state,
    setTool(t) { state.tool = t; calls.push(['setTool', t]); },
    activeTool: () => state.tool,
    setOptions(p) { Object.assign(state.opts, p); calls.push(['setOptions', { ...p }]); },
    magnetMode: () => state.opts.magnet || 'off',
    selected: () => state.selection[0] || null,
    selection: () => state.selection,
    select(ids) { state.selection = Array.isArray(ids) ? ids.slice() : ids ? [ids] : []; calls.push(['select', state.selection.slice()]); },
    hovered: () => state.hovered,
    get: (id) => state.drawings.find((x) => x.id === id),
    drawings: () => state.drawings,
    update(id, patch) { Object.assign(d.get(id), patch); calls.push(['update', id, patch]); return true; },
    remove(id) {
      state.drawings = state.drawings.filter((x) => x.id !== id);
      state.selection = state.selection.filter((x) => x !== id);
      calls.push(['remove', id]);
      return true;
    },
    clear() { state.drawings = []; state.selection = []; calls.push(['clear']); },
    undo() { calls.push(['undo']); return true; },
    redo() { calls.push(['redo']); return true; },
    canUndo: () => state.undo > 0,
    canRedo: () => state.redo > 0,
    duplicate(ids) { calls.push(['duplicate', ids.slice()]); return []; },
    nudge(ids, dx, dy) { calls.push(['nudge', ids.slice(), dx, dy]); },
    cancel() { calls.push(['cancel']); const had = state.tool !== null; state.tool = null; return had; },
    finish() { calls.push(['finish']); return true; },
    popAnchor() { calls.push(['popAnchor']); return true; },
  };
  return d;
}

function fakeChart() {
  const handlers = {};
  return {
    on(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); return () => {}; },
    emit(ev, p) { for (const fn of handlers[ev] || []) fn(p); },
    handlers,
  };
}

const names = (calls, name) => calls.filter((c) => c[0] === name);
const railButtons = (page) => page.rail.querySelectorAll('.rail__btn');
const toolButtons = (page) => page.rail.querySelectorAll('.rail__tool');
const groupButton = (page, id) => page.rail.querySelector(`[data-group="${id}"]`);
const useIds = (node) => node.querySelectorAll('use').map((u) => u.getAttribute('href'));

let page;
let app;
let store;

function setup(opts = {}) {
  page = railPage();
  store = fakeStorage();
  if (opts.prefs) store.set(RAIL_PREFS_KEY, JSON.stringify(opts.prefs));
  app = { draw: fakeDraw(), draw2: null, chart: fakeChart(), focusPane: 1, shortcuts: {} };
  initRail(app, opts.init || {});
  buildRail();
  return app.draw;
}

beforeEach(() => { vi.useRealTimers(); });
afterEach(() => { closeFlyout(); closeRailMenu(); hideRailTip(); });

describe('sprite and glyphs', () => {
  it('injects the sprite once and draws every tool button and flyout row through <use>', () => {
    setup();
    const sprites = () => page.doc.body.all().filter((n) => n.id === 'oac-rail-sprite');
    expect(sprites()).toHaveLength(1);
    const symbols = sprites()[0].querySelectorAll('symbol').map((s) => s.getAttribute('id'));
    expect(symbols).toContain(ICON_SYMBOL_PREFIX + 'trend-line');
    // A rebuild (the drawing module calls buildRail again once the tier has answered) adds no second sprite.
    buildRail();
    expect(sprites()).toHaveLength(1);
    expect(page.doc.head.all().filter((n) => n.id === 'oac-rail-css')).toHaveLength(1);

    for (const b of toolButtons(page)) {
      const refs = useIds(b);
      expect(refs, b.getAttribute('aria-label')).toHaveLength(1);
      expect(refs[0].startsWith('#' + ICON_SYMBOL_PREFIX)).toBe(true);
      expect(symbols).toContain(refs[0].slice(1));
    }
    // No native control anywhere on the rail.
    expect(page.rail.querySelectorAll('select')).toHaveLength(0);
    expect(page.rail.querySelectorAll('input')).toHaveLength(0);

    clickOn(groupButton(page, 'lines'), { from: groupButton(page, 'lines').querySelector('.rail__chev') });
    const rows = flyoutEl().querySelectorAll('.fly__row');
    expect(rows.length).toBe(10);
    for (const r of rows) expect(useIds(r.querySelector('.fly__glyph'))).toEqual(['#' + ICON_SYMBOL_PREFIX + r.dataset.tool]);
  });

  it('lists every group tool that the tier registers, named from the descriptor', () => {
    setup();
    const listed = RAIL_GROUPS.filter((g) => g.items).flatMap((g) => g.items.filter((i) => i.tool).map((i) => i.tool));
    expect(new Set(listed).size).toBe(listed.length);
    for (const g of RAIL_GROUPS.filter((x) => x.items)) expect(groupButton(page, g.id), g.id).not.toBeNull();
    clickOn(groupButton(page, 'lines'), { from: groupButton(page, 'lines').querySelector('.rail__chev') });
    const row = flyoutEl().querySelector('[data-tool="trend-line"]');
    expect(row.querySelector('.fly__name').textContent).toBe('Trend Line');
  });
});

describe('arming tools', () => {
  it('a group button arms its last-used tool, aria-pressed follows, and the cursor button disarms', () => {
    const d = setup();
    const lines = groupButton(page, 'lines');
    clickOn(lines);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'trend-line']);
    expect(lines.getAttribute('aria-pressed')).toBe('true');
    expect(lines.classList.contains('is-on')).toBe(true);
    const cursor = toolButtons(page)[0];
    expect(cursor.getAttribute('aria-pressed')).toBe('false');
    clickOn(cursor);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', null]);
    expect(cursor.getAttribute('aria-pressed')).toBe('true');
    expect(lines.getAttribute('aria-pressed')).toBe('false');
    // The legacy picker mirrors the armed tool, so a saved layout still reads it.
    expect(page.drawtool.value).toBe('');
  });

  it('the chevron opens the flyout, a row pick arms it and becomes the group face', () => {
    const d = setup();
    const lines = groupButton(page, 'lines');
    expect(lines.getAttribute('aria-expanded')).toBe('false');
    clickOn(lines, { from: lines.querySelector('.rail__chev') });
    expect(flyoutOpen()).toBe(true);
    expect(lines.getAttribute('aria-expanded')).toBe('true');
    expect(names(d.calls, 'setTool')).toHaveLength(0);
    const ray = flyoutEl().querySelector('[data-tool="ray"]');
    ray.dispatchEvent(new FakeEvent('click', { detail: 1 }));
    expect(flyoutOpen()).toBe(false);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'ray']);
    expect(useIds(lines.querySelector('.rail__glyph'))).toEqual(['#' + ICON_SYMBOL_PREFIX + 'ray']);
    expect(lines.getAttribute('aria-label')).toBe('Ray');
    expect(railPrefs().last.lines).toBe('ray');
    expect(JSON.parse(store.get(RAIL_PREFS_KEY)).last.lines).toBe('ray');
    // Next plain click arms the remembered tool without opening anything.
    d.state.tool = null;
    clickOn(lines);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'ray']);
    expect(flyoutOpen()).toBe(false);
  });

  it('a chord arms through the tier and the group remembers it', () => {
    const d = setup();
    const ev = pressKey('h', { altKey: true });
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'horizontal-line']);
    expect(ev.defaultPrevented).toBe(true);
    expect(ev.propagationStopped).toBe(true);
    expect(useIds(groupButton(page, 'lines').querySelector('.rail__glyph'))).toEqual(['#' + ICON_SYMBOL_PREFIX + 'horizontal-line']);
    // A bare letter is never a chord.
    pressKey('h');
    expect(names(d.calls, 'setTool')).toHaveLength(1);
  });

  it('the flyout shows the descriptor chord at the row edge', () => {
    setup();
    const lines = groupButton(page, 'lines');
    clickOn(lines, { from: lines.querySelector('.rail__chev') });
    const row = flyoutEl().querySelector('[data-tool="trend-line"]');
    expect(row.children[row.children.length - 1].tagName).toBe('KBD');
    expect(row.querySelector('.fly__chord').textContent).toBe('Alt+T');
    expect(flyoutEl().querySelector('[data-tool="ray"] .fly__chord').textContent).toBe('');
  });

  it('arming sets the tool cursor on the chart box through the custom property', () => {
    setup();
    armCursor(page.chart, 'trend-line');
    expect(page.chart.style.getPropertyValue('--tool-cursor')).toBe(toolCursor('trend-line'));
    expect(page.chart.style.getPropertyValue('--tool-cursor')).toMatch(/^url\("data:image\/svg\+xml,/);
    armCursor(page.chart, null);
    expect(page.chart.style.getPropertyValue('--tool-cursor')).toBe('');
  });
});

describe('favorites', () => {
  it('the star pins a tool to the rail and the pin survives a reload', () => {
    const d = setup();
    const lines = groupButton(page, 'lines');
    clickOn(lines, { from: lines.querySelector('.rail__chev') });
    const star = flyoutEl().querySelector('[data-tool="ray"] .fly__star');
    expect(star.getAttribute('aria-pressed')).toBe('false');
    star.dispatchEvent(new FakeEvent('click', { detail: 1 }));
    expect(star.getAttribute('aria-pressed')).toBe('true');
    expect(favorites()).toEqual(['ray']);
    expect(JSON.parse(store.get(RAIL_PREFS_KEY)).favorites).toEqual(['ray']);
    // Pinned tools sit on the rail as their own buttons, before the groups.
    const fav = page.rail.querySelector('.rail__fav');
    expect(fav.dataset.tools).toBe('ray');
    expect(toolButtons(page).indexOf(fav)).toBe(1);
    clickOn(fav);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'ray']);
    // The flyout stayed open through the pin, still anchored to the same button.
    expect(flyoutOpen()).toBe(true);
    closeFlyout();

    // A fresh page reads the pin back; a pin to an unknown tool is dropped.
    const saved = JSON.parse(store.get(RAIL_PREFS_KEY));
    saved.favorites.push('no-such-tool');
    setup({ prefs: saved });
    expect(favorites()).toEqual(['ray']);
    expect(page.rail.querySelectorAll('.rail__fav')).toHaveLength(1);
    toggleFavorite('ray', false);
    expect(page.rail.querySelectorAll('.rail__fav')).toHaveLength(0);
  });
});

describe('magnet and stay', () => {
  it('the magnet cycles off, weak, strong and the mode reaches the controller and the store', () => {
    const d = setup();
    const magnet = page.rail.querySelector('.rail__btn--magnet');
    expect(magnetMode()).toBe('off');
    expect(d.state.opts.magnet).toBe('off');
    clickOn(magnet);
    expect(magnetMode()).toBe('weak');
    expect(d.state.opts.magnet).toBe('weak');
    expect(magnet.dataset.mode).toBe('weak');
    expect(magnet.classList.contains('is-weak')).toBe(true);
    expect(page.magnet.checked).toBe(true);
    clickOn(magnet);
    expect(magnetMode()).toBe('strong');
    expect(magnet.classList.contains('is-on')).toBe(true);
    expect(magnet.getAttribute('aria-pressed')).toBe('true');
    clickOn(magnet);
    expect(magnetMode()).toBe('off');
    expect(page.magnet.checked).toBe(false);
    expect(magnet.getAttribute('aria-pressed')).toBe('false');
    cycleMagnet();
    expect(JSON.parse(store.get(RAIL_PREFS_KEY)).magnet).toBe('weak');
    expect(() => setMagnetMode('sideways')).toThrow();
  });

  it('a rebuilt controller gets the rail modes back', () => {
    setup({ prefs: { magnet: 'weak', stay: true } });
    expect(app.draw.state.opts).toEqual({ magnet: 'weak', stayInDrawingMode: true });
    // A chart-type switch: the drawing module builds a fresh controller from
    // the legacy checkbox and resyncs the rail, which is where the modes go back on.
    app.draw = fakeDraw();
    app.draw.setOptions({ magnet: 'strong', stayInDrawingMode: false });
    syncRail(null);
    expect(app.draw.state.opts).toEqual({ magnet: 'weak', stayInDrawingMode: true });
  });

  it('stay is a mode the toggle owns; the double-click hold is separate and Escape clears only the hold', () => {
    const d = setup();
    const stay = railButtons(page).find((b) => b.getAttribute('aria-label') === 'Keep tool active');
    expect(stayMode()).toBe(false);
    clickOn(stay);
    expect(stayMode()).toBe(true);
    expect(stay.getAttribute('aria-pressed')).toBe('true');
    expect(d.state.opts.stayInDrawingMode).toBe(true);
    expect(JSON.parse(store.get(RAIL_PREFS_KEY)).stay).toBe(true);
    // What the drawing module does on Escape: release the hold. The mode stays.
    setDrawLock(false);
    expect(d.state.opts.stayInDrawingMode).toBe(true);
    expect(stayMode()).toBe(true);
    setStayMode(false);
    expect(d.state.opts.stayInDrawingMode).toBe(false);
    // The hold: a double-click on a group keeps that tool until something leaves it.
    clickOn(groupButton(page, 'lines'), { detail: 2 });
    expect(d.state.opts.stayInDrawingMode).toBe(true);
    expect(groupButton(page, 'lines').classList.contains('is-held')).toBe(true);
    expect(page.status.textContent).toMatch(/stays active until Escape/);
    setDrawLock(false);
    expect(d.state.opts.stayInDrawingMode).toBe(false);
    expect(groupButton(page, 'lines').classList.contains('is-held')).toBe(false);
  });

  it('the split chart follows both modes', () => {
    setup();
    app.draw2 = fakeDraw();
    setMagnetMode('strong');
    setStayMode(true);
    expect(app.draw2.state.opts).toEqual({ magnet: 'strong', stayInDrawingMode: true });
  });

  it('the shell bar toggling the legacy checkbox moves the rail mode with it', () => {
    setup();
    page.magnet.checked = true;
    page.magnet.dispatchEvent(new FakeEvent('change'));
    expect(magnetMode()).toBe('strong');
    setMagnetMode('weak');
    page.magnet.dispatchEvent(new FakeEvent('change'));   // still checked: weak is kept
    expect(magnetMode()).toBe('weak');
    page.magnet.checked = false;
    page.magnet.dispatchEvent(new FakeEvent('change'));
    expect(magnetMode()).toBe('off');
  });
});

describe('the eraser and the ruler', () => {
  /** The fake controller, with the eraser and the ruler the rail reads. */
  const withGestures = (d) => {
    d.state.erasing = false;
    d.state.measuring = false;
    d.erasing = () => d.state.erasing;
    d.measuring = () => d.state.measuring;
    d.setEraser = (on) => { d.state.erasing = on; d.calls.push(['setEraser', on]); app.chart.emit('draw:eraser', { active: on }); };
    return d;
  };

  it('the eraser button turns the mode on and off, and the cursor button stands against it', () => {
    const d = withGestures(setup());
    buildRail();
    const eraser = page.rail.querySelector('.rail__btn--eraser');
    const cursor = toolButtons(page)[0];
    expect(eraser.getAttribute('aria-pressed')).toBe('false');
    expect(cursor.getAttribute('aria-pressed')).toBe('true');
    clickOn(eraser);
    expect(names(d.calls, 'setEraser')).toEqual([['setEraser', true]]);
    expect(eraser.getAttribute('aria-pressed')).toBe('true');
    expect(eraser.classList.contains('is-on')).toBe(true);
    expect(cursor.getAttribute('aria-pressed')).toBe('false');
    clickOn(eraser);
    expect(d.state.erasing).toBe(false);
    expect(eraser.getAttribute('aria-pressed')).toBe('false');
    expect(cursor.getAttribute('aria-pressed')).toBe('true');
  });

  it('Escape reaches cancel() while the eraser or a ruler is up, and not otherwise', () => {
    const d = withGestures(setup());
    d.state.erasing = true;
    pressKey('Escape');
    expect(names(d.calls, 'cancel')).toHaveLength(1);
    d.state.erasing = false;
    d.state.measuring = true;
    pressKey('Escape');
    expect(names(d.calls, 'cancel')).toHaveLength(2);
    d.state.measuring = false;
    pressKey('Escape');
    expect(names(d.calls, 'cancel')).toHaveLength(2);
  });
});

describe('selection controls', () => {
  const byLabel = (label) => railButtons(page).find((b) => b.getAttribute('aria-label') === label);

  it('lock, eye and trash are inert with nothing selected and act on the whole selection', () => {
    const d = setup();
    const lock = byLabel('Lock drawing');
    const eye = byLabel('Hide drawing');
    const trash = byLabel('Delete drawing');
    for (const b of [lock, eye, trash]) {
      expect(b.classList.contains('is-off')).toBe(true);
      expect(b.getAttribute('aria-disabled')).toBe('true');
    }
    clickOn(trash);
    expect(names(d.calls, 'remove')).toHaveLength(0);

    d.state.drawings = [{ id: 'a', tool: 'trend-line' }, { id: 'b', tool: 'ray' }];
    d.select(['a', 'b']);
    app.chart.emit('drawing:select', { ids: ['a', 'b'] });
    for (const b of [lock, eye, trash]) expect(b.classList.contains('is-off')).toBe(false);

    clickOn(lock);
    expect(names(d.calls, 'update')).toEqual([['update', 'a', { locked: true }], ['update', 'b', { locked: true }]]);
    expect(lock.getAttribute('aria-pressed')).toBe('true');
    expect(useIds(lock)).toHaveLength(0);   // chrome glyphs are inline, not sprite
    // The closed padlock while locked, as every other surface shows it; one name throughout.
    expect(lock.dataset.glyph).toBe('lock');
    expect(lock.getAttribute('aria-label')).toBe('Lock drawing');
    clickOn(lock);
    expect(names(d.calls, 'update').pop()).toEqual(['update', 'b', { locked: false }]);
    expect(lock.dataset.glyph).toBe('unlock');

    clickOn(eye);
    expect(names(d.calls, 'update').pop()).toEqual(['update', 'b', { visible: false }]);
    expect(eye.dataset.glyph).toBe('eye-off');
    expect(eye.getAttribute('aria-pressed')).toBe('true');
    clickOn(eye);
    expect(names(d.calls, 'update').pop()).toEqual(['update', 'b', { visible: true }]);

    clickOn(byLabel('Delete 2 drawings'));
    expect(names(d.calls, 'remove').map((c) => c[1])).toEqual(['a', 'b']);
    expect(trash.classList.contains('is-off')).toBe(true);
  });

  it('undo and redo follow the history and the trash menu selects or removes everything', () => {
    const d = setup();
    const undo = byLabel('Undo');
    const redo = byLabel('Redo');
    expect(undo.classList.contains('is-off')).toBe(true);
    clickOn(undo);
    expect(names(d.calls, 'undo')).toHaveLength(0);
    d.state.undo = 1;
    app.chart.emit('draw:add', {});
    expect(undo.classList.contains('is-off')).toBe(false);
    expect(redo.classList.contains('is-off')).toBe(true);
    clickOn(undo);
    expect(names(d.calls, 'undo')).toHaveLength(1);

    // With nothing drawn the menu still says what it would do, disabled.
    const trash = byLabel('Delete drawing');
    trash.dispatchEvent(new FakeEvent('contextmenu'));
    const empty = page.doc.body.querySelectorAll('.rail-menu button');
    expect(empty.map((r) => r.textContent)).toEqual(['Select all (0)', 'Remove all drawings (0)']);
    expect(empty.map((r) => r.getAttribute('aria-disabled'))).toEqual(['true', 'true']);
    empty[1].dispatchEvent(new FakeEvent('click'));
    expect(names(d.calls, 'clear')).toHaveLength(0);
    expect(page.doc.body.querySelector('.rail-menu')).not.toBeNull();   // an inert row does not dismiss the menu
    closeRailMenu();

    d.state.drawings = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    trash.dispatchEvent(new FakeEvent('contextmenu'));
    const menu = page.doc.body.querySelector('.rail-menu');
    const rows = menu.querySelectorAll('button');
    expect(rows.map((r) => r.textContent)).toEqual(['Select all (3)', 'Remove all drawings (3)']);
    expect(menu.querySelectorAll('svg')).toHaveLength(2);
    rows[0].dispatchEvent(new FakeEvent('click'));
    expect(names(d.calls, 'select').pop()).toEqual(['select', ['a', 'b', 'c']]);
    expect(page.doc.body.querySelector('.rail-menu')).toBeNull();
    trash.dispatchEvent(new FakeEvent('contextmenu'));
    page.doc.body.querySelectorAll('.rail-menu button')[1].dispatchEvent(new FakeEvent('click'));
    expect(names(d.calls, 'clear')).toHaveLength(1);
    expect(page.status.textContent).toBe('removed 3 drawings');
  });

  it('turns lock, eye and trash off for a read-only selection and counts only what each row reaches', () => {
    const d = setup();
    d.state.drawings = [
      { id: 'fixed', policy: { editable: false } },
      { id: 'ghost', policy: { selectable: false } },
      { id: 'mine' },
    ];
    d.select(['fixed']);
    app.chart.emit('drawing:select', { ids: ['fixed'] });
    const [lock, eye, trash] = ['Lock drawing', 'Hide drawing', 'Delete drawing'].map(byLabel);
    for (const b of [lock, eye, trash]) expect(b.classList.contains('is-off')).toBe(true);
    trash.dispatchEvent(new FakeEvent('contextmenu'));
    const rows = page.doc.body.querySelectorAll('.rail-menu button');
    expect(rows.map((r) => r.textContent)).toEqual(['Select all (2)', 'Remove all drawings (2)']);
    rows[1].dispatchEvent(new FakeEvent('click'));
    expect(page.status.textContent).toBe('removed 2 drawings');
  });

  it('selects only the drawings on the chart at its interval, and still removes them all', () => {
    const d = setup();
    d.state.drawings = [{ id: 'a' }, { id: 'intraday', intervals: { to: '1h' } }, { id: 'c' }];
    // On daily bars the intraday level is not drawn: Select all must not
    // pick it, or the delete that follows would take a drawing no one sees.
    d.hiddenOnInterval = () => ['intraday'];
    const trash = byLabel('Delete drawing');
    trash.dispatchEvent(new FakeEvent('contextmenu'));
    const rows = page.doc.body.querySelectorAll('.rail-menu button');
    expect(rows.map((r) => r.textContent)).toEqual(['Select all (2)', 'Remove all drawings (3)']);
    rows[0].dispatchEvent(new FakeEvent('click'));
    expect(names(d.calls, 'select').pop()).toEqual(['select', ['a', 'c']]);
  });

  it('counts only what the trash deletes in a selection that mixes read-only and editable drawings', () => {
    const d = setup();
    d.state.drawings = [{ id: 'fixed', policy: { editable: false } }, { id: 'a' }, { id: 'b' }];
    d.select(['fixed', 'a', 'b']);
    app.chart.emit('drawing:select', { ids: ['fixed', 'a', 'b'] });
    const trash = byLabel('Delete 2 drawings');
    expect(trash).toBeDefined();
    expect(trash.classList.contains('is-off')).toBe(false);
  });
});

describe('keyboard', () => {
  it('binds the editing keys through the tier and claims what it acts on', () => {
    const d = setup();
    d.state.drawings = [{ id: 'a' }];
    d.select('a');
    let ev = pressKey('z', { ctrlKey: true });
    expect(names(d.calls, 'undo')).toHaveLength(1);
    expect(ev.propagationStopped).toBe(true);
    pressKey('z', { ctrlKey: true, shiftKey: true });
    pressKey('y', { metaKey: true });
    expect(names(d.calls, 'redo')).toHaveLength(2);
    ev = pressKey('ArrowRight', { shiftKey: true });
    expect(names(d.calls, 'nudge').pop()).toEqual(['nudge', ['a'], 10, 0]);
    expect(ev.propagationStopped).toBe(true);
    pressKey('d', { ctrlKey: true });
    expect(names(d.calls, 'duplicate').pop()).toEqual(['duplicate', ['a']]);
    // Copy, cut and paste are the clipboard module's: seen, not claimed.
    ev = pressKey('c', { ctrlKey: true });
    expect(ev.propagationStopped).toBe(false);
    expect(ev.defaultPrevented).toBe(false);
    pressKey('Delete');
    expect(names(d.calls, 'remove').pop()).toEqual(['remove', 'a']);
    // With no selection, an arrow is the engine's pan and passes through.
    ev = pressKey('ArrowLeft');
    expect(names(d.calls, 'nudge')).toHaveLength(1);
    expect(ev.propagationStopped).toBe(false);
    // Delete reaches the drawing under the pointer when nothing is selected.
    d.state.drawings = [{ id: 'h' }];
    d.state.hovered = 'h';
    pressKey('Backspace');
    expect(names(d.calls, 'remove').pop()).toEqual(['remove', 'h']);
  });

  it('while placing, Escape cancels, Enter finishes and Backspace drops the last anchor', () => {
    const d = setup();
    d.setTool('polyline');
    let ev = pressKey('Backspace');
    expect(names(d.calls, 'popAnchor')).toHaveLength(1);
    expect(names(d.calls, 'remove')).toHaveLength(0);
    expect(ev.propagationStopped).toBe(true);
    pressKey('Enter');
    expect(names(d.calls, 'finish')).toHaveLength(1);
    setDrawLock(true);
    ev = pressKey('Escape');
    expect(names(d.calls, 'cancel')).toHaveLength(1);
    expect(ev.defaultPrevented).toBe(true);
    // Escape is left to propagate: the menus and dialogs close on the same press.
    expect(ev.propagationStopped).toBe(false);
    expect(d.state.opts.stayInDrawingMode).toBe(false);
  });

  it('stays out of text fields, dialogs and the split chart the pointer is not over', () => {
    const d = setup();
    d.state.drawings = [{ id: 'a' }];
    d.select('a');
    const input = page.doc.createElement('input');
    page.doc.body.appendChild(input);
    pressKey('Delete', {}, input);
    expect(names(d.calls, 'remove')).toHaveLength(0);
    page.doc.getElementById('chartset').hidden = false;
    pressKey('Delete');
    expect(names(d.calls, 'remove')).toHaveLength(0);
    page.doc.getElementById('chartset').hidden = true;
    // The chart under the pointer is the one the keys act on.
    app.draw2 = fakeDraw();
    app.draw2.state.drawings = [{ id: 'x' }];
    app.draw2.select('x');
    app.focusPane = 2;
    pressKey('Delete');
    expect(names(d.calls, 'remove')).toHaveLength(0);
    expect(names(app.draw2.calls, 'remove').pop()).toEqual(['remove', 'x']);
    pressKey('t', { altKey: true });
    expect(names(app.draw2.calls, 'setTool').pop()).toEqual(['setTool', 'trend-line']);
  });

  it('the rail is one tab stop: arrows walk it, ArrowRight opens a group, Escape returns focus to the chart', () => {
    const d = setup();
    const btns = railButtons(page);
    expect(btns.filter((b) => b.tabIndex === 0)).toHaveLength(1);
    expect(btns[0].tabIndex).toBe(0);   // the cursor, which is what is armed
    btns[0].focus();
    pressKey('ArrowDown', {}, btns[0]);
    expect(page.doc.activeElement).toBe(btns[1]);
    expect(btns[1].tabIndex).toBe(0);
    expect(btns[0].tabIndex).toBe(-1);
    pressKey('ArrowUp', {}, btns[1]);
    expect(page.doc.activeElement).toBe(btns[0]);
    pressKey('ArrowUp', {}, btns[0]);
    expect(page.doc.activeElement).toBe(btns[btns.length - 1]);
    pressKey('Home', {}, btns[btns.length - 1]);
    expect(page.doc.activeElement).toBe(btns[0]);
    // With the rail focused, the drawing keys stand down: an arrow is navigation, not a nudge.
    d.state.drawings = [{ id: 'a' }];
    d.select('a');
    pressKey('ArrowDown', {}, btns[0]);
    expect(names(d.calls, 'nudge')).toHaveLength(0);
    const lines = groupButton(page, 'lines');
    lines.focus();
    pressKey('ArrowRight', {}, lines);
    expect(flyoutOpen()).toBe(true);
    // Opened from the keyboard, the list starts on a row; arrows walk it, Enter arms.
    const rows = flyoutEl().querySelectorAll('.fly__row');
    expect(page.doc.activeElement).toBe(rows[0]);
    pressKey('ArrowDown', {}, rows[0]);
    expect(page.doc.activeElement).toBe(rows[1]);
    pressKey('ArrowRight', {}, rows[1]);
    expect(page.doc.activeElement).toBe(rows[1].querySelector('.fly__star'));
    pressKey('Enter', {}, page.doc.activeElement);
    expect(favorites()).toEqual(['ray']);
    pressKey('ArrowLeft', {}, page.doc.activeElement);
    pressKey('Enter', {}, rows[1]);
    expect(names(d.calls, 'setTool').pop()).toEqual(['setTool', 'ray']);
    expect(flyoutOpen()).toBe(false);
    expect(page.doc.activeElement).toBe(lines);
    pressKey('ArrowRight', {}, lines);
    pressKey('Escape', {}, page.doc.activeElement);
    expect(flyoutOpen()).toBe(false);
    expect(page.doc.activeElement).toBe(lines);
    const ev = pressKey('Escape', {}, lines);
    expect(page.doc.activeElement).toBe(page.chart);
    expect(ev.propagationStopped).toBe(true);
    expect(names(d.calls, 'cancel')).toHaveLength(0);
    toggleFavorite('ray', false);
  });
});

describe('tooltips', () => {
  it('appear after the dwell, not on entry, and leave with the pointer', () => {
    vi.useFakeTimers();
    setup();
    const lines = groupButton(page, 'lines');
    pointer('pointerenter', lines);
    vi.advanceTimersByTime(TIP_DWELL_MS - 1);
    expect(railTipTarget()).toBeNull();
    vi.advanceTimersByTime(1);
    expect(railTipTarget()).toBe(lines);
    const tip = page.doc.body.querySelector('.rail-tip');
    expect(tip.classList.contains('is-on')).toBe(true);
    expect(tip.textContent).toContain('Trend Line');
    expect(tip.querySelector('.rail-tip__chord').textContent).toBe('Alt+T');
    expect(lines.getAttribute('aria-label')).toBe('Trend Line');
    pointer('pointerleave', lines);
    expect(tip.classList.contains('is-on')).toBe(false);
    // A press before the dwell cancels it.
    pointer('pointerenter', lines);
    pointer('pointerdown', lines);
    vi.advanceTimersByTime(TIP_DWELL_MS);
    expect(railTipTarget()).toBeNull();
    // A control's label follows its state.
    const magnet = page.rail.querySelector('.rail__btn--magnet');
    setMagnetMode('weak');
    pointer('pointerenter', magnet);
    vi.advanceTimersByTime(TIP_DWELL_MS);
    expect(tip.textContent).toContain('Magnet: weak');
    expect(magnet.getAttribute('aria-label')).toBe('Magnet: weak');
    vi.useRealTimers();
  });

  it('say active, never armed, for the stay mode and the double-click hold', () => {
    vi.useFakeTimers();
    setup();
    const said = [];
    const tipText = (b) => {
      pointer('pointerenter', b);
      vi.advanceTimersByTime(TIP_DWELL_MS);
      const text = page.doc.body.querySelector('.rail-tip').textContent;
      pointer('pointerleave', b);
      said.push(text);
      return text;
    };
    const stay = railButtons(page).find((b) => (b.getAttribute('aria-label') || '').startsWith('Keep tool'));
    expect(tipText(stay)).toContain('Keep tool active');
    expect(tipText(groupButton(page, 'lines'))).toContain('Double-click keeps it active');
    setStayMode(true);
    said.push(page.status.textContent);
    expect(page.status.textContent).toBe('tools stay active after each drawing');
    expect(tipText(stay)).toContain('On: the tool stays active after each drawing');
    setStayMode(false);
    clickOn(groupButton(page, 'lines'), { detail: 2 });
    said.push(page.status.textContent);
    for (const text of said) expect(text).not.toMatch(/arm(ed|ing|s)?/i);
    setDrawLock(false);
    vi.useRealTimers();
  });

  it('is placed beside the control and flipped back inside the window', () => {
    const vp = { width: 400, height: 300 };
    expect(placeTip({ left: 0, top: 100, right: 42, bottom: 132, width: 42, height: 32 }, { width: 120, height: 24 }, vp))
      .toEqual({ left: 50, top: 104 });
    // No room on the right: the tip goes to the left of the anchor.
    expect(placeTip({ left: 340, top: 100, right: 380, bottom: 132, width: 40, height: 32 }, { width: 120, height: 24 }, vp))
      .toEqual({ left: 212, top: 104 });
    // Near the bottom edge it is clamped, never off screen.
    const low = placeTip({ left: 0, top: 290, right: 42, bottom: 322, width: 42, height: 32 }, { width: 120, height: 24 }, vp);
    expect(low.top + 24).toBeLessThanOrEqual(vp.height - 6);
  });

  it('flyouts open beside the button and are pulled up rather than running off the bottom', () => {
    const vp = { width: 1280, height: 800 };
    expect(placeBeside({ left: 0, top: 200, right: 42, bottom: 232 }, { width: 250, height: 300 }, vp))
      .toEqual({ left: 48, top: 200, side: 'right' });
    const low = placeBeside({ left: 0, top: 700, right: 42, bottom: 732 }, { width: 250, height: 300 }, vp);
    expect(low.top).toBe(800 - 300 - 8);
    expect(placeBeside({ left: 1200, top: 10, right: 1240, bottom: 42 }, { width: 250, height: 100 }, vp).side).toBe('left');
    // In the page the flyout sits in the layer host at the computed spot.
    setup();
    const lines = groupButton(page, 'lines');
    lines.rect = { left: 0, top: 700, width: 42, height: 32 };
    clickOn(lines, { from: lines.querySelector('.rail__chev') });
    flyoutEl().size = { width: 250, height: 300 };
    expect(flyoutEl().parentNode).toBe(page.doc.body);
    expect(flyoutEl().style.left).toBe('48px');
    // Clicking outside closes it; clicking the button again toggles it.
    pointer('pointerdown', page.chart);
    expect(flyoutOpen()).toBe(false);
    clickOn(lines, { from: lines.querySelector('.rail__chev') });
    clickOn(lines);
    expect(flyoutOpen()).toBe(false);
  });
});

describe('properties bar seam', () => {
  it('mounts the bar with the stage as its anchor and forwards the drawing module calls', () => {
    const calls = [];
    const handle = {
      attach: () => calls.push(['attach']),
      show: (id) => calls.push(['show', id]),
      hide: () => calls.push(['hide']),
      reposition: () => calls.push(['reposition']),
      editText: (id) => calls.push(['editText', id]),
    };
    let mountedWith = null;
    setup({ init: { mountPropertiesBar: (a, anchor) => { mountedWith = { a, anchor }; return handle; } } });
    expect(mountedWith.a).toBe(app);
    expect(mountedWith.anchor).toBe(page.stage);
    // buildRail saw the first chart: the bar was attached to it once.
    expect(calls).toEqual([['attach']]);
    showWidget('d1');
    showWidget(null);
    positionWidget();
    openTextDialog('d1');
    expect(calls.slice(1)).toEqual([['show', 'd1'], ['hide'], ['reposition'], ['editText', 'd1']]);
    // A chart-type switch: the rail notices the new chart on its resync and re-attaches the bar.
    syncRail(null);
    expect(calls.filter((c) => c[0] === 'attach')).toHaveLength(1);
    app.chart = fakeChart();
    app.draw = fakeDraw();
    syncRail(null);
    expect(calls.filter((c) => c[0] === 'attach')).toHaveLength(2);
    // Without a bar mounted the seam is inert, so the page loads either way.
    setup();
    expect(() => { showWidget('d1'); positionWidget(); openTextDialog('d1'); }).not.toThrow();
  });
});

describe('folding the rail', () => {
  const tab = () => page.stage.querySelector('.rail-tab');

  it('folds behind a tab, gives the chart the rail width, and comes back from the tab', () => {
    setup();
    expect(tab().hidden).toBe(true);
    const fold = page.rail.querySelector('.rail__collapse');
    fold.focus();
    fold.click();
    expect(railCollapsed()).toBe(true);
    expect(page.rail.classList.contains('is-collapsed')).toBe(true);
    // Every chart offset in the page keys on has-rail, so dropping it is what widens the chart.
    expect(page.stage.classList.contains('has-rail')).toBe(false);
    expect(tab().hidden).toBe(false);
    expect(document.activeElement).toBe(tab());
    expect(JSON.parse(store.get(RAIL_PREFS_KEY)).collapsed).toBe(true);
    tab().click();
    expect(railCollapsed()).toBe(false);
    expect(page.stage.classList.contains('has-rail')).toBe(true);
    expect(tab().hidden).toBe(true);
    expect(document.activeElement).toBe(page.rail.querySelector('.rail__collapse'));
  });

  it('starts folded from the store, closes an open list as it folds, and keeps the tab from the chart pointer', () => {
    setup({ prefs: { collapsed: true } });
    expect(page.rail.classList.contains('is-collapsed')).toBe(true);
    expect(tab().hidden).toBe(false);
    setRailCollapsed(false);
    clickOn(groupButton(page, 'shapes').querySelector('.rail__chev'));
    expect(flyoutOpen()).toBe(true);
    setRailCollapsed(true);
    expect(flyoutOpen()).toBe(false);
    const down = vi.fn();
    page.stage.addEventListener('pointerdown', down);
    tab().dispatchEvent(new FakeEvent('pointerdown', { bubbles: true }));
    expect(down).not.toHaveBeenCalled();
  });

  it('ignores a stored fold that is not true', () => {
    setup({ prefs: { collapsed: 'yes' } });
    expect(railCollapsed()).toBe(false);
    expect(page.rail.classList.contains('is-collapsed')).toBe(false);
  });
});

describe('module hygiene', () => {
  it('refreshControls is safe before the rail is built and the prefs store is optional', () => {
    page = railPage();
    globalThis.localStorage = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
    app = { draw: fakeDraw(), draw2: null, chart: fakeChart(), focusPane: 1, shortcuts: {} };
    expect(() => { initRail(app); buildRail(); refreshControls(); cycleMagnet(); toggleFavorite('ray'); }).not.toThrow();
    expect(favorites()).toEqual(['ray']);
    toggleFavorite('ray', false);
  });
});
