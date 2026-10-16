// The earlier release in the fixture for tests/check-compat.test.ts. Each
// export holds one rule of scripts/check-compat.mjs; new/dist/index.d.ts
// changes it, and the test names the finding each change must produce.

/** Options the host passes in. */
export interface ChartOptions {
  /** Unchanged. */
  width?: number;
  /** Removed: a host that sets it is silently ignored, which the compiler allows. */
  legacyTheme?: string;
  /** Optional, then required: a host that left it out stops compiling. */
  locale?: string;
  /** Narrowed: a host passing 'log' stops compiling. */
  scale?: 'linear' | 'log';
  /** A callback: the library hands it a payload, which loses a field. */
  onClick?: (event: ClickEvent) => void;
}

export interface ClickEvent {
  price: number;
  time: number;
}

export declare class Chart {
  /** Private: never public, so its change is no finding. */
  private _secret;
  /** A method parameter narrowed. The compiler checks method parameters both ways round; the walk does not. */
  setPrecision(digits: number | 'auto'): void;
  /** A returned object whose member may now be missing. */
  getState(): SavedState;
  /** A returned name that gains a member: additive. */
  seriesType(): 'candles' | 'line';
  /** Unchanged. */
  destroy(): void;
}

export interface SavedState {
  version: number;
  zoom: number;
}

export declare function createChart(el: HTMLElement, options?: ChartOptions): Chart;

/** Removed outright. */
export declare function legacyHelper(): void;

/** Removed, and listed as deprecated for the next major. */
export declare function retiredHelper(): void;

/** A constant whose value changes: its literal type follows the value. */
export declare const SAVE_DELAY_MS = 400;

/** A handle (HANDLES in the script): the host holds one the library made, so a new member is additive. */
export interface IndicatorApi {
  id(): string;
}
export declare function addStudy(chart: Chart): IndicatorApi;
export declare function removeStudy(study: IndicatorApi): void;

/** An interface the host implements: a new required member breaks every implementation. */
export interface DataFeed {
  history(symbol: string): Promise<number[]>;
}
export declare function connect(feed: DataFeed): void;

/** A class, which becomes only a type. */
export declare class Marker {
  constructor(price: number);
  price: number;
}
