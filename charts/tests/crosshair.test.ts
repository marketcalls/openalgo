import { describe, it, expect } from 'vitest';
import { drawCrosshair, drawCrosshairTag } from '../src/render/crosshair';
import { formatIstCrosshairLabel, istStringToUtcSeconds } from '../src/feed/time';
import { makeCtx } from './helpers/fake-ctx';

describe('crosshair date tag', () => {
  it('formats a daily bar as "Wkd DD Mon \'YY"', () => {
    // 2026-05-21 is a Thursday
    expect(formatIstCrosshairLabel(istStringToUtcSeconds('2026-05-21'))).toBe("Thu 21 May '26");
  });
  it('appends HH:MM for intraday (non-midnight) bars', () => {
    expect(formatIstCrosshairLabel(istStringToUtcSeconds('2026-05-21 09:15:00'))).toBe("Thu 21 May '26 09:15");
  });
});

describe('drawCrosshair', () => {
  it('draws both lines when y is given', () => {
    const { ctx, rec } = makeCtx();
    drawCrosshair(ctx, 100, 50, 600, 400, 1, '#888');
    expect(rec.count('stroke')).toBe(2); // vertical + horizontal
  });
  it('draws only the vertical line when y is null (global line in non-hovered panes)', () => {
    const { ctx, rec } = makeCtx();
    drawCrosshair(ctx, 100, null, 600, 400, 1, '#888');
    expect(rec.count('stroke')).toBe(1);
  });
  it('skips lines outside the plot', () => {
    const { ctx, rec } = makeCtx();
    drawCrosshair(ctx, 999, 999, 600, 400, 1, '#888');
    expect(rec.count('stroke')).toBe(0);
  });
});

describe('drawCrosshairTag', () => {
  it('draws a filled box + text for the right-axis price tag', () => {
    const { ctx, rec } = makeCtx();
    drawCrosshairTag(ctx, '280.50', 600, 200, 1, '#888', '#000', 'right');
    expect(rec.count('fillRect')).toBe(1);
    expect(rec.count('fillText')).toBe(1);
  });
});
