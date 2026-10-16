import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import {
  DrawingController, DrawingLayer,
  registeredDrawingTools, getDrawingTool, hasDrawingTool, registerDrawingTool,
  matchDrawingShortcut, drawingShortcuts,
  BUILTIN_DRAWING_TOOLS,
  distToSegment, distToLine, distToRect, distToEllipse, rectOf, extendSegment,
} from '../src/draw/index';
import type { Drawing, DrawingText } from '../src/draw/types';
import type { Bar } from '../src/model/bar';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

function makeChart(): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(), raf: { schedule: () => 0 },
    pixelRatio: () => 1, shortcuts: false,
  });
  chart.applySize(W, H);
  chart.addSeries('candlestick').setData(bars(120));
  return { chart, el };
}

describe('coordinate conversion before the first paint', () => {
  // The render loop never runs in these tests (`raf.schedule` is a no-op), which
  // is exactly the state a caller is in between `setData` and the first frame.
  // Price conversion used to depend on the autoscale pass, so it answered
  // ±Infinity there and a drawing placed from a click got a NaN anchor that
  // serialised to null and could never be rendered again.
  it('coordinateToPrice returns a real price with no frame having run', () => {
    const { chart } = makeChart();
    const p = chart.coordinateToPrice(200, 0);
    expect(p).not.toBeNull();
    expect(Number.isFinite(p as number)).toBe(true);
  });

  it('round-trips price and y before the first paint', () => {
    const { chart } = makeChart();
    const price = chart.coordinateToPrice(250, 0) as number;
    expect(chart.priceToCoordinate(price, 0)).toBeCloseTo(250, 6);
  });

  it('lands inside the data range rather than the placeholder 0..1 scale', () => {
    const { chart } = makeChart();
    const mid = chart.coordinateToPrice(H / 2, 0) as number;
    expect(mid).toBeGreaterThan(50);
    expect(mid).toBeLessThan(200);
  });

  it('a click carries a usable price, so placement anchors are never NaN', () => {
    const { chart, el } = makeChart();
    let payload: { price: number | null } | null = null;
    chart.on('click', (p) => { payload = p as { price: number | null }; });
    el.dispatch('pointerdown', pointer('down', 300, 200));
    el.dispatch('pointerup', pointer('up', 300, 200));
    expect(payload).not.toBeNull();
    const price = (payload as unknown as { price: number | null }).price;
    expect(price).not.toBeNull();
    expect(Number.isFinite(price as number)).toBe(true);
  });
});

describe('clicking a drawing selects it', () => {
  // A press on a draggable primitive arms a drag, and the drag-end branch used
  // to return before the click path ran so a drawing could be dragged but
  // never selected, and its anchor handles never appeared.
  it('a press that never moves still selects', () => {
    const { chart, el } = makeChart();
    const draw = new DrawingController(chart);
    const price = chart.coordinateToPrice(300, 0) as number;
    const time = chart.coordinateToTime(400);
    const d = draw.add({
      tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time, price }],
    });
    draw.select(null);
    expect(draw.selected()).toBeNull();

    el.dispatch('pointerdown', pointer('down', 400, 300));
    el.dispatch('pointerup', pointer('up', 400, 300));
    expect(draw.selected()).toBe(d.id);
  });

  it('a press that moves is a drag, not a selection-only click', () => {
    const { chart, el } = makeChart();
    const draw = new DrawingController(chart);
    const price = chart.coordinateToPrice(300, 0) as number;
    const time = chart.coordinateToTime(400);
    const d = draw.add({
      tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time, price }],
    });
    el.dispatch('pointerdown', pointer('down', 400, 300));
    el.dispatch('pointermove', pointer('move', 400, 360));
    el.dispatch('pointerup', pointer('up', 400, 360));
    // It moved, so the anchor changed.
    expect(draw.get(d.id)?.points[0].price).not.toBe(price);
  });
});

describe('geometry', () => {
  it('measures distance to a segment, clamped at its ends', () => {
    const a = { x: 0, y: 0 };
    const b = { x: 10, y: 0 };
    expect(distToSegment(5, 3, a, b)).toBeCloseTo(3, 9);
    // Past the end it measures to the endpoint, not the infinite line.
    expect(distToSegment(20, 0, a, b)).toBeCloseTo(10, 9);
    expect(distToLine(20, 0, a, b)).toBeCloseTo(0, 9);
  });

  it('treats a filled rect as grabbable inside and an empty one only on its edge', () => {
    const a = { x: 0, y: 0 };
    const b = { x: 10, y: 10 };
    expect(distToRect(5, 5, a, b, true)).toBe(0);
    expect(distToRect(5, 5, a, b, false)).toBeCloseTo(5, 9);
  });

  it('measures distance to an ellipse boundary', () => {
    const a = { x: 0, y: 0 };
    const b = { x: 20, y: 20 };
    expect(distToEllipse(10, 10, a, b, true)).toBe(0);
    expect(distToEllipse(20, 10, a, b, false)).toBeCloseTo(0, 6); // on the rim
  });

  it('normalises rect corners regardless of anchor order', () => {
    expect(rectOf({ x: 10, y: 8 }, { x: 2, y: 20 })).toEqual({ x0: 2, y0: 8, x1: 10, y1: 20 });
  });

  it('extends a segment to the plot edges, keeping slope', () => {
    const [a, b] = extendSegment({ x: 10, y: 10 }, { x: 20, y: 20 }, 100, true, true);
    expect(a).toEqual({ x: 0, y: 0 });
    expect(b).toEqual({ x: 100, y: 100 });
  });
});

describe('tool registry', () => {
  it('registers every built-in on tier import', () => {
    expect(BUILTIN_DRAWING_TOOLS).toHaveLength(87);
    for (const t of BUILTIN_DRAWING_TOOLS) expect(hasDrawingTool(t.id)).toBe(true);
    expect(registeredDrawingTools().length).toBeGreaterThanOrEqual(87);
  });

  it('has unique ids and a sane anchor count', () => {
    const ids = BUILTIN_DRAWING_TOOLS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of BUILTIN_DRAWING_TOOLS) expect(t.points).toBeGreaterThanOrEqual(0);
  });

  it('throws a clear error for an unknown tool', () => {
    expect(() => getDrawingTool('nope')).toThrow(/unknown drawing tool/);
  });

  it('accepts a custom tool', () => {
    registerDrawingTool({
      id: 'test-dot', name: 'Dot', points: 1,
      draw: () => {}, distance: () => 0,
    });
    expect(hasDrawingTool('test-dot')).toBe(true);
  });
});

describe('new tool families', () => {
  const rc2 = {
    timeScale: { indexToX: (i: number) => i * 5 },
    priceScale: { priceToY: (p: number) => 300 - p, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndexFloat: (t: number) => t, indexToTimeFloat: (i: number) => i },
    plotWidth: 800, plotHeight: 600, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  const hit = (id: string, pts: { x: number; y: number }[], x: number, y: number): number | null => {
    const tool = getDrawingTool(id);
    return tool.distance(x, y, {
      pts,
      rc: rc2,
      drawing: {
        id: 'd', tool: id, paneIndex: 0, zIndex: 0,
        style: { ...(tool.defaultStyle ?? {}) },
        points: pts.map((_, i) => ({ time: i, price: 100 })),
      },
    });
  };

  it('rotated rectangle follows its own axes, not the screen axes', () => {
    // 0 to 1 is a 45° edge; anchor 2 sets the depth perpendicular to it. An
    // axis-aligned rect would report a very different inside.
    const pts = [{ x: 0, y: 0 }, { x: 100, y: 100 }, { x: 60, y: 100 }];
    // Centre of the parallelogram is inside a filled shape.
    expect(hit('rotated-rectangle', pts, 40, 60)).toBe(0);
    // Well outside, past the far edge.
    expect(hit('rotated-rectangle', pts, 300, -200)).toBeGreaterThan(20);
  });

  it('rotated rectangle degenerates safely when its edge has no length', () => {
    const pts = [{ x: 50, y: 50 }, { x: 50, y: 50 }, { x: 50, y: 50 }];
    const d = hit('rotated-rectangle', pts, 50, 50);
    expect(d === null || Number.isFinite(d)).toBe(true);
  });

  it('double curve is grabbable along the S it actually draws', () => {
    const pts = [{ x: 0, y: 100 }, { x: 50, y: 0 }, { x: 100, y: 100 }];
    // Both halves bend, so points near each lobe hit.
    const near = hit('double-curve', pts, 50, 100);
    expect(near !== null && near < 30).toBe(true);
    expect(hit('double-curve', pts, 50, 400)).toBeGreaterThan(100);
  });

  it('cyclic lines repeat at the anchor interval and stop after the last one', () => {
    const pts = [{ x: 100, y: 50 }, { x: 150, y: 50 }];   // 50px period
    expect(hit('cyclic-lines', pts, 200, 300)).toBeCloseTo(0, 6);  // 3rd line
    expect(hit('cyclic-lines', pts, 205, 300)).toBeCloseTo(5, 6);
    expect(hit('cyclic-lines', pts, 50, 300)).toBeNull();          // before the 1st
    expect(hit('cyclic-lines', pts, 5000, 300)).toBeNull();        // past the last
  });

  it('cyclic lines reject a zero-width period instead of dividing by it', () => {
    expect(hit('cyclic-lines', [{ x: 100, y: 0 }, { x: 100, y: 0 }], 100, 10)).toBeNull();
  });

  it('time cycles measure to the rim of the drawn half only', () => {
    const pts = [{ x: 0, y: 100 }, { x: 100, y: 100 }];   // r = 50, arcs above y=100
    expect(hit('time-cycles', pts, 50, 50)).toBeCloseTo(0, 6);   // top of the 1st arc
    expect(hit('time-cycles', pts, 50, 300)).toBeNull();         // below the baseline
  });

  it('sine line follows the wave, not the chord', () => {
    const pts = [{ x: 0, y: 100 }, { x: 100, y: 60 }];    // period 100, amplitude -40
    // Quarter period is the crest: y = 100 + (-40) = 60.
    const crest = hit('sine-line', pts, 25, 60);
    expect(crest !== null && crest < 2).toBe(true);
    // The chord's midpoint is NOT on the wave (the wave crosses back at x=50).
    expect(hit('sine-line', pts, 50, 100)).toBeCloseTo(0, 0);
    expect(hit('sine-line', pts, 50, 400)).toBeGreaterThan(200);
  });

  it('sine line rejects a zero-width span', () => {
    expect(hit('sine-line', [{ x: 10, y: 0 }, { x: 10, y: 50 }], 10, 0)).toBeNull();
  });

  it('price label and flag mark are grabbable at their anchor', () => {
    expect(hit('price-label', [{ x: 200, y: 200 }], 200, 200)).toBe(0);
    expect(hit('flag-mark', [{ x: 200, y: 200 }], 200, 200)).toBe(0);
    expect(hit('flag-mark', [{ x: 200, y: 200 }], 600, 600)).toBeNull();
  });

  it('callout is grabbable on its bubble and along its tail', () => {
    const pts = [{ x: 100, y: 300 }, { x: 260, y: 180 }];  // target, bubble seat
    expect(hit('callout', pts, 260, 180)).toBe(0);          // bubble
    const onTail = hit('callout', pts, 180, 240);           // midway along the tail
    expect(onTail !== null && onTail < 6).toBe(true);
  });

  it('circle measures radially, so it is round on screen not axis-stretched', () => {
    const pts = [{ x: 100, y: 100 }, { x: 140, y: 100 }];   // r = 40
    // Same radial distance in x and y must give the same answer.
    expect(hit('circle', pts, 100, 140)).toBe(0);           // inside (filled)
    expect(hit('circle', pts, 100, 200)).toBeCloseTo(60, 6); // 100px out, r 40
    expect(hit('circle', pts, 200, 100)).toBeCloseTo(60, 6);
  });

  it('triangle is grabbable along every edge', () => {
    const pts = [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 50, y: 80 }];
    expect(hit('triangle', pts, 50, 0)).toBeCloseTo(0, 6);   // top edge
    expect(hit('triangle', pts, 25, 40)).toBeCloseTo(0, 6);  // left edge
  });

  it('arc passes through its middle anchor, curve only leans toward it', () => {
    const pts = [{ x: 0, y: 0 }, { x: 50, y: 50 }, { x: 100, y: 0 }];
    // The arc is defined to touch the middle point, so distance there is ~0.
    expect(hit('arc', pts, 50, 50) as number).toBeLessThan(1);
    // The curve treats it as a control handle, so the path sits well short of it.
    expect(hit('curve', pts, 50, 50) as number).toBeGreaterThan(10);
  });

  it('fib time zone marks the Fibonacci sequence, not the ratios', () => {
    const pts = [{ x: 100, y: 0 }, { x: 120, y: 0 }];        // unit = 20px
    for (const n of [0, 1, 2, 3, 5, 8]) {
      expect(hit('fib-time-zone', pts, 100 + 20 * n, 300)).toBeCloseTo(0, 6);
    }
    // 4 and 6 are not in the sequence.
    expect(hit('fib-time-zone', pts, 100 + 20 * 4, 300) as number).toBeGreaterThan(0);
  });

  it('gann fan puts a ray on the 1x1 diagonal', () => {
    const pts = [{ x: 0, y: 0 }, { x: 100, y: 100 }];
    expect(hit('gann-fan', pts, 50, 50)).toBeCloseTo(0, 6);   // 1x1
    expect(hit('gann-fan', pts, 100, 50)).toBeCloseTo(0, 6);  // 1x2
  });

  it('arrow markers only hit near their single anchor', () => {
    const pts = [{ x: 200, y: 150 }];
    expect(hit('arrow-up', pts, 200, 160)).toBe(0);      // below, where it sits
    expect(hit('arrow-up', pts, 200, 120)).toBeNull();   // above: miss
    expect(hit('arrow-down', pts, 200, 140)).toBe(0);
    expect(hit('arrow-down', pts, 200, 180)).toBeNull();
  });

  it('highlighter is grabbable across its fat stroke', () => {
    const pts = [{ x: 0, y: 0 }, { x: 100, y: 0 }];
    expect(hit('highlighter', pts, 50, 4)).toBe(0);   // inside the 12px stroke
    expect(hit('highlighter', pts, 50, 40) as number).toBeGreaterThan(0);
  });

  it('price range and date range each measure one axis', () => {
    const tool = getDrawingTool('price-range');
    expect(tool.points).toBe(2);
    expect(getDrawingTool('date-range').points).toBe(2);
    expect(getDrawingTool('forecast').points).toBe(2);
  });
});

describe('every built-in tool renders and hit-tests', () => {
  const rc = {
    timeScale: { indexToX: (i: number) => i * 5 },
    priceScale: { priceToY: (p: number) => 300 - p, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndexFloat: () => 10, indexToTimeFloat: (i: number) => i },
    plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  it('draws without throwing and reports a finite distance', () => {
    for (const tool of BUILTIN_DRAWING_TOOLS) {
      const n = Math.max(1, tool.points || 3);
      const clicked = Array.from({ length: n }, (_, i) => ({ time: 1700000000 + i * 600, price: 100 + i * 5 }));
      // A tool with `expand` is placed with fewer clicks than it has anchors
      // (the position tools drop a 1:1 box off one click), so the real anchor
      // set is what the hook returns: feeding it `tool.points` would render a
      // half-built shape and prove nothing.
      const drawing: Drawing = {
        id: 'x', tool: tool.id, paneIndex: 0, zIndex: 0,
        points: tool.expand ? tool.expand(clicked, { barSeconds: 600, visibleBars: 120 }) : clicked,
        style: { color: '#4f8cff', lineWidth: 1.5 },
        text: { value: 'hi' },
      };
      const pts = drawing.points.map((_, i) => ({ x: 50 + i * 40, y: 100 + i * 30 }));
      const { ctx, rec } = makeCtx();
      expect(() => tool.draw({
        ctx, rc, drawing, selected: false, pts,
        style: { color: '#4f8cff', lineWidth: 1.5, ...drawing.style },
        formatPrice: (v) => v.toFixed(2),
      }), tool.id).not.toThrow();
      expect(rec.ops.length, `${tool.id} drew nothing`).toBeGreaterThan(0);

      const d = tool.distance(pts[0].x, pts[0].y, { pts, drawing, rc });
      expect(d === null || Number.isFinite(d), `${tool.id} distance`).toBe(true);
    }
  });
});

describe('text styling', () => {
  const rc = {
    timeScale: { indexToX: (i: number) => i },
    priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
    dataLayer: { timeToIndexFloat: (t: number) => t },
    plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  /** Render the text tool with a text block, and hand back what it painted. */
  const render = (text: DrawingText) => {
    const drawing: Drawing = {
      id: 't', tool: 'text', paneIndex: 0, zIndex: 0,
      points: [{ time: 10, price: 10 }],
      style: { color: '#fff', lineWidth: 1 },
      text,
    };
    const { ctx, rec } = makeCtx();
    getDrawingTool('text').draw({
      ctx, rc, drawing, selected: false, pts: [{ x: 50, y: 60 }],
      style: { color: '#fff', lineWidth: 1 },
      formatPrice: (v) => String(v),
    });
    return rec;
  };

  it('ships placeholder content as default text, and none of it in the style bag', () => {
    // The text tool is its own box, so a fresh one must have something to show,
    // and in 2.0 that lives on the drawing's text, never in its style.
    const tool = getDrawingTool('text');
    expect(typeof tool.defaultText?.value).toBe('string');
    expect(tool.defaultStyle ?? {}).not.toHaveProperty('text');
    expect(tool.defaultStyle ?? {}).not.toHaveProperty('fontSize');
  });

  it('applies weight, style, and family to the canvas font', () => {
    const rec = render({ value: 'Hi', fontSize: 20, bold: true, italic: true, fontFamily: 'Georgia' });
    // The recording context keeps the last font assigned before fillText.
    expect(rec.ops.some((o) => o.type === 'fillText')).toBe(true);
    expect(rec.font).toContain('italic');
    expect(rec.font).toContain('700');
    expect(rec.font).toContain('Georgia');
    expect(rec.font).toContain('20px');
  });

  it('draws one line per newline', () => {
    const one = render({ value: 'a' });
    const three = render({ value: 'a\nb\nc' });
    expect(three.count('fillText')).toBe(one.count('fillText') + 2);
  });

  it('adds a background plate and a border only when asked', () => {
    const plain = render({ value: 'x' });
    expect(plain.count('fill')).toBe(0);
    expect(plain.count('stroke')).toBe(0);
    const boxed = render({ value: 'x', background: true, border: true, backgroundColor: '#123456' });
    expect(boxed.count('fill')).toBe(1);
    expect(boxed.count('stroke')).toBe(1);
  });

  it('soft-wraps at wrapWidth, producing more lines than unwrapped', () => {
    const value = 'the quick brown fox jumps over the lazy dog again and again';
    const unwrapped = render({ value, wrap: false });
    const wrapped = render({ value, wrap: true, wrapWidth: 60 });
    expect(wrapped.count('fillText')).toBeGreaterThan(unwrapped.count('fillText'));
  });

  it('hit-tests the measured box, not a character count', () => {
    const tool = getDrawingTool('text');
    const drawing: Drawing = {
      id: 't', tool: 'text', paneIndex: 0, zIndex: 0, points: [{ time: 10, price: 10 }],
      style: {},
      text: { value: 'hello', fontSize: 14 },
    };
    const pts = [{ x: 50, y: 60 }];
    expect(tool.distance(52, 62, { pts, drawing, rc })).toBe(0);   // inside
    expect(tool.distance(400, 62, { pts, drawing, rc })).toBeNull(); // far right
    expect(tool.distance(52, 300, { pts, drawing, rc })).toBeNull(); // far below
  });
});

describe('position readouts', () => {
  const rc = {
    timeScale: { indexToX: (i: number) => i },
    priceScale: { priceToY: (p: number) => p, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndexFloat: (t: number) => t },
    plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  const render = (points: Drawing['points'], props?: Drawing['props'], tool = 'long-position') => {
    const drawing: Drawing = {
      id: 'p', tool, paneIndex: 0, zIndex: 0, points,
      style: { color: '#a855f7', lineWidth: 1.5, accountSize: 100000, risk: 1 },
      ...(props === undefined ? {} : { props }),
    };
    const pts = points.map((p) => ({ x: p.time * 10, y: p.price }));
    const { ctx, rec } = makeCtx();
    getDrawingTool(tool).draw({
      ctx, rc, drawing, selected: false, pts,
      style: { color: '#a855f7', lineWidth: 1.5, accountSize: 100000, risk: 1 },
      formatPrice: (v) => v.toFixed(2),
    });
    return rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text);
  };

  const LONG = [{ time: 10, price: 100 }, { time: 20, price: 104 }, { time: 20, price: 98 }];

  it('reads direction, ratio, money at risk, size, and each zone in percent', () => {
    const texts = render(LONG);
    expect(texts).toContain('Long  R:R 2.00');
    // 1% of 100,000 at risk over a 2.00 stop distance buys 500.
    expect(texts).toContain('Loss 1,000.00  Size 500');
    expect(texts).toContain('Target +4.00%');
    expect(texts).toContain('Stop -2.00%');
  });

  it('reads the direction off the geometry, not the tool', () => {
    // A long tool whose target sits below the entry is a short.
    const texts = render([{ time: 10, price: 100 }, { time: 20, price: 96 }, { time: 20, price: 102 }]);
    expect(texts.some((t) => t?.startsWith('Short'))).toBe(true);
  });

  it('previews from two anchors by deriving the stop at the ratio', () => {
    const texts = render([{ time: 10, price: 100 }, { time: 20, price: 104 }]);
    expect(texts).toContain('Target +4.00%');
    expect(texts).toContain('Stop -2.00%');     // 98 derived, never stored
  });

  it('appends the level prices only when asked', () => {
    expect(render(LONG).some((t) => t?.includes('@'))).toBe(false);
    const texts = render(LONG, { showPrices: true });
    expect(texts).toContain('Target +4.00%  @ 104.00');
    expect(texts).toContain('Stop -2.00%  @ 98.00');
  });

  it('every readout toggle removes exactly its line', () => {
    expect(render(LONG, { showHeader: false }).some((t) => t?.includes('R:R'))).toBe(false);
    expect(render(LONG, { showLossSize: false }).some((t) => t?.startsWith('Loss'))).toBe(false);
    expect(render(LONG, { showTargetLabel: false }).some((t) => t?.startsWith('Target'))).toBe(false);
    expect(render(LONG, { showStopLabel: false }).some((t) => t?.startsWith('Stop'))).toBe(false);
  });
});

describe('shape labels', () => {
  const rc = {
    timeScale: { indexToX: (i: number) => i },
    priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
    dataLayer: { timeToIndexFloat: (t: number) => t },
    plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  const render = (tool: string, text?: DrawingText) => {
    const drawing: Drawing = {
      id: 's', tool, paneIndex: 0, zIndex: 0,
      points: [{ time: 10, price: 10 }, { time: 20, price: 40 }, { time: 30, price: 60 }],
      style: { color: '#a855f7', lineWidth: 1.5 },
      ...(text === undefined ? {} : { text }),
    };
    const pts = [{ x: 40, y: 40 }, { x: 200, y: 140 }, { x: 260, y: 180 }];
    const { ctx, rec } = makeCtx();
    getDrawingTool(tool).draw({
      ctx, rc, drawing, selected: false, pts,
      style: { color: '#a855f7', lineWidth: 1.5 },
      formatPrice: (v) => String(v),
    });
    return rec;
  };

  it('a shape with no text draws no label', () => {
    expect(render('rectangle').count('fillText')).toBe(0);
  });

  it('rectangle, ellipse, and channel all carry a label', () => {
    for (const tool of ['rectangle', 'ellipse', 'parallel-channel']) {
      expect(render(tool, { value: 'zone' }).count('fillText'), tool).toBe(1);
    }
  });

  it('uses the text colour for the label, keeping color as the outline', () => {
    const rec = render('rectangle', { value: 'hi', color: '#ffffff' });
    const textFill = rec.ops.filter((o) => o.type === 'fillText').map((o) => o.fillStyle);
    expect(textFill).toContain('#ffffff');
    // The outline is still stroked in the shape colour.
    expect(rec.ops.some((o) => o.type === 'strokeRect' && o.strokeStyle === '#a855f7')).toBe(true);
  });

  it('falls back to the shape colour when the text has none', () => {
    const rec = render('rectangle', { value: 'hi' });
    expect(rec.ops.filter((o) => o.type === 'fillText').map((o) => o.fillStyle)).toContain('#a855f7');
  });

  it('places an outside label above the shape and an inside one within it', () => {
    const inside = render('rectangle', { value: 'hi', position: 'inside' });
    const outside = render('rectangle', { value: 'hi', position: 'outside' });
    const y = (rec: ReturnType<typeof render>) =>
      (rec.ops.find((o) => o.type === 'fillText') as { args: number[] }).args[1];
    expect(y(outside)).toBeLessThan(40);      // above the top edge (y0 = 40)
    expect(y(inside)).toBeGreaterThanOrEqual(40);
  });

  it('honours multiline and vertical alignment', () => {
    expect(render('rectangle', { value: 'a\nb\nc' }).count('fillText')).toBe(3);
    const top = render('rectangle', { value: 'x', valign: 'top' });
    const bottom = render('rectangle', { value: 'x', valign: 'bottom' });
    const y = (rec: ReturnType<typeof render>) =>
      (rec.ops.find((o) => o.type === 'fillText') as { args: number[] }).args[1];
    expect(y(bottom)).toBeGreaterThan(y(top));
  });
});

describe('DrawingController', () => {
  it('draws a two-anchor shape from one press-drag-release gesture', () => {
    // The chart reports a drag as press-click then release-click (`viaDrag`);
    // before this, dragging with a tool armed panned the chart and drew nothing.
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('rectangle');

    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 10, y: 10 } });
    chart.emit('click', { id: null, time: 1700003600, price: 108, paneIndex: 0, point: { x: 90, y: 40 }, viaDrag: true });

    expect(draw.drawings()).toHaveLength(1);
    const d = draw.drawings()[0];
    expect(d.tool).toBe('rectangle');
    // Both anchors distinct: a degenerate rect renders as nothing at all.
    expect(d.points).toEqual([
      { time: 1700000600, price: 101 },
      { time: 1700003600, price: 108 },
    ]);
  });

  // A brush is `points: 0` like `polyline`, so it used to collect one vertex per
  // click and never terminate: you got a polyline instead of ink. Freehand
  // tools sample `crosshair:move` while the pointer is held and commit on
  // release.
  const stroke = (chart: Chart, pts: readonly [number, number][], pane = 0): void => {
    chart.emit('click', { id: null, time: pts[0][0], price: pts[0][1], paneIndex: pane, point: { x: 0, y: 0 } });
    for (const [time, price] of pts) {
      chart.emit('crosshair:move', { time, price, paneIndex: pane, bar: null, point: { x: 0, y: 0 }, pressed: true });
    }
    const last = pts[pts.length - 1];
    chart.emit('click', { id: null, time: last[0], price: last[1], paneIndex: pane, point: { x: 0, y: 0 }, viaDrag: true });
  };

  for (const tool of ['brush', 'highlighter'] as const) {
    it(`${tool} inks one stroke per press-drag-release, not a vertex per click`, () => {
      const { chart } = makeChart();
      const draw = new DrawingController(chart);
      draw.setTool(tool);

      stroke(chart, [[1700000600, 101], [1700001200, 103], [1700001800, 102], [1700002400, 105]]);

      expect(draw.drawings()).toHaveLength(1);
      const d = draw.drawings()[0];
      expect(d.tool).toBe(tool);
      // Every sampled position is kept: that curve is the whole point.
      expect(d.points).toHaveLength(4);
      expect(d.points[0]).toEqual({ time: 1700000600, price: 101 });
      expect(d.points[3]).toEqual({ time: 1700002400, price: 105 });
      // ...and the gesture ended, rather than staying open for more clicks.
      expect(draw.activeTool()).toBeNull();
    });
  }

  it('a selected brush stroke offers only its two end handles', () => {
    // One anchor per sample means one handle per sample: dozens of circles
    // burying the ink, and no way to grab the stroke itself.
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    // A zigzag, so every sample is a corner the thinning has to keep.
    const pts: [number, number][] = Array.from({ length: 30 }, (_, i) => [1700000600 + i * 60, 100 + i * 0.2 + (i % 2)]);
    stroke(chart, pts);

    const d = draw.drawings()[0];
    expect(d.points).toHaveLength(30);   // every corner survives the thinning
    draw.select(d.id);

    const layer = new DrawingLayer();
    layer.setDrawings(draw.drawings());
    layer.setSelected([d.id]);
    const rc = {
      timeScale: { indexToX: (i: number) => i * 5 },
      priceScale: { priceToY: (p: number) => 300 - p, format: (p: number) => p.toFixed(2) },
      dataLayer: { timeToIndexFloat: (t: number) => (t - 1700000600) / 60, indexToTimeFloat: (i: number) => i },
      plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
    } as never;
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, rc);
    // ...but only two of them are drawn as grab handles.
    expect(rec.ops.filter((o) => o.type === 'arc')).toHaveLength(2);
  });

  // `points: 0` tools collect anchors until something ends them, and nothing
  // could: double-click reset the view instead. They were unfinishable.
  for (const tool of ['polyline', 'path'] as const) {
    it(`${tool} finishes on double-click`, () => {
      const { chart } = makeChart();
      const draw = new DrawingController(chart);
      draw.setTool(tool);
      for (const [t, p] of [[1700000600, 101], [1700001200, 104], [1700001800, 102]]) {
        chart.emit('click', { id: null, time: t, price: p, paneIndex: 0, point: { x: 0, y: 0 } });
      }
      expect(draw.drawings()).toHaveLength(0);   // still collecting

      chart.emit('dblclick', {});
      expect(draw.drawings()).toHaveLength(1);
      expect(draw.drawings()[0].points).toHaveLength(3);
      expect(draw.activeTool()).toBeNull();
    });
  }

  it('a double-click with nothing pending is harmless', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    expect(draw.finish()).toBe(false);
    chart.emit('dblclick', {});
    expect(draw.drawings()).toHaveLength(0);
  });

  it('does not finish a fixed-anchor tool early on double-click', () => {
    // A rectangle needs its second anchor; a stray double-click must not commit
    // a one-anchor degenerate shape.
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('rectangle');
    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 0, y: 0 } });
    chart.emit('dblclick', {});
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.activeTool()).toBe('rectangle');
  });

  it('drops a freehand tap that never moved', () => {
    // One sample is not a stroke; committing it would leave an unclickable dot.
    const { chart } = makeChart();
    const draw = new DrawingController(chart, { stayInDrawingMode: true });
    draw.setTool('brush');

    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 0, y: 0 } });
    chart.emit('crosshair:move', { time: 1700000600, price: 101, paneIndex: 0, bar: null, point: { x: 0, y: 0 }, pressed: true });
    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 0, y: 0 }, viaDrag: true });

    expect(draw.drawings()).toHaveLength(0);
  });

  it('does not ink while merely hovering with a brush armed', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart, { stayInDrawingMode: true });
    draw.setTool('highlighter');

    for (let i = 0; i < 5; i++) {
      chart.emit('crosshair:move', { time: 1700000600 + i * 60, price: 100 + i, paneIndex: 0, bar: null, point: { x: 0, y: 0 }, pressed: false });
    }
    chart.emit('click', { id: null, time: 1700000900, price: 103, paneIndex: 0, point: { x: 0, y: 0 }, viaDrag: true });

    expect(draw.drawings()).toHaveLength(0);
  });

  it('keeps a stroke inside the pane it started in', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');

    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 0, y: 0 } });
    chart.emit('crosshair:move', { time: 1700000600, price: 101, paneIndex: 0, bar: null, point: { x: 0, y: 0 }, pressed: true });
    chart.emit('crosshair:move', { time: 1700001200, price: 55, paneIndex: 1, bar: null, point: { x: 0, y: 0 }, pressed: true });
    chart.emit('crosshair:move', { time: 1700001800, price: 104, paneIndex: 0, bar: null, point: { x: 0, y: 0 }, pressed: true });
    chart.emit('click', { id: null, time: 1700001800, price: 104, paneIndex: 0, point: { x: 0, y: 0 }, viaDrag: true });

    const d = draw.drawings()[0];
    expect(d.paneIndex).toBe(0);
    expect(d.points).toHaveLength(2); // the pane-1 sample was rejected
  });

  for (const [tool, sign] of [['long-position', 1], ['short-position', -1]] as const) {
    it(`${tool} drops a default 2:1 box facing its way from a bare click`, () => {
      // Two clicks on the same spot: nothing was dragged, so the tool picks
      // the direction and sizes the box on screen (64 px of risk, 150 px wide).
      const { chart } = makeChart();
      const draw = new DrawingController(chart);
      draw.setTool(tool);

      chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });
      expect(draw.drawings()).toHaveLength(0);          // one click is not a box yet
      chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });

      expect(draw.drawings()).toHaveLength(1);
      const [entry, target, stop] = draw.drawings()[0].points;
      expect(entry).toEqual({ time: 1700003000, price: 100 });
      expect(Math.sign(target.price - entry.price)).toBe(sign);
      expect(Math.sign(stop.price - entry.price)).toBe(-sign);
      // Two parts reward to one of risk, measured on the (linear) screen.
      const reward = chart.priceToCoordinate(entry.price, 0)! - chart.priceToCoordinate(target.price, 0)!;
      const risk = chart.priceToCoordinate(stop.price, 0)! - chart.priceToCoordinate(entry.price, 0)!;
      expect(reward / risk).toBeCloseTo(2, 6);
      expect(Math.abs(risk)).toBeCloseTo(64, 6);
      // Width on screen too, so it is grabbable at any zoom.
      expect(chart.timeToCoordinate(target.time) - chart.timeToCoordinate(entry.time)).toBeCloseTo(150, 6);
      expect(stop.time).toBe(target.time);
      expect(draw.drawings()[0].points).toHaveLength(3);
    });
  }

  it('the second click is the target, and the stop lands opposite at 2:1', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('long-position');

    chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });
    chart.emit('click', { id: null, time: 1700003600, price: 104, paneIndex: 0, point: { x: 100, y: 10 } });

    const [entry, target, stop] = draw.drawings()[0].points;
    expect(target.price).toBeCloseTo(104, 6);
    expect(stop.price).toBeCloseTo(98, 6);              // half the reward, below the entry
    expect(target.time).toBeGreaterThan(entry.time);
    expect(stop.time).toBe(target.time);
  });

  it('a target released below the entry makes a short, whichever tool was armed', () => {
    // The armed tool only decides which way a bare click faces; a drag says
    // where the profit is, and the readout follows the geometry.
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('long-position');

    chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });
    chart.emit('click', { id: null, time: 1700003600, price: 96, paneIndex: 0, point: { x: 100, y: 80 } });

    const [entry, target, stop] = draw.drawings()[0].points;
    expect(target.price).toBeLessThan(entry.price);
    expect(stop.price).toBeGreaterThan(entry.price);
    expect(stop.price).toBeCloseTo(102, 6);
  });

  it('dragging the stop through the entry flips the target across it', () => {
    // Both levels on one side of the entry is not a trade. The moved level
    // stays under the hand; the other reflects, so the ratio survives.
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('long-position');
    chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });
    chart.emit('click', { id: null, time: 1700003600, price: 104, paneIndex: 0, point: { x: 100, y: 10 } });
    const d = draw.drawings()[0];
    const [, , stop] = d.points;

    chart.emit('drag', {
      id: `draw:${d.id}#2`, time: stop.time, price: 103, paneIndex: 0,
      fromTime: stop.time, fromPrice: stop.price,
    });
    chart.emit('drag:end', {});

    const [entry, target, moved] = draw.drawings()[0].points;
    expect(moved.price).toBeCloseTo(103, 6);            // the stop went where it was dragged
    expect(target.price).toBeCloseTo(96, 6);            // 104 reflected across 100
    expect(Math.sign(target.price - entry.price)).toBe(-Math.sign(moved.price - entry.price));
  });

  it('a points patch keeps the levels opposed too', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('long-position');
    chart.emit('click', { id: null, time: 1700003000, price: 100, paneIndex: 0, point: { x: 40, y: 40 } });
    chart.emit('click', { id: null, time: 1700003600, price: 104, paneIndex: 0, point: { x: 100, y: 10 } });
    const d = draw.drawings()[0];

    // Set the target below the entry while the stop is still below it.
    draw.update(d.id, { points: [d.points[0], { ...d.points[1], price: 97 }, d.points[2]] });

    const [entry, target, stop] = draw.drawings()[0].points;
    expect(target.price).toBeCloseTo(97, 6);
    expect(stop.price).toBeGreaterThan(entry.price);    // reflected: the patch did not move it
  });

  it('ignores the release click for a single-anchor tool', () => {
    // Otherwise dragging with `text` armed drops a second box where you let go.
    const { chart } = makeChart();
    const draw = new DrawingController(chart, { stayInDrawingMode: true });
    draw.setTool('text');

    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 10, y: 10 } });
    expect(draw.drawings()).toHaveLength(1);
    chart.emit('click', { id: null, time: 1700003600, price: 108, paneIndex: 0, point: { x: 90, y: 40 }, viaDrag: true });
    expect(draw.drawings()).toHaveLength(1);
  });

  it('arms and releases the chart placement mode with the tool', () => {
    const { chart } = makeChart();
    const modes: boolean[] = [];
    (chart as unknown as { setPlacementMode: (a: boolean) => void }).setPlacementMode = (a) => modes.push(a);
    const draw = new DrawingController(chart);

    draw.setTool('rectangle');
    expect(modes[modes.length - 1]).toBe(true);          // press must not pan
    chart.emit('click', { id: null, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 } });
    chart.emit('click', { id: null, time: 2, price: 2, paneIndex: 0, point: { x: 2, y: 2 }, viaDrag: true });
    expect(modes[modes.length - 1]).toBe(false);          // panning handed back

    draw.setTool('rectangle');
    draw.destroy();
    expect(modes[modes.length - 1]).toBe(false);          // never left armed
  });

  it('places a two-anchor tool over two clicks and selects it', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    expect(draw.activeTool()).toBe('trend-line');

    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 10, y: 10 } });
    expect(draw.drawings()).toHaveLength(0); // still one anchor short
    chart.emit('click', { id: null, time: 1700003600, price: 108, paneIndex: 0, point: { x: 90, y: 40 } });

    expect(draw.drawings()).toHaveLength(1);
    const d = draw.drawings()[0];
    expect(d.tool).toBe('trend-line');
    expect(d.points).toEqual([
      { time: 1700000600, price: 101 },
      { time: 1700003600, price: 108 },
    ]);
    expect(draw.selected()).toBe(d.id);
    expect(draw.activeTool()).toBeNull(); // returns to the cursor by default
  });

  it('stays in the tool when asked', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart, { stayInDrawingMode: true });
    draw.setTool('horizontal-line');
    chart.emit('click', { id: null, time: 1700000600, price: 101, paneIndex: 0, point: { x: 10, y: 10 } });
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.activeTool()).toBe('horizontal-line');
  });

  it('snaps to the nearest O/H/L/C when magnet is on', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart, { magnet: true });
    // The crosshair supplies the bar the magnet snaps against.
    chart.emit('crosshair:move', {
      time: 1700000600, price: 103.4, paneIndex: 0, bar: { open: 100, high: 104, low: 99, close: 101 },
    });
    draw.setTool('horizontal-line');
    chart.emit('click', { id: null, time: 1700000600, price: 103.4, paneIndex: 0, point: { x: 10, y: 10 } });
    expect(draw.drawings()[0].points[0].price).toBe(104); // nearest of O/H/L/C
  });

  it('drags a whole shape by the cursor delta', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
    });
    chart.emit('drag', { id: `draw:${d.id}`, time: 1000, price: 10, paneIndex: 0 });
    chart.emit('drag', { id: `draw:${d.id}`, time: 1500, price: 15, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(draw.get(d.id)?.points).toEqual([
      { time: 1500, price: 15 },
      { time: 2500, price: 25 },
    ]);
  });

  it('drags a single anchor by its handle', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
    });
    chart.emit('drag', { id: `draw:${d.id}#1`, time: 3000, price: 33, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(draw.get(d.id)?.points).toEqual([
      { time: 1000, price: 10 },   // untouched
      { time: 3000, price: 33 },
    ]);
  });

  it('refuses to drag a locked drawing', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {}, locked: true,
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
    });
    chart.emit('drag', { id: `draw:${d.id}`, time: 5000, price: 50, paneIndex: 0 });
    expect(draw.get(d.id)?.points[0]).toEqual({ time: 1000, price: 10 });
  });

  it('undoes a drag as one step, not one per frame', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
    });
    for (let i = 1; i <= 5; i++) {
      chart.emit('drag', { id: `draw:${d.id}`, time: 1000 + i * 100, price: 10 + i, paneIndex: 0 });
    }
    chart.emit('drag:end', {});
    draw.undo();
    expect(draw.get(d.id)?.points[0]).toEqual({ time: 1000, price: 10 });
  });

  it('undo / redo round-trips add and remove', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 10 }] });
    expect(draw.drawings()).toHaveLength(1);
    draw.remove(d.id);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.redo()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.redo()).toBe(false);
  });

  it('a new edit clears the redo branch', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }] });
    draw.undo();
    expect(draw.canRedo()).toBe(true);
    draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 2, price: 2 }] });
    expect(draw.canRedo()).toBe(false);
  });

  it('persists through the chart state and restores', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#abc' }, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    // The slot carries a versioned document, not a bare list.
    expect(state.drawings.version).toBe(2);
    expect(state.drawings.drawings).toHaveLength(1);
    expect(state.drawings.drawings[0].tool).toBe('rectangle');

    // A fresh chart + controller picks the drawings back up from the state.
    const other = makeChart();
    other.chart.restoreState(state);
    const draw2 = new DrawingController(other.chart);
    expect(draw2.drawings()).toHaveLength(1);
    expect(draw2.drawings()[0].style.color).toBe('#abc');
  });

  it('clicking empty space clears the selection', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }] });
    draw.select(d.id);
    expect(draw.selected()).toBe(d.id);
    chart.emit('click', { id: null, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 } });
    expect(draw.selected()).toBeNull();
  });

  it('clicking a drawing selects it', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }] });
    chart.emit('click', { id: `draw:${d.id}`, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 } });
    expect(draw.selected()).toBe(d.id);
  });

  it('rejects an unknown tool id', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    expect(() => draw.setTool('nope')).toThrow(/unknown drawing tool/);
  });

  it('destroy detaches its layers and listeners', () => {
    const { chart } = makeChart();
    const draw = new DrawingController(chart);
    draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }] });
    draw.destroy();
    // Events after destroy must not mutate the model.
    chart.emit('click', { id: null, time: 9, price: 9, paneIndex: 0, point: { x: 1, y: 1 } });
    expect(draw.drawings()).toHaveLength(1);
  });
});

describe('DrawingLayer hit-testing', () => {
  const rc = {
    timeScale: { indexToX: (i: number) => i },
    priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
    dataLayer: { timeToIndexFloat: (t: number) => t },
    plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  } as never;

  const line = (id: string): Drawing => ({
    id, tool: 'trend-line', paneIndex: 0, zIndex: 0,
    points: [{ time: 100, price: 100 }, { time: 200, price: 200 }],
    style: {},
  });

  it('hits the body within the grab radius and misses beyond it', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([line('a')]);
    expect(layer.hitTest(150, 150, rc)?.externalId).toBe('draw:a');
    expect(layer.hitTest(150, 400, rc)).toBeNull();
  });

  it('marks hits draggable so the chart arms a two-axis drag', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([line('a')]);
    expect(layer.hitTest(150, 150, rc)?.draggable).toBe(true);
  });

  it('an anchor handle of the selected drawing beats its body', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([line('a')]);
    layer.setSelected(['a']);
    const hit = layer.hitTest(100, 100, rc);
    expect(hit?.externalId).toBe('draw:a#0');
  });

  it('skips locked and hidden drawings', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([{ ...line('a'), locked: true }]);
    expect(layer.hitTest(150, 150, rc)).toBeNull();
    layer.setDrawings([{ ...line('b'), visible: false }]);
    expect(layer.hitTest(150, 150, rc)).toBeNull();
  });

  it('the newest drawing wins a tie', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([line('old'), line('new')]);
    expect(layer.hitTest(150, 150, rc)?.externalId).toBe('draw:new');
  });

  it('draws an in-progress preview alongside committed drawings', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([line('a')]);
    layer.setPreview({ ...line('__preview'), id: '__preview' });
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, rc);
    expect(rec.count('stroke')).toBe(2);
  });
});

describe('drawing shortcuts', () => {
  it('exposes the shortcuts the reference platform uses for the line tools', () => {
    const map = drawingShortcuts();
    expect(map['trend-line']).toBe('Alt+T');
    expect(map['horizontal-line']).toBe('Alt+H');
    expect(map['horizontal-ray']).toBe('Alt+J');
    expect(map['vertical-line']).toBe('Alt+V');
    expect(map['cross-line']).toBe('Alt+C');
  });

  it('matches a key event to its tool, case-insensitively', () => {
    expect(matchDrawingShortcut({ key: 't', altKey: true })).toBe('trend-line');
    expect(matchDrawingShortcut({ key: 'T', altKey: true })).toBe('trend-line');
    expect(matchDrawingShortcut({ key: 'h', altKey: true })).toBe('horizontal-line');
  });

  it('reads the letter from the physical key under Alt only where macOS Option types a symbol', () => {
    // What e.key holds for Option+T and Option+H on a US Mac layout.
    expect(matchDrawingShortcut({ key: String.fromCharCode(0x2020), code: 'KeyT', altKey: true })).toBe('trend-line');
    expect(matchDrawingShortcut({ key: String.fromCharCode(0x2d9), code: 'KeyH', altKey: true })).toBe('horizontal-line');
    expect(matchDrawingShortcut({ key: 't', code: 'KeyT', altKey: true })).toBe('trend-line');
    // A layout that types a letter keeps its own letters, as before 2.5.10:
    // on Dvorak the key labelled T sits where QWERTY has K.
    expect(matchDrawingShortcut({ key: 't', code: 'KeyK', altKey: true })).toBe('trend-line');
    expect(matchDrawingShortcut({ key: 'k', code: 'KeyT', altKey: true })).toBeNull();
  });

  it('requires the modifiers to match exactly, so it cannot shadow a host chord', () => {
    // Ctrl+Alt+T is a terminal shortcut on Linux; it must not arm a tool.
    expect(matchDrawingShortcut({ key: 't', altKey: true, ctrlKey: true })).toBeNull();
    expect(matchDrawingShortcut({ key: 't', altKey: true, shiftKey: true })).toBeNull();
  });

  it('never fires on a bare letter, so typing is unaffected', () => {
    expect(matchDrawingShortcut({ key: 't' })).toBeNull();
    expect(matchDrawingShortcut({ key: 'h', shiftKey: true })).toBeNull();
  });

  it('returns null for an unbound combination and an empty key', () => {
    expect(matchDrawingShortcut({ key: 'q', altKey: true })).toBeNull();
    expect(matchDrawingShortcut({ key: '', altKey: true })).toBeNull();
  });

  it('treats Cmd as Ctrl, so a Mac chord does not arm a tool either', () => {
    expect(matchDrawingShortcut({ key: 't', altKey: true, metaKey: true })).toBeNull();
  });

  it('lists the shortcut of a custom tool whatever its id, as its own key', () => {
    registerDrawingTool({ id: '__proto__', name: 'Odd id', points: 1, shortcut: 'Ctrl+Alt+F9', draw: () => {}, distance: () => 0 });
    const map = drawingShortcuts();
    expect(Object.keys(map)).toContain('__proto__');
    expect(Object.getOwnPropertyDescriptor(map, '__proto__')?.value).toBe('Ctrl+Alt+F9');
    // Still an ordinary object, so a host reading it with the usual methods keeps working.
    expect(Object.getPrototypeOf(map)).toBe(Object.prototype);
    expect(map['trend-line']).toBe('Alt+T');
  });
});
