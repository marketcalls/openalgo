import { DrawingController, BUILTIN_DRAWING_TOOLS, drawingShortcuts } from '/dist/openalgo-charts.draw.mjs';
import { el, inTextField, MOD } from './ui.js';
import { clipboardPort, activeDraw, canClip, clipboardAction } from './clipboard.js';
import {
  buildRail, syncRail, syncMobileControls, observeMobileControls,
  armCursor, setDrawLock, magnetMode, stayMode, toolName,
} from './rail.js';
import { autosave } from './persist.js';
import { followSessionMarks } from './session-marks.js';
import { historyFor, historyPress, initHistory, onHistoryChange } from './history.js';

let app;

// ── drawing tools ──────────────────────────────────────────────────────
// The controller is headless: it owns the model and the interactions, and
// this module is just a host driving setTool / undo / remove. Drawings
// persist through chart.getState(), so Layout > Save keeps them.
export function attachDrawing() {
  if (app.draw) app.draw.destroy();
  // Seeded from the rail's modes rather than the legacy checkbox: the rail
  // re-asserts both on any controller it observes, so the seed only keeps
  // the first anchor after a rebuild from landing unsnapped.
  app.draw = new DrawingController(app.chart, { magnet: magnetMode(), stayInDrawingMode: stayMode(), clipboard: clipboardPort });
  observeMobileControls(app.chart, app.draw);
  // The chord table comes from the tier, so the rail can only label its rows
  // once this point is reached.
  if (!Object.keys(app.shortcuts).length) {
    app.shortcuts = drawingShortcuts();
    buildRail();
  }
  app.chart.on('draw:tool', ({ tool }) => { syncRail(tool); syncMobileControls(tool); armCursor(el('chart'), tool); });
  // A drawing with a policy is the host's (a session mark put back after a
  // rebuild), not something the user just drew.
  app.chart.on('draw:add', ({ drawing }) => { if (!drawing.policy) el('status').textContent = `drew ${toolName(drawing.tool)}`; });
  followSessionMarks(app.chart, app.draw, () => app.req?.symbol);
  // The modifier gestures leave no drawing behind to explain them, so the
  // status line says what is on the chart and how it goes.
  app.chart.on('draw:measure', ({ active }) => {
    el('status').textContent = active ? 'measuring: click anywhere or press Esc to clear' : '';
  });
  app.chart.on('draw:eraser', ({ active }) => {
    el('status').textContent = active ? 'eraser: click or drag across drawings to delete them · Esc to stop' : 'eraser off';
  });
  for (const ev of ['drawing:change', 'drawing:select']) app.chart.on(ev, syncDrawToolbar);
  syncDrawToolbar();
  // The properties bar follows the selection on its own (it subscribes to
  // the chart when the rail hands it the rebuilt one). What is left for the
  // status line is the chords, at the one moment they apply: the engine
  // ships no keys, so nothing else on screen would ever mention them.
  app.chart.on('draw:select', ({ id }) => {
    const d = id ? app.draw.get(id) : null;
    if (d && canClip()) {
      el('status').textContent = `${toolName(d.tool)} selected · ${MOD}+C copy · ${MOD}+X cut · ${MOD}+V paste`;
    }
  });
  for (const ev of ['draw:add', 'draw:remove', 'draw:update']) app.chart.on(ev, autosave);
  // `layout:change` covers the setters with no event of their own: a grid
  // toggled from the keyboard, an axis set from its menu, a pane weight.
  for (const ev of ['paneResized', 'paneMoved', 'paneMaximized', 'paneCollapsed', 'paneRemoved', 'indicatorRemoved', 'layout:change']) {
    app.chart.on(ev, autosave);
  }
  syncRail(app.draw.activeTool());
  syncMobileControls(app.draw.activeTool());
}

/**
 * What the toolbar's draw buttons would do for `draw` right now. Del takes
 * the part of the selection the user may delete and Clear every drawing but
 * the read-only ones, so each is offered only with something to take; Undo
 * and Redo follow the controller, which drops a step that would do nothing.
 */
export function drawToolbarState(draw) {
  const sel = draw ? draw.selection() : [];
  const del = sel.filter((id) => draw.get(id)?.policy?.editable !== false).length;
  return {
    undo: !!draw && draw.canUndo(), redo: !!draw && draw.canRedo(),
    del, readOnly: sel.length > 0 && del === 0,
    clear: draw ? draw.drawings().filter((d) => d.policy?.editable !== false).length : 0,
  };
}

function syncDrawToolbar() {
  const state = drawToolbarState(app.draw);
  const del = el('drawdel');
  if (!del) return;
  // Undo and Redo walk the main chart's whole timeline once it has one:
  // a study or a pane is as much a step as a drawing.
  const history = historyFor(1);
  el('drawundo').disabled = !(history ? history.canUndo() : state.undo);
  el('drawredo').disabled = !(history ? history.canRedo() : state.redo);
  del.disabled = state.del === 0;
  del.title = state.readOnly ? 'read-only' : 'delete selected';
  el('drawclear').disabled = state.clear === 0;
}

export function fillToolPicker() {
  const sel = el('drawtool');
  const none = document.createElement('option');
  none.value = ''; none.textContent = 'Cursor';
  sel.appendChild(none);
  for (const t of BUILTIN_DRAWING_TOOLS) {
    const o = document.createElement('option');
    o.value = t.id; o.textContent = t.name;
    sel.appendChild(o);
  }
}

export function initDrawing(a) {
  app = a;
  initHistory(a);
  fillToolPicker();
  el('drawtool').addEventListener('change', () => { if (!app.draw) return; setDrawLock(false); app.draw.setTool(el('drawtool').value || null); });
  el('drawundo').addEventListener('click', () => historyPress('undo', 1));
  el('drawredo').addEventListener('click', () => historyPress('redo', 1));
  onHistoryChange(syncDrawToolbar);
  // The whole selection, as one undo step; read-only drawings in it stay.
  el('drawdel').addEventListener('click', () => app.draw && app.draw.removeMany(app.draw.selection()));
  el('drawclear').addEventListener('click', () => app.draw && app.draw.clear());
  // The legacy magnet checkbox is the rail's to follow (it owns the
  // three-way mode); nothing here reads it any more.
  // The shared selection owner in rail.js chooses the controller for chords.

  // Keyboard. The rail claims the drawing chords (tool chords, undo and
  // redo, delete, nudges, placement keys) in the capture phase; what
  // reaches here is the clipboard, which the rail leaves alone on purpose.
  window.addEventListener('keydown', (e) => {
    const d = activeDraw();
    if (!d || inTextField(e)) return;
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key.toLowerCase();
    // Copy and cut only claim the chord when there is a drawing under it:
    // with nothing selected, Ctrl+C still belongs to the page's text.
    if (mod && (key === 'c' || key === 'x') && d.selected() && canClip()) {
      clipboardAction(key === 'c' ? 'copy' : 'cut');
      e.preventDefault();
      return;
    }
    if (mod && key === 'v' && canClip()) {
      clipboardAction('paste');
      e.preventDefault();
    }
  });
}
