import { describe, it, expect } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import type { Bar } from '../src/model/bar';

const bar = (time: number, close: number): Bar => ({
  time, open: close, high: close + 1, low: close - 1, close,
});

describe('DataLayer', () => {
  it('assigns logical indices to a single series and collapses to length', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [bar(300, 10), bar(100, 8), bar(200, 9)]); // unsorted input
    expect(dl.length).toBe(3);
    expect(dl.baseIndex).toBe(2);
    // sorted by time: indices 0,1,2 at times 100,200,300
    expect(dl.indexToTime(0)).toBe(100);
    expect(dl.timeToIndex(300)).toBe(2);
    const ib = dl.indexedBars(id);
    expect(ib.map((x) => x.index)).toEqual([0, 1, 2]);
    expect(ib.map((x) => x.bar.close)).toEqual([8, 9, 10]); // re-sorted
  });

  it('merges two series onto one shared index space (alignment)', () => {
    const dl = new DataLayer();
    const price = dl.createSeries();
    const vol = dl.createSeries();
    dl.setSeriesData(price, [bar(100, 1), bar(200, 2), bar(300, 3)]);
    dl.setSeriesData(vol, [bar(200, 5), bar(400, 6)]); // 400 is new, 100/300 absent here
    // union of times: 100,200,300,400, so 4 indices
    expect(dl.length).toBe(4);
    expect(dl.timeToIndex(400)).toBe(3);
    // the volume bar at time 200 must share index 1 with the price bar at 200
    expect(dl.timeToIndex(200)).toBe(1);
    const volIndexed = dl.indexedBars(vol);
    expect(volIndexed.find((x) => x.bar.time === 200)?.index).toBe(1);
    expect(volIndexed.find((x) => x.bar.time === 400)?.index).toBe(3);
    // gaps are implicit: vol has no bar at index 0 or 2 (whitespace, not drawn)
    expect(volIndexed.map((x) => x.index)).toEqual([1, 3]);
  });

  it('returns only bars within a visible index window', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [bar(100, 1), bar(200, 2), bar(300, 3), bar(400, 4), bar(500, 5)]);
    const vis = dl.visibleBars(id, 1, 3);
    expect(vis.map((x) => x.bar.close)).toEqual([2, 3, 4]);
  });

  it('clamps visible window to data bounds', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [bar(100, 1), bar(200, 2)]);
    const vis = dl.visibleBars(id, -10, 99);
    expect(vis).toHaveLength(2);
  });
});
