/**
 * Candle level-of-detail (§6). The `wick` tier drops the body fill once the
 * body can only repaint what the wick already covered.
 *
 * The load-bearing claim is that the tier is an optimisation and NOT a visual
 * change, so the tests here rasterise the recorded ops onto a pixel grid and
 * compare the result against the pre-LOD op stream (wick, then body, then
 * border) rather than merely counting calls. A tier that skipped a body which
 * was actually visible would show up as a differing cell.
 */
import { describe, it, expect } from 'vitest';
import { drawCandles, candleTier, optimalBarWidth, type CandleDrawItem, type CandleStyle } from '../src/render/candles';
import type { Bar } from '../src/model/bar';
import { makeCtx, type Op } from './helpers/fake-ctx';

const DPR = 1;
const WICK_W = 1; // Math.max(1, Math.floor(DPR))

/** Body and wick share a colour, which is what lets the body be skipped. */
const FLAT: CandleStyle = {
  upColor: '#11aa11',
  downColor: '#aa1111',
  borderUpColor: '#11aa11',
  borderDownColor: '#aa1111',
  wickUpColor: '#11aa11',
  wickDownColor: '#aa1111',
  borderVisible: false,
  wickVisible: true,
};

const bar = (o: number, h: number, l: number, c: number): Bar => ({ time: 0, open: o, high: h, low: l, close: c });

const ITEMS: CandleDrawItem[] = [
  { x: 4, bar: bar(10, 14, 9, 12) },   // up
  { x: 8, bar: bar(12, 13, 6, 7) },    // down
  { x: 12, bar: bar(8, 8, 8, 8) },     // flat: high == low == open == close
];

const priceToY = (p: number): number => 40 - p * 2;

/** Replay fillRect / strokeRect ops onto a sparse pixel grid: `"x,y" -> colour`. */
function raster(ops: readonly Op[]): Map<string, string> {
  const grid = new Map<string, string>();
  for (const op of ops) {
    if (op.type !== 'fillRect') continue;
    const [x, y, w, h] = op.args;
    for (let px = x; px < x + w; px++) {
      for (let py = y; py < y + h; py++) grid.set(`${px},${py}`, op.fillStyle ?? '');
    }
  }
  return grid;
}

/**
 * The op stream 1.9.2 produced: the wick, then the body unconditionally. This
 * is the reference the LOD output must match pixel for pixel.
 */
function rasterPreLod(items: readonly CandleDrawItem[], barSpacing: number, style: CandleStyle): Map<string, string> {
  const bodyW = optimalBarWidth(barSpacing, DPR);
  const wickW = Math.max(1, Math.floor(DPR));
  const grid = new Map<string, string>();
  const paint = (x: number, y: number, w: number, h: number, color: string): void => {
    for (let px = x; px < x + w; px++) for (let py = y; py < y + h; py++) grid.set(`${px},${py}`, color);
  };
  for (const { x, bar: b } of items) {
    const up = b.close >= b.open;
    const cx = Math.round(x * DPR);
    const yHigh = Math.round(priceToY(b.high) * DPR);
    const yLow = Math.round(priceToY(b.low) * DPR);
    const yOpen = Math.round(priceToY(b.open) * DPR);
    const yClose = Math.round(priceToY(b.close) * DPR);
    paint(cx - Math.floor(wickW / 2), yHigh, wickW, Math.max(1, yLow - yHigh), up ? style.wickUpColor : style.wickDownColor);
    paint(cx - Math.floor(bodyW / 2), Math.min(yOpen, yClose), bodyW, Math.max(1, Math.abs(yClose - yOpen)), up ? style.upColor : style.downColor);
  }
  return grid;
}

describe('candleTier', () => {
  it('drops the body once it is no wider than the wick and shares its colour', () => {
    expect(candleTier(1, 1, FLAT)).toBe('wick');
  });

  it('keeps the body while it is wider than the wick', () => {
    expect(candleTier(2, 1, FLAT)).toBe('full');
  });

  it('keeps the body when it is painted a different colour from the wick', () => {
    expect(candleTier(1, 1, { ...FLAT, upColor: '#ffffff' })).toBe('full');
    expect(candleTier(1, 1, { ...FLAT, downColor: '#ffffff' })).toBe('full');
  });

  it('keeps a hollow candle, whose outline is the candle', () => {
    expect(candleTier(1, 1, { ...FLAT, hollow: true })).toBe('full');
  });

  it('keeps the body when there is no wick to hide behind', () => {
    expect(candleTier(1, 1, { ...FLAT, wickVisible: false })).toBe('full');
  });

  it('keeps a border that is wide enough to survive the 3px guard', () => {
    expect(candleTier(3, 3, { ...FLAT, borderVisible: true })).toBe('full');
    // Below the guard drawCandles drops the border anyway, so there is nothing
    // the body could be hiding under.
    expect(candleTier(1, 1, { ...FLAT, borderVisible: true })).toBe('wick');
  });

  it('leaves a body-less candle alone: there is nothing to skip', () => {
    expect(candleTier(1, 1, { ...FLAT, bodyVisible: false })).toBe('full');
  });
});

describe('drawCandles at the wick tier', () => {
  // Bar spacing that collapses the body onto the wick: optimalBarWidth matches
  // parity with the 1px wick, so a 2px raw body is shaved back to 1px.
  const TIGHT = 2;

  it('collapses the body onto the wick at this spacing', () => {
    expect(optimalBarWidth(TIGHT, DPR)).toBe(WICK_W);
    expect(candleTier(optimalBarWidth(TIGHT, DPR), WICK_W, FLAT)).toBe('wick');
  });

  it('paints exactly the pixels the pre-LOD path painted', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, ITEMS, priceToY, TIGHT, DPR, FLAT);
    expect(raster(rec.ops)).toEqual(rasterPreLod(ITEMS, TIGHT, FLAT));
  });

  it('does the work in one fill per candle instead of two', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, ITEMS, priceToY, TIGHT, DPR, FLAT);
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(ITEMS.length);
  });

  it('still paints both fills, and the same pixels, once the body is visible', () => {
    const WIDE = 8;
    expect(candleTier(optimalBarWidth(WIDE, DPR), WICK_W, FLAT)).toBe('full');
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, ITEMS, priceToY, WIDE, DPR, FLAT);
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(ITEMS.length * 2);
    expect(raster(rec.ops)).toEqual(rasterPreLod(ITEMS, WIDE, FLAT));
  });

  it('keeps a differently-coloured body at tight spacing, pixels and all', () => {
    const TWO_TONE: CandleStyle = { ...FLAT, wickUpColor: '#004400', wickDownColor: '#440000' };
    expect(candleTier(optimalBarWidth(TIGHT, DPR), WICK_W, TWO_TONE)).toBe('full');
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, ITEMS, priceToY, TIGHT, DPR, TWO_TONE);
    expect(raster(rec.ops)).toEqual(rasterPreLod(ITEMS, TIGHT, TWO_TONE));
  });

  it('judges a volume candle on the width it will actually draw', () => {
    // widthScale narrows the body per bar, so the tier cannot be hoisted: a
    // wide chart can still have individual candles collapse onto the wick.
    const WIDE = 8;
    const scaled: CandleStyle = { ...FLAT, widthScale: (b) => (b.close >= b.open ? 1 : 0.05) };
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, ITEMS, priceToY, WIDE, DPR, scaled);
    // The two up bars keep their bodies; the single down bar is scaled to 1px
    // and skips its own.
    const fills = rec.ops.filter((o) => o.type === 'fillRect');
    expect(fills).toHaveLength(ITEMS.length + 2);
  });
});
