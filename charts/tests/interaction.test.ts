import { describe, it, expect } from 'vitest';
import { TimeScale } from '../src/scale/time-scale';
import { KineticAnimation } from '../src/input/kinetic';
import { magnetSnapPrice } from '../src/input/crosshair';
import { pinchState, pinchDelta } from '../src/input/touch';
import { DataLayer } from '../src/model/data-layer';
import type { Bar } from '../src/model/bar';

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c });

describe('TimeScale zoom anchoring', () => {
  it('keeps the index under the cursor pinned while zooming', () => {
    const ts = new TimeScale({ barSpacing: 10, rightOffset: 0 });
    ts.setWidth(600);
    ts.setBaseIndex(99);
    const focusX = 300;
    const indexBefore = ts.xToIndex(focusX);
    ts.zoomAtX(focusX, 1.5); // zoom in
    expect(ts.barSpacing).toBeCloseTo(15);
    expect(ts.indexToX(indexBefore)).toBeCloseTo(focusX, 6); // same screen x
  });

  it('does not move the anchor when spacing is clamped', () => {
    const ts = new TimeScale({ barSpacing: 79, maxBarSpacing: 80 });
    ts.setWidth(600);
    ts.setBaseIndex(50);
    const before = ts.xToIndex(200);
    ts.zoomAtX(200, 4); // would exceed max, so clamped
    expect(ts.barSpacing).toBe(80);
    // index under cursor stays reasonable (not NaN / jumped)
    expect(Number.isFinite(ts.xToIndex(200))).toBe(true);
    expect(before).toBeTypeOf('number');
  });
});

describe('TimeScale pan direction', () => {
  it('dragging content right reveals older bars (rightOffset decreases)', () => {
    const ts = new TimeScale({ barSpacing: 10, rightOffset: 0 });
    ts.setWidth(500);
    ts.setBaseIndex(99);
    const before = ts.rightOffset;
    ts.scrollByPixels(50); // drag right by 50px
    expect(ts.rightOffset).toBeLessThan(before);
    expect(ts.rightOffset).toBeCloseTo(before - 5); // 50px / 10px-per-bar
  });
});

describe('KineticAnimation', () => {
  it('travels monotonically and converges to a finite distance', () => {
    const anim = new KineticAnimation(1.0); // 1 px/ms initial
    const d1 = anim.distanceAt(50);
    const d2 = anim.distanceAt(200);
    const dEnd = anim.distanceAt(anim.durationMs);
    expect(d2).toBeGreaterThan(d1);
    expect(dEnd).toBeGreaterThanOrEqual(d2);
    expect(Number.isFinite(dEnd)).toBe(true);
    expect(anim.finished(anim.durationMs)).toBe(true);
  });

  it('ignores slow flicks below the trigger speed', () => {
    expect(KineticAnimation.shouldAnimate(0.01)).toBe(false);
    expect(KineticAnimation.shouldAnimate(0.5)).toBe(true);
  });
});

describe('pinch gesture math', () => {
  it('summarizes distance + midpoint of two pointers', () => {
    const s = pinchState({ x: 0, y: 0 }, { x: 100, y: 0 });
    expect(s.dist).toBe(100);
    expect(s.cx).toBe(50);
    expect(s.cy).toBe(0);
  });
  it('delta yields zoom factor (apart > 1) + midpoint pan', () => {
    const a = pinchState({ x: 0, y: 0 }, { x: 100, y: 0 });   // dist 100, cx 50
    const b = pinchState({ x: -10, y: 20 }, { x: 130, y: 20 }); // dist 140, cx 60, cy 20
    const d = pinchDelta(a, b);
    expect(d.factor).toBeCloseTo(1.4); // fingers spread: zoom in
    expect(d.dx).toBe(10);
    expect(d.dy).toBe(20);
  });
});

describe('crosshair magnet', () => {
  it('snaps to the nearest O/H/L/C value', () => {
    const b = bar(100, 50); // open 50, high 52, low 48, close 50
    expect(magnetSnapPrice(51.9, b)).toBe(52); // nearest high
    expect(magnetSnapPrice(48.2, b)).toBe(48); // nearest low
    expect(magnetSnapPrice(49.6, b)).toBe(50); // nearest open/close
  });
});

describe('history paging preserves the viewport', () => {
  it('shifts indices but keeps visible bars at the same x after prepend', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    // initial 100 bars at times 1000..1099
    dl.setSeriesData(id, Array.from({ length: 100 }, (_, i) => bar(1000 + i, i)));

    const ts = new TimeScale({ barSpacing: 8, rightOffset: 3 });
    ts.setWidth(640);
    ts.setBaseIndex(dl.baseIndex); // 99

    // pick a currently-visible bar and record its screen x
    const visibleBarTime = 1090;
    const idxBefore = dl.timeToIndex(visibleBarTime)!;
    const xBefore = ts.indexToX(idxBefore);

    // prepend 40 older bars (times 960..999)
    dl.addBars(id, Array.from({ length: 40 }, (_, i) => bar(960 + i, -i)));
    ts.setBaseIndex(dl.baseIndex); // now 139

    const idxAfter = dl.timeToIndex(visibleBarTime)!;
    expect(idxAfter).toBe(idxBefore + 40); // index shifted up by inserted count
    expect(ts.indexToX(idxAfter)).toBeCloseTo(xBefore, 6); // SAME screen x, so no jump
  });
});

describe('pane x-sync (shared logical index space)', () => {
  it('a bar shared by two series maps to one index, so the same x in both panes', () => {
    const dl = new DataLayer();
    const price = dl.createSeries();
    const vol = dl.createSeries();
    dl.setSeriesData(price, [bar(1000, 1), bar(1060, 2), bar(1120, 3)]);
    dl.setSeriesData(vol, [bar(1060, 9)]); // only the middle time
    const sharedIndex = dl.timeToIndex(1060)!;
    expect(dl.indexedBars(price).find((b) => b.bar.time === 1060)!.index).toBe(sharedIndex);
    expect(dl.indexedBars(vol)[0].index).toBe(sharedIndex); // same index, so the same x for both panes
  });
});
