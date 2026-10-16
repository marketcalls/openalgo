/**
 * Series transforms the chart applies itself (ARCHITECTURE.md §6A, Family B).
 *
 * A price-driven chart type (Heikin Ashi, Renko, range bars, line break,
 * point and figure, Kagi) draws elements derived from the host's bars rather
 * than the bars themselves. Before 2.6.0 a host ran the transform and handed
 * the chart the result; a series given a transform here takes the host's bars
 * as they are, runs the transform, and draws its elements, tick by tick.
 *
 * The transforms themselves live in the lazy transform tier, which registers
 * them here on import, so a chart that never draws one never loads one. The
 * base holds only this registry and the shapes it names. A series with no
 * transform is exactly what it always was: nothing here runs for it, which is
 * why a host that still prepares its own elements is never transformed twice.
 */
import type { Bar } from './bar';
import type { SeriesType } from './chart-type-registry';
import type { IndicatorInput } from './indicator-registry';

/**
 * A transform choice: which one, and the options it was given. JSON-safe, so
 * saved state carries it as it is.
 */
export interface SeriesTransformSpec {
  /** A registered transform: `heikin-ashi`, `renko`, `range-bars`, `line-break`, `point-figure` or `kagi` once the transform tier is imported. */
  type: string;
  /**
   * The options the transform declares (`SeriesTransformDefinition.inputs`),
   * by the names its class takes: `boxSize`, `range`, `lines`, `reversal`.
   * An omitted option takes its default, and a size left at 0 is taken from
   * the history loaded with each `setData`.
   */
  options?: Readonly<Record<string, number | string>>;
}

/**
 * One transformed series, as the chart drives it: the host's bars in, the
 * elements it draws out. The newest source bar is the forming one, so the
 * elements it produced are provisional and a tick replaces them; no state is
 * ever committed from it (CLAUDE.md, never cache the forming bar).
 */
export interface SeriesTransformRun {
  /** Replace the source history: a load, or a new symbol. Sizes left automatic are resolved from it. */
  setData(bars: readonly Bar[]): void;
  /** Merge older bars in at the left edge, keeping the resolved sizes. */
  prepend(bars: readonly Bar[]): void;
  /**
   * Apply one source bar: the forming bar again, a newer bar, or a correction
   * of an older one. Returns the index of the first element that may differ
   * from before, so the chart writes the tail alone.
   */
  update(bar: Bar): number;
  /** The source bars, oldest first. Read-only: the run keeps it. */
  source(): readonly Bar[];
  /** The elements, oldest first, with strictly increasing times. Read-only. */
  elements(): readonly Bar[];
  /**
   * The source bar each element was completed on, the newest bar for an
   * element still forming; null when each source bar is one element at its
   * own time (Heikin Ashi).
   */
  sourceIndex(): readonly number[] | null;
}

/** What the transform tier registers for one transform. */
export interface SeriesTransformDefinition {
  /** Display name, for a settings group or a menu. */
  name: string;
  /** The renderer its elements draw with. */
  renderer: SeriesType;
  /**
   * The options it takes, described the way a study describes its inputs, so
   * `create` checks a spec against them and a settings dialog renders
   * them. Only `number` and `select` inputs are used.
   */
  inputs: readonly IndicatorInput[];
  /**
   * Build a run. Throws a `TypeError` naming an option the transform does not
   * take or a value outside what its input allows, before anything is built:
   * how a host checks a spec from outside (a saved layout).
   */
  create(options: Readonly<Record<string, number | string>>): SeriesTransformRun;
}

const registry = new Map<string, SeriesTransformDefinition>();

/** Add a transform to the registry; `registerSeriesTransform` (chart-series-transform.ts) is the public door. */
export function addSeriesTransform(type: string, definition: SeriesTransformDefinition): void {
  registry.set(type, definition);
}

export function getSeriesTransform(type: string): SeriesTransformDefinition {
  const definition = registry.get(type);
  if (definition === undefined) {
    throw new Error(`openalgo-charts: unknown series transform "${type}"; import 'openalgo-charts/transform' first`);
  }
  return definition;
}

export function registeredSeriesTransforms(): string[] {
  return Array.from(registry.keys());
}

