/**
 * Indicator templates in the widget: the studies on a chart saved by name in
 * a `WorkspaceStore`, and a saved set applied again, replacing the studies on
 * the chart or added beside them. The indicator picker opens the list from
 * its footer; the list loads on first use (layouts-templates-menu.ts).
 *
 * The planning is the workspace tier's (`planIndicatorTemplateState`), reached
 * through the store the host hands over, so the widget tier loads no code of
 * that tier on its own. A store without the member offers no templates.
 *
 * Undo: a template lands through the chart's `restoreState`, which rebuilds
 * every study and so starts a new undo timeline, as loading a layout does.
 * The apply itself is recorded as the one step on it: Ctrl+Z puts the studies
 * and panes back as they were (the drawings, alerts and view stay as they are
 * then), and Ctrl+Y applies the template again. Steps taken before the apply
 * are gone, because the studies they name were rebuilt.
 */
import { isReplaying, type ChartRestoreOptions, type ChartState } from 'openalgo-charts';
import type {
  IndicatorTemplateDocument, IndicatorTemplateInput, IndicatorTemplatePlan, WorkspaceStore,
} from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import { hostOwnedStudy } from '../model/indicator-policy';

export type IndicatorTemplateApplyMode = 'replace' | 'append';

/** The store each widget was given, for the picker the dialog registry mounts with the context alone. */
const stores = new WeakMap<object, WorkspaceStore>();

/** Internal: give the widget in `ctx` its template store, or take it away. */
export function bindTemplateStore(ctx: WidgetContext, store: WorkspaceStore | undefined): void {
  if (store === undefined) stores.delete(ctx);
  else stores.set(ctx, store);
}

/** Internal: the store the widget in `ctx` was given, if any. */
export function templateStoreOf(ctx: WidgetContext): WorkspaceStore | undefined {
  return stores.get(ctx);
}

/** The price pane's slot as a chart state names it: version 2 carries one below the top. */
const layoutState = (indicators: ChartState['indicators'], panes: ChartState['panes'], primaryPane: number | undefined, rest: Partial<ChartState>): ChartState => ({
  version: primaryPane !== undefined && primaryPane > 0 ? 2 : 1, indicators: indicators ?? [], panes,
  ...(primaryPane === undefined ? {} : { primaryPane }), ...rest,
});

/**
 * The retained scales a plan names that still exist on the chart: a restore
 * refuses a selector for a scale it cannot find, and one the apply removed
 * gets its format back from its study's descriptor anyway.
 */
function preserved(plan: IndicatorTemplatePlan, now: ChartState): ChartRestoreOptions {
  const panes = now.panes ?? [];
  return { preserveScaleFormats: (plan.restoreOptions?.preserveScaleFormats ?? []).filter(({ paneIndex, scaleId }) =>
    panes[paneIndex] !== undefined && (scaleId === 'right' || Object.prototype.hasOwnProperty.call(panes[paneIndex].scales ?? {}, scaleId))) };
}

/**
 * Apply a template to the chart in `ctx`: `replace` puts its studies in place
 * of the user's (a study the host keeps stays), `append` adds them in new
 * panes. False when appending found nothing to add. A failure puts the chart
 * back as it was and throws.
 */
export function applyIndicatorTemplate(ctx: Pick<WidgetContext, 'chart' | 'history'>, store: WorkspaceStore,
  template: IndicatorTemplateInput, mode: IndicatorTemplateApplyMode, label?: string): boolean {
  const { chart } = ctx;
  if (store.planIndicatorTemplateState === undefined) throw new Error('This template store cannot apply templates');
  // A replay owns the bars on screen; studies rebuilt now would compute from a moment in the past.
  if (isReplaying(chart)) throw new Error('Stop the replay before applying a template');
  const before = chart.getState();
  const plan = store.planIndicatorTemplateState(chart, template, mode);
  if (mode === 'append' && plan.indicators.length === (before.indicators ?? []).length) return false;
  // Drawings and alerts ride along: a restore that names none clears them.
  const kept = { drawings: before.drawings, alerts: before.alerts };
  // So does a price source moved over a study the plan keeps: a restore that
  // rebuilds the studies without naming it puts the source back at the bottom.
  const above = before.sourceAbove !== undefined && plan.indicators.some(study => study.instanceId === before.sourceAbove)
    ? { sourceAbove: before.sourceAbove } : {};
  let started = false;
  const off = chart.on('state:restore:start', () => { started = true; });
  try {
    const report = chart.restoreState(layoutState(plan.indicators,
      plan.panes ?? (mode === 'append' ? before.panes : before.panes?.slice(0, 1)), plan.primaryPane, { ...kept, ...above }), plan.restoreOptions ?? {});
    if (!report.applied) throw new Error(report.reason ?? 'The template could not be applied');
    if (report.indicators !== plan.indicators.length) throw new Error('The chart did not restore every study');
  } catch (error) {
    // Only a restore that began changed anything; one refused up front left the chart alone.
    if (started) {
      chart.restoreState(layoutState(before.indicators, before.panes, before.primaryPane, {
        ...kept, ...(before.sourceAbove === undefined ? {} : { sourceAbove: before.sourceAbove }), viewport: before.viewport, barSpacing: before.barSpacing,
      }), preserved(plan, chart.getState()));
    }
    throw error;
  } finally { off(); }
  const after = chart.getState();
  // Each way puts back the studies and panes of one side and keeps what the
  // chart holds then: a drawing or an alert added since is not the template's.
  const swap = (side: ChartState): boolean => {
    const now = chart.getState();
    return chart.restoreState(layoutState(side.indicators, side.panes, side.primaryPane,
      { ...(side.sourceAbove === undefined ? {} : { sourceAbove: side.sourceAbove }), drawings: now.drawings, alerts: now.alerts }),
    preserved(plan, now)).applied;
  };
  ctx.history?.push({ label, undo: () => swap(before), redo: () => swap(after) });
  return true;
}

/**
 * A study the host keeps from the user (one the user cannot see or remove) is
 * the host's: no template holds it. The rule is the workspace tier's template
 * parser's, taken from the base by path; the menu imports it under this name.
 */
export { hostOwnedStudy as hostKept };

/**
 * Save the user's studies on the chart as a template: with their panes and
 * scales when the store can capture them, else as the plain study list.
 * Rejects when the chart has none of the user's own, rather than store an
 * empty template.
 */
export function saveIndicatorTemplate(ctx: Pick<WidgetContext, 'chart'>, store: WorkspaceStore, name: string): Promise<IndicatorTemplateDocument> {
  let input: IndicatorTemplateInput;
  try {
    input = store.captureIndicatorTemplate?.(ctx.chart) ?? (ctx.chart.getState().indicators ?? []).filter(study => !hostOwnedStudy(study.policy));
  } catch (error) { return Promise.reject(error); }
  const studies = Array.isArray(input) ? input : input.indicators;
  if (studies.length === 0) return Promise.reject(new Error('The chart has no studies of yours to save'));
  return store.createTemplate(name, input);
}
