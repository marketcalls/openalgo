// Go to a date or a range on the selected chart.
//
// The navigation rules (which bar a date names, when history is short, how a
// newer request or a destroyed chart ends one) are the widget tier's
// DateNavigator, shared with the packaged widget. What is this page's own is
// how missing history arrives: the reference feed serves history by period
// rather than by page, so older bars come from the shortest longer period
// that reaches the requested time, loaded through the pane's ordinary load
// path. The range menu then shows the period that was actually loaded, which
// is the honest record of it.
//
// That load rebuilds the pane's chart, and the panel goes with the chart's
// overlays. The request itself carries on, so the panel is opened again on
// the new chart to show it through: a result short of a placement (history
// that starts later, no bars, a failed load) is reported where it was asked.
// A pan or zoom while the period loads drops the request instead, as the
// packaged widget does: the user has moved on, and a placement would undo it.
// That watch is the page's too, since only the page knows which view moves
// are its own.
import { DateNavigator, openDateNavigation } from '/dist/openalgo-charts.widget.mjs';
import { el } from './ui.js';
import { PERIOD_DAYS, periodsFor } from './intervals.js';
import { capturePaneTarget } from './pane-target.js';

const DAY = 86400;
let app;
let panel = null;
/** The panel's request while it runs: `{ pane, target, result }`. */
let current = null;
const navigators = new Map();

export function initGoTo(a) {
  app = a;
}

/**
 * The shortest period this interval can serve that reaches `spanSec` back
 * and is longer than `period`; the longest longer one when none reaches; null
 * when `period` is already the longest the source will go.
 */
export function widerPeriod(interval, period, spanSec) {
  const held = PERIOD_DAYS[period] || 0;
  const longer = periodsFor(interval).filter(p => PERIOD_DAYS[p] > held);
  return longer.find(p => PERIOD_DAYS[p] * DAY >= spanSec) || longer[longer.length - 1] || null;
}

/** One reach for the navigator: load `pane` again with a period reaching `time`. */
export async function loadPaneHistory(pane, time) {
  // Replay owns the bars on screen, and a workspace switch is replacing them.
  if (app.replay || app.replayPicking || app.replayLoading || app.workspaceLoading) return 'unavailable';
  const request = pane === 2 ? app.p2 : app.req;
  const next = widerPeriod(request.interval, request.period, Math.floor(Date.now() / 1000) - time);
  if (!next) return 'exhausted';
  // The page moves this chart's view on its own only after the rebuild has
  // replaced it, so a pan or zoom before then is the user's, made here or on
  // a linked chart. The listeners go with the chart they were added to.
  const chart = pane === 2 ? app.chart2 : app.chart;
  const moved = () => navigatorFor(pane).cancel();
  const offs = ['pan', 'zoom'].map(name => chart.on(name, moved));
  try {
    if (pane === 2) {
      app.p2.period = next;
      await app.loadSecondary();
    } else {
      el('period').value = next;
      await app.load();
    }
  } finally {
    for (const off of offs) off();
    // The load rebuilt the chart the panel belonged to; show the request on the
    // new one, from the control it was asked from. The bottom bar's outlives
    // the rebuild; the toolbar's is drawn again, so the new one stands in, and
    // it is the one on screen when a narrower window has hidden the bar meanwhile.
    if (current?.pane === pane && !panel) openGoTo(shown(current.anchor) || shown(el('goto')) || undefined, current);
  }
  if (pane === 2 ? app.loadFailed2 : app.loadFailed) throw new Error(`${request.symbol} history could not load`);
  return 'loaded';
}

/** `node` while it is laid out on the page, else null: a panel anchored to a hidden control opens in the corner. */
const shown = (node) => (node && node.getClientRects().length > 0 ? node : null);

function navigatorFor(pane) {
  let navigator = navigators.get(pane);
  if (!navigator) {
    navigator = new DateNavigator({
      // Read on every step: a load rebuilds the chart this pane shows.
      chart: () => (pane === 2 ? app.chart2 : app.chart),
      loadHistory: time => loadPaneHistory(pane, time),
    });
    navigators.set(pane, navigator);
  }
  return navigator;
}

/**
 * Open the shared go-to panel for the selected chart, or, with `pending`,
 * for the pane whose request it is, showing that request until it settles.
 */
export function openGoTo(anchor, pending) {
  const target = capturePaneTarget(app, pending?.pane);
  const context = target && app['inspection' + target.pane]?.context;
  if (!target?.current() || !context) return false;
  const pane = target.pane;
  // A load under way is about to replace the chart, and the panel with it;
  // a failed one left no history to go into. The toolbar greys its Go to
  // for both; the bottom bar's cannot know, so the status line says which.
  const failed = pane === 2 ? app.loadFailed2 : app.loadFailed;
  if (!pending && (failed || (pane === 2 ? app.loading2 : app.loading))) {
    el('status').textContent = failed ? 'chart history did not load, so there is no date to go to' : 'wait for chart history before going to a date';
    return false;
  }
  const navigator = navigatorFor(pane);
  panel?.close();
  let handle = null;
  handle = openDateNavigation({ ...context, status: text => { el('status').textContent = text; } }, anchor, {
    navigate: request => {
      const run = { pane, target: request, result: navigator.goTo(request), anchor };
      current = run;
      void run.result.finally(() => { if (current === run) current = null; });
      return run.result;
    },
    // Dismissed while loading: the view must not jump after the user has moved on.
    cancel: () => navigator.cancel(),
    pending,
    onClose: () => { if (panel === handle) panel = null; },
  });
  panel = handle;
  return true;
}
