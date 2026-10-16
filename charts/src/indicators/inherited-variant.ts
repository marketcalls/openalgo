import { normalizeDataVariant, type ChartDataContext, type DataVariant } from 'openalgo-charts';

/**
 * Whether the chart's context is the one `publishDataContext` passes through
 * on a variant-only change, which the real one replaces at once. The same
 * registered symbol the base tier marks it with (see data-variant.ts), read
 * here because this tier is bundled apart from that module.
 */
export const passingContext = (context: Readonly<ChartDataContext> | undefined): boolean =>
  (context as Record<symbol, unknown> | undefined)?.[Symbol.for('openalgo-charts.data-context.passing')] === true;

/**
 * The part of a chart's data variant that a request for another instrument
 * inherits: the session and the adjustment, which say how bars are observed,
 * so a benchmark or a comparison lines up with the chart bar for bar. The
 * currency and the unit belong to the instrument that was asked for, so they
 * stay behind. Undefined when nothing is inherited. Throws a TypeError for a
 * malformed variant, like `normalizeDataVariant`.
 */
export function inheritedDataVariant(variant?: DataVariant): Readonly<DataVariant> | undefined {
  const v = normalizeDataVariant(variant);
  return normalizeDataVariant(v && { session: v.session, adjustment: v.adjustment });
}
