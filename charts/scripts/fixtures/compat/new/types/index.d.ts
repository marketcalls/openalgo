// The later release in the fixture for tests/check-compat.test.ts; see
// old/types/index.d.ts for what each export holds.

export interface ChartOptions {
  width?: number;
  locale: string;
  scale?: 'linear';
  onClick?: (event: ClickEvent) => void;
  /** Added: additive. */
  height?: number;
}

export interface ClickEvent {
  price: number;
}

export declare class Chart {
  private _renamedSecret;
  setPrecision(digits: number): void;
  getState(): SavedState;
  seriesType(): 'candles' | 'line' | 'area';
  destroy(): void;
  /** Added: additive. */
  resize(): void;
}

export interface SavedState {
  version: number;
  zoom: number | undefined;
}

export declare function createChart(el: HTMLElement, options?: ChartOptions): Chart;

export declare const SAVE_DELAY_MS = 500;

export interface IndicatorApi {
  id(): string;
  barSource(): string;
}
export declare function addStudy(chart: Chart): IndicatorApi;
export declare function removeStudy(study: IndicatorApi): void;

export interface DataFeed {
  history(symbol: string): Promise<number[]>;
  close(): void;
}
export declare function connect(feed: DataFeed): void;

export interface Marker {
  price: number;
}

/** New: additive. */
export declare function newHelper(): void;
