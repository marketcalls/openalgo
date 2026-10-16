/**
 * The annotation tools: the ones whose whole job is to put a human sentence on
 * the chart.
 *
 * They share plate-and-tail machinery, so what distinguishes them is where the
 * tail leaves the plate and how the plate is shaped. That is exactly what a
 * test can pin and a reviewer cannot see by reading: two tools drawing the same
 * rectangle in different places look identical in source.
 *
 * Their text lives in `drawing.text`, never in the style bag: the plate's
 * colour, the face and the content are the text block's, the pin and stem are
 * the style's.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import {
  NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE, TABLE,
  ARROW_LEFT, ARROW_RIGHT, ARROW_UP,
} from '../src/draw/annotation-tools';
import { registerBuiltinDrawingTools } from '../src/draw/tools';
import { registeredDrawingTools } from '../src/draw/registry';
import { RecordingContext } from './helpers/fake-ctx';
import type { DrawingTool, DrawContext, Drawing, DrawingText } from '../src/draw/types';

beforeAll(() => { registerBuiltinDrawingTools(); });

// The price scale formats the price a price note shows, for its hit test as for its paint.
const PANE = { plotWidth: 800, plotHeight: 400, dpr: 1, priceScale: { format: (p: number) => p.toFixed(2) } };

function drawingOf(tool: DrawingTool, text?: Partial<DrawingText> | null): Drawing {
  const d: Drawing = {
    id: 'd1', tool: tool.id, paneIndex: 0, zIndex: 0,
    points: [{ time: 1735689600, price: 1339.7 }],
    style: { ...tool.defaultStyle },
  };
  // `null` means no text block at all; undefined means the tool's default.
  if (text === undefined) { if (tool.defaultText !== undefined) d.text = { ...tool.defaultText }; }
  else if (text !== null) d.text = { ...tool.defaultText, value: '', ...text } as DrawingText;
  return d;
}

/** Draw a one-anchor tool at (x, y) and hand back what it painted. */
function paint(tool: DrawingTool, text?: Partial<DrawingText> | null, x = 300, y = 200): RecordingContext {
  const rec = new RecordingContext();
  const drawing = drawingOf(tool, text);
  const c = {
    ctx: rec as unknown as CanvasRenderingContext2D,
    rc: { ...PANE, theme: { background: '#0d0e12' } },
    pts: [{ x, y }],
    drawing,
    style: { color: '#4f8cff', lineWidth: 1, ...drawing.style },
    selected: false,
    formatPrice: (p: number) => p.toFixed(2),
  } as unknown as DrawContext;
  tool.draw(c);
  return rec;
}

const texts = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');
const boxes = (rec: RecordingContext) =>
  rec.ops.filter((o) => o.type === 'roundRect' || o.type === 'rect');

const ALL = [NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE, TABLE];

describe('every annotation is registered and draws its text', () => {
  it('registers all of them', () => {
    const ids = new Set(registeredDrawingTools().map((t) => t.id));
    for (const t of ALL) expect(ids.has(t.id), t.id).toBe(true);
    expect(ids.has('arrow-left')).toBe(true);
    expect(ids.has('arrow-right')).toBe(true);
  });

  it.each(ALL.map((t) => [t.id, t] as const))('%s paints its own text', (_id, tool) => {
    const rec = paint(tool, { value: 'Hello' });
    expect(texts(rec).join(' ')).toContain('Hello');
  });

  it.each(ALL.map((t) => [t.id, t] as const))('%s leaves the context balanced', (_id, tool) => {
    const rec = paint(tool, { value: 'Hello' });
    expect(rec.count('save')).toBe(rec.count('restore'));
  });

  it.each(ALL.map((t) => [t.id, t] as const))('%s falls back to a label when empty', (_id, tool) => {
    // An annotation with no text is still a mark on the chart, and an empty
    // plate reads as a rendering bug rather than as an empty note.
    expect(texts(paint(tool, { value: '' })).some((t) => t.length > 0)).toBe(true);
    expect(texts(paint(tool, null)).some((t) => t.length > 0)).toBe(true);
  });

  it.each(ALL.map((t) => [t.id, t] as const))('%s starts from its default text', (_id, tool) => {
    expect(tool.defaultText?.value).toBeTruthy();
    expect(texts(paint(tool)).join('\n')).toContain(tool.defaultText?.value.split('\n')[0].split('|')[0] ?? '');
  });
});

describe('the text block, not the style bag, dresses the plate', () => {
  it('fills the plate in the text background colour, else the drawing colour', () => {
    // The plate is painted last; a note's pin head and a balloon's tail come first.
    const plate = (rec: RecordingContext) => rec.ops.filter((o) => o.type === 'fill').pop()?.fillStyle;
    expect(plate(paint(NOTE, { value: 'x' }))).toBe('#4f8cff');
    expect(plate(paint(NOTE, { value: 'x', backgroundColor: '#112233' }))).toBe('#112233');
    // The balloon's tail is the plate's colour too; it is one shape.
    expect(plate(paint(BALLOON, { value: 'x', backgroundColor: '#112233' }))).toBe('#112233');
  });

  it('prints in the text colour when set, else the one that contrasts with the plate', () => {
    const ink = (rec: RecordingContext) => rec.ops.find((o) => o.type === 'fillText')?.fillStyle;
    expect(ink(paint(COMMENT, { value: 'x', color: '#ff00ff' }))).toBe('#ff00ff');
    expect(ink(paint(COMMENT, { value: 'x' }))).not.toBe('#4f8cff');
  });

  it('strokes a border only when asked, in the border colour', () => {
    const strokes = (rec: RecordingContext) => rec.ops.filter((o) => o.type === 'stroke');
    // The balloon has no stem, so its only possible stroke is the border.
    expect(strokes(paint(BALLOON, { value: 'x' })).length).toBe(0);
    const bordered = strokes(paint(BALLOON, { value: 'x', border: true, borderColor: '#00ff00' }));
    expect(bordered.length).toBe(1);
    expect(bordered[0].strokeStyle).toBe('#00ff00');
  });

  it('sets the face from the block', () => {
    const font = (rec: RecordingContext) => rec.ops.find((o) => o.type === 'fillText')?.font ?? '';
    expect(font(paint(NOTE, { value: 'x', fontSize: 20, bold: true, italic: true, fontFamily: 'Georgia' })))
      .toBe('italic 700 20px Georgia');
    expect(font(paint(NOTE, { value: 'x' }))).toContain('12px');
  });
});

describe('each annotation puts its plate somewhere different', () => {
  const plateY = (tool: DrawingTool): number => {
    const b = boxes(paint(tool, { value: 'X' }))[0];
    return b ? Math.round(b.args[1]) : Number.NaN;
  };

  it('sits the balloon above the anchor and the note beside it', () => {
    // Both are one-anchor text marks; the placement is the whole difference.
    expect(plateY(BALLOON)).toBeLessThan(200);
    expect(plateY(NOTE)).toBeLessThan(200);
    expect(plateY(BALLOON)).not.toBe(plateY(NOTE));
  });

  it('stands the signpost clear of the price action', () => {
    // The post is 34px, so the plate must clear the anchor by at least that.
    expect(plateY(SIGNPOST)).toBeLessThan(200 - 34);
  });
});

describe('the price note reads its price rather than storing one', () => {
  it('prints the anchor price, formatted by the pane', () => {
    // A typed price is a number that was true once, which is worse on a chart
    // than no number at all.
    expect(texts(paint(PRICE_NOTE, { value: 'Support' }))).toContain('1339.70');
  });

  it('keeps the user text beneath it', () => {
    expect(texts(paint(PRICE_NOTE, { value: 'Support' })).join(' ')).toContain('Support');
  });
});

describe('the table lays out rows and columns', () => {
  it('splits rows on newline and columns on a pipe', () => {
    const drawn = texts(paint(TABLE, { value: 'Level|Price\nEntry|100\nStop|95' }));
    expect(drawn).toEqual(expect.arrayContaining(['Level', 'Price', 'Entry', '100', 'Stop', '95']));
  });

  it('draws the header row in a heavier face than the body', () => {
    const rec = paint(TABLE, { value: 'Head|Col\nBody|Cell' });
    const head = rec.ops.find((o) => o.type === 'fillText' && o.text === 'Head');
    const body = rec.ops.find((o) => o.type === 'fillText' && o.text === 'Body');
    expect(head?.font).not.toBe(body?.font);
    expect(head?.font).toContain('600');
    // A bold table keeps its header a step heavier still.
    const bold = paint(TABLE, { value: 'Head|Col\nBody|Cell', bold: true });
    expect(bold.ops.find((o) => o.type === 'fillText' && o.text === 'Head')?.font).toContain('800');
    expect(bold.ops.find((o) => o.type === 'fillText' && o.text === 'Body')?.font).toContain('700');
  });

  it('survives a single cell with no separators at all', () => {
    expect(() => paint(TABLE, { value: 'just one' })).not.toThrow();
    expect(texts(paint(TABLE, { value: 'just one' }))).toContain('just one');
  });

  it('is bordered unless told otherwise', () => {
    expect(paint(TABLE, { value: 'a|b' }).count('stroke')).toBeGreaterThan(0);
    expect(paint(TABLE, { value: 'a|b', border: false }).count('stroke')).toBe(0);
  });
});

describe('the sideways arrows are the vertical one turned', () => {
  it('points left and right rather than up', () => {
    const at = (tool: DrawingTool) => {
      const rec = paint(tool, null);
      // moveTo counts: a horizontal arrow's shaft starts at the tip, so
      // measuring lineTo alone misses the length that makes it horizontal.
      const xs = rec.ops
        .filter((o) => o.type === 'lineTo' || o.type === 'moveTo')
        .map((o) => o.args[0]);
      return { min: Math.min(...xs), max: Math.max(...xs) };
    };
    const l = at(ARROW_LEFT);
    const r = at(ARROW_RIGHT);
    // The shaft runs along x, so the horizontal spread is far wider than the
    // vertical arrow's, which only spreads by its head width.
    expect(l.max - l.min).toBeGreaterThan(at(ARROW_UP).max - at(ARROW_UP).min);
    // And they lie on opposite sides of the anchor.
    expect(l.max).toBeGreaterThan(300);
    expect(r.min).toBeLessThan(300);
  });

  it('outline only when the fill is off', () => {
    const filled = paint(ARROW_UP, null);
    const rec = new RecordingContext();
    const d = drawingOf(ARROW_UP, null);
    d.style.fill = false;
    ARROW_UP.draw({
      ctx: rec as unknown as CanvasRenderingContext2D, rc: { ...PANE, theme: { background: '#000' } },
      pts: [{ x: 300, y: 200 }], drawing: d, style: { color: '#4f8cff', lineWidth: 1, ...d.style },
      selected: false, formatPrice: (p: number) => String(p),
    } as unknown as DrawContext);
    expect(filled.count('fill')).toBe(1);
    expect(rec.count('fill')).toBe(0);
    expect(rec.count('stroke')).toBe(1);
  });
});

describe('every annotation can be grabbed', () => {
  const hitContext = (tool: DrawingTool) => {
    const drawing = drawingOf(tool, { value: 'Hello' });
    return { pts: [{ x: 300, y: 200 }], drawing, rc: PANE } as never;
  };

  it.each(ALL.map((t) => [t.id, t] as const))('%s hit-tests on its plate', (_id, tool) => {
    const h = hitContext(tool);
    // Somewhere on the plate has to be grabbable, or the drawing cannot be
    // selected, moved or deleted once placed.
    let hit = false;
    for (let dx = -140; dx <= 200 && !hit; dx += 10) {
      for (let dy = -90; dy <= 60 && !hit; dy += 10) {
        if (tool.distance(300 + dx, 200 + dy, h) === 0) hit = true;
      }
    }
    expect(hit).toBe(true);
  });

  it.each(ALL.map((t) => [t.id, t] as const))('%s misses far away', (_id, tool) => {
    expect(tool.distance(700, 380, hitContext(tool))).not.toBe(0);
  });

  it('grows the guessed plate with the font size and the line count', () => {
    const at = (text: Partial<DrawingText>) => {
      const drawing = drawingOf(NOTE, text);
      const h = { pts: [{ x: 300, y: 200 }], drawing, rc: PANE } as never;
      // Just under the plate's top-left, walking down until it misses.
      let y = 200 - 34;
      while (NOTE.distance(320, y, h) === 0) y += 1;
      return y;
    };
    expect(at({ value: 'a\nb\nc' })).toBeGreaterThan(at({ value: 'a' }));
    expect(at({ value: 'a', fontSize: 30 })).toBeGreaterThan(at({ value: 'a' }));
  });
});
