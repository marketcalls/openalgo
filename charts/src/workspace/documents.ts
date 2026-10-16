import type {
  ChartState, ChartSettingsState, DataVariant, IndicatorState, LinkMissingPolicy, PaneState, PriceScaleId, PriceScaleState,
  SeriesState, SeriesTransformSpec,
} from 'openalgo-charts';
import { normalizeDataVariant, parseAlertsDocument, parseIndicatorPolicy, parsePaneState } from 'openalgo-charts';
import { boolean, choice, list, number, readJson, record, string, WorkspaceDocumentError, type Json } from './json';
import { hostOwnedStudy } from '../model/indicator-policy';
import { isPriceScaleId } from '../model/price-axis-layout';

export { WorkspaceDocumentError } from './json';
export const WORKSPACE_VERSION = 1;
/** The last pane slot a portable document may name: 32 panes, slots 0 to 31. Internal. */
export const MAX_PANE_SLOT = 31;
/** The most studies one chart or template may hold. Internal. */
export const MAX_STUDIES = 256;
export type WorkspaceKind = 'workspace' | 'indicator-template';
export type WorkspaceSettings = Record<string, string | number | boolean>;
export type WorkspaceChartState = ChartState & ChartSettingsState & { timezone?: string };
export interface WorkspaceComparison {
  id: string; symbol: string; exchange: string; color?: string; visible: boolean;
}
export interface WorkspaceSlot {
  paneId: string; row: number; column: number; rowSpan: number; columnSpan: number;
}
export interface WorkspacePane {
  id: string; symbol: string; exchange: string; interval: string; chartType: string;
  /** Which of the provider's series the chart showed. Absent is the provider's default. */
  variant?: DataVariant;
  chart: WorkspaceChartState; settings: WorkspaceSettings;
  volume: boolean; magnet: 'off' | 'weak' | 'strong'; stay: boolean;
  comparisons: WorkspaceComparison[]; comparisonMode: 'price' | 'percent'; historyPeriod?: string | undefined;
  /**
   * The id of the named link group this chart is in, one of `sync.groups`.
   * Absent: in no group when the desk declares groups, and in the desk's one
   * group when it declares none, which is how every earlier workspace reads.
   */
  linkGroup?: string;
}
/**
 * The channels one link group links on, named as `LinkOptions` names them, so
 * a group's flags open as a `LinkGroup` without translation. The first four
 * have been written since the first release and stay required; the rest are
 * optional, and absent reads as the engine's default (off, and 'nearest').
 */
export interface WorkspaceLinkChannels {
  crosshair: boolean; viewport: boolean; symbol: boolean; interval: boolean;
  appearance?: boolean;
  /** The chart type (candles, bars, a line) follows. */
  chartType?: boolean;
  /** Drawings are shared between the group's charts on the same instrument. */
  drawings?: boolean;
  /** What a follower does with an instant it has no bar for. */
  whenMissing?: LinkMissingPolicy;
}
/** A named link group: the charts whose `linkGroup` is its id link on its own channels. */
export interface WorkspaceLinkGroup extends WorkspaceLinkChannels {
  /** What each chart's `linkGroup` names: 1 to 100 characters, unique in the workspace. */
  id: string;
  /** What a person called the group: 1 to 120 characters. */
  name: string;
}
/** How the charts of a workspace link to each other. */
export interface WorkspaceSync extends WorkspaceLinkChannels {
  /**
   * Named link groups, up to 16. Absent: the whole desk is one group on the
   * channels above, as every workspace saved before groups is. Present, even
   * empty: each chart is in the group its `linkGroup` names or in none, and
   * each group links on its own channels. The channels above then only tell a
   * reader that predates groups what to apply to the whole desk, so a writer
   * turns one on there only when every chart can follow it together.
   */
  groups?: WorkspaceLinkGroup[];
}
export interface WorkspacePayload {
  layout: { rows: number; columns: number; slots: WorkspaceSlot[]; preset?: string; rowWeights?: number[]; columnWeights?: number[] };
  panes: WorkspacePane[]; activePaneId: string;
  sync: WorkspaceSync;
}
interface DocumentMetadata {
  version: 1; id: string; name: string; createdAt: number; updatedAt: number;
}
export interface WorkspaceDocument extends DocumentMetadata, WorkspacePayload { kind: 'workspace' }
export interface IndicatorTemplatePlotBinding {
  instanceId: string; plotKey: string; paneIndex: number; scaleId: PriceScaleId;
}
/**
 * Pane and scale relationships of a portable template. Pane 0 is always the
 * price pane and the study panes follow in their chart order, whatever slot
 * the price pane held on the chart that was captured: a template applies the
 * same way to a chart that keeps its price pane at the top and to one that
 * keeps it below its studies.
 */
export interface IndicatorTemplateLayout {
  panes: PaneState[]; plots: IndicatorTemplatePlotBinding[]; primaryScaleId?: PriceScaleId;
}
export interface IndicatorTemplatePayload { indicators: IndicatorState[]; layout?: IndicatorTemplateLayout }
export type IndicatorTemplateInput = IndicatorState[] | IndicatorTemplatePayload;
export interface IndicatorTemplateDocument extends DocumentMetadata, IndicatorTemplatePayload { kind: 'indicator-template' }

function metadata(input: Record<string, Json>, kind: WorkspaceKind): DocumentMetadata {
  if (input.kind !== kind || input.version !== WORKSPACE_VERSION) throw new WorkspaceDocumentError(`Unsupported ${kind} kind or version`);
  const createdAt = number(input.createdAt, 'createdAt', 0);
  return { version: WORKSPACE_VERSION, id: string(input.id, 'id', 100), name: string(input.name, 'name', 120),
    createdAt, updatedAt: number(input.updatedAt, 'updatedAt', createdAt) };
}

function priceScaleId(input: Json | undefined, label: string): PriceScaleId {
  if (!isPriceScaleId(input)) throw new WorkspaceDocumentError(`Invalid ${label}`);
  return input;
}

/**
 * `keepPolicy` false drops each study's policy: a portable template is the
 * user's own copy, and a host's restriction must not ride along into it.
 */
function indicatorStates(input: Json | undefined, preserveIdentity = true, keepPolicy = true): IndicatorState[] {
  const ids = new Set<string>();
  return list(input, 'indicators', MAX_STUDIES).map(item => {
    const entry = record(item, 'indicator');
    const settings = record(entry.settings, 'indicator settings');
    const out: IndicatorState = {
      indicatorId: string(entry.indicatorId, 'indicatorId'),
      settings,
      paneIndex: number(entry.paneIndex, 'indicator paneIndex', 0, MAX_PANE_SLOT, true),
    };
    if (entry.studyInputs !== undefined) {
      const keys = list(entry.studyInputs, 'indicator studyInputs', 100000).map(key => {
        if (typeof key !== 'string' || !key.trim()) throw new WorkspaceDocumentError('Invalid study input key');
        const source = record(settings[key], 'study input reference');
        if (source.kind !== 'indicator' || Object.keys(source).length !== 3) {
          throw new WorkspaceDocumentError('Invalid study input reference');
        }
        const instanceId = string(source.instanceId, 'study input instanceId');
        if (typeof source.plotKey !== 'string' || !source.plotKey.trim()) throw new WorkspaceDocumentError('Invalid study input plotKey');
        settings[key] = { kind: 'indicator', instanceId, plotKey: source.plotKey };
        return key;
      });
      if (new Set(keys).size !== keys.length) throw new WorkspaceDocumentError('Duplicate study input key');
      out.studyInputs = keys;
    }
    if (entry.visible !== undefined) out.visible = boolean(entry.visible, 'indicator visibility');
    if (entry.barSource !== undefined) out.barSource = choice(entry.barSource, 'indicator bar source', ['chart', 'underlying'] as const);
    if (keepPolicy && entry.policy !== undefined) {
      let policy: ReturnType<typeof parseIndicatorPolicy>;
      try { policy = parseIndicatorPolicy(entry.policy); }
      catch { throw new WorkspaceDocumentError('Invalid indicator policy'); }
      if (Object.keys(policy).length) out.policy = { ...policy };
    }
    if (entry.priceScaleId !== undefined) {
      out.priceScaleId = priceScaleId(entry.priceScaleId, 'indicator priceScaleId');
    }
    if (entry.plotPriceScaleIds !== undefined) {
      const assignments = record(entry.plotPriceScaleIds, 'indicator plotPriceScaleIds');
      const entries = Object.entries(assignments).map(([key, value]) => [key, priceScaleId(value, 'indicator plot priceScaleId')] as const);
      if (entries.length) out.plotPriceScaleIds = Object.fromEntries(entries);
    }
    if (preserveIdentity && entry.instanceId !== undefined) {
      out.instanceId = string(entry.instanceId, 'indicator instanceId');
      if (ids.has(out.instanceId)) throw new WorkspaceDocumentError('Duplicate indicator instance ID');
      ids.add(out.instanceId);
    }
    return out;
  });
}

/** Keep repeated/custom descriptor IDs; availability is checked by the applying host. */
export function parseIndicatorStates(input: unknown): IndicatorState[] { return indicatorStates(readJson(input)); }

// The template planners import it from here; it is declared in the base.
export { hostOwnedStudy };

/**
 * A scale whose range owner is leaving lets go of the range. An owner the
 * user set by hand leaves the scale as the user had it; otherwise the scale
 * fits again. Internal, shared with the template planner.
 */
export function releaseScaleOwner(scale: PriceScaleState): void {
  const manual = scale.indicatorRange?.manual === true;
  delete scale.indicatorRange; delete scale.fixedRange;
  if (!manual) { scale.autoScale = true; delete scale.range; delete scale.ratioLock; }
}

/**
 * Which entries a portable template keeps. A study its host keeps from the
 * user is the host's, and so is every study that reads its output, since a
 * copy would read nothing. Also returns the ids of the entries left out.
 */
function portableEntries(entries: readonly Json[]): { kept: Json[]; left: Set<string> } {
  const records = entries.map(item => record(item, 'indicator'));
  const out = records.map(entry => {
    if (entry.policy === undefined) return false;
    try { return hostOwnedStudy(parseIndicatorPolicy(entry.policy)); }
    catch { throw new WorkspaceDocumentError('Invalid indicator policy'); }
  });
  const left = new Set<string>();
  const reads = (entry: Record<string, Json>): boolean => {
    const settings = entry.settings, keys = Array.isArray(entry.studyInputs) ? entry.studyInputs : [];
    if (settings === null || typeof settings !== 'object' || Array.isArray(settings)) return false;
    return keys.some(key => {
      const source = typeof key === 'string' ? settings[key] : undefined;
      return source !== null && typeof source === 'object' && !Array.isArray(source)
        && typeof source.instanceId === 'string' && left.has(source.instanceId);
    });
  };
  for (let grew = true; grew;) {
    grew = false;
    records.forEach((entry, index) => {
      if (!out[index] && reads(entry)) out[index] = grew = true;
      if (out[index] && typeof entry.instanceId === 'string' && !left.has(entry.instanceId)) { left.add(entry.instanceId); grew = true; }
    });
  }
  return { kept: entries.filter((_, index) => !out[index]), left };
}

function templateIndicatorStates(input: Json | undefined, requireIdentity = false, left?: Set<string>): IndicatorState[] {
  // A portable template is the user's own copy of the user's own studies.
  const portable = portableEntries(list(input, 'indicators', MAX_STUDIES)), entries = portable.kept;
  for (const id of portable.left) left?.add(id);
  const connected = entries.some(item => {
    const keys = record(item, 'indicator').studyInputs;
    return Array.isArray(keys) && keys.length > 0;
  });
  const states = indicatorStates(entries, connected || requireIdentity, false);
  if (requireIdentity && states.some(state => state.instanceId === undefined)) {
    throw new WorkspaceDocumentError('Template layout requires every indicator instance ID');
  }
  if (!connected) return states;
  const identities = new Map(states.flatMap((state, index) => state.instanceId === undefined ? [] : [[state.instanceId, index] as const]));
  const dependencies = states.map((state, index) => (state.studyInputs ?? []).map(key => {
    const reference = state.settings[key] as { instanceId: string };
    const target = identities.get(reference.instanceId);
    if (target === undefined) throw new WorkspaceDocumentError(`External study dependency: ${reference.instanceId}`);
    if (target === index) throw new WorkspaceDocumentError('A study cannot depend on itself');
    return target;
  }));
  const active = new Set<number>(), complete = new Set<number>();
  // Every index visited is a study's: the loop below, or a target read from `identities`.
  const visit = (index: number): void => {
    if (active.has(index)) throw new WorkspaceDocumentError('Study dependencies contain a cycle');
    if (complete.has(index)) return;
    active.add(index);
    for (const target of dependencies[index]!) visit(target);
    active.delete(index);
    complete.add(index);
  };
  for (let index = 0; index < states.length; index++) visit(index);
  return states;
}

/** Internal shared normalization; only metadata declares portable graph edges. */
export function parseTemplateIndicatorStates(input: unknown): IndicatorState[] {
  return templateIndicatorStates(readJson(input));
}

function chartPanes(input: Json | undefined): PaneState[] {
  return list(input, 'chart panes', MAX_PANE_SLOT + 1).map(item => {
    try {
      const pane = parsePaneState(item);
      // Portable workspaces retain their established numeric limits; the engine
      // can restore larger native states without inheriting a host catalog limit.
      number(pane.weight, 'pane weight', Number.MIN_VALUE);
      for (const scale of [pane.priceScale, ...Object.values(pane.scales ?? {})]) {
        if (!scale) continue;
        number(scale.marginTop, 'marginTop', 0, 1);
        number(scale.marginBottom, 'marginBottom', 0, 1);
        number(scale.minMove, 'minMove', 0);
        if (scale.marginTop + scale.marginBottom >= 1) throw new WorkspaceDocumentError('Price scale margins leave no chart area');
        for (const range of [scale.range, scale.fixedRange]) {
          if (!range) continue;
          number(range.min, 'range.min', -Number.MAX_SAFE_INTEGER);
          number(range.max, 'range.max', range.min);
          if (range.max === range.min) throw new WorkspaceDocumentError('Price scale range must have positive width');
        }
      }
      return pane;
    }
    catch (error) { throw new WorkspaceDocumentError(error instanceof Error ? error.message : 'Invalid pane scale state'); }
  });
}

function templatePayload(input: Json): IndicatorTemplatePayload {
  if (Array.isArray(input)) return { indicators: templateIndicatorStates(input) };
  const source = record(input, 'indicator template payload');
  const left = new Set<string>();
  const indicators = templateIndicatorStates(source.indicators, source.layout !== undefined, left);
  if (source.layout === undefined) return { indicators };
  const layout = record(source.layout, 'indicator template layout');
  const panes = chartPanes(layout.panes);
  if (!panes.length) throw new WorkspaceDocumentError('Template layout needs pane zero');
  const studies = new Map(indicators.map(state => [state.instanceId!, state]));
  for (const study of indicators) {
    if (study.paneIndex >= panes.length) throw new WorkspaceDocumentError('Template indicator pane is missing');
  }
  for (const pane of panes) for (const scale of [pane.priceScale, ...Object.values(pane.scales ?? {})]) {
    // A scale a study left out owned lets go of its range, as it would on a replace.
    const owner = scale?.indicatorRange;
    if (scale && owner && left.has(owner.instanceId)) {
      releaseScaleOwner(scale);
      continue;
    }
    if (scale?.indicatorRange && !studies.has(scale.indicatorRange.instanceId)) {
      throw new WorkspaceDocumentError('Template scale range owner is missing');
    }
  }
  // Called with a binding's pane, range-checked against `panes`, or with pane zero, which exists.
  const requireScale = (paneIndex: number, scaleId: PriceScaleId): void => {
    if (scaleId !== 'right' && !panes[paneIndex]!.scales?.[scaleId]) {
      throw new WorkspaceDocumentError('Template plot or primary scale is missing');
    }
  };
  const bindings = new Map<string, Map<string, PriceScaleId>>();
  const plots = list(layout.plots, 'template plot bindings', 100000).filter(item => {
    const id = record(item, 'template plot binding').instanceId;
    return typeof id !== 'string' || !left.has(id);
  }).map(item => {
    const binding = record(item, 'template plot binding');
    const instanceId = string(binding.instanceId, 'template plot instanceId');
    const study = studies.get(instanceId);
    if (!study) throw new WorkspaceDocumentError('Template plot indicator is missing');
    // Plot keys are descriptor-owned values, including empty or private-looking names.
    if (typeof binding.plotKey !== 'string') throw new WorkspaceDocumentError('Template plot key must be a string');
    const plotKey = binding.plotKey;
    const paneIndex = number(binding.paneIndex, 'template plot paneIndex', 0, panes.length - 1, true);
    if (paneIndex !== 0 && paneIndex !== study.paneIndex) throw new WorkspaceDocumentError('Template plot belongs to another pane');
    const scaleId = priceScaleId(binding.scaleId, 'template plot scaleId');
    requireScale(paneIndex, scaleId);
    const keys = bindings.get(instanceId) ?? new Map<string, PriceScaleId>();
    if (keys.has(plotKey)) throw new WorkspaceDocumentError('Duplicate template plot binding');
    keys.set(plotKey, scaleId);
    bindings.set(instanceId, keys);
    return { instanceId, plotKey, paneIndex, scaleId };
  });
  for (const study of indicators) for (const [key, scaleId] of Object.entries(study.plotPriceScaleIds ?? {})) {
    if (bindings.get(study.instanceId!)?.get(key) !== scaleId) {
      throw new WorkspaceDocumentError('Template plot override needs a matching scale binding');
    }
  }
  const result: IndicatorTemplatePayload = { indicators, layout: { panes, plots } };
  if (layout.primaryScaleId !== undefined) {
    const scaleId = priceScaleId(layout.primaryScaleId, 'template primaryScaleId');
    requireScale(0, scaleId);
    result.layout!.primaryScaleId = scaleId;
  }
  return result;
}

/** Validate and detach portable study settings and optional pane/scale relationships. */
export function parseIndicatorTemplatePayload(input: unknown): IndicatorTemplatePayload {
  return templatePayload(readJson(input));
}

function chartState(input: Json | undefined): WorkspaceChartState {
  const source = record(input, 'chart');
  if (source.version !== 1 && source.version !== 2) throw new WorkspaceDocumentError('Unsupported chart version');
  const out: WorkspaceChartState = { version: source.version === 2 ? 2 : 1 };
  if (source.timezone !== undefined) out.timezone = string(source.timezone, 'timezone', 100);
  for (const key of ['navigation', 'canvas', 'statusLine', 'watermark', 'trading', 'events', 'axisChrome'] as const) {
    if (source[key] !== undefined) Object.assign(out, { [key]: record(source[key], key) });
  }
  if (source.viewport !== undefined) {
    const view = record(source.viewport, 'viewport');
    const from = number(view.from, 'viewport.from', -Number.MAX_SAFE_INTEGER);
    out.viewport = { from, to: number(view.to, 'viewport.to', from) };
  }
  if (source.barSpacing !== undefined) out.barSpacing = number(source.barSpacing, 'barSpacing', Number.MIN_VALUE);
  if (source.grid !== undefined) {
    const grid = record(source.grid, 'grid');
    out.grid = { vertLines: boolean(grid.vertLines, 'vertical grid'), horzLines: boolean(grid.horzLines, 'horizontal grid') };
  }
  if (source.crosshairMode !== undefined) out.crosshairMode = choice(source.crosshairMode, 'crosshairMode', ['normal', 'magnet'] as const);
  if (source.crosshairSnapToBar !== undefined) out.crosshairSnapToBar = boolean(source.crosshairSnapToBar, 'crosshairSnapToBar');
  if (source.priceOnlyAutoScale !== undefined) out.priceOnlyAutoScale = boolean(source.priceOnlyAutoScale, 'priceOnlyAutoScale');
  if (source.indicatorLegendCollapsed !== undefined) out.indicatorLegendCollapsed = boolean(source.indicatorLegendCollapsed, 'indicatorLegendCollapsed');
  if (source.indicators !== undefined) out.indicators = indicatorStates(source.indicators);
  if (source.sourceAbove !== undefined) out.sourceAbove = string(source.sourceAbove, 'sourceAbove');
  if (source.alerts !== undefined) {
    try { out.alerts = parseAlertsDocument(source.alerts); }
    catch (error) { throw new WorkspaceDocumentError(error instanceof Error ? error.message : 'Invalid alert document'); }
  }
  if (source.drawings !== undefined) {
    if (source.drawings === null || typeof source.drawings !== 'object') throw new WorkspaceDocumentError('drawings must be a document or array');
    out.drawings = source.drawings;
  }
  if (source.panes !== undefined) out.panes = chartPanes(source.panes);
  if (source.primaryPane !== undefined) {
    // Only version 2 says where the price pane sits. A version 1 chart that
    // claims a slot would be misread by every reader that trusts the version.
    if (source.version !== 2) throw new WorkspaceDocumentError('A moved price pane needs chart version 2');
    out.primaryPane = number(source.primaryPane, 'primaryPane', 0, MAX_PANE_SLOT, true);
    if (!out.panes || out.primaryPane >= out.panes.length) throw new WorkspaceDocumentError('The price pane slot must name a saved pane');
  }
  if (source.series !== undefined) out.series = list(source.series, 'series descriptors', 512).map(item => {
    const series = record(item, 'series');
    const scaleId = series.priceScaleId;
    if (typeof scaleId !== 'string') throw new WorkspaceDocumentError('priceScaleId must be a string');
    const out = { type: string(series.type, 'series type'), style: record(series.style, 'series style'),
      paneIndex: number(series.paneIndex, 'series paneIndex', 0, MAX_PANE_SLOT, true), priceScaleId: scaleId } as SeriesState;
    if (series.transform !== undefined) out.transform = seriesTransform(series.transform);
    return out;
  });
  return out;
}

/**
 * The transform a chart applies to a series, by shape alone: whether this
 * build registers it, and takes its options, is the applying host's to check,
 * as it is for a study's descriptor.
 */
function seriesTransform(input: Json): SeriesTransformSpec {
  const source = record(input, 'series transform');
  const out: SeriesTransformSpec = { type: string(source.type, 'series transform type', 100) };
  if (source.options === undefined) return out;
  const options = record(source.options, 'series transform options');
  for (const value of Object.values(options)) {
    if (typeof value !== 'string' && (typeof value !== 'number' || !Number.isFinite(value))) {
      throw new WorkspaceDocumentError('Series transform options must be finite numbers or text');
    }
  }
  out.options = options as Record<string, number | string>;
  return out;
}

function paneState(input: Json): WorkspacePane {
  const source = record(input, 'workspace pane');
  const settings = record(source.settings ?? {}, 'settings');
  for (const value of Object.values(settings)) {
    if (!['string', 'number', 'boolean'].includes(typeof value)) throw new WorkspaceDocumentError('Chart settings must be scalar values');
  }
  const comparisons = list(source.comparisons ?? [], 'comparisons', 32).map(item => {
    const entry = record(item, 'comparison');
    const result: WorkspaceComparison = { id: string(entry.id, 'comparison id', 100), symbol: string(entry.symbol, 'comparison symbol'),
      exchange: string(entry.exchange, 'comparison exchange', 200, true), visible: boolean(entry.visible, 'comparison visibility', true) };
    if (entry.color !== undefined) result.color = string(entry.color, 'comparison color', 200);
    return result;
  });
  if (new Set(comparisons.map(item => item.id)).size !== comparisons.length) throw new WorkspaceDocumentError('Duplicate comparison ID');
  const out: WorkspacePane = {
    id: string(source.id, 'pane id', 100), symbol: string(source.symbol, 'symbol'), exchange: string(source.exchange, 'exchange', 200, true),
    interval: string(source.interval, 'interval', 100), chartType: string(source.chartType, 'chartType', 100), chart: chartState(source.chart),
    settings: settings as WorkspaceSettings, volume: boolean(source.volume, 'volume', true),
    magnet: choice(source.magnet, 'magnet', ['off', 'weak', 'strong'], 'off'), stay: boolean(source.stay, 'stay', false),
    comparisons, comparisonMode: choice(source.comparisonMode, 'comparisonMode', ['price', 'percent'], 'percent'),
  };
  if (source.historyPeriod !== undefined) out.historyPeriod = string(source.historyPeriod, 'historyPeriod', 100);
  if (source.variant !== undefined) {
    // A variant this build cannot name would reopen as some other series, so the document is refused.
    let variant: DataVariant | undefined;
    try { variant = normalizeDataVariant(source.variant); }
    catch (error) { throw new WorkspaceDocumentError(error instanceof Error ? error.message : 'Invalid data variant'); }
    if (variant) out.variant = { ...variant };
  }
  if (source.linkGroup !== undefined) out.linkGroup = string(source.linkGroup, 'linkGroup', 100);
  return out;
}

/**
 * One group's channel flags. The four written since the first release default
 * as the engine does; the later ones are kept only when written, so a desk
 * that never mentioned them reads, and writes back, exactly as it was.
 */
function linkChannels(source: Record<string, Json>, label: string): WorkspaceLinkChannels {
  const out: WorkspaceLinkChannels = {
    crosshair: boolean(source.crosshair, `${label}crosshair sync`, true), viewport: boolean(source.viewport, `${label}viewport sync`, true),
    symbol: boolean(source.symbol, `${label}symbol sync`, false), interval: boolean(source.interval, `${label}interval sync`, false),
  };
  for (const key of ['appearance', 'chartType', 'drawings'] as const) {
    if (source[key] !== undefined) out[key] = boolean(source[key], `${label}${key} sync`);
  }
  if (source.whenMissing !== undefined) out.whenMissing = choice(source.whenMissing, `${label}whenMissing`, ['nearest', 'hide'] as const);
  return out;
}

/** Sixteen at most: one per chart is the most a desk of sixteen charts can use. */
function linkGroups(input: Json): WorkspaceLinkGroup[] {
  const ids = new Set<string>();
  return list(input, 'link groups', 16).map(item => {
    const source = record(item, 'link group');
    const id = string(source.id, 'link group id', 100);
    if (ids.has(id)) throw new WorkspaceDocumentError('Duplicate link group ID');
    ids.add(id);
    return { id, name: string(source.name, 'link group name', 120), ...linkChannels(source, 'link group ') };
  });
}

function payload(input: Record<string, Json>): WorkspacePayload {
  const panes = list(input.panes, 'panes', 16).map(paneState);
  if (panes.length === 0) throw new WorkspaceDocumentError('A workspace needs at least one pane');
  const ids = new Set(panes.map(pane => pane.id));
  if (ids.size !== panes.length) throw new WorkspaceDocumentError('Duplicate pane ID');
  const activePaneId = string(input.activePaneId, 'activePaneId', 100);
  if (!ids.has(activePaneId)) throw new WorkspaceDocumentError('Focused pane is missing');
  const grid = record(input.layout, 'layout');
  const rows = number(grid.rows, 'rows', 1, 8, true);
  const columns = number(grid.columns, 'columns', 1, 8, true);
  const seen = new Set<string>();
  const cells = new Set<number>();
  const slots = list(grid.slots, 'layout slots', 16).map(item => {
    const slot = record(item, 'slot');
    const result: WorkspaceSlot = {
      paneId: string(slot.paneId, 'slot paneId', 100), row: number(slot.row, 'row', 0, rows - 1, true),
      column: number(slot.column, 'column', 0, columns - 1, true),
      rowSpan: number(slot.rowSpan ?? 1, 'rowSpan', 1, rows, true), columnSpan: number(slot.columnSpan ?? 1, 'columnSpan', 1, columns, true),
    };
    if (!ids.has(result.paneId) || seen.has(result.paneId)) throw new WorkspaceDocumentError('Invalid or duplicate layout pane ID');
    seen.add(result.paneId);
    if (result.row + result.rowSpan > rows || result.column + result.columnSpan > columns) throw new WorkspaceDocumentError('Layout slot is outside the grid');
    for (let r = result.row; r < result.row + result.rowSpan; r++) for (let c = result.column; c < result.column + result.columnSpan; c++) {
      const cell = r * columns + c;
      if (cells.has(cell)) throw new WorkspaceDocumentError('Layout slots overlap');
      cells.add(cell);
    }
    return result;
  });
  if (seen.size !== panes.length) throw new WorkspaceDocumentError('Every pane needs one layout slot');
  const sync = record(input.sync ?? {}, 'sync');
  const out: WorkspacePayload = { layout: { rows, columns, slots }, panes, activePaneId, sync: linkChannels(sync, '') };
  if (sync.groups !== undefined) out.sync.groups = linkGroups(sync.groups);
  // A chart naming a group nobody declared would silently land in none, or,
  // with no groups at all, in the whole desk's: either links it wrongly.
  const declared = new Set(out.sync.groups?.map(group => group.id));
  for (const pane of panes) {
    if (pane.linkGroup !== undefined && !declared.has(pane.linkGroup)) {
      throw new WorkspaceDocumentError(`Link group ${pane.linkGroup} is not declared`);
    }
  }
  if (grid.preset !== undefined) out.layout.preset = string(grid.preset, 'layout preset', 100);
  for (const [key, count] of [['rowWeights', rows], ['columnWeights', columns]] as const) {
    if (grid[key] === undefined) continue;
    const weights = list(grid[key], key, 8).map(value => number(value, key, Number.MIN_VALUE, 1000));
    if (weights.length !== count) throw new WorkspaceDocumentError(`${key} must match the number of grid tracks`);
    out.layout[key] = weights;
  }
  return out;
}

/** Validate, detach and project a portable chart-only workspace. */
export function parseWorkspaceDocument(input: unknown): WorkspaceDocument {
  const source = record(readJson(input), 'workspace');
  return { kind: 'workspace', ...metadata(source, 'workspace'), ...payload(source) };
}
export function parseWorkspacePayload(input: unknown): WorkspacePayload { return payload(record(readJson(input), 'workspace')); }
export function parseIndicatorTemplate(input: unknown): IndicatorTemplateDocument {
  const source = record(readJson(input), 'indicator template');
  return { kind: 'indicator-template', ...metadata(source, 'indicator-template'), ...templatePayload(source) };
}

/** Explicit migration of the existing single-widget state; no input is modified. */
export function migrateWidgetWorkspace(input: unknown, meta: { id: string; name: string; now: number }): WorkspaceDocument {
  const source = record(readJson(input), 'widget');
  if (source.version !== 1 || source.kind !== undefined) throw new WorkspaceDocumentError('Unsupported widget state');
  const rail = source.rail === null ? {} : record(source.rail ?? {}, 'rail');
  return parseWorkspaceDocument({
    kind: 'workspace', version: 1, id: meta.id, name: meta.name, createdAt: meta.now, updatedAt: meta.now,
    panes: [{ id: 'p0', symbol: source.symbol, exchange: source.exchange ?? '', interval: source.interval,
      chartType: source.chartType, chart: source.chart, magnet: rail.magnet ?? 'off', stay: rail.stay ?? false,
      ...(source.variant === undefined ? {} : { variant: source.variant }),
      settings: { 'widget.theme': choice(source.theme, 'theme', ['light', 'dark'], 'dark') } }],
    layout: { rows: 1, columns: 1, slots: [{ paneId: 'p0', row: 0, column: 0, rowSpan: 1, columnSpan: 1 }] }, activePaneId: 'p0',
  });
}
