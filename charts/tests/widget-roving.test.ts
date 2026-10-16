/** Roving focus arithmetic (roving.ts): the arrows wrap, Home and End go to the ends, and nothing moves from no item unless asked. */
import { describe, expect, it } from 'vitest';
import { rovingIndex } from '../src/widget/roving';

const ROW = ['ArrowLeft', 'ArrowRight'] as const;
const COLUMN = ['ArrowUp', 'ArrowDown'] as const;

describe('rovingIndex', () => {
  it('wraps the arrows and sends Home and End to the ends', () => {
    expect(rovingIndex('ArrowRight', 0, 3, ROW)).toBe(1);
    expect(rovingIndex('ArrowRight', 2, 3, ROW)).toBe(0);
    expect(rovingIndex('ArrowLeft', 0, 3, ROW)).toBe(2);
    expect(rovingIndex('Home', 2, 3, ROW)).toBe(0);
    expect(rovingIndex('End', 0, 3, ROW)).toBe(2);
  });

  it('answers only its own axis', () => {
    expect(rovingIndex('ArrowDown', 0, 3, ROW)).toBe(-1);
    expect(rovingIndex('ArrowRight', 0, 3, COLUMN)).toBe(-1);
    expect(rovingIndex('Enter', 0, 3, ROW)).toBe(-1);
  });

  it('moves nothing from no item unless asked, then starts at the ends', () => {
    expect(rovingIndex('ArrowDown', -1, 3, COLUMN)).toBe(-1);
    expect(rovingIndex('Home', -1, 3, COLUMN)).toBe(-1);
    expect(rovingIndex('ArrowDown', -1, 3, COLUMN, true)).toBe(0);
    expect(rovingIndex('ArrowUp', -1, 3, COLUMN, true)).toBe(2);
    expect(rovingIndex('ArrowDown', -1, 0, COLUMN, true)).toBe(-1);
  });
});
