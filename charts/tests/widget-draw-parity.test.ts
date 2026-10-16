/**
 * The widget restates two things the draw tier keeps private, because a
 * widget module may not import that tier by path: the text tool's layout,
 * which the inline editor lays its box over, and the style fallbacks the
 * layer paints with, which the properties dialog shows before the first
 * edit. These tests paint through the draw tier and hold the widget's copy
 * to what was painted, so a change on either side fails here instead of
 * leaving an editor box offset from its text or a control showing a value
 * the drawing does not have. (The test they replace compared the copy with
 * itself.)
 */
import { beforeAll, describe, expect, it } from 'vitest';
import { darkTheme } from '../src/theme';
import { DrawingLayer, drawingSettingsSchema, getDrawingTool, registerBuiltinDrawingTools } from '../src/draw/index';
import type { Drawing, DrawingText } from '../src/draw/index';
import { textFrame, TEXT_PAD } from '../src/widget/dialogs/text-editor';
import { drawingDefaults } from '../src/widget/dialogs/drawing-properties';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

beforeAll(() => { registerBuiltinDrawingTools(); });

/** A pane whose times and prices are its pixels, at one device pixel per CSS pixel. */
const rc = {
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
  dataLayer: { timeToIndexFloat: (t: number) => t },
  plotWidth: 900, plotHeight: 600, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
} as never;

/** Paint `drawings` through the layer, noting the alpha each fill ran at. */
function paint(drawings: Drawing[]): { rec: RecordingContext; fillAlphas: number[] } {
  const { ctx, rec } = makeCtx();
  const fillAlphas: number[] = [];
  const alpha = (): number => (rec as unknown as { globalAlpha?: number }).globalAlpha ?? 1;
  const fill = rec.fill.bind(rec);
  const fillRect = rec.fillRect.bind(rec);
  rec.fill = (): void => { fillAlphas.push(alpha()); fill(); };
  rec.fillRect = (x: number, y: number, w: number, h: number): void => { fillAlphas.push(alpha()); fillRect(x, y, w, h); };
  const layer = new DrawingLayer('top');
  layer.setDrawings(drawings);
  layer.draw(ctx, rc);
  return { rec, fillAlphas };
}

const textDrawing = (text: Partial<DrawingText>): Drawing => ({
  id: 't', tool: 'text', paneIndex: 0, zIndex: 0, style: {},
  points: [{ time: 120, price: 240 }], text: { value: '', ...text },
});

describe('the inline text editor over the painted text', () => {
  it.each([
    ['plain', { value: 'Breakout' }],
    ['multi-line', { value: 'Gap fill\nabove 2451', fontSize: 12 }],
    ['bold italic, in its own family', { value: 'Pivot', bold: true, italic: true, fontFamily: 'Georgia', fontSize: 18 }],
    ['wrapped at its own width', { value: 'the swing high held twice before the break', wrap: true, wrapWidth: 90 }],
    ['wrapped at the default width', { value: 'volume dried up into the close and the gap filled on the open next morning', wrap: true }],
    ['empty, shown as its placeholder', { value: '' }],
  ] as const)('sits exactly on the %s text the draw tier paints', (_, text) => {
    const drawing = textDrawing({ ...text, background: true });
    const { rec } = paint([drawing]);
    const plate = rec.ops.find((op) => op.type === 'roundRect')!.args;
    const lines = rec.ops.filter((op) => op.type === 'fillText');
    const chart = { timeToCoordinate: (t: number) => t, priceToCoordinate: (p: number) => p };
    const frame = textFrame(chart, drawing, (s) => rec.measureText(s).width)!;
    expect([frame.x, frame.y, frame.width, frame.height]).toEqual(plate.slice(0, 4));
    expect(frame.lines).toEqual(lines.map((op) => op.text));
    expect(frame.font).toBe(lines[0]!.font);
    lines.forEach((op, i) => {
      expect(op.args[0]).toBe(frame.x + TEXT_PAD);
      expect(op.args[1]).toBeCloseTo(frame.y + TEXT_PAD + i * frame.lineHeight, 9);
    });
  });
});

describe('the properties dialog before the first edit', () => {
  const defaults = (tool: string): Record<string, unknown> =>
    drawingDefaults(getDrawingTool(tool), drawingSettingsSchema(tool), darkTheme.lineColor);

  it('shows the line width the layer hands a drawing that sets none', () => {
    // The width a tool is given, before it rounds the stroke to whole device pixels.
    const tool = getDrawingTool('trend-line');
    const draw = tool.draw;
    const given: number[] = [];
    tool.draw = (c) => { given.push(c.style.lineWidth); draw(c); };
    try {
      paint([{ id: 'l', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
        points: [{ time: 100, price: 300 }, { time: 400, price: 200 }] }]);
    } finally { tool.draw = draw; }
    expect(given).toEqual([defaults('trend-line')['style.lineWidth']]);
  });

  it('shows the fill alpha a filled shape paints with when it sets none', () => {
    const { fillAlphas } = paint([{ id: 'r', tool: 'rectangle', paneIndex: 0, zIndex: 0, style: { fill: true },
      points: [{ time: 100, price: 300 }, { time: 400, price: 200 }] }]);
    expect(fillAlphas[0]).toBe(defaults('rectangle')['style.fillOpacity']);
  });

  it('shows the plate alpha and the size a text drawing paints with when it sets neither', () => {
    const { rec, fillAlphas } = paint([textDrawing({ value: 'Open', background: true })]);
    expect(fillAlphas[0]).toBe(defaults('text')['text.backgroundOpacity']);
    expect(rec.ops.find((op) => op.type === 'fillText')!.font).toContain(`${String(defaults('text')['text.fontSize'])}px`);
  });
});
