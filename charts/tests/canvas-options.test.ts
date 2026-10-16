import { describe, it, expect } from 'vitest';
import {
  computeGridLines, drawGrid, resolveGridStyle, resolveScaleStyle, resolvePlotMargins,
  dashPattern, SCALE_FONT_MAX, SCALE_FONT_MIN,
} from '../src/render/grid';
import type { CanvasOptions } from '../src/render/grid';
import { resolveCrosshairStyle } from '../src/render/crosshair';
import { darkTheme } from '../src/theme';
import { makeCtx } from './helpers/fake-ctx';

const DASHED = [4, 4];
const DOTTED = [1, 3];

describe('grid visibility flags', () => {
  it('draws both axes when the flags are absent (the historical default)', () => {
    const lines = computeGridLines(200, 100, { spacing: 50 });
    expect(lines.verticals).toEqual([50, 100, 150]);
    expect(lines.horizontals).toEqual([50]);
  });

  it('drops one axis without touching the other', () => {
    expect(computeGridLines(200, 100, { spacing: 50, vertLines: false }))
      .toEqual({ verticals: [], horizontals: [50] });
    expect(computeGridLines(200, 100, { spacing: 50, horzLines: false }))
      .toEqual({ verticals: [50, 100, 150], horizontals: [] });
  });

  it('drops both when both are off', () => {
    const lines = computeGridLines(200, 100, { spacing: 50, vertLines: false, horzLines: false });
    expect(lines).toEqual({ verticals: [], horizontals: [] });
  });

  it('an explicit true is the same as absent', () => {
    expect(computeGridLines(200, 100, { spacing: 50, vertLines: true, horzLines: true }))
      .toEqual(computeGridLines(200, 100, { spacing: 50 }));
  });
});

describe('grid style precedence', () => {
  it('falls through to the theme when nothing is set', () => {
    const style = resolveGridStyle(darkTheme, undefined, 1);
    expect(style.vert?.color).toBe(darkTheme.grid);
    expect(style.horz?.color).toBe(darkTheme.grid);
    expect(style.vert?.dash).toEqual([]); // theme has no gridStyle -> solid
    expect(style.horz?.dash).toEqual([]);
  });

  it('an option wins over the theme, per axis', () => {
    const style = resolveGridStyle(
      { grid: '#111111', gridStyle: 'dotted' },
      { vertColor: '#ff0000', vertStyle: 'dashed' },
      1,
    );
    expect(style.vert?.color).toBe('#ff0000');
    expect(style.vert?.dash).toEqual(DASHED);
    // the untouched axis keeps reading the theme
    expect(style.horz?.color).toBe('#111111');
    expect(style.horz?.dash).toEqual(DOTTED);
  });

  it('the theme wins back when the option is cleared', () => {
    const theme = { grid: '#111111', gridStyle: 'dashed' as const };
    const set = resolveGridStyle(theme, { horzColor: '#00ff00', horzStyle: 'solid' }, 1);
    expect(set.horz?.color).toBe('#00ff00');
    expect(set.horz?.dash).toEqual([]);
    const cleared = resolveGridStyle(theme, {}, 1);
    expect(cleared.horz?.color).toBe('#111111');
    expect(cleared.horz?.dash).toEqual(DASHED);
  });

  it('scales the dash by dpr', () => {
    expect(dashPattern('dashed', 2)).toEqual([8, 8]);
    expect(dashPattern('dotted', 2)).toEqual([2, 6]);
    expect(dashPattern('solid', 2)).toEqual([]);
    expect(dashPattern(undefined, 2)).toEqual([]);
  });
});

describe('drawGrid', () => {
  const lines = { verticals: [50, 100], horizontals: [30] };

  it('strokes each axis with its own colour', () => {
    const { ctx, rec } = makeCtx();
    const style = resolveGridStyle(
      { grid: '#111111' },
      { vertColor: '#ff0000', horzColor: '#0000ff' },
      1,
    );
    drawGrid(ctx, lines, 200, 100, 1, style);
    const strokes = rec.ops.filter((o) => o.type === 'stroke');
    expect(strokes.map((s) => s.strokeStyle)).toEqual(['#ff0000', '#0000ff']);
  });

  it('sets each axis dash before its stroke', () => {
    const { ctx, rec } = makeCtx();
    const style = resolveGridStyle(
      { grid: '#111111' },
      { vertStyle: 'dotted', horzStyle: 'dashed' },
      1,
    );
    drawGrid(ctx, lines, 200, 100, 1, style);
    const dashes = rec.ops.filter((o) => o.type === 'setLineDash').map((o) => o.args);
    // vertical, horizontal, then the reset that leaves the context clean
    expect(dashes).toEqual([DOTTED, DASHED, []]);
  });

  it('skips the stroke for an axis with no lines', () => {
    const { ctx, rec } = makeCtx();
    const style = resolveGridStyle(darkTheme, { vertColor: '#ff0000' }, 1);
    drawGrid(ctx, { verticals: [], horizontals: [30] }, 200, 100, 1, style);
    const strokes = rec.ops.filter((o) => o.type === 'stroke');
    expect(strokes).toHaveLength(1);
    expect(strokes[0].strokeStyle).toBe(darkTheme.grid); // the horizontal one
  });

  it('honours the flat style a caller passes without per-axis fields', () => {
    const { ctx, rec } = makeCtx();
    drawGrid(ctx, lines, 200, 100, 1, { color: '#abcdef', lineWidth: 1, dash: DASHED });
    const strokes = rec.ops.filter((o) => o.type === 'stroke');
    expect(strokes.map((s) => s.strokeStyle)).toEqual(['#abcdef', '#abcdef']);
    const dashes = rec.ops.filter((o) => o.type === 'setLineDash').map((o) => o.args);
    expect(dashes).toEqual([DASHED, DASHED, []]);
  });

  it('snaps line positions to device pixels', () => {
    const { ctx, rec } = makeCtx();
    drawGrid(ctx, { verticals: [50.4], horizontals: [] }, 200, 100, 2, { color: '#fff', lineWidth: 1 });
    const move = rec.ops.find((o) => o.type === 'moveTo');
    expect(move?.args[0]).toBe(101); // round(50.4 * 2)
  });
});

describe('crosshair style precedence', () => {
  it('falls through to the theme, which defaults to a dashed hairline', () => {
    const style = resolveCrosshairStyle(darkTheme, undefined, 1);
    expect(style.color).toBe(darkTheme.crosshair);
    expect(style.width).toBe(1);
    expect(style.dash).toEqual(DASHED);
  });

  it('an option wins over the theme', () => {
    const theme = { crosshair: '#888888', crosshairStyle: 'dotted' as const, crosshairWidth: 2 };
    const style = resolveCrosshairStyle(theme, { color: '#ff00ff', style: 'solid', width: 3 }, 1);
    expect(style.color).toBe('#ff00ff');
    expect(style.dash).toEqual([]);
    expect(style.width).toBe(3);
  });

  it('the theme wins back when the option is cleared', () => {
    const theme = { crosshair: '#888888', crosshairStyle: 'dotted' as const, crosshairWidth: 2 };
    const style = resolveCrosshairStyle(theme, {}, 1);
    expect(style.color).toBe('#888888');
    expect(style.dash).toEqual(DOTTED);
    expect(style.width).toBe(2);
  });
});

describe('scale text and line precedence', () => {
  it('falls through to the theme', () => {
    const style = resolveScaleStyle(darkTheme, undefined);
    expect(style.textColor).toBe(darkTheme.axisText);
    expect(style.lineColor).toBe(darkTheme.axisLine);
    expect(style.font).toBe('11px system-ui, sans-serif');
  });

  it('an option wins over the theme', () => {
    const style = resolveScaleStyle(
      { axisText: '#111111', axisLine: '#222222', axisFontSize: 11 },
      { textColor: '#ffffff', lineColor: '#333333', fontSize: 13 },
    );
    expect(style.textColor).toBe('#ffffff');
    expect(style.lineColor).toBe('#333333');
    expect(style.font).toBe('13px system-ui, sans-serif');
  });

  it('the theme wins back for whichever field is cleared', () => {
    const theme = { axisText: '#111111', axisLine: '#222222', axisFontSize: 12 };
    const style = resolveScaleStyle(theme, { textColor: '#ffffff' });
    expect(style.textColor).toBe('#ffffff');
    expect(style.lineColor).toBe('#222222');
    expect(style.font).toBe('12px system-ui, sans-serif');
  });

  it('clamps the option to the dialog range but leaves a theme size alone', () => {
    const theme = { axisText: '#111111', axisLine: '#222222', axisFontSize: 18 };
    expect(resolveScaleStyle(theme, { fontSize: 40 }).font).toBe(`${SCALE_FONT_MAX}px system-ui, sans-serif`);
    expect(resolveScaleStyle(theme, { fontSize: 2 }).font).toBe(`${SCALE_FONT_MIN}px system-ui, sans-serif`);
    expect(resolveScaleStyle(theme, undefined).font).toBe('18px system-ui, sans-serif');
  });
});

describe('plot margins', () => {
  it('converts percent to the fraction the price scale stores', () => {
    expect(resolvePlotMargins({ top: 10, bottom: 25 })).toEqual({ marginTop: 0.1, marginBottom: 0.25 });
  });

  it('omits the side that was not set, so a patch never clobbers the other', () => {
    expect(resolvePlotMargins({ top: 5 })).toEqual({ marginTop: 0.05 });
    expect(resolvePlotMargins(undefined)).toEqual({});
  });

  it('caps each side so the pair always leaves a band for the data', () => {
    expect(resolvePlotMargins({ top: 90, bottom: -5 })).toEqual({ marginTop: 0.49, marginBottom: 0 });
  });
});

describe('CanvasOptions', () => {
  it('carries every Canvas tab control in one block', () => {
    const opts: CanvasOptions = {
      grid: { vertLines: false, horzColor: '#123456', horzStyle: 'dotted' },
      crosshair: { color: '#654321', style: 'solid' },
      scales: { textColor: '#abcabc', fontSize: 14, lineColor: '#cbacba' },
      margins: { top: 12, bottom: 8 },
    };
    const grid = resolveGridStyle(darkTheme, opts.grid, 1);
    expect(grid.horz?.color).toBe('#123456');
    expect(computeGridLines(200, 100, { spacing: 50, ...opts.grid }).verticals).toEqual([]);
    expect(resolveCrosshairStyle(darkTheme, opts.crosshair, 1).dash).toEqual([]);
    expect(resolveScaleStyle(darkTheme, opts.scales).font).toBe('14px system-ui, sans-serif');
    expect(resolvePlotMargins(opts.margins)).toEqual({ marginTop: 0.12, marginBottom: 0.08 });
  });
});
