import {
  getIndicator, parsePaneState, registeredIndicators,
  type Chart, type ChartRestoreOptions, type IndicatorDescriptor, type IndicatorState, type IndicatorStudySource,
  type PaneState, type PriceScaleId, type PriceScaleState,
} from 'openalgo-charts';
import {
  hostOwnedStudy, MAX_PANE_SLOT, parseIndicatorStates, parseIndicatorTemplatePayload, releaseScaleOwner,
  type IndicatorTemplateInput, type IndicatorTemplateLayout, type IndicatorTemplatePayload, type IndicatorTemplatePlotBinding,
} from './documents';
import { choice, readJson, record, WorkspaceDocumentError } from './json';
import {
  checkPlanned, fromTemplatePane, planIndicatorTemplate, remapTemplateIndicatorIds, toTemplatePane, type IndicatorTemplateMode,
} from './templates';

export interface IndicatorTemplateApplyOptions {
  /** Copy isolates non-primary main-pane scales; share keeps existing destination settings. */
  scalePolicy?: 'copy' | 'share';
  /** Auto fits copied axes to current data or their fixed band; preserve retains saved views. */
  rangePolicy?: 'auto' | 'preserve';
}

export interface IndicatorTemplatePlan {
  indicators: IndicatorState[];
  panes?: PaneState[];
  /**
   * Slot of the price pane in `panes`, present only when the destination keeps
   * its price pane below a study pane. Forward it beside `panes` as the
   * restored state's `primaryPane` (a version 2 state), or the restore puts
   * the price pane back at the top and lays its settings on a study pane.
   */
  primaryPane?: number;
  /** Forward as restoreState's second argument to retain destination runtime formatters. */
  restoreOptions?: ChartRestoreOptions;
}

function scaleEntries(pane: PaneState): [PriceScaleId, PriceScaleState][] {
  return [['right', pane.priceScale], ...Object.entries(pane.scales ?? {})] as [PriceScaleId, PriceScaleState][];
}

function scaleState(pane: PaneState, id: PriceScaleId): PriceScaleState | undefined {
  return id === 'right' ? pane.priceScale : pane.scales?.[id];
}

/** The scale id on the price pane, at chart slot `slot`, that the primary series maps to. */
function primaryId(chart: Chart, slot: number, pane: PaneState): PriceScaleId | undefined {
  const primary = chart.primarySeries();
  if (!primary) return undefined;
  const target = primary.priceScale();
  // `slot` is the chart's price pane slot, and a chart always has its price pane.
  return scaleEntries(pane).find(([id]) => chart.panes()[slot]!.scaleFor(id) === target)?.[0];
}

/**
 * A chart's pane list in template order: the price pane first, the rest in
 * their order. `primary` is the price pane's slot in `items`, so the list is
 * never empty.
 */
function templateOrder<T>(items: readonly T[], primary: number): [T, ...T[]] {
  return [items[primary]!, ...items.filter((_, index) => index !== primary)];
}

/** A template-order pane list back in chart order, the price pane at `primary`. */
function chartOrder<T>(items: readonly T[], primary: number): T[] {
  const out: T[] = [];
  items.forEach((item, slot) => { out[fromTemplatePane(slot, primary)] = item; });
  return out;
}

/**
 * Capture effective bindings and scale configuration, without data or runtime
 * callbacks. The template is written price pane first (see
 * `IndicatorTemplateLayout`), so a chart whose price pane sits below its
 * studies captures the same portable document as one whose price pane is on top.
 */
export function captureIndicatorTemplate(chart: Chart): IndicatorTemplatePayload {
  const state = chart.getState(), visual = state.panes;
  if (!visual?.length) throw new WorkspaceDocumentError('Cannot capture a destroyed chart');
  const primary = chart.primaryPaneIndex(), panes = templateOrder(visual, primary);
  const plots: IndicatorTemplatePlotBinding[] = [];
  for (const instance of chart.indicators()) for (const plot of getIndicator(instance.indicatorId).plots) {
    const handle = instance.series(plot.key), scaleId = instance.plotPriceScaleId(plot.key);
    if (!handle || chart.seriesType(handle) === null || scaleId === null) {
      throw new WorkspaceDocumentError('Cannot capture a removed indicator plot');
    }
    plots.push({ instanceId: instance.id, plotKey: plot.key,
      paneIndex: plot.overlay === true ? 0 : toTemplatePane(instance.paneIndex, primary), scaleId });
  }
  const layout: IndicatorTemplateLayout = { panes, plots };
  const id = primaryId(chart, primary, panes[0]);
  if (id !== undefined) layout.primaryScaleId = id;
  const indicators = (state.indicators ?? []).map(study => ({ ...study, paneIndex: toTemplatePane(study.paneIndex, primary) }));
  return parseIndicatorTemplatePayload({ indicators, layout });
}

function validateBindings(studies: readonly IndicatorState[], layout: IndicatorTemplateLayout): Map<string, IndicatorTemplatePlotBinding[]> {
  const byStudy = new Map<string, IndicatorTemplatePlotBinding[]>();
  for (const binding of layout.plots) {
    const group = byStudy.get(binding.instanceId) ?? [];
    group.push(binding); byStudy.set(binding.instanceId, group);
  }
  for (const study of studies) {
    const descriptor = getIndicator(study.indicatorId), bindings = byStudy.get(study.instanceId!) ?? [];
    const inputs = descriptor.inputs.filter(input => input.type === 'source'
      && typeof (Object.prototype.hasOwnProperty.call(study.settings, input.key) ? study.settings[input.key] : input.default) !== 'string');
    const declared = new Set(study.studyInputs ?? []);
    if (inputs.length !== declared.size || inputs.some(input => !declared.has(input.key)
      || input.type !== 'source' || input.allowStudyOutputs !== true)) {
      throw new WorkspaceDocumentError('Template dependency metadata disagrees with its source inputs');
    }
    for (const key of declared) {
      const reference = study.settings[key] as IndicatorStudySource;
      const producer = studies.find(candidate => candidate.instanceId === reference.instanceId)!;
      const selected = getIndicator(producer.indicatorId).plots.filter(plot => plot.key === reference.plotKey);
      if (selected.length !== 1 || selected[0]!.ohlc !== undefined) {
        throw new WorkspaceDocumentError('Template study source must identify one declared scalar plot');
      }
    }
    if (bindings.length !== descriptor.plots.length) throw new WorkspaceDocumentError('Template needs every declared plot binding');
    for (const binding of bindings) {
      const plot = descriptor.plots.find(item => item.key === binding.plotKey);
      if (!plot || binding.paneIndex !== (plot.overlay === true ? 0 : study.paneIndex)) {
        throw new WorkspaceDocumentError('Template plot key or pane disagrees with its descriptor');
      }
    }
    validateFills(descriptor, study, bindings);
  }
  return byStudy;
}

function validateFills(descriptor: IndicatorDescriptor, study: IndicatorState, bindings: readonly IndicatorTemplatePlotBinding[]): void {
  const firstLocal = descriptor.plots.find(plot => plot.overlay !== true);
  const local = firstLocal ? bindings.find(binding => binding.plotKey === firstLocal.key)!.scaleId : study.priceScaleId ?? 'right';
  for (const fill of descriptor.fills ?? []) {
    const pane = fill.overlay === true ? 0 : study.paneIndex;
    // `between` is a pair, so there are two endpoints.
    const endpoints = fill.between.map(key => bindings.find(binding => binding.plotKey === key)
      ?? { paneIndex: pane, scaleId: fill.overlay === true ? 'right' : local });
    if (endpoints.some(endpoint => endpoint.paneIndex !== pane) || endpoints[0]!.scaleId !== endpoints[1]!.scaleId) {
      throw new WorkspaceDocumentError('Template fill endpoints must share their pane and scale');
    }
  }
}

/** Panes holding host series, in template slots. */
function hostPanes(chart: Chart): Set<number> {
  const counts = chart.panes().map(pane => pane.series().length), primary = chart.primaryPaneIndex();
  for (const instance of chart.indicators()) for (const plot of getIndicator(instance.indicatorId).plots) {
    const handle = instance.series(plot.key);
    // A study's pane, and the price pane, are both panes of the chart that `counts` lists.
    if (handle && chart.seriesType(handle) !== null) counts[plot.overlay === true ? primary : instance.paneIndex]!--;
  }
  return new Set(counts.flatMap((count, index) => count > 0 ? [toTemplatePane(index, primary)] : []));
}

function defaultScale(): PriceScaleState {
  return { marginTop: 0.1, marginBottom: 0.1, minMove: 0, minPrecision: 0, mode: 'linear', inverted: false, autoScale: true };
}

function copiedScale(source: PriceScaleState, owners: ReadonlyMap<string, string>, preserve: boolean): PriceScaleState {
  const scale = parsePaneState({ weight: 1, priceScale: source }).priceScale;
  if (preserve) {
    if (scale.indicatorRange) scale.indicatorRange.instanceId = owners.get(scale.indicatorRange.instanceId)!;
  } else {
    scale.autoScale = true;
    delete scale.range; delete scale.ratioLock;
    if (scale.indicatorRange) { delete scale.indicatorRange; delete scale.fixedRange; }
  }
  return scale;
}

function clearOutgoingOwners(panes: PaneState[], outgoing: ReadonlySet<string>): void {
  for (const pane of panes) for (const [, scale] of scaleEntries(pane)) {
    const owner = scale.indicatorRange;
    if (owner && outgoing.has(owner.instanceId)) releaseScaleOwner(scale);
  }
}

/**
 * Plan a detached patch. The host owns restore, cancellation and recovery.
 *
 * The plan is in the destination's own slots, and keeps its price pane where
 * it is: a template's price pane is the destination's price pane, and its
 * study panes take the slots around it in order. When that slot is not 0 the
 * plan carries it as `primaryPane`, and lists the destination's panes.
 */
export function planIndicatorTemplateState(chart: Chart, incoming: IndicatorTemplateInput, mode: IndicatorTemplateMode,
  options: IndicatorTemplateApplyOptions = {}): IndicatorTemplatePlan {
  if (mode !== 'replace' && mode !== 'append') throw new WorkspaceDocumentError('Unsupported indicator template mode');
  const primary = chart.primaryPaneIndex();
  const plan = planTemplateOrder(chart, incoming, mode, options, primary);
  if (primary === 0) return plan;
  // Back to the chart's order. Only a chart whose price pane moved gets here, so
  // a chart with its price pane on top receives exactly the plan it always did.
  const out: IndicatorTemplatePlan = {
    indicators: plan.indicators.map(study => ({ ...study, paneIndex: fromTemplatePane(study.paneIndex, primary) })),
    panes: plan.panes ? chartOrder(plan.panes, primary) : listedPanes(chart, mode),
    primaryPane: primary,
  };
  if (plan.restoreOptions) out.restoreOptions = { preserveScaleFormats: (plan.restoreOptions.preserveScaleFormats ?? [])
    .map(selector => ({ ...selector, paneIndex: fromTemplatePane(selector.paneIndex, primary) })) };
  return out;
}

/**
 * The destination's own panes, for a template without a layout on a chart
 * whose price pane moved: the price pane keeps its slot only if the panes above
 * it are listed. Replace lets go of the outgoing studies' scale ranges, the way
 * a layout plan does, so a new study that takes a slot does not inherit them.
 */
function listedPanes(chart: Chart, mode: IndicatorTemplateMode): PaneState[] {
  const state = chart.getState(), panes = (state.panes ?? []).map(pane => parsePaneState(pane));
  if (mode === 'replace') clearOutgoingOwners(panes, new Set((state.indicators ?? []).flatMap(study => study.instanceId ? [study.instanceId] : [])));
  return panes;
}

/**
 * Where each of the template's study panes lands: the next slot from `first`
 * that holds nothing the plan keeps, in the template's order. Pane zero is
 * the price pane on both sides.
 */
function templateSlots(additions: readonly IndicatorState[], reserved: ReadonlySet<number>, first: number): Map<number, number> {
  const paneMap = new Map<number, number>([[0, 0]]);
  let nextPane = first;
  for (const sourcePane of [...new Set(additions.map(study => study.paneIndex).filter(index => index > 0))].sort((a, b) => a - b)) {
    while (reserved.has(nextPane)) nextPane++;
    if (nextPane > MAX_PANE_SLOT) throw new WorkspaceDocumentError('Indicator pane limit exceeded');
    paneMap.set(sourcePane, nextPane++);
  }
  return paneMap;
}

/**
 * Each template study pane onto its slot, its weight scaled from the
 * template's price pane to the destination's, with its scales as `copy`
 * makes them.
 */
function copyTemplatePanes(panes: PaneState[], source: readonly PaneState[], paneMap: ReadonlyMap<number, number>,
  copy: (pane: PaneState) => ReadonlyArray<readonly [PriceScaleId, PriceScaleState]>): void {
  const main = panes[0]!, templateMain = source[0]!; // both sides always have a price pane (see the planner)
  for (const [sourcePane, targetPane] of paneMap) {
    if (!sourcePane) continue;
    const from = source[sourcePane]!;
    const weight = from.weight / templateMain.weight * main.weight;
    if (!(weight > 0) || !Number.isFinite(weight)) throw new WorkspaceDocumentError('Template pane weight is not representable');
    const entries = copy(from);
    // scaleEntries lists the right scale first, so a pane always has entry zero.
    panes[targetPane] = { weight, priceScale: entries[0]![1],
      ...(entries.length > 1 ? { scales: Object.fromEntries(entries.slice(1)) } : {}) };
  }
}

/** The planner proper, run with the destination read in template order. */
function planTemplateOrder(chart: Chart, incoming: IndicatorTemplateInput, mode: IndicatorTemplateMode,
  options: IndicatorTemplateApplyOptions, primary: number): IndicatorTemplatePlan {
  const settings = record(readJson(options), 'template apply options');
  const policy = choice(settings.scalePolicy, 'scale policy', ['copy', 'share'] as const, 'copy');
  const preserve = choice(settings.rangePolicy, 'range policy', ['auto', 'preserve'] as const, 'auto') === 'preserve';
  const incomingState = parseIndicatorTemplatePayload(incoming), live = chart.getState();
  if (!live.panes?.length) throw new WorkspaceDocumentError('Cannot plan for a destroyed chart');
  const current = { ...live, panes: templateOrder(live.panes, primary),
    indicators: (live.indicators ?? []).map(study => ({ ...study, paneIndex: toTemplatePane(study.paneIndex, primary) })) };
  const available = new Set(registeredIndicators().map(item => item.id));
  if (!incomingState.layout) {
    return { indicators: planIndicatorTemplate(current.indicators, incomingState.indicators, mode, available, current.panes.length) };
  }
  const layout = incomingState.layout, additions = incomingState.indicators, previous = parseIndicatorStates(current.indicators ?? []);
  // A study the host keeps from the user survives a replace, and its pane is kept out of the template's way.
  const kept = mode === 'replace' ? previous.filter(study => hostOwnedStudy(study.policy)) : [];
  const planned = mode === 'append' ? [...previous, ...additions] : [...kept, ...additions];
  checkPlanned(planned, available);
  const bindings = validateBindings(additions, layout);
  const reservedPanes = mode === 'replace' ? hostPanes(chart) : new Set<number>();
  for (const study of kept) if (study.paneIndex > 0) reservedPanes.add(study.paneIndex);
  const restoreOptions: ChartRestoreOptions = { preserveScaleFormats: current.panes.flatMap((pane, paneIndex) =>
    paneIndex === 0 || mode === 'append' || reservedPanes.has(paneIndex)
      ? scaleEntries(pane).map(([scaleId]) => ({ paneIndex, scaleId })) : []) };
  if (mode === 'append' && !additions.length) return { indicators: previous, restoreOptions };
  const destinationPrimary = primaryId(chart, primary, current.panes[0]);
  const panes = current.panes.map(pane => parsePaneState(pane));
  if (mode === 'replace') clearOutgoingOwners(panes, new Set(previous.filter(study => !kept.includes(study))
    .flatMap(study => study.instanceId ? [study.instanceId] : [])));
  const paneMap = templateSlots(additions, reservedPanes, mode === 'append' ? panes.length : 1);
  const originalIds = additions.map(study => study.instanceId!);
  const owners = remapTemplateIndicatorIds(previous, additions);
  // Parsing gave the template a pane zero and put every template study on one of
  // its panes; the destination always has its price pane. A study pane lands at
  // slot 1 or later, so `main` stays the destination's price pane.
  const main = panes[0]!, templateMain = layout.panes[0]!;
  copyTemplatePanes(panes, layout.panes, paneMap, pane => scaleEntries(pane).map(([id, scale]) => [id, copiedScale(scale, owners, preserve)] as const));
  const originalMainIds = new Set(scaleEntries(main).map(([id]) => id));
  const scaleMap = new Map<PriceScaleId, PriceScaleId>();
  const copiedColumns: { id: PriceScaleId; source: PriceScaleState }[] = [];
  let nextScale = 1;
  const mapScale = (pane: number, id: PriceScaleId): PriceScaleId => {
    if (pane > 0) return id;
    const cached = scaleMap.get(id);
    if (cached !== undefined) return cached;
    if (id === layout.primaryScaleId && destinationPrimary !== undefined) {
      scaleMap.set(id, destinationPrimary); return destinationPrimary;
    }
    let target = id;
    if (policy === 'copy') {
      // Only the loop over `additions` below calls this, so there is a first addition.
      do { target = `overlay:template-scale-${additions[0]!.instanceId}-${nextScale++}`; } while (scaleState(main, target));
    }
    scaleMap.set(id, target);
    if (!scaleState(main, target)) {
      const source = scaleState(templateMain, id) ?? defaultScale();
      const scale = copiedScale(source, owners, preserve);
      if (target === 'right') main.priceScale = scale;
      else { main.scales ??= {}; main.scales[target] = scale; }
      if (policy === 'copy') copiedColumns.push({ id: target, source: { ...source,
        placement: source.placement ?? { side: id === 'left' || id === 'right' ? id : 'hidden', order: 0 } } });
    }
    return target;
  };
  additions.forEach((study, index) => {
    // `originalIds` was mapped from `additions`, one id per study.
    const original = originalIds[index]!, originalPane = study.paneIndex;
    const maps = (bindings.get(original) ?? []).map(binding => [binding.plotKey, mapScale(binding.paneIndex, binding.scaleId)]);
    if (maps.length) study.plotPriceScaleIds = Object.fromEntries(maps);
    if (study.priceScaleId !== undefined) study.priceScaleId = mapScale(originalPane, study.priceScaleId);
    else if (!getIndicator(study.indicatorId).plots.some(plot => plot.overlay !== true)) study.priceScaleId = mapScale(originalPane, 'right');
    study.paneIndex = paneMap.get(originalPane)!;
    // Unplotted overlay fill columns always use the native right fallback.
    // A primary relation remap must remain representable by that same contract.
    // Every binding's plot key was written into plotPriceScaleIds just above.
    validateFills(getIndicator(study.indicatorId), study, (bindings.get(original) ?? []).map(binding => ({ ...binding,
      paneIndex: paneMap.get(binding.paneIndex)!, scaleId: study.plotPriceScaleIds![binding.plotKey]! })));
  });
  for (const side of ['left', 'right', 'hidden'] as const) {
    let order = Math.max(-1, ...scaleEntries(main).filter(([id]) => originalMainIds.has(id))
      .map(([id, scale]) => scale.placement ?? { side: id === 'left' || id === 'right' ? id : 'hidden', order: 0 })
      .filter(placement => placement.side === side).map(placement => placement.order)) + 1;
    for (const column of copiedColumns.filter(column => column.source.placement!.side === side)
      .sort((a, b) => a.source.placement!.order - b.source.placement!.order)) {
      scaleState(main, column.id)!.placement = { side, order: order++ };
    }
  }
  return { indicators: planned, panes, restoreOptions };
}
