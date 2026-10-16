/**
 * The icon sets, checked mechanically.
 *
 * Sixty-odd glyphs cannot be kept consistent by review. What makes a set look
 * drawn rather than assembled is not the quality of any single glyph, it is
 * that they share a grid, a stroke weight, a margin and a visual density; and
 * every one of those is a property a test can hold and a reader cannot.
 *
 * The previous hand-drawn sets in the demo and the terminal drifted on exactly
 * these axes because nothing checked them. This file is the reason the next
 * glyph added will match the ones before it, on either grid.
 */
import { describe, it, expect } from 'vitest';
import '../src/indicators/index';
import {
  DRAWING_TOOL_ICONS, drawingToolIcon, drawingToolIconIds,
  ICON_VIEWBOX, ICON_STROKE, ICON_ATTRS, ICON_SIZE,
  CHROME_ICONS, CHROME_ICON_FILLED, chromeIcon, chromeIconIds,
  CHROME_ICON_VIEWBOX, CHROME_ICON_STROKE, CHROME_ICON_ATTRS, CHROME_ICON_SIZE,
  DRAWING_TOOL_ACCENTS, drawingToolAccent, CHROME_ICON_ACCENTS, chromeIconAccent,
  chartTypeIcon, layoutIconPath,
  type IconAttrs, type LayoutIconSlot,
} from '../src/draw/icons';
import { chromeIconSvg, iconSvg } from '../src/draw/icon-svg';
import { registeredDrawingTools, registerBuiltinDrawingTools } from '../src/draw/index';
import { registeredChartTypes } from '../src/index';
import { registerTransformChartTypes } from '../src/transform/index';
import {
  clotted, coords, drawingKey, gridPoints, isClosed, subpathKey, subpaths,
} from './helpers/icon-geometry';

registerBuiltinDrawingTools();
registerTransformChartTypes();

/**
 * Every chrome id a host may code against, other than the chart types. The
 * ids are public API from the release that ships them: a host's toolbar
 * names them in its own source, so a rename or a removal breaks it, and this
 * list is the check that one does not happen by accident.
 */
const CHROME_ID_LIST = [
  // Shipped through 2.5.9.
  'cursor', 'magnet', 'lock', 'unlock', 'eye', 'eye-off', 'star', 'star-filled', 'trash', 'settings',
  'undo', 'redo', 'copy', 'paste', 'duplicate', 'front', 'back', 'text', 'chevron-down', 'chevron-right',
  'close', 'plus', 'minus', 'search', 'grid', 'link', 'unlink', 'camera', 'download',
  // Capture, navigation and the grid of charts.
  'capture-grid', 'chevron-up', 'chevron-left', 'chevrons-left', 'chevrons-right', 'check', 'more', 'grip', 'refresh', 'swap',
  'layout', 'maximize', 'restore', 'fullscreen', 'fullscreen-exit',
  'link-group', 'drawing-sync', 'crosshair', 'time-range', 'palette',
  // Time, the market session and replay.
  'calendar', 'clock', 'globe', 'market-open', 'market-pre', 'market-post', 'market-closed', 'market-holiday',
  'replay', 'play', 'pause', 'stop', 'step-forward', 'step-back', 'record',
  // The price scale, layouts and files.
  'scale-auto', 'scale-log', 'scale-percent',
  'folder', 'save', 'save-as', 'autosave', 'rename', 'recent', 'template', 'keyboard',
  // Status, drawing, text, panels and trading.
  'bell', 'bell-off', 'pin', 'pin-filled', 'info', 'warning', 'error', 'sun', 'moon',
  'eraser', 'measure', 'fill', 'bold', 'italic',
  'watchlist', 'news', 'account', 'compare', 'indicators',
  'buy', 'sell', 'close-position', 'reverse', 'bracket', 'dom-ladder',
  // Settings tabs and menu marks.
  'legend', 'axes', 'panels', 'trading', 'brush', 'above-series', 'behind-series', 'fit', 'coordinates',
  'line-dashed', 'line-dotted', 'line-mixed',
];

/** The transforms, by the id a host names each by; two of them are chart types as well. */
const TRANSFORM_IDS = ['heikin-ashi', 'renko', 'range-bars', 'line-break', 'point-figure', 'kagi'];

/**
 * The layouts a picker offers, as rows, columns and slots. Uneven ones are
 * spans: one tall pane beside two or three, one wide pane over two.
 */
const LAYOUTS: [string, number, number, LayoutIconSlot[] | undefined][] = [
  ['1x1', 1, 1, undefined], ['1x2', 1, 2, undefined], ['2x1', 2, 1, undefined], ['1x3', 1, 3, undefined],
  ['3x1', 3, 1, undefined], ['2x2', 2, 2, undefined], ['2x3', 2, 3, undefined], ['3x2', 3, 2, undefined],
  ['2x4', 2, 4, undefined], ['3x3', 3, 3, undefined], ['3x4', 3, 4, undefined], ['4x4', 4, 4, undefined],
  ['1+2', 2, 2, [{ row: 0, column: 0, rowSpan: 2 }, { row: 0, column: 1 }, { row: 1, column: 1 }]],
  ['2+1', 2, 2, [{ row: 0, column: 0 }, { row: 1, column: 0 }, { row: 0, column: 1, rowSpan: 2 }]],
  ['1+3', 3, 2, [{ row: 0, column: 0, rowSpan: 3 }, { row: 0, column: 1 }, { row: 1, column: 1 }, { row: 2, column: 1 }]],
  ['1/2', 2, 2, [{ row: 0, column: 0, columnSpan: 2 }, { row: 1, column: 0 }, { row: 1, column: 1 }]],
  ['2/1', 2, 2, [{ row: 0, column: 0 }, { row: 0, column: 1 }, { row: 1, column: 0, columnSpan: 2 }]],
];

/**
 * One row per tier. The invariants are the same on both grids; only the
 * numbers differ. The live area keeps the ink one pixel clear of the box at
 * native size: a stroke of 2 reaches a unit past its points, so the points
 * stay two units in on either grid. The minimum span is half the live area.
 */
interface Tier {
  name: string;
  entries: [string, string][];
  accents: [string, string][];
  registry: Readonly<Record<string, string>>;
  accentOf: (id: string) => string | undefined;
  attrs: IconAttrs;
  viewBox: string;
  stroke: number;
  grid: number;
  lo: number;
  hi: number;
  minSpan: number;
  maxCommands: number;
}

const TIERS: Tier[] = [
  {
    name: 'tool', entries: Object.entries(DRAWING_TOOL_ICONS), accents: Object.entries(DRAWING_TOOL_ACCENTS),
    registry: DRAWING_TOOL_ICONS, accentOf: drawingToolAccent, attrs: ICON_ATTRS,
    viewBox: ICON_VIEWBOX, stroke: ICON_STROKE, grid: 24, lo: 2, hi: 22, minSpan: 10, maxCommands: 14,
  },
  {
    name: 'chrome', entries: Object.entries(CHROME_ICONS), accents: Object.entries(CHROME_ICON_ACCENTS),
    registry: CHROME_ICONS, accentOf: chromeIconAccent, attrs: CHROME_ICON_ATTRS,
    viewBox: CHROME_ICON_VIEWBOX, stroke: CHROME_ICON_STROKE, grid: 16, lo: 2, hi: 14, minSpan: 7, maxCommands: 14,
  },
];

describe('the tool set covers the registry', () => {
  it('has a glyph for every registered drawing tool', () => {
    // The whole point of shipping these is that an adopter never has to draw
    // one. A tool with no glyph pushes that work straight back onto them.
    const missing = registeredDrawingTools()
      .map((t) => t.id)
      .filter((id) => drawingToolIcon(id) === undefined);
    expect(missing, `tools with no icon: ${missing.join(', ')}`).toEqual([]);
  });
});

describe.each(TIERS)('the $name set shares one grid', (tier) => {
  it.each(tier.entries)(`%s stays inside the ${tier.lo}..${tier.hi} live area`, (_id, d) => {
    // A glyph that reaches the edge of the box looks larger than its
    // neighbours, and a rail of them reads as ragged.
    for (const n of gridPoints(d)) {
      expect(n).toBeGreaterThanOrEqual(tier.lo);
      expect(n).toBeLessThanOrEqual(tier.hi);
    }
  });

  it.each(tier.entries)('%s lands on whole units', (_id, d) => {
    // With a stroke of 2, an orthogonal edge centred on an integer covers
    // exactly two device pixels at 1:1. Half units were the old set's
    // crispness bug: nothing landed on a pixel boundary at any size.
    for (const n of coords(d)) expect(Number.isInteger(n), `${n} in ${d}`).toBe(true);
  });

  it.each(tier.entries)('%s carries no presentation attributes of its own', (_id, d) => {
    // Weight, cap and colour belong to the host's one `<svg>`, so a glyph
    // cannot quietly opt out of the set.
    expect(d).not.toMatch(/stroke|fill|width|style|class/i);
  });

  it.each(tier.entries)('%s is a path, not a document', (_id, d) => {
    expect(d).not.toMatch(/[<>]/);
    expect(d.trim()).toMatch(/^[Mm]/);
  });
});

describe.each(TIERS)('the $name set has one visual weight', (tier) => {
  it('declares a single stroke, applied by the host', () => {
    expect(tier.attrs.strokeWidth).toBe(tier.stroke);
    expect(tier.attrs.fill).toBe('none');
    expect(tier.attrs.stroke).toBe('currentColor');
  });

  it('rounds every cap and join, so no glyph ends square beside a round one', () => {
    expect(tier.attrs.strokeLinecap).toBe('round');
    expect(tier.attrs.strokeLinejoin).toBe('round');
  });

  it('shares one viewBox', () => {
    expect(tier.viewBox).toBe(`0 0 ${tier.grid} ${tier.grid}`);
    expect(tier.attrs.viewBox).toBe(tier.viewBox);
  });
});

describe.each(TIERS)('the $name set is balanced', (tier) => {
  it('keeps every glyph within a sane complexity band', () => {
    // A glyph far busier than the rest dominates a rail whatever its weight.
    // Fib retracement and Gann box are the densest by nature; nothing should
    // be denser than they are.
    for (const [id, d] of tier.entries) {
      const commands = (d.match(/[A-Za-z]/g) ?? []).length;
      expect(commands, `${id} has ${commands} commands`).toBeLessThanOrEqual(tier.maxCommands);
      expect(commands, `${id} is empty`).toBeGreaterThan(0);
    }
  });

  it('uses most of the live area rather than floating small in the box', () => {
    // A glyph occupying a third of its box reads as a different size from one
    // that fills it, even at the same nominal dimensions.
    for (const [id, d] of tier.entries) {
      // Measured along the arcs, not only between endpoints: the halves of
      // the chrome `link` end two units inside the curves that give it its
      // width, and an endpoint span calls a twelve-unit glyph six.
      const pts = subpaths(d).flatMap((s) => s.extent);
      if (pts.length < 2) continue;
      const xs = pts.map((p) => p[0]);
      const ys = pts.map((p) => p[1]);
      const span = Math.round(Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)));
      expect(span, `${id} spans only ${span} units`).toBeGreaterThanOrEqual(tier.minSpan);
    }
  });

  it('has no duplicate glyph, however its subpaths are ordered or directed', () => {
    // 2.5.5 shipped long-position and short-position as one picture: the same
    // two boxes and stem, written in the other order. A string comparison
    // passed it. The key walks each glyph into absolute subpaths, sorts them
    // and reads each from a fixed end, so only a different drawing gets a
    // different key. The path alone is keyed, accents aside: it is the whole
    // glyph for a host that draws nothing else. The raster spec (icon-raster)
    // is the check for glyphs that differ on paper and still look alike.
    const seen = new Map<string, string>();
    for (const [id, d] of tier.entries) {
      const key = drawingKey(d);
      const prev = seen.get(key);
      expect(prev, `${id} draws the same as ${prev}`).toBeUndefined();
      seen.set(key, id);
    }
  });

  it('keys a glyph by its drawing, not by how the string was written', () => {
    // The key itself, pinned: a check that silently compares strings again
    // would pass every glyph set.
    expect(drawingKey('M3 5h18v5H3zM3 15h18v5H3z')).toBe(drawingKey('M3 15h18v5H3zM21 5H3v5h18z'));
    expect(drawingKey('M4 20 20 4')).toBe(drawingKey('M20 4 4 20'));
    expect(drawingKey('M2 12h20m-10-10v20')).toBe(drawingKey('M12 2v20M22 12H2'));
    expect(drawingKey('M4 20 20 4')).not.toBe(drawingKey('M4 20 20 5'));
    expect(drawingKey('M3 5h18v5H3z')).not.toBe(drawingKey('M3 5h18v5H3'));
    expect(drawingKey('M4 20 20 4M3 21a1 1 0 0 0 2 0a1 1 0 0 0-2 0z')).not.toBe(drawingKey('M4 20 20 4'));
  });

  it('keys curves and arcs by their drawing too', () => {
    // Lines and polygons were normalised and curves were not, so the same arc
    // drawn from its other end, or a dot started on its far side, keyed as a
    // different glyph. A curve reverses with its control points, an arc with
    // its sweep, and a closed ring of either may start at any of its joints.
    expect(drawingKey('M3 19a12 12 0 0 1 18 0')).toBe(drawingKey('M21 19a12 12 0 0 0-18 0'));
    expect(drawingKey('M4 19a1 1 0 0 0 2 0a1 1 0 0 0-2 0z')).toBe(drawingKey('M6 19a1 1 0 0 0-2 0a1 1 0 0 0 2 0z'));
    expect(drawingKey('M4 19a1 1 0 0 0 2 0a1 1 0 0 0-2 0z')).toBe(drawingKey('M4 19a1 1 0 0 1 2 0a1 1 0 0 1-2 0z'));
    expect(drawingKey('M3 18c4-12 14-12 18 0')).toBe(drawingKey('M21 18c-4-12-14-12-18 0'));
    expect(drawingKey('M2 12c3-9 6-9 9 0s6 9 9 0')).toBe(drawingKey('M2 12c3-9 6-9 9 0 3 9 6 9 9 0'));
    expect(drawingKey('M12 5c5 0 9 3 9 7s-4 7-9 7-9-3-9-7 4-7 9-7z'))
      .toBe(drawingKey('M21 12c0 4-4 7-9 7s-9-3-9-7 4-7 9-7 9 3 9 7z'));
    expect(drawingKey('M3 19a12 12 0 0 1 18 0')).not.toBe(drawingKey('M3 19a12 12 0 0 0 18 0'));
    expect(drawingKey('M3 18c4-12 14-12 18 0')).not.toBe(drawingKey('M3 18c4-11 14-12 18 0'));
  });

  it('leaves no hollow shape filled in by its own strokes', () => {
    // A shape wide enough to show a hole at the tier's line is drawn hollow
    // on purpose; if another stroke of the glyph runs through its middle, the
    // 2px line fills it and the glyph turns into a block. Marks an accent
    // fills are meant solid.
    for (const [id, d] of tier.entries) {
      if (tier.name === 'chrome' && CHROME_ICON_FILLED.has(id)) continue;
      const marks = new Set(subpaths(tier.accentOf(id) ?? '').map(subpathKey));
      expect(clotted(d, tier.stroke, marks), `${id} fills a hollow shape solid`).toEqual([]);
    }
  });
});

describe.each(TIERS)('the $name accents', (tier) => {
  // An accent fills the marks a glyph may carry: an anchor dot, a pole cap,
  // an arrowhead. The glyph's own path already draws each of them, so a host
  // that renders the path data and nothing else still gets every mark that
  // tells a glyph from its siblings, only outlined; the accent is the fill on
  // top, a second path because a fill is a presentation choice.
  const accents = tier.accents;

  it('belong to glyphs of their own tier', () => {
    for (const [id] of accents) expect(tier.registry[id], `${id} has an accent but no glyph`).toBeDefined();
    expect(accents.length).toBeGreaterThan(0);
  });

  it.each(accents)('%s fills marks its glyph already draws', (id, a) => {
    // The accent carries weight, never identity: every mark in it is also a
    // subpath of the glyph, so leaving it out loses a fill and nothing else.
    // Accents that held the only arrowhead or origin dot shipped a path-only
    // horizontal ray at 0.86 overlap with the horizontal line.
    const drawn = new Set(subpaths(tier.registry[id]).map(subpathKey));
    for (const mark of subpaths(a)) {
      expect(drawn.has(subpathKey(mark)), `${id}: the path does not draw ${subpathKey(mark)}`).toBe(true);
    }
  });

  it.each(accents)('%s lands on whole units inside the live area', (_id, a) => {
    // The same grid as the glyph it marks. The extent includes the arcs of a
    // dot, not only their endpoints: a dot is all arc.
    for (const n of coords(a)) expect(Number.isInteger(n), `${n} in ${a}`).toBe(true);
    for (const s of subpaths(a)) {
      for (const [px, py] of s.extent) {
        expect(px, a).toBeGreaterThanOrEqual(tier.lo - 1e-9);
        expect(px, a).toBeLessThanOrEqual(tier.hi + 1e-9);
        expect(py, a).toBeGreaterThanOrEqual(tier.lo - 1e-9);
        expect(py, a).toBeLessThanOrEqual(tier.hi + 1e-9);
      }
    }
  });

  it.each(accents)('%s carries no presentation attributes of its own', (_id, a) => {
    // The one-stroke rule holds for accents too: the fill is the only thing
    // the builders add, and the stroke comes from the frame like the glyph's.
    expect(a).not.toMatch(/stroke|fill|width|style|class|[<>]/i);
    expect(a.trim()).toMatch(/^M/);
  });

  it.each(accents)('%s is made of closed, small marks', (_id, a) => {
    // Closed, or the fill has no edge to stop at. Small, or it is a second
    // glyph painted solid: a mark spans at most a third of the grid.
    const marks = subpaths(a);
    expect(marks.length).toBeGreaterThan(0);
    expect(marks.length, `${a} has ${marks.length} marks`).toBeLessThanOrEqual(3);
    for (const s of marks) {
      expect(isClosed(s), `open mark in ${a}`).toBe(true);
      const xs = s.extent.map((p) => p[0]);
      const ys = s.extent.map((p) => p[1]);
      const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
      expect(span, `${a} spans ${span}`).toBeLessThanOrEqual(tier.grid / 3);
    }
  });

  it('answers undefined for a glyph that has none, and never for one that has', () => {
    for (const [id, a] of accents) expect(tier.accentOf(id)).toBe(a);
    const plain = tier.entries.find(([id]) => tier.accentOf(id) === undefined);
    expect(plain, 'every glyph has an accent, so none is optional').toBeDefined();
    expect(tier.accentOf('no-such-glyph')).toBeUndefined();
  });
});

describe('the two tiers read as one set', () => {
  it('pins each tier to the stroke and size it was drawn for', () => {
    expect([ICON_STROKE, ICON_SIZE]).toEqual([1.6, 20]);
    expect([CHROME_ICON_STROKE, CHROME_ICON_SIZE]).toEqual([1.3, 16]);
  });

  /** The line a tier draws on screen, in CSS pixels, at the size it is drawn for. */
  const linePx = (stroke: number, viewBox: string, size: number): number => stroke * size / Number(viewBox.split(' ')[2]);

  it.each([
    ['tool', ICON_STROKE, ICON_VIEWBOX, ICON_SIZE],
    ['chrome', CHROME_ICON_STROKE, CHROME_ICON_VIEWBOX, CHROME_ICON_SIZE],
  ] as const)('draws the %s line fine, at about 1.3px', (_name, stroke, viewBox, size) => {
    // Through 2.6.2 both tiers drew 2px: crisp edges, but nearly twice the ink of a
    // fine line, and the rail read as heavy beside the chart. Below a pixel
    // the curves break up on a 1x screen, so the band is narrow.
    const px = linePx(stroke, viewBox, size);
    expect(px).toBeGreaterThanOrEqual(1.2);
    expect(px).toBeLessThanOrEqual(1.4);
  });

  it('draws one line width on screen in both rails', () => {
    // A lock under the tools has to read as the same set, only smaller, so
    // the two strokes are matched at their display sizes, not as a fraction
    // of their boxes.
    const toolPx = linePx(ICON_STROKE, ICON_VIEWBOX, ICON_SIZE);
    const chromePx = linePx(CHROME_ICON_STROKE, CHROME_ICON_VIEWBOX, CHROME_ICON_SIZE);
    expect(Math.abs(chromePx - toolPx)).toBeLessThanOrEqual(0.05);
  });
});

describe('look-alike glyphs are drawn apart', () => {
  // Read from the path data alone, which is all some hosts draw: the marks
  // that tell siblings apart have to be in it, not only in the accent.
  const tool = (id: string): string => DRAWING_TOOL_ICONS[id];
  /** The closed marks of a glyph's path: its dots and heads. */
  const marks = (id: string) => subpaths(tool(id)).filter((s) => isClosed(s));
  /** The open strokes of a glyph's path. */
  const strokes = (id: string) => subpaths(tool(id)).filter((s) => !isClosed(s));
  /** The centre of each mark, from the extent it covers. */
  const centres = (id: string): [number, number][] => marks(id).map((s) => {
    const xs = s.extent.map((p) => p[0]);
    const ys = s.extent.map((p) => p[1]);
    return [Math.round((Math.min(...xs) + Math.max(...xs)) / 2), Math.round((Math.min(...ys) + Math.max(...ys)) / 2)];
  });
  const ends = (id: string): [number, number][] => {
    const s = strokes(id)[0];
    return [[s.start[0], s.start[1]], [s.points[s.points.length - 1][0], s.points[s.points.length - 1][1]]];
  };

  it('starts the ray at an origin dot, with no tick across it', () => {
    // The ray was a line with a short stroke across its start, which read as
    // a check mark. It is one line now, from a dot, open at the far end.
    expect(strokes('ray')).toHaveLength(1);
    expect(centres('ray')).toEqual([ends('ray')[0]]);
  });

  it('tells the line family apart by its ends', () => {
    // Same diagonal, different ends, because the ends are what differ between
    // the tools: a segment stops at both anchors, a ray at one, an extended
    // line at neither, and an arrow ends in a head.
    expect(centres('trend-line')).toEqual(ends('trend-line'));
    const [a, b] = ends('extended-line');
    for (const [cx, cy] of centres('extended-line')) {
      expect(cx).toBeGreaterThan(Math.min(a[0], b[0]));
      expect(cx).toBeLessThan(Math.max(a[0], b[0]));
      expect(cy).toBeGreaterThan(Math.min(a[1], b[1]));
      expect(cy).toBeLessThan(Math.max(a[1], b[1]));
    }
    expect(centres('extended-line')).toHaveLength(2);
    expect(marks('arrow')).toHaveLength(1);
    const keys = ['trend-line', 'ray', 'extended-line', 'arrow'].map((id) => marks(id).map(subpathKey).sort().join(' | '));
    expect(new Set(keys).size).toBe(keys.length);
    // The info line is a segment that also labels itself: a segment's ends,
    // and a label the plain segment does not have.
    expect(centres('info-line').filter(([x, y]) => centres('trend-line').some(([u, v]) => u === x && v === y)))
      .toEqual(centres('trend-line'));
    expect(subpaths(tool('info-line')).length).toBeGreaterThan(subpaths(tool('trend-line')).length);
  });

  it('starts the horizontal ray at a dot inside the grid, where the line runs edge to edge', () => {
    // The two sat at 0.86 overlap as path data: the ray was the line with its
    // start trimmed, and its dot lived only in the accent. The ray now leaves
    // from an anchor a third of the way in and reaches the far edge, as the
    // diagonal ray does, and the line keeps the full width.
    expect(centres('horizontal-ray')).toEqual([ends('horizontal-ray')[0]]);
    expect(ends('horizontal-ray')[0][0]).toBeGreaterThanOrEqual(8);
    expect(ends('horizontal-ray')[1][0]).toBe(22);
    expect(ends('horizontal-line').map(([x]) => x).sort((p, q) => p - q)).toEqual([2, 22]);
  });

  it('draws a short position as the long one turned over, not as the same picture', () => {
    // The direction is the difference, so the direction is what the glyph
    // shows: flipping one vertically gives the other, and nothing else does.
    const flip = (d: string): string => d.replace(/([MLHVCSQTA])([^A-Za-z]*)/gi, (_m, c: string, args: string) => {
      const n = (args.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
      const up = c.toUpperCase();
      const abs = c === up;
      const out = n.map((v, i) => {
        if (up === 'V') return abs ? 24 - v : -v;
        if (up === 'H') return v;
        if (up === 'A') return i % 7 === 4 ? 1 - v : i % 7 === 6 ? (abs ? 24 - v : -v) : v;
        return i % 2 === 1 ? (abs ? 24 - v : -v) : v;
      });
      return c + out.join(' ');
    });
    for (const [long, short] of [['long-position', 'short-position'], ['risk-reward-long', 'risk-reward-short']]) {
      expect(drawingKey(tool(long))).not.toBe(drawingKey(tool(short)));
      expect(drawingKey(flip(tool(long)))).toBe(drawingKey(tool(short)));
      const acc = drawingToolAccent(long);
      if (acc !== undefined) expect(drawingKey(flip(acc))).toBe(drawingKey(drawingToolAccent(short) ?? ''));
    }
  });
});

describe('the chrome tier', () => {
  it('ships every glyph a host rail, bar, menu and dialog need', () => {
    // A missing chrome glyph sends the host back to drawing its own, which is
    // the drift this registry exists to end.
    const missing = CHROME_ID_LIST.filter((id) => chromeIcon(id) === undefined);
    expect(missing, `chrome glyphs missing: ${missing.join(', ')}`).toEqual([]);
  });

  it('publishes exactly the listed ids besides the chart types, and at least eighty of them', () => {
    // An id that appears here without being listed is an id nobody agreed
    // to support; one that disappears breaks a host that names it.
    const ids = chromeIconIds().filter((id) => !id.startsWith('chart-'));
    expect([...ids].sort()).toEqual([...CHROME_ID_LIST].sort());
    expect(new Set(CHROME_ID_LIST).size).toBe(CHROME_ID_LIST.length);
    expect(ids.length).toBeGreaterThanOrEqual(80);
  });

  it.each(chromeIconIds())('%s renders as markup through the builder', (id) => {
    const svg = chromeIconSvg(id);
    expect(svg).toContain(`<path d="${CHROME_ICONS[id]}"/>`);
    expect(svg).toContain('viewBox="0 0 16 16"');
    expect(svg).toContain(`fill="${CHROME_ICON_FILLED.has(id) ? 'currentColor' : 'none'}"`);
  });

  it('marks only glyphs it actually has as filled', () => {
    for (const id of CHROME_ICON_FILLED) expect(chromeIcon(id), id).toBeDefined();
    expect(CHROME_ICON_FILLED.has('star-filled')).toBe(true);
    expect(CHROME_ICON_FILLED.has('star')).toBe(false);
  });

  it.each([...CHROME_ICON_FILLED])('%s has an area to fill', (id) => {
    // A fill paints only closed shapes; a glyph listed as filled with none
    // would draw as its outline and show no state change at all.
    expect(subpaths(chromeIcon(id)!).some(isClosed), `${id} has no closed shape`).toBe(true);
  });

  it('keeps the outline and the filled state of one control as two drawings', () => {
    for (const [off, on] of [['star', 'star-filled'], ['pin', 'pin-filled']]) {
      expect(drawingKey(chromeIcon(off)!)).not.toBe(drawingKey(chromeIcon(on)!));
      expect(CHROME_ICON_FILLED.has(off)).toBe(false);
      expect(CHROME_ICON_FILLED.has(on)).toBe(true);
    }
  });

  it('draws the filled star as a closed pentagram, so the nonzero rule fills its centre', () => {
    // The outline star has ten vertices and an empty middle. The pentagram is
    // five crossing edges: its centre pentagon has a winding of two and fills
    // solid under the default rule, which is what makes one path both a star
    // and its solid state without a presentation attribute in the registry.
    const d = chromeIcon('star-filled')!;
    expect(d.endsWith('z')).toBe(true);
    expect(gridPoints(d).length / 2).toBe(5);
    expect(gridPoints(chromeIcon('star')!).length / 2).toBe(10);
  });

  it('lists every id it covers, and nothing the tool tier covers by accident', () => {
    expect(chromeIconIds().length).toBe(Object.keys(CHROME_ICONS).length);
    expect(chromeIconIds()).toContain('undo');
    expect(chromeIcon('trend-line')).toBeUndefined();
  });
});

describe('the chart types', () => {
  it('has a glyph for every registered chart type, transforms included', () => {
    // The chart-type menu shows every type; one without a glyph leaves a gap
    // in the column of pictures, and a host fills it with its own drawing.
    const types = registeredChartTypes();
    expect(types).toContain('point-figure');
    expect(types).toContain('kagi');
    const missing = types.filter((t) => chartTypeIcon(t) === undefined);
    expect(missing, `chart types with no glyph: ${missing.join(', ')}`).toEqual([]);
  });

  it('has a glyph for every transform', () => {
    const missing = TRANSFORM_IDS.filter((t) => chartTypeIcon(t) === undefined);
    expect(missing, `transforms with no glyph: ${missing.join(', ')}`).toEqual([]);
  });

  it('draws nothing but chart types and transforms under the chart- prefix', () => {
    const known = new Set([...registeredChartTypes(), ...TRANSFORM_IDS]);
    const stray = chromeIconIds().filter((id) => id.startsWith('chart-') && !known.has(id.slice(6)));
    expect(stray).toEqual([]);
    expect(chromeIconIds().filter((id) => id.startsWith('chart-'))).toHaveLength(known.size);
  });

  it('reads the chrome entry of the same name, and nothing for a type a host registered', () => {
    for (const t of [...registeredChartTypes(), ...TRANSFORM_IDS]) expect(chartTypeIcon(t)).toBe(chromeIcon(`chart-${t}`));
    expect(chartTypeIcon('my-renderer')).toBeUndefined();
    expect(chartTypeIcon('')).toBeUndefined();
    // A chrome id that is not a chart type is not one through this lookup.
    expect(chartTypeIcon('settings')).toBeUndefined();
  });
});

describe('the layout glyphs', () => {
  const grid = { lo: 2, hi: 14 };

  it.each(LAYOUTS)('%s is drawn to the chrome grid', (_name, rows, columns, slots) => {
    const d = layoutIconPath(rows, columns, slots);
    expect(d).not.toMatch(/stroke|fill|width|style|class|[<>]/i);
    expect(d.startsWith('M2 2h12v12H2z'), 'the frame comes first').toBe(true);
    for (const n of coords(d)) expect(Number.isInteger(n), `${n} in ${d}`).toBe(true);
    for (const n of gridPoints(d)) {
      expect(n).toBeGreaterThanOrEqual(grid.lo);
      expect(n).toBeLessThanOrEqual(grid.hi);
    }
  });

  it.each(LAYOUTS)('%s leaves a pixel clear between any two parallel lines', (_name, rows, columns, slots) => {
    // A 2px line either side of a whole unit: centres three units apart
    // leave one clear pixel, and closer ones merge into a block at 16px.
    const d = layoutIconPath(rows, columns, slots);
    for (const axis of [0, 1] as const) {
      const at = [...new Set(subpaths(d).flatMap((s) => s.segments
        .filter((g) => g.from[axis] === g.to[axis]).map((g) => g.from[axis])))].sort((a, b) => a - b);
      for (let i = 1; i < at.length; i++) expect(at[i] - at[i - 1], `${d}`).toBeGreaterThanOrEqual(3);
    }
  });

  it('draws every layout differently', () => {
    const seen = new Map<string, string>();
    for (const [name, rows, columns, slots] of LAYOUTS) {
      const key = drawingKey(layoutIconPath(rows, columns, slots));
      expect(seen.get(key), `${name} draws the same as ${seen.get(key)}`).toBeUndefined();
      seen.set(key, name);
    }
  });

  it('splits a grid evenly, and leaves out the dividers inside a spanning pane', () => {
    expect(layoutIconPath(1, 1)).toBe('M2 2h12v12H2z');
    expect(layoutIconPath(2, 2)).toBe('M2 2h12v12H2zM8 2 8 14M2 8 14 8');
    expect(layoutIconPath(1, 3)).toBe('M2 2h12v12H2zM6 2 6 14M10 2 10 14');
    expect(layoutIconPath(4, 1)).toBe('M2 2h12v12H2zM2 5 14 5M2 8 14 8M2 11 14 11');
    // One tall pane on the left: the column divider runs the full height,
    // the row divider only across the right-hand column.
    expect(layoutIconPath(2, 2, [{ row: 0, column: 0, rowSpan: 2 }, { row: 0, column: 1 }, { row: 1, column: 1 }]))
      .toBe('M2 2h12v12H2zM8 2 8 14M8 8 14 8');
    // One pane across the whole grid is the plain frame.
    expect(layoutIconPath(3, 3, [{ row: 0, column: 0, rowSpan: 3, columnSpan: 3 }])).toBe(layoutIconPath(1, 1));
  });

  it('draws a cell no slot claims as a pane of its own', () => {
    expect(layoutIconPath(2, 2, [{ row: 0, column: 0 }])).toBe(layoutIconPath(2, 2));
    expect(layoutIconPath(2, 2, [])).toBe(layoutIconPath(2, 2));
  });

  it('refuses what a 16px tile cannot show, and slots that do not fit', () => {
    for (const [rows, columns] of [[0, 1], [1, 0], [5, 1], [1, 5], [1.5, 2], [Number.NaN, 2], [2, Number.POSITIVE_INFINITY]]) {
      expect(() => layoutIconPath(rows, columns), `${rows}x${columns}`).toThrow(RangeError);
    }
    expect(() => layoutIconPath(2, 2, [{ row: 2, column: 0 }])).toThrow(RangeError);
    expect(() => layoutIconPath(2, 2, [{ row: 0, column: 1, columnSpan: 2 }])).toThrow(RangeError);
    expect(() => layoutIconPath(2, 2, [{ row: 0, column: 0, rowSpan: 0 }])).toThrow(RangeError);
    expect(() => layoutIconPath(2, 2, [{ row: -1, column: 0 }])).toThrow(RangeError);
    expect(() => layoutIconPath(2, 2, [{ row: 0, column: 0, rowSpan: 2 }, { row: 1, column: 0 }])).toThrow(/overlaps/);
  });
});

describe('the lookup', () => {
  it('returns undefined for an unknown tool rather than a placeholder', () => {
    // A host handed a question mark ships it; one handed nothing sees the gap.
    expect(drawingToolIcon('no-such-tool')).toBeUndefined();
    expect(chromeIcon('no-such-button')).toBeUndefined();
  });

  it('reads only its own entries, never a name every object inherits', () => {
    // The registries are plain objects: `toString` is a function there, and
    // was handed back as path data where an unknown id gives undefined.
    for (const id of ['toString', 'constructor', 'hasOwnProperty', '__proto__']) {
      expect(drawingToolIcon(id), id).toBeUndefined();
      expect(drawingToolAccent(id), id).toBeUndefined();
      expect(chromeIcon(id), id).toBeUndefined();
      expect(chromeIconAccent(id), id).toBeUndefined();
      expect(() => chromeIconSvg(id), id).toThrow(/no chrome icon/);
      expect(() => iconSvg(id), id).toThrow(/no tool icon/);
    }
  });

  it('lists every id it covers', () => {
    expect(drawingToolIconIds().length).toBe(Object.keys(DRAWING_TOOL_ICONS).length);
    expect(drawingToolIconIds()).toContain('trend-line');
  });
});
