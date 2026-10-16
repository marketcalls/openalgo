import { ChartObjects } from '/dist/openalgo-charts.mjs';
import {
  applyTokens, widgetTokens, mountPanelDock, mountDataWindow,
  createObjectsPanelContent, mountQuickEntry, mountDrawingProperties,
  mountWatchlistPanel, mountNewsPanel,
} from '/dist/openalgo-charts.widget.mjs';
import { el, currentTheme, chartTheme, topOverlay } from './ui.js';
import { capturePaneTarget } from './pane-target.js';
import { toolName } from './rail.js';
import { openSettings } from './indicators.js';
import { openChartSettings } from './chart-settings.js';
import { autosave } from './persist.js';
import { INTERVALS } from './intervals.js';
import { referenceSymbolSearch } from './symbol-search.js';
import { referenceWatchlists, referenceQuotes, referenceNewsFeed, referencePanelStorage, watchlistSymbolSearch } from './market-panels.js';

const DEFAULT_DOCK = { panel: null, width: 300 };
let app;

export function initInspection(host) {
  app = host;
  app.inspectionState1 = { ...DEFAULT_DOCK };
  app.inspectionState2 = { ...DEFAULT_DOCK };
}

export function directEntryEnabled(host, pane, chartElement, active = document.activeElement) {
  if (!host || host.focusPane !== pane || !chartElement?.contains(active)) return false;
  if (host.workspaceLoading || host.replay || host.replayPicking || host.replayLoading || host.restoringSecondary) return false;
  if (pane === 2 ? host.loading2 || host.loadFailed2 : host.loading || host.loadFailed) return false;
  if (topOverlay() || host.alertUi?.isOpen() || host.alertUi2?.isOpen()) return false;
  for (const id of ['chartset', 'setmodal', 'cmpmodal', 'textmodal', 'workspacemodal', 'templatemodal', 'indsource', 'chartdatamodal']) {
    const modal = el(id);
    if (modal && !modal.hidden) return false;
  }
  return true;
}

export function attachInspection(host, pane = 1) {
  detachInspection(host, pane);
  const suffix = pane === 2 ? '2' : '';
  const chart = host['chart' + suffix];
  const draw = host['draw' + suffix];
  const ui = host['alertUi' + suffix];
  const layout = el('inspect-layout-' + pane);
  const chartElement = el(pane === 2 ? 'chart2' : 'chart');
  if (!chart || !draw || !ui || !layout || !chartElement) return null;
  // Rows name a drawing as the rail and the properties title do, not by its id.
  const objects = new ChartObjects(chart, { drawings: draw, drawingName: toolName, onSettings: row => {
    const target = capturePaneTarget(host, pane);
    if (!target?.current() || target.chart !== chart) return;
    if (row.kind === 'indicator') openSettings(row.sourceId, target);
    else if (row.kind === 'drawing') mountDrawingProperties(ctx, undefined, { ids: [row.sourceId] });
    else if (row.kind === 'source') openChartSettings(undefined, target);
  } });
  const ctx = { ...ui.context, root: layout, objects };
  const themeChanged = () => applyTokens(layout, widgetTokens(chartTheme(), currentTheme()));
  themeChanged();
  document.addEventListener('oac:theme', themeChanged);
  let disposing = false;
  const dock = mountPanelDock(ctx, layout, {
    state: host['inspectionState' + pane],
    data: content => mountDataWindow(ctx, content),
    objects: content => {
      const panel = createObjectsPanelContent(ctx, { objects });
      content.appendChild(panel.element);
      return panel;
    },
    // Rows open their instrument through the same request path as the symbol box.
    // The sort lives in the page's panel store: this dock is rebuilt on every symbol load.
    watchlist: content => mountWatchlistPanel({ ...ctx, symbolSearch: watchlistSymbolSearch, storage: referencePanelStorage() }, content, {
      store: referenceWatchlists(), quotes: referenceQuotes(),
      onSelect: ({ symbol }) => {
        const target = capturePaneTarget(host, pane);
        if (target?.current() && target.chart === chart) host.changeRequest?.(target, { symbol });
      },
    }),
    news: content => mountNewsPanel(ctx, content, { feed: referenceNewsFeed }),
    onChange: state => {
      if (disposing) return;
      host['inspectionState' + pane] = state;
      autosave();
      if (host['inspection' + pane]) host.renderToolbar?.();
    },
  });
  const quick = mountQuickEntry(ctx, {
    enabled: () => directEntryEnabled(host, pane, chartElement),
    search: referenceSymbolSearch,
    onSymbol: symbol => {
      const target = capturePaneTarget(host, pane);
      if (target?.current() && target.chart === chart) host.changeRequest?.(target, { symbol });
    },
    onInterval: interval => {
      if (!INTERVALS.includes(interval)) {
        el('status').textContent = `The reference feed does not offer ${interval}`;
        return;
      }
      const target = capturePaneTarget(host, pane);
      if (target?.current() && target.chart === chart) host.changeRequest?.(target, { interval });
    },
  });
  const instance = { dock, objects, quick, context: ctx, destroy() {
    host['inspectionState' + pane] = dock.state();
    disposing = true;
    quick.destroy(); dock.destroy(); objects.destroy();
    document.removeEventListener('oac:theme', themeChanged);
  } };
  host['inspection' + pane] = instance;
  return instance;
}

export function detachInspection(host, pane = 1) {
  const key = 'inspection' + pane;
  host[key]?.destroy();
  host[key] = null;
}

export function toggleInspection(pane, panel) {
  const target = capturePaneTarget(app, pane);
  if (!target?.current()) return;
  app['inspection' + pane]?.dock.toggle(panel);
}
