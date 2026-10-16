/**
 * Glyphs for the drawing tools and for host chrome, as path data.
 *
 * The engine ships no DOM, and this does not change that: an icon here is a
 * string of SVG path commands, not an element. The host still builds its own
 * toolbar, flyouts and rail; what it no longer has to do is draw every glyph
 * before it can show them. `icon-svg.ts` turns these into markup strings for a
 * host that wants the convenience; this file is the single source both of them
 * and every other surface read from.
 *
 * That was the real cost of leaving them out. Every adopter drew their own set,
 * each drifted on stroke weight, grid and visual density independently, and the
 * result read as sixty icons rather than as one set, however carefully any
 * single glyph was made. A shipped set is worth more than a better glyph.
 *
 * # Two tiers, one line
 *
 * Tool glyphs live on a 24-unit grid and are shown at 20px in the rail. Host
 * chrome (undo, close, the settings tab rail) is shown at 16px beside them on
 * a registry of its own, drawn on a 16-unit grid, because a 24-grid glyph
 * scaled to 16 loses its detail. Each tier's stroke is set so that it lands
 * on the same line on screen at its display size: 1.6 units at 20px and 1.3
 * units at 16px are both about 1.3px, so a lock under the tools reads as part
 * of the same set, only smaller.
 *
 * Through 2.6.2 both tiers drew a 2-unit stroke at their grid size (24px and
 * 16px), which put every edge on a pixel boundary. Crisp, but a line half
 * again as wide on tool glyphs a fifth larger is nearly twice the ink, and a
 * rail of them read as heavy beside the chart it frames: on screen, weight is
 * noticed long before edge sharpness.
 * Earlier still the chrome stroke was 1.5 at 16px, the lightest of the three,
 * and the tool rail beside it the heaviest; one line across both is the rule
 * that survived every revision.
 *
 * # The grid
 *
 * Every glyph is authored to the same constraints, and `tests/draw-icons.test.ts`
 * enforces all of them mechanically, because a set of this size cannot be kept
 * consistent by review:
 *
 *  - **One viewBox per tier.** 24 by 24 for tools, 16 by 16 for chrome, so a
 *    host sets the size once per surface.
 *  - **A margin all round.** Live area 2 to 22 on the tool grid, 2 to 14 on the
 *    chrome grid, so the ink stops short of the box. Without it, glyphs that
 *    happen to reach the edge look larger than their neighbours and the rail
 *    reads as ragged.
 *  - **Integer coordinates.** Parallel strokes keep an even gap and a family
 *    of glyphs shares its anchor points, so siblings line up in a list.
 *  - **One stroke weight.** Different weights across identically sized boxes
 *    is the single most visible tell of a set assembled rather than drawn.
 *  - **The whole glyph in its path.** The marks that tell siblings apart (a
 *    segment ends in two dots, a ray starts at one, a path ends in a head)
 *    are small closed shapes drawn in the path itself, so a host that renders
 *    the path data and nothing else still gets every one of them. An accent
 *    registry repeats those marks for a fill on top: a dot then paints solid
 *    rather than as a ring, which adds weight, never identity.
 *
 * # Rendering
 *
 * Tool glyphs are drawn for 20px and chrome glyphs for 16px, which is what
 * `iconSvg` and `chromeIconSvg` default to. A host that shows a glyph larger
 * scales the line with it; one that wants the same line at another size sets
 * the stroke to keep it near 1.3px.
 */

/** The viewBox every glyph is authored in. */
export const ICON_VIEWBOX = '0 0 24 24';

/**
 * The CSS pixel size a tool glyph is drawn for: the rail, a flyout row and
 * `iconSvg` by default.
 */
export const ICON_SIZE = 20;

/**
 * Stroke width in viewBox units: about 1.3px at `ICON_SIZE`. Paths carry no
 * presentation attributes, so a host that wants another weight overrides this
 * once rather than editing glyphs.
 */
export const ICON_STROKE = 1.6;

/**
 * The attribute bag a tier hands its host. Structural, so the markup builders
 * in `icon-svg.ts` take either tier's bag through one signature.
 */
export interface IconAttrs {
  readonly viewBox: string;
  readonly fill: 'none';
  readonly stroke: 'currentColor';
  readonly strokeWidth: number;
  readonly strokeLinecap: 'round';
  readonly strokeLinejoin: 'round';
}

/** Attributes a host should apply to the `<svg>`, so every set matches. */
export const ICON_ATTRS = {
  viewBox: ICON_VIEWBOX,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: ICON_STROKE,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const satisfies IconAttrs;

/**
 * A round mark of radius `r` centred on a grid point: two half-turn arcs, so
 * the path closes where it starts. Stroked with the glyph's line, radius 1
 * paints a near-solid dot over twice the line across, which is what makes it
 * read as an anchor; radius 2 is a ring the accent fills.
 */
function dot(x: number, y: number, r = 1): string {
  return `M${x - r} ${y}a${r} ${r} 0 0 0 ${2 * r} 0a${r} ${r} 0 0 0 ${-2 * r} 0z`;
}

/**
 * A circle that stays open: the same two half turns as `dot`, at a radius the
 * line cannot fill. Named apart because a ring is part of a drawing (a level,
 * a wave) and never a mark an accent paints solid.
 */
const ring = (x: number, y: number, r: number): string => dot(x, y, r);

/**
 * A harmonic pattern through X, A, B, C and D, given as heights on five
 * evenly spaced columns, then the bases XB and BD of the two triangles its
 * tool fills. Price runs up the grid, so a smaller number is a higher price.
 */
function harmonic(x: number, a: number, b: number, c: number, d: number): string {
  return `M2 ${x} 7 ${a} 12 ${b} 17 ${c} 22 ${d}M2 ${x} 12 ${b} 22 ${d}`;
}

/*
 * The closed marks of the tool glyphs, written once: each is drawn in its
 * glyph's path and repeated in `DRAWING_TOOL_ACCENTS` for the fill.
 */
const MAGNET_CAPS = 'M5 3h2v3H5zM17 3h2v3h-2z';
const SEGMENT_ENDS = dot(6, 18) + dot(18, 6);
const RAY_ORIGIN = dot(4, 18);
const EXTENDED_DOTS = dot(8, 16) + dot(16, 8);
const ARROW_HEAD = 'M20 4l-2 8-6-6z';
const HRAY_ORIGIN = dot(10, 12);
const CROSS_CENTRE = dot(12, 12);
const PATH_HEAD = 'M20 8l-6 2 4 4z';
const POLYLINE_VERTICES = dot(4, 19, 2) + dot(9, 7, 2) + dot(14, 16, 2);
const LONG_DIRECTION = 'M10 11l3-4 3 4z';
const SHORT_DIRECTION = 'M10 13l3 4 3-4z';
const FORK_PIVOT = dot(12, 21);
const SCHIFF_PIVOT = dot(19, 14);
const MODIFIED_PIVOT = dot(19, 20);
const INSIDE_PIVOT = dot(12, 20);
/** A pitchfork's head: two outer tines and the crossbar between them. */
const FORK_HEAD = 'M5 2v8h14V2';

/**
 * Path data by tool id, plus a few keys a host toolbar needs that are not
 * themselves tools (`cursor`, the group headers).
 *
 * Values are the `d` attribute of one `<path>`. Multiple subpaths are joined
 * into the same string rather than split across elements, so a host renders one
 * node per glyph, and that node is the whole glyph: its dots and heads are in
 * the string as outlines. `DRAWING_TOOL_ACCENTS` repeats those marks for a
 * host that also wants them filled.
 */
export const DRAWING_TOOL_ICONS: Readonly<Record<string, string>> = {
  // ── chrome ──────────────────────────────────────────────────────────────
  // A pointer, not a cross: the button puts the chart back in its plain mode,
  // and a cross beside the cross-line tool and a plus read as the same button.
  cursor: 'M6 3v15l4-4h7zM11 15l3 6',
  magnet: 'M6 7v5a6 6 0 0 0 12 0V7' + MAGNET_CAPS,

  // ── lines ───────────────────────────────────────────────────────────────
  // Told apart by their ends, which is what differs between the tools: two
  // anchor dots, one origin dot and an open end, dots inside a line that runs
  // to both edges, and a head. The ray also leaves at a shallower angle: on
  // the segment's diagonal, its open end ran through the segment's second
  // dot and the two overlapped by 87 percent at 24px. A line that extends
  // runs to the edge of the live area; one that stops ends on its dot.
  'trend-line': 'M6 18 18 6' + SEGMENT_ENDS,
  ray: 'M4 18 22 6' + RAY_ORIGIN,
  'extended-line': 'M2 22 22 2' + EXTENDED_DOTS,
  arrow: 'M4 20 15 9' + ARROW_HEAD,
  'horizontal-line': 'M2 12h20',
  // The ray leaves from its anchor two fifths of the way in and runs to the
  // far edge. Trimmed from the same line with its dot held only in the accent,
  // it was the horizontal line at 86 percent overlap for a host drawing the
  // path; from a third of the way in, at the finer line of 2.6.3, 71 percent.
  'horizontal-ray': 'M10 12h12' + HRAY_ORIGIN,
  'vertical-line': 'M12 2v20',
  'cross-line': 'M2 12h20M12 2v20' + CROSS_CENTRE,
  'trend-angle': 'M4 20 18 8M4 20h12M8 20a8 8 0 0 0 2-5',
  'info-line': 'M6 18 18 6M3 3h8v5H3z' + SEGMENT_ENDS,
  // A path points somewhere and a polyline only joins its vertices, which is
  // the difference between the tools: a head on one, vertex rings on the other.
  path: 'M3 20 7 7l5 9 5-5' + PATH_HEAD,
  polyline: 'M4 19 9 7l5 9 6-11' + POLYLINE_VERTICES,

  // ── channels ────────────────────────────────────────────────────────────
  'parallel-channel': 'M2 16 14 4M8 22 20 10',
  'disjoint-channel': 'M2 16 14 6M8 22 22 14',
  'flat-bottom': 'M2 14 14 4M2 20h20',
  'fib-channel': 'M2 14 14 4M4 18 16 8M6 22 18 12',
  'regression-trend': 'M2 18 20 6M4 20 22 8M2 14 20 2',

  'flat-top-bottom': 'M3 6h18M3 20 21 12M3 6v14',
  'regression-channel': 'M3 18 19 6M5 21 21 9M3 12 17 2M10 16h4',

  // ── pitchforks ──────────────────────────────────────────────────────────
  // One trident, upright so it reads as one, and a pivot dot. The four tools
  // differ only in where the median starts, so that is what the glyphs show,
  // each as its tool constructs it, turned so the tines point up: time runs
  // up the glyph and price across it. The standard median starts at the
  // pivot. The Schiff median starts at the pivot's time and halfway to the
  // second anchor's price, so the handle stops short and turns square to
  // the pivot. The modified one also moves halfway in time, to the middle of
  // the swing from the pivot to the second anchor, and draws that swing. The
  // inside median starts on the crossbar itself; the swing from the pivot to
  // both crossbar ends stands for the lines that tool draws below it. Drawn
  // diagonally through 2.5.8, the four crossed their tines through the
  // handle and read as an X.
  pitchfork: FORK_HEAD + 'M12 2v19' + FORK_PIVOT,
  'schiff-pitchfork': FORK_HEAD + 'M12 2v12h7' + SCHIFF_PIVOT,
  'modified-schiff-pitchfork': FORK_HEAD + 'M12 2v13M5 10l14 10' + MODIFIED_PIVOT,
  'inside-pitchfork': FORK_HEAD + 'M12 2v8M5 10l7 10 7-10' + INSIDE_PIVOT,

  'fib-extension-two-point': 'M3 4h18M3 10h18M3 16h18M3 21h18M6 4v12',
  // The tool marks the box its anchors span by the two far edges alone and
  // fans out to both from the first anchor: the diagonal, and the half level
  // on each edge. With the near axes it was the speed fan again with one
  // more ray; with the whole box it was the Gann box and Gann square beside
  // it in the same flyout, at 0.68 and 0.71 overlap.
  'fib-speed-resistance-fan': 'M3 3h18v18M3 21 21 3M21 12 3 21 12 3',
  'icon-stamp': 'M12 3l3 6 6 3-6 3-3 6-3-6-6-3 6-3z',
  // ── shapes ──────────────────────────────────────────────────────────────
  rectangle: 'M3 5h18v14H3z',
  'rotated-rectangle': 'M2 14 10 4l12 6-8 10z',
  ellipse: 'M12 5c5 0 9 3 9 7s-4 7-9 7-9-3-9-7 4-7 9-7z',
  circle: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',
  triangle: 'M12 4 21 20H3z',
  arc: 'M3 19a12 12 0 0 1 18 0',
  curve: 'M3 18c4-12 14-12 18 0',
  'double-curve': 'M3 18c3-9 7-9 9 0 2 9 6 9 9 0',
  brush: 'M3 19c4 0 4-8 8-8s4 8 9 4',
  highlighter: 'M4 16 14 6l4 4-10 10H4z',

  // ── fibonacci and gann ──────────────────────────────────────────────────
  'fib-retracement': 'M3 4h18M3 9h18M3 14h18M3 19h18',
  'fib-extension': 'M3 5h18M3 12h18M3 19h18M8 5v14',
  'fib-fan': 'M3 20 21 4M3 20 21 10M3 20 21 16M3 20h18',
  'fib-time-zone': 'M4 3v18M8 3v18M14 3v18M22 3v18',
  // The tool rings one centre at each level.
  'fib-circles': ring(12, 12, 3) + ring(12, 12, 6) + ring(12, 12, 9),
  // Quarter turns of radius 2, 3, 5, 8 and 13, each leaving where the last
  // ended and heading the same way: the golden spiral the tool draws, in
  // whole units. The last, radius 13, turns 67 degrees rather than 90 and
  // ends on a 5, 12, 13 triangle, which keeps it on the grid and inside the
  // box. The arcs it replaced did not meet, and the last one, too short a
  // chord for its radius, bulged out past the edge as a tail.
  'fib-spiral': 'M8 10A2 2 0 0 0 10 8 3 3 0 0 0 7 5 5 5 0 0 0 2 10 8 8 0 0 0 10 18 13 13 0 0 0 22 10',
  // A sector: the two radii and its levels between them. A 3, 4, 5 edge
  // puts every level on whole units.
  'fib-wedge': 'M20 18H5l9-12M10 18A5 5 0 0 0 8 14M15 18A10 10 0 0 0 11 10M20 18A15 15 0 0 0 14 6',
  'fib-speed-fan': 'M3 20V4M3 20h18M3 20 21 4M3 20 13 4',
  'gann-fan': 'M3 20 21 2M3 20 21 9M3 20 21 15M3 20h18',
  'gann-box': 'M3 3h18v18H3zM3 3l18 18M3 21 21 3',
  'trend-fib-time': 'M3 20 8 8 12 15M12 3v18M16 3v18M22 3v18',
  // Half circles about the trend's first anchor, turned to face along it,
  // with the trend through their crowns. Each arc's radius is written short
  // of its chord on purpose: SVG scales such a radius up to half the chord,
  // which makes the arc an exact half turn on a diagonal whose true radius
  // is not a whole number.
  'fib-speed-resistance-arcs': 'M10 14 22 2M2 6a8 8 0 0 1 16 16M6 10a4 4 0 0 1 8 8',
  'gann-square': 'M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18M3 21 21 3',
  // The tool's own figure: a square as tall as the unit arcs, which stand on
  // its bottom corners, arcs a third as high on the same base, and the wall
  // at half. The half rings under a pole it replaced read as an umbrella.
  'dedekind-tessellation': 'M3 3h18v18H3zM3 3A18 18 0 0 1 21 21M21 3A18 18 0 0 0 3 21'
    + 'M3 21a6 6 0 0 1 12 0M9 21a6 6 0 0 1 12 0M12 3 12 21',
  sonic: 'M3 12a9 9 0 0 1 18 0M6 12a6 6 0 0 1 12 0M9 12a3 3 0 0 1 6 0M3 12h18',
  // Waves inside the Mach cone, each on its axis and tangent to both sides,
  // as the tool draws them. The two tools differ only in their levels, and
  // so do the glyphs: equal steps for the one, radii 2, 3 and 5 for the
  // golden one. The smallest golden wave sits a third of a unit inside the
  // cone: exactly tangent, it would be centred where the next wave's line
  // passes, and that line would fill it solid. The half rings across the
  // cone they replaced matched nothing either tool draws.
  supersonic: 'M22 3 2 12l20 9' + ring(7, 12, 2) + ring(12, 12, 4),
  'golden-sonic': 'M3 12a9 9 0 0 1 18 0M7 12a5 5 0 0 1 10 0M10 12a2 2 0 0 1 4 0M3 16h18M12 16v5',
  'golden-supersonic': 'M22 5 2 12l20 7' + ring(7, 12, 2) + ring(11, 12, 3) + ring(17, 12, 5),

  // ── patterns ────────────────────────────────────────────────────────────
  'xabcd-pattern': 'M3 19 7 4 12 16 16 8 21 20M3 19 12 16 21 20M7 4 16 8',
  'abcd-pattern': 'M3 18 9 4 15 15 21 3M3 18 15 15M9 4 21 3',
  'elliott-impulse': 'M2 21 6 12 9 17 13 5 17 11 22 2',
  'elliott-correction': 'M3 4 9 18 15 8 21 21M3 4h4M17 21h4',
  'head-shoulders': 'M2 20 5 10 8 17 12 3 16 17 19 10 22 20M3 17h18',
  // The six harmonics are one zigzag and differ only in where B and D fall
  // against XA, so each is drawn to its own ratios, and its tool accepts it
  // as a valid instance of itself and of no other harmonic. Gartley: B at
  // 0.61 of XA, D at 0.78. Bat: a shallow B at 0.44, a deep D at 0.89.
  // Butterfly: D beyond X, at 1.38. Crab: D far beyond X, at 1.58, after a
  // leg 3.4 times BC. Shark: C above A, D back at X. Cypher: C above A, D at
  // 0.79 of XC. Drawn by eye, as before, five of the six failed their own
  // tool's check.
  gartley: harmonic(21, 3, 14, 7, 17),
  bat: harmonic(21, 3, 11, 5, 19),
  butterfly: harmonic(16, 3, 13, 6, 21),
  crab: harmonic(14, 2, 9, 4, 21),
  shark: harmonic(22, 5, 13, 2, 22),
  cypher: harmonic(21, 7, 14, 2, 17),

  // ── measure and range ───────────────────────────────────────────────────
  measure: 'M4 16h16M4 12v8M20 12v8M8 4h8M12 4v6',
  'anchored-vwap': 'M4 4v16M4 15 8 12 12 14 16 8 20 6M2 4h4',
  'fixed-range-volume-profile': 'M4 3v18M4 5h8v3H4M4 10h16v3H4M4 15h12v3H4',
  'price-range': 'M12 4v16M7 9l5-5 5 5M7 15l5 5 5-5',
  'date-range': 'M4 12h16M9 7l-5 5 5 5M15 7l5 5-5 5',
  'date-price-range': 'M5 6h14v12H5zM5 12h14M12 6v12',

  // ── cycles ──────────────────────────────────────────────────────────────
  'cyclic-lines': 'M4 4v16M10 4v16M16 4v16M22 4v16',
  'time-cycles': 'M4 12a4 4 0 0 1 8 0 4 4 0 0 0 8 0M4 4v16',
  'sine-line': 'M2 12c3-9 6-9 9 0 3 9 6 9 9 0',

  // ── positions and forecast ──────────────────────────────────────────────
  // A position is one frame split at the entry into its two zones, the
  // target the taller, with a tick out to the left at the entry price and
  // the direction solid in the target. A short is the long turned over.
  // They were one picture in 2.5.5, and the box over a thin stop bar that
  // replaced it read as an eject key or a laptop. The risk-reward pair
  // measures instead: from one entry line, the reward as a tall span with a
  // cap, the risk as a short one the other way, flipped for the short.
  'long-position': 'M2 14h4M6 3h15v17H6zM6 14h15' + LONG_DIRECTION,
  'short-position': 'M2 10h4M6 4h15v17H6zM6 10h15' + SHORT_DIRECTION,
  forecast: 'M3 18 9 10l4 4 8-10M13 4h8v8',
  'risk-reward-long': 'M2 14h20M8 14V3M5 3h6M17 14v6M14 20h6',
  'risk-reward-short': 'M2 10h20M8 10v11M5 21h6M17 10V4M14 4h6',

  // ── annotations ─────────────────────────────────────────────────────────
  text: 'M4 5h16M12 5v14M8 19h8',
  note: 'M4 20 9 15M9 5h13v10H9zM4 20v-4',
  // A callout's tail runs back to a point it annotates, well clear of the
  // box; a balloon's is a stub under its own anchor, and a comment's smaller.
  callout: 'M3 3h18v9H11l-6 8 1-8H3z',
  balloon: 'M3 4h18v12H9l-4 4v-4H3z',
  comment: 'M3 5h18v10H3zM6 15v4l4-4',
  signpost: 'M12 21V9M5 3h14v6H5z',
  'price-label': 'M3 12 8 7h13v10H8z',
  'price-note': 'M2 12h5M7 6h15v12H7zM10 12h9',
  table: 'M3 5h18v14H3zM3 10h18M9 10v9M15 10v9',
  'flag-mark': 'M6 21V3M6 3h12l-3 4 3 4H6',
  'arrow-up': 'M12 3v18M6 9l6-6 6 6',
  'arrow-down': 'M12 3v18M6 15l6 6 6-6',
  'arrow-left': 'M3 12h18M9 6l-6 6 6 6',
  'arrow-right': 'M3 12h18M15 6l6 6-6 6',
};

/**
 * The fills of the tool glyphs' marks, by tool id: anchor dots, pole caps and
 * arrowheads. Optional: most glyphs have none.
 *
 * Every mark here is also drawn, as an outline, in the glyph's own path, so a
 * host that renders only `DRAWING_TOOL_ICONS` still shows each one. This adds
 * the fill: a second `<path>` painted in `currentColor` with no stroke of its
 * own, after the glyph's path. The markup builders in `icon-svg.ts` add it; a
 * host wrapping the path data itself adds
 * `<path d="..." fill="currentColor" stroke="none"/>` for the same result.
 */
export const DRAWING_TOOL_ACCENTS: Readonly<Record<string, string>> = {
  magnet: MAGNET_CAPS,
  'trend-line': SEGMENT_ENDS,
  ray: RAY_ORIGIN,
  'extended-line': EXTENDED_DOTS,
  arrow: ARROW_HEAD,
  'horizontal-ray': HRAY_ORIGIN,
  'cross-line': CROSS_CENTRE,
  'info-line': SEGMENT_ENDS,
  path: PATH_HEAD,
  polyline: POLYLINE_VERTICES,
  'long-position': LONG_DIRECTION,
  'short-position': SHORT_DIRECTION,
  pitchfork: FORK_PIVOT,
  'schiff-pitchfork': SCHIFF_PIVOT,
  'modified-schiff-pitchfork': MODIFIED_PIVOT,
  'inside-pitchfork': INSIDE_PIVOT,
};

/**
 * A registry's own entry. The registries are plain objects, so `toString` or
 * `constructor` would otherwise come back as an inherited function: drawn as
 * path data where an unknown id must give `undefined`.
 */
const own = (registry: Readonly<Record<string, string>>, id: string): string | undefined =>
  Object.prototype.hasOwnProperty.call(registry, id) ? registry[id] : undefined;

/**
 * The glyph for a tool, or `undefined` when it has none.
 *
 * Undefined rather than a placeholder: a host that renders an empty box has a
 * visible gap to fix, while one handed a question mark ships it.
 */
export function drawingToolIcon(toolId: string): string | undefined {
  return own(DRAWING_TOOL_ICONS, toolId);
}

/** The filled accent for a tool glyph, or `undefined` when it has none. */
export function drawingToolAccent(toolId: string): string | undefined {
  return own(DRAWING_TOOL_ACCENTS, toolId);
}

/** Every id this set covers, for a host building a palette from it. */
export function drawingToolIconIds(): string[] {
  return Object.keys(DRAWING_TOOL_ICONS);
}

// ── the chrome tier ─────────────────────────────────────────────────────────

/** The viewBox every chrome glyph is authored in. */
export const CHROME_ICON_VIEWBOX = '0 0 16 16';

/** The CSS pixel size a chrome glyph is drawn for, and `chromeIconSvg`'s default. */
export const CHROME_ICON_SIZE = 16;

/**
 * Chrome stroke width in viewBox units: about 1.3px at `CHROME_ICON_SIZE`, the
 * line the tool tier draws at its own size, so the two rails read as one set.
 */
export const CHROME_ICON_STROKE = 1.3;

/** Attributes a host should apply to the `<svg>` around a chrome glyph. */
export const CHROME_ICON_ATTRS = {
  viewBox: CHROME_ICON_VIEWBOX,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: CHROME_ICON_STROKE,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const satisfies IconAttrs;

/* The closed marks of the chrome glyphs, as above for the tools. */
const CHROME_MAGNET_CAPS = 'M3 2h2v2H3zM11 2h2v2h-2z';
const CHROME_PUPIL = dot(8, 8);
const CHROME_KNOBS = dot(5, 5, 2) + dot(11, 11, 2);
const CHROME_LENS = dot(8, 9);
const CHROME_ENDS = dot(4, 12) + dot(12, 4);
const CHROME_MARKERS = dot(5, 5, 2) + dot(10, 11, 2);
const CHROME_HEAD = dot(8, 5, 2);
/** The clipboard's clip: the board's top edge runs through it, so it is filled. */
const CHROME_CLIP = 'M6 2h4v2H6z';

/**
 * A pip: a stroke of no length, which the round cap paints as a disc one
 * line wide. The small marks of the chrome tier (an i's dot, a row of keys,
 * a grip) are pips rather than `dot`s, whose ring is a disc over twice the
 * line across and crowds a 16px box.
 */
const pip = (x: number, y: number): string => `M${x} ${y}h0`;

/**
 * Path data for host chrome: the buttons around the chart rather than the
 * tools in it. Same rules as the tool tier (the whole glyph in one path, its
 * marks included; no presentation attributes; integer coordinates) on the 16
 * grid with a 2..14 live area.
 *
 * The set was drawn for a 2px line, where a 16px glyph has room for about four
 * parallel strokes with a pixel between them, and keeps that air at the finer
 * line it is shown with now: two
 * sliders rather than three, a lens and a pupil as small solid dots rather
 * than rings, and no plus squeezed inside a square.
 *
 * The pair `cursor` / `magnet` / `text` also exist in the tool registry, at 24.
 * They are drawn twice on purpose: a rail button and a toolbar button are
 * different sizes, and the whole point of a second grid is not scaling one
 * drawing to both.
 *
 * The tier also carries a glyph for each chart type and transform, under
 * `chart-<id>` (see `chartTypeIcon`), so a chart-type menu reads from the
 * same set as the buttons around it. A layout picker's tiles are derived
 * rather than listed (`layoutIconPath`).
 */
export const CHROME_ICONS: Readonly<Record<string, string>> = {
  // ── pointer and snapping ────────────────────────────────────────────────
  // A pointer, not the cross it was: that cross overlapped `plus` by 92
  // percent at 16px.
  cursor: 'M4 2v10l3-3h5zM8 10l2 4',
  magnet: 'M4 5v3a4 4 0 0 0 8 0V5' + CHROME_MAGNET_CAPS,

  // ── state ───────────────────────────────────────────────────────────────
  // Unlocked swings the shackle off to the side. Leaving it in place with
  // one leg shortened, as before, let the round cap close the gap: the two
  // overlapped by more than 99 percent at 16px.
  lock: 'M3 8h10v6H3zM5 8V6a3 3 0 0 1 6 0v2',
  unlock: 'M3 8h10v6H3zM8 8V5a3 3 0 0 0-6 0',
  eye: 'M2 8c2-3 4-5 6-5s4 2 6 5c-2 3-4 5-6 5s-4-2-6-5z' + CHROME_PUPIL,
  'eye-off': 'M2 8c2-3 4-5 6-5s4 2 6 5c-2 3-4 5-6 5s-4-2-6-5zM3 3l10 10',
  star: 'M8 2l2 4h4l-3 3 1 5-4-3-4 3 1-5-3-3h4z',
  // A pentagram rather than the outline: filled with the default nonzero rule
  // its centre has a winding of two and fills solid, so one path is both a
  // star and its filled state. See CHROME_ICON_FILLED.
  'star-filled': 'M8 2l4 12-10-8h12L4 14z',

  // ── editing ─────────────────────────────────────────────────────────────
  trash: 'M2 4h12M6 4V2h4v2M3 4l1 10h8l1-10',
  settings: 'M2 5h12M2 11h12' + CHROME_KNOBS,
  undo: 'M3 6h7a4 4 0 0 1 0 8H6M6 3 3 6l3 3',
  redo: 'M13 6H6a4 4 0 0 0 0 8h4M10 3l3 3-3 3',
  copy: 'M6 6h8v8H6zM10 6V2H2v8h4',
  // A board with its clip and two lines of content: the empty board beside
  // the trash can's lid and handle overlapped it by 72 percent at 16px.
  paste: 'M3 3h10v11H3z' + CHROME_CLIP + 'M6 8h4M6 11h4',
  // The copy of a square, as a square and a plus: a plus inside the front
  // square of `copy` leaves no pixel between the two at this weight.
  duplicate: 'M8 8h6v6H8zM5 2v6M2 5h6',
  front: 'M2 9h6v5H2zM11 14V2M8 5l3-3 3 3',
  back: 'M2 2h6v5H2zM11 2v12M8 11l3 3 3-3',
  text: 'M3 3h10M8 3v10M6 13h4',

  // ── navigation ──────────────────────────────────────────────────────────
  'chevron-down': 'M3 6l5 5 5-5',
  'chevron-right': 'M6 3l5 5-5 5',
  close: 'M3 3l10 10M13 3 3 13',
  plus: 'M8 2v12M2 8h12',
  minus: 'M2 8h12',
  search: 'M7 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM11 11l3 3',
  grid: 'M2 2h12v12H2zM2 8h12M8 2v12',
  // Two half links and the bar between them; unlinked drops the bar and
  // marks the break.
  link: 'M6 5H5a3 3 0 0 0 0 6h1M10 5h1a3 3 0 0 1 0 6h-1M6 8h4',
  unlink: 'M6 5H5a3 3 0 0 0 0 6h1M10 5h1a3 3 0 0 1 0 6h-1M8 2v1M8 13v1',

  // ── capture ─────────────────────────────────────────────────────────────
  camera: 'M2 5h3l1-2h4l1 2h3v8H2z' + CHROME_LENS,
  download: 'M8 2v9M4 7l4 4 4-4M2 14h12',
  // Viewfinder corners round four panes. A camera with a grid in its body
  // overlapped `camera`, which sits beside it in one menu, by 81 percent.
  'capture-grid': 'M2 5 2 2 5 2M11 2 14 2 14 5M14 11 14 14 11 14M5 14 2 14 2 11'
    + pip(6, 6) + pip(10, 6) + pip(6, 10) + pip(10, 10),

  // ── navigation, continued ───────────────────────────────────────────────
  'chevron-up': 'M3 10l5-5 5 5',
  'chevron-left': 'M10 3 5 8l5 5',
  // A panel folding away and coming back: the rail's collapse and its tab.
  'chevrons-left': 'M8 4 4 8l4 4M12 4 8 8l4 4',
  'chevrons-right': 'M4 4l4 4-4 4M8 4l4 4-4 4',
  // The widget's menu tick moved onto whole units: its short leg ran from
  // 3,8.5 to an elbow at 6.5,12, and on the grid that elbow is 7,12, so a
  // menu that adopts this glyph keeps the tick it already shows.
  check: 'M3 8l4 4 6-8',
  // Stacked, so it is not read as the dotted line style beside it.
  more: pip(8, 3) + pip(8, 8) + pip(8, 13),
  grip: pip(6, 4) + pip(10, 4) + pip(6, 8) + pip(10, 8) + pip(6, 12) + pip(10, 12),
  refresh: 'M10 12A5 5 0 1 1 12 8M10 6l2 2 2-2',
  swap: 'M2 5h11M10 2l3 3-3 3M14 11H3M6 8l-3 3 3 3',

  // ── the grid of charts ──────────────────────────────────────────────────
  // Loose tiles, not a split frame: `grid` is already a split frame, and a
  // layout glyph is the picker for one. The tiles of a particular layout
  // come from `layoutIconPath`, not from this registry.
  layout: 'M2 2 6 2 6 14 2 14zM10 2 14 2 14 6 10 6zM10 10 14 10 14 14 10 14z',
  // A cell grows to fill the grid along its diagonal, and shrinks back to
  // its centre; fullscreen is the whole display, so its marks are the
  // display's corners. The heads are three units, as on the set's other
  // arrows, and the two arrows of each glyph leave the centre clear, which
  // is where maximize and restore differ.
  maximize: 'M10 6 14 2M11 2h3v3M6 10 2 14M2 11v3h3',
  restore: 'M13 3 9 7M12 7H9V4M3 13l4-4M4 9h3v3',
  fullscreen: 'M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4',
  'fullscreen-exit': 'M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4',
  // The channels a group of charts shares: two panes joined, a drawing by its
  // anchors, a reticle, a span of time and a palette. The reticle keeps its
  // centre open: a cross with a gap in the middle was `plus` at 92 percent.
  'link-group': 'M2 3h4v10H2zM10 3h4v10h-4zM6 8h4',
  'drawing-sync': 'M4 12 12 4' + CHROME_ENDS,
  crosshair: ring(8, 8, 4) + 'M8 2 8 4M8 12 8 14M2 8 4 8M12 8 14 8',
  'time-range': 'M3 4v8M13 4v8M3 8h10',
  palette: 'M8 14A6 6 0 1 1 14 8L10 10z' + pip(5, 8) + pip(7, 5) + pip(10, 5),

  // ── time and the market ─────────────────────────────────────────────────
  // A ring with a mark inside is info, clock and globe at once unless the
  // rings differ: at one radius the ring is most of each glyph's ink, and
  // clock and info overlapped by 87 percent. The clock is drawn a size
  // smaller than the other two for that reason.
  // The rings sit a third of the way in, not near the corners, and the
  // holiday below is the same page with the day struck off.
  calendar: 'M2 4h12v10H2zM2 7h12M6 2v3M10 2v3M5 10h2',
  clock: ring(8, 8, 5) + 'M8 6v2h2',
  globe: ring(8, 8, 6) + 'M8 2a3 6 0 0 0 0 12a3 6 0 0 0 0-12M2 8h12',
  // The session as a day on a horizon: the sun up, rising, setting, the moon,
  // and a day struck off the calendar. As rings with a dot or a bar inside,
  // open and closed were the clock at 85 and 89 percent, and each other.
  // The setting sun sits lower than the rising one: with the same sun and
  // only the arrow turned over, the two overlapped by 84 percent. The arrows
  // have shafts, the rising one's head at the top of the box and the setting
  // one's just over its sun: a bare chevron over the small setting sun read
  // as an hourglass at 16px, and one shaft for both was 72 percent alike.
  'market-open': ring(8, 8, 2) + 'M8 2 8 3M2 8 3 8M13 8 14 8M3 3 4 4M13 3 12 4M2 13h12',
  'market-pre': 'M2 13h12M5 13a3 3 0 0 1 6 0M8 7V2M5 5l3-3 3 3',
  'market-post': 'M2 13h12M6 13a2 2 0 0 1 4 0M8 3v5M5 5l3 3 3-3',
  'market-closed': 'M8 2A4 4 0 1 0 12 6 4 4 0 0 1 8 2zM2 13h12',
  'market-holiday': 'M2 4h12v10H2zM6 2v3M10 2v3M6 8l4 4M10 8l-4 4',

  // ── replay ──────────────────────────────────────────────────────────────
  // The solid media set, filled through CHROME_ICON_FILLED. The pause bars
  // are three pixels wide rather than four so the stop square beside them
  // is not the same block of ink (69 percent at four).
  replay: 'M8 3v10L2 8zM14 3v10L8 8z',
  play: 'M5 3v10l8-5z',
  pause: 'M4 3h1v10H4zM11 3h1v10h-1z',
  stop: 'M4 4h8v8H4z',
  'step-forward': 'M3 3v10l6-5zM12 3v10',
  'step-back': 'M13 3v10L7 8zM4 3v10',
  record: dot(8, 8, 4),

  // ── the price scale ─────────────────────────────────────────────────────
  'scale-auto': 'M8 2v12M5 5l3-3 3 3M5 11l3 3 3-3',
  'scale-log': 'M2 2v12h12M4 12C8 11 11 8 13 3',
  'scale-percent': 'M13 3 3 13' + ring(4, 4, 2) + ring(12, 12, 2),

  // ── layouts and files ───────────────────────────────────────────────────
  // One menu, so drawn apart: save-as leaves out the disk's shutter for its
  // plus (with it the two were 78 percent alike), and autosave is two arrows
  // round rather than a third disk. Recent is the one arrow turned back, with
  // hands; refresh is the one arrow forward.
  folder: 'M2 3h4l2 2h6v8H2z',
  save: 'M2 2h9l3 3v9H2zM5 2v4h5V2M5 14v-4h6v4',
  'save-as': 'M9 14H2V2h9l3 3v4M12 10v4M10 12h4',
  autosave: 'M3 8A5 5 0 0 1 12 5M12 2v3H9M13 8A5 5 0 0 1 4 11M4 14v-3h3',
  rename: 'M9 5H2v6h7M12 3v10M10 3h4M10 13h4',
  recent: 'M6 12A5 5 0 1 0 4 8M6 6 4 8 2 6M9 6v2h2',
  template: 'M2 2h12v4H2zM2 9h5v5H2zM10 9h4M10 12h4',
  keyboard: 'M2 3h12v10H2z' + pip(5, 6) + pip(8, 6) + pip(11, 6) + 'M5 10h6',

  // ── status ──────────────────────────────────────────────────────────────
  bell: 'M4 11V7a4 4 0 0 1 8 0v4M2 11h12M7 14h2',
  'bell-off': 'M4 11V7a4 4 0 0 1 8 0v4M2 11h12M7 14h2M2 2l12 12',
  pin: 'M5 2h6M6 2v5l-2 3h8l-2-3V2M8 10v4',
  'pin-filled': 'M5 2h6M6 2h4v5l2 3H4l2-3zM8 10v4',
  // Three outlines, so the level reads before the mark inside does. An
  // octagon for the error rasterised as a circle at 16px, 93 percent info.
  info: ring(8, 8, 6) + pip(8, 5) + 'M8 8v3',
  warning: 'M8 2l6 12H2zM8 7v1' + pip(8, 11),
  error: 'M8 2l6 6-6 6-6-6zM8 5v2' + pip(8, 10),
  sun: ring(8, 8, 2) + 'M8 2 8 3M8 13 8 14M2 8 3 8M13 8 14 8M3 3 4 4M12 12 13 13M13 3 12 4M3 13 4 12',
  moon: 'M12 11A5 5 0 1 1 5 4a7 7 0 0 0 7 7z',

  // ── drawing and text ────────────────────────────────────────────────────
  eraser: 'M2 10 8 4l6 6-4 4H6zM5 7l6 6',
  measure: 'M2 5h12v6H2zM5 5v3M8 5v2M11 5v3',
  fill: 'M8 2l4 6a4 4 0 1 1-8 0z',
  bold: 'M4 2h5a3 3 0 0 1 0 6H4zM4 8h6a3 3 0 0 1 0 6H4z',
  italic: 'M7 2h6M3 14h6M10 2 6 14',

  // ── panels ──────────────────────────────────────────────────────────────
  watchlist: pip(3, 4) + pip(3, 8) + pip(3, 12) + 'M6 4h8M6 8h8M6 12h8',
  news: 'M4 12V3h10v10H3a1 1 0 0 1-1-1V6h2M7 6h4M7 9h4',
  account: CHROME_HEAD + 'M3 14a5 4 0 0 1 10 0',
  compare: 'M2 7 6 3 10 6 14 2M2 14 6 10 10 12 14 8',
  indicators: 'M4 14V5a2 2 0 0 1 2-2h1M2 7h4M9 8l5 6M14 8l-5 6',

  // ── trading ─────────────────────────────────────────────────────────────
  // Buy and sell are one solid triangle turned over, since the direction is
  // the difference. Closing a position is leaving it: a box with a cross in
  // it was the square frame of save and grid again. A bracket is the entry
  // with its target above and its stop below, the three levels on one stem,
  // and the depth of market is the ladder traders call it. Each was drawn
  // before as short bars off a stem, and each read as a letter at 16px.
  buy: 'M8 3l6 9H2z',
  sell: 'M8 13 2 4h12z',
  'close-position': 'M9 2H2v12h7M6 8h8M11 5l3 3-3 3',
  reverse: 'M5 13V3M2 6l3-3 3 3M11 3v10M8 10l3 3 3-3',
  bracket: 'M2 8h12M4 3h8M4 13h8M8 3v10',
  'dom-ladder': 'M4 2v12M12 2v12M4 5h8M4 8h8M4 11h8',

  // ── settings tabs and menu marks ────────────────────────────────────────
  // The pictures the widget drew for itself outside the registry, so its
  // settings tabs, stacking order and line style control can read from here
  // and be held to the same checks. The solid line style is `minus`, which
  // is the same drawing. Dashes are two, four pixels apart and set in from
  // the ends: with one pixel between them the round caps closed the gaps (the
  // dashed line was `minus` at 86 percent), and three short dashes with two
  // between them were the dotted line's dots, a little longer.
  legend: 'M2 4h8M2 8h12M2 12h9',
  axes: 'M3 2v11h11M3 6h2M3 10h2M7 13v-2M11 13v-2',
  panels: 'M2 3h12v10H2zM2 8h12M7 3v10',
  trading: 'M2 11l4-4 3 2 5-5M11 4h3v3M2 14h12',
  brush: 'M14 2 9 7M9 7 7 5M9 7l-2 4-4 2 2-4z',
  'above-series': 'M3 3h10M8 14V7M5 10l3-3 3 3',
  'behind-series': 'M3 13h10M8 2v7M5 6l3 3 3-3',
  fit: 'M2 8h12M5 5 2 8l3 3M11 5l3 3-3 3',
  coordinates: 'M3 2v11h11' + pip(10, 6) + 'M3 6h4M10 13v-4',
  'line-dashed': 'M3 8h2M11 8h2',
  'line-dotted': pip(2, 8) + pip(6, 8) + pip(10, 8) + pip(14, 8),
  'line-mixed': 'M2 5h12M3 11h2M11 11h2',

  // ── chart types and transforms ──────────────────────────────────────────
  // One per registered chart type and per transform, read through
  // `chartTypeIcon`. A chart-type menu lists them together, so each family
  // is told apart by what its renderer does differently. Candles: a hollow
  // and a solid body; two hollow; widths that vary; bodies that open halfway
  // up the one before, with no lower wick. Bars: ticks for open and close,
  // or a bare range. Lines: plain, with markers, stepped, and the long
  // verticals and short shoulders of a kagi line. Blocks: bricks corner to
  // corner, bars of one height stepping, boxes of any height, columns on a
  // base, a histogram about zero. A solid body is two units wide and drawn as
  // three strokes side by side, solid at any line; a hollow one is four, with
  // its wicks stopping at it.
  'chart-candlestick': 'M5 2 5 5M3 5h4v6H3zM5 11 5 14M12 3 12 13M11 5 11 11M13 5 13 11',
  'chart-hollow-candle': 'M5 2 5 4M3 4h4v5H3zM5 9 5 12M11 4 11 7M9 7h4v5H9zM11 12 11 14',
  'chart-volume-candle': 'M4 3 4 13M3 5 3 10M5 5 5 10M8 4h6v7H8zM11 2 11 4M11 11 11 14',
  'chart-heikin-ashi': 'M3 8h4v6H3zM5 6 5 8M9 4h4v7H9zM11 2 11 4',
  'chart-bar': 'M5 2 5 14M2 5 5 5M5 11 8 11M11 3 11 12M8 9 11 9M11 5 14 5',
  'chart-high-low': 'M4 3 4 11M8 5 8 14M12 2 12 9',
  'chart-line': 'M2 12 6 6 9 10 14 3',
  'chart-line-markers': 'M2 10 5 5 10 11 14 4' + CHROME_MARKERS,
  'chart-step': 'M2 12h3V8h4v3h3V4h2',
  'chart-area': 'M2 14V10l4-5 3 3 5-6v12z',
  'chart-hlc-area': 'M2 6 6 4 10 6 14 3V9l-4 3-4-2-4 2z',
  'chart-baseline': 'M2 8h12M2 12 6 4 10 12 14 5',
  'chart-column': 'M3 14 3 9M6 14 6 5M9 14 9 8M12 14 12 3',
  'chart-histogram': 'M2 8h12M4 8 4 4M7 8 7 2M10 8 10 12M13 8 13 14',
  'chart-point-figure': 'M2 2 6 6M6 2 2 6M2 8 6 12M6 8 2 12' + ring(11, 5, 2) + ring(11, 11, 2),
  'chart-kagi': 'M3 13V5h4v6h3V3h3v7',
  'chart-renko': 'M2 10 6 10 6 14 2 14zM6 6 10 6 10 10 6 10zM10 2 14 2 14 6 10 6z',
  'chart-range-bars': 'M3 9 4 9 4 14 3 14zM7 6 8 6 8 11 7 11zM11 3 12 3 12 8 11 8z',
  'chart-line-break': 'M2 9 6 9 6 14 2 14zM6 4 10 4 10 9 6 9zM10 7 14 7 14 11 10 11z',
};

/**
 * The fills of the chrome glyphs' marks, as `DRAWING_TOOL_ACCENTS` is for the
 * tools: each mark is outlined in the glyph's path, and this paints it solid.
 * At 16px a ring of radius 1 is mostly line already, so the fill matters
 * most for the rings of radius 2: the slider knobs, a head, a line's markers.
 */
export const CHROME_ICON_ACCENTS: Readonly<Record<string, string>> = {
  magnet: CHROME_MAGNET_CAPS,
  eye: CHROME_PUPIL,
  paste: CHROME_CLIP,
  settings: CHROME_KNOBS,
  camera: CHROME_LENS,
  'drawing-sync': CHROME_ENDS,
  account: CHROME_HEAD,
  'chart-line-markers': CHROME_MARKERS,
};

/**
 * Chrome glyphs meant to be painted solid. Paths carry no presentation
 * attributes, so the fill is applied by the wrapper (`chromeIconSvg` does it,
 * a host with its own wrapper reads this set) and the registry stays pure.
 */
export const CHROME_ICON_FILLED: ReadonlySet<string> = new Set([
  // A second state of an outline glyph.
  'star-filled', 'pin-filled',
  // Media controls, read as solid shapes by convention.
  'replay', 'play', 'stop', 'step-forward', 'step-back', 'record',
  // Solid marks: a direction, and the moon of the theme and the market.
  'buy', 'sell', 'moon', 'market-closed',
]);

/** The chrome glyph for an id, or `undefined` when there is none. */
export function chromeIcon(id: string): string | undefined {
  return own(CHROME_ICONS, id);
}

/** The filled accent for a chrome glyph, or `undefined` when it has none. */
export function chromeIconAccent(id: string): string | undefined {
  return own(CHROME_ICON_ACCENTS, id);
}

/** Every id the chrome tier covers. */
export function chromeIconIds(): string[] {
  return Object.keys(CHROME_ICONS);
}

/**
 * The chrome glyph for a chart type or a transform, by its id: a registered
 * type (`candlestick`, `point-figure`) or one of the transforms that render
 * as candles (`heikin-ashi`, `renko`, `range-bars`, `line-break`). It is the
 * `chart-<id>` entry of `CHROME_ICONS`, so `chromeIconSvg('chart-' + id)`
 * draws the same picture. `undefined` for a type a host registered itself,
 * which has no glyph until the host draws one.
 */
export function chartTypeIcon(type: string): string | undefined {
  return own(CHROME_ICONS, `chart-${type}`);
}

/** One chart's place in a layout glyph: a cell, and how many rows and columns it spans. */
export interface LayoutIconSlot {
  readonly row: number;
  readonly column: number;
  /** Default 1. */
  readonly rowSpan?: number;
  /** Default 1. */
  readonly columnSpan?: number;
}

/** The most rows or columns a 16px tile shows with a pixel of clear between its lines. */
const LAYOUT_MAX = 4;

/**
 * A chrome glyph for a grid of charts: the frame, split into `rows` by
 * `columns` cells, with the dividers inside a spanning slot left out, so a
 * chart that spans two cells reads as one pane. Cells no slot claims are
 * drawn as their own panes. Without `slots`, every cell is one chart.
 *
 * Derived rather than drawn per layout, so a host's layout picker gets a
 * tile for every layout it offers, uneven ones included, without an entry in
 * this registry for each. The path is on the chrome grid and to its rules
 * (whole units, the 2..14 live area, no presentation attributes), and draws
 * through the chrome attribute bag like any `CHROME_ICONS` value.
 *
 * One to four a side: twelve units split four ways leaves clear space
 * between two lines even at the 2px stroke the set was drawn for, and five
 * would close it up. Throws a
 * `RangeError` for anything else, and for a slot outside the grid or over
 * another. A chart grid takes up to eight a side, so a caller that draws the
 * current layout falls back to the `layout` glyph past four.
 */
export function layoutIconPath(rows: number, columns: number, slots?: readonly LayoutIconSlot[]): string {
  const count = (n: number): boolean => Number.isInteger(n) && n >= 1 && n <= LAYOUT_MAX;
  if (!count(rows) || !count(columns)) {
    throw new RangeError(`openalgo-charts: a layout glyph takes 1..${LAYOUT_MAX} rows and columns, not ${rows}x${columns}`);
  }
  // Each cell's owner: its slot's index, or a negative id of its own when no
  // slot claims it. A divider is drawn wherever two neighbours differ.
  const owner = Array.from({ length: rows * columns }, (_, i) => -1 - i);
  (slots ?? []).forEach((s, k) => {
    const rs = s.rowSpan ?? 1;
    const cs = s.columnSpan ?? 1;
    if (!(Number.isInteger(s.row) && Number.isInteger(s.column) && Number.isInteger(rs) && Number.isInteger(cs)
      && s.row >= 0 && s.column >= 0 && rs >= 1 && cs >= 1 && s.row + rs <= rows && s.column + cs <= columns)) {
      throw new RangeError(`openalgo-charts: layout slot ${k} is outside a ${rows}x${columns} grid`);
    }
    for (let r = s.row; r < s.row + rs; r++) {
      for (let c = s.column; c < s.column + cs; c++) {
        // Inside the grid, checked above.
        if (owner[r * columns + c]! >= 0) throw new RangeError(`openalgo-charts: layout slot ${k} overlaps slot ${owner[r * columns + c]}`);
        owner[r * columns + c] = k;
      }
    }
  });
  // Twelve units divide evenly by one to four, so every line is whole.
  const at = (i: number, n: number): number => 2 + (12 / n) * i;
  let d = 'M2 2h12v12H2z';
  // A divider runs along each inner grid line, broken where a slot spans it.
  const lines = (outer: number, inner: number, split: (o: number, i: number) => boolean,
    seg: (o: number, from: number, to: number) => string): void => {
    for (let o = 1; o < outer; o++) {
      let from = -1;
      for (let i = 0; i <= inner; i++) {
        const cut = i < inner && split(o, i);
        if (cut && from < 0) from = i;
        if (!cut && from >= 0) { d += seg(o, from, i); from = -1; }
      }
    }
  };
  lines(columns, rows, (c, r) => owner[r * columns + c - 1] !== owner[r * columns + c],
    (c, from, to) => `M${at(c, columns)} ${at(from, rows)} ${at(c, columns)} ${at(to, rows)}`);
  lines(rows, columns, (r, c) => owner[(r - 1) * columns + c] !== owner[r * columns + c],
    (r, from, to) => `M${at(from, columns)} ${at(r, rows)} ${at(to, columns)} ${at(r, rows)}`);
  return d;
}
