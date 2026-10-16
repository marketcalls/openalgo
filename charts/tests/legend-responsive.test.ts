import { describe, expect, it } from 'vitest';
import { PaneLegend } from '../src/primitives/pane-legend';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import { makeCtx } from './helpers/fake-ctx';

function paint(legend: PaneLegend, width: number, hoverId?: string, dpr = 1) {
  const { ctx, rec } = makeCtx();
  const rc: PrimitiveRenderContext = { priceScale: new PriceScale(), timeScale: new TimeScale(),
    dataLayer: new DataLayer(), plotWidth: width, plotHeight: 200, priceAxisWidth: 60, dpr, theme: darkTheme, hoverId };
  legend.draw(ctx, rc);
  return { rec, texts: rec.ops.filter(op => op.type === 'fillText').map(op => op.text) };
}

describe('responsive canvas legends', () => {
  it('keeps a complete preferred reading and shortens a long title inside the plot', () => {
    const legend = new PaneLegend({ id: 'price', title: 'A very long instrument description', params: '1D US',
      status: { marketStatus: { text: 'Market closed' } }, actions: [] });
    legend.setValues([{ label: 'O', text: '100.00', field: 'ohlc' },
      { label: 'C', text: '123.45', field: 'ohlc', priority: 10 }]);
    const narrow = paint(legend, 140);
    expect(narrow.texts).toContain('123.45');
    expect(narrow.texts).toContain('C');
    expect(narrow.texts).not.toContain('O');
    expect(narrow.texts).not.toContain('Market closed');
    expect(narrow.texts.some(text => text?.endsWith('...'))).toBe(true);
    for (const op of narrow.rec.ops.filter(op => op.type === 'fillText')) {
      expect(op.args[0] + (op.text?.length || 0) * 6).toBeLessThanOrEqual(140);
    }
    expect(narrow.rec.ops.some(op => op.type === 'clip')).toBe(true);
    expect(paint(legend, 800).texts).toEqual([
      'A very long instrument description', '1D US', 'Market closed', 'O', '100.00', 'C', '123.45',
    ]);
  });

  it('never draws half a labelled number when that reading cannot fit', () => {
    const legend = new PaneLegend({ id: 'price', title: 'A', actions: [] });
    legend.setValues([{ label: 'Close', text: '1234567890.12', priority: 10 }]);
    const result = paint(legend, 70);
    expect(result.texts).toContain('A');
    expect(result.texts).not.toContain('Close');
    expect(result.texts).not.toContain('1234567890.12');
  });

  it.each([1, 2])('keeps hover actions and hit areas out of the price axis at pixel ratio %s', dpr => {
    const legend = new PaneLegend({ id: 'study', title: 'A study with long settings',
      params: '14 close 200', actions: ['hide', 'settings', 'close'], statusLine: { background: true } });
    paint(legend, 100, 'study::row', dpr);
    const buttons = (legend as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
    expect(buttons.map(button => button.id)).toContain('study::close');
    for (const button of buttons) {
      expect(button.x + 16).toBeLessThanOrEqual(100);
      expect(legend.hitTest(button.x + 8, button.y + 8)?.externalId).toBe(button.id);
    }
    expect(legend.hitTest(101, 12)).toBeNull();
    expect(legend.hitTest(150, 12)).toBeNull();
    paint(legend, 0, 'study::row', dpr);
    expect(legend.hitTest(8, 12)).toBeNull();
  });

  it('keeps the final action when the plot cannot fit the complete action row', () => {
    const legend = new PaneLegend({ id: 'study', title: 'Study', actions: ['up', 'down', 'hide', 'maximize', 'close'] });
    paint(legend, 50, 'study::row');
    const buttons = (legend as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
    expect(buttons.map(button => button.id)).toEqual(['study::close']);
    expect(legend.hitTest(buttons[0].x + 8, buttons[0].y + 8)?.externalId).toBe('study::close');
  });

  it('honours field switches before choosing preferred compact readings', () => {
    const legend = new PaneLegend({ id: 'price', title: 'A', actions: [], statusLine: { chartValues: false } });
    legend.setValues([{ label: 'C', text: '123.45', field: 'ohlc', priority: 10 }, { text: '3.14' }]);
    expect(paint(legend, 80).texts).toEqual(['A', '3.14']);
    legend.setOptions({ statusLine: { chartValues: true } });
    expect(paint(legend, 80).texts).toEqual(['A', 'C', '123.45']);
  });

  it('does not intercept a clipped row below the plot', () => {
    const legend = new PaneLegend({ id: 'study', title: 'Study', row: 11 });
    paint(legend, 200, 'study::row');
    expect(legend.hitTest(20, 212)).toBeNull();
  });
});
