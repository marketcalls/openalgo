/** Labeled price patterns with shared paint and hit geometry. */
import type { AtLeast, DrawingPoint, DrawingTool, HitContext, ScreenPoint } from './types';
import { composeSettings, FILL_FIELDS, FONT_FIELDS, LINE_FIELDS, SHOW_LABELS_FIELD } from './schema';
import { VALID_COLOR, INVALID_COLOR } from './tool-paint';
import {
  clippedLine, clipPolygon, finitePoint, geometryTool, midpoint,
  type DrawingGeometry, type GeometryLabel, type GeometryPath,
} from './advanced-shared';

interface RatioBand { min: number; max: number }
interface HarmonicBands { ab: RatioBand; bc: RatioBand; cd: RatioBand; ad: RatioBand }
interface PatternSpec {
  id: string;
  name: string;
  labels: readonly string[];
  fill?: boolean;
  ratios?: 'xabcd' | 'abcd';
  harmonic?: HarmonicBands | 'cypher';
  neckline?: readonly [number, number];
}
interface RatioRule {
  name: string;
  value: number | null;
  band?: RatioBand;
  anchor: number;
}

const CYPHER_XC: RatioBand = { min: 1.272, max: 1.414 };
const CYPHER_CD: RatioBand = { min: 0.74, max: 0.83 };
const NAMED = {
  gartley: { ab: { min: 0.55, max: 0.68 }, bc: { min: 0.382, max: 0.886 }, cd: { min: 1.13, max: 1.618 }, ad: { min: 0.74, max: 0.83 } },
  bat: { ab: { min: 0.382, max: 0.5 }, bc: { min: 0.382, max: 0.886 }, cd: { min: 1.618, max: 2.618 }, ad: { min: 0.84, max: 0.92 } },
  butterfly: { ab: { min: 0.74, max: 0.83 }, bc: { min: 0.382, max: 0.886 }, cd: { min: 1.618, max: 2.618 }, ad: { min: 1.272, max: 1.618 } },
  crab: { ab: { min: 0.382, max: 0.618 }, bc: { min: 0.382, max: 0.886 }, cd: { min: 2.618, max: 3.618 }, ad: { min: 1.55, max: 1.69 } },
  shark: { ab: { min: 0.382, max: 0.618 }, bc: { min: 1.13, max: 1.618 }, cd: { min: 1.618, max: 2.24 }, ad: { min: 0.886, max: 1.13 } },
} satisfies Readonly<Record<string, HarmonicBands>>;

const LINE_AND_LABEL_SETTINGS = composeSettings([LINE_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS]);
const FILLED_PATTERN_SETTINGS = composeSettings([LINE_FIELDS, FILL_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS]);
const empty = (): DrawingGeometry => ({ paths: [] });
const leg = (a: ScreenPoint, b: ScreenPoint, c: HitContext): GeometryPath => ({ points: clippedLine(a, b, c.rc) });

function dashedLeg(a: ScreenPoint, b: ScreenPoint, c: HitContext): GeometryPath[] {
  const clipped = clippedLine(a, b, c.rc);
  if (clipped.length < 2) return [];
  const [start, end] = clipped as AtLeast<ScreenPoint, 2>; // by the length check
  const dx = end.x - start.x, dy = end.y - start.y, length = Math.hypot(dx, dy);
  if (!(length > 0) || !Number.isFinite(length)) return [{ points: clipped }];
  const paths: GeometryPath[] = [];
  for (let offset = 0; offset < length; offset += 12) {
    const from = offset / length, to = Math.min(offset + 7, length) / length;
    paths.push({ points: [
      { x: start.x + dx * from, y: start.y + dy * from },
      { x: start.x + dx * to, y: start.y + dy * to },
    ] });
  }
  return paths;
}

function ratio(numerator: number, denominator: number): number | null {
  return Number.isFinite(numerator) && Number.isFinite(denominator) && Math.abs(denominator) >= 1e-9
    ? Math.abs(numerator) / Math.abs(denominator) : null;
}

function priceLength(points: readonly DrawingPoint[], a: number, b: number): number {
  const first = points[a]?.price, second = points[b]?.price;
  return Number.isFinite(first) && Number.isFinite(second) ? Math.abs(second! - first!) : NaN; // both finite numbers
}

function alternatingPriceDirections(points: readonly DrawingPoint[], count: number): boolean {
  if (points.length < count) return false;
  // A harmonic's five anchors, all there by the length check; index < count.
  let previous = points[1]!.price - points[0]!.price;
  if (!Number.isFinite(previous) || previous === 0) return false;
  for (let index = 2; index < count; index++) {
    const current = points[index]!.price - points[index - 1]!.price;
    if (!Number.isFinite(current) || current === 0 || Math.sign(current) === Math.sign(previous)) return false;
    previous = current;
  }
  return true;
}

function genericRules(points: readonly DrawingPoint[], kind: 'xabcd' | 'abcd'): RatioRule[] {
  if (kind === 'xabcd') {
    const xa = priceLength(points, 0, 1), ab = priceLength(points, 1, 2), bc = priceLength(points, 2, 3);
    return [
      { name: 'AB/XA', value: ratio(ab, xa), anchor: 2 },
      { name: 'BC/AB', value: ratio(bc, ab), anchor: 3 },
      { name: 'CD/BC', value: ratio(priceLength(points, 3, 4), bc), anchor: 4 },
    ];
  }
  const ab = priceLength(points, 0, 1), bc = priceLength(points, 1, 2);
  return [
    { name: 'BC/AB', value: ratio(bc, ab), anchor: 2 },
    { name: 'CD/BC', value: ratio(priceLength(points, 2, 3), bc), anchor: 3 },
  ];
}

function harmonicRules(points: readonly DrawingPoint[], bands: HarmonicBands | 'cypher'): RatioRule[] {
  const xa = priceLength(points, 0, 1), ab = priceLength(points, 1, 2);
  if (bands === 'cypher') {
    const xc = priceLength(points, 0, 3);
    return [
      { name: 'AB/XA', value: ratio(ab, xa), band: { min: 0.382, max: 0.618 }, anchor: 2 },
      { name: 'XC/XA', value: ratio(xc, xa), band: CYPHER_XC, anchor: 3 },
      { name: 'CD/XC', value: ratio(priceLength(points, 3, 4), xc), band: CYPHER_CD, anchor: 4 },
    ];
  }
  const bc = priceLength(points, 2, 3);
  return [
    { name: 'AB/XA', value: ratio(ab, xa), band: bands.ab, anchor: 2 },
    { name: 'BC/AB', value: ratio(bc, ab), band: bands.bc, anchor: 3 },
    { name: 'CD/BC', value: ratio(priceLength(points, 3, 4), bc), band: bands.cd, anchor: 4 },
    { name: 'AD/XA', value: ratio(priceLength(points, 1, 4), xa), band: bands.ad, anchor: 4 },
  ];
}

function inBand(rule: RatioRule): boolean {
  return rule.value !== null && rule.band !== undefined && rule.value >= rule.band.min && rule.value <= rule.band.max;
}

function vertexLabels(spec: PatternSpec, points: readonly ScreenPoint[]): GeometryLabel[] {
  return points.flatMap((point, index) => {
    const text = spec.labels[index];
    if (!text || !finitePoint(point)) return [];
    const before = points[index - 1]?.y ?? point.y;
    const after = points[index + 1]?.y ?? point.y;
    const above = point.y <= (before + after) / 2;
    return [{ at: { x: point.x + 4, y: point.y + (above ? -6 : 14) }, text }];
  });
}

function ratioLabels(rules: readonly RatioRule[], points: readonly ScreenPoint[]): GeometryLabel[] {
  const labels: GeometryLabel[] = [];
  for (let index = 0; index < rules.length; index++) {
    const rule = rules[index]!; // index is in range
    if (rule.value === null || !Number.isFinite(rule.value)) continue;
    const end = points[rule.anchor], start = points[Math.max(0, rule.anchor - 1)];
    if (!end || !start || !finitePoint(end) || !finitePoint(start)) continue;
    const checked = rule.band !== undefined;
    const ok = checked && inBand(rule);
    const suffix = checked ? (ok ? ' OK' : ' OUT') : '';
    const at = midpoint(start, end);
    labels.push({
      at: { x: at.x + 6, y: at.y + (index === rules.length - 1 && rule.anchor === rules[index - 1]?.anchor ? 14 : -3) },
      text: `${rule.name} ${rule.value.toFixed(3)}${suffix}`,
      color: checked ? (ok ? VALID_COLOR : INVALID_COLOR) : undefined,
    });
  }
  return labels;
}

/** Intersect an infinite line with a bounded segment. */
function lineSegmentIntersection(lineA: ScreenPoint, lineB: ScreenPoint, a: ScreenPoint, b: ScreenPoint): ScreenPoint | null {
  const dx = lineB.x - lineA.x, dy = lineB.y - lineA.y;
  const ex = b.x - a.x, ey = b.y - a.y;
  const denominator = ex * dy - ey * dx;
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-9) return null;
  const s = ((a.y - lineA.y) * dx - (a.x - lineA.x) * dy) / denominator;
  if (!Number.isFinite(s) || s < 0 || s > 1) return null;
  return { x: a.x + s * ex, y: a.y + s * ey };
}

function patternGeometry(spec: PatternSpec, c: HitContext): DrawingGeometry {
  const points = c.pts.slice(0, spec.labels.length);
  const dataPoints = c.drawing.points.slice(0, spec.labels.length);
  if (points.length < 2) return empty();
  const paths: GeometryPath[] = [];
  if (spec.fill === true) {
    for (const indices of [[0, 1, 2], [2, 3, 4]] as const) {
      const triangle = indices.map(index => points[index]);
      if (triangle.every((point): point is ScreenPoint => point !== undefined && finitePoint(point))) {
        paths.push({ points: clipPolygon(triangle, c.rc), closed: true, fill: true, stroke: false });
      }
    }
  }
  for (let index = 1; index < points.length; index++) paths.push(leg(points[index - 1]!, points[index]!, c)); // in range
  if (spec.neckline !== undefined && points.length >= spec.labels.length) {
    const [leftIndex, rightIndex] = spec.neckline;
    // Every anchor the pattern declares is there, and the neckline names two of them.
    const leftTrough = points[leftIndex]!, rightTrough = points[rightIndex]!;
    const left = lineSegmentIntersection(leftTrough, rightTrough, points[0]!, points[1]!) ?? leftTrough;
    const last = points.length - 1;
    const right = lineSegmentIntersection(leftTrough, rightTrough, points[last - 1]!, points[last]!) ?? rightTrough;
    paths.push(...dashedLeg(left, right, c));
  }
  if (c.drawing.style.showLabels === false) return { paths };
  const labels = vertexLabels(spec, points);
  const rules = spec.harmonic !== undefined ? harmonicRules(dataPoints, spec.harmonic)
    : spec.ratios !== undefined ? genericRules(dataPoints, spec.ratios) : [];
  labels.push(...ratioLabels(rules, points));
  if (spec.harmonic !== undefined && points.length >= spec.labels.length) {
    const topologyValid = alternatingPriceDirections(dataPoints, spec.labels.length);
    const valid = topologyValid && rules.length > 0 && rules.every(inBand);
    const completion = points[spec.labels.length - 1];
    if (completion && finitePoint(completion)) labels.push({
      at: { x: completion.x + 4, y: completion.y + 30 },
      text: `${spec.name}: ${!topologyValid ? 'invalid sequence' : valid ? 'valid' : 'outside range'}`,
      color: valid ? VALID_COLOR : INVALID_COLOR,
    });
  }
  return { paths, labels };
}

function descriptor(spec: PatternSpec): DrawingTool {
  return geometryTool({
    id: spec.id, name: spec.name, points: spec.labels.length,
    defaultStyle: spec.fill === true ? { fill: true, fillOpacity: 0.12, showLabels: true } : { showLabels: true },
    settings: spec.fill === true ? FILLED_PATTERN_SETTINGS : LINE_AND_LABEL_SETTINGS,
  }, c => patternGeometry(spec, c));
}

const XABCD_LABELS = ['X', 'A', 'B', 'C', 'D'] as const;

/** Pattern drawing descriptors. Registration is owned by the draw-tier catalog. */
export const PATTERN_DRAWING_TOOLS: readonly DrawingTool[] = [
  descriptor({ id: 'xabcd-pattern', name: 'XABCD Pattern', labels: XABCD_LABELS, fill: true, ratios: 'xabcd' }),
  descriptor({ id: 'abcd-pattern', name: 'ABCD Pattern', labels: ['A', 'B', 'C', 'D'], ratios: 'abcd' }),
  descriptor({ id: 'elliott-impulse', name: 'Elliott Impulse', labels: ['1', '2', '3', '4', '5'] }),
  descriptor({ id: 'elliott-correction', name: 'Elliott Correction', labels: ['A', 'B', 'C'] }),
  descriptor({ id: 'head-shoulders', name: 'Head and Shoulders', labels: ['', 'LS', '', 'H', '', 'RS', ''], neckline: [2, 4] }),
  descriptor({ id: 'gartley', name: 'Gartley', labels: XABCD_LABELS, fill: true, harmonic: NAMED.gartley }),
  descriptor({ id: 'bat', name: 'Bat', labels: XABCD_LABELS, fill: true, harmonic: NAMED.bat }),
  descriptor({ id: 'butterfly', name: 'Butterfly', labels: XABCD_LABELS, fill: true, harmonic: NAMED.butterfly }),
  descriptor({ id: 'crab', name: 'Crab', labels: XABCD_LABELS, fill: true, harmonic: NAMED.crab }),
  descriptor({ id: 'shark', name: 'Shark', labels: XABCD_LABELS, fill: true, harmonic: NAMED.shark }),
  descriptor({ id: 'cypher', name: 'Cypher', labels: XABCD_LABELS, fill: true, harmonic: 'cypher' }),
];
