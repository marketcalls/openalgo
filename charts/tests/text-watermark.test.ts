/**
 * The mode marker: a word stamped across the plot so a chart showing a past
 * session cannot be mistaken for one showing the present.
 *
 * A trader who forgets which they are looking at can read a live decision off
 * history, so the mark has to be readable without being looked for, and it must
 * never eat a click or cover the candles it is describing.
 */
import { describe, it, expect } from 'vitest';
import { TextWatermark } from '../src/primitives/text-watermark';
import { RecordingContext } from './helpers/fake-ctx';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const rc = (plotWidth = 800, plotHeight = 400, dpr = 1): PrimitiveRenderContext =>
  ({ plotWidth, plotHeight, dpr }) as PrimitiveRenderContext;

function drawn(w: TextWatermark, ctx = rc()): RecordingContext {
  const rec = new RecordingContext();
  w.draw(rec as unknown as CanvasRenderingContext2D, ctx);
  return rec;
}

describe('TextWatermark', () => {
  it('draws the word once, centred in the plot', () => {
    const rec = drawn(new TextWatermark({ text: 'Replay' }));
    const texts = rec.ops.filter((o) => o.type === 'fillText');
    expect(texts).toHaveLength(1);
    expect(texts[0].text).toBe('Replay');
    expect(texts[0].args).toEqual([400, 200]);
  });

  it('sits under the series, so it never covers the bars it describes', () => {
    expect(new TextWatermark({ text: 'Replay' }).zOrder()).toBe('bottom');
  });

  it('reports no hit, so a click reaches the chart beneath it', () => {
    expect(new TextWatermark({ text: 'Replay' }).hitTest()).toBeNull();
  });

  it('is faint by default and leaves the context balanced', () => {
    const rec = drawn(new TextWatermark({ text: 'Replay' }));
    expect(rec.count('save')).toBe(rec.count('restore'));
    // A mark at full strength would compete with the candles.
    const w = new TextWatermark({ text: 'Replay' });
    expect((w as unknown as { _opts: { opacity: number } })._opts.opacity).toBeLessThan(0.2);
  });

  it('shrinks to fit a narrow pane rather than running off the edge', () => {
    // The fake context measures 6px a character whatever the font, so the word
    // has to be long enough to overflow on its own: 40 characters is 240px,
    // past the 160px a 200px-wide pane allows and inside the 960px a wide one
    // does. A real browser scales the measurement with the font as well, so the
    // shrink triggers earlier there, not later.
    const long = 'Replay Replay Replay Replay Replay Repl';
    const wide = drawn(new TextWatermark({ text: long, fontSize: 64 }), rc(1200, 400));
    const narrow = drawn(new TextWatermark({ text: long, fontSize: 64 }), rc(200, 400));
    const sizeOf = (rec: RecordingContext): number =>
      Number(/([\d.]+)px/.exec(rec.ops.find((o) => o.type === 'fillText')?.font ?? '')?.[1] ?? 0);
    expect(sizeOf(narrow)).toBeLessThan(sizeOf(wide));
    expect(sizeOf(narrow)).toBeGreaterThan(0);
  });

  it('scales with device pixel ratio, so it is not half size on a retina panel', () => {
    const one = drawn(new TextWatermark({ text: 'R', fontSize: 40 }), rc(800, 400, 1));
    const two = drawn(new TextWatermark({ text: 'R', fontSize: 40 }), rc(800, 400, 2));
    const sizeOf = (rec: RecordingContext): number =>
      Number(/(\d+)px/.exec(rec.ops.find((o) => o.type === 'fillText')?.font ?? '')?.[1] ?? 0);
    expect(sizeOf(two)).toBe(sizeOf(one) * 2);
  });

  it('draws nothing for an empty word or an unmeasured pane', () => {
    expect(drawn(new TextWatermark({ text: '' })).ops).toHaveLength(0);
    expect(drawn(new TextWatermark({ text: 'Replay' }), rc(0, 0)).ops).toHaveLength(0);
  });

  it('can be restyled in place, which is how a host turns the mode off', () => {
    const w = new TextWatermark({ text: 'Replay' });
    w.setOptions({ text: '' });
    expect(drawn(w).ops).toHaveLength(0);
    w.setOptions({ text: 'Replay' });
    expect(drawn(w).ops.length).toBeGreaterThan(0);
  });
});

it('fits a short pane vertically and shrinks long text below ten pixels when needed', () => {
  const short = drawn(new TextWatermark({ text: 'Research', fontSize: 64 }), rc(800, 24));
  const text = short.ops.find((op) => op.type === 'fillText')!;
  expect(Number(/([\d.]+)px/.exec(text.font!)![1])).toBeLessThanOrEqual(19.2);
  const long = drawn(new TextWatermark({ text: 'A'.repeat(1000), fontSize: 64 }), rc(100, 100));
  const small = long.ops.find((op) => op.type === 'fillText')!;
  expect(Number(/([\d.]+)px/.exec(small.font!)![1])).toBeLessThan(10);
});

it('requests a repaint when a mounted text mark is restyled', () => {
  const mark = new TextWatermark({ text: 'Replay' });
  let updates = 0;
  mark.attached({ requestUpdate: () => { updates++; } });
  mark.setOptions({ color: '#123456' });
  expect(updates).toBe(1);
  mark.detached();
  mark.setOptions({ color: '#abcdef' });
  expect(updates).toBe(1);
});
