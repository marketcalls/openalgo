import { expect, it } from 'vitest';
import { MEASURE } from '../src/draw/measure-tools';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import type { DrawContext } from '../src/draw/types';

it('measures only the selected history window and reads its live volume again', () => {
  let reads = 0;
  const bars = Array.from({ length: 100_000 }, (_, i) => ({
    get time() { reads++; return i; }, volume: 1,
  }));
  const paint = () => {
    const { ctx, rec } = makeCtx();
    MEASURE.draw({
      ctx, selected: false, pts: [{ x: 10, y: 50 }, { x: 100, y: 150 }],
      drawing: { id: 'm', tool: 'measure', points: [{ time: 99_989, price: 10 }, { time: 99_999, price: 20 }], style: {}, paneIndex: 0, zIndex: 0 },
      style: { color: '#4f8cff', lineWidth: 1.5 }, formatPrice: (p: number) => p.toFixed(2),
      rc: { dpr: 1, theme: darkTheme, bars: () => bars, dataLayer: { timeToIndexFloat: (t: number) => t } },
    } as unknown as DrawContext);
    return rec.ops.filter(o => o.type === 'fillText').map(o => o.text);
  };
  expect(paint()).toContain('Vol 11');
  expect(reads).toBeLessThan(100);
  reads = 0;
  bars[99_999].volume = 10;
  expect(paint()).toContain('Vol 20');
  expect(reads).toBeLessThan(100);
});
