/**
 * A platform timer holds a delay of at most 2^31 - 1 ms. A longer one overflows
 * and fires at once, so a replay slowed far enough ticked every millisecond, and
 * a timeout set in weeks failed immediately. Every timer these modules start
 * for a caller's delay is held under the ceiling; ReplayGroup already was.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { ReplayController } from '../src/replay/controller';
import { FakeDataFeed } from '../src/feed/fake-feed';
import { withHistoryDeadline, HistoryRequestPool } from '../src/feed/request-pool';
import { OpenAlgoWsFeed } from '../src/feed/openalgo-ws';
import type { Bar } from '../src/model/bar';
import type { DataFeed } from '../src/feed/types';

const CEILING = 2 ** 31 - 1;
const WEEKS = 3e9;

afterEach(() => { vi.restoreAllMocks(); });

/** The delays every setInterval and setTimeout call was given. */
function delays(): { interval: number[]; timeout: number[] } {
  const seen = { interval: [] as number[], timeout: [] as number[] };
  const interval = globalThis.setInterval, timeout = globalThis.setTimeout;
  vi.spyOn(globalThis, 'setInterval').mockImplementation(((cb: () => void, ms?: number) => {
    seen.interval.push(ms ?? 0);
    return interval(cb, Math.min(ms ?? 0, CEILING));
  }) as typeof setInterval);
  vi.spyOn(globalThis, 'setTimeout').mockImplementation(((cb: () => void, ms?: number) => {
    seen.timeout.push(ms ?? 0);
    return timeout(cb, Math.min(ms ?? 0, CEILING));
  }) as typeof setTimeout);
  return seen;
}

/** A seeded random walk, the shape of a traded stock. */
function walk(n: number): Bar[] {
  let seed = 7, price = 1480;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  return Array.from({ length: n }, (_, i) => {
    const open = price;
    price = Math.max(1, price + next() * 12);
    return { time: 1_700_000_000 + i * 60, open, high: Math.max(open, price) + 2, low: Math.min(open, price) - 2, close: price, volume: 1000 + i };
  });
}

describe('timers held under the platform ceiling', () => {
  it('a very slow replay asks for an interval the platform can hold', () => {
    const seen = delays();
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(), raf: { schedule: () => 0 }, pixelRatio: () => 1, shortcuts: false,
    });
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    const bars = walk(30);
    series.setData(bars);
    const replay = new ReplayController(chart, { series, bars, speed: 1e-7 });
    replay.play();
    expect(seen.interval).toHaveLength(1);
    expect(seen.interval[0]).toBeLessThanOrEqual(CEILING);
    replay.stop();
    chart.destroy();
  });

  it('the fake feed holds a tick cadence the same way', () => {
    const seen = delays();
    const feed = new FakeDataFeed(60);
    const off = feed.subscribeBars({ symbol: 'SBIN', exchange: 'NSE', interval: '1m' }, () => {}, { tickMs: WEEKS });
    expect(seen.interval[0]).toBeLessThanOrEqual(CEILING);
    off();
  });

  it('a history deadline in weeks waits rather than failing at once', async () => {
    const answer = withHistoryDeadline({ timeoutMs: WEEKS }, () => new Promise<string>(resolve => setTimeout(() => resolve('bars'), 30)));
    await expect(answer).resolves.toBe('bars');
    const feed: DataFeed = { getBars: () => new Promise<Bar[]>(resolve => setTimeout(() => resolve(walk(3)), 30)) };
    const pool = new HistoryRequestPool(feed, { timeoutMs: WEEKS });
    await expect(pool.getBars({ symbol: 'SBIN', exchange: 'NSE', interval: '1m' })).resolves.toHaveLength(3);
  });

  it('a socket watchdog set in weeks does not probe at once', async () => {
    const sent: string[] = [];
    const socket = {
      readyState: 1, onopen: null, onclose: null, onerror: null,
      onmessage: null as ((e: { data: string }) => void) | null,
      send(frame: string) { sent.push(frame); }, close() {},
    };
    const ws = new OpenAlgoWsFeed({ url: 'ws://x', apiKey: 'k', heartbeat: { timeoutMs: WEEKS }, socketFactory: () => socket });
    ws.connect();
    socket.onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await new Promise(resolve => setTimeout(resolve, 30));
    expect(sent.some(frame => frame.includes('"ping"'))).toBe(false);
    ws.close();
  });
});
