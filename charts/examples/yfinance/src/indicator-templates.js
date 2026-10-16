import { captureIndicatorTemplate as captureNativeTemplate, parseIndicatorStates,
  planIndicatorTemplateState } from '/dist/openalgo-charts.workspace.mjs';

const operations = new WeakMap();
const flagOwners = new WeakMap();

export function templateUnavailableReason(app, target) {
  if (!target?.current() || target.chart.isDestroyed) return 'The chart changed; reopen Templates for its current owner';
  if (app.workspaceLoading || app.applyingTemplate || app.chartSettingsEditing || app.restoringSecondary
    || (target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed)
    || !target.chart.primaryBars().length) return 'Finish loading or settings changes before using templates';
  if (app.replayPicking || app.replayLoading) return 'Finish replay selection and loading before using templates';
  return null;
}

function assertOwner(app, target) {
  const reason = templateUnavailableReason(app, target);
  if (reason) throw new Error(reason);
}

export function captureIndicatorTemplate(app, target) {
  assertOwner(app, target);
  return captureNativeTemplate(target.chart);
}

/** Apply to the captured chart's displayed data; never reload a source to add studies. */
export function applyIndicatorTemplate(app, target, incoming, mode, options) {
  assertOwner(app, target);
  const chart = target.chart, before = chart.getState();
  const previous = parseIndicatorStates(before.indicators || []);
  const planned = planIndicatorTemplateState(chart, incoming, mode, options);
  assertOwner(app, target);
  if (mode === 'append' && planned.indicators.length === previous.length) return previous;
  const retained = { drawings: before.drawings, alerts: before.alerts };
  const token = {};
  let expectedStart = false, superseded = false;
  const owns = () => operations.get(chart) === token && !superseded && target.current() && !chart.isDestroyed;
  // A callback can restore this same chart without going through this helper.
  // Its newer layout must survive both error recovery and mirror publication.
  const unsubscribe = chart.on?.('state:restore:start', () => {
    if (expectedStart) expectedStart = false;
    else superseded = true;
  });
  const restore = (indicators, extra, restoreOptions) => {
    expectedStart = true;
    let report;
    // A price pane moved below the studies is carried as its slot, which only
    // a version 2 state has; without one the restore puts it back on top.
    const state = { version: extra.primaryPane > 0 ? 2 : 1, indicators, ...retained, ...extra };
    try { report = restoreOptions === undefined ? chart.restoreState(state) : chart.restoreState(state, restoreOptions); }
    finally { expectedStart = false; }
    if (!report.applied) throw new Error(report.reason || 'The template could not be applied');
    if (report.indicators !== indicators.length) throw new Error('The chart did not restore all studies');
  };
  operations.set(chart, token); flagOwners.set(app, token);
  app.applyingTemplate = true;
  try {
    restore(planned.indicators, { panes: planned.panes ?? (mode === 'append' ? before.panes : before.panes?.slice(0, 1)),
      ...(planned.primaryPane === undefined ? {} : { primaryPane: planned.primaryPane }) }, planned.restoreOptions);
    if (!owns()) throw new Error('The chart changed or a newer restore replaced this template');
    return parseIndicatorStates(chart.getState().indicators || []);
  } catch (error) {
    if (owns()) {
      try {
        const panes = chart.getState().panes ?? [];
        // Only retained destination axes keep runtime formatters. Replaced study
        // panes need their outgoing descriptors to reinstall the original format.
        const restoreOptions = planned.restoreOptions && { ...planned.restoreOptions,
          preserveScaleFormats: (planned.restoreOptions.preserveScaleFormats ?? []).filter(({ paneIndex, scaleId }) =>
            panes[paneIndex] && (scaleId === 'right' || Object.prototype.hasOwnProperty.call(panes[paneIndex].scales ?? {}, scaleId))),
        };
        restore(previous, { panes: before.panes, viewport: before.viewport, barSpacing: before.barSpacing,
          ...(before.primaryPane === undefined ? {} : { primaryPane: before.primaryPane }) }, restoreOptions);
      }
      catch (rollbackError) { throw new AggregateError([error, rollbackError], 'Template application and recovery failed'); }
    }
    throw error;
  } finally {
    try {
      if (target.pane === 1 && owns()) app.activeIndicators = parseIndicatorStates(chart.getState().indicators || []);
    } finally {
      unsubscribe?.();
      if (operations.get(chart) === token) operations.delete(chart);
      if (flagOwners.get(app) === token) { flagOwners.delete(app); app.applyingTemplate = false; }
    }
  }
}
