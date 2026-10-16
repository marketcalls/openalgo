/**
 * Data variants: which of a provider's series for one instrument a chart shows.
 *
 * Regular and extended session, adjusted and raw prices, and a quote currency
 * or unit are each a different series from the provider, not a view of one
 * series. Extended hours add bars that the regular series does not have, and
 * an adjusted history rewrites every price before a corporate action. So a
 * variant is identity, like the symbol: it is part of every request, every
 * cache key and every saved chart, and a change of variant is a change of
 * source.
 *
 * Nothing here converts, adjusts or filters bars. A variant is served by the
 * provider that declares it (`DataFeed.dataVariants`) or it is unsupported;
 * there is no local fallback, because a series derived here would look exactly
 * like the provider's own and be wrong in ways nobody could see.
 */
import type { ChartDataContext } from '../model/indicator-registry';

/** Regular trading hours only, or with the provider's pre and post market sessions. */
export type DataSession = 'regular' | 'extended';
/** Prices adjusted by the provider for corporate actions, or as traded. */
export type DataAdjustment = 'adjusted' | 'raw';
/** One field of a variant, as a snapshot or an error names it. */
export type DataVariantDimension = 'session' | 'adjustment' | 'currency' | 'unit';

/**
 * A provider series for one instrument. An absent field is the provider's
 * default for it, which is itself an identity: `{}` asks for exactly what a
 * request without a variant always got, and `{ session: 'regular' }` asks for
 * regular hours explicitly, whatever the provider's default is.
 */
export interface DataVariant {
  session?: DataSession;
  adjustment?: DataAdjustment;
  /** The currency the provider quotes the series in, as it names it (`'USD'`). Compared exactly. */
  currency?: string;
  /** The unit the provider quotes the series in, as it names it (`'per lot'`). Compared exactly. */
  unit?: string;
}

/**
 * What a provider can serve for one instrument and interval. A dimension that
 * is absent or empty serves only the provider's default, so a variant must
 * leave it out.
 */
export interface DataVariantCapabilities {
  sessions?: readonly DataSession[];
  adjustments?: readonly DataAdjustment[];
  currencies?: readonly string[];
  units?: readonly string[];
}

/** What `DataFeed.dataVariants` is asked about. */
export interface DataVariantQuery {
  symbol: string;
  exchange: string;
  interval: string;
  signal?: AbortSignal;
}

const DIMENSIONS: readonly DataVariantDimension[] = ['session', 'adjustment', 'currency', 'unit'];
/** The closed choices; a currency and a unit are the provider's own names. */
const CHOICES: Partial<Record<DataVariantDimension, readonly string[]>> = { session: ['regular', 'extended'], adjustment: ['adjusted', 'raw'] };

/**
 * Validate a variant and return a frozen copy that holds only the fields it
 * names, always in the same order, or undefined for the provider's default.
 * Throws a TypeError for anything else: an unknown session or adjustment, a
 * blank or overlong currency or unit, or a field this build does not know,
 * which could only be a variant from a newer build that this one would
 * silently serve wrong.
 */
export function normalizeDataVariant(input: unknown): Readonly<DataVariant> | undefined {
  if (input == null) return undefined;
  const source = input as Record<string, unknown>;
  if (typeof input !== 'object' || Array.isArray(input)
    || Object.keys(source).some(key => !DIMENSIONS.includes(key as DataVariantDimension))) throw new TypeError('Invalid data variant');
  const out: Record<string, unknown> = {};
  for (const key of DIMENSIONS) {
    const value = source[key], choices = CHOICES[key];
    if (value === undefined) continue;
    if (choices ? !choices.includes(value as string) : typeof value !== 'string' || !value.trim() || value.length > 32) {
      throw new TypeError(`Invalid data ${key}: ${String(value)}`);
    }
    out[key] = value;
  }
  return Object.keys(out).length ? Object.freeze(out as DataVariant) : undefined;
}

/**
 * One string per variant, for keys and comparisons: empty for the provider's
 * default, so a key that appends it is byte-identical to the key before
 * variants existed. Field order in the input does not matter.
 */
export function dataVariantKey(variant?: DataVariant): string {
  const v = normalizeDataVariant(variant);
  return v ? JSON.stringify(DIMENSIONS.map(key => v[key] ?? null)) : '';
}

/**
 * The first field of `variant` the provider did not declare, or null when it
 * can serve all of it. The default variant is always served. Without a
 * declaration only the default is: a provider that never said it serves
 * extended hours cannot be trusted to have honoured the request, and a
 * regular series labelled extended is worse than no chart.
 */
export function unsupportedDataVariant(capabilities: DataVariantCapabilities | undefined, variant?: DataVariant): DataVariantDimension | null {
  const v = normalizeDataVariant(variant);
  const listed = (key: DataVariantDimension): readonly string[] | undefined =>
    capabilities?.[key === 'currency' ? 'currencies' : `${key}s` as keyof DataVariantCapabilities];
  return DIMENSIONS.find(key => v?.[key] !== undefined && !listed(key)?.includes(v[key]!)) ?? null;
}

/** The error a provider or the loading controller raises for an undeclared variant. */
export function dataVariantError(dimension: DataVariantDimension, variant?: DataVariant): Error {
  const error = new Error(`This source does not serve ${dimension} ${String(variant?.[dimension])}`);
  error.name = 'DataVariantUnsupportedError';
  return error;
}

/**
 * Marks the context `publishDataContext` passes through on its way to a
 * variant-only change. The chart copies it with the context, so a listener
 * sees it on the `data:context` payload and on `getDataContext()` while that
 * event runs, and the real context follows at once without it. A registered
 * symbol, so the indicators tier, bundled apart from this one, reads the same
 * key; JSON never carries it.
 */
const PASSING = Symbol.for('openalgo-charts.data-context.passing');

/**
 * Whether a context is the one `publishDataContext` passes through, which
 * the library's own listeners skip: asking a provider for it, publishing a
 * status for it or saving alerts for it is work thrown away a moment later.
 */
export function passingDataContext(context: unknown): boolean {
  return typeof context === 'object' && context !== null && (context as Record<symbol, unknown>)[PASSING] === true;
}

/** The two chart members `publishDataContext` needs. */
export interface DataContextTarget {
  getDataContext(): Readonly<ChartDataContext> | undefined;
  setDataContext(context: ChartDataContext | undefined): void;
}

/**
 * Give a chart a data context whose variant counts as part of its source.
 *
 * `Chart.setDataContext` treats a change of symbol, exchange, interval or
 * variant as a new source: it aborts requested bars, restarts source revisions
 * and tells studies to read the context again. For a `Chart` this is therefore
 * `setDataContext` with the variant normalized, and `data:context` fires once.
 *
 * A target that does not compare the variant, such as a host's own
 * `DataContextTarget`, would ignore a context that differs only there and go
 * on reporting the old one. For it this passes through a context with a
 * different interval first, which the target does treat as a source change,
 * then sets the real one. The instrument never changes on the way, so event
 * markers, linked drawings and news stay with it. On that detour
 * `data:context` fires twice: once for the passing context, whose interval is
 * cleared, then for the real one. That context is marked, and the library's
 * requested studies, Tier 2 studies and alert controller wait for the real one
 * rather than fetch, report or save for it. A host's own listener sees both.
 */
export function publishDataContext(chart: DataContextTarget, context: ChartDataContext | undefined): void {
  const variant = normalizeDataVariant(context?.variant);
  const next = context && { ...context };
  if (next) { delete next.variant; if (variant) next.variant = variant; }
  chart.setDataContext(next);
  if (next && dataVariantKey(chart.getDataContext()?.variant) !== dataVariantKey(variant)) {
    chart.setDataContext({ ...next, interval: next.interval === undefined ? '' : undefined, [PASSING]: true } as ChartDataContext);
    chart.setDataContext(next);
  }
}
