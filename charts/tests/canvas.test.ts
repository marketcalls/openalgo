import { describe, it, expect } from 'vitest';
import { alignToDevicePixels, CanvasLayer, hairlineHeight } from '../src/core/canvas';
import { bitmapSize, snapToDevicePixel } from '../src/helpers/math';
import { fakeDocument } from './helpers/fake-dom';

/** Stacked boxes of the given heights, top to bottom. */
const stack = (heights: readonly number[]): { top: number; height: number }[] => {
  let top = 0;
  return heights.map((height) => { const box = { top, height }; top += height; return box; });
};
/** Whether a media coordinate lands on a device pixel. */
const onDevicePixel = (media: number, dpr: number): boolean => Math.abs(media * dpr - Math.round(media * dpr)) < 1e-9;

describe('HiDPI bitmap sizing', () => {
  // Validates "renders correctly at DPR 1 / 1.5 / 2 / 3" at the math level
  // (actual pixel-diff rendering is covered by the browser harness in Phase 2-3).
  it('scales media to integer device pixels across DPRs', () => {
    expect(bitmapSize(800, 600, 1)).toEqual({ width: 800, height: 600 });
    expect(bitmapSize(800, 600, 2)).toEqual({ width: 1600, height: 1200 });
    expect(bitmapSize(800, 600, 3)).toEqual({ width: 2400, height: 1800 });
  });

  it('rounds fractional DPR to whole device pixels', () => {
    // 1.5x of an odd media size must not leave a fractional backing buffer.
    expect(bitmapSize(801, 601, 1.5)).toEqual({ width: 1202, height: 902 });
    expect(Number.isInteger(bitmapSize(123, 457, 1.25).width)).toBe(true);
    expect(Number.isInteger(bitmapSize(123, 457, 1.25).height)).toBe(true);
  });

  it('snaps coordinates to crisp device-pixel edges', () => {
    expect(snapToDevicePixel(10.4, 1)).toBe(10);
    expect(snapToDevicePixel(10.2, 2)).toBe(10); // 20.4 rounds to 20, then /2
    expect(snapToDevicePixel(10.3, 2)).toBe(10.5); // 20.6 rounds to 21, then /2
  });
});

describe('pane boundaries on device pixels', () => {
  // A price pane over two studies at the weights the chart gives them, in a
  // chart whose height splits into fractions of a pixel at every ratio.
  const shares = [344 / 1.64, (344 * 0.32) / 1.64, (344 * 0.32) / 1.64];

  it('moves every boundary between boxes onto a device pixel', () => {
    for (const dpr of [1, 1.25, 1.5, 2, 3]) {
      const out = alignToDevicePixels(stack(shares), dpr);
      for (const box of out.slice(1)) expect(onDevicePixel(box.top, dpr), `top ${box.top} at ${dpr}`).toBe(true);
      // So each box but the last is a whole number of device pixels tall.
      for (const box of out.slice(0, -1)) expect(onDevicePixel(box.height, dpr), `height ${box.height} at ${dpr}`).toBe(true);
    }
  });

  it('keeps each boundary within half a device pixel of its share and the outer edges where they were', () => {
    for (const dpr of [1, 1.25, 1.5, 2]) {
      const before = stack(shares);
      const out = alignToDevicePixels(before, dpr);
      out.forEach((box, i) => expect(Math.abs(box.top - before[i].top)).toBeLessThanOrEqual(0.5 / dpr + 1e-9));
      expect(out[0].top).toBe(0);
      const last = out[out.length - 1];
      expect(last.top + last.height).toBeCloseTo(344, 9);
      // Nothing overlaps and nothing is left between the boxes.
      out.slice(1).forEach((box, i) => expect(box.top).toBeCloseTo(out[i].top + out[i].height, 9));
    }
  });

  it('rounds the running total, so a long stack does not drift', () => {
    const many = Array.from({ length: 200 }, () => 5.3);
    const out = alignToDevicePixels(stack(many), 1.5);
    // Rounding each height alone would put the last box 20 px off; this keeps it within half a device pixel.
    expect(Math.abs(out[199].top - 199 * 5.3)).toBeLessThanOrEqual(0.5 / 1.5 + 1e-9);
  });

  it('leaves a box with no share at no height, where a hidden pane sits', () => {
    const out = alignToDevicePixels(stack([0, 250.4, 0, 99.6]), 1.25);
    expect(out[0].height).toBe(0);
    expect(out[2].height).toBe(0);
    expect(out[2].top).toBe(out[1].top + out[1].height);
    expect(out[3].top + out[3].height).toBeCloseTo(350, 9);
  });

  it('hands back the boxes unchanged for a ratio it cannot use', () => {
    const before = stack(shares);
    for (const dpr of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) expect(alignToDevicePixels(before, dpr)).toEqual(before);
    expect(alignToDevicePixels([], 1.5)).toEqual([]);
  });
});

describe('the separator hairline', () => {
  it('is a whole number of device pixels, at least one', () => {
    for (const dpr of [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3]) {
      const css = hairlineHeight(dpr);
      expect(onDevicePixel(css, dpr), `at ${dpr}`).toBe(true);
      expect(Math.round(css * dpr)).toBeGreaterThanOrEqual(1);
    }
  });

  it('stays the 1 px it always was at whole ratios, and is one device pixel between them', () => {
    expect([1, 2, 3].map(hairlineHeight)).toEqual([1, 1, 1]);
    expect(hairlineHeight(1.25)).toBeCloseTo(0.8, 12);
    expect(hairlineHeight(1.5)).toBeCloseTo(2 / 3, 12);
    expect(hairlineHeight(Number.NaN)).toBe(1);
  });
});

describe('a canvas sized from the device-pixel box the browser reports', () => {
  const layer = (): CanvasLayer => new CanvasLayer(fakeDocument(), 0);

  it('takes a box the browser snapped a pixel narrower than media times ratio, and says it changed', () => {
    const canvas = layer();
    canvas.resize(560.5, 340, 1);
    expect(canvas.element.width).toBe(561);
    expect(canvas.setDeviceSize(560, 340)).toBe(true);
    expect([canvas.element.width, canvas.element.height]).toEqual([560, 340]);
    // The same report again changes nothing, so nothing needs painting.
    expect(canvas.setDeviceSize(560, 340)).toBe(false);
    // The media size and the ratio the drawing code scales by are untouched.
    expect([canvas.mediaWidth, canvas.mediaHeight, canvas.pixelRatio]).toEqual([560.5, 340, 1]);
  });

  it('refuses a report at another scale, the way an emulated device ratio reports the box', () => {
    const canvas = layer();
    canvas.resize(300, 200, 1.5);
    expect(canvas.setDeviceSize(300, 200)).toBe(false);
    expect([canvas.element.width, canvas.element.height]).toEqual([450, 300]);
  });

  it('keeps the reported box through a resize that leaves it the same, which the browser does not report again', () => {
    // A box half a pixel in: 560.5 px covers 560 device pixels, reported once.
    const canvas = layer();
    canvas.resize(560.5, 340, 1);
    canvas.setDeviceSize(560, 340);
    // A tenth of a pixel wider still covers the same 560: the browser says
    // nothing, so the store must not fall back to 561 and be stretched.
    canvas.resize(560.6, 340, 1);
    expect([canvas.element.width, canvas.element.height]).toEqual([560, 340]);
    canvas.resize(560.5, 340, 1);
    expect([canvas.element.width, canvas.element.height]).toEqual([560, 340]);
    // A change the box cannot have absorbed is estimated until the browser reports it.
    canvas.resize(700.4, 340, 1);
    expect([canvas.element.width, canvas.element.height]).toEqual([700, 340]);
    canvas.setDeviceSize(701, 340);
    expect(canvas.element.width).toBe(701);
  });

  it('drops the reported box on a whole-pixel resize, so the store is the new size at once', () => {
    // 800 px at ratio 1 covers 800 device pixels, reported once. 801 px can
    // only cover 801: keeping the 800 would paint into the wrong store and
    // leave the browser's report of 801 to clear it and paint it all again.
    const canvas = layer();
    canvas.resize(800, 600, 1);
    canvas.setDeviceSize(800, 600);
    canvas.resize(801, 600, 1);
    expect([canvas.element.width, canvas.element.height]).toEqual([801, 600]);
    expect(canvas.setDeviceSize(801, 600)).toBe(false);
    // The same a pixel down, and on the other axis.
    canvas.resize(801, 599, 1);
    expect([canvas.element.width, canvas.element.height]).toEqual([801, 599]);
    // At ratio 2 a half-pixel step is one device pixel, which no snapped box absorbs.
    canvas.resize(400, 300, 2);
    canvas.setDeviceSize(800, 600);
    canvas.resize(400.5, 300, 2);
    expect(canvas.element.width).toBe(801);
  });

  it('stops trusting the box once a report is refused, and estimates again', () => {
    const canvas = layer();
    canvas.resize(560.5, 340, 1);
    canvas.setDeviceSize(560, 340);
    // A report at another scale, the way an emulated device ratio reports it.
    expect(canvas.setDeviceSize(1121, 680)).toBe(false);
    canvas.resize(560.6, 340, 1);
    expect(canvas.element.width).toBe(561);
  });

  it('refuses sizes that are not whole pixels or are empty', () => {
    const canvas = layer();
    canvas.resize(100, 100, 1);
    for (const [w, h] of [[99.5, 100], [0, 100], [100, -1], [Number.NaN, 100]]) expect(canvas.setDeviceSize(w, h)).toBe(false);
    expect(canvas.element.width).toBe(100);
  });
});
