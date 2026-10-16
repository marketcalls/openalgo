/**
 * The public option and column types of `exportChartDataCsv`, published from
 * chart-data-export.ts. A module of their own so the export's parts (snapshot,
 * alignment, formatting) can name them without importing the module that
 * imports them.
 */
import type { ComparisonHandle } from '../compare/controller';

/** Inclusive UTC-second bounds over installed primary rows. Omitted bounds are unbounded. */
export interface ChartDataCsvRange {
  readonly from?: number;
  readonly to?: number;
}

/** Canonical identities stay available even when a callback changes visible headers. */
export type ChartDataColumn = Readonly<{ key: string; title: string } & (
  | { kind: 'time' | 'timeLabel' | 'logicalIndex' | 'timeOrigin' }
  | { kind: 'primary'; field: 'open' | 'high' | 'low' | 'close' | 'volume' | 'oi' }
  | { kind: 'indicator'; instanceId: string; plotKey: string; field?: 'open' | 'high' | 'low' | 'close' }
  | { kind: 'comparison'; comparisonIndex: number; symbol: string; field: 'close' }
)>;

/** Detached installed axis. Replay never exposes its unrevealed source history here. */
export interface ChartDataProjectionContext {
  readonly axisTimes: readonly number[];
  readonly replay?: Readonly<{ time: number; forming: boolean; asOf?: number }>;
}

export interface ChartDataCsvFormatters {
  /** Adds a time_label column without replacing raw UTC seconds. */
  time?: (utcSeconds: number) => string;
  /** Called only for finite primary, study and comparison values. */
  value?: (value: number, column: ChartDataColumn) => string;
  header?: (column: ChartDataColumn) => string;
}

/** Options for a numeric snapshot of the chart's currently loaded data. */
export interface ChartDataCsvOptions {
  /** All studies by default, false for none, or instance IDs in the requested column order. Hidden studies remain eligible. */
  indicators?: boolean | readonly string[];
  /** Filter rows after full installed-history calculation, without changing study warmup. */
  range?: ChartDataCsvRange;
  /** Override the chart's registered comparisons, for example with an explicitly managed controller's list. */
  comparisons?: readonly Pick<ComparisonHandle, 'symbol' | 'barAt'>[];
  /** Source rows by default. Display uses effective study offsets on the shared axis. */
  alignment?: 'source' | 'display';
  /** Resolves positions outside the captured axis. Null explicitly leaves time unknown. */
  projectTime?: (logicalIndex: number, context: Readonly<ChartDataProjectionContext>) => number | null;
  formatters?: ChartDataCsvFormatters;
}
