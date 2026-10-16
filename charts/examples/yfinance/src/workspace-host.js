import { ReferenceWorkspaceTransition } from './workspace-transition.js';
import { layoutSnapshot, autosave } from './persist.js';
import { secondaryRawBars } from './split.js';
import { magnetMode, stayMode } from './rail.js';
import { renderToolbar } from './toolbar.js';
import { syncReplayAlertPause } from './replay.js';
import { syncComparisons } from './compare.js';
import { el } from './ui.js';

export function workspaceUnavailable(app) {
  return !app.chart || app.applyingTemplate || app.replay || app.replayPicking || app.replayLoading || app.loading || app.loadFailed
    || app.loading2 || app.loadFailed2 || app.restoringSecondary || app.chartSettingsEditing;
}

function snapshot() {
  return { ...layoutSnapshot(), magnet: magnetMode(), stay: stayMode() };
}

/** Bind one transition owner to the reference page; catalog actions reuse it. */
export function initWorkspaceHost(app, install) {
  const transition = new ReferenceWorkspaceTransition({
    capture() {
      if (workspaceUnavailable(app)) throw new Error('Finish loading, replay or settings changes before switching layouts');
      const layout = snapshot();
      return { layout, bars: [app.currentBars.map(bar => ({ ...bar })), ...(app.chart2 ? [secondaryRawBars()] : [])],
        charts: [app.chart, app.chart2], fingerprint: JSON.stringify(layout) };
    },
    current(before) {
      return !workspaceUnavailable(app) && app.chart === before.charts[0] && app.chart2 === before.charts[1]
        && JSON.stringify(snapshot()) === before.fingerprint;
    },
    watch(cancel) {
      const disposers = [];
      for (const chart of [app.chart, app.chart2].filter(Boolean)) {
        for (const event of ['destroy', 'data:context', 'data:update', 'pan', 'zoom', 'draw:add', 'draw:update', 'draw:remove',
          'indicatorAdded', 'indicatorRemoved', 'indicatorUpdated', 'state:restore:start']) {
          disposers.push(chart.on(event, cancel));
        }
      }
      return () => { for (const dispose of disposers) dispose(); };
    },
    setPending(pending) {
      app.workspaceLoading = pending;
      el('split').setAttribute('aria-busy', String(pending));
      syncReplayAlertPause();
      renderToolbar();
    },
    install,
  });
  app.workspaceTransition = transition;
  app.openWorkspace = async (document, persist) => {
    const prepared = await transition.open(document, persist);
    const primary = app.chart, secondary = app.chart2;
    await Promise.all([syncComparisons(1), ...(secondary ? [syncComparisons(2)] : [])]);
    if (primary === app.chart && secondary === app.chart2) autosave();
    return prepared;
  };
  // A page restored from the back-forward cache still owns usable charts.
  window.addEventListener('pagehide', () => transition.cancel());
  return transition;
}
