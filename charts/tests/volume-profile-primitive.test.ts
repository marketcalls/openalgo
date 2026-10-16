import { describe, it, expect } from 'vitest';
import { VolumeProfile } from '../src/profile/volume-profile-primitive';
import { computeVolumeProfileSessions } from '../src/profile/volume-profile-family';
import { istStringToUtcSeconds } from '../src/feed/time';
import type { Bar } from '../src/model/bar';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const bar = (time: number, low: number, high: number, open: number, close: number, volume: number): Bar =>
  ({ time, low, high, open, close, volume });

function makeResult() {
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');
  const bars = [
    bar(t0, 100, 103, 100, 103, 300),
    bar(t0 + 1800, 101, 104, 104, 101, 200),
  ];
  return { result: computeVolumeProfileSessions(bars, { tickSize: 1, session: 'composite' }), t0 };
}

function recorder() {
  const calls = { fillRect: 0, fillText: 0, stroke: 0 };
  const ctx = {
    canvas: {}, globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {},
    stroke() { calls.stroke++; }, fillRect() { calls.fillRect++; }, fillText() { calls.fillText++; },
  } as unknown as CanvasRenderingContext2D;
  return { ctx, calls };
}

function makeRc(startTime: number, endTime: number): PrimitiveRenderContext {
  return {
    dpr: 2, plotWidth: 600, plotHeight: 300, priceAxisWidth: 60,
    timeScale: { indexToX: (i: number) => 100 + i * 40 },
    priceScale: { priceToY: (p: number) => 400 - p, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndex: (t: number) => (t === startTime ? 0 : t === endTime ? 5 : 5) },
    theme: {},
  } as unknown as PrimitiveRenderContext;
}

describe('VolumeProfile primitive', () => {
  it('draws histogram bars and POC/VA lines (total mode)', () => {
    const { result, t0 } = makeResult();
    const vp = new VolumeProfile(result);
    const { ctx, calls } = recorder();
    vp.draw(ctx, makeRc(t0, t0 + 1800));
    expect(calls.fillRect).toBeGreaterThan(0);
    expect(calls.stroke).toBeGreaterThan(0);
    expect(calls.fillText).toBeGreaterThan(0);
  });

  it('renders buy/sell split (two rects per non-empty row)', () => {
    const { result, t0 } = makeResult();
    const total = new VolumeProfile(result, { displayMode: 'total', showPoc: false, showValueArea: false, highlightValueArea: false });
    const split = new VolumeProfile(result, { displayMode: 'buySell', showPoc: false, showValueArea: false, highlightValueArea: false });
    const a = recorder(); total.draw(a.ctx, makeRc(t0, t0 + 1800));
    const c = recorder(); split.draw(c.ctx, makeRc(t0, t0 + 1800));
    expect(c.calls.fillRect).toBeGreaterThan(a.calls.fillRect); // split adds a second segment per row
  });

  it('reports price extent and is a no-op with no data', () => {
    const { result } = makeResult();
    expect(new VolumeProfile(result).autoscaleInfo()).toEqual({ min: 100, max: 104 });
    const empty = new VolumeProfile(null);
    const { ctx, calls } = recorder();
    empty.draw(ctx, makeRc(0, 1));
    expect(calls.fillRect + calls.stroke + calls.fillText).toBe(0);
    expect(empty.autoscaleInfo()).toBeNull();
  });
});
