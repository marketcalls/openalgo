/**
 * The chart history's captures and what differs between two of them
 * (history.ts): the snapshot a step holds of the chart, the field-by-field
 * diff that scopes what a press writes, and the entries the timeline keeps.
 * Pure and stateless, like the value helpers in history-values.ts, so they
 * live apart from the class that records and walks the steps.
 *
 * The two public types the model names, `ChartHistoryChange` and
 * `ChartHistoryCommand`, are declared here so this module reads nothing back
 * from history.ts; history.ts re-exports them, and the tier entry takes them
 * from there as before.
 */
import type {
  ChartSettingsValues, IndicatorPolicy, IndicatorSettings, PriceAxisSide, PriceScaleId, PriceScaleMode, PriceScaleOptions,
} from 'openalgo-charts';
import type { Drawing, DrawingsDocument } from 'openalgo-charts/draw';
import { same } from './history-values';

/** What a step changes, for a label or a test. */
export type ChartHistoryChange =
  | 'study-add' | 'study-remove' | 'study-settings' | 'study-visibility' | 'study-scale' | 'study-pane' | 'study-order'
  | 'chart-type' | 'series-scale' | 'pane-add' | 'pane-remove' | 'pane-order' | 'pane-weight' | 'pane-collapse' | 'axis'
  | 'settings' | 'drawing' | 'command';

/**
 * A host's own reversible step, for a change the history cannot observe or
 * make itself: a host that rebuilds its chart to switch the chart type. A
 * return of exactly `false`, or a throw, is a failure.
 */
export interface ChartHistoryCommand {
  label?: string | undefined;
  undo(): unknown;
  redo(): unknown;
}

export interface StudyShot {
  /** The history's name for the study (see `_nameOf`): its id, unless another study held that id first. */
  id: string;
  indicatorId: string;
  settings: IndicatorSettings;
  pane: number;
  visible: boolean;
  scale: PriceScaleId | null;
  plots: Record<string, PriceScaleId>;
}

/**
 * The chart-wide price scale defaults a pane added later starts from
 * (`chart.priceScaleDefaults()`), in the fields that describe the axis. They
 * move only with a chart-wide write, never with one axis changed from its own
 * menu, so they are captured apart from every pane's own scales.
 */
type ScaleDefaults = Partial<Pick<PriceScaleOptions, 'mode' | 'inverted' | 'marginTop' | 'marginBottom'>>;
export const DEFAULT_KEYS = ['mode', 'inverted', 'marginTop', 'marginBottom'] as const;

/**
 * Chart settings that read the price pane's own scale but write every pane's
 * and the defaults. The defaults and the axes carry each of them, so as
 * settings they are never compared: replayed after a change made to one axis
 * from its own menu, they would move every other pane's scale and the
 * defaults too.
 */
const BROAD = new Set(['scales.mode', 'scales.inverted', 'scales.autoScale']);

export interface AxisShot {
  side: PriceAxisSide;
  order: number;
  mode: PriceScaleMode;
  inverted: boolean;
  marginTop: number;
  marginBottom: number;
  // Only in a full capture: a pan, a zoom or an axis drag changes both, and
  // those are views of the chart rather than edits to it.
  auto?: boolean | undefined;
  lock?: boolean | undefined;
}

/**
 * `series` counts every series in the pane, a study's plots and a host's own
 * alike. A pane with none keeps the range its scales last had, and that range
 * is all that places its drawings, so it is held in `ranges` to make such a
 * pane again; it is a view, never compared. `host` marks a pane the host
 * made (for a primitive of its own, or a drawing placed there): like one
 * holding the host's series, history never makes or removes it.
 */
export interface PaneShot {
  key: number; weight: number; collapsed: boolean; series: number; axes: Record<string, AxisShot>;
  ranges?: Record<string, { min: number; max: number }>;
  host?: boolean;
}

export interface Shot {
  full: boolean;
  type: string | null;
  scale: PriceScaleId | null;
  studies: StudyShot[];
  panes: PaneShot[];
  defaults: ScaleDefaults;
  settings?: ChartSettingsValues | undefined;
}

/**
 * What differs between two captures, field by field: the scope a step
 * reaches. A step writes these fields and no others, so a change the host
 * made to a neighbouring field since is still there after an undo.
 */
export interface Delta {
  type: boolean;
  scale: boolean;
  settings: string[];
  defaults: (keyof ScaleDefaults)[];
  studies: Map<string, StudyDelta>;
  kinds: Set<ChartHistoryChange>;
  order: boolean;
  paneOrder: boolean;
  panes: Map<number, PaneDelta>;
  /** Panes only the second capture has, and panes only the first has: what a step makes and removes. */
  born: number[];
  gone: number[];
}

/** A study present on one side only is `presence`; otherwise the fields that differ. */
export interface StudyDelta { presence: boolean; keys: string[]; visible: boolean; scale: boolean; pane: boolean }
interface PaneDelta { weight: boolean; collapsed: boolean; axes: Map<string, (keyof AxisShot)[]> }

/** A drawing a removed pane took with it, and the pane it goes back on. */
export interface Orphan { pane: number; drawing: Drawing }

/**
 * A drawing step, by the number its controller holds it under, with the
 * drawings either side of it. A host that rebuilds its chart replaces the
 * controller, and the new one holds none of the old steps; such a step is
 * `detached` and is taken back from the two documents instead.
 */
export interface Step { id: number; before: DrawingsDocument; after: DrawingsDocument; detached: boolean }

export interface Part {
  label?: string | undefined;
  before?: Shot;
  after?: Shot;
  steps?: Step[];
  commands?: ChartHistoryCommand[];
  orphans?: Orphan[];
  linked?: boolean;
}

/** A transaction in progress: what it began from (again after an `ignore` inside it), and what it holds so far. */
export interface Tx { label?: string | undefined; before: Shot; steps: Step[]; commands: ChartHistoryCommand[] }

/** A group in progress; `redo` and `shifted` are what its entry took away, for a group that ends as no step. */
export interface Group { entry: Entry | null; label?: string | undefined; depth: number; redo?: Entry[]; shifted?: Entry }

/**
 * One stretch of chart changes. `epoch` names the baseline its `before` was
 * measured from: changes on one baseline merge into one stretch, and one a
 * host's own change interrupted starts another, so taking the step back never
 * takes the host's change with it.
 */
interface Stretch { before: Shot; after: Shot; epoch: number }

export interface Entry {
  label?: string | undefined;
  changes: Stretch[];
  steps: Step[];
  commands: ChartHistoryCommand[];
  orphans: Orphan[];
  /**
   * The step announced an appearance change (`style:change`), which linked
   * charts follow; taking it back or applying it again announces the result.
   */
  linked?: boolean;
}

// `layout:change` follows the setters that change a pane's weight or a
// scale's options without an event of their own; a capture reads the weights
// and the axes, so a change made through them outside a transaction is a step
// too. What else it announces (a chart setting, auto-fit) is read only in a
// transaction's full capture, and an observed one finds nothing there.
export const OBSERVED = ['objects:change', 'indicatorRemoved', 'paneAdded', 'paneRemoved', 'paneMoved', 'paneCollapsed',
  'paneResized', 'priceAxisMoved', 'priceAxisPlacementChanged', 'layout:change'] as const;

/**
 * What the chart lets a step do, read against the chart the stretch starts
 * from. A study's policy is its host's, and no undo or redo overrides it: a
 * step leaves a protected study as the policy keeps it and does the rest of
 * what it records, the way the drawing history leaves a read-only drawing.
 */
export interface Rules {
  /** The policy the host holds now for the study a step names, on the chart or not. */
  policy(id: string): Readonly<IndicatorPolicy>;
  /** Whether the study is on the chart the stretch starts from. */
  present(id: string): boolean;
  /** Whether a step may bring the study back: not one its host took away, nor one it keeps from the user's remove. */
  returns(id: string): boolean;
  /** Whether putting one pane's stack into the order `to` records changes it, without two studies that may not move trading places. */
  order(to: Shot, pane: number): boolean;
}

/**
 * Captures compared on what both hold: settings and the view-driven axis
 * fields only in full ones. With `rules`, what the chart would refuse, and
 * what the chart the stretch starts from leaves nothing to do for, is left
 * out: the delta is then what a press can still do.
 */
export function diff(a: Shot, b: Shot, rules?: Rules): Delta {
  const d: Delta = {
    type: false, scale: false, settings: [], defaults: [], studies: new Map(), kinds: new Set(), order: false, paneOrder: false,
    panes: new Map(), born: [], gone: [],
  };
  if (a.type !== b.type) { d.type = true; d.kinds.add('chart-type'); }
  if (a.scale !== b.scale) { d.scale = true; d.kinds.add('series-scale'); }
  if (a.settings && b.settings) {
    for (const key of new Set([...Object.keys(a.settings), ...Object.keys(b.settings)])) {
      if (!BROAD.has(key) && key in a.settings && key in b.settings && !same(a.settings[key], b.settings[key])) d.settings.push(key);
    }
  }
  d.defaults = DEFAULT_KEYS.filter(key => !same(a.defaults[key], b.defaults[key]));
  if (d.settings.length || d.defaults.length) d.kinds.add('settings');
  const left = new Map(a.studies.map(s => [s.id, s]));
  const right = new Map(b.studies.map(s => [s.id, s]));
  const whole: StudyDelta = { presence: true, keys: [], visible: true, scale: true, pane: true };
  for (const [id, s] of left) {
    // Gone from the chart the stretch starts from: nothing of it is there to take away or change.
    if (rules !== undefined && !rules.present(id)) continue;
    const t = right.get(id);
    const policy = rules?.policy(id) ?? {};
    if (t === undefined) {
      if (policy.removable !== false) { d.studies.set(id, whole); d.kinds.add('study-remove'); }
      continue;
    }
    const keys = policy.configurable === false ? []
      : [...new Set([...Object.keys(s.settings), ...Object.keys(t.settings)])].filter(key => !same(s.settings[key], t.settings[key]));
    const sd: StudyDelta = {
      presence: false, keys, visible: s.visible !== t.visible,
      scale: policy.configurable !== false && (s.scale !== t.scale || !same(s.plots, t.plots)),
      pane: policy.movable !== false && s.pane !== t.pane,
    };
    if (keys.length) d.kinds.add('study-settings');
    if (sd.visible) d.kinds.add('study-visibility');
    if (sd.scale) d.kinds.add('study-scale');
    if (sd.pane) d.kinds.add('study-pane');
    if (keys.length || sd.visible || sd.scale || sd.pane) d.studies.set(id, sd);
  }
  for (const id of right.keys()) {
    if (left.has(id)) continue;
    // One on the chart already has nothing to come back as; one the host took
    // away, or keeps from the user's remove, only the host brings back.
    if (rules !== undefined && (rules.present(id) || !rules.returns(id))) continue;
    d.studies.set(id, whole);
    d.kinds.add('study-add');
  }
  // Stacking is per pane: the order of the studies both captures share, pane by pane.
  const stack = (shot: Shot, pane: number): string[] => shot.studies.filter(s => s.pane === pane && left.has(s.id) && right.has(s.id)).map(s => s.id);
  for (const pane of new Set(b.studies.map(s => s.pane))) {
    if (!same(stack(a, pane), stack(b, pane)) && (rules === undefined || rules.order(b, pane))) d.order = true;
  }
  if (d.order) d.kinds.add('study-order');
  const before = new Map(a.panes.map(p => [p.key, p]));
  const after = new Set(b.panes.map(p => p.key));
  // A pane a study brought or took is that study's change. One that came or
  // went on its own is a step of its own, unless it holds a series or the
  // host made it: that is the host's, which history never makes or removes.
  const carried = (p: PaneShot, shot: Shot): boolean => shot.studies.some(s => s.pane === p.key && d.studies.has(s.id));
  const own = (p: PaneShot, shot: Shot): boolean => carried(p, shot) || (p.series === 0 && p.host !== true);
  d.gone = a.panes.filter(p => !after.has(p.key) && own(p, a)).map(p => p.key);
  d.born = b.panes.filter(p => !before.has(p.key) && own(p, b)).map(p => p.key);
  if (a.panes.some(p => d.gone.includes(p.key) && !carried(p, a))) d.kinds.add('pane-remove');
  if (b.panes.some(p => d.born.includes(p.key) && !carried(p, b))) d.kinds.add('pane-add');
  const shared = b.panes.filter(p => before.has(p.key));
  const was = a.panes.filter(p => shared.some(q => q.key === p.key)).map(p => p.key);
  if (!same(was, shared.map(p => p.key))) { d.paneOrder = true; d.kinds.add('pane-order'); }
  for (const p of shared) {
    const q = before.get(p.key)!;
    const pd: PaneDelta = { weight: !same(p.weight, q.weight), collapsed: p.collapsed !== q.collapsed, axes: new Map() };
    if (pd.weight) d.kinds.add('pane-weight');
    if (pd.collapsed) d.kinds.add('pane-collapse');
    for (const [id, axis] of Object.entries(p.axes)) {
      const other = q.axes[id];
      if (other === undefined) continue;
      const fields = (Object.keys(axis) as (keyof AxisShot)[]).filter(field => field in other && !same(axis[field], other[field]));
      if (fields.length) { pd.axes.set(id, fields); d.kinds.add('axis'); }
    }
    if (pd.weight || pd.collapsed || pd.axes.size) d.panes.set(p.key, pd);
  }
  return d;
}

export const empty = (d: Delta): boolean => d.kinds.size === 0;

/** The change that walking a step the other way makes. The rest read the same both ways. */
export const REVERSED: Partial<Record<ChartHistoryChange, ChartHistoryChange>> = {
  'study-add': 'study-remove', 'study-remove': 'study-add', 'pane-add': 'pane-remove', 'pane-remove': 'pane-add',
};

/** One stretch of a step as a press walks it. */
export interface Move { from: Shot; to: Shot; delta: Delta }

/**
 * The chart a stretch starts from, as far as the rules read it: the studies
 * on it by name, in the chart's stacking order, and the pane key each is on.
 * A press walks a step's stretches one after another, so each is read
 * against the chart the one before it leaves, never the chart before the press.
 */
export interface View { order: string[]; pane: Map<string, number> }

/**
 * A study the steps name on a chart the history no longer follows: the id it
 * had and the policy its host last gave it. The study object itself would keep
 * that chart, and everything the study computed, alive for as long as a step
 * names it.
 */
export interface Former { readonly id: string; policy(): Readonly<IndicatorPolicy> }

export function former(study: Former): Former {
  const id = study.id, policy = { ...study.policy() };
  return { id, policy: () => policy };
}

class HistoryFailure extends Error {}
export const fail: (why: string) => never = (why) => { throw new HistoryFailure(why); };

/** The panes of a partial capture with the view fields a full one adds, pane by pane and scale by scale. */
export function fill(panes: readonly PaneShot[], full: readonly PaneShot[]): PaneShot[] {
  return panes.map(p => {
    const other = full.find(q => q.key === p.key);
    if (other === undefined) return p;
    const axes: Record<string, AxisShot> = {};
    for (const [id, axis] of Object.entries(p.axes)) {
      const more = other.axes[id];
      axes[id] = more === undefined ? axis : { ...axis, auto: more.auto, lock: more.lock };
    }
    return { ...p, axes };
  });
}
