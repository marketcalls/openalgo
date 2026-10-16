import {
  getDrawingTool, hasDrawingTool, drawingShortcuts, matchDrawingShortcut, keyToDrawingAction,
  iconSprite, toolCursor, DRAWING_TOOL_ICONS, BUILTIN_DRAWING_TOOLS,
  ICON_SIZE, ICON_STROKE, CHROME_ICON_SIZE, CHROME_ICON_STROKE,
} from '/dist/openalgo-charts.draw.mjs';
import { el, inTextField, MOD } from './ui.js';
import {
  RAIL_FLYOUT_CSS, toolGlyph, chromeGlyph, attachRailTip, hideRailTip, refreshTipLabel,
  openFlyout, closeFlyout, flyoutOpen, flyoutEl, openRailMenu, closeRailMenu, railMenuOpen,
} from './rail-flyout.js';
import { historyPress, historyReady, initHistory, onHistoryChange } from './history.js';

let app;

// ══ drawing UI: the left tool rail ══════════════════════════════════════
// All of this is HOST ui: the engine draws on canvas and ships no DOM, so
// a rail belongs here. Everything routes through the controller's public
// API, and every glyph comes from the tier's own registry: the sprite is
// injected once and each button, flyout row and menu entry is a `<use>`
// into it, so the rail, its flyouts and the armed cursor cannot drift.
//
// The properties bar for a selected drawing is a separate module. The rail
// mounts it and forwards the calls the drawing module makes (see the seam
// at the bottom), so the two can be developed apart.

/** Where the pins, the magnet mode, the stay toggle and each group's last pick live between visits. */
export const RAIL_PREFS_KEY = 'oa-charts-rail';
export const MAGNET_MODES = ['off', 'weak', 'strong'];

/**
 * Rail groups. A group is one button standing for its last-used tool, with
 * a chevron that lists the rest. Only registered tools are shown, so a
 * dist/ that predates a tool leaves a gap rather than a dead row. Names
 * come from the descriptors, not from here: the rail cannot spell a tool
 * differently from the registry.
 */
export const RAIL_GROUPS = [
  { id: 'lines', title: 'Lines', items: [
    { head: 'Lines' },
    { tool: 'trend-line' }, { tool: 'ray' }, { tool: 'extended-line' }, { tool: 'arrow' },
    { tool: 'info-line' }, { tool: 'trend-angle' },
    { head: 'Horizontal and vertical' },
    { tool: 'horizontal-line' }, { tool: 'horizontal-ray' }, { tool: 'vertical-line' }, { tool: 'cross-line' },
  ] },
  { id: 'channels', title: 'Channels', items: [
    { head: 'Channels' },
    { tool: 'parallel-channel' }, { tool: 'fib-channel' },
    { tool: 'disjoint-channel' }, { tool: 'flat-top-bottom' }, { tool: 'regression-channel' },
    { head: 'Pitchforks' },
    { tool: 'pitchfork' }, { tool: 'schiff-pitchfork' }, { tool: 'modified-schiff-pitchfork' }, { tool: 'inside-pitchfork' },
  ] },
  { id: 'fib', title: 'Fibonacci and Gann', items: [
    { head: 'Fibonacci' },
    { tool: 'fib-retracement' }, { tool: 'fib-extension' }, { tool: 'fib-time-zone' }, { tool: 'fib-fan' },
    { tool: 'fib-extension-two-point' }, { tool: 'fib-speed-resistance-fan' },
    { tool: 'trend-fib-time' }, { tool: 'fib-circles' }, { tool: 'fib-speed-resistance-arcs' },
    { tool: 'fib-wedge' }, { tool: 'fib-spiral' },
    { head: 'Gann' },
    { tool: 'gann-fan' }, { tool: 'gann-box' }, { tool: 'gann-square' },
  ] },
  { sep: true },
  { id: 'shapes', title: 'Shapes', items: [
    { head: 'Shapes' },
    { tool: 'rectangle' }, { tool: 'rotated-rectangle' }, { tool: 'ellipse' }, { tool: 'circle' }, { tool: 'triangle' },
    { head: 'Paths' },
    { tool: 'path' }, { tool: 'polyline' }, { tool: 'arc' }, { tool: 'curve' }, { tool: 'double-curve' },
  ] },
  { id: 'cycles', title: 'Cycles', items: [
    { head: 'Cycles' },
    { tool: 'cyclic-lines' }, { tool: 'time-cycles' }, { tool: 'sine-line' },
  ] },
  { id: 'patterns', title: 'Patterns', items: [
    { head: 'Patterns and waves' },
    { tool: 'xabcd-pattern' }, { tool: 'abcd-pattern' }, { tool: 'head-shoulders' },
    { tool: 'elliott-impulse' }, { tool: 'elliott-correction' },
    { head: 'Harmonic patterns' },
    { tool: 'gartley' }, { tool: 'bat' }, { tool: 'butterfly' }, { tool: 'crab' }, { tool: 'shark' }, { tool: 'cypher' },
  ] },
  { id: 'geometry', title: 'Geometric studies', items: [
    { head: 'Geometric studies' },
    { tool: 'sonic' }, { tool: 'supersonic' }, { tool: 'golden-sonic' }, { tool: 'golden-supersonic' },
    { tool: 'dedekind-tessellation' },
  ] },
  { id: 'marks', title: 'Arrows and marks', items: [
    { head: 'Arrows' },
    { tool: 'arrow-up' }, { tool: 'arrow-down' }, { tool: 'arrow-left' }, { tool: 'arrow-right' },
    { head: 'Marks' },
    { tool: 'flag-mark' }, { tool: 'icon-stamp' }, { tool: 'price-label' }, { tool: 'signpost' },
  ] },
  { sep: true },
  { id: 'forecast', title: 'Forecasting', items: [
    { head: 'Forecasting' },
    { tool: 'long-position' }, { tool: 'short-position' }, { tool: 'forecast' },
  ] },
  { id: 'analysis', title: 'Volume studies', items: [
    { head: 'Volume studies' },
    { tool: 'anchored-vwap' }, { tool: 'fixed-range-volume-profile' },
  ] },
  { id: 'measure', title: 'Measurers', items: [
    { head: 'Measurers' },
    { tool: 'price-range' }, { tool: 'date-range' }, { tool: 'measure' },
  ] },
  { sep: true },
  { id: 'text', title: 'Text and notes', items: [
    { head: 'Text and notes' },
    { tool: 'text' }, { tool: 'note' }, { tool: 'callout' }, { tool: 'balloon' }, { tool: 'comment' },
    { tool: 'price-note' }, { tool: 'table' },
    { head: 'Brushes' },
    { tool: 'brush' }, { tool: 'highlighter' },
  ] },
];

const groupById = (id) => RAIL_GROUPS.find((g) => g.id === id);
const toolsOf = (g) => g.items.filter((i) => i.tool && hasDrawingTool(i.tool)).map((i) => i.tool);
export const toolName = (id) => (id && hasDrawingTool(id) ? getDrawingTool(id).name : String(id || 'Cursor'));

// The chord table is the tier's. Read once per build rather than per row:
// `drawingShortcuts()` walks the registry, and the demo's `app.shortcuts`
// is the same table when the drawing module has filled it.
let chords = null;
export function chordOf(id) {
  if (!id) return undefined;
  if (app && app.shortcuts && app.shortcuts[id]) return app.shortcuts[id];
  if (!chords) chords = drawingShortcuts();
  return chords[id];
}

// ── preferences ────────────────────────────────────────────────────────
const prefs = { favorites: [], magnet: 'off', stay: false, last: {}, collapsed: false };
let latch = false;   // a double-click's hold on one tool; see setDrawLock

function loadPrefs() {
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(RAIL_PREFS_KEY) || 'null'); } catch { raw = null; }
  prefs.favorites = [];
  prefs.magnet = 'off';
  prefs.stay = false;
  prefs.last = {};
  prefs.collapsed = false;
  if (!raw || typeof raw !== 'object') return;
  // Validated field by field: a pin to a tool this dist/ lacks, or a mode
  // a later release renamed, is dropped on its own rather than taking the
  // rest of the saved rail with it.
  if (Array.isArray(raw.favorites)) {
    prefs.favorites = raw.favorites.filter((id, i, a) => typeof id === 'string' && hasDrawingTool(id) && a.indexOf(id) === i);
  }
  if (MAGNET_MODES.includes(raw.magnet)) prefs.magnet = raw.magnet;
  prefs.stay = raw.stay === true;
  prefs.collapsed = raw.collapsed === true;
  if (raw.last && typeof raw.last === 'object') {
    for (const g of RAIL_GROUPS) {
      if (g.id && typeof raw.last[g.id] === 'string' && toolsOf(g).includes(raw.last[g.id])) prefs.last[g.id] = raw.last[g.id];
    }
  }
}

function savePrefs() {
  // The store is a convenience: a private window or a full quota loses
  // the pins between visits, never the rail.
  try { localStorage.setItem(RAIL_PREFS_KEY, JSON.stringify(prefs)); } catch { /* see above */ }
}

/** A copy of what the rail remembers. Tests read it; the page never needs to. */
export const railPrefs = () => ({
  favorites: prefs.favorites.slice(), magnet: prefs.magnet, stay: prefs.stay, last: { ...prefs.last },
  collapsed: prefs.collapsed,
});

const lastOf = (g) => prefs.last[g.id] || toolsOf(g)[0] || null;

// ── the controllers the rail drives ────────────────────────────────────
// Shared controls and drawing chords use the same explicitly selected chart.
const activeDraw = () => (app.focusPane === 2 && app.draw2 ? app.draw2 : app.draw);
const activeChart = () => (app.focusPane === 2 && app.chart2 ? app.chart2 : app.chart);

/** Pointer or keyboard selection owns shared controls until another selection. */
export function focusChart(pane) {
  const selected = pane === 2 && app.chart2 ? 2 : 1;
  const changed = app.focusPane !== selected;
  app.focusPane = selected;
  for (const [id, index] of [['chart', 1], ['chart2', 2]]) {
    el(id)?.setAttribute('data-chart-focused', String(index === selected));
  }
  syncMobileControls(activeDraw()?.activeTool());
  if (changed) app.onFocusPane?.(selected);
}
const eachDraw = (fn) => { for (const d of [app.draw, app.draw2]) if (d) fn(d); };
const mobileObserved = new WeakSet();
const navigationObserved = new WeakSet();
const selectionOf = (d) => {
  if (!d) return [];
  if (typeof d.selection === 'function') return d.selection().slice();
  const one = d.selected();
  return one ? [one] : [];
};

/**
 * The armed tool's glyph as the pointer. It goes through a custom property
 * read by the stylesheet, not the inline cursor: the engine owns that one
 * for its hover hints (a divider, an order line) and clears it as the
 * pointer moves, and a hint still wins while it is up.
 */
export function armCursor(box, tool) {
  if (tool && DRAWING_TOOL_ICONS[tool]) box.style.setProperty('--tool-cursor', toolCursor(tool));
  else box.style.removeProperty('--tool-cursor');
}

// ── eraser ─────────────────────────────────────────────────────────────
/**
 * The eraser's glyph, on the chrome grid in the chrome stroke: a tilted
 * block over the line it wipes. The tier ships no eraser glyph, so the rail
 * draws its own, inline like the tier's.
 */
const ERASER_GLYPH = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16" fill="none" '
  + 'stroke="currentColor" stroke-width="' + CHROME_ICON_STROKE + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M9 2.5l4.5 4.5-6 6H4.5L2.5 11zM5.75 5.75l4.5 4.5M9.5 14h4"/></svg>';

const erasing = () => Boolean(app.draw && typeof app.draw.erasing === 'function' && app.draw.erasing());

/** Eraser mode on the active chart's controller, or off. The controller disarms any tool. */
export function setEraser(on) {
  if (!app.draw || typeof app.draw.setEraser !== 'function') return;
  setDrawLock(false);
  app.draw.setEraser(on === true);
  syncRail(app.draw.activeTool());
}

// ── magnet and stay ────────────────────────────────────────────────────
export const magnetMode = () => prefs.magnet;

function applyMagnet() {
  eachDraw((d) => d.setOptions({ magnet: prefs.magnet }));
  // The legacy checkbox seeds the controller drawing.js builds on every
  // chart rebuild, and the shell bar reads it: keep it telling the truth
  // as a boolean, and let observe() restore the finer mode afterwards.
  const box = el('magnet');
  if (box) box.checked = prefs.magnet !== 'off';
}

export function setMagnetMode(mode) {
  if (!MAGNET_MODES.includes(mode)) throw new Error(`rail: unknown magnet mode "${mode}"`);
  prefs.magnet = mode;
  savePrefs();
  applyMagnet();
  refreshControls();
}

/** off -> weak -> strong -> off. */
export function cycleMagnet() {
  const next = MAGNET_MODES[(MAGNET_MODES.indexOf(prefs.magnet) + 1) % MAGNET_MODES.length];
  setMagnetMode(next);
  const status = el('status');
  if (status) {
    status.textContent = next === 'off' ? `magnet off · hold ${MOD} to snap while placing or dragging`
      : next === 'weak' ? 'magnet weak: snaps when a bar or study value is within a few pixels'
      : 'magnet strong: every anchor lands on the nearest bar or study value';
  }
}

export const stayMode = () => prefs.stay;

// A tool stays armed after a drawing when either the toggle is on or a
// double-click held it. Both charts: the split is one workspace, and a
// tool that latched on one half but not the other is a difference nobody
// asked for.
function applyStay() {
  eachDraw((d) => d.setOptions({ stayInDrawingMode: prefs.stay || latch }));
}

export function setStayMode(on) {
  prefs.stay = on === true;
  savePrefs();
  applyStay();
  refreshControls();
  const status = el('status');
  if (status) status.textContent = prefs.stay ? 'tools stay active after each drawing' : 'one drawing per pick';
}

/**
 * The double-click hold: one tool kept armed until something leaves it
 * (Escape, the cursor button, another single click). The drawing module
 * clears it on those paths; it never touches the stay toggle, which is a
 * mode the user set and keeps.
 */
export function setDrawLock(on) {
  latch = on === true;
  applyStay();
  syncRail(app.draw ? app.draw.activeTool() : null);
}
export const drawLocked = () => latch;

// ── favorites ──────────────────────────────────────────────────────────
export const favorites = () => prefs.favorites.slice();
export const isFavorite = (id) => prefs.favorites.includes(id);

export function toggleFavorite(id, on = !isFavorite(id)) {
  if (!hasDrawingTool(id)) return;
  const has = isFavorite(id);
  if (on && !has) prefs.favorites.push(id);
  if (!on && has) prefs.favorites.splice(prefs.favorites.indexOf(id), 1);
  savePrefs();
  renderFavorites();
  syncRail(app.draw ? app.draw.activeTool() : null);
}

// ── building the rail ──────────────────────────────────────────────────
let chromeReady = false;

/** The sprite and the stylesheet, once per document. */
function ensureChrome() {
  if (chromeReady && document.getElementById('oac-rail-sprite')) return;
  if (!document.getElementById('oac-rail-css')) {
    const s = document.createElement('style');
    s.id = 'oac-rail-css';
    s.textContent = RAIL_CSS + RAIL_FLYOUT_CSS;
    (document.head || document.body).appendChild(s);
  }
  if (!document.getElementById('oac-rail-sprite')) {
    const w = document.createElement('div');
    w.id = 'oac-rail-sprite';
    w.hidden = true;
    w.innerHTML = iconSprite();
    document.body.appendChild(w);
  }
  chromeReady = true;
}

function makeBtn({ cls, glyph, tip, onClick, onContext }) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'rail__btn' + (cls ? ' ' + cls : '');
  b.tabIndex = -1;
  b.innerHTML = '<span class="rail__glyph">' + glyph + '</span>';
  attachRailTip(b, tip);
  b.addEventListener('click', (e) => { closeRailMenu(); if (!b.classList.contains('is-off')) onClick(e); });
  if (onContext) {
    b.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); onContext(e); });
  }
  return b;
}

const sep = () => {
  const s = document.createElement('div');
  s.className = 'rail__sep';
  s.setAttribute('role', 'separator');
  return s;
};

function arm(tool) {
  if (!app.draw) return;
  app.draw.setTool(tool);
  // The event drives syncRail on the page; a controller that emits nothing
  // (a test double, an older dist/) still leaves the rail truthful.
  syncRail(tool);
}

function cursorButton() {
  const b = makeBtn({
    cls: 'rail__tool',
    glyph: toolGlyph('cursor'),
    tip: () => ({ title: 'Cursor', chord: 'Esc', side: 'right' }),
    onClick: () => { setDrawLock(false); arm(null); },
  });
  b.dataset.tools = '';
  return b;
}

function favoriteButton(id) {
  const b = makeBtn({
    cls: 'rail__tool rail__fav',
    glyph: toolGlyph(id),
    tip: () => ({ title: toolName(id), chord: chordOf(id), sub: 'Pinned. Right-click to unpin', side: 'right' }),
    onClick: (e) => {
      if (e.detail >= 2 && !prefs.stay) { hold(id); return; }
      setDrawLock(false);
      arm(id);
    },
    onContext: () => openRailMenu(b, [
      { label: 'Unpin from rail', icon: 'star', onSelect: () => toggleFavorite(id, false) },
    ]),
  });
  b.dataset.tools = id;
  return b;
}

/** Keep `tool` armed until something leaves it: the double-click gesture. */
function hold(tool) {
  setDrawLock(true);
  arm(tool);
  const status = el('status');
  if (status) status.textContent = `${toolName(tool)} stays active until Escape`;
}

function groupButton(g) {
  const tools = toolsOf(g);
  const b = makeBtn({
    cls: 'rail__tool rail__group',
    glyph: toolGlyph(lastOf(g)),
    tip: () => ({
      title: toolName(lastOf(g)),
      chord: chordOf(lastOf(g)),
      sub: g.title + ': chevron for the rest' + (prefs.stay ? '' : '. Double-click keeps it active'),
      side: 'right',
    }),
    onClick: (e) => {
      if (!app.draw) return;
      const onChevron = Boolean(e.target && e.target.closest && e.target.closest('.rail__chev'));
      if (flyoutOpen() && flyoutEl() && b.getAttribute('aria-expanded') === 'true') { closeFlyout(); return; }
      if (onChevron) { openGroupFlyout(g, b, false); return; }
      if (e.detail >= 2 && !prefs.stay) { hold(lastOf(g)); return; }
      // A click on a tool that is already armed is a request for the list:
      // arming it again would do nothing the user could see.
      if (app.draw.activeTool() === lastOf(g)) { openGroupFlyout(g, b, false); return; }
      setDrawLock(false);
      arm(lastOf(g));
    },
    onContext: () => openGroupFlyout(g, b, false),
  });
  b.dataset.tools = tools.join(',');
  b.dataset.group = g.id;
  b.dataset.face = lastOf(g);
  b.setAttribute('aria-haspopup', 'menu');
  b.setAttribute('aria-expanded', 'false');
  const chev = document.createElement('span');
  chev.className = 'rail__chev';
  chev.innerHTML = chromeGlyph('chevron-right');
  b.appendChild(chev);
  return b;
}

function openGroupFlyout(g, anchor, viaKeyboard) {
  openFlyout({
    anchor,
    edge: el('rail'),   // clear the rail, not just the button inside it
    group: { title: g.title, items: g.items.filter((i) => i.head || hasDrawingTool(i.tool)) },
    armed: app.draw ? app.draw.activeTool() : null,
    nameOf: toolName,
    chordOf,
    isPinned: isFavorite,
    onPick: (tool) => {
      prefs.last[g.id] = tool;
      savePrefs();
      setDrawLock(false);   // a pick from the list is one placement, like a single click
      arm(tool);
    },
    onPin: (tool, on) => toggleFavorite(tool, on),
    viaKeyboard,
  });
}

// ── the controls block ─────────────────────────────────────────────────
const ctl = {};   // the control buttons, for refreshControls

function controlsBlock() {
  const box = document.createElement('div');
  box.className = 'rail__ctl';

  ctl.magnet = makeBtn({
    cls: 'rail__btn--chrome rail__btn--magnet',
    glyph: chromeGlyph('magnet'),
    tip: () => ({
      title: 'Magnet: ' + prefs.magnet,
      sub: (prefs.magnet === 'off' ? 'Click for weak: snaps when a bar or study value is within a few pixels'
        : prefs.magnet === 'weak' ? 'Click for strong: every anchor lands on the nearest bar or study value'
        : 'Click to switch the magnet off') + `. Hold ${MOD} for a strong snap while placing or dragging`,
      side: 'right',
    }),
    onClick: cycleMagnet,
  });
  box.appendChild(ctl.magnet);

  ctl.eraser = makeBtn({
    cls: 'rail__btn--chrome rail__btn--eraser',
    glyph: ERASER_GLYPH,
    tip: () => ({
      title: erasing() ? 'Eraser: on' : 'Eraser',
      chord: erasing() ? 'Esc' : undefined,
      sub: erasing() ? 'Click or drag across drawings to delete them. Click to stop'
        : 'Click, then click or drag across drawings to delete them',
      side: 'right',
    }),
    onClick: () => setEraser(!erasing()),
  });
  box.appendChild(ctl.eraser);

  ctl.stay = makeBtn({
    cls: 'rail__btn--chrome',
    glyph: chromeGlyph('link'),
    tip: () => ({
      title: 'Keep tool active',
      sub: prefs.stay ? 'On: the tool stays active after each drawing' : 'Off: one drawing per pick',
      side: 'right',
    }),
    onClick: () => setStayMode(!prefs.stay),
  });
  box.appendChild(ctl.stay);
  box.appendChild(sep());

  ctl.lock = makeBtn({
    cls: 'rail__btn--chrome',
    glyph: chromeGlyph('unlock'),
    tip: () => {
      const sel = selectionOf(app.draw);
      // One name; the pressed state and the glyph say locked. A disabled
      // button says why it is off.
      return { title: 'Lock drawing', sub: !sel.length ? 'Select a drawing first' : readOnlySub(sel), side: 'right' };
    },
    onClick: () => {
      const sel = selectionOf(app.draw);
      const locked = !allLocked(sel);
      for (const id of sel) app.draw.update(id, { locked });
      refreshControls();
    },
  });
  box.appendChild(ctl.lock);

  ctl.eye = makeBtn({
    cls: 'rail__btn--chrome',
    glyph: chromeGlyph('eye'),
    tip: () => {
      const sel = selectionOf(app.draw);
      return { title: 'Hide drawing', side: 'right', sub: !sel.length ? 'Select a drawing first'
        : readOnlySub(sel) ?? (allHidden(sel) ? undefined : 'Stays selected, so the eye brings it back') };
    },
    onClick: () => {
      const sel = selectionOf(app.draw);
      const visible = allHidden(sel);
      for (const id of sel) app.draw.update(id, { visible });
      refreshControls();
    },
  });
  box.appendChild(ctl.eye);

  ctl.trash = makeBtn({
    cls: 'rail__btn--chrome rail__btn--danger',
    glyph: chromeGlyph('trash'),
    tip: () => {
      const sel = selectionOf(app.draw);
      // The count is what the press deletes: read-only drawings stay.
      const n = sel.filter((id) => isEditable(app.draw.get(id))).length;
      return sel.length
        ? { title: n > 1 ? `Delete ${n} drawings` : 'Delete drawing', chord: 'Del', sub: readOnlySub(sel) ?? 'Right-click to remove all', side: 'right' }
        : { title: 'Delete drawing', chord: 'Del', sub: 'Select one first. Right-click to remove all', side: 'right' };
    },
    onClick: () => {
      for (const id of selectionOf(app.draw)) app.draw.remove(id);
      refreshControls();
    },
    onContext: () => {
      if (!app.draw) return;
      // Each count is what its row reaches: an unselectable drawing never
      // joins a selection, and a read-only one survives a clear. Select all
      // takes only what is on the chart: a drawing whose interval range hides
      // it here would otherwise go with the delete that follows, unseen.
      // Remove all is every drawing, as its count says.
      const all = app.draw.drawings();
      const off = new Set(app.draw.hiddenOnInterval?.() ?? []);
      const onChart = all.filter((d) => !off.has(d.id));
      const picked = onChart.filter((d) => d.policy?.selectable !== false).length;
      const n = all.filter(isEditable).length;
      openRailMenu(ctl.trash, [
        { label: `Select all (${picked})`, icon: 'cursor', disabled: picked === 0, onSelect: () => {
          app.draw.select(onChart.map((d) => d.id));
          refreshControls();
        } },
        { label: `Remove all drawings (${n})`, icon: 'trash', danger: true, disabled: n === 0, onSelect: () => {
          app.draw.clear();   // one undo step, so it is recoverable
          refreshControls();
          const status = el('status');
          if (status) status.textContent = n ? `removed ${n} drawing${n === 1 ? '' : 's'}` : 'no drawings to remove';
        } },
      ]);
    },
  });
  box.appendChild(ctl.trash);
  box.appendChild(sep());

  ctl.undo = makeBtn({
    cls: 'rail__btn--chrome',
    glyph: chromeGlyph('undo'),
    tip: () => ({ title: 'Undo', chord: `${MOD}+Z`, side: 'right' }),
    // The main chart's whole timeline: a study or a pane, not only a drawing.
    onClick: () => { historyPress('undo', 1); refreshControls(); },
  });
  box.appendChild(ctl.undo);
  ctl.redo = makeBtn({
    cls: 'rail__btn--chrome',
    glyph: chromeGlyph('redo'),
    tip: () => ({ title: 'Redo', chord: `${MOD}+Y`, side: 'right' }),
    onClick: () => { historyPress('redo', 1); refreshControls(); },
  });
  box.appendChild(ctl.redo);
  box.appendChild(sep());
  ctl.collapse = makeBtn({
    cls: 'rail__btn--chrome rail__collapse',
    glyph: chromeGlyph('chevrons-left'),
    tip: () => ({ title: 'Hide drawing tools', sub: 'The chart takes the space. The tab at its bottom left brings them back', side: 'right' }),
    onClick: () => setRailCollapsed(true),
  });
  box.appendChild(ctl.collapse);
  return box;
}

// ── folding ────────────────────────────────────────────────────────────
// Folded, the rail leaves a tab at the chart's bottom left and the rail's
// container drops `has-rail`, which is what every chart offset in the page
// keys on, so the chart takes the rail's width. The tab stops the press: the
// chart's pointer capture would otherwise eat it.
let railTab = null;
// Where styles.css swaps the rail for the touch bar (below 900px, or a short
// coarse-pointer window under 960px): there is no room for a tab, so a fold
// chosen on a desktop window waits there until the rail is back.
const TOUCH_LAYOUT = '(max-width: 900px), (pointer: coarse) and (max-width: 960px) and (max-height: 599px)';
let touchQuery = null;
const foldable = () => !touchQuery || !touchQuery.matches;

function ensureRailTab() {
  const rail = el('rail');
  if (!rail || !rail.parentNode || typeof rail.parentNode.insertBefore !== 'function') return null;
  // One tab per page, beside the rail wherever the rail is: a full-screen
  // second chart takes the rail into its own pane, and the tab goes with it.
  if (railTab && railTab.ownerDocument === document) {
    if (railTab.parentNode !== rail.parentNode) rail.parentNode.insertBefore(railTab, rail.nextSibling);
    return railTab;
  }
  railTab = document.createElement('button');
  railTab.type = 'button';
  railTab.className = 'rail-tab';
  railTab.hidden = true;
  railTab.innerHTML = chromeGlyph('chevrons-right');
  attachRailTip(railTab, () => ({ title: 'Show drawing tools', side: 'right' }));
  railTab.addEventListener('pointerdown', (e) => e.stopPropagation());
  railTab.addEventListener('click', () => setRailCollapsed(false));
  rail.parentNode.insertBefore(railTab, rail.nextSibling);
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    touchQuery = window.matchMedia(TOUCH_LAYOUT);
    if (typeof touchQuery.addEventListener === 'function') touchQuery.addEventListener('change', applyRailCollapsed);
  }
  return railTab;
}

/** Re-apply the fold where the rail is now: the full-screen chrome calls it after moving the rail. */
export function applyRailCollapsed() {
  const rail = el('rail');
  if (!rail) return;
  const tab = ensureRailTab();
  const on = prefs.collapsed === true && foldable();
  rail.classList.toggle('is-collapsed', on);
  if (rail.parentNode && rail.parentNode.classList) rail.parentNode.classList.toggle('has-rail', !on);
  if (tab) { tab.hidden = !on; refreshTipLabel(tab); }
}

export const railCollapsed = () => prefs.collapsed === true;

/** Fold the rail away behind its tab, or bring it back. Focus follows the control that replaces the one pressed. */
export function setRailCollapsed(on) {
  const next = on === true;
  if (prefs.collapsed === next) return;
  const rail = el('rail');
  const active = document.activeElement;
  const hadFocus = next ? Boolean(rail && active && rail.contains(active)) : Boolean(railTab && active === railTab);
  if (next) { closeFlyout(); hideRailTip(); }
  prefs.collapsed = next;
  savePrefs();
  applyRailCollapsed();
  const target = next ? railTab : ctl.collapse;
  if (hadFocus && target) target.focus();
}

/** Whether the user may edit `d`: a drawing whose policy says otherwise is the host's. */
const isEditable = (d) => !!d && d.policy?.editable !== false;
/** The sub line of a control that is off because nothing selected may be edited. */
const readOnlySub = (ids) => (ids.some((id) => isEditable(app.draw.get(id))) ? undefined : 'Read-only');
const allLocked = (ids) => ids.length > 0 && ids.every((id) => { const d = app.draw.get(id); return d && d.locked === true; });
const allHidden = (ids) => ids.length > 0 && ids.every((id) => { const d = app.draw.get(id); return d && d.visible === false; });

function setState(b, { on, off, glyph, pressed }) {
  if (!b) return;
  b.classList.toggle('is-on', on === true);
  b.classList.toggle('is-off', off === true);
  b.setAttribute('aria-disabled', off === true ? 'true' : 'false');
  if (pressed !== undefined) b.setAttribute('aria-pressed', String(pressed));
  if (glyph !== undefined && b.dataset.glyph !== glyph) {
    b.dataset.glyph = glyph;
    b.querySelector('.rail__glyph').innerHTML = chromeGlyph(glyph);
  }
}

/** The controls follow the controller: cheap class flips, no rebuild. */
export function refreshControls() {
  if (!ctl.magnet) return;
  const d = app.draw;
  setState(ctl.magnet, { on: prefs.magnet === 'strong', pressed: prefs.magnet !== 'off' });
  ctl.magnet.classList.toggle('is-weak', prefs.magnet === 'weak');
  ctl.magnet.dataset.mode = prefs.magnet;
  setState(ctl.eraser, { on: erasing(), pressed: erasing() });
  setState(ctl.stay, { on: prefs.stay, pressed: prefs.stay });
  const sel = d ? selectionOf(d) : [];
  // A read-only selection leaves these three nothing they could change.
  const none = !sel.some((id) => isEditable(d.get(id)));
  const locked = !none && allLocked(sel);
  const hidden = !none && allHidden(sel);
  setState(ctl.lock, { off: none, on: locked, pressed: locked, glyph: locked ? 'lock' : 'unlock' });
  setState(ctl.eye, { off: none, on: hidden, pressed: hidden, glyph: hidden ? 'eye-off' : 'eye' });
  setState(ctl.trash, { off: none });
  setState(ctl.undo, { off: !historyReady('undo', 1) });
  setState(ctl.redo, { off: !historyReady('redo', 1) });
  // The accessible name follows the tip now, not what it said when it was
  // built or last hovered (the trash counts what it deletes).
  for (const b of Object.values(ctl)) refreshTipLabel(b);
}

let favWrap = null;

function renderFavorites() {
  if (!favWrap) return;
  favWrap.innerHTML = '';
  const favs = prefs.favorites.filter(hasDrawingTool);
  if (!favs.length) return;
  favWrap.appendChild(sep());
  for (const id of favs) favWrap.appendChild(favoriteButton(id));
}

export function buildRail() {
  ensureChrome();
  const rail = el('rail');
  rail.innerHTML = '';
  rail.setAttribute('role', 'toolbar');
  rail.setAttribute('aria-orientation', 'vertical');
  rail.setAttribute('aria-label', 'Drawing tools');
  // Rebuilt on demand (the drawing module calls this once the tier has
  // answered), so the listeners go on once and survive the refill.
  if (!rail.dataset.railKeys) {
    rail.dataset.railKeys = '1';
    rail.addEventListener('keydown', onRailKey);
    rail.addEventListener('focusin', (e) => {
      const b = e.target && e.target.closest ? e.target.closest('.rail__btn') : null;
      if (b) setRoving(b);
    });
  }
  rail.appendChild(cursorButton());
  favWrap = document.createElement('div');
  favWrap.className = 'rail__favs';
  rail.appendChild(favWrap);
  renderFavorites();
  rail.appendChild(sep());
  for (const g of RAIL_GROUPS) {
    if (g.sep) { rail.appendChild(sep()); continue; }
    if (toolsOf(g).length) rail.appendChild(groupButton(g));
  }
  rail.appendChild(controlsBlock());
  applyRailCollapsed();
  syncRail(app && app.draw ? app.draw.activeTool() : null);
}

const railButtons = () => Array.from(el('rail').querySelectorAll('.rail__btn'));

/** One tab stop for the whole rail: the arrow keys do the rest. */
function setRoving(target) {
  for (const b of railButtons()) b.tabIndex = b === target ? 0 : -1;
}

let observedDraw = null;
let observedChart = null;

/**
 * Follow the controller the page has now. A chart-type switch builds a
 * new chart and a new controller seeded from the legacy checkbox, so the
 * rail's own modes are re-asserted on it, and the selection and history
 * events of the new chart drive the control states.
 */
function observe() {
  if (app.draw && app.draw !== observedDraw) {
    observedDraw = app.draw;
    applyMagnet();
    applyStay();
  }
  const c = app.chart;
  if (c && c !== observedChart && typeof c.on === 'function') {
    observedChart = c;
    for (const ev of ['drawing:select', 'draw:select', 'drawing:change', 'draw:add', 'draw:remove', 'draw:update', 'draw:paste', 'draw:cut']) {
      c.on(ev, refreshControls);
    }
    // The eraser is a mode the cursor button stands against, so both follow it.
    c.on('draw:eraser', () => syncRail(app.draw ? app.draw.activeTool() : null));
    // The properties bar listens to the chart too, and the old chart is
    // gone: hand it the new one here, where the rebuild is first noticed.
    if (propertiesBar && typeof propertiesBar.attach === 'function') propertiesBar.attach();
  }
}

export function syncRail(tool) {
  tool = tool || null;
  const rail = el('rail');
  if (!rail) return;
  let armed = null;
  for (const b of rail.querySelectorAll('.rail__tool')) {
    const tools = (b.dataset.tools || '').split(',').filter(Boolean);
    // The cursor is the mode with no tool armed and no eraser.
    const on = tool === null ? tools.length === 0 && !erasing() : tools.includes(tool);
    b.classList.toggle('is-on', on);
    b.classList.toggle('is-held', on && latch && tools.length > 0);
    b.setAttribute('aria-pressed', String(on));
    if (on && !armed) armed = b;
    // A group stands for whichever of its tools was armed last, however it
    // was armed: a chord or a paste of a saved layout counts as a pick. The
    // face is tracked on the button itself, since the pick may already have
    // written the preference before the controller answered.
    if (on && b.dataset.group && tools.length) {
      if (prefs.last[b.dataset.group] !== tool) { prefs.last[b.dataset.group] = tool; savePrefs(); }
      if (b.dataset.face !== tool) {
        b.dataset.face = tool;
        b.querySelector('.rail__glyph').innerHTML = toolGlyph(tool);
      }
    }
    // A group's accessible name is the tool it stands for now.
    refreshTipLabel(b);
  }
  const active = document.activeElement;
  if (armed && !(active && rail.contains(active))) setRoving(armed);
  const pick = el('drawtool');
  if (pick) pick.value = tool || '';
  observe();
  refreshControls();
}

// ── keyboard ───────────────────────────────────────────────────────────
const dialogOpen = () => ['chartset', 'setmodal', 'cmpmodal', 'textmodal'].some((id) => { const n = el(id); return n && !n.hidden; });
const railOwnsFocus = () => {
  const a = document.activeElement;
  if (!a) return false;
  const rail = el('rail');
  if (rail && rail.contains(a)) return true;
  const f = flyoutEl();
  return Boolean(f && f.contains(a)) || railMenuOpen();
};

/** Arrow keys walk the rail, ArrowRight opens a group, Escape hands focus back to the chart. */
function onRailKey(e) {
  const btns = railButtons();
  const cur = e.target && e.target.closest ? e.target.closest('.rail__btn') : null;
  const at = btns.indexOf(cur);
  const go = (i) => {
    const b = btns[(i + btns.length) % btns.length];
    setRoving(b);
    b.focus();
  };
  switch (e.key) {
    case 'ArrowDown': go(at + 1); break;
    case 'ArrowUp': go(at - 1); break;
    case 'Home': go(0); break;
    case 'End': go(btns.length - 1); break;
    case 'ArrowRight':
      if (cur && cur.dataset.group) openGroupFlyout(groupById(cur.dataset.group), cur, true);
      else return;
      break;
    case 'Escape': {
      closeFlyout();
      closeRailMenu();
      hideRailTip();
      const chart = el('chart');
      if (chart && typeof chart.focus === 'function') chart.focus();
      else if (cur) cur.blur();
      break;
    }
    default: return;
  }
  e.preventDefault();
  e.stopPropagation();
}

/**
 * The drawing keyboard. The tier installs no listener and answers two
 * questions instead: `matchDrawingShortcut` (which tool this chord arms)
 * and `keyToDrawingAction` (what this key means for the selection or the
 * placement in hand). Everything acted on here is claimed, so the engine's
 * own arrow-key pan does not also fire on a nudge; Escape is left to
 * propagate, because leaving a tool and closing a menu on one press is
 * what the page did before. Copy, cut and paste are the clipboard
 * module's and pass through untouched.
 */
function onGlobalKey(e) {
  if (inTextField(e) || dialogOpen() || railOwnsFocus() || app.alertUi?.isOpen() || app.alertUi2?.isOpen()) return;
  const d = activeDraw();
  if (!d) return;
  const claim = () => { e.preventDefault(); e.stopPropagation(); };
  const tool = matchDrawingShortcut(e);
  if (tool) {
    setDrawLock(false);
    d.setTool(tool);
    if (d === app.draw) syncRail(tool);
    claim();
    return;
  }
  const action = keyToDrawingAction(e, {
    hasSelection: d.selected() !== null,
    hasTarget: typeof d.hovered === 'function' && d.hovered() !== null,
    editingText: false,
    // A ruler or the eraser takes Escape the way a tool being placed does.
    placing: d.activeTool() !== null || (typeof d.measuring === 'function' && d.measuring())
      || (typeof d.erasing === 'function' && d.erasing()),
  });
  if (!action) {
    // The focused chart's alert is a fallback only after drawing ownership.
    const alerts = d === app.draw2 ? app.alerts2 : app.alerts;
    const alertId = alerts?.hovered();
    if (alertId === undefined || d.activeTool() !== null
        || (e.key !== 'Delete' && e.key !== 'Backspace')
        || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    alerts.remove(alertId);
    claim();
    refreshControls();
    return;
  }
  const targets = () => {
    const sel = selectionOf(d);
    if (sel.length) return sel;
    const h = typeof d.hovered === 'function' ? d.hovered() : null;
    return h ? [h] : [];
  };
  switch (action.type) {
    // The focused chart's timeline, which holds its drawings with everything else.
    case 'undo': historyPress('undo', d === app.draw2 ? 2 : 1); break;
    case 'redo': historyPress('redo', d === app.draw2 ? 2 : 1); break;
    case 'delete': for (const id of targets()) d.remove(id); break;
    case 'duplicate': if (typeof d.duplicate === 'function') d.duplicate(targets()); break;
    case 'nudge': if (typeof d.nudge === 'function') d.nudge(targets(), action.dx, action.dy); break;
    case 'cancel':
      d.cancel();
      if (d.activeTool() === null) setDrawLock(false);
      e.preventDefault();
      refreshControls();
      return;
    case 'finish': d.finish(); break;
    case 'popAnchor': d.popAnchor(); break;
    default: return;   // copy, cut, paste
  }
  claim();
  refreshControls();
}

// ── the properties bar seam ────────────────────────────────────────────
// The bar for a selected drawing is its own module, mounted here with the
// stage as its anchor. The drawing module keeps calling the three entry
// points it always did; they forward to the mounted bar and do nothing
// until one is mounted, so the page loads either way.
let propertiesBar = null;

export const propertiesBarHandle = () => propertiesBar;

export function showWidget(id) {
  if (!propertiesBar) return;
  if (id) { if (typeof propertiesBar.show === 'function') propertiesBar.show(id); }
  else if (typeof propertiesBar.hide === 'function') propertiesBar.hide();
}
export function positionWidget() {
  if (propertiesBar && typeof propertiesBar.reposition === 'function') propertiesBar.reposition();
}
export function openTextDialog(id) {
  if (propertiesBar && typeof propertiesBar.editText === 'function') propertiesBar.editText(id);
}

/**
 * `opts.mountPropertiesBar(app, anchorEl)` builds the properties bar for
 * the selected drawing and returns its handle (`show`, `hide`,
 * `reposition`, `editText`, `destroy`). The anchor is the stage the rail
 * sits in, so a bar docked to it comes along into chart-only full screen.
 */
export function initRail(a, opts = {}) {
  app = a;
  initHistory(a);
  loadPrefs();
  const rail = el('rail');
  if (typeof opts.mountPropertiesBar === 'function') {
    propertiesBar = opts.mountPropertiesBar(app, rail ? rail.parentElement : document.body) || null;
  }
  ensureChrome();
  // A study or a pane changes what Undo would do without any drawing event.
  onHistoryChange(refreshControls);
  window.addEventListener('keydown', onGlobalKey, true);
  const closeAll = () => { closeFlyout(); closeRailMenu(); hideRailTip(); };
  window.addEventListener('blur', closeAll);
  window.addEventListener('resize', closeAll);
  // The shell bar still toggles the legacy checkbox; follow it, so the two
  // never disagree about whether the magnet is on.
  const box = el('magnet');
  if (box) {
    box.addEventListener('change', () => {
      if (box.checked && prefs.magnet === 'off') setMagnetMode('strong');
      else if (!box.checked && prefs.magnet !== 'off') setMagnetMode('off');
    });
  }
}

/** Scale the current logical range around its center through the chart's public API. */
export function zoomVisibleRange(chart, factor) {
  if (!chart || typeof chart.getVisibleLogicalRange !== 'function'
      || typeof chart.setVisibleLogicalRange !== 'function'
      || chart.navigationOptions?.().zoomEnabled === false
      || !Number.isFinite(factor) || factor <= 0) return false;
  const range = chart.getVisibleLogicalRange();
  if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to) || range.to <= range.from) return false;
  const scale = chart.timeScale;
  if (!scale || !(scale.width > 0) || typeof scale.constrainBarSpacing !== 'function') return false;
  const spacing = scale.width / (range.to - range.from);
  const legalSpacing = scale.constrainBarSpacing(spacing / factor);
  if (Math.abs(legalSpacing - spacing) <= Number.EPSILON * Math.max(1, spacing)) return false;
  const center = (range.from + range.to) / 2;
  const half = scale.width / legalSpacing / 2;
  chart.setVisibleLogicalRange({ from: center - half, to: center + half });
  return true;
}

/** Update buttons in place so policy changes do not close an open toolbar dialog. */
export function syncNavigationControls() {
  if (!app) return;
  const allowed = chart => Boolean(chart && chart.isDestroyed !== true && chart.navigationOptions?.().zoomEnabled !== false);
  const selected = allowed(activeChart());
  for (const id of ['mobile-zoom-in', 'mobile-zoom-out', 'mobile-fit', 'toolbar-fit', 'fit']) {
    const control = el(id);
    if (!control) continue;
    control.disabled = !(id === 'fit' ? allowed(app.chart) : selected);
    control.setAttribute('aria-disabled', String(control.disabled));
  }
}

/** Keep the compact picker and stateful controls aligned with the shared host state. */
export function syncMobileControls(tool) {
  syncNavigationControls();
  const picker = el('mobile-draw');
  if (picker) picker.value = tool || '';
  const magnet = el('mobile-magnet');
  if (magnet) {
    const mode = magnetMode();
    magnet.textContent = 'Magnet: ' + mode;
    magnet.setAttribute('aria-pressed', String(mode !== 'off'));
  }
  const undo = el('mobile-undo');
  const redo = el('mobile-redo');
  if (undo) undo.disabled = !historyReady('undo');
  if (redo) redo.disabled = !historyReady('redo');
}

/** Follow history changes regardless of whether they came from touch, keyboard or another host control. */
export function observeMobileControls(chart, draw) {
  if (!chart || typeof chart.on !== 'function') return;
  if (!navigationObserved.has(chart)) {
    navigationObserved.add(chart);
    for (const event of ['objects:change', 'state:restore:end', 'destroy']) chart.on(event, syncNavigationControls);
  }
  if (!draw || mobileObserved.has(chart)) return;
  mobileObserved.add(chart);
  for (const event of ['drawing:select', 'draw:select', 'drawing:change', 'draw:add', 'draw:remove', 'draw:update', 'draw:paste', 'draw:cut']) {
    chart.on(event, () => {
      if (draw === activeDraw()) syncMobileControls(draw.activeTool());
    });
  }
}

function setMobileTool(tool) {
  const draw = activeDraw();
  if (!draw) return;
  setDrawLock(false);
  draw.setTool(tool || null);
  if (draw === app.draw) syncRail(tool || null);
  syncMobileControls(tool || null);
}

/** Wire the host-owned touch bar to the same controllers and actions as the desktop chrome. */
export function initMobile(a) {
  app = a;
  initHistory(a);
  const picker = el('mobile-draw');
  if (!picker) return;
  picker.innerHTML = '';
  const cursor = document.createElement('option');
  cursor.value = '';
  cursor.textContent = 'Drawing tool';
  picker.appendChild(cursor);
  for (const tool of BUILTIN_DRAWING_TOOLS) {
    const option = document.createElement('option');
    option.value = tool.id;
    option.textContent = tool.name;
    picker.appendChild(option);
  }

  picker.addEventListener('change', () => setMobileTool(picker.value));
  el('mobile-cursor').addEventListener('click', () => setMobileTool(null));
  el('mobile-undo').addEventListener('click', () => { historyPress('undo'); syncMobileControls(activeDraw()?.activeTool()); });
  el('mobile-redo').addEventListener('click', () => { historyPress('redo'); syncMobileControls(activeDraw()?.activeTool()); });
  onHistoryChange(() => syncMobileControls(activeDraw()?.activeTool()));
  el('mobile-magnet').addEventListener('click', () => { cycleMagnet(); syncMobileControls(activeDraw()?.activeTool()); });
  el('mobile-zoom-out').addEventListener('click', () => zoomVisibleRange(activeChart(), 1.25));
  el('mobile-zoom-in').addEventListener('click', () => zoomVisibleRange(activeChart(), 0.8));
  el('mobile-fit').addEventListener('click', () => { const chart = activeChart(); if (chart && chart.navigationOptions?.().zoomEnabled !== false) chart.resetScale(); });

  el('mobilebar').addEventListener('pointerdown', (event) => event.stopPropagation());
  for (const [id, pane] of [['chart', 1], ['chart2', 2]]) {
    const node = el(id);
    if (!node) continue;
    node.tabIndex = 0;
    node.addEventListener('pointerdown', () => focusChart(pane));
    node.addEventListener('focusin', () => focusChart(pane));
  }
  focusChart(app.focusPane);
  observeMobileControls(app.chart, app.draw);
  observeMobileControls(app.chart2, app.draw2);
  syncMobileControls(activeDraw()?.activeTool());
}

// ── stylesheet ─────────────────────────────────────────────────────────
// The rail's own rules, injected once beside the flyout's. They sit on top
// of the page stylesheet's `.rail` box (position, width, background) and
// replace its button rules: a tool glyph and a chrome glyph each sit at the
// size their tier is drawn for, and every tint is a class.
export const RAIL_CSS = `
.rail { padding: 6px 0 0; gap: 2px; overflow-x: hidden; scrollbar-width: none; }
.rail::-webkit-scrollbar { width: 0; height: 0; }
.rail:focus { outline: none; }
.rail .rail__btn { position: relative; width: 32px; height: 30px; padding: 0; display: grid; place-items: center;
  flex: none; background: transparent; border: 1px solid transparent; border-radius: 6px; color: var(--mut);
  cursor: pointer; transition: background .09s, color .09s, border-color .09s; }
.rail .rail__btn:hover { background: var(--elev); color: var(--tx); }
.rail .rail__btn:focus-visible { outline: 2px solid var(--acc-2); outline-offset: -2px; }
.rail .rail__btn.is-on { background: var(--on-bg); border-color: var(--on-bd); color: var(--acc-2); }
.rail .rail__btn.is-weak { color: var(--acc-2); }
.rail .rail__btn.is-off { color: var(--faint); cursor: default; }
.rail .rail__btn.is-off:hover { background: transparent; color: var(--faint); }
.rail .rail__btn--danger:not(.is-off):hover { color: var(--danger-tx); }
.rail .rail__glyph { display: grid; place-items: center; width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; line-height: 0; }
.rail .rail__glyph > svg { width: ${ICON_SIZE}px; height: ${ICON_SIZE}px; fill: none; stroke: currentColor;
  stroke-width: ${ICON_STROKE}; stroke-linecap: round; stroke-linejoin: round; }
.rail .rail__btn--chrome .rail__glyph > svg { width: ${CHROME_ICON_SIZE}px; height: ${CHROME_ICON_SIZE}px;
  stroke-width: ${CHROME_ICON_STROKE}; }
.rail .rail__chev { position: absolute; right: 0; bottom: 0; width: 13px; height: 13px; display: grid;
  place-items: center; border-radius: 5px 0 6px 0; color: var(--mut); opacity: 0; transition: opacity .1s, background .1s; }
.rail .rail__chev > svg { width: 9px; height: 9px; fill: none; stroke: currentColor; stroke-width: 2.2;
  stroke-linecap: round; stroke-linejoin: round; }
.rail .rail__btn:hover .rail__chev, .rail .rail__btn:focus-visible .rail__chev,
.rail .rail__btn[aria-expanded="true"] .rail__chev { opacity: 1; }
.rail .rail__chev:hover { background: var(--elev-2); color: var(--tx); }
.rail .rail__btn.is-held::after, .rail .rail__btn[data-mode="weak"]::after,
.rail .rail__btn[data-mode="strong"]::after { content: ''; position: absolute; top: 3px; right: 3px;
  width: 5px; height: 5px; border-radius: 50%; }
.rail .rail__btn.is-held::after, .rail .rail__btn[data-mode="strong"]::after { background: var(--acc-2); }
.rail .rail__btn[data-mode="weak"]::after { border: 1.5px solid var(--acc-2); width: 4px; height: 4px; }
.rail .rail__sep { width: 22px; height: 1px; background: var(--bd-soft); margin: 4px 0; flex: none; }
.rail .rail__favs { display: contents; }
.rail .rail__ctl { margin-top: auto; position: sticky; bottom: 0; display: flex; flex-direction: column;
  align-items: center; gap: 2px; width: 100%; padding: 4px 0 6px; background: var(--panel-2);
  border-top: 1px solid var(--bd-soft); flex: none; }
/* Tools that scroll under the controls fade out instead of being cut through. */
.rail .rail__ctl::before { content: ''; position: absolute; left: 0; right: 0; bottom: 100%; height: 14px;
  background: linear-gradient(to bottom, transparent, var(--panel-2)); pointer-events: none; }
.rail .rail__ctl .rail__sep { margin: 3px 0; }
.rail.is-collapsed { display: none; }
.rail-tab { position: absolute; left: 0; bottom: 34px; z-index: 21; width: 16px; height: 26px; padding: 0;
  display: grid; place-items: center; background: var(--panel-2); color: var(--mut); cursor: pointer;
  border: 1px solid var(--bd-soft); border-left: 0; border-radius: 0 6px 6px 0;
  transition: background .09s, color .09s, width .09s; }
.rail-tab:hover { width: 20px; background: var(--elev); color: var(--tx); }
.rail-tab:focus-visible { outline: 2px solid var(--acc-2); outline-offset: -2px; }
.rail-tab > svg { width: 12px; height: 12px; }
.rail-tab[hidden] { display: none; }
/* A full-screen second chart holds the rail in its own pane, so its offset follows the fold there. */
body[data-fullscreen-pane="2"] .p2plot:not(.has-rail) #chart2,
body[data-fullscreen-pane="2"] .p2plot:not(.has-rail) .inspect-layout { left: 0; }
@media (prefers-reduced-motion: reduce) { .rail .rail__btn, .rail .rail__chev { transition: none; } }
`;
