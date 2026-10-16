/**
 * Stream-driven repair: refresh when a bar closes or a bucket is skipped, fetch
 * only the tail, and keep a provisional open from undoing a repair.
 *
 * The fixed poll re-fetches the whole load window on a clock, whether or not
 * anything happened. A stream already says when something happened: a pushed
 * bar that opens a new bucket means the previous one closed, and a bar that
 * lands more than one bucket past the tail means buckets were skipped. Reacting
 * to those costs about one request per bar, nothing while the market is quiet,
 * and repairs a skipped bucket at once instead of at the next tick of a clock.
 *
 * Every option is off by default: the first test pins that a controller built
 * the old way schedules nothing new on a push.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DataLoadingController } from '../src/feed/data-controller';
import type { Bar } from '../src/model/bar';
import type { BarsRequest, DataFeed } from '../src/feed/types';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
const bar = (time: number, close = 100, volume = 10, open = 100): Bar =>
  ({ time, open, high: Math.max(open, close, 101), low: Math.min(open, close, 99), close, volume });
/** One-minute bars on a minute grid; the load window ends inside the 180 bucket. */
const req: BarsRequest = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m', from: 0, to: 190 };
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.useRealTimers(); });
function make(feed: DataFeed, options = {}) {
  const controller = new DataLoadingController(feed, { now: () => 190, ...options });
  cleanups.push(() => controller.destroy());
  return controller;
}
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const times = (controller: DataLoadingController) => controller.bars().map(b => b.time);

/** A feed that records every history request and answers from a script. */
function recording(answers: () => Bar[]) {
  const requests: BarsRequest[] = [];
  const feed: DataFeed = { getBars: async (r) => { requests.push({ ...r, signal: undefined }); return answers(); } };
  return { feed, requests };
}

describe('defaults', () => {
  it.each([undefined, 0, 150])('keeps the live open-interest observation %s during an overlapping history repair', async (oi) => {
    const pending = deferred<Bar[]>();
    let calls = 0;
    const controller = make({
      getBars: async () => ++calls === 1 ? [{ ...bar(60), oi: 100 }] : pending.promise,
    });
    await controller.load(req);
    const refresh = controller.refresh();
    controller.pushBar({ ...bar(60, 105), ...(oi === undefined ? {} : { oi }) });
    pending.resolve([{ ...bar(60, 102), oi: 120 }]);
    await refresh;
    expect(controller.bars()[0].close).toBe(105);
    expect(controller.bars()[0].oi).toBe(oi);
  });

  it('a controller built the old way schedules nothing on a push', async () => {
    vi.useFakeTimers();
    const { feed, requests } = recording(() => [bar(60), bar(120)]);
    const controller = make(feed);
    await controller.load(req);
    controller.pushBar(bar(180));
    controller.pushBar(bar(300));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requests).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(times(controller)).toEqual([60, 120, 180, 300]);
  });

  it('rejects options that cannot mean anything', () => {
    const feed: DataFeed = { getBars: async () => [] };
    expect(() => new DataLoadingController(feed, { refreshWindowBars: 0 })).toThrow(RangeError);
    expect(() => new DataLoadingController(feed, { refreshWindowBars: 1.5 })).toThrow(RangeError);
    expect(() => new DataLoadingController(feed, { refreshOnBarClose: { delayMs: -1 } })).toThrow(RangeError);
    expect(() => new DataLoadingController(feed, { refreshOnBarClose: { retries: 0.5 } })).toThrow(RangeError);
  });
});

describe('refreshOnBarClose', () => {
  it('refreshes once, delayMs after the stream opens a new bucket, and not on updates within it', async () => {
    vi.useFakeTimers();
    const { feed, requests } = recording(() => [bar(60), bar(120, 105)]);
    const controller = make(feed, { refreshOnBarClose: { delayMs: 2500 } });
    await controller.load(req);
    controller.pushBar(bar(120, 102));
    controller.pushBar(bar(120, 103));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requests).toHaveLength(1);

    controller.pushBar(bar(180, 104));
    await vi.advanceTimersByTimeAsync(2_499);
    expect(requests).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(requests).toHaveLength(2);
    expect(requests[1].noCache).toBe(true);
    // The closed bar took REST's close; the bar the stream opened is untouched.
    expect(controller.bars()[1].close).toBe(105);
    expect(times(controller)).toEqual([60, 120, 180]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requests).toHaveLength(2);
  });

  it('retries, a bounded number of times, while history has not published the closed bar', async () => {
    vi.useFakeTimers();
    let published = false;
    const { feed, requests } = recording(() => published ? [bar(60), bar(120)] : [bar(60)]);
    const controller = make(feed, { refreshOnBarClose: { delayMs: 1000, retries: 2, retryDelayMs: 5000 } });
    await controller.load(req);
    controller.pushBar(bar(120));
    controller.pushBar(bar(180));
    await vi.advanceTimersByTimeAsync(1000);
    await settle();
    expect(requests).toHaveLength(2);
    // Still short of 120: retry after retryDelayMs, and the stream's bars stay.
    expect(times(controller)).toEqual([60, 120, 180]);
    await vi.advanceTimersByTimeAsync(5000);
    await settle();
    expect(requests).toHaveLength(3);
    published = true;
    await vi.advanceTimersByTimeAsync(5000);
    await settle();
    expect(requests).toHaveLength(4);
    // Satisfied now: no further retries.
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requests).toHaveLength(4);
  });

  it('stops retrying once the budget is spent', async () => {
    vi.useFakeTimers();
    const { feed, requests } = recording(() => [bar(60)]);
    const controller = make(feed, { refreshOnBarClose: { delayMs: 1000, retries: 1, retryDelayMs: 1000 } });
    await controller.load(req);
    controller.pushBar(bar(120));
    controller.pushBar(bar(180));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requests).toHaveLength(3);
  });

  it('fires on any rollover, fixed-length interval or not', async () => {
    vi.useFakeTimers();
    const { feed, requests } = recording(() => [bar(60)]);
    const controller = make(feed, { refreshOnBarClose: true });
    await controller.load({ ...req, interval: 'not-an-interval' });
    controller.pushBar(bar(120));
    await vi.advanceTimersByTimeAsync(2500);
    await settle();
    expect(requests).toHaveLength(2);
  });

  it('does nothing while hidden and cancels a pending repair on hide', async () => {
    vi.useFakeTimers();
    const { feed, requests } = recording(() => [bar(60), bar(120)]);
    const controller = make(feed, { refreshOnBarClose: { delayMs: 1000 } });
    await controller.load(req);
    controller.pushBar(bar(180));
    controller.setVisible(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requests).toHaveLength(1);
    controller.pushBar(bar(240));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requests).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('queues a repair behind a refresh in flight instead of aborting it', async () => {
    vi.useFakeTimers();
    const pending = deferred<Bar[]>();
    let calls = 0;
    const requests: BarsRequest[] = [];
    const controller = make({ getBars: async (r) => { requests.push(r); return ++calls === 1 ? [bar(60), bar(120)] : calls === 2 ? pending.promise : [bar(60), bar(120), bar(180)]; } },
      { refreshOnBarClose: { delayMs: 1000 } });
    await controller.load(req);
    const work = controller.refresh();
    controller.pushBar(bar(180));
    await vi.advanceTimersByTimeAsync(1000);
    expect(requests).toHaveLength(2);
    expect(requests[1].signal?.aborted).toBe(false);
    pending.resolve([bar(60), bar(120)]);
    await work;
    await settle();
    expect(requests).toHaveLength(3);
    expect(times(controller)).toEqual([60, 120, 180]);
  });

  it('is cleared by destroy', async () => {
    vi.useFakeTimers();
    const { feed } = recording(() => [bar(60)]);
    const controller = make(feed, { refreshOnBarClose: true });
    await controller.load(req);
    controller.pushBar(bar(120));
    controller.destroy();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('refreshOnGap', () => {
  it('refreshes at once when a pushed bar skips buckets, and fills them from history', async () => {
    let answers: Bar[] = [bar(60), bar(120)];
    const { feed, requests } = recording(() => answers);
    const controller = make(feed, { refreshOnGap: true });
    await controller.load(req);
    answers = [bar(60), bar(120), bar(180), bar(240), bar(300)];
    controller.pushBar(bar(300));
    expect(times(controller)).toEqual([60, 120, 300]);
    await settle();
    expect(requests).toHaveLength(2);
    expect(times(controller)).toEqual([60, 120, 180, 240, 300]);
  });

  it('treats a plain rollover as no gap', async () => {
    const { feed, requests } = recording(() => [bar(60), bar(120)]);
    const controller = make(feed, { refreshOnGap: true });
    await controller.load(req);
    controller.pushBar(bar(180));
    await settle();
    expect(requests).toHaveLength(1);
  });

  it('needs a fixed-length interval', async () => {
    const { feed, requests } = recording(() => [bar(60), bar(120)]);
    const controller = make(feed, { refreshOnGap: true });
    await controller.load({ ...req, interval: 'not-an-interval' });
    controller.pushBar(bar(900));
    await settle();
    expect(requests).toHaveLength(1);
  });

  it('reaches back to the last bar the stream delivered, past a tail window', async () => {
    let answers: Bar[] = [bar(60), bar(120)];
    const { feed, requests } = recording(() => answers);
    const controller = make(feed, { refreshOnGap: true, refreshWindowBars: 1 });
    await controller.load(req);
    answers = [bar(60), bar(120), bar(180), bar(240), bar(300)];
    controller.pushBar(bar(300));
    await settle();
    expect(requests[1].from).toBe(120);
    expect(times(controller)).toEqual([60, 120, 180, 240, 300]);
  });

  it('is off by default', async () => {
    let answers: Bar[] = [bar(60), bar(120)];
    const { feed, requests } = recording(() => answers);
    const controller = make(feed);
    await controller.load(req);
    answers = [bar(60), bar(120), bar(180), bar(240), bar(300)];
    controller.pushBar(bar(300));
    await settle();
    expect(requests).toHaveLength(1);
    expect(times(controller)).toEqual([60, 120, 300]);
  });
});

describe('refreshWindowBars', () => {
  it('asks history for the tail only and leaves older bars alone', async () => {
    let answers: Bar[] = [bar(0), bar(60), bar(120), bar(180)];
    const { feed, requests } = recording(() => answers);
    const controller = make(feed, { refreshWindowBars: 1 });
    await controller.load(req);
    // History omits everything before the window; those bars must survive.
    answers = [bar(120, 111), bar(180)];
    await controller.refresh();
    expect(requests[1].from).toBe(120);
    expect(requests[1].to).toBe(190);
    expect(times(controller)).toEqual([0, 60, 120, 180]);
    expect(controller.bars()[2].close).toBe(111);
  });

  it('keeps the whole window without a fixed-length interval', async () => {
    const { feed, requests } = recording(() => [bar(0), bar(60), bar(120), bar(180)]);
    const controller = make(feed, { refreshWindowBars: 1 });
    await controller.load({ ...req, interval: 'not-an-interval' });
    await controller.refresh();
    expect(requests[1].from).toBe(0);
  });

  it('keeps the whole window by default', async () => {
    const { feed, requests } = recording(() => [bar(0), bar(60), bar(120), bar(180)]);
    const controller = make(feed);
    await controller.load(req);
    await controller.refresh();
    expect(requests[1].from).toBe(0);
  });
});

describe('provisional bars', () => {
  it('a provisional push keeps the open history holds for that bucket and widens the extremes', async () => {
    const { feed } = recording(() => [bar(60), bar(120, 104, 40, 100)]);
    const controller = make(feed);
    await controller.load(req);
    controller.pushBar({ time: 120, open: 103, high: 106, low: 103, close: 105, volume: 3 }, { provisional: true });
    expect(controller.bars()[1]).toEqual({ time: 120, open: 100, high: 106, low: 99, close: 105, volume: 40 });
  });

  it('a plain push still replaces the bar, as it always did', async () => {
    const { feed } = recording(() => [bar(60), bar(120, 104, 40, 100)]);
    const controller = make(feed);
    await controller.load(req);
    controller.pushBar({ time: 120, open: 103, high: 106, low: 103, close: 105, volume: 3 });
    expect(controller.bars()[1]).toEqual({ time: 120, open: 103, high: 106, low: 103, close: 105, volume: 3 });
  });

  it('a bucket history does not have yet keeps the provisional open until a refresh brings the true one', async () => {
    let answers: Bar[] = [bar(60)];
    const { feed } = recording(() => answers);
    const controller = make(feed);
    await controller.load(req);
    // Cold start mid-bucket: the first tick is all anyone knows about 120.
    controller.pushBar({ time: 120, open: 103, high: 103, low: 103, close: 103, volume: 1 }, { provisional: true });
    controller.pushBar({ time: 120, open: 103, high: 104, low: 103, close: 104, volume: 2 }, { provisional: true });
    expect(controller.bars()[1].open).toBe(103);
    // History catches up with the bucket's true open.
    answers = [bar(60), { time: 120, open: 100, high: 104, low: 99, close: 104, volume: 30 }];
    await controller.refresh();
    expect(controller.bars()[1]).toMatchObject({ open: 100, low: 99, volume: 30 });
    // The builder still believes in its first tick; the repair is not undone.
    controller.pushBar({ time: 120, open: 103, high: 105, low: 103, close: 105, volume: 3 }, { provisional: true });
    expect(controller.bars()[1]).toEqual({ time: 120, open: 100, high: 105, low: 99, close: 105, volume: 30 });
  });

  it('a refresh keeps the extremes the stream saw on the forming bar', async () => {
    let answers: Bar[] = [bar(60), bar(120)];
    const { feed } = recording(() => answers);
    const controller = make(feed);
    await controller.load(req);
    controller.pushBar({ time: 120, open: 100, high: 110, low: 90, close: 100, volume: 20 });
    // REST's snapshot of the forming bar predates the spike the stream showed.
    answers = [bar(60), { time: 120, open: 100, high: 102, low: 98, close: 101, volume: 25 }];
    await controller.refresh();
    expect(controller.bars()[1]).toEqual({ time: 120, open: 100, high: 110, low: 90, close: 101, volume: 25 });
  });
});
