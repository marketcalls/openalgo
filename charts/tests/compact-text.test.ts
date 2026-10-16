import { describe, expect, it } from 'vitest';
import { drawCompactText } from '../src/profile/compact-text';

function raster(text: string, height = 5, width = text.length * 4 - 1) {
  const pixels = new Set<string>();
  const ctx = {
    fillRect(x: number, y: number, w: number, h: number) {
      expect([x, y, w, h].every(Number.isInteger)).toBe(true);
      for (let row = y; row < y + h; row++) {
        for (let col = x; col < x + w; col++) pixels.add(`${col},${row}`);
      }
    },
  } as CanvasRenderingContext2D;
  const drawn = drawCompactText(ctx, text, 0.2, height / 2, height, width, 'left');
  return { drawn, pixels };
}

describe('compact pixel alphabet', () => {
  it('paints a recognizable A at exactly 3 by 5 physical pixels', () => {
    const { pixels, drawn } = raster('A');
    expect(drawn).toBe(true);
    const rows = Array.from({ length: 5 }, (_, y) =>
      Array.from({ length: 3 }, (_, x) => pixels.has(`${x},${y}`) ? '#' : '.').join(''));
    expect(rows).toEqual(['.#.', '#.#', '###', '#.#', '#.#']);
  });

  it('keeps every TPO period and digit visually distinct', () => {
    const shapes = new Map<string, string>();
    for (const letter of 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#') {
      const { drawn, pixels } = raster(letter);
      expect(drawn).toBe(true);
      expect(pixels.size).toBeGreaterThan(0);
      const shape = [...pixels].sort().join(';');
      expect(shapes.get(shape), `glyph ${letter} duplicates another character`).toBeUndefined();
      shapes.set(shape, letter);
    }
  });

  it('fits full volume numbers within their column without fractional resampling', () => {
    const { drawn, pixels } = raster('12345', 6.8, 20);
    expect(drawn).toBe(true);
    for (const pixel of pixels) {
      const [x, y] = pixel.split(',').map(Number);
      expect(x).toBeLessThan(20);
      expect(y).toBeLessThan(7);
    }
  });

  it('tolerates price-scale floating-point noise at an exact five-pixel row', () => {
    expect(raster('A', 5 - 1e-10, 3).drawn).toBe(true);
    expect(raster('A', 4.99, 3).drawn).toBe(false);
  });

  it('declines glyphs when fewer than five physical rows or three columns fit', () => {
    expect(raster('A', 4, 3).drawn).toBe(false);
    expect(raster('A', 5, 2).drawn).toBe(false);
  });
});
