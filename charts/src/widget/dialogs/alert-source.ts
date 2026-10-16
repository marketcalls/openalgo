import { widgetText } from '../localization';
import { getIndicator, registeredBarConditions, type AlertSource, type IndicatorApi } from 'openalgo-charts';
import type { WidgetContext } from '../context';
import { toolName } from '../rail';
import { numberedNames, studyNames } from '../objects-panel';
import type { FormControl } from '../form';

type Choice = { value: string; label: string };
const kinds: Choice[] = [
  { value: 'price', label: 'Price' }, { value: 'indicator', label: 'Study plot' },
  { value: 'drawing', label: 'Drawing level' }, { value: 'barCondition', label: 'Candle condition' },
];
const select = (key: string, label: string, options: Choice[]): FormControl => ({ key, label, kind: 'select', options });
/** The price pane's slot now: a study's overlay plots draw there, wherever it sits. */
const pricePane = (ctx: WidgetContext): number => ctx.chart.primaryPaneIndex();
const plots = (ctx: WidgetContext, instance: IndicatorApi | undefined, pane?: number): Choice[] => instance
  ? getIndicator(instance.indicatorId).plots.filter(plot => pane === undefined || (plot.overlay ? pricePane(ctx) : instance.paneIndex) === pane)
    .map(plot => ({ value: plot.key, label: widgetText(ctx, `schema.indicator.${instance.indicatorId}.plot.${plot.key}`, {}, plot.title) })) : [];

/** Resolve stable identities without replacing a removed selection with another object. */
export function alertSourceFields(ctx: WidgetContext, draft: Record<string, unknown>): {
  source: AlertSource; controls: FormControl[]; reason?: string | undefined; hint?: string | undefined;
} {
  const controls = [select('kind', widgetText(ctx, 'Source'), kinds.map(item => ({ ...item, label: widgetText(ctx, `schema.alert.kind.${item.value}`, {}, item.label) })))];
  // A host's unlisted studies stay out of these lists, unless the alert being
  // edited already names one, the same rule its unlisted drawings follow.
  const instances = ctx.chart.indicators().filter(item => item.policy().listed !== false
    || item.id === draft.instanceId || item.id === draft.inputInstanceId);
  const bars = ctx.chart.primaryBars();
  const at = bars.length - 1;
  const choose = (key: string, options: Choice[]): string => {
    if (draft[key] === undefined) draft[key] = options[0]?.value ?? '';
    return String(draft[key]);
  };
  const names = studyNames(ctx.chart);
  const studies = (items: readonly IndicatorApi[]): Choice[] => items.map(instance => ({ value: instance.id, label: names.get(instance.id) ?? instance.name }));
  const kind = draft.kind;
  if (kind === 'barCondition') {
    const conditions = registeredBarConditions().map(item => ({ value: item.id, label: widgetText(ctx, `schema.barCondition.${item.id}.title`, {}, item.title) }));
    const id = choose('barConditionId', conditions);
    controls.push(select('barConditionId', widgetText(ctx, 'Candle condition'), conditions));
    return { source: { kind, id }, controls, reason: conditions.some(item => item.value === id) ? undefined : widgetText(ctx, 'Candle condition is unavailable') };
  }
  if (kind === 'indicator') {
    const instanceId = choose('instanceId', studies(instances));
    const instance = instances.find(item => item.id === instanceId);
    const choices = plots(ctx, instance);
    const plotKey = choose('plotKey', choices);
    controls.push(select('instanceId', widgetText(ctx, 'Study'), studies(instances)), select('plotKey', widgetText(ctx, 'Plot'), choices));
    const value = instance?.values()[plotKey]?.[at];
    if (!('value' in draft)) draft.value = value ?? undefined;
    return {
      source: { kind, instanceId, plotKey, value: draft.value as number, upperValue: draft.upperValue as number | undefined }, controls,
      reason: !instance ? widgetText(ctx, 'Study instance is unavailable') : !instance.series(plotKey) ? widgetText(ctx, 'Study plot is unavailable') : undefined,
      hint: Number.isFinite(value) ? undefined : widgetText(ctx, 'The current plot value is unavailable. The alert waits for observed values.'),
    };
  }
  if (kind === 'drawing') {
    // A host's unlisted drawings stay out of every list, this one included,
    // unless the alert being edited already names one.
    const all = ctx.draw.drawings(), listed = (item: (typeof all)[number]): boolean => item.policy?.listed !== false;
    const named = numberedNames(all, item => widgetText(ctx, `schema.drawing.${item.tool}.name`, {}, toolName(item.tool)), listed);
    const choices = all.filter(item => listed(item) || item.id === draft.drawingId).map(item => ({ value: item.id, label: named.get(item.id)! }));
    const drawingId = choose('drawingId', choices);
    const info = ctx.draw.alertInfo(drawingId);
    const levels = info.levels.map(item => ({ value: item.id, label: item.title }));
    const level = choose('level', levels);
    controls.push(select('drawingId', widgetText(ctx, 'Drawing'), choices), select('level', widgetText(ctx, 'Level'), levels));
    const compatible = instances.filter(item => plots(ctx, item, info.paneIndex).length > 0);
    const inputs = studies(compatible);
    if (info.paneIndex === pricePane(ctx)) inputs.unshift({ value: '', label: widgetText(ctx, 'Price') });
    const inputInstanceId = choose('inputInstanceId', inputs);
    controls.push(select('inputInstanceId', widgetText(ctx, 'Compare with'), inputs));
    const instance = compatible.find(item => item.id === inputInstanceId);
    let input: { instanceId: string; plotKey: string } | undefined;
    if (inputInstanceId) {
      const choices = plots(ctx, instance, info.paneIndex);
      const plotKey = choose('inputPlotKey', choices);
      input = { instanceId: inputInstanceId, plotKey };
      controls.push(select('inputPlotKey', widgetText(ctx, 'Input plot'), choices));
    }
    const reason = !info.available ? info.reason
      : !levels.some(item => item.value === level) ? widgetText(ctx, 'Drawing level is unavailable')
        : input ? !plots(ctx, instance, info.paneIndex).some(plot => plot.value === input.plotKey) ? widgetText(ctx, 'Select an input plot on the drawing pane') : undefined
          : info.paneIndex !== pricePane(ctx) ? widgetText(ctx, 'Select an input plot on the drawing pane') : undefined;
    return { source: { kind, drawingId, level, ...(input ? { input } : {}) }, controls, reason };
  }
  if (!('price' in draft)) draft.price = bars[at]?.close;
  return { source: { kind: 'price', price: draft.price as number, upperPrice: draft.upperPrice as number | undefined }, controls };
}
