/**
 * A refresh must not delete a bar the stream built and REST has not caught up to.
 *
 * On a one-minute chart at 11:26:00 the 11:25 candle closes. It was built from
 * live ticks and is on screen. The broker's REST history is a few seconds
 * behind, so a refresh that fires now returns everything up to 11:24 and no
 * 11:25. Treating that snapshot as authoritative for the whole window deletes
 * the candle the user just watched form, and it stays gone until a later
 * refresh finds it in REST. On screen: current candle becomes previous, then
 * vanishes, then backfills.
 *
 * Bars pushed while a refresh is in flight are already protected by the
 * buffer. The gap is bars that completed before the refresh started, which
 * live only in the held series and so are not in the buffer either.
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
const bar = (time: number, close = 23802, volume = 65): Bar =>
  ({ time, open: 23800, high: Math.max(23804, close), low: Math.min(23798, close), close, volume });
const req: BarsRequest = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m', from: 100, to: 300 };
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.useRealTimers(); });
function make(feed: DataFeed, options = {}) {
  const controller = new DataLoadingController(feed, { now: () => 300, ...options });
  cleanups.push(() => controller.destroy());
  return controller;
}

describe('a refresh against a lagging REST history', () => {
  it('keeps a bar the stream completed before the refresh started', async () => {
    // REST knows 100 and 200. It will still know only 100 and 200 when the
    // refresh asks again: the broker has not yet published the bar at 300.
    const controller = make({ getBars: async () => [bar(100), bar(200)] });
    await controller.load(req);

    // Live ticks complete the bar at 300 and it goes on screen.
    controller.pushBar(bar(300, 23810));
    expect(controller.bars().map(b => b.time)).toEqual([100, 200, 300]);

    // The repair poll fires. The window it repairs is [100, 300], which
    // contains the bar REST does not have.
    await controller.refresh();

    // The bar the user watched form must still be there. Deleting it because
    // a slower source has not mentioned it yet is the defect.
    expect(controller.bars().map(b => b.time)).toEqual([100, 200, 300]);
    expect(controller.bars()[2].close).toBe(23810);
  });

  it('keeps a bar the stream completes while the refresh is in flight', async () => {
    // The case the buffer already covers, kept beside the failing one so the
    // asymmetry is visible: same bar, same lagging REST, only the timing of
    // the push differs.
    const pending = deferred<Bar[]>();
    let calls = 0;
    const controller = make({
      getBars: async () => (++calls === 1 ? [bar(100), bar(200)] : pending.promise),
    });
    await controller.load(req);

    const work = controller.refresh();
    controller.pushBar(bar(300, 23810));
    pending.resolve([bar(100), bar(200)]);
    await work;

    expect(controller.bars().map(b => b.time)).toEqual([100, 200, 300]);
  });

  it('still lets REST correct a bar it does know about', async () => {
    // The refresh is not made blind. A bar REST returns is REST's to correct:
    // here it revises the close of 200, and the live-built bar at 300 that it
    // has not caught up to is left alone.
    let calls = 0;
    const controller = make({
      getBars: async () => (++calls === 1
        ? [bar(100), bar(200, 23802)]
        : [bar(100), bar(200, 23850)]),
    });
    await controller.load(req);
    controller.pushBar(bar(300, 23810));

    await controller.refresh();

    const times = controller.bars().map(b => b.time);
    expect(times).toEqual([100, 200, 300]);
    expect(controller.bars()[1].close).toBe(23850);
    expect(controller.bars()[2].close).toBe(23810);
  });
});
