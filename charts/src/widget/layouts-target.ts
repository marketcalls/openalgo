/**
 * One widget as the target of a layouts controller: its state as a portable
 * one-chart workspace payload, and a saved one-chart layout put back through
 * `restoreState`.
 *
 * Built from the widget's public state alone, so the widget tier needs no
 * code from the workspace tier to save a layout: the payload is written here
 * in the form `migrateWidgetWorkspace` produces, and the store parses it.
 *
 * Three decisions worth recording:
 *
 * - **A layout is what is on the chart, not where it was scrolled.** The
 *   capture leaves out the viewport, the bar spacing and every pinned price
 *   range (`stripView`), as a layout opened on another symbol already did.
 *   Otherwise every pan, and every bar a live feed adds, would read as an
 *   unsaved change and cost an autosave write; an opened layout fits the
 *   bars it loads instead.
 * - **A layout holds the alerts the user set, not how far they have judged
 *   the feed.** Each closed bar moves an alert's bookkeeping (the last bar
 *   judged, the last touch and trigger), so keeping it would mark the layout
 *   unsaved on every bar, and two tabs holding it would each write it and
 *   refuse the other. An alert's `state` stays: a spent alert is kept spent.
 *   A restored alert is judged from the loaded bars onwards, as after a reload.
 * - **A replay suspends it.** While a replay owns the chart its bars stop at a
 *   moment in the past; autosave waits for the replay to end, and a layout is
 *   not opened under it.
 */
import { isKnownInterval, isReplaying, registeredIndicators } from 'openalgo-charts';
import { isChartTypeChoice } from './chart-type-choice';
import type { WorkspaceChartState, WorkspacePane, WorkspacePayload } from 'openalgo-charts/workspace';
import type { LayoutApplyReport, LayoutTarget } from './layouts';
import type { Widget, WidgetChartState, WidgetRestoreReport, WidgetState } from './widget';
import { stripView } from './widget-persist';

/** Where a layout keeps a chart's theme: one widget's layout and the chart grid's desk alike. Internal. */
export const THEME_SETTING = 'widget.theme';
const PANE = 'p0';
const WIDGET_EVENTS = ['symbol', 'interval', 'variant', 'theme', 'layout'] as const;
/**
 * Changes a layout holds that the widget raises no event of its own for, and
 * the replay events that suspend autosave or let it go on. A study, a setting
 * or a drawing changes the chart's objects, which the widget announces as a
 * `layout` event; an alert does not.
 */
const CHART_EVENTS = [
  'alert:created', 'alert:updated', 'alert:removed', 'alert:triggered', 'alert:expired',
  'replay:start', 'replay:stop', 'replay:end',
] as const;

/** Alert fields the chart advances as bars close; see the module notes. */
const ALERT_BOOKKEEPING = ['lastClosedTime', 'lastTouchedTime', 'lastTriggeredAt', 'lastTriggeredTime'] as const;

/**
 * Internal: a chart state as a layout keeps it, without the view or the alerts'
 * bookkeeping. A chart grid's target writes its charts the same way.
 */
export function layoutChartState(chart: WidgetChartState): WorkspaceChartState {
  const out = stripView(chart) as WorkspaceChartState;
  const alerts = out.alerts;
  if (alerts === undefined || !Array.isArray(alerts.alerts)) return out;
  return {
    ...out,
    alerts: { ...alerts, alerts: alerts.alerts.map(alert => {
      const kept = { ...alert } as Record<string, unknown>;
      for (const key of ALERT_BOOKKEEPING) delete kept[key];
      return kept as unknown as typeof alert;
    }) },
  };
}

/**
 * A widget's state as a workspace pane, with `chart` as the caller keeps it:
 * a layout without the view, the chart grid's own desk with it. The widget
 * draws no separate volume series and no comparisons, so it saves neither
 * rather than claim a preference it cannot show. Internal, shared with the
 * chart grid.
 */
export function widgetPane(id: string, state: WidgetState, chart: WorkspaceChartState): WorkspacePane {
  return { id, symbol: state.symbol, exchange: state.exchange, interval: state.interval, ...(state.variant ? { variant: state.variant } : {}),
    chartType: state.chartType, chart, settings: { [THEME_SETTING]: state.theme }, volume: false,
    magnet: state.rail?.magnet ?? 'off', stay: state.rail?.stay ?? false, comparisons: [], comparisonMode: 'percent' };
}

/**
 * Put a workspace pane on a widget, with the pane's theme when `withTheme`
 * (the chart grid gives every chart one theme itself). The pane carries the
 * rail's magnet and stay; the rest of the rail (pins, last tools) stays the
 * user's. Internal, shared with the chart grid.
 */
export function restorePane(widget: Widget, pane: WorkspacePane, withTheme: boolean): WidgetRestoreReport {
  const theme = withTheme ? pane.settings[THEME_SETTING] : undefined;
  const rail = widget.getState().rail;
  return widget.restoreState({
    version: 1, symbol: pane.symbol, exchange: pane.exchange, interval: pane.interval, chartType: pane.chartType, chart: pane.chart,
    ...(theme === 'dark' || theme === 'light' ? { theme } : {}), ...(pane.variant ? { variant: pane.variant } : {}),
    ...(rail === null ? {} : { rail: { ...rail, magnet: pane.magnet, stay: pane.stay } }),
  });
}

/** Why a saved layout cannot show on one widget, checked before anything changes; empty when it can. */
function refusal(payload: WorkspacePayload): string {
  if (payload.panes.length !== 1) return `a layout of ${payload.panes.length} charts needs a chart grid`;
  const [pane] = payload.panes as [WorkspacePane]; // exactly one, checked above
  if (!isKnownInterval(pane.interval)) return `unknown interval ${pane.interval}`;
  if (!isChartTypeChoice(pane.chartType)) return `unknown chart type ${pane.chartType}`;
  if (pane.comparisons.length > 0) return 'comparison symbols are not supported in a widget chart';
  const studies = new Set(registeredIndicators().map(descriptor => descriptor.id));
  const missing = (pane.chart.indicators ?? []).find(study => !studies.has(study.indicatorId));
  return missing === undefined ? '' : `unavailable study ${missing.indicatorId}`;
}

/**
 * A `LayoutTarget` for one widget: pass it to `createLayoutsController`. The
 * widget's own `workspaces` option builds one; a host driving its own menu
 * builds it here.
 */
export function widgetLayoutTarget(widget: Widget): LayoutTarget {
  return {
    capture(): WorkspacePayload {
      // A chart state carries absent optional fields; the portable form is plain JSON.
      const state = JSON.parse(JSON.stringify(widget.getState())) as ReturnType<Widget['getState']>;
      const pane = widgetPane(PANE, state, layoutChartState(state.chart));
      return {
        layout: { rows: 1, columns: 1, slots: [{ paneId: PANE, row: 0, column: 0, rowSpan: 1, columnSpan: 1 }] },
        panes: [pane], activePaneId: PANE, sync: { crosshair: true, viewport: true, symbol: false, interval: false },
      };
    },
    apply(payload): LayoutApplyReport {
      // The widget sets its theme and chart type before the chart half, so what
      // it would refuse part way is refused here, before anything changes.
      const reason = refusal(payload);
      if (reason !== '') return { applied: false, reason };
      const [pane] = payload.panes as [WorkspacePane]; // refusal() lets only a single pane through
      const report = restorePane(widget, pane, true);
      return report.applied ? { applied: true } : { applied: false, reason: report.reason ?? 'the chart state could not be restored' };
    },
    subscribe(listener) {
      const offs = [
        ...WIDGET_EVENTS.map(event => widget.on(event, listener)),
        ...CHART_EVENTS.map(event => widget.chart.on(event, listener)),
        // An undo or a redo puts the chart back without raising any event.
        widget.history.subscribe(listener),
      ];
      return () => { for (const off of offs) off(); };
    },
    suspended: () => isReplaying(widget.chart),
  };
}
