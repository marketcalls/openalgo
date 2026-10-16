/**
 * Serialisable chart state: the keystone the persistence-shaped features hang
 * off (saved layouts, templates, an objects panel, favourites, drawings).
 *
 * The rule that shapes this type: **the chart serialises what the chart owns.**
 * Series *data* is the application's (it knows the symbol, the timeframe, and
 * the feed), so `restoreState` never recreates series. It restores the things
 * the chart is the source of truth for (viewport, grid, panes, price scales,
 * indicators) and reports the series it saw so an app can rebuild them itself
 * and re-apply their styling.
 */
import type { SeriesStyle } from '../render/series-style';
import type { PriceScaleId } from './series';
import type { IndicatorSettings } from './indicator-registry';
import { PRICE_SCALE_MODES, type PriceScaleMode } from '../scale/price-scale';
import type { AlertsDocument } from '../alerts/types';
import { isPriceScaleId, type PriceAxisPlacement } from './price-axis-layout';
import type { IndicatorPolicy } from './indicator-policy';
import type { SeriesTransformSpec } from './series-transform';
import type { IndicatorBarSource } from './indicator-bar-source';
import { hasOnlyDataProperties, isPlainObject } from '../helpers/validate';

/**
 * The newest state version this build reads and writes. Bumped when the shape
 * changes incompatibly; `restoreState` ignores unknown versions.
 *
 * Version 2 adds `primaryPane`. `getState` writes it only for a chart whose
 * price pane has moved from the top, and writes every other state as version
 * 1, unchanged, so a reader from before the move still opens it. A reader
 * that predates version 2 refuses a moved layout instead of laying the price
 * pane's scales, studies and drawings onto the study pane in slot 0.
 */
export const CHART_STATE_VERSION = 2;

export interface PriceScaleState {
  marginTop: number;
  marginBottom: number;
  minMove: number;
  /** Optional in older snapshots, which used the current scale's precision floor. */
  minPrecision?: number;
  mode: PriceScaleMode;
  inverted: boolean;
  /** False when the user (or an indicator's fixed range) pinned the scale. */
  autoScale: boolean;
  /** The pinned range, present only when `autoScale` is false. */
  range?: { min: number; max: number };
  /** The declared auto-fit band, independent of a temporary manual range. */
  fixedRange?: { min: number; max: number } | null;
  /** Study default ownership; manual records a host view override without losing the default. */
  indicatorRange?: { instanceId: string; manual: boolean };
  /** Geometry paired with the saved range, so reopening at another size preserves its proportion. */
  ratioLock?: { barSpacing: number; height: number };
  /** Independent axis side and order. Omission restores the scale identity's default placement. */
  placement?: PriceAxisPlacement;
}

export interface PaneState {
  /** Relative height weight among panes. */
  weight: number;
  priceScale: PriceScaleState;
  /** Secondary scales only; the right scale remains in priceScale for older readers. */
  scales?: Partial<Record<PriceScaleId, PriceScaleState>>;
  /**
   * Folded to its header strip. Omission restores the pane open; the primary
   * price pane (see `ChartState.primaryPane`) is always open, whatever it says.
   */
  collapsed?: boolean;
}

function stateRecord(input: unknown): Record<string, unknown> {
  if (!isPlainObject(input)) throw new Error('Invalid pane scale object');
  if (!hasOnlyDataProperties(input)) throw new Error('Pane scale accessors are not supported');
  return input;
}

function stateNumber(value: unknown, label: string, min = -Number.MAX_VALUE, max = Number.MAX_VALUE): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error(`Invalid ${label}`);
  return value;
}

function stateRange(input: unknown): { min: number; max: number } {
  const value = stateRecord(input);
  const min = stateNumber(value.min, 'scale range minimum');
  const max = stateNumber(value.max, 'scale range maximum', min);
  return { min, max };
}

function scaleState(input: unknown, legacy: boolean): PriceScaleState {
  const value = stateRecord(input);
  const field = (key: string, fallback: unknown): unknown => value[key] === undefined && legacy ? fallback : value[key];
  const mode = field('mode', 'linear');
  const inverted = field('inverted', false), autoScale = field('autoScale', true);
  if (!PRICE_SCALE_MODES.includes(mode as PriceScaleMode)
    || typeof inverted !== 'boolean' || typeof autoScale !== 'boolean') throw new Error('Invalid price scale mode or flags');
  const result: PriceScaleState = {
    marginTop: stateNumber(field('marginTop', 0.1), 'top scale margin'),
    marginBottom: stateNumber(field('marginBottom', 0.1), 'bottom scale margin'),
    minMove: stateNumber(field('minMove', 0), 'scale tick', 0), mode: mode as PriceScaleMode, inverted, autoScale,
  };
  if (value.minPrecision !== undefined) {
    result.minPrecision = stateNumber(value.minPrecision, 'scale precision', 0, 100);
    if (!Number.isInteger(result.minPrecision)) throw new Error('Scale precision must be an integer');
  }
  if (value.range !== undefined) result.range = stateRange(value.range);
  if (value.fixedRange !== undefined) result.fixedRange = value.fixedRange === null ? null : stateRange(value.fixedRange);
  if (value.indicatorRange !== undefined) {
    const owner = stateRecord(value.indicatorRange);
    if (typeof owner.instanceId !== 'string' || !owner.instanceId.trim() || typeof owner.manual !== 'boolean' || !result.fixedRange) {
      throw new Error('Invalid indicator range ownership');
    }
    result.indicatorRange = { instanceId: owner.instanceId, manual: owner.manual };
  }
  if (value.ratioLock !== undefined) {
    const lock = stateRecord(value.ratioLock);
    if (autoScale || !result.range) throw new Error('A scale ratio lock requires a manual range');
    result.ratioLock = { barSpacing: stateNumber(lock.barSpacing, 'ratio bar spacing', Number.MIN_VALUE),
      height: stateNumber(lock.height, 'ratio height', Number.MIN_VALUE) };
  }
  if (value.placement !== undefined) {
    const placement = stateRecord(value.placement);
    if (!Object.prototype.hasOwnProperty.call(placement, 'side') || !Object.prototype.hasOwnProperty.call(placement, 'order')
      || !['left', 'right', 'hidden'].includes(placement.side as string)
      || typeof placement.order !== 'number' || !Number.isSafeInteger(placement.order) || placement.order < 0) {
      throw new Error('Invalid price axis placement side or order');
    }
    result.placement = { side: placement.side as PriceAxisPlacement['side'], order: placement.order };
  }
  return result;
}

/** Validate and detach a pane snapshot before either a chart or workspace accepts it. */
export function parsePaneState(input: unknown, allowLegacyPartial = false): PaneState {
  const value = stateRecord(input);
  const result: PaneState = { weight: stateNumber(value.weight, 'pane weight', Number.MIN_VALUE),
    priceScale: scaleState(value.priceScale, allowLegacyPartial) };
  if (value.scales !== undefined) {
    const scales = stateRecord(value.scales);
    result.scales = {};
    for (const [id, state] of Object.entries(scales)) {
      // The right scale is the pane's own `priceScale`, saved above, never a secondary one.
      if (!isPriceScaleId(id) || id === 'right') throw new Error('Invalid secondary price scale id');
      result.scales[id as PriceScaleId] = scaleState(state, false);
    }
  }
  if (value.collapsed !== undefined) {
    if (typeof value.collapsed !== 'boolean') throw new Error('Invalid pane collapse flag');
    result.collapsed = value.collapsed;
  }
  return result;
}

/** A series descriptor: enough to rebuild the shell, never the data. */
export interface SeriesState {
  type: string;
  style: SeriesStyle;
  paneIndex: number;
  priceScaleId: PriceScaleId;
  /**
   * The transform the chart applies to the series (`Chart.setSeriesTransform`),
   * written only for a series that has one, so every other series saves what it
   * always did. Like the rest of this descriptor it is the host's to reapply.
   */
  transform?: SeriesTransformSpec;
}

export interface IndicatorState {
  indicatorId: string;
  /** Stable workspace identity. Dependency templates remap it when copied. */
  instanceId?: string;
  /** Settings keys carrying declared study references, for portable template remapping. */
  studyInputs?: readonly string[];
  /** Whole-study scale override. Omission retains the descriptor's plot assignments. */
  priceScaleId?: PriceScaleId;
  /** Explicit plot assignments, including plots drawn on the price pane. */
  plotPriceScaleIds?: Readonly<Record<string, PriceScaleId>>;
  settings: IndicatorSettings;
  paneIndex: number;
  /** Omitted by older layouts, which restore the indicator as visible. */
  visible?: boolean;
  /**
   * The restrictions its host set, written only when a flag is false, so an
   * unrestricted study saves exactly what it always did. Omission restores it
   * unrestricted.
   */
  policy?: IndicatorPolicy;
  /**
   * `'underlying'` for a study computing on the bars under a transformed chart,
   * written only then, so a study on the chart's bars saves what it always did.
   * Omission restores it on the chart's bars.
   */
  barSource?: IndicatorBarSource;
}

export interface ChartState {
  version: number;
  /** Visible logical range at save time. */
  viewport?: { from: number; to: number } | undefined;
  barSpacing?: number | undefined;
  grid?: { vertLines: boolean; horzLines: boolean };
  crosshairMode?: 'normal' | 'magnet';
  crosshairSnapToBar?: boolean;
  /** Only the primary series contributes to its scale's auto-fit. Omission preserves the current preference. */
  priceOnlyAutoScale?: boolean;
  /** Collapse only study legend rows. Omission preserves the current preference. */
  indicatorLegendCollapsed?: boolean;
  panes?: PaneState[] | undefined;
  /**
   * Slot in `panes` of the primary price pane, present only when it is not the
   * first (version 2). Every `paneIndex` in the state, of a pane, a series, a
   * study or a drawing, is a visual slot counted from the top, so this says
   * which of them is the price pane. Omitted with `panes` present means slot
   * 0, the only place a price pane could be before it could move. Needs
   * `panes`, and must name one of them.
   */
  primaryPane?: number;
  /** Informational: `restoreState` does not recreate these (it has no data). */
  series?: SeriesState[];
  indicators?: IndicatorState[];
  /**
   * Instance id of the study the price source paints directly above, present
   * only when the source was moved over a study on its pane. Omission, as in
   * every layout from before the source could move, paints the source behind
   * the studies. Read with `indicators`: a restore without them leaves it be.
   */
  sourceAbove?: string;
  /**
   * Opaque slot the drawing tier fills. The base engine round-trips it
   * untouched, so an app that persists state keeps drawings for free once the
   * tier is loaded.
   */
  drawings?: unknown;
  alerts?: AlertsDocument | undefined;
}

/** Runtime choices for restoring configuration without serializing callbacks. */
export interface ChartRestoreOptions {
  /**
   * Keep the current formatter callback or default formatter on selected live
   * scales while recreating study series. Numeric saved scale settings still
   * apply. Selectors must name existing panes/scales; no callbacks are serialized.
   */
  preserveScaleFormats?: readonly { paneIndex: number; scaleId: PriceScaleId }[];
}

/** What `restoreState` actually applied, so a caller can finish the job. */
export interface RestoreReport {
  /** True when the payload was a recognised, applicable state object. */
  applied: boolean;
  /** Series descriptors found in the state: the app rebuilds these itself. */
  series: SeriesState[];
  /** Indicator instances recreated. */
  indicators: number;
  /** Set when the payload was rejected. */
  reason?: string;
}
