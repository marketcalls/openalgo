import { afterEach, expect, it, vi } from 'vitest';
import { TABLE } from '../src/draw/annotation-tools';
import { makeCtx } from './helpers/fake-ctx';
import type { Drawing, HitContext } from '../src/draw/types';

afterEach(() => vi.unstubAllGlobals());

it('keeps long table cells grabbable and avoids a phantom fixed-width hit box', () => {
  const { ctx } = makeCtx();
  vi.stubGlobal('document', { createElement: () => ({ getContext: () => ctx }) });
  const drawing: Drawing = { id: 'table', tool: 'table', paneIndex: 0, zIndex: 0,
    points: [{ time: 1, price: 1 }], style: {}, text: { value: 'A long header with many characters|Price\nEntry|23800', fontSize: 11 } };
  const h = { drawing, pts: [{ x: 10, y: 10 }] } as HitContext;
  expect(TABLE.distance(230, 20, h)).toBe(0);
  drawing.text!.value = 'X';
  expect(TABLE.distance(65, 20, h)).toBeNull();
  expect(TABLE.distance(22, 20, h)).toBe(0);
});
