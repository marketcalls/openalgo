/**
 * `SeriesStyle` is one flat optional-field bag shared by every Family-A
 * renderer, which makes it the easiest place in the codebase for a field to be
 * declared, shipped in the public `.d.ts`, and read by nothing. Three were:
 * `highColor` and `lowColor` named the two edges of an HLC area's band that no
 * renderer ever stroked, and `volumeScaled` had been superseded by the
 * `volume-candle` chart type, which scales bodies from `rc.maxVolume` whatever
 * the flag said. `volumeScaled` is gone; the two edge colours are consumed here.
 *
 * The last case is the one that keeps the fix additive: an HLC area is a filled
 * band plus a close line, and a caller who names neither edge must get the
 * frame it has always got.
 */
import { describe, it, expect } from 'vitest';
import { drawHlcArea, type LineDrawItem } from '../src/render/line';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

const BARS: Bar[] = Array.from({ length: 6 }, (_, i) => ({
  time: 1700000000 + i * 60,
  open: 100 + i, high: 103 + i, low: 97 + i, close: 101 + i, volume: 10,
}));
const ITEMS: LineDrawItem[] = BARS.map((bar, i) => ({ x: 10 + i * 10, bar }));
const toY = (v: number): number => 300 - v;

const draw = (style: Parameters<typeof drawHlcArea>[4]): RecordingContext => {
  const rec = new RecordingContext();
  drawHlcArea(rec as unknown as CanvasRenderingContext2D, ITEMS, toY, 1, style);
  return rec;
};

/** Every stroke colour the op stream carries, in order. */
const strokes = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'stroke').map((o) => o.strokeStyle ?? '');

describe('the HLC band edges are drawn, not just declared', () => {
  it('strokes the high edge in highColor and the low edge in lowColor', () => {
    // Three strokes: high edge, low edge, close line, in that order.
    expect(strokes(draw({ highColor: '#111111', lowColor: '#222222', closeColor: '#333333' })))
      .toEqual(['#111111', '#222222', '#333333']);
  });

  it('traces the high edge through the highs and the low edge through the lows', () => {
    // A copy-paste that stroked the highs twice would pass a colour-only
    // assertion, so check each polyline actually starts on its own series.
    const moves = draw({ highColor: '#111111', lowColor: '#222222' })
      .ops.filter((o) => o.type === 'moveTo').map((o) => o.args[1]);
    expect(moves).toContain(toY(BARS[0].high));
    expect(moves).toContain(toY(BARS[0].low));
  });

  it('leaves the frame untouched for a caller that names neither colour', () => {
    // The band is a fill and an unnamed edge is not invented: this is what
    // keeps the change additive for every existing hlc-area caller.
    expect(strokes(draw({ closeColor: '#333333' }))).toEqual(['#333333']);
  });

  it('honours one edge without the other', () => {
    expect(strokes(draw({ lowColor: '#222222', closeColor: '#333333' })))
      .toEqual(['#222222', '#333333']);
  });
});
