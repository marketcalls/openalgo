import * as engine from '/dist/openalgo-charts.mjs';
import { el, fmt, esc, inTextField, MOD } from './ui.js';
import { snapPrice } from './ticks.js';
import { ticon } from './toolbar.js';
import { openSettings, rememberIndicators, renderIndicatorChips } from './indicators.js';
import { openChartSettings } from './chart-settings.js';
import { volumeShown, setVolumeShown } from './volume.js';
import { placeOrder, removeAllOrders, clearPosition, saveState } from './orders.js';
import { removeBracket } from './bracket.js';
import { clipboardAction } from './clipboard.js';
import { autosave } from './persist.js';
import { alertContextEntries } from './alerts.js';
import { addSessionMark, sessionMarks, clearSessionMarks } from './session-marks.js';
import { addHostStudy, hostStudy, removeHostStudy, studyAllows } from './host-study.js';
import { capturePaneTarget } from './pane-target.js';
import { asStep } from './history.js';

// Price-level family (previous close, session extremes, extended hours,
// bid/ask). Read off the namespace for the same reason as the block above:
// an older dist/ should still draw a chart, with the level submenus simply
// reporting themselves unavailable.
const { PRICE_LEVEL_KINDS, lastPriceLevelFromSeriesStyle, seriesStyleForLastPriceLevel } = engine;

let app;
// The three menu hosts. Looked up once the document is ready, in initMenus.
let ctxMenu = null;
let axMenu = null;
let axSub = null;

// ── right-click menu: order entry, drawings, settings ──────────────
// Raised from the chart's own `contextmenu` event rather than a DOM listener
// on the container. The event carries the price, the pane and a classified
// target, which is the part a canvas cannot tell a host by itself: it is how
// the indicator row below knows which instance was under the pointer.
let ctxPrice = 0;
let ctxTime = null;        // the bar time a session mark anchors to
let ctxIndicator = null;   // instance id when the pointer was over an indicator
let ctxAlerts = [];
let ctxOwner = null;
let ctxPane = null;        // the pane row's action, when the pointer was over a study pane
let ctxMoves = [];         // the pane's up and down rows, when there is another pane to swap with
export const hideCtx = () => { ctxMenu.hidden = true; };

/**
 * Where the price pane sits. It can be moved below the studies, so "the price
 * pane" is asked of the chart rather than assumed to be the top one; an
 * engine that predates the move always keeps it there.
 */
export const pricePane = (chart) => (typeof chart?.primaryPaneIndex === 'function' ? chart.primaryPaneIndex() : 0);

/**
 * The pane row: fold a study pane to its header strip, or open it again. The
 * strip keeps the pane's studies, drawings and height, so this is a view
 * choice, not an edit. Null over the price pane, which always stays open in
 * whatever slot it sits, and on an engine that predates pane collapse.
 */
export function paneCollapseRow(chart, paneIndex) {
  if (typeof chart?.paneCollapsed !== 'function' || !(paneIndex >= 0) || paneIndex === pricePane(chart)) return null;
  const folded = chart.paneCollapsed(paneIndex);
  return { label: folded ? 'Expand pane' : 'Collapse pane',
    onSelect: () => { chart.setPaneCollapsed(paneIndex, !folded); } };
}

/**
 * The move rows: the pane under the pointer up or down one slot. Every pane
 * moves, the price pane included, which is how a trader puts the price below
 * the studies or back on top; this host builds its charts with
 * `movablePrimaryPane` for that. A row at an edge stays in the menu, greyed,
 * so the pair keeps its place, and so does one the chart would refuse because
 * it keeps its price pane pinned on top. Empty on a single pane and on an
 * engine that predates the move.
 */
export function paneMoveRows(chart, paneIndex) {
  if (typeof chart?.movePane !== 'function' || typeof chart.primaryPaneIndex !== 'function') return [];
  const count = chart.panes().length;
  if (count < 2 || !(paneIndex >= 0 && paneIndex < count)) return [];
  const price = chart.primaryPaneIndex();
  const pinned = typeof chart.movablePrimaryPane === 'function' && !chart.movablePrimaryPane();
  const row = (label, direction, edge, edgeReason) => {
    const reason = edge ? edgeReason
      : pinned && (paneIndex === price || paneIndex + direction === price) ? 'The price pane stays on top on this chart' : '';
    return { label, disabled: reason !== '', reason, onSelect: () => { chart.movePane(paneIndex, direction); } };
  };
  return [
    row('Move pane up', -1, paneIndex === 0, 'Already the top pane'),
    row('Move pane down', 1, paneIndex === count - 1, 'Already the bottom pane'),
  ];
}

/**
 * What the menu's drawing rows reach. `removable` counts what Remove All
 * would take, `deletable` is the selection Delete and Cut act on (null when
 * it is read-only), `copyable` is the selection Copy takes, and `marks`
 * counts the session marks the host would clear.
 */
export function drawingMenuState(draw) {
  const selected = draw ? draw.selected() : null;
  const primary = selected ? draw.get(selected) : undefined;
  return {
    removable: draw ? draw.drawings().filter((d) => d.policy?.editable !== false).length : 0,
    deletable: primary && primary.policy?.editable !== false ? selected : null,
    copyable: selected,
    marks: sessionMarks(draw).length,
  };
}

export function openContextMenu(e, pane = 1) {
  const owner = capturePaneTarget(app, pane);
  if (!owner) return;
  if (pane === 2) {
    hideCtx(); closeAxisMenu();
    const rect = el('chart2').getBoundingClientRect();
    const rows = alertContextEntries(app, e, 2);
    rows.push({ label: 'Chart settings...', onSelect: () => openChartSettings(undefined, owner) });
    if (app.volume2) rows.push({ label: 'Volume', on: volumeShown(2), check: true,
      onSelect: () => { if (owner.current()) setVolumeShown(!volumeShown(2), 2); } });
    if (e.target?.kind === 'indicator') {
      // A study its host protects keeps the row, greyed with the reason.
      const study = owner.chart.indicators().find((item) => item.id === e.target.instanceId);
      const allowed = studyAllows(study, 'configurable');
      rows.push({ label: 'Study settings...', disabled: !allowed, reason: allowed ? undefined : 'protected by the host',
        onSelect: () => openSettings(e.target.instanceId, owner) });
    }
    const onAxis = e.target?.kind === 'time-scale';
    for (const move of onAxis ? [] : paneMoveRows(owner.chart, e.paneIndex)) {
      rows.push({ label: move.label, disabled: move.disabled, reason: move.reason, onSelect: () => { if (owner.current()) move.onSelect(); } });
    }
    const paneRow = onAxis ? null : paneCollapseRow(owner.chart, e.paneIndex);
    if (paneRow) rows.push({ label: paneRow.label, onSelect: () => { if (owner.current()) paneRow.onSelect(); } });
    if (rows.length) popupMenu({ getBoundingClientRect: () => ({ left: rect.left + e.point.x, bottom: rect.top + e.point.y }) }, rows, { role: 'menu' });
    return;
  }
  closeMenu();
  ctxOwner = owner;
  const rect = el('chart').getBoundingClientRect();
  const target = e.target || { kind: 'empty' };
  // A price ladder gets its own menu. The chart is what knows a click landed
  // on an axis strip and which of the pane's scales that strip draws, so this
  // is the one branch that cannot be worked out from the pointer alone.
  if (target.kind === 'price-scale') { openAxisMenu(e, target); return; }
  closeAxisMenu();
  // Off the plot (on a scale) there is no price, so the order rows would be
  // offering to trade at nothing.
  const tradable = e.paneIndex === pricePane(app.chart) && e.price != null && app.currentBars.length > 0;
  ctxPrice = tradable ? snapPrice(app.ticks, e.price) : 0;
  for (const b of ctxMenu.querySelectorAll('button[data-type]')) {
    b.hidden = !tradable;
    const verb = b.getAttribute('data-side') === 'BUY' ? 'Buy' : 'Sell';
    const type = b.getAttribute('data-type');
    b.textContent = type === 'MARKET' ? `${verb} market`
      : type === 'LIMIT' ? `${verb} limit @ ${fmt(ctxPrice)}`
      : `${verb} stop (SL) @ ${fmt(ctxPrice)}`;
  }
  for (const hr of ctxMenu.querySelectorAll('hr[data-sec="order"]')) hr.hidden = !tradable;

  ctxAlerts = alertContextEntries(app, e);
  const create = ctxAlerts.length > 1 ? ctxAlerts[0] : null;
  const createRow = ctxMenu.querySelector('[data-act="alert-create"]');
  createRow.hidden = !create;
  createRow.disabled = create?.disabled === true;
  createRow.title = create?.reason || '';
  createRow.textContent = create?.label || 'Create alert';
  ctxMenu.querySelector('[data-act="alert-list"]').hidden = ctxAlerts.length === 0;
  ctxMenu.querySelector('hr[data-sec="alerts"]').hidden = ctxAlerts.length === 0;

  // Hide the drawing rows when there is nothing to act on, so the menu
  // never offers a dead option. A read-only drawing (a session mark) is
  // neither counted for removal nor offered for delete or cut.
  const drawState = drawingMenuState(app.draw);
  const rowAll = ctxMenu.querySelector('[data-act="delall"]');
  const rowSel = ctxMenu.querySelector('[data-act="delsel"]');
  const rowMark = ctxMenu.querySelector('[data-act="mark"]');
  const rowUnmark = ctxMenu.querySelector('[data-act="unmark"]');
  ctxTime = e.time ?? app.currentBars.at(-1)?.time ?? null;
  rowAll.hidden = drawState.removable === 0;
  rowSel.hidden = !drawState.deletable;
  rowMark.hidden = !app.draw || !tradable || ctxTime === null;
  rowUnmark.hidden = drawState.marks === 0;
  // The separator above the group.
  rowSel.previousElementSibling.hidden = rowAll.hidden && rowSel.hidden && rowMark.hidden && rowUnmark.hidden;
  if (drawState.removable > 0) rowAll.textContent = `Remove all drawings (${drawState.removable})`;
  if (!rowMark.hidden) rowMark.textContent = `Mark ${fmt(ctxPrice)} for this session`;
  if (drawState.marks > 0) rowUnmark.textContent = `Clear session marks (${drawState.marks})`;

  // Clipboard rows. Copy and cut need a selection; paste does not, because
  // whether there is anything of ours to paste can only be known by asking
  // the clipboard, which is asynchronous. A dist/ whose controller has no
  // copy() hides the three rather than offering three dead options.
  const clipOk = app.draw && typeof app.draw.copy === 'function';
  ctxMenu.querySelector('[data-act="copy"]').hidden = !clipOk || !drawState.copyable;
  ctxMenu.querySelector('[data-act="cut"]').hidden = !clipOk || !drawState.deletable;
  ctxMenu.querySelector('[data-act="paste"]').hidden = !clipOk;
  ctxMenu.querySelector('hr[data-sec="clip"]').hidden = !clipOk;
  // The handlers take Cmd on a Mac, where Control-click is a right click.
  for (const [act, key] of [['copy', 'C'], ['cut', 'X'], ['paste', 'V']]) {
    const row = ctxMenu.querySelector(`[data-act="${act}"]`);
    const em = row?.querySelector('em');
    if (em) em.textContent = `${MOD}+${key}`;
    row?.setAttribute('aria-keyshortcuts', `${MOD === 'Cmd' ? 'Meta' : 'Control'}+${key}`);
  }

  // The indicator row appears only where there is an indicator to settle.
  ctxIndicator = target.kind === 'indicator' ? target.instanceId : null;
  const rowInd = ctxMenu.querySelector('[data-act="indset"]');
  rowInd.hidden = !ctxIndicator;
  ctxMenu.querySelector('hr[data-sec="ind"]').hidden = !ctxIndicator;
  if (ctxIndicator) {
    const inst = app.chart.indicators().find((i) => i.id === ctxIndicator);
    rowInd.textContent = (inst ? inst.name : 'Indicator') + ' settings...';
    // Greyed with its reason on a study whose host keeps its settings.
    rowInd.disabled = !studyAllows(inst, 'configurable');
    rowInd.title = rowInd.disabled ? 'protected by the host' : '';
  }
  // The host's own protected study: one row adds it, the same row takes it away.
  const rowHost = ctxMenu.querySelector('[data-act="hoststudy"]');
  if (rowHost) {
    rowHost.hidden = !app.chart || !app.currentBars?.length;
    rowHost.textContent = hostStudy(app.chart) ? 'Remove protected VWAP' : 'Add protected VWAP';
  }

  ctxPane = target.kind === 'time-scale' ? null : paneCollapseRow(app.chart, e.paneIndex);
  ctxMoves = target.kind === 'time-scale' ? [] : paneMoveRows(app.chart, e.paneIndex);
  const rowPane = ctxMenu.querySelector('[data-act="panecollapse"]');
  rowPane.hidden = !ctxPane;
  if (ctxPane) rowPane.textContent = ctxPane.label;
  ['paneup', 'panedown'].forEach((act, i) => {
    const row = ctxMenu.querySelector(`[data-act="${act}"]`);
    if (!row) return;
    const move = ctxMoves[i];
    row.hidden = !move;
    row.disabled = move?.disabled === true;
    row.title = move?.reason || '';
  });
  ctxMenu.querySelector('hr[data-sec="pane"]').hidden = !ctxPane && ctxMoves.length === 0;

  // Volume is a fixture of a time-indexed chart only: a Renko brick or a
  // P&F column has no source bar to hang it off, so `render()` leaves the
  // series null and the row would have nothing to switch.
  const rowVol = ctxMenu.querySelector('[data-act="volshow"]');
  rowVol.hidden = !app.volume;
  ctxMenu.querySelector('hr[data-sec="vol"]').hidden = !app.volume;
  rowVol.classList.toggle('is-on', volumeShown(1));
  rowVol.setAttribute('aria-checked', String(volumeShown(1)));

  // Unhide first, then measure: the menu's height depends on which rows
  // above survived, so a fixed clamp would be wrong for most of them.
  ctxMenu.hidden = false;
  ctxMenu.style.left = Math.max(4, Math.min(rect.left + e.point.x, window.innerWidth - ctxMenu.offsetWidth - 8)) + 'px';
  ctxMenu.style.top = Math.max(4, Math.min(rect.top + e.point.y, window.innerHeight - ctxMenu.offsetHeight - 8)) + 'px';
}

// ── price-axis menu ────────────────────────────────────────────────────
// Everything here reads `chart.priceAxisState(pane, scale)` and writes back
// through the matching `priceAxis*` calls, so the menu can never claim a
// state the axis is not in. Nothing is hardcoded per axis: the same code
// serves the price ladder, a left-hand scale, and an indicator pane's.
// Which axis the menu (and the chords, which have no pointer) act on. The
// price ladder of the price pane until a right-click names another; null
// means that one, found where the price pane sits now, since it can move.
let axTarget = { paneIndex: null, scaleId: 'right' };
const axPane = () => axTarget.paneIndex ?? pricePane(app.chart);
let axSubHalf = null;   // 'line' | 'label' while a level flyout is open

const AX_TICK = '<svg viewBox="0 0 20 20"><path d="M4 10.5l4 4 8-9"/></svg>';
const AX_ARROW = '<svg viewBox="0 0 20 20"><path d="M8 5l5 5-5 5"/></svg>';
const POPUP_TICK = '<svg viewBox="0 0 20 20" width="12" height="12"><path d="M4 10.5l4 4 8-9"/></svg>';
/**
 * The four modes as one choice. A radio group and not four switches: the
 * scale holds exactly one mode, and four checkboxes would let a user ask for
 * a state the engine cannot be in.
 */
export const AX_MODES = [
  { value: 'linear', label: 'Linear', chord: 'Alt+R' },
  { value: 'logarithmic', label: 'Logarithmic', chord: 'Alt+L' },
  { value: 'percentage', label: 'Percent', chord: 'Alt+P' },
  { value: 'indexed-to-100', label: 'Indexed to 100', chord: 'Alt+1' },
];
const AX_AUTOFIT_CHORD = 'Alt+A';
const AX_INVERT_CHORD = 'Alt+I';
/** Our wording for the level family, in the order the engine lists it. */
export const LEVEL_LABEL = {
  previousClose: 'Previous close',
  sessionHigh: 'Session high',
  sessionLow: 'Session low',
  lastPrice: 'Last price',
  preMarketOpen: 'Pre-market open',
  preMarketClose: 'Pre-market close',
  postMarketOpen: 'Post-market open',
  postMarketClose: 'Post-market close',
  bid: 'Bid',
  ask: 'Ask',
};
const levelKinds = () => PRICE_LEVEL_KINDS || Object.keys(LEVEL_LABEL);

export const axisState = () => (app.chart && typeof app.chart.priceAxisState === 'function')
  ? app.chart.priceAxisState(axPane(), axTarget.scaleId)
  : null;

const axisPlacement = () => app.chart?.priceAxisPlacement?.(axPane(), axTarget.scaleId) ?? null;
const axisColumns = side => (app.chart?.priceAxisLayout?.(axPane()) ?? [])
  .filter(column => column.side === side).sort((a, b) => a.order - b.order);

/**
 * One menu row. `mark` picks the marker column: a tick for a switch, a dot
 * for one option of a choice. The column is drawn either way, so the labels
 * keep one left edge whether anything is set or not.
 */
function axRow(o) {
  const b = document.createElement('button');
  b.className = 'axrow' + (o.on ? ' is-on' : '');
  b.disabled = o.disabled === true;
  // What the marker column shows, said to a reader: a scale mode is one of a
  // set, a switch is checked or not, and anything else is a plain action.
  b.setAttribute('role', o.mark === 'radio' ? 'menuitemradio' : typeof o.on === 'boolean' ? 'menuitemcheckbox' : 'menuitem');
  if (o.mark === 'radio' || typeof o.on === 'boolean') b.setAttribute('aria-checked', String(o.on === true));
  const mark = document.createElement('span');
  mark.className = 'axmark';
  if (o.mark === 'radio') {
    const dot = document.createElement('span');
    dot.className = 'axdot';
    mark.appendChild(dot);
  } else if (o.on) {
    mark.innerHTML = AX_TICK;
  }
  const name = document.createElement('span');
  name.className = 'axname';
  name.textContent = o.label;
  b.append(mark, name);
  // Why a row is dead is worth a word: an empty greyed row reads as a bug.
  if (o.note) {
    const note = document.createElement('span');
    note.className = 'axnote';
    note.textContent = o.note;
    b.appendChild(note);
  }
  if (o.chord) {
    const chord = document.createElement('span');
    chord.className = 'chord';
    chord.textContent = o.chord;
    chord.setAttribute('aria-hidden', 'true');
    b.appendChild(chord);
    b.setAttribute('aria-keyshortcuts', o.chord);
  }
  if (o.submenu) {
    const arrow = document.createElement('span');
    arrow.className = 'axarrow';
    arrow.setAttribute('aria-hidden', 'true');
    arrow.innerHTML = AX_ARROW;
    b.appendChild(arrow);
    b.setAttribute('aria-haspopup', 'menu');
    b.dataset.submenu = o.submenu;   // so a repaint can find the open row again
    b.addEventListener('pointerenter', () => openAxisSub(o.submenu, b));
    b.addEventListener('click', () => openAxisSub(o.submenu, b));
  } else {
    // Only rows of the parent menu dismiss the flyout on hover. Wiring this
    // to every row would make the flyout close the moment the pointer
    // reached one of its own, which is what a level row is for.
    if (o.closesSub) b.addEventListener('pointerenter', closeAxisSub);
    if (o.onSelect) b.addEventListener('click', o.onSelect);
  }
  return b;
}

const axSeparator = () => document.createElement('hr');
function axHead(text) {
  const h = document.createElement('div');
  h.className = 'axhead';
  h.textContent = text;
  return h;
}

function paintAxisMenu() {
  const s = axisState();
  axMenu.innerHTML = '';
  if (!s) {
    axMenu.appendChild(axRow({
      label: 'Price-axis controls', disabled: true, note: 'not in this build of dist/',
    }));
    return;
  }
  const add = (o) => axMenu.appendChild(axRow({ closesSub: true, ...o }));

  add({
    label: 'Auto-fit to the data', on: s.autoFit, chord: AX_AUTOFIT_CHORD,
    onSelect: () => runAxis(() => setAxisAutoFit(!s.autoFit)),
  });
  const primaryScale = () => {
    const primary = app.chart?.primarySeries?.();
    return primary != null && primary.priceScale() === app.chart.panes()[axPane()]?.scaleFor(axTarget.scaleId);
  };
  if (primaryScale() && typeof app.chart.setPriceOnlyAutoScale === 'function') add({
    label: 'Fit primary prices only', on: app.chart.priceOnlyAutoScale(),
    onSelect: () => runAxis(() => {
      if (primaryScale()) app.chart.setPriceOnlyAutoScale(!app.chart.priceOnlyAutoScale());
    }),
  });
  add({
    label: 'Invert', on: s.inverted, chord: AX_INVERT_CHORD,
    onSelect: () => runAxis(() => setAxisInvert(!s.inverted)),
  });
  // Our own words for holding the price-per-bar ratio while the time axis
  // zooms. Nothing has been measured on an empty pane, so there is no ratio
  // to hold: the row stays, greyed, saying why.
  add({
    label: 'Pin price per bar', on: s.lockRatio, disabled: !s.scaled,
    note: s.scaled ? '' : 'nothing measured',
    onSelect: () => runAxis(() => setAxisLockRatio(!s.lockRatio)),
  });

  axMenu.appendChild(axSeparator());
  axMenu.appendChild(axHead('Scale'));
  for (const m of AX_MODES) {
    add({
      mark: 'radio', label: m.label, on: s.mode === m.value, chord: m.chord,
      onSelect: () => runAxis(() => setAxisMode(m.value)),
    });
  }

  const placement = axisPlacement();
  if (placement && placement.side !== 'hidden') {
    axMenu.appendChild(axSeparator());
    add({
      label: placement.side === 'right' ? 'Move the scale to the left' : 'Move the scale to the right',
      disabled: !s.active, note: s.active ? '' : 'nothing on this side',
      onSelect: () => runAxis(moveAxisToOtherSide),
    });
    const peers = axisColumns(placement.side), index = peers.findIndex(column => column.scaleId === s.scaleId);
    if (index >= 0 && peers.length > 1) for (const delta of [-1, 1]) {
      add({ label: delta < 0 ? 'Move the scale closer to the plot' : 'Move the scale further from the plot',
        disabled: peers[index + delta] === undefined,
        onSelect: () => runAxis(() => moveAxisBy(delta)),
      });
    }
  }

  axMenu.appendChild(axSeparator());
  axMenu.appendChild(axHead('Price levels'));
  add({ label: 'Lines on the plot', submenu: 'line' });
  add({ label: 'Tags on the axis', submenu: 'label' });

  axMenu.appendChild(axSeparator());
  add({
    label: 'Axis settings...',
    onSelect: () => { closeAxisMenu(); openChartSettings('axes', ctxOwner); },
  });
}

/** Run an axis action, then repaint whatever is on screen showing its state. */
function runAxis(action) {
  // A scale's mode, invert, auto-fit and placement are the user's steps, and
  // the chart announces none of them, so each row is measured as one.
  asStep(1, action, 'Price scale');
  if (!axMenu.hidden) paintAxisMenu();
  if (!axSub.hidden) { paintAxisSub(); markOpenSubRow(); }
  autosave();
}

/** Re-mark the parent row a flyout belongs to; a repaint replaced the node. */
function markOpenSubRow() {
  for (const r of axMenu.querySelectorAll('.axrow')) {
    r.classList.toggle('is-open', r.dataset.submenu === axSubHalf);
  }
}

// ── the actions themselves ─────────────────────────────────────────────
export function setAxisMode(mode) {
  const s = axisState();
  if (!s) return;
  app.chart.setPriceAxisOptions(s.paneIndex, s.scaleId, { mode });
  const m = AX_MODES.find((x) => x.value === mode);
  el('status').textContent = 'price scale: ' + (m ? m.label.toLowerCase() : mode);
}

export function setAxisInvert(on) {
  const s = axisState();
  if (!s) return;
  app.chart.setPriceAxisOptions(s.paneIndex, s.scaleId, { inverted: on });
  el('status').textContent = on ? 'price scale inverted' : 'price scale upright';
}

export function setAxisAutoFit(on) {
  const s = axisState();
  if (!s) return;
  app.chart.setPriceAxisAutoFit(s.paneIndex, s.scaleId, on);
  el('status').textContent = on ? 'price scale auto-fits the data' : 'price scale pinned where it is';
}

export function setAxisLockRatio(on) {
  const s = axisState();
  if (!s) return;
  // The engine reports whether the axis is now in the state asked for:
  // locking fails on a scale nothing has measured, and saying so beats a
  // row that flips back on the next repaint with no explanation.
  const ok = app.chart.setPriceAxisLockRatio(s.paneIndex, s.scaleId, on);
  el('status').textContent = ok
    ? (on ? 'price per bar pinned' : 'price per bar released')
    : 'nothing measured on this scale yet';
}

export function moveAxisToOtherSide() {
  const s = axisState(), placement = axisPlacement();
  if (!s?.active || !placement || placement.side === 'hidden') return;
  const to = placement.side === 'right' ? 'left' : 'right';
  if (!app.chart.setPriceAxisPlacement(s.paneIndex, s.scaleId, to)) {
    el('status').textContent = 'the scale could not be moved';
    return;
  }
  // Placement changes leave the ID intact, including for subsequent shortcuts.
  el('status').textContent = 'price scale moved to the ' + to;
}

function moveAxisBy(delta) {
  const s = axisState(), placement = axisPlacement();
  if (!s?.active || !placement || placement.side === 'hidden') return;
  const peers = axisColumns(placement.side), index = peers.findIndex(column => column.scaleId === s.scaleId);
  const neighbor = index < 0 ? undefined : peers[index + delta];
  if (!neighbor) return;
  const moved = app.chart.setPriceAxisPlacement(s.paneIndex, s.scaleId, placement.side, neighbor.order);
  el('status').textContent = moved
    ? (delta < 0 ? 'price scale moved closer to the plot' : 'price scale moved further from the plot')
    : 'the scale could not be moved';
}

// ── price levels ───────────────────────────────────────────────────────
// A level is a line and an axis tag that toggle independently, so the two
// submenus are the same ten rows read through different halves of one style.

/**
 * The last price is the one level the core already owns: `priceLineVisible`
 * and `lastValueVisible` are this level's two halves under older names, and
 * letting the primitive draw it as well would put two lines on one price.
 * The engine ships the translation both ways, so the row still reads and
 * writes like every other.
 */
const isLastPriceLevel = (kind) => kind === 'lastPrice' && Boolean(lastPriceLevelFromSeriesStyle);

function levelStyle(kind) {
  if (isLastPriceLevel(kind)) {
    const info = app.chart && app.chart.primarySeriesInfo ? app.chart.primarySeriesInfo() : null;
    return lastPriceLevelFromSeriesStyle((info && info.style) || {});
  }
  return app.priceLevels ? app.priceLevels.level(kind) : { line: false, label: false };
}

/** Whether the level has a price in the current context. */
function levelAvailable(kind) {
  return Boolean(app.priceLevels) && app.priceLevels.available(kind);
}

function setLevelHalf(kind, half, on) {
  const next = { ...levelStyle(kind), [half]: on };
  if (isLastPriceLevel(kind)) {
    if (app.price) app.price.applyOptions(seriesStyleForLastPriceLevel(next));
  } else if (app.priceLevels) {
    app.priceLevels.setLevel(kind, { [half]: on });
    // Kept outside the primitive because a chart-type switch destroys it.
    app.priceLevelState[kind] = { ...app.priceLevels.level(kind) };
  }
  el('status').textContent = LEVEL_LABEL[kind] + ' '
    + (half === 'line' ? 'line' : 'tag') + (on ? ' on' : ' off');
}

function paintAxisSub() {
  axSub.innerHTML = '';
  const half = axSubHalf;
  axSub.appendChild(axHead(half === 'line' ? 'Lines on the plot' : 'Tags on the axis'));
  if (!app.priceLevels) {
    axSub.appendChild(axRow({
      label: 'Price levels', disabled: true, note: 'not in this build of dist/',
    }));
    return;
  }
  for (const kind of levelKinds()) {
    const ok = levelAvailable(kind);
    const style = levelStyle(kind);
    axSub.appendChild(axRow({
      label: LEVEL_LABEL[kind] || kind,
      on: style[half] === true,
      // Disabled, not hidden: "no previous session yet" and "no live quote"
      // are information. The switch keeps showing the state it is in.
      disabled: !ok,
      note: ok ? '' : 'no data',
      onSelect: () => runAxis(() => setLevelHalf(kind, half, style[half] !== true)),
    }));
  }
}

function openAxisSub(half, anchor) {
  if (axSubHalf === half && !axSub.hidden) return;
  axSubHalf = half;
  paintAxisSub();
  axSub.hidden = false;
  const a = anchor.getBoundingClientRect();
  const m = axMenu.getBoundingClientRect();
  const w = axSub.offsetWidth;
  // Flip to the left of the parent when the right side has no room, which is
  // the usual case for a menu raised on a right-hand price ladder.
  const right = m.right + 2;
  axSub.style.left = (right + w + 8 > window.innerWidth ? Math.max(4, m.left - w - 2) : right) + 'px';
  axSub.style.top = Math.max(4, Math.min(a.top - 6, window.innerHeight - axSub.offsetHeight - 8)) + 'px';
  markOpenSubRow();
}

function closeAxisSub() {
  axSub.hidden = true;
  axSubHalf = null;
  for (const r of axMenu.querySelectorAll('.axrow')) r.classList.remove('is-open');
}

export function closeAxisMenu() {
  axMenu.hidden = true;
  closeAxisSub();
}

export function openAxisMenu(e, target) {
  hideCtx();
  axTarget = {
    // The price pane is kept as null, so the chords stay on it through a move.
    paneIndex: typeof e.paneIndex === 'number' && e.paneIndex !== pricePane(app.chart) ? e.paneIndex : null,
    // An older dist/ classifies the strip but does not say which scale it
    // draws; the side's own scale is the right guess in that case.
    scaleId: target.scaleId !== undefined ? target.scaleId : (target.side || 'right'),
  };
  paintAxisMenu();
  axMenu.hidden = false;
  const rect = el('chart').getBoundingClientRect();
  axMenu.style.left = Math.max(4, Math.min(rect.left + e.point.x, window.innerWidth - axMenu.offsetWidth - 8)) + 'px';
  axMenu.style.top = Math.max(4, Math.min(rect.top + e.point.y, window.innerHeight - axMenu.offsetHeight - 8)) + 'px';
}


/**
 * Price-axis chords, in the same `Alt+<key>` grammar the drawing tier uses
 * and matched the same way: modifiers exactly, never a bare letter, so
 * nothing here can shadow a browser chord. They act on the axis the menu
 * last named, which is the price ladder until a right-click says otherwise.
 *
 * `code` as well as `key`, unlike the tier's matcher: on macOS Alt+L arrives
 * as a typographic character and the letter is only recoverable from `code`.
 */
const AX_CHORDS = [
  { chord: AX_AUTOFIT_CHORD, run: () => setAxisAutoFit(!(axisState() || {}).autoFit) },
  { chord: AX_INVERT_CHORD, run: () => setAxisInvert(!(axisState() || {}).inverted) },
  ...AX_MODES.map((m) => ({ chord: m.chord, run: () => setAxisMode(m.value) })),
];

export function matchAxisShortcut(e) {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return null;
  const key = String(e.key || '').toLowerCase();
  const code = String(e.code || '').replace(/^(Key|Digit)/, '').toLowerCase();
  for (const c of AX_CHORDS) {
    const want = c.chord.split('+').pop().toLowerCase();
    if (want === key || want === code) return c;
  }
  return null;
}

/** One popup menu at a time, anchored under its button. */
let openMenu = null;
export function popupMenu(anchor, rows, opts) {
  closeMenu();
  const m = document.createElement('div');
  m.className = 'menu';
  if (opts?.role) m.setAttribute('role', opts.role);
  const find = opts && opts.find
    ? Object.assign(document.createElement('input'), { type: 'text', placeholder: opts.find })
    : null;
  if (find) {
    const wrap = document.createElement('div');
    wrap.className = 'menu-find';
    wrap.appendChild(find);
    m.appendChild(wrap);
  }
  const body = document.createElement('div');
  m.appendChild(body);

  function paint(q) {
    const needle = q.trim().toLowerCase();
    body.innerHTML = '';
    let shown = 0;
    if (needle && opts?.onSubmit) {
      const submit = document.createElement('button');
      submit.textContent = 'Load ' + q.trim();
      submit.addEventListener('click', () => { closeMenu(); opts.onSubmit(q.trim()); });
      body.appendChild(submit);
      shown++;
    }
    // A group heading is only worth drawing once something under it survives
    // the filter, so it is held back until the first matching row appears.
    let pending = null;
    for (const r of rows) {
      if (r.group) { pending = r.group; continue; }
      if (needle && !r.label.toLowerCase().includes(needle)) continue;
      if (pending) {
        const g = document.createElement('div');
        g.className = 'menu-group';
        g.textContent = pending;
        body.appendChild(g);
        pending = null;
      }
      const b = document.createElement('button');
      // A row with an `on` is one of a set of choices (or, with `check`, a
      // switch) and says whether it is on; the tick is a picture of that, not
      // a word to read out.
      if (r.check || typeof r.on === 'boolean') {
        b.setAttribute('role', r.check ? 'menuitemcheckbox' : 'menuitemradio');
        b.setAttribute('aria-checked', String(r.on === true));
      }
      else if (opts?.role === 'menu') b.setAttribute('role', 'menuitem');
      b.disabled = r.disabled === true;
      b.title = r.reason || '';
      b.innerHTML = (r.icon ? ticon(r.icon) : '<span style="width:20px"></span>') +
        '<span>' + esc(r.label) + '</span>' + (r.on ? '<em aria-hidden="true">' + POPUP_TICK + '</em>' : '');
      b.addEventListener('click', () => { if (!b.disabled) { closeMenu(); r.onSelect(); } });
      body.appendChild(b);
      shown += 1;
    }
    if (shown === 0) {
      const e = document.createElement('div');
      e.className = 'menu-empty';
      e.textContent = 'No match';
      body.appendChild(e);
    }
  }
  paint('');

  if (find) {
    find.addEventListener('input', () => paint(find.value));
    // Enter picks the only remaining row, so a unique search needs no click.
    find.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      if (opts?.onSubmit && find.value.trim()) {
        e.preventDefault();
        closeMenu();
        opts.onSubmit(find.value.trim());
        return;
      }
      const only = body.querySelectorAll('button');
      if (only.length === 1) only[0].click();
    });
  }
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, window.innerWidth - m.offsetWidth - 8) + 'px';
  m.style.top = Math.max(4, Math.min(r.bottom + 4, window.innerHeight - m.offsetHeight - 8)) + 'px';
  openMenu = m;
  if (find) find.focus();
}
export function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }

export function initMenus(a) {
  app = a;
  ctxMenu = el('ctxmenu');
  axMenu = el('axmenu');
  axSub = el('axsub');

  window.addEventListener('click', hideCtx);
  window.addEventListener('blur', hideCtx);
  el('chart').addEventListener('wheel', hideCtx, { passive: true });
  ctxMenu.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn || btn.disabled || btn.hidden) return;
    e.stopPropagation();
    hideCtx();
    const act = btn.getAttribute('data-act');
    if (act === 'alert-create') { ctxAlerts[0]?.onSelect(); return; }
    if (act === 'alert-list') { ctxAlerts.at(-1)?.onSelect(); return; }
    if (act === 'cancelall') {
      removeAllOrders(); removeBracket(); clearPosition(); saveState(); el('status').textContent = 'orders cancelled, position closed'; return;
    }
    if (act === 'delall') {
      if (!app.draw) return;
      const n = drawingMenuState(app.draw).removable;
      app.draw.clear();                 // one undo step, so it is recoverable; read-only drawings stay
      autosave();
      el('status').textContent = n ? `removed ${n} drawing${n === 1 ? '' : 's'}` : 'no drawings to remove';
      return;
    }
    if (act === 'delsel') {
      if (!app.draw) return;
      const id = app.draw.selected();
      if (id && app.draw.remove(id)) { autosave(); el('status').textContent = 'drawing deleted'; }
      return;
    }
    // Session marks are the host's own: it places them, and it alone clears
    // them, which is why this is the one row that passes `force`.
    if (act === 'mark') {
      if (!app.draw || ctxTime === null) return;
      addSessionMark(app.draw, { time: ctxTime, price: ctxPrice }, app.req.symbol, pricePane(app.chart));
      el('status').textContent = `marked ${fmt(ctxPrice)} for this session`;
      return;
    }
    if (act === 'unmark') {
      const n = clearSessionMarks(app.draw, app.req.symbol);
      el('status').textContent = `cleared ${n} session mark${n === 1 ? '' : 's'}`;
      return;
    }
    // The protected study is the host's too, so taking it away passes `force`.
    if (act === 'hoststudy') {
      if (!ctxOwner?.current()) return;
      if (hostStudy(app.chart)) { removeHostStudy(app.chart); el('status').textContent = 'removed the protected VWAP'; }
      else { addHostStudy(app.chart); el('status').textContent = 'added a protected VWAP: the host keeps it, its settings and its place'; }
      // The rebuild after a symbol or type switch re-adds the remembered studies, policy and all.
      rememberIndicators();
      renderIndicatorChips();
      autosave();
      return;
    }
    if (act === 'copy' || act === 'cut' || act === 'paste') {
      // Always the main chart: this menu is raised from the main chart's own
      // contextmenu event, so routing it through the pointer-focused pane
      // would act on the other chart if the pointer had moved on.
      app.focusPane = 1;
      clipboardAction(act);
      return;
    }
    if (act === 'volshow') { if (ctxOwner?.current()) setVolumeShown(!volumeShown(1), 1); return; }
    if (act === 'chartset') { openChartSettings(undefined, ctxOwner); return; }
    if (act === 'indset') { if (ctxIndicator) openSettings(ctxIndicator, ctxOwner); return; }
    if (act === 'panecollapse') { if (ctxOwner?.current()) ctxPane?.onSelect(); return; }
    if (act === 'paneup' || act === 'panedown') { if (ctxOwner?.current()) ctxMoves[act === 'paneup' ? 0 : 1]?.onSelect(); return; }
    placeOrder(btn.getAttribute('data-side'), btn.getAttribute('data-type'), ctxPrice);
  });

  // The menu stays up while levels are toggled, so it closes on a press
  // outside it rather than on any click at all, the way the order menu does.
  window.addEventListener('pointerdown', (e) => {
    if (axMenu.hidden) return;
    if (axMenu.contains(e.target) || axSub.contains(e.target)) return;
    closeAxisMenu();
  }, true);
  window.addEventListener('blur', closeAxisMenu);
  el('chart').addEventListener('wheel', closeAxisMenu, { passive: true });

  window.addEventListener('keydown', (e) => {
    if (inTextField(e)) return;
    if (!el('chartset').hidden || !el('setmodal').hidden) return;  // a dialog owns the keyboard
    const hit = matchAxisShortcut(e);
    if (!hit || !axisState()) return;
    e.preventDefault();
    runAxis(hit.run);
  });

  window.addEventListener('pointerdown', (e) => {
    if (openMenu && !openMenu.contains(e.target) && !e.target.closest('.tbtn')) closeMenu();
  }, true);
}
