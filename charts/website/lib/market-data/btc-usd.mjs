/** Public BTC/USD candles. Prices are accepted only from a validated market response. */
export const BTC_USD_SOURCE = 'https://developer.gemini.com/trading/rest-api/market-data/list-candles';
export const BTC_USD_REFRESH_MS = 15000;
export const BTC_USD_INTERVALS = ['15m', '1h', '4h', '1d'];
const ENDPOINTS = { '15m': '15m', '1h': '1hr', '4h': '1hr', '1d': '1day' };
const CANDLE_URL = 'https://api.gemini.com/v2/candles/btcusd/';

/** @typedef {{time: number, open: number, high: number, low: number, close: number, volume: number}} Candle */

/** Convert newest-first millisecond OHLCV rows into validated ascending candles. */
export function parseCandles(payload) {
  if (!Array.isArray(payload) || payload.length === 0) throw new Error('Market candle data is unavailable.');
  const byTime = new Map();
  for (const row of payload) {
    if (!Array.isArray(row) || row.length < 6 || row.slice(0, 6).some(value => typeof value !== 'number' || !Number.isFinite(value))) {
      throw new Error('Invalid market candle response.');
    }
    const [timestamp, open, high, low, close, volume] = row;
    const time = timestamp / 1000;
    if (!Number.isSafeInteger(time) || time <= 0 || Math.min(open, high, low, close) <= 0 || high < Math.max(open, close) || low > Math.min(open, close) || volume < 0) {
      throw new Error('Invalid market candle values.');
    }
    if (!byTime.has(time)) byTime.set(time, { time, open, high, low, close, volume });
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

/** Aggregate real candles into UTC-aligned buckets; omit a leading partial bucket. */
export function aggregateCandles(bars, seconds) {
  const result = [];
  let bucket;
  for (const bar of bars) {
    const time = Math.floor(bar.time / seconds) * seconds;
    if (!bucket || bucket.time !== time) {
      if (bar.time !== time) { bucket = undefined; continue; }
      bucket = { ...bar, time };
      result.push(bucket);
    } else {
      bucket.high = Math.max(bucket.high, bar.high);
      bucket.low = Math.min(bucket.low, bar.low);
      bucket.close = bar.close;
      bucket.volume += bar.volume;
    }
  }
  return result;
}

/**
 * Own a single cancellable polling session. Selecting a timeframe invalidates all
 * earlier work. A failed refresh preserves real history and explicitly marks it stale.
 */
export function createBtcUsdFeed({
  onBars, onStatus, fetchImpl = globalThis.fetch, now = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout,
  refreshMs = BTC_USD_REFRESH_MS, timeoutMs = 10000,
}) {
  let interval = '1h';
  let sequence = 0;
  let disposed = false;
  let controller;
  let refreshTimer;
  let requestTimer;
  let hasData = false;
  let lastUpdate;

  function cancelPending() {
    if (refreshTimer !== undefined) clearTimer(refreshTimer);
    if (requestTimer !== undefined) clearTimer(requestTimer);
    refreshTimer = undefined;
    requestTimer = undefined;
    controller?.abort();
    controller = undefined;
  }

  async function refresh() {
    if (disposed) return;
    cancelPending();
    const current = ++sequence;
    const requestedInterval = interval;
    const request = new AbortController();
    controller = request;
    const timeout = setTimer(() => request.abort(), timeoutMs);
    requestTimer = timeout;
    if (!hasData) onStatus({ state: 'loading', interval: requestedInterval });
    try {
      const response = await fetchImpl(CANDLE_URL + ENDPOINTS[requestedInterval], {
        signal: request.signal, cache: 'no-store', credentials: 'omit',
      });
      if (!response.ok) throw new Error(`Market data request failed (${response.status}).`);
      const parsed = parseCandles(await response.json());
      if (disposed || current !== sequence) return;
      const bars = (requestedInterval === '4h' ? aggregateCandles(parsed, 14400) : parsed).slice(-320);
      if (bars.length === 0) throw new Error('Market candles are not available for this interval.');
      onBars(bars, requestedInterval);
      hasData = true;
      lastUpdate = { updatedAt: now(), barTime: bars.at(-1).time, close: bars.at(-1).close };
      onStatus({ state: 'connected', interval: requestedInterval, ...lastUpdate });
    } catch (error) {
      if (disposed || current !== sequence) return;
      onStatus({
        state: hasData ? 'stale' : 'error', interval: requestedInterval, ...lastUpdate,
        message: request.signal.aborted ? 'Market data request timed out.' : error instanceof Error ? error.message : 'Market data is unavailable.',
      });
    } finally {
      clearTimer(timeout);
      if (!disposed && current === sequence) {
        requestTimer = undefined;
        controller = undefined;
        refreshTimer = setTimer(refresh, refreshMs);
      }
    }
  }

  return {
    async selectInterval(nextInterval) {
      if (!Object.hasOwn(ENDPOINTS, nextInterval)) throw new Error('Unsupported BTC/USD interval.');
      if (disposed) return;
      interval = nextInterval;
      hasData = false;
      lastUpdate = undefined;
      await refresh();
    },
    refresh,
    destroy() {
      disposed = true;
      sequence++;
      cancelPending();
    },
  };
}
