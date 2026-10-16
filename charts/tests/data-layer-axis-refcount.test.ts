/**
 * The shared time axis kept in step with its series (src/model/data-layer.ts).
 *
 * Every series on a chart shares one logical-index axis, the union of their
 * times. 2.5.8 already kept that axis when a whole write left the set of
 * times alone or only added times past the right edge. Every other change
 * rebuilt it from every series' bars: a series dropping a time (it could not
 * tell whether another series still held it), a time added inside the axis,
 * `addBars`, an insert through `update`, and `removeSeries`. A host with a
 * dozen studies on a long history paid for the whole chart each time one
 * series moved a bar.
 *
 * The axis now counts how many series hold each time, so any write costs the
 * series written and nothing else. That is what the reads test pins: it
 * counts every read of another series' bar times, and each of those changes
 * read all of them before the counts.
 */
import { describe, it, expect } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import type { Bar } from '../src/model/bar';

const bar = (time: number, c = 100): Bar => ({ time, open: c, high: c + 1, low: c - 1, close: c });

/** The axis as the union of every series' times, computed the obvious way. */
function expectedAxis(series: Map<number, Bar[]>): number[] {
  const times = new Set<number>();
  for (const bars of series.values()) for (const b of bars) times.add(b.time);
  return Array.from(times).sort((a, b) => a - b);
}

function expectAxis(dl: DataLayer, series: Map<number, Bar[]>): void {
  const want = expectedAxis(series);
  expect(dl.length).toBe(want.length);
  for (let i = 0; i < want.length; i++) {
    expect(dl.indexToTime(i)).toBe(want[i]);
    expect(dl.timeToIndex(want[i])).toBe(i);
  }
  for (const [id, bars] of series) {
    expect(dl.seriesBars(id).map((b) => b.time)).toEqual(bars.map((b) => b.time));
  }
}

/** A small deterministic generator, so a failure replays exactly. */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

describe('data layer time axis', () => {
  it('matches the union of its series through any sequence of edits', () => {
    for (const seed of [1, 2, 3, 4, 5]) {
      const r = rng(seed);
      const pick = (n: number): number => Math.floor(r() * n);
      const dl = new DataLayer();
      // What each series should hold, mirrored with the layer's own rules:
      // sorted, one bar per time, the later bar winning.
      const mirror = new Map<number, Bar[]>();
      const upsert = (list: Bar[], add: Bar[]): Bar[] => {
        const byTime = new Map<number, Bar>();
        for (const b of list) byTime.set(b.time, b);
        for (const b of add) byTime.set(b.time, b);
        return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
      };
      const randomBars = (): Bar[] => {
        const out: Bar[] = [];
        const n = pick(30);
        for (let k = 0; k < n; k++) out.push(bar(pick(60) * 10));
        return out;
      };
      for (let step = 0; step < 400; step++) {
        const ids = Array.from(mirror.keys());
        const op = ids.length === 0 ? 0 : pick(6);
        if (op === 0) {
          const id = dl.createSeries();
          const bars = randomBars();
          dl.setSeriesData(id, bars);
          mirror.set(id, upsert([], bars));
        } else if (op === 1) {
          const id = ids[pick(ids.length)];
          // Often the same times again, the refresh this change is for.
          const bars = r() < 0.5 ? mirror.get(id)!.map((b) => bar(b.time, 101)) : randomBars();
          dl.setSeriesData(id, bars);
          mirror.set(id, upsert([], bars));
        } else if (op === 2) {
          const id = ids[pick(ids.length)];
          const bars = randomBars();
          dl.addBars(id, bars);
          mirror.set(id, upsert(mirror.get(id)!, bars));
        } else if (op === 3 || op === 4) {
          // A live bar: past the end, on the last bar, or into history.
          const id = ids[pick(ids.length)];
          const list = mirror.get(id)!;
          const last = list[list.length - 1]?.time ?? 0;
          const time = op === 3 ? last + pick(3) * 10 : pick(70) * 10;
          dl.update(id, bar(time));
          mirror.set(id, upsert(list, [bar(time)]));
        } else {
          const id = ids[pick(ids.length)];
          dl.removeSeries(id);
          mirror.delete(id);
        }
        expectAxis(dl, mirror);
      }
    }
  });

  it('changes the axis by reading only the series written, never the others', () => {
    let reads = 0;
    /** A bar whose time counts its reads: the other series' bars are built from these. */
    const counted = (time: number): Bar => {
      const b = bar(time);
      Object.defineProperty(b, 'time', { get: () => { reads++; return time; }, enumerable: true });
      return b;
    };
    const n = 2_000;
    /** Six series on one-minute bars, a plain series of our own on the same bars plus a few half-minutes, and a spare. */
    const setup = (): { dl: DataLayer; mine: number; spare: number } => {
      const dl = new DataLayer();
      for (let s = 0; s < 6; s++) dl.setSeriesData(dl.createSeries(), Array.from({ length: n }, (_, i) => counted(i * 60)));
      const mine = dl.createSeries();
      dl.setSeriesData(mine, own());
      const spare = dl.createSeries();
      dl.setSeriesData(spare, [bar(30_030)]);
      reads = 0;
      return { dl, mine, spare };
    };
    const own = (): Bar[] => {
      const out = Array.from({ length: n }, (_, i) => bar(i * 60, 100 + i));
      for (const i of [300, 900, 1500]) out.push(bar(i * 60 + 30));
      return out.sort((a, b) => a.time - b.time);
    };
    const times = (dl: DataLayer): number[] => Array.from({ length: dl.length }, (_, i) => dl.indexToTime(i) as number);

    const cases: [string, (dl: DataLayer, mine: number, spare: number) => void, (axis: number[]) => void][] = [
      ['re-sending the same times', (dl, mine) => dl.setSeriesData(mine, own()), (axis) => expect(axis.length).toBe(n + 4)],
      ['dropping a time other series hold', (dl, mine) => dl.setSeriesData(mine, own().filter((b) => b.time !== 600 * 60)),
        (axis) => expect(axis).toContain(600 * 60)],
      ['dropping a time no other series holds', (dl, mine) => dl.setSeriesData(mine, own().filter((b) => b.time !== 900 * 60 + 30)),
        (axis) => expect(axis).not.toContain(900 * 60 + 30)],
      ['adding a time inside the axis', (dl, mine) => dl.setSeriesData(mine, [...own(), bar(1200 * 60 + 30)]),
        (axis) => expect(axis).toContain(1200 * 60 + 30)],
      ['adding bars inside the axis', (dl, mine) => dl.addBars(mine, [bar(700 * 60 + 15), bar(701 * 60 + 15)]),
        (axis) => expect(axis).toContain(701 * 60 + 15)],
      ['a live bar landing in history', (dl, mine) => { dl.update(mine, bar(800 * 60 + 45)); },
        (axis) => expect(axis).toContain(800 * 60 + 45)],
      ['removing a series', (dl, _mine, spare) => dl.removeSeries(spare), (axis) => expect(axis).not.toContain(30_030)],
    ];
    for (const [label, write, check] of cases) {
      const { dl, mine, spare } = setup();
      write(dl, mine, spare);
      const counts = reads;
      const axis = times(dl);
      check(axis);
      // Sorted and unique: the axis came out as a rebuild would have made it.
      for (let i = 1; i < axis.length; i++) expect(axis[i], label).toBeGreaterThan(axis[i - 1]);
      expect(counts, `${label}: read ${counts} bar times of the other series`).toBe(0);
    }
  });

  it('keeps indices before a change and drops a time no series holds', () => {
    const dl = new DataLayer();
    const a = dl.createSeries();
    const b = dl.createSeries();
    dl.setSeriesData(a, [bar(10), bar(20), bar(30)]);
    dl.setSeriesData(b, [bar(20), bar(40)]);
    expect([0, 1, 2, 3].map((i) => dl.indexToTime(i))).toEqual([10, 20, 30, 40]);

    // 40 is held only by b; 20 by both.
    dl.setSeriesData(b, [bar(20)]);
    expect(dl.length).toBe(3);
    expect(dl.timeToIndex(40)).toBeUndefined();
    expect(dl.timeToIndex(30)).toBe(2);

    dl.removeSeries(a);
    expect(dl.length).toBe(1);
    expect(dl.timeToIndex(20)).toBe(0);
    expect(dl.timeToIndex(10)).toBeUndefined();
  });
});
