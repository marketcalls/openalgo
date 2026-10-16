import type { Chart } from '../core/chart';
import { existingComparisonHandles } from '../compare/controller';
import { getIndicator } from './indicator-registry';
import { replayWindow } from './replay-window';
import type { ChartDataColumn, ChartDataCsvOptions, ChartDataCsvRange, ChartDataProjectionContext } from './chart-data-export-types';

const priceFields = ['open', 'high', 'low', 'close', 'volume', 'oi'] as const;
const allFields = ['time', ...priceFields] as const;
const candleFields = ['open', 'high', 'low', 'close'] as const;
const finiteCsvValue = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) ? value : undefined;
export const withinCsvRange = (time: number, range: ChartDataCsvRange): boolean =>
  (range.from === undefined || time >= range.from) && (range.to === undefined || time <= range.to);

export interface CsvSnapshotColumn {
  meta: ChartDataColumn;
  values: (number | undefined)[];
  offset: number;
}
export interface CsvSnapshot {
  times: number[];
  columns: CsvSnapshotColumn[];
  context: Readonly<ChartDataProjectionContext>;
}

export function captureCsvSnapshot(chart: Chart, selection: boolean | string[], alignment: 'source' | 'display',
  range: ChartDataCsvRange, requestedComparisons: ChartDataCsvOptions['comparisons']): CsvSnapshot {
  // Calculations may replace source history synchronously. Refuse a mixed snapshot
  // rather than joining accepted old values to newly installed primary rows.
  const bars = chart.primaryBars().map(({ time, open, high, low, close, volume, oi }) => ({ time, open, high, low, close, volume, oi }));
  const installed = selection === false ? [] : chart.indicators().slice();
  const byId = new Map(installed.map(study => [study.id, study]));
  const studies = typeof selection === 'boolean' ? installed : selection.map(id => {
    const study = byId.get(id);
    if (!study) throw new RangeError(`Unknown CSV indicator ID: ${id}`);
    return study;
  });
  const columns: CsvSnapshotColumn[] = priceFields.map(field => ({
    meta: Object.freeze({ key: field, title: field, kind: 'primary', field }),
    values: bars.map(bar => finiteCsvValue(bar[field])), offset: 0,
  }));
  for (const study of studies) {
    const values = study.values();
    for (const plot of getIndicator(study.indicatorId).plots) {
      let offset = 0;
      if (alignment === 'display') {
        const series = study.series(plot.key);
        const style = series && chart.seriesStyle(series);
        if (!style) throw new Error(`CSV plot resource is unavailable: ${study.id}:${plot.key}`);
        offset = style.barOffset === undefined ? 0 : style.barOffset;
        if (typeof offset !== 'number' || !Number.isFinite(offset)) throw new TypeError('CSV plot offset must be finite');
      }
      const fields = alignment === 'display' && plot.ohlc ? candleFields : [undefined];
      for (const field of fields) {
        const key = `indicator:${study.id}:${plot.key}${field ? ':' + field : ''}`;
        const valueKey = field ? plot.ohlc![field] : plot.key;
        const column = values[valueKey];
        columns.push({ meta: Object.freeze({ key, title: field ? `${plot.title} ${field}` : plot.title,
          kind: 'indicator', instanceId: study.id, plotKey: plot.key, ...(field ? { field } : {}) }),
        values: Array.isArray(column) ? column.map(finiteCsvValue) : [], offset });
      }
    }
  }
  const current = chart.primaryBars();
  if (bars.length !== current.length || bars.some((bar, index) => allFields.some(field => !Object.is(bar[field], current[index]![field])))) {
    throw new Error('Chart data changed during CSV snapshot');
  }
  const replay = replayWindow(chart);
  const axisTimes = alignment === 'display'
    ? Array.from({ length: chart.dataLayer.length }, (_, index) => chart.dataLayer.indexToTime(index)!)
      .filter(time => !replay || time <= replay.time)
    : [];
  if (axisTimes.some((time, index) => !Number.isFinite(time) || (index > 0 && time <= axisTimes[index - 1]!))) {
    throw new Error('CSV axis times must be finite and increasing');
  }
  const context = Object.freeze({ axisTimes: Object.freeze(axisTimes), ...(replay ? { replay: Object.freeze({ ...replay }) } : {}) });
  // Finish copying comparisons before invoking any presentation callback. Their
  // own symbol metadata is captured first in case a barAt callback changes a host.
  const comparisons = (requestedComparisons ?? existingComparisonHandles(chart)).map(item => ({ symbol: item.symbol, item }));
  const comparisonColumns: CsvSnapshotColumn[] = comparisons.map(({ symbol }, index) => {
    const key = `comparison:${index + 1}:${symbol}:close`;
    return { meta: Object.freeze({ key, title: symbol, kind: 'comparison', comparisonIndex: index + 1, symbol, field: 'close' }), values: [], offset: 0 };
  });
  bars.forEach((bar, index) => {
    if (alignment === 'source' && !withinCsvRange(bar.time, range)) return;
    // One column per comparison, in the same order.
    comparisons.forEach(({ item }, column) => { comparisonColumns[column]!.values[index] = finiteCsvValue(item.barAt(bar.time)?.close); });
  });
  columns.push(...comparisonColumns);
  return { times: bars.map(bar => bar.time), columns, context };
}
