declare module '*market-data/btc-usd.mjs' {
  interface Candle {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }
  export const BTC_USD_REFRESH_MS: number;
  export function createBtcUsdFeed(options: {
    onBars(bars: Candle[], interval: string): void;
    onStatus(status: {
      state: 'loading' | 'connected' | 'stale' | 'error';
      interval: string;
      message?: string;
    }): void;
    fetchImpl: typeof fetch;
  }): {
    selectInterval(interval: string): Promise<void>;
    refresh(): Promise<void>;
    destroy(): void;
  };
}
