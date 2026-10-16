import { AlertController, getIndicator } from '/dist/openalgo-charts.mjs';
import { createAlertUi } from '/dist/openalgo-charts.widget.mjs';
import { el, currentTheme, chartTheme, toast } from './ui.js';
import { autosave } from './persist.js';

/** Each chart owns an evaluator. Delivery stays in this host, separate from orders. */
export function attachAlerts(app, pane = 1) {
  const suffix = pane === 2 ? '2' : '';
  detachAlerts(app, pane);
  const chart = app['chart' + suffix];
  const draw = app['draw' + suffix];
  const alerts = new AlertController(chart, { drawings: draw });
  alerts.setPaused(Boolean(app.workspaceLoading || app.replay || app.replayPicking || app.replayLoading
    || (pane === 1 ? app.loading || app.loadFailed : app.loading2 || app.loadFailed2)));
  // Dialogs use the workspace width even when their source chart is narrow.
  const ui = createAlertUi(el('split'), {
    chart, draw, alerts, theme: currentTheme(), chartTheme: chartTheme(),
  });
  app['alerts' + suffix] = alerts;
  app['alertUi' + suffix] = ui;
  const disposers = [];
  for (const event of ['alert:created', 'alert:updated', 'alert:removed', 'alert:triggered', 'alert:expired', 'alerts:checkpoint']) {
    disposers.push(chart.on(event, autosave));
  }
  disposers.push(chart.on('alert:triggered', event => {
    toast('success', event.message || event.title);
  }));
  disposers.push(chart.on('alert:error', () => toast('error', 'An alert condition could not be evaluated. Review its source.')));
  const themeChanged = () => ui.setTheme(currentTheme(), chartTheme());
  document.addEventListener('oac:theme', themeChanged);
  disposers.push(() => document.removeEventListener('oac:theme', themeChanged));
  app['disposeAlerts' + suffix] = () => {
    for (const dispose of disposers) dispose();
    ui.destroy();
    alerts.destroy();
  };
  return alerts;
}

export function detachAlerts(app, pane = 1) {
  const suffix = pane === 2 ? '2' : '';
  app['disposeAlerts' + suffix]?.();
  app['disposeAlerts' + suffix] = null;
  app['alertUi' + suffix] = null;
  app['alerts' + suffix] = null;
}

export function openAlerts(app) {
  const ui = app.focusPane === 2 && app.chart2 ? app.alertUi2 : app.alertUi;
  return ui?.openList() ?? false;
}

/** A context action belongs to its source chart even if focus moves before selection. */
export function alertContextEntries(app, event, pane = 1) {
  const suffix = pane === 2 ? '2' : '';
  const chart = app['chart' + suffix];
  const draw = app['draw' + suffix];
  const ui = app['alertUi' + suffix];
  if (!chart || !ui) return [];
  const scope = () => {
    const context = chart.getDataContext();
    // The session is part of the series an alert is set on, like the interval.
    return JSON.stringify([context?.symbol, context?.exchange, context?.interval, context?.variant?.session ?? null]);
  };
  const initialScope = scope();
  const current = () => app['chart' + suffix] === chart && app['alertUi' + suffix] === ui && scope() === initialScope;
  const rows = [];
  const add = (label, source, info = {}) => rows.push({ label, disabled: info.available === false,
    reason: info.reason, onSelect: () => current() && info.available !== false && ui.openEditor({ source }) });
  const target = event.target || { kind: 'empty' };
  // The price pane can sit below the studies; its overlays and price alerts go with it.
  const pricePane = typeof chart.primaryPaneIndex === 'function' ? chart.primaryPaneIndex() : 0;
  if (target.kind === 'drawing') {
    const id = target.id?.startsWith('draw:') ? target.id.slice(5).split('#')[0] : null;
    if (id && draw?.get(id)) add('Create drawing alert...', { kind: 'drawing', drawingId: id }, draw.alertInfo(id));
  } else if (target.kind === 'indicator' && target.instanceId) {
    const instance = chart.indicators().find(item => item.id === target.instanceId);
    const plot = instance && getIndicator(instance.indicatorId).plots.find(item =>
      (item.overlay ? pricePane : instance.paneIndex) === event.paneIndex && (target.plotKey === undefined || item.key === target.plotKey));
    if (instance && plot) add('Create study alert...', { kind: 'indicator', instanceId: instance.id, plotKey: plot.key,
      value: instance.values()[plot.key]?.[event.index ?? chart.primaryBars().length - 1] ?? NaN });
  } else if (event.paneIndex === pricePane && event.price !== null && Number.isFinite(event.price)) {
    add('Create price alert...', { kind: 'price', price: event.price });
  }
  rows.push({ label: 'Alerts...', onSelect: () => current() && ui.openList() });
  return rows;
}
