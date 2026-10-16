/**
 * Indicator tier (opt-in: "openalgo-charts/indicators").
 *
 * The Tier-1 built-ins, computed from the chart's own bars, no extra data,
 * plus the Tier-2 contract for indicators that own an external fetch/subscribe
 * lifecycle. Importing this module registers every built-in as a side effect;
 * `registeredIndicators()` counts them.
 *
 * ```ts
 * import { createChart } from 'openalgo-charts';
 * import 'openalgo-charts/indicators';
 *
 * const chart = createChart(el);
 * chart.addSeries('candlestick').setData(bars);
 * chart.addIndicator('macd');
 * chart.addIndicator('bollinger', { length: 20, stdDev: 2.5 });
 * ```
 *
 * `registerIndicator` is imported from the package specifier
 * `'openalgo-charts'`, never a relative path: each tier is its own bundle, and
 * rollup.config.js (`tierExternal`) leaves only the package specifiers
 * external, so a relative import of `../index` or of the registry module
 * would inline a second copy of the registry and `chart.addIndicator` would
 * never find what this tier registers.
 */
import { registerIndicator } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import { SMA, EMA, WMA, VWAP, BOLLINGER, SUPERTREND, PARABOLIC_SAR, ICHIMOKU, HALFTREND } from './trend';
import { RSI, MACD, STOCHASTIC, ADX, CCI, MFI, ATR, WILLIAMS_VIX_FIX } from './momentum';
import { VOLUME, OBV, ADL } from './volume';
import { OPEN_INTEREST, OPEN_INTEREST_CHANGE, OPEN_INTEREST_BUILDUP } from './open-interest';
// The ported built-in indicators. Grouped by family in their own modules so the
// tier index stays a manifest rather than a wall of descriptors.
import { OVERLAY_INDICATORS } from './overlay';
import { OSCILLATOR_INDICATORS } from './oscillators';
import { VOLATILITY_INDICATORS } from './volatility';
import { FLOW_INDICATORS } from './flow';
import { ADAPTIVE_INDICATORS } from './adaptive';
import { AVERAGE_INDICATORS } from './averages';
import { STRENGTH_INDICATORS } from './strength';
import { INDEX_INDICATORS } from './indices';
import { RANGE_INDICATORS } from './ranges';
import { SIGNAL_INDICATORS } from './signals';
import { STUDY_INDICATORS } from './studies';
import { WAVETREND_INDICATORS } from './wavetrend';
import { SEASONALITY_INDICATORS } from './seasonality';
import { EXPONENTIAL_INDICATORS } from './exponential';
import { SWING_INDICATORS } from './swings';

export const INDICATORS_TIER = 'indicators' as const;

/** Every built-in descriptor, in picker order. */
export const BUILTIN_INDICATORS: readonly IndicatorDescriptor[] = [
  SMA, EMA, WMA, VWAP, BOLLINGER, SUPERTREND, HALFTREND, PARABOLIC_SAR, ICHIMOKU,
  RSI, MACD, STOCHASTIC, ADX, CCI, MFI, ATR, WILLIAMS_VIX_FIX,
  VOLUME, OBV, ADL,
  OPEN_INTEREST, OPEN_INTEREST_CHANGE, OPEN_INTEREST_BUILDUP,
  ...OVERLAY_INDICATORS,
  ...OSCILLATOR_INDICATORS,
  ...VOLATILITY_INDICATORS,
  ...FLOW_INDICATORS,
  ...ADAPTIVE_INDICATORS,
  ...AVERAGE_INDICATORS,
  ...STRENGTH_INDICATORS,
  ...INDEX_INDICATORS,
  ...RANGE_INDICATORS,
  ...SIGNAL_INDICATORS,
  ...STUDY_INDICATORS,
  ...WAVETREND_INDICATORS,
  ...SEASONALITY_INDICATORS,
  ...EXPONENTIAL_INDICATORS,
  ...SWING_INDICATORS,
];

let _registered = false;

/**
 * Register every built-in indicator. Called as a side effect on import, and
 * exported so bundlers that aggressively tree-shake a bare side-effect import
 * can call it explicitly. Idempotent.
 */
export function registerBuiltinIndicators(): void {
  if (_registered) return;
  _registered = true;
  for (const descriptor of BUILTIN_INDICATORS) registerIndicator(descriptor);
}

registerBuiltinIndicators(); // side effect on tier import

export { SMA, EMA, WMA, VWAP, BOLLINGER, SUPERTREND, HALFTREND, PARABOLIC_SAR, ICHIMOKU } from './trend';
export { RSI, MACD, STOCHASTIC, ADX, CCI, MFI, ATR, WILLIAMS_VIX_FIX } from './momentum';
export { VOLUME, OBV, ADL } from './volume';
export { OPEN_INTEREST, OPEN_INTEREST_CHANGE, OPEN_INTEREST_BUILDUP } from './open-interest';
export * from './overlay';
export * from './oscillators';
export * from './volatility';
export * from './flow';
export * from './adaptive';
export * from './averages';
export * from './strength';
export * from './indices';
export * from './ranges';
export * from './signals';
export * from './studies';
export * from './wavetrend';
export * from './seasonality';
export * from './exponential';
export * from './swings';
export { sma, wma, rma, stdev, highest, lowest, nulls } from './calc';
// The rest of `./calc`: the shared TA helpers. Every built-in already
// pulls these out of this bundle, so exporting them adds names and no code, and
// it is what lets a custom indicator port a study instead of re-deriving it.
export {
  smaSeededEma, change, roc, dev, percentRank, alma, vwma,
  highestBars, lowestBars, rollingSum, cumulative, linreg, swma, stoch,
  percentileNearestRank, correlation, cci, pivotHigh, pivotLow,
  barsSince, valueWhen,
} from './calc';
export {
  createTier2Indicator,
  type Tier2Descriptor,
  type Tier2Context,
  type Tier2Point,
} from './external';
export { securitySeries, securityExpression, type SecuritySeries, type SecurityOptions, type SecurityExpressionOptions } from './security';
export { withTimeframe } from './timeframe';
export {
  rollingMedian, rollingMode, rollingVariance, rollingRange, percentileLinear,
  rankCorrelation, centerOfGravity, runningMin, runningMax,
  crossesAbove, crossesBelow, crosses, rising, falling,
  type NumericalWindowOptions, type RollingVarianceOptions,
} from './statistics';
export {
  alignRequestedExpression, requestedIntrabars,
  type RequestedBarsSnapshot, type RequestedExpression, type RequestedAlignmentOptions,
  type RequestedTimeWindow, type RequestedIntrabarOptions, type RequestedIntrabarValues,
} from './requested-context';
export {
  createRequestedIndicator, type RequestedIndicatorDescriptor, type RequestedIndicatorContext,
} from './requested-indicator';
export { inheritedDataVariant } from './inherited-variant';
