// One undo timeline per chart: studies, their settings, the chart type,
// price scales, panes and drawings, walked by Ctrl+Z and Ctrl+Y, the toolbar
// buttons, the rail and the mobile bar alike.
//
// The demo rebuilds its chart on every load and every chart-type switch, so
// the timeline is not the chart's: it lives on `app`, and each rebuilt chart
// is attached to it. A study keeps its id through the rebuild and a pane its
// slot, which is what the history follows, so the steps survive it. The
// chart type itself is a rebuild here, not something the engine can switch
// in place, so the demo records it as its own command.
//
// Three things the demo does to the chart are not the user's steps, and go
// through `withoutHistory`: comparisons (they own a temporary scale mode),
// the volume row (host settings) and a layout being loaded, which starts a
// new timeline instead.
import { ChartHistory } from '/dist/openalgo-charts.widget.mjs';
import { toast } from './ui.js';
import { sameType } from './transforms.js';

let app;
const listeners = new Set();

const slot = (pane) => (pane === 2 ? 'history2' : 'history');
/** The chart the shared controls act on: the focused one. */
const focused = () => (app?.focusPane === 2 && app.chart2 ? 2 : 1);

export function initHistory(a) { app = a; }

/** The timeline of chart `pane`, or null before its first chart. */
export function historyFor(pane = 1) {
  const history = app?.[slot(pane)];
  return history && !history.isDestroyed ? history : null;
}

/** The timeline the shared controls act on: the focused chart's. */
export const activeHistory = () => historyFor(focused());

/**
 * Follow the chart a build just finished, keeping the steps already taken.
 * Called last in a build, so nothing the build itself did becomes a step.
 */
export function attachHistory(pane = 1) {
  const chart = pane === 2 ? app.chart2 : app.chart;
  const draw = pane === 2 ? app.draw2 : app.draw;
  if (!chart) return null;
  let history = historyFor(pane);
  if (history) history.attach(chart, draw);
  else {
    history = app[slot(pane)] = new ChartHistory(chart, {
      draw,
      onError: ({ direction, error }) => toast('error', `That step could not be ${direction === 'undo' ? 'undone' : 'redone'}: ${error?.message ?? error}`),
    });
    history.subscribe(() => { for (const listener of listeners) listener(); });
  }
  for (const listener of listeners) listener();
  return history;
}

/** Called whenever what an undo or redo would do changes, on either chart. */
export function onHistoryChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * One undo or redo press, on the focused chart unless `pane` names one.
 * Without a timeline (a chart not built yet, or a test double) it is the
 * drawing controller's own. What the demo mirrors outside the chart (its
 * study list, the zone, the toolbar) is read back from the chart afterwards.
 */
export function historyPress(direction, pane = focused()) {
  const history = historyFor(pane);
  let moved;
  if (history) moved = direction === 'undo' ? history.undo() : history.redo();
  else {
    const draw = pane === 2 ? app?.draw2 : app?.draw;
    moved = !!draw && (direction === 'undo' ? draw.undo() : draw.redo());
  }
  if (moved) app.afterHistory?.(pane);
  return moved;
}

/** Whether that press would do anything, for the control's enabled state. */
export function historyReady(direction, pane = focused()) {
  const history = historyFor(pane);
  if (history) return direction === 'undo' ? history.canUndo() : history.canRedo();
  const draw = pane === 2 ? app?.draw2 : app?.draw;
  if (!draw) return false;
  return direction === 'undo' ? draw.canUndo() : draw.canRedo();
}

/** Run a change the demo makes for itself, which no undo should take back. */
export function withoutHistory(pane, fn) {
  const history = historyFor(pane);
  return history ? history.ignore(fn) : fn();
}

/** Run a change the chart does not announce (a scale option) as one step. */
export function asStep(pane, fn, label) {
  const history = historyFor(pane);
  return history ? history.transact(fn, label) : fn();
}

/** Merge everything until the returned function runs into one step: a dialog session. */
export function historyGroup(pane, label) {
  return historyFor(pane)?.group(label) ?? (() => {});
}

/**
 * A chart-type switch rebuilds the chart, so the history cannot see it as a
 * change to the chart it holds. The demo records it as a command that
 * rebuilds again with the other type, or with the other options of the same
 * one (a box size, a reversal), which rebuild it just the same.
 */
export function recordChartType(pane, from, to, apply, label = 'Chart type') {
  if (sameType(from, to)) return;
  historyFor(pane)?.push({ label, undo: () => apply(from), redo: () => apply(to) });
}
