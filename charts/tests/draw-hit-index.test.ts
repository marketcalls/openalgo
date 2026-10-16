/**
 * The drawing layer's hit prefilter (src/draw/hit-index.ts).
 *
 * Two contracts. A tool's box covers every point its `distance` calls a hit,
 * at either grab radius, over random drawings of every shape the tool takes;
 * and a layer that skips drawings by their boxes answers every hover exactly
 * as a layer that asks every drawing does, through pans, zooms, rescales,
 * resizes, new bars, a pointer change, edits and a tool registered again.
 * Then the point of it: a hover over 500 drawings asks only the few near it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BUILTIN_DRAWING_TOOLS, DrawingLayer, getDrawingTool, hasDrawingTool, registerDrawingTool, sortByZIndex,
  TREND_LINE, HORIZONTAL_LINE, RECTANGLE, TEXT,
  type Drawing, type DrawingTool,
} from '../src/draw/index';
import { projectAnchors } from '../src/draw/layer';
import { toolHitBox, inHitBox } from '../src/draw/hit-index';
import { anchorCount } from '../src/draw/viewport';
import { DataLayer } from '../src/model/data-layer';
import { SessionCalendar } from '../src/feed/instrument';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveHit, PrimitiveRenderContext } from '../src/primitives/primitive';

const T0 = 1_700_000_000;

/** A seeded generator, so a failure names inputs that reproduce. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
}

/**
 * Bars that look like a market: a random walk whose volatility clusters, with
 * an overnight gap every 75 bars, so the time axis and the price range are
 * what a hover really meets.
 */
function marketBars(count: number, seed = 7): { time: number; open: number; high: number; low: number; close: number }[] {
  const rnd = seeded(seed);
  const out = [];
  let price = 1840, vol = 1.2, time = T0;
  for (let i = 0; i < count; i++) {
    vol = Math.max(0.3, Math.min(6, vol * (0.9 + rnd() * 0.22) + (rnd() < 0.03 ? 2 : 0)));
    const open = price;
    const close = Math.max(1, open + (rnd() - 0.5) * 2 * vol);
    out.push({ time, open, high: Math.max(open, close) + rnd() * vol, low: Math.min(open, close) - rnd() * vol, close });
    price = close;
    time += (i + 1) % 75 === 0 ? 60 * 60 * 17 : 60;
  }
  return out;
}

// ── 1. every box covers every hit ─────────────────────────────────────────

/** A render context with affine scales, as the layer's own tests use. */
function affineRc(width: number, height: number, rnd: () => number): PrimitiveRenderContext {
  const spacing = 1 + rnd() * 12, origin = rnd() * width;
  const top = 1900 + rnd() * 100, perPrice = height / (80 + rnd() * 300);
  return {
    plotWidth: width, plotHeight: height, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
    timeScale: { indexToX: (i: number) => origin + i * spacing },
    dataLayer: { timeToIndexFloat: (t: number) => (t - T0) / 60, length: 0 },
    priceScale: { priceToY: (p: number) => (top - p) * perPrice, format: (v: number) => v.toFixed(2) },
  } as unknown as PrimitiveRenderContext;
}

const pick = <T>(rnd: () => number, list: readonly T[]): T => list[Math.floor(rnd() * list.length)];

const TEXTS = ['', 'Swing low', 'Breakout\nretest', 'Level|Price\nEntry|1842.5\nStop|1830', 'Earnings\nguidance\nraised'];

/** A random drawing of `tool`, in data space or, where the tool allows it, pinned to the plot. */
function randomDrawing(tool: DrawingTool, rnd: () => number, id: string): Drawing {
  const count = tool.points > 0 ? tool.points + (tool.id.endsWith('position') && rnd() < 0.5 ? 1 : 0) : 2 + Math.floor(rnd() * 6);
  const levels = rnd() < 0.5 ? undefined : Array.from({ length: 1 + Math.floor(rnd() * 5) }, () => ({
    ratio: pick(rnd, [0, 0.236, 0.5, 1, 1.618, -0.5, 2.618, 4.236, NaN]),
    enabled: rnd() < 0.85 ? undefined : false,
  }));
  const style = {
    extendLeft: pick(rnd, [undefined, true, false]),
    extendRight: pick(rnd, [undefined, true, false]),
    fill: pick(rnd, [undefined, true, false]),
    lineWidth: pick(rnd, [undefined, 1, 2.5, 18, 40]),
    levels,
  };
  const text = rnd() < 0.3 ? undefined : { value: pick(rnd, TEXTS), fontSize: pick(rnd, [undefined, 9, 14, 28]) };
  const viewport = tool.viewport === true && rnd() < 0.4;
  // Anchors near each other, far apart, steep, level, and past the last bar.
  const spread = pick(rnd, [3, 40, 400, 4000]);
  const base = rnd() * 300 - 20;
  const points = Array.from({ length: count }, () => ({
    time: T0 + (base + (rnd() - 0.5) * spread) * 60,
    price: 1850 + (rnd() - 0.5) * pick(rnd, [0.5, 20, 200, 2000]),
  }));
  if (rnd() < 0.1) points[1 % count] = { ...points[0] }; // coincident anchors
  if (rnd() < 0.1 && count > 1) points[1] = { time: points[0].time, price: points[1].price }; // upright
  if (rnd() < 0.1 && count > 1) points[1] = { time: points[1].time, price: points[0].price }; // level
  return {
    id, tool: tool.id, paneIndex: 0, zIndex: 0, style, text, points: viewport ? [] : points,
    ...(viewport ? { space: 'viewport' as const, viewportPoints: points.map(() => ({ x: rnd() * 1.4 - 0.2, y: rnd() * 1.4 - 0.2 })) } : {}),
  } as Drawing;
}

describe('a tool box covers every point the tool calls a hit', () => {
  const covered = BUILTIN_DRAWING_TOOLS.filter((tool) => {
    const d = randomDrawing(tool, seeded(1), 'probe');
    const rc = affineRc(800, 500, seeded(2));
    return toolHitBox(tool, projectAnchors(rc, d), d, rc, 6) !== undefined;
  });

  it('knows the common tools, and leaves the rest to be asked every time', () => {
    const left = BUILTIN_DRAWING_TOOLS.filter((t) => !covered.includes(t)).map((t) => t.id).sort();
    // Rays out of the anchors in every direction, or geometry read off the
    // bars: nothing a box short of the whole plot can hold.
    expect(left).toEqual([
      'anchored-vwap', 'cross-line', 'dedekind-tessellation', 'disjoint-channel', 'fib-circles', 'fib-extension-two-point',
      'fib-speed-resistance-arcs', 'fib-speed-resistance-fan', 'fib-spiral', 'fib-wedge', 'fixed-range-volume-profile',
      'flat-top-bottom', 'gann-square', 'golden-sonic', 'golden-supersonic', 'icon-stamp', 'info-line',
      'inside-pitchfork', 'modified-schiff-pitchfork', 'pitchfork', 'regression-channel', 'schiff-pitchfork', 'sonic',
      'supersonic', 'trend-angle', 'trend-fib-time',
    ]);
    expect(covered.length).toBe(BUILTIN_DRAWING_TOOLS.length - left.length);
  });

  for (const tool of covered) it(tool.id, () => coversEveryHit(tool, toolHitBox));
});

/**
 * Probe random drawings of `tool`, at both grab radii, for a hit its box
 * leaves out. `boxOf` is passed in so a test can run it against modules
 * loaded afresh, with a canvas to measure text on.
 */
function coversEveryHit(tool: DrawingTool, boxOf: typeof toolHitBox): void {
  const rnd = seeded(tool.id.split('').reduce((h, c) => Math.imul(h, 31) + c.charCodeAt(0), 11));
  let checked = 0;
  for (let n = 0; n < 40; n++) {
    const width = 300 + rnd() * 900, height = 150 + rnd() * 600;
    const rc = affineRc(width, height, rnd);
    const d = randomDrawing(tool, rnd, `d${n}`);
    if (anchorCount(d) < Math.max(1, tool.points)) continue;
    const pts = projectAnchors(rc, d);
    for (const grab of [6, 12]) {
      const box = boxOf(tool, pts, d, rc, grab)!;
      const probes: { x: number; y: number }[] = [];
      for (let i = 0; i < 120; i++) probes.push({ x: rnd() * (width + 400) - 200, y: rnd() * (height + 400) - 200 });
      for (const p of pts) for (let i = 0; i < 25; i++) probes.push({ x: p.x + (rnd() - 0.5) * 6 * grab, y: p.y + (rnd() - 0.5) * 6 * grab });
      // Just outside each finite edge, anywhere along it within reach.
      const along = (lo: number, hi: number, fallback: number): number =>
        Number.isFinite(lo) && Number.isFinite(hi) ? lo + rnd() * (hi - lo) : fallback + (rnd() - 0.5) * 400;
      for (let i = 0; i < 40; i++) {
        const cy = along(box.y0, box.y1, pts[0]?.y ?? 0), cx = along(box.x0, box.x1, pts[0]?.x ?? 0);
        if (Number.isFinite(box.x0)) probes.push({ x: box.x0 - 0.001, y: cy });
        if (Number.isFinite(box.x1)) probes.push({ x: box.x1 + 0.001, y: cy });
        if (Number.isFinite(box.y0)) probes.push({ x: cx, y: box.y0 - 0.001 });
        if (Number.isFinite(box.y1)) probes.push({ x: cx, y: box.y1 + 0.001 });
      }
      for (const { x, y } of probes) {
        const dist = tool.distance(x, y, { pts: pts.map((p) => ({ ...p })), drawing: d, rc });
        if (dist === null || !Number.isFinite(dist) || dist > grab) continue;
        checked++;
        if (!inHitBox(box, x, y)) {
          expect.fail(`${tool.id}: a hit at (${x}, ${y}), distance ${dist}, grab ${grab}, lies outside ${JSON.stringify(box)} for ${JSON.stringify(d)} at ${JSON.stringify(pts)}`);
        }
      }
    }
  }
  // A box that is never tested proves nothing.
  expect(checked).toBeGreaterThan(20);
}

describe('with text measured on a canvas, a box still covers every hit', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  // The tools whose box follows their measured text: without a canvas they
  // fall back to fixed guesses, which the loop above already covers.
  for (const id of ['text', 'table', 'note', 'balloon', 'comment', 'signpost', 'price-note', 'price-label', 'callout', 'rectangle', 'ellipse']) {
    it(id, async () => {
      vi.stubGlobal('document', {
        createElement: () => ({ getContext: () => ({ font: '', save() {}, restore() {}, measureText: (s: string) => ({ width: s.length * 6.5 }) }) }),
      });
      vi.resetModules();
      const draw = await import('../src/draw/index');
      const index = await import('../src/draw/hit-index');
      coversEveryHit(draw.getDrawingTool(id), index.toolHitBox);
    });
  }
});

// ── 2. a layer answers as asking every drawing does ───────────────────────

const HANDLE = 5, GRAB = 6, TOUCH = 2;

/**
 * What a hover answered before the prefilter, restated from the layer as it
 * stood: every selected handle, then every body, top layer first, nearest
 * wins and a later shape wins a tie.
 */
function answerWithoutPrefilter(
  layers: readonly { layer: DrawingLayer; drawings: readonly Drawing[]; selected: readonly string[]; touch: boolean }[],
  x: number, y: number, rc: PrimitiveRenderContext,
): PrimitiveHit | null {
  const runnable = (d: Drawing): boolean => hasDrawingTool(d.tool) && (d.space !== 'viewport' || getDrawingTool(d.tool).viewport === true);
  const readOnly = (d: Drawing): boolean => d.policy?.editable === false;
  const touch = (own: boolean): boolean => {
    const kind = (rc as { pointerType?: unknown }).pointerType;
    return kind === 'touch' ? true : kind === 'mouse' || kind === 'pen' ? false : own;
  };
  for (const { drawings, selected, touch: own } of layers) {
    const radius = (touch(own) ? HANDLE * TOUCH : HANDLE) + 2;
    const sel = new Set(selected);
    for (const d of sortByZIndex(drawings)) {
      if (!sel.has(d.id) || d.locked === true || d.visible === false || !runnable(d) || readOnly(d)) continue;
      const pts = projectAnchors(rc, d);
      const freehand = getDrawingTool(d.tool).freehand === true && pts.length > 2;
      for (const i of freehand ? [0, pts.length - 1] : pts.map((_, k) => k)) {
        if (Math.hypot(x - pts[i].x, y - pts[i].y) <= radius) {
          return { externalId: `draw:${d.id}#${i}`, zOrder: 'top', distance: 0, cursor: 'grabbing', draggable: true };
        }
      }
    }
  }
  for (let li = 0; li < layers.length; li++) {
    const { layer, drawings, touch: own } = layers[li];
    const grab = touch(own) ? GRAB * TOUCH : GRAB;
    const sorted = sortByZIndex(drawings);
    let best: { d: Drawing; distance: number } | null = null;
    for (let i = sorted.length - 1; i >= 0; i--) {
      const d = sorted[i];
      if (d.visible === false || d.locked === true || d.policy?.selectable === false || !runnable(d)) continue;
      const tool = getDrawingTool(d.tool);
      if (anchorCount(d) < Math.max(1, tool.points)) continue;
      const dist = tool.distance(x, y, { pts: projectAnchors(rc, d), drawing: d, rc });
      if (dist === null || !Number.isFinite(dist) || dist > grab) continue;
      if (best === null || dist < best.distance) best = { d, distance: dist };
      if (dist === 0) break;
    }
    if (best === null) continue;
    const fixed = readOnly(best.d);
    const hit: PrimitiveHit = { externalId: `draw:${best.d.id}`, zOrder: 'top', distance: best.distance, cursor: fixed ? 'pointer' : 'move', draggable: !fixed };
    return li === 0 ? hit : { ...hit, paintedBy: layer };
  }
  return null;
}

interface Pane {
  data: DataLayer;
  time: TimeScale;
  price: PriceScale;
  width: number;
  height: number;
  pointerType?: 'mouse' | 'touch';
  readout?: PriceScale;
}

function paneContext(p: Pane): PrimitiveRenderContext {
  return {
    timeScale: p.time, priceScale: p.price, readoutPriceScale: p.readout, dataLayer: p.data,
    plotWidth: p.width, plotHeight: p.height, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
    ...(p.pointerType ? { pointerType: p.pointerType } : {}),
  } as PrimitiveRenderContext;
}

function makePane(bars: ReturnType<typeof marketBars>, width: number, height: number, range: { min: number; max: number }): Pane {
  const data = new DataLayer();
  const id = data.createSeries();
  data.setSeriesData(id, bars);
  const time = new TimeScale({ barSpacing: 6, rightOffset: 12 });
  time.setWidth(width);
  time.setBaseIndex(data.baseIndex);
  const price = new PriceScale();
  price.setHeight(height);
  price.setPriceRange(range);
  return { data, time, price, width, height };
}

/** A scene over every tool: past the last bar, pinned, text, long rays, locked, read-only, selected. */
function sceneDrawings(bars: ReturnType<typeof marketBars>, rnd: () => number, prefix: string): Drawing[] {
  const out: Drawing[] = [];
  const last = bars[bars.length - 1].time;
  for (const tool of BUILTIN_DRAWING_TOOLS) {
    for (let k = 0; k < 3; k++) {
      const d = randomDrawing(tool, rnd, `${prefix}${tool.id}-${k}`);
      if (d.space !== 'viewport') {
        d.points = d.points.map((_, i) => {
          // Anchors on real bars, between them, and past the last one.
          const at = bars[Math.floor(rnd() * bars.length)];
          const time = rnd() < 0.2 ? last + (i + 1) * 60 * (1 + Math.floor(rnd() * 40)) : at.time + (rnd() < 0.3 ? 30 : 0);
          return { time, price: at.low + (at.high - at.low) * rnd() + (rnd() < 0.1 ? (rnd() - 0.5) * 400 : 0) };
        });
      }
      d.zIndex = Math.floor(rnd() * 7) - 3;
      if (rnd() < 0.06) d.locked = true;
      if (rnd() < 0.06) d.visible = false;
      if (rnd() < 0.06) d.policy = { editable: false };
      if (rnd() < 0.04) d.policy = { selectable: false };
      out.push(d);
    }
  }
  // A plugin tool the table does not know, answered on every move.
  out.push({ id: `${prefix}plugin`, tool: 'test-plugin-ring', paneIndex: 0, zIndex: 0, style: {},
    points: [{ time: bars[60].time, price: bars[60].close }, { time: bars[90].time, price: bars[90].close }] });
  return out;
}

registerDrawingTool({
  id: 'test-plugin-ring', name: 'Plugin ring', points: 2, draw() {},
  distance: (x, y, c) => Math.abs(Math.hypot(x - c.pts[0].x, y - c.pts[0].y) - Math.hypot(c.pts[1].x - c.pts[0].x, c.pts[1].y - c.pts[0].y)),
});

describe('a layer with the prefilter answers every hover as before', () => {
  afterEach(() => { for (const tool of BUILTIN_DRAWING_TOOLS) registerDrawingTool(tool); });

  it('across two panes, three layers each, through every change a key follows', () => {
    const rnd = seeded(20260927);
    const bars = marketBars(400);
    const panes = [makePane(bars, 900, 420, { min: 1760, max: 1960 }), makePane(bars, 900, 180, { min: 1700, max: 2000 })];
    // The second pane quotes from a moved readout scale, as a left axis does.
    panes[1].readout = new PriceScale({ inverted: false });
    panes[1].readout.setHeight(180);
    panes[1].readout.setPriceRange({ min: 1800, max: 1900 });

    const groups = panes.map((pane, index) => {
      const all = sceneDrawings(bars, rnd, `p${index}-`);
      const top = new DrawingLayer('top'), band = new DrawingLayer('series'), bottom = new DrawingLayer('bottom');
      const split = { top: all.filter((d) => d.zIndex >= 1), band: all.filter((d) => d.zIndex === 0), bottom: all.filter((d) => d.zIndex < 0) };
      top.setDrawings(split.top); band.setDrawings(split.band); bottom.setDrawings(split.bottom);
      top.setBelow([band, bottom]);
      const selected = all.filter(() => rnd() < 0.15).map((d) => d.id);
      for (const layer of [top, band, bottom]) layer.setSelected(selected);
      return { pane, top, band, bottom, split, selected, touch: false };
    });

    let compared = 0, hits = 0;
    const compare = (label: string): void => {
      for (const g of groups) {
        const rc = paneContext(g.pane);
        const scene = [
          { layer: g.top, drawings: g.split.top, selected: g.selected, touch: g.touch },
          { layer: g.band, drawings: g.split.band, selected: g.selected, touch: g.touch },
          { layer: g.bottom, drawings: g.split.bottom, selected: g.selected, touch: g.touch },
        ];
        const oracleRc = g.pane.readout ? { ...rc, priceScale: g.pane.readout } : rc;
        const points: { x: number; y: number }[] = [];
        for (let i = 0; i < 250; i++) points.push({ x: rnd() * (g.pane.width + 80) - 40, y: rnd() * (g.pane.height + 80) - 40 });
        // Where the drawings are: on and around their anchors.
        for (const d of [...g.split.top, ...g.split.band, ...g.split.bottom]) {
          const pts = projectAnchors(oracleRc, d);
          for (const p of pts.slice(0, 3)) points.push({ x: p.x + (rnd() - 0.5) * 30, y: p.y + (rnd() - 0.5) * 30 });
        }
        // Twice, so the second pass answers from the boxes the first one kept.
        for (let pass = 0; pass < 2; pass++) {
          for (const { x, y } of points) {
            const got = g.top.hitTest(x, y, rc);
            const want = answerWithoutPrefilter(scene, x, y, oracleRc);
            // The painting layer by identity; everything else by value.
            const plain = (hit: PrimitiveHit | null): string => JSON.stringify(hit === null ? null : { ...hit, paintedBy: undefined });
            if (plain(got) !== plain(want) || got?.paintedBy !== want?.paintedBy) {
              expect.fail(`${label}: hover at (${x}, ${y}) answered ${plain(got)}, not ${plain(want)}`);
            }
            compared++;
            if (want !== null) hits++;
          }
        }
      }
    };

    compare('first hover');
    for (const g of groups) g.pane.time.setRightOffset(g.pane.time.rightOffset - 37.5);
    compare('after a pan');
    for (const g of groups) g.pane.time.setBarSpacing(2.5);
    compare('after a zoom');
    groups[0].pane.price.setPriceRange({ min: 1700, max: 2100 });
    groups[1].pane.readout!.setOptions({ mode: 'logarithmic' });
    compare('after a rescale');
    for (const g of groups) { g.pane.width = 640; g.pane.height = 300; g.pane.time.setWidth(640); g.pane.price.setHeight(300); }
    compare('after a resize');
    // New bars move every anchor placed past the old last bar.
    const more = marketBars(460).slice(400).map((b) => ({ ...b, time: b.time + 60 * 30 }));
    for (const g of groups) {
      g.pane.data.addBars(1, more);
      g.pane.time.setBaseIndex(g.pane.data.baseIndex);
    }
    compare('after new bars');
    for (const g of groups) { g.touch = true; for (const layer of [g.top, g.band, g.bottom]) layer.setPointerType('touch'); }
    compare('after a touch');
    for (const g of groups) { g.touch = false; for (const layer of [g.top, g.band, g.bottom]) layer.setPointerType('mouse'); }
    groups[0].pane.pointerType = 'touch';
    compare('with a touch in the render context');
    groups[0].pane.pointerType = undefined;
    // An edit in place, handed over again as the controller does.
    for (const g of groups) {
      for (const d of g.split.top) if (d.space !== 'viewport') d.points = d.points.map((p) => ({ time: p.time + 60 * 11, price: p.price * 1.004 }));
      g.top.setDrawings(g.split.top);
      g.selected = g.selected.slice(0, 3);
      for (const layer of [g.top, g.band, g.bottom]) layer.setSelected(g.selected);
    }
    compare('after an edit');
    // A built-in id registered again with a host's own geometry.
    registerDrawingTool({ ...HORIZONTAL_LINE, distance: (x, y, h) => Math.hypot(x - h.pts[0].x, y - h.pts[0].y) });
    registerDrawingTool({ ...TREND_LINE, distance: () => 0 });
    compare('after a tool is registered again');

    expect(compared).toBeGreaterThan(8000);
    // The scene is dense enough that the comparison covers hits, not only misses.
    expect(hits).toBeGreaterThan(compared / 10);
  }, 120_000);
});

// ── 3. the key: each thing it follows moves a drawing a hover must find ────

describe('a kept box goes when what placed it changes', () => {
  // Each case changes one thing the key reads and nothing else, so each part
  // of the key is pinned on its own. The drawing under test sits between two
  // notes pinned to the plot, first and last in paint order, whose anchors
  // project through no scale.
  const bars = marketBars(200);
  const pinned = (id: string, z: number): Drawing => ({ id, tool: 'text', paneIndex: 0, zIndex: z, style: {}, points: [],
    text: { value: id }, space: 'viewport', viewportPoints: [{ x: 0.02, y: z < 0 ? 0.02 : 0.9 }] });
  const trend = (): Drawing => ({ id: 't', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
    points: [{ time: bars[100].time, price: 1850 }, { time: bars[120].time, price: 1850 }] });

  function setup(
    drawing: Drawing, pane = makePane(bars, 800, 400, { min: 1800, max: 1900 }),
    opts: { bars?: boolean; pinned?: 'both' | 'first' | 'last' | 'none' } = {},
  ): { layer: DrawingLayer; pane: Pane; rc: () => PrimitiveRenderContext; mid: () => { x: number; y: number } } {
    const layer = new DrawingLayer();
    // Which pinned notes stand around the drawing in paint order: with one
    // gone, the drawing is itself the first or the last one the key projects.
    const notes = opts.pinned ?? 'both';
    layer.setDrawings([
      ...(notes === 'both' || notes === 'first' ? [pinned('first', -1)] : []),
      drawing,
      ...(notes === 'both' || notes === 'last' ? [pinned('last', 1)] : []),
    ]);
    // A study pane's render context has no price bars to hand over.
    const rc = (): PrimitiveRenderContext => ({ ...paneContext(pane), ...(opts.bars === false ? {} : { bars: () => pane.data.seriesBars(1) }) });
    const mid = (): { x: number; y: number } => {
      const pts = projectAnchors(rc(), drawing);
      return { x: (pts[0].x + pts[pts.length - 1].x) / 2, y: (pts[0].y + pts[pts.length - 1].y) / 2 };
    };
    // Measure once where the drawing is, so each change below starts from kept boxes.
    const first = mid();
    expect(layer.hitTest(first.x, first.y, rc())?.externalId).toBe(`draw:${drawing.id}`);
    return { layer, pane, rc, mid };
  }

  it('follows a pan', () => {
    const { layer, pane, rc, mid } = setup(trend());
    pane.time.setRightOffset(pane.time.rightOffset + 40);
    const p = mid();
    expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows a zoom', () => {
    const { layer, pane, rc, mid } = setup(trend());
    pane.time.setBarSpacing(20);
    const p = mid();
    expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows a new price range', () => {
    const { layer, pane, rc, mid } = setup(trend());
    pane.price.setPriceRange({ min: 1845, max: 1860 });
    const p = mid();
    expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows a scale mode, even one that maps its two probe prices where they were', () => {
    const level: Drawing = { ...trend(), points: [{ time: bars[100].time, price: 30 }, { time: bars[120].time, price: 30 }] };
    const { layer, pane, rc, mid } = setup(level, makePane(bars, 800, 400, { min: 1, max: 1000 }));
    // Linear and logarithmic agree at 1 and at 1000 on this range, and nowhere between.
    pane.price.setOptions({ mode: 'logarithmic' });
    const p = mid();
    expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
  });

  // The data cases hover just past the end that moved: along a level line, a
  // shift of the whole line leaves its middle where the old box still covers it.
  const dataPane = (): Pane => {
    const pane = makePane(bars, 800, 400, { min: 1800, max: 1900 });
    pane.time.setBarSpacing(20);
    pane.time.setRightOffset(-70);
    return pane;
  };

  it('follows a bar inserted inside the history, on a pane with no price bars to watch', () => {
    const d = trend();
    const { layer, pane, rc } = setup(d, dataPane(), { bars: false });
    // A late bar between two others: every later time moves one index right,
    // and the time scale, which counts from the last bar, has not been told.
    pane.data.update(1, { time: bars[50].time + 30, open: 1850, high: 1851, low: 1849, close: 1850 });
    const end = projectAnchors(rc(), d)[1];
    expect(layer.hitTest(end.x + 4, end.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows a window that rolls, one bar in and one out, on a pane with no price bars to watch', () => {
    const d = trend();
    const { layer, pane, rc } = setup(d, dataPane(), { bars: false });
    // A host keeping the last N bars: the count and the last index stay, and
    // every anchor moves one bar left.
    const last = bars[bars.length - 1];
    pane.data.setSeriesData(1, [...bars.slice(1), { ...last, time: last.time + 60 }]);
    const start = projectAnchors(rc(), d)[0];
    expect(layer.hitTest(start.x - 4, start.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows new price bars with the same count and the same ends', () => {
    const d = trend();
    const { layer, pane, rc } = setup(d, dataPane());
    // One bar early in the history leaves and one after the anchors arrives:
    // the axis keeps its length and both ends, and the anchors move one bar left.
    const next = bars.filter((_, i) => i !== 10);
    next.splice(149, 0, { ...bars[150], time: bars[150].time - 30 });
    pane.data.setSeriesData(1, next);
    const start = projectAnchors(rc(), d)[0];
    expect(layer.hitTest(start.x - 4, start.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows the same change on a pane with no price bars, through the drawings it can project', () => {
    const d = trend();
    const { layer, pane, rc } = setup(d, dataPane(), { bars: false, pinned: 'none' });
    const next = bars.filter((_, i) => i !== 10);
    next.splice(149, 0, { ...bars[150], time: bars[150].time - 30 });
    pane.data.setSeriesData(1, next);
    const start = projectAnchors(rc(), d)[0];
    expect(layer.hitTest(start.x - 4, start.y, rc())?.externalId).toBe('draw:t');
  });

  // Each probe of the key on its own: a change that leaves every other probe
  // exactly where it was, to the bit, and moves the drawing out of its box.
  for (const [probe, other] of [[0, 1], [1, 0]]) {
    it(`follows a zoom that keeps bar ${probe} where it was`, () => {
      const { layer, pane, rc, mid } = setup(trend());
      const kept = pane.time.indexToX(probe), moved = pane.time.indexToX(other);
      pane.time.setBarSpacing(8);
      pane.time.setRightOffset(pane.time.rightOffset + (pane.time.indexToX(probe) - kept) / 8);
      expect(pane.time.indexToX(probe)).toBe(kept);
      expect(pane.time.indexToX(other)).not.toBe(moved);
      const p = mid();
      expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
    });
  }

  for (const [probe, other, from, to, at] of [
    [1000, 1, { min: 950, max: 1050 }, { min: 900, max: 1100 }, 1020],
    [1, 1000, { min: 0.5, max: 1.5 }, { min: 0, max: 2 }, 1.2],
  ] as const) {
    it(`follows a rescale that keeps the price ${probe} where it was`, () => {
      const level: Drawing = { ...trend(), points: [{ time: bars[100].time, price: at }, { time: bars[120].time, price: at }] };
      const { layer, pane, rc, mid } = setup(level, makePane(bars, 800, 400, from));
      const kept = pane.price.priceToY(probe), moved = pane.price.priceToY(other);
      pane.price.setPriceRange(to);
      expect(pane.price.priceToY(probe)).toBe(kept);
      expect(pane.price.priceToY(other)).not.toBe(moved);
      const p = mid();
      expect(layer.hitTest(p.x, p.y, rc())?.externalId).toBe('draw:t');
    });
  }

  // A time at either end of the axis, moved with the count, the other times
  // and the drawings the key projects all as they were: on a pane with no
  // price bars, only the probe of that time sees it.
  const n = bars.length, t = (i: number): number => bars[i].time;
  for (const { at, time, view, anchors } of [
    // The first gap sizes every index left of the first bar.
    { at: 0, time: t(0) + 30, view: -189, anchors: [t(0) - 600, t(5)] },
    { at: 1, time: t(0) + 30, view: -189, anchors: [t(0) - 600, t(5)] },
    // The last bar starts the times still to come.
    { at: n - 1, time: t(n - 1) + 30, view: 30, anchors: [t(n - 1) + 600, t(n - 1) + 1200] },
    // The bar before it sizes the last gap.
    { at: n - 2, time: t(n - 2) + 20, view: 1, anchors: [t(n - 2) + 30, t(n - 1) + 600] },
  ]) {
    it(`follows bar ${at === 0 || at === 1 ? at : `n - ${n - at}`} of the time axis moving, on a pane with no price bars to watch`, () => {
      const d: Drawing = { ...trend(), points: anchors.map((time) => ({ time, price: 1850 })) };
      const pane = makePane(bars, 800, 400, { min: 1800, max: 1900 });
      pane.time.setBarSpacing(at >= n - 2 ? 40 : 20);
      pane.time.setRightOffset(view);
      const { layer, rc } = setup(d, pane, { bars: false });
      const ends = (): (number | undefined)[] => [0, 1, n - 2, n - 1].map((i) => pane.data.indexToTime(i));
      const before = ends(), start = projectAnchors(rc(), d)[0];
      pane.data.setSeriesData(1, bars.map((b, i) => (i === at ? { ...b, time } : b)));
      expect(pane.data.length).toBe(n);
      expect(ends().filter((v, i) => v !== before[i])).toHaveLength(1);
      const now = projectAnchors(rc(), d)[0];
      // The start moved left, out of the box kept for where it was.
      expect(now.x).toBeLessThan(start.x - 8);
      expect(layer.hitTest(now.x - 4, now.y, rc())?.externalId).toBe('draw:t');
    });
  }

  for (const notes of ['first', 'last'] as const) {
    it(`follows the same change through the ${notes === 'first' ? 'last' : 'first'} drawing alone`, () => {
      const d = trend();
      const { layer, pane, rc } = setup(d, dataPane(), { bars: false, pinned: notes });
      const next = bars.filter((_, i) => i !== 10);
      next.splice(149, 0, { ...bars[150], time: bars[150].time - 30 });
      pane.data.setSeriesData(1, next);
      const start = projectAnchors(rc(), d)[0];
      expect(layer.hitTest(start.x - 4, start.y, rc())?.externalId).toBe('draw:t');
    });
  }

  it('follows a session calendar, which moves every time past the last bar', () => {
    // Five-minute bars over one exchange session; the far anchor is the next
    // morning. Without a calendar the night counts in bars; with one it is skipped.
    const ist = (wall: string): number => Date.parse(`${wall}+05:30`) / 1000;
    const times: number[] = [];
    for (let t = ist('2026-02-02T09:15:00'); t <= ist('2026-02-02T15:25:00'); t += 300) times.push(t);
    const pane = makePane(times.map((time) => ({ time, open: 1850, high: 1852, low: 1848, close: 1850 })), 800, 400, { min: 1800, max: 1900 });
    pane.time.setBarSpacing(3);
    pane.time.setRightOffset(60);
    const ray: Drawing = { id: 't', tool: 'horizontal-ray', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: ist('2026-02-03T10:00:00'), price: 1850 }] };
    const { layer, rc } = setup(ray, pane);
    const before = projectAnchors(rc(), ray)[0];
    pane.data.setSessionCalendar(new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'] }));
    const after = projectAnchors(rc(), ray)[0];
    expect(after.x).toBeLessThan(before.x - 20);
    expect(layer.hitTest(after.x + 1, after.y, rc())?.externalId).toBe('draw:t');
  });

  it('follows the plot size, for a drawing pinned to the plot', () => {
    const box: Drawing = { id: 't', tool: 'rectangle', paneIndex: 0, zIndex: 0, style: { fill: true }, points: [],
      space: 'viewport', viewportPoints: [{ x: 0.6, y: 0.6 }, { x: 0.7, y: 0.7 }] };
    const { layer, pane, rc } = setup(box);
    pane.width = 1600;
    expect(layer.hitTest(1040, 260, rc())?.externalId).toBe('draw:t');
    pane.height = 900;
    expect(layer.hitTest(1040, 585, rc())?.externalId).toBe('draw:t');
  });

  it('follows a touch, whose grab reaches twice as far', () => {
    const { layer, rc, mid } = setup(trend());
    const p = mid();
    expect(layer.hitTest(p.x, p.y + 10, rc())).toBeNull();
    layer.setPointerType('touch');
    expect(layer.hitTest(p.x, p.y + 10, rc())?.externalId).toBe('draw:t');
  });

  it('follows a touch onto a handle', () => {
    const d = trend();
    const { layer, rc } = setup(d);
    layer.setSelected(['t']);
    const end = projectAnchors(rc(), d)[1];
    expect(layer.hitTest(end.x - 9, end.y - 5, rc())?.externalId).toBe('draw:t');
    layer.setPointerType('touch');
    expect(layer.hitTest(end.x - 9, end.y - 5, rc())?.externalId).toBe('draw:t#1');
  });

  it('follows a tool registered again under a built-in id', () => {
    const { layer, rc } = setup(trend());
    try {
      registerDrawingTool({ ...TREND_LINE, distance: () => 0 });
      expect(layer.hitTest(400, 380, rc())?.externalId).toBe('draw:t');
    } finally {
      registerDrawingTool(TREND_LINE);
    }
  });

  it('follows the drawing list', () => {
    const d = trend();
    const { layer, rc } = setup(d);
    d.points = [{ time: bars[20].time, price: 1820 }, { time: bars[40].time, price: 1820 }];
    layer.setDrawings([pinned('first', -1), d, pinned('last', 1)]);
    const pts = projectAnchors(rc(), d);
    expect(layer.hitTest((pts[0].x + pts[1].x) / 2, pts[0].y, rc())?.externalId).toBe('draw:t');
  });
});

describe('a text box follows the fonts', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('measures a note again once a font has loaded', async () => {
    // A document whose text widths change when its fonts finish loading. The
    // tools module measures through the one probe context it makes, so it is
    // loaded fresh with this document in place.
    let charWidth = 7;
    const fonts = new EventTarget();
    vi.stubGlobal('document', {
      fonts,
      createElement: () => ({ getContext: () => ({ font: '', measureText: (s: string) => ({ width: s.length * charWidth }) }) }),
    });
    vi.resetModules();
    const draw = await import('../src/draw/index');
    const layerModule = await import('../src/draw/layer');
    const pane = makePane(marketBars(200), 800, 400, { min: 1800, max: 1900 });
    const rc = paneContext(pane);
    const note: Drawing = { id: 'n', tool: 'text', paneIndex: 0, zIndex: 0, style: {}, text: { value: 'Support holds', fontSize: 14 },
      points: [{ time: T0 + 60 * 100, price: 1850 }] };
    const layer = new draw.DrawingLayer();
    layer.setDrawings([note]);
    const at = layerModule.projectAnchors(rc, note)[0];
    // 13 characters at 7 px, plus padding: well short of 200 px.
    expect(layer.hitTest(at.x + 60, at.y + 5, rc)?.externalId).toBe('draw:n');
    expect(layer.hitTest(at.x + 200, at.y + 5, rc)).toBeNull();
    charWidth = 20;
    fonts.dispatchEvent(new Event('loadingdone'));
    expect(layer.hitTest(at.x + 200, at.y + 5, rc)?.externalId).toBe('draw:n');
  });

  it('grabs a long note anywhere on its plate, as it is painted', async () => {
    // A plate paints as wide as its text, and the hit test used to assume 120
    // px whatever the text, so a long note could not be grabbed on its right.
    vi.stubGlobal('document', {
      createElement: () => ({ getContext: () => ({ font: '', save() {}, restore() {}, measureText: (s: string) => ({ width: s.length * 7 }) }) }),
    });
    vi.resetModules();
    const draw = await import('../src/draw/index');
    const layerModule = await import('../src/draw/layer');
    const pane = makePane(marketBars(200), 800, 400, { min: 1800, max: 1900 });
    const rc = paneContext(pane);
    // 30 characters at 7 px and 16 px of padding: a plate 226 px wide, its
    // top-left 16 px right of and 34 px above the pin.
    const note: Drawing = { id: 'n', tool: 'note', paneIndex: 0, zIndex: 0, style: {},
      text: { value: 'Breakout above the weekly high', fontSize: 12 }, points: [{ time: T0 + 60 * 100, price: 1850 }] };
    const layer = new draw.DrawingLayer();
    layer.setDrawings([note]);
    const pin = layerModule.projectAnchors(rc, note)[0];
    expect(layer.hitTest(pin.x + 16 + 200, pin.y - 34 + 5, rc)?.externalId).toBe('draw:n');
    expect(layer.hitTest(pin.x + 16 + 240, pin.y - 34 + 5, rc)).toBeNull();
  });

  it('grabs a price label on the pill it paints, centred up and to the right of its anchor', async () => {
    // The hit test assumed a 64 px box starting 18 px right of the anchor,
    // where the pill is centred there: its left half could not be grabbed.
    vi.stubGlobal('document', {
      createElement: () => ({ getContext: () => ({ font: '', save() {}, restore() {}, measureText: (s: string) => ({ width: s.length * 7 }) }) }),
    });
    vi.resetModules();
    const draw = await import('../src/draw/index');
    const layerModule = await import('../src/draw/layer');
    const pane = makePane(marketBars(200), 800, 400, { min: 1800, max: 1900 });
    const rc = paneContext(pane);
    // 21 characters at 7 px and 14 px of padding: a pill 161 px wide, centred
    // 18 px right of and 30 px above the anchor.
    const label: Drawing = { id: 'l', tool: 'price-label', paneIndex: 0, zIndex: 0, style: {},
      text: { value: 'Resistance zone ahead' }, points: [{ time: T0 + 60 * 100, price: 1850 }] };
    const layer = new draw.DrawingLayer();
    layer.setDrawings([label]);
    const at = layerModule.projectAnchors(rc, label)[0];
    expect(layer.hitTest(at.x - 50, at.y - 30, rc)?.externalId).toBe('draw:l');
    expect(layer.hitTest(at.x + 90, at.y - 30, rc)?.externalId).toBe('draw:l');
    expect(layer.hitTest(at.x + 110, at.y - 30, rc)).toBeNull();
  });
});

// ── 4. what it is for ─────────────────────────────────────────────────────

describe('a hover asks only the drawings near the pointer', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('asks a handful of 500 drawings per move, where it used to ask all 500', () => {
    const bars = marketBars(600);
    const pane = makePane(bars, 1000, 500, { min: 1700, max: 2000 });
    const rc = paneContext(pane);
    const rnd = seeded(500);
    const tools = [TREND_LINE, HORIZONTAL_LINE, RECTANGLE, TEXT];
    const spies = tools.map((tool) => vi.spyOn(tool, 'distance'));
    const first = bars.length - 150;
    const drawings: Drawing[] = Array.from({ length: 500 }, (_, i) => {
      const tool = tools[i % tools.length];
      const a = bars[first + Math.floor(rnd() * 140)], b = bars[Math.min(bars.length - 1, first + Math.floor(rnd() * 140) + 3)];
      return { id: String(i), tool: tool.id, paneIndex: 0, zIndex: 0, style: tool === RECTANGLE ? { fill: false } : {},
        text: tool === TEXT ? { value: 'Retest' } : undefined,
        points: tool.points === 1 ? [{ time: a.time, price: a.low + (a.high - a.low) * rnd() }]
          : [{ time: a.time, price: a.low }, { time: b.time, price: b.high }] };
    });
    const layer = new DrawingLayer();
    layer.setDrawings(drawings);
    layer.hitTest(500, 250, rc); // the first move measures
    for (const spy of spies) spy.mockClear();
    let moves = 0;
    for (let i = 0; i < 400; i++, moves++) layer.hitTest(40 + ((i * 37) % 900), 30 + ((i * 53) % 440), rc);
    const asked = spies.reduce((sum, spy) => sum + spy.mock.calls.length, 0) / moves;
    expect(asked).toBeLessThan(15);
  });
});
