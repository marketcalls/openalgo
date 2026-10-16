/**
 * The midpoint readout of the line family: what it says, where it sits, how
 * it is tinted, and that it is off unless asked for, so a line with the
 * default style paints exactly what it painted before the readout existed.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import {
  TREND_LINE, RAY, EXTENDED_LINE, ARROW, RECTANGLE,
  registerBuiltinDrawingTools,
} from '../src/draw/tools';
import { drawingSettingsSchema } from '../src/draw/registry';
import { MEASURE, PRICE_RANGE, FORECAST, LONG_POSITION } from '../src/draw/measure-tools';
import { darkTheme, lightTheme } from '../src/theme';
import { RecordingContext } from './helpers/fake-ctx';
import type { Drawing, DrawingPoint, DrawingStyle, DrawingText, DrawingTool, DrawContext } from '../src/draw/types';

beforeAll(() => { registerBuiltinDrawingTools(); });

/** Six time units per bar, price straight onto y with 400 at the bottom. */
const RC = {
  plotWidth: 800, plotHeight: 400, dpr: 1, priceAxisWidth: 60,
  theme: { background: '#0d0e12', lineColor: '#4f8cff', axisText: '#9aa0a6', upColor: darkTheme.upColor, downColor: darkTheme.downColor },
  priceScale: { priceToY: (p: number) => 400 - p, format: (p: number) => p.toFixed(2) },
  timeScale: { indexToX: (i: number) => i },
  dataLayer: { timeToIndexFloat: (t: number) => t / 6 },
};

const toPt = (p: DrawingPoint) => ({ x: p.time / 6, y: 400 - p.price });

function paint(tool: DrawingTool, points: DrawingPoint[], style: DrawingStyle = {}, text?: DrawingText, rc: object = RC): RecordingContext {
  const rec = new RecordingContext();
  const d: Drawing = { id: 'd', tool: tool.id, paneIndex: 0, zIndex: 0, points, style: { ...tool.defaultStyle, ...style } };
  if (text !== undefined) d.text = text;
  tool.draw({
    ctx: rec as unknown as CanvasRenderingContext2D,
    rc: rc as never,
    pts: points.map(toPt),
    drawing: d,
    style: { color: '#4f8cff', lineWidth: 1.5, ...d.style },
    selected: false,
    formatPrice: (p: number) => p.toFixed(2),
  } as DrawContext);
  return rec;
}

const texts = (rec: RecordingContext) => rec.ops.filter((o) => o.type === 'fillText');
const plates = (rec: RecordingContext) => rec.ops.filter((o) => o.type === 'fillRect');

// From (50, 300) to (150, 100) on screen: 100 bars along, 200 up.
const RISING: DrawingPoint[] = [{ time: 300, price: 100 }, { time: 900, price: 300 }];
const FALLING: DrawingPoint[] = [{ time: 300, price: 300 }, { time: 900, price: 100 }];

describe('the line readout', () => {
  it('is off by default, so a plain line prints nothing', () => {
    for (const tool of [TREND_LINE, RAY, EXTENDED_LINE, ARROW]) {
      expect(texts(paint(tool, RISING)), tool.id).toHaveLength(0);
      expect(plates(paint(tool, RISING)), tool.id).toHaveLength(0);
    }
  });

  it('prints the signed change, the percent, the bar count and the screen angle', () => {
    const rec = paint(TREND_LINE, RISING, { showStats: true });
    const t = texts(rec);
    expect(t).toHaveLength(1);
    // +200 on 100 is +200%; 600 time units at six per bar is 100 bars; the
    // segment rises 200 px over 100 px, which is 63.4 degrees.
    expect(t[0].text).toBe('+200.00 (+200.00%)  100 bars  63.4 deg');
  });

  it('signs a fall, and reads the angle below the horizontal', () => {
    const t = texts(paint(TREND_LINE, FALLING, { showStats: true }));
    expect(t[0].text).toBe('-200.00 (-66.67%)  100 bars  -63.4 deg');
  });

  it('counts bars off the gapless axis, not elapsed time', () => {
    // The same two prices, three times as far apart in time.
    const wide: DrawingPoint[] = [{ time: 300, price: 100 }, { time: 2100, price: 300 }];
    expect(texts(paint(TREND_LINE, wide, { showStats: true }))[0].text).toContain('300 bars');
  });

  it('tints the plate by direction and prints in the tool colour', () => {
    const up = paint(TREND_LINE, RISING, { showStats: true, color: '#abcdef' });
    const down = paint(TREND_LINE, FALLING, { showStats: true, color: '#abcdef' });
    // The plate is two fills: the pane background, then the direction wash.
    expect(plates(up).map((o) => o.fillStyle)).toEqual(['#0d0e12', '#26a69a']);
    expect(plates(down).map((o) => o.fillStyle)).toEqual(['#0d0e12', '#ef5350']);
    expect(texts(up)[0].fillStyle).toBe('#abcdef');
    expect(texts(down)[0].fillStyle).toBe('#abcdef');
  });

  it('lets the text block override the face, the way every readout does', () => {
    const rec = paint(TREND_LINE, RISING, { showStats: true }, { value: '', color: '#ff00ff', fontSize: 20 });
    expect(texts(rec)[0].fillStyle).toBe('#ff00ff');
    expect(texts(rec)[0].font).toContain('20px');
  });

  it('sits centred on the midpoint of the anchors, just above the line', () => {
    const rec = paint(TREND_LINE, RISING, { showStats: true });
    const [t] = texts(rec);
    const [plate] = plates(rec);
    // Midpoint of (50, 300) and (150, 100) is (100, 200); the recorder
    // measures six px per character, and the plate carries 2 px of padding.
    const width = (t.text as string).length * 6;
    expect(t.args[0]).toBeCloseTo(100 - width / 2, 6);
    expect(t.args[1]).toBeCloseTo(200 - 10, 6);
    expect(plate.args[0]).toBeCloseTo(100 - width / 2 - 2, 6);
    expect(plate.args[2]).toBeCloseTo(width + 4, 6);
  });

  it('is measured on the anchors even when the line itself is extended', () => {
    const plain = texts(paint(TREND_LINE, RISING, { showStats: true }))[0].text;
    const extended = texts(paint(EXTENDED_LINE, RISING, { showStats: true }))[0].text;
    const ray = texts(paint(RAY, RISING, { showStats: true }))[0].text;
    expect(extended).toBe(plain);
    expect(ray).toBe(plain);
  });

  it('is offered by every two-anchor line tool, and by no shape', () => {
    for (const tool of [TREND_LINE, RAY, EXTENDED_LINE, ARROW]) {
      expect(drawingSettingsSchema(tool.id).fields.some((f) => f.path === 'style.showStats'), tool.id).toBe(true);
      expect(tool.angleLock, tool.id).toBe(true);
    }
    expect(drawingSettingsSchema(RECTANGLE.id).fields.some((f) => f.path === 'style.showStats')).toBe(false);
    expect(RECTANGLE.angleLock).toBeUndefined();
  });

  it('leaves the context balanced', () => {
    const rec = paint(ARROW, RISING, { showStats: true });
    expect(rec.count('save')).toBe(rec.count('restore'));
  });
});

describe('the direction tints', () => {
  // The default chart is the light theme, whose candles are not the dark
  // theme's colours the tints were fixed to.
  const LIGHT = { ...RC, theme: { ...RC.theme, upColor: lightTheme.upColor, downColor: lightTheme.downColor } };
  const fills = (rec: RecordingContext): (string | undefined)[] =>
    rec.ops.filter((o) => o.type === 'fillRect' || o.type === 'fill').map((o) => o.fillStyle);

  it('are the theme up and down colours, as the candles beside the drawing are', () => {
    const up = lightTheme.upColor, down = lightTheme.downColor;
    expect(plates(paint(TREND_LINE, RISING, { showStats: true }, undefined, LIGHT))[1]!.fillStyle).toBe(up);
    expect(plates(paint(TREND_LINE, FALLING, { showStats: true }, undefined, LIGHT))[1]!.fillStyle).toBe(down);
    for (const tool of [MEASURE, PRICE_RANGE, FORECAST]) {
      expect(fills(paint(tool, RISING, {}, undefined, LIGHT))[0], tool.id).toBe(up);
      expect(fills(paint(tool, FALLING, {}, undefined, LIGHT))[0], tool.id).toBe(down);
    }
    // A long's profit zone and its loss zone, unless the drawing names its own.
    const entry = { time: 300, price: 200 }, target = { time: 900, price: 260 }, stop = { time: 900, price: 170 };
    expect(fills(paint(LONG_POSITION, [entry, target, stop], {}, undefined, LIGHT)).slice(0, 2)).toEqual([up, down]);
  });

  it('keeps the zone colours a position drawing names', () => {
    const rec = new RecordingContext();
    const points = [{ time: 300, price: 200 }, { time: 900, price: 260 }, { time: 900, price: 170 }];
    LONG_POSITION.draw({
      ctx: rec as unknown as CanvasRenderingContext2D, rc: LIGHT as never, pts: points.map(toPt),
      drawing: { id: 'p', tool: LONG_POSITION.id, paneIndex: 0, zIndex: 0, points, style: {}, props: { profitColor: '#123456', lossColor: '#654321' } },
      style: { color: '#4f8cff', lineWidth: 1 }, selected: false, formatPrice: (p: number) => p.toFixed(2),
    } as DrawContext);
    expect(fills(rec).slice(0, 2)).toEqual(['#123456', '#654321']);
  });

  it('marks the verdict of a forecast in the valid and invalid pair of the pattern tools', () => {
    // Bars through the window: one reaches the target, and none does.
    const bars = (high: number) => [300, 600, 900].map((time) => ({ time, open: 150, high, low: 90, close: 150 }));
    const verdict = (high: number): string | undefined => {
      const rec = paint(FORECAST, RISING, {}, undefined, { ...LIGHT, bars: () => bars(high) });
      const chip = rec.ops.findIndex((o) => o.type === 'fillText' && (o.text === 'SUCCESS' || o.text === 'MISSED'));
      const fills = rec.ops.slice(0, chip).filter((o) => o.type === 'fill');
      return fills[fills.length - 1]?.fillStyle;
    };
    expect(verdict(320)).toBe('#16a34a');
    expect(verdict(250)).toBe('#dc2626');
  });
});
