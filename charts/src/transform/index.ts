// Transform tier (opt-in: "openalgo-charts/transform").
// Family B: price/movement-driven series. Importing the tier lets a chart apply
// Heikin Ashi, Renko, Range, Line Break, Point & Figure and Kagi itself
// (`chart.setSeriesTransform`), live, from the bars a host feeds. A host can
// still run a transform over OHLC bars and plot the result: Heikin Ashi /
// Renko / Range / Line Break render as a 'candlestick' series; Point & Figure
// as 'point-figure'; Kagi as 'kagi'.

// The registry MUST come from the package specifier 'openalgo-charts', not a
// relative path: each tier is its own rollup bundle, and rollup.config.js
// (`tierExternal`) leaves only the package specifiers external, so a relative
// import would inline a *second* copy of the registry and `createChart` would
// never see what this tier registers.
import { registerChartType } from 'openalgo-charts';
import { drawPointFigure } from '../render/point-figure';
import { drawKagi } from '../render/kagi';
import { registerSeriesTransforms } from './live';

export const TRANSFORM_TIER = 'transform' as const;

let _registered = false;

/**
 * Register the Family-B custom renderers (point-figure, kagi) and the six
 * transforms a chart can apply itself (`registeredSeriesTransforms`). Called
 * as a side effect when this tier is imported, and also exported so consumers
 * whose bundler aggressively tree-shakes a bare `import 'openalgo-charts/transform'`
 * can call it explicitly. Idempotent.
 *
 * (Heikin Ashi / Renko / Range / Line Break render as a 'candlestick' series and
 * need no new type: only P&F and Kagi have custom renderers.)
 */
export function registerTransformChartTypes(): void {
  if (_registered) return;
  _registered = true;
  registerSeriesTransforms();
  registerChartType('point-figure', {
    defaultStyle: {}, isPriceSeries: true,
    draw: (g, items, toY, bs, dpr, s, rc) => drawPointFigure(g, items, toY, bs, dpr, s, rc.plotHeight),
    extents: (bar) => ({ min: bar.low, max: bar.high }),
  });
  // Kagi joins each vertex to the next like a step line, so it takes the
  // neighbour beyond each edge too: otherwise the connector that enters the
  // view is lost, which on a sparse vertex series is most of the line.
  registerChartType('kagi', {
    defaultStyle: { thickColor: '#26a69a', thinColor: '#ef5350' }, isPriceSeries: true, connectsBars: true,
    draw: (g, items, toY, _bs, dpr, s) => drawKagi(g, items, toY, dpr, s),
    extents: (bar) => ({ min: bar.close, max: bar.close }),
  });
}

registerTransformChartTypes(); // side effect on tier import

export type { ISeriesTransform } from './transform';
export { runTransform, ensureIncreasingTimes } from './transform';
export { HeikinAshiTransform } from './heikin-ashi';
export { RenkoTransform, type RenkoOptions } from './renko';
export { RangeBarsTransform, type RangeOptions } from './range-bars';
export { LineBreakTransform, type LineBreakOptions } from './line-break';
export {
  PointFigureTransform,
  type PointFigureOptions,
  type PointFigureColumn,
  type PointFigureMethod,
  type PointFigureBoxMode,
} from './point-figure';
export { KagiTransform, type KagiOptions } from './kagi';

// Symbol arithmetic. It sits in this tier because it is the same shape as
// the others -- bars in, bars out, no DOM -- and a host that never charts a
// spread should not carry a parser in the base bundle.
export {
  parseExpression,
  evaluateExpression,
  isPlainSymbol,
  ExpressionError,
  type SymbolExpression,
  type ExpressionNode,
  type ExpressionFunctionName,
  type EvaluateOptions,
} from './expression';
