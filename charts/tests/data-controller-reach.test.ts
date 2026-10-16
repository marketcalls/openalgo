/**
 * Paging older history back to a requested time. A date far behind the loaded
 * window must cost one date-window request on a range feed, not one request
 * per default page, and the paging contract (empty windows, exhaustion,
 * retention, context changes) must hold for a reach exactly as for a gesture.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { DataLoadingController } from '../src/feed/data-controller';
import type { Bar } from '../src/model/bar';
import type { BarsRequest, DataFeed } from '../src/feed/types';

const bar = (time: number, close = 100): Bar => ({ time, open: 100, high: Math.max(101, close), low: 99, close });
const req: BarsRequest = { symbol: 'NIFTY', exchange: 'NSE', interval: '1m', from: 1000, to: 1200 };
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(fn => fn()); });
function make(feed: DataFeed, options = {}): DataLoadingController {
  const controller = new DataLoadingController(feed, { now: () => 1200, ...options });
  cleanups.push(() => controller.destroy());
  return controller;
}

describe('history reach', () => {
  it('asks a date-range feed for the whole gap back to the requested time in one window', async () => {
    const windows: Array<[number, number]> = [];
    const controller = make({ getBars: async request => {
      windows.push([request.from!, request.to!]);
      if (windows.length === 1) return [bar(1080), bar(1140)];
      return [bar(-9000), bar(-8940), bar(500)].filter(value => value.time >= request.from! && value.time <= request.to!);
    } });
    await controller.load(req);
    await controller.loadMore(-9000);
    expect(windows).toHaveLength(2);
    expect(windows[1][0]).toBeLessThanOrEqual(-9000);
    expect(windows[1][1]).toBeLessThan(1080);
    expect(controller.bars().map(value => value.time)).toEqual([-9000, -8940, 500, 1080, 1140]);
    expect(controller.getState().reason).toBe('prepend');
  });

  it('keeps the ordinary page window when the requested time is already inside it', async () => {
    const windows: Array<[number, number]> = [];
    const controller = make({ getBars: async request => {
      windows.push([request.from!, request.to!]);
      return windows.length === 1 ? [bar(1080)] : [bar(1000)];
    } });
    await controller.load(req);
    await controller.loadMore(1050);
    expect(windows[1][0]).toBe(1080 - 200);
  });

  it('reports an empty reach without claiming the provider is exhausted', async () => {
    let calls = 0;
    const controller = make({ getBars: async () => ++calls === 1 ? [bar(1080)] : [] }, { maxEmptyPages: 2 });
    await controller.load(req);
    await controller.loadMore(-50_000);
    expect(calls).toBe(3);
    expect(controller.getState()).toMatchObject({ hasMore: null, historyStatus: 'idle' });
  });

  it('never widens a date window past what retention could keep', async () => {
    const windows: Array<[number, number]> = [];
    const controller = make({ getBars: async request => {
      windows.push([request.from!, request.to!]);
      return windows.length === 1 ? [bar(1080), bar(1140)] : [];
    } }, { maxBars: 1000, maxEmptyPages: 1 });
    await controller.load(req);
    // Two years of one-minute bars back; retention holds a thousand of them.
    await controller.loadMore(1080 - 2 * 365 * 86400);
    expect(windows).toHaveLength(2);
    expect(windows[1][1] - windows[1][0]).toBeLessThanOrEqual(1000 * 60);
    expect(windows[1][0]).toBeLessThanOrEqual(1080 - 200);
  });

  it('leaves a paged feed its ordinary window, since it pages by count', async () => {
    const pages: Array<[number, number]> = [];
    const controller = make({ getBars: async () => [bar(1080)], getBarsPage: async request => {
      pages.push([request.from!, request.before]);
      return { bars: [bar(900)], hasMore: true };
    } });
    await controller.load(req);
    await controller.loadMore(-50_000);
    expect(pages).toEqual([[1080 - 200, 1080]]);
  });

  it('pages a countBack feed one page per reach and respects its exhaustion', async () => {
    const pages: number[] = [];
    const controller = make({ getBars: async () => [bar(1080)], getBarsPage: async request => {
      pages.push(request.countBack);
      return { bars: [bar(900), bar(960)], hasMore: false };
    } }, { pageSize: 50 });
    await controller.load(req);
    await controller.loadMore(-50_000);
    expect(pages).toEqual([50]);
    expect(controller.getState()).toMatchObject({ hasMore: false, historyStatus: 'exhausted' });
  });
});
