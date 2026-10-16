import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { parseCandles, aggregateCandles, createBtcUsdFeed } from '../website/lib/market-data/btc-usd.mjs';

const start = 1788652800;
const row = (offset = 0, close = 102) => [(start + offset) * 1000, 100, 110, 90, close, 2];
const response = rows => ({ ok: true, status: 200, json: async () => rows });
const bar = (offset, open, high, low, close, volume) => ({ time: start + offset, open, high, low, close, volume });

function harness(fetchImpl) {
  const timers = new Map();
  const updates = [];
  const statuses = [];
  let id = 0;
  const feed = createBtcUsdFeed({
    fetchImpl, onBars: (bars, interval) => updates.push({ bars, interval }),
    onStatus: status => statuses.push(status), now: () => 123456,
    setTimer: (cb, delay) => { timers.set(++id, { cb, delay }); return id; },
    clearTimer: timer => timers.delete(timer),
  });
  return { feed, timers, updates, statuses };
}

test('normalizes real candle rows to ascending UTC seconds and keeps latest duplicate', () => {
  const bars = parseCandles([row(3600, 108), row(0, 104), row(0, 101)]);
  assert.deepEqual(bars.map(b => [b.time, b.close]), [[start, 104], [start + 3600, 108]]);
  assert.equal(bars[0].volume, 2);
});

test('rejects unavailable, empty, and malformed market data rather than creating bars', () => {
  for (const data of [{ error: 'unavailable' }, [], [row().slice(0, 4)], [[null, 100, 110, 90, 102, 2]], [[start * 1000, 100, 95, 90, 102, 2]], [[start * 1000, 100, 110, 90, NaN, 2]]]) {
    assert.throws(() => parseCandles(data), /candle|market/i);
  }
});

test('aggregates four-hour candles on UTC boundaries using actual OHLC and summed volume', () => {
  const hourly = [bar(0, 100, 110, 97, 105, 2), bar(3600, 105, 115, 103, 109, 3), bar(7200, 109, 112, 101, 104, 4), bar(10800, 104, 117, 100, 116, 5), bar(14400, 116, 122, 112, 120, 6)];
  assert.deepEqual(aggregateCandles(hourly, 14400), [bar(0, 100, 117, 97, 116, 14), bar(14400, 116, 122, 112, 120, 6)]);
});

test('drops the incomplete leading four-hour bucket instead of inventing its open', () => {
  const hourly = [bar(3600, 105, 115, 103, 109, 3), bar(7200, 109, 112, 101, 104, 4), bar(14400, 116, 122, 112, 120, 6)];
  assert.deepEqual(aggregateCandles(hourly, 14400), [bar(14400, 116, 122, 112, 120, 6)]);
});

test('uses verified endpoint interval names and publishes real response values', async () => {
  const urls = [];
  const h = harness(async url => { urls.push(url); return response([row()]); });
  for (const interval of ['15m', '1h', '4h', '1d']) await h.feed.selectInterval(interval);
  assert.deepEqual(urls.map(url => url.split('/').pop()), ['15m', '1hr', '1hr', '1day']);
  assert.equal(h.updates.length, 4);
  assert.equal(h.updates[3].bars[0].close, 102);
  assert.equal(h.statuses.at(-1).state, 'connected');
  assert.equal(h.statuses.at(-1).updatedAt, 123456);
  assert.equal([...h.timers.values()].filter(t => t.delay === 15000).length, 1);
  h.feed.destroy();
  assert.equal(h.timers.size, 0);
});

test('rejects unsupported timeframes without requesting mislabeled data', async () => {
  let calls = 0;
  const h = harness(async () => { calls++; return response([row()]); });
  await assert.rejects(h.feed.selectInterval('5m'), /interval/i);
  assert.equal(calls, 0);
  h.feed.destroy();
});

test('polling applies a changed market close and keeps just one refresh timer', async () => {
  let close = 102;
  const h = harness(async () => response([row(0, close)]));
  await h.feed.selectInterval('1h');
  close = 108;
  const [timerId, timer] = [...h.timers].find(([, t]) => t.delay === 15000);
  h.timers.delete(timerId);
  await timer.cb();
  assert.equal(h.updates.at(-1).bars[0].close, 108);
  assert.equal(h.updates.length, 2);
  assert.equal(h.timers.size, 1);
  h.feed.destroy();
});

test('initial network failure shows unavailable state with no synthetic bars and retries', async () => {
  let failed = true;
  const h = harness(async () => { if (failed) throw new Error('offline'); return response([row()]); });
  await h.feed.selectInterval('1h');
  assert.equal(h.updates.length, 0);
  assert.equal(h.statuses.at(-1).state, 'error');
  failed = false;
  await h.feed.refresh();
  assert.equal(h.updates.length, 1);
  assert.equal(h.statuses.at(-1).state, 'connected');
  h.feed.destroy();
});

test('failed refresh labels existing candles stale and never manufactures replacements', async () => {
  let failed = false;
  const h = harness(async () => failed ? { ok: false, status: 429 } : response([row()]));
  await h.feed.selectInterval('1h');
  failed = true;
  await h.feed.refresh();
  assert.equal(h.updates.length, 1);
  assert.equal(h.statuses.at(-1).state, 'stale');
  h.feed.destroy();
});

test('a slow previous timeframe cannot replace a newer selection', async () => {
  let finishFirst;
  let firstSignal;
  const h = harness(async (url, options) => {
    if (url.endsWith('/15m')) { firstSignal = options.signal; return new Promise(resolve => { finishFirst = resolve; }); }
    return response([row(0, 108)]);
  });
  const first = h.feed.selectInterval('15m');
  await h.feed.selectInterval('1h');
  assert.equal(firstSignal.aborted, true);
  finishFirst(response([row(0, 101)]));
  await first;
  assert.deepEqual(h.updates.map(u => [u.interval, u.bars[0].close]), [['1h', 108]]);
  h.feed.destroy();
});

test('destroy aborts requests, removes timers, and suppresses late updates', async () => {
  let finish;
  let signal;
  const h = harness(async (url, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); });
  const loading = h.feed.selectInterval('1h');
  const statusCount = h.statuses.length;
  h.feed.destroy();
  assert.equal(signal.aborted, true);
  assert.equal(h.timers.size, 0);
  finish(response([row()]));
  await loading;
  assert.equal(h.updates.length, 0);
  assert.equal(h.statuses.length, statusCount);
});
