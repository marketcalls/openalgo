/**
 * Whether a widget can show a chart type. A leaf module, so the layout,
 * persistence and grid code that validate a saved chart type need not import
 * the top bar, which imports the Layouts button and through it those modules.
 */
import { registeredChartTypes, registeredSeriesTransforms, type Chart } from 'openalgo-charts';

/** Whether a widget can show this chart type: a registered renderer, or a transform the chart applies. Internal. */
export function isChartTypeChoice(id: unknown): id is string {
  return typeof id === 'string' && (registeredChartTypes().includes(id) || registeredSeriesTransforms().includes(id));
}

/**
 * The transform the chart's primary series is built with when that type has
 * a settings dialog of its own (point and figure, Renko), else null. Point
 * and figure drawn from a host's own elements is a renderer with no box size
 * to set, so it answers null. Internal.
 */
export function boxChartType(chart: Chart): 'point-figure' | 'renko' | null {
  const series = chart.primarySeries();
  const type = series === null ? undefined : chart.seriesTransform(series)?.type;
  return type === 'point-figure' || type === 'renko' ? type : null;
}
